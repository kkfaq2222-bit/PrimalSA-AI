# HUD 數字樣板比對的截圖端：背景 PrintWindow → 依版面裁出各欄位 → 原解析度二值化 → 輸出 0/1 字串列（不做 OCR；比對在 digitmatch.py）
# 用法：digitmatch.ps1 [-Image 檔.png]  → 一行 JSON：{"ok":true,"layout":"2880x1659","ms":N,"fields":{"lv":"0010..,0110..,...",...}}（每欄一個字串，列以逗號分隔）
#   -Boxes "x,y,w,h,mode;…"：改裁自訂框（客戶區像素；mode 1 = 亮字、0 = 深字、2 = 咖啡色字），只輸出 fields.b0,b1,…（namematch.py 切換面板卡片名字用，不輸出 HUD 欄位 / 血條）。
#   -Image：用截圖檔測試（尺寸須是支援的版面）。唯讀：只截圖，不點擊、不送鍵。
# 另外輸出 hpPct / mpPct（血條 / 魔條比例，-1 = 掃不出來）。版面座標與 stat.ps1 的 $Layouts 一致（x, y, 寬, 高；客戶區像素）。字色：HUD 數字 = 亮白字（light）；座標行 = 深色字（dark）。
param([string]$Image, [string]$Boxes)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
if (-not ("DM" -as [type])) { Add-Type -TypeDefinition @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Drawing; using System.Drawing.Imaging;
public class DM {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  public struct RECT { public int L,T,R,B; }
  // 把 bmp 的 (x0,y0,w,h) 區域二值化成 h 個長度 w 的 '0'/'1' 字串（1 = 字）；一次 LockBits，整張只讀一次
  public static string[] Crop(byte[] buf, int stride, int bw, int bh, int x0, int y0, int w, int h, bool light) { return CropMode(buf, stride, bw, bh, x0, y0, w, h, light ? 1 : 0); }
  // mode：1 = 亮白字、0 = 深色字（mx<110）、2 = 咖啡色字（切換面板卡片名字 ≈ (125,64,28)；米底 (249,231,200)）
  public static string[] CropMode(byte[] buf, int stride, int bw, int bh, int x0, int y0, int w, int h, int mode) {
    string[] rows = new string[h];
    char[] line = new char[w];
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        int px = x0 + x, py = y0 + y; char c = '0';
        if (px >= 0 && py >= 0 && px < bw && py < bh) {
          int i = py * stride + px * 4; int b = buf[i], g = buf[i + 1], r = buf[i + 2];
          int mx = Math.Max(r, Math.Max(g, b)), mn = Math.Min(r, Math.Min(g, b));
          bool ink = mode == 1 ? (mn > 190 && mx - mn < 40) : mode == 2 ? (r < 170 && g < 130 && b < 100) : (mx < 110);
          if (ink) c = '1';
        }
        line[x] = c;
      }
      rows[y] = new string(line);
    }
    return rows;
  }
  // 血條 / 魔條填滿比例 0～100（同 stat.ps1 的 Bar：沿中線每 2 px 掃，第一個空槽棕色像素是終點；掃到的像素多半不像條 / 字 → -1）
  public static int Bar(byte[] buf, int stride, int bw, int bh, int y, int x0, int x1, bool red) {
    int end = -1, good = 0, n = 0;
    if (y < 0 || y >= bh || x1 >= bw) return -1;
    for (int x = x0; x <= x1; x += 2) {
      int i = y * stride + x * 4; int b = buf[i], g = buf[i + 1], r = buf[i + 2]; n++;
      bool empty = Math.Abs(r - 123) < 22 && Math.Abs(g - 97) < 20 && Math.Abs(b - 65) < 20;
      bool fill = red ? (r > 130 && r - g > 60 && r - b > 60) : (b > 130 && b - r > 60);
      int mn = Math.Min(r, Math.Min(g, b)), mx = Math.Max(r, Math.Max(g, b));
      bool text = mn > 150 || mx < 90;
      if (empty || fill || text) good++;
      if (empty && end < 0) end = x;
    }
    if (good < n * 0.8) return -1;
    if (end < 0) end = x1 + 2;
    return (int)Math.Round(100.0 * (end - x0) / (x1 + 2 - x0));
  }
  public static byte[] Bytes(Bitmap bmp, out int stride) {
    BitmapData d = bmp.LockBits(new Rectangle(0, 0, bmp.Width, bmp.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
    stride = d.Stride; byte[] buf = new byte[d.Stride * bmp.Height]; Marshal.Copy(d.Scan0, buf, 0, buf.Length); bmp.UnlockBits(d);
    return buf;
  }
}
"@ -ReferencedAssemblies System.Drawing }   # 常駐 server 內第二次起不用重編（type 已存在）
function Out-Json($o) { $o | ConvertTo-Json -Compress -Depth 5; exit 0 }
$sw = [Diagnostics.Stopwatch]::StartNew()
if ($Image) {
  try { $full = New-Object System.Drawing.Bitmap $Image } catch { Out-Json @{ ok = $false; error = "讀不到圖：$Image" } }
  $W = $full.Width; $Hh = $full.Height
} else {
  [DM]::SetProcessDPIAware() | Out-Null
  $proc = Get-Process PrimalSA -ErrorAction SilentlyContinue
  # 同時開多個客戶端時，用 PSA_EXE_MATCH 指定哪一個（沒選會拿到陣列 → IsIconic 型別轉換失敗；2026-10-12）
  if ($env:PSA_EXE_MATCH -and $proc) { . (Join-Path $PSScriptRoot 'psaclient.ps1'); $proc = Select-PsaProc $proc }
  if (-not $proc) { Out-Json @{ ok = $false; error = '遊戲沒有在執行' } }
  $h = $proc.MainWindowHandle
  if ([DM]::IsIconic($h)) { Out-Json @{ ok = $false; error = '遊戲視窗最小化' } }
  $r = New-Object DM+RECT; [DM]::GetClientRect($h, [ref]$r) | Out-Null
  $W = $r.R; $Hh = $r.B
  $full = New-Object System.Drawing.Bitmap $W, $Hh
  $g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
  $ok = [DM]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
  if (-not $ok) { Out-Json @{ ok = $false; error = 'PrintWindow 失敗' } }
}
# 欄位：名稱 = x, y, w, h, light（1 = 亮字、0 = 深字）
$Bars = @{ '2880x1659' = @(344, 532, 112, 180); '1920x1017' = @(214, 332, 72, 113) }   # barX0, barX1, hpY, mpY（同 stat.ps1）
$Layouts = @{
  '2880x1659' = [ordered]@{ lv = 150,186,180,46,1; hp = 340,92,200,44,1; mp = 340,166,200,38,1; plv = 560,158,160,46,1; php = 750,92,200,44,1; pos = 2220,150,360,46,0; pos2 = 2250,178,300,34,0 }
  '1920x1017' = [ordered]@{ lv = 110,122,84,29,1; hp = 211,60,124,26,1; mp = 230,104,86,21,1; plv = 354,101,98,30,1; php = 466,60,124,26,1; pos = 1530,98,190,30,0; pos2 = 1545,113,185,22,0 }
}
if ($Boxes) {   # 自訂框模式：不管版面，座標由呼叫端給
  $stride = 0; $buf = [DM]::Bytes($full, [ref]$stride); $full.Dispose()
  $f = [ordered]@{}; $i = 0
  foreach ($b in ($Boxes -split ';')) { $a = $b.Split(','); if ($a.Count -lt 5) { continue }
    $f["b$i"] = ([DM]::CropMode($buf, $stride, $W, $Hh, [int]$a[0], [int]$a[1], [int]$a[2], [int]$a[3], [int]$a[4]) -join ","); $i++ }
  Out-Json ([ordered]@{ ok = $true; layout = "${W}x${Hh}"; ms = [int]$sw.ElapsedMilliseconds; fields = $f })
}
$key = "${W}x${Hh}"; $L = $Layouts[$key]
if (-not $L) { Out-Json @{ ok = $false; error = "視窗大小 $key，只支援 2880x1659 或 1920x1017" } }
$stride = 0; $buf = [DM]::Bytes($full, [ref]$stride); $full.Dispose()
$f = [ordered]@{}
foreach ($k in $L.Keys) { $a = $L[$k]; $f[$k] = ([DM]::Crop($buf, $stride, $W, $Hh, $a[0], $a[1], $a[2], $a[3], ($a[4] -eq 1)) -join ",") }
$bb = $Bars[$key]
$hpPct = [DM]::Bar($buf, $stride, $W, $Hh, $bb[2], $bb[0], $bb[1], $true); $mpPct = [DM]::Bar($buf, $stride, $W, $Hh, $bb[3], $bb[0], $bb[1], $false)
Out-Json ([ordered]@{ ok = $true; layout = $key; ms = [int]$sw.ElapsedMilliseconds; hpPct = $hpPct; mpPct = $mpPct; fields = $f })
