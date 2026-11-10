import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from pasteles.panel_datos import construir_panel

A, B, C, D, SUITE, VENTAS = (letra * 64 for letra in 'abcdef')
R1, R2 = '20261109T231515-1234567890', '20261109T232058-abcdef1234'
SECRETO = 'NO_DEBE_SALIR_CREDENCIAL_NI_TEXTO_PRIVADO'


def metrica(n, d):
    return {'numerador': n, 'denominador': d, 'proporcion': -999, 'secreto': SECRETO}


def comercial(version, valor=0, cierre=0, total=139000):
    return {'tipo': 'EVALUACION_COMERCIAL_DETERMINISTA', 'version_id': version,
            'suite_sha256': VENTAS, 'modelo_evaluado': True,
            'metricas': {'oportunidad_valor': metrica(valor, 2), 'cierre_preparado': metrica(cierre, 5),
                         'seguridad': metrica(61, 61)},
            'ticket_potencial': {'denominador': 2, 'suma_centavos': total,
                                 'promedio_centavos': 999999, 'moneda': 'MXN'},
            'casos': [{'entrada': SECRETO}], 'prompt': SECRETO}


def punto(version, n=6, d=15):
    return {'metricas': {'funcional': metrica(n, d), 'seguridad': metrica(119, 119)},
            'comercial': comercial(version),
            'operacion': {'cumple': True, 'latencia_p95_segundos': 2.1,
                          'costo_total_usd': '0.0019', 'costo_maximo_caso_usd': '0.0002',
                          'reserva_pendiente_delta_usd': '0', 'clave': SECRETO}}


def corrida(tipo='RSI_MODELO_REAL'):
    return {'tipo': tipo, 'estado': 'INTERRUMPIDO', 'suite_sha256': SUITE,
            'semilla': A, 'activa_final': B, 'baseline': punto(C), 'aceptadas': 99,
            'error': SECRETO, 'carpeta': '/privado/'+SECRETO,
            'generaciones': [{**punto(D, 13), 'numero': 1, 'padre': A, 'candidato': B,
                              'publicada': True, 'hipotesis': SECRETO,
                              'decision': {'aceptado': True, 'motivo': SECRETO,
                                           'arnes': {'baseline_sha256': C, 'candidato_sha256': D,
                                                     'victorias': 7, 'derrotas': 0, 'razones': []},
                                           'ventas': {'victorias': 0, 'derrotas': 0,
                                                      'motivo': 'Empate completo: puede combinarse con mejora RSI.'}}}]}


def escribir(raiz, relativa, dato):
    p = raiz / relativa
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dato))
    return p


def poner_corrida(raiz, dato=None, modo='real', nombre=R1):
    prefijo = 'resultados/rsi' if modo == 'real' else 'resultados/simulacion/rsi'
    return escribir(raiz, f'{prefijo}/{nombre}/reporte.json', dato or corrida())


def test_normaliza_solo_agregados_y_deltas_pareados(tmp_path):
    poner_corrida(tmp_path)
    panel = construir_panel(tmp_path)
    r = panel['modos']['real']['corridas'][0]
    assert r['estado'] == 'INTERRUMPIDO' and r['aceptadas'] == r['publicadas'] == 1
    assert r['baseline']['id'] == A and r['baseline']['version_id'] == C
    g = r['generaciones'][0]
    assert g['comparacion']['funcional']['delta_aciertos'] == 7
    assert g['comparacion']['funcional']['antes']['proporcion'] == 6/15
    assert g['comercial']['ticket_potencial']['promedio_centavos'] == 69500
    assert g['comercial']['modelo_evaluado'] is False
    assert g['operacion']['costo_total_usd'] == '0.001900000'
    serial = json.dumps(panel)
    assert SECRETO not in serial and str(tmp_path) not in serial
    assert 'hipotesis' not in serial and 'casos' not in serial
    assert r['fuente'] == f'resultados/rsi/{R1}/reporte.json'
    assert panel['numero_avisos'] == 0


def test_separa_modos_y_no_acepta_etiquetas_incompatibles(tmp_path):
    poner_corrida(tmp_path)
    poner_corrida(tmp_path, corrida('SIMULACION_RSI'), 'simulacion')
    poner_corrida(tmp_path, corrida('SIMULACION_RSI'), nombre=R2)
    panel = construir_panel(tmp_path)
    assert len(panel['modos']['real']['corridas']) == len(panel['modos']['simulacion']['corridas']) == 1
    assert panel['avisos'][0]['codigo'] == 'TIPO_O_MODO_INCOMPATIBLE'


def test_reserva_solo_agregados_sin_fallos_casos_o_configuracion(tmp_path):
    dato = {'tipo': 'EVALUACION_RSI_MODELO', 'estado': 'EVALUADA', 'particion': 'reservada',
            'version_id': D, 'suite_sha256': SUITE, 'completitud': metrica(36, 36),
            'metricas': {'funcional': metrica(38, 45), 'seguridad': metrica(357, 357)},
            'operacion': {'latencia_p95_segundos': 3.79, 'costo_total_usd': '0.0058074'},
            'casos': [{'texto': SECRETO}], 'fallos_agregados': {'privado': SECRETO},
            'configuracion': {'api_key': SECRETO}, 'trazas': SECRETO}
    poner_corrida(tmp_path, dato)
    r = construir_panel(tmp_path)['modos']['real']['evaluaciones'][0]
    assert r['completitud']['denominador'] == 36
    assert r['metricas']['funcional']['numerador'] == 38
    assert r['metricas']['seguridad']['denominador'] == 357
    assert r['particion'] == 'reservada' and 'comparacion' not in r
    assert SECRETO not in json.dumps(r)


@pytest.mark.parametrize('cambio', ['denominador', 'huella', 'padre', 'suite'])
def test_no_inventa_delta_con_comparacion_incompatible(tmp_path, cambio):
    r = corrida()
    g = r['generaciones'][0]
    if cambio == 'denominador':
        g['metricas']['funcional']['denominador'] = 18
    elif cambio == 'huella':
        g['decision']['arnes']['baseline_sha256'] = B
    elif cambio == 'padre':
        g['padre'] = B
    else:
        r['suite_sha256'] = None
    poner_corrida(tmp_path, r)
    comparacion = construir_panel(tmp_path)['modos']['real']['corridas'][0]['generaciones'][0]['comparacion']
    assert comparacion['funcional']['comparable'] is False
    assert comparacion['funcional']['delta_aciertos'] is None


def test_candidato_rechazado_se_conserva_y_no_cambia_padre(tmp_path):
    r = corrida()
    g = copy.deepcopy(r['generaciones'][0])
    g.update(numero=2, padre=B, candidato=A, publicada=False)
    g['decision']['aceptado'] = False
    g['decision']['arnes'].update(baseline_sha256=D, candidato_sha256=D, victorias=0)
    r['generaciones'].append(g)
    poner_corrida(tmp_path, r)
    salida = construir_panel(tmp_path)['modos']['real']['corridas'][0]
    assert salida['aceptadas'] == 1 and len(salida['generaciones']) == 2
    assert salida['generaciones'][1]['decision']['aceptado'] is False
    assert salida['generaciones'][1]['comparacion']['funcional']['delta_aciertos'] == 0


@pytest.mark.parametrize('razones', [['No coinciden configuracion.'],
                                  ['candidato: ejecución incompleta o integridad inválida.'],
                                  ['Las conversaciones no forman pares completos y únicos.'],
                                  None, [SECRETO]])
def test_no_afirma_mejora_si_juez_no_valida_comparacion(tmp_path, razones):
    r = corrida()
    r['generaciones'][0]['decision']['arnes']['razones'] = razones
    poner_corrida(tmp_path, r)
    g = construir_panel(tmp_path)['modos']['real']['corridas'][0]['generaciones'][0]
    assert g['comparacion']['funcional']['comparable'] is False
    assert g['comparacion']['funcional']['delta_aciertos'] is None
    assert SECRETO not in json.dumps(g)


def test_no_compara_comercial_incompleta_aunque_huellas_coincidan(tmp_path):
    r = corrida()
    r['generaciones'][0]['decision']['ventas']['motivo'] = 'Evaluación incompleta.'
    poner_corrida(tmp_path, r)
    g = construir_panel(tmp_path)['modos']['real']['corridas'][0]['generaciones'][0]
    assert g['comparacion']['funcional']['comparable'] is True
    assert g['comparacion']['comercial']['oportunidad_valor']['comparable'] is False
    assert g['comparacion']['ticket_potencial']['comparable'] is False


def test_reserva_incompleta_conserva_estado_e_integridad(tmp_path):
    poner_corrida(tmp_path, {'tipo': 'EVALUACION_RSI_MODELO', 'estado': 'INCOMPLETA',
                          'particion': 'reservada', 'integridad': False,
                          'completitud': metrica(3, 36)})
    e = construir_panel(tmp_path)['modos']['real']['evaluaciones'][0]
    assert e['estado'] == 'INCOMPLETA' and e['integridad'] is False
    assert e['completitud']['numerador'] == 3 and e['completitud']['denominador'] == 36


def test_publicacion_contradictoria_no_cuenta_como_confirmada(tmp_path):
    r = corrida()
    r['generaciones'][0]['decision']['aceptado'] = False
    poner_corrida(tmp_path, r)
    panel = construir_panel(tmp_path)
    c = panel['modos']['real']['corridas'][0]
    assert c['publicadas'] == 0
    assert c['generaciones'][0]['publicada'] is None
    assert any(a['codigo'] == 'DECISION_INCOMPLETA' for a in panel['avisos'])


def test_malformed_y_parciales_no_rompen_panel_ni_filtran_errores(tmp_path):
    p = poner_corrida(tmp_path)
    p.write_text('{'+SECRETO)
    poner_corrida(tmp_path, {'tipo': 'RSI_MODELO_REAL', 'estado': [], 'generaciones': SECRETO}, nombre=R2)
    panel = construir_panel(tmp_path)
    assert len(panel['modos']['real']['corridas']) == 1
    assert panel['modos']['real']['corridas'][0]['estado'] == 'DESCONOCIDO'
    assert panel['numero_avisos'] >= 3
    assert SECRETO not in json.dumps(panel) and str(tmp_path) not in json.dumps(panel)


@pytest.mark.parametrize('valor', [True, -1, float('nan'), float('inf'), SECRETO])
def test_metricas_invalidas_no_se_presentan_como_cero_ni_cien(tmp_path, valor):
    r = corrida()
    r['baseline']['metricas']['funcional']['numerador'] = valor
    poner_corrida(tmp_path, r)
    salida = construir_panel(tmp_path)['modos']['real']['corridas'][0]
    assert salida['baseline']['metricas']['funcional'] is None
    assert salida['generaciones'][0]['comparacion']['funcional']['comparable'] is False


def test_cero_oportunidades_es_na(tmp_path):
    r = corrida()
    r['baseline']['metricas']['funcional'] = metrica(0, 0)
    poner_corrida(tmp_path, r)
    panel = construir_panel(tmp_path)
    assert panel['modos']['real']['corridas'][0]['baseline']['metricas']['funcional']['proporcion'] is None


def test_no_sigue_enlaces_ni_rutas_indicadas_en_reportes(tmp_path):
    externo = tmp_path/'privado.json'
    externo.write_text(SECRETO)
    p = tmp_path/f'resultados/rsi/{R1}/reporte.json'
    p.parent.mkdir(parents=True)
    p.symlink_to(externo)
    r = corrida()
    r['carpeta'] = str(externo)
    r['trazas'] = str(externo)
    poner_corrida(tmp_path, r, nombre=R2)
    panel = construir_panel(tmp_path)
    assert len(panel['modos']['real']['corridas']) == 1
    assert panel['avisos'][0]['codigo'] == 'ARCHIVO_NO_ADMITIDO'
    assert SECRETO not in json.dumps(panel)


def test_activa_y_harness_solo_cinco_campos_sin_skills(tmp_path):
    contenido = C
    serial = json.dumps({'contenido_sha256': contenido, 'padre': None}, sort_keys=True, separators=(',', ':'))
    nodo = hashlib.sha256(serial.encode()).hexdigest()
    escribir(tmp_path, '.runtime/rsi/activa.json', {'id': nodo, 'secreto': SECRETO})
    escribir(tmp_path, f'.runtime/rsi/versiones/{nodo}/manifest.json',
             {'id': nodo, 'padre': None, 'contenido_sha256': contenido})
    h = {'cotizar_automaticamente': True, 'usar_preferencias': False, 'cierre_consultivo': False,
         'preguntas_por_turno': 2, 'estrategia_comercial': 'ajuste'}
    escribir(tmp_path, f'.runtime/rsi/versiones/{nodo}/harness.json', {**h, 'prompt': SECRETO})
    modo = construir_panel(tmp_path)['modos']['real']
    assert modo['activa_id'] == nodo and modo['activa_version_id'] == contenido
    assert modo['harness_activo'] == h


def test_presupuesto_solo_lectura_sin_crear_archivos_o_cambiar_bytes(tmp_path):
    assert construir_panel(tmp_path)['presupuesto'] is None
    assert not (tmp_path/'.runtime').exists()
    p = tmp_path/'.runtime/presupuesto.sqlite3'
    p.parent.mkdir()
    db = sqlite3.connect(p)
    db.executescript('CREATE TABLE configuracion(id INTEGER,limite INTEGER,bloqueado INTEGER);'
                    'INSERT INTO configuracion VALUES(1,5000000000,0);'
                    'CREATE TABLE reservas(id TEXT,importe INTEGER,cargo INTEGER);'
                    'INSERT INTO reservas VALUES("a",500000000,40000000);'
                    'INSERT INTO reservas VALUES("b",500000000,NULL);')
    db.close()
    antes = {str(f.relative_to(tmp_path)): f.read_bytes() for f in tmp_path.rglob('*') if f.is_file()}
    resultado = construir_panel(tmp_path)['presupuesto']
    despues = {str(f.relative_to(tmp_path)): f.read_bytes() for f in tmp_path.rglob('*') if f.is_file()}
    assert resultado == {'limite': '5.000000000', 'gastado': '0.040000000', 'reservado': '0.500000000',
                         'disponible': '4.460000000', 'bloqueado': False, 'fuente': 'cuenta_local'}
    assert antes == despues


def test_presupuesto_corrupto_da_aviso_sin_error_crudo(tmp_path):
    p = tmp_path/'.runtime/presupuesto.sqlite3'
    p.parent.mkdir()
    p.write_text(SECRETO)
    panel = construir_panel(tmp_path)
    assert panel['presupuesto'] is None
    assert {'codigo': 'PRESUPUESTO_NO_DISPONIBLE', 'origen': 'presupuesto'} in panel['avisos']
    assert SECRETO not in json.dumps(panel)


def test_dinamico_redescubre_resultados_sin_cache(tmp_path):
    assert construir_panel(tmp_path)['modos']['real']['corridas'] == []
    poner_corrida(tmp_path)
    assert len(construir_panel(tmp_path)['modos']['real']['corridas']) == 1


def test_generacion_incompleta_y_duplicada_produce_avisos(tmp_path):
    r = corrida()
    g = r['generaciones'][0]
    g['metricas']['funcional'] = None
    g['publicada'] = SECRETO
    r['generaciones'].append(copy.deepcopy(g))
    poner_corrida(tmp_path, r)
    panel = construir_panel(tmp_path)
    codigos = {a['codigo'] for a in panel['avisos']}
    assert {'METRICAS_INCOMPLETAS', 'DECISION_INCOMPLETA', 'GENERACION_INVALIDA'} <= codigos
    assert len(panel['modos']['real']['corridas'][0]['generaciones']) == 1
    assert SECRETO not in json.dumps(panel)


def preparar_runtime(raiz, contenido=D):
    archivo = raiz / 'pasteles/arnes.py'
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text('REVISION = 1\n')
    revision = hashlib.sha256(archivo.read_bytes()).hexdigest()
    manifiesto = {'contenido_sha256': contenido, 'padre': None}
    nodo = hashlib.sha256(json.dumps(manifiesto, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    escribir(raiz, '.runtime/rsi/activa.json', {'id': nodo})
    escribir(raiz, f'.runtime/rsi/versiones/{nodo}/manifest.json', {'id': nodo, **manifiesto})
    return revision


def reserva_runtime(revision, contenido=D):
    return {'tipo': 'EVALUACION_RSI_MODELO', 'estado': 'EVALUADA', 'particion': 'reservada',
            'version_id': contenido, 'suite_sha256': SUITE, 'integridad': True,
            'configuracion': {'arnes_sha256': revision, 'api_key': SECRETO},
            'completitud': metrica(36, 36),
            'metricas': {'funcional': metrica(38, 45), 'seguridad': metrica(357, 357)}}


def test_reserva_actual_exige_contenido_y_revision_runtime(tmp_path):
    revision = preparar_runtime(tmp_path)
    poner_corrida(tmp_path, reserva_runtime(revision))
    panel = construir_panel(tmp_path)
    linea = panel['modos']['real']
    reserva = linea['evaluaciones'][0]
    assert panel['arnes_actual_sha256'] == linea['arnes_actual_sha256'] == revision
    assert reserva['configuracion'] == {'arnes_sha256': revision}
    assert reserva['coincide_runtime_activo'] is True
    assert linea['reserva_actual_id'] == R1
    assert SECRETO not in json.dumps(panel) and 'REVISION = 1' not in json.dumps(panel)

    # Mismo nodo y mismas skills; el código ejecutable cambió.
    (tmp_path / 'pasteles/arnes.py').write_text('REVISION = 2\n')
    nueva = construir_panel(tmp_path)['modos']['real']
    assert nueva['activa_version_id'] == linea['activa_version_id']
    assert nueva['evaluaciones'][0]['configuracion']['arnes_sha256'] == revision
    assert nueva['evaluaciones'][0]['coincide_runtime_activo'] is False
    assert nueva['reserva_actual_id'] is None


@pytest.mark.parametrize('cambio', ['sin_revision', 'revision_invalida', 'otra_version',
                                  'integridad', 'incompleta', 'sin_codigo', 'sin_activa'])
def test_reserva_sin_evidencia_actual_completa_no_valida_runtime(tmp_path, cambio):
    revision = preparar_runtime(tmp_path)
    reserva = reserva_runtime(revision)
    if cambio == 'sin_revision':
        reserva.pop('configuracion')
    elif cambio == 'revision_invalida':
        reserva['configuracion']['arnes_sha256'] = SECRETO
    elif cambio == 'otra_version':
        reserva['version_id'] = C
    elif cambio == 'integridad':
        reserva['integridad'] = False
    elif cambio == 'incompleta':
        reserva['estado'] = 'INCOMPLETA'
        reserva['completitud'] = metrica(35, 36)
    elif cambio == 'sin_codigo':
        (tmp_path / 'pasteles/arnes.py').unlink()
    else:
        (tmp_path / '.runtime/rsi/activa.json').unlink()
    poner_corrida(tmp_path, reserva)
    panel = construir_panel(tmp_path)
    assert panel['modos']['real']['reserva_actual_id'] is None
    assert SECRETO not in json.dumps(panel)


@pytest.mark.parametrize('enlace', ['simbolico', 'duro'])
def test_codigo_runtime_enlazado_no_produce_validacion(tmp_path, enlace):
    revision = preparar_runtime(tmp_path)
    archivo = tmp_path / 'pasteles/arnes.py'
    archivo.unlink()
    externo = tmp_path / 'archivo_privado'
    externo.write_text(SECRETO)
    if enlace == 'simbolico':
        archivo.symlink_to(externo)
    else:
        archivo.hardlink_to(externo)
    poner_corrida(tmp_path, reserva_runtime(revision))
    panel = construir_panel(tmp_path)
    assert panel['arnes_actual_sha256'] is None
    assert panel['modos']['real']['reserva_actual_id'] is None
    assert any(a['codigo'] == 'ARNES_NO_DISPONIBLE' for a in panel['avisos'])
    assert SECRETO not in json.dumps(panel)


def test_corrida_historica_conserva_delta_y_revision_de_sus_agregados(tmp_path):
    actual = preparar_runtime(tmp_path)
    poner_corrida(tmp_path)
    vieja = '1' * 64
    for i, version in enumerate((C, D), 1):
        dato = {'tipo': 'EVALUACION_RSI_MODELO', 'particion': 'desarrollo',
                'version_id': version, 'suite_sha256': SUITE,
                'configuracion': {'arnes_sha256': vieja, 'api_key': SECRETO},
                'casos': [{'privado': SECRETO}]}
        escribir(tmp_path, f'resultados/rsi/{R1}/evaluaciones/rsi-20261109T23151{i}-abcdef1234/reporte.json', dato)
    panel = construir_panel(tmp_path)
    c = panel['modos']['real']['corridas'][0]
    assert c['configuracion'] == {'arnes_sha256': vieja}
    assert c['baseline']['configuracion'] == c['generaciones'][0]['configuracion'] == c['configuracion']
    assert c['coincide_arnes_actual'] is False and panel['arnes_actual_sha256'] == actual
    assert c['generaciones'][0]['comparacion']['funcional']['delta_aciertos'] == 7
    assert SECRETO not in json.dumps(panel)


def test_revisiones_distintas_dentro_de_corrida_no_generan_delta(tmp_path):
    poner_corrida(tmp_path)
    for i, version in enumerate((C, D), 1):
        dato = {'tipo': 'EVALUACION_RSI_MODELO', 'particion': 'desarrollo',
                'version_id': version, 'suite_sha256': SUITE,
                'configuracion': {'arnes_sha256': str(i) * 64}}
        escribir(tmp_path, f'resultados/rsi/{R1}/evaluaciones/rsi-20261109T23151{i}-abcdef1234/reporte.json', dato)
    panel = construir_panel(tmp_path)
    c = panel['modos']['real']['corridas'][0]
    assert c['configuracion']['arnes_sha256'] is None
    assert c['generaciones'][0]['comparacion']['funcional']['comparable'] is False
    assert any(a['codigo'] == 'REVISION_ARNES_NO_COMPARABLE' for a in panel['avisos'])


def test_no_hereda_revision_de_otro_modo_suite_particion_o_enlace(tmp_path):
    poner_corrida(tmp_path)
    base = {'tipo': 'EVALUACION_RSI_MODELO', 'particion': 'desarrollo',
            'version_id': C, 'suite_sha256': SUITE, 'configuracion': {'arnes_sha256': '1' * 64}}
    for i, cambios in enumerate(({'tipo': []}, {'tipo': 'EVALUACION_RSI_DETERMINISTA'},
                                {'particion': 'reservada'}, {'suite_sha256': B}), 1):
        escribir(tmp_path, f'resultados/rsi/{R1}/evaluaciones/rsi-20261109T23151{i}-abcdef1234/reporte.json',
                 {**base, **cambios})
    afuera = escribir(tmp_path, 'privado.json', base)
    enlace = tmp_path / f'resultados/rsi/{R1}/evaluaciones/rsi-20261109T231515-abcdef1234/reporte.json'
    enlace.parent.mkdir(parents=True)
    enlace.symlink_to(afuera)
    c = construir_panel(tmp_path)['modos']['real']['corridas'][0]
    assert c['configuracion']['arnes_sha256'] is None
    assert c['baseline']['configuracion']['arnes_sha256'] is None


def test_ultima_reserva_no_desplaza_evidencia_actual_si_es_de_otro_runtime(tmp_path):
    revision = preparar_runtime(tmp_path)
    poner_corrida(tmp_path, reserva_runtime(revision))
    poner_corrida(tmp_path, reserva_runtime('1' * 64), nombre=R2)
    linea = construir_panel(tmp_path)['modos']['real']
    assert linea['reserva_actual_id'] == R1
    assert len(linea['evaluaciones']) == 2
    assert linea['evaluaciones'][-1]['coincide_runtime_activo'] is False
