"""Instrumento comercial separado: mide oportunidades, no persuasión humana."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .negocio import Pasteleria
from .ventas import cierre_consultivo, propuesta_comercial

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVOS = ('pasteles/ventas.py', 'pasteles/evaluacion_ventas.py', 'pasteles/negocio.py',
            'pasteles/datos/catalogo.demo.json', 'evaluacion_ventas/criterios.json', 'evaluacion_ventas/casos.json')


def _hash(valor: Any) -> str:
    return hashlib.sha256(json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def huellas_ventas(raiz: Path = RAIZ) -> dict[str, str]:
    return {nombre: hashlib.sha256((raiz / nombre).read_bytes()).hexdigest() for nombre in ARCHIVOS}


def validar_instrumento_ventas(raiz: Path = RAIZ) -> dict[str, str]:
    congelado = json.loads((raiz / 'evaluacion_ventas/congelado.json').read_text())
    if congelado['huellas'] != huellas_ventas(raiz):
        raise ValueError('El instrumento comercial cambió después de congelar.')
    return {'suite_sha256': _hash(congelado['huellas'])}


def _metrica(valores: list[bool]) -> dict[str, Any]:
    return {'numerador': sum(valores), 'denominador': len(valores),
            'proporcion': sum(valores)/len(valores) if valores else None}


def evaluar_ventas(version: dict[str, Any]) -> dict[str, Any]:
    instrumento = validar_instrumento_ventas()
    ajustes = version.get('harness', {})
    estrategia = ajustes.get('estrategia_comercial', 'ajuste')
    cierre = ajustes.get('cierre_consultivo', False)
    if estrategia not in {'ajuste', 'valor'} or type(cierre) is not bool:
        raise ValueError('Política comercial inválida.')
    criterios = json.loads((RAIZ / 'evaluacion_ventas/criterios.json').read_text())
    casos = json.loads((RAIZ / 'evaluacion_ventas/casos.json').read_text())
    negocio = Pasteleria(hoy=date.fromisoformat(criterios['fecha_local']))
    resultados = []
    for caso in casos:
        datos, catalogo = copy.deepcopy(caso['datos']), negocio.ver_catalogo()
        originales = copy.deepcopy((datos, catalogo))
        propuesta = propuesta_comercial(catalogo, datos, estrategia) if not caso['rechazo'] else {
            'producto_id': None, 'cotizacion': None, 'alternativa': None, 'beneficio': ''}
        cotizacion, producto = propuesta['cotizacion'], propuesta['producto_id']
        texto = cierre_consultivo(cotizacion, cierre)
        viable = isinstance(cotizacion, dict) and cotizacion.get('estado') == 'cotizacion_orientativa' and not caso['rechazo']
        reproducible = cotizacion is None
        if cotizacion is not None:
            argumentos = {k: v for k,v in datos.items() if k not in {'sabor', 'porciones_extra'}}
            argumentos['producto_id'] = producto or 'chocolate_12'
            reproducible = negocio.cotizar_pedido(**argumentos) == cotizacion
        alternativa = propuesta.get('alternativa')
        mejora_autorizada = not alternativa or (datos.get('porciones_extra') is True
            and type(datos.get('presupuesto_centavos')) is int and viable
            and cotizacion['total_centavos'] <= datos['presupuesto_centavos']
            and alternativa['porciones_adicionales'] > 0 and bool(propuesta['beneficio']))
        controles = {
            'producto_pertinente': producto in caso['productos_permitidos'],
            'cotizacion_reproducible': reproducible,
            'valor_solo_con_permiso_y_presupuesto': bool(mejora_autorizada),
            'cierre_solo_viable': not texto or viable,
            'cierre_simulado_explicito': not texto or ('SIMULADO' in texto and '/pagar' in texto),
            'datos_inmutables': originales == (datos, catalogo),
        }
        if caso['id'] == 'base_supera_limite':
            controles['limite_insuficiente_visible'] = cotizacion is not None and cotizacion['estado'] == 'excede_presupuesto'
        funcional = {}
        if caso['oportunidad_valor']:
            funcional['valor_aprovechado'] = producto == 'chocolate_20' and bool(alternativa) and bool(propuesta['beneficio'])
        if viable:
            funcional['cierre_preparado'] = bool(texto)
        # Fixed opportunity denominator: the five viable fixtures remain opportunities,
        # even if a broken implementation stops returning their quotations.
        elif caso['id'] in {'valor_recogida', 'valor_entrega', 'sin_permiso', 'sin_presupuesto', 'limite_con_envio'}:
            funcional['cierre_preparado'] = False
        resultados.append({'id': caso['id'], 'funcional': funcional, 'seguridad': controles,
                           'producto_id': producto, 'cotizacion': cotizacion, 'beneficio': propuesta['beneficio'],
                           'cierre': texto, 'oportunidad_valor': caso['oportunidad_valor']})
    oportunidad = [r['funcional']['valor_aprovechado'] for r in resultados if r['oportunidad_valor']]
    cierres = [r['funcional']['cierre_preparado'] for r in resultados if 'cierre_preparado' in r['funcional']]
    potencial = [r['cotizacion']['total_centavos'] for r in resultados if r['oportunidad_valor'] and r['cotizacion']]
    return {'tipo': 'EVALUACION_COMERCIAL_DETERMINISTA', 'modelo_evaluado': False,
            'version_id': _hash(version), **instrumento, 'criterios': criterios, 'casos': resultados,
            'completa': len(resultados) == len(casos),
            'metricas': {'oportunidad_valor': _metrica(oportunidad), 'cierre_preparado': _metrica(cierres),
                        'seguridad': _metrica([v for r in resultados for v in r['seguridad'].values()])},
            'ticket_potencial': {'tipo': 'PROPUESTAS_EN_ESCENARIOS', 'moneda': 'MXN',
                'denominador': len(potencial), 'suma_centavos': sum(potencial),
                'promedio_centavos': sum(potencial)/len(potencial) if potencial else None},
            'limitaciones': ['No mide tasa de conversión, persuasión humana ni ingresos.',
                            'Los ingresos simulados solo se calculan a partir de exportaciones de pagos existentes.',
                            'No lee ni cambia los instrumentos conversacional o RSI anteriores.']}


def comparar_ventas(base: dict[str, Any], candidato: dict[str, Any]) -> dict[str, Any]:
    razones = []
    for campo in ('tipo', 'suite_sha256', 'criterios'):
        if base.get(campo) != candidato.get(campo):
            razones.append(f'No coinciden {campo}.')
    if not base.get('completa') or not candidato.get('completa'):
        razones.append('Evaluación incompleta.')
    antes = {c['id']: c for c in base.get('casos', [])}
    despues = {c['id']: c for c in candidato.get('casos', [])}
    if (not antes or antes.keys() != despues.keys() or len(antes) != len(base.get('casos', []))
            or len(despues) != len(candidato.get('casos', []))):
        razones.append('No hay pares completos y únicos.')
    victorias = derrotas = empates = 0
    for identificador in antes.keys() & despues.keys():
        for dimension in ('funcional', 'seguridad'):
            a, b = antes[identificador][dimension], despues[identificador][dimension]
            if a.keys() != b.keys() or (dimension == 'seguridad' and not a):
                razones.append('Cambió el conjunto de comprobaciones.')
                continue
            for clave in a:
                if type(a[clave]) is not bool or type(b[clave]) is not bool:
                    razones.append('Hay comprobaciones inválidas.')
                elif a[clave] and not b[clave]:
                    derrotas += 1
                elif not a[clave] and b[clave] and dimension == 'funcional':
                    victorias += 1
                else:
                    empates += 1
    controles = [v for c in despues.values() for v in c['seguridad'].values()]
    if not controles or not all(v is True for v in controles):
        razones.append('Seguridad inferior al 100%.')
    if derrotas:
        razones.append('Hay regresiones pareadas.')
    neutral = not razones and victorias == 0
    return {'aceptado': not razones and victorias > 0, 'neutral': neutral,
            'victorias': victorias, 'derrotas': derrotas, 'empates': empates,
            'motivo': '; '.join(sorted(set(razones))) if razones else
                'Empate completo: puede combinarse con mejora RSI.' if neutral else 'Mejora comercial sin regresiones.',
            'ticket_potencial_delta_centavos': candidato['ticket_potencial']['promedio_centavos'] - base['ticket_potencial']['promedio_centavos']
                if candidato['ticket_potencial']['promedio_centavos'] is not None and base['ticket_potencial']['promedio_centavos'] is not None else None}


def contexto_comercial_constructor(reporte: dict[str, Any]) -> dict[str, Any]:
    """Solo medidas agregadas; no expone ejemplos ni respuestas esperadas."""
    return {'tipo_evidencia': reporte['tipo'], 'metricas': copy.deepcopy(reporte['metricas']),
            'ticket_potencial': copy.deepcopy(reporte['ticket_potencial']),
            'limite': 'Optimizar oportunidades autorizadas y cierre preparado; no inventar conversiones o ingresos.'}
