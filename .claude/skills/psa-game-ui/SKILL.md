---
name: psa-game-ui
description: Use when operating the PrimalSA (精靈王石器) game client by screen — taking screenshots, clicking buttons, opening panels, reading what is on screen, or deciding which UI element does what before playing.
---

# 精靈王石器 介面操作

## 概觀
AI 只透過「截圖 → 看圖 → 點擊 / 按鍵 → 再截圖確認」操作遊戲（AGENTS.md 第 3 節第 4 條）。
工具核心是 `tools/gui/gui.ps1`（Windows PowerShell）。兩種環境都能用：WSL（Ubuntu）的 Claude Code、Claude 桌面 App（Windows 原生，Git Bash 當 shell）。
- 手打指令用 `bash tools/gui/gui.sh ...`（WSL / Git Bash 都行；自動用 wslpath 或 cygpath 換路徑）。
- Python 腳本（`walk.py`、`heal.py`）兩邊指令相同：`uv run --no-project python tools/gui/walk.py ...`，它們直接呼叫 `powershell.exe -File gui.ps1`（平台判斷與路徑換算在 `tools/gui/winenv.py`），不經 bash。
- Windows 原生需先裝 uv：`winget install astral-sh.uv`；設定細節見 AGENTS.md「在 Claude 桌面 App（Windows 原生）執行」。
**背景操作（預設）**：`shot` 用 PrintWindow 背景截圖；`click`/`dclick`/`drag` 不搶前景，只把游標瞬移到目標點完再移回（約 0.15 秒），`key` 完全不動游標。使用者可以同時用其他視窗。
- 原理：PostMessage 假焦點 + 按鍵訊息；Unity 的滑鼠位置讀真實游標，所以游標仍要移過去（細節見 gui.ps1 開頭註解）。
- **使用者怎麼動都不影響自動操作**：點擊那 0.15 秒用低階滑鼠鉤子吞掉使用者實體滑鼠的移動 / 按下（放開放行），游標一定停在目標上；鍵盤訊息直接送遊戲視窗，使用者打字、切視窗都不干擾。不用等使用者閒置。
- 背景點擊沒反應時改用 `fg click ...`（舊的前景模式：把遊戲拉到前景並留著，**用過 `fg` / `max` 一定要跑 `end`** 還原）。
按鈕位置與每個畫面的內容見同資料夾 [ui/README.md](ui/README.md)（索引，依功能拆檔）。

## 工具
```bash
bash tools/gui/gui.sh info                 # 視窗大小
bash tools/gui/gui.sh max                  # 最大化 → 客戶區 2880×1659（ui/ 座標的基準）
bash tools/gui/gui.sh shot [out.png]       # 預設存 tools/.cache/shot.png，再用 Read 看圖
bash tools/gui/gui.sh click X Y [right]
bash tools/gui/gui.sh dclick X Y          # 雙擊（倉庫存入）
bash tools/gui/gui.sh drag X1 Y1 X2 Y2
bash tools/gui/gui.sh key '{ESC}'          # SendKeys 語法：{ENTER} {TAB} 一般字元
bash tools/gui/gui.sh fg click X Y         # 前景模式備案（背景點擊沒反應時）
bash tools/gui/gui.sh end                  # 用過 fg / max 後還原前景視窗與游標（背景模式跑了也無害）
bash tools/gui/gui.sh seq "click 763 760; wait 400; shot"   # 同一個行程連跑多個動作（快）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\gui\stat.ps1   # （WSL 要用 "$(wslpath -w tools/gui/stat.ps1)"；Windows / Git Bash 直接給 Windows 路徑，在專案根目錄執行）OCR 讀 HUD → 一行 JSON（等級 / HP / MP / 寵物 / 地圖座標），不用看圖、不搶焦點
bash tools/gui/mirror.sh                   # 給使用者看的即時畫面鏡像視窗（DWM 縮圖：幀數同遊戲、CPU ≈ 0；可縮放、右鍵 / 標題列選單置頂）
bash tools/gui/gui.sh pixel "X,Y X,Y"      # 背景截圖讀像素顏色（腳本判斷畫面狀態用，例：遇敵開關）；seq 裡用 X,Y/X,Y
bash tools/gui/gui.sh seq "click 1340 65; waitpix 1500 1290,97,197,73,49; ifok click 259 314"   # 輪詢到面板出現（點顏色符合）才點下一步，取代固定 wait
bash tools/gui/gui.sh seq "click 459 456; waitstill 4000"   # 點地面走路後等鏡頭停下來（剛好等到走完）
uv run --no-project python tools/gui/walk.py 1000 81 66 [--exit 1005]   # 走到某地圖座標：OCR 讀起點 → maps.bin 自動找路 → 連點 + waitstill → 終點驗證（--exit = 終點是出口）
uv run --no-project python tools/gui/walk.py --path "1000:86,88 84,81 83,73 81,66" [--exit 1005]   # 照手動 waypoint 走（沒有通行格資料的圖用）
uv run --no-project python tools/gui/walk.py --plan 1000 81 66 [--from 92,99]   # 只印找路結果（每段要點的截圖座標），不動
uv run --no-project python tools/gui/heal.py [--spot 波拉島] [--watch --hp 40 --mp 20 --every 15]   # 回村補血再回練功點（約 21～24 秒）；--watch 看血條比例（%）自動補
uv run --no-project python tools/gui/petwatch.py [--once] [--interval 30] [--target-level 77]   # 監測 5 人金布伊等級，≥ 門檻換回迪基格斯（內含補血檢查 + 維持原地遇敵，不要和 heal.py --watch 同跑）
```

操作 log：click / dclick / drag / key / max / end（含 seq 裡的）以及 walk.py / heal.py / quest.py 的動作，都會寫一行到 `tools/.cache/actions.log`（只留最新 100 行，不進 git；寫入程式 `tools/gui/actlog.py`），背景記錄用，psa-hud pane 不顯示它（pane 顯示下面的錯誤 / 改進紀錄）。想附註用途：`PSA_NOTE="對話確認" bash tools/gui/gui.sh click 948 461`（Python 呼叫 `walk.gui(..., note="...")`）；shot / pixel / wait* 不記。

錯誤 / 改進紀錄（psa-hud pane 顯示這個）：遇到錯誤、失誤、卡關（點錯、工具中斷、誤判、漏做、白等）時，**當下**用 `tools/gui/errlog.py` 記一筆；之後改了程式 / 流程 / 文件，再補上改進。沒改進的會在 pane 標「待改進」。
```
uv run --no-project python tools/gui/errlog.py add "錯誤描述" [--fix "改進"] [--source quest]   # 印出 #id
uv run --no-project python tools/gui/errlog.py fix <id|last> "改進內容"
uv run --no-project python tools/gui/errlog.py list
```
存 `tools/.cache/errlog.jsonl`（最新 100 筆，不進 git）；Python 裡 `import errlog; i = errlog.add(...); errlog.fix(i, ...)`。一筆寫一件事、寫具體（發生什麼 + 為什麼），改進寫「改了什麼檔 / 之後怎麼做」。
- 遊戲**不能最小化**（Unity 最小化不繪製）；每個指令遇到最小化會用 SW_SHOWNOACTIVATE 還原（不搶焦點）。放在其他視窗後面沒關係。
- **座標 = 截圖座標**：截圖固定縮成客戶區的 1/2（`-Scale 2`，不隨視窗大小變），click 內部 ×2。實測客戶區 2880×1659 → 截圖 1440×830。
- `ui/` 的座標只在這個大小有效。**每次開始操作先跑 `info`**，不是 2880×1659 就跑 `max`；`max` 後仍不同（換螢幕 / 解析度）時不要等比例換算（UI 縮放與錨點會變，例：1436×1644 時背包在 558,790），以新截圖重新目測。
- **1920×1080 螢幕**（`max` 後 `client=1920x1017`、截圖 960×508）：用 [ui/layout-1920x1017.md](ui/layout-1920x1017.md) 的座標；`stat.ps1`、`walk.py`、`heal.py` 會自動切換（`tools/gui/layout.py`）。
- 只有 `fg` / `max` 會讓遊戲佔著前景（使用者打字可能打進遊戲），之後要跑 `end`。習慣上任務結束仍跑 `end`，沒狀態時它什麼都不做。
- 背景模式 `dclick`（倉庫存入）、`key` 打字（含中文）都實測可用（2026-10-09）。`key` 語法：一般字元 = 打進輸入框；`{ESC}` `{BS}` 等 = 按鍵；`{a}` = 只按 a 鍵（快捷鍵用）。
- `gui.ps1` 必須保持 **UTF-8 with BOM**（PowerShell 5.1 讀無 BOM 檔會把中文當 Big5，整支解析失敗）。

## 移動：先用 walk.py（不要自己算座標點地面）
- **鏡頭高度一律拉到最左**（設置 → 畫面設置，見 [ui/setting.md](ui/setting.md)）：walk.py 的每格位移只在這個鏡頭下準，與視窗大小無關；滾輪會改鏡頭高度，**不要在遊戲畫面上滾滾輪**。走路 / 補血一直走錯格時先檢查這個。
- 要走到某格 → `walk.py <地圖> <x> <y>`；要走進出口 → 加 `--exit <下一張地圖>`；要點 NPC → 腳本裡用 `walk.npc_steps` / `walk.talk_npc`（直接點 NPC 會自己走過去開對話）。
- walk.py 做的事：先點引子 1215,18（換地圖後第一下左鍵會被吃掉）→ OCR 讀起點 → 有 `knowledge/data/maps.bin` 通行格就找路
  （每段 ≤ 10 格、點擊不落在左側面板等 UI 上、離牆遠一點、點擊次數少的方向優先）→ 一個 `seq` 連點，每段之間 `waitstill` 等鏡頭停，
  某段沒動（`nomove`）就用 `ifok` 跳過後面 → 終點 OCR 驗證 → 沒到就從目前位置重新找路、改慢速逐段走（每段 OCR，沒動就格數減半）。
- 通行格對不上的圖（例：醫院 1005）會自動改成直線分段讓遊戲自己繞；固定路線可以用 `--path` 寫死 waypoint。
- 原地遇敵開著時隨時會進戰鬥（快速戰鬥只有頭上綠色 VS 牌）；戰鬥中傳送會被擋，走路會不會被擋未實測 → 要移動先關遇敵、等 VS 牌消失（heal.py 的做法），走完記得開回來。
- 常數（每格位移、最多格數、UI 禁點範圍、每格秒數）集中在 walk.py 開頭；規則說明見 [ui/home.md](ui/home.md)「走路」。
- 在 Python 腳本裡：`import walk`（同資料夾），`walk.walk_to(1000, 81, 66, exit_map=1005)`、`walk.walk_path(...)`、`walk.plan(...)`、`walk.prime()`（heal.py 是範例）。

## 功能索引（要做某件事時先讀對應檔）
| 要做的事 | 讀這個 |
|---|---|
| 認主畫面按鈕、收合、面板關不掉 | [ui/home.md](ui/home.md) |
| 5 個角色組一隊 | **`/psa-quick-team` skill**（介面參考 [ui/team.md](ui/team.md)） |
| 解散隊伍 | **`/psa-disband-team` skill**（介面參考 [ui/team.md](ui/team.md)） |
| 確認誰是「當前」角色 | [ui/team.md](ui/team.md) |
| 看角色屬性 / 抗性 / 潛力點 | [ui/role.md](ui/role.md) |
| 看任務進度、任務詳情、自動巡路解任務（`tools/gui/quest.py --task 任務名`；檢測方針：黃色「?」優先，否則 OCR 核對追蹤列表任務名再點；`ocr.ps1` / `findmark.ps1`） | [ui/quest.md](ui/quest.md) |
| 背包、道具、倉庫、材料圖鑑 | [ui/bag.md](ui/bag.md) |
| 寵物出戰 / 騎乘 / 休息、寵物技能 | [ui/pet.md](ui/pet.md) |
| 傳送到別的地圖 / 練級點 | [ui/transfer.md](ui/transfer.md) |
| 遊戲設定、離線時間 | [ui/setting.md](ui/setting.md) |
| 自動戰鬥、補血、抓寵、遇敵 | [ui/ass.md](ui/ass.md) |
| 聊天、信件、通知、排行榜、家族 | [ui/social.md](ui/social.md) |
| 商城、交易所、抽獎（多為紅區） | [ui/shop.md](ui/shop.md) |
| 「網路異常，是否重連?」提示、斷線後登入畫面（`tools/gui/netwatch.py`；已接進 quest / petwatch / heal --watch；點確定會回登入畫面 → 自動按「登錄」重登（使用者授權，只按登錄；欄位空 / 錯誤提示 / 連 3 次失敗才停手）） | [ui/network.md](ui/network.md) |
| 沒見過的畫面、答題驗證 | [ui/todo.md](ui/todo.md) |
全部清單與「依情境找」見 [ui/README.md](ui/README.md)。學到新畫面或新流程時，照 README 的「新增 / 更新規則」寫進對應檔並更新兩邊索引。

## 操作迴圈
1. `shot` → Read 圖，先判斷**目前在哪個畫面**（主畫面 / 某面板 / 對話 / 戰鬥 / 驗證）。
2. **速度**：遊戲響應很快（實測傳送面板 / 分頁 / NPC 對話框 / 遇敵圖示都在 0.05～0.15 秒內出現；傳送 Loading 1.0～2.2 秒）；每次呼叫 gui.sh 要多花約 0.4 秒啟動 PowerShell。
   - 腳本裡能用 `waitpix`（等指定點變成某顏色）/ `waitstill`（等走路停）就不要固定 `wait`；`ifok` / `ifnok` 依上一個 waitpix 結果決定做不做，面板沒出現就不會點穿。
   - **換地圖後第一下左鍵會被吃掉**：先點 1215,18（狀態列空白）當引子（ui/home.md「走路」；walk.py `PRIMER`）。
   - **已知流程**（座標都驗證過）：用 `seq` 把多個動作串成一次呼叫，動作之間 `wait 150～500`，只在**分歧點**（要判斷畫面才能決定下一步）和**結尾**截圖。
   - **陌生畫面**：一次一個動作，`seq "click X Y; wait 400; shot"`，看完再決定下一步。
3. 不要盲點：至少在結尾截圖驗證；流程中途需要事後查錯的，在 seq 裡多存一張 `shot <路徑>`（不用 Read，失敗時再看）。
4. **面板開著時只點面板範圍內**：點面板外會穿透到遊戲場景（走路、點到 NPC）。要重開面板先 ESC。
5. 關閉面板：優先 `key '{ESC}'`；ESC 關不掉的（聊天面板、小地圖浮窗、收合狀態）見 ui/home.md「關閉方式」。
6. 收合鈕（`<` `>`）按下後會**換位置**，再點同一座標會點空，要重新截圖找。
7. 任務結束（成功、失敗或停下來問使用者）→ `bash tools/gui/gui.sh end`。

## 紅區（絕對不點）
| 東西 | 原因 |
|---|---|
| 贊助、商城的「購買」、LuckyCard「抽1次 / 抽10次 / 購買獎券」、任何 NT$ / 鑽石價格鈕 | 付費（鐵則 3） |
| 設置面板底部：全員登出、離線掛機、回記錄點 | 會讓角色登出或傳送，改變全隊狀態（回記錄點＝無確認框直接回村長家，使用者交代時才按） |
| 背包道具的「丟棄」、刪除管理 | 不可逆 |
| 外掛（ASS）裡任何勾選、下拉選單、數值與 SET 鈕；主畫面「遇敵」 | 會改變自動戰鬥 / 遇敵行為。開面板看可以，改任何東西都要使用者同意 |
| 設置面板「解決異常」 | 作用未知，要先問 |
| 地圖傳送的目的地 | 會整隊傳送（實測不扣石幣），屬遊玩決策；英雄戰場有儲值門檻，不點 |
| 交易所的上架 / 購買 | 交易 |

開面板、切分頁、點道具看說明都可以自由做。
花**石幣**的操作（NPC 商店、傳送、商城石幣分頁）不違反鐵則，但屬於遊玩決策，只有在執行使用者交代的任務時才做。
任務條目（點了可能自動尋路）屬於執行任務，使用者沒交代任務時不點。

**出現答題 / 驗證視窗（npcanswer，選項是圖片）→ 立刻停手並通知使用者**（鐵則 5）。
**出現「網路異常，是否重連?」→ 跑 `netwatch.py --once`（或腳本內建 guard）點確定；點完會回到登入畫面，netwatch 會自動按「登錄」（使用者授權：只點登錄 / 一鍵全登，帳密由遊戲自動帶入，AI 絕不輸入或讀取帳密；帳密欄空、登錄後有任何提示 / 驗證視窗、連續 3 次失敗 → 停手通知使用者）**（[ui/network.md](ui/network.md)）。

## 判讀注意
- 截圖是視窗自己的畫面，不會截到通知。背景點擊的訊息直接送進遊戲視窗，遊戲被其他視窗蓋住也點得到，不會點到別的視窗。
- 背景點擊如果 UI 沒收到（例：假焦點失效），點擊會**穿透到地面讓隊伍走路**、原地遇敵也會被取消；看到這種情況就改 `fg`。
- 角色頭頂名字很密集、會互相重疊，不要靠名字定位自己；自己腳下有藍色光圈。
- 右上角「地圖名 + 地圖ID:x,y」是目前位置，可直接對 `tools/query/psa.py map/route/grid`。
- 本帳號是多角色同時登入（DKB0…）。目前操作的角色：人物資訊 / 背包左欄有黃框的頭像、設置面板的「暱稱」、切換角色面板標「當前」的那個。面板左欄可切換正在看的角色。
