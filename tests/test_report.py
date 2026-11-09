# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""«Segnala un problema»: pacchetto filtrato, niente contenuti del vault, invio e finestra
(python tests/test_report.py). Esegue anche il test del Worker se c'è node."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HELPIX_NO_UPDATE_CHECK"] = "1"
os.environ.pop("HELPIX_REPORT_URL", None)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import agents, report  # noqa: E402
from helpix.config import DATA_DIR, LOG_FILE, Settings  # noqa: E402
from helpix.i18n import set_language  # noqa: E402
from helpix.privacy import Redactor  # noqa: E402

set_language("it")
RED = Redactor(hostname="pc-mario-ufficio", username="mrossi")


def _write_logs():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    who, host = "mrossi", "pc-mario-ufficio"
    LOG_FILE.write_text("\n".join([
        f"2026-11-09 10:00:00 helpix: avvio da {Path.home() / 'progetti'}",
        f"2026-11-09 10:00:01 helpix: utente {who} su {host}, mail mario.rossi@example.com",
        "2026-11-09 10:00:02 helpix: server 192.168.10.25 non risponde",
    ] + [f"riga {i}" for i in range(2000)]) + "\n", encoding="utf-8")
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs" / "install-codex.log").write_text("installazione ok\n", encoding="utf-8")
    ws = agents.workspace()
    (ws / agents.PROJECT_FILE).write_bytes("﻿HELPIX-PROJECT\nNOTA: CONTENUTO-SEGRETO\n".encode("utf-8"))


def test_pacchetto_filtrato_e_senza_contenuti():
    _write_logs()
    settings = Settings()
    settings.data.update(projects_beta=True, vault_dir=str(Path.home() / "Vault-di-prova"), engine="agent")
    sections = report.collect(settings, None, diagnostics=False, redactor=RED)
    keys = [s.key for s in sections]
    assert keys[:4] == ["system", "settings", "vault", "log"] and "install-codex" in keys
    text = report.body("Non compare l'anteprima", sections)
    assert "CONTENUTO-SEGRETO" not in text, "il contenuto dei file del progetto non deve mai entrare"
    assert "Vault-di-prova" not in text and "vault_dir" not in text
    assert "HELPIX-PROJECT.md:" in text and "ef bb bf" in text and "UTF-8 con BOM" in text
    assert "mario.rossi@example.com" not in text and "192.168.10.25" not in text
    assert str(Path.home()) not in text
    assert "mrossi" not in text and "pc-mario-ufficio" not in text
    assert "- engine: agent" in text and "- projects_beta: True" in text
    assert "Helpix: " in text and "Python: " in text
    assert len(text) <= report.MAX_BODY
    assert "riga 1999" in text, "dei registri restano le righe più recenti"


def test_testo_troppo_lungo():
    big = [report.Section("log", "Registro", "x" * 50000), report.Section("quick", "Rapida", "y" * 40000)]
    text = report.body("descrizione", big)
    assert len(text) <= report.MAX_BODY and "descrizione" in text and text.count("```") == 4


class _Fake(BaseHTTPRequestHandler):
    status, answer, got = 201, {"number": 5}, []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("content-length", 0))
        _Fake.got.append((self.path, json.loads(self.rfile.read(n)), self.headers.get("User-Agent")))
        data = json.dumps(_Fake.answer).encode()
        self.send_response(_Fake.status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/segnala"


def test_invio():
    srv, url = _server()
    try:
        data = report.payload("Titolo", "testo")
        assert report.send(data, url) == 5
        path, sent, ua = _Fake.got[-1]
        assert path == "/segnala" and sent["app"] == "helpix" and sent["title"] == "Titolo" and ua.startswith("Helpix/")
        for status, answer, msg in ((429, {}, "Troppe"), (502, {"error": "GitHub (401)"}, "401")):
            _Fake.status, _Fake.answer = status, answer
            try:
                report.send(data, url)
                raise AssertionError("doveva fallire")
            except report.ReportError as exc:
                assert msg in str(exc), exc
        try:
            report.send(data, "")
            raise AssertionError("senza indirizzo non si invia")
        except report.ReportError:
            pass
    finally:
        _Fake.status, _Fake.answer = 201, {"number": 5}
        srv.shutdown()


def test_finestra():
    from helpix.ui import report_dialog
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    # senza servizio: «Invia» spento, si salva il file
    dlg = report_dialog.ReportDialog(Settings(), None, url="")
    assert not dlg.btn_send.isEnabled() and "non è ancora attivo" in dlg.status.text()
    assert dlg.checks["diag"].isChecked() is False and dlg.checks["system"].isChecked()
    dlg.title.setText("Il salvataggio non si apre")
    dlg.desc.setPlainText("Premo Salva progetto e non succede niente")
    assert "Premo Salva progetto" in dlg.preview.toPlainText()
    dlg.checks["log"].setChecked(False)
    assert "Registro di Helpix" not in dlg.preview.toPlainText()
    report_save = report.save
    report.save = lambda data: report_save(data, Path(_tmp))
    try:
        dlg._save()
    finally:
        report.save = report_save
    saved = dlg.saved_to.read_text(encoding="utf-8")
    assert saved.startswith("# Il salvataggio non si apre") and "Premo Salva progetto" in saved
    dlg.deleteLater()
    # con il servizio: parte esattamente l'anteprima, anche modificata a mano
    srv, url = _server()
    try:
        dlg = report_dialog.ReportDialog(Settings(), None, url=url, title="Vault: ")
        dlg.title.setText("Vault: non si sblocca")
        dlg.preview.setPlainText("solo questo")
        dlg._send()
        assert dlg.number == 5 and dlg.result() == dlg.DialogCode.Accepted
        assert _Fake.got[-1][1]["body"] == "solo questo" and _Fake.got[-1][1]["title"] == "Vault: non si sblocca"
    finally:
        srv.shutdown()


def test_worker_con_node():
    node = shutil.which("node")
    if not node:
        print("node assente: test del Worker saltato")
        return
    r = subprocess.run([node, str(ROOT / "tools" / "segnalazioni" / "test_worker.mjs")], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0 and "ok worker" in r.stdout, r.stdout + r.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
