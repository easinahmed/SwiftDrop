; Inno Setup 6 script for the Windows installer.  Built by .github/workflows/windows.yml:
;   iscc /DAppVersion=1.2.3 packaging\windows\SwiftDrop.iss
; Expects the PyInstaller output in dist\SwiftDrop and writes dist\SwiftDrop-Setup-<version>.exe.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "SwiftDrop"
#define AppExe "SwiftDrop.exe"

[Setup]
AppId={{0EDF2DCE-3A29-4B8A-BCE3-C99E7FFCB50C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Easin Codes
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Easin Codes
VersionInfoProductName={#AppName}
; Per-user install: no administrator rights needed.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=SwiftDrop.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\..\dist
OutputBaseFilename=SwiftDrop-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Files of an older build must not mix with the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\SwiftDrop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
