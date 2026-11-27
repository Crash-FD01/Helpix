# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progetti (beta) nella chat web: aggiornamento HELPIX-PROJECT letto dalla risposta, blocco e HELPIX-NOTA copiati,
«salva nel progetto…» scritto nella chat (python tests/test_projects_web.py). Browser integrato vero con la pagina di chat finta."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import project as pj  # noqa: E402
from helpix.config import ensure_dirs  # noqa: E402
from helpix.i18n import set_language  # noqa: E402
from helpix.ui.web_panel import WebPanel  # noqa: E402

ensure_dirs()
set_language("it")
E2E = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e")

# risposta finta all'aggiornamento del progetto: arriva dopo un po', come una chat vera
_ANSWER_JS = r"""
document.getElementById('send').addEventListener('click', () => {
  const text = window.sent[window.sent.length - 1] || '';
  if (!text.includes('HELPIX-PROJECT')) return;
  setTimeout(() => {
    const pre = document.createElement('pre'); const code = document.createElement('code');
    code.textContent = 'HELPIX-PROJECT\nNOTA: Driver stampante\nInstallato il driver giusto.\nMODIFICHE:\n' +
                       '+ Decisioni in vigore: Driver HP ufficiale\n= Stato: Stampa di prova riuscita.';
    pre.appendChild(code); document.getElementById('thread').appendChild(pre);
  }, 700);
});
'true';
"""


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


def test_aggiornamento_letto_dalla_risposta():
    panel = WebPanel("claude")
    panel.resize(900, 700)
    panel.show()
    page, done = panel.page, {}
    panel.view.loadFinished.connect(lambda ok: done.setdefault("ok", ok))
    page.setHtml(open(os.path.join(E2E, "fake_chat.html"), encoding="utf-8").read(), QUrl("https://claude.ai/new"))
    end = time.monotonic() + 15
    while "ok" not in done and time.monotonic() < end:
        pump(50)
    pump(200)
    panel._loading[panel.site] = False
    assert js(page, _ANSWER_JS) == "true"
    got, failed, summaries = [], [], []
    panel.project_copied.connect(got.append)
    panel.project_failed.connect(failed.append)
    panel.summary_copied.connect(summaries.append)
    request = pj.update_request(pj.template("Stampante", "Stampare") + "Segreto\n")
    assert "Segreto" not in request
    panel.request_summary(request, timeout=40, marker=pj.PROJECT_MARKER)
    end = time.monotonic() + 45
    while not got and not failed and time.monotonic() < end:
        pump(200)
    assert got and not failed and not summaries, (got, failed, summaries)
    up = got[0]
    assert up.title == "Driver stampante" and ("+", "Decisioni in vigore", "Driver HP ufficiale") in up.ops
    sent = js(page, "window.sent[window.sent.length - 1]")
    assert "HELPIX-PROJECT" in sent and "Segreto" not in sent

    # blocco copiato a mano e richiesta di una nota copiata
    notes = []
    panel.note_requested.connect(notes.append)
    got.clear()
    for text in ("HELPIX-PROJECT\nNOTA: A mano\nTesto.\nMODIFICHE:\n= Stato: fatto", "HELPIX-NOTA: Driver stampante"):
        panel._last_clip = None
        QGuiApplication.clipboard().setText(text)
        panel._process_clipboard()
    assert got and got[0].title == "A mano" and notes == ["Driver stampante"]
    _salva_nel_progetto_trattenuto(panel, page)
    panel.shutdown()


_ENTER_SENDS_JS = r"""
document.getElementById('prompt-textarea').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('send').click(); }
});
'true';
"""


def _type_and_enter(panel, page, text):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    js(page, "(() => { const b = document.getElementById('prompt-textarea'); b.textContent = %s; b.focus(); "
             "return 'ok'; })()"
       % json.dumps(text))
    panel.view.setFocus()
    pump(100)
    QTest.keyClick(panel.view.focusProxy() or panel.view, Qt.Key.Key_Return)  # evento vero, come la tastiera
    pump(600)


def _salva_nel_progetto_trattenuto(panel, page):
    """«salva nel progetto…» inviato nella chat: trattenuto e passato a Helpix (stessa pagina del test sopra: il motore
    web non si riavvia nello stesso processo). Attivato a pagina già aperta: lo script entra anche lì."""
    panel.set_chat_commands(True)
    pump(300)
    assert js(page, _ENTER_SENDS_JS) == "true"
    held = []
    panel.chat_command.connect(held.append)
    # un messaggio qualsiasi parte subito, senza passare da Helpix
    base = js(page, "window.sent.length")
    _type_and_enter(panel, page, "ciao, come stai?")
    assert js(page, "window.sent.length") == base + 1 and not held
    # «salva … nel progetto …»: trattenuto e passato a Helpix, non parte
    cmd = "ok abbiamo finito, salva quello che abbiamo fatto nel progetto test"
    _type_and_enter(panel, page, cmd)
    assert held == [cmd], held
    assert js(page, "window.sent.length") == base + 1
    # non era per Helpix: release_send lo manda (l'invio di Helpix non viene trattenuto di nuovo)
    panel.release_send()
    pump(500)
    assert js(page, "window.sent[window.sent.length - 1]") == cmd and len(held) == 1
    # era per Helpix: la casella si svuota prima di incollare la richiesta
    _type_and_enter(panel, page, "salva nel progetto test")
    assert len(held) == 2
    cleared = []
    panel.clear_composer(lambda: cleared.append(js(page, "document.getElementById('prompt-textarea').textContent")))
    end = time.monotonic() + 5
    while not cleared and time.monotonic() < end:
        pump(50)
    assert cleared == [""], cleared
    # la pagina non può fingere un comando: senza il prefisso casuale la console non conta
    js(page, "console.log('helpix-cmd-0000:\"salva nel progetto test\"'); 'ok'")
    pump(200)
    assert len(held) == 2
    # funzione spenta: anche «salva nel progetto» parte subito
    panel.set_chat_commands(False)
    pump(200)
    _type_and_enter(panel, page, "salva nel progetto test")
    assert len(held) == 2 and js(page, "window.sent[window.sent.length - 1]") == "salva nel progetto test"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
