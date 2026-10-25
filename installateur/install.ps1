# Installe ou met a jour Lutin pour l'utilisateur courant (sans droits administrateur) :
#   irm https://raw.githubusercontent.com/Slater-proj/lutin/main/installateur/install.ps1 | iex
# Ce que fait ce script, et rien d'autre :
#   1. cherche Python 3.10 ou plus ; sinon l'installe pour l'utilisateur avec winget (Python.Python.3.12)
#   2. cree (ou reutilise) un environnement prive dans %LOCALAPPDATA%\Programs\Lutin et y installe Lutin
#      - deja installe a la meme version : il ne change rien et le dit ; version differente : mise a jour
#   3. ajoute la commande « lutin » au PATH de l'utilisateur (une seule fois)
#   4. lance « lutin setup » (sans effet si Lutin est deja configure) sauf avec -SansSetup
# Parametres : -Source (ou variable LUTIN_SOURCE) = ce qu'il faut passer a pip (une roue, une adresse) ; par defaut : la derniere publication GitHub de Slater-proj/lutin.
#              -Dossier = ou installer (defaut : %LOCALAPPDATA%\Programs\Lutin) ; -SansPath = ne pas toucher au PATH ; -SansSetup.
param([switch]$SansSetup, [switch]$SansPath, [string]$Source = $env:LUTIN_SOURCE, [string]$Dossier = "")

$ErrorActionPreference = "Stop"
function Info($m)  { Write-Host "[Lutin] $m" -ForegroundColor Cyan }
function Echec($m) { Write-Host "[ERREUR] $m" -ForegroundColor Red; exit 1 }

# Sans -Source : la derniere publication de https://github.com/Slater-proj/lutin (jamais le nom nu « lutin » sur PyPI : c'est un autre projet).
$marqueur = ""
if (-not $Source) { $marqueur = "github:Slater-proj/lutin" }
$dossier = if ($Dossier) { $Dossier } else { Join-Path $env:LOCALAPPDATA "Programs\Lutin" }
$venv    = Join-Path $dossier "venv"
$bin     = Join-Path $dossier "bin"
$pyvenv  = Join-Path $venv "Scripts\python.exe"

function Trouver-Python {
    foreach ($cmd in @(@("py", "-3"), @("python"), @("python3"))) {
        $exe = Get-Command $cmd[0] -ErrorAction SilentlyContinue
        if (-not $exe -or $exe.Source -like "*\WindowsApps\*") { continue }       # le faux python du Microsoft Store n'est pas un vrai Python
        $args = @($cmd | Select-Object -Skip 1) + @("-c", "import sys; print(int(sys.version_info >= (3, 10)))")
        try { if ((& $exe.Source @args 2>$null) -eq "1") { return @($exe.Source) + @($cmd | Select-Object -Skip 1) } } catch { }
    }
    return $null
}

function Version-Installee {
    if (-not (Test-Path $pyvenv)) { return "" }
    try { $v = (& $pyvenv -m lutin --version 2>$null); if ($LASTEXITCODE -eq 0 -and $v) { return ($v -replace "^Lutin\s*", "").Trim() } } catch { }
    return ""
}

$avant = Version-Installee
if (-not (Test-Path $pyvenv)) {
    $python = Trouver-Python
    if (-not $python) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Echec "Python 3.10 ou plus est requis. Installe-le depuis https://www.python.org/downloads/ puis relance ce script." }
        Info "Python n'est pas installe : installation pour l'utilisateur courant (winget)..."
        winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $python = Trouver-Python
        if (-not $python) {
            $essai = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
            if ($essai) { $python = @($essai.FullName) } else { Echec "Python est installe mais introuvable : ferme cette fenetre, ouvre-en une nouvelle et relance le script." }
        }
    }
    Info "Python : $($python -join ' ')"
    New-Item -ItemType Directory -Force -Path $dossier | Out-Null
    Info "Creation de l'environnement prive..."
    & $python[0] @($python | Select-Object -Skip 1) -m venv $venv
    if ($LASTEXITCODE -ne 0) { Echec "Impossible de creer l'environnement Python." }
}
New-Item -ItemType Directory -Force -Path $bin | Out-Null

function Resoudre-Derniere-Release($depot) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12          # GitHub refuse les anciens protocoles (Windows PowerShell 5.1)
    try { $r = Invoke-RestMethod "https://api.github.com/repos/$depot/releases/latest" -Headers @{ "User-Agent" = "lutin-installation" } -TimeoutSec 30 }
    catch { Echec "Impossible de lire la derniere version de Lutin sur GitHub ($depot) : $($_.Exception.Message). Pas d'internet, ou pas encore de publication : passe -Source <fichier.whl ou adresse> pour installer autrement." }
    $roue = $r.assets | Where-Object { $_.name -like "*.whl" } | Select-Object -First 1
    if (-not $roue) { Echec "La derniere publication de $depot n'a pas de fichier .whl." }
    return $roue.browser_download_url
}
if ($marqueur) { $Source = Resoudre-Derniere-Release "Slater-proj/lutin" }

Info "Verification de Lutin ($Source)..."
& $pyvenv -m pip install --upgrade --quiet pip
& $pyvenv -m pip install --upgrade --quiet $Source
if ($LASTEXITCODE -ne 0) { Echec "pip n'a pas pu installer Lutin ($Source)." }
$apres = Version-Installee
if (-not $apres) { Echec "Lutin est installe mais ne repond pas (« python -m lutin --version »)." }
Set-Content -Path (Join-Path $dossier "source.txt") -Value $(if ($marqueur) { $marqueur } else { $Source }) -Encoding ASCII          # pour « lutin update »
if (-not $avant) { Info "Lutin $apres installe." }
elseif ($avant -eq $apres) { Info "Lutin $apres : deja a jour, rien a faire." }
else { Info "Lutin mis a jour : $avant -> $apres." }

# La commande « lutin » : un petit lanceur dans un dossier ajoute au PATH de l'utilisateur.
$lanceur = Join-Path $bin "lutin.cmd"
$contenu = "@echo off`r`n`"$pyvenv`" -m lutin %*`r`n"
if (-not (Test-Path $lanceur) -or ((Get-Content -Raw $lanceur) -ne $contenu)) { Set-Content -Path $lanceur -Value $contenu -Encoding ASCII -NoNewline }
if (-not $SansPath) {
    $chemin = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($chemin -split ";") -notcontains $bin) {
        [Environment]::SetEnvironmentVariable("Path", ($chemin.TrimEnd(";") + ";" + $bin), "User")
        Info "Dossier ajoute au PATH : $bin (ouvre une nouvelle fenetre pour utiliser « lutin » partout)."
    }
}
$env:Path += ";$bin"

if (-not $SansSetup) { & $lanceur setup }
else { Write-Host "Pour continuer :  lutin setup" }
