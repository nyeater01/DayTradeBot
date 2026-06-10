from __future__ import annotations

import logging
import time

from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings
from daytradebot.discord_notify import CycleContext, DiscordNotifier, wire_broker_discord
from daytradebot.engine_intraday import run_intraday_cycle
from daytradebot.risk import RiskController
from daytradebot.session_policy import (
    in_regular_session,
    now_et,
    should_flat_for_session,
)

log = logging.getLogger(__name__)


def run_cycle(settings: Settings, broker: AlpacaBroker, risk_ctrl: RiskController) -> CycleContext:
    acct = broker.get_account()
    clock = now_et()
    risk = risk_ctrl.evaluate(float(acct["equity"]), str(acct["status"]))
    if not risk.allow_new_trades:
        log.warning("Risk gate: new entries blocked (%s)", ", ".join(risk.reasons))

    flat_reason = ""
    if not in_regular_session(clock, settings.session_open, settings.session_close):
        flat_reason = "outside_regular_session"
    else:
        should_flat, reason = should_flat_for_session(
            clock,
            settings.killzones,
            settings.flat_outside_killzone,
            settings.flat_at_session_close,
            settings.session_close,
        )
        if should_flat:
            flat_reason = reason

    summary = run_intraday_cycle(settings, broker, risk, flat_reason, risk_ctrl)
    return CycleContext(
        zones=tuple(summary.get("zones") or ()),
        flat_reason=str(summary.get("flat_reason") or flat_reason),
        risk=risk,
        signals=summary.get("signals"),
    )


def run_loop(settings: Settings, broker: AlpacaBroker, once: bool) -> None:
    risk_ctrl = RiskController(settings)
    discord = DiscordNotifier.from_settings(settings)
    if discord:
        wire_broker_discord(broker, settings, discord)

    while True:
        ctx = CycleContext()
        ok = False
        try:
            ctx = run_cycle(settings, broker, risk_ctrl)
            ok = True
        except Exception as exc:
            log.exception("Cycle failed")
            if discord:
                try:
                    discord.send_failure(settings, exc)
                except Exception:
                    log.exception("Discord failure alert failed")
        if discord and ok and settings.discord_cycle_report:
            try:
                discord.send_cycle_report(settings, broker, ctx)
            except Exception:
                log.exception("Discord cycle report failed")
        if once:
            break
        log.info("Sleeping %s seconds", settings.poll_seconds)
        time.sleep(settings.poll_seconds)
