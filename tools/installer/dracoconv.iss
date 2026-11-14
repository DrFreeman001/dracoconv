; Installateur de dracoconv : installation pour l'utilisateur courant, sans droits d'administrateur.
; Construit par tools/build_installer.ps1, qui prépare d'abord dist/dracoconv avec PyInstaller.

#define AppName "dracoconv"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define Root ".." + "\.."

[Setup]
AppId={{5B0E6D52-3C9A-4E7B-9C1F-0D7A2F6B8E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=DrFreeman001
AppPublisherURL=https://github.com/DrFreeman001/dracoconv
AppSupportURL=https://github.com/DrFreeman001/dracoconv/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#Root}\LICENSE
OutputDir={#Root}\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
UninstallDisplayIcon={app}\dracoconv-gui.exe
UninstallDisplayName={#AppName} {#AppVersion}

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.AddToPath=Ajouter la ligne de commande dracoconv à la variable PATH
en.AddToPath=Add the dracoconv command line to PATH
fr.CommandLine=dracoconv (ligne de commande)
en.CommandLine=dracoconv (command line)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "{cm:AddToPath}"; Flags: unchecked

[Files]
Source: "{#Root}\dist\dracoconv\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\dracoconv-gui.exe"
Name: "{autoprograms}\{cm:CommandLine}"; Filename: "{cmd}"; Parameters: "/k ""{app}\dracoconv.exe"" --help"; WorkingDir: "{userdocs}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\dracoconv-gui.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\dracoconv-gui.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function PathContains(const Paths, Dir: string): Boolean;
begin
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    Paths := '';
  Result := not PathContains(Paths, Dir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Paths, Dir: string;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    exit;
  Dir := ExpandConstant('{app}');
  P := Pos(';' + Uppercase(Dir), Uppercase(Paths));
  if P > 0 then
  begin
    Delete(Paths, P, Length(Dir) + 1);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Paths);
  end;
end;
