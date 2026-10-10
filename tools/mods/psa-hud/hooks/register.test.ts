import { expect, test } from 'claude-code/testing'

import {
  Supervisor, backoffMs, decideExit, errEntries, errLine, format, logPathFromCwd, parseState, stallThresholdMs, statPathFromCwd,
  viewModel, watchPathFromCwd,
} from './register'
import type { SupDeps, ViewIn } from './register'

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


// ───────────── 即時狀態監看（第 4 階段）─────────────
const ST = (o: Record<string, unknown> = {}) => ({ v: 1, seq: 5, phase: 'running', watcher: { token: 'aa', running: true, interval: 0.5 }, screen: { label: '主畫面（未偵測到已知視窗）', age_s: 0.1 }, ...o })
const VIN = (o: Partial<ViewIn> = {}): ViewIn => ({ state: ST() as never, badVersion: null, status: 'running', lastCode: null, now: 1000, seenAt: 1000, hasFile: true, ...o })

test('狀態行：label 原樣顯示，N 秒前只在 > 3 s 才出現（age_s + 本地經過時間）', () => {
  expect(viewModel(VIN()).main).toBe('主畫面（未偵測到已知視窗）')
  expect(viewModel(VIN({ now: 1000 + 2800 })).main).toBe('主畫面（未偵測到已知視窗）')            // 0.1 + 2.8 < 3
  expect(viewModel(VIN({ now: 1000 + 3000 })).main).toBe('主畫面（未偵測到已知視窗） ｜ 3 秒前')     // 0.1 + 3.0 > 3
  expect(viewModel(VIN({ now: 1000 + 12000 })).main).toBe('主畫面（未偵測到已知視窗） ｜ 12 秒前')
  expect(viewModel(VIN({ state: ST({ screen: { label: '戰鬥中（完整・下指令）', age_s: 5 } }) as never })).main).toBe('戰鬥中（完整・下指令） ｜ 5 秒前')
  for (const l of [viewModel(VIN()).main, viewModel(VIN({ state: null })).main]) expect(l.includes('安全')).toBe(false)
})

test('狀態行提示：失敗 / 只讀 / 關閉 / 未執行 / 啟動中 / 版本', () => {
  const h = (o: Partial<ViewIn>) => viewModel(VIN(o)).hints
  expect(h({ status: 'failed', lastCode: 1 })[0]).toEqual({ text: '監看啟動失敗（最後退出碼 1）；/psa-hud watch on 重試', tone: 'red' })
  expect(h({ status: 'ro3' })[0]?.tone).toBe('gray')
  expect(h({ status: 'ro6' })[0]?.text).toContain('另一平台')
  expect(h({ status: 'off' })[0]?.text).toContain('已關閉')
  expect(h({ status: 'ro3', now: 1000 + 11000 }).map(x => x.text)).toContain('監看未執行（state.json 沒有更新）')
  expect(h({ status: 'running', now: 1000 + 20000 })).toEqual([])                       // 自己管的由卡住機制處理，不另外提示
  expect(h({ status: 'running', state: null, hasFile: false })[0]?.text).toBe('監看啟動中…')
  expect(h({ status: 'waiting', lastCode: 7 })[0]).toEqual({ text: '監看重開中（上次退出碼 7）', tone: 'yellow' })
  const bad = viewModel(VIN({ state: null, badVersion: 2 }))
  expect(bad.main).toContain('版本不符')
  expect(h({ state: ST({ flags: { verify_suspect: true, netwatch_halt: true } }) as never }).map(x => x.tone)).toEqual(['red', 'red'])
})

test('parseState：v 主版本 1 才收、忽略不認得的鍵、壞檔回 null', () => {
  expect(parseState(JSON.stringify({ v: 1, seq: 3, 未知: 1 })).state?.seq).toBe(3)
  expect(parseState(JSON.stringify({ v: 1.2, seq: 3 })).state?.seq).toBe(3)
  expect(parseState(JSON.stringify({ v: 2 }))).toEqual({ state: null, badVersion: 2 })
  expect(parseState('{"v":1,')).toEqual({ state: null, badVersion: null })
  expect(parseState(undefined).state).toBeNull()
})

test('watchPathFromCwd：WSL / Windows / Git Bash，依直譯器形式決定路徑', () => {
  expect(watchPathFromCwd('/mnt/c/games/PrimalSA-AI/tools', '/usr/bin/python3')).toBe('/mnt/c/games/PrimalSA-AI/tools/gui/watch.py')
  expect(watchPathFromCwd('/mnt/c/games/PrimalSA-AI', '/home/bal/.local/bin/python3.12')).toBe('/mnt/c/games/PrimalSA-AI/tools/gui/watch.py')
  expect(watchPathFromCwd('C:\\games\\PrimalSA-AI', 'C:\\Python312\\python.exe')).toBe('C:\\games\\PrimalSA-AI\\tools\\gui\\watch.py')
  expect(watchPathFromCwd('/c/games/PrimalSA-AI', 'C:\\x\\python.exe')).toBe('C:\\games\\PrimalSA-AI\\tools\\gui\\watch.py')
  expect(watchPathFromCwd('/mnt/c/games/PrimalSA-AI', 'C:\\x\\python.exe')).toBe('C:\\games\\PrimalSA-AI\\tools\\gui\\watch.py')   // WSL 呼叫 Windows 直譯器
  expect(watchPathFromCwd('C:\\games\\PrimalSA-AI', '/usr/bin/python3')).toBe('/mnt/c/games/PrimalSA-AI/tools/gui/watch.py')
  expect(watchPathFromCwd('/mnt/c/games/PrimalSA-AI')).toBe('/mnt/c/games/PrimalSA-AI/tools/gui/watch.py')                          // uv run 退路：由 cwd 推斷
  expect(watchPathFromCwd('C:/games/PrimalSA-AI/tools')).toBe('C:\\games\\PrimalSA-AI\\tools\\gui\\watch.py')
  expect(watchPathFromCwd('/home/x')).toBeUndefined()
})

test('decideExit：退出碼 3 / 5 / 6 不重試；3 在啟動寬限內等 3 s 重試一次', () => {
  const base = { ranMs: 1000, progressed: false, consec: 0, idx: 0, grace: false }
  expect(decideExit({ ...base, code: 5 }, 0.5).action).toBe('stopped')
  expect(decideExit({ ...base, code: 6 }, 0.5).action).toBe('ro6')
  expect(decideExit({ ...base, code: 3 }, 0.5).action).toBe('ro3')
  const g = decideExit({ ...base, code: 3, grace: true }, 0.5)
  expect([g.action, g.delayMs, g.grace]).toEqual(['retry', 3000, false])
  expect(decideExit({ ...base, code: 1 }, 0.5).action).toBe('retry')
})

test('退避序列 2/5/15/30/60 s 各 ±20%，超過上限固定 60 s', () => {
  expect([0, 1, 2, 3, 4, 9].map(i => backoffMs(i, 0.5))).toEqual([2000, 5000, 15000, 30000, 60000, 60000])
  expect(backoffMs(0, 0)).toBe(1600)
  expect(backoffMs(4, 1)).toBe(72000)
})

test('decideExit：連續 5 次跑不到 30 s 停；跑滿 60 s 或 seq 前進歸零；30~60 s 不算短也不歸零 idx', () => {
  let st = { consec: 0, idx: 0, grace: false }
  const acts: string[] = []
  for (let n = 0; n < 5; n++) {
    const o = decideExit({ code: 1, ranMs: 2000, progressed: false, ...st }, 0.5)
    acts.push(o.action); st = { consec: o.consec, idx: o.idx, grace: o.grace }
  }
  expect(acts).toEqual(['retry', 'retry', 'retry', 'retry', 'failed'])
  const a = decideExit({ code: 1, ranMs: 61000, progressed: false, consec: 4, idx: 4, grace: false }, 0.5)
  expect([a.action, a.consec, a.idx, a.delayMs]).toEqual(['retry', 0, 1, 2000])
  const b = decideExit({ code: 1, ranMs: 3000, progressed: true, consec: 4, idx: 4, grace: false }, 0.5)
  expect([b.action, b.consec, b.idx]).toEqual(['retry', 0, 1])
  const c = decideExit({ code: 1, ranMs: 40000, progressed: false, consec: 4, idx: 2, grace: false }, 0.5)
  expect([c.action, c.consec, c.idx]).toEqual(['retry', 0, 3])
})

test('卡住門檻：starting / 還沒進展 45 s；其他 max(10 s, 3×interval)', () => {
  expect(stallThresholdMs('starting', 0.5, true)).toBe(45000)
  expect(stallThresholdMs('running', 0.5, false)).toBe(45000)
  expect(stallThresholdMs('running', 0.5, true)).toBe(10000)
  expect(stallThresholdMs('running', 4, true)).toBe(12000)
  expect(stallThresholdMs(undefined, undefined, true)).toBe(10000)
})

// ── Supervisor：假子程序 / 假時鐘，驗 spawn 次數與狀態 ──
type Run = { chunks?: string[]; code?: number; runMs?: number; hang?: boolean }
function harness(runs: Run[]) {
  const t = { now: 100000 }
  const log = { spawns: 0, stops: 0, cfg: [] as boolean[], returned: 0, pulled: 0 }
  const deps: SupDeps = {
    spawn: () => {
      const r = runs[log.spawns] ?? runs[runs.length - 1]!
      log.spawns++
      const chunks = [...(r.chunks ?? [])]
      let release: (() => void) | undefined
      return {
        next: () => {
          log.pulled++
          const c = chunks.shift()
          if (c !== undefined) return Promise.resolve({ done: false, value: { stream: 'stdout', text: c } })
          if (r.hang) return new Promise<never>(res => { release = () => res(undefined as never) })
          t.now += r.runMs ?? 1000
          return Promise.resolve({ done: true, value: { code: r.code ?? 1, signal: null } })
        },
        return: () => { log.returned++; release?.(); return Promise.resolve(undefined) },
      }
    },
    now: () => Promise.resolve(t.now),
    sleep: ms => { t.now += ms; return Promise.resolve() },
    rnd: () => 0.5,
    stopCli: () => { log.stops++; return Promise.resolve() },
    saveCfg: on => { log.cfg.push(on); return Promise.resolve() },
  }
  return { t, log, sup: new Supervisor(deps) }
}
const settle = async () => { for (let i = 0; i < 3000; i++) await Promise.resolve() }

test('Supervisor：退出碼 3 / 6 / 5 不重試（3 在寬限內先重試一次）', async () => {
  const a = harness([{ code: 6 }]); a.sup.start(); await settle()
  expect([a.log.spawns, a.sup.status]).toEqual([1, 'ro6'])
  const b = harness([{ code: 5 }]); b.sup.start(); await settle()
  expect([b.log.spawns, b.sup.status]).toEqual([1, 'stopped'])
  const c = harness([{ code: 3 }, { code: 3 }]); c.sup.start(); await settle()
  expect([c.log.spawns, c.sup.status, c.sup.lastCode]).toEqual([2, 'ro3', 3])
  const d = harness([{ code: 3 }, { code: 0, chunks: ['x'], hang: true }]); d.sup.start(); await settle()
  expect([d.log.spawns, d.sup.status]).toEqual([2, 'running'])                // 舊子程序收尾完 → 第二次接手成功
})

test('Supervisor：連續 5 次跑不到 30 s → 共 spawn 5 次後停止（監看啟動失敗）', async () => {
  const h = harness([{ code: 1, runMs: 500 }]); h.sup.start(); await settle()
  expect([h.log.spawns, h.sup.status, h.sup.lastCode]).toEqual([5, 'failed', 1])
  expect(viewModel(VIN({ status: h.sup.status, lastCode: h.sup.lastCode })).hints[0]?.tone).toBe('red')
  await settle()
  expect(h.log.spawns).toBe(5)
})

test('Supervisor：卡住 → return() 結束舊串流 → 重開 1 次；門檻內不動', async () => {
  const h = harness([{ hang: true, chunks: ['hi'] }, { hang: true }])
  h.sup.start(); await settle()
  expect(h.log.spawns).toBe(1)
  await h.sup.observe('t:1', 'running', 0.5)                  // 第一次看到 key：進展
  h.t.now += 9000; await h.sup.observe('t:1', 'running', 0.5); await settle()
  expect([h.log.spawns, h.log.returned]).toEqual([1, 0])      // 9 s < 10 s
  h.t.now += 2000; await h.sup.observe('t:1', 'running', 0.5); await settle()
  expect(h.log.returned).toBe(1)
  expect(h.log.spawns).toBe(2)
  expect(h.sup.stalls).toBe(1)
})

test('Supervisor：phase=starting / 沒進展 45 s 內不重開', async () => {
  const h = harness([{ hang: true }])
  h.sup.start(); await settle()
  h.t.now += 40000; await h.sup.observe(null, 'starting', null); await settle()
  expect(h.log.spawns).toBe(1)
  h.t.now += 6000; await h.sup.observe(null, 'starting', null); await settle()
  expect(h.log.returned).toBe(1)
})

test('Supervisor：stdout 灌 2 MB 會被持續讀完（不卡子程序）', async () => {
  const big = Array.from({ length: 200 }, () => 'x'.repeat(10000) + '\n')
  const h = harness([{ chunks: big, code: 6 }]); h.sup.start(); await settle()
  expect(h.log.pulled).toBe(201)
  expect(h.sup.status).toBe('ro6')
  expect(h.sup.tail.length).toBeLessThan(5000)
})

test('Supervisor：off 呼叫 --stop 並寫設定、不再重開；on 重新啟動並歸零', async () => {
  const h = harness([{ hang: true }, { hang: true }])
  h.sup.start(); await settle()
  await h.sup.setOff(); await settle()
  expect([h.log.stops, h.log.cfg, h.sup.status, h.log.spawns]).toEqual([1, [false], 'off', 1])
  expect(h.log.returned).toBe(1)                                  // 殘留的串流被收掉
  await settle()
  expect(h.log.spawns).toBe(1)                                    // off 之後不重開
  await h.sup.setOn(); await settle()
  expect([h.log.cfg, h.log.spawns, h.sup.status]).toEqual([[false, true], 2, 'running'])
})
