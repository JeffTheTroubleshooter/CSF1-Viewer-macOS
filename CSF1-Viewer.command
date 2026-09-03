#!/bin/bash
export CSF1_VIEWER_EDITION=macOS
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec bash "$DIR/CSF1-Viewer.sh"
