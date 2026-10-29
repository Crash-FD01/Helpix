# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agenti nel terminale con un agente finto al posto di claude/codex (python tests/test_agents.py).

L'agente finto gira in un pseudo-terminale vero (modo raw, incolla tra parentesi, Invio) e
registra in un file quello che riceve.
"""
import json
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

# claude e codex finti nel PATH; gemini assente (deve comparire la pagina di installazione)
BIN = os.path.join(_tmp, "bin")
os.makedirs(BIN)
FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent", "fake_agent.py")
for name in ("claude", "codex"):
    os.symlink(FAKE, os.path.join(BIN, name))
os.environ["PATH"] = BIN + os.pathsep + "/usr/bin:/bin"
LOG = os.path.join(_tmp, "agent.log")
os.environ["FAKE_AGENT_LOG"] = LOG

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import agents  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402

ensure_dirs()


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def events(kind=None, name=None):
    if not os.path.exists(LOG):
        return []
    out = [json.loads(line) for line in open(LOG, encoding="utf-8") if line.strip()]
    return [e for e in out if (kind is None or e["event"] == kind)]


def until(fn, timeout=15, what=""):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        pump(100)
    raise AssertionError("timeout: " + what)


def test_agents_flow():
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="web", web_site="chatgpt", external_sites=[], skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    win.resize(1100, 760)
    win.show()

    # 1) scelgo Claude Code: parte nel terminale, nella cartella di Helpix con le istruzioni
    win._choose_agent("claude-code")
    start = until(lambda: events("start"), what="avvio dell'agente")[0]
    assert start["name"] == "claude" and start["tty"] and start["cols"] > 40 and start["rows"] > 10, start
    assert os.path.realpath(start["cwd"]) == os.path.realpath(str(agents.WORKSPACE))
    assert {"CLAUDE.md", "AGENTS.md", "GEMINI.md"} <= set(start["context"])
    assert "HELPIX-SUMMARY.md" in (agents.WORKSPACE / "CLAUDE.md").read_text(encoding="utf-8")
    assert win.engine == "agent" and win.picker.name.text() == "Claude Code"
    assert not win._sc_new.isEnabled(), "Ctrl+N deve arrivare al terminale"

    # 2) tasti scritti nel terminale arrivano all'agente
    win.agent.term.pty.write("ciao agente\r")
    until(lambda: any(e["text"] == "ciao agente" for e in events("line")), what="riga digitata")

    # 2b) finestra rapida con l'agente: la domanda parte con Invio e il testo nuovo del terminale torna indietro
    replies = []
    win.instance.reply = lambda sock, msg: replies.append(msg)
    win._quick_send("domanda dalla finestra rapida", object())
    until(lambda: any(e["text"] == "domanda dalla finestra rapida" for e in events("line")), what="domanda rapida")
    done = until(lambda: [m for m in replies if m.get("type") == "answer" and m.get("done")], timeout=20,
                 what="risposta completa dal terminale")[0]
    assert "domanda dalla finestra rapida" in done["text"]

    # 2c) modello ed effort: Claude Code li cambia subito con /model e /effort
    win.set_choice(model="sonnet")
    until(lambda: any(e["text"] == "/model sonnet" for e in events("line")), what="/model inviato")
    win.set_choice(effort="high")
    until(lambda: any(e["text"] == "/effort high" for e in events("line")), what="/effort inviato")
    assert "sonnet" in win.model_btn.text() and "high" in win.model_btn.text()

    # 3) screenshot: salvato nella cartella di lavoro e incollato come percorso, senza Invio
    img = QImage(300, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("#36c"))
    shot = os.path.join(_tmp, "errore.png")
    img.save(shot)
    win._add_attachment(shot)
    pasted = until(lambda: [e for e in events("data") if "screenshots/" in e["text"]], what="percorso incollato")[0]
    assert pasted["text"].startswith("\x1b[200~") and "\r" not in pasted["text"], "incolla tra parentesi, senza Invio"
    saved = [p for p in (agents.WORKSPACE / "screenshots").iterdir()]
    assert len(saved) == 1 and saved[0].stat().st_size > 0

    # 4) riepilogo: Helpix lo chiede (con Invio) e lo legge dal file scritto dall'agente
    win.open_handoff("chatgpt")
    dlg = win.handoff
    dlg._ask()
    until(lambda: any("HELPIX-SUMMARY.md" in e["text"] for e in events("line")), what="richiesta inviata")
    until(lambda: "backup notturno" in dlg.preview.toPlainText(), timeout=20, what="riepilogo letto dal file")
    assert dlg.problem.text() == "configurare il backup notturno"
    assert "Claude Code" in dlg.preview.toPlainText()
    dlg.close()

    # 5) passaggio del task a Codex: HELPIX-TASK.md, screenshot copiato, prompt iniziale,
    #    con modello ed effort scelti per Codex (passati all'avvio)
    win.settings.set("agent_model", {"claude-code": "sonnet", "codex": "gpt-5.4-mini"})
    win.settings.set("agent_effort", {"claude-code": "high", "codex": "low"})
    n_before = len(events("start"))
    win._handoff_go("codex", "TESTO DEL TASK DA CONTINUARE", [shot])
    start2 = until(lambda: events("start")[n_before:], what="avvio di codex")[0]
    assert start2["name"] == "codex" and "HELPIX-TASK.md" in start2["argv"][-1], start2
    assert start2["argv"][:4] == ["--model", "gpt-5.4-mini", "-c", 'model_reasoning_effort="low"'], start2
    task = (agents.WORKSPACE / "HELPIX-TASK.md").read_text(encoding="utf-8")
    assert "TESTO DEL TASK DA CONTINUARE" in task and "screenshots/errore" in task
    assert win.picker.name.text() == "Codex"

    # 6) Gemini CLI non installato: pagina con il comando ufficiale
    win._choose_agent("gemini-cli")
    assert win.agent.stack.currentWidget() is win.agent.install_page
    assert "@google/gemini-cli" in win.agent.install_page.cmd.text()

    # 7) di nuovo nel motore web: le scorciatoie tornano attive
    win._choose_site("chatgpt")
    assert win.engine == "web" and win._sc_new.isEnabled()
    win.close()
    assert not win.agent.term.pty.running


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    os._exit(0)
