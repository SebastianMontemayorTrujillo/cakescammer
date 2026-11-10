import copy
import json

import pytest

from pasteles.versiones_rsi import (activar, cargar_activa, cargar_version, guardar_version,
                                    huella_version, semilla, validar_sucesor, validar_version)


def sucesor():
    version = semilla()
    version['harness']['cotizar_automaticamente'] = True
    version['skills']['constructor'] += ' Aprende de recotizar por estado explícito.'
    return version


def test_versiones_inmutables_y_rollback(tmp_path):
    padre = guardar_version(tmp_path, semilla())
    hijo = guardar_version(tmp_path, sucesor(), padre)
    activar(tmp_path, hijo)
    assert cargar_activa(tmp_path) == sucesor()
    activar(tmp_path, padre)
    assert cargar_activa(tmp_path) == semilla()
    assert padre != hijo
    assert (tmp_path / 'versiones' / hijo / 'skills/constructor/SKILL.md').is_file()


def test_modificar_artefacto_rompe_su_huella(tmp_path):
    identificador = guardar_version(tmp_path, semilla())
    archivo = tmp_path / 'versiones' / identificador / 'skills/vendedor/SKILL.md'
    archivo.write_text('El adversario cambió las instrucciones sin nueva versión.')
    with pytest.raises(ValueError, match='huella'):
        cargar_version(tmp_path, identificador)


@pytest.mark.parametrize('campo', ['presupuesto', 'juez', 'modelo', 'identidad', 'ejecutar_python'])
def test_candidato_no_puede_cambiar_capacidades(campo):
    version = sucesor()
    version['harness'][campo] = 'malicioso'
    with pytest.raises(ValueError):
        validar_sucesor(semilla(), version)


def test_una_hipotesis_y_constructor_heredable():
    assert validar_sucesor(semilla(), sucesor()) == sucesor()
    version = sucesor()
    version['harness']['usar_preferencias'] = True
    with pytest.raises(ValueError, match='exactamente una'):
        validar_sucesor(semilla(), version)
    version = sucesor()
    version['skills']['constructor'] = semilla()['skills']['constructor']
    with pytest.raises(ValueError, match='constructor'):
        validar_sucesor(semilla(), version)


def test_rutas_y_enlaces_no_pueden_sacar_lecturas(tmp_path):
    with pytest.raises(ValueError):
        cargar_version(tmp_path, '../../.env')
    carpeta = tmp_path / 'enlace'
    carpeta.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        guardar_version(carpeta, semilla())


def test_datos_del_llamador_no_mutan_version_validada():
    entrada = semilla()
    validada = validar_version(entrada)
    entrada['harness']['usar_preferencias'] = True
    assert validada['harness']['usar_preferencias'] is False


def test_padre_existe_y_es_parte_de_la_huella(tmp_path):
    with pytest.raises(ValueError):
        guardar_version(tmp_path, sucesor(), 'a'*64)
    padre = guardar_version(tmp_path, semilla())
    hijo = guardar_version(tmp_path, sucesor(), padre)
    sin_padre = guardar_version(tmp_path, sucesor())
    assert hijo != sin_padre
    archivo = tmp_path/'versiones'/hijo/'manifest.json'
    manifiesto = json.loads(archivo.read_text())
    manifiesto['padre'] = None
    archivo.write_text(json.dumps(manifiesto))
    with pytest.raises(ValueError, match='huella'):
        cargar_version(tmp_path, hijo)
