#!/usr/bin/env bash
# Build a single-file desktop executable with PyInstaller into dist/.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv-desktop/bin/python}"
[[ -x "$PY" ]] || { printf 'Create the desktop venv first: ./run-desktop.sh --install\n' >&2; exit 1; }
"$PY" -m pip install -q pyinstaller
cd "$ROOT" && "$PY" -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/CIRCUIT-AI.spec
printf 'Built %s\n' "$ROOT/dist/CIRCUIT-AI"
