# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portal finto (GlobalShortcuts) per i test: risponde come xdg-desktop-portal e, dopo la
conferma della scorciatoia, simula la pressione dei tasti."""
import sys
import threading
import time

from jeepney import DBusAddress, HeaderFields, MessageType, new_method_return, new_signal
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection

PORTAL, PATH = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.GlobalShortcuts"
mode = sys.argv[1] if len(sys.argv) > 1 else "ok"   # ok | deny
conn = open_dbus_connection(bus="SESSION")
conn.send_and_get_reply(message_bus.RequestName(PORTAL))
print("ready", flush=True)
session = "/org/freedesktop/portal/desktop/session/test/helpix1"
bound = []
lock = threading.Lock()


def respond(msg, results, code=0):
    sender = msg.header.fields[HeaderFields.sender].lstrip(":").replace(".", "_")
    token = msg.body[-1]["handle_token"][1]
    handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    with lock:
        conn.send(new_method_return(msg, "o", (handle,)))
        time.sleep(0.05)
        conn.send(new_signal(DBusAddress(handle, interface="org.freedesktop.portal.Request"), "Response",
                             "ua{sv}", (code, results)))


def press_later():
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0.8)
    with lock:
        conn.send(new_signal(DBusAddress(PATH, interface=IFACE), "Activated", "osta{sv}", (session, "quick", 0, {})))
    print("pressed", flush=True)


while True:
    msg = conn.receive()
    if msg.header.message_type != MessageType.method_call:
        continue
    member = msg.header.fields[HeaderFields.member]
    if member == "Register":
        with lock:
            conn.send(new_method_return(msg))
    elif member == "Get":  # proprietà «version» del portal
        with lock:
            conn.send(new_method_return(msg, "v", (("u", 2),)))
    elif member == "CreateSession":
        respond(msg, {"session_handle": ("s", session)})
    elif member == "ListShortcuts":
        respond(msg, {"shortcuts": ("a(sa{sv})", bound)})
    elif member == "BindShortcuts":
        print("bind", msg.body[1][0][1]["preferred_trigger"][1], flush=True)
        if mode == "deny":
            respond(msg, {}, code=1)
            continue
        bound[:] = [("quick", {"description": ("s", "Helpix"), "trigger_description": ("s", "Ctrl+Alt+H")})]
        respond(msg, {"shortcuts": ("a(sa{sv})", bound)})
        threading.Thread(target=press_later, daemon=True).start()  # attiva solo dopo il bind di questa sessione
