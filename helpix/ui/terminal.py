# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pannello terminale: output in tempo reale, cronologia, completamento dei percorsi, navigazione.

Il testo è conservato come segmenti con un *ruolo* (output, prompt, avviso...), non con un
colore fisso: così al cambio di tema tutto il contenuto viene ricolorato correttamente.
"""
from __future__ import annotations

import getpass
import glob
import os
import re
import socket
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from .. import theme
from ..theme import C, mono_font
from .controls import IconButton
from ..i18n import tr

ROLE_COLORS = {"out": "termText", "prompt": "prompt", "cmd": "termText", "muted": "secondary",
               "warn": "warnText", "err": "errText"}
MAX_SEGMENTS = 4000


def _user_host() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "utente"
    return f"{user}@{socket.gethostname().split('.')[0]}"


def pretty_path(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


class HistoryLineEdit(QLineEdit):
    completions = Signal(list)

    def __init__(self, cwd_provider):
        super().__init__()
        self.history: list[str] = []
        self.idx = 0
        self.cwd_provider = cwd_provider

    def push(self, cmd: str):
        if cmd and (not self.history or self.history[-1] != cmd):
            self.history.append(cmd)
        self.idx = len(self.history)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Up and self.history:
            self.idx = max(0, self.idx - 1)
            self.setText(self.history[self.idx])
            return
        if e.key() == Qt.Key.Key_Down and self.history:
            self.idx = min(len(self.history), self.idx + 1)
            self.setText(self.history[self.idx] if self.idx < len(self.history) else "")
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Tab:
            self._complete()
            return True
        return super().event(e)

    def _complete(self):
        before = self.text()[:self.cursorPosition()]
        token = re.split(r"\s", before)[-1]
        expanded = os.path.expanduser(token)
        pattern = expanded if os.path.isabs(expanded) else os.path.join(self.cwd_provider(), expanded)
        matches = sorted(glob.glob(glob.escape(pattern) + "*"))
        if not matches:
            return
        common = os.path.commonprefix(matches)
        if len(matches) == 1 and os.path.isdir(common):
            common += "/"
        addition = common[len(pattern):]
        if addition:
            self.insert(addition)
        elif len(matches) > 1:
            self.completions.emit([os.path.basename(m) + ("/" if os.path.isdir(m) else "") for m in matches[:60]])


class TerminalPanel(QWidget):
    command_entered = Signal(str)
    stop_requested = Signal()
    browse_requested = Signal()
    cd_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("terminalPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cwd = str(Path.home())
        self.user_host = _user_host()
        self._segments: list[tuple[str, str]] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("terminalBar")
        bar.setFixedHeight(40)
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(14, 0, 8, 0)
        bh.setSpacing(4)
        title = QLabel(tr("Terminale"))
        title.setStyleSheet("font-weight: 600;")
        bh.addWidget(title)
        bh.addSpacing(8)
        self.cwd_label = QLabel()
        self.cwd_label.setObjectName("cwdLabel")
        self.cwd_label.setFont(mono_font(9))
        bh.addWidget(self.cwd_label, 1)
        for name, tip, slot in (("arrow-up", tr("Cartella superiore"),
                                 lambda: self.cd_requested.emit(os.path.dirname(self.cwd) or "/")),
                                ("home", tr("Cartella personale"), lambda: self.cd_requested.emit(str(Path.home()))),
                                ("folder", tr("Scegli una cartella…"), self.browse_requested.emit)):
            b = IconButton(name, tip, size=28, icon_size=16, color_key="secondary")
            b.clicked.connect(slot)
            bh.addWidget(b)
        self.stop_btn = IconButton("stop", tr("Interrompi il comando"), size=28, icon_size=14, color_key="errText")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.setEnabled(False)
        bh.addWidget(self.stop_btn)
        clear = IconButton("trash", tr("Pulisci il terminale"), size=28, icon_size=16, color_key="secondary")
        clear.clicked.connect(self.clear)
        bh.addWidget(clear)
        v.addWidget(bar)

        self.out = QPlainTextEdit()
        self.out.setObjectName("terminalOut")
        self.out.setReadOnly(True)
        self.out.setFont(mono_font(10))
        self.out.setMaximumBlockCount(5000)
        self.out.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.out.document().setDocumentMargin(12)
        v.addWidget(self.out, 1)

        row = QFrame()
        row.setObjectName("terminalInputRow")
        row.setFixedHeight(40)
        rh = QHBoxLayout(row)
        rh.setContentsMargins(14, 0, 10, 0)
        rh.setSpacing(6)
        self.prompt_label = QLabel()
        self.prompt_label.setObjectName("promptLabel")
        self.prompt_label.setFont(mono_font(10))
        rh.addWidget(self.prompt_label)
        self.input = HistoryLineEdit(lambda: self.cwd)
        self.input.setObjectName("terminalInput")
        self.input.setFont(mono_font(10))
        self.input.setPlaceholderText(tr("scrivi un comando e premi Invio · Tab completa i percorsi · ↑↓ cronologia"))
        self.input.returnPressed.connect(self._submit)
        self.input.completions.connect(lambda items: self.append("  ".join(items) + "\n", "muted"))
        rh.addWidget(self.input, 1)
        self.share_cb = QCheckBox(tr("Condividi l'output"))
        self.share_cb.setChecked(True)
        self.share_cb.setToolTip(tr("Prepara l'output dei comandi che scrivi qui per incollarlo nella chat"))
        rh.addWidget(self.share_cb)
        v.addWidget(row)

        theme.manager().changed.connect(lambda _d: self._rerender())

    def _submit(self):
        cmd = self.input.text().strip()
        if not cmd:
            return
        self.input.push(cmd)
        self.input.clear()
        self.command_entered.emit(cmd)

    def prompt_text(self) -> str:
        return f"{self.user_host}:{pretty_path(self.cwd)}$"

    def set_cwd(self, path: str):
        self.cwd = path
        self.cwd_label.setText(pretty_path(path))
        self.cwd_label.setToolTip(path)
        self.prompt_label.setText(self.prompt_text())

    def _insert(self, text: str, role: str):
        cur = self.out.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(C[ROLE_COLORS.get(role, "termText")]))
        cur.insertText(text, fmt)
        self.out.setTextCursor(cur)

    def append(self, text: str, role: str = "out"):
        self._segments.append((text, role))
        if len(self._segments) > MAX_SEGMENTS:
            del self._segments[:len(self._segments) - MAX_SEGMENTS]
        self._insert(text, role)
        self.out.ensureCursorVisible()

    def _rerender(self):
        self.out.clear()
        for text, role in self._segments:
            self._insert(text, role)
        self.out.ensureCursorVisible()

    def clear(self):
        self._segments.clear()
        self.out.clear()

    def set_running(self, running: bool):
        self.stop_btn.setEnabled(running)
        self.input.setEnabled(not running)
        if not running:
            self.input.setFocus()
