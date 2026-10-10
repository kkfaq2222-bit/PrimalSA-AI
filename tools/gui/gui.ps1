# 精靈王石器 遊戲視窗操作（只做正常畫面操作：截圖、滑鼠、鍵盤；不讀寫遊戲記憶體）
# 用法：
#   gui.ps1 shot <out.png>            背景截圖（PrintWindow，不搶焦點、不受其他視窗遮擋），縮成 1/Scale 存檔
#   gui.ps1 click <x> <y> [right]     點擊（座標 = 縮圖座標）
#   gui.ps1 dclick <x> <y>            雙擊
#   gui.ps1 drag <x1> <y1> <x2> <y2>  拖曳（縮圖座標）
#   gui.ps1 key <SendKeys字串>        送鍵盤，例：{ESC}、{ENTER}、abc
#   gui.ps1 info                      印出視窗大小 / 位置
#   gui.ps1 pixel <x> <y> | "x,y x,y ..."  背景截圖後印出各點顏色 r,g,b（縮圖座標），給腳本判斷畫面狀態
#   gui.ps1 max                       最大化遊戲視窗（ui/ 座標以最大化的 2880×1659 為準）
#   gui.ps1 end                       任務結束：把前景視窗與游標還給使用者（只有 fg 模式需要）
#   gui.ps1 wait <毫秒>               等待（給 seq 用）
#   gui.ps1 waitpix <逾時毫秒> "x,y,r,g,b[!] ..." [容差]  輪詢背景截圖，等到各點顏色符合（! = 不符合）才回來；印 ok/timeout 毫秒
#   gui.ps1 waitstill <逾時毫秒> [開始等待毫秒]  點地面走路後等鏡頭停下來（印 still / nomove / timeout 毫秒）
#   gui.ps1 ifok / ifnok <指令> ...   上一個 waitpix 成功 / 失敗才執行（seq 用），例：seq "click 462 335; waitpix 1500 948,445,229,197,155; ifok click 948 460"
#   gui.ps1 seq "<動作>; <動作>; ..."  同一個行程連續執行多個動作，例：seq "click 763 760; wait 300; shot C:\\x.png"
#   -Note "用途"                       任何指令後面可加，附註寫進操作 log（gui.sh 用環境變數 PSA_NOTE）
#   操作 log：click / dclick / drag / key / max / end 會寫一行到 tools/.cache/actions.log（只留最新 100 行，psa-hud pane 顯示）；shot / pixel / wait* 不記
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
param([string]$Cmd, [string]$A1, [string]$A2, [string]$A3, [string]$A4, [string]$A5, [double]$Scale = 2, [string]$Note = '')
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
  [DllImport("user32.dll")] static extern UIntPtr SetTimer(IntPtr h, UIntPtr id, uint ms, IntPtr p);
  public struct MSG { public IntPtr h; public uint m; public IntPtr w, l; public uint t; public int x, y; }
  // 每條鉤子執行緒各有自己的 Inst（hook / tid / proc 都是實例欄位）：自己裝、自己拆，
  // 下一次 Start 不會覆蓋上一條的狀態；Stop 只對自己啟動的那條送 WM_QUIT。
  class Inst { public HookProc proc; public IntPtr hook; public uint tid; public System.Threading.Thread th; }
  static Inst cur;
  public static int Swallowed;
  public static int JoinTimeouts;   // Stop() Join 逾時的累計次數（gui.ps1 讀了寫 actions.log）
  public static int AutoUnhooked;   // 逾時自動解除（沒人呼叫 Stop）的累計次數
  public const int MaxLifeMs = 2000;   // 鉤子最多活 2 秒，之後自己 Unhook
  static IntPtr Cb(int n, IntPtr w, IntPtr l) {
    if (n >= 0) {
      int flags = System.Runtime.InteropServices.Marshal.ReadInt32(l, 12);   // MSLLHOOKSTRUCT.flags
      int m = (int)w;
      // 0x0202 / 0x0205 / 0x0208 = 左 / 右 / 中鍵放開
      if ((flags & 1) == 0 && m != 0x0202 && m != 0x0205 && m != 0x0208) { Swallowed++; return (IntPtr)1; }
    }
    return CallNextHookEx(IntPtr.Zero, n, w, l);   // 低階鉤子 hhk 參數會被忽略，不用依賴 static hook
  }
  public static void Start() {
    if (cur != null) Stop();   // 上一條還沒收就先收掉，避免鉤子累積
    Swallowed = 0;
    var inst = new Inst(); cur = inst;
    var ready = new System.Threading.ManualResetEvent(false);
    inst.th = new System.Threading.Thread(delegate() {
      inst.tid = GetCurrentThreadId(); inst.proc = Cb;
      inst.hook = SetWindowsHookEx(14, inst.proc, GetModuleHandle(null), 0);   // WH_MOUSE_LL
      SetTimer(IntPtr.Zero, UIntPtr.Zero, (uint)MaxLifeMs, IntPtr.Zero);   // 到時間丟 WM_TIMER 讓迴圈結束
      ready.Set();
      MSG msg;
      while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0) {   // 低階鉤子要有訊息迴圈
        if (msg.m == 0x0113) { AutoUnhooked++; break; }   // WM_TIMER：逾時自動解除
      }
      if (inst.hook != IntPtr.Zero) UnhookWindowsHookEx(inst.hook);   // 自己裝的自己拆（區域 inst，不會拆到別條）
    });
    inst.th.IsBackground = true; inst.th.Start(); ready.WaitOne(1000);
  }
  // 回傳 false = Join 逾時（執行緒還沒收完，但它之後仍會自己拆自己的鉤子）
  public static bool Stop() {
    var inst = cur; cur = null;
    if (inst == null) return true;
    PostThreadMessage(inst.tid, 0x0012, IntPtr.Zero, IntPtr.Zero);   // WM_QUIT
    bool ok = inst.th.Join(500);
    if (!ok) JoinTimeouts++;
    return ok;
  }
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
$WaitOk = $true

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
# BgEnd 放在 finally 裡跑：$script:saved 有值才還原游標；Guard 一定 Stop，Join 逾時寫 actions.log
function BgEnd {
  try {
    Start-Sleep -Milliseconds 40
    if ($script:saved) { [W]::SetCursorPos($script:saved.X, $script:saved.Y) | Out-Null }
  } finally {
    $script:saved = $null
    if (-not [Guard]::Stop()) { ActLog "Guard Stop Join 逾時（累計 $([Guard]::JoinTimeouts) 次）" }
  }
}
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

# 操作 log：一行「HH:mm:ss 指令 參數 附註」，append 後裁到最新 100 行（失敗不影響操作；多程序偶爾掉一行可接受）
$actLog = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.cache\actions.log'))
function ActLog([string]$msg) {
  try {
    if ($Note) { $msg = "$msg $Note" }
    New-Item -ItemType Directory -Force (Split-Path $actLog) | Out-Null
    $enc = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::AppendAllText($actLog, "$(Get-Date -Format 'HH:mm:ss') $msg`n", $enc)
    $lines = [IO.File]::ReadAllLines($actLog, $enc)
    if ($lines.Count -gt 100) { [IO.File]::WriteAllText($actLog, (($lines | Select-Object -Last 100) -join "`n") + "`n", $enc) }
  } catch { }
}

function Invoke-Gui($Cmd, $A1, $A2, $A3, $A4, $A5) {
 switch ($Cmd) {
  'fg' {
    # fg <指令> ...：這一個指令用前景模式；seq 裡單獨一個 fg 則之後都用前景模式
    if (-not $A1) { $script:Fg = $true; break }
    $old = $script:Fg; $script:Fg = $true; ActLog "fg $A1"
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
    if (-not $ok) { $full.Dispose(); Write-Error "PrintWindow 失敗"; exit 1 }
    $w = [int]($r.R / $Scale); $hh = [int]($r.B / $Scale)
    $small = New-Object System.Drawing.Bitmap $w, $hh
    $g = [System.Drawing.Graphics]::FromImage($small)
    $g.InterpolationMode = 'HighQualityBicubic'; $g.DrawImage($full, 0, 0, $w, $hh); $g.Dispose()
    $small.Save($A1, [System.Drawing.Imaging.ImageFormat]::Png)
    $small.Dispose(); $full.Dispose()   # 兩張都是大 Bitmap（~19 MB / ~5 MB），常駐 server 下不能留給 GC
    "saved ${w}x${hh}"
  }
  'click' {
    if ($A3 -eq 'right') { $dn = 0x0204; $up = 0x0205; $mk = 2; $fdn = 8; $fup = 16 } else { $dn = 0x0201; $up = 0x0202; $mk = 1; $fdn = 2; $fup = 4 }
    if ($script:Fg) {
      Focus; MoveTo $A1 $A2; Start-Sleep -Milliseconds 60
      [W]::mouse_event($fdn, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 60
      [W]::mouse_event($fup, 0, 0, 0, [IntPtr]::Zero)
    } else {
      try {
        BgBegin
        BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg $dn $mk $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg $up 0 $A1 $A2
      } finally { BgEnd }
    }
    ActLog "click $A1,$A2$(if ($A3) { ' ' + $A3 })"
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
      try {
        BgBegin
        BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg 0x0201 1 $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg 0x0202 0 $A1 $A2; Start-Sleep -Milliseconds 80
        BgMsg 0x0203 1 $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg 0x0202 0 $A1 $A2
      } finally { BgEnd }
    }
    ActLog "dclick $A1,$A2"
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
      try {
        BgBegin
        BgMsg 0x0200 0 $A1 $A2; Start-Sleep -Milliseconds 40
        BgMsg 0x0201 1 $A1 $A2; Start-Sleep -Milliseconds 40
        for ($i = 1; $i -le 10; $i++) {
          $x = [double]$A1 + ([double]$A3 - [double]$A1) * $i / 10; $y = [double]$A2 + ([double]$A4 - [double]$A2) * $i / 10
          BgMsg 0x0200 1 $x $y; Start-Sleep -Milliseconds 30
        }
        BgMsg 0x0202 0 $A3 $A4
      } finally { BgEnd }
    }
    ActLog "drag $A1,$A2 -> $A3,$A4"
    "drag $A1,$A2 -> $A3,$A4"
  }
  'max' {
    # 最大化一定會把遊戲帶到前景；做完要 end
    ActLog 'max'; Focus; [W]::ShowWindow($h, 3) | Out-Null; Start-Sleep -Milliseconds 800
    [W]::GetClientRect($h, [ref]$r) | Out-Null; "client=$($r.R)x$($r.B)"
  }
  'key' {
    ActLog "key $A1"
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
    ActLog 'end 還原前景'
    "end: 已還原前景視窗與游標"
  }
  'pixel' {
    $full = New-Object System.Drawing.Bitmap $r.R, $r.B
    $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
    $ok = [W]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
    if (-not $ok) { $full.Dispose(); Write-Error "PrintWindow 失敗"; exit 1 }
    # 點可以是「pixel X Y」或一個字串「pixel "X,Y X,Y ..."」（參數個數有限，多點用後者）
    $pts = if ($A2) { @("$A1,$A2") } else { $A1 -split '[\s/]+' | Where-Object { $_ } }
    $out = foreach ($pt in $pts) {
      $v = $pt -split ','
      $c = $full.GetPixel([int]([double]$v[0] * $Scale), [int]([double]$v[1] * $Scale)); "$($c.R),$($c.G),$($c.B)"
    }
    $full.Dispose(); $out -join ' '
  }
  'waitpix' {
    # waitpix <逾時毫秒> "x,y,r,g,b x,y,r,g,b!..." [容差，預設 30]（seq 裡用 / 分隔各點：x,y,r,g,b/x,y,r,g,b）：反覆背景截圖，等到每個點的顏色都符合才回來
    # （點後面加 ! = 這點要「不是」這個顏色）。印出「ok <毫秒>」或「timeout <毫秒>」，給 seq 取代固定等待用。
    $tol = if ($A3) { [int]$A3 } else { 30 }
    $conds = New-Object System.Collections.ArrayList
    foreach ($t in ($A2 -split '[\s/]+' | Where-Object { $_ })) {
      $neg = $t.EndsWith('!'); $v = $t.TrimEnd('!') -split ','
      [void]$conds.Add(@([int]([double]$v[0] * $Scale), [int]([double]$v[1] * $Scale), [int]$v[2], [int]$v[3], [int]$v[4], $neg))
    }
    $sw = [Diagnostics.Stopwatch]::StartNew(); $hit = $false; $pwfail = $false
    $full = New-Object System.Drawing.Bitmap $r.R, $r.B
    do {
      $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
      $pw = [W]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
      if (-not $pw) { $pwfail = $true; $hit = $false; break }   # 截圖失敗：不要拿黑畫面比到逾時，印 pwfail 讓呼叫端視為「讀不到」
      $hit = $true
      foreach ($c in $conds) {
        $px = $full.GetPixel($c[0], $c[1])
        $m = [Math]::Abs($px.R - $c[2]) -le $tol -and [Math]::Abs($px.G - $c[3]) -le $tol -and [Math]::Abs($px.B - $c[4]) -le $tol
        if ($m -eq $c[5]) { $hit = $false; break }
      }
      if (-not $hit) { Start-Sleep -Milliseconds 20 }
    } while (-not $hit -and $sw.ElapsedMilliseconds -lt [int]$A1)
    $full.Dispose()
    $script:WaitOk = $hit
    if ($pwfail) { 'pwfail' } else { "$(if ($hit) { 'ok' } else { 'timeout' }) $($sw.ElapsedMilliseconds)" }
  }
  'waitstill' {
    # waitstill <逾時毫秒> [開始等待毫秒，預設 600]：等鏡頭停下來（點地面走路後用，取代按格數估的固定等待）。
    # 取畫面中間一圈 20×14 個取樣點（避開角色本身，角色待機動畫會動），先等「開始動」（多數點變色），
    # 再等連續 2 張幾乎不變（< 6% 的點變色）。印出「still <毫秒>」或「timeout <毫秒>」；一直沒開始動印「nomove <毫秒>」。
    $sw = [Diagnostics.Stopwatch]::StartNew(); $startMs = if ($A2) { [int]$A2 } else { 600 }
    # 取樣點以 2880×1659 為準，依客戶區大小等比例縮放（1920×1017 等其他版面；2880×1659 時倍率 1，與原本相同）
    $sx = $r.R / 2880; $sy = $r.B / 1659
    $pts = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt 20; $i++) { for ($j = 0; $j -lt 14; $j++) {
      $x = 900 + $i * 55; $y = 300 + $j * 70
      if ($x -gt 1280 -and $x -lt 1600 -and $y -gt 500 -and $y -lt 950) { continue }
      [void]$pts.Add(@([int]($x * $sx), [int]($y * $sy))) } }
    $full = New-Object System.Drawing.Bitmap $r.R, $r.B
    $prev = $null; $moved = $false; $still = 0; $res = 'timeout'
    while ($sw.ElapsedMilliseconds -lt [int]$A1) {
      $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
      $pw = [W]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
      if (-not $pw) { $res = 'pwfail'; break }   # 截圖失敗（同 waitpix）
      $cur = foreach ($q in $pts) { $full.GetPixel($q[0], $q[1]).ToArgb() }
      if ($prev) {
        $diff = 0; for ($k = 0; $k -lt $cur.Count; $k++) { if ($cur[$k] -ne $prev[$k]) { $diff++ } }
        $frac = $diff / $cur.Count
        if (-not $moved) { if ($frac -gt 0.3) { $moved = $true } elseif ($sw.ElapsedMilliseconds -gt $startMs) { $res = 'nomove'; break } }
        elseif ($frac -lt 0.06) { $still++; if ($still -ge 2) { $res = 'still'; break } } else { $still = 0 }
      }
      $prev = $cur
    }
    $full.Dispose(); $script:WaitOk = ($res -eq 'still')
    if ($res -eq 'pwfail') { 'pwfail' } else { "$res $($sw.ElapsedMilliseconds)" }
  }
  'ifok' {
    # ifok <指令> ...：上一個 waitpix 成功才做（seq 裡用：等到對話框出現就點按鈕，沒出現就跳過）
    if ($script:WaitOk) { Invoke-Gui $A1 $A2 $A3 $A4 $A5 } else { "skip $A1" }
  }
  'ifnok' {
    # ifnok <指令> ...：上一個 waitpix 失敗才做（例：遇敵圖示已經是目標狀態就不點）
    if (-not $script:WaitOk) { Invoke-Gui $A1 $A2 $A3 $A4 $A5 } else { "skip $A1" }
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
