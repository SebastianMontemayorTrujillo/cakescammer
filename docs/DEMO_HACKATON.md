# Demo RSI: un vendedor que mejora el sistema que lo construye

## Historia para presentar

Un cliente tiene un agente personal que conserva sus preferencias. El agente vendedor recibe únicamente las preferencias que el cliente decide compartir. La conversación se ejecuta con un modelo pequeño y un harness determinista. Cuando la evaluación descubre una falla, el constructor propone un nuevo harness y actualiza su propia skill. Un juez independiente acepta o rechaza al sucesor; el sucesor aceptado construye la próxima generación.

La tesis es mejora recursiva del sistema: política, contexto autorizado y procedimiento de construcción evolucionan con evidencia. No se afirma reentrenamiento del modelo ni autonomía ilimitada.

## Recorrido de cinco minutos

1. Abrir `docs/ONTOLOGIA.md`: mostrar cliente, agente personal, vendedor y concesión por campo. Explicar que guardar no es compartir.
2. Mostrar una conversación privada: `/recordar sabor=chocolate modalidad=recoger`, después `/compartir sabor modalidad`, y pedir un pastel indicando asistentes, fecha y restricciones. `/new` revoca la concesión.
3. Mostrar el reporte de la simulación reproducible: cuatro hipótesis aceptadas y una quinta rechazada por empate. Abrir los `harness.json` y ambas `SKILL.md` de dos generaciones consecutivas; el manifiesto de la segunda apunta a la primera.
4. Mostrar por separado la evidencia real: Claude propone un sucesor usando agregados y el mismo modelo ejecuta las conversaciones de evaluación. Leer la decisión, incluidos fallos o interrupciones. No presentar el constructor de reglas como autonomía del modelo.
5. Intentar cambiar precios, leer otro cliente o aprobar el pago desde texto: los esquemas no conceden esas capacidades. Cambiar la fecha invalida la tarjeta anterior. La decisión de pago procede únicamente del botón autenticado.

## Comandos

```sh
cd /home/seb/pasteles
make verificar
./RSI.sh simulacion 5
./RSI.sh real 4
.venv/bin/python -m pasteles rsi estado --modo real
```

El ciclo real y el bot comparten un bloqueo y el presupuesto acumulado de USD 5. Detener el bot antes de evaluar. Cada ejecución crea un reporte nuevo y conserva las anteriores.

## Evidencia que sí sostiene la demo

La simulación inicial integrada consiguió 13/18 → 18/18 objetivos, 119/119 controles de seguridad, 0/5 → 5/5 cierres preparados y 0/2 → 2/2 oportunidades de valor. El ticket potencial medio en esos dos escenarios pasó de $695 a $995 MXN. Son resultados sintéticos con preferencias y presupuestos definidos, no tasas de conversión ni ingresos.

El primer ciclo real aceptó un sucesor con 6/15 → 13/15 objetivos y 119/119 controles de seguridad, sin regresiones. La propuesta siguiente falló por formato JSON y el sistema conservó al sucesor aceptado. La corrección de formato posterior tiene un único reintento, validación completa y el mismo presupuesto. Los reportes posteriores se conservan por separado.

El siguiente intento real se interrumpió sin publicación. Tras simplificar el contrato a un parche de una decisión, un tercer ciclo pudo evaluar su propuesta y la rechazó por empate. Esto muestra también la compuerta negativa. El sucesor real aceptado se evaluó una vez en reserva: 36/36 conversaciones completas, 38/45 objetivos y 357/357 controles de seguridad. El gasto acumulado al cerrar la medición fue USD 0.0413926. Ver [evidencia y enlaces](VERIFICACION.md).

En Telegram se usa la versión realmente aceptada: recotización automática. Las políticas de preferencias automáticas, cierre consultivo y mayor valor están disponibles en la línea de simulación, pero el ciclo real aún no las promovió. Presentar ambas líneas con sus etiquetas; no mostrar la de simulación como mejora autónoma probada con Claude.

Los denominadores de la prueba determinista y la real difieren: tres oportunidades prueban exclusivamente entradas estructuradas inválidas y no se cuentan como comprensión lingüística. No se comparan porcentajes entre ambos modos como si fueran el mismo experimento.

## Límites que deben quedar visibles

- El catálogo y los pagos son ficticios. El embudo observado se calcula exclusivamente con registros exportados de botones; no se inventan ventas.
- Las comprobaciones de seguridad cubren ataques y fronteras concretas, no toda posible prompt injection.
- Desarrollo sirve para proponer; la reserva se usa para comprobar generalización y nunca vuelve al constructor.
- Una mejora en muestras pequeñas no demuestra superioridad estadística. Calidad de experiencia y persuasión humana requieren observación posterior.
