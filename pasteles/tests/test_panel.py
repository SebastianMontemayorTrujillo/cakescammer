"""El panel solo expone recursos públicos seleccionados y agregados."""

from http.client import HTTPConnection
from threading import Thread

import pytest

from pasteles.panel import crear_servidor


@pytest.fixture
def servidor_panel(tmp_path):
    web = tmp_path / "pasteles/web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<h1>Panel local</h1>")
    (tmp_path / ".env").write_text("SECRETO_NO_PUBLICO")
    with crear_servidor(tmp_path, 0) as servidor:
        hilo = Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        yield servidor, tmp_path
        servidor.shutdown()
        hilo.join(timeout=2)


def solicitar(servidor, ruta="/", metodo="GET", headers=None):
    conexion = HTTPConnection("127.0.0.1", servidor.server_port, timeout=3)
    conexion.request(metodo, ruta, headers=headers or {})
    respuesta = conexion.getresponse()
    estado, cabeceras, cuerpo = respuesta.status, dict(respuesta.getheaders()), respuesta.read()
    conexion.close()
    return estado, cabeceras, cuerpo


def test_recursos_agregados_y_cabeceras(servidor_panel):
    servidor, _ = servidor_panel
    assert servidor.server_address[0] == "127.0.0.1"
    estado, cabeceras, cuerpo = solicitar(servidor)
    assert estado == 200 and b"Panel local" in cuerpo
    assert cabeceras["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in cabeceras["Content-Security-Policy"]
    estado, cabeceras, cuerpo = solicitar(servidor, "/api/panel")
    assert estado == 200 and b'"modos"' in cuerpo
    assert "Access-Control-Allow-Origin" not in cabeceras
    assert b"SECRETO_NO_PUBLICO" not in cuerpo


def test_nunca_publica_directorios_secretos_ni_enlaces(servidor_panel):
    servidor, raiz = servidor_panel
    for ruta in ("/.env", "/../.env", "/%2e%2e/.env", "/.runtime/", "/resultados/", "/api/panel/../.env"):
        estado, _, cuerpo = solicitar(servidor, ruta)
        assert estado == 404
        assert b"SECRETO_NO_PUBLICO" not in cuerpo
    (raiz / "pasteles/web/panel.css").symlink_to(raiz / ".env")
    assert solicitar(servidor, "/panel.css")[0] == 404
    (raiz / "pasteles/web/panel.css").unlink()
    (raiz / "pasteles/web/panel.css").hardlink_to(raiz / ".env")
    assert solicitar(servidor, "/panel.css")[0] == 404


def test_bloquea_mutacion_y_origen_externo(servidor_panel):
    servidor, _ = servidor_panel
    assert solicitar(servidor, "/api/panel", "POST")[0] == 405
    assert solicitar(servidor, headers={"Host": "externo.example"})[0] == 403
    assert solicitar(servidor, "/api/panel", headers={"Origin": "https://externo.example"})[0] == 403
    assert solicitar(servidor, metodo="HEAD")[2] == b""
