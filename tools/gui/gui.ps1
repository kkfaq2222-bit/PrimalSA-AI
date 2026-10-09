# 精靈王石器 遊戲視窗操作（只做正常畫面操作：截圖、滑鼠、鍵盤；不讀寫遊戲記憶體）
# 用法：
#   gui.ps1 shot <out.png>            背景截圖（PrintWindow，不搶焦點、不受其他視窗遮擋），縮成 1/Scale 存檔
#   gui.ps1 click <x> <y> [right]     點擊（座標 = 縮圖座標）
#   gui.ps1 drag <x1> <y1> <x2> <y2>  拖曳（縮圖座標）
#   gui.ps1 key <SendKeys字串>        送鍵盤，例：{ESC}、{ENTER}、abc
#   gui.ps1 info                      印出視窗大小 / 位置
#   gui.ps1 max                       最大化遊戲視窗（ui/ 座標以最大化的 2880×1659 為準）
#   gui.ps1 end                       任務結束：把前景視窗與游標還給使用者
#   gui.ps1 wait <毫秒>               等待（給 seq 用）
#   gui.ps1 seq "<動作>; <動作>; ..."  同一個行程連續執行多個動作，例：seq "click 763 760; wait 300; shot C:\\x.png"
# 座標系：縮圖座標 × Scale = 客戶區像素座標。Scale 預設 2。
# 前景切換：任務期間第一次 click / drag / key 時記下使用者原本的前景視窗與游標（存 tools/.cache/gui-session.txt），
#           把遊戲拉到前景並一直留著；任務做完呼叫 end 才還原。shot 全程背景（PrintWindow）。
#           Unity 不吃 PostMessage 的滑鼠訊息（實測），所以輸入仍要真的移動游標。
param([string]$Cmd, [string]$A1, [string]$A2, [string]$A3, [string]$A4, [double]$Scale = 2)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8  # 讓 WSL 收到的中文不變亂碼
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int x, int y, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public struct RECT { public int L,T,R,B; }
  public struct POINT { public int X,Y; }
}
"@
[W]::SetProcessDPIAware() | Out-Null
$proc = Get-Process PrimalSA -ErrorAction SilentlyContinue
if (-not $proc) { Write-Error "PrimalSA 沒有在執行"; exit 1 }
$h = $proc.MainWindowHandle
# 最小化時 Unity 不繪製，要還原；用 SW_SHOWNOACTIVATE(4) 不搶焦點
if ([W]::IsIconic($h)) { [W]::ShowWindow($h, 4) | Out-Null; Start-Sleep -Milliseconds 800 }
$r = New-Object W+RECT; [W]::GetClientRect($h, [ref]$r) | Out-Null
$p = New-Object W+POINT; [W]::ClientToScreen($h, [ref]$p) | Out-Null

# 任務期間的使用者狀態（前景視窗、游標）存在檔案裡，跨多次呼叫保留，end 時還原
$stateFile = Join-Path $PSScriptRoot "..\.cache\gui-session.txt"
function SetFg($hwnd) {
  # 暫時把本執行緒的輸入接到目前前景視窗的執行緒，才能繞過前景鎖定（不然只會讓工作列閃爍）
  $me = [W]::GetCurrentThreadId(); $fgT = [W]::GetWindowThreadProcessId([W]::GetForegroundWindow(), [IntPtr]::Zero)
  if ($fgT -ne $me) { [W]::AttachThreadInput($me, $fgT, $true) | Out-Null }
  [W]::BringWindowToTop($hwnd) | Out-Null; [W]::SetForegroundWindow($hwnd) | Out-Null
  if ($fgT -ne $me) { [W]::AttachThreadInput($me, $fgT, $false) | Out-Null }
}
function Focus {
  $fg = [W]::GetForegroundWindow()
  if ($fg -eq $h) { return }
  # 第一次切過來才記錄；任務中使用者切走又切回時不覆蓋最初的狀態
  if (-not (Test-Path $stateFile)) {
    $cur = New-Object W+POINT; [W]::GetCursorPos([ref]$cur) | Out-Null
    New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null
    "$([int64]$fg) $($cur.X) $($cur.Y)" | Set-Content -Encoding ASCII $stateFile
  }
  SetFg $h; Start-Sleep -Milliseconds 120
}
function MoveTo($x, $y) { [W]::SetCursorPos($p.X + [int]([double]$x * $Scale), $p.Y + [int]([double]$y * $Scale)) | Out-Null }

function Invoke-Gui($Cmd, $A1, $A2, $A3, $A4) {
 switch ($Cmd) {
  'info' { "client=$($r.R)x$($r.B) origin=($($p.X),$($p.Y)) scale=$Scale shot=$([int]($r.R/$Scale))x$([int]($r.B/$Scale)) foreground=$([W]::GetForegroundWindow() -eq $h)" }
  'shot' {
    if (-not $A1) { $A1 = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.cache\shot.png")) }
    $full = New-Object System.Drawing.Bitmap $r.R, $r.B
    $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
    # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT（DirectX 視窗要 RENDERFULLCONTENT 才不會黑畫面）
    $ok = [W]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
    if (-not $ok) { Write-Error "PrintWindow 失敗"; exit 1 }
    $w = [int]($r.R / $Scale); $hh = [int]($r.B / $Scale)
    $small = New-Object System.Drawing.Bitmap $w, $hh
    $g = [System.Drawing.Graphics]::FromImage($small)
    $g.InterpolationMode = 'HighQualityBicubic'; $g.DrawImage($full, 0, 0, $w, $hh); $g.Dispose()
    $small.Save($A1, [System.Drawing.Imaging.ImageFormat]::Png)
    "saved ${w}x${hh}"
  }
  'click' {
    Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
    if ($A3 -eq 'right') { $dn = 8; $up = 16 } else { $dn = 2; $up = 4 }
    [W]::mouse_event($dn, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 60
    [W]::mouse_event($up, 0, 0, 0, [IntPtr]::Zero)
    "click $A1,$A2"
  }
  'dclick' {
    # 雙擊：游標不動、兩次按放間隔 80ms（在 Windows 雙擊時間內）。倉庫存入 / 取出用
    Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
    for ($i = 0; $i -lt 2; $i++) {
      [W]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 40
      [W]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero); if ($i -eq 0) { Start-Sleep -Milliseconds 80 }
    }
    "dclick $A1,$A2"
  }
  'drag' {
    Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
    [W]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero)
    for ($i = 1; $i -le 10; $i++) {
      $x = [double]$A1 + ([double]$A3 - [double]$A1) * $i / 10; $y = [double]$A2 + ([double]$A4 - [double]$A2) * $i / 10
      MoveTo $x $y; Start-Sleep -Milliseconds 30
    }
    [W]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero)
    "drag $A1,$A2 -> $A3,$A4"
  }
  'max' {
    Focus; [W]::ShowWindow($h, 3) | Out-Null; Start-Sleep -Milliseconds 800
    [W]::GetClientRect($h, [ref]$r) | Out-Null; "client=$($r.R)x$($r.B)"
  }
  'key' { Focus; [System.Windows.Forms.SendKeys]::SendWait($A1); "key $A1" }
  'end' {
    if (-not (Test-Path $stateFile)) { "end: 沒有要還原的狀態（任務期間沒切過前景）"; break }
    $v = (Get-Content $stateFile -Raw).Trim() -split ' '
    Remove-Item $stateFile
    [W]::SetCursorPos([int]$v[1], [int]$v[2]) | Out-Null
    $prev = [IntPtr][int64]$v[0]
    if ($prev -ne [IntPtr]::Zero -and $prev -ne $h) { SetFg $prev }
    "end: 已還原前景視窗與游標"
  }
  'wait' { Start-Sleep -Milliseconds ([int]$A1) }
  'seq' {
    # 一個行程跑多個動作，省掉每次啟動 PowerShell 的 ~0.4 秒。例：seq "click 763 760; wait 300; click 520 578"
    foreach ($step in ($A1 -split ';')) {
      $t = $step.Trim() -split '\s+'
      if ($t[0]) { Invoke-Gui $t[0] $t[1] $t[2] $t[3] $t[4] }
    }
  }
  default { "未知指令：$Cmd（shot|click|dclick|drag|key|info|max|end|wait|seq）" }
}
}
Invoke-Gui $Cmd $A1 $A2 $A3 $A4
