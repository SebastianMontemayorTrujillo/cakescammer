"""Límite acumulado de API con reservas durables y transacciones SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator
from uuid import uuid4


ESCALA = 1_000_000_000
LIMITE_MAXIMO = Decimal("5.00")
RESERVA_MAXIMA = Decimal("0.51024")


class PresupuestoAgotado(RuntimeError):
    """La reserva siguiente no cabe en el límite acumulado."""


class PresupuestoBloqueado(PresupuestoAgotado):
    """Un cargo confirmado superó su reserva y requiere revisión humana."""


def _unidades(valor: str | Decimal) -> int:
    try:
        numero = Decimal(valor)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("El importe debe ser un decimal válido.") from None
    if not numero.is_finite() or numero < 0 or numero * ESCALA != (numero * ESCALA).to_integral_value():
        raise ValueError("El importe debe ser positivo y tener como máximo nueve decimales.")
    return int(numero * ESCALA)


def _dolares(unidades: int) -> str:
    return format(Decimal(unidades) / ESCALA, ".9f")


class Presupuesto:
    """Una ruta identifica un presupuesto; reabrirla nunca reinicia ni aumenta su límite."""

    def __init__(self, ruta: Path, limite: str | Decimal = "5.00") -> None:
        self.ruta = Path(ruta)
        unidades = _unidades(limite)
        if not 0 < unidades <= _unidades(LIMITE_MAXIMO):
            raise ValueError("El límite debe ser mayor que cero y no superar 5 USD.")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._transaccion() as conexion:
            conexion.execute("CREATE TABLE IF NOT EXISTS configuracion (id INTEGER PRIMARY KEY CHECK(id=1), limite INTEGER NOT NULL, bloqueado INTEGER NOT NULL DEFAULT 0)")
            if "bloqueado" not in {fila[1] for fila in conexion.execute("PRAGMA table_info(configuracion)")}:
                conexion.execute("ALTER TABLE configuracion ADD COLUMN bloqueado INTEGER NOT NULL DEFAULT 0")
            conexion.execute("CREATE TABLE IF NOT EXISTS reservas (id TEXT PRIMARY KEY, importe INTEGER NOT NULL, cargo INTEGER, creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            fila = conexion.execute("SELECT limite FROM configuracion WHERE id=1").fetchone()
            if fila is None:
                conexion.execute("INSERT INTO configuracion (id, limite) VALUES (1, ?)", (unidades,))
            elif unidades > fila[0]:
                raise ValueError("No se puede aumentar el límite persistido.")
            elif unidades < fila[0]:
                conexion.execute("UPDATE configuracion SET limite=? WHERE id=1", (unidades,))

    @contextmanager
    def _transaccion(self) -> Iterator[sqlite3.Connection]:
        conexion = sqlite3.connect(self.ruta, timeout=30, isolation_level=None)
        try:
            conexion.execute("PRAGMA synchronous=FULL")
            conexion.execute("BEGIN IMMEDIATE")
            yield conexion
            conexion.commit()
        except BaseException:
            conexion.rollback()
            raise
        finally:
            conexion.close()

    @staticmethod
    def _totales(conexion: sqlite3.Connection) -> tuple[int, int, int]:
        limite = conexion.execute("SELECT limite FROM configuracion WHERE id=1").fetchone()[0]
        gastado, reservado = conexion.execute(
            "SELECT COALESCE(SUM(cargo),0), COALESCE(SUM(CASE WHEN cargo IS NULL THEN importe ELSE 0 END),0) FROM reservas"
        ).fetchone()
        return limite, gastado, reservado

    def reservar(self) -> str:
        """Reserva antes de llamar al proveedor; una caída deja esta reserva intacta."""
        importe = _unidades(RESERVA_MAXIMA)
        with self._transaccion() as conexion:
            if conexion.execute("SELECT bloqueado FROM configuracion WHERE id=1").fetchone()[0]:
                raise PresupuestoBloqueado("El presupuesto está bloqueado por un cargo que superó su reserva.")
            limite, gastado, reservado = self._totales(conexion)
            if gastado + reservado + importe > limite:
                raise PresupuestoAgotado("El presupuesto no alcanza para otra llamada a la API.")
            identificador = uuid4().hex
            conexion.execute("INSERT INTO reservas (id, importe) VALUES (?, ?)", (identificador, importe))
        return identificador

    def confirmar(self, identificador: str, costo: Decimal) -> None:
        """Liquida una reserva solo con consumo conocido; repetir el mismo cargo es idempotente."""
        importe = _unidades(costo)
        with self._transaccion() as conexion:
            fila = conexion.execute("SELECT importe, cargo FROM reservas WHERE id=?", (identificador,)).fetchone()
            if fila is None:
                raise ValueError("Reserva desconocida.")
            if fila[1] is not None:
                if importe != fila[1]:
                    raise ValueError("La reserva ya tiene un cargo diferente.")
                return
            conexion.execute("UPDATE reservas SET cargo=? WHERE id=?", (importe, identificador))
            excedido = importe > fila[0]
            if excedido:
                conexion.execute("UPDATE configuracion SET bloqueado=1 WHERE id=1")
        # El cargo conocido queda registrado incluso cuando viola la cota prevista.
        if excedido:
            raise PresupuestoBloqueado("Se registró un cargo superior a la reserva; el presupuesto quedó bloqueado.")

    @staticmethod
    def _resumen_conexion(conexion: sqlite3.Connection) -> dict[str, str | bool]:
        limite, gastado, reservado = Presupuesto._totales(conexion)
        columnas = {fila[1] for fila in conexion.execute("PRAGMA table_info(configuracion)")}
        bloqueado = (bool(conexion.execute("SELECT bloqueado FROM configuracion WHERE id=1").fetchone()[0])
                     if "bloqueado" in columnas else False)
        return {"limite": _dolares(limite), "gastado": _dolares(gastado),
                "reservado": _dolares(reservado), "bloqueado": bloqueado,
                "disponible": _dolares(0 if bloqueado else max(0, limite - gastado - reservado))}

    def resumen(self) -> dict[str, str | bool]:
        return self.consultar(self.ruta)

    @staticmethod
    def consultar(ruta: Path) -> dict[str, str | bool]:
        """Consulta sin crear archivos, migrar tablas ni aplicar un nuevo límite."""
        ruta = Path(ruta).resolve()
        if not ruta.is_file():
            raise ValueError("Todavía no hay un presupuesto registrado.")
        conexion = sqlite3.connect(ruta.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None)
        try:
            conexion.execute("BEGIN")
            return Presupuesto._resumen_conexion(conexion)
        finally:
            conexion.rollback()
            conexion.close()
