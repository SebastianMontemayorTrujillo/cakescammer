"""Plugin Hermes: tres consultas MCP y decisiones humanas por Telegram."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

# Hermes puede iniciarse con -I; solo la ruta local elegida por el lanzador entra aquí.
_raiz_configurada = os.environ.get("PASTELES_RAIZ")
if _raiz_configurada:
    _raiz = Path(_raiz_configurada)
    if (not _raiz.is_absolute() or not all((_raiz / "pasteles" / nombre).is_file()
            for nombre in ("__init__.py", "negocio.py", "pagos.py"))):
        raise RuntimeError("PASTELES_RAIZ no contiene el paquete de Pasteles.")
    sys.path.insert(0, str(_raiz.resolve()))

from pasteles.pagos import AlmacenPagos, ErrorPago, Identidad  # noqa: E402
from pasteles.seguridad_texto import citar_literal  # noqa: E402

HERRAMIENTA_COTIZAR = "mcp__pasteles__cotizar_pedido"
PATRON_BOTON = r"^pasteles:(aprobar|rechazar|cancelar):([A-Za-z0-9_-]{24})$"


def _usuarios_permitidos() -> frozenset[str]:
    valores = os.environ.get("TELEGRAM_ALLOWED_USERS", "").replace(";", ",").split(",")
    usuarios = frozenset(valor.strip() for valor in valores if valor.strip())
    if not usuarios or any(not usuario.isdecimal() or int(usuario) <= 0 for usuario in usuarios):
        raise RuntimeError("Configura TELEGRAM_ALLOWED_USERS con IDs numéricos explícitos.")
    return usuarios


def _importe(centavos: int) -> str:
    return f"${centavos // 100:,}.{centavos % 100:02d} MXN"


def resumen(pedido: dict[str, Any]) -> str:
    cotizacion = pedido["cotizacion"]
    entrega = "Recoger" if cotizacion["modalidad"] == "recoger" else f"Entrega: {cotizacion['zona']}"
    mensaje = ("\nMensaje solicitado: " + citar_literal(cotizacion["mensaje"])
               if cotizacion["mensaje"] else "")
    return (f"SIMULACIÓN — pedido {pedido['id'][:8]}\n"
            f"{cotizacion['producto']} · {cotizacion['porciones']} porciones\n"
            f"Fecha: {cotizacion['fecha']} · {cotizacion['asistentes']} asistentes\n"
            f"{entrega}{mensaje}\n"
            f"Pastel: {_importe(cotizacion['pastel_centavos'])}\n"
            f"Entrega: {_importe(cotizacion['entrega_centavos'])}\n"
            f"Total: {_importe(cotizacion['total_centavos'])}\n"
            f"Estado simulado: {pedido['estado']}.\n"
            "No se cobra dinero, no se reserva y no se confirma un pedido real.")


class ServicioPagos:
    def __init__(self, almacen: AlmacenPagos, usuarios: frozenset[str], *, publico: bool = False) -> None:
        self.almacen = almacen
        self.usuarios = usuarios
        self.publico = publico
        self.aplicacion: Any = None
        self._candados: dict[str, asyncio.Lock] = {}

    def _autorizar(self, chat_id: Any, usuario_id: Any, tipo_chat: str) -> None:
        if (tipo_chat not in {"private", "dm"}
                or (not self.publico and str(usuario_id) not in self.usuarios)
                or str(chat_id) != str(usuario_id)
                or not str(chat_id).isascii() or not str(chat_id).isdecimal() or int(str(chat_id)) <= 0):
            raise ErrorPago("La simulación solo está disponible en el chat privado autorizado.")

    def _identidad_hook(self, sesion_id: str) -> Identidad:
        from gateway.session_context import bound_session_key, get_session_env

        clave = bound_session_key()
        if (not clave or get_session_env("HERMES_SESSION_PLATFORM") != "telegram"
                or not sesion_id or get_session_env("HERMES_SESSION_ID") != sesion_id):
            raise ErrorPago("Falta el contexto autenticado de Telegram.")
        chat = get_session_env("HERMES_SESSION_CHAT_ID")
        usuario = get_session_env("HERMES_SESSION_USER_ID")
        self._autorizar(chat, usuario, get_session_env("HERMES_SESSION_CHAT_TYPE"))
        return Identidad(chat, usuario, sesion_id, clave)

    def _identidad_comando(self, source: Any, platform: str, session_id: str, session_key: str) -> Identidad:
        origen = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", None))
        if source is None or platform != "telegram" or origen != "telegram" or getattr(source, "is_bot", False):
            raise ErrorPago("Usa este comando en tu chat privado de Telegram.")
        self._autorizar(source.chat_id, source.user_id, source.chat_type)
        return Identidad(str(source.chat_id), str(source.user_id), session_id, session_key)

    def antes_herramienta(self, tool_name: str, args: Any = None, *, session_id: str = "",
                          tool_call_id: str = "", **_: Any) -> dict[str, str] | None:
        if tool_name != HERRAMIENTA_COTIZAR:
            return None
        try:
            identidad = self._identidad_hook(session_id)
        except ErrorPago:
            return None  # El MCP sigue siendo una consulta local; aquí no crea pedidos.
        try:
            self.almacen.iniciar_cotizacion(identidad, tool_call_id)
        except (sqlite3.Error, ErrorPago):
            return {"action": "block", "message": "No se pudo actualizar la cotización de simulación. Intenta de nuevo."}
        return None

    def despues_herramienta(self, tool_name: str, args: Any, result: Any = None, *,
                            session_id: str = "", tool_call_id: str = "", status: str = "",
                            **_: Any) -> None:
        if tool_name != HERRAMIENTA_COTIZAR:
            return
        try:
            identidad = self._identidad_hook(session_id)
        except ErrorPago:
            return
        # El texto de result nunca decide precio ni estado; se recalcula desde los argumentos.
        self.almacen.capturar(identidad, args, tool_call_id, valido=status == "ok")

    def reiniciar(self, *, old_session_id: str = "", platform: str = "", **_: Any) -> None:
        if platform == "telegram":
            self.almacen.invalidar_sesion(old_session_id)

    async def pagar(self, raw_args: str, *, source: Any = None, platform: str = "",
                    session_id: str = "", session_key: str = "") -> str | None:
        try:
            identidad = self._identidad_comando(source, platform, session_id, session_key)
            if raw_args.strip():
                raise ErrorPago("Usa /pagar sin argumentos; se utiliza tu última cotización vigente.")
            if self.aplicacion is None:
                raise ErrorPago("Telegram todavía no está conectado.")
            # Serializa dos /pagar del mismo chat para que la tarjeta vigente sea inequívoca.
            candado = self._candados.setdefault(identidad.clave_sesion, asyncio.Lock())
            async with candado:
                pedido = self.almacen.preparar(identidad)
                if pedido["estado"] != "pendiente":
                    return resumen(pedido)
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                teclado = InlineKeyboardMarkup([[InlineKeyboardButton(etiqueta, callback_data=f"pasteles:{accion}:{pedido['token']}")]
                                                for etiqueta, accion in (
                                                    ("Aprobar pago simulado", "aprobar"),
                                                    ("Rechazar", "rechazar"), ("Cancelar", "cancelar"))])
                enviado = await self.aplicacion.bot.send_message(
                    chat_id=int(identidad.chat_id), text=resumen(pedido) +
                    "\nElige un resultado. La primera decisión cierra esta simulación.",
                    reply_markup=teclado, parse_mode=None)
                self.almacen.vincular_mensaje(identidad, pedido["id"], str(enviado.message_id))
                return None
        except ErrorPago as error:
            return str(error)

    async def pedido(self, raw_args: str, *, source: Any = None, platform: str = "",
                     session_id: str = "", session_key: str = "") -> str:
        try:
            identidad = self._identidad_comando(source, platform, session_id, session_key)
            if raw_args.strip():
                raise ErrorPago("Usa /pedido sin argumentos.")
            pedido = self.almacen.consultar(identidad)
            return resumen(pedido) if pedido else "Todavía no tienes un pedido simulado en este chat."
        except ErrorPago as error:
            return str(error)

    async def boton(self, update: Any, context: Any) -> None:
        consulta = update.callback_query
        try:
            coincidencia = re.fullmatch(PATRON_BOTON, str(consulta.data))
            mensaje = consulta.message
            usuario = consulta.from_user
            if not coincidencia or mensaje is None or getattr(usuario, "is_bot", False):
                raise ErrorPago("Este botón no está disponible.")
            self._autorizar(mensaje.chat.id, usuario.id, mensaje.chat.type)
            pedido = self.almacen.resolver(str(mensaje.chat.id), str(usuario.id), str(mensaje.message_id),
                                           coincidencia[2], coincidencia[1])
        except (ErrorPago, AttributeError) as error:
            texto = str(error) if isinstance(error, ErrorPago) else "Este botón no está disponible."
            await consulta.answer(texto, show_alert=True)
            return
        await consulta.answer("Simulación registrada. No se realizó ningún cobro.")
        # El estado ya quedó confirmado de forma duradera, incluso si editar Telegram falla.
        from telegram.error import TelegramError

        try:
            await consulta.edit_message_text(text=resumen(pedido), reply_markup=None, parse_mode=None)
        except TelegramError:
            # Un callback repetido puede encontrar la tarjeta ya editada. /pedido permite
            # recuperar el resultado si Telegram dejó de aceptar ediciones del mensaje.
            pass

    async def solo_texto(self, update: Any, context: Any) -> None:
        mensaje = update.effective_message
        usuario = update.effective_user
        chat = update.effective_chat
        try:
            if usuario is None or getattr(usuario, "is_bot", False) or mensaje is None:
                return
            self._autorizar(chat.id, usuario.id, chat.type)
        except (ErrorPago, AttributeError):
            return
        await mensaje.reply_text("Por ahora escribe tu pedido en texto. No procesamos fotos, audios ni archivos.")

    def conectar(self, aplicacion: Any, adapter: Any) -> None:
        from telegram.ext import CallbackQueryHandler, MessageHandler, filters

        self.aplicacion = aplicacion
        aplicacion.add_handler(CallbackQueryHandler(self.boton, pattern=r"^pasteles:"))
        aplicacion.add_handler(MessageHandler(filters.ALL & ~filters.TEXT, self.solo_texto))


def register(ctx: Any) -> None:
    from pasteles.configuracion import acceso_publico

    publico = acceso_publico(os.environ)
    if publico and os.environ.get("PASTELES_RSI") != "1":
        raise RuntimeError("El acceso público requiere el consumidor nativo PASTELES_RSI=1.")
    usuarios = frozenset() if publico else _usuarios_permitidos()
    configurada = os.environ.get("PASTELES_DATOS")
    directorio = Path(configurada) if configurada else Path(ctx.state.data_dir)
    if not directorio.is_absolute():
        raise RuntimeError("PASTELES_DATOS debe ser un directorio absoluto.")
    servicio = ServicioPagos(AlmacenPagos(directorio / "pagos.sqlite3"), usuarios, publico=publico)
    if os.environ.get("PASTELES_RSI") == "1":
        from pasteles.telegram_rsi import ServicioTelegram

        ctx.register_platform_handler("telegram", ServicioTelegram(servicio, directorio).conectar)
        return
    ctx.register_hook("pre_tool_call", servicio.antes_herramienta)
    ctx.register_hook("post_tool_call", servicio.despues_herramienta)
    ctx.register_hook("on_session_reset", servicio.reiniciar)
    ctx.register_command("pagar", servicio.pagar, description="Elegir un resultado de pago SIMULACION")
    ctx.register_command("pedido", servicio.pedido, description="Consultar tu pedido SIMULACION")
    ctx.register_platform_handler("telegram", servicio.conectar)
