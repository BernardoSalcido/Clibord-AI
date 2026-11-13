$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
$env:PYTHONPATH = "$(Join-Path $taskRoot '.deps');$(Join-Path $taskRoot 'desktop\src')"
$env:PYTHONUTF8 = '1'
$taskTests = Join-Path $taskRoot '.test-data'
New-Item -ItemType Directory -Path $taskTests -Force | Out-Null
$taskRun = Join-Path $taskTests ([guid]::NewGuid().ToString())
& $taskPython -m pytest (Join-Path $taskRoot 'desktop\tests') -q --basetemp $taskRun
exit $LASTEXITCODE
