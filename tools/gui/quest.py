#!/usr/bin/env python3
"""解任務監測：任務靠遊戲內建自動巡路（Auto Walking），這支腳本每 1 秒截圖判斷狀態，只處理「對話要按確認」與「戰鬥按刷新角色加速」。

用法（專案根目錄；WSL / Windows 原生指令相同）：
  uv run --no-project python tools/gui/quest.py --task 黃金羚羊之謎   # 一直監測，最長 15 分鐘（--task = 追蹤列表上的任務名，必填）
  uv run --no-project python tools/gui/quest.py --once          # 只看一次、做一個動作就結束（除錯用）
  uv run --no-project python tools/gui/quest.py --max-seconds 600 --stop-after-rewards 2
  選項：--task 任務名（要點追蹤時，先用 OCR 認出追蹤列表每一格的標題，名稱相符才點；不符就捲動列表再找，找不到退出碼 5，絕不點其他任務。
          沒給 --task 又沒給 --no-track 會直接拒絕執行）、--no-marker（不找 NPC 頭上的黃色問號）、
        --every 1.0（輪詢秒數；2026-10-10 起預設 1 秒，所有「連續 N 次」的規則已改成以秒計，見 IDLE_CONFIRM_SECS 等常數）、--no-track（不主動點任務追蹤，只處理對話 / 戰鬥）、--no-refresh（戰鬥不按刷新角色）、
        --no-clef（不用 Clef 加速層；也可設環境變數 PSA_NO_CLEF=1。預設有 token 就用，失敗 / 額度用完自動退回 OCR 與規則，見 ui/quest.md「Clef 加速層」）、
        --stop-after-rewards N（領到第 N 次「獲得物品」確認窗後停；避免自動接下一個任務。成人儀式 = 2）
  --solo   單人逃跑風格（/psa-quest-solo）：**一律手動逃跑**（2026-10-10 使用者：外掛「自動逃跑」不再使用、不看那個勾選框）。
           遇敵 → 完整戰鬥下指令階段按右上「逃跑」1283,168；自動戰鬥開著（指令框不出現）先按 1380,600 關掉再逃；
           逃跑失敗（還在戰鬥）下一回合再按。要先把 DKB0 外掛的原地遇敵 / 快速戰鬥 / 自動戰鬥關（完整戰鬥畫面才有逃跑鈕；只看到 VS 牌 = 快速戰鬥還開著，只能等，印警告）。
           路上小怪只逃、不刷新角色。到 NPC 跳出對話框 → ESC 關掉（不按任何選項）後停下，退出碼 20；被打飛（回到薩姆吉爾村 1000 儲存點附近）→ 退出碼 21。
  --stop-after-dialog  對話步（組隊後單步）：按完對話框、閒置滿 2.5 秒（連續 2 次以上）就結束退出碼 0（有獲得物品視窗的步驟改用 --stop-after-rewards 1）
  --fight  戰鬥步（假設已站在 NPC 旁，**不點追蹤、不巡路**）：--npc X,Y（NPC 地圖座標）或 --npc auto（--task 目前步驟的 NPC；見 --step）→ 依自己座標算畫面位置點 NPC（--at X,Y 可手動給自己座標）
           → 先處理「選擇對象」面板（見下）→ 對話框按左鈕 → 開打。戰鬥分類：開始時距離最後一次點 NPC / 按對話框 <= QUEST_BATTLE_WINDOW(15) 秒 = 任務 / BOSS 戰
           （確保自動戰鬥開 + 刷新角色；打完閒置滿 IDLE_CONFIRM_SECS 秒（且連續 2 次）印「BOSS 戰結束」退出碼 0，不繼續巡路）；
           否則 = 路上小怪：手動逃跑（自動戰鬥開著先關再按逃跑），不刷新角色。
           點 NPC 後 12 秒沒對話框也沒戰鬥 → 退出碼 22（沒點到 NPC）；對話後 15 秒沒開打 → 23；被打飛 21。
           範例：quest.py --fight --task 英雄島前傳 --npc auto --max-seconds 300
  --disband-after  這步完成（搭配 --stop-after-dialog / --stop-after-rewards）後立刻解散隊伍；分頁沒切到組隊 / 選單沒彈出 / 解散後隊長紅標還在 → 不亂點，退出碼 26；已是單人（組隊分頁沒隊長紅標）→ 不點任何東西，退出碼 0
  --stop-after-dialog 的停止規則：只要這步已對話或領獎過，之後閒置不再點追蹤 / 黃問號，閒置滿 2.5 秒（連續 2 次以上）就停（退出碼 0）；遊戲自己又開始 Auto Walking → 退出碼 24
  --step N  --fight 用：明確指定任務第 N 步的 NPC（= --npc auto 但不 OCR 追蹤條目；需 --task）。--npc auto 不給 --step 時，改讀追蹤條目「標題正下方那行說明」
           （OCR）對照 Task 表 explandTn 找目前步驟的 endNpc；讀不到 / 對不到（或兩步相似且 NPC 不同）→ 退出碼 31，不點任何東西，絕不退回「第一個戰鬥步」
  --team-size N  隊伍人數檢查（預設 5；0 或 1 = 跳過）：--fight 點 NPC 前、預設模式（要點追蹤 / 黃問號時）每次點之前（至少隔 TEAM_CHECK_GAP=20 秒）開切換面板 763,760，
           讀 5 張卡片的隊伍標籤，要「1 隊長 + (N-1) 隊員」（N=5 即 5 人都要在隊）；面板上其他卡片是單人 / 不在隊（例如單人 DKB0）不算錯；隊員不夠 / 隊長不是 1 個 / 讀不到 → 不點、事件 log 寫出誰不在隊、關面板（✕ 1064,208）；--fight 開打前退出碼 30、執行中發現脫隊退出碼 32。
           --solo / --fight --no-click 不檢查。**開始前一定先驗**：非 --solo 模式（含 --no-track / --stop-after-*）第一次點 / 按對話框前先驗一次（不受 GAP 限制），不符退出碼 30；啟動時對話框已開 → 先 ESC 再驗（2026-10-10 18:44 事件：--solo 後單人直接 --stop-after-rewards 只有 DKB0 交任務）。聊天「離開了隊伍」OCR 不可靠（只顯示最新 2 則、會被洗掉），所以脫隊偵測改用這個「點之前先驗隊伍」的做法
  戰鬥鎖檔  所有模式一進戰鬥就寫 tools/.cache/battle.lock（pid + 開始時間），戰鬥結束 / 程式結束（finally）刪除；ass.py 看到有效鎖檔 = 戰鬥中，不改外掛設定（見 ui/ass.md）
  組隊預設模式（非 --solo / --fight）：**每一場戰鬥**（完整戰鬥或快速戰鬥、不分任務 / 路上）都刷新角色；完整戰鬥自動戰鬥鈕是關的 → 先按 1380,600；同一場按 4 次仍關（寵物指令視窗等）→ 退出碼 25
  刷新角色規則：--solo / --fight 只有任務 / BOSS 戰（點 NPC / 對話後 QUEST_BATTLE_WINDOW 內開始）刷新，路上小怪直接逃、不刷新；預設模式每場都刷新（--no-refresh 全關）。同一場最多每 REFRESH_GAP 秒刷新一次。
           刷新前底部若出現「關閉」直式鈕 + 5 個角色頭像列（上方綠字「如果遇到下指令出錯等問題，可使用下方[切換]按鈕切換至其他角色」）→ 先點左側「關閉」510,745 隱藏，再按切換（完整戰鬥 850,765 / 快速戰鬥 763,760）→ 刷新角色 910,578。
  選擇對象面板（點 NPC 後右側跳出的米色面板：頭像卡片 + 名字，NPC 是黃 / 金字、隊友白字）：偵測到就依黃字位置點 NPC 那張卡片（不寫死第一格），再等對話框；--fight 點 NPC 後與對話步（--stop-after-dialog 點 NPC / 黃問號）都處理。
  模擬測試：uv run --no-project python tools/gui/test_quest_fight.py
  事件記錄：notes/quest-events.log（每行一筆，附截圖路徑 tools/.cache/quest-log/）；啟動時自動刪 tools/.cache/quest-log/ 內超過 3 天的圖檔（cleanup_old_shots）。

狀態判斷（都是背景截圖讀像素，座標為 2880×1659 → 截圖 1440×830；細節與實測見 .claude/skills/psa-game-ui/ui/quest.md）：
  對話框   右側棕底 + 兩顆米色鈕 → 點左鈕 948,461（接受 / 完成 / 成人勾玉 等推進鈕；右鈕 1220,461 是「再見」不點）
  獲得物品 藍色「確認」鈕 720,572 + 米色底 → 點它
  戰鬥     角色頭上綠色 VS 牌（快速戰鬥沒有戰鬥畫面）→ 切換 763,760 → 刷新角色 910,578（按完面板自己關）
  巡路中   畫面中央金黃色「Auto Walking」字樣
  主畫面   外掛鈕紅字 ASS（沒對話框 / 巡路 / 戰鬥時）→ 檢測方針（使用者指定）：
           1. 場景裡有黃色「?」「!」任務標記 → 優先點它（findmark.ps1 找黃色色塊，點標記下方的 NPC）
           2. 沒有 → 在追蹤列表先用標題圖片樣板比對（titlematch，0.7 秒）、沒樣板 / 沒找到才用 OCR（ocr.ps1，成功會存樣板）找 --task 那一格，必要時捲動列表，確認標題相符才點 → 開始（繼續）巡路
  不認得   連續 3 次且滿 UNKNOWN_CONFIRM_SECS 秒都不是以上任何狀態（答題 / 驗證視窗、讀取中卡住…）→ 存圖、印警告、退出碼 2（鐵則 5：交給使用者）
  追蹤沒反應 點了任務追蹤約 5 秒（TRACK_RETRY_SECS 重點一次、再等一輪）都沒進入巡路 / 對話 / 戰鬥 → 退出碼 3，改手動（walk.py + 點 NPC）
退出碼：30 隊伍不符（開始前第一次點 / 按對話框前驗隊伍；含 --fight 點 NPC 前）、31 --npc auto 取不到目前步驟、32 執行中脫隊（點追蹤 / 黃問號 / 領獎後追蹤前的隊伍檢查）、20 --solo 到達 NPC（已 ESC 關對話框）、21 被打飛回村（--solo / --fight）、22 --fight 沒點到 NPC、23 --fight 對話後沒開打、24 --stop-after-dialog 停止時遊戲自己已在 Auto Walking、25 組隊完整戰鬥自動戰鬥按 4 次仍關、26 --disband-after 解散沒做成、0 正常結束（任務完成〔領過獎勵後整個追蹤列表掃完沒有 --task，印「任務完成」〕/ 時間到 / 做完對話或領獎後連續 2 次閒置提前結束 / --once / 達到 --stop-after-rewards）、2 不認得的畫面、3 追蹤沒反應、4 版面不支援 / 參數錯、5 追蹤列表掃完（到頂 + 到底）找不到 --task 的任務且沒領過獎勵（沒點任何東西）。
（27 / 28 / 29 = 舊外掛自動逃跑專用，2026-10-10 移除，不再使用。）
只透過 gui.ps1 背景截圖 / 點擊，不碰遊戲記憶體。
"""
import argparse
import os
import difflib
import json
import sys
import time
from pathlib import Path

import battleguard
import clef
import layout
import netwatch
import winenv
import walk
from walk import ROOT, gui, log, PRIMER, stat
import re

EXIT_AT_NPC = 20                     # --solo：到達 NPC（對話框已 ESC 關閉）
EXIT_KNOCKED = 21                    # 被打飛回薩姆吉爾儲存點
EXIT_NO_NPC = 22                     # --fight：點 NPC 後 NPC_WAIT 秒內沒對話框也沒戰鬥（沒點到 NPC / 被小怪打斷）
EXIT_NO_BATTLE = 23                  # --fight：有對話但 QUEST_BATTLE_WINDOW 秒內沒開打（這步其實不戰鬥？）
EXIT_AUTOWALK = 24                   # --stop-after-dialog：這步對話完，遊戲自己又開始 Auto Walking（腳本沒點追蹤；呼叫端要馬上處理，例如解散）
EXIT_BATTLE_STUCK = 25               # 組隊預設模式：完整戰鬥按了自動戰鬥好幾次仍是關的（寵物指令視窗 / 其他卡住畫面）→ 人工處理
EXIT_DISBAND_FAIL = 26               # --disband-after：解散沒做成（分頁沒切過去 / 選單沒彈出 / 解散後畫面沒變），沒亂點
# 27 / 28 / 29（外掛自動逃跑專用）已於 2026-10-10 移除，編號保留不重用
EXIT_TEAM_MISMATCH = 30              # --fight / 預設模式點 NPC 前：切換面板的隊伍標籤不是「1 隊長 + (N-1) 隊員」（有人脫隊 / 單人）→ 沒點 NPC
EXIT_STEP_UNKNOWN = 31               # --npc auto：讀不到追蹤條目的目前步驟文字，或對不到任務表的步驟（不退回第一個戰鬥步）
EXIT_TEAM_LOST = 32                  # 預設模式 / --fight 執行中：點追蹤 / 點 NPC 前的隊伍檢查發現有人脫隊（停下，不繼續點）
AUTO_STUCK_MAX = 4                   # 同一場戰鬥最多按幾次自動戰鬥鈕
NPC_WAIT = 12.0                      # --fight 點 NPC 後最多等幾秒看有沒有反應（走過去 + 開對話框）
LOG_FILE = ROOT / 'notes' / 'quest-events.log'
SHOT_DIR = ROOT / 'tools' / '.cache' / 'quest-log'
SHOT_KEEP_DAYS = 3                   # 啟動時清掉 SHOT_DIR 內超過幾天的圖檔
SHOT_EXTS = ('.png', '.jpg', '.jpeg')

# ---- 「連續 N 次」規則改以秒計（預設輪詢間隔 2.5 → 1.0 秒後，維持原本的實際等待時間；2026-10-10）----
DEFAULT_EVERY = 1.0                  # --every 預設（一般 / --solo / --fight 都是；舊值 2.5 / 1.5）
IDLE_CONFIRM_SECS = 2.5              # 連續閒置至少這麼久（且連續 >= 2 次）才算「這步結束 / 戰鬥打完」（舊：2 次 × 2.5 秒）
UNKNOWN_CONFIRM_SECS = 5.0           # 連續 3 次不認得 + 至少這麼久才停手（舊：3 次 × 2.5 秒 ≈ 5 秒；鐵則 5 的 3 次規則仍在，只是多一道時間條件）
SELECT_MAX_TRIES = 4                # 「選擇對象」面板連續出現幾輪還沒消失就不再點（交給不認得規則）
TRACK_RETRY_SECS = 2.5               # 點了任務追蹤後，等這麼久沒反應才算 1 次失敗（重點一次；連續 2 次失敗退出碼 3，約 5 秒）
CLEF_WAIT_SECS = 50.0                # Clef 判成「載入畫面 / 戰鬥中」時，最多連續這麼久不算「不認得」（舊：20 次 × 2.5 秒）

# ---- 座標與特徵色（2880×1659 版面，截圖座標；2026-10-09 實測）----
TRACKER = (205, 325)                 # 左側任務追蹤第一條：點了自動尋路到任務 NPC
SWITCH_BTN = (763, 760)              # 主畫面「切換」（快速戰鬥 = 主畫面）
SWITCH_FULL = (850, 765)             # 完整戰鬥畫面的「切換」（戰鬥時最右「遇敵」鈕消失，按鈕列右移；2026-10-10 實測）
REFRESH_GAP = 8.0                    # 同一場戰鬥最多每幾秒按一次刷新角色（第 1 次在戰鬥開始後馬上按）
REFRESH_BTN = (910, 578)             # 切換角色面板「刷新角色」（綠色，最右；按完面板自己關）
QUEST_BATTLE_WINDOW = 15.0           # 最後一次「按對話框 / 點 NPC / 點問號」後幾秒內開始的戰鬥 = 任務戰鬥（才按刷新角色）
ESCAPE_BTN = (1283, 168)             # 完整戰鬥下指令畫面右上角指令框的「逃跑」（跑步小人，第 2 排最右；2026-10-10 實測，點了出現 Escape! 泡泡）
AUTO_BTN = (1380, 600)               # 戰鬥畫面右側「自動戰鬥」鈕（點一下切換開 / 關，同外掛 ASS 的自動戰鬥；日誌「你已開啟 / 關閉自動戰鬥」）
# 下指令階段（右上指令框 + 上方「N回合 / 剩餘時間」）：播放中框會消失，用框的底色 / 邊框 + 逃跑鈕判斷（2026-10-10 實測，容差 25）
SIG_CMD = [(1283, 168, 143, 119, 102), (1100, 170, 139, 117, 98), (1100, 60, 187, 161, 131), (1250, 60, 187, 161, 131), (1060, 200, 133, 100, 72)]
# 自動戰鬥鈕「關」= 靜止的紅色圖示（兩點固定）；「開」是會擺動的刀劍動畫，顏色不固定 → 只判斷「是不是關」（容差 20）
SIG_AUTO_OFF = [(1380, 600, 75, 29, 16), (1375, 605, 249, 181, 100)]
SAVE_POINT = (1000, 93, 99)          # 薩姆吉爾的儲存點巫女 1000:94,99、復活 / 傳送落點 92,99 附近（知識庫 Npc 3014）
KO_RADIUS = 8                        # 地圖 1000 且離儲存點這麼近（格）才可能是「被打飛」
# 戰鬥中底部「關閉」直式鈕 + 5 個角色頭像列（上方有綠字「如果遇到下指令出錯等問題，可使用下方[切換]按鈕切換至其他角色」）：它蓋住「切換」鈕，刷新前要先點左側「關閉」收起來。
# 實機樣本 tools/.cache/battle-samples/cmd_a.png（2026-10-10）：關閉鈕半透明灰米色 ≈(188,162,134)（容差 22）、右側深色頭像條（RGB 都 < 95）；21 張戰鬥樣本全中、其餘 455 張截圖（含主畫面 / 對話 / 選擇面板）0 誤判
CLOSE_ROW_BTN = (510, 745)
SIG_CLOSE_ROW = [(480, 745, 188, 162, 134), (500, 710, 188, 162, 134), (490, 800, 182, 158, 130), (520, 745, 188, 162, 135)]
CLOSE_ROW_DARK = [(555, 745), (1085, 745)]
# 「選擇對象」面板（點 NPC 後右側跳出的米色面板：頭像卡片，名字在卡片下方，NPC 是黃 / 金字 (255,2xx,0)、隊友白字）。
# 實機樣本 tools/.cache/quest-log/172356-no-npc.png（2026-10-10，碧青 8 樓水的守護獸）：面板外框 1106～1420 × 230～560，左右棕色邊框 + 內部米色漸層；
# 8 點（容差 40）全中，其餘 475 張截圖 0 誤判。名字黃字用 findmark.ps1 的黃色色塊找（NPC 名字拆成十來塊 w<=16 h<=16）。
SIG_SELECT = [(1112, 300, 104, 79, 48), (1112, 400, 104, 79, 48), (1112, 470, 104, 79, 48), (1416, 300, 93, 68, 36), (1416, 470, 93, 68, 36),
              (1120, 470, 247, 216, 177), (1250, 490, 245, 229, 191), (1410, 470, 246, 219, 182)]
SELECT_BOX = (1115, 235, 1415, 555)  # 面板內部（找黃字名字的範圍）
SELECT_NAME_DY = 48                  # 名字中心往上 48 = 那張卡片的頭像中心（實測：名字 y=337、頭像中心 y≈285~290）
SELECT_MIN_N = 30                    # 一排黃字色塊的像素總數至少這麼多才算名字（單字名也 > 40；頭像高光 < 20）
DIALOG_NEXT = (948, 461)             # NPC 對話框左鈕
REWARD_OK = (720, 572)               # 「獲得物品」視窗的藍色確認鈕
# 對話框：棕底 2 點 + 兩顆米色鈕（heal.py 同款）。主畫面沙地很像米色，所以一定要配棕底
SIG_DIALOG = [(1360, 300, 107, 70, 44), (1100, 350, 107, 70, 44), (948, 445, 229, 197, 155), (1220, 445, 229, 197, 155)]
SIG_REWARD = [(720, 572, 62, 106, 158), (680, 560, 82, 125, 178), (560, 620, 233, 203, 161), (720, 640, 104, 72, 46)]
SIG_PANEL = [(1064, 208, 197, 69, 41), (880, 590, 55, 67, 13)]    # 切換角色面板：右上紅 ✕ + 刷新鈕深綠
SIG_HUD = [(1300, 745, 254, 0, 0)]                                  # 外掛鈕 ASS 紅字（對話框開著時整個 UI 隱藏）
VS_PROBE = battleguard.VS_PROBE                                     # 頭上 VS 牌綠框（heal.py SIG_NO_BATTLE 反過來；與 ass.py 共用，定義在 battleguard.py）
VS_COLOR = battleguard.VS_COLOR
# 完整戰鬥畫面（2026-10-10 實測，下指令 / 播放中兩種都量過）：上方中央棕框標籤（播放中 → 米色字；下指令 → 「N回合」+ 下方「剩餘時間 90」倒數），
# 標籤文字會變，所以只取「外框」9 點（兩種畫面像素相同）；主畫面 / 對話 / 獲得物品 / 地圖載入在這些點都不同。9 點同時符合（容差 25）才算。
# 完整戰鬥時 HUD 的 ASS 紅字還在，所以要排在 idle 之前
SIG_BATTLE = battleguard.SIG_BATTLE
# 「Auto Walking」金黃字：畫面中央 550～1000 × 500～540 取樣，金黃點（r>225, 150<g<205, b<50）≥ 10 個
AW_POINTS = [(x, y) for y in range(500, 541, 8) for x in range(552, 1000, 12)]
AW_MIN = 10
TOL = 40

# ---- 任務追蹤列表（左側，「任務 / 組隊」分頁下方；一格一個任務，標題 + 步驟說明，可上下捲動）----
LIST_BOX = (75, 270, 260, 180)       # OCR 區域 x,y,w,h（截圖座標）：標題深棕字
LIST_Y_MAX = 425                     # 標題中心 y 超過這個的格子被面板裁掉一半，不點
CARD_DY = 16                         # 點擊位置 = 標題中心往下一點（格子中心）
SCROLL_UP = (200, 420, 200, 300)     # 往上拖 120px ≈ 捲一格（列表往下走）
SCROLL_DOWN = (200, 300, 200, 420)   # 反向


def close(c, ref, tol=TOL):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def read_screen() -> dict:
    """一次 gui pixel 讀完所有特徵點 → 判斷狀態"""
    pts = [(x, y) for x, y, *_ in SIG_DIALOG + SIG_REWARD + SIG_PANEL + SIG_SELECT + SIG_HUD + SIG_BATTLE + SIG_CMD + SIG_AUTO_OFF] + [VS_PROBE] + AW_POINTS
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
    cols = [tuple(int(v) for v in c.split(',')) for c in out]
    if len(cols) != len(pts):
        return {'state': 'error', 'raw': out[:3]}
    px = dict(zip(pts, cols))
    match = lambda sig: all(close(px[(x, y)], (r, g, b)) for x, y, r, g, b in sig)
    full = False
    gold = sum(1 for x, y in AW_POINTS if px[(x, y)][0] > 225 and 150 < px[(x, y)][1] < 205 and px[(x, y)][2] < 50)
    if match(SIG_DIALOG):
        st = 'dialog'
    elif match(SIG_REWARD):
        st = 'reward'
    elif all(close(px[(x, y)], (r, g, b), 25) for x, y, r, g, b in SIG_BATTLE):
        st, full = 'battle', True
    elif match(SIG_PANEL):
        st = 'panel'
    elif match(SIG_SELECT):
        st = 'select'                                  # 點 NPC 後的「選擇對象」面板（HUD 紅字還在，所以要排在 idle 之前）
    elif close(px[VS_PROBE], VS_COLOR):
        st = 'battle'
    elif gold >= AW_MIN:
        st = 'walking'
    elif match(SIG_HUD):
        st = 'idle'
    else:
        st = 'unknown'
    cmd = full and all(close(px[(x, y)], (r, g, b), 25) for x, y, r, g, b in SIG_CMD)            # 完整戰鬥且在下指令階段
    auto_off = full and all(close(px[(x, y)], (r, g, b), 20) for x, y, r, g, b in SIG_AUTO_OFF)  # 自動戰鬥鈕是關的
    return {'state': st, 'gold': gold, 'full': full, 'cmd': cmd, 'auto_off': auto_off}


def ps_json(script: str, *args) -> dict:
    """跑 tools/gui 的 PowerShell 腳本（ocr.ps1 / findmark.ps1）→ 解析輸出的 JSON；失敗回 {'ok': False}"""
    r = winenv.run_ps(script, *[str(a) for a in args])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'error': (r.stderr or r.stdout)[:200]}


def norm(t: str) -> str:
    """任務名比對前的正規化：去空白、括號 / 版本字尾（例「黃金羚羊之謎(1.82)」→「黃金羚羊之謎」）"""
    import re
    return re.sub(r'[\s\(（\[【].*$', '', t)


def match_title(want: str, got: str) -> bool:
    """OCR 讀到的標題 got 是不是任務 want：完整包含，或相似度 >= 0.75（OCR 偶爾錯 1 個字）"""
    w, g = norm(want), norm(got)
    if not w or not g:
        return False
    return w in g or (len(g) >= 3 and g in w) or difflib.SequenceMatcher(None, w, g).ratio() >= 0.75


def read_list_titles() -> list[dict]:
    """OCR 追蹤列表的標題行 → [{y, texts: [各倍數讀到的字]}]（依 y 排序）。
    Windows OCR 對同一張圖換放大倍數，結果差很多（有時整行讀不到、有時只讀到右半），
    所以一次 ocr.ps1 跑放大 2～7 倍、把 y 相近（<14px）的行併成一格，比對時只要任一種讀法符合即可。"""
    x, y, w, h = LIST_BOX
    r = ps_json('ocr.ps1', x, y, w, h, '-Zooms', '2,3,4,5,6,7', '-Dark', 150)
    rows: list[dict] = []
    for ln in sorted(r.get('lines', []), key=lambda o: o['y']):
        if len(ln['text']) < 2:
            continue
        for row in rows:
            if abs(row['y'] - ln['y']) < 14:
                row['texts'].append(ln['text'])
                break
        else:
            rows.append({'y': ln['y'], 'texts': [ln['text']]})
    return rows


def list_signature() -> list[tuple]:
    """追蹤列表區域的像素取樣（判斷捲動有沒有動、是否到盡頭用；比 OCR 穩）"""
    pts = ' '.join(f'{x},{y}' for y in range(285, 445, 14) for x in range(90, 330, 20))
    return gui('pixel', pts).split()


class _Interrupted(Exception):
    """掃描途中畫面不再是主畫面（跳出對話 / 戰鬥 / 領獎）"""


def scroll_list(drag: tuple[int, int, int, int], note: str, before: list) -> tuple[bool, list]:
    """捲動追蹤列表一格；回傳（畫面有沒有變, 捲完的像素取樣）。before = 捲動前的取樣（呼叫端沿用上一次的，省一次截圖）；沒變 = 已到盡頭"""
    gui('seq', 'drag %d %d %d %d; wait 1400' % drag, note=note)
    after = list_signature()
    return after != before, after


def _find_on_page(want: str, mode: str) -> int | None:
    """目前這一頁追蹤列表上 want 的標題中心 y（沒有回 None）；畫面不是主畫面 → _Interrupted。
    tpl = 標題圖片樣板（約 0.7 秒）；ocr = Windows OCR（3～7 秒），認出目標就存樣板。名稱不符絕不回傳。"""
    if read_screen()['state'] != 'idle':
        raise _Interrupted()
    if mode == 'tpl':
        ty = _tm_find(want)
        return ty if ty is not None and ty <= LIST_Y_MAX else None
    rows = read_list_titles()
    if not rows:                                           # 整個列表讀不到（剛換圖 / 捲動慣性中）→ 等一下再讀一次
        time.sleep(1.0)
        rows = read_list_titles()
    log(f'追蹤列表標題：{[r["texts"][0] for r in rows]}')
    for row in rows:
        if row['y'] <= LIST_Y_MAX and any(match_title(want, t) for t in row['texts']):
            _tm_learn(want, row['y'])                      # OCR 認出了 → 存標題樣板，下次不必 OCR
            return row['y']
    return None


def track_task(want: str, max_scrolls: int = 12, click: bool = True) -> bool | None:
    """掃一遍追蹤列表找標題 = want 的那一格並點它（開始巡路）。名稱不符絕不點。
    回傳：True 找到（click=True 時已點）、False 整個列表掃完沒有、None 途中畫面不再是主畫面（交回主迴圈，不算找不到）。
    一輪有明確終點：先看目前這頁 → 往上捲到頂（每頁都看）→ 再往下捲到底（已看過的頁不重看）；到頂 / 到底用像素取樣沒變判斷，不來回。
    辨識：該任務有標題樣板 → 只用樣板比對（0.7 秒 / 頁，錯配率 0，樣板沒命中 = 不在）；沒樣板 → OCR（3～7 秒 / 頁，並學樣板）。"""
    gui('seq', PRIMER)
    ensure_task_tab()
    mode = 'tpl' if _tm_has(want) else 'ocr'
    t0 = time.time()
    if mode == 'ocr' and click and clef.available():
        # Clef-flash 取代 OCR 的「第一格」快速通道：只在主畫面（呼叫端已確認 idle，非登入畫面）才上傳追蹤區裁圖；
        # 最上面一格標題 = want 且 choice / noul 機率都 >= 0.9 才直接點第一格；否則 / 失敗 → 照舊 OCR 掃描
        img = clef_shot_bytes()
        hit = clef.check_track_top(img, want, known_task_titles()) if img else None
        if hit:
            gui('seq', f'click {TRACKER[0]} {TRACKER[1]}', note=f'點追蹤「{want}」（Clef，--task {want}）')
            event(f'追蹤列表第一格由 Clef 認出「{want}」→ 點 {TRACKER[0]},{TRACKER[1]}（耗時 {time.time() - t0:.1f}s，略過 OCR）')
            return True
        log('Clef 沒認出第一格是目標（或不可用）→ 退回 OCR 掃描' if hit is not None else 'Clef 不可用 → 退回 OCR 掃描')
    try:
        sig = list_signature()
        y = _find_on_page(want, mode)
        ups = pages = 0
        if y is None:
            while ups < max_scrolls:                       # 往上到頂
                moved, sig = scroll_list(SCROLL_DOWN, f'任務追蹤列表往上捲一格找「{want}」', sig)
                if not moved:
                    break
                ups += 1
                if (y := _find_on_page(want, mode)) is not None:
                    break
        if y is None:
            for i in range(max_scrolls * 2):               # 往下到底；前 ups 格是剛看過的頁，不重看
                moved, sig = scroll_list(SCROLL_UP, f'任務追蹤列表往下捲一格找「{want}」', sig)
                if not moved:
                    break
                pages += 1
                if i + 1 > ups and (y := _find_on_page(want, mode)) is not None:
                    break
    except _Interrupted:
        return None
    log(f'追蹤列表掃描（{mode}）{"找到 y=%d" % y if y is not None else "沒找到"}，上 {ups} 格 / 下 {pages} 格，耗時 {time.time() - t0:.1f}s')
    if y is None:
        return False
    if click:
        cx, cy = 205, y + CARD_DY
        gui('seq', f'click {cx} {cy}', note=f'點追蹤「{want}」（{mode}，--task {want}）')
        event(f'追蹤列表找到「{want}」（{mode}）→ 點 {cx},{cy}')
    return True


TAB_TASK = (148, 236)                # 左側面板「任務」分頁鈕
TAB_TEAM = (260, 236)                # 左側面板「組隊」分頁鈕
# 分頁選中判斷（2026-10-10 組隊狀態實機量測）：選中的分頁底是亮米色（R≈205~221），沒選中是深棕（R≈80~90）；
# 只取分頁鈕「文字上方 y=222、文字下方 y=250」兩排（y=226~246 會踩到「任務 / 組隊」字，讀數亂跳）。
# 任務分頁 x=130、組隊分頁 x=270；四點全部一致才算（組隊選中：(130,*)≈(87,68,41) 且 (270,*)≈(215,183,135)；任務選中相反）
TAB_PROBE = ((130, 222), (130, 250), (270, 222), (270, 250))
# 隊長列左上角的紅色「隊」字標（組隊分頁、自己是隊長才有；四點量到 ≈(217,33,33)；任務分頁同位置是米色 ≈(245,223,187)）
LEADER_BADGE = ((100, 306), (128, 306), (100, 312), (130, 312))


def tab_state() -> str | None:
    """左側面板目前分頁：'team'（組隊亮、任務暗）/ 'task'（任務亮、組隊暗）/ None（讀不準）。四點都要一致"""
    try:
        out = gui('pixel', ' '.join(f'{x},{y}' for x, y in TAB_PROBE)).split()
        (t1, _, _), (t2, _, _), (g1, _, _), (g2, _, _) = [tuple(int(v) for v in c.split(',')) for c in out]
    except Exception:
        return None
    if min(g1, g2) > 190 and max(t1, t2) < 120:
        return 'team'
    if min(t1, t2) > 190 and max(g1, g2) < 120:
        return 'task'
    return None


def has_leader_badge() -> bool | None:
    """組隊分頁隊長列有沒有紅色「隊」字標（四點都是紅：R>190、G<70、B<70）；讀不到回 None"""
    try:
        out = gui('pixel', ' '.join(f'{x},{y}' for x, y in LEADER_BADGE)).split()
        cols = [tuple(int(v) for v in c.split(',')) for c in out]
        if len(cols) != len(LEADER_BADGE):
            return None
        return all(r > 190 and g < 70 and b < 70 for r, g, b in cols)
    except Exception:
        return None


def ensure_task_tab() -> None:
    """左側面板停在「組隊」分頁時追蹤列表看不到任務（OCR 只讀到「創建隊伍」→ 誤判找不到）。
    只在「組隊亮、任務暗」很明確時點「任務」分頁；讀不準就不動。"""
    try:
        if tab_state() == 'team':
            gui('seq', f'click {TAB_TASK[0]} {TAB_TASK[1]}; wait 600', note='左側面板在「組隊」分頁 → 切回「任務」')
            event('左側面板在組隊分頁，已切回任務分頁')
    except Exception as e:
        log(f'ensure_task_tab 失敗：{e}')


DISBAND_LEADER = (210, 320)          # 組隊分頁隊長那一列
DISBAND_BTN = (200, 372)             # 點隊長列後彈出選單的「解散隊伍」


def disband_team() -> int:
    """對話步完成後立刻解散（/psa-disband-team 的自動版）。每一步都驗證，驗不過就停、不再點（寧可退出碼 26 也不亂點，
    避免點到 y≈325 的任務追蹤條目觸發自動巡路）：
    1. 切組隊分頁 260,236 → tab_state()=='team'（四點像素；沒切過去再點一次；換圖後第一下點擊常被吃掉）
    2. 隊長列有紅色「隊」字標（has_leader_badge）才繼續；沒有 = 已是單人（只剩「創建隊伍」）或不是隊長 → 不點任何東西，退出碼 0
    3. 點隊長列 210,320 → 左側面板像素必須變了（選單彈出）才點解散；分頁又變回任務 = 點到別的東西 → 停
    4. 點解散 200,372 → 分頁仍是組隊、面板像素變了、隊長紅標消失才算成功"""
    for attempt in range(2):
        gui('seq', f'{PRIMER}; click {TAB_TEAM[0]} {TAB_TEAM[1]}; wait 700', note='--disband-after：切左側組隊分頁')
        if tab_state() == 'team':
            break
    else:
        event(f'--disband-after：左側分頁沒切到「組隊」（連點 2 次）→ 不點解散，退出碼 {EXIT_DISBAND_FAIL}', snap('disband-no-tab'))
        return EXIT_DISBAND_FAIL
    badge = has_leader_badge()
    if badge is None:
        event(f'--disband-after：讀不到隊長紅標像素 → 不點解散，退出碼 {EXIT_DISBAND_FAIL}', snap('disband-no-badge-read'))
        return EXIT_DISBAND_FAIL
    if not badge:
        event('--disband-after：組隊分頁沒有隊長紅「隊」標（已是單人，或不是隊長）→ 沒點任何東西、未解散，視為無需解散（退出碼 0）', snap('disband-already-solo'))
        return 0
    sig0 = list_signature()
    gui('seq', f'click {DISBAND_LEADER[0]} {DISBAND_LEADER[1]}; wait 500', note='--disband-after：點隊長列')
    sig1 = list_signature()
    if tab_state() != 'team' or sig1 == sig0:
        event(f'--disband-after：點隊長列後選單沒彈出（或分頁變了）→ 不點解散，退出碼 {EXIT_DISBAND_FAIL}', snap('disband-no-menu'))
        return EXIT_DISBAND_FAIL
    gui('seq', f'click {DISBAND_BTN[0]} {DISBAND_BTN[1]}; wait 800', note='--disband-after：解散隊伍')
    if tab_state() != 'team' or list_signature() == sig1 or has_leader_badge() is not False:
        event(f'--disband-after：點解散後未確認成功（畫面沒變 / 隊長紅標還在）→ 退出碼 {EXIT_DISBAND_FAIL}（請 shot 看左側是否只剩「創建隊伍」）', snap('disband-unverified'))
        return EXIT_DISBAND_FAIL
    event('--disband-after：已解散隊伍（左側組隊分頁隊長紅標消失、面板像素已變）', snap('disbanded'))
    return 0


def finish(a, rc: int = 0) -> int:
    """一步完成的收尾：--disband-after 時先解散（失敗回 26），否則回 rc"""
    if a.disband_after:
        d = disband_team()
        return d or rc
    return rc


def _tm_has(want: str) -> bool:
    try:
        import titlematch
        return titlematch.has_templates(want)
    except Exception as e:                                 # 樣板模組壞了 → 退回 OCR
        log(f'titlematch 不可用：{e}')
        return False


def _tm_find(want: str) -> int | None:
    try:
        import titlematch
        return titlematch.find(want)
    except Exception as e:
        log(f'titlematch.find 失敗：{e}')
        return None


def _tm_learn(want: str, y: int) -> None:
    try:
        import titlematch
        d = titlematch.learn(want, y)
        if d:
            log(f'新增標題樣板 {d.name}')
    except Exception as e:
        log(f'titlematch.learn 失敗：{e}')


# ---- 黃色「?」任務標記（NPC 頭上；findmark.ps1 找黃色連通色塊，形狀 / 位置過濾在這裡）----
# 實測（2026-10-10，庫伊老爺爺頭上）：「?」金黃色，因高光被切成 3 塊（單位 = 截圖座標）：
#   上半彎鉤 18x15 n≈117、中間竪 5x10 n≈24、下面圓點 6x7 n≈27；整體 w≈18 h≈33。
#   「!」（可接任務）是 8x15 + 7x9 兩塊、寬度 ≤ 8，與「?」的彎鉤（寬 ≥ 14）明確不同；使用者只要「?」。
#   NPC 名字黃字拆成 n≤13 的小碎塊、Auto Walking 金黃字大又寬（w > 24），都不符。
MARK_HEAD = dict(w=(14, 24), h=(11, 20), n=(70, 200))      # 「?」上半彎鉤
MARK_DOT = dict(w=(4, 9), h=(5, 10), n=(15, 45))           # 「?」下面的圓點
MARK_NPC_DYS = (96, 135)              # 連續第 1、2 次嘗試的偏移；2 次都沒反應就改走追蹤列表（精靈之木這種大樹，身體在標記下 ~270，點標記下方會點到樹冠 / 隊友）
MARK_NPC_DY = 96                      # 彎鉤中心往下 96 = NPC 身體（實測：看門者彎鉤 y=296 → 點 y=392 開對話；+90 與 +45 名字牌上都沒反應）
# 場景區外的 UI（左側任務面板 / 左上 HUD / 右上地圖鈕 / 左下聊天 / 底部按鈕列 / 右側遇敵鈕）不算
MARK_EXCLUDE = [(0, 0, 560, 140), (60, 190, 400, 470), (1060, 0, 1440, 230), (0, 550, 540, 830), (700, 700, 1440, 830), (1300, 600, 1440, 830)]


def _in(b: dict, spec: dict) -> bool:
    return all(spec[k][0] <= b[k] <= spec[k][1] for k in ('w', 'h', 'n'))


def find_marker() -> dict | None:
    """場景區有沒有黃色「?」：找得到「彎鉤 + 正下方圓點」的組合才算；回傳彎鉤色塊（含 x,y,n）或 None"""
    r = ps_json('findmark.ps1')
    bl = r.get('blobs', [])
    for b in sorted((b for b in bl if _in(b, MARK_HEAD)), key=lambda b: -b['n']):
        if any(x0 <= b['x'] <= x1 and y0 <= b['y'] <= y1 for x0, y0, x1, y1 in MARK_EXCLUDE):
            continue
        if any(_in(d, MARK_DOT) and abs(d['x'] - b['x']) <= 6 and 15 <= d['y'] - b['y'] <= 30 for d in bl):
            return b
    return None


def event(msg: str, shot: str | None = None) -> None:
    """印出並寫進 notes/quest-events.log"""
    log(msg)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}' + (f' [{shot}]' if shot else '') + '\n')
    except OSError:
        pass


def cleanup_old_shots(days: int = SHOT_KEEP_DAYS, folder: Path = None, now: float | None = None) -> int:
    """刪掉 folder（預設 SHOT_DIR）內修改時間超過 days 天的圖檔（.png / .jpg / .jpeg）；只看該資料夾第一層，不進子資料夾、
    不碰其他副檔名。任何錯誤都吞掉（不影響主流程）；回傳刪掉幾張"""
    folder = SHOT_DIR if folder is None else folder
    now = time.time() if now is None else now
    n = 0
    try:
        for f in folder.iterdir():
            try:
                if f.is_file() and f.suffix.lower() in SHOT_EXTS and now - f.stat().st_mtime > days * 86400:
                    f.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def idle_confirmed(streak: int, since: float, now: float) -> bool:
    """連續閒置是否已夠久：>= 2 次且從第一次閒置起 >= IDLE_CONFIRM_SECS 秒（輪詢間隔變短也維持同樣等待時間）"""
    return streak >= 2 and now - since >= IDLE_CONFIRM_SECS


def snap(tag: str) -> str:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SHOT_DIR / f'{time.strftime("%H%M%S")}-{tag}.png'
    gui('shot', winenv.to_windows(p))
    return str(p.relative_to(ROOT))


CLEF_WAIT_SCENES = ('載入畫面', '戰鬥中')


def clef_shot_bytes() -> bytes | None:
    """背景截一張遊戲視窗（PrintWindow，只含遊戲客戶區，不含桌面）→ bytes；截完立刻刪檔。
    上傳前先用本地規則排除登入畫面 / 網路異常提示（netwatch.detect），這兩種不上傳。"""
    try:
        if netwatch.detect() is not None:
            return None
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        p = SHOT_DIR / 'clef-tmp.png'
        gui('shot', winenv.to_windows(p))
        data = p.read_bytes()
        p.unlink(missing_ok=True)
        return data
    except Exception as e:
        log(f'Clef 截圖失敗（{type(e).__name__}），退回原流程')
        return None


def known_task_titles() -> list[str]:
    """已有標題樣板的任務名（titlematch 的樣板檔名「任務@N.png」），給 Clef 當 choice 候選"""
    d = ROOT / 'tools' / '.cache' / 'task-titles'
    try:
        return sorted({f.name.split('@')[0] for f in d.glob('*.png')})
    except OSError:
        return []


def is_quest_battle(last_action: float, now: float, window: float = QUEST_BATTLE_WINDOW) -> bool:
    """戰鬥開始時離最後一次任務互動（按對話框 / 點 NPC / 點問號）夠近 → 任務戰鬥。巡路途中的隨機遇敵不算"""
    return last_action > 0 and now - last_action <= window


def plan_battle_action(s: dict, boss: bool, since_click: float, party: bool = False) -> str | None:
    """完整戰鬥畫面該做什麼（純函式，方便模擬測試）：
    BOSS 戰 → 自動戰鬥鈕是「關」才點（'auto_on'）；小怪 → 下指令階段按逃跑（'escape'），
    自動戰鬥是開著（鈕不是靜止紅圖示、也沒有指令框）就先關（'auto_off'，指令框下一回合才會出現）。
    party=True（組隊預設模式，不逃跑）：完整戰鬥、自動戰鬥鈕是「關」→ 'auto_on'（小怪也讓全隊自動打完）。
    沒有完整戰鬥畫面（快速戰鬥）或點擊間隔不夠 → None。"""
    if not s.get('full'):
        return None
    if party:
        return 'auto_on' if s.get('auto_off') and since_click >= 3.0 else None
    if boss:
        return 'auto_on' if s.get('auto_off') and since_click >= 3.0 else None
    if s.get('cmd'):
        return 'escape' if since_click >= 1.2 else None
    if not s.get('auto_off') and since_click >= 3.0:
        return 'auto_off'
    return None


def should_refresh(a, boss_now: bool, full: bool, auto_off: bool, since_refresh: float) -> bool:
    """這一輪戰鬥要不要按刷新角色（純函式）：--no-refresh 不按；--solo / --fight（手動逃跑）只有任務 / BOSS 戰（boss_now）才按，路上小怪不按；
    組隊預設模式每一場都按。完整戰鬥自動戰鬥還是關的（正要先按自動戰鬥）時先不刷新；同一場最多每 REFRESH_GAP 秒一次"""
    if a.no_refresh or ((a.solo or a.fight) and not boss_now):
        return False
    if full and auto_off:
        return False
    return since_refresh >= REFRESH_GAP


def close_row_visible() -> bool | None:
    """底部「關閉 + 5 頭像」列是否出現（關閉鈕 4 點灰米色 + 右側頭像條 2 點深色）；讀不到回 None"""
    pts = [(x, y) for x, y, *_ in SIG_CLOSE_ROW] + CLOSE_ROW_DARK
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()]
    except Exception:
        return None
    if len(cols) != len(pts):
        return None
    btn_ok = all(close(c, (r, g, b), 22) for c, (_, _, r, g, b) in zip(cols, SIG_CLOSE_ROW))
    return btn_ok and all(max(c) < 95 for c in cols[len(SIG_CLOSE_ROW):])


def hide_close_row(max_clicks: int = 2) -> bool:
    """底部關閉列在 → 點左側「關閉」510,745 收起來（第一下常被吃掉，最多點 max_clicks 次、每次驗證）。回 True = 現在沒有關閉列（可以安全點切換）"""
    for _ in range(max_clicks):
        if not close_row_visible():
            return True
        gui('seq', f'click {CLOSE_ROW_BTN[0]} {CLOSE_ROW_BTN[1]}; wait 600', note='戰鬥底部列：點「關閉」收起頭像列')
        event('刷新前底部有「關閉 + 頭像」列 → 點關閉收起')
    return not close_row_visible()


def panel_visible() -> bool:
    """切換角色面板是否開著（✕ + 刷新鈕深綠；直接讀像素，戰鬥中 read_screen 會判成 battle 看不出面板）"""
    pts = [(x, y) for x, y, *_ in SIG_PANEL]
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()]
    except Exception:
        return False
    return len(cols) == len(pts) and all(close(c, (r, g, b)) for c, (_, _, r, g, b) in zip(cols, SIG_PANEL))


def refresh_characters(full: bool = False) -> bool:
    """戰鬥中按「刷新角色」加速：（底部有關閉列先收起）→ 切換（完整戰鬥 850,765 / 快速戰鬥 763,760）→ 等面板 → 刷新角色 910,578；面板還開著就點 ✕。
    關閉列收不掉 → 不點切換（會點到角色頭像換人下指令），回 False"""
    if not hide_close_row():
        event('底部「關閉」列收不掉 → 這次不按刷新角色（避免點到頭像）')
        return False
    sw = SWITCH_FULL if full else SWITCH_BTN
    sig = '/'.join(f'{x},{y},{r},{g},{b}' for x, y, r, g, b in SIG_PANEL)
    gui('seq', f'click {sw[0]} {sw[1]}; waitpix 1500 {sig} 40; ifok click {REFRESH_BTN[0]} {REFRESH_BTN[1]}; wait 500')
    if panel_visible():
        gui('seq', f'click {PANEL_CLOSE[0]} {PANEL_CLOSE[1]}; wait 500', note='刷新後面板還開著 → 點 ✕ 關')
    return True


def pick_select_card(blobs: list) -> tuple[int, int] | None:
    """純函式：「選擇對象」面板上，從 findmark 的黃色色塊找 NPC 名字（黃 / 金字；隊友白字不會被抓），回該卡片頭像中心 (x, y)，找不到回 None。
    只取面板內部（SELECT_BOX）、色塊不大（w,h <= 16，排除頭像大片高光）；把 y 相近（相鄰差 <= 12）的色塊併成一排、再把 x 相近（相鄰間隔 <= 30）的併成一個名字，
    像素總數 >= SELECT_MIN_N 才算名字；多個名字取最上排最左一個。點的位置 = 名字外框水平中心、名字中心往上 SELECT_NAME_DY（卡片頭像，不寫死第一格）"""
    x0, y0, x1, y1 = SELECT_BOX
    bs = sorted((b for b in blobs if x0 <= b['x'] <= x1 and y0 <= b['y'] <= y1 and b['w'] <= 16 and b['h'] <= 16), key=lambda b: b['y'])
    rows: list[list[dict]] = []
    for b in bs:
        if rows and b['y'] - rows[-1][-1]['y'] <= 12:
            rows[-1].append(b)
        else:
            rows.append([b])
    for row in rows:
        names: list[list[dict]] = []
        for b in sorted(row, key=lambda b: b['x']):
            if names and b['x'] - b['w'] / 2 - max(c['x'] + c['w'] / 2 for c in names[-1]) <= 30:
                names[-1].append(b)
            else:
                names.append([b])
        for nm in names:
            if sum(b['n'] for b in nm) >= SELECT_MIN_N:
                left, right = min(b['x'] - b['w'] / 2 for b in nm), max(b['x'] + b['w'] / 2 for b in nm)
                cy = sum(b['y'] for b in nm) / len(nm)
                return int(round((left + right) / 2)), int(round(cy)) - SELECT_NAME_DY
    return None


def handle_select_panel() -> bool:
    """「選擇對象」面板開著：用顏色找黃字名字的卡片並點它（之後等對話框）。找不到黃字 → 不點，回 False（呼叫端當不認得，不亂點）"""
    r = ps_json('findmark.ps1')
    pt = pick_select_card(r.get('blobs', []))
    if pt is None:
        log('選擇對象面板：找不到黃 / 金字名字（NPC 不在面板？）→ 不點')
        return False
    gui('seq', f'click {pt[0]} {pt[1]}', note='選擇對象面板：點黃字名字（NPC）那張卡片')
    event(f'選擇對象面板 → 點黃字名字的卡片 {pt[0]},{pt[1]}')
    return True


PANEL_CLOSE = (1064, 208)            # 切換角色面板右上 ✕


# ---- 切換角色面板的隊伍標籤（2026-10-10 實測；面板只列線上角色）----
# 每張卡片左側有「當前 / 線上」標籤 + 深棕小框，框內是隊伍字樣：「隊長」紅字 ≈(217,33,33)、「隊員」黃字、「單人」（沒量過，顏色不明）。
# 框內取樣 15×8 點（x 間隔 2、y 間隔 2），紅點 >= TEAM_MIN_PX → 隊長；黃點 >= TEAM_MIN_PX → 隊員；都不是 → 'other'（單人 / 離線 / 卡片不存在）。
# 左欄卡片（DKB0 / DKB03 / DKB05）框左上 ≈ (452, 卡片 y)；右欄（DKB02 / DKB04）= 左欄 +310。2026-10-10 實機：隊長 DKB0 紅點 30、隊員黃點 42~44。
TEAM_CARDS = {'DKB0': (452, 275), 'DKB02': (762, 275), 'DKB03': (452, 360), 'DKB04': (762, 360), 'DKB05': (452, 445)}
TEAM_SAMPLE = [(dx, dy) for dy in range(8, 23, 2) for dx in range(6, 35, 2)]
TEAM_MIN_PX = 8
TEAM_CHECK_GAP = 20.0                # 預設模式：兩次隊伍檢查最短間隔（秒；--fight 點 NPC 前一定檢查）


def classify_team_label(cols: list) -> str:
    """一張卡片隊伍標籤框內的取樣色 → 'leader' / 'member' / 'other'"""
    red = sum(1 for r, g, b in cols if r > 170 and g < 100 and b < 100)
    yel = sum(1 for r, g, b in cols if r > 170 and g > 140 and b < 110)
    if red >= TEAM_MIN_PX and red > yel:
        return 'leader'
    if yel >= TEAM_MIN_PX:
        return 'member'
    return 'other'


def read_team_labels() -> dict | None:
    """切換面板已開著時，一次 pixel 讀 5 張卡片 → {角色: 'leader'|'member'|'other'}；讀不到回 None"""
    pts = [(ax + dx, ay + dy) for ax, ay in TEAM_CARDS.values() for dx, dy in TEAM_SAMPLE]
    try:
        out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
        cols = [tuple(int(v) for v in c.split(',')) for c in out]
    except Exception:
        return None
    if len(cols) != len(pts):
        return None
    n = len(TEAM_SAMPLE)
    return {r: classify_team_label(cols[i * n:(i + 1) * n]) for i, r in enumerate(TEAM_CARDS)}


def judge_team(labels: dict, size: int) -> tuple[bool, str]:
    """純函式：labels 是否有「1 隊長 + (size-1) 隊員」。回 (符合, 說明；不符時列出誰不在隊)。
    只看隊伍本身：面板上其他卡片是單人 / 不在隊（'other'，例如單人 DKB0 或離線的人）不算錯（--team-size 4 時第 5 人單人沒關係；size=5 時 5 人都要在隊，因為隊員數要 4）"""
    lead = [r for r, v in labels.items() if v == 'leader']
    mem = [r for r, v in labels.items() if v == 'member']
    out = [r for r, v in labels.items() if v == 'other']
    desc = f'隊長 {lead or "無"}、隊員 {mem or "無"}、不在隊 / 單人 / 離線 {out or "無"}'
    ok = len(lead) == 1 and len(mem) == size - 1
    return ok, desc


def check_team(size: int, tag: str = '') -> tuple[bool | None, str]:
    """開切換面板（763,760）→ 讀 5 張卡片的隊伍標籤 → 關面板（✕ 1064,208；必要時 ESC）。
    回 (True 隊伍符合 / False 不符 / None 面板沒開或讀不到, 說明)。只在主畫面（idle）時呼叫；開面板後驗證 SIG_PANEL，沒開就不讀、不點面板內座標。"""
    sig = '/'.join(f'{x},{y},{r},{g},{b}' for x, y, r, g, b in SIG_PANEL)
    gui('seq', f'click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; waitpix 1500 {sig} 40; wait 300', note=f'{tag}隊伍檢查：開切換面板')
    res: tuple[bool | None, str] = (None, '切換面板沒打開')
    if read_screen()['state'] == 'panel':
        labels = read_team_labels()
        if labels is None:
            res = (None, '讀不到隊伍標籤像素')
        else:
            ok, desc = judge_team(labels, size)
            res = (ok, desc)
    for _ in range(2):                                 # 關面板：先點 ✕，仍開著再 ESC
        if read_screen()['state'] != 'panel':
            break
        gui('seq', f'click {PANEL_CLOSE[0]} {PANEL_CLOSE[1]}; wait 500', note='隊伍檢查：關切換面板（✕）')
    if read_screen()['state'] == 'panel':
        gui('key', '{ESC}')
    return res


def read_pos() -> tuple[int, int, int] | None:
    """stat.ps1 OCR 讀右上角「地圖ID:x,y」→ (地圖, x, y)；讀不到回 None"""
    m = re.match(r'(\d+):(\d+),(\d+)', stat().get('pos') or '')
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_knocked(last: tuple[int, int, int] | None, cur: tuple[int, int, int] | None) -> bool:
    """被打飛 = 現在在薩姆吉爾村 1000 的儲存點附近，而且「上次不在那裡」（換了地圖，或位置突然跳了 > KO_RADIUS 以上）。
    任務本來就在儲存點附近開始時，last 也在附近 → 不算（要真的被傳走才算）；不知道上次位置（last=None）也不算。"""
    if not cur or cur[0] != SAVE_POINT[0]:
        return False
    near = lambda p: p[0] == SAVE_POINT[0] and max(abs(p[1] - SAVE_POINT[1]), abs(p[2] - SAVE_POINT[2])) <= KO_RADIUS
    if not near(cur):
        return False
    return last is not None and not near(last)


STEP_TEXT_BOX = (80, 270, 245, 175)  # 追蹤列表 OCR 區（標題 + 說明行；深棕字，Dark 170 才讀得到較淺的說明行）
STEP_MIN_RATIO = 0.8                 # 說明文字與任務表 explandTn 的相似度門檻（OCR 偶爾錯 1 字）


def norm_step(t: str) -> str:
    """步驟說明比對前的正規化：去空白與標點"""
    return re.sub(r'[\s·・,.:：，。、!！?？「」『』()（）\[\]【】~～\-—]+', '', t or '')


def read_step_texts(task: str) -> list[str]:
    """OCR 追蹤列表，找出標題 = task 那一格，回傳它「正下方那行說明」的各種讀法（Zoom 2/3/4）；標題不在目前這頁 / 讀不到 → []。
    不捲動、不點任何東西（純讀）。實測（碧青洞窟）：標題 y≈309、說明行 y≈341（差約 32px）。"""
    x, y, w, h = STEP_TEXT_BOX
    r = ps_json('ocr.ps1', x, y, w, h, '-Zooms', '2,3,4', '-Dark', 170)
    lines = sorted(r.get('lines', []), key=lambda o: o['y'])
    titles = [ln for ln in lines if len(ln['text']) >= 2 and match_title(task, ln['text'])]
    if not titles:
        return []
    ty = min(t['y'] for t in titles)
    return [ln['text'] for ln in lines if ty + 18 <= ln['y'] <= ty + 50 and len(ln['text']) >= 2]


def skel_step(t: str) -> str:
    """步驟說明的「骨架」：把「數字 + 樓」（OCR 常把「9樓」讀成單字「婁」、「14樓」讀成「楼」之類）收成同一個符號，其餘不變。
    例「通過碧青9樓的挑戰」「通過碧青婁的」→「通過碧青#的挑戰」「通過碧青#的」"""
    return re.sub(r'[0-9０-９]*[樓婁楼樓]', '#', norm_step(t))


STEP_PREFIX_MIN = 5                  # 說明行被面板邊緣截斷時，用「前綴」比對至少要這麼多字（太短會誤配很多步）
STEP_PREFIX_FACTOR = 0.95            # 前綴比對的折扣（完整相符 1.0 仍優先）
STEP_SKEL_FACTOR = 0.9               # 骨架比對（忽略「數字 + 樓」）的折扣：數字讀對的完整文字要贏過「只剩骨架相同」（9樓 vs 14樓 差 >= 0.05 才分得出來）


def step_score(a: str, b: str) -> float:
    """OCR 讀到的說明 a 與任務表說明 b 的相似度（兩者都已 norm_step）：取下列的最大值——
    ① 原文比對；② 說明被截斷時的原文前綴比對（追蹤條目寬度有限，後半段常被截掉或讀不到；a >= STEP_PREFIX_MIN 字才用，打 STEP_PREFIX_FACTOR 折）；
    ③ 骨架比對（把「數字 + 樓」收成同一符號，OCR 常把「9樓」讀成單字「婁」；打 STEP_SKEL_FACTOR 折，避免「通過碧青9樓」「通過碧青14樓」骨架相同時蓋過數字讀對的結果）；④ 骨架前綴（兩個折扣相乘）。
    骨架相同而 NPC 不同的步驟（碧青步 2 / 3）會平手 → match_step 交給「目前所在地圖」判定，判不了才退出碼 31"""
    if a == b:
        return 1.0
    sa, sb = skel_step(a), skel_step(b)
    sm = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio()
    r = max(sm(a, b), sm(sa, sb) * STEP_SKEL_FACTOR)
    if len(a) >= STEP_PREFIX_MIN and len(b) > len(a):
        r = max(r, sm(a, b[:len(a)]) * STEP_PREFIX_FACTOR)
    if len(sa) >= STEP_PREFIX_MIN and len(sb) > len(sa):
        r = max(r, sm(sa, sb[:len(sa)]) * STEP_SKEL_FACTOR * STEP_PREFIX_FACTOR)
    return r


def _npc_map_of(row: dict):
    try:
        return (walk.psa.by_id('Npc').get(row.get('endNpc')) or {}).get('map')
    except Exception:
        return None


def match_step(ts: list, texts: list[str], cur_map_fn=None) -> tuple[dict | None, str]:
    """純函式：追蹤條目說明文字 texts（OCR 各種讀法）對任務表各步的 explandTn / explandCn。
    取相似度（step_score：原文 / 忽略「數字+樓」誤讀 / 說明被截斷的前綴）最高且 >= STEP_MIN_RATIO 的步驟。
    有另一個「不同 NPC」的步驟相似度差 < 0.05 → 視為對不準；但若給了 cur_map_fn（回傳目前所在地圖 ID 或 None），
    就用「--fight 本來就站在 NPC 旁」這個事實，只留 NPC 在目前地圖的候選：剛好剩 1 個 NPC（可能多步同 NPC，取最前一步）才採用，其他情況回 None（退出碼 31）。回 (步驟列或 None, 說明)"""
    best: dict[int, float] = {}
    for tx in texts:
        a = norm_step(tx)
        if not a:
            continue
        for k, t in enumerate(ts):
            for fld in ('explandTn', 'explandCn'):
                b = norm_step(t.get(fld))
                if b:
                    best[k] = max(best.get(k, 0.0), step_score(a, b))
    if not best:
        return None, '追蹤條目說明文字讀不到'
    rank = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    k0, r0 = rank[0]
    if r0 < STEP_MIN_RATIO:
        return None, f'說明文字 {texts} 對不到任務表任何一步（最像 第 {ts[k0].get("step")} 步，相似度 {r0:.2f} < {STEP_MIN_RATIO}）'
    close_ks = [k for k, r in rank if r0 - r < 0.05]
    if len({ts[k].get('endNpc') for k in close_ks}) > 1:
        steps = '、'.join(str(ts[k].get('step')) for k in close_ks)
        cur = cur_map_fn() if cur_map_fn else None
        same = [k for k in close_ks if cur and _npc_map_of(ts[k]) == cur]
        if len({ts[k].get('endNpc') for k in same}) == 1:
            k0 = same[0]
            return ts[k0], f'說明文字 {texts} 相似步驟 {steps}（NPC 不同）→ 依目前所在地圖 {cur} 判定第 {ts[k0].get("step")} 步（相似度 {best[k0]:.2f}）'
        return None, f'說明文字 {texts} 同時像第 {steps} 步（NPC 不同），無法判定；請改用 --step N'
    return ts[k0], f'說明文字 {texts} → 第 {ts[k0].get("step")} 步（相似度 {r0:.2f}）'


def resolve_npc(a) -> tuple[int, int] | None:
    """--fight 的 NPC 地圖座標：--npc X,Y，或 --npc auto = 「目前步驟」的 endNpc（--task 任務；--step N 明確指定，不給就 OCR 追蹤條目下方的說明行
    對照 Task 表 explandTn）。讀不到 / 對不到 → 不退回第一個戰鬥步（2026-10-10 抓錯 8 樓守護獸的事故），a.resolve_rc = EXIT_STEP_UNKNOWN，回 None"""
    a.resolve_rc = 4
    if a.npc.lower() == 'auto':
        if not a.task:
            log('--npc auto 需要 --task（用任務步驟找目前步驟的 NPC）')
            return None
        g, ts, _ = walk.psa.task_steps(a.task)
        if not ts:
            log(f'任務表找不到「{a.task}」')
            a.resolve_rc = EXIT_STEP_UNKNOWN
            return None
        if a.step:
            row = next((t for t in ts if t.get('step') == a.step), None)
            why = f'--step {a.step}'
        else:
            row, why = match_step(ts, read_step_texts(a.task), None if a.at else (lambda: (read_pos() or (None,))[0]))
        if row is None:
            event(f'--npc auto 取不到目前步驟：{why} → 不點 NPC，退出碼 {EXIT_STEP_UNKNOWN}（請 shot 看追蹤條目，改用 --step N 或 --npc X,Y）')
            a.resolve_rc = EXIT_STEP_UNKNOWN
            return None
        n = walk.psa.by_id('Npc').get(row.get('endNpc'))
        if not n:
            event(f'--npc auto：第 {row.get("step")} 步（{why}）沒有 endNpc → 退出碼 {EXIT_STEP_UNKNOWN}')
            a.resolve_rc = EXIT_STEP_UNKNOWN
            return None
        kind = walk.psa.classify_step(row)[0]
        event(f'--npc auto：目前步驟 = 第 {row.get("step")} 步（{why}；{kind}）→ {walk.psa.nm(n)} @ 地圖 {n.get("map")}:{n.get("x")},{n.get("y")}')
        a.npc_map = n.get('map')
        return (n['x'], n['y'])
    m = re.fullmatch(r'(\d+)[,:](\d+)', a.npc.strip())
    if not m:
        log('--fight 要給 --npc X,Y（NPC 地圖座標）/ --npc auto（用 --task 查），或加 --no-click（已自己點過 NPC）')
        return None
    return (int(m[1]), int(m[2]))


def click_npc(npc: tuple[int, int], a) -> bool:
    """依自己的座標算 NPC 的畫面位置並點一下（走路函式 walk.npc_screen；不巡路、不亂走）。座標讀不到 / 太遠 / 地圖不符 → False"""
    if a.at:
        m = re.fullmatch(r'(\d+),(\d+)', a.at.strip())
        cur = (getattr(a, 'npc_map', None), int(m[1]), int(m[2])) if m else None
    else:
        cur = None
        for _ in range(3):
            if (cur := read_pos()):
                break
            time.sleep(1.0)
    if not cur:
        log('讀不到自己的座標（--at X,Y 可手動給）')
        return False
    want_map = getattr(a, 'npc_map', None)
    if want_map and cur[0] and cur[0] != want_map:
        log(f'目前在地圖 {cur[0]}，NPC 在地圖 {want_map}：不在同一張圖，先傳送 / 走過去（--fight 不巡路）')
        return False
    at = (cur[1], cur[2])
    dx, dy = npc[0] - at[0], npc[1] - at[1]
    if not walk.reachable(dx, dy):
        log(f'NPC {npc} 離我 {at} 太遠或點擊位置落在 UI 上（dx={dx}, dy={dy}）→ 先走近一點再跑 --fight')
        return False
    nx, ny = walk.npc_screen(npc, at)
    gui('seq', f'{PRIMER}; click {nx} {ny}', note=f'--fight 點 NPC {npc}（我在 {at}）')
    event(f'--fight 點 NPC {npc}（我在 {at}）→ 畫面 {nx},{ny}')
    return True


def _main() -> int:
    ap = argparse.ArgumentParser(description='解任務監測：對話按確認、戰鬥按刷新角色、巡路停了重點任務追蹤')
    ap.add_argument('--once', action='store_true', help='只判斷一次、做一個動作就結束')
    ap.add_argument('--every', type=float, default=None, help='輪詢間隔秒數（預設 1.0；連續 N 次的規則已換算成秒，見 IDLE_CONFIRM_SECS 等）')
    ap.add_argument('--solo', action='store_true', help='單人逃跑風格（手動逃跑）：完整戰鬥按逃跑鈕（自動戰鬥開著先關）；路上小怪不刷新；到 NPC 出對話框 → ESC 後停下（退出碼 20）；被打飛退出碼 21')
    ap.add_argument('--stop-after-dialog', action='store_true', help='對話框按完、回主畫面連續閒置 2 次就結束（沒有獲得物品視窗的對話步用；組隊後單步對話用，避免自動點下一步追蹤開始巡路）')
    ap.add_argument('--disband-after', action='store_true', help='這步完成（--stop-after-dialog / --stop-after-rewards 結束）後立刻解散隊伍：切組隊分頁 → 點隊長列 → 解散，每步驗證，失敗退出碼 %d 且不亂點' % EXIT_DISBAND_FAIL)
    ap.add_argument('--fight', action='store_true', help='戰鬥步（要先站在 NPC 附近；不巡路）：點 NPC → 對話左鈕 → 開打；只有點 NPC / 按對話框後 %d 秒內開始的才是任務 / BOSS 戰（開自動戰鬥 + 刷新角色、打完退出碼 0）；其他戰鬥是路上小怪（關自動戰鬥、按逃跑、不刷新）；沒反應退出碼 22、對話後沒開打 23、被打飛 21' % QUEST_BATTLE_WINDOW)
    ap.add_argument('--npc', default='', help='--fight 用：NPC 的地圖座標 X,Y，或 auto（讀追蹤條目目前步驟說明對 --task 的任務表找 NPC；讀不到退出碼 31，可改 --step N）；不給 = 必須加 --no-click')
    ap.add_argument('--step', type=int, default=0, help='--fight 用：明確指定任務第 N 步（Task.step）的 endNpc 當 NPC（等於 --npc auto 但不 OCR 追蹤條目；需要 --task）')
    ap.add_argument('--team-size', type=int, default=None, help='隊伍人數檢查（預設 5）：--fight 點 NPC 前、預設模式每次點追蹤 / 黃問號前，開切換面板確認 1 隊長 + (N-1) 隊員，不符 → 不點（--fight 退出碼 %d、執行中脫隊 %d）；開始前第一次點 / 按對話框前一定先驗（不符 30）；0 或 1 = 跳過；--solo / --fight --no-click 不檢查' % (EXIT_TEAM_MISMATCH, EXIT_TEAM_LOST))
    ap.add_argument('--at', default='', help='--fight 用：自己目前的座標 X,Y（不給就 OCR 讀右上角）')
    ap.add_argument('--no-click', action='store_true', help='--fight 用：不點 NPC（已手動點過 / 對話已開），從現在起算開打時間窗')
    ap.add_argument('--max-seconds', type=int, default=900, help='最長執行秒數（預設 900）')
    ap.add_argument('--task', default='', help='追蹤列表上的任務名（例：黃金羚羊之謎）；點追蹤前先 OCR 核對標題，名稱不符絕不點')
    ap.add_argument('--no-marker', action='store_true', help='不找 NPC 頭上的黃色問號')
    ap.add_argument('--no-track', action='store_true', help='不主動點任務追蹤')
    ap.add_argument('--no-clef', action='store_true', help='不用 Clef（Cloudflare Workers AI）加速層，全走原本的規則 / OCR（也可設環境變數 PSA_NO_CLEF=1）')
    ap.add_argument('--no-refresh', action='store_true', help='戰鬥不按刷新角色（預設：--solo / --fight 只在任務 / BOSS 戰刷新，組隊預設模式每場都刷新）')
    ap.add_argument('--stop-after-rewards', type=int, default=0, help='領到第 N 次獲得物品視窗後停（0 = 不停）')
    a = ap.parse_args()
    if a.step and not a.npc:
        a.npc = 'auto'
    if layout.current() != '2880x1659':
        log('quest.py 只量過 2880×1659 版面，先跑 gui.sh max；見 ui/layout-1920x1017.md')
        return 4
    if a.solo and a.fight:
        log('--solo（逃跑）與 --fight（打）互斥')
        return 4
    if a.disband_after and (a.solo or a.fight or not (a.stop_after_dialog or a.stop_after_rewards)):
        log('--disband-after 只能搭配 --stop-after-dialog 或 --stop-after-rewards（不可與 --solo / --fight 並用）')
        return 4
    if a.every is None:
        a.every = DEFAULT_EVERY
    npc_xy = None                        # --fight：要點的 NPC 地圖座標
    if a.fight:
        a.no_track = True                # --fight 假設已站在 NPC 旁，絕不點任務追蹤巡路
        if not a.no_click:
            npc_xy = resolve_npc(a)
            if npc_xy is None:
                return a.resolve_rc
    guard_ko = a.solo or a.fight         # 只有這兩種風格才會被打飛後要停手
    if not a.no_track and not a.task:
        log('沒給 --task：不知道要點哪個任務追蹤（點錯任務是之前的老問題）。請加 --task 任務名，或用 --no-track（只處理對話 / 戰鬥）')
        return 4
    clef.set_logger(event)
    n_old = cleanup_old_shots()
    if n_old:
        event(f'清理 {n_old} 張 {SHOT_KEEP_DAYS} 天前截圖')
    if a.no_clef:
        clef.set_enabled(False)
    else:
        clef.available()         # 啟動時檢查一次：沒 token 會在 stderr 醒目提示並寫事件 log
    end = time.time() + a.max_seconds
    clef_wait = 0                # 連續被 Clef 解釋成「載入 / 戰鬥」的 unknown 次數
    clef_wait_t0 = 0.0           # 這一串 Clef「載入 / 戰鬥」判斷的起始時間（CLEF_WAIT_SECS 用）
    marker_fail = 0              # 連續點黃色問號沒反應的次數
    task_miss = 0
    event(f'開始監測（每 {a.every}s，最長 {a.max_seconds}s）')
    unknown = 0
    unknown_t0 = 0.0             # 這一串不認得的第一次時間
    track_fail = 0
    track_t = 0.0                # 最後一次點任務追蹤的時間（TRACK_RETRY_SECS）
    idle_t0 = 0.0                # 這一串閒置的第一次時間（IDLE_CONFIRM_SECS）
    tracked = False              # 剛點過任務追蹤，還沒看到任何反應
    rewards = 0
    checked_rewards = 0          # 已做過「領獎後完整列表檢查」的獎勵次數
    last = ''
    battles = dialogs = 0
    last_full_log = 0.0
    last_action = 0.0            # 最後一次對話框 / 點 NPC / 點問號的時間（time.time()）
    quest_battle = False         # 目前這場戰鬥是不是任務戰鬥（戰鬥開始那一刻決定）
    prev_st = ''
    idle_streak = 0
    last_pos = None                              # 上一次讀到的 (地圖, x, y)；對戰鬥畫面 OCR 會讀不到，起點最多試 3 次
    for _ in range(3 if guard_ko else 0):
        if (last_pos := read_pos()) or read_screen()['state'] == 'battle':
            break
        time.sleep(1.0)
    last_pos_t = time.time()
    ko_pending = False           # 剛打完一場 / 讀圖中 → 下次閒置時查一次位置
    last_click_t = 0.0           # 逃跑 / 自動戰鬥鈕最後一次點擊時間（避免連點）
    battle_t0 = 0.0              # 這場戰鬥開始時間
    in_battle = False            # 戰鬥中（直到看到主畫面 / 對話 / 領獎 / 巡路才算結束；中間 unknown / panel 不重新分類）
    boss = False                 # 目前這場是不是 BOSS 戰（戰鬥開始那一刻決定，打完才重設）
    boss_seen = False            # --fight：已打過 BOSS 戰
    npc_click_t = 0.0            # --fight：點 NPC 的時間
    warned_quick = False
    auto_presses = 0             # 組隊預設模式：本場戰鬥按自動戰鬥鈕的次數
    select_tries = 0             # 連續幾輪看到「選擇對象」面板（點了還在就別一直點）
    last_refresh_t = 0.0         # 本場戰鬥最後一次按刷新角色的時間（REFRESH_GAP）
    if guard_ko:
        event(f'模式：{"單人逃跑 --solo" if a.solo else "戰鬥步 --fight"}；起點 {last_pos}')
    team_size = 5 if a.team_size is None else a.team_size
    team_on = team_size > 1 and not a.solo and (bool(npc_xy) if a.fight else True)     # --solo 本來就是單人跑；--fight --no-click 不點 NPC。預設模式即使 --no-track 也會按對話框 → 一樣要驗隊伍
    last_team_check = 0.0
    pre_checked = not team_on    # 第一次點任何東西 / 按對話框之前是否已驗過隊伍（不受 TEAM_CHECK_GAP 限制）
    dialog_esc = 0               # 啟動時對話框已開：為了開切換面板先 ESC 關掉的次數

    def team_gate(tag: str, code: int, force: bool = False) -> int:
        """點 NPC / 追蹤前的隊伍檢查（脫隊偵測的保底做法：聊天日誌「離開了隊伍」讀不可靠，所以每次要點之前確認隊伍還在）。
        符合（或不檢查 / 剛檢查過）回 0；隊伍不符或讀不到 → 寫事件 log 回 code（呼叫端直接 return）"""
        nonlocal last_team_check
        if not team_on or (not force and time.time() - last_team_check < TEAM_CHECK_GAP):
            return 0
        ok_, desc = check_team(team_size, tag)
        last_team_check = time.time()
        if ok_:
            log(f'隊伍檢查通過：{desc}')
            return 0
        shot = snap('team-mismatch')
        if ok_ is None:
            event(f'{tag}隊伍檢查失敗：{desc} → 無法確認隊伍完整，不點，退出碼 {code}', shot)
        else:
            event(f'{tag}隊伍不符（要 1 隊長 + {team_size - 1} 隊員）：{desc} → 有人不在隊，不點，退出碼 {code}', shot)
        print('隊伍不完整，沒有點 NPC / 追蹤', flush=True)
        return code

    if a.fight:
        if npc_xy and read_screen()['state'] == 'idle':
            rc = team_gate('--fight 點 NPC 前：', EXIT_TEAM_MISMATCH, force=True)
            if rc:
                return rc
            pre_checked = True
        if npc_xy:
            if not click_npc(npc_xy, a):
                return 4
            npc_click_t = last_action = time.time()
        elif a.no_click:
            last_action = time.time()
            event('--fight --no-click：不點 NPC，從現在起算 BOSS 戰時間窗')
    while True:
        s = read_screen()
        st = s['state']
        if st in ('idle', 'walking', 'dialog', 'reward'):
            if in_battle:
                battleguard.release()          # 戰鬥結束 → 刪鎖檔，ass.py 可以動了
            in_battle = False
        in_battle_new = st == 'battle' and not in_battle
        if in_battle_new:
            in_battle = True
            battleguard.acquire(f'quest.py {"--solo" if a.solo else "--fight" if a.fight else "預設"}')   # 戰鬥中鎖檔：ass.py 看到就不改外掛設定
            battle_t0 = time.time()
            quest_battle = is_quest_battle(last_action, time.time())
            boss = quest_battle
            boss_seen = boss_seen or boss
            log(f'戰鬥開始：{"任務戰鬥（對話 / 點 NPC 後 %ds 內）" % QUEST_BATTLE_WINDOW if quest_battle else "一般遇敵"}')
            if a.fight:
                event(f'--fight 戰鬥開始：{"任務 / BOSS 戰（點 NPC / 對話後 %.0f 秒）→ 自動戰鬥 + 刷新角色" % (time.time() - last_action) if boss else "路上小怪 → 手動逃跑（不刷新）"}')
        if guard_ko and prev_st == 'battle' and st != 'battle':
            ko_pending = True
        prev_st = st
        if st != 'select':
            select_tries = 0
        else:
            select_tries += 1
            if select_tries <= SELECT_MAX_TRIES and handle_select_panel():
                last_action = time.time()                      # 點了 NPC = 任務互動（戰鬥時間窗從這裡起算）
                if npc_click_t:
                    npc_click_t = last_action                  # --fight：「點 NPC 後 12 秒沒反應」重新計時（還要等 NPC 走過來開對話框）
                if a.once:
                    return 0
                time.sleep(a.every)
                continue
            st = 'unknown'                                     # 找不到黃字 / 點了面板還在 → 不亂點，照「不認得」規則（3 次 + 5 秒 → 交給使用者）
            s = dict(s, state='unknown')
        if st in ('unknown', 'error'):
            # 先給 netwatch 看：「網路異常，是否重連?」提示 / 登入畫面（自動按登錄重登；失敗才 halt exit 10，不輸入帳密）
            nr = netwatch.guard('quest')
            if nr['status'] == 'reconnected':
                event('網路斷線後已恢復（netwatch），重新判斷畫面')
                tracked, track_fail, marker_fail, last, unknown = False, 0, 0, '', 0
                continue
            if nr.get('failed'):
                continue
        if st != last:
            log(f'狀態 {last or "-"} → {st}' + (f'（金黃點 {s["gold"]}）' if st in ('walking', 'idle') else ''))
        last = st
        if st != 'unknown':
            unknown = 0
            clef_wait = 0
        if st == 'idle':
            if idle_streak == 0:
                idle_t0 = time.time()
            idle_streak += 1
        else:
            idle_streak = 0
        idle_ok = idle_confirmed(idle_streak, idle_t0, time.time())
        if st in ('dialog', 'reward', 'battle'):
            marker_fail = 0
        if st in ('walking', 'dialog', 'reward', 'battle'):
            if tracked:
                tracked, track_fail = False, 0
        if not pre_checked and st in ('idle', 'dialog'):
            # 啟動後第一次點 / 按之前一定先驗隊伍（2026-10-10 18:44 事件：--solo 後單人，--stop-after-rewards 啟動直接按對話框 → 只有 DKB0 交任務）
            if st == 'dialog':
                # 對話框開著蓋住切換面板鈕：先 ESC 關掉（不回答任何選項，同 --solo），回主迴圈等 idle 再驗；ESC 3 次還開著 → 無法驗證，不按
                if dialog_esc >= 3:
                    event(f'啟動時對話框開著，ESC {dialog_esc} 次仍關不掉 → 無法先驗隊伍，不按對話框，退出碼 {EXIT_TEAM_MISMATCH}', snap('team-mismatch'))
                    return EXIT_TEAM_MISMATCH
                dialog_esc += 1
                gui('key', '{ESC}', note='啟動時對話框已開：先 ESC 關閉（不回答），驗過隊伍才處理')
                time.sleep(a.every)
                continue
            if (rc := team_gate('開始前：', EXIT_TEAM_MISMATCH, force=True)):
                return rc
            pre_checked = True
        if st == 'dialog' and a.solo:
            shot = snap('npc-dialog')
            gui('key', '{ESC}', note='到達 NPC：ESC 關閉對話框（不回答任何選項）')
            event(f'--solo 到達 NPC：對話框已 ESC 關閉，停下交給組隊（退出碼 {EXIT_AT_NPC}）', shot)
            print('到達 NPC（對話框已 ESC 關閉）', flush=True)
            return EXIT_AT_NPC
        if st == 'dialog':
            dialogs += 1
            shot = snap('dialog')
            gui('seq', f'click {DIALOG_NEXT[0]} {DIALOG_NEXT[1]}')
            last_action = time.time()
            event(f'對話框 #{dialogs}：按左鈕 {DIALOG_NEXT}', shot)
        elif st == 'reward':
            rewards += 1
            shot = snap('reward')
            gui('seq', f'click {REWARD_OK[0]} {REWARD_OK[1]}')
            event(f'獲得物品視窗 #{rewards}：按確認', shot)
            if a.stop_after_rewards and rewards >= a.stop_after_rewards:
                event(f'已領 {rewards} 次獎勵視窗，停止（--stop-after-rewards）')
                return finish(a)
        elif st == 'battle':
            # 手動逃跑模式（--solo / --fight）：路上小怪只逃、不刷新；任務 / BOSS 戰（--fight 且點 NPC / 對話後 QUEST_BATTLE_WINDOW 內開始）開自動戰鬥 + 刷新角色。
            # 組隊預設模式：每一場戰鬥都刷新（完整戰鬥先確保自動戰鬥開）
            manual = a.solo or a.fight
            boss_now = a.fight and boss
            full = bool(s.get('full'))
            act = None
            if in_battle_new:
                auto_presses = 0
                last_refresh_t = 0.0
            if manual and not full:
                if not boss_now and not warned_quick:
                    event(f'--{"solo" if a.solo else "fight"}：遇敵但沒有完整戰鬥畫面（只看到 VS 牌 = 快速戰鬥還開著？）→ 無法逃跑，只能等；請先關快速戰鬥')
                    warned_quick = True
            elif manual:
                act = plan_battle_action(s, boss_now, time.time() - last_click_t)
                if act:
                    xy = {'escape': ESCAPE_BTN, 'auto_off': AUTO_BTN, 'auto_on': AUTO_BTN}[act]
                    gui('seq', f'click {xy[0]} {xy[1]}', note={'escape': '完整戰鬥小怪 → 逃跑', 'auto_off': '小怪戰 → 先關自動戰鬥', 'auto_on': 'BOSS 戰 → 開自動戰鬥'}[act])
                    last_click_t = time.time()
                    battles += 1
                    event({'escape': f'{"--solo" if a.solo else "--fight 小怪"} 戰鬥中：按逃跑（第 {battles} 次）',
                           'auto_off': '--solo / 小怪戰：自動戰鬥是開的 → 先按一下關掉，下一回合再逃',
                           'auto_on': f'--fight 任務 / BOSS 戰：自動戰鬥鈕是關的 → 按一下（第 {battles} 次）'}[act])
                elif boss_now and time.time() - last_full_log > 20:
                    event('--fight 任務 / BOSS 戰中（自動戰鬥已開，等打完）')
                    last_full_log = time.time()
            elif full:
                # 組隊預設模式的完整戰鬥：自動戰鬥是關的 → 按 1380,600 讓全隊自動打完（不逃跑：組隊逃跑行為未驗證）
                act = plan_battle_action(s, False, time.time() - last_click_t, party=True)
                if act:
                    if auto_presses >= AUTO_STUCK_MAX:
                        shot = snap('battle-stuck')
                        event(f'組隊完整戰鬥：自動戰鬥鈕按了 {auto_presses} 次仍是關的（寵物指令視窗 / 其他卡住畫面？）→ 停，退出碼 {EXIT_BATTLE_STUCK}（人工：戰寵視窗先選攻擊再按選擇）', shot)
                        return EXIT_BATTLE_STUCK
                    gui('seq', f'click {AUTO_BTN[0]} {AUTO_BTN[1]}', note='組隊完整戰鬥 → 開自動戰鬥')
                    last_click_t = time.time()
                    auto_presses += 1
                    event(f'組隊完整戰鬥：自動戰鬥鈕是關的 → 按 {AUTO_BTN}（本場第 {auto_presses} 次）')
            if should_refresh(a, boss_now, full, s.get('auto_off'), time.time() - last_refresh_t):
                battles += 1
                refresh_characters(full)
                last_refresh_t = time.time()
                event(f'戰鬥中（{"完整" if full else "快速"}戰鬥）：按刷新角色（第 {battles} 次）')
            elif not act and full and time.time() - last_full_log > 20:
                event('完整戰鬥畫面（自動戰鬥已開，等打完）')
                last_full_log = time.time()
        elif st == 'panel':
            gui('key', '{ESC}')
            event('切換角色面板殘留，ESC 關閉')
        elif st == 'idle' and guard_ko and (ko_pending or time.time() - last_pos_t >= 12) and not (ko_pending and not idle_ok):
            # 打完一場後（或每 12 秒）查位置：被打飛回村 → 退出碼 21。剛打完的第一次閒置先略過一輪（畫面轉場中 OCR 讀不準）
            ko_pending = False
            cur = read_pos()
            last_pos_t = time.time()
            if is_knocked(last_pos, cur):
                shot = snap('KNOCKED')
                event(f'偵測到被打飛：{last_pos} → {cur}（薩姆吉爾儲存點附近）→ 停下（退出碼 {EXIT_KNOCKED}）', shot)
                print(f'被打飛回村：{cur}', flush=True)
                return EXIT_KNOCKED
            if cur:
                last_pos = cur
        elif st == 'idle' and a.fight:
            now = time.time()
            if boss_seen:
                if idle_ok:
                    event(f'--fight BOSS 戰結束（對話 {dialogs}、獎勵 {rewards}），連續閒置 {idle_streak} 次 → 結束，不巡路')
                    print('BOSS 戰結束', flush=True)
                    return 0
            elif npc_click_t and not dialogs and now - npc_click_t >= NPC_WAIT:
                shot = snap('no-npc')
                event(f'--fight 點 NPC 後 {NPC_WAIT:.0f} 秒內沒對話框也沒戰鬥 → 沒點到 NPC（或被小怪打斷）→ 不亂走，退出碼 {EXIT_NO_NPC}', shot)
                print('沒點到 NPC', flush=True)
                return EXIT_NO_NPC
            elif dialogs and now - last_action >= QUEST_BATTLE_WINDOW:
                shot = snap('no-battle')
                event(f'--fight 對話後 {QUEST_BATTLE_WINDOW:.0f} 秒沒開打（這步可能不戰鬥）→ 退出碼 {EXIT_NO_BATTLE}', shot)
                print('對話後沒開打', flush=True)
                return EXIT_NO_BATTLE
        elif a.stop_after_dialog and (dialogs or rewards) and st in ('idle', 'walking'):
            # 這一步已經對話 / 領獎過：從這裡起絕不點追蹤、不點 NPC 頭上黃「?」（否則會把下一步也對完、接著巡路 = 2026-10-10 深紅事故）。
            # 只等閒置 2 次就停；遊戲自己又進入 Auto Walking → 退出碼 24（呼叫端立刻處理，例如 --disband-after 已先解散）
            if st == 'walking':
                event(f'--stop-after-dialog：步驟完成後遊戲自己開始 Auto Walking（對話 {dialogs}、獎勵 {rewards}）→ 不點任何追蹤，退出碼 {EXIT_AUTOWALK}')
                return finish(a, EXIT_AUTOWALK)
            if idle_ok:
                event(f'步驟結束（對話 {dialogs}、獎勵 {rewards}），連續閒置 {idle_streak} 次 → 停（--stop-after-dialog，未點追蹤 / 黃問號）')
                return finish(a)
        elif st == 'idle':
            # 做完事（對話 / 領獎）後連續 2 次閒置 = 這一步結束，馬上結束不空等（有領過獎勵，或 --no-track 時對話過）
            if idle_ok and not (rewards and not a.no_track and a.task and not tracked and checked_rewards < rewards) and (rewards or (a.no_track and dialogs) or (a.stop_after_dialog and dialogs)):
                event(f'步驟結束（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}），連續閒置 {idle_streak} 次，提前結束')
                return finish(a)
            wait_track = tracked and time.time() - track_t < TRACK_RETRY_SECS     # 剛點過追蹤：給遊戲時間開始巡路，不重點、不計失敗
            if tracked and not wait_track:
                track_fail += 1
                if track_fail >= 2:
                    shot = snap('no-autowalk')
                    event('點了任務追蹤兩次都沒進入巡路 / 對話 / 戰鬥 → 這個任務步驟不能自動巡路或已完成，請改手動（walk.py + 點 NPC）', shot)
                    return 3
            if wait_track:
                pass
            elif rewards > checked_rewards and not a.no_track and a.task:
                # 領過獎勵後第一次回到主畫面：立刻掃整個追蹤列表。目標任務不在列表 = 任務完成（不空轉）；還在 = 下一步，順便點它
                if (rc := team_gate('領獎後點追蹤前：', EXIT_TEAM_LOST)):
                    return rc
                checked_rewards = rewards
                time.sleep(1.0)                              # 等獲得物品視窗收掉、列表刷新
                res = track_task(a.task)
                if res is None:
                    checked_rewards = rewards - 1            # 被打斷，下次回主畫面再查
                elif res:
                    tracked, track_t = True, time.time()
                    task_miss = 0
                else:
                    shot = snap('task-done')
                    event(f'領過 {rewards} 次獎勵後追蹤列表整個掃完沒有「{a.task}」→ 任務完成（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}）', shot)
                    print(f'任務完成：{a.task}', flush=True)
                    return 0
            elif not a.no_track:
                # 檢測方針：1. 場景有黃色問號 → 優先點它；2. 沒有 → 追蹤列表核對任務名再點
                if not wait_track and (rc := team_gate('點追蹤 / 黃問號前：', EXIT_TEAM_LOST)):
                    return rc
                mk = None if a.no_marker else find_marker()
                log('找黃色問號：' + (f'{mk["x"]},{mk["y"]} n={mk["n"]}' if mk else '沒有'))
                if mk and marker_fail < len(MARK_NPC_DYS):
                    dy = MARK_NPC_DYS[marker_fail]
                    tx, ty = mk['x'], mk['y'] + dy
                    gui('seq', f'{PRIMER}; click {tx} {ty}', note=f'點 NPC 頭上黃色標記下方（標記 {mk["x"]},{mk["y"]} n={mk["n"]}）')
                    last_action = time.time()
                    event(f'閒置：場景有黃色標記 {mk["x"]},{mk["y"]}（{mk["w"]}x{mk["h"]} n={mk["n"]}）→ 點 {tx},{ty}')
                    # 點 NPC = 隊伍自己走過去再開對話框，途中不會出現 Auto Walking 字樣 → 等最多 8 秒看有沒有對話 / 戰鬥 / 領獎 / 巡路
                    reacted = False
                    for _ in range(8):
                        time.sleep(1.0)
                        if read_screen()['state'] != 'idle':
                            reacted = True
                            break
                    marker_fail = 0 if reacted else marker_fail + 1       # 連續沒反應 2 次 → 這個問號點不到，改走追蹤列表
                    tracked = False
                elif (res := track_task(a.task)) is None:
                    log('找追蹤時畫面變了（對話 / 戰鬥 / 領獎），交回主迴圈')
                elif res:
                    tracked, track_t = True, time.time()
                    task_miss = 0
                else:
                    if rewards:                      # 領過獎勵又找不到 = 完成
                        shot = snap('task-done')
                        event(f'追蹤列表整個掃完沒有「{a.task}」，且已領過獎勵 → 任務完成', shot)
                        print(f'任務完成：{a.task}', flush=True)
                        return 0
                    task_miss += 1
                    if task_miss < 2:        # 可能剛好剛換圖 / 捲動慣性 / 標記剛出現：下一輪再來一次（會先重找黃色問號）
                        log(f'追蹤列表找不到「{a.task}」（第 {task_miss} 次），下一輪重試')
                    else:
                        shot = snap('task-not-found')
                        event(f'追蹤列表掃完（到頂 + 到底）都找不到「{a.task}」（連續 {task_miss} 次，沒領過獎勵）→ 沒點任何東西，退出', shot)
                        return 5
        elif st == 'unknown' or st == 'error':
            if st == 'unknown' and (clef_wait == 0 or time.time() - clef_wait_t0 < CLEF_WAIT_SECS) and clef.available() and (img := clef_shot_bytes()):
                cr = clef.classify_scene(img)
                if cr:
                    log(f'Clef 場景：{cr["scene"] or "信心不足"} p={cr["p"]:.2f}（{cr["model"]}）驗證窗機率 {cr["verify_p"]:.3f}')
                    if cr['alarm']:          # 只多一道警報：verify >= clef.VERIFY_ALARM（高信心）或場景判驗證窗 → 馬上停手（鐵則 5）；模型說沒有不會放行任何事
                        shot = snap('UNKNOWN')
                        event(f'警告：Clef 判斷可能是答題 / 驗證視窗（verify p={cr["verify_p"]:.3f}，場景 {cr["scene"]}）→ 停止自動操作，請使用者處理', shot)
                        print('!!! 請人工檢查畫面（鐵則 5：驗證視窗不可亂猜答案）', flush=True)
                        return 2
                    if cr['scene'] in CLEF_WAIT_SCENES and (clef_wait == 0 or time.time() - clef_wait_t0 < CLEF_WAIT_SECS):
                        clef_wait += 1
                        if clef_wait == 1:
                            clef_wait_t0 = time.time()
                            event(f'Clef 判斷為「{cr["scene"]}」（p={cr["p"]:.2f}），不算不認得（最多連續 {CLEF_WAIT_SECS:.0f} 秒）')
                        if a.once:
                            return 0
                        time.sleep(a.every)
                        continue
            if unknown == 0:
                unknown_t0 = time.time()
            unknown += 1
            log(f'不認得的畫面 {unknown}/3 {s}')
            if unknown >= 3 and time.time() - unknown_t0 >= UNKNOWN_CONFIRM_SECS:
                shot = snap('UNKNOWN')
                event('警告：連續 3 次遇到不認得的畫面（可能是答題 / 防腳本驗證視窗）→ 停止自動操作，請使用者處理', shot)
                print('!!! 請人工檢查畫面（鐵則 5：驗證視窗不可亂猜答案）', flush=True)
                return 2
        if a.once:
            return 0
        if time.time() >= end:
            event(f'時間到，結束（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}）')
            return 0
        time.sleep(a.every)


def main() -> int:
    """包一層：不論怎麼結束（含例外 / Ctrl-C）都刪自己的戰鬥鎖檔"""
    winenv.enable_server()   # 長程序：用常駐 server 讀畫面（預設關，PSA_GUI_SERVER=1 才啟用）
    try:
        return _main()
    finally:
        battleguard.release()
        winenv.shutdown_server()   # 明確關常駐 server（送 quit + 關 stdin），不只靠 atexit


if __name__ == '__main__':
    sys.exit(main())
