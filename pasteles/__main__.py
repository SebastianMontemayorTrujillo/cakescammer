"""Operación local, conversación privada y evaluaciones de Pasteles."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .negocio import Pasteleria
from .servidor_mcp import servir


def principal() -> None:
    parser = argparse.ArgumentParser(description="Pasteles: Telegram privado y pagos de simulación.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("demo", help="Demostración determinista sin API")
    comandos.add_parser("mcp", help="Servidor de herramientas stdio")
    comandos.add_parser("diagnostico", help="Requisitos y configuración; nunca muestra secretos")
    configurar = comandos.add_parser("configurar", help="Preparar perfil dedicado de Hermes")
    configurar.add_argument("--telegram", action="store_true", help="Pedir token oculto e ID localmente")
    configurar.add_argument("--rsi", action="store_true", help="Usar el harness RSI autenticado en Telegram")
    acceso = configurar.add_mutually_exclusive_group()
    acceso.add_argument("--publico", dest="publico", action="store_const", const=True, default=None,
                        help="Permitir cualquier cuenta por chat privado, con límites por persona")
    acceso.add_argument("--privado", dest="publico", action="store_const", const=False,
                        help="Volver a los usuarios autorizados explícitamente")
    comandos.add_parser("iniciar", help="Supervisar proxy y gateway; consume API")
    comandos.add_parser("gasto", help="Consultar gasto y reservas persistentes")
    experiencia = comandos.add_parser("experiencia", help="Regresiones de conversación: instrumento separado de RSI")
    experiencia.add_argument("--modo", choices=["offline", "real"], default="offline")
    rsi = comandos.add_parser("rsi", help="Mejora recursiva controlada y trazable").add_subparsers(dest="accion", required=True)
    ciclo = rsi.add_parser("ciclo", help="Proponer, evaluar y aceptar sucesores con compuertas")
    ciclo.add_argument("--modo", choices=["simulacion", "real"], default="simulacion")
    ciclo.add_argument("--generaciones", type=int, default=4)
    estado_rsi = rsi.add_parser("estado")
    estado_rsi.add_argument("--modo", choices=["simulacion", "real"], default="real")
    revertir = rsi.add_parser("rollback")
    revertir.add_argument("--modo", choices=["simulacion", "real"], default="real")
    revertir.add_argument("--version", required=True)
    evaluar_rsi = rsi.add_parser("evaluar")
    evaluar_rsi.add_argument("--modo", choices=["simulacion", "real"], default="simulacion")
    evaluar_rsi.add_argument("--particion", choices=["desarrollo", "reservada"], default="desarrollo")
    embudo = rsi.add_parser("embudo", help="Medir clics y montos de una exportación SIMULACION")
    embudo.add_argument("--entrada", type=Path, required=True)
    pagos = comandos.add_parser("pagos").add_subparsers(dest="accion", required=True)
    exportar = pagos.add_parser("exportar")
    exportar.add_argument("--formato", choices=["csv", "json"], required=True)
    exportar.add_argument("--salida", type=Path, required=True)
    evals = comandos.add_parser("evals").add_subparsers(dest="accion", required=True)
    evals.add_parser("validar", help="Validar corpus y contratos sin evaluar un modelo")
    pagos_eval = evals.add_parser("pagos", help="Métricas deterministas del flujo de pagos, sin API")
    pagos_eval.add_argument("--salida", type=Path)
    evaluar = evals.add_parser("ejecutar", help="Conversaciones con API y presupuesto compartido")
    evaluar.add_argument("--particion", choices=["desarrollo", "reservada"], required=True)
    evaluar.add_argument("--salida", type=Path, required=True)
    evaluar.add_argument("--repeticiones", type=int, default=1)
    revisar = evals.add_parser("revisar", help="Incorporar la revisión humana al reporte")
    revisar.add_argument("--reporte", type=Path, required=True)
    revisar.add_argument("--revisiones", type=Path, required=True)
    argumentos = parser.parse_args()
    if argumentos.comando == "mcp":
        servir(sys.stdin, sys.stdout)
    elif argumentos.comando == "demo":
        negocio = Pasteleria(hoy=date(2026, 11, 9))
        datos = {
            "aviso": "SIMULACIÓN determinista. Fecha ficticia: 2026-11-09. No evalúa un modelo.",
            "opciones": negocio.recomendar_pasteles(10, 75000, "chocolate"),
            "cotizacion": negocio.cotizar_pedido(
                "chocolate_12", 10, "2026-11-13", "entrega", "ninguna",
                zona="centro", mensaje="¡Feliz cumpleaños!", presupuesto_centavos=75000,
            ),
        }
        print(json.dumps(datos, ensure_ascii=False, indent=2))
    else:
        try:
            resultado = operar(argumentos)
        except (ValueError, RuntimeError, OSError) as fallo:
            # Los errores de credenciales/proveedor deben sanitizarse en sus módulos.
            print(f"No se pudo completar: {fallo}", file=sys.stderr)
            raise SystemExit(1) from None
        if resultado is not None:
            print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))


def operar(argumentos: argparse.Namespace) -> object:
    from .configuracion import ruta_datos

    if argumentos.comando == "diagnostico":
        from .operacion import diagnostico
        return diagnostico()
    if argumentos.comando == "configurar":
        from .configuracion import guardar_telegram, preparar_perfil, guardar_entorno_perfil
        perfil = preparar_perfil(publico=argumentos.publico)
        if argumentos.rsi:
            guardar_entorno_perfil(perfil, {"PASTELES_RSI": "1"})
        if argumentos.telegram:
            from getpass import getpass
            if not sys.stdin.isatty():
                raise ValueError("Configura Telegram desde una terminal interactiva; no pases secretos por argumentos.")
            print("Crea un bot dedicado con /newbot en https://t.me/BotFather.")
            token = getpass("Token del bot (entrada oculta): ")
            usuario = input("Tu ID numérico de Telegram: ").strip()
            guardar_telegram(perfil, token, usuario)
        return {"perfil": str(perfil), "configurado": True, "iniciar": "./INICIAR.sh"}
    if argumentos.comando == "iniciar":
        from .operacion import iniciar
        raise SystemExit(iniciar())
    if argumentos.comando == "gasto":
        from .presupuesto import Presupuesto
        return Presupuesto.consultar(ruta_datos() / "presupuesto.sqlite3")
    if argumentos.comando == "experiencia":
        from .configuracion import raiz_proyecto
        from .evaluacion_experiencia import evaluar_experiencia
        from .versiones_rsi import cargar_activa
        version = cargar_activa(ruta_datos() / "rsi")
        if argumentos.modo == "real":
            from .llm import ClienteAnthropic
            from .operacion import bloqueo_exclusivo
            import os
            with bloqueo_exclusivo(ruta_datos()):
                reporte = evaluar_experiencia(version, cliente=ClienteAnthropic(
                    ruta_datos(), limite=os.environ.get("PRESUPUESTO_USD", "5.00")),
                    salida=raiz_proyecto() / "resultados/experiencia")
        else:
            reporte = evaluar_experiencia(version, salida=raiz_proyecto() / "resultados/simulacion/experiencia")
        return {k: v for k, v in reporte.items() if k not in {"casos", "trazas"}}
    if argumentos.comando == "rsi":
        if argumentos.accion == "embudo":
            from .ventas import metricas_embudo
            return metricas_embudo(json.loads(argumentos.entrada.read_text(encoding="utf-8")))
        from .configuracion import raiz_proyecto
        from .versiones_rsi import cargar_activa, huella_version, id_activa
        from .orquestador_rsi import ejecutar_ciclo, rollback
        from .evaluacion_rsi import evaluar_version
        from .operacion import bloqueo_exclusivo
        from .llm import ClienteAnthropic
        import os

        real = argumentos.modo == "real"
        directorio = ruta_datos() / ("rsi" if real else "rsi-simulacion")
        salida = raiz_proyecto() / ("resultados/rsi" if real else "resultados/simulacion/rsi")
        if argumentos.accion == "estado":
            version = cargar_activa(directorio)
            return {"modo": argumentos.modo, "id": id_activa(directorio), "contenido_sha256": huella_version(version), "harness": version['harness'],
                    "directorio": str(directorio)}
        with bloqueo_exclusivo(ruta_datos()):
            if argumentos.accion == "rollback":
                return rollback(directorio, argumentos.version)
            cliente = ClienteAnthropic(ruta_datos(), limite=os.environ.get("PRESUPUESTO_USD", "5.00")) if real else None
            if argumentos.accion == "ciclo":
                return ejecutar_ciclo(directorio, salida, cliente=cliente, generaciones=argumentos.generaciones)
            return evaluar_version(cargar_activa(directorio), cliente=cliente, salida=salida,
                                   particion=argumentos.particion)
    if argumentos.comando == "pagos":
        from .pagos import AlmacenPagos
        cantidad = AlmacenPagos(ruta_datos() / "pagos.sqlite3").exportar(
            argumentos.formato, argumentos.salida)
        return {"registros": cantidad, "archivo": str(argumentos.salida), "simulacion": True}
    if argumentos.comando == "evals":
        from .evaluacion import validar_corpus, completar_revision, evaluar_pagos_offline
        from .evaluar_modelo import ejecutar_evaluacion
        if argumentos.accion == "validar":
            return validar_corpus()
        if argumentos.accion == "pagos":
            return evaluar_pagos_offline(argumentos.salida)
        if argumentos.accion == "revisar":
            return completar_revision(argumentos.reporte, argumentos.revisiones)
        if argumentos.repeticiones < 1:
            raise ValueError("repeticiones debe ser al menos 1.")
        import os
        from .llm import ClienteAnthropic
        from .operacion import bloqueo_exclusivo
        with bloqueo_exclusivo(ruta_datos()):
            cliente = ClienteAnthropic(ruta_datos(), limite=os.environ.get("PRESUPUESTO_USD", "5.00"))
            return ejecutar_evaluacion(cliente, argumentos.particion, argumentos.salida,
                                      repeticiones=argumentos.repeticiones)
    raise ValueError("Comando desconocido.")


if __name__ == "__main__":
    principal()
