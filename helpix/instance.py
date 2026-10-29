# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Collegamento con la finestra di Helpix già aperta (un'istanza sola).

L'app ascolta su un canale locale accessibile solo all'utente: un socket Unix su Linux, una named pipe su
Windows (QLocalServer crea l'una o l'altra). Lo usano:
- `helpix` lanciato di nuovo: porta in primo piano la finestra esistente;
- `helpix --quick`: la finestra rapida manda testo e richieste di screenshot all'app.
Protocollo: una riga JSON per messaggio, in entrambe le direzioni.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .system import IS_WINDOWS, channel


def socket_path() -> str:
    return channel("app")


# ------------------------------------------------------------------ Windows: client delle named pipe
class _Pipe:
    r"""Client minimo di una named pipe (\\.\pipe\<nome>) con timeout, tramite l'API di Windows."""

    def __init__(self, name: str, timeout: float):
        import ctypes
        from ctypes import wintypes
        self._k = k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        k.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
        k.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self._ct, self._wt = ctypes, wintypes
        self.timeout = timeout
        path = name if name.startswith("\\\\") else "\\\\.\\pipe\\" + name
        deadline = time.monotonic() + timeout
        invalid = wintypes.HANDLE(-1).value
        while True:
            h = k.CreateFileW(path, 0x80000000 | 0x40000000, 0, None, 3, 0, None)  # lettura+scrittura, OPEN_EXISTING
            if h and h != invalid:
                self.handle = h
                # server nello stesso processo (la finestra principale che parla con sé stessa, i test): mentre
                # aspetto devo far girare gli eventi di Qt, se no il server non legge e restiamo bloccati entrambi
                self.own = self.server_pid() == os.getpid()
                return
            err = ctypes.get_last_error()
            left = deadline - time.monotonic()
            if err != 231 or left <= 0:  # 231: tutte le istanze occupate, si può aspettare; altro: non c'è nessuno
                raise OSError(err, "named pipe non disponibile")
            k.WaitNamedPipeW(path, max(1, int(left * 1000)))

    def _pump(self) -> None:
        if self.own:
            from PySide6.QtCore import QCoreApplication
            if QCoreApplication.instance() is not None:
                QCoreApplication.processEvents()

    def send(self, data: bytes) -> None:
        """Scrive con un limite di tempo: la scrittura su una pipe aspetta che l'altra parte legga, e un Helpix
        bloccato non deve bloccare anche chi lo chiama."""
        import threading
        result: dict = {}
        view = self._ct.create_string_buffer(data, len(data))

        def write():
            done = self._wt.DWORD(0)
            ok = self._k.WriteFile(self.handle, view, len(data), self._ct.byref(done), None)
            result["ok"] = bool(ok) and done.value == len(data)
            result["err"] = self._ct.get_last_error()

        t = threading.Thread(target=write, daemon=True)
        t.start()
        deadline = time.monotonic() + max(self.timeout, 0.5)
        while t.is_alive() and time.monotonic() < deadline:
            self._pump()
            t.join(0.01)
        if t.is_alive():
            self._k.CancelIoEx(self.handle, None)
            t.join(1.0)
            raise OSError(1460, "scrittura sulla named pipe scaduta")  # ERROR_TIMEOUT
        if not result.get("ok"):
            raise OSError(result.get("err", 0), "scrittura sulla named pipe non riuscita")

    def read_line(self, timeout: float) -> bytes:
        buf, deadline = b"", time.monotonic() + timeout
        avail = self._wt.DWORD(0)
        while b"\n" not in buf:
            if not self._k.PeekNamedPipe(self.handle, None, 0, None, self._ct.byref(avail), None):
                break  # chiusa dall'altra parte
            if avail.value:
                chunk = self._ct.create_string_buffer(min(avail.value, 65536))
                got = self._wt.DWORD(0)
                if not self._k.ReadFile(self.handle, chunk, len(chunk), self._ct.byref(got), None):
                    break
                buf += chunk.raw[:got.value]
                continue
            if time.monotonic() >= deadline:
                break
            self._pump()
            time.sleep(0.01)
        return buf

    def server_pid(self) -> int | None:
        pid = self._wt.ULONG(0)
        return pid.value if self._k.GetNamedPipeServerProcessId(self.handle, self._ct.byref(pid)) and pid.value else None

    def close(self) -> None:
        self._k.CloseHandle(self.handle)


def _win_exchange(msg: dict | None, path: str, timeout: float, want_reply: bool) -> dict | bool | None:
    try:
        pipe = _Pipe(path, timeout)
    except OSError:
        return None
    try:
        if msg is not None:
            pipe.send((json.dumps(msg) + "\n").encode("utf-8"))
        if not want_reply:
            return True
        line = pipe.read_line(timeout).split(b"\n", 1)[0]
        reply = json.loads(line.decode("utf-8")) if line.strip() else None
        return reply if isinstance(reply, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        pipe.close()


# ------------------------------------------------------------------ client
def is_running(path: str | None = None) -> bool:
    if IS_WINDOWS:
        return _win_exchange(None, path or socket_path(), 0.5, False) is True
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
    if IS_WINDOWS:
        return _win_exchange(msg, path or socket_path(), 1.0, False) is True
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
    if IS_WINDOWS:
        reply = _win_exchange(msg, path, timeout, True)
        return reply if isinstance(reply, dict) else None
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
    """Pid del processo in ascolto sul socket (credenziali del socket: solo processi dello stesso utente).

    Su Windows la pipe accetta solo l'utente stesso (QLocalServer.UserAccessOption): il pid lo dà il sistema."""
    if IS_WINDOWS:
        try:
            pipe = _Pipe(path, 1.0)
        except OSError:
            return None
        try:
            return pipe.server_pid()
        finally:
            pipe.close()
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
        if not IS_WINDOWS:  # su Windows è il nome di una named pipe, non un file
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
        if ok and not IS_WINDOWS:
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
