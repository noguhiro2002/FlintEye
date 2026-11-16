# Only synthetic processes on a disposable native Windows CI runner.
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Use a disposable CI runner.' }
$root=Join-Path $env:RUNNER_TEMP ('FlintEye stop test '+[guid]::NewGuid().ToString('N'))
$profile=Join-Path $root 'custom profile'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
$source=@'
using System;
using System.IO;
using System.Diagnostics;
using System.Threading;
using System.Collections.Generic;
using System.Web.Script.Serialization;
public class SyntheticFlintEye {
 public static void Main(string[] args) {
  if(args.Length > 0 && args[0] == "--worker") { Thread.Sleep(60000); return; }
  string profile=args[0]; string exe=Process.GetCurrentProcess().MainModule.FileName;
  var start=new ProcessStartInfo(Path.Combine(Path.GetDirectoryName(exe), "ffmpeg.exe"), "--worker");
  start.UseShellExecute=false; start.CreateNoWindow=true;
  var child=Process.Start(start);
  var control=new Dictionary<string,object>{{"token",new string('a',64)},{"pid",Process.GetCurrentProcess().Id},{"executable",exe}};
  File.WriteAllText(Path.Combine(profile,"instance-control.json"),new JavaScriptSerializer().Serialize(control));
  File.WriteAllText(Path.Combine(profile,"child.pid"),child.Id.ToString());
  while(!File.Exists(Path.Combine(profile,"stop-request.json"))) Thread.Sleep(50);
  // A child created while shutdown is requested must also be discovered.
  var late=Process.Start(start);
  File.WriteAllText(Path.Combine(profile,"late-child.pid"),late.Id.ToString());
  Thread.Sleep(400);
  // Reproduce an old launcher exiting while its child remains alive.
 }
}
'@
$exe=Join-Path $root 'FlintEye.exe'
Add-Type -TypeDefinition $source -ReferencedAssemblies 'System.dll','System.Web.Extensions.dll' -OutputAssembly $exe -OutputType ConsoleApplication
Copy-Item $exe (Join-Path $root 'ffmpeg.exe')
$parent=$null; $unrelated=$null; $childId=0; $failure=$null
try {
    $parent=Start-Process -FilePath $exe -ArgumentList ('"'+$profile+'"') -PassThru
    $unrelated=Start-Process -FilePath (Join-Path $root 'ffmpeg.exe') -ArgumentList '--worker' -PassThru
    $readyDeadline=(Get-Date).AddSeconds(60)
    do {
        $idText=Get-Content -LiteralPath (Join-Path $profile 'child.pid') -Raw -ErrorAction SilentlyContinue
        if($idText -and [int]::TryParse($idText.Trim(), [ref]$childId) -and $childId -gt 0) { break }
        if($parent.HasExited) { throw 'Synthetic launcher exited before its child was ready.' }
        Start-Sleep -Milliseconds 100
    } while((Get-Date) -lt $readyDeadline)
    if($childId -le 0) { throw 'Synthetic launcher did not publish its child identity within 60 seconds.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File packaging/stop_windows.ps1 -InstallDir $root -DataDir $profile -Force -TimeoutSeconds 2
    if($LASTEXITCODE -ne 0) { throw 'Scoped helper failed.' }
    if(-not $parent.WaitForExit(5000)) { throw 'Parent survived.' }
    if(Get-Process -Id $childId -ErrorAction SilentlyContinue) { throw 'Orphaned media child survived.' }
    $lateId=[int](Get-Content -LiteralPath (Join-Path $profile 'late-child.pid'))
    if(Get-Process -Id $lateId -ErrorAction SilentlyContinue) { throw 'Child created during shutdown survived.' }
    if($unrelated.HasExited) { throw 'Unrelated process was stopped.' }
    $receipt=Get-Content -LiteralPath (Join-Path $profile 'last-stop-result.json') -Raw | ConvertFrom-Json
    if($receipt.mode -ne 'forced') { throw 'Forced media cleanup was reported as normal shutdown.' }
    if(-not (Test-Path -LiteralPath (Join-Path $profile 'instance-control.json'))) { throw 'Retained synthetic profile was removed.' }
    Write-Host 'PASS: scoped stop reaps an orphaned child, preserves an unrelated process and reports force accurately.'
} catch {
    $failure=$_
    Write-Warning ('Scoped stop regression failed: '+$_.Exception.Message)
    throw
} finally {
    foreach($candidate in @($parent,$unrelated)) {
        if($candidate -and -not $candidate.HasExited) { $candidate.Kill(); $candidate.WaitForExit() }
    }
    # A slow first CLR startup can create a child before its PID file is ready.
    # Reap only this disposable fixture's exact executable paths, then wait for
    # handles to close before deleting the files. Preserve the original failure.
    $fixturePaths=@($exe,(Join-Path $root 'ffmpeg.exe'))
    foreach($child in @(Get-CimInstance Win32_Process -Filter "Name='FlintEye.exe' OR Name='ffmpeg.exe'")) {
        if($child.ExecutablePath -notin $fixturePaths) { continue }
        $process=Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if($process -and -not $process.HasExited) { $process.Kill(); $null=$process.WaitForExit(10000) }
    }
    for($attempt=0;$attempt -lt 50;$attempt++) {
        try { Remove-Item -LiteralPath $root -Recurse -Force; break }
        catch {
            if($attempt -eq 49) {
                if($failure) { Write-Warning 'Synthetic fixture cleanup was incomplete; original test failure is preserved.' }
                else { throw }
            }
            Start-Sleep -Milliseconds 100
        }
    }
}
