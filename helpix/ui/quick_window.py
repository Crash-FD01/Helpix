# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra rapida: un riquadro piccolo in basso a destra per chiedere al volo.

Si apre e si chiude con la scorciatoia globale (o `helpix --quick`): c'è sempre una sola
finestra rapida, che resta pronta in un processo a parte. Parla con la finestra principale di
Helpix tramite il socket dell'istanza: il testo va all'assistente attivo e la risposta torna
qui, in una piccola area che scorre. Da qui si scelgono anche modello ed effort.

Di norma la finestra è ancorata all'angolo; con il lucchetto si sblocca, si sposta e,
richiudendolo, resta ancorata nella nuova posizione.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QKeyEvent, QKeySequence, QPainter, QPainterPath,
                           QPen, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import theme
from ..config import DATA_DIR
from ..i18n import tr
from ..icons import icon
from ..instance import socket_path
from ..theme import C
from .controls import IconButton

RADIUS = 16
MARGIN = 18
PANEL_GUESS = 64        # se il sistema non dice dov'è il pannello, lascio spazio in basso
WIDTH = 480
ANSWER_HEIGHT = 260
NO_ANSWER_AFTER = 150_000  # ms senza risposta: la finestra non resta mai bloccata
POS_FILE = DATA_DIR / "quick.json"


def quick_socket_path() -> str:
    from ..system import channel
    return channel("quick")


def _load_pos() -> dict:
    try:
        return json.loads(POS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_pos(data: dict) -> None:
    try:
        POS_FILE.parent.mkdir(parents=True, exist_ok=True)
        POS_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


class _Input(QPlainTextEdit):
    submit = Signal()
    cancel = Signal()

    def keyPressEvent(self, event: QKeyEvent):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel.emit()
            return
        super().keyPressEvent(event)


class QuickWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(tr("Helpix — richiesta rapida"))
        self.setFixedWidth(WIDTH)
        self.sock = QLocalSocket(self)
        self.sock.readyRead.connect(self._read)
        self.sock.connected.connect(self._connected)
        # Helpix chiuso: solo ricollegamento silenzioso (per esempio dopo un riavvio per la lingua). Riaprirlo
        # da qui farebbe ripartire Helpix subito dopo «Esci»: lo si riapre solo se l'utente usa la finestra rapida.
        self.sock.disconnected.connect(self._lost)
        self._buf = b""
        self._launched = False
        self._may_launch = False
        self._tries = 0
        self._sending = False
        self._history: list[tuple[str, str]] = []   # (domanda, risposta) di questa finestra
        self._answer = ""
        self._filling = False
        pos = _load_pos()
        self.anchored = pos.get("locked", True)
        self.offset = (int(pos.get("dx", MARGIN)), int(pos.get("dy", MARGIN)))
        self._no_answer = QTimer(self)
        self._no_answer.setSingleShot(True)
        self._no_answer.setInterval(NO_ANSWER_AFTER)
        self._no_answer.timeout.connect(self._answer_timeout)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 14, 14)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(22))
        logo.setFixedSize(22, 22)
        head.addWidget(logo)
        name = QLabel("Helpix")
        name.setStyleSheet("font-weight: 600;")
        head.addWidget(name)
        self.target = QLabel(tr("collegamento…"))
        self.target.setObjectName("secondary")
        head.addWidget(self.target, 1)
        self.btn_open = IconButton("external", tr("Apri la conversazione in Helpix"), size=26, icon_size=14,
                                   color_key="secondary")
        self.btn_open.clicked.connect(lambda: self._send({"type": "show"}))
        head.addWidget(self.btn_open)
        self.btn_clear = IconButton("plus", tr("Nuova richiesta (pulisce questa finestra)"), size=26, icon_size=14,
                                    color_key="secondary")
        self.btn_clear.clicked.connect(self.clear_conversation)
        self.btn_clear.hide()
        head.addWidget(self.btn_clear)
        self.btn_anchor = IconButton("lock", "", size=26, icon_size=14, color_key="secondary")
        self.btn_anchor.clicked.connect(self.toggle_anchor)
        head.addWidget(self.btn_anchor)
        close = IconButton("x", tr("Nascondi (Esc o la scorciatoia)"), size=26, icon_size=14, color_key="secondary")
        close.clicked.connect(self.hide_now)
        head.addWidget(close)
        v.addLayout(head)

        # modello ed effort dell'assistente attivo
        choice = QHBoxLayout()
        choice.setSpacing(6)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setToolTip(tr("Modello"))
        self.model.setMinimumWidth(190)
        self.model.activated.connect(lambda _i: self._choose_model())
        self.model.lineEdit().editingFinished.connect(self._choose_model)
        choice.addWidget(self.model, 3)
        self.effort = QComboBox()
        self.effort.setToolTip(tr("Effort: quanto ragiona il modello prima di rispondere"))
        self.effort.activated.connect(lambda _i: self._choose_effort())
        choice.addWidget(self.effort, 2)
        self.choice_note = QLabel()
        self.choice_note.setObjectName("secondary")
        self.choice_note.setWordWrap(True)
        choice.addWidget(self.choice_note, 5)
        v.addLayout(choice)

        # risposte: area piccola che scorre, compare dopo il primo invio
        self.answers = QTextBrowser()
        self.answers.setOpenExternalLinks(True)
        self.answers.setFixedHeight(ANSWER_HEIGHT)
        self.answers.hide()
        v.addWidget(self.answers)

        self.input = _Input()
        self.input.setPlaceholderText(tr("Chiedi qualcosa o descrivi il problema…"))
        self.input.setFixedHeight(76)
        self.input.submit.connect(self.send)
        self.input.cancel.connect(self.hide_now)
        v.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.status = QLabel()
        self.status.setObjectName("secondary")
        row.addWidget(self.status, 1)
        self.btn_unlock = QPushButton(tr("Sblocca"))
        self.btn_unlock.setIcon(icon("lock", C["text"], 14))
        self.btn_unlock.clicked.connect(self._unlock)
        self.btn_unlock.hide()
        row.addWidget(self.btn_unlock)
        self.btn_send = QPushButton(tr("Invia"))
        self.btn_send.setObjectName("primary")
        self.btn_send.setIcon(icon("send", "#FFFFFF", 14))
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.btn_send)
        v.addLayout(row)
        self._idle_status()
        self._anchor_icon()
        # con la finestra rapida in primo piano la scorciatoia arriva a lei: la nasconde
        QShortcut(QKeySequence("Ctrl+Alt+H"), self, self.hide_now)
        self._last_toggle = 0.0
        theme.manager().changed.connect(lambda _d: (self.update(), self._render()))
        self._connect(launch=True)  # aperta dalla scorciatoia con Helpix chiuso: lo avvia

    # ------------------------------------------------------------ aspetto e posizione
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        p.fillPath(path, QColor(C["window"]))
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawPath(path)
        p.end()

    @staticmethod
    def _area():
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if area == screen.geometry():  # il sistema non indica il pannello (XWayland): lascio spazio
            area = area.adjusted(0, 0, 0, -PANEL_GUESS)
        return area

    def place(self):
        """Ancorata: stessa distanza dall'angolo in basso a destra, cresce verso l'alto."""
        self.adjustSize()
        area = self._area()
        dx, dy = self.offset
        x = min(max(area.left(), area.right() - self.width() - dx + 1), area.right() - self.width() + 1)
        y = min(max(area.top(), area.bottom() - self.height() - dy + 1), area.bottom() - self.height() + 1)
        self.move(x, y)

    def _anchor_icon(self):
        self.btn_anchor.set_icon_name("lock" if self.anchored else "unlock")
        self.btn_anchor.setToolTip(tr("Ancorata all'angolo: premi per spostarla") if self.anchored
                                   else tr("Trascinala dove vuoi, poi premi per ancorarla lì"))

    def toggle_anchor(self):
        if self.anchored:
            self.anchored = False
        else:  # ancoro nella posizione attuale (distanza dall'angolo in basso a destra)
            area = self._area()
            g = self.frameGeometry()
            self.offset = (max(0, area.right() - g.right()), max(0, area.bottom() - g.bottom()))
            self.anchored = True
        _save_pos({"locked": self.anchored, "dx": self.offset[0], "dy": self.offset[1]})
        self._anchor_icon()

    def _resize_keep_anchor(self):
        if self.anchored:
            self.place()
        else:
            bottom = self.frameGeometry().bottom()
            self.adjustSize()
            self.move(self.x(), bottom - self.height() + 1)

    def hide_now(self):
        """Nascosta dall'utente (Esc, ×, scorciatoia con la finestra in primo piano): si può riaprire subito."""
        self._last_toggle = 0.0
        self.hide()

    def toggle(self):
        now = time.monotonic()
        if now - self._last_toggle < 0.35:  # stessa pressione arrivata due volte (portal e desktop)
            return
        self._last_toggle = now
        if self.isVisible():
            self.hide()
        else:
            if self.sock.state() != QLocalSocket.LocalSocketState.ConnectedState:
                self._tries, self._launched = 0, False  # Helpix chiuso nel frattempo: lo riapro (l'hai chiesto tu)
                self._connect(launch=True)
            else:
                self._send({"type": "hello"})  # assistente, modello ed effort aggiornati
            self.place()
            self.show()
            self.place()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(50, self.input.setFocus)

    def mousePressEvent(self, event):  # noqa: N802 - si sposta solo se sbloccata
        if not self.anchored and event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def _idle_status(self):
        self.status.setText(tr("Invio per inviare · Esc per nascondere"))

    # ------------------------------------------------------------ collegamento con Helpix
    def _lost(self):
        self._tries, self._launched, self._may_launch = 0, False, False
        QTimer.singleShot(1000, self._connect)

    def _connect(self, launch: bool | None = None):
        if launch is not None:
            self._may_launch = launch
        if self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            return
        self.sock.abort()
        self.sock.connectToServer(socket_path())
        QTimer.singleShot(600, self._check_connected)

    def _check_connected(self):
        if self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            return
        self._tries += 1
        if self._may_launch and not self._launched:
            self._launched = True
            self.target.setText(tr("avvio Helpix…"))
            env = dict(os.environ)
            env.pop("QT_QPA_PLATFORM", None)  # la finestra principale usa la piattaforma normale
            from ..system import helpix_argv
            subprocess.Popen(helpix_argv(), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        if self._tries > 60:
            if self._may_launch:
                self.target.setText(tr("Helpix non risponde"))
            return  # in silenzio: la prossima volta che la usi riprova (e se serve avvia Helpix)
        QTimer.singleShot(500, self._connect)

    def _connected(self):
        self._tries = 0
        self._send({"type": "hello"})

    def _send(self, msg: dict) -> bool:
        if self.sock.state() != QLocalSocket.LocalSocketState.ConnectedState:
            self.status.setText(tr("Helpix non è ancora pronto…"))
            if self.isVisible():  # l'utente la sta usando: se Helpix è chiuso lo riapre
                self._tries = 0
                self._connect(launch=True)
            return False
        self.sock.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.sock.flush()
        return True

    def _read(self):
        self._buf += bytes(self.sock.readAll())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            self._handle(msg)

    def _handle(self, msg: dict):
        kind = msg.get("type")
        if kind == "status":
            self.target.setText("→ " + str(msg.get("target", "")))
            self._fill_choices(msg)
        elif kind == "sent":
            self.status.setText(tr("In attesa della risposta…"))
        elif kind == "answer":
            self._no_answer.start()
            self._answer = str(msg.get("text", ""))
            self._render()
            if msg.get("done"):
                self._finish_answer()
            else:
                self.status.setText(tr("Sta rispondendo…"))
        elif kind == "answer_unavailable":
            self._answer = str(msg.get("text", "")) or tr("_La risposta è nella finestra di Helpix._")
            self._render()
            self._finish_answer()
        elif kind == "locked":
            if msg.get("target"):
                self.target.setText("→ " + str(msg["target"]))
            if self._sending and self._history and not self._history[-1][1]:
                question = self._history.pop()[0]  # non è partito: la domanda torna nella casella
                self.input.setPlainText(question)
                self._render()
            self._sending = False
            self._no_answer.stop()
            self.btn_send.setEnabled(False)
            self.btn_unlock.show()
            self.btn_unlock.setEnabled(True)
            self.status.setText(tr("Helpix è bloccato"))
        elif kind == "unlocked":
            self.btn_unlock.hide()
            self.btn_send.setEnabled(True)
            self._idle_status()
            self._send({"type": "hello"})
            self.input.setFocus()
        elif kind == "note":
            self.status.setText(str(msg.get("text", "")))
        elif kind == "error":
            self._finish_answer()
            self.status.setText(str(msg.get("text", "")))

    # ------------------------------------------------------------ modello ed effort
    def _fill_choices(self, msg: dict):
        self._filling = True
        models, efforts = msg.get("models") or [], msg.get("efforts") or []
        self.model.clear()
        self.model.addItems([str(m) for m in models])
        self.model.setCurrentText(str(msg.get("model") or ""))
        self.model.setVisible(bool(models))
        self.effort.clear()
        for value, label in efforts:
            self.effort.addItem(label, value)
        idx = self.effort.findData(msg.get("effort"))
        self.effort.setCurrentIndex(max(idx, 0))
        self.effort.setVisible(bool(efforts))
        note = str(msg.get("note") or "")
        self.choice_note.setText(note)
        self.choice_note.setVisible(bool(note))
        self._filling = False
        if self.isVisible():
            self._resize_keep_anchor()

    def _choose_model(self):
        if not self._filling and self.model.currentText().strip():
            self._send({"type": "set_model", "model": self.model.currentText().strip()})

    def _choose_effort(self):
        if not self._filling:
            self._send({"type": "set_effort", "effort": self.effort.currentData()})

    # ------------------------------------------------------------ conversazione
    def _render(self):
        if not self._history:
            return
        parts = []
        for i, (question, answer) in enumerate(self._history):
            last = i == len(self._history) - 1
            text = self._answer if last else answer
            q = question.replace("\n", "  \n")
            parts.append(f"**{tr('Tu')}:** {q}\n\n{text or tr('_…_')}")
        bar = self.answers.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.answers.setMarkdown("\n\n---\n\n".join(parts))
        if at_end:
            bar.setValue(bar.maximum())

    def _finish_answer(self):
        self._no_answer.stop()
        if self._history:
            self._history[-1] = (self._history[-1][0], self._answer)
        self._sending = False
        self.btn_send.setEnabled(True)
        self._idle_status()
        self.input.setFocus()

    def _answer_timeout(self):
        """Nessuna risposta per un po': non resto bloccata, la risposta si guarda in Helpix."""
        if not self._sending:
            return
        self._answer = self._answer or tr("_Nessuna risposta qui: guardala in Helpix (↗)._")
        self._render()
        self._finish_answer()
        self._send({"type": "cancel"})

    def clear_conversation(self):
        if self._sending:
            self._send({"type": "cancel"})
        self._no_answer.stop()
        self._sending = False
        self.btn_send.setEnabled(True)
        self._idle_status()
        self._history.clear()
        self._answer = ""
        self.answers.clear()
        self.answers.hide()
        self.btn_clear.hide()
        self._resize_keep_anchor()
        self.input.setFocus()

    def _unlock(self):
        if self._send({"type": "unlock"}):
            self.btn_unlock.setEnabled(False)
            self.status.setText(tr("Conferma nel dialogo del sistema…"))

    def send(self):
        text = self.input.toPlainText().strip()
        if self._sending or not text:
            return
        if not self._send({"type": "send", "text": text}):
            return
        self._sending = True
        self.btn_send.setEnabled(False)
        self.status.setText(tr("Invio…"))
        self._history.append((text, ""))
        self._answer = ""
        self.input.clear()
        self._no_answer.start()
        if self.answers.isHidden():
            self.answers.show()
            self.btn_clear.show()
            self._resize_keep_anchor()
        self._render()


class _QuickServer(QLocalServer):
    """Una sola finestra rapida: i lanci successivi le chiedono solo di mostrarsi o nascondersi."""

    def __init__(self, win: QuickWindow):
        super().__init__(win)
        self.win = win
        self.newConnection.connect(self._accept)

    def _accept(self):
        while self.hasPendingConnections():
            sock = self.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))

    def _read(self, sock):
        for line in bytes(sock.readAll()).splitlines():
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("type") == "ping":  # Helpix controlla che la finestra rapida sia della sua versione
                from .. import __version__
                sock.write((json.dumps({"type": "pong", "version": __version__, "pid": os.getpid()}) + "\n")
                           .encode("utf-8"))
                sock.flush()
            elif msg.get("type") == "toggle":
                self.win.toggle()
            elif msg.get("type") == "show":
                if not self.win.isVisible():
                    self.win.toggle()
            elif msg.get("type") == "quit":  # «Esci da Helpix»: si chiude anche la finestra rapida
                QApplication.instance().quit()


def _xcb_usable() -> bool:
    """Il plugin X11 di Qt 6 ha bisogno di libxcb-cursor: senza, resto su Wayland (posizione scelta dal desktop)."""
    import ctypes.util
    return bool(ctypes.util.find_library("xcb-cursor"))


def run(argv: list[str]) -> int:
    """Processo della finestra rapida (`helpix --quick`): la prima volta la crea, poi la mostra o nasconde."""
    from ..instance import send_once
    if send_once({"type": "toggle"}, quick_socket_path()):
        return 0
    # Su Wayland una finestra non può scegliere la propria posizione: la finestra rapida usa
    # XWayland (se c'è) per comparire davvero in basso a destra.
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("DISPLAY") \
            and "QT_QPA_PLATFORM" not in os.environ and _xcb_usable():
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    from PySide6.QtWidgets import QApplication

    from ..config import Settings
    from ..i18n import set_language
    settings = Settings()
    set_language(settings.get("language", "auto"))
    QApplication.setApplicationName("Helpix")
    QApplication.setDesktopFileName("helpix")
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)  # nascosta resta pronta per la prossima scorciatoia
    theme.setup(app, settings.get("theme", "auto"))
    app.setWindowIcon(theme.app_icon())
    win = QuickWindow()
    server = _QuickServer(win)
    path = quick_socket_path()
    QLocalServer.removeServer(path)
    server.listen(path)
    win.toggle()
    return app.exec()
