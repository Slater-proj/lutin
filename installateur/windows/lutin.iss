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
fr.AddToPath=Ajouter la commande "lutin" au PATH (conseillé)
en.RunLutin=Start Lutin now (the guided setup opens on the first start)
fr.RunLutin=Lancer Lutin maintenant (la configuration guidée s'ouvre au premier lancement)
en.UsingPython=An existing Python is used, nothing else is installed: %1
fr.UsingPython=Un Python déjà installé est utilisé, rien d'autre n'est installé : %1
en.UsingEmbedded=No suitable Python (3.10 or more) was found: the Python bundled with this installer is copied into the Lutin folder.
fr.UsingEmbedded=Aucun Python adapté (3.10 ou plus) n'a été trouvé : le Python fourni avec cet installateur est copié dans le dossier de Lutin.
en.CreatingEnv=Preparing Lutin...
fr.CreatingEnv=Préparation de Lutin...
en.InstallFailed=Lutin could not be installed with the Python found (%1). Run the installer again after fixing it, or use the /EMBEDDED=1 option.
fr.InstallFailed=Lutin n'a pas pu être installé avec le Python trouvé (%1). Relance l'installateur après correction, ou utilise l'option /EMBARQUE=1.
en.ShortcutChat=Lutin (terminal)
fr.ShortcutChat=Lutin (terminal)
en.AskDeleteData=Also delete your Lutin data (conversations, settings, memory) in:%n%n%1%n%2%n%nChoose No to keep them: a later installation finds them again. Your working folders and the files in them are never deleted.
fr.AskDeleteData=Supprimer aussi tes données Lutin (conversations, réglages, mémoire) dans :%n%n%1%n%2%n%nChoisis Non pour les garder : une installation ultérieure les retrouve. Tes dossiers de travail et leurs fichiers ne sont jamais supprimés.
en.LeftOver=These items of %1 could not be removed:%n%n%2%n%nWhy: a program still uses them (a terminal or a File Explorer window open in this folder, an antivirus scanning it, or a program started from it). Close it, then delete the folder by hand, or restart the computer and delete it.
fr.LeftOver=Ces éléments de %1 n'ont pas pu être supprimés :%n%n%2%n%nPourquoi : un programme les utilise encore (un terminal ou une fenêtre de l'Explorateur ouverts dans ce dossier, un antivirus qui l'analyse, ou un programme lancé depuis ce dossier). Ferme-le, puis supprime le dossier à la main, ou redémarre l'ordinateur et supprime-le.

[Tasks]
Name: "path"; Description: "{cm:AddToPath}"

[InstallDelete]
; passer du Python embarque a un Python existant (ou l'inverse) ne laisse pas l'ancien environnement
Type: filesandordirs; Name: "{app}\python"; Check: not UseEmbedded
Type: filesandordirs; Name: "{app}\venv"; Check: UseEmbedded
; mise a jour par-dessus un Python embarque deja installe : les anciens fichiers de Lutin (et leurs metadonnees de version) partent avant la copie des nouveaux
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\lutin"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\lutin-*"

[Files]
Source: "{#AppDir}\wheel\*"; DestDir: "{app}\wheel"; Flags: ignoreversion
Source: "{#AppDir}\source.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "lutin.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: UseEmbedded

[Icons]
Name: "{autoprograms}\Lutin"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m lutin zone"; WorkingDir: "{userdocs}"; IconFilename: "{app}\lutin.ico"; Check: UseEmbedded
Name: "{autoprograms}\Lutin"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: "-m lutin zone"; WorkingDir: "{userdocs}"; IconFilename: "{app}\lutin.ico"; Check: not UseEmbedded
Name: "{autoprograms}\{cm:ShortcutChat}"; Filename: "{app}\bin\lutin.cmd"; Parameters: "chat"; WorkingDir: "{userdocs}"; IconFilename: "{app}\lutin.ico"

[Run]
; Lutin sans console (icone en bas a droite) ; au premier lancement, l'installation guidee s'ouvre toute seule dans une console
Filename: "{app}\python\pythonw.exe"; Parameters: "-m lutin zone"; WorkingDir: "{userdocs}"; Description: "{cm:RunLutin}"; Flags: postinstall skipifsilent nowait; Check: UseEmbedded
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: "-m lutin zone"; WorkingDir: "{userdocs}"; Description: "{cm:RunLutin}"; Flags: postinstall skipifsilent nowait; Check: not UseEmbedded

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

{ Lutin tourne en arriere-plan (icone en bas a droite, serveur) : tant qu'il tourne, Windows garde ses fichiers ouverts et ni la mise a jour ni la desinstallation ne peuvent les remplacer ou les supprimer.
  On l'arrete donc d'abord : tous les programmes lances depuis le dossier de Lutin (jamais l'installateur ni le desinstalleur eux-memes). }
procedure ArreterLutin;
var
  Script: String;
  Code: Integer;
begin
  Script := ExpandConstant('{tmp}\arreter-lutin.ps1');
  SaveStringToFile(Script,
    'param([string]$Dossier)' + #13#10 +
    '$racine = $Dossier.TrimEnd([char]92) + [char]92' + #13#10 +
    'Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($racine, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -notlike ''unins*'' -and $_.Name -notlike ''_iu*'' -and $_.Name -notlike ''_unin*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }' + #13#10, False);
  Exec('powershell.exe', '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '" "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(700);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if DirExists(ExpandConstant('{app}')) then
    ArreterLutin;
  Result := '';
end;

{ Ce qui reste dans un dossier, sans le desinstalleur lui-meme (il s'efface en dernier) : au plus 12 lignes. }
procedure ListerRestes(Dossier, Prefixe: String; var Liste: String; var Nombre: Integer);
var
  Trouve: TFindRec;
begin
  if FindFirst(Dossier + '\*', Trouve) then
  try
    repeat
      if (Trouve.Name <> '.') and (Trouve.Name <> '..') and (Pos('unins', Lowercase(Trouve.Name)) <> 1) then
      begin
        if Nombre < 12 then
          Liste := Liste + '  ' + Prefixe + Trouve.Name + #13#10;
        Nombre := Nombre + 1;
        if (Trouve.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          ListerRestes(Dossier + '\' + Trouve.Name, Prefixe + Trouve.Name + '\', Liste, Nombre);
      end;
    until not FindNext(Trouve);
  finally
    FindClose(Trouve);
  end;
end;

{ Supprime tout ce qui reste dans le dossier, sauf le desinstalleur (il s'efface lui-meme en dernier). }
procedure NettoyerRestes(Dossier: String);
var
  Trouve: TFindRec;
begin
  if FindFirst(Dossier + '\*', Trouve) then
  try
    repeat
      if (Trouve.Name <> '.') and (Trouve.Name <> '..') and (Pos('unins', Lowercase(Trouve.Name)) <> 1) then
      begin
        if (Trouve.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DelTree(Dossier + '\' + Trouve.Name, True, True, True)
        else
          DeleteFile(Dossier + '\' + Trouve.Name);
      end;
    until not FindNext(Trouve);
  finally
    FindClose(Trouve);
  end;
end;

procedure VerifierRestes;
var
  Dossier, Liste: String;
  Nombre, Essai: Integer;
begin
  Dossier := ExpandConstant('{app}');
  for Essai := 1 to 3 do
  begin
    Liste := '';
    Nombre := 0;
    if DirExists(Dossier) then
      ListerRestes(Dossier, '', Liste, Nombre);
    if Nombre = 0 then
      Break;
    if Essai < 3 then
    begin
      ArreterLutin;
      NettoyerRestes(Dossier);
    end;
  end;
  if Nombre > 12 then
    Liste := Liste + '  ... (' + IntToStr(Nombre - 12) + ')' + #13#10;
  if (Nombre > 0) and not UninstallSilent then
    MsgBox(FmtMessage(CustomMessage('LeftOver'), [Dossier, Liste]), mbInformation, MB_OK);
end;

procedure SupprimerDonnees;
var
  Config, Cache: String;
begin
  if UninstallSilent then
    Exit;
  Config := GetEnv('LUTIN_HOME');
  if Config <> '' then
    Cache := ''
  else
  begin
    Config := ExpandConstant('{userappdata}\Lutin');
    Cache := ExpandConstant('{localappdata}\Lutin');
  end;
  if not DirExists(Config) then
    Exit;
  if MsgBox(FmtMessage(CustomMessage('AskDeleteData'), [Config, Cache]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(Config, True, True, True);
    if Cache <> '' then
      DelTree(Cache, True, True, True);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    ArreterLutin;
    ModifierPath(ExpandConstant('{app}\bin'), False);
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    VerifierRestes;
    SupprimerDonnees;
  end;
end;
