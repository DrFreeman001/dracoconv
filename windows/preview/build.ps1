param()
$ErrorActionPreference='Stop'
$vc='C:/Program Files (x86)/Microsoft Visual Studio/18/BuildTools/VC/Tools/MSVC/14.51.36231'
$sdk='C:/Program Files (x86)/Windows Kits/10'
$version='10.0.26100.0'
$env:INCLUDE="$vc/include;$sdk/Include/$version/ucrt;$sdk/Include/$version/um;$sdk/Include/$version/shared"
$env:LIB="$vc/lib/x64;$sdk/Lib/$version/ucrt/x64;$sdk/Lib/$version/um/x64"
New-Item -ItemType Directory -Force "$PSScriptRoot/build" | Out-Null
& "$vc/bin/Hostx64/x64/cl.exe" /nologo /utf-8 /EHsc /std:c++17 /W4 /DUNICODE /D_UNICODE "$PSScriptRoot/probe.cpp" /Fo"$PSScriptRoot/build/probe.obj" /Fe"$PSScriptRoot/build/probe.exe" /link ole32.lib shlwapi.lib gdi32.lib uuid.lib
if($LASTEXITCODE){throw 'Probe compile failed'}
if(Test-Path "$PSScriptRoot/bridge.cpp"){
& "$vc/bin/Hostx64/x64/cl.exe" /nologo /utf-8 /EHsc /std:c++17 /W4 /DUNICODE /D_UNICODE /LD "$PSScriptRoot/bridge.cpp" /Fo"$PSScriptRoot/build/bridge.obj" /Fe"$PSScriptRoot/build/DracoPreview.dll" /link /DEF:"$PSScriptRoot/bridge.def" ole32.lib shell32.lib shlwapi.lib gdi32.lib user32.lib uuid.lib windowscodecs.lib advapi32.lib
if($LASTEXITCODE){throw 'Bridge compile failed'}
}

foreach($name in @('preview_probe','cache_probe')) {
 & "$vc/bin/Hostx64/x64/cl.exe" /nologo /utf-8 /EHsc /std:c++17 "$PSScriptRoot/$name.cpp" /Fo"$PSScriptRoot/build/$name.obj" /Fe"$PSScriptRoot/build/$name.exe" /link ole32.lib shell32.lib shlwapi.lib user32.lib uuid.lib
 if($LASTEXITCODE){throw "$name compile failed"}
}

# Lecteur STEP : OpenCascade 8.0.1 (paquet conda-forge « novtk ») et ses DLL dans third_party, voir README.
$occt="$PSScriptRoot/../../third_party/occt-8.0.1/Library"
if(Test-Path "$occt/include/opencascade"){
 New-Item -ItemType Directory -Force "$PSScriptRoot/build/step" | Out-Null
 $env:INCLUDE="$env:INCLUDE;$occt/include/opencascade"
 $env:LIB="$env:LIB;$occt/lib"
 & "$vc/bin/Hostx64/x64/cl.exe" /nologo /utf-8 /EHsc /std:c++17 /O2 /MD /W3 /DUNICODE /D_UNICODE /DWNT "$PSScriptRoot/step_mesh.cpp" /Fo"$PSScriptRoot/build/step_mesh.obj" /Fe"$PSScriptRoot/build/step/step_mesh.exe" /link TKernel.lib TKMath.lib TKBRep.lib TKG2d.lib TKG3d.lib TKGeomBase.lib TKTopAlgo.lib TKMesh.lib TKDESTEP.lib TKXSBase.lib TKDE.lib
 if($LASTEXITCODE){throw 'step_mesh compile failed'}
 & "$PSScriptRoot/../../.venv/Scripts/python.exe" -I "$PSScriptRoot/stage_step.py" "$vc/bin/Hostx64/x64/dumpbin.exe"
 if($LASTEXITCODE){throw 'step_mesh staging failed'}
}
