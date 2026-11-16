param([Parameter(Mandatory=$true)][string]$Script, [Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference = 'Stop'
if ($Script.Contains('"') -or $Request.Contains('"')) { throw 'Invalid file path' }
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Script + '" -Request "' + $Request + '"'
$process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -PassThru -Wait
exit $process.ExitCode
