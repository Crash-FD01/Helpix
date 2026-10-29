# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Esecuzione in background di funzioni bloccanti (rete, screenshot)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


class FuncWorker(QThread):
    done = Signal(object)
    failed = Signal(object)  # l'eccezione

    def __init__(self, fn, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.fn, self.args, self.kwargs = fn, args, kwargs

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            log.info("Operazione in background fallita: %s", exc)
            self.failed.emit(exc)
            return
        self.done.emit(result)
