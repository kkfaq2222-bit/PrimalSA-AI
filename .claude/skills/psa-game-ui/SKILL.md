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
  - **常駐 server（WSL 預設開；Windows 原生需 `PSA_GUI_SERVER=1`；`PSA_GUI_SERVER=0` 關閉）**：長程序（quest / heal / petwatch / walk 主流程）已呼叫 `winenv.enable_server()`；會走常駐 `serve.ps1`（WSL 預設；Windows 原生未量測，設 `PSA_GUI_SERVER=1` 才走）（每個程序各自一個，程序結束一定會一起結束：atexit / quest.main finally 送 quit + 關 stdin、卡住時 kill 並用 Windows PID taskkill、SIGTERM / SIGHUP 也先關、閒置 3 分鐘自動結束、下次起 server 會清掉「擁有者已死」的殘留；pixel 0.6 s → 0.09 s）。`PSA_GUI_SERVER=0` 一律關閉。`gui.sh` 與 psa-hud 的 stat.ps1 維持一次性（psa-hud 另外自動 spawn watch.py，由 watch 自己用常駐 server，見下方「即時狀態監看」）。server 的 stderr 在 `tools/.cache/gui-server.err`。孤兒 server 查法：`powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | ? { $_.CommandLine -match 'serve\.ps1' } | select ProcessId"`，再 `taskkill.exe /pid <pid> /f`（登記檔 `tools/.cache/gui-server.pids`；`uv run --no-project python -c "import sys; sys.path.insert(0,'tools/gui'); import winenv; print(winenv.reap_orphans())"` 手動清擁有者已死的）。
- Windows 原生需先裝 uv：`winget install astral-sh.uv`；設定細節見 AGENTS.md「在 Claude 桌面 App（Windows 原生）執行」。
**背景操作（預設）**：`shot` 用 PrintWindow 背景截圖；`click`/`dclick`/`drag` 不搶前景，只把游標瞬移到目標點完再移回（約 0.15 秒），`key` 完全不動游標。使用者可以同時用其他視窗。
- 原理：PostMessage 假焦點 + 按鍵訊息；Unity 的滑鼠位置讀真實游標，所以游標仍要移過去（細節見 gui.ps1 開頭註解）。
- **使用者怎麼動都不影響自動操作**：點擊那 0.15 秒用低階滑鼠鉤子吞掉使用者實體滑鼠的移動 / 按下（放開放行），游標一定停在目標上；鍵盤訊息直接送遊戲視窗，使用者打字、切視窗都不干擾。不用等使用者閒置。
  - 鉤子執行緒各自保存自己的 hook（自己裝自己拆）、最多活 2 秒自動解除；click / dclick / drag 的 BgBegin…BgEnd 在 try/finally 內，出錯也會還原游標並停 Guard；Stop Join 逾時寫 actions.log。離線測試：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\gui\test_guard.ps1`。
- 背景點擊沒反應時改用 `fg click ...`（舊的前景模式：把遊戲拉到前景並留著，**用過 `fg` / `max` 一定要跑 `end`** 還原）。
按鈕位置與每個畫面的內容見同資料夾 [ui/README.md](ui/README.md)（索引，依功能拆檔）。

## 工具
```bash
bash tools/gui/gui.sh info                 # 視窗大小
bash tools/gui/gui.sh max                  # 最大化 → 客戶區 2880×1659（ui/ 座標的基準）
bash tools/gui/gui.sh shot [out.png]       # 預設存 tools/.cache/shot.png，再用 Read 看圖（不能存到 /tmp，WSL 路徑會 GDI+ Save 例外；用預設路徑或 Windows 可寫路徑）
bash tools/gui/gui.sh click X Y [right]
bash tools/gui/gui.sh dclick X Y          # 雙擊（倉庫存入）
bash tools/gui/gui.sh drag X1 Y1 X2 Y2
bash tools/gui/gui.sh key '{ESC}'          # SendKeys 語法：{ENTER} {TAB} 一般字元
bash tools/gui/gui.sh fg click X Y         # 前景模式備案（背景點擊沒反應時）
bash tools/gui/gui.sh end                  # 用過 fg / max 後還原前景視窗與游標（背景模式跑了也無害）
bash tools/gui/gui.sh seq "click 763 760; wait 400; shot"   # 同一個行程連跑多個動作（快）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\gui\stat.ps1   # （WSL 要用 "$(wslpath -w tools/gui/stat.ps1)"；Windows / Git Bash 直接給 Windows 路徑，在專案根目錄執行）OCR 讀 HUD → 一行 JSON（等級 / HP / MP / 寵物 / 地圖座標），不用看圖、不搶焦點
uv run --no-project python tools/gui/bench.py [--ab --old-dir 舊版目錄 | --srv-ab | --server | --soak] [-n 5] [--only stat,ocr_zooms]   # 唯讀量測各指令耗時（中位數 / min / max）；--ab 與舊版交錯並比對輸出、--srv-ab 一次性 vs 常駐 server 交錯、--soak 長跑看 GDI / 記憶體；只在沒有任務在跑時用
uv run --no-project python tools/gui/test_binarize.py   # ocr / stat 二值化（LockBits）與舊 GetPixel 版逐位元組比對（離線）；test_netwatch.py = netwatch 三態 mock 測試；test_errlog.py = errlog 多程序寫入；其餘離線測試：test_winenv_server.py（server 協定）、test_quest_fight.py、test_ass.py（皆 `uv run --no-project python tools/gui/<檔名>`）、test_guard.ps1（Guard）
bash tools/gui/mirror.sh                   # 給使用者看的即時畫面鏡像視窗（DWM 縮圖：幀數同遊戲、CPU ≈ 0；可縮放、右鍵 / 標題列選單置頂）
bash tools/gui/gui.sh pixel "X,Y X,Y"      # 背景截圖讀像素顏色（腳本判斷畫面狀態用，例：遇敵開關）；seq 裡用 X,Y/X,Y
bash tools/gui/gui.sh seq "click 1340 65; waitpix 1500 1290,97,197,73,49; ifok click 259 314"   # 輪詢到面板出現（點顏色符合）才點下一步，取代固定 wait
bash tools/gui/gui.sh seq "click 459 456; waitstill 4000"   # 點地面走路後等鏡頭停下來（剛好等到走完）
uv run --no-project python tools/gui/walk.py 1000 81 66 [--exit 1005]   # 走到某地圖座標：OCR 讀起點 → maps.bin 自動找路 → 連點 + waitstill → 終點驗證（--exit = 終點是出口）
uv run --no-project python tools/gui/walk.py --path "1000:86,88 84,81 83,73 81,66" [--exit 1005]   # 照手動 waypoint 走（沒有通行格資料的圖用）
uv run --no-project python tools/gui/walk.py --plan 1000 81 66 [--from 92,99]   # 只印找路結果（每段要點的截圖座標），不動
uv run --no-project python tools/gui/heal.py [--spot 波拉島] [--watch --hp 40 --mp 20 --every 15]   # 回村補血再回練功點（約 21～24 秒）；--watch 看血條比例（%）自動補（watch 活著時讀 state.hud 的 hpPct / mpPct，0 次額外 stat；不可用退回現場 stat；疑似驗證視窗暫停）
uv run --no-project python tools/gui/heal.py --no-return   # 補完血停在醫院，不傳回練功點、不開遇敵（解任務被打飛後用）
uv run --no-project python tools/gui/quest.py --solo --task 任務名   # 單人逃跑：遇怪按逃跑，到 NPC ESC 對話框退出碼 20，被打飛退出碼 21；--fight = 戰鬥步按自動戰鬥，退出碼 0 才是打贏（35 沒贏 / 36 不確定 / 33 對話無進展 / 34 不同圖，見 /psa-quest-solo）
uv run --no-project python tools/gui/team.py status|check|disband   # 隊伍狀態（唯讀）/ 檢查 1 隊長 + 4 隊員（0 = 符合）/ 解散（當前須為隊長）；退出碼 40～47 見 ui/team.md；名字用 namematch.py 整名樣板比對（`namematch.py learn|read|list`，見 ui/team.md）；form 未做
uv run --no-project python tools/gui/char.py current|switch DKBO2|ensure DKBO   # 當前角色：唯讀讀取 / 切過去並驗證（點前 namematch 確認名字 + 線上，點後等加載 → HUD → 重開面板確認；成功寫 current-char.json；最後一行 JSON 含 changed）；退出碼 60～65 見 ui/team.md；不會自動切回 DKBO，呼叫端負責 ensure；離線測試 test_char.py（假面板在 fake_switch.py，test_team 共用）
uv run --no-project python tools/gui/petwatch.py [--once] [--interval 30] [--target-level 77]   # 監測 5 人金布伊等級，≥ 門檻換回迪基格斯（內含補血檢查 + 維持原地遇敵，不要和 heal.py --watch 同跑）
```

操作 log：click / dclick / drag / key / max / end（含 seq 裡的）以及 walk.py / heal.py / quest.py 的動作，都會寫一行到 `tools/.cache/actions.log`（只留最新 100 行，不進 git；寫入程式 `tools/gui/actlog.py`），背景記錄用，psa-hud pane 不顯示它（pane 顯示下面的錯誤 / 改進紀錄）。想附註用途：`PSA_NOTE="對話確認" bash tools/gui/gui.sh click 948 461`（Python 呼叫 `walk.gui(..., note="...")`）；shot / pixel / wait* 不記。

即時狀態監看（第 2～7 階段已完成）：psa-hud 的 session.start 會自動 spawn `watch.py`（只管自己 spawn 的子程序：結束退避 2/5/15/30/60 s 重開、連續 5 次跑不到 30 s 停並顯示「監看啟動失敗」、退出碼 3 / 6 只讀、卡住 10 s（starting 45 s）return() 後重開），pane 頂端狀態行每 1 s 讀 state.json（label + 「N 秒前」>3 s 才顯示 + 監看未執行 / 另一平台 / 啟動失敗提示）；`/psa-hud watch on|off|status` 開關（持久化 `tools/.cache/psa-hud.json`，off 會呼叫 `watch.py --stop` 且不再重開；兩平台同時開 session 時只有一邊有即時狀態，另一邊在對方結束後要 `/psa-hud watch on`）。等級 / HP 行：watch 活著時讀 `state.hud`（watch 每 3 s 讀 HUD：`digitmatch.py` 字元樣板比對第一順位〔樣板 `tools/.cache/digit-tpl/<版面>.json`，約 95 ms〕，讀不出的欄位才用 stat.ps1 補，`state.hud.src` 標每欄來源 digit / ocr；每分鐘最多一次用 stat 當標籤自動補樣板〔兩張圖相同、與 digit 讀值一致或 digit 為 None、與既有樣板不衝突、每字最多 6 變體〕，沒有樣板的版面〔如 1920×1017〕先全走 stat 並背景累積，不動視窗；`watch.py --bench N` 會印來源計數；只在主畫面 / 行走 / 快速戰鬥讀；被蓋住、完整戰鬥、最小化時保留舊值並標 stale，pane 顯示「（原因 · N s 前）」，欄位帶各自時間戳），HUD 此時不再 spawn stat.ps1；watch 不在才退回 15 s 一次的 stat.ps1。手動：`uv run --no-project python tools/gui/watch.py` 常駐（單例鎖；同平台已有 → 退出碼 3、別平台 → 6），每 0.5 s 只送 `gui pixel / info -NoRestore 1`（**零輸入**、最小化不還原），把畫面狀態寫進 `tools/.cache/state.json`（內容變了才寫 + 每 1 s 心跳）。讀取：`watch.py --get [--max-age 2]`、`--status`；結束：`--stop`；跨平台殘鎖：`--unlock`。Python 讀取 API 在 `tools/gui/watchstate.py`（`fresh()` / `screen(max_age, after=)`）。**state 只能用來顯示 / 決定要不要再看，不能當點擊依據；idle 不代表沒有驗證視窗**（點擊前照舊現場讀圖）。**警示（第 5 階段）**：watch 只標出、不點任何東西：畫面 `unknown`（登入 / 選角除外）連續 10 s → `alerts.unknown_long` + `flags.verify_suspect`（HUD 紅字；寫 errlog 一筆，連續 5 s 回到已知畫面自動清除並補 fix；載入畫面時間 M8 未量，可能誤報，門檻待實機調）；讀 `notes/quest-events.log` 啟動後新增行，轉述 quest 的「Clef 判斷可能是答題 / 驗證視窗」與「連續 3 次遇到不認得的畫面」（`/psa-hud ack` 或 `watch.py --ack` 清除）；`annotate` 只上有正例樣本的 4 種：提示視窗（黃字）、登入畫面、選角畫面、遇敵鈕（`screen.enc_on`），通用彈窗 / 背包面板 / 驗證視窗沒有可靠特徵、不上線。`heal.py --watch`、`petwatch.py` 每輪先看 state：疑似驗證視窗 → 暫停動作並印警告，**暫停超過 10 分鐘就停止（heal 退出碼 11，寫 errlog，不自動恢復）**；state 不可用時行為不變。errlog.add / fix 已改 O_EXCL 鎖 + 原子寫（多程序不互蓋，`test_errlog.py`）。**人物名 / 寵物名（第 7 階段）**：HUD 沒有名字，所以人物名 = 頭頂名牌 OCR（框 660,420,120x30、`-Light 200`）只在白名單 `tools/.cache/watch-config.json` 的 `chars`（`{"chars":["DKBO","DKBO2",…]}`，真名字母 O；舊設定寫 DKB0… 讀入時經 `charstate.display` 轉真名，不進 git）內完全比對；OCR 常把 DKB0 讀成「DKBO」，所以先正規化（全部 O→0、首字 0→D）；連續 2 次一致才採用，讀不到沿用舊值（`state.hud.name.stale`，HUD 顯示 `DKB0?`），完整戰鬥 / 對話 / 面板不讀；沒有白名單也沒有旁路 = `?`。旁路：切換**當前角色**的流程（點切換面板卡片）點完要呼叫 `uv run --no-project python tools/gui/watch.py --set-char DKB02`（寫 `tools/.cache/current-char.json`；watch 以它為主、OCR 核對，兩者不同時較新的勝出並標 conflict，HUD 顯示 `DKB05!`；ass.py 的 select_role 只切 ASS 面板的角色、不算）。寵物名：HUD 只有頭像，用 `watch.py --learn-pet 迪基格斯`（主畫面時、只讀 pixel）把當下頭像存進 `tools/.cache/pet-avatars.json`，之後自動比對，沒學過 / 太像 = `?`。注意：watch 強制用常駐 server（Windows 原生預設關也強制開；`PSA_GUI_SERVER=0` 才關）；除 pixel / info 外只多送 digitmatch.ps1 / stat.ps1（唯讀截圖 / OCR）。

錯誤 / 改進紀錄（psa-hud pane 顯示這個）：遇到錯誤、失誤、卡關（點錯、工具中斷、誤判、漏做、白等）時，**當下**用 `tools/gui/errlog.py` 記一筆；之後改了程式 / 流程 / 文件，再補上改進。沒改進的會在 pane 標「待改進」。
```
uv run --no-project python tools/gui/errlog.py add "錯誤描述" [--fix "改進"] [--source quest]   # 印出 #id
uv run --no-project python tools/gui/errlog.py fix <id|last> "改進內容"
uv run --no-project python tools/gui/errlog.py list
```
存 `tools/.cache/errlog.jsonl`（最新 100 筆，不進 git）；Python 裡 `import errlog; i = errlog.add(...); errlog.fix(i, ...)`。一筆寫一件事、寫具體（發生什麼 + 為什麼），改進寫「改了什麼檔 / 之後怎麼做」。
- 遊戲**不能最小化**（Unity 最小化不繪製）；每個指令遇到最小化會用 SW_SHOWNOACTIVATE 還原（不搶焦點）；**例外**：`gui.ps1 pixel|info ... -NoRestore 1`（watch 唯讀監看用）遇到最小化不還原，印 `minimized`、exit 3。放在其他視窗後面沒關係。
- **座標 = 截圖座標**：截圖固定縮成客戶區的 1/2（`-Scale 2`，不隨視窗大小變），click 內部 ×2。實測客戶區 2880×1659 → 截圖 1440×830。
- `ui/` 的座標只在這個大小有效。**每次開始操作先跑 `info`**，不是 2880×1659 就跑 `max`；`max` 後仍不同（換螢幕 / 解析度）時不要等比例換算（UI 縮放與錨點會變，例：1436×1644 時背包在 558,790），以新截圖重新目測。
- **1920×1080 螢幕**（`max` 後 `client=1920x1017`、截圖 960×508）：用 [ui/layout-1920x1017.md](ui/layout-1920x1017.md) 的座標；`stat.ps1`、`walk.py`、`heal.py` 會自動切換（`tools/gui/layout.py`）。
- 只有 `fg` / `max` 會讓遊戲佔著前景（使用者打字可能打進遊戲），之後要跑 `end`。習慣上任務結束仍跑 `end`，沒狀態時它什麼都不做。
- 背景模式 `dclick`（倉庫存入）、`key` 打字（含中文）都實測可用（2026-10-09）。`key` 語法：一般字元 = 打進輸入框；`{ESC}` `{BS}` 等 = 按鍵；`{a}` = 只按 a 鍵（快捷鍵用）。
- `gui.ps1` 必須保持 **UTF-8 with BOM**（PowerShell 5.1 讀無 BOM 檔會把中文當 Big5，整支解析失敗）。

## 移動：先用 walk.py（不要自己算座標點地面）
- **鏡頭高度一律拉到最左**（設置 → 畫面設置，見 [ui/setting.md](ui/setting.md)）：walk.py 的每格位移只在這個鏡頭下準，與視窗大小無關；滾輪會改鏡頭高度，**不要在遊戲畫面上滾滾輪**。走路 / 補血一直走錯格時先檢查這個。
- 要走到某格 → `walk.py <地圖> <x> <y>`；要走進出口 → 加 `--exit <下一張地圖>`；要點 NPC → 腳本裡用 `walk.npc_steps` / `walk.talk_npc`（直接點 NPC 會自己走過去開對話）。
- walk.py 做的事：先點引子 1215,18（換地圖後第一下左鍵會被吃掉）→ 讀起點（`walk.pos()`：現場 digitmatch 字元樣板比對約 0.1 s 為主，認不出 / 沒樣板 / 逾時才退回 stat.ps1 OCR；不讀 watch 的 state.hud，因為 watch 每 3 s 才更新、拿不到點擊之後的新值）→ 有 `knowledge/data/maps.bin` 通行格就找路
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
| 開始 / 恢復練功（選練功區、傳送、開遇敵、5 人快速 + 自動戰鬥檢查） | **`/psa-grind-start` skill** |
| 解散隊伍 | **`/psa-disband-team` skill**（介面參考 [ui/team.md](ui/team.md)） |
| 確認誰是「當前」角色 | [ui/team.md](ui/team.md) |
| 看角色屬性 / 抗性 / 潛力點 | [ui/role.md](ui/role.md) |
| 看任務進度、任務詳情、自動巡路解任務（`tools/gui/quest.py --task 任務名`；檢測方針：黃色「?」優先，否則 OCR 核對追蹤列表任務名再點；`ocr.ps1` / `findmark.ps1`） | [ui/quest.md](ui/quest.md) |
| **單人逃跑解任務**（DKB0 單人跑 NPC、遇怪逃跑 → 組隊對話 / 打；紅暴 2031；`quest.py --solo / --fight`、`psa.py steps`、`heal.py --no-return`） | **`/psa-quest-solo` skill**（介面參考 [ui/quest.md](ui/quest.md#單人逃跑解任務questpy---solo----fight2026-10-10流程見-psa-quest-solo-skill)） |
| 背包、道具、倉庫、材料圖鑑 | [ui/bag.md](ui/bag.md) |
| **交寵物類任務**（恐龍博士 2016 / 卡坦的願望 2019：外掛自動抓寵、共用倉庫分配、練寵、交任務；轉生 / 封印書後要重做） | **`/psa-pet-quest` skill** |
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
0. （選用）先看即時狀態：`uv run --no-project python tools/gui/watch.py --get --max-age 2`（有 psa-hud 在跑才有；沒有 / 太舊就回退碼 1，照下面 shot 流程）。給你「現在是哪種畫面、等級 / HP、有沒有警報」的**參考**，**不能當點擊依據**：點擊前一律現場 shot / pixel；`idle` 只代表「沒偵測到已知視窗」，**不代表沒有驗證視窗**；`alerts` / `verify_suspect` 出現就立刻停手回報。watch 本身零輸入（只送 pixel / info / stat），由開 psa-hud 的那個 session 管理（單一管理者）；殘鎖（別平台 / 已死）用 `watch.py --unlock`，同平台擁有者還活著要 `--stop` 或 `--unlock --force`；兩個平台同時開 session 時只有一邊有即時狀態。
1. `shot` → Read 圖，先判斷**目前在哪個畫面**（主畫面 / 某面板 / 對話 / 戰鬥 / 驗證）。
2. **速度**：遊戲響應很快（實測傳送面板 / 分頁 / NPC 對話框 / 遇敵圖示都在 0.05～0.15 秒內出現；傳送 Loading 1.0～2.2 秒）；每次呼叫 gui.sh 要多花約 0.4 秒啟動 PowerShell（gui.sh 維持一次性；Python 長程序可用常駐 server 省掉，見上方「常駐 server」）。
   - 腳本裡能用 `waitpix`（等指定點變成某顏色）/ `waitstill`（等走路停）就不要固定 `wait`；`ifok` / `ifnok` 依上一個 waitpix 結果決定做不做，面板沒出現就不會點穿。
   - **換地圖後第一下左鍵會被吃掉**：先點 1215,18（狀態列空白）當引子（ui/home.md「走路」；walk.py `PRIMER`）。
   - **已知流程**（座標都驗證過）：用 `seq` 把多個動作串成一次呼叫，動作之間 `wait 150～500`，只在**分歧點**（要判斷畫面才能決定下一步）和**結尾**截圖。
   - **陌生畫面**：一次一個動作，`seq "click X Y; wait 400; shot"`，看完再決定下一步。
3. 不要盲點：至少在結尾截圖驗證；流程中途需要事後查錯的，在 seq 裡多存一張 `shot <檔名>`（不用 Read，失敗時再看；相對檔名一律存到 `tools/.cache/`，單獨 shot 與 seq 內都一樣，絕對路徑照用）。
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
- 本帳號是多角色同時登入（真名 DKBO、DKBO2～5，字母 O；文件舊寫法 DKB0… 同義，程式比對 O / 0 視為相同）。目前操作的角色：人物資訊 / 背包左欄有黃框的頭像、設置面板的「暱稱」、切換角色面板標「當前」的那個。面板左欄可切換正在看的角色。
