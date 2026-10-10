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
}

// errlog.jsonl 一筆
export type ErrEntry = { id: number; ts: number; error: string; fix: string | null; source: string | null }

declare module 'claude-code' {
  interface PluginState {
    'psa-hud': {
      // 最近一次讀取結果；null = 還沒讀過
      stat: Stat | null
      // 錯誤 / 改進紀錄（errlog.jsonl）最新 100 筆，最新在前
      errs: ErrEntry[]
      // 最近一次讀取的時間（毫秒）
      at: number
    }
  }
}
