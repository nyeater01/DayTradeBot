from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings
from daytradebot.risk import RiskDecision
from daytradebot.session_policy import now_et

log = logging.getLogger(__name__)

_COLOR_BUY = 0x2ECC71
_COLOR_SELL = 0xF39C12
_COLOR_BALANCE = 0x9B59B6
_COLOR_ERR = 0xE74C3C
_COLOR_NOTICE = 0x3498DB
_COLOR_CYCLE = 0x95A5A6
_FORCE_POST_GAP_SEC = 1.0


@dataclass(frozen=True)
class CycleContext:
    zones: tuple[str, ...] = ()
    flat_reason: str = ""
    risk: RiskDecision | None = None
    signals: dict[str, Any] | None = None


def _mode_label(settings: Settings) -> str:
    return "Paper" if settings.paper else "LIVE"


def _footer(settings: Settings, *, et_line: str | None = None) -> dict[str, str]:
    parts = ["DayTradeBot", _mode_label(settings)]
    if et_line:
        parts.append(et_line)
    return {"text": " | ".join(parts)}


def _format_positions(positions: list[dict[str, Any]]) -> str:
    if not positions:
        return "Flat."
    blocks: list[str] = []
    for p in sorted(positions, key=lambda x: str(x.get("symbol", ""))):
        sym = p["symbol"]
        qty = float(p["qty"])
        upl = float(p.get("unrealized_pl", 0.0))
        blocks.append(f"**{sym}** qty={qty:g} unrealized=${upl:+,.2f}")
    return "\n".join(blocks)


class DiscordNotifier:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.discord_webhook_url.strip()
        self._min_interval = max(0, int(settings.discord_min_interval_sec))

    @classmethod
    def from_settings(cls, settings: Settings) -> DiscordNotifier | None:
        if not settings.discord_webhook_url.strip():
            return None
        return cls(settings)

    def _post(self, payload: dict[str, Any], *, force: bool = False) -> bool:
        gap = _FORCE_POST_GAP_SEC if force else float(self._min_interval)
        if gap > 0 and (time.monotonic() - getattr(self, "_last_sent", 0.0)) < gap:
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
            "title": "DayTradeBot webhook connected",
            "description": (
                "Intraday bot using **VWAP**, **volume profile**, **pivots**, and **ICT killzones**.\n\n"
                "Trades and errors post here. StockBot uses a separate webhook."
            ),
            "color": _COLOR_NOTICE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        return self._post({"embeds": [embed]}, force=True)

    def send_failure(self, settings: Settings, err: BaseException) -> None:
        embed = {
            "title": "Cycle failed",
            "description": f"**{type(err).__name__}**\n```\n{err}\n```"[:4000],
            "color": _COLOR_ERR,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings, et_line=now_et().strftime("%Y-%m-%d %H:%M ET")),
        }
        self._post({"embeds": [embed]}, force=True)

    def send_trade(
        self, settings: Settings, symbol: str, side: str, qty: float, order_id: str
    ) -> None:
        side_u = side.upper()
        embed = {
            "title": side_u,
            "description": (
                f"**{symbol}**\n\n"
                f"{'Sold' if side_u == 'SELL' else 'Bought'} **{qty:g}** shares\n\n"
                f"Order ID\n`{order_id[:64]}`"
            ),
            "color": _COLOR_SELL if side_u == "SELL" else _COLOR_BUY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings),
        }
        self._post({"embeds": [embed]}, force=True)

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
            log.exception("Discord report: could not load account")
            return

        lines = [
            f"**Equity** ${float(acct['equity']):,.2f}",
            f"**Killzones** {', '.join(ctx.zones) if ctx.zones else 'none'}",
        ]
        if ctx.flat_reason:
            lines.append(f"**Flat reason** {ctx.flat_reason}")
        if ctx.risk is not None:
            gate = "OK" if ctx.risk.allow_new_trades else "BLOCKED"
            lines.append(f"**New entries** {gate} ({', '.join(ctx.risk.reasons)})")
        if ctx.signals:
            for sym, sig in sorted(ctx.signals.items()):
                lines.append(
                    f"**{sym}** {sig.get('action')} score={sig.get('score')} "
                    f"pos={sig.get('pos')} ({', '.join(sig.get('reasons', ()))})"
                )
        lines.append("")
        lines.append("**Positions**\n" + _format_positions(positions))

        embed = {
            "title": "Intraday cycle",
            "description": "\n".join(lines)[:4000],
            "color": _COLOR_CYCLE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": _footer(settings, et_line=now_et().strftime("%Y-%m-%d %H:%M ET")),
        }
        self._post({"embeds": [embed]})


def wire_broker_discord(broker: AlpacaBroker, settings: Settings, discord: DiscordNotifier) -> None:
    if not settings.discord_on_trade:
        broker.set_trade_callback(None)
        return

    def _on_trade(side: str, qty: float, symbol: str, order_id: str) -> None:
        discord.send_trade(settings, symbol, side, qty, order_id)

    broker.set_trade_callback(_on_trade)
