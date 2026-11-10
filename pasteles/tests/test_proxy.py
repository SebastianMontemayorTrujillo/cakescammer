import http.client
import json
from contextlib import contextmanager
from threading import Thread

import pytest

from pasteles.llm import ClienteFalso, MODELO
from pasteles.presupuesto import PresupuestoAgotado
from pasteles.proxy import crear_servidor


CLAVE = "credencial-local-ficticia-para-tests-1234"


@contextmanager
def servidor(cliente):
    instancia = crear_servidor(cliente, puerto=0, clave_local=CLAVE)
    hilo = Thread(target=instancia.serve_forever, daemon=True)
    hilo.start()
    try:
        yield instancia.server_address[1]
    finally:
        instancia.shutdown()
        instancia.server_close()
        hilo.join(timeout=5)


def enviar(puerto, metodo, ruta, cuerpo=None, cabeceras=None):
    conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
    try:
        conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras or {})
        respuesta = conexion.getresponse()
        return respuesta.status, json.loads(respuesta.read())
    finally:
        conexion.close()


def peticion():
    return json.dumps({"model": MODELO, "max_tokens": 100,
                       "messages": [{"role": "user", "content": "Hola"}]})


@pytest.mark.parametrize("cabeceras", [{"x-api-key": CLAVE}, {"Authorization": "Bearer " + CLAVE}])
def test_roundtrip_autenticado(cabeceras):
    cliente = ClienteFalso([{"id": "msg_falso", "content": [{"type": "text", "text": "SIMULACION"}]}])
    with servidor(cliente) as puerto:
        estado, contenido = enviar(puerto, "POST", "/v1/messages", peticion(), cabeceras)
    assert estado == 200
    assert contenido["id"] == "msg_falso"
    assert len(cliente.solicitudes) == 1


def test_salud_no_revela_credenciales_y_sin_autenticacion_no_hay_api():
    cliente = ClienteFalso()
    with servidor(cliente) as puerto:
        estado, salud = enviar(puerto, "GET", "/salud")
        assert estado == 200
        assert salud == {"estado": "listo", "servicio": "pasteles"}
        estado, error = enviar(puerto, "POST", "/v1/messages", peticion())
        assert estado == 401
        assert CLAVE not in json.dumps(error)
    assert not cliente.solicitudes


@pytest.mark.parametrize("cuerpo", ["{", "null", '{"model": NaN}'])
def test_json_invalido_no_llega_al_modelo(cuerpo):
    cliente = ClienteFalso()
    with servidor(cliente) as puerto:
        estado, _ = enviar(puerto, "POST", "/v1/messages", cuerpo, {"x-api-key": CLAVE})
    assert estado == 400
    assert not cliente.solicitudes


def test_presupuesto_y_errores_se_exponen_sin_detalles():
    cliente = ClienteFalso([PresupuestoAgotado("detalle-privado")])
    with servidor(cliente) as puerto:
        estado, respuesta = enviar(puerto, "POST", "/v1/messages", peticion(), {"x-api-key": CLAVE})
    assert estado == 402
    assert "detalle-privado" not in json.dumps(respuesta)


def test_no_permite_exposicion_publica_ni_clave_vacia():
    with pytest.raises(ValueError, match="127.0.0.1"):
        crear_servidor(ClienteFalso(), host="0.0.0.0", clave_local=CLAVE)
    with pytest.raises(ValueError, match="credencial"):
        crear_servidor(ClienteFalso())
