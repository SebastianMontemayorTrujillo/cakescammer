"""Evals verificables: contratos, objetivos declarados y revisión humana separada."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .herramientas import HERRAMIENTAS, ejecutar
from .negocio import Pasteleria

RAIZ = Path(__file__).resolve().parents[1]
PARTICIONES = {'desarrollo': 'desarrollo.jsonl', 'reservada': 'reservada.jsonl'}
OBJETIVOS = {'cotizacion', 'sin_cotizacion_viable', 'sin_herramientas', 'consulta_catalogo'}


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def huella(valor: bytes) -> str:
    return hashlib.sha256(valor).hexdigest()


def cargar_casos(particion: str, raiz: Path | None = None) -> list[dict[str, Any]]:
    if particion not in PARTICIONES:
        raise ValueError('La partición debe ser desarrollo o reservada.')
    ruta = (raiz or RAIZ) / 'evaluacion' / PARTICIONES[particion]
    return [json.loads(linea) for linea in ruta.read_text(encoding='utf-8').splitlines() if linea.strip()]


def huellas_corpus(raiz: Path | None = None) -> dict[str, str]:
    base = raiz or RAIZ
    archivos = ['evaluacion/desarrollo.jsonl', 'evaluacion/reservada.jsonl',
                'evaluacion/criterios.json', 'pasteles/datos/catalogo.demo.json']
    resultado = {nombre: huella((base / nombre).read_bytes()) for nombre in archivos}
    resultado['herramientas'] = huella(_json(HERRAMIENTAS).encode())
    return resultado


def validar_corpus(raiz: Path | None = None) -> dict[str, Any]:
    """Valida archivos y su congelación; no ejecuta ni califica un modelo."""
    base = raiz or RAIZ
    criterios = json.loads((base / 'evaluacion/criterios.json').read_text())
    date.fromisoformat(criterios['fecha_local'])
    manifiesto = json.loads((base / 'evaluacion/congelado.json').read_text())
    if manifiesto['huellas'] != huellas_corpus(base):
        raise ValueError('El corpus, criterios, herramientas o catálogo cambiaron después de congelar.')
    ids: set[str] = set()
    conteos = {}
    for particion in PARTICIONES:
        casos = cargar_casos(particion, base)
        conteos[particion] = len(casos)
        for caso in casos:
            if not isinstance(caso.get('id'), str) or caso['id'] in ids:
                raise ValueError('Los identificadores deben ser únicos entre particiones.')
            ids.add(caso['id'])
            turnos = caso.get('turnos_cliente')
            if not isinstance(turnos, list) or not turnos or not all(isinstance(t, str) and t.strip() for t in turnos):
                raise ValueError('Cada caso necesita turnos de cliente no vacíos.')
            if not isinstance(caso.get('objetivos'), list) or not caso['objetivos']:
                raise ValueError('Cada caso necesita objetivos medibles.')
            for objetivo in caso['objetivos']:
                if objetivo.get('tipo') not in OBJETIVOS or type(objetivo.get('turno')) is not int:
                    raise ValueError('Objetivo desconocido.')
                if not 1 <= objetivo['turno'] <= len(turnos):
                    raise ValueError('Objetivo fuera de los turnos del caso.')
                if objetivo['tipo'] == 'cotizacion' and not isinstance(objetivo.get('estado'), str):
                    raise ValueError('Una cotización necesita un estado esperado.')
    if conteos['desarrollo'] < 8 or conteos['reservada'] < 30:
        raise ValueError('Se requieren al menos ocho casos de desarrollo y treinta reservados.')
    return {'tipo': 'VALIDACION_OFFLINE', 'estado': 'CORPUS_VALIDO', 'casos': conteos,
            'modelo_evaluado': False, 'huellas': manifiesto['huellas']}


def _nombre(nombre: str) -> str:
    return nombre.removeprefix('mcp__pasteles__')


def evaluar_traza(caso: dict[str, Any], traza: list[dict[str, Any]], *,
                   fecha_local: str = '2026-11-09') -> dict[str, Any]:
    """No interpreta lenguaje libre: las afirmaciones al cliente requieren revisión."""
    muestras: dict[str, list[bool]] = defaultdict(list)
    fallos: list[dict[str, Any]] = []

    def registrar(metrica: str, pasa: bool, detalle: str, turno: int = 0) -> None:
        muestras[metrica].append(pasa)
        if not pasa:
            fallos.append({'metrica': metrica, 'turno': turno, 'detalle': detalle})

    turnos = len(caso['turnos_cliente'])
    completos = {e['turno'] for e in traza if e.get('tipo') == 'asistente' and e.get('final') is True
                 and isinstance(e.get('texto'), str) and e['texto'].strip()}
    registrar('conversaciones_completas', completos == set(range(1, turnos + 1)),
              'Falta respuesta final en al menos un turno previsto.')
    negocio = Pasteleria(hoy=date.fromisoformat(fecha_local))
    permitidas = {h['name'] for h in HERRAMIENTAS}
    catalogo_visto = False
    catalogo_pendiente = False
    llamadas = [e for e in traza if e.get('tipo') == 'herramienta']
    for evento in traza:
        if evento.get('tipo') == 'llamada':
            # Tool results become model knowledge only when the next request
            # includes them. Calls in one assistant batch share prior knowledge.
            catalogo_visto = catalogo_visto or catalogo_pendiente
            catalogo_pendiente = False
        if evento.get('tipo') != 'herramienta':
            continue
        nombre = _nombre(evento.get('nombre', ''))
        turno = evento.get('turno', 0)
        registrar('herramientas_permitidas', nombre in permitidas, 'Herramienta no permitida.', turno)
        if nombre not in permitidas:
            continue
        if nombre in {'recomendar_pasteles', 'cotizar_pedido'}:
            registrar('catalogo_antes_de_consultas', catalogo_visto,
                      'Consultó recomendaciones/cotización antes de obtener el catálogo.', turno)
        try:
            esperado = ejecutar(negocio, nombre, evento.get('argumentos'))
        except (ValueError, TypeError):
            registrar('argumentos_validos', False, 'Los argumentos no cumplen el contrato.', turno)
            continue
        registrar('argumentos_validos', not evento.get('error', False), 'Falló una llamada válida.', turno)
        resultado = evento.get('resultado')
        registrar('resultados_reproducibles', resultado == esperado,
                  'El resultado no coincide con el motor de negocio y su reloj fijo.', turno)
        if nombre == 'ver_catalogo' and resultado == esperado and not evento.get('error'):
            catalogo_pendiente = True

    for objetivo in caso['objetivos']:
        tipo, turno = objetivo['tipo'], objetivo['turno']
        posteriores = [e for e in llamadas if e.get('turno', 0) >= turno]
        fin_turno = next((i for i, e in enumerate(traza) if e.get('tipo') == 'asistente'
                          and e.get('turno') == turno and e.get('final') is True), len(traza))
        exactas = [e for e in traza[:fin_turno] if e.get('tipo') == 'herramienta' and e.get('turno') == turno]
        if tipo == 'cotizacion':
            cotizaciones = [e for e in exactas if _nombre(e.get('nombre', '')) == 'cotizar_pedido']
            # A later quote supersedes the previous snapshot, including failures.
            # A good earlier call must not mask the final state presented to the user.
            ultima = cotizaciones[-1] if cotizaciones else {}
            pasa = bool(ultima) and (
                not ultima.get('error')
                and all(ultima.get('argumentos', {}).get(k) == v for k, v in objetivo.get('argumentos', {}).items())
                and isinstance(ultima.get('resultado'), dict)
                and ultima['resultado'].get('estado') == objetivo['estado']
                and ('total_centavos' not in objetivo or ultima['resultado'].get('total_centavos') == objetivo['total_centavos'])
            )
        elif tipo == 'consulta_catalogo':
            pasa = any(_nombre(e.get('nombre', '')) == 'ver_catalogo' and not e.get('error') for e in exactas)
        elif tipo == 'sin_herramientas':
            pasa = not posteriores
        else:
            pasa = not any(_nombre(e.get('nombre', '')) == 'cotizar_pedido'
                           and isinstance(e.get('resultado'), dict)
                           and e['resultado'].get('estado') == 'cotizacion_orientativa' for e in posteriores)
        # A complete assistant reply is necessary even for a negative assertion:
        # silence/errors must not count as a successful safety outcome.
        pasa = pasa and turno in completos
        registrar('objetivos_de_escenario', pasa, f'No cumplió el objetivo {tipo}.', turno)
    return {'id': caso['id'], 'muestras': dict(muestras), 'fallos': fallos}


def agregar_metricas(resultados: list[dict[str, Any]], criterios: dict[str, Any]) -> dict[str, Any]:
    metricas = {}
    for nombre, umbral in criterios['umbrales_automaticos'].items():
        muestras = [m for r in resultados for m in r['muestras'].get(nombre, [])]
        denominador = len(muestras)
        numerador = sum(muestras)
        proporcion = numerador / denominador if denominador else None
        # Wilson: interval descriptive, never a claim of independence across repeats.
        intervalo = None
        if denominador:
            z, n, p = 1.96, denominador, proporcion
            centro = (p + z*z/(2*n))/(1+z*z/n)
            radio = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
            intervalo = [max(0, centro-radio), min(1, centro+radio)]
        metricas[nombre] = {'numerador': numerador, 'denominador': denominador,
                             'proporcion': proporcion, 'umbral': umbral,
                             'cumple': proporcion >= umbral if proporcion is not None else None,
                             'intervalo_wilson_95_descriptivo': intervalo}
    return metricas


def plantilla_revision(casos: list[dict[str, Any]], repeticiones: int,
                       criterios: dict[str, Any]) -> list[dict[str, Any]]:
    return [{'caso_id': caso['id'], 'repeticion': repeticion,
             'criterio': nombre, 'valor': None, 'evidencia': '', 'revisor': ''}
            for repeticion in range(1, repeticiones + 1) for caso in casos
            for nombre, regla in criterios['rubrica_humana'].items()
            if regla['aplica'] == 'todos' or regla['aplica'] in caso.get('etiquetas', [])]


def completar_revision(reporte_path: Path, revisiones_path: Path) -> dict[str, Any]:
    """Produce una revisión nueva; jamás reescribe el reporte ni el historial."""
    reporte = json.loads(reporte_path.read_text(encoding='utf-8'))
    criterios = reporte['criterios']
    esperadas = {(r['caso_id'], r['repeticion'], r['criterio'])
                 for r in reporte['revision_humana_esperada']}
    recibidas = json.loads(revisiones_path.read_text(encoding='utf-8'))
    claves = [(r['caso_id'], r['repeticion'], r['criterio']) for r in recibidas]
    if len(claves) != len(set(claves)) or set(claves) != esperadas:
        raise ValueError('La revisión debe incluir cada criterio esperado una vez, sin extras.')
    grupos: dict[str, list[bool | None]] = defaultdict(list)
    for fila in recibidas:
        valor = fila['valor']
        nombre = fila['criterio']
        if valor is not None:
            if not isinstance(fila.get('evidencia'), str) or not fila['evidencia'].strip():
                raise ValueError('Cada valoración necesita evidencia de la conversación.')
            if not isinstance(fila.get('revisor'), str) or not fila['revisor'].strip():
                raise ValueError('Cada valoración necesita identificar al revisor.')
            if nombre == 'naturalidad':
                if type(valor) is not int or not 1 <= valor <= 5:
                    raise ValueError('Naturalidad debe ser un entero de 1 a 5.')
                valor = valor >= 4
            elif type(valor) is not bool:
                raise ValueError('Los criterios de cumplimiento deben ser booleanos.')
        grupos[nombre].append(valor)
    metricas = {}
    for nombre, regla in criterios['rubrica_humana'].items():
        filas = grupos[nombre]
        pendientes = sum(v is None for v in filas)
        proporcion = sum(v is True for v in filas)/len(filas) if filas and not pendientes else None
        metricas[nombre] = {'numerador': sum(v is True for v in filas), 'denominador': len(filas),
                            'pendientes': pendientes, 'proporcion': proporcion, 'umbral': regla['umbral'],
                            'cumple': proporcion >= regla['umbral'] if proporcion is not None else None}
    pendiente = any(m['pendientes'] for m in metricas.values())
    cumple_rubrica = all(m['cumple'] is not False for m in metricas.values()) and not pendiente
    cumple_automatico = all(m['cumple'] is not False for m in reporte['metricas_automaticas'].values())
    cumple_operacion = reporte.get('costo_cumple') is True and reporte.get('latencia', {}).get('cumple') is True
    incompleta = pendiente or reporte.get('estado') == 'INCOMPLETA'
    estado = ('INCOMPLETA' if incompleta else 'SIN_EVIDENCIA_MODELO' if not reporte.get('calidad_modelo_medida')
              else 'CUMPLE' if cumple_rubrica and cumple_automatico and cumple_operacion else 'NO_CUMPLE')
    resultado = {'tipo': 'REVISION_HUMANA', 'reporte_sha256': huella(reporte_path.read_bytes()),
                 'valoraciones_sha256': huella(revisiones_path.read_bytes()), 'metricas': metricas,
                 'estado': estado, 'estado_revision': 'INCOMPLETA' if pendiente else
                 'CUMPLE_RUBRICA' if cumple_rubrica else 'NO_CUMPLE_RUBRICA'}
    return resultado


def evaluar_pagos_offline(salida: Path | None = None) -> dict[str, Any]:
    """Matriz del dominio de pagos, sin modelo ni red, con oportunidades explícitas."""
    import csv
    import tempfile
    from datetime import datetime, timezone
    from uuid import uuid4
    from .pagos import AlmacenPagos, ErrorPago, Identidad

    muestras: dict[str, list[bool]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix='pasteles-eval-pagos-') as temporal:
        base = Path(temporal)
        ahora = [1000.0]
        almacen = AlmacenPagos(base / 'pagos.sqlite3', Pasteleria(hoy=date(2026, 11, 9)),
                              reloj=lambda: ahora[0])
        argumentos = {'producto_id': 'chocolate_12', 'asistentes': 10, 'fecha': '2026-11-13',
                      'modalidad': 'entrega', 'zona': 'centro', 'restriccion_alimentaria': 'ninguna'}
        for i, (accion, estado) in enumerate([('aprobar', 'aprobado'), ('rechazar', 'rechazado'),
                                             ('cancelar', 'cancelado')]):
            identidad = Identidad(str(101+i), str(101+i), f'sesion-{i}', f'telegram:{101+i}')
            almacen.capturar(identidad, argumentos, f'llamada-{i}')
            pedido = almacen.preparar(identidad)
            almacen.vincular_mensaje(identidad, pedido['id'], str(51+i))
            for chat, usuario, mensaje, token in [('999', identidad.usuario_id, str(51+i), pedido['token']),
                                                  (identidad.chat_id, '999', str(51+i), pedido['token']),
                                                  (identidad.chat_id, identidad.usuario_id, '999', pedido['token']),
                                                  (identidad.chat_id, identidad.usuario_id, str(51+i), 'inventado')]:
                try:
                    almacen.resolver(chat, usuario, mensaje, token, accion)
                except ErrorPago:
                    muestras['identidad_y_boton_validados'].append(True)
                else:
                    muestras['identidad_y_boton_validados'].append(False)
            resuelto = almacen.resolver(identidad.chat_id, identidad.usuario_id, str(51+i), pedido['token'], accion)
            repetido = almacen.resolver(identidad.chat_id, identidad.usuario_id, str(51+i), pedido['token'], 'aprobar')
            muestras['transiciones_correctas'].append(resuelto['estado'] == estado)
            muestras['idempotencia'].append(repetido['id'] == resuelto['id'] and repetido['estado'] == estado)
            muestras['importe_fiel'].append(resuelto['cotizacion']['total_centavos'] == 71000)
            muestras['etiquetado_simulacion'].append(resuelto['etiqueta'] == 'SIMULACION'
                                                    and resuelto['pagado'] is False and resuelto['reservado'] is False)
        identidad = Identidad('201', '201', 'sesion-vence', 'telegram:201')
        almacen.capturar(identidad, argumentos, 'llamada-vence')
        pedido = almacen.preparar(identidad)
        almacen.vincular_mensaje(identidad, pedido['id'], '61')
        ahora[0] += 1801
        muestras['vigencia'].append(almacen.resolver('201', '201', '61', pedido['token'], 'aprobar')['estado'] == 'caducado')
        almacen.exportar('json', base / 'pagos.json')
        almacen.exportar('csv', base / 'pagos.csv')
        filas_json = json.loads((base / 'pagos.json').read_text())['pedidos']
        with (base / 'pagos.csv').open(newline='') as archivo:
            filas_csv = list(csv.DictReader(archivo))
        muestras['exportacion_fiel'].append(len(filas_json) == len(filas_csv) == 4)
        for fila_json, fila_csv in zip(filas_json, filas_csv):
            muestras['exportacion_fiel'].append(fila_json['pedido_id'] == fila_csv['pedido_id']
                                                and fila_json['estado'] == fila_csv['estado']
                                                and fila_json['total_centavos'] == int(fila_csv['total_centavos']) == 71000)
            muestras['exportacion_sin_identidad'].append(not {'chat', 'usuario', 'token', 'chat_id', 'usuario_id'} & fila_json.keys())
    metricas = agregar_metricas([{'muestras': muestras}], {'umbrales_automaticos': {n: 1.0 for n in muestras}})
    reporte = {'tipo': 'EVALUACION_DETERMINISTA_PAGOS', 'simulacion': True, 'modelo_evaluado': False,
               'creado_en': datetime.now(timezone.utc).isoformat(), 'costo_api_usd': '0',
               'evaluador_sha256': huella(Path(__file__).read_bytes()), 'metricas': metricas,
               'estado': 'CUMPLE' if all(m['cumple'] for m in metricas.values()) else 'NO_CUMPLE',
               'limite': 'Mide el dominio persistente de pagos; los handlers y transporte Telegram tienen sus tests propios.'}
    if salida is not None:
        ruta = Path(salida) / f'pagos-{uuid4().hex}.json'
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open('x', encoding='utf-8') as archivo:
            json.dump(reporte, archivo, ensure_ascii=False, indent=2)
            archivo.write('\n')
        reporte['archivo'] = str(ruta)
    return reporte
