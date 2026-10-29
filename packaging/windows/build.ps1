# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Costruisce Helpix per Windows: Helpix.exe (PyInstaller, cartella dist\windows\Helpix) e il programma di
# installazione dist\packages\Helpix-<versione>-Setup.exe (Inno Setup 6).
#   pwsh packaging\windows\build.ps1            (da una macchina Windows con Python 3.13)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

Write-Host '-> Dipendenze di build'
python -m pip install --quiet --upgrade pip
python -m pip install --quiet . pyinstaller pillow
if ($LASTEXITCODE) { throw 'pip non riuscito' }

$assets = Join-Path $root 'build\windows'
$version = (python packaging\windows\make_assets.py $assets).Trim()
Write-Host "-> Helpix $version"

Write-Host '-> Helpix.exe (PyInstaller)'
python -m PyInstaller --noconfirm --clean --windowed --name Helpix `
    --icon "$assets\helpix.ico" --version-file "$assets\version.txt" `
    --collect-data helpix --collect-submodules helpix --collect-submodules winrt --hidden-import winpty `
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
    --distpath dist\windows --workpath build\pyinstaller --specpath build\pyinstaller `
    packaging\windows\helpix_main.py
if ($LASTEXITCODE) { throw 'PyInstaller non riuscito' }

# licenze e note dei componenti inclusi accanto al programma
$lic = 'dist\windows\Helpix\licenses'
New-Item -ItemType Directory -Force $lic | Out-Null
Copy-Item LICENSE, THIRD-PARTY-NOTICES.md, LICENSES\*.txt $lic
python -m pip list --format=freeze | Out-File -Encoding utf8 "$lic\BUNDLED-COMPONENTS.txt"

Write-Host '-> Programma di installazione (Inno Setup)'
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Host '   Inno Setup non trovato: lo installo con winget o choco'
    if (Get-Command choco -ErrorAction SilentlyContinue) { choco install innosetup -y --no-progress | Out-Null }
    else { winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements }
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
New-Item -ItemType Directory -Force dist\packages | Out-Null
& $iscc /Q "/DMyAppVersion=$version" packaging\windows\helpix.iss
if ($LASTEXITCODE) { throw 'Inno Setup non riuscito' }
Get-Item "dist\packages\Helpix-$version-Setup.exe" | ForEach-Object { '{0}  {1:N0} MB' -f $_.Name, ($_.Length / 1MB) }
