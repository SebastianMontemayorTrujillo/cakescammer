# Verificación de la entrega

Fecha: 2026-11-09. Proyecto independiente; copia original conservada.

- Suite completa: 166 pruebas sin API, incluidas las 43 originales.
- Corpus: 8 conversaciones de desarrollo y 32 reservadas; hashes congelados.
- Plugin Doctor de Hermes real: registro correcto; 0 herramientas nuevas y 3 hooks.
- Integración Hermes real + proveedor falso: cuatro llamadas, exactamente tres herramientas MCP, cotización de 71000 centavos; sin API ni mensajes externos.
- Revisión independiente corrigió falsos aprobados por última cotización y catálogo solicitado en el mismo lote. Los criterios y corpus no se alteraron.
- El perfil quedó restringido: comandos administrativos bloqueados, tool_search desactivado, cuenta persistente y bloqueo compartido entre gateway y evals.
- El extra oficial telegram de Hermes fue instalado con autorización explícita.

## Evaluación determinista de pagos

| Métrica | Aciertos / oportunidades |
| --- | --- |
| identidad_y_boton_validados | 12/12 |
| transiciones_correctas | 3/3 |
| idempotencia | 3/3 |
| importe_fiel | 3/3 |
| etiquetado_simulacion | 3/3 |
| vigencia | 1/1 |
| exportacion_fiel | 5/5 |
| exportacion_sin_identidad | 4/4 |

Estos resultados prueban el dominio de pagos con escenarios controlados. No son mediciones de Claude ni entregas reales de mensajes de Telegram.

## Activación privada observada

El 2026-11-09 se validaron ambas credenciales, se vinculó una única cuenta mediante un mensaje de verificación y Hermes se conectó a Telegram en modo polling. El proxy respondió a `/salud` y el bloqueo exclusivo quedó ocupado por el gateway. El token del bot está en el perfil privado con permisos 0600; la clave de Anthropic permanece únicamente en memoria/entorno del proceso.

Esto verifica el arranque y la conexión, no una conversación completa ni la entrega real de botones. El proceso necesita seguir ejecutándose; para reiniciarlo se usa `/home/seb/pasteles/INICIAR.sh`, que vuelve a pedir la clave sin guardarla.

## Primeras mediciones reales de desarrollo

| Evidencia | Inicial | Prompt revisado |
| --- | --- | --- |
| Conversaciones completas | 8/8 | 8/8 |
| Catálogo antes de consultas | 1/3 | 4/4 |
| Objetivos de escenario | 6/9 | 7/9 |
| Herramientas permitidas / argumentos válidos / resultados reproducibles | 7/7 cada una | 8/8 cada una |
| Costo de la corrida, USD | 0.008835600 | 0.010680400 |
| Latencia p95 de conversación | 8.13 s | 8.59 s |
| Dictamen automático | NO_CUMPLE_AUTOMATICA | NO_CUMPLE_AUTOMATICA |

Reportes conservados: [inicial](../resultados/evals/20261109T223433-fcf7484796b2/reporte.md) y [prompt revisado](../resultados/evals/20261109T223624-42eff26ba4da/reporte.md). Cada corrida tiene sus trazas, huella del prompt y 36 valoraciones humanas pendientes. Corpus, criterios y herramientas mantienen las huellas congeladas. Las oportunidades de catálogo dependen de las llamadas ejecutadas; por eso cambia ese denominador.

La revisión del prompt aclara el orden del catálogo, evita repetir restricciones ya respondidas y pide cotizar/recotizar con los datos disponibles. La segunda corrida todavía falla al cambiar fecha o presupuesto: el modelo responde sin volver a llamar a la herramienta. También se observaron afirmaciones incorrectas en el texto. No se ejecutó la reserva ni se declara calidad aprobada o superioridad estadística a partir de una repetición.

El gasto acumulado al cerrar estas pruebas, incluida una llamada mínima de conectividad, fue 0.019519500 USD de un tope de 5 USD, sin reservas pendientes. Las conversaciones posteriores del bot usan la misma cuenta.

Siguiente trabajo: impedir mecánicamente que `/pagar` conserve una cotización anterior cuando el modelo omite recotizar después de un cambio; verificarlo sin API y volver a evaluar desarrollo. La revisión humana, la evaluación reservada y el flujo completo de botones por Telegram siguen pendientes. La activación actual es una prueba técnica privada del equipo, no un piloto validado para clientes.

## Ampliación RSI — 2026-11-09

La limitación de snapshot descrita arriba quedó cubierta por el nuevo harness: cada mensaje invalida el pago anterior antes de inferir, una extracción inválida borra el estado ambiguo, las ediciones revocan la generación y el callback exige la sesión vigente. Se conserva la evidencia original como historial de aquella implementación.

Suite completa actual: **401 pruebas aprobadas**. Incluye contexto consentido, ontología, inyecciones estructuradas, parentesco de versiones, rechazo, rollback, fallos de publicación, comercio, transporte y protección de pagos. Doctor Hermes y un despacho con `python-telegram-bot` real se verificaron sin red: el handler nativo consume el mensaje y no cae al agente general.

| Evidencia nueva | Resultado | Alcance |
| --- | --- | --- |
| [Ciclo determinista](../resultados/simulacion/rsi/20261109T231432-83a1b09c87/reporte.md) | Cuatro generaciones aceptadas; quinta rechazada | Constructor de reglas, no autonomía del modelo |
| Objetivos deterministas | 13/18 → 18/18; seguridad 119/119 | Política del harness |
| Comercial determinista | Cierre 0/5 → 5/5; valor 0/2 → 2/2; seguridad 61/61 | Oportunidades sintéticas, no ventas |
| Ticket potencial | $695 → $995 MXN, dos escenarios | Presupuesto y porciones extra expresamente definidos |
| [Primer ciclo real](../resultados/rsi/20261109T231515-de256961a1/reporte.md) | Un sucesor aceptado; 6/15 → 13/15; seguridad 119/119 | Propuesta y extracción con Claude |
| [Segundo intento real](../resultados/rsi/20261109T231814-f5b7882632/reporte.md) | Interrumpido, ninguna publicación | Propuesta fuera de validación; resultado negativo conservado |
| [Tercer ciclo real](../resultados/rsi/20261109T232058-d5c7664649/reporte.md) | Candidato evaluado y rechazado por empate | El padre aceptado permanece activo |
| [Reserva RSI real](../resultados/rsi/rsi-20261109T232300-9e9be651d2/reporte.json) | 36/36 conversaciones; 38/45 objetivos; seguridad 357/357 | Validación independiente, no enviada al constructor |

La reserva consumió USD 0.0058074 y tuvo latencia p95 de 3.79 segundos por caso. Gasto acumulado al terminar estas mediciones: **USD 0.0413926 de 5**, sin reservas pendientes. Este total incluye la implementación anterior y todas las llamadas de construcción y evaluación; las conversaciones posteriores siguen consumiendo la misma cuenta.

El sucesor real activo (`b37113db…`) habilita recotización automática. Las mejoras de preferencias automáticas, cierre consultivo y selección comercial de valor están implementadas y demostradas en la línea de simulación; todavía no fueron promovidas por el ciclo real. Telegram conserva archivos de preferencias y concesiones explícitas mediante `/recordar` y `/compartir`, pero su aplicación automática depende de la versión aceptada. No se fuerza una publicación para mejorar la presentación del hackatón.

La reserva mantiene siete objetivos incumplidos. No se ajustó el sistema usando sus casos ni se afirma calidad aprobada para clientes. La revisión de experiencia con personas y la validación completa de botones por una persona permanecen pendientes.

## Panel de evidencia e informe — 2026-11-09

Se añadió `./PANEL.sh` (también `make panel`), un servidor de lectura en loopback
con interfaz para corridas, generaciones, benchmarks, reserva, versión activa y
saldo. No ejecuta evaluaciones ni consume API. Conserva resultados negativos y
no cruza denominadores, modos o particiones para atribuir mejoras. La lectura
agregada identificó tres ciclos reales, una evaluación reservada y un ciclo de
simulación; las cifras históricas anteriores permanecen intactas.

`make verificar`: **433 pruebas aprobadas**. Las 32 pruebas añadidas cubren
proyección de agregados, exclusión de campos privados, evidencia corrupta,
completitud e integridad, comparabilidad, decisiones contradictorias, presupuesto
de lectura, rutas HTTP cerradas, enlaces y origen. No se modificaron los tests
anteriores ni los instrumentos congelados.

La verificación con Chromium aislado comprobó ambas líneas, selección de corrida,
reserva, ticket sintético, rechazo, desplegables, actualización y árbol accesible.
Se revisó la presentación en 320, 768, 1024 y 1440 px, sin desbordamiento de la
página, errores JavaScript ni solicitudes a dominios externos. Se inspeccionaron
capturas de escritorio, móvil y benchmarks. Los enlaces PDF y LaTeX respondieron
HTTP 200. No se añadió una dependencia al proyecto.

El informe `output/pdf/pasteles_rsi.pdf` tiene **nueve páginas A4**. Se compiló con
XeLaTeX en dos pasadas, sin desbordamientos ni caracteres ausentes, y se revisaron
visualmente todas sus páginas. Conserva el corte de evidencia de esta fecha;
la cuenta compartida y el dashboard pueden cambiar con mensajes posteriores.
El documento y la vista no sustituyen los pendientes de revisión humana descritos
en la sección anterior.

## Corrección de experiencia observada en Telegram — 2026-11-09

Una captura del equipo mostró negaciones alimentarias interpretadas como cancelación,
solicitudes coloquiales rechazadas, disponibilidad comprobada demasiado tarde y
consultas de pago fuera del contrato. El extractor recibía el pedido acumulado,
pero no la pregunta anterior. Se reprodujeron las fallas de estado sin API antes
de modificar el código.

El harness conserva ahora preguntas pendientes y la última respuesta acotada;
pregunta restricciones alimentarias por separado, resuelve negaciones mínimas
solo con esa pregunta pendiente y mantiene la cancelación explícita. Consulta el
catálogo antes de pedir más datos de un producto agotado y ofrece alternativas
sin sustituir la elección. La intención de pago explica el flujo y recalcula una
cotización vigente antes de habilitarlo. Identidad, importes, alergias, pagos y
presupuesto siguen bajo los controles del dominio.

Se creó **Experiencia v1**, separado de los instrumentos anteriores, con ocho
conversaciones públicas sintéticas derivadas del incidente y variantes: quince
objetivos y 120 controles. Juez, casos y criterios se congelaron antes de medir.
No constituye reserva independiente. No se usaron errores reservados para diseñar
el cambio ni se modificaron corpus, criterios, jueces o reportes históricos.

| Medición | Código anterior | Código corregido |
| --- | --- | --- |
| JSON preparado, sin API | 11/15 objetivos | 15/15 objetivos |
| Claude real, una repetición | 7/15 objetivos | 15/15 objetivos |
| Controles en ambas modalidades | 120/120 | 120/120 |
| Conversaciones reales completas | 8/8 | 8/8 |
| Costo real de la corrida | USD 0.0014839 | USD 0.0020912 |
| Latencia p95 por conversación | 2.53 s | 2.61 s |

Fuentes reales conservadas: [anterior](../resultados/experiencia/experiencia-20261110T000614-f0a5cb2464/reporte.json)
y [corregido](../resultados/experiencia/experiencia-20261110T000627-b3ecb5f0d7/reporte.json).
Las fechas de carpeta son UTC; ambas corridas ocurrieron el 9 de noviembre, a las
18:06 de Monterrey. Costaron juntas **USD 0.0035751**, con saldo acumulado de
**USD 0.045687 de 5** al cierre y sin reservas pendientes. El bot estuvo detenido
durante la medición; se reinició con los handlers nativos a las 18:07.

Código anterior: `77b82ad056686d33bbcbab396dd15f347d08bf702e25eb922dd61be35ef514f4`.
Código corregido: `d3b3d8f5751dcd5fd1df16ef3d77203cb7b2c54be187839f9114dcc58e02ce5a`.
La versión declarativa RSI permanece igual. Este cambio es una **corrección de
ingeniería del núcleo**, no una propuesta ni promoción autónoma del constructor.

`make verificar`: **495 pruebas aprobadas**. Incluye 31 nuevas regresiones del
diálogo, 14 del nuevo evaluador, 14 de correspondencia de revisión en el panel y
tres de proyección segura de sus agregados. El navegador verificó los dos modos,
7/15 y 15/15 visibles, reserva histórica, filtros, actualización y diseños a
320/768/1024/1440 px sin errores ni solicitudes externas.

El panel ya no atribuye la reserva anterior al núcleo corregido: exige que
coincidan tanto la versión declarativa como el SHA del código. Muestra los nuevos
resultados como desarrollo público. Sigue pendiente la revisión integral con
personas, una reserva independiente para esta revisión y la calidad comercial;
15/15 en estos guiones no certifica naturalidad, generalización ni ventas.

## Informe ampliado con ejemplos — 2026-11-09

El PDF tiene ahora **trece páginas A4**. Incluye cuatro comparaciones de diálogo
antes y después, con extractos de las reproducciones sintéticas evaluadas con
Claude real: negación alimentaria, petición coloquial, disponibilidad y consulta
de pago. Cada ejemplo explica el cambio y cita su evidencia; no se presenta como
una continuación del chat privado. Se añadieron el método de Experiencia v1,
sus cifras y límites, y una guía para interpretar el dashboard. La corrección
manual del núcleo permanece distinguida de las promociones autónomas RSI.

XeLaTeX compiló dos veces con salida correcta y referencias resueltas. Se
inspeccionaron visualmente las trece páginas, sin recortes ni solapamientos;
no hubo desbordamientos ni caracteres ausentes. Los enlaces del panel al PDF y
LaTeX respondieron HTTP 200 y entregaron los mismos archivos finales.
`make verificar`: **495 pruebas aprobadas**. Esta edición documental no hizo
llamadas a la API ni modificó resultados, instrumentos o el agente activo.

## Ronda RSI solicitada tras nuevo bloqueo — 2026-11-09, 18:29

El equipo solicitó una ronda RSI tras mostrar una conversación que quedaba en
revisión alimentaria o de diseño después de indicar una zona. La inspección del
código identifica que esas marcas persisten hasta recibir una corrección
explícita; la captura no revela cuál produjo el extractor. Este episodio no forma
parte del instrumento RSI congelado y no se entregó como instrucción al constructor.

`make humo` pasó, incluidas **495 pruebas** y la validación determinista del dominio.
Con el bot detenido se ejecutó primero una generación de simulación, conservada en
`resultados/simulacion/rsi/20261110T002843-93d8ab24c3/`: terminó sin mejora y sin
publicación. Después se ejecutó **una generación real**, sin reintentos externos,
con la cuenta acumulada existente y sin cambiar el límite de USD 5.

La [corrida real](../resultados/rsi/20261110T002844-c45403a7a9/reporte.json)
quedó **INTERRUMPIDA**. Su evaluación inicial completó **13/15 objetivos** y
**119/119 controles**, con p95 de **2.66 s**. La propuesta incumplió la regla de
cambiar exactamente una decisión del harness; no se admitió un candidato ni se
publicó una versión. El ciclo completo consumió **USD 0.0029905**; el acumulado
quedó en **USD 0.0498153 de 5**, sin reservas pendientes.

Se conservó la versión `b37113dbd620779fcd1e898170e67185f7efc6f8cc7aa814e07edac90b657381`.
Telegram reinició a las 18:29 con los handlers nativos y el dashboard incluyó la
interrupción. No hubo cambios al núcleo, skills activas, instrumentos ni resultados
anteriores. El bloqueo de la captura sigue sin una corrección demostrada; medir su
recuperación exige un nuevo caso público separado de los instrumentos congelados.
