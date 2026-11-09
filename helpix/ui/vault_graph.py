# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista Grafo del pannello Vault: il percorso del progetto e i collegamenti tra note e file.

Disposizione fissa, non «a molle», così si legge come una linea del tempo e non cambia a ogni apertura:
- a sinistra, dall'alto in basso, le note in ordine di indice (dalla più vecchia) e in fondo PROJECT.md, lo
  stato attuale: le frecce «poi» sono il percorso del lavoro;
- a destra i file del progetto, ciascuno all'altezza delle note che lo citano;
- gli archi sono i link [[…]]: a sinistra quelli tra note, verso destra quelli verso i file.
In verticale perché il pannello è più alto che largo: si legge a grandezza naturale e si scorre come una pagina.

Passando sopra un nodo si accendono lui e i suoi collegamenti; un clic apre la nota nel pannello. La rotella
ingrandisce e rimpicciolisce, trascinando lo sfondo ci si sposta.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QFrame, QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ..i18n import tr
from ..theme import C

NOTE_W, NOTE_H = 236, 58
PROJ_W, PROJ_H = 252, 68
FILE_W, FILE_H = 168, 34
STEP_Y = 92           # distanza tra una nota e la successiva
FILE_X = 300          # colonna dei file, a destra delle note
FILE_GAP = 46         # distanza minima tra due file


def _qc(key: str, alpha: float = 1.0) -> QColor:
    c = QColor(C[key])
    c.setAlphaF(alpha)
    return c


class _Node(QGraphicsObject):
    def __init__(self, view: "GraphView", node, w: int, h: int):
        super().__init__()
        self.view, self.node, self.w, self.h = view, node, w, h
        self.dim = False
        self.hot = False
        self.current = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        tip = node.title if node.kind != "project" else tr("PROJECT.md — stato attuale")
        if node.date:
            tip = f"{node.date} · {tip}"
        if node.summary:
            tip += "\n" + node.summary
        if node.in_context:
            tip += "\n" + tr("Va all'IA all'inizio di ogni chat nuova")
        self.setToolTip(tip)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-self.w / 2 - 4, -self.h / 2 - 4, self.w + 8, self.h + 8)

    def rect(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def paint(self, p: QPainter, _opt, _w=None):
        n = self.node
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.28 if self.dim else 1.0)
        r = self.rect()
        radius = self.h / 2 if n.kind == "file" else 12
        if n.kind == "project":
            fill, border = _qc("accentBg"), _qc("accentBg")
        elif n.kind == "file":
            fill, border = _qc("panel2"), _qc("border")
        else:
            fill, border = _qc("panel"), _qc("accent", 0.85) if n.in_context else _qc("border")
        if self.hot:
            border = _qc("accent") if n.kind != "project" else _qc("text")
        pen = QPen(border, 2.4 if (self.hot or self.current) else (1.6 if n.in_context else 1.0))
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(r, radius, radius)
        if self.current:   # la nota aperta nel pannello
            p.setPen(QPen(_qc("accent", 0.45), 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        base = QFont(self.view.font())
        if n.kind == "file":
            f = QFont(base)
            f.setPointSizeF(max(8.0, base.pointSizeF() - 0.5))
            p.setFont(f)
            p.setPen(_qc("text"))
            fm = QFontMetrics(f)
            p.drawText(r.adjusted(14, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(n.title, Qt.TextElideMode.ElideMiddle, int(r.width() - 26)))
            return
        title_f = QFont(base)
        title_f.setBold(True)
        small = QFont(base)
        small.setPointSizeF(max(7.5, base.pointSizeF() - 1.5))
        fg = QColor("#FFFFFF") if n.kind == "project" else _qc("text")
        sub = QColor(255, 255, 255, 200) if n.kind == "project" else _qc("secondary")
        inner = r.adjusted(14, 9, -14, -9)
        if n.kind == "project":
            top, bottom = tr("Stato attuale · PROJECT.md"), n.title
            p.setFont(small)
            p.setPen(sub)
            p.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, top)
            p.setFont(title_f)
            p.setPen(fg)
            p.drawText(inner, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(title_f).elidedText(bottom, Qt.TextElideMode.ElideRight, int(inner.width())))
            return
        p.setFont(title_f)
        p.setPen(fg)
        p.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(title_f).elidedText(n.title, Qt.TextElideMode.ElideRight, int(inner.width())))
        p.setFont(small)
        p.setPen(sub)
        p.drawText(inner, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, n.date or tr("senza data"))
        if n.in_context:   # pallino: va nel contesto della prossima chat
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("accent"))
            p.drawEllipse(QPointF(r.right() - 14, r.bottom() - 15), 4, 4)

    # interazione
    def hoverEnterEvent(self, ev):  # noqa: N802
        self.view.highlight(self.node.rel)
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):  # noqa: N802
        self.view.highlight(None)
        super().hoverLeaveEvent(ev)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.scenePos()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        start = getattr(self, "_press", None)
        self._press = None
        if (ev.button() == Qt.MouseButton.LeftButton and start is not None
                and (ev.scenePos() - start).manhattanLength() < 6):
            self.view.activated.emit(self.node.rel)
        super().mouseReleaseEvent(ev)


class _Edge(QGraphicsItem):
    def __init__(self, a: _Node, b: _Node, kind: str):
        super().__init__()
        self.a, self.b, self.kind = a, b, kind
        self.dim = False
        self.hot = False
        self.setZValue(-1)
        self.path = self._make_path()

    def _make_path(self) -> QPainterPath:
        a, b = self.a, self.b
        pa, pb = a.pos(), b.pos()
        path = QPainterPath()
        if self.kind == "next":   # freccia verso il basso tra due nodi della colonna
            path.moveTo(pa.x(), pa.y() + a.h / 2)
            path.lineTo(pb.x(), pb.y() - b.h / 2 - 2)
            return path
        a_file, b_file = a.node.kind == "file", b.node.kind == "file"
        if a_file != b_file:      # nota ↔ file: dal lato destro della nota al lato sinistro del file
            n, f = (b, a) if a_file else (a, b)
            st = QPointF(n.pos().x() + n.w / 2, n.pos().y())
            e = QPointF(f.pos().x() - f.w / 2, f.pos().y())
            dx = (e.x() - st.x()) * 0.55
            path.moveTo(st)
            path.cubicTo(QPointF(st.x() + dx, st.y()), QPointF(e.x() - dx, e.y()), e)
            return path
        # stessa colonna: arco a sinistra (note) o a destra (file), più largo quanto più sono lontani
        sign = 1 if a_file else -1
        top, bottom = (a, b) if pa.y() <= pb.y() else (b, a)
        st = QPointF(top.pos().x() + sign * top.w / 2, top.pos().y())
        e = QPointF(bottom.pos().x() + sign * bottom.w / 2, bottom.pos().y())
        w = min(110.0, 26 + abs(e.y() - st.y()) * 0.22)
        path.moveTo(st)
        path.cubicTo(QPointF(st.x() + sign * w, st.y()), QPointF(e.x() + sign * w, e.y()), e)
        return path

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self.path.boundingRect().adjusted(-10, -10, 10, 10)

    def paint(self, p: QPainter, _opt, _w=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.15 if self.dim else 1.0)
        if self.kind == "next":
            color = _qc("accent") if self.hot else _qc("secondary", 0.75)
            pen = QPen(color, 2.6 if self.hot else 2.0)
        else:
            color = _qc("accent") if self.hot else _qc("accent", 0.55)
            pen = QPen(color, 2.2 if self.hot else 1.4)
            if not self.hot:
                pen.setDashPattern([5, 4])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self.path)
        if self.kind == "next":   # punta della freccia
            end = self.path.pointAtPercent(1.0)
            ang = math.radians(-self.path.angleAtPercent(1.0))
            size = 8
            pts = [end, QPointF(end.x() - size * math.cos(ang - 0.45), end.y() - size * math.sin(ang - 0.45)),
                   QPointF(end.x() - size * math.cos(ang + 0.45), end.y() - size * math.sin(ang + 0.45))]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygonF(pts))


class GraphView(QGraphicsView):
    """Il disegno; `activated(rel)` quando si fa clic su un nodo."""

    activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("vaultGraph")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # di lato: trascinando
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nodes: dict[str, _Node] = {}
        self.edges: list[_Edge] = []
        self.graph = None
        self._zoom = 1.0

    # ---------------------------------------------------------------- dati
    def set_graph(self, graph, current: str | None = None):
        self.graph = graph
        sc = self.scene()
        sc.clear()
        self.nodes, self.edges = {}, []
        notes = [n for n in graph.nodes if n.kind == "note"]
        files = [n for n in graph.nodes if n.kind == "file"]
        proj = next((n for n in graph.nodes if n.kind == "project"), None)
        for i, n in enumerate(notes):
            item = _Node(self, n, NOTE_W, NOTE_H)
            item.setPos(0, i * STEP_Y)
            self.nodes[n.rel] = item
        if proj is not None:
            item = _Node(self, proj, PROJ_W, PROJ_H)
            item.setPos(0, len(notes) * STEP_Y + (PROJ_H - NOTE_H) / 2 + 6)
            self.nodes[proj.rel] = item
        # file: all'altezza media delle note che li citano; quelli mai citati in fondo
        end_y = len(notes) * STEP_Y
        want = []
        for f in files:
            ys = [self.nodes[o].pos().y() for o in graph.neighbours(f.rel) if o in self.nodes
                  and self.nodes[o].node.kind != "file"]
            want.append((sum(ys) / len(ys) if ys else end_y, f))
        want.sort(key=lambda t: t[0])
        last = -1e9
        x = NOTE_W / 2 + FILE_X - NOTE_W / 2 + FILE_W / 2
        for y, f in want:
            y = max(y, last + FILE_GAP)
            item = _Node(self, f, FILE_W, FILE_H)
            item.setPos(x, y)
            self.nodes[f.rel] = item
            last = y
        for e in graph.edges:
            a, b = self.nodes.get(e.src), self.nodes.get(e.dst)
            if a is None or b is None:
                continue
            edge = _Edge(a, b, e.kind)
            self.edges.append(edge)
            sc.addItem(edge)
        for item in self.nodes.values():
            sc.addItem(item)
        self.set_current(current)
        rect = sc.itemsBoundingRect().adjusted(-40, -30, 40, 30)
        sc.setSceneRect(rect)

    def set_current(self, rel: str | None):
        for r, item in self.nodes.items():
            item.current = r == rel
            item.update()

    def fit(self):
        """Tutto in vista se ci sta senza rimpicciolire troppo; altrimenti grandezza naturale, sulla fine del
        percorso (le note recenti e lo stato attuale)."""
        sc = self.scene().sceneRect()
        if sc.isEmpty():
            return
        # larghezza utile anche quando compare la barra di scorrimento verticale
        bar = 0 if self.verticalScrollBar().isVisible() else self.verticalScrollBar().sizeHint().width()
        vw = max(1, self.viewport().width() - bar - 2)
        vh = max(1, self.viewport().height())
        scale = min(1.0, vw / sc.width(), vh / sc.height())
        self.resetTransform()
        if scale >= 0.8:
            self.scale(scale, scale)
            self._zoom = scale
            self.centerOn(sc.center())
            return
        scale = min(1.0, vw / sc.width())
        self.scale(scale, scale)
        self._zoom = scale
        self.centerOn(QPointF(sc.center().x(), sc.bottom() - vh / scale / 2))

    # ---------------------------------------------------------------- interazione
    def highlight(self, rel: str | None):
        near = self.graph.neighbours(rel) | {rel} if (rel and self.graph) else set()
        for r, item in self.nodes.items():
            item.hot = r == rel
            item.dim = bool(rel) and r not in near
            item.update()
        for e in self.edges:
            on = bool(rel) and rel in (e.a.node.rel, e.b.node.rel)
            e.hot = on
            e.dim = bool(rel) and not on
            e.update()

    def zoom_by(self, factor: float):
        new = max(0.3, min(2.5, self._zoom * factor))
        factor = new / self._zoom
        if abs(factor - 1) > 1e-3:
            self._zoom = new
            self.scale(factor, factor)

    def wheelEvent(self, ev):  # noqa: N802
        """Rotella: scorre come una pagina; con Ctrl ingrandisce e rimpicciolisce."""
        delta = ev.angleDelta().y()
        if delta and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.15 if delta > 0 else 1 / 1.15)
            ev.accept()
        else:
            super().wheelEvent(ev)

    def drawBackground(self, p: QPainter, rect: QRectF):  # noqa: N802
        p.fillRect(rect, _qc("page"))
        # griglia a puntini leggera: aiuta a capire che si può trascinare
        step = 28
        p.setPen(QPen(_qc("hairline"), 1.6))
        x0 = math.floor(rect.left() / step) * step
        y0 = math.floor(rect.top() / step) * step
        y = y0
        while y < rect.bottom():
            x = x0
            while x < rect.right():
                p.drawPoint(QPointF(x, y))
                x += step
            y += step


class GraphPage(QWidget):
    """Legenda, pulsante «Adatta» e il disegno; un messaggio se il progetto non ha ancora note."""

    activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(16)
        self.legend = QLabel()
        self.legend.setObjectName("secondary")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        bar.addWidget(self.legend, 1)
        self.btn_fit = QPushButton(tr("Adatta"))
        self.btn_fit.setToolTip(tr("Mostra tutto il grafo (Ctrl + rotella: ingrandisci; trascina lo sfondo per spostarti)"))
        bar.addWidget(self.btn_fit)
        v.addLayout(bar)
        self.frame = QFrame()
        self.frame.setObjectName("vaultGraphFrame")
        fv = QVBoxLayout(self.frame)
        fv.setContentsMargins(1, 1, 1, 1)
        self.view = GraphView()
        fv.addWidget(self.view)
        v.addWidget(self.frame, 1)
        self.empty = QLabel()
        self.empty.setObjectName("secondary")
        self.empty.setWordWrap(True)
        v.addWidget(self.empty)
        self.view.activated.connect(self.activated)
        self.btn_fit.clicked.connect(self.view.fit)
        self._fitted = False

    def set_graph(self, graph, current: str | None = None):
        self.view.set_graph(graph, current)
        n_notes = sum(1 for n in graph.nodes if n.kind == "note")
        n_links = sum(1 for e in graph.edges if e.kind == "link")
        accent, sec = C["accent"], C["secondary"]
        self.legend.setText(
            f'<span style="color:{sec}">━━▸</span> {tr("percorso nel tempo")} &nbsp;&nbsp; '
            f'<span style="color:{accent}">╌╌</span> {tr("collegamento [[…]]")} &nbsp;&nbsp; '
            f'<span style="color:{accent}">●</span> {tr("nel contesto della prossima chat")}')
        self.empty.setText(tr("Ancora nessuna nota: salva il progetto (Salva progetto) e qui comparirà il percorso "
                              "del lavoro.") if not n_notes else
                           tr("{n} note · {l} collegamenti · un clic apre la nota").format(n=n_notes, l=n_links))
        self._fitted = False
        if self.isVisible():
            self.view.fit()
            self._fitted = True

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        if not self._fitted:
            self.view.fit()
            self._fitted = True

    def refresh_theme(self):
        self.view.viewport().update()
        if self.view.graph is not None:
            self.set_graph(self.view.graph, next((r for r, i in self.view.nodes.items() if i.current), None))
