#!/usr/bin/env bash
# WSL / Git Bash 手打用包裝：bash tools/gui/gui.sh <shot|click|dclick|drag|key|info> ...
# （Python 腳本 walk.py / heal.py 不經過這支，直接呼叫 powershell.exe，見 winenv.py）
# 動到遊戲的指令（click / drag / key / max / end…）gui.ps1 會寫操作 log（tools/.cache/actions.log，pane 顯示）；
# 想附註用途：PSA_NOTE="對話確認" bash tools/gui/gui.sh click 948 461
# shot 不給檔名時存到 tools/.cache/shot.png；給相對檔名（如 out1.png）也存到 tools/.cache/ 底下，絕對路徑照用
DIR="$(cd "$(dirname "$0")" && pwd)"
# 路徑換算：WSL 用 wslpath -w；Git Bash 用 cygpath -w；都沒有就用原路徑
winpath() { if command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"; elif command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
PS="$(winpath "$DIR/gui.ps1")"
cmd="$1"; shift
if [ "$cmd" = shot ]; then
  out="${1:-shot.png}"
  case "$out" in /*|[A-Za-z]:*|\\*) ;; *) out="$DIR/../.cache/$out" ;; esac   # 相對路徑一律放 tools/.cache/（與 gui.ps1 一致）
  mkdir -p "$(dirname "$out")"
  set -- "$(winpath "$(realpath -m "$out" 2>/dev/null || echo "$out")")"
fi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS" "$cmd" "$@" ${PSA_NOTE:+-Note "$PSA_NOTE"} 2>&1 | tr -d '\r'
