#define AppVersion "0.6.2"
[Setup]
AppId={{D179B83F-5E90-43C3-B417-72A9EC81EF0A}
AppName=Clipboard AI
AppVersion={#AppVersion}
DefaultDirName={autopf}\Clipboard AI
DefaultGroupName=Clipboard AI
OutputDir=..\..\dist\windows
OutputBaseFilename=ClipboardAI-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName=Clipboard AI

[Files]
Source: "..\..\dist\windows\ClipboardAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Clipboard AI"; Filename: "{app}\ClipboardAI.exe"
Name: "{autoprograms}\Clipboard AI"; Filename: "{app}\ClipboardAI.exe"

[Run]
Filename: "{app}\ClipboardAI.exe"; Description: "Abrir Clipboard AI"; Flags: nowait postinstall skipifsilent
