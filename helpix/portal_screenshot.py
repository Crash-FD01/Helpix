#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshot tramite xdg-desktop-portal (funziona su Wayland: GNOME, KDE, wlroots...).

Viene lanciato come processo separato con il Python di sistema, perché usa
PyGObject (gi) e un GLib main loop indipendente da Qt.

Uscita: stampa l'URI dell'immagine su stdout (codice 0); 2 = annullato
dall'utente; 1 = portal non disponibile o errore.
"""
import random
import string
import sys


def main() -> int:
    interactive = "--interactive" in sys.argv
    try:
        from gi.repository import Gio, GLib
    except Exception as exc:  # noqa: BLE001
        print(f"PyGObject non disponibile: {exc}", file=sys.stderr)
        return 1
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        token = "helpix" + "".join(random.choices(string.ascii_lowercase, k=8))
        sender = bus.get_unique_name().lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        loop = GLib.MainLoop()
        result = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            code, res = params.unpack()
            result["code"] = code
            result["uri"] = res.get("uri")
            loop.quit()

        bus.signal_subscribe(None, "org.freedesktop.portal.Request", "Response", handle,
                             None, Gio.DBusSignalFlags.NONE, on_response)
        options = {"handle_token": GLib.Variant("s", token),
                   "interactive": GLib.Variant("b", interactive),
                   "modal": GLib.Variant("b", True)}
        bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                      "org.freedesktop.portal.Screenshot", "Screenshot",
                      GLib.Variant("(sa{sv})", ("", options)), GLib.VariantType("(o)"),
                      Gio.DBusCallFlags.NONE, -1, None)

        def on_timeout():
            result.setdefault("code", 99)
            loop.quit()
            return False

        GLib.timeout_add_seconds(110, on_timeout)
        loop.run()
    except Exception as exc:  # noqa: BLE001
        print(f"Portal non disponibile: {exc}", file=sys.stderr)
        return 1

    if result.get("code") == 0 and result.get("uri"):
        print(result["uri"])
        return 0
    if result.get("code") == 1:
        print("annullato", file=sys.stderr)
        return 2
    print(f"Portal: risposta {result.get('code')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
