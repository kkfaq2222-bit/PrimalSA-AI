import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ErrEntry, Stat } from '../types'

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
const PANE = 'psa-hud'

export const statArgv = () => ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', statPs1]

const stat = atom({ plugin: 'psa-hud', key: 'stat' } as const, null)
const acts = atom({ plugin: 'psa-hud', key: 'errs' } as const, [] as ErrEntry[])
const at = atom({ plugin: 'psa-hud', key: 'at' } as const, 0)

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

async function refresh($: EngineInterface): Promise<Stat | undefined> {
  if (busy) return undefined
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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 設定在使用者層級（每個專案都會載入），只在精靈王石器專案裡啟動
    if (!e.cwd.includes('PrimalSA-AI') || !e.isInteractive) return next(e)
    statPs1 = statPathFromCwd(e.cwd) ?? statPs1
    logFile = logPathFromCwd(e.cwd) ?? logFile
    await $.command.register({ name: 'psa-hud', description: '打開精靈王石器資訊 pane 並立即更新' })
    // 舊版（0.1）放在狀態列，改用 pane 後清掉
    $.ui.status(undefined)
    void $.ui.open({ id: PANE, title: '精靈王石器' })
    void refresh($)
    $.clock.every(PERIOD_MS, () => void refresh($))
    void refreshLog($)
    $.clock.every(LOG_PERIOD_MS, () => void refreshLog($))
    return next(e)
  })

  on('command.run', { command: 'psa-hud' }, async $ => {
    await $.ui.open({ id: PANE, title: '精靈王石器' })
    const s = await refresh($)
    return { text: s ? format(s) : '上一次讀取還在進行中' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const lines = await read($, acts)

    return (
      <Box flexDirection="column">
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
