@echo off
rem daily quest: for each page given: withdraw page materials from shared depot, craft the page, submit.
rem usage: run_daily_craft.cmd 3 4 5      (client = kkfaq11111, today list = tools\.cache\daily-today.json)
set "HERE=%~dp0"
set PSA_EXE_MATCH=kkfaq11111
set PSA_GUI_SERVER=1
if "%PSA_CLICK_HOLD_MS%"=="" set PSA_CLICK_HOLD_MS=120
set PYTHONIOENCODING=utf-8
cd /d "%HERE%..\.."
for %%P in (%*) do (
  echo ===== page %%P =====
  uv run --no-project python tools/gui/dailyquest1920.py withdraw --client kkfaq11111 --file tools/.cache/daily-today.json --page %%P
  if errorlevel 1 goto :done
  uv run --no-project python tools/gui/dailyquest1920.py craft --client kkfaq11111 --file tools/.cache/daily-today.json --page %%P --submit
  if errorlevel 1 goto :done
)
:done
echo.
echo exit code %ERRORLEVEL%
pause
