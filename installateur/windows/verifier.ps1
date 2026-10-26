# Verifie un installateur construit : installation silencieuse, reinstallation sans changement, mode "Python embarque", desinstallation.
#   pwsh installateur/windows/verifier.ps1 -Installateur dist/lutin-setup-0.2.0.exe -Version 0.2.0
# Rien n'est touche en dehors de dossiers temporaires : pas de PATH (aucune tache cochee), LUTIN_HOME dans un dossier temporaire.
# Ce fichier reste en ASCII pur.
param(
    [Parameter(Mandatory = $true)][string]$Installateur,
    [Parameter(Mandatory = $true)][string]$Version
)
$ErrorActionPreference = "Stop"
$exe = (Resolve-Path $Installateur).Path
$base = Join-Path ([IO.Path]::GetTempPath()) ("lutin-installateur-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $base | Out-Null
$env:LUTIN_HOME = Join-Path $base "donnees"
$env:LUTIN_LANGUE = "en"

function Echec($m) { Write-Host "ECHEC : $m"; exit 1 }

function Installer($dossier, $options) {
    $journal = Join-Path $base ("setup-" + [guid]::NewGuid().ToString("N").Substring(0, 6) + ".log")
    $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/TASKS=", "/DIR=$dossier", "/LOG=$journal") + $options
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -Wait -PassThru
    if ($p.ExitCode -ne 0) { Get-Content $journal -ErrorAction SilentlyContinue | Select-Object -Last 40; Echec "l'installateur a rendu le code $($p.ExitCode)" }
    return $journal
}

function Version-De($dossier) {
    $lanceur = Join-Path $dossier "bin\lutin.cmd"
    if (-not (Test-Path $lanceur)) { Echec "$lanceur n'existe pas" }
    $sortie = (& cmd /c "`"$lanceur`" --version" 2>&1) -join " "
    return $sortie
}

# 1. Installation avec le Python de l'ordinateur s'il y en a un (sinon l'installateur prend le Python embarque : les deux sont valables ici)
$un = Join-Path $base "un"
Installer $un @() | Out-Null
$v = Version-De $un
if ($v -notmatch [regex]::Escape($Version)) { Echec "version attendue $Version, obtenue : $v" }
$mode = if (Test-Path (Join-Path $un "venv\Scripts\python.exe")) { "Python existant (environnement prive)" } else { "Python embarque" }
Write-Host "Installation 1 : $v - $mode"
if (-not (Test-Path (Join-Path $un "source.txt"))) { Echec "source.txt manque (lutin update ne saurait pas d'ou se mettre a jour)" }

# 2. Reinstallation par-dessus : meme resultat, rien de casse
Installer $un @() | Out-Null
$v2 = Version-De $un
if ($v2 -ne $v) { Echec "apres reinstallation : $v2 au lieu de $v" }
Write-Host "Reinstallation : $v2"

# 3. Python embarque force
$deux = Join-Path $base "deux"
Installer $deux @("/EMBEDDED=1") | Out-Null
if (-not (Test-Path (Join-Path $deux "python\python.exe"))) { Echec "le Python embarque n'a pas ete copie" }
if (Test-Path (Join-Path $deux "venv")) { Echec "un environnement a ete cree malgre /EMBEDDED=1" }
$v3 = Version-De $deux
if ($v3 -notmatch [regex]::Escape($Version)) { Echec "Python embarque : $v3" }
$pip = (& (Join-Path $deux "python\python.exe") -m pip --version 2>&1) -join " "
if ($pip -notmatch "^pip ") { Echec "pip manque dans le Python embarque ($pip) : lutin update ne marcherait pas" }
Write-Host "Python embarque : $v3 ; $pip"

# 4. La commande de base fonctionne vraiment (pas seulement --version)
$s = (& cmd /c "`"$(Join-Path $deux 'bin\lutin.cmd')`" securite" 2>&1) -join " "
if ($s -notmatch "Level") { Echec "lutin securite : $s" }

# 5. Desinstallation
foreach ($d in @($un, $deux)) {
    $desinstalleur = Get-ChildItem $d -Filter "unins*.exe" | Select-Object -First 1
    if (-not $desinstalleur) { Echec "pas de desinstalleur dans $d" }
    $p = Start-Process -FilePath $desinstalleur.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
    if ($p.ExitCode -ne 0) { Echec "desinstallation : code $($p.ExitCode)" }
    for ($i = 0; $i -lt 20 -and (Test-Path $d); $i++) { Start-Sleep -Milliseconds 500 }
    if (Test-Path (Join-Path $d "bin")) { Echec "il reste des fichiers dans $d apres la desinstallation" }
}
Write-Host "Desinstallation : propre"
Remove-Item -Recurse -Force $base -ErrorAction SilentlyContinue
Write-Host "OK : l'installateur fonctionne."
