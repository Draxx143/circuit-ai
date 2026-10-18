#!/usr/bin/env bash
# CIRCUIT AI - one-click installer/launcher
# Usage:  bash install-circuit-ai.sh
set -e
cd "$HOME"

if [ ! -d circuit-ai/.git ]; then
  echo "==> Downloading CIRCUIT AI ..."
  git clone https://github.com/Draxx143/circuit-ai.git
else
  echo "==> Updating CIRCUIT AI ..."
  git -C circuit-ai pull --ff-only || true
fi

cd circuit-ai
echo "==> Installing dependencies (first run only, needs internet) ..."
./run-desktop.sh --install

echo ""
echo "==> Starting CIRCUIT AI ..."
echo "==> Open this address in your browser:  پنجره برنامه به‌صورت خودکار باز می‌شود (مرورگر لازم نیست)"
echo "==> To stop the program press:  Ctrl+C"
echo ""
exec ./run-desktop.sh
