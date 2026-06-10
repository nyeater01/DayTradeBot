# StockBot vs DayTradeBot — keep them separate

Two bots, one mini PC. **Never mix git remotes, `.env`, or systemd units.**

| | StockBot | DayTradeBot |
|---|----------|-------------|
| **GitHub** | `nyeater01/StockBot` | `nyeater01/DayTradeBot` |
| **NUC path** | `~/projects/StockBot` | `~/projects/DayTradeBot` |
| **Env prefix** | `STOCKBOT_*` | `DAYTRADEBOT_*` |
| **Secrets file** | `~/projects/StockBot/.env` | `~/projects/DayTradeBot/.env` |
| **Alpaca account** | Paper #1 (rotation) | Paper #2 (intraday) — **different keys** |
| **Discord webhook** | StockBot channel | DayTradeBot channel — **different URL** |
| **State / logs** | `.state/`, `logs/stockbot.log` | `.state/`, `logs/daytradebot.log` |
| **systemd unit** | `stockbot.service` | `daytradebot.service` |
| **Control script** | `stockbot-ctl.sh` | `daytradebot-ctl.sh` |
| **Auto-update cron** | `StockBot/scripts/auto-update.sh` | `DayTradeBot/scripts/auto-update.sh` |

## Rules

1. **One repo per directory.** Do not `git pull` StockBot inside DayTradeBot or vice versa.
2. **Never copy `.env` between repos.** Shared `ALPACA_*` keys = both bots on one account (usually wrong).
3. **Edit code on Windows** in the matching Desktop folder → push → NUC pulls that repo only.
4. **Ops on NUC:** `cd ~/projects/StockBot` or `cd ~/projects/DayTradeBot` before any git/systemctl command.
5. **Agents / Cursor:** open the correct workspace folder; read that repo's `AGENTS.md` only.

## Quick checks (NUC)

```bash
git -C ~/projects/StockBot remote get-url origin
git -C ~/projects/DayTradeBot remote get-url origin
systemctl --user status stockbot.service daytradebot.service
```

## DayTradeBot before Alpaca keys

Service is installed but **not started** until `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are in `~/projects/DayTradeBot/.env`. Discord webhook can be tested without keys:

```bash
cd ~/projects/DayTradeBot && ./scripts/run.sh --discord-test
```

After keys:

```bash
./scripts/smoke-check.sh
./scripts/daytradebot-ctl.sh restart
./scripts/daytradebot-ctl.sh enable
```
