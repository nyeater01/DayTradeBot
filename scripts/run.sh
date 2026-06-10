#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/ensure-venv.sh"
mkdir -p logs .state
export DAYTRADEBOT_LOG_FILE="${DAYTRADEBOT_LOG_FILE:-$ROOT/logs/daytradebot.log}"
exec .venv/bin/python -m daytradebot "$@"
