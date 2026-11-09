# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pannello Vault (beta): progetti e note, lettura e modifica, link [[ ]], ricerca, backlink, versioni e peso del
contesto che va all'IA. Tre colonne: vault a sinistra, nota al centro, contesto e collegamenti a destra."""
from __future__ import annotations

import html
import re

import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTextBrowser, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import project as pj, theme
from ..i18n import tr
from ..icons import icon
from ..theme import C, mono_font
from ..vault import FILES, INDEX_FILE, NOTES, PROJECT_FILE, SESSIONS, VERSIONS, Vault, VaultError
from .controls import WindowControls
from .frameless import FramelessHelper, RoundedCentral
from .vault_dialogs import ISSUES_URL
from .vault_graph import GraphPage

_ROLE = Qt.ItemDataRole.UserRole
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MDLINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.*)$")


# ------------------------------------------------------------------ Markdown → HTML (quello che serve alle note)
def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?!\w)", r"<i>\1</i>", out)
    out = re.sub(r"(?<![\w_])_([^_\s][^_]*)_(?!\w)", r"<i>\1</i>", out)

    def wiki(m):
        target, label = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        href = "helpix:" + QUrl.toPercentEncoding(html.unescape(target)).data().decode("ascii")
        return f'<a href="{href}">{label}</a>'
    out = _LINK.sub(wiki, out)
    out = _MDLINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    return out


def markdown_html(text: str) -> str:
    """Titoli, paragrafi, elenchi, blocchi di codice, `codice`, grassetto, corsivo, link [[ ]] e [x](url)."""
    out: list[str] = []
    para: list[str] = []
    lst: str | None = None
    code: list[str] | None = None

    def flush():
        nonlocal lst
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()
        if lst:
            out.append(f"</{lst}>")
            lst = None

    for line in (text or "").splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
                code = None
            else:
                code.append(line)
            continue
        s = line.strip()
        if s.startswith("```"):
            flush()
            code = []
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush()
            out.append(_heading(_inline(m.group(2)), 15 if len(m.group(1)) <= 2 else 14))
            continue
        bullet = re.match(r"^[-*•]\s+(.*)$", s)
        number = re.match(r"^\d+[.)]\s+(.*)$", s)
        if bullet or number:
            kind = "ul" if bullet else "ol"
            if para:
                out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
                para.clear()
            if lst != kind:
                if lst:
                    out.append(f"</{lst}>")
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{_inline((bullet or number).group(1))}</li>")
            continue
        if s.startswith(">"):
            flush()
            out.append(f'<p class="quote">{_inline(s.lstrip("> "))}</p>')
            continue
        if not s:
            flush()
            continue
        if lst:
            out.append(f"</{lst}>")
            lst = None
        para.append(s)
    if code is not None:
        out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
    flush()
    return "\n".join(out)


def _heading(inner: str, size: int = 15) -> str:
    return (f'<p style="font-size:{size}px; font-weight:600; margin-top:16px; margin-bottom:4px;">{inner}</p>')


def _chip(text: str, fg: str, bg: str) -> str:
    return (f'<span style="background-color:{bg}; color:{fg}; font-size:11px; font-weight:600;">'
            f"&nbsp;{html.escape(text)}&nbsp;</span>")


def project_html(text: str) -> str:
    """PROJECT.md con le decisioni «in vigore» e la sezione «Solo per me» messa in evidenza (mai inviata)."""
    doc = pj.parse(text)
    out: list[str] = []
    for title, lines in doc.sections:
        key = pj.section_key(title)
        body = "\n".join(lines).strip()
        if key == "private":
            chip = _chip(tr("mai inviata all'IA"), C["warnText"], C["warnBg"])
            inner = markdown_html(body) if body else f'<p class="muted">{tr("Vuota.")}</p>'
            out.append(f'<p style="margin-top:20px;"></p><table width="100%" cellpadding="12" cellspacing="0" '
                       f'border="0" style="background-color:{C["segBg"]};"><tr><td>'
                       f'<p style="font-size:15px; font-weight:600; margin:0;">{html.escape(title)}&nbsp;&nbsp;{chip}</p>'
                       f"{inner}</td></tr></table>")
            continue
        out.append(_heading(html.escape(title)))
        if key == "decisions":
            rows = []
            for ln in lines:
                s = re.sub(r"^\s*[-*•]\s+", "", ln).strip()
                if not s:
                    continue
                m = _DATE.match(s)
                date, what = (m.group(1), m.group(2)) if m else ("", s)
                rows.append(f'<tr><td class="date" width="92">{date}</td><td>{_inline(what)}</td>'
                            f'<td align="right" width="80">{_chip(tr("in vigore"), C["okText"], C["okBg"])}</td></tr>')
            out.append('<table class="decisions" width="100%" cellspacing="0" cellpadding="5">' + "".join(rows)
                       + "</table>" if rows else f'<p class="muted">{tr("Nessuna decisione ancora.")}</p>')
            continue
        out.append(markdown_html(body) if body and body != "-" else f'<p class="muted">{tr("Vuota.")}</p>')
    return "\n".join(out)


def _css() -> str:
    return f"""
    body {{ color: {C['text']}; font-size: 14px; }}
    p {{ margin-top: 2px; margin-bottom: 8px; }}
    li {{ margin-bottom: 3px; }}
    a {{ color: {C['accentFg']}; text-decoration: none; }}
    code {{ font-family: 'JetBrains Mono', monospace; background-color: {C['code']}; }}
    pre {{ font-family: 'JetBrains Mono', monospace; background-color: {C['code']}; padding: 10px; }}
    .muted {{ color: {C['secondary']}; }}
    .quote {{ color: {C['secondary']}; }}
    td.date {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: {C['secondary']}; }}
    """


def _panel_qss() -> str:
    return f"""
    QDialog#vaultPanel[rounded="true"] {{ background: transparent; }}
    #vaultSide, #vaultAside {{ background: {C['sidebar']}; }}
    #vaultSide {{ border-right: 1px solid {C['hairline']}; }}
    #vaultAside {{ border-left: 1px solid {C['hairline']}; }}
    #vaultMain {{ background: {C['page']}; }}
    #vaultSideTitle {{ font-weight: 600; font-size: 14px; }}
    #vaultSection {{ color: {C['secondary']}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
    #vaultCard {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
    #vaultBeta {{ background: {C['warnBg']}; border-bottom: 1px solid {C['hairline']}; }}
    #vaultBeta QLabel {{ color: {C['warnText']}; }}
    #vaultBeta QPushButton {{ background: transparent; border: none; color: {C['warnText']};
                              text-decoration: underline; padding: 2px 6px; min-height: 22px; }}
    #vaultCrumb {{ color: {C['secondary']}; font-size: 12px; }}
    #vaultTitle {{ font-size: 24px; font-weight: 700; }}
    #vaultMeta {{ color: {C['secondary']}; font-size: 13px; }}
    #vaultTokens {{ color: {C['secondary']}; font-family: 'JetBrains Mono', monospace; font-size: 12px; }}
    #vaultRule {{ background: {C['hairline']}; max-height: 1px; min-height: 1px; }}
    QTreeWidget#vaultTree, QListWidget#vaultList {{ background: transparent; border: none; outline: 0; }}
    QTreeWidget#vaultTree::item {{ min-height: 28px; padding-left: 2px; background: transparent; border: none; }}
    QTreeWidget#vaultTree::item:hover, QTreeWidget#vaultTree::item:selected {{ background: transparent; }}
    QTreeWidget#vaultTree {{ show-decoration-selected: 0; selection-background-color: transparent; }}
    QListWidget#vaultList::item {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 8px;
                                   margin: 2px 0; padding: 0 8px; min-height: 34px; }}
    QListWidget#vaultList::item:hover {{ background: {C['hover']}; }}
    QListWidget#vaultList::item:selected {{ background: {C['tint']}; color: {C['text']}; }}
    QTextBrowser#vaultView {{ background: transparent; border: none; }}
    QPlainTextEdit#vaultEditor {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px;
                                  padding: 10px; }}
    QProgressBar#vaultMeter {{ background: {C['segBg']}; border: none; border-radius: 3px; }}
    QProgressBar#vaultMeter::chunk {{ background: {C['ok']}; border-radius: 3px; }}
    QProgressBar#vaultMeter[over="true"]::chunk {{ background: {C['warn']}; }}
    """


def _bold(label: QLabel) -> QLabel:
    f = label.font()
    f.setWeight(QFont.Weight.DemiBold)
    label.setFont(f)
    return label


class VaultPanel(QDialog):
    resume = Signal(str)          # riprendi il progetto (slug) in una chat nuova
    paste = Signal(str)           # incolla questo testo nella chat attiva
    lock_requested = Signal()
    export_requested = Signal()
    tour_requested = Signal()     # giro guidato del pannello
    changed = Signal(str)         # un file del progetto (slug) è stato modificato
    project_deleted = Signal(str)  # progetto (slug) spostato nel cestino
    project_restored = Signal(str)

    def __init__(self, vault: Vault, parent=None, active: str | None = None, keep_versions: int = 20,
                 assistant=None, frameless: bool = False, rounded: bool = False):
        """Finestra indipendente (parent=None): non resta sopra a Helpix e ha la sua voce nella barra delle
        applicazioni. Con `frameless` usa la barra integrata di Helpix invece di quella del sistema."""
        super().__init__(parent)
        self.vault = vault
        self.active = active
        self.keep_versions = keep_versions
        self.assistant = assistant or (lambda: "")
        self.current: tuple[str, str, str] | None = None   # (tipo, slug, percorso)
        self._items: dict[str, QTreeWidgetItem] = {}
        self.frameless = frameless
        self.rounded = frameless and rounded
        self.setObjectName("vaultPanel")
        self.setWindowTitle(tr("Helpix — Vault"))
        from ..theme import app_icon
        self.setWindowIcon(app_icon())
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.setMinimumSize(820, 540)
        self._fit_to_screen(parent)
        self.setStyleSheet(_panel_qss())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_side())
        body.addWidget(self._build_main(), 1)
        body.addWidget(self._build_aside())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        if frameless:
            self.toolbar = self._build_titlebar()
            if self.rounded:
                # finestra trasparente: lo sfondo con gli angoli arrotondati lo dipinge RoundedCentral, come in Helpix
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setProperty("rounded", "true")
                self.toolbar.setProperty("rounded", "true")
                self.central = RoundedCentral(self.toolbar)
            else:
                self.central = QWidget()
            self.central.setObjectName("central")
            self.central.setProperty("frameless", "true")
            self.central.setProperty("rounded", "true" if self.rounded else "false")
            cl = QVBoxLayout(self.central)
            cl.setContentsMargins(1, 1, 1, 1)
            cl.setSpacing(0)
            cl.addWidget(self.toolbar)
            cl.addLayout(body, 1)
            outer.addWidget(self.central)
            if self.rounded:
                self.central.set_square(False)
            self._frameless = FramelessHelper(self, self.toolbar)
        else:
            outer.addLayout(body, 1)
        self.reload()

    def _fit_to_screen(self, parent):
        """Grande quanto serve ma mai più dello schermo (prima la colonna di destra poteva finire fuori)."""
        from PySide6.QtGui import QGuiApplication
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        w, h = 1240, 800
        if avail is not None:
            w = max(self.minimumWidth(), min(w, int(avail.width() * 0.94)))
            h = max(self.minimumHeight(), min(h, int(avail.height() * 0.92)))
        self.resize(w, h)
        if avail is not None:
            center = parent.geometry().center() if parent is not None and parent.isVisible() else avail.center()
            x = min(max(center.x() - w // 2, avail.left()), avail.right() - w)
            y = min(max(center.y() - h // 2, avail.top()), avail.bottom() - h)
            self.move(max(x, avail.left()), max(y, avail.top()))

    def _build_titlebar(self) -> QFrame:
        """Barra integrata come quella di Helpix: icona, titolo, riduci / ingrandisci / chiudi; si trascina."""
        from ..theme import app_icon
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar.setFixedHeight(46)
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 10, 0)
        h.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(20, 20))
        h.addWidget(logo)
        self.bar_title = _bold(QLabel(tr("Helpix — Vault")))
        h.addWidget(self.bar_title)
        h.addStretch(1)
        self.win_controls = WindowControls(self)
        h.addWidget(self.win_controls)
        return bar

    ASIDE_MIN_WIDTH = 1120   # sotto questa larghezza la colonna di destra si nasconde: la nota resta leggibile

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.aside.setVisible(self.width() >= self.ASIDE_MIN_WIDTH)

    def changeEvent(self, ev):
        if ev.type() == QEvent.Type.WindowStateChange and self.frameless:
            maxed = self.isMaximized() or self.isFullScreen()
            self.central.setProperty("frameless", "false" if maxed else "true")
            if self.rounded:
                self.central.set_square(maxed)  # ingrandita: angoli dritti, niente margini
            else:
                self.central.layout().setContentsMargins(*(0 if maxed else 1,) * 4)
            self.central.style().unpolish(self.central)
            self.central.style().polish(self.central)
            self.win_controls.refresh()
        super().changeEvent(ev)

    # ------------------------------------------------------------ costruzione
    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("vaultSide")
        side.setFixedWidth(270)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(10)
        head = QHBoxLayout()
        self.side_icon = QLabel()
        head.addWidget(self.side_icon)
        self.side_title = QLabel()
        self.side_title.setObjectName("vaultSideTitle")
        head.addWidget(self.side_title, 1)
        v.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Cerca nel vault"))
        self.search.setAccessibleName(tr("Cerca nel vault"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", C["secondary"], 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._search)
        v.addWidget(self.search)
        section = QLabel(tr("PROGETTI"))
        section.setObjectName("vaultSection")
        v.addWidget(section)
        self.tree = _Tree()
        self.tree.setObjectName("vaultTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setExpandsOnDoubleClick(False)  # un clic apre e chiude (vedi _item_clicked)
        self.tree.setMouseTracking(True)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.setIconSize(QSize(15, 15))
        self.tree.setAccessibleName(tr("Progetti e note"))
        self.tree.setItemDelegate(_NoFocusDelegate(self.tree))
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.currentItemChanged.connect(self._item_changed)
        v.addWidget(self.tree, 1)
        self.lock_card = QFrame()
        self.lock_card.setObjectName("vaultCard")
        ch = QHBoxLayout(self.lock_card)
        ch.setContentsMargins(10, 8, 8, 8)
        ch.setSpacing(8)
        self.lock_icon = QLabel()
        ch.addWidget(self.lock_icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.lock_title = _bold(QLabel())
        self.lock_text = QLabel()
        self.lock_text.setObjectName("secondary")
        self.lock_text.setWordWrap(True)
        texts.addWidget(self.lock_title)
        texts.addWidget(self.lock_text)
        ch.addLayout(texts, 1)
        self.btn_lock = QPushButton(tr("Blocca"))
        self.btn_lock.clicked.connect(self.lock_requested.emit)
        ch.addWidget(self.btn_lock, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(self.lock_card)
        return side

    def _build_main(self) -> QWidget:
        main = QFrame()
        main.setObjectName("vaultMain")
        v = QVBoxLayout(main)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        beta = QFrame()
        beta.setObjectName("vaultBeta")
        bh = QHBoxLayout(beta)
        bh.setContentsMargins(16, 6, 10, 6)
        bh.setSpacing(6)
        msg = QLabel("<b>" + tr("Beta") + "</b> · " + tr("Progetti e vault sono in prova: tieni una copia dei dati "
                                                           "importanti."))
        msg.setWordWrap(True)
        msg.setMinimumWidth(120)
        bh.addWidget(msg, 1)
        for label, slot in ((tr("Esporta in chiaro"), self.export_requested.emit),
                            (tr("Segnala un problema"), lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL))),
                            (tr("Guida"), self.tour_requested.emit)):
            b = QPushButton(label)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # mai tagliati
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            bh.addWidget(b)
        self.btn_guide = b
        v.addWidget(beta)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(32, 18, 32, 16)
        bv.setSpacing(6)
        self.crumb = QLabel()
        self.crumb.setObjectName("vaultCrumb")
        bv.addWidget(self.crumb)
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("vaultTitle")
        self.title.setWordWrap(True)
        title_row.addWidget(self.title, 1)
        self.seg = QFrame()
        self.seg.setObjectName("seg")
        sh = QHBoxLayout(self.seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self.btn_read = QToolButton()
        self.btn_read.setText(tr("Leggi"))
        self.btn_edit = QToolButton()
        self.btn_edit.setText(tr("Modifica"))
        self.btn_graph = QToolButton()
        self.btn_graph.setText(tr("Grafo"))
        self.btn_graph.setToolTip(tr("La mappa delle decisioni: quando sono nate, quali sono superate e da cosa, lo stato e i prossimi passi"))
        group = QButtonGroup(self)
        for b in (self.btn_read, self.btn_edit, self.btn_graph):
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b)
            sh.addWidget(b)
        self.btn_read.setChecked(True)
        self.btn_read.toggled.connect(lambda on: on and self._mode(False))
        self.btn_edit.toggled.connect(lambda on: on and self._mode(True))
        self.btn_graph.toggled.connect(lambda on: on and self._show_graph())
        self.seg.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for b in (self.btn_read, self.btn_edit, self.btn_graph):
            b.setMinimumWidth(b.sizeHint().width() + 16)
        title_row.addWidget(self.seg, 0, Qt.AlignmentFlag.AlignBottom)
        self.btn_more = QToolButton()
        self.btn_more.setIcon(icon("more", C["text"], 18))
        self.btn_more.setIconSize(QSize(18, 18))
        self.btn_more.setToolTip(tr("Altre azioni: rinomina, elimina…"))
        self.btn_more.setAccessibleName(tr("Altre azioni"))
        self.btn_more.setObjectName("iconBtn")
        self.btn_more.setFixedSize(34, 34)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.more_menu = theme.prepare_menu(QMenu(self))
        self.more_menu.aboutToShow.connect(lambda: self._fill_menu(self.more_menu, self.current))
        self.btn_more.setMenu(self.more_menu)
        title_row.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignBottom)
        bv.addLayout(title_row)
        self.meta = QLabel()
        self.meta.setObjectName("vaultMeta")
        self.meta.setWordWrap(True)
        bv.addWidget(self.meta)
        bv.addSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_resume = QPushButton()
        self.btn_resume.setObjectName("primary")
        self.btn_resume.setToolTip(tr("Apre una chat nuova nell'assistente attivo con lo stato del progetto"))
        self.btn_resume.clicked.connect(lambda: self.current and self.resume.emit(self.current[1]))
        actions.addWidget(self.btn_resume)
        self.btn_paste = QPushButton(tr("Incolla nella chat"))
        self.btn_paste.setToolTip(tr("Incolla questa nota nella chat attiva (senza inviarla)"))
        self.btn_paste.clicked.connect(self._paste_current)
        actions.addWidget(self.btn_paste)
        self.btn_restore = QPushButton(tr("Ripristina questa versione"))
        self.btn_restore.clicked.connect(self._restore)
        actions.addWidget(self.btn_restore)
        self.btn_untrash = QPushButton(tr("Ripristina"))
        self.btn_untrash.setObjectName("primary")
        self.btn_untrash.clicked.connect(lambda: self.current and self._untrash(self.current[1]))
        actions.addWidget(self.btn_untrash)
        self.btn_purge = QPushButton(tr("Elimina definitivamente"))
        self.btn_purge.setObjectName("danger")
        self.btn_purge.clicked.connect(lambda: self.current and self._purge(self.current[1]))
        actions.addWidget(self.btn_purge)
        actions.addStretch(1)
        self.meter_box = QWidget()
        mh = QHBoxLayout(self.meter_box)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(10)
        self.meter = QProgressBar()
        self.meter.setObjectName("vaultMeter")
        self.meter.setTextVisible(False)
        self.meter.setFixedSize(120, 6)
        self.meter.setRange(0, pj.TOKEN_LIMIT)
        mh.addWidget(self.meter)
        self.tokens = QLabel()
        self.tokens.setObjectName("vaultTokens")
        mh.addWidget(self.tokens)
        actions.addWidget(self.meter_box)
        for b in (self.btn_resume, self.btn_paste, self.btn_restore, self.btn_untrash, self.btn_purge):
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.meter_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        bv.addLayout(actions)
        bv.addSpacing(10)
        rule = QFrame()
        rule.setObjectName("vaultRule")
        bv.addWidget(rule)
        self.stack = QStackedWidget()
        self.view = QTextBrowser()
        self.view.setObjectName("vaultView")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.document().setDocumentMargin(4)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("vaultEditor")
        self.editor.setFont(mono_font())
        self.editor.setAccessibleName(tr("Testo della nota"))
        edit_page = QWidget()
        ev = QVBoxLayout(edit_page)
        ev.setContentsMargins(0, 12, 0, 0)
        ev.setSpacing(8)
        ev.addWidget(self.editor, 1)
        er = QHBoxLayout()
        er.addStretch(1)
        self.btn_cancel = QPushButton(tr("Annulla le modifiche"))
        self.btn_cancel.clicked.connect(self._cancel_edit)
        er.addWidget(self.btn_cancel)
        self.btn_save = QPushButton(tr("Salva modifiche"))
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save)
        er.addWidget(self.btn_save)
        ev.addLayout(er)
        self.graph_page = GraphPage()
        self.graph_page.activated.connect(self._graph_open)
        theme.manager().changed.connect(lambda _d: self.graph_page.refresh_theme())
        self.stack.addWidget(self.view)
        self.stack.addWidget(edit_page)
        self.stack.addWidget(self.graph_page)
        bv.addWidget(self.stack, 1)
        v.addWidget(body, 1)
        return main

    def _build_aside(self) -> QWidget:
        aside = QFrame()
        aside.setObjectName("vaultAside")
        aside.setFixedWidth(300)
        self.aside = aside
        v = QVBoxLayout(aside)
        v.setContentsMargins(14, 16, 14, 14)
        v.setSpacing(8)
        self.ctx_card = QFrame()
        self.ctx_card.setObjectName("vaultCard")
        cv = QVBoxLayout(self.ctx_card)
        cv.setContentsMargins(12, 10, 12, 12)
        cv.setSpacing(6)
        cv.addWidget(_bold(QLabel(tr("Contesto per la prossima chat"))))
        self.ctx_rows = QVBoxLayout()
        self.ctx_rows.setSpacing(4)
        cv.addLayout(self.ctx_rows)
        self.ctx_note = QLabel(tr("Le altre note restano fuori: l'IA le chiede quando servono."))
        self.ctx_note.setObjectName("secondary")
        self.ctx_note.setWordWrap(True)
        cv.addWidget(self.ctx_note)
        v.addWidget(self.ctx_card)
        v.addSpacing(6)
        self.lab_links = _bold(QLabel(tr("Citata da")))
        v.addWidget(self.lab_links)
        self.backlinks = QListWidget()
        self.backlinks.setObjectName("vaultList")
        self.backlinks.setFrameShape(QFrame.Shape.NoFrame)
        self.backlinks.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.backlinks.itemClicked.connect(lambda it: it.data(_ROLE) and self.select(it.data(_ROLE)))
        v.addWidget(self.backlinks)
        v.addSpacing(6)
        self.lab_recent = _bold(QLabel(tr("Note recenti")))
        v.addWidget(self.lab_recent)
        self.recent = QListWidget()
        self.recent.setObjectName("vaultList")
        self.recent.setFrameShape(QFrame.Shape.NoFrame)
        self.recent.itemClicked.connect(lambda it: it.data(_ROLE) and self.select(it.data(_ROLE)))
        v.addWidget(self.recent, 1)
        return aside

    # ------------------------------------------------------------ albero
    def reload(self, keep: str | None = None):
        keep = keep or (self.current[2] if self.current else None)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        try:
            projects = self.vault.projects()
        except VaultError:
            projects = []
        for info in projects:
            p = self.vault.project(info.slug)
            top = QTreeWidgetItem([info.name])
            top.setIcon(0, icon("folder", C["accentFg"] if info.slug == self.active else C["secondary"], 16))
            top.setData(0, _ROLE, ("project", info.slug, p.rel(PROJECT_FILE)))
            _bold_item(top)
            self.tree.addTopLevelItem(top)
            self._add(top, "PROJECT.md", ("file", info.slug, p.rel(PROJECT_FILE)), "star")
            self._add(top, "INDEX.md", ("file", info.slug, p.rel(INDEX_FILE)), "list")
            notes = p.notes()
            if notes:
                folder = self._add(top, tr("note ({n})").format(n=len(notes)), None, "folder")
                for n in reversed(notes):
                    self._add(folder, f"{n.date} · {n.title}" if n.date else n.title, ("file", info.slug, n.rel), "file")
            for sub, label in ((FILES, tr("file ({n})")), (SESSIONS, tr("sessioni ({n})"))):
                rels = self.vault.store.list(p.rel(sub) + "/")
                if rels:
                    folder = self._add(top, label.format(n=len(rels)), None, "folder")
                    for rel in (reversed(rels) if sub == SESSIONS else rels):
                        self._add(folder, rel[len(p.rel(sub)) + 1:], ("file", info.slug, rel), "file")
            versions = p.versions()
            if versions:
                folder = self._add(top, tr("versioni ({n})").format(n=len(versions)), None, "refresh")
                for rel in versions:
                    stamp = re.search(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", rel)
                    label = (f"{stamp.group(3)}/{stamp.group(2)}/{stamp.group(1)} {stamp.group(4)}:{stamp.group(5)}"
                             if stamp else rel.rsplit("/", 1)[1])
                    self._add(folder, label, ("version", info.slug, rel), "refresh")
            top.setExpanded(info.slug == self.active or len(projects) == 1)
        if not projects:
            empty = QTreeWidgetItem([tr("Nessun progetto: creane uno dal selettore Progetto.")])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        try:
            trash = self.vault.trash()
        except VaultError:
            trash = []
        if trash:
            bin_item = QTreeWidgetItem([tr("Cestino ({n})").format(n=len(trash))])
            bin_item.setIcon(0, icon("trash", C["secondary"], 16))
            bin_item.setData(0, _ROLE, ("bin", "", ""))
            self.tree.addTopLevelItem(bin_item)
            for t in trash:
                label = t.name + "  · " + time.strftime("%d/%m %H:%M", time.localtime(t.deleted))
                it = QTreeWidgetItem([label])
                it.setIcon(0, icon("folder" if t.kind == "project" else "file", C["secondary"], 15))
                preview = next((f for f in t.files if f.endswith("/" + PROJECT_FILE) and f.count("/") == 4),
                               next((f for f in t.files if f.endswith(".md")), t.files[0]))
                it.setData(0, _ROLE, ("trash", t.id, preview))
                it.setToolTip(0, tr("Progetto eliminato") if t.kind == "project" else tr("Nota eliminata"))
                bin_item.addChild(it)
                self._items.setdefault("trash:" + t.id, it)
            bin_item.setExpanded(keep is not None and keep.startswith("trash:"))
        self.tree.blockSignals(False)
        self._update_lock_card()
        target = keep if keep in self._items else (projects and self._first_rel(projects))
        if target:
            self.select(target)
        else:
            self._show_none()

    def _update_lock_card(self):
        enc = self.vault.encrypted
        self.side_title.setText(tr("Vault «{name}»").format(name=self.vault.name))
        self.side_icon.setPixmap(icon("lock" if enc else "folder", C["secondary"], 16).pixmap(16, 16))
        self.lock_icon.setPixmap(icon("unlock" if enc else "folder", C["okText"] if enc else C["secondary"],
                                      16).pixmap(16, 16))
        self.lock_title.setText(tr("Vault sbloccato") if enc else tr("Vault non cifrato"))
        self.lock_text.setText(tr("Si blocca insieme a Helpix.") if enc else tr("File Markdown in chiaro."))
        self.btn_lock.setVisible(enc)

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
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.reload(keep=rel)
            it = self._items.get(rel)
        if it is not None:
            p = it.parent()
            while p:
                p.setExpanded(True)
                p = p.parent()
            self.tree.setCurrentItem(it)

    # ------------------------------------------------------------ contenuto
    def _dirty(self) -> bool:
        return self.stack.currentIndex() == 1 and self.editor.document().isModified()

    def _item_clicked(self, item, _column=0):
        """Un clic apre e chiude cartelle, progetti e cestino (la freccia ▸/▾ lo mostra)."""
        data = item.data(0, _ROLE)
        if item.childCount() and (data is None or data[0] in ("project", "bin")):
            item.setExpanded(not item.isExpanded())

    def _item_changed(self, item, previous):
        data = item.data(0, _ROLE) if item else None
        if not data or data[0] == "bin":
            return
        if self._dirty() and QMessageBox.question(
                self, tr("Vault"), tr("Le modifiche non salvate andranno perse. Continuare?")) != \
                QMessageBox.StandardButton.Yes:
            self.tree.blockSignals(True)  # resto sulla nota che stavo modificando
            self.tree.setCurrentItem(previous)
            self.tree.blockSignals(False)
            return
        self._open(data)

    def _open(self, data):
        kind, slug, rel = data
        if self.stack.currentIndex() == 2:
            self.stack.setCurrentIndex(0)   # si esce dal grafo
        if kind == "trash":
            self._open_trash(slug, rel)
            return
        if kind == "project":  # la riga del progetto apre PROJECT.md
            kind = "file"
        self.current = (kind, slug, rel)
        p = self.vault.project(slug)
        try:
            text = p.read_text(rel)
        except KeyError:
            text = ""
        tail = rel[len(p.rel()) + 1:]
        self.crumb.setText(f"{self.vault.name}  /  {p.name}  /  {tail}")
        name = rel.rsplit("/", 1)[1]
        is_project = name == PROJECT_FILE and f"/{VERSIONS}/" not in rel
        self.title.setText(p.name if is_project else (pj.title_of(text) or name))
        self.meter_box.setVisible(is_project)
        if is_project:
            n = pj.estimate_tokens(pj.strip_private(text))
            self.meter.setRange(0, pj.TOKEN_LIMIT)   # il tetto si può cambiare dalle impostazioni
            self.meter.setValue(min(n, pj.TOKEN_LIMIT))
            self.meter.setProperty("over", n > pj.TOKEN_LIMIT)
            self.meter.style().unpolish(self.meter)
            self.meter.style().polish(self.meter)
            self.tokens.setText(tr("~{n} / {limit} token").format(n=n, limit=pj.TOKEN_LIMIT))
            self.meta.setText(tr("Stato del progetto · inviato all'IA a ogni chat nuova, senza «Solo per me»"))
        elif kind == "version":
            self.meta.setText(tr("Versione precedente di PROJECT.md"))
        elif f"/{SESSIONS}/" in rel:
            self.meta.setText(tr("Bozza automatica della sessione: non viene inviata all'IA"))
        elif f"/{NOTES}/" in rel:
            self.meta.setText(tr("Nota · l'IA la riceve solo se la chiede (HELPIX-NOTA) o se la incolli tu"))
        elif name == INDEX_FILE:
            self.meta.setText(tr("Indice delle note: all'IA vanno solo le ultime righe"))
        else:
            self.meta.setText(tr("File del progetto · l'IA lo riceve solo se lo chiede o se lo incolli tu"))
        body = project_html(text) if is_project or kind == "version" else markdown_html(
            "\n".join(text.splitlines()[1:]) if pj.title_of(text) and text.startswith("# ") else text)
        self._set_html(body)
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self.btn_resume.setText(tr("Riprendi con {name}").format(name=self.assistant()) if self.assistant()
                                else tr("Riprendi il progetto"))
        self.btn_edit.setEnabled(kind == "file")
        self.seg.setVisible(True)
        self.btn_resume.setVisible(True)
        self.btn_untrash.hide()
        self.btn_purge.hide()
        self.btn_restore.setVisible(kind == "version")
        self.btn_paste.setVisible(f"/{NOTES}/" in rel or f"/{FILES}/" in rel)
        self.btn_resume.setEnabled(True)
        self.btn_read.setChecked(True)
        self._mode(False)
        self._side(p, rel)

    def _open_trash(self, tid: str, rel: str):
        self.current = ("trash", tid, rel)
        if self.stack.currentIndex() == 2:
            self.stack.setCurrentIndex(0)
        try:
            item = next(t for t in self.vault.trash() if t.id == tid)
            text = self.vault.store.read(rel).decode("utf-8", "replace")
        except (StopIteration, KeyError, VaultError):
            self.reload()
            return
        self.crumb.setText(f"{self.vault.name}  /  {tr('Cestino')}")
        self.title.setText(item.name)
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(item.deleted))
        self.meta.setText((tr("Progetto nel cestino") if item.kind == "project" else tr("Nota nel cestino"))
                          + " · " + tr("eliminato il {when}").format(when=when) + " · "
                          + tr("{n} file").format(n=len(item.files)))
        self._set_html(project_html(text) if rel.endswith("/" + PROJECT_FILE) else markdown_html(text))
        self.meter_box.hide()
        self.seg.hide()
        for b in (self.btn_resume, self.btn_paste, self.btn_restore):
            b.hide()
        self.btn_untrash.show()
        self.btn_purge.show()
        self.stack.setCurrentIndex(0)
        self.backlinks.clear()
        self.recent.clear()
        self._clear_ctx()
        self._ctx_row(tr("Nel cestino"), tr("non va all'IA"), muted=True)
        self.ctx_note.hide()
        for w in (self.lab_links, self.backlinks, self.lab_recent, self.recent):
            w.hide()

    # ------------------------------------------------------------ rinomina, elimina, cestino
    def _fill_menu(self, menu: QMenu, data):
        menu.clear()
        if not data:
            menu.addAction(tr("Nessuna azione")).setEnabled(False)
            return
        kind, slug, rel = data
        if kind == "bin":
            menu.addAction(icon("trash", C["errText"], 16), tr("Svuota il cestino…"), self._empty_bin)
            return
        if kind == "trash":
            menu.addAction(icon("restore", C["text"], 16), tr("Ripristina"), lambda: self._untrash(slug))
            menu.addAction(icon("trash", C["errText"], 16), tr("Elimina definitivamente…"), lambda: self._purge(slug))
            return
        name = rel.rsplit("/", 1)[-1]
        project_level = kind == "project" or name in (PROJECT_FILE, INDEX_FILE) or f"/{VERSIONS}/" in rel
        menu.addAction(icon("file", C["text"], 16), tr("Rinomina il progetto…"), lambda: self._rename(slug))
        if not project_level and f"/{SESSIONS}/" not in rel:
            label = tr("Elimina la nota…") if f"/{NOTES}/" in rel else tr("Elimina il file…")
            menu.addAction(icon("trash", C["errText"], 16), label, lambda: self._delete_file(rel))
        elif f"/{SESSIONS}/" in rel:
            menu.addAction(icon("trash", C["errText"], 16), tr("Elimina la bozza…"), lambda: self._delete_file(rel))
        menu.addSeparator()
        menu.addAction(icon("trash", C["errText"], 16), tr("Elimina il progetto…"), lambda: self._delete_project(slug))

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        data = item.data(0, _ROLE) if item else None
        if data is None and item is not None and item.parent() is not None:
            parent = item.parent().data(0, _ROLE)
            data = ("project", parent[1], parent[2]) if parent and parent[0] == "project" else None
        if not data:
            return
        menu = theme.prepare_menu(QMenu(self))
        self._fill_menu(menu, data)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename(self, slug: str):
        p = self.vault.project(slug)
        name, ok = QInputDialog.getText(self, tr("Rinomina il progetto"), tr("Nuovo nome:"), text=p.name)
        if not ok or not name.strip() or name.strip() == p.name:
            return
        try:
            self.vault.rename_project(slug, name)
        except (VaultError, KeyError) as exc:
            QMessageBox.warning(self, tr("Vault"), str(exc))
            return
        self.changed.emit(slug)
        self.reload()

    def _delete_project(self, slug: str):
        p = self.vault.project(slug)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Elimina il progetto"))
        box.setText(tr("Eliminare il progetto «{name}»?").format(name=p.name))
        box.setInformativeText(tr("Va nel cestino del vault con tutte le note e le versioni: da lì puoi ripristinarlo "
                                  "o eliminarlo definitivamente."))
        delete = box.addButton(tr("Sposta nel cestino"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not delete:
            return
        try:
            tid = self.vault.delete_project(slug)
        except (VaultError, KeyError, OSError) as exc:
            QMessageBox.warning(self, tr("Vault"), tr("Eliminazione non riuscita: {exc}").format(exc=exc))
            return
        self.current = None
        self.project_deleted.emit(slug)
        self.reload(keep="trash:" + tid)

    def _delete_file(self, rel: str):
        name = rel.rsplit("/", 1)[-1]
        if QMessageBox.question(self, tr("Vault"), tr("Spostare «{name}» nel cestino del vault?").format(name=name)) != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            self.vault.delete_file(rel)
        except (VaultError, KeyError, OSError) as exc:
            QMessageBox.warning(self, tr("Vault"), tr("Eliminazione non riuscita: {exc}").format(exc=exc))
            return
        slug = rel.split("/")[1]
        self.current = None
        self.changed.emit(slug)
        self.reload(keep=self.vault.project(slug).rel(PROJECT_FILE))

    def _untrash(self, tid: str):
        try:
            targets = self.vault.restore(tid)
        except VaultError as exc:
            QMessageBox.warning(self, tr("Vault"), tr("Non posso ripristinarlo: {exc}. Rinomina o elimina prima "
                                                      "quello che c'è adesso.").format(exc=exc))
            return
        except (KeyError, OSError) as exc:
            QMessageBox.warning(self, tr("Vault"), str(exc))
            return
        slug = targets[0].split("/")[1]
        self.current = None
        self.project_restored.emit(slug)
        self.changed.emit(slug)
        first = next((t for t in targets if t.endswith("/" + PROJECT_FILE)), targets[0])
        self.reload(keep=first)

    def _purge(self, tid: str):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Elimina definitivamente"))
        box.setText(tr("Eliminare definitivamente? Non si potrà più recuperare."))
        delete = box.addButton(tr("Elimina definitivamente"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not delete:
            return
        self.vault.purge(tid)
        self.current = None
        self.reload()

    def _empty_bin(self):
        n = len(self.vault.trash())
        if not n or QMessageBox.question(self, tr("Svuota il cestino"),
                                         tr("Eliminare definitivamente i {n} elementi del cestino?").format(n=n)) != \
                QMessageBox.StandardButton.Yes:
            return
        self.vault.purge()
        self.current = None
        self.reload()

    def _set_html(self, body: str):
        self.view.document().setDefaultStyleSheet(_css())
        self.view.setHtml(f"<body>{body}</body>")

    def _show_none(self):
        self.current = None
        self.stack.setCurrentIndex(0)
        self.btn_read.setChecked(True)
        for w in (self.crumb, self.title, self.meta, self.tokens):
            w.setText("")
        self._set_html(f'<p class="muted">{tr("Nessun progetto: creane uno dal selettore Progetto.")}</p>')
        for b in (self.btn_resume, self.btn_paste, self.btn_edit):
            b.setEnabled(False)
        self.btn_restore.hide()
        self.meter_box.hide()
        self.backlinks.clear()
        self.recent.clear()
        self._clear_ctx()

    def _mode(self, edit: bool):
        if self.stack.currentIndex() == 2:   # dal grafo: torna alla nota con la sua intestazione
            if self.current:
                self._open(self.current)
            if edit and self.btn_edit.isEnabled():
                self.btn_edit.setChecked(True)   # ora dalla lettura alla modifica
            return
        if not edit and self._dirty():
            self._cancel_edit()
            return
        self.stack.setCurrentIndex(1 if edit else 0)
        if edit:
            self.editor.setFocus()

    # ------------------------------------------------------------ grafo
    def _show_graph(self):
        if not self.current or self.current[0] == "trash":
            return
        if self._dirty() and QMessageBox.question(
                self, tr("Vault"), tr("Le modifiche non salvate andranno perse. Continuare?")) != \
                QMessageBox.StandardButton.Yes:
            self.btn_edit.setChecked(True)
            return
        kind, slug, rel = self.current
        p = self.vault.project(slug)
        try:
            graph = p.graph(recent=pj.RECENT_NOTES)
        except (KeyError, VaultError):
            return
        self.crumb.setText(f"{self.vault.name}  /  {p.name}  /  {tr('Grafo')}")
        self.title.setText(p.name)
        self.meta.setText(tr("Le sessioni dalla prima all'ultima e, accanto a ognuna, le decisioni prese lì; "
                             "in fondo lo stato attuale e i prossimi passi"))
        self.meter_box.hide()
        self.btn_paste.hide()
        self.btn_restore.hide()
        self.graph_page.set_graph(graph, current=rel)
        self.stack.setCurrentIndex(2)

    def _graph_open(self, rel: str):
        """Clic su un nodo: apre la nota (o il file, o PROJECT.md) nel pannello, in lettura."""
        it = self._items.get(rel)
        if it is not None and self.tree.currentItem() is it:
            self._open(it.data(0, _ROLE))   # è già quella scelta nell'albero: la riapro in lettura
        else:
            self.select(rel)
        if self.stack.currentIndex() == 2:   # non è nell'albero (filtro di ricerca): apro lo stesso
            self._open(("file", self.current[1], rel))

    def _cancel_edit(self):
        if self.current:
            self._open(self.current)

    def _clear_ctx(self):
        while self.ctx_rows.count():
            item = self.ctx_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _ctx_row(self, label: str, value: str, bold: bool = False, muted: bool = False):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        a, b = QLabel(label), QLabel(value)
        b.setObjectName("vaultTokens")
        if bold:
            _bold(a)
            _bold(b)
        if muted:
            a.setObjectName("secondary")
        h.addWidget(a, 1)
        h.addWidget(b)
        self.ctx_rows.addWidget(row)

    def _side(self, p, rel: str):
        self.ctx_note.show()
        for w in (self.lab_links, self.backlinks, self.lab_recent, self.recent):
            w.show()
        text = p.text()
        recent = pj.recent_index_lines(p.index_text())
        n_project = pj.estimate_tokens(pj.strip_private(text))
        n_recent = pj.estimate_tokens("\n".join(recent))
        total = pj.estimate_tokens(pj.context_text(p.name, text, p.index_text()))
        self._clear_ctx()
        self._ctx_row("PROJECT.md", f"~{n_project}")
        self._ctx_row(tr("Ultime {k} righe dell'indice").format(k=len(recent)), f"~{n_recent}")
        self._ctx_row(tr("«Solo per me»"), tr("esclusa"), muted=True)
        rule = QFrame()
        rule.setObjectName("vaultRule")
        self.ctx_rows.addWidget(rule)
        self._ctx_row(tr("Totale con le istruzioni"), tr("~{n} token").format(n=total), bold=True)
        if n_project > pj.TOKEN_LIMIT:
            warn = QLabel(tr("Oltre il limite: compatta il progetto (Progetto › Compatta il progetto)."))
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {C['warnText']};")
            self.ctx_rows.addWidget(warn)
        self.backlinks.clear()
        for other in p.backlinks(rel):
            it = QListWidgetItem(icon("file", C["secondary"], 14), other[len(p.rel()) + 1:])
            it.setData(_ROLE, other)
            self.backlinks.addItem(it)
        if not self.backlinks.count():
            it = QListWidgetItem(tr("Nessuna"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.backlinks.addItem(it)
        rows = min(self.backlinks.count(), 4)  # alta quanto le righe (fino a 4), senza vuoti sotto
        self.backlinks.setFixedHeight(rows * 40 + 6)
        self.recent.clear()
        notes = p.notes()
        in_ctx = {n.rel for n in notes[-pj.RECENT_NOTES:]}
        for n in reversed(notes[-12:]):
            it = QListWidgetItem()
            it.setToolTip(n.summary or n.title)
            it.setData(_ROLE, n.rel)
            it.setData(Qt.ItemDataRole.AccessibleTextRole, n.title)  # il disegno è quello della riga
            row = _NoteRow(n, n.rel in in_ctx)
            it.setSizeHint(QSize(0, 54))
            self.recent.addItem(it)
            self.recent.setItemWidget(it, row)
        if not self.recent.count():
            it = QListWidgetItem(tr("Nessuna nota ancora: arrivano con «Salva progetto»."))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)

    # ------------------------------------------------------------ azioni
    def _link(self, url: QUrl):
        if url.scheme() == "helpix" and self.current:
            p = self.vault.project(self.current[1])
            name = QUrl.fromPercentEncoding(url.path().encode("utf-8"))
            target = p.resolve(name)
            if target:
                self.select(target)
            else:
                QMessageBox.information(self, tr("Vault"), tr("Nota non trovata: {name}").format(name=name))
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
        _kind, slug, rel = self.current
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
            top.setIcon(0, icon("folder", C["secondary"], 16))
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            _bold_item(top)
            self.tree.addTopLevelItem(top)
            for rel, line in hits:
                label = f"{rel[len(p.rel()) + 1:]}: {line[:80]}"
                it = QTreeWidgetItem([label])
                it.setToolTip(0, line)
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

    def closeEvent(self, ev):
        if self._dirty() and QMessageBox.question(
                self, tr("Vault"), tr("Le modifiche non salvate andranno perse. Chiudere?")) != \
                QMessageBox.StandardButton.Yes:
            ev.ignore()
            return
        super().closeEvent(ev)


class _NoteRow(QWidget):
    """Riga di una nota recente: data, titolo e chip «nel contesto» / «archivio»."""

    def __init__(self, note, in_context: bool):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 8, 6)
        v.setSpacing(3)
        title = QLabel()
        title.setText(title.fontMetrics().elidedText(note.title, Qt.TextElideMode.ElideRight, 250))
        v.addWidget(title)
        h = QHBoxLayout()
        h.setSpacing(8)
        v.addLayout(h)
        date = QLabel(f"{note.date[8:10]}/{note.date[5:7]}/{note.date[:4]}" if note.date else "")
        date.setObjectName("vaultTokens")
        h.addWidget(date)
        h.addStretch(1)
        chip = QLabel(tr("nel contesto") if in_context else tr("archivio"))
        fg, bg = (C["accentFg"], C["tint"]) if in_context else (C["secondary"], C["segBg"])
        chip.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 8px; padding: 1px 7px; "
                           "font-size: 11px; font-weight: 600;")
        h.addWidget(chip)


class _Tree(QTreeWidget):
    """Albero del vault: freccia ▸/▾ disegnata da Helpix, sfondo di selezione e passaggio su tutta la riga
    (senza scalini né riquadri vuoti), nessuna cornice tratteggiata."""

    def drawRow(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        # la selezione la chiedo al modello: lo stato passato qui non sempre la riporta
        selected = self.selectionModel().isSelected(index) and bool(self.itemFromIndex(index).flags()
                                                                     & Qt.ItemFlag.ItemIsSelectable)
        hover = self.viewport().underMouse() and opt.rect.contains(self.viewport().mapFromGlobal(QCursor.pos()))
        if selected or hover:
            r = QRectF(opt.rect).adjusted(4, 1, -4, -1)
            r.setLeft(4)
            r.setRight(self.viewport().width() - 4)
            path = QPainterPath()
            path.addRoundedRect(r, 7, 7)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillPath(path, QColor(C["tint"] if selected else C["hover"]))
            painter.restore()
        opt.state &= ~(QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_Selected |
                       QStyle.StateFlag.State_MouseOver)
        if selected:
            opt.palette.setColor(opt.palette.ColorRole.Text, QColor(C["accentFg"]))
        super().drawRow(painter, opt, index)

    def mouseMoveEvent(self, ev):  # lo sfondo del passaggio copre tutta la riga: ridisegno anche fuori dall'elemento
        super().mouseMoveEvent(ev)
        self.viewport().update()

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self.viewport().update()

    def drawBranches(self, painter, rect, index):
        item = self.itemFromIndex(index)
        if item is None or not item.childCount():
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(C["secondary"]), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = rect.right() - self.indentation() / 2 + 2
        cy = rect.center().y() + 0.5
        s = 3.6
        if item.isExpanded():
            pts = [QPointF(cx - s, cy - s / 2), QPointF(cx, cy + s / 2), QPointF(cx + s, cy - s / 2)]
        else:
            pts = [QPointF(cx - s / 2, cy - s), QPointF(cx + s / 2, cy), QPointF(cx - s / 2, cy + s)]
        painter.drawPolyline(QPolygonF(pts))
        painter.restore()


class _NoFocusDelegate(QStyledItemDelegate):
    """Niente rettangolo tratteggiato attorno all'elemento attivo: la selezione si vede già dal colore."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, opt, index)


def _bold_item(item: QTreeWidgetItem):
    f = item.font(0)
    f.setWeight(QFont.Weight.DemiBold)
    item.setFont(0, f)
