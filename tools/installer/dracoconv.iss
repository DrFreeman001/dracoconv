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
fr.MenuEncode=Convertir en .drc avec dracoconv
fr.MenuDecode=Convertir depuis .drc avec dracoconv
fr.MenuFolder=Convertir avec dracoconv
fr.MenuSlicer=Ouvrir dans le trancheur
fr.ContextMenu=Ajouter « Convertir avec dracoconv » au clic droit de l'Explorateur
en.CommandLine=dracoconv (command line)
en.MenuEncode=Convert to .drc with dracoconv
en.MenuDecode=Convert from .drc with dracoconv
en.MenuFolder=Convert with dracoconv
en.MenuSlicer=Open in slicer
en.ContextMenu=Add "Convert with dracoconv" to the Explorer right-click menu

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "{cm:AddToPath}"; Flags: unchecked
Name: "contextmenu"; Description: "{cm:ContextMenu}"

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


; Clic droit de l'Explorateur (menu classique, « Afficher plus d'options » sous Windows 11). Un processus par
; fichier sélectionné : le premier ouvre la fenêtre, les suivants lui passent leur chemin (dracoconv/gui/launch.py).
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.stl\shell\dracoconv.encode"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuEncode}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.stl\shell\dracoconv.encode"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.stl\shell\dracoconv.encode"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.stl\shell\dracoconv.encode\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --encode ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.obj\shell\dracoconv.encode"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuEncode}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.obj\shell\dracoconv.encode"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.obj\shell\dracoconv.encode"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.obj\shell\dracoconv.encode\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --encode ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ply\shell\dracoconv.encode"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuEncode}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ply\shell\dracoconv.encode"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ply\shell\dracoconv.encode"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ply\shell\dracoconv.encode\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --encode ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.3mf\shell\dracoconv.encode"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuEncode}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.3mf\shell\dracoconv.encode"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.3mf\shell\dracoconv.encode"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.3mf\shell\dracoconv.encode\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --encode ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.decode"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuDecode}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.decode"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.decode"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.decode\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --decode ""%1"""; Tasks: contextmenu
; « Ouvrir dans le trancheur » : décode en STL temporaires et ouvre toute la sélection dans le trancheur choisi
; (menu « Trancheur » de dracoconv), sans fenêtre de dracoconv (dracoconv/gui/slicer_open.py).
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.slicer"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuSlicer}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.slicer"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.slicer"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.drc\shell\dracoconv.slicer\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" --slicer ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\dracoconv"; ValueType: string; ValueName: ""; ValueData: "{cm:MenuFolder}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\dracoconv"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\dracoconv-gui.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\dracoconv"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\dracoconv\command"; ValueType: string; ValueName: ""; ValueData: """{app}\dracoconv-gui.exe"" ""%1"""; Tasks: contextmenu

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
