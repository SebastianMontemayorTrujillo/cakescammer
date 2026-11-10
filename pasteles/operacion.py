"""Arranque supervisado del proxy local y del gateway privado de Hermes."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .configuracion import (PERFIL, PUERTO, entorno_hermes, leer_telegram, leer_entorno_perfil,
                            raiz_proyecto, ruta_datos, ruta_perfil)


def diagnostico() -> dict:
    perfil = ruta_perfil()
    try:
        leer_telegram(perfil)
        telegram = True
    except ValueError:
        telegram = False
    return {"proyecto": str(raiz_proyecto()), "hermes_instalado": bool(shutil.which("hermes")),
            "perfil_preparado": (perfil / "pasteles.json").is_file(),
            "telegram_configurado": telegram,
            "anthropic_en_entorno": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "modelo": "claude-haiku-5-5", "tope_usd": "5.00",
            "datos": str(ruta_datos()), "simulacion": True}


@contextmanager
def bloqueo_exclusivo(datos: Path) -> Iterator[None]:
    """Conversaciones y evals comparten cuenta; no se ejecutan simultáneamente."""
    datos.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (datos / "ejecucion.lock").open("a+") as candado:
        try:
            fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Ya hay un gateway o una evaluación de Pasteles en ejecución.") from None
        yield


def iniciar() -> int:
    from .llm import ClienteAnthropic
    from .proxy import crear_servidor

    perfil, raiz, datos = ruta_perfil(), raiz_proyecto(), ruta_datos()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("Falta ANTHROPIC_API_KEY; usa ./INICIAR.sh para ingresarla sin guardarla.")
    if not (perfil / "pasteles.json").is_file():
        raise ValueError("Primero ejecuta configurar para preparar el perfil de Pasteles.")
    marcador = json.loads((perfil / "pasteles.json").read_text())
    if marcador.get("raiz") != str(raiz) or marcador.get("datos") != str(datos):
        raise ValueError("El perfil y esta instalación no coinciden; ejecuta configurar.")
    telegram = leer_telegram(perfil)
    hermes = shutil.which("hermes")
    if not hermes:
        raise ValueError("No se encontró Hermes en PATH.")
    with bloqueo_exclusivo(datos):
        clave = leer_entorno_perfil(perfil).get('PASTELES_PROXY_KEY', '')
        if len(clave) < 32:
            raise ValueError("Falta la credencial del proxy local; ejecuta configurar.")
        cliente = ClienteAnthropic(datos, limite=os.environ.get("PRESUPUESTO_USD", "5.00"))
        servidor = crear_servidor(cliente, puerto=PUERTO, clave_local=clave)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        entorno = entorno_hermes(raiz=raiz, datos=datos, clave_local=clave,
                                 publico=telegram.get("PASTELES_PUBLICO") == "1")
        entorno.update(telegram)
        proceso = None
        anteriores: dict[int, object] = {}
        interrumpido = threading.Event()

        def detener(signum: int, frame: object) -> None:
            interrumpido.set()

        try:
            for senal in (signal.SIGTERM, signal.SIGINT):
                anteriores[senal] = signal.signal(senal, detener)
            proceso = subprocess.Popen([hermes, "-p", PERFIL, "gateway", "run", "--external-supervisor"],
                                       cwd=perfil / "workspace", env=entorno, start_new_session=True)
            acceso = "abierto a cualquier cuenta por chat privado" if telegram.get("PASTELES_PUBLICO") == "1" else "privado autorizado"
            print(f"Pasteles iniciado: Telegram {acceso}, catálogo y pagos de SIMULACIÓN.", flush=True)
            print("Para detener el gateway y el proxy, presiona Ctrl+C. Tope acumulado: 5 USD.", flush=True)
            while proceso.poll() is None and not interrumpido.wait(0.2):
                pass
            return proceso.returncode or 0
        finally:
            if proceso is not None and proceso.poll() is None:
                os.killpg(proceso.pid, signal.SIGTERM)
                try:
                    proceso.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proceso.pid, signal.SIGKILL)
                    proceso.wait()
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=5)
            for senal, anterior in anteriores.items():
                signal.signal(senal, anterior)
