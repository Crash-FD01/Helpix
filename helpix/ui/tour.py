# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Giro guidato e «consiglio del giorno»: nuvolette che spiegano Helpix con tono amichevole.

- Giro completo (primo avvio, o Impostazioni › Guida rapida): la finestra si oscura, resta illuminato solo
  il pulsante di cui si parla e una nuvoletta lo spiega. Avanti/Indietro, frecce, Invio, Esc.
- Consiglio del giorno (avvii successivi, finché la spunta è attiva): una sola nuvoletta, senza oscurare e
  senza bloccare il resto della finestra.
In ogni nuvoletta c'è la spunta «Mostra i suggerimenti all'avvio» (impostazione `show_tips`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (QCheckBox, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..system import IS_WINDOWS
from .. import theme
from ..i18n import tr

TAIL = 10          # altezza della punta della nuvoletta
RADIUS = 14
WIDTH = 360
HALO = 6           # margine della zona illuminata attorno al pulsante


@dataclass
class Step:
    key: str
    target: Callable[[], QWidget | None] | None   # None: nuvoletta al centro
    title: str
    text: Callable[[], str] | str
    tip: bool = True                               # usabile anche come consiglio del giorno

    def body(self) -> str:
        return self.text() if callable(self.text) else self.text


def steps_for(win) -> list[Step]:
    """I passi del giro; i testi si leggono al momento (lingua e motore attuali)."""
    def area_text() -> str:
        engine = getattr(win, "engine", "web")
        if engine == "agent":
            return tr("Qui gira l'agente, in un terminale vero: legge i file, propone i comandi e ti chiede il "
                      "permesso prima di toccare qualcosa. Screenshot e Diagnosi finiscono direttamente nella sua "
                      "riga di comando.")
        if engine == "api":
            return tr("Qui chatti con l'IA tramite la chiave API. I comandi che propone compaiono in schede con il "
                      "pulsante Esegui: niente copia-incolla, e l'output torna da solo all'IA.")
        return tr("Questa è proprio la pagina del servizio, con il tuo account: scrivi come sempre. Helpix ci lavora "
                  "attorno: incolla gli screenshot, esegue i comandi che copi e ti riporta l'output nella chat.")

    return [
        Step("welcome", None, tr("Ciao, sono Helpix! 👋"),
             tr("Ti porto a fare un giro veloce: un minuto e sai dove mettere le mani. Puoi saltarlo quando vuoi, "
                "tanto lo ritrovi in Impostazioni › Guida rapida."), tip=False),
        Step("picker", lambda: win.picker, tr("Chi ti dà una mano oggi?"),
             tr("Da qui scegli l'assistente: ChatGPT, Claude, Gemini, Copilot o DeepSeek con il tuo account, oppure "
                "un agente nel terminale (Claude Code, Codex, Gemini CLI). Se un'IA si incarta, dallo stesso menu "
                "passi il lavoro a un'altra senza ricominciare da capo.")),
        Step("model", lambda: win.model_btn, tr("Cervello e impegno"),
             tr("Il modello e quanto deve pensarci su (effort). Più effort vuol dire risposte più ragionate ma più "
                "lente: per le domande al volo il minimo va benissimo.")),
        Step("area", lambda: win.hsplit, tr("Il posto dove si chiacchiera"), area_text, tip=False),
        Step("shot", lambda: win.shot, tr("Una foto vale mille log"),
             tr("Fai uno screenshot dell'errore e finisce dritto nella casella della chat, senza passare dagli "
                "appunti. Dalla freccetta: una finestra, lo schermo intero o un'area dopo 3 secondi (per i menu che "
                "spariscono appena muovi il mouse).")),
        Step("diag", lambda: win.btn_diag, tr("Diagnosi lampo"),
             tr("Un clic e raccolgo disco, memoria, rete, servizi in errore e gli ultimi errori del log. Prima di "
                "incollare ti faccio vedere tutto: togli quello che non vuoi condividere.")),
        Step("command", None, tr("Comandi senza fatica"),
             tr("Quando copi un comando proposto dall'IA, in basso compare la barra «Hai copiato un comando»: premi "
                "Esegui e l'output torna nella chat da solo. Se il comando è di quelli pericolosi (Remove-Item "
                "-Recurse, diskpart, reg delete…) te lo dico prima, e per i permessi di amministratore è Windows a "
                "chiedertelo, mai io.") if IS_WINDOWS else
             tr("Quando copi un comando proposto dall'IA, in basso compare la barra «Hai copiato un comando»: premi "
                "Esegui e l'output torna nella chat da solo. Se il comando è di quelli pericolosi (rm -r, dd, "
                "mkfs…) te lo dico prima, e sudo chiede la password al sistema, mai a me.")),
        Step("privacy", lambda: win.btn_privacy, tr("Lo scudo della privacy"),
             tr("Acceso, oscura password, token, email, IP pubblici, nome utente e nome del PC prima che arrivino "
                "nella chat. Comodissimo sui PC dei clienti. Gli screenshot però non li vede: occhio a cosa "
                "inquadri.")),
        Step("tech", lambda: win.btn_tech, tr("Modalità smanettone"),
             tr("Terminale integrato e albero delle cartelle, per chi vuole vedere cosa succede sotto il cofano. "
                "Si apre e si chiude anche con Ctrl+`.")),
        Step("theme", lambda: win.btn_theme, tr("Giorno o notte?"),
             tr("Tema chiaro o scuro, a seconda dell'umore (e dell'ora). Gli occhi ringraziano.")),
        Step("gear", lambda: win.btn_gear, tr("Il cassetto degli attrezzi"),
             tr("Chiavi API, sicurezza (blocco con la password del PC o l'impronta, export cifrato), dipendenze di "
                "sistema, lingua, aspetto e finestra rapida. E sì, anche questo giro guidato.")),
        Step("quick", None, tr("La finestra rapida"),
             tr("Premi Ctrl+Alt+H da qualsiasi programma: in basso a destra compare un riquadrino per le domande "
                "al volo, con la risposta lì dentro. Ripremi e sparisce. Il lucchetto lo tiene al suo posto.")),
        Step("handoff", lambda: win.picker, tr("Cambio IA al volo"),
             tr("Messaggi gratis finiti o risposta che gira in tondo? «Continua il task con un'altra IA»: chiedo il "
                "riepilogo a quella di adesso e lo passo alla nuova, screenshot compresi.")),
        Step("tray", None, tr("Sempre a portata di mano"),
             tr("Chiudendo la finestra posso restare nell'area di notifica (lo scegli tu nelle Impostazioni): un clic "
                "sull'icona e torno, e la scorciatoia della finestra rapida resta attiva.")),
        Step("bye", None, tr("Fatto, sei pronto! 🎉"),
             tr("Ora sai tutto quello che serve. Se ti perdi, il giro lo ritrovi in Impostazioni › Guida rapida. "
                "Buona caccia ai problemi!"), tip=False),
    ]



def project_steps(win) -> list[Step]:
    """Giro dei progetti (beta) nella finestra principale."""
    def open_text() -> str:
        engine = getattr(win, "engine", "web")
        if engine == "agent":
            return tr("Da qui crei un progetto nuovo o ne apri uno. Aprendolo, l'agente riparte con lo stato del "
                      "progetto nelle sue istruzioni, e le note vecchie se le legge da solo quando servono.")
        if engine == "api":
            return tr("Da qui crei un progetto nuovo o ne apri uno. Aprendolo, lo stato del progetto va all'IA "
                      "insieme a ogni richiesta: lei sa sempre dove eravate rimasti.")
        return tr("Da qui crei un progetto nuovo o ne apri uno. Aprendolo, ti apro una chat nuova e ci incollo lo "
                  "stato del progetto: tu controlli e premi Invio. Funziona con qualsiasi IA, anche cambiandola.")

    btn = lambda: win.project_btn  # noqa: E731
    return [
        Step("p_welcome", None, tr("Progetti e vault 🗂️"),
             tr("Un progetto è un lavoro che va avanti per giorni: un cliente, un PC, un'idea tua. Io tengo un "
                "riassunto breve di dove sei arrivato e lo do all'IA ogni volta che riparti, così non devi rispiegare "
                "niente e spendi meno messaggi e token. Ti faccio vedere come in un minuto."), tip=False),
        Step("p_picker", btn, tr("Il selettore Progetto"), open_text),
        Step("p_save", btn, tr("Salva progetto"),
             tr("Quando hai fatto progressi: Progetto › Salva progetto. Chiedo all'IA solo cosa è cambiato e una nota "
                "sulla sessione, poi ti mostro l'anteprima: correggi quello che vuoi e premi Salva. Le versioni "
                "precedenti restano, e se il riassunto diventa lungo c'è «Compatta il progetto».")),
        Step("p_note", None, tr("Le note su richiesta"),
             tr("Le note vecchie non le mando sempre: pesano. Se all'IA ne serve una scrive «HELPIX-NOTA: titolo»; tu "
                "copi quella riga e compare la barra «L'IA chiede la nota…»: premi Incolla nella chat e gliela passo.")),
        Step("p_private", None, tr("«Solo per me»"),
             tr("Nel riassunto c'è una sezione tutta tua, «Solo per me»: appunti, idee, cose dei clienti che non vuoi "
                "far uscire. Non la mando mai a nessuna IA, e l'IA non può modificarla.")),
        Step("p_auto", None, tr("Bozze e promemoria"),
             tr("Ogni 10 minuti salvo da solo una bozza della sessione (comandi, output, diagnosi): niente IA, zero "
                "token. E quando cambi progetto, apri un task nuovo, passi a un'altra IA o chiudi, ti chiedo se vuoi "
                "salvare. Mai niente di nascosto: aggiorno il progetto solo quando confermi.")),
        Step("p_vault", btn, tr("Il vault"),
             tr("Tutti i progetti stanno nel vault: una cartella di file Markdown, leggibile anche con un editor o con "
                "Obsidian. Da Progetto › Apri il vault vedi progetti, note e versioni, e quanto pesa quello che va "
                "all'IA. Lì dentro c'è un altro mini-giro.")),
        Step("p_lock", btn, tr("Il lucchetto (facoltativo)"),
             tr("In Progetto › Impostazioni dei progetti puoi cifrare il vault: una password, più 8 codici usa e getta "
                "per rientrare se la dimentichi (e, se vuoi, un file di recupero). Si blocca insieme a me. Conserva "
                "bene codici e password: se li perdi tutti, nessuno può recuperare i dati, nemmeno io.")),
        Step("p_bye", None, tr("Pronto a partire! 🎉"),
             tr("Crea il primo progetto dal selettore e prova Salva progetto dopo un po' di lavoro. È una funzione in "
                "beta: tieni una copia dei dati importanti. Questa guida la ritrovi in Progetto › Guida ai "
                "progetti."), tip=False),
    ]


def vault_steps(panel) -> list[Step]:
    """Giro del pannello Vault."""
    return [
        Step("v_welcome", None, tr("Benvenuto nel vault 🗃️"),
             tr("Qui ci sono tutti i tuoi progetti, con lo stato attuale, le note e le versioni. Facciamo un giro "
                "veloce dei comandi."), tip=False),
        Step("v_tree", lambda: panel.tree, tr("Progetti e note"),
             tr("Ogni progetto ha PROJECT.md (lo stato attuale, quello che va all'IA), INDEX.md (l'elenco delle note), "
                "le note di ogni salvataggio, i file di dettaglio, le bozze delle sessioni e le versioni precedenti.")),
        Step("v_search", lambda: panel.search, tr("Cerca"),
             tr("Scrivi una parola e trovi le righe che la contengono in tutti i progetti: maiuscole e accenti non "
                "contano.")),
        Step("v_meter", lambda: panel.meter_box, tr("Quanto pesa"),
             tr("Il peso di PROJECT.md in token. Sotto i 1000 va tutto bene; oltre, conviene «Compatta il progetto», "
                "così ogni chat nuova resta leggera.")),
        Step("v_seg", lambda: panel.seg, tr("Leggi, modifica, grafo"),
             tr("Leggi mostra la nota formattata, con i link [[ ]] cliccabili. Modifica apre il testo: puoi correggere "
                "a mano e salvare; per PROJECT.md la versione precedente resta tra le versioni. Grafo è la mappa "
                "delle decisioni: accanto a ogni sessione quelle prese lì, le superate con la freccia verso quella "
                "nuova, in fondo lo stato e i prossimi passi. Un clic apre la nota da cui viene.")),
        Step("v_more", lambda: panel.btn_more, tr("Altre azioni"),
             tr("Rinomina il progetto, elimina una nota, un file o l'intero progetto (anche con il tasto destro "
                "nell'albero). Quello che elimini va nel Cestino in fondo all'albero: da lì lo ripristini o lo elimini "
                "definitivamente.")),
        Step("v_resume", lambda: panel.btn_resume, tr("Riprendi"),
             tr("Apre una chat nuova nell'assistente attivo con lo stato del progetto: il modo più veloce per "
                "ripartire.")),
        Step("v_ctx", lambda: panel.ctx_card, tr("Cosa va all'IA"),
             tr("Esattamente quello che mando a ogni chat nuova: PROJECT.md senza «Solo per me» e le ultime righe "
                "dell'indice. Tutto il resto resta qui finché non serve.")),
        Step("v_recent", lambda: panel.recent, tr("Note e collegamenti"),
             tr("Le note più recenti: «nel contesto» sono quelle elencate all'IA, «archivio» le altre. Sopra, «Citata "
                "da» mostra quali note puntano a quella aperta.")),
        Step("v_lock", lambda: panel.lock_card, tr("Il lucchetto"),
             tr("Se il vault è cifrato, da qui lo blocchi subito; si blocca anche insieme a Helpix. Se non è cifrato, "
                "sono normali file Markdown nella tua cartella.")),
        Step("v_guide", lambda: panel.btn_guide, tr("Beta e guida"),
             tr("È una funzione in prova: «Esporta in chiaro» ti fa una copia leggibile, «Segnala un problema» apre "
                "la pagina delle segnalazioni, «Guida» rifà questo giro.")),
        Step("v_bye", None, tr("Tutto qui! ✨"),
             tr("Buon lavoro con i tuoi progetti."), tip=False),
    ]


class Bubble(QWidget):
    """Nuvoletta con la punta verso il pulsante; il contenuto è un normale layout."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedWidth(WIDTH)
        self.tail_side: str | None = None   # "top", "bottom" o None
        self.tail_x = WIDTH // 2
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        self.counter = QLabel()
        self.counter.setObjectName("secondary")
        self.title = QLabel()
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 2)
        f.setBold(True)
        self.title.setFont(f)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.counter)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addSpacing(4)
        self.show_tips = QCheckBox(tr("Mostra i suggerimenti all'avvio"))
        lay.addWidget(self.show_tips)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.skip = QPushButton(tr("Salta il giro"))
        self.skip.setFlat(True)
        self.skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back = QPushButton(tr("Indietro"))
        self.next = QPushButton(tr("Avanti"))
        self.next.setObjectName("primary")
        self.next.setDefault(True)
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.next)
        lay.addLayout(row)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)
        self.set_tail(None)

    def set_tail(self, side: str | None, x: int | None = None):
        self.tail_side = side
        if x is not None:
            self.tail_x = max(RADIUS + TAIL, min(WIDTH - RADIUS - TAIL, x))
        top = 16 + (TAIL if side == "top" else 0)
        bottom = 14 + (TAIL if side == "bottom" else 0)
        self.layout().setContentsMargins(18, top, 18, bottom)
        self.update()

    def shape_path(self) -> QPainterPath:
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.tail_side == "top":
            r.setTop(r.top() + TAIL)
        elif self.tail_side == "bottom":
            r.setBottom(r.bottom() - TAIL)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        if self.tail_side:
            x = float(self.tail_x)
            tri = QPainterPath()
            if self.tail_side == "top":
                tri.moveTo(x - TAIL, r.top() + 1)
                tri.lineTo(x, r.top() - TAIL)
                tri.lineTo(x + TAIL, r.top() + 1)
            else:
                tri.moveTo(x - TAIL, r.bottom() - 1)
                tri.lineTo(x, r.bottom() + TAIL)
                tri.lineTo(x + TAIL, r.bottom() - 1)
            tri.closeSubpath()
            path = path.united(tri)
        return path

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        C = theme.C
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(QColor(C["sheet"]))
        p.drawPath(self.shape_path())


class Tour(QWidget):
    """Sovrapposto alla finestra principale. mode="tour" (giro completo) o "tip" (un consiglio)."""

    finished = Signal()

    def __init__(self, win, mode: str = "tour", start_key: str | None = None, steps: list[Step] | None = None,
                 host: QWidget | None = None, done_key: str = "tour_done"):
        """`steps`, `host` e `done_key` servono ai giri di una sola funzione (progetti, pannello Vault): altri
        passi, sopra un'altra finestra, con la loro impostazione «già visto»."""
        host = host or win.centralWidget() or win
        super().__init__(host)
        self.win, self.host, self.mode = win, host, mode
        self.done_key = done_key
        self.custom = steps is not None
        all_steps = steps if steps is not None else steps_for(win)
        self.steps = all_steps if mode == "tour" else [s for s in all_steps if s.tip]
        self.index = 0
        if start_key:
            self.index = next((i for i, s in enumerate(self.steps) if s.key == start_key), 0)
        self.hole = QRectF()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_hole)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.bubble = Bubble(self)
        self.bubble.show_tips.setChecked(bool(win.settings.get("show_tips", True)))
        self.bubble.show_tips.toggled.connect(lambda on: win.settings.set("show_tips", bool(on)))
        self.bubble.show_tips.setVisible(not self.custom)  # la spunta riguarda i consigli di Helpix
        self.bubble.next.clicked.connect(self.forward)
        self.bubble.back.clicked.connect(self.backward)
        self.bubble.skip.clicked.connect(lambda: self.close_tour())
        if mode == "tip":
            self.bubble.skip.setText(tr("Giro completo"))
            self.bubble.skip.clicked.disconnect()
            self.bubble.skip.clicked.connect(self._full_tour)
            self.bubble.back.setText(tr("Chiudi"))
            self.bubble.back.clicked.disconnect()
            self.bubble.back.clicked.connect(lambda: self.close_tour())
            self.bubble.next.setText(tr("Altro consiglio"))
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        self._show_step(animate=False)
        self.bubble.next.setFocus()

    # ------------------------------------------------------------ navigazione
    @property
    def step(self) -> Step:
        return self.steps[self.index]

    def _target(self, step: Step) -> QWidget | None:
        if step.target is None:
            return None
        try:
            w = step.target()
        except AttributeError:
            return None
        return w if w is not None and w.isVisible() else None

    def _usable(self, i: int) -> bool:
        s = self.steps[i]
        return s.target is None or self._target(s) is not None

    def forward(self):
        if self.mode == "tip":
            self.index = (self.index + 1) % len(self.steps)
            for _ in range(len(self.steps)):
                if self._usable(self.index):
                    break
                self.index = (self.index + 1) % len(self.steps)
            self.win.settings.set("tip_index", self.index)
            self._show_step()
            return
        i = self.index + 1
        while i < len(self.steps) and not self._usable(i):
            i += 1
        if i >= len(self.steps):
            self.close_tour()
            return
        self.index = i
        self._show_step()

    def backward(self):
        i = self.index - 1
        while i >= 0 and not self._usable(i):
            i -= 1
        if i >= 0:
            self.index = i
            self._show_step()

    def close_tour(self, mark_done: bool = True):
        if self.mode == "tour" and mark_done:
            self.win.settings.set(self.done_key, True)
        self.host.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        self.finished.emit()

    def _full_tour(self):
        self.close_tour()
        self.win.start_tour()

    # ------------------------------------------------------------ disegno e posizione
    def _show_step(self, animate: bool = True):
        if not self._usable(self.index):
            self.forward()
            return
        s = self.step
        b = self.bubble
        if self.mode == "tour":
            b.counter.setText(tr("{n} di {total}").format(n=self.index + 1, total=len(self.steps)))
            b.back.setEnabled(self.index > 0)
            b.next.setText(tr("Fine") if self.index == len(self.steps) - 1 else tr("Avanti"))
            b.skip.setVisible(self.index < len(self.steps) - 1)
        else:
            b.counter.setText(tr("Lo sapevi?"))
        b.title.setText(s.title)
        b.text.setText(s.body())
        b.adjustSize()
        target = self._target(s)
        new = QRectF()
        if target is not None:
            top_left = target.mapTo(self.host, QPoint(0, 0))
            r = QRect(top_left, target.size())
            new = QRectF(r.adjusted(-HALO, -HALO, HALO, HALO)).intersected(QRectF(self.rect()).adjusted(4, 4, -4, -4))
        if animate and not self.hole.isNull() and not new.isNull():
            self._anim.stop()
            self._anim.setStartValue(self.hole)
            self._anim.setEndValue(new)
            self._anim.start()
        else:
            self._set_hole(new)
        self._place_bubble(new)

    def _set_hole(self, rect):
        self.hole = QRectF(rect)
        self._update_mask()
        self.update()

    def _place_bubble(self, hole: QRectF):
        b = self.bubble
        W, H = self.width(), self.height()
        bw, bh = b.width(), b.sizeHint().height() + TAIL
        if hole.isNull():
            b.set_tail(None)
            b.resize(bw, b.sizeHint().height())
            b.move(max(12, (W - bw) // 2), max(12, (H - b.height()) // 2))
        elif hole.height() > H * 0.45:
            # zona grande (la chat): nuvoletta dentro, in alto al centro, senza punta
            b.set_tail(None)
            b.resize(bw, b.sizeHint().height())
            x = max(12, min(W - bw - 12, int(hole.center().x()) - bw // 2))
            b.move(x, int(hole.top()) + 36)
        else:
            cx = int(hole.center().x())
            x = max(12, min(W - bw - 12, cx - bw // 2))
            below = H - hole.bottom() - 8
            if below >= bh or below >= hole.top():
                b.set_tail("top", cx - x)
                b.resize(bw, b.sizeHint().height())
                y = int(hole.bottom()) + 4
            else:
                b.set_tail("bottom", cx - x)
                b.resize(bw, b.sizeHint().height())
                y = int(hole.top()) - b.height() - 4
            b.move(x, max(8, min(H - b.height() - 8, y)))
        b.raise_()
        self._update_mask()

    def _update_mask(self):
        if self.mode == "tour":
            self.clearMask()
            return
        # consiglio: solo nuvoletta e alone ricevono clic, il resto della finestra resta usabile
        region = QRegion(self.bubble.geometry().adjusted(-24, -24, 24, 34))
        if not self.hole.isNull():
            ring = QRegion(self.hole.toRect().adjusted(-4, -4, 4, 4))
            region = region.united(ring.subtracted(QRegion(self.hole.toRect().adjusted(3, 3, -3, -3))))
        self.setMask(region)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        C = theme.C
        if self.mode == "tour":
            dim = QPainterPath()
            from .frameless import INSET, RADIUS as WIN_RADIUS, RoundedCentral
            if isinstance(self.host, RoundedCentral):  # finestra con angoli arrotondati: l'ombra li segue
                dim.addRoundedRect(QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET), WIN_RADIUS, WIN_RADIUS)
            else:
                dim.addRect(QRectF(self.rect()))
            if not self.hole.isNull():
                hole = QPainterPath()
                hole.addRoundedRect(self.hole, 10, 10)
                dim = dim.subtracted(hole)
            p.fillPath(dim, QColor(0, 0, 0, 120 if theme.is_dark() else 95))
        if not self.hole.isNull():
            accent = QColor(C["accentBg"])
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.hole, 10, 10)

    # ------------------------------------------------------------ eventi
    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self._show_step(animate=False)
        return False

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            self.close_tour()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.forward()
        elif key == Qt.Key.Key_Left and self.mode == "tour":
            self.backward()
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        ev.accept()  # nel giro completo i clic fuori dalla nuvoletta non passano sotto

