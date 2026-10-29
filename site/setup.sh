#!/bin/sh
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Aggiunge il repository di Helpix al sistema e installa Helpix. Da lì gli aggiornamenti arrivano con
# «sudo apt upgrade», «sudo dnf upgrade», «sudo zypper update» insieme a quelli del sistema.
#
#   curl -fsSL @SITE_URL@/setup.sh | sudo sh
#   curl -fsSL @SITE_URL@/setup.sh | sudo sh -s -- --remove     (toglie Helpix e il repository)
#
# Leggilo pure prima di eseguirlo: fa solo quello che c'è scritto qui sotto.
set -eu

SITE="@SITE_URL@"
APT_URL="@APT_URL@"
SOURCE="@REPO_URL@"
GLIBC_X86_64="@GLIBC_x86_64@"
GLIBC_AARCH64="@GLIBC_aarch64@"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'Errore: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "servono i permessi di amministratore: curl -fsSL $SITE/setup.sh | sudo sh"

fetch() {  # fetch URL FILE
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
    else die "manca curl (o wget) per scaricare $1"; fi
}

if [ "${1:-}" = "--remove" ]; then
    say "Rimuovo Helpix e il suo repository"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get remove -y helpix || true
        rm -f /etc/apt/sources.list.d/helpix.list /etc/apt/keyrings/helpix.asc
    elif [ -e /run/ostree-booted ]; then
        rpm-ostree uninstall helpix || true
        rm -f /etc/yum.repos.d/helpix.repo
    elif command -v dnf >/dev/null 2>&1; then
        dnf remove -y helpix || true
        rm -f /etc/yum.repos.d/helpix.repo
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive remove helpix || true
        zypper --non-interactive removerepo helpix || true
    fi
    say "Fatto. Le tue impostazioni restano in ~/.config/helpix e ~/.local/share/helpix."
    exit 0
fi

# ------------------------------------------------------------------ il pacchetto funziona qui?
case "$(uname -m)" in
    x86_64) need="$GLIBC_X86_64" ;;
    aarch64) need="$GLIBC_AARCH64" ;;
    *) die "i pacchetti ci sono per x86_64 e aarch64. Su $(uname -m) usa l'installazione dai sorgenti: $SOURCE#installazione" ;;
esac
have="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
if [ -z "$have" ]; then
    die "il pacchetto richiede glibc (questo sistema usa un'altra libreria C). Usa l'installazione dai sorgenti: $SOURCE#installazione"
fi
if [ "$(printf '%s\n%s\n' "$need" "$have" | sort -V | head -n1)" != "$need" ]; then
    die "il pacchetto richiede glibc $need o più recente, qui c'è la $have. Usa l'installazione dai sorgenti, che sceglie una versione di Qt compatibile: $SOURCE#installazione"
fi

# installazione nella cartella utente (install.sh) ancora presente? Va bene lo stesso, ma meglio una sola
user_home=""
if [ -n "${SUDO_USER:-}" ]; then user_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"; fi
if [ -n "$user_home" ] && [ -d "$user_home/.local/share/helpix/venv" ]; then
    echo "Nota: c'è anche un'installazione di Helpix nella tua cartella utente (da install.sh)."
    echo "      Per usare solo il pacchetto toglila con: ./uninstall.sh (le impostazioni restano)."
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fetch "$SITE/helpix.asc" "$tmp/helpix.asc"
grep -q "BEGIN PGP PUBLIC KEY BLOCK" "$tmp/helpix.asc" || die "la chiave scaricata da $SITE/helpix.asc non è valida"

# ------------------------------------------------------------------ Debian, Ubuntu, Mint, Pop!_OS, Zorin…
if command -v apt-get >/dev/null 2>&1; then
    say "Aggiungo il repository APT di Helpix"
    install -d -m 755 /etc/apt/keyrings
    install -m 644 "$tmp/helpix.asc" /etc/apt/keyrings/helpix.asc
    echo "deb [signed-by=/etc/apt/keyrings/helpix.asc] $APT_URL ./" > /etc/apt/sources.list.d/helpix.list
    apt-get update
    say "Installo Helpix"
    DEBIAN_FRONTEND=noninteractive apt-get install -y helpix
    upgrade="sudo apt update && sudo apt upgrade"

# ------------------------------------------------------------------ Fedora Silverblue/Kinoite, Bazzite… (immutabili)
elif [ -e /run/ostree-booted ] && command -v rpm-ostree >/dev/null 2>&1; then
    say "Aggiungo il repository RPM di Helpix"
    fetch "$SITE/helpix.repo" /etc/yum.repos.d/helpix.repo
    rpm --import "$tmp/helpix.asc"
    say "Installo Helpix (sistema immutabile: sarà attivo dopo il riavvio)"
    rpm-ostree install --idempotent helpix
    upgrade="rpm-ostree upgrade (o gli aggiornamenti automatici del sistema)"

# ------------------------------------------------------------------ Fedora, RHEL 9+, Alma, Rocky, CentOS Stream
elif command -v dnf >/dev/null 2>&1; then
    say "Aggiungo il repository RPM di Helpix"
    fetch "$SITE/helpix.repo" /etc/yum.repos.d/helpix.repo
    rpm --import "$tmp/helpix.asc"
    say "Installo Helpix"
    dnf install -y helpix
    upgrade="sudo dnf upgrade"

# ------------------------------------------------------------------ openSUSE Tumbleweed, Leap
elif command -v zypper >/dev/null 2>&1; then
    say "Aggiungo il repository RPM di Helpix"
    rpm --import "$tmp/helpix.asc"
    zypper --non-interactive removerepo helpix >/dev/null 2>&1 || true
    zypper --non-interactive addrepo --refresh "$SITE/helpix.repo"
    zypper --non-interactive --gpg-auto-import-keys refresh helpix
    say "Installo Helpix"
    zypper --non-interactive install helpix
    upgrade="sudo zypper refresh && sudo zypper update"

else
    die "non riconosco il gestore dei pacchetti (apt, dnf, zypper). Su Arch e derivate usa l'installazione dai sorgenti: $SOURCE#installazione"
fi

say "✓ Helpix installato. Lo trovi nel menu delle applicazioni, o avvialo con: helpix"
echo "  Gli aggiornamenti arrivano con quelli del sistema: $upgrade"
echo "  Per toglierlo: curl -fsSL $SITE/setup.sh | sudo sh -s -- --remove"
