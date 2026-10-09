import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Stat } from '../types'

// 讀 HUD 的腳本：背景截圖 + Windows OCR，印一行 JSON，並存一張縮小截圖（見 tools/gui/stat.ps1）
const STAT_PS1 = 'C:\\games\\PrimalSA-AI\\tools\\gui\\stat.ps1'
const SHOT_WIN = 'C:\\games\\PrimalSA-AI\\tools\\.cache\\hud-pane.png'
const BLOCKS_WIN = 'C:\\games\\PrimalSA-AI\\tools\\.cache\\hud-blocks.txt'
const BLOCKS_WSL = '/mnt/c/games/PrimalSA-AI/tools/.cache/hud-blocks.txt'
const PERIOD_MS = 15000
const PANE = 'psa-hud'
const SHOT_WSL = '/mnt/c/games/PrimalSA-AI/tools/.cache/hud-pane.png'
// 截圖寬高比（stat.ps1 縮成 960×553）；終端機一格約高是寬的 2 倍
const SHOT_RATIO = 553 / 960

// 色塊畫面的寬度（終端機格數）：跟著 pane 寬度，下一次讀取生效
let blocksWidth = 100
// 終端機能畫原圖（kitty 圖片協定：kitty / Ghostty）就用 Image，否則用色塊；session.start 時判斷
let canImage = false

function argv(): string[] {
  const a = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', STAT_PS1, '-Shot', SHOT_WIN]
  return canImage ? a : [...a, '-Blocks', BLOCKS_WIN, '-BlocksWidth', String(blocksWidth)]
}

// 一格「▀」：上半像素當前景色、下半像素當背景色
export type Run = { fg: string; bg: string; n: number }

// 每行 rrggbb 的像素 → 每列一串顏色相同的連續格（顏色量化到 16 階，相鄰同色合併，減少元素數）
export function toRuns(text: string): Run[][] {
  const px = text.split('\n').map(l => l.trim()).filter(l => l.length >= 6)
  const q = (hex: string) => {
    const c = (i: number) => (Math.min(255, (parseInt(hex.slice(i, i + 2), 16) & 0xf0) + 8)).toString(16).padStart(2, '0')
    return `#${c(0)}${c(2)}${c(4)}`
  }
  const rows: Run[][] = []
  for (let y = 0; y + 1 < px.length; y += 2) {
    const top = px[y]!, bottom = px[y + 1]!
    const runs: Run[] = []
    for (let x = 0; x + 6 <= Math.min(top.length, bottom.length); x += 6) {
      const fg = q(top.slice(x, x + 6)), bg = q(bottom.slice(x, x + 6))
      const last = runs[runs.length - 1]
      if (last && last.fg === fg && last.bg === bg) last.n += 1
      else runs.push({ fg, bg, n: 1 })
    }
    rows.push(runs)
  }
  return rows
}

const stat = atom({ plugin: 'psa-hud', key: 'stat' } as const, null)
const gen = atom({ plugin: 'psa-hud', key: 'gen' } as const, 0)
const at = atom({ plugin: 'psa-hud', key: 'at' } as const, 0)
const blocks = atom({ plugin: 'psa-hud', key: 'blocks' } as const, [])

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
    const { exitCode, stdout, stderr } = await $.process.run(argv(), { timeoutMs: 10000 })
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
    if (s.ok) {
      if (!canImage) {
        const rows = toRuns(await $.fs.read(BLOCKS_WSL).catch(() => ''))
        await update($, blocks, () => rows)
      }
      await update($, gen, n => n + 1)
    }
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
    await $.command.register({ name: 'psa-hud', description: '打開精靈王石器畫面 pane 並立即更新' })
    // 舊版（0.1）放在狀態列，改用 pane 後清掉
    $.ui.status(undefined)
    const term = (await $.env.get('TERM')) ?? ''
    canImage = Boolean(await $.env.get('KITTY_WINDOW_ID')) || term.includes('kitty') || term.includes('ghostty') ||
      Boolean(await $.env.get('GHOSTTY_RESOURCES_DIR'))
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
    const ui = $.ui.resolve(e)
    const { Box, Text, Button } = ui
    const Image = canImage && 'Image' in ui ? ui.Image : undefined
    const s = await read($, stat)
    const t = await read($, at)
    const g = await read($, gen)
    const rows = Image ? [] : await read($, blocks)
    const columns = Math.max(40, Math.min(200, (e.viewport?.columns ?? 102) - 2))
    blocksWidth = columns

    return (
      <Box flexDirection="column">
        <Text bold>{s ? format(s) : '讀取中…'}</Text>
        <Box flexDirection="row">
          <Text dimColor>{t ? `更新 ${clock(t)}（每 ${PERIOD_MS / 1000} 秒） ` : ' '}</Text>
          <Button key="open" label="開原圖" onPress={() => void $.process.run(['explorer.exe', SHOT_WIN]).catch(() => undefined)} />
          <Button key="refresh" label="更新" onPress={() => void refresh($)} />
        </Box>
        {Image && g > 0 && (
          <Image
            key="shot"
            source={{ file: SHOT_WSL, format: 'png', generation: g }}
            columns={columns}
            rows={Math.max(6, Math.min(255, Math.round((columns * SHOT_RATIO) / 2)))}
            alt="（遊戲截圖）"
          />
        )}
        {rows.map((runs, y) => (
          <Text key={`r${y}`} wrap="truncate">
            {runs.map((r, i) => (
              <Text key={`c${i}`} color={r.fg} backgroundColor={r.bg}>{'▀'.repeat(r.n)}</Text>
            ))}
          </Text>
        ))}
      </Box>
    )
  })
}
