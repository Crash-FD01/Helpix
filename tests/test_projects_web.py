# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progetti (beta) nella chat web: aggiornamento HELPIX-PROJECT letto dalla risposta, blocco e HELPIX-NOTA copiati
(python tests/test_projects_web.py). Browser integrato vero con la pagina di chat finta."""
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
    panel.shutdown()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
