[Setup]
AppName=NacionalSign Agent
AppVersion=1.0.0
DefaultDirName={pf}\NacionalSign\Agent
DefaultGroupName=NacionalSign
OutputBaseFilename=NacionalSignAgentSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "SigningAgent.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\NacionalSign Agent"; Filename: "{app}\SigningAgent.exe"; Parameters: "serve"
Name: "{commondesktop}\NacionalSign Agent"; Filename: "{app}\SigningAgent.exe"; Parameters: "serve"

[Run]
Filename: "{app}\SigningAgent.exe"; Parameters: "serve"; Flags: nowait postinstall skipifsilent
