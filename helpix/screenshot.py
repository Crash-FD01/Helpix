# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cattura dello schermo su X11 e Wayland.

Ordine dei tentativi:
1. X11 + schermo intero: cattura diretta con Qt (istantanea, nessuna dipendenza).
2. xdg-desktop-portal (standard su GNOME, KDE e wlroots, funziona su Wayland).
3. Strumenti da riga di comando, se installati: grim/slurp, spectacle,
   gnome-screenshot, flameshot, maim, scrot, import.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import SHOTS_DIR, ensure_dirs
from .i18n import tr

PORTAL_HELPER = Path(__file__).with_name("portal_screenshot.py")
MAX_SIDE = 2048            # lato massimo inviato all'IA
MAX_BYTES = 3_500_000      # oltre questa dimensione si passa a JPEG

FULL_TOOLS = [
    (("grim",), "grim {out}"),
    (("spectacle",), "spectacle -b -n -f -o {out}"),
    (("gnome-screenshot",), "gnome-screenshot -f {out}"),
    (("flameshot",), "flameshot full -r > {out}"),
    (("maim",), "maim {out}"),
    (("scrot",), "scrot -o {out}"),
    (("import",), "import -window root {out}"),
]
AREA_TOOLS = [
    (("grim", "slurp"), 'grim -g "$(slurp)" {out}'),
    (("spectacle",), "spectacle -b -n -r -o {out}"),
    (("gnome-screenshot",), "gnome-screenshot -a -f {out}"),
    (("flameshot",), "flameshot gui -r > {out}"),
    (("maim",), "maim -s {out}"),
    (("scrot",), "scrot -s -o {out}"),
]


class ScreenshotError(Exception):
    pass


class ScreenshotCancelled(ScreenshotError):
    pass


def is_x11() -> bool:
    stype = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if stype:
        return stype == "x11"
    return bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")


def new_shot_path(prefix: str = "shot", ext: str = "png") -> Path:
    ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = SHOTS_DIR / f"{prefix}-{stamp}.{ext}"
    n = 1
    while path.exists():
        path = SHOTS_DIR / f"{prefix}-{stamp}-{n}.{ext}"
        n += 1
    return path


def _portal(area: bool) -> str | None:
    from .sysdeps import system_pythons
    pythons = [*system_pythons(), sys.executable]
    errors = []
    for py in dict.fromkeys(pythons):
        if not os.path.exists(py):
            continue
        try:
            r = subprocess.run([py, "-I", str(PORTAL_HELPER), "--interactive" if area else "--full"],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
            continue
        if r.returncode == 0 and r.stdout.strip():
            uri = r.stdout.strip().splitlines()[-1]
            return unquote(urlparse(uri).path) if uri.startswith("file://") else uri
        if r.returncode == 2:
            raise ScreenshotCancelled("annullato")
        errors.append(r.stderr.strip()[-300:])
        if "PyGObject" not in r.stderr:  # il portal ha risposto: inutile riprovare con altri python
            break
    return None


def capture_external(area: bool = False) -> str:
    """Bloccante: va eseguita in un thread. Restituisce il percorso del PNG."""
    path = _portal(area)
    if path and os.path.exists(path):
        dest = new_shot_path()
        shutil.copyfile(path, dest)
        return str(dest)
    for needs, template in (AREA_TOOLS if area else FULL_TOOLS):
        if not all(shutil.which(n) for n in needs):
            continue
        dest = new_shot_path()
        try:
            subprocess.run(["bash", "-c", template.format(out=f"'{dest}'")],
                           capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if dest.exists() and dest.stat().st_size > 0:
            return str(dest)
        dest.unlink(missing_ok=True)
        if area:  # l'utente probabilmente ha annullato la selezione
            raise ScreenshotCancelled("annullato")
    raise ScreenshotError(
        tr("Nessun metodo di cattura disponibile.\n"
        "Su Wayland serve xdg-desktop-portal (già presente su GNOME e KDE); "
        "in alternativa installa uno tra grim+slurp, spectacle, gnome-screenshot o flameshot."))


def is_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def capture_area_native() -> str:
    """Selezione di un'area con lo strumento del desktop (Wayland). Bloccante: va in un thread.

    Su KDE usa Spectacle in modalità area (selezione nativa su tutti i monitor, senza dialoghi);
    altrove il portal interattivo (su GNOME è la sua interfaccia di cattura), poi gli strumenti
    da riga di comando.
    """
    if is_kde() and shutil.which("spectacle"):
        dest = new_shot_path()
        try:
            subprocess.run(["spectacle", "--background", "--nonotify", "--region", "--output", str(dest)],
                           capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScreenshotError(str(exc)) from exc
        if dest.exists() and dest.stat().st_size > 0:
            return str(dest)
        dest.unlink(missing_ok=True)
        raise ScreenshotCancelled("annullato")
    return capture_external(area=True)


def capture_full_external() -> str:
    """Schermo intero senza dialoghi (portal non interattivo o strumenti CLI). Bloccante."""
    return capture_external(area=False)


def qt_grab_full_image():
    """Cattura immediata con Qt di tutto il desktop virtuale (solo X11, thread della GUI).

    Restituisce (QImage, geometria virtuale in coordinate logiche).
    """
    from PySide6.QtGui import QGuiApplication

    screens = QGuiApplication.screens()
    if not screens:
        raise ScreenshotError(tr("Nessuno schermo rilevato"))
    geo = screens[0].virtualGeometry()
    pix = screens[0].grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
    if pix.isNull():
        raise ScreenshotError(tr("Cattura Qt fallita"))
    return pix.toImage(), geo


def qt_grab_full() -> str:
    image, _ = qt_grab_full_image()
    dest = new_shot_path()
    image.save(str(dest), "PNG")
    return str(dest)


def save_image(image) -> str:
    dest = new_shot_path()
    if not image.save(str(dest), "PNG"):
        raise ScreenshotError(tr("Impossibile salvare lo screenshot"))
    return str(dest)


def _run(argv: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def x11_window_rects() -> list[tuple[tuple[int, int, int, int], str]]:
    """Finestre visibili su X11, dalla più in alto alla più in basso, in pixel del root.

    Usa xprop/xwininfo (pacchetto x11-utils / xorg-x11-utils). Lista vuota se non disponibili.
    """
    if not (is_x11() and shutil.which("xprop") and shutil.which("xwininfo")):
        return []
    out = _run(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"])
    ids = re.findall(r"0x[0-9a-fA-F]+", out.split("#", 1)[-1]) if "#" in out else []
    result = []
    for wid in reversed(ids):  # la lista è dal basso verso l'alto
        props = _run(["xprop", "-id", wid, "_NET_WM_STATE", "_NET_WM_WINDOW_TYPE", "_NET_WM_NAME",
                      "_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS"])
        if "_NET_WM_STATE_HIDDEN" in props or re.search(r"_NET_WM_WINDOW_TYPE_(DOCK|DESKTOP)", props):
            continue
        info = _run(["xwininfo", "-id", wid])
        if "IsViewable" not in info:
            continue
        nums = {k: int(v) for k, v in re.findall(
            r"(Absolute upper-left X|Absolute upper-left Y|Width|Height):\s+(-?\d+)", info)}
        if len(nums) < 4:
            continue
        x, y = nums["Absolute upper-left X"], nums["Absolute upper-left Y"]
        w, h = nums["Width"], nums["Height"]
        gtk = re.search(r"_GTK_FRAME_EXTENTS\(CARDINAL\) = (\d+), (\d+), (\d+), (\d+)", props)
        net = re.search(r"_NET_FRAME_EXTENTS\(CARDINAL\) = (\d+), (\d+), (\d+), (\d+)", props)
        if gtk:   # decorazioni lato client: togli l'ombra
            left, right, top, bottom = map(int, gtk.groups())
            x, y, w, h = x + left, y + top, w - left - right, h - top - bottom
        elif net:  # decorazioni del window manager: includi la cornice
            left, right, top, bottom = map(int, net.groups())
            x, y, w, h = x - left, y - top, w + left + right, h + top + bottom
        name = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', props)
        if w > 20 and h > 20:
            result.append(((x, y, w, h), name.group(1) if name else ""))
    return result


def normalize_image(src: str) -> str:
    """Ridimensiona e converte l'immagine in un formato accettato da tutti i fornitori."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    img = QImage(src)
    if img.isNull():
        raise ScreenshotError(tr("Immagine non leggibile: {src}").format(src=src))
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    src_path = Path(src)
    if src_path.parent == SHOTS_DIR and src_path.suffix == ".png":
        dest = src_path
    else:
        dest = new_shot_path("img")
    img.save(str(dest), "PNG")
    if dest.stat().st_size > MAX_BYTES:
        jpg = dest.with_suffix(".jpg")
        img.convertToFormat(QImage.Format.Format_RGB888).save(str(jpg), "JPEG", 85)
        dest.unlink(missing_ok=True)
        dest = jpg
    return str(dest)
