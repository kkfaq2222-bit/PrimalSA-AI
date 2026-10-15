#!/usr/bin/env python3
"""漆黑洞窟（一轉）步 6「覲見精靈王」+ 轉生（1920×1017；終端機直接跑）。

轉生不可逆（角色回到 1 級），所以分階段、每個會動到對話選項的動作都要使用者放行：
  go    組隊（1 隊長 + 4 隊員，已是就不動）→ 外掛：不逃跑 + 自動戰鬥 → 點追蹤欄導航到精靈王 → 對話窗一出現就停手
        （不點任何選項；把對話文字 / 選項 OCR 與截圖存起來，對話窗保持開著）
  look  只讀：目前畫面狀態 + 對話文字 / 選項 OCR + 截圖（不點）
  step  對話窗開著時「只點第一個選項一次」→ 再 look（要連點就多跑幾次 step，每次都先看過畫面）
  after 轉生後只讀：追蹤欄、寵物欄第 1 格名字（找烏力斯坦用）

用法（專案根目錄）：
  tools\\gui\\run_rebirth.cmd kkfaq22222 go
  tools\\gui\\run_rebirth.cmd kkfaq22222 look
  tools\\gui\\run_rebirth.cmd kkfaq22222 step
退出碼：0 成功 / 3 隊伍 / 4 外掛 / 5 追蹤欄不是「覲見精靈王」/ 6 疑似驗證視窗或卡住 / 7 逾時 / 2 版面不對
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import q1920 as q  # noqa: E402

DIALOG_TEXT = (555, 160, 350, 95)    # 與 q1920.talk 同一組框
DIALOG_OPT = (565, 262, 175, 42)
CACHE = HERE.parent / '.cache'


def shot(tag: str) -> str:
    name = f'rebirth-{tag}-{time.strftime("%H%M%S")}.png'
    q.uk().gui('shot', name)
    return str(CACHE / name)


def read_dialog() -> tuple:
    txt = ''.join(q.uk().ocr(DIALOG_TEXT, '-Zooms', '2,3'))
    opt = ''.join(q.uk().ocr(DIALOG_OPT, '-Zooms', '2,3'))
    return txt, opt


def look(tag: str) -> None:
    s = q.state()
    p = shot(tag)
    q.log(f'畫面狀態：{s}；截圖：{p}')
    if s in ('DIALOG', 'REWARD'):
        txt, opt = read_dialog()
        q.log(f'對話文字：{txt}')
        q.log(f'第一個選項：{opt}')
    q.log(f'追蹤欄：{q.tracker_text()!r}')


def cmd_go() -> int:
    q.scroll_tracker()
    head = q.tracker_text()
    if '覲見' not in head and '精靈王' not in head:
        raise q.Halt(q.EXIT_NOQUEST, f'追蹤欄不是「覲見精靈王」（{head!r}）：停手，請看畫面')
    q.form_team()
    q.set_ass(flee=False, auto=True)
    q.note('轉生：隊伍 / 外掛就緒，點追蹤欄導航到精靈王（到點對話窗出現就停，不點選項）')
    s = q.navigate()
    q.log(f'已抵達（{s}）→ 對話窗保持開著，不點任何選項')
    look('arrive')
    q.note(f'轉生：已到精靈王，對話窗開著等使用者放行；追蹤欄 {q.tracker_text()!r}')
    return q.EXIT_OK


def cmd_step() -> int:
    s = q.state()
    if s != 'DIALOG':
        raise q.Halt(q.EXIT_HALT, f'現在不是 NPC 對話窗（{s}）：不點，請看畫面')
    # 對話窗開著時切換面板打不開，不能在這裡重驗隊伍；隊伍在 go 階段已驗證過（1 隊長 + 4 隊員），對話窗開著期間不會變
    txt, opt = read_dialog()
    if not any(k in opt for k in ('漆黑', '轉生', '確')):
        raise q.Halt(q.EXIT_HALT, f'第一個選項「{opt}」不是預期的選項：不點，請看畫面')
    q.log(f'即將點第一個選項「{opt}」；對話：{txt}')
    shot('before')
    q.click(q.OPT1, wait_ms=2500, note='rebirth 對話第一個選項（使用者放行）')
    q.note(f'轉生：點了第一個選項「{opt}」；對話「{txt[:30]}」')
    look('after')
    return q.EXIT_OK


def cmd_after() -> int:
    look('final')
    q.log('寵物欄第 1 格名稱請用寵物面板確認（烏力斯坦；只刪名稱確認的那隻）')
    return q.EXIT_OK


def cmd_auto() -> int:
    """對話窗開著時自動點選項直到轉生對話結束（使用者 2026-10-12 要求全自動）：
    每次只點第一個選項；選項是「再見 / 離開 / 取消」類就停手；最多 4 次；每次點前後都存截圖。"""
    for k in range(4):
        s = q.state()
        if s not in ('DIALOG', 'REWARD'):
            q.log(f'對話已結束（{s}）')
            return q.EXIT_OK
        txt, opt = read_dialog()
        if any(w in opt for w in ('再見', '離開', '取消')):
            raise q.Halt(q.EXIT_HALT, f'第一個選項「{opt}」是離開類：不點，請看畫面')
        q.log(f'自動第 {k + 1} 次：點第一個選項「{opt}」；對話：{txt}')
        shot(f'auto{k + 1}')
        q.click(q.OPT1, wait_ms=2800, note=f'rebirth auto 第一個選項（{opt}）')
        q.note(f'轉生 auto：第 {k + 1} 次點「{opt}」；對話「{txt[:30]}」')
    look('auto-end')
    return q.EXIT_OK


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('cmd', choices=['go', 'look', 'step', 'auto', 'after'])
    a = ap.parse_args(argv)
    q.CLIENT = a.client
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    try:
        q.preflight()
        if a.cmd == 'go':
            return cmd_go()
        if a.cmd == 'look':
            look('look')
            return q.EXIT_OK
        if a.cmd == 'step':
            return cmd_step()
        if a.cmd == 'auto':
            return cmd_auto()
        return cmd_after()
    except q.Halt as h:
        q.log(f'停手（退出碼 {h.code}）：{h.msg}')
        return h.code


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('rebirth1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
