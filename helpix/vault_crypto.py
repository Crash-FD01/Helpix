# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cifratura del vault di Helpix (beta).

Questo file non dipende dal resto di Helpix: serve solo la libreria `cryptography`. Così i dati restano
recuperabili anche senza Helpix:

    python3 vault_crypto.py decrypt <cartella del vault> <cartella di destinazione>

Schema (come gli slot di LUKS):
- una chiave master casuale da 256 bit; da questa, con HKDF-SHA256, la chiave dei dati e quella dei nomi;
- la chiave master è chiusa con AES-256-GCM in più «slot»: password, codici usa e getta, file di recupero,
  portachiavi di sistema. Password e codici diventano chiavi con scrypt (parametri salvati nello slot);
- ogni file del vault è `dati/<HMAC del percorso>.hxv` = MAGIC + nonce + AES-256-GCM(percorso + contenuto),
  con il nome del file nei dati autenticati: un file spostato o scambiato non si decifra.
L'intestazione `helpix-vault.json` è in chiaro e non contiene dati dell'utente.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sys
import time
import uuid
from pathlib import Path

FORMAT = "helpix-vault"
VERSION = 1
HEADER = "helpix-vault.json"
BACKUP_DIR = ".backup"
DATA_DIR = "dati"
FILE_MAGIC = b"HXV1"
FILE_EXT = ".hxv"
RECOVERY_MAGIC = "HELPIX-VAULT-RECOVERY"
KEEP_BACKUPS = 10
# 128 MiB di memoria, circa mezzo secondo: provare password a caso diventa molto lento (anche con le GPU)
SCRYPT = {"n": 2 ** 17, "r": 8, "p": 1}
_NONCE = 12

KINDS = ("password", "code", "recovery", "keyring")


class VaultError(Exception):
    """Errore del vault con un messaggio da mostrare."""


class WrongSecret(VaultError):
    """Password, codice o file di recupero non validi per questo vault."""


class CorruptFile(VaultError):
    """File cifrato rovinato, modificato o spostato."""


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _aesgcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _hkdf(key: bytes, info: bytes, salt: bytes | None = None) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(key)


def normalize_code(code: str) -> str:
    """Codice usa e getta in forma canonica: minuscolo, parole separate da un trattino."""
    words = "".join(c if c.isalnum() else " " for c in (code or "").lower()).split()
    return "-".join(words)


def _secret_bytes(kind: str, secret) -> bytes:
    if isinstance(secret, bytes):
        return secret
    if kind == "code":
        return normalize_code(secret).encode("utf-8")
    return str(secret).encode("utf-8")


def derive_kek(kind: str, secret, slot: dict) -> bytes:
    """Chiave che apre uno slot. Password e codici con scrypt; file di recupero e portachiavi (già casuali,
    256 bit) con HKDF."""
    raw = _secret_bytes(kind, secret)
    salt = b64d(slot["salt"])
    kdf = slot.get("kdf", {})
    if kdf.get("name") == "scrypt":
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return Scrypt(salt=salt, length=32, n=int(kdf["n"]), r=int(kdf["r"]), p=int(kdf["p"])).derive(raw)
    if kdf.get("name") == "hkdf":
        return _hkdf(raw, b"helpix-vault slot", salt)
    raise VaultError(f"KDF sconosciuto: {kdf.get('name')!r}")


class Keys:
    """Chiavi ricavate dalla chiave master (in memoria solo mentre il vault è aperto)."""

    def __init__(self, master: bytes, vault_id: str):
        if len(master) != 32:
            raise ValueError("chiave master non valida")
        self.master = master
        self.vault_id = vault_id
        self.data = _hkdf(master, b"helpix-vault data")
        self.names = _hkdf(master, b"helpix-vault names")

    def opaque_name(self, relpath: str) -> str:
        return hmac.new(self.names, relpath.encode("utf-8"), hashlib.sha256).hexdigest()[:40]

    def _aad(self, opaque: str) -> bytes:
        return FILE_MAGIC + self.vault_id.encode("ascii") + b"|" + opaque.encode("ascii")

    def encrypt(self, relpath: str, content: bytes) -> tuple[str, bytes]:
        """(nome del file, contenuto cifrato) per il percorso logico `relpath`."""
        opaque = self.opaque_name(relpath)
        head = json.dumps({"p": relpath}, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(_NONCE)
        blob = _aesgcm(self.data).encrypt(nonce, head + b"\n" + content, self._aad(opaque))
        return opaque + FILE_EXT, FILE_MAGIC + nonce + blob

    def decrypt(self, filename: str, blob: bytes) -> tuple[str, bytes]:
        """(percorso logico, contenuto) di un file cifrato; CorruptFile se rovinato, modificato o spostato."""
        from cryptography.exceptions import InvalidTag
        opaque = filename[:-len(FILE_EXT)] if filename.endswith(FILE_EXT) else filename
        if not blob.startswith(FILE_MAGIC) or len(blob) < len(FILE_MAGIC) + _NONCE + 16:
            raise CorruptFile(filename)
        nonce = blob[len(FILE_MAGIC):len(FILE_MAGIC) + _NONCE]
        try:
            plain = _aesgcm(self.data).decrypt(nonce, blob[len(FILE_MAGIC) + _NONCE:], self._aad(opaque))
        except InvalidTag as exc:
            raise CorruptFile(filename) from exc
        head, _, content = plain.partition(b"\n")
        try:
            relpath = json.loads(head.decode("utf-8"))["p"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CorruptFile(filename) from exc
        if not hmac.compare_digest(self.opaque_name(relpath), opaque):
            raise CorruptFile(filename)
        return relpath, content


# ------------------------------------------------------------------ intestazione e slot
class Header:
    """`helpix-vault.json`: formato, identificativo, cifratura e slot delle chiavi."""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def new_plain(cls, name: str = "") -> "Header":
        return cls({"format": FORMAT, "version": VERSION, "id": uuid.uuid4().hex, "name": name,
                    "created": int(time.time()), "encrypted": False})

    @classmethod
    def new_encrypted(cls, name: str = "", vault_id: str | None = None) -> tuple["Header", bytes]:
        """Intestazione nuova senza slot e la chiave master da chiudere negli slot."""
        h = cls({"format": FORMAT, "version": VERSION, "id": vault_id or uuid.uuid4().hex, "name": name,
                 "created": int(time.time()), "encrypted": True, "cipher": "AES-256-GCM", "slots": []})
        return h, secrets.token_bytes(32)

    @classmethod
    def load(cls, root: str | Path) -> "Header":
        path = Path(root) / HEADER
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, ValueError) as exc:
            raise VaultError(f"intestazione del vault illeggibile: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise VaultError("la cartella non contiene un vault di Helpix")
        if int(data.get("version", 0)) > VERSION:
            raise VaultError("il vault è stato creato con una versione più recente di Helpix: aggiornala")
        return cls(data)

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def encrypted(self) -> bool:
        return bool(self.data.get("encrypted"))

    @property
    def slots(self) -> list[dict]:
        return self.data.setdefault("slots", [])

    def count(self, kind: str) -> int:
        return sum(1 for s in self.slots if s.get("kind") == kind)

    def _aad(self, slot: dict) -> bytes:
        return f"{FORMAT}|{self.id}|{slot['id']}|{slot['kind']}".encode("utf-8")

    def add_slot(self, kind: str, secret, master: bytes, kdf: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(kind)
        if kdf is None:
            kdf = {"name": "scrypt", **SCRYPT} if kind in ("password", "code") else {"name": "hkdf"}
        slot = {"id": uuid.uuid4().hex[:12], "kind": kind, "created": int(time.time()),
                "salt": b64e(os.urandom(16)), "kdf": dict(kdf)}
        kek = derive_kek(kind, secret, slot)
        nonce = os.urandom(_NONCE)
        slot["nonce"] = b64e(nonce)
        slot["wrapped"] = b64e(_aesgcm(kek).encrypt(nonce, master, self._aad(slot)))
        self.slots.append(slot)
        return slot

    def remove_slot(self, slot_id: str) -> None:
        self.data["slots"] = [s for s in self.slots if s.get("id") != slot_id]

    def remove_kind(self, kind: str) -> int:
        before = len(self.slots)
        self.data["slots"] = [s for s in self.slots if s.get("kind") != kind]
        return before - len(self.slots)

    def open_slot(self, slot: dict, secret) -> bytes | None:
        from cryptography.exceptions import InvalidTag
        try:
            kek = derive_kek(slot["kind"], secret, slot)
            return _aesgcm(kek).decrypt(b64d(slot["nonce"]), b64d(slot["wrapped"]), self._aad(slot))
        except (InvalidTag, KeyError, ValueError):
            return None

    def unlock(self, kind: str, secret) -> tuple[bytes, dict]:
        """(chiave master, slot usato). WrongSecret se nessuno slot di quel tipo si apre con il segreto."""
        if not self.encrypted:
            raise VaultError("il vault non è cifrato")
        if kind == "recovery" and isinstance(secret, str):
            secret = parse_recovery(secret, self.id)
        for slot in self.slots:
            if slot.get("kind") != kind:
                continue
            master = self.open_slot(slot, secret)
            if master is not None:
                return master, slot
        raise WrongSecret(kind)

    def keys(self, master: bytes) -> Keys:
        return Keys(master, self.id)

    def save(self, root: str | Path) -> None:
        """Scrive l'intestazione in modo atomico, dopo averne copiato la versione precedente in .backup/."""
        root = Path(root)
        path = root / HEADER
        if path.exists():
            backups = root / BACKUP_DIR
            backups.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
            shutil.copy2(path, backups / f"helpix-vault-{stamp}.json")
            old = sorted(backups.glob("helpix-vault-*.json"))
            for extra in old[:-KEEP_BACKUPS]:
                extra.unlink(missing_ok=True)
        text = json.dumps(self.data, indent=1, ensure_ascii=False)
        atomic_write(path, text.encode("utf-8"))
        if json.loads(path.read_text(encoding="utf-8")) != self.data:  # riletta: dev'essere identica
            raise VaultError("intestazione del vault non scritta correttamente")


# ------------------------------------------------------------------ file di recupero
def recovery_text(key: bytes, vault_id: str, name: str = "") -> str:
    return (f"{RECOVERY_MAGIC} 1\n"
            "# File di recupero del vault di Helpix: chi lo possiede apre il vault.\n"
            "# Tienilo fuori dal PC (chiavetta, password manager, stampa) e mai nella cartella del vault.\n"
            f"vault: {vault_id}\n"
            f"name: {name}\n"
            f"key: {b64e(key)}\n")


def parse_recovery(text: str, vault_id: str | None = None) -> bytes:
    if RECOVERY_MAGIC not in (text or ""):
        raise WrongSecret("recovery")
    fields = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            fields[k.strip().lower()] = v.strip()
    if vault_id and fields.get("vault") and fields["vault"] != vault_id:
        raise WrongSecret("recovery: file di un altro vault")
    try:
        key = b64d(fields.get("key", ""))
    except ValueError as exc:
        raise WrongSecret("recovery") from exc
    if len(key) != 32:
        raise WrongSecret("recovery")
    return key


# ------------------------------------------------------------------ scrittura atomica
def atomic_write(path: str | Path, data: bytes, verify=None, attempts: int = 20) -> None:
    """Scrive in un file temporaneo, lo rilegge (e lo verifica con `verify(bytes)`, se c'è), poi sostituisce il
    file vero. Su Windows un file aperto da un altro programma (antivirus, editor) non si sostituisce: riprova per
    qualche secondo prima di arrendersi."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        back = tmp.read_bytes()
        if back != data or (verify is not None and not verify(back)):
            raise VaultError(f"verifica della scrittura non riuscita: {path.name}")
        for i in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == attempts - 1:
                    raise
                time.sleep(0.1 * (i + 1) if i < 5 else 0.5)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------ uso da riga di comando
def decrypt_vault(root: str | Path, keys: Keys, dest: str | Path) -> int:
    """Decifra tutti i file del vault in `dest` (stessa struttura logica). Restituisce quanti ne ha scritti."""
    root, dest = Path(root), Path(dest)
    count = 0
    for f in sorted((root / DATA_DIR).glob("*" + FILE_EXT)):
        relpath, content = keys.decrypt(f.name, f.read_bytes())
        target = (dest / relpath).resolve()
        if dest.resolve() not in target.parents:
            raise CorruptFile(f"percorso non valido: {relpath}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        count += 1
    return count


def _cli(argv: list[str]) -> int:
    import getpass
    if len(argv) != 3 or argv[0] != "decrypt":
        print("Uso: python3 vault_crypto.py decrypt <cartella del vault> <cartella di destinazione>")
        return 2
    root, dest = argv[1], argv[2]
    header = Header.load(root)
    if not header.encrypted:
        print("Il vault non è cifrato: i file sono già leggibili.")
        return 0
    print("Come vuoi aprire il vault?  1) password   2) codice usa e getta   3) file di recupero")
    choice = input("> ").strip()
    try:
        if choice == "3":
            path = input("Percorso del file di recupero: ").strip()
            master, _ = header.unlock("recovery", Path(path).read_text(encoding="utf-8"))
        elif choice == "2":
            master, _ = header.unlock("code", getpass.getpass("Codice: "))
        else:
            master, _ = header.unlock("password", getpass.getpass("Password: "))
    except WrongSecret:
        print("Non valido per questo vault.")
        return 1
    n = decrypt_vault(root, header.keys(master), dest)
    print(f"{n} file decifrati in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
