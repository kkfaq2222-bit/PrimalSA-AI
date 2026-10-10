import { expect, test } from 'claude-code/testing'

import { errEntries, errLine, format, logPathFromCwd, statPathFromCwd } from './register'

const OK = '{"ok":true,"level":"0轉38級","hp":208,"mp":45,"petLevel":"0轉38級","petHp":434,"map":"奇努伊的海底通路","pos":"31401:91,29"}'

test('format：一行顯示等級 / HP / MP / 寵物 / 地圖', () => {
  expect(format(JSON.parse(OK))).toBe('0轉38級  HP 208  MP 45  |  寵 0轉38級 HP 434  |  奇努伊的海底通路 31401:91,29')
  expect(format({ ok: false, error: '遊戲沒有在執行' })).toBe('PSA: 遊戲沒有在執行')
  expect(format({ ok: true, level: '0轉1級', hp: null, mp: 3 })).toBe('0轉1級  HP ?  MP 3')
})

test('/psa-hud 開 pane、只跑 stat.ps1（不截圖、不產生色塊）並回報數值', async ($, on) => {
  const seen: string[][] = []
  on('process.run', (_$, e) => {
    seen.push([...e.argv])
    return { value: { exitCode: 0, stdout: `${OK}\r\n`, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.now', () => ({ value: 0 }))
  const { text } = await $.command.run({ command: 'psa-hud', args: '' } as never)
  expect(text).toBe('0轉38級  HP 208  MP 45  |  寵 0轉38級 HP 434  |  奇努伊的海底通路 31401:91,29')
  expect(seen[0]?.[0]).toBe('powershell.exe')
  expect(seen[0]).not.toContain('-Shot')
  expect(seen[0]).not.toContain('-Blocks')
})

test('stat.ps1 失敗時回報讀取失敗', async ($, on) => {
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: 'boom', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.now', () => ({ value: 0 }))
  const { text } = await $.command.run({ command: 'psa-hud', args: '' } as never)
  expect(text).toBe('PSA: 讀取失敗 boom')
})

test('statPathFromCwd：WSL / Windows / Git Bash / 子目錄都換成 Windows 路徑', () => {
  const want = 'C:\\games\\PrimalSA-AI\\tools\\gui\\stat.ps1'
  expect(statPathFromCwd('/mnt/c/games/PrimalSA-AI')).toBe(want)
  expect(statPathFromCwd('C:\\games\\PrimalSA-AI')).toBe(want)
  expect(statPathFromCwd('C:/games/PrimalSA-AI/tools')).toBe(want)
  expect(statPathFromCwd('/c/games/PrimalSA-AI')).toBe(want)
  expect(statPathFromCwd('/home/x/other')).toBeUndefined()
})

test('errEntries：只取最新 100 筆、最新在前、略過空行與壞行', () => {
  const text = Array.from({ length: 120 }, (_, i) => JSON.stringify({ id: i + 1, ts: 0, error: `e${i + 1}`, fix: null, source: null })).join('\n') + '\n\nnot json\n'
  const l = errEntries(text)
  expect(l.length).toBe(100)
  expect(l[0]?.id).toBe(120)
  expect(l[99]?.id).toBe(21)
})

test('errLine：有改進顯示 → 改進，沒有標待改進', () => {
  const ts = new Date(2026, 9, 9, 23, 18).getTime()
  const a = errLine({ id: 9, ts, error: '空等', fix: '閒置結束', source: 'quest' })
  expect(a.head).toBe('10/09 23:18 #9 [quest] 空等')
  expect(a.fix).toBe('→ 改進：閒置結束')
  expect(a.pending).toBe(false)
  const b = errLine({ id: 10, ts, error: 'x', fix: null, source: null })
  expect(b.fix).toBe('→ 待改進')
  expect(b.pending).toBe(true)
})

test('format：OCR 讀不到數字時改用血條比例', () => {
  expect(format({ ok: true, level: '0轉5級', hp: null, mp: null, hpPct: 80, mpPct: 100 })).toBe('0轉5級  HP 80%  MP 100%')
  expect(format({ ok: true, hp: null, mp: null })).toContain('讀不到 HUD')
})

test('logPathFromCwd：WSL / Windows / Git Bash 都接到 tools/.cache/errlog.jsonl', () => {
  expect(logPathFromCwd('/mnt/c/games/PrimalSA-AI/tools')).toBe('/mnt/c/games/PrimalSA-AI/tools/.cache/errlog.jsonl')
  expect(logPathFromCwd('C:\\games\\PrimalSA-AI')).toBe('C:\\games\\PrimalSA-AI/tools/.cache/errlog.jsonl')
  expect(logPathFromCwd('/home/x')).toBeUndefined()
})
