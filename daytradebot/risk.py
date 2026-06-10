from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typing import Any

from daytradebot.config import Settings

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")


def et_day_stats(risk_state_dir: str, equity: float) -> dict[str, Any]:
    """Read persisted ET-day baseline for Discord / status."""
    path = Path(risk_state_dir) / "risk_state.json"
    out: dict[str, Any] = {"baseline": None, "dd_pct": None, "halted": False}
    if not path.is_file():
        return out
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    today = datetime.now(NY).date().isoformat()
    if str(state.get("date_et", "")) != today:
        return out
    baseline = float(state.get("baseline_equity", 0.0) or 0.0)
    halted = bool(state.get("halted", False))
    out["baseline"] = baseline if baseline > 0 else None
    out["halted"] = halted
    if baseline > 0 and equity > 0:
        out["dd_pct"] = (equity / baseline - 1.0) * 100.0
    return out


@dataclass(frozen=True)
class RiskDecision:
    allow_new_trades: bool
    reasons: tuple[str, ...]


class RiskController:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = Path(settings.risk_state_dir) / "risk_state.json"

    def _load(self) -> dict:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _today(self) -> str:
        return datetime.now(NY).date().isoformat()

    def evaluate(self, equity: float, account_status: str) -> RiskDecision:
        reasons: list[str] = []
        status = str(account_status).strip().upper()
        if "ACTIVE" not in status:
            reasons.append(f"account_not_active:{status}")
            return RiskDecision(False, tuple(reasons))

        if self._settings.kill_switch:
            reasons.append("kill_switch_env")
            return RiskDecision(False, tuple(reasons))

        kf = self._settings.kill_switch_file.strip()
        if kf and Path(kf).is_file():
            reasons.append(f"kill_switch_file:{kf}")
            return RiskDecision(False, tuple(reasons))

        state = self._load()
        today = self._today()
        if state.get("date_et") != today:
            state = {
                "date_et": today,
                "baseline_equity": equity,
                "trades_today": 0,
                "halted": False,
            }
            self._save(state)
            log.info("Risk: new ET day %s baseline=%.2f", today, equity)

        if state.get("halted"):
            reasons.append("daily_loss_halted")
            return RiskDecision(False, tuple(reasons))

        trades = int(state.get("trades_today", 0) or 0)
        if trades >= self._settings.max_trades_per_day:
            reasons.append(f"max_trades_per_day:{trades}")
            return RiskDecision(False, tuple(reasons))

        lim = float(self._settings.max_daily_loss_pct)
        baseline = float(state.get("baseline_equity", 0.0) or 0.0)
        if lim > 0 and baseline > 0 and equity > 0:
            dd = equity / baseline - 1.0
            if dd <= -lim:
                state["halted"] = True
                self._save(state)
                reasons.append(f"daily_loss_tripped:{dd:.4f}")
                return RiskDecision(False, tuple(reasons))

        return RiskDecision(True, ("ok",))

    def record_trade(self) -> None:
        state = self._load()
        if state.get("date_et") != self._today():
            return
        state["trades_today"] = int(state.get("trades_today", 0) or 0) + 1
        self._save(state)
