# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Esecuzione dei comandi: analisi di sicurezza, privilegi via polkit, tracking della cartella.

Ogni comando gira in una `bash -c` nuova e non interattiva (stdin chiuso, pager
disattivati). La cartella corrente viene preservata tra un comando e l'altro: una
trap EXIT scrive `$PWD` su un descrittore dedicato, così anche `cd x && ls` o uno
script con `exit` aggiornano correttamente la posizione.
"""
from __future__ import annotations

import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal
from .i18n import tr

MAX_CAPTURE = 200_000  # caratteri di output conservati per comando

_PREFIX = r"(^|[;&|({]\s*|\b(?:then|do|else)\s+)"
_SUDO_ANY = re.compile(_PREFIX + r"sudo\b", re.M)
_SUDO_PLAIN = re.compile(_PREFIX + r"sudo\s+(?=[^-\s])", re.M)
_SUDO_OPTS = re.compile(_PREFIX + r"sudo\s+-", re.M)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")

DANGEROUS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+(\S+\s+)*-\w*[rR]"), tr("cancellazione ricorsiva di file (rm -r)")),
    (re.compile(r"\bmkfs(\.\w+)?\b"), tr("formattazione di un filesystem")),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/"), tr("scrittura diretta su un dispositivo")),
    (re.compile(r">\s*/dev/(sd|nvme|vd|hd|mmcblk)"), tr("scrittura diretta su un disco")),
    (re.compile(r"\b(wipefs|shred|fdisk|sfdisk|parted|gdisk|sgdisk|cfdisk)\b"), tr("modifica delle partizioni o cancellazione sicura")),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"), tr("fork bomb")),
    (re.compile(r"\b(chmod|chown|chgrp)\s+(\S+\s+)*-\w*R"), tr("modifica ricorsiva di permessi o proprietario")),
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b|\binit\s+[06]\b|\bsystemctl\s+(reboot|poweroff|halt)\b"), tr("riavvio o spegnimento")),
    (re.compile(r"\b(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"), tr("esecuzione di uno script scaricato da Internet")),
    (re.compile(r"\b(dnf|yum|apt|apt-get|zypper|pacman|rpm)\b[^\n;|]*\s(remove|erase|purge|autoremove|-R\w*|-e)\b"), tr("rimozione di pacchetti")),
    (re.compile(r"\bsystemctl\s+(stop|disable|mask)\s+\S*(NetworkManager|network|sshd|gdm|sddm|lightdm|dbus|polkit)"), tr("arresto di un servizio essenziale")),
    (re.compile(r"\b(userdel|groupdel|deluser)\b"), tr("cancellazione di utenti o gruppi")),
    (re.compile(r"\bmv\s+(\S+\s+)*/(etc|usr|boot|bin|lib|lib64|sbin)(/\S*)?\s"), tr("spostamento di file di sistema")),
    (re.compile(r">\s*/etc/(passwd|shadow|fstab|sudoers|group)\b"), tr("sovrascrittura di un file di sistema critico")),
]

INTERACTIVE = {
    "top", "htop", "btop", "atop", "nano", "vim", "vi", "nvim", "emacs", "micro", "less", "more",
    "most", "man", "ssh", "telnet", "ftp", "sftp", "watch", "nmtui", "mc", "ranger", "passwd",
    "visudo", "vipw", "alsamixer", "python", "python3", "ipython", "node", "mysql", "psql",
    "sqlite3", "bash", "zsh", "sh", "fish", "su", "tmux", "screen",
}
_FOLLOW = re.compile(r"\b(tail|journalctl|dmesg)\b[^|;&\n]*\s(-f\b|--follow\b|-w\b)")


@dataclass
class CommandInfo:
    needs_root: bool = False
    sudo_options: bool = False
    dangers: list = field(default_factory=list)
    interactive: str | None = None


def analyze(cmd: str) -> CommandInfo:
    info = CommandInfo()
    info.needs_root = bool(_SUDO_ANY.search(cmd)) or cmd.lstrip().startswith("pkexec ")
    info.sudo_options = bool(_SUDO_OPTS.search(cmd))
    info.dangers = [reason for rx, reason in DANGEROUS if rx.search(cmd)]
    for seg in re.split(r"\|\|?|&&|;|\n|\$\(|`", cmd):
        words = seg.strip().split()
        while words and (words[0] in ("sudo", "env", "nohup", "time", "command", "exec")
                         or re.match(r"^\w+=", words[0])):
            words.pop(0)
        if not words:
            continue
        name = os.path.basename(words[0])
        # "bash script.sh" o "python3 x.py" non sono interattivi; senza argomenti sì
        if name in INTERACTIVE and not (name in ("bash", "zsh", "sh", "fish", "python", "python3", "node")
                                        and len(words) > 1):
            info.interactive = tr("«{name}» è un programma interattivo e qui non riceverebbe input").format(name=name)
            break
    if not info.interactive and _FOLLOW.search(cmd):
        info.interactive = tr("il comando resta in ascolto finché non premi «Ferma» (o fino al timeout)")
    return info


_BUILTINS = {"cd", "export", "echo", "printf", "source", ".", "for", "if", "while", "test", "[",
             "unset", "alias", "type", "ulimit", "umask", "set", "read", "case"}
# "$ cmd" oppure "utente@host:~$ cmd" / "root@host:~# cmd"; un "#" da solo è un commento
_PROMPT = re.compile(r"^\s*(?:[\w.-]+@[\w.-]+[:~][^$#\n]*[$#]|\$)\s+")


def looks_like_command(text: str) -> str | None:
    """Se il testo copiato sembra un comando di shell lo restituisce ripulito, altrimenti None.

    Serve a riconoscere i comandi copiati dalla chat web: deve essere breve e iniziare con
    un programma esistente sul PC (o un builtin di bash).
    """
    text = (text or "").strip()
    if not text or len(text) > 3000 or text.count("\n") > 30:
        return None
    lines = [_PROMPT.sub("", line, count=1) for line in text.splitlines()]
    cleaned = "\n".join(lines).strip()
    first_line = next((ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")), "")
    words = first_line.split()
    while words and (words[0] in ("sudo", "env", "nohup", "time", "command") or re.match(r"^\w+=\S*$", words[0])):
        words.pop(0)
    if not words:
        return None
    name = words[0]
    if name in _BUILTINS or (re.match(r"^[\w.+/-]+$", name) and shutil.which(name)):
        return cleaned
    return None


def strip_sudo(cmd: str) -> str:
    return _SUDO_PLAIN.sub(r"\1", cmd)


def pkexec_available() -> bool:
    return shutil.which("pkexec") is not None


def clean_output(text: str) -> str:
    text = _ANSI.sub("", text).replace("\r\n", "\n")
    if "\r" in text:  # barre di avanzamento: tieni solo l'ultimo aggiornamento di ogni riga
        text = "\n".join(line.split("\r")[-1] for line in text.split("\n"))
    return text


@dataclass
class CommandResult:
    cmd: str
    rc: int
    cwd: str
    output: str
    root: bool = False
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    duration: float = 0.0


class CommandRunner(QThread):
    chunk = Signal(str)          # output in tempo reale
    completed = Signal(object)   # CommandResult

    def __init__(self, cmd: str, cwd: str, root: bool = False, timeout: int = 120,
                 prev_cwd: str | None = None, parent=None):
        super().__init__(parent)
        self.cmd, self.cwd, self.root, self.timeout = cmd, cwd, root, timeout
        self.prev_cwd = prev_cwd or cwd
        self._cancel = threading.Event()
        self.proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def _env(self) -> dict:
        env = os.environ.copy()
        env.update(TERM="dumb", PAGER="cat", SYSTEMD_PAGER="cat", GIT_PAGER="cat", MANPAGER="cat",
                   NO_COLOR="1", SYSTEMD_COLORS="0", DEBIAN_FRONTEND="noninteractive",
                   OLDPWD=self.prev_cwd)
        return env

    def _kill(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        for sig, wait in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                try:
                    self.proc.send_signal(sig)
                except (ProcessLookupError, PermissionError):
                    return
            try:
                self.proc.wait(wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def run(self) -> None:  # noqa: C901 - flusso lineare, più leggibile in un unico metodo
        start = time.monotonic()
        r_fd, w_fd = os.pipe()
        bash = shutil.which("bash") or "/bin/bash"
        if self.root:
            script = f"cd {shlex.quote(self.cwd)} || exit 1\n{strip_sudo(self.cmd)}\n"
            argv, fds = ["pkexec", bash, "-c", script], ()
        else:
            script = f"trap 'printf \"%s\" \"$PWD\" >&{w_fd} 2>/dev/null' EXIT\n{self.cmd}\n"
            argv, fds = [bash, "-c", script], (w_fd,)
        try:
            self.proc = subprocess.Popen(
                argv, cwd=self.cwd, env=self._env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=fds,
                start_new_session=True, bufsize=0)  # byte: il testo "universal newlines" trasformerebbe \r in \n
        except OSError as exc:
            os.close(r_fd)
            os.close(w_fd)
            msg = tr("Impossibile avviare il comando: {exc}\n").format(exc=exc)
            self.chunk.emit(msg)
            self.completed.emit(CommandResult(self.cmd, 127, self.cwd, msg, self.root))
            return
        os.close(w_fd)

        lines: queue.Queue = queue.Queue()

        def reader():
            assert self.proc and self.proc.stdout
            for raw in self.proc.stdout:
                lines.put(raw.decode("utf-8", "replace"))
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()

        captured: list[str] = []
        size, truncated, timed_out, cancelled = 0, False, False, False
        pending: list[str] = []
        last_emit = time.monotonic()
        exited_at = None
        deadline = start + self.timeout if self.timeout else None

        while True:
            try:
                line = lines.get(timeout=0.05)
            except queue.Empty:
                line = ""
                if self.proc.poll() is not None:
                    # processi in background possono tenere aperto stdout: non aspettarli
                    exited_at = exited_at or time.monotonic()
                    if time.monotonic() - exited_at > 0.5:
                        break
                if deadline and time.monotonic() > deadline and not timed_out:
                    timed_out = True
                    self._kill()
                if self._cancel.is_set() and not cancelled:
                    cancelled = True
                    self._kill()
            if line is None:
                break
            if line:
                line = clean_output(line)
                pending.append(line)
                if size < MAX_CAPTURE:
                    captured.append(line)
                    size += len(line)
                else:
                    truncated = True
            if pending and (time.monotonic() - last_emit > 0.05 or line == ""):
                self.chunk.emit("".join(pending))
                pending.clear()
                last_emit = time.monotonic()
        if pending:
            self.chunk.emit("".join(pending))

        try:
            rc = self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self._kill()
            rc = self.proc.returncode if self.proc.returncode is not None else -9

        new_cwd = self.cwd
        try:
            os.set_blocking(r_fd, False)
            data = os.read(r_fd, 65536).decode("utf-8", "replace")
            if data and os.path.isdir(data):
                new_cwd = data
        except (BlockingIOError, OSError):
            pass
        finally:
            os.close(r_fd)

        self.completed.emit(CommandResult(
            self.cmd, rc, new_cwd, "".join(captured), self.root, timed_out, cancelled,
            truncated, time.monotonic() - start))
