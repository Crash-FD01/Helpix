# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Uscita immediata dei test, uguale su Linux e Windows.

Su Windows os._exit esegue ancora le routine di chiusura delle DLL: con il motore web di Qt caricato e non
smontato (i test escono a metà) può andare in crash dopo che il test è già riuscito. TerminateProcess le salta.
"""
import os
import sys

if sys.platform == "win32":  # preparato subito: fra la fine del test e l'uscita non deve passare tempo
    import ctypes
    _kernel32 = ctypes.windll.kernel32
    _process = _kernel32.GetCurrentProcess()


def now(code: int = 0) -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        _kernel32.TerminateProcess(_process, code)
    os._exit(code)
