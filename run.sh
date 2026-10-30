#!/usr/bin/env bash
# Starts easy-photo from its local virtual environment (app/.venv).
# On the first run it makes that environment and installs the app into it.
#
# Usage: ./run.sh [project folder or easy-photo-project.json]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app="$here/app"
venv="$app/.venv"

if [ ! -x "$venv/bin/easy-photo" ]; then
    echo "Setting up easy-photo in $venv (first run only)..."
    python3 -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install -e "$app"
fi

exec "$venv/bin/easy-photo" "$@"
