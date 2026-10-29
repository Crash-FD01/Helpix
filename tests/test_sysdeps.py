# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dipendenze di sistema (python tests/test_sysdeps.py)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(_tmp, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from helpix import sysdeps  # noqa: E402

LDD = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibxcb-cursor.so.0 => not found
\tlibQt6Pdf.so.6 => not found
\tlibnss3.so => not found
\tlibc.so.6 => /lib64/libc.so.6 (0x00007f)
"""


def test_parse_and_tables():
    assert sysdeps.parse_ldd(LDD) == {"libxcb-cursor.so.0", "libQt6Pdf.so.6", "libnss3.so"}
    for soname, pkgs in sysdeps.LIBS.items():
        assert len(pkgs) == 4 and all(pkgs), soname
    assert sysdeps._pkg(sysdeps.LIBS, "libxcb-cursor.so.0", "dnf") == "xcb-util-cursor"
    assert sysdeps._pkg(sysdeps.LIBS, "libxcb-cursor.so.0", "apt") == "libxcb-cursor0"
    assert sysdeps._pkg(sysdeps.TOOLS, "npm", "zypper") == "nodejs-default npm-default"
    assert sysdeps._pkg(sysdeps.LIBS, "libxcb-cursor.so.0", None) is None


def test_install_commands():
    assert sysdeps.install_argv(["a", "b"], "dnf") == ["dnf", "install", "-y", "a", "b"]
    assert sysdeps.install_argv(["a"], "pacman") == ["pacman", "-S", "--needed", "--noconfirm", "a"]
    assert sysdeps.install_argv(["a"], "zypper") == ["zypper", "--non-interactive", "install", "a"]
    apt = sysdeps.install_argv(["libxcb-cursor0"], "apt")
    assert apt[:2] == ["sh", "-c"] and "apt-get install -y libxcb-cursor0" in apt[2]
    assert sysdeps.install_argv([], "dnf") is None and sysdeps.install_argv(["a"], None) is None
    line = sysdeps.shell_install(["npm"], pm="dnf")
    assert "dnf install -y nodejs npm" in line


def test_real_qt_is_complete():
    """Qui le librerie di Qt sono state installate: nessuna mancanza (e mai librerie di Qt stesso)."""
    files = sysdeps.qt_binaries()
    assert any(f.endswith("libqxcb.so") for f in files) and any("QtWebEngineProcess" in f for f in files)
    missing = sysdeps.missing_libs(files)
    assert not [m for m in missing if m.startswith("libQt6")]
    print("  librerie mancanti su questo sistema:", missing or "nessuna")


def test_check_and_install_flow():
    saved = (sysdeps.missing_libs, sysdeps.detect_manager, sysdeps.is_immutable, sysdeps.subprocess.call)
    calls = []
    state = {"libs": ["libxcb-cursor.so.0", "libsconosciuta.so.9"]}
    try:
        sysdeps.missing_libs = lambda files=None: list(state["libs"])
        sysdeps.detect_manager = lambda: "pacman"
        sysdeps.is_immutable = lambda: False

        def fake_call(cmd):
            calls.append(cmd)
            state["libs"] = []
            return 0
        sysdeps.subprocess.call = fake_call
        r = sysdeps.check(include_optional=False, lookup=False)
        assert r.packages == ["xcb-util-cursor"] and r.unknown == ["libsconosciuta.so.9"]
        assert sysdeps.main(["install", "--yes", "--required-only"]) == 0
        assert calls and calls[0][-4:] == ["-S", "--needed", "--noconfirm", "xcb-util-cursor"], calls

        # sistema immutabile: niente installazione, solo il comando da eseguire
        state["libs"] = ["libxcb-cursor.so.0"]
        calls.clear()
        sysdeps.is_immutable = lambda: True
        assert sysdeps.main(["install", "--yes", "--required-only"]) == 1 and not calls
        assert sysdeps.manual_hint(sysdeps.check(False, False)).startswith("rpm-ostree install xcb-util-cursor")
    finally:
        sysdeps.missing_libs, sysdeps.detect_manager, sysdeps.is_immutable, sysdeps.subprocess.call = saved


def test_agent_install_adds_prerequisites():
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from helpix import agents
    from helpix.config import ensure_dirs
    from helpix.ui.agent_panel import AgentPanel
    ensure_dirs()
    saved = (sysdeps.tools_missing, sysdeps.detect_manager, sysdeps.is_immutable)
    try:
        sysdeps.tools_missing = lambda tools, path=None: [t for t in tools if t == "npm"]
        sysdeps.detect_manager = lambda: "dnf"
        sysdeps.is_immutable = lambda: False
        panel = AgentPanel("gemini-cli")
        started = []
        panel.term.pty.start = lambda argv, cwd=None, env=None: started.append(argv)
        panel.install()
        script = started[0][-1]
        assert script.index("dnf install -y nodejs npm") < script.index("process.versions.node") < \
            script.index(agents.AGENTS["gemini-cli"]["install"]), script
        started.clear()
        panel.key = "codex"
        panel.install()
        assert "dnf" not in started[0][-1], "codex: curl c'è, nessun pacchetto da installare"
    finally:
        sysdeps.tools_missing, sysdeps.detect_manager, sysdeps.is_immutable = saved


def test_settings_dialog_installs():
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QMessageBox
    from helpix.config import SecretStore, Settings
    from helpix.ui.main_window import MainWindow

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settings = Settings()
    settings.data.update(engine="api", skip_setup=True, quick_shortcut=False)
    win = MainWindow(settings, SecretStore())
    notes = []
    win.notify = lambda text, ms=0: notes.append(text)
    report = sysdeps.Report("dnf", False, [sysdeps.Missing("libxcb-cursor.so.0", "finestra rapida e Qt su X11",
                                                           "xcb-util-cursor")])
    saved = (sysdeps.elevate, sysdeps.check, QMessageBox.exec, QMessageBox.clickedButton)
    ran = []
    try:
        sysdeps.elevate = lambda argv, gui=False: (ran.append((argv, gui)), ["sh", "-c", "exit 0"])[1]
        sysdeps.check = lambda include_optional=True, lookup=True: sysdeps.Report("dnf", False, [])
        QMessageBox.exec = lambda self: 0
        QMessageBox.clickedButton = lambda self: self.buttons()[0]  # «Installa»
        win._deps_ready(report)
        end = time.monotonic() + 10
        while win._deps_proc is not None and time.monotonic() < end:
            pump(50)
        assert ran == [(["dnf", "install", "-y", "xcb-util-cursor"], True)], ran
        assert any("Dipendenze installate" in n for n in notes), notes
    finally:
        sysdeps.elevate, sysdeps.check, QMessageBox.exec, QMessageBox.clickedButton = saved
    win.close()


def test_apt_t64_names():
    """Ubuntu 24.04/Debian 13: libasound2 esiste solo come libasound2t64; Ubuntu 22.04: solo libasound2."""
    import subprocess as sp

    def fake_run(available):
        def run(argv, **kw):
            name = argv[-1]
            out = f"{name}:\n  Installed: (none)\n  Candidate: 1.0\n" if name in available else ""
            return sp.CompletedProcess(argv, 0, out, "")
        return run

    real = sysdeps.subprocess.run
    try:
        for available, expected in (({"libasound2t64", "libnss3"}, "libasound2t64"), ({"libasound2"}, "libasound2")):
            sysdeps._APT_NAMES.clear()
            sysdeps.subprocess.run = fake_run(available)
            assert sysdeps.apt_name("libasound2") == expected, (available, sysdeps.apt_name("libasound2"))
            assert sysdeps._pkg(sysdeps.LIBS, "libasound.so.2", "apt") == expected
    finally:
        sysdeps.subprocess.run = real
        sysdeps._APT_NAMES.clear()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
    os._exit(0)
