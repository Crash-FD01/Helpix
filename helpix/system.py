# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cosa cambia tra Linux e Windows: cartelle, nomi dei canali locali, shell.

Il resto di Helpix chiede qui invece di controllare il sistema da solo, così le differenze stanno in un posto.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"

APP_ID = "helpix"
APP_NAME = "Helpix"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def _win_dir(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return (Path(value) if value else Path.home() / fallback) / APP_NAME


def config_dir() -> Path:
    """Impostazioni. Linux: ~/.config/helpix. Windows: %APPDATA%\\Helpix (segue l'utente nei domini)."""
    if IS_WINDOWS:
        return _win_dir("APPDATA", "AppData/Roaming")
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_ID


def data_dir() -> Path:
    """Dati, sessioni, screenshot, log. Linux: ~/.local/share/helpix. Windows: %LOCALAPPDATA%\\Helpix."""
    if IS_WINDOWS:
        return _win_dir("LOCALAPPDATA", "AppData/Local")
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_ID


def runtime_dir() -> str:
    """Cartella privata per socket e file temporanei della sessione.

    Linux: $XDG_RUNTIME_DIR (/run/user/UID, solo dell'utente); se manca (sessioni senza systemd, avvii da cron
    o SSH) ~/.cache/helpix-run invece di /tmp, dove un altro utente potrebbe creare per primo la cartella con un
    nome prevedibile. Windows: %LOCALAPPDATA%\\Helpix\\run (la cartella dell'utente è già privata).
    """
    if IS_WINDOWS:
        path = data_dir() / "run"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isdir(base):
        return base
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(cache, "helpix-run")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _user_tag() -> str:
    name = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:40]


def channel(kind: str) -> str:
    """Indirizzo del canale locale «kind» («app», «quick», «bridge»).

    Linux: percorso di un socket Unix nella cartella privata. Windows: nome di una named pipe
    (\\\\.\\pipe\\<nome>); QLocalServer la crea con accesso solo per l'utente, il nome include l'utente perché
    le pipe sono visibili a tutta la macchina (più persone collegate allo stesso PC, desktop remoto).
    """
    if IS_WINDOWS:
        session = os.environ.get("SESSIONNAME", "")
        tag = _user_tag() + (f"-{re.sub(r'[^A-Za-z0-9]', '', session)}" if session else "")
        return f"helpix-{kind}-{tag}"
    return os.path.join(runtime_dir(), "helpix", f"{kind}.sock")


def is_admin() -> bool:
    """Helpix gira con i permessi di amministratore (root su Linux, elevato su Windows)?"""
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def shell_name() -> str:
    """Shell in cui girano i comandi proposti dall'IA."""
    return "PowerShell" if IS_WINDOWS else "bash"


def os_label() -> str:
    """Nome del sistema per i messaggi all'IA, es. «Windows 11 (build 26100)» o «Fedora Linux 44»."""
    if IS_WINDOWS:
        import platform as _p
        build = sys.getwindowsversion().build if hasattr(sys, "getwindowsversion") else 0
        name = "Windows 11" if build >= 22000 else f"Windows {_p.release()}"
        return f"{name} (build {build})" if build else name
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


# ------------------------------------------------------------------ processi
def process_alive(pid: int) -> bool:
    if IS_WINDOWS:
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong(0)
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    return os.path.exists(f"/proc/{pid}") or _posix_alive(pid)


def _posix_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_helpix_quick(pid: int) -> bool:
    """Il processo è la finestra rapida di Helpix? (prima di terminarlo)

    Linux: la riga di comando contiene «helpix» e «--quick». Windows: il canale è una pipe dell'utente con il nome
    di Helpix, quindi basta che il programma sia Helpix o Python."""
    if IS_WINDOWS:
        exe = process_image(pid).lower()
        return exe.endswith(("helpix.exe", "python.exe", "pythonw.exe"))
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        return False
    return b"--quick" in args and any(b"helpix" in a for a in args)


def process_image(pid: int) -> str:
    """Percorso dell'eseguibile del processo (Windows), "" se non si sa."""
    if not IS_WINDOWS:
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return ""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        return buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
    finally:
        k.CloseHandle(h)


def terminate(pid: int) -> bool:
    if IS_WINDOWS:
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if not h:
            return False
        try:
            return bool(k.TerminateProcess(h, 1))
        finally:
            k.CloseHandle(h)
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def helpix_argv(*args: str) -> list[str]:
    """Riga di comando per avviare Helpix con questi argomenti (es. «--quick»).

    Programma installato su Windows (PyInstaller): Helpix.exe. Dai sorgenti: python -m helpix; su Windows con
    pythonw.exe, che non apre una finestra di console."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = sys.executable
    if IS_WINDOWS and exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    return [exe, "-m", "helpix", *args]
