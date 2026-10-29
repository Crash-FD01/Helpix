# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra senza cornice di sistema, con barra integrata (stile Apple / GNOME).

Spostamento e ridimensionamento usano startSystemMove/startSystemResize di Qt, che
delegano al compositor: funzionano sia su Wayland sia su X11.

Niente filtri di eventi globali (con QtWebEngine causano crash): la barra riceve un
filtro solo per sé e il ridimensionamento usa maniglie invisibili lungo i bordi.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

EDGE = 6
CORNER = 12

_SPECS = {
    "l": (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
    "r": (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
    "t": (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
    "b": (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
    "tl": (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
    "br": (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
    "tr": (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
    "bl": (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
}


class _Grip(QWidget):
    """Maniglia invisibile su un bordo o un angolo della finestra."""

    def __init__(self, window: QWidget, key: str):
        super().__init__(window)
        self.win = window
        self.edges, cursor = _SPECS[key]
        self.key = key
        self.setCursor(cursor)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def mousePressEvent(self, event):  # noqa: N802
        handle = self.win.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle:
            handle.startSystemResize(self.edges)


class FramelessHelper(QObject):
    def __init__(self, window: QWidget, drag_area: QWidget):
        super().__init__(window)
        self.win = window
        self.drag_area = drag_area
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.grips = [_Grip(window, k) for k in _SPECS]
        drag_area.installEventFilter(self)
        window.installEventFilter(self)
        self.layout_grips()

    def layout_grips(self):
        w, h = self.win.width(), self.win.height()
        geo = {
            "l": (0, CORNER, EDGE, h - 2 * CORNER), "r": (w - EDGE, CORNER, EDGE, h - 2 * CORNER),
            "t": (CORNER, 0, w - 2 * CORNER, EDGE), "b": (CORNER, h - EDGE, w - 2 * CORNER, EDGE),
            "tl": (0, 0, CORNER, CORNER), "tr": (w - CORNER, 0, CORNER, CORNER),
            "bl": (0, h - CORNER, CORNER, CORNER), "br": (w - CORNER, h - CORNER, CORNER, CORNER),
        }
        visible = not (self.win.isMaximized() or self.win.isFullScreen())
        for g in self.grips:
            g.setGeometry(*geo[g.key])
            g.setVisible(visible)
            g.raise_()

    def eventFilter(self, obj, event):  # noqa: N802
        et = event.type()
        if obj is self.win:
            if et in (QEvent.Type.Resize, QEvent.Type.WindowStateChange, QEvent.Type.Show):
                self.layout_grips()
            return False
        if obj is self.drag_area:
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                handle = self.win.windowHandle()
                if handle and handle.startSystemMove():
                    return True
            elif et == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                self.win.showNormal() if self.win.isMaximized() else self.win.showMaximized()
                return True
        return False


RADIUS = 16
INSET = 6  # spazio tra il bordo e il contenuto: con raggio 16 gli angoli del contenuto restano dentro la curva


class RoundedCentral(QWidget):
    """Sfondo della finestra con gli angoli arrotondati (la finestra è trasparente).

    Il contenuto rettangolare (pagine web, terminale) sta a INSET pixel dal bordo, così i
    suoi angoli cadono dentro la curva; la fascia della barra in alto è dipinta qui con il
    colore della barra, fino ai bordi.
    """

    def __init__(self, toolbar: QWidget):
        super().__init__()
        self.toolbar = toolbar
        self.radius = RADIUS

    def set_square(self, square: bool):
        self.radius = 0 if square else RADIUS
        m = 0 if square else INSET
        self.layout().setContentsMargins(m, 1 if not square else 0, m, m)
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

        from ..theme import C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        p.fillPath(path, QColor(C["window"]))
        band = self.toolbar.geometry().bottom() + 1
        p.save()
        p.setClipPath(path)
        p.fillRect(0, 0, self.width(), band, QColor(C["toolbar"]))
        p.fillRect(0, band - 1, self.width(), 1, QColor(C["hairline"]))
        p.restore()
        if self.radius:
            p.setPen(QPen(QColor(C["border"]), 1))
            p.drawPath(path)
        p.end()
