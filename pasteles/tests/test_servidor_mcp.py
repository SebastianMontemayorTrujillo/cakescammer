import json
import os
import subprocess
import sys
from datetime import date
from io import StringIO
from pathlib import Path

from pasteles.servidor_mcp import Servidor, servir
from pasteles.negocio import Pasteleria


def inicializar() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "prueba", "version": "1"}}}


def llamada(nombre: str, argumentos: object) -> dict:
    return {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": nombre, "arguments": argumentos}}


def test_negociacion_y_descubrimiento() -> None:
    servidor = Servidor()
    assert servidor.responder(inicializar())["result"]["protocolVersion"] == "2024-11-05"
    assert servidor.responder({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    herramientas = servidor.responder({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {h["name"] for h in herramientas} == {"ver_catalogo", "recomendar_pasteles", "cotizar_pedido"}


def test_cotizacion_por_protocolo() -> None:
    servidor = Servidor(Pasteleria(hoy=date(2026, 11, 9)))
    servidor.responder(inicializar())
    respuesta = servidor.responder(llamada("cotizar_pedido", {
        "producto_id": "chocolate_12", "asistentes": 10, "fecha": "2026-11-13",
        "modalidad": "entrega", "zona": "centro", "restriccion_alimentaria": "ninguna",
    }))
    assert json.loads(respuesta["result"]["content"][0]["text"])["total_centavos"] == 71000


def test_errores_recuperables_y_metodos_no_admitidos() -> None:
    servidor = Servidor()
    assert servidor.responder(llamada("ver_catalogo", {}))["error"]["code"] == -32000
    servidor.responder(inicializar())
    assert servidor.responder(llamada("cotizar_pedido", []))["result"]["isError"] is True
    assert servidor.responder(llamada("borrar_pedido", {}))["error"]["code"] == -32602
    assert servidor.responder({"jsonrpc": "2.0", "id": 4, "method": "desconocido"})["error"]["code"] == -32601
    assert servidor.responder(llamada("ver_catalogo", {}))["result"]["content"]


def test_json_invalido_no_rompe_siguiente_solicitud() -> None:
    entrada = StringIO('no es json\n[]\n' + json.dumps(inicializar()) + '\n')
    salida = StringIO()
    servir(entrada, salida)
    respuestas = [json.loads(linea) for linea in salida.getvalue().splitlines()]
    assert respuestas[0]["error"]["code"] == -32700
    assert respuestas[1]["error"]["code"] == -32600
    assert respuestas[2]["result"]["serverInfo"]["name"] == "pasteles-demo"


def test_cli_stdio_no_contamina_protocolo_y_termina_al_cerrar_entrada() -> None:
    solicitudes = [inicializar(), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   llamada("ver_catalogo", {})]
    entorno = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
    proceso = subprocess.run(
        [sys.executable, "-m", "pasteles", "mcp"],
        input="\n".join(json.dumps(s) for s in solicitudes) + "\n",
        text=True, capture_output=True, timeout=10,
        cwd=Path(__file__).resolve().parents[2], env=entorno,
    )
    assert proceso.returncode == 0, proceso.stderr
    respuestas = [json.loads(linea) for linea in proceso.stdout.splitlines()]
    assert len(respuestas) == 2
    assert respuestas[1]["id"] == 3
    assert proceso.stderr == ""
