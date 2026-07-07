#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DESKTOP_DIR="$HOME/Desktop"
LAUNCHER="$DESKTOP_DIR/Homebase Camera.desktop"

mkdir -p "$DESKTOP_DIR"

cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Homebase Camera
Comment=Start the Homebase Camera Streamlit dashboard
Exec=$PROJECT_DIR/run_app.sh
Path=$PROJECT_DIR
Terminal=true
Categories=Utility;
EOF

chmod +x "$LAUNCHER"
echo "Installed desktop launcher: $LAUNCHER"
