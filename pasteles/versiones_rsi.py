"""Versiones declarativas e inmutables: el candidato no puede cambiar al juez."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def semilla() -> dict[str, Any]:
    return {
        'harness': {'cotizar_automaticamente': False, 'usar_preferencias': False,
                    'preguntas_por_turno': 2, 'estrategia_comercial': 'ajuste',
                    'cierre_consultivo': False},
        'skills': {
            'vendedor': 'Extrae los datos del pedido. Indica cotizar=true cuando el cliente pide una cotización. Nunca inventes datos.',
            'constructor': 'Formula una hipótesis general a partir de fallos agregados. Cambia una sola decisión del harness y describe cómo refutar la hipótesis.',
        },
    }


def validar_version(version: object) -> dict[str, Any]:
    if not isinstance(version, dict) or set(version) != {'harness', 'skills'}:
        raise ValueError('La versión solo admite harness y skills.')
    harness, skills = version['harness'], version['skills']
    if not isinstance(harness, dict) or set(harness) != set(semilla()['harness']):
        raise ValueError('El harness contiene capacidades no autorizadas.')
    for campo in ('cotizar_automaticamente', 'usar_preferencias', 'cierre_consultivo'):
        if type(harness[campo]) is not bool:
            raise ValueError('Las decisiones del harness deben ser booleanas.')
    if type(harness['preguntas_por_turno']) is not int or harness['preguntas_por_turno'] not in (1, 2):
        raise ValueError('Se permiten una o dos preguntas por turno.')
    if harness['estrategia_comercial'] not in ('ajuste', 'valor'):
        raise ValueError('Estrategia comercial desconocida.')
    if not isinstance(skills, dict) or set(skills) != {'vendedor', 'constructor'}:
        raise ValueError('Solo se admiten las skills vendedor y constructor.')
    for contenido in skills.values():
        if not isinstance(contenido, str) or not 20 <= len(contenido) <= 4000 or '\x00' in contenido:
            raise ValueError('Skill inválida o demasiado grande.')
    return json.loads(json.dumps(version, ensure_ascii=False, allow_nan=False))


def validar_sucesor(padre: dict, candidato: object) -> dict:
    padre, candidato = validar_version(padre), validar_version(candidato)
    cambios = [k for k in padre['harness'] if padre['harness'][k] != candidato['harness'][k]]
    if len(cambios) != 1:
        raise ValueError('Cada hipótesis debe cambiar exactamente una decisión del harness.')
    if padre['skills']['constructor'] == candidato['skills']['constructor']:
        raise ValueError('El sucesor debe actualizar la skill del constructor de la siguiente generación.')
    return candidato


def huella_version(version: dict) -> str:
    contenido = json.dumps(validar_version(version), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(contenido.encode()).hexdigest()


def _directorio(ruta: Path) -> Path:
    ruta = Path(ruta).absolute()
    if any(p.is_symlink() for p in [ruta, *ruta.parents]):
        raise ValueError('Las versiones no admiten directorios enlazados.')
    ruta.mkdir(parents=True, exist_ok=True, mode=0o700)
    return ruta


def _leer(ruta: Path, limite: int = 20000) -> str:
    if (any(p.is_symlink() for p in [ruta, *ruta.parents]) or not ruta.is_file()
            or ruta.stat().st_nlink != 1 or ruta.stat().st_size > limite):
        raise ValueError('Artefacto de versión inválido.')
    return ruta.read_text(encoding='utf-8')


def _nuevo(ruta: Path, contenido: str) -> None:
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as archivo:
        archivo.write(contenido)
        archivo.flush()
        os.fsync(archivo.fileno())


def _huella_nodo(contenido: str, padre: str | None) -> str:
    return hashlib.sha256(json.dumps({'contenido_sha256': contenido, 'padre': padre},
                                     sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def guardar_version(directorio: Path, version: dict, padre: str | None = None) -> str:
    version = validar_version(version)
    if padre is not None and not re.fullmatch(r'[a-f0-9]{64}', padre):
        raise ValueError('Huella del padre inválida.')
    if padre is not None:
        cargar_version(directorio, padre)
    contenido = huella_version(version)
    identificador = _huella_nodo(contenido, padre)
    raiz = _directorio(Path(directorio) / 'versiones')
    carpeta = raiz / identificador
    if carpeta.exists():
        if cargar_version(directorio, identificador) != version:
            raise ValueError('La versión persistida no coincide.')
        return identificador
    carpeta.mkdir(mode=0o700)
    _nuevo(carpeta / 'harness.json', json.dumps(version['harness'], ensure_ascii=False, indent=2)+'\n')
    for nombre, texto_skill in version['skills'].items():
        destino = carpeta / 'skills' / nombre
        destino.mkdir(parents=True, mode=0o700)
        _nuevo(destino / 'SKILL.md', texto_skill)
    _nuevo(carpeta / 'manifest.json', json.dumps({'id': identificador, 'padre': padre,
                                                'contenido_sha256': contenido, 'formato': 2})+'\n')
    return identificador


def cargar_version(directorio: Path, identificador: str) -> dict:
    if not isinstance(identificador, str) or not re.fullmatch(r'[a-f0-9]{64}', identificador):
        raise ValueError('Identificador de versión inválido.')
    carpeta = Path(directorio) / 'versiones' / identificador
    if any(p.is_symlink() for p in [carpeta, *carpeta.parents]):
        raise ValueError('La versión no admite enlaces.')
    manifiesto = json.loads(_leer(carpeta / 'manifest.json'))
    version = validar_version({'harness': json.loads(_leer(carpeta / 'harness.json')),
                              'skills': {n: _leer(carpeta / 'skills' / n / 'SKILL.md', 16000)
                                         for n in ('vendedor', 'constructor')}})
    padre = manifiesto.get('padre')
    contenido = huella_version(version)
    if (set(manifiesto) != {'id', 'padre', 'contenido_sha256', 'formato'} or manifiesto['formato'] != 2
            or padre is not None and (not isinstance(padre, str) or not re.fullmatch(r'[a-f0-9]{64}', padre)
                                      or not (Path(directorio)/'versiones'/padre/'manifest.json').is_file())
            or manifiesto.get('id') != identificador or manifiesto.get('contenido_sha256') != contenido
            or _huella_nodo(contenido, padre) != identificador):
        raise ValueError('La huella de la versión cambió.')
    return version


def activar(directorio: Path, identificador: str) -> None:
    cargar_version(directorio, identificador)
    raiz = _directorio(directorio)
    destino = raiz / 'activa.json'
    if destino.is_symlink():
        raise ValueError('El puntero activo no admite enlaces.')
    temporal = raiz / ('.activa-' + os.urandom(8).hex())
    _nuevo(temporal, json.dumps({'id': identificador})+'\n')
    os.replace(temporal, destino)


def id_activa(directorio: Path) -> str | None:
    destino = Path(directorio) / 'activa.json'
    if not destino.exists() and not destino.is_symlink():
        return None
    identificador = json.loads(_leer(destino))['id']
    cargar_version(directorio, identificador)
    return identificador


def cargar_activa(directorio: Path) -> dict:
    identificador = id_activa(directorio)
    if identificador is None:
        return semilla()
    return cargar_version(directorio, identificador)
