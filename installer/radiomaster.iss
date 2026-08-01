; RadioMaster installer — offers a real Program Files install OR a portable
; extract-to-any-folder mode from a single installer.
;
; The app itself is already fully portable (config.json/stations.db/etc. all
; live next to RadioMaster.exe, no registry writes, no %APPDATA% writes), so
; "portable" here just means: skip Start Menu/Desktop shortcuts and suggest a
; relocatable folder instead of Program Files, so the resulting folder can be
; copied straight onto a USB drive and run from there.
;
; AppId is deliberately per-VERSION (not a single fixed GUID) — Inno Setup
; silently skips the "install for me/all users" and destination-folder pages
; when it detects the same AppId already installed, reusing whatever was
; chosen last time (confirmed: this is what made the wizard look "broken"
; when testing repeatedly). Keying AppId off the version makes every build
; look like a brand-new, independent app to Setup, so those pages always
; show, and multiple versions can be installed side by side for testing
; without fighting over the same registry entry.

#define MyAppName "RadioMaster"
#define MyAppVersion "1.5.2"
#define MyAppExeName "RadioMaster.exe"
#define MyAppPublisher "Deenadayalan Moodley"
#define MyDistDir "..\dist\RadioMaster"

[Setup]
AppId={{RadioMaster-{#MyAppVersion}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) Deenadayalan Moodley 2026. All rights reserved.
DefaultDirName={autopf}\{#MyAppName} {#MyAppVersion}
DefaultGroupName={#MyAppName} {#MyAppVersion}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=RadioMaster-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: not IsPortableMode
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; Check: not IsPortableMode
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Check: not IsPortableMode

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Check: not IsPortableMode

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  InstallModePage: TInputOptionWizardPage;

function IsPortableMode: Boolean;
begin
  Result := InstallModePage.SelectedValueIndex = 1;
end;

procedure InitializeWizard;
begin
  InstallModePage := CreateInputOptionPage(wpWelcome,
    'Choose Installation Type', 'How would you like to set up ' + '{#MyAppName}' + '?',
    'Select an option, then click Next.',
    True, False);
  InstallModePage.Add('Full installation (Start Menu shortcuts + uninstaller, Program Files)');
  InstallModePage.Add('Portable (copy to any folder you choose, e.g. a USB drive - no shortcuts)');
  InstallModePage.SelectedValueIndex := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectDir then
  begin
    if IsPortableMode then
      WizardForm.DirEdit.Text := ExpandConstant('{userdocs}\RadioMaster-Portable-{#MyAppVersion}')
    else
      WizardForm.DirEdit.Text := ExpandConstant('{autopf}\{#MyAppName} {#MyAppVersion}');
  end;
end;
