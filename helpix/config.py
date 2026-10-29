# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Percorsi (XDG su Linux, AppData su Windows), impostazioni e archiviazione sicura delle chiavi API."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .system import APP_ID, config_dir, data_dir  # noqa: F401

log = logging.getLogger(__name__)

CONFIG_DIR = config_dir()
DATA_DIR = data_dir()
SESSIONS_DIR = DATA_DIR / "sessions"
SHOTS_DIR = DATA_DIR / "screenshots"
LOG_FILE = DATA_DIR / "helpix.log"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
FALLBACK_SECRETS = CONFIG_DIR / "secrets.json"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, SESSIONS_DIR, SHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for d in (CONFIG_DIR, DATA_DIR):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def write_private(path: Path, text: str) -> None:
    """Scrittura atomica con permessi 0600."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


DEFAULT_SETTINGS = {
    "engine": "web",              # web (account normale) | api (chiave API, avanzato)
    "web_site": "chatgpt",        # servizio web predefinito
    "auto_paste_output": True,    # motore web: incolla l'output dei comandi nella chat
    "tech_mode": False,           # mostra terminale e cartelle
    "theme": "auto",              # auto (segue il sistema) | light | dark
    "language": "auto",           # auto (lingua del sistema) | it | en
    "rounded_corners": True,      # finestra con angoli arrotondati (solo con la barra integrata)
    "system_titlebar": False,     # True = cornice del sistema invece della barra integrata
    "external_sites": ["gemini"],  # servizi aperti nel browser di sistema (Google blocca i browser integrati)
    "default_engine": None,       # motore che si apre all'avvio (None = l'ultimo usato)
    "default_site": None,         # servizio web predefinito (None = l'ultimo usato)
    "default_model": None,        # modello API predefinito per default_provider
    "default_provider": "anthropic",
    "models": {},            # provider -> ultimo modello usato
    "model_cache": {},       # provider -> elenco modelli scaricato dall'API
    "base_urls": {},         # provider -> indirizzo personalizzato (es. Ollama remoto)
    "skip_setup": False,     # avvia direttamente con l'agente predefinito
    "auto_continue": True,   # dopo un comando proposto dall'IA, rimanda l'output e continua
    "hide_on_screenshot": True,
    "always_on_top": False,
    "show_tree": True,
    "command_timeout": 120,
    "last_cwd": str(Path.home()),
}


class Settings:
    def __init__(self) -> None:
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    def load(self) -> None:
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("Impostazioni illeggibili (%s): uso i valori predefiniti", exc)

    def save(self) -> None:
        ensure_dirs()
        write_private(SETTINGS_FILE, json.dumps(self.data, indent=2, ensure_ascii=False))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()

    def start_engine(self) -> str:
        return self.data.get("default_engine") or self.data.get("engine") or "web"

    def start_site(self) -> str:
        return self.data.get("default_site") or self.data.get("web_site") or "chatgpt"

    def start_model(self, provider: str) -> str:
        if provider == self.data.get("default_provider") and self.data.get("default_model"):
            return self.data["default_model"]
        return self.model_for(provider)

    def model_for(self, provider: str) -> str:
        from .providers import PROVIDERS
        return self.data.get("models", {}).get(provider) or PROVIDERS[provider]["models"][0]

    def set_model(self, provider: str, model: str) -> None:
        self.data.setdefault("models", {})[provider] = model
        self.save()

    def base_url_for(self, provider: str):
        return (self.data.get("base_urls", {}).get(provider) or "").strip() or None

    def cached_models(self, provider: str):
        return self.data.get("model_cache", {}).get(provider)

    def cache_models(self, provider: str, models: list) -> None:
        self.data.setdefault("model_cache", {})[provider] = models
        self.save()


class SecretStore:
    """Chiavi API nel portachiavi di sistema (Secret Service: GNOME Keyring / KWallet).

    Se il portachiavi non è disponibile ripiega su un file 0600 nella cartella di
    configurazione e lo segnala nell'interfaccia.
    """

    SERVICE = "helpix"

    def __init__(self) -> None:
        self._keyring = None
        try:
            import keyring
            from keyring.backends import fail

            backend = keyring.get_keyring()
            name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
            if isinstance(backend, fail.Keyring) or "null" in name or "plaintext" in name:
                log.info("Nessun portachiavi utilizzabile (%s)", name)
            else:
                self._keyring = keyring
        except Exception as exc:  # noqa: BLE001 - keyring può fallire in molti modi
            log.info("keyring non disponibile: %s", exc)

    @property
    def secure(self) -> bool:
        return self._keyring is not None

    def _read_file(self) -> dict:
        try:
            data = json.loads(FALLBACK_SECRETS.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_file(self, data: dict) -> None:
        ensure_dirs()
        if data:
            write_private(FALLBACK_SECRETS, json.dumps(data))
        else:
            FALLBACK_SECRETS.unlink(missing_ok=True)

    def get(self, provider: str) -> str:
        if self._keyring:
            try:
                value = self._keyring.get_password(self.SERVICE, provider)
                if value:
                    return value
            except Exception as exc:  # noqa: BLE001
                log.warning("Lettura dal portachiavi fallita: %s", exc)
        return self._read_file().get(provider, "")

    def forget_all(self, providers) -> int:
        """Cancella tutte le chiavi API (disinstallazione con --purge). Restituisce quante ne ha tolte."""
        removed = 0
        for provider in providers:
            if self._keyring:
                try:
                    self._keyring.delete_password(self.SERVICE, provider)
                    removed += 1
                except Exception:  # noqa: BLE001 - chiave assente o portachiavi chiuso
                    pass
        data = self._read_file()
        if data:
            removed += len(data)
            self._write_file({})
        return removed

    def set(self, provider: str, value: str) -> None:
        value = value.strip()
        if self._keyring:
            try:
                self._keyring.set_password(self.SERVICE, provider, value)
                data = self._read_file()
                if provider in data:
                    del data[provider]
                    self._write_file(data)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("Scrittura nel portachiavi fallita, uso il file: %s", exc)
        data = self._read_file()
        data[provider] = value
        self._write_file(data)
