import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ErrEntry, Stat, WatchLine, WatchTone } from '../types'

// 讀 HUD 的腳本：背景截圖 + Windows OCR，印一行 JSON（見 tools/gui/stat.ps1）
// 遊戲畫面由獨立的鏡像視窗顯示（tools/gui/mirror.sh），pane 只放文字
// 路徑由 session cwd 推算（WSL /mnt/c/games/PrimalSA-AI、Windows C:\\games\\PrimalSA-AI、Git Bash /c/games/... 都通），
// 一律換成 Windows 路徑給 powershell.exe；還沒收到 session.start 時用預設值
const PROJECT = 'PrimalSA-AI'
let statPs1 = `C:\\games\\${PROJECT}\\tools\\gui\\stat.ps1`

export function statPathFromCwd(cwd: string): string | undefined {
  const i = cwd.indexOf(PROJECT)
  if (i < 0) return undefined
  let root = cwd.slice(0, i + PROJECT.length)
  const m = /^\/(?:mnt\/|cygdrive\/)?([a-zA-Z])\//.exec(root)
  if (m && !/^[a-zA-Z]:/.test(root)) root = `${m[1]!.toUpperCase()}:/${root.slice(m[0].length)}`
  return `${root}/tools/gui/stat.ps1`.replace(/\//g, '\\')
}
const PERIOD_MS = 15000
// 錯誤 / 改進紀錄（tools/gui/errlog.py 寫入，只留最新 100 筆，一行一筆 JSON）；讀檔很便宜，2 秒一次
// 操作 log（actions.log）照樣由 actlog.py / gui.ps1 在背景寫，只是 pane 不顯示
const LOG_PERIOD_MS = 2000
const STATE_PERIOD_MS = 1000     // 讀 state.json（watch.py 寫的即時狀態）
const LOG_MAX = 100
let logFile = `C:/games/${PROJECT}/tools/.cache/errlog.jsonl`

// 專案根目錄（保留原本的斜線形式，$.fs 接受 /mnt/c/...、C:\... 與 C:/...）
export function logPathFromCwd(cwd: string): string | undefined {
  const i = cwd.indexOf(PROJECT)
  return i < 0 ? undefined : `${cwd.slice(0, i + PROJECT.length)}/tools/.cache/errlog.jsonl`
}

function stamp(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// errlog.jsonl → 最新在上、最多 LOG_MAX 筆；壞行略過
export function errEntries(text: string): ErrEntry[] {
  const out: ErrEntry[] = []
  for (const l of text.split(/\r?\n/)) {
    if (!l.trim()) continue
    try {
      const r = JSON.parse(l) as ErrEntry
      if (typeof r.error === 'string') out.push({ id: r.id, ts: r.ts, error: r.error, fix: r.fix ?? null, source: r.source ?? null })
    } catch {
      // 壞行略過
    }
  }
  return out.slice(-LOG_MAX).reverse()
}

// 一筆紀錄的顯示文字：[錯誤] 與 [改進]（沒改進 = 待改進）
export function errLine(e: ErrEntry): { head: string; fix: string; pending: boolean } {
  return { head: `${stamp(e.ts)} #${e.id}${e.source ? ` [${e.source}]` : ''} ${e.error}`, fix: e.fix ? `→ 改進：${e.fix}` : '→ 待改進', pending: !e.fix }
}

// ───────────────────────── 即時狀態監看（watch.py）：路徑 / 解析 / 顯示 / 監督 ─────────────────────────
// 計畫：notes/plan-watch-state.md §1.3～1.5、§7 第 4 階段。只管「自己 spawn 的」子程序；其他 session / 平台只讀 state.json

// 專案根目錄與其下檔案（保留 cwd 的斜線形式，$.fs 接受 /mnt/c/...、C:\... 與 C:/...）
export function rootFromCwd(cwd: string): string | undefined {
  const i = cwd.indexOf(PROJECT)
  return i < 0 ? undefined : cwd.slice(0, i + PROJECT.length)
}
export const stateFileFromCwd = (cwd: string) => { const r = rootFromCwd(cwd); return r ? `${r}/tools/.cache/state.json` : undefined }
export const hudCfgFromCwd = (cwd: string) => { const r = rootFromCwd(cwd); return r ? `${r}/tools/.cache/psa-hud.json` : undefined }

// watch.py 的絕對路徑：直譯器是 Windows 的（C:\...\python.exe、.exe）→ Windows 路徑；Linux 直譯器 → /mnt/<磁碟>/ 原生路徑。
// 不給直譯器（uv run 退路）時由 cwd 的形式推斷：/mnt/c/... 當 WSL（Linux 路徑），其他當 Windows
export function watchPathFromCwd(cwd: string, pythonPath?: string): string | undefined {
  const root = rootFromCwd(cwd)
  if (!root) return undefined
  const m = /^(?:\/(?:mnt\/|cygdrive\/)?([a-zA-Z])\/|([a-zA-Z]):[\\/])(.*)$/.exec(root)
  if (!m) return `${root}/tools/gui/watch.py`           // 純 Linux 路徑（不是 /mnt/c 之類）
  const drive = (m[1] ?? m[2])!
  const rest = m[3]!.replace(/\\/g, '/')
  const isWin = pythonPath !== undefined ? /^[a-zA-Z]:|\.exe$/i.test(pythonPath) : !cwd.startsWith('/mnt/')
  return isWin
    ? `${drive.toUpperCase()}:\\${rest.replace(/\//g, '\\')}\\tools\\gui\\watch.py`
    : `/mnt/${drive.toLowerCase()}/${rest}/tools/gui/watch.py`
}

// state.hud（第 3 階段）：欄位級 {v, ts}；ok = 最近一次讀到資料；stale = 被蓋住 / 太久沒更新（欄位值保留舊的）
type WF<T> = { v?: T; ts?: number }
export type WHud = {
  ok?: boolean; stale?: boolean; age_s?: number | null
  level?: WF<string>; hp?: WF<number>; hpPct?: WF<number>; mp?: WF<number>; mpPct?: WF<number>
  pet?: { level?: WF<string>; hp?: WF<number> }
  map?: WF<string> & { id?: number }
  pos?: WF<number[]>
}

// state.json（只認 v 主版本 1；不認得的鍵一律忽略）
type WState = {
  v?: number; seq?: number; phase?: string
  watcher?: { token?: string; running?: boolean; interval?: number }
  screen?: { label?: string; age_s?: number; state?: string; full?: boolean; annot?: string[] }
  hud?: WHud
  flags?: { verify_suspect?: boolean; netwatch_halt?: boolean }
  alerts?: { msg?: string; line?: string }[]
}
export function parseState(text: string | undefined): { state: WState | null; badVersion: number | null } {
  if (!text) return { state: null, badVersion: null }
  try {
    const d = JSON.parse(text) as WState
    if (!d || typeof d !== 'object') return { state: null, badVersion: null }
    if (Math.floor(Number(d.v)) !== 1) return { state: null, badVersion: typeof d.v === 'number' ? d.v : -1 }
    return { state: d, badVersion: null }
  } catch {
    return { state: null, badVersion: null }   // 寫到一半 / 壞檔：這輪當沒讀到（下一秒再讀）
  }
}

// 退避：2 → 5 → 15 → 30 → 60 s（上限 60 s），±20% jitter
const BACKOFF_S = [2, 5, 15, 30, 60]
export function backoffMs(idx: number, rnd: number): number {
  return Math.round(BACKOFF_S[Math.min(idx, BACKOFF_S.length - 1)]! * 1000 * (0.8 + 0.4 * rnd))
}
export const SHORT_RUN_MS = 30000     // 跑不到 30 s 算「立刻死」
export const GOOD_RUN_MS = 60000      // 跑滿 60 s 歸零
export const MAX_SHORT_RUNS = 5       // 連續 5 次跑不到 30 s 就停止重開
export const GRACE3_MS = 3000         // 啟動後第一次拿到退出碼 3：可能是熱重載時舊子程序還在收尾，等 3 s 重試一次

export type ExitIn = { code: number | null; ranMs: number; progressed: boolean; consec: number; idx: number; grace: boolean }
export type ExitOut = { action: 'retry' | 'ro3' | 'ro6' | 'stopped' | 'failed'; delayMs: number; consec: number; idx: number; grace: boolean }
// 子程序結束後怎麼辦（純函式）
export function decideExit(i: ExitIn, rnd: number): ExitOut {
  const keep = { consec: i.consec, idx: i.idx, grace: i.grace }
  if (i.code === 5) return { action: 'stopped', delayMs: 0, ...keep }
  if (i.code === 6) return { action: 'ro6', delayMs: 0, ...keep }
  if (i.code === 3) {
    if (i.grace) return { action: 'retry', delayMs: GRACE3_MS, ...keep, grace: false }
    return { action: 'ro3', delayMs: 0, ...keep }
  }
  let { consec, idx } = i
  if (i.ranMs >= GOOD_RUN_MS || i.progressed) { consec = 0; idx = 0 }
  else if (i.ranMs < SHORT_RUN_MS) consec++
  else consec = 0
  if (consec >= MAX_SHORT_RUNS) return { action: 'failed', delayMs: 0, consec, idx, grace: false }
  return { action: 'retry', delayMs: backoffMs(idx, rnd), consec, idx: idx + 1, grace: false }
}

// 卡住門檻：phase=starting 或還沒看到任何進展（剛 spawn）45 s；其他 max(10 s, 3×interval)
export function stallThresholdMs(phase: string | null | undefined, interval: number | null | undefined, progressed: boolean): number {
  if (phase === 'starting' || !progressed) return 45000
  return Math.max(10000, 3 * (interval && interval > 0 ? interval : 0.5) * 1000)
}

type Chunk = { stream: string; text: string }
type Streamer = {
  next: () => Promise<{ done?: boolean; value?: unknown }>
  return?: (v?: unknown) => Promise<unknown>
}
export type SupDeps = {
  spawn: () => Streamer | Promise<Streamer>      // 組 argv + $.process.spawn
  now: () => Promise<number>                     // 本地毫秒
  sleep: (ms: number) => Promise<void>
  rnd: () => number
  stopCli: () => Promise<void>                   // watch.py --stop（寫 psa-hud.json watch=false + watch.stop，等 watch 結束）
  saveCfg: (on: boolean) => Promise<void>        // 寫 psa-hud.json（唯一依據）
}
export type SupStatus = 'idle' | 'running' | 'waiting' | 'ro3' | 'ro6' | 'failed' | 'stopped' | 'off'

// 監督自己 spawn 的 watch 子程序（不依賴 $：測試用假 deps）
export class Supervisor {
  status: SupStatus = 'idle'
  spawns = 0
  lastCode: number | null = null
  stalls = 0
  tail = ''                        // 子程序 stdout / stderr 最後約 20 行
  seenAt = 0                       // (token, seq) 最近一次變化的本地時間（顯示年齡、判斷沒更新用）
  private key: string | null = null
  private epoch = 0
  private spawnAt = 0
  private progressed = false
  private abortRun: (() => void) | null = null
  cfgOn = true
  constructor(private d: SupDeps) {}

  start(): void {
    this.epoch++
    this.cfgOn = true
    this.status = 'idle'
    void this.loop(this.epoch)
  }

  // 每秒呼叫：key = `${token}:${seq}` 或 null
  async observe(key: string | null, phase: string | null, interval: number | null): Promise<void> {
    const now = await this.d.now()
    if (key !== this.key) {
      this.key = key
      this.seenAt = now
      if (key && this.status === 'running') this.progressed = true
    }
    if (this.status === 'running' && this.abortRun) {
      const last = Math.max(this.seenAt, this.spawnAt)
      if (now - last > stallThresholdMs(phase, interval, this.progressed)) {
        this.stalls++
        this.status = 'waiting'          // 先換狀態，避免同一次卡住重複觸發
        this.abortRun()
      }
    }
  }

  private pushTail(text: string): void {
    this.tail = (this.tail + text).split('\n').slice(-20).join('\n').slice(-4000)
  }

  private async sleepSliced(ms: number, epoch: number): Promise<void> {
    for (let left = ms; left > 0 && epoch === this.epoch; left -= 500) await this.d.sleep(Math.min(500, left))
  }

  private async loop(epoch: number): Promise<void> {
    let consec = 0, idx = 0, grace = true
    while (epoch === this.epoch) {
      this.status = 'running'
      const t0 = await this.d.now()
      this.spawnAt = t0
      this.progressed = false
      let code: number | null = -1
      let stream: Streamer | undefined
      try {
        stream = await this.d.spawn()
        this.spawns++
      } catch (err) {
        this.pushTail(`spawn 失敗：${String(err).slice(0, 120)}\n`)
      }
      if (stream) {
        const abort = new Promise<'abort'>(res => { this.abortRun = () => res('abort') })
        try {
          for (;;) {
            // 持續讀 stdout / stderr（避免 1,048,576 字元上限卡住子程序）；被叫停就 return() 結束串流（殺子程序）
            const r = await Promise.race([stream.next(), abort])
            if (r === 'abort') {
              code = -2
              if (stream.return) void stream.return().catch(() => undefined)
              break
            }
            if (r.done) {
              const v = r.value as { code?: number | null } | undefined
              code = v?.code ?? -1
              break
            }
            this.pushTail((r.value as Chunk).text)
          }
        } catch (err) {
          this.pushTail(`串流錯誤：${String(err).slice(0, 120)}\n`)
        }
        this.abortRun = null
      }
      if (epoch !== this.epoch) return             // off / on / 重載：不判斷、不重開
      this.lastCode = code
      const ranMs = (await this.d.now()) - t0
      const o = decideExit({ code, ranMs, progressed: this.progressed, consec, idx, grace }, this.d.rnd())
      ;({ consec, idx, grace } = o)
      if (o.action === 'retry') {
        this.status = 'waiting'
        await this.sleepSliced(o.delayMs, epoch)
        continue
      }
      this.status = o.action
      return
    }
  }

  // /psa-hud watch off：寫設定 → 先 --stop（乾淨退出碼 5）→ 作廢目前迴圈並殺殘留
  async setOff(): Promise<void> {
    this.cfgOn = false
    this.epoch++
    await this.d.saveCfg(false).catch(() => undefined)
    await this.d.stopCli().catch(() => undefined)
    this.abortRun?.()
    this.status = 'off'
  }

  // /psa-hud watch on：寫設定、計數歸零、立即啟動（watch.stop 由 stopCli 對面清；on 時 watch.py 自己忽略早於啟動的 stop 檔）
  async setOn(): Promise<void> {
    await this.d.saveCfg(true).catch(() => undefined)
    this.abortRun?.()
    this.stalls = 0
    this.start()
  }
}

// ── 狀態行顯示 ──
export type ViewIn = { state: WState | null; badVersion: number | null; status: SupStatus; lastCode: number | null; now: number; seenAt: number; hasFile: boolean }
// 狀態行最多幾秒沒變就提示「監看沒有更新」（沒有自己的子程序在管時）
export const STALE_HINT_MS = 10000
export function viewModel(i: ViewIn): WatchLine {
  const hints: { text: string; tone: WatchTone }[] = []
  let main: string
  if (i.badVersion != null) {
    main = '（state.json 版本不符）'
    hints.push({ text: `state.json 版本 v${i.badVersion}，這個 HUD 只認 v1`, tone: 'red' })
  } else if (!i.state) {
    main = i.hasFile ? '（state.json 讀取中）' : '（沒有狀態）'
  } else {
    main = i.state.screen?.label || '（無畫面資料）'
    // 「N 秒前」：state 內的 age_s + 本地第一次看到這個 (token, seq) 之後的經過時間；> 3 s 才顯示（不比對跨平台時鐘）
    const age = (i.state.screen?.age_s ?? 0) + Math.max(0, i.now - i.seenAt) / 1000
    if (age > 3) main += ` ｜ ${Math.floor(age)} 秒前`
  }
  const own = i.status === 'running' || i.status === 'waiting' || i.status === 'idle'
  switch (i.status) {
    case 'failed': hints.push({ text: `監看啟動失敗（最後退出碼 ${i.lastCode ?? '?'}）；/psa-hud watch on 重試`, tone: 'red' }); break
    case 'ro3': hints.push({ text: '已有 watch 在跑（不是這個 HUD 啟動的），只讀', tone: 'gray' }); break
    case 'ro6': hints.push({ text: '另一平台的 watch 正在跑，只讀（它結束後要 /psa-hud watch on）', tone: 'gray' }); break
    case 'off': hints.push({ text: '監看已關閉（/psa-hud watch on 開啟）', tone: 'gray' }); break
    case 'stopped': hints.push({ text: '監看已被要求停止（/psa-hud watch on 重開）', tone: 'gray' }); break
    case 'waiting': hints.push({ text: `監看重開中（上次退出碼 ${i.lastCode ?? '?'}）`, tone: 'yellow' }); break
    case 'idle': case 'running': if (!i.state) hints.push({ text: '監看啟動中…', tone: 'yellow' }); break
  }
  // 不是自己管的 watch（只讀 / 關閉 / 停止 / 失敗）：state 久沒更新 = 監看未執行
  if (!own && i.state && i.now - i.seenAt > STALE_HINT_MS) hints.push({ text: '監看未執行（state.json 沒有更新）', tone: 'red' })
  if (!own && !i.state && i.badVersion == null && (i.status === 'off' || i.status === 'failed' || i.status === 'stopped')) hints.push({ text: '監看未執行', tone: 'red' })
  // 黃字：畫面上有提示視窗（annotate 只標出，不代表是驗證視窗；idle + 提示視窗是最該看一眼的組合）
  if (i.state?.screen?.annot?.includes('notice_dialog')) hints.push({ text: '畫面上有提示視窗，請看一眼', tone: 'yellow' })
  if (i.state?.flags?.verify_suspect) hints.push({ text: '疑似答題 / 驗證視窗，請人工處理', tone: 'red' })
  if (i.state?.flags?.netwatch_halt) hints.push({ text: '斷線監看已暫停（netwatch.halt）', tone: 'red' })
  for (const a of (i.state?.alerts ?? []).slice(0, 2)) if (a.msg || a.line) hints.push({ text: String(a.msg || a.line).slice(0, 120), tone: 'red' })
  return { main, hints }
}

const PANE = 'psa-hud'

export const statArgv = () => ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', statPs1]

const stat = atom({ plugin: 'psa-hud', key: 'stat' } as const, null)
const acts = atom({ plugin: 'psa-hud', key: 'errs' } as const, [] as ErrEntry[])
const at = atom({ plugin: 'psa-hud', key: 'at' } as const, 0)
const hudAtom = atom({ plugin: 'psa-hud', key: 'hud' } as const, null as string | null)
const line = atom({ plugin: 'psa-hud', key: 'line' } as const, { main: '（沒有狀態）', hints: [] } as WatchLine)

// 數值排成一行文字
export function format(s: Stat): string {
  if (!s.ok) return `PSA: ${s.error ?? '讀取失敗'}`
  const v = (n: number | null | undefined) => (n == null ? '?' : String(n))
  // OCR 讀不到數字時改顯示血條比例（hpPct / mpPct），都沒有才是 ?
  const num = (n: number | null | undefined, pct: number | null | undefined) => (n != null ? String(n) : pct != null ? `${pct}%` : '?')
  if (!s.level && s.hp == null && s.mp == null && s.hpPct == null) return 'PSA: 讀不到 HUD（對話 / 戰鬥 / 其他畫面蓋住，或視窗被遮）'
  const parts = [`${s.level || '?'}  HP ${num(s.hp, s.hpPct)}  MP ${num(s.mp, s.mpPct)}`]
  if (s.petLevel || s.petHp != null) parts.push(`寵 ${s.petLevel || '?'} HP ${v(s.petHp)}`)
  if (s.map || s.pos) parts.push(`${s.map ?? ''} ${s.pos ?? ''}`.trim())
  return parts.join('  |  ')
}

// watch 活著 = 讀得到 state，且 (token, seq) 在 STALE_HINT_MS 內有變、watcher 沒說自己 stopping（另一 session / 平台的 watch 也算）
export function watchAlive(state: WState | null, now: number, seenAt: number): boolean {
  return !!state && state.watcher?.running !== false && now - seenAt <= STALE_HINT_MS
}

const COVER_TEXT: Record<string, string> = {
  battle: '戰鬥前', dialog: '對話前', reward: '領獎前', select: '選單前', panel: '面板前', unknown: '畫面被蓋住前',
  minimized: '遊戲最小化前', no_game: '遊戲未執行前', error: '讀取失敗前',
}

// state.hud → pane 第二行（和 format 同格式）；沒有任何數值 → null。stale 時加灰字（原因 · N 秒前）
export function hudText(state: WState | null, now: number, seenAt: number): string | null {
  const h = state?.hud
  if (!h) return null
  const v = <T,>(f?: WF<T>): T | undefined => f?.v
  const pos = v(h.pos)
  const s: Stat = {
    ok: true, level: v(h.level), hp: v(h.hp) ?? null, hpPct: v(h.hpPct) ?? null, mp: v(h.mp) ?? null, mpPct: v(h.mpPct) ?? null,
    petLevel: v(h.pet?.level), petHp: v(h.pet?.hp) ?? null, map: v(h.map),
    pos: pos && h.map?.id != null ? `${h.map.id}:${pos[0]},${pos[1]}` : pos ? `${pos[0]},${pos[1]}` : undefined,
  }
  if (!s.level && s.hp == null && s.mp == null && s.hpPct == null && !s.petLevel && !s.map && !s.pos) return null
  let t = format(s)
  if (h.stale) {
    const age = Math.round((h.age_s ?? 0) + Math.max(0, now - seenAt) / 1000)
    const why = COVER_TEXT[state?.screen?.state ?? ''] ?? '讀取中'
    t += `（${why} · ${age}s 前）`
  }
  return t
}

async function poll($: EngineInterface): Promise<Stat> {
  try {
    const { exitCode, stdout, stderr } = await $.process.run(statArgv(), { timeoutMs: 10000 })
    const line = stdout.trim().split('\n').pop()?.trim() ?? ''
    if (exitCode !== 0 || !line.startsWith('{')) return { ok: false, error: `讀取失敗 ${stderr.trim().slice(0, 80)}` }
    return JSON.parse(line) as Stat
  } catch (err) {
    return { ok: false, error: `讀取失敗 ${String(err).slice(0, 80)}` }
  }
}

// 上一次讀取還沒結束就不再開新的（約 1 秒，計時器 15 秒一次）
let busy = false

// watch 活著時（tickState 每秒更新）等級 / HP 改讀 state.hud，不再 spawn 一次性 stat.ps1；watch 不在才退回
let hudAlive = false

async function refresh($: EngineInterface): Promise<Stat | undefined> {
  if (busy || hudAlive) return undefined
  busy = true
  try {
    const s = await poll($)
    const now = await $.clock.now()
    await update($, stat, () => s)
    await update($, at, () => now)
    return s
  } finally {
    busy = false
  }
}

async function refreshLog($: EngineInterface): Promise<void> {
  let lines: ErrEntry[] = []
  try {
    lines = errEntries(await $.fs.read(logFile))
  } catch {
    // 還沒有 log 檔：顯示空的
  }
  const old = await read($, acts)
  if (JSON.stringify(old) === JSON.stringify(lines)) return   // 沒變就不重畫
  await update($, acts, () => lines)
}

function clock(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// ── 與引擎接起來 ──
let sup: Supervisor | undefined
let projCwd = ''
let argvPrefix: string[] | undefined     // [python] 或 ['uv','run','--no-project','python']
let watchScript = ''
let tickBusy = false

// 取得直譯器：uv python find；失敗退回 uv run（推測 uv 會轉發 SIGTERM，待驗）
async function watchArgv($: EngineInterface, extra: string[] = []): Promise<string[]> {
  if (!argvPrefix) {
    let py: string | undefined
    try {
      const r = await $.process.run(['uv', 'python', 'find'], { timeoutMs: 15000 })
      const l = r.stdout.trim().split(/\r?\n/).pop()?.trim()
      if (r.exitCode === 0 && l) py = l
    } catch {
      // 找不到 uv python：走退路
    }
    watchScript = watchPathFromCwd(projCwd, py) ?? ''
    argvPrefix = py ? [py] : ['uv', 'run', '--no-project', 'python']
  }
  return [...argvPrefix, watchScript, ...extra]
}

function makeSup($: EngineInterface): Supervisor {
  return new Supervisor({
    spawn: async () => $.process.spawn({
      argv: await watchArgv($),
      cwd: rootFromCwd(projCwd),
      env: { PSA_WATCH_OWNER: 'hud', PYTHONIOENCODING: 'utf-8' },
    }) as unknown as Streamer,
    now: () => $.clock.now(),
    sleep: ms => $.clock.sleep(ms),
    rnd: () => Math.random(),
    stopCli: async () => { await $.process.run(await watchArgv($, ['--stop']), { timeoutMs: 15000 }) },
    saveCfg: async on => {
      const f = hudCfgFromCwd(projCwd)
      if (!f) return
      let cfg: Record<string, unknown> = {}
      try {
        const d = JSON.parse(await $.fs.read(f)) as unknown
        if (d && typeof d === 'object') cfg = d as Record<string, unknown>
      } catch {
        // 沒有設定檔：新建
      }
      cfg.watch = on
      await $.fs.write(f, JSON.stringify(cfg))
    },
  })
}

// psa-hud.json 的 watch 欄位是 on / off 唯一依據；沒檔 / 壞檔 = on
async function cfgWatchOn($: EngineInterface): Promise<boolean> {
  const f = hudCfgFromCwd(projCwd)
  if (!f) return true
  try {
    const d = JSON.parse(await $.fs.read(f)) as { watch?: unknown }
    return d.watch !== false
  } catch {
    return true
  }
}

// 每秒：讀 state.json → 餵給監督（存活 / 卡住）→ 顯示文字變了才更新 atom
async function tickState($: EngineInterface): Promise<void> {
  if (tickBusy || !sup) return
  tickBusy = true
  try {
    let text: string | undefined
    let hasFile = true
    try {
      text = await $.fs.read(stateFileFromCwd(projCwd) ?? 'tools/.cache/state.json')
    } catch {
      hasFile = false
    }
    const { state, badVersion } = parseState(text)
    const key = state ? `${state.watcher?.token ?? '?'}:${state.seq ?? '?'}` : null
    await sup.observe(key, state?.phase ?? null, state?.watcher?.interval ?? null)
    const vm = viewModel({ state, badVersion, status: sup.status, lastCode: sup.lastCode, now: await $.clock.now(), seenAt: sup.seenAt, hasFile })
    const now = await $.clock.now()
    const alive = watchAlive(state, now, sup.seenAt)
    const wasAlive = hudAlive
    hudAlive = alive
    const ht = alive ? (hudText(state, now, sup.seenAt) ?? '（等級 / HP 讀取中…）') : null
    if ((await read($, hudAtom)) !== ht) await update($, hudAtom, () => ht)
    if (wasAlive && !alive) void refresh($)       // watch 剛死：馬上用一次性 stat 補上，不等 15 s
    const old = await read($, line)
    if (JSON.stringify(old) !== JSON.stringify(vm)) await update($, line, () => vm)
  } finally {
    tickBusy = false
  }
}

const STATUS_TEXT: Record<SupStatus, string> = {
  idle: '準備啟動', running: '執行中', waiting: '等待重開', ro3: '已有 watch 在跑（只讀）', ro6: '另一平台的 watch 在跑（只讀）',
  failed: '啟動失敗', stopped: '已被要求停止', off: '已關閉',
}
const supSummary = (s: Supervisor) => `監看：${STATUS_TEXT[s.status]}｜spawn ${s.spawns} 次｜卡住重開 ${s.stalls} 次｜最後退出碼 ${s.lastCode ?? '無'}`

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 設定在使用者層級（每個專案都會載入），只在精靈王石器專案裡啟動
    if (!e.cwd.includes('PrimalSA-AI') || !e.isInteractive) return next(e)
    statPs1 = statPathFromCwd(e.cwd) ?? statPs1
    logFile = logPathFromCwd(e.cwd) ?? logFile
    projCwd = e.cwd
    await $.command.register({ name: 'psa-hud', description: '打開精靈王石器資訊 pane 並立即更新；/psa-hud watch on|off 開關即時監看；/psa-hud ack 清掉驗證警報' })
    // 舊版（0.1）放在狀態列，改用 pane 後清掉
    $.ui.status(undefined)
    void $.ui.open({ id: PANE, title: '精靈王石器' })
    void refresh($)
    $.clock.every(PERIOD_MS, () => void refresh($))
    void refreshLog($)
    $.clock.every(LOG_PERIOD_MS, () => void refreshLog($))
    // 即時狀態監看：設定 off 就不啟動；否則 spawn 自己的 watch 並開始每秒讀 state.json
    sup = makeSup($)
    if (await cfgWatchOn($)) sup.start()
    else sup.status = 'off'
    void tickState($)
    $.clock.every(STATE_PERIOD_MS, () => void tickState($))
    return next(e)
  })

  on('command.run', { command: 'psa-hud' }, async ($, e) => {
    const arg = String((e as { args?: string }).args ?? '').trim().split(/\s+/)
    if (arg[0] === 'ack') {
      // 人工確認過 quest 轉述的驗證警報：叫 watch 清掉（unknown_long 靠畫面恢復自動清）
      if (!sup) return { text: '監看未啟用（只在精靈王石器專案的互動 session 裡啟動）' }
      try {
        const r = await $.process.run(await watchArgv($, ['--ack']), { timeoutMs: 15000 })
        return { text: r.exitCode === 0 ? '已送出 ack：watch 下一輪清掉 quest 轉述的驗證警報（畫面不認得的警報要等畫面恢復才會清）' : `ack 失敗（退出碼 ${r.exitCode}）` }
      } catch (err) {
        return { text: `ack 失敗：${String(err).slice(0, 80)}` }
      }
    }
    if (arg[0] === 'watch') {
      if (!sup) return { text: '監看未啟用（只在精靈王石器專案的互動 session 裡啟動）' }
      if (arg[1] === 'off') await sup.setOff()
      else if (arg[1] === 'on') await sup.setOn()
      else if (arg[1] !== undefined && arg[1] !== 'status') return { text: '用法：/psa-hud watch on|off|status' }
      await tickState($)
      return { text: `${supSummary(sup)}${sup.tail ? `\n最後輸出：${sup.tail.trim().split('\n').slice(-3).join(' / ')}` : ''}` }
    }
    await $.ui.open({ id: PANE, title: '精靈王石器' })
    const s = await refresh($)
    const ht = hudAlive ? await read($, hudAtom) : null
    return { text: (ht ?? (s ? format(s) : '上一次讀取還在進行中')) + (sup ? `\n${supSummary(sup)}` : '') }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const lines = await read($, acts)
    const wl = await read($, line)
    const st = await read($, stat)
    const ht = await read($, hudAtom)
    const color = (t: WatchTone) => (t === 'red' ? 'red' : t === 'yellow' ? 'yellow' : undefined)

    return (
      <Box flexDirection="column">
        <Text wrap="truncate-end" bold>{wl.main}</Text>
        {wl.hints.map(h => <Text wrap="truncate-end" color={color(h.tone)} dimColor={h.tone === 'gray'}>{h.text}</Text>)}
        <Text wrap="truncate-end" dimColor={!st && !ht}>{ht ?? (st ? format(st) : '（等級 / HP 讀取中…）')}</Text>
        <Text dimColor>{'─'.repeat(20)}</Text>
        <Text dimColor>{`錯誤 / 改進紀錄（新→舊，最多 ${LOG_MAX} 筆）`}</Text>
        {lines.length === 0
          ? <Text dimColor>（還沒有錯誤紀錄）</Text>
          : lines.map(en => {
              const r = errLine(en)
              return (
                <Box flexDirection="column">
                  <Text wrap="truncate-end">{r.head}</Text>
                  <Text wrap="truncate-end" color={r.pending ? 'yellow' : 'green'} bold={r.pending}>{`   ${r.fix}`}</Text>
                </Box>
              )
            })}
      </Box>
    )
  })
}
