<!-- SPDX-FileCopyrightText: 2026 Crash -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Servizio di segnalazione

«Segnala un problema» in Helpix prepara una segnalazione (versione, sistema, impostazioni, ultime righe dei
registri, stato del vault **senza contenuti**), la passa dal filtro privacy e la mostra all'utente. Con
«Invia» la manda a questo piccolo servizio, che la apre come issue in un **repo privato**.

```
Helpix ──POST JSON──▶ Cloudflare Worker (gettone segreto) ──▶ issue in Crash-FD01/helpix-segnalazioni
```

- Il gettone di GitHub sta solo nel Worker, come segreto: Helpix è open source e non contiene segreti.
- Il Worker accetta solo POST JSON su `/segnala`, al massimo 80 KB, 3 segnalazioni al minuto per IP e
  20 al minuto in tutto; rende inerti le menzioni `@`; non salva niente e non registra gli IP.
- Costo: zero. Il piano gratuito di Workers regge 100.000 richieste al giorno.
- Senza servizio, o se non risponde, Helpix permette di salvare la segnalazione come file `.md`.

## Messa in servizio (una volta)

1. **Repo privato** per le segnalazioni:
   `gh repo create Crash-FD01/helpix-segnalazioni --private`
   e, nel repo, le etichette `segnalazione`, `windows`, `linux`.
2. **Gettone** fine-grained (GitHub › Settings › Developer settings › Fine-grained tokens):
   - Repository access: *Only select repositories* › `helpix-segnalazioni`
   - Permissions › Repository › **Issues: Read and write** (nient'altro)
   - Scadenza: la più lunga consentita; segnati quando rinnovarlo (a gettone scaduto il servizio risponde
     502 e Helpix propone di salvare il file).
3. **Cloudflare** (account gratuito), da questa cartella:
   ```
   npx wrangler login
   npx wrangler deploy
   npx wrangler secret put GITHUB_TOKEN      # incolla il gettone del punto 2
   ```
   `deploy` stampa l'indirizzo, del tipo `https://helpix-segnalazioni.<nome>.workers.dev`.
4. **Prova**:
   ```
   curl -s https://helpix-segnalazioni.<nome>.workers.dev/segnala -H 'content-type: application/json' \
     -d '{"app":"helpix","version":"0.19.4","os":"linux","title":"Prova","body":"prova del servizio"}'
   ```
   Risponde `{"number": 1}` e la issue compare nel repo privato.
5. **Helpix**: metti l'indirizzo completo (con `/segnala`) in `REPORT_URL` in `helpix/report.py`. Per
   provarlo prima di un rilascio basta la variabile d'ambiente `HELPIX_REPORT_URL`.

## Test

`node tools/segnalazioni/test_worker.mjs` (anche dentro `tests/test_report.py`): validazione, limiti,
menzioni, errori di GitHub, senza rete.

## Leggere le segnalazioni con Claude

In una sessione di Claude Code collega anche il repo privato `Crash-FD01/helpix-segnalazioni`: le issue si
leggono con `gh api repos/Crash-FD01/helpix-segnalazioni/issues`, e la correzione va poi in una PR su Helpix.
