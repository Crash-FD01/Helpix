/* SPDX-FileCopyrightText: 2026 Crash
 * SPDX-License-Identifier: GPL-3.0-or-later */
/* Helpix — pulsanti nella pagina della chat.
 *
 * - «Esegui con Helpix» sotto i blocchi di codice: il blocco viene inviato a Helpix solo
 *   quando premi il pulsante; Helpix controlla il comando, lo esegue e incolla l'output
 *   nella casella della chat. Tu premi Invio.
 * - Un piccolo pannello a lato con Screenshot e Diagnosi.
 *
 * Lo script non legge la conversazione e non invia mai messaggi al posto tuo.
 */
(() => {
  "use strict";
  if (window.__helpixLoaded) return;
  window.__helpixLoaded = true;

  const api = globalThis.browser ?? globalThis.chrome;
  const SITE_BY_HOST = {
    "chatgpt.com": "chatgpt", "chat.openai.com": "chatgpt", "claude.ai": "claude",
    "gemini.google.com": "gemini", "copilot.microsoft.com": "copilot", "chat.deepseek.com": "deepseek",
  };
  const site = SITE_BY_HOST[location.hostname];
  if (!site) return;

  const SUMMARY_MARKER = "HELPIX-TASK";
  // linguaggi che non sono comandi di shell: niente pulsante
  const NON_SHELL = /\blang(uage)?-(python|py|javascript|js|jsx|typescript|ts|tsx|json|jsonc|json5|yaml|yml|toml|ini|html|xml|svg|css|scss|less|c|cpp|cxx|h|hpp|java|kotlin|kt|go|golang|rust|rs|ruby|rb|php|sql|swift|csharp|cs|fsharp|lua|perl|pl|r|markdown|md|dockerfile|makefile|cmake|nginx|apache|systemd|csv|latex|tex|dart|scala|haskell|hs|elixir|erlang|clojure|vue|svelte|graphql|proto|protobuf|mermaid)\b/i;
  const COMPOSER = {
    chatgpt: ["#prompt-textarea", "div.ProseMirror[contenteditable='true']", "form textarea"],
    claude: ["div.ProseMirror[contenteditable='true']", "[contenteditable='true'][role='textbox']", "fieldset [contenteditable='true']"],
    gemini: ["rich-textarea .ql-editor[contenteditable='true']", ".ql-editor[contenteditable='true']", "[contenteditable='true'][role='textbox']"],
    copilot: ["textarea#userInput", "textarea[placeholder]", "[contenteditable='true'][role='textbox']"],
    deepseek: ["textarea#chat-input", "textarea[placeholder]", "textarea"],
  };

  const t = (key, subs) => {
    try {
      return api.i18n.getMessage(key, subs) || key;
    } catch (_e) {
      return key;
    }
  };
  let state = { host: "connecting", app: false };
  let invalidated = false;

  function send(msg) {
    try {
      const r = api.runtime.sendMessage(msg);
      return r && r.then ? r.catch(() => onInvalidated()) : Promise.resolve(undefined);
    } catch (_e) {
      onInvalidated();
      return Promise.resolve(undefined);
    }
  }

  function onInvalidated() {
    if (invalidated) return undefined;
    if (api.runtime && api.runtime.id) return undefined;
    invalidated = true; // l'estensione è stata aggiornata o rimossa: questa pagina va ricaricata
    toast(t("reload"));
    return undefined;
  }

  // ------------------------------------------------------------------ aspetto
  function isDark() {
    const root = document.documentElement;
    if (root.classList.contains("dark") || root.dataset.theme === "dark" || root.dataset.mode === "dark") return true;
    if (root.classList.contains("light") || root.dataset.theme === "light" || root.dataset.mode === "light") return false;
    for (const el of [document.body, root]) {
      const m = el && getComputedStyle(el).backgroundColor.match(/\d+(\.\d+)?/g);
      if (m && m.length >= 3 && (m.length < 4 || Number(m[3]) > 0.5)) {
        const [r, g, b] = m.map(Number);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;
      }
    }
    return matchMedia("(prefers-color-scheme: dark)").matches;
  }

  const BASE_CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: -apple-system, "Inter", "Segoe UI", system-ui, sans-serif; }
    :host { --bg: rgba(255,255,255,.92); --fg: #1d1d1f; --muted: #6e6e73; --line: rgba(0,0,0,.10);
            --btn: rgba(0,0,0,.05); --btnh: rgba(0,0,0,.09); --accent: #0a84ff; --accentfg: #fff;
            --ok: #1f8a3b; --err: #c4352b; --warnbg: #fff6e5; --warnline: #f0c36d; --shadow: 0 6px 24px rgba(0,0,0,.14); }
    :host([data-dark]) { --bg: rgba(40,40,44,.92); --fg: #f5f5f7; --muted: #a1a1a6; --line: rgba(255,255,255,.12);
            --btn: rgba(255,255,255,.08); --btnh: rgba(255,255,255,.14); --ok: #4cd06a; --err: #ff6b5f;
            --warnbg: #3a2f17; --warnline: #8a6a24; --shadow: 0 6px 24px rgba(0,0,0,.45); }
    button { font-weight: 500; font-size: 12.5px; line-height: 1; color: var(--fg); background: var(--btn); border: 1px solid var(--line);
             border-radius: 999px; padding: 6px 11px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
    button:hover { background: var(--btnh); }
    button:disabled { opacity: .55; cursor: default; }
    button.primary { background: var(--accent); color: var(--accentfg); border-color: transparent; }
    svg { width: 14px; height: 14px; flex: none; }
    .spin { animation: spin 0.9s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
  `;
  const ICON = {
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    pulse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg>',
    spinner: '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.3"/></svg>',
    paste: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="5" width="12" height="15" rx="2"/><path d="M9 5V3.8h6V5"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  };

  function setHTML(el, html) {
    // markup statico dell'estensione (mai testo della pagina): lo analizzo come documento separato
    const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
    el.replaceChildren(...doc.body.childNodes);
  }

  // ------------------------------------------------------------------ casella della chat
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const editable = (el) => !!el && (el.isContentEditable || el.tagName === "TEXTAREA" ||
    (el.tagName === "INPUT" && /^(text|search)$/i.test(el.type)));

  function findComposer() {
    const active = document.activeElement;
    if (editable(active) && visible(active) && !active.closest("helpix-run, helpix-pill")) return active;
    for (const sel of COMPOSER[site] || []) {
      const found = [...document.querySelectorAll(sel)].filter(visible);
      if (found.length) return found[found.length - 1];
    }
    const any = [...document.querySelectorAll("textarea, [contenteditable='true'], [contenteditable='']")].filter(visible);
    return any.length ? any[any.length - 1] : null;
  }

  function focusComposer(el) {
    if (document.activeElement === el || el.contains(document.activeElement)) return;
    el.focus();
    if (el.isContentEditable) {
      const range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } else if (typeof el.setSelectionRange === "function") {
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }

  function dispatchPaste(el, dt) {
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true, composed: true });
    // dispatchEvent restituisce false se l'editor della pagina ha gestito l'incolla
    return !el.dispatchEvent(ev);
  }

  function pasteText(text) {
    const el = findComposer();
    if (!el) return false;
    focusComposer(el);
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    if (dispatchPaste(el, dt)) return true;
    if (document.execCommand("insertText", false, text)) return true;
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set;
      setter.call(el, el.value + text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }
    return false;
  }

  function pasteFile(file) {
    const el = findComposer();
    if (!el) return false;
    focusComposer(el);
    const dt = new DataTransfer();
    dt.items.add(file);
    if (dispatchPaste(el, dt)) return true;
    const drop = new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true, composed: true });
    if (!el.dispatchEvent(drop)) return true;
    const input = [...document.querySelectorAll("input[type='file']")]
      .find((i) => !i.disabled && (!i.accept || /image|\*/.test(i.accept)));
    if (input) {
      input.files = dt.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    return false;
  }

  function b64ToFile(data, mime, name) {
    const bin = atob(data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name || "screenshot.png", { type: mime || "image/png" });
  }

  async function waitComposer(ms) {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      if (document.readyState === "complete" && findComposer()) return true;
      await new Promise((r) => setTimeout(r, 400));
    }
    return false;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ------------------------------------------------------------------ pannello flottante e avvisi
  const pill = document.createElement("helpix-pill");
  const pillRoot = pill.attachShadow({ mode: "open" });
  let toastTimer = null;
  let clipboardOffer = null;

  function buildPill() {
    setHTML(pillRoot, `
      <style>${BASE_CSS}
        .pill { position: fixed; right: 14px; top: 46%; z-index: 2147483646; display: flex; flex-direction: column;
                align-items: center; gap: 6px; padding: 6px; border-radius: 22px; background: var(--bg);
                border: 1px solid var(--line); box-shadow: var(--shadow); backdrop-filter: blur(14px); }
        .pill.collapsed .b { display: none; }
        .logo { position: relative; width: 32px; height: 32px; padding: 0; border: 0; background: none; border-radius: 9px; cursor: grab; }
        .logo canvas { width: 32px; height: 32px; border-radius: 8px; display: block; }
        .dot { position: absolute; right: -2px; bottom: -2px; width: 11px; height: 11px; border-radius: 50%;
               border: 2px solid var(--bg); background: #8a8a8e; }
        .dot.on { background: #34c759; } .dot.err { background: #ff453a; }
        .b { width: 34px; height: 34px; padding: 0; justify-content: center; }
        .b svg { width: 17px; height: 17px; }
        .toast { position: fixed; left: 50%; bottom: 128px; transform: translateX(-50%); z-index: 2147483647;
                 max-width: min(560px, 90vw); padding: 10px 14px; border-radius: 14px; background: var(--bg); color: var(--fg);
                 border: 1px solid var(--line); box-shadow: var(--shadow); font-size: 13px; line-height: 1.4; backdrop-filter: blur(14px);
                 display: none; align-items: center; gap: 10px; }
        .toast.show { display: flex; }
        .toast b { font-weight: 600; }
      </style>
      <div class="pill collapsed" part="pill">
        <button class="logo" title="Helpix"><canvas width="64" height="64"></canvas><span class="dot"></span></button>
        <button class="b shot" title="${t("screenshotTip")}">${ICON.camera}</button>
        <button class="b diag" title="${t("diagnosticsTip")}">${ICON.pulse}</button>
      </div>
      <div class="toast" role="status"><span class="msg"></span></div>`);
    drawLogo(pillRoot.querySelector("canvas"));
    const box = pillRoot.querySelector(".pill");
    const logo = pillRoot.querySelector(".logo");
    let drag = null;
    logo.addEventListener("pointerdown", (e) => {
      drag = { y: e.clientY, top: box.getBoundingClientRect().top, moved: false };
      logo.setPointerCapture(e.pointerId);
    });
    logo.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dy = e.clientY - drag.y;
      if (Math.abs(dy) > 4) drag.moved = true;
      if (drag.moved) {
        const top = Math.max(8, Math.min(innerHeight - box.offsetHeight - 8, drag.top + dy));
        box.style.top = `${(top / innerHeight) * 100}%`;
      }
    });
    logo.addEventListener("pointerup", (e) => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      if (moved) {
        store({ pillTop: box.style.top });
      } else if (e.isTrusted) {
        box.classList.toggle("collapsed");
        store({ pillOpen: !box.classList.contains("collapsed") });
        if (!state.app) showStateHint();
      }
    });
    pillRoot.querySelector(".shot").addEventListener("click", (e) => request(e, "screenshot"));
    pillRoot.querySelector(".diag").addEventListener("click", (e) => request(e, "diagnostics"));
    load().then((prefs) => {
      if (prefs.showPill === false) pill.style.display = "none";
      if (prefs.pillTop) box.style.top = prefs.pillTop;
      if (prefs.pillOpen !== false) box.classList.remove("collapsed");
    });
  }

  const LOGO_PNG = "__HELPIX_LOGO_B64__"; // inserito da tools/build_extension.py

  async function drawLogo(canvas) {
    // disegnato da byte già presenti nello script: nessuna risorsa caricata nella pagina
    try {
      const bmp = await createImageBitmap(b64ToFile(LOGO_PNG, "image/png", "logo.png"));
      canvas.getContext("2d").drawImage(bmp, 0, 0, 64, 64);
    } catch (_e) {
      const g = canvas.getContext("2d");
      g.fillStyle = "#1c2433";
      g.fillRect(0, 0, 64, 64);
      g.fillStyle = "#4fb3ff";
      g.font = "bold 40px sans-serif";
      g.textAlign = "center";
      g.fillText("H", 32, 46);
    }
  }

  function load() {
    try {
      const r = api.storage.local.get(["showPill", "pillTop", "pillOpen"]);
      return r && r.then ? r.catch(() => ({})) : Promise.resolve({});
    } catch (_e) {
      return Promise.resolve({});
    }
  }

  function store(obj) {
    try {
      const r = api.storage.local.set(obj);
      if (r && r.catch) r.catch(() => {});
    } catch (_e) { /* storage non disponibile */ }
  }

  function toast(text, ms = 6000, action = null) {
    const box = pillRoot.querySelector(".toast");
    if (!box) return;
    box.querySelector(".msg").textContent = text;
    box.querySelector("button")?.remove();
    if (action) {
      const b = document.createElement("button");
      b.className = "primary";
      b.textContent = action.label;
      b.addEventListener("click", (e) => { if (e.isTrusted) action.run(); });
      box.appendChild(b);
    }
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), ms);
  }

  function offerCopy(text, why) {
    // la casella non c'è: l'utente copia con un clic (serve un suo gesto per usare gli appunti)
    clipboardOffer = text;
    toast(why, 15000, {
      label: t("copy"),
      run: async () => {
        try {
          await navigator.clipboard.writeText(clipboardOffer || "");
          toast(t("copied"));
        } catch (_e) {
          toast(t("noComposer"));
        }
      },
    });
  }

  function applyState() {
    const dot = pillRoot.querySelector(".dot");
    if (dot) {
      dot.className = `dot ${state.app ? "on" : state.host === "missing" || state.host === "error" ? "err" : ""}`;
      dot.parentElement.title = statusText();
    }
    for (const run of runs.values()) if (run.waiting && (state.host === "missing" || state.host === "error")) run.notConnected();
  }

  function statusText() {
    if (state.app) return t("statusOn");
    if (state.host === "ok" || state.host === "connecting") return t("statusApp");
    return t("statusMissing");
  }

  function showStateHint() {
    if (state.host === "missing" || state.host === "error") toast(t("notConnected"), 9000);
    else if (!state.app) toast(t("statusApp"), 6000, { label: t("launch"), run: () => send({ type: "launch" }) });
  }

  async function request(e, type) {
    if (!e.isTrusted) return;
    const res = await send({ type, site });
    if (!res || !res.ok || res.host === "missing" || res.host === "error") {
      toast(t("notConnected"), 9000);
    } else if (!res.app) {
      toast(t("appClosed"));
    } else if (type === "screenshot") {
      toast(t("shotHint"), 4000);
    } else {
      toast(t("diagHint"), 6000);
    }
  }

  // ------------------------------------------------------------------ pulsanti sui blocchi di codice
  const runs = new Map();          // id della richiesta -> controllo
  const hosts = new WeakMap();     // <pre> -> controllo
  const controls = new Set();

  function blockKind(pre) {
    if (pre.closest("[contenteditable='true'], textarea, helpix-run, helpix-pill")) return null;
    const code = pre.querySelector("code") || pre;
    const head = (code.textContent || "").trimStart().slice(0, SUMMARY_MARKER.length);
    if (head === SUMMARY_MARKER) return "summary";
    if (NON_SHELL.test(`${code.className} ${pre.className}`)) return null;
    if (!(code.textContent || "").trim()) return null;
    return "run";
  }

  class RunControl {
    constructor(pre, kind) {
      this.pre = pre;
      this.kind = kind;
      this.id = null;
      this.output = "";
      this.waiting = false;
      this.el = document.createElement("helpix-run");
      this.el.style.cssText = "display:block;margin:6px 0 10px;";
      this.root = this.el.attachShadow({ mode: "open" });
      setHTML(this.root, `
        <style>${BASE_CSS}
          .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
          .state { font-size: 12.5px; line-height: 1.35; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
          .state.ok { color: var(--ok); } .state.err { color: var(--err); }
          .confirm { margin-top: 8px; padding: 10px 12px; border-radius: 12px; background: var(--warnbg);
                     border: 1px solid var(--warnline); color: var(--fg); font-size: 12.5px; line-height: 1.45; max-width: 640px; }
          .confirm b { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
          .confirm ul { margin: 4px 0 8px 18px; padding: 0; }
          .confirm .row { margin-top: 6px; }
          [hidden] { display: none !important; }
        </style>
        <div class="row">
          <button class="go"></button>
          <span class="state"></span>
          <button class="again" hidden>${ICON.paste}<span>${t("pasteOutput")}</span></button>
        </div>
        <div class="confirm" hidden>
          <b>${ICON.warn}<span>${t("confirmTitle")}</span></b>
          <ul></ul>
          <div class="row"><button class="primary yes">${t("runAnyway")}</button><button class="no">${t("cancel")}</button></div>
        </div>`);
      this.btn = this.root.querySelector(".go");
      this.stateEl = this.root.querySelector(".state");
      this.again = this.root.querySelector(".again");
      this.confirmBox = this.root.querySelector(".confirm");
      this.btn.addEventListener("click", (e) => this.click(e));
      this.again.addEventListener("click", (e) => {
        if (e.isTrusted && this.output) this.paste(this.output);
      });
      this.root.querySelector(".yes").addEventListener("click", (e) => {
        if (!e.isTrusted) return;
        this.confirmBox.hidden = true;
        this.submit(true);
      });
      this.root.querySelector(".no").addEventListener("click", (e) => {
        if (!e.isTrusted) return;
        this.confirmBox.hidden = true;
        this.reset(t("cancelled"));
      });
      this.label();
      this.theme();
    }

    theme() {
      this.el.toggleAttribute("data-dark", darkMode);
    }

    label() {
      const icon = this.kind === "summary" ? ICON.send : ICON.play;
      setHTML(this.btn, `${icon}<span>${t(this.kind === "summary" ? "sendSummary" : "run")}</span>`);
    }

    setKind(kind) {
      if (kind !== this.kind && !this.id) {
        this.kind = kind;
        this.label();
      }
    }

    place() {
      if (this.pre.nextSibling !== this.el) this.pre.after(this.el);
    }

    setState(text, cls = "", icon = "") {
      this.stateEl.className = `state ${cls}`;
      setHTML(this.stateEl, icon);
      const span = document.createElement("span");
      span.textContent = text;
      this.stateEl.appendChild(span);
    }

    click(e) {
      if (!e.isTrusted) return;
      this.confirmBox.hidden = true;
      this.again.hidden = true;
      this.submit(false);
    }

    async submit(confirmed) {
      const code = this.pre.querySelector("code") || this.pre;
      const text = (code.innerText || code.textContent || "").replace(/ /g, " ").trim();
      if (!text) return;
      if (this.id) runs.delete(this.id);
      this.id = this.id && confirmed ? this.id : crypto.randomUUID();
      runs.set(this.id, this);
      this.btn.disabled = true;
      this.waiting = true;
      this.setState(t("waiting"), "", ICON.spinner);
      const res = await send({ type: "run", id: this.id, cmd: text, confirmed });
      if (!res || !res.ok || res.host === "missing" || res.host === "error") {
        this.notConnected();
      } else if (!res.app) {
        this.setState(t("appClosed"), "", ICON.spinner);
      }
    }

    notConnected() {
      this.waiting = false;
      this.btn.disabled = false;
      this.setState(t("notConnected"), "err");
    }

    reset(text, cls = "") {
      this.waiting = false;
      this.btn.disabled = false;
      this.setState(text, cls);
      if (this.id) runs.delete(this.id);
      this.id = null;
    }

    paste(text) {
      if (pasteText(text)) {
        toast(t("outputPasted"));
        return true;
      }
      offerCopy(text, t("noComposer"));
      return false;
    }

    status(msg) {
      this.waiting = false;
      switch (msg.state) {
        case "running":
          this.btn.disabled = true;
          this.setState(t("running"), "", ICON.spinner);
          break;
        case "confirm": {
          this.btn.disabled = true;
          this.setState("", "");
          const ul = this.confirmBox.querySelector("ul");
          ul.replaceChildren(...(msg.warnings || []).map((w) => {
            const li = document.createElement("li");
            li.textContent = String(w);
            return li;
          }));
          this.confirmBox.hidden = false;
          break;
        }
        case "done": {
          const ok = msg.rc === 0;
          this.output = typeof msg.output === "string" ? msg.output : "";
          const base = ok ? t("done") : t("failedRc", [String(msg.rc)]);
          let pasted = false;
          if (this.output && msg.auto) pasted = this.paste(this.output);
          this.reset(pasted ? `${base} · ${t("outputPastedShort")}` : base, ok ? "ok" : "err");
          if (ok) this.setState(this.stateEl.textContent, "ok", ICON.check);
          this.again.hidden = !this.output;
          break;
        }
        case "summary":
          this.reset(t("summarySent"), "ok");
          this.setState(t("summarySent"), "ok", ICON.check);
          break;
        case "busy":
          this.reset(t("busy"), "err");
          break;
        case "rejected":
          this.reset(msg.reason || t("rejected"), "err");
          break;
        case "cancelled":
          this.reset(t("cancelled"));
          break;
        default:
          this.reset(msg.reason || "", "err");
      }
    }

    remove() {
      this.el.remove();
      controls.delete(this);
    }
  }

  let darkMode = false;
  let scanTimer = null;

  function scan() {
    scanTimer = null;
    const dark = isDark();
    if (dark !== darkMode) {
      darkMode = dark;
      pill.toggleAttribute("data-dark", dark);
      for (const c of controls) c.theme();
    }
    if (!pill.isConnected) document.documentElement.appendChild(pill);
    for (const pre of document.querySelectorAll("pre")) {
      const kind = blockKind(pre);
      let ctl = hosts.get(pre);
      if (!kind) {
        if (ctl && !ctl.id) {
          ctl.remove();
          hosts.delete(pre);
        }
        continue;
      }
      if (!ctl) {
        ctl = new RunControl(pre, kind);
        hosts.set(pre, ctl);
        controls.add(ctl);
      }
      ctl.setKind(kind);
      ctl.place();
    }
    for (const ctl of controls) if (!ctl.pre.isConnected) ctl.remove();
  }

  function scheduleScan() {
    if (!scanTimer) scanTimer = setTimeout(scan, 350);
  }

  // ------------------------------------------------------------------ messaggi da Helpix
  async function pastePackage(msg) {
    const ready = await waitComposer(30000);
    if (!ready) {
      offerCopy(msg.text || "", t("noComposer"));
      send({ type: "package_result", ok: false });
      return;
    }
    await sleep(500);
    let ok = msg.text ? pasteText(msg.text) : true;
    for (const img of msg.images || []) {
      await sleep(900);
      ok = pasteFile(b64ToFile(img.data, img.mime, img.name)) && ok;
    }
    toast(ok ? t("packagePasted") : t("noComposer"), 9000);
    send({ type: "package_result", ok });
  }

  api.runtime.onMessage.addListener((msg) => {
    if (!msg || typeof msg !== "object") return;
    switch (msg.type) {
      case "helpix_state":
        state = msg;
        applyState();
        break;
      case "paste_text":
        if (pasteText(msg.text || "")) toast(t("textPasted"));
        else offerCopy(msg.text || "", t("noComposer"));
        break;
      case "paste_image":
        if (pasteFile(b64ToFile(msg.data, msg.mime, msg.name))) toast(t("shotPasted"));
        else toast(t("noComposer"), 8000);
        break;
      case "run_status": {
        const run = runs.get(msg.id);
        if (run) run.status(msg);
        break;
      }
      case "paste_package":
        pastePackage(msg);
        break;
      case "notify":
        if (msg.text) toast(String(msg.text), 8000);
        break;
      default:
        break;
    }
  });

  function reportActive() {
    if (document.visibilityState === "visible" && document.hasFocus()) send({ type: "active", site });
  }

  try {
    api.storage.onChanged.addListener((changes) => {
      if (changes.showPill) pill.style.display = changes.showPill.newValue === false ? "none" : "";
    });
  } catch (_e) { /* storage non disponibile */ }

  buildPill();
  scan();
  new MutationObserver(scheduleScan).observe(document.documentElement, { childList: true, subtree: true });
  addEventListener("focus", reportActive);
  document.addEventListener("visibilitychange", reportActive);
  send({ type: "ready", site }).then((res) => {
    if (res) {
      state = res;
      applyState();
    }
    reportActive();
  });
})();
