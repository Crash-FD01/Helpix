# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Comandi su Windows: PowerShell, elevazione con UAC, regole di rischio, riconoscimento dei comandi copiati.

Ogni comando gira in un PowerShell nuovo e non interattivo. Lo script arriva codificato (-EncodedCommand), così
virgolette e caratteri speciali non creano problemi. La cartella corrente passa da un comando all'altro tramite un
file temporaneo (su Linux lo fa un descrittore dedicato).

Con «sudo» davanti (lo stesso modo che usa l'IA su Linux) il comando gira come amministratore: Windows mostra la
richiesta di Controllo account utente e l'output arriva da un file che il PowerShell elevato scrive man mano.
"""
from __future__ import annotations

import base64
import os
import re
import shutil

from .i18n import tr


def powershell() -> str:
    """PowerShell 7 se c'è (sintassi più moderna: &&, ||, ?:), altrimenti Windows PowerShell 5.1, sempre presente."""
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"


def powershell_version_label() -> str:
    return "PowerShell 7" if shutil.which("pwsh") else "Windows PowerShell 5.1"


def encode(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _q(value: str) -> str:
    """Stringa PowerShell tra apici singoli."""
    return "'" + value.replace("'", "''") + "'"


_PRELUDE = (
    "$ProgressPreference = 'SilentlyContinue'\n"
    "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}\n"
    "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
)


def script(cmd: str, cwd: str, cwd_file: str) -> str:
    """Script per un comando normale: esegue nella cartella giusta, poi annota la cartella finale e l'esito."""
    return (
        _PRELUDE
        + f"Set-Location -LiteralPath {_q(cwd)}\n"
        + "$global:LASTEXITCODE = 0\n"
        + "try {\n" + cmd + "\n} finally {\n"
        + "  $__ok = $?\n"
        + f"  try {{ [IO.File]::WriteAllText({_q(cwd_file)}, (Get-Location).ProviderPath) }} catch {{}}\n"
        + "}\n"
        + "if ($global:LASTEXITCODE) { exit $global:LASTEXITCODE }\n"
        + "if (-not $__ok) { exit 1 }\n"
    )


def elevated_script(cmd: str, cwd: str, out_file: str, rc_file: str) -> str:
    """Script che gira come amministratore: l'output va in out_file (letto da Helpix man mano), l'esito in rc_file."""
    return (
        _PRELUDE
        + f"Set-Location -LiteralPath {_q(cwd)}\n"
        + "$global:LASTEXITCODE = 0\n"
        + "$__ok = $true\n"
        + "try {\n"
        + "  & {\n" + cmd + "\n  } *>&1 | Out-File -LiteralPath " + _q(out_file) + " -Encoding utf8 -Width 4096 -Append\n"
        + "  $__ok = $?\n"
        + "} catch {\n"
        + "  $_ | Out-File -LiteralPath " + _q(out_file) + " -Encoding utf8 -Width 4096 -Append\n"
        + "  $__ok = $false\n"
        + "}\n"
        + "$__rc = if ($global:LASTEXITCODE) { $global:LASTEXITCODE } elseif ($__ok) { 0 } else { 1 }\n"
        + f"Set-Content -LiteralPath {_q(rc_file)} -Value $__rc -Encoding ascii\n"
    )


def launcher_script(elevated_b64: str) -> str:
    """Script non elevato che chiede l'UAC e aspetta il PowerShell elevato (nascosto)."""
    exe = powershell()
    return (
        "try {\n"
        f"  $p = Start-Process -FilePath {_q(exe)} -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
        f"-ArgumentList '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand','{elevated_b64}'\n"
        "  exit $p.ExitCode\n"
        "} catch {\n"
        "  [Console]::Error.WriteLine($_.Exception.Message)\n"
        "  exit 1223\n"  # ERROR_CANCELLED: richiesta di amministratore rifiutata
        "}\n"
    )


def argv(encoded: str) -> list[str]:
    return [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", encoded]


def kill_tree(pid: int) -> None:
    """Termina il processo e tutti i figli (su Windows non ci sono i gruppi di processi di Linux)."""
    import subprocess
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


# ------------------------------------------------------------------ analisi dei rischi
_P = r"(?i)"
DANGEROUS: list[tuple[re.Pattern, str]] = [
    (re.compile(_P + r"\b(Remove-Item|rm|ri|del|erase|rd|rmdir)\b[^\n;|]*\s-(r|re|rec|recu|recur|recurs|recurse)\b"),
     tr("cancellazione ricorsiva di file")),
    (re.compile(_P + r"\b(rd|rmdir)\b[^\n]*\s/s\b|\bdel\b[^\n]*\s/s\b"), tr("cancellazione ricorsiva di file")),
    (re.compile(_P + r"\b(Format-Volume|Clear-Disk|Initialize-Disk|Remove-Partition)\b|\bformat\s+[a-z]:"),
     tr("formattazione o cancellazione di un disco")),
    (re.compile(_P + r"\bdiskpart\b"), tr("modifica delle partizioni o cancellazione sicura")),
    (re.compile(_P + r"\bcipher\b[^\n]*\s/w\b"), tr("modifica delle partizioni o cancellazione sicura")),
    (re.compile(_P + r"\b(bcdedit|bootrec|bcdboot)\b"), tr("modifica dell'avvio di Windows")),
    (re.compile(_P + r"\breg(\.exe)?\s+delete\b|\bRemove-Item(Property)?\b[^\n;|]*\b(HKLM|HKEY_LOCAL_MACHINE|HKCR)"),
     tr("cancellazione di chiavi del registro di sistema")),
    (re.compile(_P + r"\b(Stop-Computer|Restart-Computer)\b|\bshutdown(\.exe)?\s+/[srpgh]\b"),
     tr("riavvio o spegnimento")),
    (re.compile(_P + r"\b(iwr|irm|curl|wget|Invoke-WebRequest|Invoke-RestMethod)\b[^\n;]*\|\s*(iex|Invoke-Expression)\b"
                r"|\b(iex|Invoke-Expression)\b[^\n;]*\b(iwr|irm|Invoke-WebRequest|Invoke-RestMethod|DownloadString)\b"),
     tr("esecuzione di uno script scaricato da Internet")),
    (re.compile(_P + r"\b(winget|choco|scoop)\s+uninstall\b|\b(Remove-AppxPackage|Remove-AppxProvisionedPackage|"
                r"Uninstall-Package|Uninstall-WindowsFeature|Disable-WindowsOptionalFeature)\b"),
     tr("rimozione di pacchetti")),
    (re.compile(_P + r"\b(Stop-Service|Set-Service|sc(\.exe)?\s+(stop|config|delete))\b[^\n;|]*\b(WinDefend|mpssvc|"
                r"Dhcp|Dnscache|LanmanWorkstation|LanmanServer|RpcSs|EventLog|wuauserv|BFE|Netlogon|W32Time)\b"),
     tr("arresto di un servizio essenziale")),
    (re.compile(_P + r"\b(Remove-LocalUser|Remove-ADUser|Remove-LocalGroup)\b|\bnet\s+(user|localgroup)\b[^\n]*/del"),
     tr("cancellazione di utenti o gruppi")),
    (re.compile(_P + r"\b(takeown|icacls)\b[^\n]*\s/(t|r)\b"), tr("modifica ricorsiva di permessi o proprietario")),
    (re.compile(_P + r"\bSet-MpPreference\b[^\n]*-Disable\w*\s+\$?true|\bnetsh\s+advfirewall\b[^\n]*\bstate\s+off\b|"
                r"\bSet-NetFirewallProfile\b[^\n]*-Enabled\s+\$?false"),
     tr("disattivazione delle protezioni di Windows (antivirus o firewall)")),
    (re.compile(_P + r"\bvssadmin\b[^\n]*\bdelete\b|\bwbadmin\b[^\n]*\bdelete\b|\bwmic\s+shadowcopy\s+delete\b"),
     tr("cancellazione delle copie di backup di Windows")),
    (re.compile(_P + r"\b(Clear-EventLog|wevtutil\s+cl)\b"), tr("cancellazione dei registri eventi")),
    (re.compile(_P + r"\bSet-ExecutionPolicy\b[^\n]*\b(Unrestricted|Bypass)\b[^\n]*\bLocalMachine\b"),
     tr("disattivazione dei controlli sugli script per tutto il PC")),
]

INTERACTIVE = {
    "ssh", "telnet", "ftp", "sftp", "python", "python3", "py", "node", "cmd", "powershell", "pwsh", "wsl", "bash",
    "nslookup", "diskpart", "netsh", "edit", "vim", "vi", "nano", "mysql", "psql", "sqlite3", "more", "notepad",
}
_INTERACTIVE_CALLS = re.compile(r"(?i)\b(Read-Host|Get-Credential|pause)\b")
FOLLOW = re.compile(r"(?i)\bGet-Content\b[^\n|;]*\s-Wait\b|\bping(\.exe)?\b[^\n|;]*\s-t\b")
# cmdlet di PowerShell: Verbo-Nome (Get-Service, Restart-NetAdapter…), non si trovano con shutil.which
CMDLET = re.compile(r"^[A-Z][a-z]+-[A-Za-z]+$")
BUILTINS = {"cd", "dir", "ls", "cat", "echo", "set", "type", "copy", "move", "del", "md", "mkdir", "cls", "pwd",
            "sl", "gci", "gcm", "gps", "gsv", "sls", "iwr", "irm", "if", "foreach", "for", "&", "."}
# «PS C:\Users\x> comando» o «C:\Users\x> comando» copiati dalla chat
PROMPT = re.compile(r"^\s*(?:PS\s+)?[A-Za-z]:\\[^>\n]*>\s*")


def interactive_reason(name: str, words: list[str]) -> str | None:
    base = os.path.splitext(name.lower())[0]
    if base in INTERACTIVE and len(words) == 1:
        return tr("«{name}» è un programma interattivo e qui non riceverebbe input").format(name=name)
    if base in ("ssh", "telnet", "ftp", "sftp", "edit", "vim", "vi", "nano", "notepad", "more"):
        return tr("«{name}» è un programma interattivo e qui non riceverebbe input").format(name=name)
    return None


def interactive_call(cmd: str) -> str | None:
    m = _INTERACTIVE_CALLS.search(cmd)
    if m:
        return tr("«{name}» è un programma interattivo e qui non riceverebbe input").format(name=m.group(1))
    return None


def is_command_word(name: str) -> bool:
    if name.startswith("$") or name in BUILTINS or name.lower() in BUILTINS:
        return True
    if CMDLET.match(name):
        return True
    if re.match(r"^\.?\.?[\\/]", name) or re.match(r"^[A-Za-z]:\\", name):  # .\script.ps1, C:\...\x.exe
        return True
    return bool(re.match(r"^[\w.+-]+$", name) and shutil.which(name))
