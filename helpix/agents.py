# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agenti a riga di comando che Helpix apre nel suo terminale: Claude Code, Codex, Gemini CLI.

Ognuno si collega con il proprio account (accesso nel browser di sistema, quindi anche con
Google) e legge le istruzioni da un file nella cartella di lavoro: CLAUDE.md, AGENTS.md,
GEMINI.md. Helpix prepara quella cartella con le istruzioni, il task da continuare e gli
screenshot, e legge il riepilogo che l'agente scrive in HELPIX-SUMMARY.md.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .config import DATA_DIR
from .i18n import current, tr
from .prompts import system_info
from .system import IS_WINDOWS
from .task import SUMMARY_MARKER

WORKSPACE = DATA_DIR / "agent"
SUMMARY_FILE = "HELPIX-SUMMARY.md"
TASK_FILE = "HELPIX-TASK.md"

AGENTS: dict[str, dict] = {
    "claude-code": {
        "label": "Claude Code", "icon": "claude", "cmd": "claude", "context": "CLAUDE.md",
        "who": "Anthropic", "plan": tr("Serve un abbonamento Claude Pro o Max (o un account Console)"),
        "install": "curl -fsSL https://claude.ai/install.sh | bash",
        "needs": ["curl", "bash"],  # se mancano, li installa prima il gestore pacchetti (sysdeps)
        "docs": "https://code.claude.com/docs/en/setup",
        "install_win": "irm https://claude.ai/install.ps1 | iex",  # in %USERPROFILE%\\.local\\bin, senza amministratore
        "needs_win": [],
        "prompt_args": lambda p: [p],
        # modelli (alias ufficiali) ed effort: --model / --effort all'avvio, /model e /effort durante la sessione
        "models": ["default", "opus", "sonnet", "haiku", "best"],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "model_args": lambda m: ["--model", m],
        "effort_args": lambda e: ["--effort", e],
        "live_model": lambda m: f"/model {m}",
        "live_effort": lambda e: f"/effort {e}",
    },
    "codex": {
        "label": "Codex", "icon": "chatgpt", "cmd": "codex", "context": "AGENTS.md",
        "who": "OpenAI", "plan": tr("Accesso con l'account ChatGPT (Plus, Pro, Business…) o con una chiave API"),
        "install": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
        "needs": ["curl"],
        "docs": "https://github.com/openai/codex",
        "install_win": "irm https://chatgpt.com/codex/install.ps1 | iex",
        "needs_win": [],
        "prompt_args": lambda p: [p],
        "models": ["default", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"],
        "efforts": ["minimal", "low", "medium", "high", "xhigh"],
        "model_args": lambda m: ["--model", m],
        "effort_args": lambda e: ["-c", f'model_reasoning_effort="{e}"'],
    },
    "gemini-cli": {
        "label": "Gemini CLI", "icon": "gemini", "cmd": "gemini", "context": "GEMINI.md",
        "who": "Google", "plan": tr("Accesso con l'account Google; serve Node.js (npm) per installarlo"),
        "install": 'npm install -g --prefix "$HOME/.local" @google/gemini-cli',
        "needs": ["npm"],
        # Gemini CLI richiede Node.js 20 o superiore; alcune distro ne hanno uno più vecchio
        "precheck": "node -e 'process.exit(+process.versions.node.split(\".\")[0] < 20)' || "
                    "echo 'Attenzione: Gemini CLI richiede Node.js 20 o superiore; questa distro ne ha uno più "
                    "vecchio (aggiornalo, per esempio da nodejs.org o con il modulo nodejs:20).'",
        "docs": "https://github.com/google-gemini/gemini-cli",
        "install_win": "npm install -g @google/gemini-cli",
        "needs_win": ["npm"],  # Node.js: se manca lo installa winget (OpenJS.NodeJS.LTS)
        "precheck_win": "if ([int](node -p 'process.versions.node.split(\".\")[0]') -lt 20) { Write-Warning "
                        "'Gemini CLI richiede Node.js 20 o superiore: aggiornalo con winget upgrade OpenJS.NodeJS.LTS' }",
        "prompt_args": lambda p: ["-i", p],
        "models": ["default", "gemini-2.5-pro", "gemini-2.5-flash"],
        "efforts": [],
        "model_args": lambda m: ["--model", m],
    },
}

# dove finiscono di solito i programmi installati senza root
_EXTRA_PATHS = ["~/.local/bin", "~/.npm-global/bin", "~/bin", "~/.local/share/pnpm", "/usr/local/bin"]
_EXTRA_PATHS_WIN = ["~/.local/bin", "%APPDATA%/npm", "%LOCALAPPDATA%/Programs/nodejs", "%ProgramFiles%/nodejs",
                    "%LOCALAPPDATA%/Helpix/agents/codex"]  # Codex installato da Helpix senza giunzioni


def _registry_path() -> list[str]:
    """PATH di utente e sistema letti dal registro: dopo un'installazione Windows aggiorna solo quelli, e Helpix
    (già aperto) li vede solo così, senza riavviarsi."""
    try:
        import winreg
    except ImportError:
        return []
    out: list[str] = []
    for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                value, _ = winreg.QueryValueEx(k, "Path")
            out += [os.path.expandvars(p) for p in str(value).split(";") if p]
        except OSError:
            continue
    return out


def search_path() -> str:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if IS_WINDOWS:
        extra = [os.path.expandvars(os.path.expanduser(p)) for p in _EXTRA_PATHS_WIN] + _registry_path()
    else:
        extra = [os.path.expanduser(p) for p in _EXTRA_PATHS]
    return os.pathsep.join(dict.fromkeys(p for p in parts + extra if p))


def install_command(key: str) -> str:
    a = AGENTS[key]
    return a["install_win"] if IS_WINDOWS else a["install"]


def install_log(key: str) -> Path:
    """Registro dell'ultima installazione dell'agente (Windows: %LOCALAPPDATA%\\Helpix\\logs)."""
    return DATA_DIR / "logs" / f"install-{key}.log"


def _ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# Lo script ufficiale di Codex legge [RuntimeInformation]::OSArchitecture, che con Windows PowerShell 5.1 non
# esiste: in modalità strict si ferma con PropertyNotFoundStrict (issue #6). Lì Helpix scarica lo script e mette
# al suo posto l'architettura letta dalle variabili di Windows; con PowerShell 7 lo esegue così com'è.
_OSARCH = r"\[(?:System\.)?(?:Runtime\.InteropServices\.)?RuntimeInformation\]::OSArchitecture"
_IRM_IEX = re.compile(r"^irm (\S+) \| iex$")


# Codex: lo script ufficiale crea giunzioni (junction) nella cartella dell'utente. Dove Windows applica RedirectionGuard
# (Windows 11 recenti, criteri di sicurezza aziendali) non le può attraversare e si ferma con
# ERROR_UNTRUSTED_MOUNT_POINT (448). Allora Helpix installa lo stesso pacchetto ufficiale della release GitHub di
# Codex in una cartella normale, senza giunzioni: codex.exe è un collegamento fisso (hard link) al programma.
CODEX_ZIP_URL = "https://github.com/openai/codex/releases/latest/download/codex-{arch}-pc-windows-msvc.exe.zip"
_CODEX_FALLBACK = r"""
function Test-HelpixUntrustedMount($err) {
  $e = $err.Exception
  while ($e) {
    if ($e.HResult -eq -2147023424 -or $e.Message -match 'untrusted mount point|punto di montaggio non attendibile') {
      return $true
    }
    $e = $e.InnerException
  }
  return $false
}
function Install-HelpixCodexPackage {
  $arch = if ("$env:PROCESSOR_ARCHITEW6432 $env:PROCESSOR_ARCHITECTURE" -match 'ARM64') { 'aarch64' } else { 'x86_64' }
  $url = %(url)s.Replace('{arch}', $arch)
  $dest = Join-Path $env:LOCALAPPDATA 'Helpix\agents\codex'
  $zip = Join-Path ([IO.Path]::GetTempPath()) ('helpix-codex-' + $arch + '.zip')
  Write-Host ''
  Write-Host (%(note)s.Replace('{dir}', $dest)) -ForegroundColor Yellow
  Write-Host "> $url"
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Expand-Archive -Path $zip -DestinationPath $dest -Force
  Remove-Item -Force $zip
  $pkg = Get-Content -Raw (Join-Path $dest 'codex-package.json') | ConvertFrom-Json
  $exe = Join-Path $dest 'codex.exe'
  New-Item -ItemType HardLink -Path $exe -Target (Join-Path $dest $pkg.entrypoint) | Out-Null
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not (($userPath -split ';') -contains $dest)) {
    [Environment]::SetEnvironmentVariable('Path', ((($userPath -split ';') + $dest | Where-Object { $_ }) -join ';'), 'User')
  }
  $env:Path = "$dest;$env:Path"
  Write-Host (%(done)s.Replace('{version}', [string]$pkg.version))
}
"""


def _codex_fallback() -> str:
    return _CODEX_FALLBACK % {
        "url": _ps(CODEX_ZIP_URL),
        "note": _ps(tr("Lo script ufficiale non può usare le giunzioni (junction) su questo PC: Windows le blocca "
                       "(RedirectionGuard). Installo lo stesso pacchetto ufficiale di Codex, dalla sua release su "
                       "GitHub, in una cartella normale: {dir}")),
        "done": _ps(tr("Codex {version} installato.")),
    }


def windows_install_script(key: str, steps: list[str] | None = None) -> str:
    """Script PowerShell per installare l'agente su Windows.

    Esegue i passi preliminari e il comando ufficiale; se qualcosa va storto mostra l'errore con la riga e la
    traccia, esce con codice 1 e lascia tutto nel registro install_log(key).
    """
    cmd = install_command(key)
    m = _IRM_IEX.match(cmd)
    if m:
        url = _ps(m.group(1))
        note = _ps(tr("(Windows PowerShell 5.1: uso l'architettura del PC letta da Windows, {arch}, perché lo script "
                      "ufficiale qui non riesce a leggerla)"))
        install = (
            "if ($PSVersionTable.PSVersion.Major -lt 6) {\n"
            "  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor "
            "[Net.SecurityProtocolType]::Tls12\n"
            "  $helpixArch = $(if (\"$env:PROCESSOR_ARCHITEW6432 $env:PROCESSOR_ARCHITECTURE\" -match 'ARM64') "
            "{ 'Arm64' } elseif (\"$env:PROCESSOR_ARCHITEW6432 $env:PROCESSOR_ARCHITECTURE\" -match 'AMD64') "
            "{ 'X64' } else { 'X86' })\n"
            f"  $helpixScript = Invoke-RestMethod {url}\n"
            f"  $helpixFixed = $helpixScript -replace {_ps(_OSARCH)}, '$$helpixArch'\n"
            "  if ($helpixFixed -ne $helpixScript) {\n"
            f"    Write-Host ({note}.Replace('{{arch}}', $helpixArch))\n"
            "  }\n"
            "  Invoke-Expression $helpixFixed\n"
            f"}} else {{ {cmd} }}"
        )
    else:
        install = cmd + f"\nif ($LASTEXITCODE) {{ throw ({_ps(tr('codice di uscita {rc}'))}.Replace('{{rc}}', $LASTEXITCODE)) }}"
    prelude = ""
    if key == "codex":
        prelude = _codex_fallback()
        install = ("try {\n" + install + "\n} catch {\n"
                   "  if (-not (Test-HelpixUntrustedMount $_)) { throw }\n"
                   f"  Write-Host ({_ps(tr('Errore:'))} + ' ' + $_.Exception.Message) -ForegroundColor DarkGray\n"
                   "  Install-HelpixCodexPackage\n"
                   "}")
    log = _ps(str(install_log(key)))
    body = "\n".join([prelude, *(steps or []), install])
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        f"$helpixLog = {log}\n"
        "try { New-Item -ItemType Directory -Force -Path (Split-Path $helpixLog) | Out-Null; "
        "Start-Transcript -LiteralPath $helpixLog -Force | Out-Null } catch {}\n"
        "Write-Host (\"PowerShell \" + $PSVersionTable.PSVersion.ToString() + \" (\" + $PSHOME + \")\")\n"
        "try {\n" + body + "\n} catch {\n"
        "  Write-Host ''\n"
        f"  Write-Host ({_ps(tr('Errore:'))} + ' ' + $_.Exception.Message) -ForegroundColor Red\n"
        "  if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) { Write-Host $_.InvocationInfo.PositionMessage }\n"
        "  if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }\n"
        "  try { Stop-Transcript | Out-Null } catch {}\n"
        "  exit 1\n"
        "}\n"
        "try { Stop-Transcript | Out-Null } catch {}\n"
        "exit 0\n"
    )


def windows_install_argv(key: str, steps: list[str] | None = None, exe: str | None = None) -> list[str]:
    """Riga di comando per installare l'agente su Windows: lo script va in un file .ps1 ed è eseguito con -File.

    Niente -EncodedCommand né -ExecutionPolicy Bypass: sono proprio i segnali che gli antivirus usano per bloccare
    PowerShell. Un file .ps1 creato in locale è ammesso dalla politica RemoteSigned (predefinita su Windows)."""
    from .winshell import powershell
    path = DATA_DIR / "run" / f"install-{key}.ps1"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(windows_install_script(key, steps), encoding="utf-8-sig")  # con BOM: lo legge bene anche la 5.1
    return [exe or powershell(), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(path)]


def needs(key: str) -> list[str]:
    a = AGENTS[key]
    return list(a.get("needs_win", []) if IS_WINDOWS else a.get("needs", []))


def precheck(key: str) -> str | None:
    a = AGENTS[key]
    return a.get("precheck_win") if IS_WINDOWS else a.get("precheck")


def find_cli(key: str) -> str | None:
    return shutil.which(AGENTS[key]["cmd"], path=search_path())


def workspace() -> Path:
    for sub in ("", "screenshots"):
        (WORKSPACE / sub).mkdir(parents=True, exist_ok=True)
    return WORKSPACE


_TEMPLATE = {
    "it": """# Helpix

Sei l'assistente di Helpix: aiuti l'utente a risolvere problemi o a portare avanti lavori sul suo PC.
L'utente potrebbe non essere esperto: scrivi in italiano, in modo semplice e con passi chiari.

## Il PC
{pc}

## Regole
- Prima di eseguire comandi che modificano il sistema (installazioni, file di configurazione, servizi, sudo,
  cancellazioni) spiega cosa fanno e chiedi conferma.
- Gli screenshot che l'utente ti manda sono nella cartella `screenshots/`; le diagnosi nei file `diagnosi-*.txt`.
  Quando l'utente ti indica un file, leggilo.
- Se c'è il file `{task}`, contiene un lavoro iniziato con un'altra IA: leggilo e riparti da lì.

## Riepilogo per Helpix
Quando l'utente ti chiede il riepilogo per Helpix, scrivi il file `{summary}` (sovrascrivilo se esiste) con
esattamente questo formato, compilando ogni voce con nomi, valori, file, errori e comandi rilevanti:

```
{marker}
Obiettivo:
Contesto:
Cosa è stato fatto (comandi, risultati, decisioni):
Stato attuale:
Prossimi passi:
```
""",
    "en": """# Helpix

You are Helpix's assistant: you help the user fix problems or carry on work on their PC.
The user may not be an expert: write in English, simply, with clear steps.

## The PC
{pc}

## Rules
- Before running commands that change the system (installs, configuration files, services, sudo, deletions),
  explain what they do and ask for confirmation.
- Screenshots the user sends you are in the `screenshots/` folder; diagnostics in `diagnosi-*.txt` files.
  When the user points you to a file, read it.
- If the file `{task}` exists, it holds work started with another AI: read it and pick up from there.

## Summary for Helpix
When the user asks for the summary for Helpix, write the file `{summary}` (overwrite it if it exists) in exactly
this format, filling every item with relevant names, values, files, errors and commands:

```
{marker}
Goal:
Context:
What was done (commands, results, decisions):
Current status:
Next steps:
```
""",
}


def _pc_lines() -> str:
    info, en = system_info(), current() == "en"
    if IS_WINDOWS:
        return ("- System: {distro} ({arch})\n- Shell: {shell}\n- Package managers: {pkg}" if en else
                "- Sistema: {distro} ({arch})\n- Shell: {shell}\n- Gestori di pacchetti: {pkg}").format(**info)
    return ("- System: {distro} ({arch}), kernel {kernel}\n- Desktop: {desktop} ({session} session)\n"
            "- Package manager: {pkg}; other formats: {extra}" if en else
            "- Sistema: {distro} ({arch}), kernel {kernel}\n- Desktop: {desktop} (sessione {session})\n"
            "- Gestore pacchetti: {pkg}; altri formati: {extra}").format(**info)


def write_context(key: str, task_text: str | None = None) -> Path:
    """Prepara la cartella di lavoro: istruzioni per l'agente ed eventuale task da continuare."""
    ws = workspace()
    text = _TEMPLATE.get(current(), _TEMPLATE["it"]).format(
        task=TASK_FILE, summary=SUMMARY_FILE, marker=SUMMARY_MARKER, pc=_pc_lines())
    from . import privacy
    text = privacy.filter_paste(text, notify=False)  # scudo acceso: l'agente non riceve utente e nome del PC
    for agent in AGENTS.values():  # tutti e tre: si può cambiare agente nella stessa cartella
        (ws / agent["context"]).write_text(text, encoding="utf-8")
    task_path = ws / TASK_FILE
    if task_text is not None:
        task_path.write_text(task_text + "\n", encoding="utf-8")
    return ws


def clear_task() -> None:
    (workspace() / TASK_FILE).unlink(missing_ok=True)


def save_screenshot(path: str) -> Path:
    dest = workspace() / "screenshots" / Path(path).name
    if Path(path).resolve() != dest.resolve():
        shutil.copyfile(path, dest)
    return dest


def save_diagnostics(text: str) -> Path:
    from datetime import datetime
    dest = workspace() / f"diagnosi-{datetime.now():%Y%m%d-%H%M%S}.txt"
    dest.write_text(text, encoding="utf-8")
    return dest


def summary_request() -> str:
    return tr("Scrivi il riepilogo per Helpix nel file {file}, nel formato indicato nelle istruzioni.").format(
        file=SUMMARY_FILE)


def read_summary() -> str | None:
    """Il riepilogo scritto dall'agente, solo se completo (le voci non sono tutte vuote)."""
    path = workspace() / SUMMARY_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if SUMMARY_MARKER not in text:
        return None
    body = text[text.index(SUMMARY_MARKER) + len(SUMMARY_MARKER):].split("```")[0].strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    filled = [ln for ln in lines if not re.match(r"^[^:]{2,80}:$", ln)]
    return body if len(filled) >= 2 else None


def reset_summary() -> None:
    (workspace() / SUMMARY_FILE).unlink(missing_ok=True)


def choice_args(key: str, model: str | None, effort: str | None) -> list[str]:
    """Argomenti di avvio per il modello e l'effort scelti («default» e «auto» = quelli dell'agente)."""
    a = AGENTS[key]
    out: list[str] = []
    if model and model != "default" and "model_args" in a:
        out += a["model_args"](model)
    if effort and effort != "auto" and effort in a.get("efforts", []) and "effort_args" in a:
        out += a["effort_args"](effort)
    return out
