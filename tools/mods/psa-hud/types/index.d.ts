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
      // 截圖檔換新時遞增，讓終端機重新讀同一個路徑
      gen: number
      // 最近一次讀取的時間（毫秒）
      at: number
      // 色塊畫面：每列一串 { 上色, 下色, 格數 }
      blocks: { fg: string; bg: string; n: number }[][]
    }
  }
}
