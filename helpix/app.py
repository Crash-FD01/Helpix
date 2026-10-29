# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Punto di ingresso di Helpix."""
from __future__ import annotations

import logging
import os
import sys

from . import __version__


def _system_prefers_dark() -> bool:
    """Preferenza del desktop prima che Qt sia avviato (GNOME e derivati; su Windows il tema delle app)."""
    import shutil
    import subprocess
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False
    if shutil.which("gsettings"):
        try:
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                                 capture_output=True, text=True, timeout=2).stdout
            return "dark" in out
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def _web_color_scheme(theme_mode: str) -> None:
    """Le pagine web leggono prefers-color-scheme da Chromium, che lo fissa all'avvio."""
    dark = theme_mode == "dark" or (theme_mode == "auto" and _system_prefers_dark())
    flag = f"--blink-settings=preferredColorScheme={0 if dark else 1}"
    current = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "preferredColorScheme" not in current:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (current + " " + flag).strip()


def restart() -> None:
    """Riavvia Helpix (serve per applicare una nuova lingua)."""
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from .system import helpix_argv
    argv = helpix_argv(*[a for a in sys.argv[1:] if a != "--setup"])
    QProcess.startDetached(argv[0], argv[1:])
    app = QApplication.instance()
    if app:
        app.quit()


def _test_shortcut() -> int:
    import logging as lg
    import time
    lg.basicConfig(level=lg.INFO, format="%(asctime)s %(name)s: %(message)s")
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    app = QCoreApplication(sys.argv)
    from .global_shortcut import GlobalShortcut
    gs = GlobalShortcut("CTRL+ALT+h", "Helpix: richiesta rapida")
    gs.state.connect(lambda kind, text: print(f"STATO: {kind} {text!r}", flush=True))
    gs.activated.connect(lambda: print("PREMUTA: la scorciatoia è arrivata a Helpix", flush=True))
    print("Chiedo la scorciatoia al desktop; premi Ctrl+Alt+H nei prossimi 30 secondi…", flush=True)
    gs.start()
    end = time.monotonic() + 30
    while time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
    gs.stop()
    del app
    return 0


USAGE = """Helpix {version} — assistente AI per risolvere i problemi del PC

Uso: helpix [opzione]

  (nessuna)              apre Helpix (o porta in primo piano quello già aperto)
  --setup                apre la schermata iniziale (assistente, lingua, tema)
  --quick                mostra o nasconde la finestra rapida (da usare come scorciatoia del desktop)
  --test-shortcut        prova la scorciatoia globale con il desktop (con Helpix chiuso)
  --version              mostra la versione
  -h, --help             mostra questo aiuto

Dipendenze di sistema:  python -m helpix.sysdeps check | install
Licenza GPL-3.0-or-later: è software libero, senza alcuna garanzia. Sorgenti: https://github.com/Crash-FD01/Helpix
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"Helpix {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(USAGE.format(version=__version__))
        return 0
    if "--test-shortcut" in argv:  # diagnosi della scorciatoia globale: stampa cosa risponde il desktop
        return _test_shortcut()
    if "--quick" in argv:  # finestra rapida (di solito dalla scorciatoia globale)
        from .ui.quick_window import run
        return run(argv)
    if "--setup" not in argv:
        from . import instance
        if instance.send_once({"type": "show"}):  # Helpix è già aperto: porto avanti quella finestra
            return 0
    if "--connect-browser" in argv or "--disconnect-browser" in argv:
        from . import native_install
        rest = [a for a in argv[1:] if a not in ("--connect-browser", "--disconnect-browser")]
        return native_install.main(rest + (["--uninstall"] if "--disconnect-browser" in argv else []))

    from .config import LOG_FILE, SecretStore, Settings, ensure_dirs

    ensure_dirs()
    logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings()
    from .i18n import set_language
    set_language(settings.get("language", "auto"))
    _web_color_scheme(settings.get("theme", "auto"))
    from .system import IS_LINUX, is_admin
    if IS_LINUX and is_admin():
        # Chromium rifiuta di girare come root con la sandbox attiva
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    try:  # QtWebEngine va importato prima di creare la QApplication
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        logging.info("PySide6-WebEngine non disponibile: solo motore API")

    from PySide6.QtWidgets import QApplication, QDialog

    from . import theme
    from .providers import PROVIDERS
    from .ui.main_window import MainWindow
    from .ui.setup_dialog import SetupDialog
    from .ui.start_dialog import StartDialog
    from .ui.web_panel import WEBENGINE

    QApplication.setApplicationName("Helpix")
    QApplication.setApplicationVersion(__version__)
    QApplication.setDesktopFileName("helpix")
    app = QApplication(argv)
    secrets = SecretStore()
    theme.setup(app, settings.get("theme", "auto"))
    app.setWindowIcon(theme.app_icon())
    engine = settings.start_engine()
    provider = settings.get("default_provider")
    if provider not in PROVIDERS:
        provider = "anthropic"
    model = settings.start_model(provider)

    need_start = "--setup" in argv or not settings.get("skip_setup")
    if not need_start and engine == "web" and not WEBENGINE:
        need_start = True
    if not need_start and engine == "api" and PROVIDERS[provider]["needs_key"] and not secrets.get(provider):
        dlg = SetupDialog(settings, secrets, first_run=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return 0
        provider, model = dlg.provider, dlg.model
    if need_start:
        dlg = StartDialog(settings, secrets)
        result = dlg.exec()
        if result == StartDialog.RESTART:  # cambio lingua: l'interfaccia va ricostruita da zero
            restart()
            return 0
        if result != QDialog.DialogCode.Accepted:
            return 0
        engine = dlg.engine
        if engine == "api":
            provider, model = dlg.provider, dlg.model

    win = MainWindow(settings, secrets, engine, provider, model)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
