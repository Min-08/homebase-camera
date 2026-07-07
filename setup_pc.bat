@echo off
setlocal
cd /d "%~dp0"

if not exist app.py (
  echo Please run this script from the homebase-camera project root.
  exit /b 1
)

set "PYTHON_CMD=py -3"
%PYTHON_CMD% --version >nul 2>nul
if errorlevel 1 (
  set "PYTHON_CMD=python"
  python --version >nul 2>nul
  if errorlevel 1 (
    echo Python 3 was not found. Install Python 3 and try again.
    exit /b 1
  )
)

%PYTHON_CMD% -c "import sysconfig; raise SystemExit(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)" >nul 2>nul
if errorlevel 1 (
  if "%PYTHON_CMD%"=="py -3" (
    python --version >nul 2>nul
    if not errorlevel 1 (
      set "PYTHON_CMD=python"
      python -c "import sysconfig; raise SystemExit(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)" >nul 2>nul
    )
  )
  if errorlevel 1 (
    echo Homebase Camera PC setup requires standard CPython, not the free-threaded CPython build.
    echo Install the normal Python 3 release from python.org, then run setup_pc.bat again.
    exit /b 1
  )
)

if not exist .venv (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv. Confirm Python 3 venv support is installed.
    exit /b 1
  )
)

if not exist .venv\Scripts\activate.bat (
  echo .venv exists but is not a Windows virtual environment.
  echo Remove .venv and run setup_pc.bat again, or use setup_pc.sh on macOS/Linux.
  exit /b 1
)

.venv\Scripts\python.exe -c "import sysconfig; raise SystemExit(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)" >nul 2>nul
if errorlevel 1 (
  echo Existing .venv uses free-threaded CPython, which lacks wheels for required packages.
  echo Remove .venv, install standard CPython, and run setup_pc.bat again.
  exit /b 1
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
