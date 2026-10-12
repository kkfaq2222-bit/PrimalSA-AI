@echo off
rem redo skipped quests from step 1: dream cave, five brothers
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/questflow1920.py --client %C% --only dreamcave --from-step 1 --skip-bag
if errorlevel 1 goto done
uv run --no-project python tools/gui/questflow1920.py --client %C% --only fiveb --from-step 1 --skip-bag
:done
echo.
echo questflow exit code %ERRORLEVEL%
pause
