# 讀主畫面 HUD 的數值（背景截圖 PrintWindow + Windows 內建 OCR；不搶焦點、不讀遊戲記憶體）
# 用法：stat.ps1   → 印出一行 JSON：{"ok":true,"level":"0轉25級","hp":115,"mp":100,"hpPct":23,"mpPct":100,"petLevel":...,"petHp":...,"map":"...","pos":"1000:92,99"}
#       stat.ps1 -Shot <out.png> [-ShotWidth 960]   → 另外存一張縮小的整窗截圖
# 要看即時遊戲畫面用鏡像視窗 mirror.ps1（mirror.sh）。
# 區域座標 = 客戶區像素（截圖座標 ×2）。支援兩種視窗大小（版面 $L）：2880×1659（原本的基準）、1920×1017（1920×1080 螢幕最大化）；
# 其他大小回 ok=false。
param([string]$Shot, [int]$ShotWidth = 960)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing, System.Runtime.WindowsRuntime
Add-Type @"
using System; using System.Runtime.InteropServices;
public class WS {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  public struct RECT { public int L,T,R,B; }
  // 二值化：light=true 取亮白字（HUD 數字），false 取深色字（地圖名牌）；字 → 黑、其他 → 白
  // 2026-10-10 改 LockBits 逐列處理（同 ocr.ps1）；非 Format32bppArgb 走舊 GetPixel 版保底，輸出與舊版逐位元組相同。
  public static void Binarize(System.Drawing.Bitmap b, bool light) {
    if (b.PixelFormat != System.Drawing.Imaging.PixelFormat.Format32bppArgb) { BinSlow(b, light); return; }
    int w = b.Width, h = b.Height;
    System.Drawing.Imaging.BitmapData d = b.LockBits(new System.Drawing.Rectangle(0, 0, w, h),
      System.Drawing.Imaging.ImageLockMode.ReadWrite, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
    try {
      byte[] row = new byte[w * 4];
      for (int y = 0; y < h; y++) {
        IntPtr p = IntPtr.Add(d.Scan0, y * d.Stride);      // stride 為負時也正確
        Marshal.Copy(p, row, 0, row.Length);
        for (int x = 0; x < w; x++) {
          int i = x * 4; int bl = row[i], g = row[i + 1], r = row[i + 2];
          int mx = Math.Max(r, Math.Max(g, bl)), mn = Math.Min(r, Math.Min(g, bl));
          bool ink = light ? (mn > 190 && mx - mn < 40) : (mx < 110);
          byte v = ink ? (byte)0 : (byte)255;
          row[i] = v; row[i + 1] = v; row[i + 2] = v; row[i + 3] = 255;
        }
        Marshal.Copy(row, 0, p, row.Length);
      }
    } finally { b.UnlockBits(d); }
  }
  static void BinSlow(System.Drawing.Bitmap b, bool light) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); int mx = Math.Max(c.R, Math.Max(c.G, c.B)), mn = Math.Min(c.R, Math.Min(c.G, c.B));
      bool ink = light ? (mn > 190 && mx - mn < 40) : (mx < 110);
      b.SetPixel(x, y, ink ? System.Drawing.Color.Black : System.Drawing.Color.White);
    }
  }
}
"@ -ReferencedAssemblies System.Drawing
function Out-Json($o) { $o | ConvertTo-Json -Compress; exit 0 }
[WS]::SetProcessDPIAware() | Out-Null
$proc = Get-Process PrimalSA -ErrorAction SilentlyContinue
if (-not $proc) { Out-Json @{ ok = $false; error = '遊戲沒有在執行' } }
$h = $proc.MainWindowHandle
# 最小化時 Unity 不繪製，這裡不去還原（不打擾使用者），直接回報
if ([WS]::IsIconic($h)) { Out-Json @{ ok = $false; error = '遊戲視窗最小化' } }
$r = New-Object WS+RECT; [WS]::GetClientRect($h, [ref]$r) | Out-Null
# 各版面的 OCR 區域（x, y, 寬, 高, 放大倍數）與血條 / 魔條掃描線
# 1920×1017：UI 約為 2880×1659 的 0.613 倍（依高度縮放、貼邊對齊），2026-10-09 從截圖量測；字小所以 OCR 放大倍數調高
$Layouts = @{
  '2880x1659' = @{ lv = 150, 186, 180, 46, 2; hp = 340, 92, 200, 44, 2; mp = 340, 166, 200, 38, 2
                   plv = 560, 158, 160, 46, 2; php = 750, 92, 200, 44, 2
                   pos = 2220, 150, 360, 46, 3; pos2 = 2250, 178, 300, 34, 3
                   barX0 = 344; barX1 = 532; hpY = 112; mpY = 180 }
  '1920x1017' = @{ lv = 110, 122, 84, 29, 4; hp = 211, 60, 124, 26, 3; mp = 230, 104, 86, 21, 3
                   plv = 354, 101, 98, 30, 3; php = 466, 60, 124, 26, 3
                   pos = 1530, 98, 190, 30, 4; pos2 = 1545, 113, 185, 22, 4   # pos2（地圖名折兩行）是換算值，未實測
                   barX0 = 214; barX1 = 332; hpY = 72; mpY = 113; retryZoom = 2, 3, 4, 5 }   # MP 兩位數 Windows OCR 常讀不到 → 看 mpPct
}
$L = $Layouts["$($r.R)x$($r.B)"]
if (-not $L) { Out-Json @{ ok = $false; error = "視窗大小 $($r.R)x$($r.B)，只支援 2880x1659 或 1920x1017（請最大化遊戲視窗）" } }

$full = New-Object System.Drawing.Bitmap $r.R, $r.B
$g = [System.Drawing.Graphics]::FromImage($full); $dc = $g.GetHdc()
$ok = [WS]::PrintWindow($h, $dc, 3); $g.ReleaseHdc($dc); $g.Dispose()
if (-not $ok) { Out-Json @{ ok = $false; error = 'PrintWindow 失敗' } }
if ($Shot) {
  $sh = [int]($r.B * $ShotWidth / $r.R)
  $small = New-Object System.Drawing.Bitmap $ShotWidth, $sh
  $g = [System.Drawing.Graphics]::FromImage($small); $g.InterpolationMode = 'HighQualityBicubic'
  $g.DrawImage($full, 0, 0, $ShotWidth, $sh); $g.Dispose()
  # 先寫暫存檔再改名，避免終端機讀到寫一半的圖
  $tmp = "$Shot.tmp"; $small.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png); $small.Dispose()
  Move-Item -Force $tmp $Shot
}

# WinRT OCR（PowerShell 5.1 要自己把 IAsyncOperation 轉成 Task）
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language 'zh-Hant-TW'))
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }

# 裁一塊 → 放大 → OCR，回傳去掉空白的文字
function Ocr([int]$x, [int]$y, [int]$w, [int]$hh, [int]$zoom = 2, [bool]$light = $true) {
  $crop = New-Object System.Drawing.Bitmap ($w * $zoom), ($hh * $zoom)
  $g = [System.Drawing.Graphics]::FromImage($crop); $g.InterpolationMode = 'HighQualityBicubic'
  $g.DrawImage($full, (New-Object System.Drawing.Rectangle 0, 0, ($w * $zoom), ($hh * $zoom)), $x, $y, $w, $hh, 'Pixel'); $g.Dispose()
  [WS]::Binarize($crop, $light)
  # 四周補白邊：字太短又貼邊時 OCR 會整個漏掉（實測 MP「75」）
  $pad = New-Object System.Drawing.Bitmap ($crop.Width + 80), ($crop.Height + 80)
  $g = [System.Drawing.Graphics]::FromImage($pad); $g.Clear([System.Drawing.Color]::White); $g.DrawImage($crop, 40, 40); $g.Dispose()
  $crop.Dispose(); $crop = $pad
  if ($env:STAT_DEBUG) { $crop.Save((Join-Path $env:STAT_DEBUG "$x-$y.png")) }
  $ms = New-Object IO.MemoryStream; $crop.Save($ms, [System.Drawing.Imaging.ImageFormat]::Bmp); $crop.Dispose()
  $ras = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $out = $ras.GetOutputStreamAt(0)
  $wr = New-Object Windows.Storage.Streams.DataWriter $out
  $wr.WriteBytes($ms.ToArray()); $null = Await ($wr.StoreAsync()) ([uint32]); $null = Await ($wr.FlushAsync()) ([bool])
  $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $sb = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $res = Await ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
  ($res.Text -replace '\s', '')
}
function Num($s) { $m = [regex]::Match($s, '\d+'); if ($m.Success) { [int]$m.Value } else { $null } }
# 「N轉M級」：以「轉」字切開；OCR 漏掉轉數時（例「轉42級」）當 0 轉
function Lv($s) {
  $m = [regex]::Match($s, '(\d*)\s*轉\s*(\d+)')
  if ($m.Success) { $t = if ($m.Groups[1].Value) { $m.Groups[1].Value } else { '0' }; return "${t}轉$($m.Groups[2].Value)級" }
  $m = [regex]::Match($s, '(\d+)\D+(\d+)'); if ($m.Success) { "$($m.Groups[1].Value)轉$($m.Groups[2].Value)級" } else { $s }
}

# 區域（客戶區像素）：人物等級 / HP / MP、寵物等級 / HP / MP、地圖名、地圖ID:座標
# 版面有 retryZoom 時（1920×1017：字小，Windows OCR 對同一張圖偶爾整個回空字串），讀不到數字就換放大倍數再試
function OcrAt($a, [bool]$light = $true) {
  $t = Ocr $a[0] $a[1] $a[2] $a[3] $a[4] $light
  foreach ($z in $L.retryZoom) { if ($t -match '\d') { break }; $t = Ocr $a[0] $a[1] $a[2] $a[3] $z $light }
  $t
}
$lvT   = OcrAt $L.lv
$hpT   = OcrAt $L.hp
$mpT   = OcrAt $L.mp
$plvT  = OcrAt $L.plv
$phpT  = OcrAt $L.php
# 座標行：一般在 y≈150；地圖名太長折成兩行時往下移到 y≈172（上面還壓著第二行字）→ 兩個位置都試
function Pos($t) { $m = [regex]::Match($t, '(\d{3,6})[:：.](\d+)[,，.](\d+)'); if ($m.Success) { "$($m.Groups[1].Value):$($m.Groups[2].Value),$($m.Groups[3].Value)" } else { '' } }
$posT = OcrAt $L.pos $false; $pos = Pos $posT
if (-not $pos) { $posT = OcrAt $L.pos2 $false; $pos = Pos $posT }
# 地圖名用地圖 ID 查 knowledge/data/tables/MapName.jsonl（OCR 讀名牌常漏字）
$mapT = ''
if ($pos -match '^(\d+):') {
  $tbl = Join-Path $PSScriptRoot '..\..\knowledge\data\tables\MapName.jsonl'
  $line = Select-String -Path $tbl -Pattern ('^\{"ID":' + $Matches[1] + ',') -Encoding UTF8 | Select-Object -First 1
  if ($line) { $mapT = ($line.Line | ConvertFrom-Json).nameTn }
}
# 血條 / 魔條的填滿比例（0～100）：沿條的中線從左往右掃，第一個「空槽棕色」像素就是填滿的終點。
# OCR 讀不出單一位數（實測 HP「1」二值化後很乾淨，Windows OCR 仍回空字串），低血判斷改看條長比較可靠。
# 條內部 x 344～532（截圖 172～266）；HP 中線 y 112、MP 中線 y 180。數字是白字黑邊，不會被當成棕色。
# 掃到的像素大多不是「填滿色 / 空槽色 / 白字 / 黑邊」時（HUD 被蓋住、其他畫面）回 null。
function Bar([int]$y, [bool]$red) {
  $x0 = $L.barX0; $x1 = $L.barX1; $end = $null; $good = 0; $n = 0
  for ($x = $x0; $x -le $x1; $x += 2) {
    $c = $full.GetPixel($x, $y); $n++
    $empty = [Math]::Abs($c.R - 123) -lt 22 -and [Math]::Abs($c.G - 97) -lt 20 -and [Math]::Abs($c.B - 65) -lt 20
    $fill = if ($red) { $c.R -gt 130 -and $c.R - $c.G -gt 60 -and $c.R - $c.B -gt 60 } else { $c.B -gt 130 -and $c.B - $c.R -gt 60 }
    $text = ([Math]::Min($c.R, [Math]::Min($c.G, $c.B)) -gt 150) -or ([Math]::Max($c.R, [Math]::Max($c.G, $c.B)) -lt 90)
    if ($empty -or $fill -or $text) { $good++ }
    if ($empty -and $null -eq $end) { $end = $x }
  }
  if ($good -lt $n * 0.8) { return $null }
  if ($null -eq $end) { $end = $x1 + 2 }
  [int][Math]::Round(100 * ($end - $x0) / ($x1 + 2 - $x0))
}
$hpPct = Bar $L.hpY $true
$mpPct = Bar $L.mpY $false
$full.Dispose()
Out-Json ([ordered]@{
  ok = $true; level = (Lv $lvT); hp = (Num $hpT); mp = (Num $mpT); hpPct = $hpPct; mpPct = $mpPct
  petLevel = (Lv $plvT); petHp = (Num $phpT)
  map = $mapT; pos = $pos; raw = @($lvT, $hpT, $mpT, $plvT, $phpT, $posT)
})
