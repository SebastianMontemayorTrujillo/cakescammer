"""Prueba Hermes instalado + MCP + proxy con respuestas falsas y perfil temporal."""

from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from pasteles.configuracion import (configuracion, entorno_hermes, preparar_perfil,
                                    guardar_entorno_perfil)
from pasteles.llm import ClienteFalso, MODELO
from pasteles.negocio import Pasteleria
from pasteles.proxy import crear_servidor


def respuesta(numero: int, contenido: dict, *, herramienta: bool = True) -> dict:
    return {"id": f"msg_prueba_{numero}", "type": "message", "role": "assistant", "model": MODELO,
            "content": [contenido], "stop_reason": "tool_use" if herramienta else "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}


def llamar(numero: int, nombre: str, argumentos: dict) -> dict:
    return respuesta(numero, {"type": "tool_use", "id": f"tool_prueba_{numero}",
                              "name": f"mcp__pasteles__{nombre}", "input": argumentos})


def principal() -> None:
    hermes = shutil.which("hermes")
    if not hermes:
        raise SystemExit("No se encontró Hermes instalado.")
    # Verifica la semántica efectiva del control de comandos del Hermes instalado.
    archivo_politica = Path.home() / '.hermes/hermes-agent/gateway/slash_access.py'
    spec = importlib.util.spec_from_file_location('politica_hermes_prueba', archivo_politica)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    cfg_base = configuracion(RAIZ, sys.executable, RAIZ / '.runtime')
    politica = modulo.policy_from_extra(cfg_base['gateway']['platforms']['telegram']['extra'], 'dm')
    assert politica.can_run('123456789', 'pagar')
    assert not politica.can_run('123456789', 'model')
    fecha = (Pasteleria().hoy() + timedelta(days=4)).isoformat()
    while fecha in Pasteleria().catalogo['fechas_cerradas']:
        from datetime import date
        fecha = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
    cliente = ClienteFalso([
        llamar(1, "ver_catalogo", {}),
        llamar(2, "recomendar_pasteles", {"asistentes": 10, "presupuesto_centavos": 75000,
                                           "sabor": "chocolate"}),
        llamar(3, "cotizar_pedido", {"producto_id": "chocolate_12", "asistentes": 10,
                                    "presupuesto_centavos": 75000, "fecha": fecha,
                                    "modalidad": "entrega", "zona": "centro",
                                    "restriccion_alimentaria": "ninguna"}),
        respuesta(4, {"type": "text", "text": "SIMULACIÓN verificada: total $710 MXN."}, herramienta=False),
    ])
    clave = "prueba-local-sin-acceso-a-proveedores-externos"
    servidor = crear_servidor(cliente, puerto=0, clave_local=clave)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        # Un home reconocido como perfil reutiliza el runtime instalado de Hermes.
        perfiles = Path.home() / '.hermes/profiles'
        perfiles.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pasteles-prueba-", dir=perfiles) as temporal:
            perfil = Path(temporal)
            perfil.rmdir()  # preparar_perfil crea este directorio vacío propiedad de la prueba.
            datos = Path(temporal) / "datos"
            preparar_perfil(perfil=perfil, raiz=RAIZ, datos=datos, crear_con_cli=False)
            guardar_entorno_perfil(perfil, {'PASTELES_PROXY_KEY': clave,
                                           'TELEGRAM_ALLOWED_USERS': '123456789'})
            cfg = configuracion(RAIZ, sys.executable, datos, puerto=servidor.server_port)
            (perfil / "config.yaml").write_text(json.dumps(cfg), encoding="utf-8")
            # Mismo perfil restrictivo; sin bot conectado ni llave Anthropic.
            entorno = entorno_hermes(raiz=RAIZ, datos=datos, clave_local=clave)
            entorno.update({"HERMES_HOME": str(perfil), "TELEGRAM_ALLOWED_USERS": "123456789"})
            comandos = [
                ["plugins", "doctor", "--ci", str(RAIZ / "plugin_hermes")],
                ["mcp", "test", "pasteles"],
                ["chat", "--oneshot", "-Q", "-q", "Cotiza chocolate para 10, entrega centro, "
                 f"{fecha}, presupuesto $750, sin restricciones. Usa las tres herramientas."],
            ]
            evidencias = []
            for comando in comandos:
                print('Verificando Hermes: ' + ' '.join(comando[:3]), flush=True)
                proceso = subprocess.run([hermes, *comando], cwd=perfil / "workspace", env=entorno,
                                         text=True, capture_output=True, timeout=90)
                evidencias.append({"comando": comando[:3], "codigo": proceso.returncode,
                                   "salida": proceso.stdout, "errores": proceso.stderr})
                if proceso.returncode != 0:
                    registros = {}
                    for registro in (perfil / 'logs').glob('*.log'):
                        texto = registro.read_text(errors='replace')
                        registros[registro.name] = texto[-16000:].replace(clave, '[CLAVE_LOCAL]')
                    print(json.dumps({"tipo": "INTEGRACION_HERMES_FALSA", "evidencias": evidencias},
                                     ensure_ascii=False, indent=2))
                    print(json.dumps({'llamadas': len(cliente.solicitudes), 'diagnostico': registros},
                                     ensure_ascii=False, indent=2))
                    raise SystemExit(1)
            nombres = {h["name"] for s in cliente.solicitudes for h in s.get("tools", [])}
            esperadas = {f"mcp__pasteles__{n}" for n in (
                "ver_catalogo", "recomendar_pasteles", "cotizar_pedido")}
            resultados = [b for s in cliente.solicitudes for m in s['messages']
                          if isinstance(m['content'], list) for b in m['content']
                          if b.get('type') == 'tool_result']
            if (len(cliente.solicitudes) != 4 or nombres != esperadas
                    or not any('71000' in json.dumps(b) for b in resultados)
                    or 'SIMULACIÓN verificada' not in evidencias[-1]['salida']):
                print(json.dumps({"evidencias": evidencias, "llamadas": len(cliente.solicitudes),
                                  "herramientas": sorted(nombres)}, ensure_ascii=False, indent=2))
                raise SystemExit("No se verificó el recorrido completo de Hermes y sus herramientas.")
            print(json.dumps({"tipo": "INTEGRACION_HERMES_FALSA", "estado": "CUMPLE",
                              "modelo_evaluado": False, "costo_api_usd": "0",
                              "llamadas_falsas": 4, "herramientas": sorted(nombres),
                              "cotizacion_centavos": 71000,
                              "checks": ["plugin_doctor", "mcp", "conversacion_con_3_herramientas"]},
                             ensure_ascii=False, indent=2))
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


if __name__ == '__main__':
    principal()
