#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "app.py" || ! -f "requirements.txt" ]]; then
  echo "Please run this script from the homebase-camera project root."
  exit 1
fi

echo "Setting up Homebase Camera in: $SCRIPT_DIR"

mkdir -p data data/snapshots config

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found. Install it first: sudo apt install python3 python3-venv"
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating Python virtual environment at .venv"
  if ! python3 -m venv --system-site-packages .venv; then
    echo "Could not create a virtual environment."
    echo "On Raspberry Pi OS try: sudo apt install python3-venv"
    exit 1
  fi
fi

source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
if ! python -m pip install -r requirements.txt; then
  echo "Python dependency installation failed."
  echo "If OpenCV or camera packages are missing on Raspberry Pi OS, run:"
  echo "  sudo apt update"
  echo "  sudo apt install python3-picamera2 python3-opencv"
  echo "Then run ./setup_raspberry_pi.sh again."
  exit 1
fi

if [[ ! -f "config/settings.toml" ]]; then
  cp config/settings.example.toml config/settings.toml
  echo "Created config/settings.toml from example."
else
  echo "Keeping existing config/settings.toml."
fi

if [[ ! -f "config/seats.json" ]]; then
  cp config/seats.example.json config/seats.json
  echo "Created config/seats.json from example."
else
  echo "Keeping existing config/seats.json."
fi

chmod +x setup_raspberry_pi.sh run_app.sh run_mock.sh
if [[ -f "scripts/install_desktop_launcher.sh" ]]; then
  chmod +x scripts/install_desktop_launcher.sh
fi

echo ""
echo "Setup complete."
echo "Next command:"
echo "  ./run_app.sh"
echo ""
echo "No Raspberry Pi camera available? Use:"
echo "  ./run_mock.sh"
