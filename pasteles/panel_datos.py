"""Proyección de evidencia agregada para el panel local, sin inferencia ni escrituras.

No importa evaluadores ni carga corpus, transcripciones, skills o contexto privado.
Los reportes son datos no confiables: solo salen enums, hashes y medidas validadas.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_HUELLA = re.compile(r'[a-f0-9]{64}')
_CORRIDA = re.compile(r'(?:rsi-)?(\d{8}T\d{6})-[a-f0-9]{8,16}')
_ESTADOS = {'EN_CURSO', 'INTERRUMPIDO', 'DETENIDO_SIN_MEJORA', 'LIMITE_DE_GENERACIONES',
            'EVALUADA', 'INCOMPLETA', 'PRUEBA_ARNES'}
_METRICAS = ('funcional', 'seguridad')


def _objeto(valor: Any) -> dict:
    return valor if isinstance(valor, dict) else {}


def _huella(valor: Any) -> str | None:
    return valor if isinstance(valor, str) and _HUELLA.fullmatch(valor) else None


def _configuracion(valor: Any) -> dict:
    return {'arnes_sha256': _huella(_objeto(valor).get('arnes_sha256'))}


def _estado(valor: Any) -> str:
    return valor if isinstance(valor, str) and valor in _ESTADOS else 'DESCONOCIDO'


def _entero(valor: Any) -> bool:
    return type(valor) is int and 0 <= valor <= 10**12


def _numero(valor: Any) -> float | None:
    if type(valor) not in (int, float) or not 0 <= valor <= 10**12 or not math.isfinite(valor):
        return None
    return float(valor)


def _dolar(valor: Any) -> str | None:
    if type(valor) not in (str, int, float) or len(str(valor)) > 80:
        return None
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or not 0 <= numero <= 10**9:
            return None
        if numero * 10**9 != (numero * 10**9).to_integral_value():
            return None
        return format(numero, '.9f')
    except (InvalidOperation, ValueError):
        return None


def _metrica(valor: Any) -> dict | None:
    valor = _objeto(valor)
    n, d = valor.get('numerador'), valor.get('denominador')
    if not _entero(n) or not _entero(d) or n > d:
        return None
    return {'numerador': n, 'denominador': d, 'proporcion': n/d if d else None}


def _metricas(valor: Any, nombres: tuple = _METRICAS) -> dict:
    valor = _objeto(valor)
    return {nombre: _metrica(valor.get(nombre)) for nombre in nombres}


def _operacion(valor: Any) -> dict:
    valor = _objeto(valor)
    return {'cumple': valor.get('cumple') if type(valor.get('cumple')) is bool else None,
            'latencia_p95_segundos': _numero(valor.get('latencia_p95_segundos')),
            **{k: _dolar(valor.get(k)) for k in ('costo_total_usd', 'costo_maximo_caso_usd',
                                                'reserva_pendiente_delta_usd')}}


def _comercial(valor: Any) -> dict | None:
    valor = _objeto(valor)
    if valor.get('tipo') != 'EVALUACION_COMERCIAL_DETERMINISTA':
        return None
    ticket = _objeto(valor.get('ticket_potencial'))
    n, suma = ticket.get('denominador'), ticket.get('suma_centavos')
    valido = _entero(n) and _entero(suma) and ticket.get('moneda') == 'MXN' and (n > 0 or suma == 0)
    return {'tipo': 'EVALUACION_COMERCIAL_DETERMINISTA', 'modelo_evaluado': False,
            'version_id': _huella(valor.get('version_id')), 'suite_sha256': _huella(valor.get('suite_sha256')),
            'metricas': _metricas(valor.get('metricas'), ('oportunidad_valor', 'cierre_preparado', 'seguridad')),
            'ticket_potencial': {'moneda': 'MXN', 'denominador': n, 'suma_centavos': suma,
                                 'promedio_centavos': suma/n if n else None} if valido else None}


def _punto(valor: Any, nodo: str | None = None) -> dict:
    valor = _objeto(valor)
    comercial = _comercial(valor.get('comercial'))
    return {'id': nodo, 'version_id': comercial['version_id'] if comercial else None,
            'metricas': _metricas(valor.get('metricas')), 'comercial': comercial,
            'operacion': _operacion(valor.get('operacion')),
            'configuracion': _configuracion(valor.get('configuracion'))}


def _delta(antes: dict | None, despues: dict | None, identidad: bool) -> dict:
    comparable = bool(identidad and antes and despues and antes['denominador'] > 0
                      and antes['denominador'] == despues['denominador'])
    return {'comparable': comparable, 'antes': antes, 'despues': despues,
            'delta_aciertos': despues['numerador'] - antes['numerador'] if comparable else None,
            'delta_proporcion': despues['proporcion'] - antes['proporcion'] if comparable else None}


def _comparacion(antes: dict, despues: dict, decision: dict, suite: str | None) -> dict:
    arnes = _objeto(decision.get('arnes'))
    razones = arnes.get('razones')
    razones_comparables = {'El candidato no cumple el 100% de seguridad.',
                          'Hay regresiones pareadas.', 'No hay mejora funcional demostrada.'}
    pares_validos = (isinstance(razones, list)
                     and all(isinstance(r, str) and r in razones_comparables for r in razones))
    revision_antes = _configuracion(antes.get('configuracion'))['arnes_sha256']
    revision_despues = _configuracion(despues.get('configuracion'))['arnes_sha256']
    revisiones_compatibles = not (revision_antes and revision_despues and revision_antes != revision_despues)
    identidad = bool(suite and antes['version_id'] and despues['version_id']
                     and pares_validos and revisiones_compatibles
                     and arnes.get('baseline_sha256') == antes['version_id']
                     and arnes.get('candidato_sha256') == despues['version_id'])
    resultado = {k: _delta(antes['metricas'][k], despues['metricas'][k], identidad) for k in _METRICAS}
    a, b = antes['comercial'], despues['comercial']
    ventas = _objeto(decision.get('ventas'))
    motivo = ventas.get('motivo')
    motivos_validos = {'Empate completo: puede combinarse con mejora RSI.',
                      'Mejora comercial sin regresiones.', 'Seguridad inferior al 100%.',
                      'Hay regresiones pareadas.'}
    pares_ventas = isinstance(motivo, str) and all(r in motivos_validos for r in motivo.split('; '))
    mismo = bool(identidad and pares_ventas and a and b and a['suite_sha256'] and a['suite_sha256'] == b['suite_sha256'])
    resultado['comercial'] = {k: _delta(a['metricas'][k] if a else None, b['metricas'][k] if b else None, mismo)
                              for k in ('oportunidad_valor', 'cierre_preparado', 'seguridad')}
    ta, tb = a['ticket_potencial'] if a else None, b['ticket_potencial'] if b else None
    comparable = bool(mismo and ta and tb and ta['denominador'] > 0 and ta['denominador'] == tb['denominador'])
    resultado['ticket_potencial'] = {'comparable': comparable, 'antes': ta, 'despues': tb,
                                    'delta_centavos': tb['promedio_centavos']-ta['promedio_centavos'] if comparable else None}
    return resultado


class _Lector:
    def __init__(self, raiz: Path):
        self.raiz = raiz.resolve()
        self.avisos: list[dict[str, str]] = []

    def avisar(self, codigo: str, origen: str) -> None:
        aviso = {'codigo': codigo, 'origen': origen}
        if aviso not in self.avisos:
            self.avisos.append(aviso)

    def segura(self, ruta: Path) -> bool:
        try:
            partes = ruta.relative_to(self.raiz).parts
            actual = self.raiz
            for parte in partes:
                actual = actual / parte
                if actual.is_symlink():
                    return False
            return ruta.is_file() and ruta.stat().st_nlink == 1
        except (OSError, ValueError):
            return False

    def leer(self, ruta: Path, origen: str, opcional: bool = False) -> dict | None:
        if opcional and not ruta.exists() and not ruta.is_symlink():
            return None
        try:
            if not self.segura(ruta) or ruta.stat().st_size > 16_000_000:
                self.avisar('ARCHIVO_NO_ADMITIDO', origen)
                return None
            # Nunca se consultan los campos casos, trazas, prompts o transcripciones.
            valor = json.loads(ruta.read_text(encoding='utf-8'))
            if not isinstance(valor, dict):
                raise ValueError
            return valor
        except (OSError, UnicodeError, ValueError, RecursionError):
            self.avisar('JSON_INVALIDO', origen)
            return None

    def arnes_actual(self) -> str | None:
        ruta = self.raiz / 'pasteles/arnes.py'
        if not ruta.exists() and not ruta.is_symlink():
            return None
        try:
            if not self.segura(ruta) or ruta.stat().st_size > 2_000_000:
                raise ValueError
            return hashlib.sha256(ruta.read_bytes()).hexdigest()
        except (OSError, ValueError):
            self.avisar('ARNES_NO_DISPONIBLE', 'arnes_actual')
            return None

    def activa(self, modo: str) -> dict:
        directorio = self.raiz / '.runtime' / ('rsi' if modo == 'real' else 'rsi-simulacion')
        dato = self.leer(directorio/'activa.json', f'{modo}/activa', opcional=True)
        resultado = {'activa_id': None, 'activa_version_id': None, 'harness_activo': None}
        if dato is None:
            return resultado
        identificador = _huella(dato.get('id'))
        if not identificador:
            self.avisar('ACTIVA_INVALIDA', f'{modo}/activa')
            return resultado
        resultado['activa_id'] = identificador
        carpeta = directorio/'versiones'/identificador
        manifiesto = self.leer(carpeta/'manifest.json', f'{modo}/manifiesto_activo', opcional=True)
        if manifiesto:
            contenido = _huella(manifiesto.get('contenido_sha256'))
            padre = manifiesto.get('padre')
            if contenido and (padre is None or _huella(padre)):
                serial = json.dumps({'contenido_sha256': contenido, 'padre': padre}, sort_keys=True, separators=(',', ':'))
                if manifiesto.get('id') == identificador and hashlib.sha256(serial.encode()).hexdigest() == identificador:
                    resultado['activa_version_id'] = contenido
                else:
                    self.avisar('MANIFIESTO_INVALIDO', f'{modo}/activa')
        harness = self.leer(carpeta/'harness.json', f'{modo}/harness_activo', opcional=True)
        if harness is not None:
            claves = ('cotizar_automaticamente', 'usar_preferencias', 'cierre_consultivo')
            if (all(type(harness.get(k)) is bool for k in claves)
                    and type(harness.get('preguntas_por_turno')) is int
                    and harness['preguntas_por_turno'] in (1, 2)
                    and harness.get('estrategia_comercial') in ('ajuste', 'valor')):
                resultado['harness_activo'] = {k: harness[k] for k in (*claves, 'preguntas_por_turno', 'estrategia_comercial')}
            else:
                self.avisar('HARNESS_INVALIDO', f'{modo}/activa')
        return resultado

    def corrida(self, dato: dict, identificador: str, fecha: str, fuente: str) -> dict:
        originales = dato.get('generaciones')
        if not isinstance(originales, list):
            originales = []
            self.avisar('REPORTE_PARCIAL', fuente)
        primer_padre = _huella(_objeto(originales[0]).get('padre')) if originales else _huella(dato.get('activa_final'))
        base = _punto(dato.get('baseline'), primer_padre)
        actual = base
        generaciones = []
        numeros = set()
        suite = _huella(dato.get('suite_sha256'))
        for entrada in originales:
            entrada = _objeto(entrada)
            numero = entrada.get('numero')
            if not _entero(numero) or numero < 1 or numero in numeros:
                self.avisar('GENERACION_INVALIDA', fuente)
                continue
            numeros.add(numero)
            punto = _punto(entrada, _huella(entrada.get('candidato')))
            if any(v is None for v in punto['metricas'].values()):
                self.avisar('METRICAS_INCOMPLETAS', fuente)
            decision = _objeto(entrada.get('decision'))
            aceptado = decision.get('aceptado') if type(decision.get('aceptado')) is bool else None
            publicada = entrada.get('publicada') if type(entrada.get('publicada')) is bool else None
            if aceptado is None or publicada is None or (publicada and not aceptado):
                self.avisar('DECISION_INCOMPLETA', fuente)
                if publicada is True and aceptado is not True:
                    publicada = None
            arnes = _objeto(decision.get('arnes'))
            ventas = _objeto(decision.get('ventas'))
            conteo = lambda d, k: d.get(k) if _entero(d.get(k)) else None
            comparacion = _comparacion(actual, punto, decision, suite)
            padre = _huella(entrada.get('padre'))
            if padre != actual['id'] or padre is None or padre == punto['id'] or punto['id'] is None:
                comparacion = _comparacion(actual, punto, {}, None)
                self.avisar('LINAJE_NO_COMPARABLE', fuente)
            normal = {**punto, 'numero': numero, 'padre': padre, 'candidato': punto['id'], 'publicada': publicada,
                      'decision': {'aceptado': aceptado, 'victorias': conteo(arnes, 'victorias'),
                                   'derrotas': conteo(arnes, 'derrotas'),
                                   'victorias_comerciales': conteo(ventas, 'victorias'),
                                   'derrotas_comerciales': conteo(ventas, 'derrotas')},
                      'comparacion': comparacion}
            generaciones.append(normal)
            if aceptado is True and publicada is True:
                actual = punto
        if any(v is None for v in base['metricas'].values()):
            self.avisar('METRICAS_INCOMPLETAS', fuente)
        estado = _estado(dato.get('estado'))
        if estado == 'DESCONOCIDO':
            self.avisar('ESTADO_DESCONOCIDO', fuente)
        return {'id': identificador, 'fecha': fecha, 'fuente': fuente, 'tipo': dato['tipo'], 'estado': estado,
                'suite_sha256': suite, 'aceptadas': sum(g['decision']['aceptado'] is True for g in generaciones),
                'publicadas': sum(g['publicada'] is True for g in generaciones), 'baseline': base,
                'generaciones': generaciones, 'activa_final': _huella(dato.get('activa_final'))}

    def evaluacion(self, dato: dict, identificador: str, fecha: str, fuente: str) -> dict:
        metricas = _metricas(dato.get('metricas'))
        completitud = _metrica(dato.get('completitud'))
        if completitud is None or any(v is None for v in metricas.values()):
            self.avisar('METRICAS_INCOMPLETAS', fuente)
        return {'id': identificador, 'fecha': fecha, 'fuente': fuente, 'tipo': dato['tipo'],
                'estado': _estado(dato.get('estado')),
                'integridad': dato.get('integridad') if type(dato.get('integridad')) is bool else None,
                'particion': dato.get('particion') if dato.get('particion') in ('desarrollo', 'reservada') else 'desconocida',
                'version_id': _huella(dato.get('version_id')), 'suite_sha256': _huella(dato.get('suite_sha256')),
                'configuracion': _configuracion(dato.get('configuracion')),
                'completitud': completitud, 'metricas': metricas, 'operacion': _operacion(dato.get('operacion'))}

    def revisiones_corrida(self, ruta: Path, corrida: dict, tipos: set[str]) -> None:
        """Recupera solo huellas de agregados internos; jamás sigue rutas del reporte."""
        try:
            rutas = sorted((ruta.parent / 'evaluaciones').glob('*/reporte.json'))
            rutas += sorted(ruta.parent.glob('evaluacion-[1-5].json'))
        except OSError:
            self.avisar('DIRECTORIO_NO_DISPONIBLE', corrida['fuente'])
            return
        revisiones: dict[str, set[str | None]] = {}
        for agregado in rutas:
            if agregado.name == 'reporte.json' and not _CORRIDA.fullmatch(agregado.parent.name):
                continue
            dato = self.leer(agregado, corrida['fuente'])
            if (not dato or not isinstance(dato.get('tipo'), str) or dato['tipo'] not in tipos
                    or dato.get('particion') != 'desarrollo'):
                continue
            version = _huella(dato.get('version_id'))
            if not version or not corrida['suite_sha256'] or dato.get('suite_sha256') != corrida['suite_sha256']:
                continue
            revision = _configuracion(dato.get('configuracion'))['arnes_sha256']
            revisiones.setdefault(version, set()).add(revision)
        puntos = [corrida['baseline'], *corrida['generaciones']]
        for punto in puntos:
            opciones = revisiones.get(punto['version_id'], set())
            previa = punto['configuracion']['arnes_sha256']
            if previa:
                opciones = opciones | {previa}
            punto['configuracion']['arnes_sha256'] = next(iter(opciones)) if len(opciones) == 1 else None
            if len(opciones) > 1:
                self.avisar('REVISION_ARNES_AMBIGUA', corrida['fuente'])
        todas = {p['configuracion']['arnes_sha256'] for p in puntos}
        corrida['configuracion'] = {'arnes_sha256': next(iter(todas)) if len(todas) == 1 else None}
        # Conserva comparaciones históricas, pero una revisión distinta entre pares
        # no se puede presentar como efecto de la versión declarativa.
        actual = corrida['baseline']
        for punto in corrida['generaciones']:
            a, b = actual['configuracion']['arnes_sha256'], punto['configuracion']['arnes_sha256']
            if a and b and a != b:
                punto['comparacion'] = _comparacion(actual, punto, {}, None)
                self.avisar('REVISION_ARNES_NO_COMPARABLE', corrida['fuente'])
            if punto['decision']['aceptado'] is True and punto['publicada'] is True:
                actual = punto

    def presupuesto(self) -> dict | None:
        ruta = self.raiz/'.runtime/presupuesto.sqlite3'
        if not ruta.exists() and not ruta.is_symlink():
            return None
        if not self.segura(ruta):
            self.avisar('PRESUPUESTO_NO_DISPONIBLE', 'presupuesto')
            return None
        conexion = None
        try:
            conexion = sqlite3.connect(ruta.as_uri()+'?mode=ro', uri=True, timeout=0.2, isolation_level=None)
            conexion.execute('PRAGMA query_only=ON')
            conexion.execute('BEGIN')
            limite, bloqueado = conexion.execute('SELECT limite, bloqueado FROM configuracion WHERE id=1').fetchone()
            gastado, reservado = conexion.execute('SELECT COALESCE(SUM(cargo),0), COALESCE(SUM(CASE WHEN cargo IS NULL THEN importe ELSE 0 END),0) FROM reservas').fetchone()
            if not all(type(v) is int and v >= 0 for v in (limite, gastado, reservado)) or bloqueado not in (0, 1):
                raise ValueError
            disponible = 0 if bloqueado else max(0, limite-gastado-reservado)
            return {**{k: format(Decimal(v)/10**9, '.9f') for k, v in
                       (('limite', limite), ('gastado', gastado), ('reservado', reservado), ('disponible', disponible))},
                    'bloqueado': bool(bloqueado), 'fuente': 'cuenta_local'}
        except (sqlite3.Error, TypeError, ValueError, OSError):
            self.avisar('PRESUPUESTO_NO_DISPONIBLE', 'presupuesto')
            return None
        finally:
            if conexion is not None:
                conexion.rollback()
                conexion.close()


def construir_panel(raiz: Path) -> dict[str, Any]:
    """Lee rutas fijas de una raíz local; nunca acepta rutas desde los reportes.

    Un delta exige padre y huellas del juez coincidentes, la misma corrida y el
    mismo denominador. No compara reserva con desarrollo ni modos entre sí.
    """
    lector = _Lector(Path(raiz))
    arnes_actual = lector.arnes_actual()
    modos = {}
    for modo, relativa, tipo_ciclo, tipos_eval in (
            ('real', 'resultados/rsi', 'RSI_MODELO_REAL', {'EVALUACION_RSI_MODELO'}),
            ('simulacion', 'resultados/simulacion/rsi', 'SIMULACION_RSI', {'EVALUACION_RSI_DETERMINISTA', 'EVALUACION_RSI_ARNES'})):
        salida = {**lector.activa(modo), 'arnes_actual_sha256': arnes_actual,
                  'reserva_actual_id': None, 'corridas': [], 'evaluaciones': []}
        fecha_reserva = None
        directorio = lector.raiz/relativa
        try:
            rutas = sorted(directorio.glob('*/reporte.json'))
        except OSError:
            rutas = []
            lector.avisar('DIRECTORIO_NO_DISPONIBLE', modo)
        for ruta in rutas:
            coincidencia = _CORRIDA.fullmatch(ruta.parent.name)
            if not coincidencia:
                lector.avisar('IDENTIFICADOR_NO_ADMITIDO', modo)
                continue
            identificador = ruta.parent.name
            fuente = f'{relativa}/{identificador}/reporte.json'
            try:
                fecha = datetime.strptime(coincidencia[1], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                lector.avisar('FECHA_INVALIDA', modo)
                continue
            dato = lector.leer(ruta, fuente)
            if dato is None:
                continue
            if dato.get('tipo') == tipo_ciclo:
                corrida = lector.corrida(dato, identificador, fecha, fuente)
                lector.revisiones_corrida(ruta, corrida, tipos_eval)
                corrida['coincide_arnes_actual'] = bool(arnes_actual and corrida['configuracion']['arnes_sha256'] == arnes_actual)
                salida['corridas'].append(corrida)
            elif isinstance(dato.get('tipo'), str) and dato['tipo'] in tipos_eval:
                evaluacion = lector.evaluacion(dato, identificador, fecha, fuente)
                evaluacion['coincide_runtime_activo'] = bool(
                    salida['activa_version_id'] and arnes_actual
                    and evaluacion['version_id'] == salida['activa_version_id']
                    and evaluacion['configuracion']['arnes_sha256'] == arnes_actual)
                salida['evaluaciones'].append(evaluacion)
                completa = evaluacion['completitud']
                if (evaluacion['particion'] == 'reservada' and evaluacion['coincide_runtime_activo']
                        and evaluacion['estado'] == 'EVALUADA' and evaluacion['integridad'] is True
                        and completa and completa['denominador'] > 0 and completa['proporcion'] == 1
                        and all(m and m['denominador'] > 0 for m in evaluacion['metricas'].values())
                        and (fecha_reserva is None or fecha >= fecha_reserva)):
                    salida['reserva_actual_id'] = identificador
                    fecha_reserva = fecha
            else:
                lector.avisar('TIPO_O_MODO_INCOMPATIBLE', fuente)
        modos[modo] = salida
    presupuesto = lector.presupuesto()
    return {'esquema': 1, 'generado_en': datetime.now(timezone.utc).isoformat(), 'modos': modos,
            'arnes_actual_sha256': arnes_actual,
            'presupuesto': presupuesto, 'avisos': lector.avisos, 'numero_avisos': len(lector.avisos)}
