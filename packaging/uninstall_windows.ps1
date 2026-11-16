# Official current-user removal entry. Run from a temporary copy so no file
# inside the installation is held open while Inno removes that installation.
param([Parameter(Mandatory=$true)][string]$InstallDir, [switch]$Detached, [switch]$Silent)
$ErrorActionPreference = 'Stop'
$installRoot = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
if ($installRoot.Contains('"') -or [IO.Path]::GetPathRoot($installRoot).TrimEnd('\') -eq $installRoot) { throw 'Invalid installation folder' }
if (-not $Detached) {
    $copy = Join-Path ([IO.Path]::GetTempPath()) ('flinteye-uninstall-' + [guid]::NewGuid().ToString('N') + '.ps1')
    Copy-Item -LiteralPath $PSCommandPath -Destination $copy
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $copy + '" -Detached -InstallDir "' + $installRoot + '"'
    if ($Silent) { $arguments += ' -Silent' }
    $process = Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
    Remove-Item -LiteralPath $copy -ErrorAction SilentlyContinue
    exit $process.ExitCode
}
$sha = [Security.Cryptography.SHA256]::Create()
$id = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($installRoot.ToLowerInvariant())))).Replace('-', '')
$sha.Dispose()
$mutex = [Threading.Mutex]::new($false, ('Local\FlintEye-Maintenance-' + $id))
$owned = $false
$setupMutex = $null
$setupOwned = $false
$resultCode = 1
$data = Join-Path $env:LOCALAPPDATA 'FlintEye'
try {
    $owned = $mutex.WaitOne(0)
    if (-not $owned) { throw 'FlintEye installation or removal is already in progress. Wait for it to finish.' }
    $created = $false
    $setupMutex = [Threading.Mutex]::new($true, 'FlintEye.Setup', [ref]$created)
    $setupOwned = $created
    if (-not $created) { throw 'FlintEye setup or another removal is in progress. Wait for it to finish.' }
    $stop = Join-Path $installRoot 'stop_windows.ps1'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $stop -InstallDir $installRoot
    if ($LASTEXITCODE -ne 0) { throw 'FlintEye could not finish recordings and stop. Removal was cancelled; retry Stop or restart Windows.' }
    $firewallOwner = Join-Path $data 'firewall-owner.json'
    if (Test-Path -LiteralPath $firewallOwner) {
        $registration = Get-Content -LiteralPath $firewallOwner -Raw | ConvertFrom-Json
        if ($registration.applied) {
            $cleanup = Start-Process -FilePath (Join-Path $installRoot 'FlintEye.exe') -ArgumentList '--remove-firewall-rules' -Wait -PassThru
            if ($cleanup.ExitCode -ne 0) { throw 'Firewall removal was not approved or completed. Retry removal to clean this installation rules.' }
        }
    }
    # Register only the uninstall log, retrieve lock holders without ending them.
    if (-not ('FlintEyeLocks' -as [type])) { Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class FlintEyeLocks {
 [StructLayout(LayoutKind.Sequential)] public struct Process { public int pid; public System.Runtime.InteropServices.ComTypes.FILETIME start; }
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct Info {
  public Process process;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string name;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=64)] public string service;
  public uint type, status, session;
  [MarshalAs(UnmanagedType.Bool)] public bool restartable;
 }
 [DllImport("rstrtmgr.dll", CharSet=CharSet.Unicode)] static extern int RmStartSession(out uint session, int flags, string key);
 [DllImport("rstrtmgr.dll", CharSet=CharSet.Unicode)] static extern int RmRegisterResources(uint session, uint count, string[] files, uint apps, Process[] processes, uint services, string[] names);
 [DllImport("rstrtmgr.dll")] static extern int RmGetList(uint session, out uint needed, ref uint count, [In, Out] Info[] info, ref uint reason);
 [DllImport("rstrtmgr.dll")] static extern int RmEndSession(uint session);
 public static string Describe(string file) {
  uint session; int error=RmStartSession(out session,0,Guid.NewGuid().ToString("N"));
  if(error!=0) return "Lock information unavailable";
  try {
   if(RmRegisterResources(session,1,new[]{file},0,null,0,null)!=0) return "Lock information unavailable";
   uint needed=0,count=0,reason=0; error=RmGetList(session,out needed,ref count,null,ref reason);
   if(error==0) return "";
   if(error!=234) return "Lock information unavailable";
   var info=new Info[needed];count=needed;
   if(RmGetList(session,out needed,ref count,info,ref reason)!=0) return "Lock information unavailable";
   var names=new System.Collections.Generic.List<string>();
   for(int i=0;i<count;i++) names.Add(info[i].name+" (PID "+info[i].process.pid+")");
   return String.Join(", ",names);
  } finally { RmEndSession(session); }
 }
}
'@
    }
    $log = Join-Path $installRoot 'unins000.dat'
    $holders = ''
    for ($attempt=0; $attempt -lt 5; $attempt++) {
        $holders = [FlintEyeLocks]::Describe($log)
        if (-not $holders) { break }
        Start-Sleep -Seconds 1
    }
    if ($holders) { throw ('Uninstall data is in use: ' + $holders + '. Close that operation and try again. No product data was deleted.') }
    $installer = Join-Path $installRoot 'unins000.exe'
    if (-not (Test-Path -LiteralPath $installer)) { throw 'The uninstaller is missing. Reinstall the same version before removal.' }
    $argsList = @('/LOG="' + (Join-Path $data 'uninstall.log') + '"')
    if ($Silent) { $argsList += '/VERYSILENT'; $argsList += '/SUPPRESSMSGBOXES' }
    $process = Start-Process -FilePath $installer -ArgumentList $argsList -Wait -PassThru
    $resultCode = $process.ExitCode
    if ($resultCode -ne 0) { throw ('Removal did not complete, code ' + $resultCode + '. Settings and recordings were retained.') }
} catch {
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'uninstall-failure.txt'), $_.Exception.Message)
    if (-not $Silent) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'FlintEye removal not completed', 'OK', 'Warning') | Out-Null
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    if ($setupOwned) { $setupMutex.ReleaseMutex() }
    if ($setupMutex) { $setupMutex.Dispose() }
}
exit $resultCode
