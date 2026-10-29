#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installa Helpix per l'utente corrente. I pacchetti di sistema mancanti (Python, librerie di Qt,
# strumenti per gli screenshot) li installa con il gestore pacchetti: sudo chiede la password.
# Con --no-deps non tocca il sistema e si limita a dire cosa manca.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/helpix"
BIN="$HOME/.local/bin"
APPS="$DATA/applications"

DEPS=1
for arg in "$@"; do
    case "$arg" in
        --no-deps) DEPS=0 ;;
        -h|--help) echo "Uso: ./install.sh [--no-deps]   (--no-deps: non installa pacchetti di sistema)"; exit 0 ;;
    esac
done

# Gestore pacchetti della distro; su sistemi immutabili (Silverblue, Kinoite, Bazzite, SteamOS) non si usa
PM=""
for c in dnf:dnf apt-get:apt pacman:pacman zypper:zypper; do
    if command -v "${c%%:*}" >/dev/null; then PM="${c##*:}"; break; fi
done
if [[ -e /run/ostree-booted ]]; then PM=""; fi

# Installa pacchetti di sistema come root (sudo chiede la password; pkexec se sudo non c'è)
sys_install() {
    [[ $DEPS == 1 && -n "$PM" ]] || return 1
    local cmd
    case "$PM" in
        dnf) cmd=(dnf install -y "$@") ;;
        apt) cmd=(sh -c "apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -y $*") ;;
        pacman) cmd=(pacman -S --needed --noconfirm "$@") ;;
        zypper) cmd=(zypper --non-interactive install "$@") ;;
    esac
    echo "→ Installo i pacchetti di sistema: $* (servono i permessi di amministratore)"
    if [[ $EUID -eq 0 ]]; then "${cmd[@]}"
    elif command -v sudo >/dev/null; then sudo "${cmd[@]}"
    elif command -v pkexec >/dev/null; then pkexec "${cmd[@]}"
    else echo "  né sudo né pkexec disponibili" >&2; return 1
    fi
}

# Il Python più recente disponibile (≥ 3.9): su RHEL/Alma/Rocky 8 e openSUSE Leap «python3» è il 3.6
find_python() {
    PY=""
    local cand
    for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
        if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
            PY="$(command -v "$cand")"
            return 0
        fi
    done
    return 1
}

if ! find_python; then
    case "$PM" in
        dnf) if command -v python3 >/dev/null; then pkgs=(python3.11); else pkgs=(python3); fi ;;
        zypper) if command -v python3 >/dev/null; then pkgs=(python311); else pkgs=(python3); fi ;;
        apt) pkgs=(python3 python3-venv) ;;
        pacman) pkgs=(python) ;;
        *) pkgs=() ;;
    esac
    if [[ ${#pkgs[@]} -gt 0 ]]; then sys_install "${pkgs[@]}" || true; fi
    if ! find_python; then
        echo "Serve Python 3.9 o superiore e non sono riuscito a installarlo." >&2
        echo "  Fedora: sudo dnf install python3   Debian/Ubuntu: sudo apt install python3 python3-venv" >&2
        echo "  RHEL/Alma/Rocky 8: sudo dnf install python3.11   openSUSE Leap: sudo zypper install python311" >&2
        echo "  Arch: sudo pacman -S python" >&2
        exit 1
    fi
fi
if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
    # Debian/Ubuntu separano venv: python3-venv per il predefinito, python3.X-venv per gli altri
    ver="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    if [[ "$PM" == apt ]]; then sys_install "python$ver-venv" || sys_install python3-venv || true; fi
    if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
        echo "Manca il modulo venv per $PY. Debian/Ubuntu: sudo apt install python$ver-venv" >&2
        exit 1
    fi
fi
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|aarch64) ;;
    *) echo "Attenzione: Qt (PySide6) è pubblicato solo per x86_64 e aarch64; su $ARCH l'installazione può fallire." >&2 ;;
esac
GLIBC="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
ver_ge() { "$PY" -c "import sys; a=tuple(map(int,'$1'.split('.')[:2])); b=tuple(map(int,'$2'.split('.')[:2])); sys.exit(a < b)"; }
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
# Qt recente: 6.12 con Python ≥ 3.12, 6.11 con Python 3.10/3.11 (la 6.12.0 lì fa chiudere il programma; la scelta
# la fa pip, vedi pyproject.toml). Serve glibc ≥ 2.34 (≥ 2.39 su aarch64); altrimenti Qt 6.8/6.9, compatibile con
# Helpix (provato con tutti i test): RHEL/Alma/Rocky 8, Debian 11, Ubuntu 20.04, openSUSE Leap 15…
QT=modern
if [[ -z "$GLIBC" ]]; then
    echo "Attenzione: libc diversa da glibc (es. Alpine/musl): i pacchetti Qt per pip non funzionano qui." >&2
elif ! ver_ge "$GLIBC" 2.28; then
    echo "Attenzione: glibc $GLIBC è troppo vecchia per Qt 6 (serve 2.28 o superiore)." >&2
else
    need=2.34; [[ "$ARCH" == aarch64 ]] && need=2.39
    if ! ver_ge "$GLIBC" "$need" || ! ver_ge "$PYVER" 3.10; then QT=compat; fi
fi
COMPAT_DEPS=("PySide6-Essentials>=6.8,<6.10" "PySide6-Addons>=6.8,<6.10" "requests>=2.25" "keyring>=23"
             "cryptography>=41" "jeepney>=0.8")

echo "→ Creo l'ambiente in $PREFIX/venv"
"$PY" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
echo "→ Installo Helpix e le dipendenze (Qt può richiedere qualche minuto)"
install_compat() {
    echo "  Il Qt più recente non è disponibile per questo sistema (glibc ${GLIBC:-?}, Python $PYVER, $ARCH): uso Qt 6.8/6.9."
    "$PREFIX/venv/bin/pip" install --quiet "${COMPAT_DEPS[@]}" && "$PREFIX/venv/bin/pip" install --quiet --no-deps .
}
PIPLOG="$(mktemp)"
if [[ "$QT" == compat ]]; then
    install_compat
elif ! "$PREFIX/venv/bin/pip" install --quiet . 2>"$PIPLOG"; then
    if grep -qiE "pyside6|no matching distribution|requires-python" "$PIPLOG"; then
        install_compat   # il calcolo sopra non è bastato: proviamo comunque la versione compatibile
    else
        cat "$PIPLOG" >&2; rm -f "$PIPLOG"; exit 1
    fi
fi
rm -f "$PIPLOG"

mkdir -p "$BIN" "$APPS"
ln -sf "$PREFIX/venv/bin/helpix" "$BIN/helpix"
for size in 16 24 32 48 64 128 256 512; do
    install -Dm644 "helpix/data/icons/helpix-$size.png" "$DATA/icons/hicolor/${size}x${size}/apps/helpix.png"
done
sed "s|@EXEC@|$BIN/helpix|" packaging/helpix.desktop > "$APPS/helpix.desktop"
# scheda per i software center (GNOME Software, Discover): nome, descrizione, licenza
install -Dm644 packaging/io.github.crash_fd01.helpix.metainfo.xml "$DATA/metainfo/io.github.crash_fd01.helpix.metainfo.xml"
update-desktop-database "$APPS" >/dev/null 2>&1 || true
gtk-update-icon-cache -q "$DATA/icons/hicolor" >/dev/null 2>&1 || true

# Librerie di sistema che servono a Qt e strumenti per gli screenshot: Helpix guarda cosa manca davvero
# (ldd sui moduli di Qt) e lo installa con il gestore pacchetti della distro
echo "→ Controllo le dipendenze di sistema"
if [[ $DEPS == 1 ]]; then
    "$PREFIX/venv/bin/python" -m helpix.sysdeps install --yes || \
        echo "  Alcune dipendenze mancano ancora: le trovi in Helpix › Impostazioni › Dipendenze di sistema." >&2
else
    "$PREFIX/venv/bin/python" -m helpix.sysdeps check || true
fi

echo
echo "✓ Helpix installato. Avvialo dal menu delle applicazioni oppure con: helpix"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  (aggiungi $BIN al PATH per usare il comando 'helpix')";; esac
