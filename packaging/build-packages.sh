#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Costruisce i pacchetti .deb e .rpm di Helpix in dist/packages/.
#
# I pacchetti sono autonomi: dentro /opt/helpix c'è il proprio Python (python-build-standalone) con Qt 6 e le
# altre dipendenze Python. Così lo stesso pacchetto funziona su Fedora, RHEL, openSUSE, Debian, Ubuntu e Mint,
# qualunque versione di Python e Qt abbiano; le librerie di sistema che servono (Xcb, EGL, NSS…) diventano
# dipendenze del pacchetto e le installa dnf/apt.
#
# Uso: packaging/build-packages.sh [x86_64|aarch64]
# Variabili: PBS_URL (archivio di python-build-standalone da usare), MAINTAINER, SKIP_RPM=1, SKIP_DEB=1
set -euo pipefail

ARCH="${1:-$(uname -m)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/packages"
MAINTAINER="${MAINTAINER:-Crash <Crash-FD01@users.noreply.github.com>}"
HOMEPAGE="https://github.com/Crash-FD01/Helpix"
VERSION="$(python3 -c "import re,sys; print(re.search(r'^version = \"([^\"]+)\"', open('$ROOT/pyproject.toml').read(), re.M).group(1))")"
# Python incluso nel pacchetto: python-build-standalone (licenza PSF; le librerie incluse sono elencate nel
# pacchetto stesso). Versione fissata per avere build ripetibili; il workflow di rilascio può passarne un'altra.
PBS_TAG="20250317"
PBS_PY="3.13.2"
case "$ARCH" in
    x86_64) DEB_ARCH=amd64 ;;
    aarch64) DEB_ARCH=arm64 ;;
    *) echo "Architettura non supportata: $ARCH" >&2; exit 1 ;;
esac
PBS_URL="${PBS_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/cpython-$PBS_PY+$PBS_TAG-$ARCH-unknown-linux-gnu-install_only_stripped.tar.gz}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/root"
APP="$STAGE/opt/helpix"
mkdir -p "$APP" "$OUT"

echo "→ Python $PBS_PY ($ARCH)"
curl -fsSL "$PBS_URL" | tar -xz -C "$APP"          # crea $APP/python
# Ambiente isolato (venv) sopra il Python incluso: le librerie Python dell'utente (~/.local) non possono
# né mancare al momento della build né interferire con Helpix dopo l'installazione.
export PYTHONNOUSERSITE=1 PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
"$APP/python/bin/python3" -m venv "$APP/venv"
PY="$APP/venv/bin/python3"
"$PY" -m pip install --quiet --upgrade pip
echo "→ Helpix $VERSION e dipendenze (Qt 6)"
"$PY" -m pip install --quiet --no-warn-script-location "$ROOT"
"$PY" -m pip list --format=freeze > "$WORK/bundled.txt"   # versioni esatte, per le note sulle licenze
# il venv e i programmi installati da pip puntano alla cartella di lavoro: li sistemo per /opt/helpix
for link in "$APP"/venv/bin/*; do
    [[ -L "$link" ]] || continue
    target="$(readlink "$link")"
    if [[ "$target" == "$APP"/python/* ]]; then
        ln -sfn "../../python/${target#"$APP"/python/}" "$link"
    fi
done
grep -rlI --null "$STAGE" "$APP/venv/bin" "$APP/venv/pyvenv.cfg" 2>/dev/null | xargs -0 -r sed -i "s|$STAGE||g"
if grep -rlI "$STAGE" "$APP/venv/bin" "$APP/venv/pyvenv.cfg" >/dev/null 2>&1; then
    echo "Errore: percorsi della cartella di lavoro rimasti nel venv" >&2; exit 1
fi
# niente di inutile: i test della libreria standard, gli strumenti per sviluppatori di Qt
rm -rf "$APP"/python/lib/python3.*/test "$APP"/python/lib/python3.*/idlelib "$APP"/python/lib/python3.*/tkinter \
       "$APP"/python/lib/python3.*/turtledemo "$APP"/python/lib/{tcl,tk,Tix,itcl,thread}[0-9]*
SP="$(echo "$APP"/venv/lib/python3.*/site-packages)"
rm -rf "$SP"/PySide6/{designer,assistant,linguist,lupdate,lrelease,qmlformat,qmllint,qmlls,rcc,uic} \
       "$SP"/PySide6/Qt/libexec/{qmlcachegen,qmlimportscanner,qmltyperegistrar,rcc,uic} "$SP"/PySide6/scripts \
       "$APP"/venv/bin/pyside6-* 2>/dev/null || true

# moduli già compilati: l'utente non può scrivere in /opt, senza questi Python li ricompilerebbe a ogni avvio
# (con il Python di base: il venv ormai punta a /opt/helpix, che sulla macchina di build non c'è)
BASEPY="$APP/python/bin/python3"
"$BASEPY" -m compileall -q -f -j0 -s "$STAGE" -p / "$APP"/python/lib/python3.* "$SP"

echo "→ File di sistema"
install -Dm755 /dev/stdin "$STAGE/usr/bin/helpix" <<'EOF'
#!/bin/sh
# Helpix (pacchetto): Python e Qt inclusi in /opt/helpix. -P: la cartella corrente non entra nel percorso dei
# moduli (una cartella «helpix» lì non può sostituire il programma).
exec /opt/helpix/venv/bin/python3 -P -m helpix "$@"
EOF
sed "s|@EXEC@|helpix|" "$ROOT/packaging/helpix.desktop" | install -Dm644 /dev/stdin "$STAGE/usr/share/applications/helpix.desktop"
for size in 16 24 32 48 64 128 256 512; do
    install -Dm644 "$ROOT/helpix/data/icons/helpix-$size.png" "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/helpix.png"
done
install -Dm644 "$ROOT/packaging/io.github.crash_fd01.helpix.metainfo.xml" \
    "$STAGE/usr/share/metainfo/io.github.crash_fd01.helpix.metainfo.xml"
# regola polkit dello sblocco: con il pacchetto il blocco facoltativo funziona senza chiedere altro
install -Dm644 "$ROOT/helpix/data/polkit/io.github.crash_fd01.helpix.unlock.policy" \
    "$STAGE/usr/share/polkit-1/actions/io.github.crash_fd01.helpix.unlock.policy"
install -Dm644 "$ROOT/README.md" "$STAGE/usr/share/doc/helpix/README.md"
install -Dm644 "$ROOT/docs/GUIDA.md" "$STAGE/usr/share/doc/helpix/GUIDA.md"
install -Dm644 "$ROOT/THIRD-PARTY-NOTICES.md" "$STAGE/usr/share/doc/helpix/THIRD-PARTY-NOTICES.md"
install -Dm644 "$ROOT/LICENSE" "$STAGE/usr/share/licenses/helpix/LICENSE"
for f in "$ROOT"/LICENSES/*.txt; do install -Dm644 "$f" "$STAGE/usr/share/licenses/helpix/$(basename "$f")"; done
# componenti inclusi in /opt/helpix: licenze di Python e di Qt (LGPL) e dove trovarne i sorgenti
install -Dm644 "$(echo "$APP"/python/lib/python3.*/LICENSE.txt)" "$STAGE/usr/share/licenses/helpix/Python-PSF-2.0.txt"
if [[ -f /usr/share/common-licenses/LGPL-3 ]]; then
    install -Dm644 /usr/share/common-licenses/LGPL-3 "$STAGE/usr/share/licenses/helpix/LGPL-3.0-only.txt"
else
    curl -fsSL https://www.gnu.org/licenses/lgpl-3.0.txt | install -Dm644 /dev/stdin "$STAGE/usr/share/licenses/helpix/LGPL-3.0-only.txt"
fi
QT_VER="$(sed -n 's/^PySide6[-_]Essentials==//ip' "$WORK/bundled.txt")"
{
    echo "Componenti inclusi in /opt/helpix (versioni esatte di questo pacchetto)"
    echo "======================================================================"
    echo
    echo "Python $PBS_PY (python-build-standalone $PBS_TAG): licenza PSF-2.0, /usr/share/licenses/helpix/Python-PSF-2.0.txt"
    echo "  Sorgenti: https://www.python.org/downloads/release/python-${PBS_PY//./}/"
    echo "            https://github.com/astral-sh/python-build-standalone/releases/tag/$PBS_TAG"
    echo
    echo "Qt $QT_VER e Qt for Python (PySide6, Shiboken6) $QT_VER: licenza LGPL-3.0-only,"
    echo "  /usr/share/licenses/helpix/LGPL-3.0-only.txt (con la GPL-3.0 in GPL-3.0-or-later.txt)."
    echo "  Sorgenti completi di questa versione:"
    echo "    https://download.qt.io/official_releases/qt/${QT_VER%.*}/$QT_VER/"
    echo "    https://download.qt.io/official_releases/QtForPython/pyside6/"
    echo "  Qt è usato senza modifiche, come librerie condivise. Puoi sostituirlo con un'altra versione:"
    echo "    sudo /opt/helpix/venv/bin/python3 -m pip install 'PySide6-Essentials==X' 'PySide6-Addons==X' 'PySide6-WebEngine==X'"
    echo "  Qt WebEngine contiene Chromium e i suoi componenti di terzi (licenze BSD e altre):"
    echo "    https://doc.qt.io/qt-6/qtwebengine-licensing.html"
    echo
    echo "Librerie Python (testi delle licenze nelle cartelle *.dist-info di"
    echo "/opt/helpix/venv/lib/python3.*/site-packages/):"
    sed 's/^/  /' "$WORK/bundled.txt"
} | install -Dm644 /dev/stdin "$STAGE/usr/share/licenses/helpix/BUNDLED-COMPONENTS.txt"

echo "→ Dipendenze di sistema (librerie richieste dai file inclusi)"
"$BASEPY" "$ROOT/packaging/needed_libs.py" "$STAGE" > "$WORK/sonames.txt"
cp "$WORK/sonames.txt" "$OUT/sonames-$ARCH.txt"
GLIBC_MIN="$("$BASEPY" "$ROOT/packaging/needed_libs.py" "$STAGE" --glibc)"
export GLIBC_MIN
echo "$GLIBC_MIN" > "$OUT/glibc-$ARCH.txt"   # per lo script di installazione del sito
echo "  $(wc -l < "$WORK/sonames.txt") librerie di sistema, glibc >= $GLIBC_MIN"

SIZE_KB="$(du -sk "$STAGE" | cut -f1)"
SUMMARY="Fix your Linux PC with the AI you already use"
DESC="Helpix opens ChatGPT, Claude, Gemini, Copilot or DeepSeek with your own account, pastes screenshots
 into the chat, runs the commands the AI suggests with one click and brings the output back."

# ------------------------------------------------------------------ .deb
if [[ "${SKIP_DEB:-0}" != 1 ]]; then
    echo "→ Pacchetto .deb"
    DEBROOT="$WORK/deb"
    cp -a "$STAGE" "$DEBROOT"
    mkdir -p "$DEBROOT/DEBIAN" "$DEBROOT/usr/share/doc/helpix"
    cat > "$DEBROOT/usr/share/doc/helpix/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Helpix
Source: $HOMEPAGE

Files: *
Copyright: 2026 Crash
License: GPL-3.0-or-later
 On Debian systems, the complete text of the GNU General Public License version 3 can be found in
 /usr/share/common-licenses/GPL-3. Third-party components bundled in /opt/helpix (Python, Qt for Python,
 xterm.js, fonts) are listed in /usr/share/doc/helpix/THIRD-PARTY-NOTICES.md and keep their own licenses;
 exact versions, source code locations and license texts are in /usr/share/licenses/helpix/BUNDLED-COMPONENTS.txt
 and /usr/share/licenses/helpix/.
EOF
    DEPENDS="$("$BASEPY" "$ROOT/packaging/deb_depends.py" "$WORK/sonames.txt")"
    cat > "$DEBROOT/DEBIAN/control" <<EOF
Package: helpix
Version: $VERSION
Architecture: $DEB_ARCH
Maintainer: $MAINTAINER
Installed-Size: $SIZE_KB
Depends: $DEPENDS
Recommends: pkexec | policykit-1, xdg-desktop-portal, x11-utils
Section: utils
Priority: optional
Homepage: $HOMEPAGE
Description: $SUMMARY
 $DESC
EOF
    # file creati dopo l'installazione (es. cache di Python se Helpix gira come root): via con il pacchetto
    install -m755 /dev/stdin "$DEBROOT/DEBIAN/postrm" <<'EOF2'
#!/bin/sh
set -e
case "$1" in
    remove|purge) rm -rf /opt/helpix ;;
esac
EOF2
    (cd "$DEBROOT" && find . -path ./DEBIAN -prune -o -type f -printf '%P\0' | xargs -0 md5sum > DEBIAN/md5sums)
    dpkg-deb --root-owner-group -Zxz -z6 --build "$DEBROOT" "$OUT/helpix_${VERSION}_${DEB_ARCH}.deb" >/dev/null
    echo "  $(du -h "$OUT/helpix_${VERSION}_${DEB_ARCH}.deb" | cut -f1)  dist/packages/helpix_${VERSION}_${DEB_ARCH}.deb"
fi

# ------------------------------------------------------------------ .rpm
if [[ "${SKIP_RPM:-0}" != 1 ]]; then
    echo "→ Pacchetto .rpm"
    TOP="$WORK/rpmbuild"
    mkdir -p "$TOP"/{SPECS,RPMS,BUILD,BUILDROOT}
    REQUIRES="$("$BASEPY" "$ROOT/packaging/rpm_requires.py" "$WORK/sonames.txt" "$ARCH")"
    cat > "$TOP/SPECS/helpix.spec" <<EOF
Name:           helpix
Version:        $VERSION
Release:        1
Summary:        $SUMMARY
License:        GPL-3.0-or-later AND LGPL-3.0-only AND PSF-2.0 AND MIT AND Apache-2.0 AND BSD-3-Clause AND MPL-2.0 AND OFL-1.1
URL:            $HOMEPAGE
BuildArch:      $ARCH
# dipendenze calcolate dalle librerie di sistema richieste (le librerie incluse non vanno né richieste né
# offerte al resto del sistema)
AutoReqProv:    no
$REQUIRES
Recommends:     polkit
Recommends:     xdg-desktop-portal

%global __os_install_post %{nil}
%global debug_package %{nil}
%global _build_id_links none

%description
$DESC

%install
cp -a "$STAGE"/. %{buildroot}/

%postun
# disinstallazione (non aggiornamento): via anche i file creati dopo, es. cache di Python
if [ "\$1" = 0 ]; then rm -rf /opt/helpix; fi

%files
/opt/helpix
/usr/bin/helpix
/usr/share/applications/helpix.desktop
/usr/share/icons/hicolor/*/apps/helpix.png
/usr/share/metainfo/io.github.crash_fd01.helpix.metainfo.xml
/usr/share/polkit-1/actions/io.github.crash_fd01.helpix.unlock.policy
%doc /usr/share/doc/helpix
%license /usr/share/licenses/helpix
EOF
    rpmbuild --quiet -bb --define "_topdir $TOP" --define "_binary_payload w19.zstdio" "$TOP/SPECS/helpix.spec"
    cp "$TOP"/RPMS/"$ARCH"/helpix-*.rpm "$OUT/"
    echo "  $(du -h "$OUT"/helpix-"$VERSION"-1."$ARCH".rpm | cut -f1)  dist/packages/helpix-$VERSION-1.$ARCH.rpm"
fi
