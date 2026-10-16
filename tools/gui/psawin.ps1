# 多視窗共用小工具（gui.ps1 dot-source 用）：點擊鎖（全域具名 Mutex）、本視窗帳號查詢。
#
# 點擊鎖：
#   Enter-PsaInputLock [-What 'click 1,2']   拿鎖；拿到回 $true（abandoned 接手也算拿到，會寫 actions.log）
#                                            等超過 PSA_INPUT_LOCK_MS（預設 5000 毫秒）回 $false，呼叫端不能點、要 exit 4
#   Exit-PsaInputLock                        放鎖（沒拿就什麼都不做；放在 finally）
#   只鎖「一下」：移游標 → 送訊息 → 還原游標 → 放鎖。截圖 / 讀像素 / OCR 不拿鎖。
#   Mutex 名稱 Local\PrimalSA-AI-Input（同一個登入工作階段的所有程序共用：多個終端機、常駐 serve.ps1、gui.sh 都一樣）。
#
# 帳號查詢（只給 gui.ps1 typeacct / acctinfo 用；帳號不經過 Python、不進命令列參數）：
#   Get-PsaAccount -Keys @('PrimalSA222', ...)  依序找第一個有設定的鍵，回帳號字串或 $null
#   設定檔：tools/gui/accounts.local.json（PSA_ACCOUNTS_FILE 可改路徑，測試用），格式 {"客戶端資料夾名或代號": "帳號"}
#   不進 git；帳號不寫進任何 log / 輸出 / 例外訊息（呼叫端只能印長度）。
#
# 退出碼（gui.ps1 用）：4 = 點擊鎖逾時，這一下沒點。

$script:PsaLockName = 'Local\PrimalSA-AI-Input'
$script:PsaLock = $null

function Get-PsaLockMs {
  if ($env:PSA_INPUT_LOCK_MS -match '^\d+$') { return [int]$env:PSA_INPUT_LOCK_MS }
  return 5000
}

function Enter-PsaInputLock([string]$What = '') {
  if ($script:PsaLock) { return $true }          # 同一次呼叫已持有（例：fg 包著 click）
  $m = New-Object System.Threading.Mutex($false, $script:PsaLockName)
  $got = $false; $abandoned = $false
  try { $got = $m.WaitOne((Get-PsaLockMs)) }
  catch {
    $e = $_.Exception
    while ($e -and -not ($e -is [System.Threading.AbandonedMutexException])) { $e = $e.InnerException }
    if ($e) { $got = $true; $abandoned = $true } else { throw }
  }
  if (-not $got) {
    $m.Dispose()
    if (Get-Command ActLog -ErrorAction SilentlyContinue) { ActLog "點擊鎖等超過 $(Get-PsaLockMs) ms，不點：$What" }
    return $false
  }
  $script:PsaLock = $m
  if ($abandoned -and (Get-Command ActLog -ErrorAction SilentlyContinue)) { ActLog "點擊鎖：前一個持有者沒放就結束（abandoned），已接手：$What" }
  $script:PsaLockAbandoned = $abandoned
  return $true
}

function Exit-PsaInputLock {
  $m = $script:PsaLock
  if (-not $m) { return }
  $script:PsaLock = $null
  try { $m.ReleaseMutex() } catch { }
  $m.Dispose()
}

function Get-PsaAccountsFile {
  if ($env:PSA_ACCOUNTS_FILE) { return $env:PSA_ACCOUNTS_FILE }
  return (Join-Path $PSScriptRoot 'accounts.local.json')
}

function Get-PsaAccount([string[]]$Keys) {
  $f = Get-PsaAccountsFile
  if (-not (Test-Path -LiteralPath $f)) { return $null }
  try { $j = Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }   # 不帶例外內容（可能含檔案片段）
  foreach ($k in $Keys) {
    if (-not $k) { continue }
    $p = $j.PSObject.Properties[$k]
    if ($p -and ($p.Value -is [string]) -and $p.Value.Trim()) { return $p.Value.Trim() }
  }
  return $null
}
