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
$taskPyInstallerArgs = @('--noconfirm', '--clean', '--windowed', '--onedir', '--name', 'ClipboardAI',
    '--distpath', (Join-Path $taskRoot 'dist\windows'), '--workpath', (Join-Path $taskEnv 'work'),
    '--specpath', $taskEnv, '--paths', (Join-Path $taskRoot 'desktop\src'))
# The Codex-bundled Python patches ssl.py to load this adjacent certificate.
# A standard Python build has no such file and needs no extra data.
$taskSslPath = & $taskBuildPython -c 'import ssl; print(ssl.__file__)'
$taskCaPath = Join-Path (Split-Path -Parent $taskSslPath) 'codex-rejected-cas.pem'
if (Test-Path -LiteralPath $taskCaPath) {
    $taskPyInstallerArgs += @('--add-data', "$taskCaPath;.")
}
$taskPyInstallerArgs += (Join-Path $taskRoot 'scripts\run_gui.py')
& $taskBuildPython -m PyInstaller @taskPyInstallerArgs
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
$taskPrivateNames = @('server.pem', 'server-key.pem', 'ai.json', 'desktop.ini',
    'desktop.lock', 'pairing.html', 'debug.keystore', '.env')
$taskPackageFiles = Get-ChildItem -LiteralPath (Join-Path $taskRoot 'dist\windows\ClipboardAI') -Recurse -File
$taskPrivateFiles = @($taskPackageFiles | Where-Object {
    $_.Name -in $taskPrivateNames -or
    $_.Extension -in @('.sqlite', '.sqlite3', '.db', '.key', '.p12', '.pfx', '.keystore') -or
    ($_.Extension -eq '.pem' -and $_.Name -notin @('cacert.pem', 'codex-rejected-cas.pem'))
})
if ($taskPrivateFiles.Count) {
    throw 'El paquete contiene archivos de configuración o vinculación personales. No se generará el instalador.'
}
Write-Host "Ejecutable: $taskExe"
$taskSmokeData = Join-Path $taskEnv ('smoke-' + [guid]::NewGuid().ToString('N'))
$taskSmokeArgs = @('--data-dir', ('"' + $taskSmokeData + '"'), '--bind', '127.0.0.1', '--port', '0', '--background')
$taskSmokeProcess = Start-Process -FilePath $taskExe -ArgumentList $taskSmokeArgs -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 4
    $taskSmokeProcess.Refresh()
    if ($taskSmokeProcess.HasExited -or
        (Test-Path -LiteralPath (Join-Path $taskSmokeData 'startup-error.log')) -or
        -not (Test-Path -LiteralPath (Join-Path $taskSmokeData 'Dock\files.sqlite3'))) {
        throw 'El ejecutable no inició el cerebro en la prueba temporal. Revisa startup-error.log en la carpeta de prueba.'
    }
    Write-Host 'Arranque del cerebro: verificado con datos temporales.'
} finally {
    $taskSmokeProcess.Refresh()
    if (-not $taskSmokeProcess.HasExited) { Stop-Process -Id $taskSmokeProcess.Id -Force }
}
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
