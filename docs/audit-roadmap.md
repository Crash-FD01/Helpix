# Helpix: revisione completa e piano di compatibilità

> **Stato (v0.12.0):**
> - Priorità a completare la versione Linux; Windows e macOS (§4) sono rimandati.
> - Fatti in v0.12: filtro privacy con pulsante on/off e dipendenze di sistema installate da sole.
>
> La revisione del §1 si riferisce alla v0.11.5.

## 0. Pacchetti e repository (v0.15.0)

**Come funziona**
- `packaging/build-packages.sh` costruisce un .deb e un .rpm autonomi: in `/opt/helpix` ci sono un Python proprio
  (python-build-standalone) e un ambiente isolato con Qt 6.12, i moduli già compilati e nessuno strumento per
  sviluppatori. Le librerie di sistema che servono a Qt diventano dipendenze del pacchetto: il .deb le ricava con
  `dpkg -S` (la build si ferma se una non ha un pacchetto noto), l'.rpm le chiede per nome della libreria, quindi
  vale per Fedora, RHEL e openSUSE. La glibc minima è calcolata dai file inclusi (2.34 su x86_64, 2.39 su ARM).
- `packaging/update-repos.sh` firma gli .rpm e prepara due repository firmati con la stessa chiave:
  - APT «piatto» (InRelease, Release.gpg) nella release `repo` di GitHub;
  - metadati RPM (repomd.xml.asc) su GitHub Pages, con i pacchetti lasciati sulla release della versione
    (`xml:base`).
  I pacchetti (~200 MB) superano il limite dei file di Pages, quindi restano sulle release.
- Il sito (`site/`) ha la pagina di installazione e `setup.sh`, che aggiunge il repository giusto (apt, dnf,
  zypper, rpm-ostree), controlla architettura e glibc e con `--remove` toglie tutto.
- Il workflow `.github/workflows/release.yml` fa tutto al push di un tag `vX.Y.Z`: build x86_64 e aarch64,
  prova del pacchetto installato, firma, release, repository e sito.
- `packaging/github-setup.sh` crea e configura il repository GitHub (Pages, ambiente, chiave di firma nel secret,
  tag) in un solo comando.

**Verificato in locale** (server HTTP con la stessa struttura di GitHub)
- Installazione con `curl … | sudo sh` da sistema pulito, avvio da utente normale (nessun file scritto in
  `/opt`), `apt upgrade` a una versione nuova, `--remove` senza residui.
- dnf: metadati firmati verificati, dipendenze lette, pacchetto scaricato dall'indirizzo della release con firma
  valida (`rpm -K`).
- GitHub accetta i percorsi `./InRelease` che apt richiede ai repository piatti.
- `github-setup.sh` provato con un `gh` finto e un repository git locale, anche la seconda volta (salta quello
  che è già fatto) e con un nome utente diverso (aggiorna indirizzi e ID dell'app; i test restano verdi).
- Workflow controllati con `actionlint`.

**Corretto durante la verifica**
- Il pacchetto non trovava `requests`: la build riusava le librerie Python dell'utente. Ora usa un ambiente isolato.
- Senza moduli precompilati, Python li avrebbe ricompilati a ogni avvio (l'utente non può scrivere in `/opt`).
- La build funzionava solo se `/opt/helpix` esisteva già sulla macchina: su GitHub Actions sarebbe fallita.
- I pacchetti ora includono le note e le licenze dei componenti inclusi (Python, Qt LGPL con i link ai sorgenti).
- **Qt for Python 6.12.0 con Python 3.10/3.11** toglie un riferimento a `None` a ogni chiamata senza risultato
  (`setText`, `show`, `resize`, timer…): dopo circa 5000 chiamate Python si chiude («deallocating None»). Da 3.12
  `None` è immortale e non succede. Colpiva l'installazione dai sorgenti su Ubuntu 22.04, Mint 21 e Debian 12.
  Ora `pyproject.toml` chiede Qt 6.12 solo da Python 3.12 e altrimenti 6.8–6.11 (pip sceglie la 6.11 con glibc
  ≥ 2.34): 6.11.3, 6.9.3 e 6.8.0.2 provate senza perdite, suite completa verde con Python 3.11 e Qt 6.11.3.
  `tests/test_qt_refcount.py` lo controlla (in CI anche con Python 3.10). I pacchetti .deb/.rpm usano Python 3.13
  e non erano colpiti. Da ricontrollare quando esce una 6.12.x successiva.

**Corretto con la prima esecuzione su GitHub Actions** (CI e prova dei pacchetti x86_64 e aarch64 ora verdi)
- Su Ubuntu 24.04+ e Debian 13 `libasound2`, `libcups2`, `libglib2.0-0` e `libminizip1` esistono solo come
  pacchetti virtuali (i veri hanno il suffisso `t64`): l'installazione automatica delle dipendenze falliva. Ora
  `sysdeps.apt_name()` sceglie il nome installabile.
- Il controllo delle librerie guardava tutti i moduli Python di Qt, anche quelli che Helpix non usa (Multimedia,
  Nfc): su un sistema senza audio o smart card chiedeva libpulse e libpcsclite. Ora solo i moduli usati.
- Su aarch64 Qt WebEngine usa librerie di sistema (opus, webp, lcms2, snappy…) che su x86_64 sono incluse: aggiunte
  alla tabella per tutti e quattro i gestori di pacchetti.
- La protezione dei segreti di GitHub bloccava il caricamento per le chiavi finte del corpus di prova del filtro
  privacy: ora le stringhe sono spezzate nel sorgente (Python le riunisce), il test controlla le stesse cose.
- `test_quit` dipendeva dal nome della cartella del progetto.
- In CI, se un passo fallisce, le ultime righe finiscono in un'annotazione (`.github/scripts/annotate.sh`).

**v0.15.1** — Il .deb 0.15.0 costruito su GitHub dipendeva da `firefox`: sulla macchina di build `dpkg -S` trovava
`libnspr4.so` anche dentro Firefox. Ora contano solo le cartelle di sistema delle librerie e la build si ferma se
una dipendenza non è una libreria (`tests/test_packaging.py`). Verificato installando dal repository pubblico.

**v0.15.2** — Su Fedora 44 dnf rifiutava l'.rpm: «nothing provides libc.so.6(GLIBC_2.34)(64bit)». La glibc minima ora
è richiesta come pacchetto (`Requires: glibc >= 2.34`, 2.38 su ARM), che ha lo stesso nome su Fedora, RHEL e
openSUSE. Trovato da Crash installando con `setup.sh` sul suo Fedora.

## 0.1 Prima versione pubblica (v0.14.0)

**Revisione finale prima della pubblicazione**
- Lint esteso con le regole di sicurezza: nessun `shell=True`, nessuna richiesta senza timeout, nessuna verifica
  TLS disattivata, nessun file temporaneo insicuro.
- Nessun dato personale o segreto nel codice; residui di debug assenti.
- Il pacchetto contiene tutti i file necessari.
- `.desktop` e metadati AppStream validati (`desktop-file-validate`, `appstreamcli validate --pedantic`).
- Primo avvio reale da configurazione vuota: nessuna eccezione, log senza errori.
- Installazione e disinstallazione provate da zero.
- Test (76) verdi con Qt 6.12 e Qt 6.8.

**Corretto in questa revisione**
- `helpix --help` apriva il programma invece di mostrare l'aiuto.
- `uninstall.sh` lasciava la scorciatoia Ctrl+Alt+H nelle impostazioni del desktop (puntava a un comando che non
  esisteva più), il lanciatore di KDE e la finestra rapida in esecuzione. Con `--purge` ora cancella anche le
  chiavi API dal portachiavi.
- Il file `.desktop` aveva due categorie principali (l'app poteva comparire due volte nel menu).

**Licenza**
- GPL-3.0-or-later, © 2026 Crash. Progetto conforme a REUSE 3.3: `reuse lint` verifica che ogni file abbia
  autore e licenza.
- `LICENSE`, `LICENSES/`, `REUSE.toml`, `THIRD-PARTY-NOTICES.md`, metadati AppStream (CC0-1.0).
- La finestra «Informazioni» mostra licenza, assenza di garanzia e indirizzo dei sorgenti.

## 1. Esito della revisione

**Controlli eseguiti:**
- **Test automatici:** tutte le 14 suite, 44 test, in verde. Coprono:
  - motore web, incolla e screenshot;
  - riepilogo e passaggio del task;
  - agenti nel terminale;
  - finestra rapida e scorciatoia globale (con un portal finto su D-Bus);
  - tray, blocco ed export cifrato.
- **ruff** (errori, bug, nomi inesistenti): pulito. Anche i controlli di sicurezza S/PLW sono stati verificati a mano.
- **vermin:** il codice gira con Python ≥ 3.8; il minimo dichiarato resta 3.9.

**Problemi trovati e corretti:**

| # | Problema | Rischio | Correzione |
|---|---|---|---|
| 1 | Senza `XDG_RUNTIME_DIR` i socket finivano in `/tmp/helpix-UID`. Capita con `su`, in alcuni container, nelle sessioni senza systemd-logind e su distro senza systemd. | Un altro utente poteva creare prima la cartella e intercettare i messaggi (finestra rapida, istanza unica). | Ripiego in `~/.cache/helpix-run` con permessi 0700. |
| 2 | Il pseudo-terminale degli agenti usava `preexec_fn` in un processo con thread. | Possibile blocco (deadlock) all'avvio di un agente. Python lo sconsiglia. | Avvio con `setsid --ctty`, che c'è in util-linux su tutte le distro; `preexec_fn` resta solo come ripiego. |
| 3 | `install.sh` usava solo `python3`. | Su RHEL/Alma/Rocky 8 e openSUSE Leap `python3` è il 3.6, quindi l'installazione falliva. | Sceglie il Python più recente tra `python3.14` e `python3.9`. Avvisa su architettura non supportata, glibc < 2.28 o musl (Alpine) e assenza di `libxcb-cursor`, con il comando giusto per ogni distro. |
| 4 | La finestra rapida forzava XWayland anche senza `libxcb-cursor`. | Qt 6 non parte su xcb senza quella libreria: la finestra rapida non si apriva. | Usa XWayland solo se la libreria c'è; altrimenti resta su Wayland. |
| 5 | Blocco attivo ma regola polkit sparita (reinstallazione, aggiornamento di una distro immutabile). | `pkcheck` rifiuta sempre lo sblocco: l'utente restava chiuso fuori. | Senza regola Helpix si apre senza blocco. Coperto da un test. |
| 6 | Il README diceva che il riepilogo è «l'unica eccezione» all'invio automatico. | Informativa incompleta: anche la finestra rapida invia e legge le risposte. | README corretto. Sistemata anche la sezione dell'estensione, che è messa da parte. |

**Cose da tenere d'occhio** (non sono bug):
- I selettori delle pagine di chat (`_INSERT_JS`, `_SEND_JS`, `_ANSWER_JS`) dipendono dalla struttura dei siti, che cambia spesso: è il punto più fragile del programma (vedi §4).
- L'invio e la lettura automatici (riepilogo e finestra rapida) restano un'automazione sull'account dell'utente: va mantenuta l'informativa sui termini d'uso.

## 2. Compatibilità Linux (verifica di v0.13.4)

**Come è stata verificata**
- **Qt:** tutta la suite di test (73 test) gira con Qt 6.12 (Python 3.13) e con Qt 6.8.0.2 (Python 3.11), le
  due estremità che `install.sh` può installare. L'installazione «compatibile» è provata da zero simulando
  glibc 2.31.
- **Scorciatoia globale:** provata con gli schemi veri di GNOME, Cinnamon e MATE e con il vero `xfconfd`
  di Xfce; per COSMIC si scrive il suo file RON, provato con file vuoti, già pieni e malformati. In una
  sessione desktop vera è provata solo KDE Plasma 6 (Fedora 44, il PC dello sviluppatore).
- **Il resto** (screenshot, area di notifica, polkit) è verificato sul codice e sulla documentazione dei
  desktop, non in una sessione vera di ciascuno.

**Qt e distribuzioni.** PySide6 6.12 (Qt 6.12) si installa con pip solo con glibc ≥ 2.34 (≥ 2.39 su ARM)
e Python ≥ 3.10. Dove manca, `install.sh` installa da solo Qt 6.8/6.9, con cui Helpix funziona allo stesso
modo (tutti i test passano).

| Distribuzione (desktop predefinito) | Qt installato | Note |
|---|---|---|
| Fedora 40+ Workstation (GNOME) / KDE | 6.12 | Provata (Fedora 44 KDE) |
| Ubuntu 22.04, 24.04, 26.04 (GNOME); Kubuntu, Xubuntu… | 6.12 | Area di notifica: AppIndicator già presente |
| Linux Mint 21–22 (Cinnamon, Xfce, MATE), LMDE | 6.12 | **Scorciatoia corretta in questa versione** (prima finiva nelle impostazioni di GNOME) |
| Pop!_OS 24.04 (COSMIC) | 6.12 | Scorciatoia nel file delle scorciatoie di COSMIC |
| Zorin OS 17–18, elementary OS 8 (GNOME, Pantheon) | 6.12 | Scorciatoia con le impostazioni di GNOME |
| Debian 12, 13 (GNOME e altri), MX Linux (Xfce, senza systemd) | 6.12 | Su ARM Debian 12 usa 6.8 |
| Arch, CachyOS, EndeavourOS, Manjaro | 6.12 | |
| openSUSE Tumbleweed; Leap 16 | 6.12 | |
| RHEL/Alma/Rocky 9 | 6.12 con Python 3.11/3.12, altrimenti 6.9 | Prima con il Python 3.9 di sistema l'installazione falliva |
| RHEL/Alma/Rocky 8, Debian 11, Ubuntu 20.04, openSUSE Leap 15, Raspberry Pi OS 12 | 6.8/6.9 | Prima non si installava affatto |
| Bazzite, Aurora, Bluefin, Silverblue, Kinoite, SteamOS (immutabili) | 6.12 | Pacchetti di sistema: Helpix mostra `rpm-ostree install …`; niente blocco con polkit |
| NixOS, Alpine (musl) | — | Non supportate con pip |

**Desktop**

| Desktop | Scorciatoia globale (Ctrl+Alt+H) | Screenshot | Area di notifica | Password di amministratore |
|---|---|---|---|---|
| KDE Plasma 6 | Portal (conferma di KDE) + lanciatore | Spectacle o portal | Sì | Sì |
| GNOME 48+ | Portal (finestra di conferma) | Portal | Ubuntu sì; Fedora/Debian: Helpix installa e attiva AppIndicator (visibile dal prossimo accesso) | Sì |
| GNOME 42–47, Budgie, Pantheon, Zorin | Impostata da Helpix (gsettings) | Portal | Come sopra | Sì |
| Cinnamon (Mint) | Impostata da Helpix | Diretto (X11) o portal | Sì | Sì |
| MATE | Impostata da Helpix | Diretto (X11) | Sì | Sì |
| Xfce | Impostata da Helpix (xfconf) | Diretto (X11, xprop/xwininfo installati da `install.sh`) | Sì | Sì, se c'è un agente polkit (Mint e MX lo hanno) |
| COSMIC | Impostata da Helpix (file RON) | Portal | Applet dell'area di notifica | Sì |
| Hyprland, Sway, niri | Riga da copiare nella configurazione | Portal o grim+slurp | Con una barra che la supporta (waybar…) | Serve un agente polkit avviato (Helpix lo spiega se manca) |
| LXQt | Riga da aggiungere in Preferenze › Scorciatoie | Diretto (X11) | Sì | Sì |

**Corretto in questa verifica**
- **Linux Mint (Cinnamon):** la scorciatoia veniva scritta nelle impostazioni di GNOME, che Cinnamon non
  legge: Helpix diceva «fatto» ma non funzionava.
- **Xfce, MATE, COSMIC:** prima non c'era nessuna impostazione automatica.
- **Hyprland, Sway, niri, LXQt:** ora c'è la riga pronta da copiare.
- **Portal assente:** nei desktop dove Helpix sa impostare la scorciatoia, la imposta subito, senza
  passare da un'altra finestra.
- **RHEL 9 con Python 3.9 e distribuzioni con glibc < 2.34:** l'installazione falliva; ora usa Qt 6.8/6.9.
- **Area di notifica assente** (GNOME senza estensione): spariscono dal menu «Riduci nell'area di notifica»
  e «Chiudendo, resta nell'area di notifica», che non potevano funzionare.
- **Agente polkit mancante** (Hyprland, Sway, niri): Helpix spiega cosa manca invece di dire
  «autorizzazione negata».
- **Riavvio per cambiare lingua con l'icona nell'area di notifica:** restava aperta la vecchia istanza.

**Da tenere presente**
- **GNOME su Fedora e Debian (v0.13.5):** l'area di notifica richiede l'estensione «AppIndicator and
  KStatusNotifierItem Support». `install.sh` e Impostazioni › Dipendenze di sistema la installano
  (`gnome-shell-extension-appindicator`) e la attivano per l'utente; al primo avvio Helpix lo propone una volta.
  - Su Ubuntu lo stesso pacchetto ha un altro identificativo (`ubuntu-appindicators@ubuntu.com`): Helpix li
    riconosce entrambi (provato con il pacchetto vero).
  - GNOME carica le estensioni nuove solo all'accesso: l'icona compare dopo essere usciti e rientrati.
  - Sui sistemi immutabili (Silverblue, Bluefin) il pacchetto va aggiunto con rpm-ostree o dal sito delle
    estensioni.
- **Finestra rapida in basso a destra su Wayland:** usa XWayland. Su compositor senza XWayland (alcune
  configurazioni di Hyprland o niri) la posizione la sceglie il desktop.
- **Angoli arrotondati:** su X11 senza compositing (Xfce o MATE con il compositing spento) gli angoli possono
  apparire neri; si disattivano da Impostazioni › Angoli arrotondati.

## 3. Pacchetti e distribuzione

Oggi l'installazione è `install.sh`: un venv nella home più `pip`, circa 300 MB. Funziona ovunque ci sia glibc, ma non si aggiorna da sola. In ordine di convenienza:

1. **AppImage** (un file per tutte le distro, x86_64 e aarch64).
   - Pro: è il modo più semplice per «persone normali»; contiene già Qt e `libxcb-cursor`.
   - Contro: niente aggiornamenti automatici senza AppImageUpdate.
2. **RPM su Copr** (Fedora, RHEL, Alma, Rocky) e **DEB su OBS** o un repository proprio.
   - Pro: aggiornamenti con il sistema; la regola polkit si installa con il pacchetto, quindi il blocco funziona senza chiedere la password.
   - Contro: va mantenuto un pacchetto per ogni famiglia di distro.
3. **Flatpak/Flathub**, solo dopo una valutazione.
   - Il sandbox impedisce di eseguire comandi sul sistema, che è la funzione centrale di Helpix.
   - Servirebbe `flatpak-spawn --host` (permesso `org.freedesktop.Flatpak`), che i revisori di Flathub accettano solo con una motivazione.
   - Su Silverblue e Bazzite è però il formato atteso.
4. **Nix**: pacchetto o flake, per NixOS.

Da aggiungere in ogni caso: un controllo facoltativo delle nuove versioni (GitHub Releases), con un avviso nell'app.

## 4. Windows e macOS (rimandato: prima si completa Linux)

La GUI (PySide6, QtWebEngine, tray, finestra rapida, portachiavi tramite keyring) è già multipiattaforma. La parte da riscrivere è tutto ciò che parla con il sistema. Il piano è un **livello di piattaforma** `helpix/platform/{linux,windows,macos}.py` con un'interfaccia comune, così il resto del codice non cambia.

| Componente | Linux (oggi) | Windows | macOS |
|---|---|---|---|
| Esecuzione dei comandi | bash + pkexec (polkit) | PowerShell; elevazione con UAC (`Start-Process -Verb RunAs`) | zsh; `osascript … with administrator privileges` |
| Analisi dei rischi | Regole bash (rm -r, dd, mkfs…) | Regole PowerShell e cmd: `Remove-Item -Recurse`, `Format-Volume`, `diskpart`, `reg delete`, `bcdedit` | Regole bash più `diskutil`, `csrutil`, `tmutil delete` |
| Diagnosi rapida | /proc, journalctl, systemctl | `Get-CimInstance`, `Get-WinEvent`, `Get-Service` | `system_profiler`, `log show`, `launchctl` |
| Terminale degli agenti | `os.openpty` | ConPTY con **pywinpty** | `os.openpty` (uguale a Linux) |
| Sblocco | polkit (password o impronta) | **Windows Hello** (`UserConsentVerifier`, pacchetto winrt) | **Touch ID o password** (LocalAuthentication via pyobjc) |
| Scorciatoia globale | Portal su D-Bus | `RegisterHotKey` (ctypes) | `RegisterEventHotKey` di Carbon (pyobjc, senza permesso di accessibilità) |
| Screenshot | Portal / X11 | Cattura Qt (funziona già) | Cattura Qt o `screencapture -i`; serve il permesso *Registrazione schermo* |
| Istanza unica e finestra rapida | Socket AF_UNIX | Da passare a `QLocalSocket` (named pipe), che funziona su tutti e tre | Come Windows |
| Cartelle | XDG | `QStandardPaths` (%APPDATA%) | `QStandardPaths` (~/Library/Application Support) |
| Bordi arrotondati | Disegnati da Helpix | Nativi su Windows 11 (DWM) | Nativi |
| Pacchetto | AppImage, rpm, deb | PyInstaller o Nuitka con installer Inno Setup o MSIX, **firma Authenticode** (senza firma SmartScreen blocca l'avvio), pubblicazione su winget | App `.app` arm64 + x86_64, **firma Developer ID e notarizzazione Apple** (Apple Developer Program a pagamento), Homebrew cask |

Le CLI degli agenti (Claude Code, Codex, Gemini CLI) vanno verificate su Windows una per una: requisiti e shell supportate cambiano spesso.

**Ordine consigliato:**
1. **Livello di piattaforma su Linux.** Si sposta il codice esistente dietro l'interfaccia e si passa l'IPC a `QLocalSocket`. Nessun cambiamento visibile; i test esistenti fanno da rete di sicurezza.
2. **CI su GitHub Actions** con matrice Ubuntu, Fedora (container), Windows e macOS, che fa girare i test in modalità offscreen.
3. **Windows, prima versione:**
   - motore web, screenshot, esecuzione PowerShell con UAC e regole di rischio;
   - tray, finestra rapida, scorciatoia;
   - installer firmato.
4. **Windows completo:** agenti con ConPTY, Windows Hello, diagnosi.
5. **macOS:** riusa gran parte del ramo Linux (bash, pty); il lavoro vero è firma, notarizzazione e permessi.

## 5. Altre implementazioni consigliate

**Priorità alta:**
- ~~**Filtro privacy prima di incollare.**~~ ✅ **Fatto in v0.12.**
  - Pulsante a scudo nella barra, spento di default.
  - Oscura segreti, token, chiavi, email, IP pubblici, MAC, utente e nome del PC nell'output dei comandi, nella diagnosi (con anteprima) e nel task passato a un'altra IA.
  - Segnaposti coerenti nella sessione; avviso con il numero di dati coperti.
- ✅ **Dipendenze installate da sole (v0.12).**
  - `install.sh` installa Python/venv se mancano.
  - Installa anche le librerie di Qt che mancano davvero (controllo con `ldd`) e gli strumenti per gli screenshot, con dnf, apt, pacman o zypper.
  - Lo stesso controllo è in *Impostazioni › Dipendenze di sistema…* (installa con pkexec).
  - La pagina degli agenti installa prima Node.js/npm e curl se mancano.
- **Selettori dei siti centralizzati.** Un file JSON per servizio con i selettori di campo, invio e risposta, aggiornabile senza nuova versione (scaricato da GitHub e verificato con una firma). Oggi un cambio di pagina di ChatGPT o Claude richiede un rilascio.
- **Registro dei comandi eseguiti.** Data, comando, chi l'ha proposto, esito, output abbreviato; esportabile come allegato a un ticket.
- **Controllo aggiornamenti** (vedi §3) e **CI** (vedi §4).

**Priorità media:**
- **Pacchetto «segnalazione problema».** Uno zip, anche cifrato, con riepilogo, diagnosi, screenshot e registro dei comandi, da mandare a un tecnico.
- **Cifratura dei task salvati in locale** (oggi è cifrato solo l'export), con la chiave nel portachiavi di sistema.
- **Azioni di root predefinite con polkit**: riavvia un servizio, aggiorna il sistema, svuota la cache dei pacchetti. Sono già nella roadmap.
- **Scorciatoia globale su XFCE, Cinnamon, Hyprland e Sway** (vedi §2).
- **Accessibilità**: uso completo da tastiera, nomi accessibili per Orca o NVDA, dimensione del testo regolabile.

**Priorità bassa:**
- Altre lingue (es, de, fr): il catalogo `i18n` è già pronto.
- `helpix --report-bug`, che raccoglie log e versione (senza dati personali) per segnalare un problema di Helpix.
