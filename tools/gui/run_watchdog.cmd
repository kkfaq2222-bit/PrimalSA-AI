@echo off
rem full run with watchdog for one client (ASCII only):
rem   run_watchdog.cmd <client> [--loop [--max-rounds N] [--max-trans 5]]
rem   client may be an account code, folder name, or alias from tools/.cache/clients.json (example: 333)
rem   Ctrl+C to stop. state: tools/.cache/fullrun-<client>.json, flag: fullrun-flag-<client>.json
set "HERE=%~dp0"
set "C=%1"
if "%C%"=="" set "C=kkfaq11111"
shift
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
if "%PSA_TILE_SCALE%"=="" set PSA_TILE_SCALE=0.5
set PYTHONIOENCODING=utf-8
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/fullrun_watchdog.py --client %C% %1 %2 %3 %4 %5 %6
echo.
echo watchdog exit code %ERRORLEVEL%
pause
