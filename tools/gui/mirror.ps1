# 精靈王石器 畫面鏡像視窗：背景截圖（PrintWindow）即時畫進一個獨立小視窗，不搶焦點、不讀遊戲記憶體
# 用法：mirror.ps1 [-Fps 2]          （WSL：bash tools/gui/mirror.sh）
# - 視窗可自由縮放，畫面保持比例；右鍵選單：置頂、更新速度（0.5 / 1 / 2 / 5 幀）。
# - 鏡像視窗最小化時暫停截圖；遊戲最小化 / 沒開時顯示提示，遊戲重開會自動重新找視窗。
# - 單一執行個體：已經開著就把它帶到前面。位置、大小、置頂、速度存在 tools/.cache/mirror.txt。
# 效能（2026-10-09 實測，Core Ultra 7 258V）：每幀約 25 ms CPU，2 幀 / 秒 ≈ 全機 0.2%。
param([double]$Fps = 0)
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type -ReferencedAssemblies System.Drawing, System.Windows.Forms @"
using System; using System.Drawing; using System.Drawing.Drawing2D; using System.Windows.Forms;
using System.Runtime.InteropServices; using System.Diagnostics; using System.IO;
public class Mirror : Form {
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int c);
  struct RECT { public int L, T, R, B; }
  public static void DpiAware() { SetProcessDPIAware(); }

  IntPtr game = IntPtr.Zero; Bitmap full; string msg = "找遊戲視窗…"; string stateFile;
  Timer timer = new Timer(); MenuItem topItem; double fps;
  public Mirror(string stateFile, double fps) {
    this.stateFile = stateFile;
    Text = "精靈王石器 畫面"; DoubleBuffered = true; BackColor = Color.Black;
    StartPosition = FormStartPosition.Manual; ClientSize = new Size(720, 415); Location = new Point(40, 40);
    bool top = false; double savedFps = 2;
    try {
      var v = File.ReadAllText(stateFile).Trim().Split(' ');
      Location = new Point(int.Parse(v[0]), int.Parse(v[1])); ClientSize = new Size(int.Parse(v[2]), int.Parse(v[3]));
      top = v[4] == "1"; savedFps = double.Parse(v[5], System.Globalization.CultureInfo.InvariantCulture);
    } catch { }
    // 存檔的位置不在任何螢幕上（換過螢幕）就放回左上
    if (Screen.FromRectangle(Bounds).WorkingArea.IntersectsWith(Bounds) == false) Location = new Point(40, 40);
    TopMost = top; this.fps = fps > 0 ? fps : savedFps;
    var menu = new ContextMenu();
    topItem = new MenuItem("置頂", delegate { TopMost = !TopMost; topItem.Checked = TopMost; Save(); });
    topItem.Checked = TopMost; menu.MenuItems.Add(topItem);
    menu.MenuItems.Add("-");
    foreach (double f in new double[] { 0.5, 1, 2, 5 }) {
      double ff = f;
      var it = new MenuItem(f + " 幀 / 秒", delegate { SetFps(ff); Save(); });
      it.RadioCheck = true; menu.MenuItems.Add(it);
    }
    ContextMenu = menu;
    timer.Tick += delegate { Tick(); };
    SetFps(this.fps);
    FormClosing += delegate { Save(); timer.Stop(); };
    Resize += delegate { Invalidate(); };
    // 用 -WindowStyle Hidden 啟動時，行程第一次 ShowWindow 會沿用「隱藏」→ 表單建立後再顯示一次
    Shown += delegate { ShowWindow(Handle, 5); Activate(); };
  }
  void SetFps(double f) {
    fps = f; timer.Interval = (int)(1000 / f); timer.Start();
    foreach (MenuItem it in ContextMenu.MenuItems) if (it.RadioCheck) it.Checked = it.Text.StartsWith(f + " ");
  }
  void Save() {
    if (WindowState != FormWindowState.Normal) return;
    try { File.WriteAllText(stateFile, string.Format(System.Globalization.CultureInfo.InvariantCulture,
      "{0} {1} {2} {3} {4} {5}", Location.X, Location.Y, ClientSize.Width, ClientSize.Height, TopMost ? 1 : 0, fps)); } catch { }
  }
  void Tick() {
    if (WindowState == FormWindowState.Minimized) return;   // 沒人看就不截
    if (game == IntPtr.Zero || !IsWindow(game)) {
      game = IntPtr.Zero;
      foreach (var p in Process.GetProcessesByName("PrimalSA")) if (p.MainWindowHandle != IntPtr.Zero) game = p.MainWindowHandle;
      if (game == IntPtr.Zero) { Status("遊戲沒有在執行"); return; }
    }
    if (IsIconic(game)) { Status("遊戲視窗最小化（Unity 最小化不繪製）"); return; }
    RECT r; GetClientRect(game, out r);
    if (r.R <= 0 || r.B <= 0) { Status("讀不到遊戲視窗大小"); return; }
    if (full == null || full.Width != r.R || full.Height != r.B) { if (full != null) full.Dispose(); full = new Bitmap(r.R, r.B); }
    using (var g = Graphics.FromImage(full)) {
      IntPtr dc = g.GetHdc();
      // 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT（DirectX 視窗要 RENDERFULLCONTENT 才不會黑畫面）
      bool ok = PrintWindow(game, dc, 3); g.ReleaseHdc(dc);
      if (!ok) { Status("PrintWindow 失敗"); return; }
    }
    msg = null; Invalidate();
  }
  void Status(string m) { if (msg != m) { msg = m; Invalidate(); } }
  protected override void OnPaint(PaintEventArgs e) {
    var g = e.Graphics; var c = ClientSize;
    if (msg != null || full == null) {
      TextRenderer.DrawText(g, msg ?? "", Font, new Rectangle(0, 0, c.Width, c.Height), Color.Gray,
        TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak);
      return;
    }
    // 保持比例置中
    double s = Math.Min((double)c.Width / full.Width, (double)c.Height / full.Height);
    int w = (int)(full.Width * s), h = (int)(full.Height * s);
    g.InterpolationMode = InterpolationMode.HighQualityBilinear; g.PixelOffsetMode = PixelOffsetMode.HighSpeed;
    g.DrawImage(full, new Rectangle((c.Width - w) / 2, (c.Height - h) / 2, w, h));
  }
}
"@
[Mirror]::DpiAware()
# 單一執行個體：已開著就把那個視窗帶到前面
$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'PrimalSA-AI-Mirror', [ref]$created)
if (-not $created) {
  Add-Type -Namespace M -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);'
  $other = Get-Process powershell | Where-Object { $_.MainWindowTitle -eq '精靈王石器 畫面' } | Select-Object -First 1
  if ($other) { [M.U]::ShowWindow($other.MainWindowHandle, 9) | Out-Null; [M.U]::SetForegroundWindow($other.MainWindowHandle) | Out-Null }
  exit 0
}
$state = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.cache\mirror.txt'))
New-Item -ItemType Directory -Force (Split-Path $state) | Out-Null
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run((New-Object Mirror $state, $Fps))
$mutex.ReleaseMutex()
