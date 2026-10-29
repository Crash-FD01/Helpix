# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finestra rapida di una versione vecchia (prima della 0.13.2), per i test.

Fa quello che faceva il codice vecchio: occupa quick.sock, ignora «quit» e, quando Helpix si chiude,
lo riapre. Gira finché qualcuno non la termina.
"""
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.environ["PYTHONPATH"])
from helpix.instance import socket_path  # noqa: E402
from helpix.ui.quick_window import quick_socket_path  # noqa: E402

path = quick_socket_path()
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path):
    os.unlink(path)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(path)
srv.listen(5)
srv.settimeout(0.2)
log = open(os.environ["OLD_QUICK_LOG"], "a")
app = None
while True:
    try:
        conn, _ = srv.accept()
        conn.settimeout(0.2)
        try:
            log.write("msg " + conn.recv(4096).decode(errors="replace").strip() + "\n")  # ignorato
            log.flush()
        except OSError:
            pass
        conn.close()
    except OSError:
        pass
    if app is None:
        try:
            app = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            app.connect(socket_path())
            app.setblocking(False)
        except OSError:
            app = None
        continue
    try:
        if app.recv(1) == b"":  # Helpix si è chiuso: il codice vecchio lo riapriva
            app = None
            time.sleep(1)
            log.write("relaunch\n")
            log.flush()
            subprocess.Popen([sys.executable, "-m", "helpix"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except BlockingIOError:
        pass
    except OSError:
        app = None
