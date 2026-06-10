# DayTradeBot roadmap

## Done (v0.1)

- Repo scaffold with `DAYTRADEBOT_*` env prefix (no collision with StockBot)
- ICT killzones: asia, london, ny_am, ny_pm (ET)
- Session VWAP, volume profile (POC/VAH/VAL), classic pivots
- Confluence scoring + intraday engine with stop/target exits
- Alpaca broker (intraday + daily bars, wash-trade skip)
- Risk: daily loss halt, max trades/day, kill switch
- Discord webhook (trades + cycle summary + errors)
- Linux scripts + `daytradebot.service` template

## Now

- Paper month on second Alpaca account; tune `CONFLUENCE_MIN`, killzones, deploy frac
- Create GitHub repo, clone on NUC, enable systemd

## Later

- Bracket orders (native stop/limit) instead of poll-based exits
- Opening range / FVG-style filters
- Per-symbol killzone profiles (e.g. QQQ ny_am only)
- Shared ops dashboard with StockBot (optional)
