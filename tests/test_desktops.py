# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorciatoia della finestra rapida nei vari desktop, con gli schemi veri (python tests/test_desktops.py).

Va lanciato dentro dbus-run-session (per Xfce parte il vero xfconfd). Gli schemi di GNOME, Cinnamon e MATE
devono essere installati (pacchetti gnome-settings-daemon-common, cinnamon-desktop-data,
mate-control-center-common): se mancano, quel desktop viene saltato.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["GSETTINGS_BACKEND"] = "keyfile"  # niente dconf: le impostazioni vanno in un file nella cartella di prova

from helpix import shortcut_setup as ss  # noqa: E402

SCHEMAS = (subprocess.run(["gsettings", "list-schemas"], capture_output=True, text=True).stdout.split() +
           subprocess.run(["gsettings", "list-relocatable-schemas"], capture_output=True, text=True).stdout.split()) \
    if shutil.which("gsettings") else []


def get(schema, key):
    return subprocess.run(["gsettings", "get", schema, key], capture_output=True, text=True, check=True).stdout.strip()


def test_detection():
    cases = {"ubuntu:GNOME": "gnome", "X-Cinnamon": "cinnamon", "Budgie:GNOME": "gnome", "Pantheon": "gnome",
             "zorin:GNOME": "gnome", "KDE": "kde", "XFCE": "xfce", "MATE": "mate", "COSMIC": "cosmic",
             "pop:COSMIC": "cosmic", "Hyprland": "hyprland", "sway": "sway", "niri": "niri", "LXQt": "lxqt",
             "": "other"}
    old = os.environ.get("XDG_CURRENT_DESKTOP")
    try:
        for value, expected in cases.items():
            os.environ["XDG_CURRENT_DESKTOP"] = value
            os.environ.pop("DESKTOP_SESSION", None)
            assert ss.desktop() == expected, (value, ss.desktop())
    finally:
        os.environ["XDG_CURRENT_DESKTOP"] = old or ""


def test_gnome():
    if "org.gnome.settings-daemon.plugins.media-keys" not in SCHEMAS:
        print("  (schemi di GNOME assenti: saltato)")
        return
    base = "org.gnome.settings-daemon.plugins.media-keys"
    subprocess.run(["gsettings", "set", base, "custom-keybindings",
                    "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']"], check=True)
    assert ss.install("gnome") and ss.install("gnome"), "due volte: nessun doppione"
    paths = ss._strv(get(base, "custom-keybindings"))
    assert paths == ["/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/",
                     "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/helpix-quick/"], paths
    schema = f"{base}.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/helpix-quick/"
    assert get(schema, "binding") == "'<Control><Alt>h'" and "--quick" in get(schema, "command")


def test_cinnamon():
    if "org.cinnamon.desktop.keybindings" not in SCHEMAS:
        print("  (schemi di Cinnamon assenti: saltato)")
        return
    base = "org.cinnamon.desktop.keybindings"
    subprocess.run(["gsettings", "set", base, "custom-list", "['__dummy__', 'custom0']"], check=True)
    assert ss.install("cinnamon") and ss.install("cinnamon")
    assert ss._strv(get(base, "custom-list")) == ["__dummy__", "custom0", "helpix-quick"]
    schema = f"{base}.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/helpix-quick/"
    assert get(schema, "binding") == "['<Primary><Alt>h']", get(schema, "binding")
    assert "--quick" in get(schema, "command") and "Helpix" in get(schema, "name")


def test_mate():
    if "org.mate.control-center.keybinding" not in SCHEMAS:
        print("  (schemi di MATE assenti: saltato)")
        return
    assert ss.install("mate")
    schema = "org.mate.control-center.keybinding:/org/mate/desktop/keybindings/helpix-quick/"
    assert get(schema, "binding") == "'<Primary><Alt>h'" and "--quick" in get(schema, "action")


def test_xfce():
    if not shutil.which("xfconf-query") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        print("  (xfconf o D-Bus assenti: saltato)")
        return
    assert ss.install("xfce")
    out = subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", "/commands/custom/<Primary><Alt>h"],
                         capture_output=True, text=True, check=True).stdout
    assert "--quick" in out, out
    assert ss.install("xfce"), "la seconda volta aggiorna"


def test_cosmic():
    path = ss.cosmic_file()
    assert ss.install("cosmic")
    text = path.read_text()
    assert text.startswith("{") and 'modifiers: [Ctrl, Alt], key: "h"' in text and "--quick" in text, text
    # file già pieno di scorciatoie dell'utente: le sue restano, la nostra si aggiunge una volta sola
    path.write_text('{\n    (modifiers: [Super], key: "t"): Spawn("cosmic-term")\n}\n')
    assert ss.install("cosmic") and ss.install("cosmic")
    text = path.read_text()
    assert 'Spawn("cosmic-term"),' in text and text.count("--quick") == 1, text
    assert text.strip().endswith("}") and (path.parent / "custom.helpix-bak").exists()
    path.write_text("formato che non conosco")
    assert not ss.install("cosmic") and path.read_text() == "formato che non conosco", "non tocca file strani"


def test_manual_desktops():
    assert ss.manual_line("hyprland").startswith("bind = CTRL ALT, H, exec, ") and "--quick" in ss.manual_line("hyprland")
    assert ss.manual_line("sway").startswith("bindsym Ctrl+Alt+h exec ")
    assert "spawn" in ss.manual_line("niri")
    assert not ss.install("hyprland") and not ss.install("sway")
    assert set(ss.AUTOMATIC) == {"kde", "gnome", "cinnamon", "mate", "xfce", "cosmic"}


def test_remove_all():
    """Disinstallazione: la scorciatoia di Helpix sparisce da ogni desktop, quelle dell'utente restano."""
    gnome_other = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
    if "org.gnome.settings-daemon.plugins.media-keys" in SCHEMAS:
        ss.install("gnome")
    if "org.cinnamon.desktop.keybindings" in SCHEMAS:
        ss.install("cinnamon")
    if "org.mate.control-center.keybinding" in SCHEMAS:
        ss.install("mate")
    xfce = bool(shutil.which("xfconf-query") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    if xfce:
        ss.install("xfce")
    ss.cosmic_file().write_text('{\n    (modifiers: [Super], key: "t"): Spawn("cosmic-term"),\n}\n')
    ss.install("cosmic")
    ss.install_kde()
    done = ss.remove_all()
    assert {"cosmic", "kde"} <= set(done), done
    text = ss.cosmic_file().read_text()
    assert "--quick" not in text and 'Spawn("cosmic-term")' in text and text.strip().endswith("}"), text
    assert not (ss._apps_dir() / ss.DESKTOP_ID).exists()
    assert not ss.cosmic_file().with_name("custom.helpix-bak").exists(), "nessuna traccia di Helpix"
    if "org.gnome.settings-daemon.plugins.media-keys" in SCHEMAS:
        assert "gnome" in done
        assert ss._strv(get("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings")) == [gnome_other]
    if "org.cinnamon.desktop.keybindings" in SCHEMAS:
        assert "cinnamon" in done
        assert "helpix-quick" not in get("org.cinnamon.desktop.keybindings", "custom-list")
        assert "custom0" in get("org.cinnamon.desktop.keybindings", "custom-list")
    if "org.mate.control-center.keybinding" in SCHEMAS:
        assert "mate" in done
    if xfce:
        assert "xfce" in done
        r = subprocess.run(["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", "/commands/custom/<Primary><Alt>h"],
                           capture_output=True, text=True)
        assert r.returncode != 0, r.stdout
    assert ss.remove_all() == [], "la seconda volta non c'è più niente da togliere"


def test_gnome_tray_extension():
    """GNOME senza area di notifica: AppIndicator da installare, poi da attivare; con l'area già presente o
    fuori da GNOME non serve nulla."""
    if "org.gnome.shell" not in SCHEMAS:
        print("  (schemi di GNOME Shell assenti: saltato)")
        return
    from helpix import sysdeps
    saved = {k: os.environ.get(k) for k in ("XDG_CURRENT_DESKTOP", "XDG_DATA_HOME", "XDG_DATA_DIRS")}
    data = os.path.join(_tmp, "gnome-data")
    os.environ.update(XDG_CURRENT_DESKTOP="GNOME", XDG_DATA_HOME=data, XDG_DATA_DIRS=os.path.join(_tmp, "nessuna") + ":/usr/local/share:/usr/share")
    try:
        subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", "['altra@estensione']"], check=True)
        assert sysdeps.gnome_tray_status() == "install"
        item = [m for m in sysdeps.check(lookup=False).items if m.what == "AppIndicator"]
        assert item and item[0].package == "gnome-shell-extension-appindicator" and not item[0].required

        # installata (dal pacchetto o a mano) ma spenta: basta attivarla, l'altra estensione resta
        ext = os.path.join(data, "gnome-shell", "extensions", sysdeps.APPINDICATOR_UUID)
        os.makedirs(ext)
        open(os.path.join(ext, "metadata.json"), "w").write("{}")
        assert sysdeps.gnome_tray_status() == "enable"
        report = sysdeps.check(lookup=False)
        assert report.gnome_tray and "gnome-shell-extension-appindicator" not in report.packages
        assert sysdeps.enable_gnome_tray()
        assert sysdeps.gnome_enabled_extensions() == ["altra@estensione", sysdeps.APPINDICATOR_UUID]
        assert sysdeps.gnome_tray_status() == "relogin", "attivata: si vedrà dal prossimo accesso"
        assert not sysdeps.check(lookup=False).gnome_tray

        # qualcuno fornisce già l'area di notifica (Ubuntu, Zorin, o dopo il nuovo accesso)
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            from jeepney.bus_messages import message_bus
            from jeepney.io.blocking import open_dbus_connection
            conn = open_dbus_connection(bus="SESSION")
            conn.send_and_get_reply(message_bus.RequestName("org.kde.StatusNotifierWatcher"), timeout=3)
            try:
                assert sysdeps.tray_watcher_present() is True
                assert sysdeps.gnome_tray_status() == "ok"
            finally:
                conn.close()

        # non GNOME (o GNOME «con altro», come Budgie): niente
        os.environ["XDG_CURRENT_DESKTOP"] = "Budgie:GNOME"
        assert sysdeps.gnome_tray_status() == "n/a"
        os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
        assert sysdeps.gnome_tray_status() == "n/a"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_main_window_per_desktop():
    """Finestra principale: scorciatoia impostata da sola dove il portal manca, voci dell'area di notifica,
    messaggio chiaro quando manca l'agente polkit."""
    os.environ.setdefault("XDG_DATA_HOME", os.path.join(_tmp, "data"))
    os.environ.setdefault("XDG_RUNTIME_DIR", os.path.join(_tmp, "run"))
    os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from helpix.config import SecretStore, Settings, ensure_dirs
    from helpix.executor import CommandResult
    from helpix.ui.main_window import MainWindow
    ensure_dirs()

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False, show_tips=False, auto_continue=False)
    win = MainWindow(settings, SecretStore())
    notes = []
    win.notify = lambda text, ms=0: notes.append(text)

    # niente area di notifica (offscreen, come GNOME senza estensione): le voci relative spariscono
    assert win.tray is None and not win.act_to_tray.isVisible() and not win.act_close_tray.isVisible()

    # Cinnamon: il portal non c'è; la richiesta dell'utente imposta subito la scorciatoia nel desktop
    if "org.cinnamon.desktop.keybindings" in SCHEMAS:
        os.environ["XDG_CURRENT_DESKTOP"] = "X-Cinnamon"
        win._shortcut_from_user = True
        win._shortcut_changed("error", "portal GlobalShortcuts assente")
        pump(600)
        assert any("Cinnamon" in n for n in notes), notes
        assert "helpix-quick" in get("org.cinnamon.desktop.keybindings", "custom-list")

    # Hyprland: nessuna impostazione automatica, la finestra mostra la riga da copiare
    os.environ["XDG_CURRENT_DESKTOP"] = "Hyprland"
    seen = {}
    old_exec = QMessageBox.exec

    def fake_exec(box):
        seen["text"] = box.informativeText()
        seen["buttons"] = [b.text() for b in box.buttons()]
        return 0
    QMessageBox.exec = fake_exec
    try:
        win.quick_shortcut_info()
    finally:
        QMessageBox.exec = old_exec
    assert "bind = CTRL ALT, H, exec" in seen["text"] and "hyprland.conf" in seen["text"], seen
    assert "Copia la riga" in seen["buttons"] and "Imposta la scorciatoia nel desktop" not in seen["buttons"]

    # sudo senza agente polkit: messaggio che spiega cosa manca, non «autorizzazione negata»
    res = CommandResult("sudo dnf update", 127, win.session.cwd,
                        "Error executing command as another user: No authentication agent found.", root=True)
    win._command_done(res, "ai", None)
    text = win.terminal.out.toPlainText()
    assert "agente polkit" in text and "autorizzazione negata" not in text, text[-300:]
    win.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
