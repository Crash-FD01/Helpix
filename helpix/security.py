# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sicurezza facoltativa di Helpix.

- Cifratura con password dei task esportati (.helpix): AES-256-GCM, chiave derivata dalla
  password con scrypt. Il file cifrato inizia con MAGIC; senza la password non si legge e
  qualsiasi modifica viene rilevata.
- Sblocco di Helpix con la password del proprio utente Linux o con l'impronta, tramite polkit
  (lo stesso dialogo di sistema di sudo e delle impostazioni).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

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
    return bool(shutil.which("pkcheck"))


def policy_installed() -> bool:
    return POLICY_FILE.exists()


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
        argv = self.command or ["pkcheck", "--action-id", ACTION_ID, "--process", str(os.getpid()),
                                "--allow-user-interaction"]
        self.proc = QProcess(self)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.proc.start(argv[0], argv[1:])

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
