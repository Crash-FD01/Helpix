# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vista Grafo del pannello Vault: la mappa delle decisioni del progetto.

Due colonne, dall'alto in basso:
- a sinistra la linea del tempo: «Inizio», le sessioni (le note, dalla più vecchia) e in fondo lo stato attuale
  (PROJECT.md);
- a destra, all'altezza della sessione in cui sono nate, le decisioni: in vigore (barra verde), superate (barrate,
  con la freccia verso quella che le ha sostituite) o tolte; accanto allo stato i prossimi passi.
Si capisce perché il progetto è arrivato dov'è, non solo l'ordine delle note. I file citati da una nota sono un
numero sulla nota; i link [[…]] tra note sono archi sottili a sinistra.

Disposizione fissa (si legge come una pagina e non cambia a ogni apertura). Passando sopra un nodo si accendono
lui e i suoi collegamenti; un clic apre la nota da cui viene. Rotella per scorrere, Ctrl + rotella per lo zoom.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF, QTextOption
from PySide6.QtWidgets import (QFrame, QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ..i18n import tr
from ..theme import C

TIME_W = 220                       # colonna del tempo
NOTE_H, START_H, STATE_H = 48, 34, 62
DEC_X = TIME_W / 2 + 44            # bordo sinistro della colonna delle decisioni
DEC_W, DEC_H, STEP_H = 300, 50, 34
GAP = 10                           # tra due decisioni della stessa sessione
ROW_GAP = 22                       # tra una sessione (con le sue decisioni) e la successiva


def _qc(key: str, alpha: float = 1.0) -> QColor:
    c = QColor(C[key])
    c.setAlphaF(alpha)
    return c


def _small(base: QFont, delta: float = 1.5) -> QFont:
    f = QFont(base)
    f.setPointSizeF(max(7.5, base.pointSizeF() - delta))
    return f


class _Node(QGraphicsObject):
    def __init__(self, view: "GraphView", node, w: float, h: float):
        super().__init__()
        self.view, self.node, self.w, self.h = view, node, w, h
        self.dim = self.hot = self.current = False
        self.setAcceptHoverEvents(True)
        if node.open_rel:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(view.tooltip(node))

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-self.w / 2 - 6, -self.h / 2 - 6, self.w + 12, self.h + 12)

    def rect(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    # punti di aggancio
    def left(self) -> QPointF:
        return self.pos() + QPointF(-self.w / 2, 0)

    def right(self) -> QPointF:
        return self.pos() + QPointF(self.w / 2, 0)

    def top(self) -> QPointF:
        return self.pos() + QPointF(0, -self.h / 2)

    def bottom(self) -> QPointF:
        return self.pos() + QPointF(0, self.h / 2)

    def paint(self, p: QPainter, _opt, _w=None):
        n = self.node
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.25 if self.dim else 1.0)
        r = self.rect()
        base = QFont(self.view.font())
        kind = n.kind
        radius = 10
        # sfondo e bordo
        if kind == "state":
            fill, border = _qc("accentBg"), _qc("accentBg")
        elif kind == "start":
            fill, border, radius = _qc("panel2"), _qc("border"), self.h / 2
        elif kind == "step":
            fill, border, radius = _qc("page"), _qc("border"), self.h / 2
        elif kind == "decision" and n.status != "in_force":
            fill, border = _qc("panel2"), _qc("border")
        else:
            fill, border = _qc("panel"), _qc("border")
        if self.hot:
            border = _qc("text") if kind == "state" else _qc("accent")
        pen = QPen(border, 2.2 if self.hot else 1.0)
        if kind in ("step",) or (kind == "decision" and n.status != "in_force"):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawRoundedRect(r, radius, radius)
        if self.current:
            p.setPen(QPen(_qc("accent", 0.45), 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        if kind == "decision" and n.status == "in_force":   # barra verde: in vigore
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("ok"))
            p.drawRoundedRect(QRectF(r.left() + 5, r.top() + 8, 3.5, r.height() - 16), 1.5, 1.5)
        getattr(self, "_paint_" + kind)(p, r, base)

    def _paint_start(self, p, r, base):
        p.setFont(_small(base, 0.5))
        p.setPen(_qc("secondary"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, tr("Inizio del progetto"))

    def _paint_note(self, p, r, base):
        n = self.node
        inner = r.adjusted(12, 7, -12, -7)
        title = QFont(base)
        title.setBold(True)
        p.setFont(title)
        p.setPen(_qc("text"))
        right_pad = 0
        p.drawText(inner.adjusted(0, 0, -right_pad, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(title).elidedText(n.title, Qt.TextElideMode.ElideRight, int(inner.width())))
        small = _small(base)
        p.setFont(small)
        p.setPen(_qc("secondary"))
        bits = [n.date or tr("senza data")]
        if n.files:
            bits.append(tr("{n} file").format(n=len(n.files)))
        p.drawText(inner, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, "  ·  ".join(bits))
        if n.in_context:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("accent"))
            p.drawEllipse(QPointF(r.right() - 12, r.bottom() - 12), 3.5, 3.5)

    def _paint_state(self, p, r, base):
        n = self.node
        inner = r.adjusted(12, 8, -12, -8)
        p.setFont(_small(base))
        p.setPen(QColor(255, 255, 255, 210))
        p.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, tr("Stato attuale · PROJECT.md"))
        title = QFont(base)
        title.setBold(True)
        p.setFont(title)
        p.setPen(QColor("#FFFFFF"))
        text = n.summary or n.title
        p.drawText(inner, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(title).elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width())))

    def _paint_decision(self, p, r, base):
        n = self.node
        inner = r.adjusted(16, 6, -10, -6)
        small = _small(base, 2)
        p.setFont(small)
        label = {"in_force": tr("in vigore"), "superseded": tr("superata"), "removed": tr("tolta")}[n.status]
        if n.status == "superseded" and n.until:
            label = tr("superata il {d}").format(d=n.until)
        p.setPen(_qc("okText") if n.status == "in_force" else _qc("secondary"))
        head = f"{n.date}  ·  {label}" if n.date else label
        p.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, head)
        if n.in_context:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("accent"))
            p.drawEllipse(QPointF(r.right() - 11, r.top() + 11), 3.5, 3.5)
        f = QFont(base)
        f.setPointSizeF(max(8.0, base.pointSizeF() - 0.5))
        f.setStrikeOut(n.status != "in_force")
        p.setFont(f)
        p.setPen(_qc("text") if n.status == "in_force" else _qc("secondary"))
        fm = QFontMetrics(f)
        body = QRectF(inner.left(), inner.top() + QFontMetrics(small).height() + 1, inner.width(),
                      inner.height() - QFontMetrics(small).height() - 1)
        text = n.title
        if fm.horizontalAdvance(text) > body.width():   # al massimo una riga: la decisione intera è nel suggerimento
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(body.width()))
        opt = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        p.drawText(body, text, opt)

    def _paint_step(self, p, r, base):
        n = self.node
        p.setPen(QPen(_qc("secondary"), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(r.left() + 16, r.center().y()), 5, 5)
        f = QFont(base)
        f.setPointSizeF(max(8.0, base.pointSizeF() - 0.5))
        p.setFont(f)
        p.setPen(_qc("text"))
        inner = r.adjusted(30, 0, -12, 0)
        p.drawText(inner, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(f).elidedText(n.title, Qt.TextElideMode.ElideRight, int(inner.width())))

    # interazione
    def hoverEnterEvent(self, ev):  # noqa: N802
        self.view.highlight(self.node.rel)
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):  # noqa: N802
        self.view.highlight(None)
        super().hoverLeaveEvent(ev)

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and self.node.open_rel:
            self._press = ev.scenePos()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        start = getattr(self, "_press", None)
        self._press = None
        if (ev.button() == Qt.MouseButton.LeftButton and start is not None
                and (ev.scenePos() - start).manhattanLength() < 6):
            self.view.activated.emit(self.node.open_rel)
        super().mouseReleaseEvent(ev)


class _Edge(QGraphicsItem):
    def __init__(self, a: _Node, b: _Node, kind: str):
        super().__init__()
        self.a, self.b, self.kind = a, b, kind
        self.dim = self.hot = False
        self.setZValue(-1)
        self.path = self._make_path()

    def _make_path(self) -> QPainterPath:
        a, b, k = self.a, self.b, self.kind
        path = QPainterPath()
        if k == "next":                  # giù lungo la linea del tempo
            path.moveTo(a.bottom())
            path.lineTo(b.top() - QPointF(0, 2))
            return path
        if k in ("decided", "step"):     # dalla sessione (o dallo stato) alla decisione (o al passo), a destra
            s, e = a.right(), b.left()
            dx = max(16.0, (e.x() - s.x()) * 0.5)
            path.moveTo(s)
            path.cubicTo(s + QPointF(dx, 0), e - QPointF(dx, 0), e)
            return path
        if k == "replaced":              # superata → nuova: arco sul lato destro della colonna
            s, e = a.right(), b.right()
            w = min(90.0, 22 + abs(e.y() - s.y()) * 0.18)
            path.moveTo(s)
            path.cubicTo(s + QPointF(w, 0), e + QPointF(w, 0), e + QPointF(2, 0))
            return path
        # link tra note: arco sul lato sinistro della linea del tempo
        top, bottom = (a, b) if a.pos().y() <= b.pos().y() else (b, a)
        s, e = top.left(), bottom.left()
        w = min(70.0, 18 + abs(e.y() - s.y()) * 0.15)
        path.moveTo(s)
        path.cubicTo(s - QPointF(w, 0), e - QPointF(w, 0), e)
        return path

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self.path.boundingRect().adjusted(-10, -10, 10, 10)

    def paint(self, p: QPainter, _opt, _w=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.12 if self.dim else 1.0)
        k = self.kind
        if k == "next":
            color, width = (_qc("accent") if self.hot else _qc("secondary", 0.7)), 2.0
        elif k == "replaced":
            color, width = (_qc("warn") if self.hot else _qc("warn", 0.75)), 1.6
        elif k == "link":
            color, width = (_qc("accent") if self.hot else _qc("accent", 0.45)), 1.3
        else:
            color, width = (_qc("accent") if self.hot else _qc("border")), 1.3
        pen = QPen(color, width + (0.8 if self.hot else 0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if k in ("link", "step") and not self.hot:
            pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self.path)
        if k in ("next", "replaced"):   # punta della freccia
            end = self.path.pointAtPercent(1.0)
            ang = math.radians(-self.path.angleAtPercent(1.0))
            size = 7
            pts = [end, QPointF(end.x() - size * math.cos(ang - 0.45), end.y() - size * math.sin(ang - 0.45)),
                   QPointF(end.x() - size * math.cos(ang + 0.45), end.y() - size * math.sin(ang + 0.45))]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygonF(pts))


class GraphView(QGraphicsView):
    """Il disegno; `activated(rel)` quando si fa clic su un nodo (rel = cosa aprire)."""

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
        self._titles: dict[str, str] = {}
        self._zoom = 1.0

    def tooltip(self, n) -> str:
        if n.kind == "start":
            return tr("Inizio del progetto: le decisioni scritte prima della prima sessione partono da qui")
        if n.kind == "state":
            return tr("Stato attuale (PROJECT.md): va all'IA all'inizio di ogni chat nuova") + (
                "\n" + n.summary if n.summary else "")
        if n.kind == "step":
            return tr("Prossimo passo") + "\n" + n.title
        if n.kind == "decision":
            label = {"in_force": tr("In vigore: va all'IA a ogni chat nuova"),
                     "superseded": tr("Superata"), "removed": tr("Tolta dal progetto")}[n.status]
            out = [n.title, label]
            where = self._titles.get(n.origin)
            if where:
                out.append(tr("Presa in «{note}»").format(note=where))
            if n.replaced_by and self.graph is not None:
                new = self.graph.node(n.replaced_by)
                if new is not None:
                    out.append(tr("Sostituita da: {d}").format(d=new.title))
            return "\n".join(out)
        tip = f"{n.date} · {n.title}" if n.date else n.title
        if n.summary:
            tip += "\n" + n.summary
        if n.files:
            tip += "\n" + tr("File citati: {f}").format(f=", ".join(n.files))
        if n.in_context:
            tip += "\n" + tr("Va all'IA all'inizio di ogni chat nuova")
        return tip

    # ---------------------------------------------------------------- dati e disposizione
    def set_graph(self, graph, current: str | None = None):
        self.graph = graph
        self._titles = {n.rel: n.title for n in graph.nodes if n.kind == "note"}
        self._titles["start"] = tr("Inizio del progetto")
        sc = self.scene()
        sc.clear()
        self.nodes, self.edges = {}, []
        by_origin: dict[str, list] = {}
        for n in graph.nodes:
            if n.kind == "decision":
                by_origin.setdefault(n.origin, []).append(n)
        steps = [n for n in graph.nodes if n.kind == "step"]
        timeline = [n for n in graph.nodes if n.kind in ("start", "note", "state")]
        dec_cx = DEC_X + DEC_W / 2
        y = 0.0
        for t in timeline:
            h = {"start": START_H, "state": STATE_H}.get(t.kind, NOTE_H)
            side = by_origin.get(t.rel, []) if t.kind != "state" else []
            # in vigore prima, poi le superate
            side.sort(key=lambda d: (d.status != "in_force", d.date))
            if t.kind == "state":
                side = steps
            side_h = [STEP_H if s.kind == "step" else DEC_H for s in side]
            block = sum(side_h) + GAP * max(0, len(side) - 1)
            row_h = max(h, block)
            item = _Node(self, t, TIME_W, h)
            item.setPos(0, y + h / 2)
            self.nodes[t.rel] = item
            sy = y
            for s, sh in zip(side, side_h):
                it = _Node(self, s, DEC_W, sh)
                it.setPos(dec_cx, sy + sh / 2)
                self.nodes[s.rel] = it
                sy += sh + GAP
            y += row_h + ROW_GAP
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
        sc.setSceneRect(sc.itemsBoundingRect().adjusted(-30, -24, 30, 24))

    def set_current(self, rel: str | None):
        for r, item in self.nodes.items():
            item.current = r == rel and item.node.kind in ("note", "state")
            item.update()

    def fit(self):
        """Tutto in vista se ci sta senza rimpicciolire troppo; altrimenti a larghezza piena, sulla fine del
        percorso (le sessioni recenti, lo stato attuale e i prossimi passi)."""
        sc = self.scene().sceneRect()
        if sc.isEmpty():
            return
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
        near = (self.graph.neighbours(rel) | {rel}) if (rel and self.graph) else set()
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
        step = 28   # puntini leggeri: si capisce che si può trascinare
        p.setPen(QPen(_qc("hairline"), 1.6))
        x0 = math.floor(rect.left() / step) * step
        y = math.floor(rect.top() / step) * step
        while y < rect.bottom():
            x = x0
            while x < rect.right():
                p.drawPoint(QPointF(x, y))
                x += step
            y += step


class GraphPage(QWidget):
    """Legenda, pulsante «Adatta», il disegno e un riepilogo (o l'invito a salvare, se non ci sono sessioni)."""

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
        bar.addWidget(self.btn_fit, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(bar)
        self.frame = QFrame()
        self.frame.setObjectName("vaultGraphFrame")
        fv = QVBoxLayout(self.frame)
        fv.setContentsMargins(1, 1, 1, 1)
        self.view = GraphView()
        fv.addWidget(self.view)
        v.addWidget(self.frame, 1)
        self.summary = QLabel()
        self.summary.setObjectName("secondary")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.view.activated.connect(self.activated)
        self.btn_fit.clicked.connect(self.view.fit)
        self._fitted = False

    def set_graph(self, graph, current: str | None = None):
        self.view.set_graph(graph, current)
        nodes = graph.nodes
        n_notes = sum(1 for n in nodes if n.kind == "note")
        dec = [n for n in nodes if n.kind == "decision"]
        n_force = sum(1 for d in dec if d.status == "in_force")
        n_steps = sum(1 for n in nodes if n.kind == "step")
        ok, warn, accent, sec = C["ok"], C["warn"], C["accent"], C["secondary"]
        to_ai = tr("va all'IA nella prossima chat")   # fuori dalla f-string (Python 3.10)
        self.legend.setText(
            f'<span style="color:{ok}">▌</span>{tr("in vigore")} &nbsp; '
            f'<span style="color:{sec}"><s>{tr("superata")}</s></span> '
            f'<span style="color:{warn}">⤷</span> {tr("sostituita da")} &nbsp; '
            f'<span style="color:{sec}">○</span> {tr("prossimo passo")} &nbsp; '
            f'<span style="color:{accent}">●</span> {to_ai}')
        if not n_notes and not dec:
            self.summary.setText(tr("Ancora nessuna sessione: salva il progetto (Salva progetto) e qui compariranno "
                                    "le decisioni, quando e perché sono cambiate."))
        else:
            self.summary.setText(tr("{n} sessioni · {f} decisioni in vigore · {s} superate · {p} prossimi passi · "
                                    "un clic apre la nota da cui viene").format(
                n=n_notes, f=n_force, s=len(dec) - n_force, p=n_steps))
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
        if self.view.graph is not None:
            self.set_graph(self.view.graph, next((r for r, i in self.view.nodes.items() if i.current), None))
