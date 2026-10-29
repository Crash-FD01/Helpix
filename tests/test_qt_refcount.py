# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""La versione di Qt for Python installata non deve consumare i riferimenti a None.

Qt for Python 6.12.0 con Python 3.10/3.11 toglie un riferimento a None a ogni chiamata senza risultato (setText,
show, resize…): dopo qualche migliaio di chiamate Python si chiude («deallocating None»). Da Python 3.12 None è
immortale e il difetto non si vede, ma il test resta valido: il conteggio non deve calare.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_none_refcount_stable():
    label, timer = QLabel(), QTimer()
    before = sys.getrefcount(None)
    for _ in range(25):  # 100 chiamate bastano a vederlo (1 riferimento perso per chiamata) senza esaurirli
        label.setText("x")
        label.resize(10, 10)
        timer.start(10)
        timer.stop()
    lost = before - sys.getrefcount(None)
    assert lost < 20, (f"Qt for Python {PySide6.__version__} con Python {sys.version.split()[0]} perde {lost} "
                        "riferimenti a None su 100 chiamate: il programma si chiuderebbe (vedi pyproject.toml)")


if __name__ == "__main__":
    test_none_refcount_stable()
    print(f"ok test_none_refcount_stable (Qt for Python {PySide6.__version__}, Python {sys.version.split()[0]})")
