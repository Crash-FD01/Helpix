# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra rapida e istanza unica (python tests/test_quick.py).

La finestra rapida (qui nello stesso processo) parla con la finestra principale tramite il
socket dell'istanza; la chat è una pagina finta servita in locale.
"""
import http.server
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
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-proxy-server")

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e", "fake_chat.html"), "rb").read()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *_a):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

from helpix import instance  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402
from helpix.ui import web_panel  # noqa: E402

ensure_dirs()
for key in web_panel.WEB_SITES:
    web_panel.WEB_SITES[key]["url"] = f"http://127.0.0.1:{httpd.server_address[1]}/{key}/"


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(page, code):
    box = {}
    page.runJavaScript(code, 0, lambda r: box.setdefault("r", r))
    end = time.monotonic() + 5
    while "r" not in box and time.monotonic() < end:
        pump(30)
    return box.get("r")


def until(fn, timeout=15, what=""):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        pump(100)
    raise AssertionError("timeout: " + what)


def test_quick_window():
    from helpix.ui.main_window import MainWindow
    from helpix.ui.quick_window import QuickWindow
    settings = Settings()
    settings.data.update(engine="web", web_site="chatgpt", external_sites=[], skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    win.show()
    gpt = win.web._tabs["chatgpt"][1]
    until(lambda: not win.web._loading["chatgpt"], what="caricamento")
    assert instance.is_running(), "la finestra principale deve ascoltare sul socket dell'istanza"
    assert instance.send_once({"type": "show"}), "un secondo avvio porta avanti la finestra esistente"

    q = QuickWindow()
    q.place()
    q.show()
    until(lambda: q.target.text() == "→ ChatGPT", what="collegamento con Helpix")
    area = QGuiApplication.primaryScreen().availableGeometry()
    from helpix.ui.quick_window import PANEL_GUESS  # offscreen: nessun pannello indicato, resta lo spazio
    assert q.geometry().right() > area.right() - 60 and q.geometry().bottom() > area.bottom() - 60 - PANEL_GUESS, \
        "la finestra rapida sta in basso a destra"

    # chat web: modello ed effort si scelgono nella pagina del servizio
    assert q.choice_note.text().startswith("Modello ed effort") and q.model.isHidden()

    # ancoraggio: di default bloccata; sbloccata e riancorata ricorda la posizione
    assert q.anchored
    q.toggle_anchor()
    assert not q.anchored
    q.move(q.x() - 200, q.y() - 100)
    q.toggle_anchor()
    from helpix.ui.quick_window import _load_pos
    pos = _load_pos()
    assert pos["locked"] and pos["dx"] >= 150 and pos["dy"] >= 50, pos

    # nuova richiesta mentre aspetta: la finestra non resta bloccata
    q.input.setPlainText("domanda annullata")
    q.send()
    assert q._sending and not q.btn_send.isEnabled()
    q.clear_conversation()
    assert not q._sending and q.btn_send.isEnabled()
    pump(300)
    assert win._quick_watch is None, "Helpix smette di aspettare la risposta annullata"
    pump(3000)
    n_sent = js(gpt, "window.sent.length")  # annullata subito: di norma non parte nemmeno

    # invio: il testo va nella chat e il messaggio parte
    q.input.setPlainText("perché il wifi è lento?")
    q.send()
    until(lambda: js(gpt, "window.sent.length") == n_sent + 1, what="messaggio inviato")
    assert "perché il wifi è lento?" in js(gpt, f"window.sent[{n_sent}]")
    # la risposta arriva nella finestra rapida, che resta aperta in modalità ridotta
    until(lambda: "NetworkManager" in q.answers.toPlainText(), timeout=20, what="risposta nella finestra rapida")
    until(lambda: q.btn_send.isEnabled(), timeout=15, what="risposta completa")
    assert q.isVisible() and q.answers.isVisible()
    assert "perché il wifi è lento?" in q.answers.toPlainText()

    # una sola finestra rapida: la scorciatoia la nasconde e la rimostra
    from helpix.ui.quick_window import _QuickServer, quick_socket_path
    server = _QuickServer(q)
    assert server.listen(quick_socket_path())
    assert instance.send_once({"type": "toggle"}, quick_socket_path())
    until(lambda: not q.isVisible(), what="nascosta con la scorciatoia")
    pump(400)  # due pressioni a meno di 0,35 s contano come una sola
    assert instance.send_once({"type": "toggle"}, quick_socket_path())
    until(lambda: q.isVisible(), what="mostrata di nuovo, con la conversazione")
    assert "NetworkManager" in q.answers.toPlainText()
    server.close()
    win.close()


def test_effort_payload():
    from helpix.providers import build_request
    _url, body = build_request("anthropic", "claude-opus-5-5", "sys", [], effort="high")
    assert body["output_config"] == {"effort": "high"} and body["max_tokens"] == 32000
    _url, body = build_request("anthropic", "claude-opus-5-5", "sys", [], effort=None)
    assert "output_config" not in body
    _url, body = build_request("openai", "gpt-5", "sys", [], effort="low")
    assert body["reasoning_effort"] == "low"
    _url, body = build_request("deepseek", "deepseek-chat", "sys", [], effort="high")
    assert "reasoning_effort" not in body, "DeepSeek non ha effort: non va inviato"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    os._exit(0)
