@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo .venv was not found. Run setup_pc.bat first.
  exit /b 1
)
if not exist .venv\Scripts\activate.bat (
  echo .venv exists but is not a Windows virtual environment. Run setup_pc.bat on this machine.
  exit /b 1
)

call .venv\Scripts\activate.bat
python tools\generate_demo_assets.py >nul
if errorlevel 1 exit /b 1

set HOMEBASE_DEMO_MODE=1
set HOMEBASE_SETTINGS_PATH=config/settings.demo.toml
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo Starting Homebase Camera PC demo...
echo Open this computer: http://localhost:8501
echo. | python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
