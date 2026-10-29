/* SPDX-FileCopyrightText: 2026 Crash
 * SPDX-License-Identifier: GPL-3.0-or-later */
/* Helpix — collegamento tra il browser e l'app Helpix (native messaging).
 *
 * Il lavoro vero lo fa l'app: questo script inoltra le richieste delle pagine di chat
 * (esegui un comando, screenshot, diagnosi) e rimanda alla scheda giusta ciò che l'app
 * vuole incollare. Non legge le conversazioni e non invia messaggi.
 */
"use strict";

const api = globalThis.browser ?? globalThis.chrome;
const HOST = "com.helpix.bridge";
const SITES = {
  chatgpt: { url: "https://chatgpt.com/", match: ["https://chatgpt.com/*", "https://chat.openai.com/*"] },
  claude: { url: "https://claude.ai/new", match: ["https://claude.ai/*"] },
  gemini: { url: "https://gemini.google.com/app", match: ["https://gemini.google.com/*"] },
  copilot: { url: "https://copilot.microsoft.com/", match: ["https://copilot.microsoft.com/*"] },
  deepseek: { url: "https://chat.deepseek.com/", match: ["https://chat.deepseek.com/*"] },
};
const ALL_MATCHES = Object.values(SITES).flatMap((s) => s.match);
const FORWARD = new Set(["run", "screenshot", "diagnostics", "package_result", "active"]);

let port = null;
let hostState = "connecting"; // connecting | ok | missing | error
let appConnected = false;
let appVersion = "";
let lastError = "";
let retryDelay = 2000;
let retryTimer = null;
const chunks = new Map();          // id -> {n, parts[]}
const activeTab = {};              // servizio -> ultima scheda usata
const pendingPackages = new Map(); // scheda -> task da incollare appena la pagina è pronta

function browserName() {
  const ua = navigator.userAgent;
  if (/LibreWolf/.test(ua)) return "LibreWolf";
  if (/Firefox\//.test(ua)) return "Firefox";
  if (navigator.brave) return "Brave";
  if (/Edg\//.test(ua)) return "Microsoft Edge";
  if (/OPR\//.test(ua)) return "Opera";
  if (/Vivaldi/.test(ua)) return "Vivaldi";
  const brands = (navigator.userAgentData?.brands || []).map((b) => b.brand);
  if (brands.includes("Google Chrome")) return "Google Chrome";
  return "Chromium";
}

function siteOfUrl(url) {
  try {
    const host = new URL(url).hostname;
    if (host === "chatgpt.com" || host === "chat.openai.com") return "chatgpt";
    if (host === "claude.ai") return "claude";
    if (host === "gemini.google.com") return "gemini";
    if (host === "copilot.microsoft.com") return "copilot";
    if (host === "chat.deepseek.com") return "deepseek";
  } catch (_e) { /* URL non valido */ }
  return null;
}

// ------------------------------------------------------------------ collegamento con l'host
function post(msg) {
  if (!port) connect();
  if (!port) return false;
  try {
    port.postMessage(msg);
    return true;
  } catch (e) {
    lastError = String(e);
    return false;
  }
}

function hello() {
  post({ type: "hello", browser: browserName(), version: api.runtime.getManifest().version, tabs: { ...activeTab } });
}

function connect() {
  if (port) return;
  clearTimeout(retryTimer);
  retryTimer = null;
  let p;
  try {
    p = api.runtime.connectNative(HOST);
  } catch (e) {
    setState("missing", String(e));
    scheduleRetry();
    return;
  }
  port = p;
  if (hostState !== "ok") setState("connecting");
  p.onMessage.addListener(onHostMessage);
  p.onDisconnect.addListener(() => {
    const err = (api.runtime.lastError && api.runtime.lastError.message) || (p.error && p.error.message) || "";
    if (port === p) port = null;
    appConnected = false;
    const missing = /not found|no such native application|not allowed|forbidden|access to the specified/i.test(err);
    setState(missing ? "missing" : "error", err);
    scheduleRetry();
  });
  hello();
}

function scheduleRetry() {
  if (retryTimer) return;
  const delay = hostState === "missing" ? 30000 : retryDelay;
  retryDelay = Math.min(retryDelay * 2, 30000);
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, delay);
}

function setState(state, error) {
  hostState = state;
  if (error !== undefined) lastError = error;
  if (state === "ok") retryDelay = 2000;
  updateBadge();
  broadcast({ type: "helpix_state", ...status() });
}

function status() {
  return { host: hostState, app: appConnected, appVersion, browser: browserName(), error: lastError };
}

function updateBadge() {
  const action = api.action || api.browserAction;
  if (!action) return;
  const text = appConnected ? "" : hostState === "missing" || hostState === "error" ? "!" : "off";
  const color = hostState === "missing" || hostState === "error" ? "#d93f3f" : "#8a8a8e";
  try {
    action.setBadgeText({ text });
    action.setBadgeBackgroundColor({ color });
    action.setTitle({ title: api.i18n.getMessage(appConnected ? "statusOn" : hostState === "ok" ? "statusApp" : "statusMissing") });
  } catch (_e) { /* il browser non supporta i badge */ }
}

async function broadcast(msg) {
  let tabs = [];
  try {
    tabs = await api.tabs.query({ url: ALL_MATCHES });
  } catch (_e) {
    return;
  }
  for (const tab of tabs) sendToTab(tab.id, msg);
}

function sendToTab(tabId, msg) {
  try {
    const r = api.tabs.sendMessage(tabId, msg);
    if (r && r.catch) r.catch(() => {});
    return true;
  } catch (_e) {
    return false;
  }
}

// ------------------------------------------------------------------ messaggi dall'app
function onHostMessage(msg) {
  if (!msg || typeof msg !== "object") return;
  if (hostState !== "ok") setState("ok", "");
  switch (msg.type) {
    case "chunk":
      return onChunk(msg);
    case "helpix_status":
      appConnected = !!msg.connected;
      if (appConnected) hello();
      setState("ok", "");
      return;
    case "hello_ack":
      appVersion = String(msg.app || "");
      appConnected = true;
      setState("ok", "");
      return;
    case "pong":
      return;
    case "open_paste":
      return openAndPaste(msg);
    case "open":
      return openSite(msg);
    default:
      return route(msg);
  }
}

function onChunk(msg) {
  let entry = chunks.get(msg.id);
  if (!entry) {
    entry = { n: msg.n, parts: new Array(msg.n), got: 0, time: Date.now() };
    chunks.set(msg.id, entry);
  }
  if (entry.parts[msg.i] === undefined) {
    entry.parts[msg.i] = msg.data;
    entry.got += 1;
  }
  if (entry.got === entry.n) {
    chunks.delete(msg.id);
    try {
      onHostMessage(JSON.parse(entry.parts.join("")));
    } catch (_e) { /* messaggio rovinato: lo scarto */ }
  }
  for (const [id, e] of chunks) if (Date.now() - e.time > 60000) chunks.delete(id);
}

async function route(msg) {
  const site = SITES[msg.site] ? msg.site : null;
  let tabId = Number.isInteger(msg.tab) ? msg.tab : site ? activeTab[site] : undefined;
  if (tabId !== undefined) {
    try {
      const tab = await api.tabs.get(tabId);
      if (tab && (!site || siteOfUrl(tab.url || "") === site)) {
        sendToTab(tabId, msg);
        return;
      }
    } catch (_e) { /* scheda chiusa */ }
  }
  if (!site) return;
  const tabs = await api.tabs.query({ url: SITES[site].match });
  const best = tabs.find((t) => t.active) || tabs[0];
  if (best) {
    activeTab[site] = best.id;
    sendToTab(best.id, { ...msg, tab: best.id });
  }
}

async function focusTab(tab) {
  await api.tabs.update(tab.id, { active: true });
  if (tab.windowId !== undefined && api.windows) await api.windows.update(tab.windowId, { focused: true });
}

async function openSite(msg) {
  const site = SITES[msg.site] ? msg.site : null;
  if (!site) return;
  try {
    const tabs = await api.tabs.query({ url: SITES[site].match });
    const known = tabs.find((t) => t.id === activeTab[site]) || tabs.find((t) => t.active) || tabs[0];
    if (known) {
      await focusTab(known);
    } else {
      const tab = await api.tabs.create({ url: SITES[site].url, active: true });
      await focusTab(tab);
    }
  } catch (_e) { /* finestra chiusa nel frattempo */ }
}

async function openAndPaste(msg) {
  const site = SITES[msg.site] ? msg.site : null;
  if (!site) return;
  try {
    const tab = await api.tabs.create({ url: SITES[site].url, active: true });
    pendingPackages.set(tab.id, { msg, until: Date.now() + 90000 });
    await focusTab(tab).catch(() => {});
  } catch (_e) {
    post({ type: "package_result", ok: false, site });
  }
}

// ------------------------------------------------------------------ messaggi dalle pagine
api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return;
  const tab = sender.tab;
  const site = tab ? siteOfUrl(tab.url || sender.url || "") : null;
  switch (msg.type) {
    case "status":
      if (!port) connect();
      sendResponse(status());
      return;
    case "launch":
      sendResponse({ ok: post({ type: "launch" }) });
      return;
    case "reconnect":
      if (port) { try { port.disconnect(); } catch (_e) { /* già chiuso */ } port = null; }
      retryDelay = 2000;
      connect();
      sendResponse(status());
      return;
    case "ready": {
      if (tab && site) {
        if (tab.active) activeTab[site] = tab.id;
        const pending = pendingPackages.get(tab.id);
        if (pending) {
          pendingPackages.delete(tab.id);
          if (Date.now() < pending.until) {
            activeTab[site] = tab.id;
            post({ type: "active", site, tab: tab.id });
            sendToTab(tab.id, { type: "paste_package", text: pending.msg.text, images: pending.msg.images || [] });
          }
        }
      }
      sendResponse(status());
      return;
    }
    default:
      break;
  }
  if (!FORWARD.has(msg.type) || !tab || !site) return;
  activeTab[site] = tab.id;
  const out = { ...msg, site, tab: tab.id };
  if (msg.type === "active" && !appConnected) {
    post(out); // l'host lo tiene da parte finché Helpix non si collega
    return;
  }
  const ok = post(out);
  sendResponse({ ok, host: hostState, app: appConnected });
});

api.tabs.onRemoved.addListener((tabId) => {
  pendingPackages.delete(tabId);
  for (const [site, id] of Object.entries(activeTab)) {
    if (id === tabId) {
      delete activeTab[site];
      if (port) post({ type: "tab_closed", site, tab: tabId });
    }
  }
});

// Chrome non inietta gli script nelle schede già aperte quando l'estensione viene installata
api.runtime.onInstalled?.addListener(async () => {
  if (!api.scripting) return;
  const tabs = await api.tabs.query({ url: ALL_MATCHES }).catch(() => []);
  for (const tab of tabs) {
    api.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] }).catch(() => {});
  }
});

api.runtime.onStartup?.addListener(connect);
connect();
updateBadge();
