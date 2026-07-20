# Creates a "Claude Launcher" desktop shortcut that runs the app from its
# virtual environment (no console window), with the custom icon.
# Run once:  right-click > "Run with PowerShell", or:  powershell -File make_shortcut.ps1

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$mainPy = Join-Path $appDir 'main.py'
$icon   = Join-Path $appDir 'claude_launcher.ico'
$venv   = Join-Path $appDir '.venv'
$vpy    = Join-Path $venv 'Scripts\python.exe'
$vpyw   = Join-Path $venv 'Scripts\pythonw.exe'

# Ensure the venv exists (run.bat builds the same one on first launch).
if (-not (Test-Path $vpyw)) {
    Write-Host 'Virtual environment not found - creating it...'
    $py = $null
    foreach ($c in 'py', 'python', 'python3') {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source; break }
    }
    if (-not $py) {
        Write-Error 'Could not find Python (py/python/python3) on PATH. Install Python 3.8+ first.'
        exit 1
    }
    & $py -m venv $venv
    & $vpy -m pip install --upgrade pip
    & $vpy -m pip install -r (Join-Path $appDir 'requirements.txt')
}
if (-not (Test-Path $vpyw)) {
    Write-Error 'Failed to create the virtual environment.'
    exit 1
}

# Generate the icon if it's somehow missing (Pillow is in requirements.txt).
if (-not (Test-Path $icon)) {
    Write-Host 'Icon not found - generating it...'
    & $vpy (Join-Path $appDir 'generate_icon.py')
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'Claude Launcher.lnk'

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnkPath)
$sc.TargetPath       = $vpyw
$sc.Arguments        = "`"$mainPy`""
$sc.WorkingDirectory = $appDir
$sc.IconLocation     = "$icon,0"
$sc.Description       = 'Browse, create and launch Claude Code projects'
$sc.Save()

Write-Host "Created shortcut: $lnkPath"
