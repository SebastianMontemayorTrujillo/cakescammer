#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  printf 'Prepara el entorno siguiendo README.md antes de iniciar.\n' >&2
  exit 1
fi
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  read -r -s -p 'Llave API de Anthropic (no se guarda): ' ANTHROPIC_API_KEY
  printf '\n'
  export ANTHROPIC_API_KEY
fi
export PRESUPUESTO_USD="${PRESUPUESTO_USD:-5.00}"
exec .venv/bin/python -m pasteles iniciar
