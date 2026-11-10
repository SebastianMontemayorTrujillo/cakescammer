# Pasteles — proyecto independiente

Proyecto separado de Río por autorización explícita del equipo. La copia original se conserva. Este repositorio implementa Telegram privado, catálogo demo y pagos simulados; no depende del código ni del presupuesto de Río.

- Python >=3.11, biblioteca estándar, anthropic y pytest; reutilizar Hermes instalado sin modificarlo. No añadir dependencias sin autorización.
- El equipo autorizó explícitamente instalar el extra oficial telegram de Hermes (python-telegram-bot==22.8) el 2026-11-09.
- Todo acceso a Anthropic pasa por pasteles/llm.py. Llave solo desde ANTHROPIC_API_KEY, nunca imprimir, registrar ni persistir. No enviar temperature, top_p, top_k ni prefill.
- Tope acumulado máximo 5 USD incluyendo pruebas. Persistir reservas/cargos y bloquear antes de gastar; no resetear ni subir automáticamente.
- Nunca debilitar, borrar o saltar tests. Si parecen incorrectos, detener y reportar.
- Verificar offline antes de gastar. make verificar al cerrar cada etapa y commit [EQUIPO] fase N: descripción.
- Nombres propios de código en español sin acentos; texto para personas en español correcto.
- Pagos y catálogo siempre marcados SIMULACION. El modelo no determina importes ni estados de pago.
- Identidad exclusivamente desde el contexto autenticado de Telegram. No aceptar ids de cliente del modelo.
- Resultados y eventos de evaluación conservan el historial. No presentar pruebas offline como calidad medida del modelo.
- No usar respuestas reservadas para optimizar prompts; documentar métricas y denominadores.
