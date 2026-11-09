# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cornice di Helpix per le finestre di dialogo.

Tutte le finestre di dialogo (impostazioni, conferme, avvisi, richieste di testo) usano la barra
integrata di Helpix invece di quella del sistema, come la finestra principale: icona, titolo, chiudi;
si trascinano dalla barra e, se ridimensionabili, dai bordi.

Funziona senza filtri di eventi globali (con QtWebEngine causano crash): `install()` aggancia
`QDialog.exec/open/show` e le funzioni statiche di QMessageBox e QInputDialog, così la cornice arriva
anche alle finestre create in un punto qualsiasi del codice. Ogni finestra riceve un filtro solo per sé.

Il contenuto non viene spostato: la barra è un figlio della finestra posato sopra e il margine superiore
della finestra (contentsMargins) lascia il suo spazio, quindi il layout esistente resta com'è.

Con *Barra del titolo del sistema* attiva nelle impostazioni non fa niente.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QToolButton, QWidget)

from .. import theme
from ..i18n import tr
from ..icons import icon
from ..theme import C

ENABLED = True      # False con la barra del titolo del sistema
ROUNDED = True      # angoli arrotondati (impostazione *Angoli arrotondati*)
TITLE_H = 40
RADIUS = 12

_installed = False


def configure(enabled: bool, rounded: bool) -> None:
    global ENABLED, ROUNDED
    ENABLED, ROUNDED = bool(enabled), bool(enabled and rounded)


def _skip(dlg: QWidget) -> bool:
    if not ENABLED or dlg.property("hxframe") is not None:
        return True
    if isinstance(dlg, QFileDialog):      # selettore dei file: quello del sistema
        return True
    if dlg.windowFlags() & Qt.WindowType.FramelessWindowHint:   # ha già la sua barra (es. pannello Vault)
        return True
    return False


class _DialogBar(QFrame):
    def __init__(self, dlg: QDialog):
        super().__init__(dlg)
        self.setObjectName("dialogBar")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 8, 0)
        h.setSpacing(9)
        self.logo = QLabel()
        self.logo.setPixmap(theme.app_icon().pixmap(18, 18))
        h.addWidget(self.logo)
        self.title = QLabel(dlg.windowTitle() or "Helpix")
        self.title.setObjectName("dialogTitle")
        self.title.setStyleSheet("font-weight: 600;")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.title.setMinimumWidth(0)
        h.addWidget(self.title, 1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("winClose")
        self.close_btn.setProperty("class", "win")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setToolTip(tr("Chiudi"))
        self.close_btn.setAccessibleName(tr("Chiudi"))
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(dlg.close)
        h.addWidget(self.close_btn)
        dlg.windowTitleChanged.connect(lambda t: self.title.setText(t or "Helpix"))
        theme.manager().changed.connect(lambda _d: self.refresh())
        self.refresh()

    def refresh(self):
        self.close_btn.setIcon(icon("x", C["text"], 12, 2))
        style = f"background: {C['winBtn']}; border-radius: 12px; padding: 0;"
        self.close_btn.setStyleSheet(f"QToolButton {{ {style} }} QToolButton:hover {{ background: #E0443E; }}")


class _Frame(QObject):
    """Barra, sfondo arrotondato e altezza minima che segue il testo a capo."""

    def __init__(self, dlg: QDialog):
        super().__init__(dlg)
        self.dlg = dlg
        dlg.setProperty("hxframe", "true")
        dlg.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        if ROUNDED:
            dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.radius = RADIUS if ROUNDED else 0
        m = dlg.contentsMargins()
        dlg.setContentsMargins(m.left(), m.top() + TITLE_H, m.right(), m.bottom())
        self.bar = _DialogBar(dlg)
        # spazio per il titolo intero (QMessageBox calcola da sé la larghezza, titolo compreso)
        self.min_w = 0 if isinstance(dlg, QMessageBox) else min(self.bar.sizeHint().width() + 12, 560)
        if isinstance(dlg, QInputDialog):
            self.min_w = max(self.min_w, 360)   # una casella di testo comoda, non da 200 px
        if self.min_w:
            dlg.setMinimumWidth(max(dlg.minimumWidth(), self.min_w))
        from .frameless import FramelessHelper
        self.helper = FramelessHelper(dlg, self.bar, maximize=False)
        dlg.installEventFilter(self)
        dlg.style().unpolish(dlg)
        dlg.style().polish(dlg)
        self._place()

    def _resizable(self) -> bool:
        d = self.dlg
        if isinstance(d, QMessageBox):
            return False
        return d.minimumWidth() != d.maximumWidth() or d.minimumHeight() != d.maximumHeight()

    def _place(self):
        self.bar.setGeometry(0, 0, self.dlg.width(), TITLE_H)
        self.bar.raise_()
        if not self._resizable():
            for g in self.helper.grips:
                g.hide()

    def _fit_height(self):
        """Il testo a capo (etichette lunghe) chiede più altezza quando la finestra si stringe: senza questo
        le righe finirebbero una sopra l'altra."""
        lay = self.dlg.layout()
        if lay is None or not lay.hasHeightForWidth() or isinstance(self.dlg, QMessageBox):
            return
        need = lay.totalHeightForWidth(self.dlg.width())
        if need > 0 and need != self.dlg.minimumHeight() and need <= 4000:
            self.dlg.setMinimumHeight(need)

    def eventFilter(self, obj, ev):  # noqa: N802
        if "bar" not in self.__dict__:   # finestra in chiusura
            return False
        t = ev.type()
        if t in (QEvent.Type.Resize, QEvent.Type.Show):
            if t == QEvent.Type.Show and self.dlg.width() < self.min_w <= self.dlg.maximumWidth():
                self.dlg.resize(self.min_w, self.dlg.height())   # layout che riscrive il minimo (QInputDialog)
            self._place()
            if t == QEvent.Type.Resize:
                self._fit_height()
        elif t == QEvent.Type.Paint:
            self._paint()
        return False

    def _paint(self):
        d = self.dlg
        p = QPainter(d)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(d.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        p.fillPath(path, QColor(C["window"]))
        p.save()
        p.setClipPath(path)
        p.fillRect(0, 0, d.width(), TITLE_H, QColor(C["toolbar"]))
        p.fillRect(0, TITLE_H - 1, d.width(), 1, QColor(C["hairline"]))
        p.restore()
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawPath(path)
        p.end()


def frame_dialog(dlg: QWidget) -> QWidget:
    """Dà la cornice di Helpix a `dlg` (prima che venga mostrata). Non fa niente se è già fatta."""
    if isinstance(dlg, QDialog) and not dlg.isVisible() and not _skip(dlg):
        _Frame(dlg)
    return dlg


# ---------------------------------------------------------------- funzioni statiche di Qt

def _box(kind, parent, title, text, buttons, default):
    box = QMessageBox(kind, title, text, buttons, parent)
    if default not in (None, QMessageBox.StandardButton.NoButton):
        box.setDefaultButton(default)
    box.exec()
    clicked = box.clickedButton()
    return box.standardButton(clicked) if clicked is not None else QMessageBox.StandardButton.NoButton


def _make_static(kind, default_buttons):
    def fn(parent, title, text, buttons=default_buttons, defaultButton=QMessageBox.StandardButton.NoButton):  # noqa: N803
        return _box(kind, parent, title, text, buttons, defaultButton)
    return staticmethod(fn)


def _get_text(parent, title, label, echo=QLineEdit.EchoMode.Normal, text="", flags=Qt.WindowType.Widget,
              inputMethodHints=Qt.InputMethodHint.ImhNone):  # noqa: N803
    dlg = QInputDialog(parent, flags)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextEchoMode(echo)
    dlg.setTextValue(text)
    dlg.setInputMethodHints(inputMethodHints)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return (dlg.textValue() if ok else ""), ok


def _get_item(parent, title, label, items, current=0, editable=True, flags=Qt.WindowType.Widget,
              inputMethodHints=Qt.InputMethodHint.ImhNone):  # noqa: N803
    items = list(items)
    dlg = QInputDialog(parent, flags)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setComboBoxItems(items)
    if items:
        dlg.setTextValue(items[max(0, min(current, len(items) - 1))])
    dlg.setComboBoxEditable(editable)
    dlg.setInputMethodHints(inputMethodHints)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return (dlg.textValue() if ok else (items[current] if items and 0 <= current < len(items) else "")), ok


def _get_int(parent, title, label, value=0, minValue=-2147483647, maxValue=2147483647, step=1,  # noqa: N803
             flags=Qt.WindowType.Widget):
    dlg = QInputDialog(parent, flags)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setIntRange(minValue, maxValue)
    dlg.setIntStep(step)
    dlg.setIntValue(value)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return (dlg.intValue() if ok else value), ok


def install() -> None:
    """Aggancia la cornice a tutte le finestre di dialogo create da Helpix. Si chiama una volta sola."""
    global _installed
    if _installed:
        return
    _installed = True
    for cls in (QDialog, QMessageBox, QInputDialog):
        for name in ("exec", "open", "show"):
            if cls is not QDialog and name not in cls.__dict__:
                continue   # eredita quello di QDialog, già agganciato
            real = getattr(cls, name)

            def wrapper(self, *a, _real=real, **k):
                frame_dialog(self)
                return _real(self, *a, **k)
            wrapper.__name__ = name
            setattr(cls, name, wrapper)
    ok, yes_no = QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    QMessageBox.information = _make_static(QMessageBox.Icon.Information, ok)
    QMessageBox.warning = _make_static(QMessageBox.Icon.Warning, ok)
    QMessageBox.critical = _make_static(QMessageBox.Icon.Critical, ok)
    QMessageBox.question = _make_static(QMessageBox.Icon.Question, yes_no)
    QInputDialog.getText = staticmethod(_get_text)
    QInputDialog.getItem = staticmethod(_get_item)
    QInputDialog.getInt = staticmethod(_get_int)
