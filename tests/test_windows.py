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
    import hashlib
    from unittest import mock
    from helpix import updates
    assert updates.is_newer("0.16.0", "0.15.2") and updates.is_newer("1.0", "0.99.9")
    assert not updates.is_newer("0.15.2", "0.15.2") and not updates.is_newer("0.15.1", "0.15.2")

    class S(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    no_check = os.environ.pop("HELPIX_NO_UPDATE_CHECK", None)
    try:
        # attivo di default su Windows e Linux, a ogni avvio (non più una volta ogni 20 ore)
        assert updates.due(S()) and updates.due(S(check_updates=True, updates_checked_at=10**12))
        assert not updates.due(S(check_updates=False))
    finally:
        if no_check is not None:
            os.environ["HELPIX_NO_UPDATE_CHECK"] = no_check
    assert not updates.due(S()) or not no_check

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"tag_name": "v9.1.0", "html_url": "https://github.com/x/y/releases/tag/v9.1.0", "assets": [
                {"name": "helpix_9.1.0_amd64.deb", "browser_download_url": "https://x/deb"},
                {"name": "Helpix-9.1.0-Setup.exe", "browser_download_url": "https://x/Helpix-9.1.0-Setup.exe"},
                {"name": "SHA256SUMS", "browser_download_url": "https://x/SHA256SUMS"}]}
    with mock.patch("requests.get", return_value=R()) as get:
        info = updates.latest_release()
    assert info == {"version": "9.1.0", "url": "https://github.com/x/y/releases/tag/v9.1.0",
                    "setup": "https://x/Helpix-9.1.0-Setup.exe", "sums": "https://x/SHA256SUMS"}, info
    assert "/repos/Crash-FD01/Helpix/releases/latest" in get.call_args[0][0]

    # Windows: installer scaricato e controllato con SHA256SUMS; impronta sbagliata = niente installazione
    payload = b"installer finto" * 1000

    class Resp:
        def __init__(self, text=b""):
            self.content = text
            self.text = text.decode()

        def raise_for_status(self):
            pass

        def iter_content(self, _n):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_get(sums_line):
        return lambda url, **_k: Resp(sums_line if url.endswith("SHA256SUMS") else payload)
    good = f"{hashlib.sha256(payload).hexdigest()}  Helpix-9.1.0-Setup.exe\n".encode()
    with mock.patch("requests.get", side_effect=fake_get(good)):
        path = updates.download_setup(info)
    assert open(path, "rb").read() == payload
    os.remove(path)
    with mock.patch("requests.get", side_effect=fake_get(b"0" * 64 + b"  Helpix-9.1.0-Setup.exe\n")):
        try:
            updates.download_setup(info)
            raise AssertionError("impronta sbagliata accettata")
        except RuntimeError:
            pass
    assert not os.path.exists(path)
    assert updates.setup_argv("C:/t/s.exe")[1:] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                                     "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]

    # Linux: aggiorna solo Helpix con il gestore pacchetti; dai sorgenti o immutabile solo il comando da usare
    apt = updates.linux_update_argv("apt")
    assert apt[:2] == ["sh", "-c"] and "sources.list.d/helpix.list" in apt[2] and "--only-upgrade helpix" in apt[2]
    assert updates.linux_update_argv("dnf") == ["dnf", "upgrade", "-y", "--refresh", "helpix"]
    assert "zypper --non-interactive update helpix" in updates.linux_update_argv("zypper")[2]
    assert updates.linux_update_argv("pacman") is None
    assert updates.manual_hint("source", "apt") == "git pull && ./install.sh"
    assert updates.manual_hint("immutable", "dnf") == "sudo rpm-ostree upgrade"
    assert updates.install_kind() == ("windows" if WINDOWS else "source")  # i test girano dai sorgenti


def test_window_list_on_windows():
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    from helpix.screenshot import windows_window_rects
    rects = windows_window_rects()  # sulle macchine di GitHub può essere vuota: basta che non si rompa
    assert all(w > 40 and h > 30 and isinstance(t, str) for (_x, _y, w, h), t in rects), rects[:3]
    print("  finestre visibili:", len(rects))


# installer finto con lo stesso rilevamento dell'architettura dello script ufficiale di Codex (issue #6)
_FAKE_INSTALLER = """param([string]$Version = "latest")
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
switch ($architecture) {
  "Arm64" { $target = "aarch64-pc-windows-msvc" }
  "X64" { $target = "x86_64-pc-windows-msvc" }
  default { throw "Unsupported architecture: $architecture" }
}
Write-Host "INSTALLATO target=$target"
"""


def _serve(body: str) -> str:
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *_a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/install.ps1"


def test_agent_install_script():
    """Installazione degli agenti: compatibilità con Windows PowerShell 5.1, errori visibili, registro."""
    import shutil
    import subprocess
    from helpix import agents
    agents.IS_WINDOWS = True
    try:
        orig = agents.AGENTS["codex"]["install_win"]
        assert orig == "irm https://chatgpt.com/codex/install.ps1 | iex"
        agents.AGENTS["codex"]["install_win"] = f"irm {_serve(_FAKE_INSTALLER)} | iex"
        script = agents.windows_install_script("codex")
        assert "PSVersion.Major -lt 6" in script and "Tls12" in script and "Start-Transcript" in script
        assert str(agents.install_log("codex")) in script
        agents.AGENTS["gemini-cli"]["install_win"] = "comando_inesistente_helpix"
        failing = agents.windows_install_script("gemini-cli", ["Write-Host 'passo preliminare'"])
        # lo script va in un file .ps1 (con BOM) e parte con -File: niente -EncodedCommand né -ExecutionPolicy Bypass
        argv = agents.windows_install_argv("codex", exe="pwsh.exe")
        assert argv[0] == "pwsh.exe" and argv[-2] == "-File" and argv[-1].endswith("install-codex.ps1"), argv
        assert "-EncodedCommand" not in argv and "Bypass" not in argv, argv
        assert open(argv[-1], "rb").read().startswith(b"\xef\xbb\xbf")
        flags = argv[1:-1]
    finally:
        agents.AGENTS["codex"]["install_win"] = orig
        agents.AGENTS["gemini-cli"]["install_win"] = "npm install -g @google/gemini-cli"
        agents.IS_WINDOWS = WINDOWS
    # Windows: il PowerShell 5.1 vero (powershell.exe), quello dove lo script ufficiale si fermava
    shells = [s for s in (shutil.which("powershell.exe") if WINDOWS else None, shutil.which("pwsh")) if s]
    if not shells:
        print("  (PowerShell non presente: script non eseguito)")
        return
    env = dict(os.environ, PROCESSOR_ARCHITECTURE="AMD64")
    work = tempfile.mkdtemp()

    def script_file(text, ps):
        if "powershell" not in os.path.basename(ps).lower():  # PowerShell 7: si prova anche il ramo per la 5.1
            text = text.replace("$PSVersionTable.PSVersion.Major -lt 6", "$true")
        path = os.path.join(work, f"s{len(os.listdir(work))}.ps1")
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(text)
        return [ps, *flags, path]
    for ps in shells:
        def run(text, ps=ps):
            return subprocess.run(script_file(text, ps), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, env=env)
        r = run(script)
        assert r.returncode == 0 and "INSTALLATO target=x86_64-pc-windows-msvc" in r.stdout, (ps, r.stdout, r.stderr)
        assert "INSTALLATO" in agents.install_log("codex").read_text(encoding="utf-8", errors="replace")
        r = run(failing)
        assert r.returncode == 1, (ps, r.returncode, r.stdout, r.stderr)
        assert "passo preliminare" in r.stdout and "comando_inesistente_helpix" in r.stdout, (ps, r.stdout)
    if not WINDOWS:
        return
    # nel terminale vero (ConPTY), come nel pannello degli agenti: deve scrivere subito e finire
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from helpix.pty_process import PtyProcess
    app = QCoreApplication.instance() or QCoreApplication([])
    for ps in shells:
        pty = PtyProcess()
        out, codes = [], []
        loop = QEventLoop()
        pty.output.connect(out.append)
        pty.finished.connect(lambda rc, codes=codes, loop=loop: (codes.append(rc), loop.quit()))
        QTimer.singleShot(90000, loop.quit)
        pty.start(script_file(script, ps), os.path.expanduser("~"), {"PROCESSOR_ARCHITECTURE": "AMD64"})
        loop.exec()
        text = "".join(out)
        assert codes == [0] and "INSTALLATO target=x86_64" in text, (ps, codes, text[-2000:])
    del app


def test_bundled_powershell():
    """Programma installato: solo il PowerShell 7 incluso (cartella pwsh accanto a Helpix.exe), anche nel PATH."""
    import types
    from pathlib import Path
    from helpix import system
    app_dir = Path(tempfile.mkdtemp())
    exe = app_dir / "pwsh" / "pwsh.exe"
    fake_sys = types.SimpleNamespace(frozen=True, executable=str(app_dir / "Helpix.exe"))
    real = (system.sys, system.IS_WINDOWS, os.environ.get("PATH", ""))
    system.sys, system.IS_WINDOWS = fake_sys, True
    try:
        assert winshell.bundled_powershell() is None  # cartella pwsh mancante
        exe.parent.mkdir()
        exe.write_bytes(b"")
        bundled = str(exe.resolve())
        assert winshell.bundled_powershell() == bundled
        assert winshell.powershell() == bundled
        assert winshell.argv("QQ==")[0] == bundled
        assert winshell.powershell_version_label() == "PowerShell 7"
        assert bundled in winshell.launcher_script("QQ==")  # anche i comandi come amministratore
        # per primo nel PATH che Helpix passa a ciò che avvia (installazione degli agenti, agenti), una volta sola
        system.use_bundled_pwsh()
        system.use_bundled_pwsh()
        parts = os.environ["PATH"].split(os.pathsep)
        assert parts[0] == str(exe.parent.resolve()) and parts.count(parts[0]) == 1, parts[:3]
        from helpix import agents
        assert agents.search_path().split(os.pathsep)[0] == parts[0]
        assert os.environ["POWERSHELL_TELEMETRY_OPTOUT"] == "1"
    finally:
        system.sys, system.IS_WINDOWS = real[0], real[1]
        os.environ["PATH"] = real[2]
    assert winshell.bundled_powershell() is None  # dai sorgenti: PowerShell del sistema

def test_junctions_on_windows():
    """Giunzioni come quelle dell'installer di Codex: dal PowerShell avviato normalmente e nel terminale (ConPTY)."""
    if not WINDOWS:
        print("  (solo su Windows: saltato)")
        return
    import shutil
    import subprocess
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from helpix.pty_process import PtyProcess
    app = QCoreApplication.instance() or QCoreApplication([])
    ps1 = os.path.join(tempfile.mkdtemp(), "probe.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(winshell.JUNCTION_PROBE)
    report = []
    for ps in [p for p in (shutil.which("pwsh"), shutil.which("powershell.exe")) if p]:
        argv = [ps, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", ps1]
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        report.append(f"{os.path.basename(ps)} processo: {r.stdout.strip()} {r.stderr.strip()[-400:]}")
        pty, out, loop = PtyProcess(), [], QEventLoop()
        pty.output.connect(out.append)
        pty.finished.connect(lambda _rc, loop=loop: loop.quit())
        QTimer.singleShot(120000, loop.quit)
        pty.start(argv, os.path.expanduser("~"))
        loop.exec()
        report.append(f"{os.path.basename(ps)} ConPTY: " + "".join(out)[-1200:])
    # RedirectionGuard: criterio del processo prima e dopo il motore web (Chromium), e quello di un figlio
    code = (
        "import os, subprocess, sys\n"
        "sys.path.insert(0, %r)\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "from helpix.system import redirection_trust_policy as pol\n"
        "before = pol()\n"
        "import PySide6.QtWebEngineWidgets\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from PySide6.QtWebEngineWidgets import QWebEngineView\n"
        "from PySide6.QtCore import QTimer\n"
        "app = QApplication([]); v = QWebEngineView(); v.setHtml('<p>x</p>'); v.show()\n"
        "QTimer.singleShot(4000, app.quit); app.exec()\n"
        "child = subprocess.run([%r, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File', %r],"
        " capture_output=True, text=True).stdout.strip().replace(chr(10), ' | ')\n"
        "print('POLICY', before, pol(), child, flush=True)\n"
        "os._exit(0)\n"
    ) % (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), shutil.which("pwsh") or "powershell.exe", ps1)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("POLICY")), r.stdout[-300:] + r.stderr[-300:])
    report.append("motore web: criterio del processo prima/dopo e figlio: " + line)
    text = "\n".join(report)
    print(text)
    print("::notice title=Giunzioni e RedirectionGuard (Windows)::" + text.replace("\r", "").replace("\n", "%0A"))
    assert text.count("junction-ok") == 2 * len([1 for r in report if " processo: " in r]), text
    del app


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name, flush=True)
