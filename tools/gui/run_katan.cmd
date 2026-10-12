@echo off
rem Katan wish launcher (ASCII only): run_katan.cmd <client> <shark|bird> [extra args for katan1920.py]
rem   EVERYTHING (shark then bird, from zero): run_katan.cmd kkfaq22222 all --phase all --do --resume
rem   shark only:  run_katan.cmd kkfaq22222 shark --phase all --do --resume
rem   bird  (after shark): run_katan.cmd kkfaq22222 bird --phase all --no-setup --do --resume
rem   preview only:       run_katan.cmd kkfaq22222 shark --plan
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set "F=%2"
if "%F%"=="" set "F=shark"
shift
shift
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/katan1920.py --client %C% --family %F% %1 %2 %3 %4 %5 %6 %7 %8 %9
echo.
echo katan exit code %ERRORLEVEL%
pause
