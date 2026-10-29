# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pannello degli agenti a riga di comando: Claude Code, Codex o Gemini CLI in un terminale vero.

L'agente lavora nella cartella di Helpix (istruzioni, task da continuare, screenshot) e si
collega con il proprio account. Helpix gli passa screenshot e diagnosi incollando il
percorso del file nella riga di comando, e legge il riepilogo che l'agente scrive su file.
"""
from __future__ import annotations

import os
import shlex
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ..system import IS_WINDOWS
from .. import agents, site_icons, theme
from ..i18n import tr
from .controls import IconButton
from .terminal_view import TerminalView


class _InstallPage(QWidget):
    install = Signal()
    retry = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("chatContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("group")
        card.setMaximumWidth(640)
        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(12)
        self.logo = QLabel()
        self.logo.setFixedSize(48, 48)
        v.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.title)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setObjectName("secondary")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.text)
        self.cmd = QLabel()
        self.cmd.setObjectName("codeChip")
        self.cmd.setWordWrap(True)
        self.cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cmd.setFont(theme.mono_font(9))
        v.addWidget(self.cmd)
        row = QHBoxLayout()
        self.docs = QPushButton(tr("Istruzioni ufficiali"))
        row.addWidget(self.docs)
        again = QPushButton(tr("Ricontrolla"))
        again.setToolTip(tr("Già installato? Helpix lo cerca di nuovo"))
        again.clicked.connect(self.retry.emit)
        row.addWidget(again)
        row.addStretch(1)
        go = QPushButton(tr("Installa"))
        go.setObjectName("primary")
        go.clicked.connect(self.install.emit)
        row.addWidget(go)
        v.addLayout(row)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card, 10)
        wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(2)
        self._url = ""
        self.docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))

    def show_agent(self, key: str):
        a = agents.AGENTS[key]
        self.logo.setPixmap(site_icons.pixmap(a["icon"], 48))
        self.title.setText(tr("{name} non è installato").format(name=a["label"]))
        self.text.setText(tr("{name} di {who} lavora nel terminale qui sotto: legge i tuoi screenshot, esegue i "
                             "comandi (chiedendoti conferma) e si collega con il tuo account nel browser. {plan}.\n"
                             "Helpix lo installa per il tuo utente con il comando ufficiale:").format(
            name=a["label"], who=a["who"], plan=a["plan"]))
        self.cmd.setText(agents.install_command(key))
        self._url = a["docs"]


class AgentPanel(QWidget):
    status_changed = Signal()
    summary_ready = Signal(str)
    summary_failed = Signal(str)
    hint = Signal(str)

    def __init__(self, key: str = "claude-code", parent=None):
        super().__init__(parent)
        self.key = key if key in agents.AGENTS else "claude-code"
        self.state = "idle"        # idle | running | installing | exited
        self.model = "default"     # modello ed effort scelti (dalle impostazioni di Helpix)
        self.effort = "auto"
        self._summary_until = 0.0
        self._summary_last = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("terminalBar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(14, 6, 8, 6)
        bh.setSpacing(8)
        self.status = QLabel()
        self.status.setObjectName("secondary")
        bh.addWidget(self.status, 1)
        self.btn_restart = IconButton("refresh", tr("Riavvia l'agente (nuova conversazione)"), text=tr("Riavvia"),
                                      icon_size=15)
        self.btn_restart.clicked.connect(lambda: self.start())
        bh.addWidget(self.btn_restart)
        self.btn_folder = IconButton("folder", tr("Apri la cartella di lavoro dell'agente"), icon_size=15)
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(agents.workspace()))))
        bh.addWidget(self.btn_folder)
        v.addWidget(bar)

        self.stack = QStackedWidget()
        self.install_page = _InstallPage()
        self.install_page.install.connect(self.install)
        self.install_page.retry.connect(self.ensure_started)
        self.term = TerminalView()
        self.term.pty.finished.connect(self._exited)
        self.stack.addWidget(self.install_page)
        self.stack.addWidget(self.term)
        v.addWidget(self.stack, 1)
        self._update_status()

    # ------------------------------------------------------------ stato
    @property
    def label(self) -> str:
        return agents.AGENTS[self.key]["label"]

    @property
    def running(self) -> bool:
        return self.state == "running" and self.term.pty.running

    def _update_status(self):
        texts = {"idle": tr("Non avviato"), "running": tr("{name} nel terminale · accesso con il tuo account"),
                 "installing": tr("Installazione di {name}…"), "exited": tr("{name} si è chiuso")}
        self.status.setText(texts[self.state].format(name=self.label))
        self.btn_restart.setVisible(self.state in ("running", "exited"))
        self.status_changed.emit()

    def set_agent(self, key: str):
        if key == self.key and self.state != "idle":
            return
        if self.term.pty.running:
            self.term.pty.stop()
        self.key = key
        self.state = "idle"
        self.ensure_started()

    # ------------------------------------------------------------ avvio
    def ensure_started(self, task_text: str | None = None, prompt: str | None = None):
        """Avvia l'agente se non è già in esecuzione (o mostra come installarlo)."""
        if self.running and task_text is None and prompt is None:
            return
        if not agents.find_cli(self.key):
            self.state = "idle"
            self.install_page.show_agent(self.key)
            self.stack.setCurrentWidget(self.install_page)
            self._update_status()
            return
        self.start(task_text, prompt)

    def start(self, task_text: str | None = None, prompt: str | None = None):
        exe = agents.find_cli(self.key)
        if not exe:
            self.ensure_started()
            return
        ws = agents.write_context(self.key, task_text)
        argv = [exe] + agents.choice_args(self.key, self.model, self.effort) + (
            agents.AGENTS[self.key]["prompt_args"](prompt) if prompt else [])
        self.term.pty.finished.disconnect(self._exited)
        self.term.pty.stop()
        self.term.pty.finished.connect(self._exited)
        self.term.clear()
        self.stack.setCurrentWidget(self.term)
        try:
            self.term.pty.start(argv, str(ws), {"PATH": agents.search_path()})
        except OSError as exc:
            self.term.write_local(tr("Impossibile avviare {name}: {exc}\n").format(name=self.label, exc=exc))
            self.state = "exited"
        else:
            self.state = "running"
        self._update_status()
        QTimer.singleShot(300, self.term.focus_terminal)

    def install(self):
        """Installa con il comando ufficiale, nel terminale, così si vede cosa succede."""
        a = agents.AGENTS[self.key]
        self.term.pty.finished.disconnect(self._exited)
        self.term.pty.stop()
        self.term.pty.finished.connect(self._exited)
        self.term.clear()
        self.stack.setCurrentWidget(self.term)
        if IS_WINDOWS:
            self._install_windows()
            return
        from .. import sysdeps
        steps = []
        missing = sysdeps.tools_missing(a.get("needs", []), path=agents.search_path())
        prereq = sysdeps.shell_install(missing) if missing else None
        if prereq:
            self.term.write_local(tr("Prima installo ciò che serve ({tools}) con il gestore pacchetti; la password "
                                     "di amministratore la chiede il sistema qui sotto:\n$ {cmd}\n\n").format(
                tools=", ".join(missing), cmd=prereq))
            steps.append(prereq)
        elif missing:
            self.term.write_local(tr("Manca {tools}: installalo con il gestore pacchetti della tua distribuzione, "
                                     "poi riprova.\n\n").format(tools=", ".join(missing)))
        if a.get("precheck"):
            steps.append(f"{{ {a['precheck']}; }}")
        self.term.write_local(tr("Installo {name} con il comando ufficiale:\n$ {cmd}\n\n").format(
            name=a["label"], cmd=a["install"]))
        self.state = "installing"
        self._update_status()
        script = " && ".join([*steps, a["install"]]) + "; rc=$?; echo; exit $rc"
        self.term.pty.start(["bash", "-lc", script], os.path.expanduser("~"), {"PATH": agents.search_path()})

    def _install_windows(self):
        """Windows: installazione in PowerShell con il comando ufficiale; Node.js (per Gemini CLI) con winget."""
        import shutil
        from ..winshell import powershell
        a = agents.AGENTS[self.key]
        path = agents.search_path()
        steps = ["$ErrorActionPreference = 'Stop'", "$ProgressPreference = 'SilentlyContinue'"]
        if "npm" in agents.needs(self.key) and not shutil.which("npm", path=path):
            self.term.write_local(tr("Prima installo Node.js con winget (Windows può chiedere il permesso di "
                                     "amministratore):\n> winget install OpenJS.NodeJS.LTS\n\n"))
            steps += ["winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements",
                      "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
                      "[Environment]::GetEnvironmentVariable('Path','User')"]
        if agents.precheck(self.key):
            steps.append(agents.precheck(self.key))
        cmd = agents.install_command(self.key)
        self.term.write_local(tr("Installo {name} con il comando ufficiale:\n> {cmd}\n\n").format(
            name=a["label"], cmd=cmd))
        steps.append(cmd)
        self.state = "installing"
        self._update_status()
        script = "\n".join(steps) + "\nexit 0"
        self.term.pty.start([powershell(), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                            os.path.expanduser("~"), {"PATH": path})

    def _exited(self, rc: int):
        if self.state == "installing":
            if agents.find_cli(self.key):
                self.term.write_local(tr("\n✓ {name} installato. Lo avvio…\n").format(name=self.label))
                QTimer.singleShot(1200, lambda: self.start())
                return
            self.term.write_local(tr("\nInstallazione non riuscita (codice {rc}). Controlla il messaggio qui sopra o "
                                     "usa le istruzioni ufficiali.\n").format(rc=rc))
            self.state = "idle"
            QTimer.singleShot(4000, self.ensure_started)
        else:
            self.term.write_local(tr("\n[{name} si è chiuso: premi «Riavvia» per una nuova conversazione]\n").format(
                name=self.label))
            self.state = "exited"
        self._update_status()

    def apply_choice(self, model: str | None = None, effort: str | None = None) -> str:
        """Cambia modello o effort: «live» se l'agente lo applica subito, «restart» se serve riavviarlo."""
        a = agents.AGENTS[self.key]
        if model is not None:
            self.model = model
        if effort is not None:
            self.effort = effort
        if not self.running:
            return "restart"
        if model is not None and "live_model" in a:
            self.paste(a["live_model"](model if model != "default" else "default"), enter=True)
            return "live"
        if effort is not None and "live_effort" in a:
            self.paste(a["live_effort"](effort), enter=True)
            return "live"
        return "restart"

    # ------------------------------------------------------------ dati dall'utente
    def paste(self, text: str, enter: bool = False):
        """Scrive nella riga di comando dell'agente come un incolla (Invio solo se richiesto)."""
        if not self.running:
            self.hint.emit(tr("{name} non è in esecuzione: premi «Riavvia».").format(name=self.label))
            return False
        self.term.pty.paste(text)
        if enter:
            QTimer.singleShot(250, lambda: self.term.pty.write("\r"))
        self.term.focus_terminal()
        return True

    def send_screenshot(self, path: str) -> bool:
        dest = agents.save_screenshot(path)
        return self.paste(tr("Guarda lo screenshot {path} ").format(path=shlex.quote(str(dest))))

    def send_diagnostics(self, text: str) -> bool:
        dest = agents.save_diagnostics(text)
        return self.paste(tr("Leggi la diagnosi del PC nel file {path}. Il problema è: ").format(
            path=shlex.quote(str(dest))))

    # ------------------------------------------------------------ riepilogo
    def request_summary(self, timeout: float = 300.0):
        """Chiede all'agente di scrivere il riepilogo su file e lo legge appena è completo."""
        if not self.running:
            self.summary_failed.emit(tr("{name} non è in esecuzione: avvialo e riprova.").format(name=self.label))
            return
        agents.reset_summary()
        self._summary_until = time.monotonic() + timeout
        self._summary_last = None
        self.paste(agents.summary_request(), enter=True)
        QTimer.singleShot(2000, self._summary_poll)

    @property
    def summary_pending(self) -> bool:
        return time.monotonic() < self._summary_until

    def cancel_summary(self):
        self._summary_until = 0.0

    def _summary_poll(self):
        if not self.summary_pending:
            return
        text = agents.read_summary()
        if text and text == self._summary_last:  # uguale a due controlli di fila: l'agente ha finito di scriverlo
            self._summary_until = 0.0
            self.summary_ready.emit(text)
            return
        self._summary_last = text
        if time.monotonic() < self._summary_until:
            QTimer.singleShot(1500, self._summary_poll)
        else:
            self.summary_failed.emit(tr("{name} non ha scritto il riepilogo nel file {file}.").format(
                name=self.label, file=agents.SUMMARY_FILE))

    def shutdown(self):
        self._summary_until = 0.0
        self.term.pty.stop()

    def icon_key(self) -> str:
        return agents.AGENTS[self.key]["icon"]
