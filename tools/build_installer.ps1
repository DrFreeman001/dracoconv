# Construit dist/dracoconv-<version>-setup.exe : PyInstaller (dist/dracoconv), puis Inno Setup 6.
# Prérequis : .venv/Scripts/python -m pip install pyinstaller ; Inno Setup 6 (winget install JRSoftware.InnoSetup --scope user).
param([switch]$SkipExe)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$version=(& "$root/.venv/Scripts/python.exe" -c "import dracoconv; print(dracoconv.__version__)").Trim()
if(-not $SkipExe){ & "$PSScriptRoot/build_exe.ps1" }
$iscc=@("$env:LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe", "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if(-not $iscc){throw 'Inno Setup 6 introuvable (winget install JRSoftware.InnoSetup --scope user)'}
& $iscc /Qp "/DAppVersion=$version" "$PSScriptRoot/installer/dracoconv.iss"
if($LASTEXITCODE){throw 'Inno Setup failed'}
Get-Item "$root/dist/dracoconv-$version-setup.exe"
