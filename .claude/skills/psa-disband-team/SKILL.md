---
name: psa-disband-team
description: Use when the PrimalSA (精靈王石器) party needs to be broken up — the user asks to 解散隊伍 / 解散組隊 / 拆隊, or characters must go back to solo before regrouping or doing things separately.
---

# 解散隊伍

**REQUIRED BACKGROUND:** 先載入 psa-game-ui（工具、操作迴圈、紅區）。介面細節見 `../psa-game-ui/ui/team.md`。
**使用者的視窗是 1920×1017（優先）**：直接跑 `PSA_EXE_MATCH=<客戶端代號> uv run --no-project python tools/gui/q1920.py disband`（組隊面板 ✕ 812,42、解散 / 創建鈕 480,413），座標見 `../psa-game-ui/ui/layout-1920x1017.md`。下面的手動步驟座標只在客戶區 2880×1659（前人版面）有效。工具：`G="bash tools/gui/gui.sh"`（在專案根目錄執行）。

## 步驟（左側組隊分頁就能解散＋驗證，最快）
1. **檢查點 1**：`$G seq "info; click 260 236; wait 300; shot"` → 主畫面左側切到「組隊」分頁。
   - 不是 2880×1659 → `$G max` 後重來；左側面板不在（被收合或有面板擋住）→ `$G end` 後先問使用者。
   - 只有藍色「**創建隊伍**」→ 本來就沒隊伍，`$G end` 後回報。
   - 列出成員（隊長那列有紅色「隊」字，第一列 210,320）→ 繼續。
2. **解散**：`$G seq "click 210 320; wait 400; click 200 372; wait 400; shot"`
   - 點隊長那一列 → 彈出選單「**解散隊伍**」200,372 /「離開隊伍」200,443 → 點解散隊伍。**沒有確認框，立即解散**。
3. **檢查點 2**：左側組隊分頁變回只有「**創建隊伍**」= 成功（畫面中央會閃「隊伍已經解散」，日誌也有）。
   - 選單沒出現就點了 200,372 → 那裡是第 2 列成員，會開別人的選單；截圖確認後 `key {ESC}` 重來。
4. **收尾**：`$G end`，回報使用者。

實測：步驟 2 約 1.2 秒。

## 備用：從組隊面板解散
`$G seq "click 850 760; wait 400; click 720 670; wait 300; key {ESC}; wait 300; click 260 236; wait 300; shot"` → 一樣看左側是否變回「創建隊伍」。

## 注意
- 解散不可確認、按了就生效：只在使用者要求或任務明確需要時做。
- 要重組隊伍用 `/psa-quick-team`。
- 「離開隊伍」200,443：只讓自己（當前角色）退出，未實測。
- 未實測：當前角色是隊員時，選單是否只有「離開隊伍」。目前實測是以隊長解散。
