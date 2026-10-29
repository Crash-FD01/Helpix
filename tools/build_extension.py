#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Costruisce l'estensione di Helpix per i browser Chromium (MV3) e per Firefox (MV2).

    python tools/build_extension.py          # helpix/data/extension/{chromium,firefox} + dist/*.zip

- chromium: Chrome, Chromium, Edge, Brave, Vivaldi, Opera. Il campo "key" fissa l'ID
  dell'estensione (kcnapjkchmgjacppmmajcddjoemeahdj), quello autorizzato dall'host nativo.
- firefox: Firefox e LibreWolf, ID helpix@crash-fd01.github.io.
- dist/: pacchetti da caricare sul Chrome Web Store (senza "key") e su addons.mozilla.org.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "extension" / "src"
OUT = ROOT / "helpix" / "data" / "extension"
DIST = ROOT / "dist"
ICONS = ROOT / "helpix" / "data" / "icons"
FIREFOX_ID = "helpix@crash-fd01.github.io"
SITES = ["https://chatgpt.com/*", "https://chat.openai.com/*", "https://claude.ai/*",
         "https://gemini.google.com/*", "https://copilot.microsoft.com/*", "https://chat.deepseek.com/*"]


def version() -> str:
    text = (ROOT / "helpix" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def icons() -> dict:
    return {str(s): f"icons/icon-{s}.png" for s in (16, 32, 48, 128)}


def common(ver: str) -> dict:
    return {
        "name": "__MSG_name__",
        "short_name": "Helpix",
        "description": "__MSG_description__",
        "version": ver,
        "default_locale": "en",
        "homepage_url": "https://github.com/Crash-FD01/Helpix",
        "icons": icons(),
        "content_scripts": [{"matches": SITES, "js": ["content.js"], "run_at": "document_idle"}],
    }


def chromium_manifest(ver: str, with_key: bool) -> dict:
    m = {"manifest_version": 3, **common(ver),
         "minimum_chrome_version": "110",
         "permissions": ["nativeMessaging", "storage", "scripting"],
         "host_permissions": SITES,
         "background": {"service_worker": "background.js"},
         "action": {"default_popup": "popup.html", "default_icon": icons(), "default_title": "Helpix"}}
    if with_key:
        m["key"] = (ROOT / "extension" / "chromium-public-key.txt").read_text().strip()
    return m


def firefox_manifest(ver: str) -> dict:
    return {"manifest_version": 2, **common(ver),
            "permissions": ["nativeMessaging", "storage", *SITES],
            "background": {"scripts": ["background.js"], "persistent": True},
            "browser_action": {"default_popup": "popup.html", "default_icon": icons(), "default_title": "Helpix"},
            "browser_specific_settings": {"gecko": {
                "id": FIREFOX_ID, "strict_min_version": "140.0",
                "data_collection_permissions": {"required": ["none"]}}}}


def build(target: Path, manifest: dict):
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    logo = base64.b64encode((ICONS / "helpix-64.png").read_bytes()).decode("ascii")
    for f in SRC.rglob("*"):
        if f.is_dir():
            continue
        dest = target / f.relative_to(SRC)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.name == "content.js":
            dest.write_text(f.read_text(encoding="utf-8").replace("__HELPIX_LOGO_B64__", logo), encoding="utf-8")
        else:
            shutil.copy2(f, dest)
    (target / "icons").mkdir(exist_ok=True)
    for size in (16, 32, 48, 64, 128):
        shutil.copy2(ICONS / f"helpix-{size}.png", target / "icons" / f"icon-{size}.png")
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pack(folder: Path, dest: Path, manifest: dict | None = None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                rel = f.relative_to(folder).as_posix()
                if rel == "manifest.json" and manifest is not None:
                    z.writestr(rel, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
                else:
                    z.write(f, rel)


def main() -> int:
    ver = version()
    build(OUT / "chromium", chromium_manifest(ver, with_key=True))
    build(OUT / "firefox", firefox_manifest(ver))
    pack(OUT / "chromium", DIST / f"helpix-extension-{ver}-chromium.zip", chromium_manifest(ver, with_key=False))
    pack(OUT / "firefox", DIST / f"helpix-extension-{ver}-firefox.zip")
    print(f"Estensione {ver}: {OUT / 'chromium'}, {OUT / 'firefox'}, pacchetti in {DIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
