# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collegamento con la finestra di Helpix già aperta (un'istanza sola).

L'app ascolta su un socket locale accessibile solo all'utente. Lo usano:
- `helpix` lanciato di nuovo: porta in primo piano la finestra esistente;
- `helpix --quick`: la finestra rapida manda testo e richieste di screenshot all'app.
Protocollo: una riga JSON per messaggio, in entrambe le direzioni.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def socket_path() -> str:
    from .bridge_host import runtime_base
    return os.path.join(runtime_base(), "helpix", "app.sock")


def is_running(path: str | None = None) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(path or socket_path())
        return True
    except OSError:
        return False
    finally:
        s.close()


def send_once(msg: dict, path: str | None = None) -> bool:
    """Invia un messaggio all'app aperta senza aspettare risposta (es. «mostra la finestra»)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(path or socket_path())
        s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False
    finally:
        s.close()


def request(msg: dict, path: str, timeout: float = 1.0) -> dict | None:
    """Invia un messaggio e aspetta una riga di risposta (None se non risponde)."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n", 1)[0]
        reply = json.loads(line.decode("utf-8")) if line.strip() else None
        return reply if isinstance(reply, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def peer_pid(path: str) -> int | None:
    """Pid del processo in ascolto sul socket (credenziali del socket: solo processi dello stesso utente)."""
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    import struct
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(path)
        pid, uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        return pid if uid == os.getuid() and pid > 0 else None
    except OSError:
        return None
    finally:
        s.close()


class InstanceServer(QObject):
    message = Signal(dict, object)   # messaggio, connessione (per rispondere con reply())

    def __init__(self, parent=None, path: str | None = None):
        super().__init__(parent)
        self.path = path or socket_path()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._bufs: dict[int, bytes] = {}

    def start(self) -> bool:
        folder = Path(self.path).parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.chmod(folder, 0o700)
        except OSError:
            return False
        if is_running(self.path):
            return False
        QLocalServer.removeServer(self.path)
        ok = self.server.listen(self.path)
        if ok:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        return ok

    def stop(self):
        self.server.close()
        QLocalServer.removeServer(self.path)

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(self._read)
            sock.disconnected.connect(sock.deleteLater)

    def _read(self):
        sock = self.sender()
        if not isinstance(sock, QLocalSocket):
            return
        key = id(sock)
        buf = self._bufs.get(key, b"") + bytes(sock.readAll())
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(msg, dict):
                self.message.emit(msg, sock)
        self._bufs[key] = buf[-1_000_000:]

    @staticmethod
    def reply(sock, msg: dict):
        try:
            if sock is not None and sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
                sock.write((json.dumps(msg) + "\n").encode("utf-8"))
                sock.flush()
        except RuntimeError:  # connessione già chiusa
            pass
