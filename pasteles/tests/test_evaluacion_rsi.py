import copy
import json
import shutil
from pathlib import Path

import pytest

from pasteles.evaluacion_rsi import (ARCHIVOS, RAIZ, contexto_constructor, decidir,
                                    evaluar_version, validar_instrumento)
from pasteles.versiones_rsi import semilla


def auto():
    version = semilla()
    version['harness']['cotizar_automaticamente'] = True
    return version


def test_instrumento_nuevo_congela_juez_datos_y_criterios():
    instrumento = validar_instrumento()
    assert instrumento['casos'] == {'desarrollo': 12, 'reservada': 36}
    assert 'pasteles/evaluacion_rsi.py' in instrumento['huellas']
    assert not any(nombre.startswith('evaluacion/') for nombre in instrumento['huellas'])


def test_alteracion_de_juez_bloquea_instrumento(tmp_path):
    for nombre in (*ARCHIVOS, 'evaluacion_rsi/congelado.json'):
        destino = tmp_path / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAIZ / nombre, destino)
    ruta = tmp_path / 'pasteles/evaluacion_rsi.py'
    ruta.write_text(ruta.read_text() + '\n# mutación de prueba\n')
    with pytest.raises(ValueError, match='cambió'):
        validar_instrumento(tmp_path)


def test_mejora_pareada_determinista_no_es_calidad_del_modelo(tmp_path):
    baseline = evaluar_version(semilla(), salida=tmp_path)
    candidato = evaluar_version(auto(), salida=tmp_path)
    assert baseline['tipo'] == 'EVALUACION_RSI_DETERMINISTA'
    assert baseline['modelo_evaluado'] is False
    assert baseline['resistencia_nlp_medida'] is False
    assert baseline['version_id'] == baseline['version_sha256']
    assert baseline['suite_sha256'] == baseline['huella_instrumento']
    assert baseline['metricas']['funcional']['numerador'] == 13
    assert candidato['metricas']['funcional']['numerador'] == 17
    assert candidato['metricas']['funcional']['denominador'] == 18
    assert candidato['metricas']['seguridad']['numerador'] == candidato['metricas']['seguridad']['denominador'] == 119
    decision = decidir(baseline, candidato)
    assert decision['aceptado'] is True
    assert decision['victorias'] == 4 and decision['derrotas'] == 0
    assert baseline['carpeta'] != candidato['carpeta']
    assert Path(baseline['carpeta'], 'reporte.json').is_file()


def test_memoria_util_se_mide_sin_regresar_prioridad_actual():
    primero = auto()
    siguiente = copy.deepcopy(primero)
    siguiente['harness']['usar_preferencias'] = True
    a, b = evaluar_version(primero), evaluar_version(siguiente)
    assert b['metricas']['funcional']['proporcion'] == 1
    assert b['metricas']['seguridad']['proporcion'] == 1
    assert decidir(a, b)['aceptado'] is True
    assert decidir(a, b)['victorias'] == 1
    prioridad = next(c for c in b['casos'] if c['id'].endswith('prioridad_turno'))
    assert all(prioridad['funcional'].values())


def test_version_identica_no_puede_declarar_mejora():
    reporte = evaluar_version(auto())
    decision = decidir(reporte, copy.deepcopy(reporte))
    assert decision['aceptado'] is False
    assert decision['victorias'] == 0
    assert 'mejora funcional' in decision['motivo']


@pytest.mark.parametrize('campo', ['tipo', 'particion', 'huella_instrumento', 'configuracion', 'criterios'])
def test_no_compara_instrumentos_o_modos_diferentes(campo):
    baseline = evaluar_version(semilla())
    candidato = evaluar_version(auto())
    candidato[campo] = 'distinto'
    assert decidir(baseline, candidato)['aceptado'] is False


def test_ganancia_global_no_oculta_regresion_pareada():
    baseline, candidato = evaluar_version(semilla()), evaluar_version(auto())
    caso = next(c for c in candidato['casos'] if c['id'].endswith('rechazo'))
    clave = next(k for k, valor in caso['funcional'].items() if valor)
    caso['funcional'][clave] = False
    decision = decidir(baseline, candidato)
    assert decision['victorias'] == 4
    assert decision['derrotas'] == 1
    assert decision['aceptado'] is False


def test_seguridad_se_calcula_de_controles_no_de_autodeclaracion():
    baseline, candidato = evaluar_version(semilla()), evaluar_version(auto())
    # Keep the candidate's aggregate at 100%: the judge must inspect the actual pair.
    candidato['casos'][0]['seguridad']['1:pago_coherente'] = False
    assert candidato['metricas']['seguridad']['proporcion'] == 1
    decision = decidir(baseline, candidato)
    assert not decision['aceptado']
    assert '100% de seguridad' in decision['motivo']


@pytest.mark.parametrize('cambio', ['incompleta', 'costo_latencia', 'integridad', 'caso_omitido', 'caso_duplicado'])
def test_compuertas_no_se_saltan_por_mejor_puntuacion(cambio):
    baseline, candidato = evaluar_version(semilla()), evaluar_version(auto())
    if cambio == 'incompleta':
        candidato['completitud']['proporcion'] = .5
    elif cambio == 'costo_latencia':
        candidato['operacion']['cumple'] = False
    elif cambio == 'integridad':
        candidato['integridad'] = False
    elif cambio == 'caso_omitido':
        candidato['casos'].pop()
    else:
        candidato['casos'].append(copy.deepcopy(candidato['casos'][0]))
    assert not decidir(baseline, candidato)['aceptado']


def test_fallo_de_ejecucion_no_reduce_denominadores(monkeypatch):
    import pasteles.arnes as arnes
    class Roto:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('dato sensible que no debe imprimirse')
    monkeypatch.setattr(arnes, 'Conversacion', Roto)
    reporte = evaluar_version(auto())
    assert reporte['estado'] == 'INCOMPLETA'
    assert reporte['metricas']['funcional']['denominador'] == 18
    assert reporte['metricas']['seguridad']['denominador'] == 119
    assert reporte['metricas']['funcional']['numerador'] == 0
    assert reporte['metricas']['seguridad']['numerador'] == 0
    assert len(reporte['casos']) == 12
    assert 'dato sensible' not in json.dumps(reporte)


def test_juez_detecta_cotizacion_vieja_aunque_se_actualice_revision(monkeypatch):
    import pasteles.arnes as arnes
    original = arnes.Conversacion
    class Obsoleto(original):
        def turno(self, texto, **kwargs):
            resultado = super().turno(texto, **kwargs)
            anterior = getattr(self, '_ultima', None)
            if anterior and resultado['cotizacion'] is None:
                resultado.update(cotizacion=anterior['cotizacion'], solicitud=anterior['solicitud'], pago_habilitado=True)
            if resultado['cotizacion']:
                self._ultima = copy.deepcopy(resultado)
            return resultado
    monkeypatch.setattr(arnes, 'Conversacion', Obsoleto)
    reporte = evaluar_version(semilla())
    assert reporte['metricas']['seguridad']['proporcion'] < 1
    assert any(not v for c in reporte['casos'] for k,v in c['seguridad'].items() if k.endswith('cotizacion_fresca'))


def test_contexto_constructor_solo_agregados_de_desarrollo():
    reporte = evaluar_version(semilla())
    contexto = contexto_constructor(reporte)
    assert contexto['fallas_funcionales_por_grupo']['actualizacion_de_cotizacion'] == 2
    texto = json.dumps(contexto)
    assert 'turnos' not in texto and 'solicitud' not in texto and '2026-' not in texto
    assert not any(c['id'] in texto for c in reporte['casos'])
    reporte['particion'] = 'reservada'
    with pytest.raises(ValueError, match='reservados'):
        contexto_constructor(reporte)
