# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Motore Web: la chat ufficiale del servizio scelto, dentro Helpix, con il tuo account.

Helpix agisce solo quando premi un pulsante:
- incolla uno screenshot o un testo nel campo in cui stai scrivendo (come Ctrl+V);
- si accorge quando copi un comando (dagli appunti) e ti propone di eseguirlo;
- «Chiedi il riepilogo» (unica eccezione al non inviare e non leggere): invia quel messaggio e
  legge dalla risposta solo il blocco del riepilogo HELPIX-TASK.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QStackedWidget, QVBoxLayout, QWidget

from .. import site_icons
from .external_page import ExternalPage
from ..config import DATA_DIR
from ..i18n import tr

log = logging.getLogger(__name__)

try:
    from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEnginePermission, QWebEngineProfile,
                                         QWebEngineScript, QWebEngineSettings)
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE = True
except ImportError:  # pacchetto PySide6-WebEngine non installato
    WEBENGINE = False

WEB_SITES: dict[str, dict] = {
    "chatgpt": {"label": "ChatGPT", "url": "https://chatgpt.com/", "who": "OpenAI",
                "note": tr("Gratis, Plus o Pro")},
    "claude": {"label": "Claude", "url": "https://claude.ai/new", "who": "Anthropic",
               "note": tr("Gratis, Pro o Max")},
    "gemini": {"label": "Gemini", "url": "https://gemini.google.com/app", "who": "Google",
               "note": tr("Account Google · si apre nel tuo browser")},
    "copilot": {"label": "Copilot", "url": "https://copilot.microsoft.com/", "who": "Microsoft",
                "note": tr("Account Microsoft")},
    "deepseek": {"label": "DeepSeek", "url": "https://chat.deepseek.com/", "who": "DeepSeek",
                 "note": tr("Account DeepSeek")},
}

# Porta il cursore nel campo di testo della chat se non c'è già. Gira in un "mondo" isolato:
# la pagina non lo vede e lo script non legge alcun contenuto, controlla solo il focus.
_FOCUS_JS = r"""
(function () {
  const editable = e => e && (e.isContentEditable || e.tagName === 'TEXTAREA' ||
      (e.tagName === 'INPUT' && /^(text|search)$/i.test(e.type)));
  if (editable(document.activeElement)) return 'ok';
  const fields = [...document.querySelectorAll('textarea, [contenteditable="true"], [contenteditable=""]')]
      .filter(e => e.offsetParent !== null);
  if (!fields.length) return 'none';
  fields[fields.length - 1].focus();
  return 'focused';
})();
"""

# Incolla un'immagine o un testo nella casella della chat come farebbe Ctrl+V: un evento «paste»
# con i dati dentro, senza passare dagli appunti (che su Wayland non funzionano se la finestra
# non ha ancora il focus, ad esempio subito dopo uno screenshot). Gira nel mondo isolato e non
# legge nulla della pagina: cerca solo la casella. Risultato: pasted / unhandled / none.
_INSERT_JS = r"""
(function (p) {
  const editable = e => e && (e.isContentEditable || e.tagName === 'TEXTAREA' ||
      (e.tagName === 'INPUT' && /^(text|search)$/i.test(e.type)));
  const visible = e => e && e.isConnected && e.getClientRects().length > 0;
  let el = document.activeElement;
  if (!editable(el) || !visible(el)) {
    const fields = [...document.querySelectorAll('textarea, [contenteditable="true"], [contenteditable=""]')]
        .filter(visible);
    el = fields[fields.length - 1];
    if (!el) return 'none';
    el.focus();
    if (el.isContentEditable) {
      const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    }
  }
  const dt = new DataTransfer();
  if (p.kind === 'image') {
    const bin = atob(p.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    dt.items.add(new File([bytes], p.name, { type: p.mime }));
  } else {
    dt.setData('text/plain', p.text);
  }
  const paste = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
  if (!el.dispatchEvent(paste)) return 'pasted';   // l'editor della pagina l'ha gestito
  if (p.kind !== 'image') return document.execCommand('insertText', false, p.text) ? 'pasted' : 'unhandled';
  const drop = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true });
  if (!el.dispatchEvent(drop)) return 'pasted';
  const input = [...document.querySelectorAll('input[type="file"]')]
      .find(i => !i.disabled && (!i.accept || /image|\*/.test(i.accept)));
  if (input) {
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return 'pasted';
  }
  return 'unhandled';
})(%s);
"""

# Invia il messaggio appena incollato: il pulsante di invio del sito, altrimenti il tasto Invio.
_SEND_JS = r"""
(function () {
  const visible = e => e && e.isConnected && e.getClientRects().length > 0;
  const sels = ['button[data-testid="send-button"]', '#composer-submit-button', 'button[aria-label="Send message"]',
                'button[aria-label="Invia messaggio"]', 'button[aria-label*="Send" i]', 'button[aria-label*="Invia" i]',
                'button[aria-label*="Submit" i]', 'button.send-button'];
  for (const sel of sels) {
    const b = [...document.querySelectorAll(sel)].filter(visible).find(x => !x.disabled &&
        x.getAttribute('aria-disabled') !== 'true');
    if (b) { b.click(); return 'clicked'; }
  }
  const el = document.activeElement;
  if (!el) return 'none';
  for (const type of ['keydown', 'keypress', 'keyup']) {
    el.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                                              bubbles: true, cancelable: true }));
  }
  return 'enter';
})();
"""

# Cerca nella pagina il riepilogo scritto dall'IA: l'ultimo blocco di codice che inizia con il
# marcatore e ha i campi compilati (la richiesta stessa ha i campi vuoti). busy = l'IA sta ancora
# scrivendo (pulsante «Stop» visibile).
_SUMMARY_JS = r"""
(function (marker) {
  const texts = [...document.querySelectorAll('pre, code')].map(e => (e.innerText || e.textContent || '').trim())
      .filter(t => t.startsWith(marker));
  let found = '';
  for (let i = texts.length - 1; i >= 0; i--) {
    // compilato = c'è testo oltre alle etichette («Problema:» vuote nella richiesta), sulla stessa riga
    // («Problema: testo») o a capo («Problema:» e il testo sotto, come scrive spesso Claude)
    const lines = texts[i].split('\n').slice(1).map(l => l.trim()).filter(l => l);
    const filled = lines.filter(l => !/^[^:]{2,80}:$/.test(l)).length;
    if (filled >= 2) { found = texts[i]; break; }
  }
  const busy = !!document.querySelector('[data-testid="stop-button"], button[aria-label*="Stop" i], ' +
                                         'button[aria-label*="Interrompi" i]');
  return JSON.stringify({ text: found, busy: busy });
})(%s);
"""

# Ultima risposta dell'assistente nella pagina (per la finestra rapida): quante risposte ci sono,
# il testo dell'ultima e se sta ancora scrivendo.
_ANSWER_JS = r"""
(function () {
  const sels = ['[data-message-author-role="assistant"]', '[data-is-streaming]', '.font-claude-response',
                '[data-testid="assistant-message"]', 'model-response message-content', 'model-response',
                '[data-content="ai-message"]', '.ds-markdown'];
  const busy = !!document.querySelector('[data-testid="stop-button"], button[aria-label*="Stop" i], ' +
                                         'button[aria-label*="Interrompi" i]');
  // solo il testo che l'utente vede nel messaggio: niente etichette per lettori di schermo
  // («Claude responded:»), pulsanti, scorciatoie, orari («just now») e barre che compaiono al passaggio
  const SKIP = 'button, [role="button"], [role="toolbar"], [role="menu"], [role="tooltip"], svg, kbd, time, ' +
               'nav, form, textarea, input, select, img, [aria-hidden="true"], .sr-only, [class*="sr-only"], ' +
               '[class*="visually-hidden"], [data-testid*="action"], [data-testid*="feedback"]';
  const BLOCK = /^(P|DIV|LI|UL|OL|PRE|H[1-6]|TR|TABLE|BLOCKQUOTE|SECTION|ARTICLE|HR)$/;
  function hidden(el) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return true;
    // testo «visivamente nascosto» (1 pixel, ritagliato)
    if (cs.position === 'absolute' && (el.offsetWidth <= 1 || el.offsetHeight <= 1)) return true;
    return cs.clip === 'rect(0px, 0px, 0px, 0px)' || cs.clipPath === 'inset(50%)';
  }
  function text(node, inPre) {
    let out = '';
    for (const child of node.childNodes) {
      if (child.nodeType === 3) { out += child.nodeValue; continue; }
      if (child.nodeType !== 1 || child.matches(SKIP) || hidden(child)) continue;
      if (child.tagName === 'BR') { out += '\n'; continue; }
      const pre = inPre || child.tagName === 'PRE';
      const inner = text(child, pre);
      if (child.tagName === 'PRE') out += '\n```\n' + inner.trim() + '\n```\n';
      else if (child.tagName === 'CODE' && !inPre) out += '`' + inner + '`';
      else if (child.tagName === 'LI') out += '\n- ' + inner.trim();
      else if (/^(UL|OL)$/.test(child.tagName)) out += '\n' + inner + '\n';
      else out += BLOCK.test(child.tagName) && !inPre ? '\n' + inner + '\n' : inner;
    }
    return out;
  }
  function body(msg) {  // la parte con il testo vero e proprio, se il sito la distingue
    const parts = [...msg.querySelectorAll('[class*="markdown"], .prose')].filter(e => !e.parentElement.closest(
        '[class*="markdown"], .prose') || !msg.contains(e.parentElement.closest('[class*="markdown"], .prose')));
    return parts.length ? parts : [msg];
  }
  for (const sel of sels) {
    const els = [...document.querySelectorAll(sel)];
    if (!els.length) continue;
    const last = els[els.length - 1];
    const raw = body(last).map(e => text(e, false)).join('\n');
    const clean = raw.replace(/ /g, ' ').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    return JSON.stringify({ count: els.length, text: clean, busy });
  }
  return JSON.stringify({ count: 0, text: '', busy });
})();
"""

# Come _FOCUS_JS, ma solo a pagina caricata: serve per incollare dopo un cambio di sito.
_READY_JS = "document.readyState === 'complete' ? " + _FOCUS_JS.strip().rstrip(";") + " : 'none'"

if WEBENGINE:
    class _Page(QWebEnginePage):
        """Apre i popup (es. «Accedi con Microsoft/Google») in una finestra separata."""

        def __init__(self, profile, parent=None, google_hook=None):
            super().__init__(profile, parent)
            self.popups: list[QDialog] = []
            self.google_hook = google_hook
            self.paste_hook = None  # scudo privacy: Incolla dal menu passa da Helpix
            self.permissionRequested.connect(self._on_permission)
            self.urlChanged.connect(self._url_changed)
            s = self.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)

        def triggerAction(self, action, checked=False):  # noqa: N802
            if action in (QWebEnginePage.WebAction.Paste, QWebEnginePage.WebAction.PasteAndMatchStyle) \
                    and self.paste_hook is not None and self.paste_hook():
                return
            super().triggerAction(action, checked)

        def _url_changed(self, url):
            # Google non permette l'accesso dai browser integrati nelle app: lo segnaliamo all'utente
            if url.host() == "accounts.google.com" and self.google_hook:
                self.google_hook()

        def _on_permission(self, permission):
            allowed = {QWebEnginePermission.PermissionType.ClipboardReadWrite}
            if permission.permissionType() in allowed:
                permission.grant()
            else:
                permission.deny()

        def createWindow(self, _type):  # noqa: N802
            dlg = QDialog(self.parent() if isinstance(self.parent(), QWidget) else None)
            dlg.setWindowTitle(tr("Helpix — Accesso"))
            dlg.resize(560, 720)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            view = QWebEngineView(dlg)
            page = _Page(self.profile(), view, self.google_hook)
            page.windowCloseRequested.connect(dlg.close)
            view.setPage(page)
            lay.addWidget(view)
            dlg.finished.connect(lambda _=0, d=dlg: self.popups.remove(d) if d in self.popups else None)
            self.popups.append(dlg)
            dlg.show()
            return page


def _image_payload(path: str, img: QImage) -> dict:
    """L'immagine così com'è su disco (PNG o JPEG già ridimensionati da normalize_image)."""
    data = Path(path).read_bytes()
    mime = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    if mime == "image/png" and data[:8] != b"\x89PNG\r\n\x1a\n":  # altri formati: converto in PNG
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(ba)
    name = Path(path).stem + (".jpg" if mime == "image/jpeg" else ".png")
    return {"kind": "image", "mime": mime, "name": name, "data": base64.b64encode(data).decode("ascii")}


class _PasteKeys(QObject):
    """Filtro dei tasti solo sulle pagine di chat: Ctrl+V / Maiusc+Ins / Ctrl+Maiusc+V con lo scudo acceso."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() != QEvent.Type.KeyPress or not WebPanel._is_paste_key(ev):
            return False
        from .. import privacy
        if not privacy.paste_filter_active():
            return False
        for view, page in list(self.panel._tabs.values()):
            if page is not None and (obj is view or obj is view.focusProxy()):
                return self.panel._filtered_paste(view, page)
        return False


class WebPanel(QWidget):
    """Una pagina per ogni servizio, tutte con lo stesso profilo (gli accessi restano salvati).

    Cambiare servizio non ricarica nulla: la chat precedente resta aperta dietro le quinte,
    così si può fare l'accesso al nuovo servizio con calma e tornare indietro in ogni momento.
    """

    hint = Signal(str)            # messaggi brevi per la barra di stato
    command_copied = Signal(str)  # l'utente ha copiato un comando di shell
    summary_copied = Signal(str)  # l'utente ha copiato il riepilogo del task scritto dall'IA
    summary_failed = Signal(str)  # riepilogo automatico non riuscito (resta la copia a mano)
    package_done = Signal(bool)   # pacchetto del task incollato (True) o casella non trovata (False)
    site_changed = Signal(str)
    google_signin = Signal(str)   # è comparsa la pagina di accesso Google nel browser integrato
    use_integrated = Signal(str)  # l'utente vuole riportare il servizio nel browser integrato
    keep_on_top = Signal()
    connect_browser = Signal()    # l'utente vuole collegare l'estensione del browser

    def __init__(self, site: str = "chatgpt", parent=None, external=()):
        super().__init__(parent)
        self.bridge = None        # BridgeServer: collegamento con l'estensione del browser
        self.site = site if site in WEB_SITES else "chatgpt"
        self.external: set[str] = set(external)  # servizi aperti nel browser di sistema
        self._last_clip = ""
        self._ignore_clipboard = False
        self._job = None
        self._tabs: dict[str, tuple] = {}     # servizio -> (view, page)
        self._loading: dict[str, bool] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        if not WEBENGINE:
            msg = QLabel(tr("Il componente browser di Qt non è installato.\n"
                         "Installa il pacchetto PySide6-WebEngine (reinstallando Helpix con install.sh) "
                         "oppure usa il motore API dalle impostazioni."))
            msg.setWordWrap(True)
            msg.setContentsMargins(24, 24, 24, 24)
            v.addWidget(msg, 1)
            self.stack = None
            return

        storage = DATA_DIR / "web"
        storage.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("helpix", self)  # profilo con nome = login che restano salvati
        self.profile.setPersistentStoragePath(str(storage / "storage"))
        self.profile.setCachePath(str(storage / "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        # è un Chromium a tutti gli effetti: togli solo il marcatore "QtWebEngine/x.y"
        self.profile.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", self.profile.httpUserAgent()))
        self.profile.downloadRequested.connect(self._download)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        QGuiApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self._paste_keys = _PasteKeys(self)  # Ctrl+V nella chat passa dallo scudo privacy
        self._ensure(self.site)
        self.stack.setCurrentWidget(self._tabs[self.site][0])

    # ------------------------------------------------------------ pagine
    def _ensure(self, site: str):
        if site in self._tabs:
            return self._tabs[site]
        if site in self.external:
            ext = ExternalPage(site, WEB_SITES[site]["label"], WEB_SITES[site]["url"],
                               lambda t: self._set_clipboard(text=t), lambda img: self._set_clipboard(image=img),
                               opener=self._open_in_browser)
            ext.use_integrated.connect(lambda s=site: self.use_integrated.emit(s))
            ext.keep_on_top.connect(self.keep_on_top.emit)
            ext.connect_browser.connect(self.connect_browser.emit)
            if self.bridge is not None:
                ext.set_bridge(self.bridge.connected, self.bridge.browsers())
            self.stack.addWidget(ext)
            self._tabs[site] = (ext, None)
            self._loading[site] = False
            # aperto al giro successivo del ciclo eventi: se nel frattempo parte un passaggio del task
            # (che apre da sé una chat nuova) non serve aprire un'altra scheda
            self._pending_open = site
            from .. import native_install
            # con l'estensione installata aspetta un attimo che il browser si colleghi: così si riusa
            # la scheda già aperta invece di aprirne un'altra
            connected = self.bridge is not None and self.bridge.connected
            QTimer.singleShot(1500 if native_install.installed() and not connected else 0, self._open_pending)
            return self._tabs[site]
        view = QWebEngineView(self.stack)
        page = _Page(self.profile, view, lambda s=site: self.google_signin.emit(s))
        page.paste_hook = lambda v=view, p=page: self._filtered_paste(v, p)
        view.setPage(page)
        self._hook_paste_keys(view)
        view.loadStarted.connect(lambda v=view: self._hook_paste_keys(v))
        view.loadFinished.connect(lambda _ok, v=view: self._hook_paste_keys(v))
        view.loadStarted.connect(lambda s=site: self._loading.__setitem__(s, True))
        view.loadFinished.connect(lambda _ok, s=site: self._loading.__setitem__(s, False))
        page.iconChanged.connect(lambda ic, s=site: site_icons.store_icon(s, ic))
        self.stack.addWidget(view)
        self._tabs[site] = (view, page)
        self._loading[site] = True
        view.setUrl(QUrl(WEB_SITES[site]["url"]))
        return self._tabs[site]

    @property
    def view(self):
        tab = self._tabs.get(self.site)
        return tab[0] if tab and tab[1] is not None else None

    @property
    def page(self):
        tab = self._tabs.get(self.site)
        return tab[1] if tab else None

    def is_external(self, site: str | None = None) -> bool:
        return (site or self.site) in self.external

    def set_external(self, site: str, on: bool):
        """Sposta un servizio tra browser integrato e browser di sistema."""
        if (site in self.external) == on or not self.stack:
            return
        if on:
            self.external.add(site)
        else:
            self.external.discard(site)
        tab = self._tabs.pop(site, None)
        if tab:
            widget, page = tab
            if page is not None:
                for dlg in list(page.popups):
                    dlg.close()
                widget.setPage(None)
                page.deleteLater()
            self.stack.removeWidget(widget)
            widget.deleteLater()
        if site == self.site:
            self._ensure(site)
            self.stack.setCurrentWidget(self._tabs[site][0])

    def _open_pending(self):
        site, self._pending_open = getattr(self, "_pending_open", None), None
        if site and site in self._tabs and self._tabs[site][1] is None:
            self._tabs[site][0].open_browser()

    def _open_in_browser(self, site: str, url: str):
        """Con l'estensione collegata porta in primo piano (o apre) la scheda del servizio in quel browser."""
        if self.bridge is not None and self.bridge.connected and self.bridge.open_site(site, url):
            return
        QDesktopServices.openUrl(QUrl(url))

    def set_bridge_state(self, connected: bool, browsers: list[str]):
        for widget, page in self._tabs.values():
            if page is None:
                widget.set_bridge(connected, browsers)

    def _bridge_has(self, site: str) -> bool:
        return self.bridge is not None and self.bridge.has_site(site)

    def is_open(self, site: str) -> bool:
        return site in self._tabs

    def shutdown(self):
        """Chiude le pagine prima del profilo (altrimenti QtWebEngine non salva bene i dati)."""
        for view, page in self._tabs.values():
            if page is None:
                continue
            for dlg in list(page.popups):
                dlg.close()
            view.setPage(None)
            page.deleteLater()
        self._tabs.clear()

    # ------------------------------------------------------------ navigazione
    def set_site(self, site: str):
        if site not in WEB_SITES or not self.stack:
            return
        self._ensure(site)
        if site != self.site:
            self.site = site
            self.stack.setCurrentWidget(self._tabs[site][0])
            self.site_changed.emit(site)

    def go_home(self):
        if self.is_external():
            self._tabs[self.site][0].open_browser()
            return
        if self.view:
            self._loading[self.site] = True  # fino a loadFinished: evita di incollare nella pagina precedente
            self.view.setUrl(QUrl(WEB_SITES[self.site]["url"]))

    def back(self):
        if self.view:
            self.view.back()

    def reload(self):
        if self.view:
            self.view.reload()

    def open_external(self):
        url = self.view.url() if self.view and not self.view.url().isEmpty() else QUrl(WEB_SITES[self.site]["url"])
        QDesktopServices.openUrl(url)

    def _download(self, req):
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or str(Path.home())
        req.setDownloadDirectory(folder)
        req.accept()
        self.hint.emit(tr("Download in corso in {folder}").format(folder=folder))

    # ------------------------------------------------------------ incolla
    def _set_clipboard(self, image: QImage | None = None, text: str | None = None):
        self._ignore_clipboard = True
        cb = QGuiApplication.clipboard()
        if image is not None:
            cb.setImage(image)
            self._last_clip = ""
        else:
            cb.setText(text or "")
            self._last_clip = text or ""
        self._ignore_clipboard = False

    def paste_image(self, path: str):
        img = QImage(path)
        if img.isNull():
            self.hint.emit(tr("Screenshot non leggibile"))
            return
        if self.is_external() and self._bridge_has(self.site) and self.bridge.paste_image(self.site, path):
            self.hint.emit(tr("Screenshot incollato nella chat di {name} nel browser.").format(
                name=WEB_SITES[self.site]["label"]))
            return
        self._set_clipboard(image=img)
        if self.is_external():
            self.hint.emit(tr("Screenshot copiato: nella chat di {name} nel browser premi Ctrl+V.").format(
                name=WEB_SITES[self.site]["label"]))
            return
        payload = _image_payload(path, img)
        self._paste(tr("Screenshot incollato nella chat: aggiungi una descrizione e invia."), payload)

    def paste_text(self, text: str, done_hint: str | None = tr("Testo incollato nella chat: controlla e invia.")):
        if self.is_external() and self._bridge_has(self.site) and self.bridge.paste_text(self.site, text):
            self.hint.emit(done_hint or tr("Incollato nella chat di {name} nel browser.").format(
                name=WEB_SITES[self.site]["label"]))
            return
        self._set_clipboard(text=text)
        if self.is_external():
            self.hint.emit(tr("Copiato: nella chat di {name} nel browser premi Ctrl+V.").format(
                name=WEB_SITES[self.site]["label"]))
            return
        self._paste(done_hint, {"kind": "text", "text": text})

    def _paste(self, done_hint: str | None, payload: dict | None = None):
        """Incolla nella casella della chat: prima con un evento «paste» con i dati (non dipende dagli
        appunti né dal focus della finestra), se la pagina non lo gestisce con il normale Incolla."""
        if not self.view:
            self.hint.emit(tr("Browser non disponibile: il contenuto è negli appunti, incollalo con Ctrl+V."))
            return
        view, page = self.view, self.page
        view.setFocus()

        def not_found():
            self.hint.emit(tr("Non trovo la casella della chat: cliccaci dentro e premi Ctrl+V "
                              "(il contenuto è già negli appunti)."))

        def native(result="ok"):
            if result == "none":
                not_found()
                return
            page.triggerAction(QWebEnginePage.WebAction.Paste)
            if done_hint:
                self.hint.emit(done_hint)

        def after_insert(result):
            if result == "pasted":
                if done_hint:
                    self.hint.emit(done_hint)
            elif result == "none":
                not_found()
            else:  # la pagina non gestisce l'evento: Incolla classico dagli appunti
                page.runJavaScript(_FOCUS_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld, native)

        if payload is None:
            page.runJavaScript(_FOCUS_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld, native)
            return
        script = _INSERT_JS % json.dumps(payload)
        page.runJavaScript(script, QWebEngineScript.ScriptWorldId.ApplicationWorld, after_insert)

    def last_answer(self, callback):
        """callback(dict) con count, text, busy dell'ultima risposta nella pagina visibile."""
        if not (self.view and self.page):
            callback({"count": 0, "text": "", "busy": False})
            return

        def got(result):
            try:
                callback(json.loads(result or "{}"))
            except ValueError:
                callback({"count": 0, "text": "", "busy": False})

        self.page.runJavaScript(_ANSWER_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld, got)

    def send_current(self):
        """Invia il messaggio presente nella casella della chat (pulsante di invio del sito)."""
        if self.view and self.page:
            self.page.runJavaScript(_SEND_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld)

    # ------------------------------------------------------------ riepilogo automatico
    def request_summary(self, text: str, timeout: float = 240.0):
        """Incolla la richiesta di riepilogo, la invia e legge la risposta appena l'IA ha finito.

        Il riepilogo arriva con summary_copied (come se l'utente l'avesse copiato); se non arriva
        entro il tempo massimo, summary_failed e resta la copia a mano con il pulsante Copia.
        """
        if not self.view:
            self.summary_failed.emit(tr("Browser non disponibile."))
            return
        self._summary_job = {"site": self.site, "until": time.monotonic() + timeout, "last": "", "stable": 0}
        self._set_clipboard(text=text)
        self._paste(None, {"kind": "text", "text": text})
        QTimer.singleShot(1200, self._summary_send)

    @property
    def summary_pending(self) -> bool:
        return getattr(self, "_summary_job", None) is not None

    def cancel_summary(self):
        self._summary_job = None

    def _summary_tab(self):
        job = getattr(self, "_summary_job", None)
        tab = self._tabs.get(job["site"]) if job else None
        return job, (tab if tab and tab[1] is not None else None)

    def _summary_send(self):
        job, tab = self._summary_tab()
        if not tab:
            return
        tab[1].runJavaScript(_SEND_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld,
                             lambda _r: QTimer.singleShot(3000, self._summary_poll))

    def _summary_poll(self):
        job, tab = self._summary_tab()
        if not tab:
            return

        def got(result):
            if getattr(self, "_summary_job", None) is not job:
                return
            try:
                data = json.loads(result or "{}")
            except ValueError:
                data = {}
            text, busy = data.get("text", ""), data.get("busy", False)
            if text and not busy and text == job["last"]:
                job["stable"] += 1
            else:
                job["stable"] = 0
            job["last"] = text
            from ..task import parse_summary
            summary = parse_summary(text) if text else None
            if summary and job["stable"] >= 1:  # testo uguale per due controlli di fila: l'IA ha finito
                self._summary_job = None
                self.summary_copied.emit(summary)
            elif time.monotonic() < job["until"]:
                QTimer.singleShot(2000, self._summary_poll)
            else:
                self._summary_job = None
                self.summary_failed.emit(tr("Non ho trovato il riepilogo nella risposta: copialo tu con il pulsante "
                                            "Copia del blocco di codice."))

        from ..task import SUMMARY_MARKER
        tab[1].runJavaScript(_SUMMARY_JS % json.dumps(SUMMARY_MARKER), QWebEngineScript.ScriptWorldId.ApplicationWorld,
                             got)

    # ------------------------------------------------------------ pacchetto del task
    def paste_package(self, text: str, images: list[str], timeout: float = 90.0):
        """Incolla testo e screenshot nella chat del servizio visibile appena la pagina è pronta.

        Attende che la pagina abbia una casella di testo, poi incolla il testo e le immagini una alla
        volta, come farebbe l'utente con Ctrl+V. Non invia il messaggio.
        """
        if self.is_external() and self.bridge is not None and self.bridge.connected:
            # l'estensione apre una chat nuova nel browser e incolla testo e screenshot; l'esito arriva dopo
            if self.bridge.open_paste(self.site, WEB_SITES[self.site]["url"], text, images):
                self._pending_open = None
                return
        if self.is_external() and self.stack:
            self._ensure(self.site)[0].set_queue(text, images)
            self.package_done.emit(True)
            return
        if not self.view:
            self._set_clipboard(text=text)
            self.package_done.emit(False)
            return
        self._job = {"site": self.site, "text": text, "images": list(images), "until": time.monotonic() + timeout}
        QTimer.singleShot(600, self._job_poll)

    def _job_tab(self, job):
        return self._tabs.get(job["site"]) if job else None

    def _job_poll(self):
        job = self._job
        tab = self._job_tab(job)
        if tab is None:
            return
        view, page = tab
        if self._loading.get(job["site"]):
            if time.monotonic() < job["until"]:
                QTimer.singleShot(500, self._job_poll)
            return

        def ready(result):
            if self._job is not job:
                return
            if result in ("ok", "focused"):
                view.setFocus()
                self._insert(view, page, {"kind": "text", "text": job["text"]})
                QTimer.singleShot(700, self._job_images)
            elif time.monotonic() < job["until"]:
                QTimer.singleShot(500, self._job_poll)
            else:
                self._job = None
                self._set_clipboard(text=job["text"])
                self.package_done.emit(False)

        page.runJavaScript(_READY_JS, QWebEngineScript.ScriptWorldId.ApplicationWorld, ready)

    def _job_images(self):
        job = self._job
        tab = self._job_tab(job)
        if tab is None:
            return
        view, page = tab
        if not job["images"]:
            self._job = None
            self.package_done.emit(True)
            return
        path = job["images"].pop(0)
        img = QImage(path)
        if not img.isNull():
            view.setFocus()
            self._insert(view, page, _image_payload(path, img))
        QTimer.singleShot(900, self._job_images)

    # ------------------------------------------------------------ scudo privacy sugli incolla
    def _filtered_paste(self, view, page) -> bool:
        """Con lo scudo acceso incolla il testo degli appunti già oscurato. False: incolla normale
        (scudo spento, immagine, o niente da oscurare: così si conserva la formattazione)."""
        from .. import privacy
        if not privacy.paste_filter_active():
            return False
        md = QGuiApplication.clipboard().mimeData()
        if md is None or md.hasImage() or not md.hasText():
            return False
        text = md.text()
        clean = privacy.filter_paste(text)
        if clean == text:
            return False
        self._insert(view, page, {"kind": "text", "text": clean})
        return True

    @staticmethod
    def _is_paste_key(ev) -> bool:
        if ev.matches(QKeySequence.StandardKey.Paste):
            return True
        mods = ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        return ev.key() == Qt.Key.Key_V and mods == (Qt.KeyboardModifier.ControlModifier |
                                                      Qt.KeyboardModifier.ShiftModifier)

    def _hook_paste_keys(self, view):
        """I tasti arrivano al widget interno della pagina (focusProxy), che nasce col primo caricamento."""
        for w in (view, view.focusProxy()):
            if w is not None and not w.property("helpixPasteHook"):
                w.setProperty("helpixPasteHook", True)
                w.installEventFilter(self._paste_keys)

    def _insert(self, view, page, payload: dict):
        """Incolla in una pagina precisa (anche non visibile); se la pagina non gestisce l'evento,
        ripiega sugli appunti e sull'Incolla classico."""
        def done(result):
            if result != "unhandled":
                return
            if payload["kind"] == "image":
                self._set_clipboard(image=QImage.fromData(base64.b64decode(payload["data"])))
            else:
                self._set_clipboard(text=payload["text"])
            view.setFocus()
            page.triggerAction(QWebEnginePage.WebAction.Paste)

        page.runJavaScript(_INSERT_JS % json.dumps(payload), QWebEngineScript.ScriptWorldId.ApplicationWorld, done)

    # ------------------------------------------------------------ appunti
    def _clipboard_changed(self):
        if self._ignore_clipboard or not self.isVisible():
            return
        if QApplication.activeWindow() is None:  # reagisci solo a ciò che l'utente copia dentro Helpix
            return
        self._process_clipboard()

    def check_clipboard(self):
        """Al ritorno su Helpix: con il servizio nel browser di sistema, controlla cosa è stato copiato.

        Su Wayland le app non leggono gli appunti mentre non hanno il focus, quindi il controllo
        si fa quando l'utente torna sulla finestra di Helpix.
        """
        if self.isVisible() and self.is_external():
            self._process_clipboard()

    def _process_clipboard(self):
        text = QGuiApplication.clipboard().text()
        if not text or text == self._last_clip:
            return
        self._last_clip = text
        from ..task import parse_summary
        summary = parse_summary(text)
        if summary:
            self.summary_copied.emit(summary)
            return
        from ..executor import looks_like_command
        cmd = looks_like_command(text)
        if cmd:
            self.command_copied.emit(cmd)
