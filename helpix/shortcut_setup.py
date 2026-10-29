# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorciatoia globale della finestra rapida impostata nel desktop (quando il portal non basta).

Il portal GlobalShortcuts c'è su KDE Plasma 6 e GNOME 48+; negli altri desktop Helpix scrive una scorciatoia
personalizzata nelle impostazioni del desktop, la stessa che si crea a mano dal pannello delle scorciatoie:

- GNOME (anche Ubuntu, Zorin, Budgie, Pantheon di elementary OS): gsettings, media-keys di GNOME
- Cinnamon (Linux Mint): gsettings, org.cinnamon.desktop.keybindings
- MATE: gsettings, org.mate.control-center.keybinding
- Xfce: xfconf-query, canale xfce4-keyboard-shortcuts
- COSMIC (Pop!_OS): file ~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom
- KDE Plasma: lanciatore con X-KDE-Shortcuts, poi conferma nelle scorciatoie di KDE
- Hyprland, Sway, niri, LXQt e altri: Helpix mostra la riga da aggiungere alla configurazione (è un file che
  l'utente scrive a mano: meglio non toccarlo da soli)

Il comando è sempre `helpix --quick`: mostra o nasconde la finestra rapida da qualsiasi programma.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

KEYS = "Ctrl+Alt+H"
GNOME_KEYS = "<Control><Alt>h"
GTK_KEYS = "<Primary><Alt>h"
DESKTOP_ID = "helpix-quick.desktop"
ENTRY = "helpix-quick"
NAME = "Helpix — richiesta rapida"

# desktop in cui Helpix imposta la scorciatoia da solo
AUTOMATIC = ("kde", "gnome", "cinnamon", "mate", "xfce", "cosmic")
LABELS = {"kde": "KDE Plasma", "gnome": "GNOME", "cinnamon": "Cinnamon", "mate": "MATE", "xfce": "Xfce",
          "cosmic": "COSMIC", "hyprland": "Hyprland", "sway": "Sway", "niri": "niri", "lxqt": "LXQt",
          "other": ""}


def quick_command() -> str:
    exe = shutil.which("helpix")
    return f"{shlex.quote(exe)} --quick" if exe else f"{shlex.quote(sys.executable)} -m helpix --quick"


_DESKTOPS = (  # nell'ordine: prima chi si dichiara anche «GNOME» (Budgie:GNOME, Pantheon, Zorin…)
    ("cinnamon", ("CINNAMON",)), ("mate", ("MATE",)), ("xfce", ("XFCE",)), ("cosmic", ("COSMIC",)),
    ("kde", ("KDE", "PLASMA")), ("lxqt", ("LXQT",)), ("hyprland", ("HYPRLAND",)), ("sway", ("SWAY",)),
    ("niri", ("NIRI",)), ("gnome", ("GNOME", "UNITY", "BUDGIE", "PANTHEON", "ZORIN", "POP")),
)


def desktop() -> str:
    """Il desktop in uso, da XDG_CURRENT_DESKTOP (es. «ubuntu:GNOME», «X-Cinnamon», «Budgie:GNOME»)."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    parts = [p.upper().removeprefix("X-") for p in re.split(r"[:;]", raw) if p]
    for key, words in _DESKTOPS:
        if any(p.startswith(w) for p in parts for w in words):
            return key
    return "other"


def _apps_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def _config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5, check=True).stdout.strip()


def _strv(value: str) -> list[str]:
    """Una lista gsettings («['a', 'b']» o «@as []») in lista Python."""
    value = value.strip()
    if value.startswith("@as"):
        value = value[3:].strip()
    return [p.strip().strip("'\"") for p in value.strip("[]").split(",") if p.strip()]


def _gvariant_strv(items: list[str]) -> str:
    return "[" + ", ".join("'" + i.replace("\\", "\\\\").replace("'", "\\'") + "'" for i in items) + "]"


# ------------------------------------------------------------ KDE
def install_kde() -> Path:
    """Crea il lanciatore con la scorciatoia e aggiorna l'elenco delle applicazioni di KDE."""
    path = _apps_dir() / DESKTOP_ID
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Name[en]=Helpix — quick request\n"
        "Comment=Mostra o nasconde la finestra rapida di Helpix\n"
        f"Exec={quick_command()}\n"
        "Icon=helpix\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        f"X-KDE-Shortcuts={KEYS}\n", encoding="utf-8")
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(tool):
            subprocess.run([tool], capture_output=True, timeout=60)
            break
    return path


def open_kde_shortcuts() -> None:
    for argv in (["systemsettings", "kcm_keys"], ["kcmshell6", "kcm_keys"]):
        if shutil.which(argv[0]):
            subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


# ------------------------------------------------------------ GNOME (anche Budgie, Pantheon, Zorin)
def install_gnome() -> bool:
    """Aggiunge (o aggiorna) la scorciatoia personalizzata di GNOME."""
    if not shutil.which("gsettings"):
        return False
    base = "org.gnome.settings-daemon.plugins.media-keys"
    path = f"/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{ENTRY}/"
    try:
        paths = _strv(_gsettings("get", base, "custom-keybindings"))
        if path not in paths:
            paths.append(path)
        _gsettings("set", base, "custom-keybindings", _gvariant_strv(paths))
        schema = f"{base}.custom-keybinding:{path}"
        for key, value in (("name", NAME), ("command", quick_command()), ("binding", GNOME_KEYS)):
            _gsettings("set", schema, key, value)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ Cinnamon (Linux Mint)
def install_cinnamon() -> bool:
    if not shutil.which("gsettings"):
        return False
    base = "org.cinnamon.desktop.keybindings"
    try:
        ids = _strv(_gsettings("get", base, "custom-list"))
        schema = f"{base}.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/{ENTRY}/"
        for key, value in (("name", NAME), ("command", quick_command()), ("binding", _gvariant_strv([GTK_KEYS]))):
            _gsettings("set", schema, key, value)
        if ENTRY not in ids:  # per ultima: Cinnamon rilegge l'elenco e trova già tutto pronto
            _gsettings("set", base, "custom-list", _gvariant_strv(ids + [ENTRY]))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ MATE
def install_mate() -> bool:
    if not shutil.which("gsettings"):
        return False
    schema = f"org.mate.control-center.keybinding:/org/mate/desktop/keybindings/{ENTRY}/"
    try:
        for key, value in (("name", NAME), ("action", quick_command()), ("binding", GTK_KEYS)):
            _gsettings("set", schema, key, value)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ Xfce
def install_xfce() -> bool:
    if not shutil.which("xfconf-query"):
        return False
    try:
        subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", f"/commands/custom/{GTK_KEYS}",
                        "-n", "-t", "string", "-s", quick_command()],
                       capture_output=True, text=True, timeout=5, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ COSMIC (Pop!_OS)
def cosmic_file() -> Path:
    return _config_dir() / "cosmic" / "com.system76.CosmicSettings.Shortcuts" / "v1" / "custom"


def install_cosmic() -> bool:
    """Aggiunge la voce alla mappa RON delle scorciatoie personalizzate (COSMIC la rilegge da sola)."""
    path = cosmic_file()
    cmd = quick_command().replace("\\", "\\\\").replace('"', '\\"')
    entry = f'    (modifiers: [Ctrl, Alt], key: "h"): Spawn("{cmd}"),\n'
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if "--quick" in text and "helpix" in text:
            return True  # c'è già
        body = text.strip()
        if not body or body == "{}":
            new = "{\n" + entry + "}\n"
        elif body.endswith("}"):
            inner = body[:-1].rstrip()
            if not inner.endswith((",", "{")):
                inner += ","
            new = inner + "\n" + entry + "}\n"
        else:
            return False  # formato inatteso: meglio non toccarlo
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.with_name(path.name + ".helpix-bak").write_text(text, encoding="utf-8")
        path.write_text(new, encoding="utf-8")
        return True
    except OSError:
        return False


# ------------------------------------------------------------ tutti
def install(de: str | None = None) -> bool:
    """Imposta la scorciatoia nel desktop indicato (o in quello in uso). KDE: vedi install_kde()."""
    de = de or desktop()
    fn = {"gnome": install_gnome, "cinnamon": install_cinnamon, "mate": install_mate, "xfce": install_xfce,
          "cosmic": install_cosmic}.get(de)
    if de == "kde":
        install_kde()
        return True
    return bool(fn and fn())


def manual_line(de: str | None = None) -> str:
    """La riga da aggiungere a mano nei desktop che si configurano con un file."""
    de = de or desktop()
    cmd = quick_command()
    return {
        "hyprland": f"bind = CTRL ALT, H, exec, {cmd}",
        "sway": f"bindsym Ctrl+Alt+h exec {cmd}",
        "niri": f'Ctrl+Alt+H {{ spawn "sh" "-c" "{cmd}"; }}',
    }.get(de, cmd)


def manual_where(de: str | None = None) -> str:
    de = de or desktop()
    return {
        "hyprland": "~/.config/hypr/hyprland.conf",
        "sway": "~/.config/sway/config",
        "niri": "~/.config/niri/config.kdl (sezione binds)",
        "lxqt": "Preferenze LXQt › Scorciatoie › Aggiungi",
    }.get(de, "")


# ------------------------------------------------------------ rimozione (uninstall.sh)
def _schema_known(schema: str) -> bool:
    if not shutil.which("gsettings"):
        return False
    out = subprocess.run(["gsettings", "list-schemas"], capture_output=True, text=True, timeout=10).stdout.split()
    out += subprocess.run(["gsettings", "list-relocatable-schemas"], capture_output=True, text=True,
                          timeout=10).stdout.split()
    return schema in out


def remove_all() -> list[str]:
    """Toglie la scorciatoia della finestra rapida da tutti i desktop in cui Helpix l'aveva messa. Le altre
    scorciatoie dell'utente restano. Restituisce i desktop sistemati."""
    done: list[str] = []
    try:
        base = "org.gnome.settings-daemon.plugins.media-keys"
        if _schema_known(base):
            path = f"/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{ENTRY}/"
            paths = _strv(_gsettings("get", base, "custom-keybindings"))
            if path in paths:
                _gsettings("set", base, "custom-keybindings", _gvariant_strv([p for p in paths if p != path]))
                for key in ("name", "command", "binding"):
                    _gsettings("reset", f"{base}.custom-keybinding:{path}", key)
                done.append("gnome")
        base = "org.cinnamon.desktop.keybindings"
        if _schema_known(base):
            ids = _strv(_gsettings("get", base, "custom-list"))
            if ENTRY in ids:
                _gsettings("set", base, "custom-list", _gvariant_strv([i for i in ids if i != ENTRY]))
                schema = f"{base}.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/{ENTRY}/"
                for key in ("name", "command", "binding"):
                    _gsettings("reset", schema, key)
                done.append("cinnamon")
        schema = f"org.mate.control-center.keybinding:/org/mate/desktop/keybindings/{ENTRY}/"
        if _schema_known("org.mate.control-center.keybinding") and "--quick" in _gsettings("get", schema, "action"):
            for key in ("name", "action", "binding"):
                _gsettings("reset", schema, key)
            done.append("mate")
    except (OSError, subprocess.SubprocessError):
        pass
    if shutil.which("xfconf-query"):
        prop = f"/commands/custom/{GTK_KEYS}"
        try:
            cur = subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", prop], capture_output=True,
                                 text=True, timeout=5)
            if cur.returncode == 0 and "--quick" in cur.stdout and "helpix" in cur.stdout:
                subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", prop, "-r"],
                               capture_output=True, timeout=5)
                done.append("xfce")
        except (OSError, subprocess.SubprocessError):
            pass
    path = cosmic_file()
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            kept = [ln for ln in lines if not ("Spawn(" in ln and "helpix" in ln and "--quick" in ln)]
            if len(kept) != len(lines):
                path.write_text("".join(kept), encoding="utf-8")
                done.append("cosmic")
            backup = path.with_name(path.name + ".helpix-bak")  # la copia fatta da Helpix: non serve più
            if backup.exists():
                backup.unlink()
    except OSError:
        pass
    kde = _apps_dir() / DESKTOP_ID
    if kde.exists():
        kde.unlink()
        for tool in ("kbuildsycoca6", "kbuildsycoca5"):
            if shutil.which(tool):
                subprocess.run([tool], capture_output=True, timeout=60)
                break
        done.append("kde")
    return done


if __name__ == "__main__":  # python -m helpix.shortcut_setup remove
    if sys.argv[1:] == ["remove"]:
        removed = remove_all()
        print("Scorciatoia della finestra rapida tolta da: " + (", ".join(removed) if removed else "nessun desktop"))
    else:
        print("Uso: python -m helpix.shortcut_setup remove")
