@echo off
setlocal
cd /d "%~dp0"

if not exist app.py (
  echo Please run this script from the homebase-camera project root.
  exit /b 1
)

if not exist .venv (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3 was not found. Install Python 3 and try again.
    exit /b 1
  )
)

if not exist data mkdir data
if not exist data\snapshots mkdir data\snapshots
if not exist config mkdir config
if not exist demo mkdir demo
if not exist demo\frames mkdir demo\frames

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python tools\generate_demo_assets.py
if errorlevel 1 exit /b 1

if not exist config\settings.toml copy config\settings.example.toml config\settings.toml >nul
if not exist config\seats.json copy config\seats.example.json config\seats.json >nul

echo PC setup complete.
echo Start the demo with: run_demo.bat
