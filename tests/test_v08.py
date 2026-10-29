# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test v0.8: la finestra principale risponde all'estensione del browser (python tests/test_v08.py).

Un host di native messaging vero (in un thread) fa la parte del browser: invia le richieste
che l'estensione manda quando premi «Esegui con Helpix» e legge le risposte dell'app.
"""
import os
import sys
import tempfile
import threading
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

try:
    import PySide6.QtWebEngineWidgets  # noqa: F401  (va importato prima della QApplication)
except ImportError:
    pass
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpix import bridge_host, native_install  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402

app = QApplication.instance() or QApplication([])
ensure_dirs()


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeBrowser:
    """Lato browser: scrive come l'estensione e raccoglie ciò che arriva (pezzi ricomposti)."""

    def __init__(self):
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        self.to_host = os.fdopen(w1, "wb", buffering=0)
        self.from_host = os.fdopen(r2, "rb", buffering=0)
        self.host = bridge_host.Host(os.fdopen(r1, "rb", buffering=0), os.fdopen(w2, "wb", buffering=0), launch_cmd="")
        self.out = []
        threading.Thread(target=self.host.run, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            m = bridge_host.read_message(self.from_host)
            if m is None:
                return
            self.out.append(m)

    def send(self, **m):
        self.to_host.write(bridge_host.encode_message(m))

    def wait(self, pred, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = [m for m in self.out if pred(m)]
            if found:
                return found[-1]
            pump(50)
        raise AssertionError("risposta non arrivata")


def test_main_window_and_extension():
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="web", web_site="gemini", external_sites=["gemini"], skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    assert win.bridge_ok and win.web.bridge is win.bridge
    browser = FakeBrowser()
    browser.send(type="hello", browser="Firefox", version="0.8.0", tabs={"gemini": 11})
    browser.wait(lambda m: m.get("type") == "hello_ack")
    assert win.bridge.browsers() == ["Firefox"] and win.bridge.has_site("gemini")
    ext = win.web._tabs["gemini"][0]
    pump(100)
    assert ext.connected and not ext.link_box.isVisibleTo(ext), "la pagina deve sapere che il browser è collegato"

    # comando normale: eseguito, output nella risposta e nel task
    browser.send(type="run", id="a", cmd="echo ciao-dal-browser", site="gemini", tab=11)
    browser.wait(lambda m: m.get("type") == "run_status" and m.get("id") == "a" and m["state"] == "running")
    done = browser.wait(lambda m: m.get("type") == "run_status" and m.get("id") == "a" and m["state"] == "done")
    assert done["rc"] == 0 and "ciao-dal-browser" in done["output"] and done["auto"] is True and done["tab"] == 11
    out = [m for m in win.session.messages if m.kind == "output"][-1]
    assert out.meta["site"] == "gemini" and out.meta["source"] == "ext"

    # comando rischioso: prima la conferma, poi l'esecuzione
    target = os.path.join(_tmp, "da-cancellare")
    os.makedirs(os.path.join(target, "x"))
    browser.send(type="run", id="b", cmd=f"rm -rf {target}", site="gemini", tab=11)
    conf = browser.wait(lambda m: m.get("id") == "b" and m.get("state") == "confirm")
    assert conf["warnings"] and os.path.isdir(target)
    browser.send(type="run", id="b", cmd=f"rm -rf {target}", site="gemini", tab=11, confirmed=True)
    browser.wait(lambda m: m.get("id") == "b" and m.get("state") == "done")
    assert not os.path.exists(target)

    # testo che non è un comando, riepilogo del task
    browser.send(type="run", id="c", cmd="Questa è una frase qualsiasi", site="gemini", tab=11)
    assert browser.wait(lambda m: m.get("id") == "c" and m.get("type") == "run_status")["state"] == "rejected"
    browser.send(type="run", id="d", cmd="HELPIX-TASK\nProblema: il wifi cade\nSistema: Fedora", site="gemini", tab=11)
    assert browser.wait(lambda m: m.get("id") == "d" and m.get("type") == "run_status")["state"] == "summary"
    assert any(m.kind == "summary" for m in win.session.messages)

    # incolla da Helpix (es. screenshot dalla barra) nella scheda del browser
    img = os.path.join(_tmp, "shot.png")
    from PySide6.QtGui import QColor, QImage
    q = QImage(64, 48, QImage.Format.Format_RGB32)
    q.fill(QColor("red"))
    q.save(img)
    win.web.set_site("gemini")
    win.web.paste_image(img)
    pasted = browser.wait(lambda m: m.get("type") == "paste_image")
    assert pasted["tab"] == 11 and pasted["mime"] == "image/png"
    win.web.paste_text("testo di prova")
    assert browser.wait(lambda m: m.get("type") == "paste_text")["text"] == "testo di prova"

    # passaggio del task verso il browser: una chat nuova aperta dall'estensione
    win.web.paste_package("TASK", [img])
    pkg = browser.wait(lambda m: m.get("type") == "open_paste")
    assert pkg["site"] == "gemini" and pkg["text"] == "TASK" and len(pkg["images"]) == 1

    browser.to_host.close()
    win.close()


def test_native_install_paths():
    home = os.path.join(_tmp, "home")
    os.makedirs(os.path.join(home, ".config", "google-chrome"))
    os.makedirs(os.path.join(home, ".mozilla"))
    from pathlib import Path
    import importlib
    old = os.environ.get("HOME")
    os.environ["HOME"] = home
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    os.environ["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
    try:
        ni = importlib.reload(native_install)
        names = ni.install()
        assert names == ["Google Chrome", "Firefox"], names
        import json
        chrome = json.loads(Path(home, ".config/google-chrome/NativeMessagingHosts/com.helpix.bridge.json").read_text())
        assert chrome["allowed_origins"] == [f"chrome-extension://{ni.CHROME_EXTENSION_ID}/"]
        ff = json.loads(Path(home, ".mozilla/native-messaging-hosts/com.helpix.bridge.json").read_text())
        assert ff["allowed_extensions"] == [ni.FIREFOX_EXTENSION_ID] and os.access(ff["path"], os.X_OK)
        assert ni.installed()
        assert set(ni.uninstall()) == {"Google Chrome", "Firefox"} and not ni.installed()
    finally:
        os.environ["HOME"] = old or ""
        importlib.reload(native_install)


def test_extension_id_matches_key():
    import base64
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    der = base64.b64decode((root / "extension" / "chromium-public-key.txt").read_text().strip())
    ext_id = "".join("abcdefghijklmnop"[int(c, 16)] for c in hashlib.sha256(der).hexdigest()[:32])
    assert ext_id == native_install.CHROME_EXTENSION_ID


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
