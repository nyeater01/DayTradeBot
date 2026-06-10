#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs .state

"$ROOT/scripts/ensure-venv.sh"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — add second Alpaca paper keys + Discord webhook"
  exit 1
fi

if ! grep -qE '^ALPACA_API_KEY=.+' .env 2>/dev/null || ! grep -qE '^ALPACA_SECRET_KEY=.+' .env 2>/dev/null; then
  echo "Alpaca keys missing in .env — edit $ROOT/.env"
  exit 1
fi

export DAYTRADEBOT_LOG_FILE="${DAYTRADEBOT_LOG_FILE:-$ROOT/logs/daytradebot.log}"
exec .venv/bin/python -m daytradebot
