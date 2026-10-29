# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Area di notifica, scorciatoia della finestra rapida e lanciatore KDE (python tests/test_tray.py)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402

ensure_dirs()


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_quick_shortcut_hides_and_debounces():
    from helpix.ui.quick_window import QuickWindow
    q = QuickWindow()
    q.toggle()
    pump(100)
    assert q.isVisible()
    sc = [s for s in q.findChildren(QShortcut) if s.key().toString() == "Ctrl+Alt+H"]
    assert sc, "la scorciatoia deve funzionare anche con la finestra rapida in primo piano"
    sc[0].activated.emit()
    assert not q.isVisible()
    q.toggle()           # stessa pressione arrivata due volte: conta una sola
    q.toggle()
    assert q.isVisible()
    time.sleep(0.4)
    q.toggle()
    assert not q.isVisible()


def test_kde_launcher():
    from helpix import shortcut_setup as ss
    path = ss.install_kde()
    text = path.read_text(encoding="utf-8")
    assert "X-KDE-Shortcuts=Ctrl+Alt+H" in text and "--quick" in text and path.name == "helpix-quick.desktop"


def test_tray():
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    win.show()
    pump(200)
    assert win.tray is not None and not app.quitOnLastWindowClosed()
    calls = []
    real_to_tray = win.to_tray
    win.to_tray = lambda: (calls.append("to_tray"), real_to_tray())
    import traceback
    for name in ("show", "showNormal", "setVisible", "showMaximized", "raise_", "activateWindow"):
        real = getattr(win, name)
        setattr(win, name, lambda *a, _n=name, _r=real: (calls.append(
            _n + str(a) + " ← " + " / ".join(ln.strip().splitlines()[0] for ln in traceback.format_stack()[-4:-1])),
            _r(*a)))
    win.close()  # la X: resta nell'area di notifica
    for _ in range(30):  # sulle macchine lente (CI) chiusura e icona arrivano qualche istante dopo
        pump(100)
        if not win.isVisible() and win.tray.isVisible():
            break
    shown = [type(w).__name__ + ":" + w.objectName() for w in QApplication.topLevelWidgets() if w.isVisible()]
    assert not win.isVisible() and win.tray.isVisible(), (win.isVisible(), win.tray.isVisible(), calls,
                                                          int(win.windowState().value), shown)
    assert not win.isVisible() and not win._quitting
    win.show_from_tray()
    assert win.isVisible()
    from helpix import instance
    assert instance.is_running(), "da nascosto continua a rispondere (finestra rapida, scorciatoia)"
    quits = []
    app.aboutToQuit.connect(lambda: quits.append(True))
    orig_quit = app.quit
    app.quit = lambda: quits.append("quit")
    win.quit_app()
    assert "quit" in quits and not win.isVisible()
    app.quit = orig_quit


def test_first_start_asks_for_shortcut():
    """Al primo avvio Helpix propone Ctrl+Alt+H; con «Attiva» lo chiede al desktop."""
    from PySide6.QtWidgets import QMessageBox
    from helpix.ui.main_window import MainWindow
    started = []
    MainWindow._start_global_shortcut = lambda self: started.append(True)

    def answer():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            next(b for b in box.buttons() if "Ctrl+Alt+H" in b.text()).click()
        else:
            QTimer.singleShot(100, answer)

    settings = Settings()
    settings.data.update(engine="api", skip_setup=True)
    settings.data.pop("quick_shortcut", None)
    win = MainWindow(settings, SecretStore())
    win.show()
    # primo avvio: prima il giro guidato; la domanda arriva appena lo chiudi
    end = time.monotonic() + 5
    while win.tour is None and time.monotonic() < end:
        pump(100)
    assert win.tour is not None and win.tour.mode == "tour"
    pump(2500)  # la domanda arriverebbe a 2,5 s dall'avvio
    assert QApplication.activeModalWidget() is None, "nessuna domanda sopra il giro guidato"
    win.tour.bubble.skip.click()
    QTimer.singleShot(200, answer)
    end = time.monotonic() + 10
    while not started and time.monotonic() < end:
        pump(100)
    assert started and settings.get("quick_shortcut") is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    os._exit(0)
