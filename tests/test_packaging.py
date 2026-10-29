# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dipendenze del pacchetto .deb: solo librerie di sistema, mai programmi che ne includono una copia."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))
import deb_depends  # noqa: E402


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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
