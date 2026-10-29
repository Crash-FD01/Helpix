# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Punto di ingresso di Helpix.exe (PyInstaller): lo stesso di «python -m helpix»."""
import sys

from helpix.app import main

if __name__ == "__main__":
    sys.exit(main())
