#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/ensure-venv.sh"
[[ -f .env ]] || { echo "missing .env" >&2; exit 1; }
.venv/bin/python - <<'PY'
from daytradebot.config import Settings
from daytradebot.alpaca_broker import AlpacaBroker

settings = Settings.from_env()
settings.validate()
broker = AlpacaBroker(
    settings.api_key,
    settings.secret_key,
    paper=settings.paper,
    retry_attempts=settings.alpaca_retry_attempts,
    retry_base_delay_sec=settings.alpaca_retry_base_delay_sec,
)
acct = broker.get_account()
status = str(acct["status"]).strip().upper()
if status and status != "ACTIVE":
    raise SystemExit(f"account status not active: {status}")
sym = settings.symbols[0]
bars = broker.get_daily_bars(sym, 5)
if bars.empty:
    raise SystemExit(f"no daily bars for {sym}")
intraday = broker.get_intraday_bars(sym, settings.bar_timeframe_min)
print(f"smoke ok status={status} sym={sym} daily={len(bars)} intraday={len(intraday)}")
PY
