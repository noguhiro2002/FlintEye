# Destructive only to this disposable CI runner's synthetic installation/profile.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this check only on a disposable GitHub Actions runner.' }
$version = python packaging/release.py version
$testDataRoot = Join-Path $env:LOCALAPPDATA 'FlintEye'
if (Test-Path -LiteralPath $testDataRoot) { throw 'Refusing to use an existing FlintEye profile.' }
$installDir = Join-Path $env:RUNNER_TEMP ('FlintEye installed test ' + [guid]::NewGuid().ToString('N'))
$installer = (Resolve-Path "dist/FlintEye-$version-windows-${env:APP_ARCH}-setup.exe").Path
$process = $null
try {
    $setup = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOSTART', ('/DIR="' + $installDir + '"')) -PassThru
    if (-not $setup.WaitForExit(180000)) { throw 'Setup timed out.' }
    if ($setup.ExitCode -ne 0) { throw "Setup exited $($setup.ExitCode)." }
    if (-not (Test-Path -LiteralPath (Join-Path $installDir 'stop_windows.ps1'))) { throw 'Shutdown helper was not installed.' }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop()
    $process = Start-Process -FilePath (Join-Path $installDir 'FlintEye.exe') -ArgumentList @('--headless','--port',"$port") -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($process.HasExited) { throw 'Installed app exited before startup.' }
        try { $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 2; $ready = $response.StatusCode -eq 200 } catch {}
        if ($ready) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Installed API did not become ready.' }
    $marker = Join-Path $testDataRoot 'keep-after-uninstall.txt'
    Set-Content -LiteralPath $marker -Value 'Synthetic recording/config retention marker'
    $uninstall = Start-Process -FilePath (Join-Path $installDir 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru
    if (-not $uninstall.WaitForExit(180000)) { throw 'Uninstall timed out.' }
    if ($uninstall.ExitCode -ne 0) { throw "Uninstall exited $($uninstall.ExitCode)." }
    if (-not $process.WaitForExit(45000)) { throw 'API process survived uninstall.' }
    $connected = $false
    try { $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 2; $connected = $true } catch {}
    if ($connected) { throw 'API still responds after uninstall.' }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Uninstall removed retained user data.' }
    if (Test-Path -LiteralPath (Join-Path $installDir 'FlintEye.exe')) { throw 'Application was not removed.' }
    if (Test-Path -LiteralPath (Join-Path $installDir '_internal')) { throw 'Bundled runtime/media were not removed.' }
    if (Test-Path -LiteralPath (Join-Path $testDataRoot 'instance-control.json')) { throw 'Graceful shutdown did not clean its control file.' }
    Write-Host 'PASS: Windows setup, active API shutdown, bundled-file uninstall and default data retention.'
} finally {
    if ($process -and -not $process.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
    }
    # Only the synthetic profile created after the absence check above.
    if (Test-Path -LiteralPath $testDataRoot) { Remove-Item -LiteralPath $testDataRoot -Recurse -Force }
}
