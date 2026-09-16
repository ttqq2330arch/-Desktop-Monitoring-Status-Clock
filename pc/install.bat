@echo off
rem PC Monitor installer.
rem Finds a Python interpreter and runs install.py, which sets everything up:
rem dependencies, the scheduled task, and the USB watchdog.
setlocal

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where pythonw >nul 2>nul && set "PY=pythonw"
)
if not defined PY (
  echo.
  echo [ERROR] Python not found on this PC.
  echo Install Python from https://www.python.org/downloads/
  echo (tick "Add Python to PATH" during setup), then run this again.
  echo.
  pause
  exit /b 1
)

"%PY%" "%~dp0install.py" %*
echo.
pause
