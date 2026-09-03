#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export CSF1_VIEWER_EDITION="${CSF1_VIEWER_EDITION:-macOS}"
echo "CSF1 Viewer macOS"
python3 "$DIR/jck_version.py" || true
if python3 -c "import tkinter" >/dev/null 2>&1; then
  exec python3 "$DIR/csf1_viewer.py" --tk "$@"
else
  exec python3 "$DIR/csf1_viewer.py" --web "$@"
fi
