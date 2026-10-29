#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prepara i repository APT e RPM firmati a partire dai pacchetti di una versione.
#
#   packaging/update-repos.sh <cartella pacchetti> <cartella uscita> <URL pacchetti RPM> <URL sito>
#
# Variabile obbligatoria: GPG_KEY_ID (chiave già importata in gpg, senza passphrase o con l'agente sbloccato).
#
# Uscita:
#   <uscita>/apt/   repository APT «piatto»: Packages(.gz), Release, InRelease, Release.gpg e i .deb.
#                   Va pubblicato così com'è (il workflow lo carica nella release «repo» di GitHub).
#   <uscita>/site/  file per GitHub Pages: rpm/repodata (i pacchetti restano sulla release della versione,
#                   indicati con xml:base), helpix.repo, helpix.asc (chiave pubblica).
# Solo l'ultima versione è nel repository: dnf/apt aggiornano sempre all'ultima.
set -euo pipefail

PKGS="$(cd "$1" && pwd)"
OUT="$2"
RPM_BASEURL="${3%/}/"
SITE_URL="${4%/}"
: "${GPG_KEY_ID:?serve GPG_KEY_ID}"

rm -rf "$OUT/apt" "$OUT/site/rpm"
mkdir -p "$OUT/apt" "$OUT/site/rpm"

# ------------------------------------------------------------------ RPM: pacchetti firmati + metadati
shopt -s nullglob
rpms=("$PKGS"/*.rpm)
if (( ${#rpms[@]} )); then
    rpmsign --addsign --define "_gpg_name $GPG_KEY_ID" "${rpms[@]}" >/dev/null
    cp "${rpms[@]}" "$OUT/site/rpm/"
    createrepo_c --quiet --general-compress-type gz --baseurl "$RPM_BASEURL" "$OUT/site/rpm"
    rm -f "$OUT"/site/rpm/*.rpm   # i pacchetti stanno sulla release di GitHub, qui solo i metadati
    gpg --batch --yes --local-user "$GPG_KEY_ID" --detach-sign --armor "$OUT/site/rpm/repodata/repomd.xml"
fi
cat > "$OUT/site/helpix.repo" <<EOF
[helpix]
name=Helpix
baseurl=$SITE_URL/rpm/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=$SITE_URL/helpix.asc
metadata_expire=6h
EOF
gpg --batch --yes --armor --export "$GPG_KEY_ID" > "$OUT/site/helpix.asc"

# ------------------------------------------------------------------ APT: repository piatto firmato
debs=("$PKGS"/*.deb)
if (( ${#debs[@]} )); then
    cp "${debs[@]}" "$OUT/apt/"
    (
        cd "$OUT/apt"
        rm -f Release InRelease Release.gpg
        apt-ftparchive packages . > Packages
        gzip -9 -k -f Packages
        apt-ftparchive \
            -o APT::FTPArchive::Release::Origin=Helpix \
            -o APT::FTPArchive::Release::Label=Helpix \
            -o APT::FTPArchive::Release::Suite=stable \
            -o APT::FTPArchive::Release::Codename=stable \
            -o "APT::FTPArchive::Release::Architectures=$(dpkg-deb -f "${debs[0]}" Architecture) $(for d in "${debs[@]:1}"; do dpkg-deb -f "$d" Architecture; done | tr '\n' ' ')" \
            -o "APT::FTPArchive::Release::Description=Helpix: assistente AI per Linux" \
            release . > ../Release.tmp
        mv ../Release.tmp Release   # scritto fuori, se no elencherebbe sé stesso
        gpg --batch --yes --local-user "$GPG_KEY_ID" --digest-algo SHA512 --clearsign -o InRelease Release
        gpg --batch --yes --local-user "$GPG_KEY_ID" --digest-algo SHA512 -abs -o Release.gpg Release
    )
fi
echo "✓ Repository pronti in $OUT"
