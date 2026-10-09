#!/usr/bin/env bash
# WSL 包裝：開精靈王石器畫面鏡像視窗（背景執行，立即返回）。bash tools/gui/mirror.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
PS="$(wslpath -w "$DIR/mirror.ps1")"
powershell.exe -NoProfile -c "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-STA','-File','\"$PS\"'"
