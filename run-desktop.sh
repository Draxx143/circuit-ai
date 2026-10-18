#!/usr/bin/env bash
# CIRCUIT AI desktop launcher (Ubuntu 24.04): no browser, no server port.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
VENV="$ROOT/.venv-desktop"
INSTALL=0
APP_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --help|-h) printf 'Usage: %s [--install]\nDefault: no downloads; starts the desktop app.\n' "$0"; exit 0 ;;
    *) APP_ARGS+=("$arg") ;;
  esac
done

PYTHON_BIN=""
for candidate in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
done
if [[ -z "$PYTHON_BIN" ]]; then printf 'Python 3.10+ is required.\n' >&2; exit 1; fi

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV" || { printf 'venv failed. If python3-venv is missing: sudo apt install python3-venv\n' >&2; exit 1; }
fi
if [[ "$INSTALL" -eq 1 ]]; then
  "$VENV/bin/python" -m pip install -r "$ROOT/requirements-desktop.txt"
fi
if ! "$VENV/bin/python" -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
  printf 'PySide6 is not available in %s and no download was started.\n' "$VENV" >&2
  printf 'Install once (needs internet): %s --install\n' "$0" >&2
  printf 'If the error is about libGL/libEGL on Ubuntu, install system libraries once:\n' >&2
  printf '  sudo apt install libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3\n' >&2
  exit 2
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m desktop_app "${APP_ARGS[@]}"
