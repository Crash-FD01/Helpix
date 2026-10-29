# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Passaggio di un task da un'IA all'altra.

Un task è una `Session`: oltre alla conversazione del motore API, registra tutto ciò che
passa da Helpix anche nel motore web (screenshot, comandi eseguiti e output, diagnosi,
riepiloghi scritti dall'IA). Da qui si costruisce il "pacchetto" da incollare nella chat
della nuova IA, oppure un file .helpix da salvare o passare a un collega.

Helpix non legge la conversazione dai siti: il riepilogo lo scrive l'IA stessa su
richiesta, e l'utente lo copia con il pulsante Copia della risposta.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from .config import SESSIONS_DIR, SHOTS_DIR, ensure_dirs
from .i18n import current, tr
from .prompts import system_info
from .session import Message, Session

SUMMARY_MARKER = "HELPIX-TASK"
MAX_PACKAGE = 14_000
EXTENSION = ".helpix"

_SUMMARY_REQUEST = {
    "it": f"""Devo continuare questo lavoro con un'altra IA. Scrivi un riepilogo completo di tutto quello che abbiamo fatto finora, dentro UN SOLO blocco di codice, esattamente con questo formato (compila ogni voce, sii preciso e includi nomi, valori, file, messaggi d'errore e comandi rilevanti):

```
{SUMMARY_MARKER}
Obiettivo:
Contesto:
Cosa è stato fatto (comandi, risultati, decisioni):
Stato attuale:
Prossimi passi:
```""",
    "en": f"""I need to continue this work with another AI. Write a complete summary of everything we've done so far, inside ONE code block, exactly in this format (fill in every item, be precise and include relevant names, values, files, error messages and commands):

```
{SUMMARY_MARKER}
Goal:
Context:
What was done (commands, results, decisions):
Current status:
Next steps:
```""",
}


def summary_request() -> str:
    return _SUMMARY_REQUEST.get(current(), _SUMMARY_REQUEST["it"])


def parse_summary(text: str) -> str | None:
    """Estrae il riepilogo dal testo copiato, se contiene il marcatore di Helpix."""
    if not text or SUMMARY_MARKER not in text:
        return None
    body = text[text.index(SUMMARY_MARKER) + len(SUMMARY_MARKER):]
    body = body.split("```")[0].strip()
    return body or None


# etichette dell'obiettivo: formato attuale e formato dei riepiloghi salvati con le versioni precedenti
_GOAL_LABELS = r"Obiettivo|Goal|Objective|Problema|Problem"


def extract_goal(summary: str) -> str:
    """L'obiettivo dal riepilogo, sia «Obiettivo: testo» sia «Obiettivo:» con il testo a capo."""
    m = re.search(rf"^(?:{_GOAL_LABELS})\s*:[ \t]*(.*?)\s*$", summary or "", re.M | re.I)
    if not m:
        return ""
    if m.group(1).strip():
        return m.group(1).strip()
    rest = (summary or "")[m.end():].lstrip("\n").splitlines()
    first = rest[0].strip() if rest else ""
    return "" if not first or re.match(r"^[^:]{2,80}:\s*$", first) else first


extract_problem = extract_goal  # nome usato fino alla 0.8.6


def latest(session: Session, kind: str) -> Message | None:
    return next((m for m in reversed(session.messages) if m.kind == kind), None)


def screenshots(session: Session, limit: int = 3) -> list[str]:
    paths: list[str] = []
    for m in reversed(session.messages):
        for p in reversed(m.images):
            if os.path.exists(p) and p not in paths:
                paths.append(p)
        if len(paths) >= limit:
            break
    return list(reversed(paths[:limit]))


def command_outputs(session: Session) -> list[Message]:
    return [m for m in session.messages if m.kind == "output"]


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def build_handoff(session: Session, problem: str, source: str, *, include_commands: bool = True,
                  include_screens: bool = True, include_system: bool = False, max_commands: int = 6) -> tuple[str, list[str]]:
    """Testo e immagini da incollare nella chat della nuova IA."""
    outputs = command_outputs(session)
    intro = tr("Sto continuando un lavoro iniziato con un'altra IA ({source}). Ti passo tutto il contesto: "
               "riparti da dove eravamo rimasti, senza rifare ciò che è già stato fatto.").format(source=source)
    if outputs:  # si lavora sul PC: indicazioni per i comandi da eseguire con Helpix
        intro += " " + tr("Quando mi proponi comandi, scrivine uno per blocco di codice e usa solo comandi non "
                          "interattivi: li eseguirò e ti incollerò l'output.")
    parts = [intro]
    summary = latest(session, "summary")
    # l'obiettivo a parte solo se non è già quello scritto nel riepilogo
    if problem.strip() and not (summary and problem.strip() == extract_goal(summary.text)):
        parts += ["", "## " + tr("Obiettivo"), problem.strip()]

    if summary:
        who = summary.meta.get("source", source)
        parts += ["", "## " + tr("Riepilogo del lavoro fatto finora (scritto da {who})").format(who=who),
                  summary.text.strip()]
    else:
        chat = [m for m in session.messages if m.kind == "chat" and m.role in ("user", "assistant")]
        if chat:
            parts += ["", "## " + tr("Conversazione finora (estratto)")]
            for m in chat[-8:]:
                role = tr("Utente") if m.role == "user" else tr("IA")
                parts.append(f"**{role}:** {_clip(m.text, 700)}")

    if include_commands and outputs:
        shown = outputs[-max_commands:]
        parts += ["", "## " + tr("Comandi già eseguiti e risultati")]
        if len(outputs) > len(shown):
            parts.append(tr("(ultimi {n} di {total})").format(n=len(shown), total=len(outputs)))
        for m in shown:
            cmd = m.meta.get("cmd", "")
            parts += [f"$ {cmd}  →  " + tr("codice di uscita {rc}").format(rc=m.meta.get("rc", "?")),
                      "```", _clip(m.meta.get("output", ""), 1200) or tr("(nessun output)"), "```"]

    diag = latest(session, "diagnostics")
    if include_system:
        info = system_info()
        parts += ["", "## " + tr("Sistema"),
                  tr("- Sistema: {distro} ({arch}), kernel {kernel}").format(**info),
                  tr("- Desktop: {desktop} (sessione {session})").format(**info),
                  tr("- Gestore pacchetti: {pkg}; altri formati: {extra}").format(**info)]
    if diag and not summary:
        parts += ["", tr("Diagnosi raccolta in precedenza:"), _clip(diag.text, 3000)]

    images = screenshots(session) if include_screens else []
    if images:
        parts += ["", tr("Ti allego anche gli ultimi {n} screenshot del problema.").format(n=len(images))]
    parts += ["", tr("Dimmi qual è il prossimo passo.")]
    text = "\n".join(parts).strip()
    if len(text) > MAX_PACKAGE:
        text = text[:MAX_PACKAGE] + "\n[…]"
    return text, images


def record_summary(session: Session, summary: str, source: str) -> None:
    session.add(Message("assistant", summary, kind="summary", meta={"source": source}))
    problem = extract_goal(summary)
    if problem and session.title in (tr("Nuova sessione"), "Nuova sessione", "New session"):
        session.title = _clip(problem, 58)
        session.save()


# ------------------------------------------------------------------ file .helpix
def export_task(session: Session, dest: str | Path, password: str | None = None, redact=None) -> Path:
    """Salva il task (con gli screenshot) in un unico file .helpix (zip), cifrato se c'è una password.
    redact: funzione testo → testo (scudo privacy acceso), applicata a tutti i testi del task."""
    dest = Path(dest)
    if dest.suffix != EXTENSION:
        dest = dest.with_suffix(EXTENSION)
    data = session.to_dict()
    if redact is not None:
        def clean(v):
            if isinstance(v, str):
                return redact(v)
            if isinstance(v, dict):
                return {k: clean(x) for k, x in v.items()}
            if isinstance(v, list):
                return [clean(x) for x in v]
            return v
        data["title"], data["cwd"] = clean(data.get("title", "")), clean(data.get("cwd", ""))
        for m in data["messages"]:
            m["text"] = clean(m.get("text", ""))
            m["meta"] = clean(m.get("meta", {}))
    names: dict[str, str] = {}
    for m in data["messages"]:
        new = []
        for p in m.get("images", []):
            if os.path.exists(p):
                names.setdefault(p, f"images/{len(names):03d}{Path(p).suffix or '.png'}")
                new.append(names[p])
        m["images"] = new
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("task.json", json.dumps({"format": "helpix-task", "version": 1, "session": data},
                                            ensure_ascii=False, indent=1))
        for src, arc in names.items():
            zf.write(src, arc)
    blob = buf.getvalue()
    if password:
        from .security import encrypt_bytes
        blob = encrypt_bytes(blob, password)
    dest.write_bytes(blob)
    if password:
        os.chmod(dest, 0o600)
    return dest


def import_task(path: str | Path, password: str | None = None) -> Session:
    """Importa un file .helpix come nuovo task (nuovo identificativo, screenshot copiati).

    Per un file cifrato serve la password: senza solleva PasswordRequired, se sbagliata WrongPassword.
    """
    ensure_dirs()
    from .security import PasswordRequired, decrypt_bytes, is_encrypted_file
    source = path
    if is_encrypted_file(path):
        if not password:
            raise PasswordRequired()
        source = io.BytesIO(decrypt_bytes(Path(path).read_bytes(), password))
    with zipfile.ZipFile(source) as zf:
        meta = json.loads(zf.read("task.json"))
        if meta.get("format") != "helpix-task":
            raise ValueError(tr("Il file non è un task di Helpix."))
        data = meta["session"]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        mapping: dict[str, str] = {}
        for name in zf.namelist():
            if not name.startswith("images/") or name.endswith("/"):
                continue
            target = SHOTS_DIR / f"import-{stamp}-{uuid.uuid4().hex[:6]}{Path(name).suffix}"
            with zf.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mapping[name] = str(target)
    sid = f"{stamp}-{uuid.uuid4().hex[:6]}"
    while (SESSIONS_DIR / f"{sid}.json").exists():
        sid = f"{stamp}-{uuid.uuid4().hex[:6]}"
    s = Session(data.get("provider", "anthropic"), data.get("model", ""),
                data.get("cwd") or os.path.expanduser("~"), sid=sid)
    s.title = data.get("title") or s.title
    s.created = data.get("created", s.created)
    for m in data.get("messages", []):
        m["images"] = [mapping[p] for p in m.get("images", []) if p in mapping]
        s.messages.append(Message.from_dict(m))
    s.save()
    return s
