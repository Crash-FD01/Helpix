// SPDX-FileCopyrightText: 2026 Crash
// SPDX-License-Identifier: GPL-3.0-or-later
// Test del servizio di segnalazione senza Cloudflare né GitHub: node tools/segnalazioni/test_worker.mjs
import assert from "node:assert/strict";
import worker, { clean, issue, validate } from "./worker.js";

const good = { app: "helpix", version: "0.19.4", os: "windows", title: "Il salvataggio non si apre",
               body: "## Cosa è successo\n\nniente anteprima, vedi @qualcuno" };
let sent = null;
globalThis.fetch = async (url, init) => {
  sent = { url, init, body: JSON.parse(init.body) };
  return new Response(JSON.stringify({ number: 7 }), { status: 201 });
};
const env = { GITHUB_TOKEN: "x", GITHUB_REPO: "Crash-FD01/helpix-segnalazioni" };
const post = (data, extra = {}) => new Request("https://w.example/segnala", {
  method: "POST", headers: { "content-type": "application/json", "cf-connecting-ip": "1.2.3.4", ...extra },
  body: typeof data === "string" ? data : JSON.stringify(data),
});

// validazione
assert.equal(validate(good), null);
assert.match(validate({ ...good, app: "altro" }), /app/);
assert.match(validate({ ...good, os: "mac" }), /sistema/);
assert.match(validate({ ...good, version: "<script>" }), /versione/);
assert.match(validate({ ...good, body: "x".repeat(60_001) }), /lunga/);
assert.match(validate({ ...good, title: " " }), /titolo/);
assert.match(validate([]), /formato/);

// menzioni inerti, caratteri di controllo tolti, etichette
assert.equal(clean("ciao @crash \u0007", 100), "ciao @​crash ");
const is = issue(good);
assert.ok(is.body.startsWith("**Helpix 0.19.4** · windows"));
assert.ok(is.body.includes("@​qualcuno") && !is.body.includes("@qualcuno"));
assert.deepEqual(is.labels, ["segnalazione", "windows"]);

// percorso felice: issue nel repo privato con il gettone del Worker
let r = await worker.fetch(post(good), env);
assert.equal(r.status, 201);
assert.deepEqual(await r.json(), { number: 7 });
assert.equal(sent.url, "https://api.github.com/repos/Crash-FD01/helpix-segnalazioni/issues");
assert.equal(sent.init.headers.authorization, "Bearer x");
assert.equal(sent.body.title, "Il salvataggio non si apre");

// richieste sbagliate
sent = null;
assert.equal((await worker.fetch(new Request("https://w.example/segnala"), env)).status, 405);
assert.equal((await worker.fetch(new Request("https://w.example/altro", { method: "POST" }), env)).status, 404);
assert.equal((await worker.fetch(post("{rotto", {}), env)).status, 400);
assert.equal((await worker.fetch(post(good, { "content-type": "text/plain" }), env)).status, 415);
assert.equal((await worker.fetch(post({ ...good, body: "x".repeat(90_000) }), env)).status, 413);
assert.equal((await worker.fetch(post(good), {})).status, 503);
assert.equal(sent, null, "nessuna chiamata a GitHub per le richieste rifiutate");

// limiti: per IP e complessivo
const no = { limit: async () => ({ success: false }) }, yes = { limit: async () => ({ success: true }) };
assert.equal((await worker.fetch(post(good), { ...env, PER_IP: no, TUTTI: yes })).status, 429);
assert.equal((await worker.fetch(post(good), { ...env, PER_IP: yes, TUTTI: no })).status, 429);
assert.equal((await worker.fetch(post(good), { ...env, PER_IP: yes, TUTTI: yes })).status, 201);

// GitHub che rifiuta (gettone scaduto): errore chiaro, senza contenuti
globalThis.fetch = async () => new Response("{}", { status: 401 });
r = await worker.fetch(post(good), env);
assert.equal(r.status, 502);
assert.match((await r.json()).error, /401/);

console.log("ok worker");
