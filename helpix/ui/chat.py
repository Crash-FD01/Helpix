# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista della conversazione: bolle dei messaggi, card dei comandi, allegati, campo di testo."""
from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from ..executor import analyze
from ..providers import PROVIDERS
from ..screenshot import new_shot_path
from ..session import Message
from ..theme import mono_font
from ..i18n import tr

CODE_RE = re.compile(r"```[ \t]*([\w+#.-]*)[^\n]*\n(.*?)(?:```|\Z)", re.S)
SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console", "terminal", "shell-session"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def split_segments(text: str) -> list[tuple]:
    """Divide la risposta dell'IA in testo markdown e blocchi di codice."""
    segs: list[tuple] = []
    pos = 0
    for m in CODE_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            segs.append(("md", before))
        lang = (m.group(1) or "").lower()
        code = m.group(2).rstrip("\n")
        if lang in ("console", "shell-session"):
            cmds = [line[2:] for line in code.splitlines() if line.startswith("$ ")]
            code = "\n".join(cmds) if cmds else code
        if code.strip():
            segs.append(("code", lang, code))
        pos = m.end()
    rest = text[pos:].strip()
    if rest:
        segs.append(("md", rest))
    return segs


class MarkdownLabel(QLabel):
    def __init__(self, text: str, markdown: bool = True):
        super().__init__()
        self.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
        self.setText(text)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setOpenExternalLinks(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)


class ThumbLabel(QLabel):
    """Miniatura cliccabile: apre l'immagine con il visualizzatore di sistema."""

    def __init__(self, path: str, w: int = 200, h: int = 130):
        super().__init__()
        self.path = path
        pix = QPixmap(path)
        if pix.isNull():
            self.setText(tr("[immagine mancante]"))
        else:
            self.setPixmap(pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("{name} — clic per aprire").format(name=os.path.basename(path)))

    def mousePressEvent(self, event):  # noqa: N802
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
        super().mousePressEvent(event)


def _fit_height(view: QPlainTextEdit, text: str, max_lines: int) -> None:
    fm = QFontMetrics(view.font())
    lines = min(max(text.count("\n") + 1, 1), max_lines)
    longest = max((fm.horizontalAdvance(line) for line in text.splitlines()), default=0)
    extra = 14 if longest > 560 else 0  # spazio per la barra orizzontale
    view.setFixedHeight(lines * fm.lineSpacing() + 12 + extra)


class CodeCard(QFrame):
    """Blocco di codice proposto dall'IA, con pulsanti Esegui / Modifica / Copia."""

    def __init__(self, code: str, lang: str, on_run=None, on_edit=None):
        super().__init__()
        self.setObjectName("codeCard")
        self.code = code
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 8)
        v.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        lab = QLabel(lang or tr("codice"))
        lab.setObjectName("meta")
        head.addWidget(lab)
        runnable = on_run is not None and lang in SHELL_LANGS
        if runnable:
            info = analyze(code)
            if info.needs_root:
                b = QLabel(tr("richiede root"))
                b.setObjectName("badgeRoot")
                b.setToolTip(tr("Verrà chiesta la password di amministratore (polkit)"))
                head.addWidget(b)
            if info.dangers:
                b = QLabel(tr("⚠ attenzione"))
                b.setObjectName("badgeDanger")
                b.setToolTip("\n".join(info.dangers))
                head.addWidget(b)
        head.addStretch(1)

        copy = QToolButton()
        copy.setText(tr("Copia"))
        copy.clicked.connect(self._copy)
        head.addWidget(copy)
        self.run_btn = None
        if runnable:
            edit = QToolButton()
            edit.setText(tr("Modifica"))
            edit.setToolTip(tr("Modifica il comando prima di eseguirlo"))
            edit.clicked.connect(lambda: on_edit(self.code, self) if on_edit else None)
            head.addWidget(edit)
            self.run_btn = QPushButton(tr("▶ Esegui"))
            self.run_btn.setObjectName("primary")
            self.run_btn.clicked.connect(lambda: on_run(self.code, self))
            head.addWidget(self.run_btn)
        v.addLayout(head)

        self.view = QPlainTextEdit(code)
        self.view.setReadOnly(True)
        self.view.setFont(mono_font())
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        _fit_height(self.view, code, 14)
        v.addWidget(self.view)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.code)

    def set_running(self):
        if self.run_btn:
            self.run_btn.setEnabled(False)
            self.run_btn.setText(tr("In esecuzione…"))

    def set_result(self, rc: int | None):
        if not self.run_btn:
            return
        self.run_btn.setEnabled(True)
        if rc is None:
            self.run_btn.setText(tr("▶ Esegui"))
        else:
            self.run_btn.setText(tr("✓ Eseguito") if rc == 0 else tr("✗ Uscita {rc}").format(rc=rc))
            self.run_btn.setToolTip(tr("Clic per eseguirlo di nuovo"))


class OutputBubble(QFrame):
    """Risultato di un comando, condiviso con l'IA."""

    def __init__(self, msg: Message):
        super().__init__()
        self.setObjectName("outputBubble")
        meta = msg.meta
        cmd = meta.get("cmd", "")
        rc = meta.get("rc")
        out = meta.get("output", msg.text)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 8)
        v.setSpacing(4)
        head = QHBoxLayout()
        lines = cmd.strip().splitlines() or [tr("comando")]
        first = lines[0] + (" …" if len(lines) > 1 else "")
        if len(first) > 90:
            first = first[:87] + "…"
        lab = QLabel(f"$ {first}")
        lab.setFont(mono_font())
        lab.setToolTip(cmd)
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(lab, 1)
        shared = QLabel(tr("inviato all'IA"))
        shared.setObjectName("meta")
        head.addWidget(shared)
        status = QLabel(tr("✓ uscita 0") if rc == 0 else tr("✗ uscita {rc}").format(rc=rc))
        status.setObjectName("badgeOk" if rc == 0 else "badgeDanger")
        head.addWidget(status)
        self.toggle = QToolButton()
        head.addWidget(self.toggle)
        v.addLayout(head)

        self.body = QPlainTextEdit(out)
        self.body.setReadOnly(True)
        self.body.setFont(mono_font())
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        _fit_height(self.body, out, 12)
        v.addWidget(self.body)
        collapsed = out.count("\n") + 1 > 8
        self._set_open(not collapsed)
        self.toggle.clicked.connect(lambda: self._set_open(not self.body.isVisible()))

    def _set_open(self, on: bool):
        self.body.setVisible(on)
        self.toggle.setText(tr("Nascondi") if on else tr("Mostra output"))


def build_message_widget(msg: Message, cb: dict) -> QWidget:
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)

    if msg.role == "note" and msg.kind == "error":
        bubble = QFrame()
        bubble.setObjectName("errorBubble")
        v = QVBoxLayout(bubble)
        v.setContentsMargins(12, 8, 12, 10)
        v.addWidget(MarkdownLabel(msg.text, markdown=False))
        if cb.get("retry"):
            btn = QPushButton(tr("Riprova"))
            btn.clicked.connect(cb["retry"])
            btn.clicked.connect(lambda: btn.setEnabled(False))
            v.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        h.addWidget(bubble)
        return row

    if msg.role == "note":
        lab = MarkdownLabel(msg.text)
        lab.setObjectName("noteLabel")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(lab)
        return row

    if msg.kind == "output":
        h.addSpacing(40)
        h.addWidget(OutputBubble(msg), 1)
        return row

    if msg.role == "user":
        bubble = QFrame()
        bubble.setObjectName("userBubble")
        v = QVBoxLayout(bubble)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)
        if msg.text:
            lab = MarkdownLabel(msg.text, markdown=False)
            longest = max((lab.fontMetrics().horizontalAdvance(line) for line in msg.text.splitlines()), default=0)
            lab.setMinimumWidth(min(longest + 6, 520))
            v.addWidget(lab)
        if msg.images:
            thumbs = QHBoxLayout()
            for p in msg.images:
                thumbs.addWidget(ThumbLabel(p))
            thumbs.addStretch(1)
            v.addLayout(thumbs)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        h.addStretch(1)
        h.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        return row

    # assistente
    bubble = QFrame()
    bubble.setObjectName("assistantBubble")
    v = QVBoxLayout(bubble)
    v.setContentsMargins(14, 8, 14, 12)
    v.setSpacing(8)
    pid = msg.meta.get("provider", "")
    who = PROVIDERS.get(pid, {}).get("label", pid or "IA")
    meta = QLabel(f"{who} · {msg.meta.get('model', '')}")
    meta.setObjectName("meta")
    v.addWidget(meta)
    for seg in split_segments(msg.text):
        if seg[0] == "md":
            v.addWidget(MarkdownLabel(seg[1]))
        else:
            v.addWidget(CodeCard(seg[2], seg[1], cb.get("run"), cb.get("edit")))
    h.addWidget(bubble, 1)
    h.addSpacing(40)
    return row


class ChatView(QScrollArea):
    def __init__(self, callbacks: dict):
        super().__init__()
        self.cb = callbacks
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.container.setObjectName("chatContainer")
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setContentsMargins(16, 16, 16, 16)
        self.vbox.setSpacing(12)
        self.vbox.addStretch(1)
        self.setWidget(self.container)
        self._stick = True
        self._thinking: QLabel | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(hi) if self._stick else None)
        bar.valueChanged.connect(lambda val: setattr(self, "_stick", val >= bar.maximum() - 40))

    def _insert(self, w: QWidget):
        self.vbox.insertWidget(self.vbox.count() - 1, w)
        self._stick = True

    def add_message(self, msg: Message) -> QWidget:
        w = build_message_widget(msg, self.cb)
        self._insert(w)
        return w

    def clear(self):
        self.hide_thinking()
        while self.vbox.count() > 1:
            item = self.vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_thinking(self, text: str):
        self.hide_thinking()
        self._thinking = QLabel(text)
        self._thinking.setObjectName("noteLabel")
        self._base, self._dots = text, 0
        self._insert(self._thinking)
        self._timer.start(450)

    def _tick(self):
        if self._thinking:
            self._dots = (self._dots + 1) % 4
            self._thinking.setText(self._base + "." * self._dots)

    def hide_thinking(self):
        self._timer.stop()
        if self._thinking:
            self.vbox.removeWidget(self._thinking)
            self._thinking.deleteLater()
            self._thinking = None


class AttachmentStrip(QWidget):
    """Screenshot pronti per essere inviati con il prossimo messaggio."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(0, 0, 0, 0)
        self.h.setSpacing(8)
        self.h.addStretch(1)
        self._items: list[tuple[str, QWidget]] = []
        self.setVisible(False)

    def add(self, path: str):
        if any(p == path for p, _ in self._items):
            return
        box = QFrame()
        box.setObjectName("thumbBox")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(4, 4, 4, 4)
        bh.addWidget(ThumbLabel(path, 120, 72))
        rm = QToolButton()
        rm.setText("✕")
        rm.setToolTip(tr("Rimuovi allegato"))
        rm.clicked.connect(lambda _=False, b=box: self._remove(b))
        bh.addWidget(rm, 0, Qt.AlignmentFlag.AlignTop)
        self.h.insertWidget(self.h.count() - 1, box)
        self._items.append((path, box))
        self.setVisible(True)
        self.changed.emit()

    def _remove(self, box: QWidget):
        self._items = [(p, b) for p, b in self._items if b is not box]
        box.deleteLater()
        self.setVisible(bool(self._items))
        self.changed.emit()

    def paths(self) -> list[str]:
        return [p for p, _ in self._items]

    def clear(self):
        for _, b in self._items:
            b.deleteLater()
        self._items = []
        self.setVisible(False)
        self.changed.emit()


class PromptEdit(QTextEdit):
    """Campo di testo: Invio invia, Maiusc+Invio va a capo, Ctrl+V incolla anche immagini."""

    submitted = Signal()
    image_added = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)
        self.setPlaceholderText(tr("Descrivi il problema…  (Invio invia · Maiusc+Invio a capo · "
                                "Ctrl+V incolla uno screenshot)"))

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, source):  # noqa: N802
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):  # noqa: N802
        from .. import privacy
        if privacy.paste_filter_active() and source.hasText() and not source.hasImage():
            self.insertPlainText(privacy.filter_paste(source.text()))  # scudo privacy acceso
            return
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QPixmap):
                img = img.toImage()
            if isinstance(img, QImage) and not img.isNull():
                path = new_shot_path("paste")
                img.save(str(path), "PNG")
                self.image_added.emit(str(path))
                return
        if source.hasUrls():
            images = [u.toLocalFile() for u in source.urls()
                      if u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower() in IMAGE_EXTS]
            if images:
                for p in images:
                    self.image_added.emit(p)
                return
        self.insertPlainText(source.text())
