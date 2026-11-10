"""Único punto de acceso a Anthropic; valida contrato, reserva y contabiliza consumo."""

from __future__ import annotations

import copy
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from .herramientas import HERRAMIENTAS
from .presupuesto import Presupuesto


MODELO = "claude-haiku-5-5"
MAX_TOKENS = 4096
MAX_CONTEXTO = 1_000_000
_CONTRATOS = {herramienta["name"]: herramienta for herramienta in HERRAMIENTAS}


class SolicitudInvalida(ValueError):
    """La petición no pertenece al contrato de este piloto."""


class ErrorInferencia(RuntimeError):
    """Fallo sanitizado; nunca contiene el error crudo del SDK ni credenciales."""


def _nombre_herramienta(nombre: Any) -> str:
    if not isinstance(nombre, str):
        raise SolicitudInvalida("Nombre de herramienta inválido.")
    canonico = nombre.removeprefix("mcp__pasteles__")
    if canonico not in _CONTRATOS:
        raise SolicitudInvalida("Solo se permiten las tres herramientas de Pasteles.")
    return canonico


def _texto(valor: Any) -> str:
    if not isinstance(valor, str):
        raise SolicitudInvalida("Se esperaba contenido de texto.")
    return valor


def _contenido(valor: Any, rol: str) -> str | list[dict[str, Any]]:
    if isinstance(valor, str):
        return valor
    if not isinstance(valor, list) or not valor:
        raise SolicitudInvalida("Contenido de mensaje inválido.")
    resultado = []
    for bloque in valor:
        if not isinstance(bloque, dict):
            raise SolicitudInvalida("Bloque de mensaje inválido.")
        tipo = bloque.get("type")
        if tipo == "text":
            resultado.append({"type": "text", "text": _texto(bloque.get("text"))})
        elif tipo == "tool_use" and rol == "assistant":
            _nombre_herramienta(bloque.get("name"))
            if not isinstance(bloque.get("input"), dict):
                raise SolicitudInvalida("Entrada de herramienta inválida.")
            resultado.append({"type": tipo, "id": _texto(bloque.get("id")),
                              "name": bloque["name"], "input": copy.deepcopy(bloque["input"])})
        elif tipo == "tool_result" and rol == "user":
            limpio = {"type": tipo, "tool_use_id": _texto(bloque.get("tool_use_id")),
                      "content": _contenido(bloque.get("content", ""), "resultado")}
            if "is_error" in bloque:
                if type(bloque["is_error"]) is not bool:
                    raise SolicitudInvalida("Estado de herramienta inválido.")
                limpio["is_error"] = bloque["is_error"]
            resultado.append(limpio)
        else:
            raise SolicitudInvalida("Solo se permite texto y herramientas locales de Pasteles.")
    return resultado


def preparar_solicitud(solicitud: dict[str, Any]) -> dict[str, Any]:
    """Reconstruye la lista permitida; nunca reenvía sampling, caché ni campos desconocidos."""
    if not isinstance(solicitud, dict) or solicitud.get("model") != MODELO:
        raise SolicitudInvalida(f"El único modelo permitido es {MODELO}.")
    if solicitud.get("stream", False) is not False:
        raise SolicitudInvalida("Este piloto solo admite respuestas sin streaming.")
    maximo = solicitud.get("max_tokens", MAX_TOKENS)
    if type(maximo) is not int or maximo < 1:
        raise SolicitudInvalida("max_tokens debe ser un entero positivo.")
    mensajes = solicitud.get("messages")
    if not isinstance(mensajes, list) or not mensajes:
        raise SolicitudInvalida("Se requiere una conversación.")
    limpios = []
    for mensaje in mensajes:
        if (not isinstance(mensaje, dict) or not isinstance(mensaje.get("role"), str)
                or mensaje["role"] not in {"user", "assistant"}):
            raise SolicitudInvalida("Rol de conversación inválido.")
        rol = mensaje["role"]
        limpios.append({"role": rol, "content": _contenido(mensaje.get("content"), rol)})
    if limpios[0]["role"] != "user" or limpios[-1]["role"] != "user":
        raise SolicitudInvalida("La conversación debe empezar y terminar con un mensaje del usuario; no se admite prefill.")
    datos: dict[str, Any] = {"model": MODELO, "max_tokens": min(maximo, MAX_TOKENS),
                             "messages": limpios, "thinking": {"type": "disabled"}}
    if "system" in solicitud:
        datos["system"] = _contenido(solicitud["system"], "sistema")
    herramientas = solicitud.get("tools", [])
    if not isinstance(herramientas, list) or len(herramientas) > 3:
        raise SolicitudInvalida("Lista de herramientas inválida.")
    nombres: set[str] = set()
    contratos = []
    for herramienta in herramientas:
        if not isinstance(herramienta, dict) or herramienta.get("type", "custom") != "custom":
            raise SolicitudInvalida("No se permiten herramientas ejecutadas por el proveedor.")
        canonico = _nombre_herramienta(herramienta.get("name"))
        if canonico in nombres:
            raise SolicitudInvalida("Herramienta duplicada.")
        nombres.add(canonico)
        contrato = _CONTRATOS[canonico]
        contratos.append({"name": herramienta["name"], "description": contrato["description"],
                          "input_schema": copy.deepcopy(contrato["inputSchema"])})
    if contratos:
        datos["tools"] = contratos
        datos["tool_choice"] = {"type": "auto"}
    return datos


def costo_consumo(uso: Any, maximo_salida: int = MAX_TOKENS) -> Decimal:
    if not isinstance(uso, dict):
        raise ErrorInferencia("El proveedor no informó consumo válido; se conserva la reserva.")
    entrada, salida = uso.get("input_tokens"), uso.get("output_tokens")
    if (type(entrada) is not int or type(salida) is not int or not 0 <= entrada <= MAX_CONTEXTO
            or not 0 <= salida <= maximo_salida
            or any(uso.get(campo, 0) not in (0, None) for campo in ("cache_creation_input_tokens", "cache_read_input_tokens"))):
        raise ErrorInferencia("El proveedor informó consumo inválido; se conserva la reserva.")
    tasa_entrada, tasa_salida = ((Decimal("0.1"), Decimal("0.5")) if entrada <= 100_000
                                else (Decimal("0.5"), Decimal("2.5")))
    return (entrada * tasa_entrada + salida * tasa_salida) / 1_000_000


class ClienteAnthropic:
    def __init__(self, ruta_estado: Path, limite: str = "5.00", *, sdk: Any = None) -> None:
        self.es_real = sdk is None
        self.presupuesto = Presupuesto(Path(ruta_estado) / "presupuesto.sqlite3", limite)
        if sdk is None:
            llave = os.environ.get("ANTHROPIC_API_KEY", "")
            if not llave:
                raise ErrorInferencia("Falta ANTHROPIC_API_KEY en el entorno del proxy.")
            from anthropic import Anthropic
            sdk = Anthropic(api_key=llave, base_url="https://api.anthropic.com", max_retries=0, timeout=60.0)
        self._sdk = sdk

    def completar(self, solicitud: dict[str, Any]) -> dict[str, Any]:
        datos = preparar_solicitud(solicitud)
        reserva = self.presupuesto.reservar()
        try:
            respuesta = self._sdk.messages.create(**datos)
            respuesta = respuesta if isinstance(respuesta, dict) else respuesta.model_dump(mode="json")
        except Exception:
            raise ErrorInferencia("No se pudo completar la llamada al proveedor; se conserva la reserva.") from None
        if not isinstance(respuesta, dict) or respuesta.get("model") != MODELO:
            raise ErrorInferencia("Respuesta del proveedor inválida; se conserva la reserva.")
        costo = costo_consumo(respuesta.get("usage"), datos["max_tokens"])
        self.presupuesto.confirmar(reserva, costo)
        try:
            contenido = _contenido(respuesta.get("content"), "assistant")
            if not isinstance(contenido, list):
                raise SolicitudInvalida("Formato de respuesta inválido.")
            identificador = _texto(respuesta.get("id"))
            if respuesta.get("role") != "assistant" or respuesta.get("type") != "message":
                raise SolicitudInvalida("Formato de respuesta inválido.")
            if respuesta.get("stop_reason") not in ("end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal"):
                raise SolicitudInvalida("Fin de respuesta inválido.")
        except (SolicitudInvalida, RecursionError):
            raise ErrorInferencia("El proveedor devolvió una respuesta fuera del contrato del piloto.") from None
        return {"id": identificador, "type": "message", "role": "assistant", "model": MODELO,
                "content": contenido, "stop_reason": respuesta["stop_reason"], "stop_sequence": None,
                "usage": {"input_tokens": respuesta["usage"]["input_tokens"],
                          "output_tokens": respuesta["usage"]["output_tokens"]}}


class ClienteFalso:
    """Respuestas de prueba, sin red ni credenciales; conserva peticiones para aserciones."""

    es_real = False

    def __init__(self, respuestas: list[dict[str, Any] | Exception] | None = None) -> None:
        self.respuestas = list(respuestas or [])
        self.solicitudes: list[dict[str, Any]] = []

    def completar(self, solicitud: dict[str, Any]) -> dict[str, Any]:
        preparar_solicitud(solicitud)
        self.solicitudes.append(copy.deepcopy(solicitud))
        if not self.respuestas:
            raise ErrorInferencia("ClienteFalso no tiene más respuestas configuradas.")
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return copy.deepcopy(respuesta)
