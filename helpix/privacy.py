# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Filtro privacy: oscura i dati sensibili nel testo che Helpix incolla o passa a un'IA.

Si attiva e disattiva con il pulsante a forma di scudo nella barra in alto. Vale per tutto il testo che
arriva a un'IA passando da Helpix: output dei comandi, diagnosi, task passato a un'altra IA, finestra
rapida e anche quello che incolli tu (Ctrl+V nella chat, nella casella API o nel terminale degli agenti).
Non tocca quello che scrivi a mano lettera per lettera e non può oscurare gli screenshot.

Lo stesso dato riceve sempre lo stesso segnaposto per tutta la sessione ([IP-1], [EMAIL-2]…), così l'IA
capisce ancora che due righe parlano della stessa macchina o dello stesso indirizzo.
"""
from __future__ import annotations

import getpass
import ipaddress
import re
import socket
from collections import Counter
from typing import Callable

from .i18n import tr

# nomi host che non dicono nulla di chi usa il PC (e che compaiono anche come nome della distro)
_GENERIC_HOSTS = {
    "localhost", "localhost.localdomain", "fedora", "ubuntu", "debian", "archlinux", "arch", "linux",
    "opensuse", "suse", "rhel", "centos", "rocky", "almalinux", "alma", "mint", "pop-os", "manjaro",
    "endeavouros", "nixos", "kali", "host", "computer", "pc", "workstation", "steamdeck", "bazzite",
}
_GENERIC_USERS = {"root", "user", "admin", "test", "guest", "liveuser", "deck"}
_UNIT_SUFFIXES = (".service", ".socket", ".timer", ".target", ".mount", ".path", ".slice", ".scope",
                  ".device", ".swap", ".automount")
_HARMLESS_VALUES = {"true", "false", "yes", "no", "none", "null", "required", "optional", "on", "off",
                    "enabled", "disabled", "auto", "default", "unset", "n/a",
                    # nsswitch.conf («passwd: files systemd») e architetture dei pacchetti («passwd:amd64»)
                    "files", "systemd", "sss", "compat", "ldap", "nis", "nisplus", "winbind", "db", "dns", "altfiles",
                    "amd64", "arm64", "i386", "armhf", "all", "x86_64", "aarch64", "noarch", "i686", "ppc64el",
                    "s390x", "riscv64"}
# resolver DNS pubblici famosi: non dicono nulla di chi usa il PC e servono per capire la rete
_PUBLIC_DNS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "149.112.112.112", "208.67.222.222",
               "208.67.220.220", "94.140.14.14", "94.140.15.15", "2001:4860:4860::8888", "2001:4860:4860::8844",
               "2606:4700:4700::1111", "2606:4700:4700::1001", "2620:fe::fe"}

_PEM_NAME = r"((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?|OpenVPN Static key V\d)"
_PEM = re.compile(r"-----BEGIN " + _PEM_NAME + r"-----.*?-----END \1-----", re.S)
# chiave tagliata nell'output (manca la riga END): via le righe in base64 che seguono
_PEM_CUT = re.compile(r"-----BEGIN " + _PEM_NAME + r"-----(?:\n[A-Za-z0-9+/=:, .-]*)*")
_HASH = re.compile(r"\$(?:1|2[abxy]?|5|6|y|gy|7|argon2(?:id|i|d))\$[^\s:'\"]+")
_URL_CREDS = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)([^/\s@]+)@")
_AUTH = re.compile(r"(?i)\b((?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic|token|digest)?\s*)"
                   r"(?!\[)([A-Za-z0-9._~+/=-]{8,})")
_BEARER = re.compile(r"(?i)\b(bearer\s+)(?!\[)([A-Za-z0-9._~+/=-]{16,})")
# token dei servizi: (parola che deve comparire nel testo, espressione). La parola fa saltare subito le regole
# che non c'entrano: con un'unica espressione da 25 alternative 1 MB di log richiedeva quasi 2 secondi.
_TOKEN_RULES = [(hint, re.compile(rx)) for hint, rx in [
    ("sk-", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("sk-", r"\bsk-(?:proj-|live-|test-|svcacct-)?[A-Za-z0-9_-]{20,}"),
    ("gh", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    ("github_pat_", r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("glpat-", r"\bglpat-[A-Za-z0-9_-]{20,}"),
    ("xox", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("IA", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("AIza", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("eyJ", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("k_", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),                  # Stripe
    ("hooks.slack.com", r"(?<=hooks\.slack\.com/services/)[A-Za-z0-9/]{20,}"),
    ("/api/webhooks/", r"(?<=/api/webhooks/)\d+/[A-Za-z0-9_-]{20,}"),      # Discord
    (":AA", r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}"),                             # bot Telegram
    ("hf_", r"\bhf_[A-Za-z0-9]{30,}"),                                        # Hugging Face
    ("npm_", r"\bnpm_[A-Za-z0-9]{30,}"),
    ("pypi-", r"\bpypi-[A-Za-z0-9_-]{40,}"),
    ("SG.", r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{30,}"),               # SendGrid
    ("ya29.", r"\bya29\.[A-Za-z0-9_-]{20,}"),                                # Google OAuth
    ("1//0", r"\b1//0[A-Za-z0-9_-]{30,}"),
    ("gsk_", r"\bgsk_[A-Za-z0-9]{40,}"),
    ("r8_", r"\br8_[A-Za-z0-9]{30,}"),
    ("dop_v1_", r"\bdop_v1_[a-f0-9]{64}"),
    ("shp", r"\bshp(?:at|ss|ca|pa)_[a-fA-F0-9]{32}"),
    ("key-", r"\bkey-[0-9a-f]{32}\b"),                                       # Mailgun
]]
_COOKIE = re.compile(r"(?im)^(\s*(?:set-)?cookie\s*:\s*)(?![\[\s])(.+?)\s*$")
_URL_QUERY = re.compile(r"(?i)([?&](?:sig|signature|access_token|refresh_token|id_token|token|code|client_secret|"
                        r"api_?key|key|password|passwd|pass|pwd|auth|secret|sharedaccesssignature)=)(?!\[)"
                        r"([^&\s#'\"]+)")
_XML_SECRET = re.compile(r"(?i)(<(password|passwd|pwd|secret|token|api_?key|apikey|private_?key|access_?key|"
                         r"client_?secret|psk)>)(?!\[)([^<]+)(</\2>)")
_KV_HINTS = ("pass", "secret", "token", "key", "psk", "credential", "pwd", "sshpass")
_KEYS = (r"(?:password|passwd|passphrase|secret|client[_-]?secret|token|access[_-]?token|"
         r"refresh[_-]?token|auth[_-]?token|api[_-]?key|apikey|access[_-]?key|secret[_-]?key|private[_-]?key|"
         r"preshared[_-]?key|account[_-]?key|shared[_-]?access[_-]?key|client[_-]?key[_-]?data|"
         r"psk|wpa[_-]?psk|credentials?|pwd|pgpassword|sshpass)")
# camelCase (dbPassword, smtpPassword, adminPwd): solo con l'iniziale minuscola, così PermitEmptyPasswords no
_CAMEL = r"(?-i:[a-z][a-zA-Z0-9]*(?:Password|Passwd|Passphrase|Secret|Token|ApiKey|AccessKey|SecretKey|PrivateKey|Pwd|Psk))"
# chiave isolata o in fondo a un nome con separatore (DB_PASSWORD, wifi-sec.psk), mai dentro una parola (bypass)
# …PWD solo con un prefisso (MYSQL_PWD), mai da solo: PWD=/home/… è la cartella corrente
_KEY = r"(?<![\w.-])((?:[\w.-]*[_.-])?" + _KEYS + r"|" + _CAMEL + r")\b"
_KV_QUOTED = re.compile(r"(?i)" + _KEY + r"([\"']?[ \t]*[:=][ \t]*)([\"'])(?!\[)((?:(?!\3)[^\n])+)\3")
_KV_PLAIN = re.compile(r"(?i)" + _KEY + r"([ \t]*[:=][ \t]*)(?![\"'\[])([^\s\"',;&<>]+)")
# credenziali passate ai comandi: curl -u utente:password, mysql -pPASSWORD, sshpass -p, --password X
_CLI_USERPASS = re.compile(r"(?<!\S)((?:-u|--user)\s+['\"]?[^\s:'\"]+:)(?!\[)([^\s'\"@]+)")
_CLI_MYSQL = re.compile(r"(\bmysql(?:dump|admin|import|check)?\b[^\n]*?\s-p)(?![\s\[])([^\s'\"]+)")
_CLI_SSHPASS = re.compile(r"(\bsshpass\s+-p\s*)(['\"]?)(?!\[)([^\s'\"]+)\2")
_Q = r"(['\"]?)(?!\[)([^\s'\"]+)\2"  # valore, anche tra virgolette (gruppi 2 e 3 dopo il prefisso)
_CLI_MORE = [  # (parole che devono comparire, espressione)
    (("nmcli",), re.compile(r"(\bnmcli\b[^\n]*?\b(?:password|wifi-sec\.psk|802-11-wireless-security\.psk)\s+)" + _Q)),
    (("login",), re.compile(r"(\b(?:docker|podman|helm|buildah|skopeo|oras)\s+(?:registry\s+)?login\b[^\n]*?"
                            r"\s(?:-p|--password)\s+)" + _Q)),
    (("ldap",), re.compile(r"(\bldap\w*\b[^\n]*?\s-w\s+)" + _Q)),                      # ldapsearch -w password
    (("htpasswd",), re.compile(r"(\bhtpasswd\s+-\w*b\w*\s+(?:-\w+\s+)*\S+\s+\S+\s+)" + _Q)),  # -b file utente pw
    (("pass:",), re.compile(r"(-pass(?:in|out)?\s+pass:)" + _Q)),                          # openssl
    (("zip",), re.compile(r"(\bzip\b[^\n]*?\s-P\s+)" + _Q)),
    (("/p",), re.compile(r"(?i)((?<!\S)/p(?:th)?:)" + _Q)),                                # xfreerdp /p:password
    (("<<<",), re.compile(r"(\b(?:sudo\s+(?:-\w+\s+)*-S|chpasswd|passwd\s+--stdin)\b[^\n]*?<<<\s*)" + _Q)),
]
_CLI_SMB = re.compile(r"((?<!\S)(?:-U|--user(?:=|\s+))\s*['\"]?[^%\s'\"]+%)(?!\[)([^\s'\"]+)")
_CLI_7Z = re.compile(r"(\b7za?\b[^\n]*?\s-p)(?![\s\[])([^\s'\"]+)")
# echo 'password' | sudo -S …  /  echo 'utente:password' | chpasswd
_CLI_PIPE = re.compile(r"(\b(?:echo|printf)\s+(?:-[ne]+\s+)?)(['\"]?)(?![\[\s])([^'\"|\n]+?)\2"
                       r"(\s*\|\s*(?:sudo\s+(?:-\w+\s+)*-S|chpasswd|passwd\s+--stdin|openssl\s+passwd))")
_CLI_PASSARG = re.compile(r"(?<!\S)(--pass(?:word|phrase)?\s+)(['\"]?)(?!\[)([^\s'\"]+)\2")
_IDS = re.compile(r"(?i)\b((?:machine|boot|product)[ _-]?(?:id|uuid)\s*[:=]\s*)([0-9a-f]{8}-?[0-9a-f]{4}-?"
                  r"[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})\b")
_SERIAL = re.compile(r"(?i)\b((?:hardware\s+)?serial(?:\s*number)?\s*[:=]\s*)(?!\[)([^\s\n][^\n]*?)\s*$", re.M)
_SERIAL_GENERIC = {"not specified", "to be filled by o.e.m.", "default string", "none", "system serial number",
                   "0", "0123456789", "unknown", "n/a", "not available"}
_SSID = re.compile(r"(?im)(\b(?:[\w-]+\.)?e?ssid\s*[:=]\s*\"?)(?![\"\[\s])([^\"\n]*[^\"\s])")
_PHONE_KEY = re.compile(r"(?i)(\b(?:tel(?:efono)?|cell(?:ulare)?|phone|mobile|fax|telephonenumber|mobilephone|"
                        r"homephone)\b\.?\s*[:=]?\s*)(?!\[)(\+?\d[\d ./-]{5,}\d)")
_CF = re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_CARD = re.compile(r"\b\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,4})?\b")
_CARD_KEY = re.compile(r"(?i)(\b(?:carta|card|visa|mastercard|amex|pan|cc)\b[^\d\n]{0,20})(\d{13,19})\b")
_MAC_CISCO = re.compile(r"(?i)\b[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b")
_HOME = re.compile(r"(/(?:var/)?home/|/Users/)(?!\[)([^/\s:'\"]+)")
_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}(?:[\s.-]?\d{2,5}){2,4}\b")
_LDAP_CN = re.compile(r"(?i)\b(CN=)(?!\[)([^,=\n]+)")
_LDAP_DC = re.compile(r"(?i)\b(DC=)(?!\[)([^,=\s]+)")
_AD_CONTAINERS = {"users", "computers", "builtin", "system", "configuration", "schema", "program data",
                  "foreignsecurityprincipals", "managed service accounts", "domain users", "domain admins",
                  "domain computers", "domain controllers", "enterprise admins", "schema admins", "administrators",
                  "microsoft exchange security groups", "services", "sites", "default-first-site-name",
                  "servers", "policies", "keys", "infrastructure", "lostandfound", "ntds settings"}
# nomi di rete interni (Active Directory, rete di casa o dell'ufficio): dicono chi è il cliente
_INTERNAL_FQDN = re.compile(r"(?i)(?<![\w.@-])((?:[a-z0-9-]+\.)+(?:local|lan|internal|intranet|corp|home\.arpa|"
                            r"localdomain))\b(?![\w-])")
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_MAC = re.compile(r"(?<![\w:-])(?:[0-9A-Fa-f]{2}([:-]))(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![\w:-])")
_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?!\w|\.\d)")
_IPV6 = re.compile(r"(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:\.\d{1,3}){0,3})(?![\w:.])")

KINDS = ("key", "token", "secret", "doc", "email", "phone", "ip", "mac", "wifi", "id", "name", "domain", "user",
         "host")


def kind_label(kind: str) -> str:
    return {
        "key": tr("chiavi private"), "token": tr("token"), "secret": tr("password e segreti"),
        "email": tr("email"), "ip": tr("IP pubblici"), "mac": tr("indirizzi MAC"),
        "user": tr("nome utente"), "host": tr("nome del PC"), "phone": tr("numeri di telefono"),
        "wifi": tr("nomi di reti Wi-Fi"), "id": tr("identificativi della macchina"),
        "name": tr("nomi di persone e oggetti di Active Directory"), "domain": tr("domini interni"),
        "doc": tr("codici fiscali, IBAN e carte"),
    }.get(kind, kind)


# ------------------------------------------------------------ filtro sugli incolla
# L'app lo attiva quando lo scudo è acceso; i campi in cui si incolla (chat, casella API, terminale degli
# agenti, anteprima del passaggio di task) lo usano. on_found riceve i dati oscurati, per l'avviso.
_active: "Redactor | None" = None
_on_found: Callable[[Counter], None] | None = None


def activate(redactor: "Redactor", on_found: Callable[[Counter], None] | None = None) -> None:
    global _active, _on_found
    _active, _on_found = redactor, on_found


def deactivate() -> None:
    global _active, _on_found
    _active, _on_found = None, None


def paste_filter_active() -> bool:
    return _active is not None


def filter_paste(text: str, notify: bool = True) -> str:
    """Il testo da incollare, oscurato se lo scudo è acceso."""
    if not text or _active is None:
        return text
    try:
        clean, found = _active.redact(text)
    except Exception:  # noqa: BLE001 - un errore del filtro non deve impedire di incollare
        return text
    if found and notify and _on_found is not None:
        _on_found(found)
    return clean


def describe(found: Counter) -> str:
    """«3 dati (2 token, 1 email)» per l'avviso dopo l'incolla."""
    n = sum(found.values())
    parts = ", ".join(f"{found[k]} {kind_label(k)}" for k in KINDS if found.get(k))
    return tr("{n} dati ({parts})").format(n=n, parts=parts)


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return len(digits) >= 13 and total % 10 == 0


def _iban_ok(raw: str) -> bool:
    iban = raw.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    moved = iban[4:] + iban[:4]
    try:
        return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1
    except ValueError:
        return False


_CF_ODD = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]


def _cf_ok(cf: str) -> bool:
    """Carattere di controllo del codice fiscale italiano."""
    total = 0
    for i, c in enumerate(cf[:15]):
        v = int(c) if c.isdigit() else ord(c) - 65
        total += _CF_ODD[v] if i % 2 == 0 else v
    return chr(65 + total % 26) == cf[15]


def _os_id() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


_HINT_CACHE: dict = {}


def _hint_rx(hints: tuple) -> "re.Pattern":
    rx = _HINT_CACHE.get(hints)
    if rx is None:
        rx = _HINT_CACHE[hints] = re.compile("|".join(re.escape(h) for h in hints), re.I)
    return rx


class Redactor:
    """Oscura i dati sensibili; i segnaposti numerati restano gli stessi finché vive l'oggetto."""

    def __init__(self, hostname: str | None = None, username: str | None = None):
        if hostname is None:
            try:
                hostname = socket.gethostname()
            except OSError:
                hostname = ""
        if username is None:
            try:
                username = getpass.getuser()
            except Exception:  # noqa: BLE001 - utente senza nome (container)
                username = ""
        host = (hostname or "").strip()
        generic = _GENERIC_HOSTS | {_os_id()}
        names = {host, host.split(".")[0]} if host else set()
        self.hosts = sorted((h for h in names if len(h) >= 3 and h.lower() not in generic), key=len, reverse=True)
        self.user = username if username and len(username) >= 2 and username not in _GENERIC_USERS else ""
        self._seen: dict[tuple[str, str], str] = {}
        self._count: Counter = Counter()

    # ------------------------------------------------------------ segnaposti
    def _placeholder(self, kind: str, original: str, label: str, numbered: bool) -> str:
        if not numbered:
            return f"[{label}]"
        key = (kind, original.lower())
        if key not in self._seen:
            self._count[kind] += 1
            self._seen[key] = f"[{label}-{self._count[kind]}]"
        return self._seen[key]

    # ------------------------------------------------------------ filtro
    def redact(self, text: str) -> tuple[str, Counter]:
        found: Counter = Counter()
        if not text:
            return text, found

        def sub(rx, kind, repl, hints=None, per_line=False):
            """Applica una regola. hints: parole (minuscole) senza le quali la regola non può trovare nulla;
            per_line: regola che lavora su una riga sola → solo sulle righe che contengono una di quelle parole."""
            nonlocal text
            if hints is not None:
                low = text.lower()
                if not any(h in low for h in hints):
                    return

            def fn(m):
                out = repl(m)
                if out != m.group(0):
                    found[kind] += 1
                return out
            if not (hints and per_line):
                text = rx.sub(fn, text)
                return
            # solo le righe dove compare una delle parole: le trovo con una ricerca sola su tutto il testo
            spans, last_end = [], -1
            for hit in _hint_rx(hints).finditer(text):
                if hit.start() < last_end:
                    continue
                start = text.rfind("\n", 0, hit.start()) + 1
                end = text.find("\n", hit.end())
                last_end = len(text) if end < 0 else end
                spans.append((start, last_end))
            if not spans:
                return
            parts, pos = [], 0
            for start, end in spans:
                parts += [text[pos:start], rx.sub(fn, text[start:end])]
                pos = end
            parts.append(text[pos:])
            text = "".join(parts)

        key_label = "[" + tr("CHIAVE-PRIVATA") + "]"
        sub(_PEM, "key", lambda m: key_label, hints=("-----begin",))
        sub(_PEM_CUT, "key", lambda m: key_label, hints=("-----begin",))
        sub(_HASH, "secret", lambda m: "[HASH]", hints=("$",))
        sub(_COOKIE, "token", lambda m: m.group(1) + "[COOKIE]", hints=("cookie",))
        sub(_URL_QUERY, "secret", lambda m: m.group(1) + "[" + tr("SEGRETO") + "]")
        sub(_XML_SECRET, "secret", lambda m: m.group(1) + "[" + tr("SEGRETO") + "]" + m.group(4), hints=("</",))
        sub(_URL_CREDS, "secret", lambda m: m.group(1) + "[" + tr("SEGRETO") + "]@")
        sub(_AUTH, "token", lambda m: m.group(1) + "[TOKEN]")
        sub(_BEARER, "token", lambda m: m.group(1) + "[TOKEN]")
        for hint, rx in _TOKEN_RULES:
            if hint in text:
                sub(rx, "token", lambda m: "[TOKEN]")

        def kv_quoted(m):
            if m.group(4).strip().lower() in _HARMLESS_VALUES:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{m.group(3)}[{tr('SEGRETO')}]{m.group(3)}"

        def kv_plain(m):
            value = m.group(3)
            if value.lower() in _HARMLESS_VALUES or len(value) < 3 or set(value) <= {"*", "x", "X", "•"}:
                return m.group(0)
            if m.group(1).lower() == "pwd" and value.startswith(("/", "~")):
                return m.group(0)  # PWD=/home/…: è la cartella corrente, non una password
            if value.startswith(("$", "{", "%", "<")) or "(" in value:
                return m.group(0)  # $VARIABILE, {{ modello }}, chiamata di funzione: il segreto non è qui
            rest = m.string[m.end():m.end() + 20]
            if ":" in m.group(2) and "-" in m.group(1) and re.match(r" [a-z]{3,}", rest):
                return m.group(0)  # «dpkg: base-passwd: dependency problems»: un pacchetto in una frase
            if m.group(1).lower().endswith(("credentials", "credential")) and value.startswith(("/", "~")):
                return m.group(0)  # credentials=/percorso/del/file: il percorso non è il segreto
            return f"{m.group(1)}{m.group(2)}[{tr('SEGRETO')}]"
        secret = "[" + tr("SEGRETO") + "]"
        sub(_CLI_USERPASS, "secret", lambda m: m.group(1) + secret)
        sub(_CLI_MYSQL, "secret", lambda m: m.group(1) + secret, hints=("mysql",))
        sub(_CLI_SSHPASS, "secret", lambda m: f"{m.group(1)}{m.group(2)}{secret}{m.group(2)}", hints=("sshpass",))
        sub(_CLI_PASSARG, "secret", lambda m: f"{m.group(1)}{m.group(2)}{secret}{m.group(2)}", hints=("--pass",))
        for hints, rx in _CLI_MORE:
            sub(rx, "secret", lambda m: f"{m.group(1)}{m.group(2)}{secret}{m.group(2)}", hints=hints, per_line=True)
        sub(_CLI_SMB, "secret", lambda m: m.group(1) + secret, hints=("%",))
        sub(_CLI_7Z, "secret", lambda m: m.group(1) + secret, hints=("7z",))
        sub(_CLI_PIPE, "secret", lambda m: f"{m.group(1)}{m.group(2)}{secret}{m.group(2)}{m.group(4)}", hints=("|",))
        sub(_KV_QUOTED, "secret", kv_quoted, hints=_KV_HINTS, per_line=True)
        sub(_KV_PLAIN, "secret", kv_plain, hints=_KV_HINTS, per_line=True)
        sub(_IDS, "id", lambda m: m.group(1) + "[ID]", hints=("id",), per_line=True)

        def serial(m):
            if m.group(2).strip().lower() in _SERIAL_GENERIC:
                return m.group(0)
            return m.group(1) + "[" + tr("SERIALE") + "]"
        sub(_SERIAL, "id", serial, hints=("serial",), per_line=True)

        def ssid(m):
            if m.group(2).strip().lower() in ("--", "off/any", "off", "any", ""):
                return m.group(0)
            return m.group(1) + self._placeholder("wifi", m.group(2), "WIFI", True)
        sub(_SSID, "wifi", ssid, hints=("ssid",), per_line=True)
        def doc(label, check):
            def fn(m):
                raw = m.group(0)
                return "[" + label + "]" if check(raw) else raw
            return fn
        sub(_CF, "doc", doc(tr("CODICE-FISCALE"), _cf_ok))
        sub(_IBAN, "doc", doc("IBAN", _iban_ok))
        sub(_CARD, "doc", doc(tr("CARTA"), lambda raw: _luhn(re.sub(r"\D", "", raw))))
        sub(_CARD_KEY, "doc", lambda m: m.group(1) + "[" + tr("CARTA") + "]" if _luhn(m.group(2)) else m.group(0), hints=("carta", "card", "visa", "mastercard", "amex", "pan", "cc"), per_line=True)
        sub(_PHONE_KEY, "phone", lambda m: m.group(1) + self._placeholder(
            "phone", re.sub(r"\D", "", m.group(2)), tr("TELEFONO"), True),
            hints=("tel", "cell", "phone", "mobile", "fax"), per_line=True)
        sub(_PHONE, "phone", lambda m: self._placeholder("phone", re.sub(r"\D", "", m.group(0)),
                                                         tr("TELEFONO"), True))

        def cn(m):
            name = m.group(2).strip()
            if name.lower() in _AD_CONTAINERS:
                return m.group(0)
            return m.group(1) + self._placeholder("name", name, tr("NOME"), True)
        sub(_LDAP_CN, "name", cn, hints=("cn=",))
        sub(_LDAP_DC, "domain", lambda m: m.group(1) + self._placeholder("domain", m.group(2), tr("DOMINIO"), True), hints=("dc=",))

        def email(m):
            addr = m.group(0)
            if addr.lower().endswith(_UNIT_SUFFIXES):  # user@1000.service non è un'email
                return addr
            return self._placeholder("email", addr, "EMAIL", True)
        sub(_EMAIL, "email", email)

        def internal(m):
            name = m.group(1)
            before = m.string[max(0, m.start() - 2):m.start()]
            if name.lower() in ("localhost.localdomain",) or (before.endswith("/") and before != "//"):
                return name  # /etc/qualcosa.local è un file, //server.local/condivisione è un server
            return self._placeholder("domain", name, tr("DOMINIO"), True)
        sub(_INTERNAL_FQDN, "domain", internal, hints=(".local", ".lan", ".internal", ".intranet", ".corp", ".home.arpa", ".localdomain"))

        def mac(m):
            v = m.group(0).lower().replace("-", ":")
            if v in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                return m.group(0)
            return self._placeholder("mac", v, "MAC", True)
        sub(_MAC, "mac", mac)
        sub(_MAC_CISCO, "mac", lambda m: self._placeholder("mac", m.group(0).lower(), "MAC", True))

        def ipv4(m):
            try:
                ip = ipaddress.IPv4Address(m.group(1))
            except ValueError:
                return m.group(0)
            before, after = m.string[max(0, m.start() - 2):m.start()], m.string[m.end():m.end() + 1]
            tail = re.match(r"-([\w.+~]+)", m.string[m.end():m.end() + 30])
            if after in ("+", "~") or re.search(r"(?:\d:|[vV~])$", before) or (tail and re.search(r"[A-Za-z]", tail.group(1))):
                return m.group(0)  # versione di un pacchetto (8:6.9.12.98+dfsg, 5.5.2.5-2ubuntu0.1), non un indirizzo
            if not ip.is_global or ip.is_multicast or ip.is_reserved or str(ip) in _PUBLIC_DNS:
                return m.group(0)
            return self._placeholder("ip", str(ip), "IP", True)
        sub(_IPV4, "ip", ipv4)

        def ipv6(m):
            cand = m.group(1)
            if cand.count(":") < 2:
                return cand
            try:
                ip = ipaddress.IPv6Address(cand)
            except ValueError:
                return cand
            if ip.ipv4_mapped is not None or not ip.is_global or ip.is_site_local or ip.is_multicast \
                    or str(ip) in _PUBLIC_DNS:
                return cand
            return self._placeholder("ip", str(ip), "IP", True)
        sub(_IPV6, "ip", ipv6)

        label = "[" + tr("UTENTE") + "]"

        def home(m):  # la tua cartella → [UTENTE]; quelle di altri utenti → [UTENTE-n]
            name = m.group(2)
            if name.lower() in _GENERIC_USERS | {"username", "utente", "nome", "your_user", "yourname"}:
                return m.group(0)
            if self.user and name == self.user:
                return m.group(1) + label
            return m.group(1) + self._placeholder("user", name, tr("UTENTE"), True)
        sub(_HOME, "user", home)
        if self.user:
            u = re.escape(self.user)
            sub(re.compile(r"(?m)^" + u + r"(?=:)"), "user", lambda m: label)  # /etc/passwd, /etc/shadow
            sub(re.compile(r"(?<![\w.-])" + u + r"(?=@)"), "user", lambda m: label)
            sub(re.compile(r"(?i)\b((?:user(?:name)?|logname|login)\s*[=:]\s*)" + u + r"\b"), "user",
                lambda m: m.group(1) + label)
            # log di sudo («crash : TTY=pts/1 ; …»), sshd e pam («for user crash», «user crash(uid=1000)»), id
            sub(re.compile(r"(?<![\w.-])" + u + r"(?=\s*:\s*(?:TTY|PWD|USER|COMMAND)=)"), "user", lambda m: label)
            sub(re.compile(r"(?i)(\b(?:for|by)\s+(?:invalid\s+)?user\s+|\buser\s+)" + u + r"(?![\w.-])"), "user",
                lambda m: m.group(1) + label)
            sub(re.compile(r"(\d\()" + u + r"(?=\))"), "user", lambda m: m.group(1) + label)  # id, groups
            sub(re.compile(r"(\bfor\s+)" + u + r"(?=\s+from\b)"), "user", lambda m: m.group(1) + label)  # sshd
            sub(re.compile(r"(\bby\s+)" + u + r"(?=\(uid=)"), "user", lambda m: m.group(1) + label)  # pam
        for host in self.hosts:
            sub(re.compile(r"(?i)(?<![\w.-])" + re.escape(host) + r"(?![\w-])"), "host", lambda m: "[HOST]")
        return text, found


def redact(text: str) -> str:
    """Comodità per un solo testo (segnaposti numerati solo all'interno di questo testo)."""
    return Redactor().redact(text)[0]
