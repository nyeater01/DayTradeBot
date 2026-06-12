# DayTradeBot — agent context

Read this (and `docs/ROADMAP.md`) at the start of a session. Intraday companion to **StockBot** on the same mini PC. See **`docs/REPO_SEPARATION.md`** — never mix repos or `.env` files.

**Status (2026-06-12):** Second Alpaca paper keys on NUC; `daytradebot.service` **enabled + active**. Profitability paper profile on NUC `.env` (`ny_am` only, confluence 4). First meaningful watch: **2026-06-15** Mon AM killzone 9:30–11:00 ET.

## Workflow

- GitHub `main` is source of truth. Edit on Windows → push. NUC pulls at `~/projects/DayTradeBot`.
- Never commit: `.env`, `.venv/`, `.state/`
- Service: `daytradebot.service` (user systemd), optional cron `auto-update.sh`
- StockBot stays in `~/projects/StockBot` — no shared `.env`

## Strategy

**Operating model (profitability-first paper profile, NUC `.env` 2026-06-12):** selective AM-session confluence — quality over quantity. Tune from logs after ~20 trading days; do not chase trade count.

Confluence intraday entries during **ICT killzones** (NUC paper: **`ny_am` only** — 9:30–11:00 ET):

| Signal | Role |
|--------|------|
| Session VWAP | Trend bias (above = long bias, below = short) |
| Volume profile | POC / VAH / VAL — value area context |
| Floor pivots | Prior day H/L/C → P, R1, S1 |
| Killzones | Entries only inside enabled windows |

**NUC paper tuning (not in git):** `CONFLUENCE_MIN=4`, `MAX_TRADES_PER_DAY=2`, `DEPLOY_FRAC=0.30`, stop/target 0.4%/0.8% (2:1), tighter pivot tolerance.

- **Flat** outside killzone and at session close (configurable)
- **Stop / target** from entry (`DAYTRADEBOT_STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`)
- **Risk:** max trades/day, daily loss halt (blocks new entries only)

**Path to live:** paper month → score expectancy → code upgrades (brackets, spread filter, backtest) → small live size.

## Code map

| Area | Files |
|------|--------|
| Loop | `daytradebot/runner.py`, `session_policy.py` |
| Signals | `engine_intraday.py`, `features/` |
| Broker | `daytradebot/alpaca_broker.py` |
| Risk | `daytradebot/risk.py` |
| Discord | `daytradebot/discord_notify.py` |
| Config | `daytradebot/config.py`, `.env.example` |

## When changing behavior

- Match existing style; minimal diff
- Add/update tests under `tests/` for signal or policy logic
- Update `docs/ROADMAP.md` Done / Now / Later (and changelog when shipping)
- Document new env keys in `.env.example` only — never commit mini PC `.env`
- NUC runtime tuning: edit `~/projects/DayTradeBot/.env` on mini PC; note values + date in ROADMAP

## Tests

```bash
python -m pytest tests/ -q
```
