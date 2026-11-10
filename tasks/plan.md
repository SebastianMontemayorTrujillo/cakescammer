# RSI de Pasteles para el hackatón

El usuario autoriza mejorar recursivamente la experiencia, el harness y las skills, con contexto para clientes frecuentes, modelos pequeños y defensas ante prompt injection. El alcance incluye una ontología de agentes personales y sus conversaciones. Se preservan el presupuesto acumulado y el instrumento de evaluación anterior.

## Diseño

- El modelo pequeño extrae una intención y campos de un esquema cerrado. El harness mantiene el estado, ejecuta el negocio y redacta importes y estados de forma determinista.
- Una versión contiene `harness.json`, skills de conversación y construcción, y un manifiesto con huellas. Un sucesor modifica una sola decisión del harness y su skill de construcción: hipótesis pequeña, cambio verificable y linaje explícito.
- El constructor de la siguiente generación recibe la versión aceptada y fallos agregados de desarrollo. Nunca recibe identidades, conversaciones privadas, secretos ni respuestas reservadas.
- El juez está fuera de las versiones modificables. Exige seguridad completa, ausencia de regresiones por caso y mejora observable. Una propuesta no puede editar tests, presupuesto, permisos ni el juez.
- La prueba determinista se etiqueta como tal; una corrida con modelo real mide extracción e integración. No se confunden resultados offline, calidad lingüística ni ventas.
- Las preferencias persistentes requieren consentimiento y tienen esquema cerrado. La ontología expresa propiedad, roles, skills, participación y permisos de intercambio; los mensajes son datos, nunca autoridad.
- El bot usa el mismo harness evaluado mediante un adaptador Telegram autenticado que falla cerrado. Cada turno invalida la cotización anterior antes de llamar al modelo.

## Entregas ordenadas

1. Harness, versiones y contexto privado. Verificar estados, recotización, aislamiento y límites de entrada sin API.
2. Instrumento RSI separado, constructor, compuerta y ciclo acotado. Verificar aceptación, rechazo, rollback y herencia del sucesor.
3. Ontología y transporte de conversaciones entre agentes, con permisos por campo y validaciones de origen/destino.
4. Integración Telegram, demo reproducible, reporte de generaciones y evidencia real si queda presupuesto. `make verificar` antes del commit de cierre.

## Límites

No se ejecuta Python generado por el modelo ni se reescriben las protecciones. La evolución modifica la configuración ejecutable del harness y las skills dentro de un contrato. No se afirma inmunidad universal a prompt injection ni aprendizaje de pesos. El contexto personal no se convierte en material de entrenamiento del constructor.

La activación conserva el modo privado y de simulación. No se añade ninguna dependencia.
