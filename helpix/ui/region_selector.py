# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Selettore a schermo intero: l'immagine dello schermo viene "congelata" e l'utente
trascina un riquadro (poi spostabile e ridimensionabile) oppure, su X11, fa clic su
una finestra per catturarla intera.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from ..theme import C
from ..i18n import tr

HANDLE = 8          # lato delle maniglie
MIN_DRAG = 6        # sotto questa distanza la pressione è un clic
HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
}


def image_rect(sel: QRect, widget_size: QSize, image: QImage) -> QRect:
    """Converte un rettangolo in coordinate del widget in pixel dell'immagine."""
    sx = image.width() / max(widget_size.width(), 1)
    sy = image.height() / max(widget_size.height(), 1)
    r = QRect(round(sel.x() * sx), round(sel.y() * sy), round(sel.width() * sx), round(sel.height() * sy))
    return r.intersected(image.rect())


class RegionSelector(QWidget):
    selected = Signal(QImage)
    cancelled = Signal()

    def __init__(self, image: QImage, windows: list[tuple[QRect, str]] | None = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Helpix — Seleziona l'area"))
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.image = image
        self.windows = windows or []          # coordinate del widget, dall'alto in basso
        self.sel: QRect | None = None
        self.hover: tuple[QRect, str] | None = None
        self.mode: str | None = None
        self.press = QPoint()
        self.orig = QRect()
        self._done = False

        self.bar = QFrame(self)
        self.bar.setObjectName("selectorBar")
        bh = QHBoxLayout(self.bar)
        bh.setContentsMargins(6, 6, 6, 6)
        bh.setSpacing(6)
        redo = QPushButton(tr("Rifai"))
        redo.clicked.connect(self._reset)
        cancel = QPushButton(tr("Annulla"))
        cancel.clicked.connect(self.cancel)
        ok = QPushButton(tr("✓ Usa questa area"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.confirm)
        for b in (redo, cancel, ok):
            b.setCursor(Qt.CursorShape.ArrowCursor)
            bh.addWidget(b)
        self.bar.hide()

    # ------------------------------------------------------------ geometria
    def _handles(self) -> dict[str, QRect]:
        if not self.sel:
            return {}
        r = self.sel
        pts = {"tl": r.topLeft(), "t": QPoint(r.center().x(), r.top()), "tr": r.topRight(),
               "r": QPoint(r.right(), r.center().y()), "br": r.bottomRight(),
               "b": QPoint(r.center().x(), r.bottom()), "bl": r.bottomLeft(),
               "l": QPoint(r.left(), r.center().y())}
        return {k: QRect(p.x() - HANDLE // 2, p.y() - HANDLE // 2, HANDLE, HANDLE) for k, p in pts.items()}

    def _handle_at(self, pos: QPoint) -> str | None:
        for name, rect in self._handles().items():
            if rect.adjusted(-4, -4, 4, 4).contains(pos):
                return name
        return None

    def _window_at(self, pos: QPoint):
        for rect, title in self.windows:
            if rect.contains(pos):
                return rect, title
        return None

    def _place_bar(self):
        if not self.sel:
            self.bar.hide()
            return
        self.bar.adjustSize()
        x = min(max(self.sel.right() - self.bar.width(), 8), self.width() - self.bar.width() - 8)
        y = self.sel.bottom() + 10
        if y + self.bar.height() > self.height() - 8:
            y = max(self.sel.top() - self.bar.height() - 10, 8)
        self.bar.move(x, y)
        self.bar.show()
        self.bar.raise_()

    # ------------------------------------------------------------ azioni
    def _reset(self):
        self.sel = None
        self.bar.hide()
        self.update()

    def confirm(self):
        if self._done or not self.sel or self.sel.width() < 2 or self.sel.height() < 2:
            return
        self._done = True
        crop = self.image.copy(image_rect(self.sel, self.size(), self.image))
        self.close()
        self.selected.emit(crop)

    def cancel(self):
        if self._done:
            return
        self._done = True
        self.close()
        self.cancelled.emit()

    def closeEvent(self, event):  # noqa: N802 - chiusura dal window manager = annulla
        if not self._done:
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)

    # ------------------------------------------------------------ eventi
    def mousePressEvent(self, e):  # noqa: N802
        pos = e.position().toPoint()
        if e.button() == Qt.MouseButton.RightButton:
            self._reset() if self.sel else self.cancel()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.press = pos
        handle = self._handle_at(pos) if self.sel else None
        if handle:
            self.mode, self.orig = handle, QRect(self.sel)
        elif self.sel and self.sel.contains(pos):
            self.mode, self.orig = "move", QRect(self.sel)
        else:
            self.mode = "new"
            self.sel = None
            self.bar.hide()
        self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        pos = e.position().toPoint()
        if self.mode == "new":
            if (pos - self.press).manhattanLength() >= MIN_DRAG:
                self.sel = QRect(self.press, pos).normalized()
        elif self.mode == "move":
            r = QRect(self.orig)
            r.translate(pos - self.press)
            r.moveLeft(min(max(r.left(), 0), self.width() - r.width()))
            r.moveTop(min(max(r.top(), 0), self.height() - r.height()))
            self.sel = r
        elif self.mode in HANDLES:
            r, d = QRect(self.orig), pos - self.press
            if "l" in self.mode:
                r.setLeft(r.left() + d.x())
            if "r" in self.mode:
                r.setRight(r.right() + d.x())
            if "t" in self.mode:
                r.setTop(r.top() + d.y())
            if "b" in self.mode:
                r.setBottom(r.bottom() + d.y())
            self.sel = r.normalized().intersected(self.rect())
        else:
            handle = self._handle_at(pos) if self.sel else None
            if handle:
                self.setCursor(_CURSORS[handle])
            elif self.sel and self.sel.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            if not self.sel:
                self.hover = self._window_at(pos)
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        was_new = self.mode == "new"
        self.mode = None
        if was_new and self.sel is None:
            win = self._window_at(e.position().toPoint())
            if win:                      # clic su una finestra: catturala subito
                self.sel = win[0].intersected(self.rect())
                self.confirm()
                return
        self._place_bar()
        self.update()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self.sel and self.sel.contains(e.position().toPoint()):
            self.confirm()

    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm()

    # ------------------------------------------------------------ disegno
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        accent = QColor(C["accent"])

        target = self.sel or (self.hover[0] if self.hover else None)
        if target:
            p.drawImage(target, self.image, image_rect(target, self.size(), self.image))
            p.setPen(QPen(accent, 2))
            p.drawRect(target.adjusted(0, 0, -1, -1))

        if self.sel:
            p.setBrush(accent)
            p.setPen(QPen(QColor("white"), 1))
            for rect in self._handles().values():
                p.drawRect(rect)
            ir = image_rect(self.sel, self.size(), self.image)
            self._label(p, f"{ir.width()} × {ir.height()}", self.sel.topLeft() + QPoint(0, -8))
        elif self.hover:
            self._label(p, tr("Clic per catturare: {title}").format(title=self.hover[1] or tr("finestra")),
                        self.hover[0].topLeft() + QPoint(0, -8))

        tip = (tr("Trascina per selezionare un'area") + (tr(" · clic su una finestra per catturarla") if self.windows else "")
               + tr(" · Invio conferma · Esc annulla"))
        self._label(p, tip, QPoint(self.width() // 2, 34), center=True)
        p.end()

    def _label(self, p: QPainter, text: str, anchor: QPoint, center: bool = False):
        font = QFont(self.font())
        font.setPointSize(10)
        p.setFont(font)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 18, fm.height() + 10
        x = anchor.x() - w // 2 if center else anchor.x()
        y = anchor.y() - h
        if y < 4:
            y = anchor.y() + 12 if not center else 4
        x = min(max(x, 4), self.width() - w - 4)
        box = QRect(x, y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 28, 225))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
