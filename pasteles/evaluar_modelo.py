"""Arnés de conversación contra la frontera LLM; no reemplaza las pruebas del gateway."""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .evaluacion import (RAIZ, agregar_metricas, cargar_casos, evaluar_traza, huella,
                         plantilla_revision, validar_corpus)
from .herramientas import HERRAMIENTAS, ejecutar
from .negocio import Pasteleria


class ClienteEvaluable(Protocol):
    def completar(self, solicitud: dict[str, Any]) -> dict[str, Any]: ...


def _escribir_nuevo(ruta: Path, dato: Any) -> None:
    with ruta.open('x', encoding='utf-8') as salida:
        json.dump(dato, salida, ensure_ascii=False, indent=2)
        salida.write('\n')


def _cuenta(cliente: ClienteEvaluable) -> dict[str, Decimal]:
    presupuesto = getattr(cliente, 'presupuesto', None)
    if presupuesto is None:
        return {'gastado': Decimal('0'), 'reservado': Decimal('0')}
    return {k: Decimal(str(v)) for k, v in presupuesto.resumen().items()
            if k in {'gastado', 'reservado'}}


def _percentil(valores: list[float], proporcion: float) -> float | None:
    return sorted(valores)[max(0, math.ceil(len(valores)*proporcion)-1)] if valores else None


def ejecutar_evaluacion(cliente: ClienteEvaluable, particion: str, salida: Path,
                        repeticiones: int = 1, *, raiz: Path | None = None) -> dict[str, Any]:
    """Escribe una corrida nueva y conserva casos interrumpidos en los denominadores.

    Solo un cliente con es_real=True produce la etiqueta EVALUACION_MODELO. La
    frontera LLM fija False cuando recibe un SDK inyectado o un cliente falso.
    """
    if type(repeticiones) is not int or not 1 <= repeticiones <= 3:
        raise ValueError('Repeticiones debe ser un entero de 1 a 3 dentro del presupuesto compartido.')
    base = raiz or RAIZ
    validacion = validar_corpus(base)
    casos = cargar_casos(particion, base)
    criterios = json.loads((base / 'evaluacion/criterios.json').read_text())
    prompt = (base / 'prompts/vendedor.md').read_text(encoding='utf-8')
    # Set by the LLM boundary, never read from model response metadata.
    real = getattr(cliente, 'es_real', False) is True
    tipo = 'EVALUACION_MODELO' if real else 'PRUEBA_ARNES'
    ahora = datetime.now(timezone.utc)
    carpeta = Path(salida) / (ahora.strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:12])
    carpeta.mkdir(parents=True, exist_ok=False, mode=0o700)
    identidad = {'tipo': tipo, 'particion': particion, 'creado_en': ahora.isoformat(),
                 'modelo': criterios['modelo'], 'prompt_sha256': huella(prompt.encode()),
                 'corpus_y_criterios': validacion['huellas'], 'fecha_local': criterios['fecha_local'],
                 'repeticiones': repeticiones, 'max_tokens': criterios['max_tokens_salida'],
                 'max_iteraciones_por_turno': criterios['max_iteraciones_por_turno']}
    _escribir_nuevo(carpeta / 'identidad.json', identidad)
    herramientas = [{'name': h['name'], 'description': h['description'], 'input_schema': h['inputSchema']}
                    for h in HERRAMIENTAS]
    negocio = Pasteleria(hoy=date.fromisoformat(criterios['fecha_local']))
    cuenta_inicio = _cuenta(cliente)
    resultados, conversaciones = [], []
    interrumpida = False
    causa = None
    for repeticion in range(1, repeticiones + 1):
        for caso in casos:
            traza: list[dict[str, Any]] = []
            ruta_traza = carpeta / f'{caso["id"]}-{repeticion}.jsonl'
            cuenta_antes = _cuenta(cliente)
            inicio = time.monotonic()
            intentada = not interrumpida
            mensajes: list[dict[str, Any]] = []

            def anotar(evento: dict[str, Any]) -> None:
                traza.append(evento)
                with ruta_traza.open('a', encoding='utf-8') as archivo:
                    archivo.write(json.dumps(evento, ensure_ascii=False) + '\n')

            if interrumpida:
                anotar({'tipo': 'no_ejecutado', 'motivo': causa})
            else:
                for turno, texto in enumerate(caso['turnos_cliente'], 1):
                    mensajes.append({'role': 'user', 'content': texto})
                    anotar({'tipo': 'usuario', 'turno': turno, 'texto': texto})
                    final = False
                    for iteracion in range(1, criterios['max_iteraciones_por_turno'] + 1):
                        solicitud = {'model': criterios['modelo'], 'max_tokens': criterios['max_tokens_salida'],
                                     'system': prompt, 'messages': mensajes, 'tools': herramientas,
                                     'stream': False}
                        desde = time.monotonic()
                        try:
                            respuesta = cliente.completar(solicitud)
                        except Exception as fallo:
                            # Never include provider exception text, requests or credentials.
                            causa = type(fallo).__name__
                            interrumpida = True
                            anotar({'tipo': 'fallo', 'turno': turno, 'clase': causa})
                            break
                        anotar({'tipo': 'llamada', 'turno': turno, 'iteracion': iteracion,
                                'latencia_segundos': time.monotonic()-desde,
                                'usage': respuesta.get('usage', {}),
                                'stop_reason': respuesta.get('stop_reason')})
                        contenido = respuesta.get('content')
                        if not isinstance(contenido, list) or not contenido or not all(isinstance(b, dict) for b in contenido):
                            causa, interrumpida = 'RespuestaInvalida', True
                            anotar({'tipo': 'fallo', 'turno': turno, 'clase': causa})
                            break
                        mensajes.append({'role': 'assistant', 'content': contenido})
                        llamadas = [b for b in contenido if b.get('type') == 'tool_use']
                        texto_asistente = '\n'.join(b.get('text', '') for b in contenido if b.get('type') == 'text')
                        final = not llamadas and respuesta.get('stop_reason') == 'end_turn' and bool(texto_asistente.strip())
                        anotar({'tipo': 'asistente', 'turno': turno, 'texto': texto_asistente, 'final': final})
                        if not llamadas:
                            if not final:
                                anotar({'tipo': 'fallo', 'turno': turno, 'clase': 'RespuestaTruncadaOVacia'})
                            break
                        respuestas_herramientas = []
                        for llamada in llamadas:
                            nombre, argumentos = llamada.get('name', ''), llamada.get('input')
                            try:
                                resultado = ejecutar(negocio, nombre.removeprefix('mcp__pasteles__'), argumentos)
                                error = False
                            except (ValueError, TypeError):
                                resultado, error = {'error': 'Argumentos o herramienta no válidos.'}, True
                            anotar({'tipo': 'herramienta', 'turno': turno, 'nombre': nombre,
                                    'argumentos': argumentos, 'resultado': resultado, 'error': error})
                            respuestas_herramientas.append({'type': 'tool_result', 'tool_use_id': llamada.get('id', ''),
                                                           'content': json.dumps(resultado, ensure_ascii=False), 'is_error': error})
                        mensajes.append({'role': 'user', 'content': respuestas_herramientas})
                    if not final and not interrumpida:
                        anotar({'tipo': 'fallo', 'turno': turno, 'clase': 'TurnoSinCompletar'})
                    if interrumpida:
                        break
            cuenta_despues = _cuenta(cliente)
            costo = cuenta_despues['gastado']-cuenta_antes['gastado']
            reserva = cuenta_despues['reservado']-cuenta_antes['reservado']
            evaluada = evaluar_traza(caso, traza, fecha_local=criterios['fecha_local'])
            evaluada['repeticion'] = repeticion
            resultados.append(evaluada)
            conversaciones.append({'caso_id': caso['id'], 'repeticion': repeticion, 'intentada': intentada,
                                   'completa': all(evaluada['muestras']['conversaciones_completas']),
                                   'latencia_segundos': time.monotonic()-inicio if intentada else None,
                                   'costo_usd': str(costo) if intentada else None,
                                   'reserva_pendiente_delta_usd': str(reserva) if intentada else None,
                                   'traza': ruta_traza.name, 'fallos': evaluada['fallos']})
    metricas = agregar_metricas(resultados, criterios)
    completas = [c for c in conversaciones if c['completa']]
    latencias = [c['latencia_segundos'] for c in completas]
    costo_maximo = max((Decimal(c['costo_usd']) for c in conversaciones if c['intentada']), default=None)
    cuenta_final = _cuenta(cliente)
    p95 = _percentil(latencias, .95)
    plantilla = plantilla_revision(casos, repeticiones, criterios)
    costo_cumple = costo_maximo <= Decimal(criterios['costo_maximo_conversacion_usd']) if real and costo_maximo is not None else None
    latencia_cumple = p95 <= criterios['latencia_p95_conversacion_segundos'] if real and p95 is not None else None
    falla_automatica = any(m['cumple'] is False for m in metricas.values()) or costo_cumple is False or latencia_cumple is False
    reporte = {**identidad, 'calidad_modelo_medida': real, 'carpeta': str(carpeta),
               'estado': 'INCOMPLETA' if interrumpida else 'NO_CUMPLE_AUTOMATICA' if
               falla_automatica else 'PENDIENTE_REVISION_HUMANA',
               'causa_interrupcion': causa, 'conversaciones_previstas': len(conversaciones),
               'conversaciones_intentadas': sum(c['intentada'] for c in conversaciones),
               'conversaciones_completas': len(completas), 'metricas_automaticas': metricas,
               'costo_cargado_usd': str(cuenta_final['gastado']-cuenta_inicio['gastado']),
               'reserva_pendiente_delta_usd': str(cuenta_final['reservado']-cuenta_inicio['reservado']),
               'costo_maximo_conversacion_usd': str(costo_maximo) if costo_maximo is not None else None,
               'costo_cumple': costo_cumple,
               'latencia': {'conversaciones_medidas': len(latencias), 'p50_segundos': _percentil(latencias, .5),
                            'p95_segundos': p95, 'cumple': latencia_cumple},
               'revision_humana_esperada': plantilla, 'criterios': criterios, 'conversaciones': conversaciones,
               'limitaciones': ['El arnés evalúa prompt, modelo y herramientas; no ejecuta Hermes ni Telegram.',
                                'Las trazas no certifican la veracidad del texto: hace falta revisión humana.',
                                'Los intervalos son descriptivos; las repeticiones no son conversaciones independientes.',
                                'Un resultado aprobado simulado no demuestra una venta real.']}
    _escribir_nuevo(carpeta / 'revision_humana.json', plantilla)
    _escribir_nuevo(carpeta / 'reporte.json', reporte)
    lineas = [f'# {tipo}: {particion}', '', f'Estado: **{reporte["estado"]}**.',
              f'Conversaciones completas: {len(completas)}/{len(conversaciones)}.',
              f'Cargo medido: {reporte["costo_cargado_usd"]} USD; reserva pendiente: {reporte["reserva_pendiente_delta_usd"]} USD.',
              '', '| Métrica automática | Aciertos / oportunidades | Cumple |', '| --- | --- | --- |']
    lineas.extend(f'| {n} | {m["numerador"]}/{m["denominador"]} | {m["cumple"] if m["cumple"] is not None else "N/A"} |' for n,m in metricas.items())
    lineas += ['', 'Revisión humana pendiente: completar una copia de `revision_humana.json`, con evidencia y revisor.',
               'Este reporte no acredita calidad en Telegram ni ventas reales.', '', '## Fallos']
    lineas.extend(f'- {c["caso_id"]} / repetición {c["repeticion"]}: {f["metrica"]}, turno {f["turno"]}: {f["detalle"]}' for c in conversaciones for f in c['fallos'])
    with (carpeta / 'reporte.md').open('x', encoding='utf-8') as archivo:
        archivo.write('\n'.join(lineas)+'\n')
    return reporte
