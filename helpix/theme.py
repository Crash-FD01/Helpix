# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tema di Helpix: chiaro, scuro o automatico (segue il sistema), cambiabile al volo.

`C` contiene i colori del tema attivo ed è aggiornato sul posto a ogni cambio: chi
legge `C["..."]` al momento del disegno ottiene sempre il colore giusto. Chi deve
ridisegnarsi si collega a `manager().changed`.
"""
from __future__ import annotations

from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMenu

from .config import DATA_DIR
from .icons import write_svg

DATA = Path(__file__).parent / "data"
ICON_CACHE = DATA_DIR / "cache" / "icons"

LIGHT = {
    "window": "#FFFFFF", "toolbar": "#F6F6F8", "sidebar": "#F2F2F5", "page": "#FFFFFF",
    "text": "#1D1D1F", "secondary": "#6B6B70", "border": "#D9D9DE", "hairline": "#E4E4E8",
    "control": "#FFFFFF", "hover": "#EDEDF0", "pressed": "#E3E3E8",
    "accentBg": "#0A66D8", "accentHover": "#0857B8", "accentFg": "#0A66D8", "tint": "#E5EFFD",
    "bubble": "#F0F0F3", "code": "#F4F4F6", "sheet": "#FFFFFF", "selected": "#F1F6FE",
    "warnText": "#7A4B00", "warnBg": "#FFF1D6", "okText": "#146C2E", "okBg": "#DDF4E3",
    "errText": "#B3261E", "errBg": "#FCE4E2", "term": "#FBFBFC", "termText": "#1D1D1F",
    "prompt": "#146C2E", "segBg": "#E6E6EA", "segOn": "#FFFFFF", "winBtn": "#E6E6EA",
    "switchOff": "#C7C7CC", "switchOn": "#30B158", "scroll": "#C7C7CC", "dim": "rgba(0,0,0,0.42)",
}
DARK = {
    "window": "#1C1C1E", "toolbar": "#242426", "sidebar": "#202022", "page": "#1C1C1E",
    "text": "#F2F2F4", "secondary": "#9A9AA1", "border": "#3A3A3E", "hairline": "#2E2E32",
    "control": "#2C2C2F", "hover": "#343438", "pressed": "#3C3C40",
    "accentBg": "#1C6BE0", "accentHover": "#165CC4", "accentFg": "#5AA2FF", "tint": "#16304F",
    "bubble": "#2C2C2F", "code": "#141416", "sheet": "#2A2A2D", "selected": "#1A2A40",
    "warnText": "#FFD28A", "warnBg": "#3A2D14", "okText": "#7EE2A0", "okBg": "#173B24",
    "errText": "#FF9B94", "errBg": "#3D1C1A", "term": "#141416", "termText": "#E4E4E7",
    "prompt": "#7EE2A0", "segBg": "#2A2A2D", "segOn": "#48484D", "winBtn": "#333337",
    "switchOff": "#48484D", "switchOn": "#30B158", "scroll": "#48484D", "dim": "rgba(0,0,0,0.5)",
}
# nomi usati dal codice precedente
for _t in (LIGHT, DARK):
    _t.update(bg=_t["window"], panel=_t["toolbar"], panel2=_t["control"], muted=_t["secondary"],
              accent=_t["accentFg"], accent2=_t["accentHover"], user=_t["bubble"],
              ok=_t["okText"], warn=_t["warnText"], err=_t["errText"])

C: dict = dict(LIGHT)
_state = {"mode": "auto", "dark": False, "busy": False}

STYLE = Template("""
QWidget { color: $text; }
QMainWindow, QDialog, #central { background: $window; }
QToolTip { background: $sheet; color: $text; border: 1px solid $border; padding: 5px 8px; border-radius: 6px; }
#central[frameless="true"] { border: 1px solid $border; }
QMainWindow[rounded="true"], #central[rounded="true"] { background: transparent; border: none; }
#toolbar[rounded="true"] { background: transparent; border: none; }

#toolbar { background: $toolbar; border-bottom: 1px solid $hairline; }
#vsep { background: $hairline; }

QPushButton { background: $control; color: $text; border: 1px solid $border; border-radius: 8px;
    padding: 0 14px; min-height: 32px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:disabled { color: $secondary; }
QPushButton#primary { background: $accentBg; color: #FFFFFF; border: none; font-weight: 600; }
QPushButton#primary:hover { background: $accentHover; }
QPushButton#primary:disabled { background: $segBg; color: $secondary; }
QPushButton#plain { background: transparent; border: none; color: $accentFg; padding: 0 4px; }
QPushButton#plain:hover { text-decoration: underline; }
QPushButton#danger { color: $errText; }

QToolButton { background: transparent; color: $text; border: none; border-radius: 8px; padding: 4px 8px; }
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $pressed; }
QToolButton:checked { background: $tint; color: $accentFg; }
QToolButton:disabled { color: $secondary; }
QPushButton#picker { background: $control; border: 1px solid $border; border-radius: 8px; padding: 0; text-align: left; }
QPushButton#picker:hover { background: $hover; }
QPushButton#picker::menu-indicator { image: none; width: 0; }
QToolButton#pill { background: $control; border: 1px solid $border; padding: 0 10px; min-height: 30px; }
QToolButton#pill:hover { background: $hover; }
QToolButton::menu-indicator { image: none; width: 0; }
#winBtn { background: $winBtn; border-radius: 12px; padding: 0; }
#winBtn:hover { background: $pressed; }
#winClose:hover { background: #E0443E; }

#capsule { background: $accentBg; border-radius: 8px; }
#capsule QToolButton { background: transparent; color: #FFFFFF; font-weight: 600; border-radius: 0; padding: 0 12px; }
#capsule QToolButton#capsuleMain { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
#capsule QToolButton#capsuleMore { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
#capsule QToolButton:hover { background: $accentHover; }
#capsule QToolButton:pressed { background: $accentHover; }
#capsuleSep { background: rgba(255,255,255,0.35); }
#capsule QToolButton#capsuleMore { padding: 0; }

#seg { background: $segBg; border-radius: 8px; }
#seg QToolButton { color: $secondary; border-radius: 6px; padding: 3px 14px; }
#seg QToolButton:checked { background: $segOn; color: $text; font-weight: 600; }
#seg QToolButton:hover:!checked { color: $text; background: transparent; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QListWidget {
    background: $control; color: $text; border: 1px solid $border; border-radius: 8px; padding: 6px 10px;
    selection-background-color: $accentBg; selection-color: #FFFFFF; }
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus { border: 1px solid $accentFg; }
QComboBox { background: $control; color: $text; border: 1px solid $border; border-radius: 8px;
    padding: 4px 28px 4px 10px; min-height: 22px; }
QComboBox:hover { background: $hover; }
QComboBox:editable { background: $control; }
QComboBox::drop-down { border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url($chevron); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $sheet; border: 1px solid $border; padding: 4px; outline: none;
    selection-background-color: $accentBg; selection-color: #FFFFFF; }
QListWidget { padding: 4px; outline: none; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background: $accentBg; color: #FFFFFF; }

QMenu { background: $sheet; border: 1px solid $border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 18px 7px 10px; border-radius: 6px; color: $text; }
QMenu::item:selected { background: $accentBg; color: #FFFFFF; }
QMenu::item:disabled { color: $secondary; }
QMenu::icon { padding-left: 8px; }
QMenu::separator { height: 1px; background: $hairline; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; padding-left: 6px; }
QMenu::indicator:checked { image: url($checkAccent); }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border; background: $control; }
QCheckBox::indicator:checked { background: $accentBg; border: 1px solid $accentBg; image: url($checkWhite); }

QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 12px; padding: 12px 10px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: $secondary; }

QScrollArea { border: none; background: transparent; }
#chatContainer, #chatScroll, #commandWrap { background: $page; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0; background: none; }

QSplitter::handle { background: $hairline; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

#sidebar, QTreeView { background: $sidebar; border: none; outline: none; }
QTreeView::item { padding: 4px 2px; border-radius: 6px; }
QTreeView::item:selected { background: $tint; color: $accentFg; }
QTreeView::item:hover:!selected { background: $hover; }

#title { font-size: 13pt; font-weight: 600; }
#heading, #setupTitle { font-size: 18pt; font-weight: 700; }
#secondary, #meta, #noteLabel { color: $secondary; }
#noteLabel { font-style: italic; }

#sheet { background: $sheet; border: 1px solid $border; border-radius: 14px; }
#group { background: $sheet; border: 1px solid $border; border-radius: 12px; }
#notice { background: $tint; border: none; border-radius: 12px; }
#codeChip { background: $code; border-radius: 8px; padding: 8px 12px; }
#iconBadge { background: $tint; border-radius: 9px; }
#okBadge { background: $okBg; border-radius: 16px; }
#errBadge { background: $errBg; border-radius: 16px; }
#pillWarn { background: $warnBg; color: $warnText; border-radius: 10px; padding: 3px 10px; font-weight: 500; }
#pillErr { background: $errBg; color: $errText; border-radius: 10px; padding: 3px 10px; font-weight: 500; }
#pillOk { background: $okBg; color: $okText; border-radius: 10px; padding: 3px 10px; font-weight: 500; }
#avatar { background: $tint; color: $accentFg; font-weight: 600; }
#toast { background: $sheet; color: $text; border: 1px solid $border; border-radius: 18px; padding: 8px 16px; }

#userBubble { background: $bubble; border-radius: 16px; }
#assistantBubble { background: transparent; }
#codeCard { background: $code; border: none; border-radius: 10px; }
#codeCard QPlainTextEdit, #outputBubble QPlainTextEdit, #codeChip QPlainTextEdit { background: transparent; border: none; padding: 0; }
#outputBubble { background: $code; border: 1px solid $hairline; border-radius: 10px; }
#errorBubble { background: $errBg; border: none; border-radius: 10px; color: $errText; }
#thumbBox { background: $control; border: 1px solid $border; border-radius: 8px; }
#composer { background: $page; border-top: 1px solid $hairline; }
#badgeRoot { color: $warnText; font-weight: 600; }
#badgeDanger { color: $errText; font-weight: 600; }
#badgeOk { color: $okText; font-weight: 600; }

#terminalPanel, #terminalOut, #terminalInput { background: $term; color: $termText; }
#terminalBar { background: $term; border-bottom: 1px solid $hairline; }
#terminalInputRow { background: $term; border-top: 1px solid $hairline; }
#terminalOut, #terminalInput { border: none; border-radius: 0; }
#promptLabel, #cwdLabel { color: $prompt; }

#selectorBar { background: $sheet; border: 1px solid $border; border-radius: 10px; }
#serviceRow { background: transparent; border: none; border-radius: 0; text-align: left; padding: 0; min-height: 58px; }
#serviceRow:hover { background: $hover; }
#serviceRow[selected="true"] { background: $selected; }
#rowSep { background: $hairline; }
""")


class _Manager(QObject):
    changed = Signal(bool)  # True = scuro


_manager: _Manager | None = None


def manager() -> _Manager:
    global _manager
    if _manager is None:
        _manager = _Manager()
    return _manager


def prepare_menu(menu: QMenu) -> QMenu:
    """Menu con angoli arrotondati: la finestra del menu deve avere sfondo trasparente.

    Va chiamata su ogni menu (e sottomenu) prima che venga mostrato. Niente filtri di eventi
    globali: con QtWebEngine provocano crash.
    """
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    return menu


def is_dark() -> bool:
    return _state["dark"]


def mode() -> str:
    return _state["mode"]


def _system_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def _request_scheme(theme_mode: str) -> None:
    """Comunica il tema anche a Qt (Qt >= 6.8): così le pagine web ricevono prefers-color-scheme."""
    hints = QGuiApplication.styleHints()
    if not hasattr(hints, "setColorScheme"):
        return
    scheme = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(theme_mode, Qt.ColorScheme.Unknown)
    hints.setColorScheme(scheme)


def load_fonts(app: QApplication) -> None:
    for f in (DATA / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))
    if "Inter" in QFontDatabase.families():
        font = QFont("Inter", 10)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        app.setFont(font)


def mono_font(size: int | None = None) -> QFont:
    if "JetBrains Mono" in QFontDatabase.families():
        font = QFont("JetBrains Mono", size or 10)
    else:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if size:
            font.setPointSize(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def app_icon() -> QIcon:
    ic = QIcon()
    for f in sorted((DATA / "icons").glob("helpix-*.png")):
        ic.addFile(str(f))
    return ic if not ic.isNull() else QIcon.fromTheme("help-browser")


def logo_pixmap(size: int):
    """Icona dell'app in alta risoluzione per la barra e la finestra di avvio."""
    pix = app_icon().pixmap(size * 3, size * 3)
    pix.setDevicePixelRatio(3)
    return pix


def _apply() -> None:
    app = QApplication.instance()
    if app is None or _state["busy"]:
        return
    _state["busy"] = True
    try:
        _request_scheme(_state["mode"])
        _apply_now(app)
    finally:
        _state["busy"] = False


def _apply_now(app) -> None:
    dark = _state["mode"] == "dark" or (_state["mode"] == "auto" and _system_dark())
    _state["dark"] = dark
    C.clear()
    C.update(DARK if dark else LIGHT)

    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: C["window"], QPalette.ColorRole.WindowText: C["text"],
        QPalette.ColorRole.Base: C["control"], QPalette.ColorRole.AlternateBase: C["toolbar"],
        QPalette.ColorRole.Text: C["text"], QPalette.ColorRole.Button: C["control"],
        QPalette.ColorRole.ButtonText: C["text"], QPalette.ColorRole.Highlight: C["accentBg"],
        QPalette.ColorRole.HighlightedText: "#FFFFFF", QPalette.ColorRole.Link: C["accentFg"],
        QPalette.ColorRole.ToolTipBase: C["sheet"], QPalette.ColorRole.ToolTipText: C["text"],
        QPalette.ColorRole.PlaceholderText: C["secondary"], QPalette.ColorRole.Mid: C["border"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(C["secondary"]))
    app.setPalette(pal)

    tokens = dict(C)
    tokens["chevron"] = write_svg(ICON_CACHE, "chevron-down", C["secondary"])
    tokens["checkWhite"] = write_svg(ICON_CACHE, "check", "#FFFFFF", 3)
    tokens["checkAccent"] = write_svg(ICON_CACHE, "check", C["accentFg"], 3)
    app.setStyleSheet(STYLE.substitute(tokens))
    manager().changed.emit(dark)


def setup(app: QApplication, theme_mode: str = "auto") -> None:
    app.setStyle("Fusion")
    load_fonts(app)
    try:
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: _apply() if _state["mode"] == "auto" else None)
    except AttributeError:
        pass
    _state["mode"] = theme_mode if theme_mode in ("auto", "light", "dark") else "auto"
    _apply()


def set_mode(theme_mode: str) -> None:
    _state["mode"] = theme_mode if theme_mode in ("auto", "light", "dark") else "auto"
    _apply()


def toggle() -> str:
    """Passa dal tema attuale all'opposto (esce da «automatico») e restituisce la nuova modalità."""
    set_mode("light" if is_dark() else "dark")
    return _state["mode"]


def apply(app, theme_mode: str = "auto") -> None:  # compatibilità con il codice precedente
    setup(app, theme_mode)
