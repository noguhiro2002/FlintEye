# Stop current-user processes from one FlintEye installation; preserve user data.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$DataDir,
    [switch]$Force,
    [ValidateRange(1,120)][int]$TimeoutSeconds=45
)
$ErrorActionPreference = 'Stop'
$installRoot = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
if ([IO.Path]::GetPathRoot($installRoot).TrimEnd('\') -eq $installRoot) {
    throw 'Specify the FlintEye installation folder, not a drive root.'
}
$prefix = $installRoot + '\'
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$defaultData = Join-Path $env:LOCALAPPDATA 'FlintEye'
$names = @('FlintEye.exe', 'ffmpeg.exe', 'ffprobe.exe', 'mediamtx.exe')
$events = [Collections.Generic.List[object]]::new()
$forced = $false
$stage = 'initialization'

# Parse quoting exactly as Windows does, including paths containing spaces.
if (-not ('FlintEyeCommandLine' -as [type])) { Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FlintEyeCommandLine {
    [DllImport("shell32.dll", SetLastError=true)] static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmd, out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr memory);
    public static string[] Parse(string command) {
        int count; IntPtr memory = CommandLineToArgvW(command, out count);
        if(memory == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        try { string[] result = new string[count]; for(int i=0; i<count; i++) result[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory, i * IntPtr.Size)); return result; }
        finally { LocalFree(memory); }
    }
}
'@
}

function Test-OwnedProcess($process) {
    if ($process.Name -notin $names) { return $false }
    if ($process.ExecutablePath -and -not ([IO.Path]::GetFullPath($process.ExecutablePath)).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    try {
        $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
        if ($owner.ReturnValue -ne 0) { throw 'Process ownership could not be verified.' }
        if ($owner.Sid -ne $ownerSid) { return $false }
        if (-not $process.ExecutablePath) { throw 'Current-user process path is unavailable.' }
        return ([IO.Path]::GetFullPath($process.ExecutablePath)).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    } catch {
        # Exiting between enumeration and GetOwnerSid is normal. Other errors
        # must stop the operation rather than broaden the process selection.
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ProcessId)"
        if (-not $current -or $current.CreationDate -ne $process.CreationDate) { return $false }
        throw
    }
}
function Get-OwnedProcesses {
    Get-CimInstance Win32_Process -Filter "Name='FlintEye.exe' OR Name='ffmpeg.exe' OR Name='ffprobe.exe' OR Name='mediamtx.exe'" |
        Where-Object { Test-OwnedProcess $_ }
}
function Still-Running($candidate) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.ProcessId)"
    return $current -and $current.CreationDate -eq $candidate.CreationDate -and (Test-OwnedProcess $current)
}
function Update-Tracked($snapshot) {
    $expanded=$true
    while ($expanded) {
        $expanded=$false
        foreach ($child in $snapshot) {
            if (@($tracked | Where-Object { $_.ProcessId -eq $child.ProcessId -and $_.CreationDate -eq $child.CreationDate }).Count -gt 0) { continue }
            foreach ($parent in @($tracked.ToArray())) {
                if ($child.ParentProcessId -ne $parent.ProcessId -or $child.CreationDate -lt $parent.CreationDate) { continue }
                $currentParent=Get-CimInstance Win32_Process -Filter "ProcessId=$($parent.ProcessId)"
                if ($currentParent -and $currentParent.CreationDate -ne $parent.CreationDate) { continue }
                $tracked.Add($child); $expanded=$true; break
            }
        }
    }
}
function Get-Remaining {
    $snapshot=@(Get-OwnedProcesses)
    if (-not $DataDir) { return $snapshot }
    Update-Tracked $snapshot
    return @($tracked | Where-Object { Still-Running $_ })
}
function Report-Stop($mode, $code) {
    $report = @{ mode=$mode; exit_code=$code; events=@($events.ToArray()); media_finalization='Check active recordings separately; a process exit alone is not proof of finalization.' }
    $json = $report | ConvertTo-Json -Depth 5
    $receiptRoot = if ($DataDir) { [IO.Path]::GetFullPath($DataDir) } else { $defaultData }
    New-Item -ItemType Directory -Force -Path $receiptRoot | Out-Null
    [IO.File]::WriteAllText((Join-Path $receiptRoot 'last-stop-result.json'), $json)
    Write-Output $json
}

try {
    $stage = 'enumerate-owned-processes'
    $original = @(Get-OwnedProcesses)
    $targets = [Collections.Generic.List[object]]::new()
    foreach ($process in $original) {
        if ($process.Name -ne 'FlintEye.exe') { continue }
        $arguments = [FlintEyeCommandLine]::Parse($process.CommandLine)
        if ($arguments -contains '--worker' -or $arguments -contains '--segment-complete' -or $arguments -contains '--pick-folder') { continue }
        $profile = $defaultData
        for ($index=1; $index -lt $arguments.Count; $index++) {
            if ($arguments[$index] -eq '--data-dir' -and $index+1 -lt $arguments.Count) { $profile=$arguments[++$index] }
            elseif ($arguments[$index].StartsWith('--data-dir=')) { $profile=$arguments[$index].Substring(11) }
        }
        # New bundles register their resolved profile, covering relative CLI
        # paths and FLINTEYE_DATA_DIR without inspecting another process's env.
        $indexFile=Join-Path $defaultData ("running\" + $process.ProcessId + '.json')
        if (Test-Path -LiteralPath $indexFile) {
            $registration=Get-Content -LiteralPath $indexFile -Raw | ConvertFrom-Json
            if ($registration.pid -eq $process.ProcessId -and $registration.executable -eq $process.ExecutablePath -and
                (Get-Item -LiteralPath $indexFile).LastWriteTimeUtc -ge $process.CreationDate.ToUniversalTime()) {
                $profile=$registration.profile
            }
        }
        # Explicit DataDir also supports an environment-selected profile. The
        # control PID below must match, so another profile is never signalled.
        if ($DataDir) { $profile=$DataDir }
        if (-not [IO.Path]::IsPathRooted($profile)) { throw 'Use an absolute -DataDir for this older relative-path instance.' }
        $profile=[IO.Path]::GetFullPath($profile)
        $stage='read-control'
        $controlFile=Join-Path $profile 'instance-control.json'
        if (-not (Test-Path -LiteralPath $controlFile)) {
            $events.Add(@{pid=$process.ProcessId; state='no-control-file'})
            if (-not $DataDir) { $targets.Add($process) }
            continue
        }
        $control=Get-Content -LiteralPath $controlFile -Raw | ConvertFrom-Json
        if ($control.pid -ne $process.ProcessId) { continue }
        if ($control.executable -ne (Join-Path $installRoot 'FlintEye.exe') -or
            $control.token -notmatch '^[0-9a-f]{64}$' -or
            (Get-Item -LiteralPath $controlFile).LastWriteTimeUtc -lt $process.CreationDate.ToUniversalTime()) {
            throw 'Control identity does not match the running installation.'
        }
        if (-not (Still-Running $process)) { continue }
        $targets.Add($process)
        $stage='write-stop-request'
        $request=Join-Path $profile 'stop-request.json'
        $temporary=Join-Path $profile ('stop-request-' + [guid]::NewGuid().ToString('N') + '.tmp')
        try {
            [IO.File]::WriteAllText($temporary, (@{token=$control.token} | ConvertTo-Json -Compress))
            Move-Item -LiteralPath $temporary -Destination $request -Force
        } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
        $events.Add(@{pid=$process.ProcessId; state='requested'})
    }
    if ($DataDir -and $targets.Count -eq 0 -and $original.Count -gt 0) { throw 'No running instance matched DataDir; no processes were stopped.' }
    # Keep owned descendants by identity even after the parent exits. Do not use
    # taskkill /T, which could also terminate descendants outside this bundle.
    $tracked=[Collections.Generic.List[object]]::new()
    foreach ($target in $targets) { $tracked.Add($target) }
    Update-Tracked $original
    $stage='wait-for-shutdown'
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $remaining=@(Get-Remaining)
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ($remaining.Count -gt 0 -and -not $Force) {
        $events.Add(@{state='timeout'; remaining=$remaining.Count})
        throw 'Shutdown did not complete. See last-stop-result.json. Force stopping is a separate option.'
    }
    $stage='force-stop'
    foreach ($candidate in $remaining) {
        if (Still-Running $candidate) {
            $forced=$true
            & "$env:SystemRoot\System32\taskkill.exe" /PID $candidate.ProcessId /F | Out-Null
            $events.Add(@{pid=$candidate.ProcessId; state='force-requested'})
        }
    }
    $deadline=(Get-Date).AddSeconds(10)
    do {
        $remaining=@(Get-Remaining)
        if ($remaining.Count -eq 0) {
            $mode=if ($forced) {'forced'} elseif ($original.Count -eq 0) {'already-stopped'} else {'requested-shutdown-completed'}
            Report-Stop $mode 0
            exit 0
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw 'Processes remain running.'
} catch {
    # Do not echo command lines, control-file contents or shutdown tokens.
    $events.Add(@{state='failed'; stage=$stage; exception=$_.Exception.GetType().Name; code=$_.Exception.HResult})
    Report-Stop 'incomplete' 1
    Write-Error "FlintEye shutdown failed during $stage. See last-stop-result.json; keep data and retry after stopping the app."
    exit 1
}
