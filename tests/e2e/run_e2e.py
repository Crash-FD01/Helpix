# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test end-to-end dell'estensione in Chromium vero (python tests/e2e/run_e2e.py).

Carica l'estensione, registra l'host di native messaging nel profilo di prova, avvia
un'app finta (BridgeServer vero) e usa pagine di chat finte servite al posto dei siti reali.
"""
import http.server
import json
import os
import ssl
import threading
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EXT = ROOT / "helpix" / "data" / "extension" / "chromium"
EXT_ID = "kcnapjkchmgjacppmmajcddjoemeahdj"


def wait(cond, timeout=15, what="condizione"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError(f"timeout: {what}")


def serve_fake_sites(tmp: Path) -> int:
    """Siti finti in HTTPS locale: anche le schede aperte dall'estensione arrivano qui."""
    pages = {"chatgpt.com": (HERE / "fake_chat.html").read_bytes(), "claude.ai": (HERE / "fake_textarea.html").read_bytes()}
    cert, key = tmp / "cert.pem", tmp / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=test",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = pages.get(self.headers.get("Host", "").split(":")[0], b"not found")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


SHOTS = os.environ.get("HELPIX_E2E_SHOTS")


def shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="helpix-e2e-"))
    runtime = tmp / "run"
    runtime.mkdir(mode=0o700)
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), QT_QPA_PLATFORM="offscreen")
    log_file = tmp / "events.json"
    profile = tmp / "profile"
    (profile / "NativeMessagingHosts").mkdir(parents=True)
    launcher = tmp / "helpix-bridge"
    launcher.write_text(f"#!/bin/sh\nexport XDG_RUNTIME_DIR={runtime}\nexport HELPIX_CMD=\n"
                        f"exec {sys.executable} -I {ROOT / 'helpix' / 'bridge_host.py'} \"$@\"\n")
    launcher.chmod(0o755)
    (profile / "NativeMessagingHosts" / "com.helpix.bridge.json").write_text(json.dumps({
        "name": "com.helpix.bridge", "description": "test", "path": str(launcher), "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXT_ID}/"]}))

    app = subprocess.Popen([sys.executable, str(HERE / "fake_app.py"), str(log_file)], env=env)
    events = lambda: json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []  # noqa: E731
    wait(lambda: any(e["kind"] == "started" for e in events()), what="avvio app finta")

    port = serve_fake_sites(tmp)
    ok = []
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(profile), headless=False,
                ignore_https_errors=True,
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", "--ignore-certificate-errors", "--no-proxy-server",
                      f"--host-resolver-rules=MAP chatgpt.com 127.0.0.1:{port}, MAP claude.ai 127.0.0.1:{port}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            assert EXT_ID in sw.url, f"ID estensione inatteso: {sw.url}"
            ok.append("estensione caricata con l'ID previsto")

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://chatgpt.com/c/test")
            page.bring_to_front()
            page.wait_for_function("document.querySelectorAll('helpix-run').length >= 4", timeout=10000)
            n = page.evaluate("document.querySelectorAll('helpix-run').length")
            assert n == 4, f"pulsanti attesi 4 (bash, rischioso, riepilogo, package), trovati {n}"
            ok.append("pulsante sui blocchi shell e sul riepilogo, nessuno sul Python")
            wait(lambda: any(e["kind"] == "clients" and "Chromium" in str(e.get("browsers")) or
                             e["kind"] == "clients" and e.get("browsers") for e in events()),
                 what="collegamento del browser all'app")
            page.wait_for_function(
                "(() => { const r = document.querySelector('helpix-pill').shadowRoot;"
                " return r.querySelector('.dot.on') !== null; })()", timeout=10000)
            ok.append("estensione ↔ host ↔ app collegati (pallino verde)")
            popup = ctx.new_page()
            popup.set_viewport_size({"width": 352, "height": 300})
            popup.goto(f"chrome-extension://{EXT_ID}/popup.html")
            popup.wait_for_function("document.getElementById('state').className.includes('ok')", timeout=8000)
            shot(popup, "ext-popup.png")
            popup.close()
            page.bring_to_front()
            ok.append("finestrella dell'estensione: «Collegato a Helpix»")

            runs = page.locator("helpix-run")
            # 1) comando normale: eseguito e output incollato nella casella
            runs.nth(0).locator("button.go").click()
            page.wait_for_function("document.getElementById('prompt-textarea').textContent.includes('hello-helpix')",
                                   timeout=10000)
            text = page.evaluate("document.getElementById('prompt-textarea').textContent")
            assert "Output di `echo hello-helpix`" in text, text
            run_ev = [e for e in events() if e["kind"] == "run"][0]
            assert run_ev["cmd"] == "echo hello-helpix" and run_ev["site"] == "chatgpt" and isinstance(run_ev["tab"], int)
            state = runs.nth(0).locator(".state").inner_text()
            assert "Fatto" in state or "Done" in state, state
            ok.append("Esegui → app → output incollato nella chat (" + state.strip() + ")")
            shot(page, "ext-run-done.png")

            # 2) comando rischioso: conferma nella pagina
            page.evaluate("document.getElementById('prompt-textarea').textContent = ''")
            runs.nth(1).locator("button.go").click()
            runs.nth(1).locator(".confirm").wait_for(state="visible", timeout=8000)
            assert "ricorsivo" in runs.nth(1).locator(".confirm").inner_text()
            if SHOTS:
                page.evaluate("document.documentElement.classList.add('dark');"
                              "document.body.style.background='#212121'; document.body.style.color='#eee'")
                page.wait_for_timeout(800)
                shot(page, "ext-confirm-dark.png")
                page.evaluate("document.documentElement.classList.remove('dark');"
                              "document.body.style.background=''; document.body.style.color=''")
                page.wait_for_timeout(800)
            runs.nth(1).locator("button.yes").click()
            page.wait_for_function("document.getElementById('prompt-textarea').textContent.includes('removed')",
                                   timeout=10000)
            confirmed = [e for e in events() if e["kind"] == "run" and e.get("confirmed")]
            assert confirmed and confirmed[0]["id"] == [e for e in events() if e["kind"] == "run"][1]["id"]
            ok.append("comando rischioso: avviso nella pagina, eseguito solo dopo «Esegui comunque»")

            # 3) clic finto dalla pagina: ignorato
            before = len([e for e in events() if e["kind"] == "run"])
            page.evaluate("document.querySelectorAll('helpix-run')[0].shadowRoot.querySelector('button.go').click()")
            time.sleep(1.2)
            assert len([e for e in events() if e["kind"] == "run"]) == before, "un clic sintetico non deve inviare"
            ok.append("i clic simulati dalla pagina vengono ignorati")

            # 4) riepilogo del task
            runs.nth(2).locator("button.go").click()
            runs.nth(2).locator(".state.ok").wait_for(timeout=8000)
            ok.append("riepilogo HELPIX-TASK inviato all'app")

            # 5) screenshot e diagnosi dal pannello laterale
            pill = page.locator("helpix-pill")
            page.evaluate("document.getElementById('prompt-textarea').textContent = ''")
            pill.locator("button.shot").click()
            page.wait_for_function("window.pastedFiles && window.pastedFiles.length === 1", timeout=10000)
            f = page.evaluate("window.pastedFiles[0]")
            assert f["type"] == "image/png" and f["size"] > 100, f
            pill.locator("button.diag").click()
            page.wait_for_function("document.getElementById('prompt-textarea').textContent.includes('DIAGNOSI DI PROVA')",
                                   timeout=10000)
            ok.append("Screenshot e Diagnosi dal pannello: immagine e testo incollati nella chat")

            # 6) passaggio del task: nuova scheda, incolla testo e screenshot (casella textarea + input file)
            with ctx.expect_page(timeout=15000) as info:
                runs.nth(3).locator("button.go").click()
            new = info.value
            new.wait_for_load_state()
            assert "claude.ai" in new.url, new.url
            new.wait_for_function("document.getElementById('chat-input').value.includes('TESTO DEL TASK')", timeout=15000)
            new.wait_for_function("window.uploaded && window.uploaded.length === 1", timeout=10000)
            wait(lambda: any(e["kind"] == "package_result" and e["ok"] for e in events()), what="esito del pacchetto")
            ok.append("task aperto in una chat nuova di un altro servizio: testo e screenshot incollati")

            # 7) Helpix si chiude e si riapre: il browser si ricollega e la scheda resta nota all'app
            app.terminate()
            app.wait(5)
            page.bring_to_front()
            page.wait_for_function("document.querySelector('helpix-pill').shadowRoot.querySelector('.dot.on') === null",
                                   timeout=10000)
            log_file.unlink()
            app = subprocess.Popen([sys.executable, str(HERE / "fake_app.py"), str(log_file)], env=env)
            page.wait_for_function("document.querySelector('helpix-pill').shadowRoot.querySelector('.dot.on') !== null",
                                   timeout=15000)
            wait(lambda: any(e["kind"] == "clients" and any(t.get("chatgpt") for t in e.get("tabs", []))
                             for e in events()), what="schede comunicate di nuovo all'app")
            page.evaluate("document.getElementById('prompt-textarea').textContent = ''")
            runs.nth(0).locator("button.go").click()
            page.wait_for_function("document.getElementById('prompt-textarea').textContent.includes('hello-helpix')",
                                   timeout=10000)
            ok.append("Helpix riavviato: il browser si ricollega da solo e tutto funziona di nuovo")

            ctx.close()
    finally:
        app.terminate()
        app.wait(5)
    for line in ok:
        print("ok", line)
    print(f"E2E superato ({len(ok)} controlli)")


if __name__ == "__main__":
    main()
