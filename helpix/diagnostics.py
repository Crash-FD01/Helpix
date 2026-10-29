# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnosi rapida: raccoglie informazioni di base sul PC con comandi in sola lettura.

Il testo viene mostrato all'utente prima di essere incollato nella chat, perché
contiene dati come nome del computer e indirizzi IP.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .prompts import system_info
from .i18n import tr

CHECKS: list[tuple[str, str]] = [
    (tr("Tempo di attività e carico"), "uptime"),
    (tr("Spazio su disco"), "df -h -x tmpfs -x devtmpfs -x squashfs -x overlay"),
    (tr("Memoria"), "free -h"),
    (tr("Interfacce di rete"), "ip -br address"),
    (tr("Stato della rete"), "nmcli -t -f STATE,CONNECTIVITY,WIFI general"),
    (tr("Connessioni attive"), "nmcli -t -f NAME,TYPE,DEVICE connection show --active"),
    (tr("Rotta predefinita e DNS"), "ip route show default; resolvectl dns 2>/dev/null | head -5"),
    (tr("Servizi in errore"), "systemctl --failed --no-pager --no-legend"),
    (tr("Errori dall'ultimo avvio"), "journalctl -b -p err --no-pager -n 25 -o short-monotonic"),
]
MAX_CHARS = 9000


def _run(cmd: str, timeout: int = 6) -> str:
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, errors="replace",
                           env={**os.environ, "LC_ALL": "C.UTF-8", "SYSTEMD_PAGER": "cat", "SYSTEMD_COLORS": "0"})
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return tr("(nessuna risposta entro il tempo limite)")


# Windows: tutti i controlli in un solo PowerShell (avviarlo costa circa un secondo ciascuno)
WINDOWS_CHECKS: list[tuple[str, str]] = [
    (tr("Sistema, avvio e memoria"),
     "$o = Get-CimInstance Win32_OperatingSystem; '{0} {1} (build {2})' -f $o.Caption, $o.OSArchitecture, $o.BuildNumber;"
     " 'Last boot: {0}' -f $o.LastBootUpTime;"
     " 'RAM: {0:N1} GB free of {1:N1} GB' -f ($o.FreePhysicalMemory/1MB), ($o.TotalVisibleMemorySize/1MB)"),
    (tr("Spazio su disco"),
     "Get-PSDrive -PSProvider FileSystem | Where-Object Used -ne $null | ForEach-Object {"
     " '{0}:  {1:N1} GB free of {2:N1} GB' -f $_.Name, ($_.Free/1GB), (($_.Used+$_.Free)/1GB) }"),
    (tr("Interfacce di rete"),
     "Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' } | ForEach-Object {"
     " '{0}: IP {1}, gateway {2}, DNS {3}' -f $_.InterfaceAlias, ($_.IPv4Address.IPAddress -join ', '),"
     " ($_.IPv4DefaultGateway.NextHop -join ', '), ($_.DNSServer.ServerAddresses -join ', ') }"),
    (tr("Stato della rete"),
     "Get-NetConnectionProfile | ForEach-Object { '{0} ({1}): IPv4 {2}, IPv6 {3}, category {4}' -f $_.Name,"
     " $_.InterfaceAlias, $_.IPv4Connectivity, $_.IPv6Connectivity, $_.NetworkCategory }"),
    (tr("Servizi automatici fermi"),
     "Get-CimInstance Win32_Service -Filter \"StartMode='Auto' AND State<>'Running'\" | Select-Object -First 15 |"
     " ForEach-Object { '{0} ({1}): {2}, exit code {3}' -f $_.Name, $_.DisplayName, $_.State, $_.ExitCode }"),
    (tr("Errori delle ultime 24 ore"),
     "Get-WinEvent -FilterHashtable @{LogName='System','Application'; Level=1,2; StartTime=(Get-Date).AddHours(-24)}"
     " -MaxEvents 25 -ErrorAction SilentlyContinue | ForEach-Object { '{0:dd/MM HH:mm} {1} ({2}): {3}' -f"
     " $_.TimeCreated, $_.ProviderName, $_.Id, (($_.Message -split \"`r?`n\")[0]) }"),
    (tr("Riavvio in attesa"),
     "$r = (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired')"
     " -or (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending');"
     " if ($r) { 'yes' } else { 'no' }"),
    (tr("Antivirus (Microsoft Defender)"),
     "$m = Get-MpComputerStatus -ErrorAction Stop; 'Real-time protection: {0}; signatures updated {1:yyyy-MM-dd}' -f"
     " $m.RealTimeProtectionEnabled, $m.AntivirusSignatureLastUpdated"),
]


def _windows_sections() -> list[tuple[str, str, str]]:
    """Esegue i controlli di Windows in un solo PowerShell; restituisce (titolo, comando, output)."""
    from .winshell import argv, encode
    marker = "@@HELPIX-SECTION@@"
    script = "$ProgressPreference='SilentlyContinue'\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\n"
    for i, (_title, cmd) in enumerate(WINDOWS_CHECKS):
        script += (f"'{marker}{i}'\ntry {{ & {{ {cmd} }} | Out-String -Width 220 }} "
                   "catch { '(' + $_.Exception.Message + ')' }\n")
    try:
        r = subprocess.run(argv(encode(script)), capture_output=True, timeout=40, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return [(WINDOWS_CHECKS[0][0], "", tr("(nessuna risposta entro il tempo limite)"))]
    out: list[tuple[str, str, str]] = []
    for chunk in text.split(marker)[1:]:
        num, _, body = chunk.partition("\n")
        try:
            title, cmd = WINDOWS_CHECKS[int(num.strip())]
        except (ValueError, IndexError):
            continue
        out.append((title, cmd.split(";")[0].split("|")[0].strip(), body.strip()))
    return out


def _collect_windows() -> str:
    info = system_info()
    parts = [
        tr("Ciao, ho un problema sul mio PC Windows. Ecco le informazioni di sistema raccolte da Helpix "
           "(un'app di troubleshooting). Quando mi proponi dei comandi, usa PowerShell, scrivine uno per blocco di "
           "codice e usa solo comandi non interattivi: li eseguirò e ti incollerò l'output."),
        "",
        tr("- Sistema: {distro} ({arch})").format(**info),
        tr("- Shell: {shell}; gestori di pacchetti: {pkg}").format(**info),
        "",
    ]
    for title, cmd, out in _windows_sections():
        out = out or tr("(nessun risultato)")
        if len(out) > 1800:
            out = out[:1800] + "\n[…]"
        parts += [f"**{title}**", "```", out, "```", ""]
    text = "\n".join(parts).strip()
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + tr("\n[…troncato]")


def collect() -> str:
    from .system import IS_WINDOWS
    if IS_WINDOWS:
        return _collect_windows()
    info = system_info()
    parts = [
        tr("Ciao, ho un problema sul mio PC Linux. Ecco le informazioni di sistema raccolte da Helpix "
        "(un'app di troubleshooting). Quando mi proponi dei comandi, scrivine uno per blocco di codice "
        "e usa solo comandi non interattivi: li eseguirò e ti incollerò l'output."),
        "",
        tr("- Sistema: {distro} ({arch}), kernel {kernel}").format(**info),
        tr("- Desktop: {desktop} (sessione {session})").format(**info),
        tr("- Gestore pacchetti: {pkg}; altri formati: {extra}").format(**info),
        "",
    ]
    for title, cmd in CHECKS:
        if not shutil.which(cmd.split()[0]):
            continue
        out = _run(cmd) or tr("(nessun risultato)")
        if len(out) > 1800:
            out = out[:1800] + "\n[…]"
        parts += [f"**{title}** (`{cmd.split(';')[0]}`)", "```", out, "```", ""]
    text = "\n".join(parts).strip()
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + tr("\n[…troncato]")
