#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Pubblica Helpix su GitHub e attiva gli aggiornamenti con apt/dnf/zypper. Va eseguito una volta, sul tuo PC,
# dalla cartella del progetto:
#
#   packaging/github-setup.sh [nome del repository]        (predefinito: helpix)
#
# Serve: git, gh (GitHub CLI, con «gh auth login» già fatto), gpg. Prima di cambiare qualcosa mostra cosa farà
# e chiede conferma. Si può rieseguire: salta quello che è già fatto.
#
#   1. se il tuo utente GitHub non è quello scritto nel progetto, lo aggiorna (indirizzi, ID dell'app);
#   2. crea il repository pubblico e ci carica il codice;
#   3. imposta descrizione, sito, argomenti e le segnalazioni private delle vulnerabilità;
#   4. attiva GitHub Pages (pubblicate dal workflow «Rilascio») e permette ai tag v* di aggiornarle;
#   5. crea la chiave che firma i pacchetti: la privata va nel secret HELPIX_GPG_PRIVATE_KEY e in una copia di
#      backup per te, la pubblica in packaging/signing-key.asc;
#   6. pubblica il tag della versione: il workflow «Rilascio» costruisce, firma e pubblica tutto (~15 minuti).
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_NAME="${1:-helpix}"
DESCRIPTION="Fix your Linux PC with the AI you already use (ChatGPT, Claude, Gemini, Copilot, DeepSeek)"
TOPICS="linux,ai,troubleshooting,sysadmin,desktop-app,pyside6,qt6,chatgpt,claude,gemini,fedora,ubuntu"
BACKUP="$HOME/helpix-signing-key-PRIVATE.asc"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'Errore: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" > /dev/null || die "manca $1 (${2})"; }

need git "Fedora: sudo dnf install git — Ubuntu: sudo apt install git"
need gh "Fedora: sudo dnf install gh — Ubuntu: sudo apt install gh — poi: gh auth login"
need gpg "Fedora: sudo dnf install gnupg2 — Ubuntu: sudo apt install gnupg"
gh auth status > /dev/null 2>&1 || die "prima accedi a GitHub con: gh auth login"

LOGIN="$(gh api user --jq .login)"
USER_ID="$(gh api user --jq .id)"
REPO="$LOGIN/$REPO_NAME"
OWNER_LC="${LOGIN,,}"
if [[ "${REPO_NAME,,}" == "$OWNER_LC.github.io" ]]; then SITE_URL="https://$OWNER_LC.github.io"
else SITE_URL="https://$OWNER_LC.github.io/$REPO_NAME"; fi
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1)"
CURRENT="$(sed -n 's|^SPDX-PackageDownloadLocation = "https://github.com/\(.*\)"|\1|p' REUSE.toml)"

bold "Helpix $VERSION → https://github.com/$REPO"
echo "  sito e repository dei pacchetti: $SITE_URL"
[[ "$CURRENT" != "$REPO" ]] && echo "  il progetto ora punta a $CURRENT: lo aggiorno a $REPO"
gh repo view "$REPO" > /dev/null 2>&1 && echo "  il repository esiste già: aggiorno solo quello che manca"
read -rp "Procedo? [s/N] " answer
[[ "$answer" =~ ^[sSyY] ]] || exit 0

# ------------------------------------------------------------------ 1. utente e repository nel progetto
if [[ "$CURRENT" != "$REPO" ]]; then
    python3 packaging/rename_owner.py "$LOGIN" "$REPO_NAME" "$USER_ID"
fi

# ------------------------------------------------------------------ 2. repository e codice
[[ -d .git ]] || git init -q -b main
if [[ -z "$(git config user.email || true)" ]]; then
    git config user.name "$LOGIN"
    git config user.email "$USER_ID+$LOGIN@users.noreply.github.com"
    echo "  (git: per questo repository firmo i commit come $LOGIN, con l'indirizzo noreply di GitHub)"
fi
git add -A
git diff --cached --quiet || git commit -q -m "Helpix $VERSION"
if ! gh repo view "$REPO" > /dev/null 2>&1; then
    bold "Creo il repository pubblico $REPO"
    gh repo create "$REPO" --public --description "$DESCRIPTION" --homepage "$SITE_URL" > /dev/null
fi
if [[ "$(gh config get git_protocol 2>/dev/null)" == ssh ]]; then URL="git@github.com:$REPO.git"
else URL="https://github.com/$REPO.git"; gh auth setup-git; fi   # git usa l'accesso di gh
git remote get-url origin > /dev/null 2>&1 && git remote set-url origin "$URL" || git remote add origin "$URL"
bold "Carico il codice"
git push -u origin HEAD:main

# ------------------------------------------------------------------ 3. impostazioni
bold "Imposto descrizione, sito e argomenti"
gh repo edit "$REPO" --description "$DESCRIPTION" --homepage "$SITE_URL" --enable-issues --enable-wiki=false \
    --add-topic "$TOPICS" > /dev/null
gh api -X PUT "repos/$REPO/private-vulnerability-reporting" > /dev/null 2>&1 \
    || echo "  (segnalazioni private delle vulnerabilità: attivale da Settings → Security)"

# ------------------------------------------------------------------ 4. GitHub Pages
bold "Attivo GitHub Pages"
if gh api "repos/$REPO/pages" > /dev/null 2>&1; then
    gh api -X PUT "repos/$REPO/pages" -f build_type=workflow > /dev/null
else
    gh api -X POST "repos/$REPO/pages" -f build_type=workflow > /dev/null
fi
# l'ambiente github-pages di norma accetta solo il ramo principale: il sito lo pubblica il tag della versione
gh api -X PUT "repos/$REPO/environments/github-pages" --input - > /dev/null <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
gh api -X POST "repos/$REPO/environments/github-pages/deployment-branch-policies" -f name=main -f type=branch \
    > /dev/null 2>&1 || true   # già presente
gh api -X POST "repos/$REPO/environments/github-pages/deployment-branch-policies" -f 'name=v*' -f type=tag \
    > /dev/null 2>&1 || true

# ------------------------------------------------------------------ 5. chiave di firma
if gh secret list -R "$REPO" 2> /dev/null | grep -q '^HELPIX_GPG_PRIVATE_KEY'; then
    echo "  chiave di firma già configurata"
else
    bold "Creo la chiave che firma i pacchetti"
    KEYHOME="$(mktemp -d)"
    trap 'GNUPGHOME="$KEYHOME" gpgconf --kill gpg-agent 2>/dev/null || true; rm -rf "$KEYHOME"' EXIT
    chmod 700 "$KEYHOME"
    GNUPGHOME="$KEYHOME" gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
        --quick-gen-key "Helpix packages <$USER_ID+$LOGIN@users.noreply.github.com>" rsa4096 sign never
    FPR="$(GNUPGHOME="$KEYHOME" gpg --list-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')"
    [[ -e "$BACKUP" ]] && mv "$BACKUP" "$BACKUP.$(date +%Y%m%d%H%M%S).old"
    (umask 077; GNUPGHOME="$KEYHOME" gpg --armor --export-secret-keys "$FPR" > "$BACKUP")
    gh secret set HELPIX_GPG_PRIVATE_KEY -R "$REPO" < "$BACKUP"
    GNUPGHOME="$KEYHOME" gpg --armor --export "$FPR" > packaging/signing-key.asc
    git add packaging/signing-key.asc
    git commit -q -m "Chiave pubblica che firma i pacchetti" && git push -q origin HEAD:main
    echo "  impronta: $FPR"
    echo "  copia di backup della chiave privata: $BACKUP"
    echo "  → spostala in un posto sicuro (gestore di password, chiavetta) e cancellala da qui."
    echo "    Non va mai nel repository: chi la ha può firmare aggiornamenti a nome tuo."
fi

# ------------------------------------------------------------------ 6. rilascio
TAG="v$VERSION"
if git ls-remote --exit-code --tags origin "refs/tags/$TAG" > /dev/null 2>&1; then
    echo "  il tag $TAG è già pubblicato: per ripubblicarlo usa Actions → Rilascio → Run workflow"
else
    bold "Pubblico $TAG: parte il workflow di rilascio"
    git tag -a "$TAG" -m "Helpix $VERSION"
    git push -q origin "$TAG"
fi

bold "✓ Fatto"
echo "  Repository:   https://github.com/$REPO"
echo "  Rilascio:     https://github.com/$REPO/actions (circa 15 minuti; oppure: gh run watch -R $REPO)"
echo "  Poi il sito:  $SITE_URL"
echo "  Installazione per gli utenti: curl -fsSL $SITE_URL/setup.sh | sudo sh"
echo
echo "  Prossime versioni: aggiorna version in pyproject.toml (e la release nel metainfo), fai commit e push, poi"
echo "    git tag -a vX.Y.Z -m 'Helpix X.Y.Z' && git push origin vX.Y.Z"
