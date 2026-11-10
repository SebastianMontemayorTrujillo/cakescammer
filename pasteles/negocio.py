"""Catálogo y cotizaciones orientativas. Dinero en centavos enteros."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RUTA_CATALOGO = Path(__file__).parent / "datos" / "catalogo.demo.json"


def entero(valor: object, nombre: str, minimo: int, maximo: int) -> int:
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ValueError(f"{nombre} debe ser un entero entre {minimo} y {maximo}.")
    return valor


def texto(valor: object, nombre: str, maximo: int) -> str:
    if not isinstance(valor, str) or len(valor) > maximo:
        raise ValueError(f"{nombre} debe ser texto de hasta {maximo} caracteres.")
    return valor.strip()


class Pasteleria:
    def __init__(self, *, hoy: date | None = None) -> None:
        self.catalogo = json.loads(RUTA_CATALOGO.read_text(encoding="utf-8"))
        self.hoy_fijo = hoy

    def hoy(self) -> date:
        return self.hoy_fijo or datetime.now(ZoneInfo(self.catalogo["zona_horaria"])).date()

    def resultado(self, estado: str, **campos: Any) -> dict[str, Any]:
        return {"demostracion": True, "estado": estado, "moneda": "MXN", **campos}

    def ver_catalogo(self) -> dict[str, Any]:
        # Cargar de nuevo impide que un consumidor modifique nuestro catálogo.
        datos = json.loads(json.dumps(self.catalogo))
        return self.resultado(
            "catalogo_demo", fecha_local=self.hoy().isoformat(), **datos,
            aviso="Datos ficticios. Precios finales de ejemplo; no hay inventario real ni reservas.",
        )

    def recomendar_pasteles(
        self, asistentes: int, presupuesto_centavos: int, sabor: str = ""
    ) -> dict[str, Any]:
        entero(asistentes, "asistentes", 1, 100)
        entero(presupuesto_centavos, "presupuesto_centavos", 1, 10000000)
        sabor = texto(sabor, "sabor", 60).casefold()
        opciones = [
            dict(producto) for producto in self.catalogo["productos"]
            if producto["disponible"] and producto["porciones"] >= asistentes
            and producto["precio_centavos"] <= presupuesto_centavos
            and (not sabor or producto["sabor"] == sabor)
        ]
        opciones.sort(key=lambda producto: producto["precio_centavos"])
        return self.resultado(
            "opciones" if opciones else "sin_opciones", opciones=opciones[:2],
            aviso="Presupuesto aplicado al pastel. Falta cotizar entrega, fecha y restricciones alimentarias.",
            siguiente_paso="Cotizar la opción elegida." if opciones else
            "Ofrecer revisar tamaño, sabor o presupuesto; no inventar descuentos.",
        )

    def cotizar_pedido(
        self,
        producto_id: str,
        asistentes: int,
        fecha: str,
        modalidad: str,
        restriccion_alimentaria: str,
        zona: str = "",
        mensaje: str = "",
        presupuesto_centavos: int | None = None,
        diseno_especial: bool = False,
    ) -> dict[str, Any]:
        producto_id = texto(producto_id, "producto_id", 60)
        entero(asistentes, "asistentes", 1, 100)
        fecha = texto(fecha, "fecha", 10)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            raise ValueError("fecha debe tener formato AAAA-MM-DD.")
        try:
            dia = date.fromisoformat(fecha)
        except ValueError:
            raise ValueError("fecha no es una fecha válida.") from None
        modalidad = texto(modalidad, "modalidad", 20)
        if modalidad not in {"recoger", "entrega"}:
            raise ValueError("modalidad debe ser recoger o entrega.")
        restriccion_alimentaria = texto(restriccion_alimentaria, "restriccion_alimentaria", 30)
        if restriccion_alimentaria not in {"ninguna", "alergia", "otra", "por_confirmar"}:
            raise ValueError("restriccion_alimentaria debe ser ninguna, alergia, otra o por_confirmar.")
        zona = texto(zona, "zona", 60).casefold()
        mensaje = texto(mensaje, "mensaje", 500)
        if type(diseno_especial) is not bool:
            raise ValueError("diseno_especial debe ser verdadero o falso.")
        if presupuesto_centavos is not None:
            entero(presupuesto_centavos, "presupuesto_centavos", 1, 10000000)

        if restriccion_alimentaria == "por_confirmar":
            return self.resultado("faltan_datos", motivo="Confirmar si existen restricciones alimentarias.")
        if restriccion_alimentaria != "ninguna":
            return self.resultado(
                "requiere_persona", motivo="La pastelería debe revisar ingredientes y contaminación cruzada.",
            )
        if diseno_especial or len(mensaje) > self.catalogo["mensaje_personalizado_maximo"]:
            return self.resultado("requiere_persona", motivo="El diseño o mensaje requiere una cotización manual.")
        producto = next((p for p in self.catalogo["productos"] if p["id"] == producto_id), None)
        if not producto or not producto["disponible"]:
            return self.resultado("no_disponible", motivo="Ese pastel no está disponible en el catálogo demo.")
        if producto["porciones"] < asistentes:
            return self.resultado("sin_capacidad", motivo="Las porciones no alcanzan para los asistentes.")
        dias = (dia - self.hoy()).days
        if dias < self.catalogo["anticipacion_dias"]:
            return self.resultado("fecha_no_disponible", motivo="Se requieren al menos dos días de anticipación.")
        if dias > self.catalogo["horizonte_dias"]:
            return self.resultado("requiere_persona", motivo="La fecha supera el horizonte de 60 días del catálogo demo.")
        if fecha in self.catalogo["fechas_cerradas"]:
            return self.resultado("fecha_no_disponible", motivo="La agenda demo está cerrada para esa fecha.")
        if modalidad == "recoger" and zona:
            raise ValueError("Para recoger, zona debe quedar vacía.")
        if modalidad == "entrega" and zona not in self.catalogo["zonas_entrega_centavos"]:
            return self.resultado("requiere_persona", motivo="Falta la zona o está fuera de la cobertura demo.")
        envio = self.catalogo["zonas_entrega_centavos"][zona] if modalidad == "entrega" else 0
        total = producto["precio_centavos"] + envio
        excede = presupuesto_centavos is not None and total > presupuesto_centavos
        return self.resultado(
            "excede_presupuesto" if excede else "cotizacion_orientativa",
            producto_id=producto_id, producto=producto["nombre"], asistentes=asistentes,
            porciones=producto["porciones"], fecha=fecha, modalidad=modalidad, zona=zona,
            mensaje=mensaje, pastel_centavos=producto["precio_centavos"],
            entrega_centavos=envio, total_centavos=total, reservado=False, pagado=False,
            siguiente_paso="Revisar opciones con el cliente." if excede else
            "Pedir permiso para compartir este resumen con una persona que confirme capacidad, horario y pago.",
            aviso="DEMOSTRACIÓN: cotización orientativa. No confirma disponibilidad real ni registra un pedido.",
        )
