# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pagina mostrata al posto della chat quando un servizio è aperto nel browser di sistema.

Serve quando il sito non permette l'accesso da un browser integrato (Google blocca il login
nelle app per sicurezza). Helpix lavora affiancato al browser tramite gli appunti:
- screenshot e testi vengono copiati, pronti per Ctrl+V nella chat;
- i comandi copiati nel browser vengono riconosciuti quando si torna su Helpix.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import site_icons, theme
from ..i18n import tr
from ..icons import icon
from ..theme import C


class _QueueRow(QFrame):
    def __init__(self, title: str, detail: str, copy_fn):
        super().__init__()
        self.copy_fn = copy_fn
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(10)
        self.mark = QLabel()
        self.mark.setFixedSize(18, 18)
        h.addWidget(self.mark)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        d = QLabel(detail)
        d.setObjectName("secondary")
        texts.addWidget(t)
        texts.addWidget(d)
        h.addLayout(texts, 1)
        self.btn = QPushButton(tr("Copia"))
        self.btn.clicked.connect(self.copy)
        h.addWidget(self.btn)
        self.set_done(False)

    def copy(self):
        self.copy_fn()
        self.set_done(True)

    def set_done(self, done: bool):
        self.done = done
        self.mark.setPixmap(icon("check" if done else "clipboard", C["okText"] if done else C["secondary"], 16, 2)
                            .pixmap(16, 16))
        self.btn.setText(tr("Copia di nuovo") if done else tr("Copia"))


class ExternalPage(QWidget):
    use_integrated = Signal()
    keep_on_top = Signal()
    connect_browser = Signal()

    def __init__(self, site: str, label: str, url: str, copy_text, copy_image, opener=None):
        super().__init__()
        self.site, self.label, self.url = site, label, url
        self.opener = opener
        self.copy_text, self.copy_image = copy_text, copy_image
        self.setObjectName("chatContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("chatContainer")
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 24, 0, 24)
        col.addStretch(1)

        card = QFrame()
        card.setObjectName("group")
        card.setMaximumWidth(680)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 26, 28, 24)
        cl.setSpacing(14)
        self.logo = QLabel()
        self.logo.setFixedSize(48, 48)
        cl.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel(tr("{name} è aperto nel tuo browser").format(name=label))
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setObjectName("secondary")
        self.intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.intro)
        self.rows = []
        for icon_name in ("camera", "terminal", "clipboard"):
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel()
            ic.setPixmap(icon(icon_name, C["accentFg"], 18).pixmap(18, 18))
            ic.setFixedSize(20, 20)
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel()
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            cl.addLayout(row)
            self.rows.append(lab)
        self.link_box = QFrame()
        self.link_box.setObjectName("notice")
        lb = QHBoxLayout(self.link_box)
        lb.setContentsMargins(12, 10, 12, 10)
        lb.setSpacing(10)
        link_ic = QLabel()
        link_ic.setPixmap(icon("link", C["accentFg"], 18).pixmap(18, 18))
        lb.addWidget(link_ic, 0, Qt.AlignmentFlag.AlignTop)
        link_text = QLabel(tr("Con l'estensione di Helpix per il browser non serve copiare: comandi, screenshot e "
                              "output passano direttamente dalla chat del browser."))
        link_text.setWordWrap(True)
        lb.addWidget(link_text, 1)
        link_btn = QPushButton(tr("Collega il browser…"))
        link_btn.clicked.connect(self.connect_browser.emit)
        lb.addWidget(link_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        cl.addWidget(self.link_box)

        self.queue_box = QFrame()
        qb = QVBoxLayout(self.queue_box)
        qb.setContentsMargins(0, 8, 0, 0)
        qb.setSpacing(2)
        qtitle = QLabel(tr("Da incollare nella chat"))
        qtitle.setObjectName("secondary")
        qb.addWidget(qtitle)
        self.queue_rows = QVBoxLayout()
        qb.addLayout(self.queue_rows)
        self.queue_box.hide()
        cl.addWidget(self.queue_box)

        buttons = QHBoxLayout()
        integrated = QPushButton(tr("Usa il browser integrato"))
        integrated.setToolTip(tr("Per i servizi a cui accedi con email e password"))
        integrated.clicked.connect(self.use_integrated.emit)
        buttons.addWidget(integrated)
        on_top = QPushButton(tr("In primo piano"))
        on_top.setToolTip(tr("Tieni Helpix in primo piano"))
        on_top.clicked.connect(self.keep_on_top.emit)
        buttons.addWidget(on_top)
        buttons.addStretch(1)
        open_btn = QPushButton(tr("Apri {name} nel browser").format(name=label))
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self.open_browser)
        buttons.addWidget(open_btn)
        cl.addLayout(buttons)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card, 10)
        wrap.addStretch(1)
        col.addLayout(wrap)
        col.addStretch(2)
        theme.manager().changed.connect(lambda _d: self._logo())
        site_icons.notifier.changed.connect(lambda key: self._logo() if key == site else None)
        self._logo()
        self.set_bridge(False, [])

    def set_bridge(self, connected: bool, browsers: list[str]):
        """Testi diversi se l'estensione del browser è collegata (niente appunti da usare)."""
        self.connected = connected
        label = self.label
        if connected:
            self.intro.setText(tr("Helpix è collegato a {browsers}: lavora direttamente nella chat di {name}.").format(
                browsers=", ".join(browsers), name=label))
            texts = (tr("Screenshot: lo fai da qui o dal pulsante a lato della chat, viene incollato nella casella."),
                     tr("Comandi: premi «Esegui con Helpix» sotto il blocco di codice nella chat."),
                     tr("Output e diagnosi: incollati direttamente nella casella della chat, tu premi Invio."))
        else:
            self.intro.setText(tr("Usa {name} nel tuo browser (Chrome, Firefox…), dove l'accesso con Google funziona. "
                                  "Helpix lavora affiancato tramite gli appunti:").format(name=label))
            texts = (tr("Screenshot: viene copiato, nella chat premi Ctrl+V."),
                     tr("Comandi: copiali nel browser e torna su Helpix, compare il pulsante Esegui."),
                     tr("Output e diagnosi: vengono copiati, nella chat premi Ctrl+V."))
        for lab, text in zip(self.rows, texts):
            lab.setText(text)
        self.link_box.setVisible(False)  # estensione del browser: messa da parte per ora

    def _logo(self):
        self.logo.setPixmap(site_icons.pixmap(self.site, 48))

    def open_browser(self):
        if self.opener:
            self.opener(self.site, self.url)
        else:
            QDesktopServices.openUrl(QUrl(self.url))

    def set_queue(self, text: str, images: list[str]):
        """Elementi del task da incollare uno alla volta (gli appunti ne contengono uno solo)."""
        while self.queue_rows.count():
            w = self.queue_rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        rows = [_QueueRow(tr("Testo del task"), tr("{n} caratteri").format(n=len(text)),
                          lambda: self.copy_text(text))]
        for i, path in enumerate(images, 1):
            rows.append(_QueueRow(tr("Screenshot {i}").format(i=i), Path(path).name,
                                  lambda p=path: self.copy_image(QImage(p))))
        for r in rows:
            self.queue_rows.addWidget(r)
        self.queue_box.show()
        rows[0].copy()

