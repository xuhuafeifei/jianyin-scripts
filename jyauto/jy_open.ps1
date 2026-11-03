param(
  [int]$X = 441, [int]$Y = 251,
  [int]$WinH = 1400, [int]$WinY = -440,
  [string]$Out = 'F:\JYAutoEdit\data\jy_open.png', [int]$WaitMs = 14000
)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class JYO {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, IntPtr e);
}
"@
function Tall([IntPtr]$h) {
  [JYO]::ShowWindow($h, 9) | Out-Null            # SW_RESTORE: needed if maximized
  Start-Sleep -Milliseconds 250
  [JYO]::SetWindowPos($h, [IntPtr]::Zero, 0, $WinY, 1700, $WinH, 0x0004) | Out-Null
  Start-Sleep -Milliseconds 350
  [JYO]::keybd_event(0x12,0,0,[IntPtr]::Zero); [JYO]::SetForegroundWindow($h) | Out-Null; [JYO]::keybd_event(0x12,0,2,[IntPtr]::Zero)
  Start-Sleep -Milliseconds 300
}
$p = Get-Process JianyingPro -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Host "no window"; exit 1 }
$win = $p.MainWindowHandle

Tall $win
[JYO]::SetCursorPos($X, $Y) | Out-Null
Start-Sleep -Milliseconds 300
[JYO]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero); [JYO]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)
Start-Sleep -Milliseconds 90
[JYO]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero); [JYO]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)

# keep it tall while the editor loads
for ($i = 0; $i -lt [Math]::Floor($WaitMs / 1500); $i++) {
  Start-Sleep -Milliseconds 1500
  [JYO]::SetWindowPos($win, [IntPtr]::Zero, 0, $WinY, 1700, $WinH, 0x0004) | Out-Null
}
Start-Sleep -Milliseconds 800

$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host "saved $Out"
