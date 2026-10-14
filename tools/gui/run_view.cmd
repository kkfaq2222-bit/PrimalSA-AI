@echo off
rem read-only small game-screen preview window for one client (ASCII only):
rem   run_view.cmd <client> [--width 480] [--every 3] [--pos x,y]
rem   client = kkfaq11111 / kkfaq22222 / 333    stop: hudview.py --client <c> --stop
set "HERE=%~dp0"
set "C=%1"
if "%C%"=="" set "C=kkfaq11111"
shift
set PSA_GUI_SERVER=1
cd /d "%HERE%..\.."
start "" /b uv run --no-project python tools/gui/hudview.py --client %C% %1 %2 %3 %4 %5 %6
