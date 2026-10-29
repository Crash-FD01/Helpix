# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Connettori verso i fornitori di IA.

Due soli protocolli coprono tutti i fornitori supportati:
- Anthropic Messages API (Claude)
- OpenAI Chat Completions (OpenAI, Gemini via endpoint compatibile, DeepSeek, Ollama)

I messaggi arrivano in formato neutro ({role, text, images}) dalla sessione,
così si può cambiare fornitore a metà conversazione senza perdere il contesto.
"""
from __future__ import annotations

import base64
import mimetypes

import requests
from .i18n import tr

PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "needs_key": True,
        "vision": True,
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
    },
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "needs_key": True,
        "vision": True,
        "key_url": "https://platform.openai.com/api-keys",
        "models": ["gpt-5", "gpt-5-mini"],
        "efforts": ["minimal", "low", "medium", "high"],
    },
    "gemini": {
        "label": "Gemini (Google)",
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "needs_key": True,
        "vision": True,
        "key_url": "https://aistudio.google.com/apikey",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
        "efforts": ["low", "medium", "high"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "kind": "openai",
        "base_url": "https://api.deepseek.com",
        "needs_key": True,
        "vision": False,
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "efforts": [],
    },
    "ollama": {
        "label": tr("Ollama (locale)"),
        "kind": "openai",
        "base_url": "http://localhost:11434/v1",
        "needs_key": False,
        "vision": True,
        "key_url": "https://ollama.com/download",
        "models": ["llama3.2-vision", "qwen2.5vl"],
        "efforts": [],
    },
}

TIMEOUT = (10, 240)  # connessione, lettura
SUPPORTED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
_SKIP_MODEL_WORDS = (
    "embed", "whisper", "tts", "dall-e", "davinci", "babbage", "moderation",
    "audio", "realtime", "transcribe", "image", "aqa", "imagen", "veo", "search",
)


class ProviderError(Exception):
    pass


def _b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _mime(path: str) -> str:
    mime = mimetypes.guess_type(path)[0]
    return mime if mime in SUPPORTED_IMAGE_TYPES else "image/png"


def to_anthropic(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = "assistant" if m["role"] == "assistant" else "user"
        blocks = []
        if role == "user":
            for p in m.get("images", []):
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": _mime(p), "data": _b64(p)}})
        text = m.get("text", "")
        if text.strip():
            blocks.append({"type": "text", "text": text})
        if not blocks:
            continue
        if out and out[-1]["role"] == role:  # l'API vuole ruoli alternati
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def to_openai(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = "assistant" if m["role"] == "assistant" else "user"
        text = m.get("text", "")
        images = m.get("images", []) if role == "user" else []
        if images:
            content = [{"type": "text", "text": text or tr("Screenshot allegato.")}]
            content += [{"type": "image_url",
                         "image_url": {"url": f"data:{_mime(p)};base64,{_b64(p)}"}} for p in images]
        else:
            if not text.strip():
                continue
            content = text
        out.append({"role": role, "content": content})
    return out


def _base(pid: str, base_url: str | None) -> str:
    return (base_url or PROVIDERS[pid]["base_url"]).rstrip("/")


def _headers(pid: str, key: str) -> dict:
    if PROVIDERS[pid]["kind"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def build_request(pid: str, model: str, system: str, messages: list[dict],
                  base_url: str | None = None, effort: str | None = None) -> tuple[str, dict]:
    """effort: livello di ragionamento (None o «auto» = quello predefinito del modello)."""
    base = _base(pid, base_url)
    effort = effort if effort in PROVIDERS[pid].get("efforts", []) else None
    if PROVIDERS[pid]["kind"] == "anthropic":
        payload = {
            "model": model, "max_tokens": 8192, "system": system,
            "messages": to_anthropic(messages),
        }
        if effort:  # output_config.effort; con più ragionamento serve più spazio per la risposta
            payload["output_config"] = {"effort": effort}
            payload["max_tokens"] = {"high": 32000, "xhigh": 64000, "max": 64000}.get(effort, 8192)
        return f"{base}/v1/messages", payload
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + to_openai(messages),
    }
    if effort:
        payload["reasoning_effort"] = effort
    return f"{base}/chat/completions", payload


_HINTS = {
    401: tr("Chiave API non valida o scaduta."),
    403: tr("Accesso negato: verifica permessi e credito dell'account."),
    404: tr("Modello o indirizzo non trovato: controlla il nome del modello."),
    413: tr("Richiesta troppo grande: prova con meno screenshot."),
    429: tr("Troppe richieste o credito esaurito: riprova tra poco."),
}


def _json_or_raise(resp: requests.Response) -> dict:
    if resp.status_code < 400:
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(tr("Risposta non valida dal server.")) from exc
    msg = resp.text[:500]
    try:
        data = resp.json()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = err.get("message") or msg
        elif isinstance(err, str):
            msg = err
    except ValueError:
        pass
    hint = _HINTS.get(resp.status_code)
    raise ProviderError(f"HTTP {resp.status_code}: {msg}" + (f"\n{hint}" if hint else ""))


def parse_response(pid: str, data: dict) -> str:
    if PROVIDERS[pid]["kind"] == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if data.get("stop_reason") == "max_tokens":
            text += tr("\n\n_(Risposta troncata: raggiunto il limite di lunghezza.)_")
        return text.strip()
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(tr("Il modello ha restituito una risposta vuota."))
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if choices[0].get("finish_reason") == "length":
        content += tr("\n\n_(Risposta troncata: raggiunto il limite di lunghezza.)_")
    return content.strip()


def chat(pid: str, model: str, api_key: str, system: str, messages: list[dict],
         base_url: str | None = None, effort: str | None = None) -> str:
    url, payload = build_request(pid, model, system, messages, base_url, effort)
    try:
        resp = requests.post(url, headers=_headers(pid, api_key), json=payload, timeout=TIMEOUT)
    except requests.exceptions.Timeout as exc:
        raise ProviderError(tr("Il server non ha risposto in tempo. Riprova.")) from exc
    except requests.exceptions.RequestException as exc:
        raise ProviderError(tr("Impossibile contattare {host}: {exc}").format(host=url.split('/')[2], exc=exc)) from exc
    return parse_response(pid, _json_or_raise(resp))


def list_models(pid: str, api_key: str, base_url: str | None = None) -> list[str]:
    base = _base(pid, base_url)
    anthropic = PROVIDERS[pid]["kind"] == "anthropic"
    url = f"{base}/v1/models?limit=1000" if anthropic else f"{base}/models"
    try:
        resp = requests.get(url, headers=_headers(pid, api_key), timeout=(10, 30))
    except requests.exceptions.RequestException as exc:
        raise ProviderError(tr("Impossibile contattare {host}: {exc}").format(host=url.split('/')[2], exc=exc)) from exc
    data = _json_or_raise(resp)
    ids: list[str] = []
    for item in data.get("data", []) or data.get("models", []):
        mid = item.get("id") or item.get("name") or ""
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        if not mid or mid in ids:
            continue
        if not anthropic and any(w in mid.lower() for w in _SKIP_MODEL_WORDS):
            continue
        ids.append(mid)
    return ids if anthropic else sorted(ids)
