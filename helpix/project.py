# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Testo dei progetti (beta): PROJECT.md, contesto per l'IA, aggiornamenti HELPIX-PROJECT, richieste HELPIX-NOTA.

Niente Qt e niente accesso al disco: lavora su stringhe. Specifica: docs/PROGETTI.md.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .i18n import current, tr

PROJECT_MARKER = "HELPIX-PROJECT"
NOTE_MARKER = "HELPIX-NOTA"
NOTE_MARKERS = ("HELPIX-NOTA", "HELPIX-NOTE")
AGENT_FILE = "HELPIX-PROJECT.md"
TOKEN_LIMIT = 1000
RECENT_NOTES = 3

# chiave, titolo italiano, titolo inglese, inizi riconosciuti (anche dei file scritti nell'altra lingua)
SECTIONS = [
    ("goal", "Obiettivo", "Goal", ("obiettiv", "goal", "scopo", "objective")),
    ("context", "Contesto", "Context", ("contest", "context", "background")),
    ("decisions", "Decisioni in vigore", "Decisions in force", ("decision",)),
    ("status", "Stato", "Status", ("stato", "status", "state")),
    ("next", "Prossimi passi", "Next steps", ("prossim", "next", "todo", "da fare")),
    ("refs", "Riferimenti", "References", ("riferiment", "referenc", "link")),
    ("private", "Solo per me", "Only for me", ("solo per me", "only for me", "private", "privat")),
]
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", text).strip()


def estimate_tokens(text: str) -> int:
    """Stima grossolana: circa 4 caratteri per token."""
    return math.ceil(len(text or "") / 4)


def section_key(heading: str) -> str | None:
    h = _norm(heading).strip("#: ")
    for key, it, en, starts in SECTIONS:
        if h in (_norm(it), _norm(en)) or any(h.startswith(s) for s in starts):
            return key
    return None


def section_title(key: str) -> str:
    for k, it, en, _ in SECTIONS:
        if k == key:
            return en if current() == "en" else it
    return key


# ------------------------------------------------------------------ PROJECT.md
@dataclass
class Doc:
    preamble: list[str] = field(default_factory=list)
    sections: list[list] = field(default_factory=list)  # [titolo, [righe]]

    def find(self, key: str | None, name: str = "") -> list | None:
        for sec in self.sections:
            if (key and section_key(sec[0]) == key) or (not key and _norm(sec[0]) == _norm(name)):
                return sec
        return None

    def add_section(self, title: str) -> list:
        sec = [title, []]
        private = self.find("private")
        self.sections.insert(self.sections.index(private) if private else len(self.sections), sec)
        return sec


def parse(text: str) -> Doc:
    doc = Doc()
    target = doc.preamble
    for line in (text or "").splitlines():
        if line.startswith("## "):
            sec = [line[3:].strip(), []]
            doc.sections.append(sec)
            target = sec[1]
        else:
            target.append(line)
    return doc


def render(doc: Doc) -> str:
    out = list(doc.preamble)
    while out and not out[-1].strip():
        out.pop()
    for title, lines in doc.sections:
        body = list(lines)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        out += ["", f"## {title}"] + body
    return "\n".join(out).strip("\n") + "\n"


def title_of(text: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def strip_private(text: str) -> str:
    """PROJECT.md senza la sezione «Solo per me»: è quello che può uscire verso un'IA."""
    doc = parse(text)
    doc.sections = [s for s in doc.sections if section_key(s[0]) != "private"]
    return render(doc)


def template(name: str, goal: str = "", context: str = "") -> str:
    def title(key):
        return section_title(key)
    lines = [f"# {name.strip()}", "", f"## {title('goal')}", goal.strip() or "-", "",
             f"## {title('context')}", context.strip() or "-", "", f"## {title('decisions')}", "",
             f"## {title('status')}", tr("Appena creato."), "", f"## {title('next')}", "",
             f"## {title('refs')}", "", f"## {title('private')}", ""]
    return "\n".join(lines)


def import_request() -> str:
    """Richiesta da copiare in un'altra IA (o in un Project di Claude) per avere il contesto già nel formato."""
    heads = ", ".join(section_title(k) for k, *_ in SECTIONS if k != "private")
    return tr("Riassumi questo progetto per Helpix in un file Markdown breve (massimo circa 800 parole), con «# nome del "
              "progetto» in cima e queste sezioni «## »: {heads}. Nelle decisioni scrivi solo quelle ancora valide, "
              "una per riga con la data (AAAA-MM-GG). Niente dettagli superati.").format(heads=heads)


# ------------------------------------------------------------------ contesto per l'IA
def recent_index_lines(index_text: str, n: int = RECENT_NOTES) -> list[str]:
    lines = [ln.strip() for ln in (index_text or "").splitlines() if ln.strip().startswith("- ")]
    return lines[-n:]


def context_text(name: str, project_text: str, index_text: str, *, for_chat: bool = True,
                 agent_cmds: tuple[str, str] | None = None) -> str:
    """Testo da dare all'IA all'apertura del progetto (mai la sezione «Solo per me»)."""
    body = strip_private(project_text).strip()
    recent = recent_index_lines(index_text)
    parts = [tr("Sto lavorando al progetto «{name}» con Helpix. Qui sotto c'è lo stato attuale del progetto "
                "(PROJECT.md): riparti da qui, senza rifare quello che è già deciso o fatto.").format(name=name),
             "", body, "", "## " + tr("Ultime note")]
    parts += recent or [tr("(nessuna nota ancora)")]
    parts.append("")
    if agent_cmds:
        parts.append(tr("Le note più vecchie sono nell'archivio del progetto. Per leggerne una esegui `{cat}`; per "
                        "cercare `{search}`. Leggile solo quando servono.").format(cat=agent_cmds[0],
                                                                                 search=agent_cmds[1]))
    else:
        parts.append(tr("Le note più vecchie sono in un archivio. Se te ne serve una, scrivi su una riga da sola "
                        "`{marker}: titolo della nota` e te la passerò. Non inventare il contenuto delle note che "
                        "non hai.").format(marker=NOTE_MARKER))
    if for_chat:
        parts.append(tr("Rispondi in una riga che hai il contesto, poi aspetta la mia domanda."))
    return "\n".join(parts).strip() + "\n"


def _format_rules(today: str) -> str:
    heads = ", ".join(section_title(k) for k, *_ in SECTIONS if k != "private")
    return tr("""- una riga «NOTA: » con un titolo breve per questa sessione;
- da 2 a 8 righe su cosa abbiamo fatto, risultati, problemi aperti;
- una riga «MODIFICHE:» e, sotto, solo le modifiche a PROJECT.md, una per riga:
  + Sezione: riga da aggiungere
  - Sezione: riga da togliere, scritta com'è adesso
  ~ Sezione: riga com'è adesso => riga nuova
  = Sezione: nuovo testo dell'intera sezione
Sezioni: {heads}. Non toccare «{private}».
Le decisioni nuove iniziano con la data di oggi ({today}); una decisione che ne sostituisce un'altra si scrive con ~.
Aggiorna sempre lo Stato. Se non cambia niente, scrivi solo la NOTA e il testo.""").format(
        heads=heads, private=section_title("private"), today=today)


def update_request(project_text: str, *, today: str | None = None, for_agent: bool = False) -> str:
    """Richiesta all'IA del blocco HELPIX-PROJECT (solo le modifiche, più la nota della sessione).

    Niente blocchi di codice nella richiesta: Helpix cerca nella pagina il blocco che inizia con il marcatore e
    la richiesta stessa non deve sembrare una risposta."""
    today = today or time.strftime("%Y-%m-%d")
    rules = _format_rules(today)
    if for_agent:
        return tr("Aggiorniamo il file del progetto per Helpix. PROJECT.md attuale è nelle tue istruzioni. Scrivi il "
                  "file {file} (sovrascrivilo), senza blocchi di codice: la prima riga dev'essere {marker}, poi:\n"
                  "{rules}").format(file=AGENT_FILE, marker=PROJECT_MARKER, rules=rules)
    return tr("Aggiorniamo il file del progetto per Helpix. PROJECT.md adesso è così:\n\n<<<\n{text}>>>\n\n"
              "Rispondi con UN SOLO blocco di codice. La prima riga del blocco dev'essere {marker}, poi:\n"
              "{rules}").format(text=strip_private(project_text), marker=PROJECT_MARKER, rules=rules)


def compact_request(project_text: str, *, for_agent: bool = False) -> str:
    tokens = estimate_tokens(strip_private(project_text))
    where = (tr("Scrivi il file {file} (sovrascrivilo), senza blocchi di codice").format(file=AGENT_FILE) if for_agent
             else tr("Rispondi con UN SOLO blocco di codice"))
    text = "" if for_agent else "\n\n<<<\n" + strip_private(project_text) + ">>>"
    return tr("Il file del progetto per Helpix è diventato lungo (circa {tokens} token).{text}\n\nRiscrivilo più "
              "corto (al massimo circa {limit} token) senza perdere decisioni in vigore, vincoli e stato: accorpa, "
              "togli i dettagli superati o che stanno già nelle note. {where}: prima riga {marker}, seconda riga "
              "COMPLETO, poi il nuovo PROJECT.md intero (stesse sezioni, «# titolo» in cima). Non includere «{private}»."
              ).format(tokens=tokens, text=text, limit=TOKEN_LIMIT, where=where, marker=PROJECT_MARKER,
                       private=section_title("private"))


# ------------------------------------------------------------------ lettura del blocco HELPIX-PROJECT
@dataclass
class Update:
    title: str = ""
    body: str = ""
    ops: list[tuple[str, str, str]] = field(default_factory=list)  # (simbolo, sezione, testo)
    full_text: str | None = None  # «COMPLETO»: PROJECT.md intero (compattazione)


_OP = re.compile(r"^\s*([+\-~=])\s*([^:]{2,60}?)\s*:\s*(.*)$")
_CHANGES = re.compile(r"^\s*(modifiche|changes)\s*:?\s*$", re.I)
_NOTE = re.compile(r"^\s*(nota|note)\s*:\s*(.*)$", re.I)


def parse_update(text: str) -> Update | None:
    """Il blocco HELPIX-PROJECT scritto dall'IA (risposta, file dell'agente o testo copiato), o None."""
    if not text or PROJECT_MARKER not in text:
        return None
    # il marcatore su una riga da solo: nella richiesta (copiata per sbaglio) sta in mezzo a una frase
    all_lines = text.splitlines()
    start = next((i for i, ln in enumerate(all_lines) if ln.strip().strip("`").strip() == PROJECT_MARKER), None)
    if start is None:
        return None
    body = "\n".join(all_lines[start + 1:]).split("```")[0]
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return None
    if lines[0].strip().upper() in ("COMPLETO", "FULL", "COMPLETE"):
        full = "\n".join(lines[1:]).strip("\n")
        return Update(full_text=full + "\n") if full.strip() else None
    up = Update()
    note: list[str] = []
    in_ops = False
    for line in lines:
        if not in_ops:
            m = _NOTE.match(line)
            if m and not up.title:
                up.title = m.group(2).strip()
                continue
            if _CHANGES.match(line):
                in_ops = True
                continue
            note.append(line)
            continue
        m = _OP.match(line)
        # dopo «= Sezione:» le righe di un elenco («- passo: dettaglio») sono il testo della sezione, non modifiche
        if m and up.ops and up.ops[-1][0] == "=" and section_key(m.group(2)) is None:
            m = None
        if m:
            up.ops.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
        elif line.strip() and up.ops:  # continuazione (per «=» su più righe)
            sym, sec, txt = up.ops[-1]
            up.ops[-1] = (sym, sec, (txt + "\n" + line.rstrip()).strip("\n"))
    up.body = "\n".join(note).strip()
    if "<" in up.title and ">" in up.title:  # la richiesta copiata per sbaglio, non una risposta
        return None
    return up if (up.title or up.body or up.ops) else None


def _clean_line(line: str) -> str:
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line or "").strip()
    return _DATE.sub("", t).strip(" -–—:")


def _matches(target: str, line: str) -> bool:
    a, b = _norm(_clean_line(target)).strip(" ."), _norm(_clean_line(line)).strip(" .")
    if not a or not b:
        return False
    if a == b or (len(a) >= 8 and a in b):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _bullet(text: str, key: str | None, today: str) -> str:
    t = text.strip()
    if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", t):
        t = re.sub(r"^\s*[*•]\s+", "- ", t)
        inner = t[2:].strip() if t.startswith("- ") else t
    else:
        inner = t
        t = "- " + t
    if key == "decisions" and not _DATE.match(inner):
        t = f"- {today} {inner}"
    return t


@dataclass
class Result:
    text: str
    applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    superseded: list[tuple[str, str]] = field(default_factory=list)


def apply_update(project_text: str, update: Update, today: str | None = None) -> Result:
    """Applica le modifiche a PROJECT.md. «Solo per me» non si tocca; le modifiche che non trovano la riga finiscono
    negli avvisi (l'utente le vede nell'anteprima)."""
    today = today or time.strftime("%Y-%m-%d")
    if update.full_text is not None:
        return _apply_full(project_text, update.full_text)
    doc = parse(project_text)
    res = Result("")
    for sym, sec_name, payload in update.ops:
        key = section_key(sec_name)
        label = section_title(key) if key else sec_name
        if key == "private":
            res.warnings.append(tr("Ignorata (sezione «{s}»): {t}").format(s=label, t=payload))
            continue
        sec = doc.find(key, sec_name)
        if sec is None:
            if sym in "+=":
                sec = doc.add_section(section_title(key) if key else sec_name.strip())
            else:
                res.warnings.append(tr("Sezione «{s}» non trovata: {t}").format(s=label, t=payload))
                continue
        lines = sec[1]
        if sym == "=":
            sec[1] = [""] + payload.splitlines()
            res.applied.append(tr("«{s}» riscritta").format(s=label))
        elif sym == "+":
            new = _bullet(payload, key, today)
            if any(_matches(new, ln) for ln in lines if ln.strip()):
                res.warnings.append(tr("Già presente in «{s}»: {t}").format(s=label, t=payload))
                continue
            # i segnaposto del modello («-») spariscono alla prima riga vera
            sec[1] = [ln for ln in lines if ln.strip() not in ("-", "- ")]
            while sec[1] and not sec[1][-1].strip():
                sec[1].pop()
            sec[1].append(new)
            res.applied.append(tr("Aggiunta in «{s}»: {t}").format(s=label, t=_clean_line(new)))
        elif sym == "-":
            idx = next((i for i, ln in enumerate(lines) if ln.strip() and _matches(payload, ln)), None)
            if idx is None:
                res.warnings.append(tr("Riga da togliere non trovata in «{s}»: {t}").format(s=label, t=payload))
                continue
            removed = lines.pop(idx)
            res.applied.append(tr("Tolta da «{s}»: {t}").format(s=label, t=_clean_line(removed)))
        elif sym == "~":
            parts = re.split(r"\s*(?:=>|→|->)\s*", payload, maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                res.warnings.append(tr("Sostituzione senza «=>»: {t}").format(t=payload))
                continue
            old, new_text = parts
            idx = next((i for i, ln in enumerate(lines) if ln.strip() and _matches(old, ln)), None)
            new = _bullet(new_text, key, today)
            if idx is None:
                res.warnings.append(tr("Riga da sostituire non trovata in «{s}»: {t}").format(s=label, t=old))
                continue
            before = lines[idx]
            lines[idx] = new
            if key == "decisions":
                res.superseded.append((_clean_line(before), _clean_line(new)))
            res.applied.append(tr("Sostituita in «{s}»: {a} → {b}").format(s=label, a=_clean_line(before),
                                                                          b=_clean_line(new)))
    res.text = render(doc)
    return res


def _apply_full(old_text: str, new_text: str) -> Result:
    new = parse(new_text)
    new.sections = [s for s in new.sections if section_key(s[0]) != "private"]
    if not any(ln.startswith("# ") for ln in new.preamble):
        new.preamble = [f"# {title_of(old_text) or 'Progetto'}", ""] + new.preamble
    private = parse(old_text).find("private")
    new.sections.append(private if private else [section_title("private"), []])
    text = render(new)
    return Result(text, applied=[tr("PROJECT.md riscritto più corto: da circa {a} a circa {b} token").format(
        a=estimate_tokens(strip_private(old_text)), b=estimate_tokens(strip_private(text)))])


# ------------------------------------------------------------------ note
def note_text(title: str, body: str, source: str, superseded=(), warnings=(), date: str | None = None) -> str:
    date = date or time.strftime("%Y-%m-%d")
    out = [f"# {title.strip() or tr('Sessione')}", "", f"_{date} · {source}_", "", body.strip() or "-"]
    if superseded:
        out += ["", "## " + tr("Decisioni superate")]
        out += [f"- {a} → {b}" for a, b in superseded]
    if warnings:
        out += ["", "## " + tr("Modifiche non applicate")]
        out += [f"- {w}" for w in warnings]
    return "\n".join(out).rstrip() + "\n"


def note_summary(body: str, limit: int = 120) -> str:
    text = " ".join((body or "").split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


_NOTE_REQ = re.compile(r"^\s*[`*_>]*\s*(?:HELPIX-NOTA|HELPIX-NOTE)\s*[:：]\s*(.+?)\s*[`*_]*\s*$", re.M | re.I)


def parse_note_request(text: str) -> str | None:
    """Titolo della nota chiesta dall'IA con «HELPIX-NOTA: titolo» (testo copiato o risposta), o None."""
    if not text or not any(m in text.upper() for m in NOTE_MARKERS):
        return None
    m = _NOTE_REQ.search(text)
    if not m:
        return None
    title = m.group(1).strip().strip("«»\"'`").strip()
    if not title or title.lower().startswith(("titolo della nota", "title of the note")):
        return None
    return title[:200]


def note_paste(title: str, text: str) -> str:
    return tr("Ecco la nota «{title}» del progetto:\n\n{text}").format(title=title, text=text.strip()) + "\n"


# ------------------------------------------------------------------ bozza della sessione
def session_markdown(session) -> str:
    """Bozza della sessione: quello che è passato da Helpix (comandi, output, diagnosi, riepiloghi, note)."""
    def clip(t: str, n: int) -> str:
        t = (t or "").strip()
        return t if len(t) <= n else t[: n - 1].rstrip() + "…"

    when = time.strftime("%Y-%m-%d %H:%M")
    out = [f"# {tr('Bozza della sessione')} — {session.title}", "",
           f"_{tr('Aggiornata')}: {when} · {tr('task')} {session.id}_", ""]
    for m in session.messages:
        ts = time.strftime("%H:%M", time.localtime(m.ts))
        if m.kind == "output":
            out += [f"### {ts} · $ {m.meta.get('cmd', '')} ({tr('codice')} {m.meta.get('rc', '?')})", "```",
                    clip(m.meta.get("output", ""), 2000) or tr("(nessun output)"), "```", ""]
        elif m.kind == "diagnostics":
            out += [f"### {ts} · {tr('Diagnosi')}", "```", clip(m.text, 3000), "```", ""]
        elif m.kind == "summary":
            out += [f"### {ts} · {tr('Riepilogo')}", clip(m.text, 4000), ""]
        elif m.kind == "shot" or (m.images and m.kind == "chat" and not m.text.strip()):
            out += [f"- {ts} · {tr('Screenshot')}: " + ", ".join(p.rsplit('/', 1)[-1] for p in m.images)]
        elif m.role == "note" or m.kind == "note":
            out += [f"> {ts} · {clip(m.text, 300)}", ""]
        elif m.kind == "chat" and m.role in ("user", "assistant") and m.text.strip():
            who = tr("Utente") if m.role == "user" else tr("IA")
            out += [f"**{ts} · {who}:** {clip(m.text, 1500)}", ""]
    return "\n".join(out).rstrip() + "\n"
