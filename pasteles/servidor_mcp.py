"""Servidor MCP stdio mínimo, protocolo 2024-11-05, sin red ni persistencia."""

from __future__ import annotations

import json
from typing import Any, TextIO

from .herramientas import HERRAMIENTAS, ejecutar
from .negocio import Pasteleria


def error(identificador: Any, codigo: int, mensaje: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identificador, "error": {"code": codigo, "message": mensaje}}


class Servidor:
    def __init__(self, negocio: Pasteleria | None = None) -> None:
        self.negocio = negocio or Pasteleria()
        self.inicializado = False

    def responder(self, solicitud: Any) -> dict[str, Any] | None:
        if not isinstance(solicitud, dict):
            return error(None, -32600, "Solicitud inválida.")
        identificador = solicitud.get("id")
        if (solicitud.get("jsonrpc") != "2.0" or not isinstance(solicitud.get("method"), str)
                or ("id" in solicitud and type(identificador) not in (str, int))):
            return error(None, -32600, "Solicitud inválida.")
        if "id" not in solicitud:
            return None
        metodo = solicitud["method"]
        parametros = solicitud.get("params", {})
        if not isinstance(parametros, dict):
            return error(identificador, -32602, "Los parámetros deben ser un objeto.")
        if metodo == "initialize":
            if (not isinstance(parametros.get("protocolVersion"), str)
                    or not isinstance(parametros.get("capabilities"), dict)
                    or not isinstance(parametros.get("clientInfo"), dict)):
                return error(identificador, -32602, "Faltan datos de inicialización.")
            self.inicializado = True
            resultado = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                         "serverInfo": {"name": "pasteles-demo", "version": "0.1.0"}}
        elif metodo == "ping":
            resultado = {}
        elif not self.inicializado:
            return error(identificador, -32000, "Inicializa la conexión primero.")
        elif metodo == "tools/list":
            resultado = {"tools": HERRAMIENTAS}
        elif metodo == "tools/call":
            nombre = parametros.get("name")
            if not isinstance(nombre, str) or nombre not in {h["name"] for h in HERRAMIENTAS}:
                return error(identificador, -32602, "Herramienta desconocida.")
            try:
                datos = ejecutar(self.negocio, nombre, parametros.get("arguments", {}))
                resultado = {"content": [{"type": "text", "text": json.dumps(datos, ensure_ascii=False)}]}
            except ValueError as fallo:
                resultado = {"content": [{"type": "text", "text": str(fallo)}], "isError": True}
        else:
            return error(identificador, -32601, "Método no disponible.")
        return {"jsonrpc": "2.0", "id": identificador, "result": resultado}


def servir(entrada: TextIO, salida: TextIO) -> None:
    servidor = Servidor()
    for linea in entrada:
        if not linea.strip():
            continue
        try:
            solicitud = json.loads(linea)
        except (ValueError, RecursionError):
            respuesta = error(None, -32700, "JSON inválido.")
        else:
            respuesta = servidor.responder(solicitud)
        if respuesta is not None:
            salida.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            salida.flush()
