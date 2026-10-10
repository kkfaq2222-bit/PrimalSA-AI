# 精靈王石器 畫面鏡像視窗：用 DWM 縮圖（Alt+Tab 預覽同一套）把遊戲視窗即時合成進一個獨立小視窗
# 用法：mirror.ps1          （WSL：bash tools/gui/mirror.sh）
# - 幀數跟遊戲同步、幾乎不吃 CPU（顯示卡合成，不截圖、不縮放）；不搶焦點、不讀遊戲記憶體。
# - 視窗可自由縮放，畫面保持比例。預設置頂，可在畫面右鍵選單與標題列選單取消（兩邊同步）。
# - 遊戲最小化時 DWM 沒有畫面可給（Unity 最小化不繪製）→ 顯示提示；遊戲重開會自動重新接上。
# - 單一執行個體：已經開著就把它帶到前面。位置、大小、置頂存在 tools/.cache/mirror.txt。
# 同時開多個客戶端：設環境變數 PSA_EXE_MATCH（路徑片段，例：PrimalSA222）就只鏡像那一個，且各自一個鏡像視窗
#   （單一執行個體、位置存檔 tools/.cache/mirror-<片段>.txt、標題列「精靈王石器 畫面 - <片段>」都各自獨立）。
# 舊版每幀用 PrintWindow 截圖，2 幀/秒 ≈ 全機 CPU 0.9%；DWM 縮圖不需要。
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type -ReferencedAssemblies System.Drawing, System.Windows.Forms @"
using System; using System.Drawing; using System.Windows.Forms;
using System.Runtime.InteropServices; using System.Diagnostics; using System.IO;
public class Mirror : Form {
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] static extern IntPtr GetSystemMenu(IntPtr h, bool revert);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool AppendMenu(IntPtr m, uint flags, UIntPtr id, string text);
  [DllImport("user32.dll")] static extern uint CheckMenuItem(IntPtr m, uint id, uint flags);
  [DllImport("dwmapi.dll")] static extern int DwmRegisterThumbnail(IntPtr dest, IntPtr src, out IntPtr thumb);
  [DllImport("dwmapi.dll")] static extern int DwmUnregisterThumbnail(IntPtr thumb);
  [DllImport("dwmapi.dll")] static extern int DwmUpdateThumbnailProperties(IntPtr thumb, ref THUMBPROPS p);
  struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] struct THUMBPROPS {
    public uint flags; public RECT dest; public RECT src; public byte opacity;
    [MarshalAs(UnmanagedType.Bool)] public bool visible; [MarshalAs(UnmanagedType.Bool)] public bool clientOnly;
  }
  const uint SC_TOP = 0x1000;   // 標題列系統選單的「置頂」
  public static void DpiAware() { SetProcessDPIAware(); }

  IntPtr game = IntPtr.Zero, thumb = IntPtr.Zero; string msg = "找遊戲視窗…"; string stateFile;
  string match = ""; Timer timer = new Timer(); MenuItem topItem; int srcW, srcH; bool shown;
  public Mirror(string stateFile) {
    this.stateFile = stateFile;
    var mt = Environment.GetEnvironmentVariable("PSA_EXE_MATCH");
    if (!string.IsNullOrEmpty(mt)) match = mt;
    Text = "精靈王石器 畫面" + (match != "" ? " - " + match : ""); DoubleBuffered = true; BackColor = Color.Black;
    StartPosition = FormStartPosition.Manual; ClientSize = new Size(720, 415); Location = new Point(40, 40);
    bool top = true;   // 預設置頂；存檔裡有記錄就以存檔為準（右鍵選單可取消）
    try {
      var v = File.ReadAllText(stateFile).Trim().Split(' ');
      Location = new Point(int.Parse(v[0]), int.Parse(v[1])); ClientSize = new Size(int.Parse(v[2]), int.Parse(v[3]));
      top = v[4] == "1";
    } catch { }
    // 存檔的位置不在任何螢幕上（換過螢幕）就放回左上
    if (!Screen.FromRectangle(Bounds).WorkingArea.IntersectsWith(Bounds)) Location = new Point(40, 40);
    TopMost = top;
    var menu = new ContextMenu();
    topItem = new MenuItem("置頂", delegate { SetTop(!TopMost); });
    topItem.Checked = TopMost; menu.MenuItems.Add(topItem);
    ContextMenu = menu;
    // 計時器只負責檢查遊戲還在不在、有沒有最小化、大小有沒有變；畫面本身由 DWM 即時合成
    timer.Interval = 500; timer.Tick += delegate { Check(); }; timer.Start();
    FormClosing += delegate { Save(); timer.Stop(); Drop(); };
    Resize += delegate { Place(); Invalidate(); };
    // 用 -WindowStyle Hidden 啟動時，行程第一次 ShowWindow 會沿用「隱藏」→ 表單建立後再顯示一次
    Shown += delegate { ShowWindow(Handle, 5); Activate(); shown = true; Check(); };
  }
  // 置頂：畫面右鍵選單與標題列系統選單兩邊同步打勾
  void SetTop(bool on) {
    TopMost = on; topItem.Checked = on;
    if (IsHandleCreated) CheckMenuItem(GetSystemMenu(Handle, false), SC_TOP, on ? 8u : 0u);   // MF_CHECKED = 8
    Save();
  }
  protected override void OnHandleCreated(EventArgs e) {
    base.OnHandleCreated(e);
    IntPtr m = GetSystemMenu(Handle, false);
    AppendMenu(m, 0x800, UIntPtr.Zero, null);                     // MF_SEPARATOR
    AppendMenu(m, TopMost ? 8u : 0u, (UIntPtr)SC_TOP, "置頂(&T)");
  }
  protected override void WndProc(ref Message m) {
    if (m.Msg == 0x0112 && ((long)m.WParam & 0xFFF0) == SC_TOP) { SetTop(!TopMost); return; }   // WM_SYSCOMMAND
    base.WndProc(ref m);
  }
  void Save() {
    if (WindowState != FormWindowState.Normal) return;
    try { File.WriteAllText(stateFile, string.Format("{0} {1} {2} {3} {4}",
      Location.X, Location.Y, ClientSize.Width, ClientSize.Height, TopMost ? 1 : 0)); } catch { }
  }
  void Drop() { if (thumb != IntPtr.Zero) { DwmUnregisterThumbnail(thumb); thumb = IntPtr.Zero; } }
  void Check() {
    if (!shown) return;
    if (game == IntPtr.Zero || !IsWindow(game)) {
      Drop(); game = IntPtr.Zero;
      foreach (var p in Process.GetProcessesByName("PrimalSA")) {
        if (p.MainWindowHandle == IntPtr.Zero) continue;
        if (match != "") {
          string path = "";
          try { path = p.MainModule.FileName; } catch { }
          if (path.IndexOf(match, StringComparison.OrdinalIgnoreCase) < 0) continue;
        }
        game = p.MainWindowHandle;
      }
      if (game == IntPtr.Zero) { Status("遊戲沒有在執行"); return; }
    }
    if (IsIconic(game)) { Status("遊戲視窗最小化（Unity 最小化不繪製）"); return; }
    RECT r; GetClientRect(game, out r);
    if (r.R <= 0 || r.B <= 0) { Status("讀不到遊戲視窗大小"); return; }
    if (thumb == IntPtr.Zero && DwmRegisterThumbnail(Handle, game, out thumb) != 0) { thumb = IntPtr.Zero; Status("DWM 縮圖註冊失敗"); return; }
    bool changed = msg != null || r.R != srcW || r.B != srcH;
    srcW = r.R; srcH = r.B;
    if (changed) { msg = null; Place(); Invalidate(); }
  }
  // 把縮圖放到視窗中間、保持比例；只取遊戲的客戶區（不含標題列）
  void Place() {
    if (thumb == IntPtr.Zero || srcW <= 0) return;
    var c = ClientSize;
    double s = Math.Min((double)c.Width / srcW, (double)c.Height / srcH);
    int w = (int)(srcW * s), h = (int)(srcH * s), x = (c.Width - w) / 2, y = (c.Height - h) / 2;
    var p = new THUMBPROPS();
    p.flags = 0x1 | 0x8 | 0x10;   // RECTDESTINATION | VISIBLE | SOURCECLIENTAREAONLY
    p.dest = new RECT { L = x, T = y, R = x + w, B = y + h };
    p.visible = msg == null; p.clientOnly = true;
    DwmUpdateThumbnailProperties(thumb, ref p);
  }
  void Status(string m) { if (msg != m) { msg = m; Place(); Invalidate(); } }
  protected override void OnPaint(PaintEventArgs e) {
    if (msg == null) return;   // 有畫面時 DWM 直接蓋在上面
    var c = ClientSize;
    TextRenderer.DrawText(e.Graphics, msg, Font, new Rectangle(0, 0, c.Width, c.Height), Color.Gray,
      TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak);
  }
}
"@
[Mirror]::DpiAware()
# 單一執行個體：已開著就把那個視窗帶到前面
$created = $false
$suffix = if ($env:PSA_EXE_MATCH) { '-' + $env:PSA_EXE_MATCH } else { '' }
$mutex = New-Object System.Threading.Mutex($true, "PrimalSA-AI-Mirror$suffix", [ref]$created)
if (-not $created) {
  Add-Type -Namespace M -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);'
  $other = Get-Process powershell | Where-Object { $_.MainWindowTitle -eq ('精靈王石器 畫面' + $(if ($env:PSA_EXE_MATCH) { ' - ' + $env:PSA_EXE_MATCH } else { '' })) } | Select-Object -First 1
  if ($other) { [M.U]::ShowWindow($other.MainWindowHandle, 9) | Out-Null; [M.U]::SetForegroundWindow($other.MainWindowHandle) | Out-Null }
  exit 0
}
$state = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.cache\mirror$(if ($env:PSA_EXE_MATCH) { '-' + $env:PSA_EXE_MATCH } else { '' }).txt"))
New-Item -ItemType Directory -Force (Split-Path $state) | Out-Null
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run((New-Object Mirror $state))
$mutex.ReleaseMutex()
