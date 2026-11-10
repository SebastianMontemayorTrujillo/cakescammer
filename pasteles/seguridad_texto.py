"""Texto libre citado sin controles que puedan suplantar el resumen del pedido."""

import json
import unicodedata


def citar_literal(texto: str) -> str:
    """JSON reversible de una sola línea, con español normal y controles visibles."""
    if not isinstance(texto, str):
        raise TypeError("Solo se puede citar texto.")
    citado = json.dumps(texto, ensure_ascii=False)
    return "".join(json.dumps(caracter, ensure_ascii=True)[1:-1]
                   if unicodedata.category(caracter) in {"Cc", "Cf", "Zl", "Zp"}
                   else caracter for caracter in citado)
