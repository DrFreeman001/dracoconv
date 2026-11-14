# Construit dist/dracoconv : le convertisseur utilisable sans Python (fenêtre et ligne de commande).
# Prérequis : .venv/Scripts/python -m pip install pyinstaller
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
& "$root/.venv/Scripts/python.exe" -m PyInstaller --noconfirm --distpath "$root/dist" --workpath "$root/build/pyinstaller" "$PSScriptRoot/dracoconv.spec"
if($LASTEXITCODE){throw 'PyInstaller failed'}
