#!/usr/bin/env bash
# WSL 包裝：bash tools/gui/gui.sh <shot|click|dclick|drag|key|info> ...
# shot 不給檔名時存到 tools/.cache/shot.png
DIR="$(cd "$(dirname "$0")" && pwd)"
PS="$(wslpath -w "$DIR/gui.ps1")"
cmd="$1"; shift
if [ "$cmd" = shot ]; then
  out="${1:-$DIR/../.cache/shot.png}"; mkdir -p "$(dirname "$out")"
  set -- "$(wslpath -w "$(realpath -m "$out")")"
fi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS" "$cmd" "$@" 2>&1 | tr -d '\r'
