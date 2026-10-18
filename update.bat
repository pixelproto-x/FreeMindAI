@echo off
setlocal
cd /d "%~dp0"

echo Updating FreeMind AI from GitHub...

if exist ".git\HEAD" (
  where git >nul 2>nul
  if errorlevel 1 (
    echo Git was not found. Downloading the latest ZIP instead...
    goto :zip_update
  )
  git pull --ff-only origin main
  if errorlevel 1 (
    echo Git update failed. No files were intentionally overwritten.
    pause
    exit /b 1
  )
  goto :start_app
)

:zip_update
echo This folder was downloaded as a ZIP, so Git pull cannot be used.
echo Downloading the latest project and preserving .env, .venv, and data...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $target=(Get-Location).Path; $tmp=Join-Path $env:TEMP ('FreeMindAI-'+[guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null; try { $zip=Join-Path $tmp 'main.zip'; Invoke-WebRequest -Uri 'https://github.com/pixelproto-x/FreeMindAI/archive/refs/heads/main.zip' -OutFile $zip; Expand-Archive -LiteralPath $zip -DestinationPath $tmp; $src=Join-Path $tmp 'FreeMindAI-main'; if (!(Test-Path (Join-Path $src 'run.bat'))) { throw 'The downloaded archive did not contain run.bat.' }; & robocopy $src $target /E /XD '.git' '.venv' 'venv' '__pycache__' 'data' '.pytest_cache' /XF '.env' 'update.bat'; if ($LASTEXITCODE -ge 8) { throw ('File copy failed with robocopy exit code '+$LASTEXITCODE) }; Copy-Item -LiteralPath (Join-Path $src 'update.bat') -Destination (Join-Path $target 'update.bat') -Force; Write-Host 'Update files copied successfully.' } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }"
if errorlevel 1 (
  echo Update failed. Your .env and local data were preserved.
  pause
  exit /b 1
)

:start_app
echo Update complete. Starting FreeMind AI...
call run.bat
