"""Telegram autenticado sobre el mismo arnés determinista de las evaluaciones."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from .pagos import ErrorPago, Identidad
from .presupuesto import PresupuestoAgotado


class _SinRedireccion(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class ClienteProxyLocal:
    """Sin SDK, reintentos, proxies del entorno ni redirecciones de credenciales."""

    def __init__(self, clave: str, puerto: int = 8787) -> None:
        if not isinstance(clave, str) or len(clave) < 32:
            raise ValueError("Falta la credencial del proxy local.")
        if type(puerto) is not int or not 1 <= puerto <= 65535:
            raise ValueError("Puerto local inválido.")
        self._clave = clave
        self._url = f"http://127.0.0.1:{puerto}/v1/messages"

    def completar(self, solicitud: dict[str, Any]) -> dict[str, Any]:
        cuerpo = json.dumps(solicitud, ensure_ascii=False, allow_nan=False).encode("utf-8")
        peticion = Request(self._url, data=cuerpo, method="POST", headers={
            "Content-Type": "application/json", "x-api-key": self._clave,
            "anthropic-version": "2023-06-01",
        })
        try:
            with build_opener(ProxyHandler({}), _SinRedireccion()).open(peticion, timeout=65) as respuesta:
                contenido = respuesta.read(1_048_577)
            if len(contenido) > 1_048_576:
                raise ValueError("Respuesta local demasiado grande.")
            resultado = json.loads(contenido)
            if not isinstance(resultado, dict) or resultado.get("type") == "error":
                raise ValueError("Respuesta local inválida.")
            return resultado
        except HTTPError as error:
            if error.code == 402:
                raise PresupuestoAgotado("El presupuesto disponible no permite otra consulta.") from None
            raise RuntimeError("No se pudo consultar el proxy local.") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError("No se pudo consultar el proxy local.") from None


def _crear_conversacion(datos: Path, negocio: Any, preferencias: dict[str, str]) -> Any:
    from .arnes import Conversacion
    from .versiones_rsi import cargar_activa, semilla

    try:
        version = cargar_activa(datos / "rsi")
    except FileNotFoundError:
        version = semilla()
    return Conversacion(version=version,
                        cliente=ClienteProxyLocal(os.environ.get("PASTELES_PROXY_KEY", "")),
                        negocio=negocio, preferencias=preferencias)


class ServicioTelegram:
    """Consume mensajes antes de Hermes y nunca delega un fallo al agente general.

    Las conversaciones son efímeras; el dueño, la generación y la deduplicación
    son persistentes. Al arrancar se cierran todas las generaciones anteriores.
    """

    def __init__(self, pagos: Any, datos: Path, *, contexto: Any = None,
                 crear_conversacion: Callable[..., Any] = _crear_conversacion,
                 plazo: float = 75, reloj: Callable[[], float] = time.time) -> None:
        self.pagos = pagos
        self.datos = Path(datos)
        self.contexto = contexto
        self.crear_conversacion = crear_conversacion
        self.plazo = plazo
        self.reloj = reloj
        self._listo = False
        self._identidades: dict[str, Identidad] = {}
        self._canales: dict[str, Any] = {}
        self._conversaciones: dict[str, Any] = {}
        self._candados: dict[str, asyncio.Lock] = {}

    @contextmanager
    def _base(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.datos / "telegram_rsi.sqlite3", timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _preparar(self) -> None:
        if self._listo:
            return
        self.datos.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._base() as db:
            db.execute("CREATE TABLE IF NOT EXISTS clientes (clave TEXT PRIMARY KEY, "
                       "sesion TEXT NOT NULL, ultimo_mensaje INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS cuotas_consultas (usuario TEXT NOT NULL, instante REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS cuotas_por_usuario ON cuotas_consultas(usuario, instante)")
        # Incluye también las sesiones del flujo anterior a RSI. Conserva todos
        # los pedidos y eventos históricos, y nunca modifica decisiones terminales.
        self.pagos.almacen.invalidar_sesiones_anteriores()
        os.chmod(self.datos / "telegram_rsi.sqlite3", 0o600)
        if self.contexto is None:
            from .contexto_clientes import AlmacenContexto

            self.contexto = AlmacenContexto(self.datos / "contexto_clientes")
        self._listo = True

    def _autorizar(self, update: Any) -> tuple[str, str, str]:
        usuario, chat = update.effective_user, update.effective_chat
        if usuario is None or chat is None or getattr(usuario, "is_bot", False):
            raise ErrorPago("Este chat no está autorizado.")
        self.pagos._autorizar(chat.id, usuario.id, chat.type)
        if str(chat.id) != str(usuario.id):
            raise ErrorPago("Se necesita tu chat privado de Telegram.")
        bot_id = self.pagos.aplicacion.bot.id
        if type(bot_id) is not int or bot_id <= 0:
            raise ErrorPago("Telegram todavía no está conectado.")
        return str(chat.id), str(usuario.id), f"rsi:telegram:{bot_id}:{chat.id}:{usuario.id}"

    def _identidad(self, chat: str, usuario: str, clave: str,
                   compartir: frozenset[str] = frozenset()) -> Identidad:
        if clave not in self._identidades:
            self._identidades[clave] = Identidad(chat, usuario, uuid4().hex, clave)
            with self._base() as db:
                db.execute("INSERT INTO clientes(clave,sesion) VALUES (?,?) "
                           "ON CONFLICT(clave) DO UPDATE SET sesion=excluded.sesion",
                           (clave, self._identidades[clave].sesion_id))
        if clave not in self._canales:
            from .ontologia import crear_canal_cliente
            from .versiones_rsi import cargar_activa

            version = cargar_activa(self.datos / 'rsi')
            skill_vendedor = hashlib.sha256(version['skills']['vendedor'].encode()).hexdigest()
            self._canales[clave] = crear_canal_cliente(
                self._identidades[clave], self.pagos.almacen.negocio,
                preferencias=self.contexto.leer(self._identidades[clave]), compartir=compartir,
                skills_cliente=('preferencias_consentidas', 'pedido_estructurado'),
                skills_vendedor=('cotizacion_determinista', 'sha256:'+skill_vendedor))
        return self._identidades[clave]

    def _reiniciar(self, identidad: Identidad,
                   compartir: frozenset[str] = frozenset()) -> Identidad:
        self.pagos.almacen.invalidar_sesion(identidad.sesion_id)
        self._conversaciones.pop(identidad.clave_sesion, None)
        self._identidades.pop(identidad.clave_sesion, None)
        self._canales.pop(identidad.clave_sesion, None)
        return self._identidad(identidad.chat_id, identidad.usuario_id, identidad.clave_sesion, compartir)

    def _aceptar_mensaje(self, clave: str, numero: Any) -> bool:
        if type(numero) is not int or numero <= 0:
            return False
        with self._base() as db:
            return db.execute("UPDATE clientes SET ultimo_mensaje=? "
                              "WHERE clave=? AND ultimo_mensaje<?", (numero, clave, numero)).rowcount == 1

    @staticmethod
    def _parametros(identidad: Identidad) -> dict[str, Any]:
        return {"source": SimpleNamespace(platform="telegram", chat_id=identidad.chat_id,
                                          user_id=identidad.usuario_id, chat_type="private", is_bot=False),
                "platform": "telegram", "session_id": identidad.sesion_id,
                "session_key": identidad.clave_sesion}

    def _espera_por_cuota(self, usuario: str) -> int:
        """Ventanas móviles durables: /new y reiniciar el proceso no reinician la cuota."""
        if not self.pagos.publico:
            return 0
        ahora = self.reloj()
        with self._base() as db:
            db.execute("DELETE FROM cuotas_consultas WHERE instante <= ?", (ahora - 86400,))
            instantes = [fila[0] for fila in db.execute(
                "SELECT instante FROM cuotas_consultas WHERE usuario=? ORDER BY instante", (usuario,))]
            recientes = [t for t in instantes if t > ahora - 60]
            espera = max(instantes[-100] + 86400 - ahora if len(instantes) >= 100 else 0,
                         recientes[-12] + 60 - ahora if len(recientes) >= 12 else 0)
            if espera > 0:
                return math.ceil(espera)
            db.execute("INSERT INTO cuotas_consultas(usuario, instante) VALUES (?, ?)", (usuario, ahora))
        return 0

    async def _comando(self, identidad: Identidad, texto: str) -> str | None:
        comando, _, argumentos = texto.partition(" ")
        comando = comando.split("@", 1)[0].lower()
        argumentos = argumentos.strip()
        if comando in {"/start", "/new"}:
            self._reiniciar(identidad)
            return ("SIMULACIÓN — conversación nueva. Cuéntame qué pastel necesitas. "
                    "Puedes usar /pagar, /pedido, /preferencias, /recordar clave=valor y /olvidar. "
                    "Tus preferencias guardadas son privadas; /compartir autoriza campos para esta conversación.")
        if comando in {"/pagar", "/pedido"}:
            funcion = self.pagos.pagar if comando == "/pagar" else self.pagos.pedido
            return await funcion(argumentos, **self._parametros(identidad))
        if comando == "/preferencias":
            preferencias = self.contexto.leer(identidad)
            campos = self._canales[identidad.clave_sesion].campos_compartidos
            return (("Preferencias guardadas: " + ", ".join(f"{k}={v}" for k, v in sorted(preferencias.items()))
                     if preferencias else "No tienes preferencias guardadas. /recordar clave=valor autoriza guardarlas.")
                    + "\nCompartidas con el vendedor en esta conversación: " + (", ".join(sorted(campos)) or "ninguna") + ".")
        if comando == "/compartir":
            campos = argumentos.split()
            preferencias = self.contexto.leer(identidad)
            if not campos or len(campos) != len(set(campos)) or not set(campos) <= set(preferencias):
                return ("Indica los campos guardados que autorizas compartir, por ejemplo /compartir sabor zona. "
                        "Consulta /preferencias; /new revoca lo compartido.")
            self._reiniciar(identidad, frozenset(campos))
            return ("Conversación nueva. Autorizaste compartir con el vendedor únicamente: "
                    + ", ".join(sorted(campos)) + ". /new revoca esta autorización.")
        if comando == "/olvidar" and not argumentos:
            self.contexto.olvidar(identidad)
            self._reiniciar(identidad)
            return "Preferencias eliminadas. Comenzamos una conversación nueva sin ellas."
        if comando == "/recordar":
            from .contexto_clientes import PREFERENCIAS

            campos = argumentos.split()
            preferencias: dict[str, str] = {}
            for campo in campos:
                nombre, separador, valor = campo.partition("=")
                if not separador or nombre in preferencias or valor not in PREFERENCIAS.get(nombre, ()):
                    return "Usa /recordar con preferencias permitidas: " + "; ".join(
                        f"{k}=" + "|".join(sorted(v)) for k, v in sorted(PREFERENCIAS.items()))
                preferencias[nombre] = valor
            if not preferencias:
                return "Usa /recordar clave=valor para autorizar guardar esa preferencia."
            anteriores = self.contexto.leer(identidad)
            self.contexto.recordar(identidad, {**anteriores, **preferencias}, consentimiento=True)
            self._reiniciar(identidad)
            return ("Preferencias guardadas en tu contexto personal. Comenzamos una conversación nueva. "
                    "Todavía no se comparten con el vendedor; autoriza campos con /compartir sabor zona.")
        return "Comando disponible: /new, /pagar, /pedido, /preferencias, /recordar, /compartir u /olvidar."

    async def recibir(self, update: Any, context: Any) -> None:
        from telegram.ext import ApplicationHandlerStop

        mensaje = getattr(update, "effective_message", None)
        autorizado = False
        try:
            chat, usuario, clave = self._autorizar(update)
            autorizado = True
            async with self._candados.setdefault(clave, asyncio.Lock()):
                self._preparar()
                identidad = self._identidad(chat, usuario, clave)
                if getattr(update, "edited_message", None) is not None:
                    # Telegram conserva el ID de un mensaje editado: no tratarlo
                    # como un duplicado inocuo que deja vivo el pago anterior.
                    self._reiniciar(identidad)
                    if mensaje:
                        await mensaje.reply_text("El mensaje cambió y la cotización anterior dejó de estar vigente. "
                                                 "Envía tu pedido en un mensaje nuevo.", parse_mode=None)
                    return
                if mensaje is None or not self._aceptar_mensaje(clave, mensaje.message_id):
                    return
                texto = getattr(mensaje, "text", None)
                if not isinstance(texto, str) or not texto.strip():
                    await mensaje.reply_text("Por ahora escribe tu pedido en texto. No procesamos archivos.", parse_mode=None)
                    return
                if texto.startswith("/"):
                    respuesta = await self._comando(identidad, texto)
                else:
                    llamada = uuid4().hex
                    # Ocurre antes del await: ningún callback puede cobrar una revisión vieja.
                    self.pagos.almacen.iniciar_cotizacion(identidad, llamada)
                    espera = self._espera_por_cuota(usuario)
                    if espera:
                        await mensaje.reply_text(
                            f"Alcanzaste el límite de consultas de la demo (12 por minuto y 100 en 24 horas). "
                            f"Espera {espera} segundos y vuelve a enviar tu mensaje. "
                            "La cotización anterior dejó de estar vigente.", parse_mode=None)
                        return
                    if clave not in self._conversaciones:
                        canal = self._canales[clave]
                        sobre = canal.compartir_preferencias()
                        preferencias = dict(sobre.datos["preferencias"]) if sobre else {}
                        self._conversaciones[clave] = self.crear_conversacion(
                            self.datos, self.pagos.almacen.negocio, preferencias)
                        self._conversaciones[clave].canal = canal
                    conversacion = self._conversaciones[clave]
                    try:
                        resultado = await asyncio.wait_for(asyncio.to_thread(conversacion.turno, texto), self.plazo)
                        if not isinstance(resultado, dict) or not isinstance(resultado.get("texto"), str):
                            raise ValueError("Salida inválida del arnés.")
                        if resultado.get("pago_habilitado") is True and isinstance(resultado.get("cotizacion"), dict):
                            self.pagos.almacen.capturar(identidad, resultado.get("solicitud"), llamada)
                        respuesta = resultado["texto"]
                    except BaseException:
                        # Un hilo que termina tarde conserva solo su objeto, nunca el estado vigente.
                        self._reiniciar(identidad)
                        raise
                if respuesta:
                    await mensaje.reply_text(respuesta, parse_mode=None)
        except PresupuestoAgotado:
            if autorizado and mensaje:
                await mensaje.reply_text("El presupuesto disponible no permite otra consulta. No se realizó ningún cobro.", parse_mode=None)
        except Exception:
            if autorizado and mensaje:
                try:
                    await mensaje.reply_text("No pude completar este mensaje. Intenta de nuevo; no se realizó ningún cobro.", parse_mode=None)
                except Exception:
                    pass
        finally:
            raise ApplicationHandlerStop

    async def boton(self, update: Any, context: Any) -> None:
        from telegram.ext import ApplicationHandlerStop

        try:
            chat, usuario, clave = self._autorizar(update)
            async with self._candados.setdefault(clave, asyncio.Lock()):
                self._preparar()
                identidad = self._identidad(chat, usuario, clave)
                token = str(getattr(update.callback_query, "data", "")).rsplit(":", 1)[-1]
                self.pagos.almacen.validar_boton(identidad, token)
                await self.pagos.boton(update, context)
        except Exception:
            consulta = getattr(update, "callback_query", None)
            if consulta:
                try:
                    await consulta.answer("Este botón no está disponible.", show_alert=True)
                except Exception:
                    pass
        finally:
            raise ApplicationHandlerStop

    def conectar(self, aplicacion: Any, adapter: Any) -> None:
        from telegram.ext import CallbackQueryHandler, MessageHandler, filters

        self.pagos.aplicacion = aplicacion
        # Todo mensaje y callback se consume; los comandos desconocidos tampoco llegan a Hermes.
        aplicacion.add_handler(MessageHandler(filters.ALL, self.recibir), group=-100)
        aplicacion.add_handler(CallbackQueryHandler(self.boton), group=-100)
