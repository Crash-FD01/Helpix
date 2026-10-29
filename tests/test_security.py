# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sicurezza facoltativa: export cifrato e blocco con la password di sistema (python tests/test_security.py).

Lo sblocco vero passa da polkit (pkcheck): qui il comando è sostituito da `true` / `false`.
"""
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

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import security  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402
from helpix.session import Message, Session  # noqa: E402
from helpix.task import export_task, import_task  # noqa: E402

ensure_dirs()


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def until(fn, timeout=10, what=""):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        pump(50)
    raise AssertionError("timeout: " + what)


def test_crypto():
    blob = security.encrypt_bytes(b"segreto del task", "password-lunga")
    assert blob.startswith(security.MAGIC) and b"segreto" not in blob
    assert security.decrypt_bytes(blob, "password-lunga") == b"segreto del task"
    for wrong in ("password-sbagliata", ""):
        try:
            security.decrypt_bytes(blob, wrong)
            raise AssertionError("una password sbagliata non deve aprire il file")
        except security.WrongPassword:
            pass
    tampered = bytearray(blob)
    tampered[-5] ^= 1
    try:
        security.decrypt_bytes(bytes(tampered), "password-lunga")
        raise AssertionError("un file modificato deve essere rifiutato")
    except security.WrongPassword:
        pass
    # due cifrature della stessa cosa sono diverse (sale e nonce casuali)
    assert security.encrypt_bytes(b"x", "p" * 8) != security.encrypt_bytes(b"x", "p" * 8)


def test_encrypted_export_roundtrip():
    png = os.path.join(_tmp, "shot.png")
    with open(png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nimmagine")
    s = Session("anthropic", "claude-sonnet-5-5", "/tmp")
    s.title = "Backup del NAS"
    s.add(Message("user", "Screenshot", images=[png], kind="shot"))
    s.add(Message("assistant", "Obiettivo: backup notturno", kind="summary", meta={"source": "Claude"}))
    plain = export_task(s, os.path.join(_tmp, "chiaro.helpix"))
    enc = export_task(s, os.path.join(_tmp, "cifrato.helpix"), password="parola-segreta")
    assert not security.is_encrypted_file(plain) and security.is_encrypted_file(enc)
    assert oct(os.stat(enc).st_mode & 0o777) == "0o600"
    assert b"backup" not in open(enc, "rb").read()
    try:
        import_task(enc)
        raise AssertionError("senza password non si importa")
    except security.PasswordRequired:
        pass
    try:
        import_task(enc, "sbagliata")
        raise AssertionError("password sbagliata")
    except security.WrongPassword:
        pass
    back = import_task(enc, "parola-segreta")
    assert back.title == "Backup del NAS"
    assert any(m.kind == "summary" for m in back.messages)
    img = [m for m in back.messages if m.kind == "shot"][0].images[0]
    assert open(img, "rb").read().endswith(b"immagine")
    assert import_task(plain).title == "Backup del NAS"


def test_lock_and_unlock():
    if not security.unlock_available():
        print("  (pkcheck assente: test del blocco saltato)")
        return
    from helpix.ui.main_window import MainWindow
    from pathlib import Path
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, lock_enabled=True, lock_minutes=5, quick_shortcut=False)

    # regola polkit sparita (es. dopo un aggiornamento): niente blocco, per non chiudere fuori l'utente
    security.POLICY_FILE = Path(_tmp) / "assente.policy"
    probe = MainWindow(settings, SecretStore())
    assert not probe.lock_enabled and not probe.locked
    probe.close()
    probe.deleteLater()
    pump(100)

    security.POLICY_FILE = Path(_tmp) / "helpix.policy"
    security.POLICY_FILE.write_text("<policyconfig/>")
    win = MainWindow(settings, SecretStore())
    win.resize(900, 600)
    win.show()
    pump(200)
    assert win.locked and win._overlay.isVisible(), "con il blocco attivo Helpix parte bloccato"
    assert not win.picker.isEnabled() and not win.shot.isEnabled()
    assert win._overlay.geometry() == win.hsplit.geometry(), "il lucchetto copre tutto il contenuto"

    # la finestra rapida non può inviare nulla
    replies = []
    win.instance.reply = lambda sock, msg: replies.append(msg)
    win._on_instance({"type": "send", "text": "ciao"}, object())
    assert replies[-1]["type"] == "locked"

    # sblocco rifiutato, poi riuscito
    security.SystemUnlock.command = ["false"]
    win.unlock()
    until(lambda: not win._unlocker.busy, what="esito pkcheck")
    assert win.locked and win._overlay.isVisible()
    security.SystemUnlock.command = ["true"]
    results = []
    win._on_instance({"type": "unlock"}, object())
    win.unlock(results.append)
    until(lambda: not win.locked, what="sblocco")
    assert results == [True] and not win._overlay.isVisible() and win.picker.isEnabled()
    assert replies[-1]["type"] == "unlocked"

    # blocco automatico: parte quando Helpix non è in uso, si ferma quando torna attivo
    win._activity(False)
    assert win._lock_timer.isActive() and win._lock_timer.interval() == 5 * 60_000
    win._activity(True)
    assert not win._lock_timer.isActive()
    win._lock_timer.timeout.emit()
    assert win.locked
    win.close()
    security.SystemUnlock.command = None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    os._exit(0)
