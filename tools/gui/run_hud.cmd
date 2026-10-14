@echo off
rem small status window for one client (read-only, ASCII only):
rem   run_hud.cmd <client>      client = kkfaq11111 / kkfaq22222 / 333
set "HERE=%~dp0"
set "C=%1"
if "%C%"=="" set "C=kkfaq11111"
cd /d "%HERE%..\.."
start "" /b uv run --no-project python tools/gui/hudwin.py --client %C%
