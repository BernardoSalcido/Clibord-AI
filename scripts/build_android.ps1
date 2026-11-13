param([switch]$Check)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskConfig = Join-Path $taskRoot '.tools\android-env.json'
if (-not (Test-Path -LiteralPath $taskConfig)) {
    throw 'Primero prepara el entorno con scripts/prepare_android.py o usa Android Studio.'
}
$taskEnvironment = Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
$env:JAVA_HOME = $taskEnvironment.java
$env:ANDROID_HOME = $taskEnvironment.sdk
$env:GRADLE_USER_HOME = Join-Path $taskRoot '.tools\gradle-home'
$env:ANDROID_USER_HOME = Join-Path $taskRoot '.tools\android-home'
$env:PATH = "$($taskEnvironment.java)\bin;$env:PATH"
$taskKeyStore = Join-Path $taskRoot '.tools\debug.keystore'
if (-not (Test-Path -LiteralPath $taskKeyStore)) {
    & (Join-Path $taskEnvironment.java 'bin\keytool.exe') -genkeypair -keystore $taskKeyStore -storepass android -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Android Debug,O=Clipboard AI,C=DE'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$taskArguments = @('--no-daemon', '--console=plain', '-p', (Join-Path $taskRoot 'android'), 'assembleAndroidDebug', 'assembleHarmonyDebug')
if ($Check) { $taskArguments += @('testAndroidDebugUnitTest', 'testHarmonyDebugUnitTest', 'lintAndroidDebug', 'lintHarmonyDebug') }
& $taskEnvironment.gradle @taskArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskOutput = Join-Path $taskRoot 'dist'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $taskRoot 'android\app\build\outputs\apk\android\debug\app-android-debug.apk') -Destination (Join-Path $taskOutput 'ClipboardAI-Android-0.3.9-debug.apk')
Copy-Item -LiteralPath (Join-Path $taskRoot 'android\app\build\outputs\apk\harmony\debug\app-harmony-debug.apk') -Destination (Join-Path $taskOutput 'ClipboardAI-Harmony-0.3.9-debug.apk')
Write-Host "APK Android: $taskOutput\ClipboardAI-Android-0.3.9-debug.apk"
Write-Host "APK HarmonyOS: $taskOutput\ClipboardAI-Harmony-0.3.9-debug.apk"
