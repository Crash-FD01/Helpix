<!-- SPDX-FileCopyrightText: 2026 Crash
     SPDX-License-Identifier: GPL-3.0-or-later -->
# Sicurezza / Security

## Segnalare una vulnerabilità

**Non aprire una issue pubblica.** Usa la segnalazione privata di GitHub:
[Security › Report a vulnerability](https://github.com/Crash-FD01/Helpix/security/advisories/new).

Indica la versione (`helpix --version`), come l'hai installato e i passi per riprodurre il problema. Ricevi una
prima risposta entro una settimana; la correzione esce con una nuova versione e, quando serve, un avviso di
sicurezza che riconosce il tuo contributo (se lo desideri).

*Please report vulnerabilities privately through GitHub's "Report a vulnerability" button, not in a public issue.
Italian or English are both fine.*

## Versioni supportate

Solo l'ultima versione riceve correzioni. Con il repository di Helpix l'aggiornamento arriva con quelli del
sistema.

## Cosa rientra

Per esempio:
- comandi eseguiti senza che l'utente li abbia confermati, o che aggirano gli avvisi sui comandi rischiosi;
- dati (screenshot, output, chiavi API) inviati a qualcuno diverso dal servizio scelto dall'utente;
- il filtro privacy che lascia passare segreti che dovrebbe riconoscere;
- il blocco con polkit o l'export cifrato aggirabili;
- socket locali, file o permessi che un altro utente dello stesso PC può usare;
- pacchetti o repository: firme non verificate, file scritti in posti sbagliati.

Non rientrano i problemi dei servizi IA stessi (ChatGPT, Claude, Gemini…): vanno segnalati a loro.

## Verificare i pacchetti

I repository APT e RPM e il file `SHA256SUMS` di ogni release sono firmati con la chiave in
`packaging/signing-key.asc`. Il gestore dei pacchetti verifica da solo la firma; a mano:

```bash
gpg --import packaging/signing-key.asc
gpg --verify SHA256SUMS.asc SHA256SUMS && sha256sum -c --ignore-missing SHA256SUMS
```
