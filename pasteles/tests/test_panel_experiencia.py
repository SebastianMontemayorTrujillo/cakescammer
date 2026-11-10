import json

from pasteles.panel_experiencia import leer_experiencia


def informe(tmp_path, **cambios):
    dato = {'tipo': 'EVALUACION_EXPERIENCIA_MODELO', 'particion': 'desarrollo',
            'version_sha256': 'a'*64, 'configuracion': {'arnes_sha256': 'b'*64},
            'estado': 'EVALUADA', 'cumple_automatico': True,
            'completitud': {'numerador': 8, 'denominador': 8},
            'metricas': {'objetivos': {'numerador': 12, 'denominador': 15},
                        'seguridad': {'numerador': 40, 'denominador': 40}},
            'casos': [{'texto_privado': 'NO_PUBLICAR_SECRETO'}]}
    dato.update(cambios)
    p = tmp_path/'resultados/experiencia/experiencia-20261109T235000-1234567890/reporte.json'
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(dato))
    return p


def test_lectura_solo_agregados_y_version_real_del_codigo(tmp_path):
    informe(tmp_path)
    salida = leer_experiencia(tmp_path, 'a'*64, 'b'*64)
    assert salida['real'][0]['coincide_runtime_activo'] is True
    assert salida['real'][0]['metricas']['objetivos']['proporcion'] == 12/15
    assert 'NO_PUBLICAR_SECRETO' not in json.dumps(salida)
    assert not salida['offline']
    assert leer_experiencia(tmp_path, 'a'*64, 'c'*64)['real'][0]['coincide_runtime_activo'] is False


def test_no_confunde_evidencia_offline_en_carpeta_real(tmp_path):
    informe(tmp_path, tipo='PRUEBA_EXPERIENCIA_OFFLINE')
    salida = leer_experiencia(tmp_path, None, None)
    assert salida['real'] == []
    assert salida['avisos'][0]['codigo'] == 'TIPO_O_MODO_INCOMPATIBLE'


def test_archivo_enlazado_o_roto_no_expone_datos(tmp_path):
    p = informe(tmp_path)
    p.write_text('{NO_PUBLICAR_SECRETO')
    salida = leer_experiencia(tmp_path, None, None)
    assert salida['real'] == [] and salida['avisos']
    externo = tmp_path/'privado'
    externo.write_text('NO_PUBLICAR_SECRETO')
    p.unlink()
    p.symlink_to(externo)
    salida = leer_experiencia(tmp_path, None, None)
    assert salida['real'] == [] and 'NO_PUBLICAR_SECRETO' not in json.dumps(salida)
