@echo off
setlocal
REM ===========================================================================
REM  Starts the GoodSAM -> REDCap web app AND shares it through ngrok.
REM  Opens two windows ("GoodSAM app" and "ngrok"). Keep both open; close them
REM  to stop sharing.
REM  First run asks for your ngrok address and saves it (not in the code) to
REM  %USERPROFILE%\.streamlit\ngrok_domain.txt
REM  The app refuses to open without APP_PASSWORD when started from here.
REM ===========================================================================
cd /d "%~dp0"
set "CFG=%USERPROFILE%\.streamlit"
set "DOMAIN_FILE=%CFG%\ngrok_domain.txt"

where python >nul 2>nul && (set "PY=python") || (set "PY=py")

where ngrok >nul 2>nul
if errorlevel 1 (
  echo ngrok was not found. Install it with:   winget install ngrok.ngrok
  echo then open a new window and run this file again.
  pause
  exit /b 1
)

REM --- Is the app already running (e.g. from start_app.bat)? ---
curl -s -o nul http://localhost:8501/_stcore/health
if not errorlevel 1 (
  echo The app is already running on this PC. Close its window first
  echo (the one started by start_app.bat^), then run this file again.
  pause
  exit /b 1
)

REM --- ngrok address: ask once, then remember it ---
if exist "%DOMAIN_FILE%" goto have_domain
if not exist "%CFG%" mkdir "%CFG%"
echo Find your address on the ngrok dashboard under Domains.
set /p "DOMAIN=Your ngrok address (e.g. something.ngrok-free.dev): "
if "%DOMAIN%"=="" (
  echo No address entered.
  pause
  exit /b 1
)
set "DOMAIN=%DOMAIN:https://=%"
set "DOMAIN=%DOMAIN:/=%"
>"%DOMAIN_FILE%" echo %DOMAIN%
:have_domain
set /p DOMAIN=<"%DOMAIN_FILE%"

REM --- Start the app (locked unless APP_PASSWORD is set) ---
set "GOODSAM_SHARED=1"
start "GoodSAM app - keep open" cmd /k %PY% -m streamlit run app.py --server.address localhost --server.port 8501

echo Waiting for the app to start...
set /a TRIES=0
:wait
curl -s -o nul http://localhost:8501/_stcore/health
if not errorlevel 1 goto app_up
set /a TRIES+=1
if %TRIES% geq 90 (
  echo The app did not start. Check the "GoodSAM app" window for errors.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:app_up
start "ngrok - keep open" ngrok http --url=%DOMAIN% 8501
echo.
echo Shared at:  https://%DOMAIN%
echo On this PC: http://localhost:8501
echo.
echo Keep the "GoodSAM app" and "ngrok" windows open. Close them to stop sharing.
echo To use a different ngrok address, delete %DOMAIN_FILE%
echo.
pause
