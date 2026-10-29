# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cambia l'utente/il repository GitHub in tutto il progetto (indirizzi, ID dell'app, file con l'ID nel nome).

    python packaging/rename_owner.py <utente GitHub> [nome repository] [id numerico dell'utente]

Lo usa github-setup.sh quando il tuo nome utente non è quello scritto nel progetto. Tocca solo i file di testo
del progetto (non dist/, build/, .git/).
"""
import os
import re
import subprocess
import sys

OLD_OWNER = "crashfd01"
OLD_REPO = "helpix"
SKIP_DIRS = {".git", "dist", "build", "__pycache__", ".ruff_cache", "helpix.egg-info", "node_modules"}


def app_id_part(login: str) -> str:
    """Componente dell'ID dell'app (io.github.<questo>.helpix): minuscolo, «-» → «_» come chiede AppStream."""
    part = login.lower().replace("-", "_")
    return "_" + part if part[:1].isdigit() else part


def project_files(root: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout
        return [os.path.join(root, f) for f in out.split("\0") if f]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            files += [os.path.join(base, n) for n in names]
        return files


def main() -> int:
    login = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else OLD_REPO
    user_id = sys.argv[3] if len(sys.argv) > 3 else ""
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login) or not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
        print(f"Nome non valido: {login}/{repo}", file=sys.stderr)
        return 1
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    email = f"{user_id}+{login}@users.noreply.github.com" if user_id else f"{login}@users.noreply.github.com"
    # dal più specifico al più generico
    pairs = [
        (f"{OLD_OWNER}@users.noreply.github.com", email),
        (f"github.com/{OLD_OWNER}/{OLD_REPO}", f"github.com/{login}/{repo}"),
        (f"{OLD_OWNER}.github.io/{OLD_REPO}", f"{login.lower()}.github.io/{repo}"),
        (f"io.github.{OLD_OWNER}.", f"io.github.{app_id_part(login)}."),
        (f"io.github.{OLD_OWNER}", f"io.github.{app_id_part(login)}"),   # es. developer id nel metainfo
        (OLD_OWNER, login),
    ]
    this = os.path.abspath(__file__)
    changed = 0
    for path in project_files(root):
        if os.path.abspath(path) == this or not os.path.isfile(path) or os.path.islink(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue  # file binario
        new = text
        for old, rep in pairs:
            new = new.replace(old, rep)
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            changed += 1
    renamed = 0
    for path in project_files(root):
        name = os.path.basename(path)
        if f"io.github.{OLD_OWNER}." in name and os.path.exists(path):
            dest = os.path.join(os.path.dirname(path), name.replace(f"io.github.{OLD_OWNER}.",
                                                                     f"io.github.{app_id_part(login)}."))
            if subprocess.run(["git", "-C", root, "mv", path, dest], capture_output=True).returncode != 0:
                os.rename(path, dest)
            renamed += 1
    print(f"✓ {changed} file aggiornati, {renamed} rinominati: github.com/{login}/{repo}, "
          f"ID app io.github.{app_id_part(login)}.helpix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
