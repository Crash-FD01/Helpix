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

  const LOGO_PNG = "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"; // inserito da tools/build_extension.py

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
