"use strict";
const api = globalThis.browser ?? globalThis.chrome;
const t = (k) => api.i18n.getMessage(k) || k;
const $ = (id) => document.getElementById(id);

function show(st) {
  if (!st) return;
  const state = $("state");
  const missing = st.host === "missing" || st.host === "error";
  state.textContent = st.app ? `${t("statusOn")}${st.appVersion ? ` · ${st.appVersion}` : ""}` : t(missing ? "statusMissing" : "statusApp");
  state.className = `state ${st.app ? "ok" : missing ? "err" : ""}`;
  $("help").textContent = t(st.app ? "popupOnHelp" : missing ? "popupMissingHelp" : "popupAppHelp");
  $("launch").hidden = st.app || missing;
  $("retry").hidden = !missing;
  $("detail").textContent = missing && st.error ? st.error : "";
}

async function refresh(type = "status") {
  try {
    show(await api.runtime.sendMessage({ type }));
  } catch (_e) { /* il servizio dell'estensione si sta riavviando */ }
}

$("launch").textContent = t("launch");
$("retry").textContent = t("reconnect");
$("pillLabel").textContent = t("showPill");
$("privacy").textContent = t("privacy");
$("launch").addEventListener("click", async () => {
  await api.runtime.sendMessage({ type: "launch" }).catch(() => {});
  setTimeout(refresh, 2500);
});
$("retry").addEventListener("click", () => refresh("reconnect").then(() => setTimeout(refresh, 800)));
const store = api.storage.local;
Promise.resolve(store.get("showPill")).then((v) => { $("pill").checked = (v && v.showPill) !== false; });
$("pill").addEventListener("change", (e) => store.set({ showPill: e.target.checked }));
refresh();
setInterval(refresh, 2000);
