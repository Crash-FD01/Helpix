# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pannello che compare quando l'utente copia un comando dalla chat web.

Mostra il comando con gli avvisi di sicurezza, lo esegue con un clic e, a comando
finito, prepara l'output da incollare nella chat.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .. import theme
from ..executor import analyze
from ..icons import icon
from ..theme import C, mono_font
from .controls import IconButton
from ..i18n import tr


def format_output_for_chat(res) -> str:
    out = res.output.strip() or tr("(nessun output)")
    if len(out) > 8000:
        out = tr("[…output troncato, mostrata l'ultima parte…]\n") + out[-8000:]
    first = res.cmd.strip().splitlines()[0] if res.cmd.strip() else res.cmd
    extra = tr(" — interrotto per timeout") if res.timed_out else tr(" — interrotto") if res.cancelled else ""
    return tr("Output di `{first}` (codice di uscita {rc}{extra}):\n```\n{out}\n```").format(
        first=first, rc=res.rc, extra=extra, out=out)


class CommandBar(QFrame):
    run_requested = Signal(str)
    paste_requested = Signal(str)
    show_terminal = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sheet")
        self.setMaximumWidth(760)
        self.cmd = ""
        self.result_text = ""
        self._state = "copied"
        self._ok = True
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 12, 14)
        v.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.badge = QLabel()
        self.badge.setFixedSize(32, 32)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 11pt;")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("secondary")
        self.subtitle.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        head.addLayout(texts, 1)
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        head.addLayout(self.pills)
        self.close_btn = IconButton("x", tr("Chiudi"), size=28, icon_size=14, color_key="secondary")
        self.close_btn.clicked.connect(self.hide)
        head.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)

        self.code_row = QFrame()
        row = QHBoxLayout(self.code_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        chip = QFrame()
        chip.setObjectName("codeChip")
        ch = QHBoxLayout(chip)
        ch.setContentsMargins(12, 6, 12, 6)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(mono_font(10))
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.document().setDocumentMargin(2)
        ch.addWidget(self.view)
        row.addWidget(chip, 1)
        self.ignore_btn = QPushButton(tr("Ignora"))
        self.ignore_btn.clicked.connect(self.hide)
        row.addWidget(self.ignore_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.run_btn = QPushButton(tr("Esegui"))
        self.run_btn.setObjectName("primary")
        self.run_btn.setIconSize(QSize(12, 12))
        self.run_btn.clicked.connect(lambda: self.run_requested.emit(self.cmd))
        row.addWidget(self.run_btn, 0, Qt.AlignmentFlag.AlignBottom)
        v.addWidget(self.code_row)

        self.result_row = QFrame()
        rr = QHBoxLayout(self.result_row)
        rr.setContentsMargins(44, 0, 0, 0)
        rr.setSpacing(8)
        rr.addStretch(1)
        self.details = QPushButton(tr("Mostra output"))
        self.details.clicked.connect(self.show_terminal.emit)
        rr.addWidget(self.details)
        self.rerun_btn = QPushButton(tr("Riesegui"))
        self.rerun_btn.clicked.connect(lambda: self.run_requested.emit(self.cmd))
        rr.addWidget(self.rerun_btn)
        self.paste_btn = QPushButton(tr("Incolla nella chat"))
        self.paste_btn.setObjectName("primary")
        self.paste_btn.clicked.connect(lambda: self.paste_requested.emit(self.result_text))
        rr.addWidget(self.paste_btn)
        v.addWidget(self.result_row)

        theme.manager().changed.connect(lambda _d: self._refresh_icons())
        self.hide()

    def setVisible(self, visible: bool):  # noqa: N802 - mostra/nasconde anche il contenitore
        super().setVisible(visible)
        parent = self.parentWidget()
        if parent is not None and parent.objectName() == "commandWrap":
            parent.setVisible(visible)

    # ------------------------------------------------------------ aspetto
    def _refresh_icons(self):
        if self._state == "done":
            self.badge.setObjectName("okBadge" if self._ok else "errBadge")
            name, color = ("check", C["okText"]) if self._ok else ("x", C["errText"])
            self.badge.setPixmap(icon(name, color, 16, 2.4).pixmap(16, 16))
        else:
            self.badge.setObjectName("iconBadge")
            self.badge.setPixmap(icon("terminal", C["accentFg"], 17, 1.9).pixmap(17, 17))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.run_btn.setIcon(icon("play", "#FFFFFF", 12))

    def _set_pills(self, pills: list[tuple[str, str, str]]):
        while self.pills.count():
            w = self.pills.takeAt(0).widget()
            if w:
                w.deleteLater()
        for text, kind, tip in pills:
            p = QLabel(text)
            p.setObjectName(kind)
            p.setToolTip(tip)
            self.pills.addWidget(p, 0, Qt.AlignmentFlag.AlignTop)

    def _fit_code(self, cmd: str):
        lines = cmd.count("\n") + 1
        self.view.setPlainText(cmd)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if lines > 5
                                             else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFixedHeight(min(lines, 5) * self.view.fontMetrics().lineSpacing() + 10)

    # ------------------------------------------------------------ stati
    def show_command(self, cmd: str):
        self._state = "copied"
        self.cmd = cmd
        self.result_text = ""
        info = analyze(cmd)
        pills = []
        if info.needs_root:
            pills.append((tr("Chiede la password"), "pillWarn", tr("Serve la password di amministratore (polkit)")))
        if info.dangers:
            pills.append((tr("Attenzione"), "pillErr", "\n".join(info.dangers)))
        if info.interactive:
            pills.append((tr("Interattivo"), "pillWarn", info.interactive))
        self._set_pills(pills)
        self.title.setText(tr("Hai copiato un comando"))
        self.subtitle.setText(tr("Vuoi eseguirlo su questo PC? L'output verrà incollato nella chat."))
        self._fit_code(cmd)
        self.run_btn.setText(tr("Esegui"))
        self.run_btn.setEnabled(True)
        self.code_row.show()
        self.result_row.hide()
        self.close_btn.hide()
        self._refresh_icons()
        self.show()

    def set_running(self):
        self.run_btn.setEnabled(False)
        self.run_btn.setText(tr("In esecuzione…"))
        self.subtitle.setText(tr("Comando in esecuzione…"))

    def set_result(self, res, auto_pasted: bool, external: bool = False):
        self._state = "done"
        self._ok = res.rc == 0
        self.cmd = res.cmd
        self.result_text = format_output_for_chat(res)
        lines = res.output.strip().count("\n") + 1 if res.output.strip() else 0
        self.title.setText(tr("Comando eseguito") if self._ok else tr("Il comando è terminato con codice {rc}").format(rc=res.rc))
        first = res.cmd.strip().splitlines()[0] if res.cmd.strip() else res.cmd
        if external:
            where = tr("Output copiato: nella chat del browser premi Ctrl+V.")
        elif auto_pasted:
            where = tr("Output incollato nella chat: premi Invio per inviarlo.")
        else:
            where = tr("L'output è pronto da incollare nella chat.")
        count = tr("1 riga") if lines == 1 else tr("{n} righe").format(n=lines)
        self.subtitle.setText(f"{where}   ·   {first[:60]}   ·   {count}")
        self._set_pills([])
        self.code_row.hide()
        self.result_row.show()
        self.paste_btn.setVisible(not auto_pasted)
        self.paste_btn.setText(tr("Copia di nuovo") if external else tr("Incolla nella chat"))
        self.close_btn.show()
        self._refresh_icons()
        self.show()
