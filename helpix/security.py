# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sicurezza facoltativa di Helpix.

- Cifratura con password dei task esportati (.helpix): AES-256-GCM, chiave derivata dalla
  password con scrypt. Il file cifrato inizia con MAGIC; senza la password non si legge e
  qualsiasi modifica viene rilevata.
- Sblocco di Helpix con la password del proprio utente Linux o con l'impronta, tramite polkit
  (lo stesso dialogo di sistema di sudo e delle impostazioni). Su Windows con Windows Hello (PIN, impronta o
  volto), lo stesso dialogo che Windows usa per confermare l'identità.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, Signal

IS_WINDOWS = sys.platform == "win32"

MAGIC = b"HELPIX-ENC1\n"
_SALT, _NONCE = 16, 12
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}

ACTION_ID = "io.github.crash_fd01.helpix.unlock"
POLICY_DIR = Path("/usr/share/polkit-1/actions")
POLICY_FILE = POLICY_DIR / f"{ACTION_ID}.policy"
POLICY_SOURCE = Path(__file__).resolve().parent / "data" / "polkit" / f"{ACTION_ID}.policy"


class WrongPassword(Exception):
    pass


class PasswordRequired(Exception):
    pass


# ------------------------------------------------------------------ cifratura
def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, **_SCRYPT).derive(password.encode("utf-8"))


def encrypt_bytes(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not password:
        raise ValueError("password vuota")
    salt, nonce = os.urandom(_SALT), os.urandom(_NONCE)
    return MAGIC + salt + nonce + AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC):
        raise ValueError("non è un file cifrato di Helpix")
    rest = blob[len(MAGIC):]
    salt, nonce, ct = rest[:_SALT], rest[_SALT:_SALT + _NONCE], rest[_SALT + _NONCE:]
    try:
        return AESGCM(_key(password or "", salt)).decrypt(nonce, ct, MAGIC)
    except InvalidTag as exc:
        raise WrongPassword() from exc


def is_encrypted_file(path: str | Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


# ------------------------------------------------------------------ sblocco con polkit
def unlock_available() -> bool:
    if IS_WINDOWS:
        return hello_status() == "available"
    return bool(shutil.which("pkcheck"))


def policy_installed() -> bool:
    if IS_WINDOWS:
        return True  # nessuna regola di sistema: Windows Hello è sempre utilizzabile dall'utente
    return POLICY_FILE.exists()


# ------------------------------------------------------------------ Windows Hello
_HELLO_STATUS: str | None = None


def _run_async(coro_factory, timeout: float):
    """Esegue una chiamata asincrona di WinRT in un thread separato (Qt ha già il suo ciclo di eventi)."""
    import asyncio
    box: dict = {}

    def runner():
        try:
            box["value"] = asyncio.run(asyncio.wait_for(coro_factory(), timeout))
        except BaseException as exc:  # noqa: BLE001 - riportata al chiamante
            box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout + 1)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def hello_status() -> str:
    """«available», «not-configured» (PIN, impronta o volto non impostati), «unavailable» (WinRT o criteri)."""
    global _HELLO_STATUS
    if _HELLO_STATUS is not None:
        return _HELLO_STATUS
    try:
        from winrt.windows.security.credentials.ui import UserConsentVerifier, UserConsentVerifierAvailability as A

        async def check():
            return await UserConsentVerifier.check_availability_async()

        value = _run_async(check, 10)
        _HELLO_STATUS = ("available" if value == A.AVAILABLE else
                         "not-configured" if value in (A.NOT_CONFIGURED_FOR_USER, A.DEVICE_NOT_PRESENT) else
                         "unavailable")
    except Exception:  # noqa: BLE001 - modulo assente, WinRT non disponibile
        _HELLO_STATUS = "unavailable"
    return _HELLO_STATUS


def _bring_hello_to_front() -> None:
    """Il dialogo di Windows Hello aperto da un programma desktop a volte resta dietro: lo porto davanti."""
    import ctypes
    import time
    user32 = ctypes.windll.user32
    for _ in range(40):  # fino a 4 secondi
        hwnd = user32.FindWindowW("Credential Dialog Xaml Host", None)
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            return
        time.sleep(0.1)


class SystemUnlock(QObject):
    """Chiede al sistema di confermare che davanti al PC c'è l'utente (password o impronta).

    Esito con finished(ok, messaggio). Il comando è sostituibile nei test.
    """

    finished = Signal(bool, str)
    command: list[str] | None = None   # per i test: comando al posto di pkcheck

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None

    @property
    def busy(self) -> bool:
        return self.proc is not None

    def start(self):
        if self.proc is not None:
            return
        if IS_WINDOWS and self.command is None:
            self._start_hello()
            return
        argv = self.command or ["pkcheck", "--action-id", ACTION_ID, "--process", str(os.getpid()),
                                "--allow-user-interaction"]
        self.proc = QProcess(self)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.proc.start(argv[0], argv[1:])

    _hello_done = Signal(bool, str)

    def _start_hello(self):
        from .i18n import tr
        self.proc = "hello"  # occupato
        self._hello_done.connect(self._finish_hello, type=Qt.ConnectionType.UniqueConnection)
        message = tr("Sblocca Helpix")

        def run():
            ok, msg = False, ""
            try:
                from winrt.windows.security.credentials.ui import UserConsentVerificationResult as R
                from winrt.windows.security.credentials.ui import UserConsentVerifier

                async def verify():
                    return await UserConsentVerifier.request_verification_async(message)

                threading.Thread(target=_bring_hello_to_front, daemon=True).start()
                result = _run_async(verify, 300)
                ok = result == R.VERIFIED
                msg = "" if ok else ("annullato" if result == R.CANCELED else str(result))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
            self._hello_done.emit(ok, msg)

        threading.Thread(target=run, name="helpix-hello", daemon=True).start()

    def _finish_hello(self, ok: bool, msg: str):
        self.proc = None
        self.finished.emit(ok, msg)

    def _done(self, code, _status=None):
        proc, self.proc = self.proc, None
        err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip() if proc else ""
        if proc:
            proc.deleteLater()
        self.finished.emit(code == 0, err)

    def _error(self, _err):
        if self.proc is not None and self.proc.state() == QProcess.ProcessState.NotRunning:
            proc, self.proc = self.proc, None
            msg = proc.errorString()
            proc.deleteLater()
            self.finished.emit(False, msg)


def install_policy_command() -> list[str]:
    """Installa (con la password di amministratore, una volta sola) la regola polkit di Helpix."""
    return ["pkexec", "/usr/bin/install", "-m", "0644", str(POLICY_SOURCE), str(POLICY_FILE)]
