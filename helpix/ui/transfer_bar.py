# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra discreta che compare quando si passa a un'altra IA con un task in corso.

Non blocca nulla: l'utente può fare l'accesso al nuovo servizio con calma e, quando è
pronto, portare lì il task con un clic.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import site_icons, theme
from ..i18n import tr
from ..icons import icon
from ..theme import C
from .controls import IconButton


class TransferBar(QFrame):
    transfer = Signal()
    back = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sheet")
        self.setMaximumWidth(760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 10, 12)
        outer.setSpacing(10)
        h = QHBoxLayout()
        h.setSpacing(12)
        outer.addLayout(h)
        self.icons = QLabel()
        self.icons.setFixedSize(56, 28)
        h.addWidget(self.icons)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("secondary")
        self.subtitle.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        h.addLayout(texts, 1)
        close = IconButton("x", tr("Chiudi"), size=28, icon_size=14, color_key="secondary")
        close.clicked.connect(self.hide)
        h.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 4, 0)
        buttons.addStretch(1)
        self.back_btn = QPushButton()
        self.back_btn.clicked.connect(self.back.emit)
        buttons.addWidget(self.back_btn)
        self.go_btn = QPushButton(tr("Porta il task qui"))
        self.go_btn.setObjectName("primary")
        self.go_btn.clicked.connect(self.transfer.emit)
        buttons.addWidget(self.go_btn)
        outer.addLayout(buttons)
        self._src = self._dst = ""
        theme.manager().changed.connect(lambda _d: self._draw_icons())
        site_icons.notifier.changed.connect(lambda _k: self._draw_icons())
        self.hide()

    def setVisible(self, visible: bool):  # noqa: N802 - mostra/nasconde anche il contenitore
        super().setVisible(visible)
        parent = self.parentWidget()
        if parent is not None and parent.objectName() == "transferWrap":
            parent.setVisible(visible)

    def _draw_icons(self):
        if not self._src:
            return
        from PySide6.QtGui import QPainter, QPixmap
        pix = QPixmap(56 * 3, 28 * 3)
        pix.fill(Qt.GlobalColor.transparent)
        pix.setDevicePixelRatio(3)
        p = QPainter(pix)
        p.drawPixmap(0, 4, site_icons.pixmap(self._src, 20))
        p.drawPixmap(20, 6, icon("arrow-right-small", C["secondary"], 16, 2).pixmap(16, 16))
        p.drawPixmap(36, 4, site_icons.pixmap(self._dst, 20))
        p.end()
        self.icons.setPixmap(pix)

    def show_notice(self, site: str, title: str, subtitle: str, primary: str, secondary: str | None = None):
        """Riusa la barra per un avviso con un'azione (es. accesso Google bloccato)."""
        self._src = self._dst = ""
        self.icons.setFixedSize(28, 28)
        self.icons.setPixmap(site_icons.pixmap(site, 28))
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.go_btn.setText(primary)
        self.back_btn.setVisible(bool(secondary))
        if secondary:
            self.back_btn.setText(secondary)
        self.show()

    def show_for(self, src: str, src_label: str, dst: str, dst_label: str):
        self._src, self._dst = src, dst
        self.icons.setFixedSize(56, 28)
        self.title.setText(tr("Hai un task in corso su {src}").format(src=src_label))
        self.subtitle.setText(tr("Quando hai fatto l'accesso a {dst}, portalo qui: screenshot, comandi, risultati "
                                 "e riepilogo.").format(dst=dst_label))
        self.back_btn.setText(tr("Torna a {src}").format(src=src_label))
        self.back_btn.show()
        self.go_btn.setText(tr("Porta il task qui"))
        self._draw_icons()
        self.show()
