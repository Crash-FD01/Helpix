# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dipendenze del pacchetto .deb: solo librerie di sistema, mai programmi che ne includono una copia."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))
import deb_depends  # noqa: E402
import rpm_requires  # noqa: E402


def test_only_system_library_paths():
    # 0.15.0: su GitHub Actions libnspr4.so era trovata anche dentro Firefox e il .deb dipendeva da firefox
    for path, ok in (("/usr/lib/x86_64-linux-gnu/libnspr4.so", True), ("/lib/aarch64-linux-gnu/libz.so.1", True),
                     ("/usr/lib/firefox/libnspr4.so", False), ("/usr/lib/thunderbird/libnss3.so", False),
                     ("/snap/firefox/1/usr/lib/x86_64-linux-gnu/libnss3.so", False),
                     ("/usr/lib/x86_64-linux-gnu/nss/libsoftokn3.so", False)):
        assert bool(deb_depends.SYSTEM_LIB.match(path)) == ok, path


def test_dependencies_are_libraries():
    for name, ok in (("libnspr4", True), ("libstdc++6", True), ("zlib1g", True), ("libglib2.0-0", True),
                     ("firefox", False), ("snapd", False), ("thunderbird", False)):
        assert bool(deb_depends.LIBRARY_PACKAGE.match(name)) == ok, name


def test_rpm_requires_glibc_by_package():
    # 0.15.2: «libc.so.6(GLIBC_2.34)(64bit)» non è fornito da glibc su Fedora 44 → dnf rifiutava il pacchetto
    import io
    import tempfile
    from contextlib import redirect_stdout
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("libxcb-cursor.so.0\nlibnss3.so\n")
    argv, out = sys.argv, io.StringIO()
    try:
        sys.argv = ["rpm_requires.py", f.name, "x86_64"]
        with redirect_stdout(out):
            rpm_requires.main()
    finally:
        sys.argv = argv
        os.unlink(f.name)
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("Requires:") and "glibc >= " in lines[0], lines
    assert not any("GLIBC_" in line for line in lines), lines
    assert "Requires:       libxcb-cursor.so.0()(64bit)" in lines, lines


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
