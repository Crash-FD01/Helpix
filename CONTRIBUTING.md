<!-- SPDX-FileCopyrightText: 2026 Crash
     SPDX-License-Identifier: GPL-3.0-or-later -->
# Contribuire a Helpix

Grazie per l'interesse! Segnalazioni, idee e pull request sono benvenute, in italiano o in inglese.
*Contributions are welcome in Italian or English.*

## Segnalare un problema

Apri una [issue](https://github.com/Crash-FD01/Helpix/issues/new/choose) con versione (`helpix --version`),
distribuzione, desktop e sessione (Wayland o X11). Prima di allegare log o screenshot controlla che non
contengano password, token o dati personali.

Le vulnerabilità di sicurezza vanno segnalate in privato: vedi [SECURITY.md](SECURITY.md).

## Preparare l'ambiente

```bash
git clone https://github.com/Crash-FD01/Helpix.git helpix && cd helpix
python3 -m venv .venv && . .venv/bin/activate
pip install -e . ruff reuse
python -m helpix.sysdeps install      # librerie di sistema che servono a Qt, se mancano
python -m helpix
```

## Prima di aprire una pull request

```bash
ruff check .          # stile e regole di sicurezza (niente shell=True, timeout sulle richieste…)
reuse lint            # ogni file ha autore e licenza
tests/run_all.sh      # tutti i test
```

La CI li ripete su ogni pull request, con Python 3.10 e 3.13.

Alcune regole del progetto:
- **Helpix agisce solo quando l'utente preme un pulsante.** Niente invii, letture o comandi automatici in più
  rispetto a quelli descritti nella [guida](docs/GUIDA.md).
- **Ogni funzione di sicurezza o privacy è facoltativa** e si può disattivare.
- Non aggirare i blocchi dei siti (per esempio quello di Google sui browser integrati): niente user agent finti,
  niente cookie importati.
- I testi visibili passano da `tr()` (`helpix/i18n.py`): aggiungi la traduzione inglese nel catalogo.
- I file nuovi hanno l'intestazione SPDX:
  ```python
  # SPDX-FileCopyrightText: 2026 Il tuo nome
  # SPDX-License-Identifier: GPL-3.0-or-later
  ```
- Mai nel repository: chiavi private (`*.pem`, chiave di firma dei pacchetti), token, dati personali.

Contribuendo accetti che il tuo codice sia distribuito con la licenza del progetto, GPL-3.0-or-later.

## Pubblicare una versione (manutentori)

1. Aggiorna `version` in `pyproject.toml` e `__version__` in `helpix/__init__.py`, aggiungi la release in
   `packaging/io.github.crash_fd01.helpix.metainfo.xml` e la riga nella Roadmap di `docs/GUIDA.md`.
2. Commit e push su `main`; aspetta che la CI sia verde.
3. Tag e push:
   ```bash
   git tag -a v0.15.1 -m "Helpix 0.15.1" && git push origin v0.15.1
   ```
4. Il workflow **Rilascio** (circa 15 minuti):
   - costruisce i pacchetti x86_64 e aarch64 e li prova installati;
   - li firma e crea la release con `SHA256SUMS` firmato;
   - aggiorna il repository APT (release `repo`), i metadati RPM e il sito su GitHub Pages.

   Da quel momento `apt upgrade`, `dnf upgrade` e `zypper update` trovano la nuova versione (dnf entro 6 ore,
   o subito con `dnf upgrade --refresh`).

Per ripubblicare una versione già taggata (per esempio dopo aver cambiato il sito): *Actions › Rilascio ›
Run workflow*, indicando il tag.

**Chiave di firma.** La privata sta solo nel secret `HELPIX_GPG_PRIVATE_KEY` e nella copia di backup creata da
`packaging/github-setup.sh`; la pubblica è in `packaging/signing-key.asc` e sul sito. Se la perdi o viene
compromessa: generane una nuova, aggiorna il secret e ripubblica. Chi ha già il repository dovrà rieseguire lo
script di installazione per importare la chiave nuova.

**Windows:** l'installer lo costruisce il workflow di rilascio. A mano, su un PC Windows con Python 3.13:
`pwsh packaging\windows\build.ps1` (crea `dist\packages\Helpix-<versione>-Setup.exe`). I test girano anche lì:
`bash tests/run_all.sh python` da Git Bash.

**Prova locale dei pacchetti:**

```bash
packaging/build-packages.sh x86_64                     # dist/packages/*.deb, *.rpm
GPG_KEY_ID=<impronta> packaging/update-repos.sh dist/packages /tmp/repo <URL dei .rpm> <URL del sito>
```
