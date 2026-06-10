# DayTradeBot — agent context

Intraday companion to **StockBot** on the same mini PC. Separate git repo, Alpaca paper account, Discord webhook, systemd service. See **`docs/REPO_SEPARATION.md`** — never mix repos or `.env` files.

## Workflow

- GitHub `main` is source of truth. Edit on Windows → push. NUC pulls at `~/projects/DayTradeBot`.
- Never commit: `.env`, `.venv/`, `.state/`
- Service: `daytradebot.service` (user systemd), optional cron `auto-update.sh`
- StockBot stays in `~/projects/StockBot` — no shared `.env`

## Strategy

Confluence intraday entries during **ICT killzones** (default `ny_am`, `ny_pm` ET):

| Signal | Role |
|--------|------|
| Session VWAP | Trend bias (above = long bias, below = short) |
| Volume profile | POC / VAH / VAL — value area context |
| Floor pivots | Prior day H/L/C → P, R1, S1 |
| Killzones | Entries only inside enabled windows |

- **Flat** outside killzone and at session close (configurable)
- **Stop / target** from entry (`DAYTRADEBOT_STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`)
- **Risk:** max trades/day, daily loss halt (blocks new entries only)

## Code map

| Area | Files |
|------|--------|
| Loop | `daytradebot/runner.py`, `session_policy.py` |
| Signals | `engine_intraday.py`, `features/` |
| Broker | `daytradebot/alpaca_broker.py` |
| Risk | `daytradebot/risk.py` |
| Discord | `daytradebot/discord_notify.py` |
| Config | `daytradebot/config.py`, `.env.example` |

## Tests

```bash
python -m pytest tests/ -q
```
