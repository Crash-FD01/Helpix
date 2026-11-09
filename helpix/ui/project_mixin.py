# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progetti e vault (beta) nella finestra principale: selettore, apertura con il contesto, «Salva progetto»
con anteprima, HELPIX-NOTA, promemoria, bozze automatiche, blocco del vault, `helpix vault …`.

È una classe da aggiungere a MainWindow (usa i suoi attributi: settings, session, engine, web, agent…), tenuta a
parte per non allungare ancora main_window.py. Specifica: docs/PROGETTI.md.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton

from .. import agents, project as pj, theme
from ..i18n import tr
from ..icons import icon
from ..theme import C
from ..vault import Vault, VaultError, WrongSecret, default_root
from .controls import IconButton

log = logging.getLogger(__name__)


class NoteRequestBar(QFrame):
    """«L'IA chiede la nota "…"» — Incolla nella chat / Ignora."""

    def __init__(self, on_paste, parent=None):
        super().__init__(parent)
        self.setObjectName("notice")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 10, 8)
        h.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icon("clipboard", C["accentFg"], 18).pixmap(18, 18))
        h.addWidget(ic)
        self.label = QLabel()
        self.label.setWordWrap(True)
        h.addWidget(self.label, 1)
        self.btn = QPushButton(tr("Incolla nella chat"))
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(lambda: (self.hide(), on_paste(self.payload)))
        h.addWidget(self.btn)
        ignore = QPushButton(tr("Ignora"))
        ignore.clicked.connect(self.hide)
        h.addWidget(ignore)
        self.payload = ("", "")
        self.hide()

    def ask(self, title: str, text: str):
        self.payload = (title, text)
        self.label.setText(tr("L'IA chiede la nota «{title}» (~{n} token)").format(
            title=title, n=pj.estimate_tokens(text)))
        self.show()


class ProjectsMixin:
    # ------------------------------------------------------------ preparazione
    def _setup_projects(self):
        self.vault: Vault | None = None
        self.project = None
        self.vault_panel = None
        self._project_saved_at = 0      # messaggi del task già salvati nel progetto
        self._draft_marker = None
        self._last_update: dict | None = None
        self._project_request: dict | None = None
        self.project_btn = IconButton("folder", tr("Progetto (beta)"), text=tr("Nessun progetto"), icon_size=15,
                                      color_key="secondary")
        self.project_btn.setObjectName("pill")
        self.project_btn.setPopupMode(IconButton.ToolButtonPopupMode.InstantPopup)
        self.project_menu = theme.prepare_menu(QMenu(self))
        self.project_menu.aboutToShow.connect(self._build_project_menu)
        self.project_btn.setMenu(self.project_menu)
        layout = self.toolbar.layout()
        layout.insertWidget(layout.indexOf(self.model_btn) + 1, self.project_btn)
        self.note_bar = NoteRequestBar(self._paste_note)
        self._note_wrap.layout().addWidget(self.note_bar)
        self.web.project_copied.connect(self._project_update_received)
        self.web.project_failed.connect(self._project_update_failed)
        self.web.note_requested.connect(self._note_requested)
        self._draft_timer = QTimer(self)
        self._draft_timer.timeout.connect(self._write_draft)
        self._apply_project_settings(initial=True)

    @property
    def projects_enabled(self) -> bool:
        return bool(self.settings.get("projects_beta", False))

    def _apply_project_settings(self, initial: bool = False):
        on = self.projects_enabled
        self.project_btn.setVisible(on)
        self._schedule_toolbar_fit()
        if hasattr(self, "act_projects_beta"):
            self.act_projects_beta.setChecked(on)
        limit = pj.TOKEN_LIMIT
        if pj.set_token_limit(self.settings.get("project_token_limit", 1000)) != limit and self.vault_panel:
            self.vault_panel.reload()   # misuratore con il tetto nuovo
        minutes = int(self.settings.get("project_autosave_min", 10) or 0)
        self._draft_timer.stop()
        if on and minutes:
            self._draft_timer.start(minutes * 60 * 1000)
        if not on:
            if self.project is not None:
                self._set_project(None, announce=False)
            if self.vault is not None:
                self.vault.lock()  # niente chiave in memoria con la funzione spenta
            self.vault = None
            return
        root = Path(self.settings.get("vault_dir") or default_root())
        if self.vault is None or self.vault.root != root:
            if self.vault is not None:
                self.vault.lock()
            self.vault = None
            if self.project is not None:
                self._set_project(None, announce=False)
        if initial:
            slug = self.settings.get("active_project")
            vault = self._get_vault(create=False)
            if slug and vault and vault.is_open:
                try:
                    self._set_project(vault.project(slug), announce=False)
                except KeyError:
                    pass
        self._update_project_button()

    def _get_vault(self, create: bool = True) -> Vault | None:
        if not self.projects_enabled:
            return None
        root = Path(self.settings.get("vault_dir") or default_root())
        if self.vault is None or self.vault.root != root:
            try:
                self.vault = Vault(root)
            except VaultError as exc:
                QMessageBox.warning(self, tr("Vault"), tr("Non riesco a leggere il vault: {exc}").format(exc=exc))
                return None
        if create and not self.vault.exists:
            try:
                self.vault.create_plain(tr("Lavoro"))
            except OSError as exc:
                QMessageBox.warning(self, tr("Vault"), tr("Non riesco a creare il vault: {exc}").format(exc=exc))
                return None
        return self.vault

    def _vault_open(self) -> Vault | None:
        """Il vault pronto per leggere e scrivere: se è cifrato e bloccato, chiede di sbloccarlo."""
        vault = self._get_vault()
        if vault is None:
            return None
        if vault.is_open:
            return vault
        from .vault_dialogs import VaultUnlockDialog
        dlg = VaultUnlockDialog(vault, self, allow_system=True)
        dlg.system_unlock.connect(lambda: self._vault_system_unlock(dlg))
        if dlg.exec() != QDialog.DialogCode.Accepted or not vault.is_open:
            return None
        self._after_vault_unlock(dlg.info or {})
        return vault

    def _after_vault_unlock(self, info: dict):
        if info.get("damaged"):
            QMessageBox.warning(self, tr("Vault"), tr("{n} file del vault sono rovinati o sono stati modificati da fuori: "
                                                      "li ho lasciati da parte. Le copie dell'intestazione sono in "
                                                      ".backup.").format(n=len(info["damaged"])))
        if info.get("used_code") and info.get("codes_left", 0) < 3:
            self.notify(tr("Restano {n} codici di recupero: rigenerali da Impostazioni › Progetti e vault.").format(
                n=info.get("codes_left", 0)), 9000)
        slug = self.settings.get("active_project")
        if self.project is None and slug:
            try:
                self._set_project(self.vault.project(slug), announce=False)
            except KeyError:
                pass
        self._update_project_button()

    def _vault_system_unlock(self, dlg):
        """Sblocco con il portachiavi, dopo la conferma del sistema (polkit o Windows Hello)."""
        from ..security import SystemUnlock, policy_installed, unlock_available
        if not unlock_available() or not policy_installed():
            QMessageBox.information(dlg, tr("Vault"), tr("La conferma del sistema non è disponibile: attivala in "
                                                         "Impostazioni › Sicurezza, oppure usa la password del vault."))
            return
        checker = SystemUnlock(dlg)

        def done(ok, _msg):
            if not ok:
                return
            try:
                dlg.info = self.vault.unlock_keyring()
            except (WrongSecret, VaultError, Exception) as exc:  # noqa: BLE001
                QMessageBox.warning(dlg, tr("Vault"), tr("Sblocco dal portachiavi non riuscito: {exc}").format(exc=exc))
                return
            dlg.accept()
        checker.finished.connect(done)
        checker.start()

    # ------------------------------------------------------------ selettore
    def _update_project_button(self):
        if not hasattr(self, "project_btn"):
            return
        vault = self.vault
        locked = bool(vault and vault.encrypted and not vault.is_open)
        if self.project is not None and not locked:
            text = self.project.name   # la barra lo accorcia se non ci sta (nome intero nel suggerimento)
        elif locked and self.settings.get("active_project"):
            text = tr("Vault bloccato")
        else:
            text = tr("Nessun progetto")
        self.project_btn.setText(text)
        self.project_btn.set_icon_name("lock" if locked else "folder")
        self._schedule_toolbar_fit()

    def _build_project_menu(self):
        m = self.project_menu
        m.clear()
        vault = self._get_vault()
        if vault is None:
            return
        if vault.encrypted and not vault.is_open:
            m.addAction(icon("unlock", C["text"], 16), tr("Sblocca il vault…"), self._vault_open)
        else:
            try:
                projects = vault.projects()
            except VaultError:
                projects = []
            for info in projects[:15]:
                act = m.addAction(info.name, lambda s=info.slug: self._open_project(s))
                act.setCheckable(True)
                act.setChecked(self.project is not None and self.project.slug == info.slug)
            if projects:
                m.addSeparator()
            m.addAction(icon("plus", C["text"], 16), tr("Nuovo progetto…"), self.new_project)
            if self.project is not None:
                m.addAction(icon("upload", C["text"], 16), tr("Salva progetto"), self.save_project)
                act = m.addAction(tr("Compatta il progetto…"), lambda: self.save_project(compact=True))
                try:
                    act.setEnabled(pj.estimate_tokens(pj.strip_private(self.project.text())) > pj.TOKEN_LIMIT // 2)
                except (KeyError, VaultError):
                    pass
                if self._last_update and time.time() - self._last_update["at"] < 1800:
                    m.addAction(tr("Annulla l'ultimo aggiornamento"), self._undo_project_update)
                m.addAction(tr("Chiudi il progetto"), lambda: self._close_project())
                m.addAction(icon("trash", C["errText"], 16), tr("Elimina il progetto…"), self.delete_current_project)
            m.addSeparator()
            m.addAction(icon("folder", C["text"], 16), tr("Apri il vault…"), self.open_vault_panel)
            if vault.encrypted:
                m.addAction(icon("lock", C["text"], 16), tr("Blocca il vault"), self.lock_vault)
        m.addSeparator()
        m.addAction(icon("info", C["text"], 16), tr("Guida ai progetti"), self.start_projects_tour)
        m.addAction(icon("gear", C["text"], 16), tr("Impostazioni dei progetti…"), self.open_project_settings)

    def new_project(self):
        from .vault_dialogs import NewProjectDialog
        vault = self._vault_open()
        if vault is None:
            return
        dlg = NewProjectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            p = vault.create_project(dlg.project_name(), dlg.project_text())
        except (VaultError, OSError) as exc:
            QMessageBox.warning(self, tr("Progetto"), tr("Non riesco a creare il progetto: {exc}").format(exc=exc))
            return
        self._open_project(p.slug, remind=True)

    def _set_project(self, project, announce: bool = True):
        self.project = project
        self.settings.set("active_project", project.slug if project else None)
        self._project_saved_at = len(self.session.messages)
        if project is not None:
            self.session.project = project.slug
        self._refresh_agent_project()
        self._update_project_button()
        if announce and project is not None:
            self.notify(tr("Progetto «{name}» aperto.").format(name=project.name))

    def _close_project(self):
        if not self._remind_project(tr("chiudere il progetto")):
            return
        self._set_project(None, announce=False)
        self.notify(tr("Nessun progetto aperto: le chat nuove partono senza contesto."))

    def _open_project(self, slug: str, remind: bool = True):
        vault = self._vault_open()
        if vault is None:
            return
        if remind and self.project is not None and self.project.slug != slug and \
                not self._remind_project(tr("cambiare progetto")):
            return
        try:
            project = vault.project(slug)
        except KeyError:
            QMessageBox.warning(self, tr("Progetto"), tr("Progetto non trovato."))
            return
        self._set_project(project, announce=False)
        self._start_project_chat()

    def _start_project_chat(self):
        """Task nuovo collegato al progetto, con il contesto: incollato (web), nel messaggio di sistema (API) o nei
        file delle istruzioni (agenti)."""
        p = self.project
        if p is None:
            return
        self._skip_reminder = True
        try:
            self.new_session()
        finally:
            self._skip_reminder = False
        self.session.project = p.slug
        self._project_saved_at = 0
        if self.engine == "web":
            text = self._private(pj.context_text(p.name, p.text(), p.index_text()))
            if isinstance(text, tuple):
                text = text[0]
            self.web.paste_package(text, [])
            self.notify(tr("Progetto «{name}»: contesto incollato in una chat nuova, controlla e premi Invio.").format(
                name=p.name), 9000)
        elif self.engine == "agent":
            self.notify(tr("Progetto «{name}»: l'agente riparte con il contesto nelle istruzioni.").format(name=p.name),
                        8000)
        else:
            from ..session import Message
            n = pj.estimate_tokens(pj.context_text(p.name, p.text(), p.index_text(), for_chat=False))
            note = Message("note", tr("Progetto «{name}»: il contesto (~{n} token) va all'IA con ogni richiesta.").format(
                name=p.name, n=n))
            self.chat.add_message(note)

    def _project_system_text(self) -> str:
        """Aggiunta al messaggio di sistema del motore API (vuota senza progetto o con il vault bloccato)."""
        p = self.project
        if p is None or not (self.vault and self.vault.is_open):
            return ""
        if self.session.project != p.slug:  # task fuori dal progetto (es. finestra rapida)
            return ""
        try:
            return "\n\nPROGETTO ATTIVO\n" + pj.context_text(p.name, p.text(), p.index_text(), for_chat=False)
        except (KeyError, VaultError):
            return ""

    def _refresh_agent_project(self):
        p = self.project
        text = None
        if p is not None and self.vault and self.vault.is_open:
            try:
                text = pj.context_text(p.name, p.text(), p.index_text(), for_chat=False,
                                       agent_cmds=agents.vault_commands())
                text = "## " + tr("Progetto attivo") + "\n\n" + text
            except (KeyError, VaultError):
                text = None
        agents.set_project_context(text)
        if self.agent is not None:
            try:
                agents.write_context(self.agent.key)
            except OSError:
                pass

    # ------------------------------------------------------------ salvataggio
    def save_project(self, compact: bool = False):
        p = self.project
        if p is None:
            self.notify(tr("Nessun progetto aperto."))
            return
        if self._vault_open() is None:
            return
        text = p.text()
        self._project_request = {"slug": p.slug, "compact": compact, "at": time.time()}
        source = self._source_label()
        if self.engine == "agent" and self.agent:
            panel = self.agent
            panel.request_project(agents.project_update_request(compact, text))
            self.notify(tr("Chiedo a {name} l'aggiornamento del progetto: lo scrive su file e Helpix lo legge…").format(
                name=source), 8000)
            return
        request = pj.compact_request(text) if compact else pj.update_request(text)
        request = self._private(request)
        if isinstance(request, tuple):
            request = request[0]
        from .web_panel import WEB_SITES
        if self.engine == "web" or self.session.site in WEB_SITES:
            src = self._task_site()
            if self.engine != "web":
                self._apply_engine("web")
            self.web.set_site(src)
            self._update_picker()
            if self.web.is_external(src):
                self.web.paste_text(request)
                self.notify(tr("Richiesta incollata nel browser: invia, poi copia il blocco della risposta con il "
                               "pulsante Copia."), 12000)
                return
            if self.web.summary_pending:
                self.notify(tr("Sto già aspettando una risposta dall'IA: riprova tra poco."))
                return
            self.web.request_summary(request, marker=pj.PROJECT_MARKER)
            self.notify(tr("Chiedo a {name} l'aggiornamento del progetto: lo invio e leggo la risposta…").format(
                name=WEB_SITES[src]["label"]), 8000)
            return
        # motore API: una chiamata a parte, che non entra nella conversazione
        from ..providers import PROVIDERS, chat as provider_chat
        from .workers import FuncWorker
        pid, model = self.session.provider, self.session.model
        prov = PROVIDERS[pid]
        key = self.secrets.get(pid) if prov["needs_key"] else ""
        wire = self.session.to_wire(prov["vision"], max_images=0) + [{"role": "user", "text": request, "images": []}]
        w = FuncWorker(provider_chat, pid, model, key, self._system_prompt(), wire,
                       base_url=self.settings.base_url_for(pid), effort=self._api_effort(), parent=self)
        w.done.connect(lambda answer: (self._project_update_received(pj.parse_update(answer)) if pj.parse_update(answer)
                                       else self._project_update_failed(tr("La risposta non contiene il blocco "
                                                                           "{marker}.").format(marker=pj.PROJECT_MARKER))))
        w.failed.connect(lambda exc: self._project_update_failed(tr("Errore dall'IA: {exc}").format(exc=exc)))
        self._start(w)
        self.notify(tr("Chiedo l'aggiornamento del progetto a {name}…").format(name=prov["label"]), 6000)

    def _project_update_failed(self, message: str):
        self.notify(message, 12000)

    def _project_update_received(self, update):
        if update is None:
            return
        p = self.project
        if p is None or not (self.vault and self.vault.is_open):
            self.notify(tr("Aggiornamento del progetto ricevuto, ma nessun progetto è aperto."), 8000)
            return
        signature = (p.slug, repr(update))
        if signature == getattr(self, "_last_signature", None):
            self.notify(tr("Questo aggiornamento del progetto è già stato salvato."))
            return
        req, self._project_request = self._project_request, None
        if self.agent is not None:
            self.agent.cancel_project()
        try:
            current = p.text()
        except (KeyError, VaultError) as exc:
            self.notify(str(exc), 8000)
            return
        result = pj.apply_update(current, update)
        self._pending_signature = signature
        source = self._source_label()
        compact = update.full_text is not None
        if self.settings.get("project_update_mode") == "auto" and not compact and not (req or {}).get("compact"):
            self._commit_project(result.text, update.title, update.body, result, source)
            extra = f" ({len(result.warnings)} " + tr("non applicate") + ")" if result.warnings else ""
            self.notify(tr("Progetto aggiornato{extra}. Per tornare indietro: Progetto › Annulla l'ultimo "
                           "aggiornamento.").format(extra=extra), 10000)
            return
        from .vault_dialogs import ProjectSaveDialog
        dlg = ProjectSaveDialog(p.name, update, result, source, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.notify(tr("Aggiornamento del progetto annullato: niente è cambiato."))
            return
        title, body = dlg.note()
        if compact:
            title, body = "", ""
        self._commit_project(dlg.project_text(), title, body, result, source)
        self.notify(tr("Progetto «{name}» salvato.").format(name=p.name))

    def _commit_project(self, text: str, title: str, body: str, result, source: str):
        p = self.project
        keep = int(self.settings.get("project_versions", 20))
        try:
            version = p.save_text(text, keep=keep)
            note = None
            if title or body:
                note_md = pj.note_text(title or tr("Sessione"), body, source, result.superseded, result.warnings)
                note = p.add_note(title or tr("Sessione"), note_md, pj.note_summary(body))
            if self.session.messages and self._in_project():
                p.write_session_draft(self.session.id, pj.session_markdown(self.session))
        except (VaultError, OSError) as exc:
            QMessageBox.warning(self, tr("Progetto"), tr("Salvataggio non riuscito: {exc}").format(exc=exc))
            return
        self._last_update = {"slug": p.slug, "version": version, "note": note, "at": time.time()}
        self._last_signature = getattr(self, "_pending_signature", None)
        self._project_saved_at = len(self.session.messages)
        self._refresh_agent_project()
        if self.vault_panel is not None:
            self.vault_panel.reload()
        if pj.estimate_tokens(pj.strip_private(text)) > pj.TOKEN_LIMIT:
            QTimer.singleShot(1500, lambda: self.notify(tr("Il progetto supera i {n} token: conviene compattarlo "
                                                           "(Progetto › Compatta il progetto).").format(
                n=pj.TOKEN_LIMIT), 9000))

    def _undo_project_update(self):
        last, self._last_update = self._last_update, None
        self._last_signature = None  # dopo «Annulla» lo stesso aggiornamento si può applicare di nuovo
        if not last or self.project is None or self.project.slug != last["slug"]:
            return
        try:
            if last["version"]:
                self.project.restore_version(last["version"])
            if last["note"]:
                self.project.delete_note(last["note"])
        except (VaultError, OSError, KeyError) as exc:
            QMessageBox.warning(self, tr("Progetto"), str(exc))
            return
        self._refresh_agent_project()
        if self.vault_panel is not None:
            self.vault_panel.reload()
        self.notify(tr("Ultimo aggiornamento del progetto annullato."))

    # ------------------------------------------------------------ note chieste dall'IA
    def _find_note(self, title: str) -> tuple[str, str] | None:
        p = self.project
        if p is None or not (self.vault and self.vault.is_open):
            return None
        rel = p.resolve(title)
        if not rel:
            return None
        try:
            text = p.read_text(rel)
        except KeyError:
            return None
        if rel == p.rel("PROJECT.md"):
            text = pj.strip_private(text)
        return pj.title_of(text) or title, text

    def _note_requested(self, title: str):
        if self.project is None:
            self.notify(tr("L'IA chiede una nota, ma nessun progetto è aperto."), 7000)
            return
        if self._vault_open() is None:
            return
        found = self._find_note(title)
        if not found:
            self.notify(tr("Nota «{title}» non trovata nel progetto: cercala in Progetto › Apri il vault.").format(
                title=title), 9000)
            return
        self.note_bar.ask(*found)

    def _paste_note(self, payload):
        title, text = payload
        out = self._private(pj.note_paste(title, text))
        if isinstance(out, tuple):
            out = out[0]
        if self.engine == "agent" and self.agent:
            self.agent.paste(out)
        else:
            self.web.paste_text(out)

    def _check_api_note_request(self, answer: str):
        """Motore API: se la risposta chiede una nota, Helpix chiede conferma prima di inviarla."""
        if not self._in_project():
            return
        title = pj.parse_note_request(answer or "")
        if not title:
            return
        found = self._find_note(title)
        if not found:
            self.notify(tr("L'IA chiede la nota «{title}», che non c'è nel progetto.").format(title=title), 8000)
            return
        if QMessageBox.question(self, tr("Nota del progetto"),
                                tr("L'IA chiede la nota «{title}» (~{n} token). Inviarla?").format(
                                    title=found[0], n=pj.estimate_tokens(found[1]))) == QMessageBox.StandardButton.Yes:
            self.prompt.setPlainText(pj.note_paste(*found))
            self.send_message()

    # ------------------------------------------------------------ promemoria e bozze
    def _in_project(self) -> bool:
        """Il task attuale appartiene al progetto aperto (non, per esempio, un task della finestra rapida)."""
        return self.project is not None and self.session.project == self.project.slug

    def _project_dirty(self) -> bool:
        if not self._in_project():
            return False
        new = self.session.messages[self._project_saved_at:]
        return any(m.kind in ("output", "diagnostics", "summary", "chat", "shot") and m.role != "note" for m in new)

    def _remind_project(self, action: str) -> bool:
        """«Salvare nel progetto?» prima di un'azione. False = l'azione si ferma (si salva prima)."""
        if getattr(self, "_skip_reminder", False) or not self.settings.get("project_reminder", True):
            return True
        if not self._project_dirty():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(tr("Progetto"))
        box.setText(tr("Ci sono novità non salvate nel progetto «{name}». Salvarle prima di {action}?").format(
            name=self.project.name, action=action))
        save = box.addButton(tr("Salva prima"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Non ora"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            self.save_project()
            self.notify(tr("Salvo il progetto: quando hai confermato l'anteprima, ripeti l'operazione."), 9000)
            return False
        self._project_saved_at = len(self.session.messages)  # «Non ora»: non lo richiedo per le stesse novità
        return True

    def _write_draft(self):
        p = self.project
        if not self._in_project() or not self.session.messages or not (self.vault and self.vault.is_open):
            return
        marker = (self.session.id, len(self.session.messages))
        if marker == self._draft_marker:
            return
        try:
            p.write_session_draft(self.session.id, pj.session_markdown(self.session))
            self._draft_marker = marker
        except (VaultError, OSError) as exc:
            log.warning("Bozza della sessione non salvata: %s", exc)

    # ------------------------------------------------------------ pannello, impostazioni, blocco
    def open_vault_panel(self):
        vault = self._vault_open()
        if vault is None:
            return
        from .vault_panel import VaultPanel
        if self.vault_panel is not None:
            self.vault_panel.reload()
            self.vault_panel.show()
            self.vault_panel.raise_()
            self.vault_panel.activateWindow()
            return
        # nessun genitore: è una finestra a sé, non resta sempre sopra a Helpix; stessa barra integrata di Helpix
        panel = VaultPanel(vault, None, active=self.project.slug if self.project else None,
                           keep_versions=int(self.settings.get("project_versions", 20)),
                           assistant=self._source_label, frameless=self.frameless,
                           rounded=getattr(self, "rounded", False))
        panel._fit_to_screen(self)
        panel.resume.connect(lambda slug: self._open_project(slug))
        panel.paste.connect(self._paste_text_anywhere)
        panel.lock_requested.connect(self.lock_vault)
        panel.export_requested.connect(self.export_vault)
        panel.changed.connect(lambda slug: self._refresh_agent_project()
                              if self.project and self.project.slug == slug else None)
        panel.finished.connect(lambda _r: setattr(self, "vault_panel", None))
        panel.tour_requested.connect(lambda: self.start_vault_tour(panel))
        panel.project_deleted.connect(self._project_deleted)
        panel.changed.connect(lambda _slug: self._update_project_button())
        self.vault_panel = panel
        panel.show()
        if not self.settings.get("vault_tour_done"):  # prima apertura: il giro del pannello
            QTimer.singleShot(400, lambda: self.start_vault_tour(panel))

    def _project_deleted(self, slug: str):
        """Progetto spostato nel cestino: se era quello aperto, si chiude."""
        if self.project is not None and self.project.slug == slug:
            self._set_project(None, announce=False)
            self.notify(tr("Progetto spostato nel cestino del vault: le chat nuove partono senza contesto."), 8000)
        if self.settings.get("active_project") == slug:
            self.settings.set("active_project", None)
        self._update_project_button()

    def delete_current_project(self):
        """Progetto › Elimina il progetto…: apre il pannello sul progetto e chiede conferma."""
        if self.project is None:
            return
        slug = self.project.slug
        self.open_vault_panel()
        if self.vault_panel is not None:
            self.vault_panel._delete_project(slug)

    def _paste_text_anywhere(self, text: str):
        out = self._private(text)
        if isinstance(out, tuple):
            out = out[0]
        if self.engine == "agent" and self.agent:
            self.agent.paste(out)
        elif self.engine == "web":
            self.web.paste_text(out)
        else:
            self.prompt.setPlainText(out)
        self.notify(tr("Nota incollata: controlla e invia."))

    def open_project_settings(self):
        from .vault_dialogs import ProjectSettingsDialog
        dlg = ProjectSettingsDialog(self.settings, lambda: self._get_vault(), self,
                                    system_unlock=self._vault_system_unlock)
        dlg.changed.connect(lambda: (self._apply_project_settings(), self._update_project_button()))
        dlg.export_requested.connect(self.export_vault)
        dlg.exec()
        self._apply_project_settings()

    def toggle_projects_beta(self, on: bool):
        if bool(on) == self.projects_enabled:
            return
        self.settings.set("projects_beta", bool(on))
        self._apply_project_settings()
        if on:
            self.notify(tr("Progetti e vault (beta) attivi: trovi il selettore Progetto nella barra."), 8000)
            if not self.settings.get("projects_tour_done"):  # la prima volta: il giro a nuvolette
                QTimer.singleShot(500, self.start_projects_tour)

    # ------------------------------------------------------------ giri guidati
    def start_projects_tour(self):
        from .tour import Tour, project_steps
        if not self.projects_enabled or getattr(self, "_ptour", None) is not None:
            return
        if getattr(self, "tour", None) is not None:
            self.tour.close_tour(mark_done=False)
        self._ptour = Tour(self, "tour", steps=project_steps(self), done_key="projects_tour_done")
        self._ptour.finished.connect(lambda: setattr(self, "_ptour", None))

    def start_vault_tour(self, panel=None):
        from .tour import Tour, vault_steps
        panel = panel or self.vault_panel
        if panel is None or getattr(panel, "_tour", None) is not None:
            return
        panel._tour = Tour(self, "tour", steps=vault_steps(panel), host=panel, done_key="vault_tour_done")
        panel._tour.finished.connect(lambda: setattr(panel, "_tour", None))

    def lock_vault(self):
        vault = self.vault
        if vault is None or not vault.encrypted:
            return
        if self.vault_panel is not None:
            self.vault_panel.editor.document().setModified(False)  # il blocco vince sulle modifiche aperte
            self.vault_panel.close()
            self.vault_panel = None
        vault.lock()
        self.note_bar.hide()
        agents.set_project_context(None)
        if self.agent is not None:
            try:
                agents.write_context(self.agent.key)
            except OSError:
                pass
        self._update_project_button()

    def export_vault(self):
        vault = self._vault_open()
        if vault is None:
            return
        base = QFileDialog.getExistingDirectory(self, tr("Dove esporto il vault in chiaro?"), str(Path.home()))
        if not base:
            return
        dest = Path(base) / f"Helpix-vault-{time.strftime('%Y%m%d-%H%M')}"
        try:
            n = vault.export_plain(dest)
        except (VaultError, OSError) as exc:
            QMessageBox.warning(self, tr("Vault"), tr("Esportazione non riuscita: {exc}").format(exc=exc))
            return
        QMessageBox.information(self, tr("Vault"), tr("{n} file esportati in chiaro in:\n{path}\n\nRicordati che "
                                                      "questa copia non è cifrata.").format(n=n, path=dest))

    # ------------------------------------------------------------ helpix vault … (agenti)
    def _vault_request(self, msg: dict) -> dict:
        if getattr(self, "locked", False):
            return {"ok": False, "text": "Helpix è bloccato: sbloccalo e riprova."}
        p = self.project
        if not self.projects_enabled or p is None:
            return {"ok": False, "text": "Nessun progetto aperto in Helpix."}
        if not (self.vault and self.vault.is_open):
            return {"ok": False, "text": "Il vault è bloccato: sbloccalo in Helpix e riprova."}
        op, query = msg.get("op"), str(msg.get("q", ""))
        try:
            if op == "project":
                text, ok = pj.strip_private(p.text()), True
            elif op == "cat":
                found = self._find_note(query)
                text, ok = (found[1], True) if found else (f"Nota non trovata: {query}. Prova con: vault search", False)
            elif op == "search":
                # niente righe della sezione «Solo per me»: non escono mai verso un'IA
                private = pj.parse(p.text()).find("private")
                hidden = {ln.strip() for ln in (private[1] if private else []) if ln.strip()}
                hits = [(rel, line) for rel, line in p.search(query)
                        if not (rel == p.rel("PROJECT.md") and (line in hidden or pj.section_key(line.lstrip("# "))
                                                                == "private"))]
                base = len(p.rel()) + 1
                text = "\n".join(f"{rel[base:]}: {line}" for rel, line in hits) or "Nessun risultato."
                ok = bool(hits)
            else:
                return {"ok": False, "text": "Operazione sconosciuta."}
        except (KeyError, VaultError) as exc:
            return {"ok": False, "text": str(exc)}
        out = self._private(text)
        return {"ok": ok, "text": out[0] if isinstance(out, tuple) else out}

    def _projects_on_lock(self):
        """Il blocco di Helpix chiude anche il vault cifrato."""
        vault = getattr(self, "vault", None)  # il blocco all'avvio arriva prima della preparazione dei progetti
        if vault is not None and vault.encrypted and vault.is_open:
            self.lock_vault()

    def _projects_on_quit(self) -> bool:
        if self.project is not None:
            self._write_draft()
            if not self._remind_project(tr("uscire da Helpix")):
                return False
        if self.vault_panel is not None:  # finestra a sé: si chiude con Helpix
            self.vault_panel.close()
        return True
