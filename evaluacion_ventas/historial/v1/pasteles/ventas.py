"""Propuestas consultivas y métricas de pagos simulados; sin inferencia ni cobros."""
from __future__ import annotations

import copy
from datetime import date
from typing import Any

from .negocio import Pasteleria

_CAMPOS_COTIZACION = {'producto_id', 'asistentes', 'fecha', 'modalidad', 'restriccion_alimentaria',
                     'zona', 'mensaje', 'presupuesto_centavos', 'diseno_especial'}


def _motor(catalogo: dict[str, Any]) -> Pasteleria:
    """El catálogo completo y su fecha son entradas; no usa el reloj del sistema."""
    hoy = date.fromisoformat(catalogo['fecha_local'])
    negocio = Pasteleria.__new__(Pasteleria)
    negocio.hoy_fijo = hoy
    negocio.catalogo = copy.deepcopy(catalogo)
    return negocio


def propuesta_comercial(catalogo: dict[str, Any], datos: dict[str, Any],
                       estrategia: str = 'ajuste') -> dict[str, Any]:
    """El presupuesto insuficiente sigue visible en la cotización base.

    Una mejora de ticket necesita permiso expreso para porciones extra y un
    presupuesto que cubra pastel y entrega. Nunca cambia de sabor para vender más.
    """
    if estrategia not in {'ajuste', 'valor'}:
        raise ValueError('Estrategia comercial desconocida.')
    resultado: dict[str, Any] = {'producto_id': None, 'base_id': None, 'alternativa': None,
                               'beneficio': '', 'cotizacion': None, 'motivo': 'faltan_datos',
                               'simulacion': True}
    if not isinstance(catalogo, dict) or not isinstance(datos, dict):
        return resultado
    try:
        negocio = _motor(catalogo)
    except (KeyError, TypeError, ValueError):
        return resultado
    asistentes = datos.get('asistentes')
    if type(asistentes) is not int or not 1 <= asistentes <= 100:
        return resultado
    productos = catalogo.get('productos', [])
    elegido = next((p for p in productos if p.get('id') == datos.get('producto_id')), None)
    sabor = elegido.get('sabor') if elegido else datos.get('sabor')
    opciones = [p for p in productos if p.get('sabor') == sabor and p.get('disponible') is True
                and type(p.get('porciones')) is int and p['porciones'] >= asistentes
                and type(p.get('precio_centavos')) is int and p['precio_centavos'] > 0]
    opciones.sort(key=lambda p: (p['precio_centavos'], p['porciones'], p['id']))
    if not opciones:
        resultado['motivo'] = 'sin_opcion_suficiente_disponible'
        return resultado
    if datos.get('producto_id'):
        # An explicit unavailable/undersized request is not silently substituted.
        if elegido not in opciones:
            resultado['motivo'] = 'producto_solicitado_no_viable'
            return resultado
        base = elegido
    else:
        base = opciones[0]
    argumentos = {k: copy.deepcopy(v) for k, v in datos.items() if k in _CAMPOS_COTIZACION}

    def cotizar(producto: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return negocio.cotizar_pedido(**{**argumentos, 'producto_id': producto['id']})
        except (TypeError, ValueError):
            return None

    inicial = cotizar(base)
    if inicial is None:
        return resultado
    resultado['motivo'] = inicial['estado']
    # Keep a failed date/restriction result available for a precise explanation.
    resultado['cotizacion'] = inicial
    if inicial['estado'] not in {'cotizacion_orientativa', 'excede_presupuesto'}:
        return resultado
    resultado.update(producto_id=base['id'], base_id=base['id'])
    presupuesto = datos.get('presupuesto_centavos')
    if (estrategia != 'valor' or datos.get('porciones_extra') is not True
            or type(presupuesto) is not int or presupuesto <= 0
            or inicial['estado'] != 'cotizacion_orientativa'):
        return resultado
    alternativas = []
    for producto in opciones:
        if producto['precio_centavos'] <= base['precio_centavos'] or producto['porciones'] <= base['porciones']:
            continue
        cotizacion = cotizar(producto)
        if cotizacion and cotizacion['estado'] == 'cotizacion_orientativa' and cotizacion['total_centavos'] <= presupuesto:
            alternativas.append((producto, cotizacion))
    if not alternativas:
        return resultado
    # Maximize ticket only within the customer's explicitly allowed, useful alternatives.
    producto, cotizacion = max(alternativas, key=lambda par: (par[1]['total_centavos'], par[0]['porciones'], par[0]['id']))
    extra = producto['porciones'] - base['porciones']
    diferencia = cotizacion['total_centavos'] - inicial['total_centavos']
    beneficio = (f'{extra} porciones adicionales por ${diferencia // 100}.{diferencia % 100:02d} MXN más; '
                 f'el total con {"entrega" if datos.get("modalidad") == "entrega" else "recogida"} '
                 f'es ${cotizacion["total_centavos"] // 100}.{cotizacion["total_centavos"] % 100:02d} MXN, dentro de tu presupuesto.')
    resultado.update(producto_id=producto['id'], cotizacion=cotizacion, beneficio=beneficio,
                     alternativa={'producto_id': producto['id'], 'producto_base_id': base['id'],
                                  'porciones_adicionales': extra, 'diferencia_centavos': diferencia,
                                  'total_centavos': cotizacion['total_centavos'], 'moneda': 'MXN'})
    return resultado


def elegir_producto(catalogo: dict[str, Any], datos: dict[str, Any], estrategia: str = 'ajuste') -> str | None:
    return propuesta_comercial(catalogo, datos, estrategia)['producto_id']


def cierre_consultivo(cotizacion: dict[str, Any] | None, activo: bool) -> str:
    if (activo is not True or not isinstance(cotizacion, dict)
            or cotizacion.get('estado') != 'cotizacion_orientativa'
            or type(cotizacion.get('total_centavos')) is not int or cotizacion['total_centavos'] <= 0
            or cotizacion.get('pagado') is not False or cotizacion.get('reservado') is not False):
        return ''
    return ('¿Quieres probar esta opción? Escribe /pagar para elegir el resultado de un pago SIMULADO. '
            'No se cobra dinero ni se reserva un pedido.')


def metricas_embudo(registros: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    """Mide únicamente registros exportados; no inventa decisiones de clientes."""
    if isinstance(registros, dict):
        if registros.get('etiqueta') != 'SIMULACION':
            raise ValueError('Solo se admiten exportaciones de simulación.')
        registros = registros.get('pedidos')
    if not isinstance(registros, list):
        raise ValueError('Se esperaba la lista JSON de pedidos simulados.')
    pedidos = {}
    duplicados = 0
    estados = {'pendiente', 'aprobado', 'rechazado', 'cancelado', 'caducado'}
    for fila in registros:
        if (not isinstance(fila, dict) or fila.get('etiqueta') != 'SIMULACION'
                or not isinstance(fila.get('pedido_id'), str) or not fila['pedido_id']
                or fila.get('estado') not in estados or fila.get('moneda') != 'MXN'
                or type(fila.get('total_centavos')) is not int or fila['total_centavos'] <= 0
                or fila.get('pagado') is not False or fila.get('reservado') is not False):
            raise ValueError('Hay un registro inválido o que no es una simulación.')
        identificador = fila['pedido_id']
        anterior = pedidos.get(identificador)
        # Reject conflicting snapshots instead of choosing whichever was read last.
        if anterior is not None:
            if any(anterior[k] != fila[k] for k in ('estado', 'total_centavos', 'moneda')):
                raise ValueError('El mismo pedido tiene registros contradictorios.')
            duplicados += 1
        else:
            pedidos[identificador] = fila
    conteos = {estado: sum(p['estado'] == estado for p in pedidos.values()) for estado in sorted(estados)}
    aprobados = [p for p in pedidos.values() if p['estado'] == 'aprobado']
    total, resueltos = len(pedidos), len(pedidos) - conteos['pendiente']
    ingreso = sum(p['total_centavos'] for p in aprobados)
    def proporcion(denominador: int) -> dict[str, Any]:
        return {'numerador': len(aprobados), 'denominador': denominador,
                'proporcion': len(aprobados)/denominador if denominador else None}
    return {'tipo': 'EMBUDO_SIMULADO', 'simulacion': True, 'moneda': 'MXN',
            'intentos_simulados': total, 'estados': conteos, 'registros_duplicados_omitidos': duplicados,
            'aprobaciones_sobre_intentos': proporcion(total), 'aprobaciones_sobre_resueltos': proporcion(resueltos),
            'ingreso_simulado_centavos': ingreso,
            'ticket_promedio_simulado_centavos': ingreso/len(aprobados) if aprobados else None,
            'ticket_denominador': len(aprobados),
            'advertencia': 'Estos clics y montos son simulados; no miden ventas, ingresos reales ni efecto de persuasión.'}
