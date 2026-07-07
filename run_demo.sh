#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d ".venv" ]]; then
  echo ".venv was not found. Run ./setup_pc.sh first."
  exit 1
fi
if [[ ! -f ".venv/bin/activate" ]]; then
  echo ".venv exists but is not a macOS/Linux virtual environment. Run ./setup_pc.sh on this machine."
  exit 1
fi

source .venv/bin/activate
python tools/generate_demo_assets.py >/dev/null

export HOMEBASE_DEMO_MODE=1
export HOMEBASE_SETTINGS_PATH="config/settings.demo.toml"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo "Starting Homebase Camera PC demo..."
echo "Open this computer: http://localhost:8501"
printf '\n' | python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
