from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd
from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings
from daytradebot.features.pivots import classic_pivots, near_level
from daytradebot.features.volume_profile import session_volume_profile
from daytradebot.features.vwap import session_vwap, vwap_side
from daytradebot.risk import RiskController, RiskDecision
from daytradebot.session_policy import active_killzones, now_et

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Signal:
    action: str  # BUY | SELL | HOLD | FLAT
    side_bias: str  # long | short | neutral
    score: int
    reasons: tuple[str, ...]


def _confluence_long(
    price: float,
    vwap: float | None,
    vp: dict[str, float] | None,
    piv: dict[str, float],
    tol: float,
) -> tuple[int, list[str]]:
    hits: list[str] = []
    if vwap_side(price, vwap) == "above":
        hits.append("above_vwap")
    if vp and price >= vp["VAL"]:
        hits.append("above_val")
    if vp and near_level(price, vp["POC"], tol):
        hits.append("near_poc")
    if near_level(price, piv["S1"], tol) or near_level(price, piv["P"], tol):
        hits.append("near_pivot_support")
    if vp and near_level(price, vp["VAL"], tol):
        hits.append("at_val")
    return len(hits), hits


def _confluence_short(
    price: float,
    vwap: float | None,
    vp: dict[str, float] | None,
    piv: dict[str, float],
    tol: float,
) -> tuple[int, list[str]]:
    hits: list[str] = []
    if vwap_side(price, vwap) == "below":
        hits.append("below_vwap")
    if vp and price <= vp["VAH"]:
        hits.append("below_vah")
    if vp and near_level(price, vp["POC"], tol):
        hits.append("near_poc")
    if near_level(price, piv["R1"], tol) or near_level(price, piv["P"], tol):
        hits.append("near_pivot_resistance")
    if vp and near_level(price, vp["VAH"], tol):
        hits.append("at_vah")
    return len(hits), hits


def evaluate_symbol(
    settings: Settings,
    symbol: str,
    session_bars: pd.DataFrame,
    prior_daily: pd.DataFrame,
    in_killzone: bool,
) -> Signal:
    if session_bars.empty or len(prior_daily) < 1:
        return Signal("HOLD", "neutral", 0, ("no_bars",))

    last = float(session_bars["close"].iloc[-1])
    prev = prior_daily.iloc[-1]
    piv = classic_pivots(float(prev["high"]), float(prev["low"]), float(prev["close"]))
    vwap = session_vwap(session_bars)
    vp = session_volume_profile(
        session_bars,
        n_bins=settings.volume_profile_bins,
        value_area_pct=settings.value_area_pct,
    )

    if not in_killzone:
        return Signal("HOLD", "neutral", 0, ("outside_killzone",))

    long_score, long_hits = _confluence_long(last, vwap, vp, piv, settings.pivot_tolerance_pct)
    short_score, short_hits = _confluence_short(last, vwap, vp, piv, settings.pivot_tolerance_pct)

    log.info(
        "[%s] px=%.4f vwap=%s poc=%s | long=%d %s short=%d %s",
        symbol,
        last,
        f"{vwap:.4f}" if vwap else "n/a",
        f"{vp['POC']:.4f}" if vp else "n/a",
        long_score,
        long_hits,
        short_score,
        short_hits,
    )

    if long_score >= settings.confluence_min and long_score > short_score:
        return Signal("BUY", "long", long_score, tuple(long_hits))
    if short_score >= settings.confluence_min and short_score > long_score:
        return Signal("SELL", "short", short_score, tuple(short_hits))
    return Signal("HOLD", "neutral", max(long_score, short_score), ("no_setup",))


def _check_stop_targets(
    settings: Settings,
    broker: AlpacaBroker,
    symbol: str,
    last_price: float,
) -> str | None:
    """Return exit side if stop or target hit for an open position."""
    pos = broker.get_position(symbol)
    if not pos or last_price <= 0:
        return None
    qty = float(pos["qty"])
    entry = float(pos["avg_entry_price"])
    if qty == 0 or entry <= 0:
        return None
    stop = settings.stop_loss_pct
    target = settings.take_profit_pct
    if qty > 0:
        pnl_pct = last_price / entry - 1.0
        if stop > 0 and pnl_pct <= -stop:
            return "stop_long"
        if target > 0 and pnl_pct >= target:
            return "target_long"
    else:
        pnl_pct = entry / last_price - 1.0
        if stop > 0 and pnl_pct <= -stop:
            return "stop_short"
        if target > 0 and pnl_pct >= target:
            return "target_short"
    return None


def _submit_exit(
    broker: AlpacaBroker,
    symbol: str,
    qty: float,
    tag: str,
) -> str:
    side = "SELL" if qty > 0 else "BUY"
    cid = f"dtb-{tag}-{uuid.uuid4().hex[:16]}"
    return broker.submit_market_order(symbol, abs(qty), side, client_order_id=cid)


def run_intraday_cycle(
    settings: Settings,
    broker: AlpacaBroker,
    risk: RiskDecision,
    flat_reason: str,
    risk_ctrl: RiskController | None = None,
) -> dict[str, Any]:
    """One decision cycle across the symbol watchlist."""
    acct = broker.get_account()
    clock = now_et()
    zones = active_killzones(clock, settings.killzones)
    log.info(
        "Account ACTIVE=%s equity=%.2f zones=%s flat=%s",
        acct["status"],
        acct["equity"],
        zones or "none",
        flat_reason or "no",
    )

    summary: dict[str, Any] = {
        "zones": zones,
        "flat_reason": flat_reason,
        "signals": {},
    }

    if flat_reason:
        for sym in settings.symbols:
            pos = broker.get_position_qty(sym)
            if pos == 0:
                continue
            oid = _submit_exit(broker, sym, pos, "flat")
            if oid and risk_ctrl:
                risk_ctrl.record_trade()
        return summary

    in_kz = bool(zones)
    for sym in settings.symbols:
        pos = broker.get_position_qty(sym)
        session_bars = broker.get_intraday_bars(sym, settings.bar_timeframe_min)
        prior = broker.get_daily_bars(sym, 5)

        if not session_bars.empty and pos != 0:
            last = float(session_bars["close"].iloc[-1])
            exit_tag = _check_stop_targets(settings, broker, sym, last)
            if exit_tag:
                log.info("[%s] exit %s at px=%.4f", sym, exit_tag, last)
                oid = _submit_exit(broker, sym, pos, exit_tag.replace("_", "-"))
                summary["signals"][sym] = {
                    "action": "EXIT",
                    "score": 0,
                    "reasons": (exit_tag,),
                    "pos": pos,
                }
                if oid and risk_ctrl:
                    risk_ctrl.record_trade()
                continue

        sig = evaluate_symbol(settings, sym, session_bars, prior, in_kz)
        summary["signals"][sym] = {
            "action": sig.action,
            "score": sig.score,
            "reasons": sig.reasons,
            "pos": pos,
        }

        if sig.action == "HOLD" or pos != 0:
            continue

        if not risk.allow_new_trades:
            log.warning("[%s] skip entry (%s)", sym, ", ".join(risk.reasons))
            continue

        qty = _size_qty(settings, sym, acct, session_bars)
        if qty <= 0:
            continue

        if sig.action == "BUY":
            cid = f"dtb-b-{uuid.uuid4().hex[:16]}"
            oid = broker.submit_market_order(sym, qty, "BUY", client_order_id=cid)
        elif sig.action == "SELL":
            cid = f"dtb-s-{uuid.uuid4().hex[:16]}"
            oid = broker.submit_market_order(sym, qty, "SELL", client_order_id=cid)
        else:
            oid = ""
        if oid and risk_ctrl:
            risk_ctrl.record_trade()

    return summary


def _size_qty(
    settings: Settings,
    symbol: str,
    acct: dict[str, Any],
    session_bars: pd.DataFrame,
) -> float:
    equity = float(acct["equity"])
    if equity <= 0 or session_bars.empty:
        return 0.0
    last = float(session_bars["close"].iloc[-1])
    if last <= 0:
        return 0.0
    notional = equity * settings.deploy_frac / max(len(settings.symbols), 1)
    qty = notional / last
    if qty * last < 1.0:
        return 0.0
    return round(qty, 4)
