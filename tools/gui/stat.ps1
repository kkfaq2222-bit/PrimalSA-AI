# 讀主畫面 HUD 的數值（背景截圖 PrintWindow + Windows 內建 OCR；不搶焦點、不讀遊戲記憶體）
# 用法：stat.ps1   → 印出一行 JSON：{"ok":true,"level":"0轉25級","hp":115,"mp":100,"petLevel":...,"petHp":...,"map":"...","pos":"1000:92,99"}
#       stat.ps1 -Shot <out.png> [-ShotWidth 960]   → 另外存一張縮小的整窗截圖（給 psa-hud mod 的 pane 顯示）
# 區域座標 = 客戶區 2880×1659 的像素（截圖座標 ×2）；視窗大小不同時回 ok=false。
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
  public static void Binarize(System.Drawing.Bitmap b, bool light) {
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
if ($r.R -ne 2880 -or $r.B -ne 1659) { Out-Json @{ ok = $false; error = "視窗大小 $($r.R)x$($r.B)，需要最大化 2880x1659" } }

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
$lvT   = Ocr 150 186 180 46
$hpT   = Ocr 340 92 200 44
$mpT   = Ocr 340 166 200 38
$plvT  = Ocr 560 158 160 46
$phpT  = Ocr 750 92 200 44
# 座標行：一般在 y≈150；地圖名太長折成兩行時往下移到 y≈172（上面還壓著第二行字）→ 兩個位置都試
function Pos($t) { $m = [regex]::Match($t, '(\d{3,6})[:：.](\d+)[,，.](\d+)'); if ($m.Success) { "$($m.Groups[1].Value):$($m.Groups[2].Value),$($m.Groups[3].Value)" } else { '' } }
$posT = Ocr 2220 150 360 46 3 $false; $pos = Pos $posT
if (-not $pos) { $posT = Ocr 2250 178 300 34 3 $false; $pos = Pos $posT }
# 地圖名用地圖 ID 查 knowledge/data/tables/MapName.jsonl（OCR 讀名牌常漏字）
$mapT = ''
if ($pos -match '^(\d+):') {
  $tbl = Join-Path $PSScriptRoot '..\..\knowledge\data\tables\MapName.jsonl'
  $line = Select-String -Path $tbl -Pattern ('^\{"ID":' + $Matches[1] + ',') -Encoding UTF8 | Select-Object -First 1
  if ($line) { $mapT = ($line.Line | ConvertFrom-Json).nameTn }
}
$full.Dispose()
Out-Json ([ordered]@{
  ok = $true; level = (Lv $lvT); hp = (Num $hpT); mp = (Num $mpT)
  petLevel = (Lv $plvT); petHp = (Num $phpT)
  map = $mapT; pos = $pos; raw = @($lvT, $hpT, $mpT, $plvT, $phpT, $posT)
})
