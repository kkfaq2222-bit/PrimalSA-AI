@echo off
rem Terminal launcher: run_levelwatch.cmd <client code> [levelwatch args...]
rem Example: tools\gui\run_levelwatch.cmd kkfaq11111 --dry-run --verbose --every 10
set "HERE=%~dp0"
set PSA_EXE_MATCH=%1
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
if "%PSA_TILE_SCALE%"=="" set PSA_TILE_SCALE=0.5
shift
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/levelwatch.py %1 %2 %3 %4 %5 %6 %7 %8 %9
