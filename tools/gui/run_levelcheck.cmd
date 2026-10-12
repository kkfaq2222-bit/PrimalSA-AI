@echo off
rem level check only: run_levelcheck.cmd [client] [target] [every_seconds]
rem   opens the pet panel, selects pet #4 of role 1, reads "0 turn N"; stops when N >= target, otherwise looks again after N seconds
rem   does nothing else (no teleport / team / settings)
set "HERE=%~dp0"
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set "T=%2"
if "%T%"=="" set "T=25"
set "E=%3"
if "%E%"=="" set "E=20"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/katantrain1920.py --client %C% check --target %T% --every %E%
echo.
echo levelcheck exit code %ERRORLEVEL%
pause
