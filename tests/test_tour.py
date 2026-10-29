# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Giro guidato e consiglio del giorno (python tests/test_tour.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from helpix import i18n  # noqa: E402
from helpix.config import SecretStore, Settings, ensure_dirs  # noqa: E402

ensure_dirs()


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def window(**extra):
    from helpix.ui.main_window import MainWindow
    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False, **extra)
    win = MainWindow(settings, SecretStore())
    win.resize(1100, 700)
    win.show()
    return win, settings


def test_first_run_tour():
    win, settings = window()
    pump(1300)
    tour = win.tour
    assert tour is not None and tour.mode == "tour" and tour.step.key == "welcome", "primo avvio: giro completo"
    assert tour.geometry() == win.centralWidget().rect()
    b = tour.bubble
    assert b.counter.text() == f"1 di {len(tour.steps)}" and not b.back.isEnabled()

    # avanti: la zona illuminata è il pulsante dell'assistente, la nuvoletta lo indica da sotto
    b.next.click()
    pump(300)
    assert tour.step.key == "picker"
    picker = QRectFfrom(win.picker, tour)
    assert tour.hole.contains(picker.center()) and b.tail_side == "top"
    assert b.geometry().top() >= tour.hole.bottom(), "nuvoletta sotto il pulsante"

    # tastiera: frecce, Invio
    QTest.keyClick(tour, Qt.Key.Key_Right)
    QTest.keyClick(tour, Qt.Key.Key_Left)
    assert tour.step.key == "picker"
    for _ in range(3):
        QTest.keyClick(tour, Qt.Key.Key_Return)
    assert tour.step.key == "shot"

    # zona grande (la chat): nuvoletta dentro, sotto la barra
    while tour.step.key != "area":
        tour.backward()
    pump(300)
    assert b.tail_side is None and b.geometry().top() > win.toolbar.geometry().bottom()

    # la spunta cambia l'impostazione
    b.show_tips.setChecked(False)
    assert settings.get("show_tips") is False
    b.show_tips.setChecked(True)

    # Esc chiude e segna il giro come fatto
    QTest.keyClick(tour, Qt.Key.Key_Escape)
    pump(50)
    assert win.tour is None and settings.get("tour_done") is True

    # fino in fondo: «Fine» sull'ultimo passo
    win.start_tour()
    t = win.tour
    while t.step.key != "bye":
        t.forward()
    assert t.bubble.next.text() == "Fine" and not t.bubble.skip.isVisible()
    t.bubble.next.click()
    pump(50)
    assert win.tour is None
    win.close()


def test_tip_of_the_day_and_opt_out():
    win, settings = window(tour_done=True, tip_index=0)
    pump(1300)
    tip = win.tour
    assert tip is not None and tip.mode == "tip", "dopo il primo giro: un consiglio"
    assert all(s.tip for s in tip.steps) and tip.bubble.counter.text() == "Lo sapevi?"
    # non blocca la finestra: la maschera copre solo nuvoletta e alone
    assert not tip.mask().isEmpty() and not tip.mask().contains(QPoint(5, tip.height() - 5))
    first = tip.step.key
    tip.bubble.next.click()  # «Altro consiglio»
    assert tip.step.key != first and settings.get("tip_index") == tip.index
    tip.bubble.skip.click()  # «Giro completo»
    pump(50)
    assert win.tour is not None and win.tour.mode == "tour"
    win.tour.close_tour()

    # spunta tolta: niente suggerimenti all'avvio
    settings.set("show_tips", False)
    win._startup_tips()
    assert win.tour is None
    win.close()

    win2, _ = window(tour_done=True, show_tips=False)
    pump(1300)
    assert win2.tour is None
    assert not win2.act_tips.isChecked()
    win2.act_tips.setChecked(True)
    assert win2.settings.get("show_tips") is True
    win2.close()


def test_lock_closes_tour_without_marking_done():
    win, settings = window(tour_done=False, show_tips=False)
    win.start_tour()
    from helpix import security
    from pathlib import Path
    if not security.unlock_available():
        win.tour.close_tour(mark_done=False)
    else:
        security.POLICY_FILE = Path(_tmp) / "p.policy"
        security.POLICY_FILE.write_text("<policyconfig/>", encoding="utf-8")
        settings.set("lock_enabled", True)
        win.lock()
    assert win.tour is None and not settings.get("tour_done")
    win.close()


def test_start_screen_from_settings():
    """La schermata iniziale si riapre dall'app; la spunta nel menu decide se mostrarla all'avvio."""
    from PySide6.QtWidgets import QDialog, QLabel
    from helpix.ui import start_dialog
    win, settings = window(tour_done=True, show_tips=False)  # window() salta già la schermata (skip_setup)
    assert not win.act_start_screen.isChecked(), "saltata: la spunta è spenta"
    win.act_start_screen.setChecked(True)
    assert settings.get("skip_setup") is False
    win.act_start_screen.setChecked(False)
    assert settings.get("skip_setup") is True

    old = start_dialog.StartDialog.exec
    seen = {}

    def choose_claude(dlg):
        seen["remember"] = dlg.remember.isChecked()
        seen["hint"] = any("Impostazioni › Schermata iniziale" in w.text() for w in dlg.findChildren(QLabel))
        dlg.engine, dlg.site = "web", "claude"
        return QDialog.DialogCode.Accepted
    start_dialog.StartDialog.exec = choose_claude
    try:
        win.open_start_screen()
    finally:
        start_dialog.StartDialog.exec = old
    assert seen["remember"] and seen["hint"], seen
    assert win.engine == "web" and win.web.site == "claude"
    win.close()


def test_english():
    i18n.set_language("en")
    try:
        from helpix.ui.tour import steps_for

        class W:
            engine = "web"
        steps = steps_for(W())
        assert steps[0].title.startswith("Hi, I'm Helpix")
        area = next(s for s in steps if s.key == "area")
        assert "real page" in area.body()
    finally:
        i18n.set_language("it")


def QRectFfrom(widget, tour):
    from PySide6.QtCore import QRectF
    return QRectF(widget.mapTo(tour.host, QPoint(0, 0)), widget.size().toSizeF())


if __name__ == "__main__":
    import traceback
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
            except BaseException:  # noqa: BLE001 - QtWebEngine non chiude da solo dopo un errore
                traceback.print_exc()
                os._exit(1)
            print("ok", name, flush=True)
    os._exit(0)
