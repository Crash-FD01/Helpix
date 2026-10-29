; SPDX-FileCopyrightText: 2026 Crash
; SPDX-License-Identifier: GPL-3.0-or-later
;
; Programma di installazione di Helpix per Windows (Inno Setup 6).
; Si installa per l'utente, senza permessi di amministratore, in %LOCALAPPDATA%\Programs\Helpix (oppure, se lo
; scegli nella prima schermata, per tutti gli utenti). Impostazioni e accessi restano in %APPDATA% e
; %LOCALAPPDATA%\Helpix: aggiornare o disinstallare non li tocca.
;   iscc /DMyAppVersion=0.16.0 packaging\windows\helpix.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1C9F5E-3D2A-4C7B-9E80-4A1F2D6C8B35}
AppName=Helpix
AppVersion={#MyAppVersion}
AppVerName=Helpix {#MyAppVersion}
AppPublisher=Crash
AppPublisherURL=https://github.com/Crash-FD01/Helpix
AppSupportURL=https://github.com/Crash-FD01/Helpix/issues
AppUpdatesURL=https://github.com/Crash-FD01/Helpix/releases
AppCopyright=Copyright (C) 2026 Crash
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\Helpix
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist\packages
OutputBaseFilename=Helpix-{#MyAppVersion}-Setup
SetupIconFile=..\..\build\windows\helpix.ico
UninstallDisplayIcon={app}\Helpix.exe
UninstallDisplayName=Helpix
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1809: serve ConPTY per il terminale degli agenti
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; aggiornamento: via i file della versione prima, così non restano librerie vecchie
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\windows\Helpix\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Helpix"; Filename: "{app}\Helpix.exe"; Comment: "Assistente AI per risolvere i problemi del PC"
Name: "{autodesktop}\Helpix"; Filename: "{app}\Helpix.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Helpix.exe"; Description: "{cm:LaunchProgram,Helpix}"; Flags: nowait postinstall skipifsilent
