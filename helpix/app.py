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
    argv = helpix_argv(*[a for a in sys.argv[1:] if a not in ("--setup", "--background")])
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
  --background           avvia Helpix senza mostrare la finestra principale (lo usa la finestra rapida)
  --test-shortcut        prova la scorciatoia globale con il desktop (con Helpix chiuso)
  vault cat "nota"       testo di una nota del progetto attivo (beta; Helpix aperto e vault sbloccato)
  vault search "parole"  righe delle note che contengono le parole (beta)
  vault project          PROJECT.md del progetto attivo, senza «Solo per me» (beta)
                         con --out FILE il risultato va anche nel file (serve su Windows)
  --version              mostra la versione
  -h, --help             mostra questo aiuto

Dipendenze di sistema:  python -m helpix.sysdeps check | install
Licenza GPL-3.0-or-later: è software libero, senza alcuna garanzia. Sorgenti: https://github.com/Crash-FD01/Helpix
"""


def _self_test() -> int:
    return _self_test_run()


def _say(msg: str) -> None:
    """Messaggio del self-test: su stdout e, se impostato, nel file HELPIX_SELF_TEST_LOG (Helpix.exe è un programma
    a finestre: la sua console non si vede)."""
    print(msg, flush=True)
    log = os.environ.get("HELPIX_SELF_TEST_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _self_test_run() -> int:
    """Apre il motore web su una pagina vuota e prova i moduli che dipendono dal sistema; codice 0 se va tutto.

    Lo usa la build (pacchetti Linux e installer di Windows) per controllare il programma pronto, senza toccare
    impostazioni o accessi dell'utente."""
    import PySide6.QtWebEngineWidgets  # noqa: F401 - prima della QApplication
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from . import diagnostics, executor, instance, privacy, pty_process, system  # noqa: F401
    if system.IS_WINDOWS:
        from . import global_shortcut, security, winshell  # noqa: F401
        import winpty  # noqa: F401
    if system.IS_WINDOWS and getattr(sys, "frozen", False):
        # il PowerShell 7 incluso c'è ed esegue i comandi (è l'unico che usa il programma installato)
        import subprocess
        exe = winshell.bundled_powershell()
        if not exe:
            _say("self-test: PowerShell 7 incluso non trovato")
            return 1
        if os.environ.get("PATH", "").split(os.pathsep)[0] != os.path.dirname(exe):
            _say("self-test: PowerShell 7 incluso non è il primo nel PATH")
            return 1
        r = subprocess.run(winshell.argv(winshell.encode("$PSVersionTable.PSVersion.Major")), capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode or r.stdout.strip() != "7":
            _say(f"self-test: PowerShell incluso non funziona ({r.returncode}): {r.stdout} {r.stderr}")
            return 1
        # come nel pannello degli agenti: script .ps1 con -File nel terminale (ConPTY)
        import tempfile
        from PySide6.QtCore import QEventLoop
        from .pty_process import PtyProcess
        ps1 = os.path.join(tempfile.mkdtemp(), "self-test.ps1")
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write("Write-Host ('helpix-pty-' + $PSVersionTable.PSVersion.Major)\nexit 3\n")
        pty, out, codes, loop = PtyProcess(), [], [], QEventLoop()
        pty.output.connect(out.append)
        pty.finished.connect(lambda rc: (codes.append(rc), loop.quit()))
        QTimer.singleShot(90000, loop.quit)
        pty.start([exe, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", ps1],
                  os.path.expanduser("~"))
        loop.exec()
        if codes != [3] or "helpix-pty-7" not in "".join(out):
            _say(f"self-test: PowerShell incluso nel terminale (ConPTY): codici {codes}, output {''.join(out)[-500:]!r}")
            return 1
        # giunzioni come quelle dell'installer di Codex, nel terminale (ConPTY)
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(winshell.JUNCTION_PROBE)
        out.clear()
        codes.clear()
        loop = QEventLoop()
        pty.finished.disconnect()
        pty.finished.connect(lambda rc: (codes.append(rc), loop.quit()))
        QTimer.singleShot(120000, loop.quit)
        pty.start([exe, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", ps1],
                  os.path.expanduser("~"))
        loop.exec()
        if "junction-ok" not in "".join(out):
            _say(f"self-test: giunzioni nel terminale: codici {codes}, output {''.join(out)[-1500:]!r}")
            return 1
    result = {"ok": False}
    view = QWebEngineView()

    def loaded(ok):
        result["ok"] = ok
        app.quit()

    view.loadFinished.connect(loaded)
    view.setHtml("<p>Helpix</p>", QUrl("about:blank"))
    QTimer.singleShot(60000, app.quit)
    app.exec()
    if not result["ok"]:
        _say("self-test: il motore web non ha caricato la pagina di prova")
    return 0 if result["ok"] else 1


def _vault_cli(args: list[str]) -> int:
    """`helpix vault cat|search|project …`: chiede la nota a Helpix aperto (canale locale dell'utente).

    Lo usano gli agenti nel terminale per leggere le note del progetto attivo senza file in chiaro su disco."""
    from . import instance
    out_file = None
    if "--out" in args:
        i = args.index("--out")
        out_file = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    op = args[0] if args else ""
    query = " ".join(args[1:]).strip()
    if op not in ("cat", "search", "project") or (op != "project" and not query):
        text, code = 'Uso: helpix vault cat "titolo della nota" | vault search "parole" | vault project [--out FILE]', 2
    else:
        reply = instance.request({"type": "vault", "op": op, "q": query}, instance.socket_path(), timeout=15)
        if reply is None:
            text, code = "Helpix non è aperto: aprilo e apri il progetto.", 1
        else:
            text, code = str(reply.get("text", "")), 0 if reply.get("ok") else 1
    if out_file:
        with open(out_file, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if sys.stdout is not None:  # Helpix.exe su Windows è un programma a finestre: niente console
        try:
            print(text, flush=True)
        except (OSError, UnicodeEncodeError):
            sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
    return code


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) > 1 and argv[1] == "vault":  # progetti (beta): note per gli agenti nel terminale
        return _vault_cli(argv[2:])
    if "--version" in argv:
        print(f"Helpix {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(USAGE.format(version=__version__))
        return 0
    if "--self-test" in argv:  # verifica del programma installato: Qt, motore web, moduli di Windows
        return _self_test()
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

    # --background (dalla finestra rapida con Helpix chiuso): niente finestra principale né schermata iniziale,
    # se l'assistente è già stato scelto almeno una volta
    background = "--background" in argv and "--setup" not in argv and bool(
        settings.get("default_engine") or settings.get("engine"))
    need_start = "--setup" in argv or (not settings.get("skip_setup") and not background)
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
    if background:
        app.setQuitOnLastWindowClosed(False)  # nascosta resta attiva per la finestra rapida
    else:
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
