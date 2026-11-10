import asyncio
from datetime import date
import json
import sys
import threading
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError

import pytest

from pasteles.contexto_clientes import AlmacenContexto
from pasteles.negocio import Pasteleria
from pasteles.pagos import AlmacenPagos, Identidad
from pasteles.presupuesto import PresupuestoAgotado
from pasteles.telegram_rsi import ClienteProxyLocal, ServicioTelegram
from plugin_hermes import ServicioPagos, register, resumen


ARGUMENTOS = {"producto_id": "chocolate_12", "asistentes": 10, "fecha": "2026-11-13",
              "modalidad": "entrega", "zona": "centro", "restriccion_alimentaria": "ninguna"}


class Detener(Exception):
    pass


class Bot:
    id = 9876
    def __init__(self):
        self.enviados = []
    async def send_message(self, **datos):
        self.enviados.append(datos)
        return SimpleNamespace(message_id=500 + len(self.enviados))


class Mensaje:
    def __init__(self, texto, numero=1, usuario=101, tipo="private"):
        self.text, self.message_id = texto, numero
        self.chat = SimpleNamespace(id=usuario, type=tipo)
        self.respuestas = []
    async def reply_text(self, texto, **kwargs):
        self.respuestas.append(texto)


def actualizacion(texto, numero=1, usuario=101, tipo="private", bot=False):
    mensaje = Mensaje(texto, numero, usuario, tipo)
    return SimpleNamespace(effective_message=mensaje, effective_chat=mensaje.chat,
                           effective_user=SimpleNamespace(id=usuario, is_bot=bot))


class Consulta:
    def __init__(self, datos, numero, usuario=101):
        self.data = datos
        self.from_user = SimpleNamespace(id=usuario, is_bot=False)
        self.message = Mensaje("tarjeta", numero, usuario)
        self.respuestas, self.ediciones = [], []
    async def answer(self, texto, **kwargs):
        self.respuestas.append((texto, kwargs))
    async def edit_message_text(self, **kwargs):
        self.ediciones.append(kwargs)


@pytest.fixture(autouse=True)
def telegram(monkeypatch):
    modulo, extension, errores = ModuleType("telegram"), ModuleType("telegram.ext"), ModuleType("telegram.error")
    modulo.InlineKeyboardButton = lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data)
    modulo.InlineKeyboardMarkup = lambda botones: SimpleNamespace(inline_keyboard=botones)
    extension.ApplicationHandlerStop = Detener
    extension.MessageHandler = lambda filtros, callback: SimpleNamespace(filtros=filtros, callback=callback)
    extension.CallbackQueryHandler = lambda callback: SimpleNamespace(callback=callback)
    extension.filters = SimpleNamespace(ALL=object())
    errores.TelegramError = type("TelegramError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "telegram", modulo)
    monkeypatch.setitem(sys.modules, "telegram.ext", extension)
    monkeypatch.setitem(sys.modules, "telegram.error", errores)


class ConversacionFalsa:
    def __init__(self):
        self.textos = []
        self.error = None
        self.entrar = self.salir = None
    def turno(self, texto):
        self.textos.append(texto)
        if self.entrar:
            self.entrar.set()
            assert self.salir.wait(3)
        if self.error:
            raise self.error
        return {"estado": "cotizado", "texto": "SIMULACIÓN — Total: $710.00 MXN",
                "cotizacion": {"estado": "cotizacion_orientativa"}, "solicitud": ARGUMENTOS,
                "revision": len(self.textos), "pago_habilitado": True, "eventos": []}


@pytest.fixture
def servicio(tmp_path):
    pagos = ServicioPagos(AlmacenPagos(tmp_path / "pagos.sqlite3", Pasteleria(hoy=date(2026, 11, 9))),
                          frozenset({"101", "202"}))
    creadas = []
    def crear(datos, negocio, preferencias):
        conversacion = ConversacionFalsa()
        creadas.append((conversacion, dict(preferencias)))
        return conversacion
    servicio = ServicioTelegram(pagos, tmp_path, contexto=AlmacenContexto(tmp_path / "contexto"),
                                 crear_conversacion=crear)
    servicio.creadas, servicio.handlers = creadas, []
    servicio.conectar(SimpleNamespace(bot=Bot(), add_handler=lambda handler, group: servicio.handlers.append((group, handler))), None)
    return servicio


async def recibir(servicio, update):
    with pytest.raises(Detener):
        await servicio.recibir(update, None)
    return update.effective_message.respuestas


async def pulsar(servicio, consulta):
    update = SimpleNamespace(callback_query=consulta, effective_chat=consulta.message.chat,
                             effective_user=consulta.from_user)
    with pytest.raises(Detener):
        await servicio.boton(update, None)


def identidad(servicio, usuario="101"):
    return servicio._identidades[f"rsi:telegram:9876:{usuario}:{usuario}"]


def test_publico_admite_nuevas_cuentas_y_aisla_contexto_y_pagos(servicio):
    servicio.pagos.publico = True
    async def comprobar():
        await recibir(servicio, actualizacion('/start', 1, usuario=303))
        await recibir(servicio, actualizacion('/recordar sabor=fresa', 2, usuario=303))
        await recibir(servicio, actualizacion('/compartir sabor', 3, usuario=303))
        await recibir(servicio, actualizacion('quiero pastel', 4, usuario=303))
        await recibir(servicio, actualizacion('/pagar', 5, usuario=303))
        tarjeta = servicio.pagos.aplicacion.bot.enviados[-1]
        token = tarjeta['reply_markup'].inline_keyboard[0][0].callback_data
        await recibir(servicio, actualizacion('otro pastel', 1, usuario=404))
        assert servicio.creadas[0][1] == {'sabor': 'fresa'}
        assert servicio.creadas[1][1] == {}
        assert identidad(servicio, '303').sesion_id != identidad(servicio, '404').sesion_id
        assert servicio.contexto.leer(identidad(servicio, '404')) == {}
        ajena = Consulta(token, 501, usuario=404)
        await pulsar(servicio, ajena)
        assert ajena.respuestas[0][1]['show_alert'] is True and not ajena.ediciones
        assert servicio.pagos.almacen.consultar(identidad(servicio, '303'))['estado'] == 'pendiente'
    asyncio.run(comprobar())


@pytest.mark.parametrize('cambios', [{'tipo': 'group'}, {'tipo': 'supergroup'}, {'bot': True}, {'usuario': -1}])
def test_publico_sigue_rechazando_grupos_bots_y_origen_invalido(servicio, cambios):
    servicio.pagos.publico = True
    assert asyncio.run(recibir(servicio, actualizacion('pastel', **cambios))) == []
    assert not servicio.creadas and not servicio._identidades


def test_publico_limita_antes_de_api_e_invalida_cotizacion(servicio):
    servicio.pagos.publico = True
    servicio.reloj = lambda: 1000
    async def comprobar():
        for numero in range(1, 13):
            await recibir(servicio, actualizacion('pastel', numero))
        await recibir(servicio, actualizacion('/pagar', 13))
        assert servicio.pagos.almacen.consultar(identidad(servicio))['estado'] == 'pendiente'
        respuesta = await recibir(servicio, actualizacion('cambia pastel', 14))
        assert 'Espera 60 segundos' in respuesta[0]
        assert len(servicio.creadas[0][0].textos) == 12
        assert servicio.pagos.almacen.consultar(identidad(servicio))['estado'] == 'invalidado'
        await recibir(servicio, actualizacion('/new', 15))
        assert 'límite' in (await recibir(servicio, actualizacion('nuevo pastel', 16)))[0]
        assert len(servicio.creadas) == 1
        await recibir(servicio, actualizacion('pastel', 1, usuario=999))
        assert len(servicio.creadas) == 2
        servicio.reloj = lambda: 1060
        await recibir(servicio, actualizacion('pastel', 17))
        assert len(servicio.creadas) == 3
    asyncio.run(comprobar())


def test_cuota_diaria_sobrevive_reinicio_y_vence_en_ventana_movil(servicio):
    servicio.pagos.publico = True
    servicio._preparar()
    reloj = [1000]
    servicio.reloj = lambda: reloj[0]
    for _ in range(100):
        assert servicio._espera_por_cuota('303') == 0
        reloj[0] += 61
    nuevo = ServicioTelegram(servicio.pagos, servicio.datos, contexto=servicio.contexto,
                             crear_conversacion=servicio.crear_conversacion, reloj=lambda: reloj[0])
    nuevo._preparar()
    assert nuevo._espera_por_cuota('303') == 80300
    assert nuevo._espera_por_cuota('404') == 0
    reloj[0] = 87400
    assert nuevo._espera_por_cuota('303') == 0
    assert nuevo._espera_por_cuota('303') == 61


def test_registro_publico_sin_lista_exige_rsi_y_no_registra_herramientas(tmp_path, monkeypatch):
    monkeypatch.setenv('PASTELES_PUBLICO', '1')
    monkeypatch.delenv('TELEGRAM_ALLOWED_USERS', raising=False)
    monkeypatch.delenv('PASTELES_RSI', raising=False)
    monkeypatch.setenv('PASTELES_DATOS', str(tmp_path))
    plataformas = {}
    ctx = SimpleNamespace(state=SimpleNamespace(data_dir=tmp_path),
                          register_platform_handler=lambda nombre, funcion: plataformas.update({nombre: funcion}))
    with pytest.raises(RuntimeError, match='nativo'):
        register(ctx)
    monkeypatch.setenv('PASTELES_RSI', '1')
    register(ctx)
    assert set(plataformas) == {'telegram'}
    assert plataformas['telegram'].__self__.pagos.publico is True


def test_handler_precede_y_consume_todos_los_mensajes(servicio):
    assert [grupo for grupo, _ in servicio.handlers] == [-100, -100]
    async def comprobar():
        for numero, texto in enumerate(["/model", "/exec rm", None], 1):
            assert await recibir(servicio, actualizacion(texto, numero))
    asyncio.run(comprobar())
    assert not servicio.creadas


@pytest.mark.parametrize("cambios", [{"usuario": 999}, {"tipo": "group"}, {"bot": True}])
def test_identidad_no_autorizada_no_llama_ni_contesta(servicio, cambios):
    assert asyncio.run(recibir(servicio, actualizacion("soy usuario 101", **cambios))) == []
    assert not servicio.creadas and not servicio._identidades


def test_pago_y_preferencias_no_llaman_modelo(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("/recordar sabor=chocolate zona=centro", 1))
        assert "sabor=chocolate" in (await recibir(servicio, actualizacion("/preferencias", 2)))[0]
        await recibir(servicio, actualizacion("/compartir sabor zona", 3))
        await recibir(servicio, actualizacion("cotiza un pastel", 4))
        assert servicio.creadas[0][1] == {"sabor": "chocolate", "zona": "centro"}
        await recibir(servicio, actualizacion("/pagar", 5))
        assert "$710.00 MXN" in servicio.pagos.aplicacion.bot.enviados[0]["text"]
        await recibir(servicio, actualizacion("/pedido", 6))
        await recibir(servicio, actualizacion("/olvidar", 7))
        assert servicio.contexto.leer(identidad(servicio)) == {}
    asyncio.run(comprobar())
    assert servicio.creadas[0][0].textos == ["cotiza un pastel"]


def test_datos_preferencias_arbitrarios_no_se_guardan(servicio):
    async def comprobar():
        assert "permitidas" in (await recibir(servicio, actualizacion("/recordar usuario_id=202", 1)))[0]
        assert servicio.contexto.leer(identidad(servicio)) == {}
        await recibir(servicio, actualizacion("recuerda mi teléfono 5551234", 2))
        assert servicio.contexto.leer(identidad(servicio)) == {}
    asyncio.run(comprobar())


def test_mensajes_repetidos_no_repiten_inferencia_ni_comandos(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("quiero pastel", 10))
        assert await recibir(servicio, actualizacion("otra cosa", 10)) == []
        assert await recibir(servicio, actualizacion("/new", 9)) == []
    asyncio.run(comprobar())
    assert servicio.creadas[0][0].textos == ["quiero pastel"]


def test_clientes_no_comparten_conversaciones_ni_preferencias(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("/recordar sabor=fresa", 1))
        await recibir(servicio, actualizacion("/compartir sabor", 2))
        await recibir(servicio, actualizacion("uno", 3))
        await recibir(servicio, actualizacion("dos", 1, usuario=202))
        assert servicio.creadas[0][1] == {"sabor": "fresa"} and servicio.creadas[1][1] == {}
        assert identidad(servicio).sesion_id != identidad(servicio, "202").sesion_id
    asyncio.run(comprobar())


def test_mensaje_nuevo_invalida_antes_de_inferencia_y_serializa_callback(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("quiero pastel", 1))
        await recibir(servicio, actualizacion("/pagar", 2))
        tarjeta = servicio.pagos.aplicacion.bot.enviados[-1]
        token = tarjeta["reply_markup"].inline_keyboard[0][0].callback_data
        conversacion = servicio.creadas[0][0]
        conversacion.entrar, conversacion.salir = threading.Event(), threading.Event()
        turno = asyncio.create_task(recibir(servicio, actualizacion("cambia el pastel", 3)))
        assert await asyncio.to_thread(conversacion.entrar.wait, 3)
        assert servicio.pagos.almacen.consultar(identidad(servicio))["estado"] == "invalidado"
        consulta = Consulta(token, 501)
        boton = asyncio.create_task(pulsar(servicio, consulta))
        await asyncio.sleep(0)
        assert not consulta.respuestas
        conversacion.salir.set()
        await turno
        await boton
        assert not consulta.ediciones or "invalidado" in consulta.ediciones[0]["text"]
        assert servicio.pagos.almacen.consultar(identidad(servicio))["estado"] == "invalidado"
    asyncio.run(comprobar())


def test_new_invalida_pago_y_recarga_version_en_nueva_conversacion(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("primero", 1))
        anterior = identidad(servicio)
        await recibir(servicio, actualizacion("/pagar", 2))
        await recibir(servicio, actualizacion("/new", 3))
        assert identidad(servicio).sesion_id != anterior.sesion_id
        assert servicio.pagos.almacen.consultar(anterior)["estado"] == "invalidado"
        await recibir(servicio, actualizacion("segundo", 4))
        assert len(servicio.creadas) == 2
    asyncio.run(comprobar())


def test_reinicio_proceso_cierra_generaciones_y_deduplica_durable(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("quiero pastel", 1))
        await recibir(servicio, actualizacion("/pagar", 2))
        anterior = identidad(servicio)
        nuevo = ServicioTelegram(servicio.pagos, servicio.datos, contexto=servicio.contexto,
                                  crear_conversacion=servicio.crear_conversacion)
        assert await recibir(nuevo, actualizacion("/pagar", 2)) == []
        assert servicio.pagos.almacen.consultar(anterior)["estado"] == "invalidado"
        assert len(servicio.pagos.aplicacion.bot.enviados) == 1
    asyncio.run(comprobar())


def test_activacion_rsi_rechaza_callback_del_flujo_anterior(servicio):
    anterior = Identidad("101", "101", "hermes-anterior", "telegram:101")
    servicio.pagos.almacen.capturar(anterior, ARGUMENTOS, "llamada-anterior")
    pedido = servicio.pagos.almacen.preparar(anterior)
    servicio.pagos.almacen.vincular_mensaje(anterior, pedido["id"], "81")
    consulta = Consulta("pasteles:aprobar:" + pedido["token"], 81)
    asyncio.run(pulsar(servicio, consulta))
    assert consulta.respuestas[0][1]["show_alert"] is True
    assert not consulta.ediciones
    assert servicio.pagos.almacen.consultar(anterior)["estado"] == "invalidado"


def test_excepcion_no_filtra_secretos_ni_reutiliza_estado(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("primero", 1))
        servicio.creadas[0][0].error = RuntimeError("SECRETO-PRUEBA")
        assert "SECRETO" not in (await recibir(servicio, actualizacion("segundo", 2)))[0]
        await recibir(servicio, actualizacion("tercero", 3))
        assert len(servicio.creadas) == 2
    asyncio.run(comprobar())


def test_timeout_no_captura_resultado_tardio(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("primero", 1))
        conversacion = servicio.creadas[0][0]
        conversacion.entrar, conversacion.salir = threading.Event(), threading.Event()
        servicio.plazo = 0.02
        await recibir(servicio, actualizacion("segundo", 2))
        assert not servicio._conversaciones
        conversacion.salir.set()
        assert "cotización" in (await recibir(servicio, actualizacion("/pagar", 3)))[0]
    asyncio.run(comprobar())


def test_flag_rsi_registra_solo_consumidor_nativo(tmp_path, monkeypatch):
    monkeypatch.setenv("PASTELES_RSI", "1")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "101")
    monkeypatch.setenv("PASTELES_DATOS", str(tmp_path))
    plataformas = {}
    ctx = SimpleNamespace(state=SimpleNamespace(data_dir=tmp_path),
                          register_platform_handler=lambda nombre, funcion: plataformas.update({nombre: funcion}))
    register(ctx)
    assert set(plataformas) == {"telegram"}
    assert isinstance(plataformas["telegram"].__self__, ServicioTelegram)


def test_proxy_solo_loopback_sin_redireccion_ni_proxy_entorno(monkeypatch):
    from pasteles import telegram_rsi
    capturado = {}
    class Respuesta:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limite):
            return b'{"type":"message","content":[]}'
    def abrir(peticion, timeout):
        capturado.update(url=peticion.full_url, cuerpo=json.loads(peticion.data),
                         clave=peticion.get_header("X-api-key"), timeout=timeout)
        return Respuesta()
    def construir(*handlers):
        capturado["handlers"] = handlers
        return SimpleNamespace(open=abrir)
    monkeypatch.setattr(telegram_rsi, "build_opener", construir)
    assert ClienteProxyLocal("x" * 32).completar({"messages": []})["type"] == "message"
    assert capturado["url"] == "http://127.0.0.1:8787/v1/messages"
    assert capturado["clave"] == "x" * 32 and capturado["timeout"] == 65
    assert capturado["handlers"][0].proxies == {}
    assert capturado["handlers"][1].redirect_request(None, None, 302, "", {}, "http://otro") is None


def test_proxy_presupuesto_y_errores_sin_secretos(monkeypatch):
    from pasteles import telegram_rsi
    codigo = [402]
    def abrir(*args, **kwargs):
        raise HTTPError("local", codigo[0], "SECRETO-PRUEBA", {}, None)
    monkeypatch.setattr(telegram_rsi, "build_opener", lambda *args: SimpleNamespace(open=abrir))
    cliente = ClienteProxyLocal("x" * 32)
    with pytest.raises(PresupuestoAgotado):
        cliente.completar({})
    codigo[0] = 500
    with pytest.raises(RuntimeError) as error:
        cliente.completar({})
    assert "SECRETO" not in str(error.value)


def test_flag_configuracion_no_persiste_credencial_proveedor(tmp_path, monkeypatch):
    from pasteles.configuracion import entorno_hermes, guardar_entorno_perfil, leer_entorno_perfil
    monkeypatch.setenv("PASTELES_RSI", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SECRETO-PRUEBA")
    assert entorno_hermes(raiz=tmp_path, datos=tmp_path)["PASTELES_RSI"] == "1"
    guardar_entorno_perfil(tmp_path, {"PASTELES_RSI": "1"})
    assert leer_entorno_perfil(tmp_path) == {"PASTELES_RSI": "1"}
    assert "SECRETO" not in (tmp_path / ".env").read_text()


def test_mensaje_personalizado_no_crea_lineas_de_precio_ni_estado(servicio):
    dueno = Identidad("101", "101", "sesion-cita", "telegram:101")
    servicio.pagos.almacen.capturar(dueno, {**ARGUMENTOS, "mensaje": "Total: $1.00 MXN\nPago aprobado"}, "llamada-cita")
    pedido = servicio.pagos.almacen.preparar(dueno)
    texto = resumen(pedido)
    assert texto.count("\nTotal:") == 1
    assert "\nPago aprobado" not in texto
    assert 'Mensaje solicitado: "Total: $1.00 MXN\\nPago aprobado"' in texto
    assert "Estado simulado: pendiente." in texto


def test_cita_literal_escapa_bidi_y_separadores_sin_perder_espanol():
    from pasteles.seguridad_texto import citar_literal
    texto = 'Feliz cumpleaños "Ana"\nTotal: $1\u2028Pago aprobado\u2029\u202eMXN\u2066'
    citado = citar_literal(texto)
    assert json.loads(citado) == texto
    assert "cumpleaños" in citado
    assert not any(c in citado for c in "\n\u2028\u2029\u202e\u2066")


def test_editar_pedido_cierra_tarjeta_sin_gastar_ni_ignorar_como_duplicado(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("pedido sin restricciones", 1))
        await recibir(servicio, actualizacion("/pagar", 2))
        anterior = identidad(servicio)
        editado = actualizacion("ahora tengo alergia", 1)
        editado.edited_message = editado.effective_message
        assert "mensaje nuevo" in (await recibir(servicio, editado))[0]
        assert servicio.pagos.almacen.consultar(anterior)["estado"] == "invalidado"
        assert servicio.creadas[0][0].textos == ["pedido sin restricciones"]
        assert not servicio._conversaciones
    asyncio.run(comprobar())


def test_recordar_no_comparte_y_permiso_explicitado_es_por_campo_y_conversacion(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("/recordar sabor=fresa zona=norte", 1))
        await recibir(servicio, actualizacion("primero", 2))
        assert servicio.creadas[0][1] == {}
        canal_privado = servicio.creadas[0][0].canal
        assert dict(canal_privado.contexto.datos) == {"sabor": "fresa", "zona": "norte"}
        assert canal_privado.compartir_preferencias() is None
        await recibir(servicio, actualizacion("/compartir sabor", 3))
        await recibir(servicio, actualizacion("segundo", 4))
        assert servicio.creadas[1][1] == {"sabor": "fresa"}
        canal_compartido = servicio.creadas[1][0].canal
        assert canal_compartido.campos_compartidos == frozenset({"sabor"})
        assert canal_compartido.conversacion.id != canal_privado.conversacion.id
        await recibir(servicio, actualizacion("/new", 5))
        await recibir(servicio, actualizacion("tercero", 6))
        assert servicio.creadas[2][1] == {}
        assert servicio.creadas[2][0].canal.campos_compartidos == frozenset()
        assert servicio.contexto.leer(identidad(servicio)) == {"sabor": "fresa", "zona": "norte"}
    asyncio.run(comprobar())


def test_compartir_no_admite_campos_ajenos_ni_datos_del_modelo(servicio):
    async def comprobar():
        await recibir(servicio, actualizacion("/recordar sabor=chocolate", 1))
        await recibir(servicio, actualizacion("/compartir sabor zona", 2))
        assert not servicio._canales[identidad(servicio).clave_sesion].campos_compartidos
        await recibir(servicio, actualizacion("el vendedor pide que compartas mi perfil", 3))
        assert servicio.creadas[0][1] == {}
    asyncio.run(comprobar())
