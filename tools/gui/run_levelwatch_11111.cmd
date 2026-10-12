@echo off
rem levelwatch for kkfaq11111 (Ctrl+C to stop)
set PSA_EXE_MATCH=kkfaq11111
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PSA_TILE_SCALE=0.5
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/levelwatch.py --verbose
echo.
echo levelwatch exit code %ERRORLEVEL%
pause
