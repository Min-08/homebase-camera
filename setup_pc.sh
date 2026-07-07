#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "app.py" || ! -f "requirements.txt" ]]; then
  echo "Please run this script from the homebase-camera project root."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3 first."
  exit 1
fi

mkdir -p data data/snapshots config demo demo/frames

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
if [[ ! -f ".venv/bin/activate" ]]; then
  echo ".venv exists but is not a macOS/Linux virtual environment."
  echo "Remove .venv and run ./setup_pc.sh again, or use setup_pc.bat on Windows."
  exit 1
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python tools/generate_demo_assets.py

if [[ ! -f "config/settings.toml" ]]; then
  cp config/settings.example.toml config/settings.toml
fi
if [[ ! -f "config/seats.json" ]]; then
  cp config/seats.example.json config/seats.json
fi

chmod +x run_demo.sh run_mock.sh run_app.sh setup_pc.sh setup_raspberry_pi.sh

echo "PC setup complete."
echo "Start the demo with: ./run_demo.sh"
