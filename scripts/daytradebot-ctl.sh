#!/usr/bin/env bash
set -euo pipefail
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT="daytradebot.service"
CMD="${1:-}"

usage() {
  cat <<EOF
DayTradeBot control (systemd user service)

  daytradebot-ctl on|off|restart|status|update|smoke|logs|enable|disable

Repo: $ROOT
EOF
}

case "$CMD" in
  on|start)
    systemctl --user start "$UNIT"
    systemctl --user status "$UNIT" --no-pager || true
    ;;
  off|stop)
    systemctl --user stop "$UNIT"
    echo "DayTradeBot stopped."
    ;;
  restart)
    systemctl --user restart "$UNIT"
    systemctl --user status "$UNIT" --no-pager || true
    ;;
  status)
    systemctl --user status "$UNIT" --no-pager || true
    ;;
  update)
    exec "$ROOT/scripts/auto-update.sh"
    ;;
  smoke)
    exec "$ROOT/scripts/smoke-check.sh"
    ;;
  logs)
    touch "$ROOT/logs/daytradebot.log"
    tail -f "$ROOT/logs/daytradebot.log"
    ;;
  enable)
    systemctl --user enable "$UNIT"
    loginctl enable-linger "$USER" 2>/dev/null || true
    echo "DayTradeBot will start on boot."
    ;;
  disable)
    systemctl --user disable "$UNIT"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    usage >&2
    exit 1
    ;;
esac
