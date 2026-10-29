# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra di avvio: scelta dell'assistente con il proprio account (selezione agente +
login + predefinito, come nello schizzo originale), aspetto chiaro/scuro e accesso
all'uso avanzato con chiave API.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import site_icons, theme
from ..icons import icon
from ..theme import C
from .controls import Segmented, Switch
from .setup_dialog import SetupDialog
from .web_panel import WEB_SITES, WEBENGINE
from ..i18n import LANGUAGES, current as current_language, tr


class ServiceRow(QPushButton):
    def __init__(self, sid: str, site: dict):
        super().__init__()
        self.sid = sid
        self.setObjectName("serviceRow")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)
        self.setAccessibleName(f"{site['label']}, {tr(site['note'])}")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        self.avatar = QLabel()
        self.avatar.setFixedSize(32, 32)
        h.addWidget(self.avatar)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(site["label"])
        name.setStyleSheet("font-weight: 600;")
        note = QLabel(site["note"])
        note.setObjectName("secondary")
        texts.addWidget(name)
        texts.addWidget(note)
        h.addLayout(texts, 1)
        self.radio = QLabel()
        self.radio.setFixedSize(20, 20)
        h.addWidget(self.radio)
        self.letter = site["label"][0]
        for w in (self.avatar, name, note, self.radio):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(lambda _on: self.refresh())
        theme.manager().changed.connect(lambda _d: self.refresh())
        site_icons.notifier.changed.connect(lambda key: self.refresh() if key == self.sid else None)
        self.refresh()

    def refresh(self):
        self.setProperty("selected", "true" if self.isChecked() else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.avatar.setPixmap(site_icons.pixmap(self.sid, 32))
        if self.isChecked():
            self.radio.setStyleSheet(f"background: {C['accentBg']}; border-radius: 10px;")
            self.radio.setPixmap(icon("check", "#FFFFFF", 12, 3.2).pixmap(12, 12))
            self.radio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.radio.setStyleSheet(f"border: 1.5px solid {C['border']}; border-radius: 10px;")
            self.radio.clear()


class StartDialog(QDialog):
    RESTART = 2  # codice di uscita: la lingua è cambiata, riaprire l'app

    def __init__(self, settings, secrets, parent=None):
        super().__init__(parent)
        self.settings, self.secrets = settings, secrets
        self.engine = None
        self.site = None
        self.provider = self.model = None
        self.setWindowTitle(tr("Benvenuto in Helpix"))
        self.setFixedWidth(560)

        v = QVBoxLayout(self)
        v.setContentsMargins(32, 30, 32, 22)
        v.setSpacing(20)

        head = QVBoxLayout()
        head.setSpacing(8)
        logo = QLabel()
        logo.setFixedSize(76, 76)
        logo.setPixmap(theme.logo_pixmap(76))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel(tr("Benvenuto in Helpix"))
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(title)
        sub = QLabel(tr("Scegli l'assistente con cui risolvere il problema. Usi il tuo account di sempre, "
                     "anche gratuito."))
        sub.setObjectName("secondary")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(sub)
        v.addLayout(head)

        group = QFrame()
        group.setObjectName("group")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(1, 1, 1, 1)
        gl.setSpacing(0)
        self.rows: list[ServiceRow] = []
        current = settings.start_site()
        for i, (sid, site) in enumerate(WEB_SITES.items()):
            if i:
                sep = QFrame()
                sep.setObjectName("rowSep")
                sep.setFixedHeight(1)
                gl.addWidget(sep)
            row = ServiceRow(sid, site)
            row.setChecked(sid == current)
            row.clicked.connect(lambda _=False, r=row: self._pick(r))
            row.setEnabled(WEBENGINE)
            gl.addWidget(row)
            self.rows.append(row)
        v.addWidget(group)

        opts = QVBoxLayout()
        opts.setSpacing(12)
        line = QHBoxLayout()
        line.addWidget(QLabel(tr("Aspetto")), 1)
        self.seg = Segmented([("auto", tr("Automatico")), ("light", tr("Chiaro")), ("dark", tr("Scuro"))],
                             settings.get("theme", "auto"))
        self.seg.changed.connect(self._theme)
        line.addWidget(self.seg)
        opts.addLayout(line)
        line = QHBoxLayout()
        line.addWidget(QLabel(tr("Lingua")), 1)
        self.lang = Segmented(list(LANGUAGES.items()), current_language())
        self.lang.changed.connect(self._language)
        line.addWidget(self.lang)
        opts.addLayout(line)
        line = QHBoxLayout()
        lab = QLabel(tr("Usa sempre questa scelta e non mostrare più questa schermata"))
        lab.setWordWrap(True)
        line.addWidget(lab, 1)
        self.remember = Switch(bool(settings.get("skip_setup", False)), lab.text())
        line.addWidget(self.remember)
        opts.addLayout(line)
        again = QLabel(tr("La ritrovi quando vuoi in Impostazioni › Schermata iniziale."))
        again.setObjectName("secondary")
        opts.addWidget(again)
        info = QLabel(tr("La prima volta accedi nella pagina del servizio: l'accesso resta salvato su questo PC. "
                         "Google non permette l'accesso dai browser integrati nelle app: per ChatGPT e Claude "
                         "accedi con email e password; Gemini si apre nel tuo browser."))
        info.setObjectName("secondary")
        info.setWordWrap(True)
        opts.addWidget(info)
        if not WEBENGINE:
            warn = QLabel(tr("Il componente browser (PySide6-WebEngine) non è installato: puoi usare solo una chiave API."))
            warn.setObjectName("pillWarn")
            warn.setWordWrap(True)
            opts.addWidget(warn)
        v.addLayout(opts)

        sep = QFrame()
        sep.setObjectName("rowSep")
        sep.setFixedHeight(1)
        v.addWidget(sep)
        foot = QHBoxLayout()
        adv = QPushButton(tr("Uso avanzato con chiave API…"))
        adv.setObjectName("plain")
        adv.setCursor(Qt.CursorShape.PointingHandCursor)
        adv.clicked.connect(self._advanced)
        foot.addWidget(adv)
        foot.addStretch(1)
        quit_btn = QPushButton(tr("Esci"))
        quit_btn.clicked.connect(self.reject)
        foot.addWidget(quit_btn)
        self.ok = QPushButton()
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._accept_web)
        foot.addWidget(self.ok)
        v.addLayout(foot)
        self._update_ok()
        site_icons.refresh_in_background(self)

    def _selected(self) -> ServiceRow | None:
        return next((r for r in self.rows if r.isChecked()), None)

    def _pick(self, row: ServiceRow):
        for r in self.rows:
            r.setChecked(r is row)
        self._update_ok()

    def _language(self, code: str):
        if code == current_language():
            return
        self.settings.data["language"] = code
        self.settings.data["web_site"] = self._selected().sid if self._selected() else self.settings.get("web_site")
        self.settings.save()
        self.done(self.RESTART)

    def _theme(self, mode: str):
        theme.set_mode(mode)
        self.settings.set("theme", mode)

    def _update_ok(self):
        row = self._selected()
        self.ok.setEnabled(WEBENGINE and row is not None)
        self.ok.setText(tr("Continua con {name}").format(name=WEB_SITES[row.sid]["label"]) if row else tr("Continua"))

    def keyPressEvent(self, e):  # noqa: N802 - frecce su/giù per scegliere il servizio
        if e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.rows:
            row = self._selected()
            i = self.rows.index(row) if row else -1
            i = (i + (1 if e.key() == Qt.Key.Key_Down else -1)) % len(self.rows)
            self._pick(self.rows[i])
            self.rows[i].setFocus()
            return
        super().keyPressEvent(e)

    def _accept_web(self):
        row = self._selected()
        if not (WEBENGINE and row):
            return
        self.engine, self.site = "web", row.sid
        self.settings.data.update(engine="web", web_site=self.site, skip_setup=self.remember.isChecked())
        if self.remember.isChecked():
            self.settings.data.update(default_engine="web", default_site=self.site)
        self.settings.save()
        self.accept()

    def _advanced(self):
        dlg = SetupDialog(self.settings, self.secrets, self, first_run=True)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.provider:
            self.engine, self.provider, self.model = "api", dlg.provider, dlg.model
            self.settings.data["engine"] = "api"
            self.settings.data["skip_setup"] = self.remember.isChecked()
            self.settings.save()
            self.accept()

