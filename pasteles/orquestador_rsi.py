"""Ciclo RSI acotado, con juez independiente y evolución heredada del constructor."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constructor_rsi import proponer
from .evaluacion_rsi import decidir, evaluar_version, validar_instrumento
from .versiones_rsi import activar, cargar_activa, cargar_version, guardar_version, huella_version, id_activa


def _guardar(ruta: Path, datos: Any) -> None:
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, allow_nan=False)
        archivo.write('\n')


def _anotar(directorio: Path, evento: str, **datos: Any) -> None:
    archivo = directorio / 'bitacora.jsonl'
    descriptor = os.open(archivo, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a', encoding='utf-8') as salida:
        salida.write(json.dumps({'actor': 'SISTEMA', 'fecha': datetime.now(timezone.utc).isoformat(),
                                'evento': evento, **datos}, ensure_ascii=False)+'\n')
        salida.flush()
        os.fsync(salida.fileno())


def _comercial(version: dict) -> dict:
    from .evaluacion_ventas import evaluar_ventas
    return evaluar_ventas(version)


def _compuerta(antes: dict, despues: dict, ventas_antes: dict, ventas_despues: dict) -> dict:
    from .evaluacion_ventas import comparar_ventas
    arnes = decidir(antes, despues)
    ventas = comparar_ventas(ventas_antes, ventas_despues)
    # El instrumento RSI original conserva su dictamen. Esta compuerta nueva
    # permite una mejora comercial con empate funcional, nunca una regresión.
    arnes_neutral = arnes['razones'] == ['No hay mejora funcional demostrada.']
    comercial_seguro = ventas.get('aceptado') is True or ventas.get('neutral') is True
    aceptado = (arnes['aceptado'] or arnes_neutral) and comercial_seguro and (
        arnes['victorias'] > 0 or ventas.get('victorias', 0) > 0)
    return {'aceptado': bool(aceptado), 'arnes': arnes, 'ventas': ventas,
            'motivo': 'Mejora sin regresiones funcionales, comerciales ni de seguridad.' if aceptado else
                      'El candidato no supera las compuertas independientes.'}


def ejecutar_ciclo(directorio: Path, salida: Path, *, cliente: Any = None,
                   generaciones: int = 4) -> dict:
    if type(generaciones) is not int or not 1 <= generaciones <= 5:
        raise ValueError('El ciclo admite entre una y cinco propuestas.')
    real = getattr(cliente, 'es_real', False) is True
    if cliente is not None and not real:
        raise ValueError('Usa simulación explícita sin cliente o un cliente real con presupuesto.')
    directorio = Path(directorio).absolute()
    salida = Path(salida).absolute()
    if any(p.is_symlink() for ruta in (directorio, salida) for p in [ruta, *ruta.parents]):
        raise ValueError('El ciclo no admite directorios enlazados.')
    directorio.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directorio / 'ciclo.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a+') as candado:
        if os.fstat(candado.fileno()).st_nlink != 1:
            raise ValueError('El bloqueo no admite enlaces.')
        try:
            fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Ya hay un ciclo RSI en ejecución.') from None
        return _ejecutar(directorio, Path(salida), cliente, generaciones, real)


def _ejecutar(directorio: Path, salida: Path, cliente: Any, generaciones: int, real: bool) -> dict:
    instrumento = validar_instrumento()
    identificador = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:10]
    carpeta = salida / identificador
    carpeta.mkdir(parents=True, exist_ok=False, mode=0o700)
    tipo = 'RSI_MODELO_REAL' if real else 'SIMULACION_RSI'
    version = cargar_activa(directorio)
    padre = id_activa(directorio) or guardar_version(directorio, version)
    _anotar(directorio, 'inicio_ciclo', corrida=identificador, tipo=tipo, padre=padre)
    resultado = {'tipo': tipo, 'corrida': identificador, 'carpeta': str(carpeta),
                 'semilla': padre, 'activa_final': padre, 'generaciones': [],
                 'modelo_evaluado': real, 'estado': 'EN_CURSO',
                 'suite_sha256': instrumento['huella_instrumento'],
                 'limites': ['No mide ventas reales ni aprendizaje de pesos.',
                             'El juez y las fronteras de seguridad no son editables por el constructor.',
                             'Solo desarrollo se usa para elegir sucesores; reservado exige evaluación aparte.']}
    _guardar(carpeta / 'identidad.json', resultado)
    try:
        baseline = evaluar_version(version, cliente=cliente, salida=carpeta / 'evaluaciones')
        ventas = _comercial(version)
        _guardar(carpeta / 'ventas-inicial.json', ventas)
        resultado['baseline'] = {'metricas': baseline['metricas'], 'comercial': ventas,
                                 'operacion': baseline['operacion']}
        if baseline['estado'] != 'EVALUADA':
            raise RuntimeError('No se completó la evaluación inicial.')
        for numero in range(1, generaciones+1):
            # La entrada del constructor es SIEMPRE la versión actualmente aceptada.
            propuesta = proponer(cliente, version, {**baseline, 'comercial': ventas})
            candidata = propuesta['version']
            hija = guardar_version(directorio, candidata, padre)
            _guardar(carpeta / f'propuesta-{numero}.json', {**propuesta, 'padre': padre, 'hija': hija})
            _anotar(directorio, 'candidato', corrida=identificador, generacion=numero, padre=padre, hija=hija)
            # Prueba barata obligatoria antes de evaluar un candidato con API.
            previa = evaluar_version(candidata)
            if previa['estado'] != 'EVALUADA' or previa['metricas']['seguridad']['proporcion'] != 1:
                raise RuntimeError('El candidato no superó la seguridad determinista.')
            evaluada = evaluar_version(candidata, cliente=cliente, salida=carpeta / 'evaluaciones') if real else previa
            if not real:
                _guardar(carpeta / f'evaluacion-{numero}.json', evaluada)
            comercio = _comercial(candidata)
            _guardar(carpeta / f'ventas-{numero}.json', comercio)
            decision = _compuerta(baseline, evaluada, ventas, comercio)
            fila = {'numero': numero, 'padre': padre, 'candidato': hija,
                    'hipotesis': propuesta['hipotesis'], 'origen': propuesta['origen'],
                    'decision': decision, 'metricas': evaluada['metricas'],
                    'operacion': evaluada['operacion'], 'comercial': comercio, 'publicada': False}
            resultado['generaciones'].append(fila)
            if validar_instrumento()['huella_instrumento'] != instrumento['huella_instrumento']:
                raise RuntimeError('El instrumento cambió durante el ciclo.')
            _guardar(carpeta / f'decision-{numero}.json', fila)
            if decision['aceptado']:
                _anotar(directorio, 'aceptado', corrida=identificador, padre=padre, hija=hija,
                        tipo=tipo, generacion=numero)
                activar(directorio, hija)
                version, padre, baseline, ventas = candidata, hija, evaluada, comercio
                resultado['activa_final'] = hija
                fila['publicada'] = True
                _guardar(carpeta / f'publicacion-{numero}.json', {'activa': hija, 'publicada': True})
            else:
                _anotar(directorio, 'rechazado', corrida=identificador, padre=padre, hija=hija,
                        generacion=numero)
                # Evita optimizar indefinidamente sobre la misma muestra o gastar en reintentos.
                resultado['estado'] = 'DETENIDO_SIN_MEJORA'
                break
        else:
            resultado['estado'] = 'LIMITE_DE_GENERACIONES'
    except Exception as error:
        resultado['estado'] = 'INTERRUMPIDO'
        resultado['error'] = type(error).__name__
        mensajes_seguros = {
            'Propuesta fuera del contrato.', 'Cambio fuera del contrato.',
            'Cada hipótesis debe cambiar exactamente una decisión del harness.',
            'El sucesor debe actualizar la skill del constructor de la siguiente generación.',
            'El constructor no produjo JSON válido tras una corrección de formato.',
            'El constructor devolvió una propuesta incompleta.',
            'La versión solo admite harness y skills.', 'Se necesita una hipótesis general y breve.',
            'Skill inválida o demasiado grande.', 'El candidato no superó la seguridad determinista.',
        }
        if str(error) in mensajes_seguros:
            resultado['detalle'] = str(error)
        _anotar(directorio, 'interrumpido', corrida=identificador, clase=type(error).__name__)
    resultado['aceptadas'] = sum(f['publicada'] for f in resultado['generaciones'])
    if real:
        resultado['presupuesto'] = cliente.presupuesto.resumen()
    _guardar(carpeta / 'reporte.json', resultado)
    lineas = [f'# {tipo}', '', f'Estado: {resultado["estado"]}.',
              f'Generaciones aceptadas: {resultado["aceptadas"]}/{len(resultado["generaciones"])}.', '',
              '| Generación | Padre → candidato | Decisión | Funcional | Seguridad |', '| --- | --- | --- | --- | --- |']
    for fila in resultado['generaciones']:
        funcional, seguridad = fila['metricas']['funcional'], fila['metricas']['seguridad']
        lineas.append(f'| {fila["numero"]} | {fila["padre"][:8]} → {fila["candidato"][:8]} | '
                      f'{"ACEPTADO" if fila["decision"]["aceptado"] else "RECHAZADO"} | '
                      f'{funcional["numerador"]}/{funcional["denominador"]} | {seguridad["numerador"]}/{seguridad["denominador"]} |')
    lineas += ['', 'La aceptación es empírica en estas pruebas. No acredita ventas reales ni superioridad estadística.',
               'Las versiones aceptadas heredan tanto el harness como la skill que construye la siguiente generación.']
    with (carpeta / 'reporte.md').open('x', encoding='utf-8') as archivo:
        archivo.write('\n'.join(lineas)+'\n')
    return resultado


def rollback(directorio: Path, identificador: str) -> dict:
    directorio = Path(directorio)
    version = cargar_version(directorio, identificador)
    registros = [json.loads(linea) for linea in (directorio / 'bitacora.jsonl').read_text().splitlines() if linea.strip()]
    elegible = any((r['evento'] == 'aceptado' and r.get('hija') == identificador) or
                  (r['evento'] == 'inicio_ciclo' and r.get('padre') == identificador) for r in registros)
    if not elegible:
        raise ValueError('Solo se puede volver a una versión inicial o anteriormente aceptada.')
    anterior = id_activa(directorio)
    activar(directorio, identificador)
    _anotar(directorio, 'rollback', anterior=anterior, activa=identificador)
    return {'activa': identificador, 'anterior': anterior}
