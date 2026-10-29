# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra «Collega il browser»: estensione di Helpix per Chrome, Edge, Brave, Firefox…

Con l'estensione i servizi si usano nel browser di tutti i giorni (dove l'accesso con
Google funziona) e Helpix lavora direttamente nella chat: «Esegui con Helpix» sotto i
comandi, screenshot, diagnosi e output incollati nella casella, passaggio del task.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import native_install
from ..i18n import tr
from ..theme import C

CHROMIUM_STORE_URL = ""   # da compilare quando l'estensione sarà pubblicata sul Chrome Web Store
FIREFOX_STORE_URL = ""    # da compilare quando l'estensione sarà firmata su addons.mozilla.org


DIALOG_WIDTH = 660
STEP_TEXT_WIDTH = DIALOG_WIDTH - 48 - 32


class _Step(QFrame):
    def __init__(self, title: str, text: str, folder: str, store_url: str):
        super().__init__()
        self.setObjectName("group")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        v.addWidget(t)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setFixedWidth(STEP_TEXT_WIDTH)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(body)
        path = QLabel(folder)
        path.setObjectName("secondary")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(path)
        row = QHBoxLayout()
        row.setSpacing(8)
        if store_url:
            store = QPushButton(tr("Installa dallo store"))
            store.setObjectName("primary")
            store.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(store_url)))
            row.addWidget(store)
        open_btn = QPushButton(tr("Apri la cartella"))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        row.addWidget(open_btn)
        copy = QPushButton(tr("Copia il percorso"))
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(folder), copy.setText(tr("Copiato"))))
        row.addWidget(copy)
        row.addStretch(1)
        v.addLayout(row)


class BrowserDialog(QDialog):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle(tr("Collega il browser"))
        self.setFixedWidth(DIALOG_WIDTH)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        title = QLabel(tr("Usa Helpix nel tuo browser"))
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel(tr("Con l'estensione di Helpix usi ChatGPT, Claude, Gemini, Copilot e DeepSeek nel browser di tutti "
                        "i giorni, con l'accesso Google che funziona. Nella chat compare «Esegui con Helpix» sotto i "
                        "comandi e, a lato, Screenshot e Diagnosi: Helpix esegue e incolla l'output nella casella, tu "
                        "premi Invio. L'estensione non legge le conversazioni e non invia messaggi."))
        sub.setWordWrap(True)
        sub.setObjectName("secondary")
        v.addWidget(sub)

        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        registered = native_install.install()
        v.addWidget(_Step(
            tr("Chrome, Chromium, Edge, Brave, Vivaldi, Opera"),
            tr("Apri la pagina delle estensioni (chrome://extensions, edge://extensions…), attiva «Modalità "
               "sviluppatore», premi «Carica estensione non pacchettizzata» e scegli questa cartella:"),
            str(native_install.extension_dir("chromium")), CHROMIUM_STORE_URL))
        v.addWidget(_Step(
            tr("Firefox"),
            tr("Firefox installa in modo permanente solo estensioni firmate da Mozilla. Finché la versione firmata non è "
               "disponibile: apri about:debugging › Questo Firefox › «Carica componente aggiuntivo temporaneo» e scegli "
               "manifest.json in questa cartella (resta attiva fino alla chiusura di Firefox):"),
            str(native_install.extension_dir("firefox")), FIREFOX_STORE_URL))

        notes = []
        if registered:
            notes.append(tr("Collegamento registrato per: {names}.").format(names=", ".join(registered)))
        else:
            notes.append(tr("Non ho trovato browser nella tua cartella utente: avvia il browser almeno una volta, "
                            "poi riapri questa finestra."))
        boxed = native_install.sandboxed_browsers()
        if boxed:
            notes.append(tr("Browser installati come Flatpak o Snap ({names}): di norma non possono avviare il "
                            "collegamento con Helpix. Usa la versione del browser installata dal gestore dei "
                            "pacchetti (dnf, apt).").format(names=", ".join(boxed)))
        notes.append(tr("Dopo aver installato l'estensione ricarica le pagine delle chat già aperte."))
        note = QLabel("\n".join(notes))
        note.setObjectName("secondary")
        note.setWordWrap(True)
        v.addWidget(note)

        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Fine"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        if bridge is not None:
            bridge.clients_changed.connect(self.refresh)
        self.refresh()
        self.adjustSize()

    def showEvent(self, event):  # noqa: N802
        # le finestre di primo livello non usano heightForWidth: fisso l'altezza dei testi a capo
        # quando lo stile (e quindi il font) è già applicato
        for lab in self.findChildren(QLabel):
            if lab.wordWrap():
                lab.setMinimumHeight(lab.heightForWidth(lab.width() if lab.width() > 50 else STEP_TEXT_WIDTH))
        self.adjustSize()
        super().showEvent(event)

    def refresh(self):
        connected = self.bridge is not None and self.bridge.connected
        if connected:
            text = tr("Collegato: {names}").format(names=", ".join(self.bridge.browsers()))
            color = C["okText"]
        elif self.bridge is None:
            text = tr("Il collegamento è già usato da un'altra finestra di Helpix.")
            color = C["secondary"]
        else:
            text = tr("In attesa dell'estensione: installala e apri una chat nel browser.")
            color = C["secondary"]
        self.status.setText(("✓ " if connected else "") + text)
        self.status.setStyleSheet(f"color: {color}; font-weight: 600;")
