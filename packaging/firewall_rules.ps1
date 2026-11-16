# Selection only. Callers handle confirmation and any elevated modifications.
function Test-InstallationFirewallRule($Rule, [string]$Application, [string]$Media) {
    $group=[string]$Rule.Group
    if($group -notmatch '^FlintEye-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') { return $false }
    if($Rule.Name -in @(($group+'-HTTPS'), ($group+'-HTTPS-staging'))) { $expected=$Application }
    elseif($Rule.Name -in @(($group+'-WebRTC'), ($group+'-WebRTC-staging'))) { $expected=$Media }
    else { return $false }
    $filters=@($Rule | Get-NetFirewallApplicationFilter -ErrorAction Stop)
    if($filters.Count -ne 1 -or -not $filters[0].Program) { return $false }
    try {
        $actual=[Environment]::ExpandEnvironmentVariables([string]$filters[0].Program)
        if(-not [IO.Path]::IsPathRooted($actual)) { return $false }
        return [IO.Path]::GetFullPath($actual).Equals([IO.Path]::GetFullPath($expected), [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Get-InstallationFirewallRules([string]$Application, [string]$Media) {
    Get-NetFirewallRule -ErrorAction Stop | Where-Object { Test-InstallationFirewallRule $_ $Application $Media }
}
