@echo off
rem bag cleanup launcher (ASCII only):
rem   run_bag.cmd <client>          preview only (nothing is moved or deleted)
rem   run_bag.cmd <client> --do     really store / delete
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/bag1920.py --client %C% %2
echo.
echo bag exit code %ERRORLEVEL%
pause
