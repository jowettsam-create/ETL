@echo off
REM Starts the GoodSAM -> REDCap web app on this PC (http://localhost:8501).
REM Only this PC can open it directly; share it with others through a tunnel (e.g. ngrok).
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
%PY% -m streamlit run app.py --server.address localhost
pause
