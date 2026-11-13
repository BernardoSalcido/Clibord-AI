param([switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = (Get-Command python -ErrorAction Stop).Source
    if ($taskPython -like '*WindowsApps*') { throw 'Instala Python 3.11 o posterior desde python.org.' }
}
$taskEnv = Join-Path $env:TEMP 'ClipboardAI-Windows-Build'
if (-not (Test-Path -LiteralPath (Join-Path $taskEnv 'Scripts\python.exe'))) {
    & $taskPython -m venv $taskEnv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de compilación.' }
}
$taskBuildPython = Join-Path $taskEnv 'Scripts\python.exe'
& $taskBuildPython -m pip install --disable-pip-version-check -e "$(Join-Path $taskRoot 'desktop')[gui]" 'pyinstaller>=6,<7'
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de compilación.' }
& $taskBuildPython -m PyInstaller --noconfirm --clean --windowed --onedir --name ClipboardAI --distpath (Join-Path $taskRoot 'dist\windows') --workpath (Join-Path $taskEnv 'work') --specpath $taskEnv --paths (Join-Path $taskRoot 'desktop\src') (Join-Path $taskRoot 'scripts\run_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller no pudo generar el ejecutable.' }
$taskExe = Join-Path $taskRoot 'dist\windows\ClipboardAI\ClipboardAI.exe'
if (-not (Test-Path -LiteralPath $taskExe)) { throw 'No se generó ClipboardAI.exe.' }
# The bundled ICU 78 exports suffixed symbols, while QtCore requires the
# unsuffixed Windows ICU ABI. Use the OS copy that PySide6 uses in Python.
$taskInternal = Join-Path $taskRoot 'dist\windows\ClipboardAI\_internal'
foreach ($taskName in @('icuuc.dll', 'icudt78.dll')) {
    $taskBundledIcu = Join-Path $taskInternal $taskName
    if (Test-Path -LiteralPath $taskBundledIcu) {
        Remove-Item -LiteralPath $taskBundledIcu
    }
}
Write-Host "Ejecutable: $taskExe"
if (-not $SkipInstaller) {
    $taskIscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $taskIscc) { $taskIscc = Get-Item 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' -ErrorAction SilentlyContinue }
    if (-not $taskIscc) { $taskIscc = Get-Item (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe') -ErrorAction SilentlyContinue }
    if ($taskIscc) {
        $taskIsccPath = if ($taskIscc -is [System.Management.Automation.CommandInfo]) { $taskIscc.Source } else { $taskIscc.FullName }
        & $taskIsccPath (Join-Path $taskRoot 'packaging\windows\ClipboardAI.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup no pudo crear el instalador.' }
    } else {
        Write-Warning 'Inno Setup 6 no está instalado. El ejecutable portable está listo; instala Inno Setup y vuelve a ejecutar para crear Setup.exe.'
    }
}
