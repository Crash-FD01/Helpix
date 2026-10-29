# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test del canale estensione ↔ Helpix (python tests/test_bridge.py)."""
import sys as _sys
if _sys.platform == "win32":
    print("saltato su Windows: l'estensione del browser (messa da parte) gira solo su Linux")
    raise SystemExit(0)

import io
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpix import bridge_host  # noqa: E402
from helpix.bridge import BridgeServer  # noqa: E402

app = QApplication.instance() or QApplication([])


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_framing_and_chunks():
    msg = {"type": "x", "text": "ciao àè"}
    assert bridge_host.read_message(io.BytesIO(bridge_host.encode_message(msg))) == msg
    big = {"type": "paste_image", "data": "A" * 2_500_000}
    parts = bridge_host.split_for_browser(big)
    assert len(parts) > 1 and all(p["type"] == "chunk" for p in parts)
    assert all(len(json.dumps(p).encode()) < 1_000_000 for p in parts)  # limite di Chrome
    assert json.loads("".join(p["data"] for p in sorted(parts, key=lambda p: p["i"]))) == big
    assert bridge_host.split_for_browser(msg) == [msg]


class _Pipe:
    """stdin/stdout binari collegati come quelli che usa il browser."""

    def __init__(self):
        r, w = os.pipe()
        self.r, self.w = os.fdopen(r, "rb", buffering=0), os.fdopen(w, "wb", buffering=0)


def test_host_and_server_roundtrip():
    path = os.path.join(_tmp, "rt", "bridge.sock")
    server = BridgeServer(path=path)
    assert server.start()
    assert oct(os.stat(os.path.dirname(path)).st_mode & 0o777) == "0o700"
    got = {}
    server.run_requested.connect(lambda m: got.setdefault("run", m))
    to_host, from_host = _Pipe(), _Pipe()
    host = bridge_host.Host(to_host.r, from_host.w, path=path, launch_cmd="")
    threading.Thread(target=host.run, daemon=True).start()

    out = []

    def reader():
        while True:
            m = bridge_host.read_message(from_host.r)
            if m is None:
                break
            out.append(m)

    threading.Thread(target=reader, daemon=True).start()
    for m in ({"type": "hello", "browser": "Chromium", "version": "0.8.0"},
              {"type": "run", "id": "r1", "cmd": "uname -s", "site": "chatgpt", "tab": 7}):
        to_host.w.write(bridge_host.encode_message(m))
    deadline = time.monotonic() + 5
    while "run" not in got and time.monotonic() < deadline:
        pump(50)
    assert got["run"]["cmd"] == "uname -s" and server.browsers() == ["Chromium"]
    assert server.target("chatgpt")[1] == 7 and server.has_site("chatgpt")

    img = QImage(1600, 1200, QImage.Format.Format_ARGB32)
    for y in range(0, 1200, 7):  # contenuto vario: il PNG non si comprime troppo
        img.fill(QColor((y * 37) % 255, (y * 11) % 255, (y * 3) % 255)) if y == 0 else None
    noisy = os.path.join(_tmp, "noise.png")
    import random
    for x in range(0, 1600, 3):
        for y in range(0, 1200, 3):
            img.setPixelColor(x, y, QColor(random.randrange(256), random.randrange(256), random.randrange(256)))
    img.save(noisy)
    assert server.paste_text("chatgpt", "output del comando")
    assert server.paste_image("chatgpt", noisy)
    assert server.run_status(got["run"], "done", rc=0)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not any(m.get("type") == "run_status" for m in out):
        pump(50)
    kinds = [m["type"] for m in out]
    assert "helpix_status" in kinds and "hello_ack" in kinds and "paste_text" in kinds
    assert "chunk" in kinds, "l'immagine grande deve arrivare a pezzi"
    pasted = next(m for m in out if m["type"] == "paste_text")
    assert pasted["tab"] == 7 and pasted["site"] == "chatgpt"
    status = next(m for m in out if m["type"] == "run_status")
    assert status["id"] == "r1" and status["rc"] == 0
    to_host.w.close()
    server.stop()


def test_host_launches_app_and_queues():
    """Helpix chiuso: l'host tiene da parte la richiesta, avvia l'app e la consegna quando si collega."""
    path = os.path.join(_tmp, "launch", "bridge.sock")
    marker = os.path.join(_tmp, "launched")
    to_host, from_host = _Pipe(), _Pipe()
    host = bridge_host.Host(to_host.r, from_host.w, path=path, launch_cmd=f"touch {marker}")
    threading.Thread(target=host.run, daemon=True).start()
    to_host.w.write(bridge_host.encode_message({"type": "run", "id": "q", "cmd": "true", "site": "claude", "tab": 3}))
    deadline = time.monotonic() + 5
    while not os.path.exists(marker) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert os.path.exists(marker), "l'host deve avviare Helpix"
    server = BridgeServer(path=path)
    got = {}
    server.run_requested.connect(lambda m: got.setdefault("run", m))
    assert server.start()
    deadline = time.monotonic() + 6
    while "run" not in got and time.monotonic() < deadline:
        pump(50)
    assert got["run"]["id"] == "q", "la richiesta in coda deve arrivare all'app appena si collega"
    second = BridgeServer(path=path)
    assert not second.start(), "una seconda finestra di Helpix non deve rubare il collegamento"
    to_host.w.close()
    server.stop()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
