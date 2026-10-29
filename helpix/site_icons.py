# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Icone ufficiali dei servizi di IA (le favicon pubblicate dai siti stessi).

Helpix non ridisegna i loghi: scarica l'icona che ogni sito pubblica per i browser
(apple-touch-icon o favicon.ico), oppure la riceve dal browser integrato quando la pagina
si apre, e la conserva in cache. Finché non è disponibile mostra l'iniziale.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPixmap

from .config import DATA_DIR

log = logging.getLogger(__name__)
CACHE = DATA_DIR / "cache" / "site-icons"

# servizio -> sito da cui prendere l'icona
ORIGINS = {
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "copilot": "https://copilot.microsoft.com",
    "deepseek": "https://chat.deepseek.com",
    "ollama": "https://ollama.com",
}
# fornitore API -> icona del servizio corrispondente
PROVIDER_ICON = {"anthropic": "claude", "openai": "chatgpt", "gemini": "gemini", "deepseek": "deepseek",
                 "ollama": "ollama"}
LABELS = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini", "copilot": "Copilot",
          "deepseek": "DeepSeek", "ollama": "Ollama"}
PATHS = ("/apple-touch-icon.png", "/favicon.ico", "/favicon.png")
MIN_GOOD = 64  # sotto questa dimensione si continua a cercare un'icona migliore


class _Notifier(QObject):
    changed = Signal(str)


notifier = _Notifier()


def _path(key: str) -> Path:
    return CACHE / f"{key}.png"


def cached_size(key: str) -> int:
    img = QImage(str(_path(key)))
    return 0 if img.isNull() else min(img.width(), img.height())


def store(key: str, image: QImage) -> bool:
    """Salva l'icona se è più grande di quella già in cache."""
    if image.isNull() or min(image.width(), image.height()) <= cached_size(key):
        return False
    CACHE.mkdir(parents=True, exist_ok=True)
    if max(image.width(), image.height()) > 256:
        image = image.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    image.save(str(_path(key)), "PNG")
    _tile.cache_clear()
    notifier.changed.emit(key)
    return True


def store_icon(key: str, ic: QIcon) -> None:
    """Icona ricevuta dal browser integrato (page.iconChanged)."""
    if ic.isNull():
        return
    sizes = ic.availableSizes() or [ic.actualSize(QPixmap(256, 256).size())]
    best = max(sizes, key=lambda s: s.width() * s.height())
    store(key, ic.pixmap(best).toImage())


def fetch_missing(keys=None) -> dict:
    """Scarica le icone mancanti o troppo piccole. Bloccante: va eseguita in un thread.

    Non salva nulla: restituisce {servizio: QImage}, da passare ad `apply_fetched` nel thread
    dell'interfaccia (che avvisa i widget del cambio).
    """
    import requests

    found: dict = {}
    for key in keys or ORIGINS:
        if cached_size(key) >= MIN_GOOD:
            continue
        for path in PATHS:
            try:
                r = requests.get(ORIGINS[key] + path, timeout=(5, 10),
                                 headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            except requests.RequestException as exc:
                log.info("icona %s%s non scaricata: %s", key, path, exc)
                break  # sito non raggiungibile: inutile provare altri percorsi
            if r.status_code != 200 or not r.content:
                continue
            img = QImage()
            if not img.loadFromData(r.content):
                continue
            best = found.get(key)
            if best is None or min(img.width(), img.height()) > min(best.width(), best.height()):
                found[key] = img
            if min(img.width(), img.height()) >= MIN_GOOD:
                break
    return found


def apply_fetched(found: dict) -> None:
    for key, img in found.items():
        store(key, img)


class _Bridge(QObject):
    """Riporta nel thread dell'interfaccia le icone scaricate in background."""

    fetched = Signal(object)

    def __init__(self):
        super().__init__()
        self.fetched.connect(self._apply)  # connessione "queued": il destinatario vive nel thread GUI
        self.running = False

    @Slot(object)
    def _apply(self, found):
        self.running = False
        apply_fetched(found)


_bridge: _Bridge | None = None


def refresh_in_background(_parent=None) -> None:
    """Scarica le icone mancanti in un thread daemon (non blocca l'interfaccia né la chiusura)."""
    global _bridge
    if all(cached_size(k) >= MIN_GOOD for k in ORIGINS):
        return
    if _bridge is None:
        _bridge = _Bridge()
    if _bridge.running:
        return
    _bridge.running = True
    bridge = _bridge

    def work():
        try:
            found = fetch_missing()
        except Exception as exc:  # noqa: BLE001
            log.info("download icone fallito: %s", exc)
            found = {}
        bridge.fetched.emit(found)

    threading.Thread(target=work, name="helpix-icons", daemon=True).start()


def _letter_tile(key: str, size: int, scale: int, bg: str, fg: str) -> QImage:
    img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(QRectF(0, 0, size * scale, size * scale), size * scale * 0.24, size * scale * 0.24)
    font = QFont()
    font.setPixelSize(int(size * scale * 0.5))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor(fg))
    p.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignmentFlag.AlignCenter,
               LABELS.get(key, key or "?")[:1].upper())
    p.end()
    return img


@lru_cache(maxsize=256)
def _tile(key: str, size: int, bg: str, fg: str) -> QPixmap:
    """Icona del servizio su una piastrella bianca arrotondata (leggibile in tema chiaro e scuro)."""
    scale = 3
    src = QImage(str(_path(key)))
    if src.isNull():
        img = _letter_tile(key, size, scale, bg, fg)
    else:
        full = size * scale
        img = QImage(full, full, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, full, full), full * 0.24, full * 0.24)
        p.setClipPath(clip)
        p.fillRect(img.rect(), QColor("#FFFFFF"))
        # le apple-touch-icon riempiono il quadrato; le favicon piccole hanno bisogno di margine
        pad = 0 if min(src.width(), src.height()) >= 120 else full * 0.14
        side = full - 2 * pad
        scaled = src.scaled(int(side), int(side), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QRectF((full - scaled.width()) / 2, (full - scaled.height()) / 2,
                           scaled.width(), scaled.height()), scaled)
        p.end()
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(scale)
    return pix


def pixmap(key: str, size: int = 20) -> QPixmap:
    from .theme import C
    return _tile(key, size, C.get("tint", "#E5EFFD"), C.get("accentFg", "#0A66D8"))


def icon(key: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(key, size))


def provider_key(pid: str) -> str:
    return PROVIDER_ICON.get(pid, pid)
