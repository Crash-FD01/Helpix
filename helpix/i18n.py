# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lingue dell'interfaccia: italiano (testo sorgente) e inglese.

Il testo italiano nel codice è la chiave; `tr()` restituisce la traduzione inglese quando
la lingua attiva è l'inglese. Le frasi con valori variabili usano segnaposto
`{nome}` e vanno formattate dopo la traduzione: `tr("Uscita {rc}").format(rc=1)`.
"""
from __future__ import annotations

import locale
import os

LANGUAGES = {"it": "Italiano", "en": "English"}
_state = {"lang": "it"}


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var, "")
        if value:
            return "it" if value.lower().startswith("it") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "it" if loc.lower().startswith("it") else "en"


def set_language(code: str) -> str:
    _state["lang"] = code if code in LANGUAGES else system_language()
    return _state["lang"]


def current() -> str:
    return _state["lang"]


def tr(text: str) -> str:
    if _state["lang"] == "en":
        return EN.get(text, text)
    return text


EN: dict[str, str] = {
    # --- diagnostica
    "Tempo di attività e carico": "Uptime and load",
    "Spazio su disco": "Disk space",
    "Memoria": "Memory",
    "Interfacce di rete": "Network interfaces",
    "Stato della rete": "Network status",
    "Connessioni attive": "Active connections",
    "Rotta predefinita e DNS": "Default route and DNS",
    "Servizi in errore": "Failed services",
    "Errori dall'ultimo avvio": "Errors since last boot",
    "(nessuna risposta entro il tempo limite)": "(no response within the time limit)",
    "(nessun risultato)": "(no result)",
    "\n[…troncato]": "\n[…truncated]",
    "Ciao, ho un problema sul mio PC Linux. Ecco le informazioni di sistema raccolte da Helpix "
    "(un'app di troubleshooting). Quando mi proponi dei comandi, scrivine uno per blocco di codice "
    "e usa solo comandi non interattivi: li eseguirò e ti incollerò l'output.":
        "Hi, I have a problem on my Linux PC. Here is the system information collected by Helpix "
        "(a troubleshooting app). When you suggest commands, put one per code block and use only "
        "non-interactive commands: I will run them and paste the output back to you.",
    "- Sistema: {distro} ({arch}), kernel {kernel}": "- System: {distro} ({arch}), kernel {kernel}",
    "- Desktop: {desktop} (sessione {session})": "- Desktop: {desktop} ({session} session)",
    "- Gestore pacchetti: {pkg}; altri formati: {extra}": "- Package manager: {pkg}; other formats: {extra}",
    "\n\nIl problema è: ": "\n\nThe problem is: ",

    # --- esecuzione comandi
    "cancellazione ricorsiva di file (rm -r)": "recursive file deletion (rm -r)",
    "formattazione di un filesystem": "formatting a filesystem",
    "scrittura diretta su un dispositivo": "writing directly to a device",
    "scrittura diretta su un disco": "writing directly to a disk",
    "modifica delle partizioni o cancellazione sicura": "changing partitions or secure erase",
    "fork bomb": "fork bomb",
    "modifica ricorsiva di permessi o proprietario": "recursive permission or owner change",
    "riavvio o spegnimento": "reboot or shutdown",
    "esecuzione di uno script scaricato da Internet": "running a script downloaded from the Internet",
    "rimozione di pacchetti": "removing packages",
    "arresto di un servizio essenziale": "stopping an essential service",
    "cancellazione di utenti o gruppi": "deleting users or groups",
    "spostamento di file di sistema": "moving system files",
    "sovrascrittura di un file di sistema critico": "overwriting a critical system file",
    "«{name}» è un programma interattivo e qui non riceverebbe input":
        "“{name}” is an interactive program and would not receive input here",
    "il comando resta in ascolto finché non premi «Ferma» (o fino al timeout)":
        "the command keeps running until you press “Stop” (or until the timeout)",
    "Impossibile avviare il comando: {exc}\n": "Could not start the command: {exc}\n",

    # --- fornitori API
    "Ollama (locale)": "Ollama (local)",
    "Screenshot allegato.": "Screenshot attached.",
    "Chiave API non valida o scaduta.": "Invalid or expired API key.",
    "Accesso negato: verifica permessi e credito dell'account.": "Access denied: check the account's permissions and credit.",
    "Modello o indirizzo non trovato: controlla il nome del modello.": "Model or address not found: check the model name.",
    "Richiesta troppo grande: prova con meno screenshot.": "Request too large: try with fewer screenshots.",
    "Troppe richieste o credito esaurito: riprova tra poco.": "Too many requests or no credit left: try again shortly.",
    "Risposta non valida dal server.": "Invalid response from the server.",
    "\n\n_(Risposta troncata: raggiunto il limite di lunghezza.)_": "\n\n_(Response truncated: length limit reached.)_",
    "Il modello ha restituito una risposta vuota.": "The model returned an empty response.",
    "Il server non ha risposto in tempo. Riprova.": "The server did not respond in time. Try again.",
    "Impossibile contattare {host}: {exc}": "Could not reach {host}: {exc}",

    # --- screenshot
    "Nessun metodo di cattura disponibile.\nSu Wayland serve xdg-desktop-portal (già presente su GNOME e KDE); "
    "in alternativa installa uno tra grim+slurp, spectacle, gnome-screenshot o flameshot.":
        "No capture method available.\nOn Wayland you need xdg-desktop-portal (already present on GNOME and KDE); "
        "otherwise install one of grim+slurp, spectacle, gnome-screenshot or flameshot.",
    "Nessuno schermo rilevato": "No screen detected",
    "Cattura Qt fallita": "Qt capture failed",
    "Impossibile salvare lo screenshot": "Could not save the screenshot",
    "Immagine non leggibile: {src}": "Unreadable image: {src}",
    "Screenshot non leggibile": "Unreadable screenshot",

    # --- sessioni
    "Nuova sessione": "New session",
    "\n[Screenshot non più disponibile]": "\n[Screenshot no longer available]",
    "\n[Screenshot allegato: il modello attuale non può vedere le immagini]":
        "\n[Screenshot attached: the current model cannot see images]",
    "\n[Screenshot precedente omesso per limitare la dimensione della richiesta]":
        "\n[Earlier screenshot omitted to limit the request size]",

    # --- chat (motore API)
    "[immagine mancante]": "[missing image]",
    "{name} — clic per aprire": "{name} — click to open",
    "richiede root": "needs root",
    "Verrà chiesta la password di amministratore (polkit)": "The administrator password will be requested (polkit)",
    "⚠ attenzione": "⚠ caution",
    "Copia": "Copy",
    "Modifica": "Edit",
    "Modifica il comando prima di eseguirlo": "Edit the command before running it",
    "▶ Esegui": "▶ Run",
    "In esecuzione…": "Running…",
    "✓ Eseguito": "✓ Done",
    "✗ Uscita {rc}": "✗ Exit {rc}",
    "Clic per eseguirlo di nuovo": "Click to run it again",
    "inviato all'IA": "sent to the AI",
    "✓ uscita 0": "✓ exit 0",
    "✗ uscita {rc}": "✗ exit {rc}",
    "Mostra output": "Show output",
    "Nascondi": "Hide",
    "Riprova": "Try again",
    "Rimuovi allegato": "Remove attachment",
    "Descrivi il problema…  (Invio invia · Maiusc+Invio a capo · Ctrl+V incolla uno screenshot)":
        "Describe the problem…  (Enter sends · Shift+Enter new line · Ctrl+V pastes a screenshot)",
    "codice": "code",
    "comando": "command",

    # --- barra del comando copiato
    "(nessun output)": "(no output)",
    "[…output troncato, mostrata l'ultima parte…]\n": "[…output truncated, showing the last part…]\n",
    " — interrotto": " — interrupted",
    " — interrotto per timeout": " — stopped by timeout",
    "Output di `{first}` (codice di uscita {rc}{extra}):\n```\n{out}\n```":
        "Output of `{first}` (exit code {rc}{extra}):\n```\n{out}\n```",
    "Chiudi": "Close",
    "Ignora": "Dismiss",
    "Esegui": "Run",
    "Riesegui": "Run again",
    "Incolla nella chat": "Paste into chat",
    "Chiede la password": "Asks for password",
    "Serve la password di amministratore (polkit)": "The administrator password is required (polkit)",
    "Attenzione": "Caution",
    "Interattivo": "Interactive",
    "Hai copiato un comando": "You copied a command",
    "Vuoi eseguirlo su questo PC? L'output verrà incollato nella chat.":
        "Run it on this PC? The output will be pasted into the chat.",
    "Comando in esecuzione…": "Command running…",
    "Il comando è terminato con codice {rc}": "The command ended with code {rc}",
    "Comando eseguito": "Command completed",
    "Output incollato nella chat: premi Invio per inviarlo.": "Output pasted into the chat: press Enter to send it.",
    "L'output è pronto da incollare nella chat.": "The output is ready to paste into the chat.",
    "1 riga": "1 line",
    "{n} righe": "{n} lines",

    # --- controlli
    "Altre opzioni": "More options",
    "Riduci a icona": "Minimize",
    "Ingrandisci": "Maximize",

    # --- sessioni salvate
    "Helpix — Sessioni salvate": "Helpix — Saved sessions",
    "Riapri un troubleshooting precedente. Puoi continuarlo anche con un'altra IA: il contesto viene mantenuto.":
        "Reopen a previous troubleshooting session. You can continue it with another AI too: the context is kept.",
    "Nessuna sessione salvata.": "No saved sessions.",
    "Elimina": "Delete",
    "Apri": "Open",
    "Elimina sessione": "Delete session",
    "Eliminare definitivamente questa sessione?": "Permanently delete this session?",
    "{title}\n{when} · {who} · {model} · {count} messaggi": "{title}\n{when} · {who} · {model} · {count} messages",

    # --- finestra principale
    "Assistente: {name}, {status}. Apri il menu": "Assistant: {name}, {status}. Open the menu",
    "Scegli l'assistente o cambia motore": "Choose the assistant or switch engine",
    "Diagnosi rapida": "Quick diagnostics",
    "Questi dati verranno incollati nella chat. Contengono il nome del PC e gli indirizzi di rete: "
    "puoi modificarli o cancellare ciò che non vuoi condividere.":
        "This data will be pasted into the chat. It contains the PC name and network addresses: "
        "you can edit it or delete anything you don't want to share.",
    "Annulla": "Cancel",
    "{msg}\n\nIn alternativa usa il tuo strumento di cattura e incolla l'immagine con Ctrl+V.":
        "{msg}\n\nAlternatively, use your own screenshot tool and paste the image with Ctrl+V.",
    "Area o finestra": "Area or window",
    "Finestra (dialogo di sistema)": "Window (system dialog)",
    "Schermo intero": "Full screen",
    "Area dopo 3 secondi": "Area after 3 seconds",
    "Allega immagine da file…": "Attach image from file…",
    "Altre modalità di cattura": "More capture modes",
    "Raccoglie le informazioni del PC e le incolla nella chat": "Collects the PC's information and pastes it into the chat",
    "Diagnosi": "Diagnostics",
    "Modalità tecnico: terminale e cartelle (Ctrl+`)": "Technician mode: terminal and folders (Ctrl+`)",
    "Tema scuro": "Dark theme",
    "Impostazioni": "Settings",
    "Invia": "Send",
    "Doppio clic per spostare il terminale in questa cartella": "Double-click to move the terminal to this folder",
    "Chiavi API e modelli…": "API keys and models…",
    "Aspetto": "Appearance",
    "Automatico (come il sistema)": "Automatic (follow the system)",
    "Chiaro": "Light",
    "Scuro": "Dark",
    "Automatico": "Automatic",
    "Lingua": "Language",
    "Tieni sopra le altre finestre": "Keep above other windows",
    "Usa la barra del titolo del sistema": "Use the system title bar",
    "Informazioni su Helpix": "About Helpix",
    "Indietro": "Back",
    "Ricarica la pagina": "Reload page",
    "Pagina iniziale": "Home page",
    "Apri nel browser": "Open in browser",
    "Usa una chiave API (avanzato)": "Use an API key (advanced)",
    "Modello: {model}": "Model: {model}",
    "Altro modello…": "Other model…",
    "Aggiorna l'elenco": "Refresh the list",
    "Sessioni salvate…": "Saved sessions…",
    "Torna al mio account (web)": "Back to my account (web)",
    "Descrivi il problema qui sotto. Puoi allegare uno **screenshot** (pulsante in alto o Ctrl+V): "
    "i comandi proposti dall'IA si eseguono con un clic e il loro output torna automaticamente all'IA.":
        "Describe the problem below. You can attach a **screenshot** (button at the top or Ctrl+V): "
        "commands suggested by the AI run with one click and their output goes back to the AI automatically.",
    "il tuo account": "your account",
    "Passa al tema chiaro (Ctrl+Maiusc+L)": "Switch to light theme (Ctrl+Shift+L)",
    "Passa al tema scuro (Ctrl+Maiusc+L)": "Switch to dark theme (Ctrl+Shift+L)",
    "La pagina della chat userà il nuovo tema dal prossimo avvio (oppure cambialo nelle impostazioni del sito).":
        "The chat page will use the new theme from the next launch (or change it in the site's settings).",
    "La modifica sarà applicata al prossimo avvio di Helpix.": "The change will apply the next time Helpix starts.",
    "Seleziona un'area o una finestra e incollala nella chat (Ctrl+Maiusc+S)":
        "Select an area or window and paste it into the chat (Ctrl+Shift+S)",
    "Seleziona un'area o una finestra e allegala al messaggio (Ctrl+Maiusc+S)":
        "Select an area or window and attach it to the message (Ctrl+Shift+S)",
    "Chiave API": "API key",
    "Inserisci la chiave API per {label}.\nLa trovi su: {url}": "Enter the API key for {label}.\nYou can find it at: {url}",
    "Modello": "Model",
    "Nome esatto del modello:": "Exact model name:",
    "Agente cambiato in **{label} · {model}**. Conversazione e contesto sono mantenuti.":
        "Agent switched to **{label} · {model}**. Conversation and context are kept.",
    " Questo agente non legge le immagini: gli screenshot non verranno inviati.":
        " This agent cannot read images: screenshots will not be sent.",
    "Aggiorno l'elenco dei modelli…": "Refreshing the model list…",
    "Impossibile ottenere l'elenco dei modelli:\n{exc}": "Could not get the model list:\n{exc}",
    "{n} modelli disponibili: aprili dal menu dell'assistente": "{n} models available: open them from the assistant menu",
    "Ecco uno screenshot del problema.": "Here is a screenshot of the problem.",
    "{label} sta analizzando": "{label} is analysing",
    "_(risposta vuota)_": "_(empty response)_",
    "Errore dall'IA: {exc}": "Error from the AI: {exc}",
    "Questo comando può modificare o danneggiare il sistema:\n• ": "This command can change or damage the system:\n• ",
    "Attenzione: {msg}.": "Caution: {msg}.",
    "Conferma comando": "Confirm command",
    "Comando:\n{cmd}\n\nVuoi eseguirlo comunque?": "Command:\n{cmd}\n\nRun it anyway?",
    "C'è già un comando in esecuzione. Attendi o premi «Ferma».": "A command is already running. Wait or press “Stop”.",
    "Le opzioni di sudo (es. sudo -u, sudo -i) non sono supportate.\nUsa «sudo comando» senza opzioni oppure un terminale esterno.":
        "sudo options (e.g. sudo -u, sudo -i) are not supported.\nUse “sudo command” without options or an external terminal.",
    "pkexec (polkit) non è installato: impossibile ottenere i privilegi di amministratore da qui.":
        "pkexec (polkit) is not installed: administrator privileges cannot be obtained from here.",
    "Autorizzazione di amministratore richiesta (polkit)…\n": "Administrator authorization requested (polkit)…\n",
    "interrotto: superato il limite di {s} s": "stopped: exceeded the {s} s limit",
    "interrotto dall'utente": "stopped by the user",
    "autorizzazione annullata": "authorization cancelled",
    "autorizzazione negata": "authorization denied",
    "output molto lungo, conservata solo la prima parte": "very long output, only the first part was kept",
    "[codice di uscita {rc}]\n": "[exit code {rc}]\n",
    "Output incollato nella chat: premi Invio nella chat per inviarlo.":
        "Output pasted into the chat: press Enter in the chat to send it.",
    "Ho eseguito nel terminale (cartella {cwd}):\n````bash\n{cmd}\n````\nCodice di uscita: {rc}{extra}\nOutput:\n````\n{out}\n````":
        "I ran this in the terminal (folder {cwd}):\n````bash\n{cmd}\n````\nExit code: {rc}{extra}\nOutput:\n````\n{out}\n````",
    "Modifica comando": "Edit command",
    "Modifica il comando e premi OK per eseguirlo:": "Edit the command and press OK to run it:",
    "Raccolgo le informazioni del sistema…": "Collecting system information…",
    "Diagnosi incollata nella chat: descrivi il problema in fondo e invia.":
        "Diagnostics pasted into the chat: describe the problem at the end and send.",
    "Cartella non accessibile: {path}\n": "Folder not accessible: {path}\n",
    "Scegli una cartella": "Choose a folder",
    "Screenshot allegato: descrivi il problema e premi Invio": "Screenshot attached: describe the problem and press Enter",
    "Allega immagini": "Attach images",
    "Immagini ({exts})": "Images ({exts})",
    "Immagine": "Image",
    "Sessioni": "Sessions",
    "Impossibile aprire la sessione:\n{exc}": "Could not open the session:\n{exc}",
    "Riavvia ora": "Restart now",
    "Più tardi": "Later",
    "La nuova lingua sarà usata dopo il riavvio di Helpix.": "The new language will be used after Helpix restarts.",

    # --- selettore area
    "Helpix — Seleziona l'area": "Helpix — Select the area",
    "Rifai": "Redo",
    "✓ Usa questa area": "✓ Use this area",
    "Clic per catturare: {title}": "Click to capture: {title}",
    "finestra": "window",
    "Trascina per selezionare un'area": "Drag to select an area",
    " · clic su una finestra per catturarla": " · click a window to capture it",
    " · Invio conferma · Esc annulla": " · Enter confirms · Esc cancels",

    # --- impostazioni API
    "Helpix — Impostazioni": "Helpix — Settings",
    "Helpix — Scegli l'assistente": "Helpix — Choose the assistant",
    "Assistente AI per risolvere i problemi del tuo PC": "AI assistant to fix the problems of your PC",
    "Intelligenza artificiale": "Artificial intelligence",
    "Scegli dall'elenco o scrivi il nome esatto del modello": "Choose from the list or type the exact model name",
    "↻ Aggiorna": "↻ Refresh",
    "Scarica dal fornitore l'elenco dei modelli disponibili per la tua chiave":
        "Download from the provider the list of models available to your key",
    "incolla qui la chiave API": "paste the API key here",
    "Mostra": "Show",
    "Indirizzo server": "Server address",
    "🔒 Le chiavi sono salvate nel portachiavi di sistema.": "🔒 Keys are stored in the system keyring.",
    "⚠ Portachiavi di sistema non disponibile: le chiavi saranno salvate in {path} (permessi 600).":
        "⚠ System keyring not available: keys will be saved in {path} (permissions 600).",
    "Imposta come agente predefinito": "Set as default agent",
    "Alle prossime aperture avvia direttamente con l'agente predefinito": "Start directly with the default agent next time",
    "Opzioni": "Options",
    "Dopo un comando proposto dall'IA, invia l'output e continua da solo":
        "After a command suggested by the AI, send the output and continue automatically",
    "Nascondi Helpix durante lo screenshot": "Hide Helpix while taking a screenshot",
    "Durata massima di un comando": "Maximum command duration",
    "Verifica connessione": "Test connection",
    "Esci": "Quit",
    "Avvia Helpix": "Start Helpix",
    "Salva": "Save",
    "Non hai una chiave? Creala qui:": "No key yet? Create one here:",
    "Nessuna chiave necessaria: i dati restano sul tuo PC. Installa Ollama ({link}) e scarica un modello con "
    "supporto alle immagini, ad esempio {cmd}.":
        "No key needed: your data stays on your PC. Install Ollama ({link}) and download a model that supports "
        "images, for example {cmd}.",
    "<br>Nota: questo fornitore non legge gli screenshot.": "<br>Note: this provider cannot read screenshots.",
    "Inserisci prima la chiave API.": "Enter the API key first.",
    "Contatto il fornitore…": "Contacting the provider…",
    "Connessione non riuscita.\n{exc}": "Connection failed.\n{exc}",
    "Connessione riuscita, ma il fornitore non ha restituito modelli.": "Connected, but the provider returned no models.",
    "✓ Connessione riuscita: {n} modelli disponibili.": "✓ Connected: {n} models available.",
    "Per usare questo fornitore serve una chiave API.": "This provider requires an API key.",
    "Scegli o scrivi il nome di un modello.": "Choose or type a model name.",

    # --- finestra di avvio
    "Benvenuto in Helpix": "Welcome to Helpix",
    "Scegli l'assistente con cui risolvere il problema. Usi il tuo account di sempre, anche gratuito.":
        "Choose the assistant you want to solve the problem with. You use your usual account, even a free one.",
    "La prima volta accedi nella pagina del servizio: l'accesso resta salvato su questo PC. "
    "Meglio usare email e password, perché «Accedi con Google» a volte viene bloccato.":
        "The first time, sign in on the service's page: the login stays saved on this PC. "
        "Email and password work best, because “Sign in with Google” is sometimes blocked.",
    "Il componente browser (PySide6-WebEngine) non è installato: puoi usare solo una chiave API.":
        "The browser component (PySide6-WebEngine) is not installed: you can only use an API key.",
    "Uso avanzato con chiave API…": "Advanced use with an API key…",
    "Continua con {name}": "Continue with {name}",
    "Continua": "Continue",
    "Gratis, Plus o Pro": "Free, Plus or Pro",
    "Gratis, Pro o Max": "Free, Pro or Max",
    "Account Google": "Google account",
    "Account Microsoft": "Microsoft account",
    "Account DeepSeek": "DeepSeek account",

    # --- terminale
    "Terminale": "Terminal",
    "Cartella superiore": "Parent folder",
    "Cartella personale": "Home folder",
    "Scegli una cartella…": "Choose a folder…",
    "Interrompi il comando": "Stop the command",
    "Pulisci il terminale": "Clear the terminal",
    "scrivi un comando e premi Invio · Tab completa i percorsi · ↑↓ cronologia":
        "type a command and press Enter · Tab completes paths · ↑↓ history",
    "Condividi l'output": "Share the output",
    "Prepara l'output dei comandi che scrivi qui per incollarlo nella chat":
        "Prepare the output of the commands you type here for pasting into the chat",

    # --- pannello web
    "Helpix — Accesso": "Helpix — Sign in",
    "Il componente browser di Qt non è installato.\nInstalla il pacchetto PySide6-WebEngine (reinstallando Helpix "
    "con install.sh) oppure usa il motore API dalle impostazioni.":
        "Qt's browser component is not installed.\nInstall the PySide6-WebEngine package (by reinstalling Helpix "
        "with install.sh) or use the API engine from the settings.",
    "Download in corso in {folder}": "Downloading to {folder}",
    "Screenshot incollato nella chat: aggiungi una descrizione e invia.": "Screenshot pasted into the chat: add a description and send.",
    "Testo incollato nella chat: controlla e invia.": "Text pasted into the chat: check it and send.",
    "Browser non disponibile: il contenuto è negli appunti, incollalo con Ctrl+V.":
        "Browser not available: the content is on the clipboard, paste it with Ctrl+V.",
    "Non trovo la casella della chat: cliccaci dentro e premi Ctrl+V (il contenuto è già negli appunti).":
        "I can't find the chat box: click inside it and press Ctrl+V (the content is already on the clipboard).",

    # --- passaggio del task tra IA
    "Dimmi qual è il prossimo passo.": "Tell me what the next step is.",
    "Sto continuando un troubleshooting su un PC Linux iniziato con un'altra IA ({source}). Ti passo tutto il contesto: "
    "riparti da dove eravamo rimasti, senza rifare le verifiche già fatte se non serve. Quando mi proponi comandi, "
    "scrivine uno per blocco di codice e usa solo comandi non interattivi: li eseguirò e ti incollerò l'output.":
        "I'm continuing a troubleshooting session on a Linux PC that I started with another AI ({source}). Here is the "
        "full context: pick up where we left off, without repeating checks already done unless needed. When you "
        "suggest commands, put one per code block and use only non-interactive commands: I will run them and paste "
        "the output back to you.",
    "Problema": "Problem",
    "Comandi già eseguiti e risultati": "Commands already run and results",
    "Sistema": "System",
    "Diagnosi raccolta in precedenza:": "Diagnostics collected earlier:",
    "Il file non è un task di Helpix.": "The file is not a Helpix task.",
    "Conversazione finora (estratto)": "Conversation so far (excerpt)",
    "Utente": "User",
    "IA": "AI",
    "Ti allego anche gli ultimi {n} screenshot del problema.": "I'm also attaching the last {n} screenshots of the problem.",
    "Riepilogo del lavoro fatto finora (scritto da {who})": "Summary of the work done so far (written by {who})",
    "(ultimi {n} di {total})": "(last {n} of {total})",
    "codice di uscita {rc}": "exit code {rc}",
    "Helpix — Task salvati": "Helpix — Saved tasks",
    "Riprendi un task precedente con qualsiasi IA: screenshot, comandi, risultati e riepilogo passano alla nuova chat.":
        "Resume an earlier task with any AI: screenshots, commands, results and summary move to the new chat.",
    "Nessun task salvato.": "No saved tasks.",
    "Elimina task": "Delete task",
    "Eliminare definitivamente questo task?": "Permanently delete this task?",
    "{title}\n{when} · {who} · {count} elementi": "{title}\n{when} · {who} · {count} items",
    "Continua il task con un'altra IA": "Continue the task with another AI",
    "Helpix incolla nella nuova chat il riepilogo, i comandi già eseguiti con i risultati e gli ultimi screenshot. "
    "Tu controlli e premi Invio.":
        "Helpix pastes into the new chat the summary, the commands already run with their results and the latest "
        "screenshots. You check it and press Enter.",
    "Descrivi in una frase il problema (es. il Wi-Fi non si connette)": "Describe the problem in one sentence (e.g. Wi-Fi won't connect)",
    "Informazioni di sistema": "System information",
    "Anteprima del testo da incollare": "Preview of the text to paste",
    "Rigenera": "Regenerate",
    "Annulla le modifiche manuali e rigenera il testo": "Discard manual edits and regenerate the text",
    "Esporta su file…": "Export to file…",
    "Salva il task in un file .helpix, ad esempio per passarlo a un collega": "Save the task to a .helpix file, e.g. to hand it to a colleague",
    "Riprendi il task": "Resume the task",
    "Nuova IA": "New AI",
    "Chiedi un nuovo riepilogo": "Ask for a new summary",
    "Chiedi il riepilogo a {source}": "Ask {source} for a summary",
    "Comandi eseguiti e risultati ({n})": "Commands run and results ({n})",
    "Ultimi screenshot ({n})": "Latest screenshots ({n})",
    "In attesa del riepilogo…": "Waiting for the summary…",
    "Nessun riepilogo dalla conversazione": "No summary from the conversation",
    "Apri {name} e incolla": "Open {name} and paste",
    "Riepilogo ricevuto da {who}": "Summary received from {who}",
    "{n} righe: sarà incluso nel pacchetto. Puoi chiederne uno nuovo se il task è andato avanti.":
        "{n} lines: it will be included in the package. You can ask for a new one if the task has moved on.",
    "Ho incollato la richiesta nella chat di {source}: premi Invio, poi copia la risposta con il pulsante Copia del "
    "blocco di codice. Helpix la riconosce da solo.":
        "I pasted the request into the {source} chat: press Enter, then copy the answer with the code block's Copy "
        "button. Helpix recognizes it automatically.",
    "Consigliato: {source} scrive un riepilogo di ciò che avete fatto, così la nuova IA non riparte da zero. Senza "
    "riepilogo passano solo screenshot, comandi e risultati.":
        "Recommended: {source} writes a summary of what you did, so the new AI doesn't start from scratch. Without a "
        "summary only screenshots, commands and results are carried over.",
    "Esporta il task": "Export the task",
    "Importa un task": "Import a task",
    "Continua il task con un'altra IA…": "Continue the task with another AI…",
    "Nuovo task": "New task",
    "Task salvati…": "Saved tasks…",
    "Esporta il task su file…": "Export the task to a file…",
    "Importa un task da file…": "Import a task from a file…",
    "Richiesta di riepilogo incollata: premi Invio nella chat, poi copia la risposta.":
        "Summary request pasted: press Enter in the chat, then copy the answer.",
    "Riepilogo del task salvato: lo userò se passi a un'altra IA.": "Task summary saved: I'll use it if you switch to another AI.",
    "Il task è ancora vuoto: non c'è niente da esportare.": "The task is still empty: there is nothing to export.",
    "Nuovo task: si apre una chat nuova.": "New task: a new chat opens.",
    "Continua il task con il mio account (web)…": "Continue the task with my account (web)…",
    "Task spostato da {source} a {target}.": "Task moved from {source} to {target}.",
    "Apro {name} e incollo il task…": "Opening {name} and pasting the task…",
    "Task di Helpix (*{ext})": "Helpix tasks (*{ext})",
    "Task salvato in {path}": "Task saved to {path}",
    "Task incollato in {name}: controlla e premi Invio. Se non hai ancora fatto l'accesso, accedi e premi Ctrl+V.":
        "Task pasted into {name}: check it and press Enter. If you haven't signed in yet, sign in and press Ctrl+V.",
    "Non trovo la casella della chat di {name}: il testo del task è negli appunti, incollalo con Ctrl+V.":
        "I can't find the {name} chat box: the task text is on the clipboard, paste it with Ctrl+V.",
    "Impossibile importare il task:\n{exc}": "Could not import the task:\n{exc}",
    "Screenshot inviato a {site}": "Screenshot sent to {site}",

    # --- v0.6: cambio servizio, predefinito
    "Imposta {name} come predefinito": "Set {name} as default",
    "{name} è ora l'assistente predefinito: si aprirà così all'avvio.":
        "{name} is now the default assistant: Helpix will open with it at startup.",
    "predefinito": "default",
    "Task incollato in {name}: controlla e premi Invio.": "Task pasted into {name}: check it and press Enter.",
    "Non trovo la casella della chat di {name}: forse devi ancora fare l'accesso. Il testo del task è negli "
    "appunti: accedi e premi Ctrl+V.":
        "I can't find the {name} chat box: maybe you still need to sign in. The task text is on the clipboard: "
        "sign in and press Ctrl+V.",
    "Porta il task qui": "Bring the task here",
    "Hai un task in corso su {src}": "You have a task in progress on {src}",
    "Quando hai fatto l'accesso a {dst}, portalo qui: screenshot, comandi, risultati e riepilogo.":
        "Once you're signed in to {dst}, bring it here: screenshots, commands, results and summary.",
    "Torna a {src}": "Back to {src}",

    # --- v0.7: servizi nel browser di sistema (Google blocca i browser integrati)
    "Output copiato: nella chat del browser premi Ctrl+V.": "Output copied: press Ctrl+V in the browser chat.",
    "Copia di nuovo": "Copy again",
    "Da incollare nella chat": "To paste into the chat",
    "Usa il browser integrato": "Use the built-in browser",
    "Per i servizi a cui accedi con email e password": "For services you sign in to with email and password",
    "Tieni Helpix in primo piano": "Keep Helpix on top",
    "In primo piano": "Keep on top",
    "Screenshot: viene copiato, nella chat premi Ctrl+V.": "Screenshots: copied for you, press Ctrl+V in the chat.",
    "Comandi: copiali nel browser e torna su Helpix, compare il pulsante Esegui.":
        "Commands: copy them in the browser and come back to Helpix, the Run button appears.",
    "Output e diagnosi: vengono copiati, nella chat premi Ctrl+V.": "Output and diagnostics: copied for you, press Ctrl+V in the chat.",
    "Testo del task": "Task text",
    "{name} è aperto nel tuo browser": "{name} is open in your browser",
    "Usa {name} nel tuo browser (Chrome, Firefox…), dove l'accesso con Google funziona. Helpix lavora affiancato "
    "tramite gli appunti:":
        "Use {name} in your browser (Chrome, Firefox…), where signing in with Google works. Helpix works alongside "
        "it through the clipboard:",
    "Apri {name} nel browser": "Open {name} in the browser",
    "{n} caratteri": "{n} characters",
    "Screenshot {i}": "Screenshot {i}",
    "Ho copiato la richiesta: incollala nella chat di {source} nel browser (Ctrl+V) e inviala, poi copia la risposta "
    "con il pulsante Copia e torna su Helpix: la riconosce da solo.":
        "I copied the request: paste it into the {source} chat in your browser (Ctrl+V) and send it, then copy the "
        "answer with the Copy button and come back to Helpix: it recognizes it automatically.",
    "Gemini richiede un account Google e Google non permette l'accesso dai browser integrati nelle app. Aprilo nel "
    "tuo browser: Helpix lavora affiancato tramite gli appunti.":
        "Gemini requires a Google account, and Google doesn't allow sign-in from browsers built into apps. Open it in "
        "your browser: Helpix works alongside it through the clipboard.",
    "Accesso con Google non disponibile qui": "Sign-in with Google isn't available here",
    "Uso email e password": "I'll use email and password",
    "Google non permette l'accesso dai browser integrati nelle app. Accedi a {name} con email e password (o con il "
    "codice via email), oppure aprilo nel tuo browser.":
        "Google doesn't allow sign-in from browsers built into apps. Sign in to {name} with email and password (or "
        "with the email code), or open it in your browser.",
    "Apri {name} nel mio browser": "Open {name} in my browser",
    "{name} si apre nel tuo browser: Helpix lavora affiancato.": "{name} opens in your browser: Helpix works alongside it.",
    "{name} usa di nuovo il browser integrato.": "{name} uses the built-in browser again.",
    "Testo del task copiato: incollalo nella chat di {name} nel browser (Ctrl+V), poi copia gli screenshot dalla lista.":
        "Task text copied: paste it into the {name} chat in your browser (Ctrl+V), then copy the screenshots from the list.",
    "La prima volta accedi nella pagina del servizio: l'accesso resta salvato su questo PC. Google non permette "
    "l'accesso dai browser integrati nelle app: per ChatGPT e Claude accedi con email e password; Gemini si apre nel "
    "tuo browser.":
        "The first time, sign in on the service's page: the login stays saved on this PC. Google doesn't allow "
        "sign-in from browsers built into apps: for ChatGPT and Claude sign in with email and password; Gemini opens "
        "in your browser.",
    "Account Google · si apre nel tuo browser": "Google account · opens in your browser",
    "Screenshot copiato: nella chat di {name} nel browser premi Ctrl+V.": "Screenshot copied: press Ctrl+V in the {name} chat in your browser.",
    "Copiato: nella chat di {name} nel browser premi Ctrl+V.": "Copied: press Ctrl+V in the {name} chat in your browser.",

    # --- v0.7.1: accesso con email invece di Google
    "Gemini richiede un account Google e Google non permette l'accesso dai browser integrati. Usa la chiave gratuita "
    "di AI Studio (motore API, esperienza piena in Helpix) oppure aprilo nel browser.":
        "Gemini requires a Google account, and Google doesn't allow sign-in from built-in browsers. Use the free AI "
        "Studio key (API engine, full experience in Helpix) or open it in your browser.",
    "Gemini richiede l'account Google": "Gemini requires a Google account",
    "Accedi con email, non con Google": "Sign in with email, not Google",
    "Accedi con email": "Sign in with email",
    "Accedi a {name} con email o con il codice: l'accesso resta salvato, non dovrai rifarlo.":
        "Sign in to {name} with email or the code: the login stays saved, you won't have to do it again.",
    "«Accedi con Google» è bloccato da Google nei browser integrati, non da Helpix. Accedi a {name} con email o con "
    "il codice: resti dentro Helpix e l'accesso rimane salvato, lo fai una volta sola.":
        "“Sign in with Google” is blocked by Google in built-in browsers, not by Helpix. Sign in to {name} with email "
        "or the code: you stay inside Helpix and the login is saved, you only do it once.",
    # v0.8 — estensione del browser
    'Screenshot incollato nella chat di {name} nel browser.':
        'Screenshot pasted into the {name} chat in the browser.',
    'Incollato nella chat di {name} nel browser.':
        'Pasted into the {name} chat in the browser.',
    'Apri la cartella':
        'Open folder',
    'Copia il percorso':
        'Copy path',
    'Collega il browser':
        'Connect browser',
    'Usa Helpix nel tuo browser':
        'Use Helpix in your browser',
    "Con l'estensione di Helpix usi ChatGPT, Claude, Gemini, Copilot e DeepSeek nel browser di tutti i giorni, con l'accesso Google che funziona. Nella chat compare «Esegui con Helpix» sotto i comandi e, a lato, Screenshot e Diagnosi: Helpix esegue e incolla l'output nella casella, tu premi Invio. L'estensione non legge le conversazioni e non invia messaggi.":
        "With the Helpix extension you use ChatGPT, Claude, Gemini, Copilot and DeepSeek in your everyday browser, where Google sign-in works. In the chat, “Run with Helpix” appears below commands and Screenshot and Diagnostics on the side: Helpix runs the command and pastes the output into the chat box, you press Enter. The extension doesn't read your conversations or send messages.",
    "Dopo aver installato l'estensione ricarica le pagine delle chat già aperte.":
        'After installing the extension, reload any chat pages that are already open.',
    'Fine':
        'Done',
    'Installa dallo store':
        'Install from the store',
    'Chrome, Chromium, Edge, Brave, Vivaldi, Opera':
        'Chrome, Chromium, Edge, Brave, Vivaldi, Opera',
    'Apri la pagina delle estensioni (chrome://extensions, edge://extensions…), attiva «Modalità sviluppatore», premi «Carica estensione non pacchettizzata» e scegli questa cartella:':
        'Open the extensions page (chrome://extensions, edge://extensions…), turn on “Developer mode”, press “Load unpacked” and choose this folder:',
    'Firefox':
        'Firefox',
    'Firefox installa in modo permanente solo estensioni firmate da Mozilla. Finché la versione firmata non è disponibile: apri about:debugging › Questo Firefox › «Carica componente aggiuntivo temporaneo» e scegli manifest.json in questa cartella (resta attiva fino alla chiusura di Firefox):':
        'Firefox permanently installs only extensions signed by Mozilla. Until the signed version is available: open about:debugging › This Firefox › “Load Temporary Add-on” and choose manifest.json in this folder (it stays active until Firefox is closed):',
    "Il collegamento è già usato da un'altra finestra di Helpix.":
        'The connection is already used by another Helpix window.',
    "In attesa dell'estensione: installala e apri una chat nel browser.":
        'Waiting for the extension: install it and open a chat in the browser.',
    'Collegato: {names}':
        'Connected: {names}',
    'Copiato':
        'Copied',
    'Collegamento registrato per: {names}.':
        'Connection registered for: {names}.',
    'Browser installati come Flatpak o Snap ({names}): di norma non possono avviare il collegamento con Helpix. Usa la versione del browser installata dal gestore dei pacchetti (dnf, apt).':
        "Browsers installed as Flatpak or Snap ({names}): they usually can't start the connection with Helpix. Use the browser version installed by the package manager (dnf, apt).",
    'Collega il browser…':
        'Connect browser…',
    "Gemini richiede un account Google e Google non permette l'accesso dai browser integrati. Aprilo nel tuo browser: con l'estensione di Helpix comandi, screenshot e output funzionano direttamente nella chat.":
        "Gemini requires a Google account and Google doesn't allow sign-in from built-in browsers. Open it in your browser: with the Helpix extension, commands, screenshots and output work directly in the chat.",
    "C'è già uno screenshot in corso.":
        'A screenshot is already in progress.',
    'La diagnosi è già in corso.':
        'Diagnostics are already running.',
    "«Accedi con Google» è bloccato da Google nei browser integrati, non da Helpix. Accedi a {name} con email o con il codice (resti dentro Helpix), oppure usalo nel tuo browser con l'estensione di Helpix: comandi, screenshot e output funzionano direttamente nella chat.":
        '“Sign in with Google” is blocked by Google in built-in browsers, not by Helpix. Sign in to {name} with email or the code (you stay inside Helpix), or use it in your browser with the Helpix extension: commands, screenshots and output work directly in the chat.',
    'Non sembra un comando da eseguire su questo PC (o il programma non è installato).':
        "This doesn't look like a command to run on this PC (or the program isn't installed).",
    'Le opzioni di sudo (es. sudo -u, sudo -i) non sono supportate: usa «sudo comando».':
        "sudo options (e.g. sudo -u, sudo -i) aren't supported: use “sudo command”.",
    'pkexec (polkit) non è installato: impossibile ottenere i privilegi di amministratore.':
        "pkexec (polkit) isn't installed: administrator privileges can't be obtained.",
    'Task incollato nella chat di {name} nel browser: controlla e premi Invio.':
        'Task pasted into the {name} chat in the browser: check it and press Enter.',
    "Non trovo la casella della chat di {name} nel browser: forse devi ancora fare l'accesso. Accedi e usa «Copia» nell'avviso della pagina.":
        "Can't find the {name} chat box in the browser: you may still need to sign in. Sign in and use “Copy” in the page notice.",
    "Con l'estensione di Helpix per il browser non serve copiare: comandi, screenshot e output passano direttamente dalla chat del browser.":
        "With the Helpix browser extension there's no need to copy: commands, screenshots and output go straight through the browser chat.",
    'Screenshot: lo fai da qui o dal pulsante a lato della chat, viene incollato nella casella.':
        "Screenshot: take it from here or from the button beside the chat, it's pasted into the chat box.",
    'Comandi: premi «Esegui con Helpix» sotto il blocco di codice nella chat.':
        'Commands: press “Run with Helpix” below the code block in the chat.',
    'Output e diagnosi: incollati direttamente nella casella della chat, tu premi Invio.':
        'Output and diagnostics: pasted directly into the chat box, you press Enter.',
    'Helpix è collegato a {browsers}: lavora direttamente nella chat di {name}.':
        'Helpix is connected to {browsers}: it works directly in the {name} chat.',
    "Non ho trovato browser nella tua cartella utente: avvia il browser almeno una volta, poi riapri questa finestra.":
        "No browsers found in your home folder: start the browser at least once, then reopen this window.",
    "Google blocca il suo accesso dentro le app. Se il tuo account ChatGPT è nato con Google, aggiungi una password "
    "una volta: «Continua con email», scrivi la tua Gmail e scegli «Password dimenticata?». Poi accedi con email e "
    "password: lo stesso account, con le tue chat.":
        "Google blocks its sign-in inside apps. If your ChatGPT account was created with Google, add a password once: "
        "“Continue with email”, enter your Gmail and choose “Forgot password?”. Then sign in with email and password: "
        "same account, with your chats.",
    "Google blocca il suo accesso dentro le app. Scegli «Continua con email» e scrivi la tua Gmail: Claude ti manda "
    "un codice e ritrovi lo stesso account, con le tue chat.":
        "Google blocks its sign-in inside apps. Choose “Continue with email” and enter your Gmail: Claude sends you a "
        "code and you get the same account, with your chats.",
    "Google blocca il suo accesso dentro le app. Accedi a {name} con email (o con il tuo account Microsoft): "
    "l'accesso resta salvato.":
        "Google blocks its sign-in inside apps. Sign in to {name} with email (or your Microsoft account): the sign-in "
        "stays saved.",
    "Gemini richiede un account Google e Google non permette l'accesso dai browser integrati. Aprilo nel tuo "
    "browser: Helpix lavora affiancato tramite gli appunti.":
        "Gemini requires a Google account and Google doesn't allow sign-in from built-in browsers. Open it in your "
        "browser: Helpix works alongside it through the clipboard.",
    "Prima chiedi il riepilogo a {source}": "First ask {source} for a summary",
    "Helpix non legge la conversazione: è {source} a riassumerla. Premi «Chiedi il riepilogo», invia il messaggio "
    "nella chat e copia la risposta con il pulsante Copia: Helpix la inserisce qui da solo.":
        "Helpix doesn't read the conversation: {source} summarizes it. Press “Ask for a summary”, send the message in "
        "the chat and copy the reply with the Copy button: Helpix adds it here automatically.",
    "Non ho trovato il riepilogo nella risposta: copialo tu con il pulsante Copia del blocco di codice.":
        "I couldn't find the summary in the reply: copy it yourself with the code block's Copy button.",
    "Browser non disponibile.": "Browser not available.",
    "Chiedo il riepilogo a {name}: lo invio e leggo la risposta appena ha finito di scrivere…":
        "Asking {name} for a summary: I send it and read the reply as soon as it's done writing…",
    "Poi premi di nuovo Esporta.": "Then press Export again.",
    "Il task è ancora solo nella chat: chiedo il riepilogo a {name}, poi ti faccio salvare il file.":
        "The task is still only in the chat: I'm asking {name} for a summary, then you can save the file.",
    "Ho inviato la richiesta a {source}: appena finisce di scrivere, Helpix legge il riepilogo e lo mette qui.":
        "I sent the request to {source}: as soon as it's done writing, Helpix reads the summary and puts it here.",
    "Helpix chiede a {source} di riassumere la conversazione, invia la richiesta e inserisce qui il riepilogo appena "
    "arriva.":
        "Helpix asks {source} to summarize the conversation, sends the request and puts the summary here as soon as "
        "it arrives.",
    "Obiettivo": "Goal",
    "In una frase: es. sistemare il Wi-Fi, scrivere uno script di backup":
        "In one sentence: e.g. fix the Wi-Fi, write a backup script",
    "Sto continuando un lavoro iniziato con un'altra IA ({source}). Ti passo tutto il contesto: riparti da dove "
    "eravamo rimasti, senza rifare ciò che è già stato fatto.":
        "I'm continuing work started with another AI ({source}). Here's the full context: pick up where we left off, "
        "without redoing what's already been done.",
    "Quando mi proponi comandi, scrivine uno per blocco di codice e usa solo comandi non interattivi: li eseguirò "
    "e ti incollerò l'output.":
        "When you suggest commands, write one per code block and use only non-interactive commands: I'll run them "
        "and paste you the output.",
    # v0.9 — agenti nel terminale
    'Serve un abbonamento Claude Pro o Max (o un account Console)':
        'Requires a Claude Pro or Max subscription (or a Console account)',
    "Accesso con l'account ChatGPT (Plus, Pro, Business…) o con una chiave API":
        'Sign in with your ChatGPT account (Plus, Pro, Business…) or an API key',
    "Accesso con l'account Google; serve Node.js (npm) per installarlo":
        'Sign in with your Google account; Node.js (npm) is needed to install it',
    'Scrivi il riepilogo per Helpix nel file {file}, nel formato indicato nelle istruzioni.':
        'Write the summary for Helpix in the file {file}, in the format given in the instructions.',
    'Agenti nel terminale':
        'Agents in the terminal',
    "Riavvia l'agente":
        'Restart the agent',
    'Apri la cartella di lavoro':
        'Open the working folder',
    'nel terminale':
        'in the terminal',
    'da installare':
        'to install',
    'Screenshot (nella cartella di lavoro):':
        'Screenshots (in the working folder):',
    '{name} parte con il task: lo legge da {file}.':
        '{name} starts with the task: it reads it from {file}.',
    'Il task è pronto per {name}: installalo e avvialo, lo troverà nella sua cartella.':
        'The task is ready for {name}: install and start it, it will find it in its folder.',
    'Chiedo il riepilogo a {name}: lo scrive su file e Helpix lo legge da solo…':
        'Asking {name} for a summary: it writes it to a file and Helpix reads it automatically…',
    'Leggi il file {file}: è il task da continuare. Riparti da lì.':
        "Read the file {file}: it's the task to continue. Pick up from there.",
    'Il task è ancora solo nella conversazione: chiedo il riepilogo a {name}, poi ti faccio salvare il file.':
        "The task is still only in the conversation: I'm asking {name} for a summary, then you can save the file.",
    'Diagnosi passata a {name}: descrivi il problema e premi Invio.':
        'Diagnostics passed to {name}: describe the problem and press Enter.',
    'Screenshot passato a {name}: scrivi cosa vuoi sapere e premi Invio.':
        'Screenshot passed to {name}: write what you want to know and press Enter.',
    'Avvia {name} con il task':
        'Start {name} with the task',
    '{name} (terminale)':
        '{name} (terminal)',
    'Istruzioni ufficiali':
        'Official instructions',
    'Ricontrolla':
        'Check again',
    'Già installato? Helpix lo cerca di nuovo':
        'Already installed? Helpix looks for it again',
    'Installa':
        'Install',
    "Riavvia l'agente (nuova conversazione)":
        'Restart the agent (new conversation)',
    "Apri la cartella di lavoro dell'agente":
        "Open the agent's working folder",
    'Non avviato':
        'Not started',
    '{name} nel terminale · accesso con il tuo account':
        '{name} in the terminal · signed in with your account',
    'Installazione di {name}…':
        'Installing {name}…',
    '{name} si è chiuso':
        '{name} has exited',
    'Riavvia':
        'Restart',
    '{name} non è installato':
        "{name} isn't installed",
    '{name} di {who} lavora nel terminale qui sotto: legge i tuoi screenshot, esegue i comandi (chiedendoti conferma) e si collega con il tuo account nel browser. {plan}.\nHelpix lo installa per il tuo utente con il comando ufficiale:':
        '{name} by {who} works in the terminal below: it reads your screenshots, runs commands (asking you first) and signs in with your account in the browser. {plan}.\nHelpix installs it for your user with the official command:',
    'Installo {name} con il comando ufficiale:\n$ {cmd}\n\n':
        'Installing {name} with the official command:\n$ {cmd}\n\n',
    'Guarda lo screenshot {path} ':
        'Look at the screenshot {path} ',
    'Leggi la diagnosi del PC nel file {path}. Il problema è: ':
        'Read the PC diagnostics in the file {path}. The problem is: ',
    '\nInstallazione non riuscita (codice {rc}). Controlla il messaggio qui sopra o usa le istruzioni ufficiali.\n':
        '\nInstallation failed (code {rc}). Check the message above or use the official instructions.\n',
    '\n[{name} si è chiuso: premi «Riavvia» per una nuova conversazione]\n':
        '\n[{name} has exited: press “Restart” for a new conversation]\n',
    '{name} non è in esecuzione: premi «Riavvia».':
        "{name} isn't running: press “Restart”.",
    '{name} non è in esecuzione: avvialo e riprova.':
        "{name} isn't running: start it and try again.",
    '{name} non ha scritto il riepilogo nel file {file}.':
        "{name} didn't write the summary to the file {file}.",
    'Impossibile avviare {name}: {exc}\n':
        "Couldn't start {name}: {exc}\n",
    '\n✓ {name} installato. Lo avvio…\n':
        '\n✓ {name} installed. Starting it…\n',
    "Nuovo task: {name} riparte con una conversazione nuova.": "New task: {name} restarts with a new conversation.",
    "Angoli arrotondati": "Rounded corners",
    # finestra rapida
    'non attiva':
        'not active',
    'Apri la finestra rapida':
        'Open the quick window',
    'Scorciatoia globale…':
        'Global shortcut…',
    'non disponibile in questa sessione':
        'not available in this session',
    'Finestra rapida':
        'Quick window',
    'Helpix: richiesta rapida':
        'Helpix: quick request',
    "La finestra rapida si apre in basso a destra per chiedere al volo: scrivi, aggiungi uno screenshot e premi Invio. Il messaggio va all'assistente attivo in Helpix.\n\nScorciatoia globale (Ctrl+Alt+H): {state}.\n\nSe non è attiva, impostala a mano nelle impostazioni del desktop. KDE: Impostazioni di sistema › Tastiera › Scorciatoie › Aggiungi nuovo › Comando. GNOME: Impostazioni › Tastiera › Scorciatoie personalizzate. Comando da usare:\n\n{cmd}":
        "The quick window opens at the bottom right for quick questions: type, add a screenshot and press Enter. The message goes to the active assistant in Helpix.\n\nGlobal shortcut (Ctrl+Alt+H): {state}.\n\nIf it isn't active, set it manually in your desktop settings. KDE: System Settings › Keyboard › Shortcuts › Add New › Command. GNOME: Settings › Keyboard › Custom Shortcuts. Command to use:\n\n{cmd}",
    'attiva: {keys}':
        'active: {keys}',
    'non disponibile ({why})':
        'not available ({why})',
    'Helpix — richiesta rapida':
        'Helpix — quick request',
    'collegamento…':
        'connecting…',
    'Chiudi (Esc)':
        'Close (Esc)',
    'Chiedi qualcosa o descrivi il problema…':
        'Ask something or describe the problem…',
    'Cattura una parte dello schermo e la incolla nella chat':
        'Capture part of the screen and paste it into the chat',
    'Invio per inviare · Esc per chiudere':
        'Enter to send · Esc to close',
    'Screenshot':
        'Screenshot',
    'avvio Helpix…':
        'starting Helpix…',
    'Helpix non risponde':
        "Helpix isn't responding",
    'Helpix non è ancora pronto…':
        "Helpix isn't ready yet…",
    'Invio…':
        'Sending…',
    '✓ Screenshot nella chat':
        '✓ Screenshot in the chat',
    "_Testo copiato: incollalo nella chat del browser._": "_Text copied: paste it into the browser chat._",
    "Apri la conversazione in Helpix": "Open the conversation in Helpix",
    "Nuova richiesta (pulisce questa finestra)": "New request (clears this window)",
    "Nascondi (Esc o la scorciatoia)": "Hide (Esc or the shortcut)",
    "Invio per inviare · Esc per nascondere": "Enter to send · Esc to hide",
    "_(screenshot)_": "_(screenshot)_",
    "In attesa della risposta…": "Waiting for the answer…",
    "Tu": "You",
    "_…_": "_…_",
    "Sta rispondendo…": "Answering…",
    "_La risposta è nella finestra di Helpix._": "_The answer is in the Helpix window._",
    # sicurezza
    'Sicurezza…':
        'Security…',
    'Blocca ora':
        'Lock now',
    'Blocca Helpix':
        'Lock Helpix',
    'Impostazioni di sicurezza salvate.':
        'Security settings saved.',
    'Task protetto':
        'Protected task',
    'Questo task è cifrato. Inserisci la password:':
        'This task is encrypted. Enter the password:',
    'Sblocco non riuscito o annullato. Riprova.':
        'Unlock failed or cancelled. Try again.',
    'Helpix è bloccato: sbloccalo e riprova.':
        'Helpix is locked: unlock it and try again.',
    'Task cifrato salvato in {path}':
        'Encrypted task saved to {path}',
    'Password sbagliata.':
        'Wrong password.',
    'Proteggi il task con una password':
        'Protect the task with a password',
    'Password (almeno 8 caratteri)':
        'Password (at least 8 characters)',
    'Ripeti la password':
        'Repeat the password',
    'Esporta cifrato':
        'Export encrypted',
    'Helpix è bloccato':
        'Helpix is locked',
    "Sbloccalo con la password del tuo utente o con l'impronta.":
        'Unlock it with your user password or your fingerprint.',
    'Sblocca':
        'Unlock',
    'Sicurezza':
        'Security',
    "Blocca Helpix con la password del sistema o l'impronta":
        'Lock Helpix with the system password or fingerprint',
    'Proteggi con una password i task esportati':
        'Protect exported tasks with a password',
    'Non è stato possibile installare la regola di sistema per lo sblocco (autorizzazione annullata o pkexec non disponibile). Il blocco resta disattivato.':
        "The system rule for unlocking couldn't be installed (authorization cancelled or pkexec not available). The lock stays off.",
    "Il file sarà cifrato (AES-256): per aprirlo servirà questa password. Comunicala a chi deve importarlo per un'altra strada (non insieme al file). Se la perdi, il file non si può più aprire.":
        'The file will be encrypted (AES-256): opening it will require this password. Give it to whoever needs to import it by another channel (not together with the file). If you lose it, the file can no longer be opened.',
    'La password deve avere almeno 8 caratteri.':
        'The password must be at least 8 characters.',
    'Conferma nel dialogo del sistema…':
        'Confirm in the system dialog…',
    'Opzioni facoltative: scegli tu cosa attivare.':
        'Optional settings: you choose what to turn on.',
    "All'avvio e dopo un periodo in cui non lo usi, Helpix si blocca: per riaprirlo usi la password del tuo utente Linux o l'impronta (se è configurata nel sistema), con il dialogo di sistema. Anche la finestra rapida resta bloccata.":
        "At startup and after a period when you don't use it, Helpix locks itself: to reopen it you use your Linux user password or your fingerprint (if set up in the system), through the system dialog. The quick window stays locked too.",
    'Blocco automatico se non lo usi':
        'Auto-lock when not in use',
    'Ogni file .helpix esportato viene cifrato (AES-256) con una password che scegli al momento. I file cifrati ricevuti da altri si aprono sempre, chiedendo la password.':
        'Every exported .helpix file is encrypted (AES-256) with a password you choose at that moment. Encrypted files received from others can always be opened, by entering the password.',
    'Da sapere: gli accessi a ChatGPT, Claude e agli altri servizi li conserva il browser integrato nella tua cartella utente. Il blocco impedisce di usarli da Helpix; per proteggere i file quando il PC è spento serve la cifratura del disco (LUKS).':
        'Good to know: your sign-ins to ChatGPT, Claude and the other services are kept by the built-in browser in your user folder. The lock prevents using them from Helpix; protecting the files when the PC is off requires disk encryption (LUKS).',
    'polkit (pkcheck) non è installato: il blocco non è disponibile.':
        "polkit (pkcheck) isn't installed: the lock isn't available.",
    'Le due password non coincidono.':
        "The two passwords don't match.",
    'Al salvataggio Helpix installa una regola di sistema (una volta sola): ti verrà chiesta la password di amministratore.':
        "When you save, Helpix installs a system rule (once only): you'll be asked for the administrator password.",
    'dopo 5 minuti': 'after 5 minutes',
    'dopo 15 minuti': 'after 15 minutes',
    'dopo 30 minuti': 'after 30 minutes',
    "dopo un'ora": 'after one hour',
    'mai': 'never',
    # modello ed effort, finestra rapida
    "Effort (quanto ragiona)": "Effort (how much it reasons)",
    "automatico (predefinito del modello)": "automatic (model default)",
    "modello predefinito": "default model",
    "_Nuovo task avviato._": "_New task started._",
    "effort non disponibile": "effort not available",
    "Modello ed effort si scelgono nella pagina di {site}.": "Model and effort are chosen on the {site} page.",
    "predefinito dell'agente": "agent default",
    "Modello ed effort di {name}": "{name} model and effort",
    "Cambiato subito in {name}.": "Changed right away in {name}.",
    "Vale dalla prossima conversazione: in Helpix premi «Riavvia».":
        "Applies from the next conversation: in Helpix press “Restart”.",
    "effort auto": "effort auto",
    "_Non vedo la risposta nella pagina: guardala in Helpix (↗)._":
        "_I can't see the answer on the page: look at it in Helpix (↗)._",
    "Effort: quanto ragiona il modello prima di rispondere": "Effort: how much the model reasons before answering",
    "_Nessuna risposta qui: guardala in Helpix (↗)._": "_No answer here: look at it in Helpix (↗)._",
    "Ancorata all'angolo: premi per spostarla": "Anchored to the corner: press to move it",
    "Trascinala dove vuoi, poi premi per ancorarla lì": "Drag it where you want, then press to anchor it there",
    # area di notifica e scorciatoia
    "Chiudendo, resta nell'area di notifica":
        'When closed, stay in the notification area',
    "Riduci nell'area di notifica":
        'Minimize to the notification area',
    'Apri Helpix':
        'Open Helpix',
    'Esci da Helpix':
        'Quit Helpix',
    "Ho aggiunto il lanciatore «Helpix — richiesta rapida» con la scorciatoia Ctrl+Alt+H e aperto le scorciatoie di KDE.\n\nSe premendo Ctrl+Alt+H da un altro programma non succede nulla: nella finestra delle scorciatoie premi «Aggiungi nuovo › Applicazione», scegli «Helpix — richiesta rapida» e assegnale Ctrl+Alt+H (se KDE segnala un conflitto, scegli un'altra combinazione).":
        "I added the “Helpix — quick request” launcher with the Ctrl+Alt+H shortcut and opened KDE's shortcuts.\n\nIf pressing Ctrl+Alt+H from another program does nothing: in the shortcuts window press “Add New › Application”, choose “Helpix — quick request” and assign Ctrl+Alt+H (if KDE reports a conflict, choose another combination).",
    "Helpix resta attivo nell'area di notifica: Ctrl+Alt+H apre la finestra rapida, clic sull'icona per riaprirlo.":
        'Helpix stays active in the notification area: Ctrl+Alt+H opens the quick window, click the icon to reopen it.',
    'Imposta la scorciatoia nel desktop':
        'Set the shortcut in the desktop',
    'La finestra rapida si apre in basso a destra per chiedere al volo: scrivi e premi Invio, la risposta compare lì. La stessa scorciatoia la mostra e la nasconde.\n\nScorciatoia globale (Ctrl+Alt+H) chiesta al desktop: {state}.':
        'The quick window opens at the bottom right for quick questions: type and press Enter, the answer appears there. The same shortcut shows and hides it.\n\nGlobal shortcut (Ctrl+Alt+H) requested from the desktop: {state}.',
    'Se da altri programmi non funziona, Helpix può impostarla nel desktop (KDE o GNOME). Comando usato:\n{cmd}':
        "If it doesn't work from other programs, Helpix can set it in the desktop (KDE or GNOME). Command used:\n{cmd}",
    'Scorciatoia Ctrl+Alt+H aggiunta alle scorciatoie personalizzate di GNOME.':
        "Ctrl+Alt+H shortcut added to GNOME's custom shortcuts.",
    'Non è stato possibile impostare la scorciatoia: aggiungila a mano in Impostazioni › Tastiera.':
        "The shortcut couldn't be set: add it manually in Settings › Keyboard.",
    "Vuoi aprire la finestra rapida di Helpix con Ctrl+Alt+H da qualsiasi programma?":
        "Do you want to open the Helpix quick window with Ctrl+Alt+H from any program?",
    "Il desktop ti chiederà di confermare la scorciatoia (e potrai cambiarla).":
        "The desktop will ask you to confirm the shortcut (and you can change it).",
    "Attiva Ctrl+Alt+H": "Enable Ctrl+Alt+H",
    "Non ora": "Not now",
    "Puoi attivarla quando vuoi da Impostazioni › Finestra rapida.":
        "You can enable it any time from Settings › Quick window.",
    "in attesa del desktop…": "waiting for the desktop…",
    "Scorciatoia attiva: {keys} apre e chiude la finestra rapida da qualsiasi programma.":
        "Shortcut active: {keys} opens and closes the quick window from any program.",
    "Chiedi di nuovo al desktop": "Ask the desktop again",
    "registrata ma senza tasti: assegnali nelle scorciatoie del desktop":
        "registered but without keys: assign them in the desktop shortcuts",
    # filtro privacy
    "chiavi private": "private keys", "token": "tokens", "password e segreti": "passwords and secrets",
    "email": "emails", "IP pubblici": "public IPs", "indirizzi MAC": "MAC addresses", "nome utente": "user name",
    "nome del PC": "computer name", "{n} dati ({parts})": "{n} items ({parts})",
    "CHIAVE-PRIVATA": "PRIVATE-KEY", "SEGRETO": "SECRET", "UTENTE": "USER",
    "Filtro privacy attivo: password, token, email, IP pubblici, nome utente e nome del PC "
    "vengono oscurati prima di finire nella chat.":
        "Privacy filter on: passwords, tokens, emails, public IPs, user name and computer name "
        "are masked before they reach the chat.",
    "Filtro privacy disattivato.": "Privacy filter off.",
    "Filtro privacy ATTIVO: oscura password, token, chiavi, email, telefoni, IP pubblici, reti Wi-Fi, "
    "nomi e domini di Active Directory, nome utente e nome del PC in tutto ciò che arriva all'IA "
    "tramite Helpix: output dei comandi, diagnosi, task, finestra rapida e quello che incolli tu. "
    "Non vale per gli screenshot e per ciò che scrivi a mano. Clic per disattivare.":
        "Privacy filter ON: masks passwords, tokens, keys, emails, phone numbers, public IPs, Wi-Fi networks, "
        "Active Directory names and domains, user name and computer name in everything that reaches the AI "
        "through Helpix: command output, diagnostics, tasks, the quick window and what you paste. "
        "Screenshots and what you type by hand are not covered. Click to turn it off.",
    "numeri di telefono": "phone numbers", "nomi di reti Wi-Fi": "Wi-Fi network names",
    "identificativi della macchina": "machine identifiers",
    "nomi di persone e oggetti di Active Directory": "Active Directory people and object names",
    "domini interni": "internal domains", "DOMINIO": "DOMAIN", "SERIALE": "SERIAL", "TELEFONO": "PHONE",
    "NOME": "NAME",
    "(scudo privacy acceso: dati sensibili oscurati; gli screenshot restano come sono)":
        "(privacy shield on: sensitive data masked; screenshots are left as they are)",
    # scorciatoia nei vari desktop, area di notifica, polkit
    "icona di Helpix nell'area di notifica di GNOME": "Helpix icon in the GNOME notification area",
    "L'estensione AppIndicator è già installata ma spenta: la attivo?":
        "The AppIndicator extension is installed but turned off: shall I turn it on?",
    "Attiva": "Turn on", "Area di notifica": "Notification area",
    "Estensione AppIndicator attivata. Su GNOME le estensioni nuove si caricano all'accesso: esci e rientra nella "
    "sessione, poi l'icona di Helpix comparirà nella barra in alto.":
        "AppIndicator extension turned on. GNOME loads new extensions at login: log out and back in, then the "
        "Helpix icon will appear in the top bar.",
    "Non sono riuscito ad attivare l'estensione AppIndicator: attivala dall'app Estensioni.":
        "I couldn't turn on the AppIndicator extension: turn it on from the Extensions app.",
    "Su questo GNOME non c'è l'area di notifica, quindi Helpix non può restare attivo con la sua icona quando "
    "chiudi la finestra.":
        "This GNOME has no notification area, so Helpix can't keep running with its icon when you close the window.",
    "Vuoi aggiungerla? Helpix installa e attiva l'estensione AppIndicator (la usano anche altre app, come Dropbox, "
    "Steam o Discord).":
        "Do you want to add it? Helpix installs and turns on the AppIndicator extension (other apps such as Dropbox, "
        "Steam or Discord use it too).",
    "Aggiungila": "Add it", "No, grazie": "No, thanks",
    "Usa sempre questa scelta e non mostrare più questa schermata":
        "Always use this choice and don't show this screen again",
    "La ritrovi quando vuoi in Impostazioni › Schermata iniziale.":
        "You can open it again any time from Settings › Start screen.",
    "Schermata iniziale…": "Start screen…",
    "Mostra la schermata iniziale all'avvio": "Show the start screen at startup",
    "Scelta salvata come predefinita: Helpix si aprirà così. La schermata iniziale la ritrovi in Impostazioni.":
        "Choice saved as default: Helpix will open like this. You'll find the start screen in Settings.",
    "<b>Helpix {version}</b><br>Assistente AI open source per il troubleshooting su Linux e Windows.<br><br>"
    "© 2026 Crash<br>"
    "Helpix è software libero: puoi ridistribuirlo e/o modificarlo secondo i termini della "
    "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General Public License</a>, versione 3 o "
    "(a tua scelta) successiva. È distribuito <b>senza alcuna garanzia</b>.<br>"
    "Codice sorgente: <a href='{url}'>{url}</a><br><br>"
    "Componenti di terzi: Qt e PySide6 (LGPL-3.0), xterm.js (MIT), font Inter e JetBrains Mono "
    "(SIL Open Font License). Dettagli nel file THIRD-PARTY-NOTICES.md.<br>"
    "Helpix non è affiliato a OpenAI, Anthropic, Google, Microsoft o DeepSeek: i loro nomi e marchi "
    "appartengono ai rispettivi proprietari.":
        "<b>Helpix {version}</b><br>Open source AI troubleshooting assistant for Linux and Windows.<br><br>"
        "© 2026 Crash<br>"
        "Helpix is free software: you can redistribute it and/or modify it under the terms of the "
        "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU General Public License</a>, version 3 or "
        "(at your option) any later version. It comes with <b>ABSOLUTELY NO WARRANTY</b>.<br>"
        "Source code: <a href='{url}'>{url}</a><br><br>"
        "Third-party components: Qt and PySide6 (LGPL-3.0), xterm.js (MIT), Inter and JetBrains Mono fonts "
        "(SIL Open Font License). Details in THIRD-PARTY-NOTICES.md.<br>"
        "Helpix is not affiliated with OpenAI, Anthropic, Google, Microsoft or DeepSeek: their names and "
        "trademarks belong to their respective owners.",
    "questo desktop": "this desktop", "Copia la riga": "Copy the line",
    "Riga copiata: incollala nella configurazione del desktop e ricaricala.":
        "Line copied: paste it into your desktop configuration and reload it.",
    "nessun agente polkit: manca il programma che mostra la finestra della password (su Hyprland, Sway o niri "
    "avvia ad esempio hyprpolkitagent, polkit-gnome o lxqt-policykit)":
        "no polkit agent: the program that shows the password window is missing (on Hyprland, Sway or niri start "
        "for example hyprpolkitagent, polkit-gnome or lxqt-policykit)",
    "impostata nelle scorciatoie di {name}": "set in the {name} shortcuts",
    "Se da altri programmi non funziona, Helpix può impostarla nelle scorciatoie di {name}. Comando usato:\n{cmd}":
        "If it doesn't work from other programs, Helpix can set it in the {name} shortcuts. Command used:\n{cmd}",
    "Scorciatoia Ctrl+Alt+H aggiunta alle scorciatoie di {name}: prova a premerla da un altro programma.":
        "Ctrl+Alt+H added to the {name} shortcuts: try pressing it from another program.",
    "Non è stato possibile impostare la scorciatoia: aggiungila a mano nelle impostazioni della tastiera di {name} "
    "con il comando {cmd}":
        "Couldn't set the shortcut: add it by hand in the {name} keyboard settings with the command {cmd}",
    "Aggiungi nelle scorciatoie del desktop una scorciatoia (Ctrl+Alt+H) che esegue:":
        "Add a shortcut (Ctrl+Alt+H) in your desktop shortcuts that runs:",
    "Su {name} aggiungi questa riga in {where}:": "On {name} add this line to {where}:",
    "codici fiscali, IBAN e carte": "tax codes, IBANs and cards", "CODICE-FISCALE": "TAX-CODE", "CARTA": "CARD",
    "Scudo privacy acceso: i dati sensibili qui sotto sono già oscurati.":
        "Privacy shield on: sensitive data below is already masked.",
    "Filtro privacy disattivato: clic per oscurare i dati sensibili prima che finiscano nella chat.":
        "Privacy filter off: click to mask sensitive data before it reaches the chat.",
    "Filtro privacy: oscurati {what}.": "Privacy filter: masked {what}.",
    # dipendenze di sistema
    "Dipendenze di sistema…": "System dependencies…", "Dipendenze di sistema": "System dependencies",
    "Controllo le dipendenze di sistema…": "Checking system dependencies…",
    "Tutto a posto: non manca nulla.": "All good: nothing is missing.",
    " (consigliata)": " (recommended)",
    "Mancano alcuni componenti del sistema:": "Some system components are missing:",
    "Helpix può installarli con il gestore pacchetti ({pm}): la password di amministratore la chiede il sistema.":
        "Helpix can install them with the package manager ({pm}): the system will ask for the administrator "
        "password.",
    "Su questo sistema (immutabile) non posso installarli da qui.":
        "On this (immutable) system I can't install them from here.",
    "Non trovo un gestore pacchetti che so usare.": "I can't find a package manager I know how to use.",
    "Comando da eseguire:": "Command to run:",
    "Installo: {pkgs}…": "Installing: {pkgs}…",
    "Installazione annullata.": "Installation cancelled.",
    "Dipendenze installate. Riavvia Helpix se qualcosa non funzionava.":
        "Dependencies installed. Restart Helpix if something wasn't working.",
    "Non è andato tutto a buon fine.": "Not everything went well.",
    "finestra rapida e Qt su X11": "quick window and Qt on X11",
    "Qt (interfaccia di Helpix)": "Qt (Helpix interface)",
    "screenshot di una finestra con un clic (X11)": "one-click window screenshot (X11)",
    "screenshot tramite portal (Wayland)": "screenshots via the portal (Wayland)",
    "Prima installo ciò che serve ({tools}) con il gestore pacchetti; la password di amministratore la chiede "
    "il sistema qui sotto:\n$ {cmd}\n\n":
        "First I install what's needed ({tools}) with the package manager; the system asks for the administrator "
        "password below:\n$ {cmd}\n\n",
    "Manca {tools}: installalo con il gestore pacchetti della tua distribuzione, poi riprova.\n\n":
        "{tools} is missing: install it with your distribution's package manager, then try again.\n\n",
    # giro guidato e consigli
    "Guida rapida (giro guidato)": "Quick guide (guided tour)",
    "Mostra i suggerimenti all'avvio": "Show tips at startup",
    "Salta il giro": "Skip the tour", "Avanti": "Next", "Giro completo": "Full tour",
    "Altro consiglio": "Another tip", "Lo sapevi?": "Did you know?", "{n} di {total}": "{n} of {total}",
    "Ciao, sono Helpix! 👋": "Hi, I'm Helpix! 👋",
    "Ti porto a fare un giro veloce: un minuto e sai dove mettere le mani. Puoi saltarlo quando vuoi, tanto lo "
    "ritrovi in Impostazioni › Guida rapida.":
        "Let me show you around: one minute and you'll know where everything is. Skip it whenever you like, "
        "you can find it again in Settings › Quick guide.",
    "Chi ti dà una mano oggi?": "Who's helping you out today?",
    "Da qui scegli l'assistente: ChatGPT, Claude, Gemini, Copilot o DeepSeek con il tuo account, oppure un agente "
    "nel terminale (Claude Code, Codex, Gemini CLI). Se un'IA si incarta, dallo stesso menu passi il lavoro a "
    "un'altra senza ricominciare da capo.":
        "Pick your assistant here: ChatGPT, Claude, Gemini, Copilot or DeepSeek with your own account, or an agent "
        "in the terminal (Claude Code, Codex, Gemini CLI). If an AI gets stuck, the same menu hands the work over "
        "to another one without starting from scratch.",
    "Cervello e impegno": "Brains and effort",
    "Il modello e quanto deve pensarci su (effort). Più effort vuol dire risposte più ragionate ma più lente: per "
    "le domande al volo il minimo va benissimo.":
        "The model, and how hard it should think (effort). More effort means more thoughtful but slower answers: "
        "for quick questions the minimum is just fine.",
    "Il posto dove si chiacchiera": "Where the chatting happens",
    "Questa è proprio la pagina del servizio, con il tuo account: scrivi come sempre. Helpix ci lavora attorno: "
    "incolla gli screenshot, esegue i comandi che copi e ti riporta l'output nella chat.":
        "This is the service's real page, with your account: type as usual. Helpix works around it: it pastes "
        "screenshots, runs the commands you copy and brings the output back to the chat.",
    "Qui gira l'agente, in un terminale vero: legge i file, propone i comandi e ti chiede il permesso prima di "
    "toccare qualcosa. Screenshot e Diagnosi finiscono direttamente nella sua riga di comando.":
        "The agent runs here, in a real terminal: it reads files, suggests commands and asks before touching "
        "anything. Screenshots and Diagnostics go straight into its command line.",
    "Qui chatti con l'IA tramite la chiave API. I comandi che propone compaiono in schede con il pulsante Esegui: "
    "niente copia-incolla, e l'output torna da solo all'IA.":
        "Here you chat with the AI through your API key. The commands it suggests show up as cards with a Run "
        "button: no copy and paste, and the output goes back to the AI by itself.",
    "Una foto vale mille log": "A picture is worth a thousand logs",
    "Fai uno screenshot dell'errore e finisce dritto nella casella della chat, senza passare dagli appunti. Dalla "
    "freccetta: una finestra, lo schermo intero o un'area dopo 3 secondi (per i menu che spariscono appena muovi "
    "il mouse).":
        "Take a screenshot of the error and it lands right in the chat box, without going through the clipboard. "
        "From the little arrow: a window, the whole screen, or an area after 3 seconds (for menus that vanish as "
        "soon as you move the mouse).",
    "Diagnosi lampo": "Lightning diagnostics",
    "Un clic e raccolgo disco, memoria, rete, servizi in errore e gli ultimi errori del log. Prima di incollare ti "
    "faccio vedere tutto: togli quello che non vuoi condividere.":
        "One click and I gather disk, memory, network, failed services and the latest log errors. Before pasting "
        "I show you everything: remove whatever you'd rather not share.",
    "Comandi senza fatica": "Effortless commands",
    "Quando copi un comando proposto dall'IA, in basso compare la barra «Hai copiato un comando»: premi Esegui e "
    "l'output torna nella chat da solo. Se il comando è di quelli pericolosi (rm -r, dd, mkfs…) te lo dico prima, "
    "e sudo chiede la password al sistema, mai a me.":
        "When you copy a command the AI suggests, the \"You copied a command\" bar appears at the bottom: press Run "
        "and the output goes back to the chat by itself. If it's a risky one (rm -r, dd, mkfs…) I warn you first, "
        "and sudo asks the system for the password, never me.",
    "Lo scudo della privacy": "The privacy shield",
    "Acceso, oscura password, token, email, IP pubblici, nome utente e nome del PC prima che arrivino nella chat. "
    "Comodissimo sui PC dei clienti. Gli screenshot però non li vede: occhio a cosa inquadri.":
        "When it's on, it masks passwords, tokens, emails, public IPs, user name and computer name before they "
        "reach the chat. Super handy on customers' PCs. It can't see screenshots though: mind what you capture.",
    "Modalità smanettone": "Tinkerer mode",
    "Terminale integrato e albero delle cartelle, per chi vuole vedere cosa succede sotto il cofano. Si apre e si "
    "chiude anche con Ctrl+`.":
        "Built-in terminal and folder tree, for those who want to see what's going on under the hood. Ctrl+` "
        "opens and closes it too.",
    "Giorno o notte?": "Day or night?",
    "Tema chiaro o scuro, a seconda dell'umore (e dell'ora). Gli occhi ringraziano.":
        "Light or dark theme, depending on your mood (and the time). Your eyes will thank you.",
    "Il cassetto degli attrezzi": "The toolbox",
    "Chiavi API, sicurezza (blocco con la password del PC o l'impronta, export cifrato), dipendenze di sistema, "
    "lingua, aspetto e finestra rapida. E sì, anche questo giro guidato.":
        "API keys, security (lock with your computer password or fingerprint, encrypted export), system "
        "dependencies, language, appearance and the quick window. And yes, this tour too.",
    "Premi Ctrl+Alt+H da qualsiasi programma: in basso a destra compare un riquadrino per le domande al volo, con "
    "la risposta lì dentro. Ripremi e sparisce. Il lucchetto lo tiene al suo posto.":
        "Press Ctrl+Alt+H from any program: a small box pops up in the bottom right for quick questions, with the "
        "answer right inside. Press again and it's gone. The padlock keeps it in place.",
    "La finestra rapida": "The quick window",
    "Cambio IA al volo": "Switch AI on the fly",
    "Messaggi gratis finiti o risposta che gira in tondo? «Continua il task con un'altra IA»: chiedo il riepilogo a "
    "quella di adesso e lo passo alla nuova, screenshot compresi.":
        "Out of free messages, or going round in circles? \"Continue the task with another AI\": I ask the current "
        "one for a summary and hand it to the new one, screenshots included.",
    "Sempre a portata di mano": "Always within reach",
    "Chiudendo la finestra posso restare nell'area di notifica (lo scegli tu nelle Impostazioni): un clic "
    "sull'icona e torno, e la scorciatoia della finestra rapida resta attiva.":
        "When you close the window I can stay in the notification area (you choose in Settings): one click on the "
        "icon and I'm back, and the quick window shortcut keeps working.",
    "Fatto, sei pronto! 🎉": "Done, you're all set! 🎉",
    "Ora sai tutto quello che serve. Se ti perdi, il giro lo ritrovi in Impostazioni › Guida rapida. Buona caccia "
    "ai problemi!":
        "Now you know everything you need. If you get lost, the tour is in Settings › Quick guide. Happy "
        "troubleshooting!",

    # --- Windows: comandi, elevazione, rischi
    "cancellazione ricorsiva di file": "recursive file deletion",
    "formattazione o cancellazione di un disco": "formatting or wiping a disk",
    "modifica dell'avvio di Windows": "changes to Windows startup",
    "cancellazione di chiavi del registro di sistema": "deletion of system registry keys",
    "disattivazione delle protezioni di Windows (antivirus o firewall)":
        "disabling Windows protections (antivirus or firewall)",
    "cancellazione delle copie di backup di Windows": "deletion of Windows backup copies",
    "cancellazione dei registri eventi": "clearing the event logs",
    "disattivazione dei controlli sugli script per tutto il PC": "disabling script checks for the whole PC",
    "Controllo account utente": "User Account Control",
    "Richiesta di amministratore annullata.\n": "Administrator request cancelled.\n",
    "\nIl comando gira come amministratore: Helpix non può fermarlo da qui. Se serve, chiudilo da Gestione attività.\n":
        "\nThe command runs as administrator: Helpix cannot stop it from here. If needed, end it from Task Manager.\n",
    "Windows chiede il permesso di amministratore (Controllo account utente)…\n":
        "Windows is asking for administrator permission (User Account Control)…\n",
    "Windows chiederà il permesso di amministratore (Controllo account utente)":
        "Windows will ask for administrator permission (User Account Control)",
    "Come amministratore": "As administrator",
    "Funziona da qualsiasi programma; la disattivi quando vuoi da Impostazioni.":
        "It works from any program; you can turn it off at any time in Settings.",
    "La finestra rapida si apre in basso a destra per chiedere al volo: scrivi e premi Invio, la risposta compare lì. "
    "La stessa scorciatoia la mostra e la nasconde.\n\nScorciatoia globale Ctrl+Alt+H: {state}.":
        "The quick window opens at the bottom right to ask on the fly: type and press Enter, the answer appears there. "
        "The same shortcut shows and hides it.\n\nGlobal shortcut Ctrl+Alt+H: {state}.",
    "Ctrl+Alt+H non è disponibile ({why}). Dentro Helpix funziona comunque; la finestra rapida si apre anche dal menu "
    "dell'icona vicino all'orologio.":
        "Ctrl+Alt+H is not available ({why}). It still works inside Helpix; the quick window also opens from the menu "
        "of the icon next to the clock.",
    "Prima installo Node.js con winget (Windows può chiedere il permesso di amministratore):\n"
    "> winget install OpenJS.NodeJS.LTS\n\n":
        "First I install Node.js with winget (Windows may ask for administrator permission):\n"
        "> winget install OpenJS.NodeJS.LTS\n\n",
    "Installo {name} con il comando ufficiale:\n> {cmd}\n\n": "Installing {name} with the official command:\n> {cmd}\n\n",

    # --- Windows: diagnosi rapida
    "Sistema, avvio e memoria": "System, boot and memory",
    "Servizi automatici fermi": "Automatic services not running",
    "Errori delle ultime 24 ore": "Errors in the last 24 hours",
    "Riavvio in attesa": "Restart pending",
    "Antivirus (Microsoft Defender)": "Antivirus (Microsoft Defender)",
    "Ciao, ho un problema sul mio PC Windows. Ecco le informazioni di sistema raccolte da Helpix "
    "(un'app di troubleshooting). Quando mi proponi dei comandi, usa PowerShell, scrivine uno per blocco di "
    "codice e usa solo comandi non interattivi: li eseguirò e ti incollerò l'output.":
        "Hi, I have a problem on my Windows PC. Here is the system information collected by Helpix "
        "(a troubleshooting app). When you suggest commands, use PowerShell, put one per code block and use only "
        "non-interactive commands: I will run them and paste the output back to you.",
    "- Sistema: {distro} ({arch})": "- System: {distro} ({arch})",
    "- Shell: {shell}; gestori di pacchetti: {pkg}": "- Shell: {shell}; package managers: {pkg}",

    # --- Windows: sblocco con Windows Hello
    "Sblocca Helpix": "Unlock Helpix",
    "Blocca Helpix con Windows Hello (PIN, impronta o volto)": "Lock Helpix with Windows Hello (PIN, fingerprint or face)",
    "All'avvio e dopo un periodo in cui non lo usi, Helpix si blocca: per riaprirlo confermi con Windows Hello (PIN, "
    "impronta o volto), lo stesso dialogo che Windows usa per confermare la tua identità. Anche la finestra rapida "
    "resta bloccata.":
        "At startup and after a period when you don't use it, Helpix locks itself: to reopen it you confirm with "
        "Windows Hello (PIN, fingerprint or face), the same dialog Windows uses to confirm your identity. The quick "
        "window stays locked too.",
    "Da sapere: gli accessi a ChatGPT, Claude e agli altri servizi li conserva il browser integrato nella tua cartella "
    "utente. Il blocco impedisce di usarli da Helpix; per proteggere i file quando il PC è spento serve la cifratura "
    "del disco (BitLocker).":
        "Good to know: the sign-ins to ChatGPT, Claude and the other services are kept by the built-in browser in your "
        "user folder. The lock prevents using them from Helpix; to protect the files when the PC is off you need disk "
        "encryption (BitLocker).",
    "Windows Hello non è configurato: imposta un PIN (o impronta o volto) in Impostazioni › Account › Opzioni di "
    "accesso, poi riapri questa finestra.":
        "Windows Hello is not set up: set a PIN (or fingerprint or face) in Settings › Accounts › Sign-in options, "
        "then reopen this window.",
    "Windows Hello non è disponibile su questo PC: il blocco non si può usare.":
        "Windows Hello is not available on this PC: the lock cannot be used.",
    "Quando copi un comando proposto dall'IA, in basso compare la barra «Hai copiato un comando»: premi Esegui e "
    "l'output torna nella chat da solo. Se il comando è di quelli pericolosi (Remove-Item -Recurse, diskpart, reg "
    "delete…) te lo dico prima, e per i permessi di amministratore è Windows a chiedertelo, mai io.":
        "When you copy a command the AI suggests, the \"You copied a command\" bar appears at the bottom: press Run "
        "and the output goes back to the chat by itself. If it's a risky one (Remove-Item -Recurse, diskpart, reg "
        "delete…) I warn you first, and Windows asks for administrator permission, never me.",
}
