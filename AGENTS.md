# AGENTS.md — 精靈王石器（PrimalSA）AI 遊玩專案規範

所有 AI 代理（Claude Code、Codex、其他 agent）在這個專案工作前都要先讀完本檔。

## 1. 專案目標
讓 AI 遊玩《精靈王石器》（PrimalSA，Unity 製作的石器時代類回合制網路遊戲，韓版客戶端 `yhkrn`）。
遊戲客戶端放在 `GameClient/`；從客戶端整理出的遊戲知識放在 `knowledge/`，AI 玩遊戲時用來檢索。
角色真名 DKBO、DKBO2～5（字母 O）；文件中的 DKB0～DKB05（數字 0）同義，程式比對 O / 0 視為相同（`tools/gui/charname.canon`、`charstate.same / display`），輸出 / 顯示用真名。

## 2. 目錄結構
```
PrimalSA-AI/
  AGENTS.md            本檔：專案規範 + 遊戲規則摘要
  PLAYBOOK.md          方法手冊：怎麼讓 AI 玩遊戲（給其他 AI / 想照做的人）
  GameClient/          遊戲本體（唯讀！見第 3 節）
  knowledge/           遊戲知識庫（自動產生，勿手動修改）
    README.md          知識庫索引：分類目錄、全部文件清單、查詢方法
    overview/          遊戲常數、程式列舉、客戶端檔案分類與格式、UI 畫面清單
    items/             道具（武器 / 防具 / 飾品 / 藥品 / 材料 / 寵物裝備 / 任務 / 其他）、套裝
    pets/              寵物與怪物（依系別分檔）、取得方式、騎乘、經驗表
    skills/            戰鬥技能、戰鬥狀態 Buff、角色 Buff、技能學習 NPC
    world/             地圖、出口 / 傳送點、NPC（依地圖分組）、交通 / 傳送服務
    quests/            任務鏈、攻略說明、NPC 腳本與對話、答題題庫
    crafting/          合成配方、材料圖鑑、製作、強化、回爐
    economy/           NPC 商店、商城、抽獎、活動 / 副本、公告、儲值（參考）
    text/              遊戲文字（繁中 / 韓文對照，用來看懂畫面訊息）
    data/              機器可讀原始資料：tables/*.jsonl（全部設定表）、maps.bin（通行格）、schema.tsv、enums.tsv
  tools/
    extract/           匯出器：GameClient → knowledge（extract.py、tabtoy.py、docs.py）
    schemadump/        SchemaDump.cs：從 HotUpdate.dll 抽 Tabtoy 欄位對照與列舉（ReflectionOnly，不執行遊戲程式）
    query/psa.py       知識庫查詢工具（搜尋、交叉查詢、跨地圖路線、通行格）
    gui/gui.sh         遊戲畫面操作（截圖、點擊、拖曳、按鍵）；用法與按鈕地圖見 .claude/skills/psa-game-ui/
                       watch.py（零輸入即時狀態監看 → tools/.cache/state.json，psa-hud 啟動；HUD 數值用 digitmatch.py 樣板比對為主、stat.ps1 OCR 補漏；state 只供顯示，不能當點擊依據）、serve.ps1（常駐 server，winenv.GuiServer 啟動；WSL 預設開、Windows 原生需 PSA_GUI_SERVER=1、=0 關閉）、bench.py（唯讀量測 / soak）、clients.py（PSA_EXE_MATCH 選視窗、每視窗狀態資料夾：主視窗 tools/.cache/、其他 tools/.cache/clients/<資料夾名>/）、accounts.py（視窗 → 帳號對照檢查，`accounts.py check` 不印帳號）、psawin.ps1（點擊鎖：每一下 click / drag / key 拿全域具名 Mutex，等超過 5 秒不點、exit 4）、failshot.py（所有停手 / 暫時性失敗當下存圖 → tools/.cache/fail/，同原因留 3 張、總量 200；`stats.py errors` 列出對應截圖）、test_*（離線測試）
    web/               靜態查詢網站：build.py 讀 knowledge/ 產生 site/（不進 git），static/ 是前端；deploy.sh 建置並發布到 Cloudflare Pages
    .cache/            匯出時的暫存（HotUpdate.dll 等），可刪
```
網站：Cloudflare Pages 專案 `kkfaq-psa-wiki`（尚未部署；`tools/web/deploy.sh`，只上傳 site/；可用 `CF_PAGES_PROJECT` 改專案名）。原始碼在 GitHub repo https://github.com/kkfaq2222-bit/PrimalSA-AI（公開；本專案由 kkfaq2222-bit 獨立維護，不再與其他帳號的 repo 同步）。仍照公開標準：不要 commit 帳號機密、角色私人資訊、`notes/` 遊玩紀錄；`GameClient/` 不進 repo。`.gitignore` 排除 `GameClient/`、`tools/.cache/`、`site/`、`notes/`。

## 3. 鐵則（必須遵守）
1. **`GameClient/` 是唯讀的**：不得新增、修改、刪除、搬移、重新命名其中任何檔案或資料夾，也不要把任何輸出寫進去。
   工具只能讀取它；所有產出寫到 `knowledge/` 或 `tools/.cache/`。遊戲自己更新 / 下載資源不在此限。
2. **不碰帳號機密**：不讀取、不輸出、不記錄密碼與登入資訊（例：`AssetBundles/savepwd.txt`、登錄檔 PlayerPrefs 的 `LastPassword_*`、`LastCdkey_*`、`LastAccount_*`）。需要登入時由人類操作。
   例外：斷線回到登入畫面時，可以自動按「登錄」（用遊戲已自動帶入的帳密；不點鑰匙 / 註冊、不把帳號名寫進 log）。
   多視窗例外（使用者 2026-10-16 授權）：本視窗在 `tools/gui/accounts.local.json`（本機檔、不進 git、只放帳號不放密碼）有對照時，
   可以清空**帳號欄**並打入本視窗帳號再按登錄（`gui.ps1 typeacct`，帳號不經參數、不寫 log；只在量過座標的 2880×1659 做）。
   **密碼欄絕不點、不清、不打、不讀內容**（只數深色像素判斷有沒有字）。沒有對照的視窗：單視窗照舊只按登錄；多視窗不自動登入、只通知人。
   密碼欄空、帳號欄清不掉、登錄出錯（密碼錯誤、封號、維護、驗證碼）、畫面不認得或連續失敗 3 次 → 停手（只停該視窗）通知使用者。實作見 `tools/gui/netwatch.py`。
3. **不付費**：不得進行任何儲值、購買鑽石、月卡、抽獎扣鑽等花真錢或鑽石的操作；`economy/recharge.md` 只供參考。
4. **不修改遊戲行為**：不改遊戲檔案、不注入、不寫入遊戲記憶體、不竄改 / 偽造封包、不使用加速或修改器。
   AI 只能透過正常的畫面操作（看畫面、點擊、鍵盤）遊玩。
5. **防腳本驗證要交給人類**：遊戲有伺服器觸發的答題驗證（NpcScript「防腳本驗證」、`quests/answers.md` 題庫，選項是圖片），
   公告寫明違規「最高永久封停所有帳戶」。**一旦出現答題 / 驗證視窗，立刻停止自動操作並通知使用者**，不要自己亂猜答案。
6. **不可多開繞限制**：客戶端強制單一執行個體；伺服器依「裝置」限制同時登入角色數（電腦版每台約 2 個）。不要嘗試繞過。
   遊戲本身支援在同一視窗多角色同時登入組隊（最多 5 個，UISwitchRole）。
7. **`knowledge/` 不要手動改**：它由工具產生，重新匯出會覆蓋。要補充攻略心得、遊玩紀錄，請另外放在 `notes/`（自行建立）。
8. 對使用者回報時說實話：查不到的資料就說查不到，推測的內容要標明是推測。

## 4. 遊戲規則摘要（玩之前先懂這些）
細節以 `knowledge/` 為準；以下是快速參考。

### 4.1 基本
- 回合制石器時代類 MMORPG。主城 / 新手村：**薩姆吉爾村**（地圖 1000），村長家（1006）接新手主線「初入石器」。
- 寵物等級上限 140（Config.petMaxLevel）；經驗表 Exp 列到 200 級（`pets/levels.md`）。角色可**轉生**（transLimit / trans 條件），2 轉以上線上每 10 分鐘得 1 點活力。
- 角色四項基礎點：體力 Vitality、腕力 Strength、耐力 Stamina、速度 Speed（升級配點，可自動加點 / 存方案）。
- 伺服器設定（開服公告）：1.5 倍基礎經驗；每次登入有離線時間（一般 2 小時）。

### 4.2 貨幣
| 代碼 | 名稱 | 用途 |
|---|---|---|
| 3 | 石幣 | 主要遊戲貨幣：NPC 商店、傳送、委託任務、合成。賣寵物 / 道具、答題、刷樓取得 |
| 1 | 鑽石 | 儲值貨幣（**AI 不得花費**） |
| 8 | 綁定鑽石 | 不可交易的鑽石 |
| 2 | 金幣 | 強化等 |
| 10 | 活躍度 / 活力 | 每日活動累積，合成、精工用 |
| — | 聲望 | 練寵掛機升級取得，用於回爐、合成、購買門票 |

### 4.3 戰鬥
- 回合制，雙方各最多 10 格：上排人物位置 0~4、下排寵物（主人位置 +5）。每回合所有人下指令後一起演出。
- 指令（EBattleCmdType）：攻擊、技能（精靈 / 寵物技能）、捕捉、道具、防禦、換騎寵、逃跑。有下指令時限（同引擎的時光石器實測約 90 秒），可開自動戰鬥。
- **屬性相剋**（地水火風，每隻合計 100）：地剋水、水剋火、火剋風、風剋地。戰場屬性 / 結界（物理、魔法）會改變傷害。
- 異常狀態：毒、麻痺、睡眠、石化、酒醉、混亂、暈眩；裝備有對應抗性（`items/` 能力欄的「抗毒、抗麻…」）。
- 遇敵率可用道具 / Buff 調整（例：月神守護降低遇敵率，`skills/role-buffs.md`）。
- 戰鬥錄影檔：`AssetBundles/{攻方}_{守方}_{時間}_{序號}.json`（base64 JSON），在遊戲裡看過錄影才會有。

### 4.4 寵物
- 系別 petType 0~28（烏力系、布伊系…融合系），100 = 敵方 / NPC 不可當寵物（`pets/README.md`）。
- 成長檔：體 / 腕 / 耐 / 速 檔數加總為「總檔」，越高越好；依石器時代通則，同種寵物個體各項會有約 ±2 的檔次差異（本遊戲未實測）。
- 寵物技能欄上限 7；技能可在寵物技能店 NPC 學（`skills/skill-teachers.md`），或用技能罐頭 / 道具。
- 取得：野外捕捉（公告：寵物依圖鑑抓捕）、抽獎蛋、領取點、任務獎勵、合成（`pets/pet-sources.md`、`economy/lottery.md`）。
- 部分寵物可騎乘，多數需要先學騎乘（`pets/ride.md`）。

### 4.5 地圖與移動
- 座標 (x, y) 格子制，畫面為斜角視角（x 往右上、y 往右下）。方向：0 下、1 左下、2 左、3 左上、4 上、5 右上、6 右、7 右下。
- 走到地圖出口座標就會傳送（`world/warps.md`）。另有城鎮傳送、付費傳送（例如 2000 石幣）、船 / 飛行交通 NPC（`world/transport.md`）。
- NPC 常在櫃檯後方，站在 3 格內即可點擊對話。
- 有些地圖禁止組隊、禁止看錄影、禁止逃跑或必須脫離戰鬥（`world/transport.md` 的「地圖限制」）。

### 4.6 任務與活動
- 任務類型：主線、支線、引導、每日、副本、突襲、職業 / 轉生、新手、家族任務（`quests/tasks.md` 有接取 / 回報 NPC 座標與條件）。
- 每日委託、藏寶圖（挖寶點 `world/transport.md`）、閻羅殿副本、族戰（莊園）等，見 `economy/activities.md`、`economy/notices.md`。

## 5. 操作遊戲畫面
操作前先讀 `.claude/skills/psa-game-ui/SKILL.md`（工具用法、操作迴圈、紅區）與同資料夾 `ui/README.md`（功能索引；按鈕座標、各面板內容依功能拆檔）。
工具：`bash tools/gui/gui.sh shot|click|drag|key|info|max|end`（WSL / Git Bash 手打用）；走路 / 補血用 `uv run --no-project python tools/gui/walk.py ...`、`heal.py`（兩邊指令相同）。座標用截圖座標；預設背景操作（不搶前景，點擊時游標瞬移約 0.15 秒）；用過 `fg` / `max` 後要跑 `end` 把前景還給使用者。

**即時狀態**：開著 psa-hud 時有 `watch.py` 在背景零輸入監看（只送 pixel / info / digitmatch / stat），`uv run --no-project python tools/gui/watch.py --get` 可讀；它只是參考，點擊前仍要現場讀圖，`idle` 不代表沒有驗證視窗；出現 `verify_suspect` / alerts 就依鐵則 5 停手通知。只有開 psa-hud 的那個 session 管理它，兩個平台同時開 session 時只有一邊有即時狀態。

## 5.2 在 Claude 桌面 App（Windows 原生）執行
專案也可以用 Claude 桌面 App 的 Claude Code 開（路徑 `C:\games\PrimalSA-AI`，shell 是 Git Bash，沒有 wslpath、沒有 /mnt/c）。工具已兼容，差異如下：
- **前置**：安裝 uv for Windows：`winget install astral-sh.uv`（Python 由 uv 自動管理）。`powershell.exe`（Windows PowerShell 5.1）系統內建。
- **指令**：`uv run --no-project python tools/gui/walk.py ...`、`heal.py`、`tools/query/psa.py` 與 WSL 完全相同；`bash tools/gui/gui.sh ...` 在 Git Bash 也能用（用 cygpath 換路徑）。
- **psa-hud mod**：stat.ps1 / watch.py 路徑由 session cwd 推算，不用改程式；session.start 會自動 spawn `tools/gui/watch.py`（即時狀態 → `tools/.cache/state.json`，pane 頂端顯示狀態行；`/psa-hud watch on|off` 開關）。載入方式在使用者層級設定（不放進專案）：Windows 版的 `CLAUDE_CODE_PLUGIN_DIRS` 設成 `C:\games\PrimalSA-AI\tools\mods\psa-hud`（WSL 版是 `/mnt/c/games/PrimalSA-AI/tools/mods/psa-hud`；兩邊各有自己的 settings.json）。
- 其他：Windows 原生 Python 的 stdout 預設 cp950，walk.py 已自行改成 UTF-8；自己寫 Python 呼叫 gui.ps1 時用 `winenv.run_ps()`。
- 紅區、背景操作、驗證視窗等規則與 WSL 相同。
- 實測狀態：WSL 完整驗證；Windows 原生用 Windows 版 Python 驗過 `walk.py --plan`、`gui info / shot / pixel`、`stat.ps1`（Git Bash 環境本身未實測）。

## 5.4 每日任務（委託接取）
醫院（1005）委託接取 NPC：5 頁 × 2 項，全部合成提交（5/5）拿「裝備升級石」。材料在薩村 1009、漁村 2009 的 24 小時店買（每個 500 石幣，合成 1000）。
```
uv run --no-project python tools/gui/dailyrun1920.py --client kkfaq11111 --role 1          # 目前角色跑一輪
uv run --no-project python tools/gui/dailyrun1920.py --client kkfaq22222 --roles 2,3,4,5   # 自動切角色接力
```
- 前置：該角色背包 15 格、公共倉庫 20 格清空；先停掉同一個客戶端的一條龍 / 練等（會搶畫面）。
- 流程：讀 5 頁 → 查配方 → 先買要存倉的（存公共倉庫）、再買留身上的（最多 13 種，留 2 格放成品；第 1 頁材料一律留身上）→ 回醫院逐頁領料 / 合成 / 提交。
- 防呆：兩項都是綠色 1/1 才提交；第 5 頁後用「合成鈕消失 / 計數 5/5 / 背包有裝備升級石」三訊號至少 2 個成立才算完成；存取前核對浮窗名稱；公共分頁亮黃才存取。
- 記錄：`tools/.cache/daily-live.log`（每角色耗時）、`daily-done-<client>-r<N>.json`（已買、格位，重跑不重買）。不停手時一個角色約 13~15 分。
- 24 小時店沒賣的材料（合成品、胡椒 1~3 等遠程店）目前不支援，規劃會標「？」，合成時防呆停手。

## 5.3 一條龍（fullrun）與看門狗
一輪 = `train`（練到 131）→ `wait131` → `stopenc` → `ledger` → `prebag` → `adult`（成人儀式先做）→ `quests` → `riddle` → `katan` → `dino` → `gate` → `rebirth` → `gift`（開 N 轉新手禮盒、吃 2 倍智慧果 / 離線水晶、安撫之素 / 誘餌存共用倉庫）→ `organize` → `clear` → `prep`（抓格魯西斯坐騎、鎖定騎寵、領個人倉庫第 1 隻當戰寵）→ `grind`（練 1~131）。
```
uv run --no-project python tools/gui/fullrun_watchdog.py --client kkfaq11111                      # 跑一輪，出錯自動重啟 / 卡住偵測
uv run --no-project python tools/gui/fullrun_watchdog.py --client kkfaq11111 --loop --max-rounds 2 # 自動接下一輪（轉數到 --max-trans 5 或輪數到就停）
```
- 狀態檔 `tools/.cache/fullrun-<client>.json`（已完成階段）；停手旗標 `fullrun-flag-<client>.json`；`PAUSE-<client>` 暫停。
- 恐龍博士只有「接任務」組隊，交任務單人；猜謎三兄弟、卡坦組隊交。龍王的守護沒了不停手。
- 開背包 / 人物 / 寵物等面板一律「打開 → 偵測 → 沒成功 ESC 復原再重來」；道具浮窗按鈕與 OCR 做法見 PLAYBOOK 第 5 節。

## 5.1 怎麼查知識庫
1. 先看 `knowledge/README.md` 的分類目錄。
2. **用名稱 grep**（繁中、簡中、韓文都可；畫面上看到韓文就搜韓文）：
   ```
   grep -rn "烏力" knowledge --include=*.md
   ```
3. **查詢工具**（交叉關聯，推薦）：
   ```
   uv run --no-project python tools/query/psa.py find 薩姆吉爾
   uv run --no-project python tools/query/psa.py item 小的爪        # 能力 / 誰賣 / 怎麼合成 / 用途
   uv run --no-project python tools/query/psa.py pet 烏力           # 成長檔 / 屬性 / 技能 / 取得
   uv run --no-project python tools/query/psa.py npc 老村長         # 位置 / 販售 / 腳本對話 / 任務
   uv run --no-project python tools/query/psa.py map 1000           # NPC / 出口 / 入口
   uv run --no-project python tools/query/psa.py steps 2031         # 任務每一步：NPC @ 座標、對話 / 戰鬥 / 打怪（單人逃跑解任務用）
   uv run --no-project python tools/query/psa.py route 1000 92 99 1006   # 跨地圖路線（只算地圖出口）
   uv run --no-project python tools/query/psa.py grid 1000 92 99 10      # 座標附近通行格
   ```
   找不到路線時通常要搭船 / 用傳送服務；完全不相通時會立即回報，地圖相通但走不到時約需 10 秒。
4. 要精確欄位值就查原始表：`knowledge/data/tables/<表名>.jsonl`（一行一筆 JSON）。
5. ID 慣例：SkillBattle ID = skillId×1000+等級；戰鬥 Buff ID = type×1000+level；地圖 ID 以 `mapdata_<ID>` 檔名為準；
   道具圖示 Sprite 名 = Item.imageId；寵物頭像 Sprite 名 = Monster.imageId。

## 6. 更新知識庫（遊戲更新後）
遊戲啟動時會熱更新 `configs.assetbundle`、`hotupdate.dll.assetbundle` 等。更新後在專案根目錄執行：
```
uv run --no-project --with UnityPy python tools/extract/extract.py
```
約 10~30 秒，會重新產生 `knowledge/` 全部內容（schema 也會從新的 HotUpdate.dll 重抽，不用手動改欄位）。
只想重產 Markdown：`uv run --no-project python tools/extract/docs.py`。

## 7. 開發慣例
- Python：查詢工具只用標準函式庫；匯出器需要 UnityPy（用 `uv run --with UnityPy` 臨時載入，不要裝進系統）。本機沒有 `python` / `py` 指令，一律用 `uv run`。
- C#：用 Windows 內建 `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`，只支援 C# 5（不能用 `$""`、`?.`、`nameof`、`out var`）。
- 程式註解與文件用繁體中文。
- **跨平台（WSL 與 Windows 原生都要能跑）**：不寫死 `/mnt/c` 或 `C:\games\...`；Python 呼叫 PowerShell 一律經 `tools/gui/winenv.py`（`run_ps` / `to_windows`，自動判斷 WSL / Windows）；bash 腳本路徑換算先試 `wslpath -w`、再 `cygpath -w`。文件裡的指令寫成兩邊都通（`uv run --no-project python ...`）。
- 格式逆向細節：`knowledge/overview/client-files.md`。同引擎的《時光石器》工具 `C:\games\SA-tool`（CLAUDE.md 有大量逆向筆記）可作參考，但兩個遊戲的設定表欄位不同，不要直接套用它的 schema。
