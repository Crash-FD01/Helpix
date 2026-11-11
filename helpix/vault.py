# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vault dei progetti (beta): una cartella di file Markdown, in chiaro o cifrata da Helpix.

Struttura logica (uguale nei due casi; nel vault cifrato i file stanno in `dati/` con nomi illeggibili):

    progetti/<nome>/PROJECT.md      stato attuale, incollato all'inizio di ogni chat nuova
    progetti/<nome>/INDEX.md        una riga per nota
    progetti/<nome>/note/…          una nota per salvataggio
    progetti/<nome>/file/…          dettagli
    progetti/<nome>/sessioni/…      bozze automatiche della sessione
    progetti/<nome>/.versioni/…     versioni precedenti di PROJECT.md

Qui non c'è niente di Qt: lo usano l'interfaccia, `helpix vault …` e i test. Specifica: docs/PROGETTI.md.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import vault_crypto as vc
from .vault_crypto import VaultError, WrongSecret

log = logging.getLogger(__name__)

PROJECTS = "progetti"
PROJECT_FILE = "PROJECT.md"
INDEX_FILE = "INDEX.md"
NOTES = "note"
FILES = "file"
SESSIONS = "sessioni"
VERSIONS = ".versioni"
TRASH = ".cestino"   # progetti e note eliminati: si ripristinano o si eliminano definitivamente
_INDEX_LINES = "riga-indice.txt"   # nel cestino, la riga dell'indice di una nota eliminata
KEYRING_SERVICE = "helpix-vault"
_SKIP_PLAIN = {vc.HEADER, vc.BACKUP_DIR, vc.DATA_DIR}


def default_root() -> Path:
    from .system import data_dir
    return data_dir() / "vault"


def in_onedrive(path: str | Path) -> bool:
    """Cartella dentro OneDrive (conflitti di sincronizzazione e file «solo online»)."""
    p = str(Path(path).expanduser())
    roots = [os.environ.get(v) for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    if any(r and p.lower().startswith(r.lower()) for r in roots):
        return True
    return any(part.lower().startswith("onedrive") for part in Path(p).parts)


def slugify(name: str, limit: int = 60) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit].strip("-") or "progetto"


def clean_relpath(rel: str) -> str:
    """Percorso logico sicuro: relativo, con «/», senza «..» né parti vuote."""
    rel = (rel or "").replace("\\", "/").strip("/")
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ("..", ".", "") or ":" in p for p in parts):
        raise VaultError(f"percorso non valido: {rel!r}")
    return "/".join(parts)


# ------------------------------------------------------------------ archivi
class PlainStore:
    """File in chiaro nella cartella del vault."""

    encrypted = False

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, rel: str) -> Path:
        rel = clean_relpath(rel)
        if rel.split("/")[0] in _SKIP_PLAIN:
            raise VaultError(f"percorso riservato: {rel}")
        return self.root / rel

    def read(self, rel: str) -> bytes:
        try:
            return self._path(rel).read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(rel) from exc

    def exists(self, rel: str) -> bool:
        return self._path(rel).is_file()

    def write(self, rel: str, data: bytes) -> None:
        vc.atomic_write(self._path(rel), data)

    def delete(self, rel: str) -> None:
        self._path(rel).unlink(missing_ok=True)

    def list(self, prefix: str = "") -> list[str]:
        out = []
        if not self.root.exists():
            return out
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root)
            if rel_dir == Path("."):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_PLAIN]
            for f in filenames:
                if f.startswith(".") and f.endswith(".tmp"):
                    continue
                rel = (rel_dir / f).as_posix() if rel_dir != Path(".") else f
                if rel in _SKIP_PLAIN or rel.split("/")[0] in _SKIP_PLAIN:
                    continue
                try:  # nomi messi da fuori che il vault non sa gestire (es. con «:»): li ignoro
                    clean_relpath(rel)
                except VaultError:
                    continue
                if rel.startswith(prefix):
                    out.append(rel)
        return sorted(out)


class EncryptedStore:
    """File cifrati in `dati/`: l'elenco si ricostruisce decifrandoli (nessun indice centrale da perdere)."""

    encrypted = True

    def __init__(self, root: Path, keys: vc.Keys):
        self.root = Path(root)
        self.keys = keys
        self.dir = self.root / vc.DATA_DIR
        self._cache: dict[str, bytes] = {}
        self.damaged: list[str] = []
        self._scan()

    def _scan(self) -> None:
        self._cache.clear()
        self.damaged = []
        if not self.dir.exists():
            return
        for f in sorted(self.dir.glob("*" + vc.FILE_EXT)):
            try:
                rel, content = self.keys.decrypt(f.name, f.read_bytes())
                self._cache[clean_relpath(rel)] = content
            except (vc.CorruptFile, VaultError, OSError) as exc:
                log.warning("File del vault illeggibile: %s (%s)", f.name, exc)
                self.damaged.append(f.name)

    def read(self, rel: str) -> bytes:
        return self._cache[clean_relpath(rel)]

    def exists(self, rel: str) -> bool:
        return clean_relpath(rel) in self._cache

    def write(self, rel: str, data: bytes) -> None:
        rel = clean_relpath(rel)
        name, blob = self.keys.encrypt(rel, data)
        vc.atomic_write(self.dir / name, blob, verify=lambda b: self.keys.decrypt(name, b) == (rel, data))
        self._cache[rel] = data

    def delete(self, rel: str) -> None:
        rel = clean_relpath(rel)
        (self.dir / (self.keys.opaque_name(rel) + vc.FILE_EXT)).unlink(missing_ok=True)
        self._cache.pop(rel, None)

    def list(self, prefix: str = "") -> list[str]:
        return sorted(r for r in self._cache if r.startswith(prefix))

    def wipe(self) -> None:
        """Toglie dalla memoria contenuti e chiavi (blocco del vault)."""
        self._cache.clear()
        self.keys = None


# ------------------------------------------------------------------ portachiavi
def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        if isinstance(backend, fail.Keyring) or "null" in name or "plaintext" in name:
            return None
        return keyring
    except Exception:  # noqa: BLE001 - keyring può fallire in molti modi
        return None


def keyring_available() -> bool:
    return _keyring() is not None


# ------------------------------------------------------------------ il vault
@dataclass
class TrashItem:
    id: str
    kind: str        # "project" o "note"
    name: str
    deleted: float
    files: list


@dataclass
class ProjectInfo:
    slug: str
    name: str
    updated: float


@dataclass
class ImportItem:
    slug: str      # cartella del progetto nel vault di origine
    name: str
    files: int
    action: str    # "new" entra così; "same" c'è già uguale (si salta); "copy" stesso nome, entra come copia
    target: str    # cartella nel vault di destinazione


class Vault:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else default_root()
        self.header: vc.Header | None = None
        self.store: PlainStore | EncryptedStore | None = None
        self._master: bytes | None = None
        self.reload()

    # --- stato
    def reload(self) -> None:
        try:
            self.header = vc.Header.load(self.root)
        except FileNotFoundError:
            self.header = None
        if self.header and not self.header.encrypted:
            self.store = PlainStore(self.root)

    @property
    def exists(self) -> bool:
        return self.header is not None

    @property
    def encrypted(self) -> bool:
        return bool(self.header and self.header.encrypted)

    @property
    def is_open(self) -> bool:
        return self.store is not None

    @property
    def name(self) -> str:
        return (self.header.data.get("name") if self.header else "") or "Vault"

    def _need_open(self) -> None:
        if not self.is_open:
            raise VaultError("vault bloccato")

    def _need_encrypted_open(self) -> None:
        self._need_open()
        if not self.encrypted or self._master is None:
            raise VaultError("il vault non è cifrato")

    # --- creazione e apertura
    def create_plain(self, name: str = "") -> None:
        if self.exists:
            raise VaultError("c'è già un vault in questa cartella")
        self.root.mkdir(parents=True, exist_ok=True)
        self.header = vc.Header.new_plain(name)
        self.header.save(self.root)
        self.store = PlainStore(self.root)

    def ensure(self, name: str = "") -> None:
        """Crea un vault in chiaro se la cartella non ne ha uno."""
        if not self.exists:
            self.create_plain(name)

    def create_encrypted(self, password: str, codes: list[str], recovery: bool = False, name: str = "") -> str | None:
        """Vault cifrato nuovo, oppure cifratura di quello in chiaro esistente (i file vengono cifrati, verificati e
        solo alla fine tolti in chiaro). Restituisce il testo del file di recupero, se chiesto."""
        if self.encrypted:
            raise VaultError("il vault è già cifrato")
        old_plain = self.store if (self.exists and not self.encrypted) else None
        name = name or (self.header.data.get("name", "") if self.header else "")
        header, master = vc.Header.new_encrypted(name, vault_id=self.header.id if self.header else None)
        header.add_slot("password", password, master)
        for c in codes:
            header.add_slot("code", c, master)
        text = None
        if recovery:
            key = os.urandom(32)
            header.add_slot("recovery", key, master)
            text = vc.recovery_text(key, header.id, name)
        self.root.mkdir(parents=True, exist_ok=True)
        data_dir = self.root / vc.DATA_DIR
        if data_dir.exists():  # resti di una cifratura interrotta prima di scrivere l'intestazione: illeggibili
            shutil.rmtree(data_dir)
        store = EncryptedStore(self.root, header.keys(master))
        files = old_plain.list() if old_plain else []
        for rel in files:
            store.write(rel, old_plain.read(rel))
        check = EncryptedStore(self.root, header.keys(master))  # verifica: rilette da disco tutte uguali
        for rel in files:
            if not check.exists(rel) or check.read(rel) != old_plain.read(rel):
                raise VaultError(f"verifica della cifratura non riuscita: {rel}")
        header.save(self.root)
        self.header, self.store, self._master = header, store, master
        self._remove_plain_copies()
        return text

    def _remove_plain_copies(self) -> int:
        """Cancella le copie in chiaro rimaste dopo la cifratura (anche se era stata interrotta)."""
        if not self.encrypted or not isinstance(self.store, EncryptedStore):
            return 0
        plain = PlainStore(self.root)
        removed = 0
        for rel in plain.list():
            if self.store.exists(rel) and self.store.read(rel) == plain.read(rel):
                plain.delete(rel)
                removed += 1
            elif not self.store.exists(rel):
                self.store.write(rel, plain.read(rel))
                plain.delete(rel)
                removed += 1
        for dirpath, _dirs, _files in os.walk(self.root / PROJECTS, topdown=False):
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass
        return removed

    def unlock(self, kind: str, secret) -> dict:
        """Apre il vault cifrato. Con un codice usa e getta, quel codice viene annullato.

        Restituisce {"kind", "codes_left", "used_code"}; WrongSecret se il segreto non va."""
        if not self.encrypted:
            raise VaultError("il vault non è cifrato")
        master, slot = self.header.unlock(kind, secret)
        self._master = master
        self.store = EncryptedStore(self.root, self.header.keys(master))
        used = False
        if kind == "code":
            self.header.remove_slot(slot["id"])
            self.header.save(self.root)
            used = True
        self._remove_plain_copies()
        return {"kind": kind, "codes_left": self.header.count("code"), "used_code": used,
                "damaged": list(self.store.damaged)}

    def unlock_keyring(self) -> dict:
        kr = _keyring()
        if not kr or not self.header:
            raise WrongSecret("keyring")
        value = kr.get_password(KEYRING_SERVICE, self.header.id)
        if not value:
            raise WrongSecret("keyring")
        return self.unlock("keyring", vc.b64d(value))

    def lock(self) -> None:
        if isinstance(self.store, EncryptedStore):
            self.store.wipe()
            self.store = None
        self._master = None

    # --- gestione delle chiavi (vault aperto)
    def change_password(self, new_password: str) -> None:
        self._need_encrypted_open()
        self.header.remove_kind("password")
        self.header.add_slot("password", new_password, self._master)
        self.header.save(self.root)

    def regenerate_codes(self, codes: list[str]) -> None:
        self._need_encrypted_open()
        self.header.remove_kind("code")
        for c in codes:
            self.header.add_slot("code", c, self._master)
        self.header.save(self.root)

    def codes_left(self) -> int:
        return self.header.count("code") if self.encrypted else 0

    def has_recovery(self) -> bool:
        return bool(self.encrypted and self.header.count("recovery"))

    def create_recovery(self) -> str:
        """Nuovo file di recupero (annulla quello precedente)."""
        self._need_encrypted_open()
        key = os.urandom(32)
        self.header.remove_kind("recovery")
        self.header.add_slot("recovery", key, self._master)
        self.header.save(self.root)
        return vc.recovery_text(key, self.header.id, self.name)

    def revoke_recovery(self) -> None:
        self._need_encrypted_open()
        self.header.remove_kind("recovery")
        self.header.save(self.root)

    def keyring_enabled(self) -> bool:
        return bool(self.encrypted and self.header.count("keyring"))

    def enable_keyring(self) -> None:
        self._need_encrypted_open()
        kr = _keyring()
        if not kr:
            raise VaultError("portachiavi di sistema non disponibile")
        key = os.urandom(32)
        kr.set_password(KEYRING_SERVICE, self.header.id, vc.b64e(key))
        self.header.remove_kind("keyring")
        self.header.add_slot("keyring", key, self._master)
        self.header.save(self.root)

    def disable_keyring(self) -> None:
        self._need_encrypted_open()
        self.header.remove_kind("keyring")
        self.header.save(self.root)
        kr = _keyring()
        if kr:
            try:
                kr.delete_password(KEYRING_SERVICE, self.header.id)
            except Exception:  # noqa: BLE001 - già assente
                pass

    def export_plain(self, dest: str | Path) -> int:
        """Copia il vault, decifrato, in una cartella nuova o vuota (un vault in chiaro valido)."""
        self._need_open()
        dest = Path(dest)
        if dest.resolve() == self.root.resolve() or self.root.resolve() in dest.resolve().parents:
            raise VaultError("scegli una cartella fuori dal vault")
        if dest.exists() and any(dest.iterdir()):
            raise VaultError("la cartella di destinazione non è vuota")
        dest.mkdir(parents=True, exist_ok=True)
        out = PlainStore(dest)
        files = self.store.list()
        for rel in files:
            out.write(rel, self.store.read(rel))
        vc.Header.new_plain(self.name).save(dest)
        return len(files)

    # --- importazione (da un'esportazione, da un altro vault in chiaro o cifrato)
    @classmethod
    def open_source(cls, path: str | Path) -> "Vault":
        """Il vault da cui importare: un vault di Helpix (anche cifrato: va sbloccato prima di leggerlo) o una
        cartella con `progetti/<nome>/PROJECT.md` senza intestazione (es. copiata a mano o da Obsidian)."""
        root = Path(path)
        if not root.is_dir():
            raise VaultError("la cartella non esiste")
        src = cls(root)
        if src.exists:
            return src
        bare = PlainStore(root)
        if any(len(r.split("/")) == 3 and r.endswith("/" + PROJECT_FILE) for r in bare.list(PROJECTS + "/")):
            src.store = bare
            return src
        raise VaultError("nella cartella non c'è un vault di Helpix")

    def import_plan(self, src: "Vault") -> list[ImportItem]:
        """Cosa farebbe l'importazione, senza toccare niente. Non sovrascrive mai: un progetto con lo stesso
        nome di cartella ma contenuto diverso entra come copia («… (importato)»), uno identico si salta."""
        self._need_open()
        if not src.is_open:
            raise VaultError("il vault da importare è bloccato")
        a, b = self.root.resolve(), src.root.resolve()
        if a == b or a in b.parents or b in a.parents:
            raise VaultError("scegli una cartella fuori da questo vault")
        taken = {i.slug for i in self.projects()}
        items = []
        for info in src.projects():
            files = src.store.list(f"{PROJECTS}/{info.slug}/")
            action, target = "new", info.slug
            if info.slug in taken:
                mine = self.store.list(f"{PROJECTS}/{info.slug}/")
                if mine == files and all(self.store.read(r) == src.store.read(r) for r in files):
                    action = "same"
                else:
                    action, n = "copy", 2
                    target = f"{info.slug}-importato"
                    while target in taken:
                        target, n = f"{info.slug}-importato-{n}", n + 1
            taken.add(target)
            items.append(ImportItem(info.slug, info.name, len(files), action, target))
        return items

    def import_projects(self, src: "Vault", items: list[ImportItem] | None = None, label: str = "importato") -> int:
        """Copia i progetti del piano (tutti i file: note, file, bozze, versioni) nel vault, cifrandoli se
        questo vault è cifrato; le copie prendono «(label)» nel nome. Ogni file si rilegge dopo averlo scritto; se un progetto non entra tutto, i suoi
        file già scritti si tolgono. Restituisce il numero di progetti importati."""
        items = self.import_plan(src) if items is None else items
        done = 0
        for it in items:
            if it.action == "same":
                continue
            src_prefix, dst_prefix = f"{PROJECTS}/{it.slug}/", f"{PROJECTS}/{it.target}/"
            if self.store.list(dst_prefix):
                raise VaultError(f"la cartella del progetto esiste già: {it.target}")
            written = []
            try:
                for rel in src.store.list(src_prefix):
                    data = src.store.read(rel)
                    dst = dst_prefix + rel[len(src_prefix):]
                    self.store.write(dst, data)
                    written.append(dst)
                    if self.store.read(dst) != data:
                        raise VaultError(f"copia non riuscita: {rel}")
                if it.action == "copy":
                    self.rename_project(it.target, f"{it.name} ({label})")
            except Exception:
                for rel in written:
                    self.store.delete(rel)
                self._prune_dirs()
                raise
            done += 1
            log.info("Progetto importato nel vault: %s -> %s (%d file)", it.slug, it.target, len(written))
        return done

    # --- progetti
    def projects(self) -> list[ProjectInfo]:
        self._need_open()
        out = []
        for rel in self.store.list(PROJECTS + "/"):
            parts = rel.split("/")
            if len(parts) == 3 and parts[2] == PROJECT_FILE:
                p = Project(self, parts[1])
                out.append(ProjectInfo(parts[1], p.name, p.updated()))
        out.sort(key=lambda i: i.updated, reverse=True)
        return out

    def project(self, slug: str) -> "Project":
        self._need_open()
        for candidate in dict.fromkeys((slug, slugify(slug))):
            if candidate not in ("", ".", "..") and "/" not in candidate and "\\" not in candidate and self.store.exists(f"{PROJECTS}/{candidate}/{PROJECT_FILE}"):
                return Project(self, candidate)
        raise KeyError(slug)

    # --- cestino
    def _move(self, rels: list[str], src_prefix: str, dst_prefix: str) -> None:
        """Copia i file sotto un altro prefisso e solo dopo, a copie verificate, toglie gli originali."""
        moved = []
        for rel in rels:
            data = self.store.read(rel)
            dst = dst_prefix + rel[len(src_prefix):]
            self.store.write(dst, data)
            if self.store.read(dst) != data:
                raise VaultError(f"copia non riuscita: {rel}")
            moved.append(rel)
        for rel in moved:
            self.store.delete(rel)
        self._prune_dirs()

    def _prune_dirs(self) -> None:
        if isinstance(self.store, PlainStore):
            for top in (PROJECTS, TRASH):
                for dirpath, _dirs, _files in os.walk(self.root / top, topdown=False):
                    try:
                        if not os.listdir(dirpath):
                            os.rmdir(dirpath)
                    except OSError:
                        pass

    def _trash_id(self, base: str) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tid, n = f"{base}-{stamp}", 2
        while self.store.list(f"{TRASH}/{tid}/"):
            tid, n = f"{base}-{stamp}-{n}", n + 1
        return tid

    def delete_project(self, slug: str) -> str:
        """Sposta il progetto nel cestino del vault. Restituisce l'identificativo nel cestino."""
        p = self.project(slug)
        rels = self.store.list(p.rel() + "/")
        tid = self._trash_id(slugify(slug, 40))
        self._move(rels, f"{PROJECTS}/", f"{TRASH}/{tid}/{PROJECTS}/")
        return tid

    def delete_file(self, rel: str) -> str:
        """Sposta una nota o un file nel cestino (la riga dell'indice di una nota viene tolta)."""
        self._need_open()
        rel = clean_relpath(rel)
        parts = rel.split("/")
        if len(parts) < 4 or parts[0] != PROJECTS or parts[2] in (PROJECT_FILE, INDEX_FILE):
            raise VaultError("si eliminano solo note e file di un progetto")
        if not self.store.exists(rel):
            raise KeyError(rel)
        tid = self._trash_id(slugify(parts[-1].removesuffix(".md"), 40))
        if parts[2] == NOTES:  # la riga dell'indice va nel cestino con la nota, per poterla rimettere
            p = Project(self, parts[1])
            stem = parts[-1].removesuffix(".md")
            keep, gone = [], []
            for ln in p.index_text().splitlines():
                (gone if f"[[{stem}|" in ln or f"[[{stem}]]" in ln else keep).append(ln)
            if gone:
                self.store.write(f"{TRASH}/{tid}/{_INDEX_LINES}", ("\n".join(gone) + "\n").encode("utf-8"))
            p.write_text(p.rel(INDEX_FILE), "\n".join(keep).rstrip("\n") + "\n")
        self._move([rel], f"{PROJECTS}/", f"{TRASH}/{tid}/{PROJECTS}/")
        return tid

    def trash(self) -> list[TrashItem]:
        """Elementi nel cestino, dal più recente."""
        self._need_open()
        groups: dict[str, list[str]] = {}
        for rel in self.store.list(TRASH + "/"):
            parts = rel.split("/")
            if len(parts) >= 3:
                groups.setdefault(parts[1], []).append(rel)
        out = []
        for tid, all_rels in groups.items():
            rels = [r for r in all_rels if not r.endswith("/" + _INDEX_LINES)] or all_rels
            inner = [r[len(f"{TRASH}/{tid}/"):] for r in rels]
            project_md = next((r for r in rels if r.endswith(f"/{PROJECT_FILE}") and r.count("/") == 4), None)
            if project_md:
                kind = "project"
                name = _title(self.store.read(project_md).decode("utf-8", "replace")) or inner[0].split("/")[1]
            else:
                kind = "note"
                name = _title(self.store.read(rels[0]).decode("utf-8", "replace")) or inner[0].rsplit("/", 1)[-1]
                proj = inner[0].split("/")[1] if inner[0].count("/") >= 2 else ""
                try:
                    pname = Project(self, proj).name if self.store.exists(f"{PROJECTS}/{proj}/{PROJECT_FILE}") else proj
                except VaultError:
                    pname = proj
                name = f"{name} ({pname})" if pname else name
            m = re.search(r"(\d{8})-(\d{6})", tid)
            stamp = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")) if m else 0.0
            out.append(TrashItem(tid, kind, name, stamp, sorted(all_rels)))
        out.sort(key=lambda t: t.deleted, reverse=True)
        return out

    def restore(self, tid: str) -> list[str]:
        """Rimette al loro posto i file di un elemento del cestino. VaultError se qualcosa con lo stesso nome c'è
        già (un progetto ricreato nel frattempo, per esempio)."""
        self._need_open()
        prefix = f"{TRASH}/{clean_relpath(tid)}/"
        index_rel = prefix + _INDEX_LINES
        rels = [r for r in self.store.list(prefix) if r != index_rel]
        if not rels:
            raise KeyError(tid)
        targets = [r[len(prefix):] for r in rels]
        clash = [t for t in targets if self.store.exists(t)]
        if clash:
            raise VaultError("esiste già: " + clash[0])
        self._move(rels, prefix, "")
        if self.store.exists(index_rel):  # nota ripristinata: torna anche la sua riga nell'indice
            parts = targets[0].split("/")
            if len(parts) >= 2 and self.store.exists(f"{PROJECTS}/{parts[1]}/{PROJECT_FILE}"):
                p = Project(self, parts[1])
                lines = self.store.read(index_rel).decode("utf-8", "replace").strip("\n")
                index = p.index_text().rstrip("\n") + "\n"
                if not any(ln.strip().startswith("- ") for ln in index.splitlines()):
                    index += "\n"  # riga vuota tra il titolo e la prima nota, come in add_note
                p.write_text(p.rel(INDEX_FILE), index + lines + "\n")
            self.store.delete(index_rel)
            self._prune_dirs()
        return targets

    def purge(self, tid: str | None = None) -> int:
        """Elimina definitivamente un elemento del cestino (o tutto il cestino con tid=None)."""
        self._need_open()
        prefix = f"{TRASH}/" + (f"{clean_relpath(tid)}/" if tid else "")
        rels = self.store.list(prefix)
        for rel in rels:
            self.store.delete(rel)
        self._prune_dirs()
        return len(rels)

    def rename_project(self, slug: str, name: str) -> None:
        """Cambia il nome mostrato (il «# titolo» di PROJECT.md); la cartella resta la stessa."""
        name = " ".join((name or "").split())
        if not name:
            raise VaultError("nome vuoto")
        p = self.project(slug)
        lines = p.text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith("# "):
                lines[i] = f"# {name}"
                break
        else:
            lines = [f"# {name}", ""] + lines
        p.save_text("\n".join(lines).rstrip("\n") + "\n")

    def create_project(self, name: str, text: str) -> "Project":
        self._need_open()
        base = slugify(name)
        slug, n = base, 2
        while self.store.exists(f"{PROJECTS}/{slug}/{PROJECT_FILE}"):
            slug, n = f"{base}-{n}", n + 1
        p = Project(self, slug)
        self.store.write(p.rel(PROJECT_FILE), text.encode("utf-8"))
        self.store.write(p.rel(INDEX_FILE), f"# Indice — {name}\n\n".encode("utf-8"))
        return p


def _title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


_NOTE_LINE = re.compile(r"^-\s*(\d{4}-\d{2}-\d{2})\s*·\s*\[\[([^|\]]+)(?:\|([^\]]+))?\]\]\s*(?:—\s*(.*))?$")


_WIKILINK = re.compile(r"!?\[\[([^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")


@dataclass
class GraphNode:
    rel: str           # identificativo: percorso per note e stato, «start», «dec:…», «step:…»
    kind: str          # "start", "note", "decision", "state", "step"
    title: str
    date: str
    summary: str
    in_context: bool   # va all'IA all'inizio di una chat nuova
    open_rel: str = "" # cosa apre un clic
    status: str = ""   # decisioni: "in_force", "superseded" (sostituita), "removed" (tolta senza sostituto)
    files: list[str] = field(default_factory=list)   # note: file citati con [[…]]
    origin: str = ""   # decisioni: nodo della sessione in cui è nata
    replaced_by: str = ""
    until: str = ""    # decisioni superate: data della sessione che le ha sostituite


@dataclass
class GraphEdge:
    src: str
    dst: str
    kind: str          # "next" (tempo), "decided" (sessione → decisione), "replaced" (superata → nuova),
                       # "step" (stato → prossimo passo), "link" ([[…]] tra note)


@dataclass
class Graph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    def node(self, rel: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.rel == rel), None)

    def neighbours(self, rel: str) -> set[str]:
        return {e.dst if e.src == rel else e.src for e in self.edges if rel in (e.src, e.dst)}


@dataclass
class NoteInfo:
    rel: str
    stem: str
    title: str
    date: str
    summary: str


class Project:
    def __init__(self, vault: Vault, slug: str):
        self.vault = vault
        self.slug = slug

    @property
    def store(self):
        self.vault._need_open()
        return self.vault.store

    def rel(self, *parts: str) -> str:
        return "/".join((PROJECTS, self.slug) + parts)

    def read_text(self, rel: str) -> str:
        return self.store.read(rel).decode("utf-8", "replace")

    def write_text(self, rel: str, text: str) -> None:
        self.store.write(rel, text.encode("utf-8"))

    # --- PROJECT.md
    def text(self) -> str:
        return self.read_text(self.rel(PROJECT_FILE))

    @property
    def name(self) -> str:
        try:
            for line in self.text().splitlines():
                if line.startswith("# "):
                    return line[2:].strip() or self.slug
        except KeyError:
            pass
        return self.slug

    def updated(self) -> float:
        stamps = [self._stamp(r) for r in self.store.list(self.rel(VERSIONS) + "/")]
        stamps += [self._stamp(r) for r in self.store.list(self.rel(NOTES) + "/")]
        if isinstance(self.store, PlainStore):  # nel vault cifrato le date dei file non dicono niente
            try:
                stamps.append(self.store._path(self.rel(PROJECT_FILE)).stat().st_mtime)
            except OSError:
                pass
        return max([s for s in stamps if s] or [0.0])

    @staticmethod
    def _stamp(rel: str) -> float:
        m = re.search(r"(\d{8})-(\d{6})", rel) or re.search(r"(\d{4})-(\d{2})-(\d{2})", rel)
        if not m:
            return 0.0
        try:
            if len(m.groups()) == 2:
                return time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
            return time.mktime(time.strptime("".join(m.groups()), "%Y%m%d"))
        except ValueError:
            return 0.0

    def save_text(self, text: str, keep: int = 20) -> str | None:
        """Scrive PROJECT.md; la versione precedente va in .versioni/ (le ultime `keep`). Restituisce il percorso
        della versione salvata (per «Annulla»)."""
        saved = None
        try:
            old = self.text()
        except KeyError:
            old = None
        if old is not None and old != text:
            # microsecondi nel nome: l'ordine alfabetico è quello cronologico anche per più salvataggi al secondo
            while True:
                stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{(time.time_ns() // 1000) % 1_000_000:06d}"
                saved = self.rel(VERSIONS, f"PROJECT-{stamp}.md")
                if not self.store.exists(saved):
                    break
            self.write_text(saved, old)
            for extra in self.versions()[keep:]:
                self.store.delete(extra)
        self.write_text(self.rel(PROJECT_FILE), text)
        return saved

    def versions(self) -> list[str]:
        """Versioni precedenti, dalla più recente."""
        return sorted(self.store.list(self.rel(VERSIONS) + "/"), reverse=True)

    def restore_version(self, rel: str) -> None:
        self.save_text(self.read_text(rel))

    # --- note e indice
    def index_text(self) -> str:
        try:
            return self.read_text(self.rel(INDEX_FILE))
        except KeyError:
            return f"# Indice — {self.name}\n\n"

    def notes(self) -> list[NoteInfo]:
        """Note in ordine di indice (dalla più vecchia); anche quelle senza riga nell'indice."""
        out: list[NoteInfo] = []
        seen = set()
        for line in self.index_text().splitlines():
            m = _NOTE_LINE.match(line.strip())
            if not m:
                continue
            stem = m.group(2).strip()
            rel = self.rel(NOTES, stem + ".md")
            seen.add(rel)
            out.append(NoteInfo(rel, stem, (m.group(3) or stem).strip(), m.group(1), (m.group(4) or "").strip()))
        for rel in self.store.list(self.rel(NOTES) + "/"):
            if rel not in seen:
                stem = rel.rsplit("/", 1)[1][:-3] if rel.endswith(".md") else rel.rsplit("/", 1)[1]
                date = stem[:10] if re.match(r"\d{4}-\d{2}-\d{2}", stem) else ""
                out.append(NoteInfo(rel, stem, self._note_title(rel) or stem, date, ""))
        return out

    def _note_title(self, rel: str) -> str:
        try:
            for line in self.read_text(rel).splitlines():
                if line.startswith("# "):
                    return line[2:].strip()
        except KeyError:
            pass
        return ""

    def add_note(self, title: str, text: str, summary: str = "", date: str | None = None) -> str:
        date = date or time.strftime("%Y-%m-%d")
        base = f"{date}-{slugify(title, 50)}"
        stem, n = base, 2
        while self.store.exists(self.rel(NOTES, stem + ".md")):
            stem, n = f"{base}-{n}", n + 1
        rel = self.rel(NOTES, stem + ".md")
        self.write_text(rel, text)
        index = self.index_text().rstrip("\n") + "\n"
        if not any(ln.strip().startswith("- ") for ln in index.splitlines()):
            index += "\n"  # riga vuota tra il titolo e la prima nota
        line = f"- {date} · [[{stem}|{title.strip()}]]" + (f" — {summary.strip()}" if summary.strip() else "")
        self.write_text(self.rel(INDEX_FILE), index + line + "\n")
        return rel

    def delete_note(self, rel: str) -> None:
        """Toglie una nota e la sua riga dall'indice (serve ad «Annulla» dopo un aggiornamento automatico)."""
        stem = rel.rsplit("/", 1)[1][:-3]
        self.store.delete(rel)
        lines = [ln for ln in self.index_text().splitlines() if f"[[{stem}|" not in ln and f"[[{stem}]]" not in ln]
        self.write_text(self.rel(INDEX_FILE), "\n".join(lines).rstrip("\n") + "\n")

    def files(self) -> list[str]:
        return self.store.list(self.rel(FILES) + "/")

    def all_files(self) -> list[str]:
        return [r for r in self.store.list(self.rel() + "/") if f"/{VERSIONS}/" not in r]

    def resolve(self, name: str) -> str | None:
        """Percorso di una nota o di un file a partire da quello che scrive l'IA: titolo, nome del file, data e
        titolo, «PROJECT.md», «INDEX.md», «file/x». Prima corrispondenza esatta, poi la più simile."""
        q = (name or "").strip().strip("«»\"'`[]").strip()
        if "|" in q:
            q = q.split("|", 1)[0]
        if not q:
            return None
        low = q.lower()
        for special in (PROJECT_FILE, INDEX_FILE):
            if low in (special.lower(), special[:-3].lower()):
                return self.rel(special)
        candidates = self.all_files()
        for rel in candidates:
            tail = rel[len(self.rel()) + 1:]
            if low in (tail.lower(), tail.lower().removesuffix(".md")):
                return rel
        notes = self.notes()
        for n in notes:
            if low in (n.stem.lower(), n.title.lower(), f"{n.date} {n.title}".lower(), f"{n.date} · {n.title}".lower()):
                return n.rel
        key = slugify(q)
        best, score = None, 0.0
        from difflib import SequenceMatcher
        for n in notes:
            for cand in (slugify(n.title), n.stem, slugify(f"{n.date} {n.title}")):
                s = 1.0 if key and key in cand else SequenceMatcher(None, key, cand).ratio()
                if s > score:
                    best, score = n.rel, s
        return best if score >= 0.6 else None

    def search(self, query: str, limit: int = 30) -> list[tuple[str, str]]:
        """(nota, riga) che contengono tutte le parole cercate (maiuscole e accenti non contano)."""
        def norm(t: str) -> str:
            return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()
        words = [w for w in norm(query).split() if w]
        if not words:
            return []
        out = []
        for rel in self.all_files():
            if f"/{SESSIONS}/" in rel:
                continue
            try:
                text = self.read_text(rel)
            except KeyError:
                continue
            for line in text.splitlines():
                n = norm(line)
                if all(w in n for w in words):
                    out.append((rel, line.strip()))
                    if len(out) >= limit:
                        return out
        return out

    def backlinks(self, rel: str) -> list[str]:
        """Note che citano `rel` con un link [[…]]."""
        stem = rel.rsplit("/", 1)[1].removesuffix(".md")
        rx = re.compile(r"\[\[" + re.escape(stem) + r"(\||\]\])")
        out = []
        for other in self.all_files():
            # l'indice cita tutte le note: non dice niente
            if other == rel or not other.endswith(".md") or other == self.rel(INDEX_FILE):
                continue
            try:
                if rx.search(self.read_text(other)):
                    out.append(other)
            except KeyError:
                continue
        return out

    def graph(self, recent: int = 3) -> "Graph":
        """Mappa delle decisioni del progetto, per la vista Grafo.

        Linea del tempo: «Inizio» → sessioni (le note, in ordine di indice) → stato attuale (PROJECT.md).
        Accanto a ogni sessione le decisioni nate lì: in vigore (da «Decisioni in vigore») o superate (dalle note,
        «Decisioni superate»), con la freccia verso quella che l'ha sostituita. Accanto allo stato i prossimi passi.
        In più i link [[…]] tra le note e, come numero sulla nota, i file che cita.

        Dove è nata una decisione: la nota che la elenca in «Decisioni prese» o come nuova in «Decisioni superate»;
        altrimenti la nota dello stesso giorno (l'ultima), altrimenti l'ultima nota precedente; altrimenti «Inizio».
        Tutto viene da file che ci sono già: niente IA, niente token."""
        from . import project as pj
        notes = self.notes()
        in_ctx = {n.rel for n in notes[-recent:]} if recent else set()
        proj_rel = self.rel(PROJECT_FILE)
        try:
            proj_text = self.text()
        except KeyError:
            proj_text = ""
        versions = self.versions()
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        start = GraphNode("start", "start", "Inizio", "", "", False, versions[-1] if versions else proj_rel)
        nodes.append(start)
        texts: dict[str, str] = {}
        for n in notes:
            try:
                texts[n.rel] = self.read_text(n.rel)
            except KeyError:
                texts[n.rel] = ""
        # file citati da ogni nota: diventano un numero sulla nota (meno nodi, stesso significato)
        file_keys: dict[str, str] = {}
        for rel in self.files():
            tail = rel[len(self.rel()) + 1:]
            stem = tail.rsplit("/", 1)[-1]
            for k in (tail, tail.removesuffix(".md"), stem, stem.removesuffix(".md")):
                file_keys.setdefault(k.lower(), rel)
        note_keys: dict[str, str] = {}
        for n in notes:
            for k in (n.stem, n.title, f"note/{n.stem}"):
                note_keys.setdefault(k.strip().lower(), n.rel)
        links: list[tuple[str, str]] = []
        for n in notes:
            files, seen_f = [], set()
            for m in _WIKILINK.finditer(texts[n.rel]):
                key = m.group(1).strip().lower()
                if key in file_keys and file_keys[key] not in seen_f:
                    seen_f.add(file_keys[key])
                    files.append(file_keys[key][len(self.rel(FILES)) + 1:])
                elif key in note_keys and note_keys[key] != n.rel:
                    links.append((n.rel, note_keys[key]))
            nodes.append(GraphNode(n.rel, "note", n.title, n.date, n.summary, n.rel in in_ctx, n.rel,
                                   files=files))
        state_lines = pj.section_lines(proj_text, "status")
        nodes.append(GraphNode(proj_rel, "state", self.name, "", " ".join(state_lines), True, proj_rel))
        timeline = ["start"] + [n.rel for n in notes] + [proj_rel]
        for a, b in zip(timeline, timeline[1:]):
            edges.append(GraphEdge(a, b, "next"))

        # decisioni: chi le ha prese
        taken: dict[str, str] = {}          # chiave della decisione -> nota
        replaced: list[tuple[str, str, str]] = []   # (vecchia, nuova, nota)
        for n in notes:
            added, sup = pj.note_decisions(texts[n.rel])
            for d in added:
                taken.setdefault(pj.decision_key(d), n.rel)
            for old, new in sup:
                taken.setdefault(pj.decision_key(new), n.rel)
                replaced.append((old, new, n.rel))

        def origin(key: str, date: str) -> str:
            if key in taken:
                return taken[key]
            if date:
                same = [n.rel for n in notes if n.date == date]
                if same:
                    return same[-1]
                before = [n.rel for n in notes if n.date and n.date <= date]
                if before:
                    return before[-1]
            return "start"
        dec: dict[str, GraphNode] = {}
        for date, text in pj.decisions_in_force(proj_text):
            key = pj.decision_key(text)
            if not key or key in dec:
                continue
            node = GraphNode(f"dec:{key}", "decision", text, date, "", True, "", status="in_force")
            node.origin = origin(key, date)
            dec[key] = node
        for old, new, note_rel in replaced:
            ko, kn = pj.decision_key(old), pj.decision_key(new)
            if not ko or not kn:
                continue
            if ko not in dec:   # superata: resta solo nella nota che l'ha sostituita
                node = GraphNode(f"dec:{ko}", "decision", old, "", "", False, "", status="superseded")
                node.origin = origin(ko, "")
                if node.origin == note_rel:   # nata e superata nella stessa sessione: la metto prima
                    node.origin = next((t for t, nx in zip(timeline, timeline[1:]) if nx == note_rel), "start")
                dec[ko] = node
            elif dec[ko].status == "in_force":
                continue   # torna in vigore più avanti: niente freccia all'indietro
            if kn not in dec:   # la nuova è stata superata a sua volta o tolta a mano
                node = GraphNode(f"dec:{kn}", "decision", new, "", "", False, "", status="superseded")
                node.origin = note_rel
                dec[kn] = node
            dec[ko].replaced_by = dec[kn].rel
            dec[ko].until = next((n.date for n in notes if n.rel == note_rel), "")
        dates = {n.rel: n.date for n in notes}
        for node in dec.values():
            node.date = node.date or dates.get(node.origin, "")   # le superate perdono la data: quella della sessione
            node.open_rel = node.origin if node.origin != "start" else start.open_rel
            if node.status == "superseded" and not node.replaced_by:
                node.status = "removed"
            nodes.append(node)
            edges.append(GraphEdge(node.origin, node.rel, "decided"))
            if node.replaced_by:
                edges.append(GraphEdge(node.rel, node.replaced_by, "replaced"))
        # prossimi passi, accanto allo stato attuale
        for i, step in enumerate(pj.section_lines(proj_text, "next")):
            nodes.append(GraphNode(f"step:{i}", "step", step, "", "", True, proj_rel))
            edges.append(GraphEdge(proj_rel, f"step:{i}", "step"))
        seen = {(e.src, e.dst) for e in edges}
        for a, b in links:
            if (a, b) not in seen and (b, a) not in seen:
                seen.add((a, b))
                edges.append(GraphEdge(a, b, "link"))
        return Graph(nodes, edges)

    def write_session_draft(self, session_id: str, text: str) -> str:
        rel = self.rel(SESSIONS, f"{slugify(session_id, 40)}.md")
        try:
            if self.read_text(rel) == text:
                return rel
        except KeyError:
            pass
        self.write_text(rel, text)
        return rel
