#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
VENV="$ROOT/.venv"
INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --help|-h)
      printf 'Usage: %s [--install]\n' "$0"
      printf 'Default: no downloads; starts the local app on 127.0.0.1:8501.\n'
      printf 'Use --install to explicitly install requirements into the project venv.\n'
      exit 0
      ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3 is required. Ubuntu 24.04: python3 --version\n' >&2
  exit 1
fi
python3 - <<'PY' || { printf 'Python 3.10 or newer is required.\n' >&2; exit 1; }
import sys
if sys.version_info < (3, 10):
    raise SystemExit(1)
PY

if [[ ! -x "$VENV/bin/python" ]]; then
  if ! python3 -m venv "$VENV"; then
    printf 'Could not create .venv. On Ubuntu, install python3-venv only if missing:\n  sudo apt install python3-venv\n' >&2
    exit 1
  fi
fi

if [[ "$INSTALL" -eq 1 ]]; then
  "$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"
fi

if ! "$VENV/bin/python" -c 'import streamlit, pandas' >/dev/null 2>&1; then
  printf 'Dependencies are not installed in %s. No download was started.\n' "$VENV" >&2
  printf 'Install explicitly with: %s --install\n' "$0" >&2
  printf 'Or follow the offline/online instructions in README.md.\n' >&2
  exit 2
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$VENV/bin/python" "$ROOT/tools/manage_data.py" init
HOST="${CIRCUIT_AI_HOST:-127.0.0.1}"
PORT="${CIRCUIT_AI_PORT:-8501}"
case "$PORT" in *[!0-9]*|'') printf 'CIRCUIT_AI_PORT must be numeric.\n' >&2; exit 2 ;; esac
if (( PORT < 1024 || PORT > 65535 )); then
  printf 'Choose a port in the range 1024–65535.\n' >&2
  exit 2
fi
printf 'CIRCUIT AI is local at http://%s:%s\n' "$HOST" "$PORT"
exec "$VENV/bin/python" -m streamlit run "$ROOT/app.py" \
  --server.address "$HOST" --server.port "$PORT" --server.headless true \
  --browser.gatherUsageStats false
