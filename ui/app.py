"""Interfaccia Streamlit.

Struttura, che ricalca l'ordine in cui si lavora davvero:

  1 Sorgenti     cosa c'e' in INPUT e cosa contiene ciascun file. Sola lettura.
  2 Confronto    un file alla volta: si provano i modelli su spezzoni brevi.
  3 Lavorazione  si scelgono i file, si conferma il modello, si avvia.

La selezione sta nella terza scheda e non nella prima: mescolare "guardo cosa
ho" con "scelgo cosa elaborare" rendeva ambiguo cosa succedesse spuntando un
file e poi provandone un altro.

Altri principi:
  - la prima schermata compare subito. L'elenco usa i soli metadati; l'analisi
    completa parte su richiesta e viene conservata su disco.
  - nessun impegno di tempo senza una stima mostrata prima.
  - i risultati video NON si guardano qui: a scala diversa da 1:1 un
    riproduttore in una pagina web nasconde gli artefatti da giudicare. Si
    aprono in video-compare con un clic. A schermo solo i ritagli 1:1.
  - questo file non contiene logica di dominio: chiama il motore, che
    funziona identico da riga di comando.
"""

from __future__ import annotations

import base64
import html
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Due radici distinte, e vanno tenute separate: `CODICE` è dove sta questo
# file (quindi il lanciatore, i sorgenti, i binari), `ROOT` è dove stanno i
# DATI. Coincidono quasi sempre, ma il lanciatore documenta di rispettare un
# ANIMEUP_ROOT impostato dall'utente: in quel caso cercare `animeup` sotto la
# radice dati significa non trovarlo, e l'interfaccia diceva "Avviata" mentre
# la shell rispondeva 127.
CODICE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("ANIMEUP_ROOT", CODICE))
sys.path.insert(0, str(CODICE / "src"))

import streamlit as st  # noqa: E402

from animeup import __version__, su_disco  # noqa: E402
from animeup import (  # noqa: E402
    aggiornamenti, i18n, library, monitor, preview, primo_avvio, taratura)
from animeup.i18n import t, tn  # noqa: E402
from animeup.models import (  # noqa: E402
    ALTEZZA_INCERTA, CATALOG, CLEAN_SOURCE_MIN_HEIGHT, altezza_minima,
    recommend)
from animeup.paths import PATHS, gb_liberi  # noqa: E402
from animeup.ffmpeg import FFmpegError  # noqa: E402
from animeup.plan import PlanError, build_plan  # noqa: E402
from animeup.probe import FieldMode  # noqa: E402
from animeup.report import (  # noqa: E402
    fps_str, hms, quando_finisce, stima_hm)


def _bolla(testo: str) -> str:
    """Il fumetto d'aiuto per il markup nostro, come ELEMENTO VERO.

    Era uno pseudo-elemento (`.au-perche::after` con `content: attr(...)`), ed
    e' stata la causa di meta' dei suggerimenti finiti fuori posto: il
    centraggio automatico del motore funzionava sugli elementi veri e non
    sugli pseudo-elementi, dove la posizione verticale si risolveva ma
    l'orizzontale cadeva a zero — il fumetto incollato al bordo sinistro
    della finestra mentre la sua icona stava a 1164px. Da li' erano nate una
    centratura a mano e una catena di eccezioni per la sidebar e per la
    Taratura, che si scavalcavano a vicenda.

    Ora i due meccanismi sono uno solo: questo e' lo stesso `.au-bolla` che la
    (i) usa da sempre e che non ha mai sbagliato un fumetto. Meno CSS, e
    soprattutto una regola sola da capire quando qualcosa si sposta.
    """
    return (f"<span class='au-bolla'><span class='au-bolla-riga'>"
            f"{esc(testo)}</span></span>")


def _icona_aiuto(testo: str, predefinito: str = "") -> str:
    """Il "?" con il fumetto NOSTRO, da mettere accanto a un'etichetta.

    Prende il posto degli `help=` di Streamlit, che sono disegnati da BaseWeb
    e piazzati da un popover in JavaScript: niente punta, mai centrati
    sull'icona, e di quella posizione dal CSS non si arriva a niente (visto
    dall'utente il 2026-08-10). Il disegno e' lo stesso — cerchio, gancio e
    punto, tratto da 2 — copiato dal DOM di Streamlit perche' il cambio non
    si noti.

    `predefinito` va in coda, in grigio: e' un dato di servizio, non parte
    della spiegazione, e distinguerlo col colore evita di doverlo introdurre
    con una frase.
    """
    coda = (f"<span class='au-bolla-nota'>"
            f"{esc(t('comune.predefinito', valore=predefinito))}</span>"
            if predefinito else "")
    return ("<span class='au-info' tabindex='0'>"
            "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round' aria-hidden='true'>"
            "<circle cx='12' cy='12' r='10'></circle>"
            "<path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path>"
            "<line x1='12' y1='17' x2='12.01' y2='17'></line>"
            "</svg>"
            f"<span class='au-bolla'>"
            f"<span class='au-bolla-riga'>{esc(testo)}</span>{coda}</span></span>")


def _etichetta_sb(testo: str, aiuto: str, valore: str = "",
                  predefinito: str = "") -> None:
    """L'etichetta di un controllo della sidebar, disegnata da noi.

    Con l'etichetta nativa il valore andava messo in un `content` di CSS
    (una regola per controllo, rigenerata a ogni giro) perche' il "?" viveva
    dentro l'etichetta di Streamlit e collassarla lo faceva sparire. Ora che
    il suggerimento e' nostro, l'etichetta puo' essere un pezzo di markup
    normale e il valore un semplice `span`: una cosa in meno da tenere in
    piedi, e il fumetto e' quello dell'app.
    """
    val = f"<span class='au-sb-val'>{esc(valore)}</span>" if valore else ""
    st.sidebar.markdown(
        f"<div class='au-sb-eti'>{esc(testo)}"
        f"{_icona_aiuto(aiuto, predefinito)}{val}</div>",
        unsafe_allow_html=True)


def _aiuto_a_destra(testo: str, predefinito: str = "") -> None:
    """L'aiuto di un interruttore, in fondo alla sua riga.

    L'etichetta di un `toggle` vive DENTRO il componente, insieme
    all'interruttore e alla sua zona cliccabile: portarla fuori
    significherebbe rifare il controllo. Qui non si rompe niente — al nativo
    si toglie solo il suo `help=`, e la nostra icona si appoggia sopra, a
    filo destro della riga, fuori dall'etichetta (che finisce ben prima:
    misurata 193px su 256 disponibili). Il click sull'icona non arriva
    all'interruttore perche' l'icona sta sopra.
    """
    st.markdown(f"<div class='au-sb-aiuto'>{_icona_aiuto(testo, predefinito)}</div>",
                unsafe_allow_html=True)


def _icona_info(titolo: str, righe: list[str], nota: str = "") -> str:
    """Il fumetto della (i): informazione IN PIÙ, non aiuto necessario.

    Distinta dalla (?) di proposito: quella risponde a una domanda che chi
    legge potrebbe farsi ("perché questo file è sconsigliato?"), questa
    aggiunge dettaglio a un numero che si capisce già da solo. Stesso
    disegno del suggerimento nativo — cerchio, asta e punto — perché il
    gesto sia lo stesso.

    Il fumetto è un elemento VERO, non un `content: attr(...)` come la (?):
    serve un titolo in grassetto e delle righe separate, e un pseudo-elemento
    porta un blocco di testo solo, tutto dello stesso peso. Tre frasi di
    fila su una riga sola non si leggono, e mischiare due informazioni
    diverse nello stesso fumetto è peggio che non darle.
    """
    corpo = "".join(f"<span class='au-bolla-riga'>{esc(r)}</span>"
                    for r in righe)
    coda = (f"<span class='au-bolla-nota'>{esc(nota)}</span>" if nota else "")
    return ("<span class='au-info' tabindex='0'>"
            "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round' aria-hidden='true'>"
            "<circle cx='12' cy='12' r='10'></circle>"
            "<line x1='12' y1='16' x2='12' y2='11'></line>"
            "<line x1='12' y1='8' x2='12.01' y2='8'></line>"
            "</svg>"
            f"<span class='au-bolla'>"
            f"<span class='au-bolla-tit'>{esc(titolo)}</span>{corpo}{coda}"
            "</span></span>")


def _nota_taratura() -> str:
    """Con che titolo parlano le stime: misurate qui, o di fabbrica.

    La differenza non è pignoleria: i numeri di fabbrica vengono da UN Mac
    preciso, e su un chip diverso sbagliano tutti dello stesso fattore.
    Chi legge una stima deve sapere se è casa sua o casa d'altri.
    """
    voce = taratura.carica()
    if voce:
        import datetime
        quando = datetime.datetime.fromtimestamp(voce["quando"])
        return t("lav.nota_tarata", data=quando.strftime(t("lav.fmt_giorno")))
    return t("lav.nota_fabbrica")

st.set_page_config(page_title="AnimeUp", page_icon="▲", layout="wide")

# Senza il numero nell'etichetta: il cerchio numerato lo genera il CSS con un
# contatore, così il numero è un elemento a se' e non tre caratteri dentro
# una stringa che non si possono impaginare.
SEZIONI = ["Sorgenti", "Confronto", "Lavorazione"]

# Dalla risoluzione più bassa alla più alta, nello stesso verso in cui sono
# ordinati i modelli: chi legge segue una scala sola invece di saltare avanti
# e indietro fra le fasce.
# Una funzione e non una costante: i testi si leggono nella lingua attiva al
# momento del disegno, e la lingua si cambia mentre l'app gira.
# L'altezza d'uscita serve alla fascia di mezzo: il denoise leggero esiste
# solo a x2, e la regola lo suggeriva anche dove non arriva al bersaglio (a
# 1080p, da 380 a 539 righe), contraddicendo la scheda «non arriva» lì sopra.
# Con «forza» acceso il piano lo accetta lo stesso, e la regola torna piena.
def perche_generale(altezza_uscita: int, forza: bool = False
                    ) -> tuple[tuple[str, str, str, str], ...]:
    minimo = altezza_minima("cugan-denoise", altezza_uscita)
    if forza or minimo <= ALTEZZA_INCERTA:
        mezzo = ("giallo", t("conf.pg.mezzo_modello"), t("conf.pg.mezzo_testo"))
    elif minimo < CLEAN_SOURCE_MIN_HEIGHT:
        mezzo = ("giallo", t("conf.pg.mezzo_modello_da", minimo=minimo),
                 t("conf.pg.mezzo_testo_da", minimo=minimo,
                   altezza=altezza_uscita))
    else:
        mezzo = ("verde", "animevideov3",
                 t("conf.pg.mezzo_testo_mai", altezza=altezza_uscita))
    return (
        (t("conf.pg.sotto_fascia", altezza=ALTEZZA_INCERTA), "verde",
         "animevideov3", t("conf.pg.sotto_testo")),
        (f"{ALTEZZA_INCERTA}p–{CLEAN_SOURCE_MIN_HEIGHT}p", *mezzo),
        (t("conf.pg.sopra_fascia", altezza=CLEAN_SOURCE_MIN_HEIGHT), "verde",
         "CUGAN no-denoise", t("conf.pg.sopra_testo")),
    )

# I colori NON stanno qui: stanno in `.streamlit/config.toml` (i token di
# Streamlit) e nel blocco `:root` del CSS più sotto (quelli che Streamlit non
# ha). Questi nomi puntano la', così esiste un posto solo da cambiare — la
# lezione della volta in cui un cambio di tema ha richiesto venti modifiche.
# Riferimento visivo: `design/animeup-mockup-v2.html`.
BORDO      = "var(--borderColor)"
BORDO_VIVO = "var(--borderStrong)"
FONDO_2    = "var(--surfaceHover)"
TESTO      = "var(--textPrimary)"
TESTO_2    = "var(--textSecondary)"
TESTO_3    = "var(--textTertiary)"
GIALLO     = "var(--yellowText)"
VERDE      = "var(--greenText)"
CIANO      = "var(--primary)"

STYLE = f"""
<style>
  /* NIENTE dissolvenza sugli elementi "vecchi". Streamlit, mentre aspetta
     il contenuto nuovo di una riesecuzione, marca ogni contenitore con
     `data-stale="true"` e gli cambia classe: quella classe accende una
     transizione sull'opacita' (ritardo 0.5s, durata 1s) per sbiadire cio'
     che sta per essere sostituito.
     Sulla scheda Lavorazione il riquadro si riesegue ogni 5 secondi finche'
     una lavorazione e' viva, e quel ciclo parte e si annulla in continuazione
     su circa 1.900 contenitori: si vede come un lampo che scorre dall'alto
     verso il basso, e sembra che la pagina stia per crollare (segnalato
     dall'utente). Misurato: in 42 secondi zero nodi aggiunti o rimossi —
     il DOM non viene ricostruito — e 7.585 cambi di attributo, tutti
     `class` e `data-stale` sui contenitori.
     Qui la dissolvenza si spegne: l'aggiornamento diventa istantaneo e
     invisibile. Non cambia cosa viene ridisegnato, solo come appare il
     passaggio. */
     SOLO il contenitore, MAI i suoi figli. Streamlit applica la dissolvenza
     sull'elemento stesso che porta `data-stale` e su nient'altro: nel suo
     codice e' `{{opacity: tema.stale, transition: opacity 1s ease-in 0.5s}}`
     sul contenitore, e l'attributo `data-stale` sta sullo stesso nodo.
     La prima versione di questa regola scendeva sui discendenti con
     `[data-stale="true"] *` e imponeva `opacity: 1` a tutti: ma i fumetti
     dei suggerimenti (`.au-bolla`) stanno a riposo proprio a `opacity: 0` e
     si accendono solo al passaggio del mouse, quindi ogni riesecuzione li
     mostrava tutti insieme per una frazione di secondo. Al posto del lampo
     sugli elementi era arrivato un albero di Natale (detto dall'utente, e
     aveva ragione). Regola: qui si spegne una dissolvenza, non si decide
     cosa e' visibile - la visibilita' e' affare di chi possiede l'elemento. */
  [data-stale="true"] {{ transition: none !important; opacity: 1 !important; }}

  /* I token che Streamlit non conosce. Quelli che conosce stanno nel
     config.toml e non vanno duplicati qui: se un colore esiste come chiave di
     tema, si usa quella. */
  /* Due righe che valgono più di venti ritocchi ai singoli testi. Streamlit
     lascia il rendering predefinito (`auto`, cioè subpixel): su macOS
     ispessisce i caratteri e lascia una frangia colorata sui bordi, ed è il
     motivo per cui la stessa Inter alla stessa misura sembrava più grezza
     che nel mockup. E l'interlinea di Streamlit è 1.6, quella del mockup
     1.5: 22.4px contro 21 su ogni riga di testo. */
  html, body, [class*="st-"], .stMarkdown, input, button, select, textarea {{
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale; }}
  body, .stMarkdown, [data-testid="stSidebar"] {{ line-height: 1.5; }}

  :root {{
    --primary:        #2AC9DE;
    --primaryHover:   #55D8EA;
    --primaryBg:      rgba(42,201,222,.10);
    --primaryEdge:    rgba(42,201,222,.45);
    --onPrimary:      #08262B;
    --surface:        #17191C;
    --surfaceHover:   #1C1F23;
    --insetBackground:#131518;
    --borderColor:    #26292E;
    --borderStrong:   #33373D;
    --idleEdge:       #3A3F46;
    --textPrimary:    #E8EAED;
    --textSecondary:  #9BA1A9;
    --textTertiary:   #686E76;
    --yellow:         #F2B84B;
    --yellowBg:       #2A2110;
    --yellowText:     #F5CB78;
    --green:          #45D483;
    --greenBg:        #10251A;
    --greenText:      #7FE3AC;
    --red:            #F26D6D;
    --redBg:          #2A1414;
    --redText:        #F59B9B;
    --blue:           #4DA3FF;
    --blueBg:         #101C2B;
    --blueText:       #8CC2FF;
    --grayBg:         #1C1F23;
    --grayText:       #B7BCC3;
    --mono:           "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
    /* La font dell'interfaccia, dichiarata: serve dove un contenitore
       impone il monospazio e un pezzo di testo deve tornare normale
       (i fumetti dentro la cella della stima). */
    --font:           Inter, "Source Sans", sans-serif;
  }}
  /* 1.6rem non bastavano: la barra di Streamlit copriva la cima del
     titolo, che risultava tagliato a metà altezza. */
  /* 4rem in fondo e non 1: scorrendo fino in basso, Sorgenti e Confronto
     finivano a filo della finestra e sembravano tagliati — «come se la
     pagina fosse croppata» (detto dall'utente). Serve un po' di vuoto sotto
     l'ultima riga, come quello che nella Lavorazione lascia la fascia fissa.
     La Lavorazione ha una regola sua piu' sotto (9rem), perche' li' il vuoto
     deve fare spazio anche alla fascia. */
  .block-container {{ padding-top: 3.4rem; padding-bottom: 4rem; max-width: 1400px; }}
  /* Marchio e sottotitolo su una riga sola, separati da una barretta: due
     righe impilate per tre parole occupavano l'altezza di un titolo di
     sezione senza esserlo. */
  .au-marchio {{ display: flex; align-items: center; gap: 11px;
                margin-bottom: 22px; }}
  .au-marchio svg {{ display: block; flex: 0 0 auto; }}
  .au-title {{ font-size: 19px; font-weight: 600; letter-spacing: -.02em;
              color: {TESTO}; }}
  .au-title b {{ color: var(--primary); font-weight: 600; }}
  .au-sub {{ color: {TESTO_3}; font-size: 12px; margin-left: 2px;
            padding-left: 13px; border-left: 1px solid {BORDO}; }}

  /* Lo stepper: il numero nel cerchio è un contatore CSS, non testo
     dell'etichetta. Streamlit non accetta markup dentro l'etichetta di un
     controllo, ma un `::before` con `counter()` non è markup — è la stessa
     numerazione che si otterrebbe a mano, senza toccare il valore che poi
     torna indietro come stato. */
  /* `[data-testid="stButtonGroup"]` e non `[data-baseweb="button-group"]`:
     quest'ultimo in 1.61 non esiste più e il selettore non agganciava nulla
     (verificato nel DOM: il contenitore è stButtonGroup, i figli hanno
     `role="radio"` e `aria-checked`). */
  .st-key-fasi [data-testid="stButtonGroup"] {{ counter-reset: fase; gap: 8px; }}
  .st-key-fasi [data-testid="stButtonGroup"] > div {{ display: flex; gap: 8px; }}
  .st-key-fasi [data-testid="stButtonGroup"] button {{
      counter-increment: fase;
      display: inline-flex; align-items: center; gap: 10px;
      background: var(--surface) !important;
      border: 1px solid {BORDO} !important;
      border-radius: 8px !important;
      /* `height: auto` o la spaziatura non ha effetto: Streamlit fissa
         `height` e `min-height` a 28px, quindi i 12px sopra e sotto non
         allargavano niente e le schede restavano schiacciate. */
      height: auto !important; min-height: 0 !important;
      padding: 12px 22px !important; }}
  .st-key-fasi [data-testid="stButtonGroup"] button p {{
      font-size: 14px; color: {TESTO_2}; }}
  .st-key-fasi [data-testid="stButtonGroup"] button:hover p {{ color: {TESTO}; }}
  .st-key-fasi [data-testid="stButtonGroup"] button::before {{
      content: counter(fase);
      display: inline-flex; align-items: center; justify-content: center;
      width: 22px; height: 22px; border-radius: 50%;
      /* Cifra e bordo un gradino sopra il terziario: il numero nel cerchio
         era quasi invisibile da spento (visto dall'utente). */
      border: 1px solid #40454C;
      font-family: var(--mono); font-size: 11px; color: {TESTO_2};
      flex: 0 0 auto; }}
  .st-key-fasi [data-testid="stButtonGroup"] button:hover {{
      border-color: {BORDO_VIVO} !important; }}
  /* La scheda attiva: fondo ciano tenue, cerchio pieno con la cifra scura.
     `aria-checked` e non una classe di Streamlit, che cambia a ogni versione. */
  .st-key-fasi [data-testid="stButtonGroup"] button[aria-checked="true"] {{
      background: var(--primaryBg) !important;
      border-color: var(--primaryEdge) !important; }}
  .st-key-fasi [data-testid="stButtonGroup"] button[aria-checked="true"]::before {{
      background: var(--primary); border-color: var(--primary);
      color: var(--onPrimary); font-weight: 600; }}
  .st-key-fasi [data-testid="stButtonGroup"] button[aria-checked="true"] p {{
      color: {TESTO}; font-weight: 600; }}
  /* Il nome NON si tronca mai: l'informazione che serve puo' stare nelle
     ultime lettere (hash, tag del rilascio) e i puntini la mangiavano.
     Se serve, la riga cresce di una riga di testo: il ritmo dell'elenco
     vale meno del nome intero (deciso dall'utente, 2026-08-09).
     `overflow-wrap: anywhere` spezza anche le catene [Tag][Tag][Hash]
     senza spazi. */
  .au-name {{ font-weight: 500; font-size: 14px; line-height: 1.35;
             margin-bottom: .18rem; overflow-wrap: anywhere; }}
  /* Regola ferrea dello spec: numeri, codec, timecode e risoluzioni in
     monospaziato tabulare. Senza `tabular-nums` le cifre ballano da una riga
     all'altra e una colonna di numeri non si legge più come colonna. */
  .au-meta {{ color: {TESTO_2}; font-family: var(--mono); font-size: 11.5px;
             line-height: 1.5; font-variant-numeric: tabular-nums; }}
  .au-cell {{ color: {TESTO}; font-family: var(--mono); font-size: 13px;
             font-variant-numeric: tabular-nums; }}
  /* `nowrap`: con la spaziatura fra lettere "RISOLUZIONE" andava a capo e
     l'intestazione diventava alta il doppio delle altre. */
  .au-eyebrow {{ color: {TESTO_3}; font-size: 10.5px; font-weight: 600;
                letter-spacing: .08em; text-transform: uppercase;
                white-space: nowrap; }}
  /* Le chip erano strette al punto da sembrare testo colorato invece che un
     elemento a se'. Respiro attorno al testo, angolo più morbido e un bordo
     della stessa tinta del fondo: si stacca dalla riga senza gridare. */
  /* Pillola piena e non rettangolo: le chip sono etichette di stato, non
     pulsanti, e la forma lo deve dire prima del colore. Non interattive:
     nessun hover. */
  .au-tag {{ display:inline-flex; align-items:center; gap:4px;
            padding:3px 9px; border-radius:999px;
            font-family: var(--mono); font-size:11px;
            line-height:1.45; white-space: nowrap;
            border:1px solid transparent; }}
  /* Niente puntino nella chip: era un richiamo d'attenzione solo per
     l'elenco dei sorgenti, ma nessun'altra chip dell'app ce l'ha e stonava
     (rimosso su richiesta dell'utente, 2026-08-09). */
  /* La chip in coda alla colonna Analisi: senza margine si appiccicava al
     testo sopra e sbordava sotto il bordo della riga. */
  .au-chip-riga {{ margin-top: .3rem; }}
  .au-ok   {{ background: rgba(69,212,131,.10); border-color: rgba(69,212,131,.25);
             color:{VERDE}; }}
  .au-warn {{ background: rgba(242,184,75,.10); border-color: rgba(242,184,75,.25);
             color:{GIALLO}; }}
  /* "fatta" è BLU, non verde: il verde è già di "consigliato", e due chip
     verdi nella stessa colonna si leggevano come la stessa cosa (detto
     dall'utente). Il blu qui dice "capitolo chiuso". */
  .au-fatta {{ background: var(--blueBg); border-color: rgba(77,163,255,.30);
             color: var(--blueText); }}
  /* In coda: grigio, neutro — il file aspetta il suo turno nella catena. */
  .au-coda {{ background: var(--grayBg); border-color: rgba(138,144,153,.30);
             color: var(--grayText); }}
  .au-dim  {{ background: rgba(138,144,153,.10);border-color: rgba(138,144,153,.25);
             color:{TESTO_2}; }}
  /* Rosso e non ambra: l'ambra dice "guarda", il rosso dice "così non
     parte". Sono due cose diverse e la riga si comporta diversamente. */
  .au-err  {{ background: var(--redBg); border-color: rgba(242,109,109,.35);
             color: var(--redText); }}
  .au-hint {{ color: {TESTO_2}; font-size:13px; line-height:1.55; }}
  /* Salti d'ingresso dei gruppi UGUALI (misurati: ~27px l'uno). Il primo
     gruppo dopo un titolo di sezione partiva 8px indietro (il titolo
     "pesa" meno di un controllo): si compensa solo lui. */
  .au-sgruppo {{ margin: 18px 0 10px; }}
  /* Stesso corpo delle etichette degli slider accanto (12.25px, misurato
     sul DOM: e' il 14px di base per lo 0.875 della sidebar). I margini
     vivono sul CONTENITORE e non qui: il link "Ripeti" si ancora al
     contenitore, e un margine interno lo scentrerebbe. */
  /* Pallino di notifica sulle schede, alla iOS. Il NUMERO non puo' stare
     qui (cambia a ogni giro): lo inietta `_pallini_schede` in un blocco
     di stile suo, con `content`. Qui c'e' solo la forma. */
  .st-key-fasi [role="radio"] {{ position: relative; overflow: visible; }}
  .st-key-fasi [role="radio"]::after {{
      position: absolute; top: -6px; right: -6px;
      min-width: 18px; height: 18px; padding: 0 5px;
      border-radius: 9px; background: var(--primary); color: #06232A;
      font-size: 11px; font-weight: 700; line-height: 18px;
      text-align: center; box-shadow: 0 0 0 2px #101113; }}
  .au-tar-riga {{ display: flex; justify-content: space-between;
                 align-items: baseline; font-size: 12.25px; color: {TESTO};
                 margin: 0; }}
  /* Il (?) si centra sull'etichetta come nei tooltip nativi degli slider:
     il gruppo di sinistra e' un flex centrato, e la sua baseline resta
     quella del testo "Taratura". */
  .au-tar-riga > span:first-child {{ display: inline-flex;
      align-items: center; gap: 6px; }}
  .au-tar-riga .au-perche {{ margin-left: 0; position: relative;
      top: 2px; }}
  /* La barra della taratura e' spezzata nei suoi passi, e ogni segmento e'
     largo quanto il passo costa: un CUGAN x3 dura il triplo di un
     animevideov3 x2, e segmenti uguali direbbero una bugia. Il segmento in
     corso pulsa perche' dentro un passo non si muove nient'altro: e'
     l'unico segno che il lavoro sta procedendo. */
  .au-tar-tappe {{ display: flex; gap: 3px; height: 9px; margin: 3px 0 7px; }}
  /* `min-width`: l'estrazione vale meno dell'1% del giro; senza un minimo
     sparirebbe, e sotto i 14px la pillola non si legge come tale (a
     parita' di raggio diventerebbe un cerchio). */
  .au-tar-tappe > span {{ background: {BORDO_VIVO}; border-radius: 999px;
      min-width: 14px; }}
  .au-tar-tappe > span.fatta {{ background: var(--primary); }}
  .au-tar-tappe > span.corso {{ background: var(--primary);
      animation: au-pulsa 1.3s ease-in-out infinite; }}
  @keyframes au-pulsa {{ 0%, 100% {{ opacity: .35; }} 50% {{ opacity: 1; }} }}
  /* Non monospazio: lo spazio della vedova mono e' largo quanto una
     lettera e la riga sembrava avere doppi spazi. */
  .au-tar-stato {{ font-size: 12.5px; color: {TESTO_2};
      margin-bottom: 16px; }}
  .au-tar-stato::first-letter {{ text-transform: uppercase; }}
  /* Il titolo della modale e' un h2 che Streamlit fissa alla creazione:
     non puo' cambiare a meta' processo. Il contatore glielo appende il CSS,
     guardando quale marcatore invisibile e' presente nel corpo. */
  .au-tar-passo {{ display: none; }}
  /* L'h2 e' un contenitore flex: lo spazio in testa al `content` diventa
     un elemento a se' e il distacco raddoppia. Lo spazio lo fa il margine.
     Lo span interno del titolo porta un `margin-right: 2rem` di Streamlit
     (serve a tenere il titolo lontano dalla X): con il contatore in coda
     diventava un buco di 32px, e va azzerato — la distanza dalla X la
     garantisce il contatore stesso. */
  [role="dialog"]:has(.au-tar-passo) h2 > span {{ margin-right: 0; }}
  [role="dialog"] h2::after {{ margin-left: 7px; }}
  /* Il contatore «· 1 di 3» lo scrive `_modale_taratura`, nella lingua
     del momento: qui, in un CSS calcolato una volta all'avvio, restava
     in italiano anche con l'interfaccia in inglese. */
  .au-tar-avviso {{ display: flex; gap: 9px; align-items: flex-start; }}
  .au-tar-avviso svg {{ color: {GIALLO}; flex: 0 0 auto; margin-top: 3px; }}
  [class*="st-key-cTarValori"] table {{ width: 100%; }}
  [class*="st-key-cTarValori"] thead th {{ background: {FONDO_2}; }}
  /* Confronto finale: le colonne stavano addosso l'una all'altra. */
  [class*="st-key-cTarConfronto"] table {{ width: 100%; }}
  [class*="st-key-cTarConfronto"] th,
  [class*="st-key-cTarConfronto"] td {{ padding: 7px 16px; }}
  [class*="st-key-cTarConfronto"] thead th {{ background: {FONDO_2}; }}
  /* La colonna "nuova" e' il nuovo riferimento, le altre sono solo il
     paragone: la tinta di casa lo dice senza bisogno di una legenda. */
  [class*="st-key-cTarConfronto"] tr > *:nth-child(4) {{
      background: var(--primaryBg) !important; color: {TESTO};
      font-weight: 500; }}
  /* Il primario staccato dall'avviso che lo precede: attaccato sembrava
     parte del testo invece che il passo successivo. */
  [class*="st-key-tarAvvia"] {{ margin-top: 18px; }}
  /* La (?) della Taratura sta a ridosso del margine sinistro: il fumetto
     resta centrato (e' la regola) ma si aggancia spostato a destra quanto
     basta a non uscire dalla finestra. Vale per entrambi gli stati, chiuso e
     aperto, o il transform dell'hover lo ricentrerebbe. */
  .au-tar-riga .au-perche .au-bolla {{
      left: 50px; transform: translateX(-50%) translateY(3px); }}
  .au-tar-riga .au-perche:hover .au-bolla,
  .au-tar-riga .au-perche:focus-visible .au-bolla {{
      transform: translateX(-50%) translateY(0); }}
[data-testid="stSidebar"] :is([class*="st-key-cTarRiga"], [class*="st-key-cCartellaRiga"]) {{
      margin: 6px 0 2px; }}
  :is([class*="st-key-cTarRiga"], [class*="st-key-cCartellaRiga"]) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  /* La DATA detta la baseline (allineata a "Taratura" dal flex sopra);
     il calendario, che una baseline non ce l'ha, viene riappeso a mano
     sull'inchiostro delle cifre. */
  .au-tar-data {{ display: inline-flex; align-items: baseline; gap: 5px; }}
  /* Il percorso della cartella dei dati: sotto la sua riga, a capo dove
     serve invece di sbordare (un percorso non ha spazi dove andare a capo). */
  .au-cartella {{ overflow-wrap: anywhere; margin: -2px 0 10px;
      font-size: 11.5px; }}
  .au-sb-versione {{ font-size: 11px; color: {TESTO_3};
      margin: 18px 0 4px; }}
  .au-tar-data svg {{ position: relative; top: 1.5px; }}
  /* Tutto su una riga: la scritta+data nel markdown, e il bottone di
     Streamlit TRAVESTITO da link, ancorato in assoluto a destra della
     stessa riga (Streamlit impila, non affianca). Il padding-right della
     riga riserva lo spazio del link, calcolato da chi la scrive. */
  [data-testid="stSidebar"] :is([class*="st-key-cTarRiga"], [class*="st-key-cCartellaRiga"]) {{
      position: relative; }}
  [data-testid="stSidebar"] :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) {{
      position: absolute; right: 0; top: 50%;
      transform: translateY(calc(-50% - 2px)); width: auto; }}
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button {{
      background: none !important; border: none !important;
      padding: 0 !important; min-height: 0 !important; height: auto;
      color: {TESTO} !important;
      text-decoration: underline; text-underline-offset: 2px;
      transform: none !important; }}
  /* Il corpo va sul p interno (il button non lo tramanda), e il ritocco
     verticale riporta la sua baseline su quella di "Taratura" e della
     data: misurato, il centraggio geometrico lo lasciava 3px sotto. */
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button p {{ font-size: 11.5px; }}
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button:hover {{
      background: none !important; border: none !important;
      color: {TESTO} !important; opacity: .8; }}
  [data-testid="stElementContainer"]:has(.au-sb-sezione)
      + [data-testid="stElementContainer"] .au-sgruppo {{
      margin-top: 26px; }}
  /* VERDE: etichetta e binario dello slider si abbracciano — il padding
     interno del cursore era 17.5px sopra il binario (misurato). */
  [data-testid="stSidebar"] [data-testid="stSlider"]
      > div:not([data-testid]) > div {{
      padding-top: 8px !important; padding-bottom: 10px !important; }}
  /* Il titolo-madre della sidebar: un gradino sopra le sezioni ("Di base",
     "Avanzate"), che sono in grassetto semplice. */
  .au-sb-titolo {{ font-size: 19px; font-weight: 650;
                  letter-spacing: -.01em; margin: 14px 0 10px; }}
  /* Le due sezioni sorelle: un gradino sotto il titolo-madre, uno sopra
     le etichette di gruppo (che restano eyebrow maiuscole). Il margine
     SOPRA è ciò che le fa leggere come inizio-blocco: senza, la
     gerarchia si appiattiva (successo alla prima stretta di spazi). */
  .au-sb-sezione {{ font-size: 15px; font-weight: 600;
                   letter-spacing: -.005em; margin: 34px 0 6px; }}
  /* Aria verticale della sidebar: più stretta dell'originale ma con i
     TITOLI che staccano — la compattezza sta nei controlli, non nella
     gerarchia. */
  [data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{
      gap: 0.65rem; }}
  /* 3px e non 12: il salto fra i due macro-blocchi ("di base" ->
     "avanzate") deve pesare quanto quello sopra "di base" (misurati 52
     contro 43: il divisore portava 9px di troppo). */
  /* Il divisore sta al CENTRO del salto fra i due macro-blocchi, e il
     salto totale pareggia quello sopra "di base" (43px): margini
     asimmetrici calcolati sulle misure reali (era 10 sopra / 41 sotto). */
  [data-testid="stSidebar"] hr {{ margin: 10px 0 0; }}
  /* Il titolo di sezione che SEGUE il divisore rinuncia a parte del suo
     margine (34 -> 14): e' il divisore a portare gia' meta' del salto. */
  [data-testid="stElementContainer"]:has(hr)
      + [data-testid="stElementContainer"] .au-sb-sezione {{
      margin-top: 23px; }}
  /* La nota di stato "Congelate...": in un riquadro discreto — deve
     spiccare sul resto spento della sidebar senza gridare (niente giallo,
     chiesto cosi'). È anche l'unico testo che il dimmer risparmia. */
  /* La tabella del confronto fra modelli: numeri in rilievo, in cima al
     risultato. Prima erano una riga di testo grigia in coda — "non e'
     affatto in rilievo" (utente). */
  .au-cnf {{ width: 100%; border-collapse: collapse; margin: 4px 0 2px;
      font-size: 13px; }}
  .au-cnf th {{ text-align: left; font-weight: 500; font-size: 11px;
      letter-spacing: .04em; text-transform: uppercase;
      color: var(--grayText); padding: 0 10px 4px 0;
      border-bottom: 1px solid rgba(138,144,153,.25); }}
  .au-cnf td {{ padding: 6px 10px 6px 0; font-variant-numeric: tabular-nums;
      border-bottom: 1px solid rgba(138,144,153,.12); }}
  .au-cnf .au-cnf-nome {{ font-weight: 600; }}
  .au-cnf .au-cnf-scarto {{ color: var(--grayText); }}
  /* L'avviso vero e proprio: giallo, la stessa famiglia delle chip
     `au-warn` e degli avvisi del referto. Distinto dalla nota grigia di
     congelamento, che e' una didascalia e non un avviso. */
  .au-nota-avviso {{ background: rgba(242,184,75,.10);
      border: 1px solid rgba(242,184,75,.25);
      border-left: 3px solid rgba(242,184,75,.55);
      border-radius: 6px; padding: 8px 12px; margin: 6px 0 4px;
      font-size: 12px; line-height: 1.5; color: #E8C98A; }}
  .au-nota-congelo {{ background: var(--grayBg);
      border: 1px solid rgba(138, 144, 153, .30);
      border-left: 3px solid rgba(138, 144, 153, .55);
      border-radius: 6px; padding: 8px 12px; margin: 6px 0 4px;
      font-size: 12px; line-height: 1.5; color: var(--grayText); }}
  /* Le etichette di sezione hanno bisogno di uno stacco dichiarato. Misurato,
     tutte e quattro avevano gli stessi margini: la differenza che si vedeva
     era che sotto la tendina c'e' un controllo con la sua spaziatura interna,
     mentre sotto "Modelli disponibili" la griglia comincia subito. Senza il
     modificatore, la stessa regola avrebbe allontanato anche le intestazioni
     di colonna dell'elenco, che sono la stessa classe. */
  /* 8px fra etichetta e contenuto, come `.filebox > label` nel mockup.
     NON si compensa lo stacco di Streamlit con un margine negativo: quello
     vale 14px davanti a un controllo e 0 davanti a del markup, quindi una
     compensazione unica andava bene in un punto e faceva SOVRAPPORRE
     l'etichetta al campo nell'altro (misurato -6px). Si dichiara invece il
     `gap` del contenitore che le avvolge entrambe.
     `[data-testid=...]` in testa serve solo ad alzare la specificita': la
     regola di Streamlit sul `gap` ha lo stesso peso della mia e arriva dopo,
     quindi senza vinceva lei (misurato: gap 14px invece di 8). */
  .au-sez {{ display: block; margin-bottom: 0; }}
  .au-sez-int {{ display: block; margin-bottom: 8px; }}
  [data-testid="stVerticalBlock"][class*="st-key-campo"] {{ gap: 8px; }}
  [class*="st-key-campo"] [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  /* --- 2 · Confronto ---------------------------------------------------- */
  .au-sezione {{ font-size: 18px; font-weight: 600; letter-spacing: -.01em;
                margin-bottom: 4px; }}
  /* Le tre statistiche in un riquadro solo, largo quanto il contenuto: erano
     tre `st.metric`, che hanno una misura loro enorme e pesavano più
     dell'elenco dei modelli — cioè della cosa da cui si decide. */
  .au-stat {{ display: flex; width: fit-content; margin: 22px 0 30px;
             border: 1px solid {BORDO}; border-radius: 8px;
             background: var(--surface); }}
  .au-stat > div {{ padding: 14px 26px; }}
  .au-stat > div + div {{ border-left: 1px solid {BORDO}; }}
  .au-stat dt {{ font-size: 10px; font-weight: 500; letter-spacing: .08em;
                text-transform: uppercase; color: {TESTO_3}; margin-bottom: 3px; }}
  .au-stat dd {{ font-family: var(--mono); font-size: 19px; margin: 0;
                font-variant-numeric: tabular-nums; letter-spacing: -.01em; }}
  .au-stat dd small {{ font-size: 12px; color: {TESTO_2}; }}
  /* Identico al suggerimento nativo della sidebar: stessa icona, stessa
     misura, stesso colore e `cursor: pointer` — non `help`, che su macOS
     diventa il punto interrogativo accanto alla freccia. */
  .au-perche {{ display: inline-flex; align-items: center; margin-left: 6px;
               cursor: pointer; vertical-align: middle; }}
  /* Su per 1px: l'etichetta e' maiuscoletto senza discendenti, i glifi
     stanno tutti sopra la baseline, e l'icona centrata sul BOX del testo
     risultava otticamente bassa (visto dall'utente, righello alla mano). */
  .au-perche svg {{ display: block; transform: translateY(-1px); }}
  /* Il "?" è un aiuto, non un contenuto: al colore del testo pieno pesava
     quanto l'etichetta che accompagna. */
  /* Stesso colore ovunque, sidebar e colonna principale: Streamlit usa il
     testo pieno al 60% in un punto e pieno nell'altro, quindi gli stessi
     suggerimenti pesavano diversamente a seconda di dove stavano. */
  /* `:not(.au-tag)`: il colore del suggerimento non deve toccare le chip, che
     il loro colore ce l'hanno già. Applicandolo anche a quelle, la chip
     d'errore usciva grigio-marrone invece che rossa. */
  [data-testid="stTooltipHoverTarget"], .au-perche:not(.au-tag) {{
      color: {TESTO_3}; }}
  [data-testid="stTooltipHoverTarget"] svg {{ stroke: {TESTO_3} !important; }}
  [data-testid="stTooltipHoverTarget"]:hover, .au-perche:not(.au-tag):hover {{
      color: {TESTO_2}; }}
  [data-testid="stTooltipHoverTarget"]:hover svg {{
      stroke: {TESTO_2} !important; }}

  /* Il fumetto d'aiuto per il markup nostro. Prima era l'attributo `title`,
     cioè il riquadro giallino del sistema operativo: fuori tema, fuori
     carattere e con mezzo secondo di ritardo. Questo somiglia a quello dei
     controlli di Streamlit, che nella sidebar è quello che si vede. */
  .au-perche {{ position: relative; }}
  /* SOPRA l'icona, sempre: e' la regola dell'app (decisa dall'utente il
     2026-08-10). In alto lo spazio c'e' praticamente ovunque, e un fumetto
     che scende copre quello che si sta per leggere o cliccare. Le eccezioni
     che c'erano — fascia, righe — sono sparite: erano la regola scritta tre
     volte. */
  /* Il vestito del fumetto sta tutto in `.au-bolla`, piu' sotto: qui non
     c'e' piu' niente. Prima queste erano cinquanta righe che ridichiaravano
     fondo, bordo, carattere, misure e ombra identici a quelli della (i) —
     due vestiti per la stessa cosa, tenuti allineati a mano. Il fumetto e'
     ora un elemento vero anche qui (vedi `_bolla`), quindi la stessa
     regola veste tutti e due. */
  /* Il fumetto della (i): stesso vestito di quello della (?), ma fatto di
     elementi veri, perché ha un titolo e delle righe. */
  /* L'etichetta dei controlli della sidebar, disegnata da noi al posto di
     quella di Streamlit. I valori NON sono scelti: sono misurati sul DOM
     dell'etichetta nativa (Inter 12.25/18.375, peso 400, testo pieno,
     margine 0 0 3.5px, riga flex con l'icona a 6px), così il cambio non si
     vede. */
  .au-sb-eti {{ display: flex; align-items: center;
               font-size: 12.25px; font-weight: 400; line-height: 18.375px;
               color: {TESTO}; margin: 0 0 3.5px;
               /* 21px e' l'altezza MISURATA dell'etichetta nativa: senza,
                  il controllo si accorciava di 2,6px e tutta la sidebar
                  saliva. Il margine di 3.5 e' anch'esso il suo. */
               min-height: 21px; }}
  /* Il contenitore di markdown porta il margine negativo che in questo
     progetto serve a recuperare i 14px che Streamlit mette sotto ogni
     paragrafo: qui NON va, o l'etichetta finisce sopra il cursore
     (misurato: si sovrapponevano di 1,5px). */
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(.au-sb-eti) {{
      margin-bottom: 0 !important; }}
  /* L'etichetta ora e' un blocco a se', e la colonna della sidebar mette
     0.65rem di distanza fra un blocco e l'altro: distanza che prima non
     c'era, perche' etichetta e cursore stavano nello stesso blocco. Va
     tolta, o ogni controllo cresce di 9px e la sidebar si allunga.
     (Misurato: 42,5px per controllo prima, 51,6 dopo.) */
  [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.au-sb-eti) {{
      margin-bottom: -0.65rem; }}
  .au-sb-val {{ margin-left: auto; padding-left: 12px; }}
  /* Nella sidebar il fumetto resta centrato sull'icona — e' la regola —
     ma li' lo spazio a sinistra e' poco: l'icona piu' vicina al bordo sta a
     99px dal margine della finestra (misurato), quindi centrata puo' essere
     larga al massimo 199. A 190 ci sta con un margine, e nessuno dei cinque
     esce dallo schermo. Piu' stretta significa piu' alta, che in una colonna
     e' il verso giusto in cui crescere. */
  [data-testid="stSidebar"] .au-bolla {{ max-width: 190px; }}

  /* L'aiuto degli interruttori: appoggiato a filo destro della riga, fuori
     dall'etichetta del componente (che e' larga 193px su 256). Fuori dal
     flusso, quindi non aggiunge altezza ne' prende il gap della colonna. */
  /* Tutti gli interruttori della sidebar, per PREFISSO e non per elenco:
     l'elenco a mano (cDedup, cDenoise, cForza) ha lasciato fuori il quarto
     appena e' stato aggiunto, e la sua icona d'aiuto non si posizionava —
     senza errori, semplicemente non si vedeva dov'era attesa. */
  [data-testid="stSidebar"] [class*="st-key-sw"] {{ position: relative; }}
  /* Va sfilato dal flusso il BLOCCO che Streamlit costruisce intorno al
     nostro markup, non il nostro div: `stElementContainer` e' gia'
     `position: relative`, quindi un assoluto messo piu' dentro si aggancia
     a lui e resta dov'era (misurato: 29px sotto la riga, cioe' esattamente
     dove sarebbe caduto da solo). */
  [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.au-sb-aiuto) {{
      position: absolute; right: 0; top: 0; height: 21px; width: auto;
      /* La centratura si fa QUI: piu' sotto i contenitori di Streamlit hanno
         altezza zero, e un `height: 100%` non ha su cosa appoggiarsi (l'icona
         restava incollata in alto, 4,5px fuori asse). */
      display: flex; align-items: center; }}
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"]:has(.au-sb-aiuto) {{
      margin-bottom: 0 !important; }}
  .au-sb-aiuto {{ display: flex; align-items: center; }}
  .au-sb-aiuto .au-info {{ margin-left: 0; }}
  /* L'1px di rialzo dell'icona serve accanto al maiuscoletto delle
     etichette-occhiello, che non ha discendenti; qui il testo e' normale e
     lo stesso rialzo la porta fuori asse (misurato: -0,8px). */
  .au-sb-eti .au-info svg, .au-sb-aiuto .au-info svg {{ transform: none; }}
  /* Qui, e SOLO qui, il fumetto non e' centrato sull'icona ma allineato al
     suo bordo destro: l'icona sta a filo della colonna, e centrato
     sborderebbe di quasi cento pixel sulla pagina. La punta invece resta
     sotto l'icona, che e' cio' che deve indicare. */
  .au-sb-aiuto .au-bolla {{ left: auto; right: 0;
                           transform: translateY(3px); }}
  .au-sb-aiuto .au-info:hover .au-bolla,
  .au-sb-aiuto .au-info:focus-visible .au-bolla {{ transform: translateY(0); }}
  .au-sb-aiuto .au-bolla::before {{ left: auto; right: 7px;
                                   transform: translateX(50%) rotate(225deg); }}
.au-info {{ display: inline-flex; align-items: center; margin-left: 6px;
             cursor: pointer; vertical-align: middle; position: relative;
             color: {TESTO_3}; }}
  .au-info:hover {{ color: {TESTO_2}; }}
  .au-info svg {{ display: block; transform: translateY(-1px); }}
  .au-bolla {{
      position: absolute; left: 50%; bottom: calc(100% + 8px);
      transform: translateX(-50%) translateY(3px);
      display: flex; flex-direction: column; gap: 2px;
      /* 264 e non 230: misurata, la riga della forchetta («Durata
         possibile: da 10h 15m a 15h 35m») ne chiede 254, e andava a
         capo spezzando in due un intervallo che si legge come uno. */
      width: max-content; max-width: 264px; text-align: left;
      background: var(--surfaceHover); color: {TESTO};
      border: 1px solid {BORDO}; border-radius: 6px;
      padding: 9px 12px; font-size: 12.5px; font-weight: 400;
      line-height: 1.45; letter-spacing: normal; text-transform: none;
      font-family: var(--font); box-shadow: 0 6px 20px rgba(0,0,0,.45);
      /* Le chip sono `nowrap` — devono stare su una riga — e il fumetto
         EREDITA quel valore: il testo si stendeva su una riga sola larga
         1.800px dentro un riquadro da 264, e quel traboccamento allargava
         la pagina (barra di scorrimento orizzontale in Lavorazione,
         2.623px contro 1.129 di finestra: misurato per bisezione). Serviva
         solo ai fumetti delle chip finche' erano pseudo-elementi; ora che
         il meccanismo e' uno solo, sta qui. */
      white-space: normal;
      opacity: 0; pointer-events: none;
      /* Sopra la fascia in basso, che e' fissa a z-index 100: una riga
         appena sopra la fascia aveva il fumetto nascosto dietro di essa
         (misurato). Un suggerimento coperto e' un suggerimento che non
         c'e'. */
      z-index: 220;
      /* IL PERIODO DI GRAZIA (0,3 s di ritardo solo in USCITA).
         Ogni cinque secondi il riquadro della Lavorazione si riesegue, e in
         quell'istante il puntatore viene rubato all'icona da un pulsante
         della riga: misurato, 8 campioni su 286 a passi di cinque secondi
         esatti, con l'icona ferma a `1364,577 14x14` e il suo z-index
         intatto. La finestra dura meno di un decimo di secondo, ma tanto
         basta: il fumetto si chiudeva di colpo e Safari non rivaluta il
         `:hover` fino al disegno successivo, quindi restava chiuso quasi un
         secondo. Da fuori: un fumetto che lampeggia ogni cinque secondi
         (segnalato dall'utente, che ha anche indovinato il meccanismo).
         Con tre decimi di ritardo sulla SPARIZIONE, un blip da un decimo
         non lo tocca. L'apparizione resta immediata: il ritardo sta qui,
         nella regola a riposo, e la regola di hover qui sotto lo azzera.
         Non e' la cura del difetto — quella e' non rieseguire le righe —
         ma toglie il sintomo anche mentre la cura si costruisce. */
      transition: opacity .12s ease .3s, transform .12s ease .3s; }}
  .au-info:hover .au-bolla, .au-info:focus-visible .au-bolla,
  .au-perche:hover .au-bolla, .au-perche:focus-visible .au-bolla {{
      opacity: 1; transform: translateX(-50%) translateY(0);
      transition: opacity .12s ease 0s, transform .12s ease 0s; }}
  /* Nelle righe l'icona porta `z-index: 2` (per stare sopra la lastra che
     rende cliccabile la riga) e con esso apre un contesto di impilamento:
     dentro, il 220 del fumetto vale solo verso i fratelli, e le (i) delle
     altre righe — pari grado, ma dopo nel DOM — gli finivano sopra. Ad
     aprire il fumetto sale l'ICONA INTERA, che e' il contesto. */
  /* E lo stesso periodo di grazia sullo Z-INDEX, che e' l'altra meta' del
     lampeggio. L'icona sale a 240 SOLO mentre e' sotto il mouse; perdendo
     l'hover per un istante ricadeva a 2, pari grado con tutte le altre, e
     le icone che vengono DOPO nel documento le passavano davanti insieme al
     suo fumetto — «per un attimo viene coperto dalle (i) degli altri»
     (utente, che aveva ragione anche qui). `z-index` transisce a scatti,
     quindi un ritardo di 0,3 s in discesa lo tiene su per tutta la durata
     del blip; in salita il ritardo e' zero, sotto. */
  .au-info, .au-perche {{ transition: z-index 0s .3s; }}
  .au-info:hover, .au-info:focus-within, .au-info:focus-visible,
  .au-perche:hover, .au-perche:focus-within, .au-perche:focus-visible {{
      z-index: 240; transition: z-index 0s 0s; }}
  .au-bolla-tit {{ font-weight: 600; color: {TESTO};
                  margin-bottom: 3px; }}
  .au-bolla-riga {{ color: {TESTO_2}; }}
  /* La frase che spiega il PERCHÉ sta staccata dalle cifre: è prosa, non
     una voce dell'elenco, e incollata si legge come una quarta riga. */
  .au-bolla-nota {{ color: {TESTO_3}; margin-top: 6px; }}
  .au-bolla::before {{
      content: ""; position: absolute; left: 50%; bottom: -5px;
      width: 10px; height: 10px; background: var(--surfaceHover);
      border-left: 1px solid {BORDO_VIVO}; border-top: 1px solid {BORDO_VIVO};
      transform: translateX(-50%) rotate(225deg); }}

  /* I suggerimenti NATIVI che restano (quelli sui comandi senza icona:
     pulsanti, caselle, tendine) prendono lo stesso vestito dei nostri. La
     posizione e la punta no: quelle le decide un popover in JavaScript e
     BaseWeb la punta non la disegna proprio. Ma colore, carattere, corpo,
     riquadro e ombra sì, e sono quelli che si notano.
     Misurati i suoi valori di partenza: fondo #22262B, angoli 8px, nessun
     bordo, testo pieno a 12.25/18.375, imbottitura 5.25/10.5. */
  [data-testid="stTooltipContent"] {{
      max-width: 264px !important;
      background: var(--surfaceHover) !important;
      color: {TESTO_2} !important;
      border: 1px solid {BORDO} !important; border-radius: 6px !important;
      padding: 9px 12px !important;
      font-family: var(--font) !important;
      font-size: 12.5px !important; line-height: 1.45 !important;
      box-shadow: 0 6px 20px rgba(0,0,0,.45) !important; }}
  /* Il testo dentro eredita, ma Streamlit ci mette un paragrafo con le sue
     misure: vanno riportate anche li'. */
  [data-testid="stTooltipContent"] p {{
      color: {TESTO_2} !important; font-size: 12.5px !important;
      line-height: 1.45 !important; margin: 0 !important; }}
  /* Il contenitore di markdown porta il `margin-bottom: -14px` con cui in
     tutta l'app si recuperano i 14px che Streamlit mette sotto ogni
     paragrafo. Dentro il fumetto quel recupero si mangia l'imbottitura: il
     testo finiva 4px SOTTO il bordo inferiore, contro i 10 che aveva sopra
     (misurato, visto dall'utente sul suggerimento di "Chiudi AnimeUp"). */
  [data-testid="stTooltipContent"] [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}


  /* La tendina dei file: larga quanto il nome più lungo, entro un minimo e
     un massimo. A tutta colonna erano ottocento pixel di vuoto per un nome che
     ne occupa trecento. */
  /* La larghezza arriva da Python (vedi `page_confronto`): il testo dentro la
     tendina ha i puntini di troncamento, quindi la sua larghezza intrinseca è
     piccola e né `fit-content` né `max-content` la fanno crescere — restava
     al minimo troncando il nome. La misura del nome più lungo la sappiamo
     noi, e gliela diciamo. */
  .st-key-campoFile [data-testid="stSelectbox"] {{ max-width: 100%; }}

  .au-modelli {{ display: grid; grid-template-columns: repeat(3, 1fr);
                gap: 12px; margin-bottom: 14px; }}
  .au-modello {{ background: var(--surface); border: 1px solid {BORDO};
                border-radius: 8px; padding: 14px 16px; }}
  /* Ogni scheda si tinge del suo verdetto — bordo E un velo di fondo, così
     la fila si legge a colpo d'occhio senza leggere le chip. Il velo sta
     sotto il 6%: deve orientare, non urlare. */
  .au-consigliato {{ border-color: rgba(69,212,131,.35);
                    background: rgba(69,212,131,.05); }}
  .au-verifica {{ border-color: rgba(242,184,75,.3);
                 background: rgba(242,184,75,.04); }}
  .au-sconsigliato {{ border-color: rgba(242,109,109,.3);
                     background: rgba(242,109,109,.04); }}
  .au-m-testa {{ display: flex; align-items: center; gap: 8px;
                margin-bottom: 6px; flex-wrap: wrap; }}
  .au-m-nome {{ font-size: 13.5px; font-weight: 600; }}
  .au-m-desc {{ font-size: 12px; color: {TESTO_2}; line-height: 1.5;
               margin-bottom: 8px; }}
  .au-m-vel {{ font-family: var(--mono); font-size: 11px; color: {TESTO_3}; }}

  /* Le card degli spezzoni: la selezione si vede dal bordo ciano più un
     fondo appena acceso, gli stessi della scheda attiva nello stepper. */
  /* Le card della stessa riga alte uguali: le colonne di Streamlit si
     allineano in alto, quindi una descrizione da due righe lasciava la card
     più bassa delle vicine. Stira la colonna e la card la riempie. */
  [class*="st-key-clip"] {{ background: var(--surface);
      border: 1px solid {BORDO}; border-radius: 8px; padding: 8px;
      height: 100%;
      transition: border-color .12s ease, background .12s ease; }}
  [data-testid="stHorizontalBlock"]:has([class*="st-key-clip"]) {{
      align-items: stretch; }}
  [data-testid="stHorizontalBlock"]:has([class*="st-key-clip"])
      [data-testid="stColumn"] {{ display: flex; }}
  [data-testid="stHorizontalBlock"]:has([class*="st-key-clip"])
      [data-testid="stColumn"] > div {{ width: 100%; }}
  /* Fra la colonna e la card c'e' uno `stLayoutWrapper` che si dimensiona sul
     contenuto: `height: 100%` sulla card era il 100% di quello, non della
     colonna, e restava alta 246 dentro una colonna da 262. Si stira anche
     l'anello di mezzo. */
  [data-testid="stHorizontalBlock"]:has([class*="st-key-clip"])
      [data-testid="stColumn"] [data-testid="stLayoutWrapper"] {{
      height: 100%; width: 100%; }}
  /* I pulsanti del video-compare sono L'AZIONE dei risultati: bordo e
     testo ciano, spazio sopra — prima erano secondari grigi appiccicati
     alle proiezioni e sparivano (visto dall'utente). */
  /* La linea verticale che separa "Modelli da provare" dal resto della
     fascia di lancio: stesso peso e colore della riga orizzontale sopra. */
  .st-key-lancio > div > [data-testid="stHorizontalBlock"]
      > [data-testid="stColumn"]:nth-child(2) {{
      border-left: 1px solid {BORDO}; padding-left: 24px; }}
  /* I pulsanti del video-compare sono primari veri (ciano pieno, come
     "Elabora gli spezzoni"), larghi quanto il loro testo, con aria sopra. */
  [class*="st-key-cmp"] button {{ margin-top: 4px; }}
  .au-file-eti {{ color: {TESTO}; font-weight: 600; }}
  /* Aria fra i percorsi e la CTA della cartella (era incollata). */
  [class*="st-key-finder_conf"] {{ margin-top: 10px !important; }}
  /* Titoli degli accordion dei risultati: un gradino sopra il normale. */
  .st-key-risultati [data-testid="stExpander"] summary p {{
      font-size: 15px; font-weight: 600; }}
  /* Il pulsante di schermo intero sulle immagini: SEMPRE visibile (non
     solo al passaggio) e a misura d'uomo — era microscopico e fantasma
     (visto dall'utente). Coperti entrambi i markup di Streamlit. */
  .st-key-risultati [data-testid="stElementToolbar"] {{
      opacity: 1 !important; transform: scale(1.5);
      transform-origin: top right; }}
  .st-key-risultati [data-testid="StyledFullScreenButton"] {{
      opacity: 1 !important; width: 3rem !important;
      height: 3rem !important; }}
  .st-key-risultati [data-testid="StyledFullScreenButton"] svg {{
      width: 2rem !important; height: 2rem !important; }}
  /* Scheda-modello impraticabile: presente ma chiaramente fuori gioco. */
  .au-modello.au-spenta {{ opacity: .55; }}
  /* E nella lista "Modelli da provare" il nome si BARRA: spento + barrato
     = fuori gioco senza ambiguita' (chiesto dall'utente). */
  .st-key-campoModelli [data-testid="stCheckbox"]:has(input:disabled) p {{
      text-decoration: line-through; }}
  [class*="st-key-clip"]:hover {{ border-color: {BORDO_VIVO}; }}
  /* Tutta la card fa da interruttore della spunta. NON con un overlay
     dell'etichetta: il click su uno pseudo-elemento non attiva la spunta
     (provato: manina si', spunta no). Il click lo raccoglie il sentinella
     (vedi header) e lo gira all'input vero. Qui solo la manina. */
  [class*="st-key-clip"] {{ cursor: pointer; }}
  [class*="st-key-clip"]:has(input:checked) {{
      border-color: rgba(42,201,222,.55); background: var(--primaryBg); }}
  [class*="st-key-clip"] .au-c-desc {{ font-size: 11px; color: {TESTO_3};
      line-height: 1.45; padding: 0 3px 3px; }}
  [class*="st-key-clip"] [data-testid="stCheckbox"] p {{ font-size: 13px;
      font-weight: 500; }}
  /* L'etichetta prende tutta la riga così l'ora del giorno, messa da
     `::after`, può andare a fondo riga. */
  /* Tutta la catena a larghezza piena: bastava che un anello restasse largo
     quanto il testo (misurato: etichetta 83px dentro un genitore da 104)
     perché l'ora del giorno non avesse spazio dove spostarsi. */
  /* Streamlit dimensiona il contenitore della casella sul suo contenuto
     (misurato: 104px dentro una card da 305), quindi l'etichetta non aveva
     spazio dove spingere l'ora del giorno. Si allarga tutta la catena. */
  [class*="st-key-clip"] [data-testid="stElementContainer"] {{
      width: 100% !important; }}
  [class*="st-key-clip"] [data-testid="stCheckbox"],
  [class*="st-key-clip"] [data-testid="stCheckbox"] > label {{
      width: 100% !important; display: flex; }}
  /* `flex: 1` e non solo `width: 100%`: l'etichetta è un elemento flex e
     restava larga quanto il testo (83px), quindi l'ora del giorno spinta a
     destra si fermava subito dopo la parola. */
  [class*="st-key-clip"] [data-testid="stWidgetLabel"] {{
      flex: 1 1 auto; width: 100%; align-items: center; }}
  [class*="st-key-clip"] [data-testid="stWidgetLabel"]::after {{
      margin-left: auto; font-family: var(--mono); font-size: 11px;
      color: {TESTO_2}; font-variant-numeric: tabular-nums; }}
  [class*="st-key-clip"] [data-testid="stCheckbox"] {{ margin-bottom: 5px; }}
  /* Il solito `margin-bottom: -14px` di Streamlit su `stMarkdownContainer`:
     qui tirava su la scatola lasciando il testo fuori, e la descrizione
     usciva di 2px sotto il bordo della card mentre sopra ne restavano 19.
     Neutralizzato, le distanze tornano quelle dichiarate. */
  [class*="st-key-clip"] [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  [class*="st-key-clip"] .au-c-desc {{ padding: 0 3px; margin: 0; }}
  /* La card È il blocco verticale: il suo `gap` è 1rem, e fra video,
     etichetta e descrizione era troppo. Si mira alla card e non alla classe
     generata (`st-emotion-cache-...`), che Streamlit riusa altrove — la
     stessa sta anche su un cursore della sidebar — e che cambia a ogni
     aggiornamento. */
  [class*="st-key-clip"] {{ gap: .5rem; }}
  /* Streamlit avvolge l'HTML del markdown in un `<p>` con 14px di margine
     sotto: il video se lo portava dietro. */
  [class*="st-key-clip"] .stMarkdown p:has(> .au-clip) {{ margin-bottom: 0; }}
  [class*="st-key-clip"] [data-testid="stCheckbox"] {{ margin-bottom: 0; }}

  /* Le colonne di Streamlit allineano in alto: la chip restava appesa sopra
     il pulsante invece di stargli a fianco. */
  .st-key-avvio [data-testid="stHorizontalBlock"] {{ align-items: center; }}
  .st-key-avvio {{ margin: 28px 0 16px; }}

  /* La parte di lancio è un blocco a se', separato da una linea come nel
     mockup: prima erano due colonne buttate dopo un divisore, con le
     spaziature che capitavano. */
  /* Niente `gap` scritto a mano sul blocco a colonne: Streamlit dimensiona
     ogni colonna con `calc(60% - 14px)`, dove i 14px SONO la distanza che si
     aspetta. Portandola a 32 la somma superava il 100% e le due colonne
     andavano a capo una sotto l'altra. La distanza si chiede a `st.columns`,
     che aggiusta anche la base. */
  .st-key-lancio {{ border-top: 1px solid {BORDO}; padding-top: 24px;
                   margin-top: 32px; }}
  /* Tre colonne: modelli (compatta) | quanto ci vuole (fissa) | esito
     (tutto il resto, e' li' che vivono barra e nota). La vecchia regola
     `1fr | 300px` era dell'era a due colonne e strangolava i pesi passati
     a st.columns (misurato: terza colonna inchiodata a 300px). */
  /* `stretch` e non `start`: le colonne si pareggiano in altezza e la
     linea verticale sulla seconda corre per TUTTA la fascia (col `start`
     si fermava dove finiva il suo contenuto, visto dall'utente). Il
     contenuto resta in cima comunque. */
  .st-key-lancio [data-testid="stHorizontalBlock"] {{
      gap: 32px; flex-wrap: nowrap; align-items: stretch; }}
  .st-key-lancio [data-testid="stColumn"]:nth-child(1) {{
      flex: 0 0 280px; min-width: 0; }}
  .st-key-lancio [data-testid="stColumn"]:nth-child(2) {{
      flex: 0 0 300px; min-width: 0; }}
  .st-key-lancio [data-testid="stColumn"]:nth-child(3) {{
      flex: 1 1 auto; min-width: 0; }}
  /* Il campo dei modelli non deve prendere tutta la colonna: 520px, come
     `.mselect`. */
  .st-key-campoModelli [data-testid="stMultiSelect"] {{ max-width: 520px; }}
  .st-key-lancio .au-sez, .st-key-lancio .au-sez-int {{ margin-bottom: 10px; }}
  [data-testid="stVerticalBlock"].st-key-campoModelli {{ gap: 10px; }}
  .st-key-lancio [data-testid="stMultiSelect"] {{ margin-bottom: 12px; }}
  .st-key-lancio .stButton {{ margin-top: 14px; }}
  .st-key-lancio [data-testid="stCheckbox"] p {{ font-size: 12.5px;
      color: {TESTO_2}; }}

  /* I tag del multiselect. Il selettore precedente era
     `[data-baseweb="tag"]` e non agganciava NIENTE: Streamlit 1.61 non usa
     più BaseWeb qui ma react-aria, e la pillola è il primo `span` dentro il
     tag. Verificato nel DOM prima di scrivere questa regola. */
  [data-testid="stMultiSelectTagsContainer"] > span > span {{
      background: var(--primaryBg) !important;
      border: 1px solid rgba(42,201,222,.3);
      color: var(--primaryHover) !important;
      border-radius: 5px !important;
      padding: 3px 6px 3px 10px !important;
      font-size: 12px !important; }}
  /* La regola sopra vale per ogni tag e non solo per il primo: mirando a
     `:first-child` il secondo modello aggiunto restava col ciano pieno di
     Streamlit e il testo bianco. Il `span` di testo interno viene poi
     ripulito, o si vedrebbe una pillola dentro la pillola. */
  [data-testid="stMultiSelectTagsContainer"] > span > span > span {{
      background: none !important; border: 0 !important; padding: 0 !important;
      color: var(--primaryHover) !important; }}
  [data-testid="stMultiSelectTagsContainer"] > span button svg {{
      color: var(--primaryHover) !important; opacity: .7; }}
  [data-testid="stMultiSelectTagsContainer"] > span button:hover svg {{
      opacity: 1; }}
  /* Il campo attorno, con i valori di `.mselect` nel mockup. */
  [data-testid="stMultiSelect"] [class*="react-aria-ComboBox"] > div {{
      background: var(--surface) !important;
      border: 1px solid {BORDO_VIVO} !important;
      border-radius: 6px !important;
      padding: 7px 10px !important; }}
  /* La × che svuota tutto: ogni tag ha già la sua, e nel mockup non c'e'.
     La freccia resta, perché è l'unico segno che si apre un elenco. */
  [data-testid="stMultiSelect"] [class*="el1q88c8"] {{ display: none; }}

  /* La spunta è un `polyline` con lo STROKE bianco, non un tracciato pieno:
     agire su `color` e `fill` non cambiava niente e il segno restava bianco su
     ciano, cioè invisibile. */
  /* Solo il quadratino, non tutto quello che sta dentro la casella: il
     suggerimento "?" vive lì dentro, e la regola larga dipingeva anche
     quello di `#08262B` — verde scuro su fondo scuro, illeggibile. */
  [data-testid="stCheckbox"] label > div:not([data-testid]) svg,
  [data-testid="stCheckbox"] label > div:not([data-testid]) svg polyline,
  [data-testid="stCheckbox"] label > div:not([data-testid]) svg path {{
      stroke: var(--onPrimary) !important; color: var(--onPrimary) !important; }}

  /* La stima sta in una colonna stretta come nel mockup (300px), non a mezza
     pagina: è una tabellina di tre righe. */
  .au-stima {{ max-width: 320px; }}

  /* Le tre righe della stima: voce a sinistra, tempo a destra, e il totale
     staccato da una linea. Dire solo il totale nascondeva quanto costa il
     riferimento, che è l'unica voce che si può togliere. */
  .au-stima {{ display: flex; justify-content: space-between;
              font-size: 12.5px; color: {TESTO_2}; padding: 5px 0; }}
  .au-stima b {{ font-family: var(--mono); font-weight: 500; color: {TESTO};
                font-variant-numeric: tabular-nums; }}
  .au-stima-tot {{ border-top: 1px solid {BORDO}; margin-top: 6px;
                  padding-top: 10px; }}

  /* La fascia dell'accordion si tinge quando c'e' da verificare: non urla,
     ma smette di essere indistinguibile dal fondo. Più respiro sopra e
     sotto, che a 8px sembrava una riga di elenco. */
  [class*="st-key-perche"] details, [class*="st-key-perche"] summary {{
      border-radius: 8px; }}
  [class*="st-key-perche"] summary {{ padding-top: 12px; padding-bottom: 12px; }}
  .st-key-perche_att summary {{
      background: var(--yellowBg) !important;
      border-left: 3px solid var(--yellow); }}
  .st-key-perche_att summary p {{ color: {GIALLO}; }}
  .st-key-perche_ok summary {{ background: var(--surface) !important; }}

  /* Il perché del consiglio: il caso concreto in evidenza, la regola sotto.
     Un muro di testo uguale non dice quale delle tre fasce è la tua. */
  .au-p-caso {{ border-left: 3px solid var(--green); background: var(--greenBg);
               border-radius: 6px; padding: 12px 16px; }}
  .au-p-giallo.au-p-caso {{ border-left-color: var(--yellow);
                           background: var(--yellowBg); }}
  .au-p-scelta {{ font-size: 15px; font-weight: 600; margin: 4px 0 6px; }}
  .au-p-motivo, .au-p-testo {{ font-size: 12.5px; color: {TESTO_2};
                              line-height: 1.5; }}
  .au-p-alt {{ font-size: 12px; color: {TESTO_3}; margin-top: 6px; }}
  .au-p-regole {{ display: grid; gap: 10px; }}
  .au-p-riga {{ display: grid; grid-template-columns: 150px 1fr; gap: 16px;
               padding-left: 12px; border-left: 2px solid var(--green); }}
  .au-p-riga.au-p-giallo {{ border-left-color: var(--yellow); }}
  .au-p-fascia {{ font-family: var(--mono); font-size: 12px; color: {TESTO}; }}
  .au-p-mod {{ font-size: 12.5px; font-weight: 600; }}
  /* Sotto l'ultima riga non c'era niente e il testo toccava il bordo del
     pannello. */
  .au-provenienza {{ margin: 16px 0 4px; }}
  /* Piu' respiro su tutti i lati, soprattutto sotto: il testo toccava
     il bordo del pannello (visto dall'utente). */
  [class*="st-key-perche"] [data-testid="stExpanderDetails"] {{
      padding: 20px 24px 24px !important; }}
  /* Il solito margin-bottom -14px di Streamlit sull'ultimo markdown si
     mangiava il padding qui sopra: "Non è una teoria" restava incollato
     al bordo anche a padding aumentato. */
  [class*="st-key-perche"] [data-testid="stExpanderDetails"]
      [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  /* La chevron dell'espansore segue il COLORE del testo accanto: gialla
     con la scritta gialla, non bianca per conto suo. `currentColor` via
     inherit, qualunque sia il markup dell'icona. */
  [class*="st-key-perche"] summary svg,
  [class*="st-key-perche"] summary [data-testid="stExpanderToggleIcon"],
  [class*="st-key-perche"] summary [data-testid="stIconMaterial"] {{
      color: inherit !important; fill: currentColor !important; }}
  .st-key-perche_att summary svg,
  .st-key-perche_att summary [data-testid="stExpanderToggleIcon"],
  .st-key-perche_att summary [data-testid="stIconMaterial"] {{
      color: {GIALLO} !important; }}

  /* --- 3 · Lavorazione --------------------------------------------------- */
  /* Le schede del monitoraggio: come le righe dell'elenco, ma il bordo
     sinistro dice "sta girando" (ciano) o "interrotta" (giallo). */
  .au-mon {{ background: var(--surface); border: 1px solid {BORDO};
            border-left: 3px solid var(--yellow); border-radius: 8px;
            padding: 12px 16px; margin-bottom: 8px; }}
  .au-mon-viva {{ border-left-color: var(--primary); }}
  .au-mon-testa {{ display: flex; align-items: center; gap: 10px;
                  flex-wrap: wrap; margin-bottom: 8px; }}
  .au-mon-nome {{ font-weight: 600; font-size: 14px; }}
  .au-mon-dx {{ margin-left: auto; }}
  .au-mon-barra {{ height: 4px; border-radius: 2px; overflow: hidden;
                  background: var(--idleEdge); }}
  .au-mon-barra > span {{ display: block; height: 100%;
                         background: var(--primary);
                         transition: width .6s ease; }}
  .au-mon:not(.au-mon-viva) .au-mon-barra > span {{
      background: var(--yellow); }}
  .au-mon-log {{ font-family: var(--mono); font-size: 11px; color: {TESTO_3};
                margin-top: 8px; white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }}
  .au-busy {{ background: var(--primaryBg); color: var(--primaryHover);
             border-color: rgba(42,201,222,.3); }}
  /* La barra dentro la riga: sotto la testata, sopra il pannello. Il testo
     accanto è già tutto etichettato, quindi può stare in piccolo. */
  /* Barra a tutta larghezza, testo sotto a destra: due righe DELIBERATE.
     La versione a fianco era un flex che su finestre strette andava a capo
     da solo, e sembrava un errore di impaginazione — perché lo era. */
  /* Il testo è una DIDASCALIA della barra: sotto, a sinistra, attaccato a
     lei (4px). A destra a filo del bordo sembrava un pezzo vagante senza
     padrone — detto dall'utente, ed era vero. */
  /* Barra e didascalia si INCOLONNANO col titolo (46px = 16 di padding riga
     + casella + suo distacco): partivano dal bordo della riga, 30px più a
     sinistra di tutto il resto, e sembravano di un'altra scheda. */
  .au-riga-avanz {{ padding: 10px 16px 14px 62px; }}
  /* Il solito margin-bottom negativo di Streamlit sul contenitore del
     markdown: qui la didascalia è l'ULTIMO elemento della riga chiusa,
     quindi il margine accorciava la riga e la scritta finiva SUL bordo
     (misurato: testo a 879 con bordo a 877). */
  [class*="st-key-jrow"] [data-testid="stMarkdownContainer"]:has(.au-riga-avanz) {{
      margin-bottom: 0 !important; }}
  .au-riga-barra {{ height: 4px; border-radius: 2px; margin-bottom: 4px;
                   overflow: hidden; background: var(--idleEdge); }}
  .au-riga-avanz .au-meta {{ display: block; text-align: left;
                            font-size: 11px; color: {TESTO_3};
                            white-space: nowrap; overflow: hidden;
                            text-overflow: ellipsis; }}
  .au-riga-barra > span {{ display: block; height: 100%;
                          background: var(--primary);
                          transition: width .6s ease; }}
  .au-riga-ferma > span {{ background: var(--yellow); }}


  /* Le righe hanno la stessa forma di quelle dei sorgenti, ma qui il bordo
     sinistro dice "selezionato" invece che "stato dell'analisi". */
  /* Nessuna spaziatura sulla riga: la mettono la testata e il pannello,
     come nei Sorgenti — è ciò che permette al pannello di arrivare ai
     bordi senza margini negativi. */
  [class*="st-key-jrow"] {{
      background: var(--surface);
      border: 1px solid {BORDO}; border-left: 3px solid {BORDO_VIVO};
      border-radius: 8px; padding: 0; margin: 0;
      transition: background-color .12s ease, border-color .12s ease,
                  box-shadow .3s ease, transform .3s ease; }}
  /* L'accensione vale solo col mouse sulla TESTATA. Niente :has annidato
     (vietato dai CSS, la regola veniva scartata in blocco): l'overlay della
     chevron copre esattamente la testata, quindi il suo button:hover E' il
     sensore "mouse sulla testata". */
  [class*="st-key-jrow"]:has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{ background: var(--surfaceHover);
      border-top-color: {BORDO_VIVO}; border-right-color: {BORDO_VIVO};
      border-bottom-color: {BORDO_VIVO}; }}
  /* Col mouse sulla testata di una riga COLORATA il colore non si spegne:
     si schiarisce. Un `background` piatto cancellerebbe il gradiente, che
     e' l'unica cosa che dice a colpo d'occhio in che stato e' la riga. */
  [class*="st-key-jrow"]:has(.au-sel):has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{
      background: linear-gradient(90deg, #1B2E34 0%, #1F262A 50%); }}
  [class*="st-key-jrow"]:has(.au-tag.au-busy):has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{
      background: linear-gradient(90deg, #0D3A44 0%, #1F262A 50%); }}
  [class*="st-key-jrow"]:has(.au-compiuta):has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{
      background: linear-gradient(90deg, #0B3A2C 0%, #1F262A 50%); }}
  /* Il riquadro col processo in corso si "alza" dal piano della pagina:
     ombra scura a due strati (contatto + diffusa) e superficie un filo
     piu' chiara — in tema scuro l'elevazione si legge cosi', l'ombra da
     sola su fondo quasi nero non basta. Voluta discreta (utente). */
  [class*="st-key-riga"]:has(.au-s-corso),
  [class*="st-key-jrow"]:has(.au-tag.au-busy) {{
      background: rgba(255, 255, 255, .035);
      /* Lo zoom leggero completa l'effetto "sopraelevato". 1.025 scelto
         dall'utente (1.01 era troppo timido). */
      transform: scale(1.025);
      /* Alone piu' ampio: i tre strati restano (contatto, media
         distanza, diffusa) ma con raggi maggiori, cosi' la riga sembra
         piu' staccata dal piano senza diventare piu' scura. */
      box-shadow: 0 -12px 30px -6px rgba(0, 0, 0, .50),
                  0 6px 18px rgba(0, 0, 0, .45),
                  0 22px 46px -10px rgba(0, 0, 0, .65); }}
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"] {{
      align-items: center; padding: 11px 16px; }}
  /* Due chip nella stessa cella di stato (es. "fatto" + "1 avviso"):
     in colonna, centrate, con 4px d'aria. Da inline si accavallavano
     (line-height piu' bassa della chip) e la seconda ereditava il rientro
     del tooltip: sembravano chip diverse, ed erano solo maltrattate. */
  [class*="st-key-jrow"] [data-testid="stMarkdownContainer"]
      p:has(> .au-tag:nth-of-type(2)) {{
      display: flex; flex-direction: column;
      align-items: flex-start; gap: 4px; }}
  [class*="st-key-jrow"] [data-testid="stMarkdownContainer"]
      p:has(> .au-tag:nth-of-type(2)) > .au-tag.au-perche {{
      margin-left: 0; }}
  /* Gap a zero fra testata e pannello: i 14px di Streamlit finivano SOTTO la
     testata anche a pannello chiuso, e la riga aveva 1px sopra e 16 sotto
     (misurati). La distanza interna la danno i padding, non il gap. */
  [data-testid="stVerticalBlock"][class*="st-key-jrow"],
  [data-testid="stVerticalBlock"][class*="st-key-riga"] {{ gap: 0; }}
  /* Gli elenchi di Sorgenti e Lavorazione sono una fila serrata, non
     schede sparse: al posto dei 14px di Streamlit una fessura sottile,
     quanto basta a separare due bordi senza aprire un vuoto (0.5rem, che
     qui vale 7px: il rem del progetto e' 14, non 16). In px e non in rem
     perche' i valori frazionari venivano arrotondati ora per difetto ora
     per eccesso, e le fessure uscivano disuguali (misurato). */
  /* La fessura si stringe sulle SINGOLE righe e non azzerando il gap del
     blocco che le contiene: in Sorgenti quel blocco e' la pagina intera, e
     il titolo "Controllo dei sorgenti" finiva incollato alle schede
     (visto dall'utente). Il gap resta 14, ogni riga se ne riprende 7. */
  [data-testid="stLayoutWrapper"]:has(> [class*="st-key-jrow"]),
  [data-testid="stLayoutWrapper"]:has(> [class*="st-key-riga"]) {{
      margin-bottom: -7px; }}
  /* La riga al lavoro respira un filo piu' delle altre. Il margine non e'
     quello che si vede: l'effetto di sollevamento la ingrandisce dell'1,5%
     e si mangia ~1,4px per lato, quindi 2px di margine danno ~7,6px
     visibili contro i 7 delle altre (misurato). */
  [class*="st-key-jrow"]:has(.au-tag.au-busy),
  [class*="st-key-riga"]:has(.au-s-corso) {{ margin: 2px 0; }}
  /* La colonna della chip si allinea al centro della tendina accanto: le
     colonne di Streamlit partono in alto, e la chip restava appesa sopra il
     campo invece che alla sua altezza. */
  [class*="st-key-jrow"] [data-testid="stColumn"] {{
      display: flex; flex-direction: column; justify-content: center; }}
  /* La casella restava 3px sotto il centro: Streamlit lascia lo spazio
     dell'etichetta anche quando è nascosta, e la casella si appoggiava in
     fondo al suo contenitore. Centrata dentro il contenitore, non solo il
     contenitore dentro la riga. */
  /* I 7px sono un `margin-top` che Streamlit mette sulla casella per
     allinearla a un'etichetta che qui non c'e' (misurato: `margin-top: 7px`,
     casella alta 21 dentro un contenitore da 28). Tolto quello, il centro
     torna al centro. */
  [class*="st-key-jrow"] [data-testid="stCheckbox"],
  .st-key-intestLav [data-testid="stCheckbox"] {{
      display: flex; align-items: center; margin-top: 0 !important; }}
  /* Nella testata anche il margine SOTTO va a zero: e' lui che spingeva
     la spunta-madre 7px sotto la mediana delle etichette (misurato). */
  .st-key-intestLav [data-testid="stCheckbox"],
  .st-key-intestLav [data-testid="stElementContainer"] {{
      margin: 0 !important; }}
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label,
  .st-key-intestLav [data-testid="stCheckbox"] label {{ margin: 0; }}
  /* La colonna della casella a larghezza FISSA: le colonne di Streamlit sono
     percentuali, quindi il titolo cambiava distanza dal bordo con la
     larghezza della finestra (+49px a 1800, +64 con la sidebar chiusa) e
     niente sotto di lui poteva incolonnarsi con un numero solo. Bloccata la
     colonna, il titolo sta sempre a 3+16+32+16 = 67px dal bordo riga. */
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"]
      > [data-testid="stColumn"]:first-child,
  .st-key-intestLav [data-testid="stHorizontalBlock"]
      > [data-testid="stColumn"]:first-child {{
      flex: 0 0 32px !important; min-width: 32px !important; }}
  /* La casella di riga era 14x14: quasi invisibile su uno schermo grande
     (detto dall'utente). 18x18 col bordo un filo più marcato; il segno di
     spunta dentro si adegua da solo perché l'SVG riempie la scatola. */
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label > div:not([data-testid]),
  .st-key-intestLav [data-testid="stCheckbox"] label > div:not([data-testid]) {{
      width: 18px; height: 18px; flex-shrink: 0;
      border-color: {BORDO_VIVO}; }}
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label > div:not([data-testid]) svg,
  .st-key-intestLav [data-testid="stCheckbox"] label > div:not([data-testid]) svg {{
      width: 100%; height: 100%; }}
  /* La riga d'intestazione si centra in verticale: la spunta-madre e le
     etichette (FILE, RISOLUZIONE...) sulla stessa linea mediana. Misurato:
     la madre ERA centrata — erano le etichette a stare in cima a colonne
     alte 35px; si centra il contenuto di ogni colonna. */
  .st-key-intestLav [data-testid="stHorizontalBlock"] {{
      align-items: center; }}
  .st-key-intestLav [data-testid="stColumn"] {{
      display: flex; align-items: center; }}
  .st-key-intestLav [data-testid="stColumn"] > div {{ width: 100%; }}
  .st-key-intestLav [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  /* Il vero ladro dei 7px: il margin-bottom da 14px sta sul P dentro il
     markdown (misurato: p alto 21 + 14 di margine = scatola da 35 col
     testo in cima). */
  .st-key-intestLav [data-testid="stMarkdownContainer"] p {{
      margin-bottom: 0 !important; }}
  /* `div` E `p`: il paragrafo che Streamlit mette attorno all'HTML porta
     14px di margine sotto, quindi la scatola della chip era alta 38 con una
     chip da 24 e restava in cima invece di centrarsi sulla tendina. */
  /* Solo nella TESTATA: applicata a tutta la riga schiaccerebbe i margini
     dei gruppi dentro il pannello, come già successo nei Sorgenti. */
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"] .stMarkdown div,
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"] .stMarkdown p {{
      margin-bottom: 0 !important; }}
  [class*="st-key-jrow"]:has(.au-open) {{
      border-top-color: {BORDO_VIVO}; border-right-color: {BORDO_VIVO};
      border-bottom-color: {BORDO_VIVO}; }}
  /* Non selezionata: il nome si attenua e il selettore del modello si spegne,
     così l'elenco si legge come "questi sì, questi no" a colpo d'occhio. */
  [class*="st-key-jrow"]:not(:has(.au-sel)) .au-name {{ color: {TESTO_2}; }}
  [class*="st-key-jrow"]:not(:has(.au-sel)) [data-testid="stSelectbox"] {{
      opacity: .55; }}
  /* Lo stato della riga si legge da SINISTRA: il bordo colorato e una
     velatura dello stesso colore che si scioglie nel fondo standard a
     meta' larghezza. Tre stati, tre colori, stessa grammatica. */
  [class*="st-key-jrow"]:has(.au-sel) {{
      border-left-color: var(--primary);
      background: linear-gradient(90deg, #16262B 0%, #191F22 50%); }}
  /* In corso: la stessa velatura, piu' viva. */
  [class*="st-key-jrow"]:has(.au-tag.au-busy) {{
      background: linear-gradient(90deg, #0A2E36 0%, #191F22 50%); }}
  /* Fatto DURANTE la maratona: la riga resta viva e si prende il bordo
     verde delle cose concluse. Il nome torna a piena luce, altrimenti la
     regola generica delle righe non selezionate lo lascerebbe smorto. */
  [class*="st-key-jrow"]:has(.au-compiuta) {{
      border-left-color: var(--green);
      background: linear-gradient(90deg, #082B21 0%, #191F22 50%); }}
  [class*="st-key-jrow"]:has(.au-compiuta) .au-name {{ color: {TESTO}; }}
  /* Concluso ma CON AVVISI: il fondo resta quello verde delle cose fatte
     — il file c'e' ed e' a posto — e cambia solo il bordo, che diventa
     giallo. La velatura gialla su tutta la riga era troppo: gridava un
     allarme dove c'e' solo qualcosa da guardare. */
  [class*="st-key-jrow"]:has(.au-con-avvisi) {{
      border-left-color: var(--yellow); }}
  /* Le tendine non devono avere una scatola propria dentro la riga: il
     loro fondo pieno tagliava il gradiente a meta'. */
  /* Due livelli: il ComboBox di react-aria e il suo `role=group` interno
     (quello con la cornice). Il fondo pieno di entrambi tagliava il
     gradiente a meta' riga. */
  [class*="st-key-jrow"] [data-testid="stSelectbox"] > div,
  [class*="st-key-jrow"] [data-testid="stSelectbox"] div[role="group"] {{
      background: transparent !important; }}
  .st-key-intestLav {{ padding: 0 16px 0 20px; margin-bottom: 2px; }}
  .st-key-sceltaTutti {{ margin-bottom: 20px; }}
  /* Pulsanti e tendina della fascia ad ALTEZZA IDENTICA, imposta e non
     ereditata: i due bottoni uscivano un filo piu' bassi della tendina
     (visto dall'utente). 40px per tutti, contenuto centrato. */
  .st-key-sceltaTutti .stButton button {{
      min-height: 40px; height: 40px; }}
  /* I 40px si impongono al RIQUADRO COL BORDO (il piu' interno) e gli
     involucri lo abbracciano da soli: bloccare anche gli esterni alla
     stessa quota gli segava il bordo inferiore di un pixel (visto
     dall'utente). Nota di servizio: questa tendina e' un ComboBox di
     react-aria, non baseweb — selettori per posizione, non per marca. */
  .st-key-sceltaTutti [data-testid="stSelectbox"] > div > div {{
      height: 40px !important; min-height: 40px !important;
      box-sizing: border-box; align-items: center; }}
  /* Riprendi e Scarta impilati: 6px di gap fra loro (il gap di serie del
     blocco verticale era un fosso). Le spaziature attorno non si toccano;
     larghezza gia' identica per entrambi (use_container_width). */
  [class*="st-key-jrow"] [data-testid="stColumn"]:has([class*="st-key-rip"])
      [data-testid="stVerticalBlock"] {{ gap: 6px; }}
  .au-num {{ text-align: right; }}
  /* La stima di riga sta col resto dei metadati, non alla misura del testo
     corrente: è un dato di contorno, non il contenuto della riga. */
  /* A SINISTRA come la sua intestazione e come ogni altra colonna: era a
     destra e la colonna sembrava sbandierata per conto suo (visto
     dall'utente nello screenshot). I tabular-nums tengono comunque le
     cifre incolonnate fra riga e riga. */
  .au-stima-riga {{ font-family: var(--mono); font-size: 11.5px;
      color: {TESTO_2}; font-variant-numeric: tabular-nums;
      text-align: left; }}
  [class*="st-key-jrow"]:has(.au-sel) .au-stima-riga {{ color: {TESTO}; }}

  /* Il selettore del modello con i valori di `.msel`: fondo più scuro della
     riga, così si legge come un campo dentro una scheda e non come un altro
     riquadro accanto. */
  /* Nelle righe la tendina non ha fondo proprio: sotto c'e' il gradiente
     che racconta lo stato, e una scatola opaca lo bucava. Resta la
     cornice, che basta a dire "qui si sceglie". Nella fascia dei Sorgenti
     il fondo invece serve, perche' li' non c'e' nessun gradiente. */
  [class*="st-key-jrow"] [data-testid="stSelectbox"] > div {{
      background: transparent !important;
      border: 1px solid {BORDO_VIVO} !important;
      border-radius: 6px !important;
      min-height: 0 !important; }}
  .st-key-sceltaTutti [data-testid="stSelectbox"] > div {{
      background: var(--backgroundColor, #101113) !important;
      border: 1px solid {BORDO_VIVO} !important;
      border-radius: 6px !important;
      min-height: 0 !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"] div[value],
  [class*="st-key-jrow"] [data-testid="stSelectbox"] input,
  .st-key-sceltaTutti [data-testid="stSelectbox"] div[value],
  .st-key-sceltaTutti [data-testid="stSelectbox"] input {{
      font-size: 12px !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:hover > div {{
      border-color: #40454C !important; }}
  /* Congelati: `disabled` li spegne davvero, ma rispondevano ancora al
     passaggio del mouse — un invito a cliccare qualcosa che non fa
     niente. La casella durante la catena e' gia' un finto indicatore
     (`au-cb-finta`), qui si zittiscono le tendine: quelle delle righe e
     quella in cima che assegna il modello a tutti (che vive fuori da
     `jrow` e la prima volta era rimasta fuori dalla regola). */
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:has(input:disabled),
  [class*="st-key-modello_tutti"] [data-testid="stSelectbox"]:has(
      input:disabled) {{
      pointer-events: none; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:has(input:disabled):hover
      > div,
  [class*="st-key-modello_tutti"] [data-testid="stSelectbox"]:has(
      input:disabled):hover > div {{
      background: transparent !important;
      border-color: {BORDO} !important; }}
  /* Il cursore di testo dentro una tendina promette una scrittura che
     abbiamo disarmato (vedi il sentinella in header): via anche lui. */
  [data-testid="stSelectbox"] input {{ caret-color: transparent !important; }}
  /* " (consigliato)" SOLO nell'elenco aperto: l'indice della voce arriva
     dal sentinella (data-consig sull'ul), il testo lo mette il CSS — un
     attributo che React non gestisce sopravvive ai suoi ridisegni, quindi
     non puo' sfarfallare. Una regola per possibile posizione. */

  /* Checkbox e tendina delle righe: manina e accensione al passaggio —
     sono comandi veri, devono dichiararsi tali (chiesto dall'utente).
     La manina NON vale da disabilitati (catena in corso). */
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label,
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label *,
  [class*="st-key-jrow"] [data-testid="stSelectbox"] > div,
  [class*="st-key-jrow"] [data-testid="stSelectbox"] > div *,
  .st-key-sceltaTutti [data-testid="stSelectbox"] > div,
  .st-key-sceltaTutti [data-testid="stSelectbox"] > div * {{
      cursor: pointer; }}
  [class*="st-key-jrow"] [data-testid="stCheckbox"] input:disabled,
  [class*="st-key-jrow"] [data-testid="stCheckbox"]:has(input:disabled)
      label, [class*="st-key-jrow"] [data-testid="stCheckbox"]:has(
      input:disabled) label *,
  [class*="st-key-jrow"] [data-testid="stSelectbox"] [aria-disabled="true"],
  [class*="st-key-jrow"] [data-testid="stSelectbox"]
      [aria-disabled="true"] * {{ cursor: default !important; }}
  /* Il riquadrino della checkbox e' un DIV 18x18 dentro la label (lo
     span che gli sta accanto e' un segnaposto da 1px: mirato per errore
     alla prima stesura, e l'hover non si vedeva). */
  [class*="st-key-jrow"] [data-testid="stCheckbox"] label > div:first-of-type {{
      transition: border-color .12s ease, background-color .12s ease; }}
  /* Stessa intensita' dell'hover della tendina qui accanto: prima era
     troppo squillante (ritarato con l'utente). */
  [class*="st-key-jrow"] [data-testid="stCheckbox"]:hover
      label > div:first-of-type {{
      border-color: #565C66 !important;
      background: rgba(255, 255, 255, .07) !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:hover > div,
  .st-key-sceltaTutti [data-testid="stSelectbox"]:hover > div {{
      background: rgba(255, 255, 255, .07);
      border-color: #565C66 !important; }}

  /* La fascia-contenitore dei Sorgenti: la veste grafica sta sul
     CONTENITORE (che ospita anche la CTA, un widget vero), la .au-fascia
     interna resta nuda. */
  [class*="st-key-fasciaSorgenti"] {{
      background: var(--surface); border: 1px solid {BORDO};
      border-radius: 8px; padding: 6px 16px; margin-bottom: 24px; }}
  [class*="st-key-fasciaSorgenti"] [data-testid="stHorizontalBlock"] {{
      align-items: center; }}
  .au-fascia-nuda {{ background: none !important; border: none !important;
                    padding: 0 !important; margin: 0 !important; }}
  [class*="st-key-fasciaSorgenti"] [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  [class*="st-key-fasciaSorgenti"] [data-testid="stColumn"]:has(.stButton),
  [class*="st-key-fasciaSorgenti"] [data-testid="stColumn"]:has(.stButton)
      [data-testid="stVerticalBlock"],
  [class*="st-key-fasciaSorgenti"] [data-testid="stColumn"]:has(.stButton)
      [data-testid="stElementContainer"],
  [class*="st-key-fasciaSorgenti"] [data-testid="stColumn"]:has(.stButton)
      .stButton {{
      display: flex; justify-content: flex-end;
      align-items: flex-end; flex-direction: column; width: 100%; }}
  [class*="st-key-fasciaSorgenti"] [data-testid="stColumn"]:has(.stButton)
      .stButton > button {{ flex: 0 0 auto; width: auto; }}
  [class*="st-key-rianTutti"] button {{
      border: 1px solid {BORDO_VIVO} !important; background: none !important;
      box-shadow: none !important; padding: 6px 14px !important; }}
  [class*="st-key-rianTutti"] button p {{ font-size: 12.5px;
      font-weight: 500; color: var(--codeTextColor, #C6CBD2); }}
  [class*="st-key-rianTutti"] button [data-testid="stIconMaterial"] {{
      font-size: 15px; color: var(--textSecondary); }}

  /* La fascia di riepilogo: una riga sola, allineata alla lista che segue. */
  .au-fascia {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
               background: var(--surface); border: 1px solid {BORDO};
               border-radius: 8px; padding: 12px 16px; margin-bottom: 24px; }}
  .au-fascia b {{ font-size: 14px; font-weight: 600; }}
  .au-fascia-dx {{ margin-left: auto; display: flex; align-items: center;
                  gap: 10px; white-space: nowrap; }}
  /* Il paragrafo di Streamlit porta 14px di margine sotto: il contenuto
     restava in alto nella sua cella e il centro cadeva 7px piu' su di
     quello della fascia (misurato). Stesso azzeramento gia' fatto nella
     barra in basso. */
  [class*="st-key-fasciaSorgenti"] .stMarkdown p {{ margin: 0; }}
  /* Stessa storia dentro le righe: le chip vivono in un paragrafo, e i
     14px di margine sotto le tenevano 7px piu' in alto delle celle
     accanto (misurato). Le celle di testo non se ne accorgevano perche'
     hanno un'altezza propria. */
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] .stMarkdown p,
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"] .stMarkdown p {{
      margin: 0; }}
  .au-barra {{ width: 120px; height: 3px; border-radius: 2px;
              background: {BORDO_VIVO}; overflow: hidden; }}
  .au-barra > span {{ display: block; height: 100%; background: var(--primary); }}
  /* Gli iframe di st.iframe portano solo script (sentinella, auto-scroll):
     st.iframe pretende height >= 1, ma quel pixel sposterebbe le quote
     millimetrate della testata. Qui si schiaccia a zero, come col vecchio
     components.html. */
  [data-testid="stIFrame"], [data-testid="stIFrame"] iframe {{
      height: 0 !important; display: block; }}
  /* Il valore vive nella riga dell'etichetta (vedi `_valore_a_destra`), quindi
     quello sopra il pomello è un doppione, e i valori di minimo e massimo
     sono rumore: si vedono trascinando. */
  [data-testid="stSidebar"] [data-testid="stSliderThumbValue"],
  [data-testid="stSidebar"] [data-testid="stSliderTickBar"] {{ display: none; }}
  /* Le toggle: 30x17 con il pomello da 13, come il mockup. Streamlit le fa
     28x14 con pomello 11 e le colora col primario anche da spente, quindi
     "acceso" e "spento" si distinguevano solo dalla posizione del pomello.
     Il selettore mira ai due div dentro l'etichetta della casella: sono
     generati da BaseWeb e non hanno un `data-testid` proprio. */
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label > div:not([data-testid]) {{
      width: 30px !important; height: 17px !important;
      border-radius: 999px !important; flex: none;
      background: var(--idleEdge) !important;
      transition: background .15s ease; }}
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label > div:not([data-testid]) > div {{
      width: 13px !important; height: 13px !important;
      /* Niente margini orizzontali e posizioni ESPLICITE per i due stati
         (qui sotto): BaseWeb aggiunge un translateX suo anche da spenta,
         e la traccia ha 2px di padding suo: ogni conto usciva sbagliato di
         2px. I valori sotto sono MISURATI sul DOM, non calcolati: spenta
         2px dal bordo sinistro, accesa 1px dal destro (l'asimmetria è
         voluta, scelta a occhio dall'utente sul pannello vero). */
      border-radius: 50% !important; margin: 2px 0 !important;
      transform: translateX(0) !important;
      background: {TESTO_2} !important;
      box-shadow: none !important; transition: background .15s ease; }}
  /* Acceso: la traccia prende il ciano e il pomello si fa scuro, così lo
     stato si legge dal colore prima che dalla posizione. */
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked)
      > div:not([data-testid]) {{ background: var(--primary) !important; }}
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked)
      > div:not([data-testid]) > div {{ background: #0B2A2F !important;
      /* BaseWeb sposta il pomello con un translateX calcolato sulla SUA
         geometria (traccia 28, pomello 11): sulla nostra 30/13 lo portava
         3px troppo a destra, fuori dalla traccia (misurato: pomello a 53 su
         traccia che finisce a 52). Il viaggio MISURATO che lascia 2px di
         1px di aria verso il bordo destro è 12px — non i 13 del conto
         teorico: BaseWeb parte già 2px più in la'. Con 2px il pomello
         sembrava non arrivare in fondo alla corsa (detto dall'utente). */
      transform: translateX(14px) !important; }}
  /* Spenta, anche l'etichetta si attenua: è un'opzione non attiva. */
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label:not(:has(input:checked))
      [data-testid="stWidgetLabel"] p {{ color: {TESTO_2}; }}
  [data-testid="stSidebar"] [data-testid="stCheckbox"] label {{ gap: 10px; }}
  [data-testid="stSidebar"] [data-testid="stCheckbox"] p {{ font-size: 12.5px; }}

  /* Il "?" appartiene all'etichetta e le sta subito accanto: senza questo
     l'etichetta si allarga e il suggerimento galleggia a metà riga, dove non
     si capisce più a cosa si riferisca. */
  [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{
      align-items: center; gap: 6px; }}
  [data-testid="stSidebar"] [data-testid="stWidgetLabel"] > * {{ flex: 0 0 auto; }}
  [data-testid="stSidebar"] [data-testid="stWidgetLabel"]::after {{
      font-family: var(--mono); font-size: 12px; color: {TESTO_2};
      white-space: nowrap; }}
  /* 3px di bordo di stato + 1px di bordo + 16px di padding: se
     l'intestazione non replica lo stesso box model delle righe, le colonne
     slittano di 4px e l'allineamento salta. Vale la pena scriverlo, perché
     guardando il CSS non si capisce da dove venga il 20px. */
  .st-key-intest {{ padding: 0 16px 0 20px; margin-bottom: 2px; }}

  /* Gli spezzoni sono provini che girano in cerchio, non un lettore: i
     comandi coprivano metà immagine e il sovrapposto di Chrome (schermo
     intero, immagine nell'immagine) compariva al passaggio del mouse proprio
     sopra la scena da giudicare. `pointer-events` toglie anche quello. */
  /* Gli spezzoni sono provini che girano in cerchio, non un lettore video.
     Il tag lo scriviamo noi senza `controls` (vedi `_video_ciclico`): è
     l'unico modo che regge anche su Safari, dove il CSS sui comandi non ha
     presa. Le regole su `[data-testid=stVideo]` restano per il ripiego. */
  .au-clip {{ width: 100%; display: block; border-radius: .5rem;
             background: #000; pointer-events: none; }}
  video[data-testid="stVideo"] {{
      border-radius: .5rem; display: block; pointer-events: none; }}
  video[data-testid="stVideo"]::-webkit-media-controls,
  video[data-testid="stVideo"]::-webkit-media-controls-enclosure,
  video[data-testid="stVideo"]::-webkit-media-controls-panel {{
      display: none !important; -webkit-appearance: none; opacity: 0; }}

  /* Le schede sono larghe quanto il loro contenuto, non divise in tre parti
     uguali: `flex: 1 1 auto` le stirava fino a riempire la riga e la
     spaziatura interna del mockup (12x22) andava persa. */
  .st-key-fasi button {{ flex: 0 0 auto; white-space: nowrap; }}
  /* margin-bottom 0: il bordo qui sotto E' la linea su cui deve chiudersi
     la fascia sticky — ogni margine dopo di lui diventava una striscia nera
     morta che copriva il contenuto in scorrimento (visto dall'utente). */
  /* La linea sta sull'INVOLUCRO (piu' sotto, insieme alla fascia sticky) e
     non qui: il blocco e' largo quanto la colonna del contenuto — 989px
     misurati — mentre la fascia arriva ai bordi dell'area a 1.129, e la
     linea restava confinata in mezzo mentre lo sfondo proseguiva (visto
     dall'utente). Chi disegna il fondo disegna anche il bordo che lo
     chiude. */
  .st-key-fasi {{ padding-bottom: 22px; margin-bottom: 0; }}

  /* Fascia di azione ancorata in fondo alla finestra.
     `sticky` non funziona qui: essendo l'ultimo elemento non ha nulla sotto
     contro cui spingere, quindi scorre via con il contenuto. */
  /* width:auto è necessario: Streamlit impone width:100% ai contenitori, che
     con position:fixed ignora `right` e fa sforare la fascia oltre lo schermo */
  /* Fondo semitrasparente e sfocato come `.runbar` nel mockup: l'elenco si
     intravede scorrere sotto invece di essere tagliato da una barra opaca.
     La POSIZIONE resta `fixed` e non `sticky`: è l'ultimo elemento della
     pagina e non ha nulla sotto contro cui spingere. */
  .st-key-barra {{ position: fixed; bottom: 0; left: 0; right: 0;
                  width: auto !important; max-width: none !important;
                  z-index: 100; background: rgba(16,17,19,.92);
                  backdrop-filter: blur(8px);
                  -webkit-backdrop-filter: blur(8px);
                  border-top: 1px solid {BORDO_VIVO};
                  /* Più chiara del fondo pagina, o non si distingueva
                     dall'elenco che le scorre sotto: è una fascia di
                     comando, deve staccarsi. */
                  box-shadow: 0 -10px 30px rgba(0,0,0,.55);
                  /* Passo unico da 16px sopra e sotto: prima 20 dichiarati
                     ma 21/14 misurati, per i margini interni delle bande
                     (incoerenza vista dall'utente). Qui sotto i margini
                     interni vengono azzerati: lo spazio lo da' SOLO questo
                     padding. */
                  padding: 12px 1.2rem 12px; }}
  .st-key-barra::before {{ content: ""; position: absolute; inset: 0;
      background: var(--surface); opacity: .96; z-index: -1; }}
  .st-key-barra [data-testid="stHorizontalBlock"] {{ align-items: center; }}
  .st-key-barra .au-catena, .st-key-barra .au-gpu-occupata,
  .st-key-barra .au-gpu-pausa {{ margin-bottom: 0; }}
  /* Il distacco della terza riga vale anche dentro la barra: la regola
     qui sopra azzera solo il margine SOTTO, che è quello che sballava
     l'altezza della fascia. */
  /* -9 e non 10: fra i due paragrafi la fascia infila i suoi 14px, e il
     distacco misurato usciva 24 invece dei 5 voluti. */
  .st-key-barra .au-catena {{ margin-top: -9px; }}
  .st-key-barra .au-gpu-pausa {{ margin-top: 10px; }}
  .st-key-barra .stMarkdown p {{ margin: 0; }}
  /* Il `margin-bottom: -14px` di Streamlit su stMarkdownContainer (vedi la
     stessa cura nelle card dei clip): qui faceva sbordare la banda di stato
     nel padding inferiore della barra — misurati 2px dal fondo invece dei
     16 dichiarati. */
  .st-key-barra [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .st-key-barra .au-meta {{ font-size: 11px; }}
  .st-key-barra .stButton button {{ padding: 0.8rem 1.6rem; width: auto; }}
  /* Le due CTA a filo destro. `flex-end` sulla colonna non bastava: dentro
     c'e' un blocco verticale che occupa tutta la larghezza, ed è quello che
     va allineato. */
  /* `:has(.stButton)`: solo le colonne che contengono un pulsante. Senza il
     filtro finiva a destra anche il riepilogo, che va letto da sinistra.
     Il pulsante stesso deve smettere di essere largo quanto la colonna, o
     "allineato a destra" non significa niente: è già tutto lo spazio. */
  .st-key-barra [data-testid="stColumn"]:has(.stButton),
  .st-key-barra [data-testid="stColumn"]:has(.stButton) [data-testid="stVerticalBlock"],
  .st-key-barra [data-testid="stColumn"]:has(.stButton) [data-testid="stElementContainer"],
  .st-key-barra [data-testid="stColumn"]:has(.stButton) .stMarkdown,
  .st-key-barra [data-testid="stColumn"]:has(.stButton) .stButton {{
      display: flex; justify-content: flex-end; width: 100%; }}
  .st-key-barra [data-testid="stColumn"]:has(.stButton) .stButton > button {{
      flex: 0 0 auto; width: auto;
      /* Tutte le CTA della fascia larghe uguali: sono alternative fra loro,
         e larghezze diverse le facevano leggere come pesi diversi. Non
         `width: 100%` — resterebbero a filo destro ma prenderebbero tutta
         la colonna, e "allineato a destra" non vorrebbe piu' dire niente.
         168px e' misurato: la piu' larga delle tre («Rifai questo da capo»)
         ne occupa 163 col carattere e i margini di questo pulsante. */
      min-width: 168px; }}
  /* la fascia parte dopo la sidebar QUANDO c'e': con `left` fisso a 21rem,
     chiudendo la sidebar restava a mezz'aria, lasciando un vuoto a sinistra e
     tagliando a metà i nomi dei file */
  [data-testid="stSidebar"][aria-expanded="true"] ~ * .st-key-barra,
  section[data-testid="stSidebar"][aria-expanded="true"] ~ div .st-key-barra {{
      left: 300px; }}
  /* Lo spazio in coda sta sul contenitore della pagina, non in un contenitore
     vuoto: `st.container()` senza contenuto non produce alcun nodo (verificato:
     zero elementi con quella chiave), quindi lo spazio non esisteva e l'ultima
     parte del contenuto restava sotto la fascia, irraggiungibile.
     `:has()` lo applica solo dove la fascia c'e' davvero. */
  .block-container:has(.st-key-barra) {{ padding-bottom: 9rem; }}

  /* Rotella dell'analisi in corso. Gira davvero: è l'unico posto dove
     un'animazione continua ha senso, perché dice "sto lavorando" e la
     pagina altrimenti sembrerebbe ferma per venti secondi. */
  .au-lavoro {{ display: inline-flex; align-items: center; gap: .4rem; }}

  /* --- pannello dei dettagli: una gerarchia sola ------------------------
     Tre livelli e basta: titolo di gruppo, etichetta, valore. Tutte le
     etichette identiche fra loro, tutti i valori identici fra loro. Nessun
     troncamento: se un valore è lungo va a capo, non sparisce dietro i
     puntini. */
  /* Titolo di gruppo con la sua linea: la riga non è un separatore fra i
     gruppi ma la coda del titolo, quindi parte DOPO il testo e arriva a fine
     colonna. Con un bordo inferiore sull'intero blocco la linea passava anche
     sotto al titolo e sembrava una sottolineatura. */
  /* Il titolo di gruppo è più chiaro delle etichette che governa: con
     entrambi sul terziario "TEMPI" e "FRAMERATE" si leggevano come una
     stringa sola. Ed è staccato di 11px, non appoggiato ai figli. */
  .au-gtitolo {{ display: flex; align-items: center; gap: 12px;
                color: {TESTO_2}; font-size: 10.5px; font-weight: 600;
                letter-spacing: .1em; text-transform: uppercase;
                margin: 0 0 11px; }}
  .au-blocco {{ margin-bottom: 18px; }}
  .au-blocco:last-of-type {{ margin-bottom: 0; }}
  .au-gtitolo::after {{ content:""; flex:1; height:1px; background:{BORDO}; }}
  /* Quattro colonne fisse e non `auto-fit`: con l'adattamento automatico
     l'ultima voce di ogni gruppo finiva da sola su una riga nuova e la
     griglia usciva sfilacciata, diversa da gruppo a gruppo. Quattro voci per
     gruppo, quattro colonne: le righe si allineano fra i gruppi. */
  .au-griglia {{ display: grid; gap: 12px 28px;
                grid-template-columns: repeat(4, minmax(0, 1fr)); }}
  .au-voce {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
  .au-etichetta {{ font-size: 10px; font-weight: 500; letter-spacing: .08em;
                  text-transform: uppercase; color: {TESTO_3}; }}
  .au-valore {{ font-family: var(--mono); font-size: 12.5px; color: {TESTO};
               font-variant-numeric: tabular-nums; line-height: 1.45;
               overflow-wrap: anywhere; }}
  /* I valori che cambieranno il risultato si distinguono dagli altri: chi
     apre i dettagli cerca proprio quelli. */
  .au-valore.au-attenzione {{ color: {GIALLO}; }}
  /* Il pannello sta più in basso del fondo della riga: è un dentro, non un
     accanto. */
  .au-testata {{ display: flex; align-items: center; justify-content: space-between;
                margin-bottom: 4px; }}
  /* Riquadro d'avviso, stesso giallo della chip sulla riga: sono la stessa
     informazione a due livelli di dettaglio, e devono somigliarsi. */
  /* La banda dell'analisi in corso stava a 49px dalla fascia sopra e a
     MENO 7 dall'intestazione sotto, che quindi le finiva addosso: il
     margine superiore di `au-avviso` si sommava a quello della fascia, e
     sotto non ce n'era nessuno (piu' il -14px di Streamlit sul contenitore
     del markdown). Qui i due lati si dichiarano insieme. */
  [class*="st-key-fasciaAnalisi"] .au-avviso {{ margin: -6px 0 32px; }}
  .au-avviso {{ display: flex; align-items: center; gap: 10px;
               background: var(--yellowBg);
               border: 1px solid rgba(242,184,75,.2);
               border-left: 3px solid var(--yellow);
               border-radius: 6px; padding: 10px 14px;
               color: {GIALLO}; font-size: 12px; line-height: 1.5;
               margin-top: 18px; }}
  /* Lo stesso disegno, in rosso: per gli avvisi che BLOCCANO un'azione
     (la GPU occupata che spegne l'Avvia). Il grigino non si notava.
     NON chiamarla `au-blocco`: quel nome è già dei gruppi del pannello
     dettagli, e la collisione li tingeva tutti di rosso (successo). */
  .au-gpu-occupata {{ display: flex; align-items: center; gap: 10px;
               background: var(--redBg);
               border: 1px solid rgba(242,109,109,.25);
               border-left: 3px solid var(--red);
               border-radius: 6px; padding: 8px 12px;
               color: var(--redText); font-size: 12.5px; line-height: 1.5;
               margin-top: 10px; }}
  /* La pausa fra due file è un riposo previsto, non un errore: giallo. */
  /* La pausa e' uno stato ordinario, non un allarme: nella fascia e' testo
     giallo e basta, con un respiro lento che dice "sta aspettando, non e'
     morto". Il riquadro resta al gemello `au-gpu-pausa`, che vive nella
     conferma di spegnimento — li' l'avviso conta davvero. */
  .au-riga-pausa {{ color: {GIALLO}; font-size: 13px; line-height: 1.5;
                   margin: 10px 0 0;
                   animation: au-respiro 2.6s ease-in-out infinite; }}
  @keyframes au-respiro {{ 0%, 100% {{ opacity: 1; }}
                          50% {{ opacity: .5; }} }}
  .st-key-barra .au-riga-pausa {{ margin-top: -9px; }}
  /* Stesso giallo della pausa, ma FERMO: il lampeggio della pausa dice
     "sta succedendo adesso", questa riga dice "attenzione a cosa parte".
     Due significati diversi non possono avere lo stesso movimento. */
  .au-riga-forse {{ color: {GIALLO}; font-size: 13px; line-height: 1.6;
                   margin: 6px 0 0; }}
  /* Il resoconto di fine coda: il numero grosso e' quanti file sono
     usciti, il resto e' contorno. */
  .au-fine-testa {{ font-size: 15px; color: {TESTO}; line-height: 1.7;
                   margin: 2px 0 0; }}
  .au-fine-quando {{ font-size: 13px; color: {TESTO_2}; line-height: 1.6;
                    margin-top: 10px; }}
  /* Le cifre in colonna: etichetta a sinistra, valore a destra, un filo di
     riga fra l'una e l'altra. Cosi' si scorrono, invece di doverle leggere
     tutte per trovarne una. */
  .au-fine-stat {{ margin: 20px 0 0; }}
  .au-fine-stat > div {{ display: flex; justify-content: space-between;
                        gap: 16px; padding: 11px 0;
                        border-top: 1px solid {BORDO}; font-size: 13px; }}
  .au-fine-stat > div > span:first-child {{ color: {TESTO}; }}
  .au-fine-stat > div > span:last-child {{ color: {TESTO_2};
                                          font-family: var(--mono); }}
  .au-fine-guai {{ font-size: 13px; color: {GIALLO}; font-weight: 600;
                  margin: 24px 0 8px; }}
  /* Il nome del file in monospazio e su fondo suo: e' un dato da leggere
     carattere per carattere, non prosa. */
  .au-fine-nome {{ font-family: var(--mono); font-size: 11.5px;
                  color: {TESTO_2}; background: var(--insetBackground);
                  border-radius: 5px; padding: 5px 9px; margin-bottom: 4px;
                  word-break: break-all; }}
  /* I due pulsanti staccati dal testo: attaccati sembravano la riga
     successiva del resoconto invece che l'azione da prendere. */
  [class*="st-key-cFineAzioni"] {{ margin-top: 22px; }}
  /* Le modali centrate anche in VERTICALE: Streamlit le ancora in alto
     (`align-items: flex-start` sul velo, che e' fisso e alto quanto la
     finestra). `safe center` e non `center`: con una modale piu' alta della
     finestra — la Taratura lo diventa — il centraggio secco ne spinge la
     testa sopra il bordo e la rende irraggiungibile, mentre `safe` in quel
     caso torna da solo all'ancoraggio in alto. */
  [data-testid="stDialog"] {{ align-items: safe center; }}

  .au-gpu-pausa {{ display: flex; align-items: center; gap: 10px;
               background: var(--yellowBg);
               border: 1px solid rgba(242,184,75,.25);
               border-left: 3px solid var(--yellow);
               border-radius: 6px; padding: 8px 12px;
               color: {GIALLO}; font-size: 12.5px; line-height: 1.5;
               margin-top: 10px; }}
  /* La fascia "Chiudi AnimeUp": ancorata al FONDO della sidebar, il
     contenuto le scorre sotto. Prima era l'ultima voce del flusso e con una
     finestra bassa finiva fuori dallo scroll: un pulsante di spegnimento
     che devi sapere che esiste non spegne niente. Lo sfondo pieno e la
     riga sopra la staccano da ciò che ci scorre dietro. */
  /* Lo sticky sta sul WRAPPER di Streamlit e non sul blocco: il blocco
     vive in un involucro alto quanto lui, e dentro un genitore su misura
     lo sticky non ha spazio per muoversi (misurato: wrapper 72px per un
     blocco da 54). Il wrapper invece galleggia nel colonnone della
     sidebar, che di spazio ne ha. */
  /* Due meccanismi insieme, perché i casi sono due: contenuto PIÙ
     CORTO della finestra -> margin-top auto spinge la fascia al fondo
     (serve la catena di flex ad altezza piena qui sotto); contenuto PIÙ
     LUNGO -> position sticky la tiene inchiodata durante lo scroll. Solo
     sticky lasciava la fascia a metà aria nelle finestre alte (visto
     dall'utente). */
  /* La colonna intera sale di 18px, misurati: e' lo scarto fra la baseline
     di "Impostazioni" e quella del marchio "AnimeUp" accanto. Si sposta il
     BLOCCO, non le singole voci: le spaziature interne sono gia' quelle
     giuste (calibrate una per una il 2026-08-09). */
  [data-testid="stSidebarUserContent"] {{ padding-bottom: 0 !important;
      margin-top: -18px;
      min-height: 100%; display: flex; flex-direction: column; }}
  [data-testid="stSidebarUserContent"] > div {{
      flex: 1; display: flex; flex-direction: column; }}
  [data-testid="stSidebarUserContent"] > div >
      [data-testid="stVerticalBlock"] {{ flex: 1; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-spegnimento) {{
      position: sticky; bottom: 0; z-index: 6; margin-top: auto;
      background: #1A1D21; border-top: 1px solid #33373D;
      padding-top: 0; }}
  /* 16px dalla linea alla CTA e 16px dalla CTA al fondo: la CTA stava a
     6px dal bordo finestra, "molto attaccata" (utente). Stesso passo della
     barra di Lavorazione. */
  .st-key-spegnimento {{ padding: 16px 0 16px; }}

  /* Le tre schede restano APPICCICATE in alto e il contenuto ci scorre
     sotto: senza, per cambiare scheda da fondo pagina si risaliva tutto
     l'elenco ("scrollare su e giù come un matto"). Sticky sul WRAPPER di
     Streamlit, non sul blocco: dentro un involucro su misura lo sticky non
     ha spazio per muoversi (stessa lezione della fascia Chiudi). Lo sfondo
     pieno copre ciò che scorre dietro. */
  /* Testata "a zero movimento": logo e schede sono sticky con `top` UGUALE
     alla loro posizione naturale a pagina in cima. Cosi' pinnate o a riposo
     stanno sempre nello stesso punto, e il reset dello scroll che Streamlit
     fa al cambio scheda non le muove di un pixel (prima la testata "saltava",
     visto dall'utente). Il logo resta sempre in vista, per scelta.
     I margini negativi + padding uguali estendono gli SFONDI (sopra, fino
     sotto la barra di Streamlit; sotto, fino alla fascia delle schede) senza
     spostare il contenuto: le due fasce contigue formano uno scudo opaco
     45px -> linea sotto le schede, e il contenuto ci scorre sotto. */
  /* Anche in ORIZZONTALE, e per la stessa ragione. Le due fasce erano larghe
     quanto la colonna del contenuto (misurati 989px) dentro un'area larga
     1.129: restavano scoperti 70px per lato, ed erano esattamente il padding
     di `stMainBlockContainer`. Il contenuto che scorreva sotto si vedeva in
     quelle due strisce, e la fascia sembrava una toppa appiccicata invece che
     una barra (visto dall'utente). Margine negativo piu' padding uguale: lo
     sfondo arriva ai bordi dell'area, il contenuto non si sposta di un pixel.
     I 70px sono il padding di Streamlit misurato in pagina, non un numero
     scelto: se un giorno cambia, la striscia torna e si rimisura. */
  [data-testid="stLayoutWrapper"]:has(> .st-key-marchio),
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{
      margin-left: -70px; margin-right: -70px;
      padding-left: 70px; padding-right: 70px;
      /* La larghezza va DICHIARATA: il wrapper e' un elemento flex e col
         solo margine negativo si sposta a sinistra senza allargarsi —
         misurato, restava a 989px e scopriva 140px a destra invece di 70
         per lato. E si scrive `min-width`, non `width`: Streamlit fissa la
         larghezza di questi involucri e vince (provato in pagina: con
         `width` restava 989, con `min-width` arriva a 1.129, cioe' l'area
         intera). */
      min-width: calc(100% + 140px);
      /* ...e il resto lo fanno due OMBRE laterali. Il margine di -70px
         bastava su una finestra stretta, dove il padding di
         `stMainBlockContainer` vale esattamente 70px per lato. Su una
         finestra larga Streamlit CENTRA il contenuto con un massimo, e
         l'avanzo diventa un altro numero: misurato a 1920px, restavano
         scoperti 105px a sinistra e 115 a destra (segnalato dall'utente).
         Un margine fisso non puo' seguirlo.
         Ombre e non margini perche' le ombre NON entrano nel calcolo
         dell'area scorribile: `stMain` ha `overflow-x: auto`, e qualunque
         sbordatura vera (margini negativi, `100vw`) gli farebbe comparire
         una barra orizzontale. L'ombra invece viene semplicemente tagliata
         al bordo di `stMain`, che e' esattamente dove deve fermarsi. */
      box-shadow: -400px 0 0 0 #101113, 400px 0 0 0 #101113; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-marchio) {{
      position: sticky; top: 45px; z-index: 26; background: #101113;
      margin-top: -17px; margin-bottom: -14px;
      padding-top: 17px; padding-bottom: 14px; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{
      position: sticky; top: 45px; z-index: 25;
      background: #101113; padding-top: 16px; padding-bottom: 0;
      /* La linea sotto le schede: qui e non su `.st-key-fasi`, perche' qui
         la larghezza e' quella dell'area intera. Vedi il commento accanto
         al blocco. */
      /* La linea NON e' un `border-bottom`: un bordo si ferma al box, e il
         box e' largo quanto il contenuto. E' un elemento suo, allargato
         dalle stesse ombre dello sfondo.
         NIENTE `position: relative` qui: la riga sopra dice gia' `sticky`,
         che e' anch'essa una posizione e fa da contenitore all'elemento
         assoluto. Dichiarare `relative` piu' in basso SOVRASCRIVE `sticky`
         e la testata smette di restare in cima — introdotto e corretto il
         12/08, notato dall'utente in dieci secondi. */
      box-shadow: -400px 0 0 0 #101113, 400px 0 0 0 #101113,
                  0 6px 12px -8px rgba(0, 0, 0, .6); }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi)::after {{
      content: ""; position: absolute; left: 0; right: 0; bottom: -1px;
      height: 1px; background: {BORDO}; pointer-events: none;
      box-shadow: -400px 0 0 0 {BORDO}, 400px 0 0 0 {BORDO}; }}
  [data-testid="stHeader"] {{ background: #101113 !important; }}

  /* Fuori dal programma della catena: la riga si spegne del tutto —
     saturazione zero, alpha basso, niente interazioni. Durante la maratona
     quei file sono scenografia, e devono sembrarlo (chiesto dall'utente,
     con tanto di valori: "saturation 0% e alpha 40%"). */
  [class*="st-key-jrow"]:has(.au-fuori) {{
      filter: saturate(0); opacity: .4; pointer-events: none; }}
  /* La casella-indicatore delle righe durante la catena: stessa geometria
     della vera (18px), spuntata fissa per i membri del lancio. Non è un
     widget e non finge di esserlo: niente hover, niente cursore. */
  .au-cb-finta {{ display: inline-block; width: 18px; height: 18px;
      border-radius: 4px; border: 1px solid {BORDO_VIVO};
      background: var(--insetBackground); vertical-align: middle; }}
  /* Spuntata ma con l'aria DISATTIVATA: in scala di GRIGIO, il classico
     aspetto spento — il ciano, anche semitrasparente, invitava ancora a
     de-spuntare (detto dall'utente due volte, la seconda con le specifiche:
     "scala di grigio e un po' trasparente"). */
  .au-cb-finta.au-cb-si {{ background: rgba(138, 144, 153, .25);
      border-color: rgba(138, 144, 153, .40); position: relative; }}
  .au-cb-finta.au-cb-si::after {{ content: ''; position: absolute;
      left: 5px; top: 1px; width: 5px; height: 10px;
      border: solid rgba(183, 188, 195, .70); border-width: 0 2px 2px 0;
      transform: rotate(45deg); }}

  /* Le colonne della PAGELLA non sono la testata della riga: si disfano le
     sue regole — niente colonna-casella fissa a 32px (strozzava "Esito" a
     lettere in verticale) e niente padding da testata (disallineava dagli
     altri gruppi del pannello). */
  [class*="st-key-pagella"] [data-testid="stHorizontalBlock"] {{
      padding: 0; align-items: flex-start; }}
  [class*="st-key-pagella"] [data-testid="stHorizontalBlock"]
      > [data-testid="stColumn"]:first-child {{
      flex: 1 1 calc(25% - 1rem) !important; min-width: 0 !important; }}
  /* "OUTPUT · apri" è un LINK travestito, non una CTA: da pulsante vero
     sballava la griglia (font suo, aria sopra, cornice — visto dall'utente
     nello screenshot). Resta un pulsante Streamlit perché deve eseguire
     `open -R` lato server, ma si veste ESATTAMENTE da .au-valore:
     mono 12.5px, bianco, sottolineato, zero cornice, zero spazio extra. */
  [class*="st-key-pagella"] .stButton {{ margin-top: -14px; }}
  [class*="st-key-pagella"] .stButton button {{
      background: transparent !important; border: none !important;
      padding: 0 !important; height: auto !important;
      min-height: 0 !important; box-shadow: none !important;
      justify-content: flex-start; }}
  [class*="st-key-pagella"] .stButton button p {{
      font-family: var(--mono); font-size: 12.5px; color: {TESTO} !important;
      line-height: 1.45; text-decoration: underline;
      text-underline-offset: 3px; }}
  [class*="st-key-pagella"] .stButton button:hover p {{
      color: var(--primary) !important; }}

  /* La zona sotto "Elabora gli spezzoni": esiste GIA' da vuota, con
     l'altezza che poi serve alla barra di avanzamento e al banner "pronto".
     Così il click non sposta la pagina e l'avanzamento nasce dove stanno
     gli occhi, non sotto la piega. */
  .st-key-zonaEsito {{ min-height: 72px; }}

  /* Lo stato della catena ("file 5 di 8..."): ciano come tutto ciò che è
     attivo. Testo un gradino più chiaro del primario, per leggersi sul
     fondo scuro (fratello di linkColor). */
  /* Titolo e sottotitolo sono una coppia: il margine negativo annulla lo
     spazio che Streamlit lascia sotto il paragrafo del titolo. */
  .au-coda-dettaglio {{ font-size: 12px; color: {TESTO_3};
                       margin: -13px 0 0; }}
  /* La terza riga e' l'informazione principale, e per esserlo non ha
     bisogno di un riquadro: testo bianco, staccato quel tanto che basta
     dalla coppia titolo/sottotitolo. I riquadri colorati restano per cio'
     che deve DAVVERO farsi notare (avvisi, pause, errori) — se li porta
     anche l'ordinaria amministrazione non li guarda piu' nessuno.
     Niente `nowrap`: qui non passa piu' il nome del file (era lui a
     chiedere il taglio con i puntini) e troncare il tempo rimanente
     sarebbe nascondere proprio cio' che si sta cercando. */
  .au-catena {{ display: block; margin: 10px 0 0;
               color: {TESTO}; font-size: 13px; line-height: 1.5; }}
  .au-catena .au-eti {{ color: {TESTO}; }}
  .au-catena .au-val {{ color: {TESTO_2}; }}
  .au-catena b {{ font-weight: 600; }}
  /* `inline-block` + `vertical-align` non bastavano: la rotellina sedeva
     sulla linea di base e risultava più alta del testo accanto. Dentro un
     contenitore flex che allinea al centro, si allinea davvero. */
  .au-rotella {{ width: .72rem; height: .72rem; border-radius: 50%; flex: none;
                border: 2px solid rgba(150,150,150,.3);
                border-top-color: rgba(190,190,190,.95);
                animation: au-gira .7s linear infinite; }}
  @keyframes au-gira {{ to {{ transform: rotate(360deg); }} }}
  @media (prefers-reduced-motion: reduce) {{
    .au-rotella {{ animation: none; border-top-color: rgba(150,150,150,.3); }}
  }}

  /* --- animazioni ------------------------------------------------------
     Tenute brevi di proposito: Streamlit ridisegna il DOM a ogni
     interazione, quindi qualunque animazione d'ingresso si ripete a ogni
     clic. Sotto i 200 ms si legge come reattivita'; più lunga diventa
     fastidiosa. Chi ha attivato la riduzione del movimento non le vede. */
  @keyframes au-sale {{ from {{ transform: translateY(100%); opacity: 0; }}
                       to   {{ transform: translateY(0);    opacity: 1; }} }}
  /* Si anima SOLO opacità e posizione. Con `max-height` in animazione serve
     `overflow: hidden`, e un pannello più alto del limite veniva tagliato:
     40rem non bastavano per tre gruppi di dettagli. Un'animazione non deve
     poter nascondere contenuto. */
  /* `0fr` -> `1fr` anima l'altezza VERA senza doverla sapere in anticipo, ed
     è il motivo per cui non si usa `max-height`: quella va indovinata, e col
     tetto sbagliato il pannello finisce di comparire nei primi 70ms — cioè
     lo scatto che si voleva togliere. Qui il contenuto è un figlio solo
     (vedi il container annidato in `_riga`), quindi la traccia è una sola.
     A pannello aperto la traccia vale quanto il contenuto, quindi
     l'`overflow: hidden` che serve durante la transizione non può nascondere
     niente — l'errore già fatto una volta con `max-height`. */

  .st-key-barra {{ animation: au-sale .18s cubic-bezier(.22,.61,.36,1); }}

  /* Ogni riga è una scheda, sempre: chiusa o aperta. Il bordo trasparente
     evitava lo spostamento ma lasciava l'elenco senza struttura, e aprendo
     una riga il riquadro sembrava comparire dal nulla. Ora c'e' e basta:
     aprendo cambia solo l'intensita', non la presenza. */
  [class*="st-key-riga"] {{
      background: var(--surface);
      border: 1px solid {BORDO};
      border-left: 3px solid var(--idleEdge);
      border-radius: 8px;
      /* Nessuna spaziatura sulla riga: la mettono la testata e il pannello,
         ciascuno la sua. Con la spaziatura qui, il pannello per arrivare ai
         bordi doveva uscirne con margini negativi — e da figlio flex la sua
         larghezza veniva decisa dal contenitore, quindi il margine destro non
         aveva effetto e restavano 33px scoperti. Provato con `width: auto` e
         con `calc(100% + 32px)`: nessuno dei due vince sul flex. */
      padding: 0;
      margin: 0;
      transition: background-color .18s ease, border-color .18s ease,
                  box-shadow .3s ease, transform .3s ease; }}
  /* Il bordo sinistro porta lo stato. Streamlit trasforma la chiave del
     contenitore in una classe, quindi lo stato viaggia nella chiave: è il
     solo modo di far arrivare un dato al CSS senza avvolgere i widget in
     markup nostro, cosa che Streamlit non consente. */
  /* Il segno di stato non si vede: serve solo al selettore. */
  .au-stato {{ display: none; }}
  [class*="st-key-riga"]:has(.au-s-corso)  {{ border-left-color: var(--primary); }}
  [class*="st-key-riga"]:has(.au-s-fatto)  {{ border-left-color: var(--green); }}
  [class*="st-key-riga"]:has(.au-s-avviso) {{ border-left-color: var(--yellow); }}
  /* In coda il contenuto si attenua: c'e', ma non compete con le righe che
     hanno qualcosa da dire. */
  [class*="st-key-riga"]:has(.au-s-coda) .au-name,
  [class*="st-key-riga"]:has(.au-s-coda) .au-cell {{ opacity: .72; }}
  /* Riga aperta = riga che contiene un pannello. Prima era una chiave
     diversa, ed era l'altra metà del problema dei doppioni. */
  /* Come per il passaggio del mouse: `border-color` avrebbe riscritto anche
     il lato sinistro, cancellando il colore dello stato sulla riga aperta. */
  [class*="st-key-riga"]:has(.au-open) {{
      background: rgba(255,255,255,.03);
      border-top-color: {BORDO_VIVO}; border-right-color: {BORDO_VIVO};
      border-bottom-color: {BORDO_VIVO}; }}

  /* Riga aperta: riga e dettagli diventano UNA scheda sola, con un bordo che
     dice dove comincia e dove finisce. Niente scatola dentro la scatola: il
     pannello interno è separato da una riga, non da un secondo riquadro. */

  /* La testata del pannello (titolo + Rianalizza) ereditava il padding
     11x16 delle righe: il titolo partiva 16px piu' a destra delle sezioni
     sotto (visto dall'utente). Qui dentro lo spazio lo da' il pannello. */
  /* Tre selettori: deve VINCERE sulla regola generale delle righe
     (11px 16px), che ha pari specificita' e viene dopo nel foglio. */
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stHorizontalBlock"],
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stHorizontalBlock"] {{ padding: 0; }}
  /* Tutta la catena di involucri di Streamlit deve allinearsi a destra,
     come nella barra di Lavorazione (stessa ricetta): fermarsi alla
     colonna lasciava il pulsante a bandiera dentro gli involucri interni. */
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton),
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) [data-testid="stVerticalBlock"],
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) [data-testid="stElementContainer"],
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) .stButton,
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton),
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) [data-testid="stVerticalBlock"],
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) [data-testid="stElementContainer"],
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) .stButton {{
      display: flex !important; justify-content: flex-end;
      align-items: flex-end; flex-direction: column; width: 100%; }}
  /* ...ma NON nella pagella del file concluso: li' la cella "Cartella"
     ha un pulsante e finiva bandierata a destra insieme alla sua
     etichetta, mentre e' una voce come le altre e va incolonnata a
     sinistra con loro (visto dall'utente il 2026-08-10). Si cambia solo
     l'allineamento: il `display` resta quello di Streamlit, o il blocco
     verticale perde la sua struttura. */
  [class*="st-key-pagella"] [data-testid="stColumn"],
  [class*="st-key-pagella"] [data-testid="stColumn"]
      [data-testid="stVerticalBlock"],
  [class*="st-key-pagella"] [data-testid="stColumn"]
      [data-testid="stElementContainer"],
  [class*="st-key-pagella"] [data-testid="stColumn"] .stButton {{
      justify-content: flex-start !important;
      align-items: flex-start !important; }}
  [class*="st-key-riga"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) .stButton > button,
  [class*="st-key-jrow"] [class*="st-key-dett"]
      [data-testid="stColumn"]:has(.stButton) .stButton > button {{
      flex: 0 0 auto; width: auto; }}
  /* Un gradino sopra gli eyebrow di sezione (TEMPI, IMMAGINE): e' il
     titolo del pannello intero. */
  .au-pan-titolo {{ font-size: 12px; font-weight: 600;
                   letter-spacing: .1em; text-transform: uppercase;
                   color: {TESTO_2}; padding-top: 6px; }}
  [class*="st-key-dett"] {{
      /* La colonna va dichiarata quanto le righe. Con le sole righe la
         colonna implicita è `auto`, quindi si dimensiona sul contenuto: il
         figlio misurava 1014px dentro un pannello da 1256, e il `width: 100%`
         qui sotto era il 100% di quella colonna stretta, non del pannello.
         È il vero motivo del buco a destra — tutto figlio del trucco
         `0fr -> 1fr` usato per animare l'apertura. */
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      /* `transition` e non `animation`: un'animazione parte solo quando
         l'elemento compare, quindi valeva per l'apertura e non per la
         chiusura — che infatti si spegneva di colpo. Il pannello ora resta
         montato e la traccia passa da `0fr` a `1fr`: la transizione vale in
         tutti e due i versi. */
      grid-template-rows: 0fr; overflow: hidden;
      /* Il padding sinistro è IDENTICO a quello dello stato aperto (21px
         qui, 62 in Lavorazione, più sotto): era nella transizione insieme
         al resto, e durante l'apertura il contenuto scivolava di lato.
         Deve animarsi solo l'altezza. */
      opacity: 0; padding: 0 24px 0 21px; border-top-color: transparent;
      transition: grid-template-rows .22s cubic-bezier(.4,0,.2,1),
                  opacity .18s ease, padding .22s ease,
                  border-top-color .22s ease;
      background: var(--insetBackground);
      border-top: 1px solid transparent;
      border-radius: 0 0 6px 6px; }}
  /* Aperto: la traccia prende l'altezza del contenuto e tornano spaziatura,
     opacità e linea di separazione. */
  [class*="st-key-riga"]:has(.au-open) [class*="st-key-dett"],
  [class*="st-key-jrow"]:has(.au-open) [class*="st-key-dett"] {{
      grid-template-rows: 1fr; opacity: 1;
      /* 26/30 e non 18/22: il contenuto stava troppo appiccicato ai bordi
         del pannello. Cambia solo il respiro ESTERNO — le distanze fra le
         voci dentro restano quelle. */
      padding: 26px 24px 30px 21px; border-top-color: {BORDO}; }}
  /* Il pannello NON prende il gradiente: la velatura colorata resta alla
     fascia del titolo, che e' quella che deve dire lo stato a colpo
     d'occhio. Ripeterla anche nel dettaglio la sbiadiva. */
  /* SOLO in Lavorazione (dettlav, che il selettore sopra intercetta perché
     "dett" ne è un prefisso): il contenuto del pannello si incolonna col
     titolo della testata, che qui sta 46px dentro per via della casella.
     Nei Sorgenti la testata parte prima e i 21px vanno già bene. */
  [class*="st-key-jrow"]:has(.au-open) [class*="st-key-dettlav"] {{
      padding-left: 62px; }}
  /* Lo stesso 62 anche da CHIUSO, o il contenuto scivola da 21 a 62 durante
     l'apertura (il glitch "verso l'interno" visto dall'utente). */
  [class*="st-key-jrow"] [class*="st-key-dettlav"] {{ padding-left: 62px; }}
  /* Senza `width: 100%` il contenitore annidato si stringe al contenuto e il
     pannello resta corto a destra: il genitore non lo stira (misurato: figlio
     1014px dentro un pannello da 1256). È lo stesso contenitore che serve
     all'animazione, quindi non si può togliere — gli si dichiara la
     larghezza. */
  [class*="st-key-dett"] > [data-testid="stLayoutWrapper"] {{
      width: 100% !important; }}
  /* `min-height:0` o la traccia non scende mai sotto il contenuto e `0fr` non
     ha alcun effetto: è la metà del trucco che di solito manca. */
  [class*="st-key-dett"] > div {{ min-height: 0; }}

  /* le righe rispondono al passaggio del mouse: aiuta a seguire la riga
     giusta su elenchi lunghi */
  /* Le colonne di Streamlit hanno `align-items: stretch`: prendono l'altezza
     del blocco, e quello che eccede ESCE dal riquadro invece di allargarlo.
     È il motivo per cui la chip "1 avviso" e il sottotitolo sotto un nome su
     due righe sbordavano: non era la spaziatura, era l'altezza bloccata.
     Misurato: colonna 70px, contenuto 86px. */
  /* `center` e non `flex-start`: le due icone devono stare a metà altezza
     del contenuto, non appese in cima. Si può fare solo ora che il margine
     negativo qui sotto è neutralizzato — prima `center` avrebbe fatto
     sbordare tutto. */
  [class*="st-key-riga"] > div > div > [data-testid="stHorizontalBlock"],
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] {{
      align-items: center; }}
  /* La spaziatura della testata, che prima stava sulla riga. */
  [class*="st-key-riga"] > [data-testid="stVerticalBlock"]
      > [data-testid="stElementContainer"],
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] {{
      padding-left: 16px; padding-right: 16px; }}
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] {{
      padding-top: 11px; padding-bottom: 11px; }}
  [class*="st-key-riga"] [data-testid="stColumn"] {{ height: auto !important; }}
  /* Streamlit mette `margin-bottom: -16px` sul contenitore del markdown per
     compattare gli elementi. Dentro una riga incorniciata quel margine è
     veleno: il contenuto è alto 86px, il genitore ne dichiara 70, e i 16px
     di differenza escono dal riquadro. È la causa comune della chip che
     sbordava e del sottotitolo tagliato — non la spaziatura, come avevo
     creduto due volte. */
  /* Ristretta alla TESTATA della riga. Applicata a tutta la riga schiacciava
     anche i margini del pannello dei dettagli, e i titoli di gruppo finivano
     incollati alle loro etichette: si leggeva "TEMPI FRAMERATE" come una
     stringa sola. Il margine negativo di Streamlit sta nelle colonne della
     testata, ed è lì che va neutralizzato. */
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] .stMarkdown div {{
      margin-bottom: 0 !important; }}
  /* Stessa storia dentro il pannello, dove il margine negativo vale -14px:
     lo spazio in fondo c'era (22px dichiarati e misurati sotto il contenitore)
     ma il contenuto ne usciva, e ne restavano 8 visibili. Si mira al solo
     `stMarkdownContainer` e non a tutti i div, o si schiacciano di nuovo i
     margini dei titoli di gruppo. */
  [class*="st-key-dett"] [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}

  /* L'evidenziazione sta sulla RIGA, non sul blocco interno: sul blocco
     lasciava scoperta la spaziatura della riga, e il rettangolo colorato
     risultava più piccolo del riquadro. */
  /* `border-color` da solo riscriveva anche il lato sinistro, cancellando il
     colore dello stato proprio quando ci passi sopra. Si toccano i tre lati
     che devono cambiare. */
  [class*="st-key-riga"]:has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{ background: var(--surfaceHover);
      border-top-color: {BORDO_VIVO}; border-right-color: {BORDO_VIVO};
      border-bottom-color: {BORDO_VIVO}; }}

  .stButton button {{ transition: transform .1s ease, border-color .12s ease; }}
  /* Sul ciano il testo è scuro, mai bianco: è scritto nello spec e si vede
     perché il ciano è chiaro — bianco su ciano non ha contrasto. */
  .stButton button[kind="primary"] {{
      background: var(--primary) !important; border-color: var(--primary) !important; }}
  .stButton button[kind="primary"] p {{
      color: var(--onPrimary) !important; font-weight: 600; }}
  .stButton button[kind="primary"]:hover {{
      background: var(--primaryHover) !important;
      border-color: var(--primaryHover) !important; }}
  .stButton button[kind="primary"]:active {{ background: var(--primaryActive) !important; }}
  /* Disabilitato DEVE vedersi: il ciano forzato con !important qui sopra
     vinceva anche sullo stato spento di Streamlit, e "Avvia" da disattivato
     era identico a quando è cliccabile — l'utente non ha modo di capire
     che non rispondera'. */
  .stButton button[kind="primary"]:disabled,
  .stButton button[kind="primary"]:disabled:hover {{
      background: var(--idleEdge) !important;
      border-color: var(--idleEdge) !important;
      cursor: not-allowed; transform: none; }}
  .stButton button[kind="primary"]:disabled p {{
      color: {TESTO_3} !important; }}
  /* Le icone dentro i pulsanti: erano alla dimensione del testo, cioè
     illeggibili. `au-icona` le porta a una misura da icona vera. */
  .au-icona {{ font-size: 1.15rem; line-height: 1; vertical-align: -.08em; }}
  /* Streamlit non accetta markup nell'etichetta di un pulsante, quindi le
     icone si ingrandiscono da CSS. Erano alla dimensione del testo, cioè
     quasi invisibili. Si mira alla CHIAVE del pulsante e non al contenitore:
     mirando al contenitore diventava grande anche la parola "Dettagli". */

  /* Ferma: rosso, perché interrompe — ma in bordo e testo, non pieno: il
     pulsante convive con la riga senza urlare. La CONFERMA invece si riempie:
     a quel punto il rosso deve pesare, sta per succedere davvero. */
  [class*="st-key-ferma"] button,
  [class*="st-key-scarta"] button {{
      border-color: rgba(242, 109, 109, .45) !important;
      /* Nemmeno il fondo scuro predefinito: dentro una riga colorata era
         una toppa grigia. Il bordo rosso basta a farlo riconoscere. */
      background: transparent !important; }}
  [class*="st-key-ferma"] button p,
  [class*="st-key-scarta"] button p {{ color: var(--red) !important; }}
  [class*="st-key-ferma"] button:hover,
  [class*="st-key-scarta"] button:hover {{
      border-color: var(--red) !important;
      background: rgba(242, 109, 109, .08) !important; }}
  [class*="st-key-fermasi"] button,
  [class*="st-key-scartasi"] button {{
      background: var(--red) !important;
      border-color: var(--red) !important; }}
  [class*="st-key-fermasi"] button p,
  [class*="st-key-scartasi"] button p {{
      color: #2A0F0F !important; font-weight: 600; }}
  [class*="st-key-fermasi"] button:hover,
  [class*="st-key-scartasi"] button:hover {{
      background: #F58585 !important; border-color: #F58585 !important; }}

  /* PAUSA: azzurro, non rosso. Ferma e' un'azione che costa lavoro — il
     blocco riparte da capo — e il rosso lo dice. La pausa non costa niente
     ed e' reversibile, quindi porta il colore dell'app.
     Aspetto SECONDARIO (solo bordo) quando invita a sospendere, PRIMARIO
     (pieno) quando invita a riprendere: la ripresa e' l'azione che si vuole
     rendere ovvia quando la macchina e' ferma. Scelta dell'utente, 11/08. */
  /* I due pulsanti della fascia IN FILA, stretti e a filo destro.
     Stanno nella stessa colonna, quindi Streamlit li impilerebbe: qui il
     blocco verticale che li contiene diventa una riga.
     Due cose imparate a caro prezzo, che restano scritte perche' torneranno:
     1) con un `help=` Streamlit avvolge il pulsante in un div e due span,
        quindi ogni regola scritta con `.stButton > button` NON matcha mai —
        comprese quelle gia' nel foglio da prima;
     2) `width: 100%` sul solo pulsante vale il 100% di quel wrapper da 81px,
        cioe' niente. O si allarga tutta la catena, o non si tocca la
        larghezza affatto — che e' la strada scelta qui: larghezza naturale,
        con un minimo perche' i due si leggano come una coppia. */
  .st-key-barra [data-testid="stColumn"]:has([class*="st-key-pausa_tutto"])
      > [data-testid="stVerticalBlock"],
  .st-key-barra [data-testid="stColumn"]:has([class*="st-key-riprendi_tutto"])
      > [data-testid="stVerticalBlock"] {{
      flex-direction: row !important; justify-content: flex-end !important;
      align-items: center !important; gap: 8px !important; width: 100%; }}
  .st-key-barra [class*="st-key-pausa_tutto"],
  .st-key-barra [class*="st-key-riprendi_tutto"],
  .st-key-barra [class*="st-key-ferma_tutto"],
  .st-key-barra [class*="st-key-fermasi_tutto"] {{
      width: auto !important; flex: 0 0 auto !important; }}
  .st-key-barra [class*="st-key-pausa_tutto"] .stButton button,
  .st-key-barra [class*="st-key-riprendi_tutto"] .stButton button,
  .st-key-barra [class*="st-key-ferma_tutto"] .stButton button,
  .st-key-barra [class*="st-key-fermasi_tutto"] .stButton button {{
      /* 132px: la piu' larga delle due («Ferma tutto») ne chiede 112 col
         carattere e i margini. Uguali, perche' sono azioni dello stesso
         rango e larghezze diverse le farebbero leggere come pesi diversi. */
      min-width: 132px !important; width: auto !important; }}

  [class*="st-key-pausa_tutto"] button {{
      border-color: rgba(42, 201, 222, .45) !important;
      background: transparent !important; }}
  [class*="st-key-pausa_tutto"] button p {{ color: {CIANO} !important; }}
  [class*="st-key-pausa_tutto"] button:hover {{
      border-color: {CIANO} !important;
      background: rgba(42, 201, 222, .08) !important; }}

  /* La chevron non è una chiamata all'azione: è l'indicatore di un
     accordion. Niente cornice, niente sfondo — solo il triangolo, che si
     accende al passaggio insieme al resto della riga. */
  /* Chevron spenta (file non ancora analizzato): invisibile e sorda, ma
     nel DOM — l'accordion senza referto non apre niente e mostrarla era
     una promessa a vuoto (detto dall'utente). */
  [class*="st-key-det"]:not([class*="st-key-dett"]) button:disabled {{
      opacity: 0 !important; pointer-events: none; }}
  /* NIENTE position sul pulsante: l'overlay qui sotto deve ancorarsi alla
     RIGA (il primo antenato posizionato), non al pulsante stesso. */
  [class*="st-key-det"]:not([class*="st-key-dett"]) button {{ border: none !important;
      background: transparent !important; box-shadow: none !important; }}
  /* La zona sensibile del pulsante si allunga a coprire tutta la testata:
     cliccare sul nome del file apre e chiude come cliccare sulla freccia.
     È un'estensione invisibile dell'area del pulsante, non un secondo
     elemento cliccabile — così non c'e' niente da tenere in sincronia.
     ANCORATA AI BORDI VERI della riga (position:relative sulla riga +
     inset:0): il vecchio `left:-2000px` sbordava dal riquadro e mouseover
     e click funzionavano nel vuoto ai lati (visto dall'utente). */
  /* L'ancora dell'overlay e' la TESTATA (il blocco orizzontale che
     contiene la chevron), non la riga intera: ancorato alla riga copriva
     anche il pannello aperto, e passandoci sopra il cursore prometteva
     un'apertura che era una chiusura (visto dall'utente). */
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"]:has(
      [class*="st-key-det"]:not([class*="st-key-dett"])),
  [class*="st-key-jrow"] [data-testid="stHorizontalBlock"]:has(
      [class*="st-key-det"]:not([class*="st-key-dett"])) {{
      position: relative; }}
  [class*="st-key-riga"] [class*="st-key-det"]:not([class*="st-key-dett"])
      button::after,
  [class*="st-key-jrow"] [class*="st-key-det"]:not([class*="st-key-dett"])
      button::after {{
      content: ""; position: absolute; inset: 0; }}
  /* In Lavorazione la testata ospita anche comandi veri: stanno SOPRA
     l'overlay (z-index), così checkbox, tendina del modello e pulsanti
     (Riprendi/Scarta/Ferma) rispondono ai loro click e tutto il resto
     della riga apre e chiude la tendina. Il pannello aperto viene dopo
     la chevron nel DOM, quindi galleggia gia' sopra l'overlay da solo
     (stessa ragione per cui in Sorgenti "Rianalizza" funziona). */
  [class*="st-key-jrow"] [data-testid="stCheckbox"],
  [class*="st-key-jrow"] [data-testid="stSelectbox"],
  /* Anche i suggerimenti: la lastra li copriva e il fumetto non compariva
     MAI nelle righe (visto dall'utente). Il click sulla riga continua a
     funzionare dappertutto tranne che sui 14px dell'icona, che e' proprio
     quello che si vuole. */
  [class*="st-key-jrow"] .au-info,
  [class*="st-key-jrow"] [data-testid="stColumn"]:not(
      :has([class*="st-key-det"])) .stButton {{
      position: relative; z-index: 2; }}
  /* Le chip stanno sopra anche loro, ed e' una scelta con un prezzo: sono
     larghe quanto la loro etichetta ("fatto", "2 avvisi", "parametri suoi"),
     quindi su quei ~50px il click non apre piu' la riga. Si tiene cosi'
     perche' il fumetto della chip e' l'unico posto dove si leggono gli
     avvisi di quella lavorazione, mentre per aprire la riga restano il nome
     — larghissimo — e la freccia. Il prezzo e' un bersaglio piccolo che non
     risponde; il guadagno e' un'informazione che altrimenti non si vede.
     (Rilievo dell'audit del 2026-08-10, valutato e accettato.) */
  [class*="st-key-jrow"] .au-perche {{
      position: relative; z-index: 2; }}
  /* Il `z-index: 2` qui sopra apre un contesto di impilamento sull'icona:
     dentro, il 220 del fumetto vale solo verso i fratelli, e le righe che
     vengono DOPO nel DOM gli finivano davanti. Ad aprire il fumetto sale
     l'icona intera, che e' il contesto. Va scritta qui e non accanto alle
     altre regole del fumetto: a pari specificita' vince l'ultima, e quella
     delle righe viene dopo. */
  [class*="st-key-jrow"] .au-info:hover,
  [class*="st-key-jrow"] .au-info:focus-within,
  [class*="st-key-jrow"] .au-perche:hover,
  [class*="st-key-jrow"] .au-perche:focus-within {{ z-index: 240; }}
  /* La colonna della chevron NON entra nell'esclusione qui sopra, e il suo
     contenitore resta STATICO: qualunque antenato posizionato fra pulsante
     e riga si ruberebbe l'ancora dell'overlay, che deve essere la riga
     (successo: overlay largo quanto la sola freccia). */
  [class*="st-key-riga"] [class*="st-key-det"]:not([class*="st-key-dett"]),
  [class*="st-key-riga"] [class*="st-key-det"]:not([class*="st-key-dett"])
      .stButton,
  [class*="st-key-jrow"] [class*="st-key-det"]:not([class*="st-key-dett"]),
  [class*="st-key-jrow"] [class*="st-key-det"]:not([class*="st-key-dett"])
      .stButton {{ position: static !important; }}
  /* E NIENTE transform, in nessuno stato: alla pressione i pulsanti hanno
     l'effetto "schiacciato" (scale), ma una transform diventa containing
     block e l'overlay si ri-ancora al bottone COLLASSANDO a meta' click —
     il mouseup cadeva fuori e il click non arrivava mai (elementFromPoint
     diceva che era tutto a posto perche' senza pressione la transform non
     c'era: caso da manuale di verifica che mente). */
  [class*="st-key-riga"] [class*="st-key-det"]:not([class*="st-key-dett"])
      button,
  [class*="st-key-jrow"] [class*="st-key-det"]:not([class*="st-key-dett"])
      button {{ transform: none !important; }}
  [class*="st-key-det"]:not([class*="st-key-dett"]) button
      [data-testid="stIconMaterial"] {{
      font-size: 2.2rem; line-height: 1; color: {TESTO_3};
      transition: color .12s ease; }}
  [class*="st-key-riga"]:has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) [class*="st-key-det"]:not([class*="st-key-dett"])
      button [data-testid="stIconMaterial"],
  [class*="st-key-jrow"]:has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) [class*="st-key-det"]:not([class*="st-key-dett"])
      button [data-testid="stIconMaterial"] {{ color: {TESTO}; }}
  /* "Rianalizza" ora vive dentro il pannello ed è un secondario vero, con la
     sua parola: fuori era un simbolo accanto alla chevron, e due icone
     affiancate si contendevano l'attenzione. */
  [class*="st-key-ric"] button {{
      border: 1px solid {BORDO_VIVO} !important;
      background: none !important; box-shadow: none !important;
      padding: 8px 18px !important; }}
  /* L'icona nativa di Streamlit e non il carattere "⟳": quello a 12px è un
     ghirigoro illeggibile, questa è un'icona disegnata per essere piccola. */
  [class*="st-key-ric"] button [data-testid="stIconMaterial"] {{
      font-size: 16px; color: var(--textSecondary); }}
  [class*="st-key-ric"] button p {{
      font-size: 12.5px; font-weight: 500;
      color: var(--codeTextColor, #C6CBD2); transition: color .12s ease; }}
  /* L'HOVER STANDARD delle CTA secondarie: identico ovunque (chiesto
     dall'utente: "Seleziona tutti" brillava ciano, "Rianalizza" appena).
     Un filo piu' visibile del vecchio Rianalizza, meno del ciano di
     Streamlit. La famiglia rossa, le chevron e i pulsanti-link restano
     fuori: hanno il loro carattere. */
  [data-testid="stElementContainer"]:not([class*="st-key-ferma"]):not(
      [class*="st-key-scarta"]):not([class*="st-key-det"]):not(
      [class*="st-key-finder"]) .stButton button[kind="secondary"]:hover {{
      background: #22262C !important;
      border-color: #40454C !important; }}
  [data-testid="stElementContainer"]:not([class*="st-key-ferma"]):not(
      [class*="st-key-scarta"]):not([class*="st-key-det"]):not(
      [class*="st-key-finder"]) .stButton
      button[kind="secondary"]:hover p {{ color: {TESTO} !important; }}
  .stButton button:active {{ transform: scale(.97); }}

  @media (prefers-reduced-motion: reduce) {{
    .st-key-barra {{ animation: none; }}
    [class*="st-key-dett"] {{ transition: none; }}
    [data-testid="stHorizontalBlock"], .stButton button {{ transition: none; }}
  }}

</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


# ===========================================================================
#  Dati
# ===========================================================================

# UN solo decoratore. Ce n'erano due impilati, 30 secondi sopra 8: quello
# esterno catturava il risultato di quello interno, quindi il TTL vero era 30
# e un file appena messo in INPUT poteva farsi aspettare quattro volte il
# tempo dichiarato qui sotto.
@st.cache_data(ttl=8, show_spinner=False)
def load_library() -> list[dict]:
    """Solo metadati: deve essere istantaneo anche su una serie intera.

    In cache per 8 secondi. La scansione costa 0.37s su sedici file, e veniva
    rifatta a OGNI rerun: aprire una tendina ne fa uno, e quei 0.37s erano la
    parte grossa dell'attesa. Otto secondi perché un file nuovo in INPUT deve
    comunque comparire da solo, senza ricaricare la pagina.
    """
    return [
        {
            "path": str(e.path), "name": e.name, "resolution": e.resolution,
            "width": e.width, "height": e.height, "duration": e.duration_hms,
            "size_mb": e.size_mb, "codec": e.codec,
        }
        for e in library.scan()
    ]


# ===========================================================================
#  Analisi in sottofondo
# ===========================================================================

class Analizzatore:
    """Analizza i sorgenti mentre l'utente guarda l'elenco.

    L'analisi costa una ventina di secondi a file: chiedere all'utente di
    premere un pulsante e aspettare, file per file, era tempo suo speso a
    guardare una rotellina. Parte da sola all'apertura e procede in ordine,
    uno alla volta.

    UNO alla volta di proposito: ogni analisi decodifica il video per intero,
    quindi due insieme si contendono disco e CPU senza finire prima. E il
    risultato finisce nella cache su disco, che è già scritta in modo
    atomico — il thread non condivide struttura con la pagina, condivide solo
    dei file.

    Vive nella cache di Streamlit, quindi uno solo per server, non uno per
    scheda del browser aperta.
    """

    def __init__(self) -> None:
        self._coda: list[Path] = []
        self._in_corso: str | None = None
        # I file per cui e' stato chiesto anche il campione della deduplica.
        self._approfondire: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def accoda_approfondita(self, percorsi: list[Path]) -> None:
        """Come `accoda`, ma per la misura della deduplica sul file.

        Va in coda con le analisi normali e nello stesso thread: due misure
        pesanti in parallelo si contendono il disco e finiscono per metterci
        di piu' entrambe.
        """
        with self._lock:
            for p in percorsi:
                self._approfondire.add(str(p))
                if str(p) == self._in_corso or p in self._coda:
                    continue
                self._coda.append(p)
        self._assicura_thread()

    def accoda(self, percorsi: list[Path], *, rifai: bool = False,
               approfondita: bool = False) -> None:
        # La cache si legge FUORI dal lock: è accesso al disco, e tenendo il
        # lock si bloccherebbe il thread che sta lavorando.
        # Con l'approfondita accesa conta anche il file gia' analizzato ma
        # SENZA la misura: e' il caso di chi accende l'opzione dopo.
        da_fare = [
            p for p in percorsi
            if rifai or (r := library.cached_report(p)) is None
            or (approfondita and r.dedup_campione is None)]
        with self._lock:
            for p in da_fare:
                if approfondita:
                    self._approfondire.add(str(p))
                # Il file IN CORSO non si riaccoda: la sua cache non è ancora
                # scritta, quindi `cached_report` dice None e a ogni ricarica
                # della pagina tornava in fila. Veniva contato due volte — una
                # come "in corso" e una come "in coda" — e a fine analisi
                # sarebbe stato rianalizzato da capo per niente.
                if str(p) == self._in_corso or p in self._coda:
                    continue
                self._coda.append(p)
        self._assicura_thread()

    def _assicura_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._lavora, daemon=True)
        self._thread.start()

    def _lavora(self) -> None:
        while True:
            with self._lock:
                if not self._coda:
                    self._in_corso = None
                    return
                p = self._coda.pop(0)
                self._in_corso = str(p)
            try:
                with self._lock:
                    approfondire = str(p) in self._approfondire
                if approfondire:
                    # Riusa il referto gia' in cassa e ci aggiunge la misura:
                    # l'analisi veloce fatta prima non viene rifatta.
                    library.approfondisci(p)
                    with self._lock:
                        self._approfondire.discard(str(p))
                else:
                    library.analyse(p, force=True)
            except Exception:                              # noqa: BLE001
                pass          # un file illeggibile non deve fermare la coda

    @property
    def in_corso(self) -> str | None:
        with self._lock:
            return self._in_corso

    @property
    def in_coda(self) -> set[str]:
        with self._lock:
            return {str(p) for p in self._coda}

    @property
    def al_lavoro(self) -> bool:
        with self._lock:
            return bool(self._coda) or self._in_corso is not None


@st.cache_resource(show_spinner=False)
def analizzatore() -> Analizzatore:
    return Analizzatore()


def _chroma(pix_fmt: str) -> str:
    """4:2:0, 4:2:2 o 4:4:4 dal nome del formato pixel."""
    for marchio in ("444", "422", "420", "411", "410"):
        if marchio in pix_fmt:
            return ":".join(marchio)
    return pix_fmt


def esc(testo: str) -> str:
    """Filtra un testo che finisce dentro `unsafe_allow_html`.

    I nomi dei file arrivavano grezzi nell'HTML: un file chiamato
    `<b>grassetto<b> & <i>corsivo.mkv` compariva a schermo come "grassetto &
    *corsivo.mkv*", in grassetto, senza i pezzi `<b>` e `<i>`. Lo stesso file
    si mostrava con TRE nomi diversi in tre punti dell'app, il che rende
    impossibile essere sicuri di quale file si stia guardando. Streamlit
    ripulisce gli script, quindi non era un problema di sicurezza: era che il
    nome mostrato non era il nome del file.
    """
    return html.escape(str(testo))


def state(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def model_for(path: str, height: int) -> str:
    return state("modelli", {}).get(path) or recommend(height).model


@st.cache_data(ttl=20, show_spinner=False)
def _deduplica_dei_file_avviati() -> dict[str, tuple[float, int]]:
    """Nome del sorgente -> (deduplica ESATTA, su quanti fotogrammi).

    Il conteggio viaggia insieme alla quota perche' il piano possa rifiutare
    una mappa che parla di un'altra estrazione dello stesso file.

    La mappa completa esiste su disco pochi minuti dopo la partenza e non
    cambia più per tutta la lavorazione: venti secondi di cache sono un
    aggiornamento istantaneo su una scala di ore.
    """
    fuori: dict[str, float] = {}
    for lavoro in monitor.lavori():
        misura = monitor.dedup_esatta(lavoro.cartella)
        if misura is not None and lavoro.sorgente:
            # `setdefault` e non assegnazione: `monitor.lavori()` torna i vivi
            # per primi e poi dal piu' recente, quindi il PRIMO che nomina un
            # sorgente e' quello buono. Assegnando, un tentativo abbandonato
            # di tre giorni fa vinceva sulla lavorazione in corso.
            fuori.setdefault(lavoro.sorgente, misura)
    return fuori


def plan_for(path: Path, cfg: dict, height: int):
    # Se questo file è già partito, la sua deduplica non si stima: si legge.
    # È la differenza fra il ±3% del modello e il ±47% del caso peggiore
    # visto (Tsukimonogatari, 6,5% reale contro il 30% di mediana storica).
    nota = _deduplica_dei_file_avviati().get(path.name) if cfg["dedup"] else None
    return build_plan(
        library.analyse(path), target_height=cfg["altezza"], crf=cfg["crf"],
        preset=cfg["preset"], peak_disk_gb=cfg["disco"], dedup=cfg["dedup"],
        denoise=cfg["denoise"], forza=cfg["forza"],
        model_key=model_for(str(path), height), dedup_nota=nota,
    )


def entry_for(path: str) -> dict | None:
    return next((f for f in load_library() if f["path"] == path), None)


# ===========================================================================
#  Intestazione, schede, impostazioni
# ===========================================================================

def _pallini_schede() -> None:
    """Quante cose stanno aspettando, per scheda: un pallino come su iOS.

    Il numero arriva dal CSS e non dal testo del pulsante: le schede sono
    un `segmented_control` di Streamlit, e cambiarne le etichette
    cambierebbe anche i valori con cui la selezione si confronta.
    """
    coda_analisi = analizzatore()
    quante = {
        "Sorgenti": len(coda_analisi.in_coda) + (1 if coda_analisi.in_corso
                                                 else 0),
    }
    catena = monitor.catena()
    if catena:
        # Il file in corso piu' quelli che aspettano il loro turno.
        resta = int(catena.get("totale") or 0) - int(catena.get("numero") or 0)
        quante["Lavorazione"] = max(0, resta) + 1

    regole = []
    for scheda, n in quante.items():
        if not n:
            continue
        indice = SEZIONI.index(scheda) + 1
        regole.append(
            f'.st-key-fasi [role="radio"]:nth-of-type({indice})::after '
            f'{{ content: "{n if n < 100 else "99+"}"; }}')
    if regole:
        st.markdown("<style>" + "".join(regole) + "</style>",
                    unsafe_allow_html=True)


def header() -> str:
    # Niente nome ne' logo sopra le schede (deciso con l'utente): il nome e'
    # gia' nel titolo della finestra o della scheda del browser, e il logo
    # era quello vecchio. Versione e sottotitolo stanno in fondo alla sidebar.
    with st.container(key="fasi"):
        # La scheda attiva vive anche nell'URL (?scheda=lavorazione): al
        # refresh la sessione muore ma l'indirizzo resta, e la pagina si
        # riapre dov'era — prima si tornava sempre in Sorgenti (detto
        # dall'utente). L'ancora #hash non funzionerebbe: il server non la
        # riceve mai; il query param sì.
        dal_url = str(st.query_params.get("scheda") or "").capitalize()
        predefinita = dal_url if dal_url in SEZIONI else SEZIONI[0]
        # `format_func`: i valori restano gli identificativi italiani (URL,
        # CSS, confronti nel codice), cambia solo la scritta.
        scelta = st.segmented_control(
            "Fasi", SEZIONI, key="sezione", default=predefinita,
            format_func=lambda s: t(f"tab.{s}"),
            label_visibility="collapsed")
        _pallini_schede()
    # Le tendine di Streamlit sono combobox: scrivendoci si filtrano le
    # voci, e con tre opzioni il filtro produce solo "No results" e
    # perplessita' (visto dall'utente). Non esiste un interruttore nativo:
    # si disarmano i tasti-carattere sugli input delle tendine, lasciando
    # vive frecce, Invio ed Esc. L'iframe e' SEMPRE presente e in posizione
    # stabile: e' la regola anti-adozione imparata col Confronto.
    # (Il "consigliato dentro l'elenco aperto" e' stato tolto DI PROPOSITO:
    # ogni via provata — riscrivere i nodi, marcare le opzioni da un
    # osservatore — o sfarfallava o si avvitava in un loop di mutazioni che
    # strangolava la pagina. Il consiglio vive nella chip accanto, punto.)
    st.iframe(
        "<script>const D=window.parent.document;"
        "if(!D.__auTendineMute){D.__auTendineMute=true;"
        "D.addEventListener('keydown',e=>{const t=e.target;"
        "if(t&&t.matches&&t.matches('[data-testid=\"stSelectbox\"] input')"
        "&&e.key.length===1&&!e.metaKey&&!e.ctrlKey)e.preventDefault();"
        "},true);"
        "D.addEventListener('paste',e=>{const t=e.target;"
        "if(t&&t.matches&&t.matches('[data-testid=\"stSelectbox\"] input'))"
        "e.preventDefault();},true);"
        # Card degli spezzoni (Confronto): un click OVUNQUE nella card
        # attiva/disattiva la spunta. La checkbox vera resta esclusa dalla
        # delega (il suo click nativo funziona gia'): niente doppio scatto.
        "D.addEventListener('click',e=>{"
        "const card=e.target.closest&&e.target.closest('[class*=\"st-key-clip\"]');"
        "if(!card)return;"
        "if(e.target.closest('[data-testid=\"stCheckbox\"]'))return;"
        "const inp=card.querySelector('[data-testid=\"stCheckbox\"] input');"
        "if(inp)inp.click();"
        "},true);"
        "}</script>", height=1)
    attiva = scelta or st.session_state.get("sezione") or SEZIONI[0]
    if st.query_params.get("scheda") != attiva.lower():
        st.query_params["scheda"] = attiva.lower()
    return attiva


def _valore_a_destra(regole: list[str], chiave: str, testo: str) -> None:
    """Il valore del controllo, in fondo alla riga dell'etichetta.

    Streamlit mostra il valore del cursore sopra il pomello, dove si muove e
    non si allinea con niente. Spostarlo con `position:absolute` non funziona:
    fra il valore e il contenitore del widget c'e' un div già posizionato, e
    l'assoluto si aggancia a quello (misurato: valore a 39px dall'alto, etichetta
    a 2px).

    Si passa invece dalla chiave del contenitore, che Streamlit trasforma in
    una classe: una regola per controllo, con il valore in `content`. Costa
    qualche riga di CSS a ogni rerun e in cambio l'etichetta resta quella
    nativa, col suo tooltip — che con `label_visibility="collapsed"` si
    perderebbe, visto che l'icona del suggerimento vive dentro l'etichetta.
    """
    # `margin-left: auto` sul valore e NON sul suggerimento: il "?" appartiene
    # all'etichetta e le resta accanto, il valore va all'estremita' opposta.
    # Messo sul suggerimento, i due finivano appiccicati in fondo.
    regole.append(
        f'.st-key-{chiave} [data-testid="stWidgetLabel"]::after '
        f'{{ content: "{testo}"; margin-left: auto; padding-left: 12px; }}')


# Le impostazioni della sidebar vivono anche su disco: al riavvio tornano
# quelle dell'ultima sessione, non i default (prima "quando riapro mi dà i
# default... al 99% butta lavoro fatto" — Interstellar0verdrive). Il file sta nei registri,
# accanto alle pagelle.
# Sotto questa soglia non si lavora: i soli fotogrammi sorgente di un
# episodio da 24 minuti a 720p ne occupano 31, e un blocco ci si aggiunge.
# Offrire 10 GB nel cursore significava offrire un'impostazione con cui
# nessun file puo' essere lavorato. (Soglia proposta da Interstellar0verdrive l'11/08.)
MINIMO_SPAZIO_GB = 50


def _tetto_spazio() -> tuple[int, int]:
    """(tetto consigliato, spazio libero) in GB, per lo spazio per file.

    Il tetto e' il PIU' PRUDENTE fra l'85% del libero e «tutto meno 40 GB».
    La percentuale da sola non basta: su un disco quasi pieno l'85% di 60 GB
    lascerebbe nove giga al sistema, che sono pochi. Su un disco vuoto vince
    invece la percentuale, e il margine assoluto non stringe inutilmente.

    Questo numero e' un TETTO, non una prenotazione: l'app occupa quello che
    il file chiede, non quello che gli si concede. Un tetto generoso non
    costa niente, serve solo a non farsi rifiutare una lavorazione che ci
    starebbe. (Regola concordata con l'utente l'11/08.)

    Il tetto non scende mai sotto `MINIMO_SPAZIO_GB + 1`: non e' generosita'
    ma la larghezza minima di un cursore. Con un disco cosi' pieno non si
    lavora comunque, e a dirlo dev'essere il rifiuto della lavorazione —
    «servono almeno N GB, liberi M» — non un cursore che sparisce.
    """
    try:
        libero = int(gb_liberi(PATHS.output))
    except OSError:
        return 120, 120
    return max(MINIMO_SPAZIO_GB + 1,
               min(int(libero * 0.85), libero - 40)), libero


_IMPOSTAZIONI_DEFAULT = {
    "altezza": 1080, "crf": 18, "preset": "slower", "dedup": True,
    "denoise": False, "forza": False, "disco": None,
    "pausa": 5,
    # Acceso di fabbrica: la stima serve a decidere PRIMA di lanciare, e
    # senza la misura sul file la deduplica si deduce dai file simili per
    # taglia — criterio che pesca il fratello sbagliato (voce 84).
    "approfondita": True,
    # Scritto per esteso e non `i18n.PREDEFINITA`: il dizionario deve restare
    # un letterale, i test lo leggono cosi'. Sono la stessa cosa.
    "lingua": "en",
    # Un controllo al giorno su GitHub, spegnibile: e' l'unica connessione
    # che AnimeUp fa da solo dopo il primo avvio.
    "aggiornamenti": True,
}


def _predefiniti() -> dict:
    """I valori di fabbrica, con lo spazio risolto sul disco di ADESSO.

    `disco` non puo' stare nel dizionario come numero fisso: il suo
    predefinito e' una REGOLA — il piu' prudente fra l'85% del libero e
    «tutto meno 40 GB» — e dipende dal disco su cui gira l'app. Scritto come
    costante valeva `MINIMO_SPAZIO_GB`, cioe' il minimo del cursore, ed e'
    cosi' che su un disco con 606 GB liberi l'impostazione si e' ritrovata a
    50 GB senza che nessuno l'avesse scelta (segnalato dall'utente il 12/08).
    E' lo stesso difetto gia' corretto per il valore SALVATO, che pero'
    lasciava scoperta la via dei predefiniti.
    """
    valori = dict(_IMPOSTAZIONI_DEFAULT)
    valori["disco"] = _tetto_spazio()[0]
    return valori


def _impostazioni_file() -> Path:
    return PATHS.impostazioni


def _impostazioni_carica() -> dict:
    """Il salvato, sanificato valore per valore: un file manomesso o di una
    versione futura non deve poter rompere i widget (che con un valore fuori
    scala sollevano eccezione, non avvisano)."""
    try:
        dati = su_disco.leggi(_impostazioni_file())
    except (OSError, ValueError):
        dati = {}
    puliti = _impostazioni_pulite(dati)
    # Lo spazio per file si RICALCOLA a ogni avvio dalla regola — il piu'
    # prudente fra l'85% del libero e «tutto meno 40 GB» — e il valore
    # salvato si ignora, anche se valido. Deciso dall'utente il 12/08
    # («possiamo anche decidere che a ogni avvio ri-imposta all'85%,
    # fottendosene della precedente impostazione toccata a mano»).
    #
    # Non e' pigrizia, e' la cura di un difetto che e' tornato due volte in
    # una notte: `disco` si e' ritrovato prima a 10 GB e poi a 50 — il minimo
    # del cursore — su un disco con 600 e 700 GB liberi, senza che nessuno
    # l'avesse scelto. Il lato lettura era stato difeso (si scartava un
    # valore fuori scala), ma il lato SCRITTURA no: una sessione con la
    # chiave non seminata salva il minimo su disco, e da li' in poi quel
    # minimo e' indistinguibile da una scelta vera. Ricalcolando sempre, il
    # valore sbagliato non puo' sopravvivere a un ricaricamento.
    #
    # Il prezzo, accettato: chi abbassa il cursore a mano se lo ritrova
    # rialzato al giro dopo. E' un TETTO, non una prenotazione — l'app
    # occupa quello che il file chiede — quindi alzarlo non costa niente,
    # mentre trovarselo al minimo costa blocchi inutili e ore.
    puliti["disco"] = _tetto_spazio()[0]
    return puliti


def _impostazioni_pulite(dati: object) -> dict:
    """Gli stessi controlli, su un dizionario qualunque.

    Serve anche alla ricetta di un file sospeso (`parametri.json`), che prima
    finiva nei widget senza passare di qui: un preset scritto a mano o un CRF
    fuori scala li avrebbe fatti sollevare, che e' proprio quello contro cui
    questa funzione esiste.
    """
    if not isinstance(dati, dict):
        dati = {}
    puliti = _predefiniti()
    if dati.get("altezza") in (720, 1080, 1440, 2160):
        puliti["altezza"] = dati["altezza"]
    if dati.get("preset") in ("medium", "slow", "slower", "veryslow"):
        puliti["preset"] = dati["preset"]
    if dati.get("lingua") in i18n.LINGUE:
        puliti["lingua"] = dati["lingua"]
    for chiave, minimo, massimo in (("crf", 14, 24),
                                    ("disco", MINIMO_SPAZIO_GB, _tetto_spazio()[0]),
                                    ("pausa", 0, 30)):
        try:
            grezzo = int(dati[chiave])
            if isinstance(dati[chiave], bool) or grezzo < minimo:
                # SOTTO il minimo non si stringe: si scarta. Stringere
                # significherebbe presentare all'utente il valore piu' piccolo
                # possibile come se l'avesse scelto lui — ed e' esattamente
                # cosa e' successo con `disco`, ritrovato a 10 GB (il minimo
                # del cursore) su un disco da 600 liberi, senza che nessuno
                # l'avesse impostato. Da dove venisse quel valore non si e'
                # ricostruito; quel che si e' potuto stabilire e' che solo
                # uno zero, un negativo o un booleano lo producono.
                # SOPRA il massimo invece si stringe, perche' li' il limite
                # e' fisico — il disco e' quello — e viene detto in sidebar.
                raise ValueError(f"{chiave} fuori scala: {dati[chiave]!r}")
            puliti[chiave] = min(massimo, grezzo)
        except (KeyError, TypeError, ValueError):
            pass
    # Le chiavi booleane si RICAVANO dai valori di fabbrica, non si elencano
    # a mano: l'elenco scritto a mano diceva ("dedup", "denoise", "forza") e
    # al primo interruttore aggiunto — «Analisi approfondita» — il valore
    # salvato veniva scartato in silenzio e tornava sempre il predefinito.
    # Un difetto che non da' errori: sembra solo che l'app non ricordi.
    for chiave, fabbrica in _IMPOSTAZIONI_DEFAULT.items():
        if isinstance(fabbrica, bool) and isinstance(dati.get(chiave), bool):
            puliti[chiave] = dati[chiave]
    return puliti


def _impostazioni_scrivi(cfg: dict) -> None:
    try:
        _impostazioni_file().parent.mkdir(parents=True, exist_ok=True)
        _impostazioni_file().write_text(su_disco.dumps(
            {k: cfg[k] for k in _IMPOSTAZIONI_DEFAULT}, indent=2))
    except OSError:
        pass


def _leggi_parametri(cartella: Path | None) -> dict:
    """La ricetta (parametri.json) di una lavorazione, se esiste."""
    if cartella is None:
        return {}
    try:
        dati = su_disco.leggi(cartella / "parameters.json")
        return dati if isinstance(dati, dict) else {}
    except (OSError, ValueError):
        return {}


def _modello_usato(esito: dict | None) -> str | None:
    """Il modello con cui il file e' stato lavorato davvero.

    Sta nella pagella (campo `modello`); le pagelle scritte prima che
    quel campo esistesse lo portano comunque dentro il NOME dell'uscita
    (`[upscale 1080p animevideov3 x3 crf18 dd]`), da cui si ricava.
    """
    if not esito:
        return None
    chiave = esito.get("modello")
    if chiave in CATALOG:
        return chiave
    nome = str(esito.get("output") or "")
    # Dal piu' lungo al piu' corto: "cugan" e' un pezzo di "cugan-denoise".
    for k in sorted(CATALOG, key=len, reverse=True):
        if f" {k} x" in nome:
            return k
    return None


# Le impostazioni che NON si confrontano col file sospeso, e che «Riporta la
# sidebar…» non rimette. Lo spazio su disco si ricalcola dallo spazio libero a
# ogni avvio, quindi non coincideva quasi mai con quello salvato: l'avviso
# scattava per lui e basta, e il ripristino rimetteva un valore vecchio,
# misurato su un disco che nel frattempo e' cambiato. E non conta per la
# ripresa: Riprendi adotta comunque la griglia di blocchi salvata.
_FUORI_DAL_CONFRONTO = ("disco",)


def _diversi_dal_sospeso(ricetta: dict, attuali: dict) -> list[str]:
    """Le impostazioni della sidebar diverse da quelle del file sospeso."""
    return sorted(k for k in _IMPOSTAZIONI_DEFAULT
                  if k in ricetta and k not in _FUORI_DAL_CONFRONTO
                  and ricetta[k] != attuali.get(k))


def _ripristina_parametri(ricetta: dict) -> None:
    """Riporta la sidebar ai parametri di un file sospeso.

    Deve girare come RICHIAMO del pulsante, non nel suo corpo: i widget con
    quelle chiavi sono gia' stati creati piu' su nello stesso giro, e
    scrivere allora nello stato sollevava
    `StreamlitAPIException: ... cannot be modified after the widget with key
    w_altezza is instantiated` — cioe' il pulsante rompeva la pagina invece
    di fare il suo mestiere. I richiami girano PRIMA del corpo dello script,
    quando nessun widget di quel giro esiste ancora.
    """
    puliti = _impostazioni_pulite(ricetta)
    for chiave in _IMPOSTAZIONI_DEFAULT:
        if chiave in ricetta and chiave not in _FUORI_DAL_CONFRONTO:
            st.session_state[f"w_{chiave}"] = puliti[chiave]


def _ricetta_sospesa() -> dict:
    """La ricetta del file sospeso più recente (per l'avviso in sidebar)."""
    migliore, quando = {}, 0.0
    for lav in monitor.lavori():
        if lav.vivo:
            continue
        f = lav.cartella / "parameters.json"
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt > quando:
            dati = _leggi_parametri(lav.cartella)
            if dati:
                migliore, quando = dati, mt
    return migliore


def _svuota_selezione() -> None:
    """Via la spunta da tutto: i file appena lavorati non devono restare
    selezionati, o la lista li ripropone con l'avviso "gia' lavorati,
    vengono saltati" — l'app che rimprovera all'utente di aver fatto quello
    che gli aveva chiesto lei."""
    st.session_state["coda"] = set()
    st.session_state["rifai_comunque"] = set()
    for chiave in list(st.session_state.keys()):
        if str(chiave).startswith("q_"):
            st.session_state[chiave] = False


def _tocca_modelli(path: str) -> None:
    """Segna che i modelli del Confronto per QUESTO file li ha scelti una
    persona, non la pagina.

    Serve a distinguere tre stati che altrimenti sarebbero due: "mai stato
    qui", "la pagina ha proposto il consigliato" e "ho scelto io". Senza la
    distinzione, la proposta veniva registrata come scelta al primo disegno
    e il Confronto smetteva di seguire il modello del file. Come callback
    gira PRIMA del corpo dello script, quindi la scrittura non incappa nella
    regola che vieta di toccare la chiave di un widget gia' disegnato — e
    comunque questa chiave non e' di nessun widget."""
    st.session_state[f"tocco_modelli_{path}"] = True


def _lancio_visto_file() -> Path:
    return PATHS.logs / ".last-launch-seen"


def _lancio_da_mostrare() -> dict | None:
    """Il resoconto di un lancio finito che non e' ancora stato mostrato.

    Il segno "gia' visto" sta su DISCO e non in sessione: un riavvio
    dell'interfaccia farebbe altrimenti ricomparire la stessa modale, e una
    finestra che torna dopo che l'hai chiusa e' peggio che non averla.
    """
    lancio = monitor.ultimo_lancio()
    if not lancio or not lancio.get("fine"):
        return None
    try:
        visto = float(_lancio_visto_file().read_text().strip())
    except (OSError, ValueError):
        visto = 0.0
    return lancio if float(lancio["fine"]) > visto else None


def _segna_lancio_visto(lancio: dict) -> None:
    try:
        PATHS.logs.mkdir(parents=True, exist_ok=True)
        _lancio_visto_file().write_text(str(lancio.get("fine") or 0))
    except OSError:
        pass


# "Terminata" e non "completata": il titolo non deve smentire quello che
# c'e' scritto due righe sotto ("1 file non completato"). Dice che il
# processo e' finito, non che sia andato tutto bene (scelta dell'utente).
def _contenuto_fine_coda(lancio: dict) -> None:
    """Il resoconto di fine coda: cosa e' uscito, in quanto, con che avvisi.

    Compare una volta sola, alla prima apertura utile: se AnimeUp era chiuso
    quando la coda e' finita, si vede al ritorno. Chiudendola si svuota anche
    la selezione — senza, la lista restava con tutto spuntato e per giunta
    con l'avviso che quei file sono gia' stati lavorati, cioe' l'app che
    rimprovera all'utente di aver fatto quello che gli aveva chiesto lei.
    """
    riusciti = list(lancio.get("riusciti") or [])
    # "Non completati" sono TRE cose diverse che all'utente interessano allo
    # stesso modo: falliti, non pianificabili, e fermati a mano col Ferma
    # per-file. Questi ultimi sparivano da ogni conteggio, e la modale
    # festeggiava una coda in cui un file era stato interrotto.
    falliti = (list(lancio.get("falliti") or [])
               + list(lancio.get("scartati") or [])
               + list(lancio.get("interrotti") or []))
    previsti = list(lancio.get("previsti") or []) or riusciti + falliti
    n_ok, n_tot = len(riusciti), len(previsti)
    secondi = float(lancio.get("secondi") or 0)
    orologio = float(lancio.get("fine") or 0) - float(lancio.get("inizio") or 0)

    # `<b>` e non `**`: qui il markdown non passa, e gli asterischi si
    # vedevano tali e quali.
    st.markdown(
        f"<div class='au-fine-testa'>"
        f"{tn('lav.fine_completati', n_ok, totale=n_tot)}<br>"
        f"{t('lav.fine_tempo', durata=stima_hm(secondi))}</div>",
        unsafe_allow_html=True)

    if lancio.get("inizio") and lancio.get("fine"):
        da = time.localtime(lancio["inizio"])
        a = time.localtime(lancio["fine"])
        # Una maratona che passa la mezzanotte diceva "dalle 19:39 alle
        # 17:46", che si legge come un orario sbagliato. Il giorno compare
        # solo quando serve a capire.
        # «Dalle 04:34 alle 14:37» non dice di COSA siano quegli orari, e
        # sotto una riga che parla di tempo di lavorazione si legge come un
        # secondo conteggio invece che come il periodo in cui si e' lavorato
        # (detto dall'utente il 12/08). I due verbi lo dicono e basta.
        if (da.tm_year, da.tm_yday) == (a.tm_year, a.tm_yday):
            quando = t("lav.fine_stesso_giorno",
                       inizio=time.strftime('%H:%M', da),
                       fine=time.strftime('%H:%M', a))
        else:
            giorno = t("lav.fmt_giorno")
            quando = t("lav.fine_giorni_diversi",
                       giorno_inizio=time.strftime(giorno, da),
                       inizio=time.strftime('%H:%M', da),
                       giorno_fine=time.strftime(giorno, a),
                       fine=time.strftime('%H:%M', a))
        st.markdown(f"<div class='au-fine-quando'>{quando}</div>",
                    unsafe_allow_html=True)

    # Le cifre in colonna, una per riga: di fila su una riga sola erano un
    # elenco da decifrare, incolonnate si leggono a colpo d'occhio.
    respiro = orologio - secondi
    n_avvisi = int(lancio.get("avvisi") or 0)
    voci: list[tuple[str, str]] = []
    if n_ok > 1:
        voci.append((t("lav.fine_medio"), stima_hm(secondi / n_ok)))
    if respiro > 90:
        voci.append((t("lav.fine_pause"), stima_hm(respiro)))
    # `is not None` e non la verita' del valore: una deduplica misurata allo
    # ZERO — attiva, ma su questo materiale non ha trovato niente — e' un
    # risultato, e sparendo dal resoconto diventava indistinguibile da
    # «deduplica spenta», che scrive `null`. Sono due cose diverse e chi
    # legge deve poterle distinguere.
    if lancio.get("dedup_medio") is not None:
        voci.append((t("lav.fine_dedup"),
                     f"{float(lancio['dedup_medio']):.1%}".replace(
                         ".", t("lav.fmt_decimale"))))
    voci.append((t("lav.fine_avvisi"), str(n_avvisi)))
    st.markdown(
        "<div class='au-fine-stat'>"
        + "".join(f"<div><span>{esc(k)}</span><span>{esc(v)}</span></div>"
                  for k, v in voci)
        + "</div>", unsafe_allow_html=True)

    if falliti:
        st.markdown(
            f"<div class='au-fine-guai'>"
            f"{tn('lav.fine_non_completati', len(falliti))}</div>"
            + "".join(f"<div class='au-fine-nome'>{esc(n)}</div>"
                      for n in falliti[:4])
            + (f"<div class='au-fine-quando'>"
               f"{t('lav.fine_e_altri', n=len(falliti) - 4)}</div>"
               if len(falliti) > 4 else ""),
            unsafe_allow_html=True)

    def _chiudi() -> None:
        # Il segno vive su disco per sopravvivere ai riavvii; il doppione in
        # sessione (`fine_vista`) e' il paracadute per il caso in cui la
        # cartella dei registri non sia scrivibile, che altrimenti farebbe
        # riaprire questa finestra a ogni giro, per sempre.
        _segna_lancio_visto(lancio)
        st.session_state["fine_da_mostrare"] = None

    with st.container(key="cFineAzioni"):
        a, b = st.columns(2)
        if a.button(t("lav.fine_apri"), type="primary",
                    use_container_width=True):
            subprocess.run(["open", str(PATHS.output)], check=False)
            _chiudi()
            st.rerun()
        if b.button(t("lav.chiudi"), use_container_width=True):
            _chiudi()
            st.rerun()

    # I palloncini SOLO quando e' andato tutto bene: dopo venti ore di
    # maratona riuscita ci stanno, sopra un file fallito sarebbero una pacca
    # sulla spalla fuori luogo. Una volta sola, o tornerebbero a ogni giro
    # della pagina finche' la modale resta aperta.
    if not falliti and n_ok and not st.session_state.get("fine_festeggiata"):
        st.session_state["fine_festeggiata"] = True
        st.balloons()


# Il titolo della modale si traduce a ogni apertura: `@st.dialog("...")` in
# testa alla funzione lo fisserebbe nella lingua attiva all'avvio. Il
# frammento della modale resta lo stesso (Streamlit lo riconosce dal nome
# della funzione del contenuto), quindi i rerun interni non cambiano.
def _modale_fine_coda(lancio: dict) -> None:
    st.dialog(t("lav.fine_titolo"))(_contenuto_fine_coda)(lancio)


def _contenuto_taratura() -> None:
    """Il processo a passi: presentazione -> cronometro -> confronto.

    Una modale e non una tab: si fa una volta per macchina (e la si rifa'
    dopo un cambio di macOS o per curiosita'), non merita peso permanente
    nella navigazione di tutti i giorni.
    """
    fase = st.session_state.get("tar_fase", "intro")

    if fase == "intro":
        voce = taratura.carica()
        # La presentazione vive in una zona cancellabile: quando il
        # giro parte sparisce tutta (avviso e pulsante compresi) e
        # resta solo il cronometro. Erano tre schermate, non una con
        # la coda che cresce.
        zona = st.empty()
        with zona.container():
            st.markdown("<span class='au-tar-passo au-tar-p1'></span>",
                        unsafe_allow_html=True)
            st.markdown(t("lav.tar_intro"))
            st.markdown(t("lav.tar_intro_dettagli"))
            if voce:
                import datetime
                quando = datetime.datetime.fromtimestamp(voce["quando"])
                _quando = quando.strftime(t("lav.fmt_data_alle"))
                st.markdown(f"<span class='au-meta'>"
                            f"{t('lav.tar_ultima', quando=_quando)}"
                            "</span>", unsafe_allow_html=True)
                with st.expander(t("lav.tar_valori")):
                    def _tab(voci):
                        corpo = [f"| {t('lav.tar_col_misura')} "
                                 f"| {t('lav.tar_col_valore')} |",
                                 "|---|---:|"]
                        corpo += [f"| {nome} | {valore} |"
                                  for nome, valore in voci]
                        return "\n".join(corpo)

                    def _modello(chiavi):
                        voci = []
                        for chiave in chiavi:
                            modello = CATALOG[chiave]
                            for scala in modello.scales:
                                val = voce.get("mpxs", {}).get(chiave,
                                                               {}).get(str(scala))
                                if val:
                                    voci.append((f"{modello.short} x{scala}",
                                                 f"{val:.2f} Mpx/s"))
                        return voci

                    # I pesi seguono la lunghezza dei nomi (CUGAN e' il piu'
                    # largo), e le tabelle riempiono la loro colonna: cosi' i
                    # vuoti fra una tabella e l'altra sono il gap di Streamlit,
                    # uguale per tutti, e la fila occupa tutta la larghezza.
                    with st.container(key="cTarValori"):
                        c1, c2, c3 = st.columns([0.9, 1.35, 0.75])
                        c1.markdown(_tab(_modello(["animevideov3"])))
                        c2.markdown(_tab(_modello(["cugan-denoise", "cugan"])))
                        c3.markdown(_tab([
                            (t("lav.tar_estrazione"),
                             f"{voce.get('estrazione_fps', 0):.0f} f/s"),
                            (t("lav.tar_codifica"),
                             f"{voce.get('codifica_fps', 0):.1f} f/s"),
                        ]))
                    # Anche qui, come nel riepilogo finale: e' parte di cio'
                    # che questa macchina ha gia' misurato. Una taratura
                    # precedente al passo che li misura non ce l'ha, e allora
                    # non si dice niente invece di dire "4" spacciando il
                    # predefinito per una misura.
                    _salv = taratura.frase_salvataggio(voce)
                    if _salv:
                        st.markdown(f"<span class='au-meta'>{esc(_salv)}</span>",
                                    unsafe_allow_html=True)
            else:
                st.markdown(f"<span class='au-meta'>{t('lav.tar_mai')}</span>",
                            unsafe_allow_html=True)
            occupata = (any(l.vivo for l in monitor.lavori())
                        or monitor.catena() is not None
                        or monitor.pausa() is not None)
            if occupata:
                st.error(t("lav.tar_occupata"))
                return
            st.markdown(
                "<div class='au-tar-avviso'>"
                "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' "
                "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
                "stroke-linejoin='round' aria-hidden='true'>"
                "<path d='M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 "
                "1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/>"
                "<line x1='12' y1='9' x2='12' y2='13'/>"
                "<line x1='12' y1='17' x2='12.01' y2='17'/></svg>"
                f"<span>{t('lav.tar_prima')}"
                "</span></div>", unsafe_allow_html=True)
            avviato = st.button(t('lav.tar_avvia'), type='primary',
                                 key='tarAvvia')
        if avviato:
            zona.empty()
            st.markdown("<span class='au-tar-passo au-tar-p2'></span>",
                        unsafe_allow_html=True)
            st.markdown(f"**{t('lav.tar_in_corso')}**")
            # Testo normale e non `au-meta`: quella classe e' monospazio,
            # buona per un'etichetta corta ma non per due frasi di prosa.
            st.markdown(f"{t('lav.tar_chiudibile')}  \n"
                        f"{t('lav.tar_nel_frattempo')}")
            st.session_state["tar_precedente"] = taratura.carica()
            # I pesi vengono dallo stesso preventivo che muove la barra
            # dentro il motore: una sola verita'. Se il modulo in memoria e'
            # anteriore alla funzione (server non ancora riavviato) si
            # ripiega su segmenti uguali, che e' brutto ma non rotto.
            try:
                tappe = [costo for _, costo in taratura.preventivo()]
            except (AttributeError, OSError, ValueError,
                    subprocess.CalledProcessError):
                tappe = []
            barra = st.empty()

            def _quanto(resta: float) -> str:
                minuti = max(1, round(resta / 60))
                return tn("lav.tar_resta", minuti)

            def _segmenti(indice: int, totale: int) -> str:
                pesi = tappe if len(tappe) == totale else [1.0] * totale
                parti = []
                for n, peso in enumerate(pesi, start=1):
                    classe = ("fatta" if n < indice
                              else "corso" if n == indice else "")
                    parti.append(f"<span class='{classe}' "
                                 f"style='flex:{peso:.3f}'></span>")
                return f"<div class='au-tar-tappe'>{''.join(parti)}</div>"

            barra.markdown(
                f"{_segmenti(0, len(tappe) or 9)}"
                f"<div class='au-tar-stato'>{t('lav.tar_preparazione')}</div>",
                unsafe_allow_html=True)

            # `frazione` e `resta` con un valore di ripiego: il server
            # tiene in cache i moduli di src/animeup dall'avvio, mentre
            # app.py si rilegge a ogni rerun. Fra una modifica al modulo e
            # il riavvio del server convivono un chiamante vecchio e un
            # callback nuovo, e senza ripiego la taratura muore con un
            # TypeError (successo davvero, 2026-08-10).
            def _avanzamento(etichetta, indice, totale,
                             frazione=None, resta=None):
                if frazione is None:
                    frazione = max(0.0, (indice - 1) / totale)
                coda = f" · {_quanto(resta)}" if resta is not None else ""
                barra.markdown(
                    f"{_segmenti(indice, totale)}"
                    f"<div class='au-tar-stato'>{etichetta} "
                    f"({indice}/{totale}) · {frazione:.0%}{coda}</div>",
                    unsafe_allow_html=True)
            try:
                st.session_state["tar_nuova"] = taratura.esegui(
                    avanzamento=_avanzamento)
            except (OSError, RuntimeError, FileNotFoundError,
                    subprocess.CalledProcessError) as errore:
                st.error(t("lav.tar_interrotta", errore=errore))
                return
            barra.markdown(
                f"{_segmenti(999, len(tappe) or 9)}"
                f"<div class='au-tar-stato'>{t('lav.tar_finito')}</div>",
                unsafe_allow_html=True)
            st.session_state["tar_fase"] = "esito"
            st.rerun(scope="fragment")
        return

    # --- esito: il confronto a tre colonne e il congedo -------------------
    nuova = st.session_state.get("tar_nuova") or {}
    prima = st.session_state.get("tar_precedente")
    st.markdown("<span class='au-tar-passo au-tar-p3'></span>",
                unsafe_allow_html=True)
    st.markdown(t("lav.tar_salvata"))
    st.markdown(f"{t('lav.tar_da_ora')}  \n{t('lav.tar_ripetibile')}")

    def _scarto(nuovo, riferimento):
        if not (nuovo and riferimento):
            return "—"
        return f"{(nuovo / riferimento - 1) * 100:+.0f}%"

    righe = [f"| {t('lav.tar_col_misura')} | {t('lav.tar_col_fabbrica')} "
             f"| {t('lav.tar_col_precedente')} | {t('lav.tar_col_nuova')} "
             f"| {t('lav.tar_col_scarto')} |",
             "|---|---:|---:|---:|---:|"]
    for chiave, modello in CATALOG.items():
        for scala in modello.scales:
            fab = modello.throughput.get(scala)
            pre = (prima or {}).get("mpxs", {}).get(chiave, {}).get(str(scala))
            nuo = nuova.get("mpxs", {}).get(chiave, {}).get(str(scala))
            righe.append(
                f"| {modello.short} x{scala} "
                f"| {fab:.2f} Mpx/s "
                f"| {f'{pre:.2f} Mpx/s' if pre else '—'} "
                f"| {f'{nuo:.2f} Mpx/s' if nuo else '—'} "
                f"| {_scarto(nuo, pre or fab)} |")
    pre_e = (prima or {}).get("estrazione_fps")
    pre_c = (prima or {}).get("codifica_fps")
    righe.append(f"| {t('lav.tar_estrazione')} | 60 f/s "
                 f"| {f'{pre_e:.0f} f/s' if pre_e else '—'} "
                 f"| {nuova.get('estrazione_fps', 0):.0f} f/s "
                 f"| {_scarto(nuova.get('estrazione_fps'), pre_e or 60.0)} |")
    righe.append(f"| {t('lav.tar_codifica')} (1080p) | 8.0 f/s "
                 f"| {f'{pre_c:.1f} f/s' if pre_c else '—'} "
                 f"| {nuova.get('codifica_fps', 0):.1f} f/s "
                 f"| {_scarto(nuova.get('codifica_fps'), pre_c or 8.0)} |")
    with st.container(key="cTarConfronto"):
        st.markdown("\n".join(righe))
    # I thread di salvataggio non stanno nella tabella: non sono un ritmo da
    # confrontare con la fabbrica, sono una SCELTA che la taratura ha fatto.
    # Vanno detti dove si riferisce, pero': altrimenti la prova che li misura
    # (un minuto e mezzo su dieci) sembra non essere mai avvenuta.
    _frase_salv = taratura.frase_salvataggio(taratura.carica())
    if _frase_salv:
        st.markdown(f"<span class='au-meta'>{esc(_frase_salv)}</span>",
                    unsafe_allow_html=True)
    st.markdown(f"<span class='au-meta'>{t('lav.tar_nota_scarto')}</span>",
                unsafe_allow_html=True)
    if st.button(t("lav.chiudi"), type="primary", key="tarChiudi"):
        st.session_state.pop("tar_fase", None)
        st.rerun()


# Come per la fine coda: il titolo si traduce all'apertura, non all'avvio.
def _modale_taratura() -> None:
    st.markdown("<style>" + "".join(
        f'[role="dialog"]:has(.au-tar-p{n}) h2::after '
        f'{{ content: "{t("lav.tar_passo", n=n, totale=3)}"; }}'
        for n in (1, 2, 3)) + "</style>", unsafe_allow_html=True)
    st.dialog(t("lav.tar_titolo"), width="large")(_contenuto_taratura)()


def _chiedi_aggiornamento() -> None:
    """Lascia all'app per macOS la richiesta di aggiornarsi.

    Solo la richiesta: quale versione, da dove e con che checksum lo chiede
    l'app direttamente a GitHub, senza fidarsi di niente scritto qui.
    """
    stato = os.environ.get("ANIMEUP_STATO")
    if not stato:
        return
    try:
        (Path(stato) / "aggiornamento-richiesta").write_text(str(time.time()))
        st.session_state["aggiornamento_chiesto"] = True
    except OSError:
        pass


def _file_cartella_dati() -> Path | None:
    """Dove l'app per macOS legge la cartella dei dati al prossimo avvio."""
    stato = os.environ.get("ANIMEUP_STATO")
    return Path(stato) / "cartella_dati" if stato else None


def _scegli_cartella_dati() -> None:
    """Il selettore di cartelle di macOS, aperto dal server (che gira su
    questo stesso Mac). Annullare non cambia niente."""
    esito = subprocess.run(
        ["osascript", "-e",
         f'POSIX path of (choose folder with prompt "{t("sb.cartella_prompt")}")'],
        capture_output=True, text=True, check=False)
    scelta = esito.stdout.strip()
    file = _file_cartella_dati()
    if esito.returncode == 0 and scelta and file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(str(Path(scelta).resolve()) + "\n")
        st.session_state["cartella_cambiata"] = str(Path(scelta).resolve())


def _icona_perche(testo: str) -> str:
    """Il (?) col fumetto, nella forma usata dalle righe con un link a destra."""
    return ("<span class='au-perche' tabindex='0'>"
            "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round' aria-hidden='true'>"
            "<circle cx='12' cy='12' r='10'></circle>"
            "<path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path>"
            "<line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
            f"{_bolla(testo)}</span>")


def _breve(percorso: str | Path) -> str:
    return str(percorso).replace(str(Path.home()), "~", 1)


def _nota_cartella_assente() -> str | None:
    """La cartella scelta che l'app ha dovuto saltare (disco non collegato)."""
    assente = os.environ.get("ANIMEUP_CARTELLA_ASSENTE")
    if not assente:
        return None
    return t("sb.cartella_assente", scelta=_breve(assente), attuale=_breve(PATHS.root))


def _riga_cartella_dati(congelata: bool) -> None:
    """La cartella dei dati dell'app: dove sta, e come cambiarla.

    Stesso disegno della riga Taratura: etichetta e link sulla stessa riga,
    il percorso sotto. Scelta una cartella, l'app riavvia il server su
    quella (lo nota da `cartella_dati`) e la pagina si ricarica da sola.
    """
    with st.sidebar.container(key="cCartellaRiga"):
        st.markdown(
            "<div class='au-tar-riga' style='padding-right: 58px'>"
            f"<span>{t('sb.cartella')}{_icona_perche(t('sb.cartella_aiuto'))}</span>"
            "</div>", unsafe_allow_html=True)
        st.button(t("sb.cartella_cambia"), key="apriCartella",
                  disabled=congelata, on_click=_scegli_cartella_dati)
    st.sidebar.markdown(f"<div class='au-meta au-cartella'>{esc(_breve(PATHS.root))}</div>",
                        unsafe_allow_html=True)
    if (nota := _nota_cartella_assente()):
        st.sidebar.markdown(f"<div class='au-nota-viva au-nota-avviso'>{esc(nota)}</div>",
                            unsafe_allow_html=True)
    nuova = st.session_state.get("cartella_cambiata")
    if nuova:
        st.sidebar.caption(t("sb.cartella_riavvia", cartella=_breve(nuova)))


def _nomi_impostazioni(chiavi: list[str]) -> list[str]:
    """Le chiavi delle impostazioni col nome che hanno in sidebar.

    L'avviso del file sospeso elencava le chiavi interne («disco», «forza»):
    nomi che a schermo non compaiono da nessuna parte.
    """
    nomi = {"altezza": t("sb.altezza"), "crf": "CRF", "preset": "Preset x265",
            "dedup": t("sb.dedup"), "denoise": t("sb.denoise"),
            "forza": t("sb.forza"), "disco": t("sb.disco"),
            "pausa": t("sb.pausa"), "approfondita": t("sb.approf")}
    return [nomi.get(c, c) for c in chiavi]


def sidebar() -> dict:
    # Con una catena in corso le impostazioni si CONGELANO: cambiarle non
    # avrebbe alcun effetto reale (la catena porta i parametri scritti nel
    # suo comando, e Avvia/Riprendi sono spenti), ma rigiudicava le righe
    # coi valori nuovi — l'episodio "fatto" smetteva di esserlo solo perché
    # il CRF a schermo era cambiato: "un effetto ottico orrendo" (detto
    # dall'utente, e aveva ragione).
    congelata = (monitor.catena() is not None
                 or monitor.pausa() is not None
                 or any(l.vivo for l in monitor.lavori()))
    # La sidebar dichiara con che stato si è disegnata: vive FUORI dal
    # fragment che si auto-aggiorna, quindi da sola non si accorgerebbe mai
    # di una catena nata o morta nel frattempo — dopo un Riprendi restava
    # scongelata (successo). Il fragment confronta e forza il giro completo.
    st.session_state["sidebar_congelata"] = congelata
    # I widget leggono la sessione (chiavi w_*), seminata dal disco al primo
    # giro: niente `value=` sui widget, o Streamlit litiga con la sessione.
    salvate = _impostazioni_carica()
    for chiave, valore in salvate.items():
        st.session_state.setdefault(f"w_{chiave}", valore)
    # Gerarchia a tre livelli, decisa con l'utente dopo che "Impostazioni
    # globali / Opzioni avanzate" faceva sembrare congelate solo le prime
    # (e le avanzate globali non meno delle altre): un titolo-madre
    # "Impostazioni" con la nota di stato sotto — così copre TUTTO — e due
    # sezioni sorelle, "Di base" e "Avanzate".
    nuova = aggiornamenti.disponibile(attivo=salvate.get("aggiornamenti", True))
    if nuova:
        app = os.environ.get("ANIMEUP_APP") == "1"
        # Nell'app l'aggiornamento lo fa l'app stessa (scarica, verifica il
        # checksum, si sostituisce): qui si chiede soltanto. Nella cartella
        # portatile resta il link alla release, da scaricare a mano.
        link = (f"<a href='{esc(nuova['url'])}' target='_blank'>"
                f"{t('sb.aggiornamento_note' if app else 'sb.aggiornamento_link')}</a>")
        st.sidebar.markdown(
            "<div class='au-nota-viva au-nota-avviso'>"
            f"{t('sb.aggiornamento', versione=esc(nuova['versione']))} {link}</div>",
            unsafe_allow_html=True)
        if app:
            if st.sidebar.button(t("sb.aggiornamento_installa"), key="installaAgg",
                                 type="primary", use_container_width=True,
                                 icon=":material/system_update_alt:"):
                _chiedi_aggiornamento()
            if st.session_state.get("aggiornamento_chiesto"):
                st.sidebar.caption(t("sb.aggiornamento_chiesto"))
    st.sidebar.markdown(f"<div class='au-sb-titolo'>{t('sb.titolo')}</div>",
                        unsafe_allow_html=True)
    # Il posto dell'avviso «file sospeso» sta QUI, in alto, anche se il suo
    # contenuto si sa solo in fondo (serve il confronto con i widget). Prima
    # veniva scritto dove veniva calcolato — in coda, dopo dodici elementi —
    # e bastava aprire «Impostazioni avanzate» o avere una finestra bassa
    # perche' scivolasse fuori dall'area visibile: un avviso che si vede
    # solo se scorri e' un avviso che meta' delle volte non esiste
    # (segnalato dall'utente il 12/08, misurato: 1.057 px di contenuto in
    # 582 px di sidebar).
    posto_sospeso = st.sidebar.empty()
    if congelata:
        # `au-nota-viva`: è l'unico testo che SPIEGA il congelamento, e il
        # dimmer qui sotto lo risparmia — spegnere anche la spiegazione
        # lascerebbe solo il mistero.
        st.sidebar.markdown("<div class='au-nota-viva au-nota-congelo'>"
                            f"{t('sb.congelata')}</div>",
                            unsafe_allow_html=True)
        # Congelata DAVVERO anche all'occhio: `disabled=` spegne i widget ma
        # le toggle restavano col loro ciano e i tooltip vivi — "tutto
        # dovrebbe essere in scala di grigi" (detto dall'utente). Il blocco
        # di stile esiste solo in questo stato, quindi non serve marcare
        # niente: sparisce da solo quando la sidebar si sblocca. Il filtro
        # grigio vince anche sui colori forzati con !important.
        st.sidebar.markdown(
            "<style>"
            "[data-testid='stSidebar'] [data-testid='stSlider'],"
            "[data-testid='stSidebar'] [data-testid='stCheckbox'] {"
            "  filter: saturate(0); opacity: .45; pointer-events: none; }"
            "[data-testid='stSidebar'] [data-testid='stSlider'] "
            "[data-testid='stTooltipIcon'],"
            "[data-testid='stSidebar'] [data-testid='stCheckbox'] "
            "[data-testid='stTooltipIcon'] { display: none; }"
            # I suggerimenti ora sono NOSTRI e vivono fuori dai contenitori
            # dei widget: cadevano fuori da entrambe le regole qui sopra e
            # restavano vivi e a colori mentre tutto il resto era spento,
            # col fumetto che si apriva sbiadito al 45% (audit del
            # 2026-08-10). Si spengono con le loro etichette.
            "[data-testid='stSidebar'] .au-sb-eti,"
            "[data-testid='stSidebar'] .au-sb-aiuto {"
            "  opacity: .45; }"
            # TUTTI i suggerimenti della sidebar, non due classi scelte a
            # mano: quello della riga Taratura non stava in nessuna delle due
            # e restava vivo e a colori. E `pointer-events` ferma il mouse ma
            # NON il fuoco da tastiera: con Tab il fumetto si apriva lo
            # stesso, sbiadito al 45%. Si spegne il fumetto, non solo il
            # puntatore. (Niente `filter` sul contenitore: creerebbe un
            # blocco di contenimento e romperebbe l'ancoraggio del fumetto,
            # che finiva tagliato dal bordo alto — audit del 2026-08-10.)
            "[data-testid='stSidebar'] .au-info,"
            "[data-testid='stSidebar'] .au-perche {"
            "  pointer-events: none; }"
            "[data-testid='stSidebar'] .au-info .au-bolla,"
            "[data-testid='stSidebar'] .au-perche .au-bolla {"
            "  display: none !important; }"
            # Anche titoli, sottotitoli ed etichette di sezione: spenti.
            # Restano vivi solo la nota che spiega il congelamento e la
            # fascia Chiudi (che congelata non è mai).
            "[data-testid='stSidebar'] :is([data-testid='stMarkdownContainer'],"
            "[data-testid='stCaptionContainer'])"
            ":not(:has(.au-nota-viva)):not(.st-key-spegnimento *) {"
            "  opacity: .45; }"
            "</style>", unsafe_allow_html=True)
    else:
        st.sidebar.caption(t("sb.valgono"))
    st.sidebar.markdown(f"<div class='au-sb-sezione'>{t('sb.di_base')}</div>",
                        unsafe_allow_html=True)
    regole: list[str] = []

    # La lingua in testa alle impostazioni di base (scelto dall'utente), con
    # l'etichetta nelle due lingue: chi si ritrova l'interfaccia in una
    # lingua che non legge deve poterla trovare lo stesso. Non si congela:
    # non tocca nessuna lavorazione.
    # Sotto un gruppo suo, come «Uscita»: attaccata al titolo della sezione
    # stava troppo stretta (detto dall'utente), e il gruppo da' lo stesso
    # respiro degli altri controlli.
    st.sidebar.markdown(
        f"<div class='au-eyebrow au-sgruppo'>{t('sb.interfaccia')}</div>",
        unsafe_allow_html=True)
    _etichetta_sb("Language · Lingua", t("sb.lingua_aiuto"),
                  predefinito=i18n.LINGUE[i18n.PREDEFINITA])
    with st.sidebar.container(key="cLingua"):
        lingua = st.selectbox(
            "Language · Lingua", list(i18n.LINGUE), key="w_lingua",
            format_func=i18n.LINGUE.get, label_visibility="collapsed")

    st.sidebar.markdown(f"<div class='au-eyebrow au-sgruppo'>{t('sb.uscita')}</div>",
                        unsafe_allow_html=True)
    _etichetta_sb(
        t("sb.altezza"), t("sb.altezza_aiuto"),
        f"{st.session_state.get('w_altezza', 1080)} px",
        predefinito="1080 px")
    with st.sidebar.container(key="cAltezza"):
        altezza = st.select_slider(
            "Altezza finale", options=[720, 1080, 1440, 2160],
            key="w_altezza", disabled=congelata,
            label_visibility="collapsed")

    _etichetta_sb(
        "CRF (x265)", t("sb.crf_aiuto"),
        str(st.session_state.get("w_crf", 18)), predefinito="18")
    with st.sidebar.container(key="cCrf"):
        crf = st.slider(
            "CRF (x265)", 14, 24, key="w_crf", disabled=congelata,
            label_visibility="collapsed")

    _etichetta_sb(
        "Preset x265", t("sb.preset_aiuto"),
        str(st.session_state.get("w_preset", "slower")),
        predefinito="slower")
    with st.sidebar.container(key="cPreset"):
        preset = st.select_slider(
            "Preset x265", options=["medium", "slow", "slower", "veryslow"],
            key="w_preset", disabled=congelata,
            label_visibility="collapsed")

    # Da qui in giù sono regolazioni per chi sa cosa sta toccando: sezione
    # SORELLA di "Di base" (stesso grado), figlia di "Impostazioni" come
    # tutto il resto.
    st.sidebar.divider()
    st.sidebar.markdown(f"<div class='au-sb-sezione'>{t('sb.avanzate')}</div>",
                        unsafe_allow_html=True)
    st.sidebar.caption(t("sb.avanzate_nota"))

    st.sidebar.markdown(f"<div class='au-eyebrow au-sgruppo'>{t('sb.preelab')}</div>",
                        unsafe_allow_html=True)
    with st.sidebar.container(key="swDedup"):
        dedup = st.toggle(t("sb.dedup"), key="w_dedup",
                          disabled=congelata)
        _aiuto_a_destra(t("sb.dedup_aiuto"), t("sb.abilitato"))
    with st.sidebar.container(key="swDenoise"):
        denoise = st.toggle(t("sb.denoise"), key="w_denoise",
                            disabled=congelata)
        _aiuto_a_destra(t("sb.denoise_aiuto"), t("sb.disabilitato"))
    with st.sidebar.container(key="swForza"):
        forza = st.toggle(t("sb.forza"), key="w_forza",
                          disabled=congelata)
        _aiuto_a_destra(t("sb.forza_aiuto"), t("sb.disabilitato"))

    with st.sidebar.container(key="swApprof"):
        # Spento davvero come gli altri, non solo ingrigito dal CSS della
        # sidebar congelata: grigio e basta restava raggiungibile da tastiera.
        approfondita = st.toggle(t("sb.approf"),
                                 key="w_approfondita",
                                 disabled=congelata)
        _aiuto_a_destra(t("sb.approf_aiuto"), t("sb.abilitato"))

    st.sidebar.markdown(f"<div class='au-eyebrow au-sgruppo'>{t('sb.sistema')}</div>",
                        unsafe_allow_html=True)
    # Il TETTO COMPLESSIVO, non la dimensione di un blocco: si chiede quanto
    # disco dedicare a un file, e la divisione in blocchi la decide l'app.
    # L'etichetta vecchia («Spazio per blocco») descriveva un dettaglio di
    # implementazione e prometteva un limite che non era: con 40 GB impostati
    # il picco vero era 165 su un film da due ore e 359 a 1080p, perché quel
    # numero governava i soli fotogrammi ingranditi mentre i sorgenti si
    # estraggono tutti insieme e costano quello che costano.
    #
    # Il massimo del cursore è lo spazio LIBERO VERO meno un margine: fissarlo
    # a 120 GB significava impedire di dedicare a un film le centinaia di
    # giga che quel film chiede, su un disco che ce li ha.
    _tetto_max, _libero_gb = _tetto_spazio()
    # Il ripiego e' il tetto, non un 40 scritto a mano: quel numero non e'
    # piu' il predefinito di nessun ramo del codice, e comparirebbe a
    # schermo come valore corrente nell'unico giro in cui la sessione non e'
    # ancora stata seminata.
    _disco_ora = st.session_state.get("w_disco", _tetto_max)
    # Il valore ricordato non entra piu' nel disco di oggi: si abbassa e lo si
    # DICE. Un'impostazione corretta in silenzio e' un'impostazione che
    # l'utente crede ancora di avere. (Chiesto da Interstellar0verdrive l'11/08.)
    if _disco_ora > _tetto_max:
        st.sidebar.markdown(
            f"<div class='au-nota-viva au-nota-congelo'>"
            f"{t('sb.disco_ridotto', ora=_disco_ora, libero=_libero_gb, tetto=_tetto_max)}"
            "</div>",
            unsafe_allow_html=True)
        st.session_state["w_disco"] = _tetto_max
        _disco_ora = _tetto_max
    _etichetta_sb(
        t("sb.disco"), t("sb.disco_aiuto"),
        f"{_disco_ora} GB",
        # Il predefinito e' una REGOLA, non un numero: scriverne uno fisso
        # («40 GB») voleva dire mostrare per mesi un valore che nessun ramo
        # del codice produceva piu' (segnalato dall'utente il 12/08).
        predefinito=t("sb.disco_predefinito", tetto=_tetto_max, libero=_libero_gb))
    with st.sidebar.container(key="cDisco"):
        disco = st.slider(
            t("sb.disco"), MINIMO_SPAZIO_GB, _tetto_max,
            key="w_disco",
            disabled=congelata, label_visibility="collapsed")

    _pausa_ora = st.session_state.get("w_pausa", 5)
    _etichetta_sb(
        t("sb.pausa"), t("sb.pausa_aiuto"),
        t("sb.pausa_nessuna") if _pausa_ora == 0 else f"{_pausa_ora} min",
        predefinito="5 min")
    with st.sidebar.container(key="cPausa"):
        # Default 5 e non 0 (scelta dell'utente): nelle maratone la pausa
        # deve esserci senza doversene ricordare; 0 spegne la funzione.
        pausa = st.slider(
            t("sb.pausa"), 0, 30, key="w_pausa",
            disabled=congelata, label_visibility="collapsed")

    # La voce di manutenzione: data dell'ultima taratura e l'ingresso alla
    # modale. Vive in Sistema perche' e' della macchina, non del lavoro.
    with st.sidebar.container(key="swAggiorn"):
        controlla_agg = st.toggle(t("sb.controlla_agg"), key="w_aggiornamenti",
                                  disabled=congelata)
        _aiuto_a_destra(t("sb.controlla_agg_aiuto"), t("sb.abilitato"))

    # La cartella dei dati si sceglie solo nell'app: nella modalita' a
    # cartella i dati stanno accanto al programma (o in ANIMEUP_ROOT, che e'
    # una variabile da Terminale).
    if os.environ.get("ANIMEUP_APP") == "1":
        _riga_cartella_dati(congelata)

    voce_tar = taratura.carica()
    if voce_tar:
        import datetime as _dt
        _q = _dt.datetime.fromtimestamp(voce_tar["quando"])
        stato_tar = _q.strftime(t("fmt.data_ora"))
        azione, spazio_link = t("sb.taratura_ripeti"), 42
    else:
        stato_tar, azione, spazio_link = (t("sb.taratura_mai"),
                                          t("sb.taratura_esegui"), 66)
    # Calendario nello stesso tratto delle altre icone di casa (stroke 2).
    _cal = ("<svg width='12' height='12' viewBox='0 0 24 24' fill='none' "
            "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round' aria-hidden='true'>"
            "<rect x='3' y='4' width='18' height='18' rx='2'/>"
            "<line x1='16' y1='2' x2='16' y2='6'/>"
            "<line x1='8' y1='2' x2='8' y2='6'/>"
            "<line x1='3' y1='10' x2='21' y2='10'/></svg>")
    _aiuto_tar = t("sb.taratura_aiuto")
    _perche = _icona_perche(_aiuto_tar)
    with st.sidebar.container(key="cTarRiga"):
        st.markdown(
            f"<div class='au-tar-riga' style='padding-right: "
            f"{spazio_link}px'><span>{t('sb.taratura')}{_perche}</span>"
            f"<span class='au-meta au-tar-data'>{_cal} {stato_tar}</span>"
            f"</div>", unsafe_allow_html=True)
        # DENTRO il contenitore della riga: il CSS che lo posiziona a destra
        # di "Taratura" e' agganciato a `[data-testid="stSidebar"]`, quindi
        # fuori dalla sidebar non aggancia piu' niente e il pulsante finisce
        # in cima all'area principale, orfano della sua etichetta. E' gia'
        # successo: una de-indentazione di quattro spazi durante un lavoro
        # sul CSS lo ha spostato per un giorno intero senza che nessun test
        # se ne accorgesse.
        # Spento durante una lavorazione: la taratura e' un benchmark, e
        # misurare una GPU occupata da' numeri falsi (il passo 1 lo dice
        # gia', ma il pulsante restava cliccabile). In piu' Streamlit ammette
        # UNA sola modale per giro: se il clic cadeva nello stesso giro del
        # resoconto di fine coda, la pagina andava in errore.
        if st.button(azione, key="apriTaratura", disabled=congelata):
            st.session_state.pop("tar_fase", None)
            _modale_taratura()

    st.sidebar.markdown("<style>" + "\n".join(regole) + "</style>",
                        unsafe_allow_html=True)

    attuali = {"altezza": altezza, "crf": crf, "preset": preset,
               "dedup": dedup, "denoise": denoise, "forza": forza,
               "disco": disco, "pausa": pausa,
               "approfondita": approfondita, "lingua": lingua,
               "aggiornamenti": controlla_agg}
    # Persistenza: si scrive solo quando qualcosa e' cambiato davvero.
    if attuali != salvate:
        _impostazioni_scrivi(attuali)

    # Il Riprendi e' blindato (usa la ricetta del file, non la sidebar),
    # quindi qui non c'e' pericolo da annunciare: solo la differenza, con il
    # ripristino a un click per chi vuole riallineare la sidebar.
    if not congelata:
        ricetta = _ricetta_sospesa()
        diversi = _diversi_dal_sospeso(ricetta, attuali)
        if diversi:
            # GIALLO e non grigio: e' un avviso, non una didascalia. Col
            # grigio della nota di congelamento si leggeva come testo di
            # contorno (chiesto dall'utente il 12/08). Niente rosso pero':
            # non c'e' niente di rotto e il Riprendi resta blindato sui
            # parametri suoi — e' informazione, non pericolo.
            with posto_sospeso.container():
                st.markdown(
                    "<div class='au-nota-viva au-nota-avviso'>"
                    f"{t('sb.sospeso', diversi=', '.join(_nomi_impostazioni(diversi)))}"
                    "</div>",
                    unsafe_allow_html=True)
                # Niente `st.rerun()`: il richiamo ne provoca gia' uno, e
                # chiamarlo qui significherebbe scrivere nello stato dal
                # corpo dello script — cioe' il difetto che questa forma
                # evita.
                st.button(t("sb.ripristina"), key="ripristina_parametri",
                          use_container_width=True,
                          on_click=_ripristina_parametri, args=(ricetta,))

    # Il distintivo verde "cartella autonoma" diceva solo che va tutto bene:
    # informazione da zero pixel. Si parla soltanto quando c'e' un problema
    # di portabilità — cioè quando serve davvero saperlo.
    mancanti = [n for n, _t, s in PATHS.portability_report() if s != "ok"]
    if mancanti:
        st.sidebar.divider()
        st.sidebar.markdown(
            f"<span class='au-tag au-warn'>{tn('sb.dipendenze', len(mancanti))}</span>",
            unsafe_allow_html=True)
        st.sidebar.caption(t("sb.non_autonoma"))

    # Chiudere TUTTO da qui: "chiudo la finestra = ho chiuso l'app" è il
    # modello mentale di chiunque, e costringere al Terminale lo tradiva
    # (detto dall'utente). Conferma a due passi con scadenza, come i Ferma.
    # La fascia è ANCORATA in fondo alla sidebar (sticky): prima il
    # pulsante finiva fuori dall'area di scroll e per trovarlo bisognava
    # sapere che c'era — il contenuto ora le scorre sotto.
    st.sidebar.markdown(f"<div class='au-sb-versione'>"
                        f"{t('header.sottotitolo', versione=__version__)}</div>",
                        unsafe_allow_html=True)

    # Nell'app per macOS si esce dal menu (⌘Q), che ferma il server e chiude
    # la finestra insieme: il pulsante spegnerebbe solo il server, lasciando
    # la finestra vuota davanti all'utente.
    if os.environ.get("ANIMEUP_APP") == "1":
        return {"altezza": altezza, "crf": crf, "dedup": dedup, "preset": preset,
                "denoise": denoise, "disco": disco, "forza": forza, "pausa": pausa,
                "approfondita": approfondita}
    with st.sidebar.container(key="spegnimento"):
        conferma_off = st.session_state.get("conferma_spegni")
        spegni_armato = (isinstance(conferma_off, float)
                         and time.time() - conferma_off < 10)
        if not spegni_armato:
            if st.button(t("sb.chiudi"), use_container_width=True,
                         icon=":material/power_settings_new:",
                         help=t("sb.chiudi_aiuto")):
                st.session_state["conferma_spegni"] = time.time()
                st.rerun()
        else:
            # Se una catena è viva va DETTO prima della conferma: chiudere
            # l'interfaccia non la ferma, ed è una feature, ma se lo sai.
            if congelata:
                st.markdown(
                    "<div class='au-gpu-pausa' style='margin-bottom:10px'>"
                    f"{t('sb.chiudi_avviso')}</div>",
                    unsafe_allow_html=True)
            if st.button(t("sb.chiudi_conferma"), use_container_width=True,
                         key="fermasi_app"):
                st.session_state.pop("conferma_spegni", None)
                _spegni_interfaccia(congelata)
            if st.button(t("sb.annulla"), use_container_width=True,
                         key="spegni_annulla"):
                st.session_state.pop("conferma_spegni", None)
                st.rerun()

    return {"altezza": altezza, "crf": crf, "dedup": dedup, "preset": preset,
            "denoise": denoise, "disco": disco, "forza": forza, "pausa": pausa,
            "approfondita": approfondita}


def page_sorgenti(cfg: dict) -> None:
    files = load_library()
    if not files:
        st.markdown(f"#### {t('src.vuoto_titolo')}")
        st.info(t("src.vuoto_testo", cartella=PATHS.input))
        if (nota := _nota_cartella_assente()):
            st.warning(nota)
        app = os.environ.get("ANIMEUP_APP") == "1"
        st.caption(t("src.vuoto_cartella_app" if app else "src.vuoto_cartella_cartella"))
        c1, c2, _ = st.columns([1, 1.4, 3], gap="small")
        if c1.button(t("src.apri_input"), key="apriInput",
                     icon=":material/folder_open:"):
            PATHS.input.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(PATHS.input)], check=False)
        if app:
            c2.button(t("src.scegli_cartella"), key="sceltaCartellaVuoto",
                      icon=":material/drive_folder_upload:",
                      on_click=_scegli_cartella_dati)
            if st.session_state.get("cartella_cambiata"):
                st.caption(t("sb.cartella_riavvia",
                             cartella=_breve(st.session_state["cartella_cambiata"])))
        return

    alta = sum(1 for f in files if f["height"] >= CLEAN_SOURCE_MIN_HEIGHT)
    # `duration_hms` produce MM:SS sotto l'ora e H:MM:SS sopra. Leggendo
    # sempre i primi due campi come minuti e secondi, un film da 1h05
    # contribuiva 65 secondi al totale e otto file diventavano "00:01:33".
    def _secondi(testo: str) -> int:
        parti = [p for p in testo.split(":") if p.strip().isdigit()]
        totale = 0
        for parte in parti:                 # H:MM:SS oppure MM:SS, indifferente
            totale = totale * 60 + int(parte)
        return totale

    durata = sum(_secondi(f["duration"]) for f in files)

    # Titolo e sottotitolo come nelle altre due schede: erano l'unica
    # pagina senza, e chi arriva qui per la prima volta non aveva una riga
    # che gli dicesse cosa sta guardando (chiesto dall'utente).
    st.markdown(
        f"<div class='au-sezione'>{t('src.titolo')}</div>"
        "<div class='au-hint' style='margin-bottom:20px'>"
        f"{t('src.sottotitolo')}</div>",
        unsafe_allow_html=True)

    # Una fascia al posto di titolo + paragrafo + tre riquadri di spiegazione.
    # Quei tre elementi dicevano in venti righe quello che qui sta in una, e
    # occupavano la parte alta della pagina — cioè il posto dove si guarda per
    # primo — con testo che si legge una volta sola nella vita dello strumento.
    # Il conteggio dell'analisi è l'unica cosa che cambia nel tempo, ed è
    # l'unica che ha diritto di stare in alto.
    chip = []
    if alta:
        chip.append(f"<span class='au-tag au-dim'>{alta} &ge; "
                    f"{CLEAN_SOURCE_MIN_HEIGHT}p</span>")
    # La soglia scritta nella chip: «N sotto soglia» lasciava indovinare
    # quale, mentre la chip accanto la dice («≥ 560p»).
    if len(files) - alta:
        chip.append(f"<span class='au-tag au-dim'>"
                    f"{t('src.sotto_soglia', n=len(files) - alta, soglia=CLEAN_SOURCE_MIN_HEIGHT)}"
                    "</span>")
    # Conta i FILE, non gli avvisi: chiave sua e parole sue, perche' la chip
    # della riga ha lo stesso aspetto ma conta gli avvisi di quel file, e con
    # lo stesso «N avvisi» due numeri diversi si leggevano come uno.
    con_avvisi = sum(1 for f in files
                     if (r := library.cached_report(Path(f["path"]))) and r.warnings())
    if con_avvisi:
        chip.append(f"<span class='au-tag au-warn'>"
                    f"{tn('src.file_con_avvisi', con_avvisi)}</span>")
    analizzati = sum(1 for f in files
                     if library.cached_report(Path(f["path"])) is not None)
    # Lo stato dell'analisi serve gia' qui, per la fascia in alto. La coda
    # e' gia' stata accodata da `main`, per tutte le schede: qui si legge e
    # basta.
    lavoro = analizzatore()
    corrente, in_coda = lavoro.in_corso, lavoro.in_coda
    # La struttura (contenitore con chiave + due colonne) NON cambia mai
    # forma fra i due stati: e' la lezione dei pannelli doppi — un elemento
    # che compare e scompare sposta la conta posizionale e Streamlit adotta
    # nodi altrui. Cambia solo il CONTENUTO della colonna destra: barra di
    # avanzamento mentre si analizza, CTA "Rianalizza tutti" a riposo (una
    # barra piena in eterno non informava di niente, detto dall'utente).
    with st.container(key="fasciaSorgenti"):
        fs1, fs2 = st.columns([5, 1])
        fs1.markdown(
            f"<div class='au-fascia au-fascia-nuda'>"
            f"<b>{tn('src.file_in_input', len(files))}</b>"
            f"<span class='au-meta'>{t('src.di_video', durata=hms(durata))}</span>"
            f"{''.join(chip)}</div>", unsafe_allow_html=True)
        # `al_lavoro` e non il solo conteggio dei referti: chiedendo una
        # RIANALISI i referti vecchi restano (di proposito, cosi' l'elenco
        # non si svuota), quindi "analizzati" era gia' al massimo e in alto
        # restava la CTA come se non stesse succedendo niente — mentre
        # sotto le righe dicevano "in coda" (visto dall'utente).
        da_fare = len(in_coda) + (1 if corrente else 0)
        if lavoro.al_lavoro or analizzati < len(files):
            # `max(0, ...)`: la coda dell'analizzatore puo' contenere file
            # spariti da INPUT nel frattempo, e "analisi -1/5" con la barra
            # a larghezza negativa e' un modo curioso di informare.
            fatti = max(0, min(analizzati, len(files) - da_fare))
            fs2.markdown(
                f"<span class='au-fascia-dx'><span class='au-meta'>"
                f"{t('src.analisi_conta', fatti=fatti, totale=len(files))}</span>"
                f"<span class='au-barra'><span style='width:"
                f"{fatti / max(1, len(files)) * 100:.0f}%'></span>"
                f"</span></span>", unsafe_allow_html=True)
        elif fs2.button(t("src.rianalizza_tutti"), key="rianTutti",
                        icon=":material/refresh:",
                        help=t("src.rianalizza_tutti_aiuto")):
            analizzatore().accoda([Path(f["path"]) for f in files],
                                  approfondita=cfg.get("approfondita", True),
                                  rifai=True)
            st.rerun()



    # L'analisi parte da sola, in ordine, mentre si guarda l'elenco: costa una
    # ventina di secondi a file e non ha senso farla pagare all'utente un
    # pulsante alla volta.
    # L'avviso sta PRIMA dell'elenco, non in fondo: dice cosa sta succedendo
    # adesso, e in fondo alla pagina lo si legge quando non serve più. Stesso
    # giallo della chip sulla riga, così i due si riconoscono come la stessa
    # cosa a due livelli di dettaglio.
    # Il contenitore c'e' SEMPRE, anche quando non c'e' niente da dire. È
    # quello che risolve i pannelli doppi: comparendo, la fascia inseriva un
    # elemento prima dell'elenco e spostava tutto di una posizione, e per un
    # fotogramma Streamlit assegnava il pannello aperto alla riga precedente.
    # Misurato: 9 fotogrammi su 23 con due pannelli, sempre uno nella riga
    # sopra. Con il contenitore fisso l'albero non cambia forma.
    with st.container(key="fasciaAnalisi"):
        if lavoro.al_lavoro:
            rimasti = len(in_coda) + (1 if corrente else 0)
            st.markdown(
                "<div class='au-avviso'><span class='au-rotella'></span>"
                f"{tn('src.analisi_in_corso', rimasti)}</div>",
                unsafe_allow_html=True)

    pesi = [4.6, 1.2, 0.9, 3.6, 0.5]
    with st.container(key="intest"):
        for col, label in zip(st.columns(pesi),
                              [t("src.col_file"), t("src.col_risoluzione"),
                               t("src.col_durata"), t("src.col_analisi"), ""]):
            col.markdown(f"<span class='au-eyebrow'>{label}</span>",
                         unsafe_allow_html=True)

    for i, f in enumerate(files):
        path = Path(f["path"])
        rep = library.cached_report(path)
        # Un insieme e non un percorso solo: confrontando file diversi si
        # vogliono due schede sotto gli occhi insieme, non una alla volta.
        aperti = st.session_state.setdefault("dettagli", set())
        aperto = str(path) in aperti

        # Lo stato NON sta nella chiave del contenitore. Ci stava, e cambiando
        # (per esempio da `fatto` a `corso` premendo Rianalizza) cambiava la
        # chiave: Streamlit costruiva un sottoalbero nuovo e lasciava in pagina
        # quello vecchio, coi suoi dettagli aperti. Si vedevano due pannelli,
        # entrambi con chiave `st-key-dett1`, e sembrava che si aprisse la
        # riga sopra. Ora la chiave è fissa e lo stato viaggia su un segno
        # invisibile dentro la riga, che il CSS legge con `:has()`.
        if str(path) == corrente:
            stato = "corso"
        elif str(path) in in_coda or rep is None:
            # `in_coda` PRIMA di `rep`: chiedendo una rianalisi il referto
            # c'e' gia', e la riga restava identica a prima — nessun segno
            # che la richiesta fosse stata presa in carico (visto
            # dall'utente il 2026-08-10).
            stato = "coda"
        elif rep.warnings():
            stato = "avviso"
        else:
            stato = "fatto"

        # L'indice e non il nome del file: i nomi contengono spazi e parentesi
        # che non sopravvivono a un nome di classe CSS.
        with st.container(key=f"riga{i}"):
            # Due segni invisibili: lo stato e l'apertura. Il secondo esiste
            # perché il pannello ora è SEMPRE montato (vedi sotto), quindi
            # "aperto" non si può più dedurre dalla sua presenza.
            st.markdown(f"<span class='au-stato au-s-{stato}"
                        f"{' au-open' if aperto else ''}'></span>",
                        unsafe_allow_html=True)
            c = st.columns(pesi)
            c[0].markdown(f"<div class='au-name'>{esc(f['name'])}</div>"
                          f"<div class='au-meta'>{f['codec']} · {f['size_mb']:.0f} MB</div>",
                          unsafe_allow_html=True)
            c[1].markdown(f"<div class='au-cell'>{f['resolution']}</div>",
                          unsafe_allow_html=True)
            c[2].markdown(f"<div class='au-cell'>{f['duration']}</div>",
                          unsafe_allow_html=True)

            if str(path) == corrente:
                # Gialla, non grigia: a colpo d'occhio si deve vedere DOVE sta
                # lavorando, non solo che qualcosa sta lavorando.
                c[3].markdown(
                    "<span class='au-tag au-warn au-lavoro'>"
                    f"<span class='au-rotella'></span>{t('src.riga_in_corso')}</span>",
                    unsafe_allow_html=True)
            elif str(path) in in_coda:
                c[3].markdown(
                    f"<span class='au-tag au-dim'>{t('src.riga_in_coda')}</span>",
                    unsafe_allow_html=True)
            elif rep is None:
                c[3].markdown(
                    f"<span class='au-tag au-dim'>{t('src.riga_da_analizzare')}</span>",
                    unsafe_allow_html=True)
            else:
                # UNA riga di sintesi, non tre. Il framerate esatto, il SAR e
                # il resto stanno nel pannello dei dettagli: in elenco erano
                # tre righe di pari peso che facevano crescere la riga e
                # seppellivano il nome del file. La gerarchia è nome →
                # risoluzione e durata → avviso; questa sintesi si legge solo
                # se la si cerca.
                # Solo "23.976", senza "(24000/1001)": la frazione esatta è
                # nel pannello, qui ruberebbe metà riga per un dato che in
                # elenco non si confronta mai.
                breve = fps_str(rep.timing.fps).split(" (")[0]
                sintesi = [f"{breve} {t(f'enum.ritmo.{rep.timing.mode.value}')}",
                           f"{rep.bit_depth} bit {_chroma(rep.pix_fmt)}"]
                if rep.fields and rep.fields.mode is not FieldMode.PROGRESSIVE:
                    sintesi.append(t(f"enum.campi.{rep.fields.mode.value}"))
                if rep.color_space:
                    sintesi.append(rep.color_space)
                tracce = []
                if rep.audio_tracks:
                    tracce.append(t("src.tracce_audio", n=rep.audio_tracks))
                if rep.subtitle_tracks:
                    tracce.append(t("src.tracce_sub", n=rep.subtitle_tracks))
                if rep.chapters:
                    tracce.append(t("src.tracce_capitoli", n=rep.chapters))
                if tracce:
                    sintesi.append(", ".join(tracce))

                avvisi = rep.warnings()
                blocco = f"<div class='au-meta'>{esc(' · '.join(sintesi))}</div>"
                if avvisi:
                    blocco += (f"<div><span class='au-tag au-warn au-chip-riga'>"
                               f"{tn('src.avvisi', len(avvisi))}</span></div>")
                c[3].markdown(blocco, unsafe_allow_html=True)

            # La chevron è l'unico comando della riga chiusa. "Rianalizza"
            # è migrato dentro il pannello: in testata erano due icone
            # affiancate, e quella rara rubava attenzione a quella che si usa
            # sempre. Dentro il pannello è anche un pulsante con una parola
            # sopra, invece di un simbolo da interpretare.
            # I triangolini piccoli (▾ ▴) si allineano al testo, quelli
            # grandi (▼ ▲) siedono sotto la linea di base.
            # Icona di sistema e non il carattere "▾": quel triangolo è un
            # glifo tipografico, pesante e senza grazia. Niente `help`: il
            # suggerimento comparendo copriva la riga per dire una cosa che si
            # capisce dalla freccia.
            # Senza referto la chevron non ha niente da aprire: si SPEGNE e
            # si nasconde via CSS, ma il pulsante resta nel DOM — un widget
            # che compare e scompare a fine analisi cambia la conta
            # posizionale, e quella strada porta al brodo di nodi adottati.
            if c[4].button(
                "", key=f"det{i}", use_container_width=True,
                disabled=rep is None,
                icon=(":material/keyboard_arrow_up:" if aperto
                      else ":material/keyboard_arrow_down:"),
            ):
                aperti.discard(str(path)) if aperto else aperti.add(str(path))
                st.rerun()

            # Il pannello si costruisce SEMPRE, non solo quando è aperto:
            # chiuso resta in pagina a altezza zero. È l'unico modo per
            # animare anche la chiusura — un nodo che al rerun sparisce non
            # può dissolversi, e infatti prima si spegneva di colpo. Costa
            # una ventina di valori di testo per riga, già in memoria.
            if rep is not None:
                with st.container(key=f"dett{i}"):
                    # Il contenitore interno non è decorativo: l'animazione di
                    # apertura anima UNA traccia di griglia, e senza questo il
                    # pannello ne avrebbe sette (una per gruppo) — si apriva
                    # solo il primo e il resto compariva di scatto.
                    with st.container():
                        testa, fondo, azione = st.columns([3, 1.35, 1])
                        testa.markdown(
                            "<div class='au-pan-titolo'>"
                            f"{t('src.dettagli')}</div>", unsafe_allow_html=True)
                        # L'analisi normale non misura la deduplica: la
                        # dedurrebbe dai file gia' lavorati, e quel criterio
                        # pesca il fratello sbagliato (voce 84). Misurarla
                        # costa da 11 a 69 secondi secondo la risoluzione, e
                        # non si puo' far pagare a ogni file in cartella —
                        # compresi quelli che non verranno mai convertiti.
                        # Quindi si chiede, per il file che interessa.
                        gia_misurata = getattr(rep, "dedup_campione", None)
                        # Col toggle acceso l'approfondita la fa gia'
                        # l'analisi: un pulsante per chiederla sarebbe un
                        # comando che non fa niente.
                        sempre = cfg.get("approfondita", True)
                        if gia_misurata is not None:
                            fondo.markdown(
                                f"<div class='au-tag au-ok' "
                                f"style='margin-top:6px'>"
                                f"{t('src.dedup_misurata', quota=f'{gia_misurata:.0%}')}"
                                "</div>",
                                unsafe_allow_html=True)
                        # «In corso» solo se lo e' DAVVERO. Su un file troppo
                        # corto la misura non riesce, la coda lo scarta e non
                        # riprova: la prima versione avrebbe lasciato «misura
                        # in corso...» a schermo per sempre, che e' una bugia
                        # tranquilla — di quelle che si scoprono solo
                        # aspettando invano.
                        elif sempre and (str(path) == lavoro.in_corso
                                         or str(path) in lavoro.in_coda):
                            fondo.markdown(
                                "<div class='au-hint' style='margin-top:8px'>"
                                f"{t('src.misura_in_corso')}</div>",
                                unsafe_allow_html=True)
                        elif sempre:
                            fondo.markdown(
                                "<div class='au-hint' style='margin-top:8px'>"
                                f"{t('src.dedup_non_misurabile')}</div>",
                                unsafe_allow_html=True)
                        elif fondo.button(
                                t("src.approfondita"),
                                icon=":material/query_stats:",
                                key=f"appr{i}",
                                use_container_width=True,
                                help=t("src.approfondita_aiuto")):
                            lavoro.accoda_approfondita([path])
                            st.rerun()
                        # Serve quando il file cambia ma tiene lo stesso nome,
                        # o per ricontrollare senza fidarsi di quanto salvato.
                        # `icon=` e non ":material/refresh:" dentro
                        # l'etichetta: lì resta la parola "refresh" in Inter,
                        # perché il font delle icone non viene applicato.
                        if azione.button(t("src.rianalizza"), icon=":material/refresh:",
                                         key=f"ric{i}",
                                         help=t("src.rianalizza_aiuto")):
                            lavoro.accoda([path], rifai=True)
                            st.rerun()
                        _dettagli(rep)

    # Finché c'e' lavoro, la pagina si riguarda da sola: è l'unico modo per
    # far avanzare gli stati, dato che il thread non può toccare la pagina.
    # Un'attesa breve e poi un rerun, non un ciclo: così l'interfaccia resta
    # reattiva ai clic in mezzo.
    if lavoro.al_lavoro:
        time.sleep(1.5)
        st.rerun()


def _dettagli(rep) -> None:
    """Il pannello dei dettagli, con UNA sola gerarchia.

    Prima erano due sistemi mescolati: i widget `metric` di Streamlit, che
    hanno una dimensione loro enorme e troncano il valore con i puntini, e
    sotto delle righe di testo minuto. Alcuni dati giganti, altri quasi
    illeggibili, e il più lungo — il framerate — tagliato proprio dal widget
    più grande. Qui tutte le etichette hanno lo stesso stile e tutti i valori
    pure, con una dimensione che ci sta.
    """
    # Terzo campo: se il valore merita attenzione. Sono i dati che cambiano il
    # risultato — la geometria d'uscita, il colore da indovinare — e chi apre
    # i dettagli sta cercando proprio quelli.
    g = rep.geometry
    intreccio = rep.fields and rep.fields.mode is not FieldMode.PROGRESSIVE
    gruppi = [
        (t("det.tempi"), [
            # Senza " fps": l'etichetta dice già FRAMERATE, e quelle tre
            # lettere mandavano il valore a capo dentro la colonna.
            (t("det.framerate"), fps_str(rep.timing.fps), False),
            (t("det.ritmo"), t(f"enum.ritmo.{rep.timing.mode.value}"),
             rep.timing.mode.value != "cfr"),
            (t("det.fotogrammi"),
             f"{rep.timing.packets:,}".replace(",", t("fmt.migliaia")), False),
            (t("det.durata"), hms(rep.duration), False),
        ]),
        (t("det.immagine"), [
            (t("det.geometria"), f"{g.width}×{g.height}", False),
            (t("det.pixel"), (t("det.pixel_non_quadri", sar=g.sar,
                                larghezza=g.display_width,
                                altezza=g.display_height)
                              if g.anamorphic else t("det.pixel_quadri")),
             g.anamorphic),
            (t("det.formato"), f"{rep.pix_fmt} · {rep.bit_depth} bit", False),
            # Niente giallo: un sorgente senza tag colore non e' un
            # problema, e' un dato mancante che AnimeUp copre da solo con
            # la convenzione (601 sotto i 720p, 709 sopra) scrivendo poi i
            # tag espliciti nell'uscita. Il giallo si tiene per i problemi
            # veri, o smette di volere dire qualcosa.
            (t("det.colore"), rep.color_space or t("det.non_dichiarato"), False),
        ]),
        (t("det.tracce"), [
            (t("det.audio"), str(rep.audio_tracks), False),
            (t("det.sottotitoli"),
             (f"{rep.subtitle_tracks} ({', '.join(rep.subtitle_codecs)})"
              if rep.subtitle_codecs else str(rep.subtitle_tracks)), False),
            (t("det.capitoli"), str(rep.chapters), False),
            (t("det.campi"), (t(f"enum.campi.{rep.fields.mode.value}")
                              if rep.fields else t("det.non_analizzati")),
             bool(intreccio)),
        ]),
    ]

    # Tutto il pannello in UN blocco di HTML, non un `st.markdown` per gruppo.
    # Con una chiamata per gruppo Streamlit inserisce un contenitore per
    # ciascuna, con i suoi margini, e i gruppi finivano distanziati in modo
    # diverso da come sono impaginati dentro. Qui il markup è nostro dal
    # titolo all'ultimo valore, quindi la griglia è esattamente quella
    # dichiarata.
    pezzi = []
    for titolo, voci in gruppi:
        celle = "".join(
            f"<div class='au-voce'><span class='au-etichetta'>{esc(k)}</span>"
            f"<span class='au-valore{' au-attenzione' if occhio else ''}'>"
            f"{esc(v)}</span></div>"
            for k, v, occhio in voci
        )
        pezzi.append(f"<div class='au-blocco'><div class='au-gtitolo'>{titolo}</div>"
                     f"<div class='au-griglia'>{celle}</div></div>")

    for w in rep.warnings():
        pezzi.append(f"<div class='au-avviso'><span class='au-icona'>&#9888;</span>"
                     f"{esc(w)}</div>")

    st.markdown("".join(pezzi), unsafe_allow_html=True)


# ===========================================================================
#  2 · Confronto
# ===========================================================================

def page_confronto(cfg: dict) -> None:
    st.markdown(
        f"<div class='au-sezione'>{t('conf.titolo')}</div>"
        "<div class='au-hint' style='margin-bottom:20px'>"
        f"{t('conf.intro')}</div>",
        unsafe_allow_html=True)

    files = load_library()
    if not files:
        st.info(t("conf.nessun_file"))
        return

    # La selezione vive nella CHIAVE del widget, non in un doppione che poi
    # rientra da `index=`. Il giro precedente — leggere lo stato, calcolare
    # `index`, riscrivere lo stato — cambiava l'identita' del widget a ogni
    # cambio di default: se fra il clic e la sua elaborazione arrivava un
    # rerun (l'estrazione degli spezzoni ne fa), il clic veniva applicato al
    # widget vecchio e scartato, e la tendina tornava sul file di prima.
    percorsi = [f["path"] for f in files]
    nomi = {f["path"]: f["name"] for f in files}
    if st.session_state.get("file_confronto") not in percorsi:
        st.session_state.pop("file_confronto", None)
    # `ch` e non pixel: è la larghezza del carattere corrente, quindi la
    # stima regge anche se un giorno cambia il corpo del testo. Il minimo
    # evita una tendina ridicola quando i nomi sono corti, il massimo la tiene
    # dentro la colonna quando sono assurdi.
    piu_lungo = max((len(f["name"]) for f in files), default=40)
    st.markdown(
        "<style>.st-key-campoFile [data-testid=\"stSelectbox\"] "
        f"{{ width: clamp(360px, calc({piu_lungo}ch + 72px), 100%); }}</style>",
        unsafe_allow_html=True)
    with st.container(key="campoFile"):
        st.markdown(f"<div class='au-eyebrow au-sez'>{t('conf.file_da_provare')}</div>",
                    unsafe_allow_html=True)
        prescelto = st.selectbox(t("conf.file_da_provare"), percorsi,
                                 key="file_confronto",
                                 format_func=lambda pth: nomi[pth],
                                 label_visibility="collapsed")
    entry = next(f for f in files if f["path"] == prescelto)
    path = Path(entry["path"])

    # Misurati il 12/08: 8,9s su un 360p, 37s su un 720p, 49s su un 1080p,
    # tutti episodi da circa 25 minuti. Il "~15 secondi" di prima era una
    # sottostima di tre volte sul caso peggiore.
    with st.spinner(t("conf.analisi")):
        try:
            plan = plan_for(path, cfg, entry["height"])
        except (PlanError, OSError, FFmpegError, ValueError) as exc:
            st.error(str(exc))
            return

    # Tre valori affiancati in un riquadro solo, largo quanto il contenuto.
    # `st.metric` li scriveva alla sua misura — enorme — e con tre righe di
    # etichetta sopra: pesavano più dell'elenco dei modelli, che è la cosa da
    # cui si decide.
    # Stesso formato delle stime in Lavorazione: ore e minuti, niente
    # secondi — coerenza fra le schede, stessa ragione.
    intero = (f"{stima_hm(plan.est_best_seconds)} / "
              f"{stima_hm(plan.est_total_seconds)}"
              if plan.est_best_seconds < plan.est_total_seconds * 0.95
              else stima_hm(plan.est_total_seconds))
    st.markdown(
        "<div class='au-stat'>"
        f"<div><dt>{t('conf.stat_sorgente')}</dt><dd>{esc(entry['resolution'])}</dd></div>"
        f"<div><dt>{t('conf.stat_uscita')}</dt>"
        f"<dd>{plan.target_width}×{plan.target_height}</dd></div>"
        # Due durate e non una: senza spiegazione sembrano un errore. Il
        # suggerimento è nativo del browser (`title`) perché qui il markup è
        # nostro e quello di Streamlit vive solo dentro i suoi controlli.
        f"<div><dt>{t('conf.stat_episodio')}"
        f"<span class='au-perche' tabindex='0'>"
        # Lo stesso disegno del suggerimento nativo della sidebar, copiato dal
        # DOM: cerchio, gancio e punto, tratto da 2. Un "?" scritto come testo
        # non gli somigliava, ed era grande la metà.
        "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' "
        "stroke-linejoin='round' aria-hidden='true'>"
        "<circle cx='12' cy='12' r='10'></circle>"
        "<path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'></path>"
        "<line x1='12' y1='17' x2='12.01' y2='17'></line></svg>"
        + _bolla(t("conf.stat_episodio_aiuto")) +
        "</span></dt>"
        # Niente suffisso "h": il nuovo formato porta già le unità dentro
        # ("02h 30m"), e un "h" in coda le raddoppierebbe.
        f"<dd>{intero}</dd></div>"
        "</div>", unsafe_allow_html=True)


    # La praticabilita' REALE di ogni modello con le impostazioni correnti,
    # calcolata UNA volta e rispettata da tutta la pagina (schede, consiglio
    # nell'espansore, caselle): prima le caselle si spegnevano ma il resto
    # continuava a pubblicizzare modelli che non arrivano al bersaglio
    # (visto dall'utente sul 400p in fascia intermedia).
    praticabili: dict[str, str] = {}
    for k in CATALOG:
        try:
            build_plan(plan.source, target_height=cfg["altezza"],
                       crf=cfg["crf"], preset=cfg["preset"],
                       peak_disk_gb=cfg["disco"], dedup=cfg["dedup"],
                       denoise=cfg["denoise"], forza=cfg["forza"],
                       model_key=k)
            praticabili[k] = ""
        except (PlanError, ValueError) as exc:
            praticabili[k] = str(exc)

    # Ogni scheda porta il giudizio della SUA fascia: consigliato (verde),
    # da verificare (giallo), sconsigliato (rosso), o niente. Prima la chip
    # stava solo sul vincitore, e nella fascia intermedia "da verificare"
    # finiva sul consigliato stesso — il contrario di quello che significa.
    giudizi = (plan.recommendation.giudizi or {}) if plan.recommendation else {}
    CHIP = {"ok": f"<span class='au-tag au-ok'>{t('conf.chip_ok')}</span>",
            "verifica": f"<span class='au-tag au-warn'>{t('conf.chip_verifica')}</span>",
            "no": f"<span class='au-tag au-err'>{t('conf.chip_no')}</span>"}
    BORDO_SCHEDA = {"ok": " au-consigliato", "verifica": " au-verifica",
                    "no": " au-sconsigliato"}
    schede = []
    for chiave, modello in CATALOG.items():
        giudizio = giudizi.get(chiave)
        chip = CHIP.get(giudizio, "")
        morta = bool(praticabili.get(chiave))
        if morta:
            # L'impossibilita' vince sul giudizio: e' aritmetica, non
            # opinione. E niente velocita': la stima di un'opzione
            # impossibile e' solo pubblicita' ingannevole.
            chip = ("<span class='au-tag au-dim'>"
                    f"{t('conf.chip_non_arriva', altezza=plan.target_height)}"
                    "</span>")
        # Alla scala che QUESTO modello userebbe davvero, non a quella del
        # piano: CUGAN denoise leggero esiste solo a scala 2, quindi chiedendo
        # la scala del piano non trovava niente e restava senza velocità.
        scala = preview.scale_for(chiave, plan)
        mpx_s = modello.throughput.get(scala, min(modello.throughput.values()))
        # In fotogrammi al secondo su questo file, non in megapixel al secondo:
        # i Mpx/s sono l'unita' con cui il motore fa i conti, ma per decidere
        # servono i fotogrammi. `throughput` è riferito ai pixel in INGRESSO.
        src_mpx = plan.source.geometry.width * plan.source.geometry.height / 1e6
        velocita = mpx_s / src_mpx if src_mpx else None
        schede.append(
            f"<div class='au-modello"
            f"{' au-spenta' if morta else BORDO_SCHEDA.get(giudizio, '')}'>"
            f"<div class='au-m-testa'><span class='au-m-nome'>{esc(modello.label)}</span>"
            f"{chip}</div>"
            f"<div class='au-m-desc'>{esc(modello.description)}</div>"
            # «(solo fasi di upscale)» e non «per l'intero file»: il numero e'
            # `fotogrammi / velocita`, cioe' il tempo del solo ingrandimento —
            # niente deduplica, niente codifica, niente turni fra i blocchi.
            # Il riquadro qui sopra dice EPISODIO INTERO e quello e' il totale
            # vero. Due quantita' diverse con parole quasi uguali: a 1080p la
            # differenza e' piccola (11m contro 13m) e non si nota, a 1440p
            # diventa 11m contro 20m e chi legge pensa a un errore.
            # La scheda serve a CONFRONTARE i modelli fra loro, e per quello
            # il solo upscale e' il numero giusto: deduplica e codifica sono
            # identiche qualunque modello si scelga, e sommarle appiattirebbe
            # proprio la differenza che si sta guardando.
            + (f"<div class='au-m-vel'>"
               f"{t('conf.velocita', fps=f'{velocita:.1f}', durata=stima_hm(plan.frames / velocita))}"
               f"</div>"
               if velocita and not morta else "")
            + "</div>")
    # Etichetta e griglia nello STESSO blocco: separate, la distanza fra le
    # due la decide la spaziatura fra elementi di Streamlit, che vale 14px
    # davanti a un controllo (che ha il suo padding) e 0 davanti a del markup
    # nudo — infatti la card finiva 6px SOPRA l'etichetta. Insieme, la
    # distanza è quella dichiarata e basta.
    st.markdown(
        f"<div class='au-eyebrow au-sez-int'>{t('conf.modelli_disponibili')}</div>"
        f"<div class='au-modelli'>{''.join(schede)}</div>",
        unsafe_allow_html=True)
    # Prima QUESTO caso, poi la regola generale. L'accordion diceva solo la
    # teoria, e chi lo apre l'ha aperto per sapere perché è stato scelto
    # quel modello per QUESTO file — la teoria è il seguito, non la risposta.
    rec = plan.recommendation
    # Un'etichetta sola per tutti i casi: è la domanda a cui il pannello
    # risponde. "Perché va verificato" presupponeva che l'utente sapesse già
    # cosa andava verificato.
    # L'accordion prende il colore dello stato: giallo quando la fascia è
    # incerta, neutro quando il consiglio è sicuro. Su fondo uguale al resto
    # passava inosservato proprio nel caso in cui va letto.
    # Il "dipende" della fascia intermedia ha senso solo se l'alternativa
    # e' davvero praticabile: se non arriva al bersaglio, il dubbio e'
    # morto e il pannello torna neutro.
    dubbio = bool(rec and not rec.sicuro
                  and not praticabili.get("cugan-denoise"))
    with st.container(key=("perche_att" if dubbio else "perche_ok")):
        with st.expander(t("conf.quale_modello")):
            if rec:
                # Tre frasi, non un muro: in quale fascia sei, cosa usare,
                # cosa fare se la fascia è incerta.
                h = plan.source.geometry.height
                if h >= CLEAN_SOURCE_MIN_HEIGHT:
                    fascia_t = t("conf.caso.sopra_fascia",
                                 altezza=CLEAN_SOURCE_MIN_HEIGHT)
                    scelta = t("conf.caso.sopra_scelta")
                    spiega = t("conf.caso.sopra_spiega")
                elif h >= ALTEZZA_INCERTA:
                    fascia_t = t("conf.caso.mezzo_fascia", da=ALTEZZA_INCERTA,
                                 a=CLEAN_SOURCE_MIN_HEIGHT)
                    if praticabili.get("cugan-denoise"):
                        # L'alternativa della fascia non arriva al bersaglio
                        # con le impostazioni attuali: niente "dipende", e
                        # si dice PERCHE' il dubbio non esiste piu'.
                        scelta = t("conf.caso.usa_esrgan")
                        spiega = t("conf.caso.mezzo_bloccato", h=h,
                                   altezza=plan.target_height)
                    else:
                        # Il titolo è la domanda vera di questa fascia, non
                        # un "usa X" che contraddirebbe il "dipende" sotto.
                        scelta = t("conf.caso.mezzo_scelta")
                        spiega = t("conf.caso.mezzo_spiega")
                else:
                    fascia_t = t("conf.caso.sotto_fascia",
                                 altezza=ALTEZZA_INCERTA)
                    scelta = t("conf.caso.usa_esrgan")
                    spiega = t("conf.caso.sotto_spiega")
                colore = "verde" if not dubbio else "giallo"
                st.markdown(
                    f"<div class='au-p-caso au-p-{colore}'>"
                    f"<div class='au-eyebrow'>"
                    f"{esc(t('conf.caso.questo_file', h=h, fascia=fascia_t))}</div>"
                    f"<div class='au-p-scelta'>{esc(scelta)}</div>"
                    f"<div class='au-p-motivo'>{esc(spiega)}</div></div>",
                    unsafe_allow_html=True)
            # La regola generale STA nell'accordion: fuori era un secondo
            # blocco che fluttuava da solo sotto un pannello chiuso.
            st.markdown("<div class='au-eyebrow' style='margin:18px 0 10px'>"
                        f"{t('conf.regola')}</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='au-p-regole'>" + "".join(
                    f"<div class='au-p-riga au-p-{colore}'>"
                    f"<div class='au-p-fascia'>{esc(fascia)}</div>"
                    f"<div><span class='au-p-mod'>{esc(modello)}</span>"
                    f"<span class='au-p-testo'> — {esc(testo)}</span></div></div>"
                    for fascia, colore, modello, testo in perche_generale(
                        plan.target_height, bool(cfg.get("forza"))))
                + "</div>", unsafe_allow_html=True)
            st.markdown("<div class='au-hint' style='margin-top:14px'>"
                        f"{t('conf.regola_nota')}</div>", unsafe_allow_html=True)

    _spezzoni(plan, path, cfg, praticabili)


# Oltre questa soglia si rinuncia al video incorporato: un data URI enorme
# gonfia la pagina, e a quel punto meglio i comandi brutti che una pagina lenta.
TETTO_VIDEO_MB = 4.0


def _video_ciclico(f: Path) -> bool:
    """Uno spezzone in ciclo, senza i comandi del riproduttore.

    `st.video` scrive `controls` nel tag e non si può togliere: è fissato nel
    frontend di Streamlit. Nasconderlo col CSS funziona su Chrome ma non su
    Safari, che dalle ultime versioni blinda la shadow DOM del riproduttore e
    ignora le pseudo-classi `::-webkit-media-controls-*`. L'unico modo che vale
    su tutti i browser è non chiedere i comandi: qui il tag lo scriviamo noi.

    Il file viaggia come data URI perché l'indirizzo servito da Streamlit è
    interno e cambia di versione in versione; incorporarlo costa un terzo in
    più di byte e non dipende da niente. Ritorna False se non ce la fa, così
    chi chiama può ripiegare.
    """
    try:
        dati = f.read_bytes()
    except OSError:
        return False
    if len(dati) > TETTO_VIDEO_MB * 1024 * 1024:
        return False
    b64 = base64.b64encode(dati).decode("ascii")
    st.markdown(
        f"<video class='au-clip' src='data:video/mp4;base64,{b64}' "
        f"autoplay loop muted playsinline></video>", unsafe_allow_html=True)
    return True


def _spezzoni(plan, path: Path, cfg: dict,
              praticabili: dict[str, str] | None = None) -> None:
    praticabili = praticabili or {}
    chiave = f"cand_{path}"
    # La scansione ora lascia traccia su disco: se l'interfaccia è stata
    # ricaricata (o riavviata) a metà lavoro, i minuti spesi non sono persi e
    # non serve ricliccare. Prima il risultato viveva solo in sessione, e un
    # riavvio riportava alla schermata iniziale senza errore e senza spiegazioni.
    if chiave not in st.session_state:
        try:
            # Prima il deposito (l'elenco COMPLETO, tutti i lotti); se manca —
            # file scansionati prima che il deposito esistesse — si ripiega
            # sullo schedario del primo lotto.
            recuperati = preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS,
                                                PATHS)
            if not recuperati:
                schedario = preview._schedario(plan, 2, preview.DEFAULT_SECONDS,
                                               PATHS)
                if schedario.is_file():
                    recuperati = preview._leggi_schedario(schedario,
                                                          float(plan.fps))
            if recuperati:
                st.session_state[chiave] = recuperati
                # E anche la memoria dei GIA' VISTI, che prima non si
                # recuperava: senza, il pulsante tornava a dire «trova gli
                # spezzoni» e ripescava dalla cassa gli stessi otto, che
                # finivano AGGIUNTI a quelli gia' in pagina — otto card
                # doppie dopo un semplice ricaricamento.
                st.session_state[f"visti_{path}"] = tuple(
                    c.start_frame for c in recuperati)
                st.session_state.setdefault(f"thumbs_{path}", {})
        except OSError:
            pass

    # Il contenitore serve al CSS per centrare la chip sul pulsante: le
    # colonne di Streamlit si allineano in alto, e la chip restava appesa.
    with st.container(key="avvio"):
        avvio, esito = st.columns([1, 3])
        if candidati_gia := st.session_state.get(chiave):
            esito.markdown(
                f"<span class='au-tag au-ok'>"
                f"{tn('conf.individuati', len(candidati_gia))}</span>",
                unsafe_allow_html=True)
        # L'etichetta dice cosa fara' ADESSO: la prima volta cerca, dalla
        # seconda in poi cerca ALTRO. Senza, premerlo di nuovo sembrava
        # rifare la stessa cosa (e prima la rifaceva davvero).
        gia_visti = tuple(st.session_state.get(f"visti_{path}") or ())
        premuto = avvio.button(
            t("conf.trova_altri") if gia_visti
            else t("conf.trova"),
            type="primary", use_container_width=True)
    if premuto:
        # La durata annunciata era "circa tre minuti": misurata, sta fra 28s
        # (360p) e 51s (720p) su episodi interi. Sovrastimare per prudenza fa
        # rinunciare a una cosa che costa meno di un minuto.
        # NIENTE `st.status`: ha la forma di un accordion apribile con dentro
        # il nulla — l'utente lo apre e resta deluso (successo). Una riga di
        # avviso con la rotella dice le stesse cose senza fingersi altro, e a
        # cose fatte sparisce col rerun.
        area = st.empty()

        def _passo(testo: str) -> None:
            area.markdown(f"<div class='au-avviso' style='margin-top:8px'>"
                          f"<span class='au-rotella'></span>{esc(testo)}"
                          f"</div>", unsafe_allow_html=True)

        _passo(t("conf.scansione"))
        try:
            nuovi = preview.find_candidates(
                plan, per_kind=2, on_step=_passo, escludi=gia_visti)
            if not nuovi:
                area.empty()
                st.warning(t("conf.nessun_altro"), icon="ℹ️")
                return
            # I nuovi si AGGIUNGONO: chi ha chiesto altri spezzoni vuole
            # scegliere fra piu' scene, non ricominciare da capo. Ma solo i
            # DAVVERO nuovi: se per qualunque via ne tornasse uno gia' in
            # pagina, aggiungerlo fabbricherebbe una card doppia.
            avuti = list(st.session_state.get(chiave) or [])
            nuovi = preview.solo_nuovi(avuti, nuovi)
            if not nuovi:
                area.empty()
                st.warning(t("conf.nessun_altro"), icon="ℹ️")
                return
            tutti = avuti + nuovi
            st.session_state[chiave] = tutti
            st.session_state[f"visti_{path}"] = gia_visti + tuple(
                c.start_frame for c in nuovi)
            st.session_state.setdefault(f"thumbs_{path}", {})
            # L'elenco completo va su disco: e' cio' che la pagina ritrova
            # dopo un ricaricamento, lotti successivi compresi.
            preview.scrivi_deposito(plan, tutti, 2, preview.DEFAULT_SECONDS,
                                    PATHS)
        except Exception as exc:                   # noqa: BLE001
            area.empty()
            st.error(t("conf.errore_analisi", errore=exc), icon="⚠️")
            return
        st.rerun()

    candidati = st.session_state.get(chiave)
    if candidati is None:
        st.markdown(
            f"<span class='au-hint'>{t('conf.spiega_spezzoni')}</span>",
            unsafe_allow_html=True)
        return
    if not candidati:
        st.warning(t("conf.nessuno_spezzone"))
        return

    thumbs = st.session_state.setdefault(f"thumbs_{path}", {})
    scelti = state(f"scelti_{path}", set())

    # Spezzoni animati e non fermi immagine: su un fotogramma solo non si vede
    # la differenza fra una scena ferma e una in movimento, che è la cosa su
    # cui si sta scegliendo. Costano poco (misurati 1.1s e 0.3 MB per otto) e
    # restano su disco, quindi si pagano una volta.
    mancanti = [c for c in candidati if c.slug not in thumbs]
    if mancanti:
        # Stessa riga-avviso della scansione, per lo stesso motivo: niente
        # finti accordion.
        area = st.empty()

        def _passo(testo: str) -> None:
            area.markdown(f"<div class='au-avviso' style='margin-top:8px'>"
                          f"<span class='au-rotella'></span>{esc(testo)}"
                          f"</div>", unsafe_allow_html=True)

        _passo(tn("conf.estraggo", len(mancanti)))
        for cand in mancanti:
            # La durata sta nel nome: cambiarla senza cambiare il nome
            # avrebbe continuato a servire i ritagli vecchi dalla cache.
            secondi = int(round(cand.frames / cand.fps))
            base = (PATHS.previews / "clips"
                    / f"{path.stem}_{cand.slug}_{secondi}s")
            clip = preview.animation(
                plan, cand, base.with_suffix(".mp4"), on_step=_passo)
            # Se l'estrazione fallisce resta il fermo immagine: peggio del
            # video, molto meglio di un buco senza spiegazione.
            thumbs[cand.slug] = clip or preview.thumbnail(
                plan, cand, base.with_suffix(".jpg"))
        # Il rerun fa sparire la riga a lavoro finito: a cose fatte non dice
        # più niente e resterebbe come residuo in mezzo alla pagina.
        st.rerun()

    regole_clip: list[str] = []
    for inizio in range(0, len(candidati), 4):
        for j, (col, cand) in enumerate(
                zip(st.columns(4), candidati[inizio:inizio + 4])):
            with col:
                # La chiave sta sul contenitore perché il CSS possa accendere
                # la card intera quando la casella dentro è spuntata
                # (`:has(input:checked)`): la selezione riguarda la card, non
                # il quadratino.
                with st.container(key=f"clip{inizio + j}"):
                    media = thumbs.get(cand.slug)
                    if media and media.suffix == ".mp4":
                        if not _video_ciclico(media):
                            st.video(str(media), loop=True, autoplay=True,
                                     muted=True)
                    elif media:
                        st.image(str(media), use_container_width=True)
                    # Il timecode viene messo dal CSS in fondo alla riga
                    # dell'etichetta (vedi `regole_clip`): dentro l'etichetta
                    # sarebbe una stringa sola e non si potrebbe spingere a
                    # destra, perché Streamlit non accetta markup lì.
                    # Il tipo resta l'identificativo italiano (nomi dei
                    # file, cassa): si traduce solo la scritta.
                    acceso = st.checkbox(
                        t(f"conf.tipo.{cand.kind.value}").capitalize(),
                        value=cand.slug in scelti, key=f"c_{path}_{cand.slug}")
                    regole_clip.append(
                        f'.st-key-clip{inizio + j} [data-testid="stWidgetLabel"]'
                        f'::after {{ content: "{cand.timecode_range}"; }}')
                    if acceso:
                        scelti.add(cand.slug)
                    else:
                        scelti.discard(cand.slug)
                    st.markdown(
                        f"<div class='au-c-desc'>"
                        f"{esc(t('conf.c_desc', motivo=cand.reason, prove=cand.kind.tests))}"
                        "</div>",
                        unsafe_allow_html=True)

    st.markdown("<style>" + "\n".join(regole_clip) + "</style>",
                unsafe_allow_html=True)
    st.session_state[f"scelti_{path}"] = scelti

    # Tre colonne, non due: modelli | quanto ci vuole | esito. Prima la
    # stima stava in una mega-colonna a destra con un buco fra lei e i
    # modelli, e l'avanzamento nasceva SOTTO la stima allungando la pagina
    # (ristrutturazione chiesta dall'utente). La terza colonna e' vuota a
    # riposo e ospita barra e nota durante l'elaborazione.
    with st.container(key="lancio"):
        sinistra, centro, destra = st.columns([0.8, 0.9, 1.5], gap="large")
    with sinistra:
        with st.container(key="campoModelli"):
            st.markdown(f"<div class='au-eyebrow au-sez'>{t('conf.modelli_da_provare')}</div>",
                        unsafe_allow_html=True)
            # Tre caselle e non un multiselect: le opzioni sono TRE, fisse e
            # note — la tendina coi tag era cerimonia (detto dall'utente).
            # La chiave include il file: cambiando episodio si riparte dal
            # modello consigliato per QUELLA risoluzione.
            # Le regole della Lavorazione valgono anche qui: un modello che
            # verrebbe rifiutato (es. "non arriva a 1080p") non si può
            # nemmeno provare — la clip uscirebbe a una scala diversa e si
            # sceglierebbe su un test poi inutilizzabile (disallineamento
            # notato dall'utente). La casella si spegne e il motivo sta
            # nel suggerimento.
            # `praticabili` e' gia' calcolata in cima alla pagina (una
            # verita' sola per schede, consiglio e caselle).
            for k in CATALOG:
                if praticabili.get(k) and st.session_state.get(
                        f"prova_{k}_{path}"):
                    # Una spunta rimasta accesa da prima non deve
                    # sopravvivere allo spegnimento della casella.
                    st.session_state[f"prova_{k}_{path}"] = False
            # Streamlit butta lo stato dei widget che un giro non disegna:
            # uscendo dalla pagina e tornando, le caselle rinascevano col
            # valore di partenza e un modello scelto in più spariva in
            # silenzio (difetto visto in prova: due modelli all'andata, uno
            # al ritorno, con la stima che cambiava senza dire perché).
            # Gli spezzoni si salvavano solo perché la pagina li ricopia in
            # `scelti_`: qui serve lo stesso specchio. La chiave dello
            # specchio è diversa da quella del widget, altrimenti scriverla
            # dopo il disegno solleverebbe.
            # Lo specchio vale SOLO dopo che l'utente ha davvero messo mano
            # alle caselle. Scritto anche al primo disegno, congelava il
            # valore proposto e da quel momento la pagina non seguiva più il
            # modello del file: sceglendolo dalla tendina della Lavorazione,
            # il Confronto continuava a provare quello di prima senza dirlo.
            toccato = st.session_state.get(f"tocco_modelli_{path}")
            memoria = st.session_state.get(f"modelli_{path}") if toccato else None
            voluti = memoria if memoria is not None else {plan.model_key}
            # Se NIENTE di ciò che si voleva è utilizzabile a questa altezza
            # — capita spegnendo un modello che esiste a una scala sola — la
            # pagina resterebbe senza una casella accesa, senza pulsante e
            # senza spiegazione. Si ricade sul consigliato, praticabile per
            # costruzione. Lo specchio VUOTO invece è una scelta vera ("li ho
            # tolti tutti") e si rispetta.
            if voluti and all(praticabili.get(k) for k in voluti):
                voluti = {plan.model_key}
            # Il suggerimento di una casella barrata non si limita al "non
            # si puo'": dice anche cosa aspettarsi dalle alternative — in
            # particolare se quella rimasta selezionabile e' comunque
            # sconsigliata per questo file (chiesto dall'utente).
            giudizi_ = ((plan.recommendation.giudizi or {})
                        if plan.recommendation else {})
            sconsigliate_vive = [CATALOG[a].short for a in CATALOG
                                 if not praticabili.get(a)
                                 and giudizi_.get(a) == "no"]
            aiuti: dict[str, str] = {}
            for k in CATALOG:
                if not praticabili.get(k):
                    continue
                aiuto = praticabili[k]
                if sconsigliate_vive:
                    aiuto += " " + t(
                        "conf.nota_sconsigliate",
                        modelli=t("conf.e").join(sconsigliate_vive))
                aiuti[k] = aiuto
            chiavi = [k for k in CATALOG
                      if st.checkbox(CATALOG[k].short,
                                     value=(k in voluti) and not praticabili[k],
                                     key=f"prova_{k}_{path}",
                                     disabled=bool(praticabili[k]),
                                     help=aiuti.get(k) or None,
                                     on_change=_tocca_modelli, args=(str(path),))
                      and not praticabili[k]]
            if toccato:
                st.session_state[f"modelli_{path}"] = set(chiavi)
        # Stessa storia per l'originale: spento e poi ritrovato acceso.
        riferimento = st.checkbox(
            t("conf.includi_originale"),
            value=st.session_state.get(f"originale_{path}", True),
            help=t("conf.includi_aiuto"))
        st.session_state[f"originale_{path}"] = riferimento

    prescelti = [c for c in candidati if c.slug in scelti]
    varianti = preview.variants_for(*chiavi, reference=riferimento)

    premi = False
    with centro:
        st.markdown(f"<div class='au-eyebrow au-sez-int'>{t('conf.quanto')}</div>",
                    unsafe_allow_html=True)
        # Niente nota sulla taratura qui: si sa gia' (la dice la sidebar), e
        # allungava la colonna di centro disallineando le tre del Confronto
        # (chiesto da Interstellar0verdrive il 2026-08-10).
        if not prescelti or not varianti:
            st.markdown(f"<span class='au-hint'>{t('conf.seleziona')}</span>",
                        unsafe_allow_html=True)
        else:
            # Scomposta e non un totale solo: il riferimento è l'unica voce
            # che si può togliere, e senza vederne il costo non si può
            # decidere se toglierla. "N varianti" contava il riferimento come
            # un modello scelto, e chi ne aveva spuntati tre ne leggeva
            # quattro chiedendosi quale fosse il quarto.
            modelli = [v for v in varianti if not v.is_reference]
            ns, nm = len(prescelti), len(modelli)
            solo_modelli = preview.estimate_seconds(plan, prescelti, modelli)
            totale = preview.estimate_seconds(plan, prescelti, varianti)
            righe = [f"<div class='au-stima'><span>{tn('conf.n_spezzoni', ns)}"
                     f" × {tn('conf.n_modelli', nm)}</span>"
                     f"<b>{hms(solo_modelli)}</b></div>"]
            if riferimento:
                righe.append(f"<div class='au-stima'><span>{t('conf.stima_originale')}"
                             f"</span><b>{hms(totale - solo_modelli)}"
                             "</b></div>")
            righe.append("<div class='au-stima au-stima-tot'><span>"
                         f"{tn('conf.stima_totale', ns * len(varianti))}</span>"
                         f"<b>{hms(totale)}</b></div>")
            st.markdown("".join(righe), unsafe_allow_html=True)
            premi = st.button(t("conf.elabora"), type="primary",
                              use_container_width=True)
    with destra:
        st.markdown(f"<div class='au-eyebrow au-sez-int'>{t('conf.avanzamento')}</div>",
                    unsafe_allow_html=True)
        # La zona esiste GIA' PRIMA del click (segnaposto + altezza dal
        # CSS): al click barra e nota compaiono qui, nella terza colonna,
        # senza spostare la pagina.
        zona = st.container(key="zonaEsito")
        with zona:
            st.markdown("<span class='au-zona-segnaposto'></span>",
                        unsafe_allow_html=True)
            # Il "pronto" resta finche' i risultati esistono: prima viveva
            # solo nel giro della generazione e il primo rerun lo mangiava
            # (sparizione vista dall'utente).
            # ...ma NON mentre una generazione nuova sta girando: «pronto»
            # sopra la barra di un lavoro in corso, con la freccia che punta
            # a quella barra invece che alle clip, e' fuorviante (segnalato
            # dall'utente il 12/08, al secondo giro di confronto).
            if st.session_state.get(f"risultati_{path}") and not premi:
                st.markdown(f"<div class='au-hint'>{t('conf.pronto')}</div>",
                            unsafe_allow_html=True)
        if premi:
            _genera(plan, prescelti, varianti, path, zona)

    _risultati(path)


def _genera(plan, candidati, varianti, path: Path, zona) -> None:
    with zona:
        barra = st.progress(0.0, t("conf.avvio"))
        # La verita', detta prima che faccia male: qualunque interazione
        # fa ripartire lo script di Streamlit e il giro muore (limite del
        # suo modello di esecuzione, non nostro). Insieme al limite si
        # dice pero' anche la rete di salvataggio: la ripresa riusa le
        # clip gia' fatte.
        nota_fragile = st.empty()
        nota_fragile.markdown(
            "<div class='au-hint'>"
            f"{t('conf.fragile', pulsante=t('conf.elabora'))}</div>",
            unsafe_allow_html=True)
    # La barra nasce nella zona riservata sotto la CTA, che con una lista
    # di spezzoni lunga sta sotto la piega: senza scroll "parte ma non si
    # vede niente" (visto dall'utente). Stessa ricetta dello scroll ai
    # risultati, solo all'inizio invece che alla fine. Il piccolo ritardo
    # lascia alla barra il tempo di esistere nel DOM.
    st.iframe(
        "<script>setTimeout(()=>{"
        "const z=window.parent.document.querySelector('.st-key-zonaEsito');"
        "if(z)z.scrollIntoView({behavior:'smooth',block:'center'});"
        "},200);</script>", height=1)
    # La percentuale è VERA: le varianti completate più la frazione di
    # fotogrammi della variante in corso (lo stesso contatore delle barre di
    # Lavorazione). Prima avanzava solo a variante finita, e con clip da uno
    # o due minuti l'una "sembra ferma da un bel po'" (detto dall'utente).
    totale, risultati = len(candidati) * len(varianti), []
    stato = {"fatte": 0, "testo": t("conf.avvio")}
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    contesto = get_script_run_ctx()

    def _ridisegna(frazione: float = 0.0) -> None:
        quota = min((stato["fatte"] + min(frazione, 1.0)) / totale, 1.0)
        barra.progress(quota, f"{stato['testo']} · {quota:.0%}")

    guasti: list[str] = []
    for cand in candidati:
        def passo(label: str, _c=cand):
            stato["testo"] = (f"{t(f'conf.tipo.{_c.kind.value}')} "
                              f"{_c.timecode} — {label}")
            _ridisegna()

        def frazione(fatti_f: int, attesi_f: int):
            # Arriva dal thread di sorveglianza di `upscale_dir`: senza il
            # contesto di Streamlit le chiamate a `st.progress` sono no-op
            # silenziosi ("missing ScriptRunContext" nel log, misurato) e la
            # barra restava a 0% per tutta la variante.
            from streamlit.runtime.scriptrunner import add_script_run_ctx
            add_script_run_ctx(threading.current_thread(), contesto)
            _ridisegna(fatti_f / attesi_f if attesi_f else 0.0)

        def variante_finita():
            stato["fatte"] += 1
            _ridisegna()

        # Uno spezzone che non si elabora non deve portarsi via la scheda
        # intera: si segnala e si va avanti con gli altri, che sono
        # indipendenti fra loro.
        # Dentro il `try` ci va anche `crop_sheet`: protetta la sola `render`,
        # un montaggio dei ritagli fallito portava giù lo stesso la scheda.
        try:
            res = preview.render(plan, cand, varianti, on_step=passo,
                                 on_progress=frazione, on_done=variante_finita)
            if res.files:
                preview.crop_sheet(res, plan)
                risultati.append(res)
        except Exception as exc:                       # noqa: BLE001
            guasti.append(f"{t(f'conf.tipo.{cand.kind.value}')} "
                          f"{cand.timecode}: {exc}")
            continue
    barra.empty()
    nota_fragile.empty()
    with zona:
        for g in guasti:
            st.error(g, icon="⚠️")
        if risultati and not st.session_state.get(f"risultati_{path}"):
            # Solo alla PRIMA generazione: rigenerando, la zona espone gia'
            # il "pronto" dalla sessione e questo sarebbe un doppione.
            st.markdown(f"<div class='au-hint'>{t('conf.pronto')}</div>",
                        unsafe_allow_html=True)
            # Lo scroll porta "Risultati" circa a meta' finestra (un filo
            # sopra): block center sull'ancora piu' una spintarella.
            st.iframe(
                "<script>const M=window.parent.document;"
                "M.querySelector('.au-ancora-risultati')?.scrollIntoView("
                "{behavior:'smooth', block:'center'});"
                "setTimeout(()=>{const s=M.querySelector("
                "'[data-testid=\"stMain\"]');"
                "if(s)s.scrollBy({top:90,behavior:'smooth'});},700);"
                "</script>", height=1)

    st.session_state[f"risultati_{path}"] = [
        {"cartella": str(r.folder), "file": {k: str(v) for k, v in r.files.items()},
         "foglio": str(r.crop_sheet) if r.crop_sheet else None,
         # Il range completo (inizio - fine), non solo l'inizio: stesso
         # formato delle card di scelta (chiesto dall'utente).
         # Tipo e range e non il titolo gia' scritto: il titolo si compone
         # al disegno, nella lingua di quel momento.
         "tipo": r.candidate.kind.value,
         "intervallo": r.candidate.timecode_range,
         # Quanto ci ha messo OGNI modello su questo spezzone e cosa
         # significherebbe sull'episodio intero. La proiezione tiene conto
         # della DEDUPLICA: prima si scriveva «stima senza deduplica, di
         # solito si finisce prima», che su un file al 33% sbagliava di
         # quattro ore e mezza — e la deduplica ormai o e' misurata sul file
         # o e' stimata sui file simili, quindi non c'e' motivo di ignorarla.
         "modelli": [
             {"chiave": k, "nome": CATALOG[k].short,
              "secondi": r.tempi[k],
              "intero": r.tempi[k] * plan.frames / max(r.candidate.frames, 1)
                        * (1 - _quota_dedup(plan)[0]),
              "metriche": r.metriche.get(k)}
             for k in preview.ordine_lettura(r.tempi)
             if k in CATALOG and r.tempi.get(k, 0) >= 5
         ],
         "dedup": _quota_dedup(plan)}
        for r in risultati
    ]


def _quota_dedup(plan) -> tuple[float, str]:
    """(quanta deduplica applicare alla proiezione, da dove viene).

    Tre casi, in ordine di forza: misurata su QUESTO file (la mappa esiste
    gia' su disco), attesa dai file simili gia' lavorati, oppure nessuna —
    che e' anche il caso della deduplica spenta, dove ignorarla e' giusto.

    La provenienza e' un codice e non la frase: il risultato resta in
    sessione, e la frase si scrive al disegno nella lingua di quel momento
    (vedi `_tabella_confronto`).
    """
    d = getattr(plan, "dedup", None)
    if d is None or not d.enabled:
        return 0.0, "spenta"
    if getattr(d, "misurata", False):
        return d.expected_ratio, "misurata"
    storico = getattr(plan, "dedup_storico", None)
    if storico is not None:
        return storico.attesa, "storico"
    if d.expected_ratio:
        return d.expected_ratio, "prevista"
    return 0.0, "ignota"


# Una funzione e non un dizionario fisso: i testi seguono la lingua attiva.
def _spiega_indicatori() -> dict[int, str]:
    return {0: t("conf.spiega_dettaglio"), 1: t("conf.spiega_rumore")}


def _tabella_confronto(modelli: list[dict], dedup,
                       riferimento: bool = True) -> None:
    """I numeri del confronto, in rilievo e in cima.

    Prima stavano in coda, in grigetto, formato nota a margine: «non e'
    affatto in rilievo» (utente, 12/08). Sono la prima domanda a cui un
    confronto risponde — quale modello, e a che prezzo — quindi aprono.

    La colonna del CONFRONTO FRA MODELLI compare solo da due modelli in su:
    con un modello solo contro l'ingrandito il tempo e' ovvio e la colonna
    sarebbe rumore (detto dall'utente, e ha ragione).
    """
    # Solo il NOME della deduplica: la quota e' gia' applicata a
    # `m["intero"]` da chi ha costruito le righe.
    quota, codice = (dedup or (0.0, ""))
    pct = f"{quota:.0%}"
    come = {"spenta": t("conf.dedup.spenta"),
            "misurata": t("conf.dedup.misurata", pct=pct),
            "storico": t("conf.dedup.storico", pct=pct),
            "prevista": t("conf.dedup.prevista", pct=pct),
            "ignota": t("conf.dedup.ignota")}.get(codice, "")
    piu_veloce = min(m["secondi"] for m in modelli)
    righe = []
    for m in modelli:
        scarto = ""
        if len(modelli) > 1:
            d = m["secondi"] / piu_veloce - 1
            scarto = (t("conf.piu_veloce") if d < 0.005
                      else t("conf.piu_tempo", pct=f"{d:.0%}"))
        righe.append(
            f"<tr><td class='au-cnf-nome'>{esc(m['nome'])}</td>"
            f"<td>{stima_hm(m['secondi'])}</td>"
            f"<td>≈ {stima_hm(m['intero'])}</td>"
            f"<td class='au-cnf-scarto'>{esc(scarto)}</td></tr>")
    st.markdown(
        "<table class='au-cnf'>"
        f"<thead><tr><th>{t('conf.th_modello')}</th><th>{t('conf.th_spezzone')}</th>"
        f"<th>{t('conf.th_episodio')}</th><th></th></tr></thead>"
        f"<tbody>{''.join(righe)}</tbody></table>"
        f"<div class='au-hint' style='margin:6px 0 2px'>"
        f"{esc(t('conf.proiezione', come=come))}</div>",
        unsafe_allow_html=True)

    # Una colonna si disegna solo se qualcuno ha un numero da metterci: una
    # fila di trattini non e' informazione, e' rumore. Il rumore nelle aree
    # piatte non e' misurabile su ogni fotogramma (vedi RESIDUO_MINIMO).
    def _c(m, i):
        q = m.get("metriche")
        return q[i] if q and len(q) > i else None

    colonne = [(i, testo) for i, testo in
               ((0, t("conf.col_dettaglio")), (1, t("conf.col_rumore")))
               if any(_c(m, i) is not None for m in modelli)]
    if not colonne:
        # Niente indicatori: si dice PERCHE'. Sparire in silenzio manda a
        # cercare un difetto dove non c'e' — ed e' esattamente il modo in cui
        # il difetto vero era rimasto invisibile fino all'audit del 12/08.
        st.markdown(
            "<div class='au-hint' style='margin:10px 0 2px'>" +
            (t("conf.ind_no_rif") if not riferimento
             else t("conf.ind_no_aree")) +
            "</div>", unsafe_allow_html=True)
        return
    voci = []
    for m in modelli:
        # OGNI modello ha la sua riga, anche chi non e' stato misurato: chi
        # sparisce lascia una tabella piu' corta dell'altra senza una parola,
        # e chi guarda si chiede quale delle due sbagli (visto in audit).
        celle = "".join(
            f"<td>{v * 100:.0f}%</td>" if (v := _c(m, i)) is not None
            else "<td>—</td>" for i, _t in colonne)
        voci.append(
            f"<tr><td class='au-cnf-nome'>{esc(m['nome'])}</td>{celle}</tr>")
    # `testo` e non `t`: `t` e' la funzione dei testi.
    intestazioni = "".join(f"<th>{testo}</th>" for _i, testo in colonne)
    spiega = _spiega_indicatori()
    st.markdown(
        "<div class='au-eyebrow' style='margin:14px 0 6px'>"
        f"{t('conf.indicatori')}</div>"
        "<table class='au-cnf'>"
        f"<thead><tr><th>{t('conf.th_modello')}</th>{intestazioni}</tr></thead>"
        f"<tbody>{''.join(voci)}</tbody></table>"
        # Le righe che spiegano come si leggono: senza, due percentuali non
        # dicono niente a nessuno (chiesto dall'utente il 12/08). Si spiega
        # solo cio' che si sta mostrando.
        "<div class='au-hint' style='margin:8px 0 2px'>"
        + "<br>".join(spiega[i] for i, _t in colonne) +
        "</div>"
        "<div class='au-hint' style='margin:6px 0 2px;opacity:.85'>"
        f"{t('conf.avvertenza')}"
        "</div>",
        unsafe_allow_html=True)


def _risultati(path: Path) -> None:
    risultati = st.session_state.get(f"risultati_{path}")
    if not risultati:
        return
    st.divider()
    # L'ancora dello scroll automatico post-elaborazione.
    st.markdown("<div class='au-ancora-risultati'></div>",
                unsafe_allow_html=True)
    # Il contenitore con chiave serve al CSS (titoli accordion + stile):
    # tutto il corpo dei risultati vive qui dentro.
    blocco_risultati = st.container(key="risultati")
    # Titolo di sezione VERO, come "Confronto dei modelli": "#####"
    # era il piu' piccolo dei markdown e l'arrivo dei risultati — cioe'
    # il momento clou della scheda — sembrava una nota a margine
    # ("sfigatissimo", parola dell'utente).
    # Coppia __enter__/__exit__ esplicita: il corpo e' lungo e
    # re-indentarlo tutto sotto un `with` renderebbe illeggibile
    # ogni diff futuro. L'uscita sta in fondo alla funzione.
    blocco_risultati.__enter__()
    st.markdown(
        f"<div class='au-sezione'>{t('conf.risultati')}</div>"
        f"<div class='au-hint' style='margin-bottom:14px'>"
        f"{t('conf.risultati_nota', cartella=PATHS.previews.name)}</div>",
        unsafe_allow_html=True)

    for res in risultati:
        # `titolo` e' il formato di prima: risultati rimasti in sessione da
        # un giro precedente all'aggiornamento.
        titolo = (t(f"conf.tipo.{res['tipo']}") + f" · {res['intervallo']}"
                  if "tipo" in res else res.get("titolo", ""))
        with st.expander(titolo, expanded=True):
            # GERARCHIA: prima l'AZIONE (aprire il confronto vero), poi la
            # prova visiva (il foglio 1:1), in coda i numeri e il percorso.
            # Prima le proiezioni stavano in cima e i pulsanti, appiccicati
            # al testo, sparivano ("non si nota per niente", utente).
            # I tempi e la proiezione APRONO il report: sono la prima
            # domanda a cui il risultato risponde (spostati su richiesta).
            modelli = res.get("modelli") or []
            if modelli:
                _tabella_confronto(
                    modelli, res.get("dedup"),
                    riferimento="originale" in (res.get("file") or {}))
            nomi = preview.ordine_lettura(res["file"])
            coppie = [(a, b) for i, a in enumerate(nomi) for b in nomi[i + 1:]]
            if coppie:
                st.markdown("<div class='au-eyebrow' style='margin:16px 0 "
                            f"8px'>{t('conf.video_compare')}</div>",
                            unsafe_allow_html=True)
                for col, (x, y) in zip(st.columns(len(coppie)), coppie):
                    lx = t("conf.originale") if x == "originale" else CATALOG[x].short
                    ly = t("conf.originale") if y == "originale" else CATALOG[y].short
                    if col.button(t("conf.apri_coppia", a=lx, b=ly),
                                  key=f"cmp_{res['cartella']}_{x}_{y}",
                                  type="primary"):
                        ok, msg = preview.open_comparison(
                            Path(res["file"][x]), Path(res["file"][y]))
                        (st.success if ok else st.error)(msg)
            if res["foglio"]:
                st.markdown("<div class='au-eyebrow' style='margin:18px 0 "
                            f"8px'>{t('conf.frame_statico')}</div>",
                            unsafe_allow_html=True)
                # Alla larghezza NATURALE del PNG. Con `use_container_width` il
                # browser lo riscalava da 1.1x a 2.2x con interpolazione
                # bilineare: il foglio dei ritagli è 1:1 nel file, e mostrarlo
                # riscalato annulla l'unica ragione per cui esiste — a scala
                # diversa da 1:1 gli artefatti da giudicare spariscono.
                try:
                    from PIL import Image
                    with Image.open(res["foglio"]) as im:
                        larghezza = im.width
                    st.image(res["foglio"], width=larghezza)
                    st.markdown(f"<span class='au-hint'>{t('conf.ritagli_nota')}"
                                "</span>", unsafe_allow_html=True)
                except Exception:                          # noqa: BLE001
                    st.image(res["foglio"])
            # L'elenco ESPLICITO dei file prodotti, uno per riga, e la via
            # breve alla cartella: prima c'era solo il percorso in un
            # caption muto (chiesto dall'utente).
            righe_file = ["<div class='au-eyebrow' style='margin:14px 0 "
                          f"6px'>{t('conf.percorso')}</div>"]
            for k_f, v_f in res["file"].items():
                nome_f = (t("conf.originale_ingrandito") if k_f == "originale"
                          else CATALOG[k_f].label)
                # Un font solo (il mono di au-meta): etichetta piena e in
                # grassetto, percorso normale e grigio.
                righe_file.append(
                    f"<div class='au-meta' style='margin-top:2px'>"
                    f"<b class='au-file-eti'>{esc(t('conf.file_eti', nome=nome_f))}</b> "
                    f"{esc(str(v_f))}</div>")
            st.markdown("".join(righe_file), unsafe_allow_html=True)
            if st.button(t("conf.apri_finder"),
                         key=f"finder_conf_{res['cartella']}",
                         icon=":material/folder_open:"):
                subprocess.run(["open", str(res["cartella"])], check=False)
    blocco_risultati.__exit__(None, None, None)


# ===========================================================================
#  3 · Lavorazione
# ===========================================================================

def page_lavorazione(cfg: dict) -> None:
    files = load_library()
    if not files:
        st.info(t("lav.vuoto"))
        return
    # Il corpo è un fragment: con un lavoro vivo si riaggiorna da solo ogni
    # 5 secondi, così le barre DENTRO le righe avanzano; da fermo niente
    # auto-refresh, che chiuderebbe le tendine mentre le usi. Un fragment
    # ridisegna solo se stesso e per intero: niente nodi orfani adottati, il
    # pasticcio già misurato con `sleep` + rerun di pagina.
    # Armato = c'e' QUALCOSA di vivo nella maratona: un lavoro col lucchetto,
    # una pausa dichiarata, o la catena stessa (che copre anche i varchi di
    # qualche secondo fra un file e l'altro). Le tre condizioni DEVONO essere
    # le stesse del riarmo in fondo a `_corpo_lavorazione`: quando la pausa
    # era solo qui, il confronto la' sotto risultava sempre in disaccordo e
    # forzava un rerun completo ogni 5 secondi per tutta la pausa — la
    # tempesta di rerun che fa comparire liste duplicate transitorie.
    armato = (any(l.vivo for l in monitor.lavori())
              or monitor.pausa() is not None
              or monitor.catena() is not None
              # Il cuscinetto post-Avvia: la fase di analisi di un lotto
              # grosso è muta (niente lucchetti né marcatori) ma la pagina
              # deve restare in ascolto per accorgersi della catena che nasce.
              or time.time() - st.session_state.get("attesa_avvio", 0) < 180
              # Anche durante l'analisi: le righe non ancora analizzate si
              # popolano da sole man mano che il referto arriva.
              or analizzatore().al_lavoro)
    # IL RIQUADRO ESTERNO NON SI RIESEGUE PIU' DA SOLO.
    # Prima era `run_every="5s"` qui, e voleva dire ridisegnare ogni cinque
    # secondi 1.150 righe di codice, diciannove righe d'elenco, tutte le
    # icone e tutti i pulsanti — per aggiornare una barra di avanzamento e
    # una fascia. Il danno era misurato: un pulsante della riga rubava il
    # puntatore all'icona d'aiuto per meno di un decimo di secondo a ogni
    # giro (8 campioni su 286, a passi di cinque secondi esatti), e i
    # contenitori venivano marcati "vecchi" facendo sbiadire le scritte (33
    # raffiche in 28 minuti). Da fuori: un'interfaccia che lampeggia.
    # Ora si aggiornano da soli i due soli pezzi che cambiano davvero — la
    # barra della riga al lavoro e la fascia in basso — e le righe restano
    # ferme. Quando cambia qualcosa di strutturale (un file che finisce, uno
    # che parte) il riquadro vivo se ne accorge dalla firma dello stato e
    # chiede UN giro completo: vedi `_firma_stato` e `_avanzamento_vivo`.
    corpo = st.fragment(_corpo_lavorazione)
    corpo(cfg, files, armato)


def _turno_previsto(piano, lav) -> float | None:
    """Il turno di codifica secondo la taratura, per il primo blocco.

    Il calcolo sta in `monitor` perché sia eseguibile da un test: qui resta
    solo il prelievo dei campi dal piano."""
    if piano is None:
        return None
    return monitor.turno_da_taratura(
        lav.blocco_totale, piano.target_width, piano.target_height,
        piano.fps_codifica)


def _resto_misurato(lav, campioni: dict, stati: dict | None = None,
                    turno_stimato: float | None = None, *,
                    ritmo: float | None = None) -> float | None:
    """Quanto manca a questo file secondo il RITMO MISURATO, o niente.

    Un solo posto per un conto che serve in due: la riga del file e il
    residuo della coda in fondo alla pagina. Tenerne due copie significava
    che la riga poteva dire una cosa e la fascia un'altra sullo stesso file.

    Il conto vero sta in `monitor.tempo_che_resta` perche' sia eseguibile da
    un test: sommare i turni di codifica invece di sottrarli, o dimenticarli,
    non deve poter passare inosservato. Si usa la durata MISURATA dei turni
    di questa lavorazione; solo per il primo blocco, quando non se n'e'
    ancora visto uno, si ripiega sulla taratura.

    `None` quando non c'e' niente di misurato da cui partire: meglio la
    stima di partenza che un numero inventato.
    """
    if not lav.totale:
        return None
    # `ritmo` si accetta gia' calcolato: la riga lo mostra a schermo e lo
    # calcolava due volte, una per scriverlo e una qui dentro.
    if ritmo is None:
        ritmo = monitor.andatura(campioni.get(lav.cartella.name, []))
    if not ritmo:
        return None
    turno = monitor.turno_misurato(stati or {}, lav.cartella.name)
    return monitor.tempo_che_resta(
        lav.fatti, lav.totale, ritmo,
        blocchi_totali=lav.blocchi_totali, blocco_n=lav.blocco_n,
        blocco_totale=lav.blocco_totale,
        turno=turno if turno is not None else turno_stimato)


def _riempimento(lav) -> float:
    """Quanto riempire la barra della riga, 0..1.

    Nelle prime due fasi e' la frazione di fotogrammi elaborati. Nella TERZA
    no: li' i fotogrammi sono tutti fatti per definizione, quindi la barra
    sarebbe piena al 100% mentre il testo accanto dice «26%» — due misure
    diverse una sopra l'altra, che si contraddicono a colpo d'occhio
    (segnalato dall'utente il 12/08 guardando una fase 3 in corso).

    In fase 3 la barra segue quindi il lavoro che RESTA davvero, che il
    monitor gia' misura contando i pacchetti scritti: la prima meta' e' la
    codifica dell'ultimo blocco, la seconda il montaggio del file finale.
    Cosi' la barra cresce una volta sola da 0 a 1 e non torna indietro fra i
    due sottopassi.
    """
    # Le prime due fasi si fermano al 90%: alla fine dell'upscale il file NON
    # e' pronto, restano la codifica dell'ultimo blocco e il montaggio. Il
    # restante 10% e' loro. Cosi' la barra non torna mai indietro — la prima
    # versione di questa funzione faceva crollare la barra dal 100% al 13%
    # entrando in fase 3, che e' peggio del difetto che doveva curare.
    if lav.fase != "codifica finale":
        return lav.frazione * 0.9
    quota = max(0.0, min(1.0, lav.codifica_frazione))
    dentro = 0.5 + quota / 2 if lav.sottopasso == "montaggio" else quota / 2
    return 0.9 + dentro * 0.1


def _avanzamento_testo(lav, campioni: dict, stati: dict | None = None,
                       turno_stimato: float | None = None) -> str:
    """Tutto etichettato: fps (fotogrammi elaborati al secondo), quanto resta,
    quanto è trascorso. Un numero senza etichetta accanto a un altro tempo
    non si capisce — detto dall'utente guardando la prima versione."""
    # Tre macro-fasi vere, numerate. NON quattro barre separate: upscale e
    # codifica si alternano per blocco, e il montaggio non ha una metrica per
    # fotogramma — una barra a fase è informazione, quattro sarebbero teatro.
    if lav.fase == "codifica finale":
        # Due sottopassi, ciascuno con la sua percentuale MISURATA (pacchetti
        # contati, come per i blocchi): prima l'ultimo blocco passa in x265,
        # poi il montaggio scrive il file finale. Chiesta dall'utente.
        if lav.sottopasso == "montaggio":
            perc = (f" {lav.codifica_frazione:.0%}"
                    if lav.codifica_frazione > 0 else "")
            passo = t("lav.av_scrittura", perc=perc)
        else:
            perc = (f" {lav.codifica_frazione:.0%}"
                    if lav.codifica_frazione > 0 else "")
            passo = t("lav.av_ultimo_blocco", perc=perc)
        return t("lav.av_fase3", passo=passo, totale=lav.totale,
                 trascorso=monitor.trascorso(lav))
    if lav.fase == "codifica blocco":
        # Il cambio turno GPU→CPU: dirlo esplicitamente, e NIENTE fps o ETA
        # — in questa finestra sarebbero numeri di un regime che non c'e'.
        # La percentuale invece è MISURATA (pacchetti del segmento in
        # scrittura) e compare appena il file inizia a esistere.
        perc = (f" {lav.codifica_frazione:.0%}"
                if lav.codifica_frazione > 0 else "")
        quale = (f" ({t('lav.av_blocco', n=lav.blocco_n, totale=lav.blocchi_totali)})"
                 if lav.blocchi_totali else "")
        # NIENTE tempo che resta qui, ed e' una decisione misurata. La
        # percentuale non cresce liscia: sta ferma 30-35 secondi e poi salta
        # di ~11 punti in un colpo, perche' x265 scarica i pacchetti a
        # raffiche. Estrapolando da li' il numero mostrato oscillava fra -27
        # e +91 secondi su un turno di sei minuti: cresceva mentre lo si
        # guardava e ricascava giu' a ogni scalino. Un conto alla rovescia
        # che sale e scende non e' un'informazione, e' un tic. La
        # percentuale, che e' MISURATA, resta.
        return t("lav.av_fase2_codifica", perc=perc, quale=quale,
                 fatti=lav.fatti, totale=lav.totale,
                 trascorso=monitor.trascorso(lav))
    numero = "1/3" if lav.fase == "estrazione" else "2/3"
    nome_fase = "estrazione" if lav.fase == "estrazione" else "upscale"
    # `nome_fase` si confronta qui sotto: a schermo va la sua traduzione.
    scritta_fase = (t("lav.av_estrazione") if nome_fase == "estrazione"
                    else t("lav.av_upscale"))
    if not lav.totale:
        # Estrazione appena nata, prima di state.json: il totale non è
        # ancora noto, ma dire QUANTI fotogrammi stanno uscendo è già la
        # differenza fra "sta lavorando" e "sembra tutto fermo".
        testo = t("lav.av_estratti", numero=numero, fase=scritta_fase,
                  fatti=lav.fatti)
        if monitor.trascorso(lav):
            testo += f" · {t('lav.av_trascorsi', trascorso=monitor.trascorso(lav))}"
        return testo
    # Il punto nel blocco accanto al totale: dice quanto manca al prossimo
    # punto di salvataggio — cioè quando un Ferma non butta via niente
    # (chiesto dall'utente proprio per scegliere il momento).
    nel_blocco = (" (" + t("lav.av_nel_blocco", fatti=lav.blocco_fatti,
                           totale=lav.blocco_totale, n=lav.blocco_n,
                           blocchi=lav.blocchi_totali) + ")"
                  if lav.blocchi_totali and nome_fase == "upscale" else "")
    testo = t("lav.av_fotogrammi", numero=numero, fase=scritta_fase,
              fatti=lav.fatti, totale=lav.totale, nel_blocco=nel_blocco)
    ritmo = monitor.andatura(campioni.get(lav.cartella.name, []))
    resta = _resto_misurato(lav, campioni, stati, turno_stimato, ritmo=ritmo)
    if ritmo and resta is not None:
        testo += f" · ~{ritmo:.1f} fps · {t('lav.av_restano', resta=hms(resta))}"
    if monitor.trascorso(lav):
        testo += f" · {t('lav.av_trascorsi', trascorso=monitor.trascorso(lav))}"
    return testo


def _scheda_monitor(lav, campioni: dict, stati: dict | None = None) -> str:
    if lav.vivo:
        stato = f"<span class='au-tag au-busy'>{t('lav.mon_in_corso')}</span>"
        # Anche qui i turni misurati vanno passati: senza, la scheda dei
        # lavori fuori da INPUT mostrava ancora la stima che ignora i turni,
        # cioe' proprio il difetto che questa modifica esiste per chiudere.
        # Il piano non c'e' (sono orfani) quindi niente ripiego da taratura:
        # o si e' misurato un turno, o non si somma niente.
        extra = f"<span class='au-meta'>{_avanzamento_testo(lav, campioni, stati)}</span>"
    else:
        stato = f"<span class='au-tag au-warn'>{t('lav.mon_interrotto')}</span>"
        extra = f"<span class='au-meta'>{t('lav.mon_riprendibile')}</span>"
    riga_log = lav.ultima_riga()
    return (
        f"<div class='au-mon{' au-mon-viva' if lav.vivo else ''}'>"
        f"<div class='au-mon-testa'>"
        f"<span class='au-mon-nome'>{esc(lav.nome)}</span>{stato}"
        f"<span class='au-tag au-dim'>{esc(lav.modello)}</span>"
        f"<span class='au-mon-dx'>{extra}</span></div>"
        f"<div class='au-mon-barra'><span style='width:"
        f"{lav.frazione * 100:.1f}%'></span></div>"
        + (f"<div class='au-mon-log'>{esc(riga_log[-160:])}</div>"
           if lav.vivo and riga_log else "")
        + "</div>")


def _firma_stato() -> tuple:
    """Cio' che, cambiando, obbliga a ridisegnare le RIGHE.

    Non i numeri che scorrono — fotogrammi, ritmo, percentuale — ma la
    struttura: quali lavorazioni esistono, quali sono vive, quante pagelle
    sono state scritte, se c'e' una pausa o una catena. Sono esattamente gli
    eventi che cambiano una chip, un pulsante o l'ordine delle righe.
    """
    lavori = monitor.lavori()
    return (tuple(sorted((l.cartella.name, bool(l.vivo)) for l in lavori)),
            len(monitor.esiti() or {}),
            monitor.pausa() is not None,
            bool(monitor.catena()))


def _controlla_firma() -> None:
    """Se e' cambiato qualcosa di strutturale, chiede UN giro completo.

    Va chiamata da OGNI riquadro che si aggiorna da solo, non da uno solo.
    Il primo tentativo la metteva nella sola barra di avanzamento, e c'era un
    buco largo cinque minuti: durante la pausa fra un file e l'altro non
    esiste nessun file al lavoro, quindi quella barra non esiste, quindi
    nessuno sorvegliava la firma. Il file successivo partiva e l'elenco
    restava fermo a quello di prima (visto dall'utente al primo cambio di
    file, 11/08).
    """
    prec = st.session_state.get("firma_lav")
    ora = _firma_stato()
    st.session_state["firma_lav"] = ora
    if prec is not None and ora != prec:
        st.rerun(scope="app")


def _avanzamento_vivo(cartella: str, turno: float | None) -> None:
    """La barra di UNA riga al lavoro, che si aggiorna da sola.

    E' il cuore della cura al lampeggio. Prima si rieseguiva l'intero corpo
    della Lavorazione ogni cinque secondi — 1.150 righe, diciannove righe di
    elenco, tutte le icone e tutti i pulsanti — per aggiornare questa barra e
    la fascia in basso. Il prezzo era misurabile e l'utente lo vedeva: ogni
    cinque secondi un pulsante della riga rubava il puntatore all'icona
    d'aiuto per meno di un decimo di secondo (8 campioni su 286, a passi di
    cinque secondi esatti), il fumetto si chiudeva e riappariva, e i
    contenitori venivano marcati "vecchi" facendo sbiadire le scritte (33
    raffiche in 28 minuti, fino a opacita' 0,81).

    Qui dentro si ridisegna SOLO questa barra. Il lavoro va riletto da capo a
    ogni giro — il riquadro si riesegue da solo, quindi non puo' fidarsi di
    un oggetto catturato prima — mentre `turno` e' una costante del file e
    puo' arrivare dalla chiusura.
    """
    _controlla_firma()

    lav = next((l for l in monitor.lavori()
                if l.cartella.name == cartella), None)
    if lav is None or not lav.vivo:
        return
    campioni = st.session_state.setdefault("mon_campioni", {})
    stati = st.session_state.setdefault("mon_stati", {})
    if monitor.sospeso(lav) is not None:
        # In pausa NON si campiona. I fotogrammi non avanzano perche' nessuno
        # sta lavorando, e infilare quei punti nella finestra farebbe crollare
        # il ritmo verso lo zero e sparare il «restano» all'infinito — una
        # bugia costruita su misure vere. La finestra si azzera alla ripresa.
        st.markdown(
            f"<div class='au-riga-avanz'>"
            f"<div class='au-riga-barra au-riga-ferma'>"
            f"<span style='width:{lav.frazione * 100:.1f}%'></span></div>"
            f"<span class='au-meta'>"
            + t("lav.av_in_pausa", perc=f"{lav.frazione:.0%}",
                fatti=lav.fatti, totale=lav.totale)
            + "</span>"
            f"</div>", unsafe_allow_html=True)
        return
    monitor.aggiorna_campioni(
        campioni, stati, [(lav.cartella.name, lav.fase, lav.fatti)],
        time.time())
    dett = _avanzamento_testo(lav, campioni, stati, turno)
    st.markdown(
        f"<div class='au-riga-avanz'>"
        f"<div class='au-riga-barra'>"
        f"<span style='width:{_riempimento(lav) * 100:.1f}%'></span></div>"
        f"<span class='au-meta'>{esc(dett)}</span></div>",
        unsafe_allow_html=True)


def _corpo_lavorazione(cfg: dict, files: list[dict], armato: bool) -> None:
    lavori_tutti = monitor.lavori()
    # I campioni per il ritmo, per cartella: ogni giro del fragment aggiunge
    # un punto; finestra di ~2 minuti per smorzare i singhiozzi della GPU.
    # Quando azzerare la finestra e quando tacere lo decide `monitor`, dove
    # sta anche `andatura` che la legge: le due cose sono la stessa regola
    # vista da due parti, e separarle aveva già prodotto un ritmo sbagliato
    # per il primo minuto e mezzo di ogni file.
    campioni = st.session_state.setdefault("mon_campioni", {})
    stati = st.session_state.setdefault("mon_stati", {})
    monitor.aggiorna_campioni(
        campioni, stati,
        [(l.cartella.name, l.fase, l.fatti) for l in lavori_tutti if l.vivo],
        time.time())
    # Durante l'estrazione appena nata (senza state.json) il lavoro non
    # conosce ancora il suo sorgente per esteso: la chiave ricade sul nome
    # della cartella, che è lo stem del sorgente senza estensione. Per
    # questo la ricerca sotto prova prima la chiave esatta e poi il
    # prefisso: "nome.mkv" normalizzato INIZIA con lo stem normalizzato.
    per_file = {monitor.chiave_nome(l.sorgente or l.nome): l
                for l in lavori_tutti if l.sorgente or l.nome}

    def _lavoro_di(nome_file: str):
        k = monitor.chiave_nome(nome_file)
        if k in per_file:
            return per_file[k]
        for chiave, lavoro in per_file.items():
            if chiave and k.startswith(chiave):
                return lavoro
        return None

    nomi_presenti = {monitor.chiave_nome(f["name"]) for f in files}
    # I lavori il cui sorgente NON sta in INPUT (una prova, un file spostato)
    # non hanno una riga in cui vivere: restano in una scheda propria.
    orfani = [l for l in lavori_tutti
              if not any(n.startswith(monitor.chiave_nome(l.sorgente or l.nome))
                         for n in nomi_presenti)]
    # Una lavorazione alla volta, finché non esiste una coda vera: un secondo
    # avvio non romperebbe nulla (le prenotazioni proteggono il disco) ma
    # dividerebbe la GPU, raddoppiando i tempi di entrambi e rendendo false le
    # ETA. Le CASELLE restano attive: preparare la prossima selezione mentre
    # si lavora è legittimo; è partire che aspetta.
    # Occupata anche durante la PAUSA fra due file e nei varchi della catena:
    # il lucchetto in quei momenti non esiste, ma la maratona è viva e
    # ripartirà — un Avvia permesso adesso vorrebbe dire due lavorazioni
    # insieme al risveglio.
    pausa_ora = monitor.pausa()
    catena_ora = monitor.catena()
    gpu_occupata = (any(l.vivo for l in lavori_tutti)
                    or pausa_ora is not None or catena_ora is not None)
    # Una taratura in volo blocca Avvia e Riprendi ma NON entra in
    # `gpu_occupata`: quella descrive una catena di lavorazione (righe in
    # coda, Ferma tutto, caselle spente), e la taratura non ne ha nessuna.
    tarando = taratura.in_corso()
    # I file che aspettano il loro turno nella catena in corso: la riga
    # mostra "in coda". Copre il comando corrente; in un lancio spezzato su
    # più modelli, i gruppi successivi compariranno quando tocca a loro.
    in_coda_ora = (set(catena_ora.get("in_coda") or [])
                   if catena_ora else set())
    # Il file NOMINATO dal marcatore aspetta sempre il suo turno finché non
    # prende il lucchetto: durante la pausa, ma anche nei secondi fra la
    # fine della pausa e l'avvio vero, e fra la fine di un file e il
    # marcatore del successivo. Senza, in quelle finestre la riga ricadeva
    # sul giudizio "consigliato" come se non c'entrasse niente (visto
    # dall'utente il 2026-08-10). Non serve escludere il file in corso: il
    # ramo "in corso" viene prima e vince comunque.
    if catena_ora:
        in_coda_ora.add(str(catena_ora.get("file") or ""))
    # Le pagelle dei file già conclusi (durata reale, avvisi): scritte dalla
    # CLI, sopravvivono all'autopulizia della cartella di lavoro.
    esiti_noti = monitor.esiti()
    # Chi fa parte della catena in corso: il "programma" nel marcatore. Una
    # catena avviata con la CLI vecchia non ce l'ha: si ricostruisce dai
    # segnali disponibili (in coda, corrente, lavorazione presente, fatto).
    programma_catena = (set(catena_ora.get("programma") or [])
                        if catena_ora else set())

    def _in_catena(nome: str, fatta: bool, con_lavoro: bool) -> bool:
        if not gpu_occupata:
            return False
        if programma_catena:
            return nome in programma_catena
        return (nome in in_coda_ora or fatta or con_lavoro
                or nome == str((catena_ora or {}).get("file") or ""))
    if orfani:
        st.markdown(f"<div class='au-eyebrow au-sez-int'>{t('lavb.fuori_input')}"
                    "</div>", unsafe_allow_html=True)
        st.markdown("".join(_scheda_monitor(l, campioni, stati) for l in orfani),
                    unsafe_allow_html=True)

    # Titolo e istruzioni seguono lo stato: dire "spunta e avvia" mentre le
    # caselle sono congelate era un invito a fare l'impossibile (detto
    # dall'utente durante la prima maratona).
    if gpu_occupata:
        st.markdown(
            f"<div class='au-sezione'>{t('lavb.titolo_in_corso')}</div>"
            "<div class='au-hint' style='margin-bottom:20px'>"
            f"{t('lavb.hint_in_corso')}</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='au-sezione'>{t('lavb.titolo')}</div>"
            "<div class='au-hint' style='margin-bottom:20px'>"
            f"{t('lavb.hint')}</div>",
            unsafe_allow_html=True)

    coda = state("coda", set())
    modelli = state("modelli", {})
    # `modelli` porta il modello EFFETTIVO di ogni riga (lo legge anche
    # `model_for`, cioè il piano). `scelte` dice quali di quei modelli li ha
    # voluti l'utente: senza questa distinzione una riga, dopo il primo
    # ridisegno, risultava sempre "scelta a mano" e la verità (pagella,
    # ricetta) non veniva più consultata.
    scelte = state("scelte_modello", set())
    # I file che risultano lavorati dalla pagella ma la cui uscita non è più
    # in OUTPUT non si rifanno d'ufficio: si annunciano nella barra e si
    # rifanno solo se lo si chiede qui. Rifare per sbaglio un episodio già
    # caricato altrove costa ore, e il file rimasto per distrazione in
    # INPUT è il caso normale, non l'eccezione.
    rifai_comunque = state("rifai_comunque", set())
    # Un file rimosso da INPUT mentre l'app è aperta restava in coda per
    # sempre: `discard` gira solo sui file ancora elencati. La barra diceva
    # "6 file selezionati" mostrandone cinque, ed è il numero su cui si decide
    # se premere Avvia.
    presenti = {f["path"] for f in files}

    def _sparito(chiave: str) -> bool:
        """Il file non c'è più DAVVERO, non "non è nell'elenco".

        La distinzione non è pedante: l'elenco viene da una scansione con
        otto secondi di cache che salta in silenzio ogni sorgente che
        ffprobe non riesce a leggere in quell'istante (`library.scan`). Un
        singhiozzo del disco esterno bastava a far sparire la selezione — e
        l'Avvia saltava quel file senza dire niente, che è esattamente il
        difetto descritto qui sopra, al contrario. Nel dubbio si TIENE:
        perdere una scelta dell'utente è il danno caro, tenerne una di
        troppo si vede subito nella riga.
        """
        if chiave in presenti:
            return False
        try:
            return not Path(chiave).exists()
        except OSError:
            return False

    for insieme in (coda, rifai_comunque, scelte):
        insieme.difference_update({k for k in insieme if _sparito(k)})

    # Si scrive lo stato DEI WIDGET, non solo la coda. Cambiare `coda` e
    # rilanciare non serviva a niente: la casella ha una `key`, quindi il suo
    # valore vive nel front-end e il parametro `value=` viene ignorato dopo il
    # primo disegno. Python vedeva nove file selezionati e mostrava la stima,
    # il browser mostrava nove caselle vuote, e al clic successivo rimandava
    # `False` per tutte svuotando la coda: "Avvia" non partiva e non lo diceva.
    # "Deseleziona tutti" faceva il danno speculare, peggiore: le caselle
    # restavano spuntate e i file tolti tornavano dentro e venivano lanciati.
    def _spunta_tutte(valore: bool) -> None:
        for f in files:
            st.session_state[f"q_{f['path']}"] = valore
        st.session_state["coda"] = {f["path"] for f in files} if valore else set()

    # Un modello per TUTTO l'elenco, in un colpo: si applica al cambio e
    # il selettore torna subito al segnaposto (è un'azione, non uno stato —
    # da fermo mentirebbe appena si ritocca una riga singola). "Consigliato
    # per ciascuno" rimette la scelta automatica riga per riga. I giudizi
    # (chip, errori tipo "non arriva a 1080p") restano quelli per-riga.
    def _applica_modello_tutti() -> None:
        scelta = st.session_state.get("modello_tutti")
        if not scelta:
            return
        modelli_tutti = state("modelli", {})
        scelte_tutte = state("scelte_modello", set())
        for f_ in files:
            if scelta == "auto":
                # "Consigliato per ciascuno" applica IL CONSIGLIATO, e conta
                # come una scelta a tutti gli effetti.
                #
                # Prima era il ritiro della scelta: ogni riga tornava al suo
                # "vero", che su un file già convertito è il modello della
                # pagella. Su una serie lavorata ieri con animevideov3 il
                # comando quindi non cambiava niente — prometteva il
                # consigliato e restituiva lo storico (segnalato dall'utente
                # sulle puntate 720p, dove il consigliato è CUGAN).
                # Il ritiro resta possibile riga per riga; qui l'etichetta
                # dice una cosa sola e ora la fa.
                if f_["height"]:
                    consigliato = recommend(f_["height"]).model
                    modelli_tutti[f_["path"]] = consigliato
                    st.session_state[f"m_{f_['path']}"] = consigliato
                    scelte_tutte.add(f_["path"])
            elif f_["height"]:
                modelli_tutti[f_["path"]] = scelta
                st.session_state[f"m_{f_['path']}"] = scelta
                scelte_tutte.add(f_["path"])
        st.session_state["modello_tutti"] = None

    # La scelta della singola riga si registra QUI, nel momento in cui viene
    # fatta: il richiamo gira prima del corpo della pagina, quindi il giro
    # innescato dal cambio trova già il modello nuovo. (Prima il dizionario
    # veniva riempito più in basso, dopo la stima, e per un giro chip e
    # stima giudicavano il modello appena abbandonato.)
    def _scelta_modello(chiave_file: str) -> None:
        valore = st.session_state.get(f"m_{chiave_file}")
        if valore:
            state("modelli", {})[chiave_file] = valore
            state("scelte_modello", set()).add(chiave_file)

    # Niente piu' "Seleziona/Deseleziona tutti": la spunta-madre sta
    # nell'intestazione dell'elenco, a sinistra di FILE, come nelle tabelle
    # di tutto il mondo (deciso dall'utente dopo troppi giri di
    # allineamento fra pulsanti e tendina). Qui resta solo la tendina.
    with st.container(key="sceltaTutti"):
        m, _ = st.columns([1.8, 6.6])
        m.selectbox(
            t("lavb.stesso_modello"), ["auto", *CATALOG],
            index=None, key="modello_tutti",
            on_change=_applica_modello_tutti,
            placeholder=t("lavb.stesso_modello_segnaposto"),
            label_visibility="collapsed", disabled=gpu_occupata,
            format_func=lambda k: (t("lavb.consigliato_ciascuno") if k == "auto"
                                   else CATALOG[k].short))

    pesi = [0.45, 4.4, 1.1, 0.85, 2.5, 1.25, 1.5, 0.5]

    def _spunta_madre() -> None:
        _spunta_tutte(bool(st.session_state.get("spunta_madre")))

    with st.container(key="intestLav"):
        colonne = st.columns(pesi)
        # La spunta-madre riflette lo stato vero a ogni giro (pre-seminata:
        # coincide col risultato del suo stesso on_change, quindi non
        # combatte mai con l'utente) e seleziona/deseleziona tutto.
        tutte = bool(files) and all(f["path"] in state("coda", set())
                                    for f in files)
        st.session_state["spunta_madre"] = tutte
        colonne[0].checkbox(
            t("lavb.tutti_i_file"), key="spunta_madre", on_change=_spunta_madre,
            label_visibility="collapsed", disabled=gpu_occupata,
            help=t("lavb.tutti_i_file_aiuto"))
        for col, label in zip(colonne[1:],
                              [t("lavb.col_file"), t("lavb.col_risoluzione"),
                               t("lavb.col_durata"), t("lavb.col_modello"),
                               t("lavb.col_note"), t("lavb.col_stima"), ""]):
            col.markdown(f"<span class='au-eyebrow'>{label}</span>",
                         unsafe_allow_html=True)

    piani = []
    rifiutati: list[tuple[str, str]] = []
    # Spuntati, ma già lavorati secondo la pagella e con l'uscita sparita:
    # tenuti FUORI dalla coda finché non lo si chiede. `in_forse` sono
    # quelli esclusi, `rifatti` quelli che si è scelto di rifare.
    in_forse: list[tuple[str, str]] = []
    rifatti: list[tuple[str, str]] = []
    # Spuntati ma con l'uscita gia' in OUTPUT: non partono, e il fumetto lo
    # spiega. Contati e non dedotti per differenza, cosi' le tre voci del
    # fumetto tornano sempre con la somma.
    conclusi_in_coda: list[str] = []
    # Spuntati e in lavorazione ADESSO: contati, non dedotti.
    in_corso_coda: list[str] = []
    # Stesso principio dei Sorgenti: ogni riga è un accordion e i dettagli
    # del SUO piano stanno lì dentro. Il pulsante unico "Mostra i dettagli"
    # apriva una sezione lontana, in fondo, scollegata dalle righe.
    aperti_lav = st.session_state.setdefault("dettagli_lav", set())
    # Stessa regola della coda: si chiude un accordion solo se il file e'
    # sparito davvero, non se la scansione non e' riuscita a leggerlo.
    aperti_lav.difference_update({k for k in aperti_lav if _sparito(k)})
    for i, f in enumerate(files):
        path, chiave = Path(f["path"]), f["path"]
        aperto = chiave in aperti_lav
        # La riga conosce il SUO lavoro: barra e stato stanno qui, non in un
        # pannello a parte da ricollegare a occhio.
        lav = _lavoro_di(f["name"])
        elaborando = bool(lav and lav.vivo)
        interrotto = bool(lav and not lav.vivo)
        # Il piano si calcola SUBITO: `fatta` decide la spunta fissa e lo
        # spegnimento della riga durante la catena, quindi serve prima della
        # casella. La stima vale per tutte le righe: è il dato su cui si
        # decide cosa spuntare (misurato: sedici piani in 8 millisecondi).
        # PRIMA di tutto il modello della riga, perché da lui dipendono il
        # piano, la stima, le chip e "fatto". La verità è quella dei FATTI:
        # su un file concluso il modello che lo ha prodotto (dalla pagella),
        # su uno in corso o interrotto quello con cui sta girando (dalla
        # ricetta nella cartella di lavorazione, la stessa che userà il
        # Riprendi), sugli altri il consigliato. Solo una scelta esplicita
        # dell'utente sta sopra a tutto: serve a rifare il file in un altro
        # modo.
        #
        # Qui prima si copiava e basta lo stato del widget nel dizionario, a
        # ogni giro: dal secondo ridisegno in poi OGNI riga risultava scelta
        # a mano e la verità non veniva più consultata. Un file che finiva a
        # pagina aperta continuava a mostrare il modello di prima — lo stesso
        # difetto già visto il 2026-08-10, rientrato per un'altra porta
        # (audit).
        esito = esiti_noti.get(monitor.chiave_nome(f["name"]))
        ricetta = (_leggi_parametri(lav.cartella) if lav else {}).get("modello")
        verita = (_modello_usato(esito)
                  or (ricetta if ricetta in CATALOG else None)
                  or (recommend(f["height"]).model if f["height"] else None))
        if verita and chiave not in scelte:
            modelli[chiave] = verita
            # La tendina ha una `key`: dopo il primo disegno `index=` viene
            # ignorato e vince il valore salvato. Perché la verità vinca va
            # scritta lì dentro, prima che la tendina venga disegnata.
            st.session_state[f"m_{chiave}"] = verita
        # Il piano si costruisce SOLO se l'analisi c'e' gia'. Altrimenti
        # `library.analyse` la farebbe qui, in primo piano: 37 secondi a
        # file misurati, per sedici file una decina di minuti di pagina
        # bloccata mentre il thread di sfondo fa lo stesso lavoro. La riga
        # aspetta il suo turno e si popola da sola (la pagina si aggiorna
        # ogni cinque secondi finche' l'analisi lavora).
        analizzato = library.cached_report(path) is not None
        piano, errore = None, None
        if analizzato:
            try:
                piano = plan_for(path, cfg, f["height"])
            except (PlanError, OSError, FFmpegError, ValueError) as exc:
                errore = exc
        # "Fatto" = l'USCITA esiste, punto. Un'uscita difettosa viene
        # rinominata .PARZIALE, quindi qui non esiste e non inganna.
        # (La pagella — durata reale, avvisi, modello, nome dell'uscita — è
        # gia' stata letta piu' sopra: da lei nasce il modello della riga.)
        # "Fatto" sono DUE cose diverse, e tenerle insieme costava caro.
        #  - `fatta`: l'uscita e' li'. Solo questa fa SALTARE il file al
        #    lancio, ed e' anche cio' che decide la CLI per conto suo
        #    ("gia' presente"): le due non possono divergere.
        #  - `archiviata`: la pagella dice che quel file e' stato prodotto,
        #    con ESATTAMENTE questi parametri, ma l'uscita non e' piu' in
        #    OUTPUT — spostata nella libreria, che e' il gesto normale a
        #    lavoro finito. E' un fatto storico vero e va MOSTRATO; non fa
        #    saltare niente, cosi' per rifare il file basta rispuntarlo e
        #    non c'e' nessuna pagella da cancellare a mano.
        # Il confronto e' fra NOMI di uscita: quel nome porta dentro altezza,
        # modello, scala, CRF e deduplica, quindi e' il controllo dei
        # parametri per intero, in una riga. (Prima si confrontava il solo
        # modello: un file restava "fatto" anche cambiando CRF o altezza, e
        # l'Avvia lo saltava in silenzio — audit del 2026-08-10.)
        # Anche col nome vecchio: un file prodotto prima della
        # distinzione upscale/supersampling e' fatto lo stesso.
        fatta = bool(piano is not None and piano.uscita_esiste)
        # DUE condizioni, non una. La pagella si scrive anche quando l'uscita
        # e' risultata DIFETTOSA (vedi cli.py: `_scrivi_esito` sta fuori
        # dall'else), e in quel caso il file buono non esiste — e' stato
        # rinominato .PARZIALE apposta perche' il rilancio lo rifaccia.
        # Senza `not difettosa` un episodio mutilato veniva mostrato come
        # fatto e tenuto FUORI dalla coda: esattamente il danno permanente
        # che quella rinomina esiste per impedire (audit del 2026-08-10).
        archiviata = bool(piano is not None and esito
                          and esito.get("output") in {u.name for u in piano.uscite_note}
                          and not esito.get("difettosa"))
        # Una lavorazione A META' sul disco batte la pagella di un lavoro
        # precedente: dichiararla "fatta" nascondeva Riprendi e Scarta, e
        # quei gigabyte non erano piu' raggiungibili da nessuna parte
        # dell'interfaccia. UNA variabile sola per questo giudizio, usata sia
        # da quel che si vede sia da quel che entra in coda: tenendo due
        # condizioni gemelle in due punti lontani, la riga diceva
        # "interrotto" e la barra "gia' lavorato, per ora viene saltato"
        # sullo stesso file (audit del 2026-08-10).
        gia_prodotta = archiviata and not interrotto
        # Per tutto cio' che si VEDE — chip, "Finito in", riga verde — vale
        # anche il lavoro archiviato altrove.
        risulta_fatta = fatta or gia_prodotta
        # L'ultima lavorazione ha prodotto un file ROTTO (uscita messa da
        # parte come .PARZIALE). Non e' "fatto" e non e' "mai toccato": e' la
        # cosa piu' importante che quella riga abbia da dire, e senza questa
        # chip spariva del tutto dall'interfaccia.
        difettosa = bool(piano is not None and esito
                         and esito.get("difettosa")
                         and esito.get("output") in {u.name for u in piano.uscite_note}
                         and not fatta)
        # Membro = sta nel PROGRAMMA di questa catena. Un file fatto la
        # settimana scorsa non lo e', e prima si prendeva la spunta finta
        # come se facesse parte del lancio in corso. Resta comunque acceso
        # (vedi `fuori` piu' sotto): visibile, ma non spacciato per membro.
        membro = _in_catena(f["name"], risulta_fatta, lav is not None)

        riga_box = st.container(key=f"jrow{i}")
        with riga_box:
            c = st.columns(pesi)

        if gpu_occupata:
            # Durante la catena la casella è un INDICATORE, non un widget:
            # spunta fissa per i membri del lancio (fatti, in corso,
            # interrotti, in coda), vuota e spenta per gli altri. Il widget
            # vero tornerà a catena finita, ripescando la coda salvata.
            c[0].markdown(f"<span class='au-cb-finta"
                          f"{' au-cb-si' if membro else ''}'></span>",
                          unsafe_allow_html=True)
            spuntato = membro
        else:
            spuntato = c[0].checkbox(
                t("lavb.elabora", nome=f["name"]), value=chiave in coda,
                key=f"q_{chiave}",
                label_visibility="collapsed",
                # Senza analisi non c'e' piano, quindi non c'e' niente da
                # avviare: spuntarlo avrebbe promesso una lavorazione che
                # l'Avvia avrebbe silenziosamente saltato.
                disabled=elaborando or not analizzato)
            if elaborando or not analizzato:
                coda.discard(chiave)
            elif spuntato:
                coda.add(chiave)
            else:
                coda.discard(chiave)

        # Il segno di selezione: il CSS lo legge con `:has()` per accendere il
        # bordo sinistro e togliere l'attenuazione. Stessa tecnica delle righe
        # dei sorgenti — lo stato non entra nella chiave, che deve restare
        # fissa o Streamlit lascia in pagina sottoalberi vecchi.
        # `au-fuori` spegne l'intera riga (saturazione zero, alpha basso):
        # durante la maratona i file fuori programma sono scenografia.
        # Un file GIA' FATTO non e' scenografia: e' il risultato della
        # maratona in corso, e va visto. Si spengono solo i file che non
        # c'entrano niente col lancio. (Con piu' modelli nello stesso
        # lancio il marcatore porta solo il programma del PROPRIO comando,
        # quindi i file dei gruppi precedenti uscivano dal programma e si
        # spegnevano appena la catena passava oltre: e' il difetto visto
        # dall'utente il 2026-08-10.)
        fuori = gpu_occupata and not membro and not risulta_fatta
        c[1].markdown(
            f"<span class='au-stato{' au-sel' if spuntato else ''}"
            f"{' au-open' if aperto else ''}{' au-fuori' if fuori else ''}"
            f"{' au-compiuta' if gpu_occupata and risulta_fatta else ''}"
            f"{' au-con-avvisi' if gpu_occupata and risulta_fatta and (esito or {}).get('avvisi') else ''}'>"
            f"</span>"
            f"<div class='au-name'>{esc(f['name'])}</div>", unsafe_allow_html=True)
        c[2].markdown(f"<div class='au-cell'>{f['resolution']}</div>",
                      unsafe_allow_html=True)
        c[3].markdown(f"<div class='au-cell'>{f['duration']}</div>",
                      unsafe_allow_html=True)

        if f["height"]:
            suggerimento = recommend(f["height"])
            consigliato = suggerimento.model
            chiavi = list(CATALOG)
            # Il modello della riga è già deciso in cima al giro (verità dei
            # fatti, o scelta esplicita se c'è): qui la tendina lo mostra e
            # basta. Dire "CUGAN" accanto a "fatto" su un file prodotto con
            # animevideov3 è semplicemente falso (visto dall'utente il
            # 2026-08-10).
            attuale = modelli.get(chiave) or consigliato
            # Il nome del modello e basta. Il giudizio va nella chip accanto:
            # dentro la tendina può essere solo testo semplice, perché
            # `format_func` restituisce una stringa e le voci dell'elenco le
            # disegna Streamlit.
            c[4].selectbox(
                "modello", chiavi, index=chiavi.index(attuale), key=f"m_{chiave}",
                label_visibility="collapsed", help=suggerimento.reason,
                # La scelta si registra nel richiamo, non dal valore di
                # ritorno: un ritorno lo dà anche un ridisegno qualunque, e
                # scambiarlo per una scelta è proprio il difetto corretto qui.
                on_change=_scelta_modello, args=(chiave,),
                # Spenta per tutti durante la catena: i piani del lancio sono
                # già decisi, e cambiare il modello a metà non fa nulla.
                disabled=elaborando or gpu_occupata,
                # Etichette PULITE alla fonte: il " (consigliato)"
                # nell'elenco aperto lo aggiunge il CSS (vedi il sentinella
                # in header), cosi' non c'e' niente da nascondere altrove e
                # niente puo' sfarfallare.
                format_func=lambda k: CATALOG[k].short)
        # Equivale a `interrotto and risulta_fatta` per costruzione (una
        # lavorazione a meta' esclude gia' `gia_prodotta`): scritto cosi'
        # perche' sia leggibile senza rifare l'algebra, non perche' sia
        # una protezione in piu'.
        concluso = bool(interrotto and fatta)

        if elaborando:
            # «in pausa» e non «in corso»: se i processi sono congelati la
            # riga non deve raccontare un lavoro che non sta avvenendo — e
            # nemmeno passare per interrotta, perche' non lo e'.
            if lav is not None and monitor.sospeso(lav) is not None:
                c[5].markdown(
                    "<span class='au-tag au-warn au-perche' tabindex='0'>"
                    + t("lavb.chip_pausa")
                    + _bolla(t("lavb.chip_pausa_aiuto"))
                    + "</span>", unsafe_allow_html=True)
            else:
                c[5].markdown("<span class='au-tag au-busy'>"
                              f"{t('lavb.chip_in_corso')}</span>",
                              unsafe_allow_html=True)
        elif difettosa:
            # PRIMA di ogni altro giudizio: che l'ultima lavorazione abbia
            # prodotto un file rotto conta più del modello consigliato. La
            # riga resta in coda (è giusto rifarla) e lo dice.
            c[5].markdown(
                "<span class='au-tag au-err au-perche' tabindex='0'>"
                + t("lavb.chip_da_rifare")
                + _bolla(t("lavb.chip_da_rifare_aiuto"))
                + "</span>",
                unsafe_allow_html=True)
        elif risulta_fatta:
            if fatta:
                chip = f"<span class='au-tag au-fatta'>{t('lavb.chip_fatto')}</span>"
            else:
                # Prodotto, ma l'uscita non è più in OUTPUT. Dirlo e basta
                # sarebbe una mezza verità: chi legge deve sapere che
                # rispuntarlo lo rifà — è l'unica cosa che cambia davvero
                # rispetto a un file ancora in cartella.
                chip = ("<span class='au-tag au-fatta au-perche' tabindex='0'>"
                        + t("lavb.chip_fatto")
                        + _bolla(t("lavb.chip_fatto_spostato"))
                        + "</span>")
            avvisi = (esito or {}).get("avvisi") or []
            if avvisi:
                # Come il "1 avviso" dei Sorgenti: giallo, col dettaglio nel
                # fumetto — un esito con avvisi non deve passare per liscio.
                chip += (f" <span class='au-tag au-warn au-perche' tabindex='0'>"
                         f"{tn('lavb.avvisi', len(avvisi))}"
                         f"{_bolla(' · '.join(avvisi))}</span>")
            c[5].markdown(chip, unsafe_allow_html=True)
        elif interrotto:
            chip = f"<span class='au-tag au-warn'>{t('lavb.chip_interrotto')}</span>"
            # Se la ricetta salvata differisce dalla sidebar, la chip lo
            # dice: Riprendi userà la ricetta (blindato), non la sidebar.
            ricetta = _leggi_parametri(lav.cartella if lav else None)
            # Lo spazio no, come nell'avviso della sidebar: si ricalcola a
            # ogni avvio e la chip sarebbe accesa quasi sempre per lui (vedi
            # `_FUORI_DAL_CONFRONTO`). Nel fumetto resta, come parte della
            # ricetta.
            if ricetta and any(
                    k in ricetta and ricetta[k] != cfg.get(k)
                    for k in ("altezza", "crf", "preset", "dedup",
                              "denoise", "forza")):
                descr = " · ".join(filter(None, [
                    f"{ricetta.get('altezza')}p" if "altezza" in ricetta else "",
                    f"CRF {ricetta.get('crf')}" if "crf" in ricetta else "",
                    ricetta.get("preset", ""),
                    f"{ricetta.get('disco')} GB" if "disco" in ricetta else "",
                    CATALOG[ricetta["modello"]].short
                    if ricetta.get("modello") in CATALOG else "",
                ]))
                chip += (" <span class='au-tag au-dim au-perche' tabindex='0'>"
                         + t("lavb.chip_parametri_suoi")
                         + _bolla(t("lavb.chip_parametri_suoi_aiuto", descr=descr))
                         + "</span>")
            c[5].markdown(chip, unsafe_allow_html=True)
        elif not analizzato:
            c[5].markdown("<span class='au-tag au-dim'>"
                          f"{t('lavb.chip_attesa_analisi')}</span>",
                          unsafe_allow_html=True)
        elif f["name"] in in_coda_ora:
            c[5].markdown("<span class='au-tag au-coda'>"
                          f"{t('lavb.chip_in_coda')}</span>",
                          unsafe_allow_html=True)
        elif errore is not None:
            # La chip dice QUALE ostacolo, il perché per esteso sta nel
            # suggerimento: "non elaborabile" non diceva niente, e il motivo
            # compariva solo sotto l'elenco e solo per le righe spuntate.
            breve = getattr(errore, "sintesi", t("lavb.non_elaborabile"))
            c[5].markdown(
                f"<span class='au-tag au-err au-perche' tabindex='0'>"
                f"{esc(breve)}{_bolla(str(errore))}</span>",
                unsafe_allow_html=True)
            # Raccolti e mostrati DOPO l'elenco: scritti qui diventavano
            # paragrafi a tutta larghezza infilati fra due righe della
            # tabella. E niente `:orange[...]`: una parentesi quadra nel
            # nome — cioè quasi ogni rilascio anime — ne rompe la sintassi.
            if spuntato:
                rifiutati.append((f["name"], str(errore)))
        elif f["height"]:
            # La chip giudica il modello SELEZIONATO, qualunque sia: prima
            # compariva solo quando coincideva col consigliato, e scegliendo
            # lo sconsigliato la riga taceva — proprio nel caso in cui aveva
            # qualcosa da dire.
            giudizio = (suggerimento.giudizi or {}).get(modelli.get(chiave))
            chip_riga = {
                "ok": f"<span class='au-tag au-ok'>{t('lavb.giudizio_ok')}</span>",
                "verifica": ("<span class='au-tag au-warn'>"
                             f"{t('lavb.giudizio_verifica')}</span>"),
                "no": f"<span class='au-tag au-err'>{t('lavb.giudizio_no')}</span>",
            }.get(giudizio)
            if chip_riga:
                c[5].markdown(chip_riga, unsafe_allow_html=True)

        if piano is not None:
            # I file già FATTI non entrano nei piani: la CLI li salterebbe
            # comunque ("già presente") e intanto gonfiavano la stima.
            if spuntato and elaborando:
                in_corso_coda.append(chiave)
            if spuntato and not elaborando:
                if fatta:
                    # Spuntato ma l'uscita c'e' gia': la CLI lo salterebbe
                    # comunque. Contato, perche' il fumetto dica PERCHE' i
                    # file che partono sono meno di quelli spuntati.
                    conclusi_in_coda.append(chiave)
                # L'uscita non c'è più, ma la pagella dice che quel lavoro è
                # stato fatto: prima di rifare ore di GPU si chiede.
                elif gia_prodotta and chiave not in rifai_comunque:
                    in_forse.append((chiave, f["name"]))
                else:
                    piani.append(piano)
                    if gia_prodotta:
                        rifatti.append((chiave, f["name"]))
        # Riprendi e Scarta stanno FUORI dal piano: una lavorazione a metà
        # va ripresa o buttata anche se il file non e' ancora analizzato,
        # altrimenti quei gigabyte non sono piu' raggiungibili da nessuna
        # parte dell'interfaccia.
        # Lo stesso vale per la cartella rimasta in JOBS accanto a un'uscita
        # gia' in OUTPUT (`concluso`): niente Riprendi, ma lo Scarta si', o
        # quei GB restavano raggiungibili solo dal Finder.
        armato_via = st.session_state.get("conferma_scarta")
        scarta_in_conferma = (interrotto and isinstance(armato_via, tuple)
                              and armato_via[0] == chiave
                              and time.time() - armato_via[1] < 10)
        if interrotto and (not concluso or scarta_in_conferma):
            if scarta_in_conferma:
                # Stesso schema del Ferma: conferma nel pulsante stesso,
                # rosso pieno, scadenza da sola in 10 secondi.
                if c[6].button(t("lavb.conferma_scarta"), key=f"scartasi{i}",
                               use_container_width=True):
                    st.session_state.pop("conferma_scarta", None)
                    # Guardia: si butta SOLO una cartella dentro
                    # JOBS. Sorgente e OUTPUT non si toccano mai.
                    if (lav is not None
                            and PATHS.work in lav.cartella.parents):
                        shutil.rmtree(lav.cartella, ignore_errors=True)
                        # Su una riga conclusa non torna "come nuova":
                        # l'uscita resta, se ne va solo il residuo.
                        st.toast(t("lavb.residuo_scartato") if concluso
                                 else t("lavb.scartata"))
                    st.rerun()
            else:
                # Riprendere = rilanciare lo stesso file: la pipeline
                # ritrova il suo stato su disco e riparte da dove si era
                # fermata, coi parametri della ricetta (blindato).
                if c[6].button(t("lavb.riprendi"), key=f"rip{i}",
                               use_container_width=True,
                               # Senza referto non c'e' piano, e `_riprendi`
                               # arrivava a leggere `piano.model_key` su
                               # None: traceback rosso in pagina. Succedeva
                               # aprendo la pagina subito dopo
                               # un'interruzione, o per un singhiozzo di
                               # lettura del disco esterno (`cached_report`
                               # torna None su qualunque errore di lettura).
                               # Lo Scarta invece resta sempre disponibile:
                               # non gli serve il piano, e serve a liberare
                               # i gigabyte.
                               disabled=(gpu_occupata or piano is None
                                         or tarando),
                               help=(t("lavb.taratura_blocca") if tarando
                                     else None if piano is not None else
                                     t("lavb.riprendi_attesa"))):
                    if _riprendi(piano, lav.cartella if lav else None, cfg):
                        st.session_state["appena_avviata"] = True
                        st.session_state["attesa_avvio"] = time.time()
                if lav is not None and c[6].button(
                        t("lavb.scarta"), key=f"scarta{i}",
                        use_container_width=True,
                        disabled=gpu_occupata,
                        help=t("lavb.scarta_aiuto")):
                    st.session_state["conferma_scarta"] = (chiave,
                                                          time.time())
                    st.rerun()
        elif risulta_fatta:
            # Il tempo VERO al posto della forchetta: a episodio finito
            # la stima è storia, quello che conta è quanto c'e' voluto.
            secondi = (esito or {}).get("secondi")
            if secondi:
                # Lavorato in piu' riprese: il totale supera quello
                # di una passata dritta, e va detto PERCHE'. Non e' un
                # avviso (il file e' a posto): e' una nota appesa al
                # numero che la spiega.
                riprese = int((esito or {}).get("riprese") or 1)
                perche_riprese = ""
                if riprese > 1 and piano is not None and piano.chunks:
                    blocco = piano.est_gpu_seconds / piano.chunks / 60
                    perche_riprese = (
                        f"<span class='au-perche' tabindex='0'>"
                        "<svg width='13' height='13' viewBox='0 0 24 24' "
                        "fill='none' stroke='currentColor' "
                        "stroke-width='2' stroke-linecap='round' "
                        "stroke-linejoin='round' aria-hidden='true'>"
                        "<circle cx='12' cy='12' r='10'></circle>"
                        "<path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3'>"
                        "</path><line x1='12' y1='17' x2='12.01' y2='17'>"
                        "</line></svg>"
                        + _bolla(t("lavb.riprese_aiuto", riprese=riprese,
                                   minuti=round(blocco)))
                        + "</span>")
                c[6].markdown("<div class='au-stima-riga'>"
                              f"{t('lavb.finito_in', durata=stima_hm(secondi))}"
                              f"{perche_riprese}</div>",
                              unsafe_allow_html=True)
            # Uscita fatta ma cartella di lavoro ancora in JOBS: oggi la
            # pipeline la tiene solo per un difetto (e allora l'uscita diventa
            # .PARZIALE, quindi qui non si arriva), percio' e' un residuo —
            # una versione vecchia che la teneva per gli avvisi, una pulizia
            # interrotta, `--tieni-temp`. Si libera con lo stesso Scarta in
            # due passi delle lavorazioni a meta'.
            if concluso and lav is not None and c[6].button(
                    t("lavb.scarta"), key=f"scarta{i}",
                    use_container_width=True,
                    disabled=gpu_occupata,
                    help=t("lavb.scarta_residuo_aiuto")):
                st.session_state["conferma_scarta"] = (chiave, time.time())
                st.rerun()
        elif not elaborando and piano is not None:
            # Il valore PIÙ PROBABILE, come nella fascia: la forchetta
            # scritta con la barra ("05h 08m / 07h 49m") non diceva quali
            # fossero i due numeri, e chi legge una cella di elenco non ha
            # nessuna legenda a cui appoggiarsi. L'intervallo resta, nel
            # fumetto, per chi vuole sapere quanto può ballare.
            b, alto = piano.est_best_seconds, piano.est_total_seconds
            stima = f"≈ {stima_hm(piano.est_attesa_seconds)}"
            if b < alto * 0.95:
                # Con la deduplica MISURATA su questo file l'incertezza non
                # è più «quanti fotogrammi ripetuti ci saranno»: quella
                # domanda ha già risposta. Resta solo quanto sbaglia il
                # modello, e dirlo con la nota vecchia sarebbe mentire su
                # cosa sappiamo.
                stima += _icona_info(
                    t("lavb.durata_stimata"),
                    [t("lavb.piu_probabile",
                       durata=stima_hm(piano.est_attesa_seconds)),
                     t("lavb.durata_possibile", da=stima_hm(b),
                       a=stima_hm(alto))],
                    nota=(t("lavb.nota_dedup_misurata",
                            quota=f"{piano.dedup.expected_ratio:.0%}")
                          if piano.dedup.misurata else
                          t("lavb.nota_dedup")))
            c[6].markdown(f"<div class='au-stima-riga'>{stima}</div>",
                          unsafe_allow_html=True)

        if elaborando:
            # Niente pulsante Pausa QUI: sta nella fascia in basso, accanto a
            # Ferma tutto, perché il suo raggio è la macchina e non il singolo
            # file. Sulla riga resta il solo indicatore «in pausa», che è dove
            # se ne vede l'effetto — la barra che smette di avanzare.
            #
            # Ferma con conferma in due passi A SCADENZA: il primo click arma,
            # il secondo (entro 10 secondi) esegue, poi si disarma da solo al
            # giro dopo. Niente finestre di dialogo: la conferma sta nel
            # pulsante stesso, che cambia faccia e colore.
            armato_stop = st.session_state.get("conferma_ferma")
            in_conferma = (isinstance(armato_stop, tuple)
                           and armato_stop[0] == chiave
                           and time.time() - armato_stop[1] < 10)
            if not in_conferma:
                if c[6].button(t("lavb.ferma"), key=f"ferma{i}",
                               use_container_width=True,
                               help=t("lavb.ferma_aiuto")):
                    st.session_state["conferma_ferma"] = (chiave, time.time())
                    st.rerun()
            else:
                if c[6].button(t("lavb.conferma_stop"), key=f"fermasi{i}",
                               use_container_width=True):
                    st.session_state.pop("conferma_ferma", None)
                    _ferma(lav, tutto=False)
                    st.toast(t("lavb.interruzione_richiesta"))
                    time.sleep(1.5)
                    st.rerun()

        # La barra vive DENTRO la riga, sotto la testata, con tutto il testo
        # etichettato accanto: fps, quanto resta, quanto è trascorso.
        if lav is not None:
            with riga_box:
                # Niente istruzioni con preposizioni spaziali sbagliate: il
                # pulsante si chiama Riprendi e si spiega da solo.
                if lav.vivo:
                    # RIQUADRO SUO: si aggiorna ogni cinque secondi senza
                    # toccare un solo pixel del resto della riga. Vedi
                    # `_avanzamento_vivo` per il perche'.
                    st.fragment(run_every="5s")(_avanzamento_vivo)(
                        lav.cartella.name, _turno_previsto(piano, lav))
                    dett = None
                elif concluso:
                    dett = t("lavb.concluso_residuo")
                else:
                    dett = t("lavb.fermo_al", quota=f"{lav.frazione:.0%}",
                             fatti=lav.fatti, totale=lav.totale)
                # Solo per le righe FERME: quella viva l'ha gia' disegnata il
                # suo riquadro qui sopra, e ridisegnarla qui la
                # raddoppierebbe.
                if dett is not None:
                    st.markdown(
                        f"<div class='au-riga-avanz'>"
                        f"<div class='au-riga-barra au-riga-ferma'>"
                        f"<span style='width:{lav.frazione * 100:.1f}%'>"
                        f"</span></div>"
                        f"<span class='au-meta'>{esc(dett)}</span></div>",
                        unsafe_allow_html=True)

        if c[7].button("", key=f"detlav{i}", use_container_width=True,
                       icon=(":material/keyboard_arrow_up:" if aperto
                             else ":material/keyboard_arrow_down:")):
            aperti_lav.discard(chiave) if aperto else aperti_lav.add(chiave)
            st.rerun()

        # Il pannello è SEMPRE montato e chiuso sta a altezza zero, come nei
        # Sorgenti: è ciò che permette di animare anche la chiusura.
        with riga_box:
            with st.container(key=f"dettlav{i}"):
                with st.container():
                    _dettagli_piano(piano, errore,
                                    esito=esito if (risulta_fatta
                                                    or difettosa) else None)

    # Lo scroll promesso all'ingresso nella scheda: SOLO se c'è davvero una
    # riga al lavoro, e una volta sola (il segnale si consuma qui).
    # L'iframe c'è SEMPRE, anche vuoto: un elemento che compare e scompare
    # cambia la conta posizionale su cui Streamlit riconcilia il DOM, ed è
    # la ricetta del brodo di nodi adottati (misurato: card del Confronto
    # dentro le righe dei Sorgenti).
    scrolla = (st.session_state.pop("scroll_al_lavoro", False)
               and any(l.vivo for l in lavori_tutti))
    st.iframe(
        # Animazione fatta a mano: scrollIntoView non lascia scegliere ne'
        # durata ne' curva, e l'utente vuole uno scroll piu' lento (~750 ms,
        # una volta e mezza lo smooth di Chrome) con ease-in-out. Il
        # requestAnimationFrame va preso dal PARENT: in un iframe alto zero
        # il browser lo strozza.
        ("<script>setTimeout(() => {"
         "const D=window.parent.document;"
         "const b=D.querySelector('[class*=\"st-key-jrow\"] .au-tag.au-busy');"
         "if(!b)return;"
         "const m=D.querySelector('[data-testid=\"stMain\"]');"
         "const r=b.closest('[class*=\"st-key-jrow\"]').getBoundingClientRect();"
         "const da=m.scrollTop;"
         "const fine=Math.max(0,Math.min("
         "da+r.top+r.height/2-m.clientHeight/2,"
         "m.scrollHeight-m.clientHeight));"
         "const raf=window.parent.requestAnimationFrame.bind(window.parent);"
         "let t0=null;"
         "const passo=t=>{if(t0===null)t0=t;"
         "const x=Math.min(1,(t-t0)/750);"
         "const e=x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2;"
         "m.scrollTop=da+(fine-da)*e;"
         "if(x<1)raf(passo);};"
         "raf(passo);"
         "}, 450);</script>") if scrolla else "<!-- niente da scrollare -->",
        height=1)

    if rifiutati:
        st.write("")
        for nome, motivo in rifiutati:
            st.markdown(
                f"<div class='au-hint'><span class='au-tag au-warn'>"
                f"{t('lavb.non_elaborabile')}</span>&nbsp; <b>{esc(nome)}</b> — "
                f"{esc(motivo)}</div>",
                unsafe_allow_html=True)

    st.session_state["coda"] = coda
    st.session_state["modelli"] = modelli

    # LA FASCIA IN BASSO, riquadro suo. E' il secondo (e ultimo) pezzo che
    # cambia davvero ogni cinque secondi: numeri della coda, stima, stato dei
    # pulsanti. Chiuso qui dentro, si aggiorna da solo senza far ridisegnare
    # le righe dell'elenco — che e' l'intera ragione di questa modifica.
    #
    # Le letture dello STATO si rifanno qui, fresche: il riquadro si riesegue
    # per conto suo e non puo' fidarsi di valori catturati prima. Gli
    # AGGREGATI invece arrivano dalla chiusura (coda, piani, in_forse,
    # rifatti, rifiutati, modelli...) ed e' corretto che siano quelli
    # dell'ultimo disegno completo: dipendono da quali file ci sono, da cosa
    # e' spuntato e dalle impostazioni, tre cose che non possono cambiare
    # senza un ridisegno completo.
    @st.fragment(run_every="5s" if armato else None)
    def _fascia_viva() -> None:
        # La sorveglianza della firma sta ANCHE qui, e non per ridondanza:
        # fra un file e l'altro questo e' l'unico riquadro vivo — la barra di
        # avanzamento non esiste perche' non c'e' niente in lavorazione — e
        # senza questa riga il file successivo parte senza che l'elenco se ne
        # accorga (visto dall'utente al primo cambio di file).
        _controlla_firma()
        lavori_tutti = monitor.lavori()
        catena_ora = monitor.catena()
        pausa_ora = monitor.pausa()
        gpu_occupata = (any(l.vivo for l in lavori_tutti)
                        or pausa_ora is not None or catena_ora is not None)
        tarando = taratura.in_corso()
        in_coda_ora = (set(catena_ora.get("in_coda") or [])
                       if catena_ora else set())
        with st.container(key="barra"):
            # I due pulsanti in UNA colonna sola, affiancati come "Seleziona /
            # Deseleziona tutti": due colonne separate li tenevano distanti
            # quanto le colonne, non quanto serviva a leggerli come una coppia.
            a, azioni = st.columns([7, 3])

            vivo_qualcosa = any(l.vivo for l in lavori_tutti)
            # Un avvio appena chiesto ha una fase muta (analisi dei file, fino a
            # un minuto con un lotto grosso): senza questo cuscinetto la barra
            # taceva e "non mi pare stia lavorando" (successo, col messaggio
            # verde già sparito per il rerun).
            attesa_avvio = st.session_state.get("attesa_avvio", 0)
            in_avvio = (not gpu_occupata and time.time() - attesa_avvio < 180)

            if gpu_occupata:
                # Durante la catena la barra racconta SOLO la catena: niente
                # "Nessun file selezionato" (tanto le caselle sono spente), e la
                # vecchia banda rossa non serve più — se non puoi selezionare,
                # non c'e' niente da vietare. Ordine: riepilogo, poi la banda.
                n, tot = ((catena_ora.get("numero"), catena_ora.get("totale"))
                          if catena_ora else (None, None))
                # In attesa si conta dal totale del LANCIO, non dalla coda del
                # singolo comando: con piu' modelli i comandi sono piu' d'uno e
                # l'ultimo file di un gruppo avrebbe detto "0 in attesa" mentre
                # un altro gruppo aspettava.
                completo = bool(tot and n)
                if completo:
                    fatti_coda, attesa = n - 1, max(0, tot - n)
                else:
                    fatti_coda, attesa = 0, len(in_coda_ora)

                # Titolo: dove siamo. Sottotitolo: com'e' composta la coda.
                # Il tempo, che e' l'informazione che si cerca davvero, sta
                # staccato sotto (vedi `au-catena`).
                if completo:
                    titolo = f"**{t('lavb.elaborazione_di', numero=n, totale=tot)}**"
                    if attesa:
                        titolo += f" · {tn('lavb.file_in_attesa', attesa)}"
                    a.markdown(titolo, unsafe_allow_html=True)
                    voci = []
                    if fatti_coda:
                        voci.append(tn("lavb.completati", fatti_coda))
                    voci.append(t("lavb.uno_in_elaborazione"))
                    if attesa:
                        voci.append(t("lavb.n_in_attesa", n=attesa))
                    a.markdown("<div class='au-coda-dettaglio'>"
                               f"{t('lavb.coda_voci', voci=' · '.join(voci))}</div>",
                               unsafe_allow_html=True)
                else:
                    a.markdown(f"**{t('lavb.titolo_in_corso')}**",
                               unsafe_allow_html=True)

                if pausa_ora is not None and not vivo_qualcosa:
                    riparte = time.strftime("%H:%M", time.localtime(pausa_ora[0]))
                    posiz = (t("lavb.pausa_posiz", numero=n, totale=tot)
                             if tot and tot > 1 else "")
                    a.markdown("<div class='au-riga-pausa'>"
                               f"{t('lavb.coda_in_pausa', posiz=posiz, ora=riparte)}"
                               "</div>", unsafe_allow_html=True)
                elif catena_ora is not None:
                    # L'ora di fine e' CALCOLATA dalla stima, non un numero
                    # letto altrove: i due valori del marcatore sono durate
                    # (minimo e massimo), e leggerli come orari sarebbe un
                    # numero inventato.
                    # Il conto sta in `monitor.residuo_coda` perche' sia
                    # eseguibile da un test: mescola una MISURA (il file in
                    # corso) e delle STIME (quelli dopo), e uno sbaglio nel
                    # mescolarli non si vede guardando la pagina — si vede
                    # ore dopo, quando l'ora promessa passa e il lavoro va
                    # avanti.
                    #
                    # Il lavoro vivo si prende PER NOME, non "il primo che
                    # capita": se accanto alla catena gira una lavorazione
                    # avviata a mano dalla CLI, il residuo di QUELLA finirebbe
                    # nella fascia spacciato per il file della coda.
                    #
                    # E solo nelle fasi in cui il ritmo misura l'UPSCALE. In
                    # estrazione il ritmo e' quello dell'estrazione, e il
                    # «restano» che ne esce e' il tempo per finire di
                    # estrarre: buono sulla riga, che dice «fase 1/3»,
                    # disastroso qui, dove verrebbe letto come il tempo per
                    # finire il file — cioe' ore in meno del vero.
                    vivo = next((l for l in lavori_tutti if l.vivo
                                 and l.sorgente == catena_ora.get("file")
                                 and l.fase in monitor.UNITA_UPSCALE), None)
                    _stati = st.session_state.get("mon_stati") or {}
                    # Finche' non si e' cronometrato un turno di codifica, la
                    # misura NON copre i turni che restano e sarebbe piu'
                    # corta del vero: nel primo blocco di Koyomimonogatari 12
                    # sarebbero stati nove turni, una ventina di minuti su
                    # tre ore. La riga puo' permetterselo — dice «fase 2/3» e
                    # ha il ripiego dal piano — la fascia no, perche' li'
                    # quel numero e' l'ora in cui finisce tutto. Meglio la
                    # stima di partenza, che i turni li conta.
                    misurabile = (
                        vivo is not None
                        and (monitor.turno_misurato(_stati, vivo.cartella.name)
                             is not None
                             or not vivo.blocchi_totali
                             or vivo.blocco_n >= vivo.blocchi_totali))
                    residuo = monitor.residuo_coda(
                        catena_ora,
                        _resto_misurato(
                            vivo,
                            st.session_state.get("mon_campioni") or {},
                            _stati)
                        if misurabile else None)
                    if residuo is not None:
                        mn, mx = residuo
                        # Il GIORNO va detto quando non e' oggi: «fra le 23:48
                        # e le 02:43» non dice a chi legge di sera che le 02:43
                        # sono di domani, e su una coda da piu' giorni diventa
                        # indecifrabile (segnalato dall'utente).
                        _adesso = time.time()
                        # Etichette e dati distinti dal COLORE, non dal peso:
                        # la riga resta un unico blocco di testo, e l'occhio
                        # trova subito i numeri.
                        if mx <= 60:
                            # La stima è esaurita ma il lavoro no: continuare a
                            # spostare l'orologio in avanti sarebbe una bugia, e
                            # un orario nel passato pure. Si dice quel che si sa.
                            quanto, quando = (t("lavb.meno_di_un_minuto"),
                                              t("lavb.a_minuti"))
                        elif mn < mx * 0.95 and mn > 60:
                            quanto = t("lavb.da_a", da=stima_hm(mn),
                                       a=stima_hm(mx))
                            quando = quando_finisce(_adesso + mn, _adesso + mx)
                        else:
                            quanto = stima_hm(mx)
                            quando = quando_finisce(_adesso + mx, _adesso + mx)
                        # "per l'intera coda", esplicito: il numero è il residuo
                        # di TUTTI i file rimasti, pause fra l'uno e l'altro
                        # comprese, e si leggeva come se riguardasse solo il file
                        # in corso — che è quello nominato due righe sopra.
                        testo = (f"<span class='au-eti'>"
                                 f"{t('lavb.rimanente_coda', quanto=quanto)}</span> · "
                                 f"<span class='au-val'>"
                                 f"{t('lavb.fine_prevista', quando=quando)}</span>")
                    else:
                        testo = t("lavb.in_lavorazione_file",
                                  nome=esc(str(catena_ora.get('file', ''))))
                    a.markdown(f"<div class='au-catena'>{testo}</div>",
                               unsafe_allow_html=True)
            elif in_avvio:
                a.markdown(f"<div class='au-catena'>{t('lavb.avvio_in_corso')}</div>",
                           unsafe_allow_html=True)
            elif not coda:
                a.markdown(f"<span class='au-hint'>{t('lavb.nessun_file')}</span>",
                           unsafe_allow_html=True)
            else:
                # Le pause fra un file e l'altro entrano nel totale della CODA
                # (non nella stima del singolo file, che dice quanto ci vuole a
                # finire quello): con dieci file e cinque minuti di respiro sono
                # quarantacinque minuti che prima sparivano dal conto.
                respiro = max(0, len(piani) - 1) * int(cfg.get("pausa") or 0) * 60
                totale = sum(p.est_total_seconds for p in piani) + respiro
                minimo = sum(p.est_best_seconds for p in piani) + respiro
                # Il numero PIU' PROBABILE, non un estremo: la mediana della
                # deduplica e del lavoro non contato. Misurato sulle cinque
                # lavorazioni vere, sbaglia il 3,5% contro il 10,6% del minimo e
                # il 36,1% del massimo — cioè è l'unico dei tre che risponde
                # alla domanda che ci si fa davvero ("quanto ci mette?"). Gli
                # altri due sono i BORDI, costruiti per contenere il vero, e
                # affiancarli tutti e tre voleva una legenda per essere letto.
                atteso = sum(p.est_attesa_seconds for p in piani) + respiro
                # Quanti dei selezionati NON partiranno. Restavano fuori in
                # silenzio: il conteggio diceva "5 file" e ne partivano quattro,
                # e il motivo stava in fondo alla pagina. Ora si dice l'opposto,
                # cioè quanti ne partono: "già fatto o non elaborabile" metteva
                # insieme due condizioni diverse e rubava l'occhio al numero che
                # conta. Il dettaglio scende nel fumetto.
                n_sel, n_fare = len(coda), len(piani)
                # Divisi per CAUSA VERA: "già completato o non elaborabile"
                # metteva insieme due cose che si risolvono in modi opposti —
                # una si sblocca rifacendo il file, l'altra guardando l'errore.
                n_completati = len(conclusi_in_coda) + len(in_forse)
                n_rifiutati = len(rifiutati)
                # Le voci si CONTANO, non si deducono per differenza: un
                # residuo raccoglie tutto quello che non rientra altrove e prima
                # o poi mente. Con una catena spezzata per modello diceva "In
                # lavorazione: 3" mentre ne girava uno solo e gli altri due
                # aspettavano il comando successivo (audit del 2026-08-10).
                n_in_corso = len(in_corso_coda)
                n_attesa = max(0, n_sel - n_fare - n_completati - n_rifiutati
                               - n_in_corso)
                righe_sel = [t("lavb.sel_da_elaborare", n=n_fare)]
                if n_in_corso:
                    righe_sel.append(t("lavb.sel_in_lavorazione", n=n_in_corso))
                if n_attesa:
                    righe_sel.append(t("lavb.sel_in_attesa", n=n_attesa))
                righe_sel += [t("lavb.sel_completati", n=n_completati),
                              t("lavb.sel_rifiutati", n=n_rifiutati)]
                info_sel = _icona_info(t("lavb.file_selezionati"), righe_sel)
                info_stima = _icona_info(
                    t("lavb.durata_stimata"),
                    [t("lavb.piu_probabile", durata=stima_hm(atteso)),
                     t("lavb.durata_possibile", da=stima_hm(minimo),
                       a=stima_hm(totale))],
                    nota=t("lavb.nota_dedup"))
                # Il picco di disco non sta più qui: si legge già nella sidebar,
                # ed è un dato tecnico che rubava spazio alle due cose su cui si
                # decide davvero (quanti file partono, e quanto ci vuole).
                # "N da elaborare" compare SOLO quando è un numero diverso da
                # quelli spuntati: se coincidono non aggiunge niente, e con lui
                # sparisce il suo fumetto — che esiste per spiegare la
                # differenza. Il fumetto della durata invece c'è sempre: la
                # forchetta è un'informazione utile a prescindere.
                a.markdown(
                    f"**{tn('lavb.n_selezionati', n_sel)}**"
                    + (f" · {t('lavb.n_da_elaborare', n=n_fare)}{info_sel}"
                       if n_fare != n_sel else "")
                    + (f" · {t('lavb.stima_barra', durata=stima_hm(atteso))}"
                       f"{info_stima}"
                       if piani else ""), unsafe_allow_html=True)
                # I già lavorati la cui uscita è sparita: annunciati sempre, e
                # con l'azione opposta a portata di clic. Il valore predefinito
                # è quello prudente (non si rifà), perché il costo dei due
                # errori non è lo stesso: dimenticare di rifare un file si
                # scopre subito, rifarne uno già caricato altrove sono ore di
                # GPU buttate che nessuno ferma.
                # Un nome per riga: incolonnati si leggono, in fila separati da un
                # punto si scambiano per un nome solo lunghissimo (i rilasci anime
                # hanno nomi da ottanta caratteri).
                def _nomi(elenco: list[tuple[str, str]]) -> str:
                    brevi = [esc(n) for _, n in elenco[:2]]
                    resto = len(elenco) - 2
                    if resto > 0:
                        brevi.append(tn("lavb.e_altri", resto))
                    return "<br>".join(brevi)

                if in_forse:
                    a.markdown(
                        f"<div class='au-riga-forse'>"
                        f"{tn('lavb.in_forse', len(in_forse), nomi=_nomi(in_forse))}"
                        "</div>",
                        unsafe_allow_html=True)
                # `if`, non `elif`: le due liste convivono benissimo (basta aver
                # armato un file e spuntarne poi un altro archiviato), e con
                # l'elif i file che stavano per essere RIFATTI DA CAPO
                # sparivano dall'avviso pur essendo dentro la coda.
                if rifatti:
                    a.markdown(
                        f"<div class='au-riga-forse'>"
                        f"{tn('lavb.rifatti', len(rifatti), nomi=_nomi(rifatti))}"
                        "</div>",
                        unsafe_allow_html=True)
                # Il perche' dell'Avvia spento si dice a parole, non solo nel
                # fumetto: un pulsante grigio senza motivo sembra un guasto.
                if tarando:
                    a.markdown(f"<div class='au-riga-forse'>"
                               f"{t('lavb.taratura_blocca')}</div>",
                               unsafe_allow_html=True)
                # La didascalia diceva a parole proprio quello che ora l'estremo
                # basso calcola: descriveva un valore che non veniva mostrato.
                a.markdown(f"<span class='au-meta'>{t('lavb.tempo_minimo')} "
                           f"{_nota_taratura()}</span>",
                           unsafe_allow_html=True)
                # Un pulsante solo: i dettagli ora vivono dentro le righe, come
                # nei Sorgenti, e non serve più un interruttore globale.
                with azioni:
                    # Le tre azioni della fascia hanno la stessa larghezza: la
                    # colonna intera. Sono alternative fra loro, e larghezze
                    # diverse le facevano leggere come importanze diverse.
                    if st.button(t("lavb.avvia"), type="primary",
                                 use_container_width=True,
                                 disabled=not piani or gpu_occupata or tarando,
                                 help=(t("lavb.taratura_blocca") if tarando
                                       else None)):
                        # Il consenso a rifare si CONSUMA col lancio — ma solo
                        # se il lancio c'è stato davvero. `_avvia` esce presto
                        # se manca il lanciatore o se la shell muore subito:
                        # consumarlo lo stesso lasciava l'utente senza lancio,
                        # senza messaggio (lo cancella il rilancio della pagina)
                        # e coi file tornati in "per ora vengono saltati".
                        # Restando invece acceso a lancio riuscito, la volta dopo
                        # — archiviata di nuovo l'uscita appena prodotta, che è
                        # il gesto normale — il file sarebbe rientrato in coda
                        # senza passare per la conferma che serve a imporre.
                        if _avvia(piani, cfg):
                            st.session_state["rifai_comunque"] = set()
                            st.session_state["attesa_avvio"] = time.time()
                            # IL GIRO COMPLETO SI CHIEDE QUI, non con la
                            # bandierina `appena_avviata`.
                            #
                            # Questo pulsante vive DENTRO `_fascia_viva`, che
                            # e' un fragment: un click qui riesegue soltanto
                            # il fragment, e il rimedio in fondo al corpo
                            # (`pop("appena_avviata")` -> rerun) non viene
                            # raggiunto mai. Senza giro principale `armato`
                            # resta falso, il fragment nasce con
                            # `run_every=None` e nessuno guarda piu' il disco:
                            # la pagina resta allo stato PRE-lancio per tutta
                            # la lavorazione, col riquadro verde ancora a
                            # schermo perche' non c'e' stato alcun giro a
                            # cancellarlo. E' il difetto della voce 83,
                            # riprodotto in banco di prova il 12/08.
                            #
                            # `st.rerun()` da dentro un fragment ha scope
                            # "app" (predefinito in Streamlit 1.61.1) e
                            # rilancia lo script intero: `armato` si ricalcola
                            # sul cuscinetto `attesa_avvio` appena scritto,
                            # il fragment rinasce con `run_every="5s"` e vede
                            # comparire il lucchetto quando l'analisi finisce.
                            #
                            # Niente `appena_avviata`: qui il giro si e' gia'
                            # ottenuto, e lasciarla accesa ne farebbe scattare
                            # un secondo, con in mezzo un `sleep(1.5)` che
                            # aspetta un lucchetto lontano quarantotto secondi.
                            # La bandierina resta per l'Avvia della singola
                            # riga, che sta nel corpo principale e il rimedio
                            # lo raggiunge davvero.
                            st.rerun()
                    # Le azioni opposte stanno accanto alla riga che le spiega,
                    # non in un menu altrove: si decide dove si legge. Ed
                    # esistono TUTT'E DUE insieme quando entrambe le liste sono
                    # piene, o per disarmare un file bisognerebbe prima armarne
                    # un altro.
                    if in_forse and not gpu_occupata:
                        if st.button(tn("lavb.rifai_si", len(in_forse)),
                                     key="rifai_si",
                                     use_container_width=True):
                            rifai_comunque.update(k for k, _ in in_forse)
                            st.rerun()
                    if rifatti and not gpu_occupata:
                        if st.button(tn("lavb.rifai_no", len(rifatti)),
                                     key="rifai_no",
                                     use_container_width=True):
                            rifai_comunque.difference_update(k for k, _ in rifatti)
                            st.rerun()

            # Ferma tutto: vive nella barra perché il suo raggio È globale —
            # il Ferma della riga ferma quel file, questo ferma il file in corso
            # E annulla i successivi del lancio. Fuori dall'if della selezione:
            # deve esserci anche quando nessun file è spuntato. Il PID arriva
            # dal lucchetto, dal marcatore di pausa O da quello di catena: così
            # il freno esiste anche nel limbo dell'estrazione appena nata.
            if gpu_occupata:
                vivo_ora = next((l for l in lavori_tutti if l.vivo), None)
                if (vivo_ora is not None or pausa_ora is not None
                        or catena_ora is not None):
                    armato_tutto = st.session_state.get("conferma_ferma_tutto")
                    in_conferma_tutto = (isinstance(armato_tutto, float)
                                         and time.time() - armato_tutto < 10)
                    # Tutti e due nella STESSA colonna: a metterli in due
                    # sotto-colonne ognuno riempiva la sua meta' e uscivano
                    # due pulsanti larghissimi (detto dall'utente). In fila li
                    # mette il CSS, che li tiene stretti e a filo destro.
                    with azioni:
                        # PAUSA, qui e non sulla riga. «Ferma» sta sulla riga
                        # perché ha un senso per QUEL file: ferma questo, gli
                        # altri proseguono. La pausa quel senso non ce l'ha —
                        # si lavora un file alla volta, quindi mettere in
                        # pausa «quel» file è sempre mettere in pausa la
                        # macchina, ed è la macchina che si vuole liberare.
                        # E c'è un motivo pratico che chiude la questione: nei
                        # momenti in cui serve di più la riga non c'è. Durante
                        # la pausa fra un file e l'altro, o durante l'analisi
                        # di un lotto, non esiste nessuna riga «in corso» —
                        # ma la macchina è impegnata lo stesso.
                        # (Decisione presa con l'utente l'11/08.)
                        if vivo_ora is not None:
                            if monitor.sospeso(vivo_ora) is not None:
                                if st.button(t("lavb.riprendi"), key="riprendi_tutto",
                                             type="primary",
                                             use_container_width=True,
                                             help=t("lavb.riprendi_tutto_aiuto")):
                                    if (err := _pausa(vivo_ora, riprendi=True)):
                                        st.toast(t("lavb.non_riprende", errore=err))
                                    else:
                                        st.toast(t("lavb.ripreso"))
                                    time.sleep(1.0)
                                    st.rerun()
                            elif st.button(t("lavb.pausa"), key="pausa_tutto",
                                           use_container_width=True,
                                           help=t("lavb.pausa_aiuto")):
                                if (err := _pausa(vivo_ora, riprendi=False)):
                                    st.toast(t("lavb.pausa_errore", errore=err))
                                else:
                                    st.toast(t("lavb.in_pausa"))
                                time.sleep(1.0)
                                st.rerun()
                        if not in_conferma_tutto:
                            if st.button(t("lavb.ferma_tutto"), key="ferma_tutto",
                                         use_container_width=True,
                                         help=t("lavb.ferma_tutto_aiuto")):
                                st.session_state["conferma_ferma_tutto"] = time.time()
                                st.rerun()
                        else:
                            if st.button(t("lavb.conferma_ferma_tutto"),
                                         key="fermasi_tutto",
                                         use_container_width=True):
                                st.session_state.pop("conferma_ferma_tutto", None)
                                if vivo_ora is not None:
                                    _ferma(vivo_ora, tutto=True)
                                elif pausa_ora is not None:
                                    # Catena in pausa: niente lucchetto, ma il
                                    # marcatore porta il PID della CLI dormiente.
                                    _termina_gruppo(pausa_ora[1])
                                else:
                                    # Limbo dell'estrazione: c'e' solo .catena.
                                    _termina_gruppo(int(catena_ora.get("pid", 0)))
                                st.toast(t("lavb.lancio_interrotto"))
                                time.sleep(1.5)
                                st.rerun()


    _fascia_viva()

    # Riarmo dell'auto-aggiornamento: il ritmo del fragment è deciso dal run
    # PRINCIPALE, quindi quando lo stato vivo/fermo cambia serve un giro
    # completo. Dopo un avvio si aspetta un attimo che il lucchetto compaia.
    if st.session_state.pop("appena_avviata", False):
        time.sleep(1.5)
        st.rerun()
    # STESSA definizione di `armato` in page_lavorazione, o il confronto
    # resta in disaccordo per tutta una pausa e piove un rerun completo ogni
    # 5 secondi (misurato: è così che la lista si duplicava a schermo).
    occupato_ora = (any(l.vivo for l in lavori_tutti)
                    or monitor.pausa() is not None
                    or monitor.catena() is not None
                    or time.time() - st.session_state.get("attesa_avvio", 0) < 180
                    # DEVE combaciare con `armato` (vedi page_lavorazione):
                    # se uno dei due conta l'analisi e l'altro no, il
                    # confronto qui sotto non torna mai e la pagina si
                    # rilancia in continuazione invece che ogni 5 secondi.
                    or analizzatore().al_lavoro)
    # Il vero stato di occupazione, SENZA la finestra post-avvio: è il
    # metro con cui la sidebar decide il congelamento, e va confrontato a
    # parte — durante l'attesa-avvio `armato` era già vero e il primo
    # confronto taceva proprio mentre la catena nasceva.
    catena_vera = (any(l.vivo for l in lavori_tutti)
                   or monitor.pausa() is not None
                   or monitor.catena() is not None)
    scaduta = st.session_state.get("conferma_spegni")
    if isinstance(scaduta, float) and time.time() - scaduta >= 10:
        # La conferma di spegnimento è scaduta ma la sidebar (fuori dal
        # fragment) non può accorgersene da sola: si disarma qui e si
        # ridisegna tutto. Senza, restava "Confermi? Chiudi" per sempre.
        st.session_state.pop("conferma_spegni", None)
        st.rerun()
    if (occupato_ora != armato
            or catena_vera != st.session_state.get("sidebar_congelata")):
        st.rerun()



def _dettagli_piano(plan, errore, esito=None) -> None:
    """Il piano di UN file, con l'impaginazione dei dettagli dei Sorgenti.

    Stessi gruppi con titolo e hairline, stessa griglia etichetta-sopra e
    valore-sotto: chi ha imparato a leggere un pannello lì non deve
    impararne un altro qui. Se il piano non esiste, il pannello dice il
    motivo per esteso invece dei dettagli. Per un file già COMPLETATO,
    `esito` (la pagella di registri/esiti.jsonl) aggiunge in fondo le
    statistiche vere: inizio, fine, durata, deduplica, velocità, esito.
    """
    if plan is None and errore is None:
        # Caso nuovo (2026-08-10): il file non e' ancora stato analizzato,
        # quindi un piano non esiste ANCORA — e non e' un errore. Prima
        # questa combinazione non poteva darsi e il codice sotto andava
        # dritto su `plan.model`, facendo esplodere l'intera scheda.
        st.markdown("<div class='au-hint' style='margin-top:0'>"
                    f"{t('lav.det_analisi')}</div>", unsafe_allow_html=True)
        return
    if errore is not None:
        st.markdown(f"<div class='au-avviso' style='margin-top:0'>"
                    f"<span class='au-icona'>&#9888;</span>{esc(str(errore))}"
                    "</div>", unsafe_allow_html=True)
        return
    gruppi = [
        (t("lav.det_lavorazione"), [
            (t("lav.det_modello"), plan.model.label),
            (t("lav.det_catena"),
             t("lav.det_catena_valore", modello=plan.model_name,
               rapporto=f"{plan.downscale:.2f}")),
            (t("lav.det_uscita"), f"{plan.target_width}×{plan.target_height}"),
            (t("lav.det_blocchi"),
             tn("lav.det_blocchi_valore", plan.chunks, dim=plan.chunk_size)),
        ]),
        (t("lav.det_codifica"), [
            ("Codec", f"{plan.encoding.codec} {plan.encoding.pix_fmt}"),
            ("CRF", str(plan.encoding.crf)),
            ("Preset", plan.encoding.preset),
            (t("lav.det_restauro"),
             ", ".join(plan.restoration.chain()) or t("lav.det_nessuno")),
        ]),
    ]
    pezzi = []
    for titolo, voci in gruppi:
        celle = "".join(
            f"<div class='au-voce'><span class='au-etichetta'>{esc(k)}</span>"
            f"<span class='au-valore'>{esc(v)}</span></div>" for k, v in voci)
        pezzi.append(f"<div class='au-blocco'><div class='au-gtitolo'>{titolo}"
                     f"</div><div class='au-griglia'>{celle}</div></div>")
    pezzi.append(
        "<div class='au-blocco'><div class='au-gtitolo'>"
        f"{t('lav.det_file_finale')}</div>"
        "<div class='au-valore' style='overflow-wrap:anywhere'>"
        f"{esc(plan.output.name)}</div></div>")

    for w in plan.warnings:
        pezzi.append(f"<div class='au-avviso'><span class='au-icona'>&#9888;"
                     f"</span>{esc(w)}</div>")

    # La pagella del lavoro concluso: numeri VERI, non stime. Sta in fondo,
    # sotto il nome del file finale (posizione chiesta dall'utente). NON è
    # nella griglia HTML come gli altri gruppi: l'ultima cella è il pulsante
    # "Apri nel Finder", che è un widget e in mezzo all'HTML non può stare
    # — su una sua riga andava a capo da solo e sembrava un orfano (visto
    # dall'utente). Colonne native con le stesse classi = stesso aspetto.
    if esito and esito.get("secondi"):
        pezzi.append("<div class='au-blocco' style='margin-bottom:0'>"
                     f"<div class='au-gtitolo'>{t('lav.det_conclusa')}</div></div>")
        st.markdown("".join(pezzi), unsafe_allow_html=True)

        secondi = float(esito["secondi"])
        fine = float(esito.get("quando") or 0)
        inizio = fine - secondi if fine else 0
        avvisi = esito.get("avvisi") or []
        if avvisi:
            chip_esito = (f"<span class='au-tag au-warn'>"
                          f"{tn('lav.det_avvisi', len(avvisi))}</span>")
        else:
            chip_esito = f"<span class='au-tag au-ok'>{t('lav.det_tutto_ok')}</span>"
        voci = [(t("lav.det_esito"), chip_esito)]
        giorno_ora = t("lav.fmt_giorno_ora")
        if inizio:
            voci.append((t("lav.det_inizio"), time.strftime(
                giorno_ora, time.localtime(inizio))))
        if fine:
            voci.append((t("lav.det_fine"), time.strftime(
                giorno_ora, time.localtime(fine))))
        voci.append((t("lav.det_durata"), stima_hm(secondi)))
        if esito.get("dedup"):
            voci.append((t("lav.det_dedup"), f"{float(esito['dedup']):.0%}"))
        if esito.get("fotogrammi"):
            voci.append((t("lav.det_velocita"),
                         f"{esito['fotogrammi'] / secondi:.1f} fps"))
        try:
            peso = (PATHS.output / esito["output"]).stat().st_size / 1048576
            voci.append((t("lav.det_peso"), f"{peso:.0f} MB"))
        except (OSError, KeyError, TypeError):
            pass

        # Due file di quattro celle; l'ottava è il pulsante. Il contenitore
        # con chiave serve al CSS per DISFARE le regole della testata (la
        # colonna-casella fissa a 32px strozzava la cella "Esito" a lettere
        # in verticale, misurato a occhio dall'utente prima che da me).
        righe_voci = [voci[n:n + 4] for n in range(0, len(voci), 4)]
        # "Cartella" e' l'ULTIMA voce e sta subito dopo le altre, nella
        # prima cella libera: una riga tutta sua la staccava dal gruppo.
        # (Quello che la faceva sembrare fuori posto era l'allineamento a
        # destra, corretto nel CSS, non la posizione.) Se la riga e' piena
        # se ne apre una nuova.
        if not righe_voci or len(righe_voci[-1]) >= 4:
            righe_voci.append([])
        with st.container(key=f"pagella_{plan.output.name}"):
            for indice_r, gruppo_voci in enumerate(righe_voci):
                cols = st.columns(4)
                for col, (titolo, valore) in zip(cols, gruppo_voci):
                    col.markdown(
                        f"<div class='au-voce'><span class='au-etichetta'>"
                        f"{titolo}</span><span class='au-valore'>{valore}"
                        f"</span></div>", unsafe_allow_html=True)
                if indice_r == len(righe_voci) - 1 and esito.get("output"):
                    cella = cols[len(gruppo_voci)]
                    cella.markdown("<div class='au-voce'><span class="
                                   f"'au-etichetta'>{t('lav.det_cartella')}"
                                   "</span></div>",
                                   unsafe_allow_html=True)
                    # `open -R` rivela il FILE nella cartella d'uscita: il
                    # server gira sullo stesso Mac dell'utente, è legittimo.
                    if cella.button(t("lav.det_finder",
                                      cartella=PATHS.output.name),
                                    key=f"finder_{plan.output.name}"):
                        subprocess.run(
                            ["open", "-R",
                             str(PATHS.output / esito["output"])],
                            check=False)
        for a in avvisi:
            st.markdown(f"<div class='au-avviso'><span class='au-icona'>"
                        f"&#9888;</span>{esc(str(a))}</div>",
                        unsafe_allow_html=True)
    else:
        st.markdown("".join(pezzi), unsafe_allow_html=True)


def _riprendi(piano, cartella: Path | None, cfg: dict) -> bool:
    """Riprendi BLINDATO: usa i parametri scritti nella cartella di
    lavorazione (parametri.json, li scrive la CLI a ogni lancio), ignorando
    la sidebar del momento — così riprendere non può mai buttare il lavoro
    fatto. Rifare con parametri nuovi = Scarta + rilancio, per scelta.
    Senza ricetta (lavorazioni di versioni vecchie) si ricade sulla sidebar,
    come è sempre stato."""
    ricetta = _leggi_parametri(cartella)
    if not ricetta:
        return _avvia([piano], cfg)
    unione = {**cfg, **{k: ricetta[k] for k in
                        ("altezza", "crf", "preset", "disco",
                         "dedup", "denoise", "forza") if k in ricetta}}
    return _avvia([piano], unione, modello=ricetta.get("modello"))


def _avvia(piani, cfg: dict, modello: str | None = None) -> bool:
    """Lancia la lavorazione: gruppi diversi UNO DOPO L'ALTRO, mai insieme.

    La CLI accetta un solo `--modello` per invocazione mentre qui la scelta è
    per file: si raggruppa. Prima il modello non veniva passato affatto e il
    processo ricadeva sul consigliato, producendo un file diverso da quello
    annunciato a schermo.

    I gruppi vanno in SEQUENZA, non in parallelo. Lanciandoli insieme ognuno
    interrogava lo spazio libero per conto proprio e vedeva tutto il disco:
    due lotti da 16 GB di PNG passavano entrambi la guardia su 32 GB liberi e
    riempivano il volume a metà lavorazione. In più si contendevano la stessa
    GPU, rendendo prive di senso sia le stime a schermo sia i tempi reali.

    Si usa una sola shell con i comandi separati da `;` (non `&&`): un gruppo
    che fallisce non deve impedire al successivo di partire.
    """
    # Mai insieme a una taratura: si dividerebbero la GPU, e la taratura
    # salverebbe numeri falsi su cui poi poggiano tutte le stime. La guardia
    # sta QUI e non solo sui pulsanti: Avvia, Riprendi e qualunque via futura
    # passano da questa funzione, e un pulsante disegnato un attimo prima che
    # la taratura partisse (un'altra scheda del browser) resterebbe attivo.
    # Il blocco opposto, la taratura rifiutata durante una lavorazione, sta
    # nella sua modale.
    if taratura.in_corso():
        st.error(t("lav.avvia_taratura"), icon="⚠️")
        return False
    registro = PATHS.registro_coda
    registro.parent.mkdir(parents=True, exist_ok=True)

    per_modello: dict[str, list] = {}
    for piano in piani:
        # `modello` (dal Riprendi blindato) vince sulla tendina della riga:
        # la ripresa deve rilanciare col modello con cui era partita.
        per_modello.setdefault(modello or piano.model_key, []).append(piano)

    comandi: list[str] = []
    # Il "file N di M" della barra deve contare TUTTA la catena, non il
    # singolo gruppo: ogni comando riceve il totale e quanti file lo
    # precedono, così il conteggio non riparte da 1 a ogni cambio modello.
    totale_catena = sum(len(g) for g in per_modello.values())
    precedenti = 0
    # Un'etichetta sola per tutto il lancio: e' cio' che permette al
    # resoconto di rimettere insieme i pezzi quando la coda viene spezzata
    # in un comando per modello. Senza, ogni comando raccontava solo se
    # stesso e l'ultimo si spacciava per l'intera maratona.
    etichetta_lancio = f"{int(time.time())}-{os.getpid()}"
    for modello, gruppo in per_modello.items():
        comando = [str(CODICE / "animeup"), "run", "--si",
                   "--lancio", etichetta_lancio,
                   "--altezza", str(cfg["altezza"]), "--crf", str(cfg["crf"]),
                   "--preset", cfg["preset"], "--modello", modello,
                   "--disco", str(cfg["disco"])]
        if not cfg["dedup"]:
            comando.append("--no-dedup")
        if cfg.get("pausa"):
            comando += ["--pausa", str(cfg["pausa"])]
            # I gruppi dopo il primo riposano anche PRIMA di partire: sono
            # la continuazione della stessa maratona, non un lancio nuovo.
            if comandi:
                comando.append("--pausa-prima")
        if len(per_modello) > 1:
            comando += ["--catena-totale", str(totale_catena),
                        "--catena-inizio", str(precedenti)]
        precedenti += len(gruppo)
        if cfg["denoise"]:
            comando.append("--denoise")
        if cfg["forza"]:
            comando.append("--forza")
        comando += [str(x.source.path) for x in gruppo]
        comandi.append(" ".join(shlex.quote(a) for a in comando))

    lanciatore = CODICE / "animeup"
    if not lanciatore.is_file():
        st.error(t("lav.avvia_no_lanciatore", percorso=lanciatore), icon="⚠️")
        return False
    with registro.open("a") as fh:
        proc = subprocess.Popen(["/bin/sh", "-c", "; ".join(comandi)],
                                stdout=fh, stderr=fh, start_new_session=True)
    # Un attimo per intercettare il fallimento immediato: annunciare "Avviata"
    # mentre la shell risponde 127 è peggio che non annunciare nulla.
    time.sleep(0.6)
    if proc.poll() not in (None, 0):
        st.error(t("lav.avvia_fallito", codice=proc.poll(), registro=registro),
                 icon="⚠️")
        return False

    quanti = " + ".join(t("lav.avvia_gruppo", n=len(g), modello=CATALOG[m].short)
                        for m, g in per_modello.items())
    coda = f" ({t('lav.avvia_sequenza')})" if len(per_modello) > 1 else ""
    st.success(t("lav.avviata", quanti=quanti, coda=coda, registro=registro))
    return True


def _spegni_interfaccia(lavori_in_corso: bool) -> None:
    """Spegne il server di Streamlit da dentro, con garbo.

    Prima si disegna il commiato (il server morto non può più dire
    niente), poi un thread manda SIGTERM a NOI STESSI dopo un secondo:
    Streamlit chiude pulito e la finestra del Terminale mostra "processo
    completato" — da lì in poi si può chiudere tutto senza rimorsi.
    Le lavorazioni, processi separati, non se ne accorgono nemmeno.
    """
    import signal as segnali
    import threading as fili

    st.markdown(
        "<div style='text-align:center; padding:80px 0'>"
        f"<div style='font-size:22px; font-weight:600'>{t('lav.spento')}</div>"
        "<div class='au-hint' style='margin-top:12px'>"
        f"{t('lav.spento_chiudi')}"
        + (f" {t('lav.spento_lavori')}" if lavori_in_corso else "")
        + "</div></div>", unsafe_allow_html=True)

    def _poi() -> None:
        time.sleep(1.0)
        os.kill(os.getpid(), segnali.SIGTERM)

    fili.Thread(target=_poi, daemon=True).start()
    st.stop()


def _ferma(lav, *, tutto: bool) -> None:
    """Interrompe la lavorazione in corso, in uno di due modi.

    `tutto=False` (il Ferma della riga): SIGUSR1 alla CLI, che abbatte
    l'upscaler, interrompe SOLO il file in corso (riprendibile) e prosegue
    con i successivi del lancio. Il pulsante sta sulla riga di un file, e
    deve fare quello che sembra: fermare quel file.

    `tutto=True` (il Ferma tutto della barra): SIGTERM al GRUPPO. Al gruppo
    e non al solo processo: un lancio con più file è una catena `cmd; cmd`
    in una shell, e fermando solo il processo corrente la shell farebbe
    partire il comando successivo — "Ferma tutto" che fa ripartire qualcosa
    è un tradimento. Il file in corso resta riprendibile, i successivi non
    partono.

    Prima di sparare si verifica che il comando del PID sia davvero AnimeUp:
    dopo un crash il numero può essere stato riciclato da un processo
    innocente, e il monitor non può accorgersene.
    """
    lock = lav.cartella / "running.lock"
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        return
    if not _e_processo_nostro(pid):
        return
    if tutto:
        _termina_gruppo(pid)
        return
    try:
        os.kill(pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _operai_sotto(pid_cli: int) -> list[int]:
    """I processi che stanno facendo il lavoro vero sotto questa CLI.

    Si scende tutto l'albero e non solo i figli diretti: fra la CLI e
    l'upscaler puo' esserci una shell, e congelare la shell lascerebbe
    l'upscaler a macinare — cioe' una pausa che non mette in pausa.
    """
    try:
        esito = subprocess.run(["ps", "-eo", "pid=,ppid=,command="],
                               capture_output=True, text=True, check=False)
    except OSError:
        return []
    figli: dict[int, list[int]] = {}
    comando: dict[int, str] = {}
    for riga in esito.stdout.splitlines():
        parti = riga.split(None, 2)
        if len(parti) < 3:
            continue
        try:
            p, pp = int(parti[0]), int(parti[1])
        except ValueError:
            continue
        figli.setdefault(pp, []).append(p)
        comando[p] = parti[2]
    operai, coda = [], [pid_cli]
    while coda:
        n = coda.pop()
        for f in figli.get(n, []):
            coda.append(f)
            c = comando.get(f, "")
            if any(x in c for x in ("realcugan", "realesrgan", "ffmpeg")):
                operai.append(f)
    return operai


def _pausa(lav, *, riprendi: bool) -> str:
    """Congela o risveglia i processi al lavoro. Restituisce un errore o "".

    Il meccanismo e' `SIGSTOP`/`SIGCONT` sui processi operai, non sulla CLI:
    la CLI deve restare viva ad aspettarli, altrimenti al risveglio non c'e'
    piu' nessuno a raccogliere il risultato.

    Provato l'11/08 su tutte e due le fasi, con verifica byte per byte dei
    PNG e decodifica integrale del video prodotto: non si perde niente,
    perche' upscaler e codificatore scrivono un pezzo alla volta e fra un
    pezzo e l'altro non hanno nulla di aperto.
    """
    from animeup.pipeline import SOSPESO, PAUSE_TOTALI

    lock = lav.cartella / "running.lock"
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        return t("lav.pausa_senza_processo")
    if not _e_processo_nostro(pid):
        return t("lav.pausa_non_risponde")

    marcatore = lav.cartella / SOSPESO
    if riprendi:
        # Prima si risveglia, poi si toglie il marcatore: se qualcosa va
        # storto in mezzo, resta il segno di cosa c'e' da risvegliare.
        try:
            dati = su_disco.loads(marcatore.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            dati = {}
        for p in dati.get("pids") or _operai_sotto(pid):
            try:
                os.kill(int(p), signal.SIGCONT)
            except (ProcessLookupError, PermissionError, OSError, ValueError):
                pass
        durata = max(0.0, time.time() - float(dati.get("da") or time.time()))
        conta = lav.cartella / PAUSE_TOTALI
        try:
            prima = float(conta.read_text().strip() or 0)
        except (OSError, ValueError):
            prima = 0.0
        try:
            conta.write_text(f"{prima + durata:.1f}")
        except OSError:
            pass
        marcatore.unlink(missing_ok=True)
        # La finestra del ritmo riparte da zero, come si fa a ogni cambio di
        # fase: i punti di prima della pausa sono validi ma vecchi, e mediarli
        # con quelli nuovi darebbe per minuti un ritmo che non e' ne' quello
        # di prima ne' quello di adesso.
        st.session_state.get("mon_campioni", {}).pop(lav.cartella.name, None)
        st.session_state.get("mon_stati", {}).pop(lav.cartella.name, None)
        return ""

    operai = _operai_sotto(pid)
    if not operai:
        return t("lav.pausa_niente")
    # Il marcatore PRIMA del segnale: se l'interfaccia morisse fra le due
    # cose, meglio un marcatore senza pausa (si vede e si toglie) che dei
    # processi congelati senza nessuno che sappia quali sono.
    try:
        marcatore.write_text(su_disco.dumps({"da": time.time(), "pids": operai}))
    except OSError:
        return t("lav.pausa_marcatore")
    for p in operai:
        try:
            os.kill(p, signal.SIGSTOP)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return ""


def _e_processo_nostro(pid: int) -> bool:
    """Il PID è davvero una CLI di AnimeUp? Contro i numeri riciclati."""
    try:
        esito = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                               capture_output=True, text=True, check=False)
    except OSError:
        return False
    return "animeup" in esito.stdout or "python" in esito.stdout


def _termina_gruppo(pid: int) -> None:
    """SIGTERM al gruppo del PID: ferma la catena intera, tutto riprendibile."""
    if not _e_processo_nostro(pid):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


# ===========================================================================

@st.cache_resource
def _preparazione() -> primo_avvio.Preparazione:
    """Una sola preparazione per server: sopravvive ai giri della pagina."""
    return primo_avvio.Preparazione()


def _pagina_primo_avvio() -> bool:
    """Al primo avvio mancano FFmpeg e i motori: si scaricano da qui.

    Ritorna True se ha disegnato la pagina (e il resto dell'app va saltato).
    Prima la preparazione si faceva solo nel Terminale, che l'app per macOS
    non mostra.
    """
    # Il controllo esegue ffmpeg per leggerne la versione: una volta per
    # sessione basta, la Lavorazione rifa' il giro ogni cinque secondi.
    if st.session_state.get("preparato"):
        return False
    lavoro = _preparazione()
    if not lavoro.in_corso and not lavoro.errore and not primo_avvio.serve():
        st.session_state["preparato"] = True
        return False
    st.markdown(f"<div class='au-sezione' style='margin-top:24px'>{t('pa.titolo')}</div>"
                f"<div class='au-hint' style='margin-bottom:16px'>{t('pa.intro')}</div>",
                unsafe_allow_html=True)
    mancano = primo_avvio.da_scaricare()
    voci = []
    if mancano["ffmpeg"]:
        voci.append(t("pa.voce_ffmpeg"))
    if mancano["ncnn"]:
        voci.append(t("pa.voce_ncnn"))
    if voci:
        st.markdown("\n".join(f"- {v}" for v in voci))
        st.caption(t("pa.nota", mb=primo_avvio.peso_mb()))
    if lavoro.in_corso:
        with st.spinner(t("pa.in_corso")):
            righe = lavoro.righe.righe[-4:]
            if righe:
                st.code("\n".join(righe), language=None)
            time.sleep(1.0)
        st.rerun()
    if lavoro.errore:
        st.error(t("pa.errore"))
        st.code(lavoro.errore, language=None)
        if st.button(t("pa.riprova"), type="primary", key="paRiprova"):
            lavoro.avvia()
            st.rerun()
        return True
    if lavoro.finita and not primo_avvio.serve():
        return False
    if st.button(t("pa.scarica", mb=primo_avvio.peso_mb()), type="primary",
                 key="paScarica"):
        lavoro.avvia()
        st.rerun()
    return True


def main() -> None:
    try:
        PATHS.ensure_dirs()
    except OSError:
        pass
    # La lingua si decide PRIMA di disegnare: l'intestazione viene prima
    # della sidebar, che e' dove la lingua si sceglie. Cambiandola, il
    # widget scrive la sessione e Streamlit rifa' il giro: qui la si trova.
    i18n.imposta(st.session_state.get("w_lingua")
                 or _impostazioni_carica()["lingua"])
    if _pagina_primo_avvio():
        return
    sezione = header()
    # L'analisi si accoda QUI e non dentro Sorgenti: la scheda aperta
    # sopravvive nell'URL, quindi aprendo l'app direttamente su Lavorazione
    # nessuno accodava niente e le righe restavano ferme su "in attesa di
    # analisi" per sempre — con la banda che prometteva il contrario.
    try:
        analizzatore().accoda([Path(f["path"]) for f in load_library()],
                              approfondita=_impostazioni_carica().get(
                                  "approfondita", True))
    except (OSError, KeyError, TypeError):
        pass
    cfg = sidebar()
    # Il resoconto di fine coda, se ce n'e' uno da mostrare. Qui e non dentro
    # Lavorazione: la coda puo' finire con l'utente su un'altra scheda, o con
    # l'app chiusa, e il resoconto non deve dipendere da dove si trovava.
    # Non durante una lavorazione nuova: una modale che si apre mentre si
    # guarda una barra e' un ostacolo, non un'informazione.
    # Streamlit non sa dire quando una modale viene chiusa con la X, con ESC
    # o cliccando fuori: non c'e' nessun richiamo. Quindi tutto cio' che il
    # resoconto DEVE fare — segnare il lancio come visto e svuotare la
    # selezione — si fa nel momento in cui la finestra si apre, non quando si
    # chiude. Cosi' nessun modo di chiuderla puo' farlo perdere (prima con la
    # X non succedeva niente: la lista restava tutta spuntata e la modale
    # tornava al ricarico successivo).
    _lancio = _lancio_da_mostrare()
    # Il segno vive su disco per sopravvivere ai riavvii, ma se `registri/`
    # non fosse scrivibile resterebbe non-visto per sempre: la modale si
    # riaprirebbe a ogni giro, la selezione si svuoterebbe di continuo e i
    # palloncini ripartirebbero a ogni clic. Il doppione in sessione e' il
    # paracadute (audit del 2026-08-10, quinto giro).
    if _lancio is not None and monitor.catena() is None \
            and st.session_state.get("fine_vista") != _lancio.get("fine"):
        # Lo svuotamento della selezione si fa QUI, all'apertura: e' l'unica
        # cosa che non deve dipendere da come la finestra viene chiusa.
        # Il segno "visto" invece si scrive alla CHIUSURA (vedi `_chiudi`),
        # e puo' farlo perche' la finestra resta richiamata finche' non si
        # preme un pulsante: la X non e' piu' un buco. Cosi' si recuperano
        # due casi che scrivendolo all'apertura restavano aperti — una
        # seconda scheda che consuma il resoconto senza mostrarlo a nessuno,
        # e un crash del browser prima che sia stato letto.
        st.session_state["fine_vista"] = _lancio.get("fine")
        _svuota_selezione()
        st.session_state["fine_da_mostrare"] = _lancio
        st.session_state["fine_festeggiata"] = False
    # Una coda nuova cancella il resoconto della precedente: restare aperta
    # sopra una lavorazione in corso e' l'ostacolo che si voleva evitare.
    if monitor.catena() is not None:
        st.session_state["fine_da_mostrare"] = None
    # Finche' resta qui dentro la modale viene richiamata a ogni giro, e cosi'
    # resta aperta: senza, un rilancio della pagina — il riquadro della
    # Lavorazione ne forza uno ogni cinque secondi — la faceva sparire da
    # sola a meta' lettura. Si svuota solo coi suoi due pulsanti: e' un
    # resoconto, e va chiuso apposta.
    if st.session_state.get("fine_da_mostrare"):
        _modale_fine_coda(st.session_state["fine_da_mostrare"])
    # Entrando in Lavorazione con un file in corso, la lista scorre da sola
    # fino alla riga attiva: era a metà elenco e "devo capire che se scrollo
    # trovo qualcosa in corso" (detto dall'utente). Il segnale si arma al
    # CAMBIO di scheda (o al primo carico) e si consuma dopo lo scroll.
    if (sezione == SEZIONI[2]
            and st.session_state.get("sezione_prec") != SEZIONI[2]):
        st.session_state["scroll_al_lavoro"] = True
    st.session_state["sezione_prec"] = sezione
    if sezione == SEZIONI[0]:
        page_sorgenti(cfg)
    elif sezione == SEZIONI[1]:
        page_confronto(cfg)
    else:
        page_lavorazione(cfg)


main()
