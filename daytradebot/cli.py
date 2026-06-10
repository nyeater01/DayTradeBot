"""Command-line entry: `python -m daytradebot` from the project folder."""
from __future__ import annotations

import argparse
import logging

from daytradebot.alpaca_broker import AlpacaBroker
from daytradebot.config import Settings, configure_logging
from daytradebot.discord_notify import DiscordNotifier
from daytradebot.runner import run_loop

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="DayTradeBot (Alpaca intraday)")
    parser.add_argument("--once", action="store_true", help="Single cycle then exit")
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging")
    parser.add_argument(
        "--discord-test",
        action="store_true",
        help="Send test message to DAYTRADEBOT_DISCORD_WEBHOOK_URL and exit",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.discord_test:
        if not settings.discord_webhook_url:
            raise ValueError("Set DAYTRADEBOT_DISCORD_WEBHOOK_URL in .env first.")
        configure_logging(settings, logging.INFO)
        ok = DiscordNotifier(settings).send_test(settings)
        if not ok:
            raise SystemExit("Discord test message failed.")
        log.info("Discord test message sent.")
        return

    settings.validate()
    configure_logging(settings, logging.DEBUG if args.verbose else logging.INFO)

    mode = "paper" if settings.paper else "LIVE"
    log.warning(
        "Starting DayTradeBot mode=%s symbols=%s killzones=%s",
        mode,
        ",".join(settings.symbols),
        ",".join(settings.killzones),
    )
    if not settings.paper:
        log.critical("LIVE trading enabled — verify kill switch and daily loss limit.")

    broker = AlpacaBroker(
        settings.api_key,
        settings.secret_key,
        paper=settings.paper,
        retry_attempts=settings.alpaca_retry_attempts,
        retry_base_delay_sec=settings.alpaca_retry_base_delay_sec,
    )
    run_loop(settings, broker, once=args.once)


if __name__ == "__main__":
    main()
