"""Perfil aislado de Hermes; configuración sin credenciales del proveedor."""

from __future__ import annotations

import json
import os
import re
import shutil
import secrets
import subprocess
import sys
from pathlib import Path

PERFIL = "pasteles"
MODELO = "claude-haiku-5-5"
PUERTO = 8787


def raiz_proyecto() -> Path:
    return Path(__file__).resolve().parent.parent


def ruta_datos() -> Path:
    ruta = (raiz_proyecto() / ".runtime").resolve()
    if os.environ.get("PASTELES_DATOS") and Path(os.environ["PASTELES_DATOS"]).resolve() != ruta:
        raise ValueError("No se puede cambiar la cuenta del piloto mediante PASTELES_DATOS.")
    return ruta


def ruta_perfil() -> Path:
    return Path.home() / ".hermes" / "profiles" / PERFIL


def configuracion(raiz: Path, python: str, datos: Path, *, puerto: int = PUERTO,
                  publico: bool = False) -> dict:
    """JSON es también YAML: no se necesita un parser adicional para generarlo."""
    return {
        "_config_version": 51,
        "model": {"provider": "pasteles-local", "default": MODELO, "streaming": False},
        "providers": {"pasteles-local": {
            "api": f"http://127.0.0.1:{puerto}", "transport": "anthropic_messages",
            "key_env": "PASTELES_PROXY_KEY", "default_model": MODELO,
            "discover_models": False, "catalog_provider": "anthropic", "context_length": 64000,
        }},
        "fallback_providers": [],
        "agent": {"max_turns": 6, "reasoning_effort": "low", "run_budget_seconds": 180},
        "auth": {"adopt_external_logins": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "compression": {"enabled": False},
        "auxiliary": {"title_generation": {"enabled": False}},
        "stt": {"enabled": False},
        "tools": {"tool_search": {"enabled": "off"}, "connectors": {"enabled": False}},
        "mcp_servers": {"pasteles": {
            "command": python, "args": ["-m", "pasteles", "mcp"], "cwd": str(raiz),
            "env": {"PYTHONDONTWRITEBYTECODE": "1"},
            "tools": {"include": ["ver_catalogo", "recomendar_pasteles", "cotizar_pedido"],
                      "prompts": False, "resources": False},
        }},
        "platform_toolsets": {"cli": ["mcp-pasteles"], "telegram": ["mcp-pasteles"]},
        "plugins": {"enabled": ["pasteles-pagos"], "isolation": "in_process",
                    "auto_update_check_hours": 0, "auto_apply": False},
        "gateway": {"standalone": True, "platforms": {"telegram": {
            "extra": {"dm_policy": "open" if publico else "allowlist", "group_policy": "disabled",
                      # Hermes interpreta [] como compatibilidad sin restricciones.
                      # Telegram nunca asigna el ID 0; activa la política sin admins.
                      "allow_admin_from": ["0"],
                      "user_allowed_commands": ["start", "new", "pagar", "pedido", "stop",
                                                "recordar", "olvidar", "preferencias", "compartir"],
                      "max_concurrent_updates": 4},
        }}},
        "display": {"streaming": False},
    }


def entorno_hermes(*, raiz: Path, datos: Path, clave_local: str = "",
                   publico: bool = False) -> dict[str, str]:
    """Hermes y sus subprocessos nunca reciben la llave Anthropic ni otros proveedores."""
    permitidas = {"HOME", "PATH", "LANG", "LC_ALL", "TERM", "USER", "LOGNAME",
                  "SSL_CERT_FILE", "SSL_CERT_DIR"}
    entorno = {k: v for k, v in os.environ.items() if k in permitidas}
    entorno.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PASTELES_RAIZ": str(raiz),
        "PASTELES_DATOS": str(datos), "PASTELES_PROXY_KEY": clave_local,
        "TELEGRAM_ALLOW_ALL_USERS": "true" if publico else "false",
        "GATEWAY_ALLOW_ALL_USERS": "false", "PASTELES_PUBLICO": "1" if publico else "0",
        "TELEGRAM_DM_POLICY": "open" if publico else "allowlist", "TELEGRAM_GROUP_POLICY": "disabled",
    })
    if publico or os.environ.get("PASTELES_RSI") == "1":
        entorno["PASTELES_RSI"] = "1"
    return entorno


def preparar_perfil(*, perfil: Path | None = None, raiz: Path | None = None,
                    datos: Path | None = None, crear_con_cli: bool = True,
                    publico: bool | None = None) -> Path:
    perfil = perfil or ruta_perfil()
    raiz = (raiz or raiz_proyecto()).resolve()
    datos = (datos or ruta_datos()).resolve()
    marcador = perfil / "pasteles.json"
    if perfil.is_symlink():
        raise ValueError("El perfil de Pasteles no puede ser un enlace simbólico.")
    anteriores = leer_entorno_perfil(perfil)
    if publico is None:
        publico = acceso_publico(anteriores)
    if perfil.exists() and not marcador.exists():
        raise ValueError("El perfil pasteles ya existe y no pertenece a este instalador.")
    if marcador.exists():
        anterior = json.loads(marcador.read_text(encoding="utf-8"))
        if anterior.get("raiz") != str(raiz):
            raise ValueError("El perfil pertenece a otra copia de Pasteles; no se reemplazó.")
        if anterior.get("datos") != str(datos):
            raise ValueError("El piloto ya tiene una cuenta persistente; no se puede cambiar su ruta.")
    if not perfil.exists() and crear_con_cli:
        hermes = shutil.which("hermes")
        if not hermes:
            raise ValueError("Hermes no está instalado o no aparece en PATH.")
        subprocess.run([hermes, "profile", "create", PERFIL, "--no-alias", "--no-skills"],
                       check=True, cwd=raiz,
                       env=entorno_hermes(raiz=raiz, datos=datos), timeout=120)
    perfil.mkdir(parents=True, exist_ok=True, mode=0o700)
    (perfil / "workspace").mkdir(exist_ok=True)
    (perfil / "config.yaml").write_text(
        json.dumps(configuracion(raiz, sys.executable, datos, publico=publico), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    shutil.copy2(raiz / "prompts" / "vendedor.md", perfil / "SOUL.md")
    plugin = perfil / "plugins" / "pasteles-pagos"
    shutil.copytree(raiz / "plugin_hermes", plugin, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    marcador.write_text(json.dumps({"raiz": str(raiz), "datos": str(datos), "version": 1}) + "\n")
    guardar_entorno_perfil(perfil, {
        "PASTELES_RAIZ": str(raiz), "PASTELES_DATOS": str(datos),
        "PASTELES_PROXY_KEY": anteriores.get("PASTELES_PROXY_KEY") or secrets.token_urlsafe(32),
        "PASTELES_PUBLICO": "1" if publico else "0",
        **({"PASTELES_RSI": "1"} if publico else {}),
    })
    return perfil


CLAVES_PERFIL = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "PASTELES_PROXY_KEY",
                "PASTELES_RAIZ", "PASTELES_DATOS", "PASTELES_RSI", "PASTELES_PUBLICO"}


def acceso_publico(valores: dict[str, str]) -> bool:
    valor = valores.get("PASTELES_PUBLICO", "0")
    if valor not in {"0", "1"}:
        raise ValueError("PASTELES_PUBLICO debe ser 0 o 1.")
    return valor == "1"


def leer_entorno_perfil(perfil: Path) -> dict[str, str]:
    destino = perfil / ".env"
    valores: dict[str, str] = {}
    if destino.is_file():
        for linea in destino.read_text(encoding="utf-8").splitlines():
            nombre, _, valor = linea.partition("=")
            if nombre in CLAVES_PERFIL:
                valor = valor.strip()
                valores[nombre] = json.loads(valor) if valor.startswith('"') else valor
    return valores


def guardar_entorno_perfil(perfil: Path, cambios: dict[str, str]) -> None:
    if set(cambios) - CLAVES_PERFIL or any('\n' in v or '\r' in v for v in cambios.values()):
        raise ValueError("Campo no permitido en el entorno privado del perfil.")
    valores = leer_entorno_perfil(perfil)
    valores.update(cambios)
    destino = perfil / ".env"
    if destino.is_symlink():
        raise ValueError("La configuración de Telegram no puede ser un enlace.")
    temporal = perfil / ".env.pasteles.tmp"
    descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
        for nombre, valor in sorted(valores.items()):
            archivo.write(f"{nombre}={json.dumps(valor)}\n")
    os.replace(temporal, destino)


def guardar_telegram(perfil: Path, token: str, usuario: str) -> None:
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("El token de BotFather no tiene un formato válido.")
    if not re.fullmatch(r"[1-9]\d{3,19}", usuario):
        raise ValueError("Se necesita tu ID numérico positivo de Telegram.")
    guardar_entorno_perfil(perfil, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_ALLOWED_USERS": usuario})


def leer_telegram(perfil: Path) -> dict[str, str]:
    valores = {k: v for k, v in leer_entorno_perfil(perfil).items()
               if k in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "PASTELES_PUBLICO"}}
    for nombre in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"):
        if os.environ.get(nombre):
            valores[nombre] = os.environ[nombre]
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", valores.get("TELEGRAM_BOT_TOKEN", "")):
        raise ValueError("Falta un token válido: ejecuta configurar --telegram desde tu terminal.")
    if not acceso_publico(valores) and not re.fullmatch(r"[1-9]\d{3,19}", valores.get("TELEGRAM_ALLOWED_USERS", "")):
        raise ValueError("Falta tu ID numérico de Telegram: ejecuta configurar --telegram.")
    return valores
