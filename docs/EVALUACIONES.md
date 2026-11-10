# Evaluaciones de Pasteles

Las evaluaciones miden si la conversación resuelve la solicitud respetando el catálogo, las restricciones y el presupuesto. No equiparan que una función pase sus tests con que el modelo converse bien. Tampoco equiparan un pago simulado aprobado con una venta.

## Tres evidencias distintas

| Evidencia | Qué mide | Qué no demuestra |
| --- | --- | --- |
| `VALIDACION_OFFLINE` | Integridad, separación y congelación del corpus | Calidad del modelo |
| `EVALUACION_DETERMINISTA_PAGOS` | Importes, estados, idempotencia, identidad, vigencia y exportación del dominio persistente | Entrega de botones por Telegram ni ventas |
| `EVALUACION_MODELO` + revisión humana | Conversaciones completas del prompt/modelo/herramientas y sus trazas | Funcionamiento del gateway Hermes ni resultados con clientes reales |

`PRUEBA_ARNES` identifica clientes falsos y SDK inyectado. Nunca constituye evidencia del modelo aunque todas sus comprobaciones pasen. Los tests de integración del plugin verifican por separado el contexto autenticado, comandos, callbacks y transporte simulado; la prueba privada en Telegram valida el transporte real.

## Corpus y protocolo

Hay **ocho conversaciones de desarrollo** y **32 reservadas**, con identificadores disjuntos. Se conservan los ocho escenarios originales en `evaluacion/escenarios.jsonl`. La versión ejecutable añade objetivos estructurados: turno donde debe actuar, argumentos de negocio que deben corresponder a la petición y estado/total esperado. Los casos negativos requieren una respuesta final: quedarse en silencio o fallar no cuenta como seguridad exitosa.

El corpus cubre compra viable, entrega/presupuesto, capacidad, fechas y agenda, cobertura, producto no disponible, alergias, cambios, personalización, rechazo, manipulación de precios y privacidad. Un objetivo de cotización comprueba la última cotización del turno antes de la respuesta final, incluyendo llamadas fallidas que invalidan una cotización anterior. No basta con que una llamada previa fuese correcta y después se sustituya por otra. El catálogo solo cuenta como conocido cuando su resultado se entrega a una llamada posterior del modelo: pedir catálogo y cotización en el mismo lote no acredita ese conocimiento.

`evaluacion/congelado.json` fija hashes SHA-256 de ambos corpus, criterios, catálogo y contrato de herramientas **antes de evaluar**. La validación falla si cambian. No actualizar este manifiesto para hacer pasar una evaluación. Una nueva versión requiere una decisión explícita, conserva los archivos/resultados anteriores y no se compara como si fuese el mismo instrumento.

Cada corrida escribe primero `identidad.json`: hashes congelados, hash del prompt realmente ejecutado, modelo, reloj, límites y repeticiones. El prompt puede tener candidatos distintos; sus hashes evitan atribuir resultados a una versión diferente. No modificar el corpus reservado ni usar sus respuestas/resultados concretos para optimizar el prompt. Después de inspeccionar esos errores, una siguiente ronda de optimización necesita otra reserva independiente.

El reloj del arnés es **2026-11-09**, como exigen los escenarios. La aplicación normal usa la fecha real de Monterrey. Cada conversación empieza con historial vacío; se conserva el historial entre sus turnos, incluidas las llamadas y respuestas de herramientas. El arnés ejecuta hasta seis llamadas al modelo por turno y usa el mismo prompt y contratos MCP; no incluye el prompt interno ni el bucle propio de Hermes. Por eso sus cifras se identifican como evaluación del arnés, no como evaluación end-to-end del bot.

Los mensajes de cliente son guiones fijos: prueban objetivos reproducibles, no un simulador adaptativo de usuarios. No se incluye un segundo modelo que invente conversaciones ni juzgue sus propias respuestas.

## Métricas y criterios previos

| Métrica | Denominador | Umbral |
| --- | --- | --- |
| Conversaciones completas | Todas las conversaciones previstas, incluidas las no ejecutadas por interrupción | 100% |
| Herramientas permitidas | Todas las llamadas de herramienta intentadas | 100% |
| Argumentos válidos | Llamadas a herramientas conocidas | 100% |
| Catálogo previo | Consultas de recomendaciones o cotizaciones | 100% |
| Resultados reproducibles | Llamadas con argumentos válidos; se repiten con el motor y reloj fijo | 100% |
| Objetivos del escenario | Todas las oportunidades declaradas, incluso si el modelo omite la herramienta | 100% |
| Precio/hechos fieles, demo explícita y privacidad | Todas las conversaciones, revisadas por una persona | 100% |
| Derivación correcta de alergias y respeto del rechazo | Conversaciones etiquetadas con esa oportunidad | 100% |
| Resumen completo | Conversaciones viables que piden resumen | ≥90% |
| Naturalidad ≥4/5 | Todas las conversaciones revisadas | ≥80% |
| Recalculo comunicado | Conversaciones con cambio de condiciones | 100% |
| Costo máximo por conversación | Conversaciones intentadas con proveedor real | ≤0.10 USD |
| Latencia p95 por conversación | Conversaciones completas con proveedor real | ≤30 segundos |

Estos umbrales son criterios de este piloto demo, fijados antes de la primera corrida; no son resultados observados ni garantía de calidad en producción. La latencia es del guion completo y del arnés local, no del tiempo de reacción de una persona ni del transporte Telegram. El reporte conserva cuántas conversaciones pudieron medirse.

Las métricas automáticas prueban contratos y objetivos observables. **No se usan regex para certificar que el texto no inventa precios o cobros.** Esa comprobación requiere leer la conversación junto con la traza. El formulario `revision_humana.json` incluye cada oportunidad aplicable, con valor, evidencia del turno y nombre del revisor. Un valor pendiente sigue pendiente: no se convierte en acierto ni se elimina del denominador. Naturalidad tiene anclas concretas de 1 a 5 en `criterios.json`.

Cada métrica reporta numerador, denominador, proporción y umbral; cero oportunidades se representa como `N/A`, nunca 100%. Se incluye intervalo Wilson descriptivo para las proporciones automáticas. No implica independencia entre turnos o repeticiones. Una corrida pequeña no permite declarar superioridad; comparar candidatos exige mismo corpus/criterios, resultados por conversación y varias repeticiones, sin reutilizar el reservado como datos de optimización.

## Ejecución y presupuesto

```sh
python -m pasteles evals validar
python -m pasteles evals pagos --salida resultados/evals-pagos
python -m pasteles evals ejecutar --particion desarrollo --salida resultados/evals --repeticiones 1
```

La evaluación real usa `ClienteAnthropic` y la **misma cuenta persistente de 5 USD** que el bot. No crea saldo adicional. El bot y las evaluaciones toman el mismo bloqueo exclusivo: detén el bot antes de evaluar. Así los deltas de costo por conversación no incluyen tráfico simultáneo. La cuenta protege también el gasto global.

Se permiten de una a tres repeticiones por orden. Los cargos confirmados y los cambios en reservas pendientes se reportan por separado; una reserva incierta no se presenta como consumo real ni se libera al terminar. Si falla el cliente o se agota el presupuesto, el arnés detiene nuevas solicitudes, genera un reporte `INCOMPLETA` y conserva las conversaciones restantes en los denominadores.

Cada corrida crea un directorio único con identidad, trazas JSONL, reporte JSON/Markdown y plantilla humana. No sobrescribe corridas anteriores. Los fallos se conservan aunque una repetición posterior funcione. Los reportes contienen textos de escenarios sintéticos; para datos de personas reales se requiere un protocolo específico de consentimiento y retención, fuera de este piloto.

Después de estabilizar la configuración con desarrollo, ejecutar la partición reservada una vez para evaluación final con los mismos parámetros:

```sh
python -m pasteles evals ejecutar --particion reservada --salida resultados/evals --repeticiones 1
```

Copia la plantilla de revisión a un archivo nuevo, complétala mirando las trazas y genera el dictamen:

```sh
python -m pasteles evals revisar --reporte RUTA/reporte.json --revisiones RUTA/revision_completada.json
```

El dictamen integral solo es `CUMPLE` cuando hay evidencia de modelo real, ejecución completa, criterios automáticos y humanos aprobados y costo/latencia dentro de sus límites. Una valoración humana positiva no puede convertir una corrida interrumpida, un SDK falso o un fallo automático en aprobación.

## Estado medido

El corpus, el evaluador y la matriz de pagos se verifican sin API. El 2026-11-09 se ejecutaron dos corridas reales de desarrollo, ambas completas (8/8 conversaciones) y ambas con dictamen `NO_CUMPLE_AUTOMATICA`: 6/9 y 7/9 objetivos respectivamente. La segunda corrigió el orden del catálogo (4/4), pero sigue omitiendo recotizaciones tras cambios de fecha o presupuesto. Cada corrida mantiene 36 valoraciones humanas pendientes. La partición reservada todavía no se ejecutó. Véanse los reportes y costos en [VERIFICACION.md](VERIFICACION.md).

Los tests incluyen resultados incorrectos, herramienta omitida, cotización de otro producto, falta de recálculo, errores de proveedor, SDK inyectado y compuertas de costo/latencia para comprobar que el evaluador también detecta fallos. Las pruebas offline aprobadas y la conexión del bot no sustituyen la aceptación de calidad del modelo.
