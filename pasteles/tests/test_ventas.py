import copy
import json
from datetime import date

import pytest

from pasteles.negocio import Pasteleria
from pasteles.ventas import (cierre_consultivo, elegir_producto, metricas_embudo,
                             propuesta_comercial)


@pytest.fixture
def catalogo():
    return Pasteleria(hoy=date(2026, 11, 9)).ver_catalogo()


def pedido(**cambios):
    return {'sabor': 'chocolate', 'asistentes': 10, 'fecha': '2026-11-13',
            'modalidad': 'entrega', 'zona': 'centro', 'restriccion_alimentaria': 'ninguna', **cambios}


def test_valor_explicito_con_beneficio_y_total_que_incluye_entrega(catalogo):
    datos = pedido(porciones_extra=True, presupuesto_centavos=110000)
    antes = copy.deepcopy((catalogo, datos))
    assert elegir_producto(catalogo, datos, 'ajuste') == 'chocolate_12'
    propuesta = propuesta_comercial(catalogo, datos, 'valor')
    assert propuesta['producto_id'] == 'chocolate_20'
    assert propuesta['cotizacion']['total_centavos'] == 101000
    assert propuesta['alternativa']['porciones_adicionales'] == 8
    assert propuesta['alternativa']['diferencia_centavos'] == 30000
    assert '8 porciones adicionales' in propuesta['beneficio']
    assert '$1010.00 MXN' in propuesta['beneficio']
    assert (catalogo, datos) == antes


@pytest.mark.parametrize('cambios', [{}, {'porciones_extra': False}, {'porciones_extra': 'si'},
                                      {'presupuesto_centavos': 110000}, {'porciones_extra': True}])
def test_no_sube_ticket_sin_permiso_y_presupuesto_explicitos(catalogo, cambios):
    assert elegir_producto(catalogo, pedido(**cambios), 'valor') == 'chocolate_12'


def test_el_envio_impide_upsell_que_solo_cabe_sin_entrega(catalogo):
    datos = pedido(porciones_extra=True, presupuesto_centavos=100000)
    propuesta = propuesta_comercial(catalogo, datos, 'valor')
    assert propuesta['producto_id'] == 'chocolate_12'
    assert propuesta['alternativa'] is None
    assert propuesta['cotizacion']['total_centavos'] == 71000


def test_presupuesto_insuficiente_permanece_visible(catalogo):
    propuesta = propuesta_comercial(catalogo, pedido(porciones_extra=True, presupuesto_centavos=60000), 'valor')
    assert propuesta['producto_id'] == 'chocolate_12'
    assert propuesta['cotizacion']['estado'] == 'excede_presupuesto'
    assert propuesta['alternativa'] is None
    assert cierre_consultivo(propuesta['cotizacion'], True) == ''


@pytest.mark.parametrize('cambios', [{'fecha': '2026-11-10'}, {'fecha': '2026-11-14'},
                                    {'restriccion_alimentaria': 'alergia'}, {'restriccion_alimentaria': 'por_confirmar'},
                                    {'asistentes': 30}, {'zona': 'sur'}, {'diseno_especial': True}])
def test_no_propone_opcion_no_viable(catalogo, cambios):
    propuesta = propuesta_comercial(catalogo, pedido(porciones_extra=True, presupuesto_centavos=120000, **cambios), 'valor')
    assert propuesta['producto_id'] is None
    assert propuesta['alternativa'] is None
    assert cierre_consultivo(propuesta['cotizacion'], True) == ''


def test_no_cambia_sabor_ni_vende_producto_no_disponible(catalogo):
    datos = pedido(sabor='vainilla', porciones_extra=True, presupuesto_centavos=200000)
    assert elegir_producto(catalogo, datos, 'valor') == 'vainilla_12'
    catalogo['productos'][2]['disponible'] = False
    assert elegir_producto(catalogo, pedido(porciones_extra=True, presupuesto_centavos=200000), 'valor') == 'chocolate_12'
    assert elegir_producto(catalogo, pedido(producto_id='fresa_12'), 'valor') is None


def test_cierre_unico_claro_solo_simulado(catalogo):
    cotizacion = propuesta_comercial(catalogo, pedido())['cotizacion']
    assert cierre_consultivo(cotizacion, False) == ''
    cierre = cierre_consultivo(cotizacion, True)
    assert cierre.count('¿') == 1 and '/pagar' in cierre and 'SIMULADO' in cierre
    assert cierre_consultivo(None, True) == ''
    assert cierre_consultivo({**cotizacion, 'estado': 'rechazo'}, True) == ''
    assert cierre_consultivo({**cotizacion, 'pagado': True}, True) == ''


def fila(id,estado,total=71000):
    return {'pedido_id': id, 'etiqueta': 'SIMULACION', 'estado': estado,
            'total_centavos': total, 'moneda': 'MXN', 'pagado': False, 'reservado': False}


def test_embudo_deriva_unicamente_de_registros_aprobados():
    datos = [fila('a','aprobado'),fila('b','aprobado',101000),fila('c','rechazado'),
             fila('d','pendiente'),fila('e','cancelado'),fila('f','caducado')]
    metricas = metricas_embudo({'etiqueta':'SIMULACION','pedidos':datos})
    assert metricas['intentos_simulados'] == 6
    assert metricas['aprobaciones_sobre_intentos'] == {'numerador':2,'denominador':6,'proporcion':2/6}
    assert metricas['aprobaciones_sobre_resueltos']['denominador'] == 5
    assert metricas['ingreso_simulado_centavos'] == 172000
    assert metricas['ticket_promedio_simulado_centavos'] == 86000
    assert metricas['ticket_denominador'] == 2
    assert metricas['simulacion'] is True


def test_sin_registros_no_inventa_conversion_ni_ticket():
    metricas = metricas_embudo([])
    assert metricas['ingreso_simulado_centavos'] == 0
    assert metricas['aprobaciones_sobre_intentos']['proporcion'] is None
    assert metricas['ticket_promedio_simulado_centavos'] is None


def test_embudo_con_exportacion_del_almacen_incluye_invalidaciones_y_caducidad(tmp_path):
    from pasteles.pagos import AlmacenPagos, Identidad, VIGENCIA_SEGUNDOS

    ahora = [1000.0]
    almacen = AlmacenPagos(tmp_path / 'pagos.db', Pasteleria(hoy=date(2026, 11, 9)),
                           reloj=lambda: ahora[0])
    argumentos = {k: v for k, v in pedido(producto_id='chocolate_12').items() if k != 'sabor'}

    def preparar(numero):
        identidad = Identidad(str(numero), str(numero), f'sesion-{numero}', f'telegram:{numero}')
        assert almacen.capturar(identidad, argumentos, f'llamada-{numero}') is not None
        pedido_simulado = almacen.preparar(identidad)
        almacen.vincular_mensaje(identidad, pedido_simulado['id'], str(numero))
        return identidad, pedido_simulado

    invalidado, _ = preparar(1)
    almacen.iniciar_cotizacion(invalidado, 'cotizacion-nueva')
    _, aprobado = preparar(2)
    assert almacen.resolver('2', '2', '2', aprobado['token'], 'aprobar')['estado'] == 'aprobado'
    _, caducado = preparar(3)
    ahora[0] += VIGENCIA_SEGUNDOS
    assert almacen.resolver('3', '3', '3', caducado['token'], 'aprobar')['estado'] == 'caducado'
    preparar(4)
    exportacion = tmp_path / 'exportacion.json'
    assert almacen.exportar('json', exportacion) == 4

    metricas = metricas_embudo(json.loads(exportacion.read_text()))
    assert metricas['estados']['invalidado'] == metricas['estados']['caducado'] == 1
    assert metricas['intentos_simulados'] == 4
    assert metricas['aprobaciones_sobre_intentos'] == {'numerador': 1, 'denominador': 4, 'proporcion': 0.25}
    assert metricas['aprobaciones_sobre_resueltos'] == {'numerador': 1, 'denominador': 3, 'proporcion': 1/3}
    assert metricas['ingreso_simulado_centavos'] == 71000
    assert metricas['ticket_denominador'] == 1


def test_deduplica_exportes_y_rechaza_snapshots_contradictorios():
    registro = fila('a','aprobado')
    metricas = metricas_embudo([registro, copy.deepcopy(registro)])
    assert metricas['ingreso_simulado_centavos'] == 71000
    assert metricas['registros_duplicados_omitidos'] == 1
    with pytest.raises(ValueError,match='contradictorios'):
        metricas_embudo([registro, fila('a','rechazado')])


@pytest.mark.parametrize('cambio', [{'etiqueta':'REAL'}, {'pagado':True}, {'moneda':'USD'},
                                   {'total_centavos':True}, {'total_centavos':1.5}, {'estado':'desconocido'}])
def test_no_mezcla_datos_reales_o_invalidos(cambio):
    with pytest.raises(ValueError):
        metricas_embudo([{**fila('a','aprobado'), **cambio}])
