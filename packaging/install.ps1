# Release assets replace the version marker. Compatible with Windows PowerShell 5.1.
param(
    [string]$Version = '@RELEASE_VERSION@',
    [string]$PackageDirectory,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
if ($Version -cnotmatch '^[0-9]+\.[0-9]+\.[0-9]+(-preview\.[1-9][0-9]{0,5})?$') { throw 'Use a published release or pass -Version X.Y.Z[-preview.N].' }
$applicationVersion = $Version -replace '-preview\.[0-9]+$', ''
if ($Version -like '*-preview.*') { Write-Host "FlintEye $Version -- UNDER DEVELOPMENT; this is not a stable release." }
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Use install.sh on macOS/Linux.' }
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19045) { throw 'Windows 10 22H2 or Windows 11 is required.' }
$architecture = $env:PROCESSOR_ARCHITEW6432
if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
# Check the host architecture even in an emulated PowerShell process.
$hostArchitecture = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').PROCESSOR_ARCHITECTURE
if ($hostArchitecture) { $architecture = $hostArchitecture }
switch ($architecture.ToUpperInvariant()) {
    'AMD64' { $arch = 'amd64' }
    'ARM64' { $arch = 'arm64' }
    default { throw 'Only 64-bit Intel/AMD and ARM computers are supported.' }
}
if (Get-Process -Name FlintEye -ErrorAction SilentlyContinue) { throw 'Quit FlintEye using Stop monitoring and quit, then retry.' }
$asset = "FlintEye-$applicationVersion-windows-$arch-setup.exe"
$base = "https://github.com/noguhiro2002/FlintEye/releases/download/v$Version"
$work = Join-Path ([IO.Path]::GetTempPath()) ('flinteye-install-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($work) | Out-Null
$previousProtocol = [Net.ServicePointManager]::SecurityProtocol
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if ($PackageDirectory) {
        $packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
        $sums = Get-Content -LiteralPath (Join-Path $packageRoot 'SHA256SUMS') -Raw
        Write-Host 'Installing from explicitly selected validation artifacts; no release download will occur.'
    } else {
        $sums = (Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS").Content
    }
    if ($sums -is [byte[]]) { $sums = [Text.Encoding]::UTF8.GetString($sums) }
    $pattern = '^([a-f0-9]{64})  ' + [regex]::Escape($asset) + '$'
    $matchesFound = @($sums -split '\r?\n' | Where-Object { $_ -match $pattern })
    if ($matchesFound.Count -ne 1) { throw 'Package checksum is missing or ambiguous.' }
    $expected = $matchesFound[0].Substring(0, 64)
    $installer = Join-Path $work $asset
    if ($PackageDirectory) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $asset) -Destination $installer
    } else {
        Invoke-WebRequest -UseBasicParsing "$base/$asset" -OutFile $installer
    }
    if ((Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant() -ne $expected) { throw 'Checksum mismatch. Nothing was installed.' }
    # Mark the downloaded installer as Internet-origin; do not bypass SmartScreen.
    Set-Content -LiteralPath $installer -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3" -ErrorAction Stop
    $arguments = @('/CURRENTUSER')
    if ($NoStart) { $arguments += '/NOSTART' }
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer exited with code $($process.ExitCode)." }
    Write-Host "Installed FlintEye $Version. Open it from the Start menu."
} finally {
    [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
