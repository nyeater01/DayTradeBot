from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings
from daytradebot.discord_notify import DiscordNotifier
from daytradebot.market_calendar import (
    format_day_long,
    next_trading_session,
    normalize_calendar_rows,
    session_for_date,
    upcoming_market_holidays,
)
from daytradebot.session_policy import now_et

log = logging.getLogger(__name__)


def _state_path(settings: Settings) -> Path:
    return Path(settings.risk_state_dir) / "discord_session.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Corrupt session notice state at %s; resetting", path)
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def maybe_send_session_notices(
    settings: Settings,
    broker: AlpacaBroker,
    discord: DiscordNotifier,
) -> None:
    if not settings.discord_session_notices:
        return

    today = now_et().date()
    look_end = today + timedelta(days=45)
    try:
        raw = broker.get_market_calendar(today - timedelta(days=1), look_end)
    except Exception:
        log.exception("Could not load market calendar for session notices")
        return

    rows = normalize_calendar_rows(raw)
    state_path = _state_path(settings)
    state = _load_state(state_path)
    changed = False

    today_sess = session_for_date(rows, today)
    now = now_et()

    open_key = str(state.get("open_announced_date", ""))
    close_key = str(state.get("close_announced_date", ""))
    closed_today_key = str(state.get("closed_today_announced_date", ""))
    announced: set[str] = set(state.get("holidays_announced", []))

    if today_sess is None and today.weekday() < 5:
        if closed_today_key != today.isoformat():
            discord.send_market_closed_today(settings, format_day_long(today))
            state["closed_today_announced_date"] = today.isoformat()
            changed = True
    elif today_sess is not None:
        if now >= today_sess["open"] and open_key != today.isoformat():
            discord.send_market_open(settings, today_sess)
            state["open_announced_date"] = today.isoformat()
            changed = True

        if now >= today_sess["close"] and close_key != today.isoformat():
            nxt = next_trading_session(rows, today)
            discord.send_market_close(settings, today_sess, nxt)
            state["close_announced_date"] = today.isoformat()
            changed = True

    ahead = max(1, int(settings.discord_holiday_ahead_days))
    window_end = today + timedelta(days=ahead)
    for hol in upcoming_market_holidays(rows, start=today + timedelta(days=1), end=window_end):
        key = hol.isoformat()
        if key in announced:
            continue
        days_until = (hol - today).days
        if days_until > ahead:
            continue
        resume = next_trading_session(rows, hol)
        discord.send_upcoming_holiday(settings, hol, days_until, resume)
        announced.add(key)
        changed = True

    if changed:
        state["holidays_announced"] = sorted(announced)
        _save_state(state_path, state)
