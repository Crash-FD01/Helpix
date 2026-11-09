// SPDX-FileCopyrightText: 2026 Crash
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Servizio di segnalazione di Helpix (Cloudflare Workers, piano gratuito).
//
// Riceve da Helpix la segnalazione già filtrata e riletta dall'utente e la apre come issue in un repo
// PRIVATO. Il gettone di GitHub sta solo qui, come segreto del Worker (GITHUB_TOKEN): mai nell'app,
// che è open source. L'indirizzo del Worker è pubblico, quindi: solo POST JSON, dimensioni limitate,
// limite per IP e complessivo, menzioni @ disattivate. Non salva niente: niente IP, niente registri propri.
//
// Variabili: GITHUB_REPO (es. "Crash-FD01/helpix-segnalazioni"); segreto: GITHUB_TOKEN (fine-grained,
// solo quel repo, permesso Issues: lettura e scrittura). Limiti: binding PER_IP e TUTTI in wrangler.toml.

const MAX_REQUEST = 80_000;   // byte della richiesta
const MAX_TITLE = 120;
const MAX_BODY = 60_000;      // le issue arrivano a 65536 caratteri

function reply(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

// toglie i caratteri di controllo e rende inerti menzioni e riferimenti: nessuna notifica a nessuno
export function clean(text, max) {
  return String(text ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
    .replace(/@(?=[A-Za-z0-9-])/g, "@​")
    .slice(0, max);
}

export function validate(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return "formato non valido";
  if (data.app !== "helpix") return "app sconosciuta";
  if (typeof data.version !== "string" || !/^\d+\.\d+(\.\d+)?([.+-][\w.]+)?$/.test(data.version)) return "versione non valida";
  if (data.os !== "windows" && data.os !== "linux") return "sistema non valido";
  if (typeof data.title !== "string" || !data.title.trim()) return "titolo mancante";
  if (typeof data.body !== "string" || !data.body.trim()) return "testo mancante";
  if (data.title.length > MAX_TITLE || data.body.length > MAX_BODY) return "segnalazione troppo lunga";
  return null;
}

export function issue(data) {
  const title = clean(data.title.replace(/\s+/g, " ").trim(), MAX_TITLE);
  const head = `**Helpix ${clean(data.version, 40)}** · ${data.os} · ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC\n\n`;
  return {
    title,
    body: head + clean(data.body, MAX_BODY),
    labels: ["segnalazione", data.os],
  };
}

async function limited(env, ip) {
  // i binding mancano solo in prova locale: senza, si lascia passare
  for (const [binding, key] of [[env.PER_IP, ip], [env.TUTTI, "tutti"]]) {
    if (binding && !(await binding.limit({ key })).success) return true;
  }
  return false;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/segnala") return reply(404, { error: "non trovato" });
    if (request.method !== "POST") return reply(405, { error: "solo POST" });
    if (!(request.headers.get("content-type") || "").includes("application/json")) {
      return reply(415, { error: "serve JSON" });
    }
    const size = Number(request.headers.get("content-length") || 0);
    if (size > MAX_REQUEST) return reply(413, { error: "segnalazione troppo grande" });
    const ip = request.headers.get("cf-connecting-ip") || "?";
    if (await limited(env, ip)) return reply(429, { error: "troppe segnalazioni, riprova più tardi" });

    const raw = await request.text();
    if (raw.length > MAX_REQUEST) return reply(413, { error: "segnalazione troppo grande" });
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return reply(400, { error: "JSON non valido" });
    }
    const problem = validate(data);
    if (problem) return reply(400, { error: problem });
    if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return reply(503, { error: "servizio non configurato" });

    const gh = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "helpix-segnalazioni",
        "content-type": "application/json",
      },
      body: JSON.stringify(issue(data)),
    });
    if (!gh.ok) {
      console.log("GitHub ha risposto", gh.status);   // solo il codice: niente contenuti nei registri
      return reply(502, { error: `GitHub non ha accettato la segnalazione (${gh.status})` });
    }
    const created = await gh.json();
    return reply(201, { number: created.number });
  },
};
