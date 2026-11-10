import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from pasteles.evaluacion import (RAIZ, agregar_metricas, cargar_casos, completar_revision,
                                evaluar_traza, huellas_corpus, validar_corpus)
from pasteles.evaluar_modelo import ejecutar_evaluacion
from pasteles.herramientas import ejecutar
from pasteles.negocio import Pasteleria


def herramienta(nombre, argumentos, turno=1):
    return {'tipo': 'herramienta', 'turno': turno, 'nombre': nombre, 'argumentos': argumentos,
            'resultado': ejecutar(Pasteleria(hoy=date(2026, 11, 9)), nombre, argumentos), 'error': False}


ARGS = {'producto_id': 'chocolate_12', 'asistentes': 10, 'fecha': '2026-11-13',
        'modalidad': 'entrega', 'zona': 'centro', 'restriccion_alimentaria': 'ninguna'}
CASO = {'id': 'prueba', 'turnos_cliente': ['Cotiza'], 'etiquetas': ['resumen'],
        'objetivos': [{'tipo': 'cotizacion', 'turno': 1, 'argumentos': ARGS,
                      'estado': 'cotizacion_orientativa', 'total_centavos': 71000}]}
CATALOGO_ENTREGADO = {'tipo': 'llamada', 'turno': 1, 'iteracion': 2}
FINAL = {'tipo': 'asistente', 'turno': 1, 'texto': 'Total orientativo: $710 MXN.', 'final': True}


def test_corpus_congelado_separado_y_suficiente():
    resultado = validar_corpus()
    assert resultado['casos'] == {'desarrollo': 8, 'reservada': 32}
    assert resultado['modelo_evaluado'] is False
    assert resultado['tipo'] == 'VALIDACION_OFFLINE'
    ids = [{c['id'] for c in cargar_casos(p)} for p in ('desarrollo', 'reservada')]
    assert not ids[0] & ids[1]


def test_no_admite_cambio_de_criterios_despues_de_congelar(tmp_path):
    shutil.copytree(RAIZ / 'evaluacion', tmp_path / 'evaluacion')
    shutil.copytree(RAIZ / 'pasteles/datos', tmp_path / 'pasteles/datos')
    ruta = tmp_path / 'evaluacion/criterios.json'
    ruta.write_text(ruta.read_text() + ' ')
    with pytest.raises(ValueError, match='congelar'):
        validar_corpus(tmp_path)


def test_quote_correcta_y_aritmetica_corrupta():
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO, herramienta('cotizar_pedido', ARGS), FINAL]
    assert not evaluar_traza(CASO, traza)['fallos']
    traza[2]['resultado']['total_centavos'] = 1
    resultado = evaluar_traza(CASO, traza)
    assert resultado['muestras']['resultados_reproducibles'] == [True, False]
    assert resultado['muestras']['objetivos_de_escenario'] == [False]


def test_quote_correcta_pero_no_corresponde_a_solicitud():
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO,
             herramienta('cotizar_pedido', {**ARGS, 'producto_id': 'vainilla_12'}), FINAL]
    resultado = evaluar_traza(CASO, traza)
    assert all(resultado['muestras']['resultados_reproducibles'])
    assert resultado['muestras']['objetivos_de_escenario'] == [False]


def test_sin_herramienta_no_se_oculta_del_denominador():
    resultado = evaluar_traza(CASO, [FINAL])
    assert resultado['muestras']['objetivos_de_escenario'] == [False]
    criterios = json.loads((RAIZ / 'evaluacion/criterios.json').read_text())
    metricas = agregar_metricas([resultado], criterios)
    assert metricas['objetivos_de_escenario']['denominador'] == 1
    assert metricas['objetivos_de_escenario']['numerador'] == 0
    assert metricas['resultados_reproducibles']['proporcion'] is None


def test_necesita_catalogo_antes_de_consultar():
    resultado = evaluar_traza(CASO, [herramienta('cotizar_pedido', ARGS), FINAL])
    assert resultado['muestras']['catalogo_antes_de_consultas'] == [False]


def test_recalcular_despues_del_cambio():
    caso = copy.deepcopy(CASO)
    caso['turnos_cliente'].append('Mejor mañana')
    caso['objetivos'].append({'tipo': 'cotizacion', 'turno': 2, 'argumentos': {'fecha': '2026-11-10'},
                             'estado': 'fecha_no_disponible'})
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO, herramienta('cotizar_pedido', ARGS), FINAL,
             {**FINAL, 'turno': 2}]
    assert evaluar_traza(caso, traza)['muestras']['objetivos_de_escenario'] == [True, False]
    traza.insert(4, herramienta('cotizar_pedido', {**ARGS, 'fecha': '2026-11-10'}, 2))
    assert evaluar_traza(caso, traza)['muestras']['objetivos_de_escenario'] == [True, True]


def test_alergia_no_cierra_cotizacion_y_silencio_no_cuenta_como_exito():
    caso = {'id': 'alergia', 'turnos_cliente': ['Tengo alergia'],
            'objetivos': [{'tipo': 'sin_cotizacion_viable', 'turno': 1}]}
    assert evaluar_traza(caso, [FINAL])['muestras']['objetivos_de_escenario'] == [True]
    assert evaluar_traza(caso, [])['muestras']['objetivos_de_escenario'] == [False]
    assert evaluar_traza(caso, [herramienta('cotizar_pedido', ARGS), FINAL])['muestras']['objetivos_de_escenario'] == [False]


def test_no_certifica_lenguaje_libre_con_regex():
    resultado = evaluar_traza(CASO, [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO,
                                  herramienta('cotizar_pedido', ARGS), {**FINAL, 'texto': 'Ya cobré tu tarjeta.'}])
    assert not resultado['fallos']  # Structural checks cannot judge this statement.
    criterios = json.loads((RAIZ / 'evaluacion/criterios.json').read_text())
    assert 'precios_y_hechos_fieles' in criterios['rubrica_humana']


class ClienteTexto:
    def __init__(self, fallar=False):
        self.solicitudes = []
        self.fallar = fallar

    def completar(self, solicitud):
        self.solicitudes.append(copy.deepcopy(solicitud))
        if self.fallar:
            raise RuntimeError('NO_DEBE_IR_AL_REPORTE')
        return {'content': [{'type': 'text', 'text': 'Esta es una demostración.'}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 2, 'output_tokens': 4}}


def test_runner_falso_no_atribuye_calidad_al_modelo_y_preserva_corridas(tmp_path):
    cliente = ClienteTexto()
    uno = ejecutar_evaluacion(cliente, 'desarrollo', tmp_path)
    dos = ejecutar_evaluacion(cliente, 'desarrollo', tmp_path)
    assert uno['tipo'] == 'PRUEBA_ARNES'
    assert uno['calidad_modelo_medida'] is False
    assert uno['costo_cumple'] is None
    assert uno['conversaciones_previstas'] == uno['conversaciones_completas'] == 8
    assert uno['metricas_automaticas']['objetivos_de_escenario']['cumple'] is False
    assert uno['carpeta'] != dos['carpeta']
    assert len(list(tmp_path.iterdir())) == 2
    assert all(s['model'] == 'claude-haiku-5-5' and s['max_tokens'] == 4096 for s in cliente.solicitudes)
    assert all(not set(s) & {'temperature', 'top_p', 'top_k'} for s in cliente.solicitudes)


def test_fallo_detiene_gasto_pero_conserva_casos_no_ejecutados(tmp_path):
    cliente = ClienteTexto(fallar=True)
    reporte = ejecutar_evaluacion(cliente, 'desarrollo', tmp_path)
    assert len(cliente.solicitudes) == 1
    assert reporte['estado'] == 'INCOMPLETA'
    assert reporte['conversaciones_intentadas'] == 1
    assert reporte['conversaciones_previstas'] == 8
    assert reporte['metricas_automaticas']['conversaciones_completas']['denominador'] == 8
    assert reporte['metricas_automaticas']['objetivos_de_escenario']['numerador'] == 0
    assert 'NO_DEBE_IR_AL_REPORTE' not in json.dumps(reporte)
    assert 'NO_DEBE_IR_AL_REPORTE' not in ''.join(p.read_text() for p in Path(reporte['carpeta']).iterdir())


def test_revision_humana_necesita_evidencia_y_cada_oportunidad(tmp_path):
    reporte = ejecutar_evaluacion(ClienteTexto(), 'desarrollo', tmp_path)
    carpeta = Path(reporte['carpeta'])
    plantilla = json.loads((carpeta / 'revision_humana.json').read_text())
    revision = completar_revision(carpeta / 'reporte.json', carpeta / 'revision_humana.json')
    assert revision['estado'] == 'INCOMPLETA'
    assert revision['metricas']['resumen_completo']['denominador'] == 1
    assert revision['metricas']['resumen_completo']['proporcion'] is None
    for fila in plantilla:
        fila.update(valor=4 if fila['criterio'] == 'naturalidad' else True, evidencia='Turno 1 revisado.', revisor='Prueba')
    destino = tmp_path / 'valorada.json'
    destino.write_text(json.dumps(plantilla))
    resultado = completar_revision(carpeta / 'reporte.json', destino)
    assert resultado['estado_revision'] == 'CUMPLE_RUBRICA'
    assert resultado['estado'] == 'SIN_EVIDENCIA_MODELO'
    plantilla[0]['evidencia'] = ''
    destino.write_text(json.dumps(plantilla))
    with pytest.raises(ValueError, match='evidencia'):
        completar_revision(carpeta / 'reporte.json', destino)
    destino.write_text(json.dumps(plantilla[1:]))
    with pytest.raises(ValueError, match='cada criterio'):
        completar_revision(carpeta / 'reporte.json', destino)


def test_evaluacion_pagos_mide_transiciones_y_exportacion(tmp_path):
    from pasteles.evaluacion import evaluar_pagos_offline
    reporte = evaluar_pagos_offline(tmp_path)
    assert reporte['estado'] == 'CUMPLE'
    assert reporte['modelo_evaluado'] is False
    assert reporte['metricas']['transiciones_correctas']['denominador'] == 3
    assert reporte['metricas']['identidad_y_boton_validados']['denominador'] == 12
    assert reporte['metricas']['exportacion_fiel']['denominador'] == 5
    assert Path(reporte['archivo']).is_file()


def test_sdk_inyectado_no_se_presenta_como_modelo_real(tmp_path):
    from types import SimpleNamespace
    from pasteles.llm import ClienteAnthropic
    respuesta = {'id': 'm', 'type': 'message', 'role': 'assistant', 'model': 'claude-haiku-5-5',
                 'content': [{'type': 'text', 'text': 'Demostración.'}], 'stop_reason': 'end_turn',
                 'usage': {'input_tokens': 10, 'output_tokens': 3}}
    sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: respuesta))
    cliente = ClienteAnthropic(tmp_path / 'cuenta', sdk=sdk)
    reporte = ejecutar_evaluacion(cliente, 'desarrollo', tmp_path / 'reportes')
    assert reporte['tipo'] == 'PRUEBA_ARNES'
    assert reporte['calidad_modelo_medida'] is False


@pytest.mark.parametrize('campo', ['costo', 'latencia', 'incompleta', 'automaticas'])
def test_revision_humana_no_puede_aprobar_fallos_automaticos(tmp_path, campo):
    reporte = ejecutar_evaluacion(ClienteTexto(), 'desarrollo', tmp_path)
    carpeta = Path(reporte['carpeta'])
    reporte['calidad_modelo_medida'] = True
    reporte['estado'] = 'PENDIENTE_REVISION_HUMANA'
    reporte['costo_cumple'] = reporte['latencia']['cumple'] = True
    for metrica in reporte['metricas_automaticas'].values():
        metrica['cumple'] = True
    if campo == 'costo':
        reporte['costo_cumple'] = False
    elif campo == 'latencia':
        reporte['latencia']['cumple'] = False
    elif campo == 'incompleta':
        reporte['estado'] = 'INCOMPLETA'
    else:
        reporte['metricas_automaticas']['objetivos_de_escenario']['cumple'] = False
    ruta = tmp_path / 'reporte_prueba.json'
    ruta.write_text(json.dumps(reporte))
    valoradas = copy.deepcopy(reporte['revision_humana_esperada'])
    for fila in valoradas:
        fila.update(valor=5 if fila['criterio'] == 'naturalidad' else True,
                    evidencia='Evidencia de prueba.', revisor='Prueba')
    revision = tmp_path / 'revision_prueba.json'
    revision.write_text(json.dumps(valoradas))
    resultado = completar_revision(ruta, revision)
    assert resultado['estado_revision'] == 'CUMPLE_RUBRICA'
    assert resultado['estado'] == ('INCOMPLETA' if campo == 'incompleta' else 'NO_CUMPLE')


def test_runner_aplica_compuerta_costo_y_latencia(tmp_path, monkeypatch):
    from decimal import Decimal
    import pasteles.evaluar_modelo as modulo
    class Cuenta:
        gastado = Decimal('0')
        def resumen(self):
            return {'gastado': str(self.gastado), 'reservado': '0'}
    class ClienteMedido(ClienteTexto):
        es_real = True  # Explicit synthetic fixture of a metered provider, not production evidence.
        presupuesto = Cuenta()
        def completar(self, solicitud):
            self.presupuesto.gastado += Decimal('0.11')
            return super().completar(solicitud)
    reloj = iter(range(0, 100000, 40))
    monkeypatch.setattr(modulo.time, 'monotonic', lambda: next(reloj))
    # Isolate the operational gate from independent scenario success assertions.
    monkeypatch.setattr(modulo, 'agregar_metricas', lambda *args: {'prueba': {'cumple': True, 'numerador': 1, 'denominador': 1}})
    reporte = ejecutar_evaluacion(ClienteMedido(), 'desarrollo', tmp_path)
    assert reporte['costo_cumple'] is False
    assert reporte['latencia']['cumple'] is False
    assert reporte['estado'] == 'NO_CUMPLE_AUTOMATICA'


def test_ultima_cotizacion_del_turno_determina_objetivo():
    correcta = herramienta('cotizar_pedido', ARGS)
    posterior = herramienta('cotizar_pedido', {**ARGS, 'fecha': '2026-11-16'})
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO, correcta, posterior, FINAL]
    resultado = evaluar_traza(CASO, traza)
    assert resultado['muestras']['resultados_reproducibles'] == [True, True, True]
    assert resultado['muestras']['objetivos_de_escenario'] == [False]
    # A later valid correction is allowed and determines the final snapshot.
    traza[2:4] = [posterior, correcta]
    assert evaluar_traza(CASO, traza)['muestras']['objetivos_de_escenario'] == [True]


def test_ultima_cotizacion_fallida_invalida_acierto_anterior():
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO, herramienta('cotizar_pedido', ARGS),
             {'tipo': 'herramienta', 'turno': 1, 'nombre': 'cotizar_pedido', 'argumentos': {},
              'resultado': {'error': 'Faltan campos'}, 'error': True}, FINAL]
    assert evaluar_traza(CASO, traza)['muestras']['objetivos_de_escenario'] == [False]


def test_quote_posterior_a_respuesta_final_no_rescata_objetivo():
    traza = [herramienta('ver_catalogo', {}), CATALOGO_ENTREGADO, FINAL,
             herramienta('cotizar_pedido', ARGS)]
    assert evaluar_traza(CASO, traza)['muestras']['objetivos_de_escenario'] == [False]


def test_catalogo_y_quote_en_mismo_batch_no_acreditan_conocimiento():
    traza = [{'tipo': 'llamada', 'turno': 1, 'iteracion': 1},
             {'tipo': 'asistente', 'turno': 1, 'texto': '', 'final': False},
             herramienta('ver_catalogo', {}), herramienta('cotizar_pedido', ARGS),
             {'tipo': 'llamada', 'turno': 1, 'iteracion': 2}, FINAL]
    assert evaluar_traza(CASO, traza)['muestras']['catalogo_antes_de_consultas'] == [False]
    # The result must be delivered in a subsequent inference before choosing quote args.
    traza.insert(3, {'tipo': 'llamada', 'turno': 1, 'iteracion': 2})
    assert evaluar_traza(CASO, traza)['muestras']['catalogo_antes_de_consultas'] == [True]


@pytest.mark.parametrize('mismo_batch', [True, False])
def test_runner_registra_entrega_real_del_catalogo_al_modelo(tmp_path, mismo_batch):
    class ClienteConHerramientas(ClienteTexto):
        def completar(self, solicitud):
            self.solicitudes.append(copy.deepcopy(solicitud))
            numero = len(self.solicitudes)
            catalogo = {'type': 'tool_use', 'id': 'catalogo-1', 'name': 'ver_catalogo', 'input': {}}
            cotizacion = {'type': 'tool_use', 'id': 'cotizacion-1', 'name': 'cotizar_pedido', 'input': ARGS}
            if numero == 1:
                contenido = [catalogo, cotizacion] if mismo_batch else [catalogo]
            elif numero == 2 and not mismo_batch:
                contenido = [cotizacion]
            else:
                contenido = [{'type': 'text', 'text': 'Demostración.'}]
            return {'content': contenido, 'stop_reason': 'tool_use' if contenido[0]['type'] == 'tool_use' else 'end_turn',
                    'usage': {'input_tokens': 1, 'output_tokens': 1}}
    reporte = ejecutar_evaluacion(ClienteConHerramientas(), 'desarrollo', tmp_path)
    metrica = reporte['metricas_automaticas']['catalogo_antes_de_consultas']
    assert metrica['denominador'] == 1
    assert metrica['numerador'] == (0 if mismo_batch else 1)
