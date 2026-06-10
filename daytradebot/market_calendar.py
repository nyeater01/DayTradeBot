from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from daytradebot.session_policy import NY

_REGULAR_CLOSE = (16, 0)


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _to_et_dt(value: Any, on_day: date) -> datetime:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=NY)
        return dt.astimezone(NY)
    raw = str(value).strip()
    if "T" in raw or "+" in raw or raw.endswith("Z"):
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=NY)
        return dt.astimezone(NY)
    parts = raw.replace(":", "")[:4]
    hh, mm = int(parts[:2]), int(parts[2:4])
    return datetime(on_day.year, on_day.month, on_day.day, hh, mm, tzinfo=NY)


def normalize_calendar_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        d = _as_date(row["date"])
        open_et = _to_et_dt(row["open"], d)
        close_et = _to_et_dt(row["close"], d)
        out.append(
            {
                "date": d,
                "open": open_et,
                "close": close_et,
                "early_close": (close_et.hour, close_et.minute) < _REGULAR_CLOSE,
            }
        )
    return sorted(out, key=lambda r: r["date"])


def trading_date_set(rows: list[dict[str, Any]]) -> set[date]:
    return {_as_date(r["date"]) for r in rows}


def session_for_date(rows: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    for row in rows:
        if row["date"] == day:
            return row
    return None


def next_trading_session(
    rows: list[dict[str, Any]], after: date
) -> dict[str, Any] | None:
    for row in rows:
        if row["date"] > after:
            return row
    return None


def upcoming_market_holidays(
    rows: list[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> list[date]:
    trade = trading_date_set(rows)
    holidays: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in trade:
            holidays.append(d)
        d += timedelta(days=1)
    return holidays


def _fmt_clock(dt: datetime) -> str:
    text = dt.strftime("%I:%M %p")
    if text.startswith("0"):
        text = text[1:]
    return text


def format_session_hours(row: dict[str, Any]) -> str:
    line = f"{_fmt_clock(row['open'])} - {_fmt_clock(row['close'])} ET"
    if row.get("early_close"):
        line += "\n\n_(Early close)_"
    return line


def format_day_long(d: date) -> str:
    return d.strftime("%A, %B %d, %Y").replace(" 0", " ")
