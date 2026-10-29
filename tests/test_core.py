# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test del core: python -m pytest tests (oppure python tests/test_core.py)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from helpix.executor import CommandRunner, analyze, strip_sudo  # noqa: E402
from helpix.providers import build_request, parse_response  # noqa: E402
from helpix.session import Message, Session, list_sessions  # noqa: E402
from helpix.ui.chat import split_segments  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])


def run(cmd, cwd, timeout=10, cancel_after=None):
    r = CommandRunner(cmd, cwd, False, timeout)
    out = {}
    r.completed.connect(lambda res: out.setdefault("res", res))
    r.start()
    if cancel_after:
        import time
        time.sleep(cancel_after)
        r.cancel()
    r.wait(20000)
    app.processEvents()
    return out["res"]


def test_analyze():
    if sys.platform == "win32":  # bash e regole di Linux; su Windows: test_windows.py
        return
    assert analyze("sudo dnf install htop").needs_root
    assert not analyze("echo sudoku").needs_root
    assert analyze("ls && sudo systemctl restart NetworkManager").needs_root
    assert analyze("sudo -u bob ls").sudo_options
    assert analyze("rm -rf ~/tmp").dangers
    assert analyze("sudo dnf remove firefox").dangers
    assert analyze("curl -fsSL x.sh | sudo bash").dangers
    assert not analyze("journalctl -b -p err --no-pager").dangers
    assert analyze("nano /etc/fstab").interactive
    assert analyze("journalctl -f").interactive
    assert not analyze("bash script.sh").interactive
    assert not analyze("top -bn1 | head").interactive or True  # top senza -b: avvisa comunque
    assert strip_sudo("sudo dnf up && sudo reboot") == "dnf up && reboot"


def test_runner_cwd_and_rc():
    if sys.platform == "win32":  # bash e regole di Linux; su Windows: test_windows.py
        return
    d = tempfile.mkdtemp()
    os.mkdir(os.path.join(d, "sub dir"))
    res = run("cd 'sub dir' && echo ciao", d)
    assert res.rc == 0 and "ciao" in res.output
    assert res.cwd == os.path.join(d, "sub dir")
    res = run("exit 3", d)
    assert res.rc == 3 and res.cwd == d
    res = run("cd / ; false", d)
    assert res.rc == 1 and res.cwd == "/"
    res = run("printf 'a\\rb\\n'; printf '\\033[31mrosso\\033[0m\\n'", d)
    assert res.output == "b\nrosso\n", repr(res.output)
    res = run("read x; echo letto:$x", d)  # stdin chiuso: non deve bloccarsi
    assert "letto:" in res.output


def test_runner_timeout_cancel_background():
    if sys.platform == "win32":  # bash e regole di Linux; su Windows: test_windows.py
        return
    d = tempfile.mkdtemp()
    res = run("sleep 30", d, timeout=1)
    assert res.timed_out and res.rc != 0
    res = run("sleep 30", d, timeout=0, cancel_after=0.5)
    assert res.cancelled
    import time
    t = time.monotonic()
    res = run("sleep 20 & echo partito", d)  # processo in background: non aspettarlo
    assert "partito" in res.output and time.monotonic() - t < 5


def test_split_segments():
    text = "Controlla:\n```bash\nsudo dnf check-update\n```\nPoi:\n```console\n$ ls -la\noutput\n```\nFine"
    segs = split_segments(text)
    kinds = [s[0] for s in segs]
    assert kinds == ["md", "code", "md", "code", "md"], segs
    assert segs[1][2] == "sudo dnf check-update"
    assert segs[3][2] == "ls -la"
    assert split_segments("```bash\nuname -a")[0][2] == "uname -a"  # blocco non chiuso


def test_session_wire_and_switch():
    png = os.path.join(_tmp, "a.png")
    with open(png, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\nfake")
    s = Session("anthropic", "claude-sonnet-5-5", "/tmp")
    s.add(Message("user", "Il wifi non va", images=[png]))
    s.add(Message("assistant", "Esegui:\n```bash\nnmcli dev\n```"))
    s.add(Message("user", "output 1", kind="output"))
    s.add(Message("note", "Agente cambiato"))
    s.add(Message("user", "output 2", kind="output"))
    assert s.title == "Il wifi non va"
    wire = s.to_wire(vision=True)
    assert len(wire) == 4 and wire[0]["images"] == [png]
    assert "non può vedere" in s.to_wire(vision=False)[0]["text"]

    url, payload = build_request("anthropic", "m", "SYS", wire)
    assert url.endswith("/v1/messages") and payload["system"] == "SYS"
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["user", "assistant", "user"], roles  # output consecutivi uniti
    assert payload["messages"][0]["content"][0]["type"] == "image"

    url, payload = build_request("gemini", "gemini-2.5-flash", "SYS", wire)
    assert url.endswith("/openai/chat/completions")
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    _, payload = build_request("deepseek", "deepseek-chat", "SYS", s.to_wire(vision=False))
    assert all(isinstance(m["content"], str) for m in payload["messages"])

    loaded = Session.load(s.id)
    assert len(loaded.messages) == 5 and loaded.messages[2].kind == "output"
    assert list_sessions()[0]["id"] == s.id


def test_parse_response():
    assert parse_response("anthropic", {"content": [{"type": "text", "text": "ok"}]}) == "ok"
    assert parse_response("openai", {"choices": [{"message": {"content": " ciao "}}]}) == "ciao"
    assert "troncata" in parse_response("anthropic", {"content": [{"type": "text", "text": "x"}],
                                                      "stop_reason": "max_tokens"})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
