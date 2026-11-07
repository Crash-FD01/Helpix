# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pannello Vault (beta): progetti e note, lettura e modifica, link [[ ]], ricerca, backlink, versioni e peso del
contesto che va all'IA."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import project as pj
from ..i18n import tr
from ..icons import icon
from ..theme import C, mono_font
from ..vault import FILES, INDEX_FILE, NOTES, PROJECT_FILE, SESSIONS, VERSIONS, Vault, VaultError
from .vault_dialogs import BetaBanner

_ROLE = Qt.ItemDataRole.UserRole
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _md_links(text: str) -> str:
    """[[nota|titolo]] → link cliccabile nel pannello."""
    def repl(m):
        target, label = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        return f"[{label}](helpix:{QUrl.toPercentEncoding(target).data().decode('ascii')})"
    return _LINK.sub(repl, text)


class VaultPanel(QDialog):
    resume = Signal(str)          # riprendi il progetto (slug) in una chat nuova
    paste = Signal(str)           # incolla questo testo nella chat attiva
    lock_requested = Signal()
    export_requested = Signal()
    changed = Signal(str)         # un file del progetto (slug) è stato modificato

    def __init__(self, vault: Vault, parent=None, active: str | None = None, keep_versions: int = 20):
        super().__init__(parent)
        self.vault = vault
        self.active = active
        self.keep_versions = keep_versions
        self.current: tuple[str, str, str] | None = None   # (tipo, slug, percorso)
        self.setWindowTitle(tr("Helpix — Vault"))
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.resize(1180, 760)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)
        banner = BetaBanner()
        banner.export.connect(self.export_requested.emit)
        v.addWidget(banner)

        split = QSplitter(Qt.Orientation.Horizontal)
        v.addWidget(split, 1)

        # --- sinistra: ricerca e albero
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Cerca nel vault"))
        self.search.setAccessibleName(tr("Cerca nel vault"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search)
        lv.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._open_item(cur))
        lv.addWidget(self.tree, 1)
        bottom = QFrame()
        bottom.setObjectName("group")
        bh = QHBoxLayout(bottom)
        bh.setContentsMargins(10, 8, 10, 8)
        self.lock_label = QLabel()
        self.lock_label.setWordWrap(True)
        bh.addWidget(self.lock_label, 1)
        self.btn_lock = QPushButton(tr("Blocca"))
        self.btn_lock.clicked.connect(self.lock_requested.emit)
        bh.addWidget(self.btn_lock)
        lv.addWidget(bottom)
        split.addWidget(left)

        # --- centro: nota
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(8, 0, 8, 0)
        cv.setSpacing(8)
        self.crumb = QLabel()
        self.crumb.setObjectName("secondary")
        cv.addWidget(self.crumb)
        self.title = QLabel()
        self.title.setObjectName("heading")
        self.title.setWordWrap(True)
        cv.addWidget(self.title)
        self.meta = QLabel()
        self.meta.setObjectName("secondary")
        self.meta.setWordWrap(True)
        cv.addWidget(self.meta)
        actions = QHBoxLayout()
        self.btn_resume = QPushButton(tr("Riprendi il progetto"))
        self.btn_resume.setObjectName("primary")
        self.btn_resume.setToolTip(tr("Apre una chat nuova nell'assistente attivo con lo stato del progetto"))
        self.btn_resume.clicked.connect(lambda: self.current and self.resume.emit(self.current[1]))
        actions.addWidget(self.btn_resume)
        self.btn_paste = QPushButton(tr("Incolla nella chat"))
        self.btn_paste.setToolTip(tr("Incolla questa nota nella chat attiva (senza inviarla)"))
        self.btn_paste.clicked.connect(self._paste_current)
        actions.addWidget(self.btn_paste)
        actions.addStretch(1)
        self.btn_restore = QPushButton(tr("Ripristina questa versione"))
        self.btn_restore.clicked.connect(self._restore)
        actions.addWidget(self.btn_restore)
        self.btn_save = QPushButton(tr("Salva modifiche"))
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save)
        actions.addWidget(self.btn_save)
        seg = QFrame()
        seg.setObjectName("seg")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self.btn_read = QPushButton(tr("Leggi"))
        self.btn_edit = QPushButton(tr("Modifica"))
        group = QButtonGroup(self)
        for b in (self.btn_read, self.btn_edit):
            b.setCheckable(True)
            group.addButton(b)
            sh.addWidget(b)
        self.btn_read.setChecked(True)
        self.btn_read.toggled.connect(lambda on: on and self._mode(False))
        self.btn_edit.toggled.connect(lambda on: on and self._mode(True))
        actions.addWidget(seg)
        cv.addLayout(actions)
        self.stack = QStackedWidget()
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.editor = QPlainTextEdit()
        self.editor.setFont(mono_font())
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.editor)
        cv.addWidget(self.stack, 1)
        split.addWidget(center)

        # --- destra: contesto, backlink, note recenti
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        ctx = QFrame()
        ctx.setObjectName("group")
        xv = QVBoxLayout(ctx)
        xv.setContentsMargins(12, 10, 12, 10)
        head = QLabel(tr("Contesto per la prossima chat"))
        f = head.font()
        f.setWeight(QFont.Weight.DemiBold)
        head.setFont(f)
        xv.addWidget(head)
        self.ctx = QLabel()
        self.ctx.setWordWrap(True)
        self.ctx.setTextFormat(Qt.TextFormat.RichText)
        xv.addWidget(self.ctx)
        rv.addWidget(ctx)
        rv.addWidget(QLabel(tr("Citata da")))
        self.backlinks = QListWidget()
        self.backlinks.setMaximumHeight(130)
        self.backlinks.itemActivated.connect(lambda it: self.select(it.data(_ROLE)))
        self.backlinks.itemClicked.connect(lambda it: self.select(it.data(_ROLE)))
        rv.addWidget(self.backlinks)
        rv.addWidget(QLabel(tr("Note recenti")))
        self.recent = QListWidget()
        self.recent.itemClicked.connect(lambda it: self.select(it.data(_ROLE)))
        rv.addWidget(self.recent, 1)
        split.addWidget(right)
        split.setSizes([280, 600, 300])

        self.reload()

    # ------------------------------------------------------------ albero
    def reload(self, keep: str | None = None):
        keep = keep or (self.current[2] if self.current else None)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items: dict[str, QTreeWidgetItem] = {}
        try:
            projects = self.vault.projects()
        except VaultError:
            projects = []
        for info in projects:
            p = self.vault.project(info.slug)
            top = QTreeWidgetItem([info.name])
            top.setIcon(0, icon("folder", C["text"], 16))
            top.setData(0, _ROLE, ("project", info.slug, p.rel(PROJECT_FILE)))
            f = top.font(0)
            f.setWeight(QFont.Weight.DemiBold)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            self._add(top, "PROJECT.md", ("file", info.slug, p.rel(PROJECT_FILE)), "star")
            self._add(top, "INDEX.md", ("file", info.slug, p.rel(INDEX_FILE)), "list")
            notes = p.notes()
            if notes:
                folder = self._add(top, tr("note ({n})").format(n=len(notes)), None, "folder")
                for n in reversed(notes):
                    self._add(folder, f"{n.date} · {n.title}" if n.date else n.title, ("file", info.slug, n.rel))
            for sub, label in ((FILES, tr("file ({n})")), (SESSIONS, tr("sessioni ({n})"))):
                rels = self.vault.store.list(p.rel(sub) + "/")
                if rels:
                    folder = self._add(top, label.format(n=len(rels)), None, "folder")
                    for rel in reversed(rels) if sub == SESSIONS else rels:
                        self._add(folder, rel[len(p.rel(sub)) + 1:], ("file", info.slug, rel))
            versions = p.versions()
            if versions:
                folder = self._add(top, tr("versioni ({n})").format(n=len(versions)), None, "refresh")
                for rel in versions:
                    stamp = re.search(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", rel)
                    label = (f"{stamp.group(3)}/{stamp.group(2)}/{stamp.group(1)} {stamp.group(4)}:{stamp.group(5)}"
                             if stamp else rel.rsplit("/", 1)[1])
                    self._add(folder, label, ("version", info.slug, rel))
            top.setExpanded(info.slug == self.active or len(projects) == 1)
        if not projects:
            empty = QTreeWidgetItem([tr("Nessun progetto: creane uno dal selettore Progetto.")])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        self.tree.blockSignals(False)
        enc = self.vault.encrypted
        self.lock_label.setText(tr("Vault cifrato, aperto. Si blocca insieme a Helpix.") if enc
                                else tr("Vault non cifrato (Markdown in chiaro)."))
        self.btn_lock.setVisible(enc)
        target = keep if keep in self._items else (projects and self._first_rel(projects))
        if target:
            self.select(target)
        else:
            self._show_none()

    def _first_rel(self, projects) -> str:
        slug = self.active if any(p.slug == self.active for p in projects) else projects[0].slug
        return self.vault.project(slug).rel(PROJECT_FILE)

    def _add(self, parent, label, data, icon_name: str | None = None) -> QTreeWidgetItem:
        it = QTreeWidgetItem([label])
        if icon_name:
            it.setIcon(0, icon(icon_name, C["secondary"], 15))
        it.setData(0, _ROLE, data)
        if data is None:
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        parent.addChild(it)
        if data and data[0] in ("file", "version"):
            self._items.setdefault(data[2], it)
        return it

    def select(self, rel: str | None):
        if not rel:
            return
        it = self._items.get(rel)
        if it is None:
            self.reload(keep=rel)
            it = self._items.get(rel)
        if it is not None:
            p = it.parent()
            while p:
                p.setExpanded(True)
                p = p.parent()
            self.tree.setCurrentItem(it)

    # ------------------------------------------------------------ contenuto
    def _open_item(self, item):
        data = item.data(0, _ROLE) if item else None
        if not data:
            return
        if self.stack.currentIndex() == 1 and self.current and self.editor.document().isModified():
            if QMessageBox.question(self, tr("Vault"), tr("Le modifiche non salvate andranno perse. Continuare?")) != \
                    QMessageBox.StandardButton.Yes:
                return
        kind, slug, rel = data
        if kind == "project":  # la riga del progetto apre PROJECT.md
            kind = "file"
        self.current = (kind, slug, rel)
        p = self.vault.project(slug)
        try:
            text = p.read_text(rel)
        except KeyError:
            text = ""
        tail = rel[len(p.rel()) + 1:]
        self.crumb.setText(f"{self.vault.name} / {p.name} / {tail}")
        name = rel.rsplit("/", 1)[1]
        is_project = name == PROJECT_FILE and f"/{VERSIONS}/" not in rel
        self.title.setText(p.name if is_project else (pj.title_of(text) or name))
        if is_project:
            n = pj.estimate_tokens(pj.strip_private(text))
            self.meta.setText(tr("Stato del progetto · inviato all'IA a ogni chat nuova (senza «Solo per me») · "
                                 "~{n} / {limit} token").format(n=n, limit=pj.TOKEN_LIMIT))
        elif kind == "version":
            self.meta.setText(tr("Versione precedente di PROJECT.md"))
        elif f"/{SESSIONS}/" in rel:
            self.meta.setText(tr("Bozza automatica della sessione: non viene inviata all'IA"))
        elif f"/{NOTES}/" in rel:
            self.meta.setText(tr("Nota · l'IA la riceve solo se la chiede (HELPIX-NOTA) o se la incolli tu"))
        else:
            self.meta.setText("")
        self.view.setMarkdown(_md_links(text))
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        editable = kind == "file"
        self.btn_edit.setEnabled(editable)
        self.btn_restore.setVisible(kind == "version")
        self.btn_paste.setVisible(f"/{NOTES}/" in rel or f"/{FILES}/" in rel)
        self.btn_resume.setEnabled(True)
        self.btn_read.setChecked(True)
        self._mode(False)
        self._side(p, rel)

    def _show_none(self):
        self.current = None
        for w in (self.crumb, self.title, self.meta, self.ctx):
            w.setText("")
        self.view.setMarkdown("")
        for b in (self.btn_resume, self.btn_paste, self.btn_edit):
            b.setEnabled(False)
        self.btn_restore.hide()
        self.btn_save.hide()
        self.backlinks.clear()
        self.recent.clear()

    def _mode(self, edit: bool):
        self.stack.setCurrentIndex(1 if edit else 0)
        self.btn_save.setVisible(edit)
        if not edit and self.current:
            self.view.setMarkdown(_md_links(self.editor.toPlainText()))

    def _side(self, p, rel: str):
        text = p.text()
        recent = pj.recent_index_lines(p.index_text())
        n_project = pj.estimate_tokens(pj.strip_private(text))
        n_recent = pj.estimate_tokens("\n".join(recent))
        total = pj.estimate_tokens(pj.context_text(p.name, text, p.index_text()))
        warn = f" <span style='color:{C['warnText']}'>{tr('oltre il limite: compatta il progetto')}</span>" \
            if n_project > pj.TOKEN_LIMIT else ""
        self.ctx.setText(
            f"PROJECT.md: ~{n_project}{warn}<br>"
            + tr("Ultime {k} righe dell'indice: ~{n}").format(k=len(recent), n=n_recent) + "<br>"
            + f"<span style='color:{C['secondary']}'>" + tr("«Solo per me»: esclusa") + "</span><br>"
            + "<b>" + tr("Totale con le istruzioni: ~{n} token").format(n=total) + "</b><br>"
            + f"<span style='color:{C['secondary']}'>"
            + tr("Le altre note restano fuori: l'IA le chiede quando servono.") + "</span>")
        self.backlinks.clear()
        for other in p.backlinks(rel):
            it = QListWidgetItem(other[len(p.rel()) + 1:])
            it.setData(_ROLE, other)
            self.backlinks.addItem(it)
        if not self.backlinks.count():
            it = QListWidgetItem(tr("Nessuna"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.backlinks.addItem(it)
        self.recent.clear()
        notes = p.notes()
        in_ctx = {n.rel for n in notes[-pj.RECENT_NOTES:]}
        for n in reversed(notes[-12:]):
            badge = tr("nel contesto") if n.rel in in_ctx else tr("archivio")
            it = QListWidgetItem(f"{n.date[8:10]}/{n.date[5:7]}  {n.title}  · {badge}" if n.date else n.title)
            it.setData(_ROLE, n.rel)
            self.recent.addItem(it)

    # ------------------------------------------------------------ azioni
    def _link(self, url: QUrl):
        if url.scheme() == "helpix" and self.current:
            p = self.vault.project(self.current[1])
            target = p.resolve(QUrl.fromPercentEncoding(url.path().encode("utf-8")))
            if target:
                self.select(target)
            else:
                QMessageBox.information(self, tr("Vault"), tr("Nota non trovata: {name}").format(name=url.path()))
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _paste_current(self):
        if not self.current:
            return
        p = self.vault.project(self.current[1])
        text = p.read_text(self.current[2])
        self.paste.emit(pj.note_paste(pj.title_of(text) or self.current[2].rsplit("/", 1)[1], text))

    def _save(self):
        if not self.current or self.current[0] != "file":
            return
        kind, slug, rel = self.current
        p = self.vault.project(slug)
        text = self.editor.toPlainText().rstrip("\n") + "\n"
        try:
            if rel == p.rel(PROJECT_FILE):
                p.save_text(text, keep=self.keep_versions)
            else:
                p.write_text(rel, text)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Vault"), tr("Salvataggio non riuscito: {exc}").format(exc=exc))
            return
        self.editor.document().setModified(False)
        self.changed.emit(slug)
        self.reload(keep=rel)

    def _restore(self):
        if not self.current or self.current[0] != "version":
            return
        _kind, slug, rel = self.current
        if QMessageBox.question(self, tr("Vault"), tr("Ripristinare questa versione di PROJECT.md? Quella attuale resta "
                                                      "tra le versioni.")) != QMessageBox.StandardButton.Yes:
            return
        p = self.vault.project(slug)
        p.restore_version(rel)
        self.changed.emit(slug)
        self.reload(keep=p.rel(PROJECT_FILE))

    def _search(self, text: str):
        text = text.strip()
        if not text:
            self.reload()
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        try:
            projects = self.vault.projects()
        except VaultError:
            projects = []
        found = 0
        for info in projects:
            p = self.vault.project(info.slug)
            hits = p.search(text)
            if not hits:
                continue
            top = QTreeWidgetItem([info.name])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for rel, line in hits:
                label = f"{rel[len(p.rel()) + 1:]}: {line[:80]}"
                it = QTreeWidgetItem([label])
                it.setData(0, _ROLE, ("file", info.slug, rel))
                top.addChild(it)
                self._items.setdefault(rel, it)
                found += 1
            top.setExpanded(True)
        if not found:
            empty = QTreeWidgetItem([tr("Nessun risultato.")])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        self.tree.blockSignals(False)
