from datetime import date

import pytest

from pasteles.herramientas import ejecutar
from pasteles.negocio import Pasteleria


@pytest.fixture
def negocio() -> Pasteleria:
    return Pasteleria(hoy=date(2026, 11, 9))


def pedido(**cambios: object) -> dict:
    return {"producto_id": "chocolate_12", "asistentes": 10, "fecha": "2026-11-13",
            "modalidad": "entrega", "zona": "centro", "restriccion_alimentaria": "ninguna",
            **cambios}


def test_total_incluye_entrega_sin_confirmar_venta(negocio: Pasteleria) -> None:
    resultado = negocio.cotizar_pedido(**pedido())
    assert resultado["total_centavos"] == 71000
    assert resultado["pastel_centavos"] == 65000
    assert resultado["entrega_centavos"] == 6000
    assert resultado["demostracion"] is True
    assert resultado["reservado"] is False
    assert resultado["pagado"] is False


def test_recoger_y_cambio_de_zona_recalculan(negocio: Pasteleria) -> None:
    assert negocio.cotizar_pedido(**pedido(modalidad="recoger", zona=""))["total_centavos"] == 65000
    assert negocio.cotizar_pedido(**pedido(zona="norte"))["total_centavos"] == 74000


def test_presupuesto_considera_entrega(negocio: Pasteleria) -> None:
    assert negocio.cotizar_pedido(**pedido(presupuesto_centavos=70000))["estado"] == "excede_presupuesto"
    assert negocio.cotizar_pedido(**pedido(presupuesto_centavos=71000))["estado"] == "cotizacion_orientativa"


@pytest.mark.parametrize(("cambios", "estado"), [
    ({"fecha": "2026-11-10"}, "fecha_no_disponible"),
    ({"fecha": "2026-11-08"}, "fecha_no_disponible"),
    ({"fecha": "2026-11-14"}, "fecha_no_disponible"),
    ({"fecha": "2027-04-10"}, "requiere_persona"),
    ({"zona": "fuera"}, "requiere_persona"),
    ({"zona": ""}, "requiere_persona"),
    ({"asistentes": 13}, "sin_capacidad"),
    ({"producto_id": "fresa_12"}, "no_disponible"),
    ({"producto_id": "inventado"}, "no_disponible"),
    ({"restriccion_alimentaria": "alergia"}, "requiere_persona"),
    ({"restriccion_alimentaria": "otra"}, "requiere_persona"),
    ({"restriccion_alimentaria": "por_confirmar"}, "faltan_datos"),
    ({"diseno_especial": True}, "requiere_persona"),
    ({"mensaje": "A" * 41}, "requiere_persona"),
])
def test_impedimentos_no_producen_cotizacion(negocio: Pasteleria, cambios: dict, estado: str) -> None:
    resultado = negocio.cotizar_pedido(**pedido(**cambios))
    assert resultado["estado"] == estado
    assert "total_centavos" not in resultado


def test_dos_dias_justos_son_validos(negocio: Pasteleria) -> None:
    assert negocio.cotizar_pedido(**pedido(fecha="2026-11-11"))["estado"] == "cotizacion_orientativa"


def test_cambio_de_fecha_invalida_cotizacion_anterior(negocio: Pasteleria) -> None:
    assert negocio.cotizar_pedido(**pedido())["estado"] == "cotizacion_orientativa"
    assert negocio.cotizar_pedido(**pedido(fecha="2026-11-10"))["estado"] == "fecha_no_disponible"


def test_recomendaciones_caben_en_presupuesto_y_porciones(negocio: Pasteleria) -> None:
    resultado = negocio.recomendar_pasteles(15, 100000)
    assert [opcion["id"] for opcion in resultado["opciones"]] == ["chocolate_20"]
    assert negocio.recomendar_pasteles(10, 50000)["estado"] == "sin_opciones"
    assert negocio.recomendar_pasteles(10, 100000, "fresa")["opciones"] == []


@pytest.mark.parametrize("cambios", [
    {"asistentes": True}, {"asistentes": 0}, {"asistentes": "10"},
    {"presupuesto_centavos": 650.5}, {"presupuesto_centavos": -1},
    {"presupuesto_centavos": None}, {"diseno_especial": "false"},
    {"fecha": "2026-02-30"}, {"fecha": "20261113"},
    {"modalidad": "envio"}, {"modalidad": "recoger"},
    {"restriccion_alimentaria": []}, {"zona": 10},
    {"precio_centavos": 1}, {"hoy": "2026-11-01"},
])
def test_herramientas_rechazan_datos_inseguros(negocio: Pasteleria, cambios: dict) -> None:
    with pytest.raises(ValueError):
        ejecutar(negocio, "cotizar_pedido", pedido(**cambios))


def test_no_hay_estado_compartido_entre_clientes(negocio: Pasteleria) -> None:
    catalogo = negocio.ver_catalogo()
    catalogo["productos"][1]["precio_centavos"] = 1
    negocio.cotizar_pedido(**pedido(mensaje="Cliente anterior"))
    siguiente = negocio.cotizar_pedido(**pedido())
    assert siguiente["total_centavos"] == 71000
    assert siguiente["mensaje"] == ""


def test_no_se_puede_invocar_metodo_interno(negocio: Pasteleria) -> None:
    with pytest.raises(ValueError):
        ejecutar(negocio, "__init__", {})


def test_campos_obligatorios(negocio: Pasteleria) -> None:
    with pytest.raises(ValueError):
        ejecutar(negocio, "cotizar_pedido", {})
