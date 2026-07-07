#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d ".venv" ]]; then
  echo ".venv was not found. Run ./setup_raspberry_pi.sh first."
  exit 1
fi
if [[ ! -f ".venv/bin/activate" ]]; then
  echo ".venv exists but is not a Linux virtual environment. Run ./setup_raspberry_pi.sh on this Raspberry Pi."
  exit 1
fi

mkdir -p data data/snapshots config
if [[ ! -f "config/settings.toml" && -f "config/settings.example.toml" ]]; then
  cp config/settings.example.toml config/settings.toml
fi
if [[ ! -f "config/seats.json" && -f "config/seats.example.json" ]]; then
  cp config/seats.example.json config/seats.json
fi

source .venv/bin/activate
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo "Starting Homebase Camera dashboard..."
echo "Open this on the Raspberry Pi: http://localhost:8501"
echo "From another device on the same network, open: http://<raspberry-pi-ip>:8501"

printf '\n' | python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
