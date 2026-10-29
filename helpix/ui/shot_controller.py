# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regia dello screenshot: nasconde Helpix, cattura, mostra il selettore, ripristina la finestra.

Modalità:
- "smart":  su X11 schermo congelato + selezione di un'area o clic su una finestra;
            su Wayland la selezione dell'area dello strumento del desktop (Spectacle su KDE)
- "full":   schermo intero, senza selezione
- "window": dialogo di sistema (xdg-desktop-portal), l'unico modo per scegliere
            una finestra su Wayland
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QImage

from ..system import IS_WINDOWS
from ..screenshot import (ScreenshotCancelled, ScreenshotError, capture_area_native, capture_external,
                          capture_full_external, is_x11, qt_grab_full_image, save_image, windows_window_rects,
                          x11_window_rects)
from .region_selector import RegionSelector
from .workers import FuncWorker


class ScreenshotController(QObject):
    captured = Signal(str)     # percorso del PNG
    failed = Signal(str)       # messaggio d'errore
    finished = Signal()        # sempre, alla fine (per ripristinare la finestra)

    def __init__(self, window, settings):
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.busy = False
        self._worker = None
        self._selector = None

    def start(self, mode: str = "smart", delay: int = 0):
        if self.busy:
            return
        self.busy = True
        hide = bool(self.settings.get("hide_on_screenshot", True))
        # Su Wayland Helpix resta dov'è: nascondere la finestra fa riordinare le altre al compositor
        # e un'app non può togliersi da sola dalla riduzione a icona. La selezione dell'area dello
        # strumento del desktop (Spectacle, cattura di GNOME) copre comunque tutto lo schermo.
        hide = hide and (is_x11() or IS_WINDOWS)
        if hide:
            self.window.hide()
        wait = (450 if hide else 80) + max(delay, 0) * 1000
        QTimer.singleShot(wait, lambda: self._capture(mode))

    # ------------------------------------------------------------ cattura
    def _capture(self, mode: str):
        if IS_WINDOWS:  # come su X11: schermo congelato e selezione di Helpix (clic su una finestra per sceglierla)
            try:
                image, geo = qt_grab_full_image()
            except ScreenshotError as exc:
                self._fail(str(exc))
                return
            if mode == "full":
                self._done_image(image)
            else:
                self._select(image, geo, self._native_windows(image, geo, windows_window_rects()))
            return
        if mode == "window":
            self._in_thread(capture_external, True, self._done_path)
            return
        if is_x11():
            try:
                image, geo = qt_grab_full_image()
            except ScreenshotError as exc:
                self._fail(str(exc))
                return
            if mode == "full":
                self._done_image(image)
            else:
                self._select(image, geo, self._x11_windows(image, geo))
            return
        if mode == "full":
            self._in_thread(capture_full_external, None, self._done_path)
            return
        # Wayland: selezione con lo strumento del desktop (niente schermo congelato a tutto schermo)
        self._in_thread(capture_area_native, None, self._done_path)

    def _in_thread(self, fn, arg, on_done):
        args = () if arg is None else (arg,)
        self._worker = FuncWorker(fn, *args, parent=self)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(lambda exc: self._fail(exc))
        self._worker.start()

    @staticmethod
    def _x11_windows(image: QImage, geo: QRect) -> list[tuple[QRect, str]]:
        return ScreenshotController._native_windows(image, geo, x11_window_rects())

    @staticmethod
    def _native_windows(image: QImage, geo: QRect, rects) -> list[tuple[QRect, str]]:
        """Finestre in coordinate del selettore (che copre tutto il desktop virtuale)."""
        scale = image.width() / max(geo.width(), 1)  # pixel fisici per pixel logico
        out = []
        for (x, y, w, h), title in rects:
            r = QRect(round(x / scale) - geo.x(), round(y / scale) - geo.y(), round(w / scale), round(h / scale))
            out.append((r, title))
        return out

    def _select(self, image: QImage, geo: QRect, windows, screen=None):
        sel = RegionSelector(image, windows)
        sel.selected.connect(self._done_image)
        sel.cancelled.connect(lambda: self._fail(ScreenshotCancelled("annullato")))
        self._selector = sel
        if screen is not None:
            sel.setScreen(screen)
            sel.showFullScreen()
        else:
            sel.setGeometry(geo)
            sel.show()
        sel.raise_()
        sel.activateWindow()

    # ------------------------------------------------------------ esito
    def _done_image(self, image: QImage):
        try:
            self._done_path(save_image(image))
        except ScreenshotError as exc:
            self._fail(str(exc))

    def _done_path(self, path: str):
        self._finish()
        self.captured.emit(path)

    def _fail(self, exc):
        self._finish()
        if not isinstance(exc, ScreenshotCancelled):
            self.failed.emit(str(exc))

    def _finish(self):
        self.busy = False
        self._selector = None
        self.finished.emit()
