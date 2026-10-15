# 二值化新舊逐位元組比對（離線，不碰遊戲）：從 ocr.ps1 / stat.ps1 取出實際的 Add-Type C# 原始碼編譯，
# 與本檔內的「舊版 GetPixel/SetPixel 參考實作」比對 LockBits 版的完整 ARGB 位元組。
# 用法：由 test_binarize.py 呼叫；也可直接 powershell -File test_binarize.ps1 [樣本圖.png ...]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Samples)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
function Load-Cs($file) {
  $t = [IO.File]::ReadAllText((Join-Path $PSScriptRoot $file), [Text.Encoding]::UTF8)
  $m = [regex]::Match($t, '(?s)Add-Type @"\r?\n(.*?)\r?\n"@')
  if (-not $m.Success) { throw "$file 找不到 Add-Type 區塊" }
  Add-Type -TypeDefinition $m.Groups[1].Value -ReferencedAssemblies System.Drawing
}
Load-Cs 'ocr.ps1'
Load-Cs 'stat.ps1'
# 舊版參考實作（2026-10-10 以前 ocr.ps1 / stat.ps1 的 GetPixel/SetPixel 迴圈）
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System; using System.Drawing;
public class RefBin {
  public static void Light(Bitmap b, int light) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); int mn = Math.Min(c.R, Math.Min(c.G, c.B));
      b.SetPixel(x, y, mn > light ? Color.Black : Color.White); } }
  public static void Dark(Bitmap b, int dark) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); int mx = Math.Max(c.R, Math.Max(c.G, c.B));
      b.SetPixel(x, y, mx < dark ? Color.Black : Color.White); } }
  // 2026-10-15 以前 ocr.ps1 的 BinarizeGreen（GetPixel 版）
  public static void Green(Bitmap b, int th) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); bool ink = c.G > th && c.G - c.R > 50 && c.G - c.B > 90;
      b.SetPixel(x, y, ink ? Color.Black : Color.White); } }
  // -Key 參考：與任一組 (r,g,b,tol) 各通道差都 <= tol 為字
  public static void Key(Bitmap b, int[] k) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); bool ink = false;
      for (int i = 0; i + 3 < k.Length; i += 4)
        if (Math.Abs(c.R - k[i]) <= k[i + 3] && Math.Abs(c.G - k[i + 1]) <= k[i + 3] && Math.Abs(c.B - k[i + 2]) <= k[i + 3]) ink = true;
      b.SetPixel(x, y, ink ? Color.Black : Color.White); } }
  public static void Stat(Bitmap b, bool light) {
    for (int y = 0; y < b.Height; y++) for (int x = 0; x < b.Width; x++) {
      var c = b.GetPixel(x, y); int mx = Math.Max(c.R, Math.Max(c.G, c.B)), mn = Math.Min(c.R, Math.Min(c.G, c.B));
      bool ink = light ? (mn > 190 && mx - mn < 40) : (mx < 110);
      b.SetPixel(x, y, ink ? Color.Black : Color.White); } }
}
"@
$script:fail = 0; $script:n = 0
function Bytes($b) {
  $d = $b.LockBits((New-Object System.Drawing.Rectangle 0, 0, $b.Width, $b.Height), 'ReadOnly', 'Format32bppArgb')
  $buf = New-Object byte[] ($d.Stride * $b.Height); [Runtime.InteropServices.Marshal]::Copy($d.Scan0, $buf, 0, $buf.Length); $b.UnlockBits($d); $buf
}
function Clone32($b, $fmt = 'Format32bppArgb') {
  $o = New-Object System.Drawing.Bitmap $b.Width, $b.Height, ([System.Drawing.Imaging.PixelFormat]$fmt)
  $g = [System.Drawing.Graphics]::FromImage($o); $g.DrawImageUnscaled($b, 0, 0); $g.Dispose(); $o
}
# 直接寫 ARGB（Graphics 會預乘 / 合成，所以合成圖用 SetPixel 精確設 alpha）
function Synth($pixels) {   # $pixels = @( @(a,r,g,b), ... ) 排成一列
  $bm = New-Object System.Drawing.Bitmap $pixels.Count, 1, ([System.Drawing.Imaging.PixelFormat]'Format32bppArgb')
  for ($i = 0; $i -lt $pixels.Count; $i++) { $p = $pixels[$i]; $bm.SetPixel($i, 0, [System.Drawing.Color]::FromArgb($p[0], $p[1], $p[2], $p[3])) }
  $bm
}
function Cmp($name, $src, [scriptblock]$new, [scriptblock]$old) {
  $a = Clone-Exact $src; $b = Clone-Exact $src
  & $new $a; & $old $b
  $x = Bytes $a; $y = Bytes $b; $same = ($x.Length -eq $y.Length)
  if ($same) { for ($i = 0; $i -lt $x.Length; $i++) { if ($x[$i] -ne $y[$i]) { $same = $false; break } } }
  $script:n++
  if ($same) { "PASS $name ($($src.Width)x$($src.Height), $($x.Length) bytes)" } else { $script:fail++; "FAIL $name" }
  $a.Dispose(); $b.Dispose()
}
function Clone-Exact($src) { $src.Clone((New-Object System.Drawing.Rectangle 0, 0, $src.Width, $src.Height), $src.PixelFormat) }

# ---- 合成邊界圖 ----
$vals = 0, 1, 40, 100, 108, 109, 110, 111, 148, 149, 150, 151, 189, 190, 191, 198, 199, 200, 201, 220, 254, 255
# ocr Dark 150：max = 149 / 150 / 151（三個通道輪流當最大值）；Light 200：min = 199 / 200 / 201
$px = @()
foreach ($m in 148, 149, 150, 151, 152) { $px += , @(255, $m, 10, 10); $px += , @(255, 10, $m, 10); $px += , @(255, 10, 10, $m); $px += , @(255, $m, $m, $m) }
foreach ($m in 198, 199, 200, 201, 202) { $px += , @(255, $m, 255, 255); $px += , @(255, 255, $m, 255); $px += , @(255, 255, 255, $m) }
Cmp 'ocr Dark150 邊界 max=148..152' (Synth $px) { param($b) [WO2]::Binarize($b, 150) } { param($b) [RefBin]::Dark($b, 150) }
Cmp 'ocr Light200 邊界 min=198..202' (Synth $px) { param($b) [WO2]::BinarizeLight($b, 200) } { param($b) [RefBin]::Light($b, 200) }
# Green 120：G = 120 / 121、G-R = 50 / 51、G-B = 90 / 91；Key (240,220,0,50)+(245,245,245,45)：各通道差 = tol / tol+1
$px = @()
foreach ($gv in 119, 120, 121, 122, 200) { foreach ($d in 49, 50, 51) { $px += , @(255, ($gv - $d), $gv, 0); $px += , @(255, 0, $gv, ($gv - $d - 40)) } }
foreach ($d in 49, 50, 51) { $px += , @(255, (240 - $d), 220, 0); $px += , @(255, 240, (220 - $d), 0); $px += , @(255, 240, 220, $d); $px += , @(255, 245, 245, (245 - $d + 5)) }
$script:keys = [int[]]@(240, 220, 0, 50, 245, 245, 245, 45)
Cmp 'ocr Green120 邊界' (Synth $px) { param($b) [WO2]::BinarizeGreen($b, 120) } { param($b) [RefBin]::Green($b, 120) }
Cmp 'ocr Key 邊界' (Synth $px) { param($b) [WO2]::BinarizeKey($b, $script:keys) } { param($b) [RefBin]::Key($b, $script:keys) }
# stat：mn = 190 / 191、mx−mn = 39 / 40、mx = 109 / 110
$px = @()
foreach ($mn in 189, 190, 191, 192) { foreach ($d in 0, 38, 39, 40, 41) { $px += , @(255, $mn, ($mn + $d), $mn); $px += , @(255, ($mn + $d), $mn, ($mn + $d)); $px += , @(255, $mn, $mn, ($mn + $d)) } }
foreach ($mx in 108, 109, 110, 111) { $px += , @(255, $mx, 0, 0); $px += , @(255, 0, $mx, 0); $px += , @(255, 0, 0, $mx); $px += , @(255, $mx, $mx, $mx) }
Cmp 'stat light 邊界 (mn 190/191, mx-mn 39/40)' (Synth $px) { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }
Cmp 'stat dark 邊界 (mx 109/110)' (Synth $px) { param($b) [WS]::Binarize($b, $false) } { param($b) [RefBin]::Stat($b, $false) }
# alpha < 255（推測 HighQualityBicubic 放大後邊緣可能半透明）：所有輸入通道值 × 數種 alpha
$px = @()
foreach ($a in 0, 1, 127, 128, 254, 255) { foreach ($v in $vals) { $px += , @($a, $v, $v, $v); $px += , @($a, $v, (255 - $v), 7) } }
Cmp 'ocr Dark150 alpha<255' (Synth $px) { param($b) [WO2]::Binarize($b, 150) } { param($b) [RefBin]::Dark($b, 150) }
Cmp 'ocr Light200 alpha<255' (Synth $px) { param($b) [WO2]::BinarizeLight($b, 200) } { param($b) [RefBin]::Light($b, 200) }
Cmp 'stat light alpha<255' (Synth $px) { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }
Cmp 'stat dark alpha<255' (Synth $px) { param($b) [WS]::Binarize($b, $false) } { param($b) [RefBin]::Stat($b, $false) }

# ---- 隨機雜訊（固定種子；含隨機 alpha、寬度不是 4 的倍數）----
$rnd = New-Object Random 12345
$bm = New-Object System.Drawing.Bitmap 97, 61, ([System.Drawing.Imaging.PixelFormat]'Format32bppArgb')
for ($y = 0; $y -lt 61; $y++) { for ($x = 0; $x -lt 97; $x++) {
  $bm.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($rnd.Next(0, 256), $rnd.Next(0, 256), $rnd.Next(0, 256), $rnd.Next(0, 256))) } }
Cmp 'ocr Dark 隨機' $bm { param($b) [WO2]::Binarize($b, 150) } { param($b) [RefBin]::Dark($b, 150) }
Cmp 'ocr Light 隨機' $bm { param($b) [WO2]::BinarizeLight($b, 200) } { param($b) [RefBin]::Light($b, 200) }
Cmp 'ocr Green 隨機' $bm { param($b) [WO2]::BinarizeGreen($b, 120) } { param($b) [RefBin]::Green($b, 120) }
Cmp 'ocr Key 隨機' $bm { param($b) [WO2]::BinarizeKey($b, $script:keys) } { param($b) [RefBin]::Key($b, $script:keys) }
Cmp 'stat light 隨機' $bm { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }
Cmp 'stat dark 隨機' $bm { param($b) [WS]::Binarize($b, $false) } { param($b) [RefBin]::Stat($b, $false) }
# 亮灰區塊（stat light 的 mx-mn 與 mn 同時落在邊界附近）
$bm2 = New-Object System.Drawing.Bitmap 64, 64, ([System.Drawing.Imaging.PixelFormat]'Format32bppArgb')
for ($y = 0; $y -lt 64; $y++) { for ($x = 0; $x -lt 64; $x++) { $bm2.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, (185 + $rnd.Next(0, 12)), (185 + $rnd.Next(0, 12)), (185 + $rnd.Next(0, 12)))) } }
Cmp 'stat light 近邊界雜訊' $bm2 { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }

# ---- 非 32bppArgb 輸入走 GetPixel 退路（不丟例外、結果與參考一致）----
foreach ($fmt in 'Format24bppRgb', 'Format32bppPArgb', 'Format32bppRgb') {
  $o = New-Object System.Drawing.Bitmap 40, 20, ([System.Drawing.Imaging.PixelFormat]$fmt)
  for ($y = 0; $y -lt 20; $y++) { for ($x = 0; $x -lt 40; $x++) { $o.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, $rnd.Next(0, 256), $rnd.Next(0, 256), $rnd.Next(0, 256))) } }
  Cmp "ocr Dark 退路 $fmt" $o { param($b) [WO2]::Binarize($b, 150) } { param($b) [RefBin]::Dark($b, 150) }
  Cmp "ocr Light 退路 $fmt" $o { param($b) [WO2]::BinarizeLight($b, 200) } { param($b) [RefBin]::Light($b, 200) }
  Cmp "ocr Green 退路 $fmt" $o { param($b) [WO2]::BinarizeGreen($b, 120) } { param($b) [RefBin]::Green($b, 120) }
  Cmp "stat light 退路 $fmt" $o { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }
  Cmp "stat dark 退路 $fmt" $o { param($b) [WS]::Binarize($b, $false) } { param($b) [RefBin]::Stat($b, $false) }
  $o.Dispose()
}

# ---- 離線樣本（gui shot 存的 PNG；縮放後用 HighQualityBicubic 放大 3 倍，模擬 OCR 前處理）----
foreach ($f in $Samples) {
  if (-not (Test-Path $f)) { continue }
  $img = [System.Drawing.Image]::FromFile($f)
  $w = [Math]::Min(260, $img.Width); $h = [Math]::Min(180, $img.Height)
  foreach ($z in 2, 3) {
    $crop = New-Object System.Drawing.Bitmap ($w * $z), ($h * $z)
    $g = [System.Drawing.Graphics]::FromImage($crop); $g.InterpolationMode = 'HighQualityBicubic'
    $g.DrawImage($img, (New-Object System.Drawing.Rectangle 0, 0, $crop.Width, $crop.Height), 0, 0, $w, $h, 'Pixel'); $g.Dispose()
    $nm = [IO.Path]::GetFileName($f) + " x$z"
    Cmp "樣本 $nm ocr Dark" $crop { param($b) [WO2]::Binarize($b, 150) } { param($b) [RefBin]::Dark($b, 150) }
    Cmp "樣本 $nm ocr Light" $crop { param($b) [WO2]::BinarizeLight($b, 200) } { param($b) [RefBin]::Light($b, 200) }
    Cmp "樣本 $nm ocr Green" $crop { param($b) [WO2]::BinarizeGreen($b, 120) } { param($b) [RefBin]::Green($b, 120) }
    Cmp "樣本 $nm ocr Key" $crop { param($b) [WO2]::BinarizeKey($b, $script:keys) } { param($b) [RefBin]::Key($b, $script:keys) }
    Cmp "樣本 $nm stat light" $crop { param($b) [WS]::Binarize($b, $true) } { param($b) [RefBin]::Stat($b, $true) }
    Cmp "樣本 $nm stat dark" $crop { param($b) [WS]::Binarize($b, $false) } { param($b) [RefBin]::Stat($b, $false) }
    $crop.Dispose()
  }
  $img.Dispose()
}
"SUMMARY $($script:n - $script:fail)/$($script:n) 通過"
exit $(if ($script:fail) { 1 } else { 0 })
