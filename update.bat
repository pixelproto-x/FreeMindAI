@echo off
setlocal
cd /d "%~dp0"
echo Updating FreeMind AI from GitHub...
where git >nul 2>nul
if errorlevel 1 (
  echo Git was not found. Install Git for Windows, or download the latest ZIP from GitHub and preserve your existing .env file.
  pause
  exit /b 1
)
git pull --ff-only origin main
if errorlevel 1 (
  echo Update failed. Your local changes were not overwritten.
  echo Please copy the error above before trying again.
  pause
  exit /b 1
)
echo Update complete. Starting FreeMind AI...
call run.bat
