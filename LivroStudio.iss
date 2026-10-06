#define MyAppName "LivroStudio"
#define MyAppVersion "3.5.0"
#define MyAppPublisher "LivroStudio"
#define MyAppExeName "LivroStudio.exe"

[Setup]
AppId={{A7D7F2B1-8E4B-4C5D-9A21-6B8E5F2D3C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LivroStudio
DefaultGroupName=LivroStudio
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=LivroStudio_Setup_{#MyAppVersion}
SetupIconFile=livrostudio.ico
UninstallDisplayIcon={app}\LivroStudio.exe
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "dist\LivroStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LivroStudio"; Filename: "{app}\LivroStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\LivroStudio"; Filename: "{app}\LivroStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\LivroStudio.exe"; Description: "Abrir LivroStudio"; Flags: nowait postinstall skipifsilent
