# 精靈王石器 遊戲視窗操作（只做正常畫面操作：截圖、滑鼠、鍵盤；不讀寫遊戲記憶體）
# 用法：
#   gui.ps1 shot <out.png>            背景截圖（PrintWindow，不搶焦點、不受其他視窗遮擋），縮成 1/Scale 存檔
#   gui.ps1 click <x> <y> [right]     點擊（座標 = 縮圖座標）
#   gui.ps1 dclick <x> <y>            雙擊
#   gui.ps1 drag <x1> <y1> <x2> <y2>  拖曳（縮圖座標）
#   gui.ps1 key <SendKeys字串>        送鍵盤，例：{ESC}、{ENTER}、abc
#   gui.ps1 info                      印出視窗大小 / 位置
#   gui.ps1 max                       最大化遊戲視窗（ui/ 座標以最大化的 2880×1659 為準）
#   gui.ps1 end                       任務結束：把前景視窗與游標還給使用者（只有 fg 模式需要）
#   gui.ps1 wait <毫秒>               等待（給 seq 用）
#   gui.ps1 seq "<動作>; <動作>; ..."  同一個行程連續執行多個動作，例：seq "click 763 760; wait 300; shot C:\\x.png"
#   gui.ps1 fg <指令> ...             用舊的前景模式執行（背景模式失靈時的備案），例：fg click 763 760、seq "fg; click ..."
# 座標系：縮圖座標 × Scale = 客戶區像素座標。Scale 預設 2。
# 背景模式（預設，2026-10-09 實測可用）：不把遊戲拉到前景，使用者可以繼續用其他視窗。
#   - 滑鼠：先 PostMessage WM_ACTIVATEAPP / WM_ACTIVATE / WM_SETFOCUS 讓 Unity 以為有焦點
#     （不然 UGUI 的 StandaloneInputModule 會忽略 UI 點擊，點擊穿透到地面變成走路），
#     再把游標瞬間移到目標、PostMessage 按下 / 放開、立刻移回原位（游標離開約 0.15 秒）。
#     Unity 的滑鼠位置讀的是真實游標，所以游標還是得移過去；按鍵事件則吃 PostMessage。
#   - 點擊期間用低階滑鼠鉤子吞掉使用者實體滑鼠的移動 / 按下（放開放行），使用者怎麼動都不會把點擊帶歪；
#     使用者那邊的代價：每次點擊約 0.15 秒滑鼠沒反應。
#   - 鍵盤：PostMessage WM_KEYDOWN / WM_CHAR / WM_KEYUP，游標完全不動。
# fg 模式：任務期間第一次 click / drag / key 時記下使用者原本的前景視窗與游標（存 tools/.cache/gui-session.txt），
#          把遊戲拉到前景並一直留著；任務做完呼叫 end 才還原。
param([string]$Cmd, [string]$A1, [string]$A2, [string]$A3, [string]$A4, [string]$A5, [double]$Scale = 2)
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
  [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "PostMessageW")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint c, uint t);
  [DllImport("user32.dll")] public static extern short VkKeyScan(char c);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public struct RECT { public int L,T,R,B; }
  public struct POINT { public int X,Y; }
}
// 背景點擊期間（約 0.15 秒）吞掉使用者實體滑鼠的移動 / 按下 / 滾輪，讓游標停在目標上，點擊不會被使用者帶歪。
// 用低階滑鼠鉤子（WH_MOUSE_LL，只過濾本機輸入，不碰遊戲）；放開事件照樣放行，免得使用者那邊的按鍵卡住。
// SetCursorPos 不經過鉤子，本工具移游標不受影響；mouse_event / SendInput 產生的（LLMHF_INJECTED）也放行。
public class Guard {
  delegate IntPtr HookProc(int n, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern IntPtr SetWindowsHookEx(int id, HookProc p, IntPtr mod, uint tid);
  [DllImport("user32.dll")] static extern bool UnhookWindowsHookEx(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr h, int n, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern int GetMessage(out MSG m, IntPtr h, uint a, uint b);
  [DllImport("user32.dll")] static extern bool PostThreadMessage(uint tid, uint m, IntPtr w, IntPtr l);
  [DllImport("kernel32.dll")] static extern IntPtr GetModuleHandle(string n);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
  public struct MSG { public IntPtr h; public uint m; public IntPtr w, l; public uint t; public int x, y; }
  static HookProc proc; static IntPtr hook; static uint tid; static System.Threading.Thread th;
  public static int Swallowed;
  static IntPtr Cb(int n, IntPtr w, IntPtr l) {
    if (n >= 0) {
      int flags = System.Runtime.InteropServices.Marshal.ReadInt32(l, 12);   // MSLLHOOKSTRUCT.flags
      int m = (int)w;
      // 0x0202 / 0x0205 / 0x0208 = 左 / 右 / 中鍵放開
      if ((flags & 1) == 0 && m != 0x0202 && m != 0x0205 && m != 0x0208) { Swallowed++; return (IntPtr)1; }
    }
    return CallNextHookEx(hook, n, w, l);
  }
  public static void Start() {
    Swallowed = 0;
    var ready = new System.Threading.ManualResetEvent(false);
    th = new System.Threading.Thread(delegate() {
      tid = GetCurrentThreadId(); proc = Cb;
      hook = SetWindowsHookEx(14, proc, GetModuleHandle(null), 0);   // WH_MOUSE_LL
      ready.Set();
      MSG msg; while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0) { }   // 低階鉤子要有訊息迴圈
      UnhookWindowsHookEx(hook);
    });
    th.IsBackground = true; th.Start(); ready.WaitOne(1000);
  }
  public static void Stop() { if (th == null) return; PostThreadMessage(tid, 0x0012, IntPtr.Zero, IntPtr.Zero); th.Join(500); th = null; }   // WM_QUIT
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
$Fg = $false

# ---- fg 模式：任務期間的使用者狀態（前景視窗、游標）存在檔案裡，跨多次呼叫保留，end 時還原 ----
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

# ---- 背景模式 ----
function Wake {
  # 讓 Unity 以為視窗有焦點（UI 點擊才會生效）；不改變真正的前景視窗
  [W]::PostMessage($h, 0x001C, [IntPtr]1, [IntPtr]::Zero) | Out-Null   # WM_ACTIVATEAPP
  [W]::PostMessage($h, 0x0006, [IntPtr]1, [IntPtr]::Zero) | Out-Null   # WM_ACTIVATE(WA_ACTIVE)
  [W]::PostMessage($h, 0x0007, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null   # WM_SETFOCUS
  Start-Sleep -Milliseconds 80
}
function ToLParam($x, $y) { $cx = [int]([double]$x * $Scale); $cy = [int]([double]$y * $Scale); [IntPtr](($cy -shl 16) -bor ($cx -band 0xffff)) }
# 背景滑鼠：游標移到 (x,y)（縮圖座標）並送一則滑鼠訊息；wParam = 按著的鍵（MK_LBUTTON 1 / MK_RBUTTON 2）
function BgMsg($msg, $wp, $x, $y) { MoveTo $x $y; [W]::PostMessage($h, $msg, [IntPtr]$wp, (ToLParam $x $y)) | Out-Null }
# 背景滑鼠動作開始 / 結束：鎖住使用者實體滑鼠、記下並還原使用者游標（動作期間使用者移動的量被吞掉，游標回到原位）
function BgBegin { [Guard]::Start(); $script:saved = New-Object W+POINT; [W]::GetCursorPos([ref]$script:saved) | Out-Null; Wake }
function BgEnd { Start-Sleep -Milliseconds 40; [W]::SetCursorPos($script:saved.X, $script:saved.Y) | Out-Null; [Guard]::Stop() }
# 按鍵：WM_KEYDOWN / WM_KEYUP。Unity 會自己 TranslateMessage 產生 WM_CHAR（實測 {BS} 一次刪一字）
function BgKey($vk) {
  $sc = [int64][W]::MapVirtualKey($vk, 0)
  [W]::PostMessage($h, 0x0100, [IntPtr]$vk, [IntPtr](1 -bor ($sc -shl 16))) | Out-Null   # WM_KEYDOWN
  Start-Sleep -Milliseconds 40
  [W]::PostMessage($h, 0x0101, [IntPtr]$vk, [IntPtr](1 -bor ($sc -shl 16) -bor (3L -shl 30))) | Out-Null   # WM_KEYUP
  Start-Sleep -Milliseconds 30
}
# 打字：只送 WM_CHAR（再送按鍵會被 Unity 轉出第二個字元，實測 abc → aabbcc）；中文等任何 Unicode 字元都行
function BgChar([char]$ch) { [W]::PostMessage($h, 0x0102, [IntPtr][int]$ch, [IntPtr]1) | Out-Null; Start-Sleep -Milliseconds 30 }
# SendKeys 語法的子集：{ESC} {ENTER} {TAB} {BS} {DEL} {UP} {DOWN} {LEFT} {RIGHT} {F1}~{F12} {SPACE} {單一字母}（快捷鍵，只送按鍵）
# 與一般字元（打進輸入框，只送 WM_CHAR）
$vkNames = @{ ESC = 0x1B; ESCAPE = 0x1B; ENTER = 0x0D; TAB = 0x09; BS = 0x08; BACKSPACE = 0x08; DEL = 0x2E; DELETE = 0x2E
  UP = 0x26; DOWN = 0x28; LEFT = 0x25; RIGHT = 0x27; SPACE = 0x20; HOME = 0x24; END = 0x23 }
function BgKeys([string]$s) {
  Wake
  $i = 0
  while ($i -lt $s.Length) {
    if ($s[$i] -eq '{') {
      $j = $s.IndexOf('}', $i + 1); $name = $s.Substring($i + 1, $j - $i - 1).ToUpper(); $i = $j + 1
      if ($vkNames.ContainsKey($name)) { BgKey $vkNames[$name] }
      elseif ($name -match '^F(\d+)$') { BgKey (0x6F + [int]$Matches[1]) }
      elseif ($name.Length -eq 1) { BgKey ([W]::VkKeyScan($name[0]) -band 0xff) }
      else { Write-Error "不支援的按鍵 {$name}" }
    } else {
      BgChar $s[$i]; $i++
    }
  }
}

function Invoke-Gui($Cmd, $A1, $A2, $A3, $A4, $A5) {
 switch ($Cmd) {
  'fg' {
    # fg <指令> ...：這一個指令用前景模式；seq 裡單獨一個 fg 則之後都用前景模式
    if (-not $A1) { $script:Fg = $true; break }
    $old = $script:Fg; $script:Fg = $true
    Invoke-Gui $A1 $A2 $A3 $A4 $A5
    $script:Fg = $old
  }
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
    if ($A3 -eq 'right') { $dn = 0x0204; $up = 0x0205; $mk = 2; $fdn = 8; $fup = 16 } else { $dn = 0x0201; $up = 0x0202; $mk = 1; $fdn = 2; $fup = 4 }
    if ($script:Fg) {
      Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
      [W]::mouse_event($fdn, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 60
      [W]::mouse_event($fup, 0, 0, 0, [IntPtr]::Zero)
    } else {
      BgBegin
      BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg $dn $mk $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg $up 0 $A1 $A2
      BgEnd
    }
    "click $A1,$A2" + $(if (-not $script:Fg -and [Guard]::Swallowed) { "（擋下使用者滑鼠 $([Guard]::Swallowed) 次）" })
  }
  'dclick' {
    # 雙擊：游標不動、兩次按放間隔 80ms（在 Windows 雙擊時間內）。倉庫存入 / 取出用
    if ($script:Fg) {
      Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
      for ($i = 0; $i -lt 2; $i++) {
        [W]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 40
        [W]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero); if ($i -eq 0) { Start-Sleep -Milliseconds 80 }
      }
    } else {
      # 背景模式未實測：第二下用 WM_LBUTTONDBLCLK（0x0203），照 Windows 雙擊的訊息順序送
      BgBegin
      BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg 0x0201 1 $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg 0x0202 0 $A1 $A2; Start-Sleep -Milliseconds 80
      BgMsg 0x0203 1 $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg 0x0202 0 $A1 $A2
      BgEnd
    }
    "dclick $A1,$A2"
  }
  'drag' {
    if ($script:Fg) {
      Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
      [W]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero)
      for ($i = 1; $i -le 10; $i++) {
        $x = [double]$A1 + ([double]$A3 - [double]$A1) * $i / 10; $y = [double]$A2 + ([double]$A4 - [double]$A2) * $i / 10
        MoveTo $x $y; Start-Sleep -Milliseconds 30
      }
      [W]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero)
    } else {
      BgBegin
      BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
      BgMsg 0x0201 1 $A1 $A2; Start-Sleep -Milliseconds 40
      for ($i = 1; $i -le 10; $i++) {
        $x = [double]$A1 + ([double]$A3 - [double]$A1) * $i / 10; $y = [double]$A2 + ([double]$A4 - [double]$A2) * $i / 10
        BgMsg 0x0200 1 $x $y; Start-Sleep -Milliseconds 30
      }
      BgMsg 0x0202 0 $A3 $A4
      BgEnd
    }
    "drag $A1,$A2 -> $A3,$A4"
  }
  'max' {
    # 最大化一定會把遊戲帶到前景；做完要 end
    Focus; [W]::ShowWindow($h, 3) | Out-Null; Start-Sleep -Milliseconds 800
    [W]::GetClientRect($h, [ref]$r) | Out-Null; "client=$($r.R)x$($r.B)"
  }
  'key' {
    if ($script:Fg) { Focus; [System.Windows.Forms.SendKeys]::SendWait($A1) } else { BgKeys $A1 }
    "key $A1"
  }
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
      if ($t[0]) { Invoke-Gui $t[0] $t[1] $t[2] $t[3] $t[4] $t[5] }
    }
  }
  default { "未知指令：$Cmd（shot|click|dclick|drag|key|info|max|end|wait|seq|fg）" }
}
}
Invoke-Gui $Cmd $A1 $A2 $A3 $A4 $A5
