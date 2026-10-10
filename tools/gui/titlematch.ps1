# 任務追蹤列表「標題圖片樣板比對」（取代 OCR 一輪 20～30 秒；背景截圖 PrintWindow，不搶焦點，本機運算不上傳）。座標 = 截圖座標（客戶區 ×1/2）。
# 用法：
#   titlematch.ps1 -Mode match -Dir <樣板資料夾> [-Image 檔.png] [-Thr 0.6]
#       → 一行 JSON：{"ok":true,"ms":120,"hits":[{"name":"伐木證書@1","x":205,"y":310,"score":0.93,"second":0.41},...]}
#         每個樣板在追蹤列表區 LIST_BOX(75,270,260,180) 內找最佳位置（可垂直 / 水平任意偏移）；score = 黑字像素 IoU；
#         second = 該樣板在另一列（與最佳位置垂直距離 >= 樣板高）的次佳分數。只列出 score >= -Thr 的。x,y = 標題中心。
#   titlematch.ps1 -Mode add -Y 310 -Out <新樣板.png> [-Image 檔.png]
#       → 以標題中心 y（OCR 給的）為準，在 y±11 內取黑字外框存成樣板圖；回 {"ok":true,"w":..,"h":..,"ink":..,"x":..,"y":..}
#   -Image 省略 = 即時背景截圖；給檔案 = 用該圖測試（1440×830 或 2880×1659 都行，會統一縮成 1/2 解析度）。
# 黑字 = max(R,G,B) < 140（標題深棕字；步驟說明文字較淺不算）。
param([string]$Mode = 'match', [string]$Dir, [string]$Image, [string]$Out, [int]$Y = 0, [double]$Thr = 0.6)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Drawing; using System.Drawing.Imaging;
public class TM {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  public struct RECT { public int L,T,R,B; }
  public const int DARK = 140;
  public const int RX = 75, RY = 270, RW = 260, RH = 180;   // 與 quest.py LIST_BOX 相同
  // 取 bitmap 的 (x,y,w,h)（半解析度座標）區域最大通道值；寬 >= 2000 的圖先 2x2 平均縮半
  public static int[] Gray(Bitmap bmp, int x0, int y0, int w, int h) {
    int sc = bmp.Width >= 2000 ? 2 : 1;
    BitmapData d = bmp.LockBits(new Rectangle(0, 0, bmp.Width, bmp.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
    byte[] buf = new byte[d.Stride * bmp.Height]; Marshal.Copy(d.Scan0, buf, 0, buf.Length); bmp.UnlockBits(d);
    int[] g = new int[w * h];
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int sr = 0, sg = 0, sb = 0, n = 0;
      for (int dy = 0; dy < sc; dy++) for (int dx = 0; dx < sc; dx++) {
        int px = (x0 + x) * sc + dx, py = (y0 + y) * sc + dy;
        if (px >= bmp.Width || py >= bmp.Height) continue;
        int i = py * d.Stride + px * 4; sb += buf[i]; sg += buf[i + 1]; sr += buf[i + 2]; n++;
      }
      if (n == 0) { g[y * w + x] = 255; continue; }
      g[y * w + x] = Math.Max(sr / n, Math.Max(sg / n, sb / n));
    }
    return g;
  }
  public class Tpl { public string Name; public int W, H; public int[] Xs, Ys; }
  public static Tpl MakeTpl(string name, int[] g, int w, int h) {
    var xs = new List<int>(); var ys = new List<int>();
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) if (g[y * w + x] < DARK) { xs.Add(x); ys.Add(y); }
    return new Tpl { Name = name, W = w, H = h, Xs = xs.ToArray(), Ys = ys.ToArray() };
  }
  // 回傳 [best score, bx, by, second score]（bx,by = 左上角，區域座標）
  public static double[] Match(Tpl t, bool[] ink, int[] integ, int w, int h) {
    int iw = w + 1; double best = -1, second = -1; int bx = 0, by = 0;
    double[] rowBest = new double[h]; int[] rowX = new int[h];
    for (int y = 0; y + t.H <= h; y++) {
      double rb = -1; int rx = 0;
      for (int x = 0; x + t.W <= w; x++) {
        int inter = 0;
        for (int k = 0; k < t.Xs.Length; k++) if (ink[(y + t.Ys[k]) * w + x + t.Xs[k]]) inter++;
        if (inter * 2 < t.Xs.Length) continue;           // 連一半都沒蓋到：不用算
        int win = integ[(y + t.H) * iw + x + t.W] - integ[y * iw + x + t.W] - integ[(y + t.H) * iw + x] + integ[y * iw + x];
        double s = (double)inter / (t.Xs.Length + win - inter);
        if (s > rb) { rb = s; rx = x; }
      }
      rowBest[y] = rb; rowX[y] = rx;
      if (rb > best) { best = rb; by = y; bx = rx; }
    }
    for (int y = 0; y + t.H <= h; y++) if (Math.Abs(y - by) >= t.H && rowBest[y] > second) second = rowBest[y];
    return new double[] { best, bx, by, second };
  }
  public static bool[] InkOf(int[] g) { var m = new bool[g.Length]; for (int i = 0; i < g.Length; i++) m[i] = g[i] < DARK; return m; }
  public static int[] Integral(bool[] ink, int w, int h) {
    int iw = w + 1; int[] s = new int[iw * (h + 1)];
    for (int y = 0; y < h; y++) { int row = 0; for (int x = 0; x < w; x++) { row += ink[y * w + x] ? 1 : 0; s[(y + 1) * iw + x + 1] = s[y * iw + x + 1] + row; } }
    return s;
  }
}
"@ -ReferencedAssemblies System.Drawing
function Out-Json($o) { $o | ConvertTo-Json -Compress -Depth 4; exit 0 }
$sw = [Diagnostics.Stopwatch]::StartNew()
if ($Image) {
  try { $full = New-Object System.Drawing.Bitmap $Image } catch { Out-Json @{ ok = $false; error = "讀不到圖：$Image" } }
} else {
  [TM]::SetProcessDPIAware() | Out-Null
  $proc = Get-Process PrimalSA -ErrorAction SilentlyContinue
  # 同時開多個客戶端時，用環境變數 PSA_EXE_MATCH（角色 1 的名字（clients.json 對照）或客戶端資料夾名，例：角色1名字 / PrimalSA222）指定要操作哪一個
  if ($env:PSA_EXE_MATCH) { . (Join-Path $PSScriptRoot 'psaclient.ps1'); $proc = Select-PsaProc $proc }
  if (-not $proc) { Out-Json @{ ok = $false; error = '遊戲沒有在執行' } }
  $h = $proc.MainWindowHandle
  if ([TM]::IsIconic($h)) { Out-Json @{ ok = $false; error = '遊戲視窗最小化' } }
  $r = New-Object TM+RECT; [TM]::GetClientRect($h, [ref]$r) | Out-Null
  $full = New-Object System.Drawing.Bitmap $r.R, $r.B
  $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
  $ok = [TM]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
  if (-not $ok) { Out-Json @{ ok = $false; error = 'PrintWindow 失敗' } }
}
$W = [TM]::RW; $H = [TM]::RH
$gray = [TM]::Gray($full, [TM]::RX, [TM]::RY, $W, $H)
$full.Dispose()
if ($Mode -eq 'add') {
  # 以 Y 為標題中心（截圖座標）取 y±11 內的黑字外框
  $ly = $Y - [TM]::RY; $y0 = [Math]::Max(0, $ly - 11); $y1 = [Math]::Min($H - 1, $ly + 11)
  $x0 = 9999; $x1 = -1; $yy0 = 9999; $yy1 = -1; $n = 0
  for ($yy = $y0; $yy -le $y1; $yy++) { for ($xx = 35; $xx -lt 225; $xx++) { if ($gray[$yy * $W + $xx] -lt [TM]::DARK) {
    $n++; if ($xx -lt $x0) { $x0 = $xx }; if ($xx -gt $x1) { $x1 = $xx }; if ($yy -lt $yy0) { $yy0 = $yy }; if ($yy -gt $yy1) { $yy1 = $yy } } } }
  if ($n -lt 60) { Out-Json @{ ok = $false; error = "y=$Y 附近黑字太少（$n）" } }
  $x0 = [Math]::Max(0, $x0 - 1); $x1 = [Math]::Min($W - 1, $x1 + 1); $yy0 = [Math]::Max(0, $yy0 - 1); $yy1 = [Math]::Min($H - 1, $yy1 + 1)
  $tw = $x1 - $x0 + 1; $th = $yy1 - $yy0 + 1
  # 外框外 2px 一圈必須是米色卡片底（亮）：框線 / 木框 / 兩行字黏在一起都會被擋下（畫面剛好捲動時會抓到那些）
  $lt = 0; $tot = 0
  for ($xx = $x0 - 2; $xx -le $x1 + 2; $xx++) { foreach ($yy in @(($yy0 - 2), ($yy1 + 2))) { if ($xx -ge 0 -and $xx -lt $W -and $yy -ge 0 -and $yy -lt $H) { $tot++; if ($gray[$yy * $W + $xx] -ge 170) { $lt++ } } } }
  if ($tot -lt 10 -or $lt / $tot -lt 0.9) { Out-Json @{ ok = $false; error = "標題外框的周圍不是亮底（$lt/$tot），可能抓到框線或畫面剛捲動" } }
  $bm = New-Object System.Drawing.Bitmap $tw, $th
  for ($yy = 0; $yy -lt $th; $yy++) { for ($xx = 0; $xx -lt $tw; $xx++) {
    $v = $gray[($yy0 + $yy) * $W + $x0 + $xx]; $bm.SetPixel($xx, $yy, [System.Drawing.Color]::FromArgb($v, $v, $v)) } }
  $bm.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); $bm.Dispose()
  Out-Json ([ordered]@{ ok = $true; w = $tw; h = $th; ink = $n; x = [int]($x0 + [TM]::RX + $tw / 2); y = [int]($yy0 + [TM]::RY + $th / 2); out = $Out })
}
# match
$ink = [TM]::InkOf($gray); $integ = [TM]::Integral($ink, $W, $H)
$hits = @()
if ($Dir -and (Test-Path -LiteralPath $Dir)) {
  foreach ($f in Get-ChildItem -LiteralPath $Dir -Filter *.png) {
    if ($f.Name.StartsWith('_')) { continue }
    $b = New-Object System.Drawing.Bitmap $f.FullName
    $bw = $b.Width; $bh = $b.Height; $tg = [TM]::Gray($b, 0, 0, $bw, $bh); $b.Dispose()
    $t = [TM]::MakeTpl([IO.Path]::GetFileNameWithoutExtension($f.Name), $tg, $bw, $bh)
    if ($t.Xs.Length -lt 60) { continue }
    $m = [TM]::Match($t, $ink, $integ, $W, $H)
    if ($m[0] -ge $Thr) {
      $hits += [ordered]@{ name = $t.Name; x = [int]($m[1] + [TM]::RX + $t.W / 2); y = [int]($m[2] + [TM]::RY + $t.H / 2); score = [Math]::Round($m[0], 3); second = [Math]::Round([Math]::Max($m[3], 0), 3) }
    }
  }
}
Out-Json ([ordered]@{ ok = $true; ms = [int]$sw.ElapsedMilliseconds; hits = $hits })
