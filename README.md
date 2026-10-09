# 精靈王石器（PrimalSA）資料庫

《精靈王石器》（PrimalSA，韓版客戶端 `yhkrn`）的遊戲資料庫與查詢網站。

- **線上查詢**：https://psa-wiki.pages.dev/（Cloudflare Pages）
  搜尋道具、寵物 / 怪物、NPC、地圖、技能、狀態、任務（繁中、簡中、韓文、ID 都可以），
  詳情頁有交叉連結（誰賣、怎麼合成、拿去做什麼、哪個任務要用、NPC 位置），地圖頁會畫出通行格、NPC 和出口。
- **文件**：`knowledge/` 是從遊戲客戶端設定表自動匯出的分類文件（Markdown），網站上也可以瀏覽與篩選。

## 目錄
| 路徑 | 內容 |
|---|---|
| `knowledge/` | 遊戲知識庫（自動產生，勿手動修改）；`knowledge/data/` 是機器可讀的原始表 |
| `tools/extract/` | 從遊戲客戶端匯出 `knowledge/`（需要本機有 `GameClient/`，不在 repo 內） |
| `tools/query/psa.py` | 命令列查詢工具 |
| `tools/web/` | 靜態網站：`build.py` 產生 `site/`，`static/` 是前端，`deploy.sh` 發布到 Cloudflare Pages |
| `tools/gui/`、`.claude/skills/` | 讓 AI 透過畫面操作遊玩的工具與說明 |
| `AGENTS.md` | AI 代理工作規範與遊戲規則摘要 |

## 本機建置網站
```
uv run --no-project python tools/web/build.py          # 輸出到 site/
uv run --no-project python -m http.server -d site 8000 # 開 http://localhost:8000
```
發布到 Cloudflare Pages（第一次先 `npx wrangler@4 login --browser=false` 登入）：
```
bash tools/web/deploy.sh
```

## 遊戲更新後
```
uv run --no-project --with UnityPy python tools/extract/extract.py   # 重新匯出 knowledge/
```
然後跑 `bash tools/web/deploy.sh` 更新網站。

## 聲明
資料由遊戲客戶端設定表自動匯出，僅供玩家參考；遊戲內容與素材版權屬原開發 / 營運商。本 repo 不含遊戲客戶端檔案。
