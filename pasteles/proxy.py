"""Proxy Anthropic privado, autenticado y limitado a loopback."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from .llm import ErrorInferencia
from .presupuesto import PresupuestoAgotado


MAX_CUERPO = 1_048_576


class Cliente(Protocol):
    def completar(self, solicitud: dict[str, Any]) -> dict[str, Any]: ...


def crear_servidor(cliente: Cliente, host: str = "127.0.0.1", puerto: int = 8787,
                   clave_local: str = "") -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("El proxy solo escucha en 127.0.0.1.")
    if not isinstance(clave_local, str) or len(clave_local) < 32:
        raise ValueError("La credencial local debe tener al menos 32 caracteres.")

    class Manejador(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, formato: str, *argumentos: Any) -> None:
            pass  # No registrar cabeceras, cuerpos ni credenciales.

        def _responder(self, codigo: int, contenido: dict[str, Any]) -> None:
            cuerpo = json.dumps(contenido, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            try:
                self.wfile.write(cuerpo)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _error(self, codigo: int, tipo: str, mensaje: str) -> None:
            self._responder(codigo, {"type": "error", "error": {"type": tipo, "message": mensaje}})

        def do_GET(self) -> None:
            if self.path == "/salud":
                self._responder(200, {"estado": "listo", "servicio": "pasteles"})
            else:
                self._error(404, "not_found_error", "Ruta no disponible.")

        def do_POST(self) -> None:
            if self.path != "/v1/messages":
                self._error(404, "not_found_error", "Ruta no disponible.")
                return
            credencial = self.headers.get("x-api-key", "")
            autorizacion = self.headers.get("Authorization", "")
            if not credencial and autorizacion.startswith("Bearer "):
                credencial = autorizacion[7:]
            if not hmac.compare_digest(credencial.encode(), clave_local.encode()):
                self._error(401, "authentication_error", "Credencial local inválida.")
                return
            try:
                longitud = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                longitud = 0
            if not 0 < longitud <= MAX_CUERPO or self.headers.get("Transfer-Encoding"):
                self._error(413, "request_too_large", "Tamaño de solicitud inválido.")
                return
            try:
                cuerpo = self.rfile.read(longitud)
                if len(cuerpo) != longitud:
                    raise ValueError("Cuerpo incompleto")
                def rechazar_constante(valor: str) -> None:
                    raise ValueError("Constante JSON inválida")
                solicitud = json.loads(cuerpo, parse_constant=rechazar_constante)
                respuesta = cliente.completar(solicitud)
            except (ValueError, RecursionError, UnicodeError):
                self._error(400, "invalid_request_error", "Solicitud fuera del contrato de Pasteles.")
                return
            except PresupuestoAgotado:
                self._error(402, "billing_error", "Presupuesto de API agotado.")
                return
            except (ErrorInferencia, TimeoutError):
                self._error(502, "api_error", "No se pudo completar la llamada al proveedor.")
                return
            except Exception:
                self._error(500, "api_error", "No se pudo procesar la solicitud.")
                return
            self._responder(200, respuesta)

    return ThreadingHTTPServer((host, puerto), Manejador)
