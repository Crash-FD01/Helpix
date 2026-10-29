# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshot della documentazione e del sito, presi dall'interfaccia vera di Helpix.

    python tools/screenshots.py                 # tutti, in docs/screenshots/
    python tools/screenshots.py main light      # uno solo (scena, tema)

Gira senza schermo (piattaforma «offscreen») e con impostazioni temporanee: non tocca quelle dell'utente. La chat
mostrata è una pagina di esempio servita in locale, con una conversazione realistica.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")

SCENES = [("main", "light"), ("main", "dark"), ("quick", "light"), ("start", "light")]

CHATS = {
    "light": ("Il Wi-Fi non si connette più da stamattina.",
              "Dallo screenshot la scheda Wi-Fi risulta disconnessa. Proviamo a riavviare il servizio di rete:",
              "sudo systemctl restart NetworkManager",
              "Poi riprova a collegarti: se non va, incollami l'output e guardiamo i log."),
    "dark": ("La stampante non stampa più, i documenti restano tutti in coda.",
             "Succede quando il servizio di stampa si blocca. Riavviamolo, la coda riparte da sola:",
             "sudo systemctl restart cups",
             "Poi manda di nuovo il documento: dovrebbe partire subito."),
}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Chat</title><style>
:root {{ color-scheme: light dark; --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --bubble:#f1f3f5; --code:#f6f8fa;
        --line:#e3e6ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1b1c1f; --fg:#e8eaed; --muted:#a0a6ae; --bubble:#2a2c31;
        --code:#141518; --line:#2f3238; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font: 15.5px/1.6 "Inter", system-ui, sans-serif; }}
main {{ max-width: 640px; margin: 0 auto; padding: 36px 20px 140px; }}
.user {{ display:flex; justify-content:flex-end; margin: 6px 0 22px; }}
.user p {{ background:var(--bubble); padding: 10px 16px; border-radius: 18px; margin:0; max-width: 80%; }}
pre {{ background:var(--code); border:1px solid var(--line); border-radius:10px; padding:12px 14px;
      font: 13.5px/1.5 "JetBrains Mono", ui-monospace, monospace; overflow:auto; }}
.box {{ position:fixed; left:50%; transform:translateX(-50%); bottom:26px; width:min(640px, 92vw);
       border:1px solid var(--line); border-radius:24px; padding:14px 18px; color:var(--muted); background:var(--bg); }}
</style></head><body><main>
<div class="user"><p>{q}</p></div>
<p>{a1}</p>
<pre><code class="language-{lang}">{cmd}</code></pre>
<p>{a2}</p>
</main><div class="box" id="prompt-textarea" contenteditable="true">Scrivi un messaggio…</div></body></html>"""


def _serve(theme: str) -> str:
    q, a1, cmd, a2 = CHATS[theme]
    page = PAGE.format(q=q, a1=a1, cmd=cmd, a2=a2, lang="bash").encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *_a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}/"


def shoot(scene: str, theme: str) -> str:
    tmp = tempfile.mkdtemp()
    os.environ.update(XDG_CONFIG_HOME=os.path.join(tmp, "c"), XDG_DATA_HOME=os.path.join(tmp, "d"),
                      XDG_RUNTIME_DIR=os.path.join(tmp, "r"), QT_QPA_PLATFORM="offscreen",
                      QTWEBENGINE_DISABLE_SANDBOX="1", QT_SCALE_FACTOR="1")
    os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
    sys.path.insert(0, ROOT)
    from helpix.app import _web_color_scheme
    _web_color_scheme(theme)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] += " --disable-gpu"
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    app = QApplication(["Helpix"])
    from helpix import theme as th
    from helpix.config import SecretStore, Settings, ensure_dirs
    ensure_dirs()
    th.setup(app, theme)
    app.setWindowIcon(th.app_icon())
    settings = Settings()
    settings.data.update(engine="web", web_site="chatgpt", external_sites=[], skip_setup=True, quick_shortcut=False,
                         show_tips=False, theme=theme, language="it")
    os.makedirs(OUT, exist_ok=True)
    name = {"main": f"principale-{'chiaro' if theme == 'light' else 'scuro'}", "quick": "finestra-rapida",
            "start": "schermata-iniziale"}[scene]
    dest = os.path.join(OUT, name + ".png")

    if scene == "start":
        from helpix.ui.start_dialog import StartDialog
        dlg = StartDialog(settings, SecretStore())
        dlg.show()
        pump(1500)
        dlg.grab().save(dest)
        return dest

    from helpix.ui import web_panel
    url = _serve(theme)
    for key in web_panel.WEB_SITES:
        web_panel.WEB_SITES[key]["url"] = url
    from helpix.ui.main_window import MainWindow
    win = MainWindow(settings, SecretStore())
    win.resize(1180, 760)
    win.show()
    for _ in range(100):
        pump(100)
        if not win.web._loading.get("chatgpt", True):
            break
    pump(1500)
    if scene == "main":
        win.command_bar.show_command(CHATS[theme][2])
        win.command_bar.parentWidget().show()
        pump(800)
        win.grab().save(dest)
        return dest

    from helpix.ui.quick_window import QuickWindow
    q = QuickWindow()
    q.target.setText("→ ChatGPT")
    q._history = [("Come vedo quanto spazio libero ho sul disco?", "")]
    q._answer = ("Apri un terminale ed esegui `df -h`: la colonna **Disp.** mostra lo spazio libero di ogni disco. "
                 "In alternativa, l'app *Analizzatore di utilizzo disco* lo mostra in grafico.")
    q.answers.show()
    q._render()
    q.show()
    q.adjustSize()
    pump(1000)
    q.grab().save(dest)
    return dest


def main() -> int:
    if len(sys.argv) == 3:
        print(shoot(sys.argv[1], sys.argv[2]))
        os._exit(0)
    ok = True
    for scene, theme in SCENES:  # ogni scena in un processo nuovo: il tema del motore web si fissa all'avvio
        r = subprocess.run([sys.executable, os.path.abspath(__file__), scene, theme], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        path = (r.stdout.strip().splitlines() or [""])[-1]
        print(("✓ " if r.returncode == 0 and path else "✗ ") + (path or scene + " " + theme))
        ok &= r.returncode == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
