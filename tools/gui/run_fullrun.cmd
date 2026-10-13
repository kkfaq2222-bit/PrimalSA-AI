@echo off
rem full run launcher for one client (ASCII only):
rem   run_fullrun.cmd <client> [--plan | --from STAGE | --only STAGE | --fresh]
rem   stages: train wait131 stopenc ledger prebag quests riddle katan dino gate rebirth organize clear prep grind
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
uv run --no-project python tools/gui/fullrun1920.py --client %C% %1 %2 %3 %4 %5 %6
echo.
echo fullrun exit code %ERRORLEVEL%
pause
