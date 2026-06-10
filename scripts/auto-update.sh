#!/usr/bin/env bash
# Safe repo update + smoke check + verified restart for the mini PC runtime.
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG="$ROOT/logs/auto-update.log"
LOCK_FILE="$ROOT/.state/auto-update.lock"
FAIL_KEY_FILE="$ROOT/.state/auto-update.last-failure"
STATUS_FILE="$ROOT/.state/auto-update-status.json"
USER_UID="$(id -u)"
OLD=""
REMOTE=""
NEW=""
FAILED_STAGE=""
FAILED_MESSAGE=""

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$USER_UID}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

mkdir -p "$ROOT/logs" "$ROOT/.state"
cd "$ROOT"

log() { echo "$(date -Is) $*" | tee -a "$LOG"; }
systemctl_user() { /usr/bin/systemctl --user "$@"; }

notify_discord() {
  local title="$1"
  local body="$2"
  local color="${3:-blue}"
  if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    return 0
  fi
  "$ROOT/.venv/bin/python" "$ROOT/scripts/send-discord-notice.py" \
    --title "$title" \
    --body "$body" \
    --color "$color" \
    --footer "mini-pc auto-update" >>"$LOG" 2>&1 || true
}

remember_failure_key() {
  printf '%s\n' "$1" > "$FAIL_KEY_FILE"
}

write_update_status() {
  python3 - "$STATUS_FILE" "$1" "$2" "$3" "$4" "$5" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
status = sys.argv[2]
stage = sys.argv[3]
current = sys.argv[4]
target = sys.argv[5]
message = sys.argv[6]
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".tmp")
tmp.write_text(
    json.dumps(
        {
            "status": status,
            "stage": stage,
            "current_commit": current,
            "target_commit": target,
            "message": message,
            "at_utc": datetime.now(timezone.utc).isoformat(),
        },
        indent=2,
    ),
    encoding="utf-8",
)
tmp.replace(path)
PY
}

notify_failure_once() {
  local key="$1"
  local body="$2"
  local prev=""
  if [[ -f "$FAIL_KEY_FILE" ]]; then
    prev="$(tr -d '[:space:]' < "$FAIL_KEY_FILE")"
  fi
  if [[ "$prev" == "$key" ]]; then
    return
  fi
  remember_failure_key "$key"
  notify_discord "Deploy failed" "$body" red
}

clear_failure_key() {
  rm -f "$FAIL_KEY_FILE"
}

failure_body() {
  local stage="$1"
  local current="$2"
  local target="$3"
  local detail="$4"
  cat <<EOF
Auto-update failed on the mini PC.

**Stage**
$stage

**Current commit**
\`$current\`

**Target commit**
\`$target\`

**Details**
$detail
EOF
}

success_body() {
  local current="$1"
  local new="$2"
  local service_line="$3"
  cat <<EOF
New code was deployed on the mini PC.

**Previous commit**
\`$current\`

**Current commit**
\`$new\`

**Service**
$service_line
EOF
}

fail_update() {
  local stage="$1"
  local log_message="$2"
  local detail="$3"
  local current="${OLD:-unknown}"
  local target="${REMOTE:-unknown}"
  log "ERROR: $log_message"
  write_update_status fail "$stage" "$current" "$target" "$detail"
  notify_failure_once \
    "${stage}|${current}|${target}" \
    "$(failure_body "$stage" "$current" "$target" "$detail")"
  exit 1
}

on_error() {
  local exit_code=$?
  local stage="${FAILED_STAGE:-unknown}"
  local current="${OLD:-unknown}"
  local target="${REMOTE:-unknown}"
  local msg="${FAILED_MESSAGE:-See logs/auto-update.log on the mini PC.}"
  write_update_status fail "$stage" "$current" "$target" "$msg"
  notify_failure_once \
    "${stage}|${current}|${target}" \
    "$(failure_body "$stage" "$current" "$target" "$msg")"
  exit "$exit_code"
}

trap on_error ERR

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another auto-update is already running; skipping."
  exit 0
fi

stash_if_dirty() {
  if [[ -n "$(git status --porcelain)" ]]; then
    local stash_msg="mini-pc auto-stash $(date -Iseconds)"
    git stash push -u -m "$stash_msg" >>"$LOG" 2>&1
    log "Stashed local changes before pull: $stash_msg"
  fi
}

OLD="$(git rev-parse HEAD)"

FAILED_STAGE="git-fetch"
FAILED_MESSAGE="Could not fetch the latest code from GitHub."
if ! git fetch origin >>"$LOG" 2>&1; then
  fail_update "$FAILED_STAGE" "git fetch failed" "$FAILED_MESSAGE"
fi

REMOTE="$(git rev-parse origin/main)"
if [[ "$OLD" == "$REMOTE" ]]; then
  write_update_status noop "no-change" "$OLD" "$REMOTE" "No new commit available."
  clear_failure_key
  exit 0
fi

stash_if_dirty

FAILED_STAGE="git-pull"
FAILED_MESSAGE="Git fetch saw a new commit, but the fast-forward pull failed."
if ! git pull --ff-only origin main >>"$LOG" 2>&1; then
  fail_update "$FAILED_STAGE" "git pull failed" "$FAILED_MESSAGE"
fi

NEW="$(git rev-parse HEAD)"
chmod +x scripts/*.sh scripts/send-discord-notice.py 2>/dev/null || true

FAILED_STAGE="dependency-sync"
FAILED_MESSAGE="The repo updated, but dependency installation did not finish cleanly."
if ! "$ROOT/scripts/ensure-venv.sh" >>"$LOG" 2>&1; then
  fail_update "$FAILED_STAGE" "dependency sync failed" "$FAILED_MESSAGE"
fi

has_alpaca_keys() {
  grep -qE '^ALPACA_API_KEY=.+' "$ROOT/.env" 2>/dev/null \
    && grep -qE '^ALPACA_SECRET_KEY=.+' "$ROOT/.env" 2>/dev/null
}

log "Updated $OLD -> $NEW"

if ! has_alpaca_keys; then
  log "Alpaca keys missing; skipping smoke check and service restart"
  write_update_status ok "awaiting-keys" "$OLD" "$NEW" "Updated cleanly; add Alpaca keys then enable daytradebot.service."
  clear_failure_key
  notify_discord "Deploy applied" "$(success_body "$OLD" "$NEW" "Code updated. Alpaca keys not set yet — service not restarted.")" blue
  exit 0
fi

FAILED_STAGE="smoke-check"
FAILED_MESSAGE="The repo updated, but the non-trading smoke check failed."
if ! "$ROOT/scripts/smoke-check.sh" >>"$LOG" 2>&1; then
  fail_update "$FAILED_STAGE" "smoke check failed; update applied on disk but service was not restarted" "$FAILED_MESSAGE"
fi

if systemctl_user is-active --quiet daytradebot.service 2>/dev/null; then
  log "Restarting daytradebot.service for new code"
  FAILED_STAGE="service-restart"
  FAILED_MESSAGE="The repo updated, but daytradebot.service did not restart cleanly."
  if ! systemctl_user restart daytradebot.service >>"$LOG" 2>&1; then
    fail_update "$FAILED_STAGE" "service restart failed" "$FAILED_MESSAGE"
  fi
  sleep 5
  FAILED_STAGE="service-health"
  FAILED_MESSAGE="The repo updated, but daytradebot.service did not come back healthy after restart."
  if ! systemctl_user is-active --quiet daytradebot.service 2>/dev/null; then
    fail_update "$FAILED_STAGE" "service did not come back healthy after restart" "$FAILED_MESSAGE"
  fi
  log "Restart successful"
  write_update_status ok "service-healthy" "$OLD" "$NEW" "Updated and restarted cleanly."
  clear_failure_key
  notify_discord "Deploy applied" "$(success_body "$OLD" "$NEW" "Restarted and healthy.")" blue
else
  log "Bot service not running; update applied without restart"
  write_update_status ok "service-skipped" "$OLD" "$NEW" "Updated cleanly; bot service was not running."
  clear_failure_key
  notify_discord "Deploy applied" "$(success_body "$OLD" "$NEW" "Bot service was not running, so no restart was needed.")" blue
fi
