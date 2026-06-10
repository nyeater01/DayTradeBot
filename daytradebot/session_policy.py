from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

# ICT-style killzones (US/Eastern). Asia wraps midnight.
KILLZONE_WINDOWS: dict[str, tuple[time, time]] = {
    "asia": (time(20, 0), time(0, 0)),
    "london": (time(2, 0), time(5, 0)),
    "ny_am": (time(9, 30), time(11, 0)),
    "ny_pm": (time(13, 30), time(16, 0)),
}


def now_et() -> datetime:
    return datetime.now(NY)


def _in_window(clock: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= clock <= end
    return clock >= start or clock <= end


def active_killzones(now: datetime, enabled: tuple[str, ...]) -> tuple[str, ...]:
    """Return killzone names active at `now` (ET)."""
    t = now.astimezone(NY).time()
    hits = [name for name in enabled if name in KILLZONE_WINDOWS and _in_window(t, *KILLZONE_WINDOWS[name])]
    return tuple(hits)


def in_regular_session(now: datetime, session_open: time, session_close: time) -> bool:
    t = now.astimezone(NY)
    if t.weekday() >= 5:
        return False
    return session_open <= t.time() <= session_close


def should_flat_for_session(
    now: datetime,
    enabled_killzones: tuple[str, ...],
    flat_outside_killzone: bool,
    flat_at_session_close: bool,
    session_close: time,
) -> tuple[bool, str]:
    """Decide if open longs should be closed."""
    t = now.astimezone(NY)
    if t.weekday() >= 5:
        return True, "weekend"
    if flat_at_session_close and t.time() >= session_close:
        return True, "session_close"
    if flat_outside_killzone and enabled_killzones:
        if not active_killzones(t, enabled_killzones):
            return True, "outside_killzone"
    return False, ""
