# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestre dei progetti e del vault (beta): nuovo progetto, salvataggio con anteprima, cifratura, sblocco,
recupero della password, impostazioni."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import passwords, project as pj
from ..i18n import tr
from ..system import IS_WINDOWS
from ..theme import C, mono_font
from ..vault import Vault, VaultError, WrongSecret, in_onedrive, keyring_available
from .workers import FuncWorker


def _wrap(text: str, secondary: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if secondary:
        lab.setObjectName("secondary")
    return lab


class _PathLabel(QLabel):
    """Percorso su una riga sola, accorciato al centro se non ci sta; intero nel suggerimento."""

    def __init__(self):
        super().__init__()
        self._full = ""
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_path(self, path: str):
        self._full = path
        self.setToolTip(path)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(20, self.width()))
        if shown != self.text():
            super().setText(shown)


def _title(text: str) -> QLabel:
    t = QLabel(text)
    t.setObjectName("title")
    t.setWordWrap(True)
    return t


def run_busy(parent, fn, *args, **kwargs):
    """Esegue `fn` in un thread (scrypt richiede qualche istante) senza bloccare la finestra; rilancia gli errori."""
    loop, box = QEventLoop(), {}
    w = FuncWorker(fn, *args, parent=parent, **kwargs)
    w.done.connect(lambda r: (box.__setitem__("r", r), loop.quit()))
    w.failed.connect(lambda e: (box.__setitem__("e", e), loop.quit()))
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        w.start()
        loop.exec()
        w.wait()
    finally:
        QApplication.restoreOverrideCursor()
    if "e" in box:
        raise box["e"]
    return box.get("r")


class BetaBanner(QFrame):
    """«Funzione in beta» con il pulsante per esportare in chiaro."""

    export = Signal()

    def __init__(self, text: str | None = None, export: bool = True, strong: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("notice")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)
        pill = QLabel(tr("Beta"))
        pill.setObjectName("pillErr" if strong else "pillWarn")
        h.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        msg = _wrap(text or tr("Progetti e vault sono in prova: tieni una copia dei dati importanti."), secondary=False)
        h.addWidget(msg, 1)
        if export:
            exp = QPushButton(tr("Esporta in chiaro"))
            exp.setObjectName("plain")
            exp.clicked.connect(self.export.emit)
            h.addWidget(exp)


# ------------------------------------------------------------------ password
class PasswordFields(QWidget):
    """Password con conferma, robustezza stimata e pulsante «Genera»."""

    changed = Signal()

    def __init__(self, parent=None, label: str | None = None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        if label:
            v.addWidget(QLabel(label))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText(tr("Password del vault (almeno {n} caratteri)").format(n=passwords.MIN_LENGTH))
        self.pw.setAccessibleName(tr("Password del vault"))
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2.setPlaceholderText(tr("Ripeti la password"))
        self.pw2.setAccessibleName(tr("Ripeti la password"))
        v.addWidget(self.pw)
        v.addWidget(self.pw2)
        row = QHBoxLayout()
        self.show_pw = QCheckBox(tr("Mostra"))
        self.show_pw.toggled.connect(self._echo)
        row.addWidget(self.show_pw)
        gen = QPushButton(tr("Genera una frase"))
        gen.setToolTip(tr("Sei parole casuali: facili da ricordare, molto difficili da indovinare"))
        gen.clicked.connect(self._generate)
        row.addWidget(gen)
        row.addStretch(1)
        v.addLayout(row)
        self.strength = QLabel()
        self.strength.setWordWrap(True)
        v.addWidget(self.strength)
        self.pw.textChanged.connect(self._update)
        self.pw2.textChanged.connect(self._update)
        self._update()

    def _echo(self, on: bool):
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.pw.setEchoMode(mode)
        self.pw2.setEchoMode(mode)

    def _generate(self):
        phrase = passwords.generate_passphrase()
        self.show_pw.setChecked(True)
        self.pw.setText(phrase)
        self.pw2.setText(phrase)

    def _update(self):
        pw = self.pw.text()
        if not pw:
            self.strength.setText(tr("Conta la lunghezza: una frase di parole va benissimo."))
            self.strength.setStyleSheet(f"color: {C['secondary']};")
        else:
            res = passwords.check(pw)
            color = C["okText"] if res["level"] >= 3 else C["warnText"] if res["ok"] else C["errText"]
            text = res["message"]
            if res["ok"] and self.pw2.text() and self.pw2.text() != pw:
                text, color = tr("Le due password non coincidono."), C["errText"]
            self.strength.setText(text)
            self.strength.setStyleSheet(f"color: {color};")
        self.changed.emit()

    def valid(self) -> bool:
        return passwords.check(self.pw.text())["ok"] and self.pw.text() == self.pw2.text()

    def password(self) -> str:
        return self.pw.text()


class CodesWidget(QWidget):
    """I codici usa e getta, da salvare, con la conferma (riscrivere uno dei codici)."""

    changed = Signal()

    def __init__(self, codes: list[str], vault_name: str = "", parent=None):
        super().__init__(parent)
        self.codes = codes
        self.vault_name = vault_name
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        box = QFrame()
        box.setObjectName("codeChip")
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        for i, c in enumerate(codes):
            lab = QLabel(f"{i + 1}. {c}")
            lab.setFont(mono_font())
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setMinimumSize(lab.sizeHint())
            grid.addWidget(lab, i, 0)  # una colonna: i codici sono lunghi e vanno letti interi
        v.addWidget(box)
        row = QHBoxLayout()
        copy = QPushButton(tr("Copia"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text()))
        row.addWidget(copy)
        save = QPushButton(tr("Salva in un file…"))
        save.clicked.connect(self._save)
        row.addWidget(save)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(_wrap(tr("Ogni codice funziona una volta sola. Conservali fuori dal PC: carta, password manager, "
                             "chiavetta. Helpix non li salva da nessuna parte.")))
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText(tr("Riscrivi uno dei codici per confermare di averli salvati"))
        self.confirm.setAccessibleName(tr("Conferma dei codici"))
        self.confirm.textChanged.connect(lambda _t: self.changed.emit())
        v.addWidget(self.confirm)

    def text(self) -> str:
        head = tr("Codici di recupero del vault di Helpix «{name}» (ognuno vale una volta sola):").format(
            name=self.vault_name)
        return head + "\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(self.codes)) + "\n"

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva i codici"),
                                              str(Path.home() / f"Codici-vault-{self.vault_name or 'Helpix'}.txt"),
                                              tr("Testo (*.txt)"))
        if path:
            Path(path).write_text(self.text(), encoding="utf-8")

    def confirmed(self) -> bool:
        from ..vault_crypto import normalize_code
        typed = normalize_code(self.confirm.text())
        return bool(typed) and typed in self.codes


def save_recovery_file(parent, text: str, vault_name: str) -> bool:
    """Chiede dove salvare il file di recupero. False se l'utente rinuncia."""
    path, _ = QFileDialog.getSaveFileName(parent, tr("Salva il file di recupero"),
                                          str(Path.home() / f"Vault-{vault_name or 'Helpix'}.helpix-recovery"),
                                          tr("File di recupero (*.helpix-recovery)"))
    if not path:
        return False
    Path(path).write_text(text, encoding="utf-8")
    try:
        Path(path).chmod(0o600)
    except OSError:
        pass
    if in_onedrive(path):
        QMessageBox.warning(parent, tr("File di recupero"),
                            tr("Il file è in una cartella di OneDrive: chi accede al tuo OneDrive potrà aprire il vault. "
                               "Meglio spostarlo su una chiavetta o nel password manager."))
    return True


# ------------------------------------------------------------------ nuovo progetto
class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Nuovo progetto"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(_title(tr("Nuovo progetto")))
        v.addWidget(_wrap(tr("Un progetto è un lavoro che continua: Helpix tiene un file breve con lo stato attuale e "
                             "lo dà all'IA a ogni chat nuova, con qualsiasi IA.")))
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Nome (es. «Cliente Rossi — firewall» o «Casa — rete Wi-Fi»)"))
        self.name.setAccessibleName(tr("Nome del progetto"))
        v.addWidget(self.name)
        self.goal = QLineEdit()
        self.goal.setPlaceholderText(tr("Obiettivo in una frase (facoltativo)"))
        self.goal.setAccessibleName(tr("Obiettivo"))
        v.addWidget(self.goal)
        self.context = QPlainTextEdit()
        self.context.setPlaceholderText(tr("Contesto (facoltativo). Puoi incollare qui un riepilogo fatto da un'altra "
                                           "IA: se è già nel formato di Helpix lo uso così com'è."))
        self.context.setAccessibleName(tr("Contesto"))
        self.context.setMinimumHeight(140)
        v.addWidget(self.context)
        copy = QPushButton(tr("Copia la richiesta per un'altra IA"))
        copy.setObjectName("plain")
        copy.setToolTip(tr("Incollala nell'IA (o nel progetto) dove hai già il contesto: ti restituirà il riepilogo nel "
                           "formato giusto da incollare qui sopra."))
        copy.clicked.connect(self._copy_request)
        v.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
        self.err = QLabel()
        self.err.setStyleSheet(f"color: {C['errText']};")
        self.err.hide()
        v.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(tr("Crea e apri"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        row.addWidget(ok)
        v.addLayout(row)

    def _copy_request(self):
        QGuiApplication.clipboard().setText(pj.import_request())
        self.err.setStyleSheet(f"color: {C['secondary']};")
        self.err.setText(tr("Richiesta copiata: incollala nell'altra IA, poi incolla qui la risposta."))
        self.err.show()

    def _ok(self):
        pasted = self.context.toPlainText().strip()
        if not self.name.text().strip() and not pj.title_of(pasted):
            self.err.setStyleSheet(f"color: {C['errText']};")
            self.err.setText(tr("Dai un nome al progetto."))
            self.err.show()
            return
        self.accept()

    def project_name(self) -> str:
        return self.name.text().strip() or pj.title_of(self.context.toPlainText()) or tr("Progetto")

    def project_text(self) -> str:
        pasted = self.context.toPlainText().strip()
        name = self.project_name()
        doc = pj.parse(pasted)
        if pasted and len(doc.sections) >= 2 and any(pj.section_key(s[0]) for s in doc.sections):
            # riepilogo già nel formato: titolo e sezione «Solo per me» se mancano
            if not pj.title_of(pasted):
                doc.preamble = [f"# {name}", ""] + doc.preamble
            if not doc.find("private"):
                doc.sections.append([pj.section_title("private"), []])
            if self.goal.text().strip() and not doc.find("goal"):
                doc.sections.insert(0, [pj.section_title("goal"), [self.goal.text().strip()]])
            return pj.render(doc)
        return pj.template(name, self.goal.text(), pasted)


# ------------------------------------------------------------------ salvataggio con anteprima
class ProjectSaveDialog(QDialog):
    """Anteprima dell'aggiornamento: PROJECT.md risultante e nota, modificabili, e l'elenco delle modifiche."""

    def __init__(self, project_name: str, update: pj.Update, result: pj.Result, source: str, parent=None):
        super().__init__(parent)
        self.full = update.full_text is not None
        self.setWindowTitle(tr("Aggiorna il progetto"))
        self.resize(820, 720)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(8)
        v.addWidget(_title(tr("Compatta il progetto «{name}»").format(name=project_name) if self.full
                           else tr("Aggiorna il progetto «{name}»").format(name=project_name)))
        v.addWidget(_wrap(tr("Proposta da {source}. Controlla e correggi se serve: si salva solo quando premi Salva; la "
                             "versione precedente resta tra le versioni.").format(source=source)))
        changes = [("✓ " + a, C["okText"]) for a in result.applied] + [("! " + w, C["warnText"]) for w in result.warnings]
        if not changes:
            changes = [(tr("Nessuna modifica a PROJECT.md: si salva solo la nota."), C["secondary"])]
        for text, color in changes[:14]:
            lab = _wrap(text, secondary=False)
            lab.setStyleSheet(f"color: {color};")
            v.addWidget(lab)
        if len(changes) > 14:
            v.addWidget(_wrap(tr("…e altre {n}.").format(n=len(changes) - 14)))
        head = QHBoxLayout()
        head.addWidget(QLabel("PROJECT.md"))
        head.addStretch(1)
        self.tokens = QLabel()
        head.addWidget(self.tokens)
        v.addLayout(head)
        self.text = QPlainTextEdit(result.text)
        self.text.setFont(mono_font())
        self.text.setAccessibleName("PROJECT.md")
        self.text.textChanged.connect(self._update_tokens)
        v.addWidget(self.text, 3)
        self.note_title = QLineEdit(update.title or tr("Sessione"))
        self.note_title.setAccessibleName(tr("Titolo della nota"))
        self.note_body = QPlainTextEdit(update.body)
        self.note_body.setAccessibleName(tr("Testo della nota"))
        if not self.full:
            v.addWidget(QLabel(tr("Nota della sessione")))
            v.addWidget(self.note_title)
            v.addWidget(self.note_body, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton(tr("Salva"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)
        self._update_tokens()

    def _update_tokens(self):
        n = pj.estimate_tokens(pj.strip_private(self.text.toPlainText()))
        self.tokens.setText(tr("~{n} / {limit} token").format(n=n, limit=pj.TOKEN_LIMIT))
        self.tokens.setObjectName("pillWarn" if n > pj.TOKEN_LIMIT else "pillOk")
        self.tokens.setToolTip(tr("Oltre il limite conviene compattare il progetto.") if n > pj.TOKEN_LIMIT else "")
        self.tokens.style().unpolish(self.tokens)
        self.tokens.style().polish(self.tokens)

    def project_text(self) -> str:
        return self.text.toPlainText().rstrip("\n") + "\n"

    def note(self) -> tuple[str, str]:
        return self.note_title.text().strip(), self.note_body.toPlainText().strip()


# ------------------------------------------------------------------ cifratura del vault
class VaultCreateDialog(QDialog):
    """Cifra il vault in tre passi: password, codici (e file di recupero facoltativo), comodità."""

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle(tr("Cifra il vault"))
        self.setMinimumWidth(560)
        self.codes = passwords.generate_codes()
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(BetaBanner(tr("La cifratura del vault è in beta. Se perdi password e codici, i dati non si "
                                  "recuperano: esporta regolarmente una copia."), export=False, strong=True))
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # passo 1: password
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(_title(tr("1 di 3 · Scegli la password del vault")))
        l1.addWidget(_wrap(tr("La chiederà Helpix per aprire il vault. Conta la lunghezza: una frase di parole che "
                              "ricordi va benissimo.")))
        self.fields = PasswordFields()
        l1.addWidget(self.fields)
        try:
            has_files = bool(vault.is_open and vault.store.list())
        except VaultError:
            has_files = False
        if has_files:
            l1.addWidget(_wrap(tr("I file già nel vault vengono cifrati, verificati e poi cancellati in chiaro. Su SSD o "
                                  "con copie automatiche del disco la cancellazione non garantisce che non restino "
                                  "tracce: per la protezione a PC spento usa anche la cifratura del disco (LUKS, "
                                  "BitLocker).")))
        l1.addStretch(1)
        self.stack.addWidget(p1)

        # passo 2: codici e file di recupero
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(_title(tr("2 di 3 · Salva i codici di recupero")))
        l2.addWidget(_wrap(tr("Se dimentichi la password, uno di questi codici ti fa entrare e scegliere una password "
                              "nuova.")))
        self.codes_w = CodesWidget(self.codes, vault.name)
        l2.addWidget(self.codes_w)
        self.recovery = QCheckBox(tr("Crea anche un file di recupero (facoltativo)"))
        self.recovery.setToolTip(tr("Un file che apre il vault: comodo, ma chi lo possiede entra. Tienilo fuori dal PC."))
        l2.addWidget(self.recovery)
        l2.addStretch(1)
        self.stack.addWidget(p2)

        # passo 3: comodità
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.addWidget(_title(tr("3 di 3 · Comodità (facoltativo)")))
        how = tr("con Windows Hello") if IS_WINDOWS else tr("con la password del tuo utente o l'impronta")
        self.keyring = QCheckBox(tr("Sblocca il vault anche {how}").format(how=how))
        self.keyring.setEnabled(keyring_available())
        l3.addWidget(self.keyring)
        l3.addWidget(_wrap(tr("Una chiave in più nel portachiavi di sistema; prima di usarla Helpix chiede conferma al "
                              "sistema. La password del vault resta valida.") if keyring_available() else
                           tr("Il portachiavi di sistema non è disponibile: userai la password del vault.")))
        l3.addStretch(1)
        self.stack.addWidget(p3)

        self.err = QLabel()
        self.err.setStyleSheet(f"color: {C['errText']};")
        self.err.setWordWrap(True)
        self.err.hide()
        v.addWidget(self.err)
        row = QHBoxLayout()
        self.back = QPushButton(tr("Indietro"))
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        row.addWidget(self.back)
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.next = QPushButton(tr("Avanti"))
        self.next.setObjectName("primary")
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        row.addWidget(self.next)
        v.addLayout(row)
        self.fields.changed.connect(self._refresh)
        self.codes_w.changed.connect(self._refresh)
        self.recovery_text: str | None = None
        self._go(0)

    def _go(self, i: int):
        self.stack.setCurrentIndex(max(0, min(2, i)))
        page = self.stack.currentWidget()
        self.stack.setMinimumHeight(page.sizeHint().height())  # ogni passo con lo spazio che gli serve
        hint = self.sizeHint()
        self.resize(max(self.width(), hint.width()), max(hint.height(), self.minimumSizeHint().height()))
        self.back.setVisible(self.stack.currentIndex() > 0)
        self.next.setText(tr("Cifra il vault") if self.stack.currentIndex() == 2 else tr("Avanti"))
        self.err.hide()
        self._refresh()

    def _refresh(self):
        i = self.stack.currentIndex()
        self.next.setEnabled(self.fields.valid() if i == 0 else self.codes_w.confirmed() if i == 1 else True)

    def _next(self):
        if self.stack.currentIndex() < 2:
            self._go(self.stack.currentIndex() + 1)
            return
        try:
            self.recovery_text = run_busy(self, self.vault.create_encrypted, self.fields.password(), self.codes,
                                          self.recovery.isChecked())
        except Exception as exc:  # noqa: BLE001 - mostrato all'utente, il vault resta com'era
            self.err.setText(tr("Cifratura non riuscita: {exc}. Il vault è rimasto com'era.").format(exc=exc))
            self.err.show()
            return
        if self.recovery_text:
            while not save_recovery_file(self, self.recovery_text, self.vault.name):
                if QMessageBox.question(self, tr("File di recupero"),
                                        tr("Senza salvarlo il file di recupero non serve. Lo annullo?")) == \
                        QMessageBox.StandardButton.Yes:
                    self.vault.revoke_recovery()
                    break
        if self.keyring.isChecked():
            try:
                self.vault.enable_keyring()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, tr("Portachiavi"), tr("Non riesco a usare il portachiavi: {exc}").format(exc=exc))
        self.accept()


class CodesDialog(QDialog):
    """Codici nuovi (rigenerati): da salvare e confermare."""

    def __init__(self, codes: list[str], vault_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Codici di recupero"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(_title(tr("Nuovi codici di recupero")))
        v.addWidget(_wrap(tr("I codici vecchi non valgono più.")))
        self.w = CodesWidget(codes, vault_name)
        v.addWidget(self.w)
        row = QHBoxLayout()
        row.addStretch(1)
        self.ok = QPushButton(tr("Li ho salvati"))
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        v.addLayout(row)
        self.w.changed.connect(lambda: self.ok.setEnabled(self.w.confirmed()))

    def reject(self):  # i codici sono già attivi: si chiude solo confermando di averli salvati
        if self.w.confirmed():
            super().reject()
            return
        if QMessageBox.question(self, tr("Codici di recupero"),
                                tr("I codici nuovi sono già attivi e quelli vecchi non valgono più. Chiudere senza "
                                   "averli salvati?")) == QMessageBox.StandardButton.Yes:
            super().reject()


def regenerate_codes(parent, vault: Vault) -> bool:
    codes = passwords.generate_codes()
    try:
        run_busy(parent, vault.regenerate_codes, codes)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(parent, tr("Codici di recupero"), str(exc))
        return False
    CodesDialog(codes, vault.name, parent).exec()
    return True


class ChangePasswordDialog(QDialog):
    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or tr("Cambia la password del vault"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(_title(title or tr("Cambia la password del vault")))
        self.fields = PasswordFields()
        v.addWidget(self.fields)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.ok = QPushButton(tr("Salva la password"))
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        v.addLayout(row)
        self.fields.changed.connect(lambda: self.ok.setEnabled(self.fields.valid()))

    def password(self) -> str:
        return self.fields.password()


class VaultUnlockDialog(QDialog):
    """Sblocco del vault: password, conferma del sistema (portachiavi) o recupero con codice o file."""

    system_unlock = Signal()   # l'utente vuole usare password di sistema / impronta / Windows Hello

    def __init__(self, vault: Vault, parent=None, allow_system: bool = False):
        super().__init__(parent)
        self.vault = vault
        self.info: dict | None = None
        self.setWindowTitle(tr("Sblocca il vault"))
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)

        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(_title(tr("Vault «{name}» bloccato").format(name=vault.name)))
        l1.addWidget(_wrap(tr("I file sul disco sono cifrati. Sbloccalo per leggere progetti e note e usarli con l'IA.")))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText(tr("Password del vault"))
        self.pw.setAccessibleName(tr("Password del vault"))
        self.pw.returnPressed.connect(self._unlock)
        l1.addWidget(self.pw)
        self.btn = QPushButton(tr("Sblocca"))
        self.btn.setObjectName("primary")
        self.btn.setDefault(True)
        self.btn.clicked.connect(self._unlock)
        l1.addWidget(self.btn)
        if allow_system and vault.keyring_enabled():
            how = tr("Usa Windows Hello") if IS_WINDOWS else tr("Usa la password di sistema o l'impronta")
            sysb = QPushButton(how)
            sysb.clicked.connect(self.system_unlock.emit)
            l1.addWidget(sysb)
        forgot = QPushButton(tr("Password dimenticata?"))
        forgot.setObjectName("plain")
        forgot.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        l1.addWidget(forgot, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack.addWidget(p1)

        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(_title(tr("Recupera l'accesso")))
        self.use_code = QRadioButton(tr("Con un codice usa e getta"))
        self.use_code.setChecked(True)
        l2.addWidget(self.use_code)
        self.code = QLineEdit()
        self.code.setPlaceholderText(tr("Uno dei codici di recupero (es. vela-torre-muschio-faro-cedro-lampo)"))
        self.code.setAccessibleName(tr("Codice di recupero"))
        l2.addWidget(self.code)
        self.use_file = QRadioButton(tr("Con il file di recupero"))
        self.file_path = ""
        self.file_btn = QPushButton(tr("Scegli il file…"))
        self.file_btn.clicked.connect(self._pick_file)
        if vault.has_recovery():
            l2.addWidget(self.use_file)
            l2.addWidget(self.file_btn)
        self.use_code.toggled.connect(lambda on: (self.code.setEnabled(on), self.file_btn.setEnabled(not on)))
        self.file_btn.setEnabled(False)
        l2.addWidget(QLabel(tr("Nuova password")))
        self.new_pw = PasswordFields()
        l2.addWidget(self.new_pw)
        row2 = QHBoxLayout()
        back = QPushButton(tr("Indietro"))
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        row2.addWidget(back)
        row2.addStretch(1)
        self.reset_btn = QPushButton(tr("Reimposta la password"))
        self.reset_btn.setObjectName("primary")
        self.reset_btn.clicked.connect(self._recover)
        row2.addWidget(self.reset_btn)
        l2.addLayout(row2)
        self.stack.addWidget(p2)

        self.err = QLabel()
        self.err.setStyleSheet(f"color: {C['errText']};")
        self.err.setWordWrap(True)
        self.err.hide()
        v.addWidget(self.err)
        close = QPushButton(tr("Annulla"))
        close.clicked.connect(self.reject)
        v.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _error(self, text: str):
        self.err.setText(text)
        self.err.show()

    def _unlock(self):
        if not self.pw.text():
            return
        try:
            self.info = run_busy(self, self.vault.unlock, "password", self.pw.text())
        except WrongSecret:
            self.pw.selectAll()
            self._error(tr("Password sbagliata."))
            return
        except Exception as exc:  # noqa: BLE001
            self._error(tr("Non riesco ad aprire il vault: {exc}").format(exc=exc))
            return
        self.accept()

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("File di recupero"), str(Path.home()),
                                              tr("File di recupero (*.helpix-recovery);;Tutti i file (*)"))
        if path:
            self.file_path = path
            self.file_btn.setText(Path(path).name)

    def _recover(self):
        if not self.new_pw.valid():
            self._error(tr("Scegli una password nuova valida (e ripetila uguale)."))
            return
        try:
            if self.use_code.isChecked():
                self.info = run_busy(self, self.vault.unlock, "code", self.code.text())
            else:
                if not self.file_path:
                    self._error(tr("Scegli il file di recupero."))
                    return
                self.info = run_busy(self, self.vault.unlock, "recovery",
                                     Path(self.file_path).read_text(encoding="utf-8", errors="replace"))
            run_busy(self, self.vault.change_password, self.new_pw.password())
        except WrongSecret:
            self._error(tr("Codice o file non validi per questo vault (un codice vale una volta sola)."))
            return
        except Exception as exc:  # noqa: BLE001
            self._error(tr("Recupero non riuscito: {exc}").format(exc=exc))
            return
        left = self.vault.codes_left()
        msg = tr("Password reimpostata. Codici di recupero rimasti: {n}.").format(n=left)
        msg += "\n\n" + tr("Consiglio: rigenera i codici, così quelli che potrebbero essere in un vecchio backup del "
                           "vault non valgono più.")
        if QMessageBox.question(self, tr("Vault"), msg + "\n\n" + tr("Rigenerarli adesso?")) == \
                QMessageBox.StandardButton.Yes:
            regenerate_codes(self, self.vault)
        self.accept()


# ------------------------------------------------------------------ impostazioni
AUTOSAVE = [(0, "spento"), (5, "ogni 5 minuti"), (10, "ogni 10 minuti"), (15, "ogni 15 minuti")]
TOKEN_LIMITS = [(500, "~500 token (molto corto)"), (1000, "~1000 token (consigliato)"),
                (2000, "~2000 token"), (4000, "~4000 token (contesti grandi)")]


class ProjectSettingsDialog(QDialog):
    """Impostazioni › Progetti e vault (beta)."""

    changed = Signal()        # impostazioni cambiate (l'app rilegge)
    export_requested = Signal()

    def __init__(self, settings, vault_getter, parent=None, system_unlock=None):
        super().__init__(parent)
        self.settings = settings
        self.vault_getter = vault_getter
        self.system_unlock = system_unlock
        self.setWindowTitle(tr("Progetti e vault (beta)"))
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(_title(tr("Progetti e vault")))
        banner = BetaBanner()
        banner.export.connect(self.export_requested.emit)
        v.addWidget(banner)
        self.enabled = QCheckBox(tr("Attiva progetti e vault (beta)"))
        self.enabled.setChecked(bool(settings.get("projects_beta", False)))
        self.enabled.toggled.connect(lambda on: self._set("projects_beta", on))
        v.addWidget(self.enabled)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        r = 0
        grid.addWidget(QLabel(tr("Cartella del vault")), r, 0)
        self.folder = _PathLabel()
        grid.addWidget(self.folder, r, 1)
        change = QPushButton(tr("Cambia…"))
        change.clicked.connect(self._choose_folder)
        grid.addWidget(change, r, 2)
        r += 1
        self.onedrive = _wrap(tr("⚠ È dentro OneDrive: rischio di conflitti e file «solo online»."))
        grid.addWidget(self.onedrive, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel(tr("Bozza della sessione")), r, 0)
        self.autosave = QComboBox()
        for minutes, label in AUTOSAVE:
            self.autosave.addItem(tr(label), minutes)
        values = [m for m, _ in AUTOSAVE]
        cur = int(settings.get("project_autosave_min", 10))
        self.autosave.setCurrentIndex(values.index(cur) if cur in values else 2)
        self.autosave.currentIndexChanged.connect(lambda _i: self._set("project_autosave_min", self.autosave.currentData()))
        self.autosave.setToolTip(tr("Comandi, output e diagnosi della sessione salvati nel progetto: niente IA, "
                                    "niente token."))
        grid.addWidget(self.autosave, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel(tr("Aggiornamento del progetto")), r, 0)
        self.mode = QComboBox()
        self.mode.addItem(tr("Chiedi sempre (anteprima)"), "ask")
        self.mode.addItem(tr("Automatico con annullamento"), "auto")
        self.mode.setCurrentIndex(1 if settings.get("project_update_mode") == "auto" else 0)
        self.mode.currentIndexChanged.connect(lambda _i: self._set("project_update_mode", self.mode.currentData()))
        grid.addWidget(self.mode, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel(tr("Versioni da conservare")), r, 0)
        self.versions = QComboBox()
        for n in (10, 20, 50, 100):
            self.versions.addItem(str(n), n)
        keep = int(settings.get("project_versions", 20))
        if keep not in (10, 20, 50, 100):
            self.versions.addItem(str(keep), keep)
        self.versions.setCurrentIndex(self.versions.findData(keep))
        self.versions.currentIndexChanged.connect(lambda _i: self._set("project_versions", self.versions.currentData()))
        grid.addWidget(self.versions, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel(tr("Tetto di PROJECT.md")), r, 0)
        self.limit = QComboBox()
        for n, label in TOKEN_LIMITS:
            self.limit.addItem(tr(label), n)
        cur_limit = pj.set_token_limit(settings.get("project_token_limit", 1000))
        self.limit.setCurrentIndex(max(0, self.limit.findData(cur_limit)))
        self.limit.currentIndexChanged.connect(lambda _i: self._set("project_token_limit", self.limit.currentData()))
        self.limit.setToolTip(tr("PROJECT.md va all'IA all'inizio di ogni chat nuova (con API e agenti a ogni "
                                 "richiesta): più è corto, meno costa e meglio viene seguito. Oltre il tetto Helpix "
                                 "propone di compattarlo; non blocca niente."))
        grid.addWidget(self.limit, r, 1, 1, 2)
        r += 1
        self.reminder = QCheckBox(tr("Ricordami di salvare (cambio progetto, nuovo task, altra IA, chiusura)"))
        self.reminder.setChecked(bool(settings.get("project_reminder", True)))
        self.reminder.toggled.connect(lambda on: self._set("project_reminder", on))
        grid.addWidget(self.reminder, r, 0, 1, 3)
        v.addLayout(grid)

        sec = QFrame()
        sec.setObjectName("group")
        sv = QVBoxLayout(sec)
        sv.setContentsMargins(14, 12, 14, 12)
        sv.setSpacing(8)
        sv.addWidget(_title(tr("Cifratura (facoltativa, beta)")))
        self.status = _wrap("")
        sv.addWidget(self.status)
        rows = QGridLayout()
        self.b_encrypt = QPushButton(tr("Cifra il vault…"))
        self.b_encrypt.clicked.connect(self._encrypt)
        self.b_password = QPushButton(tr("Cambia password…"))
        self.b_password.clicked.connect(self._change_password)
        self.b_codes = QPushButton(tr("Rigenera i codici…"))
        self.b_codes.clicked.connect(lambda: (regenerate_codes(self, self.vault_getter()), self._refresh()))
        self.b_recovery = QPushButton()
        self.b_recovery.clicked.connect(self._recovery)
        self.b_keyring = QPushButton()
        self.b_keyring.clicked.connect(self._keyring)
        self.b_unlock = QPushButton(tr("Sblocca il vault…"))
        self.b_unlock.clicked.connect(self._unlock)
        self.b_export = QPushButton(tr("Esporta in chiaro…"))
        self.b_export.clicked.connect(self.export_requested.emit)
        for i, b in enumerate((self.b_encrypt, self.b_unlock, self.b_password, self.b_codes, self.b_recovery,
                               self.b_keyring, self.b_export)):
            rows.addWidget(b, i // 2, i % 2)
        sv.addLayout(rows)
        v.addWidget(sec)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Chiudi"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self._refresh()

    def _set(self, key, value):
        self.settings.set(key, value)
        self.changed.emit()
        self._refresh()

    def _refresh(self):
        from ..vault import default_root
        folder = self.settings.get("vault_dir") or str(default_root())
        self.folder.set_path(folder)
        self.onedrive.setVisible(in_onedrive(folder))
        vault = self.vault_getter() if self.settings.get("projects_beta") else None
        enabled = vault is not None
        for b in (self.b_encrypt, self.b_password, self.b_codes, self.b_recovery, self.b_keyring, self.b_unlock,
                  self.b_export):
            b.setVisible(False)
        if not enabled:
            self.status.setText(tr("Attiva la funzione per gestire il vault."))
            return
        if not vault.encrypted:
            self.status.setText(tr("Il vault non è cifrato: i file sono Markdown leggibili da chiunque usi il tuo "
                                   "utente. Per la protezione a PC spento basta la cifratura del disco."))
            self.b_encrypt.setVisible(True)
            self.b_export.setVisible(True)
            return
        if not vault.is_open:
            self.status.setText(tr("Vault cifrato e bloccato: sbloccalo per gestire password, codici e file di recupero."))
            self.b_unlock.setVisible(True)
            return
        parts = [tr("Vault cifrato e aperto."), tr("Codici di recupero rimasti: {n}.").format(n=vault.codes_left()),
                 tr("File di recupero: sì.") if vault.has_recovery() else tr("File di recupero: no."),
                 tr("Sblocco dal portachiavi: sì.") if vault.keyring_enabled() else tr("Sblocco dal portachiavi: no.")]
        self.status.setText(" ".join(parts))
        self.b_recovery.setText(tr("Revoca il file di recupero") if vault.has_recovery()
                                else tr("Crea il file di recupero…"))
        self.b_keyring.setText(tr("Togli lo sblocco dal portachiavi") if vault.keyring_enabled()
                               else tr("Sblocca anche dal portachiavi"))
        self.b_keyring.setEnabled(vault.keyring_enabled() or keyring_available())
        for b in (self.b_password, self.b_codes, self.b_recovery, self.b_keyring, self.b_export):
            b.setVisible(True)

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("Cartella del vault"),
                                                self.settings.get("vault_dir") or str(Path.home()))
        if not path:
            return
        if in_onedrive(path) and QMessageBox.question(
                self, tr("Cartella del vault"),
                tr("La cartella è dentro OneDrive: possono nascere conflitti di sincronizzazione e file «solo online» "
                   "non presenti sul disco. Usarla comunque?")) != QMessageBox.StandardButton.Yes:
            return
        self._set("vault_dir", path)

    def _encrypt(self):
        vault = self.vault_getter()
        if vault and VaultCreateDialog(vault, self).exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, tr("Vault"), tr("Vault cifrato. Si blocca insieme a Helpix."))
            self.changed.emit()
        self._refresh()

    def _unlock(self):
        vault = self.vault_getter()
        dlg = VaultUnlockDialog(vault, self, allow_system=self.system_unlock is not None)
        if self.system_unlock:
            dlg.system_unlock.connect(lambda: self.system_unlock(dlg))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.changed.emit()
        self._refresh()

    def _change_password(self):
        dlg = ChangePasswordDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                run_busy(self, self.vault_getter().change_password, dlg.password())
                QMessageBox.information(self, tr("Vault"), tr("Password cambiata."))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, tr("Vault"), str(exc))

    def _recovery(self):
        vault = self.vault_getter()
        if vault.has_recovery():
            if QMessageBox.question(self, tr("File di recupero"),
                                    tr("Il file di recupero non aprirà più il vault. Revocarlo?")) == \
                    QMessageBox.StandardButton.Yes:
                vault.revoke_recovery()
        else:
            text = vault.create_recovery()
            if not save_recovery_file(self, text, vault.name):
                vault.revoke_recovery()
        self._refresh()

    def _keyring(self):
        vault = self.vault_getter()
        try:
            if vault.keyring_enabled():
                vault.disable_keyring()
            else:
                vault.enable_keyring()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Portachiavi"), tr("Non riesco a usare il portachiavi: {exc}").format(exc=exc))
        self._refresh()
