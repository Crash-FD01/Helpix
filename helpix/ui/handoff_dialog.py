# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra "Continua il task con un'altra IA".

Non è modale: mentre è aperta l'utente può inviare nella chat la richiesta di riepilogo e
copiarne la risposta. Quando Helpix riceve il riepilogo (dagli appunti o dall'API) la
finestra si aggiorna da sola.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout)

from .. import site_icons
from ..i18n import tr
from ..icons import icon
from ..agents import AGENTS
from ..task import build_handoff, command_outputs, extract_goal, latest, screenshots
from ..theme import C, mono_font
from .web_panel import WEB_SITES


class HandoffDialog(QDialog):
    go = Signal(str, str, list)  # sito di destinazione, testo, immagini
    ask_summary = Signal()       # chiedi il riepilogo all'IA attuale
    export = Signal()            # salva il task su file

    def __init__(self, session, source_label: str, target: str, can_ask: bool, parent=None,
                 resume: bool = False):
        super().__init__(parent)
        self.session = session
        self.source = source_label
        self._edited = False
        self.setModal(False)
        self.setWindowTitle(tr("Continua il task con un'altra IA"))
        self.setMinimumWidth(620)
        self.resize(660, 720)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(14)
        title = QLabel(tr("Riprendi il task") if resume else tr("Continua il task con un'altra IA"))
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel(tr("Helpix incolla nella nuova chat il riepilogo, i comandi già eseguiti con i risultati e gli "
                        "ultimi screenshot. Tu controlli e premi Invio."))
        sub.setObjectName("secondary")
        sub.setWordWrap(True)
        v.addWidget(sub)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Nuova IA")), 1)
        self.target = QComboBox()
        for sid, site in WEB_SITES.items():
            self.target.addItem(site_icons.icon(sid, 18), site["label"], sid)
        from .web_panel import WEBENGINE
        if WEBENGINE:  # gli agenti nel terminale usano lo stesso componente
            self.target.insertSeparator(self.target.count())
            for key, a in AGENTS.items():
                self.target.addItem(site_icons.icon(a["icon"], 18), tr("{name} (terminale)").format(name=a["label"]), key)
        self.target.setCurrentIndex(max(self.target.findData(target), 0))
        self.target.currentIndexChanged.connect(self._update_button)
        row.addWidget(self.target)
        v.addLayout(row)

        # --- passo 1: riepilogo dall'IA attuale
        card = QFrame()
        card.setObjectName("group")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(6)
        head = QHBoxLayout()
        self.sum_icon = QLabel()
        self.sum_icon.setFixedSize(20, 20)
        head.addWidget(self.sum_icon)
        self.sum_title = QLabel()
        self.sum_title.setStyleSheet("font-weight: 600;")
        head.addWidget(self.sum_title, 1)
        self.ask_btn = QPushButton(tr("Chiedi il riepilogo a {source}").format(source=source_label))
        self.ask_btn.setVisible(can_ask)
        self.ask_btn.clicked.connect(self._ask)
        head.addWidget(self.ask_btn)
        cl.addLayout(head)
        self.sum_hint = QLabel()
        self.sum_hint.setObjectName("secondary")
        self.sum_hint.setWordWrap(True)
        cl.addWidget(self.sum_hint)
        v.addWidget(card)

        # --- problema e contenuto
        v.addWidget(QLabel(tr("Obiettivo")))
        self.problem = QLineEdit()
        self.problem.setPlaceholderText(tr("In una frase: es. sistemare il Wi-Fi, scrivere uno script di backup"))
        summary = latest(session, "summary")
        problem = extract_goal(summary.text) if summary else ""
        if not problem and session.title not in ("Nuova sessione", "New session"):
            problem = session.title
        self.problem.setText(problem)
        self.problem.textChanged.connect(self._regen)
        v.addWidget(self.problem)

        n_cmd, n_img = len(command_outputs(session)), len(screenshots(session))
        self.cb_cmd = QCheckBox(tr("Comandi eseguiti e risultati ({n})").format(n=n_cmd))
        self.cb_img = QCheckBox(tr("Ultimi screenshot ({n})").format(n=n_img))
        for cb, n in ((self.cb_cmd, n_cmd), (self.cb_img, n_img)):
            cb.setChecked(n > 0)
            cb.setVisible(n > 0)  # niente caselle vuote «(0)»
            cb.toggled.connect(self._regen)
            v.addWidget(cb)

        prev_row = QHBoxLayout()
        lab = QLabel(tr("Anteprima del testo da incollare"))
        lab.setObjectName("secondary")
        prev_row.addWidget(lab, 1)
        self.reset_btn = QToolButton()
        self.reset_btn.setText(tr("Rigenera"))
        self.reset_btn.setToolTip(tr("Annulla le modifiche manuali e rigenera il testo"))
        self.reset_btn.clicked.connect(lambda: self._regen(force=True))
        prev_row.addWidget(self.reset_btn)
        v.addLayout(prev_row)
        self.privacy_note = QLabel(tr("Scudo privacy acceso: i dati sensibili qui sotto sono già oscurati."))
        self.privacy_note.setObjectName("secondary")
        self.privacy_note.setWordWrap(True)
        self.privacy_note.hide()
        v.addWidget(self.privacy_note)
        self.preview = QPlainTextEdit()
        self.preview.setFont(mono_font(9))
        self.preview.textChanged.connect(self._mark_edited)
        v.addWidget(self.preview, 1)

        foot = QHBoxLayout()
        exp = QPushButton(tr("Esporta su file…"))
        exp.setToolTip(tr("Salva il task in un file .helpix, ad esempio per passarlo a un collega"))
        exp.clicked.connect(self.export.emit)
        foot.addWidget(exp)
        foot.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.go_btn = QPushButton()
        self.go_btn.setObjectName("primary")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._go)
        foot.addWidget(self.go_btn)
        v.addLayout(foot)

        self._images: list[str] = []
        self._update_summary_state()
        self._update_button()
        self._regen(force=True)
        self._can_ask = can_ask
        self._emphasis()

    # ------------------------------------------------------------ stato
    def _update_summary_state(self, waiting: bool = False):
        self.ask_btn.setEnabled(not waiting)  # niente doppie richieste mentre l'IA risponde
        summary = latest(self.session, "summary")
        if summary:
            lines = summary.text.count("\n") + 1
            self.sum_icon.setPixmap(icon("check", C["okText"], 18, 2.4).pixmap(18, 18))
            self.sum_title.setText(tr("Riepilogo ricevuto da {who}").format(who=summary.meta.get("source", self.source)))
            self.sum_hint.setText(tr("{n} righe: sarà incluso nel pacchetto. Puoi chiederne uno nuovo se il task è "
                                     "andato avanti.").format(n=lines))
            self.ask_btn.setText(tr("Chiedi un nuovo riepilogo"))
        elif waiting:
            self.sum_icon.setPixmap(icon("timer", C["accentFg"], 18).pixmap(18, 18))
            self.sum_title.setText(tr("In attesa del riepilogo…"))
            self.sum_hint.setText(tr("Ho inviato la richiesta a {source}: appena finisce di scrivere, Helpix legge il "
                                     "riepilogo e lo mette qui.").format(source=self.source))
        else:
            self.sum_icon.setPixmap(icon("info", C["secondary"], 18).pixmap(18, 18))
            self.sum_title.setText(tr("Prima chiedi il riepilogo a {source}").format(source=self.source))
            self.sum_hint.setText(tr("Helpix chiede a {source} di riassumere la conversazione, invia la richiesta e "
                                     "inserisce qui il riepilogo appena arriva.").format(source=self.source))

    def _emphasis(self):
        """Senza riepilogo il passo importante è chiederlo: il pulsante principale è quello."""
        has_summary = latest(self.session, "summary") is not None
        ask_first = getattr(self, "_can_ask", False) and not has_summary
        self.ask_btn.setObjectName("primary" if ask_first else "")
        self.go_btn.setObjectName("" if ask_first else "primary")
        self.go_btn.setDefault(not ask_first)
        for b in (self.ask_btn, self.go_btn):
            b.style().unpolish(b)
            b.style().polish(b)

    def _update_button(self, *_):
        key = self.target.currentData()
        if key in AGENTS:
            self.go_btn.setText(tr("Avvia {name} con il task").format(name=AGENTS[key]["label"]))
        else:
            self.go_btn.setText(tr("Apri {name} e incolla").format(name=self.target.currentText()))

    def _mark_edited(self):
        if not getattr(self, "_regenerating", False):
            self._edited = True

    def _regen(self, *_, force: bool = False):
        if self._edited and not force:
            return
        text, self._images = build_handoff(
            self.session, self.problem.text(), self.source,
            include_commands=self.cb_cmd.isChecked(), include_screens=self.cb_img.isChecked())
        from .. import privacy
        text = privacy.filter_paste(text, notify=False)  # scudo acceso: anche l'anteprima e «Copia» sono oscurati
        if getattr(self, "privacy_note", None) is not None:
            self.privacy_note.setVisible(privacy.paste_filter_active())
        self._regenerating = True
        self.preview.setPlainText(text)
        self._regenerating = False
        self._edited = False

    # ------------------------------------------------------------ azioni
    def _ask(self):
        self._update_summary_state(waiting=True)
        self.ask_summary.emit()

    def summary_received(self):
        self._update_summary_state()
        self._emphasis()
        summary = latest(self.session, "summary")
        if summary and not self.problem.text().strip():
            self.problem.setText(extract_goal(summary.text))
        self._regen(force=True)
        self.raise_()
        self.activateWindow()

    def summary_waiting_external(self, source: str):
        self.sum_hint.setText(tr("Ho copiato la richiesta: incollala nella chat di {source} nel browser (Ctrl+V) e "
                                 "inviala, poi copia la risposta con il pulsante Copia e torna su Helpix: la "
                                 "riconosce da solo.").format(source=source))

    def summary_failed(self, message: str):
        self._update_summary_state()
        self.sum_hint.setText(message)

    def _go(self):
        if self.problem.text().strip() and self.session.title in ("Nuova sessione", "New session"):
            self.session.title = self.problem.text().strip()[:58]
        images = self._images if self.cb_img.isChecked() else []
        self.go.emit(self.target.currentData(), self.preview.toPlainText().strip(), images)
        self.accept()

