# Stop only this user's processes from the selected FlintEye installation.
# Also usable to recover an older installation whose uninstaller left processes.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InstallDir)
$ErrorActionPreference = 'Stop'
$installRoot = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
if ([IO.Path]::GetPathRoot($installRoot).TrimEnd('\') -eq $installRoot) {
    throw 'Specify the FlintEye installation folder, not a drive root.'
}
$prefix = $installRoot + '\'
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$names = @('FlintEye.exe', 'ffmpeg.exe', 'ffprobe.exe', 'mediamtx.exe')

function Test-OwnedProcess($process) {
    if (-not $process.ExecutablePath -or $process.Name -notin $names) { return $false }
    $path = [IO.Path]::GetFullPath($process.ExecutablePath)
    if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
    return ($owner.ReturnValue -eq 0 -and $owner.Sid -eq $ownerSid)
}

function Get-OwnedProcesses {
    Get-CimInstance Win32_Process -Filter "Name='FlintEye.exe' OR Name='ffmpeg.exe' OR Name='ffprobe.exe' OR Name='mediamtx.exe'" |
        Where-Object { Test-OwnedProcess $_ }
}

try {
    $dataRoot = Join-Path $env:LOCALAPPDATA 'FlintEye'
    $controlFile = Join-Path $dataRoot 'instance-control.json'
    if (Test-Path -LiteralPath $controlFile) {
        $control = Get-Content -LiteralPath $controlFile -Raw | ConvertFrom-Json
        $expected = Join-Path $installRoot 'FlintEye.exe'
        if ($control.executable -eq $expected -and $control.token -match '^[0-9a-f]{64}$') {
            $request = Join-Path $dataRoot 'stop-request.json'
            @{token=$control.token} | ConvertTo-Json -Compress | Set-Content -LiteralPath $request -Encoding UTF8
            $deadline = (Get-Date).AddSeconds(30)
            while (@(Get-OwnedProcesses).Count -gt 0 -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 250
            }
        }
    }
} catch {
    # Missing/stale control files are expected with older installers.
    Write-Warning 'Graceful shutdown was unavailable; checking installed processes.'
}

try {
    foreach ($candidate in @(Get-OwnedProcesses)) {
        # Revalidate the PID and path immediately before stopping it.
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.ProcessId)"
        if ($current -and (Test-OwnedProcess $current) -and $current.CreationDate -eq $candidate.CreationDate) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $current.ProcessId /T /F | Out-Null
        }
    }
    $deadline = (Get-Date).AddSeconds(10)
    do {
        if (@(Get-OwnedProcesses).Count -eq 0) { exit 0 }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw 'FlintEye processes are still running. Restart Windows, then uninstall again.'
} catch {
    Write-Error $_
    exit 1
}
