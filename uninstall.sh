#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
# Rimuove Helpix. Le sessioni e le impostazioni restano, a meno di --purge.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
PY="$DATA/helpix/venv/bin/python"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

if [[ -x "$PY" ]]; then
    # la scorciatoia Ctrl+Alt+H messa da Helpix nelle impostazioni del desktop (GNOME, Cinnamon, MATE, Xfce,
    # COSMIC, KDE): dopo la disinstallazione punterebbe a un comando che non c'è più
    "$PY" -m helpix.shortcut_setup remove || true
    "$PY" -m helpix.native_install --uninstall >/dev/null 2>&1 || true
    if [[ $PURGE == 1 ]]; then
        "$PY" -c 'from helpix.config import SecretStore; from helpix.providers import PROVIDERS
n = SecretStore().forget_all(PROVIDERS); print(f"Chiavi API cancellate dal portachiavi: {n}")' || true
    fi
fi
# Helpix e la finestra rapida, se sono aperti (solo i processi di questa installazione)
pkill -u "$(id -u)" -f "$DATA/helpix/venv/bin/" 2>/dev/null || true

rm -rf "$DATA/helpix/venv" "$DATA/helpix/bridge"
rm -f "$HOME/.local/bin/helpix" "$DATA/applications/helpix.desktop" "$DATA/applications/helpix-quick.desktop"
rm -f "$DATA/metainfo/io.github.crash_fd01.helpix.metainfo.xml"
rm -f "$DATA"/icons/hicolor/*/apps/helpix.png
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
if [[ $PURGE == 1 ]]; then
    rm -rf "$DATA/helpix" "$CONF/helpix"  # include i login salvati del browser integrato
    echo "Rimossi anche sessioni, screenshot, impostazioni e login salvati."
fi
if [[ -f /usr/share/polkit-1/actions/io.github.crash_fd01.helpix.unlock.policy ]]; then
    echo "Per rimuovere anche la regola di sistema dello sblocco:"
    echo "  sudo rm /usr/share/polkit-1/actions/io.github.crash_fd01.helpix.unlock.policy"
fi
echo "✓ Helpix disinstallato."
