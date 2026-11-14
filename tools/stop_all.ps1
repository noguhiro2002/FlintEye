Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WorkspaceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Log([string]$Message) {
    Write-Host "[info] $Message"
}

function Warn([string]$Message) {
    Write-Warning $Message
}

function Get-MatchingProcesses([string]$Pattern) {
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and ($_.CommandLine -match $Pattern)
    }
}

function Stop-MatchingProcesses([string]$Pattern, [string]$Label) {
    $processes = @(Get-MatchingProcesses $Pattern | Sort-Object ProcessId -Unique)
    if ($processes.Count -eq 0) {
        Log "no running $Label found"
        return
    }

    $stoppedAny = $false
    foreach ($process in $processes) {
        $null = & taskkill.exe /PID $process.ProcessId /T /F 2>$null
        if ($LASTEXITCODE -eq 0) {
            $stoppedAny = $true
            continue
        }
        Warn "failed to stop $Label (pid=$($process.ProcessId))"
    }

    if ($stoppedAny) {
        Log "stopped $Label"
    } else {
        Log "no running $Label found"
    }
}

Log "stopping orchestrator stack from $WorkspaceDir"

# Stop parents first, otherwise ffmpeg workers may be respawned immediately.
Stop-MatchingProcesses "tools\.start_orchestrator_stack|start_orchestrator_stack\.py" "development launcher"
Stop-MatchingProcesses "flinteye_app\.orchestrator_api|orchestrator_api\.py" "API"

Start-Sleep -Seconds 1

# Stop managed workers and remaining media processes.
Stop-MatchingProcesses "flinteye\.py.? --worker (uvc_to_rtsp|ip_camera_to_rtsp|multiview_to_rtsp|multiview_input_to_rtsp|multiview_buffer_to_rtsp|multiview_raw_compositor)" "camera workers"
Stop-MatchingProcesses "multiview_to_rtsp\.py" "multiview_to_rtsp.py"
Stop-MatchingProcesses "mediamtx(?:\.exe)?|\\mediamtx\\mediamtx" "mediamtx"
Stop-MatchingProcesses "(^|[\\/])ffmpeg(?:\.exe)?($|\s)" "ffmpeg"

Log "remaining related processes:"
$remaining = @(
    Get-MatchingProcesses "orchestrator_api\.py|start_orchestrator_stack\.py|uvc_to_rtsp\.py|multiview_to_rtsp\.py|mediamtx(?:\.exe)?|(^|[\\/])ffmpeg(?:\.exe)?($|\s)"
)

if ($remaining.Count -eq 0) {
    Log "none"
} else {
    $remaining |
        Select-Object ProcessId, ParentProcessId, Name, CommandLine |
        Format-Table -AutoSize
}

Log "done"
