#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
modo_rsi="${1:-simulacion}"
generaciones_rsi="${2:-4}"
if [[ "$modo_rsi" != simulacion && "$modo_rsi" != real ]]; then
  echo "Uso: ./RSI.sh [simulacion|real] [1-5 generaciones]" >&2
  exit 1
fi
if [[ "$modo_rsi" == real && -z "${ANTHROPIC_API_KEY:-}" ]]; then
  read -r -s -p "Clave de Anthropic (solo en memoria): " ANTHROPIC_API_KEY
  echo
  export ANTHROPIC_API_KEY
fi
export PRESUPUESTO_USD="${PRESUPUESTO_USD:-5.00}"
exec .venv/bin/python -m pasteles rsi ciclo --modo "$modo_rsi" --generaciones "$generaciones_rsi"
