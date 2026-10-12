@echo off
rem pause scripts at the next safe point: pause.cmd [client]   (no client = all)
cd /d "%~dp0..\.."
if "%1"=="" (uv run --no-project python tools/gui/pausegate.py on) else (uv run --no-project python tools/gui/pausegate.py on %1)
