#!/bin/sh
# Double-click on macOS to open ShelfPulse (Finder runs .command files in Terminal). First time only: chmod +x start_site.command
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" scripts/serve_site.py "$@"
