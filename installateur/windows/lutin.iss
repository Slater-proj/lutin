; Installateur Windows de Lutin (Inno Setup 6). Construit par construire.ps1, qui passe : Version, NumVersion, AppDir, WheelName.
; Sans droits administrateur : tout va dans %LOCALAPPDATA%\Programs\Lutin. S'il y a deja un Python 3.10+ sur l'ordinateur, il est utilise (un environnement prive) et rien d'autre
; n'est installe ; sinon le Python embarque est copie. Les donnees (conversations, reglages) sont ailleurs (%APPDATA%\Lutin) et ne sont jamais touchees. English and French.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef NumVersion
  #define NumVersion "0.0.0.0"
#endif

[Setup]
AppId={{35FD8225-C972-4C5A-8974-9E47A345DA61}
AppName=Lutin
AppVersion={#Version}
VersionInfoVersion={#NumVersion}
VersionInfoProductName=Lutin
VersionInfoProductVersion={#NumVersion}
VersionInfoCompany=Slater-proj
VersionInfoDescription=Lutin installer
AppPublisher=Slater-proj
AppPublisherURL=https://github.com/Slater-proj/lutin
AppSupportURL=https://github.com/Slater-proj/lutin/issues
AppUpdatesURL=https://github.com/Slater-proj/lutin/releases
DefaultDirName={localappdata}\Programs\Lutin
DefaultGroupName=Lutin
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
SetupIconFile=lutin.ico
UninstallDisplayIcon={app}\lutin.ico
WizardImageFile=assistant-grand.bmp
WizardSmallImageFile=assistant-petit.bmp
UninstallDisplayName=Lutin

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
en.AddToPath=Add the "lutin" command to the PATH (recommended)
fr.AddToPath=Ajouter la commande "lutin" au PATH (conseill{é})
en.RunSetup=Configure Lutin now (guided installation)
fr.RunSetup=Configurer Lutin maintenant (installation guid{é}e)
en.UsingPython=An existing Python is used, nothing else is installed: %1
fr.UsingPython=Un Python d{é}j{à} install{é} est utilis{é}, rien d'autre n'est install{é} : %1
en.UsingEmbedded=No suitable Python (3.10 or more) was found: the Python bundled with this installer is copied into the Lutin folder.
fr.UsingEmbedded=Aucun Python adapt{é} (3.10 ou plus) n'a {é}t{é} trouv{é} : le Python fourni avec cet installateur est copi{é} dans le dossier de Lutin.
en.CreatingEnv=Preparing Lutin...
fr.CreatingEnv=Pr{é}paration de Lutin...
en.InstallFailed=Lutin could not be installed with the Python found (%1). Run the installer again after fixing it, or use the /EMBEDDED=1 option.
fr.InstallFailed=Lutin n'a pas pu {ê}tre install{é} avec le Python trouv{é} (%1). Relance l'installateur apr{è}s correction, ou utilise l'option /EMBARQUE=1.
en.ShortcutChat=Lutin (terminal)
fr.ShortcutChat=Lutin (terminal)

[Tasks]
Name: "path"; Description: "{cm:AddToPath}"

[InstallDelete]
; passer du Python embarque a un Python existant (ou l'inverse) ne laisse pas l'ancien environnement
Type: filesandordirs; Name: "{app}\python"; Check: not UseEmbedded
Type: filesandordirs; Name: "{app}\venv"; Check: UseEmbedded

[Files]
Source: "{#AppDir}\wheel\*"; DestDir: "{app}\wheel"; Flags: ignoreversion
Source: "{#AppDir}\source.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "lutin.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: UseEmbedded

[Icons]
Name: "{autoprograms}\Lutin"; Filename: "{app}\bin\lutin.cmd"; WorkingDir: "{userdocs}"; IconFilename: "{app}\lutin.ico"
Name: "{autoprograms}\{cm:ShortcutChat}"; Filename: "{app}\bin\lutin.cmd"; Parameters: "chat"; WorkingDir: "{userdocs}"; IconFilename: "{app}\lutin.ico"

[Run]
Filename: "{app}\bin\lutin.cmd"; Parameters: "setup"; Description: "{cm:RunSetup}"; Flags: postinstall skipifsilent nowait shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  PythonChemin: String;
  PythonTrouve: Boolean;

function UseEmbedded: Boolean;
begin
  Result := not PythonTrouve;
end;

function ExecuterEtLire(const Commande: String; var Sortie: String): Boolean;
var
  Tmp: String;
  Code: Integer;
  Lu: AnsiString;
begin
  Result := False;
  Sortie := '';
  Tmp := ExpandConstant('{tmp}\python-trouve.txt');
  DeleteFile(Tmp);
  if Exec(ExpandConstant('{cmd}'), '/C ' + Commande + ' > "' + Tmp + '" 2>nul', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then
    if LoadStringFromFile(Tmp, Lu) then
    begin
      Sortie := Trim(String(Lu));
      Result := Sortie <> '';
    end;
end;

function ChercherPython: Boolean;
var
  Sortie: String;
  Programme: String;
begin
  Result := False;
  if (ExpandConstant('{param:EMBEDDED|0}') = '1') or (ExpandConstant('{param:EMBARQUE|0}') = '1') then
    Exit;
  Programme := '-c "import sys;print(sys.executable) if sys.version_info>=(3,10) else sys.exit(1)"';
  if ExecuterEtLire('py -3 ' + Programme, Sortie) or ExecuterEtLire('python ' + Programme, Sortie) or ExecuterEtLire('python3 ' + Programme, Sortie) then
    if FileExists(Sortie) and (Pos('\windowsapps\', Lowercase(Sortie)) = 0) then
    begin
      PythonChemin := Sortie;
      Result := True;
    end;
end;

function InitializeSetup: Boolean;
begin
  PythonTrouve := ChercherPython;
  Result := True;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + MemoTasksInfo + NewLine + NewLine;
  if UseEmbedded then
    Result := Result + CustomMessage('UsingEmbedded')
  else
    Result := Result + FmtMessage(CustomMessage('UsingPython'), [PythonChemin]);
end;

function Lancer(const Programme, Parametres: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(Programme, Parametres, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

procedure PreparerAvecPython;
var
  Venv, Roue: String;
begin
  Venv := ExpandConstant('{app}\venv');
  Roue := ExpandConstant('{app}\wheel\{#WheelName}');
  if not WizardSilent then
    WizardForm.StatusLabel.Caption := CustomMessage('CreatingEnv');
  if not (Lancer(PythonChemin, '-m venv "' + Venv + '"') and
          Lancer(Venv + '\Scripts\python.exe', '-m pip install --upgrade --no-deps --no-index --quiet "' + Roue + '"')) then
    SuppressibleMsgBox(FmtMessage(CustomMessage('InstallFailed'), [PythonChemin]), mbError, MB_OK, IDOK);
end;

procedure EcrireLanceur;
var
  Python: String;
begin
  if UseEmbedded then
    Python := '%~dp0..\python\python.exe'
  else
    Python := '%~dp0..\venv\Scripts\python.exe';
  ForceDirectories(ExpandConstant('{app}\bin'));
  SaveStringToFile(ExpandConstant('{app}\bin\lutin.cmd'), '@echo off' + #13#10 + '"' + Python + '" -m lutin %*' + #13#10, False);
end;

procedure ModifierPath(Dossier: String; Ajouter: Boolean);
var
  Chemin, Cherche: String;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Chemin) then
    Chemin := '';
  Cherche := ';' + Lowercase(Dossier) + ';';
  P := Pos(Cherche, ';' + Lowercase(Chemin) + ';');
  if Ajouter then
  begin
    if P = 0 then
    begin
      if (Chemin <> '') and (Chemin[Length(Chemin)] <> ';') then
        Chemin := Chemin + ';';
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Chemin + Dossier);
    end;
  end
  else if P > 0 then
  begin
    Chemin := ';' + Chemin + ';';
    StringChangeEx(Chemin, ';' + Dossier + ';', ';', True);
    Chemin := Copy(Chemin, 2, Length(Chemin) - 2);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Chemin);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not UseEmbedded then
      PreparerAvecPython;
    EcrireLanceur;
    if WizardIsTaskSelected('path') then
      ModifierPath(ExpandConstant('{app}\bin'), True);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    ModifierPath(ExpandConstant('{app}\bin'), False);
end;
