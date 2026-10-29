# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Componenti in stile Apple riutilizzati da tutta l'interfaccia, sensibili al tema."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal, Property
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QSizePolicy, QToolButton, QWidget)

from .. import theme
from ..icons import icon
from ..theme import C
from ..i18n import tr


def avatar_icon(letter: str, size: int = 20) -> QIcon:
    scale = 3
    img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C["tint"]))
    p.drawEllipse(0, 0, size * scale, size * scale)
    font = QFont(QFont().family(), 1)
    font.setPixelSize(int(size * scale * 0.52))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor(C["accentFg"]))
    p.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignmentFlag.AlignCenter, letter[:1].upper())
    p.end()
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(scale)
    return QIcon(pix)


class IconButton(QToolButton):
    """Pulsante con sola icona (o icona + testo), ricolorato a ogni cambio di tema."""

    def __init__(self, name: str, tip: str, checkable: bool = False, text: str = "", size: int = 32,
                 icon_size: int = 18, color_key: str = "text"):
        super().__init__()
        self._name, self._color_key, self._isz = name, color_key, icon_size
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        if text:
            self.setText(text)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.setMinimumHeight(size)
        else:
            self.setFixedSize(size, size)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.toggled.connect(lambda _on: self.refresh())
        theme.manager().changed.connect(lambda _d: self.refresh())
        self.refresh()

    def set_icon_name(self, name: str):
        self._name = name
        self.refresh()

    def refresh(self):
        color = C["accentFg"] if self.isChecked() else C[self._color_key]
        self.setIcon(icon(self._name, color, self._isz, disabled=C["secondary"]))


class Capsule(QFrame):
    """Pulsante principale a capsula in due parti: azione + menu (es. Screenshot ▾)."""

    clicked = Signal()

    def __init__(self, text: str, icon_name: str, menu, tip: str = "", menu_tip: str = ""):
        super().__init__()
        self.setObjectName("capsule")
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.main = QToolButton()
        self.main.setObjectName("capsuleMain")
        self.main.setText(text)
        self.main.setToolTip(tip or text)
        self.main.setIcon(icon(icon_name, "#FFFFFF", 16, 2))
        self.main.setIconSize(QSize(16, 16))
        self.main.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.main.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main.setFixedHeight(32)
        self.main.clicked.connect(self.clicked.emit)
        h.addWidget(self.main)
        sep = QFrame()
        sep.setObjectName("capsuleSep")
        sep.setFixedSize(1, 18)
        h.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
        self.more = QToolButton()
        self.more.setObjectName("capsuleMore")
        self.more.setIcon(icon("chevron-down", "#FFFFFF", 14, 2.2))
        self.more.setIconSize(QSize(14, 14))
        self.more.setToolTip(menu_tip or tr("Altre opzioni"))
        self.more.setAccessibleName(menu_tip or tr("Altre opzioni"))
        self.more.setFixedSize(30, 32)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.setMenu(menu)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        h.addWidget(self.more)

    def set_tooltip(self, text: str):
        self.main.setToolTip(text)


class Segmented(QFrame):
    """Controllo segmentato (es. Automatico | Chiaro | Scuro)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str):
        super().__init__()
        self.setObjectName("seg")
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, label in options:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            h.addWidget(b)

    def set_current(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class Switch(QAbstractButton):
    """Interruttore on/off animato."""

    def __init__(self, checked: bool = False, label: str = ""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self.setAccessibleName(label)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self.toggled.connect(self._animate)
        theme.manager().changed.connect(lambda _d: self.update())

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self):  # noqa: N802
        return QSize(42, 24)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(C["switchOff"]), QColor(C["switchOn"])
        t = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 42, 24), 12, 12)
        p.setBrush(QColor(0, 0, 0, 40))
        x = 2 + t * 18
        p.drawEllipse(QRectF(x, 3, 20, 20))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 2, 20, 20))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(C["accentFg"]))
            p.drawRoundedRect(QRectF(0.5, 0.5, 41, 23), 12, 12)
        p.end()


class VSep(QFrame):
    def __init__(self, height: int = 20):
        super().__init__()
        self.setObjectName("vsep")
        self.setFixedSize(1, height)


class Toast(QLabel):
    """Avviso breve che compare in basso al centro e sparisce da solo."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade.setDuration(180)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self.hide()

    def show_message(self, text: str, ms: int = 4500, bottom: int = 24):
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        w = min(self.sizeHint().width(), parent.width() - 40)
        self.setFixedWidth(w)
        self.move((parent.width() - w) // 2, parent.height() - self.height() - bottom)
        self.raise_()
        self._fade.stop()
        self._fx.setOpacity(1.0)
        self.show()
        self._timer.start(ms)

    def _hide(self):
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()


class WindowControls(QWidget):
    """Riduci / ingrandisci / chiudi per la barra integrata."""

    def __init__(self, window):
        super().__init__()
        self.win = window
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 4, 0)
        h.setSpacing(8)
        self.btns = {}
        for key, tip, slot in (("minimize", tr("Riduci a icona"), window.showMinimized),
                               ("maximize", tr("Ingrandisci"), self._toggle_max),
                               ("x", tr("Chiudi"), window.close)):
            b = QToolButton()
            b.setObjectName("winClose" if key == "x" else "winBtn")
            if key == "x":
                b.setProperty("class", "win")
            b.setFixedSize(24, 24)
            b.setIconSize(QSize(12, 12))
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.clicked.connect(slot)
            h.addWidget(b)
            self.btns[key] = b
        theme.manager().changed.connect(lambda _d: self.refresh())
        self.refresh()

    def _toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def refresh(self):
        self.btns["minimize"].setIcon(icon("minimize", C["text"], 12, 2))
        self.btns["maximize"].setIcon(icon("restore" if self.win.isMaximized() else "maximize", C["text"], 12, 2))
        self.btns["x"].setIcon(icon("x", C["text"], 12, 2))
        style = f"background: {C['winBtn']}; border-radius: 12px; padding: 0;"
        self.btns["x"].setStyleSheet(f"QToolButton {{ {style} }} QToolButton:hover {{ background: #E0443E; }}")
