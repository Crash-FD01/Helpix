# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Righe «Requires:» dello spec RPM dalle librerie richieste (sonames.txt).

RPM risolve le dipendenze per nome della libreria (es. «libxcb-cursor.so.0()(64bit)»): funziona allo stesso
modo su Fedora, RHEL e openSUSE, qualunque sia il nome del pacchetto che la contiene.
"""
import os
import sys

GLIBC_MIN = os.environ.get("GLIBC_MIN", "2.34")  # calcolata da build-packages.sh (needed_libs.py --glibc)


def main() -> None:
    arch = sys.argv[2]
    suffix = "()(64bit)" if arch in ("x86_64", "aarch64") else ""
    # glibc minima come pacchetto: Fedora, RHEL e openSUSE lo chiamano tutti «glibc». (Il simbolo versionato
    # «libc.so.6(GLIBC_2.34)(64bit)» in 0.15.0 non era fornito da glibc su Fedora 44 e dnf rifiutava il pacchetto.)
    lines = [f"Requires:       glibc >= {GLIBC_MIN}"]
    for soname in open(sys.argv[1]).read().split():
        lines.append(f"Requires:       {soname}{suffix}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
