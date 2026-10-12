@echo off
rem resume paused scripts: resume.cmd [client]
cd /d "%~dp0..\.."
if "%1"=="" (uv run --no-project python tools/gui/pausegate.py off) else (uv run --no-project python tools/gui/pausegate.py off %1)
