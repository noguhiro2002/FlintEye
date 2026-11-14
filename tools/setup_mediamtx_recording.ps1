param(
    [string]$ConfigPath,
    [string]$EnvFile = ".env",
    [switch]$NoEnv,
    [string[]]$RecordPaths = @("ffmpeg"),
    [bool]$RecordIncludeMultiView = $true,
    [string]$MultiViewPrefix = "multiview",
    [int]$MultiViewMaxCount = 16,
    [string]$RecordRoot = "C:/recordings/mediamtx",
    [string]$RecordSegmentDuration = "10m",
    [string]$RecordDeleteAfter = "168h",
    [string]$ServiceName = "mediamtx",
    [string]$MediaMTXUser = $env:USERNAME,
    [switch]$NoRestart,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[info] $Message"
}

function Read-EnvFile {
    param([string]$Path)

    $values = @{}
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return $values
    }

    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line.StartsWith("export ")) {
            $line = $line.Substring(7).Trim()
        }
        if (-not $line.Contains("=")) {
            continue
        }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (-not $key) {
            continue
        }

        if (
            ($value.StartsWith("'") -and $value.EndsWith("'")) -or
            ($value.StartsWith('"') -and $value.EndsWith('"'))
        ) {
            if ($value.Length -ge 2) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$key] = $value
    }
    return $values
}

function Parse-ListValue {
    param([string]$Value)

    if (-not $Value) {
        return @()
    }

    $split = $Value -split "[,;]"
    $trimmed = $split | ForEach-Object { $_.Trim() }
    return @($trimmed | Where-Object { $_ -ne "" })
}

function Parse-BoolValue {
    param(
        [string]$Value,
        [string]$KeyName
    )

    if (-not $Value) {
        throw "$KeyName must be true/false (or 1/0, yes/no, on/off)"
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -in @("1", "true", "yes", "on")) {
        return $true
    }
    if ($normalized -in @("0", "false", "no", "off")) {
        return $false
    }
    throw "$KeyName must be true/false (or 1/0, yes/no, on/off), got '$Value'"
}

function Normalize-RecordPaths {
    param([string[]]$Values)

    $items = @()
    foreach ($entry in $Values) {
        if ($null -eq $entry) {
            continue
        }
        $parts = Parse-ListValue -Value $entry
        foreach ($part in $parts) {
            $items += $part
        }
    }

    return @($items | Select-Object -Unique)
}

function To-EnvToken {
    param([string]$Value)
    if (-not $Value) {
        return ""
    }
    $token = ($Value.ToUpper() -replace "[^A-Z0-9]+", "_").Trim("_")
    return $token
}

function Find-SectionEnd {
    param(
        [string[]]$Lines,
        [int]$SectionStart
    )

    $end = $Lines.Length
    for ($i = $SectionStart + 1; $i -lt $Lines.Length; $i++) {
        if ($Lines[$i] -match '^[^\s#][^:]*:\s*$') {
            $end = $i
            break
        }
    }
    return $end
}

function Replace-Or-InsertKey {
    param(
        [string[]]$Lines,
        [int]$BlockStart,
        [int]$BlockEnd,
        [string]$Key,
        [string]$Value
    )

    $lineValue = "    ${Key}: ${Value}"
    for ($i = $BlockStart + 1; $i -lt $BlockEnd; $i++) {
        if ($Lines[$i] -match ("^\s{4}" + [Regex]::Escape($Key) + "\s*:")) {
            $Lines[$i] = $lineValue
            return [PSCustomObject]@{
                Lines = $Lines
                BlockEnd = $BlockEnd
            }
        }
    }

    $before = @()
    if ($BlockEnd -gt 0) {
        $before = $Lines[0..($BlockEnd - 1)]
    }
    $after = @()
    if ($BlockEnd -lt $Lines.Length) {
        $after = $Lines[$BlockEnd..($Lines.Length - 1)]
    }
    $Lines = $before + @($lineValue) + $after
    return [PSCustomObject]@{
        Lines = $Lines
        BlockEnd = $BlockEnd + 1
    }
}

function Ensure-PathsSection {
    param([string[]]$Lines)

    $pathsIndex = [Array]::FindIndex($Lines, [Predicate[string]]{ param($line) $line -match '^\s*paths:\s*$' })
    if ($pathsIndex -lt 0) {
        if ($Lines.Length -gt 0 -and $Lines[-1] -ne "") {
            $Lines += ""
        }
        $Lines += "paths:"
        $pathsIndex = $Lines.Length - 1
    }

    $pathsEnd = Find-SectionEnd -Lines $Lines -SectionStart $pathsIndex
    return [PSCustomObject]@{
        Lines = $Lines
        PathsIndex = $pathsIndex
        PathsEnd = $pathsEnd
    }
}

function Upsert-RecordingForPath {
    param(
        [string[]]$Lines,
        [string]$PathName,
        [string]$RecordPathValue,
        [string]$RecordSegmentDuration,
        [string]$RecordDeleteAfter
    )

    $section = Ensure-PathsSection -Lines $Lines
    $Lines = [string[]]$section.Lines
    $pathsIndex = [int]$section.PathsIndex
    $pathsEnd = [int]$section.PathsEnd

    $pathPattern = '^\s{2}' + [Regex]::Escape($PathName) + ':\s*$'
    $pathIndex = -1
    for ($i = $pathsIndex + 1; $i -lt $pathsEnd; $i++) {
        if ($Lines[$i] -match $pathPattern) {
            $pathIndex = $i
            break
        }
    }

    if ($pathIndex -lt 0) {
        $newBlock = @(
            "  ${PathName}:",
            "    record: yes",
            "    recordPath: $RecordPathValue",
            "    recordFormat: fmp4",
            "    recordPartDuration: 1s",
            "    recordMaxPartSize: 50M",
            "    recordSegmentDuration: $RecordSegmentDuration",
            "    recordDeleteAfter: $RecordDeleteAfter"
        )

        $before = @()
        if ($pathsEnd -gt 0) {
            $before = $Lines[0..($pathsEnd - 1)]
        }
        $after = @()
        if ($pathsEnd -lt $Lines.Length) {
            $after = $Lines[$pathsEnd..($Lines.Length - 1)]
        }

        if ($before.Length -gt 0 -and $before[-1] -ne "") {
            $before += ""
        }
        $Lines = $before + $newBlock + $after
        return [PSCustomObject]@{
            Lines = $Lines
            Action = "inserted"
        }
    }

    $pathEnd = $pathsEnd
    for ($i = $pathIndex + 1; $i -lt $pathsEnd; $i++) {
        if ($Lines[$i] -match '^\s{2}[^ #][^:]*:\s*$') {
            $pathEnd = $i
            break
        }
    }

    $desired = [ordered]@{
        "record"                = "yes"
        "recordPath"            = $RecordPathValue
        "recordFormat"          = "fmp4"
        "recordPartDuration"    = "1s"
        "recordMaxPartSize"     = "50M"
        "recordSegmentDuration" = $RecordSegmentDuration
        "recordDeleteAfter"     = $RecordDeleteAfter
    }

    foreach ($entry in $desired.GetEnumerator()) {
        $result = Replace-Or-InsertKey -Lines $Lines -BlockStart $pathIndex -BlockEnd $pathEnd -Key $entry.Key -Value $entry.Value
        $Lines = [string[]]$result.Lines
        $pathEnd = [int]$result.BlockEnd
    }

    return [PSCustomObject]@{
        Lines = $Lines
        Action = "updated"
    }
}

function Upsert-SourceForPath {
    param(
        [string[]]$Lines,
        [string]$PathName,
        [string]$SourceValue
    )

    $section = Ensure-PathsSection -Lines $Lines
    $Lines = [string[]]$section.Lines
    $pathsIndex = [int]$section.PathsIndex
    $pathsEnd = [int]$section.PathsEnd

    $pathPattern = '^\s{2}' + [Regex]::Escape($PathName) + ':\s*$'
    $pathIndex = -1
    for ($i = $pathsIndex + 1; $i -lt $pathsEnd; $i++) {
        if ($Lines[$i] -match $pathPattern) {
            $pathIndex = $i
            break
        }
    }

    if ($pathIndex -lt 0) {
        $newBlock = @(
            "  ${PathName}:",
            "    source: $SourceValue"
        )

        $before = @()
        if ($pathsEnd -gt 0) {
            $before = $Lines[0..($pathsEnd - 1)]
        }
        $after = @()
        if ($pathsEnd -lt $Lines.Length) {
            $after = $Lines[$pathsEnd..($Lines.Length - 1)]
        }

        if ($before.Length -gt 0 -and $before[-1] -ne "") {
            $before += ""
        }
        $Lines = $before + $newBlock + $after
        return [PSCustomObject]@{
            Lines = $Lines
            Action = "inserted"
        }
    }

    $pathEnd = $pathsEnd
    for ($i = $pathIndex + 1; $i -lt $pathsEnd; $i++) {
        if ($Lines[$i] -match '^\s{2}[^ #][^:]*:\s*$') {
            $pathEnd = $i
            break
        }
    }

    $result = Replace-Or-InsertKey -Lines $Lines -BlockStart $pathIndex -BlockEnd $pathEnd -Key "source" -Value $SourceValue
    return [PSCustomObject]@{
        Lines = [string[]]$result.Lines
        Action = "updated"
    }
}

$defaultRecordRoot = "C:/recordings/mediamtx"
$defaultRecordSegmentDuration = "10m"
$defaultRecordDeleteAfter = "168h"
$defaultRecordPaths = @("ffmpeg")
$defaultRecordIncludeMultiView = $true
$defaultMultiViewPrefix = "multiview"
$defaultMultiViewMaxCount = 16
$defaultServiceName = "mediamtx"
$defaultMediaMTXUser = $env:USERNAME

$envValues = @{}
if (-not $NoEnv) {
    if ($EnvFile -ne ".env" -and -not (Test-Path -LiteralPath $EnvFile)) {
        throw "Env file not found: $EnvFile"
    }

    $envValues = Read-EnvFile -Path $EnvFile
    if ($envValues.Count -gt 0) {
        Write-Info "Loaded env file: $EnvFile"
    }
}

if (-not $ConfigPath -and $envValues.ContainsKey("MTX_CONFIG_PATH")) {
    $ConfigPath = $envValues["MTX_CONFIG_PATH"]
}
if ($RecordRoot -eq $defaultRecordRoot -and $envValues.ContainsKey("MTX_RECORD_ROOT")) {
    $RecordRoot = $envValues["MTX_RECORD_ROOT"]
}
if ($RecordSegmentDuration -eq $defaultRecordSegmentDuration -and $envValues.ContainsKey("MTX_RECORD_SEGMENT_DURATION")) {
    $RecordSegmentDuration = $envValues["MTX_RECORD_SEGMENT_DURATION"]
}
if ($RecordDeleteAfter -eq $defaultRecordDeleteAfter -and $envValues.ContainsKey("MTX_RECORD_DELETE_AFTER")) {
    $RecordDeleteAfter = $envValues["MTX_RECORD_DELETE_AFTER"]
}
if (
    $RecordPaths.Count -eq 1 -and
    $RecordPaths[0] -eq $defaultRecordPaths[0] -and
    $envValues.ContainsKey("MTX_RECORD_PATHS")
) {
    $envRecordPaths = Parse-ListValue -Value $envValues["MTX_RECORD_PATHS"]
    if ($envRecordPaths.Count -gt 0) {
        $RecordPaths = $envRecordPaths
    }
}
if (
    $RecordIncludeMultiView -eq $defaultRecordIncludeMultiView -and
    $envValues.ContainsKey("MTX_RECORD_INCLUDE_MULTIVIEW")
) {
    $RecordIncludeMultiView = Parse-BoolValue -Value $envValues["MTX_RECORD_INCLUDE_MULTIVIEW"] -KeyName "MTX_RECORD_INCLUDE_MULTIVIEW"
}
if ($MultiViewPrefix -eq $defaultMultiViewPrefix -and $envValues.ContainsKey("MTX_MULTI_VIEW_PREFIX")) {
    $MultiViewPrefix = $envValues["MTX_MULTI_VIEW_PREFIX"]
}
if (
    $MultiViewMaxCount -eq $defaultMultiViewMaxCount -and
    $envValues.ContainsKey("MTX_MULTI_VIEW_MAX_COUNT")
) {
    try {
        $MultiViewMaxCount = [int]$envValues["MTX_MULTI_VIEW_MAX_COUNT"]
    } catch {
        throw "MTX_MULTI_VIEW_MAX_COUNT must be an integer: '$($envValues["MTX_MULTI_VIEW_MAX_COUNT"])'"
    }
}
$ipSourcePaths = @()
if ($envValues.ContainsKey("MTX_IP_PATHS")) {
    $ipSourcePaths = Parse-ListValue -Value $envValues["MTX_IP_PATHS"]
}
if ($ServiceName -eq $defaultServiceName -and $envValues.ContainsKey("MTX_SERVICE_NAME")) {
    $ServiceName = $envValues["MTX_SERVICE_NAME"]
}
if ($MediaMTXUser -eq $defaultMediaMTXUser -and $envValues.ContainsKey("MTX_SERVICE_USER")) {
    $MediaMTXUser = $envValues["MTX_SERVICE_USER"]
}

if (-not $ConfigPath) {
    throw "ConfigPath is required. Pass -ConfigPath or set MTX_CONFIG_PATH in .env"
}

$RecordPaths = Normalize-RecordPaths -Values $RecordPaths
if ($RecordPaths.Count -eq 0) {
    throw "RecordPaths resolved empty. Pass -RecordPaths or set MTX_RECORD_PATHS in .env"
}
$ipSourcePaths = Normalize-RecordPaths -Values $ipSourcePaths
if (
    -not $envValues.ContainsKey("MTX_RECORD_PATHS") -and
    $RecordPaths.Count -eq 1 -and
    $RecordPaths[0] -eq "ffmpeg" -and
    $ipSourcePaths.Count -gt 0
) {
    $RecordPaths = Normalize-RecordPaths -Values ($RecordPaths + $ipSourcePaths)
}
if ($RecordIncludeMultiView) {
    if (-not $MultiViewPrefix) {
        throw "MultiViewPrefix must not be empty when RecordIncludeMultiView is enabled"
    }
    if ($MultiViewMaxCount -lt 1) {
        throw "MultiViewMaxCount must be >= 1 when RecordIncludeMultiView is enabled"
    }

    $multiViewPaths = @()
    for ($i = 1; $i -le $MultiViewMaxCount; $i++) {
        $multiViewPaths += ("{0}_{1}" -f $MultiViewPrefix, $i)
    }
    $RecordPaths = Normalize-RecordPaths -Values ($RecordPaths + $multiViewPaths)
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Config file not found: $ConfigPath"
}

$configDir = Split-Path -Parent $ConfigPath
$backupPath = Join-Path $configDir "mediamtx.yml.bak"

if ($DryRun) {
    Write-Info "Dry run mode: no files will be modified."
} else {
    Copy-Item -LiteralPath $ConfigPath -Destination $backupPath -Force
    Write-Info "Backup created: $backupPath"
}

$lines = @(Get-Content -LiteralPath $ConfigPath)
if ($null -eq $lines) {
    $lines = @()
}

foreach ($ipPath in $ipSourcePaths) {
    $token = To-EnvToken -Value $ipPath
    if (-not $token) {
        Write-Warning "Skipped invalid MTX_IP_PATHS entry: '$ipPath'"
        continue
    }

    $sourceKey = "MTX_IP_${token}_SOURCE"
    if (-not $envValues.ContainsKey($sourceKey) -or -not $envValues[$sourceKey]) {
        Write-Warning "Missing $sourceKey for path '$ipPath'; source was not changed."
        continue
    }

    $sourceUpsert = Upsert-SourceForPath -Lines $lines -PathName $ipPath -SourceValue $envValues[$sourceKey]
    $lines = [string[]]$sourceUpsert.Lines
    Write-Info ("{0} source for paths.{1}" -f $sourceUpsert.Action, $ipPath)
}

$recordPathValue = "$RecordRoot/%path/%Y-%m-%d/%H-%M-%S-%f"
foreach ($recordPath in $RecordPaths) {
    $upsert = Upsert-RecordingForPath -Lines $lines -PathName $recordPath -RecordPathValue $recordPathValue -RecordSegmentDuration $RecordSegmentDuration -RecordDeleteAfter $RecordDeleteAfter
    $lines = [string[]]$upsert.Lines
    Write-Info ("{0} recording block: paths.{1}" -f $upsert.Action, $recordPath)
}

if (-not $DryRun) {
    Set-Content -LiteralPath $ConfigPath -Value $lines -Encoding UTF8
    Write-Info "Config updated: $ConfigPath"
}

if (-not $DryRun) {
    if (-not (Test-Path -LiteralPath $RecordRoot)) {
        New-Item -ItemType Directory -Path $RecordRoot -Force | Out-Null
    }
    Write-Info "Record root ready: $RecordRoot"

    if ($MediaMTXUser) {
        icacls $RecordRoot /grant "${MediaMTXUser}:(OI)(CI)M" /T | Out-Null
        Write-Info "Granted modify permission to '$MediaMTXUser' on $RecordRoot"
    }
}

if (-not $NoRestart) {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        Write-Warning "Service '$ServiceName' not found. Restart manually if needed."
    } elseif (-not $DryRun) {
        Restart-Service -Name $ServiceName -Force
        Write-Info "Service restarted: $ServiceName"
    } else {
        Write-Info "Dry run: service restart skipped for $ServiceName"
    }
}

$recordPathSummary = ($RecordPaths -join ", ")
Write-Info "Done. Effective settings: paths=$recordPathSummary, record=yes, segment=$RecordSegmentDuration, deleteAfter=$RecordDeleteAfter, includeMultiView=$RecordIncludeMultiView, multiViewPrefix=$MultiViewPrefix, multiViewMaxCount=$MultiViewMaxCount"
