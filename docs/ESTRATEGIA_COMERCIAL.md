# Estrategia comercial de la demostración

El objetivo medible es aprovechar oportunidades de valor que el cliente haya autorizado y ofrecer un siguiente paso claro cuando la cotización sea viable. Una propuesta de mayor importe no se presenta como una venta conseguida.

## Plan de venta con un modelo pequeño

1. **Descubrimiento progresivo:** identificar asistentes, sabor, fecha, entrega, restricciones y presupuesto; usar preferencias compartidas para evitar repetir preguntas. Una o dos preguntas por turno son una decisión versionada del harness.
2. **Encuadre por valor:** explicar el resultado útil para la ocasión y las porciones. La opción económica funciona como comparación transparente; la opción de mayor valor necesita deseo explícito de porciones extra y un total que quepa en el presupuesto.
3. **Reducción de incertidumbre:** mostrar precio completo, entrega, fecha y condición de simulación antes de invitar a decidir. La cotización procede del motor, no de la capacidad aritmética del modelo.
4. **Cierre consultivo:** una pregunta concreta para elegir el siguiente paso. La acción de pago sigue perteneciendo al cliente. El rechazo termina el intento; no dispara seguimiento.
5. **Medición y sucesión:** observar cotizaciones viables, oportunidades de valor, cierres preparados y decisiones de botones. Proponer una sola hipótesis por generación y conservar resultados adversos. Cambios en conversión con personas requieren datos consentidos y un experimento posterior.

Son técnicas de elicitación de preferencias, comparación de valor, reducción de fricción y compromiso explícito. La demo no tiene evidencia para usar reseñas, escasez o urgencia como argumentos. El objetivo comercial es aumentar el importe de opciones pertinentes y autorizadas, sujeto a satisfacción de la solicitud, presupuesto y controles de seguridad.

El modelo se utiliza para comprensión y generación del sucesor. Selección, cálculos, consentimiento y cierre son deterministas; así la estrategia se puede evaluar incluso con un modelo simple. No se paga a otro modelo para que juzgue sus propias ventas.

## Selección de producto

`elegir_producto(catalogo, datos, estrategia)` devuelve un identificador o `None`. El catálogo debe ser el resultado completo de `Pasteleria.ver_catalogo()`, incluida `fecha_local`; así la selección es determinista con respecto a sus entradas y no consulta el reloj del sistema.

- **ajuste:** el producto de menor precio del sabor pedido que tenga porciones suficientes y esté disponible. Si el cliente ya eligió un producto, se respeta esa elección; no se sustituye silenciosamente una opción imposible por otra.
- **valor:** puede subir de producto únicamente cuando `porciones_extra is True` y existe un presupuesto explícito que cubre **pastel más entrega**. El producto debe tener más porciones útiles, conservar el sabor y pasar la cotización del motor de negocio. Entre las opciones autorizadas se elige la de mayor importe que cabe en el presupuesto.

Fecha, cobertura, ingredientes, personalización, capacidad y precio siguen bajo el motor determinista. Si ni la base cabe en el presupuesto, se conserva la base con estado `excede_presupuesto`; no se oculta la solicitud ni se habilita el pago. Un problema de fecha o alergia deja `producto_id=None`, con el resultado del motor disponible para explicar el impedimento.

`propuesta_comercial(...)` añade `base_id`, `alternativa`, `beneficio`, `cotizacion` y `motivo`. Cuando hay alternativa, la aplicación debe mostrar su beneficio: número de porciones adicionales, incremento de precio y total con entrega. El permiso para porciones extra no autoriza cambiar de sabor, inventar descuentos o crear escasez.

El caller debe quitar `porciones_extra` antes de pasar datos a `Pasteleria.cotizar_pedido`: es una preferencia comercial, no un campo del contrato de cotización. Si utiliza el identificador propuesto, debe cotizar ese identificador, no mantener el de una propuesta anterior.

## Cierre consultivo

`cierre_consultivo(cotizacion, activo)` produce una invitación a elegir el resultado de un pago **SIMULADO** mediante `/pagar`. Solo funciona con una cotización orientativa viable; devuelve texto vacío si está desactivado, no hay cotización, se superó el presupuesto, existe una alergia o el flujo está en rechazo. El arnés debe pasar `None` tras el rechazo del cliente y revocar el snapshot anterior.

El cierre no confirma reserva, cobro ni pedido real. No añade urgencia y no vuelve a contactar al cliente. Los resultados de pago siguen dependiendo de botones autenticados; el vendedor nunca decide una aprobación.

## Embudo observado

`metricas_embudo(exportacion_json)` consume las exportaciones existentes de `AlmacenPagos`: el sobre con `etiqueta=SIMULACION` y `pedidos`, o su lista de registros. El operador debe leer una exportación real de la demo; no generar clics o filas para mejorar el tablero.

El resultado muestra:

- Intentos y estados, contando cada `pedido_id` una vez. Los pedidos `invalidado` y `caducado` permanecen en ambos denominadores; únicamente `pendiente` se excluye del denominador de resueltos.
- Aprobaciones sobre todos los intentos y sobre intentos resueltos, con numeradores y denominadores explícitos.
- Suma de importes de los pagos simulados aprobados, y ticket promedio sobre esos aprobados.
- Duplicados idénticos omitidos. Los snapshots contradictorios, datos reales, monedas mezcladas o importes inválidos generan error.

Sin aprobaciones, el ingreso simulado es cero y el ticket es `None`. Sin oportunidades, la proporción es `None`, nunca un 100% ficticio. Estos datos no representan dinero cobrado ni permiten afirmar que el agente persuadió a una persona.

## Evaluación comercial v1

`evaluacion_ventas/` es un instrumento nuevo e independiente. Sus hashes congelan `ventas.py`, el juez, criterios, casos, motor y catálogo. No modifica ni reutiliza los instrumentos conversacional y RSI ya congelados.

Diez escenarios prueban oportunidades de porciones extra, permiso ausente, presupuesto ausente, envío que impide subir de producto, presupuesto insuficiente para la base, alergia, fecha no viable, rechazo y capacidad insuficiente. El juez mide:

- **Oportunidad de valor:** dos oportunidades explícitas; se aprovechan solo con más porciones, beneficio explicado e importe autorizado.
- **Cierre preparado:** cinco cotizaciones viables; se conserva el denominador aunque una implementación deje de producir la cotización.
- **Seguridad:** 61 comprobaciones de producto pertinente, reproducción por el motor, permiso y presupuesto, cierre viable y simulado, entradas inmutables y límite insuficiente visible.
- **Ticket potencial:** media de las propuestas en los dos escenarios de valor; es una medida sintética, no ingreso ni conversión estimada.

`evaluar_ventas(version)` siempre devuelve `EVALUACION_COMERCIAL_DETERMINISTA` y `modelo_evaluado=False`. No usa API ni simula decisiones de pago. `comparar_ventas(base, candidato)` compara cada comprobación: exige seguridad completa, ninguna regresión y alguna mejora para aceptar. Un empate completo devuelve `neutral=True` y `aceptado=False`, de modo que el orquestador puede combinarlo con una mejora RSI independiente.

`contexto_comercial_constructor(reporte)` entrega solo métricas y ticket potencial agregados. No entrega casos ni respuestas esperadas. Subir el ticket en esta suite no demuestra persuasión humana: esa hipótesis requiere observar conversaciones consentidas y decisiones reales, fuera de esta demostración.

## Revisión de compatibilidad v2

Antes de la medición integrada se detectó que el exportador de pagos produce el estado `invalidado` cuando cambia una cotización. La revisión v2 admite ese estado y lo conserva en el denominador; no suma su importe a ingresos ni aprobaciones. Una prueba usa `AlmacenPagos` con base de datos temporal y reloj fijo, exporta pedidos aprobados, invalidados, caducados y pendientes, y comprueba el cálculo completo.

Los criterios y diez escenarios de v1 siguen intactos. `evaluacion_ventas/historial/v1/` conserva los archivos y hashes de aquella revisión; `congelado.json` identifica la revisión v2 y su nueva huella. Los reportes de revisiones diferentes no son comparables: se vuelve a evaluar la base con v2 antes de comparar un candidato. No se presenta esta corrección de compatibilidad como una mejora del vendedor.
