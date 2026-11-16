#ifndef AppVersion
#error Pass /DAppVersion from flinteye_app/_version.py VERSION
#endif
#ifndef AppArch
#error Pass /DAppArch=amd64 or arm64
#endif
[Setup]
AppId=FlintEye.Community
AppName=FlintEye
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\FlintEye
DefaultGroupName=FlintEye
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FlintEye-{#AppVersion}-windows-{#AppArch}-setup
#if AppArch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
MinVersion=10.0.19045
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
SetupMutex=FlintEye.Setup
UninstallDisplayIcon={app}\FlintEye.exe
SetupIconFile=..\images\icons\flinteye.ico
[Files]
Source: "..\dist\FlintEye\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "stop_windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall_windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintEye.Community_is1"; ValueType: string; ValueName: "UninstallString"; ValueData: """{sys}\WindowsPowerShell\v1.0\powershell.exe"" -NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall_windows.ps1"" -InstallDir ""{app}"""
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintEye.Community_is1"; ValueType: string; ValueName: "QuietUninstallString"; ValueData: """{sys}\WindowsPowerShell\v1.0\powershell.exe"" -NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall_windows.ps1"" -InstallDir ""{app}"" -Silent"
[Icons]
Name: "{autoprograms}\FlintEye"; Filename: "{app}\FlintEye.exe"
Name: "{autodesktop}\FlintEye"; Filename: "{app}\FlintEye.exe"
[Run]
Filename: "{app}\FlintEye.exe"; Parameters: "--setup"; Description: "Open FlintEye"; Flags: nowait postinstall skipifsilent; Check: ShouldStart
; The desktop launcher registers login startup after first setup, with ownership checks.
; User recordings/configuration are outside {app}; intentionally not in UninstallDelete.

[Code]
function InitializeUninstall: Boolean;
var
  ResultCode: Integer;
  Arguments: String;
  StartupValue, OwnExecutable, QuotedExecutable: String;
begin
  Arguments := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\stop_windows.ps1') + '" -InstallDir "' + ExpandConstant('{app}') + '"';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Arguments, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if Result then Result := ResultCode = 0;
  if Result and RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FlintEye', StartupValue) then
  begin
    OwnExecutable := ExpandConstant('{app}\FlintEye.exe');
    QuotedExecutable := '"' + OwnExecutable + '"';
    if (CompareText(StartupValue, QuotedExecutable) = 0) or
       (CompareText(Copy(StartupValue, 1, Length(QuotedExecutable) + 1), QuotedExecutable + ' ') = 0) or
       (CompareText(StartupValue, OwnExecutable) = 0) or
       (CompareText(Copy(StartupValue, 1, Length(OwnExecutable) + 1), OwnExecutable + ' ') = 0) then
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FlintEye');
  end;
  if not Result then
    MsgBox('FlintEye could not be stopped. Restart Windows and try uninstalling again. Your files have not been removed.', mbError, MB_OK);
end;

function ShouldStart: Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOSTART') = 0 then
      Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (not WizardSilent) then
    if not Exec(ExpandConstant('{app}\FlintEye.exe'), '--setup-only', '', SW_SHOWNORMAL,
                ewWaitUntilTerminated, ResultCode) then
      MsgBox('Password setup could not start. Open FlintEye to complete setup.', mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('Also permanently delete settings, logs and recordings in your default FlintEye data folder? Recordings in other locations will be kept.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\FlintEye'), True, True, True);
end;
