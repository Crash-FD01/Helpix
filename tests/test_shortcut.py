# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorciatoia globale tramite portal, su un D-Bus vero con un portal finto.

Esegui con: dbus-run-session -- python tests/test_shortcut.py
"""
import sys as _sys
if _sys.platform == "win32":
    print("saltato su Windows: scorciatoia globale tramite il portal di Linux (su Windows: test_windows)")
    raise SystemExit(0)

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
from helpix.global_shortcut import GlobalShortcut  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal", "fake_portal.py")


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run_with(mode):
    portal = subprocess.Popen([sys.executable, FAKE, mode], stdout=subprocess.PIPE, text=True)
    assert portal.stdout.readline().strip() == "ready"
    gs = GlobalShortcut("CTRL+ALT+h", "Helpix: richiesta rapida")
    states, presses = [], []
    gs.state.connect(lambda kind, text: states.append((kind, text)))
    gs.activated.connect(lambda: presses.append(1))
    gs.start()
    end = time.monotonic() + 10
    while time.monotonic() < end and not (states and (presses or states[-1][0] == "error")):
        pump(50)
    gs.stop()
    portal.kill()
    return states, presses


def test_bind_and_activate():
    states, presses = run_with("ok")
    assert states and states[0] == ("bound", "Ctrl+Alt+H"), states
    assert presses, "la pressione dei tasti deve arrivare a Helpix"


def test_second_start_binds_again():
    """KDE Plasma ≥ 6.7.4: anche se la scorciatoia è già salvata va riconfermata (senza dialogo) a ogni avvio."""
    portal = subprocess.Popen([sys.executable, FAKE, "ok"], stdout=subprocess.PIPE, text=True)
    assert portal.stdout.readline().strip() == "ready"
    for run in range(2):
        gs = GlobalShortcut()
        states, presses = [], []
        gs.state.connect(lambda kind, text: states.append((kind, text)))  # noqa: B023
        gs.activated.connect(lambda: presses.append(1))  # noqa: B023
        gs.start()
        end = time.monotonic() + 10
        while time.monotonic() < end and not presses:
            pump(50)
        gs.stop()
        assert states and states[0][0] == "bound" and presses, (run, states, presses)
    portal.kill()


def test_user_declines():
    states, presses = run_with("deny")
    assert states and states[-1][0] == "error" and "non confermata" in states[-1][1], states
    assert not presses


def test_no_portal():
    gs = GlobalShortcut()
    states = []
    gs.state.connect(lambda kind, text: states.append((kind, text)))
    gs.start()
    end = time.monotonic() + 15
    while time.monotonic() < end and not states:
        pump(50)
    gs.stop()
    assert states and states[0][0] == "error", states


if __name__ == "__main__":
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        sys.exit(subprocess.call(["dbus-run-session", "--", sys.executable, *sys.argv]))
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
