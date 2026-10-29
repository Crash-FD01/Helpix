# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra iniziale: scelta del fornitore di IA, del modello e della chiave API."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from ..config import CONFIG_DIR
from ..providers import PROVIDERS, list_models
from ..theme import C
from .workers import FuncWorker
from ..i18n import tr


class SetupDialog(QDialog):
    def __init__(self, settings, secrets, parent=None, first_run: bool = True, current=None):
        super().__init__(parent)
        self.settings, self.secrets = settings, secrets
        self.first_run = first_run
        self.provider = self.model = None
        self._workers: set = set()
        self.setWindowTitle(tr("Helpix — Scegli l'assistente") if first_run else tr("Helpix — Impostazioni"))
        self.setMinimumWidth(560)

        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 20)
        v.setSpacing(12)
        title = QLabel("Helpix")
        title.setObjectName("setupTitle")
        v.addWidget(title)
        sub = QLabel(tr("Assistente AI per risolvere i problemi del tuo PC"))
        sub.setObjectName("meta")
        v.addWidget(sub)
        v.addSpacing(6)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(10)

        self.provider_cb = QComboBox()
        for pid, p in PROVIDERS.items():
            self.provider_cb.addItem(p["label"], pid)
        self.form.addRow(tr("Intelligenza artificiale"), self.provider_cb)

        model_row = QWidget()
        mh = QHBoxLayout(model_row)
        mh.setContentsMargins(0, 0, 0, 0)
        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        self.model_cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_cb.setToolTip(tr("Scegli dall'elenco o scrivi il nome esatto del modello"))
        mh.addWidget(self.model_cb, 1)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setText(tr("↻ Aggiorna"))
        self.refresh_btn.setToolTip(tr("Scarica dal fornitore l'elenco dei modelli disponibili per la tua chiave"))
        self.refresh_btn.clicked.connect(self._refresh_models)
        mh.addWidget(self.refresh_btn)
        self.form.addRow(tr("Modello"), model_row)

        key_row = QWidget()
        kh = QHBoxLayout(key_row)
        kh.setContentsMargins(0, 0, 0, 0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(tr("incolla qui la chiave API"))
        kh.addWidget(self.key_edit, 1)
        self.show_key = QToolButton()
        self.show_key.setText(tr("Mostra"))
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        kh.addWidget(self.show_key)
        self.form.addRow(tr("Chiave API"), key_row)
        self.key_row = key_row

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://localhost:11434/v1")
        self.form.addRow(tr("Indirizzo server"), self.url_edit)

        self.hint = QLabel()
        self.hint.setObjectName("meta")
        self.hint.setWordWrap(True)
        self.hint.setOpenExternalLinks(True)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.form.addRow("", self.hint)
        v.addLayout(self.form)

        store = QLabel(tr("🔒 Le chiavi sono salvate nel portachiavi di sistema.") if secrets.secure else
                       tr("⚠ Portachiavi di sistema non disponibile: le chiavi saranno salvate in {path} (permessi 600).").format(
                           path=f"{CONFIG_DIR}/secrets.json"))
        store.setObjectName("meta")
        store.setWordWrap(True)
        v.addWidget(store)

        self.default_cb = QCheckBox(tr("Imposta come agente predefinito"))
        self.default_cb.setChecked(True)
        v.addWidget(self.default_cb)
        self.skip_cb = QCheckBox(tr("Alle prossime aperture avvia direttamente con l'agente predefinito"))
        self.skip_cb.setChecked(bool(settings.get("skip_setup")))
        v.addWidget(self.skip_cb)

        if not first_run:
            box = QGroupBox(tr("Opzioni"))
            bf = QFormLayout(box)
            self.auto_cb = QCheckBox(tr("Dopo un comando proposto dall'IA, invia l'output e continua da solo"))
            self.auto_cb.setChecked(bool(settings.get("auto_continue", True)))
            bf.addRow(self.auto_cb)
            self.hide_cb = QCheckBox(tr("Nascondi Helpix durante lo screenshot"))
            self.hide_cb.setChecked(bool(settings.get("hide_on_screenshot", True)))
            bf.addRow(self.hide_cb)
            self.timeout_sp = QSpinBox()
            self.timeout_sp.setRange(5, 3600)
            self.timeout_sp.setSuffix(" s")
            self.timeout_sp.setValue(int(settings.get("command_timeout", 120)))
            bf.addRow(tr("Durata massima di un comando"), self.timeout_sp)
            v.addWidget(box)

        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        buttons = QHBoxLayout()
        self.test_btn = QPushButton(tr("Verifica connessione"))
        self.test_btn.clicked.connect(self._refresh_models)
        buttons.addWidget(self.test_btn)
        buttons.addStretch(1)
        cancel = QPushButton(tr("Esci") if first_run else tr("Annulla"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok_btn = QPushButton(tr("Avvia Helpix") if first_run else tr("Salva"))
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._accept)
        buttons.addWidget(self.ok_btn)
        v.addLayout(buttons)

        self.provider_cb.currentIndexChanged.connect(self._on_provider)
        start = current[0] if current else settings.get("default_provider", "anthropic")
        idx = self.provider_cb.findData(start)
        self.provider_cb.setCurrentIndex(max(idx, 0))
        self._on_provider()
        if current and current[1]:
            self.model_cb.setCurrentText(current[1])

    # --- logica -----------------------------------------------------------
    def _pid(self) -> str:
        return self.provider_cb.currentData()

    def _set_status(self, text: str, color: str | None = None):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color};" if color else "")

    def _fill_models(self, models: list[str], current: str):
        self.model_cb.clear()
        self.model_cb.addItems(models)
        self.model_cb.setCurrentText(current)

    def _on_provider(self):
        pid = self._pid()
        p = PROVIDERS[pid]
        self.form.setRowVisible(self.key_row, p["needs_key"])
        self.form.setRowVisible(self.url_edit, pid == "ollama")
        self.key_edit.setText(self.secrets.get(pid) if p["needs_key"] else "")
        self.url_edit.setText(self.settings.base_url_for(pid) or "")
        url = p["key_url"]
        if p["needs_key"]:
            self.hint.setText(tr("Non hai una chiave? Creala qui:") + f' <a href="{url}" style="color:{C["accent"]}">{url}</a>')
        else:
            self.hint.setText(tr("Nessuna chiave necessaria: i dati restano sul tuo PC. Installa Ollama ({link}) e scarica "
                                 "un modello con supporto alle immagini, ad esempio {cmd}.").format(
                link=f'<a href="{url}" style="color:{C["accent"]}">{url}</a>', cmd="<code>ollama pull llama3.2-vision</code>"))
        if not p["vision"]:
            self.hint.setText(self.hint.text() + tr("<br>Nota: questo fornitore non legge gli screenshot."))
        models = self.settings.cached_models(pid) or p["models"]
        self._fill_models(models, self.settings.model_for(pid))
        self._set_status("")

    def _base_url(self, pid: str):
        return (self.url_edit.text().strip() or None) if pid == "ollama" else self.settings.base_url_for(pid)

    def _refresh_models(self):
        pid = self._pid()
        key = self.key_edit.text().strip()
        if PROVIDERS[pid]["needs_key"] and not key:
            self._set_status(tr("Inserisci prima la chiave API."), C["warn"])
            return
        self._set_status(tr("Contatto il fornitore…"), C["muted"])
        self.test_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        worker = FuncWorker(list_models, pid, key, self._base_url(pid), parent=self)
        worker.done.connect(lambda models, pid=pid: self._models_ok(pid, models))
        worker.failed.connect(lambda exc: self._set_status(tr("Connessione non riuscita.\n{exc}").format(exc=exc), C["err"]))
        worker.finished.connect(lambda: (self.test_btn.setEnabled(True), self.refresh_btn.setEnabled(True),
                                         self._workers.discard(worker)))
        self._workers.add(worker)
        worker.start()

    def _models_ok(self, pid: str, models: list[str]):
        if pid != self._pid():
            return
        if not models:
            self._set_status(tr("Connessione riuscita, ma il fornitore non ha restituito modelli."), C["warn"])
            return
        self.settings.cache_models(pid, models)
        current = self.model_cb.currentText().strip()
        self._fill_models(models, current if current in models else models[0])
        self._set_status(tr("✓ Connessione riuscita: {n} modelli disponibili.").format(n=len(models)), C["ok"])

    def _accept(self):
        pid = self._pid()
        p = PROVIDERS[pid]
        key = self.key_edit.text().strip()
        model = self.model_cb.currentText().strip()
        if p["needs_key"] and not key:
            self._set_status(tr("Per usare questo fornitore serve una chiave API."), C["warn"])
            return
        if not model:
            self._set_status(tr("Scegli o scrivi il nome di un modello."), C["warn"])
            return
        if p["needs_key"]:
            self.secrets.set(pid, key)
        if pid == "ollama":
            self.settings.data.setdefault("base_urls", {})[pid] = self.url_edit.text().strip()
        self.settings.data.setdefault("models", {})[pid] = model
        if self.default_cb.isChecked():
            self.settings.data["default_provider"] = pid
            self.settings.data["default_model"] = model
        self.settings.data["skip_setup"] = self.skip_cb.isChecked()
        if not self.first_run:
            self.settings.data["auto_continue"] = self.auto_cb.isChecked()
            self.settings.data["hide_on_screenshot"] = self.hide_cb.isChecked()
            self.settings.data["command_timeout"] = self.timeout_sp.value()
        self.settings.save()
        self.provider, self.model = pid, model
        self.accept()

    def done(self, result):  # noqa: D401 - attende i thread prima di chiudere
        for w in list(self._workers):
            w.wait(3000)
        super().done(result)
