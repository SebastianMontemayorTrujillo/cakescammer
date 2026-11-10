"""Preferencias consentidas: datos enumerados, identidad del adaptador y archivos privados.

Este módulo no es una herramienta del modelo. El adaptador debe autenticar el
chat antes de construir Identidad; no se deserializan identidades recibidas del
cliente o del modelo. Las preferencias son sugerencias: nunca sustituyen datos
del turno y no describen alergias, fechas, precios ni disponibilidad.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pagos import Identidad

PREFERENCIAS = {
    "sabor": frozenset({"chocolate", "vainilla", "fresa"}),
    "modalidad": frozenset({"recoger", "entrega"}),
    "zona": frozenset({"centro", "norte"}),
    "idioma": frozenset({"es", "en"}),
}
_CLAVE = ".clave_contexto"
_BLOQUEO = ".bloqueo_contexto"
_BITACORA = "bitacora.jsonl"
_MAX_ARCHIVO = 2048


class ErrorContexto(ValueError):
    """Error seguro para el adaptador: no incluye identidad, rutas ni preferencias."""


def _validar_identidad(identidad: Identidad) -> str:
    if type(identidad) is not Identidad:
        raise ErrorContexto("Se requiere una identidad autenticada del adaptador.")
    for valor in (identidad.chat_id, identidad.usuario_id):
        if type(valor) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", valor):
            raise ErrorContexto("La identidad privada no es válida.")
    # Telegram privado identifica al interlocutor con el mismo ID que el chat.
    if identidad.chat_id != identidad.usuario_id:
        raise ErrorContexto("Las preferencias solo están disponibles en el chat privado propio.")
    for valor in (identidad.sesion_id, identidad.clave_sesion):
        if (type(valor) is not str or not valor.strip() or len(valor) > 512
                or any(ord(caracter) < 32 for caracter in valor)):
            raise ErrorContexto("Falta el contexto de la sesión autenticada.")
    return identidad.usuario_id


def _validar_preferencias(preferencias: object, *, permitir_vacio: bool = True) -> dict[str, str]:
    if type(preferencias) is not dict or (not preferencias and not permitir_vacio):
        raise ErrorContexto("Indica al menos una preferencia permitida.")
    if any(type(nombre) is not str or nombre not in PREFERENCIAS for nombre in preferencias):
        raise ErrorContexto("Solo se permiten sabor, modalidad, zona e idioma.")
    if any(type(valor) is not str or valor not in PREFERENCIAS[nombre]
           for nombre, valor in preferencias.items()):
        raise ErrorContexto("Hay una preferencia fuera de los valores permitidos.")
    return dict(preferencias)


def aplicar_preferencias(preferencias: dict[str, str], datos_turno: dict[str, Any]) -> dict[str, Any]:
    """Copia con precedencia absoluta del turno, incluso para valores vacíos o None."""
    defaults = _validar_preferencias(preferencias)
    if type(datos_turno) is not dict:
        raise ErrorContexto("Los datos del turno deben ser un objeto.")
    return {**defaults, **datos_turno}


def _json(datos: Any) -> bytes:
    return json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _pares_unicos(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    datos: dict[str, Any] = {}
    for nombre, valor in pares:
        if nombre in datos:
            raise ErrorContexto("El archivo de preferencias no es válido.")
        datos[nombre] = valor
    return datos


class AlmacenContexto:
    def __init__(self, directorio: Path) -> None:
        self.directorio = Path(directorio)
        if (not self.directorio.is_absolute() or len(self.directorio.parts) < 2
                or ".." in self.directorio.parts):
            raise ErrorContexto("El directorio de preferencias debe ser una ruta absoluta segura.")
        self._identificador_directorio: tuple[int, int] | None = None
        self._clave: bytes | None = None
        with self._sesion(crear=True) as directorio_fd:
            detalle = os.fstat(directorio_fd)
            self._identificador_directorio = (detalle.st_dev, detalle.st_ino)
            try:
                with self._archivo(directorio_fd, _CLAVE, os.O_RDONLY) as archivo:
                    clave = os.read(archivo, 33)
            except FileNotFoundError:
                if any(nombre.endswith(".json") for nombre in os.listdir(directorio_fd)):
                    raise ErrorContexto("Falta la clave local; no se reemplazará una cuenta existente.") from None
                clave = secrets.token_bytes(32)
                self._guardar_atomico(directorio_fd, _CLAVE, clave)
            if len(clave) != 32:
                raise ErrorContexto("La clave local no es válida; no se regenerará automáticamente.")
            self._clave = clave

    def _abrir_directorio(self, crear: bool) -> int:
        """Recorre componentes sin seguir enlaces; las operaciones usan el descriptor anclado."""
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for componente in self.directorio.parts[1:]:
                if crear:
                    try:
                        os.mkdir(componente, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                siguiente = os.open(componente, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     dir_fd=descriptor)
                os.close(descriptor)
                descriptor = siguiente
            detalle = os.fstat(descriptor)
            if detalle.st_uid != os.geteuid() or stat.S_IMODE(detalle.st_mode) != 0o700:
                raise ErrorContexto("El directorio de preferencias debe ser privado y del usuario actual.")
            actual = (detalle.st_dev, detalle.st_ino)
            if self._identificador_directorio is not None and actual != self._identificador_directorio:
                raise ErrorContexto("El directorio de preferencias cambió; se rechazó la operación.")
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    @contextmanager
    def _archivo(directorio: int, nombre: str, modo: int) -> Iterator[int]:
        descriptor = os.open(nombre, modo | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             0o600, dir_fd=directorio)
        try:
            detalle = os.fstat(descriptor)
            if (not stat.S_ISREG(detalle.st_mode) or detalle.st_nlink != 1
                    or detalle.st_uid != os.geteuid() or stat.S_IMODE(detalle.st_mode) != 0o600):
                raise ErrorContexto("Se rechazó un archivo de preferencias no privado o enlazado.")
            yield descriptor
        finally:
            os.close(descriptor)

    @contextmanager
    def _sesion(self, *, crear: bool = False) -> Iterator[int]:
        directorio = None
        try:
            directorio = self._abrir_directorio(crear)
            with self._archivo(directorio, _BLOQUEO, os.O_RDWR | os.O_CREAT) as bloqueo:
                fcntl.flock(bloqueo, fcntl.LOCK_EX)
                if self._clave is not None:
                    with self._archivo(directorio, _CLAVE, os.O_RDONLY) as archivo:
                        if not hmac.compare_digest(os.read(archivo, 33), self._clave):
                            raise ErrorContexto("La clave local cambió; se rechazó la operación.")
                yield directorio
        except OSError:
            raise ErrorContexto("No se pudo acceder de forma segura al contexto local.") from None
        finally:
            if directorio is not None:
                os.close(directorio)

    def _nombre(self, usuario: str) -> str:
        assert self._clave is not None
        return hmac.new(self._clave, b"pasteles/contexto/nombre/v1\0" + usuario.encode("ascii"),
                        hashlib.sha256).hexdigest() + ".json"

    def _firma(self, nombre: str, preferencias: dict[str, str]) -> str:
        assert self._clave is not None
        contenido = {"version": 1, "consentimiento": True, "preferencias": preferencias}
        return hmac.new(self._clave, b"pasteles/contexto/contenido/v1\0" + nombre.encode("ascii")
                        + b"\0" + _json(contenido), hashlib.sha256).hexdigest()

    def _leer(self, directorio: int, nombre: str) -> dict[str, str]:
        try:
            with self._archivo(directorio, nombre, os.O_RDONLY) as archivo:
                contenido = os.read(archivo, _MAX_ARCHIVO + 1)
        except FileNotFoundError:
            return {}
        if len(contenido) > _MAX_ARCHIVO:
            raise ErrorContexto("El archivo de preferencias excede el tamaño permitido.")
        try:
            datos = json.loads(contenido, object_pairs_hook=_pares_unicos)
        except (ValueError, UnicodeError, RecursionError):
            raise ErrorContexto("El archivo de preferencias no es válido.") from None
        if (type(datos) is not dict or set(datos) != {"version", "consentimiento", "preferencias", "firma"}
                or type(datos["version"]) is not int or datos["version"] != 1
                or datos["consentimiento"] is not True or type(datos["firma"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", datos["firma"])):
            raise ErrorContexto("El archivo de preferencias no acredita consentimiento válido.")
        preferencias = _validar_preferencias(datos["preferencias"], permitir_vacio=False)
        if not hmac.compare_digest(datos["firma"], self._firma(nombre, preferencias)):
            raise ErrorContexto("El archivo de preferencias no corresponde a esta cuenta.")
        return preferencias

    @staticmethod
    def _guardar_atomico(directorio: int, nombre: str, contenido: bytes) -> None:
        temporal = ".contexto-" + secrets.token_hex(16) + ".tmp"
        try:
            with AlmacenContexto._archivo(directorio, temporal, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as archivo:
                with os.fdopen(os.dup(archivo), "wb") as salida:
                    salida.write(contenido)
                    salida.flush()
                os.fsync(archivo)
            os.replace(temporal, nombre, src_dir_fd=directorio, dst_dir_fd=directorio)
            os.fsync(directorio)
        finally:
            try:
                os.unlink(temporal, dir_fd=directorio)
            except FileNotFoundError:
                pass

    @staticmethod
    def _anotar(directorio: int, evento: str) -> None:
        datos = {"ts": datetime.now(timezone.utc).isoformat(), "actor": "SISTEMA", "evento": evento}
        with AlmacenContexto._archivo(directorio, _BITACORA, os.O_WRONLY | os.O_CREAT | os.O_APPEND) as archivo:
            with os.fdopen(os.dup(archivo), "ab") as salida:
                salida.write(_json(datos) + b"\n")
                salida.flush()
            os.fsync(archivo)

    def recordar(self, identidad: Identidad, preferencias: dict[str, str], consentimiento: bool) -> dict[str, str]:
        """Reemplaza las preferencias solo con un consentimiento explícito para esta operación."""
        usuario = _validar_identidad(identidad)
        if type(consentimiento) is not bool or not consentimiento:
            raise ErrorContexto("Hace falta consentimiento explícito para guardar estas preferencias.")
        validadas = _validar_preferencias(preferencias, permitir_vacio=False)
        with self._sesion() as directorio:
            nombre = self._nombre(usuario)
            self._leer(directorio, nombre)  # No sobrescribir un archivo ajeno, enlazado o corrupto.
            datos = {"version": 1, "consentimiento": True, "preferencias": validadas,
                     "firma": self._firma(nombre, validadas)}
            self._guardar_atomico(directorio, nombre, _json(datos) + b"\n")
            self._anotar(directorio, "preferencias_guardadas")
        return dict(validadas)

    def leer(self, identidad: Identidad) -> dict[str, str]:
        usuario = _validar_identidad(identidad)
        with self._sesion() as directorio:
            preferencias = self._leer(directorio, self._nombre(usuario))
            self._anotar(directorio, "preferencias_leidas")
        return preferencias

    def olvidar(self, identidad: Identidad) -> bool:
        """Elimina solamente el archivo propio; la bitácora no conserva sus valores ni identidad."""
        usuario = _validar_identidad(identidad)
        with self._sesion() as directorio:
            nombre = self._nombre(usuario)
            try:
                # El nombre HMAC acredita el archivo propio; poder borrar no depende
                # de que su contenido siga siendo legible o válido.
                with self._archivo(directorio, nombre, os.O_RDONLY):
                    existe = True
            except FileNotFoundError:
                existe = False
            if existe:
                os.unlink(nombre, dir_fd=directorio)
                os.fsync(directorio)
            self._anotar(directorio, "preferencias_olvidadas")
        return existe
