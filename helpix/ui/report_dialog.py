# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra «Segnala un problema»: descrizione, sezioni da includere, anteprima modificabile, invio."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import report
from ..i18n import tr
from ..theme import mono_font

log = logging.getLogger(__name__)


class ReportDialog(QDialog):
    def __init__(self, settings=None, vault=None, parent=None, title: str = "", url: str | None = None):
        super().__init__(parent)
        self.settings, self.vault = settings, vault
        self.url = report.REPORT_URL if url is None else url
        self.number: int | None = None
        self.saved_to = None
        self.setWindowTitle(tr("Segnala un problema"))
        self.resize(780, 760)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(8)
        head = QLabel(tr("Segnala un problema"))
        head.setObjectName("title")
        v.addWidget(head)
        info = QLabel(tr("Helpix prepara una segnalazione con le informazioni tecniche utili. Il filtro privacy toglie "
                         "nome utente, nome del PC, indirizzi e simili; il contenuto di note e progetti non viene mai "
                         "incluso. Rileggi l'anteprima: parte esattamente quello che vedi, e va in un archivio privato "
                         "letto solo da chi sviluppa Helpix."))
        info.setWordWrap(True)
        info.setObjectName("secondary")
        v.addWidget(info)

        self.title = QLineEdit(title)
        self.title.setPlaceholderText(tr("Titolo breve (es. «Il salvataggio del progetto non si apre»)"))
        self.title.setMaxLength(report.MAX_TITLE)
        self.title.setAccessibleName(tr("Titolo"))
        v.addWidget(self.title)
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(tr("Cosa stavi facendo, cosa ti aspettavi e cosa è successo invece. Se si "
                                        "ripete, scrivi anche i passi."))
        self.desc.setAccessibleName(tr("Cosa è successo"))
        self.desc.setFixedHeight(110)
        v.addWidget(self.desc)

        v.addWidget(QLabel(tr("Da includere")))
        self.sections = report.collect(settings, vault, diagnostics=False)
        self.sections.append(report.Section("diag", tr("Diagnosi del PC"), "", default=False))
        boxes = QWidget()
        grid = QGridLayout(boxes)
        grid.setContentsMargins(0, 0, 0, 0)
        self.checks: dict[str, QCheckBox] = {}
        for i, s in enumerate(self.sections):
            cb = QCheckBox(s.title)
            cb.setChecked(s.default)
            cb.toggled.connect(lambda on, key=s.key: self._toggled(key, on))
            self.checks[s.key] = cb
            grid.addWidget(cb, i // 2, i % 2)
        v.addWidget(boxes)

        v.addWidget(QLabel(tr("Anteprima: puoi modificarla, ma fallo per ultima (cambiando descrizione o sezioni si ricrea)")))
        self.preview = QPlainTextEdit()
        self.preview.setFont(mono_font(9))
        self.preview.setAccessibleName(tr("Anteprima della segnalazione"))
        v.addWidget(self.preview, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("secondary")
        v.addWidget(self.status)
        row = QHBoxLayout()
        self.btn_save = QPushButton(tr("Salva come file…"))
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.btn_send = QPushButton(tr("Invia"))
        self.btn_send.setObjectName("primary")
        self.btn_send.setDefault(True)
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.btn_send)
        v.addLayout(row)
        if not self.url:
            self.btn_send.setEnabled(False)
            self.status.setText(tr("L'invio automatico non è ancora attivo in questa versione: salva il file e "
                                   "mandalo a chi sviluppa Helpix."))
        self.desc.textChanged.connect(self._refresh)
        self._refresh()
        self.title.setFocus()

    # ------------------------------------------------------------ contenuto
    def _toggled(self, key: str, on: bool):
        if key == "diag" and on:
            s = next(s for s in self.sections if s.key == "diag")
            if not s.text:
                from ..diagnostics import collect
                from .vault_dialogs import run_busy
                self.status.setText(tr("Raccolgo la diagnosi del PC…"))
                try:
                    text = run_busy(self, collect)
                except Exception as exc:  # noqa: BLE001
                    text = f"(non riuscita: {exc})"
                s.text = report.clean([report.Section("diag", s.title, text or "")])[0].text
                self.status.clear()
        self._refresh()

    def chosen(self) -> list[report.Section]:
        return [s for s in self.sections if self.checks[s.key].isChecked()]

    def _refresh(self):
        self.preview.setPlainText(report.body(self.desc.toPlainText(), self.chosen()))

    def data(self) -> dict:
        title = self.title.text().strip() or tr("Segnalazione da Helpix")
        return report.payload(title, self.preview.toPlainText())

    # ------------------------------------------------------------ azioni
    def _ready(self) -> bool:
        if self.desc.toPlainText().strip() or self.title.text().strip():
            return True
        QMessageBox.information(self, tr("Segnala un problema"),
                                tr("Scrivi almeno un titolo o due righe su cosa è successo."))
        self.title.setFocus()
        return False

    def _send(self):
        if not self._ready():
            return
        from .vault_dialogs import run_busy
        self.btn_send.setEnabled(False)
        self.status.setText(tr("Invio in corso…"))
        try:
            self.number = run_busy(self, report.send, self.data(), self.url)
        except report.ReportError as exc:
            log.warning("segnalazione non inviata: %s", exc)
            self.btn_send.setEnabled(True)
            self.status.setText(str(exc) + " " + tr("Puoi salvarla come file e mandarla a mano."))
            return
        log.info("segnalazione inviata: n. %s", self.number)
        QMessageBox.information(self, tr("Segnala un problema"),
                                tr("Segnalazione inviata (n. {n}). Grazie: la leggiamo e, se serve una correzione, "
                                   "arriva con un aggiornamento.").format(n=self.number))
        self.accept()

    def _save(self):
        if not self._ready():
            return
        try:
            self.saved_to = report.save(self.data())
        except OSError as exc:
            QMessageBox.warning(self, tr("Segnala un problema"), str(exc))
            return
        self.status.setText(tr("Salvata in {path}").format(path=self.saved_to))
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


def open_report(parent=None, title: str = "") -> ReportDialog:
    """Apre la finestra dalla finestra principale o da un punto qualsiasi (cerca impostazioni e vault)."""
    main = None
    for w in QApplication.topLevelWidgets():
        if hasattr(w, "settings") and hasattr(w, "vault"):
            main = w
            break
    settings = getattr(main, "settings", None)
    vault = getattr(main, "vault", None)
    dlg = ReportDialog(settings, vault, parent or main, title=title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dlg.open()
    return dlg
