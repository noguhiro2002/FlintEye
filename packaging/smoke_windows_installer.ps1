# Destructive only to this disposable CI runner's synthetic installation/profile.
param([switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this check only on a disposable GitHub Actions runner.' }
function Get-StartupCommand {
    # Get-ItemPropertyValue throws for an absent value even with SilentlyContinue.
    # The registry API returns the supplied default for an absent key or value.
    [Microsoft.Win32.Registry]::GetValue('HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run', 'FlintEye', $null)
}
$testDataRoot = Join-Path $env:LOCALAPPDATA 'FlintEye'
if (Test-Path -LiteralPath $testDataRoot) {
    # The preceding frozen-bundle smoke checks use isolated profiles, but their
    # discovery index can leave this one empty directory in the default root.
    # Accept only that exact empty skeleton, never settings or a live index.
    $rootItem=Get-Item -LiteralPath $testDataRoot -Force
    $entries=@(Get-ChildItem -LiteralPath $testDataRoot -Force)
    if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $entries.Count -ne 1 -or $entries[0].Name -ne 'running' -or -not $entries[0].PSIsContainer -or
        ($entries[0].Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @(Get-ChildItem -LiteralPath $entries[0].FullName -Force).Count -ne 0) {
        throw 'Refusing to use an existing FlintEye profile.'
    }
}
$runKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$previousStartup=Get-StartupCommand
if ($null -ne $previousStartup) { throw 'Refusing to overwrite an existing login registration.' }
if ($PreflightOnly) {
    Write-Host 'PASS: installer test preparation accepts a clean runner without login registration.'
    return
}
$version = python packaging/release.py version
$installDir = Join-Path $env:RUNNER_TEMP ('FlintEye installed test ' + [guid]::NewGuid().ToString('N'))
$installer = (Resolve-Path "dist/FlintEye-$version-windows-${env:APP_ARCH}-setup.exe").Path
$process = $null
$customProcess = $null
$customRoot = Join-Path $env:RUNNER_TEMP ('FlintEye custom profile ' + [guid]::NewGuid().ToString('N'))
$foreignStartup='"C:\Other FlintEye copy\FlintEye.exe" --background'
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name FlintEye -Value $foreignStartup
try {
    $setup = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOSTART', ('/DIR="' + $installDir + '"')) -PassThru
    if (-not $setup.WaitForExit(180000)) { throw 'Setup timed out.' }
    if ($setup.ExitCode -ne 0) { throw "Setup exited $($setup.ExitCode)." }
    if ((Get-StartupCommand) -ne $foreignStartup) { throw 'Installer replaced another installation login registration.' }
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
    $customReady=$false
    for($attempt=0;$attempt -lt 90;$attempt++) {
        if($customProcess.HasExited) { throw 'Custom-profile process exited early.' }
        try { $response=Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$customPort/api/v1/health" -TimeoutSec 2; $customReady=$response.StatusCode -eq 200 } catch {}
        if($customReady -and (Test-Path -LiteralPath (Join-Path $customRoot 'instance-control.json')) -and
           (Test-Path -LiteralPath (Join-Path $testDataRoot ("running\"+$customProcess.Id+'.json')))) { break }
        Start-Sleep -Seconds 1
    }
    if(-not $customReady) { throw 'Custom-profile API did not become ready.' }
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
    if ((Get-StartupCommand) -ne $foreignStartup) { throw 'Uninstall removed another installation login registration.' }
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
    if ((Get-StartupCommand) -eq $foreignStartup) {
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
