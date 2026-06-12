# DayTradeBot roadmap

Living checklist — update when shipping or changing priorities. Cursor/agents: keep in sync with `AGENTS.md`.

**As of 2026-06-12 (ET):** NUC live on second paper account; profitability paper profile on runtime `.env`. Paper month watch starts **2026-06-15** (Mon AM session). StockBot unchanged in separate repo.

## Done (shipped)

- [x] Repo scaffold with `DAYTRADEBOT_*` env prefix (no collision with StockBot)
- [x] ICT killzones: asia, london, ny_am, ny_pm (ET)
- [x] Session VWAP, volume profile (POC/VAH/VAL), classic pivots
- [x] Confluence scoring + intraday engine with stop/target exits
- [x] Alpaca broker (intraday + daily bars, wash-trade skip)
- [x] Risk: daily loss halt, max trades/day, kill switch
- [x] Discord webhook (trades + cycle summary + errors)
- [x] Linux scripts + `daytradebot.service` template
- [x] NUC clone at `~/projects/DayTradeBot`, venv, auto-update cron
- [x] Second Alpaca paper keys + smoke check (2026-06-12)
- [x] `daytradebot.service` enabled on NUC (2026-06-12)

## Now (paper watch phase)

**Plan:** ~**1 month** paper on second Alpaca account. Owner checks **Discord** during **9:30–11:00 ET** weekdays; no live until pass bar below.

- [ ] First AM killzone week under profitability profile (from **2026-06-15**)
- [ ] Weekly trade log: count, win/loss, avg win vs loss
- [ ] No false daily-loss halts; no recurring Discord/network error bursts
- [ ] Behavior boring and explainable (0 trades many days is OK)

**NUC runtime tuning (not in git, set 2026-06-12):**

| Key | Value |
|-----|-------|
| `DAYTRADEBOT_KILLZONES` | `ny_am` |
| `DAYTRADEBOT_CONFLUENCE_MIN` | `4` |
| `DAYTRADEBOT_MAX_TRADES_PER_DAY` | `2` |
| `DAYTRADEBOT_DEPLOY_FRAC` | `0.30` |
| `DAYTRADEBOT_STOP_LOSS_PCT` | `0.004` |
| `DAYTRADEBOT_TAKE_PROFIT_PCT` | `0.008` |
| `DAYTRADEBOT_PIVOT_TOLERANCE_PCT` | `0.0012` |
| `DAYTRADEBOT_SYMBOLS` | `SPY,QQQ` |

**Pass bar (then tune or code upgrades):** clean AM sessions, measured expectancy, risk limits respected. Paper P&amp;L vs buy-and-hold is optional context, not pass/fail.

## Later

- Bracket orders (native stop/limit) instead of poll-based exits
- Spread cap on entries (liquid ETFs)
- Opening range / FVG-style filters
- Per-symbol killzone profiles (e.g. QQQ ny_am only)
- Offline backtest / walk-forward
- Shared ops dashboard with StockBot (optional)

## Changelog (high level)

| When | What |
|------|------|
| 2026-06-12 | NUC keys + service enabled; profitability paper profile on runtime `.env` |
| 2026-06-10 | NUC clone, Discord tested, service installed (disabled until keys) |
| 2026-06 | v0.1 scaffold, confluence engine, Discord parity with StockBot |
