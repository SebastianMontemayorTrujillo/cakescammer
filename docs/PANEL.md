# Panel local de mejora

Desde el proyecto independiente:

```sh
cd /home/seb/pasteles
./PANEL.sh
# También: make panel
# Otro puerto: ./PANEL.sh --puerto 8766
```

Abre http://127.0.0.1:8765. El proceso permanece abierto hasta Ctrl+C. Puede convivir con el bot porque solo consulta evidencia; no inicia evaluaciones, reserva presupuesto ni cambia la versión activa. No requiere claves ni dependencias adicionales.

## Qué se puede ver

- **Evolución:** una curva por corrida, desde la base hasta sus candidatas. Diferencia publicación confirmada, rechazo e interrupción. La selección inicial muestra la corrida más reciente que publicó un sucesor; el selector permite consultar también los intentos posteriores sin mejora.
- **Benchmarks:** objetivos de conversación, controles de seguridad, oportunidades comerciales y reserva. Cada explicación incluye pregunta, denominador y límite de interpretación. La compuerta conserva los criterios del juez RSI: seguridad completa, cero regresiones y alguna mejora funcional o comercial; p95 ≤30 segundos/caso y máximo USD0.10/caso real.
- **Reserva:** muestra el último reporte reservado de la línea elegida, su estado, integridad, completitud, objetivos, seguridad, latencia, costo e identidad del contenido evaluado. Indica si corresponde a la versión activa. No calcula mejora respecto de una base de desarrollo.
- **Versión activa:** identidad de linaje y cinco decisiones observadas en el harness. La configuración mostrada es de solo lectura; el panel no vuelve a certificar la integridad de las skills.
- **Historial:** conserva corridas interrumpidas, candidatas rechazadas y publicaciones. Los resultados negativos nunca se eliminan de la vista.
- **Informe:** PDF de trece páginas y fuente LaTeX, con cuatro ejemplos comparados, método de evaluación y guía del dashboard; disponibles desde el menú y el pie de página.
- **Experiencia:** instrumento separado de ocho conversaciones públicas con respuestas breves, disponibilidad y orientación de pago. Muestra cada revisión del código, objetivos, controles y completitud. «Modelo real» corresponde a Claude; «Simulación» muestra JSON preparado. No incorpora automáticamente chats de Telegram.

La actualización automática ocurre cada 30 segundos mientras la página esté visible; «Actualizar» fuerza una nueva lectura. Ante error se conserva la última lectura con un aviso explícito. Si faltan reportes se muestra ausencia de evidencia; no se inventan ceros, porcentajes ni evaluaciones.

## Fuentes y límites

`pasteles/panel_datos.py` proyecta únicamente campos agregados de `resultados/rsi/*/reporte.json` y `resultados/simulacion/rsi/*/reporte.json`. Lee identidad y configuración activa de las rutas fijas de `.runtime/rsi/` y `.runtime/rsi-simulacion/`; consulta el saldo SQLite con `mode=ro`. No inspecciona campos de casos, trazas, prompts, datos personales ni archivos de contexto privado, aunque un reporte contenga esos campos. Nunca sirve archivos de resultados completos.

Los deltas requieren una comparación válida del juez, huellas y padre correspondientes y el mismo denominador. Una incompatibilidad de instrumento, configuración o pares bloquea la comparación. Una publicación contradictoria queda sin confirmar. Los avisos y etiquetas proceden de listas cerradas; los datos se insertan como texto en la interfaz.

El costo acumulado pertenece a la cuenta compartida: puede seguir cambiando si el bot está atendiendo mensajes. Leer el panel no añade cargos. El ticket comercial es potencial, sintético, en MXN y con N explícito; no representa ingresos ni persuasión observada. El instrumento anterior de ocho conversaciones de desarrollo y 32 reservadas permanece separado.

Una versión declarativa idéntica puede ejecutarse sobre otra revisión del código.
Para mostrar reserva vigente se exige también coincidencia del SHA-256 de
`pasteles/arnes.py`; de lo contrario se conserva como histórica. Las corridas RSI
mantienen sus comparaciones originales y su revisión. La tabla de experiencia
lee solo agregados de `resultados/experiencia/` y `resultados/simulacion/experiencia/`,
sin publicar sus trazas. Esta tabla de desarrollo no sustituye una reserva nueva.

El servidor escucha solo en `127.0.0.1`, valida Host y Origin y publica una lista cerrada de archivos y `/api/panel`. Rechaza enlaces simbólicos/hardlinks, no habilita CORS y no expone operaciones de escritura. La vista no constituye una consola administrativa ni un despliegue público.

## Documento LaTeX

Fuentes y artefacto: `output/pdf/pasteles_rsi.tex` y `output/pdf/pasteles_rsi.pdf`. El documento recoge el corte de evidencia del 9 de noviembre de 2026; el dashboard lee el estado actual.

Para recompilar con XeLaTeX instalado:

```sh
mkdir -p tmp/pdfs/pasteles_rsi
xelatex -interaction=nonstopmode -halt-on-error -no-shell-escape -output-directory=tmp/pdfs/pasteles_rsi output/pdf/pasteles_rsi.tex
xelatex -interaction=nonstopmode -halt-on-error -no-shell-escape -output-directory=tmp/pdfs/pasteles_rsi output/pdf/pasteles_rsi.tex
cp tmp/pdfs/pasteles_rsi/pasteles_rsi.pdf output/pdf/pasteles_rsi.pdf
```

La fuente incluye diagramas vectoriales y no descarga recursos externos. La edición ampliada contiene trece páginas. Los ejemplos son extractos de reproducciones sintéticas con Claude real, antes y después del cambio; la captura motivó la corrección, pero no se presenta una continuación inventada de aquel chat.
