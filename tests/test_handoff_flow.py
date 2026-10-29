# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flusso completo del passaggio del task nel browser integrato (python tests/test_handoff_flow.py).

Pagine di chat finte servite in locale al posto di ChatGPT e Claude: screenshot, comando,
riepilogo, poi «Continua con un'altra IA» e incolla automatico nella nuova chat.
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
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
E2E = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e")
PAGE = open(os.path.join(E2E, "fake_chat.html"), "rb").read()


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
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"

from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402
from helpix.ui import web_panel  # noqa: E402

ensure_dirs()
for key in web_panel.WEB_SITES:
    web_panel.WEB_SITES[key]["url"] = f"{BASE}/{key}/"


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


def composer(page):
    return js(page, "document.getElementById('prompt-textarea').textContent") or ""


def test_full_handoff():
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="web", web_site="chatgpt", external_sites=[], skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    win.resize(1100, 760)
    win.show()
    gpt = win.web._tabs["chatgpt"][1]
    until(lambda: not win.web._loading["chatgpt"], what="caricamento chatgpt")

    # 1) screenshot nella chat
    img = QImage(500, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#e33"))
    shot = os.path.join(_tmp, "problema.png")
    img.save(shot)
    win._add_attachment(shot)
    until(lambda: js(gpt, "window.pastedFiles.length") == 1, what="screenshot in chatgpt")

    # 2) comando copiato dalla chat ed eseguito: output incollato
    win.run_command("echo uscita-del-comando", "web")
    until(lambda: "uscita-del-comando" in composer(gpt), what="output in chatgpt")

    # 3) riepilogo: richiesta incollata, l'utente copia la risposta
    js(gpt, "document.getElementById('prompt-textarea').textContent = ''")
    win._choose_site("claude")
    assert win.transfer_bar.isVisible(), "deve comparire «Hai un task in corso su ChatGPT»"
    cl = win.web._tabs["claude"][1]
    until(lambda: not win.web._loading["claude"], what="caricamento claude")
    js(cl, "document.getElementById('prompt-textarea').textContent = 'VECCHIA CONVERSAZIONE'")
    win.open_handoff("claude")
    dlg = win.handoff
    dlg._ask()
    assert win.web.site == "chatgpt", "per chiedere il riepilogo si torna su ChatGPT"
    # Helpix incolla, invia e legge da solo il riepilogo quando l'IA ha finito di scrivere
    until(lambda: js(gpt, "window.sent.length") == 1, what="richiesta inviata")
    assert "HELPIX-TASK" in js(gpt, "window.sent[0]")
    until(lambda: win.web.site == "claude", timeout=30, what="riepilogo letto e ritorno sulla nuova IA")
    text = dlg.preview.toPlainText()
    assert "la stampante non stampa" in text and "driver sbagliato" in text, text
    assert "uscita-del-comando" in text
    assert dlg.problem.text() == "la stampante non stampa"
    assert dlg.cb_img.isChecked() and dlg._images, "lo screenshot deve far parte del pacchetto"

    # 4) apri Claude e incolla
    dlg._go()
    until(lambda: "la stampante non stampa" in composer(cl), timeout=30, what="testo del task in claude")
    assert "VECCHIA" not in composer(cl), "il task va in una chat nuova, non in quella già aperta"
    until(lambda: js(cl, "window.pastedFiles.length") == 1, what="screenshot in claude")
    win.close()


def test_export_empty_task_asks_summary():
    """Esporta con il task solo nella chat: Helpix chiede il riepilogo e poi salva il file."""
    from PySide6.QtWidgets import QFileDialog
    from helpix.task import import_task
    from helpix.ui import main_window as mw
    from helpix.ui.main_window import MainWindow
    dest = os.path.join(_tmp, "esportato.helpix")
    orig = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, ""))
    try:
        settings = Settings()
        settings.data.update(engine="web", web_site="chatgpt", external_sites=[], skip_setup=True, quick_shortcut=False)
        win = MainWindow(settings, SecretStore())
        win.show()
        until(lambda: not win.web._loading["chatgpt"], what="caricamento chatgpt")
        assert not win._task_has_content()
        win.export_current()
        pump(300)
        win.export_current()  # secondo clic mentre aspetta: non deve rimandare la richiesta
        gpt = win.web._tabs["chatgpt"][1]
        until(lambda: os.path.exists(dest), timeout=40, what="file esportato dopo il riepilogo")
        assert js(gpt, "window.sent.length") == 1, "la richiesta di riepilogo va inviata una volta sola"
        task = import_task(dest)
        assert any(m.kind == "summary" and "stampante" in m.text for m in task.messages)
        win.close()
    finally:
        QFileDialog.getSaveFileName = orig
    assert mw  # modulo usato per il patch del dialogo


if __name__ == "__main__":
    # ogni test in un processo a parte: QtWebEngine non permette due profili con lo stesso nome
    import subprocess
    names = [n for n in list(globals()) if n.startswith("test_")]
    if len(sys.argv) > 1:
        globals()[sys.argv[1]]()
        print("ok", sys.argv[1], flush=True)
        os._exit(0)
    failed = False
    for name in names:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), name], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240)
        ok = r.returncode == 0 and f"ok {name}" in r.stdout
        print(("ok " if ok else "FALLITO ") + name, flush=True)
        if not ok:
            failed = True
            print("\n".join((r.stdout + r.stderr).splitlines()[-25:]), flush=True)
    sys.stdout.flush()
    os._exit(1 if failed else 0)
