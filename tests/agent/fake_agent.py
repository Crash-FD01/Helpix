#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agente finto per i test: si comporta come un'interfaccia da terminale (modo raw, incolla
tra parentesi, Invio) e scrive il riepilogo su file quando glielo si chiede."""
import json
import os
import select
import sys
import termios
import time
import tty

LOG = os.environ["FAKE_AGENT_LOG"]


def rec(**k):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(k) + "\n")


size = os.get_terminal_size(0)
rec(event="start", name=os.path.basename(sys.argv[0]), argv=sys.argv[1:], tty=os.isatty(0), cwd=os.getcwd(),
    cols=size.columns, rows=size.lines, context=sorted(f for f in os.listdir(".") if f.endswith(".md")))
old = termios.tcgetattr(0)
tty.setraw(0)
out = sys.stdout
out.write("\x1b[1;35mAgente finto\x1b[0m pronto\r\n> ")
out.flush()
line = ""
try:
    while True:
        r, _, _ = select.select([0], [], [], 0.2)
        if not r:
            continue
        data = os.read(0, 4096).decode("utf-8", "replace")
        rec(event="data", text=data)
        for ch in data.replace("\x1b[200~", "").replace("\x1b[201~", ""):
            if ch == "\r":
                rec(event="line", text=line)
                out.write("\r\n")
                if "HELPIX-SUMMARY.md" in line:
                    time.sleep(0.5)
                    with open("HELPIX-SUMMARY.md", "w", encoding="utf-8") as f:
                        f.write("```\nHELPIX-TASK\nObiettivo:\nconfigurare il backup notturno\n\n"
                                "Cosa è stato fatto (comandi, risultati, decisioni):\nscritto backup.sh con rsync\n\n"
                                "Stato attuale:\nmanca il timer systemd\n```\n")
                    out.write("Riepilogo scritto in HELPIX-SUMMARY.md\r\n")
                if line.strip() == "/exit":
                    raise SystemExit(0)
                line = ""
                out.write("> ")
            elif ch == "\x03":
                raise SystemExit(130)
            else:
                line += ch
                out.write(ch)
        out.flush()
finally:
    termios.tcsetattr(0, termios.TCSADRAIN, old)
