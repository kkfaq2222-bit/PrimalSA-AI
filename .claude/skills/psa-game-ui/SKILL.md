---
name: psa-game-ui
description: Use when operating the PrimalSA (精靈王石器) game client by screen — taking screenshots, clicking buttons, opening panels, reading what is on screen, or deciding which UI element does what before playing.
---

# 精靈王石器 介面操作

## 概觀
AI 只透過「截圖 → 看圖 → 點擊 / 按鍵 → 再截圖確認」操作遊戲（AGENTS.md 第 3 節第 4 條）。
工具是 `tools/gui/gui.sh`（WSL）→ `tools/gui/gui.ps1`（Windows PowerShell）。
**前景切換**：`shot` 用 PrintWindow 背景截圖（不搶焦點、不受遮擋）。任務中第一次 `click`/`drag`/`key` 會記下使用者原本的前景視窗與游標，把遊戲拉到前景並**一直留著**；**任務做完一定要跑 `end`**，才會把前景與游標還給使用者。
Unity 不吃 PostMessage 的滑鼠訊息（實測），所以輸入一定要真的移動游標。
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
bash tools/gui/gui.sh end                  # 任務結束：還原使用者的前景視窗與游標
bash tools/gui/gui.sh seq "click 763 760; wait 400; shot"   # 同一個行程連跑多個動作（快）
```
- 遊戲**不能最小化**（Unity 最小化不繪製）；每個指令遇到最小化會用 SW_SHOWNOACTIVATE 還原（不搶焦點）。放在其他視窗後面沒關係。
- **座標 = 截圖座標**：截圖固定縮成客戶區的 1/2（`-Scale 2`，不隨視窗大小變），click 內部 ×2。實測客戶區 2880×1659 → 截圖 1440×830。
- `ui/` 的座標只在這個大小有效。**每次開始操作先跑 `info`**，不是 2880×1659 就跑 `max`；`max` 後仍不同（換螢幕 / 解析度）時不要等比例換算（UI 縮放與錨點會變，例：1436×1644 時背包在 558,790），以新截圖重新目測。
- 任務期間遊戲佔著前景、游標會被移動：使用者此時打字可能打進遊戲。**任務完成、中途停手、要問使用者問題前，都先跑 `end`**。
- `gui.ps1` 必須保持 **UTF-8 with BOM**（PowerShell 5.1 讀無 BOM 檔會把中文當 Big5，整支解析失敗）。

## 功能索引（要做某件事時先讀對應檔）
| 要做的事 | 讀這個 |
|---|---|
| 認主畫面按鈕、收合、面板關不掉 | [ui/home.md](ui/home.md) |
| 5 個角色組一隊 | **`/psa-quick-team` skill**（介面參考 [ui/team.md](ui/team.md)） |
| 解散隊伍 | **`/psa-disband-team` skill**（介面參考 [ui/team.md](ui/team.md)） |
| 確認誰是「當前」角色 | [ui/team.md](ui/team.md) |
| 看角色屬性 / 抗性 / 潛力點 | [ui/role.md](ui/role.md) |
| 看任務進度、任務詳情 | [ui/quest.md](ui/quest.md) |
| 背包、道具、倉庫、材料圖鑑 | [ui/bag.md](ui/bag.md) |
| 寵物出戰 / 騎乘 / 休息、寵物技能 | [ui/pet.md](ui/pet.md) |
| 傳送到別的地圖 / 練級點 | [ui/transfer.md](ui/transfer.md) |
| 遊戲設定、離線時間 | [ui/setting.md](ui/setting.md) |
| 自動戰鬥、補血、抓寵、遇敵 | [ui/ass.md](ui/ass.md) |
| 聊天、信件、通知、排行榜、家族 | [ui/social.md](ui/social.md) |
| 商城、交易所、抽獎（多為紅區） | [ui/shop.md](ui/shop.md) |
| 沒見過的畫面、答題驗證 | [ui/todo.md](ui/todo.md) |
全部清單與「依情境找」見 [ui/README.md](ui/README.md)。學到新畫面或新流程時，照 README 的「新增 / 更新規則」寫進對應檔並更新兩邊索引。

## 操作迴圈
1. `shot` → Read 圖，先判斷**目前在哪個畫面**（主畫面 / 某面板 / 對話 / 戰鬥 / 驗證）。
2. **速度**：遊戲響應很快（面板約 0.3～0.5 秒就開好）；每次呼叫 gui.sh 要多花約 0.4 秒啟動 PowerShell。
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

## 判讀注意
- 截圖是視窗自己的畫面，不會截到通知；但**點擊是真的點在螢幕上**，所以點擊瞬間遊戲會被拉到最上層再點，不會點到別的視窗。
- 角色頭頂名字很密集、會互相重疊，不要靠名字定位自己；自己腳下有藍色光圈。
- 右上角「地圖名 + 地圖ID:x,y」是目前位置，可直接對 `tools/query/psa.py map/route/grid`。
- 本帳號是多角色同時登入（DKB0…）。目前操作的角色：人物資訊 / 背包左欄有黃框的頭像、設置面板的「暱稱」、切換角色面板標「當前」的那個。面板左欄可切換正在看的角色。
