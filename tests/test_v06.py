# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test v0.6: icone dei servizi e assistente predefinito (python tests/test_v06.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpix import site_icons  # noqa: E402
from helpix.config import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_icon_cache_keeps_best():
    small = QImage(32, 32, QImage.Format.Format_ARGB32)
    small.fill(QColor("red"))
    big = QImage(180, 180, QImage.Format.Format_ARGB32)
    big.fill(QColor("green"))
    assert site_icons.cached_size("claude") == 0
    assert site_icons.store("claude", small) and site_icons.cached_size("claude") == 32
    assert site_icons.store("claude", big) and site_icons.cached_size("claude") == 180
    assert not site_icons.store("claude", small)  # non si torna a un'icona peggiore
    pix = site_icons.pixmap("claude", 20)
    assert pix.width() == 60 and pix.devicePixelRatio() == 3  # alta risoluzione
    assert not site_icons.pixmap("gemini", 20).isNull()  # senza icona: piastrella con l'iniziale
    assert site_icons.provider_key("openai") == "chatgpt"


def test_defaults():
    s = Settings()
    s.data.update(engine="api", web_site="gemini")
    assert s.start_engine() == "api" and s.start_site() == "gemini"
    s.data.update(default_engine="web", default_site="claude")
    assert s.start_engine() == "web" and s.start_site() == "claude"
    s.data.update(default_provider="anthropic", default_model="claude-opus-5-5")
    s.data.setdefault("models", {})["anthropic"] = "claude-haiku-5-5"
    assert s.start_model("anthropic") == "claude-opus-5-5"
    assert s.start_model("openai") == s.model_for("openai")


def test_google_services_open_in_system_browser():
    assert "gemini" in Settings().get("external_sites")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
