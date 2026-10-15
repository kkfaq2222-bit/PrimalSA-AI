@echo off
rem reset full run state (start again from stage "train") for one or more clients (ASCII only):
rem   reset_fullrun.cmd kkfaq11111 kkfaq22222 333
rem stop that client's watchdog (Ctrl+C) BEFORE running this. state file is renamed to .reset-<time>.bak (not deleted).
rem quest ledger / katan / rebirthprep progress is backed up and cleared automatically at stage "ledger".
cd /d "%~dp0..\.."
if "%~1"=="" (
  echo usage: reset_fullrun.cmd client [client ...]   example: reset_fullrun.cmd kkfaq11111 kkfaq22222 333
  exit /b 1
)
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "STAMP=%%t"
:loop
if "%~1"=="" goto done
if exist "tools\.cache\fullrun-%~1.json" (
  move /y "tools\.cache\fullrun-%~1.json" "tools\.cache\fullrun-%~1.json.reset-%STAMP%.bak" >nul
  echo %~1 : reset done (backup fullrun-%~1.json.reset-%STAMP%.bak)
) else (
  echo %~1 : no state file, already reset
)
shift
goto loop
:done
echo next: tools\gui\run_watchdog.cmd ^<client^> --loop --max-rounds 2
