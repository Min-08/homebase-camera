@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo .venv was not found. Run setup_pc.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat
set HOMEBASE_MOCK_MODE=1
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo Starting Homebase Camera mock mode...
echo Open this computer: http://localhost:8501
echo. | python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
