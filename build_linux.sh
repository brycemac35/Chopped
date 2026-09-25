#!/usr/bin/env bash
# Builds a single-file Linux binary: dist/Chopped
# Usage: ./build_linux.sh            (uses python3.12 if present, else python3)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if command -v python3.12 >/dev/null 2>&1; then PY=python3.12; else PY=python3; fi
fi
echo "== using $($PY --version)"

if [ ! -d .venv ]; then
  if ! "$PY" -m venv .venv 2>/dev/null; then
    echo "!! venv module unavailable; installing into the current interpreter instead"
    NOVENV=1
  fi
fi
if [ -z "${NOVENV:-}" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PY=python
  PIPFLAGS=""
else
  PIPFLAGS="--break-system-packages"
fi

"$PY" -m pip install $PIPFLAGS -q pygame-ce==2.5.8 pyinstaller==6.22.3
"$PY" -m pip install $PIPFLAGS -q miniupnpc==2.3.3 || echo "!! miniupnpc failed to install - building without UPnP (game still works)"

"$PY" -m PyInstaller --noconfirm --clean --onefile --windowed --name Chopped \
  --hidden-import miniupnpc \
  --collect-submodules chopped \
  main.py

echo "== verifying the binary boots headless"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy ./dist/Chopped --selftest --frames 300
echo "== built dist/Chopped"
