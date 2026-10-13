@echo off
rem Start level watching for BOTH accounts + level-speed monitor (ASCII only). Auto heal is OFF (--no-heal).
rem   run_levelwatch_both.cmd            -> 3 windows: 11111 levelwatch / 22222 levelwatch / level-speed (refresh 60s)
rem   run_levelwatch_both.cmd --no-speed -> only the 2 levelwatch windows
rem Each window stays open (cmd /k); close a window or press Ctrl+C to stop that one.
set "HERE=%~dp0"
start "levelwatch 11111" cmd /k ""%HERE%run_levelwatch.cmd" kkfaq11111 --every 30 --stop-at-end --no-heal"
start "levelwatch 22222" cmd /k ""%HERE%run_levelwatch.cmd" kkfaq22222 --every 30 --stop-at-end --no-heal"
if /i "%1"=="--no-speed" goto :eof
set PYTHONIOENCODING=utf-8
start "level speed" cmd /k "cd /d "%HERE%..\.." && uv run --no-project python tools/gui/levelspeed.py --watch 60"
