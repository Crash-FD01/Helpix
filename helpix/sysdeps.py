# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dipendenze di sistema: trova cosa manca e lo installa con il gestore pacchetti della distribuzione.

- Librerie che servono a Qt: si cercano con `ldd` sui moduli di Qt che Helpix usa davvero, così si scopre
  esattamente cosa manca su quel sistema (non una lista fissa).
- Strumenti facoltativi: xprop/xwininfo su X11 (clic su una finestra per lo screenshot), PyGObject di
  sistema su Wayland (screenshot tramite portal).

Usato da install.sh (`python -m helpix.sysdeps install --yes`), da Impostazioni › Dipendenze di sistema e
dalla pagina di installazione degli agenti (Node.js/npm, curl).

    python -m helpix.sysdeps check      # elenca cosa manca
    python -m helpix.sysdeps install    # lo installa (chiede la password di amministratore)
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, field

MANAGERS = ("dnf", "apt", "pacman", "zypper")
_EXE = {"dnf": "dnf", "apt": "apt-get", "pacman": "pacman", "zypper": "zypper"}

# libreria → pacchetto per dnf, apt, pacman, zypper
LIBS: dict[str, tuple[str, str, str, str]] = {
    "libxcb-cursor.so.0": ("xcb-util-cursor", "libxcb-cursor0", "xcb-util-cursor", "libxcb-cursor0"),
    "libxcb-icccm.so.4": ("xcb-util-wm", "libxcb-icccm4", "xcb-util-wm", "libxcb-icccm4"),
    "libxcb-image.so.0": ("xcb-util-image", "libxcb-image0", "xcb-util-image", "libxcb-image0"),
    "libxcb-keysyms.so.1": ("xcb-util-keysyms", "libxcb-keysyms1", "xcb-util-keysyms", "libxcb-keysyms1"),
    "libxcb-render-util.so.0": ("xcb-util-renderutil", "libxcb-render-util0", "xcb-util-renderutil",
                                "libxcb-render-util0"),
    "libxcb-util.so.1": ("xcb-util", "libxcb-util1", "xcb-util", "libxcb-util1"),
    "libxcb-xkb.so.1": ("libxcb", "libxcb-xkb1", "libxcb", "libxcb-xkb1"),
    "libxcb-shape.so.0": ("libxcb", "libxcb-shape0", "libxcb", "libxcb-shape0"),
    "libxcb-randr.so.0": ("libxcb", "libxcb-randr0", "libxcb", "libxcb-randr0"),
    "libxcb-xinput.so.0": ("libxcb", "libxcb-xinput0", "libxcb", "libxcb-xinput0"),
    "libxcb-xfixes.so.0": ("libxcb", "libxcb-xfixes0", "libxcb", "libxcb-xfixes0"),
    "libxcb-shm.so.0": ("libxcb", "libxcb-shm0", "libxcb", "libxcb-shm0"),
    "libxcb-sync.so.1": ("libxcb", "libxcb-sync1", "libxcb", "libxcb-sync1"),
    "libxcb-glx.so.0": ("libxcb", "libxcb-glx0", "libxcb", "libxcb-glx0"),
    "libX11-xcb.so.1": ("libX11-xcb", "libx11-xcb1", "libx11", "libX11-xcb1"),
    "libxkbcommon.so.0": ("libxkbcommon", "libxkbcommon0", "libxkbcommon", "libxkbcommon0"),
    "libxkbcommon-x11.so.0": ("libxkbcommon-x11", "libxkbcommon-x11-0", "libxkbcommon-x11", "libxkbcommon-x11-0"),
    "libxkbfile.so.1": ("libxkbfile", "libxkbfile1", "libxkbfile", "libxkbfile1"),
    "libXcomposite.so.1": ("libXcomposite", "libxcomposite1", "libxcomposite", "libXcomposite1"),
    "libXdamage.so.1": ("libXdamage", "libxdamage1", "libxdamage", "libXdamage1"),
    "libXrandr.so.2": ("libXrandr", "libxrandr2", "libxrandr", "libXrandr2"),
    "libXtst.so.6": ("libXtst", "libxtst6", "libxtst", "libXtst6"),
    "libXfixes.so.3": ("libXfixes", "libxfixes3", "libxfixes", "libXfixes3"),
    "libXext.so.6": ("libXext", "libxext6", "libxext", "libXext6"),
    "libxshmfence.so.1": ("libxshmfence", "libxshmfence1", "libxshmfence", "libxshmfence1"),
    "libEGL.so.1": ("libglvnd-egl", "libegl1", "libglvnd", "libEGL1"),
    "libGL.so.1": ("libglvnd-glx", "libgl1", "libglvnd", "libGL1"),
    "libGLX.so.0": ("libglvnd-glx", "libglx0", "libglvnd", "libGLX0"),
    "libOpenGL.so.0": ("libglvnd-opengl", "libopengl0", "libglvnd", "libOpenGL0"),
    "libgbm.so.1": ("mesa-libgbm", "libgbm1", "mesa", "libgbm1"),
    "libdrm.so.2": ("libdrm", "libdrm2", "libdrm", "libdrm2"),
    "libfontconfig.so.1": ("fontconfig", "libfontconfig1", "fontconfig", "libfontconfig1"),
    "libfreetype.so.6": ("freetype", "libfreetype6", "freetype2", "libfreetype6"),
    "libnss3.so": ("nss", "libnss3", "nss", "mozilla-nss"),
    "libnssutil3.so": ("nss-util", "libnss3", "nss", "mozilla-nss"),
    "libsmime3.so": ("nss", "libnss3", "nss", "mozilla-nss"),
    "libnspr4.so": ("nspr", "libnspr4", "nspr", "mozilla-nspr"),
    "libplc4.so": ("nspr", "libnspr4", "nspr", "mozilla-nspr"),
    "libplds4.so": ("nspr", "libnspr4", "nspr", "mozilla-nspr"),
    "libasound.so.2": ("alsa-lib", "libasound2", "alsa-lib", "libasound2"),
    "libdbus-1.so.3": ("dbus-libs", "libdbus-1-3", "dbus", "libdbus-1-3"),
    "libglib-2.0.so.0": ("glib2", "libglib2.0-0", "glib2", "libglib-2_0-0"),
    "libwayland-client.so.0": ("libwayland-client", "libwayland-client0", "wayland", "libwayland-client0"),
    "libwayland-cursor.so.0": ("libwayland-cursor", "libwayland-cursor0", "wayland", "libwayland-cursor0"),
    "libwayland-egl.so.1": ("libwayland-egl", "libwayland-egl1", "wayland", "libwayland-egl1"),
    "libgssapi_krb5.so.2": ("krb5-libs", "libgssapi-krb5-2", "krb5", "krb5"),
    "libcups.so.2": ("cups-libs", "libcups2", "libcups", "libcups2"),
    "libxslt.so.1": ("libxslt", "libxslt1.1", "libxslt", "libxslt1"),
    "libminizip.so.1": ("minizip-compat", "libminizip1", "minizip", "libminizip1"),
}

# strumenti → pacchetto per dnf, apt, pacman, zypper
TOOLS: dict[str, tuple[str, ...]] = {
    "xprop": ("xprop", "x11-utils", "xorg-xprop", "xprop"),
    "xwininfo": ("xwininfo", "x11-utils", "xorg-xwininfo", "xwininfo"),
    "gi": ("python3-gobject", "python3-gi", "python-gobject", "python3-gobject"),
    "npm": ("nodejs npm", "nodejs npm", "nodejs npm", "nodejs-default npm-default"),
    "node": ("nodejs", "nodejs", "nodejs", "nodejs-default"),
    "curl": ("curl", "curl", "curl", "curl"),
    "bash": ("bash", "bash", "bash", "bash"),
    "setsid": ("util-linux", "util-linux", "util-linux", "util-linux"),
    "appindicator": ("gnome-shell-extension-appindicator",) * 4,
}

# Area di notifica su GNOME: l'estensione «AppIndicator and KStatusNotifierItem Support». Ubuntu ne ha una sua
# già attiva; Fedora, Debian, Arch, openSUSE no.
APPINDICATOR_UUID = "appindicatorsupport@rgcjonas.gmail.com"
TRAY_EXTENSIONS = (APPINDICATOR_UUID, "ubuntu-appindicators@ubuntu.com", "zorin-appindicator@zorinos.com")

# moduli di Qt che Helpix carica (gli altri, come Qt3D o multimedia, non servono)
_QT_LIBS = ("Core", "Gui", "Widgets", "Network", "WebEngineCore", "WebEngineWidgets", "WebChannel", "DBus",
            "Svg", "XcbQpa", "WaylandClient", "OpenGL", "PrintSupport", "Positioning", "Qml", "Quick",
            "QuickWidgets", "WebChannelQuick")
_QT_PLUGINS = ("platforms/libqxcb.so", "platforms/libqwayland*.so", "platforms/libqoffscreen.so",
               "xcbglintegrations/*.so", "wayland-shell-integration/*.so",
               "wayland-graphics-integration-client/*.so", "wayland-decoration-client/*.so",
               "platforminputcontexts/*.so", "imageformats/*.so", "iconengines/*.so", "tls/*.so")


@dataclass
class Missing:
    what: str               # libreria o strumento
    reason: str             # a cosa serve
    package: str | None     # pacchetto della distro (None: sconosciuto)
    required: bool = True   # False: consigliato
    enable_only: bool = False  # già installato, va solo attivato (estensione di GNOME)


@dataclass
class Report:
    manager: str | None
    immutable: bool
    items: list[Missing] = field(default_factory=list)

    @property
    def packages(self) -> list[str]:
        out: list[str] = []
        for m in self.items:
            for p in (m.package or "").split():
                if p not in out:
                    out.append(p)
        return out

    @property
    def unknown(self) -> list[str]:
        return [m.what for m in self.items if not m.package and not m.enable_only]

    @property
    def gnome_tray(self) -> bool:
        """Fra le cose da sistemare c'è l'area di notifica di GNOME (da installare o solo da attivare)."""
        return any(m.what == "AppIndicator" for m in self.items)


# ------------------------------------------------------------ sistema
def detect_manager() -> str | None:
    for pm in MANAGERS:
        if shutil.which(_EXE[pm]):
            return pm
    return None


def is_immutable() -> bool:
    """Fedora Atomic (Silverblue, Kinoite, Bazzite), SteamOS…: /usr in sola lettura, niente dnf install."""
    if os.path.exists("/run/ostree-booted"):
        return True
    if shutil.which("steamos-readonly"):
        try:
            out = subprocess.run(["steamos-readonly", "status"], capture_output=True, text=True, timeout=5).stdout
            return "enabled" in out
        except (OSError, subprocess.SubprocessError):
            return True
    return False


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "").lower()


def _pkg(table: dict, key: str, pm: str | None) -> str | None:
    if pm not in MANAGERS or key not in table:
        return None
    name = table[key][MANAGERS.index(pm)]
    if pm == "apt" and name:
        name = " ".join(apt_name(p) for p in name.split())
    return name


_APT_NAMES: dict[str, str] = {}


def apt_name(pkg: str) -> str:
    """Nome del pacchetto che apt può installare davvero su questo sistema.

    Da Ubuntu 24.04 e Debian 13 diverse librerie hanno il suffisso «t64» (libasound2 → libasound2t64): il nome
    vecchio resta solo come pacchetto virtuale e «apt-get install libasound2» fallisce. Le tabelle usano il nome
    vecchio (valido su Ubuntu 22.04, Debian 12, Mint 21); qui si sceglie quello che ha una versione installabile.
    """
    if pkg in _APT_NAMES:
        return _APT_NAMES[pkg]

    def installable(name: str) -> bool:
        try:
            out = subprocess.run(["apt-cache", "policy", name], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "Candidate:" in out and "Candidate: (none)" not in out

    result = pkg
    if not installable(pkg) and installable(pkg + "t64"):
        result = pkg + "t64"
    _APT_NAMES[pkg] = result
    return result


# ------------------------------------------------------------ librerie di Qt
def qt_dir() -> str | None:
    spec = importlib.util.find_spec("PySide6")
    if not spec or not spec.origin:
        return None
    path = os.path.join(os.path.dirname(spec.origin), "Qt")
    return path if os.path.isdir(path) else None


def qt_binaries(root: str | None = None) -> list[str]:
    root = root or qt_dir()
    if not root:
        return []
    files = [os.path.join(root, "lib", f"libQt6{name}.so.6") for name in _QT_LIBS]
    for pattern in _QT_PLUGINS:
        files += glob.glob(os.path.join(root, "plugins", pattern))
    files.append(os.path.join(root, "libexec", "QtWebEngineProcess"))
    files += glob.glob(os.path.join(os.path.dirname(root), "Qt*.abi3.so"))
    return [f for f in files if os.path.isfile(f)]


_NOT_FOUND = re.compile(r"^\s*(\S+)\s+=>\s+not found", re.M)


def parse_ldd(output: str) -> set[str]:
    return set(_NOT_FOUND.findall(output))


def missing_libs(files: list[str] | None = None) -> list[str]:
    if not shutil.which("ldd"):
        return []
    found: set[str] = set()
    for f in files if files is not None else qt_binaries():
        try:
            out = subprocess.run(["ldd", f], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found |= parse_ldd(out)
    # le librerie di Qt/PySide stesse non sono pacchetti della distro (es. un plugin che punta a QtPdf,
    # modulo facoltativo non installato): non vanno chieste al sistema
    return sorted(f for f in found if not f.startswith(("libQt6", "libpyside6", "libshiboken6")))


def lookup_package(pm: str | None, soname: str) -> str | None:
    """Per una libreria fuori tabella chiede al gestore pacchetti chi la fornisce."""
    try:
        if pm == "dnf":
            out = subprocess.run(["dnf", "-q", "provides", f"*/{soname}"], capture_output=True, text=True,
                                 timeout=120).stdout
            m = re.search(r"^([A-Za-z0-9_.+-]+?)-\d[^\s]*\.(?:x86_64|aarch64|noarch)\s", out, re.M)
            return m.group(1) if m else None
        if pm == "zypper":
            out = subprocess.run(["zypper", "-q", "search", "--provides", "--match-exact", soname],
                                 capture_output=True, text=True, timeout=120).stdout
            for line in out.splitlines():
                cols = [c.strip() for c in line.split("|")]
                if len(cols) > 2 and cols[1] and cols[1] != "Name":
                    return cols[1]
        if pm == "pacman":
            out = subprocess.run(["pacman", "-Fq", soname], capture_output=True, text=True, timeout=60).stdout
            first = out.split()
            return first[0].split("/")[-1] if first else None
        if pm == "apt" and shutil.which("apt-file"):
            out = subprocess.run(["apt-file", "-l", "search", soname], capture_output=True, text=True,
                                 timeout=120).stdout
            first = out.split()
            return first[0] if first else None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def system_pythons() -> list[str]:
    """I Python della distro, dal predefinito ai versionati: PyGObject della distro è compilato per uno di
    questi, che non è sempre quello a cui punta python3 (alternative cambiate a mano)."""
    found = ["/usr/bin/python3", shutil.which("python3") or ""]
    found += sorted(glob.glob("/usr/bin/python3.[0-9]*"), reverse=True)
    return [p for p in dict.fromkeys(found) if p and re.search(r"python3(\.\d+)?$", p) and os.path.exists(p)]


def _system_python_has_gi() -> bool:
    for py in system_pythons():
        if py:
            try:
                if subprocess.run([py, "-c", "import gi"], capture_output=True, timeout=10).returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
    return False


# ------------------------------------------------------------ area di notifica su GNOME
def _pure_gnome() -> bool:
    """GNOME «puro»: Budgie, Pantheon e gli altri che si dichiarano anche GNOME hanno la loro area di notifica."""
    parts = [p.upper() for p in re.split(r"[:;]", os.environ.get("XDG_CURRENT_DESKTOP", "")) if p]
    return "GNOME" in parts and not any(p in ("BUDGIE", "PANTHEON", "UNITY", "CINNAMON", "MATE", "XFCE")
                                        for p in parts)


def _extension_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    dirs = [data_home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return [Path(d) / "gnome-shell" / "extensions" for d in dirs if d]


def gnome_extension_installed(uuid: str) -> bool:
    return any((d / uuid / "metadata.json").exists() for d in _extension_dirs())


def gnome_enabled_extensions() -> list[str]:
    if not shutil.which("gsettings"):
        return []
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = out.strip().removeprefix("@as").strip()
    return [x.strip().strip("'\"") for x in out.strip("[]").split(",") if x.strip()]


def tray_watcher_present() -> bool | None:
    """C'è qualcuno che mostra le icone (StatusNotifierWatcher)? None: non lo so (niente sessione D-Bus)."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError:
        return None
    try:
        conn = open_dbus_connection(bus="SESSION")
    except Exception:  # noqa: BLE001 - niente bus (installazione da SSH, container)
        return None
    try:
        bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus", interface="org.freedesktop.DBus")
        reply = conn.send_and_get_reply(new_method_call(bus, "NameHasOwner", "s", ("org.kde.StatusNotifierWatcher",)),
                                        timeout=3)
        return bool(reply.body[0])
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


def gnome_tray_status() -> str:
    """«ok», «install» (manca l'estensione), «enable» (installata ma spenta), «relogin» (attivata, si vedrà al
    prossimo accesso) o «n/a» (non è GNOME)."""
    if not _pure_gnome():
        return "n/a"
    if tray_watcher_present():
        return "ok"
    enabled = gnome_enabled_extensions()
    installed = [u for u in TRAY_EXTENSIONS if gnome_extension_installed(u)]
    if any(u in enabled for u in installed):
        return "relogin"
    return "enable" if installed else "install"


def enable_gnome_tray() -> bool:
    """Attiva l'estensione per l'utente: GNOME la carica (su Wayland) dal prossimo accesso."""
    uuid = next((u for u in TRAY_EXTENSIONS if gnome_extension_installed(u)), APPINDICATOR_UUID)
    enabled = gnome_enabled_extensions()
    try:
        if uuid not in enabled:
            value = "[" + ", ".join(f"'{u}'" for u in enabled + [uuid]) + "]"
            subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", value],
                           capture_output=True, timeout=5, check=True)
        if shutil.which("gnome-extensions"):  # se GNOME Shell la conosce già, si accende subito
            subprocess.run(["gnome-extensions", "enable", uuid], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------ verifica
def check(include_optional: bool = True, lookup: bool = True) -> Report:
    pm = detect_manager()
    report = Report(pm, is_immutable())
    for soname in missing_libs():
        pkg = _pkg(LIBS, soname, pm) or (lookup_package(pm, soname) if lookup else None)
        why = ("finestra rapida e Qt su X11" if soname == "libxcb-cursor.so.0" else "Qt (interfaccia di Helpix)")
        report.items.append(Missing(soname, why, pkg, True))
    if include_optional:
        st = session_type()
        if st != "wayland":
            for tool in ("xprop", "xwininfo"):
                if not shutil.which(tool):
                    report.items.append(Missing(tool, "screenshot di una finestra con un clic (X11)",
                                                _pkg(TOOLS, tool, pm), False))
        if st != "x11" and not _system_python_has_gi() and not (shutil.which("spectacle") or shutil.which("grim")):
            report.items.append(Missing("PyGObject", "screenshot tramite portal (Wayland)", _pkg(TOOLS, "gi", pm), False))
        tray = gnome_tray_status()
        if tray in ("install", "enable"):
            report.items.append(Missing("AppIndicator", "icona di Helpix nell'area di notifica di GNOME",
                                        _pkg(TOOLS, "appindicator", pm) if tray == "install" else None, False,
                                        enable_only=tray == "enable"))
    return report


def tools_missing(tools: list[str], path: str | None = None) -> list[str]:
    return [t for t in tools if not shutil.which(t, path=path)]


# ------------------------------------------------------------ installazione
def install_argv(packages: list[str], pm: str | None) -> list[str] | None:
    """Comando (da eseguire come root) che installa i pacchetti senza fare domande."""
    if not packages or pm not in MANAGERS:
        return None
    if pm == "dnf":
        return ["dnf", "install", "-y", *packages]
    if pm == "apt":
        q = " ".join(shlex.quote(p) for p in packages)
        return ["sh", "-c", f"apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -y {q}"]
    if pm == "pacman":
        return ["pacman", "-S", "--needed", "--noconfirm", *packages]
    return ["zypper", "--non-interactive", "install", *packages]


def elevate(argv: list[str], gui: bool = False) -> list[str] | None:
    """Root se servono: niente se lo sei già, pkexec (finestra del sistema) dall'app, sudo dal terminale."""
    if os.geteuid() == 0:
        return argv
    exe = shutil.which(argv[0]) or argv[0]
    if gui and shutil.which("pkexec"):
        return ["pkexec", exe, *argv[1:]]
    if shutil.which("sudo"):
        return ["sudo", exe, *argv[1:]]
    if shutil.which("pkexec"):
        return ["pkexec", exe, *argv[1:]]
    return None


def shell_install(tools: list[str], pm: str | None = None) -> str | None:
    """Riga di shell (con sudo) che installa gli strumenti indicati: per il terminale degli agenti."""
    pm = pm or detect_manager()
    if is_immutable():
        return None
    pkgs: list[str] = []
    for t in tools:
        for p in (_pkg(TOOLS, t, pm) or "").split():
            if p not in pkgs:
                pkgs.append(p)
    argv = install_argv(pkgs, pm)
    if not argv:
        return None
    if os.geteuid() != 0:
        argv = ["sudo", *argv]
    return " ".join(shlex.quote(a) for a in argv)


def manual_hint(report: Report) -> str:
    """Cosa dire all'utente quando non si può installare da qui."""
    pkgs = " ".join(report.packages)
    if report.immutable and pkgs:
        return f"rpm-ostree install {pkgs}   (poi riavvia)"
    argv = install_argv(report.packages, report.manager)
    return " ".join(["sudo", *argv]) if argv else ""


# ------------------------------------------------------------ riga di comando
def _print_report(r: Report) -> None:
    if not r.items:
        print("✓ Dipendenze di sistema a posto.")
        return
    for m in r.items:
        kind = "necessaria" if m.required else "consigliata"
        target = "già installata, da attivare" if m.enable_only else (m.package or "pacchetto sconosciuto")
        print(f"  - {m.what}: {m.reason} ({kind}) → {target}")


def _finish_gnome_tray() -> None:
    if enable_gnome_tray():
        print("✓ Estensione AppIndicator attivata: l'icona di Helpix comparirà nella barra in alto dal prossimo "
              "accesso (esci e rientra).")
    else:
        print("Attenzione: non sono riuscito ad attivare l'estensione AppIndicator: attivala dall'app Estensioni.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m helpix.sysdeps", description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("check", "install"))
    ap.add_argument("--yes", action="store_true", help="non chiede conferma (la password la chiede sudo)")
    ap.add_argument("--required-only", action="store_true", help="solo le librerie necessarie")
    args = ap.parse_args(argv)

    report = check(include_optional=not args.required_only)
    if args.action == "check" or not report.items:
        _print_report(report)
        return 1 if any(m.required for m in report.items) else 0

    print("Mancano alcune dipendenze di sistema:")
    _print_report(report)
    if report.gnome_tray and not report.packages:  # solo da attivare: niente da installare
        _finish_gnome_tray()
        return 0
    if report.immutable or not report.manager:
        hint = manual_hint(report)
        print("\nNon posso installarle da qui" + (" (sistema immutabile)." if report.immutable else "."))
        if hint:
            print(f"Comando da eseguire: {hint}")
        return 1 if any(m.required for m in report.items) else 0
    cmd = elevate(install_argv(report.packages, report.manager) or [])
    if not cmd:
        print(f"\nServono i permessi di amministratore (sudo o pkexec). Comando: {manual_hint(report)}")
        return 1
    if not args.yes and sys.stdin.isatty():
        ans = input(f"\nInstallo {' '.join(report.packages)} con {report.manager}? [S/n] ").strip().lower()
        if ans not in ("", "s", "si", "sì", "y", "yes"):
            print("Installazione saltata.")
            return 0
    print(f"→ {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    if report.gnome_tray and gnome_tray_status() in ("enable", "relogin"):
        _finish_gnome_tray()
    after = check(include_optional=not args.required_only, lookup=False)
    still = [m.what for m in after.items if m.what in {i.what for i in report.items} and not m.enable_only]
    if rc != 0 or still:
        print(f"Attenzione: non tutto è stato installato ({', '.join(still) or f'codice {rc}'}).")
        return 1 if any(m.required for m in after.items) else 0
    print("✓ Dipendenze di sistema installate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
