# Pure selection against synthetic objects. Never reads/changes real Firewall rules.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'firewall_rules.ps1')
$application='C:\FlintEye test\FlintEye.exe'
$media='C:\FlintEye test\_internal\bin\mediamtx.exe'
$first='FlintEye-11111111-1111-4111-8111-111111111111'
$custom='FlintEye-22222222-2222-4222-8222-222222222222'
$other='FlintEye-33333333-3333-4333-8333-333333333333'
$script:syntheticRules=@(
    [pscustomobject]@{Name=$first+'-HTTPS';Group=$first;Program=$application},
    [pscustomobject]@{Name=$custom+'-WebRTC';Group=$custom;Program=$media},
    [pscustomobject]@{Name=$custom+'-HTTPS-staging';Group=$custom;Program=$application},
    [pscustomobject]@{Name=$other+'-HTTPS';Group=$other;Program='C:\Other FlintEye\FlintEye.exe'},
    [pscustomobject]@{Name=$first+'-WebRTC';Group=$first;Program='C:\Other FlintEye\_internal\bin\mediamtx.exe'},
    [pscustomobject]@{Name=$first+'-custom';Group=$first;Program=$application},
    [pscustomobject]@{Name=$first+'-HTTPS';Group='Other app';Program=$application},
    [pscustomobject]@{Name=$first+'-HTTPS';Group=$first;Program='Any'}
)
function Get-NetFirewallRule { [CmdletBinding()]param(); $script:syntheticRules }
function Get-NetFirewallApplicationFilter {
    [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$Rule)
    process { [pscustomobject]@{Program=$Rule.Program} }
}
$selected=@(Get-InstallationFirewallRules $application $media)
if($selected.Count -ne 3) { throw 'Installation selection did not cover both profiles and staging.' }
if(@($selected | Where-Object {$_.Program -notin @($application,$media)}).Count) { throw 'Another installation was selected.' }
Write-Host 'PASS: installation Firewall selection includes custom profiles/staging and excludes other installations/manual rules.'
