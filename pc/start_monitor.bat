@echo off
rem Resume pushing after flashing: remove pause.flag and let the USB watchdog
rem pick the board up (it polls every 3 seconds, no manual start needed).
if exist "%~dp0pause.flag" (
  del "%~dp0pause.flag"
  echo pause.flag removed - watchdog will start the collector within a few seconds.
) else (
  echo No pause.flag - watchdog is already active.
)
echo.
echo If nothing happens, run install.bat to (re)install the watchdog task.
pause
