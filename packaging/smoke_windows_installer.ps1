# Destructive only to this disposable CI runner's synthetic installation/profile.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this check only on a disposable GitHub Actions runner.' }
$version = python packaging/release.py version
$testDataRoot = Join-Path $env:LOCALAPPDATA 'FlintEye'
if (Test-Path -LiteralPath $testDataRoot) { throw 'Refusing to use an existing FlintEye profile.' }
$installDir = Join-Path $env:RUNNER_TEMP ('FlintEye installed test ' + [guid]::NewGuid().ToString('N'))
$installer = (Resolve-Path "dist/FlintEye-$version-windows-${env:APP_ARCH}-setup.exe").Path
$process = $null
$customProcess = $null
$customRoot = Join-Path $env:RUNNER_TEMP ('FlintEye custom profile ' + [guid]::NewGuid().ToString('N'))
$runKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$previousStartup=Get-ItemPropertyValue -Path $runKey -Name FlintEye -ErrorAction SilentlyContinue
if ($previousStartup) { throw 'Refusing to overwrite an existing login registration.' }
$foreignStartup='"C:\Other FlintEye copy\FlintEye.exe" --background'
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name FlintEye -Value $foreignStartup
try {
    $setup = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOSTART', ('/DIR="' + $installDir + '"')) -PassThru
    if (-not $setup.WaitForExit(180000)) { throw 'Setup timed out.' }
    if ($setup.ExitCode -ne 0) { throw "Setup exited $($setup.ExitCode)." }
    if ((Get-ItemPropertyValue -Path $runKey -Name FlintEye) -ne $foreignStartup) { throw 'Installer replaced another installation login registration.' }
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
    $listener.Start(); $customPort=$listener.LocalEndpoint.Port; $listener.Stop()
    $customProcess=Start-Process -FilePath (Join-Path $installDir 'FlintEye.exe') -WorkingDirectory $env:RUNNER_TEMP -ArgumentList @('--headless','--port',"$customPort",'--data-dir',('"'+[IO.Path]::GetFileName($customRoot)+'"')) -PassThru
    for($attempt=0;$attempt -lt 90;$attempt++) {
        if((Test-Path -LiteralPath (Join-Path $customRoot 'instance-control.json')) -and
           (Test-Path -LiteralPath (Join-Path $testDataRoot ("running\"+$customProcess.Id+'.json')))) { break }
        if($customProcess.HasExited) { throw 'Custom-profile process exited early.' }
        Start-Sleep -Milliseconds 250
    }
    $registration=Get-Content -LiteralPath (Join-Path $testDataRoot ("running\"+$customProcess.Id+'.json')) -Raw | ConvertFrom-Json
    if($registration.profile -ne $customRoot) { throw 'Relative profile was not registered with its actual absolute location.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File packaging/stop_windows.ps1 -InstallDir $installDir -DataDir $customRoot -TimeoutSeconds 30
    if($LASTEXITCODE -ne 0 -or -not $customProcess.WaitForExit(10000)) { throw 'Custom-profile shutdown failed.' }
    if($process.HasExited) { throw 'Stopping one profile terminated the other profile.' }
    $customResult=Get-Content -LiteralPath (Join-Path $customRoot 'last-stop-result.json') -Raw | ConvertFrom-Json
    if($customResult.mode -ne 'requested-shutdown-completed') { throw 'Custom profile required force.' }
    $marker = Join-Path $testDataRoot 'keep-after-uninstall.txt'
    Set-Content -LiteralPath $marker -Value 'Synthetic recording/config retention marker'
    $uninstall = Start-Process -FilePath (Join-Path $installDir 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru
    if (-not $uninstall.WaitForExit(180000)) { throw 'Uninstall timed out.' }
    if ($uninstall.ExitCode -ne 0) { throw "Uninstall exited $($uninstall.ExitCode)." }
    if ((Get-ItemPropertyValue -Path $runKey -Name FlintEye) -ne $foreignStartup) { throw 'Uninstall removed another installation login registration.' }
    if (-not $process.WaitForExit(45000)) { throw 'API process survived uninstall.' }
    $connected = $false
    try { $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 2; $connected = $true } catch {}
    if ($connected) { throw 'API still responds after uninstall.' }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Uninstall removed retained user data.' }
    if (Test-Path -LiteralPath (Join-Path $installDir 'FlintEye.exe')) { throw 'Application was not removed.' }
    if (Test-Path -LiteralPath (Join-Path $installDir '_internal')) { throw 'Bundled runtime/media were not removed.' }
    if (Test-Path -LiteralPath (Join-Path $testDataRoot 'instance-control.json')) { throw 'Graceful shutdown did not clean its control file.' }
    $stopResult=Get-Content -LiteralPath (Join-Path $testDataRoot 'last-stop-result.json') -Raw | ConvertFrom-Json
    if($stopResult.mode -ne 'requested-shutdown-completed') { throw 'Installer smoke required forced parent termination.' }
    Write-Host 'PASS: Windows setup, active API shutdown, bundled-file uninstall and default data retention.'
} finally {
    if ((Get-ItemPropertyValue -Path $runKey -Name FlintEye -ErrorAction SilentlyContinue) -eq $foreignStartup) {
        Remove-ItemProperty -Path $runKey -Name FlintEye
    }
    if ($customProcess -and -not $customProcess.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $customProcess.Id /T /F | Out-Null
    }
    if ($process -and -not $process.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
    }
    # Only the synthetic profile created after the absence check above.
    if (Test-Path -LiteralPath $testDataRoot) { Remove-Item -LiteralPath $testDataRoot -Recurse -Force }
    if (Test-Path -LiteralPath $customRoot) { Remove-Item -LiteralPath $customRoot -Recurse -Force }
}
