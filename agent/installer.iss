; Inno Setup script -> output\TallySyncSetup.exe
#define MyAppName "Tally Sync Agent"
#define MyAppVersion "0.2.0"

[Setup]
AppId={{B6A3C1E0-5D2F-4C57-9E1B-7A1F0C9D2E44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Your Company Name
DefaultDirName={localappdata}\TallySyncimport hmac
import html
import os
import secrets

from 
DisableProgramGroupPage=yes
DisableDirPage=yes
; per-user install: NO administrator / UAC prompt
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=TallySyncSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile=consent.txt
UninstallDisplayIcon={app}\TallySyncAgent.exe
CloseApplications=yes
; Code signing (needed to avoid SmartScreen warnings). Configure a SignTool in Inno Setup, then:
; SignTool=mysigntool $f
; SignedUninstaller=yes

[Files]
Source: "dist\TallySyncAgent.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Tally Sync Agent"; Filename: "{app}\TallySyncAgent.exe"

[Registry]
; start automatically when this user logs in
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "TallySyncAgent"; ValueData: """{app}\TallySyncAgent.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\TallySyncAgent.exe"; Description: "Start Tally Sync Agent now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM TallySyncAgent.exe"; Flags: runhidden; RunOnceId: "KillAgent"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Also remove saved settings, logs and the stored connection token?', mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{userappdata}\TallySync'), True, True, True);
end;
