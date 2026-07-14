#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "app.py" || ! -f "requirements.txt" ]]; then
  echo "Please run this script from the homebase-camera project root."
  exit 1
fi

INSTALL_SYSTEM_PACKAGES=0
INSTALL_LAUNCHERS=0
for arg in "$@"; do
  case "$arg" in
    --install-system-packages)
      INSTALL_SYSTEM_PACKAGES=1
      ;;
    --install-launchers)
      INSTALL_LAUNCHERS=1
      ;;
    -h|--help)
      echo "Usage: ./setup_raspberry_pi.sh [--install-system-packages] [--install-launchers]"
      echo ""
      echo "  --install-system-packages  Also install Raspberry Pi OS packages:"
      echo "                             python3, python3-venv, python3-picamera2, python3-opencv, curl"
      echo "  --install-launchers        Install one-click desktop and application-menu launchers"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: ./setup_raspberry_pi.sh [--install-system-packages] [--install-launchers]"
      exit 1
      ;;
  esac
done

echo "Setting up Homebase Camera in: $SCRIPT_DIR"

mkdir -p data data/snapshots config

if [[ "$INSTALL_SYSTEM_PACKAGES" == "1" ]]; then
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get was not found. --install-system-packages is intended for Raspberry Pi OS/Debian."
    exit 1
  fi
  APT_PREFIX=()
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    APT_PREFIX=(sudo)
  fi
  echo "Installing Raspberry Pi OS system packages for camera support..."
  "${APT_PREFIX[@]}" apt-get update
  "${APT_PREFIX[@]}" apt-get install -y python3 python3-venv python3-picamera2 python3-opencv curl
fi

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
  PYARROW_FALLBACK_OK="$(python - <<'PY'
import platform
import sys
import sysconfig

platform_tag = sysconfig.get_platform().lower()
machine = platform.machine().lower()
is_armhf = (
    "armv7" in platform_tag
    or "arm-linux-gnueabihf" in platform_tag
    or "armhf" in platform_tag
    or "armv7" in machine
)
print("1" if sys.version_info >= (3, 13) and is_armhf else "0")
PY
)"
  if [[ "$PYARROW_FALLBACK_OK" == "1" ]]; then
    echo ""
    echo "Full dependency installation failed on 32-bit Raspberry Pi Python 3.13."
    echo "PyArrow wheels are often unavailable for this platform, so installing a dashboard fallback set."
    python -m pip install --no-cache-dir \
      altair cachetools click gitpython pandas pydeck protobuf tenacity toml watchdog \
      anyio httptools itsdangerous python-multipart starlette uvicorn websockets requests \
      pytest narwhals gitdb smmap h11 pluggy iniconfig
    python -m pip install --no-cache-dir --no-deps \
      "streamlit>=1.31" "streamlit-autorefresh>=1.0.1" "streamlit-drawable-canvas>=0.9.3"
    echo "Installed fallback Python dependencies without PyArrow."
    echo "Auto-refresh and table widgets will degrade gracefully if PyArrow is unavailable."
  else
    echo "Python dependency installation failed."
    echo "If OpenCV or camera packages are missing on Raspberry Pi OS, run:"
    echo "  sudo apt update"
    echo "  sudo apt install python3-picamera2 python3-opencv"
    echo "Then run ./setup_raspberry_pi.sh again."
    exit 1
  fi
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

chmod +x setup_raspberry_pi.sh run_app.sh run_mock.sh homebase
if [[ -f "scripts/install_desktop_launcher.sh" ]]; then
  chmod +x scripts/install_desktop_launcher.sh scripts/pi_control.sh
fi

if [[ "$INSTALL_LAUNCHERS" == "1" ]]; then
  ./scripts/install_desktop_launcher.sh
fi

echo ""
echo "Setup complete."
echo "Next command:"
echo "  ./homebase"
echo ""
echo "Install Raspberry Pi desktop launchers:"
echo "  ./scripts/install_desktop_launcher.sh"
echo ""
echo "No Raspberry Pi camera available? Use:"
echo "  ./run_mock.sh"
