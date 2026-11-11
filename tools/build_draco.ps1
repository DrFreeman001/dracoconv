# Compile les outils officiels draco_encoder / draco_decoder (moteur de référence).
# Prérequis : git, les outils de compilation Microsoft C++, et le paquet pip « cmake » du .venv.
# Usage : pwsh tools/build_draco.ps1 [-Tag 1.5.7]
param([string]$Tag = "", [string]$WorkDir = "")
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
# Les sources sont compilées dans un dossier au chemin court : git et le compilateur
# échouent au-delà de 260 caractères, vite atteints si le projet est rangé profondément.
if (-not $WorkDir) { $WorkDir = Join-Path $env:LOCALAPPDATA "dracoconv\draco-src" }
$src = $WorkDir
New-Item -ItemType Directory -Force (Split-Path -Parent $src) | Out-Null
$build = Join-Path $src "build"
$bin = Join-Path $root "dracoconv\bin"
$cmake = Join-Path $root ".venv\Scripts\cmake.exe"
if (-not (Test-Path $cmake)) { $cmake = "cmake" }

if (-not (Test-Path $src)) {
    if (-not $Tag) {
        $Tag = git ls-remote --tags --refs https://github.com/google/draco |
            ForEach-Object { ($_ -split "refs/tags/")[1] } |
            Where-Object { $_ -match '^\d+\.\d+\.\d+$' } |
            Sort-Object { [version]$_ } |
            Select-Object -Last 1
    }
    Write-Host "Draco $Tag"
    git clone --quiet --depth 1 --branch $Tag https://github.com/google/draco $src
    if ($LASTEXITCODE -ne 0) { throw "git clone a échoué" }
}

& $cmake -S $src -B $build -DCMAKE_BUILD_TYPE=Release -DDRACO_TESTS=OFF
if ($LASTEXITCODE -ne 0) { throw "configuration cmake échouée" }
& $cmake --build $build --config Release --target draco_encoder draco_decoder --parallel
if ($LASTEXITCODE -ne 0) { throw "compilation échouée" }

New-Item -ItemType Directory -Force $bin | Out-Null
$exes = Get-ChildItem -Path $build -Recurse -Include draco_encoder.exe, draco_decoder.exe |
    Where-Object { $_.FullName -match '\\Release\\' -or $_.Directory.FullName -eq $build }
if ($exes.Count -lt 2) { throw "exécutables introuvables après compilation" }
$exes | Copy-Item -Destination $bin -Force
Write-Host "Outils copiés dans $bin"
& (Join-Path $bin "draco_encoder.exe") -h 2>&1 | Select-Object -First 20
