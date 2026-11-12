# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progetti e vault (beta) nell'interfaccia: selettore, contesto, salvataggio con anteprima, annulla, HELPIX-NOTA,
`helpix vault …`, cifratura, sblocco e recupero dalle finestre, pannello Vault (python tests/test_projects_ui.py)."""
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

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
os.environ["HELPIX_NO_UPDATE_CHECK"] = "1"

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import project as pj, vault_crypto as vc  # noqa: E402
from helpix.config import SecretStore, Settings  # noqa: E402
from helpix.i18n import set_language  # noqa: E402
from helpix.session import Message  # noqa: E402
from helpix.ui import vault_dialogs  # noqa: E402
from helpix.ui.main_window import MainWindow  # noqa: E402
from helpix.vault import Vault  # noqa: E402

set_language("it")
vc.SCRYPT = {"n": 2 ** 10, "r": 8, "p": 1}
PASSWORD = "frase lunga per il vault di prova"


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_window(**extra):
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False, auto_continue=False,
                         projects_beta=True, project_reminder=False, **extra)
    return MainWindow(settings, SecretStore())


UPDATE = """```
HELPIX-PROJECT
NOTA: Tunnel configurato
Configurato il tunnel IPsec verso la sede. Resta da provare il failover.
MODIFICHE:
+ Decisioni in vigore: IKEv2 con AES-256
= Stato: Tunnel attivo, failover da provare.
+ Prossimi passi: Provare il failover sulla seconda WAN
```"""


def test_spento_di_default():
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False)
    settings.data.pop("projects_beta", None)
    win = MainWindow(settings, SecretStore())
    assert not win.projects_enabled and win.project_btn.isHidden()
    assert win._get_vault() is None and "PROGETTO ATTIVO" not in win._system_prompt()
    win.toggle_projects_beta(True)
    assert not win.project_btn.isHidden() and win._get_vault() is not None
    win.toggle_projects_beta(False)
    assert win.project_btn.isHidden()
    win.close()


def test_progetto_api_salva_annulla():
    win = make_window()
    vault = win._get_vault()
    p = vault.create_project("Cliente Rossi — VPN", pj.template("Cliente Rossi — VPN", "Sede collegata", "XGS 2100")
                             + "Password del cliente nel cassetto\n")
    win._open_project(p.slug)
    assert win.project.slug == p.slug and win.session.project == p.slug
    assert win.project_btn.text().startswith("Cliente Rossi")
    prompt = win._system_prompt()
    assert "PROGETTO ATTIVO" in prompt and "XGS 2100" in prompt and "cassetto" not in prompt
    # salvataggio in anteprima: la finestra viene confermata così com'è
    real_exec = vault_dialogs.ProjectSaveDialog.exec
    vault_dialogs.ProjectSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted
    try:
        win._project_update_received(pj.parse_update(UPDATE))
    finally:
        vault_dialogs.ProjectSaveDialog.exec = real_exec
    text = p.text()
    assert "IKEv2 con AES-256" in text and "Tunnel attivo" in text and "cassetto" in text
    assert p.notes()[-1].title == "Tunnel configurato" and len(p.versions()) == 1
    # automatico con annullamento
    win.settings.set("project_update_mode", "auto")
    win._project_update_received(pj.parse_update(UPDATE.replace("IKEv2 con AES-256", "Failover attivo")
                                                 .replace("Tunnel configurato", "Failover")))
    assert "Failover attivo" in p.text() and p.notes()[-1].title == "Failover"
    # lo stesso blocco arrivato due volte (letto dalla risposta e poi copiato): si applica una volta sola
    notes_before = len(p.notes())
    win._project_update_received(pj.parse_update(UPDATE.replace("IKEv2 con AES-256", "Failover attivo")
                                                 .replace("Tunnel configurato", "Failover")))
    assert len(p.notes()) == notes_before
    win._undo_project_update()
    assert "Failover attivo" not in p.text() and p.notes()[-1].title == "Tunnel configurato"
    # promemoria: c'è qualcosa di nuovo solo dopo un comando o una risposta
    win._project_saved_at = len(win.session.messages)
    assert not win._project_dirty()
    win.session.add(Message("user", "", kind="output", meta={"cmd": "ping 10.0.0.1", "rc": 0, "output": "ok"}))
    assert win._project_dirty()
    win._write_draft()
    drafts = vault.store.list(p.rel("sessioni") + "/")
    assert drafts and "ping 10.0.0.1" in p.read_text(drafts[0])
    # un task fuori dal progetto (finestra rapida): niente novità da salvare, niente bozze nel progetto
    project_id, win.session.project = win.session.project, None
    assert not win._project_dirty()
    win.session.add(Message("user", "", kind="output", meta={"cmd": "whoami", "rc": 0, "output": "x"}))
    win._draft_marker = None
    win._write_draft()
    assert "whoami" not in p.read_text(drafts[0])
    win.session.project = project_id
    win.close()


def test_note_e_comando_vault():
    win = make_window()
    vault = win._get_vault()
    p = vault.create_project("Casa — Wi-Fi", pj.template("Casa — Wi-Fi", "Copertura", "Router") + "Segreto\n")
    p.add_note("Scelta del canale", "# Scelta del canale\n\nCanale 36 a 80 MHz.\n", "Canale 36.")
    win._open_project(p.slug)
    # nella chat web la nota chiesta compare nella barra; si incolla solo premendo il pulsante
    win._note_requested("scelta del canale")
    assert not win.note_bar.isHidden() and "Scelta del canale" in win.note_bar.label.text()
    win._note_requested("nota che non esiste da nessuna parte")
    # risposte del canale locale (quelle che usa `helpix vault`)
    r = win._vault_request({"op": "cat", "q": "Scelta del canale"})
    assert r["ok"] and "Canale 36" in r["text"]
    r = win._vault_request({"op": "project"})
    assert r["ok"] and "Router" in r["text"] and "Segreto" not in r["text"]
    r = win._vault_request({"op": "search", "q": "segreto"})
    assert "Segreto" not in r["text"], "la sezione «Solo per me» non esce neanche dalla ricerca"
    r = win._vault_request({"op": "cat", "q": "PROJECT.md"})
    assert "Segreto" not in r["text"]
    # il comando vero, da un altro processo, attraverso il canale locale
    out = {}

    def run():
        root = str(Path(__file__).resolve().parents[1])
        out["r"] = subprocess.run([sys.executable, "-m", "helpix", "vault", "cat", "scelta", "del", "canale"],
                                  capture_output=True, text=True, timeout=60, cwd=root, env=dict(os.environ))
    t = threading.Thread(target=run)
    t.start()
    while t.is_alive():
        pump(50)
    assert out["r"].returncode == 0 and "Canale 36" in out["r"].stdout, out["r"]
    # file per gli agenti: contesto del progetto e comandi per le note, senza «Solo per me»
    from helpix import agents
    win._refresh_agent_project()
    agents.write_context("claude-code")
    ctx = (agents.workspace() / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Casa — Wi-Fi" in ctx and "vault cat" in ctx and "Segreto" not in ctx
    win._set_project(None, announce=False)
    agents.write_context("claude-code")
    assert "Casa — Wi-Fi" not in (agents.workspace() / "CLAUDE.md").read_text(encoding="utf-8")
    # uscendo da Helpix nella cartella dell'agente non resta niente del progetto (con il vault cifrato sarebbe il
    # suo testo in chiaro sul disco): istruzioni senza progetto, via la nota letta e l'aggiornamento scritto
    ws = agents.workspace()
    contexts = [ws / a["context"] for a in agents.AGENTS.values()]

    def leftovers():
        return [f.name for f in contexts if "Casa — Wi-Fi" in f.read_text(encoding="utf-8")] + \
               [n for n in (agents.NOTE_FILE, agents.PROJECT_FILE) if (ws / n).exists()]
    win._open_project(p.slug)
    agents.write_context("claude-code")
    (ws / agents.NOTE_FILE).write_text("Canale 36 a 80 MHz.\n", encoding="utf-8")
    (ws / agents.PROJECT_FILE).write_text("HELPIX-PROJECT\nNOTA: x\n", encoding="utf-8")
    assert len(leftovers()) == len(contexts) + 2
    assert win._projects_on_quit() and leftovers() == []
    assert all(f.exists() and "Helpix" in f.read_text(encoding="utf-8") for f in contexts)   # le istruzioni restano
    # Helpix chiuso male con il progetto aperto: all'avvio dopo, i resti si tolgono
    win._open_project(p.slug)
    agents.write_context("claude-code")
    assert leftovers()
    win2 = make_window()
    assert leftovers() == []
    win2.close()
    win.close()


def test_cifratura_dalle_finestre():
    win = make_window(vault_dir=os.path.join(_tmp, "vault-cifrato"))
    vault = win._get_vault()
    p = vault.create_project("Lab Proxmox", pj.template("Lab Proxmox", "Cluster a 3 nodi"))
    win._open_project(p.slug)
    dlg = vault_dialogs.VaultCreateDialog(vault, win)
    assert not dlg.next.isEnabled()
    dlg.fields.pw.setText("corta")
    dlg.fields.pw2.setText("corta")
    assert not dlg.next.isEnabled(), "password troppo corta"
    dlg.fields._generate()
    assert dlg.next.isEnabled()
    dlg._next()
    assert dlg.stack.currentIndex() == 1 and not dlg.next.isEnabled(), "prima va confermato un codice"
    dlg.codes_w.confirm.setText(dlg.codes[4].upper().replace("-", " "))
    assert dlg.next.isEnabled()
    dlg._next()
    dlg._next()  # «Cifra il vault»
    assert dlg.result() == QDialog.DialogCode.Accepted and vault.encrypted and vault.is_open
    password, codes = dlg.fields.password(), dlg.codes
    # il blocco di Helpix chiude anche il vault
    win.lock_vault()
    assert not vault.is_open and win.project_btn.text() == "Vault bloccato"
    assert "PROGETTO ATTIVO" not in win._system_prompt()
    assert not win._vault_request({"op": "project"})["ok"]
    # sblocco con la password
    un = vault_dialogs.VaultUnlockDialog(vault, win)
    un.pw.setText("sbagliata davvero")
    un._unlock()
    assert not vault.is_open and "sbagliata" in un.err.text()
    un.pw.setText(password)
    un._unlock()
    assert vault.is_open and un.result() == QDialog.DialogCode.Accepted
    win._after_vault_unlock(un.info)
    assert win.project is not None and "Cluster a 3 nodi" in win._system_prompt()
    # un task fuori dal progetto (es. dalla finestra rapida) non riceve il contesto
    project_id, win.session.project = win.session.project, None
    assert "Cluster a 3 nodi" not in win._system_prompt()
    win.session.project = project_id
    # il blocco di Helpix (anche per inattività) chiude il vault
    win._projects_on_lock()
    assert not vault.is_open
    un = vault_dialogs.VaultUnlockDialog(vault, win)
    un.pw.setText(password)
    un._unlock()
    win._after_vault_unlock(un.info)
    # recupero con un codice e password nuova; poi niente rigenerazione
    win.lock_vault()
    real_q = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    try:
        rec = vault_dialogs.VaultUnlockDialog(vault, win)
        rec.stack.setCurrentIndex(1)
        rec.code.setText(codes[0])
        rec.new_pw._generate()
        new_password = rec.new_pw.password()
        rec._recover()
    finally:
        QMessageBox.question = real_q
    assert vault.is_open and vault.codes_left() == 7
    assert Vault(vault.root).unlock("password", new_password)["kind"] == "password"
    win.close()


def test_importa_dalle_finestre():
    from PySide6.QtWidgets import QFileDialog, QPushButton, QTreeWidgetItemIterator
    from helpix import passwords
    # sorgenti: un'esportazione in chiaro e un vault cifrato
    a = Vault(os.path.join(_tmp, "vault-sorgente"))
    a.create_plain("Ufficio")
    a.create_project("Rete ufficio", pj.template("Rete ufficio", "VLAN separate", "Sophos XGS"))
    exported = os.path.join(_tmp, "esportato")
    a.export_plain(exported)
    b = Vault(os.path.join(_tmp, "vault-cifrato-sorgente"))
    b.create_plain("Casa")
    b.create_project("Lab Proxmox casa", pj.template("Lab Proxmox casa", "Cluster a 3 nodi"))
    b_codes = passwords.generate_codes()
    b.create_encrypted(PASSWORD, b_codes)
    b.lock()

    win = make_window(vault_dir=os.path.join(_tmp, "vault-importa"))
    vault = win._get_vault()
    win.open_vault_panel()
    panel = win.vault_panel
    assert any(b_.text() == "Importa…" for b_ in panel.findChildren(QPushButton))
    dlg = vault_dialogs.ProjectSettingsDialog(win.settings, lambda: win._get_vault(), win)
    assert not dlg.b_import.isHidden()
    dlg.close()

    asked, said = [], []
    real = (QFileDialog.getExistingDirectory, QMessageBox.question, QMessageBox.information, QMessageBox.warning,
            vault_dialogs.VaultUnlockDialog)
    folder = {"path": exported}

    class FakeUnlock:
        how = ("code", b_codes[0])   # la prima volta con un codice usa e getta, poi con la password

        def __init__(self, v, parent=None, allow_system=False):
            self.v = v
            self.info = None

        def exec(self):
            self.info = self.v.unlock(*FakeUnlock.how)
            FakeUnlock.how = ("password", PASSWORD)
            return QDialog.DialogCode.Accepted
    QFileDialog.getExistingDirectory = staticmethod(lambda *a_, **k: folder["path"])
    QMessageBox.question = staticmethod(lambda _p, _t, text, *a_, **k: (asked.append(text),
                                                                       QMessageBox.StandardButton.Yes)[1])
    QMessageBox.information = staticmethod(lambda _p, _t, text, *a_, **k: said.append(text))
    QMessageBox.warning = staticmethod(lambda _p, _t, text, *a_, **k: said.append(text))
    vault_dialogs.VaultUnlockDialog = FakeUnlock
    try:
        win.import_vault()
        assert "«Rete ufficio»: nuovo" in asked[-1] and "Niente di questo vault viene sovrascritto" in asked[-1]
        assert [i.name for i in vault.projects()] == ["Rete ufficio"]
        shown, it = [], QTreeWidgetItemIterator(panel.tree)
        while it.value():
            shown.append(it.value().text(0))
            it += 1
        assert any("Rete ufficio" in t for t in shown), shown   # il pannello aperto si aggiorna
        # di nuovo: niente da fare, nessuna domanda
        n_asked = len(asked)
        win.import_vault()
        assert len(asked) == n_asked and "ci sono già, uguali" in said[-1]
        # dal vault cifrato: chiede lo sblocco, avvisa che qui finiscono in chiaro, poi lo richiude
        folder["path"] = str(b.root)
        win.import_vault()
        assert "leggibili sul disco" in asked[-1]
        assert {i.name for i in vault.projects()} == {"Rete ufficio", "Lab Proxmox casa"}
        # aperto con un codice usa e getta: l'origine perde quel codice, e la conferma lo dice
        left = len(b_codes) - 1
        assert f"gliene restano {left}" in asked[-1] and Vault(b.root).codes_left() == left
        assert "restano dove sono" in asked[-1] and "resta com'è" not in asked[-1]
        n_asked = len(asked)
        win.import_vault()   # di nuovo, con la password: niente da importare e nessun codice consumato
        assert len(asked) == n_asked and Vault(b.root).codes_left() == left
        # cartella qualsiasi: avviso, niente importato
        folder["path"] = os.path.join(_tmp, "config")
        win.import_vault()
        assert "non c'è un vault di Helpix" in said[-1] and len(vault.projects()) == 2
    finally:
        (QFileDialog.getExistingDirectory, QMessageBox.question, QMessageBox.information, QMessageBox.warning,
         vault_dialogs.VaultUnlockDialog) = real
    panel.close()
    win.close()


def test_cartella_del_vault_tutta_sua():
    """«Cartella del vault»: una cartella con altri file non si usa così com'è (cifrando il vault ci andrebbero di
    mezzo): Helpix propone una sottocartella sua."""
    from PySide6.QtWidgets import QFileDialog
    win = make_window(vault_dir=os.path.join(_tmp, "vault-cartella"))
    docs = Path(_tmp) / "Documenti"
    docs.mkdir()
    (docs / "fattura.pdf").write_bytes(b"%PDF")
    empty = Path(_tmp) / "vuota"
    empty.mkdir()
    existing = Vault(Path(_tmp) / "vault-gia-fatto")
    existing.create_plain("Altro")
    dlg = vault_dialogs.ProjectSettingsDialog(win.settings, lambda: win._get_vault(), win)
    asked, warned, answer = [], [], {"yes": True}
    real = (QFileDialog.getExistingDirectory, QMessageBox.question, QMessageBox.warning)
    pick = {"path": str(docs)}
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: pick["path"])
    QMessageBox.question = staticmethod(lambda _p, _t, text, *a, **k: (asked.append(text), (
        QMessageBox.StandardButton.Yes if answer["yes"] else QMessageBox.StandardButton.No))[1])
    QMessageBox.warning = staticmethod(lambda _p, _t, text, *a, **k: warned.append(text))
    try:
        before = win.settings.get("vault_dir")
        answer["yes"] = False
        dlg._choose_folder()
        assert "cartella tutta sua" in asked[-1] and win.settings.get("vault_dir") == before
        answer["yes"] = True
        dlg._choose_folder()
        assert win.settings.get("vault_dir") == str(docs / "Vault Helpix") and (docs / "Vault Helpix").is_dir()
        assert sorted(f.name for f in docs.iterdir() if f.is_file()) == ["fattura.pdf"]
        # la sottocartella proposta è già occupata da altro: avviso, niente cambio
        work = Path(_tmp) / "Lavoro"
        (work / "Vault Helpix").mkdir(parents=True)
        (work / "Vault Helpix" / "altro.txt").write_text("x")
        pick["path"] = str(work)
        dlg._choose_folder()
        assert "contiene già altri file" in warned[-1] and win.settings.get("vault_dir") == str(docs / "Vault Helpix")
        for ok in (empty, existing.root):   # vuota o già un vault: si usa così, senza domande
            n = len(asked)
            pick["path"] = str(ok)
            dlg._choose_folder()
            assert win.settings.get("vault_dir") == str(ok) and len(asked) == n
    finally:
        QFileDialog.getExistingDirectory, QMessageBox.question, QMessageBox.warning = real
    dlg.close()
    win.close()


def test_pannello_e_nuovo_progetto():
    win = make_window(vault_dir=os.path.join(_tmp, "vault-pannello"))
    vault = win._get_vault()
    d = vault_dialogs.NewProjectDialog(win)
    d.context.setPlainText("# Migrazione posta\n\n## Obiettivo\nPassare a M365\n\n## Stato\nDNS pronti\n")
    text = d.project_text()
    assert text.startswith("# Migrazione posta") and "## Solo per me" in text and d.project_name() == "Migrazione posta"
    p = vault.create_project(d.project_name(), text)
    p.add_note("DNS", "# DNS\n\nRecord MX cambiati. Vedi [[file/dns]].\n", "MX cambiati.")
    p.add_note("Utenti", "# Utenti\n\nCome deciso in [[" + p.notes()[0].stem + "|DNS]].\n", "Utenti creati.")
    win._open_project(p.slug)
    win.open_vault_panel()
    panel = win.vault_panel
    assert panel is not None and panel.current and panel.current[2].endswith("PROJECT.md")
    # finestra a sé (non resta sopra a Helpix) con la stessa barra integrata di Helpix
    assert panel.parent() is None and panel.isWindow()
    assert panel.frameless == win.frameless and (not win.frameless or panel.toolbar.isVisible())
    assert panel.width() >= panel.minimumWidth()
    panel.select(p.notes()[0].rel)
    assert panel.backlinks.count() == 1 and panel.backlinks.item(0).text().startswith("note/")
    # grafo: percorso del progetto, un clic apre la nota, da lì si torna a leggere o modificare
    panel.btn_graph.setChecked(True)
    pump(50)
    gv = panel.graph_page.view
    assert panel.stack.currentIndex() == 2 and panel.title.text() == p.name
    assert {n.rel for n in p.notes()} | {"start", p.rel("PROJECT.md")} <= set(gv.nodes)
    assert "next" in {e.kind for e in gv.edges} and gv.nodes[p.notes()[0].rel].current
    gv.highlight(p.notes()[1].rel)
    assert gv.nodes[p.notes()[0].rel].hot is False and not gv.nodes[p.notes()[0].rel].dim   # vicino: acceso
    gv.highlight(None)
    second = p.notes()[1].rel
    QTest.mouseClick(gv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     gv.mapFromScene(gv.nodes[second].pos()))
    pump(50)
    assert panel.stack.currentIndex() == 0 and panel.current[2] == second and panel.btn_read.isChecked()
    panel.btn_graph.setChecked(True)
    panel.btn_read.setChecked(True)
    assert panel.stack.currentIndex() == 0 and panel.current[2] == second and panel.title.text() == "Utenti"
    panel.btn_graph.setChecked(True)
    panel.btn_edit.setChecked(True)   # dal grafo direttamente alla modifica
    assert panel.stack.currentIndex() == 1 and panel.btn_edit.isChecked() and panel.current[2] == second
    panel.btn_read.setChecked(True)
    panel.select(p.rel("PROJECT.md"))
    panel.btn_edit.setChecked(True)
    panel.editor.setPlainText(p.text() + "\n## Riferimenti\n- wiki interna\n")
    panel._save()
    assert "wiki interna" in p.text() and len(p.versions()) == 1
    panel.search.setText("record mx")
    assert panel.tree.topLevelItemCount() == 1
    panel.search.setText("")
    pasted = []
    panel.paste.connect(pasted.append)
    panel.select(p.notes()[0].rel)
    panel._paste_current()
    assert pasted and "Record MX" in pasted[0]
    # albero: un clic apre e chiude le cartelle; le frecce e le righe si disegnano senza errori
    folder = next(panel.tree.topLevelItem(0).child(j) for j in range(panel.tree.topLevelItem(0).childCount())
                  if panel.tree.topLevelItem(0).child(j).childCount())
    was = folder.isExpanded()
    panel._item_clicked(folder)
    assert folder.isExpanded() != was
    panel._item_clicked(folder)
    assert folder.isExpanded() == was
    assert not panel.grab().isNull()
    # elimina e ripristina dal pannello (conferma simulata): il progetto aperto si chiude, poi torna
    from helpix.ui import vault_panel as vp

    class Yes(vp.QMessageBox):
        def exec(self):
            return 0

        def clickedButton(self):
            return next(b for b in self.buttons() if self.buttonRole(b) == vp.QMessageBox.ButtonRole.DestructiveRole)

    real_box = vp.QMessageBox
    vp.QMessageBox = Yes
    try:
        panel._delete_project(p.slug)
        assert win.project is None and not vault.projects() and vault.trash()
        tid = vault.trash()[0].id
        assert "trash:" + tid in panel._items and panel.current[0] == "trash"
        assert panel.btn_untrash.isVisible() and panel.btn_purge.isVisible()
        panel._untrash(tid)
        assert [i.slug for i in vault.projects()] == [p.slug] and not vault.trash()
        win._open_project(p.slug)
        panel.select(p.notes()[0].rel)
        vault.delete_file(p.notes()[0].rel)
        panel.reload()
        assert vault.trash()[0].kind == "note"
        panel._purge(vault.trash()[0].id)
        assert not vault.trash()
    finally:
        vp.QMessageBox = real_box
    vault.rename_project(p.slug, "Migrazione posta — M365")
    panel.changed.emit(p.slug)
    assert win.project_btn.text().startswith("Migrazione posta — M365")
    # finestra stretta: la colonna di destra si nasconde; larga: c'è
    panel.resize(panel.minimumWidth(), 700)
    assert not panel.aside.isVisible()
    panel.resize(1240, 800)
    assert panel.aside.isVisible()
    # giro a nuvolette del pannello: tutti i passi, poi «già visto»
    win.start_vault_tour(panel)
    tour = panel._tour
    assert tour is not None and tour.host is panel and not tour.bubble.show_tips.isVisible()
    seen = []
    while panel._tour is not None and len(seen) < 30:
        seen.append(tour.step.key)
        tour.forward()
    assert seen[0] == "v_welcome" and seen[-1] == "v_bye" and "v_ctx" in seen and len(seen) >= 8
    assert win.settings.get("vault_tour_done")
    panel.close()
    # giro dei progetti: parte da solo la prima volta che si accende la funzione, si riapre dal menu
    win.settings.set("projects_tour_done", False)
    win.show()  # i passi puntano a pulsanti visibili
    win.toggle_projects_beta(False)
    win.toggle_projects_beta(True)
    pump(800)
    assert win._ptour is not None and win._ptour.step.key == "p_welcome"
    keys = []
    while win._ptour is not None and len(keys) < 30:
        keys.append(win._ptour.step.key)
        win._ptour.forward()
    assert keys[-1] == "p_bye" and {"p_picker", "p_save", "p_vault", "p_lock"} <= set(keys), keys
    assert win.settings.get("projects_tour_done")
    win.start_projects_tour()
    assert win._ptour is not None
    win._ptour.close_tour()
    # uscendo da Helpix si chiude anche la finestra del vault
    win.open_vault_panel()
    pump(100)
    assert win.vault_panel is not None and win._projects_on_quit()
    pump(100)
    assert win.vault_panel is None
    win.close()


def test_barra_stretta_e_finestre_helpix():
    """La barra in alto non sovrappone i pulsanti quando la finestra si stringe; le finestre di dialogo
    (impostazioni dei progetti, conferme, richieste di testo) usano la barra di Helpix."""
    from PySide6.QtWidgets import QInputDialog
    from helpix.ui import dialog_frame
    win = make_window()
    win.show()
    win.project_btn.setText("Un progetto con un nome davvero molto lungo")
    win.model_btn.setText("modello predefinito · high")
    pump(100)
    levels, by_width = [], {}
    for w in (1400, 1000, 820, 760):
        win.resize(w, 640)
        pump(120)
        levels.append(win._tb_level)
        lay = win.toolbar.layout()
        by_width[win.toolbar.width()] = (win._tb_level, lay.minimumSize().width(),
                                         [(type(x).__name__, x.minimumSizeHint().width(), x.minimumWidth())
                                          for x in (win.picker, win.model_btn, win.project_btn, win.shot, win.btn_diag)])
        assert win.picker.status.isVisible() == (win._tb_level == 0), (w, win._tb_level)
        bar = win.toolbar
        items = [bar.layout().itemAt(i).widget() for i in range(bar.layout().count())]
        shown = [x for x in items if x is not None and x.isVisible()]
        for a, b in zip(shown, shown[1:]):
            assert a.geometry().right() < b.geometry().left(), (w, a, b)   # niente sovrapposizioni
        pills = (win.picker, win.model_btn, win.project_btn, win.shot, win.btn_diag)
        assert len({p.geometry().top() for p in pills if p.isVisible()}) == 1, w   # tutti allineati
        assert len({p.height() for p in pills if p.isVisible()}) == 1, w
    # più stretta = livello uguale o più compatto (su Windows lo schermo del CI è piccolo: si parte già compatti)
    assert levels == sorted(levels) and levels[-1] > levels[0], levels
    # il nome intero resta (per i test, i suggerimenti e i lettori di schermo)
    assert win.project_btn.text() == "Un progetto con un nome davvero molto lungo"
    assert "molto lungo" in win.project_btn.toolTip()
    # allargando si torna indietro (stessa larghezza = stesso livello)
    win.resize(1400, 640)
    pump(120)
    assert win._tb_level <= levels[-1], (win._tb_level, levels)
    if win.toolbar.width() in by_width:
        assert win._tb_level == by_width[win.toolbar.width()][0], (win.toolbar.width(), win._tb_level,
                                                                     lay.minimumSize().width(), by_width)

    # finestre di dialogo con la cornice di Helpix
    seen = {}

    def grab(key):
        w = QApplication.activeModalWidget()
        seen[key] = (type(w).__name__, w.property("hxframe") if w else None,
                     bool(w and w.windowFlags() & dialog_frame.Qt.WindowType.FramelessWindowHint))
        if w:
            w.close()
    QTimer.singleShot(200, lambda: grab("box"))
    answer = QMessageBox.question(win, "Domanda", "Va bene?")
    assert answer == QMessageBox.StandardButton.No, answer   # chiusa con la × = No, come in Qt
    QTimer.singleShot(200, lambda: grab("text"))
    QInputDialog.getText(win, "Rinomina", "Nome:")
    dlg = vault_dialogs.ProjectSettingsDialog(win.settings, win._get_vault, win)
    QTimer.singleShot(200, lambda: grab("settings"))
    dlg.exec()
    assert seen == {"box": ("QMessageBox", "true", True), "text": ("QInputDialog", "true", True),
                    "settings": ("ProjectSettingsDialog", "true", True)}, seen
    assert dlg.findChild(dialog_frame._DialogBar).title.text() == dlg.windowTitle()
    # percorso del vault su una riga, accorciato al centro, intero nel suggerimento
    assert "\n" not in dlg.folder.text() and dlg.folder.toolTip() == dlg.folder.full_text()
    win.close()


def test_menu_ingranaggio_compatto():
    """Ingranaggio: le opzioni sì/no stanno in «Configurazione» e «Aspetto», «Segnala un problema…» è in vista."""
    win = make_window()
    try:
        menu = win.gear_menu
        top = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert len(top) <= 16, top
        assert "Segnala un problema…" in top and "Configurazione" in top and "Aspetto" in top
        for gone in ("Tieni sopra le altre finestre", "Usa la barra del titolo del sistema", "Angoli arrotondati",
                     "Mostra i suggerimenti all'avvio", "Avvisami delle nuove versioni"):
            assert gone not in top, gone
        sub = {a.text(): a.menu() for a in menu.actions() if a.menu()}
        config = [a.text() for a in sub["Configurazione"].actions()]
        assert "Tieni sopra le altre finestre" in config and "Mostra i suggerimenti all'avvio" in config
        assert win.act_titlebar in sub["Aspetto"].actions() and win.act_rounded in sub["Aspetto"].actions()
    finally:
        win.close()


def test_tetto_regolabile():
    """Il tetto di PROJECT.md si sceglie dalle impostazioni e vale per misuratore, avvisi e compattazione."""
    win = make_window()
    try:
        assert pj.set_token_limit("abc") == 1000 and pj.set_token_limit(3000) in (2000, 4000)
        dlg = vault_dialogs.ProjectSettingsDialog(win.settings, win._get_vault, win)
        dlg.changed.connect(win._apply_project_settings)
        dlg.limit.setCurrentIndex(dlg.limit.findData(2000))
        assert win.settings.get("project_token_limit") == 2000 and pj.TOKEN_LIMIT == 2000
        assert "2000 token" in pj.compact_request("# P\n\n## Stato\nok\n")
        dlg.close()
    finally:
        win.settings.set("project_token_limit", 1000)
        pj.set_token_limit(1000)
        win.close()


def test_file_dell_agente_in_codifiche_windows():
    """HELPIX-PROJECT.md scritto su Windows (BOM, UTF-16, ANSI con accenti, CRLF): Helpix lo legge lo stesso, e un
    file illeggibile non ferma il controllo lasciando Helpix «in attesa» senza dire niente."""
    from helpix import agents
    from helpix.ui.agent_panel import AgentPanel
    body = UPDATE.strip("`\n").replace("sede.", "sede, perché è più già.") + "\n"
    path = agents.workspace() / agents.PROJECT_FILE
    for data in (body.encode("utf-8-sig"), body.encode("utf-16"), body.encode("cp1252"),
                 body.replace("\n", "\r\n").encode("utf-8-sig")):
        path.write_bytes(data)
        up = agents.read_project_update()
        assert up is not None and up.title == "Tunnel configurato", data[:20]
        assert "perché è più già" in up.body
    path.write_text("﻿HELPIX-SUMMARY\nniente\n", encoding="utf-8")
    assert agents.read_summary() is None

    panel = AgentPanel("claude-code")
    try:
        got, failed = [], []
        panel.project_ready.connect(got.append)
        panel.project_failed.connect(failed.append)
        panel._project_until, panel._project_last = 1e18, None
        orig = agents.read_project_update
        agents.read_project_update = lambda: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"", 0, 1, "x"))
        try:
            panel._project_poll()  # prima lanciava l'errore e i controlli si fermavano
        finally:
            agents.read_project_update = orig
        assert panel.project_pending and not got and not failed
        path.write_bytes(body.encode("utf-16"))
        for _ in range(2):
            panel._project_poll()
        assert len(got) == 1 and not panel.project_pending
        # tempo scaduto con un file che non si capisce: lo dice, invece del messaggio «non l'ha scritto»
        import time
        path.write_text("ciao\n", encoding="utf-8")
        panel._project_until, panel._project_last = time.monotonic() + 0.05, None
        agents.read_project_update = lambda: (time.sleep(0.1), None)[1]
        try:
            panel._project_poll()
        finally:
            agents.read_project_update = orig
        assert len(failed) == 1 and "non riesce a leggerlo" in failed[0] and not panel.project_pending
    finally:
        path.unlink(missing_ok=True)
        panel.shutdown()
        panel.deleteLater()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    hardexit.now(0)
