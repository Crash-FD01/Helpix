# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Costruisce Helpix per Windows: Helpix.exe (PyInstaller, cartella dist\windows\Helpix) e il programma di
# installazione dist\packages\Helpix-<versione>-Setup.exe (Inno Setup 6).
#   pwsh packaging\windows\build.ps1            (da una macchina Windows con Python 3.13)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

# PowerShell 7 incluso nel programma (licenza MIT): Helpix esegue tutto con questo, non con powershell.exe di
# sistema. Per aggiornarlo: nuova versione LTS da https://github.com/PowerShell/PowerShell/releases e il suo SHA-256.
$pwshVersion = '7.6.9'
$pwshSha256 = 'ce7484804c0f0ad4dda10c958e71acdaf7eebfb22505c1b480f89e0e9f1da94d'

Write-Host '-> Dipendenze di build'
python -m pip install --quiet --upgrade pip
python -m pip install --quiet . pyinstaller pillow
if ($LASTEXITCODE) { throw 'pip non riuscito' }

$assets = Join-Path $root 'build\windows'
$version = (python packaging\windows\make_assets.py $assets).Trim()
Write-Host "-> Helpix $version"

Write-Host '-> Helpix.exe (PyInstaller)'
# --collect-all winpty: oltre al modulo servono conpty.dll e OpenConsole.exe, che pywinpty carica a runtime per il
# terminale degli agenti (PyInstaller da solo non li vede: senza, il terminale resta vuoto)
python -m PyInstaller --noconfirm --clean --windowed --name Helpix `
    --icon "$assets\helpix.ico" --version-file "$assets\version.txt" `
    --collect-data helpix --collect-submodules helpix --collect-submodules winrt --collect-all winpty `
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
    --distpath dist\windows --workpath build\pyinstaller --specpath build\pyinstaller `
    packaging\windows\helpix_main.py
if ($LASTEXITCODE) { throw 'PyInstaller non riuscito' }

Write-Host "-> PowerShell $pwshVersion"
$zip = "build\PowerShell-$pwshVersion-win-x64.zip"
if (-not (Test-Path $zip)) {
    New-Item -ItemType Directory -Force build | Out-Null
    Invoke-WebRequest -UseBasicParsing -OutFile $zip `
        "https://github.com/PowerShell/PowerShell/releases/download/v$pwshVersion/PowerShell-$pwshVersion-win-x64.zip"
}
$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
if ($hash -ne $pwshSha256) { Remove-Item $zip; throw "PowerShell ${pwshVersion}: SHA-256 diverso ($hash)" }
$pwshDir = 'dist\windows\Helpix\pwsh'
if (Test-Path $pwshDir) { Remove-Item -Recurse -Force $pwshDir }
Expand-Archive -Path $zip -DestinationPath $pwshDir
$sig = Get-AuthenticodeSignature "$pwshDir\pwsh.exe"
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw "pwsh.exe: firma di Microsoft non valida ($($sig.Status), $($sig.SignerCertificate.Subject))"
}
$v = & "$pwshDir\pwsh.exe" -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.ToString()'
if ($v -ne $pwshVersion) { throw "pwsh.exe incluso: versione $v invece di $pwshVersion" }

# licenze e note dei componenti inclusi accanto al programma
$lic = 'dist\windows\Helpix\licenses'
New-Item -ItemType Directory -Force $lic | Out-Null
Copy-Item LICENSE, THIRD-PARTY-NOTICES.md, LICENSES\*.txt $lic
Copy-Item "$pwshDir\LICENSE.txt" "$lic\PowerShell-LICENSE.txt"
Copy-Item "$pwshDir\ThirdPartyNotices.txt" "$lic\PowerShell-ThirdPartyNotices.txt"
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
