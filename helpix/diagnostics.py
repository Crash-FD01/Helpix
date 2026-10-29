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


def collect() -> str:
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
