param([string]$Address = '', [switch]$Terminal, [string]$DataDir = '', [int]$Port = 45821)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPythonCandidates = @(
    (Join-Path $taskRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
)
$taskPython = $taskPythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $taskPython) {
    $taskCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($taskCommand -and $taskCommand.Source -notlike '*WindowsApps*') { $taskPython = $taskCommand.Source }
}
if (-not $taskPython) { throw 'No se encontró Python. Instala Python 3.11 o posterior y las dependencias indicadas en README.md.' }
$env:PYTHONUTF8 = '1'
if ($Terminal) {
    $taskArguments = @((Join-Path $taskRoot 'scripts\run_desktop.py'))
    if ($Address) { $taskArguments += @('--advertise', $Address) }
    if ($DataDir) { $taskArguments += @('--data-dir', $DataDir) }
    $taskArguments += @('--port', $Port)
    & $taskPython @taskArguments
    exit $LASTEXITCODE
}
$taskWindowedPython = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $taskWindowedPython)) { $taskWindowedPython = $taskPython }
$taskArguments = @(('"{0}"' -f (Join-Path $taskRoot 'scripts\run_gui.py')))
if ($Address) {
    if ($Address -notmatch '^[a-zA-Z0-9.:_-]+$') { throw 'Escribe una dirección IP o nombre de equipo válido.' }
    $taskArguments += @('--advertise', $Address)
}
if ($DataDir) {
    if ($DataDir.Contains('"') -or $DataDir.EndsWith('\')) { throw 'La carpeta de datos no debe contener comillas ni terminar en barra.' }
    $taskArguments += @('--data-dir', ('"{0}"' -f $DataDir))
}
$taskArguments += @('--port', $Port)
Start-Process -FilePath $taskWindowedPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden
