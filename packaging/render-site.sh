#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copia il sito (site/) nella cartella di uscita sostituendo indirizzi e versione.
#
#   packaging/render-site.sh <uscita> <URL sito> <URL repository APT> <URL sorgenti> <versione> <cartella pacchetti>
#
# Dalla cartella dei pacchetti legge glibc-<arch>.txt (versione minima di glibc, scritta da build-packages.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$1" SITE_URL="${2%/}" APT_URL="${3%/}" REPO_URL="${4%/}" VERSION="$5" PKGS="$6"
glibc() { cat "$PKGS/glibc-$1.txt" 2>/dev/null || echo "$2"; }
mkdir -p "$OUT"
FINGERPRINT="—"
if [[ -f "$OUT/helpix.asc" ]]; then   # scritta da update-repos.sh
    FINGERPRINT="$(gpg --show-keys --with-colons "$OUT/helpix.asc" | awk -F: '/^fpr/{print $10; exit}' | sed 's/.\{4\}/& /g; s/ $//')"
fi
for f in "$ROOT"/site/*; do
    sed -e "s|@SITE_URL@|$SITE_URL|g" -e "s|@APT_URL@|$APT_URL|g" -e "s|@REPO_URL@|$REPO_URL|g" \
        -e "s|@VERSION@|$VERSION|g" -e "s|@FINGERPRINT@|$FINGERPRINT|g" -e "s|@GLIBC_x86_64@|$(glibc x86_64 2.34)|g" \
        -e "s|@GLIBC_aarch64@|$(glibc aarch64 2.39)|g" "$f" > "$OUT/$(basename "$f")"
done
cp "$ROOT/helpix/data/icons/helpix-128.png" "$OUT/icon.png"
cp "$ROOT/docs/principale-chiaro.png" "$OUT/screenshot-light.png"
cp "$ROOT/docs/principale-scuro.png" "$OUT/screenshot-dark.png"
cp "$ROOT/helpix/data/fonts/Inter-Variable.ttf" "$ROOT/helpix/data/fonts/JetBrainsMono-Regular.ttf" "$OUT/"
touch "$OUT/.nojekyll"
if grep -l '@[A-Za-z_0-9]*@' "$OUT"/*.html "$OUT"/*.sh 2>/dev/null; then echo "Segnaposto non sostituiti" >&2; exit 1; fi
echo "✓ Sito pronto in $OUT"
