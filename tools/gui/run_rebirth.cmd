@echo off
rem rebirth launcher (ASCII only):
rem   run_rebirth.cmd <client> <go|look|step|after>
rem   go   = team up + navigate to the spirit king, stop when the dialog opens (no option clicked)
rem   look = read-only (screenshot + dialog OCR)
rem   step = click the FIRST dialog option once (irreversible rebirth may happen here, run only after the user agrees)
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set "A=%2"
if "%A%"=="" set "A=look"
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
uv run --no-project python tools/gui/rebirth1920.py --client %C% %A%
echo.
echo rebirth exit code %ERRORLEVEL%
pause
