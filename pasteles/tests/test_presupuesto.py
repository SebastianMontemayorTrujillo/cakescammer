from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from pasteles.presupuesto import Presupuesto, PresupuestoAgotado, PresupuestoBloqueado, RESERVA_MAXIMA


def test_reserva_y_cargo_sobreviven_reinicio(tmp_path):
    ruta = tmp_path / "gasto.sqlite3"
    presupuesto = Presupuesto(ruta)
    pendiente = presupuesto.reservar()
    liquidada = presupuesto.reservar()
    presupuesto.confirmar(liquidada, Decimal("0.00315"))
    presupuesto.confirmar(liquidada, Decimal("0.00315"))
    reiniciado = Presupuesto(ruta)
    resumen = reiniciado.resumen()
    assert Decimal(resumen["gastado"]) == Decimal("0.00315")
    assert Decimal(resumen["reservado"]) == RESERVA_MAXIMA
    assert Decimal(resumen["disponible"]) == Decimal("5") - RESERVA_MAXIMA - Decimal("0.00315")
    with pytest.raises(ValueError, match="diferente"):
        reiniciado.confirmar(liquidada, Decimal("0.00316"))
    assert pendiente != liquidada


def test_concurrencia_no_supera_cinco_dolares(tmp_path):
    ruta = tmp_path / "gasto.sqlite3"

    def reservar(_):
        presupuesto = Presupuesto(ruta)
        try:
            return presupuesto.reservar()
        except PresupuestoAgotado:
            return None

    with ThreadPoolExecutor(max_workers=12) as grupo:
        reservas = list(grupo.map(reservar, range(30)))
    assert len(set(filter(None, reservas))) == 9
    resumen = Presupuesto(ruta).resumen()
    assert Decimal(resumen["reservado"]) == RESERVA_MAXIMA * 9
    assert Decimal(resumen["reservado"]) <= Decimal("5")


@pytest.mark.parametrize("limite", ["0", "-1", "5.01", "NaN", "Infinity", "no-numero"])
def test_rechaza_limites_invalidos(tmp_path, limite):
    with pytest.raises(ValueError):
        Presupuesto(tmp_path / "gasto.sqlite3", limite)


def test_limite_persistido_solo_puede_bajar(tmp_path):
    ruta = tmp_path / "gasto.sqlite3"
    Presupuesto(ruta, "2")
    with pytest.raises(ValueError, match="aumentar"):
        Presupuesto(ruta, "5")
    presupuesto = Presupuesto(ruta, "1")
    assert Decimal(presupuesto.resumen()["limite"]) == Decimal("1")
    presupuesto.reservar()
    with pytest.raises(PresupuestoAgotado):
        presupuesto.reservar()


def test_cargo_invalido_conserva_reserva(tmp_path):
    presupuesto = Presupuesto(tmp_path / "gasto.sqlite3")
    reserva = presupuesto.reservar()
    for costo in [Decimal("-1"), Decimal("NaN")]:
        with pytest.raises(ValueError):
            presupuesto.confirmar(reserva, costo)
    assert Decimal(presupuesto.resumen()["reservado"]) == RESERVA_MAXIMA
    assert Decimal(presupuesto.resumen()["gastado"]) == 0


def test_cargo_superior_a_reserva_se_registra_y_bloquea(tmp_path):
    ruta = tmp_path / "gasto.sqlite3"
    presupuesto = Presupuesto(ruta)
    reserva = presupuesto.reservar()
    with pytest.raises(PresupuestoBloqueado, match="registró"):
        presupuesto.confirmar(reserva, Decimal("1"))
    reiniciado = Presupuesto(ruta)
    resumen = reiniciado.resumen()
    assert Decimal(resumen["gastado"]) == Decimal("1")
    assert Decimal(resumen["reservado"]) == 0
    assert Decimal(resumen["disponible"]) == 0
    assert resumen["bloqueado"] is True
    with pytest.raises(PresupuestoBloqueado):
        reiniciado.reservar()
    reiniciado.confirmar(reserva, Decimal("1"))
    assert Decimal(reiniciado.resumen()["gastado"]) == Decimal("1")


def test_consulta_readonly_respeta_limite_reducido_y_no_crea_estado(tmp_path):
    ruta = tmp_path / "gasto.sqlite3"
    with pytest.raises(ValueError, match="Todavía"):
        Presupuesto.consultar(ruta)
    assert not ruta.exists()
    presupuesto = Presupuesto(ruta, "1")
    presupuesto.reservar()
    antes = ruta.read_bytes()
    resumen = Presupuesto.consultar(ruta)
    assert Decimal(resumen["limite"]) == Decimal("1")
    assert Decimal(resumen["reservado"]) == RESERVA_MAXIMA
    assert ruta.read_bytes() == antes
