@echo off
REM Run the Stacks desktop app in dev. Close the app window or press Ctrl+C here to stop.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo No .venv found. See README "Build from source".
  exit /b 1
)
if not exist "src\frontend\node_modules" (
  echo Frontend deps missing. Run: cd src\frontend ^&^& npm install
  exit /b 1
)

cd src\frontend
call npm run desktop
