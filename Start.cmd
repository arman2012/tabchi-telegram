@echo off
setlocal
title Telegram Campaign Manager
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%CD%\.python"
set "UV_PROJECT_ENVIRONMENT=%CD%\.venv"
set "UV_PYTHON=3.12"
set "UV_EXE=uv"
where uv >nul 2>nul
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
  ) else (
    echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/
    echo Then double-click Start.cmd again.
    if not defined TABCHI_NO_PAUSE pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  "%UV_EXE%" venv --python 3.12
  if errorlevel 1 goto failed
)
"%UV_EXE%" pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -u run.py
if errorlevel 1 goto app_failed
echo.
echo Launcher finished. If the app was already running, its dashboard was reopened.
if not defined TABCHI_NO_PAUSE pause
exit /b 0
:app_failed
echo.
echo The app could not start or reopen. The error is shown above.
if not defined TABCHI_NO_PAUSE pause
exit /b 1
:failed
echo Setup failed. Check your internet connection and the error above.
if not defined TABCHI_NO_PAUSE pause
exit /b 1
