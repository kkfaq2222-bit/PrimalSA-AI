---
name: psa-quick-team
description: Use when the PrimalSA (精靈王石器) characters need to be grouped into one party — the user asks to 組隊 / 快速組隊 / 組五人隊伍, or a task needs all logged-in characters (DKB0…) in the same team.
---

# 快速組隊（5 角色組一隊）

**REQUIRED BACKGROUND:** 先載入 psa-game-ui（工具、操作迴圈、紅區）。介面細節見 `../psa-game-ui/ui/team.md`。
**使用者的視窗是 1920×1017（優先）**：直接跑 `PSA_EXE_MATCH=<客戶端代號> uv run --no-project python tools/gui/q1920.py team`（一鍵組隊並驗證；唯讀檢查用 `team.py check`），座標見 `../psa-game-ui/ui/layout-1920x1017.md`。下面的手動步驟座標只在客戶區 2880×1659（前人版面）有效。工具：`G="bash tools/gui/gui.sh"`（在專案根目錄執行）。

## 步驟（遊戲響應很快：用 `seq` 一次送多個動作，只在兩個檢查點截圖）
1. **檢查點 1（看現況）**：
   ```bash
   $G seq "info; click 763 760; wait 400; shot"
   ```
   - 不是 2880×1659 → `$G max` 後重來。
   - 沒看到「切換角色」面板（原本有別的面板開著）→ 可能是使用者在操作，`$G end` 後先問。
   - 已經是「隊伍」→ `$G seq "key {ESC}; end"` 後回報，不要重組（要重組先用 `/psa-disband-team`）。
   - 有角色不是「線上 / 正常」→ `$G end` 後回報使用者（可能要先「全部登錄」716,578，要先問）。
   - 全部「線上」「單人」→ 繼續。
2. **一次跑完組隊並驗證**（快速組隊 → 選第一個當隊長 → 下排 4 人每個都點 → 組隊 → 開切換面板截圖後關掉）：
   ```bash
   $G seq "click 520 578; wait 500; click 549 320; wait 400; click 549 520; wait 150; click 682 520; wait 150; click 815 520; wait 150; click 948 520; wait 300; click 720 665; wait 1500; click 763 760; wait 400; shot; key {ESC}"
   ```
3. **檢查點 2**：Read `tools/.cache/shot.png` → 切換角色面板：DKB0 標紅字「**隊長**」，其餘 4 人都標「**隊員**」（取代原本的「單人」）= 成功。
   - 不要靠聊天日誌或左側組隊分頁：日誌常被抽獎廣播洗掉；左側列表只顯示 4 列，看不到第 5 人。
   - 失敗時 Read `tools/.cache/q5.png`（按組隊前的提示視窗）：看隊長 / 4 個「隊員」標籤是否都有，找出漏掉哪步。

實測：檢查點 1 約 1.2 秒，步驟 2 約 5.3 秒。
## 完成後
- **跑 `$G end`** 把前景與游標還給使用者（中途停下來回報時也要先跑）。
- **隊長會變成「當前」操作的角色**；之後移動、對話都由隊長操作。
- 回報使用者：隊長是誰、4 個隊員都入隊了（附切換面板的狀態）。

## 失敗對照
| 現象 | 原因 / 處理 |
|---|---|
| 按組隊後沒任何提示，全員還是「單人」 | 隊員沒點到（看 q5.png）。從檢查點 1 重來；若是動畫沒跑完，把 wait 加大 |
| 訊息 33231「當前地圖不支持一鍵組隊或狀態、條件不滿足」 | 地圖禁止或有人狀態異常（戰鬥中、離線）。回報使用者，不要自己傳送換地圖 |
| 上排看不到某角色 | 隊長列可左右拖曳：`$G drag 940 330 600 330` |
| 出現沒見過的視窗 / 要選答案 | 依 psa-game-ui：當成驗證，立刻停手通知使用者 |
