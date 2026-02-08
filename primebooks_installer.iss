; PrimeBooks Desktop Installer Script
#define MyAppName "PrimeBooks Desktop"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Prime Focus Uganda Ltd"
#define MyAppURL "https://primebooks.sale"
#define MyAppExeName "PrimeBooks.exe"

[Setup]
; Basic app info
AppId={{C161BA88-8F2A-4D9B-9C6D-0F1E2A3SAAD}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation directories
DefaultDirName={autopf}\PrimeBooks
DefaultGroupName=PrimeBooks
DisableProgramGroupPage=yes

; Output
OutputDir=installer_output
OutputBaseFilename=PrimeBooks_Setup_{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes

; Wizard appearance
WizardStyle=modern
WizardImageFile=wizard_image.bmp
WizardSmallImageFile=wizard_small.bmp

; Privileges
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable
Source: "dist\PrimeBooks.exe"; DestDir: "{app}"; Flags: ignoreversion

; All runtime files
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Icon
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\PrimeBooks"; Filename: "{app}\PrimeBooks.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall PrimeBooks"; Filename: "{uninstallexe}"

; Desktop (optional)
Name: "{autodesktop}\PrimeBooks"; Filename: "{app}\PrimeBooks.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
; Option to launch after install
Filename: "{app}\PrimeBooks.exe"; Description: "{cm:LaunchProgram,PrimeBooks}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up data on uninstall (optional)
Type: filesandordirs; Name: "{userappdata}\PrimeBooks"