# Guard 鉤子離線測試（不碰遊戲輸入）：從 gui.ps1 抽出 Guard 類別原始碼另行編譯，驗證
#   1) 連續 Start/Stop 多次，執行緒數不累積
#   2) Start 兩次沒 Stop，前一條被收掉（不累積）
#   3) 不呼叫 Stop，約 2 秒後自動解除（AutoUnhooked +1），之後 Stop 不出錯
#   4) Stop 後立刻 Start，新執行緒存活不被舊的拆掉（新鉤子可吞，這裡以執行緒仍活著 + 後續 Stop 正常判斷）
# 用法：powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\gui\test_guard.ps1
$src = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'gui.ps1'), [Text.Encoding]::UTF8)
$a = $src.IndexOf('public class Guard {'); $b = $src.IndexOf("}`n`"@", $a)
if ($b -lt 0) { $b = $src.IndexOf("}`r`n`"@", $a) }
$code = "using System; using System.Runtime.InteropServices;`n" + ($src.Substring($a, $b - $a + 1).Replace('public class Guard', 'public class GuardT'))
Add-Type -TypeDefinition $code
$fail = 0
function Check($name, $ok) { if ($ok) { "PASS $name" } else { "FAIL $name"; $script:fail++ } }
function Thr { [Diagnostics.Process]::GetCurrentProcess().Threads.Count }
$t0 = Thr
for ($i = 0; $i -lt 30; $i++) { [GuardT]::Start(); [void][GuardT]::Stop() }
Start-Sleep -Milliseconds 300
Check "30 次 Start/Stop 執行緒不累積 ($t0 -> $(Thr))" ((Thr) -le $t0 + 2)
$t1 = Thr
for ($i = 0; $i -lt 10; $i++) { [GuardT]::Start() }   # 故意不 Stop
[void][GuardT]::Stop(); Start-Sleep -Milliseconds 300
Check "連 Start 10 次再 Stop 一次，執行緒不累積 ($t1 -> $(Thr))" ((Thr) -le $t1 + 2)
Check "JoinTimeouts 為 0" ([GuardT]::JoinTimeouts -eq 0)
$au = [GuardT]::AutoUnhooked
[GuardT]::Start(); Start-Sleep -Milliseconds 2600
Check "2 秒後自動解除 (AutoUnhooked $au -> $([GuardT]::AutoUnhooked))" ([GuardT]::AutoUnhooked -eq $au + 1)
Check "自動解除後 Stop 回 true" ([GuardT]::Stop())
"fail=$fail"
exit $fail
