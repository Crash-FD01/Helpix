# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test delle traduzioni (python tests/test_i18n.py)."""
import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from helpix import i18n  # noqa: E402

PH = re.compile(r"\{(\w*)\}")


def test_placeholders_match():
    for it, en in i18n.EN.items():
        assert sorted(PH.findall(it)) == sorted(PH.findall(en)), f"segnaposto diversi: {it!r} -> {en!r}"


def test_every_tr_call_has_translation():
    missing = []
    for f in (ROOT / "helpix").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value not in i18n.EN:
                missing.append((f.name, node.lineno, node.args[0].value[:60]))
    assert not missing, missing


def test_switch_language():
    i18n.set_language("en")
    assert i18n.tr("Annulla") == "Cancel"
    assert i18n.tr("Il comando è terminato con codice {rc}").format(rc=2) == "The command ended with code 2"
    assert i18n.tr("testo sconosciuto") == "testo sconosciuto"
    i18n.set_language("it")
    assert i18n.tr("Annulla") == "Annulla"
    os.environ["LANG"] = "it_IT.UTF-8"
    assert i18n.set_language("auto") == "it"
    os.environ["LANG"] = "en_US.UTF-8"
    assert i18n.set_language("auto") == "en"
    i18n.set_language("it")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
