# Construit l'installateur Windows : lutin-setup-<version>.exe (Inno Setup).
#   pwsh installateur/windows/construire.ps1 -Roue dist/lutin-0.2.0-py3-none-any.whl -Version 0.2.0
# L'installateur contient : la roue de Lutin ET un Python embarque (python.org). A l'installation, s'il y a deja un Python 3.10+ sur l'ordinateur, c'est lui qui est utilise
# (un environnement prive, comme install.ps1) et rien d'autre n'est installe ; sinon le Python embarque est copie dans le dossier de Lutin.
# Ce fichier reste en ASCII pur (voir tests/test_installation_cli.py).
param(
    [Parameter(Mandatory = $true)][string]$Roue,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Sortie = "dist",
    [string]$PythonVersion = "3.12.10"
)
$ErrorActionPreference = "Stop"
$racine = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$roue = (Resolve-Path $Roue).Path
$travail = Join-Path $racine "build\installateur"
if (Test-Path $travail) { Remove-Item -Recurse -Force $travail }
$app = Join-Path $travail "app"
New-Item -ItemType Directory -Force -Path $app | Out-Null

# 1. Python embarque (il n'a pas pip : on l'ajoute plus bas, pour que "lutin update" fonctionne)
$zip = Join-Path $travail "python-embed.zip"
$url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
Write-Host "Telechargement de $url"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
$python = Join-Path $app "python"
Expand-Archive -Path $zip -DestinationPath $python
$pth = Get-ChildItem $python -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth introuvable dans le Python embarque." }
$lignes = @(Get-Content $pth.FullName | Where-Object { $_ -ne "#import site" -and $_ -ne "import site" -and $_ -ne "Lib\site-packages" })
Set-Content -Path $pth.FullName -Value ($lignes + @("Lib\site-packages", "import site")) -Encoding ASCII

# 2. Lutin et pip dans le Python embarque (Lutin n'a aucune dependance : des fichiers Python purs, sans compilation)
$site = Join-Path $python "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $site | Out-Null
& python -m pip install --quiet --no-deps --target $site $roue pip
if ($LASTEXITCODE -ne 0) { throw "pip n'a pas pu preparer le Python embarque." }
$bin = Join-Path $site "bin"
if (Test-Path $bin) { Remove-Item -Recurse -Force $bin }
& (Join-Path $python "python.exe") -m lutin --version
if ($LASTEXITCODE -ne 0) { throw "Le Python embarque ne lance pas Lutin." }

# 3. La roue (pour l'installation avec un Python deja present) et la source de mise a jour
$dossierRoue = Join-Path $app "wheel"
New-Item -ItemType Directory -Force -Path $dossierRoue | Out-Null
Copy-Item $roue $dossierRoue
Set-Content -Path (Join-Path $app "source.txt") -Value "github:Slater-proj/lutin" -Encoding ASCII

# 4. Inno Setup
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($c in @((Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"), (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"), (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"))) {
        if (Test-Path $c) { $iscc = $c; break }
    }
}
if (-not $iscc) { throw "Inno Setup (ISCC.exe) introuvable : winget install JRSoftware.InnoSetup, ou choco install innosetup." }
$sortie = $Sortie
if (-not [IO.Path]::IsPathRooted($sortie)) { $sortie = Join-Path $racine $sortie }
New-Item -ItemType Directory -Force -Path $sortie | Out-Null
$numerique = ($Version -replace "^(\d+\.\d+\.\d+).*$", '$1') + ".0"
$nomFichier = "lutin-setup-" + ($Version -replace "[^0-9A-Za-z._-]", "-")
& $iscc "/Q" "/DVersion=$Version" "/DNumVersion=$numerique" "/DAppDir=$app" "/DWheelName=$(Split-Path $roue -Leaf)" "/O$sortie" "/F$nomFichier" (Join-Path $PSScriptRoot "lutin.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a echoue." }
Write-Host "Installateur : $(Join-Path $sortie ($nomFichier + '.exe'))"
