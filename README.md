# Pasteles

Asistente de Telegram por chat privado con Hermes, Claude y catálogo ficticio en MXN.
Cotiza con herramientas deterministas y registra pagos **SIMULADOS** decididos
por botones. Es un proyecto independiente de Río; no cobra ni reserva productos.

## Ver la mejora del agente

Ejecuta `./PANEL.sh` y abre **http://127.0.0.1:8765**. El dashboard muestra
evolución por generación, benchmarks explicados, versión activa, reserva e
historial de rechazos e interrupciones. Se actualiza cada 30 segundos y separa
modelo real de simulación. Leerlo no consume API ni modifica el agente.

Consulta la [guía del panel](docs/PANEL.md), la [explicación en PDF](output/pdf/pasteles_rsi.pdf)
y su [fuente LaTeX](output/pdf/pasteles_rsi.tex).
El PDF incluye cuatro ejemplos de antes y después, la metodología de los evals
y la diferencia entre la mejora RSI y la corrección de experiencia.

La regresión de experiencia derivada de fallos de conversación tiene su propio
[instrumento público](evaluacion_experiencia/README.md):

```sh
.venv/bin/python -m pasteles experiencia --modo offline
# Con el bot detenido y ANTHROPIC_API_KEY en el entorno; usa la cuenta acumulada:
.venv/bin/python -m pasteles experiencia --modo real
```

El panel distingue la revisión del código evaluada y no presenta una reserva
histórica como validación de un harness que cambió después.

## Demo RSI del hackatón

El sistema ya incluye un agente personal por cliente, un vendedor y un ciclo que
propone sucesores del harness y sus skills. El juez permanece fuera del alcance
del constructor. El modelo pequeño extrae datos; el código decide importes,
permisos, contexto compartido y pagos.

```sh
make verificar
./RSI.sh simulacion 5
./RSI.sh real 4
.venv/bin/python -m pasteles configurar --rsi
./INICIAR.sh
```

Detén el bot antes de evaluar. La simulación muestra el mecanismo con un
constructor de reglas; el modo real usa Claude para construir y extraer. Ambos
conservan reportes separados. Solo una mejora evaluada en modo real se publica
en la línea que usa Telegram.

En Telegram, `/recordar sabor=chocolate modalidad=recoger` autoriza guardar
preferencias. `/compartir sabor modalidad` autoriza compartir esos campos con
el vendedor en la conversación actual. `/preferencias` permite consultarlas,
`/olvidar` borrarlas y `/new` revoca la concesión de compartir.

Ver [cómo funciona el RSI](docs/RSI.md), la [ontología de agentes personales](docs/ONTOLOGIA.md),
la [estrategia comercial](docs/ESTRATEGIA_COMERCIAL.md) y la [demo para el hackatón](docs/DEMO_HACKATON.md).

## Preparar

Requiere Python 3.11+, `anthropic`, `pytest` y la instalación existente de Hermes.
El extra oficial `telegram` de Hermes debe estar instalado; en esta máquina
se habilitó con `hermes pm install --extra telegram` con autorización del equipo.

```sh
cd /home/seb/pasteles
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make humo
.venv/bin/python -m pasteles configurar
```

Crear un bot dedicado con `/newbot` en [BotFather](https://t.me/BotFather).
Guardar su token y tu ID numérico exclusivamente desde la terminal local:

```sh
.venv/bin/python -m pasteles configurar --telegram
./INICIAR.sh
```

El token se introduce oculto y se guarda con permisos privados en el perfil
`~/.hermes/profiles/pasteles`. La llave Anthropic se pide oculta al arrancar,
se mantiene solo en memoria y nunca se escribe en archivos. También puede
recibirse de `ANTHROPIC_API_KEY` si tu gestor de secretos la proporciona.
No pases llaves por argumentos ni las copies en conversaciones.

En modo restringido, el bot responde únicamente a tu ID en un chat privado. Mantén abierta la
terminal mientras lo usas; **Ctrl+C** detiene gateway y proxy. No se instala
un servicio de arranque automático. El proxy solo escucha en `127.0.0.1:8787`.

### Acceso público por chat privado

Con el bot detenido, habilita cualquier cuenta y vuelve a iniciarlo:

```sh
.venv/bin/python -m pasteles configurar --publico
./INICIAR.sh
```

Comparte https://t.me/JaimitoEVbot para que cada persona pulse «Iniciar».
El modo público fuerza el consumidor nativo RSI, conserva grupos deshabilitados
y mantiene pedidos, botones y preferencias separados por identidad de Telegram.
Cada persona dispone de **12 consultas al modelo por minuto y 100 en 24 horas**,
con ventanas móviles persistentes: ni `/new` ni reiniciar el bot restablecen la
cuota. Los comandos y botones no consumen esa cuota. Todos comparten el tope
acumulado de **USD 5**. Catálogo y pagos siguen siendo simulados.

Para volver a la lista autorizada: detén el bot, ejecuta
`.venv/bin/python -m pasteles configurar --privado` y reinícialo. La configuración
conserva el ID previamente autorizado y las credenciales existentes.

El perfil usa `gateway.standalone`, disponible como compatibilidad en la versión
instalada de Hermes, para que el proceso atienda solo este bot. Después de
actualizar Hermes vuelve a ejecutar `make verificar-hermes` antes de activarlo.

## Probar una compra simulada

1. Abre el bot y pide chocolate para 10 personas, dentro de cuatro días,
   entrega en centro, presupuesto de $750 y sin restricciones alimentarias.
2. Revisa la cotización: $650 de pastel + $60 de entrega = $710 MXN.
3. Escribe `/pagar` y elige aprobar, rechazar o cancelar la simulación.
4. Consulta `/pedido`. `/new` inicia otra conversación e invalida pendientes.

Cada botón pertenece al usuario, chat, mensaje y cotización correctos. Caduca
en 30 minutos. Cambiar la cotización invalida los botones anteriores. Los
eventos se conservan y un doble clic no produce otro pago.

```sh
.venv/bin/python -m pasteles pagos exportar --formato csv --salida exportaciones/pagos.csv
.venv/bin/python -m pasteles pagos exportar --formato json --salida exportaciones/pagos.json
.venv/bin/python -m pasteles gasto
.venv/bin/python -m pasteles diagnostico
```

Los exportes identifican la simulación e incluyen importes enteros en centavos,
fechas, pedido y estado. Excluyen los identificadores personales de Telegram.
Los datos operativos están en `.runtime/`, fuera de Git; no borres esa carpeta
para reiniciar el gasto. El límite es **5 USD acumulados** entre conversaciones
y evaluaciones, con reservas conservadoras por llamadas cuyo cobro aún no se
conoce. Puede detenerse antes del límite si no alcanza para la siguiente reserva.

## Evaluaciones

`make humo` comprueba contratos, herramientas, pagos y corpus sin llamar a un
modelo. **No mide la calidad conversacional de Claude.**

```sh
.venv/bin/python -m pasteles evals validar
.venv/bin/python -m pasteles evals pagos --salida resultados/evals-pagos
.venv/bin/python -m pasteles evals ejecutar --particion desarrollo --salida resultados/desarrollo-001
.venv/bin/python -m pasteles evals ejecutar --particion reservada --salida resultados/reservada-001
```

Las ejecuciones reales requieren `ANTHROPIC_API_KEY` y comparten el mismo tope.
También puedes usar `./EVALUAR.sh desarrollo` o `./EVALUAR.sh reservada`; piden
la llave de forma oculta y no la guardan. Detén el bot antes de evaluar.
Cada reporte conserva trazas, numeradores, denominadores, costo y latencia,
señala conversaciones incompletas y requiere revisión humana de la conversación.
La evaluación del agente/modelo y herramientas se distingue de la integración
con Hermes y Telegram. Ver [criterios y protocolo](docs/EVALUACIONES.md).

No modificar el corpus reservado ni usar sus respuestas para ajustar el prompt.
Una corrida aprobada no demuestra una mejora estadística ni ventas reales.

## Arquitectura y operación

Telegram → Hermes (perfil exclusivo) → proxy local con presupuesto → Anthropic.
En modo RSI, el adaptador nativo consume el mensaje autenticado y ejecuta el
mismo harness de las evaluaciones: una extracción JSON y cálculo determinista.
El flujo anterior de tres herramientas MCP se conserva para compatibilidad.
El plugin registra la cotización y procesa `/pagar` y sus botones sin decisiones del modelo. SQLite persiste los
pagos y la contabilidad. No hay dependencias del núcleo de Río.

Hermes solo recibe una credencial aleatoria del proxy local. Su entorno no
hereda llaves de modelos, logins personales ni otros canales. La configuración
desactiva fallbacks y tareas auxiliares de inferencia. El código del proveedor
está en `pasteles/llm.py`; no se usa streaming, sampling ni prefill.
La credencial del proxy se guarda con el token de Telegram en el `.env` privado
del perfil, porque Hermes aísla los secretos por perfil. La llave Anthropic
permanece únicamente en el proceso del proxy.

`make verificar-hermes` ejecuta el CLI instalado con un perfil temporal y un
proveedor falso: verifica registro del plugin, descubrimiento MCP y una vuelta
completa de las tres herramientas. No llama a Anthropic ni envía mensajes a Telegram.

El perfil y las bases deben permanecer en un disco local. Conserva sus permisos
privados y realiza copias locales si necesitas conservar los resultados.
Una desinstalación detiene los procesos y retira el perfil; no elimina las bases
ni los resultados automáticamente.
