from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings
from daytradebot.risk import RiskDecision, et_day_stats
from daytradebot.market_calendar import format_day_long, format_session_hours
from daytradebot.session_policy import now_et

log = logging.getLogger(__name__)

_COLOR_BUY = 0x2ECC71      # green
_COLOR_SELL = 0xF39C12     # orange
_COLOR_BALANCE = 0x9B59B6  # purple
_COLOR_ERR = 0xE74C3C      # red
_COLOR_NOTICE = 0x3498DB   # blue
_COLOR_CYCLE = 0x95A5A6   # gray (optional full cycle report)
_COLOR_SESSION = 0xEAEAEA  # white / light (market open & close)
_COLOR_HOLIDAY = 0xF1C40F  # yellow
_COLOR_PENDING = 0xEAEAEA  # white / light (accepted, pending, done for day)

_PENDING_STATUSES = {
    "accepted",
    "accepted_for_bidding",
    "held",
    "new",
    "pending_cancel",
    "pending_new",
    "pending_replace",
    "replaced",
    "stopped",
    "suspended",
    "done_for_day",
}
_FILLED_STATUSES = {"filled", "partially_filled"}
_FAILED_STATUSES = {"canceled", "cancelled", "expired", "rejected"}
_FINAL_STATUSES = _FILLED_STATUSES | _FAILED_STATUSES
_ACTIVE_ORDER_STATUSES = _PENDING_STATUSES | {"partially_filled"}
_FORCE_POST_GAP_SEC = 1.0


@dataclass(frozen=True)
class CycleContext:
    zones: tuple[str, ...] = ()
    flat_reason: str = ""
    risk: RiskDecision | None = None
    signals: dict[str, Any] | None = None


def _balance_snapshot_path(settings: Settings) -> Path:
    return Path(settings.risk_state_dir) / "discord_balance.json"


def _order_state_path(settings: Settings) -> Path:
    return Path(settings.risk_state_dir) / "discord_orders.json"


def _open_order_snapshot_path(settings: Settings) -> Path:
    return Path(settings.risk_state_dir) / "discord_open_orders.json"


def _load_balance_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Corrupt Discord balance snapshot at %s; resetting", path)
        return None


def _save_balance_snapshot(path: Path, equity: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "equity": equity,
        "at_utc": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_order_state(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Corrupt Discord order state at %s; resetting", path)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _save_order_state(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _load_open_order_snapshot(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Corrupt open-order snapshot at %s; resetting", path)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _save_open_order_snapshot(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _mode_label(settings: Settings) -> str:
    return "Paper" if settings.paper else "LIVE"


def _footer(settings: Settings, *, et_line: str | None = None) -> dict[str, str]:
    parts = [_mode_label(settings)]
    if et_line:
        parts.append(et_line)
    return {"text": " | ".join(parts)}


def _format_positions(positions: list[dict[str, Any]]) -> str:
    if not positions:
        return "No open positions."
    blocks: list[str] = []
    for p in sorted(positions, key=lambda x: str(x.get("symbol", ""))):
        sym = p["symbol"]
        qty = float(p["qty"])
        mv = float(p.get("market_value", 0.0))
        upl = float(p.get("unrealized_pl", 0.0))
        blocks.append(
            f"**{sym}**\n"
            f"Shares: {qty:g}\n"
            f"Market value: ${mv:,.2f}\n"
            f"Unrealized P&L: ${upl:+,.2f}"
        )
    return "\n\n".join(blocks)


def _normalize_order_status(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split(".")[-1].lower()


def _normalize_order_side(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split(".")[-1].upper()


def _parse_order_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_bot_order(order: dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id", "") or "").strip().lower()
    return cid.startswith("dtb")


def _order_status_label(status: str) -> str:
    return status.replace("_", " ").title()


def _order_status_color(status: str, side: str) -> int:
    if status in _FAILED_STATUSES:
        return _COLOR_ERR
    if status in _FILLED_STATUSES:
        return _COLOR_SELL if side == "SELL" else _COLOR_BUY
    if status in _PENDING_STATUSES:
        return _COLOR_PENDING
    return _COLOR_NOTICE


def _order_snapshot_line(order: dict[str, Any]) -> str:
    symbol = str(order.get("symbol", "") or "UNKNOWN").upper()
    side = _normalize_order_side(str(order.get("side", ""))) or "ORDER"
    status = _order_status_label(_normalize_order_status(str(order.get("status", ""))))
    qty = float(order.get("qty", 0.0) or 0.0)
    filled_qty = float(order.get("filled_qty", 0.0) or 0.0)
    return (
        f"**{symbol}**\n"
        f"{side} | {status}\n"
        f"Requested: {qty:g} shares\n"
        f"Filled: {filled_qty:g} shares"
    )


def _order_update_lines(order: dict[str, Any], *, include_order_id: bool) -> list[str]:
    status = _normalize_order_status(str(order.get("status", "")))
    side = _normalize_order_side(str(order.get("side", ""))) or "ORDER"
    symbol = str(order.get("symbol", "") or "UNKNOWN").upper()
    qty = float(order.get("qty", 0.0) or 0.0)
    filled_qty = float(order.get("filled_qty", 0.0) or 0.0)
    label = _order_status_label(status)

    lines = [
        f"**{symbol}**",
        f"{side} | **{label}**",
        f"Requested: {qty:g} shares",
    ]
    if filled_qty > 0:
        lines.append(f"Filled so far: {filled_qty:g} shares")
    if include_order_id:
        lines.extend(
            [
                "",
                "Order ID",
                f"`{str(order.get('id', ''))[:64]}`",
            ]
        )
    return lines


def _order_batch_color(orders: list[dict[str, Any]]) -> int:
    statuses = {
        _normalize_order_status(str(order.get("status", ""))) for order in orders
    } - {""}
    sides = {
        _normalize_order_side(str(order.get("side", ""))) for order in orders
    } - {""}
    if statuses & _FAILED_STATUSES:
        return _COLOR_ERR
    if statuses and statuses <= _PENDING_STATUSES:
        return _COLOR_PENDING
    if statuses and statuses <= _FILLED_STATUSES and len(sides) == 1:
        side = next(iter(sides))
        return _COLOR_SELL if side == "SELL" else _COLOR_BUY
    return _COLOR_NOTICE


class DiscordNotifier:
    """Discord webhook: per-trade alerts, periodic balance + delta, optional full cycle report."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.discord_webhook_url.strip()
        self._min_interval = max(0, int(settings.discord_min_interval_sec))
        self._last_sent = 0.0
        self._bootstrapped_order_scan = False
        self._bootstrapped_open_order_snapshot = False

    @classmethod
    def from_settings(cls, settings: Settings) -> DiscordNotifier | None:
        if not settings.discord_webhook_url.strip():
            return None
        return cls(settings)

    def _throttled(self, *, force: bool = False) -> bool:
        gap = _FORCE_POST_GAP_SEC if force else float(self._min_interval)
        if gap <= 0:
            return False
        return (time.monotonic() - self._last_sent) < gap

    def _post(self, payload: dict[str, Any], *, force: bool = False) -> bool:
        if self._throttled(force=force):
            log.debug(
                "Discord notify skipped (min gap %.1fs, force=%s)",
                _FORCE_POST_GAP_SEC if force else self._min_interval,
                force,
            )
            return False
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "DayTradeBot/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status not in (200, 204):
                    log.warning("Discord webhook returned HTTP %s", resp.status)
                    return False
        except urllib.error.HTTPError as e:
            log.warning("Discord webhook HTTP error: %s %s", e.code, e.reason)
            return False
        except Exception:
            log.exception("Discord webhook request failed")
            return False
        self._last_sent = time.monotonic()
        return True

    def send_test(self, settings: Settings) -> bool:
        embed = {
            "title": "Webhook connected",
            "description": (
                "DayTradeBot can post to this channel.\n\n"
                "**Trades** - each buy or sell\n"
                "**Balance** - every 8 hours with change vs last update\n"
                "**Session** - market open/close (white), holidays (yellow)\n"
                "**Errors** - if a cycle crashes\n\n"
                "Full cycle reports are off unless you enable them in `.env`."
            ),
            "color": _COLOR_NOTICE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        return self._post({"embeds": [embed]}, force=True)

    def send_failure(self, settings: Settings, broker: AlpacaBroker, err: BaseException) -> None:
        embed = {
            "title": "Cycle failed",
            "description": (
                "The bot hit an error and did not finish this cycle.\n\n"
                f"**{type(err).__name__}**\n"
                f"```\n{err}\n```"
            )[:4000],
            "color": _COLOR_ERR,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings, et_line=now_et().strftime("%Y-%m-%d %H:%M ET")),
        }
        self._post({"embeds": [embed]}, force=True)

    def send_trade(
        self, settings: Settings, symbol: str, side: str, qty: float, order_id: str
    ) -> None:
        side_u = side.upper()
        action = "Sold" if side_u == "SELL" else "Bought"
        embed = {
            "title": side_u,
            "description": (
                f"**{symbol}**\n\n"
                f"{action} **{qty:g}** shares\n\n"
                f"Order ID\n`{order_id[:64]}`"
            ),
            "color": _COLOR_SELL if side_u == "SELL" else _COLOR_BUY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        self._post({"embeds": [embed]}, force=True)
        self._remember_order_status(settings, order_id, "submitted")

    def _remember_order_status(self, settings: Settings, order_id: str, status: str) -> None:
        path = _order_state_path(settings)
        state = _load_order_state(path)
        state[str(order_id)] = _normalize_order_status(status)
        _save_order_state(path, state)

    def send_order_update(self, settings: Settings, order: dict[str, Any]) -> None:
        self.send_order_updates(settings, [order])

    def send_order_updates(self, settings: Settings, orders: list[dict[str, Any]]) -> None:
        if not orders:
            return
        if len(orders) == 1:
            order = orders[0]
            side = _normalize_order_side(str(order.get("side", ""))) or "ORDER"
            title = f"{side} update"
            description = "\n".join(_order_update_lines(order, include_order_id=True))
        else:
            title = f"Order updates ({len(orders)})"
            blocks = [
                "\n".join(_order_update_lines(order, include_order_id=False))
                for order in orders
            ]
            description = "\n\n".join(blocks)[:4000]
        embed = {
            "title": title,
            "description": description,
            "color": _order_batch_color(orders),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        self._post({"embeds": [embed]}, force=True)

    def maybe_send_order_updates(self, settings: Settings, broker: AlpacaBroker) -> None:
        path = _order_state_path(settings)
        state = _load_order_state(path)
        after = datetime.now(timezone.utc) - timedelta(days=2)
        try:
            orders = broker.get_recent_orders(after=after, limit=200)
        except Exception:
            log.exception("Discord order updates: could not load recent orders")
            return

        changed = False
        first_scan = not self._bootstrapped_order_scan
        now = datetime.now(timezone.utc)
        updates_to_send: list[dict[str, Any]] = []
        for order in sorted(
            (o for o in orders if _is_bot_order(o)),
            key=lambda o: (
                str(o.get("submitted_at", "") or ""),
                str(o.get("updated_at", "") or ""),
                str(o.get("id", "") or ""),
            ),
        ):
            order_id = str(order.get("id", "") or "")
            if not order_id:
                continue
            status = _normalize_order_status(str(order.get("status", "")))
            if not status:
                continue
            prev = _normalize_order_status(state.get(order_id, ""))
            updated_at = _parse_order_dt(str(order.get("updated_at", "") or ""))
            recent_enough = bool(updated_at and (now - updated_at) <= timedelta(hours=24))

            should_notify = False
            if prev and prev != status:
                should_notify = True
            elif not prev:
                if first_scan:
                    should_notify = recent_enough and status in _FINAL_STATUSES
                else:
                    should_notify = status in (_PENDING_STATUSES | _FINAL_STATUSES)

            if should_notify:
                updates_to_send.append(order)
            if prev != status:
                changed = True
            state[order_id] = status

        self._bootstrapped_order_scan = True
        if changed:
            _save_order_state(path, state)
        if updates_to_send:
            self.send_order_updates(settings, updates_to_send)

    def maybe_send_open_order_snapshot(self, settings: Settings, broker: AlpacaBroker) -> None:
        path = _open_order_snapshot_path(settings)
        prev = _load_open_order_snapshot(path)
        try:
            orders = broker.get_open_orders()
        except Exception:
            log.exception("Discord open-order snapshot: could not load recent orders")
            return

        active_orders = [
            o
            for o in orders
            if _is_bot_order(o)
            and _normalize_order_status(str(o.get("status", ""))) in _ACTIVE_ORDER_STATUSES
        ]
        active_orders.sort(
            key=lambda o: (
                str(o.get("submitted_at", "") or ""),
                str(o.get("updated_at", "") or ""),
                str(o.get("id", "") or ""),
            )
        )

        current = {
            str(o.get("id", "") or ""): (
                f"{_normalize_order_status(str(o.get('status', '')))}|"
                f"{float(o.get('filled_qty', 0.0) or 0.0):g}"
            )
            for o in active_orders
            if str(o.get("id", "") or "")
        }

        if current == prev:
            self._bootstrapped_open_order_snapshot = True
            return

        # After a restart, only re-announce open orders if the saved snapshot changed.
        if not self._bootstrapped_open_order_snapshot and active_orders:
            blocks = [_order_snapshot_line(order) for order in active_orders]
            embed = {
                "title": f"Open orders ({len(active_orders)})",
                "description": "\n\n".join(blocks)[:4000],
                "color": _COLOR_PENDING,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": _footer(settings),
            }
            self._post({"embeds": [embed]}, force=True)
        elif prev and not current:
            embed = {
                "title": "Open orders cleared",
                "description": "No active pending orders remain.",
                "color": _COLOR_NOTICE,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": _footer(settings),
            }
            self._post({"embeds": [embed]}, force=True)

        self._bootstrapped_open_order_snapshot = True
        _save_open_order_snapshot(path, current)

    def _send_session(
        self, settings: Settings, title: str, description: str, color: int
    ) -> None:
        clock = now_et()
        embed = {
            "title": title,
            "description": description[:4000],
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings, et_line=clock.strftime("%Y-%m-%d %H:%M ET")),
        }
        self._post({"embeds": [embed]}, force=True)

    def send_market_open(self, settings: Settings, session: dict[str, Any]) -> None:
        d = session["date"]
        body = (
            f"The regular session is **open** for trading.\n\n"
            f"**Today**\n{format_day_long(d)}\n\n"
            f"**Session hours**\n{format_session_hours(session)}"
        )
        self._send_session(settings, "Market open", body, _COLOR_SESSION)

    def send_market_close(
        self,
        settings: Settings,
        session: dict[str, Any],
        next_session: dict[str, Any] | None,
    ) -> None:
        d = session["date"]
        lines = [
            "The regular session has **closed**.",
            "",
            f"**Today**\n{format_day_long(d)}",
            f"**Session hours**\n{format_session_hours(session)}",
        ]
        if next_session:
            lines.extend(
                [
                    "",
                    "**Next session**",
                    format_day_long(next_session["date"]),
                    format_session_hours(next_session),
                ]
            )
        self._send_session(settings, "Market close", "\n".join(lines), _COLOR_SESSION)

    def send_market_closed_today(self, settings: Settings, day_label: str) -> None:
        body = (
            "The market is **closed** today.\n\n"
            f"**Date**\n{day_label}\n\n"
            "No regular session - plan for a non-trading day."
        )
        self._send_session(settings, "Market closed today", body, _COLOR_HOLIDAY)

    def send_upcoming_holiday(
        self,
        settings: Settings,
        hol: date,
        days_until: int,
        resume: dict[str, Any] | None,
    ) -> None:
        when = "tomorrow" if days_until == 1 else f"in **{days_until}** days"
        lines = [
            f"A market holiday is coming up {when}.",
            "",
            f"**Closed**\n{format_day_long(hol)}",
        ]
        if resume:
            lines.extend(
                [
                    "",
                    "**Trading resumes**",
                    format_day_long(resume["date"]),
                    format_session_hours(resume),
                ]
            )
        self._send_session(settings, "Upcoming holiday", "\n".join(lines), _COLOR_HOLIDAY)

    def send_notice(self, settings: Settings, title: str, body: str) -> None:
        embed = {
            "title": title,
            "description": body[:4000],
            "color": _COLOR_NOTICE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        self._post({"embeds": [embed]}, force=True)

    def maybe_send_balance_report(self, settings: Settings, broker: AlpacaBroker) -> None:
        interval = int(settings.discord_balance_interval_sec)
        if interval <= 0:
            return

        snap_path = _balance_snapshot_path(settings)
        prev = _load_balance_snapshot(snap_path)
        now = datetime.now(timezone.utc)

        if prev is not None:
            try:
                last_at = datetime.fromisoformat(str(prev.get("at_utc", "")))
                if last_at.tzinfo is None:
                    last_at = last_at.replace(tzinfo=timezone.utc)
                elapsed = (now - last_at).total_seconds()
            except Exception:
                elapsed = interval
            if elapsed < interval:
                return

        try:
            acct = broker.get_account()
            positions = broker.get_open_positions()
        except Exception:
            log.exception("Discord balance report: could not load account")
            return

        equity = float(acct["equity"])
        cash = float(acct["cash"])
        prev_equity = float(prev["equity"]) if prev and prev.get("equity") is not None else None
        hours = max(interval / 3600.0, 0.1)

        lines = [
            f"**Account equity**\n${equity:,.2f}",
            f"**Cash**\n${cash:,.2f}",
            "",
        ]

        if prev_equity is not None and prev_equity > 0:
            delta = equity - prev_equity
            delta_pct = (equity / prev_equity - 1.0) * 100.0
            lines.extend(
                [
                    f"**Change since last update (~{hours:.0f}h)**",
                    f"${delta:+,.2f}  ({delta_pct:+.2f}%)",
                    "",
                    f"**Previous equity**\n${prev_equity:,.2f}",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "**Change since last update**",
                    "First snapshot - the next balance post will show how much changed.",
                    "",
                ]
            )

        stats = et_day_stats(settings.risk_state_dir, equity)
        dd = stats.get("dd_pct")
        if dd is not None:
            lines.extend([f"**Today (ET)**\n{dd:+.2f}%", ""])

        lines.append("**Positions**\n" + _format_positions(positions))

        clock = now_et()
        embed = {
            "title": "Balance update",
            "description": "\n".join(lines)[:4000],
            "color": _COLOR_BALANCE,
            "timestamp": now.isoformat(),
            "footer": _footer(settings, et_line=clock.strftime("%Y-%m-%d %H:%M ET")),
        }
        if self._post({"embeds": [embed]}, force=True):
            _save_balance_snapshot(snap_path, equity)

    def send_cycle_report(
        self,
        settings: Settings,
        broker: AlpacaBroker,
        ctx: CycleContext,
    ) -> None:
        try:
            acct = broker.get_account()
            positions = broker.get_open_positions()
        except Exception:
            log.exception("Discord report: could not load account/positions")
            return

        equity = float(acct["equity"])
        stats = et_day_stats(settings.risk_state_dir, equity)
        dd = stats.get("dd_pct")
        color = _COLOR_ERR if stats.get("halted") else _COLOR_CYCLE

        lines = [
            f"**Account equity**\n${equity:,.2f}",
            f"**Cash**\n${float(acct['cash']):,.2f}",
            f"**Buying power**\n${float(acct['buying_power']):,.2f}",
            "",
        ]

        if stats.get("baseline") is not None and dd is not None:
            lines.extend([f"**Today (ET)**\n{dd:+.2f}%", ""])

        if stats.get("halted"):
            lines.extend(["**Risk**\nTrading halted - daily loss limit hit", ""])
        elif ctx.risk is not None:
            gate = "Allowed" if ctx.risk.allow_new_trades else "Blocked"
            reasons = ", ".join(ctx.risk.reasons) if ctx.risk.reasons else "none"
            lines.extend([f"**New entries**\n{gate}\n{reasons}", ""])

        if ctx.zones:
            lines.extend([f"**Killzones**\n{', '.join(ctx.zones)}", ""])
        if ctx.flat_reason:
            lines.extend([f"**Session**\nFlat: {ctx.flat_reason}", ""])

        lines.append("**Positions**\n" + _format_positions(positions))

        clock = now_et()
        embed = {
            "title": "Cycle summary",
            "description": "\n".join(lines)[:4000],
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings, et_line=clock.strftime("%Y-%m-%d %H:%M ET")),
        }
        self._post({"embeds": [embed]})


def wire_broker_discord(broker: AlpacaBroker, settings: Settings, discord: DiscordNotifier) -> None:
    if settings.discord_on_trade:
        discord_ref = discord

        def _on_trade(side: str, qty: float, symbol: str, order_id: str) -> None:
            discord_ref.send_trade(settings, symbol, side, qty, order_id)

        broker.set_trade_callback(_on_trade)
    else:
        broker.set_trade_callback(None)
