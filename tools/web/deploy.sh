#!/usr/bin/env bash
# 建置靜態網站並發布到 Cloudflare Pages（專案 kkfaq-psa-wiki → https://kkfaq-psa-wiki.pages.dev）
# 第一次使用前先登入：npx wrangler@4 login --browser=false
# 用法（專案根目錄）：bash tools/web/deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/site"
PROJECT="${CF_PAGES_PROJECT:-kkfaq-psa-wiki}"

uv run --no-project python "$ROOT/tools/web/build.py" --out "$OUT"

# 專案不存在就先建立（production 分支 main）
if ! npx --yes wrangler@4 pages project list 2>/dev/null | grep -q "\b$PROJECT\b"; then
  npx --yes wrangler@4 pages project create "$PROJECT" --production-branch main --force   # --force：直接建在 Pages，不轉給 Workers
fi
npx --yes wrangler@4 pages deploy "$OUT" --project-name "$PROJECT" --branch main --commit-dirty=true
