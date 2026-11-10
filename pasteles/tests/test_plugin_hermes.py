import asyncio
from datetime import date
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from pasteles.negocio import Pasteleria
from pasteles.pagos import AlmacenPagos, Identidad
from plugin_hermes import HERRAMIENTA_COTIZAR, ServicioPagos, register


def argumentos(**cambios):
    return {"producto_id": "chocolate_12", "asistentes": 10, "fecha": "2026-11-13",
            "modalidad": "entrega", "zona": "centro", "restriccion_alimentaria": "ninguna", **cambios}


class BotFalso:
    def __init__(self):
        self.enviados = []

    async def send_message(self, **datos):
        self.enviados.append(datos)
        return SimpleNamespace(message_id=len(self.enviados))


class ConsultaFalsa:
    def __init__(self, datos, usuario=101, chat=101, mensaje=1, tipo="private"):
        self.data = datos
        self.from_user = SimpleNamespace(id=usuario, is_bot=False)
        self.message = SimpleNamespace(message_id=mensaje, chat=SimpleNamespace(id=chat, type=tipo))
        self.respuestas = []
        self.ediciones = []

    async def answer(self, texto, **kwargs):
        self.respuestas.append((texto, kwargs))

    async def edit_message_text(self, **kwargs):
        self.ediciones.append(kwargs)


@pytest.fixture
def telegram_falso(monkeypatch):
    modulo = ModuleType("telegram")
    modulo.InlineKeyboardButton = lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data)
    modulo.InlineKeyboardMarkup = lambda botones: SimpleNamespace(inline_keyboard=botones)
    extension = ModuleType("telegram.ext")
    errores = ModuleType("telegram.error")
    errores.TelegramError = type("TelegramError", (Exception,), {})
    extension.CallbackQueryHandler = lambda callback, pattern: SimpleNamespace(callback=callback, pattern=pattern)
    extension.MessageHandler = lambda filtros, callback: SimpleNamespace(callback=callback, filtros=filtros)

    class Filtro:
        def __and__(self, otro):
            return self

        def __invert__(self):
            return self

    extension.filters = SimpleNamespace(ALL=Filtro(), TEXT=Filtro())
    monkeypatch.setitem(sys.modules, "telegram", modulo)
    monkeypatch.setitem(sys.modules, "telegram.ext", extension)
    monkeypatch.setitem(sys.modules, "telegram.error", errores)


@pytest.fixture
def contexto(monkeypatch):
    datos = {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "101",
             "HERMES_SESSION_USER_ID": "101", "HERMES_SESSION_CHAT_TYPE": "dm",
             "HERMES_SESSION_ID": "sesion-a", "HERMES_SESSION_KEY": "telegram:101"}
    modulo = ModuleType("gateway.session_context")
    modulo.bound_session_key = lambda: datos.get("HERMES_SESSION_KEY", "")
    modulo.get_session_env = lambda nombre: datos.get(nombre, "")
    monkeypatch.setitem(sys.modules, "gateway", ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.session_context", modulo)
    return datos


@pytest.fixture
def servicio(tmp_path, telegram_falso):
    almacen = AlmacenPagos(tmp_path / "pagos.db", Pasteleria(hoy=date(2026, 11, 9)), lambda: 1000)
    servicio = ServicioPagos(almacen, frozenset({"101", "202"}))
    handlers = []
    servicio.conectar(SimpleNamespace(bot=BotFalso(), add_handler=handlers.append), None)
    return servicio


def origen(**cambios):
    return SimpleNamespace(platform=SimpleNamespace(value="telegram"), chat_id="101", user_id="101",
                           chat_type="dm", is_bot=False, **cambios)


def capturar(servicio, contexto, llamada="llamada-a", **cambios):
    servicio.antes_herramienta(HERRAMIENTA_COTIZAR, argumentos(), session_id="sesion-a", tool_call_id=llamada)
    servicio.despues_herramienta(HERRAMIENTA_COTIZAR, argumentos(**cambios), result="PRECIOS FALSOS $1",
                                 session_id="sesion-a", tool_call_id=llamada, status="ok")


def pagar(servicio, **cambios):
    parametros = {"source": origen(), "platform": "telegram", "session_id": "sesion-a", "session_key": "telegram:101"}
    return asyncio.run(servicio.pagar("", **{**parametros, **cambios}))


def test_plugin_captura_recalcula_envia_botones_y_cierra_sin_modelo(servicio, contexto):
    capturar(servicio, contexto)
    assert pagar(servicio) is None
    tarjeta = servicio.aplicacion.bot.enviados[0]
    assert tarjeta["chat_id"] == 101
    assert "$710.00 MXN" in tarjeta["text"] and "SIMULACIÓN" in tarjeta["text"]
    botones = tarjeta["reply_markup"].inline_keyboard
    assert len(botones) == 3
    consulta = ConsultaFalsa(botones[0][0].callback_data)
    asyncio.run(servicio.boton(SimpleNamespace(callback_query=consulta), None))
    assert "aprobado" in consulta.ediciones[0]["text"]
    assert consulta.ediciones[0]["reply_markup"] is None
    # Cancelar después de aprobar devuelve el mismo cierre; no revierte ni duplica.
    consulta2 = ConsultaFalsa(botones[2][0].callback_data)
    asyncio.run(servicio.boton(SimpleNamespace(callback_query=consulta2), None))
    assert "aprobado" in consulta2.ediciones[0]["text"]


@pytest.mark.parametrize(("campo", "valor"), [
    ("HERMES_SESSION_KEY", ""), ("HERMES_SESSION_PLATFORM", "cli"),
    ("HERMES_SESSION_CHAT_TYPE", "group"), ("HERMES_SESSION_USER_ID", "999"),
    ("HERMES_SESSION_ID", "otra-sesion"),
])
def test_hook_sin_contexto_privado_autorizado_no_guarda(servicio, contexto, campo, valor):
    contexto[campo] = valor
    capturar(servicio, contexto)
    assert "cotización completa" in pagar(servicio)


@pytest.mark.parametrize("cambios", [{"source": None}, {"platform": "cli"}, {"session_key": ""}])
def test_comando_no_acepta_identidad_inexistente(servicio, contexto, cambios):
    capturar(servicio, contexto)
    assert isinstance(pagar(servicio, **cambios), str)
    assert not servicio.aplicacion.bot.enviados


@pytest.mark.parametrize("cambios", [{"usuario": 202}, {"chat": 202}, {"mensaje": 99}, {"tipo": "group"}])
def test_botones_no_se_comparten_entre_cuentas_o_mensajes(servicio, contexto, cambios):
    capturar(servicio, contexto)
    pagar(servicio)
    token = servicio.aplicacion.bot.enviados[0]["reply_markup"].inline_keyboard[0][0].callback_data
    consulta = ConsultaFalsa(token, **cambios)
    asyncio.run(servicio.boton(SimpleNamespace(callback_query=consulta), None))
    assert consulta.respuestas[0][1]["show_alert"] is True
    assert not consulta.ediciones
    assert servicio.almacen.consultar(Identidad("101", "101", "sesion-a", "telegram:101"))["estado"] == "pendiente"


def test_new_y_cotizacion_invalida_invalidan_tarjeta(servicio, contexto):
    capturar(servicio, contexto)
    pagar(servicio)
    capturar(servicio, contexto, "llamada-b", restriccion_alimentaria="alergia")
    assert "vigente" in pagar(servicio)
    capturar(servicio, contexto, "llamada-c")
    servicio.reiniciar(old_session_id="sesion-a", platform="telegram")
    assert "vigente" in pagar(servicio)
    capturar(servicio, contexto, "llamada-tardia")
    assert "vigente" in pagar(servicio)


def test_registro_utiliza_directorio_compartido_y_no_agrega_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "101,202")
    monkeypatch.setenv("PASTELES_DATOS", str(tmp_path / "runtime"))
    hooks, comandos, plataformas = {}, {}, {}
    ctx = SimpleNamespace(state=SimpleNamespace(data_dir=tmp_path / "default"),
                          register_hook=lambda nombre, funcion: hooks.update({nombre: funcion}),
                          register_command=lambda nombre, funcion, **kw: comandos.update({nombre: funcion}),
                          register_platform_handler=lambda nombre, funcion: plataformas.update({nombre: funcion}))
    register(ctx)
    assert set(hooks) == {"pre_tool_call", "post_tool_call", "on_session_reset"}
    assert set(comandos) == {"pagar", "pedido"}
    assert set(plataformas) == {"telegram"}
    assert (tmp_path / "runtime/pagos.sqlite3").exists()
    assert not (tmp_path / "default").exists()


@pytest.mark.parametrize("usuarios", ["", "*", "101,persona", "0"])
def test_no_se_activa_sin_lista_explicita(tmp_path, monkeypatch, usuarios):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", usuarios)
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USERS"):
        register(SimpleNamespace(state=SimpleNamespace(data_dir=tmp_path)))


def test_audio_no_llega_al_modelo(servicio):
    textos = []

    async def responder(texto):
        textos.append(texto)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=101, is_bot=False),
                             effective_chat=SimpleNamespace(id=101, type="private"),
                             effective_message=SimpleNamespace(reply_text=responder))
    asyncio.run(servicio.solo_texto(update, None))
    assert len(textos) == 1 and "texto" in textos[0]


def test_tarjeta_ya_editada_no_duplica_decision_ni_falla(servicio, contexto):
    from telegram.error import TelegramError

    capturar(servicio, contexto)
    pagar(servicio)
    datos = servicio.aplicacion.bot.enviados[0]["reply_markup"].inline_keyboard[0][0].callback_data
    consulta = ConsultaFalsa(datos)

    async def edicion_fallida(**kwargs):
        raise TelegramError("Message is not modified")

    consulta.edit_message_text = edicion_fallida
    asyncio.run(servicio.boton(SimpleNamespace(callback_query=consulta), None))
    assert servicio.almacen.consultar(Identidad("101", "101", "sesion-a", "telegram:101"))["estado"] == "aprobado"
