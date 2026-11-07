# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Password del vault: robustezza, frasi casuali e codici usa e getta.

Regole come quelle del NIST (SP 800-63B): conta la lunghezza, non l'obbligo di maiuscole e simboli; si
rifiutano le password comuni, ripetitive o in sequenza; nessuna scadenza. La stima della robustezza è
indicativa (bit di entropia approssimati), serve a guidare la scelta.
"""
from __future__ import annotations

import math
import re
import secrets
from functools import lru_cache
from pathlib import Path

from .i18n import tr

MIN_LENGTH = 12
CODE_WORDS = 6
CODE_COUNT = 8
WORDLIST = Path(__file__).resolve().parent / "data" / "parole-it.txt"

# le più usate in assoluto e quelle «italiane» più frequenti: bastano per i casi peggiori (il resto lo fanno
# lunghezza, ripetizioni e sequenze)
_COMMON = {
    "password", "passw0rd", "password1", "password123", "123456", "1234567", "12345678", "123456789",
    "1234567890", "qwerty", "qwertyuiop", "asdfghjkl", "zxcvbnm", "iloveyou", "admin", "administrator",
    "welcome", "letmein", "monkey", "dragon", "football", "baseball", "superman", "batman", "trustno1",
    "sunshine", "princess", "starwars", "whatever", "shadow", "master", "michael", "jennifer", "helpix",
    "ciao", "ciaociao", "amore", "amoremio", "tiamo", "juventus", "napoli", "milan", "inter", "roma",
    "lazio", "forzainter", "forzajuve", "forzamilan", "francesco", "alessandro", "andrea", "giuseppe",
    "antonio", "giovanni", "marco", "luca", "matteo", "lorenzo", "federica", "giulia", "chiara", "martina",
    "sara", "valentina", "francesca", "stella", "tesoro", "cucciolo", "passwordsegreta", "segreto",
    "cambiami", "cambiala", "prova", "prova123", "test", "test123", "qwerty123", "abc123", "abcdef",
}
_ROWS = ("qwertyuiopasdfghjklzxcvbnm", "1234567890", "abcdefghijklmnopqrstuvwxyz")


@lru_cache(maxsize=1)
def words() -> tuple[str, ...]:
    with open(WORDLIST, encoding="utf-8") as fh:
        items = [w.strip() for w in fh if w.strip() and not w.startswith("#")]
    return tuple(dict.fromkeys(items))


def generate_code(n: int = CODE_WORDS) -> str:
    wl = words()
    return "-".join(secrets.choice(wl) for _ in range(n))


def generate_codes(count: int = CODE_COUNT, n: int = CODE_WORDS) -> list[str]:
    codes: list[str] = []
    while len(codes) < count:
        c = generate_code(n)
        if c not in codes:
            codes.append(c)
    return codes


def generate_passphrase(n: int = 6) -> str:
    """Frase di parole casuali: facile da ricordare, molto robusta (circa 11 bit per parola)."""
    return generate_code(n)


def code_bits(n: int = CODE_WORDS) -> float:
    return n * math.log2(len(words()))


def _sequence(text: str) -> bool:
    """Tutta in sequenza sulla tastiera o nell'alfabeto («abcdef», «654321», «qwerty»)."""
    low = text.lower()
    if len(low) < 4:
        return False
    for row in _ROWS:
        if low in row or low in row[::-1]:
            return True
    return False


def _repeated(text: str) -> bool:
    """Un pezzo ripetuto («abcabcabc», «aaaaaaa»)."""
    n = len(text)
    for size in range(1, n // 2 + 1):
        if n % size == 0 and text[:size] * (n // size) == text:
            return True
    return False


def estimate_bits(password: str) -> float:
    if not password:
        return 0.0
    parts = [p for p in re.split(r"[\s\-_.,;:]+", password.lower()) if p]
    wl = set(words())
    if len(parts) >= 3 and all(p in wl for p in parts):  # frase di parole dell'elenco
        return len(parts) * math.log2(len(wl))
    pool = 0
    if re.search(r"[a-z]", password):
        pool += 26
    if re.search(r"[A-Z]", password):
        pool += 26
    if re.search(r"[0-9]", password):
        pool += 10
    if re.search(r"[^A-Za-z0-9]", password):
        pool += 33
    # i caratteri ripetuti valgono meno: lunghezza efficace = distinti + un terzo dei ripetuti
    distinct = len(set(password))
    eff = distinct + (len(password) - distinct) / 3
    bits = eff * math.log2(max(pool, 2))
    if re.fullmatch(r"[A-Za-z]+[0-9]{1,4}[!?.]?", password):  # «Parola2024!»: lo schema più indovinato
        bits *= 0.6
    return bits


def check(password: str) -> dict:
    """{"ok": bool, "level": 0-4, "bits": float, "message": str} per la password scelta."""
    pw = password or ""
    low = re.sub(r"[^a-z0-9]", "", pw.lower())
    bits = estimate_bits(pw)
    if len(pw) < MIN_LENGTH:
        return {"ok": False, "level": 0, "bits": bits,
                "message": tr("Almeno {n} caratteri: conta la lunghezza, non i simboli.").format(n=MIN_LENGTH)}
    if pw.lower() in _COMMON or low in _COMMON or any(low == c + d for c in _COMMON for d in ("", "1", "12", "123")):
        return {"ok": False, "level": 0, "bits": bits, "message": tr("È una password troppo comune.")}
    if _repeated(pw) or _sequence(pw) or len(set(pw)) <= 3:
        return {"ok": False, "level": 0, "bits": bits,
                "message": tr("Troppo ripetitiva o in sequenza: è facile da indovinare.")}
    if any(c in low for c in ("password", "qwerty", "123456")) and bits < 70:
        return {"ok": False, "level": 1, "bits": bits,
                "message": tr("Contiene una sequenza molto comune: allungala o usa «Genera».")}
    if bits < 50:
        return {"ok": False, "level": 1, "bits": bits,
                "message": tr("Ancora debole: allungala, per esempio con qualche parola in più.")}
    if bits < 65:
        return {"ok": True, "level": 2, "bits": bits, "message": tr("Discreta.")}
    if bits < 80:
        return {"ok": True, "level": 3, "bits": bits, "message": tr("Buona.")}
    return {"ok": True, "level": 4, "bits": bits, "message": tr("Ottima.")}
