# 點擊鎖 / 帳號查詢離線測試（不碰遊戲）：dot-source psawin.ps1，用測試專用的 Mutex 名稱，驗證
#   1) 沒人持有 → 拿得到、放得掉
#   2) 別的程序持有 → 等 PSA_INPUT_LOCK_MS 後回 false（呼叫端不點），並寫 log
#   3) 前一個持有者沒放就結束（abandoned）→ 接手成功並寫 log
#   4) Get-PsaAccount：依鍵順序找、沒設定 / 非字串 / 壞 JSON 回 null 且不丟例外
#   5) gui.ps1 靜態檢查：輸入類指令都拿鎖、帳號變數不進輸出 / log
# 用法：powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\gui\test_inputlock.ps1
# 退出碼：0 全部通過、1 有失敗
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'psawin.ps1')
$name = 'Local\PrimalSA-AI-Input-test-' + $PID
$script:PsaLockName = $name
$script:LOG = New-Object System.Collections.ArrayList
function ActLog([string]$m) { [void]$script:LOG.Add($m) }
$fail = 0
function Check($n, $ok) { if ($ok) { "PASS $n" } else { "FAIL $n"; $script:fail++ } }
function Holder([int]$ms, [bool]$release) {
  # 另一個程序拿鎖；$release=$false 時不放就結束（製造 abandoned）
  $rel = if ($release) { '$m.ReleaseMutex();' } else { '' }
  $code = "`$m = New-Object System.Threading.Mutex(`$false, '$name'); [void]`$m.WaitOne(); Start-Sleep -Milliseconds $ms; $rel"
  Start-Process powershell.exe -ArgumentList '-NoProfile', '-Command', $code -WindowStyle Hidden -PassThru
}
function WaitHeld {
  # 等到 holder 真的持有（自己 TryWait 0 失敗 = 別人持有）
  for ($i = 0; $i -lt 100; $i++) {
    $m = New-Object System.Threading.Mutex($false, $name)
    $free = $false
    try { $free = $m.WaitOne(0); if ($free) { $m.ReleaseMutex() } } catch { $free = $true }
    $m.Dispose()
    if (-not $free) { return $true }
    Start-Sleep -Milliseconds 100
  }
  return $false
}

# 1) 基本
Check '沒人持有 → 拿得到' (Enter-PsaInputLock 'click 1,1')
Exit-PsaInputLock
Check '放掉後再拿一次也行' (Enter-PsaInputLock 'click 1,1')
Exit-PsaInputLock
Exit-PsaInputLock   # 重複放不出錯
Check '重複 Exit 不出錯' $true

# 2) 逾時不點
$env:PSA_INPUT_LOCK_MS = '800'
$p = Holder 6000 $true
Check 'holder 已持有' (WaitHeld)
$script:LOG.Clear()
$sw = [Diagnostics.Stopwatch]::StartNew()
$got = Enter-PsaInputLock 'click 5,5'
$ms = $sw.ElapsedMilliseconds
Check "別人持有 → 回 false（等了 $ms ms）" ((-not $got) -and $ms -ge 700 -and $ms -lt 3000)
Check '  逾時有寫 log' (($script:LOG -join "`n") -match '等超過')
Exit-PsaInputLock   # 沒拿到時 Exit 不能出錯 / 不能放別人的鎖
Check '  沒拿到時 Exit 不影響 holder' (WaitHeld)
$p | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

# 3) abandoned 接手
# 持有中被強制結束才會 abandoned（正常結束 PowerShell 會自己放；沒有任何 handle 時具名 Mutex 會整個消失，所以先留一個 handle）
$p = Holder 10000 $false
Check 'abandoned holder 已持有' (WaitHeld)
$keep = New-Object System.Threading.Mutex($false, $name)
$p | Stop-Process -Force
$p.WaitForExit(5000) | Out-Null
$script:LOG.Clear()
$got = Enter-PsaInputLock 'click 9,9'
Check 'holder 沒放就結束 → 接手成功' $got
Check '  abandoned 有寫 log' (($script:LOG -join "`n") -match 'abandoned')
Exit-PsaInputLock
Check '  接手後可正常放、再拿' (Enter-PsaInputLock 'x')
Exit-PsaInputLock
$keep.Dispose()
$env:PSA_INPUT_LOCK_MS = $null

# 4) 帳號查詢
$tmp = Join-Path ([IO.Path]::GetTempPath()) "psa-acct-test-$PID.json"
$env:PSA_ACCOUNTS_FILE = $tmp
[IO.File]::WriteAllText($tmp, '{"PrimalSA222": "SECRETB", "kkfaq11111": "SECRETA", "bad": 5}', (New-Object Text.UTF8Encoding($false)))
Check '資料夾名命中' ((Get-PsaAccount @('PrimalSA222')) -eq 'SECRETB')
Check '第一個鍵沒有 → 用下一個' ((Get-PsaAccount @('', 'nope', 'kkfaq11111')) -eq 'SECRETA')
Check '都沒有 → null' ($null -eq (Get-PsaAccount @('nope')))
Check '值不是字串 → null' ($null -eq (Get-PsaAccount @('bad')))
[IO.File]::WriteAllText($tmp, '{ SECRETX broken', (New-Object Text.UTF8Encoding($false)))
$threw = $false; try { $v = Get-PsaAccount @('x') } catch { $threw = $true }
Check '壞 JSON → null、不丟例外' ((-not $threw) -and $null -eq $v)
Remove-Item $tmp
Check '檔案不存在 → null' ($null -eq (Get-PsaAccount @('PrimalSA222')))
$env:PSA_ACCOUNTS_FILE = $null

# 5) gui.ps1 靜態檢查
$g = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'gui.ps1'), [Text.Encoding]::UTF8)
foreach ($c in 'click', 'dclick', 'drag', 'key', 'typeacct', 'max', 'end') {
  $a = $g.IndexOf("  '$c' {"); $b = $g.IndexOf("`n  '", $a + 5)
  $blk = $g.Substring($a, $b - $a)
  Check "gui.ps1 $c 有拿鎖、有放鎖" (($blk -match '\bLock ') -and ($blk -match 'Exit-PsaInputLock'))
}
$leak = @($g -split "`n" | Where-Object { $_ -match '(ActLog|Write-\w+|Error)[^;{}]*\$acct|"[^"]*\$acct' })
Check "gui.ps1 帳號變數不進 log / 輸出（$($leak.Count) 行可疑）" ($leak.Count -eq 0)
Check 'gui.ps1 / psawin.ps1 維持 BOM' ((([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'gui.ps1')))[0] -eq 0xEF) -and (([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'psawin.ps1')))[0] -eq 0xEF))

if ($fail) { "$fail 項失敗"; exit 1 } else { '全部通過'; exit 0 }
