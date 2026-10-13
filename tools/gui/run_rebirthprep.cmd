@echo off
set "HERE=%~dp0"
rem Post-rebirth Lv1 prep launcher (ASCII only): run_rebirthprep.cmd <client> [extra args for rebirthprep1920.py]
rem   preview only:   run_rebirthprep.cmd kkfaq22222 --plan
rem   everything:     run_rebirthprep.cmd kkfaq22222 --do --resume
rem   one phase:      run_rebirthprep.cmd kkfaq22222 --phase lock --do
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
shift
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/rebirthprep1920.py --client %C% %1 %2 %3 %4 %5 %6 %7 %8 %9
echo.
echo rebirthprep exit code %ERRORLEVEL%
pause
