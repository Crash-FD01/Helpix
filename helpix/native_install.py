# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Registra l'host di native messaging di Helpix nei browser dell'utente.

Scrive un piccolo lanciatore e i manifest nelle cartelle che i browser leggono:
Chrome, Chromium, Edge, Brave, Vivaldi, Opera (formato Chromium) e Firefox.
Non servono permessi di root: tutto avviene nella home dell'utente.

Uso: python -m helpix.native_install [--uninstall] [--extra-id ID ...]
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

HOST_NAME = "com.helpix.bridge"
CHROME_EXTENSION_ID = "kcnapjkchmgjacppmmajcddjoemeahdj"   # derivato dalla chiave in manifest.json
FIREFOX_EXTENSION_ID = "helpix@crash-fd01.github.io"
DESCRIPTION = "Helpix — collegamento tra il browser e l'app"

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share")
LAUNCHER = DATA / "helpix" / "bridge" / "helpix-bridge"

CHROMIUM_DIRS = {
    "Google Chrome": CONFIG / "google-chrome",
    "Chrome Beta": CONFIG / "google-chrome-beta",
    "Chromium": CONFIG / "chromium",
    "Microsoft Edge": CONFIG / "microsoft-edge",
    "Brave": CONFIG / "BraveSoftware" / "Brave-Browser",
    "Vivaldi": CONFIG / "vivaldi",
    "Opera": CONFIG / "opera",
}
FIREFOX_DIRS = {
    "Firefox": HOME / ".mozilla",
    "LibreWolf": HOME / ".librewolf",
}
# browser installati come Flatpak/Snap: sono isolati e di norma non possono avviare l'host
SANDBOXED = {
    "Chrome (Flatpak)": HOME / ".var" / "app" / "com.google.Chrome",
    "Chromium (Flatpak)": HOME / ".var" / "app" / "org.chromium.Chromium",
    "Firefox (Flatpak)": HOME / ".var" / "app" / "org.mozilla.firefox",
    "Firefox (Snap)": HOME / "snap" / "firefox",
    "Brave (Flatpak)": HOME / ".var" / "app" / "com.brave.Browser",
}


def helpix_command() -> str:
    """Comando per avviare l'app (lo usa l'host se Helpix non è aperto)."""
    exe = shutil.which("helpix")
    if exe:
        return shlex.quote(exe)
    return f"{shlex.quote(sys.executable)} -m helpix"


def write_launcher() -> Path:
    host = Path(__file__).with_name("bridge_host.py").resolve()
    LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "#!/bin/sh\n"
        "# Avviato dal browser per collegare l'estensione a Helpix.\n"
        f"export HELPIX_CMD={shlex.quote(helpix_command())}\n"
        f"exec {shlex.quote(sys.executable)} -I {shlex.quote(str(host))} \"$@\"\n"
    )
    LAUNCHER.write_text(script, encoding="utf-8")
    LAUNCHER.chmod(LAUNCHER.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)
    return LAUNCHER


def chromium_manifest(extra_ids=()) -> dict:
    ids = [CHROME_EXTENSION_ID, *extra_ids]
    return {"name": HOST_NAME, "description": DESCRIPTION, "path": str(LAUNCHER), "type": "stdio",
            "allowed_origins": [f"chrome-extension://{i}/" for i in dict.fromkeys(ids)]}


def firefox_manifest() -> dict:
    return {"name": HOST_NAME, "description": DESCRIPTION, "path": str(LAUNCHER), "type": "stdio",
            "allowed_extensions": [FIREFOX_EXTENSION_ID]}


def targets() -> list[tuple[str, Path, str]]:
    """(browser, file del manifest, tipo) per i browser presenti nella home."""
    out = []
    for name, base in CHROMIUM_DIRS.items():
        if base.exists():
            out.append((name, base / "NativeMessagingHosts" / f"{HOST_NAME}.json", "chromium"))
    for name, base in FIREFOX_DIRS.items():
        if base.exists():
            out.append((name, base / "native-messaging-hosts" / f"{HOST_NAME}.json", "firefox"))
    return out


def sandboxed_browsers() -> list[str]:
    return [name for name, base in SANDBOXED.items() if base.exists()]


def install(extra_ids=(), force_all: bool = False) -> list[str]:
    """Installa per i browser trovati (o per tutti con force_all). Restituisce i nomi."""
    write_launcher()
    found = targets()
    if force_all:  # solo su richiesta: non creo cartelle di browser che l'utente non ha
        found = [(n, b / "NativeMessagingHosts" / f"{HOST_NAME}.json", "chromium") for n, b in CHROMIUM_DIRS.items()]
        found += [(n, b / "native-messaging-hosts" / f"{HOST_NAME}.json", "firefox") for n, b in FIREFOX_DIRS.items()]
    done = []
    for name, path, kind in found:
        manifest = chromium_manifest(extra_ids) if kind == "chromium" else firefox_manifest()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        done.append(name)
    return done


def uninstall() -> list[str]:
    removed = []
    for name, base in {**CHROMIUM_DIRS, **FIREFOX_DIRS}.items():
        for sub in ("NativeMessagingHosts", "native-messaging-hosts"):
            f = base / sub / f"{HOST_NAME}.json"
            if f.exists():
                f.unlink()
                removed.append(name)
    if LAUNCHER.exists():
        LAUNCHER.unlink()
    return removed


def installed() -> bool:
    return LAUNCHER.exists() and any(p.exists() for _n, p, _k in targets())


def extension_dir(kind: str) -> Path:
    """Cartella dell'estensione pronta da caricare (kind: "chromium" o "firefox")."""
    return Path(__file__).parent / "data" / "extension" / kind


def browser_status() -> list[tuple[str, str, bool]]:
    """(browser, tipo, collegato) per i browser trovati nella home dell'utente."""
    return [(name, kind, path.exists()) for name, path, kind in targets()]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--uninstall" in argv:
        names = uninstall()
        print("Rimosso da: " + (", ".join(names) or "nessun browser"))
        return 0
    extra = [argv[i + 1] for i, a in enumerate(argv) if a == "--extra-id" and i + 1 < len(argv)]
    names = install(extra, force_all="--all" in argv)
    if names:
        print("Helpix collegato a: " + ", ".join(names))
    else:
        print("Nessun browser trovato: avvia il browser almeno una volta e ripeti (oppure usa --all).")
    print()
    print("Ora installa l'estensione di Helpix nel browser:")
    print(f"  Chrome, Chromium, Edge, Brave, Vivaldi, Opera: {extension_dir('chromium')}")
    print("    apri chrome://extensions, attiva «Modalità sviluppatore», «Carica estensione non pacchettizzata»")
    print(f"  Firefox: {extension_dir('firefox')}")
    print("    versione firmata da addons.mozilla.org; per provarla subito: about:debugging › Questo Firefox ›")
    print("    «Carica componente aggiuntivo temporaneo» e scegli manifest.json (resta fino al riavvio)")
    box = sandboxed_browsers()
    if box:
        print()
        print("Attenzione: browser isolati trovati (" + ", ".join(box) + "): Flatpak e Snap di norma non "
              "possono avviare l'host. Usa la versione del browser installata con dnf/apt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
