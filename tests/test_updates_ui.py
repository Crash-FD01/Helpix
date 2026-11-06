# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Controllo degli aggiornamenti nella finestra principale, Windows e Linux (python tests/test_updates_ui.py)."""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ["HELPIX_NO_UPDATE_CHECK"] = "1"  # niente controllo automatico: le prove lo chiamano a mano

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import __version__, updates  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402
from helpix.i18n import set_language  # noqa: E402

ensure_dirs()
set_language("it")  # le prove cercano i pulsanti per nome


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def boxes():
    return [w for w in app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]


def close_boxes():
    for b in boxes():
        b.done(0)
    pump(50)


def test_update_dialogs():
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False, show_tips=False)
    win = MainWindow(settings, SecretStore())
    win.show()
    pump(300)
    newer = {"version": "99.0.0", "url": "https://github.com/Crash-FD01/Helpix/releases/tag/v99.0.0",
             "setup": "https://x/Helpix-99.0.0-Setup.exe", "sums": "https://x/SHA256SUMS"}

    # dal menu: risposte anche quando non c'è nulla da fare o GitHub non risponde
    with mock.patch.object(QMessageBox, "information") as info, mock.patch.object(QMessageBox, "warning") as warn:
        win._update_found({"version": __version__, "url": "u", "setup": None, "sums": None}, manual=True)
        win._update_found(None, manual=True)
        win._update_found({"version": __version__, "url": "u", "setup": None, "sums": None})  # automatico: zitto
        win._update_found(None)
    assert info.call_count == 1 and __version__ in info.call_args[0][2]
    assert warn.call_count == 1 and "GitHub" in warn.call_args[0][2]

    # Linux, pacchetto con apt: «Aggiorna ora» con il gestore pacchetti
    with mock.patch.object(updates, "install_kind", return_value="package"), \
            mock.patch("helpix.sysdeps.detect_manager", return_value="apt"):
        win._update_found(newer)
    pump(100)
    (box,) = boxes()
    labels = [b.text() for b in box.buttons()]
    assert "99.0.0" in box.text() and "apt" in box.informativeText(), (box.text(), box.informativeText())
    assert "Aggiorna ora" in labels and "Salta questa versione" in labels, labels
    close_boxes()

    # dai sorgenti: niente pulsante, il comando da usare
    with mock.patch.object(updates, "install_kind", return_value="source"):
        win._update_found(newer)
    pump(100)
    (box,) = boxes()
    assert "git pull && ./install.sh" in box.informativeText()
    assert "Aggiorna ora" not in [b.text() for b in box.buttons()]
    skip = next(b for b in box.buttons() if b.text() == "Salta questa versione")
    skip.click()
    pump(100)
    assert settings.get("skip_version") == "99.0.0"
    win._update_found(newer)  # versione saltata: il controllo automatico non la ripropone
    pump(100)
    assert not boxes()

    # Windows: «Aggiorna ora» scarica l'installer
    with mock.patch.object(updates, "install_kind", return_value="windows"):
        win._update_found(newer, manual=True)  # dal menu si propone anche una versione saltata
    pump(100)
    (box,) = boxes()
    assert "Aggiorna ora" in [b.text() for b in box.buttons()] and "installazione" in box.informativeText()
    close_boxes()

    # finestra nascosta (Helpix nell'area di notifica): l'avviso aspetta che la finestra torni visibile
    settings.set("skip_version", None)
    win.hide()
    with mock.patch.object(QTimer, "singleShot") as later:
        win._update_found(newer)
    assert later.called and not boxes()
    win.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
