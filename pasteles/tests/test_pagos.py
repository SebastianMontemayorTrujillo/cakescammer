import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from pasteles.negocio import Pasteleria
from pasteles.pagos import AlmacenPagos, ErrorPago, Identidad, VIGENCIA_SEGUNDOS


def argumentos(**cambios):
    return {"producto_id": "chocolate_12", "asistentes": 10, "fecha": "2026-11-13",
            "modalidad": "entrega", "zona": "centro", "restriccion_alimentaria": "ninguna", **cambios}


@pytest.fixture
def entorno(tmp_path):
    reloj = [1000.0]
    negocio = Pasteleria(hoy=date(2026, 11, 9))
    almacen = AlmacenPagos(tmp_path / "pagos.sqlite3", negocio, lambda: reloj[0])
    identidad = Identidad("101", "101", "sesion-a", "telegram:101")
    return almacen, identidad, reloj, negocio


def preparado(almacen, identidad, **cambios):
    almacen.capturar(identidad, argumentos(**cambios), "llamada-a")
    pedido = almacen.preparar(identidad)
    almacen.vincular_mensaje(identidad, pedido["id"], "51")
    return pedido


def test_inicio_consumidor_cierra_pendientes_sin_alterar_terminales(entorno, tmp_path):
    almacen, identidad, _, _ = entorno
    aprobado = preparado(almacen, identidad)
    almacen.resolver("101", "101", "51", aprobado["token"], "aprobar")
    otra = Identidad("202", "202", "sesion-anterior", "telegram:202")
    pendiente = preparado(almacen, otra)
    almacen.invalidar_sesiones_anteriores()
    assert almacen.consultar(identidad)["estado"] == "aprobado"
    assert almacen.consultar(otra)["estado"] == "invalidado"
    assert almacen.resolver("202", "202", "51", pendiente["token"], "aprobar")["estado"] == "invalidado"
    assert almacen.capturar(otra, argumentos(), "llamada-tardia") is None
    almacen.exportar("json", tmp_path / "historial.json")
    filas = json.loads((tmp_path / "historial.json").read_text())["pedidos"]
    por_id = {fila["pedido_id"]: fila for fila in filas}
    assert [e["evento"] for e in por_id[aprobado["id"]]["eventos"]] == ["creado", "aprobado"]
    assert por_id[pendiente["id"]]["eventos"][-1]["motivo"] == "reinicio_telegram"


def test_boton_exige_misma_generacion_identidad_y_clave(entorno):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    almacen.validar_boton(identidad, pedido["token"])
    for otra in (Identidad("101", "101", "sesion-nueva", "telegram:101"),
                 Identidad("101", "101", "sesion-a", "otro-bot:101"),
                 Identidad("202", "202", "sesion-a", "telegram:101")):
        with pytest.raises(ErrorPago):
            almacen.validar_boton(otra, pedido["token"])


@pytest.mark.parametrize(("accion", "estado"), [("aprobar", "aprobado"), ("rechazar", "rechazado"), ("cancelar", "cancelado")])
def test_resultados_son_simulados_sin_cambiar_importe(entorno, accion, estado):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    resultado = almacen.resolver("101", "101", "51", pedido["token"], accion)
    assert resultado["estado"] == estado
    assert resultado["cotizacion"]["total_centavos"] == 71000
    assert resultado["etiqueta"] == "SIMULACION"
    assert not resultado["pagado"] and not resultado["reservado"]


def test_primera_decision_es_definitiva_y_duplicados_no_crean_eventos(entorno, tmp_path):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    for accion in ("aprobar", "cancelar", "rechazar", "aprobar"):
        assert almacen.resolver("101", "101", "51", pedido["token"], accion)["estado"] == "aprobado"
    assert almacen.preparar(identidad)["id"] == pedido["id"]
    destino = tmp_path / "resultados.json"
    assert almacen.exportar("json", destino) == 1
    fila = json.loads(destino.read_text())["pedidos"][0]
    assert [e["evento"] for e in fila["eventos"]] == ["creado", "aprobado"]


def test_clicks_concurrentes_tienen_un_solo_resultado(entorno, tmp_path):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    with ThreadPoolExecutor(max_workers=8) as grupo:
        resultados = list(grupo.map(lambda a: almacen.resolver("101", "101", "51", pedido["token"], a),
                                    ["aprobar", "rechazar", "cancelar"] * 5))
    assert len({r["estado"] for r in resultados}) == 1
    almacen.exportar("json", tmp_path / "concurrente.json")
    assert len(json.loads((tmp_path / "concurrente.json").read_text())["pedidos"][0]["eventos"]) == 2


@pytest.mark.parametrize("cambios", [
    {"restriccion_alimentaria": "alergia"}, {"restriccion_alimentaria": "por_confirmar"},
    {"fecha": "2026-11-10"}, {"fecha": "2027-05-01"}, {"zona": "fuera"},
    {"asistentes": 100}, {"presupuesto_centavos": 70000}, {"diseno_especial": True},
    {"precio_centavos": 1}, {"chat_id": "otra-persona"}, {"pagado": True},
])
def test_nueva_cotizacion_incluso_invalida_revoca_pendiente(entorno, cambios):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    assert almacen.capturar(identidad, argumentos(**cambios), "llamada-b") is None
    assert almacen.resolver("101", "101", "51", pedido["token"], "aprobar")["estado"] == "invalidado"
    with pytest.raises(ErrorPago):
        almacen.preparar(identidad)


def test_invalida_antes_de_ejecutar_y_error_o_respuesta_tardia_no_restaura(entorno):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    almacen.iniciar_cotizacion(identidad, "llamada-b")
    assert almacen.resolver("101", "101", "51", pedido["token"], "aprobar")["estado"] == "invalidado"
    almacen.iniciar_cotizacion(identidad, "llamada-c")
    assert almacen.capturar(identidad, argumentos(), "llamada-b") is None
    assert almacen.capturar(identidad, argumentos(), "llamada-c", valido=False) is None
    with pytest.raises(ErrorPago):
        almacen.preparar(identidad)


def test_hook_duplicado_no_revoca_la_cotizacion_mas_reciente(entorno):
    almacen, identidad, _, _ = entorno
    preparado(almacen, identidad)
    almacen.capturar(identidad, argumentos(modalidad="recoger", zona=""), "llamada-b")
    assert almacen.capturar(identidad, argumentos(), "llamada-a") is None
    assert almacen.preparar(identidad)["cotizacion"]["total_centavos"] == 65000


def test_vencimiento_estricto_a_los_30_minutos(entorno):
    almacen, identidad, reloj, _ = entorno
    pedido = preparado(almacen, identidad)
    reloj[0] += VIGENCIA_SEGUNDOS
    assert almacen.resolver("101", "101", "51", pedido["token"], "aprobar")["estado"] == "caducado"
    with pytest.raises(ErrorPago):
        almacen.preparar(identidad)


def test_consultar_refleja_vencimiento_sin_esperar_un_click(entorno):
    almacen, identidad, reloj, _ = entorno
    preparado(almacen, identidad)
    reloj[0] += VIGENCIA_SEGUNDOS
    assert almacen.consultar(identidad)["estado"] == "caducado"


@pytest.mark.parametrize("cambio", ["precio", "fecha"])
def test_cambio_de_precio_o_fecha_no_altera_snapshot_y_bloquea_pago(entorno, cambio):
    almacen, identidad, _, negocio = entorno
    pedido = preparado(almacen, identidad)
    if cambio == "precio":
        next(p for p in negocio.catalogo["productos"] if p["id"] == "chocolate_12")["precio_centavos"] += 100
    else:
        negocio.hoy_fijo = date(2026, 11, 13)
    resultado = almacen.resolver("101", "101", "51", pedido["token"], "aprobar")
    assert resultado["estado"] == "caducado"
    assert resultado["cotizacion"]["total_centavos"] == 71000


@pytest.mark.parametrize(("chat", "usuario", "mensaje", "token"), [
    ("202", "101", "51", None), ("101", "202", "51", None),
    ("101", "101", "99", None), ("101", "101", "51", "inventado"),
])
def test_callback_requiere_identidad_chat_mensaje_y_token(entorno, chat, usuario, mensaje, token):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    with pytest.raises(ErrorPago):
        almacen.resolver(chat, usuario, mensaje, token or pedido["token"], "aprobar")
    assert almacen.consultar(identidad)["estado"] == "pendiente"
    otra = Identidad("202", "202", "sesion-b", "telegram:202")
    assert almacen.consultar(otra) is None
    with pytest.raises(ErrorPago):
        almacen.preparar(otra)


def test_new_invalida_botones_y_cotizaciones_tardias_sin_borrar_historial(entorno, tmp_path):
    almacen, identidad, _, _ = entorno
    pedido = preparado(almacen, identidad)
    almacen.invalidar_sesion(identidad.sesion_id)
    assert almacen.capturar(identidad, argumentos(), "llamada-tardia") is None
    assert almacen.resolver("101", "101", "51", pedido["token"], "aprobar")["estado"] == "invalidado"
    almacen.exportar("json", tmp_path / "historial.json")
    fila = json.loads((tmp_path / "historial.json").read_text())["pedidos"][0]
    assert fila["eventos"][-1]["motivo"] == "nueva_sesion"


def test_reinicio_conserva_estado_y_nuevas_tarjetas_revocan_anteriores(entorno):
    almacen, identidad, reloj, negocio = entorno
    pedido = preparado(almacen, identidad)
    reinicio = AlmacenPagos(almacen.ruta, negocio, lambda: reloj[0])
    assert reinicio.preparar(identidad)["id"] == pedido["id"]
    reinicio.vincular_mensaje(identidad, pedido["id"], "52")
    with pytest.raises(ErrorPago):
        reinicio.resolver("101", "101", "51", pedido["token"], "aprobar")
    assert reinicio.resolver("101", "101", "52", pedido["token"], "aprobar")["estado"] == "aprobado"


def test_exportes_sin_identidad_textos_libres_o_tokens_y_csv_seguro(entorno, tmp_path):
    almacen, identidad, _, negocio = entorno
    next(p for p in negocio.catalogo["productos"] if p["id"] == "chocolate_12")["nombre"] = "=1+1"
    pedido = preparado(almacen, identidad, mensaje="Mi teléfono es PRIVADO")
    for formato in ("json", "csv"):
        destino = tmp_path / f"exporte.{formato}"
        assert almacen.exportar(formato, destino) == 1
        texto = destino.read_text()
        for prohibido in ("usuario", "chat", "sesion", "token", "PRIVADO", pedido["token"]):
            assert prohibido not in texto
        with pytest.raises(FileExistsError):
            almacen.exportar(formato, destino)
    with (tmp_path / "exporte.csv").open(newline="") as archivo:
        fila = next(csv.DictReader(archivo))
    assert fila["producto"] == "'=1+1"
    assert fila["total_centavos"] == "71000"
    assert fila["etiqueta"] == "SIMULACION"


def test_exporte_vacio_tiene_esquema_y_no_modifica_resultados(tmp_path):
    almacen = AlmacenPagos(tmp_path / "pagos.db")
    assert almacen.exportar("csv", tmp_path / "vacio.csv") == 0
    assert "total_centavos" in (tmp_path / "vacio.csv").read_text()
    with pytest.raises(ValueError):
        almacen.exportar("html", tmp_path / "invalido.html")
