#!/usr/bin/env bash
# WSL / Git Bash 手打用包裝：開精靈王石器畫面鏡像視窗（背景執行，立即返回）。bash tools/gui/mirror.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
winpath() { if command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"; elif command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
PS="$(winpath "$DIR/mirror.ps1")"
powershell.exe -NoProfile -c "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-STA','-File','\"$PS\"'"
