#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host di native messaging di Helpix: il ponte tra l'estensione del browser e l'app.

Il browser avvia questo programma quando l'estensione si collega e gli parla su stdin/stdout
con il protocollo di native messaging (4 byte di lunghezza + JSON UTF-8). Il programma
inoltra i messaggi all'app Helpix in esecuzione tramite un socket locale (una riga JSON per
messaggio), accessibile solo all'utente.

Usa solo la libreria standard: deve partire in fretta e non dipendere da Qt.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

MAX_TO_BROWSER = 900_000        # Chrome accetta al massimo 1 MB per messaggio verso l'estensione
CHUNK = 700_000
MAX_FROM_BROWSER = 64 * 1024 * 1024
QUEUE_LIMIT = 50


def runtime_base() -> str:
    """Cartella privata per i socket di Helpix.

    Di norma $XDG_RUNTIME_DIR (/run/user/UID, solo dell'utente). Se manca (sessioni senza systemd,
    alcuni avvii da cron o SSH) uso ~/.cache/helpix-run invece di /tmp, dove un altro utente
    potrebbe creare per primo la cartella con un nome prevedibile.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isdir(base):
        return base
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(cache, "helpix-run")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def socket_path() -> str:
    return os.path.join(runtime_base(), "helpix", "bridge.sock")


# ------------------------------------------------------------------ protocollo del browser
def _read_exact(stream, n: int) -> bytes | None:
    """Legge esattamente n byte (le pipe consegnano i messaggi grandi a pezzi)."""
    chunks, got = [], 0
    while got < n:
        part = stream.read(n - got)
        if not part:
            return None
        chunks.append(part)
        got += len(part)
    return b"".join(chunks)


def read_message(stream):
    raw = _read_exact(stream, 4)
    if raw is None:
        return None
    (length,) = struct.unpack("=I", raw)
    if length > MAX_FROM_BROWSER:
        raise ValueError("messaggio troppo grande")
    data = _read_exact(stream, length)
    if data is None:
        return None
    return json.loads(data.decode("utf-8"))


def encode_message(obj) -> bytes:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("=I", len(data)) + data


def split_for_browser(obj) -> list:
    """Divide i messaggi oltre il limite del browser in pezzi che l'estensione ricompone."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) <= MAX_TO_BROWSER:
        return [obj]
    cid = uuid.uuid4().hex
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    return [{"type": "chunk", "id": cid, "i": i, "n": len(parts), "data": p} for i, p in enumerate(parts)]


class Host:
    def __init__(self, stdin, stdout, path: str | None = None, launch_cmd: str | None = None):
        self.stdin, self.stdout = stdin, stdout
        self.path = path or socket_path()
        self.launch_cmd = launch_cmd if launch_cmd is not None else os.environ.get("HELPIX_CMD", "")
        self.sock: socket.socket | None = None
        self.out_lock = threading.Lock()
        self.sock_lock = threading.Lock()
        self.queue: list[dict] = []
        self.running = True
        self._last_status = None
        self._launched = 0.0

    # -------------------------------------------------- verso il browser
    def to_browser(self, obj):
        with self.out_lock:
            try:
                for part in split_for_browser(obj):
                    self.stdout.write(encode_message(part))
                self.stdout.flush()
            except (BrokenPipeError, OSError, ValueError):
                self.running = False  # il browser ha chiuso il collegamento

    def status(self, connected: bool):
        if connected != self._last_status:
            self._last_status = connected
            self.to_browser({"type": "helpix_status", "connected": connected})

    # -------------------------------------------------- verso l'app
    def to_app(self, obj) -> bool:
        with self.sock_lock:
            if self.sock is None:
                return False
            try:
                self.sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
                return True
            except OSError:
                self._drop()
                return False

    def _drop(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def launch_app(self):
        """Avvia Helpix se non è aperto (al massimo una volta ogni 20 secondi)."""
        if not self.launch_cmd or time.monotonic() - self._launched < 20:
            return
        self._launched = time.monotonic()
        try:
            subprocess.Popen(shlex.split(self.launch_cmd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.to_browser({"type": "notify", "text": f"Impossibile avviare Helpix: {exc}"})

    # -------------------------------------------------- cicli
    def socket_loop(self):
        while self.running:
            if self.sock is None:
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(self.path)
                    with self.sock_lock:
                        self.sock = s
                    self.status(True)
                    pending, self.queue = self.queue, []
                    for msg in pending:
                        self.to_app(msg)
                except OSError:
                    self.status(False)
                    time.sleep(1.0)
                    continue
            buf = b""
            try:
                while self.running:
                    data = self.sock.recv(65536)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            try:
                                self.to_browser(json.loads(line.decode("utf-8")))
                            except ValueError:
                                pass
            except OSError:
                pass
            with self.sock_lock:
                self._drop()
            self.status(False)

    def stdin_loop(self):
        while self.running:
            try:
                msg = read_message(self.stdin)
            except (ValueError, OSError):
                msg = None
            if msg is None:  # il browser ha chiuso il collegamento
                self.running = False
                break
            if msg.get("type") == "launch":
                self.launch_app()
                continue
            if msg.get("type") == "ping":
                self.to_browser({"type": "pong", "connected": self.sock is not None})
                continue
            if not self.to_app(msg):
                if len(self.queue) < QUEUE_LIMIT:
                    self.queue.append(msg)
                if msg.get("type") in ("run", "screenshot", "diagnostics", "summary"):
                    self.launch_app()

    def run(self):
        threading.Thread(target=self.socket_loop, daemon=True).start()
        self.stdin_loop()
        with self.sock_lock:
            self._drop()


def main() -> int:
    Host(sys.stdin.buffer, sys.stdout.buffer).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
