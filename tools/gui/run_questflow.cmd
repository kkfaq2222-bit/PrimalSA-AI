@echo off
rem Terminal launcher: run_questflow.cmd <client code> [questflow args...]
set "HERE=%~dp0"
set PSA_EXE_MATCH=%1
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
shift
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/questflow1920.py --client %PSA_EXE_MATCH% %1 %2 %3 %4 %5 %6 %7 %8 %9
