# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filtro privacy (python tests/test_privacy.py)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from helpix.privacy import Redactor, describe  # noqa: E402


def test_secrets_and_identity():
    r = Redactor(hostname="nas-rossi.studio.lan", username="mario")
    text = ("mario@nas-rossi:~$ cat /home/mario/.env\nDB_PASSWORD=Sup3rS3gret0!\napi_key: \"abc def\"\n"
            "OPENAI_API_KEY=sk" "-proj-abcdefghijklmnopqrstuvwx123\n"
            "Authorization: Bearer ey" "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk\n"
            "https://admin:pa55w0rd@git.example.com/r.git\n"
            "wan 93.184.216.34 dns 8.8.8.8 again 93.184.216.34 lan 192.168.1.20/24 gw 10.0.0.1\n"
            "inet6 2a01:4f8:c17:1::5/64 fe80::1%eth0 ether 3c:52:82:aa:bb:cc brd ff:ff:ff:ff:ff:ff\n"
            "mail mario.rossi@studio-rossi.it unit user@1000.service\n"
            "-----BE" "GIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n")
    out, found = r.redact(text)
    for secret in ("Sup3rS3gret0", "abc def", "sk" "-proj", "eyJhbG", "pa55w0rd", "93.184.216.34",
                   "2a01:4f8", "3c:52:82", "mario.rossi@", "/home/mario", "mario@", "nas-rossi", "AAAA"):
        assert secret not in out, (secret, out)
    # quello che serve per capire il problema resta
    for keep in ("192.168.1.20/24", "10.0.0.1", "fe80::1", "ff:ff:ff:ff:ff:ff", "user@1000.service", "dns 8.8.8.8",
                 "DB_PASSWORD=", "https://admin:"):
        assert keep in out, (keep, out)
    # stesso dato, stesso segnaposto
    assert out.count("[IP-1]") == 2 and "[IP-2]" in out  # 8.8.8.8 è un DNS pubblico: resta
    assert found["ip"] == 3 and found["token"] == 2 and found["key"] == 1
    assert "IP" in describe(found)
    # già filtrato: nessun cambiamento
    again, found2 = r.redact(out)
    assert again == out and not found2


def test_no_false_positives():
    r = Redactor(hostname="fedora", username="crash")
    text = ("PASS: test_login  bypass: true  password: required  passed=12  PWD=/tmp\n"
            "Linux fedora 6.8.0 12:34:56 std::vector netmask 255.255.255.0 kernel crash dump\n"
            "token: 3  secret=***  Version 1.2.3\n")
    out, found = r.redact(text)
    assert out == text, out
    assert not found


def test_admin_and_msp_data():
    r = Redactor(hostname="crash-desktop", username="crash")
    text = """Machine ID: 4f1c2a9b8e7d4c3b9a8f7e6d5c4b3a29
Serial Number: PF3XK9Z2
802-11-wireless.ssid:   CasaCrash_5G
wlp3s0    ESSID:"Ufficio Cliente"
//nas.studio.local/backup /mnt/backup cifs username=crash,password=Nas!Pass99 0 0
MYSQL_PWD=rootpw123
sudo[2201]:    crash : TTY=pts/1 ; PWD=/home/crash ; USER=root ; COMMAND=/usr/bin/dnf update
sshd[99]: Accepted publickey for crash from 192.168.10.5 port 5122 ssh2
uid=1000(crash) gid=1000(crash)
curl -u admin:SuperSecret https://api.example.com/v1
mysql -u root -pRootPass123 -h db
sshpass -p 'Passw0rd!' ssh admin@10.0.0.5
openconnect --password hunter22 vpn.example.com
dn: CN=Mario Rossi,CN=Users,DC=cliente,DC=local
telephoneNumber: +39 0544 123456
dc01.cliente.local has address 192.168.1.2
"""
    out, found = r.redact(text)
    for secret in ("4f1c2a9b", "PF3XK9Z2", "CasaCrash", "Ufficio Cliente", "nas.studio.local", "Nas!Pass99",
                   "rootpw123", " crash ", "for crash", "(crash)", "SuperSecret", "RootPass123", "Passw0rd!",
                   "hunter22", "Mario Rossi", "DC=cliente", "0544 123456", "dc01.cliente.local"):
        assert secret not in out, (secret, out)
    for keep in ("CN=Users", "192.168.10.5", "10.0.0.5", "USER=root", "api.example.com", "/mnt/backup"):
        assert keep in out, (keep, out)
    again, found2 = r.redact(out)
    assert again == out and not found2, "applicato due volte non cambia nulla"


def test_no_false_positives_admin():
    r = Redactor(hostname="crash-desktop", username="crash")
    text = ("kernel: crash dump saved\nSerial Number: Not Specified\ncat /etc/avahi/hosts.local\n"
            "PWD=/tmp\nssh -p 2222 admin@10.0.0.5\nping -c 4 example.com\n"
            "credentials=/etc/samba/cred\nTimezone: Europe/Rome (CET, +0100)\n")
    out, found = r.redact(text)
    assert out == text and not found, out


def test_corpus():
    """Decine di casi reali: segreti da nascondere e testo normale da lasciare com'è."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from privacy_corpus import CASES
    failures = []
    for text, hide, keep in CASES:
        r = Redactor(hostname="crash-desktop", username="crash")
        out, _ = r.redact(text)
        missed = [h for h in hide if h in out]
        broken = [k for k in keep if k not in out]
        again, more = r.redact(out)
        if missed or broken or again != out:
            failures.append((text[:60], missed, broken, again != out))
    assert not failures, failures


def test_paste_points():
    """Con lo scudo acceso anche gli incolla dell'utente passano dal filtro."""
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from helpix import privacy
    from helpix.ui.chat import PromptEdit
    from helpix.ui.terminal_view import _Bridge
    seen = []
    privacy.activate(Redactor(hostname="", username=""), lambda found: seen.append(sum(found.values())))
    try:
        # casella del motore API
        box = PromptEdit()
        md = QMimeData()
        md.setText("token: gh" "p_1234567890abcdefghijklmnopqrstuvwxyz ip 93.184.216.34")
        box.insertFromMimeData(md)
        assert "gh" "p_" not in box.toPlainText() and "93.184.216.34" not in box.toPlainText(), box.toPlainText()

        # terminale degli agenti (Ctrl+Maiusc+V, Incolla dal menu, clic centrale)
        class FakeView:
            class pty:
                pasted = []

                @staticmethod
                def paste(text):
                    FakeView.pty.pasted.append(text)
        _Bridge.pasteText(type("B", (), {"view": FakeView})(), "export API_KEY=abc123def456")
        assert FakeView.pty.pasted == ["export API_KEY=[SEGRETO]"], FakeView.pty.pasted
        assert seen, "avviso dopo l'incolla"
    finally:
        privacy.deactivate()
    assert privacy.filter_paste("API_KEY=abc123def456") == "API_KEY=abc123def456", "scudo spento: invariato"


def test_main_window_toggle():
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from helpix.config import SecretStore, Settings, ensure_dirs
    from helpix.ui.main_window import MainWindow
    ensure_dirs()

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False, auto_continue=False)
    win = MainWindow(settings, SecretStore())
    assert not win.btn_privacy.isChecked() and not win.privacy_on, "spento di default"

    def run(cmd):
        n = len(win.session.messages)
        win.run_command(cmd, "ai", None)
        end = time.monotonic() + 15
        while time.monotonic() < end:
            new = [m for m in win.session.messages[n:] if m.kind == "output"]
            if new:
                return new[-1].text
            pump(50)
        raise AssertionError("output non arrivato")

    cmd = "echo DB_PASSWORD=hunter2segreto; echo wan 93.184.216.34"
    assert "hunter2segreto" in run(cmd), "filtro spento: testo invariato"
    win.btn_privacy.click()
    assert win.privacy_on and settings.get("privacy_filter") is True
    out = run(cmd)
    assert "hunter2segreto" not in out and "93.184.216.34" not in out and "[IP-1]" in out, out
    # finestra rapida: anche il testo incollato lì passa dal filtro
    sent = []
    win.web.paste_text = lambda text, *a, **k: sent.append(text)
    win.web.last_answer = lambda cb: cb({"count": 0, "text": "", "busy": False})
    win.web.send_current = lambda *a, **k: None
    win.instance.reply = lambda *a, **k: None
    win.engine = "web"
    win._quick_send("guarda questo: password=hunter2segreto", None)
    assert sent and "hunter2segreto" not in sent[0], sent

    # anteprima del passaggio di task: anche «Copia» prende il testo oscurato
    from helpix.ui.handoff_dialog import HandoffDialog
    from helpix.session import Message
    win.session.add(Message("assistant", "riepilogo: la mail è mario.rossi@example.com", kind="summary"))
    dlg = HandoffDialog(win.session, "Claude", "chatgpt", False, win)
    assert "mario.rossi@example.com" not in dlg.preview.toPlainText()
    assert dlg.privacy_note.isVisibleTo(dlg)
    dlg.close()

    # utente e nome del PC «veri» per le prove che seguono
    from helpix import agents as agents_mod, prompts, privacy as priv
    fake = dict(prompts.system_info(), user="crash", host="crash-desktop")
    prompts.system_info = agents_mod.system_info = lambda: dict(fake)
    win._redactor = priv.Redactor(hostname="crash-desktop", username="crash")
    win._sync_privacy()

    # messaggio di sistema del motore API e istruzioni per gli agenti
    sysmsg = win._system_prompt()
    assert "crash-desktop" not in sysmsg and "[HOST]" in sysmsg, sysmsg[-400:]
    ws = agents_mod.write_context("claude-code")
    ctx = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "crash-desktop" not in ctx and "/home/crash" not in ctx  # nessun dato personale

    # motore API: anche il testo scritto a mano nella casella
    win.engine = "api"
    win.request_ai = lambda: None
    win.prompt.setPlainText("la password del NAS è password=Nas!Segreto9")
    win.send_message()
    assert "Nas!Segreto9" not in win.session.messages[-1].text, win.session.messages[-1].text

    # export su file: testi oscurati
    import json
    import zipfile
    path = os.path.join(_tmp, "esportato.helpix")
    from helpix.task import export_task as exp
    out = exp(win.session, path, None, redact=lambda t: priv.filter_paste(t, notify=False))
    data = json.loads(zipfile.ZipFile(out).read("task.json"))
    dump = json.dumps(data)
    assert "Nas!Segreto9" not in dump and "mario.rossi@example.com" not in dump and "hunter2segreto" not in dump

    win.btn_privacy.click()
    assert not win.privacy_on
    from helpix import privacy
    assert not privacy.paste_filter_active(), "scudo spento: niente filtro sugli incolla"
    win.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
