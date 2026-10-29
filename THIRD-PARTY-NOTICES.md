<!-- SPDX-FileCopyrightText: 2026 Crash
     SPDX-License-Identifier: GPL-3.0-or-later -->
# Componenti di terzi

Helpix è distribuito con licenza **GPL-3.0-or-later** (file `LICENSE`). Usa questi componenti di terzi, tutti con
licenze compatibili. I testi completi sono nella cartella `LICENSES/`.

## Inclusi nel codice di Helpix

| Componente | Dove | Licenza | Copyright |
|---|---|---|---|
| xterm.js 5.5.0 e addon fit | `helpix/data/xterm/` | MIT | The xterm.js authors, SourceLair Private Company, Christopher Jeffrey |
| Inter | `helpix/data/fonts/Inter-Variable.ttf` | SIL Open Font License 1.1 | The Inter Project Authors |
| JetBrains Mono | `helpix/data/fonts/JetBrainsMono-*.ttf` | SIL Open Font License 1.1 | The JetBrains Mono Project Authors |

I file con la licenza originale e le note di copyright restano accanto ai componenti
(`LICENSE-xterm.txt`, `OFL-Inter.txt`, `OFL-JetBrainsMono.txt`) e vengono installati con Helpix.

## Installati a parte (pip li scarica dai loro autori)

Non sono inclusi nel codice di Helpix: `install.sh` li installa da PyPI, ciascuno con la propria licenza.

| Componente | Licenza |
|---|---|
| PySide6 / Qt for Python (Essentials, Addons, WebEngine), Qt 6, Qt WebEngine (basato su Chromium) | LGPL-3.0 (Qt WebEngine include componenti di Chromium con licenze BSD e altre: vedi la documentazione di Qt) |
| requests | Apache-2.0 |
| keyring | MIT |
| cryptography | Apache-2.0 o BSD-3-Clause |
| jeepney | MIT |

Helpix usa Qt solo come libreria, tramite PySide6, senza modificarla: chi la riceve può sostituirla con
un'altra versione, come chiede la LGPL.

## Inclusi nei pacchetti .deb e .rpm

I pacchetti dei repository (`/opt/helpix`) contengono, oltre a Helpix, un proprio Python e le librerie qui sopra,
così funzionano allo stesso modo su ogni distribuzione:

| Componente | Licenza |
|---|---|
| Python ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)) con le sue librerie (OpenSSL, SQLite, libffi, zlib, xz, bzip2…) | PSF-2.0 e licenze delle librerie, tutte permissive |
| Qt 6, Qt WebEngine (Chromium), PySide6, Shiboken6 | LGPL-3.0-only (Chromium: BSD e altre) |
| requests, urllib3, idna, certifi, charset-normalizer, keyring, SecretStorage, jeepney, cryptography, cffi, pycparser | Apache-2.0, MIT, BSD, MPL-2.0 (certifi) |

Ogni pacchetto installa `/usr/share/licenses/helpix/BUNDLED-COMPONENTS.txt` con le versioni esatte, i link ai sorgenti
completi di Qt e Python e il comando per sostituire Qt con un'altra versione; i testi delle licenze sono in
`/usr/share/licenses/helpix/` e nelle cartelle `*.dist-info` delle librerie Python. Le licenze dei componenti di
Chromium contenuti in Qt WebEngine sono elencate nella
[documentazione di Qt](https://doc.qt.io/qt-6/qtwebengine-licensing.html).

## Marchi

ChatGPT, Codex e OpenAI sono marchi di OpenAI; Claude, Claude Code e Anthropic di Anthropic; Gemini e Google di
Google; Copilot e Microsoft di Microsoft; DeepSeek di DeepSeek. Helpix non è affiliato a queste aziende, né
approvato da loro. I nomi servono solo a indicare con quali servizi funziona.

I loghi dei servizi non sono inclusi in Helpix: li scarica il programma, al primo avvio, dai siti stessi
(le icone che ogni sito pubblica per i browser) e li tiene in una cartella del tuo utente. Gli screenshot nella
cartella `docs/` mostrano quei loghi così come compaiono nel programma.
