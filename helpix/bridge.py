# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Server locale di Helpix per l'estensione del browser.

L'host di native messaging (bridge_host.py), avviato dal browser, si collega a questo
socket. Ogni riga è un messaggio JSON. Il socket è nella cartella runtime dell'utente con
permessi 0700/0600: solo l'utente stesso può collegarsi.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .bridge_host import socket_path

log = logging.getLogger(__name__)
MAX_LINE = 64 * 1024 * 1024
SITES = ("chatgpt", "claude", "gemini", "copilot", "deepseek")


class _Client:
    def __init__(self, sock: QLocalSocket):
        self.sock = sock
        self.buf = b""
        self.browser = "browser"
        self.version = ""
        self.last_active = 0.0
        self.tabs: dict[str, int] = {}  # servizio -> ultima scheda attiva


class BridgeServer(QObject):
    clients_changed = Signal()
    run_requested = Signal(dict)
    summary_received = Signal(dict)
    screenshot_requested = Signal(dict)
    diagnostics_requested = Signal(dict)
    site_activated = Signal(str)
    package_result = Signal(bool)

    def __init__(self, parent=None, path: str | None = None):
        super().__init__(parent)
        self.path = path or socket_path()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.clients: list[_Client] = []

    # ------------------------------------------------------------ avvio
    def start(self) -> bool:
        folder = Path(self.path).parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.chmod(folder, 0o700)
        except OSError as exc:
            log.warning("cartella del socket non utilizzabile: %s", exc)
            return False
        probe = QLocalSocket()
        probe.connectToServer(self.path)
        if probe.waitForConnected(300):  # c'è già un'altra finestra di Helpix con il collegamento
            probe.disconnectFromServer()
            log.info("bridge già attivo in un'altra istanza di Helpix")
            return False
        QLocalServer.removeServer(self.path)
        ok = self.server.listen(self.path)
        if not ok:
            log.warning("bridge non avviato: %s", self.server.errorString())
        else:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        return ok

    def stop(self):
        clients, self.clients = list(self.clients), []
        for c in clients:
            try:
                c.sock.disconnected.disconnect(self._on_disconnected)
                c.sock.disconnectFromServer()
            except (RuntimeError, TypeError):
                pass
        self.server.close()
        QLocalServer.removeServer(self.path)

    # ------------------------------------------------------------ connessioni
    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            client = _Client(sock)
            self.clients.append(client)
            # metodi legati al server: Qt li scollega da solo quando il server viene distrutto
            sock.readyRead.connect(self._on_ready_read)
            sock.disconnected.connect(self._on_disconnected)
            self.clients_changed.emit()

    def _client_for(self, sock):
        return next((c for c in self.clients if c.sock is sock), None)

    def _on_ready_read(self):
        client = self._client_for(self.sender())
        if client:
            self._read(client)

    def _on_disconnected(self):
        client = self._client_for(self.sender())
        if client:
            self._gone(client)

    def _gone(self, client: _Client):
        if client in self.clients:
            self.clients.remove(client)
            try:
                client.sock.deleteLater()
            except RuntimeError:  # già distrutto insieme al server
                pass
            self.clients_changed.emit()

    def _read(self, client: _Client):
        client.buf += bytes(client.sock.readAll())
        if len(client.buf) > MAX_LINE:
            log.warning("messaggio troppo grande dal browser: chiudo")
            client.sock.disconnectFromServer()
            return
        while b"\n" in client.buf:
            line, client.buf = client.buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(msg, dict):
                self._handle(client, msg)

    def _handle(self, client: _Client, msg: dict):
        kind = msg.get("type")
        site = msg.get("site") if msg.get("site") in SITES else None
        tab = msg.get("tab")
        if kind == "tab_closed":
            if site and client.tabs.get(site) == tab:
                del client.tabs[site]
                self.clients_changed.emit()
            return
        if site and isinstance(tab, int):
            client.tabs[site] = tab
            client.last_active = time.monotonic()
        msg["_client"] = client
        if kind == "hello":
            client.browser = str(msg.get("browser") or "browser")[:40]
            client.version = str(msg.get("version") or "")[:20]
            tabs = msg.get("tabs")
            if isinstance(tabs, dict):  # schede già aperte (ad es. dopo un riavvio di Helpix)
                client.tabs.update({s: t for s, t in tabs.items() if s in SITES and isinstance(t, int)})
                if client.tabs:
                    client.last_active = time.monotonic()
            from . import __version__
            self.send(client, {"type": "hello_ack", "app": __version__})
            self.clients_changed.emit()
        elif kind == "active" and site:
            self.site_activated.emit(site)
        elif kind == "run" and site and isinstance(msg.get("cmd"), str):
            self.run_requested.emit(msg)
        elif kind == "summary" and site and isinstance(msg.get("text"), str):
            self.summary_received.emit(msg)
        elif kind == "screenshot" and site:
            self.screenshot_requested.emit(msg)
        elif kind == "diagnostics" and site:
            self.diagnostics_requested.emit(msg)
        elif kind == "package_result":
            self.package_result.emit(bool(msg.get("ok")))

    # ------------------------------------------------------------ invio
    def send(self, client: _Client, obj: dict) -> bool:
        if client not in self.clients:
            return False
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        client.sock.write(QByteArray(data))
        client.sock.flush()
        return True

    @property
    def connected(self) -> bool:
        return bool(self.clients)

    def browsers(self) -> list[str]:
        return sorted({c.browser for c in self.clients})

    def target(self, site: str):
        """Il browser e la scheda dove l'utente ha usato quel servizio più di recente."""
        best = None
        for c in self.clients:
            if site in c.tabs and (best is None or c.last_active > best.last_active):
                best = c
        if best is not None:
            return best, best.tabs[site]
        recent = max(self.clients, key=lambda c: c.last_active, default=None)
        return (recent, None) if recent else (None, None)

    def has_site(self, site: str) -> bool:
        return any(site in c.tabs for c in self.clients)

    def _to_site(self, site: str, obj: dict, client=None, tab=None) -> bool:
        if client is None:
            client, tab = self.target(site)
        if client is None:
            return False
        obj = dict(obj, site=site)
        if tab is not None:
            obj["tab"] = tab
        return self.send(client, obj)

    def paste_text(self, site: str, text: str, client=None, tab=None) -> bool:
        return self._to_site(site, {"type": "paste_text", "text": text}, client, tab)

    @staticmethod
    def encode_image(path: str) -> dict | None:
        """PNG (o JPEG se enorme) in base64, pronto per l'estensione."""
        img = QImage(path)
        if img.isNull():
            return None
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        if ba.size() > 6_000_000:  # immagini enormi: JPEG per non intasare il canale
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.convertToFormat(QImage.Format.Format_RGB888).save(buf, "JPEG", 85)
            mime, name = "image/jpeg", Path(path).with_suffix(".jpg").name
        else:
            mime, name = "image/png", Path(path).with_suffix(".png").name
        return {"mime": mime, "name": name, "data": base64.b64encode(bytes(ba)).decode("ascii")}

    def paste_image(self, site: str, path: str, client=None, tab=None) -> bool:
        image = self.encode_image(path)
        return bool(image) and self._to_site(site, {"type": "paste_image", **image}, client, tab)

    def open_site(self, site: str, url: str) -> bool:
        """Porta in primo piano la scheda del servizio nel browser collegato (o ne apre una)."""
        client, tab = self.target(site)
        return client is not None and self.send(client, {"type": "open", "site": site, "url": url, "tab": tab})

    def open_paste(self, site: str, url: str, text: str, images: list[str]) -> bool:
        """Apre una chat nuova del servizio nel browser e ci incolla il task (testo + screenshot)."""
        client, _tab = self.target(site)
        if client is None:
            return False
        encoded = [e for e in (self.encode_image(p) for p in images) if e]
        return self.send(client, {"type": "open_paste", "site": site, "url": url, "text": text, "images": encoded})

    def run_status(self, request: dict, state: str, **extra) -> bool:
        client = request.get("_client")
        if client is None:
            return False
        return self.send(client, {"type": "run_status", "id": request.get("id"), "tab": request.get("tab"),
                                  "state": state, **extra})

    def notify(self, request: dict, text: str) -> bool:
        client = request.get("_client")
        return bool(client) and self.send(client, {"type": "notify", "tab": request.get("tab"), "text": text})
