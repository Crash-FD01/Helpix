# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""App finta per il test end-to-end: un BridgeServer vero con risposte prevedibili."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from helpix.bridge import BridgeServer  # noqa: E402

LOG = sys.argv[1]
SHOT = os.path.join(os.path.dirname(LOG), "shot.png")
app = QApplication([])
img = QImage(320, 200, QImage.Format.Format_RGB32)
img.fill(QColor("#3478f6"))
img.save(SHOT)
server = BridgeServer()
events = []


def log(kind, **data):
    events.append({"kind": kind, **data})
    with open(LOG, "w") as f:
        json.dump(events, f)


def clean(m):
    return {k: v for k, v in m.items() if k != "_client"}


def on_run(m):
    log("run", **clean(m))
    cmd = m["cmd"]
    if cmd.startswith("HELPIX-TASK"):
        server.run_status(m, "summary")
        return
    if cmd == "open-package":
        server.run_status(m, "done", rc=0, output="", auto=False)
        server.open_paste("claude", "https://claude.ai/new", "TESTO DEL TASK", [SHOT])
        return
    if "rm -rf" in cmd and not m.get("confirmed"):
        server.run_status(m, "confirm", warnings=["cancella file in modo ricorsivo"])
        return
    server.run_status(m, "running")
    out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout
    QTimer.singleShot(300, lambda: server.run_status(m, "done", rc=0, auto=True,
                                                     output=f"Output di `{cmd}`:\n```\n{out.strip()}\n```"))


server.run_requested.connect(on_run)
server.screenshot_requested.connect(lambda m: (log("screenshot", **clean(m)),
                                               server.paste_image(m["site"], SHOT, m["_client"], m["tab"])))
server.diagnostics_requested.connect(lambda m: (log("diagnostics", **clean(m)),
                                                server.paste_text(m["site"], "DIAGNOSI DI PROVA", m["_client"], m["tab"])))
server.package_result.connect(lambda ok: log("package_result", ok=ok))
server.clients_changed.connect(lambda: log("clients", browsers=server.browsers(),
                                           tabs=[c.tabs for c in server.clients]))
server.site_activated.connect(lambda s: log("active", site=s))
assert server.start(), "bridge non avviato"
log("started", path=server.path)
app.exec()
