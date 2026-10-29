# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Campo Depends del .deb dalle librerie richieste (sonames.txt).

Per ogni libreria cerca il pacchetto che la fornisce sul sistema di build (dpkg -S); se lì non è installata
usa la tabella di helpix.sysdeps. I nomi sono quelli di Ubuntu 22.04/Debian 12: sulle versioni più nuove
(es. libasound2 → libasound2t64) i pacchetti rinominati li «forniscono» ancora, quindi apt li risolve.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpix.sysdeps import LIBS, MANAGERS  # noqa: E402

GLIBC_MIN = os.environ.get("GLIBC_MIN", "2.34")  # calcolata da build-packages.sh (needed_libs.py --glibc)


def package_for(soname: str) -> str | None:
    try:
        out = subprocess.run(["dpkg", "-S", f"*/{soname}"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        pkg = line.split(":", 1)[0].split(",")[0].strip()
        if pkg and not pkg.endswith("-dev"):
            return pkg.removesuffix("t64")  # nome «classico»: quello nuovo lo fornisce comunque
    row = LIBS.get(soname)
    return row[MANAGERS.index("apt")] if row else None


def main() -> None:
    deps = {f"libc6 (>= {GLIBC_MIN})"}
    missing = []
    for soname in open(sys.argv[1]).read().split():
        pkg = package_for(soname)
        if pkg:
            deps.add(pkg)
        else:
            missing.append(soname)
    if missing:  # una dipendenza mancante romperebbe l'installazione: meglio fermare la build
        sys.exit("Errore: nessun pacchetto Debian noto per " + ", ".join(missing) +
                 " (installale sulla macchina di build o aggiungile a helpix.sysdeps.LIBS)")
    print(", ".join(sorted(deps)))


if __name__ == "__main__":
    main()
