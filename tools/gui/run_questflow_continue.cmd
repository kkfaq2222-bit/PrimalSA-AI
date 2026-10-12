@echo off
rem continue questflow from the four-jade quest; usage: run_questflow_continue.cmd [client]
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/questflow1920.py --client %C% --from fourjade
echo.
echo questflow exit code %ERRORLEVEL%
pause
