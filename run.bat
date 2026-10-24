@echo off
setlocal
cd /d "%~dp0"

rem Update from GitHub before starting. The environment flag prevents update.bat/run.bat recursion.
if defined FREEMIND_UPDATE_DONE goto :launch
set "FREEMIND_UPDATE_DONE=1"
call "%~dp0update.bat"
exit /b %errorlevel%

:launch
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating the FreeMind AI Python environment...
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python Launcher was not found. Install Python 3.12 or newer from https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  py -3.12 -m venv .venv >nul 2>nul
  if errorlevel 1 (
    echo Python 3.12 not found. Trying the newest installed Python...
    py -3 -m venv .venv
    if errorlevel 1 (
      echo Could not create the virtual environment. Install Python 3.12 or newer, then retry.
      pause
      exit /b 1
    )
  )
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [2/3] Created .env. Opening it so you can add your own API key.
  notepad.exe ".env"
  echo Save and close Notepad, then return here and press any key.
  pause >nul
)

echo [3/3] Checking and updating Python dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed

echo Starting FreeMind AI...
echo Open http://127.0.0.1:8080 in your browser.
echo Keep this window open while using the app. Press Ctrl+C to stop it.
".venv\Scripts\python.exe" main.py
pause
exit /b 0

:install_failed
echo Dependency installation failed. Check the error above and confirm your internet connection.
pause
exit /b 1
