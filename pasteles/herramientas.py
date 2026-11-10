"""Contratos de las herramientas públicas. El cliente no puede pasar precios."""

from typing import Any

from .negocio import Pasteleria


def esquema(propiedades: dict[str, Any], obligatorias: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": propiedades, "required": obligatorias,
            "additionalProperties": False}


ASISTENTES = {"type": "integer", "minimum": 1, "maximum": 100}
PRESUPUESTO = {"type": "integer", "minimum": 1, "maximum": 10000000,
               "description": "MXN en centavos enteros: $650 MXN = 65000."}

HERRAMIENTAS = [
    {"name": "ver_catalogo", "description": "Consulta productos, precios y políticas FICTICIOS de la demo.",
     "inputSchema": esquema({}, [])},
    {"name": "recomendar_pasteles", "description": "Hasta dos pasteles demo con porciones suficientes y precio base dentro del presupuesto. Entrega aparte.",
     "inputSchema": esquema({"asistentes": ASISTENTES, "presupuesto_centavos": PRESUPUESTO,
                             "sabor": {"type": "string", "maxLength": 60}},
                            ["asistentes", "presupuesto_centavos"])},
    {"name": "cotizar_pedido", "description": "Calcula una cotización demo, sin reservar ni cobrar. Repetir si cambia cualquier dato; nunca afirmar venta confirmada.",
     "inputSchema": esquema({
         "producto_id": {"type": "string", "maxLength": 60},
         "asistentes": ASISTENTES,
         "fecha": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
         "modalidad": {"type": "string", "enum": ["recoger", "entrega"]},
         "restriccion_alimentaria": {"type": "string", "enum": ["ninguna", "alergia", "otra", "por_confirmar"]},
         "zona": {"type": "string", "maxLength": 60},
         "mensaje": {"type": "string", "maxLength": 500},
         "presupuesto_centavos": PRESUPUESTO,
         "diseno_especial": {"type": "boolean"},
     }, ["producto_id", "asistentes", "fecha", "modalidad", "restriccion_alimentaria"])},
]


def ejecutar(negocio: Pasteleria, nombre: str, argumentos: object) -> dict[str, Any]:
    contratos = {herramienta["name"]: herramienta["inputSchema"] for herramienta in HERRAMIENTAS}
    if nombre not in contratos:
        raise ValueError("Herramienta desconocida.")
    if not isinstance(argumentos, dict):
        raise ValueError("Los argumentos deben ser un objeto.")
    contrato = contratos[nombre]
    if set(argumentos) - set(contrato["properties"]):
        raise ValueError("Hay campos no permitidos; los precios los calcula la pastelería.")
    if set(contrato["required"]) - set(argumentos):
        raise ValueError("Faltan campos obligatorios.")
    tipos = {"string": str, "integer": int, "boolean": bool}
    for campo, valor in argumentos.items():
        regla = contrato["properties"][campo]
        if type(valor) is not tipos[regla["type"]]:
            raise ValueError(f"Tipo incorrecto para {campo}.")
    funciones = {"ver_catalogo": negocio.ver_catalogo,
                 "recomendar_pasteles": negocio.recomendar_pasteles,
                 "cotizar_pedido": negocio.cotizar_pedido}
    return funciones[nombre](**argumentos)
