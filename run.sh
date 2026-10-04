#!/usr/bin/env bash
# Run the Stacks desktop app in dev. Ctrl+C shuts down the app, its backend, and vite.
set -euo pipefail
cd "$(dirname "$0")"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) dev_python=.venv/Scripts/python.exe ;;
  *) dev_python=.venv/bin/python ;;
esac

if [ ! -x "$dev_python" ]; then
  echo "No .venv found. See README 'Build from source'." >&2
  exit 1
fi

if [ ! -d src/frontend/node_modules ]; then
  echo "Frontend deps missing. Run: cd src/frontend && npm install" >&2
  exit 1
fi

cd src/frontend
exec npm run desktop
