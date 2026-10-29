# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestre della sicurezza: impostazioni, password dell'export, schermata di blocco."""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from ..system import IS_WINDOWS
from .. import security
from ..i18n import tr
from ..icons import icon
from ..theme import C

AUTO_LOCK = [(5, "dopo 5 minuti"), (15, "dopo 15 minuti"), (30, "dopo 30 minuti"), (60, "dopo un'ora"), (0, "mai")]


def _wrap(text: str, secondary: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    if secondary:
        lab.setObjectName("secondary")
    return lab


class ExportPasswordDialog(QDialog):
    """Password (con conferma) per cifrare un task esportato."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Proteggi il task con una password"))
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        t = QLabel(tr("Proteggi il task con una password"))
        t.setObjectName("title")
        v.addWidget(t)
        v.addWidget(_wrap(tr("Il file sarà cifrato (AES-256): per aprirlo servirà questa password. Comunicala a chi "
                             "deve importarlo per un'altra strada (non insieme al file). Se la perdi, il file non si "
                             "può più aprire.")))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText(tr("Password (almeno 8 caratteri)"))
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2.setPlaceholderText(tr("Ripeti la password"))
        v.addWidget(self.pw)
        v.addWidget(self.pw2)
        self.err = QLabel()
        self.err.setStyleSheet(f"color: {C['errText']};")
        self.err.hide()
        v.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(tr("Esporta cifrato"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        row.addWidget(ok)
        v.addLayout(row)

    def _ok(self):
        if len(self.pw.text()) < 8:
            self.err.setText(tr("La password deve avere almeno 8 caratteri."))
        elif self.pw.text() != self.pw2.text():
            self.err.setText(tr("Le due password non coincidono."))
        else:
            self.accept()
            return
        self.err.show()

    def password(self) -> str:
        return self.pw.text()


class LockOverlay(QFrame):
    """Copre il contenuto di Helpix finché l'utente non si sblocca."""

    unlock = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("lockOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#lockOverlay {{ background: {C['window']}; }}")
        v = QVBoxLayout(self)
        v.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icon("lock", C["accentFg"], 44, 1.6).pixmap(44, 44))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(ic)
        t = QLabel(tr("Helpix è bloccato"))
        t.setObjectName("title")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        self.msg = QLabel(tr("Sbloccalo con la password del tuo utente o con l'impronta."))
        self.msg.setObjectName("secondary")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn = QPushButton(tr("Sblocca"))
        self.btn.setObjectName("primary")
        self.btn.setMinimumWidth(140)
        self.btn.clicked.connect(self.unlock.emit)
        row.addWidget(self.btn)
        row.addStretch(1)
        v.addSpacing(8)
        v.addLayout(row)
        v.addStretch(2)

    def restyle(self):
        self.setStyleSheet(f"#lockOverlay {{ background: {C['window']}; }}")

    def set_waiting(self, waiting: bool, error: str = ""):
        self.btn.setEnabled(not waiting)
        if waiting:
            self.msg.setText(tr("Conferma nel dialogo del sistema…"))
        elif error:
            self.msg.setText(error)
        else:
            self.msg.setText(tr("Sbloccalo con la password del tuo utente o con l'impronta."))


class SecurityDialog(QDialog):
    """Opzioni di sicurezza: tutte disattivate finché l'utente non le sceglie."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Sicurezza"))
        self.setFixedWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        t = QLabel(tr("Sicurezza"))
        t.setObjectName("title")
        v.addWidget(t)
        v.addWidget(_wrap(tr("Opzioni facoltative: scegli tu cosa attivare.")))

        box = QFrame()
        box.setObjectName("group")
        b = QVBoxLayout(box)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(8)
        self.cb_lock = QCheckBox(tr("Blocca Helpix con Windows Hello (PIN, impronta o volto)") if IS_WINDOWS else
                                 tr("Blocca Helpix con la password del sistema o l'impronta"))
        self.cb_lock.setChecked(bool(settings.get("lock_enabled", False)))
        b.addWidget(self.cb_lock)
        b.addWidget(_wrap(tr("All'avvio e dopo un periodo in cui non lo usi, Helpix si blocca: per riaprirlo confermi "
                             "con Windows Hello (PIN, impronta o volto), lo stesso dialogo che Windows usa per "
                             "confermare la tua identità. Anche la finestra rapida resta bloccata.") if IS_WINDOWS else
                          tr("All'avvio e dopo un periodo in cui non lo usi, Helpix si blocca: per riaprirlo usi la "
                             "password del tuo utente Linux o l'impronta (se è configurata nel sistema), con il "
                             "dialogo di sistema. Anche la finestra rapida resta bloccata.")))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Blocco automatico se non lo usi")))
        self.auto = QComboBox()
        for minutes, label in AUTO_LOCK:
            self.auto.addItem(tr(label), minutes)
        current = int(settings.get("lock_minutes", 15))
        self.auto.setCurrentIndex(max(self.auto.findData(current), 0))
        row.addStretch(1)
        row.addWidget(self.auto)
        b.addLayout(row)
        self.lock_status = _wrap("")
        b.addWidget(self.lock_status)
        v.addWidget(box)

        box2 = QFrame()
        box2.setObjectName("group")
        b2 = QVBoxLayout(box2)
        b2.setContentsMargins(16, 14, 16, 14)
        b2.setSpacing(8)
        self.cb_export = QCheckBox(tr("Proteggi con una password i task esportati"))
        self.cb_export.setChecked(bool(settings.get("encrypt_exports", False)))
        b2.addWidget(self.cb_export)
        b2.addWidget(_wrap(tr("Ogni file .helpix esportato viene cifrato (AES-256) con una password che scegli al "
                              "momento. I file cifrati ricevuti da altri si aprono sempre, chiedendo la password.")))
        v.addWidget(box2)

        v.addWidget(_wrap(tr("Da sapere: gli accessi a ChatGPT, Claude e agli altri servizi li conserva il browser "
                             "integrato nella tua cartella utente. Il blocco impedisce di usarli da Helpix; per "
                             "proteggere i file quando il PC è spento serve la cifratura del disco (LUKS).")
                          if not IS_WINDOWS else
                          tr("Da sapere: gli accessi a ChatGPT, Claude e agli altri servizi li conserva il browser "
                             "integrato nella tua cartella utente. Il blocco impedisce di usarli da Helpix; per "
                             "proteggere i file quando il PC è spento serve la cifratura del disco (BitLocker).")))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton(tr("Salva"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        v.addLayout(buttons)
        self.cb_lock.toggled.connect(self._update)
        self._update()

    def _update(self, *_):
        on = self.cb_lock.isChecked()
        self.auto.setEnabled(on)
        if IS_WINDOWS and not security.unlock_available():
            self.lock_status.setText(
                tr("Windows Hello non è configurato: imposta un PIN (o impronta o volto) in Impostazioni › Account › "
                   "Opzioni di accesso, poi riapri questa finestra.") if security.hello_status() == "not-configured"
                else tr("Windows Hello non è disponibile su questo PC: il blocco non si può usare."))
            self.cb_lock.setEnabled(False)
        elif not security.unlock_available():
            self.lock_status.setText(tr("polkit (pkcheck) non è installato: il blocco non è disponibile."))
            self.cb_lock.setEnabled(False)
        elif on and not security.policy_installed():
            self.lock_status.setText(tr("Al salvataggio Helpix installa una regola di sistema (una volta sola): ti "
                                        "verrà chiesta la password di amministratore."))
        else:
            self.lock_status.setText("")

    def _save(self):
        lock = self.cb_lock.isChecked()
        if lock and not security.policy_installed() and not self._install_policy():
            return
        self.settings.data.update(lock_enabled=lock, lock_minutes=int(self.auto.currentData()),
                                  encrypt_exports=self.cb_export.isChecked())
        self.settings.save()
        self.accept()

    def _install_policy(self) -> bool:
        cmd = security.install_policy_command()
        proc = QProcess(self)
        proc.start(cmd[0], cmd[1:])
        proc.waitForFinished(180_000)  # il dialogo dell'amministratore è del sistema
        if proc.exitCode() == 0 and security.policy_installed():
            return True
        QMessageBox.warning(self, tr("Sicurezza"), tr(
            "Non è stato possibile installare la regola di sistema per lo sblocco (autorizzazione annullata o "
            "pkexec non disponibile). Il blocco resta disattivato."))
        return False
