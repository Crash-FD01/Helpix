# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminale vero dentro Helpix: xterm.js in una pagina locale, collegato a un PtyProcess."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from .. import theme
from ..pty_process import PtyProcess
from ..theme import C

PAGE = Path(__file__).resolve().parent.parent / "data" / "xterm" / "terminal.html"


class _Bridge(QObject):
    write = Signal(str)
    reset = Signal()
    themeChanged = Signal(str)  # noqa: N815 (nome usato dalla pagina)
    focusTerminal = Signal()    # noqa: N815

    def __init__(self, view: "TerminalView"):
        super().__init__(view)
        self.view = view

    @Slot(str)
    def input(self, data: str):
        self.view.pty.write(data)

    @Slot(int, int)
    def resized(self, cols: int, rows: int):
        self.view.pty.resize(cols, rows)

    @Slot(str)
    def copy(self, text: str):
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def pasteClipboard(self):  # noqa: N802
        self.pasteText(QGuiApplication.clipboard().text())

    @Slot(str)
    def pasteText(self, text: str):  # noqa: N802
        """Ogni incolla nel terminale passa da qui, così lo scudo privacy lo filtra."""
        from .. import privacy
        if text:
            self.view.pty.paste(privacy.filter_paste(text))

    @Slot()
    def ready(self):
        self.view._on_ready()


def _theme() -> dict:
    dark = theme.is_dark()
    t = {"dark": dark, "background": C["term"], "foreground": C["termText"], "cursor": C["termText"],
         "selectionBackground": "#3A5A8C" if dark else "#BFD5F5"}
    if not dark:  # colori ANSI leggibili su fondo chiaro
        t.update(black="#1D1D1F", red="#C4352B", green="#1F7A36", yellow="#8A6100", blue="#0A5BC4",
                 magenta="#9A2FB0", cyan="#0B7A86", white="#6E6E73", brightBlack="#55555A",
                 brightRed="#D93F3F", brightGreen="#248A3D", brightYellow="#9C6F00", brightBlue="#0A66D8",
                 brightMagenta="#A83BC0", brightCyan="#0E8A96", brightWhite="#3A3A3C")
    return t


class TerminalView(QWebEngineView):
    """Mostra un PtyProcess: il testo arriva da self.pty, i tasti vanno a self.pty."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pty = PtyProcess(self)
        self._ready = False
        self._pending: list[str] = []
        page = QWebEnginePage(QWebEngineProfile.defaultProfile(), self)
        self.setPage(page)
        self.bridge = _Bridge(self)
        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        page.setBackgroundColor(QColor(C["term"]))
        self.pty.output.connect(self._output)
        theme.manager().changed.connect(lambda _d: self._send_theme())
        self.setUrl(QUrl.fromLocalFile(str(PAGE)))

    def _on_ready(self):
        self._ready = True
        self._send_theme()
        if self._pending:
            self.bridge.write.emit("".join(self._pending))
            self._pending.clear()

    def _send_theme(self):
        self.page().setBackgroundColor(QColor(C["term"]))
        if self._ready:
            self.bridge.themeChanged.emit(json.dumps(_theme()))

    def _output(self, text: str):
        if self._ready:
            self.bridge.write.emit(text)
        else:
            self._pending.append(text)

    def write_local(self, text: str):
        """Scrive nel terminale un messaggio di Helpix (non va al programma)."""
        self._output(text.replace("\n", "\r\n"))

    def clear(self):
        if self._ready:
            self.bridge.reset.emit()
        self._pending.clear()

    def focus_terminal(self):
        self.setFocus()
        if self._ready:
            self.bridge.focusTerminal.emit()

    def screen_text(self, callback, lines: int = 200):
        """Le ultime righe del terminale come testo semplice (callback con una stringa)."""
        if not self._ready:
            callback("")
            return
        self.page().runJavaScript(f"window.helpixScreen ? helpixScreen({int(lines)}) : ''",
                                  lambda r: callback(r or ""))
