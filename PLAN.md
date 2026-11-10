# Plan aprobado

0. Separar la base en repositorio independiente y verificar las 43 pruebas existentes.
1. Implementar frontera Anthropic y proxy local con cuenta persistente de 5 USD.
2. Implementar plugin Hermes, cotizaciones vinculadas a sesión, pagos simulados idempotentes y exportación CSV/JSON.
3. Implementar evals de conversaciones medibles, corpus de desarrollo y corpus reservado, criterios congelados, reportes con numeradores/denominadores, costo y latencia; distinguir offline de evaluación real.
4. Integrar configuración de perfil, supervisión, diagnóstico y documentación. Validar Hermes/MCP/plugin sin API y después Telegram cuando el equipo configure sus credenciales locales.

Aceptación: pruebas completas verdes, humo offline verde, herramientas efectivas limitadas a las tres de Pasteles, gasto protegido incluso ante reinicios/fallos/concurrencia, pagos sin cobros reales, reportes verificables sin resultados de modelo inventados. No activar si faltan credenciales.

## Ampliación solicitada: RSI del hackatón

5. Harness compartido con estado explícito, versiones declarativas, contexto frecuente consentido y ontología cliente/vendedor. Aceptación: recotización y aislamiento verificados sin API, roles y permisos no controlados por texto.
6. Orquestador recursivo y nuevos instrumentos separados. Aceptación: herencia de harness/skills/constructor, compuertas sin regresiones, publicación consistente, rechazo y rollback; no modificar los instrumentos anteriores ni usar reserva para construir.
7. Integración privada, estrategia de cierre y demostración medible. Aceptación: transporte falla cerrado, contexto se comparte explícitamente, total e invitación de pago derivan del negocio, resultados offline y reales diferenciados, presupuesto acumulado conservado.
8. Observatorio local y explicación del proyecto. Aceptación: dashboard de lectura con reportes dinámicos, separación de modelo real/simulación/reserva, denominadores y compuertas explicados, historial negativo conservado, comprobación en navegador y documento LaTeX compilado. Sin dependencias adicionales ni gasto de API para visualizar.
9. Corregir los fallos de experiencia observados en Telegram. Aceptación: respuestas breves vinculadas a la pregunta pendiente, rechazo explícito conservado, aviso temprano de falta de disponibilidad y consulta de pago con cotización vigente; regresiones públicas en un instrumento separado, evidencia offline/real distinguida y panel consciente de la revisión del código. Esta es una corrección de ingeniería del harness; no se atribuye al constructor RSI ni se alteran sus resultados históricos.

Detalles y seguimiento: `tasks/plan.md`, `tasks/todo.md`. La versión solo puede evolucionar dentro del contrato; no modifica pesos, juez, permisos o presupuesto.
