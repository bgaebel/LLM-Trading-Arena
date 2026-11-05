#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" = 0 ]; then echo 'Run as regular Pi user, not root.' >&2; exit 1; fi
USER_NAME="$(id -un)"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$ROOT" != "$HOME/llm-trading-arena/apps/arena" ]; then
  echo "Expected code directory $HOME/llm-trading-arena/apps/arena, got $ROOT" >&2; exit 1
fi
if [ ! -f "$ROOT/.env" ]; then echo 'Missing .env file; copy .env.example and configure first.' >&2; exit 1; fi
if ! command -v python3 >/dev/null; then echo 'Python 3 not installed.' >&2; exit 1; fi
mkdir -p "$HOME/.local/share/llm-trading-arena"
chmod 700 "$HOME/.local/share/llm-trading-arena"
chmod 600 "$ROOT/.env"
cd "$ROOT"
python3 -m unittest discover -s "$ROOT/tests" -v
sed "s/__PI_USER__/$USER_NAME/g" "$ROOT/deploy/llm-trading-arena.service" > /tmp/llm-trading-arena.service."$USER_NAME"
sudo install -m 644 /tmp/llm-trading-arena.service."$USER_NAME" /etc/systemd/system/llm-trading-arena.service
rm /tmp/llm-trading-arena.service."$USER_NAME"
sudo systemctl daemon-reload
sudo systemctl enable --now llm-trading-arena.service
sudo systemctl --no-pager status llm-trading-arena.service
