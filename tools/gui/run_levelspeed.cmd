@echo off
rem level speed / ETA to 131 for all clients (read-only, ASCII only). Optional: --watch 60
set "HERE=%~dp0"
set PYTHONIOENCODING=utf-8
cd /d "%HERE%..\.."
uv run --no-project python tools/gui/levelspeed.py %1 %2 %3 %4
pause
