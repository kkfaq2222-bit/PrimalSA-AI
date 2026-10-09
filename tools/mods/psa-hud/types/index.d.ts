// stat.ps1 印出的一行 JSON
export type Stat = {
  ok: boolean
  error?: string
  level?: string
  hp?: number | null
  mp?: number | null
  petLevel?: string
  petHp?: number | null
  map?: string
  pos?: string
}

declare module 'claude-code' {
  interface PluginState {
    'psa-hud': {
      // 最近一次讀取結果；null = 還沒讀過
      stat: Stat | null
      // 最近一次讀取的時間（毫秒）
      at: number
    }
  }
}
