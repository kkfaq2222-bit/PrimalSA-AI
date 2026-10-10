// stat.ps1 印出的一行 JSON
export type Stat = {
  ok: boolean
  error?: string
  level?: string
  hp?: number | null
  hpPct?: number | null
  mpPct?: number | null
  mp?: number | null
  petLevel?: string
  petHp?: number | null
  map?: string
  pos?: string
  // watch 的 state.hud 才有（stat.ps1 本身沒有）：人物名 / 寵物名（'?' = 不確定；結尾 ? = 舊值）
  name?: string
  petName?: string
}

// errlog.jsonl 一筆
export type ErrEntry = { id: number; ts: number; error: string; fix: string | null; source: string | null }

// pane 頂端狀態行：主行 + 提示行（tone：red 警示 / yellow 提醒 / gray 資訊）
export type WatchTone = 'red' | 'yellow' | 'gray'
export type WatchLine = { main: string; hints: { text: string; tone: WatchTone }[] }

declare module 'claude-code' {
  interface PluginState {
    'psa-hud': {
      // 最近一次讀取結果；null = 還沒讀過
      stat: Stat | null
      // 錯誤 / 改進紀錄（errlog.jsonl）最新 100 筆，最新在前
      errs: ErrEntry[]
      // 最近一次讀取的時間（毫秒）
      at: number
      // watch 活著時的等級 / HP 行（state.hud 組成）；null = watch 不在，改用 stat
      hud: string | null
      // 即時狀態行（讀 tools/.cache/state.json 組成；顯示文字變了才更新）
      line: WatchLine
    }
  }
}
