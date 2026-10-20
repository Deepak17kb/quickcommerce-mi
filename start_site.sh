#!/bin/sh
# Qcom on macOS and Linux:  ./start_site.sh          -> http://localhost:8000 on this computer
#                           ./start_site.sh --lan    -> also on phones and tablets on the same Wi-Fi, behind a code
# First time only: chmod +x start_site.sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" scripts/serve_site.py "$@"
