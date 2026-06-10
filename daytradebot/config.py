from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import time

from dotenv import load_dotenv

load_dotenv()


def _parse_time_hhmm(value: str, default: str) -> time:
    raw = (value or default).strip()
    parts = raw.split(":")
    if len(parts) == 2:
        h, m = int(parts[0]), int(parts[1])
        return time(h, m)
    raise ValueError(f"Invalid time {raw!r}; use HH:MM")


def _parse_bool(value: str, default: bool = False) -> bool:
    raw = (value or ("1" if default else "0")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _parse_csv_upper(value: str, default: str) -> tuple[str, ...]:
    raw = value.strip() if value.strip() else default
    return tuple(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))


@dataclass(frozen=True)
class Settings:
    api_key: str
    secret_key: str
    paper: bool
    symbols: tuple[str, ...]
    poll_seconds: int
    bar_timeframe_min: int
    session_open: time
    session_close: time
    killzones: tuple[str, ...]
    flat_outside_killzone: bool
    flat_at_session_close: bool
    deploy_frac: float
    max_trades_per_day: int
    max_daily_loss_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    confluence_min: int
    pivot_tolerance_pct: float
    volume_profile_bins: int
    value_area_pct: float
    risk_state_dir: str
    kill_switch: bool
    kill_switch_file: str
    discord_webhook_url: str
    discord_on_trade: bool
    discord_cycle_report: bool
    discord_balance_interval_sec: int
    discord_session_notices: bool
    discord_holiday_ahead_days: int
    discord_min_interval_sec: int
    alpaca_retry_attempts: int
    alpaca_retry_base_delay_sec: float
    log_file: str

    @classmethod
    def from_env(cls) -> Settings:
        mode = os.getenv("ALPACA_TRADING_MODE", "paper").strip().lower()
        return cls(
            api_key=os.getenv("ALPACA_API_KEY", "").strip(),
            secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
            paper=mode != "live",
            symbols=_parse_csv_upper(os.getenv("DAYTRADEBOT_SYMBOLS", ""), "SPY,QQQ"),
            poll_seconds=int(os.getenv("DAYTRADEBOT_POLL_SECONDS", "30")),
            bar_timeframe_min=int(os.getenv("DAYTRADEBOT_BAR_MINUTES", "1")),
            session_open=_parse_time_hhmm(os.getenv("DAYTRADEBOT_SESSION_OPEN", ""), "09:30"),
            session_close=_parse_time_hhmm(os.getenv("DAYTRADEBOT_SESSION_CLOSE", ""), "16:00"),
            killzones=_parse_csv_lower_killzones(
                os.getenv("DAYTRADEBOT_KILLZONES", "ny_am,ny_pm")
            ),
            flat_outside_killzone=_parse_bool(os.getenv("DAYTRADEBOT_FLAT_OUTSIDE_KILLZONE", "1")),
            flat_at_session_close=_parse_bool(os.getenv("DAYTRADEBOT_FLAT_AT_CLOSE", "1")),
            deploy_frac=float(os.getenv("DAYTRADEBOT_DEPLOY_FRAC", "0.5")),
            max_trades_per_day=int(os.getenv("DAYTRADEBOT_MAX_TRADES_PER_DAY", "3")),
            max_daily_loss_pct=float(os.getenv("DAYTRADEBOT_MAX_DAILY_LOSS_PCT", "0.03")),
            stop_loss_pct=float(os.getenv("DAYTRADEBOT_STOP_LOSS_PCT", "0.005")),
            take_profit_pct=float(os.getenv("DAYTRADEBOT_TAKE_PROFIT_PCT", "0.01")),
            confluence_min=int(os.getenv("DAYTRADEBOT_CONFLUENCE_MIN", "3")),
            pivot_tolerance_pct=float(os.getenv("DAYTRADEBOT_PIVOT_TOLERANCE_PCT", "0.0015")),
            volume_profile_bins=int(os.getenv("DAYTRADEBOT_VP_BINS", "50")),
            value_area_pct=float(os.getenv("DAYTRADEBOT_VALUE_AREA_PCT", "0.70")),
            risk_state_dir=os.getenv("DAYTRADEBOT_RISK_STATE_DIR", ".state").strip() or ".state",
            kill_switch=_parse_bool(os.getenv("DAYTRADEBOT_KILL_SWITCH", "0")),
            kill_switch_file=os.getenv("DAYTRADEBOT_KILL_SWITCH_FILE", "").strip(),
            discord_webhook_url=os.getenv("DAYTRADEBOT_DISCORD_WEBHOOK_URL", "").strip(),
            discord_on_trade=_parse_bool(os.getenv("DAYTRADEBOT_DISCORD_ON_TRADE", "1"), True),
            discord_cycle_report=_parse_bool(os.getenv("DAYTRADEBOT_DISCORD_CYCLE_REPORT", "0")),
            discord_balance_interval_sec=int(
                os.getenv("DAYTRADEBOT_DISCORD_BALANCE_INTERVAL_SEC", "28800")
            ),
            discord_session_notices=_parse_bool(
                os.getenv("DAYTRADEBOT_DISCORD_SESSION_NOTICES", "1"), True
            ),
            discord_holiday_ahead_days=int(
                os.getenv("DAYTRADEBOT_DISCORD_HOLIDAY_AHEAD_DAYS", "3")
            ),
            discord_min_interval_sec=int(os.getenv("DAYTRADEBOT_DISCORD_MIN_INTERVAL_SEC", "2")),
            alpaca_retry_attempts=int(os.getenv("DAYTRADEBOT_ALPACA_RETRY_ATTEMPTS", "3")),
            alpaca_retry_base_delay_sec=float(
                os.getenv("DAYTRADEBOT_ALPACA_RETRY_BASE_DELAY_SEC", "2.0")
            ),
            log_file=os.getenv("DAYTRADEBOT_LOG_FILE", "").strip(),
        )

    def validate(self) -> None:
        if not self.api_key or not self.secret_key:
            raise ValueError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
        if not self.symbols:
            raise ValueError("DAYTRADEBOT_SYMBOLS must list at least one ticker")
        if self.bar_timeframe_min not in (1, 2, 5, 15):
            raise ValueError("DAYTRADEBOT_BAR_MINUTES must be 1, 2, 5, or 15")
        if not (0.0 < self.deploy_frac <= 1.0):
            raise ValueError("DAYTRADEBOT_DEPLOY_FRAC must be in (0, 1]")
        if self.max_trades_per_day < 1:
            raise ValueError("DAYTRADEBOT_MAX_TRADES_PER_DAY must be >= 1")
        if self.confluence_min < 1:
            raise ValueError("DAYTRADEBOT_CONFLUENCE_MIN must be >= 1")
        if self.volume_profile_bins < 10:
            raise ValueError("DAYTRADEBOT_VP_BINS must be >= 10")
        if not (0.5 <= self.value_area_pct <= 0.95):
            raise ValueError("DAYTRADEBOT_VALUE_AREA_PCT should be between 0.5 and 0.95")
        url = self.discord_webhook_url
        if url and not url.startswith(
            ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
        ):
            raise ValueError("DAYTRADEBOT_DISCORD_WEBHOOK_URL must be a Discord webhook URL")
        if self.discord_min_interval_sec < 0:
            raise ValueError("DAYTRADEBOT_DISCORD_MIN_INTERVAL_SEC cannot be negative")
        if self.discord_balance_interval_sec < 0:
            raise ValueError("DAYTRADEBOT_DISCORD_BALANCE_INTERVAL_SEC cannot be negative")
        if self.discord_holiday_ahead_days < 0:
            raise ValueError("DAYTRADEBOT_DISCORD_HOLIDAY_AHEAD_DAYS cannot be negative")
        if not self.paper:
            got = os.getenv("DAYTRADEBOT_CONFIRM_LIVE", "").strip()
            if got != "YES_I_ACCEPT_REAL_MONEY_RISK":
                raise ValueError(
                    "Live blocked: set DAYTRADEBOT_CONFIRM_LIVE=YES_I_ACCEPT_REAL_MONEY_RISK"
                )
            if self.max_daily_loss_pct <= 0:
                raise ValueError("Live requires DAYTRADEBOT_MAX_DAILY_LOSS_PCT > 0")


def _parse_csv_lower_killzones(value: str) -> tuple[str, ...]:
    allowed = {"asia", "london", "ny_am", "ny_pm"}
    out: list[str] = []
    for part in value.split(","):
        k = part.strip().lower()
        if not k:
            continue
        if k not in allowed:
            raise ValueError(f"Unknown killzone {k!r}; allowed: {sorted(allowed)}")
        if k not in out:
            out.append(k)
    return tuple(out or ("ny_am",))


def configure_logging(settings: Settings, level: int = logging.INFO) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=fmt)
    else:
        root.setLevel(level)
    if settings.log_file:
        fh = logging.FileHandler(settings.log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        root.addHandler(fh)
