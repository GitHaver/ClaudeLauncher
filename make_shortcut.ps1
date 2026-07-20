# Creates a "Claude Launcher" desktop shortcut with the custom icon.
# Run once:  right-click > "Run with PowerShell", or:  powershell -File make_shortcut.ps1

$appDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$mainPy  = Join-Path $appDir 'main.py'
$icon    = Join-Path $appDir 'claude_launcher.ico'

# Prefer pythonw.exe (no console window); fall back to python.exe.
$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $pyw) { Write-Error 'Could not find pythonw.exe / python.exe on PATH.'; exit 1 }

if (-not (Test-Path $icon)) {
    Write-Host 'Icon not found - generating it...'
    & $pyw (Join-Path $appDir 'generate_icon.py')
}

$desktop  = [Environment]::GetFolderPath('Desktop')
$lnkPath  = Join-Path $desktop 'Claude Launcher.lnk'

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath       = $pyw
$sc.Arguments        = "`"$mainPy`""
$sc.WorkingDirectory = $appDir
$sc.IconLocation     = "$icon,0"
$sc.Description       = 'Browse, create and launch Claude Code projects'
$sc.Save()

Write-Host "Created shortcut: $lnkPath"
