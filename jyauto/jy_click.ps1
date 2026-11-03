param(
  [int]$X = -1, [int]$Y = -1, [string]$Out = 'F:\JYAutoEdit\data\jy_click.png',
  [int]$WaitMs = 4000, [switch]$DoubleClick, [string]$Keys = ''
)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class JY {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
}
"@
function Get-Title([IntPtr]$h) { $sb = New-Object System.Text.StringBuilder 512; [JY]::GetWindowTextW($h,$sb,512) | Out-Null; $sb.ToString() }

$p = Get-Process JianyingPro -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Host "no window"; exit 1 }
$h = $p.MainWindowHandle
if ([JY]::IsIconic($h)) { [JY]::ShowWindow($h, 9) | Out-Null }
[JY]::ShowWindow($h, 3) | Out-Null
[JY]::SetWindowPos($h, [IntPtr]::Zero, 0, 0, 1700, 950, 0x0040) | Out-Null

$focused = $false
for ($i = 0; $i -lt 6; $i++) {
  [JY]::keybd_event(0x12,0,0,[IntPtr]::Zero)
  [JY]::SetForegroundWindow($h) | Out-Null
  [JY]::keybd_event(0x12,0,2,[IntPtr]::Zero)
  Start-Sleep -Milliseconds 400
  if ([JY]::GetForegroundWindow() -eq $h) { $focused = $true; break }
  # attach input queues for the stubborn case
  $fg = [JY]::GetForegroundWindow()
  $null = 0
  $t1 = [JY]::GetWindowThreadProcessId($fg, [ref]$null)
  $t2 = [JY]::GetWindowThreadProcessId($h, [ref]$null)
  [JY]::AttachThreadInput($t1, $t2, $true) | Out-Null
  [JY]::SetForegroundWindow($h) | Out-Null
  [JY]::AttachThreadInput($t1, $t2, $false) | Out-Null
  Start-Sleep -Milliseconds 300
  if ([JY]::GetForegroundWindow() -eq $h) { $focused = $true; break }
}
Write-Host "focused=$focused title='$((Get-Title $h))'"
if (-not $focused) { Write-Host "ABORT: could not focus 剪映, not clicking"; exit 2 }

Start-Sleep -Milliseconds 500
if ($X -ge 0) {
  [JY]::SetCursorPos($X, $Y) | Out-Null
  Start-Sleep -Milliseconds 250
  [JY]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero); [JY]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)
  if ($DoubleClick) {
    Start-Sleep -Milliseconds 90
    [JY]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero); [JY]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)
  }
}
if ($Keys -ne '') { Start-Sleep -Milliseconds 400; [System.Windows.Forms.SendKeys]::SendWait($Keys) }
Start-Sleep -Milliseconds $WaitMs

$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host "saved $Out ; title now '$((Get-Title $h))'"
