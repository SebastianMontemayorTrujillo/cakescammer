"""Panel local de evidencia: lectura de agregados, sin ejecutar evaluaciones."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .panel_datos import construir_panel
from .panel_experiencia import leer_experiencia


def crear_servidor(raiz: Path, puerto: int = 8765) -> ThreadingHTTPServer:
    """Escucha exclusivamente en loopback y sirve una lista cerrada de recursos."""
    raiz = raiz.resolve()
    recursos = {
        "/": ("pasteles/web/index.html", "text/html; charset=utf-8"),
        "/panel.css": ("pasteles/web/panel.css", "text/css; charset=utf-8"),
        "/panel.js": ("pasteles/web/panel.js", "text/javascript; charset=utf-8"),
        "/informe.pdf": ("output/pdf/pasteles_rsi.pdf", "application/pdf"),
        "/informe.tex": ("output/pdf/pasteles_rsi.tex", "text/plain; charset=utf-8"),
    }

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, formato: str, *argumentos: object) -> None:
            # Las URL recibidas tampoco se registran: pueden contener datos privados.
            pass

        def _responder(self, estado: int, contenido: bytes, tipo: str) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(contenido)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(contenido)

        def _leer(self) -> None:
            autoridades = {f"127.0.0.1:{self.server.server_port}",
                           f"localhost:{self.server.server_port}"}
            origen = self.headers.get("Origin")
            if (self.headers.get("Host") not in autoridades
                    or (origen and origen not in {f"http://{a}" for a in autoridades})):
                self._responder(403, b"Origen no permitido.", "text/plain; charset=utf-8")
                return
            ruta = urlsplit(self.path).path
            if ruta == "/api/panel":
                try:
                    datos = construir_panel(raiz)
                    datos['experiencia'] = leer_experiencia(raiz,
                        datos['modos']['real']['activa_version_id'], datos.get('arnes_actual_sha256'))
                    datos['avisos'].extend(datos['experiencia']['avisos'])
                    datos['numero_avisos'] = len(datos['avisos'])
                    contenido = json.dumps(datos, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except (OSError, ValueError, TypeError):
                    self._responder(503, b'{"error":"No se pudo leer la evidencia local."}', "application/json")
                    return
                self._responder(200, contenido, "application/json; charset=utf-8")
                return
            if ruta not in recursos:
                self._responder(404, b"Recurso no disponible.", "text/plain; charset=utf-8")
                return
            relativa, tipo = recursos[ruta]
            archivo = raiz / relativa
            if any(p.is_symlink() for p in [archivo, *archivo.parents] if p != raiz.parent):
                self._responder(404, b"Recurso no disponible.", "text/plain; charset=utf-8")
                return
            try:
                if not archivo.is_file() or archivo.stat().st_nlink != 1:
                    raise OSError
                contenido = archivo.read_bytes()
            except OSError:
                self._responder(404, b"Recurso no disponible.", "text/plain; charset=utf-8")
                return
            self._responder(200, contenido, tipo)

        do_GET = _leer
        do_HEAD = _leer

        def do_POST(self) -> None:
            self._responder(405, b"Panel de solo lectura.", "text/plain; charset=utf-8")

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    servidor.daemon_threads = True
    return servidor


def principal() -> None:
    parser = argparse.ArgumentParser(description="Dashboard local de RSI, sin API ni cambios de versión.")
    parser.add_argument("--puerto", type=int, default=8765)
    argumentos = parser.parse_args()
    if not 1 <= argumentos.puerto <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    with crear_servidor(Path(__file__).resolve().parents[1], argumentos.puerto) as servidor:
        print(f"Panel de Pasteles: http://127.0.0.1:{servidor.server_port}", flush=True)
        print("Solo lectura · sin gasto de API · Ctrl+C para cerrar", flush=True)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    principal()
