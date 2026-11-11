# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progetti e vault (beta): archivio, cifratura, recupero, aggiornamenti dei progetti (python tests/test_vault.py).

Senza Qt: è la parte che non deve mai perdere dati. scrypt usa parametri bassi per far girare i test in fretta;
il valore vero è controllato a parte.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hardexit  # noqa: E402 - uscita immediata anche su Windows
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")

from helpix import passwords, project as pj, vault_crypto as vc  # noqa: E402
from helpix.i18n import set_language  # noqa: E402
from helpix.session import Message, Session  # noqa: E402
from helpix.vault import EncryptedStore, PlainStore, Vault, VaultError, WrongSecret, clean_relpath, in_onedrive  # noqa: E402

set_language("it")
REAL_SCRYPT = dict(vc.SCRYPT)
vc.SCRYPT = {"n": 2 ** 10, "r": 8, "p": 1}
PASSWORD = "una frase lunga per il vault di prova"


def new_root() -> Path:
    return Path(tempfile.mkdtemp(dir=_tmp))


def plain_vault_with_project():
    v = Vault(new_root())
    v.create_plain("Lavoro")
    p = v.create_project("Cliente Rossi — firewall", pj.template("Cliente Rossi — firewall", "VPN stabile", "XGS"))
    p.write_text(p.rel("file", "config.txt"), "set vpn …\n")
    p.add_note("Prima sessione", pj.note_text("Prima sessione", "Tunnel IPsec configurato.", "Claude"),
               "Tunnel IPsec configurato.")
    return v, p


def test_parametri_reali():
    assert REAL_SCRYPT["n"] >= 2 ** 17 and REAL_SCRYPT["r"] == 8, "scrypt del vault vero: almeno 128 MiB"


def test_percorsi_sicuri():
    for bad in ("../x", "a/../../b", "C:/x", "", "a//b/.."):
        try:
            clean_relpath(bad)
        except VaultError:
            continue
        raise AssertionError(bad)
    assert clean_relpath("progetti\\x\\PROJECT.md") == "progetti/x/PROJECT.md"
    assert clean_relpath("/etc/passwd") == "etc/passwd", "sempre dentro la cartella del vault"
    v, _ = plain_vault_with_project()
    for bad in ("helpix-vault.json", ".backup/x", "dati/x.hxv"):
        try:
            v.store.write(bad, b"x")
        except VaultError:
            continue
        raise AssertionError(bad)
    try:
        v.project("../..")
    except KeyError:
        pass
    assert in_onedrive("/home/u/OneDrive/vault") and not in_onedrive("/home/u/vault")


def test_vault_in_chiaro():
    v, p = plain_vault_with_project()
    assert (v.root / "progetti" / p.slug / "PROJECT.md").read_text(encoding="utf-8").startswith("# Cliente Rossi")
    assert [i.slug for i in v.projects()] == [p.slug]
    assert p.notes()[0].title == "Prima sessione" and p.notes()[0].summary == "Tunnel IPsec configurato."
    assert p.resolve("prima sessione") == p.notes()[0].rel
    assert p.resolve("file/config.txt").endswith("file/config.txt")
    assert p.resolve("PROJECT") == p.rel("PROJECT.md")
    assert p.resolve("argomento che non esiste affatto") is None
    assert p.search("ipsec") and all("ipsec" in line.lower() for _, line in p.search("IPSEC"))
    # file temporanei rimasti da una scrittura interrotta: non compaiono
    (v.root / "progetti" / p.slug / ".PROJECT.md.123.abc.tmp").write_text("resto", encoding="utf-8")
    assert not any(r.endswith(".tmp") for r in v.store.list())
    # file con nomi che il vault non gestisce, messi da fuori: ignorati, niente errori nella ricerca
    if os.name != "nt":
        (v.root / "progetti" / p.slug / "file" / "strano:nome.txt").write_text("ipsec", encoding="utf-8")
        assert p.search("ipsec") and not any(":" in r for r in v.store.list())
    # un altro progetto con lo stesso nome non sovrascrive il primo
    p2 = v.create_project("Cliente Rossi — firewall", "# Cliente Rossi — firewall\n")
    assert p2.slug != p.slug and len(v.projects()) == 2


def test_versioni_e_ripristino():
    v, p = plain_vault_with_project()
    first = p.text()
    for i in range(25):
        p.save_text(first + f"\nmodifica {i}\n", keep=20)
    assert len(p.versions()) == 20, len(p.versions())
    saved = p.save_text("# Cliente Rossi — firewall\n\nnuovo\n")
    assert saved and "modifica 24" in p.read_text(saved)
    p.restore_version(saved)
    assert "modifica 24" in p.text()


def test_aggiornamento_progetto():
    text = pj.template("Helpix", "App", "Python") + "Idea segreta\n"
    up = pj.parse_update("""Ecco:
```
HELPIX-PROJECT
NOTA: Struttura dei progetti
Deciso il vault. Restano da fare i test.
MODIFICHE:
+ Decisioni in vigore: Cifratura per singolo progetto
+ Prossimi passi: Scrivere i test
= Stato: Prima versione
del vault.
+ Solo per me: non dovrebbe entrare
- Riferimenti: riga che non c'è
```""")
    assert up and up.title == "Struttura dei progetti" and len(up.ops) == 5
    r = pj.apply_update(text, up, today="2026-11-07")
    assert "- 2026-11-07 Cifratura per singolo progetto" in r.text
    assert "Prima versione\ndel vault." in r.text
    assert "non dovrebbe entrare" not in r.text and "Idea segreta" in r.text
    assert len(r.warnings) == 2 and len(r.applied) == 3
    up2 = pj.parse_update("HELPIX-PROJECT\nNOTA: Cambio\nx\nMODIFICHE:\n"
                          "~ decisioni: cifratura per SINGOLO progetto. => Vault cifrato per intero\n"
                          "- prossimi passi: scrivere i test\n+ Decisioni in vigore: Vault cifrato per intero")
    r2 = pj.apply_update(r.text, up2, today="2026-11-08")
    assert "- 2026-11-08 Vault cifrato per intero" in r2.text and "singolo progetto" not in r2.text
    assert r2.superseded == [("Cifratura per singolo progetto", "Vault cifrato per intero")]
    assert "Scrivere i test" not in r2.text
    assert any("Già presente" in w for w in r2.warnings), "una decisione già scritta non si duplica"
    note = pj.note_text(up2.title, up2.body, "Claude", r2.superseded, r2.warnings, date="2026-11-08")
    assert "## Decisioni superate" in note and "→ Vault cifrato per intero" in note
    # «=» su più righe con un elenco: «- passo: dettaglio» è testo della sezione, non una modifica
    up3 = pj.parse_update("HELPIX-PROJECT\nNOTA: x\ny\nMODIFICHE:\n= Prossimi passi:\n- Failover: domani\n"
                          "- Backup: venerdì\n+ Stato: ok")
    assert [o[0] for o in up3.ops] == ["=", "+"] and "Backup: venerdì" in up3.ops[0][2]
    r4 = pj.apply_update(text, up3)
    assert "- Failover: domani\n- Backup: venerdì" in r4.text and not r4.warnings
    # la richiesta copiata per sbaglio non è un aggiornamento; il testo senza marcatore nemmeno
    assert pj.parse_update(pj.update_request(text)) is None
    assert pj.parse_update("NOTA: x\nMODIFICHE:\n+ Stato: y") is None
    # la richiesta non manda «Solo per me» all'IA
    assert "Idea segreta" not in pj.update_request(text) and "Idea segreta" not in pj.compact_request(text)
    assert "Idea segreta" not in pj.context_text("Helpix", text, "")
    # compattazione: PROJECT.md intero, «Solo per me» resta quella di prima
    full = pj.parse_update("HELPIX-PROJECT\nCOMPLETO\n## Obiettivo\nApp\n## Solo per me\nfinto\n")
    r3 = pj.apply_update(text, full)
    assert r3.text.startswith("# Helpix") and "Idea segreta" in r3.text and "finto" not in r3.text


def test_richiesta_nota():
    assert pj.parse_note_request("HELPIX-NOTA: Scelta del formato") == "Scelta del formato"
    assert pj.parse_note_request("Mi serve:\n`HELPIX-NOTA: «2026-10-28 · Qt»`") == "2026-10-28 · Qt"
    assert pj.parse_note_request("**HELPIX-NOTE: Windows**") == "Windows"
    assert pj.parse_note_request("HELPIX-NOTA: titolo della nota") is None
    assert pj.parse_note_request("niente da vedere") is None


def test_bozza_della_sessione():
    s = Session("anthropic", "m", "/tmp")
    s.messages.append(Message("user", "", kind="output", meta={"cmd": "ip a", "rc": 0, "output": "eth0 up"}))
    s.messages.append(Message("assistant", "Problema: VPN", kind="summary"))
    md = pj.session_markdown(s)
    assert "$ ip a" in md and "eth0 up" in md and "Problema: VPN" in md


def test_password_e_codici():
    assert len(passwords.words()) >= 2048 and passwords.code_bits() >= 66
    codes = passwords.generate_codes()
    assert len(codes) == 8 and len(set(codes)) == 8 and all(len(c.split("-")) == 6 for c in codes)
    for weak in ("corta", "password1234", "qwertyuiopas", "aaaaaaaaaaaaaa", "abcabcabcabc", "Juventus2024!",
                 "123456789012"):
        assert not passwords.check(weak)["ok"], weak
    for good in ("vela-torre-muschio-faro-cedro-lampo", passwords.generate_passphrase(),
                 "Il mio gatto dorme sul divano rosso"):
        assert passwords.check(good)["ok"], good
    assert vc.normalize_code("  Vela Torre_MUSCHIO-faro ") == "vela-torre-muschio-faro"


def test_cifratura_e_sblocco():
    v, p = plain_vault_with_project()
    before = {r: v.store.read(r) for r in v.store.list()}
    codes = passwords.generate_codes()
    rec = v.create_encrypted(PASSWORD, codes, recovery=True)
    assert rec and vc.RECOVERY_MAGIC in rec
    root = v.root
    # niente in chiaro: né contenuti né nomi dei progetti
    assert not (root / "progetti").exists(), "le copie in chiaro vanno tolte"
    for f in (root / "dati").iterdir():
        blob = f.read_bytes()
        assert b"Rossi" not in blob and b"IPsec" not in blob and b"PROJECT" not in blob
        assert "rossi" not in f.name
    header = json.loads((root / "helpix-vault.json").read_text())
    assert header["encrypted"] and {s["kind"] for s in header["slots"]} == {"password", "code", "recovery"}
    assert "Rossi" not in json.dumps(header) and PASSWORD not in json.dumps(header)
    v.lock()
    assert not v.is_open
    # password sbagliata, poi quella giusta: contenuti identici
    v2 = Vault(root)
    try:
        v2.unlock("password", "sbagliata sbagliata")
        raise AssertionError("password sbagliata accettata")
    except WrongSecret:
        pass
    v2.unlock("password", PASSWORD)
    assert {r: v2.store.read(r) for r in v2.store.list()} == before
    # codice usa e getta: funziona una volta (maiuscole e spazi non contano), poi no
    info = Vault(root).unlock("code", codes[3].upper().replace("-", "  "))
    assert info["used_code"] and info["codes_left"] == 7
    try:
        Vault(root).unlock("code", codes[3])
        raise AssertionError("codice riusato")
    except WrongSecret:
        pass
    # file di recupero: apre e permette di reimpostare la password senza ricifrare i file
    names = sorted(f.name for f in (root / "dati").iterdir())
    v3 = Vault(root)
    v3.unlock("recovery", rec)
    v3.change_password("nuova frase ancora più lunga di prima")
    assert sorted(f.name for f in (root / "dati").iterdir()) == names
    try:
        Vault(root).unlock("password", PASSWORD)
        raise AssertionError("la vecchia password apre ancora")
    except WrongSecret:
        pass
    Vault(root).unlock("password", "nuova frase ancora più lunga di prima")
    # un file di recupero di un altro vault non va
    other = vc.recovery_text(os.urandom(32), "altro-vault")
    try:
        Vault(root).unlock("recovery", other)
        raise AssertionError("file di un altro vault accettato")
    except WrongSecret:
        pass


def test_rigenera_revoca_portachiavi():
    v = Vault(new_root())
    codes = passwords.generate_codes()
    v.create_encrypted(PASSWORD, codes)
    assert not v.has_recovery()
    rec = v.create_recovery()
    assert v.has_recovery()
    new_codes = passwords.generate_codes()
    v.regenerate_codes(new_codes)
    for old in codes[:2]:
        try:
            Vault(v.root).unlock("code", old)
            raise AssertionError("codice vecchio dopo la rigenerazione")
        except WrongSecret:
            pass
    Vault(v.root).unlock("code", new_codes[0])
    v.revoke_recovery()
    try:
        Vault(v.root).unlock("recovery", rec)
        raise AssertionError("file di recupero revocato accettato")
    except WrongSecret:
        pass
    # portachiavi finto: la chiave sta lì, lo slot nel vault
    store = {}

    class FakeKeyring:
        def get_password(self, s, u):
            return store.get((s, u))

        def set_password(self, s, u, val):
            store[(s, u)] = val

        def delete_password(self, s, u):
            store.pop((s, u), None)

    import helpix.vault as hv
    real = hv._keyring
    hv._keyring = lambda: FakeKeyring()
    try:
        v.enable_keyring()
        assert v.keyring_enabled() and Vault(v.root).unlock_keyring()["kind"] == "keyring"
        v.disable_keyring()
        try:
            Vault(v.root).unlock_keyring()
            raise AssertionError("portachiavi disattivato ma ancora valido")
        except WrongSecret:
            pass
    finally:
        hv._keyring = real


def test_backup_intestazione():
    v = Vault(new_root())
    v.create_encrypted(PASSWORD, passwords.generate_codes())
    for _ in range(14):
        v.change_password(PASSWORD)
    backups = list((v.root / ".backup").glob("helpix-vault-*.json"))
    assert len(backups) == vc.KEEP_BACKUPS
    # intestazione rovinata: si recupera dall'ultima copia
    good = sorted(backups)[-1]
    (v.root / "helpix-vault.json").write_text("{rotto", encoding="utf-8")
    try:
        Vault(v.root)
        raise AssertionError("intestazione rotta accettata")
    except VaultError:
        pass
    (v.root / "helpix-vault.json").write_bytes(good.read_bytes())
    Vault(v.root).unlock("password", PASSWORD)


def test_file_rovinati_o_scambiati():
    v, p = plain_vault_with_project()
    v.create_encrypted(PASSWORD, passwords.generate_codes())
    files = sorted((v.root / "dati").iterdir())
    a, b = files[0], files[1]
    blob = bytearray(a.read_bytes())
    blob[-5] ^= 0x01
    a.write_bytes(bytes(blob))
    tmp = b.read_bytes()
    c = files[2]
    b.write_bytes(c.read_bytes())  # contenuto di un altro file con il nome di questo
    c.write_bytes(tmp)
    info = Vault(v.root).unlock("password", PASSWORD)
    assert set(info["damaged"]) == {a.name, b.name, c.name}, info["damaged"]


def test_scrittura_verificata():
    root = new_root()
    target = root / "f.txt"
    vc.atomic_write(target, b"versione 1")
    try:
        vc.atomic_write(target, b"versione 2", verify=lambda _b: False)  # la rilettura non torna
        raise AssertionError("scrittura non verificata accettata")
    except VaultError:
        pass
    assert target.read_bytes() == b"versione 1" and len(list(root.iterdir())) == 1
    # processo terminato a metà salvataggio: il file vero resta quello di prima
    code = ("import os,sys; sys.path.insert(0, sys.argv[2]); from helpix import vault_crypto as vc\n"
            "orig = os.replace\n"
            "def killed(*a): os._exit(9)\n"
            "os.replace = killed\n"
            "vc.atomic_write(sys.argv[1], b'versione 3')\n")
    r = subprocess.run([sys.executable, "-c", code, str(target), str(Path(__file__).resolve().parents[1])],
                       timeout=60)
    assert r.returncode == 9 and target.read_bytes() == b"versione 1"
    v = Vault(root)  # i .tmp rimasti non disturbano
    assert not v.exists


def test_cifratura_interrotta():
    # crash dopo l'intestazione cifrata ma prima di togliere i file in chiaro: al primo sblocco si finisce
    v, p = plain_vault_with_project()
    copies = {r: v.store.read(r) for r in v.store.list()}
    v.create_encrypted(PASSWORD, passwords.generate_codes())
    plain = PlainStore(v.root)
    for rel, data in copies.items():
        plain.write(rel, data)
    plain.write("progetti/x/extra.md", b"scritto dopo")
    v2 = Vault(v.root)
    v2.unlock("password", PASSWORD)
    assert not (v.root / "progetti").exists()
    assert v2.store.read("progetti/x/extra.md") == b"scritto dopo"
    # crash prima dell'intestazione: il vault è ancora in chiaro e i resti in dati/ si ignorano
    w, _ = plain_vault_with_project()
    (w.root / "dati").mkdir()
    (w.root / "dati" / "resto.hxv").write_bytes(b"HXV1 resto")
    assert not Vault(w.root).encrypted
    w.create_encrypted(PASSWORD, passwords.generate_codes())
    assert not (w.root / "dati" / "resto.hxv").exists()


def test_esporta_e_script_autonomo():
    v, p = plain_vault_with_project()
    before = {r: v.store.read(r) for r in v.store.list()}
    codes = passwords.generate_codes()
    v.create_encrypted(PASSWORD, codes)
    dest = new_root() / "export"
    assert v.export_plain(dest) == len(before)
    out = Vault(dest)
    assert not out.encrypted and {r: out.store.read(r) for r in out.store.list()} == before
    for bad in (dest, v.root / "export"):
        try:
            v.export_plain(bad)
            raise AssertionError(f"esportato in {bad}")
        except VaultError:
            pass
    # lo script funziona da solo: copiato altrove, senza il resto di Helpix
    alone = new_root()
    (alone / "vault_crypto.py").write_bytes(Path(vc.__file__).read_bytes())
    sys.path.insert(0, str(alone))
    import importlib
    standalone = importlib.import_module("vault_crypto")
    assert standalone is not vc and standalone.__file__.startswith(str(alone))
    header = standalone.Header.load(v.root)
    master, _ = header.unlock("code", codes[5])
    target = new_root() / "decifrato"
    assert standalone.decrypt_vault(v.root, header.keys(master), target) == len(before)
    for rel, data in before.items():
        assert (target / rel).read_bytes() == data


def test_importa():
    def files(v, slug):
        pre = f"progetti/{slug}/"
        return {r[len(pre):]: v.store.read(r) for r in v.store.list(pre)}

    a, p = plain_vault_with_project()
    exp = new_root() / "export"
    a.export_plain(exp)
    b = Vault(new_root())
    b.create_plain("Casa")
    mine = b.create_project("Rete di casa", pj.template("Rete di casa", "Wi-Fi", "Fritz"))
    # dall'esportazione: il progetto entra intero (note, file, indice), il vault di destinazione resta suo
    src = Vault.open_source(exp)
    plan = b.import_plan(src)
    assert [(i.slug, i.action, i.target) for i in plan] == [(p.slug, "new", p.slug)]
    assert b.import_projects(src, plan) == 1
    assert files(b, p.slug) == files(a, p.slug) and b.project(mine.slug).name == "Rete di casa"
    # di nuovo: uguale, si salta
    assert [i.action for i in b.import_plan(src)] == ["same"] and b.import_projects(src) == 0
    # stesso progetto cambiato: entra come copia, l'originale non si tocca
    p.save_text(p.text().replace("VPN stabile", "VPN stabile e ridondata"))
    exp2 = new_root() / "export2"
    a.export_plain(exp2)
    before = files(b, p.slug)
    plan = b.import_plan(Vault.open_source(exp2))
    assert [(i.action, i.target) for i in plan] == [("copy", p.slug + "-importato")]
    assert b.import_projects(Vault.open_source(exp2), plan) == 1
    assert files(b, p.slug) == before
    copy = b.project(p.slug + "-importato")
    assert copy.name == "Cliente Rossi — firewall (importato)" and "ridondata" in copy.text()
    assert set(files(a, p.slug)) <= set(files(b, copy.slug))   # in più solo la versione salvata dal cambio di nome
    # una seconda copia diversa non sovrascrive la prima
    p.save_text(p.text().replace("ridondata", "ridondata due volte"))
    exp3 = new_root() / "export3"
    a.export_plain(exp3)
    assert [i.target for i in b.import_plan(Vault.open_source(exp3))] == [p.slug + "-importato-2"]

    # da un vault cifrato (va sbloccato) a un vault cifrato: i file importati sono cifrati con la chiave nuova
    codes = passwords.generate_codes()
    a.create_encrypted(PASSWORD, codes)
    a.lock()
    enc = Vault.open_source(a.root)
    assert enc.encrypted and not enc.is_open
    c = Vault(new_root())
    c.create_plain("Ufficio")
    c.create_encrypted("unaltra frase lunga per il vault", passwords.generate_codes())
    try:
        c.import_plan(enc)
        raise AssertionError("importato da un vault bloccato")
    except VaultError:
        pass
    enc.unlock("code", codes[0])
    assert c.import_projects(enc) == 1
    assert files(c, p.slug) == files(enc, p.slug)
    assert not (c.root / "progetti").exists()
    for f in (c.root / "dati").iterdir():
        assert b"Rossi" not in f.read_bytes()
    c.lock()
    reopened = Vault(c.root)
    reopened.unlock("password", "unaltra frase lunga per il vault")
    assert files(reopened, p.slug) == files(enc, p.slug)

    # cartella senza intestazione ma con progetti/<nome>/PROJECT.md: si importa; senza progetti no
    bare = new_root()
    (bare / "progetti" / "a-mano").mkdir(parents=True)
    (bare / "progetti" / "a-mano" / "PROJECT.md").write_text("# Scritto a mano\n\n## Stato\n- prova\n")
    plan = b.import_plan(Vault.open_source(bare))
    assert [(i.slug, i.name, i.action) for i in plan] == [("a-mano", "Scritto a mano", "new")]
    for bad in (new_root(), bare / "non-esiste"):
        try:
            Vault.open_source(bad)
            raise AssertionError(f"aperta come vault: {bad}")
        except VaultError:
            pass
    # mai da sé stesso o da una cartella che lo contiene
    for bad in (b.root, b.root.parent):
        try:
            b.import_plan(Vault.open_source(bad) if bad == b.root else _fake_source(bad, b))
            raise AssertionError(f"importato da {bad}")
        except VaultError:
            pass

    # se un file non si scrive, il progetto a metà non resta nel vault
    d = Vault(new_root())
    d.create_plain()
    real, n = d.store.write, {"n": 0}

    def flaky(rel, data):
        n["n"] += 1
        if n["n"] == 3:
            raise OSError("disco pieno")
        real(rel, data)
    d.store.write = flaky
    try:
        d.import_projects(Vault.open_source(exp))
        raise AssertionError("errore di scrittura ignorato")
    except OSError:
        pass
    d.store.write = real
    assert d.store.list("progetti/") == [] and not (d.root / "progetti" / p.slug).exists()


def _fake_source(root: Path, inside: Vault) -> Vault:
    """Una cartella che contiene il vault di destinazione, vista come sorgente già aperta."""
    v = Vault(root)
    v.store = PlainStore(root)
    return v


def test_store_cifrato_scrive_e_cancella():
    v = Vault(new_root())
    v.create_encrypted(PASSWORD, passwords.generate_codes())
    assert isinstance(v.store, EncryptedStore)
    p = v.create_project("Casa — Wi-Fi", pj.template("Casa — Wi-Fi"))
    rel = p.add_note("Router", "# Router\n", "nota")
    assert v.store.exists(rel)
    p.delete_note(rel)
    assert not v.store.exists(rel) and "Router" not in p.index_text()
    v.lock()
    try:
        v.projects()
        raise AssertionError("vault bloccato ma leggibile")
    except VaultError:
        pass


def test_cestino_rinomina():
    for encrypted in (False, True):
        v, p = plain_vault_with_project()
        if encrypted:
            v.create_encrypted(PASSWORD, passwords.generate_codes())
        files = {r: v.store.read(r) for r in v.store.list()}
        v.rename_project(p.slug, "  Rossi   — VPN sede ")
        assert v.project(p.slug).name == "Rossi — VPN sede" and len(p.versions()) == 1
        files = {r: v.store.read(r) for r in v.store.list()}
        # nota nel cestino: sparisce anche dall'indice; ripristinata torna al suo posto
        note = p.notes()[0]
        tid = v.delete_file(note.rel)
        assert not v.store.exists(note.rel) and "Prima sessione" not in p.index_text()
        items = v.trash()
        assert len(items) == 1 and items[0].kind == "note" and "Prima sessione" in items[0].name
        for bad in (p.rel("PROJECT.md"), p.rel("INDEX.md")):
            try:
                v.delete_file(bad)
                raise AssertionError(bad)
            except VaultError:
                pass
        v.restore(tid)
        assert v.store.read(note.rel) == files[note.rel] and not v.trash()
        assert v.store.read(p.rel("INDEX.md")) == files[p.rel("INDEX.md")], "la riga dell'indice torna com'era"
        # progetto nel cestino: fuori dall'elenco; ripristinato identico
        tid = v.delete_project(p.slug)
        assert not v.projects() and v.trash()[0].kind == "project" and v.trash()[0].name == "Rossi — VPN sede"
        if not encrypted:
            assert not (v.root / "progetti" / p.slug).exists()
        restored = v.restore(tid)
        assert {r: v.store.read(r) for r in restored if r in files} == {r: d for r, d in files.items() if r in restored}
        assert [i.slug for i in v.projects()] == [p.slug]
        # ripristino che si scontra con un progetto ricreato con lo stesso nome: rifiutato, niente perso
        tid = v.delete_project(p.slug)
        v.create_project("Cliente Rossi — firewall", "# Nuovo\n")
        try:
            v.restore(tid)
            raise AssertionError("ripristino sopra un progetto esistente")
        except VaultError:
            pass
        assert v.trash() and v.project(p.slug).name == "Nuovo"
        # eliminazione definitiva
        assert v.purge(tid) > 0 and not v.trash()
        v.delete_project(p.slug)
        v.purge()
        assert not v.trash() and not v.projects()
        if not encrypted:
            assert not (v.root / ".cestino").exists()


def test_grafo_del_progetto():
    """Mappa delle decisioni: ogni decisione accanto alla sessione in cui è nata, le superate verso le nuove."""
    v = Vault(new_root())
    v.create_plain("Lavoro")
    p = v.create_project("Grafo", pj.template("Grafo", "Provare il grafo", "") .replace(
        "## Decisioni in vigore\n", "## Decisioni in vigore\n- 2026-09-30 Scritta a mano prima di tutto\n"))
    g0 = p.graph()
    assert [n.kind for n in g0.nodes] == ["start", "state", "decision"]
    assert [(e.src, e.dst) for e in g0.edges if e.kind == "decided"] == [("start", "dec:scritta a mano prima di tutto")]

    def save(date, title, body, ops):
        up = pj.parse_update(f"HELPIX-PROJECT\nNOTA: {title}\n{body}\nMODIFICHE:\n" + "\n".join(ops))
        r = pj.apply_update(p.text(), up, today=date)
        p.save_text(r.text)
        return p.add_note(title, pj.note_text(title, body, "Claude", r.superseded, r.warnings, date=date,
                                              added=r.added), pj.note_summary(body), date=date)
    a = save("2026-10-01", "Inizio", "Vedi [[schema.md]].", ["+ Decisioni in vigore: Docker", "+ Decisioni in vigore: Debian"])
    b = save("2026-10-05", "Cambio", "Come in [[Inizio]].", ["~ Decisioni in vigore: Docker => Podman",
                                                            "= Stato: in prova", "+ Prossimi passi: collaudo",
                                                            "+ Decisioni in vigore: 2026-09-01 Retrodatata"])
    c = save("2026-10-05", "Stesso giorno", "Riprende [[Inizio]].", [])
    p.write_text(p.rel("file", "schema.md"), "# Schema\n")
    # decisione aggiunta a mano in PROJECT.md: va alla sessione dello stesso giorno o alla precedente
    p.save_text(p.text().replace("## Stato", "- 2026-10-07 Aggiunta a mano\n\n## Stato", 1))
    g = p.graph(recent=2)
    node = {n.rel: n for n in g.nodes}
    assert [n.rel for n in g.nodes if n.kind in ("start", "note", "state")] == ["start", a, b, c, p.rel("PROJECT.md")]
    assert node[a].files == ["schema.md"] and [node[r].in_context for r in (a, b, c)] == [False, True, True]
    assert node[p.rel("PROJECT.md")].summary == "in prova"
    docker, podman = node["dec:docker"], node["dec:podman"]
    assert docker.status == "superseded" and docker.origin == a and docker.replaced_by == podman.rel
    assert docker.until == "2026-10-05" and docker.date == "2026-10-01" and not docker.in_context
    assert podman.status == "in_force" and podman.origin == b and podman.in_context and podman.open_rel == b
    assert node["dec:debian"].origin == a
    assert node["dec:retrodatata"].origin == b   # conta la nota che la elenca in «Decisioni prese», non la data
    assert "## Decisioni prese\n- Retrodatata" in p.read_text(b)
    assert node["dec:aggiunta a mano"].origin == c   # nessuna sessione il 7: l'ultima prima
    assert node["dec:scritta a mano prima di tutto"].origin == "start"
    assert [n.title for n in g.nodes if n.kind == "step"] == ["collaudo"]
    kinds = {(e.src, e.dst): e.kind for e in g.edges}
    assert kinds[(docker.rel, podman.rel)] == "replaced" and kinds[(c, a)] == "link"
    assert (b, a) not in kinds   # sessioni vicine: la freccia del tempo basta, il link non si ripete
    assert kinds[(p.rel("PROJECT.md"), "step:0")] == "step"
    assert [e.kind for e in g.edges].count("next") == 4   # inizio → 3 sessioni → stato
    assert g.neighbours(docker.rel) == {a, podman.rel}
    # nota senza «Decisioni prese» (salvata prima di questa versione): conta la data della sessione
    d = p.add_note("Vecchia", "# Vecchia\n\ntesto\n", "", date="2026-10-09")
    p.save_text(p.text().replace("## Stato", "- 2026-10-09 Decisa nella nota vecchia\n\n## Stato", 1))
    assert {n.rel: n for n in p.graph().nodes}["dec:decisa nella nota vecchia"].origin == d


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
