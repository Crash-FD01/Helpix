# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sessioni di troubleshooting salvate in locale, in un formato neutro.

Il formato non dipende dal fornitore: ogni messaggio ha ruolo, testo, eventuali
screenshot e metadati (comando eseguito, codice di uscita...). Per questo si può
cambiare agente a metà task e riprendere una sessione con un altro modello.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

from .config import SESSIONS_DIR, ensure_dirs, write_private
from .i18n import tr

DEFAULT_TITLE = tr("Nuova sessione")


@dataclass
class Message:
    role: str                    # user | assistant | note
    text: str
    images: list = field(default_factory=list)
    kind: str = "chat"           # chat | output | note | error
    meta: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(role=d.get("role", "user"), text=d.get("text", ""),
                   images=list(d.get("images", [])), kind=d.get("kind", "chat"),
                   meta=dict(d.get("meta", {})), ts=d.get("ts", time.time()))


class Session:
    VERSION = 1

    def __init__(self, provider: str, model: str, cwd: str, sid: str | None = None):
        self.id = sid or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.title = DEFAULT_TITLE
        self.created = time.time()
        self.updated = self.created
        self.provider = provider
        self.model = model
        self.cwd = cwd
        self.site: str | None = None  # servizio web usato per ultimo (motore web)
        self.messages: list[Message] = []

    @property
    def path(self):
        return SESSIONS_DIR / f"{self.id}.json"

    def add(self, msg: Message) -> None:
        self.messages.append(msg)
        if self.title == DEFAULT_TITLE and msg.role == "user" and msg.kind == "chat":
            text = " ".join(msg.text.split())
            if text:
                self.title = text[:57] + "…" if len(text) > 58 else text
        self.save()

    def to_dict(self) -> dict:
        return {"version": self.VERSION, "id": self.id, "title": self.title,
                "created": self.created, "updated": self.updated,
                "provider": self.provider, "model": self.model, "cwd": self.cwd, "site": self.site,
                "messages": [asdict(m) for m in self.messages]}

    def save(self) -> None:
        if not self.messages:  # niente file per le sessioni vuote
            return
        ensure_dirs()
        self.updated = time.time()
        write_private(self.path, json.dumps(self.to_dict(), ensure_ascii=False, indent=1))

    @classmethod
    def load(cls, sid: str) -> "Session":
        data = json.loads((SESSIONS_DIR / f"{sid}.json").read_text(encoding="utf-8"))
        s = cls(data.get("provider", "anthropic"), data.get("model", ""),
                data.get("cwd") or os.path.expanduser("~"), sid=data.get("id", sid))
        s.title = data.get("title", DEFAULT_TITLE)
        s.created = data.get("created", s.created)
        s.updated = data.get("updated", s.updated)
        s.site = data.get("site")
        s.messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return s

    def to_wire(self, vision: bool, max_images: int = 4, max_messages: int = 80) -> list[dict]:
        """Converte la storia nel formato neutro da passare ai connettori.

        Invia al massimo `max_images` screenshot (i più recenti) per contenere costi
        e dimensione della richiesta; quelli esclusi vengono segnalati nel testo.
        """
        msgs = [m for m in self.messages if m.role in ("user", "assistant")][-max_messages:]
        budget = max_images
        wire = []
        for m in reversed(msgs):
            text, imgs = m.text, []
            for p in m.images:
                if not os.path.exists(p):
                    text += tr("\n[Screenshot non più disponibile]")
                elif not vision:
                    text += tr("\n[Screenshot allegato: il modello attuale non può vedere le immagini]")
                elif budget > 0:
                    imgs.append(p)
                    budget -= 1
                else:
                    text += tr("\n[Screenshot precedente omesso per limitare la dimensione della richiesta]")
            wire.append({"role": m.role, "text": text, "images": imgs})
        wire.reverse()
        return wire


def list_sessions() -> list[dict]:
    out = []
    if not SESSIONS_DIR.exists():
        return out
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": f.stem, "title": data.get("title", DEFAULT_TITLE),
                    "updated": data.get("updated", f.stat().st_mtime),
                    "provider": data.get("provider", ""), "model": data.get("model", ""), "site": data.get("site"),
                    "count": len(data.get("messages", []))})
    out.sort(key=lambda d: d["updated"], reverse=True)
    return out


def delete_session(sid: str) -> None:
    (SESSIONS_DIR / f"{sid}.json").unlink(missing_ok=True)
