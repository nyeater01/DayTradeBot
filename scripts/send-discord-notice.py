#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_COLOR_MAP = {
    "blue": 0x3498DB,
    "red": 0xE74C3C,
    "green": 0x2ECC71,
    "yellow": 0xF1C40F,
    "white": 0xEAEAEA,
    "purple": 0x9B59B6,
    "orange": 0xF39C12,
    "gray": 0x95A5A6,
}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'").strip('"')
    return data


def _color_value(raw: str) -> int:
    text = raw.strip().lower()
    if text in _COLOR_MAP:
        return _COLOR_MAP[text]
    if text.startswith("0x"):
        return int(text, 16)
    return int(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Discord webhook notice from .env.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--color", default="blue")
    parser.add_argument("--footer", default="auto-update")
    args = parser.parse_args()

    env = _load_env(_root() / ".env")
    webhook = env.get("DAYTRADEBOT_DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return 0

    mode = "Paper" if env.get("ALPACA_TRADING_MODE", "paper").strip().lower() != "live" else "LIVE"
    payload = {
        "embeds": [
            {
                "title": args.title,
                "description": args.body[:4000],
                "color": _color_value(args.color),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": f"{mode} | {args.footer}"},
            }
        ]
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "DayTradeBot/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status not in (200, 204):
                print(f"Discord webhook returned HTTP {resp.status}", file=sys.stderr)
                return 1
    except urllib.error.HTTPError as exc:
        print(f"Discord webhook HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Discord webhook request failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
