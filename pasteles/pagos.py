"""Pedidos SIMULACION: instantáneas, cierre atómico y exportes sin identidad."""

from __future__ import annotations

import csv
import json
import os
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .herramientas import ejecutar
from .negocio import Pasteleria

VIGENCIA_SEGUNDOS = 30 * 60
ACCIONES = {"aprobar": "aprobado", "rechazar": "rechazado", "cancelar": "cancelado"}


class ErrorPago(ValueError):
    """Impedimento seguro para mostrar al usuario, sin datos de terceros."""


@dataclass(frozen=True)
class Identidad:
    chat_id: str
    usuario_id: str
    sesion_id: str
    clave_sesion: str

    def __post_init__(self) -> None:
        if (not self.chat_id.isdecimal() or not self.usuario_id.isdecimal()
                or not self.sesion_id or not self.clave_sesion):
            raise ErrorPago("No hay una sesión privada autenticada.")


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _fecha(valor: float) -> str:
    return datetime.fromtimestamp(valor, timezone.utc).isoformat()


class AlmacenPagos:
    def __init__(self, ruta: Path, negocio: Pasteleria | None = None,
                 reloj: Callable[[], float] | None = None) -> None:
        self.ruta = Path(ruta)
        self.negocio = negocio or Pasteleria()
        self.reloj = reloj or time.time
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sesiones (
                    id TEXT PRIMARY KEY, cerrada INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS llamadas (
                    orden INTEGER PRIMARY KEY AUTOINCREMENT,
                    sesion TEXT NOT NULL, llamada TEXT NOT NULL, terminada INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(sesion, llamada));
                CREATE TABLE IF NOT EXISTS cotizaciones (
                    id TEXT PRIMARY KEY, orden INTEGER NOT NULL,
                    chat TEXT NOT NULL, usuario TEXT NOT NULL, sesion TEXT NOT NULL, clave TEXT NOT NULL,
                    solicitud TEXT NOT NULL, detalle TEXT NOT NULL,
                    creada REAL NOT NULL, vence REAL NOT NULL, activa INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS pedidos (
                    id TEXT PRIMARY KEY, cotizacion TEXT NOT NULL UNIQUE REFERENCES cotizaciones(id),
                    estado TEXT NOT NULL, token TEXT NOT NULL UNIQUE, mensaje TEXT,
                    creado REAL NOT NULL, actualizado REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pedido TEXT NOT NULL REFERENCES pedidos(id),
                    fecha REAL NOT NULL, evento TEXT NOT NULL, motivo TEXT NOT NULL);
            """)
        os.chmod(self.ruta, 0o600)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.ruta, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _evento(self, db: sqlite3.Connection, pedido: str, evento: str, motivo: str = "") -> None:
        db.execute("INSERT INTO eventos(pedido, fecha, evento, motivo) VALUES (?, ?, ?, ?)",
                   (pedido, self.reloj(), evento, motivo))

    def _cerrar(self, db: sqlite3.Connection, pedido: str, estado: str, motivo: str = "") -> None:
        cambiado = db.execute("UPDATE pedidos SET estado=?, actualizado=? WHERE id=? AND estado='pendiente'",
                              (estado, self.reloj(), pedido)).rowcount
        if cambiado:
            self._evento(db, pedido, estado, motivo)

    def _invalidar(self, db: sqlite3.Connection, sesion: str, motivo: str) -> None:
        for fila in db.execute("SELECT p.id FROM pedidos p JOIN cotizaciones c ON c.id=p.cotizacion "
                               "WHERE c.sesion=? AND p.estado='pendiente'", (sesion,)).fetchall():
            self._cerrar(db, fila["id"], "invalidado", motivo)
        db.execute("UPDATE cotizaciones SET activa=0 WHERE sesion=?", (sesion,))

    def _iniciar(self, db: sqlite3.Connection, identidad: Identidad, llamada: str) -> int | None:
        if not llamada:
            raise ErrorPago("No hay identificador de la cotización.")
        db.execute("INSERT OR IGNORE INTO sesiones(id) VALUES (?)", (identidad.sesion_id,))
        if db.execute("SELECT cerrada FROM sesiones WHERE id=?", (identidad.sesion_id,)).fetchone()[0]:
            return None
        existente = db.execute("SELECT orden FROM llamadas WHERE sesion=? AND llamada=?",
                               (identidad.sesion_id, llamada)).fetchone()
        if existente:
            return existente[0]
        self._invalidar(db, identidad.sesion_id, "nueva_cotizacion")
        return db.execute("INSERT INTO llamadas(sesion, llamada) VALUES (?, ?)",
                          (identidad.sesion_id, llamada)).lastrowid

    def iniciar_cotizacion(self, identidad: Identidad, id_llamada: str) -> None:
        """Invalida botones antes de ejecutar otra cotización, aunque esta falle."""
        with self._conexion() as db:
            self._iniciar(db, identidad, id_llamada)

    def capturar(self, identidad: Identidad, argumentos: object, id_llamada: str,
                 *, valido: bool = True) -> dict[str, Any] | None:
        """Recalcula localmente: nunca usa importes de texto del modelo ni de un callback."""
        with self._conexion() as db:
            orden = self._iniciar(db, identidad, id_llamada)
            if orden is None:
                return None
            llamada = db.execute("SELECT terminada FROM llamadas WHERE orden=?", (orden,)).fetchone()
            ultima = db.execute("SELECT MAX(orden) FROM llamadas WHERE sesion=?",
                                (identidad.sesion_id,)).fetchone()[0]
            if llamada[0] or orden != ultima:
                return None
            db.execute("UPDATE llamadas SET terminada=1 WHERE orden=?", (orden,))
            if not valido:
                return None
            try:
                detalle = ejecutar(self.negocio, "cotizar_pedido", argumentos)
            except (ValueError, TypeError):
                return None
            if detalle["estado"] != "cotizacion_orientativa":
                return None
            ahora = self.reloj()
            identificador = uuid4().hex
            db.execute("INSERT INTO cotizaciones VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                       (identificador, orden, identidad.chat_id, identidad.usuario_id,
                        identidad.sesion_id, identidad.clave_sesion, _json(argumentos),
                        _json(detalle), ahora, ahora + VIGENCIA_SEGUNDOS))
            return {"id": identificador, "cotizacion": detalle, "vence": ahora + VIGENCIA_SEGUNDOS}

    @staticmethod
    def _coincide(cotizacion: sqlite3.Row, identidad: Identidad) -> bool:
        return (cotizacion["chat"], cotizacion["usuario"], cotizacion["sesion"], cotizacion["clave"]) == (
            identidad.chat_id, identidad.usuario_id, identidad.sesion_id, identidad.clave_sesion)

    def _vigente(self, cotizacion: sqlite3.Row) -> bool:
        if not cotizacion["activa"] or self.reloj() >= cotizacion["vence"]:
            return False
        try:
            actual = ejecutar(self.negocio, "cotizar_pedido", json.loads(cotizacion["solicitud"]))
        except (ValueError, TypeError):
            return False
        return actual == json.loads(cotizacion["detalle"])

    def _pedido(self, db: sqlite3.Connection, identificador: str) -> dict[str, Any]:
        fila = db.execute("SELECT p.*, c.detalle, c.vence FROM pedidos p "
                          "JOIN cotizaciones c ON c.id=p.cotizacion WHERE p.id=?", (identificador,)).fetchone()
        return {"id": fila["id"], "etiqueta": "SIMULACION", "estado": fila["estado"],
                "cotizacion": json.loads(fila["detalle"]), "token": fila["token"],
                "mensaje_id": fila["mensaje"], "creado": _fecha(fila["creado"]),
                "actualizado": _fecha(fila["actualizado"]), "vence": _fecha(fila["vence"]),
                "pagado": False, "reservado": False}

    def preparar(self, identidad: Identidad) -> dict[str, Any]:
        error = None
        resultado = None
        with self._conexion() as db:
            cotizacion = db.execute("SELECT * FROM cotizaciones WHERE sesion=? AND chat=? AND usuario=? "
                                    "AND clave=? ORDER BY orden DESC LIMIT 1",
                                    (identidad.sesion_id, identidad.chat_id, identidad.usuario_id,
                                     identidad.clave_sesion)).fetchone()
            if cotizacion is None:
                error = "Pide una cotización completa antes de usar /pagar."
            elif not self._vigente(cotizacion):
                self._invalidar(db, identidad.sesion_id, "cotizacion_vencida_o_modificada")
                error = "La cotización ya no está vigente. Solicita una nueva."
            else:
                existente = db.execute("SELECT id FROM pedidos WHERE cotizacion=?", (cotizacion["id"],)).fetchone()
                identificador = existente[0] if existente else uuid4().hex
                if not existente:
                    ahora = self.reloj()
                    db.execute("INSERT INTO pedidos VALUES (?, ?, 'pendiente', ?, NULL, ?, ?)",
                               (identificador, cotizacion["id"], secrets.token_urlsafe(18), ahora, ahora))
                    self._evento(db, identificador, "creado")
                resultado = self._pedido(db, identificador)
        if error:
            raise ErrorPago(error)
        assert resultado is not None
        return resultado

    def vincular_mensaje(self, identidad: Identidad, pedido_id: str, mensaje_id: str) -> None:
        with self._conexion() as db:
            cotizacion = db.execute("SELECT c.* FROM cotizaciones c JOIN pedidos p ON p.cotizacion=c.id "
                                    "WHERE p.id=?", (pedido_id,)).fetchone()
            if not cotizacion or not self._coincide(cotizacion, identidad):
                raise ErrorPago("Ese pedido no está disponible en este chat.")
            # Un reenvío recupera una tarjeta fallida y revoca automáticamente la anterior.
            db.execute("UPDATE pedidos SET mensaje=? WHERE id=? AND estado='pendiente'", (str(mensaje_id), pedido_id))

    def resolver(self, chat_id: str, usuario_id: str, mensaje_id: str,
                 token: str, accion: str) -> dict[str, Any]:
        if accion not in ACCIONES:
            raise ErrorPago("Acción de simulación desconocida.")
        with self._conexion() as db:
            pedido = db.execute("SELECT * FROM pedidos WHERE token=?", (token,)).fetchone()
            if not pedido:
                raise ErrorPago("Este botón no está disponible.")
            cotizacion = db.execute("SELECT * FROM cotizaciones WHERE id=?", (pedido["cotizacion"],)).fetchone()
            if (cotizacion["chat"] != str(chat_id) or cotizacion["usuario"] != str(usuario_id)
                    or pedido["mensaje"] is None or pedido["mensaje"] != str(mensaje_id)):
                raise ErrorPago("Este botón no está disponible para esta cuenta o mensaje.")
            if pedido["estado"] == "pendiente":
                if not self._vigente(cotizacion):
                    self._cerrar(db, pedido["id"], "caducado", "cotizacion_vencida_o_modificada")
                else:
                    self._cerrar(db, pedido["id"], ACCIONES[accion])
            return self._pedido(db, pedido["id"])

    def consultar(self, identidad: Identidad) -> dict[str, Any] | None:
        with self._conexion() as db:
            fila = db.execute("SELECT p.id, p.estado, c.id AS cotizacion FROM pedidos p JOIN cotizaciones c ON c.id=p.cotizacion "
                              "WHERE c.chat=? AND c.usuario=? AND c.clave=? ORDER BY p.creado DESC, c.orden DESC LIMIT 1",
                              (identidad.chat_id, identidad.usuario_id, identidad.clave_sesion)).fetchone()
            if fila is None:
                return None
            cotizacion = db.execute("SELECT * FROM cotizaciones WHERE id=?", (fila["cotizacion"],)).fetchone()
            if fila["estado"] == "pendiente" and not self._vigente(cotizacion):
                self._cerrar(db, fila["id"], "caducado", "cotizacion_vencida_o_modificada")
            return self._pedido(db, fila["id"])

    def invalidar_sesion(self, sesion_id: str) -> None:
        if not sesion_id:
            return
        with self._conexion() as db:
            db.execute("INSERT INTO sesiones(id, cerrada) VALUES (?, 1) "
                       "ON CONFLICT(id) DO UPDATE SET cerrada=1", (sesion_id,))
            self._invalidar(db, sesion_id, "nueva_sesion")

    def invalidar_sesiones_anteriores(self) -> None:
        """Inicio de un consumidor exclusivo: cierra sesiones y tarjetas previas.

        Los pedidos terminales y el historial permanecen intactos. También se
        impide que una llamada tardía vuelva a cotizar en una sesión cerrada.
        """
        with self._conexion() as db:
            for fila in db.execute("SELECT id FROM sesiones").fetchall():
                self._invalidar(db, fila["id"], "reinicio_telegram")
            db.execute("UPDATE sesiones SET cerrada=1")

    def validar_boton(self, identidad: Identidad, token: str) -> None:
        """Un botón del consumidor RSI debe pertenecer a su generación actual."""
        with self._conexion() as db:
            cotizacion = db.execute("SELECT c.* FROM cotizaciones c JOIN pedidos p ON p.cotizacion=c.id "
                                    "WHERE p.token=?", (token,)).fetchone()
            if cotizacion is None or not self._coincide(cotizacion, identidad):
                raise ErrorPago("Este botón pertenece a una conversación anterior o distinta.")

    def exportar(self, formato: str, ruta: Path) -> int:
        """Exporta pedidos y su historial; excluye identidad, tokens y texto libre."""
        if formato not in {"json", "csv"}:
            raise ValueError("El formato debe ser json o csv.")
        campos = ("producto_id", "producto", "asistentes", "porciones", "fecha", "modalidad", "zona",
                  "pastel_centavos", "entrega_centavos", "total_centavos", "moneda")
        filas = []
        with self._conexion() as db:
            for fila in db.execute("SELECT p.*, c.detalle FROM pedidos p JOIN cotizaciones c "
                                   "ON c.id=p.cotizacion ORDER BY p.creado, p.id").fetchall():
                detalle = json.loads(fila["detalle"])
                historial = [{"fecha": _fecha(e["fecha"]), "evento": e["evento"], "motivo": e["motivo"]}
                             for e in db.execute("SELECT fecha, evento, motivo FROM eventos WHERE pedido=? ORDER BY id",
                                                 (fila["id"],))]
                filas.append({"pedido_id": fila["id"], "etiqueta": "SIMULACION", "estado": fila["estado"],
                              "creado": _fecha(fila["creado"]), "actualizado": _fecha(fila["actualizado"]),
                              **{k: detalle[k] for k in campos}, "pagado": False, "reservado": False,
                              "eventos": historial})
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Exportes nuevos: nunca sobreescribir un archivo previo de resultados.
        with ruta.open("x", encoding="utf-8", newline="") as archivo:
            os.chmod(ruta, 0o600)
            if formato == "json":
                json.dump({"etiqueta": "SIMULACION", "pedidos": filas}, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
            else:
                nombres = ["pedido_id", "etiqueta", "estado", "creado", "actualizado", *campos, "pagado", "reservado", "eventos"]
                escritor = csv.DictWriter(archivo, fieldnames=nombres)
                escritor.writeheader()
                for fila in filas:
                    valores = {**fila, "eventos": _json(fila["eventos"])}
                    for clave, valor in valores.items():
                        if isinstance(valor, str) and valor.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                            valores[clave] = "'" + valor
                    escritor.writerow(valores)
        return len(filas)
