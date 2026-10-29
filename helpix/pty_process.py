# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Un programma in un terminale vero (pseudo-terminale), letto e scritto da Qt.

Serve per gli agenti a riga di comando (Claude Code, Codex, Gemini CLI): sono interfacce
a tutto schermo che hanno bisogno di un TTY con dimensioni, colori e tasti come in un
terminale normale.
"""
from __future__ import annotations

import codecs
import errno
import fcntl
import os
import shutil
import signal
import struct
import subprocess
import termios

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal


def _set_size(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0))


def _child_setup() -> None:  # nel processo figlio, dopo setsid: il PTY diventa il terminale di controllo
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class PtyProcess(QObject):
    output = Signal(str)     # testo dal programma (già decodificato, in blocchi)
    finished = Signal(int)   # codice di uscita

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: subprocess.Popen | None = None
        self.fd: int | None = None
        self._notifier: QSocketNotifier | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf: list[str] = []
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.setInterval(12)  # raggruppa l'output: meno chiamate verso la pagina del terminale
        self._flush.timeout.connect(self._emit)
        self.cols, self.rows = 100, 30

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, argv: list[str], cwd: str, env: dict | None = None) -> None:
        self.stop()
        master, slave = os.openpty()
        _set_size(slave, self.cols, self.rows)
        full_env = dict(os.environ)
        full_env.update(env or {})
        full_env.update(TERM="xterm-256color", COLORTERM="truecolor")
        # Il programma deve avere il PTY come terminale di controllo (sudo, Ctrl+C, ridimensionamento).
        # `setsid --ctty` (util-linux) lo fa senza eseguire codice Python nel processo figlio, cosa
        # rischiosa con più thread attivi; preexec_fn resta solo come ripiego.
        setsid = shutil.which("setsid")
        try:
            if setsid:
                self.proc = subprocess.Popen([setsid, "--ctty", *argv], cwd=cwd, env=full_env, stdin=slave,
                                             stdout=slave, stderr=slave, close_fds=True)
            else:
                self.proc = subprocess.Popen(argv, cwd=cwd, env=full_env, stdin=slave, stdout=slave, stderr=slave,
                                             start_new_session=True, preexec_fn=_child_setup, close_fds=True)
        except OSError:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        os.set_blocking(master, False)
        self.fd = master
        self._decoder.reset()
        self._notifier = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read)

    def _read(self, *_):
        if self.fd is None:
            return
        try:
            data = os.read(self.fd, 65536)
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                return
            data = b""  # EIO: il programma ha chiuso il terminale
        if not data:
            self._closed()
            return
        self._buf.append(self._decoder.decode(data))
        if not self._flush.isActive():
            self._flush.start()

    def _emit(self):
        if self._buf:
            text, self._buf = "".join(self._buf), []
            self.output.emit(text)

    def _closed(self):
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self._emit()
        rc = 0
        if self.proc is not None:
            try:
                rc = self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                rc = self.proc.wait()
        self.proc = None
        self.finished.emit(rc)

    def write(self, text: str) -> None:
        self._write_bytes(text.encode("utf-8"))

    def _write_bytes(self, data: bytes) -> None:
        while data and self.fd is not None:
            try:
                n = os.write(self.fd, data)
            except BlockingIOError:  # il programma non sta leggendo: riprovo tra poco con il resto
                QTimer.singleShot(10, lambda rest=data: self._write_bytes(rest))
                return
            except OSError:
                return
            data = data[n:]

    def paste(self, text: str) -> None:
        """Incolla come in un terminale moderno (bracketed paste): il programma non lo esegue riga per riga."""
        self.write("\x1b[200~" + text.replace("\x1b", "") + "\x1b[201~")

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = max(cols, 2), max(rows, 2)
        if self.fd is not None:
            try:
                _set_size(self.fd, self.cols, self.rows)
            except OSError:
                pass
            if self.proc is not None:
                try:
                    os.killpg(self.proc.pid, signal.SIGWINCH)
                except OSError:
                    pass

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        if self.fd is not None or self.proc is not None:
            self._closed()
