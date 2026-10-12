@echo off
rem generic questflow launcher (ASCII only):
rem   run_questflow_task.cmd <client> <alias> [step]
rem   does <alias> (from <step> if given, else auto), then continues with the rest of the flow.
rem   aliases: liuli xuanhuang biqing shenhong hero1 hero2 rescue dreamcave axe fiveb robber piglove
rem            fourjade mazu miner mengde qiangen wood antelope dragonnest miyo
set "C=%1"
if "%C%"=="" set "C=kkfaq22222"
set "Q=%2"
set "S=%3"
if "%Q%"=="" goto usage
set PSA_EXE_MATCH=%C%
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
if "%S%"=="" (
  uv run --no-project python tools/gui/questflow1920.py --client %C% --only %Q% --skip-bag
) else (
  uv run --no-project python tools/gui/questflow1920.py --client %C% --only %Q% --from-step %S% --skip-bag
)
if errorlevel 1 goto done
uv run --no-project python tools/gui/questflow1920.py --client %C% --from %Q%
goto done
:usage
echo usage: run_questflow_task.cmd ^<client^> ^<alias^> [step]
:done
echo.
echo questflow exit code %ERRORLEVEL%
pause
