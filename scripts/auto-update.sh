#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UNIT="daytradebot.service"
before="$(git rev-parse HEAD 2>/dev/null || echo none)"
git pull --ff-only origin main
after="$(git rev-parse HEAD)"
if [[ "$before" != "$after" ]]; then
  "$ROOT/scripts/ensure-venv.sh"
  systemctl --user restart "$UNIT" 2>/dev/null || true
  echo "Updated $before -> $after (service restarted if installed)"
else
  echo "Already up to date ($after)"
fi
