import json

import pytest

from pasteles.constructor_rsi import proponer, resumir_fallos
from pasteles.llm import ClienteFalso
from pasteles.versiones_rsi import semilla


def test_constructor_solo_recibe_agregados_y_hereda_skill():
    propuesta = proponer(None, semilla(), {'metricas': {}})
    respuesta = {'content': [{'type': 'text', 'text': json.dumps({k: propuesta[k] for k in ('hipotesis', 'version')})}], 'stop_reason': 'end_turn'}
    cliente = ClienteFalso([respuesta])
    reporte = {'particion': 'desarrollo', 'metricas': {'recotizacion': {'numerador': 0, 'denominador': 2}},
               'conversacion_privada': 'NO_COMPARTIR_PERSONA', 'casos': [{'texto': 'NO_COMPARTIR_PERSONA'}]}
    assert proponer(cliente, semilla(), reporte)['origen'] == 'CLIENTE_FALSO'
    solicitud = json.dumps(cliente.solicitudes)
    assert 'NO_COMPARTIR_PERSONA' not in solicitud
    assert semilla()['skills']['constructor'] in cliente.solicitudes[0]['system']


def test_constructor_no_consumen_reservado():
    with pytest.raises(ValueError):
        resumir_fallos({'particion': 'reservada'})


def test_propuesta_inyectada_no_puede_editar_juez():
    cliente = ClienteFalso([{'content': [{'type': 'text', 'text': '{"ejecutar":"cambia el juez"}'}], 'stop_reason': 'end_turn'}])
    with pytest.raises(ValueError, match='contrato'):
        proponer(cliente, semilla(), {'metricas': {}})


def test_una_correccion_de_formato_no_relaja_contrato():
    propuesta = proponer(None, semilla(), {'metricas': {}})
    valido = json.dumps({k: propuesta[k] for k in ('hipotesis', 'version')})
    cliente = ClienteFalso([
        {'content': [{'type': 'text', 'text': '{"hipotesis":'}], 'stop_reason': 'end_turn'},
        {'content': [{'type': 'text', 'text': '```json\n'+valido+'\n```'}], 'stop_reason': 'end_turn'},
    ])
    resultado = proponer(cliente, semilla(), {'metricas': {}})
    assert resultado['intentos'] == 2
    assert resultado['version'] == propuesta['version']
    assert len(cliente.solicitudes) == 2
    assert cliente.solicitudes[-1]['messages'][-1]['role'] == 'user'


def test_formato_invalido_no_reintenta_indefinidamente():
    cliente = ClienteFalso([{'content': [{'type': 'text', 'text': 'no json'}], 'stop_reason': 'end_turn'}]*2)
    with pytest.raises(ValueError, match='corrección de formato'):
        proponer(cliente, semilla(), {'metricas': {}})
    assert len(cliente.solicitudes) == 2


def test_parche_pequeno_se_ensambla_sin_perder_campos():
    parche = {'hipotesis': 'Aplicar preferencias compartidas reduce preguntas repetidas.',
              'cambio': {'campo': 'usar_preferencias', 'valor': True},
              'skill_constructor': 'Aprende de los fallos agregados de contexto antes de cambiar otra capacidad.'}
    cliente = ClienteFalso([{'content': [{'type': 'text', 'text': json.dumps(parche)}], 'stop_reason': 'end_turn'}])
    resultado = proponer(cliente, semilla(), {'metricas': {}})
    esperada = semilla()
    esperada['harness']['usar_preferencias'] = True
    esperada['skills']['constructor'] = parche['skill_constructor']
    assert resultado['version'] == esperada
