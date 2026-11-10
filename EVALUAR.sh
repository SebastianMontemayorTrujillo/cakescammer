#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
particion_pasteles="${1:-desarrollo}"
case "$particion_pasteles" in
  desarrollo|reservada) ;;
  *) printf 'Uso: ./EVALUAR.sh desarrollo|reservada\n' >&2; exit 1 ;;
esac
if [[ ! -x .venv/bin/python ]]; then
  printf 'Prepara el entorno siguiendo README.md antes de evaluar.\n' >&2
  exit 1
fi
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  read -r -s -p 'Llave API de Anthropic (no se guarda): ' ANTHROPIC_API_KEY
  printf '\n'
  export ANTHROPIC_API_KEY
fi
export PRESUPUESTO_USD="${PRESUPUESTO_USD:-5.00}"
exec .venv/bin/python -m pasteles evals ejecutar --particion "$particion_pasteles" --salida resultados/evals
