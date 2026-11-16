param([Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Request -Raw | ConvertFrom-Json
$identity = [guid]::Parse($config.id).ToString()
$group = 'FlintEye-' + $identity
function Test-PrivateIPv4([string]$value) {
    $ip = [Net.IPAddress]::Parse($value)
    $bytes = $ip.GetAddressBytes()
    return $bytes.Length -eq 4 -and ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168))
}
if ($config.action -notin @('apply', 'remove')) { throw 'Invalid Firewall action' }
$exitCode = 1
Add-Type -AssemblyName System.Windows.Forms
$installRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if ([IO.Path]::GetFullPath($config.application) -ne (Join-Path $installRoot 'FlintEye.exe')) { throw 'Unexpected application path' }
if ([IO.Path]::GetFullPath($config.media) -ne (Join-Path (Split-Path $PSScriptRoot -Parent) 'bin\mediamtx.exe')) { throw 'Unexpected media path' }
$question = 'FlintEye Firewall: ' + $config.action + [Environment]::NewLine + 'Server: ' + $config.address + [Environment]::NewLine + 'HTTPS TCP ' + $config.port + ', WebRTC UDP 8189' + [Environment]::NewLine + 'Sources: ' + ($config.subnets -join ', ') + [Environment]::NewLine + 'Private profile only. Installation: ' + $identity
if ([Windows.Forms.MessageBox]::Show($question, 'Confirm FlintEye LAN access', 'YesNo', 'Question') -ne 'Yes') { exit 2 }
try {
    # Only exact names belonging to this installation; never broad wildcard removal.
    $names = @($group + '-HTTPS', $group + '-WebRTC')
    $previous = @()
    foreach ($name in $names) {
        $rule = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
        if ($rule) {
            if ($rule.Group -ne $group) { throw 'A rule name belongs to another application. No rule was changed.' }
            $ports = $rule | Get-NetFirewallPortFilter
            $addresses = $rule | Get-NetFirewallAddressFilter
            $program = $rule | Get-NetFirewallApplicationFilter
            $previous += @{Name=$rule.Name; DisplayName=$rule.DisplayName; Group=$rule.Group; Direction=$rule.Direction; Action=$rule.Action; Profile=$rule.Profile; Enabled=$rule.Enabled; Protocol=$ports.Protocol; LocalPort=$ports.LocalPort; LocalAddress=$addresses.LocalAddress; RemoteAddress=$addresses.RemoteAddress; Program=$program.Program}
        }
    }
    if ($config.action -eq 'apply') {
        $address = [Net.IPAddress]::Parse($config.address)
        if ($address.AddressFamily -ne 'InterNetwork' -or $config.port -lt 1 -or $config.port -gt 65535) { throw 'Invalid LAN endpoint' }
        if (-not $config.subnets -or $config.subnets.Count -gt 16) { throw 'Select source ranges' }
        if (-not (Test-PrivateIPv4 $config.address)) { throw 'Use a private IPv4 address' }
        foreach ($range in $config.subnets) {
            $parts = $range.Split('/')
            if ($parts.Count -ne 2 -or $parts[1] -notmatch '^([89]|[12][0-9]|3[0-2])$' -or -not (Test-PrivateIPv4 $parts[0])) { throw 'Invalid private source range' }
            $bytes = ([Net.IPAddress]::Parse($parts[0])).GetAddressBytes()
            if (($bytes[0] -eq 172 -and [int]$parts[1] -lt 12) -or ($bytes[0] -eq 192 -and [int]$parts[1] -lt 16)) { throw 'Source range includes public addresses' }
        }
        $adapter = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $address.IPAddressToString -ErrorAction Stop
        $profile = Get-NetConnectionProfile -InterfaceIndex $adapter.InterfaceIndex -ErrorAction Stop
        if ($profile.NetworkCategory -ne 'Private') { throw 'Automatic LAN rules require a Private network. Ask your administrator for Domain networks.' }
        # Stage new rules before removing the previous pair. Roll back staging on failure.
        $staged = @()
        try {
            foreach ($kind in @('HTTPS', 'WebRTC')) {
                $ruleName = $group + '-' + $kind + '-staging'
                Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
                $protocol = if ($kind -eq 'HTTPS') { 'TCP' } else { 'UDP' }
                $port = if ($kind -eq 'HTTPS') { $config.port } else { 8189 }
                $program = if ($kind -eq 'HTTPS') { $config.application } else { $config.media }
                New-NetFirewallRule -Name $ruleName -DisplayName ('FlintEye ' + $kind + ' ' + $identity) -Group $group `
                    -Direction Inbound -Action Allow -Protocol $protocol -LocalPort $port -Program $program `
                    -LocalAddress $config.address -RemoteAddress $config.subnets -Profile Private -Enabled False | Out-Null
                $staged += $ruleName
            }
        } catch {
            foreach ($name in $staged) { Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
            throw
        }
        try {
            foreach ($name in $names) { Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
            foreach ($name in $staged) {
                Rename-NetFirewallRule -Name $name -NewName ($name -replace '-staging$', '')
                Enable-NetFirewallRule -Name ($name -replace '-staging$', '')
            }
        } catch {
            foreach ($name in @($names) + @($staged)) { Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
            foreach ($old in $previous) { New-NetFirewallRule @old | Out-Null }
            throw
        }
    } else {
        foreach ($name in $names) { Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
    }
    $exitCode = 0
} finally {
    # Return status through the process exit code; never write an elevated result to a caller path.
}

exit $exitCode
