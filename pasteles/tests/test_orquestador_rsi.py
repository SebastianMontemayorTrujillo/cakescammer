import json

import pytest

from pasteles.orquestador_rsi import ejecutar_ciclo, rollback
from pasteles.versiones_rsi import cargar_activa, cargar_version, guardar_version, semilla


def test_ciclo_hereda_cada_sucesor_y_conserva_rechazo(tmp_path):
    estado = tmp_path / 'estado'
    resultado = ejecutar_ciclo(estado, tmp_path / 'resultados', generaciones=5)
    assert resultado['tipo'] == 'SIMULACION_RSI'
    assert resultado['modelo_evaluado'] is False
    assert resultado['aceptadas'] == 4
    assert resultado['estado'] == 'DETENIDO_SIN_MEJORA'
    filas = resultado['generaciones']
    assert len(filas) == 5
    for anterior, siguiente in zip(filas, filas[1:]):
        assert siguiente['padre'] == anterior['candidato']
        padre = cargar_version(estado, siguiente['padre'])
        hijo = cargar_version(estado, siguiente['candidato'])
        assert padre['skills']['constructor'] in hijo['skills']['constructor']
    assert resultado['activa_final'] == filas[-2]['candidato']
    assert cargar_activa(estado) == cargar_version(estado, filas[-2]['candidato'])
    historial = [json.loads(l) for l in (estado/'bitacora.jsonl').read_text().splitlines()]
    assert sum(e['evento'] == 'aceptado' for e in historial) == 4
    assert sum(e['evento'] == 'rechazado' for e in historial) == 1
    assert all(e['actor'] == 'SISTEMA' for e in historial)
    assert list((tmp_path/'resultados').glob('*/reporte.md'))


def test_rollback_solo_a_semilla_o_aceptada(tmp_path):
    estado = tmp_path/'estado'
    resultado = ejecutar_ciclo(estado, tmp_path/'salida', generaciones=5)
    with pytest.raises(ValueError, match='anteriormente aceptada'):
        rollback(estado, resultado['generaciones'][-1]['candidato'])
    rollback(estado, resultado['semilla'])
    assert cargar_activa(estado) == semilla()


def test_constructor_fallido_no_publica_y_error_no_filtra_texto(tmp_path, monkeypatch):
    import pasteles.orquestador_rsi as modulo
    def fallar(*args, **kwargs):
        raise RuntimeError('NO_PUBLICAR_SECRETO')
    monkeypatch.setattr(modulo, 'proponer', fallar)
    resultado = ejecutar_ciclo(tmp_path/'estado', tmp_path/'salida', generaciones=1)
    assert resultado['estado'] == 'INTERRUMPIDO'
    assert resultado['aceptadas'] == 0
    assert not (tmp_path/'estado/activa.json').exists()
    assert 'NO_PUBLICAR_SECRETO' not in json.dumps(resultado)


def test_limite_de_generaciones_antes_de_api(tmp_path):
    for cantidad in (0, 6, True):
        with pytest.raises(ValueError):
            ejecutar_ciclo(tmp_path/'estado', tmp_path/'salida', generaciones=cantidad)


def test_no_publica_si_falla_registrar_aceptacion(tmp_path, monkeypatch):
    import pasteles.orquestador_rsi as modulo
    anotar = modulo._anotar
    def fallar(directorio, evento, **datos):
        if evento == 'aceptado':
            raise OSError('sin espacio')
        return anotar(directorio, evento, **datos)
    monkeypatch.setattr(modulo, '_anotar', fallar)
    resultado = ejecutar_ciclo(tmp_path/'estado', tmp_path/'salida', generaciones=1)
    assert resultado['estado'] == 'INTERRUMPIDO'
    assert resultado['aceptadas'] == 0
    assert not (tmp_path/'estado/activa.json').exists()
    assert resultado['activa_final'] == resultado['semilla']


def test_salida_enlazada_rechazada_antes_de_escribir(tmp_path):
    destino = tmp_path/'destino'
    destino.mkdir()
    enlace = tmp_path/'enlace'
    enlace.symlink_to(destino, target_is_directory=True)
    with pytest.raises(ValueError, match='enlazados'):
        ejecutar_ciclo(tmp_path/'estado', enlace, generaciones=1)
    assert list(destino.iterdir()) == []
