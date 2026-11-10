import copy
import hashlib
import json
import shutil

import pytest

from pasteles.evaluacion_ventas import (ARCHIVOS, RAIZ, comparar_ventas, contexto_comercial_constructor,
                                       evaluar_ventas, validar_instrumento_ventas)


def version(estrategia='ajuste', cierre=False):
    return {'harness': {'estrategia_comercial':estrategia,'cierre_consultivo':cierre}}


def test_valor_y_cierre_son_mejoras_pareadas_diferentes():
    base = evaluar_ventas(version())
    valor = evaluar_ventas(version('valor'))
    cierre = evaluar_ventas(version('valor',True))
    assert base['metricas']['oportunidad_valor']['numerador'] == 0
    assert valor['metricas']['oportunidad_valor']['numerador'] == 2
    assert valor['metricas']['oportunidad_valor']['denominador'] == 2
    assert cierre['metricas']['cierre_preparado']['numerador'] == cierre['metricas']['cierre_preparado']['denominador'] == 5
    assert cierre['metricas']['seguridad']['proporcion'] == 1
    assert comparar_ventas(base,valor)['aceptado'] is True
    assert comparar_ventas(base,valor)['victorias'] == 2
    assert comparar_ventas(valor,cierre)['aceptado'] is True
    assert comparar_ventas(valor,cierre)['victorias'] == 5
    assert cierre['tipo'] == 'EVALUACION_COMERCIAL_DETERMINISTA'
    assert cierre['modelo_evaluado'] is False
    assert cierre['ticket_potencial']['promedio_centavos'] == 99500
    assert base['ticket_potencial']['promedio_centavos'] == 69500


def test_empate_neutral_no_es_mejora():
    base=evaluar_ventas(version())
    decision=comparar_ventas(base,copy.deepcopy(base))
    assert decision['neutral'] is True
    assert decision['aceptado'] is False
    assert decision['victorias'] == decision['derrotas'] == 0


def test_regresion_no_se_oculta_tras_upsell():
    base=evaluar_ventas(version(cierre=True))
    candidato=evaluar_ventas(version('valor'))
    decision=comparar_ventas(base,candidato)
    assert decision['victorias'] == 2 and decision['derrotas'] == 5
    assert decision['aceptado'] is False and decision['neutral'] is False


def test_controles_concretos_prevalecen_sobre_aggregate():
    base=evaluar_ventas(version())
    candidato=evaluar_ventas(version('valor',True))
    candidato['casos'][0]['seguridad']['valor_solo_con_permiso_y_presupuesto']=False
    assert candidato['metricas']['seguridad']['proporcion'] == 1
    assert not comparar_ventas(base,candidato)['aceptado']


def test_juez_y_core_congelados(tmp_path):
    for nombre in (*ARCHIVOS,'evaluacion_ventas/congelado.json'):
        p=tmp_path/nombre;p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(RAIZ/nombre,p)
    p=tmp_path/'pasteles/ventas.py';p.write_text(p.read_text()+'\n# cambio\n')
    with pytest.raises(ValueError,match='congelar'):
        validar_instrumento_ventas(tmp_path)


def test_constructor_solo_recibe_metricas_agregadas():
    contexto=contexto_comercial_constructor(evaluar_ventas(version()))
    assert set(contexto)=={'tipo_evidencia','metricas','ticket_potencial','limite'}
    assert 'casos' not in contexto


def test_revision_v1_conservada_y_comparacion_entre_revisiones_rechazada():
    historial = RAIZ / 'evaluacion_ventas/historial/v1'
    original = json.loads((historial / 'evaluacion_ventas/congelado.json').read_text())
    actual = json.loads((RAIZ / 'evaluacion_ventas/congelado.json').read_text())
    assert original['version'] == 1 and actual['version'] == 2
    for nombre, huella in original['huellas'].items():
        assert hashlib.sha256((historial / nombre).read_bytes()).hexdigest() == huella
    for nombre in ('evaluacion_ventas/criterios.json', 'evaluacion_ventas/casos.json'):
        assert original['huellas'][nombre] == actual['huellas'][nombre]
    base = evaluar_ventas(version())
    candidato = evaluar_ventas(version('valor'))
    base['suite_sha256'] = actual['suite_anterior_sha256']
    decision = comparar_ventas(base, candidato)
    assert not decision['aceptado'] and not decision['neutral']
    assert 'suite_sha256' in decision['motivo']
