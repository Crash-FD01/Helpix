# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra principale di Helpix.

Due motori dietro la stessa interfaccia:
- Web (predefinito): la chat ufficiale con il tuo account; Helpix incolla screenshot e output
  e ti propone di eseguire i comandi che copi.
- API (avanzato): Helpix parla direttamente con l'IA, esegue i comandi con un clic e
  rimanda l'output da solo.
Il terminale e l'albero delle cartelle compaiono solo in modalità tecnico.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QDir, QEvent, QProcess, Qt, QTimer
from PySide6.QtGui import QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFileSystemModel, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QTreeView,
    QVBoxLayout, QWidget,
)

from ..system import IS_WINDOWS
from .. import __version__, theme
from ..diagnostics import collect as collect_diagnostics
from .. import agents
from ..bridge import BridgeServer
from ..executor import CommandRunner, analyze, looks_like_command, pkexec_available
from ..icons import icon
from ..prompts import build_system_prompt
from ..providers import PROVIDERS, chat as provider_chat, list_models
from ..screenshot import normalize_image
from ..session import Message, Session
from ..theme import C, app_icon, mono_font
from .chat import IMAGE_EXTS, AttachmentStrip, ChatView, PromptEdit
from .command_bar import CommandBar, format_output_for_chat
from .controls import Capsule, IconButton, Toast, VSep, WindowControls
from .dialogs import SessionsDialog
from .frameless import FramelessHelper, RoundedCentral
from .handoff_dialog import HandoffDialog
from .transfer_bar import TransferBar
from .. import site_icons
from ..task import EXTENSION, export_task, import_task, record_summary, summary_request
from ..task import parse_summary
from .setup_dialog import SetupDialog
from .shot_controller import ScreenshotController
from .terminal import TerminalPanel, pretty_path
from .web_panel import WEB_SITES, WEBENGINE, WebPanel
from .workers import FuncWorker
from ..i18n import LANGUAGES, current as current_language, tr

SOURCE_URL = "https://github.com/Crash-FD01/Helpix"
MAX_SHARE = 12_000  # caratteri di output inviati all'IA per comando (motore API)


class PickerButton(QPushButton):
    """Selettore dell'assistente nella barra: avatar, nome, stato, freccia."""

    def __init__(self):
        super().__init__()
        self.setObjectName("picker")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(32)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 10, 0)
        h.setSpacing(8)
        self.avatar = QLabel()
        self.avatar.setFixedSize(20, 20)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 600;")
        self.status = QLabel()
        self.status.setObjectName("secondary")
        self.chev = QLabel()
        for w in (self.avatar, self.name, self.status, self.chev):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            h.addWidget(w)
        self._key = "chatgpt"
        theme.manager().changed.connect(lambda _d: self._icons())
        site_icons.notifier.changed.connect(lambda key: self._icons() if key == self._key else None)

    def set_agent(self, key: str, name: str, status: str):
        self._key = key
        self.name.setText(name)
        self.status.setText(status)
        self.setAccessibleName(tr("Assistente: {name}, {status}. Apri il menu").format(name=name, status=status))
        self.setToolTip(tr("Scegli l'assistente o cambia motore"))
        self._icons()
        self.setMinimumWidth(self.layout().sizeHint().width())

    def _icons(self):
        self.avatar.setPixmap(site_icons.pixmap(self._key, 20))
        self.chev.setPixmap(icon("chevron-down", C["secondary"], 14, 2).pixmap(14, 14))


class DiagnosticsPreview(QDialog):
    """Mostra (e permette di modificare) i dati prima di incollarli nella chat."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Diagnosi rapida"))
        self.resize(720, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        title = QLabel(tr("Diagnosi rapida"))
        title.setObjectName("title")
        v.addWidget(title)
        info = QLabel(tr("Questi dati verranno incollati nella chat. Contengono il nome del PC e gli indirizzi di "
                      "rete: puoi modificarli o cancellare ciò che non vuoi condividere."))
        info.setWordWrap(True)
        info.setObjectName("secondary")
        v.addWidget(info)
        self.edit = QPlainTextEdit(text)
        self.edit.setFont(mono_font(10))
        v.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(tr("Incolla nella chat"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


def stop_quick_window(only_if_stale: bool = False) -> None:
    """Chiude la finestra rapida (processo separato).

    only_if_stale: solo se è di un'altra versione di Helpix. Dopo un aggiornamento può restare in giro la
    finestra rapida della versione prima, che non conosce «quit» e riapriva Helpix appena lo chiudevi:
    quella va terminata (si riapre aggiornata con Ctrl+Alt+H)."""
    from .. import __version__
    from ..instance import is_running, peer_pid, request, send_once
    from ..system import is_helpix_quick, process_alive, terminate
    from .quick_window import quick_socket_path
    path = quick_socket_path()
    if not is_running(path):
        return
    reply = request({"type": "ping"}, path, timeout=1.0)
    current = bool(reply and reply.get("version") == __version__)
    if only_if_stale and current:
        return
    pid = peer_pid(path)
    if current:
        send_once({"type": "quit"}, path)
        deadline = time.monotonic() + 1.5
        while pid and time.monotonic() < deadline and process_alive(pid):
            time.sleep(0.05)
    # versione vecchia (o bloccata): solo se è davvero la finestra rapida di Helpix
    if pid and process_alive(pid) and is_helpix_quick(pid) and terminate(pid):
        logging.getLogger(__name__).info("finestra rapida di un'altra versione terminata (pid %s)", pid)


class MainWindow(QMainWindow):
    def __init__(self, settings, secrets, engine: str | None = None,
                 provider: str | None = None, model: str | None = None):
        super().__init__()
        self.settings, self.secrets = settings, secrets
        self.engine = engine or settings.get("engine", "web")
        if self.engine in ("web", "agent") and not WEBENGINE:
            self.engine = "api"
        self.agent = None  # pannello degli agenti nel terminale, creato al primo uso
        self.frameless = not settings.get("system_titlebar", False)
        self._workers: set = set()
        self.runner: CommandRunner | None = None
        self.busy = False
        cwd = settings.get("last_cwd") or str(Path.home())
        if not os.path.isdir(cwd):
            cwd = str(Path.home())
        self.prev_cwd = cwd
        provider = provider if provider in PROVIDERS else settings.get("default_provider", "anthropic")
        if provider not in PROVIDERS:
            provider = "anthropic"
        self.session = Session(provider, model or settings.model_for(provider), cwd)

        self.setWindowTitle("Helpix")
        self.setWindowIcon(app_icon())
        self.resize(1120, 800)
        self.setMinimumSize(760, 520)
        self.shots = ScreenshotController(self, settings)
        self.shots.captured.connect(self._shot_ok)
        self.shots.failed.connect(lambda msg: QMessageBox.warning(
            self, "Screenshot", tr("{msg}\n\nIn alternativa usa il tuo strumento di cattura e incolla l'immagine con Ctrl+V.").format(msg=msg)))
        self.shots.finished.connect(self._restore)

        self._ext_request = None   # comando partito dall'estensione del browser
        self._ext_shot = None      # screenshot chiesto dal browser
        self._ext_diag = None      # diagnosi chiesta dal browser
        self._quick_shot = None    # screenshot chiesto dalla finestra rapida
        self._build_ui()
        self._start_bridge()
        self._start_instance()
        self._setup_lock()
        self._setup_tray()
        if self.frameless:
            self._frameless = FramelessHelper(self, self.toolbar)
        self._set_cwd(cwd)
        self._welcome()
        self._apply_engine(self.engine, initial=True)
        self._set_tech_mode(bool(settings.get("tech_mode", False)))
        if settings.get("always_on_top"):
            self.act_pin.setChecked(True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        theme.manager().changed.connect(lambda _d: self._theme_changed())
        self._theme_changed()
        site_icons.refresh_in_background(self)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.toolbar = QFrame()
        self.toolbar.setObjectName("toolbar")
        self.toolbar.setFixedHeight(52)
        th = QHBoxLayout(self.toolbar)
        th.setContentsMargins(14, 0, 10, 0)
        th.setSpacing(8)
        logo = QLabel()
        logo.setFixedSize(28, 28)
        logo.setPixmap(theme.logo_pixmap(28))
        logo.setToolTip(f"Helpix {__version__}")
        th.addWidget(logo)
        self.picker = PickerButton()
        self.picker_menu = theme.prepare_menu(QMenu(self))
        self.picker_menu.aboutToShow.connect(self._build_picker_menu)
        self.picker.setMenu(self.picker_menu)
        th.addWidget(self.picker)
        self.model_btn = IconButton("cpu", tr("Modello"), text="model", icon_size=15, color_key="secondary")
        self.model_btn.setObjectName("pill")
        self.model_btn.setPopupMode(IconButton.ToolButtonPopupMode.InstantPopup)
        self.model_menu = theme.prepare_menu(QMenu(self))
        self.model_menu.aboutToShow.connect(self._build_model_menu)
        self.model_btn.setMenu(self.model_menu)
        th.addWidget(self.model_btn)
        th.addStretch(1)

        shot_menu = theme.prepare_menu(QMenu(self))
        self._shot_actions = [
            (shot_menu.addAction(tr("Area o finestra"), lambda: self.shots.start("smart")), "crop"),
            (shot_menu.addAction(tr("Finestra (dialogo di sistema)"), lambda: self.shots.start("window")), "window"),
            (shot_menu.addAction(tr("Schermo intero"), lambda: self.shots.start("full")), "monitor"),
            (shot_menu.addAction(tr("Area dopo 3 secondi"), lambda: self.shots.start("smart", delay=3)), "timer"),
        ]
        shot_menu.addSeparator()
        self._shot_actions.append((shot_menu.addAction(tr("Allega immagine da file…"), self.attach_files), "image"))
        self.shot = Capsule("Screenshot", "camera", shot_menu, menu_tip=tr("Altre modalità di cattura"))
        self.shot.clicked.connect(lambda: self.shots.start("smart"))
        th.addWidget(self.shot)
        self.btn_diag = IconButton("pulse", tr("Raccoglie le informazioni del PC e le incolla nella chat"),
                                   text=tr("Diagnosi"), icon_size=16)
        self.btn_diag.setObjectName("pill")
        self.btn_diag.clicked.connect(self.quick_diagnostics)
        th.addWidget(self.btn_diag)
        self.btn_privacy = IconButton("shield", "", checkable=True)
        self.btn_privacy.setChecked(bool(self.settings.get("privacy_filter", False)))
        self.btn_privacy.toggled.connect(self._set_privacy)
        self._privacy_look()
        self._sync_privacy()
        th.addWidget(self.btn_privacy)
        th.addSpacing(2)
        th.addWidget(VSep())
        self.btn_tech = IconButton("terminal", tr("Modalità tecnico: terminale e cartelle (Ctrl+`)"), checkable=True)
        self.btn_tech.toggled.connect(self._set_tech_mode)
        th.addWidget(self.btn_tech)
        self.btn_theme = IconButton("moon", tr("Tema scuro"))
        self.btn_theme.clicked.connect(self._toggle_theme)
        th.addWidget(self.btn_theme)
        self.btn_gear = IconButton("gear", tr("Impostazioni"))
        self.btn_gear.setPopupMode(IconButton.ToolButtonPopupMode.InstantPopup)
        self.btn_gear.setMenu(self._build_gear_menu())
        th.addWidget(self.btn_gear)
        if self.frameless:
            th.addWidget(VSep())
            self.win_controls = WindowControls(self)
            th.addWidget(self.win_controls)

        # --- motore web
        self.web = WebPanel(self.settings.start_site(), external=self.settings.get("external_sites", ["gemini"]))
        self.web.google_signin.connect(self._google_signin)
        self.web.use_integrated.connect(lambda site: self._set_site_external(site, False))
        self.web.keep_on_top.connect(lambda: self.act_pin.setChecked(True))
        self._google_dismissed: set[str] = set()
        self.web.site_changed.connect(lambda _s: (self.command_bar.hide(), self._update_transfer_bar()))
        self.web.hint.connect(self.notify)
        self.web.command_copied.connect(self._command_copied)
        self.web.summary_copied.connect(self._summary_received)
        self.web.summary_failed.connect(self._summary_failed)
        self.web.package_done.connect(self._package_done)
        self.web.connect_browser.connect(self.open_browser_dialog)
        self.handoff: HandoffDialog | None = None
        self.command_bar = CommandBar()
        self.command_bar.run_requested.connect(lambda cmd: self.run_command(cmd, "web"))
        self.command_bar.paste_requested.connect(lambda text: self.web.paste_text(text))
        self.command_bar.show_terminal.connect(lambda: self._set_tech_mode(True))
        web_page = QWidget()
        wl = QVBoxLayout(web_page)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(self.web, 1)
        self.transfer_bar = TransferBar()
        self.transfer_bar.transfer.connect(self._transfer_bar_primary)
        self.transfer_bar.back.connect(self._transfer_bar_secondary)
        self._bar_mode = "transfer"
        transfer_wrap = QWidget()
        transfer_wrap.setObjectName("transferWrap")
        tw = QHBoxLayout(transfer_wrap)
        tw.setContentsMargins(16, 10, 16, 0)
        tw.addWidget(self.transfer_bar)
        wl.addWidget(transfer_wrap)
        self.transfer_bar.setVisible(False)
        bar_wrap = QWidget()
        bar_wrap.setObjectName("commandWrap")
        bw = QHBoxLayout(bar_wrap)
        bw.setContentsMargins(16, 10, 16, 12)
        bw.addWidget(self.command_bar)
        wl.addWidget(bar_wrap)
        self.command_bar.setVisible(False)

        # --- motore API
        self.chat = ChatView({"run": lambda cmd, card: self.run_command(cmd, "ai", card),
                              "edit": self._edit_command, "retry": self.request_ai})
        self.chat.setObjectName("chatScroll")
        composer = QFrame()
        composer.setObjectName("composer")
        cv = QVBoxLayout(composer)
        cv.setContentsMargins(16, 10, 16, 14)
        cv.setSpacing(8)
        self.attachments = AttachmentStrip()
        cv.addWidget(self.attachments)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.prompt = PromptEdit()
        self.prompt.setFixedHeight(64)
        self.prompt.submitted.connect(self.send_message)
        self.prompt.image_added.connect(self._add_attachment)
        row.addWidget(self.prompt, 1)
        self.btn_send = QPushButton(tr("Invia"))
        self.btn_send.setObjectName("primary")
        self.btn_send.setMinimumWidth(84)
        self.btn_send.clicked.connect(self.send_message)
        row.addWidget(self.btn_send, 0, Qt.AlignmentFlag.AlignBottom)
        cv.addLayout(row)
        api_page = QWidget()
        al = QVBoxLayout(api_page)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        al.addWidget(self.chat, 1)
        al.addWidget(composer)

        self.stack = QStackedWidget()
        self.stack.addWidget(web_page)
        self.stack.addWidget(api_page)

        # --- terminale e cartelle (modalità tecnico)
        self.terminal = TerminalPanel()
        self.terminal.command_entered.connect(lambda cmd: self.run_command(cmd, "user"))
        self.terminal.stop_requested.connect(self.stop_command)
        self.terminal.browse_requested.connect(self.browse_dir)
        self.terminal.cd_requested.connect(self.change_dir)
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.fs_model.setRootPath("/")
        self.tree = QTreeView()
        self.tree.setObjectName("sidebar")
        self.tree.setModel(self.fs_model)
        self.tree.setRootIndex(self.fs_model.index("/"))
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setToolTip(tr("Doppio clic per spostare il terminale in questa cartella"))
        self.tree.activated.connect(lambda idx: self.change_dir(self.fs_model.filePath(idx)))

        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.addWidget(self.stack)
        self.vsplit.addWidget(self.terminal)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.setSizes([560, 230])
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.addWidget(self.tree)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setSizes([220, 900])

        self.rounded = self.frameless and bool(self.settings.get("rounded_corners", True))
        if self.rounded:
            # finestra trasparente: lo sfondo con gli angoli arrotondati lo dipinge RoundedCentral
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setProperty("rounded", "true")
            self.toolbar.setProperty("rounded", "true")
            self.central = RoundedCentral(self.toolbar)
        else:
            self.central = QWidget()
        self.central.setObjectName("central")
        self.central.setProperty("frameless", "true" if self.frameless else "false")
        self.central.setProperty("rounded", "true" if self.rounded else "false")
        cl = QVBoxLayout(self.central)
        m = 1 if self.frameless else 0
        cl.setContentsMargins(m, m, m, m)
        cl.setSpacing(0)
        cl.addWidget(self.toolbar)
        cl.addWidget(self.hsplit, 1)
        self.setCentralWidget(self.central)
        if self.rounded:
            self.central.set_square(False)
        self.statusBar().hide()
        self.toast = Toast(self.central)

        self._sc_new = QShortcut(QKeySequence("Ctrl+N"), self, self.new_session)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, lambda: self.shots.start("smart"))
        QShortcut(QKeySequence("Ctrl+`"), self, self.btn_tech.toggle)
        self._sc_term = QShortcut(QKeySequence("Ctrl+L"), self, self.terminal.input.setFocus)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, self._toggle_theme)

    def _build_gear_menu(self) -> QMenu:
        menu = theme.prepare_menu(QMenu(self))
        menu.addAction(icon("key", C["text"], 16), tr("Chiavi API e modelli…"), self.open_settings)
        menu.addAction(icon("lock", C["text"], 16), tr("Sicurezza…"), self.open_security)
        menu.addAction(icon("download", C["text"], 16), tr("Dipendenze di sistema…"), self.check_system_deps)
        menu.addAction(icon("info", C["text"], 16), tr("Guida rapida (giro guidato)"), self.start_tour)
        menu.addAction(icon("star", C["text"], 16), tr("Schermata iniziale…"), self.open_start_screen)
        self.act_start_screen = menu.addAction(tr("Mostra la schermata iniziale all'avvio"))
        self.act_start_screen.setCheckable(True)
        self.act_start_screen.setChecked(not self.settings.get("skip_setup", False))
        self.act_start_screen.toggled.connect(lambda on: self.settings.set("skip_setup", not on))
        self.act_tips = menu.addAction(tr("Mostra i suggerimenti all'avvio"))
        self.act_tips.setCheckable(True)
        self.act_tips.setChecked(bool(self.settings.get("show_tips", True)))
        self.act_tips.toggled.connect(lambda on: self.settings.set("show_tips", bool(on)))
        menu.aboutToShow.connect(lambda: (self.act_tips.setChecked(bool(self.settings.get("show_tips", True))),
                                          self.act_start_screen.setChecked(not self.settings.get("skip_setup",
                                                                                                  False))))
        self.act_lock_now = menu.addAction(tr("Blocca ora"), self.lock)
        appearance = theme.prepare_menu(menu.addMenu(tr("Aspetto")))
        group = QActionGroup(self)
        self.theme_actions = {}
        for key, label in (("auto", tr("Automatico (come il sistema)")), ("light", tr("Chiaro")), ("dark", tr("Scuro"))):
            act = appearance.addAction(label, lambda k=key: self._set_theme(k))
            act.setCheckable(True)
            group.addAction(act)
            self.theme_actions[key] = act
        self.theme_actions.get(theme.mode(), self.theme_actions["auto"]).setChecked(True)
        languages = theme.prepare_menu(menu.addMenu(tr("Lingua") + " · Language"))
        lgroup = QActionGroup(self)
        for code, label in LANGUAGES.items():
            act = languages.addAction(label, lambda c=code: self._set_language(c))
            act.setCheckable(True)
            act.setChecked(code == current_language())
            lgroup.addAction(act)
        menu.addSeparator()
        self.act_pin = menu.addAction(tr("Tieni sopra le altre finestre"))
        self.act_pin.setCheckable(True)
        self.act_pin.toggled.connect(self._toggle_on_top)
        self.act_titlebar = menu.addAction(tr("Usa la barra del titolo del sistema"))
        self.act_titlebar.setCheckable(True)
        self.act_titlebar.setChecked(bool(self.settings.get("system_titlebar", False)))
        self.act_titlebar.toggled.connect(self._toggle_titlebar)
        self.act_close_tray = menu.addAction(tr("Chiudendo, resta nell'area di notifica"))
        self.act_close_tray.setCheckable(True)
        self.act_close_tray.setChecked(bool(self.settings.get("close_to_tray", True)))
        self.act_close_tray.toggled.connect(lambda on: self.settings.set("close_to_tray", on))
        self.act_to_tray = menu.addAction(tr("Riduci nell'area di notifica"), lambda: self.to_tray())
        quick = theme.prepare_menu(menu.addMenu(tr("Finestra rapida")))
        quick.addAction(tr("Apri la finestra rapida"), self.open_quick)
        self.act_quick_info = quick.addAction(tr("Scorciatoia globale…"), self.quick_shortcut_info)
        menu.addSeparator()
        self.act_rounded = menu.addAction(tr("Angoli arrotondati"))
        self.act_rounded.setCheckable(True)
        self.act_rounded.setChecked(bool(self.settings.get("rounded_corners", True)))
        self.act_rounded.setEnabled(self.frameless)
        self.act_rounded.toggled.connect(self._toggle_rounded)
        menu.addSeparator()
        menu.addAction(tr("Informazioni su Helpix"), self.show_about)
        self.gear_menu = menu
        return menu

    def _add_agent_actions(self, m):
        m.addSeparator()
        head = m.addAction(tr("Agenti nel terminale"))
        head.setEnabled(False)  # intestazione della sezione
        for key, a in agents.AGENTS.items():
            label = a["label"] + ("" if agents.find_cli(key) else "  · " + tr("da installare"))
            if self.settings.get("default_engine") == "agent" and self.settings.get("default_agent") == key:
                label += "   ★"
            act = m.addAction(site_icons.icon(a["icon"], 18), label, lambda k=key: self._choose_agent(k))
            if self.engine == "agent" and self.agent and key == self.agent.key:
                f = act.font()
                f.setBold(True)
                act.setFont(f)

    def _add_task_actions(self, m):
        m.addAction(icon("transfer", C["text"], 16), tr("Continua il task con un'altra IA…"),
                    lambda: self.open_handoff(None))
        m.addAction(icon("plus", C["text"], 16), tr("Nuovo task"), self.new_session)
        m.addAction(icon("list", C["text"], 16), tr("Task salvati…"), self.open_sessions)
        m.addAction(icon("upload", C["text"], 16), tr("Esporta il task su file…"), self.export_current)
        m.addAction(icon("download", C["text"], 16), tr("Importa un task da file…"), self.import_file)

    def _build_picker_menu(self):
        m = self.picker_menu
        m.clear()
        if self.engine == "agent":
            for sid, s in WEB_SITES.items():
                m.addAction(site_icons.icon(sid, 18), s["label"], lambda k=sid: self._choose_site(k))
            self._add_agent_actions(m)
            m.addSeparator()
            star = m.addAction(icon("star", C["text"], 16),
                               tr("Imposta {name} come predefinito").format(name=self.agent.label),
                               self.set_default_agent)
            star.setEnabled(not self._is_default_agent())
            m.addSeparator()
            self._add_task_actions(m)
            m.addSeparator()
            m.addAction(icon("refresh", C["text"], 16), tr("Riavvia l'agente"), lambda: self.agent.start())
            m.addAction(icon("folder", C["text"], 16), tr("Apri la cartella di lavoro"),
                        self.agent.btn_folder.click)
            m.addSeparator()
            m.addAction(icon("key", C["text"], 16), tr("Usa una chiave API (avanzato)"), lambda: self._apply_engine("api"))
            return
        if self.engine == "web":
            default = self.settings.get("default_site") if self.settings.get("default_engine") == "web" else None
            for sid, s in WEB_SITES.items():
                label = s["label"] + ("   ★" if sid == default else "")
                act = m.addAction(site_icons.icon(sid, 18), label, lambda k=sid: self._choose_site(k))
                if sid == self.web.site:
                    f = act.font()
                    f.setBold(True)
                    act.setFont(f)
            if WEBENGINE:
                self._add_agent_actions(m)
            m.addSeparator()
            star = m.addAction(icon("star", C["text"], 16),
                               tr("Imposta {name} come predefinito").format(name=WEB_SITES[self.web.site]["label"]),
                               self.set_default_agent)
            star.setEnabled(not self._is_default_agent())
            ext = m.addAction(icon("external", C["text"], 16),
                              tr("Apri {name} nel mio browser").format(name=WEB_SITES[self.web.site]["label"]),
                              lambda: self._set_site_external(self.web.site, not self.web.is_external()))
            ext.setCheckable(True)
            ext.setChecked(self.web.is_external())
            m.addSeparator()
            self._add_task_actions(m)
            m.addSeparator()
            m.addAction(icon("arrow-left", C["text"], 16), tr("Indietro"), self.web.back)
            m.addAction(icon("refresh", C["text"], 16), tr("Ricarica la pagina"), self.web.reload)
            m.addAction(icon("home", C["text"], 16), tr("Pagina iniziale"), self.web.go_home)
            m.addAction(icon("external", C["text"], 16), tr("Apri nel browser"), self.web.open_external)
            m.addSeparator()
            m.addAction(icon("key", C["text"], 16), tr("Usa una chiave API (avanzato)"), lambda: self._apply_engine("api"))
        else:
            for pid, p in PROVIDERS.items():
                act = m.addAction(site_icons.icon(site_icons.provider_key(pid), 18), p["label"],
                                  lambda k=pid: self._choose_provider(k))
                if pid == self.session.provider:
                    f = act.font()
                    f.setBold(True)
                    act.setFont(f)
            m.addSeparator()
            m.addAction(icon("plus", C["text"], 16), tr("Nuovo task"), self.new_session)
            m.addAction(icon("list", C["text"], 16), tr("Task salvati…"), self.open_sessions)
            m.addAction(icon("upload", C["text"], 16), tr("Esporta il task su file…"), self.export_current)
            m.addAction(icon("download", C["text"], 16), tr("Importa un task da file…"), self.import_file)
            if WEBENGINE:
                m.addSeparator()
                m.addAction(icon("transfer", C["text"], 16), tr("Continua il task con il mio account (web)…"),
                            lambda: self.open_handoff(None))
                m.addAction(icon("home", C["text"], 16), tr("Torna al mio account (web)"), lambda: self._apply_engine("web"))
                self._add_agent_actions(m)

    def _add_effort_menu(self, m, levels: list, current: str, choose):
        if not levels:
            return
        sub = theme.prepare_menu(m.addMenu(tr("Effort (quanto ragiona)")))
        group = QActionGroup(sub)
        for level in ["auto"] + list(levels):
            act = sub.addAction(tr("automatico (predefinito del modello)") if level == "auto" else level,
                                lambda lv=level: choose(lv))
            act.setCheckable(True)
            act.setChecked(level == current)
            group.addAction(act)

    def _build_model_menu(self):
        m = self.model_menu
        m.clear()
        if self.engine == "agent" and self.agent:
            a = agents.AGENTS[self.agent.key]
            model, effort = self._agent_choice()
            group = QActionGroup(m)
            for name in a.get("models", []):
                act = m.addAction(tr("predefinito dell'agente") if name == "default" else name,
                                  lambda n=name: self.set_choice(model=n))
                act.setCheckable(True)
                act.setChecked(name == model)
                group.addAction(act)
            m.addAction(tr("Altro modello…"), self._custom_agent_model)
            m.addSeparator()
            self._add_effort_menu(m, a.get("efforts", []), effort, lambda lv: self.set_choice(effort=lv))
            return
        pid = self.session.provider
        names = list(self.settings.cached_models(pid) or PROVIDERS[pid]["models"])
        if self.session.model not in names:
            names.insert(0, self.session.model)
        default = self.settings.get("default_model") if self.settings.get("default_provider") == pid else None
        group = QActionGroup(m)
        for name in names[:40]:
            act = m.addAction(name + ("   ★" if name == default else ""),
                              lambda n=name: self._apply_agent(self.session.provider, n))
            act.setCheckable(True)
            act.setChecked(name == self.session.model)
            group.addAction(act)
        m.addSeparator()
        self._add_effort_menu(m, PROVIDERS[pid].get("efforts", []), self._api_effort() or "auto",
                              lambda lv: self.set_choice(effort=lv))
        m.addAction(tr("Altro modello…"), self._custom_model)
        m.addAction(icon("refresh", C["text"], 16), tr("Aggiorna l'elenco"), self._refresh_models)
        m.addSeparator()
        star = m.addAction(icon("star", C["text"], 16),
                           tr("Imposta {name} come predefinito").format(name=self.session.model),
                           self.set_default_agent)
        star.setEnabled(not self._is_default_agent())

    def _welcome(self):
        self.chat.add_message(Message("note", (
            tr("Descrivi il problema qui sotto. Puoi allegare uno **screenshot** (pulsante in alto o Ctrl+V): "
            "i comandi proposti dall'IA si eseguono con un clic e il loro output torna automaticamente all'IA."))))

    def notify(self, text: str, ms: int = 4500):
        bottom = 24
        if self.terminal.isVisible():
            bottom += self.terminal.height()
        if self.command_bar.isVisible() and self.stack.currentIndex() == 0:
            bottom += self.command_bar.parentWidget().height()
        self.toast.show_message(text, ms, bottom)

    def _update_picker(self):
        if self.engine == "agent" and self.agent:
            self.picker.set_agent(self.agent.icon_key(), self.agent.label, tr("nel terminale"))
        elif self.engine == "web":
            self.picker.set_agent(self.web.site, WEB_SITES[self.web.site]["label"], tr("il tuo account"))
        else:
            p = PROVIDERS.get(self.session.provider, {})
            self.picker.set_agent(site_icons.provider_key(self.session.provider),
                                  p.get("label", self.session.provider).split(" (")[0], "API")
        self.model_btn.setVisible(self.engine == "api" or (self.engine == "agent" and self.agent is not None))
        if self.engine == "agent" and self.agent:
            model, effort = self._agent_choice()
            label = (tr("modello predefinito") if model == "default" else model) + (
                "" if effort == "auto" else f" · {effort}")
            self.model_btn.setText(label)
            self.model_btn.setToolTip(tr("Modello ed effort di {name}").format(name=self.agent.label))
            return
        star = " ★" if self._is_default_agent() else ""
        effort = self._api_effort()
        self.model_btn.setText(self.session.model + ("" if not effort else f" · {effort}") + star)
        self.model_btn.setToolTip(tr("Modello: {model}").format(model=self.session.model)
                                  + (" · " + tr("predefinito") if star else ""))

    def _is_default_agent(self) -> bool:
        s = self.settings
        if self.engine == "agent" and self.agent:
            return s.get("default_engine") == "agent" and s.get("default_agent") == self.agent.key
        if self.engine == "web":
            return s.get("default_engine") == "web" and s.get("default_site") == self.web.site
        return (s.get("default_engine") == "api" and s.get("default_provider") == self.session.provider
                and s.get("default_model") == self.session.model)

    def show_about(self):
        QMessageBox.about(self, tr("Informazioni su Helpix"), tr(
            "<b>Helpix {version}</b><br>Assistente AI open source per il troubleshooting su Linux e Windows.<br><br>"
            "© 2026 Crash<br>"
            "Helpix è software libero: puoi ridistribuirlo e/o modificarlo secondo i termini della "
            "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General Public License</a>, versione 3 o "
            "(a tua scelta) successiva. È distribuito <b>senza alcuna garanzia</b>.<br>"
            "Codice sorgente: <a href='{url}'>{url}</a><br><br>"
            "Componenti di terzi: Qt e PySide6 (LGPL-3.0), xterm.js (MIT), font Inter e JetBrains Mono "
            "(SIL Open Font License). Dettagli nel file THIRD-PARTY-NOTICES.md.<br>"
            "Helpix non è affiliato a OpenAI, Anthropic, Google, Microsoft o DeepSeek: i loro nomi e marchi "
            "appartengono ai rispettivi proprietari.").format(version=__version__, url=SOURCE_URL))

    def open_start_screen(self):
        """La schermata iniziale (assistente, lingua, tema, predefinito) aperta dall'app."""
        from .start_dialog import StartDialog
        dlg = StartDialog(self.settings, self.secrets, self)
        result = dlg.exec()
        if result == StartDialog.RESTART:  # lingua cambiata: Helpix si riavvia
            from ..app import restart
            self._quitting = True
            self.close()
            restart()
            return
        if result != QDialog.DialogCode.Accepted:
            return
        if dlg.engine == "web" and dlg.site:
            self._choose_site(dlg.site)
        elif dlg.engine == "api" and dlg.provider:
            self._apply_agent(dlg.provider, dlg.model)
            self._apply_engine("api")
            self._update_picker()
        if self.settings.get("skip_setup"):
            self.notify(tr("Scelta salvata come predefinita: Helpix si aprirà così. La schermata iniziale la ritrovi "
                           "in Impostazioni."), 7000)

    def set_default_agent(self):
        """Rende predefinito ciò che è attivo ora: si aprirà così all'avvio."""
        if self.engine == "agent" and self.agent:
            self.settings.data.update(default_engine="agent", default_agent=self.agent.key)
            name = self.agent.label
        elif self.engine == "web":
            self.settings.data.update(default_engine="web", default_site=self.web.site)
            name = WEB_SITES[self.web.site]["label"]
        else:
            self.settings.data.update(default_engine="api", default_provider=self.session.provider,
                                      default_model=self.session.model)
            name = f"{PROVIDERS[self.session.provider]['label']} · {self.session.model}"
        self.settings.save()
        self._update_picker()
        self.notify(tr("{name} è ora l'assistente predefinito: si aprirà così all'avvio.").format(name=name))

    # ------------------------------------------------------------ tema e finestra
    def _theme_changed(self):
        dark = theme.is_dark()
        self.btn_theme.set_icon_name("sun" if dark else "moon")
        self.btn_theme.setToolTip(tr("Passa al tema chiaro (Ctrl+Maiusc+L)") if dark else tr("Passa al tema scuro (Ctrl+Maiusc+L)"))
        for act, name in self._shot_actions:
            act.setIcon(icon(name, C["text"], 16))
        self._update_picker()

    def _toggle_theme(self):
        mode = theme.toggle()
        self.settings.set("theme", mode)
        self.theme_actions[mode].setChecked(True)
        self._web_theme_hint()

    def _set_language(self, code: str):
        if code == current_language():
            return
        self.settings.set("language", code)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Lingua"))
        box.setText(tr("La nuova lingua sarà usata dopo il riavvio di Helpix."))
        now = box.addButton(tr("Riavvia ora"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Più tardi"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is now:
            from ..app import restart
            self._quitting = True  # con l'icona nell'area di notifica la × riduce soltanto
            self.close()
            restart()

    def _set_theme(self, mode: str):
        theme.set_mode(mode)
        self.settings.set("theme", mode)
        self._web_theme_hint()

    def _web_theme_hint(self):
        if self.engine == "web" and WEBENGINE:
            self.notify(tr("La pagina della chat userà il nuovo tema dal prossimo avvio "
                        "(oppure cambialo nelle impostazioni del sito)."), 6000)

    def _toggle_titlebar(self, on: bool):
        self.settings.set("system_titlebar", on)
        self.notify(tr("La modifica sarà applicata al prossimo avvio di Helpix."))

    def _toggle_rounded(self, on: bool):
        self.settings.set("rounded_corners", on)
        self.notify(tr("La modifica sarà applicata al prossimo avvio di Helpix."))

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and hasattr(self, "_lock_timer"):
            self._activity(self.isActiveWindow())
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.engine == "web":
            QTimer.singleShot(150, self.web.check_clipboard)  # gli appunti arrivano un attimo dopo il focus
        if event.type() == QEvent.Type.WindowStateChange and self.frameless:
            maxed = self.isMaximized() or self.isFullScreen()
            self.central.setProperty("frameless", "false" if maxed else "true")
            if self.rounded:
                self.central.set_square(maxed)  # massimizzata: angoli dritti, niente margini
            else:
                self.central.layout().setContentsMargins(*(0 if maxed else 1,) * 4)
            self.central.style().unpolish(self.central)
            self.central.style().polish(self.central)
            self.win_controls.refresh()
        super().changeEvent(event)

    # ------------------------------------------------------------ motori e modalità
    def _apply_engine(self, engine: str, initial: bool = False):
        if engine == "web" and not WEBENGINE:
            engine = "api"
        if engine == "api" and not initial:
            p = PROVIDERS[self.session.provider]
            if p["needs_key"] and not self.secrets.get(self.session.provider):
                dlg = SetupDialog(self.settings, self.secrets, self, first_run=False,
                                  current=(self.session.provider, self.session.model))
                if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.provider:
                    return
                self._apply_agent(dlg.provider, dlg.model)
        if engine == "agent" and not WEBENGINE:
            engine = "api"
        self.engine = engine
        web = engine == "web"
        if engine == "agent":
            panel = self._agent_panel()
            self.stack.setCurrentWidget(panel)
            panel.ensure_started()
        else:
            self.stack.setCurrentIndex(0 if web else 1)
        # Ctrl+N e Ctrl+L servono ai programmi nel terminale dell'agente
        self._sc_new.setEnabled(engine != "agent")
        self._sc_term.setEnabled(engine != "agent")
        self.shot.set_tooltip(tr("Seleziona un'area o una finestra e incollala nella chat (Ctrl+Maiusc+S)") if web
                              else tr("Seleziona un'area o una finestra e allegala al messaggio (Ctrl+Maiusc+S)"))
        if not initial:
            self.settings.set("engine", engine)
        if engine == "api":
            self.prompt.setFocus()
        self._update_picker()

    # ------------------------------------------------------------ agenti nel terminale
    def _agent_panel(self):
        if self.agent is None:
            from .agent_panel import AgentPanel
            key = self.settings.get("default_agent") if self.settings.get("default_engine") == "agent" else None
            self.agent = AgentPanel(key or self.settings.get("agent", "claude-code"))
            self.agent.status_changed.connect(self._update_picker)
            self.agent.hint.connect(self.notify)
            self.agent.summary_ready.connect(self._summary_received)
            self.agent.summary_failed.connect(self._summary_failed)
            self.stack.addWidget(self.agent)
            self.agent.model, self.agent.effort = self._agent_choice()
        return self.agent

    def _choose_agent(self, key: str):
        panel = self._agent_panel()
        self.settings.set("agent", key)
        panel.model, panel.effort = self._agent_choice(key)
        if self.engine != "agent":
            panel.key = key
            self._apply_engine("agent")
        else:
            panel.set_agent(key)
        self._update_picker()

    def _set_tech_mode(self, on: bool):
        self.terminal.setVisible(on)
        self.tree.setVisible(on)
        if self.btn_tech.isChecked() != on:
            self.btn_tech.blockSignals(True)
            self.btn_tech.setChecked(on)
            self.btn_tech.blockSignals(False)
            self.btn_tech.refresh()
        self.settings.set("tech_mode", on)

    def _choose_site(self, site: str):
        """Passa subito all'altro servizio. Se c'è un task in corso altrove, compare la barra «Porta il task qui»."""
        if self.engine != "web":
            self._apply_engine("web")
        self.web.set_site(site)
        if not self._task_has_content():
            self.session.site = site
        self.settings.set("web_site", site)
        self._update_picker()
        self._update_transfer_bar()

    def _transfer_bar_primary(self):
        if self._bar_mode != "google":
            self.open_handoff(self.web.site)
        elif self._bar_site == "gemini":
            self._set_site_external(self._bar_site, True)      # Gemini richiede Google: apri nel browser
        else:
            self._use_email_login(self._bar_site)             # gli altri: resta qui, accedi con email

    def _transfer_bar_secondary(self):
        if self._bar_mode != "google":
            self._choose_site(self._task_site())
        elif self._bar_site == "gemini":
            self._google_dismissed.add(self._bar_site)
            self.transfer_bar.hide()
        else:
            self._google_dismissed.add(self._bar_site)
            self.transfer_bar.hide()
            self._bar_mode = "transfer"

    def _use_email_login(self, site: str):
        """Riporta l'utente all'accesso con email del servizio, dentro Helpix (niente browser)."""
        self.transfer_bar.hide()
        self._bar_mode = "transfer"
        self.web.go_home()  # torna alla pagina di accesso, dove c'è l'opzione email
        self.notify(self._email_login_help(site), 15000)

    # ------------------------------------------------------------ accesso Google e browser di sistema
    def _google_signin(self, site: str):
        if site in self._google_dismissed or self.web.is_external(site):
            return
        self._bar_mode, self._bar_site = "google", site
        if site == "gemini":
            sub = tr("Gemini richiede un account Google e Google non permette l'accesso dai browser integrati. Aprilo "
                     "nel tuo browser: Helpix lavora affiancato tramite gli appunti.")
            self.transfer_bar.show_notice(site, tr("Gemini richiede l'account Google"), sub,
                                          tr("Apri nel browser"), tr("Chiudi"))
        else:
            self.transfer_bar.show_notice(site, tr("Accedi con email, non con Google"), self._email_login_help(site),
                                          tr("Accedi con email"), tr("Chiudi"))

    @staticmethod
    def _email_login_help(site: str) -> str:
        """Come accedere senza Google, anche con un account creato con «Accedi con Google»."""
        name = WEB_SITES[site]["label"]
        if site == "chatgpt":
            return tr("Google blocca il suo accesso dentro le app. Se il tuo account ChatGPT è nato con Google, "
                      "aggiungi una password una volta: «Continua con email», scrivi la tua Gmail e scegli «Password "
                      "dimenticata?». Poi accedi con email e password: lo stesso account, con le tue chat.")
        if site == "claude":
            return tr("Google blocca il suo accesso dentro le app. Scegli «Continua con email» e scrivi la tua Gmail: "
                      "Claude ti manda un codice e ritrovi lo stesso account, con le tue chat.")
        return tr("Google blocca il suo accesso dentro le app. Accedi a {name} con email (o con il tuo account "
                  "Microsoft): l'accesso resta salvato.").format(name=name)

    def _set_site_external(self, site: str, on: bool):
        self.web.set_external(site, on)
        self.settings.set("external_sites", sorted(self.web.external))
        if self._bar_mode == "google":
            self.transfer_bar.hide()
            self._bar_mode = "transfer"
        self._update_transfer_bar()
        name = WEB_SITES[site]["label"]
        self.notify(tr("{name} si apre nel tuo browser: Helpix lavora affiancato.").format(name=name) if on
                    else tr("{name} usa di nuovo il browser integrato.").format(name=name))

    def _task_site(self) -> str:
        return self.session.site if self.session.site in WEB_SITES else self.web.site

    def _update_transfer_bar(self):
        if self._bar_mode == "google":
            if self.web.site == self._bar_site and self.transfer_bar.isVisible():
                return
            self._bar_mode = "transfer"
        src = self._task_site()
        if self.engine == "web" and self._task_has_content() and src != self.web.site:
            self.transfer_bar.show_for(src, WEB_SITES[src]["label"], self.web.site, WEB_SITES[self.web.site]["label"])
        else:
            self.transfer_bar.hide()

    # ------------------------------------------------------------ passaggio del task
    def _task_has_content(self) -> bool:
        return any(m.kind in ("shot", "output", "diagnostics", "summary", "chat") and m.role != "note"
                   for m in self.session.messages)

    def _source_label(self) -> str:
        if self.engine == "agent" and self.agent:
            return self.agent.label
        if self.session.site in agents.AGENTS:
            return agents.AGENTS[self.session.site]["label"]
        if self.engine == "web" or self.session.site in WEB_SITES:
            return WEB_SITES[self._task_site()]["label"]
        return PROVIDERS[self.session.provider]["label"]

    def open_handoff(self, target: str | None, resume: bool = False):
        if not WEBENGINE:
            QMessageBox.information(self, "Helpix", tr("Il componente browser (PySide6-WebEngine) non è installato: "
                                                       "puoi usare solo una chiave API."))
            return
        if self.handoff:
            self.handoff.close()
        if target is None:
            sites = list(WEB_SITES)
            src = self._task_site()
            target = src if resume else (self.web.site if self.web.site != src
                                         else sites[(sites.index(src) + 1) % len(sites)])
        # la conversazione fatta direttamente nella chat Helpix non la vede: il riepilogo si può
        # chiedere sempre, anche se Helpix non ha registrato screenshot o comandi
        can_ask = not resume
        dlg = HandoffDialog(self.session, self._source_label(), target, can_ask, self, resume=resume)
        dlg.go.connect(self._handoff_go)
        dlg.ask_summary.connect(self._ask_summary)
        dlg.export.connect(self.export_current)
        dlg.finished.connect(lambda _r: setattr(self, "handoff", None))
        self.handoff = dlg
        dlg.show()

    def _ask_summary(self):
        if self.engine == "agent" and self.agent:
            if not self.agent.summary_pending:
                self.agent.request_summary()
                self.notify(tr("Chiedo il riepilogo a {name}: lo scrive su file e Helpix lo legge da solo…").format(
                    name=self.agent.label), 8000)
            return
        if self.engine == "web" or self.session.site in WEB_SITES:
            src = self._task_site()
            if self.engine != "web":
                self._apply_engine("web")
            self._summary_return = self.web.site if self.web.site != src else None
            self.web.set_site(src)
            self._update_picker()
            if self.web.is_external(src):
                self.web.paste_text(summary_request())
                if self.handoff:
                    self.handoff.summary_waiting_external(WEB_SITES[src]["label"])
                return
            # Helpix incolla la richiesta, la invia e legge il riepilogo dalla risposta
            if self.web.summary_pending:  # già chiesto: non lo rimando, aspetto la risposta
                return
            self.web.request_summary(summary_request())
            self.notify(tr("Chiedo il riepilogo a {name}: lo invio e leggo la risposta appena ha finito di "
                           "scrivere…").format(name=WEB_SITES[src]["label"]), 8000)
            return
        # motore API: il riepilogo lo chiede direttamente Helpix
        pid, model = self.session.provider, self.session.model
        p = PROVIDERS[pid]
        key = self.secrets.get(pid) if p["needs_key"] else ""
        wire = self.session.to_wire(p["vision"], max_images=0) + [{"role": "user", "text": summary_request(), "images": []}]
        w = FuncWorker(provider_chat, pid, model, key, self._system_prompt(), wire,
                       base_url=self.settings.base_url_for(pid), effort=self._api_effort(), parent=self)
        w.done.connect(lambda text: self._summary_received(parse_summary(text) or text.strip()))
        w.failed.connect(lambda exc: self.handoff.summary_failed(tr("Errore dall'IA: {exc}").format(exc=exc))
                         if self.handoff else None)
        self._start(w)

    def _summary_failed(self, message: str):
        if self.handoff:
            self.handoff.summary_failed(message)
        else:
            self.notify(message, 10000)
        if getattr(self, "_export_after_summary", False):
            self._export_after_summary = False
            self.notify(message + " " + tr("Poi premi di nuovo Esporta."), 12000)

    def _summary_received(self, summary: str):
        if not summary:
            return
        self.web.cancel_summary()  # arrivato (anche copiato a mano): basta controllare la pagina
        if self.agent:
            self.agent.cancel_summary()
        record_summary(self.session, summary, self._source_label())
        back = getattr(self, "_summary_return", None)
        if back and self.engine == "web":
            self._summary_return = None
            self.web.set_site(back)
            self._update_picker()
        if self.handoff:
            self.handoff.summary_received()
        else:
            self.notify(tr("Riepilogo del task salvato: lo userò se passi a un'altra IA."))
        if getattr(self, "_export_after_summary", False):
            self._export_after_summary = False
            QTimer.singleShot(0, self.export_current)

    def _handoff_go(self, target: str, text: str, images: list):
        text = self._private(text)
        if target in agents.AGENTS:
            self._handoff_to_agent(target, text, images)
            return
        source = self._source_label()
        new_label = WEB_SITES[target]["label"]
        note = Message("note", tr("Task spostato da {source} a {target}.").format(source=source, target=new_label))
        self.session.add(note)
        self.chat.add_message(note)
        if self.engine != "web":
            self._apply_engine("web")
        fresh = not self.web.is_open(target)
        self.session.site = target
        self.settings.set("web_site", target)
        self.web.set_site(target)
        if not fresh:
            self.web.go_home()  # sempre in una chat nuova, mai in coda a una conversazione già aperta
        self._update_picker()
        self.transfer_bar.hide()
        self.session.save()
        self.notify(tr("Apro {name} e incollo il task…").format(name=new_label), 8000)
        self.web.paste_package(text, images)

    def _handoff_to_agent(self, key: str, text: str, images: list):
        """Il task va in HELPIX-TASK.md nella cartella dell'agente, che lo legge all'avvio."""
        source = self._source_label()
        label = agents.AGENTS[key]["label"]
        shots = [agents.save_screenshot(p) for p in images if os.path.exists(p)]
        if shots:
            text += "\n\n" + tr("Screenshot (nella cartella di lavoro):") + "\n" + "\n".join(
                f"- screenshots/{p.name}" for p in shots)
        note = Message("note", tr("Task spostato da {source} a {target}.").format(source=source, target=label))
        self.session.add(note)
        self.chat.add_message(note)
        self.session.site = key
        self.session.save()
        panel = self._agent_panel()
        panel.key = key
        panel.model, panel.effort = self._agent_choice(key)
        self.settings.set("agent", key)
        if self.engine != "agent":
            self.engine = "agent"
            self.settings.set("engine", "agent")
            self.stack.setCurrentWidget(panel)
            self._sc_new.setEnabled(False)
            self._sc_term.setEnabled(False)
        self.transfer_bar.hide()
        if agents.find_cli(key):
            panel.start(task_text=text, prompt=tr("Leggi il file {file}: è il task da continuare. Riparti da lì.").format(
                file=agents.TASK_FILE))
            self.notify(tr("{name} parte con il task: lo legge da {file}.").format(name=label, file=agents.TASK_FILE),
                        9000)
        else:
            agents.write_context(key, text)
            panel.ensure_started()
            self.notify(tr("Il task è pronto per {name}: installalo e avvialo, lo troverà nella sua cartella.").format(
                name=label), 10000)
        self._update_picker()

    def _package_done(self, ok: bool):
        name = WEB_SITES[self.web.site]["label"]
        if ok and self.web.is_external():
            self.notify(tr("Testo del task copiato: incollalo nella chat di {name} nel browser (Ctrl+V), poi copia "
                           "gli screenshot dalla lista.").format(name=name), 12000)
        elif ok:
            self.notify(tr("Task incollato in {name}: controlla e premi Invio.").format(name=name), 9000)
        else:
            self.notify(tr("Non trovo la casella della chat di {name}: forse devi ancora fare l'accesso. "
                           "Il testo del task è negli appunti: accedi e premi Ctrl+V.").format(name=name), 12000)

    def export_current(self):
        if not self._task_has_content():
            # la conversazione è solo nella chat: prima la faccio riassumere all'IA, poi si salva
            if self.engine == "agent" and self.agent and self.agent.running:
                self._export_after_summary = True
                self.notify(tr("Il task è ancora solo nella conversazione: chiedo il riepilogo a {name}, poi ti "
                               "faccio salvare il file.").format(name=self.agent.label), 10000)
                self._ask_summary()
                return
            if self.engine == "web" and WEBENGINE and not self.web.is_external(self._task_site()):
                self._export_after_summary = True
                self.notify(tr("Il task è ancora solo nella chat: chiedo il riepilogo a {name}, poi ti faccio "
                               "salvare il file.").format(name=WEB_SITES[self._task_site()]["label"]), 10000)
                self._ask_summary()
                return
            self.notify(tr("Il task è ancora vuoto: non c'è niente da esportare."))
            return
        self.session.save()
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.session.title)[:50].strip() or "task"
        path, _ = QFileDialog.getSaveFileName(self, tr("Esporta il task"), str(Path.home() / f"{name}{EXTENSION}"),
                                              tr("Task di Helpix (*{ext})").format(ext=EXTENSION))
        if not path:
            return
        password = None
        if self.settings.get("encrypt_exports", False):
            from .security_dialog import ExportPasswordDialog
            dlg = ExportPasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()
        try:
            from .. import privacy
            self._sync_privacy()
            redact = (lambda t: privacy.filter_paste(t, notify=False)) if self.privacy_on else None
            out = export_task(self.session, path, password, redact=redact)
        except OSError as exc:
            QMessageBox.warning(self, tr("Esporta il task"), str(exc))
            return
        msg = (tr("Task cifrato salvato in {path}") if password else tr("Task salvato in {path}")).format(path=str(out))
        if redact is not None:
            msg += " " + tr("(scudo privacy acceso: dati sensibili oscurati; gli screenshot restano come sono)")
        self.notify(msg, 7000)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Importa un task"), str(Path.home()),
                                              tr("Task di Helpix (*{ext})").format(ext=EXTENSION))
        if not path:
            return
        from ..security import PasswordRequired, WrongPassword, is_encrypted_file
        password = None
        if is_encrypted_file(path):
            for _attempt in range(3):
                password, ok = QInputDialog.getText(self, tr("Task protetto"), tr(
                    "Questo task è cifrato. Inserisci la password:"), QLineEdit.EchoMode.Password)
                if not ok:
                    return
                try:
                    session = import_task(path, password)
                    break
                except WrongPassword:
                    QMessageBox.warning(self, tr("Task protetto"), tr("Password sbagliata."))
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.warning(self, tr("Importa un task"),
                                        tr("Impossibile importare il task:\n{exc}").format(exc=exc))
                    return
            else:
                return
            self._load_session(session)
            return
        try:
            session = import_task(path)
        except PasswordRequired:
            return
        except Exception as exc:  # noqa: BLE001 - file non valido o danneggiato
            QMessageBox.warning(self, tr("Importa un task"), tr("Impossibile importare il task:\n{exc}").format(exc=exc))
            return
        self._load_session(session)

    # ------------------------------------------------------------ agenti API
    def _ask_key(self, pid: str) -> str:
        p = PROVIDERS[pid]
        key, ok = QInputDialog.getText(self, tr("Chiave API"),
                                       tr("Inserisci la chiave API per {label}.\nLa trovi su: {url}").format(label=p["label"], url=p["key_url"]),
                                       QLineEdit.EchoMode.Password)
        key = key.strip() if ok else ""
        if key:
            self.secrets.set(pid, key)
        return key

    def _choose_provider(self, pid: str):
        if pid == self.session.provider:
            return
        if PROVIDERS[pid]["needs_key"] and not self.secrets.get(pid) and not self._ask_key(pid):
            return
        self._apply_agent(pid, self.settings.model_for(pid))

    def _custom_model(self):
        name, ok = QInputDialog.getText(self, tr("Modello"), tr("Nome esatto del modello:"), text=self.session.model)
        if ok and name.strip():
            self._apply_agent(self.session.provider, name.strip())

    def _apply_agent(self, pid: str, model: str):
        old = (self.session.provider, self.session.model)
        self.session.provider, self.session.model = pid, model
        self.settings.set_model(pid, model)
        if old != (pid, model) and self.session.messages:
            p = PROVIDERS[pid]
            text = tr("Agente cambiato in **{label} · {model}**. Conversazione e contesto sono mantenuti.").format(
                label=p["label"], model=model)
            if not p["vision"] and any(m.images for m in self.session.messages):
                text += tr(" Questo agente non legge le immagini: gli screenshot non verranno inviati.")
            note = Message("note", text)
            self.session.add(note)
            self.chat.add_message(note)
        self.session.save()
        self._update_picker()

    def _refresh_models(self):
        pid = self.session.provider
        key = self.secrets.get(pid)
        if PROVIDERS[pid]["needs_key"] and not key and not (key := self._ask_key(pid)):
            return
        self.notify(tr("Aggiorno l'elenco dei modelli…"), 2500)
        w = FuncWorker(list_models, pid, key, self.settings.base_url_for(pid), parent=self)
        w.done.connect(lambda models, pid=pid: self._models_loaded(pid, models))
        w.failed.connect(lambda exc: QMessageBox.warning(self, tr("Modello"), tr("Impossibile ottenere l'elenco dei modelli:\n{exc}").format(exc=exc)))
        self._start(w)

    def _models_loaded(self, pid: str, models: list):
        if models:
            self.settings.cache_models(pid, models)
        self.notify(tr("{n} modelli disponibili: aprili dal menu dell'assistente").format(n=len(models)), 4000)

    # ------------------------------------------------------------ chat API
    def _start(self, worker: FuncWorker):
        self._workers.add(worker)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        worker.start()

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("…" if busy else tr("Invia"))

    def send_message(self):
        if self.busy:
            return
        text = self.prompt.toPlainText().strip()
        images = self.attachments.paths()
        if not text and not images:
            return
        text = self._private(text)  # motore API: tutto passa da Helpix, anche quello che scrivi a mano
        msg = Message("user", text or tr("Ecco uno screenshot del problema."), images=images)
        self.session.add(msg)
        self.chat.add_message(msg)
        self.prompt.clear()
        self.attachments.clear()
        self.request_ai()

    def request_ai(self):
        if self.busy:
            return
        pid, model = self.session.provider, self.session.model
        p = PROVIDERS[pid]
        key = self.secrets.get(pid) if p["needs_key"] else ""
        if p["needs_key"] and not key and not (key := self._ask_key(pid)):
            return
        wire = self.session.to_wire(p["vision"])
        if not wire:
            return
        self._set_busy(True)
        self.chat.show_thinking(tr("{label} sta analizzando").format(label=p["label"]))
        w = FuncWorker(provider_chat, pid, model, key, self._system_prompt(), wire,
                       base_url=self.settings.base_url_for(pid), effort=self._api_effort(), parent=self)
        w.done.connect(lambda text, pid=pid, model=model: self._ai_done(text, pid, model))
        w.failed.connect(self._ai_failed)
        self._start(w)

    def _ai_done(self, text: str, pid: str, model: str):
        w = getattr(self, "_quick_watch", None)
        if w and w.get("kind") == "api":
            self._quick_watch = None
            self.instance.reply(w["sock"], {"type": "answer", "text": text, "done": True})
        self.chat.hide_thinking()
        self._set_busy(False)
        msg = Message("assistant", text or tr("_(risposta vuota)_"), meta={"provider": pid, "model": model})
        self.session.add(msg)
        self.chat.add_message(msg)

    def _ai_failed(self, exc):
        w = getattr(self, "_quick_watch", None)
        if w and w.get("kind") == "api":
            self._quick_watch = None
            self.instance.reply(w["sock"], {"type": "answer", "text": tr("Errore dall'IA: {exc}").format(exc=exc),
                                            "done": True})
        self.chat.hide_thinking()
        self._set_busy(False)
        self.chat.add_message(Message("note", tr("Errore dall'IA: {exc}").format(exc=exc), kind="error"))

    # ------------------------------------------------------------ comandi
    def _command_copied(self, cmd: str):
        if self.runner and self.runner.isRunning():
            return
        self.command_bar.show_command(cmd)

    def _confirm(self, cmd: str, info) -> bool:
        warnings = []
        if info.dangers:
            warnings.append(tr("Questo comando può modificare o danneggiare il sistema:\n• ") + "\n• ".join(info.dangers))
        if info.interactive:
            warnings.append(tr("Attenzione: {msg}.").format(msg=info.interactive))
        if not warnings:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Conferma comando"))
        box.setText("\n\n".join(warnings))
        box.setInformativeText(tr("Comando:\n{cmd}\n\nVuoi eseguirlo comunque?").format(cmd=cmd))
        run = box.addButton(tr("Esegui"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is run

    def run_command(self, cmd: str, source: str = "user", card=None, confirmed: bool = False):
        """source: "ai" (card della chat API), "web" (copiato dalla chat web), "user" (terminale),
        "ext" (pulsante «Esegui con Helpix» nella chat del browser, già confermato lì)."""
        cmd = cmd.strip()
        if not cmd:
            return
        if self.runner and self.runner.isRunning():
            QMessageBox.information(self, "Helpix", tr("C'è già un comando in esecuzione. Attendi o premi «Ferma»."))
            return
        if cmd in ("clear", "reset", "cls"):
            self.terminal.clear()
            return
        info = analyze(cmd)
        if info.needs_root and info.sudo_options:
            QMessageBox.warning(self, "Helpix", tr("Le opzioni di sudo (es. sudo -u, sudo -i) non sono supportate.\n"
                                "Usa «sudo comando» senza opzioni oppure un terminale esterno."))
            return
        if info.needs_root and not pkexec_available():
            QMessageBox.warning(self, "Helpix", tr("pkexec (polkit) non è installato: impossibile ottenere i "
                                "privilegi di amministratore da qui."))
            return
        if not confirmed and not self._confirm(cmd, info):
            return
        self.terminal.append(f"{self.terminal.prompt_text()} ", "prompt")
        self.terminal.append(f"{cmd}\n", "cmd")
        if info.needs_root:
            self.terminal.append(tr("Windows chiede il permesso di amministratore (Controllo account utente)…\n")
                                 if IS_WINDOWS else tr("Autorizzazione di amministratore richiesta (polkit)…\n"), "muted")
        runner = CommandRunner(cmd, self.session.cwd, info.needs_root,
                               int(self.settings.get("command_timeout", 120)), self.prev_cwd, parent=self)
        runner.chunk.connect(self.terminal.append)
        runner.completed.connect(lambda res, s=source, c=card: self._command_done(res, s, c))
        self.runner = runner
        self.terminal.set_running(True)
        if card:
            card.set_running()
        if source == "web":
            self.command_bar.set_running()
        runner.start()

    def stop_command(self):
        if self.runner and self.runner.isRunning():
            self.runner.cancel()

    def _command_done(self, res, source: str, card):
        self.terminal.set_running(False)
        notes = []
        if res.timed_out:
            notes.append(tr("interrotto: superato il limite di {s} s").format(s=self.settings.get("command_timeout", 120)))
        if res.cancelled:
            notes.append(tr("interrotto dall'utente"))
        if res.root and res.rc == 126:
            notes.append(tr("autorizzazione annullata"))
        elif res.root and res.rc == 127 and "authentication agent" in res.output.lower():
            notes.append(tr("nessun agente polkit: manca il programma che mostra la finestra della password "
                            "(su Hyprland, Sway o niri avvia ad esempio hyprpolkitagent, polkit-gnome o "
                            "lxqt-policykit)"))
        elif res.root and res.rc == 127:
            notes.append(tr("autorizzazione negata"))
        if res.truncated:
            notes.append(tr("output molto lungo, conservata solo la prima parte"))
        if notes:
            self.terminal.append(f"[{'; '.join(notes)}]\n", "warn")
        if res.rc != 0:
            self.terminal.append(tr("[codice di uscita {rc}]\n").format(rc=res.rc), "err")
        if res.cwd != self.session.cwd:
            self._set_cwd(res.cwd)
        if card:
            card.set_result(res.rc)
        res = self._private_result(res)

        if source == "ext":
            req, self._ext_request = self._ext_request, None
            self._record_output(res, notes, source, site=(req or {}).get("site"))
            if req:
                self.bridge.run_status(req, "done", rc=res.rc, output=format_output_for_chat(res),
                                       auto=bool(self.settings.get("auto_paste_output", True)))
            return

        if self.engine == "web":
            if source == "web" or self.terminal.share_cb.isChecked():
                auto = source == "web" and bool(self.settings.get("auto_paste_output", True))
                external = self.web.is_external()
                if auto:
                    self.web.paste_text(format_output_for_chat(res), None)  # lo dice già il pannello
                self.command_bar.set_result(res, auto and not external, external=external and auto)
                self._record_output(res, notes, source)
            return

        if not (source == "ai" or self.terminal.share_cb.isChecked()):
            return
        self._record_output(res, notes, source)
        if source == "ai" and self.settings.get("auto_continue", True) and not self.busy:
            self.request_ai()

    def _record_output(self, res, notes, source: str, site: str | None = None):
        """Aggiunge l'esito del comando al task (serve anche per passarlo a un'altra IA)."""
        out = res.output.strip() or tr("(nessun output)")
        if len(out) > MAX_SHARE:
            out = tr("[…output troncato, mostrata l'ultima parte…]\n") + out[-MAX_SHARE:]
        extra = f" ({'; '.join(notes)})" if notes else ""
        text = tr("Ho eseguito nel terminale (cartella {cwd}):\n````bash\n{cmd}\n````\nCodice di uscita: {rc}{extra}"
                  "\nOutput:\n````\n{out}\n````").format(cwd=res.cwd, cmd=res.cmd, rc=res.rc, extra=extra, out=out)
        msg = Message("user", text, kind="output",
                      meta={"cmd": res.cmd, "rc": res.rc, "output": out, "cwd": res.cwd, "source": source})
        site = site if site in WEB_SITES else (self.web.site if self.engine == "web" else None)
        if site:
            msg.meta["site"] = site
            self.session.site = site
        self.session.add(msg)
        self.chat.add_message(msg)

    def _edit_command(self, cmd: str, card=None):
        new, ok = QInputDialog.getMultiLineText(self, tr("Modifica comando"),
                                                tr("Modifica il comando e premi OK per eseguirlo:"), cmd)
        if ok and new.strip():
            self.run_command(new, "ai", None)

    # ------------------------------------------------------------ giro guidato e suggerimenti
    def _startup_tips(self):
        """Primo avvio: giro completo. Poi, finché la spunta è attiva: un consiglio del giorno."""
        if getattr(self, "locked", False) or not self.isVisible():
            QTimer.singleShot(3000, self._startup_tips)
            return
        if not self.settings.get("show_tips", True) or self.tour is not None:
            return
        if not self.settings.get("tour_done", False):
            self.start_tour()
        else:
            self.show_tip()

    def start_tour(self):
        self._open_tour("tour")

    def show_tip(self):
        from .tour import steps_for
        tips = [s.key for s in steps_for(self) if s.tip]
        i = int(self.settings.get("tip_index", -1) or 0) + 1
        self.settings.set("tip_index", i % len(tips))
        self._open_tour("tip", tips[i % len(tips)])

    def _open_tour(self, mode: str, start_key: str | None = None):
        from .tour import Tour
        if self.tour is not None:
            self.tour.close_tour()
        if getattr(self, "locked", False):
            return
        self.tour = Tour(self, mode, start_key)
        self.tour.finished.connect(self._tour_closed)

    def _tour_closed(self):
        self.tour = None
        if hasattr(self, "act_tips"):
            self.act_tips.setChecked(bool(self.settings.get("show_tips", True)))
        if self.settings.get("quick_shortcut") is None:  # primo avvio: dopo il giro, la domanda su Ctrl+Alt+H
            QTimer.singleShot(600, self._ask_global_shortcut)

    def _gnome_tray_enabled(self, ok: bool):
        if ok:
            QMessageBox.information(self, tr("Area di notifica"), tr(
                "Estensione AppIndicator attivata. Su GNOME le estensioni nuove si caricano all'accesso: esci e "
                "rientra nella sessione, poi l'icona di Helpix comparirà nella barra in alto."))
        else:
            self.notify(tr("Non sono riuscito ad attivare l'estensione AppIndicator: attivala dall'app Estensioni."),
                        9000)

    # ------------------------------------------------------------ dipendenze di sistema
    def check_system_deps(self):
        from .. import sysdeps
        self.notify(tr("Controllo le dipendenze di sistema…"), 3000)
        w = FuncWorker(sysdeps.check, parent=self)
        w.done.connect(self._deps_ready)
        w.failed.connect(lambda exc: QMessageBox.warning(self, tr("Dipendenze di sistema"), str(exc)))
        self._start(w)

    def _deps_ready(self, report):
        from .. import sysdeps
        title = tr("Dipendenze di sistema")
        if not report.items:
            QMessageBox.information(self, title, tr("Tutto a posto: non manca nulla."))
            return
        lines = "\n".join("• {what}: {why}{opt}".format(
            what=m.what, why=tr(m.reason), opt="" if m.required else tr(" (consigliata)")) for m in report.items)
        if report.gnome_tray and not report.packages:  # estensione già installata: basta attivarla
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(lines + "\n\n" + tr("L'estensione AppIndicator è già installata ma spenta: la attivo?"))
            on = box.addButton(tr("Attiva"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is on:
                self._gnome_tray_enabled(sysdeps.enable_gnome_tray())
            return
        argv = sysdeps.install_argv(report.packages, report.manager)
        cmd = None if report.immutable or not argv else sysdeps.elevate(argv, gui=True)
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        if cmd:
            box.setText(tr("Mancano alcuni componenti del sistema:") + "\n\n" + lines + "\n\n" +
                        tr("Helpix può installarli con il gestore pacchetti ({pm}): la password di amministratore "
                           "la chiede il sistema.").format(pm=report.manager))
            install = box.addButton(tr("Installa"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        else:
            install = None
            hint = sysdeps.manual_hint(report)
            why = tr("Su questo sistema (immutabile) non posso installarli da qui.") if report.immutable else \
                tr("Non trovo un gestore pacchetti che so usare.")
            box.setText(tr("Mancano alcuni componenti del sistema:") + "\n\n" + lines + "\n\n" + why +
                        ("\n" + tr("Comando da eseguire:") + f"\n{hint}" if hint else ""))
            box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if install is None or box.clickedButton() is not install:
            return
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._deps_proc = proc
        self.notify(tr("Installo: {pkgs}…").format(pkgs=" ".join(report.packages)), 8000)

        def finished(code, _status=None):
            out = bytes(proc.readAll()).decode("utf-8", "replace")
            self._deps_proc = None
            proc.deleteLater()
            if code in (126, 127):  # finestra della password annullata o negata
                self.notify(tr("Installazione annullata."))
                return
            if report.gnome_tray and code == 0:
                self._gnome_tray_enabled(sysdeps.enable_gnome_tray())
            after = sysdeps.check(lookup=False)
            left = [m.what for m in after.items if m.what in {i.what for i in report.items} and not m.enable_only]
            if code == 0 and not left:
                self.notify(tr("Dipendenze installate. Riavvia Helpix se qualcosa non funzionava."), 8000)
            else:
                QMessageBox.warning(self, title, tr("Non è andato tutto a buon fine.") + "\n\n" + out[-1500:])
        proc.finished.connect(finished)
        proc.start(cmd[0], cmd[1:])

    # ------------------------------------------------------------ filtro privacy
    @property
    def privacy_on(self) -> bool:
        return bool(self.settings.get("privacy_filter", False))

    def _set_privacy(self, on: bool):
        self.settings.set("privacy_filter", bool(on))
        self._privacy_look()
        self._sync_privacy()
        if self.agent is not None:  # istruzioni dell'agente (con utente e nome del PC) riscritte subito
            try:
                agents.write_context(self.agent.key)
            except OSError:
                pass
        self.notify(tr("Filtro privacy attivo: password, token, email, IP pubblici, nome utente e nome del PC "
                       "vengono oscurati prima di finire nella chat.") if on else tr("Filtro privacy disattivato."))

    def _sync_privacy(self):
        """Accende o spegne il filtro anche per gli incolla (chat, casella API, terminale, anteprime)."""
        from .. import privacy
        if self.privacy_on:
            if getattr(self, "_redactor", None) is None:
                self._redactor = privacy.Redactor()
            privacy.activate(self._redactor, self._privacy_found)
        else:
            privacy.deactivate()

    def _privacy_found(self, found):
        from .. import privacy
        self.notify(tr("Filtro privacy: oscurati {what}.").format(what=privacy.describe(found)), 6000)

    def _privacy_look(self):
        on = self.btn_privacy.isChecked()
        self.btn_privacy.set_icon_name("shield-check" if on else "shield")
        self.btn_privacy.setToolTip(
            tr("Filtro privacy ATTIVO: oscura password, token, chiavi, email, telefoni, IP pubblici, reti Wi-Fi, "
               "nomi e domini di Active Directory, nome utente e nome del PC in tutto ciò che arriva all'IA "
               "tramite Helpix: output dei comandi, diagnosi, task, finestra rapida e quello che incolli tu. "
               "Non vale per gli screenshot e per ciò che scrivi a mano. Clic per disattivare.") if on else
            tr("Filtro privacy disattivato: clic per oscurare i dati sensibili prima che finiscano nella chat."))

    def _private(self, *texts: str):
        """Oscura i dati sensibili se il filtro è attivo; un solo avviso per tutti i testi."""
        if not self.privacy_on:
            return texts[0] if len(texts) == 1 else texts
        from collections import Counter
        self._sync_privacy()
        total, out = Counter(), []
        for t in texts:
            clean, found = self._redactor.redact(t)
            total += found
            out.append(clean)
        if total:
            self._privacy_found(total)
        return out[0] if len(out) == 1 else tuple(out)

    def _system_prompt(self) -> str:
        """Il messaggio di sistema del motore API contiene utente, nome del PC e cartella: con lo scudo, oscurati."""
        from .. import privacy
        self._sync_privacy()
        return privacy.filter_paste(build_system_prompt(self.session.cwd), notify=False)

    def _private_result(self, res):
        if not self.privacy_on:
            return res
        import dataclasses
        cmd, cwd, output = self._private(res.cmd, res.cwd, res.output)
        return dataclasses.replace(res, cmd=cmd, cwd=cwd, output=output)

    # ------------------------------------------------------------ diagnosi rapida
    def quick_diagnostics(self):
        self.btn_diag.setEnabled(False)
        self.notify(tr("Raccolgo le informazioni del sistema…"), 3000)
        w = FuncWorker(collect_diagnostics, parent=self)
        w.done.connect(self._diagnostics_ready)
        w.failed.connect(lambda exc: (setattr(self, "_ext_diag", None),
                                      QMessageBox.warning(self, tr("Diagnosi rapida"), str(exc))))
        w.finished.connect(lambda: self.btn_diag.setEnabled(True))
        self._start(w)

    def _diagnostics_ready(self, text: str):
        text = self._private(text)  # l'anteprima mostra già il testo oscurato
        req, self._ext_diag = self._ext_diag, None
        if req:
            self._restore()  # l'anteprima va controllata in Helpix
        dlg = DiagnosticsPreview(text, self)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted and dlg.text()
        final = self._private(dlg.text()) if accepted else ""  # anche quello che aggiungi nell'anteprima
        if req:
            if accepted:
                self.session.add(Message("user", final, kind="diagnostics", meta={"site": req["site"]}))
                self.bridge.paste_text(req["site"], final + tr("\n\nIl problema è: "), req["_client"], req["tab"])
            if not req.get("_visible"):
                self.showMinimized()  # torna al browser
            return
        if not accepted:
            return
        self.session.add(Message("user", final, kind="diagnostics"))
        if self.engine == "agent" and self.agent:
            if self.agent.send_diagnostics(final):
                self.notify(tr("Diagnosi passata a {name}: descrivi il problema e premi Invio.").format(
                    name=self.agent.label))
        elif self.engine == "web":
            self.web.paste_text(final + tr("\n\nIl problema è: "),
                                tr("Diagnosi incollata nella chat: descrivi il problema in fondo e invia."))
        else:
            current = self.prompt.toPlainText().strip()
            self.prompt.setPlainText((current + "\n\n" if current else "") + final)
            self.prompt.setFocus()

    # ------------------------------------------------------------ cartelle
    def _set_cwd(self, path: str) -> bool:
        path = os.path.normpath(os.path.expanduser(path))
        if not os.path.isdir(path):
            return False
        if path != self.session.cwd:
            self.prev_cwd = self.session.cwd
        self.session.cwd = path
        self.session.save()
        self.settings.data["last_cwd"] = path
        self.terminal.set_cwd(path)
        idx = self.fs_model.index(path)
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx)
        return True

    def change_dir(self, path: str):
        if self._set_cwd(path):
            self.terminal.append(f"cd {pretty_path(self.session.cwd)}\n", "muted")
        else:
            self.terminal.append(tr("Cartella non accessibile: {path}\n").format(path=path), "err")

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, tr("Scegli una cartella"), self.session.cwd)
        if path:
            self.change_dir(path)

    def _toggle_on_top(self, on: bool):
        self.settings.set("always_on_top", on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    # ------------------------------------------------------------ screenshot
    def _restore(self):
        if self._quick_shot is not None:  # dalla finestra rapida: Helpix resta dov'era
            QTimer.singleShot(0, self._quick_shot_cancelled)
            return
        if self._ext_shot is not None:
            # screenshot chiesto dal browser: Helpix non torna in primo piano
            QTimer.singleShot(0, self._ext_shot_cancelled)
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def _shot_ok(self, path: str):
        if self._quick_shot is not None:
            req, self._quick_shot = self._quick_shot, None
            self._ext_shot_restore(req)
            self._add_attachment(path)
            self.instance.reply(req["sock"], {"type": "shot_done", "ok": True})
            return
        if self._ext_shot is not None:
            self._ext_shot_done(path)
            return
        self._restore()
        self._add_attachment(path)

    def _add_attachment(self, path: str):
        try:
            path = normalize_image(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Immagine"), str(exc))
            return
        if self.engine == "agent" and self.agent:
            if self.agent.send_screenshot(path):
                self.notify(tr("Screenshot passato a {name}: scrivi cosa vuoi sapere e premi Invio.").format(
                    name=self.agent.label))
            self.session.site = self.agent.key
            self.session.add(Message("user", tr("Screenshot inviato a {site}").format(site=self.agent.label),
                                     images=[path], kind="shot", meta={"site": self.agent.key}))
        elif self.engine == "web":
            self.web.paste_image(path)
            label = WEB_SITES[self.web.site]["label"]
            self.session.site = self.web.site
            self.session.add(Message("user", tr("Screenshot inviato a {site}").format(site=label), images=[path],
                                     kind="shot", meta={"site": self.web.site}))
        else:
            self.attachments.add(path)
            self.prompt.setFocus()
            self.notify(tr("Screenshot allegato: descrivi il problema e premi Invio"))

    def attach_files(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, tr("Allega immagini"), str(Path.home()), tr("Immagini ({exts})").format(exts=exts))
        for f in files:
            self._add_attachment(f)

    # ------------------------------------------------------------ sessioni (API)
    def new_session(self):
        if self.busy:
            return
        w = getattr(self, "_quick_watch", None)
        if w and hasattr(self, "instance"):
            self._quick_watch = None
            self.instance.reply(w["sock"], {"type": "answer_unavailable", "text": tr("_Nuovo task avviato._")})
        self.session.save()
        self.session = Session(self.session.provider, self.session.model, self.session.cwd)
        self.chat.clear()
        self.attachments.clear()
        self._welcome()
        if self.engine == "agent" and self.agent:
            agents.clear_task()
            agents.reset_summary()
            if agents.find_cli(self.agent.key):
                self.agent.start()
            else:
                self.agent.ensure_started()
            self.notify(tr("Nuovo task: {name} riparte con una conversazione nuova.").format(name=self.agent.label))
        elif self.engine == "web":
            self.command_bar.hide()
            self.web.go_home()
            self.notify(tr("Nuovo task: si apre una chat nuova."))

    def open_sessions(self):
        if self.busy:
            return
        dlg = SessionsDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected:
            return
        try:
            session = Session.load(dlg.selected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Sessioni"), tr("Impossibile aprire la sessione:\n{exc}").format(exc=exc))
            return
        self._load_session(session)

    def _load_session(self, session: Session):
        """Apre un task salvato o importato: nel motore web propone di incollarlo in una chat nuova."""
        self.session.save()
        if session.provider not in PROVIDERS:
            session.provider = self.session.provider
        self.session = session
        self.chat.clear()
        for m in session.messages:
            self.chat.add_message(m)
        if not self._set_cwd(session.cwd):
            self._set_cwd(str(Path.home()))
        self._update_picker()
        if self.engine == "web" and session.messages:
            self.open_handoff(None, resume=True)

    def open_settings(self):
        dlg = SetupDialog(self.settings, self.secrets, self, first_run=False,
                          current=(self.session.provider, self.session.model))
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.provider:
            self._apply_agent(dlg.provider, dlg.model)

    # ------------------------------------------------------------ area di notifica (tray)
    def _setup_tray(self):
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        self.tray = None
        self._quitting = False
        if not QSystemTrayIcon.isSystemTrayAvailable() or not self.settings.get("tray", True):
            # niente area di notifica (es. GNOME senza l'estensione AppIndicator): la × chiude Helpix
            for act in (getattr(self, "act_close_tray", None), getattr(self, "act_to_tray", None)):
                if act is not None:
                    act.setVisible(False)
            if self.settings.get("tray", True) and not self.settings.get("gnome_tray_hint"):
                QTimer.singleShot(4000, self._gnome_tray_hint)
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Helpix")
        menu = theme.prepare_menu(QMenu(self))
        menu.addAction(tr("Apri Helpix"), self.show_from_tray)
        menu.addAction(tr("Finestra rapida") + "   Ctrl+Alt+H", self.open_quick)
        self.tray_lock = menu.addAction(tr("Blocca ora"), self.lock)
        self.tray_lock.setVisible(self.lock_enabled)
        menu.addSeparator()
        menu.addAction(tr("Esci da Helpix"), self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # clic: mostra o nasconde Helpix
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.hide()
            else:
                self.show_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.open_quick()

    def show_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _gnome_tray_hint(self):
        """GNOME senza area di notifica: una volta sola propone di installare/attivare AppIndicator."""
        from .. import sysdeps
        if self.settings.get("gnome_tray_hint") or sysdeps.gnome_tray_status() not in ("install", "enable"):
            return
        if getattr(self, "tour", None) is not None or getattr(self, "locked", False):
            QTimer.singleShot(10000, self._gnome_tray_hint)
            return
        self.settings.set("gnome_tray_hint", True)
        box = QMessageBox(self)
        box.setWindowTitle(tr("Area di notifica"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(tr("Su questo GNOME non c'è l'area di notifica, quindi Helpix non può restare attivo con la sua "
                       "icona quando chiudi la finestra."))
        box.setInformativeText(tr("Vuoi aggiungerla? Helpix installa e attiva l'estensione AppIndicator (la usano "
                                  "anche altre app, come Dropbox, Steam o Discord)."))
        yes = box.addButton(tr("Aggiungila"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("No, grazie"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.check_system_deps()

    def to_tray(self):
        """Nasconde Helpix nell'area di notifica (continua a funzionare, scorciatoia compresa)."""
        if not self.tray:
            self.showMinimized()
            return
        self.hide()
        if not self.settings.get("tray_hint_shown"):
            self.settings.set("tray_hint_shown", True)
            self.tray.showMessage("Helpix", tr("Helpix resta attivo nell'area di notifica: Ctrl+Alt+H apre la finestra "
                                               "rapida, clic sull'icona per riaprirlo."), app_icon(), 6000)

    def quit_app(self):
        self._quitting = True
        self.close()

    # ------------------------------------------------------------ blocco con la password di sistema
    def _setup_lock(self):
        from ..security import SystemUnlock
        self.locked = False
        self._overlay = None
        self._unlocker = SystemUnlock(self)
        self._unlocker.finished.connect(self._unlock_done)
        self._unlock_waiters: list = []
        self._lock_timer = QTimer(self)
        self._lock_timer.setSingleShot(True)
        self._lock_timer.timeout.connect(self.lock)
        self.btn_lock = IconButton("lock", tr("Blocca Helpix"))
        self.btn_lock.clicked.connect(self.lock)
        layout = self.toolbar.layout()
        layout.insertWidget(layout.indexOf(self.btn_gear), self.btn_lock)
        self._apply_lock_settings()
        if self.lock_enabled:
            self.lock()

    @property
    def lock_enabled(self) -> bool:
        from ..security import policy_installed, unlock_available
        # senza la regola polkit pkcheck rifiuta sempre: meglio non bloccare che chiudere fuori l'utente
        return bool(self.settings.get("lock_enabled", False)) and unlock_available() and policy_installed()

    def _apply_lock_settings(self):
        if getattr(self, "tray_lock", None):
            self.tray_lock.setVisible(self.lock_enabled)
        self.btn_lock.setVisible(self.lock_enabled)
        self.act_lock_now.setVisible(self.lock_enabled)
        self._lock_timer.stop()

    def open_security(self):
        from .security_dialog import SecurityDialog
        if SecurityDialog(self.settings, self).exec() == QDialog.DialogCode.Accepted:
            self._apply_lock_settings()
            self.notify(tr("Impostazioni di sicurezza salvate."))

    def lock(self):
        if not self.lock_enabled or self.locked:
            return
        from .security_dialog import LockOverlay
        if self._overlay is None:
            self._overlay = LockOverlay(self.central)
            self._overlay.unlock.connect(lambda: self.unlock())
            theme.manager().changed.connect(lambda _d: self._overlay.restyle())
        if getattr(self, "tour", None) is not None:
            self.tour.close_tour(mark_done=False)  # riprende al prossimo avvio
        self.locked = True
        self._lock_timer.stop()
        self._place_overlay()
        self._overlay.set_waiting(False)
        self._overlay.show()
        self._overlay.raise_()
        self.toast.raise_()
        for w in (self.picker, self.model_btn, self.shot, self.btn_diag, self.btn_tech, self.btn_gear, self.btn_lock):
            w.setEnabled(False)
        if self.handoff:
            self.handoff.close()

    def _place_overlay(self):
        if self._overlay is not None:
            self._overlay.setGeometry(self.hsplit.geometry())

    def unlock(self, done=None):
        """Chiede la conferma al sistema; done(ok) viene chiamata con l'esito."""
        if not self.locked:
            if done:
                done(True)
            return
        if done:
            self._unlock_waiters.append(done)
        if self._unlocker.busy:
            return
        if self._overlay:
            self._overlay.set_waiting(True)
        self._unlocker.start()

    def _unlock_done(self, ok: bool, error: str):
        if ok:
            self.locked = False
            self._overlay.hide()
            for w in (self.picker, self.model_btn, self.shot, self.btn_diag, self.btn_tech, self.btn_gear,
                      self.btn_lock):
                w.setEnabled(True)
        elif self._overlay:
            self._overlay.set_waiting(False, tr("Sblocco non riuscito o annullato. Riprova."))
        waiters, self._unlock_waiters = self._unlock_waiters, []
        for fn in waiters:
            fn(ok)

    def _activity(self, active: bool):
        """Blocco automatico: parte il conto alla rovescia quando Helpix non è in uso."""
        if not self.lock_enabled or self.locked:
            return
        minutes = int(self.settings.get("lock_minutes", 15))
        if active or minutes <= 0:
            self._lock_timer.stop()
        else:
            self._lock_timer.start(minutes * 60_000)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "_overlay", None) is not None and not self._overlay.isHidden():
            QTimer.singleShot(0, self._place_overlay)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_overlay", None) is not None and not self._overlay.isHidden():
            QTimer.singleShot(0, self._place_overlay)

    # ------------------------------------------------------------ finestra rapida e istanza unica
    def _start_instance(self):
        from ..instance import InstanceServer
        self.instance = InstanceServer(self)
        if self.instance.start():
            self.instance.message.connect(self._on_instance)
        self._shortcut_state = tr("non attiva")
        self._shortcut = None
        self._shortcut_from_user = False
        QShortcut(QKeySequence("Ctrl+Alt+H"), self, self.open_quick)
        QTimer.singleShot(800, lambda: stop_quick_window(only_if_stale=True))
        self.tour = None
        if self.settings.get("show_tips", True):
            QTimer.singleShot(900, self._startup_tips)
        choice = self.settings.get("quick_shortcut")  # None = non ancora chiesto
        if choice is None:
            QTimer.singleShot(2500, self._ask_global_shortcut)
        elif choice:
            QTimer.singleShot(1500, self._start_global_shortcut)

    def _ask_global_shortcut(self):
        """Prima volta: propone la scorciatoia globale della finestra rapida."""
        if getattr(self, "locked", False) or not self.isVisible() or getattr(self, "tour", None) is not None:
            QTimer.singleShot(5000, self._ask_global_shortcut)
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Finestra rapida"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(tr("Vuoi aprire la finestra rapida di Helpix con Ctrl+Alt+H da qualsiasi programma?"))
        box.setInformativeText(tr("Funziona da qualsiasi programma; la disattivi quando vuoi da Impostazioni.")
                               if IS_WINDOWS else
                               tr("Il desktop ti chiederà di confermare la scorciatoia (e potrai cambiarla)."))
        yes = box.addButton(tr("Attiva Ctrl+Alt+H"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Non ora"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        on = box.clickedButton() is yes
        self.settings.set("quick_shortcut", on)
        if on:
            self._shortcut_from_user = True
            self._start_global_shortcut()
        else:
            self.notify(tr("Puoi attivarla quando vuoi da Impostazioni › Finestra rapida."), 7000)

    def _start_global_shortcut(self):
        """Chiede al desktop (portal GlobalShortcuts) la scorciatoia per la finestra rapida."""
        if self._shortcut is not None:
            return
        if IS_WINDOWS:
            from ..global_shortcut import WindowsHotkey
            self._shortcut = WindowsHotkey("H", "Ctrl+Alt+H", self)
        else:
            from ..global_shortcut import GlobalShortcut
            self._shortcut = GlobalShortcut("CTRL+ALT+h", tr("Helpix: richiesta rapida"), self)
        self._shortcut.activated.connect(self.open_quick)
        self._shortcut.state.connect(self._shortcut_changed)
        self._shortcut_state = tr("in attesa del desktop…")
        self._shortcut.start()

    def _shortcut_changed(self, kind: str, text: str):
        import logging
        logging.getLogger("helpix.shortcut").info("%s %s", kind, text)
        if kind == "bound" and not text.strip():
            # registrata ma senza tasti (ad esempio Ctrl+Alt+H già usato da un'altra scorciatoia di sistema)
            self._shortcut_state = tr("registrata ma senza tasti: assegnali nelle scorciatoie del desktop")
            if self._shortcut_from_user:
                QTimer.singleShot(300, self.quick_shortcut_info)
        elif kind == "bound":
            self._shortcut_state = tr("attiva: {keys}").format(keys=text)
            if self._shortcut_from_user:
                self.notify(tr("Scorciatoia attiva: {keys} apre e chiude la finestra rapida da qualsiasi "
                               "programma.").format(keys=text), 8000)
        else:
            self._shortcut_state = tr("non disponibile ({why})").format(why=text)
            self._shortcut = None
            if self._shortcut_from_user and IS_WINDOWS:
                self.notify(tr("Ctrl+Alt+H non è disponibile ({why}). Dentro Helpix funziona comunque; la finestra "
                               "rapida si apre anche dal menu dell'icona vicino all'orologio.").format(why=text), 10000)
            elif self._shortcut_from_user:  # l'utente l'ha appena chiesta
                from .. import shortcut_setup as ss
                de = ss.desktop()
                if de in ss.AUTOMATIC and de != "kde":  # Cinnamon, MATE, Xfce, COSMIC, GNOME < 48: subito
                    QTimer.singleShot(300, lambda: self._install_desktop_shortcut(de))
                else:  # KDE (va confermata) e desktop configurati a file: spiego cosa fare
                    QTimer.singleShot(300, self.quick_shortcut_info)
        self._shortcut_from_user = False

    def open_quick(self):
        """Mostra o nasconde la finestra rapida (ce n'è una sola)."""
        from ..instance import send_once
        from .quick_window import quick_socket_path
        if send_once({"type": "toggle"}, quick_socket_path()):
            return
        from PySide6.QtCore import QProcess
        from ..system import helpix_argv
        argv = helpix_argv("--quick")
        QProcess.startDetached(argv[0], argv[1:])

    def quick_shortcut_info(self):
        if IS_WINDOWS:
            box = QMessageBox(self)
            box.setWindowTitle(tr("Finestra rapida"))
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(tr("La finestra rapida si apre in basso a destra per chiedere al volo: scrivi e premi Invio, "
                           "la risposta compare lì. La stessa scorciatoia la mostra e la nasconde.\n\n"
                           "Scorciatoia globale Ctrl+Alt+H: {state}.").format(state=self._shortcut_state))
            retry = box.addButton(tr("Attiva Ctrl+Alt+H"), QMessageBox.ButtonRole.AcceptRole) \
                if self._shortcut is None else None
            box.addButton(tr("Chiudi"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if retry is not None and box.clickedButton() is retry:
                self.settings.set("quick_shortcut", True)
                self._shortcut_from_user = True
                self._start_global_shortcut()
            return
        from .. import shortcut_setup as ss
        de = ss.desktop()
        name = ss.LABELS.get(de) or tr("questo desktop")
        box = QMessageBox(self)
        box.setWindowTitle(tr("Finestra rapida"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("La finestra rapida si apre in basso a destra per chiedere al volo: scrivi e premi Invio, la "
                       "risposta compare lì. La stessa scorciatoia la mostra e la nasconde.\n\n"
                       "Scorciatoia globale (Ctrl+Alt+H) chiesta al desktop: {state}.").format(
            state=self._shortcut_state))
        line = ss.manual_line(de)
        if de in ss.AUTOMATIC:
            box.setInformativeText(tr("Se da altri programmi non funziona, Helpix può impostarla nelle scorciatoie di "
                                      "{name}. Comando usato:\n{cmd}").format(name=name, cmd=ss.quick_command()))
        else:
            where = ss.manual_where(de)
            box.setInformativeText(
                (tr("Su {name} aggiungi questa riga in {where}:").format(name=name, where=where) if where else
                 tr("Aggiungi nelle scorciatoie del desktop una scorciatoia (Ctrl+Alt+H) che esegue:"))
                + "\n" + line)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        retry = None
        if self._shortcut is None:
            retry = box.addButton(tr("Chiedi di nuovo al desktop"), QMessageBox.ButtonRole.ActionRole)
        setup = box.addButton(tr("Imposta la scorciatoia nel desktop"), QMessageBox.ButtonRole.AcceptRole) \
            if de in ss.AUTOMATIC else None
        copy = box.addButton(tr("Copia la riga"), QMessageBox.ButtonRole.ActionRole) if setup is None else None
        box.addButton(tr("Chiudi"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if retry is not None and clicked is retry:
            self.settings.set("quick_shortcut", True)
            self._start_global_shortcut()
            return
        if copy is not None and clicked is copy:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(line)
            self.notify(tr("Riga copiata: incollala nella configurazione del desktop e ricaricala."), 7000)
            return
        if setup is None or clicked is not setup:
            return
        self._install_desktop_shortcut(de)

    def _install_desktop_shortcut(self, de: str):
        from .. import shortcut_setup as ss
        if de == "kde":
            ss.install_kde()
            ss.open_kde_shortcuts()
            QMessageBox.information(self, tr("Finestra rapida"), tr(
                "Ho aggiunto il lanciatore «Helpix — richiesta rapida» con la scorciatoia Ctrl+Alt+H e aperto le "
                "scorciatoie di KDE.\n\nSe premendo Ctrl+Alt+H da un altro programma non succede nulla: nella finestra "
                "delle scorciatoie premi «Aggiungi nuovo › Applicazione», scegli «Helpix — richiesta rapida» e "
                "assegnale Ctrl+Alt+H (se KDE segnala un conflitto, scegli un'altra combinazione)."))
            return
        name = ss.LABELS.get(de) or tr("questo desktop")
        if ss.install(de):
            self._shortcut_state = tr("impostata nelle scorciatoie di {name}").format(name=name)
            self.notify(tr("Scorciatoia Ctrl+Alt+H aggiunta alle scorciatoie di {name}: prova a premerla da un "
                           "altro programma.").format(name=name), 9000)
        else:
            self.notify(tr("Non è stato possibile impostare la scorciatoia: aggiungila a mano nelle impostazioni "
                           "della tastiera di {name} con il comando {cmd}").format(name=name, cmd=ss.quick_command()),
                        12000)

    @staticmethod
    def _quick_command() -> str:
        from ..shortcut_setup import quick_command
        return quick_command()

    def _on_instance(self, msg: dict, sock):
        kind = msg.get("type")
        if getattr(self, "locked", False) and kind in ("shot", "send", "unlock", "hello", "set_model", "set_effort"):
            if kind == "unlock":
                self.unlock(lambda ok: self.instance.reply(sock, {"type": "unlocked" if ok else "locked"}))
            else:
                self.instance.reply(sock, {"type": "locked", "target": self._quick_target()})
            return
        if hasattr(self, "_lock_timer") and not self.isActiveWindow():
            self._activity(False)  # usare la finestra rapida conta come usare Helpix
        if kind == "show":
            self.showNormal() if self.isMinimized() else self.show()
            self.raise_()
            self.activateWindow()
        elif kind == "hello":
            self.instance.reply(sock, {"type": "status", "target": self._quick_target(), **self._quick_choices()})
        elif kind in ("set_model", "set_effort"):
            note = self.set_choice(model=msg.get("model") if kind == "set_model" else None,
                                   effort=msg.get("effort") if kind == "set_effort" else None)
            self.instance.reply(sock, {"type": "status", "target": self._quick_target(), **self._quick_choices()})
            if note:
                self.instance.reply(sock, {"type": "note", "text": note})
        elif kind == "cancel":
            self._quick_watch = None
            self._quick_seq = getattr(self, "_quick_seq", 0) + 1
        elif kind == "shot":
            if self.shots.busy:
                self.instance.reply(sock, {"type": "shot_done", "ok": False})
                return
            self._quick_shot = {"sock": sock, "_visible": self.isVisible() and not self.isMinimized()}
            self.shots.start("smart")
        elif kind == "send":
            self._quick_send(str(msg.get("text", "")), sock)
            self.instance.reply(sock, {"type": "sent"})

    # ------------------------------------------------------------ modello ed effort
    def _api_effort(self) -> str | None:
        level = (self.settings.get("effort") or {}).get(self.session.provider, "auto")
        return None if level == "auto" else level

    def _agent_choice(self, key: str | None = None) -> tuple[str, str]:
        key = key or (self.agent.key if self.agent else "claude-code")
        return ((self.settings.get("agent_model") or {}).get(key, "default"),
                (self.settings.get("agent_effort") or {}).get(key, "auto"))

    def _custom_agent_model(self):
        name, ok = QInputDialog.getText(self, tr("Modello"), tr("Nome esatto del modello:"),
                                        text=self._agent_choice()[0])
        if ok and name.strip():
            self.set_choice(model=name.strip())

    def set_choice(self, model: str | None = None, effort: str | None = None) -> str:
        """Cambia modello o effort dell'assistente attivo. Restituisce un messaggio per l'utente."""
        note = ""
        if self.engine == "agent" and self.agent:
            key = self.agent.key
            for field, value in (("agent_model", model), ("agent_effort", effort)):
                if value is not None:
                    data = dict(self.settings.get(field) or {})
                    data[key] = value
                    self.settings.set(field, data)
            how = self.agent.apply_choice(model, effort)
            note = (tr("Cambiato subito in {name}.") if how == "live" else
                    tr("Vale dalla prossima conversazione: in Helpix premi «Riavvia».")).format(name=self.agent.label)
        elif self.engine == "api":
            if model is not None and model != self.session.model:
                self._apply_agent(self.session.provider, model)
            if effort is not None:
                data = dict(self.settings.get("effort") or {})
                data[self.session.provider] = effort
                self.settings.set("effort", data)
        self._update_picker()
        if note:
            self.notify(note)
        return note

    def _quick_choices(self) -> dict:
        """Modelli ed effort da mostrare nella finestra rapida per l'assistente attivo."""
        if self.engine == "agent" and self.agent:
            a = agents.AGENTS[self.agent.key]
            model, effort = self._agent_choice()
            models = list(a.get("models", []))
            if model not in models:
                models.insert(0, model)
            efforts = [("auto", tr("effort auto"))] + [(e, f"effort {e}") for e in a.get("efforts", [])]
            return {"models": models, "model": model, "efforts": efforts if a.get("efforts") else [],
                    "effort": effort, "note": "" if a.get("efforts") else tr("effort non disponibile")}
        if self.engine == "api":
            pid = self.session.provider
            models = list(self.settings.cached_models(pid) or PROVIDERS[pid]["models"])
            if self.session.model not in models:
                models.insert(0, self.session.model)
            levels = PROVIDERS[pid].get("efforts", [])
            efforts = [("auto", tr("effort auto"))] + [(e, f"effort {e}") for e in levels] if levels else []
            return {"models": models[:40], "model": self.session.model, "efforts": efforts,
                    "effort": self._api_effort() or "auto", "note": ""}
        site = WEB_SITES[self.web.site]["label"]
        return {"models": [], "efforts": [], "note": tr("Modello ed effort si scelgono nella pagina di {site}.").format(
            site=site)}

    def _quick_target(self) -> str:
        if self.engine == "agent" and self.agent:
            return self.agent.label
        if self.engine == "web":
            return WEB_SITES[self.web.site]["label"]
        return PROVIDERS[self.session.provider]["label"].split(" (")[0]

    def _quick_shot_cancelled(self):
        req, self._quick_shot = self._quick_shot, None
        if req is not None:
            self._ext_shot_restore(req)
            self.instance.reply(req["sock"], {"type": "shot_done", "ok": False})

    def _quick_send(self, text: str, sock=None):
        """Il messaggio della finestra rapida va all'assistente attivo e viene inviato; la risposta
        torna alla finestra rapida mentre arriva (Helpix resta dov'è)."""
        text = self._private(text)  # con lo scudo acceso vale anche per la finestra rapida
        self._quick_watch = None
        self._quick_seq = seq = getattr(self, "_quick_seq", 0) + 1  # una «cancel» successiva annulla questo invio
        if self.engine == "agent" and self.agent:
            if not text:
                return
            def sent_agent(before: str):
                if self._quick_seq != seq:
                    return
                self.agent.paste(text, enter=True)
                self._quick_watch = {"sock": sock, "kind": "agent", "before": before, "last": None, "stable": 0,
                                     "until": time.monotonic() + 600}
                QTimer.singleShot(2500, self._quick_poll)
            self.agent.term.screen_text(sent_agent)
        elif self.engine == "web":
            if self.web.is_external():
                self.web.paste_text(text)  # nel browser: copiato, l'utente incolla
                self.instance.reply(sock, {"type": "answer_unavailable", "text": tr(
                    "_Testo copiato: incollalo nella chat del browser._")})
                return
            def sent_web(before: dict):
                if self._quick_seq != seq:
                    return
                if text:
                    self.web.paste_text(text, None)
                QTimer.singleShot(900, self.web.send_current)
                self._quick_watch = {"sock": sock, "kind": "web", "count": before.get("count", 0), "last": None,
                                     "stable": 0, "until": time.monotonic() + 600, "t0": time.monotonic()}
                QTimer.singleShot(2500, self._quick_poll)
            self.web.last_answer(sent_web)
        else:
            self._quick_watch = {"sock": sock, "kind": "api"}
            self.prompt.setPlainText(text)
            self.send_message()

    def _quick_poll(self):
        """Segue la risposta e la manda alla finestra rapida finché non è completa."""
        w = getattr(self, "_quick_watch", None)
        if not w or w["kind"] == "api":
            return
        if time.monotonic() > w["until"]:
            self._quick_watch = None
            return

        def push(text: str, done: bool):
            if text != w.get("sent_text") or done:
                w["sent_text"] = text
                self.instance.reply(w["sock"], {"type": "answer", "text": text, "done": done})
            if done:
                self._quick_watch = None
            else:
                QTimer.singleShot(900, self._quick_poll)

        if w["kind"] == "web":
            def got(data: dict):
                if self._quick_watch is not w:
                    return
                count = data.get("count", 0)
                if count < w["count"]:  # pagina ricaricata o chat nuova: riparto da qui
                    w["count"] = count
                if count <= w["count"]:  # la risposta non è ancora comparsa
                    if time.monotonic() - w.get("t0", time.monotonic()) > 120:
                        self._quick_watch = None
                        self.instance.reply(w["sock"], {"type": "answer_unavailable", "text": tr(
                            "_Non vedo la risposta nella pagina: guardala in Helpix (↗)._")})
                        return
                    QTimer.singleShot(900, self._quick_poll)
                    return
                text = data.get("text", "")
                w["stable"] = w["stable"] + 1 if text == w["last"] and not data.get("busy") else 0
                w["last"] = text
                push(text, w["stable"] >= 2)
            self.web.last_answer(got)
        else:
            def got_screen(screen: str):
                if self._quick_watch is not w:
                    return
                if screen == w["before"]:
                    QTimer.singleShot(900, self._quick_poll)
                    return
                # quello che è cambiato nel terminale, senza righe vuote ripetute: le ultime 60 righe
                lines = [ln.rstrip() for ln in screen.splitlines()]
                before = set(w["before"].splitlines())
                fresh = [ln for ln in lines if ln.strip() and ln not in before] or lines
                text = "```\n" + "\n".join(fresh[-60:]) + "\n```"
                w["stable"] = w["stable"] + 1 if screen == w["last"] else 0
                w["last"] = screen
                push(text, w["stable"] >= 3)  # terminale fermo per qualche secondo: l'agente ha finito
            self.agent.term.screen_text(got_screen)

    # ------------------------------------------------------------ estensione del browser
    def _start_bridge(self):
        self.bridge = BridgeServer(self)
        self.bridge_ok = self.bridge.start()
        self.web.bridge = self.bridge if self.bridge_ok else None
        if not self.bridge_ok:
            return
        self.bridge.run_requested.connect(self._ext_run)
        self.bridge.screenshot_requested.connect(self._ext_screenshot)
        self.bridge.diagnostics_requested.connect(self._ext_diagnostics)
        self.bridge.package_result.connect(self._ext_package_done)
        self.bridge.clients_changed.connect(self._bridge_changed)
        try:  # aggiorna il lanciatore dell'host (percorsi cambiati dopo un aggiornamento)
            from .. import native_install
            if native_install.installed():
                native_install.install()
        except OSError:
            pass

    def _ext_package_done(self, ok: bool):
        name = WEB_SITES[self.web.site]["label"]
        if ok:
            self.notify(tr("Task incollato nella chat di {name} nel browser: controlla e premi Invio.").format(
                name=name), 9000)
        else:
            self.notify(tr("Non trovo la casella della chat di {name} nel browser: forse devi ancora fare "
                           "l'accesso. Accedi e usa «Copia» nell'avviso della pagina.").format(name=name), 12000)

    def _bridge_changed(self):
        self.web.set_bridge_state(self.bridge.connected, self.bridge.browsers())

    def open_browser_dialog(self):
        from .browser_dialog import BrowserDialog
        BrowserDialog(self.bridge if self.bridge_ok else None, self).exec()

    def _ext_run(self, msg: dict):
        if getattr(self, "locked", False):  # bloccato: niente comandi o catture dal browser
            self.bridge.run_status(msg, "rejected", reason=tr("Helpix è bloccato: sbloccalo e riprova."))
            return
        """«Esegui con Helpix» nella chat del browser: stessi controlli del pulsante Esegui."""
        text = msg.get("cmd", "")
        summary = parse_summary(text)
        if summary:
            self.bridge.run_status(msg, "summary")
            self._summary_received(summary)
            return
        cmd = looks_like_command(text)
        if not cmd:
            self.bridge.run_status(msg, "rejected", reason=tr(
                "Non sembra un comando da eseguire su questo PC (o il programma non è installato)."))
            return
        if self.runner and self.runner.isRunning():
            self.bridge.run_status(msg, "busy")
            return
        info = analyze(cmd)
        if info.needs_root and info.sudo_options:
            self.bridge.run_status(msg, "rejected", reason=tr(
                "Le opzioni di sudo (es. sudo -u, sudo -i) non sono supportate: usa «sudo comando»."))
            return
        if info.needs_root and not pkexec_available():
            self.bridge.run_status(msg, "rejected", reason=tr(
                "pkexec (polkit) non è installato: impossibile ottenere i privilegi di amministratore."))
            return
        warnings = list(info.dangers) + ([info.interactive] if info.interactive else [])
        if warnings and not msg.get("confirmed"):
            self.bridge.run_status(msg, "confirm", warnings=warnings)
            return
        self._ext_request = msg
        self.bridge.run_status(msg, "running")
        self.run_command(cmd, "ext", confirmed=True)

    def _ext_screenshot(self, msg: dict):
        if getattr(self, "locked", False):  # bloccato: niente comandi o catture dal browser
            self.bridge.run_status(msg, "rejected", reason=tr("Helpix è bloccato: sbloccalo e riprova."))
            return
        if self.shots.busy:
            self.bridge.notify(msg, tr("C'è già uno screenshot in corso."))
            return
        msg["_visible"] = self.isVisible() and not self.isMinimized()
        self._ext_shot = msg
        self.shots.start("smart")

    def _ext_shot_cancelled(self):
        req, self._ext_shot = self._ext_shot, None
        if req is not None:
            self._ext_shot_restore(req)

    def _ext_shot_restore(self, req: dict):
        """Rimette Helpix com'era senza rubare il primo piano al browser."""
        if req.get("_visible"):
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.show()
            self.lower()
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        elif not self.isVisible():
            self.showMinimized()

    def _ext_shot_done(self, path: str):
        req, self._ext_shot = self._ext_shot, None
        self._ext_shot_restore(req)
        try:
            path = normalize_image(path)
        except Exception as exc:  # noqa: BLE001
            self.bridge.notify(req, str(exc))
            return
        if self.bridge.paste_image(req["site"], path, req["_client"], req["tab"]):
            label = WEB_SITES[req["site"]]["label"]
            self.session.site = req["site"]
            self.session.add(Message("user", tr("Screenshot inviato a {site}").format(site=label), images=[path],
                                     kind="shot", meta={"site": req["site"]}))

    def _ext_diagnostics(self, msg: dict):
        if getattr(self, "locked", False):  # bloccato: niente comandi o catture dal browser
            self.bridge.run_status(msg, "rejected", reason=tr("Helpix è bloccato: sbloccalo e riprova."))
            return
        if not self.btn_diag.isEnabled():
            self.bridge.notify(msg, tr("La diagnosi è già in corso."))
            return
        msg["_visible"] = self.isVisible() and not self.isMinimized()
        self._ext_diag = msg
        self.quick_diagnostics()

    def closeEvent(self, event):  # noqa: N802
        if getattr(self, "tray", None) and not self._quitting and self.settings.get("close_to_tray", True):
            event.ignore()  # la X riduce nell'area di notifica; si esce dal menu dell'icona
            self.to_tray()
            return
        if self.runner and self.runner.isRunning():
            self.runner.cancel()
            self.runner.wait(4000)
        self.session.save()
        self.settings.save()
        for w in list(self._workers):
            if not w.wait(1500):
                w.terminate()
                w.wait(500)
        self.web.shutdown()
        if getattr(self, "_shortcut", None):
            self._shortcut.stop()
        try:  # Helpix esce: anche la finestra rapida (processo separato) si chiude
            stop_quick_window()
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self, "instance"):
            self.instance.stop()
        if self.agent:
            self.agent.shutdown()
        if self.bridge_ok:
            self.bridge.stop()
        tray = getattr(self, "tray", None)
        super().closeEvent(event)
        if tray:  # con l'icona nell'area di notifica Qt non esce da solo alla chiusura dell'ultima finestra
            tray.hide()
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()

