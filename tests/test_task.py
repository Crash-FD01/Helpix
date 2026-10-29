# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test del passaggio del task tra IA (python tests/test_task.py)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")

from helpix.session import Message, Session  # noqa: E402
from helpix.task import (SUMMARY_MARKER, build_handoff, export_task, extract_problem, import_task,  # noqa: E402
                         parse_summary, record_summary, summary_request)

COPIED = f"""{SUMMARY_MARKER}
Problema: il Wi-Fi non si connette dopo l'aggiornamento del kernel
Sistema: Fedora 43, scheda Intel AX210
Cosa è stato verificato (comandi e risultati): nmcli device status → wlp2s0 non disponibile
Cosa è stato modificato sul sistema: niente
Ipotesi attuale: firmware iwlwifi mancante
Prossimi passi consigliati: controllare dmesg | grep iwlwifi"""


def make_task():
    png = os.path.join(_tmp, "shot.png")
    Path(png).write_bytes(b"\x89PNG\r\n\x1a\nfake")
    s = Session("anthropic", "claude-sonnet-5-5", "/tmp")
    s.site = "claude"
    s.add(Message("user", "Screenshot inviato a Claude", images=[png], kind="shot"))
    s.add(Message("user", "...", kind="output", meta={"cmd": "nmcli device status", "rc": 0,
                                                     "output": "wlp2s0  wifi  non disponibile"}))
    return s, png


def test_summary_parsing():
    assert summary_request().count(SUMMARY_MARKER) == 1
    assert parse_summary("ciao") is None
    body = parse_summary("Ecco il riepilogo:\n```\n" + COPIED + "\n```\nFammi sapere")
    assert body.startswith("Problema:") and "Fammi sapere" not in body
    assert extract_problem(body) == "il Wi-Fi non si connette dopo l'aggiornamento del kernel"
    assert extract_problem("Problem: no sound\nSystem: x") == "no sound"
    # formato neutro (0.8.7): obiettivo sulla stessa riga o a capo
    assert extract_problem("Obiettivo:\nscrivere uno script di backup\n\nContesto:\nx") == \
        "scrivere uno script di backup"
    assert extract_problem("Goal: migrate the mailbox") == "migrate the mailbox"
    assert "Obiettivo:" in summary_request() or "Goal:" in summary_request()


def test_handoff_package():
    s, png = make_task()
    text, images = build_handoff(s, "Wi-Fi assente", "Claude")
    assert "Claude" in text and "Wi-Fi assente" in text
    assert "$ nmcli device status" in text and "non disponibile" in text
    assert images == [png]
    record_summary(s, parse_summary(COPIED), "Claude")
    assert s.title.startswith("il Wi-Fi non si connette")
    text, _ = build_handoff(s, "", "Claude", include_commands=False, include_screens=False)
    assert "firmware iwlwifi" in text and "$ nmcli" not in text
    # dopo il riepilogo non serve più l'estratto della conversazione
    assert "Conversazione finora" not in text


def test_export_import_roundtrip():
    s, png = make_task()
    record_summary(s, parse_summary(COPIED), "Claude")
    out = export_task(s, os.path.join(_tmp, "caso-wifi"))
    assert out.suffix == ".helpix" and out.exists()
    t = import_task(out)
    assert t.id != s.id and t.title == s.title and len(t.messages) == len(s.messages)
    img = t.messages[0].images[0]
    assert os.path.exists(img) and img != png and Path(img).read_bytes() == Path(png).read_bytes()
    assert Session.load(t.id).messages[-1].kind == "summary"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
