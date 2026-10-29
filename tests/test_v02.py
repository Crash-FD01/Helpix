# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test della v0.2: riconoscimento comandi copiati e selettore di area (python tests/test_v02.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpix.executor import looks_like_command  # noqa: E402
from helpix.ui.region_selector import RegionSelector, image_rect  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_looks_like_command():
    assert looks_like_command("ls -la /etc") == "ls -la /etc"
    assert looks_like_command("$ sudo ls /root") == "sudo ls /root"
    assert looks_like_command("user@pc:~$ uname -r") == "uname -r"
    assert looks_like_command("cd /var/log && ls") == "cd /var/log && ls"
    assert looks_like_command("LANG=C df -h") == "LANG=C df -h"
    assert looks_like_command("# controlla i log\nls /var/log") == "# controlla i log\nls /var/log"
    assert looks_like_command("root@pc:~# ls /root") == "ls /root"
    assert looks_like_command("Riavvia il computer e riprova") is None
    assert looks_like_command("comandoinesistente123 --help") is None
    assert looks_like_command("") is None
    assert looks_like_command("x" * 5000) is None


def test_image_rect_scaling():
    img = QImage(2000, 1000, QImage.Format.Format_RGB32)  # schermo HiDPI 2x
    r = image_rect(QRect(100, 50, 200, 100), QSize(1000, 500), img)
    assert r == QRect(200, 100, 400, 200), r
    assert image_rect(QRect(900, 400, 500, 500), QSize(1000, 500), img) == QRect(1800, 800, 200, 200)


def _selector(windows=None):
    img = QImage(800, 600, QImage.Format.Format_RGB32)
    img.fill(QColor("navy"))
    sel = RegionSelector(img, windows)
    sel.setGeometry(0, 0, 800, 600)
    sel.show()
    QTest.qWaitForWindowExposed(sel)
    got = {}
    sel.selected.connect(lambda im: got.setdefault("img", im))
    sel.cancelled.connect(lambda: got.setdefault("cancel", True))
    return sel, got


def test_selector_drag_resize_confirm():
    sel, got = _selector()
    QTest.mousePress(sel, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(sel, QPoint(200, 150))
    QTest.mouseMove(sel, QPoint(300, 250))
    QTest.mouseRelease(sel, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    assert sel.sel == QRect(QPoint(100, 100), QPoint(300, 250)), sel.sel
    assert sel.bar.isVisible()
    # ridimensiona dalla maniglia in basso a destra
    br = sel.sel.bottomRight()
    QTest.mousePress(sel, Qt.MouseButton.LeftButton, pos=br)
    QTest.mouseMove(sel, br + QPoint(50, 30))
    QTest.mouseRelease(sel, Qt.MouseButton.LeftButton, pos=br + QPoint(50, 30))
    assert sel.sel.bottomRight() == QPoint(350, 280), sel.sel
    QTest.keyClick(sel, Qt.Key.Key_Return)
    assert got["img"].size() == QSize(251, 181), got["img"].size()


def test_selector_window_click_and_cancel():
    sel, got = _selector([(QRect(400, 300, 300, 200), "Impostazioni")])
    QTest.mouseMove(sel, QPoint(500, 400))
    assert sel.hover and sel.hover[1] == "Impostazioni"
    QTest.mouseClick(sel, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
    assert got["img"].size() == QSize(300, 200)

    sel, got = _selector()
    QTest.keyClick(sel, Qt.Key.Key_Escape)
    assert got.get("cancel") and "img" not in got


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
