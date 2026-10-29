# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Incolla nella chat integrata senza appunti né focus (python tests/test_paste.py).

Usa il browser integrato vero (QtWebEngine) con pagine finte: un editor tipo ProseMirror
(ChatGPT, Claude) che gestisce l'evento «paste», e una textarea con caricamento da file.
"""
import faulthandler
import json
import signal
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
faulthandler.register(signal.SIGUSR1)
from helpix.config import ensure_dirs  # noqa: E402
from helpix.ui.web_panel import WebPanel  # noqa: E402

ensure_dirs()
E2E = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e")


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(page, code, timeout=5):
    box = {}
    page.runJavaScript(code, 0, lambda r: box.setdefault("r", r))
    end = time.monotonic() + timeout
    while "r" not in box and time.monotonic() < end:
        pump(30)
    return box.get("r")


def load(panel, html_file, url):
    view, page = panel.view, panel.page
    done = {}
    view.loadFinished.connect(lambda ok: done.setdefault("ok", ok))
    page.setHtml(open(os.path.join(E2E, html_file), encoding="utf-8").read(), QUrl(url))
    end = time.monotonic() + 15
    while "ok" not in done and time.monotonic() < end:
        pump(50)
    pump(200)
    panel._loading[panel.site] = False
    return page


def shot():
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#3478f6"))
    path = os.path.join(_tmp, "shot.png")
    img.save(path)
    return path


def wait_js(page, code, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if js(page, code):
            return True
        pump(100)
    return False


_panel = {}


def panel_for(site):
    """Un solo pannello: due profili con lo stesso nome nello stesso processo non funzionano."""
    if "p" not in _panel:
        _panel["p"] = WebPanel(site)
        _panel["p"].resize(900, 700)
        _panel["p"].show()
    panel = _panel["p"]
    panel.set_site(site)
    return panel


def test_editor_receives_image_and_text():
    panel = panel_for("claude")
    page = load(panel, "fake_chat.html", "https://claude.ai/new")
    panel.paste_image(shot())
    assert wait_js(page, "window.pastedFiles && window.pastedFiles.length === 1"), "immagine non incollata"
    f = js(page, "JSON.stringify(window.pastedFiles[0])")
    assert json.loads(f)["type"] == "image/png"
    panel.paste_text("Output di prova")
    assert wait_js(page, "document.getElementById('prompt-textarea').textContent.includes('Output di prova')")


def test_textarea_with_file_input():
    panel = panel_for("deepseek")
    page = load(panel, "fake_textarea.html", "https://chat.deepseek.com/")
    panel.paste_image(shot())
    assert wait_js(page, "window.uploaded && window.uploaded.length === 1"), "immagine non caricata"
    panel.paste_text("ciao dal terminale")
    assert wait_js(page, "document.getElementById('chat-input').value.includes('ciao dal terminale')")


def test_answer_text_is_clean():
    """Dalla risposta si prende solo il testo del messaggio (come in claude.ai: etichetta per i lettori
    di schermo, barra con pulsanti, scorciatoie e orario «just now»)."""
    panel = panel_for("claude")
    page = load(panel, "fake_chat.html", "https://claude.ai/chat/x")
    js(page, r"""
      const m = document.createElement('div'); m.setAttribute('data-is-streaming', 'false');
      m.innerHTML = '<span class="sr-only" style="position:absolute;width:1px;height:1px;overflow:hidden">' +
        'Claude responded: Ciao Crash, il messaggio è arrivato.</span>' +
        '<div class="font-claude-response"><div class="standard-markdown"><p>Ciao Crash, il messaggio è arrivato.</p>' +
        '<p>Prova:</p><pre><code>nmcli device status</code></pre><ul><li>uno</li><li>due</li></ul></div></div>' +
        '<div role="group" style="opacity:0"><button>Copia</button><span>⌘</span><span>CTRL</span>' +
        '<span>A</span><span>just now</span></div>';
      document.getElementById('thread').appendChild(m); true;""")
    box = {}
    panel.last_answer(lambda d: box.setdefault("d", d))
    assert wait_js(page, "true") and until_box(box)
    text = box["d"]["text"]
    assert text.startswith("Ciao Crash, il messaggio è arrivato."), text
    assert text.count("il messaggio è arrivato") == 1, text
    for junk in ("Claude responded", "just now", "CTRL", "⌘", "Copia"):
        assert junk not in text, (junk, text)
    assert "```\nnmcli device status\n```" in text and "- uno" in text, text


def test_privacy_shield_filters_user_paste():
    """Scudo acceso: Ctrl+V e Incolla dal menu nella chat integrata incollano il testo già oscurato."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWebEngineCore import QWebEnginePage
    from helpix import privacy
    panel = panel_for("claude")
    page = load(panel, "fake_chat.html", "https://claude.ai/new")
    field = "document.getElementById('prompt-textarea').textContent"
    secret = "DB_PASSWORD=Sup3rS3gret0 server 93.184.216.34"
    QGuiApplication.clipboard().setText(secret)
    privacy.activate(privacy.Redactor(hostname="", username=""))
    try:
        js(page, "document.getElementById('prompt-textarea').focus(); true")
        panel.view.setFocus()
        pump(200)
        target = panel.view.focusProxy() or panel.view
        QTest.keyClick(target, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert wait_js(page, field + ".includes('[SEGRETO]')"), js(page, field)
        text = js(page, field)
        assert "Sup3rS3gret0" not in text and "93.184.216.34" not in text and "[IP-1]" in text, text
        assert QGuiApplication.clipboard().text() == secret, "gli appunti dell'utente restano com'erano"

        js(page, "document.getElementById('prompt-textarea').textContent = ''; true")
        page.triggerAction(QWebEnginePage.WebAction.Paste)  # Incolla dal menu
        assert wait_js(page, field + ".includes('[SEGRETO]')"), js(page, field)
        assert "Sup3rS3gret0" not in js(page, field)
    finally:
        privacy.deactivate()
    # scudo spento: l'incolla resta quello normale
    js(page, "document.getElementById('prompt-textarea').textContent = ''; true")
    assert not panel._filtered_paste(panel.view, page)


def until_box(box, timeout=5):
    end = time.monotonic() + timeout
    while "d" not in box and time.monotonic() < end:
        pump(50)
    return "d" in box


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    os._exit(0)  # QtWebEngine a volte non chiude il processo da solo
