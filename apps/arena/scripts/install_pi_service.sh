#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" = 0 ]; then echo 'Run as regular Pi user, not root.' >&2; exit 1; fi
MODE="${1:-install}"
if [[ "$MODE" != install && "$MODE" != --units-only ]]; then echo 'Usage: install_pi_service.sh [--units-only]' >&2; exit 1; fi
USER_NAME="$(id -un)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$USER_NAME" != [a-z_]* || "$USER_NAME" == *[!a-z0-9_-]* ]]; then echo 'Unsupported username' >&2; exit 1; fi
if [ "$HOME" != "/home/$USER_NAME" ] || [ "$ROOT" != "$HOME/llm-trading-arena/apps/arena" ]; then
  echo 'Expected /home/<user>/llm-trading-arena/apps/arena' >&2; exit 1
fi
if [ ! -f "$ROOT/.env" ]; then echo 'Missing application .env; copy .env.example first.' >&2; exit 1; fi
DATA="$HOME/.local/share/llm-trading-arena"
export LLM_TRADING_ARENA_DATA_DIR="$DATA"
umask 077
mkdir -p "$DATA/backups" "$DATA/pre-update"
chmod 700 "$DATA" "$DATA/backups" "$DATA/pre-update"
chmod 600 "$ROOT/.env"
cd "$ROOT"
if [ "$MODE" = install ]; then
  if systemctl is-active --quiet llm-trading-arena.service; then
    echo 'Service already running; use deploy_release.py for updates.' >&2; exit 1
  fi
  python3 -m unittest discover -s tests -v
  python3 scripts/preflight.py
  python3 scripts/backup_db.py "$DATA/live_v03_bitvavo.sqlite3" "$DATA/pre-update/install-$(date -u +%Y%m%dT%H%M%S)-$$.sqlite3"
fi
TMP_UNITS="$(mktemp -d)"
trap 'rm -f "$TMP_UNITS/llm-trading-arena.service" "$TMP_UNITS/llm-trading-arena-backup.service" "$TMP_UNITS/llm-trading-arena-backup.timer"; rmdir "$TMP_UNITS"' EXIT
for UNIT in llm-trading-arena.service llm-trading-arena-backup.service llm-trading-arena-backup.timer; do
  sed "s/__PI_USER__/$USER_NAME/g" "$ROOT/deploy/$UNIT" > "$TMP_UNITS/$UNIT"
done
systemd-analyze verify "$TMP_UNITS/llm-trading-arena.service" "$TMP_UNITS/llm-trading-arena-backup.service" "$TMP_UNITS/llm-trading-arena-backup.timer"
for UNIT in llm-trading-arena.service llm-trading-arena-backup.service llm-trading-arena-backup.timer; do
  sudo install -m 644 "$TMP_UNITS/$UNIT" "/etc/systemd/system/$UNIT"
done
sudo install -m 644 "$ROOT/deploy/journald@llm-trading-arena.conf" /etc/systemd/journald@llm-trading-arena.conf
sudo systemctl daemon-reload
sudo systemctl try-restart systemd-journald@llm-trading-arena.service
if [ "$MODE" = install ]; then
  sudo systemctl enable --now llm-trading-arena.service llm-trading-arena-backup.timer
  sudo systemctl --no-pager status llm-trading-arena.service
fi
