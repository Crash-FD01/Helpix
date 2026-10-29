# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra di gestione delle sessioni salvate."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from ..providers import PROVIDERS
from ..session import delete_session, list_sessions
from .web_panel import WEB_SITES
from ..i18n import tr


class SessionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Helpix — Task salvati"))
        self.resize(560, 460)
        self.selected: str | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        info = QLabel(tr("Riprendi un task precedente con qualsiasi IA: screenshot, comandi, risultati e "
                         "riepilogo passano alla nuova chat."))
        info.setObjectName("meta")
        info.setWordWrap(True)
        v.addWidget(info)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.itemDoubleClicked.connect(lambda _: self._open())
        v.addWidget(self.list, 1)
        for s in list_sessions():
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(s["updated"]))
            who = (WEB_SITES[s["site"]]["label"] if s.get("site") in WEB_SITES
                   else PROVIDERS.get(s["provider"], {}).get("label", s["provider"]))
            title = tr(s["title"]) if s["title"] == "Nuova sessione" else s["title"]
            item = QListWidgetItem(tr("{title}\n{when} · {who} · {count} elementi").format(
                title=title, when=when, who=who, count=s["count"]))
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.list.addItem(tr("Nessun task salvato."))
            self.list.setEnabled(False)

        row = QHBoxLayout()
        delete = QPushButton(tr("Elimina"))
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        row.addStretch(1)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        open_btn = QPushButton(tr("Apri"))
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self._open)
        row.addWidget(open_btn)
        v.addLayout(row)
        delete.setEnabled(self.list.isEnabled())
        open_btn.setEnabled(self.list.isEnabled())

    def _current_id(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open(self):
        sid = self._current_id()
        if sid:
            self.selected = sid
            self.accept()

    def _delete(self):
        sid = self._current_id()
        if not sid:
            return
        if QMessageBox.question(self, tr("Elimina task"),
                                tr("Eliminare definitivamente questo task?")) == QMessageBox.StandardButton.Yes:
            delete_session(sid)
            self.list.takeItem(self.list.currentRow())
