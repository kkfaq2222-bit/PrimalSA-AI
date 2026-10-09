import { expect, test } from 'claude-code/testing'

import { format, toRuns } from './register'

const OK = '{"ok":true,"level":"0轉38級","hp":208,"mp":45,"petLevel":"0轉38級","petHp":434,"map":"奇努伊的海底通路","pos":"31401:91,29"}'

test('format：一行顯示等級 / HP / MP / 寵物 / 地圖', () => {
  expect(format(JSON.parse(OK))).toBe('0轉38級  HP 208  MP 45  |  寵 0轉38級 HP 434  |  奇努伊的海底通路 31401:91,29')
  expect(format({ ok: false, error: '遊戲沒有在執行' })).toBe('PSA: 遊戲沒有在執行')
  expect(format({ ok: true, level: '0轉1級', hp: null, mp: 3 })).toBe('0轉1級  HP ?  MP 3')
})

test('/psa-hud 開 pane、跑 stat.ps1（帶 -Blocks）並回報數值', async ($, on) => {
  const seen: string[][] = []
  on('process.run', (_$, e) => {
    seen.push([...e.argv])
    return { value: { exitCode: 0, stdout: `${OK}\r\n`, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.now', () => ({ value: 0 }))
  on('fs.read', () => ({ value: 'ffffff\n000000\n' }))
  on('env.get', () => ({ value: undefined }))
  const { text } = await $.command.run({ command: 'psa-hud', args: '' } as never)
  expect(text).toBe('0轉38級  HP 208  MP 45  |  寵 0轉38級 HP 434  |  奇努伊的海底通路 31401:91,29')
  expect(seen[0]?.[0]).toBe('powershell.exe')
  expect(seen[0]).toContain('-Blocks')
})

test('stat.ps1 失敗時回報讀取失敗', async ($, on) => {
  on('env.get', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: 'boom', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.now', () => ({ value: 0 }))
  const { text } = await $.command.run({ command: 'psa-hud', args: '' } as never)
  expect(text).toBe('PSA: 讀取失敗 boom')
})

test('toRuns：兩行像素合成一列，同色相鄰合併', () => {
  const rows = toRuns('ff0000ff0000000000\n0000ff0000ff000000\n')
  expect(rows).toEqual([[{ fg: '#f80808', bg: '#0808f8', n: 2 }, { fg: '#080808', bg: '#080808', n: 1 }]])
})
