param([string]$Mode = 'list', [long]$WindowHandle = 0, [int]$ExpectedProcess = 0)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;
public class StacksCapture {
    public delegate bool Callback(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumWindows(Callback cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    public static long[] Windows() {
        var handles = new List<long>();
        EnumWindows((h,p) => { if (IsWindowVisible(h) && !IsIconic(h)) handles.Add(h.ToInt64()); return true; }, IntPtr.Zero);
        return handles.ToArray();
    }
    public static string Title(IntPtr h) { var s = new StringBuilder(2048); GetWindowText(h,s,s.Capacity); return s.ToString(); }
    public static int Process(IntPtr h) { uint p; GetWindowThreadProcessId(h,out p); return (int)p; }
}
'@
if ($Mode -eq 'list') {
    $items = @(
        foreach ($handle in [StacksCapture]::Windows()) {
            $window = [IntPtr]::new($handle)
            $title = [StacksCapture]::Title($window)
            $processId = [StacksCapture]::Process($window)
            $processName = (Get-Process -Id $processId -ErrorAction SilentlyContinue).ProcessName
            if (!$title -or $processName -match '^(stacks|stacks-backend|powershell|pwsh)$' -or $title -eq 'Stacks Companion') { continue }
            @{handle=$handle; process_id=$processId; title=$title; application=$processName}
        }
    )
    ConvertTo-Json -InputObject $items -Depth 4 -Compress
    exit
}
$target = [IntPtr]::new($WindowHandle)
if (![StacksCapture]::IsWindowVisible($target) -or [StacksCapture]::IsIconic($target) -or [StacksCapture]::Process($target) -ne $ExpectedProcess) { throw 'That window is no longer available. Choose it again.' }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($target)
$condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::IsTextPatternAvailableProperty, $true)
$elements = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
$pieces = [System.Collections.Generic.List[string]]::new()
$limitHit = $false
$characterCount = 0
foreach ($element in $elements) {
    if ($element.Current.IsPassword) { continue }
    try {
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        if ($element.Current.ControlType -ne [System.Windows.Automation.ControlType]::Document -and $element.Current.ControlType -ne [System.Windows.Automation.ControlType]::Edit) { continue }
        if ($element.Current.Name -match '(?i)address.*bar|search.*bar|find in') { continue }
        $text = $pattern.DocumentRange.GetText(300001).Trim()
        if ($text -and !$pieces.Contains($text)) {
            $characterCount += $text.Length
            if ($characterCount -gt 300000) { $limitHit = $true; break }
            $pieces.Add($text)
        }
    } catch { }
}
$result = @{title=[StacksCapture]::Title($target); text=($pieces -join "`n`n"); image=''; limited=$limitHit}
if (!$result.text) {
    $rectangle = $root.Current.BoundingRectangle
    if ($rectangle.IsEmpty -or $rectangle.Width -gt 5000 -or $rectangle.Height -gt 4000 -or $rectangle.Width -lt 1 -or $rectangle.Height -lt 1) { throw 'That window cannot be captured. Connect a file instead.' }
    $bitmap = [System.Drawing.Bitmap]::new([int]$rectangle.Width, [int]$rectangle.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = [System.IO.MemoryStream]::new()
    try {
        $deviceContext = $graphics.GetHdc()
        try {
            if (![StacksCapture]::PrintWindow($target, $deviceContext, 2)) { throw 'This application does not support window rendering. Connect its file instead.' }
        } finally { $graphics.ReleaseHdc($deviceContext) }
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $result.image = [Convert]::ToBase64String($stream.ToArray())
    } finally { $graphics.Dispose(); $bitmap.Dispose(); $stream.Dispose() }
}
ConvertTo-Json -InputObject $result -Depth 4 -Compress
