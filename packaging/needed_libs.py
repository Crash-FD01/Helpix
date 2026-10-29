# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Librerie di sistema richieste dai file inclusi nel pacchetto (una per riga).

Guarda i moduli di Qt che Helpix usa davvero (gli stessi di helpix.sysdeps: niente driver SQL, Qt3D…),
il Python incluso e le estensioni compilate delle altre librerie Python. Le librerie che il pacchetto
porta con sé e quelle di glibc non contano: glibc c'è sempre (la versione minima la fissano i pacchetti).

Uso: python needed_libs.py <radice del pacchetto> [--glibc]
     con --glibc stampa invece la versione minima di glibc richiesta (la più alta tra i simboli GLIBC_x.y usati).
"""
import glob
import os
import re
import subprocess
import sys

GLIBC = re.compile(r"^(libc|libm|libdl|libpthread|librt|libutil|libresolv|libcrypt|libanl|ld-linux[\w.-]*)\.so")


def needed(path: str) -> list[str]:
    try:
        out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)


def glibc_versions(path: str) -> list[tuple[int, ...]]:
    try:
        out = subprocess.run(["readelf", "-V", "-W", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [tuple(int(x) for x in v.split(".")) for v in re.findall(r"Name: GLIBC_([0-9.]+)\b", out)]


def is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def main() -> None:
    root = sys.argv[1]
    app = os.path.join(root, "opt", "helpix")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from helpix import sysdeps

    qt = glob.glob(os.path.join(app, "venv", "lib", "python3.*", "site-packages", "PySide6", "Qt"))[0]
    files = set(sysdeps.qt_binaries(qt))
    for path in glob.glob(os.path.join(app, "**", "*"), recursive=True):
        if os.path.isfile(path) and is_elf(path) and "/PySide6/Qt/" not in path:
            files.add(path)  # Python, i suoi moduli e le estensioni (cryptography, cffi…)
    provided = {os.path.basename(p) for p in glob.glob(os.path.join(app, "**", "*.so*"), recursive=True)}
    if "--glibc" in sys.argv:
        best = max((v for f in files for v in glibc_versions(f)), default=(2, 17))
        print(".".join(map(str, best)))
        return
    wanted: set[str] = set()
    for f in files:
        wanted.update(needed(f))
    for soname in sorted(wanted):
        if "/" in soname:  # percorso relativo ($ORIGIN/…): è un file del pacchetto
            continue
        if soname not in provided and not GLIBC.match(soname) and not soname.startswith(("libQt6", "libpyside6",
                                                                                          "libshiboken6")):
            print(soname)


if __name__ == "__main__":
    main()
