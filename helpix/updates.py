# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Controllo delle nuove versioni, su Windows e su Linux.

All'avvio (e poi una volta al giorno, se Helpix resta aperto) chiede a GitHub qual è l'ultima release pubblicata:
l'indirizzo pubblico, senza inviare nulla dell'utente. Se ce n'è una nuova propone di aggiornare:
- Windows: scarica il programma di installazione, ne controlla l'impronta con SHA256SUMS della release e lo avvia;
- Linux, pacchetto .deb/.rpm: aggiorna solo Helpix con il gestore pacchetti (la password la chiede il sistema);
- Linux, sistema immutabile o installazione dai sorgenti: mostra il comando da usare.
Si disattiva da Impostazioni › Avvisami delle nuove versioni.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from . import __version__
from .system import IS_WINDOWS, SOURCE_URL

CHECK_EVERY = 20 * 3600  # secondi tra un controllo e l'altro, mentre Helpix resta aperto


def _repo() -> str:
    return SOURCE_URL.rstrip("/").split("github.com/", 1)[1]


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return version_tuple(candidate) > version_tuple(current)
    except ValueError:
        return False


def enabled_by_default() -> bool:
    return True


def due(settings) -> bool:
    """Controllo attivo? (all'avvio si controlla sempre; il ritmo lo dà il timer della finestra)."""
    if os.environ.get("HELPIX_NO_UPDATE_CHECK"):  # test e screenshot: niente richieste a GitHub
        return False
    return bool(settings.get("check_updates", enabled_by_default()))


def latest_release(timeout: float = 10) -> dict | None:
    """Ultima release su GitHub: {"version", "url" (pagina), "setup" (installer per Windows, se c'è)}."""
    import requests
    try:
        r = requests.get(f"https://api.github.com/repos/{_repo()}/releases/latest", timeout=timeout,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": f"Helpix/{__version__}"})
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    tag = str(data.get("tag_name") or "")
    if not re.match(r"^v?\d+\.\d+", tag) or data.get("draft") or data.get("prerelease"):
        return None
    assets = {str(a.get("name", "")): a.get("browser_download_url") for a in data.get("assets") or []}
    setup = next((u for n, u in assets.items() if n.lower().endswith("-setup.exe")), None)
    return {"version": tag.lstrip("v"), "url": data.get("html_url") or f"{SOURCE_URL}/releases/latest",
            "setup": setup, "sums": assets.get("SHA256SUMS")}


# ------------------------------------------------------------------ come si aggiorna questa installazione
def install_kind() -> str:
    """«windows», «package» (.deb/.rpm in /opt/helpix), «immutable» (pacchetto su Fedora Atomic) o «source»."""
    if IS_WINDOWS:
        return "windows"
    here = Path(__file__).resolve()
    if str(here).startswith("/opt/helpix/"):
        return "immutable" if os.path.exists("/run/ostree-booted") else "package"
    return "source"


def linux_update_argv(pm: str | None) -> list[str] | None:
    """Comando (da eseguire come root) che aggiorna solo Helpix dal suo repository."""
    if pm == "apt":  # solo l'elenco di Helpix: veloce, e un altro repository rotto non lo blocca
        return ["sh", "-c", "apt-get update -q -o Dir::Etc::sourcelist=sources.list.d/helpix.list "
                            "-o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 && "
                            "DEBIAN_FRONTEND=noninteractive apt-get install -y -q --only-upgrade helpix"]
    if pm == "dnf":
        return ["dnf", "upgrade", "-y", "--refresh", "helpix"]
    if pm == "zypper":
        return ["sh", "-c", "zypper --non-interactive refresh helpix && zypper --non-interactive update helpix"]
    return None


def manual_hint(kind: str, pm: str | None) -> str:
    """Cosa fare a mano quando Helpix non può aggiornarsi da solo."""
    if kind == "immutable":
        return "sudo rpm-ostree upgrade"
    if kind == "source":
        return "git pull && ./install.sh"
    return {"apt": "sudo apt update && sudo apt install --only-upgrade helpix",
            "dnf": "sudo dnf upgrade --refresh helpix",
            "zypper": "sudo zypper refresh && sudo zypper update helpix"}.get(pm or "", "")


# ------------------------------------------------------------------ Windows: scarica e verifica l'installer
def download_setup(info: dict, timeout: float = 30) -> str:
    """Scarica l'installer della nuova versione nella cartella temporanea e ne controlla lo SHA-256 con il file
    SHA256SUMS della stessa release. Restituisce il percorso; solleva RuntimeError se qualcosa non torna."""
    import requests
    url, sums_url = info.get("setup"), info.get("sums")
    if not url or not sums_url:
        raise RuntimeError("la release non contiene l'installer o SHA256SUMS")
    headers = {"User-Agent": f"Helpix/{__version__}"}
    name = url.rsplit("/", 1)[-1]
    sums = requests.get(sums_url, timeout=timeout, headers=headers)
    sums.raise_for_status()
    expected = next((ln.split()[0].lower() for ln in sums.text.splitlines()
                     if len(ln.split()) == 2 and ln.split()[1].lstrip("*") == name), None)
    if not expected:
        raise RuntimeError(f"{name} non è elencato in SHA256SUMS")
    dest = Path(tempfile.gettempdir()) / name
    digest = hashlib.sha256()
    with requests.get(url, timeout=timeout, headers=headers, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                digest.update(chunk)
    if digest.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError("l'impronta del file scaricato non corrisponde a SHA256SUMS")
    return str(dest)


def setup_argv(path: str) -> list[str]:
    """Installer in modalità silenziosa (mostra solo l'avanzamento), che alla fine riapre Helpix."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]
