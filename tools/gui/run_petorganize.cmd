@echo off
rem pet organize launcher (ASCII only):
rem   run_petorganize.cmd <client> <look|do> [extra args, e.g. --roles 1,2 --only store]
rem   look = preview only (reads names, touches nothing); do = really delete / store
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set "A=%2"
set "X="
if /i "%A%"=="do" set "X=--do"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/petorganize1920.py --client %C% %X% %3 %4 %5 %6
echo.
echo petorganize exit code %ERRORLEVEL%
pause
