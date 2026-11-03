#define AppName "AI Omplanering V8"
#if GetEnv("APP_VERSION") != ""
#define AppVersion GetEnv("APP_VERSION")
#else
#define AppVersion "8.0.0"
#endif
#define AppPublisher "Dizparc Värnamo"
#define AppExeName "AI-Omplanering-V8.exe"

[Setup]
AppId={{1F40E2B1-9B71-4C5B-AC98-8C558911A808}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Dizparc\AI Omplanering V8
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=AI-Omplanering-V8-Setup
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes

[Files]
Source: "..\dist\AI-Omplanering-V8\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Skapa en genväg på skrivbordet"; GroupDescription: "Ytterligare genvägar:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Starta AI Omplanering V8"; Flags: postinstall nowait skipifsilent
