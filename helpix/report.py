# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""«Segnala un problema»: raccoglie le informazioni utili, le passa dal filtro privacy e le invia.

Il pacchetto è un testo Markdown che l'utente vede e può modificare prima dell'invio: quello che vede è
esattamente quello che parte. Va al servizio di segnalazione (un piccolo server su Cloudflare Workers, in
tools/segnalazioni) che apre una issue in un repo privato: il gettone di GitHub sta solo lì, mai nell'app.
Senza servizio configurato, o se non risponde, il pacchetto si salva in un file.

Non entra mai: il contenuto delle note e di PROJECT.md, chiavi, password, percorsi del vault, cronologia
delle chat. Nome utente, nome del PC, indirizzi e simili li toglie il filtro privacy.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import DATA_DIR, LOG_FILE
from .i18n import tr
from .privacy import Redactor
from .system import IS_WINDOWS

# indirizzo del servizio di segnalazione; vuoto = invio non attivo (si salva il file)
REPORT_URL = os.environ.get("HELPIX_REPORT_URL", "")
MAX_BODY = 60000          # le issue di GitHub arrivano a 65536 caratteri: resta margine per l'intestazione
MAX_TITLE = 120
# impostazioni utili per capire un problema; niente percorsi, indirizzi o modelli personalizzati
SETTINGS_KEYS = ("engine", "default_engine", "web_site", "default_site", "default_provider", "agent",
                 "default_agent", "language", "theme", "system_titlebar", "rounded_corners", "always_on_top",
                 "hide_on_screenshot", "tech_mode", "auto_paste_output", "projects_beta", "project_update_mode",
                 "project_autosave_min", "project_versions", "project_token_limit")


@dataclass
class Section:
    key: str
    title: str
    text: str
    default: bool = True      # spuntata all'apertura


def _tail(path: Path, lines: int, chars: int) -> str:
    try:
        data = path.read_bytes()[-chars * 4:]
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    out = text.splitlines()[-lines:]
    return "\n".join(out)[-chars:].strip()


def _qt_version() -> str:
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        return f"PySide6 {PySide6.__version__}, Qt {qVersion()}"
    except Exception:  # noqa: BLE001
        return "?"


def system_section() -> str:
    if IS_WINDOWS:
        os_name = f"Windows {platform.release()} ({platform.version()})"
    else:
        os_name = "Linux"
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        os_name += f", kernel {platform.release()}"
        session = os.environ.get("XDG_SESSION_TYPE", "")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        if session or desktop:
            os_name += f", {desktop or '?'} su {session or '?'}"
    frozen = "installer" if getattr(sys, "frozen", False) else "Python"
    return "\n".join([
        f"- Helpix: {__version__} ({frozen})",
        f"- Sistema: {os_name}, {platform.machine()}",
        f"- Python: {platform.python_version()}",
        f"- {_qt_version()}",
    ])


def settings_section(settings) -> str:
    rows = []
    for key in SETTINGS_KEYS:
        value = settings.get(key) if settings is not None else None
        if value is not None:
            rows.append(f"- {key}: {value}")
    return "\n".join(rows)


def _file_facts(path: Path) -> str:
    """Solo dati tecnici di un file (dimensione, data, primi byte, codifica), mai il contenuto."""
    try:
        st = path.stat()
        head = path.read_bytes()[:8]
    except OSError:
        return f"- {path.name}: assente"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "UTF-16 con BOM"
    elif head.startswith(b"\xef\xbb\xbf"):
        enc = "UTF-8 con BOM"
    else:
        enc = "senza BOM"
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    return f"- {path.name}: {st.st_size} byte, {when}, inizio {head.hex(' ')} ({enc})"


def vault_section(settings, vault) -> str:
    from . import agents
    rows = [f"- progetti e vault attivi: {bool(settings and settings.get('projects_beta'))}",
            f"- vault configurato: {bool(settings and settings.get('vault_dir'))}"]
    if vault is not None:
        for label, attr in (("cifrato", "encrypted"), ("aperto", "is_open")):
            try:
                rows.append(f"- {label}: {bool(getattr(vault, attr))}")
            except Exception:  # noqa: BLE001
                pass
        try:
            if vault.is_open:
                rows.append(f"- progetti: {len(vault.projects())}")
        except Exception:  # noqa: BLE001
            pass
    rows.append(f"- progetto attivo: {bool(settings and settings.get('active_project'))}")
    ws = agents.WORKSPACE
    rows += [_file_facts(ws / name) for name in (agents.PROJECT_FILE, agents.SUMMARY_FILE)]
    return "\n".join(rows)


def logs_sections() -> list[Section]:
    out = []
    main = _tail(LOG_FILE, 400, 24000)
    if main:
        out.append(Section("log", tr("Registro di Helpix (ultime righe)"), main))
    logs = DATA_DIR / "logs"
    quick = _tail(logs / "finestra-rapida.log", 150, 8000)
    if quick:
        out.append(Section("quick", tr("Registro della finestra rapida"), quick))
    try:
        installs = sorted(logs.glob("install-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:2]
    except OSError:
        installs = []
    for p in installs:
        text = _tail(p, 80, 6000)
        if text:
            out.append(Section("install-" + p.stem[8:], tr("Installazione di {name}").format(name=p.stem[8:]),
                               text, default=False))
    return out


def collect(settings=None, vault=None, diagnostics: bool = True, redactor: Redactor | None = None) -> list[Section]:
    """Le sezioni del pacchetto, già filtrate. La diagnosi del PC è facoltativa (spenta all'apertura)."""
    sections = [Section("system", tr("Helpix e sistema"), system_section()),
                Section("settings", tr("Impostazioni"), settings_section(settings)),
                Section("vault", tr("Progetti e vault (senza contenuti)"), vault_section(settings, vault))]
    sections += logs_sections()
    if diagnostics:
        try:
            from .diagnostics import collect as diag
            sections.append(Section("diag", tr("Diagnosi del PC"), diag(), default=False))
        except Exception as exc:  # noqa: BLE001
            sections.append(Section("diag", tr("Diagnosi del PC"), f"(non riuscita: {exc})", default=False))
    return clean(sections, redactor)


def clean(sections: list[Section], redactor: Redactor | None = None) -> list[Section]:
    """Toglie la cartella utente dai percorsi e passa tutto dal filtro privacy (stessi segnaposti ovunque)."""
    red = redactor or Redactor()
    home = str(Path.home())
    out = []
    for s in sections:
        text = s.text.replace(home, "~") if home and len(home) > 3 else s.text
        if IS_WINDOWS:
            text = text.replace(home.replace("\\", "/"), "~")
        out.append(Section(s.key, s.title, red.redact(text)[0], s.default))
    return out


def body(description: str, sections: list[Section]) -> str:
    """Il testo della segnalazione (Markdown), tagliato al limite di GitHub togliendo dall'inizio dei registri."""
    parts = ["## " + tr("Cosa è successo"), "", description.strip() or "-", ""]
    blocks = []
    for s in sections:
        if s.text.strip():
            blocks.append([f"## {s.title}", "", "```", s.text.replace("```", "'''"), "```", ""])
    text = "\n".join(parts + [ln for b in blocks for ln in b])
    excess = len(text) - MAX_BODY
    if excess > 0:  # accorcia i registri più lunghi, tenendo le righe più recenti
        for b in sorted(blocks, key=lambda b: len(b[3]), reverse=True):
            cut = min(excess, max(0, len(b[3]) - 500))
            if cut:
                b[3] = "…\n" + b[3][cut + 2:]
                excess -= cut
            if excess <= 0:
                break
        text = "\n".join(parts + [ln for b in blocks for ln in b])[:MAX_BODY]
    return text


def payload(title: str, text: str) -> dict:
    return {"app": "helpix", "version": __version__, "os": "windows" if IS_WINDOWS else "linux",
            "title": title.strip()[:MAX_TITLE], "body": text[:MAX_BODY]}


class ReportError(Exception):
    pass


def send(data: dict, url: str | None = None, timeout: float = 30.0) -> int:
    """Invia al servizio di segnalazione; restituisce il numero della segnalazione."""
    import requests
    url = url or REPORT_URL
    if not url:
        raise ReportError(tr("L'invio delle segnalazioni non è ancora attivo."))
    try:
        r = requests.post(url, json=data, timeout=timeout, headers={"User-Agent": f"Helpix/{__version__}"})
    except requests.RequestException as exc:
        raise ReportError(tr("Il servizio di segnalazione non risponde ({exc}).").format(exc=type(exc).__name__))
    try:
        reply = r.json()
    except ValueError:
        reply = {}
    if r.status_code == 429:
        raise ReportError(tr("Troppe segnalazioni in poco tempo: riprova più tardi."))
    if r.status_code >= 400 or not reply.get("number"):
        raise ReportError(tr("Il servizio ha rifiutato la segnalazione ({code}: {msg}).").format(
            code=r.status_code, msg=str(reply.get("error") or "")[:200]))
    return int(reply["number"])


def save(data: dict, folder: Path | None = None) -> Path:
    """Salva il pacchetto come file Markdown (da inviare a mano)."""
    folder = folder or next((p for p in (Path.home() / "Desktop", Path.home() / "Scrivania",
                                         Path.home() / "Downloads") if p.is_dir()), Path.home())
    dest = folder / f"helpix-segnalazione-{time.strftime('%Y%m%d-%H%M%S')}.md"
    dest.write_text(f"# {data['title']}\n\nHelpix {data['version']} · {data['os']}\n\n{data['body']}\n",
                    encoding="utf-8")
    return dest
