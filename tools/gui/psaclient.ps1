# 多客戶端指定：環境變數 PSA_EXE_MATCH 可以填「帳號代號」或「客戶端資料夾名」。
# 名字對照放 tools/.cache/clients.json（不進 git），格式：{"kkfaq11111": "gameClient", "kkfaq22222": "PrimalSA222"}
# 挑選順序：資料夾名完全相等優先（PrimalSA 不會誤中 PrimalSA222）；沒有才退回路徑子字串比對。
function Resolve-PsaClient([string]$m) {
  if (-not $m) { return $m }
  $f = Join-Path $PSScriptRoot '..\.cache\clients.json'
  if (Test-Path -LiteralPath $f) {
    try {
      $j = Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json
      $v = $j.PSObject.Properties[$m]
      if ($v -and $v.Value) { return [string]$v.Value }
    } catch { }
  }
  return $m
}
function Select-PsaProc($procs) {
  $m = Resolve-PsaClient $env:PSA_EXE_MATCH
  $all = @($procs | Where-Object { $_ -and $_.Path })
  if (-not $m) { return $all | Sort-Object { try { $_.StartTime } catch { [datetime]::MaxValue } } | Select-Object -First 1 }   # 沒設定 = 主視窗：最早啟動的
  $exact = @($all | Where-Object { (Split-Path -Leaf (Split-Path -Parent $_.Path)) -eq $m })
  if ($exact.Count -gt 0) { return $exact[0] }
  $part = @($all | Where-Object { $_.Path -like "*$m*" })
  if ($part.Count -gt 1) {
    [Console]::Error.WriteLine("PSA_EXE_MATCH=$m 同時比到 $($part.Count) 個客戶端，不操作任何一個；請改用角色名或完整資料夾名")
    return $null
  }
  return $part | Select-Object -First 1
}
