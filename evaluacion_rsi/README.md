# Instrumento RSI v1

Instrumento independiente de `evaluacion/`: no modifica ni utiliza el corpus anterior.

- 12 casos de desarrollo y 36 reservados sintéticos con combinaciones diferentes.
- Oráculo fuera del candidato: `Pasteleria` con reloj fijo 2026-11-09, más invariantes de sesión y trazas.
- Congelación SHA-256 de juez, criterios, corpus, negocio, catálogo y contratos. Verificar antes y después de cada evaluación.
- El arnés solo recibe texto, extracción de prueba y preferencias; nunca el objetivo o la respuesta esperada.
- El constructor solo recibe `contexto_constructor(reporte)` para desarrollo. Esa función rechaza reservado y elimina ids, texto y objetivos. El orquestador debe mantener el corpus y el juez fuera de su espacio de trabajo.

## Evidencia

`evaluar_version(version)` inyecta extracciones guionizadas, algunas con una señal `cotizar` insuficiente o datos maliciosos. **Mide política y fronteras deterministas; no resistencia lingüística del modelo.**

`evaluar_version(version, cliente=cliente)` usa los mensajes originales sin inyección. Solo un cliente con `es_real=True` produce la etiqueta de evaluación del modelo. Clientes falsos tienen su propia etiqueta y no se comparan con resultados reales.

Los controles de seguridad tienen oportunidades explícitas en todos los turnos: estructura, revisión, reproducción por negocio, cotización fresca, coherencia del pago y ausencia de cobro real. Los casos adversarios añaden controles de rechazo, identidad y aislamiento. No hay seguridad aprobada por un denominador cero. Errores detienen nuevas llamadas y conservan todos los turnos previstos en los denominadores.

## Aceptación

`decidir(baseline, candidato)` exige mismo modo, partición, instrumento, configuración y pares; ejecución completa y presupuesto/latencia dentro de límites; seguridad completa; ninguna comprobación previamente correcta puede fallar; debe mejorar al menos una comprobación funcional. `victorias`, `derrotas` y `empates` cuentan **comprobaciones pareadas**, no chats. También reporta casos mejorados y casos con regresión.

Esto demuestra una mejora empírica en un instrumento sintético. No demuestra modificación de pesos, superioridad estadística ni ventas. La suite reservada no debe usarse para iterar candidatos: una inspección de sus errores contamina esa reserva.

## Interfaces

```python
from pasteles.evaluacion_rsi import evaluar_version, decidir, contexto_constructor

baseline = evaluar_version(version_base, salida=directorio)
candidato = evaluar_version(version_nueva, salida=directorio)
decision = decidir(baseline, candidato)
contexto = contexto_constructor(baseline)
```

Reportes incluyen `version_id`, `suite_sha256`, `tipo`, `casos`, `metricas`, `completitud`, `operacion` y `fallos_agregados`. Con `salida` se crean directorios nuevos y trazas; no se sobrescriben resultados. Para llamadas reales el orquestador debe sostener el mismo bloqueo de operación que el bot y reutilizar la cuenta de gasto, de modo que los deltas por caso no mezclen tráfico concurrente.
