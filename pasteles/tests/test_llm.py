from decimal import Decimal
from types import SimpleNamespace

import pytest

from pasteles.llm import ClienteAnthropic, ClienteFalso, ErrorInferencia, MODELO, SolicitudInvalida, costo_consumo
from pasteles.presupuesto import PresupuestoAgotado, RESERVA_MAXIMA


def solicitud():
    return {"model": MODELO, "messages": [{"role": "user", "content": "Hola"}], "max_tokens": 100}


def respuesta(uso=None):
    return {"id": "msg_prueba", "type": "message", "role": "assistant", "model": MODELO,
            "content": [{"type": "text", "text": "Hola; este catálogo es SIMULACION."}],
            "stop_reason": "end_turn", "usage": uso or {"input_tokens": 100, "output_tokens": 20}}


class SDKFalso:
    def __init__(self, resultado):
        self.resultado = resultado
        self.solicitudes = []
        self.messages = SimpleNamespace(create=self.crear)

    def crear(self, **datos):
        self.solicitudes.append(datos)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


def test_sdk_solo_recibe_contrato_permitido_y_cuenta_consumo(tmp_path):
    sdk = SDKFalso(respuesta())
    cliente = ClienteAnthropic(tmp_path, sdk=sdk)
    assert cliente.es_real is False
    peticion = solicitud()
    peticion.update(temperature=1, top_p=0.9, top_k=2, max_tokens=9999, cache_control={"type": "ephemeral"})
    peticion["system"] = [{"type": "text", "text": "Vendedor", "cache_control": {"type": "ephemeral"}}]
    peticion["tools"] = [{"name": "mcp__pasteles__ver_catalogo", "input_schema": {"type": "null"}, "cache_control": {"type": "ephemeral"}}]
    resultado = cliente.completar(peticion)
    enviado = sdk.solicitudes[0]
    assert enviado["max_tokens"] == 4096
    assert enviado["thinking"] == {"type": "disabled"}
    assert not {"temperature", "top_p", "top_k", "stream", "cache_control"} & enviado.keys()
    assert enviado["system"] == [{"type": "text", "text": "Vendedor"}]
    assert enviado["tools"][0]["input_schema"]["type"] == "object"
    assert "cache_control" not in enviado["tools"][0]
    assert resultado["content"][0]["text"].startswith("Hola")
    assert Decimal(cliente.presupuesto.resumen()["gastado"]) == Decimal("0.000020")
    assert Decimal(cliente.presupuesto.resumen()["reservado"]) == 0


def test_historial_de_herramientas_se_conserva(tmp_path):
    sdk = SDKFalso(respuesta())
    cliente = ClienteAnthropic(tmp_path, sdk=sdk)
    peticion = solicitud()
    peticion["messages"].extend([
        {"role": "assistant", "content": [{"type": "tool_use", "id": "u1", "name": "cotizar_pedido", "input": {"asistentes": 10}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "Resultado determinista", "is_error": False}]},
    ])
    cliente.completar(peticion)
    assert sdk.solicitudes[0]["messages"] == peticion["messages"]


@pytest.mark.parametrize("cambio", [
    {"model": "otro-modelo"}, {"stream": True}, {"max_tokens": True},
    {"messages": [{"role": "assistant", "content": "Prefill"}]},
    {"tools": [{"name": "terminal"}]},
    {"tools": [{"name": "ver_catalogo", "type": "web_search_20250305"}]},
    {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
])
def test_peticion_invalida_no_reserva_ni_llama_sdk(tmp_path, cambio):
    sdk = SDKFalso(respuesta())
    cliente = ClienteAnthropic(tmp_path, sdk=sdk)
    with pytest.raises(SolicitudInvalida):
        cliente.completar(solicitud() | cambio)
    assert not sdk.solicitudes
    assert Decimal(cliente.presupuesto.resumen()["reservado"]) == 0


def test_timeout_conserva_reserva_sin_exponer_error_y_corta_antes_de_sdk(tmp_path):
    sdk = SDKFalso(TimeoutError("secreto-ficticio-de-prueba"))
    cliente = ClienteAnthropic(tmp_path, "1", sdk=sdk)
    with pytest.raises(ErrorInferencia) as error:
        cliente.completar(solicitud())
    assert "secreto-ficticio" not in str(error.value)
    assert Decimal(cliente.presupuesto.resumen()["reservado"]) == RESERVA_MAXIMA
    reiniciado = ClienteAnthropic(tmp_path, "1", sdk=sdk)
    with pytest.raises(PresupuestoAgotado):
        reiniciado.completar(solicitud())
    assert len(sdk.solicitudes) == 1


@pytest.mark.parametrize("uso", [
    {"input_tokens": -1, "output_tokens": 1}, {"input_tokens": True, "output_tokens": 1},
    {"input_tokens": 1_000_001, "output_tokens": 1}, {"input_tokens": 10, "output_tokens": 101},
    {"input_tokens": 10}, {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 5},
])
def test_consumo_invalido_no_libera_reserva(tmp_path, uso):
    cliente = ClienteAnthropic(tmp_path, sdk=SDKFalso(respuesta(uso)))
    with pytest.raises(ErrorInferencia):
        cliente.completar(solicitud())
    assert Decimal(cliente.presupuesto.resumen()["reservado"]) == RESERVA_MAXIMA


def test_tarifas_y_reserva_maxima():
    assert costo_consumo({"input_tokens": 100_000, "output_tokens": 1000}) == Decimal("0.0105")
    assert costo_consumo({"input_tokens": 100_001, "output_tokens": 1000}) == Decimal("0.0525005")
    assert costo_consumo({"input_tokens": 1_000_000, "output_tokens": 4096}) == RESERVA_MAXIMA


def test_sdk_se_configura_sin_reintentos_y_timeout_de_sesenta(monkeypatch, tmp_path):
    import anthropic

    argumentos = {}
    def construir(**opciones):
        argumentos.update(opciones)
        return SDKFalso(respuesta())

    monkeypatch.setenv("ANTHROPIC_API_KEY", "llave-ficticia-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://endpoint-ajeno.invalid")
    monkeypatch.setattr(anthropic, "Anthropic", construir)
    assert ClienteAnthropic(tmp_path).es_real is True
    assert argumentos == {"api_key": "llave-ficticia-test", "base_url": "https://api.anthropic.com",
                          "max_retries": 0, "timeout": 60.0}


def test_modelo_distinto_en_respuesta_no_libera_reserva(tmp_path):
    cliente = ClienteAnthropic(tmp_path, sdk=SDKFalso(respuesta() | {"model": "modelo-no-autorizado"}))
    with pytest.raises(ErrorInferencia):
        cliente.completar(solicitud())
    assert Decimal(cliente.presupuesto.resumen()["reservado"]) == RESERVA_MAXIMA


def test_cliente_falso_no_necesita_credenciales(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cliente = ClienteFalso([respuesta()])
    assert cliente.es_real is False
    assert cliente.completar(solicitud())["id"] == "msg_prueba"
    assert len(cliente.solicitudes) == 1
