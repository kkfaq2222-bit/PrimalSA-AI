import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Stat } from '../types'

// 讀 HUD 的腳本：背景截圖 + Windows OCR，印一行 JSON（見 tools/gui/stat.ps1）
// 遊戲畫面由獨立的鏡像視窗顯示（tools/gui/mirror.sh），pane 只放文字
const STAT_PS1 = 'C:\\games\\PrimalSA-AI\\tools\\gui\\stat.ps1'
const PERIOD_MS = 15000
const PANE = 'psa-hud'

export const STAT_ARGV = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', STAT_PS1]

const stat = atom({ plugin: 'psa-hud', key: 'stat' } as const, null)
const at = atom({ plugin: 'psa-hud', key: 'at' } as const, 0)

// 數值排成一行文字
export function format(s: Stat): string {
  if (!s.ok) return `PSA: ${s.error ?? '讀取失敗'}`
  const v = (n: number | null | undefined) => (n == null ? '?' : String(n))
  const parts = [`${s.level || '?'}  HP ${v(s.hp)}  MP ${v(s.mp)}`]
  if (s.petLevel || s.petHp != null) parts.push(`寵 ${s.petLevel || '?'} HP ${v(s.petHp)}`)
  if (s.map || s.pos) parts.push(`${s.map ?? ''} ${s.pos ?? ''}`.trim())
  return parts.join('  |  ')
}

async function poll($: EngineInterface): Promise<Stat> {
  try {
    const { exitCode, stdout, stderr } = await $.process.run(STAT_ARGV, { timeoutMs: 10000 })
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

function clock(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 設定在使用者層級（每個專案都會載入），只在精靈王石器專案裡啟動
    if (!e.cwd.includes('PrimalSA-AI') || !e.isInteractive) return next(e)
    await $.command.register({ name: 'psa-hud', description: '打開精靈王石器資訊 pane 並立即更新' })
    // 舊版（0.1）放在狀態列，改用 pane 後清掉
    $.ui.status(undefined)
    void $.ui.open({ id: PANE, title: '精靈王石器' })
    void refresh($)
    $.clock.every(PERIOD_MS, () => void refresh($))
    return next(e)
  })

  on('command.run', { command: 'psa-hud' }, async $ => {
    await $.ui.open({ id: PANE, title: '精靈王石器' })
    const s = await refresh($)
    return { text: s ? format(s) : '上一次讀取還在進行中' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, stat)
    const t = await read($, at)

    return (
      <Box flexDirection="column">
        <Text bold>{s ? format(s) : '讀取中…'}</Text>
        <Text dimColor>{t ? `更新 ${clock(t)}（每 ${PERIOD_MS / 1000} 秒）` : ' '}</Text>
      </Box>
    )
  })
}
