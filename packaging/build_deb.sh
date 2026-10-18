#!/usr/bin/env bash
# Build a .deb that installs CIRCUIT AI desktop under /opt/circuit-ai.
# Target: Ubuntu 24.04 with system PySide6 (universe). No bundled user data.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
VERSION="${1:-2.0.0}"
OUT="$ROOT/dist"; STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT" "$STAGE/opt/circuit-ai" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/DEBIAN"

for item in desktop_app core services database data config tools pyproject.toml README.md; do
  cp -a "$ROOT/$item" "$STAGE/opt/circuit-ai/"
done
find "$STAGE/opt/circuit-ai" -name __pycache__ -type d -prune -exec rm -rf {} +

cat > "$STAGE/usr/bin/circuit-ai" << 'LAUNCH'
#!/bin/sh
export PYTHONPATH=/opt/circuit-ai
exec /usr/bin/python3 -m desktop_app "$@"
LAUNCH
chmod +x "$STAGE/usr/bin/circuit-ai"
cp "$ROOT/packaging/circuit-ai.desktop" "$STAGE/usr/share/applications/"

cat > "$STAGE/DEBIAN/control" << CONTROL
Package: circuit-ai
Version: $VERSION
Section: electronics
Priority: optional
Architecture: all
Maintainer: CIRCUIT AI Project <local@circuit-ai.invalid>
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, python3-pyside6.qtpdf, libgl1, libegl1, libxkbcommon0
Description: Intelligent Electronics Diagnostics
 Offline desktop workbench for electronics board diagnosis:
 rule-based diagnostic engine, component library, repair cases
 and engineering calculators. User data stays in the per-user
 XDG data directory and is never removed by this package.
CONTROL

DEB="$OUT/circuit-ai_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
printf 'Built %s\n' "$DEB"
