# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorciatoia globale della finestra rapida tramite xdg-desktop-portal (GlobalShortcuts).

Su Wayland un'app non può intercettare i tasti di sistema: li chiede al desktop, che la prima volta
mostra una richiesta di conferma (KDE Plasma 6, GNOME 48+). Questo modulo parla con il portal
direttamente su D-Bus con jeepney (Python puro, già usato dal portachiavi), in un thread: non serve
PyGObject, che su KDE spesso non è installato.

Segnali Qt: activated() quando l'utente preme la scorciatoia, state(str, str) con lo stato
("bound" + descrizione, "error" + motivo).
"""
from __future__ import annotations

import logging
import secrets
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

PORTAL = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "quick"
APP_ID = "helpix"


class GlobalShortcut(QObject):
    activated = Signal()
    state = Signal(str, str)

    def __init__(self, trigger: str = "CTRL+ALT+h", description: str = "Helpix", parent=None):
        super().__init__(parent)
        self.trigger, self.description = trigger, description
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="helpix-shortcut", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ thread
    def _run(self):
        try:
            self._portal()
        except Exception as exc:  # noqa: BLE001 - qualsiasi errore: scorciatoia non disponibile
            if not self._stop.is_set():
                log.info("scorciatoia globale non disponibile: %s", exc)
                self.state.emit("error", str(exc) or exc.__class__.__name__)

    def _portal(self):
        from jeepney import DBusAddress, MessageType, new_method_call
        from jeepney.bus_messages import MatchRule, message_bus
        from jeepney.io.blocking import open_dbus_connection

        conn = open_dbus_connection(bus="SESSION")
        self._conn = conn
        portal = DBusAddress(PATH, bus_name=PORTAL, interface=IFACE)
        sender = conn.unique_name.lstrip(":").replace(".", "_")

        # le app non in sandbox dicono al portal chi sono (xdg-desktop-portal ≥ 1.19; prima non serve)
        reg = new_method_call(DBusAddress(PATH, bus_name=PORTAL, interface="org.freedesktop.host.portal.Registry"),
                              "Register", "sa{sv}", (APP_ID, {}))
        reply = conn.send_and_get_reply(reg, timeout=5)
        if reply.header.message_type == MessageType.error:
            log.info("Registry.Register: %s", reply.body)

        def request(method: str, signature: str, args: tuple, timeout: float = 300) -> tuple[int, dict]:
            """Chiamata con risposta asincrona (oggetto Request): restituisce (codice, risultati)."""
            token = "helpix" + secrets.token_hex(4)
            handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
            rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response",
                             path=handle)
            conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=5)
            options = dict(args[-1])
            options["handle_token"] = ("s", token)
            with conn.filter(rule) as queue:
                msg = new_method_call(portal, method, signature, args[:-1] + (options,))
                answer = conn.send_and_get_reply(msg, timeout=10)
                if answer.header.message_type == MessageType.error:
                    raise RuntimeError(f"{method}: {answer.body[0] if answer.body else 'errore'}")
                signal = conn.recv_until_filtered(queue, timeout=timeout)
            code, results = signal.body
            return code, {k: v[1] for k, v in results.items()}

        code, res = request("CreateSession", "a{sv}", ({"session_handle_token": ("s", "helpix" + secrets.token_hex(4))},))
        if code != 0 or "session_handle" not in res:
            raise RuntimeError(f"sessione non creata (codice {code})")
        session = res["session_handle"]

        def bound_description(items) -> str | None:
            for sid, info in items or []:
                if sid == SHORTCUT_ID:
                    trig = info.get("trigger_description")
                    return trig[1] if isinstance(trig, tuple) else (trig or self.trigger)
            return None

        # Versione del portal: su KDE Plasma ≥ 6.4 (versione ≥ 2) BindShortcuts va chiamato a OGNI avvio
        # (da Plasma 6.7.4 le scorciatoie salvate non si attivano da sole) e non mostra dialoghi per quelle
        # già confermate; su Plasma ≤ 6.3 (versione 1) riaprirebbe ogni volta le impostazioni, quindi lì si
        # chiama solo la prima volta.
        version = 1
        get = new_method_call(DBusAddress(PATH, bus_name=PORTAL, interface="org.freedesktop.DBus.Properties"),
                              "Get", "ss", (IFACE, "version"))
        answer = conn.send_and_get_reply(get, timeout=5)
        if answer.header.message_type != MessageType.error:
            version = int(answer.body[0][1])
        code, res = request("ListShortcuts", "oa{sv}", (session, {}), timeout=30)
        known = bound_description(res.get("shortcuts")) if code == 0 else None
        log.info("portal versione %s, scorciatoia già salvata: %s", version, known)
        desc = known
        if known is None or version >= 2:
            shortcuts = [(SHORTCUT_ID, {"description": ("s", self.description),
                                        "preferred_trigger": ("s", self.trigger)})]
            code, res = request("BindShortcuts", "oa(sa{sv})sa{sv}", (session, shortcuts, "", {}))
            if code != 0:
                raise RuntimeError("scorciatoia non confermata" if code == 1 else f"rifiutata (codice {code})")
            desc = bound_description(res.get("shortcuts"))
            if desc is None:
                desc = known or ""
        self.state.emit("bound", desc)

        rule = MatchRule(type="signal", interface=IFACE, member="Activated")
        conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=5)
        with conn.filter(rule) as queue:
            while not self._stop.is_set():
                try:
                    msg = conn.recv_until_filtered(queue, timeout=1.0)
                except TimeoutError:
                    continue
                log.info("portal Activated %s %s", msg.body[0], msg.body[1])
                if msg.body[1] == SHORTCUT_ID:  # i segnali arrivano solo alla nostra connessione
                    self.activated.emit()


class WindowsHotkey(QObject):
    """Scorciatoia globale su Windows con RegisterHotKey: funziona da qualsiasi programma, senza conferme.

    Gira in un thread con la propria coda di messaggi (WM_HOTKEY arriva al thread che l'ha registrata). Stessi
    segnali di GlobalShortcut, così la finestra principale li gestisce allo stesso modo."""
    activated = Signal()
    state = Signal(str, str)

    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
    WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

    def __init__(self, key: str = "H", label: str = "Ctrl+Alt+H", parent=None):
        super().__init__(parent)
        self.key, self.label = key.upper(), label
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="helpix-hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
        self._thread_id = 0

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()
        mods = self.MOD_CONTROL | self.MOD_ALT | self.MOD_NOREPEAT
        if not user32.RegisterHotKey(None, 1, mods, ord(self.key)):
            err = ctypes.get_last_error()
            self.state.emit("error", "già usata da un altro programma" if err == 1409 else f"errore {err}")
            self._thread_id = 0
            return
        self.state.emit("bound", self.label)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    self.activated.emit()
        finally:
            user32.UnregisterHotKey(None, 1)
