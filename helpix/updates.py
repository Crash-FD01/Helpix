# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Avviso delle nuove versioni (Windows; su Linux gli aggiornamenti arrivano dal gestore pacchetti).

Una volta al giorno Helpix chiede a GitHub qual è l'ultima release pubblicata: l'indirizzo pubblico, senza
inviare nulla dell'utente. Si disattiva da Impostazioni › Avvisami delle nuove versioni.
"""
from __future__ import annotations

import re
import time

from . import __version__
from .system import IS_WINDOWS, SOURCE_URL

CHECK_EVERY = 20 * 3600  # secondi tra un controllo e l'altro


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
    return IS_WINDOWS


def due(settings) -> bool:
    if not settings.get("check_updates", enabled_by_default()):
        return False
    return time.time() - float(settings.get("updates_checked_at", 0) or 0) > CHECK_EVERY


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
    setup = next((a.get("browser_download_url") for a in data.get("assets") or []
                  if str(a.get("name", "")).lower().endswith("-setup.exe")), None)
    return {"version": tag.lstrip("v"), "url": data.get("html_url") or f"{SOURCE_URL}/releases/latest",
            "setup": setup}
