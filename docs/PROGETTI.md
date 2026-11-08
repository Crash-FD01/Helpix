<!-- SPDX-FileCopyrightText: 2026 Crash
     SPDX-License-Identifier: GPL-3.0-or-later -->
# Progetti e vault (beta) — specifica

Stato: **beta**, spenta di default (*Impostazioni › Funzioni sperimentali › Progetti e vault*).
Questa pagina descrive come funziona e perché è fatta così; per l'uso c'è la [guida](GUIDA.md).

## L'idea

Un **progetto è un task che continua**: lo stesso lavoro portato avanti in più sessioni, anche con IA diverse.
Invece di rimandare ogni volta tutta la conversazione, Helpix tiene un file breve con lo stato attuale
(`PROJECT.md`) e lo incolla all'inizio di ogni chat nuova. Il passato resta in note separate, che l'IA chiede solo
quando servono.

Obiettivi, in quest'ordine:
1. **Continuità**: si riparte dopo giorni, o con un'altra IA, senza rispiegare.
2. **Contesto piccolo e fisso** (~1000 token) invece di una cronologia che cresce: meno token con API e agenti,
   meno limiti d'uso con gli account web, risposte migliori.
3. **Semplicità**: per l'utente ci sono un selettore e un pulsante *Salva progetto*. Il resto lo gestisce Helpix.

Regole che non cambiano: Helpix agisce solo quando l'utente preme un pulsante; ogni aggiornamento del progetto
fatto dall'IA si vede in anteprima prima di essere salvato (salvo l'opzione *Automatico con annullamento*).

## Il vault su disco

Una cartella di file Markdown, leggibile anche senza Helpix (e compatibile con Obsidian, link `[[ ]]` compresi).
Posizione predefinita: `~/.local/share/helpix/vault` su Linux, `%LOCALAPPDATA%\Helpix\vault` su Windows
(non in Documenti: su molti PC è dentro OneDrive, che crea conflitti e file «solo online»). Si può scegliere
un'altra cartella; se è dentro OneDrive Helpix avvisa.

```
vault/
├── helpix-vault.json          intestazione: formato, versione, cifratura (slot delle chiavi)
├── .backup/                   copie dell'intestazione prima di ogni modifica (vault cifrato)
└── progetti/<nome>/
    ├── PROJECT.md             stato attuale: sempre incollato all'inizio di una chat nuova
    ├── INDEX.md               una riga per nota: data, titolo, sintesi
    ├── note/AAAA-MM-GG-titolo.md   una nota per ogni salvataggio
    ├── file/                  dettagli: codice, errori esatti, configurazioni
    ├── sessioni/<task>.md     bozze automatiche della sessione (comandi, output, diagnosi)
    └── .versioni/             versioni precedenti di PROJECT.md (le ultime 20)
.cestino/<nome>-<data>/        progetti e note eliminati, finché non si svuota il cestino
```

### PROJECT.md

Sezioni fisse, in quest'ordine:

```markdown
# Nome del progetto

## Obiettivo
## Contesto
## Decisioni in vigore
- 2026-11-07 Testo della decisione
## Stato
## Prossimi passi
## Riferimenti
## Solo per me
```

- **Solo per me** non viene mai inviata a nessuna IA (né incollata, né scritta nei file degli agenti) e le
  modifiche proposte dall'IA non la toccano.
- Tetto consigliato: **1000 token** (stima: caratteri / 4). Oltre, Helpix propone *Compatta il progetto*.
- Una decisione superata esce da `PROJECT.md` e resta nella nota della sessione in cui è stata sostituita
  («Decisione superata: … → …»): l'IA vede solo quelle in vigore.

### Note e indice

- Nota: `note/2026-11-07-titolo-breve.md`, con titolo, data, IA usata, testo e decisioni superate.
- Riga dell'indice: `- 2026-11-07 · [[2026-11-07-titolo-breve|Titolo breve]] — sintesi`.
- All'apertura del progetto si incollano solo le **ultime 3 righe** dell'indice.

## I flussi

### Apri un progetto

Selettore *Progetto* nella barra. Scegliendo un progetto Helpix apre un task nuovo collegato al progetto e:
- **chat web**: incolla in una chat nuova `PROJECT.md` (senza *Solo per me*), le ultime righe dell'indice e le
  istruzioni per chiedere le note; l'utente preme Invio;
- **motore API**: lo stesso testo va nel messaggio di sistema di ogni richiesta;
- **agenti nel terminale**: lo stesso testo va in `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, con i comandi per leggere
  le note.

Il filtro privacy, se acceso, si applica a tutto quello che esce.

### Salva progetto

Il pulsante chiede all'IA un blocco con **solo le modifiche** e la nota della sessione:

```
HELPIX-PROJECT
NOTA: Titolo breve della sessione
Cosa è stato fatto, risultati, problemi aperti (poche righe).
MODIFICHE:
+ Decisioni in vigore: 2026-11-07 nuova decisione
- Prossimi passi: riga da togliere, come è scritta ora
~ Decisioni in vigore: decisione vecchia => decisione nuova
= Stato: nuovo stato in una o due frasi
```

- `+` aggiunge una riga, `-` la toglie, `~` la sostituisce (in *Decisioni in vigore* la vecchia diventa
  «superata» nella nota), `=` riscrive la sezione.
- Helpix applica le modifiche a `PROJECT.md` (confronto tollerante su maiuscole, spazi, date e trattini) e mostra
  l'anteprima: `PROJECT.md` risultante e nota, entrambi modificabili, più l'elenco delle modifiche e quelle che
  non ha potuto applicare. *Salva* scrive tutto; la versione precedente va in `.versioni/`.
- Come arriva il blocco: chat web → Helpix lo invia e legge la risposta (lo stesso meccanismo del riepilogo del
  task); motore API → una chiamata separata che non tocca la conversazione; agenti → l'agente lo scrive nel file
  `HELPIX-PROJECT.md`, che Helpix legge. In ogni caso funziona anche copiando il blocco a mano.
- **Compatta il progetto**: stessa strada, ma l'IA restituisce `PROJECT.md` intero e più corto (blocco con
  `COMPLETO` sulla seconda riga). *Solo per me* resta quella di prima.

Modalità di aggiornamento (*Progetto › Impostazioni dei progetti…*):
- *Chiedi sempre* (predefinita): anteprima e conferma;
- *Automatico con annullamento*: salva subito e mostra «Progetto aggiornato» con *Annulla*.

### Ripescare una nota: HELPIX-NOTA

Nel testo iniziale l'IA trova questa regola: se le serve una nota, scrive su una riga sola
`HELPIX-NOTA: titolo`. L'utente copia la riga (come un comando) e compare la barra *«L'IA chiede la nota
"…"» — Incolla nella chat / Ignora*. Nel motore API Helpix lo vede nella risposta e chiede conferma prima di
inviarla. Niente letture automatiche della pagina, niente ricerche che decidono da sole.

Gli agenti leggono da soli, con due comandi che parlano con Helpix aperto (stesso canale locale della finestra
rapida, accessibile solo all'utente):

```
helpix vault cat "titolo della nota"     # testo della nota (anche PROJECT.md, INDEX.md o file/…)
helpix vault search "parole"             # righe che contengono le parole, con il nome della nota
```

Con il vault bloccato rispondono «vault bloccato». Il testo in chiaro non viene scritto su disco. Su Windows
`Helpix.exe` è un programma a finestre (niente console): le istruzioni per l'agente usano `--out HELPIX-NOTA.md`
e `| Out-Null`, così PowerShell aspetta la fine e l'agente legge il file. I task della finestra rapida non
ricevono il contesto del progetto.

### Salvataggio automatico e promemoria

- **Bozza della sessione**, ogni 10 minuti (5, 10, 15 o spento): Helpix scrive `sessioni/<task>.md` con quello
  che è passato da lui (comandi e output, diagnosi, riepiloghi, note). Nessuna IA, zero token, niente messaggi.
- **Promemoria** «Salvare nel progetto?» nei momenti naturali, solo se ci sono novità dall'ultimo salvataggio:
  cambio di progetto, nuovo task, passaggio a un'altra IA, chiusura di Helpix. Disattivabile.
- **Versioni**: le ultime 20 di `PROJECT.md`, con *Ripristina* dal pannello Vault.

### Il pannello Vault

Finestra separata (dal selettore *Progetto › Apri il vault…*) in tre colonne:
- **sinistra**: nome del vault, ricerca, albero di progetti e note (PROJECT.md, INDEX.md, note, file, sessioni,
  versioni), scheda del lucchetto con *Blocca*;
- **centro**: percorso, titolo, *Leggi/Modifica*, *Riprendi con…* (l'assistente attivo), *Incolla nella chat*,
  misuratore dei token di PROJECT.md; nota formattata con le decisioni «in vigore» e «Solo per me» evidenziata
  («mai inviata all'IA»); in modifica *Salva modifiche* / *Annulla le modifiche*; per le versioni *Ripristina*;
- **destra**: cosa va all'IA nella prossima chat (con il totale), «Citata da», note recenti (*nel contesto* /
  *archivio*).

In alto una striscia *Beta* con *Esporta in chiaro*, *Segnala un problema* e *Guida*.

L'albero si apre e si chiude con un clic (freccia ▸/▾ disegnata da Helpix). Il pulsante «⋯» e il tasto destro
danno *Rinomina il progetto* (cambia il «# titolo», la cartella resta), *Elimina la nota/il file/la bozza* ed
*Elimina il progetto*.

### Cestino

Eliminare non cancella subito: progetti e note vanno in `.cestino/<nome>-<data>/` dentro il vault (cifrati anche
loro, se il vault è cifrato), con gli stessi percorsi. Copia prima, verifica, poi toglie gli originali. Una nota
porta con sé la sua riga dell'indice, che torna al ripristino. *Ripristina* rifiuta se nel frattempo è stato creato
qualcosa con lo stesso nome; *Elimina definitivamente* e *Svuota il cestino* chiedono conferma. Un progetto
eliminato mentre è aperto si chiude.

### Guida a nuvolette

Come il giro di Helpix, con le stesse nuvolette:
- **progetti** (finestra principale): parte da solo la prima volta che si attiva la funzione; si rifà da
  *Progetto › Guida ai progetti* (anche in *Impostazioni › Funzioni sperimentali*);
- **pannello Vault**: parte la prima volta che si apre il pannello; si rifà dal pulsante *Guida*.
I passi su pulsanti non visibili (per esempio il misuratore, che c'è solo su PROJECT.md) si saltano.

## Cifratura (facoltativa)

Fatta da Helpix, senza filesystem montati né driver: funziona uguale su Linux, Windows e (in futuro) macOS.

### Chiavi e slot

- Alla creazione Helpix genera una **chiave master** casuale (256 bit). Da questa, con HKDF-SHA256, ricava la
  chiave dei dati e quella dei nomi dei file.
- La chiave master è chiusa (AES-256-GCM) in più **slot**, come in LUKS:
  - **password** del vault (obbligatoria);
  - **codici usa e getta**: 8, uno slot ciascuno (obbligatori);
  - **file di recupero** (facoltativo, spento di default; si crea o si revoca anche dopo);
  - **portachiavi di sistema** (facoltativo): chiave casuale nel portachiavi, sblocco con polkit su Linux o
    Windows Hello.
- Password e codici diventano chiavi con **scrypt** (N = 2^17, r = 8, p = 1: 128 MiB, da 0,3 a 1 secondo). I
  parametri sono salvati nello slot, per poterli alzare in futuro.
- **Reimpostare la password** = aprire la chiave master con un codice o con il file e richiuderla con la password
  nuova. I file non vengono ricifrati.
- Un **codice usato** viene cancellato (il suo slot sparisce). Sotto i 3 rimasti Helpix propone di rigenerarli;
  rigenerare annulla tutti i vecchi. Un backup vecchio del vault contiene ancora gli slot dei codici usati: per
  questo, dopo un recupero, Helpix consiglia di rigenerare i codici.

### Password e codici

- Password: almeno 12 caratteri; conta la lunghezza, non l'obbligo di simboli. Helpix rifiuta le password comuni o
  ripetitive e mostra la robustezza stimata; il pulsante *Genera* propone 6 parole casuali. Nessuna scadenza.
- Codici: 6 parole casuali da un elenco di oltre 2200 parole italiane senza accenti, separate da trattini
  (`vela-torre-muschio-faro-cedro-lampo`, circa 67 bit). Si accettano anche maiuscole e spazi.
- Per completare la creazione bisogna riscrivere uno dei codici: così si è sicuri di averli salvati.
- File di recupero `Vault-<nome>.helpix-recovery`: chiave casuale di 256 bit. Chi ha il file apre il vault: va
  tenuto fuori dal PC e fuori dalle cartelle sincronizzate.
- Password, codici e file non vengono mai inviati né salvati nel vault; il filtro privacy li oscura.
- Persi password, codici e file, i dati sono persi: non c'è una porta di servizio.

### Formato su disco

- `helpix-vault.json` (in chiaro): formato, versione, identificativo del vault, slot (sale, parametri, nonce,
  chiave master cifrata). Nessun dato dell'utente.
- File: `dati/<HMAC del percorso>.hxv`, ciascuno `HXV1` + nonce + AES-256-GCM. Dentro, il percorso vero e il
  contenuto: i nomi non si vedono da fuori e l'elenco si ricostruisce decifrando i file (nessun indice centrale da
  perdere). Il percorso è anche nei dati autenticati: un file spostato o scambiato viene rifiutato.

### Scrittura sicura

- Ogni file viene scritto in un file temporaneo, riletto, decifrato e confrontato; solo se combacia sostituisce il
  vecchio (`os.replace`). Su Windows, se l'antivirus o un altro programma ha il file aperto, riprova per qualche
  secondo prima di dare errore.
- L'intestazione, prima di ogni modifica, viene copiata in `.backup/` (le ultime 10).
- Il blocco di Helpix (*Impostazioni › Sicurezza*, anche quello per inattività), *Progetto › Blocca il vault* e la
  chiusura di Helpix chiudono il vault: la chiave master viene tolta dalla memoria.

### Uscire dal formato

- *Esporta in chiaro* copia il vault decifrato in una cartella a scelta.
- `helpix/vault_crypto.py` funziona anche da solo, senza Helpix (serve solo `cryptography`):
  `python3 vault_crypto.py decrypt <vault> <cartella>` chiede password, codice o file di recupero.

### Passare da chiaro a cifrato

*Cifra il vault* crea l'intestazione, cifra ogni file, verifica di poterli decifrare tutti e solo allora cancella
le copie in chiaro. Su SSD e dischi con copie automatiche la cancellazione non garantisce che non restino tracce:
Helpix lo dice e consiglia la cifratura del disco (LUKS, BitLocker) per la protezione a PC spento.

## Beta

- Interruttore in *Impostazioni › Funzioni sperimentali*, spento di default.
- Banner nel pannello Vault: *«Funzione in beta: tieni una copia dei dati importanti»*, con *Segnala un problema*
  ed *Esporta in chiaro*. Alla creazione di un vault cifrato, avviso più forte.
- Il formato ha un numero di versione dal primo giorno: i vault creati in beta si apriranno con le versioni
  successive.

Per togliere la beta:
- test automatici (cifra/decifra, file e intestazione corrotti, scrittura interrotta, processo terminato a metà,
  recupero con codice e con file, rigenerazione e revoca) verdi su Linux e Windows;
- prove su Windows con l'antivirus attivo e su almeno due distribuzioni;
- alcune settimane di uso reale senza perdite di dati;
- una rilettura esterna del codice di cifratura.

## Limiti noti (beta)

- I task salvati (*Task salvati…*) restano dove sono oggi, non cifrati: la cifratura riguarda il vault.
- La finestra rapida non usa ancora il progetto attivo (i suoi task restano fuori dal progetto).
- Il pannello Vault non ha un editor avanzato: per modifiche lunghe si può aprire la cartella in chiaro con un
  editor esterno (vault non cifrato).
- Stima dei token approssimativa (caratteri / 4).

## Dove sta nel codice

| File | Ruolo |
|---|---|
| `helpix/vault_crypto.py` | Chiavi, slot, cifratura dei file; usabile anche da solo |
| `helpix/vault.py` | Archivio (chiaro o cifrato), progetti, note, indice, versioni, bozze, ricerca |
| `helpix/project.py` | Testo di contesto, richiesta e lettura di `HELPIX-PROJECT`, applicazione delle modifiche, `HELPIX-NOTA` |
| `helpix/passwords.py` | Robustezza della password, codici e frasi casuali (`data/parole-it.txt`) |
| `helpix/ui/vault_panel.py` | Pannello Vault (e la resa Markdown delle note) |
| `helpix/ui/tour.py` | Giri a nuvolette, anche quelli dei progetti e del pannello |
| `helpix/ui/vault_dialogs.py` | Nuovo progetto, salvataggio con anteprima, creazione/sblocco/recupero del vault, impostazioni |
| `helpix/ui/project_mixin.py` | Selettore, apertura, salvataggio, promemoria, bozze, barra HELPIX-NOTA, blocco, `helpix vault` |
| `helpix/ui/main_window.py` | Punti di aggancio (barra, menu, nuovo task, chiusura, blocco, canale locale) |
| `helpix/app.py` | `helpix vault cat/search/project [--out FILE]` |
