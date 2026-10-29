# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""«Esci da Helpix» chiude tutto e niente lo riapre da solo (python tests/test_quit.py).

Processi veri: Helpix (finestra principale) e la finestra rapida (`helpix --quick`), che è un processo a sé.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
ENV = dict(os.environ, XDG_CONFIG_HOME=os.path.join(_tmp, "config"), XDG_DATA_HOME=os.path.join(_tmp, "data"),
           XDG_RUNTIME_DIR=os.path.join(_tmp, "run"), QT_QPA_PLATFORM="offscreen",
           QTWEBENGINE_DISABLE_SANDBOX="1", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu", PYTHONPATH=ROOT)
os.makedirs(ENV["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.update({k: ENV[k] for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR")})

from helpix.instance import is_running, socket_path  # noqa: E402
from helpix.ui.quick_window import quick_socket_path  # noqa: E402

# Helpix «vero» senza finestra di avvio, giro guidato e domande; dopo un po' esce come dal menu dell'icona
MAIN = r"""
import os, sys, PySide6.QtWebEngineWidgets
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QSystemTrayIcon
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)  # come sul desktop: icona nell'area di notifica
app = QApplication([])
from helpix.config import Settings, SecretStore, ensure_dirs
ensure_dirs()
from helpix.ui.main_window import MainWindow
s = Settings(); s.data.update(engine="api", skip_setup=True, quick_shortcut=False, show_tips=False)
w = MainWindow(s, SecretStore()); w.show()
assert w.tray is not None
mode = sys.argv[1]
if mode == "quit":
    QTimer.singleShot(int(sys.argv[2]), w.quit_app)  # «Esci da Helpix» dal menu dell'icona
app.exec()
os._exit(0)
"""


def wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


def start_main(*args):
    return subprocess.Popen([sys.executable, "-c", MAIN, *args], env=ENV, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def start_quick():
    return subprocess.Popen([sys.executable, "-m", "helpix", "--quick"], env=ENV, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def cleanup(*procs):
    for p in procs:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
    # anche gli Helpix eventualmente riaperti: tutti i processi con la cartella di prova nell'ambiente
    marker = ("XDG_RUNTIME_DIR=" + ENV["XDG_RUNTIME_DIR"]).encode()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                if marker in f.read().split(b"\0"):
                    os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass


def test_exit_closes_everything():
    main = start_main("quit", "9000")
    assert wait(lambda: is_running(socket_path()), 30), "Helpix non è partito"
    quick = start_quick()
    try:
        assert wait(lambda: is_running(quick_socket_path()), 20), "finestra rapida non partita"
        assert main.wait(30) == 0, "Helpix non è uscito"
        assert quick.wait(10) is not None, "la finestra rapida deve chiudersi insieme a Helpix"
        # nessuno lo riapre: per 6 secondi nessun Helpix in ascolto
        assert not wait(lambda: is_running(socket_path()), 6), "Helpix si è riaperto da solo"
    finally:
        cleanup(main, quick)


def test_quick_window_does_not_resurrect_helpix():
    """Helpix finisce senza salutare (es. un crash): la finestra rapida non lo riavvia per conto suo."""
    main = start_main("stay")
    assert wait(lambda: is_running(socket_path()), 30), "Helpix non è partito"
    quick = start_quick()
    try:
        assert wait(lambda: is_running(quick_socket_path()), 20), "finestra rapida non partita"
        time.sleep(1.5)  # collegata a Helpix
        os.killpg(main.pid, signal.SIGKILL)
        main.wait(10)
        assert not wait(lambda: is_running(socket_path()), 6), "la finestra rapida ha riaperto Helpix da sola"
        assert quick.poll() is None, "la finestra rapida resta disponibile"
    finally:
        cleanup(main, quick)


def test_old_quick_window_from_previous_version():
    """Dopo un aggiornamento può restare in giro la finestra rapida della versione prima, che ignora «quit»
    e riapriva Helpix: la nuova Helpix la riconosce e la chiude."""
    log = os.path.join(_tmp, "old_quick.log")
    env = dict(ENV, OLD_QUICK_LOG=log)
    # come la vera: «python -m helpix --quick» (Helpix controlla la riga di comando prima di terminarla)
    old = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "quick", "old_quick.py"), "--quick"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    assert wait(lambda: is_running(quick_socket_path()), 10), "finestra rapida vecchia non partita"
    main = start_main("quit", "9000")
    try:
        assert wait(lambda: is_running(socket_path()), 30), "Helpix non è partito"
        assert main.wait(30) == 0, "Helpix non è uscito"
        assert wait(lambda: old.poll() is not None, 10), "la finestra rapida vecchia deve essere chiusa"
        assert not wait(lambda: is_running(socket_path()), 6), "Helpix si è riaperto da solo"
        assert "relaunch" not in open(log).read()
    finally:
        cleanup(main, old)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
