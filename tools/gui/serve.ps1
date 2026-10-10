# 常駐 server-lite：從 stdin 讀一行一個 JSON 請求，用 & 呼叫同資料夾的 gui / ocr / stat / findmark / titlematch .ps1，
# 把輸出包成一行回應寫到 stdout。省掉每次啟動 powershell.exe（約 0.22 秒）與 WSL interop 的成本。
# 由 winenv.py 的 GuiServer 啟動：powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File serve.ps1
# 計畫與協定：notes/plan-gui-speedup.md 3.3；3a 驗證結果同檔。
#
# 請求（一行，純 ASCII JSON）：{"id":12,"script":"ocr","pos":["75","270"],"named":{"Zooms":"2,3,4"}}
#   管理指令：{"id":1,"cmd":"ping"} / {"cmd":"stats"} / {"cmd":"quit"}
# 回應：先寫 "\n"（吃掉前面可能殘留的半行），再 "\x1ePSA " + 一行 JSON：{"id":12,"rc":0,"out":"...","err":"...","ms":71}
#   out = 腳本的一般輸出（行以 \n 連接）；err = 錯誤 / 警告 / 詳細 / 資訊串流（行以 \n 連接，帶前綴）；rc = 腳本 exit 碼（例外 = 1）
# 協定細節：
#   - 自己建無 BOM 的 UTF-8 StreamWriter 寫 stdout：各腳本開頭會重設 [Console]::OutputEncoding，不能走 [Console]::Out。
#   - 不設 $ErrorActionPreference / StrictMode（偏好變數會動態傳進被呼叫腳本，要與一次性執行相同語意）。
#   - 本檔所有變數一律 $__psa_ 前綴（被呼叫腳本讀得到呼叫者的變數；前綴避免撞名）。
#   - 迴圈本體不准出現 exit：被呼叫腳本的 exit 只結束該腳本；結束只靠 stdin EOF、quit、看門狗、記憶體自保（都走 Environment.Exit / return）。
param([int]$IdleMin = 15, [int]$GdiMax = 2000, [int]$MemMaxMB = 1500)
$ProgressPreference = 'SilentlyContinue'
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class PsaSrv {
  [DllImport("user32.dll")] static extern uint GetGuiResources(IntPtr h, uint f);
  [DllImport("user32.dll")] public static extern bool IsProcessDPIAware();
  static System.Threading.Timer t;
  public static int Gdi() { return (int)GetGuiResources(System.Diagnostics.Process.GetCurrentProcess().Handle, 0); }
  // 閒置看門狗：每個請求結束時 Arm（重新計時），請求執行中 Disarm（長指令不被殺）；到期直接結束行程
  public static void Arm(int ms) {
    if (t == null) t = new System.Threading.Timer(delegate(object o) { Environment.Exit(0); }, null, ms, System.Threading.Timeout.Infinite);
    else t.Change(ms, System.Threading.Timeout.Infinite);
  }
  public static void Disarm() { if (t != null) t.Change(System.Threading.Timeout.Infinite, System.Threading.Timeout.Infinite); }
}
"@
$__psa_w = New-Object IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object Text.UTF8Encoding $false))
$__psa_w.AutoFlush = $false
$__psa_r = New-Object IO.StreamReader([Console]::OpenStandardInput(), (New-Object Text.UTF8Encoding $false))
$__psa_dir = $PSScriptRoot
$__psa_allow = @('gui', 'ocr', 'stat', 'findmark', 'titlematch')
$__psa_state = @{ req = 0; quit = $false }

function Send-Psa($__psa_obj) {
  $__psa_w.Write("`n" + [char]0x1e + 'PSA ' + ($__psa_obj | ConvertTo-Json -Compress -Depth 4) + "`n")
  $__psa_w.Flush()
}

function Get-PsaStats {
  $__psa_p = [Diagnostics.Process]::GetCurrentProcess()
  @{ pid = $__psa_p.Id; gdi = [PsaSrv]::Gdi(); mb = [int]($__psa_p.PrivateMemorySize64 / 1MB); threads = $__psa_p.Threads.Count
     handles = $__psa_p.HandleCount; req = $__psa_state.req; dpi = [PsaSrv]::IsProcessDPIAware() }
}

# 處理一個請求；回傳要送出的 hashtable。函式內變數全部 $__psa_ 前綴
function Invoke-PsaRequest($__psa_line) {
  $__psa_sw = [Diagnostics.Stopwatch]::StartNew()
  $__psa_id = 0
  try {
    $__psa_q = $__psa_line | ConvertFrom-Json
    $__psa_id = $__psa_q.id
    if ($__psa_q.cmd) {
      switch ($__psa_q.cmd) {
        'ping' { return @{ id = $__psa_id; rc = 0; out = 'pong'; err = ''; ms = 0 } }
        'stats' { return @{ id = $__psa_id; rc = 0; out = ((Get-PsaStats) | ConvertTo-Json -Compress); err = ''; ms = 0 } }
        'quit' { $__psa_state.quit = $true; return @{ id = $__psa_id; rc = 0; out = 'bye'; err = ''; ms = 0 } }
        default { return @{ id = $__psa_id; rc = 2; out = ''; err = "未知管理指令 $($__psa_q.cmd)"; ms = 0 } }
      }
    }
    if ($__psa_allow -notcontains [string]$__psa_q.script) { return @{ id = $__psa_id; rc = 2; out = ''; err = "不允許的腳本 $($__psa_q.script)"; ms = 0 } }
    $__psa_path = Join-Path $__psa_dir ([string]$__psa_q.script + '.ps1')
    # named 值一律字串；pos 逐項字串
    $__psa_named = @{}
    if ($__psa_q.named) { foreach ($__psa_pp in $__psa_q.named.PSObject.Properties) { $__psa_named[$__psa_pp.Name] = [string]$__psa_pp.Value } }
    $__psa_pos = @(); if ($null -ne $__psa_q.pos) { foreach ($__psa_a in @($__psa_q.pos)) { $__psa_pos += [string]$__psa_a } }
    $Error.Clear(); $global:LASTEXITCODE = 0
    $__psa_res = & $__psa_path @__psa_named @__psa_pos *>&1
    $__psa_rc = $global:LASTEXITCODE
    $__psa_o = New-Object Collections.ArrayList; $__psa_e = New-Object Collections.ArrayList
    foreach ($__psa_x in @($__psa_res)) {
      if ($null -eq $__psa_x) { continue }
      if ($__psa_x -is [Management.Automation.ErrorRecord]) { [void]$__psa_e.Add($__psa_x.ToString()) }
      elseif ($__psa_x -is [Management.Automation.WarningRecord]) { [void]$__psa_e.Add('WARNING: ' + $__psa_x.Message) }
      elseif ($__psa_x -is [Management.Automation.VerboseRecord]) { [void]$__psa_e.Add('VERBOSE: ' + $__psa_x.Message) }
      elseif ($__psa_x -is [Management.Automation.DebugRecord]) { [void]$__psa_e.Add('DEBUG: ' + $__psa_x.Message) }
      elseif ($__psa_x -is [Management.Automation.InformationRecord]) { [void]$__psa_o.Add([string]$__psa_x.MessageData) }   # Write-Host 內容
      else { [void]$__psa_o.Add([string]$__psa_x) }
    }
    # 記憶體自保：這些腳本會建大 Bitmap / WinRT 物件，每次都 GC 一輪補救沒 Dispose 的
    if ($__psa_q.script -ne 'gui' -or @('shot', 'seq') -contains [string]$__psa_q.pos[0]) { [GC]::Collect(); [GC]::WaitForPendingFinalizers() }
    return @{ id = $__psa_id; rc = [int]$__psa_rc; out = $(if ($__psa_o.Count) { ($__psa_o -join "`n") + "`n" } else { '' })
              err = $(if ($__psa_e.Count) { ($__psa_e -join "`n") + "`n" } else { '' }); ms = [int]$__psa_sw.ElapsedMilliseconds }
  } catch {
    return @{ id = $__psa_id; rc = 1; out = ''; err = "serve 例外：$($_.Exception.Message)"; ms = [int]$__psa_sw.ElapsedMilliseconds }
  }
}

Send-Psa @{ ready = $true; pid = $PID; dpi = [PsaSrv]::IsProcessDPIAware() }
[PsaSrv]::Arm($IdleMin * 60000)
while ($true) {
  $__psa_line = $__psa_r.ReadLine()
  if ($null -eq $__psa_line) { break }          # stdin EOF（父程序結束 / 關閉）
  if (-not $__psa_line.Trim()) { continue }
  [PsaSrv]::Disarm()
  $__psa_state.req++
  Send-Psa (Invoke-PsaRequest $__psa_line)
  if ($__psa_state.quit) { break }
  # 記憶體 / GDI 自保：超門檻回應後自行結束，client 下次呼叫會重開
  $__psa_st = Get-PsaStats
  if ($__psa_st.gdi -gt $GdiMax -or $__psa_st.mb -gt $MemMaxMB) { break }
  [PsaSrv]::Arm($IdleMin * 60000)
}
