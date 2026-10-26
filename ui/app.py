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
import hashlib
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

from animeup import __version__, su_disco, tema  # noqa: E402
from animeup import (  # noqa: E402
    aggiornamenti, confronto, i18n, library, monitor, preview, primo_avvio,
    taratura)
from animeup.i18n import attiva as lingua_attiva, t, tn  # noqa: E402
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
    # Il grassetto dei testi tradotti (<b>…</b>) si rende: escapato, il
    # fumetto mostrava i tag come lettere (segnalato dall'utente).
    sicuro = esc(testo).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return (f"<span class='au-bolla'><span class='au-bolla-riga'>"
            f"{sicuro}</span></span>")


def _percorso(percorso: str | Path, classe: str) -> str:
    """Il percorso di una cartella, tagliato coi puntini se non ci sta, con
    sopra il fumetto che lo mostra intero. Il fumetto si apre solo quando il
    taglio c'e' davvero: lo decide lo script della pagina al passaggio
    (classe `au-tronco`), perche' dal CSS non si sa se un testo trabocca."""
    testo = esc(_breve(percorso))
    return (f"<span class='au-perc'><code class='{classe}'>{testo}</code>"
            f"<span class='au-bolla'><span class='au-bolla-riga'>{testo}</span></span></span>")


def _icona_aiuto(testo: str, predefinito: str = "", ripristina: str | None = None) -> str:
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

    Con `ripristina` (la chiave dell'impostazione, solo se e' stata cambiata)
    il valore di fabbrica diventa un link che lo rimette: chiesto
    dall'utente. Il clic lo raccoglie lo script della pagina madre (vedi
    `_cassetto_sidebar`) e lo gira al pulsante nascosto `ripr_<chiave>`.
    """
    nota = esc(t('comune.predefinito', valore=predefinito))
    if predefinito and ripristina:
        coda = (f"<a class='au-bolla-nota au-ripristina' role='button' "
                f"data-ripristina='{esc(ripristina)}'>{nota}</a>")
    else:
        coda = f"<span class='au-bolla-nota'>{nota}</span>" if predefinito else ""
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
                  predefinito: str = "", dove=None, ripristina: str | None = None) -> None:
    """L'etichetta di un controllo della sidebar, disegnata da noi.

    Con l'etichetta nativa il valore andava messo in un `content` di CSS
    (una regola per controllo, rigenerata a ogni giro) perche' il "?" viveva
    dentro l'etichetta di Streamlit e collassarla lo faceva sparire. Ora che
    il suggerimento e' nostro, l'etichetta puo' essere un pezzo di markup
    normale e il valore un semplice `span`: una cosa in meno da tenere in
    piedi, e il fumetto e' quello dell'app.
    """
    val = f"<span class='au-sb-val'>{esc(valore)}</span>" if valore else ""
    (dove or st.sidebar).markdown(
        f"<div class='au-sb-eti'>{esc(testo)}"
        f"{_icona_aiuto(aiuto, predefinito, ripristina)}{val}</div>",
        unsafe_allow_html=True)


def _aiuto_a_destra(testo: str, predefinito: str = "", ripristina: str | None = None) -> None:
    """L'aiuto di un interruttore, in fondo alla sua riga.

    L'etichetta di un `toggle` vive DENTRO il componente, insieme
    all'interruttore e alla sua zona cliccabile: portarla fuori
    significherebbe rifare il controllo. Qui non si rompe niente — al nativo
    si toglie solo il suo `help=`, e la nostra icona si appoggia sopra, a
    filo destro della riga, fuori dall'etichetta (che finisce ben prima:
    misurata 193px su 256 disponibili). Il click sull'icona non arriva
    all'interruttore perche' l'icona sta sopra.
    """
    st.markdown(f"<div class='au-sb-aiuto'>{_icona_aiuto(testo, predefinito, ripristina)}</div>",
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

st.set_page_config(page_title="AnimeUp", page_icon="▲", layout="wide",
                   initial_sidebar_state="expanded")

# Senza il numero nell'etichetta: il cerchio numerato lo genera il CSS con un
# contatore, così il numero è un elemento a se' e non tre caratteri dentro
# una stringa che non si possono impaginare.
SEZIONI = ["Sorgenti", "Confronto", "Lavorazione"]
# «Inizio» sta prima dei tre passi ma non e' un passo del lavoro: cartelle,
# questo Mac e come va un lotto (la vecchia pagina vuota dei Sorgenti,
# promossa a pagina sua dall'utente). Fuori da SEZIONI, che il resto del
# codice indicizza per posizione.
INIZIO = "Inizio"

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

  /* I COLORI sono variabili scritte da `tema.css()` (vedi
     `_variabili_tema`): qui sotto non ne compare nessuno. */
  :root {{
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
      border: 1px solid var(--borderHover);
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
  .au-ok   {{ background: rgb(var(--greenRgb) / .10); border-color: rgb(var(--greenRgb) / .25);
             color:{VERDE}; }}
  .au-warn {{ background: rgb(var(--yellowRgb) / .10); border-color: rgb(var(--yellowRgb) / .25);
             color:{GIALLO}; }}
  /* "fatta" è BLU, non verde: il verde è già di "consigliato", e due chip
     verdi nella stessa colonna si leggevano come la stessa cosa (detto
     dall'utente). Il blu qui dice "capitolo chiuso". */
  .au-fatta {{ background: var(--blueBg); border-color: rgb(var(--blueRgb) / .30);
             color: var(--blueText); }}
  /* In coda: grigio, neutro — il file aspetta il suo turno nella catena. */
  .au-coda {{ background: var(--grayBg); border-color: rgb(var(--grayRgb) / .30);
             color: var(--grayText); }}
  .au-dim  {{ background: rgb(var(--grayRgb) / .10);border-color: rgb(var(--grayRgb) / .25);
             color:{TESTO_2}; }}
  /* Rosso e non ambra: l'ambra dice "guarda", il rosso dice "così non
     parte". Sono due cose diverse e la riga si comporta diversamente. */
  .au-err  {{ background: var(--redBg); border-color: rgb(var(--redRgb) / .35);
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
      border-radius: 9px; background: var(--primary); color: var(--onPrimary);
      font-size: 11px; font-weight: 700; line-height: 18px;
      text-align: center; box-shadow: 0 0 0 2px var(--bg); }}
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
      border-bottom: 1px solid rgb(var(--grayRgb) / .25); }}
  .au-cnf td {{ padding: 6px 10px 6px 0; font-variant-numeric: tabular-nums;
      border-bottom: 1px solid rgb(var(--grayRgb) / .12); }}
  .au-cnf .au-cnf-nome {{ font-weight: 600; }}
  .au-cnf .au-cnf-scarto {{ color: var(--grayText); }}
  /* L'avviso vero e proprio: giallo, la stessa famiglia delle chip
     `au-warn` e degli avvisi del referto. Distinto dalla nota grigia di
     congelamento, che e' una didascalia e non un avviso. */
  .au-nota-avviso {{ background: rgb(var(--yellowRgb) / .10);
      border: 1px solid rgb(var(--yellowRgb) / .25);
      border-left: 3px solid rgb(var(--yellowRgb) / .55);
      border-radius: 6px; padding: 8px 12px; margin: 6px 0 4px;
      font-size: 12px; line-height: 1.5; color: var(--yellowText); }}
  .au-nota-congelo {{ background: var(--grayBg);
      border: 1px solid rgb(var(--grayRgb) / .30);
      border-left: 3px solid rgb(var(--grayRgb) / .55);
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
      font-family: var(--font); box-shadow: 0 6px 20px rgb(var(--shadowRgb) / .45);
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
  /* .45 e non .3: il fumetto finisce di sparire a .3 + .12; scendendo
     prima, le icone vicine gli passavano sopra durante la dissolvenza. */
  .au-info, .au-perche {{ transition: z-index 0s .45s; }}
  /* Aperti verso l'interno quando centrati uscirebbero dalla finestra
     (lo decide lo script della pagina, vedi `au-a-destra`). */
  .au-a-destra .au-bolla {{ left: auto !important; right: -8px;
      transform: translateY(3px) !important; }}
  .au-a-sinistra .au-bolla {{ left: -8px !important; transform: translateY(3px) !important; }}
  :is(.au-a-destra, .au-a-sinistra):is(:hover, :focus-visible) .au-bolla {{
      transform: translateY(0) !important; }}
  .au-a-destra .au-bolla::before {{ left: auto !important; right: 5px; }}
  .au-a-sinistra .au-bolla::before {{ left: 15px !important; }}
  /* Nella sidebar l'icona non sale di livello: sale solo il suo fumetto
     (z-index 220 in tutta la barra). Salendo l'icona, un'altra «?» passata
     dal mouse mentre un fumetto svaniva saliva al pari e, venendo dopo,
     gli si disegnava sopra (visto dall'utente). Nelle righe invece l'icona
     deve stare sopra la lastra cliccabile, e la regola resta. */
  [data-testid="stSidebar"] :is(.au-info, .au-perche),
  [data-testid="stSidebar"] :is(.au-info, .au-perche):is(:hover, :focus-within, :focus-visible) {{
      z-index: auto !important; transition: none !important; }}
  .au-info:hover, .au-info:focus-within, .au-info:focus-visible,
  .au-perche:hover, .au-perche:focus-within, .au-perche:focus-visible {{
      z-index: 240; transition: z-index 0s 0s; }}
  .au-bolla-tit {{ font-weight: 600; color: {TESTO};
                  margin-bottom: 3px; }}
  .au-bolla-riga {{ color: {TESTO_2}; }}
  /* La frase che spiega il PERCHÉ sta staccata dalle cifre: è prosa, non
     una voce dell'elenco, e incollata si legge come una quarta riga. */
  .au-bolla-nota {{ color: {TESTO_3}; margin-top: 6px; }}
  /* Il predefinito che rimette il valore (vedi `_icona_aiuto`): un link
     d'accento, e il fumetto che lo porta deve restare aperto mentre ci si
     va sopra — si puo' toccare, e un ponte invisibile copre gli 8px fra
     icona e fumetto, cosi' il passaggio non lo chiude. */
  a.au-ripristina {{ color: var(--primaryText) !important; text-decoration: underline;
      text-underline-offset: 2px; align-self: flex-start; }}
  a.au-ripristina:hover {{ color: var(--primaryHover) !important; }}
  /* TUTTI i fumetti, non solo quelli col link: ci si puo' andare sopra e
     restano aperti (l'utente li trovava capricciosi, e lo erano: chi non
     aveva il link ignorava il puntatore e si chiudeva appena lo si
     raggiungeva). Il ponte copre gli 8px fra icona e fumetto. */
  /* Solo al passaggio, MAI col fuoco: dopo un clic l'icona restava col
     fuoco, e il fumetto invisibile continuava a prendere il mouse — passarci
     sopra lo riapriva e copriva quello che c'era sotto (bug segnalato
     dall'utente). */
  :is(.au-info, .au-perche):hover .au-bolla {{ pointer-events: auto; }}
  :is(.au-info, .au-perche) .au-bolla::after {{ content: ""; position: absolute; left: 0; right: 0;
      top: 100%; height: 12px; }}
  .au-agg-tip .au-bolla {{ pointer-events: none !important; }}
  .st-key-ripristiniNascosti, .st-key-premiNascosti,
  :is([data-testid="stLayoutWrapper"], [data-testid="stElementContainer"]):has(
      > :is(.st-key-ripristiniNascosti, .st-key-premiNascosti)) {{ display: none !important; }}
  /* La data dell'ultima taratura porta ai risultati: un link con la sua
     freccia, sottolineato al passaggio. */
  a.au-tar-vedi {{ display: flex; width: fit-content; align-items: center; gap: 4px;
      text-decoration: none; color: var(--greenText) !important; }}
  .au-tar-fatta a.au-tar-vedi {{ align-self: flex-start; }}
  a.au-tar-vedi svg {{ flex: none; opacity: .8; }}
  a.au-tar-vedi:hover {{ text-decoration: underline; text-underline-offset: 2px; }}
  a.au-tar-vedi:hover svg {{ opacity: 1; }}
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
     Misurati i suoi valori di partenza: fondo var(--sidebar2), angoli 8px, nessun
     bordo, testo pieno a 12.25/18.375, imbottitura 5.25/10.5. */
  [data-testid="stTooltipContent"] {{
      max-width: 264px !important;
      background: var(--surfaceHover) !important;
      color: {TESTO_2} !important;
      border: 1px solid {BORDO} !important; border-radius: 6px !important;
      padding: 9px 12px !important;
      font-family: var(--font) !important;
      font-size: 12.5px !important; line-height: 1.45 !important;
      box-shadow: 0 6px 20px rgb(var(--shadowRgb) / .45) !important; }}
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
  .au-consigliato {{ border-color: rgb(var(--greenRgb) / .35);
                    background: rgb(var(--greenRgb) / .05); }}
  .au-verifica {{ border-color: rgb(var(--yellowRgb) / .3);
                 background: rgb(var(--yellowRgb) / .04); }}
  .au-sconsigliato {{ border-color: rgb(var(--redRgb) / .3);
                     background: rgb(var(--redRgb) / .04); }}
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
      border-color: rgb(var(--primaryRgb) / .55); background: var(--primaryBg); }}
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
      color: {TESTO_2}; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  /* Nome della clip e orario interi: se insieme non ci stanno, l'orario va
     sotto (prima «Moviment/o» e «00:23 - / 00:33»). */
  [class*="st-key-clip"] [data-testid="stWidgetLabel"] {{ flex-wrap: wrap; column-gap: 8px; }}
  [class*="st-key-clip"] [data-testid="stWidgetLabel"] p {{ white-space: nowrap;
      overflow-wrap: normal; word-break: normal; }}
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
      border: 1px solid rgb(var(--primaryRgb) / .3);
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
     quello di `var(--onPrimary)` — verde scuro su fondo scuro, illeggibile. */
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
             border-color: rgb(var(--primaryRgb) / .3); }}
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
                            font-size: 11px; color: {TESTO_3}; }}
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
      background: linear-gradient(90deg, rgb(var(--primaryRgb) / .12) 0%, var(--rowBgHover) 50%); }}
  [class*="st-key-jrow"]:has(.au-tag.au-busy):has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{
      background: linear-gradient(90deg, rgb(var(--primaryRgb) / .22) 0%, var(--rowBgHover) 50%); }}
  [class*="st-key-jrow"]:has(.au-compiuta):has([class*="st-key-det"]:not([class*="st-key-dett"]) button:hover) {{
      background: linear-gradient(90deg, rgb(var(--greenRgb) / .16) 0%, var(--rowBgHover) 50%); }}
  /* Il riquadro col processo in corso si "alza" dal piano della pagina:
     ombra scura a due strati (contatto + diffusa) e superficie un filo
     piu' chiara — in tema scuro l'elevazione si legge cosi', l'ombra da
     sola su fondo quasi nero non basta. Voluta discreta (utente). */
  [class*="st-key-riga"]:has(.au-s-corso),
  [class*="st-key-jrow"]:has(.au-tag.au-busy) {{
      background: rgb(var(--overlayRgb) / .035);
      /* Lo zoom leggero completa l'effetto "sopraelevato". 1.025 scelto
         dall'utente (1.01 era troppo timido). */
      transform: scale(1.025);
      /* Alone piu' ampio: i tre strati restano (contatto, media
         distanza, diffusa) ma con raggi maggiori, cosi' la riga sembra
         piu' staccata dal piano senza diventare piu' scura. */
      box-shadow: 0 -12px 30px -6px rgb(var(--shadowRgb) / .50),
                  0 6px 18px rgb(var(--shadowRgb) / .45),
                  0 22px 46px -10px rgb(var(--shadowRgb) / .65); }}
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
      background: linear-gradient(90deg, rgb(var(--primaryRgb) / .08) 0%, var(--rowBg) 50%); }}
  /* In corso: la stessa velatura, piu' viva. */
  [class*="st-key-jrow"]:has(.au-tag.au-busy) {{
      background: linear-gradient(90deg, rgb(var(--primaryRgb) / .16) 0%, var(--rowBg) 50%); }}
  /* Fatto DURANTE la maratona: la riga resta viva e si prende il bordo
     verde delle cose concluse. Il nome torna a piena luce, altrimenti la
     regola generica delle righe non selezionate lo lascerebbe smorto. */
  [class*="st-key-jrow"]:has(.au-compiuta) {{
      border-left-color: var(--green);
      background: linear-gradient(90deg, rgb(var(--greenRgb) / .10) 0%, var(--rowBg) 50%); }}
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
      background: var(--backgroundColor, var(--bg)) !important;
      border: 1px solid {BORDO_VIVO} !important;
      border-radius: 6px !important;
      min-height: 0 !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"] div[value],
  [class*="st-key-jrow"] [data-testid="stSelectbox"] input,
  .st-key-sceltaTutti [data-testid="stSelectbox"] div[value],
  .st-key-sceltaTutti [data-testid="stSelectbox"] input {{
      font-size: 12px !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:hover > div {{
      border-color: var(--borderHover) !important; }}
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
  /* Solo sulle caselle vuote e attive: sopra una casella spuntata il
     velo grigio copriva il ciano e la spunta diventava un quadrato spento
     (segnalato dall'utente). Spuntata, al passaggio si schiarisce il suo
     ciano; spenta (durante una coda), non cambia niente. */
  [class*="st-key-jrow"] [data-testid="stCheckbox"]:hover:not(:has(input:checked)):not(:has(input:disabled))
      label > div:first-of-type {{
      border-color: var(--borderHover2) !important;
      background: rgb(var(--overlayRgb) / .07) !important; }}
  [class*="st-key-jrow"] [data-testid="stCheckbox"]:hover:has(input:checked):not(:has(input:disabled))
      label > div:first-of-type {{
      border-color: var(--primaryHover) !important;
      background: var(--primaryHover) !important; }}
  [class*="st-key-jrow"] [data-testid="stSelectbox"]:hover > div,
  .st-key-sceltaTutti [data-testid="stSelectbox"]:hover > div {{
      background: rgb(var(--overlayRgb) / .07);
      border-color: var(--borderHover2) !important; }}

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
  /* Anche «Includi l'originale» nella barra del Confronto: con lo stile
     di BaseWeb il pomello stava fuori centro in verticale (visto
     dall'utente). Una toggle sola in tutta l'app, disegnata una volta. */
  :is([data-testid="stSidebar"], [class*="st-key-tog_"]) [data-testid="stCheckbox"] label > div:not([data-testid]) {{
      width: 30px !important; height: 17px !important;
      border-radius: 999px !important; flex: none;
      background: var(--toggleOff) !important;
      transition: background .15s ease; }}
  :is([data-testid="stSidebar"], [class*="st-key-tog_"]) [data-testid="stCheckbox"] label > div:not([data-testid]) > div {{
      width: 13px !important; height: 13px !important;
      /* Niente margini orizzontali e posizioni ESPLICITE per i due stati
         (qui sotto): BaseWeb aggiunge un translateX suo anche da spenta,
         e la traccia ha 2px di padding suo: ogni conto usciva sbagliato di
         2px. I valori sotto sono MISURATI sul DOM, non calcolati: spenta
         2px dal bordo sinistro, accesa 1px dal destro (l'asimmetria è
         voluta, scelta a occhio dall'utente sul pannello vero). */
      border-radius: 50% !important; margin: 2px 0 !important;
      transform: translateX(0) !important;
      background: var(--knobOff) !important;
      box-shadow: none !important; transition: background .15s ease; }}
  /* Acceso: la traccia prende il ciano e il pomello si fa scuro, così lo
     stato si legge dal colore prima che dalla posizione. */
  :is([data-testid="stSidebar"], [class*="st-key-tog_"]) [data-testid="stCheckbox"] label:has(input:checked)
      > div:not([data-testid]) {{ background: var(--primary) !important; }}
  :is([data-testid="stSidebar"], [class*="st-key-tog_"]) [data-testid="stCheckbox"] label:has(input:checked)
      > div:not([data-testid]) > div {{ background: var(--knobOn) !important;
      /* BaseWeb sposta il pomello con un translateX calcolato sulla SUA
         geometria (traccia 28, pomello 11): sulla nostra 30/13 lo portava
         3px troppo a destra, fuori dalla traccia (misurato: pomello a 53 su
         traccia che finisce a 52). Il viaggio MISURATO che lascia 2px di
         1px di aria verso il bordo destro è 12px — non i 13 del conto
         teorico: BaseWeb parte già 2px più in la'. Con 2px il pomello
         sembrava non arrivare in fondo alla corsa (detto dall'utente). */
      transform: translateX(14px) !important; }}
  /* Spenta, anche l'etichetta si attenua: è un'opzione non attiva. */
  :is([data-testid="stSidebar"], [class*="st-key-tog_"]) [data-testid="stCheckbox"] label:not(:has(input:checked))
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
             background: var(--clipBg); pointer-events: none; }}
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
                  z-index: 100; background: rgb(var(--bgRgb) / .92);
                  backdrop-filter: blur(8px);
                  -webkit-backdrop-filter: blur(8px);
                  border-top: 1px solid {BORDO_VIVO};
                  /* Più chiara del fondo pagina, o non si distingueva
                     dall'elenco che le scorre sotto: è una fascia di
                     comando, deve staccarsi. */
                  box-shadow: 0 -10px 30px rgb(var(--shadowRgb) / .55);
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
  /* Riepilogo e nota uno sotto l'altra, non a 14px: erano letti come due
     cose separate (segnalato dall'utente). */
  .st-key-barra [data-testid="stColumn"]:first-child > [data-testid="stVerticalBlock"] {{
      gap: 6px !important; }}
  .au-barra-nota {{ font-size: 12.5px; line-height: 1.45; color: var(--textSecondary); }}
  .au-avvio {{ display: flex; align-items: center; gap: 10px; font-size: 13.5px;
      color: var(--textCode); }}
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
  /* 15rem e non 9: la barra con riepilogo, avvisi e nota arriva a ~200px,
     e il pannello aperto dell'ultima riga finiva sotto (visto dall'utente). */
  .block-container:has(.st-key-barra) {{ padding-bottom: 15rem; }}
  /* I messaggi in alto a destra (st.toast): col fondo di Streamlit erano
     tono su tono e passavano inosservati (segnalato dall'utente). Un
     riquadro rialzato, bordo vivo, una striscia d'accento e un'ombra. */
  [data-testid="stToast"] {{ background: var(--sidebar2) !important;
      border: 1px solid var(--borderHover) !important;
      border-left: 3px solid var(--primary) !important;
      box-shadow: 0 10px 28px rgb(var(--shadowRgb) / .5) !important; }}
  [data-testid="stToast"] p, [data-testid="stToast"] [data-testid="stMarkdownContainer"] {{
      color: var(--textPrimary) !important; font-weight: 500; }}

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
               font-variant-numeric: tabular-nums; line-height: 1.45; }}
  .au-ind > span {{ white-space: nowrap; }}
  /* `_pezzi`: il «·» vive nel margine sinistro di ogni pezzo; il contenitore
     esterno taglia la striscia in cui cade quello del primo pezzo di ogni
     riga. Un pezzo piu' lungo della riga va a capo da se'. */
  .au-pz {{ display: block; overflow: hidden; }}
  .au-pz > span {{ display: flex; flex-wrap: wrap; margin-left: -1.1em; }}
  .au-pz > span > span {{ position: relative; padding-left: 1.1em; min-width: 0; }}
  .au-pz > span > span::before {{ content: "·"; position: absolute; left: 0;
      width: 1.1em; text-align: center; }}
  :is(b, span, code, em) > .au-pz {{ display: inline-block; vertical-align: top; max-width: 100%; }}
  .au-nomis {{ white-space: nowrap; margin-top: 8px; }}
  [data-testid="stColumn"]:has(.au-nomis) {{ flex: 0 0 auto !important; width: auto !important; }}
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
               border: 1px solid rgb(var(--yellowRgb) / .2);
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
               border: 1px solid rgb(var(--redRgb) / .25);
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
               border: 1px solid rgb(var(--yellowRgb) / .25);
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
  /* La linea prende tutta la larghezza della barra (non solo la colonna del
     contenuto) e sopra di lei una sfumatura dice che le impostazioni
     scorrono sotto il piede, che resta fermo (chiesto dall'utente). */
  [data-testid="stLayoutWrapper"]:has(> .st-key-piede) {{
      position: sticky; bottom: 0; z-index: 6; margin-top: auto;
      margin-left: -20px; margin-right: -20px; padding: 0 20px;
      width: calc(100% + 40px) !important; max-width: none !important;
      box-sizing: border-box;
      background: var(--sidebar); border-top: 1px solid var(--borderStrong);
      padding-top: 0; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-piede)::before {{
      content: ""; position: absolute; left: 0; right: 0; top: -21px; height: 20px;
      pointer-events: none;
      background: linear-gradient(to bottom, rgb(var(--sidebarRgb) / 0), var(--sidebar)); }}
  /* 16px dalla linea alla CTA e 16px dalla CTA al fondo: la CTA stava a
     6px dal bordo finestra, "molto attaccata" (utente). Stesso passo della
     barra di Lavorazione. */
  .st-key-piede {{ padding: 14px 0 16px; }}
  /* In fondo alla barra scorsa: 20px fra l'ultima scheda e la linea, come
     ai lati (9 di passo della colonna + 11), e la sfumatura (20px) sta tutta
     in quel vuoto. Prima era alta 28 su 17 di spazio e copriva il bordo
     dell'ultima scheda (utente). */
  [data-testid="stLayoutWrapper"]:has(> .st-key-prefCard) {{ margin-bottom: 11px !important; }}

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
      box-shadow: -400px 0 0 0 var(--bg), 400px 0 0 0 var(--bg); }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-marchio) {{
      position: sticky; top: 45px; z-index: 26; background: var(--bg);
      margin-top: -17px; margin-bottom: -14px;
      padding-top: 17px; padding-bottom: 14px; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{
      position: sticky; top: 45px; z-index: 25;
      background: var(--bg); padding-top: 16px; padding-bottom: 0;
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
      box-shadow: -400px 0 0 0 var(--bg), 400px 0 0 0 var(--bg),
                  0 6px 12px -8px rgb(var(--shadowRgb) / .6); }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi)::after {{
      content: ""; position: absolute; left: 0; right: 0; bottom: -1px;
      height: 1px; background: {BORDO}; pointer-events: none;
      box-shadow: -400px 0 0 0 {BORDO}, 400px 0 0 0 {BORDO}; }}
  [data-testid="stHeader"] {{ background: var(--bg) !important; }}

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
  .au-cb-finta.au-cb-si {{ background: rgb(var(--grayRgb) / .25);
      border-color: rgb(var(--grayRgb) / .40); position: relative; }}
  .au-cb-finta.au-cb-si::after {{ content: ''; position: absolute;
      left: 5px; top: 1px; width: 5px; height: 10px;
      border: solid rgb(var(--textGrayRgb) / .70); border-width: 0 2px 2px 0;
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
                border: 2px solid rgb(var(--grayRgb) / .3);
                border-top-color: rgb(var(--textGrayRgb) / .95);
                animation: au-gira .7s linear infinite; }}
  @keyframes au-gira {{ to {{ transform: rotate(360deg); }} }}
  @media (prefers-reduced-motion: reduce) {{
    .au-rotella {{ animation: none; border-top-color: rgb(var(--grayRgb) / .3); }}
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
      background: var(--openRowBg);
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
                   color: {TESTO_2}; }}
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
      background: var(--openPanelBg);
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
      padding: 20px 24px 30px 21px; border-top-color: {BORDO}; }}
  /* La testata del pannello (titolo, stato della misura, Rianalizza) e'
     una riga sola, alta quanto il pulsante: le righe le davano 10px di
     padding e 10px di margine a ogni colonna, e la prima fascia risultava
     alta il doppio del necessario (segnalato dall'utente). */
  [class*="st-key-riga"] [class*="st-key-dett"] [data-testid="stHorizontalBlock"]:has(.au-pan-titolo) {{
      padding: 0 !important; margin-bottom: 4px; }}
  [class*="st-key-riga"] [class*="st-key-dett"] [data-testid="stHorizontalBlock"]:has(.au-pan-titolo)
      > [data-testid="stColumn"] {{ margin: 0 !important; }}
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
      transform: none; }}
  .stButton button[kind="primary"]:disabled p {{
      color: {TESTO_3} !important; }}
  /* IL CURSORE DI UN'APP, NON DI UNA PAGINA WEB (chiesto dall'utente):
     freccia sul testo — la barretta di selezione tradiva il browser — e
     manina su tutto cio' che si clicca. `cursor` si eredita, quindi basta
     dirlo sul contenitore e sugli elementi cliccabili; lo spento torna
     freccia, come in macOS (niente divieto). */
  .stApp, [role="dialog"], [data-testid="stSidebar"] {{ cursor: default; }}
  /* Niente velatura «in aggiornamento» sugli elementi mentre il server
     lavora: arrivava in ritardo e senza dire niente (al «Cambia…», detto
     dall'utente: inutile e laggoso). */
  [data-testid="stElementContainer"][data-stale="true"] {{ opacity: 1 !important;
      transition: none !important; }}
  :is(button:not(:disabled), a[href], summary, [role="slider"], [role="option"],
      [data-baseweb="slider"], [data-baseweb="select"], [data-testid="stCheckbox"] label,
      .au-info, [data-ripristina], [data-preme], #au-cassetto, #au-velo),
  :is(button:not(:disabled), a[href], summary, [data-baseweb="select"],
      [data-testid="stCheckbox"] label, [data-ripristina], [data-preme]) * {{ cursor: pointer; }}
  [data-testid="stSlider"]:not(:has(input:disabled)) [role="group"],
  [data-testid="stSlider"]:not(:has(input:disabled)) [role="group"] * {{ cursor: pointer; }}
  :is(button:disabled, [data-testid="stCheckbox"] label:has(input:disabled),
      [data-baseweb="select"]:has(input:disabled)),
  :is(button:disabled, [data-testid="stCheckbox"] label:has(input:disabled),
      [data-baseweb="select"]:has(input:disabled)) * {{ cursor: default !important; }}
  :is(input[type="text"], input[type="number"], input:not([type]), textarea):not(
      :disabled):not([readonly]):not([role="combobox"]) {{ cursor: text; }}
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
      border-color: rgb(var(--redRgb) / .45) !important;
      /* Nemmeno il fondo scuro predefinito: dentro una riga colorata era
         una toppa grigia. Il bordo rosso basta a farlo riconoscere. */
      background: transparent !important; }}
  [class*="st-key-ferma"] button p,
  [class*="st-key-scarta"] button p {{ color: var(--red) !important; }}
  [class*="st-key-ferma"] button:hover,
  [class*="st-key-scarta"] button:hover {{
      border-color: var(--red) !important;
      background: rgb(var(--redRgb) / .08) !important; }}
  [class*="st-key-fermasi"] button,
  [class*="st-key-scartasi"] button {{
      background: var(--redFill) !important;
      border-color: var(--redFill) !important; }}
  [class*="st-key-fermasi"] button p,
  [class*="st-key-scartasi"] button p {{
      color: var(--onRed) !important; font-weight: 600; }}
  [class*="st-key-fermasi"] button:hover,
  [class*="st-key-scartasi"] button:hover {{
      background: var(--redHover) !important; border-color: var(--redHover) !important; }}

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
      border-color: rgb(var(--primaryRgb) / .45) !important;
      background: transparent !important; }}
  [class*="st-key-pausa_tutto"] button p {{ color: {CIANO} !important; }}
  [class*="st-key-pausa_tutto"] button:hover {{
      border-color: {CIANO} !important;
      background: rgb(var(--primaryRgb) / .08) !important; }}

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
  [class*="st-key-rianalizzaFile"] button {{
      border: 1px solid {BORDO_VIVO} !important;
      background: none !important; box-shadow: none !important;
      padding: 8px 18px !important; }}
  /* L'icona nativa di Streamlit e non il carattere "⟳": quello a 12px è un
     ghirigoro illeggibile, questa è un'icona disegnata per essere piccola. */
  [class*="st-key-rianalizzaFile"] button [data-testid="stIconMaterial"] {{
      font-size: 16px; color: var(--textSecondary); }}
  [class*="st-key-rianalizzaFile"] button p {{
      font-size: 12.5px; font-weight: 500;
      color: var(--codeTextColor, var(--textCode)); transition: color .12s ease; }}
  /* L'HOVER STANDARD delle CTA secondarie: identico ovunque (chiesto
     dall'utente: "Seleziona tutti" brillava ciano, "Rianalizza" appena).
     Un filo piu' visibile del vecchio Rianalizza, meno del ciano di
     Streamlit. La famiglia rossa, le chevron e i pulsanti-link restano
     fuori: hanno il loro carattere. */
  [data-testid="stElementContainer"]:not([class*="st-key-ferma"]):not(
      [class*="st-key-scarta"]):not([class*="st-key-det"]):not(
      [class*="st-key-finder"]) .stButton button[kind="secondary"]:hover:not(:disabled) {{
      background: var(--sidebar2) !important;
      border-color: var(--borderHover) !important; }}
  [data-testid="stElementContainer"]:not([class*="st-key-ferma"]):not(
      [class*="st-key-scarta"]):not([class*="st-key-det"]):not(
      [class*="st-key-finder"]) .stButton
      button[kind="secondary"]:hover:not(:disabled) p {{ color: {TESTO} !important; }}
  /* Nella sidebar il fondo dell'hover generale e' quasi quello delle schede
     delle Preferenze (due grigi a quattro punti di distanza): l'hover c'era ma non si vedeva
     (segnalato dall'utente). Qui e' una velatura sul fondo che c'e', con lo
     stesso stacco che ha nella pagina. I :not(.a)... servono a vincere sulla
     regola generale, che ha un selettore lungo. */
  [data-testid="stSidebar"] [data-testid="stElementContainer"]:not(.st-key-esci) .stButton
      button[kind="secondary"]:hover:not(:disabled):not(.a):not(.b) {{
      background: rgb(var(--overlayRgb) / .07) !important;
      border-color: var(--borderHover) !important; }}
  .stButton button:active {{ transform: scale(.97); }}

  @media (prefers-reduced-motion: reduce) {{
    .st-key-barra {{ animation: none; }}
    [class*="st-key-dett"] {{ transition: none; }}
    [data-testid="stHorizontalBlock"], .stButton button {{ transition: none; }}
  }}

  /* ===================================================================
     Redesign 1.6 — sidebar. Misure dalla tavola "Sidebar" del design:
     titoli 17/600, note 12.5 nel grigio 2, occhielli 10.5 maiuscoli,
     etichette 13.5/500, valori in mono 12, riquadri con raggio 10.
     =================================================================== */
  [data-testid="stSidebar"] {{ background: var(--sidebar); }}
  [data-testid="stSidebarUserContent"] {{ margin-top: 0; padding-top: 4px; }}
  .au-sb-titolo {{ display: flex; align-items: center; gap: 8px;
      font-size: 17px; font-weight: 600; letter-spacing: -.01em;
      line-height: 1.3; margin: 16px 0 2px; color: var(--textPrimary); }}
  .au-sb-pref {{ margin-top: 6px; padding-top: 24px;
      border-top: 1px solid var(--borderStrong); }}
  .au-sb-nota {{ font-size: 12.5px; line-height: 1.45;
      color: var(--textSecondary); margin: 4px 0 0; }}
  .au-sb-nota-lock {{ color: var(--textCode); }}
  /* Bloccarsi e sbloccarsi si vede come una dissolvenza, non come uno scatto. */
  [data-testid="stSidebar"] :is([data-testid="stSlider"], [data-testid="stCheckbox"],
      [data-testid="stSelectbox"], [data-testid="stButtonGroup"], .au-sb-eti, .au-sgruppo,
      .au-pref-eti, .au-sb-aiuto, .au-sb-titolo > span, .au-percorso, .au-tar-mai,
      .au-tar-ok, .au-agg-nota, .st-key-adv summary) {{ transition: opacity .25s ease; }}
  .au-lock-chip {{ margin-left: auto; display: inline-flex;
      align-items: center; gap: 5px; padding: 2px 8px; border-radius: 999px;
      background: rgb(var(--primaryRgb) / .10);
      border: 1px solid rgb(var(--primaryRgb) / .30);
      color: var(--textPrimary); font: 400 11px var(--mono);
      white-space: nowrap; }}
  [data-testid="stSidebar"] .au-eyebrow.au-sgruppo {{ margin: 14px 0 2px;
      font-size: 10.5px; font-weight: 600; letter-spacing: .1em;
      color: var(--textTertiary); }}
  [data-testid="stSidebar"] .au-sb-eti {{ font-size: 13.5px;
      font-weight: 500; }}
  [data-testid="stSidebar"] .au-sb-val {{ font: 400 12px var(--mono);
      color: var(--textCode); }}
  /* Cursori: binario da 3, pomello da 12 con un anello del colore del
     fondo su cui sta, cosi' si legge come un ritaglio (tutti e due i temi). */
  [data-testid="stSidebar"] [data-testid="stSlider"] [data-orientation="horizontal"][style]
      > div:first-child {{ height: 3px; }}
  [data-testid="stSidebar"] [data-testid="stSlider"] [data-orientation="horizontal"][style]
      > div:nth-child(2) {{ width: 12px !important; height: 12px !important;
      background: var(--primaryStrong) !important;
      box-shadow: 0 0 0 2px var(--sidebar) !important; }}
  .st-key-adv [data-testid="stSlider"] [data-orientation="horizontal"][style]
      > div:nth-child(2) {{ box-shadow: 0 0 0 2px var(--sidebarCard) !important; }}
  /* «Avanzate»: un riquadro tono su tono che si apre. Lo stato (tutte di
     fabbrica / N cambiate) e' una pillola scritta dal CSS di ogni giro. */
  .st-key-adv [data-testid="stExpander"] details {{
      background: var(--sidebarCard); border: 1px solid var(--borderStrong);
      border-radius: 10px; }}
  .st-key-adv summary {{ padding: 12px 14px; }}
  .st-key-adv summary:hover {{ background: transparent; }}
  .st-key-adv summary p {{ display: flex; align-items: center; gap: 8px;
      font-size: 13.5px; font-weight: 600; }}
  .st-key-adv summary p::after {{ margin-left: auto; padding: 1px 8px;
      border-radius: 999px; border: 1px solid var(--borderStrong);
      color: var(--textSecondary); font: 400 11px var(--mono);
      white-space: nowrap; }}
  .st-key-adv [data-testid="stExpanderDetails"] {{ padding: 0 14px 14px; }}
  .au-adv-nota {{ font-size: 12px; color: var(--textSecondary);
      margin: -6px 0 2px; }}
  .au-cambiata {{ display: flex; align-items: center; gap: 6px;
      font: 400 11px var(--mono); color: var(--primaryText);
      margin: -6px 0 0 40px; }}
  .au-cambiata span {{ width: 5px; height: 5px; border-radius: 50%;
      background: var(--primary); flex: none; }}
  .st-key-cDisco + div .au-cambiata, .au-sb-eti + .au-cambiata,
  [data-testid="stLayoutWrapper"]:has(> :is(.st-key-cDisco, .st-key-cPausa))
      + [data-testid="stElementContainer"] .au-cambiata {{
      margin-left: 0; }}
  .au-sb-regola {{ font-size: 12px; line-height: 1.45;
      color: var(--textSecondary); margin-top: -4px; }}
  [data-testid="stElementContainer"]:has(.au-sb-ridotto) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .au-sb-ridotto {{ margin: 4px 0 10px; padding: 8px 10px; border-radius: 6px;
      background: var(--yellowBg); border: 1px solid rgb(var(--yellowRgb) / .3);
      font-size: 12px; line-height: 1.45; color: var(--yellowText); }}
  .au-sb-sospeso {{ padding: 10px 12px; border-radius: 8px;
      background: var(--yellowBg); border: 1px solid rgb(var(--yellowRgb) / .3);
      font-size: 12.5px; line-height: 1.45; color: var(--yellowText); }}
  .st-key-cSospeso button {{ background: transparent !important;
      border: 1px solid rgb(var(--yellowRgb) / .45) !important;
      color: var(--yellowText) !important; min-height: 30px; }}
  /* Preferenze: lingua e tema affiancati, poi un riquadro con cartelle,
     taratura e aggiornamenti, una riga per voce. */
  .st-key-cLinguaTema {{ gap: 12px; align-items: flex-end;
      flex-wrap: nowrap; }}
  .st-key-cLingua {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-cTema {{ flex: 0 0 auto; width: auto; }}
  .st-key-cLinguaTema [data-testid="stWidgetLabel"] p {{
      font-size: 13.5px; font-weight: 500; color: var(--textPrimary); }}
  .st-key-cTema [data-testid="stButtonGroup"] > div {{ gap: 2px;
      padding: 2px; border-radius: 8px; height: 36px; box-sizing: border-box;
      border: 1px solid var(--borderStrong); background: var(--sidebar2); }}
  .st-key-cTema [data-testid="stButtonGroup"] button {{ min-height: 0;
      height: 30px; width: 34px; padding: 0; border: 0 !important;
      background: transparent; color: var(--textSecondary); }}
  .st-key-cTema [data-testid="stButtonGroup"] button[kind$="Active"] {{
      background: var(--sidebarCard); color: var(--primaryText);
      box-shadow: 0 1px 2px rgb(var(--shadowRgb) / .25); }}
  .st-key-prefCard {{ background: var(--sidebarCard);
      border: 1px solid var(--borderStrong); border-radius: 10px;
      gap: 0 !important; }}
  .st-key-prefCard > div {{ padding: 12px 14px; }}
  .st-key-prefCard > div + div {{ border-top: 1px solid var(--borderFaint); }}
  .au-pref-eti {{ display: flex; align-items: center; gap: 6px;
      font-size: 13.5px; font-weight: 500; color: var(--textPrimary); }}
  /* Il «?» a 6px dall'etichetta come nelle Impostazioni in alto (qui il gap
     e il margine dell'icona si sommavano: 12px), e senza il rialzo di 1px
     pensato per il maiuscoletto: su un'etichetta normale la portava in alto
     (segnalato dall'utente). */
  .au-pref-eti .au-perche {{ margin-left: 0; }}
  .au-pref-eti .au-perche svg {{ transform: none; }}
  .au-percorso {{ display: block; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; font: 400 12px var(--mono) !important;
      color: var(--textCode) !important; background: none !important;
      padding: 0 !important; }}
  [class*="st-key-cCartellaPerc"] {{ flex-wrap: nowrap; gap: 8px; }}
  [class*="st-key-cCartellaPerc"] > div:first-child {{ flex: 1 1 auto;
      min-width: 0; }}
  [class*="st-key-cCartellaPerc"] > div:last-child {{ flex: 0 0 auto;
      width: auto; }}
  .st-key-cTarRiga {{ flex-wrap: nowrap; gap: 8px; }}
  .st-key-cTarRiga > div:first-child {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-cTarRiga > div:last-child {{ flex: 0 0 auto; width: auto; }}
  .au-tar-mai, .au-tar-ok {{ display: block; font: 400 11.5px var(--mono);
      margin-top: 2px; }}
  .au-tar-mai {{ color: var(--textSecondary); }}
  .au-tar-ok {{ color: var(--greenText); }}
  /* I pulsanti piccoli delle Preferenze (Cambia…, Ricalibra/Calibra ora):
     annullano il travestimento da link della versione precedente. */
  [data-testid="stSidebar"] :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) {{
      position: static; transform: none; }}
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button {{
      min-height: 28px !important; height: 28px !important; max-height: 28px;
      box-sizing: border-box; align-self: center; padding: 0 10px !important;
      border-radius: 6px; white-space: nowrap; text-decoration: none;
      border: 1px solid var(--borderStrong) !important; }}
  /* Il colore pieno solo da attivi: forzato anche da spenti, «Cambia…» a
     sidebar bloccata sembrava cliccabile (segnalato dall'utente). */
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button:not(:disabled) {{
      color: var(--textCode) !important; }}
  /* Spenti come nella pagina (testo al 40%, bordo tenue): la regola del
     vecchio travestimento da link forzava il testo pieno anche qui. */
  [data-testid="stSidebar"] :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"])
      button:disabled {{ color: rgb(var(--overlayRgb) / .4) !important;
      border-color: var(--borderColor) !important; }}
  [data-testid="stSidebar"] :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"])
      button:disabled p {{ color: inherit !important; }}
  :is([class*="st-key-apriTaratura"], [class*="st-key-apriCartella"]) button p {{
      font-size: 12.5px; font-weight: 500; }}
  /* Bordo trasparente e non assente: lo stesso box di «Cambia…», che il
     bordo ce l'ha (altezze diverse, segnalato dall'utente). */
  .st-key-apriTaratura button[kind="primary"] {{
      background: var(--primaryStrong) !important; border: 1px solid transparent !important;
      color: var(--onPrimary) !important; }}
  .st-key-apriTaratura button[kind="primary"] p {{ font-weight: 600; }}
  /* Le righe delle cartelle di Inizio: «Apri nel Finder» e i due «Cambia…»
     alti uguali. Quello accanto al pulsante pieno si allungava a 34px e
     quello da solo restava piu' basso (segnalato dall'utente). Solo qui:
     non e' una regola per tutti i pulsanti. */
  :is(.st-key-apriInput, .st-key-cambiaInput, .st-key-cambiaOutput) button {{
      min-height: 34px !important; height: 34px !important; box-sizing: border-box; }}
  /* Il piede: versione e «About» a sinistra, su due righe alte quanto il
     pulsante Esci a destra; sempre sul bordo basso della finestra. */
  .st-key-piede {{ flex-wrap: nowrap; justify-content: space-between;
      background: var(--sidebar); }}
  .au-piede {{ display: flex; flex-direction: column; line-height: 16px;
      font: 400 11.5px var(--mono); color: var(--textSecondary); }}
  .au-piede a {{ font-family: var(--font); font-size: 12px;
      color: var(--textSecondary) !important; text-decoration: underline;
      text-underline-offset: 2px; }}
  .st-key-esci, .st-key-fermasi_app {{ width: auto !important; flex: none; }}
  /* Esci in rosso al passaggio: vince sulla regola generale delle CTA
     secondarie, che ha un selettore lungo (i :not in piu' servono a questo). */
  [data-testid="stElementContainer"].st-key-esci .stButton button[kind="secondary"]:hover:not(.a):not(.b):not(.c):not(.d) {{
      background: var(--redFill) !important; border-color: var(--redFill) !important; }}
  [data-testid="stElementContainer"].st-key-esci .stButton button[kind="secondary"]:hover:not(.a):not(.b):not(.c):not(.d) p {{
      color: var(--onRed) !important; }}
  .st-key-esci button, .st-key-fermasi_app button {{ height: 32px;
      min-height: 32px; padding: 0 12px; white-space: nowrap; }}
  /* L'avviso di aggiornamento: in giallo, come un avviso, con la CTA gialla
     piena. In ciano si confondeva col resto della barra (detto dall'utente). */
  .st-key-cAggiorna [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-cAggiorna {{ gap: 10px !important; }}
  .st-key-cAggiorna {{ padding: 12px 14px; border-radius: 10px;
      background: var(--yellowBg);
      border: 1px solid rgb(var(--yellowRgb) / .45); margin-top: 12px; }}
  /* Titolo e «Novità» nel colore del testo, non in giallo: il giallo resta
     al riquadro e al pulsante, e il titolo si legge meglio (chiesto
     dall'utente). */
  .au-agg-testa {{ display: flex; align-items: center; gap: 8px;
      font-size: 13.5px; color: var(--text); }}
  .au-agg-testa a {{ margin-left: auto; font-size: 12.5px;
      color: var(--text) !important; text-decoration: underline; }}
  .st-key-cAggiorna [data-testid="stCaptionContainer"] p {{ color: var(--yellowText) !important;
      opacity: .85; }}
  .st-key-installaAgg .stButton button[kind="primary"] {{
      background: var(--yellow) !important; border-color: var(--yellow) !important; }}
  .st-key-installaAgg .stButton button[kind="primary"] p {{ color: var(--onYellow) !important; }}
  .st-key-installaAgg .stButton button[kind="primary"]:hover {{
      background: var(--yellowHover) !important; border-color: var(--yellowHover) !important; }}
  .st-key-installaAgg .stButton button[kind="primary"]:active {{
      background: var(--yellowActive) !important; }}

  /* ===================================================================
     Redesign 1.6 — struttura: sidebar da 360, barra dei passi in cima
     senza il vuoto di prima, contenuto a 40px dai bordi.
     =================================================================== */
  [data-testid="stSidebar"] {{ width: 360px !important; min-width: 360px !important;
      max-width: 360px !important; border-right: 1px solid var(--borderStrong); }}
  [data-testid="stSidebarUserContent"] {{ padding-left: 20px !important;
      padding-right: 20px !important; }}
  [data-testid="stSidebarHeader"], [data-testid="stSidebarCollapseButton"],
  [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}
  [data-testid="stHeader"] {{ display: none !important; }}
  .block-container {{ padding: 0 40px 4rem !important; max-width: none !important; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{ top: 0 !important;
      margin-left: -40px; margin-right: -40px; padding: 15px 40px 14px !important;
      min-width: calc(100% + 80px);
      box-shadow: none !important; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi)::after {{
      box-shadow: none !important; }}
  .st-key-fasi {{ padding-bottom: 0 !important; gap: 16px; flex-wrap: nowrap; }}
  .st-key-passi {{ width: auto !important; flex: 0 0 auto; padding: 4px;
      gap: 0 !important; border: 1px solid var(--borderColor);
      border-radius: 12px; background: var(--surface); }}
  .st-key-passi [class*="st-key-passo"] {{ width: auto !important; }}
  .st-key-passi button {{ position: relative; width: 230px; height: 55px;
      min-height: 55px; padding: 0 40px 0 51px !important;
      justify-content: flex-start; text-align: left; border-radius: 8px;
      border: 1px solid transparent !important; background: transparent !important;
      background-repeat: no-repeat !important; box-shadow: none !important;
      transform: none !important; }}
  .st-key-passi button > div {{ justify-content: flex-start; }}
  .st-key-passi button p {{ display: flex; flex-direction: column;
      align-items: flex-start; font-size: 14px; font-weight: 600;
      line-height: 19px; color: var(--textPrimary); white-space: nowrap; }}
  /* Il sottotitolo non si taglia mai: se non sta, va su due righe (e tutti
     e tre i passi crescono insieme). */
  .st-key-passi button > div, .st-key-passi button p {{ width: 100%; min-width: 0; }}
  .st-key-passi button p::after {{ font-size: 12.5px; font-weight: 400;
      line-height: 18px; color: var(--textSecondary); white-space: pre-line;
      max-width: 100%; }}
  .st-key-passi {{ align-items: stretch !important; }}
  .st-key-passi > [class*="st-key-passo"] {{ align-self: stretch; display: flex;
      height: auto !important; }}
  .st-key-passi > [class*="st-key-passo"] > .stButton {{ display: flex; flex: 1; }}
  .st-key-passi button {{ height: auto !important; min-height: 55px !important;
      padding-top: 6px !important; padding-bottom: 6px !important; }}
  /* Centrato su un pixel intero e senza `transform`: con la scheda alta
     67px il cerchio cadeva a mezzo pixel, e WebKit lo ricampionava
     sgranando l'icona (segnalato dall'utente sulla casetta). */
  .st-key-passi button::before {{ position: absolute; left: 14px;
      top: round(down, calc(50% - 12px), 1px); transform: none; width: 24px; height: 24px;
      box-sizing: border-box; border-radius: 50%;
      border: 1px solid var(--borderHover); display: inline-flex;
      align-items: center; justify-content: center;
      font: 500 11px var(--mono); color: var(--textSecondary); }}
  .st-key-passi button[kind="primary"] {{
      border-color: var(--primary) !important;
      background-color: rgb(var(--primaryRgb) / .08) !important; }}
  .st-key-passi button[kind="primary"]::before {{
      background: var(--primary); border-color: var(--primary);
      color: var(--onPrimary); font-weight: 600; }}
  .st-key-passi button[kind="primary"] p::after {{ color: var(--primaryText); }}
  .st-key-passi button:hover:not(:disabled) {{
      background-color: var(--surfaceHover) !important; }}
  .st-key-passi button[kind="primary"]:hover {{
      background-color: rgb(var(--primaryRgb) / .12) !important; }}
  .st-key-passi button:disabled {{ cursor: default; opacity: 1; }}
  /* Un passo chiuso dice «non ancora» anche al puntatore (chiesto
     dall'utente): il divieto, non la freccia di un testo qualsiasi. */
  .st-key-passi [class*="st-key-passo"] button:disabled,
  .st-key-passi [class*="st-key-passo"] button:disabled * {{ cursor: not-allowed !important; }}
  /* Un passo chiuso non ha mai il contatore a destra: il suo spazio va al
     sottotitolo a qualunque larghezza (prima solo sotto i 1360). */
  .st-key-passi button:disabled {{ padding-right: 14px !important; }}
  .st-key-passi button:disabled p {{ color: var(--textSecondary); }}
  .st-key-passi button:disabled::before {{
      background: var(--textTertiary); border: 0;
      -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='11.5' fill='none' stroke='black' stroke-width='1'/%3E%3Crect x='8' y='11' width='8' height='6' rx='1.2' fill='none' stroke='black' stroke-width='1.6'/%3E%3Cpath d='M9.6 11V9.2a2.4 2.4 0 0 1 4.8 0V11' fill='none' stroke='black' stroke-width='1.6'/%3E%3C/svg%3E") center / 24px 24px no-repeat; }}
  .st-key-passi button::after {{ display: none; position: absolute; right: 14px;
      top: 50%; transform: translateY(-50%); min-width: 20px; height: 20px;
      padding: 0 5px; box-sizing: border-box; border-radius: 999px;
      align-items: center; justify-content: center;
      background: var(--primary); color: var(--onPrimary);
      font: 600 11px var(--mono); }}
  /* Inizio: piu' stretto, senza numero ne' sottotitolo; al posto del
     numero una casetta, nello stesso cerchio. */
  .st-key-passi .st-key-passo0 button {{ width: auto; min-width: 0;
      padding-right: 18px !important; }}
  .st-key-passo0 button::before {{ content: ""; background: var(--textSecondary); border: 0;
      -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='11.5' fill='none' stroke='black' stroke-width='1'/%3E%3Cpath d='M7.5 12 12 8l4.5 4M9 11v5.2h6V11' fill='none' stroke='black' stroke-width='1.6' stroke-linejoin='round' stroke-linecap='round'/%3E%3C/svg%3E") center / 24px 24px no-repeat; }}
  /* Attiva: cerchio pieno con la casetta scavata. Due maschere semplici
     sottratte l'una all'altra, non una maschera SVG interna: WebKit quella
     la disegna a bassa risoluzione, e la casetta usciva sgranata mentre il
     cerchio restava nitido (visto nella finestra dell'app). */
  .st-key-passo0 button[kind="primary"]::before {{ background: var(--primary);
      -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 24 24'%3E%3Cpath d='M7.5 12 12 8l4.5 4M9 11v5.2h6V11' fill='none' stroke='black' stroke-width='1.8' stroke-linejoin='round' stroke-linecap='round'/%3E%3C/svg%3E") center / 24px 24px no-repeat, url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='12' fill='black'/%3E%3C/svg%3E") center / 24px 24px no-repeat;
      -webkit-mask-composite: xor; mask-composite: exclude; }}
  .au-fasi-stato {{ margin-left: auto; display: flex; align-items: center;
      gap: 8px; font: 400 12px var(--mono); color: var(--textSecondary);
      white-space: nowrap; }}
  .au-fasi-stato span {{ width: 6px; height: 6px; border-radius: 50%;
      background: var(--dot); }}
  .au-fasi-stato.au-vivo {{ color: var(--primaryText); }}
  .au-fasi-stato.au-vivo span {{ background: var(--primary);
      box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .st-key-fasi [data-testid="stElementContainer"]:has(.au-fasi-stato) {{
      margin-left: auto; width: auto; }}

  /* I blocchi che portano solo stile o script non occupano posto: ognuno
     prenderebbe il suo spazio di colonna (16px) e in cima alla pagina se ne
     sommavano tre prima della barra dei passi. Fuori dal flusso, ma vivi:
     un iframe nascosto esegue lo stesso il suo script. */
  [data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"] > style:only-child),
  [data-testid="stElementContainer"]:has([data-testid="stIFrame"]) {{
      position: absolute !important; width: 0 !important; height: 0 !important;
      overflow: hidden !important; margin: 0 !important; }}
  .st-key-passi button[kind="primary"] p {{ color: var(--textPrimary) !important; }}

  [data-testid="stSidebarContent"] {{ padding-left: 0 !important;
      padding-right: 0 !important; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-passi) {{
      flex: 0 0 auto !important; width: auto !important; }}
  .st-key-passi {{ width: fit-content !important; }}
  /* «Avanzate»: titolo e sottotitolo su due righe, la pillola a destra. */
  .st-key-adv summary {{ position: relative; padding: 12px 110px 12px 14px; }}
  .st-key-adv summary [data-testid="stMarkdownContainer"]::after {{
      content: var(--adv-nota); display: block; font-size: 12px;
      font-weight: 400; line-height: 1.3; color: var(--textSecondary);
      margin-top: 2px; }}
  .st-key-adv summary p::after {{ position: absolute; right: 14px; top: 50%;
      transform: translateY(-50%); margin: 0; }}
  .st-key-adv summary p {{ display: block; line-height: 1.35; }}
  .au-adv-nota {{ display: none; }}
  /* Righe delle Preferenze: compatte come nel design (76px le cartelle). */
  .st-key-prefCard [data-testid="stVerticalBlock"] {{ gap: 6px !important; }}
  .st-key-prefCard > div {{ padding: 12px 14px !important; }}
  .au-agg-nota {{ font-size: 12px; color: var(--textSecondary);
      margin: -6px 0 0 44px; }}
  .st-key-swAggiorn [data-testid="stTooltipIcon"] {{ display: none; }}
  .st-key-cLinguaTema [data-testid="stWidgetLabel"] {{ min-height: 21px;
      margin-bottom: 6px; }}

  [data-testid="stSidebar"] .au-eyebrow.au-sgruppo {{ margin-top: 22px; }}
  .st-key-adv summary {{ padding-right: 118px !important; }}
  .au-sb-pref {{ margin-top: 14px; padding-top: 28px; margin-bottom: 14px; }}
  .au-agg-nota {{ margin-left: 40px; }}
  .st-key-cTaratura {{ gap: 2px !important; }}

  /* Finestre strette (l'app scende fino a 1000px): sotto i 1360 la barra
     dei passi si stringe e lascia lo stato, che ripete il passo 3; nelle
     righe i numeri non vanno a capo a meta' e i nomi lunghi si fermano a due
     righe. A 1440 non cambia niente. */
  @media (max-width: 1360px) {{
    /* Un passo chiuso non ha mai il contatore a destra: il suo spazio va al
       sottotitolo. */
    .st-key-passi button:disabled {{ padding-right: 14px !important; }}
    /* Le fasi di una riga possono andare a capo: senza i trattini, una riga
     nuova non comincia con un trattino appeso. */
    .au-tappa + .au-tappa::before {{ display: none; }}
    /* Numeri, intestazioni e chip interi: mai tagliati. Solo i nomi dei
       file, che sono dati, si fermano a due righe. */
    .au-cell, .au-eyebrow, .au-tag {{ white-space: nowrap; }}
    /* «Rianalizza» nel dettaglio di un file: il pulsante si tiene la sua
       larghezza invece di andare a capo. */
    [data-testid="stColumn"]:has([class*="st-key-rianalizzaFile"]) {{
        flex: 0 0 auto !important; width: auto !important; min-width: max-content !important; }}
    [class*="st-key-rianalizzaFile"] button {{ white-space: nowrap; }}
    /* La fascia dei Sorgenti va a capo fra un pezzo e l'altro, mai dentro
       «6 file» o «00:07:02 di video». */
    div.au-fascia-sorgenti {{ flex-wrap: wrap; row-gap: 6px; height: auto;
        min-height: 46px; padding-top: 8px; padding-bottom: 8px; }}
    div.au-fascia-sorgenti > * {{ white-space: nowrap; }}
    .au-name {{ display: -webkit-box; -webkit-line-clamp: 2;
        -webkit-box-orient: vertical; overflow: hidden; }}
    /* La tabella dei Sorgenti (cinque colonne): stessa regola. */
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child) {{
        flex-wrap: nowrap !important; gap: 10px !important; }}
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child)
        > [data-testid="stColumn"]:nth-child(1) {{ flex: 1.3 1 0 !important; min-width: 0 !important; }}
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child)
        > [data-testid="stColumn"]:nth-child(2) {{ flex: 0 0 84px !important; min-width: 0 !important; }}
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child)
        > [data-testid="stColumn"]:nth-child(3) {{ flex: 0 0 66px !important; min-width: 0 !important; }}
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child)
        > [data-testid="stColumn"]:nth-child(4) {{ flex: 1 1 0 !important; min-width: 0 !important; }}
    :is(.st-key-intest, [class*="st-key-riga"]) [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(5):last-child)
        > [data-testid="stColumn"]:nth-child(5) {{ flex: 0 0 24px !important; min-width: 0 !important; }}
    /* La tabella di Lavorazione (otto colonne): i numeri hanno la loro
       larghezza, il nome prende quello che resta. */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child) {{
        flex-wrap: nowrap !important; gap: 10px !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(2) {{ flex: 1 1 0 !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(3) {{ flex: 0 0 84px !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(4) {{ flex: 0 0 66px !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(5) {{ flex: 0 0 150px !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(6) {{ flex: 0 0 96px !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:nth-child(7) {{ flex: 0 0 72px !important; min-width: 0 !important; }}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(8):last-child)
        > [data-testid="stColumn"]:is(:nth-child(1), :nth-child(8)) {{ flex: 0 0 24px !important;
        min-width: 0 !important; }}
  }}


  /* Il cassetto sotto i 1360px (vedi `_cassetto_sidebar`). */
  #au-cassetto, #au-velo {{ display: none; }}
  @media (max-width: 1100px) {{ .au-fasi-stato {{ display: none; }} }}
  /* Con Inizio la barra dei passi e' piu' lunga: accanto alla barra laterale
     lo stato (che ripete il passo 3) ci sta solo da 1480 in su. */
  @media (min-width: 1361px) and (max-width: 1480px) {{ .au-fasi-stato {{ display: none; }} }}
  /* La barra laterale la governa solo AnimeUp, mai lo stato «chiusa» di
     Streamlit: Streamlit la chiude da solo quando la finestra si stringe, e
     poi non la riapriva — a finestra larga restava il suo spazio con una
     striscia di contenuto tagliato (visto nella finestra dell'app). */
  @media (min-width: 1361px) {{
    [data-testid="stSidebar"] {{ transform: none !important; }}
  }}
  @media (max-width: 1360px) {{
    [data-testid="stSidebar"] {{ position: fixed !important; top: 0; bottom: 0; left: 0;
        z-index: 1002; transform: translateX(-100%) !important; transition: transform .2s ease;
        box-shadow: none; }}
    body.au-sb-aperta [data-testid="stSidebar"] {{ transform: none !important;
        box-shadow: 0 0 32px rgb(var(--shadowRgb) / .35); }}
    #au-velo {{ display: block; position: fixed; inset: 0; z-index: 1001;
        background: rgb(var(--shadowRgb) / .35); opacity: 0; pointer-events: none;
        transition: opacity .2s ease; }}
    body.au-sb-aperta #au-velo {{ opacity: 1; pointer-events: auto; }}
    #au-cassetto {{ display: inline-flex; align-items: center; justify-content: center;
        position: fixed; left: 16px; top: 30px; z-index: 1003; width: 36px; height: 36px;
        padding: 0; border-radius: 8px; cursor: pointer;
        border: 1px solid var(--borderStrong); background: var(--surface);
        color: var(--textCode); }}
    #au-cassetto:hover {{ color: var(--primaryText); border-color: var(--borderHover); }}
    /* Il pallino: qualcosa nella barra chiede attenzione (aggiornamento,
       taratura da fare o da rifare). Giallo come gli avvisi. */
    #au-cassetto.au-agg::after {{ content: ""; position: absolute; top: -4px; right: -4px;
        width: 10px; height: 10px; border-radius: 50%; background: var(--yellow);
        box-shadow: 0 0 0 2px var(--bg); }}
    /* Aperto il cassetto, il pulsante sparisce: si chiude toccando fuori
       (il velo) o con Esc. Spostato accanto alla barra non serviva e
       stonava (chiesto dall'utente). */
    body.au-sb-aperta #au-cassetto {{ display: none; }}
    .block-container {{ padding-left: 68px !important; }}
    [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{ margin-left: -68px !important;
        padding-left: 68px !important; min-width: calc(100% + 108px) !important; }}
    :is(.st-key-barraSorgenti, .st-key-barraConfronto) {{ left: 0 !important; }}
    .st-key-barra {{ left: 0 !important; }}
  }}

  /* Ritmo verticale misurato sulla tavola "Main" (passata pixel perfect). */
  [data-testid="stSidebar"] .au-eyebrow.au-sgruppo {{ margin: 30px 0 11px; }}
  :is(.st-key-cAltezza, .st-key-cCrf, .st-key-cPreset) {{ margin: -2px 0 4px; }}
  .st-key-adv {{ margin-top: 6px; }}
  .st-key-adv summary p {{ line-height: 16px; }}
  .st-key-adv summary [data-testid="stMarkdownContainer"]::after {{ margin-top: 1px; }}
  .au-sb-pref {{ margin: 19px 0 16px; padding-top: 21px; }}
  /* Lingua quanto resta, tema largo quanto i suoi tre pulsanti. */
  [data-testid="stLayoutWrapper"]:has(> .st-key-cLingua) {{ flex: 1 1 auto !important;
      min-width: 0; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-cTema) {{ flex: 0 0 auto !important;
      width: auto !important; }}
  /* Le righe del riquadro: 77px le cartelle, come nel design. */
  .st-key-prefCard [class*="st-key-cCartellaRiga"], .st-key-cTarRiga {{ margin: 0 !important; }}
  .st-key-prefCard [class*="st-key-cCartellaRiga"] {{ gap: 4px !important; }}
  .st-key-prefCard .au-pref-eti {{ line-height: 19px; }}
  [class*="st-key-cCartellaPerc"] {{ min-height: 28px; height: 28px; align-items: center; }}
  /* La nota sotto «Controlla gli aggiornamenti» restava fuori dal riquadro:
     il -1rem di Streamlit in fondo al markdown la faceva sbordare. */
  .st-key-swAggiorn [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-swAggiorn .au-agg-nota {{ margin-top: -8px; line-height: 15px; }}
  /* Il binario dei cursori va da bordo a bordo, come nel design: Streamlit
     lo rientrava di 5px per lato. */
  [data-testid="stSidebar"] [data-testid="stSlider"] > div:last-child {{
      padding-left: 0 !important; padding-right: 0 !important; }}
  .st-key-cTaratura {{ gap: 0 !important; }}
  .st-key-cTaratura .au-tar-mai, .st-key-cTaratura .au-tar-ok {{ margin-top: 0; }}
  .au-sb-pref {{ margin-bottom: 14px; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-prefCard) {{ margin-top: 2px; }}

  /* ===================================================================
     Redesign 1.6 — Sorgenti senza video.
     =================================================================== */
  .au-titolo-pagina {{ font-size: 24px; font-weight: 600;
      letter-spacing: -.02em; line-height: 1.25; margin-top: 28px;
      color: var(--textPrimary); }}
  .au-sotto-pagina {{ font-size: 14px; line-height: 1.5; max-width: 720px;
      color: var(--textSecondary); margin-top: 6px; }}
  .st-key-vuotoGriglia {{ gap: 24px !important; align-items: stretch;
      flex-wrap: nowrap; margin-top: 12px; }}
  .st-key-cartelleCard, .st-key-questoMac {{ background: var(--surface);
      border: 1px solid var(--borderColor); border-radius: 12px; }}
  .st-key-cartelleCard {{ flex: 1 1 auto; min-width: 0; gap: 16px !important;
      padding: 24px 24px 0; }}
  .st-key-questoMac {{ flex: 0 0 340px; width: 340px !important; padding: 20px;
      gap: 14px !important; }}
  .au-card-testa {{ display: flex; gap: 16px; align-items: flex-start; }}
  .au-card-testa.au-centrata {{ align-items: center; gap: 14px; }}
  /* Icone dei pulsanti pieni nel colore della loro scritta (in scuro erano
     bianche su ciano); icone delle tessere nell'accento chiaro del design. */
  button[kind="primary"] [data-testid="stIconMaterial"] {{ color: var(--onPrimary) !important; }}
  .au-tessera svg {{ color: var(--primary); }}
  /* Il -1rem di Streamlit sotto un markdown spostava lo stato a destra della
     barra dei passi e le due righe del piede 7px piu' in basso del centro. */
  .st-key-fasi [data-testid="stElementContainer"]:has(.au-fasi-stato) [data-testid="stMarkdownContainer"],
  .st-key-piede [data-testid="stMarkdownContainer"],
  [data-testid="stElementContainer"]:has(.au-cambiata) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .st-key-piede {{ align-items: center !important; }}
  .st-key-piedeSx {{ gap: 0 !important; width: auto !important; flex: 1 1 auto; }}
  .st-key-piedeVer {{ gap: 4px !important; flex-wrap: nowrap; align-items: center; }}
  .st-key-piedeVer > div:first-child {{ width: auto !important; flex: none; }}
  .st-key-controllaAgg {{ width: auto !important; flex: none; }}
  /* I fumetti dei tre cursori in cima alla barra si aprono verso il basso:
     verso l'alto uscivano dalla finestra (sotto la barra del titolo). */
  [data-testid="stElementContainer"]:has(+ [data-testid="stLayoutWrapper"] >
      :is(.st-key-cAltezza, .st-key-cCrf, .st-key-cPreset)) .au-bolla {{
      bottom: auto; top: calc(100% + 8px); transform: translateX(-50%) translateY(-3px); }}
  [data-testid="stElementContainer"]:has(+ [data-testid="stLayoutWrapper"] >
      :is(.st-key-cAltezza, .st-key-cCrf, .st-key-cPreset)) .au-bolla::before {{
      bottom: auto; top: -5px; transform: translateX(-50%) rotate(45deg); }}
  [data-testid="stElementContainer"]:has(+ [data-testid="stLayoutWrapper"] >
      :is(.st-key-cAltezza, .st-key-cCrf, .st-key-cPreset)) .au-bolla::after {{
      top: auto; bottom: 100%; }}
  /* Il fumetto dell'icona «controlla adesso»: lo stesso dei «?», con la
     punta (quello nativo di Streamlit non ce l'ha). */
  .au-ver {{ position: relative; }}
  .au-agg-tip {{ position: absolute; left: calc(100% + 13px); top: -3px; width: 0; height: 0;
      margin: 0 !important; }}
  .st-key-piedeVer:has(.st-key-controllaAgg button:hover) .au-agg-tip .au-bolla {{
      opacity: 1; transform: translateX(-50%) translateY(0);
      transition: opacity .12s ease 0s, transform .12s ease 0s; }}
  .au-agg-tip .au-bolla {{ white-space: nowrap; width: max-content; max-width: none; }}
  /* «Rianalizza tutti»: il fumetto sopra il pulsante, aperto verso
     sinistra (il pulsante sta sul bordo destro della pagina). */
  .st-key-rianRiga {{ position: relative; width: auto !important; flex: none; gap: 0 !important; }}
  /* Il contenitore del fumetto non deve allargarsi: i due pulsanti restano
     in fondo a destra come prima (spostati, segnalato dall'utente). */
  .st-key-testaSorgenti > [data-testid="stLayoutWrapper"]:has(> .st-key-rianRiga) {{
      flex: 0 0 auto !important; width: auto !important; }}
  .st-key-rianRiga [data-testid="stElementContainer"]:has(.au-rian-tip) {{
      position: absolute; left: 50%; top: 0; width: 0; height: 0; margin: 0; }}
  .st-key-rianRiga [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .au-rian-tip {{ position: absolute; left: 0; top: 0; width: 0; height: 0; }}
  .au-rian-tip .au-bolla {{ max-width: 300px; }}
  .st-key-rianRiga:has(.st-key-rianTutti button:hover) .au-rian-tip .au-bolla {{
      opacity: 1; transform: translateY(0) !important;
      transition: opacity .12s ease 0s, transform .12s ease 0s; }}
  /* La risposta del controllo aggiornamenti, al centro (vedi `_modale_esito_agg`). */
  [role="dialog"]:has(.au-esito-agg) > h2 {{ position: absolute; width: 1px; height: 1px;
      overflow: hidden; clip-path: inset(50%); }}
  /* Il titolo nativo e' nascosto e lascia 12px sopra contro i 21 ai lati:
     icona e titolo sembravano attaccati al bordo (segnalato dall'utente). */
  .au-esito-agg {{ display: flex; gap: 14px; align-items: flex-start; margin-top: 9px; }}
  .au-esito-agg b {{ display: block; font-size: 17px; font-weight: 600; margin-bottom: 4px; }}
  .au-esito-agg span:not(.au-esito-icona) {{ font-size: 13.5px; line-height: 1.5;
      color: var(--textSecondary); }}
  .au-esito-icona {{ width: 40px; height: 40px; flex: none; box-sizing: border-box;
      border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; }}
  .au-esito-ok {{ background: var(--greenBg); border: 1.5px solid var(--green); color: var(--greenText); }}
  .au-esito-nuova {{ background: rgb(var(--primaryRgb) / .10); border: 1.5px solid var(--primary);
      color: var(--primaryText); }}
  .au-esito-errore {{ background: var(--yellowBg); border: 1.5px solid var(--yellow);
      color: var(--yellowText); }}
  .au-esito-icona b {{ font-size: 18px; margin: 0; }}
  .st-key-esitoAggAzioni {{ justify-content: flex-end; gap: 10px !important; margin-top: 8px; }}
  .st-key-esitoAggAzioni [class*="st-key-esito"] {{ width: auto !important; flex: none; }}
  .st-key-esitoAggAzioni button {{ height: 38px; padding: 0 18px; white-space: nowrap; }}
  /* 1.5px giu': centrata sul testo della versione, che e' monospazio
     (misurato: l'icona stava 1.5px sopra). */
  .st-key-controllaAgg {{ transform: translateY(1.5px); }}
  .st-key-controllaAgg button {{ min-height: 0 !important; height: 18px; width: 18px;
      padding: 0 !important; color: var(--textSecondary) !important; }}
  .st-key-controllaAgg button:hover {{ color: var(--primaryText) !important; }}
  .st-key-controllaAgg [data-testid="stIconMaterial"] {{ font-size: 14px !important; }}
  /* La tendina della lingua col bordo, come il selettore del tema accanto. */
  .st-key-cLingua [data-testid="stSelectbox"] [data-rac][role="group"] {{
      border: 1px solid var(--borderStrong) !important; border-radius: 8px; }}
  /* «cambiata · di fabbrica …» attaccata all'opzione sopra, non a quella sotto. */
  .au-cambiata {{ margin-top: -11px !important; margin-bottom: 4px; }}
  [data-testid="stElementContainer"]:has(.au-sb-regola) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .au-tessera {{ width: 48px; height: 48px; flex: none; box-sizing: border-box;
      border-radius: 10px; background: rgb(var(--primaryRgb) / .10);
      border: 1px solid rgb(var(--primaryRgb) / .35); display: flex;
      align-items: center; justify-content: center; color: var(--primaryText); }}
  .au-card-titolo {{ font-size: 18px; font-weight: 600; letter-spacing: -.01em;
      color: var(--textPrimary); line-height: 1.3; }}
  .au-card-testo {{ font-size: 13.5px; line-height: 1.55;
      color: var(--textSecondary); margin-top: 6px; }}
  .au-centrata .au-card-testo {{ font-size: 12.5px; margin-top: 3px; }}
  .st-key-cartelleBox {{ background: var(--insetBackground);
      border: 1px solid var(--borderColor); border-radius: 10px;
      padding: 12px 14px; gap: 6px !important; }}
  .au-occhio {{ display: flex; align-items: center; gap: 10px;
      font-size: 10.5px; font-weight: 600; letter-spacing: .1em;
      text-transform: uppercase; color: var(--textTertiary); }}
  .au-osserva {{ display: inline-flex; align-items: center; gap: 6px;
      font: 400 11px var(--mono); letter-spacing: 0; text-transform: none;
      color: var(--primaryText); }}
  .au-osserva span {{ width: 6px; height: 6px; border-radius: 50%;
      background: var(--primary); box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .18); }}
  .st-key-percInput, .st-key-percOutput {{ flex-wrap: nowrap; gap: 10px !important; }}
  .st-key-percInput > div:first-child, .st-key-percOutput > div:first-child {{
      flex: 1 1 auto; min-width: 0; }}
  .st-key-percInput [class*="st-key-"], .st-key-percOutput [class*="st-key-"] {{
      flex: 0 0 auto; width: auto !important; }}
  .au-percorso-grande {{ display: block; overflow: hidden; white-space: nowrap;
      text-overflow: ellipsis; font: 400 13px var(--mono) !important;
      color: var(--textPrimary) !important; background: none !important;
      padding: 0 !important; }}
  /* Percorso e pulsanti centrati sulla stessa linea: il paragrafo che
     Streamlit mette attorno al percorso portava 14px di margine sotto, e il
     testo finiva 7px piu' in alto dei pulsanti (segnalato dall'utente). */
  :is(.st-key-percInput, .st-key-percOutput, [class*="st-key-cCartellaPerc"]) p {{
      margin: 0 !important; }}
  .au-perc {{ display: block; position: relative; min-width: 0; }}
  /* Il fumetto del percorso intero: ancorato a sinistra (un percorso si
     legge dall'inizio), a capo dove serve anche a meta' nome, e aperto
     solo se il percorso e' tagliato. */
  .au-perc .au-bolla, [data-testid="stSidebar"] .au-perc .au-bolla {{
      left: 0; transform: translateY(3px); max-width: 520px;
      font: 400 12px var(--mono); overflow-wrap: anywhere; }}
  [data-testid="stSidebar"] .au-perc .au-bolla {{ max-width: 260px; }}
  .au-perc .au-bolla::before {{ left: 24px; }}
  .au-perc.au-tronco:hover .au-bolla {{ opacity: 1; transform: translateY(0);
      transition: opacity .12s ease 0s, transform .12s ease 0s; }}
  .st-key-percInput button, .st-key-percOutput button {{ height: 34px;
      min-height: 34px; white-space: nowrap; }}
  .st-key-percOutput button {{ height: 30px; min-height: 30px; }}
  .au-freccia {{ display: flex; align-items: center; gap: 10px;
      margin: 4px 0 2px; }}
  .au-freccia span {{ width: 22px; height: 22px; flex: none; box-sizing: border-box;
      border-radius: 50%; background: var(--surfaceHover);
      border: 1px solid var(--borderStrong); display: inline-flex;
      align-items: center; justify-content: center; color: var(--textSecondary); }}
  /* Geometricamente e' gia' al centro, ma il minuscolo monospazio ha il
     suo peso sotto la meta' del riquadro: 1px su lo rimette sull'asse di
     icona e linea (segnalato dall'utente). */
  .au-freccia em {{ font: normal 400 11px var(--mono); color: var(--textSecondary);
      position: relative; top: -1px; }}
  .au-freccia i {{ flex: 1; height: 1px; background: var(--borderColor); }}
  .au-card-nota {{ font-size: 12px; color: var(--textSecondary); }}
  .au-tre {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 20px; margin: 0 -24px; padding: 18px 24px 20px;
      border-top: 1px solid var(--borderColor); }}
  .au-tre .au-occhio {{ margin-bottom: 8px; }}
  .au-tre p {{ margin: 0; font-size: 12.5px; line-height: 1.5;
      color: var(--textCode); }}
  .au-formati {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .au-formati span {{ padding: 2px 8px; border-radius: 999px;
      background: var(--surfaceHover); border: 1px solid var(--borderStrong);
      font: 400 11px var(--mono); color: var(--grayText); }}
  .st-key-tarDaFare {{ padding: 14px; border-radius: 10px; gap: 10px !important;
      background: rgb(var(--primaryRgb) / .06);
      border: 1px solid rgb(var(--primaryRgb) / .35); }}
  .au-tar-testa {{ display: flex; align-items: center; gap: 10px; }}
  .au-tar-testa code, .au-passo-testa code {{ width: 24px; height: 24px; flex: none;
      box-sizing: border-box; border-radius: 50%; border: 1.5px solid var(--idleEdge);
      display: inline-flex; align-items: center; justify-content: center;
      font: 400 12px var(--mono) !important; color: var(--textCode) !important;
      background: none !important; padding: 0 !important; }}
  .au-tar-testa b {{ font-size: 13.5px; font-weight: 600; }}
  .au-tar-testa small, .au-passo-testa small {{ margin-left: auto;
      font: 400 11px var(--mono); color: var(--grayText); padding: 2px 8px;
      border-radius: 999px; background: var(--surfaceHover);
      border: 1px solid var(--borderStrong); white-space: nowrap; }}
  .au-tar-testo {{ margin: 0; font-size: 12.5px; line-height: 1.5;
      color: var(--textSecondary); }}
  .st-key-calibraMac button {{ height: 38px; font-weight: 600; white-space: nowrap; }}
  .st-key-tarFatta > div:first-child {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-tarFatta [class*="st-key-ricalibraMac"] {{ margin-left: auto; width: auto !important; }}
  .st-key-tarFatta {{ padding: 12px 14px; border-radius: 10px; flex-wrap: nowrap;
      background: var(--insetBackground); border: 1px solid var(--borderColor); }}
  .au-tar-fatta {{ display: flex; align-items: center; gap: 12px; }}
  .au-tar-fatta > span:last-child {{ display: flex; flex-direction: column; gap: 3px; }}
  .au-tar-fatta b {{ font-size: 13.5px; font-weight: 600; }}
  .au-tar-fatta code {{ font: 400 11px var(--mono) !important;
      color: var(--greenText) !important; background: none !important; padding: 0 !important; }}
  .au-tar-viva .au-spunta {{ background: rgb(var(--primaryRgb) / .10);
      border-color: var(--primary); color: var(--primaryText); }}
  .au-tar-viva code {{ color: var(--primaryText) !important; }}
  .au-spunta {{ width: 24px; height: 24px; flex: none; box-sizing: border-box;
      border-radius: 50%; background: var(--greenBg); border: 1.5px solid var(--green);
      color: var(--greenText); display: inline-flex; align-items: center;
      justify-content: center; }}
  .au-mac-righe > div {{ padding: 10px 0; }}
  .au-mac-righe > div:not(:last-child) {{ border-bottom: 1px solid var(--borderColor); }}
  .au-mac-val {{ display: block; margin-top: 3px; font: 400 12px var(--mono) !important;
      color: var(--textCode) !important; background: none !important; padding: 0 !important; }}
  .au-mac-righe > div:last-child {{ padding-bottom: 0; }}
  .au-mac-riga {{ display: flex; align-items: center; gap: 10px; }}
  .au-mac-riga b {{ font-size: 13.5px; font-weight: 500; }}
  .au-mac-riga code {{ margin-left: auto; font: 400 12px var(--mono) !important;
      color: var(--textCode) !important; background: none !important; padding: 0 !important; }}
  .au-mac-righe p {{ margin: 3px 0 0; font-size: 12px; line-height: 1.45;
      color: var(--textSecondary); }}
  .au-chip-ok {{ margin-left: auto; display: inline-flex; align-items: center;
      gap: 6px; font: 400 11px var(--mono); color: var(--greenText);
      padding: 2px 8px; border-radius: 999px; background: var(--greenBg);
      border: 1px solid rgb(var(--greenRgb) / .3); white-space: nowrap; }}
  .au-chip-ok span {{ width: 5px; height: 5px; border-radius: 50%; background: var(--green); }}
  .au-passi-titolo {{ margin: 28px 0 10px; }}
  .au-passi {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px; }}
  .au-passo {{ padding: 16px; border-radius: 10px; background: var(--insetBackground);
      border: 1px solid var(--borderColor); }}
  .au-passo-zero {{ border-style: dashed; border-color: var(--borderStrong); }}
  .au-passo-qui {{ border-color: rgb(var(--primaryRgb) / .55);
      background: rgb(var(--primaryRgb) / .06); }}
  .au-passo-qui small {{ background: none; border: 0; padding: 0;
      color: var(--primaryText); }}
  .au-passo-zero small {{ background: none; border: 0; padding: 0;
      font-family: var(--font); color: var(--textSecondary); }}
  .au-passo-fatto small {{ background: none; border: 0; padding: 0;
      font-family: var(--font); color: var(--greenText); }}
  .au-passo-testa {{ display: flex; align-items: center; gap: 8px; }}
  .au-passo-testa code {{ width: auto; height: auto; border: 0; font-size: 11px !important;
      color: var(--textSecondary) !important; }}
  .au-passo-testa b {{ font-size: 14px; font-weight: 600; }}
  .au-passo p {{ margin: 8px 0 0; font-size: 12.5px; line-height: 1.5;
      color: var(--textSecondary); }}
  .au-passo-fatto .au-spunta {{ width: 16px; height: 16px; }}

  [data-testid="stLayoutWrapper"]:has(> .st-key-cartelleCard) {{
      flex: 1 1 auto !important; min-width: 0; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-questoMac) {{
      flex: 0 0 340px !important; width: 340px !important; }}
  .st-key-cartelleCard, .st-key-questoMac {{ height: 100%; box-sizing: border-box; }}
  /* Alte uguali: l'altezza in % non passava attraverso l'involucro di
     Streamlit, e «Questo Mac» da tarato restava 47px piu' corto. */
  .st-key-vuotoGriglia > [data-testid="stLayoutWrapper"] {{ display: flex;
      flex-direction: column; align-self: stretch; }}
  .st-key-vuotoGriglia > [data-testid="stLayoutWrapper"] > :is(.st-key-cartelleCard, .st-key-questoMac) {{
      flex: 1 1 auto; height: auto !important; }}
  .st-key-cartelleBox {{ padding: 12px 14px !important; }}
  .au-titolo-pagina {{ margin-top: 12px; }}
  .au-tre p, .au-tar-testo, .au-mac-righe p, .au-passo p, .au-card-testo {{
      margin-bottom: 0 !important; }}
  [data-testid="stMarkdownContainer"] .au-tre p {{ font-size: 12.5px; }}
  [data-testid="stMarkdownContainer"] p.au-tar-testo {{ font-size: 12.5px; }}
  [data-testid="stMarkdownContainer"] .au-mac-righe p {{ font-size: 12px; }}
  [data-testid="stMarkdownContainer"] .au-passo p {{ font-size: 12.5px; }}
  .st-key-tarDaFare {{ padding: 14px !important; }}
  .st-key-questoMac {{ padding: 20px !important; }}
  .st-key-cartelleCard {{ padding: 24px 24px 0 !important; }}
  /* Il -1rem di Streamlit sotto ogni markdown accorciava i riquadri: il
     contenuto sbordava sul blocco dopo e le distanze del design sparivano. */
  :is(.st-key-cartelleCard, .st-key-questoMac) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .st-key-cartelleBox .au-occhio {{ line-height: 13px; }}
  .st-key-cartelleBox .au-freccia {{ margin: 5px 0 8px; }}
  .st-key-cartelleCard .au-tre {{ margin-top: 8px; }}
  .st-key-vuotoGriglia {{ margin-top: 27px; }}
  .au-titolo-pagina {{ margin-top: 14px; }}
  .au-passi-titolo {{ margin: 12px 0 5px; }}

  /* ===================================================================
     Redesign 1.6 — Sorgenti con i file, e la barra d'azione in fondo.
     =================================================================== */
  .st-key-testaSorgenti {{ flex-wrap: nowrap; gap: 10px !important;
      margin-top: 12px; }}
  .st-key-testaSorgenti > div:first-child {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-testaSorgenti [class*="st-key-"] {{ flex: 0 0 auto; width: auto !important; }}
  .st-key-testaSorgenti .au-titolo-pagina {{ margin-top: 0; }}
  .st-key-testaSorgenti button {{ height: 34px; min-height: 34px;
      white-space: nowrap; }}
  .au-cartella-riga {{ display: flex; align-items: center; gap: 10px;
      margin-top: 4px; font-size: 13px; color: var(--textSecondary); }}
  .au-cartella-riga code {{ font: 400 12px var(--mono) !important;
      color: var(--textCode) !important; background: none !important;
      padding: 0 !important; }}
  .au-fascia-sorgenti {{ display: flex; align-items: center; gap: 10px;
      padding: 0 16px; height: 46px; border-radius: 10px;
      background: var(--surface); border: 1px solid var(--borderColor);
      font-size: 13px; }}
  .au-fascia-sorgenti b {{ font-size: 15px; font-weight: 600; }}
  .au-fascia-sorgenti > i {{ width: 1px; height: 18px; background: var(--borderStrong); }}
  .au-fascia-analisi {{ margin-left: auto; display: inline-flex;
      align-items: center; gap: 10px; font: 400 12px var(--mono);
      color: var(--primaryText); white-space: nowrap; }}
  .au-fascia-analisi .au-barra {{ width: 120px; height: 3px; border-radius: 2px;
      background: rgb(var(--primaryRgb) / .2); overflow: hidden; display: block; }}
  .au-fascia-analisi .au-barra span {{ display: block; height: 100%;
      background: var(--primary); }}
  .au-tag.au-punto::before {{ content: ""; display: inline-block; width: 5px;
      height: 5px; border-radius: 50%; background: currentColor;
      margin-right: 6px; vertical-align: middle; }}
  .au-nota-pagina {{ font-size: 13px; color: var(--textSecondary); }}
  .au-fascia-ciano {{ display: flex; gap: 10px; align-items: flex-start; margin-top: 4px;
      padding: 10px 14px; border-radius: 8px; background: rgb(var(--primaryRgb) / .08);
      border: 1px solid rgb(var(--primaryRgb) / .30); font-size: 13px; line-height: 1.5;
      color: var(--textCode); }}
  .au-fascia-ciano > span:first-child {{ width: 7px; height: 7px; margin-top: 6px; flex: none;
      border-radius: 50%; background: var(--primary);
      box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-fascia-ciano b {{ font-weight: 600; color: var(--primaryText); }}
  .st-key-barraSorgenti {{ position: fixed; bottom: 0; left: 360px; right: 0;
      width: auto !important; z-index: 100; flex-wrap: nowrap;
      gap: 12px !important; padding: 16px 40px;
      background: rgb(var(--bgRgb) / .96); backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border-top: 1px solid var(--borderColor); }}
  .st-key-barraSorgenti > div:first-child {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-barraSorgenti [class*="st-key-vai"] {{ flex: 0 0 auto; width: auto !important; }}
  .st-key-barraSorgenti button {{ height: 40px; min-height: 40px; padding: 0 18px;
      white-space: nowrap; }}
  .st-key-barraSorgenti button p {{ font-size: 14px; font-weight: 600; }}
  .au-barra-testo {{ font-size: 13.5px; color: var(--textCode); }}
  .block-container:has(.st-key-barraSorgenti) {{ padding-bottom: 7rem !important; }}
  /* Le spaziature della testa dei Sorgenti, dichiarate una per una. Il
     -14px di Streamlit sotto ogni markdown annullava il passo di 14px fra
     un blocco e l'altro: il sottotitolo usciva dal suo contenitore (i
     pulsanti si allineavano al titolo, non a lui) e testa, fascia, nota e
     tabella finivano incollate. Ora: testa, 20px, fascia dei file, 10px,
     nota dell'analisi, 28px, intestazione della tabella, 10px, righe. */
  :is(.st-key-testaSorgenti, .st-key-barraSorgenti, .st-key-fasciaAnalisi)
      [data-testid="stMarkdownContainer"],
  [data-testid="stMarkdownContainer"]:has(> .au-fascia-sorgenti) {{
      margin-bottom: 0 !important; }}
  .st-key-barraSorgenti p {{ margin: 0 !important; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-testaSorgenti) {{ margin-bottom: 6px; }}
  .st-key-fasciaAnalisi .au-fascia-ciano {{ margin-top: 0; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasciaAnalisi) {{ margin-top: -4px; }}
  /* Vuota (nessuna analisi in corso) non deve lasciare il suo passo. */
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasciaAnalisi:not(:has(.au-fascia-ciano, .au-avviso))) {{
      display: none; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-intest) {{ margin-top: 14px; }}
  .st-key-intest {{ margin-bottom: -4px !important; }}

  .au-analisi-corso {{ display: flex; align-items: center; gap: 8px;
      font: 400 12px var(--mono); color: var(--primaryText); }}
  .au-analisi-corso span {{ width: 7px; height: 7px; border-radius: 50%;
      background: var(--primary); box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-analisi-barra {{ margin-top: 8px; height: 3px; border-radius: 2px;
      background: rgb(var(--primaryRgb) / .15); overflow: hidden; }}
  .au-analisi-barra span {{ display: block; width: 35%; height: 100%;
      background: var(--primary); animation: au-scorre 1.6s ease-in-out infinite; }}
  @keyframes au-scorre {{ 0% {{ transform: translateX(-100%); }}
      100% {{ transform: translateX(300%); }} }}
  .au-analisi-coda {{ display: flex; align-items: center; gap: 8px;
      font: 400 12px var(--mono); color: var(--textSecondary); }}
  .au-analisi-coda span {{ width: 6px; height: 6px; border-radius: 50%;
      background: var(--dot); }}
  .au-chip-righe {{ display: flex; gap: 6px; margin-top: 6px; }}
  .au-tag.au-ok {{ color: var(--greenText); background: var(--greenBg);
      border: 1px solid rgb(var(--greenRgb) / .3); }}
  /* Niente piu' riga "sollevata" durante l'analisi: il ciano basta. */
  [class*="st-key-riga"]:has(.au-s-corso) {{ transform: none !important;
      margin: 0 !important; box-shadow: none !important;
      background: var(--surface) !important; }}
  [class*="st-key-riga"]:has(.au-analisi-coda) {{ opacity: .7;
      border-left-color: var(--idleEdge) !important; }}
  .au-cartella-riga {{ white-space: nowrap; min-width: 0; }}
  .au-cartella-riga code {{ overflow: hidden; text-overflow: ellipsis;
      min-width: 0; max-width: 520px; }}
  .au-cartella-riga .au-osserva {{ flex: none; }}

  /* ===================================================================
     Redesign 1.6 — Confronto.
     =================================================================== */
  .st-key-fileCard {{ background: var(--surface); border: 1px solid var(--borderColor);
      border-radius: 12px; padding: 18px 20px !important; flex-wrap: nowrap;
      gap: 0 !important; align-items: stretch; margin-top: 12px; }}
  .st-key-campoFile {{ flex: 0 0 auto; width: 420px !important;
      padding-right: 16px; gap: 8px !important; }}
  .st-key-fileCard > div:last-child {{ flex: 1 1 auto; min-width: 0; }}
  .au-stat-file {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      height: 100%; }}
  .au-stat-file > div {{ padding: 0 16px; border-left: 1px solid var(--borderColor);
      display: flex; flex-direction: column; gap: 10px; }}
  .au-stat-file dt {{ display: flex; align-items: center; gap: 6px; white-space: nowrap;
      font-size: 10.5px; font-weight: 600; letter-spacing: .1em;
      text-transform: uppercase; color: var(--textTertiary); }}
  .au-stat-file dd {{ margin: 0; font: 400 18px var(--mono); color: var(--textPrimary); }}
  .au-stat-file dd small {{ font-size: 12px; color: var(--textSecondary); }}
  .au-sez-riga {{ display: flex; align-items: baseline; gap: 12px; margin-top: 20px; }}
  .au-sez-titolo {{ font-size: 18px; font-weight: 600; letter-spacing: -.01em;
      color: var(--textPrimary); white-space: nowrap; }}
  .au-sez-nota {{ font-size: 13px; color: var(--textSecondary); }}
  a.au-guida {{ margin-left: auto; flex: none; display: inline-flex; align-items: center; gap: 5px;
      font-size: 13px; color: var(--primaryText) !important; text-decoration: none; white-space: nowrap; }}
  a.au-guida:hover {{ text-decoration: underline; text-underline-offset: 2px; }}
  [class*="st-key-verdetto"] {{ background: var(--surface); border: 1px solid var(--borderColor);
      border-radius: 12px; padding: 16px 18px 10px !important; gap: 12px !important; }}
  /* Il -14px di Streamlit sotto i markdown incollava il titolo di sezione
     alla sua scheda, e nella scheda di «Trova gli spezzoni» il testo usciva
     dal padding in basso (7px invece di 20) mentre il pulsante restava
     centrato sul riquadro accorciato (segnalato dall'utente). Senza, il
     passo di 14px fra un blocco e l'altro torna quello vero. */
  [data-testid="stMarkdownContainer"]:has(> .au-sez-riga),
  :is([class*="st-key-verdetto"], .st-key-trovaCard, .st-key-testaClip)
      [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-verdettoDubbio {{ background: var(--yellowBg);
      border-color: rgb(var(--yellowRgb) / .35); }}
  .au-verdetto {{ display: flex; gap: 14px; align-items: flex-start; }}
  .au-verdetto-icona {{ width: 32px; height: 32px; flex: none; box-sizing: border-box;
      border-radius: 50%; border: 1.5px solid var(--green); color: var(--greenText);
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700; }}
  .au-verdetto-icona.au-giallo {{ border-color: var(--yellow); color: var(--yellowText); }}
  .au-verdetto-file {{ font: 400 11px var(--mono); color: var(--textSecondary); }}
  .st-key-verdettoDubbio .au-verdetto-file {{ color: var(--yellowText); }}
  .au-verdetto-scelta {{ font-size: 15px; font-weight: 600; margin-top: 2px; }}
  .au-verdetto-motivo {{ font-size: 13px; line-height: 1.45; color: var(--textCode);
      margin-top: 2px; }}
  /* «Come si sceglie»: un cassetto che si apre su una linea sottile, con
     l'etichetta al centro e la freccia che si gira. */
  .st-key-comeScelti [data-testid="stExpander"] details {{ border: 0 !important;
      background: transparent !important; }}
  .st-key-comeScelti summary {{ display: flex; align-items: center; gap: 12px;
      padding: 6px 0 !important; justify-content: center; }}
  .st-key-comeScelti summary::before, .st-key-comeScelti summary::after {{
      content: ""; flex: 1; height: 1px; background: var(--borderColor); }}
  .st-key-comeScelti summary > span {{ flex: none; display: inline-flex;
      flex-direction: row-reverse; align-items: center; gap: 6px; }}
  .st-key-comeScelti summary p {{ font-size: 12.5px !important; font-weight: 500;
      color: var(--textCode); }}
  .st-key-comeScelti summary [data-testid="stIconMaterial"] {{
      transform: rotate(90deg); transition: transform .15s; font-size: 16px; }}
  .st-key-comeScelti details[open] summary [data-testid="stIconMaterial"] {{
      transform: rotate(-90deg); }}
  .au-regole {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px; margin-top: 6px; }}
  .au-regola {{ display: flex; flex-direction: column; gap: 6px; padding: 12px;
      border-radius: 8px; background: var(--insetBackground);
      border: 1px solid var(--borderColor); }}
  .au-regola .au-p-fascia {{ font: 400 11px var(--mono); color: var(--textSecondary); }}
  .au-regola .au-p-mod {{ font-size: 13.5px; font-weight: 600; }}
  .au-regola .au-p-testo {{ font-size: 12.5px; line-height: 1.45; color: var(--textSecondary); }}
  .au-regole-nota {{ font-size: 12px; color: var(--textSecondary); margin: 10px 0 6px; }}
  .st-key-modelli {{ gap: 12px !important; flex-wrap: nowrap; align-items: stretch; }}
  [data-testid="stLayoutWrapper"]:has(> [class*="st-key-mod_"]) {{ flex: 1 1 0 !important;
      min-width: 0; }}
  [class*="st-key-mod_"] {{ height: 100%; box-sizing: border-box; padding: 14px !important;
      gap: 10px !important; border-radius: 10px; background: var(--surface);
      border: 1px solid var(--borderColor); }}
  [class*="st-key-mod_"]:has(input:checked) {{ background: rgb(var(--primaryRgb) / .08);
      border-color: rgb(var(--primaryRgb) / .55); }}
  [class*="st-key-mod_"]:has(input:disabled) {{ opacity: .6; }}
  [class*="st-key-mod_"] [data-testid="stCheckbox"] label p {{ font-size: 14.5px;
      font-weight: 600; color: var(--textPrimary); }}
  [class*="st-key-mod_"] .au-tag {{ align-self: flex-start; }}
  [class*="st-key-mod_"] .au-m-desc {{ font-size: 13px; line-height: 1.5;
      color: var(--textCode); margin: 8px 0 10px; }}
  [class*="st-key-mod_"]:has(input:disabled) .au-m-desc {{ color: var(--textSecondary); }}
  [class*="st-key-mod_"] .au-m-vel {{ font: 400 11.5px var(--mono); color: var(--textCode); }}
  .st-key-testaClip {{ flex-wrap: nowrap; }}
  .st-key-testaClip > div:first-child {{ flex: 1 1 auto; }}
  .st-key-testaClip [class*="st-key-trova"] {{ flex: none; width: auto !important; }}
  .st-key-testaClip .au-sez-riga {{ align-items: center; margin-top: 0; }}
  .st-key-trovaCard {{ padding: 20px !important; border-radius: 12px; flex-wrap: nowrap;
      gap: 20px !important; background: var(--surface);
      border: 1px dashed var(--borderStrong); }}
  .st-key-trovaCard > div:first-child {{ flex: 1 1 auto; }}
  .st-key-trovaCard [class*="st-key-trova"] {{ flex: none; width: auto !important; }}
  .au-trova b {{ font-size: 15px; font-weight: 600; }}
  .au-trova p {{ margin: 6px 0 0; font-size: 13px !important; line-height: 1.5;
      color: var(--textSecondary); }}
  .au-c-motivo {{ font: 400 11px var(--mono); color: var(--textSecondary); }}
  .au-c-prove {{ font-size: 13px; line-height: 1.45; color: var(--textCode); margin-top: 6px; }}
  .st-key-barraConfronto {{ position: fixed; bottom: 0; left: 360px; right: 0;
      width: auto !important; z-index: 100; flex-wrap: nowrap;
      gap: 16px !important; padding: 14px 40px;
      background: rgb(var(--bgRgb) / .96); backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px); border-top: 1px solid var(--borderColor); }}
  .st-key-barraConfronto > div:first-child {{ flex: 1 1 auto; min-width: 0; }}
  .st-key-barraConfronto [class*="st-key-tog_"], .st-key-barraConfronto .st-key-elaboraClip {{
      flex: none; width: auto !important; }}
  .st-key-elaboraClip button {{ height: 40px; padding: 0 20px; white-space: nowrap; }}
  .st-key-barraConfronto > div:has(> .stMarkdown .au-tog-aiuto) {{ flex: none; width: auto !important;
      margin-left: -10px; }}
  .st-key-barraConfronto [data-testid="stMarkdownContainer"]:has(.au-tog-aiuto) {{
      margin-bottom: 0 !important; }}
  .au-tog-aiuto {{ display: flex; align-items: center; color: var(--textTertiary); }}
  .st-key-elaboraClip button p {{ font-size: 14px; font-weight: 600; }}
  .st-key-barraConfronto .au-barra-testo b {{ display: block; font-size: 14px;
      font-weight: 600; color: var(--textPrimary); }}
  .st-key-barraConfronto .au-barra-testo code {{ font: 400 12px var(--mono) !important;
      color: var(--textSecondary) !important; background: none !important; padding: 0 !important; }}
  .block-container:has(.st-key-barraConfronto) {{ padding-bottom: 8rem !important; }}
  .st-key-barraConfronto [data-testid="stFragment"], .st-key-barraConfronto > div:has([data-testid="stFragment"]) {{
      flex: 1 1 auto; }}
  .st-key-provaTesta {{ flex-wrap: nowrap; gap: 14px !important; }}
  .st-key-provaTesta > div:first-child {{ flex: 1 1 auto; }}
  .st-key-provaTesta [class*="st-key-ferma"] {{ flex: none; width: auto !important; }}
  .st-key-ferma_confronto button {{ height: 32px; min-height: 32px;
      border-color: rgb(var(--redRgb) / .55) !important; color: var(--redText) !important;
      background: transparent !important; }}
  .st-key-ferma_confronto_ok button {{ height: 32px; min-height: 32px;
      background: var(--redFill) !important; border: 0 !important; color: var(--onRed) !important; }}
  .au-prova-testa {{ display: flex; align-items: center; gap: 14px; }}
  .au-prova-testa > span {{ width: 7px; height: 7px; border-radius: 50%;
      background: var(--primary); box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-prova-testa b {{ font-size: 14px; font-weight: 600; }}
  .au-prova-testa code {{ font: 400 12px var(--mono) !important; color: var(--primaryText) !important;
      background: none !important; padding: 0 !important; }}
  .au-prova-testa small {{ margin-left: auto; font: 400 12px var(--mono);
      color: var(--textSecondary); }}
  .au-prova-barra {{ height: 6px; border-radius: 3px; overflow: hidden;
      background: rgb(var(--primaryRgb) / .15); margin-top: 10px; }}
  .au-prova-barra span {{ display: block; height: 100%; background: var(--primary); }}
  .au-prova-nota {{ font-size: 12.5px; line-height: 1.45; color: var(--textSecondary);
      margin-top: 8px; }}
  /* La barra del Confronto in corso: il -14px di Streamlit sotto ogni
     markdown la accorciava, e la nota finiva sul bordo della finestra senza
     margine sotto (segnalato dall'utente); Ferma stava piu' in alto della
     riga accanto. Ora: titolo e Ferma centrati, 12px fino alla barra, la
     nota, e il padding della fascia per intero. */
  .st-key-barraConfronto [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-barraConfronto [data-testid="stFragment"] [data-testid="stVerticalBlock"] {{
      gap: 0 !important; }}
  .st-key-provaTesta {{ align-items: center !important; }}
  .st-key-provaTesta .au-prova-testa {{ min-height: 32px; }}
  .st-key-barraConfronto .au-prova-barra {{ margin-top: 12px; }}
  .au-errore {{ padding: 12px 16px; border-radius: 10px; background: var(--redBg);
      border: 1px solid rgb(var(--redRgb) / .35); color: var(--redText);
      font-size: 13px; line-height: 1.5; margin-top: 12px; }}

  .st-key-comeScelti summary > span {{ flex: 0 0 auto !important; width: auto !important;
      display: inline-flex !important; flex-direction: row-reverse !important;
      align-items: center; gap: 6px; }}
  .st-key-campoFile [data-testid="stSelectbox"] [role="group"] {{
      background: var(--insetBackground); border: 1px solid var(--borderStrong);
      border-radius: 8px; min-height: 38px; }}
  .st-key-campoFile [data-testid="stSelectbox"] input {{ font-size: 14px;
      font-weight: 500; }}

  /* Risultati del confronto. */
  .st-key-testaRisultati {{ flex-wrap: nowrap; margin-top: 24px; }}
  .st-key-testaRisultati > div:first-child {{ flex: 1 1 auto; }}
  /* Titolo e sottotitolo dei risultati staccati fra loro e dalla prima
     clip: il -14px sotto il markdown incollava la riga alla scheda. */
  .st-key-testaRisultati [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-testaRisultati .au-sez-nota {{ display: block; margin-top: 6px; }}
  .st-key-risultati {{ gap: 16px !important; }}
  .st-key-finderRisultati {{ flex: none; width: auto !important; }}
  .au-sez-titolo.au-grande {{ font-size: 22px; }}
  .st-key-risultati [data-testid="stExpander"] details {{ background: var(--surface);
      border: 1px solid var(--borderColor); border-radius: 12px; }}
  .st-key-risultati [data-testid="stExpander"] summary p {{ font-size: 13px;
      color: var(--textSecondary); }}
  .st-key-risultati [data-testid="stExpander"] summary p strong {{ font-size: 15px;
      color: var(--textPrimary); margin-right: 8px; }}
  .st-key-risultati [data-testid="stExpander"] summary p code {{ font: 400 12px var(--mono);
      color: var(--textCode); background: none; padding: 0; margin-right: 6px; }}
  .au-res-due {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 28px; }}
  .au-res-due .au-occhio {{ margin-bottom: 10px; }}
  .au-cnf th {{ font-size: 10.5px; color: var(--textTertiary); }}
  .au-cnf td:not(:first-child), .au-cnf th:not(:first-child) {{ text-align: right; }}
  .au-cnf td {{ font: 400 12px var(--mono); }}
  .au-cnf td.au-cnf-nome {{ font: 600 13.5px var(--font); }}
  .au-cnf-nota {{ font-size: 12.5px; line-height: 1.5; color: var(--textSecondary);
      margin-top: 10px; }}
  .au-ind-modello {{ font-size: 13.5px; font-weight: 600; margin: 8px 0 6px; }}
  .au-ind {{ display: grid; grid-template-columns: minmax(130px, max-content) minmax(0, 1fr) 48px;
      align-items: center; gap: 10px; margin: 4px 0; font-size: 12.5px;
      color: var(--textSecondary); }}
  .au-ind i {{ position: relative; height: 6px; border-radius: 3px;
      background: var(--borderStrong); }}
  .au-ind i::after {{ content: ""; position: absolute; left: 25%; top: -3px;
      width: 1px; height: 12px; background: var(--textSecondary); }}
  .au-ind em {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px;
      background: var(--primary); }}
  .au-ind b {{ font: 400 12px var(--mono); color: var(--textCode); text-align: right; }}
  .au-res-sez {{ margin: 18px 0 2px; gap: 12px; }}
  .au-res-sez .au-sez-nota {{ font-size: 12.5px; letter-spacing: 0;
      text-transform: none; font-weight: 400; }}
  [class*="st-key-coppie_"] {{ gap: 8px !important; }}
  [class*="st-key-coppie_"] [class*="st-key-cmp_"] {{ width: auto !important; flex: none; }}
  .au-foglio {{ overflow-x: auto; border-radius: 8px; }}
  .au-foglio img {{ display: block; max-width: none; }}
  [class*="st-key-piedeClip_"] {{ flex-wrap: nowrap; border-top: 1px solid var(--borderColor);
      padding-top: 12px; margin-top: 8px; }}
  [class*="st-key-piedeClip_"] > div:first-child {{ flex: 1 1 auto; }}
  [class*="st-key-piedeClip_"] [class*="st-key-finder_conf"] {{ flex: none; width: auto !important; }}
  [class*="st-key-piedeClip_"] [data-testid="stExpander"] details {{ border: 0 !important;
      background: transparent !important; }}
  [class*="st-key-piedeClip_"] summary {{ padding: 4px 0 !important; }}
  /* «N file · mostra i percorsi» e' un link discreto, non un accordion:
     niente riquadro scuro al passaggio ne' sotto il titolo una volta
     aperto (visti dall'utente), testo secondario che si accende al
     passaggio, e i percorsi allineati al titolo. Il pulsante della
     cartella resta sulla riga del titolo, non a meta' dei percorsi. */
  [class*="st-key-piedeClip_"] summary,
  [class*="st-key-piedeClip_"] summary:hover,
  [class*="st-key-piedeClip_"] details[open] > summary {{
      background: transparent !important; box-shadow: none !important;
      border: 0 !important; }}
  [class*="st-key-piedeClip_"] summary p {{ font-size: 12.5px !important; font-weight: 500;
      color: var(--textSecondary); transition: color .12s; }}
  [class*="st-key-piedeClip_"] summary:hover p {{ color: var(--textPrimary); }}
  [class*="st-key-piedeClip_"] [data-testid="stExpanderDetails"] {{
      padding: 6px 0 2px 24px !important; background: transparent !important; }}
  [class*="st-key-piedeClip_"] {{ align-items: flex-start !important; }}
  .au-barra-pronto {{ display: flex; align-items: center; gap: 14px; }}
  .au-barra-pronto b {{ display: block; font-size: 14px; font-weight: 600; }}
  .au-barra-pronto span:not(.au-spunta) {{ font-size: 12.5px; color: var(--textSecondary); }}
  .st-key-barraConfronto .st-key-tornaClip, .st-key-barraConfronto .st-key-avantiLavorazione {{
      flex: none; width: auto !important; }}
  .st-key-tornaClip button, .st-key-avantiLavorazione button {{ height: 40px; padding: 0 18px;
      white-space: nowrap; }}

  /* ===================================================================
     Redesign 1.6 — Lavorazione.
     =================================================================== */
  .au-sotto-lav {{ max-width: calc(100% - 260px); }}
  /* «Stesso modello per tutti» sta sulla riga del titolo, a destra. */
  .st-key-sceltaTutti {{ position: absolute; right: 0; margin-top: -58px;
      width: 220px !important; z-index: 2; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-sceltaTutti),
  [data-testid="stVerticalBlock"]:has(> [data-testid="stLayoutWrapper"] > .st-key-sceltaTutti) {{
      position: relative; }}
  .st-key-sceltaTutti [role="group"] {{ background: var(--surface);
      border: 1px solid var(--borderStrong); border-radius: 8px; min-height: 38px; }}
  .st-key-barra {{ left: 360px !important; padding: 14px 40px !important;
      background: rgb(var(--bgRgb) / .96) !important; box-shadow: none !important;
      border-top: 1px solid var(--borderColor) !important; }}
  .st-key-barra::before {{ display: none; }}

  /* La riga al lavoro: niente piu' "sollevata" (zoom), un bordo ciano
     intero e un fondo appena velato; dentro, barra, tappe e dettaglio. */
  [class*="st-key-jrow"]:has(.au-tag.au-busy) {{ transform: none !important;
      box-shadow: none !important; border: 1px solid var(--primary) !important;
      border-left-width: 3px !important; background: rgb(var(--primaryRgb) / .05) !important;
      margin: 0 !important; }}
  .au-riga-avanz {{ padding: 4px 0 16px 48px; }}
  .au-riga-testa {{ display: flex; align-items: center; gap: 14px; }}
  .au-riga-testa .au-riga-barra {{ flex: 1; margin: 0; }}
  .au-riga-testa b {{ font: 500 12.5px var(--mono); color: var(--primaryText); }}
  .au-riga-tappe {{ display: flex; align-items: center; gap: 18px; margin-top: 10px;
      font-size: 12.5px; color: var(--textSecondary); }}
  .au-tappa {{ display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }}
  /* Nelle finestre strette le fasi vanno a capo fra l'una e l'altra, mai
     dentro «2 Codifica blocco · CPU». */
  .au-riga-tappe {{ flex-wrap: wrap; row-gap: 6px; }}
  .au-riga-misure {{ white-space: nowrap; }}
  .au-tappa-fatta {{ color: var(--greenText); }}
  .au-tappa-fatta i {{ font-style: normal; }}
  .au-tappa-ora {{ color: var(--textPrimary); font-weight: 600; }}
  .au-punto-ora {{ width: 7px; height: 7px; border-radius: 50%; background: var(--primary);
      box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-tappa + .au-tappa::before {{ content: ""; width: 24px; height: 1px;
      background: var(--borderStrong); margin-right: 12px; }}
  .au-riga-misure {{ margin-left: auto; font: 400 12px var(--mono); color: var(--textCode); }}
  /* ===== La barra del file a quattro tappe (tavola «Z» in Claude Design).
     La barra e' il file intero divisa nelle fette delle tappe; nella fetta
     dell'upscale una lineetta per confine di blocco. Sotto, le tappe con la
     loro fetta e, a destra, le misure della tappa in corso: tutto sulla
     stessa linea di base e della stessa misura, le fette un filo piu'
     piccole. Se la riga non ci sta, la pagina toglie prima numeri e fette
     (`au-s1`), poi il tempo trascorso (`au-s2`). */
  /* 4px e non 2: con larghezze frazionarie lo stacco da 2px veniva
     disegnato a volte pieno e a volte quasi chiuso (visto dall'utente), e
     si confondeva con le lineette dei blocchi. */
  .au-barra-file {{ flex: 1; min-width: 0; overflow: hidden; display: flex; gap: 4px; height: 6px; }}
  .au-seg {{ position: relative; min-width: 14px; height: 100%; border-radius: 3px;
      overflow: hidden; background: rgb(var(--primaryRgb) / .15); }}
  .au-seg > i {{ display: block; height: 100%; background: var(--primary); }}
  .au-seg > b {{ position: absolute; top: 0; bottom: 0; width: 1px;
      background: rgb(var(--bgRgb) / .7); }}
  .au-ferma .au-seg {{ background: var(--sidebar2); }}
  .au-ferma .au-seg > i {{ background: var(--yellow); }}
  .au-ferma .au-riga-testa b {{ color: var(--yellowText); }}
  .au-riga-tappe {{ align-items: baseline !important; flex-wrap: nowrap !important;
      gap: 8px !important; font-size: 12.5px; line-height: 18px; overflow: hidden;
      white-space: nowrap; }}
  .au-tp {{ display: inline-flex; align-items: baseline; gap: 6px; white-space: nowrap; }}
  .au-tp-fatta {{ color: var(--greenText); }}
  .au-tp-ora {{ color: var(--primaryText); font-weight: 600; }}
  .au-ferma .au-tp-ora {{ color: var(--yellowText); }}
  .au-tp-dopo {{ color: var(--textPrimary); }}
  .au-tp-segno {{ display: inline-flex; align-self: center; }}
  .au-fetta {{ font: 400 11px var(--mono); color: var(--textTertiary); }}
  .au-freccia-passo {{ flex: none; align-self: center; margin: 0 2px;
      color: var(--textTertiary); }}
  .au-punto-vivo {{ align-self: center; flex: none; width: 7px; height: 7px;
      border-radius: 50%; background: var(--primary);
      animation: au-respiro 1.8s ease-out infinite; }}
  .au-ferma .au-punto-vivo {{ background: var(--yellow); animation: none;
      box-shadow: 0 0 0 3px rgb(var(--yellowRgb) / .3); }}
  @keyframes au-respiro {{
      0% {{ box-shadow: 0 0 0 0 rgb(var(--primaryRgb) / .55); }}
      70% {{ box-shadow: 0 0 0 7px rgb(var(--primaryRgb) / 0); }}
      100% {{ box-shadow: 0 0 0 0 rgb(var(--primaryRgb) / 0); }} }}
  @media (prefers-reduced-motion: reduce) {{
      .au-punto-vivo {{ animation: none; box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }} }}
  /* Almeno 24px fra l'ultima tappa e le misure: a filo si leggevano come
     un'unica riga («96–100% restano…»), e la riga va considerata piena. */
  .au-riga-tappe .au-riga-misure {{ font-size: 12.5px; white-space: nowrap;
      padding-left: 16px; }}
  .au-mis + .au-mis::before {{ content: " · "; }}
  .au-s1 .au-tp-n, .au-s1 .au-fetta {{ display: none; }}
  .au-s2 .au-m-trascorso {{ display: none; }}
  .au-riga-dett {{ font-size: 12px !important; color: var(--textSecondary) !important; }}
  .au-riga-dett b {{ font-weight: 400; color: var(--textPrimary); }}
  .au-riga-dett {{ margin-top: 10px; padding: 8px 12px; border-radius: 6px;
      background: var(--insetBackground); border: 1px solid var(--borderColor);
      font: 400 11.5px var(--mono); color: var(--textCode); }}
  /* Il riquadro del dettaglio: testo a sinistra, «Mostra il log» a destra
     sulla stessa linea; sotto, il respiro fino al bordo della riga (prima
     il riquadro toccava il fondo, visto dall'utente). */
  .au-riga-dett {{ display: flex; align-items: center; gap: 16px; }}
  .au-riga-dett > span {{ flex: 1; min-width: 0; }}
  a.au-log {{ flex: none; font: 500 12px var(--font); color: var(--textSecondary) !important;
      text-decoration: underline; text-underline-offset: 2px; }}
  a.au-log:hover {{ color: var(--textPrimary) !important; }}
  [class*="st-key-log_"],
  [data-testid="stElementContainer"]:has(> [class*="st-key-log_"]) {{ display: none !important; }}

  .au-riga-avanz {{ padding-right: 18px; box-sizing: border-box; }}
  .st-key-barra [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child
      [data-testid="stHorizontalBlock"] {{ justify-content: flex-end; gap: 10px; }}
  .st-key-barra button {{ min-height: 40px; height: 40px; padding: 0 18px;
      white-space: nowrap; }}
  .st-key-barra button p {{ font-size: 14px; font-weight: 600; }}
  .st-key-pausa_tutto button, [class*="st-key-riprendi_tutto"] button {{
      background: transparent !important; border: 1px solid var(--borderStrong) !important;
      color: var(--textPrimary) !important; }}

  /* Il resoconto di fine coda. */
  .au-fine-testa {{ display: flex; align-items: center; gap: 14px; }}
  .au-fine-testa b {{ display: block; font-size: 20px; font-weight: 600; }}
  .au-fine-testa span {{ font-size: 13px; color: var(--textSecondary); }}
  .au-fine-icona {{ width: 40px; height: 40px; flex: none; box-sizing: border-box;
      border-radius: 50%; background: var(--greenBg); border: 1.5px solid var(--green);
      color: var(--greenText); display: inline-flex; align-items: center;
      justify-content: center; font-weight: 700; }}
  .au-fine-icona.au-giallo {{ background: var(--yellowBg); border-color: var(--yellow);
      color: var(--yellowText); }}
  .au-fine-cifre {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px; margin-top: 18px; }}
  .au-fine-cifre > div {{ padding: 10px 12px; border-radius: 8px;
      background: var(--insetBackground); border: 1px solid var(--borderColor);
      display: flex; flex-direction: column; gap: 6px; }}
  .au-fine-cifre span {{ font-size: 10.5px; font-weight: 600; letter-spacing: .1em;
      text-transform: uppercase; color: var(--textTertiary); }}
  .au-fine-cifre b {{ font: 500 16px var(--mono); }}
  .au-fine-sez {{ display: flex; align-items: center; gap: 8px; margin-top: 10px;
      font-size: 10.5px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase;
      color: var(--textCode); }}
  .au-fine-sez.au-giallo {{ color: var(--yellowText); }}
  .au-fine-sez.au-giallo span {{ width: 6px; height: 6px; border-radius: 50%;
      background: var(--yellow); }}
  [class*="st-key-fineAvviso"], [class*="st-key-fineGuaio"] {{ flex-wrap: nowrap;
      padding: 12px 14px !important; border-radius: 8px; gap: 14px !important;
      align-items: center !important; }}
  [class*="st-key-fineAvviso"] {{ background: var(--yellowBg);
      border: 1px solid rgb(var(--yellowRgb) / .35); }}
  [class*="st-key-fineGuaio"] {{ background: var(--surface); border: 1px solid var(--borderColor); }}
  [class*="st-key-fineAvviso"] > div:first-child, [class*="st-key-fineGuaio"] > div:first-child {{
      flex: 1 1 auto; min-width: 0; }}
  [class*="st-key-fineMostra"] {{ flex: none; width: auto !important; }}
  [class*="st-key-fineMostra"] button {{ min-height: 28px; height: 28px; padding: 0 10px; }}
  [class*="st-key-fineAvviso"] [class*="st-key-fineMostra"] button {{
      border-color: rgb(var(--yellowRgb) / .45) !important; color: var(--yellowText) !important;
      background: transparent !important; }}
  .au-fine-voce b {{ display: flex; align-items: center; gap: 8px; font-size: 13.5px;
      font-weight: 600; }}
  .au-fine-voce span {{ display: block; font-size: 12.5px; line-height: 1.45;
      color: var(--textSecondary); margin-top: 2px; }}
  [class*="st-key-fineAvviso"] .au-fine-voce span {{ color: var(--yellowText); }}
  .au-fine-voce em.au-motivo {{ flex: none; white-space: nowrap; }}
  /* Un riquadro giallo e non solo testo: da solo il colore del testo non
     bastava a farla notare (segnalato dall'utente). */
  .au-tar-nota {{ margin-top: 8px; padding: 7px 10px; border-radius: 8px;
      font-size: 12px; line-height: 1.45; color: var(--yellowText);
      background: var(--yellowBg); border: 1px solid rgb(var(--yellowRgb) / .45); }}
  :is([class*="st-key-fineAvviso"], [class*="st-key-fineGuaio"]) [data-testid="stMarkdownContainer"] {{
      margin-bottom: 0 !important; }}
  .au-motivo {{ font: normal 400 11px var(--mono); padding: 1px 8px; border-radius: 999px;
      border: 1px solid var(--borderStrong); color: var(--textSecondary);
      background: var(--surfaceHover); }}
  .au-motivo-fallito, .au-motivo-difettoso {{ color: var(--redText); background: var(--redBg);
      border-color: rgb(var(--redRgb) / .3); }}
  .au-fine-righe > div {{ display: flex; align-items: center; padding: 9px 0;
      border-bottom: 1px solid var(--borderColor); font-size: 13.5px; }}
  .au-fine-righe > div:last-child {{ border-bottom: 0; }}
  .au-fine-righe span {{ flex: none; white-space: nowrap; }}
  .au-fine-righe code {{ margin-left: auto; font: 400 12px var(--mono) !important;
      color: var(--textCode) !important; background: none !important; padding: 0 0 0 24px !important;
      min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  /* Il titolo e' gia' nel resoconto, accanto all'icona: quello della modale
     resta solo per chi legge con lo screen reader. */
  [role="dialog"]:has(.au-fine-testa) > h2 {{ position: absolute; width: 1px; height: 1px;
      overflow: hidden; clip-path: inset(50%); }}
  .st-key-cFineAzioni {{ flex-wrap: nowrap; gap: 10px !important; margin-top: 8px; }}
  .st-key-cFineAzioni .st-key-fineLog {{ margin-right: auto; }}
  .st-key-cFineAzioni [class*="st-key-fine"] {{ width: auto !important; flex: none; }}
  .st-key-fineLog button {{ text-decoration: underline; color: var(--textSecondary) !important;
      padding: 0; min-height: 0; }}
  .st-key-fineChiudi button, .st-key-fineFinder button {{ height: 38px; padding: 0 16px;
      white-space: nowrap; }}

  /* La finestra della taratura. */
  .au-tar-p {{ font-size: 14px; line-height: 1.55; color: var(--textCode); margin: 0; }}
  .au-tar-p.au-tar-p2t {{ font-size: 13px; color: var(--textSecondary); }}
  .au-tar-tessere {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px; margin: 14px 0; }}
  .au-tar-tessere > div {{ display: flex; flex-direction: column; gap: 4px; padding: 12px;
      border-radius: 8px; background: var(--insetBackground); border: 1px solid var(--borderColor); }}
  .au-tar-tessere b {{ font: 400 16px var(--mono); }}
  .au-tar-tessere span {{ font-size: 12px; color: var(--textSecondary); }}
  .au-tar-mono {{ font: 400 12px var(--mono); color: var(--textSecondary); }}
  .au-box-giallo, .au-box-rosso {{ padding: 10px 12px; border-radius: 8px; font-size: 13px;
      line-height: 1.5; }}
  .au-box-giallo {{ background: var(--yellowBg); border: 1px solid rgb(var(--yellowRgb) / .3);
      color: var(--yellowText); }}
  .au-box-rosso {{ background: var(--redBg); border: 1px solid rgb(var(--redRgb) / .35);
      color: var(--redText); }}
  .st-key-tarAzioni {{ justify-content: flex-end; gap: 10px !important; }}
  .st-key-tarAzioni [class*="st-key-tar"] {{ width: auto !important; flex: none; }}
  .st-key-tarAzioni .st-key-tarLog {{ margin-right: auto; }}
  .st-key-tarAzioni button {{ height: 38px; padding: 0 16px; white-space: nowrap; }}
  /* La taratura nella misura del design: 640px, il passo in piccolo e in
     grigio accanto al titolo, i pulsanti sulla stessa linea. */
  div:has(> [role="dialog"] .au-tar-passo) {{ width: 640px !important; }}
  [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] .au-tar-passo) {{ display: none; }}
  [role="dialog"]:has(.au-tar-passo) h2 {{ align-items: baseline; }}
  [role="dialog"]:has(.au-tar-passo) h2::after {{ font: 400 11.5px var(--mono);
      color: var(--textSecondary); margin-left: 10px; white-space: nowrap; }}
  .st-key-tarAzioni {{ align-items: center; margin-top: 4px; }}
  .st-key-tarCorsaAzioni {{ justify-content: flex-end; align-items: center;
      gap: 10px !important; margin-top: 6px; }}
  /* Il margine di quando era da solo lo abbassava di 6px accanto a «Ferma». */
  .st-key-tarCorsaAzioni .st-key-tarChiudiContinua {{ margin-top: 0; }}
  .st-key-tarCorsaAzioni [class*="st-key-tar"] {{ width: auto !important; flex: none; }}
  .st-key-tarFerma button {{ height: 38px; padding: 0 16px; white-space: nowrap;
      border-color: rgb(var(--redRgb) / .45) !important; color: var(--redText) !important;
      background: transparent !important; }}
  .st-key-tarFerma button p {{ color: var(--redText) !important; }}
  /* Il suo hover, rosso: quello generale delle secondarie lo faceva grigio.
     I :not(.a)... vincono sul selettore lungo della regola generale. */
  [data-testid="stElementContainer"].st-key-tarFerma .stButton button[kind="secondary"]:hover:not(:disabled):not(.a):not(.b):not(.c):not(.d) {{
      background: var(--redBg) !important; border-color: rgb(var(--redRgb) / .7) !important; }}
  [data-testid="stElementContainer"].st-key-tarFerma .stButton button[kind="secondary"]:hover:not(:disabled):not(.a):not(.b):not(.c):not(.d) p {{
      color: var(--redText) !important; }}
  .st-key-tarChiudiContinua {{ align-self: flex-end; width: auto !important; margin-top: 6px; }}
  .st-key-tarChiudiContinua button {{ height: 38px; padding: 0 16px; white-space: nowrap; }}
  .st-key-tarAzioni [data-testid="stElementContainer"] {{ margin: 0 !important; }}
  [role="dialog"]:has(.au-tar-p1) [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  [role="dialog"]:has(.au-tar-p1) [data-testid="stVerticalBlock"] {{ gap: 14px !important; }}
  .au-box-icona {{ display: flex; gap: 9px; align-items: flex-start; }}
  .au-box-icona svg {{ flex: none; margin-top: 2px; }}
  .au-tar-corsa-testa {{ display: flex; align-items: center; gap: 10px; }}
  .au-tar-corsa-testa > span {{ width: 8px; height: 8px; border-radius: 50%;
      background: var(--primary); box-shadow: 0 0 0 4px rgb(var(--primaryRgb) / .2); }}
  .au-tar-corsa-testa b {{ font-size: 15px; font-weight: 600; }}
  .au-tar-corsa-testa code {{ margin-left: auto; font: 400 12.5px var(--mono) !important;
      color: var(--primaryText) !important; background: none !important; padding: 0 !important; }}
  .au-tar-corsa .au-tar-tappe {{ margin-top: 10px; }}
  .au-tar-voce code {{ font: 400 11px var(--mono) !important; color: var(--textTertiary) !important;
      background: none !important; padding: 0 !important; min-width: 16px; text-align: right; }}
  .au-tar-lista {{ grid-auto-flow: column; }}
  .au-tar-lista {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px 24px; padding: 12px 14px; margin: 12px 0; border-radius: 8px;
      background: var(--insetBackground); border: 1px solid var(--borderColor); }}
  .au-tar-voce {{ display: flex; align-items: center; gap: 8px; font-size: 12.5px;
      color: var(--textTertiary); }}
  .au-tar-voce i {{ width: 8px; height: 8px; flex: none; border-radius: 50%; box-sizing: border-box;
      border: 1.5px solid var(--idleEdge); }}
  .au-tar-voce.fatta {{ color: var(--textCode); }}
  .au-tar-voce.fatta i {{ background: var(--green); border: 0; }}
  .au-tar-voce.corso {{ color: var(--textPrimary); font-weight: 600; }}
  .au-tar-voce.corso i {{ background: var(--primary); border: 0;
      box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-tar-ok-testa {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
  .au-tar-ok-testa .au-spunta {{ width: 32px; height: 32px; }}
  .au-tar-ok-testa b {{ display: block; font-size: 15px; font-weight: 600; }}
  .au-tar-ok-testa span:not(.au-spunta) {{ font-size: 12.5px; color: var(--textSecondary); }}
  .au-tar-tab {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .au-tar-tab th {{ font-size: 10.5px; font-weight: 600; letter-spacing: .08em;
      text-transform: uppercase; color: var(--textTertiary); text-align: right;
      padding: 9px 12px; vertical-align: middle; background: var(--surfaceHover);
      border-bottom: 1px solid var(--borderColor); }}
  .au-tar-tab th:first-child, .au-tar-tab td:first-child {{ text-align: left; }}
  .au-tar-tab td {{ padding: 7px 12px; border-bottom: 1px solid var(--rowLine);
      text-align: right; font: 400 12px var(--mono); color: var(--textCode); }}
  .au-tar-tab td:first-child {{ font: 400 13px var(--font); color: var(--textPrimary); }}
  .au-tar-frase {{ font-size: 13px; margin: 12px 0 4px; }}

  .au-tar-corso {{ display: inline-flex; align-items: center; gap: 6px;
      font: 400 11.5px var(--mono); color: var(--primaryText); margin-top: 2px; }}
  .au-tar-corso i {{ width: 6px; height: 6px; border-radius: 50%; background: var(--primary); }}

  /* Il primo avvio: un riquadro al centro, senza sidebar. */
  /* Al centro della finestra, nei due sensi: niente margine a sinistra per
     il pulsante del cassetto, che qui non c'e'. */
  body:has(.st-key-benvenuto) #au-cassetto {{ display: none !important; }}
  .block-container:has(.st-key-benvenuto) {{ padding: 24px 40px !important; min-height: 100vh; display: flex;
      flex-direction: column; justify-content: center; }}
  .block-container:has(.st-key-benvenuto) > * {{ flex: 1 1 auto; display: flex;
      flex-direction: column; justify-content: center; }}
  .st-key-benvenuto {{ max-width: 640px; margin: 0 auto !important; padding: 32px !important;
      border-radius: 14px; background: var(--surface); border: 1px solid var(--borderColor);
      gap: 16px !important; }}
  .au-pa-occhio {{ font: 400 12px var(--mono); color: var(--primaryText); }}
  .au-pa-titolo {{ font-size: 26px; font-weight: 600; letter-spacing: -.02em; margin-top: 6px; }}
  .au-pa-testo {{ font-size: 14px !important; line-height: 1.55; color: var(--textSecondary);
      margin: 8px 0 18px !important; }}
  .au-pa-voci {{ border-radius: 10px; background: var(--insetBackground);
      border: 1px solid var(--borderColor); }}
  .au-pa-voci > div {{ display: flex; gap: 12px; padding: 14px 16px; }}
  .au-pa-voci > div + div {{ border-top: 1px solid var(--borderColor); }}
  .au-pa-voci i {{ width: 8px; height: 8px; margin-top: 6px; flex: none; border-radius: 50%;
      box-sizing: border-box; border: 1.5px solid var(--idleEdge); }}
  .au-pa-voci.au-corso i {{ border: 0; background: var(--primary);
      box-shadow: 0 0 0 3px rgb(var(--primaryRgb) / .2); }}
  .au-pa-voci b {{ display: block; font-size: 14px; font-weight: 600; }}
  .au-pa-voci span {{ font-size: 12.5px; line-height: 1.45; color: var(--textSecondary); }}
  .au-pa-nota {{ font-size: 12.5px !important; line-height: 1.5; color: var(--textSecondary);
      margin: 18px 0 0 !important; }}
  .au-pa-stato {{ display: flex; align-items: center; gap: 10px; font-size: 13.5px; }}
  .au-pa-log {{ font: 400 11.5px var(--mono); color: var(--textCode); padding: 10px 12px;
      border-radius: 8px; background: var(--insetBackground);
      border: 1px solid var(--borderColor); white-space: pre-wrap; margin: 8px 0 0; }}
  /* Il -1rem sotto i markdown di Streamlit incollava il pulsante alla nota
     (segnalato dall'utente): margine azzerato e un po' d'aria sopra la CTA. */
  .st-key-benvenuto [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .st-key-paScarica, .st-key-paRiprova {{ margin-top: 8px; }}
  .st-key-paScarica button, .st-key-paRiprova button {{ height: 40px; padding: 0 20px;
      white-space: nowrap; }}
  .st-key-paScarica button p, .st-key-paRiprova button p {{ font-size: 14px; font-weight: 600; }}

  /* Precisione (confronto con le tavole): chip piu' basse, nomi in
     semibold, righe da 64px come nel design. */
  .au-tag {{ padding: 1px 8px; line-height: 16px; }}
  .au-chip-riga {{ margin-top: 0; }}
  .au-chip-righe {{ margin-top: 6px; }}
  [class*="st-key-riga"] .au-name, [class*="st-key-jrow"] .au-name {{ font-weight: 600; }}
  [class*="st-key-riga"] [data-testid="stHorizontalBlock"] {{ padding-top: 10px !important;
      padding-bottom: 10px !important; }}
  .au-cartella-riga code {{ white-space: nowrap; }}

  /* «Fatto» e' verde, come il bordo della riga conclusa (il blu non lo usa
     nessuno). */
  .au-fatta {{ background: var(--greenBg) !important; border-color: rgb(var(--greenRgb) / .3) !important;
      color: var(--greenText) !important; }}
  .au-finito, [class*="st-key-jrow"]:has(.au-fatta) .au-stima-riga {{ color: var(--greenText); }}
  .st-key-pausa_tutto button p, [class*="st-key-riprendi_tutto"] button p {{
      color: var(--textPrimary) !important; }}
  .st-key-ferma_tutto button {{ background: transparent !important;
      border: 1px solid rgb(var(--redRgb) / .55) !important; }}
  .st-key-ferma_tutto button p {{ color: var(--redText) !important; }}
  .au-sb-titolo {{ flex-wrap: nowrap; white-space: nowrap; }}

  /* ===================================================================
     TAB VERE (1.6.6, studio «W · Study: true tabs» in Claude Design).
     Quattro tab larghe uguali appoggiate sulla linea della testata; quella
     aperta ha il bordo su tre lati, niente bordo sotto (si apre nella
     pagina) e dove i lati toccano la linea curva verso l'esterno.
     Il contorno lo disegna il contenitore del pulsante (::before), fermo
     10px sopra la linea; le due curve le disegna il guscio `.stButton`
     (::before e ::after). Il pulsante stesso tiene il cerchio (::before) e
     il contatore (::after). Lo stato a destra non c'e' piu': con quattro
     tab uguali non ha posto, e ripeteva Lavorazione.
     =================================================================== */
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi) {{ padding-bottom: 0 !important; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi)::after {{ bottom: 0 !important;
      background: var(--borderStrong) !important; }}
  .st-key-fasi [data-testid="stElementContainer"]:has(.au-fasi-stato) {{ display: none !important; }}
  /* Sotto la linea delle tab, una sfumatura del colore della pagina: il
     contenuto che scorre ci passa sotto e svanisce, invece di essere
     tagliato di netto sulla linea — un taglio brutto quando sotto c'e' una
     scheda di un altro colore (segnalato dall'utente). A pagina ferma in
     cima la sfumatura sta sul fondo pagina e non si vede. */
  [data-testid="stLayoutWrapper"]:has(> .st-key-fasi)::before {{ content: "";
      position: absolute; left: 0; right: 0; top: 100%; height: 28px;
      background: linear-gradient(rgb(var(--bgRgb) / .96), rgb(var(--bgRgb) / 0));
      pointer-events: none; }}
  [data-testid="stLayoutWrapper"]:has(> .st-key-passi) {{ flex: 1 1 auto !important;
      width: auto !important; min-width: 0; }}
  .st-key-passi {{ width: 100% !important; padding: 0 10px !important; border: 0 !important;
      border-radius: 0 !important; background: none !important; gap: 4px !important;
      align-items: stretch !important; }}
  /* 4px fra una scheda e l'altra: attaccate, al passaggio non si capiva dove
     finiva l'una e cominciava l'altra (segnalato dall'utente). */
  .st-key-passi > [class*="st-key-passo"] {{ flex: 1 1 0 !important; width: auto !important;
      min-width: 0; position: relative; }}
  .st-key-passi > [class*="st-key-passo"] > .stButton {{ position: relative; }}
  .st-key-passi [class*="st-key-passo"] button,
  .st-key-passi .st-key-passo0 button {{ width: 100% !important; min-height: 58px !important;
      border: 0 !important; border-radius: 10px 10px 0 0 !important;
      padding-right: 40px !important; }}
  .st-key-passi button:disabled {{ padding-right: 14px !important; }}
  /* Al passaggio, anche se chiusa: e' una scheda, deve sembrarlo (chiesto
     dall'utente). Chiusa resta il divieto come puntatore. */
  .st-key-passi button[kind="secondary"]:hover {{
      background-color: var(--tabHover) !important; }}
  /* La scheda aperta: il fondo della pagina, sopra la linea. */
  .st-key-passi button[kind="primary"] {{ background-color: var(--bg) !important;
      position: relative; z-index: 2; }}
  .st-key-passi button[kind="primary"]:hover {{ background-color: var(--bg) !important; }}
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"])::before {{
      content: ""; position: absolute; left: 0; right: 0; top: 0; bottom: 10px; z-index: 3;
      border: 1px solid var(--borderStrong); border-bottom: 0;
      border-radius: 10px 10px 0 0; pointer-events: none; }}
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"]) > .stButton::before,
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"]) > .stButton::after {{
      content: ""; position: absolute; bottom: 0; width: 10px; height: 11px; z-index: 3;
      box-sizing: border-box; background: transparent; pointer-events: none;
      border-bottom: 1px solid var(--borderStrong); }}
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"]) > .stButton::before {{
      left: -9px; border-right: 1px solid var(--borderStrong);
      border-bottom-right-radius: 10px; }}
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"]) > .stButton::after {{
      right: -9px; border-left: 1px solid var(--borderStrong);
      border-bottom-left-radius: 10px; }}
  /* La linea sotto la scheda aperta E sotto i suoi piedi la copre una
     striscia di 1px del colore della pagina: la linea riparte esattamente
     dove finisce ogni curva. Prima la coprivano i piedi col loro fondo, ma il
     fondo segue l'arrotondamento: fuori dalla curva restava un mozzicone di
     linea (in WebKit si vedeva come una seconda riga) e sull'hover della
     scheda accanto il fondo compariva come un quadratino nero (utente). */
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"]) {{ z-index: 2; }}
  .st-key-passi > [class*="st-key-passo"]:has(button[kind="primary"])::after {{
      content: ""; position: absolute; left: -9px; right: -9px; bottom: 0; height: 1px;
      background: var(--bg); z-index: 2; pointer-events: none; }}
  /* Al passaggio l'ultima riga della scheda resta del colore della pagina
     (ci passa la linea): la striscia sotto i piedi non fa scalino. */
  .st-key-passi button[kind="secondary"]:hover {{
      box-shadow: inset 0 -1px 0 var(--bg) !important; }}

  /* ===================================================================
     Confronto in tre passi (tavole CF1-CF4 di Claude Design, 26/10).
     =================================================================== */
  .st-key-confNascosti,
  [data-testid="stElementContainer"]:has(> .st-key-confNascosti),
  [data-testid="stLayoutWrapper"]:has(> .st-key-confNascosti) {{ display: none !important; }}
  /* Le misure delle tavole CF1-CF3: 24px dalle schede ai passi, ~20 fra
     un blocco e l'altro (Streamlit ne mette 16 da se'). */
  .st-key-confPassi {{ flex-wrap: nowrap; gap: 10px !important; margin: 10px 0 6px; }}
  .st-key-fileCard {{ margin-top: 2px !important; margin-bottom: 6px; }}
  [class*="st-key-clip"]:is(.st-key-clip0, .st-key-clip1, .st-key-clip2, .st-key-clip3,
      .st-key-clip4, .st-key-clip5, .st-key-clip6, .st-key-clip7, .st-key-clip8,
      .st-key-clip9, .st-key-clip10, .st-key-clip11, .st-key-clip12, .st-key-clip13,
      .st-key-clip14, .st-key-clip15) {{ padding: 12px !important; }}
  .au-passo-testo {{ margin-bottom: 4px; }}
  .st-key-risultati [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
      padding: 18px !important; }}
  [class*="st-key-coppie_"] {{ margin-bottom: 4px; }}
  .st-key-confPassi > div:first-child {{ flex: 1 1 auto; }}
  .st-key-confPassi [class*="st-key-cambiaTest"], .st-key-confPassi .st-key-finderRisultati {{
      flex: none; width: auto !important; }}
  .st-key-confPassi [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .au-pp-riga {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .au-pp {{ display: inline-flex; align-items: center; gap: 8px; height: 34px;
      box-sizing: border-box; padding: 0 14px 0 6px; border-radius: 999px;
      border: 1px solid var(--borderColor); font-size: 13.5px; font-weight: 500;
      color: var(--textSecondary); text-decoration: none !important; }}
  .au-pp-segno {{ width: 22px; height: 22px; box-sizing: border-box; border-radius: 50%;
      border: 1px solid var(--borderStrong); display: inline-flex; align-items: center;
      justify-content: center; font-size: 12px; font-weight: 600; }}
  .au-pp-nome {{ display: inline-flex; align-items: baseline; gap: 6px; }}
  .au-pp-nome small {{ font: 500 11.5px var(--mono); opacity: .85; }}
  .au-pp-ora {{ background: rgb(var(--primaryRgb) / .12); border-color: rgb(var(--primaryRgb) / .55);
      color: var(--textPrimary); font-weight: 600; }}
  .au-pp-ora .au-pp-segno {{ background: var(--primaryStrong); border: 0; color: var(--onPrimary);
      font-weight: 700; }}
  .au-pp-ora .au-pp-segno.au-pp-gira {{ background: transparent;
      border: 2px solid rgb(var(--primaryRgb) / .25); border-top-color: var(--primary);
      animation: au-giro 1s linear infinite; }}
  @keyframes au-giro {{ to {{ transform: rotate(360deg); }} }}
  .au-pp-fatto {{ background: var(--greenSolid); border-color: var(--greenSolid);
      color: var(--onGreen) !important; font-weight: 600; }}
  .au-pp-fatto .au-pp-segno {{ border: 0; background: color-mix(in srgb, var(--onGreen) 20%, transparent);
      color: var(--onGreen); }}
  a.au-pp-fatto:hover {{ filter: brightness(1.1); }}
  .au-pp-freccia {{ display: inline-flex; color: var(--textTertiary); }}
  .au-pp-nota {{ margin-left: 6px; font-size: 13px; color: var(--textSecondary); }}
  /* Titolo e descrizione del passo: il -14px che Streamlit mette sotto
     ogni markdown incollava la descrizione al contenuto (visto
     dall'utente). Lo spazio sotto e' quello delle tavole. */
  [data-testid="stMarkdownContainer"]:has(.au-passo-titolo),
  [data-testid="stMarkdownContainer"]:has(.au-pp-riga) {{ margin-bottom: 0 !important; }}
  .au-passo-titolo {{ font-size: 22px; font-weight: 600; letter-spacing: -0.015em;
      line-height: 1.3; margin-top: 0; }}
  .au-passo-testo {{ font-size: 13.5px; line-height: 1.55; color: var(--textSecondary);
      margin-top: 4px; }}
  .au-passo-testo b {{ color: var(--textPrimary); font-weight: 600; }}
  .st-key-trovaAltriRiga {{ margin-top: 4px; }}
  .st-key-trovaAltriRiga .st-key-trovaAltri {{ width: auto !important; flex: none; }}
  /* La fascia in basso: due righe vicine, centrate sull'icona e sui
     pulsanti (prima il -14px del markdown le allontanava). */
  .au-barra-due {{ display: flex; align-items: center; gap: 14px; }}
  .au-barra-due > div {{ display: flex; flex-direction: column; gap: 2px; }}
  .au-barra-due b {{ font-size: 14.5px; font-weight: 600; line-height: 1.3; color: var(--textPrimary); }}
  .au-barra-due b em, .au-barra-pronto b em, .au-prova-testa b em {{ font-style: normal;
      font-weight: 400; color: var(--textSecondary); }}
  .au-barra-due span {{ font-size: 13px; line-height: 1.35; color: var(--textSecondary); }}
  .au-barra-due.au-barra-giallo b {{ color: var(--yellowText); }}
  .au-barra-num {{ width: 34px; height: 34px; flex: none; border-radius: 50%;
      background: rgb(var(--primaryRgb) / .12); color: var(--primaryText);
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700; }}
  .au-barra-pronto > div {{ display: flex; flex-direction: column; gap: 2px; }}
  .au-barra-pronto b {{ line-height: 1.3; }}
  .st-key-barraConfronto :is(.st-key-avantiModelli, .st-key-indietroClip, .st-key-indietroClip3,
      .st-key-elaboraClip, .st-key-avantiLavorazione) {{ flex: none; width: auto !important; }}
  /* Una forma sola per le azioni che portano avanti (e per «Indietro»). */
  :is(.st-key-avantiModelli, .st-key-elaboraClip, .st-key-avantiLavorazione,
      .st-key-indietroClip, .st-key-indietroClip3) button {{
      height: 44px !important; min-height: 44px !important; padding: 0 20px !important;
      border-radius: 8px !important; white-space: nowrap; }}
  :is(.st-key-avantiModelli, .st-key-elaboraClip, .st-key-avantiLavorazione) button p {{
      font-size: 14.5px !important; font-weight: 600 !important; }}
  /* Suggerimenti: un accordion vero. Un riquadro solo; l'intestazione su
     una fascia di tono diverso (piu' chiara in scuro, piu' scura in
     chiaro), titolo a sinistra, freccia a destra in giu' da chiuso e in su
     da aperto; al passaggio si schiariscono solo titolo e freccia. */
  :is(.st-key-consigli, .st-key-risultati) [data-testid="stExpander"] details {{
      border: 1px solid var(--borderStrong) !important; border-radius: 10px !important;
      overflow: hidden; background: var(--surface) !important; }}
  :is(.st-key-consigli, .st-key-risultati) [data-testid="stExpander"] summary {{
      background: var(--surfaceHover) !important; padding: 12px 16px !important;
      border-radius: 0 !important; box-shadow: none !important; }}
  :is(.st-key-consigli, .st-key-risultati) [data-testid="stExpander"] summary:hover {{
      background: var(--surfaceHover) !important; }}
  :is(.st-key-consigli, .st-key-risultati) [data-testid="stExpander"] details[open] > summary {{
      border-bottom: 1px solid var(--borderColor) !important; }}
  :is(.st-key-consigli, .st-key-risultati) summary > span {{ display: flex !important;
      flex-direction: row-reverse !important; justify-content: space-between !important;
      width: 100% !important; }}
  :is(.st-key-consigli, .st-key-risultati) summary [data-testid="stIconMaterial"] {{
      transform: rotate(90deg); transition: transform .15s, color .12s;
      color: var(--textSecondary); }}
  /* Streamlit cambia il glifo da solo (chiuso: freccia a destra; aperto:
     in giu'): ruotati, diventano in giu' da chiuso e in su da aperto. */
  :is(.st-key-consigli, .st-key-risultati) details[open] > summary [data-testid="stIconMaterial"] {{
      transform: rotate(180deg); }}
  :is(.st-key-consigli, .st-key-risultati) summary p {{ transition: color .12s; }}
  .st-key-consigli summary p {{ font-size: 14px !important; font-weight: 600; color: var(--textCode); }}
  /* «N file · mostra i percorsi» dentro una clip resta un link discreto:
     la regola dell'accordion qui sopra non deve toccarlo. */
  .st-key-risultati [class*="st-key-piedeClip_"] [data-testid="stExpander"] details {{
      border: 0 !important; background: transparent !important; overflow: visible; }}
  .st-key-risultati [class*="st-key-piedeClip_"] [data-testid="stExpander"] summary,
  .st-key-risultati [class*="st-key-piedeClip_"] [data-testid="stExpander"] details[open] > summary {{
      background: transparent !important; padding: 4px 0 !important; border: 0 !important; }}
  .st-key-risultati [class*="st-key-piedeClip_"] summary > span {{ flex-direction: row !important;
      justify-content: flex-start !important; width: auto !important; }}
  :is(.st-key-consigli, .st-key-risultati) summary:hover p,
  :is(.st-key-consigli, .st-key-risultati) summary:hover [data-testid="stIconMaterial"] {{
      color: var(--textPrimary) !important; }}
  .st-key-consigli [data-testid="stExpanderDetails"] {{ padding: 14px 16px 16px !important; }}
  .st-key-consigli .au-regole {{ display: flex; flex-direction: column; gap: 6px; margin: 0; }}
  .st-key-consigli .au-regola {{ display: grid; grid-template-columns: 130px minmax(0, 1fr);
      grid-template-rows: auto auto; column-gap: 14px; row-gap: 3px; padding: 10px 12px;
      border-color: transparent; background: transparent; }}
  .st-key-consigli .au-regola .au-p-fascia {{ grid-row: 1 / span 2; padding-top: 2px; }}
  .st-key-consigli .au-regola.au-qui {{ background: rgb(var(--primaryRgb) / .08);
      border-color: rgb(var(--primaryRgb) / .35); }}
  .st-key-consigli .au-regola.au-qui .au-p-fascia {{ color: var(--primaryText); }}
  .au-qui-chip {{ margin-left: 8px; font: 500 10.5px var(--mono); padding: 1px 7px;
      border-radius: 999px; color: var(--primaryText); border: 1px solid rgb(var(--primaryRgb) / .55); }}
  .st-key-consigli .au-regole-nota {{ margin: 10px 12px 0; line-height: 1.6; }}
  .st-key-consigli .au-guida {{ margin-left: 4px; }}
  /* Le schede dei modelli: chip sempre nello stesso punto, una riga sola. */
  [class*="st-key-mod_"] .au-m-var {{ font-size: 14.5px; font-weight: 600; line-height: 1.35;
      color: var(--textPrimary); margin: -8px 0 8px 26px; }}
  [class*="st-key-mod_"] .au-tag {{ white-space: nowrap; }}
  .au-tag.au-grigio {{ color: var(--textSecondary); background: transparent;
      border: 1px solid var(--borderStrong); }}
  .st-key-confOriginale {{ padding: 14px 16px; border-radius: 10px; background: var(--surface);
      border: 1px solid var(--borderColor); gap: 2px !important; }}
  .st-key-confOriginale [data-testid="stCheckbox"] label p {{ font-size: 14px; font-weight: 600; }}
  .st-key-confOriginale .au-orig-nota {{ margin-left: 50px; }}
  .st-key-confOriginale [class*="st-key-tog_"] {{ flex: none; width: auto !important; }}
  .st-key-confOriginale [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .au-orig-nota {{ font-size: 12.5px; color: var(--textSecondary); }}
  /* Durante il test: lo spezzone che gira e quelli che aspettano. */
  .au-attesa {{ display: flex; align-items: center; gap: 10px; padding: 14px 18px;
      border-radius: 12px; border: 1px solid var(--borderColor); color: var(--textSecondary);
      margin-top: 4px; }}
  .au-attesa b {{ font-size: 15px; color: var(--textPrimary); }}
  .au-attesa code {{ font: 400 12px var(--mono) !important; background: none !important;
      padding: 0 !important; color: var(--textCode) !important; }}
  .au-attesa span {{ margin-left: auto; font: 400 11.5px var(--mono); }}
  .au-attesa-ora {{ border-style: dashed; border-color: rgb(var(--primaryRgb) / .45); }}
  .au-attesa-ora span {{ color: var(--primaryText); }}
  /* La barra del test intero, con una tacca per versione (o per spezzone)
     e sotto cosa e' fatto e cosa gira. */
  .au-prova-barra.au-con-tacche {{ position: relative; }}
  .au-prova-barra i {{ position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px;
      background: var(--bg); }}
  .au-prova-barra i.au-tacca-fine {{ width: 1px; margin-left: 0; opacity: .7; }}
  .au-seg-righe {{ display: flex; gap: 4px; margin-top: 8px; }}
  .au-seg-righe > div {{ min-width: 0; }}
  .au-seg-righe span {{ display: block; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; font: 400 11.5px var(--mono); color: var(--textTertiary); }}
  .au-seg-righe .au-seg-fatto {{ color: var(--greenText); }}
  .au-seg-righe .au-seg-ora {{ color: var(--primaryText); }}
  .au-prova-nota code {{ font: 400 12px var(--mono) !important; background: none !important;
      padding: 0 !important; color: var(--primaryText) !important; }}
  /* Risultati: due ritagli grandi affiancati. */
  .au-ritaglio-box {{ border-radius: 8px; overflow: hidden; background: var(--clipBg); }}
  .au-ritaglio {{ display: block; width: 100%; height: auto; image-rendering: auto; }}
  .au-ritaglio-nome {{ font-size: 13px; color: var(--textCode); }}
  [class*="st-key-piedeRit_"] {{ gap: 8px !important; flex-wrap: wrap; margin-top: 2px;
      min-height: 30px; }}
  [class*="st-key-piedeRit_"] > div:first-child {{ flex: 1 1 auto; }}
  [class*="st-key-piedeRit_"] [class*="st-key-usa"], [class*="st-key-piedeRit_"] [class*="st-key-annulla"] {{
      flex: none; width: auto !important; }}
  [class*="st-key-piedeRit_"] [class*="st-key-usa"] button {{ height: 30px !important;
      min-height: 30px !important; padding: 0 12px !important; }}
  [class*="st-key-piedeRit_"] [class*="st-key-usa_"] button {{
      border-color: rgb(var(--primaryRgb) / .55) !important; }}
  [class*="st-key-piedeRit_"] [class*="st-key-usa_"] button p {{ color: var(--primaryText) !important; }}
  [class*="st-key-piedeRit_"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  .au-usato {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px;
      color: var(--greenText); }}
  /* «Guarda in movimento»: la nota verde alta quanto il pulsante. */
  [class*="st-key-coppie_"] {{ align-items: center !important; }}
  [class*="st-key-coppie_"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
  [class*="st-key-cmp_"] button {{ height: 38px !important; min-height: 38px !important; }}
  .au-aperto {{ display: inline-flex; align-items: center; height: 38px; box-sizing: border-box;
      padding: 0 14px; border-radius: 6px; background: var(--greenBg);
      border: 1px solid rgb(var(--greenRgb) / .3); color: var(--greenText); font-size: 13px;
      white-space: nowrap; }}
  .au-aperto.au-aperto-no {{ background: var(--redBg); border-color: rgb(var(--redRgb) / .35);
      color: var(--redText); }}
  .au-vc-manca {{ display: flex; flex-direction: column; gap: 3px; padding: 14px 18px;
      border-radius: 10px; background: var(--insetBackground); border: 1px solid var(--borderColor); }}
  .au-vc-manca b {{ font-size: 14px; font-weight: 600; }}
  .au-vc-manca b em {{ font-style: normal; font-weight: 400; color: var(--textSecondary); }}
  .au-vc-manca span {{ font-size: 13px; line-height: 1.6; color: var(--textSecondary); }}
  .au-vc-manca code {{ font: 400 12.5px var(--mono) !important; background: none !important;
      padding: 0 !important; color: var(--textCode) !important; }}
  .au-copia {{ display: inline-flex; vertical-align: middle; margin: 0 2px 0 4px; padding: 3px;
      border-radius: 4px; color: var(--textSecondary); cursor: pointer; }}
  .au-copia:hover {{ color: var(--textPrimary); background: var(--surfaceHover); }}
  .au-copia.au-copiato {{ color: var(--greenText); }}
  /* La tabella dei tempi: tutti i bordi come la riga di mezzo, testo
     centrato in verticale e staccato dai bordi. */
  .au-cnf {{ border: 1px solid var(--borderColor); }}
  .au-cnf th, .au-cnf td {{ padding: 9px 12px !important; vertical-align: middle;
      border: 1px solid var(--borderColor) !important; }}
  /* Gli indicatori: il segno bianco e' il 100% dell'ingrandimento semplice,
     con la sua etichetta sotto. */
  .au-ind i::after {{ display: none; }}
  .au-ind i u {{ position: absolute; left: 25%; top: -4px; width: 2px; height: 14px;
      margin-left: -1px; background: var(--textPrimary); text-decoration: none; }}
  .au-ind-scala {{ margin-top: -2px; }}
  .au-ind-scala i {{ background: transparent; height: 14px; }}
  .au-ind-scala s {{ position: absolute; left: 25%; transform: translateX(-50%);
      text-decoration: none; font: 400 11px var(--mono); color: var(--textTertiary); }}
  /* I pulsanti secondari: in scuro un fondo appena piu' chiaro della
     superficie, o non si leggono come pulsanti (in chiaro resta il bianco). */
  [data-testid="stMain"] .stButton button[kind="secondary"]:not(:disabled) {{
      background: var(--buttonFill); }}
  [data-testid="stMain"] .st-key-passi .stButton button[kind="secondary"] {{ background: transparent; }}
  /* «Usa per tutti i file»: la conferma con l'elenco di cosa cambia. */
  .au-dialogo-titolo {{ font-size: 17px; font-weight: 600; margin-bottom: 4px; }}
  .au-dialogo-testo {{ font-size: 13px !important; line-height: 1.55; color: var(--textSecondary);
      margin: 6px 0 !important; }}
  .au-dialogo-elenco {{ list-style: none; margin: 8px 0 !important; padding: 0 !important; }}
  .au-dialogo-elenco li {{ display: flex; justify-content: space-between; gap: 12px;
      padding: 7px 0; border-bottom: 1px solid var(--borderColor); font-size: 13px; margin: 0 !important; }}
  .au-dialogo-elenco code {{ font: 400 12px var(--mono) !important; background: none !important;
      padding: 0 !important; color: var(--textCode) !important; white-space: nowrap; }}
  /* Le tendine: la freccia mai attaccata al bordo. */
  [data-testid="stSelectbox"] [data-baseweb="select"] > div > div:last-child {{ padding-right: 6px; }}

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
        # File su cui la misura della deduplica e' stata tentata e non si
        # puo' fare (troppo corti): senza ricordarlo, ogni ricarica li
        # rimetteva in coda, per sempre.
        self._non_misurabili: set[str] = set()
        # I file da rifare DA CAPO («Rianalizza tutti»): senza, con
        # l'approfondita accesa il thread prendeva la via della sola misura,
        # che riusa il referto in cassa — e se la misura c'era gia' non
        # rifaceva niente. Il pulsante sembrava non fare nulla (utente).
        self._rifare: set[str] = set()
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
            or (approfondita and r.dedup_campione is None
                and str(p) not in self._non_misurabili)]
        with self._lock:
            for p in da_fare:
                if rifai:
                    self._non_misurabili.discard(str(p))   # si riprova
                    self._rifare.add(str(p))
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
                    da_capo = str(p) in self._rifare
                    self._rifare.discard(str(p))
                if da_capo:
                    # Prima il referto nuovo (senza la misura), poi, se
                    # richiesta, la misura sopra quello nuovo.
                    library.analyse(p, force=True)
                if approfondire:
                    # Riusa il referto gia' in cassa e ci aggiunge la misura:
                    # l'analisi veloce fatta prima non viene rifatta.
                    esito = library.approfondisci(p)
                    with self._lock:
                        self._approfondire.discard(str(p))
                        if esito is None or esito.dedup_campione is None:
                            self._non_misurabili.add(str(p))
                elif not da_capo:
                    library.analyse(p, force=True)
            except Exception:                              # noqa: BLE001
                # Un file illeggibile non deve fermare la coda, ne' tornarci.
                with self._lock:
                    if str(p) in self._approfondire:
                        self._approfondire.discard(str(p))
                        self._non_misurabili.add(str(p))

    @property
    def in_corso(self) -> str | None:
        with self._lock:
            return self._in_corso

    @property
    def in_coda(self) -> set[str]:
        with self._lock:
            return {str(p) for p in self._coda}

    @property
    def prossimo(self) -> str | None:
        """Il primo della fila, quello che parte dopo l'analisi in corso."""
        with self._lock:
            return str(self._coda[0]) if self._coda else None

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
    for lavoro in monitor.lavori(recente=1.0):
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

def _stato_fasi() -> dict:
    """Cosa dice ogni passo della barra, e cosa e' bloccato, adesso.

    Una funzione sola per testata e barre: i numeri devono essere gli stessi
    ovunque compaiano.
    """
    files = load_library()
    n = len(files)
    coda = analizzatore()
    attesa = len(coda.in_coda) + (1 if coda.in_corso else 0)
    fatti = max(0, n - attesa)
    stato: dict = {"vuota": n == 0, "badge": {}, "linea": {}}
    if n == 0:
        stato["Sorgenti"] = t("fasi.sorg_vuota")
    elif attesa:
        stato["Sorgenti"] = t("fasi.sorg_analisi", fatti=fatti, n=n)
        stato["linea"]["Sorgenti"] = fatti / n
        stato["badge"]["Sorgenti"] = attesa
    else:
        stato["Sorgenti"] = tn("fasi.sorg_pronte", n)
        stato["fatta"] = True
    if n == 0:
        stato["Confronto"] = stato["Lavorazione"] = t("fasi.bloccata")
    else:
        stato["Confronto"] = t("fasi.conf_libero")
        stato["Lavorazione"] = t("fasi.lav_libero")
    stato["voce"] = t("fasi.stato_libero")
    stato["attivo"] = False
    conf = confronto.stato()
    if conf and conf.get("state") == confronto.IN_CORSO:
        pct = int(100 * confronto.quota(conf))
        stato["Confronto"] = t("fasi.conf_corso", pct=pct)
        stato["linea"]["Confronto"] = pct / 100
        stato["voce"] = t("fasi.stato_confronto", pct=pct)
        stato["attivo"] = True
    catena = monitor.catena()
    vivo = next((l for l in monitor.lavori(recente=1.0) if l.vivo), None)
    if catena or vivo:
        numero = int((catena or {}).get("numero") or 1)
        totale = int((catena or {}).get("totale") or 1)
        # Lo stesso numero della barra della riga: il file intero, non la
        # fase in corso (vedi `_riempimento`).
        pct = round(100 * _riempimento(vivo)) if vivo and vivo.totale else 0
        stato["Lavorazione"] = t("fasi.lav_corso", numero=numero,
                                 totale=totale, pct=pct)
        # La barretta della scheda e' la CODA, non il file in corso: «File 1
        # di 6 · 99%» con la barra quasi piena sembrava un lavoro quasi
        # finito, mentre ne mancavano cinque (segnalato dall'utente). Il
        # numero accanto resta quello del file.
        stato["linea"]["Lavorazione"] = min(1.0, (max(0, numero - 1) + pct / 100)
                                            / max(1, totale))
        stato["badge"]["Lavorazione"] = max(0, totale - numero) + 1
        stato["voce"] = t("fasi.stato_lavoro", numero=numero, totale=totale)
        stato["attivo"] = True
    elif monitor.pausa() is not None:
        stato["Lavorazione"] = t("fasi.lav_pausa")
        stato["voce"] = t("fasi.lav_pausa")
        stato["attivo"] = True
    if taratura.in_corso():
        stato["voce"] = t("fasi.stato_taratura")
        stato["attivo"] = True
    return stato


def _vai(sezione: str) -> None:
    st.session_state["sezione"] = sezione


def _file_scheda() -> Path:
    return _impostazioni_file().parent / "last-tab.txt"


def _ricorda_scheda(sezione: str) -> None:
    """L'ultima scheda aperta, su disco a OGNI cambio: vale anche dopo una
    chiusura brusca o il riavvio di un aggiornamento."""
    if st.session_state.get("_scheda_scritta") == sezione:
        return
    try:
        _file_scheda().parent.mkdir(parents=True, exist_ok=True)
        _file_scheda().write_text(sezione)
        st.session_state["_scheda_scritta"] = sezione
    except OSError:
        pass


def _scheda_di_avvio() -> str:
    """Dove si apre l'app (deciso con l'utente), la prima regola che vale:
    una coda che gira o un lavoro interrotto da riprendere -> Lavorazione;
    altrimenti l'ultima scheda aperta. (Senza video, e al primo avvio, ci
    pensa gia' chi chiama: Inizio.)"""
    try:
        if monitor.catena() is not None or monitor.lancio_vivo():
            return SEZIONI[2]
        if any(not lv.vivo and 0 < lv.fatti < lv.totale for lv in monitor.lavori(recente=1.0)):
            return SEZIONI[2]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        ultima = _file_scheda().read_text().strip()
    except OSError:
        ultima = ""
    return ultima if ultima in SEZIONI + [INIZIO] else SEZIONI[0]


_LARGHEZZE_PASSI: dict | None = None


def _larghezza_sottotitolo(testo: str) -> float:
    """Quanto e' largo `testo` nel carattere dei sottotitoli dei passi (Inter
    12.5px), in px: misurato carattere per carattere nel browser una volta
    (ui/larghezze_passi.json), cosi' si sa prima di disegnare se ci sta."""
    global _LARGHEZZE_PASSI
    if _LARGHEZZE_PASSI is None:
        try:
            _LARGHEZZE_PASSI = json.loads(
                (Path(__file__).parent / "larghezze_passi.json").read_text())
        except (OSError, ValueError):
            _LARGHEZZE_PASSI = {}
    return sum(float(_LARGHEZZE_PASSI.get(c, 7.5)) for c in testo)


def _regole_sottotitolo(classe: str, testo: str, chiusa: bool,
                        larghezza: int = 230) -> list[str]:
    """Il sottotitolo di un passo: su una riga se ci sta, altrimenti a capo
    dove c'era il «·», che sparisce («File 1 di 2» / «55%»).

    Il CSS non sa togliere un carattere quando la riga si spezza, quindi si
    sceglie qui, prima di disegnare: lo spazio del sottotitolo e' fisso, e
    la larghezza del testo la conosciamo.
    """
    sel = f"{classe} p::after"
    pezzi = testo.split(" · ")
    if len(pezzi) == 1:
        return [f'{sel} {{ content: "{testo}"; }}']
    una = f'{sel} {{ content: "{testo}"; }}'
    due = f'{sel} {{ content: "{"\\A ".join(pezzi)}"; }}'
    serve = _larghezza_sottotitolo(testo) + 2          # un filo di margine
    destra = 14 if chiusa else 40                      # spazio del contatore
    # Ogni passo e' largo 230px a qualunque finestra (250 prima di Inizio,
    # che ha preso il suo posto): sopra i 1360 c'e' posto accanto alla barra
    # laterale, sotto la barra diventa un cassetto e la pagina prende tutta
    # la larghezza (vedi `_cassetto_sidebar`).
    return [una] if serve <= larghezza - 51 - destra else [due]


def header() -> str:
    """La barra dei passi: Sorgenti, Confronto, Lavorazione.

    Si legge come una sequenza (il lavoro ha un ordine) e si usa come delle
    schede (l'ordine non e' obbligato). Ogni passo dice in una riga a che
    punto e'; Confronto e Lavorazione restano chiusi finche' non c'e' niente
    da elaborare (deciso dall'utente). I tre pulsanti sono `st.button`
    perche' le schede di Streamlit non sanno spegnerne una sola: numero,
    lucchetto, sottotitolo e pallino arrivano dal CSS di ogni giro.
    """
    stato = _stato_fasi()
    # La scheda attiva vive anche nell'URL (?scheda=lavorazione): al refresh
    # la sessione muore ma l'indirizzo resta, e la pagina si riapre dov'era.
    dal_url = str(st.query_params.get("scheda") or "").capitalize()
    attiva = (st.session_state.get("sezione")
              or (dal_url if dal_url in SEZIONI + [INIZIO] else
                  INIZIO if stato["vuota"] else _scheda_di_avvio()))
    # Senza video i tre passi sono chiusi, Sorgenti compresa: si sta su
    # Inizio. Arrivati i primi video si passa da soli ai Sorgenti, come
    # faceva la pagina vuota che si riempiva sotto gli occhi.
    if stato["vuota"]:
        attiva = INIZIO
    elif st.session_state.get("era_vuota") and attiva == INIZIO:
        attiva = SEZIONI[0]
    st.session_state["era_vuota"] = stato["vuota"]
    st.session_state["sezione"] = attiva
    _ricorda_scheda(attiva)
    # Le quattro schede si dividono la larghezza in parti uguali: per decidere
    # se un sottotitolo va a capo si conta sulla piu' stretta che capita, una
    # finestra da 1000px (892 di contenuto, 218 a scheda).
    larghezza = 218
    regole = _regole_sottotitolo(".st-key-passo0 button", t("fasi.inizio"), False, larghezza)
    # La taratura da fare o da rifare: un pallino giallo su Inizio, come quello
    # del cassetto. Non si porta l'utente su Inizio a forza (deciso con
    # l'utente): chi non vuole tarare non deve ritrovarcisi a ogni avvio.
    if not stato["vuota"] and _taratura_da_rifare():
        # Sull'icona della casetta, in alto a destra, come quello del
        # cassetto: in fondo alla scheda non si capiva di quale fosse (utente).
        regole.append('.st-key-passo0 button::after { content: ""; display: inline-flex; '
                      'min-width: 0; width: 9px; height: 9px; padding: 0; right: auto; '
                      'left: 31px; top: calc(50% - 14px); transform: none; '
                      'background: var(--yellow); box-shadow: 0 0 0 2px var(--bg); }')
    with st.container(key="fasi", horizontal=True, vertical_alignment="center"):
        with st.container(key="passi", horizontal=True, gap=None):
            st.button(t("tab.Inizio"), key="passo0", on_click=_vai, args=(INIZIO,),
                      type="primary" if attiva == INIZIO else "secondary")
            for i, sezione in enumerate(SEZIONI, start=1):
                chiusa = stato["vuota"]
                classe = f".st-key-passo{i} button"
                st.button(t(f"tab.{sezione}"), key=f"passo{i}",
                          on_click=_vai, args=(sezione,), disabled=chiusa,
                          type="primary" if sezione == attiva else "secondary")
                regole += _regole_sottotitolo(classe, stato[sezione], chiusa, larghezza)
                if chiusa:
                    regole.append(f'{classe}::before {{ content: ""; }}')
                elif i == 1 and stato.get("fatta") and sezione != attiva:
                    regole.append(f'{classe}::before {{ content: "✓"; '
                                  'color: var(--green); '
                                  'border-color: var(--green); }')
                elif i == 1 and stato.get("fatta"):
                    # Aperta resta la spunta, nei colori della scheda attiva:
                    # tornava il numero «1» e sembrava un altro stato (utente).
                    regole.append(f'{classe}::before {{ content: "✓"; }}')
                else:
                    regole.append(f'{classe}::before {{ content: "{i}"; }}')
                if (n := stato["badge"].get(sezione)):
                    regole.append(f'{classe}::after {{ content: "{n if n < 100 else "99+"}"; '
                                  'display: inline-flex; }')
                if (q := stato["linea"].get(sezione)) is not None:
                    # La barretta sotto il sottotitolo: piena fin dove si e'
                    # arrivati, su un binario velato dello stesso colore.
                    # Tre classi davanti: `background: ... !important` in
                    # forma breve (quella delle schede vere, e quella di
                    # ogni pulsante primario) azzera anche l'immagine, e
                    # a pari forza vinceva chi veniva dopo — la barretta non
                    # si vedeva piu' (segnalato dall'utente).
                    regole.append(
                        f'.st-key-fasi .st-key-passi {classe} {{ background-image: linear-gradient(var(--primary), '
                        'var(--primary)), linear-gradient(rgb(var(--primaryRgb) / .2), '
                        'rgb(var(--primaryRgb) / .2)) !important; background-size: '
                        f'calc((100% - 91px) * {q:.3f}) 2px, calc(100% - 91px) 2px '
                        '!important; background-position: 51px calc(100% - 6px) '
                        '!important; background-repeat: no-repeat !important; }')
        st.markdown(f"<div class='au-fasi-stato{' au-vivo' if stato['attivo'] else ''}'>"
                    f"<span></span>{esc(stato['voce'])}</div>",
                    unsafe_allow_html=True)
    st.markdown("<style>" + "".join(regole) + "</style>", unsafe_allow_html=True)
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
        # Il comando di installazione di video-compare: un clic lo copia.
        "D.addEventListener('click',e=>{"
        "const c=e.target.closest&&e.target.closest('[data-copia]');if(!c)return;"
        "e.preventDefault();const W=window.parent;"
        "(W.navigator.clipboard?W.navigator.clipboard.writeText(c.dataset.copia):Promise.reject())"
        ".then(()=>{c.classList.add('au-copiato');setTimeout(()=>c.classList.remove('au-copiato'),1500);})"
        ".catch(()=>{});},true);"
        "}</script>", height=1)
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
    # Un controllo su GitHub a ogni avvio, spegnibile: e' l'unica connessione
    # che AnimeUp fa da solo dopo il primo avvio.
    "aggiornamenti": True,
    # Sistema, Scuro o Chiaro (vedi `animeup.tema`).
    "tema": "system",
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
    if dati.get("tema") in tema.SCELTE:
        puliti["tema"] = dati["tema"]
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
    for lav in monitor.lavori(recente=1.0):
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
    # Fra un gruppo di modelli e l'altro c'e' gia' un resoconto su disco, ma
    # la coda non e' finita: il resoconto vero arriva alla fine.
    if monitor.lancio_vivo() or monitor.catena() is not None:
        return None
    lancio = monitor.ultimo_lancio()
    if not lancio or not lancio.get("fine"):
        return None
    try:
        visto = float(_lancio_visto_file().read_text().strip())
    except (OSError, ValueError):
        visto = 0.0
    if float(lancio["fine"]) <= visto:
        return None
    # Un lancio in cui ogni file era gia' finito («Niente da fare»): non c'e'
    # niente da riassumere, e una modale «0 di N» con la spunta verde mente.
    presenti = set(lancio.get("presenti") or [])
    if not (any(n not in presenti for n in lancio.get("previsti") or [])
            or lancio.get("scartati") or lancio.get("riusciti")):
        _segna_lancio_visto(lancio)
        return None
    return lancio


def _non_avviati(lancio: dict) -> list[str]:
    """I file del lancio che nessun gruppo ha mai cominciato.

    Fermata la coda nella pausa prima del secondo file, o nel primo gruppo di
    una catena per modello, gli altri non comparivano in nessuna lista: il
    resoconto diceva «1 di 1» con la spunta verde. L'elenco intero sta nel
    marcatore `.launch` scritto all'avvio.
    """
    visti = set()
    for chiave in ("riusciti", "falliti", "interrotti", "scartati", "presenti"):
        visti.update(lancio.get(chiave) or [])
    tutti = list(lancio.get("previsti") or [])
    try:
        marcatore = json.loads((PATHS.work / ".launch").read_text())
        if marcatore.get("label") == lancio.get("lancio"):
            tutti += [n for n in marcatore.get("files") or [] if n not in tutti]
    except (OSError, ValueError, AttributeError):
        pass
    return [n for n in tutti if n not in visti]


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
    la selezione. Gli avvisi si dicono file per file (vengono dalla pagella
    di ciascuno) e restano gialli; i file non completati si elencano col
    motivo, e solo un fallimento vero e' rosso.
    """
    riusciti = list(lancio.get("riusciti") or [])
    # "Non completati" sono QUATTRO cose diverse: falliti, non pianificabili,
    # fermati a mano col Ferma per-file, e mai cominciati (la coda fermata
    # prima che ci arrivasse).
    difettosi = set(lancio.get("difettosi") or [])
    falliti = [(n, "difettoso" if n in difettosi else "fallito")
               for n in lancio.get("falliti") or []]
    falliti += [(n, "fermato") for n in lancio.get("interrotti") or []]
    falliti += [(n, "scartato") for n in lancio.get("scartati") or []]
    falliti += [(n, "non_avviato") for n in _non_avviati(lancio)]
    presenti = set(lancio.get("presenti") or [])
    previsti = [n for n in (lancio.get("previsti") or []) if n not in presenti]
    previsti += [n for n, m in falliti if m == "non_avviato" and n not in previsti]
    previsti = previsti or riusciti + [n for n, _m in falliti]
    n_ok, n_tot = len(riusciti), len(previsti)
    secondi = float(lancio.get("secondi") or 0)
    orologio = float(lancio.get("fine") or 0) - float(lancio.get("inizio") or 0)
    # Gli avvisi di ciascun file, dalla sua pagella.
    esiti = monitor.esiti()
    con_avvisi = []
    for nome in riusciti:
        esito = esiti.get(monitor.chiave_nome(nome)) or {}
        if esito.get("avvisi"):
            con_avvisi.append((nome, list(esito["avvisi"])))
    n_avvisi = sum(len(a) for _n, a in con_avvisi) or int(lancio.get("avvisi") or 0)

    quando = ""
    if lancio.get("inizio") and lancio.get("fine"):
        da = time.localtime(lancio["inizio"])
        a = time.localtime(lancio["fine"])
        # Una maratona che passa la mezzanotte: il giorno compare solo quando
        # serve a capire.
        # Una notte di cambio d'ora fa finire "prima" di cominciare: allora
        # gli orari portano il fuso.
        ora = '%H:%M %Z' if da.tm_isdst != a.tm_isdst else '%H:%M'
        if (da.tm_year, da.tm_yday) == (a.tm_year, a.tm_yday):
            quando = t("lav.fine_orari", inizio=time.strftime(ora, da),
                       fine=time.strftime(ora, a))
        else:
            giorno = t("lav.fmt_giorno")
            quando = t("lav.fine_giorni_diversi",
                       giorno_inizio=time.strftime(giorno, da),
                       inizio=time.strftime(ora, da),
                       giorno_fine=time.strftime(giorno, a),
                       fine=time.strftime(ora, a))
    sotto = (tn("lav.fine_sotto_avvisi", len(con_avvisi), n=n_ok, totale=n_tot, a=len(con_avvisi))
             if con_avvisi else t("lav.fine_sotto", n=n_ok, totale=n_tot))
    icona = (f"<span class='au-fine-icona au-giallo'>!</span>" if falliti else
             f"<span class='au-fine-icona'>{_svg(_I_SPUNTA, 16, 2.4)}</span>")
    respiro = orologio - secondi
    cifre = [(t("lav.fine_lavorazione"), stima_hm(secondi))]
    if n_ok > 1:
        cifre.append((t("lav.fine_per_file"), stima_hm(secondi / n_ok)))
    if respiro > 90:
        cifre.append((t("lav.fine_pause"), stima_hm(respiro)))
    st.markdown(
        f"<div class='au-fine-testa'>{icona}<div><b>{t('lav.fine_titolo')}</b>"
        f"<span>{_pezzi(sotto + (' · ' + quando if quando else ''))}</span></div></div>"
        "<div class='au-fine-cifre'>" + "".join(
            f"<div><span>{esc(k)}</span><b>{esc(v)}</b></div>" for k, v in cifre)
        + "</div>", unsafe_allow_html=True)

    def _chiudi() -> None:
        # Il segno vive su disco per sopravvivere ai riavvii; il doppione in
        # sessione (`fine_vista`) e' il paracadute se i registri non sono
        # scrivibili.
        _segna_lancio_visto(lancio)
        st.session_state["fine_da_mostrare"] = None

    def _mostra(nome: str) -> None:
        # Un pulsante dentro la modale ridisegna SOLO la modale (e' un
        # fragment): con `on_click` il clic registrava la riga da mostrare
        # ma la pagina non si ridisegnava mai, e «Mostra» sembrava non fare
        # niente (segnalato dall'utente). Il giro intero si chiede qui.
        st.session_state["scorri_riga"] = nome
        st.session_state["sezione"] = SEZIONI[2]
        _chiudi()
        st.rerun()

    if con_avvisi:
        quanti_file = len(con_avvisi)
        st.markdown(
            "<div class='au-fine-sez au-giallo'><span></span>"
            + (t("lav.fine_avvisi_su_uno", a=n_avvisi) if quanti_file == 1
               else t("lav.fine_avvisi_su", a=n_avvisi, f=quanti_file))
            + "</div>", unsafe_allow_html=True)
        for i, (nome, avvisi) in enumerate(con_avvisi[:4]):
            with st.container(key=f"fineAvviso{i}", horizontal=True):
                st.markdown(f"<div class='au-fine-voce'><b>{esc(nome)}</b>"
                            f"<span>{esc(' '.join(str(a) for a in avvisi))}</span></div>",
                            unsafe_allow_html=True)
                if st.button(t("lav.fine_mostra"), key=f"fineMostraA{i}"):
                    _mostra(nome)
    if falliti:
        st.markdown(f"<div class='au-fine-sez'>{tn('lav.fine_non_completati', len(falliti))}</div>",
                    unsafe_allow_html=True)
        # Cinque si mostrano tutti: «e altri 1» al posto dell'ultima voce non
        # risparmiava niente.
        mostrati = falliti if len(falliti) <= 5 else falliti[:4]
        for i, (nome, motivo) in enumerate(mostrati):
            with st.container(key=f"fineGuaio{i}", horizontal=True):
                st.markdown(
                    f"<div class='au-fine-voce'><b><em class='au-motivo au-motivo-{motivo}'>"
                    f"{t('lav.fine_motivo_' + motivo)}</em>{esc(nome)}</b>"
                    f"<span>{t('lav.fine_testo_' + motivo)}</span></div>",
                    unsafe_allow_html=True)
                if st.button(t("lav.fine_mostra"), key=f"fineMostraG{i}"):
                    _mostra(nome)
        if len(falliti) > len(mostrati):
            st.markdown(f"<div class='au-fine-quando'>"
                        f"{tn('lavb.e_altri', len(falliti) - len(mostrati))}</div>",
                        unsafe_allow_html=True)
    righe = []
    if lancio.get("dedup_medio") is not None:
        righe.append((t("lav.fine_dedup"),
                      f"{float(lancio['dedup_medio']):.1%}".replace(".", t("lav.fmt_decimale"))))
    uscita = Path(lancio.get("output") or PATHS.output)
    righe.append((t("lav.fine_salvati"), _breve(uscita)))
    st.markdown("<div class='au-fine-righe'>" + "".join(
        f"<div><span>{esc(k)}</span><code title='{esc(v)}'>{esc(v)}</code></div>"
        for k, v in righe)
        + "</div>", unsafe_allow_html=True)

    with st.container(key="cFineAzioni", horizontal=True, vertical_alignment="center"):
        if st.button(t("lav.fine_log"), key="fineLog", type="tertiary"):
            subprocess.run(["open", str(uscita / "logs")], check=False)
        if st.button(t("lav.chiudi"), key="fineChiudi"):
            _chiudi()
            st.rerun()
        if st.button(t("lav.fine_apri"), key="fineFinder", type="primary"):
            subprocess.run(["open", str(uscita)], check=False)
            _chiudi()
            st.rerun()

    # I palloncini SOLO quando e' andato tutto bene, una volta sola.
    if not falliti and n_ok and not st.session_state.get("fine_festeggiata"):
        st.session_state["fine_festeggiata"] = True
        st.balloons()


# Il titolo della modale si traduce a ogni apertura: `@st.dialog("...")` in
# testa alla funzione lo fisserebbe nella lingua attiva all'avvio. Il
# frammento della modale resta lo stesso (Streamlit lo riconosce dal nome
# della funzione del contenuto), quindi i rerun interni non cambiano.
def _modale_fine_coda(lancio: dict) -> None:
    # «medium» (750px) e non la predefinita da 500: i nomi dei file di una
    # serie sono lunghi, e a 500px ogni voce andava su tre righe con la
    # chip spezzata in due (segnalato dall'utente).
    st.dialog(t("lav.fine_titolo"), width="medium")(_contenuto_fine_coda)(lancio)


def _contenuto_taratura() -> None:
    """La taratura in tre passi: cosa fa, il cronometro, i risultati.

    Gira in un processo suo (`animeup calibrate --background`): la finestra si puo'
    chiudere e riaprire, e un ricaricamento non la ferma. Qui si legge solo
    il suo file di stato.
    """
    s = taratura.stato_fondo()
    stato = (s or {}).get("state")
    if st.session_state.get("tar_vedi") and stato != taratura.IN_CORSO:
        ultimi = _ultimi_risultati()
        if ultimi:
            _taratura_esito(ultimi, passo=False)
            return
    st.session_state.pop("tar_vedi", None)
    if stato == taratura.IN_CORSO:
        st.markdown("<span class='au-tar-passo au-tar-p2'></span>", unsafe_allow_html=True)
        _taratura_viva()
        with st.container(key="tarCorsaAzioni", horizontal=True):
            # Fermarla non salva niente: i numeri di prima restano.
            # Ferma e chiude: non c'e' niente da guardare dopo (detto
            # dall'utente). Lo stato resta «interrotta, vista»: la prossima
            # apertura riparte dall'inizio.
            if st.button(t("lav.tar_ferma"), key="tarFerma"):
                taratura.ferma_fondo()
                _chiudi_taratura()
                st.rerun()
            if st.button(t("lav.tar_chiudi_continua"), key="tarChiudiContinua"):
                _chiudi_taratura()
                st.rerun()
        return
    # Interrotta senza un errore vero (fermata, o AnimeUp chiuso a meta'):
    # si riparte dall'inizio, senza una schermata d'errore da chiudere.
    if stato == taratura.INTERROTTA and not (s or {}).get("error") and not s.get("seen"):
        _taratura_vista()
        stato = None
    if stato in (taratura.FINITA, taratura.FALLITA, taratura.INTERROTTA) and not s.get("seen"):
        if stato == taratura.FINITA:
            _taratura_esito(s)
        else:
            _taratura_fallita(s)
        return
    _taratura_intro()


def _taratura_vista() -> None:
    s = taratura.stato_fondo() or {}
    s["seen"] = True
    taratura.scrivi_stato(s)


def _taratura_intro() -> None:
    st.markdown("<span class='au-tar-passo au-tar-p1'></span>", unsafe_allow_html=True)
    try:
        n_misure = len(taratura.preventivo())
    except (OSError, ValueError, subprocess.CalledProcessError):
        n_misure = 11
    st.markdown(
        f"<p class='au-tar-p'>{t('lav.tar_intro')}</p>"
        "<div class='au-tar-tessere'>"
        f"<div><b>{t('lav.tar_t1')}</b><span>{t('lav.tar_t1b')}</span></div>"
        f"<div><b>{t('lav.tar_t2')}</b><span>{t('lav.tar_t2b')}</span></div>"
        f"<div><b>{t('lav.tar_t3', n=n_misure)}</b><span>{t('lav.tar_t3b')}</span></div>"
        "</div>"
        f"<p class='au-tar-p au-tar-p2t'>{t('lav.tar_intro_dettagli')}</p>",
        unsafe_allow_html=True)
    voce = taratura.carica()
    if voce:
        import datetime
        quando = datetime.datetime.fromtimestamp(voce["quando"]).strftime(t("fmt.data_ora"))
        st.markdown(f"<div class='au-tar-mono'>{t('sb.taratura_ultima', quando=quando)}</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='au-tar-mono'>{t('lav.tar_mai')}</div>", unsafe_allow_html=True)
    occupata = (any(l.vivo for l in monitor.lavori(recente=1.0)) or monitor.catena() is not None
                or monitor.pausa() is not None or confronto.in_corso())
    if occupata:
        st.markdown(f"<div class='au-box-rosso au-box-icona'>{_svg(_I_INFO, 15, 2)}"
                    f"<span>{t('lav.tar_occupata')}</span></div>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='au-box-giallo au-box-icona'>{_svg(_I_ATTENZIONE, 15, 2)}"
                    f"<span>{t('lav.tar_prima')}</span></div>",
                    unsafe_allow_html=True)
    with st.container(key="tarAzioni", horizontal=True):
        if st.button(t("lav.chiudi") if occupata else t("lav.tar_non_ora"), key="tarNonOra"):
            _chiudi_taratura()
            st.rerun()
        if st.button(t("lav.tar_avvia"), type="primary", key="tarAvvia", disabled=occupata):
            taratura.avvia_fondo()
            st.rerun(scope="fragment")


@st.fragment(run_every=2)
def _taratura_viva() -> None:
    """Il cronometro, riletto ogni due secondi dal file di stato."""
    s = taratura.stato_fondo() or {}
    if s.get("state") != taratura.IN_CORSO:
        # Finita (o fallita) mentre si guardava: si ridisegna la finestra.
        st.rerun()
        return
    tappe = s.get("steps") or []
    try:
        nomi = taratura.nomi_tappe()
    except Exception:                                  # noqa: BLE001
        nomi = []
    if len(nomi) == len(tappe):
        tappe = [[nome, costo] for nome, (_vecchio, costo) in zip(nomi, tappe)]
    indice_ora = int(s.get("index") or 0)
    etichetta = (tappe[indice_ora - 1][0] if 1 <= indice_ora <= len(tappe)
                 else s.get("label") or t("lav.tar_preparazione"))
    indice = int(s.get("index") or 0)
    totale = int(s.get("total") or len(tappe) or 1)
    quota = float(s.get("fraction") or 0)
    resta = s.get("left")
    pesi = [float(c) for _n, c in tappe] if tappe else [1.0] * totale
    segmenti = []
    for n, peso in enumerate(pesi, start=1):
        classe = "fatta" if n < indice else "corso" if n == indice else ""
        segmenti.append(f"<span class='{classe}' style='flex:{peso:.3f}'></span>")
    voci = []
    for n, (nome, _c) in enumerate(tappe, start=1):
        classe = "fatta" if n < indice else "corso" if n == indice else ""
        voci.append(f"<div class='au-tar-voce {classe}'><i></i><code>{n}</code>{esc(nome)}</div>")
    manca = (f" · {tn('lav.tar_resta', max(1, round(float(resta) / 60)))}"
             if resta is not None else "")
    st.markdown(
        "<div class='au-tar-corsa'>"
        f"<div class='au-tar-corsa-testa'><span></span><b>{t('lav.tar_in_corso')}</b>"
        f"<code>{quota:.0%}{manca}</code></div>"
        f"<div class='au-tar-tappe'>{''.join(segmenti)}</div>"
        f"<div class='au-tar-stato'>{esc(etichetta)}"
        f"{f' ({indice}/{totale})' if indice else ''}</div>"
        # Colonna per colonna, come si legge: prima tutta la prima, poi la
        # seconda; e numerate, come il «(6/11)» sotto la barra.
        f"<div class='au-tar-lista' style='grid-template-rows: repeat({(len(voci) + 1) // 2}, auto)'>"
        f"{''.join(voci)}</div>"
        f"<p class='au-tar-p'>{t('lav.tar_chiudibile')}</p></div>",
        unsafe_allow_html=True)


def _taratura_esito(s: dict, passo: bool = True) -> None:
    st.markdown("<span class='au-tar-passo au-tar-p3'></span>" if passo else
                "<span class='au-tar-passo au-tar-vista'></span>", unsafe_allow_html=True)
    nuova = s.get("new") or {}
    prima = s.get("previous") or {}
    import datetime
    quando = datetime.datetime.fromtimestamp(
        float(nuova.get("quando") or s.get("ended") or time.time())).strftime(t("fmt.data_ora"))

    def _scarto(nuovo, riferimento):
        if not (nuovo and riferimento):
            return "—"
        return f"{(nuovo / riferimento - 1) * 100:+.0f}%"

    righe = []
    for chiave, modello in CATALOG.items():
        for scala in modello.scales:
            fab = modello.throughput.get(scala)
            pre = prima.get("mpxs", {}).get(chiave, {}).get(str(scala))
            nuo = nuova.get("mpxs", {}).get(chiave, {}).get(str(scala))
            righe.append((f"{modello.short} x{scala}", f"{fab:.2f}" if fab else "—",
                          f"{pre:.2f}" if pre else "—", f"{nuo:.2f}" if nuo else "—",
                          _scarto(nuo, pre or fab)))
    # La seconda misura, sui fotogrammi 1080p: nessun valore di fabbrica.
    for chiave, modello in CATALOG.items():
        if 2 not in modello.scales:
            continue
        pre = (prima.get("mpxs_grande") or {}).get(chiave, {}).get("2")
        nuo = (nuova.get("mpxs_grande") or {}).get(chiave, {}).get("2")
        if pre or nuo:
            righe.append((f"{modello.short} x2 · 1080p", "—",
                          f"{pre:.2f}" if pre else "—", f"{nuo:.2f}" if nuo else "—",
                          _scarto(nuo, pre)))
    pre_e, pre_c = prima.get("estrazione_fps"), prima.get("codifica_fps")
    righe.append((t("lav.tar_estrazione"), "60 f/s", f"{pre_e:.0f} f/s" if pre_e else "—",
                  f"{nuova.get('estrazione_fps', 0):.0f} f/s",
                  _scarto(nuova.get("estrazione_fps"), pre_e or 60.0)))
    righe.append((f"{t('lav.tar_codifica')} (1080p)", "8.0 f/s",
                  f"{pre_c:.1f} f/s" if pre_c else "—",
                  f"{nuova.get('codifica_fps', 0):.1f} f/s",
                  _scarto(nuova.get("codifica_fps"), pre_c or 8.0)))
    tabella = (
        "<table class='au-tar-tab'><thead><tr>"
        f"<th>{t('lav.tar_col_misura')}</th><th>{t('lav.tar_col_fabbrica')}</th>"
        f"<th>{t('lav.tar_col_precedente')}</th><th>{t('lav.tar_col_nuova')}</th>"
        f"<th>{t('lav.tar_col_scarto')}</th></tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in righe)
        + "</tbody></table>")
    frase = taratura.frase_salvataggio(nuova) or ""
    st.markdown(
        f"<div class='au-tar-ok-testa'><span class='au-spunta'>{_svg(_I_SPUNTA, 16, 2.4)}</span>"
        f"<div><b>{t('lav.tar_salvata_il', quando=quando)}</b>"
        f"<span>{t('lav.tar_salvata_nota')}</span></div></div>{tabella}"
        + (f"<div class='au-tar-frase'>{esc(frase)}</div>" if frase else "")
        + f"<div class='au-tar-mono'>{t('lav.tar_nota_scarto')}</div>",
        unsafe_allow_html=True)
    with st.container(key="tarAzioni", horizontal=True):
        if st.button(t("lav.chiudi"), type="primary", key="tarChiudi"):
            _chiudi_taratura()
            _taratura_vista()
            st.rerun()


def _taratura_fallita(s: dict) -> None:
    st.markdown("<span class='au-tar-passo au-tar-p2'></span>", unsafe_allow_html=True)
    errore = str(s.get("error") or "")
    st.markdown(
        f"<div class='au-box-rosso'><b>{t('lav.tar_interrotta_titolo')}</b>"
        f"{' ' + esc(errore) if errore and errore != t('lav.tar_interrotta_titolo') else ''}</div>"
        f"<p class='au-tar-p'>{t('lav.tar_niente_salvato')}</p>",
        unsafe_allow_html=True)
    with st.container(key="tarAzioni", horizontal=True):
        registro = PATHS.cache / "calibration.log"
        try:
            pieno = registro.stat().st_size > 0
        except OSError:
            pieno = False
        if pieno and st.button(t("lav.tar_mostra_log"), key="tarLog", type="tertiary"):
            subprocess.run(["open", "-R", str(registro)], check=False)
        if st.button(t("lav.chiudi"), key="tarChiudiErr"):
            _chiudi_taratura()
            _taratura_vista()
            st.rerun()
        if st.button(t("lav.tar_riprova"), type="primary", key="tarRiprova"):
            _taratura_vista()
            taratura.avvia_fondo()
            st.rerun(scope="fragment")


# Come per la fine coda: il titolo si traduce all'apertura, non all'avvio.
def _chiudi_taratura() -> None:
    st.session_state.pop("tar_aperta", None)
    st.session_state.pop("tar_vedi", None)
    # Chiusa sui risultati appena arrivati (anche con la X): visti. Senza,
    # la finestra si riaprirebbe da sola a ogni giro (vedi `main`).
    s = taratura.stato_fondo()
    if s and s.get("state") in (taratura.FINITA, taratura.FALLITA) and not s.get("seen"):
        _taratura_vista()


def _vedi_taratura() -> None:
    """Il link accanto alla data dell'ultima taratura: riapre i risultati."""
    st.session_state["tar_aperta"] = True
    st.session_state["tar_vedi"] = True


def _ultimi_risultati() -> dict | None:
    """I risultati dell'ultima taratura, come li mostra il passo 3.

    Il file di stato tiene anche la taratura di prima, per la colonna
    «Precedente»; se pero' l'ultima voce salvata non e' quella (fatta da
    Terminale, o prima della 1.6) si mostra la voce da sola.
    """
    voce = taratura.carica()
    if not voce:
        return None
    s = taratura.stato_fondo() or {}
    nuova = s.get("new") or {}
    if s.get("state") == taratura.FINITA and nuova.get("quando") == voce.get("quando"):
        return s
    return {"new": voce, "previous": None}


def _modale_taratura() -> None:
    """La finestra della taratura, una volta per giro.

    Resta aperta da un giro all'altro (`tar_aperta`): il cronometro, a giro
    finito, chiede un giro completo della pagina, e una modale aperta solo
    dal clic su un pulsante spariva proprio quando doveva mostrare i
    risultati. Si chiude coi suoi pulsanti, con la X o con ESC.
    """
    giro = st.session_state.get("_giro")
    if st.session_state.get("tar_giro") == giro:
        return
    st.session_state["tar_giro"] = giro
    st.session_state["tar_aperta"] = True
    st.markdown("<style>" + "".join(
        f'[role="dialog"]:has(.au-tar-p{n}) h2::after '
        f'{{ content: "{t("lav.tar_passo", n=n, totale=3)}"; }}'
        for n in (1, 2, 3)) + "</style>", unsafe_allow_html=True)
    # Il titolo dice cosa si guarda: la taratura da fare o in corso, quella
    # appena finita (anche quando la finestra si riapre da sola), o i
    # risultati di una vecchia, aperti dalla sua data — li' niente «passo 3
    # di 3», che e' un passo solo se ci si arriva dal 2.
    s_tar = taratura.stato_fondo() or {}
    if st.session_state.get("tar_vedi") and s_tar.get("state") != taratura.IN_CORSO:
        titolo = t("lav.tar_titolo_risultati")
    elif s_tar.get("state") == taratura.FINITA and not s_tar.get("seen"):
        titolo = t("lav.tar_titolo_finita")
    elif s_tar.get("state") == taratura.IN_CORSO:
        titolo = t("lav.tar_titolo_corso")
    else:
        titolo = t("lav.tar_titolo")
    st.dialog(titolo, width="medium",
              on_dismiss=_chiudi_taratura)(_contenuto_taratura)()


def _chiedi_aggiornamento() -> None:
    """Lascia all'app per macOS la richiesta di aggiornarsi.

    Solo la richiesta: quale versione, da dove e con che checksum lo chiede
    l'app direttamente a GitHub, senza fidarsi di niente scritto qui.
    """
    stato = os.environ.get("ANIMEUP_STATO")
    if not stato:
        return
    try:
        (Path(stato) / "update-request").write_text(str(time.time()))
        st.session_state["aggiornamento_chiesto"] = True
    except OSError:
        pass


# Le due cartelle che l'utente sceglie: per ciascuna il file in cui l'app per
# macOS la legge al prossimo avvio, la variabile con cui segnala una scelta
# che ha dovuto saltare (disco non collegato) e i testi.
_CARTELLE = {
    "input": ("input-folder", "ANIMEUP_INPUT_MISSING", "sb.cartella_in"),
    "output": ("output-folder", "ANIMEUP_OUTPUT_MISSING", "sb.cartella_out"),
}


def _cartella_attuale(quale: str) -> Path:
    return PATHS.input if quale == "input" else PATHS.output


def _testo_applescript(testo: str) -> str:
    return str(testo).replace("\\", "\\\\").replace('"', "'")


def _avviso_mac(titolo: str, testo: str) -> None:
    """Un avviso nativo di macOS, sopra il selettore appena chiuso.

    Un rifiuto detto con un toast nella pagina passava inosservato (visto
    dall'utente: «il percorso non si aggiorna e non so perche'»): chi ha
    appena scelto una cartella in una finestra del Mac si aspetta la
    risposta li'.
    """
    subprocess.run(
        ["osascript", "-e", "activate", "-e",
         f'display alert "{_testo_applescript(titolo)}" message '
         f'"{_testo_applescript(testo)}" as warning'],
        capture_output=True, text=True, check=False)


def _scegli_cartella(quale: str) -> None:
    """Il selettore di cartelle di macOS, aperto dal server (che gira su
    questo stesso Mac). Annullare non cambia niente. Scelta una cartella,
    l'app riavvia il server su quella e la pagina si ricarica da sola."""
    testo = _CARTELLE[quale][2]
    # Il pulsante e' gia' spento quando qualcosa gira; questa e' la cintura:
    # cambiata OUTPUT, il server nuovo non vede piu' lavori, code e taratura
    # di quella vecchia e lascerebbe partire un secondo giro accanto al primo.
    if _motivo_blocco() is not None:
        _avviso_mac(t("sb.cambio_no_titolo"), t("sb.cambio_occupato"))
        return
    # Si apre dove sta la cartella di adesso, non sull'ultima vista.
    dove = _cartella_attuale(quale)
    partenza = (f' default location (POSIX file "{_testo_applescript(dove)}")'
                if dove.is_dir() else "")
    esito = subprocess.run(
        # `activate`: il selettore in primo piano, cosi' le scorciatoie del
        # Finder (⌘↑ per la cartella sopra) funzionano subito.
        ["osascript", "-e", "activate", "-e",
         f'POSIX path of (choose folder with prompt '
         f'"{_testo_applescript(t(testo + "_prompt"))}"{partenza})'],
        capture_output=True, text=True, check=False)
    if esito.returncode != 0:
        return
    _applica_cartella(quale, esito.stdout.strip())


def _cartella_dal_mac() -> None:
    """La cartella scelta nel pannello nativo dell'app.

    Nell'app «Cambia…» non passa da qui: lo script della pagina gira il clic
    all'app per macOS, che apre il suo pannello come foglio della finestra
    (di AnimeUp, con ⌘↑ e tutto; quello di `osascript` restava di un
    processo in sottofondo, sopra a ogni altra app, con AnimeUp ancora
    attiva — segnalato dall'utente). Scelta la cartella, l'app la scrive qui
    accanto e preme il pulsante nascosto che chiama questa funzione.
    """
    stato = os.environ.get("ANIMEUP_STATO")
    if not stato:
        return
    f = Path(stato) / "folder-choice.json"
    try:
        dati = json.loads(f.read_text())
        f.unlink(missing_ok=True)
    except (OSError, ValueError):
        return
    quale = dati.get("which") if isinstance(dati, dict) else None
    if quale not in ("input", "output") or not dati.get("path"):
        return
    if _motivo_blocco() is not None:
        _avviso_mac(t("sb.cambio_no_titolo"), t("sb.cambio_occupato"))
        return
    _applica_cartella(quale, str(dati["path"]))


def _applica_cartella(quale: str, scelta: str) -> None:
    """Controlla la cartella scelta e, se va, la fa usare all'app."""
    file = _CARTELLE[quale][0]
    stato = os.environ.get("ANIMEUP_STATO")
    if not scelta or not stato:
        return
    nuova = Path(scelta).resolve()
    altra = _cartella_attuale("output" if quale == "input" else "input")
    try:
        uguale = nuova == altra.resolve()
    except OSError:
        uguale = False
    if uguale:
        _avviso_mac(t("sb.cambio_no_titolo"), t("sb.cambio_uguale"))
        return
    # Una dentro l'altra: i lavori di OUTPUT (JOBS, logs) finirebbero fra i
    # video da elaborare, o i video da elaborare fra quelli finiti.
    try:
        annidata = (altra.resolve() in nuova.parents) or (nuova in altra.resolve().parents)
    except OSError:
        annidata = False
    if annidata:
        _avviso_mac(t("sb.cambio_no_titolo"), t("sb.cambio_annidata"))
        return
    # OUTPUT deve potersi scrivere (video finiti, JOBS, logs); INPUT leggere.
    if not os.access(nuova, os.W_OK if quale == "output" else os.R_OK):
        _avviso_mac(t("sb.cambio_no_titolo"),
                    t("sb.cambio_no_scrivere" if quale == "output" else "sb.cambio_no_leggere"))
        return
    if quale == "output" and nuova != PATHS.output.resolve():
        # Le lavorazioni interrotte restano nella JOBS di prima, e da qui
        # non si vedrebbero piu': lo si dice prima, non dopo.
        # Contano solo le cartelle che una lavorazione ha davvero lasciato
        # (la ricetta, lo stato o il lucchetto): contandole tutte, due
        # cartelle vuote finite in JOBS facevano dire «2 lavorazioni
        # interrotte» a chi non ne aveva nessuna (successo).
        try:
            lasciati = sum(1 for d in PATHS.work.iterdir()
                           if d.is_dir() and not d.name.startswith(".")
                           and any((d / f).is_file() for f in
                                   ("state.json", "parameters.json", "running.lock")))
        except OSError:
            lasciati = 0
        if lasciati:
            avviso = _testo_applescript(tn("sb.cambio_lavori", lasciati,
                                           cartella=_breve(PATHS.output)))
            ok = _testo_applescript(t("sb.cambio_lavori_ok"))
            no = _testo_applescript(t("sb.annulla"))
            conferma = subprocess.run(
                ["osascript", "-e", "activate", "-e",
                 f'display dialog "{avviso}" buttons {{"{no}", "{ok}"}} '
                 f'default button "{no}" cancel button "{no}" with icon caution'],
                capture_output=True, text=True, check=False)
            if conferma.returncode != 0:
                return
    if nuova == _cartella_attuale(quale).resolve():
        # La stessa di adesso: l'app non riavvia niente, e un «Passo a…»
        # resterebbe li' per tutta la sessione.
        return
    try:
        Path(stato).mkdir(parents=True, exist_ok=True)
        (Path(stato) / file).write_text(str(nuova) + "\n")
    except OSError:
        return
    st.session_state["cartella_cambiata"] = str(nuova)


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


def _unito(testo: str) -> str:
    """Un valore che puo' andare a capo solo fra un pezzo e l'altro.

    Un numero resta attaccato alla sua unita' e a cio' che lo precede
    («8 bit 4:2:0», «riduzione 2.00:1», «≈ 2m»): si va a capo dopo un «·» o
    prima di una «→», mai a meta' di una misura. Spazi normali altrove.
    """
    import re

    def pezzo(p: str) -> str:
        return re.sub(r"(?<=\d) (?=\S)|(?<=\S) (?=[\d≈~×])|(?<=[≈~]) ", "\u00a0", p)
    # Prima i separatori, poi i numeri dentro ogni pezzo: al contrario lo
    # spazio dopo «·» si attaccava al numero e si andava a capo PRIMA del «·».
    return "\u00a0· ".join(" →\u00a0".join(pezzo(q) for q in parte.split(" → "))
                            for parte in testo.split(" · "))


def _pezzi(testo: str) -> str:
    """Un testo «a · b · c» che va a capo fra un pezzo e l'altro, senza
    lasciare il «·» in fondo o in testa a una riga (chiesto dall'utente:
    «File 1 di 2» / «55%», non «File 1 di 2 ·» / «55%»).

    Ogni pezzo porta il suo «·» nel margine a sinistra; il contenitore
    nasconde quella striscia, quindi il punto si vede solo fra due pezzi
    sulla stessa riga e sparisce dove un pezzo apre una riga nuova (vedi
    `.au-pz`). Dentro un pezzo i numeri restano attaccati (`_unito`).
    """
    parti = [p for p in testo.split(" · ") if p.strip()]
    if len(parti) <= 1:
        return esc(_unito(testo))
    return ("<span class='au-pz'><span>"
            + "".join(f"<span>{esc(_unito(p))}</span>" for p in parti)
            + "</span></span>")


def _breve(percorso: str | Path) -> str:
    return str(percorso).replace(str(Path.home()), "~", 1)


def _note_cartelle_assenti() -> list[str]:
    """Le cartelle scelte che l'app ha dovuto saltare (disco non collegato)."""
    note = []
    for quale, (_, variabile, _) in _CARTELLE.items():
        assente = os.environ.get(variabile)
        if assente:
            note.append(t("sb.cartella_assente", scelta=_breve(assente),
                          attuale=_breve(_cartella_attuale(quale))))
    return note


def _riga_cartella(quale: str, congelata: bool, dove=st) -> None:
    """Una delle due cartelle: etichetta col «?» sopra, percorso e Cambia…
    sotto. Due righe e non una: in italiano etichetta e pulsante insieme non
    ci stanno nella larghezza della sidebar."""
    _, variabile, testo = _CARTELLE[quale]
    with dove.container(key=f"cCartellaRiga_{quale}"):
        st.markdown(
            f"<div class='au-pref-eti'>{t(testo)}{_icona_perche(t(testo + '_aiuto'))}</div>",
            unsafe_allow_html=True)
        with st.container(horizontal=True, vertical_alignment="center",
                          key=f"cCartellaPerc_{quale}"):
            st.markdown(_percorso(_cartella_attuale(quale), "au-percorso"),
                        unsafe_allow_html=True)
            st.button(t("sb.cartella_cambia"), key=f"apriCartella_{quale}",
                      disabled=congelata, on_click=_scegli_cartella, args=(quale,))
        if (assente := os.environ.get(variabile)):
            nota = t("sb.cartella_assente", scelta=_breve(assente),
                     attuale=_breve(_cartella_attuale(quale)))
            st.markdown(f"<div class='au-sb-ridotto'>{esc(nota)}</div>",
                        unsafe_allow_html=True)


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


def _motivo_blocco() -> str | None:
    """Perche' la sidebar e' bloccata adesso, o None.

    Una lavorazione, un confronto o una taratura in corso: in tutti e tre i
    casi cambiare un valore non avrebbe effetto su cio' che gira (porta i
    parametri con cui e' partito) e confonderebbe la pagina.
    """
    if (monitor.catena() is not None or monitor.pausa() is not None
            or monitor.lancio_vivo() or any(l.vivo for l in monitor.lavori(recente=1.0))):
        return "lavoro"
    if confronto.in_corso():
        return "confronto"
    if taratura.in_corso():
        return "taratura"
    return None


# Le impostazioni dentro «Avanzate», col valore di fabbrica scritto come lo
# legge l'utente: e' la riga «cambiata · di fabbrica …» sotto il controllo.
_AVANZATE = ("dedup", "denoise", "forza", "approfondita", "disco", "pausa")


def _testo_fabbrica(chiave: str, valore) -> str:
    if isinstance(valore, bool):
        return t("sb.abilitato" if valore else "sb.disabilitato")
    if chiave == "disco":
        return f"{valore} GB"
    if chiave == "pausa":
        return t("sb.pausa_nessuna") if valore == 0 else f"{valore} min"
    return str(valore)


def _cambiata(dove, chiave: str, fabbrica: dict) -> None:
    """La riga «cambiata · di fabbrica …» sotto un controllo avanzato."""
    if st.session_state.get(f"w_{chiave}") != fabbrica[chiave]:
        dove.markdown(
            "<div class='au-cambiata'><span></span>"
            f"{t('sb.cambiato', valore=esc(_testo_fabbrica(chiave, fabbrica[chiave])))}"
            "</div>", unsafe_allow_html=True)


_SCELTE_ALTEZZA = [720, 1080, 1440, 2160]
_SCELTE_CRF = list(range(14, 25))
_SCELTE_PRESET = ["medium", "slow", "slower", "veryslow"]
# Come si legge ogni cursore della sidebar nella sua etichetta: lo usa anche
# lo script della pagina, che la aggiorna mentre si trascina.
_ETICHETTE_SCATTI = {
    "cAltezza": [f"{v} px" for v in _SCELTE_ALTEZZA],
    "cCrf": [str(v) for v in _SCELTE_CRF],
    "cPreset": _SCELTE_PRESET,
}


def _cursore_a_scatti(chiave: str, nome: str, scelte: list, congelata: bool):
    """Un cursore a valori fissi che segue il mouse e si aggancia al rilascio.

    Quello di Streamlit salta da un valore all'altro: con quattro valori su
    300px il pomello restava fermo finche' il mouse non arrivava a meta' del
    salto, e sembrava rotto (detto dall'utente). Qui il widget e' continuo
    sulla POSIZIONE nell'elenco (0.00 … n-1), e al rilascio si arrotonda al
    valore piu' vicino: segue la mano, poi scatta come una calamita. Il
    valore vero resta in `w_<chiave>`, come prima.
    """
    vero = st.session_state.get(f"w_{chiave}", _IMPOSTAZIONI_DEFAULT[chiave])
    indice = scelte.index(vero) if vero in scelte else scelte.index(_IMPOSTAZIONI_DEFAULT[chiave])
    st.session_state[f"w_{chiave}_pos"] = float(indice)
    st.slider(nome, 0.0, float(len(scelte) - 1), step=0.01, key=f"w_{chiave}_pos",
              disabled=congelata, label_visibility="collapsed",
              on_change=_aggancia, args=(chiave, scelte))
    return scelte[indice]


def _puntini_scatti(chiave: str, n: int) -> str:
    """I valori possibili di un cursore a scatti, come puntini sul binario.

    Il pomello ora segue il mouse, ma non si capiva se i valori fossero 5 o
    50 (detto dall'utente): passandoci sopra, o trascinando, compare un
    puntino per ogni valore, sotto al pomello. Il riquadro sborda di 3px per
    lato, cosi' il centro di ogni puntino cade esattamente dove si ferma il
    centro del pomello (0 … 100%).
    """
    def punti(colore: str, anello: str = "") -> str:
        # Sul ciano il puntino chiaro ha un anello ciano: piu' largo del
        # binario, senza anello si confondeva col fondo chiaro.
        stop = (f"{colore} 0 1.6px, {anello} 1.6px 2.6px, transparent 3px" if anello
                else f"{colore} 0 2px, transparent 2.5px")
        return ", ".join(f"radial-gradient(circle, {stop})" for _ in range(n))
    posizioni = ", ".join(f"{i * 100 / (n - 1):.4f}% 50%" for i in range(n))
    base = f'.st-key-{chiave} [data-testid="stSlider"] [role="group"] > div'
    # Due strati: chiari sulla parte gia' colorata (a sinistra del pomello,
    # dove i grigi non si vedevano), grigi sul resto. Il confine e' `--au-p`
    # (0…1): lo scrive il giro a ogni valore e, mentre si trascina, lo script
    # della pagina (vedi `_cassetto_sidebar`).
    comune = ('content: ""; position: absolute; left: -3px; right: -3px; top: 50%; '
              'height: 6px; transform: translateY(-50%); pointer-events: none; '
              'background-size: 6px 6px; background-repeat: no-repeat; '
              f'background-position: {posizioni}; opacity: 0; transition: opacity .15s ease;')
    return (f'{base}::before {{ {comune} background-image: {punti("var(--dotOnFill)", "var(--primaryStrong)")}; '
            'clip-path: inset(0 calc((100% - 6px) * (1 - var(--au-p, 0)) + 3px) 0 0); }'
            f'{base}::after {{ {comune} background-image: {punti("var(--textSecondary)")}; '
            'clip-path: inset(0 0 0 calc((100% - 6px) * var(--au-p, 0) + 3px)); }'
            f'.st-key-{chiave}:is(:hover, :active) [data-testid="stSlider"] [role="group"] > div::before,'
            f'.st-key-{chiave}:is(:hover, :active) [data-testid="stSlider"] [role="group"] > div::after'
            f' {{ opacity: 1; }}'
            f'{base} > div[style*="position: absolute"] {{ z-index: 1; }}')


def _aggancia(chiave: str, scelte: list) -> None:
    posizione = float(st.session_state.get(f"w_{chiave}_pos") or 0)
    indice = min(max(int(round(posizione)), 0), len(scelte) - 1)
    st.session_state[f"w_{chiave}"] = scelte[indice]


def _ripristina_una(chiave: str, valore) -> None:
    st.session_state[f"w_{chiave}"] = valore


def _ripristina_avanzate(fabbrica: dict) -> None:
    for chiave in _AVANZATE:
        st.session_state[f"w_{chiave}"] = fabbrica[chiave]


def _chiedi_uscita() -> None:
    """Il «Esci da AnimeUp» della sidebar, nell'app: lo fa l'app.

    Come ⌘Q: se c'e' qualcosa in corso l'app chiede conferma con la sua
    finestra, poi ferma e chiude. Qui si lascia solo la richiesta.
    """
    stato = os.environ.get("ANIMEUP_STATO")
    if stato:
        try:
            (Path(stato) / "quit-request").write_text(str(time.time()))
        except OSError:
            pass


def sidebar() -> dict:
    # Con qualcosa in corso le impostazioni si CONGELANO: cambiarle non
    # avrebbe alcun effetto reale (la catena porta i parametri scritti nel
    # suo comando, e Avvia/Riprendi sono spenti), ma rigiudicava le righe
    # coi valori nuovi — l'episodio "fatto" smetteva di esserlo solo perché
    # il CRF a schermo era cambiato: "un effetto ottico orrendo" (detto
    # dall'utente, e aveva ragione). Dal redesign si blocca TUTTO, lingua,
    # tema e cartelle compresi (deciso dall'utente): resta vivo solo Esci.
    motivo = _motivo_blocco()
    congelata = motivo is not None
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
    fabbrica = _predefiniti()
    # Il valore di fabbrica dello spazio segue lo spazio libero, che cambia
    # mentre si lavora. Chi non l'ha mai toccato lo segue anche lui: prima
    # restava al numero di inizio sessione e «Avanzate» diceva «1 cambiata»
    # senza che nessuno avesse cambiato niente.
    # A sidebar bloccata si ferma anche il valore di fabbrica: durante una
    # taratura lo spazio libero scendeva di un GB e «Avanzate» tornava a
    # dire «1 cambiata». Si riallinea allo sblocco.
    _disco_prec = st.session_state.get("disco_fabbrica_prec")
    if (_disco_prec is not None and st.session_state.get("w_disco") == _disco_prec
            and fabbrica.get("disco") != _disco_prec):
        if congelata:
            fabbrica["disco"] = _disco_prec
        else:
            st.session_state["w_disco"] = fabbrica["disco"]
    st.session_state["disco_fabbrica_prec"] = fabbrica.get("disco")
    app = os.environ.get("ANIMEUP_APP") == "1"
    regole: list[str] = []

    nuova = aggiornamenti.disponibile(attivo=salvate.get("aggiornamenti", True))
    if nuova:
        # Nell'app l'aggiornamento lo fa l'app stessa (scarica, verifica il
        # checksum, si sostituisce): qui si chiede soltanto. Nella cartella
        # portatile resta il link alla release, da scaricare a mano.
        with st.sidebar.container(key="cAggiorna"):
            link = (f"<a href='{esc(nuova['url'])}' target='_blank'>"
                    f"{t('sb.aggiornamento_note' if app else 'sb.aggiornamento_link')}</a>")
            st.markdown(
                "<div class='au-agg-testa'>"
                f"<b>{t('sb.aggiornamento', versione=esc(nuova['versione']))}</b>"
                f"{link}</div>", unsafe_allow_html=True)
            if app:
                if st.button(t("sb.aggiornamento_installa"), key="installaAgg",
                             type="primary", disabled=congelata):
                    _chiedi_aggiornamento()
                st.caption(t("sb.aggiornamento_chiesto"))

    # --- Impostazioni globali -------------------------------------------
    blocco = ""
    if congelata:
        blocco = (f"<span class='au-lock-chip'>{_ICONA_LUCCHETTO}"
                  f"{t('sb.lock_' + motivo)}</span>")
    # Bloccata, il perche' prende il posto del sottotitolo, della stessa
    # misura: un riquadro in piu' spingeva giu' tutta la colonna di un salto
    # (segnalato dall'utente).
    if congelata:
        nota = {"lavoro": "sb.congelata", "confronto": "sb.congelata_confronto",
                "taratura": "sb.congelata_taratura"}[motivo]
        sotto = f"<div class='au-sb-nota au-sb-nota-lock'>{t(nota)}</div>"
    else:
        sotto = f"<div class='au-sb-nota'>{t('sb.valgono')}</div>"
    st.sidebar.markdown(
        f"<div class='au-sb-titolo'><span>{t('sb.titolo')}</span>{blocco}</div>{sotto}",
        unsafe_allow_html=True)
    # Il posto dell'avviso «file sospeso» sta QUI, in alto, anche se il suo
    # contenuto si sa solo in fondo (serve il confronto con i widget): un
    # avviso che si vede solo se scorri e' un avviso che meta' delle volte
    # non esiste (segnalato dall'utente il 12/08).
    posto_sospeso = st.sidebar.empty()
    # Bloccata DAVVERO anche all'occhio, e TUTTA allo stesso modo: titoli,
    # etichette, «?» (spenti anche al passaggio), valori. Restano pieni il
    # perche' sotto il titolo, «Mostra» della taratura e il piede con Esci.
    # Lo stile c'e' a ogni giro, vuoto da sbloccata: un elemento che compare
    # e sparisce in cima alla colonna spostava tutti quelli sotto, e per un
    # attimo Streamlit li rimetteva al posto sbagliato (la sidebar si
    # «disimpaginava», visto dall'utente).
    st.sidebar.markdown(
        "<style>[data-testid='stSidebar'] :is([data-testid='stSlider'],"
        "[data-testid='stCheckbox'],[data-testid='stSelectbox'],"
        "[data-testid='stButtonGroup'],.au-sb-eti,.au-sgruppo,.au-pref-eti,"
        ".au-sb-aiuto,.au-sb-titolo > span:first-child,"
        ".au-percorso,.au-tar-mai,.au-tar-ok,.au-agg-nota,.st-key-adv summary)"
        "{ opacity: .45; }"
        "[data-testid='stSidebar'] :is([data-testid='stSlider'],"
        "[data-testid='stCheckbox'],.au-info,.au-perche,a.au-tar-vedi)"
        "{ filter: saturate(0); pointer-events: none; }"
        "[data-testid='stSidebar'] :is(.au-info, .au-perche) .au-bolla"
        "{ display: none !important; }"
        # La riga della taratura resta viva mentre e' lei a girare: titolo
        # acceso accanto a «Mostra» (chiesto dall'utente).
        + (".st-key-cTarRiga .au-pref-eti { opacity: 1 !important; }" if motivo == "taratura" else "")
        + "</style>" if congelata else "<style></style>",
        unsafe_allow_html=True)

    # Il «Predefinito: …» dei fumetti diventa un link quando il valore e'
    # stato cambiato: lo raccoglie lo script della pagina madre e preme qui
    # il pulsante nascosto della stessa impostazione. A sidebar bloccata
    # niente link: il fumetto resta com'era, grigio.
    def rip(chiave: str) -> str | None:
        if congelata or st.session_state.get(f"w_{chiave}") == fabbrica[chiave]:
            return None
        return chiave
    with st.sidebar.container(key="ripristiniNascosti"):
        for chiave in ("altezza", "crf", "preset") + _AVANZATE:
            st.button(chiave, key=f"ripr_{chiave}", on_click=_ripristina_una,
                      args=(chiave, fabbrica[chiave]), disabled=congelata)

    st.sidebar.markdown(f"<div class='au-eyebrow au-sgruppo'>{t('sb.uscita')}</div>",
                        unsafe_allow_html=True)
    _etichetta_sb(
        t("sb.altezza"), t("sb.altezza_aiuto"),
        f"{st.session_state.get('w_altezza', 1080)} px",
        predefinito="1080 px", ripristina=rip("altezza"))
    with st.sidebar.container(key="cAltezza"):
        altezza = _cursore_a_scatti("altezza", "Altezza finale", _SCELTE_ALTEZZA, congelata)
    _etichetta_sb(
        t("sb.crf"),
        t("sb.crf_aiuto"), str(st.session_state.get("w_crf", 18)), predefinito="18",
        ripristina=rip("crf"))
    with st.sidebar.container(key="cCrf"):
        crf = _cursore_a_scatti("crf", "CRF (x265)", _SCELTE_CRF, congelata)
    _etichetta_sb(
        t("sb.preset"), t("sb.preset_aiuto"),
        str(st.session_state.get("w_preset", "slower")),
        predefinito="slower", ripristina=rip("preset"))
    with st.sidebar.container(key="cPreset"):
        preset = _cursore_a_scatti("preset", "Preset x265", _SCELTE_PRESET, congelata)
    if not congelata:
        for chiave_c, scelte_c, valore_c in (("cAltezza", _SCELTE_ALTEZZA, altezza),
                                             ("cCrf", _SCELTE_CRF, crf),
                                             ("cPreset", _SCELTE_PRESET, preset)):
            regole.append(_puntini_scatti(chiave_c, len(scelte_c)))
            regole.append(f'.st-key-{chiave_c} {{ --au-p: '
                          f'{scelte_c.index(valore_c) / (len(scelte_c) - 1):.4f}; }}')

    # --- Avanzate: un riquadro che si apre --------------------------------
    # L'intestazione dice se c'e' qualcosa di cambiato: un interruttore
    # toccato non deve potersi nascondere qui dentro. Si apre anche a
    # sidebar bloccata, per guardare i valori; i controlli restano spenti.
    cambiate = [k for k in _AVANZATE
                if st.session_state.get(f"w_{k}") != fabbrica[k]]
    stato_av = (tn("sb.avanzate_cambiate", len(cambiate)) if cambiate
                else t("sb.avanzate_tutte"))
    regole.append(
        f'.st-key-adv summary p::after {{ content: "{stato_av}"; }}'
        f'.st-key-adv {{ --adv-nota: "{t("sb.avanzate_nota")}"; }}')
    if cambiate:
        regole.append('.st-key-adv summary p::after { color: var(--primaryText);'
                      ' border-color: rgb(var(--primaryRgb) / .45); }')
    adv = st.sidebar.expander(t("sb.avanzate"), key="adv")
    with adv:
        st.markdown(f"<div class='au-adv-nota'>{t('sb.avanzate_nota')}</div>"
                    f"<div class='au-eyebrow au-sgruppo'>{t('sb.preelab')}</div>",
                    unsafe_allow_html=True)
        with st.container(key="swDedup"):
            dedup = st.toggle(t("sb.dedup"), key="w_dedup", disabled=congelata)
            _aiuto_a_destra(t("sb.dedup_aiuto"), t("sb.abilitato"), rip("dedup"))
        _cambiata(adv, "dedup", fabbrica)
        with st.container(key="swDenoise"):
            denoise = st.toggle(t("sb.denoise"), key="w_denoise", disabled=congelata)
            _aiuto_a_destra(t("sb.denoise_aiuto"), t("sb.disabilitato"), rip("denoise"))
        _cambiata(adv, "denoise", fabbrica)
        with st.container(key="swForza"):
            forza = st.toggle(t("sb.forza"), key="w_forza", disabled=congelata)
            _aiuto_a_destra(t("sb.forza_aiuto"), t("sb.disabilitato"), rip("forza"))
        _cambiata(adv, "forza", fabbrica)
        with st.container(key="swApprof"):
            approfondita = st.toggle(t("sb.approf"), key="w_approfondita",
                                     disabled=congelata)
            _aiuto_a_destra(t("sb.approf_aiuto"), t("sb.abilitato"), rip("approfondita"))
        _cambiata(adv, "approfondita", fabbrica)

        st.markdown(f"<div class='au-eyebrow au-sgruppo'>{t('sb.risorse')}</div>",
                    unsafe_allow_html=True)
        # Il TETTO COMPLESSIVO di disco per un file, non la dimensione di un
        # blocco: la divisione in blocchi la decide l'app. Il massimo del
        # cursore e' lo spazio LIBERO VERO, sul disco dei video finiti.
        _tetto_max, _libero_gb = _tetto_spazio()
        _disco_ora = st.session_state.get("w_disco", _tetto_max)
        # Il valore ricordato non entra piu' nel disco di oggi: si abbassa e
        # lo si DICE. (Chiesto da Interstellar0verdrive l'11/08.)
        # Ma solo a sidebar libera: mentre qualcosa gira e' il lavoro stesso a
        # consumare il disco, il valore e' comunque bloccato, e l'avviso
        # tornava a ogni giro dicendo il falso (visto durante una taratura).
        ridotto = None
        if _disco_ora > _tetto_max and not congelata:
            ridotto = t("sb.disco_ridotto", ora=_disco_ora, libero=_libero_gb,
                        tetto=_tetto_max)
            st.session_state["w_disco"] = _tetto_max
            _disco_ora = _tetto_max
        _etichetta_sb(t("sb.disco"), t("sb.disco_aiuto"), f"{_disco_ora} GB",
                      predefinito=t("sb.disco_predefinito", tetto=_tetto_max,
                                    libero=_libero_gb), dove=adv,
                      ripristina=rip("disco"))
        with st.container(key="cDisco"):
            disco = st.slider(t("sb.disco"), MINIMO_SPAZIO_GB, max(_tetto_max, _disco_ora),
                              key="w_disco", disabled=congelata,
                              label_visibility="collapsed")
        # Sotto il cursore e non fra etichetta e cursore: li' si sovrapponeva
        # all'etichetta (segnalato dall'utente).
        _cambiata(adv, "disco", fabbrica)
        st.markdown(f"<div class='au-sb-regola'>{t('sb.disco_regola', libero=_libero_gb)}</div>",
                    unsafe_allow_html=True)
        if ridotto:
            st.markdown(f"<div class='au-sb-ridotto'>{ridotto}</div>",
                        unsafe_allow_html=True)

        _pausa_ora = st.session_state.get("w_pausa", 5)
        _etichetta_sb(
            t("sb.pausa"), t("sb.pausa_aiuto"),
            t("sb.pausa_nessuna") if _pausa_ora == 0 else f"{_pausa_ora} min",
            predefinito="5 min", dove=adv, ripristina=rip("pausa"))
        with st.container(key="cPausa"):
            # Default 5 e non 0 (scelta dell'utente): nelle maratone la pausa
            # deve esserci senza doversene ricordare; 0 spegne la funzione.
            pausa = st.slider(t("sb.pausa"), 0, 30, key="w_pausa",
                              disabled=congelata, label_visibility="collapsed")
        _cambiata(adv, "pausa", fabbrica)
        if cambiate:
            st.button(t("sb.ripristina_avanzate"), key="ripristinaAvanzate",
                      icon=":material/restart_alt:", disabled=congelata,
                      on_click=_ripristina_avanzate, args=(fabbrica,))

    # --- Preferenze ----------------------------------------------------
    st.sidebar.markdown(f"<div class='au-sb-titolo au-sb-pref'>"
                        f"<span>{t('sb.preferenze')}</span></div>",
                        unsafe_allow_html=True)
    with st.sidebar.container(key="cLinguaTema", horizontal=True):
        with st.container(key="cLingua"):
            # L'etichetta nella lingua in uso (deciso dall'utente): "Language"
            # o "Lingua" si capisce anche da chi legge l'altra.
            lingua = st.selectbox(
                t("sb.lingua"), list(i18n.LINGUE), key="w_lingua",
                format_func=i18n.LINGUE.get, disabled=congelata)
        with st.container(key="cTema"):
            scelta_tema = st.segmented_control(
                t("sb.tema"), list(tema.SCELTE), key="w_tema", required=True,
                format_func=lambda m: _ICONE_TEMA[m], disabled=congelata)
    with st.sidebar.container(key="prefCard"):
        # Le cartelle si scelgono solo nell'app: nella modalita' a cartella
        # stanno accanto al programma (o dove dicono le variabili da Terminale).
        if app:
            _riga_cartella("input", congelata, dove=st)
            _riga_cartella("output", congelata, dove=st)
            nuova_cartella = st.session_state.get("cartella_cambiata")
            if nuova_cartella:
                st.caption(t("sb.cartella_riavvia", cartella=_breve(nuova_cartella)))
        _riga_taratura(congelata)
        with st.container(key="swAggiorn"):
            controlla_agg = st.toggle(t("sb.controlla_agg"), key="w_aggiornamenti",
                                      disabled=congelata,
                                      help=t("sb.controlla_agg_aiuto"))
            st.markdown(f"<div class='au-agg-nota'>{t('sb.controlla_agg_nota')}</div>",
                        unsafe_allow_html=True)

    st.sidebar.markdown("<style>" + "\n".join(regole) + "</style>",
                        unsafe_allow_html=True)

    attuali = {"altezza": altezza, "crf": crf, "preset": preset,
               "dedup": dedup, "denoise": denoise, "forza": forza,
               "disco": disco, "pausa": pausa,
               "approfondita": approfondita, "lingua": lingua,
               "aggiornamenti": controlla_agg,
               "tema": scelta_tema or salvate.get("tema", tema.SISTEMA)}
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
            with posto_sospeso.container(key="cSospeso"):
                st.markdown(
                    "<div class='au-sb-sospeso'>"
                    f"{t('sb.sospeso', diversi=', '.join(_nomi_impostazioni(diversi)))}"
                    "</div>", unsafe_allow_html=True)
                st.button(t("sb.ripristina"), key="ripristina_parametri",
                          on_click=_ripristina_parametri, args=(ricetta,))

    # Si parla di portabilita' soltanto quando c'e' un problema.
    mancanti = [n for n, _t, s in PATHS.portability_report() if s != "ok"]
    if mancanti:
        st.sidebar.markdown(
            f"<span class='au-tag au-warn'>{tn('sb.dipendenze', len(mancanti))}</span>",
            unsafe_allow_html=True)
        st.sidebar.caption(t("sb.non_autonoma"))

    _piede_sidebar(app, congelata)
    return {"altezza": altezza, "crf": crf, "dedup": dedup, "preset": preset,
            "denoise": denoise, "disco": disco, "forza": forza, "pausa": pausa,
            "approfondita": approfondita}


_ICONA_LUCCHETTO = (
    "<svg width='11' height='11' viewBox='0 0 24 24' fill='none' "
    "stroke='currentColor' stroke-width='2.2' stroke-linecap='round' "
    "stroke-linejoin='round' aria-hidden='true'><rect x='4' y='11' width='16' "
    "height='10' rx='2'/><path d='M8 11V7a4 4 0 0 1 8 0v4'/></svg>")

_ICONE_TEMA = {"system": ":material/contrast:", "dark": ":material/dark_mode:",
               "light": ":material/light_mode:"}


def _riga_taratura(congelata: bool) -> None:
    """La taratura nelle Preferenze: quando, e come rifarla.

    Mai fatta: un pulsante pieno «Calibrate now», dello stesso colore degli
    interruttori accanto (deciso dall'utente). Fatta: la data, e «Recalibrate»
    neutro, perche' non c'e' niente di urgente.
    """
    voce_tar = taratura.carica()
    fondo = taratura.stato_fondo() or {}
    if fondo.get("state") == taratura.IN_CORSO:
        # In corso: si puo' sempre riaprire la finestra per guardarla, anche
        # con la sidebar bloccata (e' lei a bloccarla).
        stato = None
        azione, tipo, congelata = t("sb.taratura_mostra"), "secondary", False
    elif voce_tar:
        import datetime as _dt
        quando = _dt.datetime.fromtimestamp(voce_tar["quando"]).strftime(t("fmt.data_ora"))
        stato = (f"<a class='au-tar-ok au-tar-vedi' data-preme='vediTaratura' role='button' "
                 f"title='{t('sb.taratura_vedi')}'>{t('sb.taratura_ultima', quando=quando)}"
                 f"{_svg(_I_AVANTI, 11, 2.2)}</a>")
        azione, tipo = t("sb.taratura_ripeti"), "secondary"
        if voce_tar.get("vecchia"):
            # Fatta prima dell'1.6.8: senza la misura a 1080p, e le stime dei
            # file grandi escono lunghe. Si dice, e Ricalibra torna pieno.
            stato += f"<div class='au-tar-nota'>{t('sb.taratura_vecchia')}</div>"
            tipo = "primary"
    else:
        altro = taratura.di_altro_mac()
        # Mai fatta: anche qui la nota gialla, come per quella vecchia. Il
        # pallino sul cassetto e su Inizio deve portare a una scritta che lo
        # spiega (segnalato dall'utente: pallino acceso e niente in giallo).
        stato = (f"<span class='au-tar-mai'>"
                 + (t("sb.taratura_altro_mac", chip=esc(altro)) if altro
                    else f"{t('sb.taratura_mai')} · {t('sb.taratura_mai_nota')}")
                 + "</span>"
                 + ("" if altro else f"<div class='au-tar-nota'>{t('sb.taratura_mai_avviso')}</div>"))
        azione, tipo = t("sb.taratura_esegui"), "primary"
    with st.container(key="cTaratura"):
        with st.container(key="cTarRiga", horizontal=True,
                          vertical_alignment="center"):
            st.markdown(
                f"<div class='au-pref-eti'>{t('sb.taratura')}"
                f"{_icona_perche(t('sb.taratura_aiuto'))}</div>",
                unsafe_allow_html=True)
            # Spento durante una lavorazione: la taratura e' un benchmark, e
            # misurare una GPU occupata da' numeri falsi. In piu' Streamlit
            # ammette UNA sola modale per giro.
            if st.button(azione, key="apriTaratura", type=tipo,
                         disabled=congelata):
                st.session_state.pop("tar_fase", None)
                _modale_taratura()
        if stato is None:
            _tar_corso_sidebar()
        else:
            st.markdown(stato, unsafe_allow_html=True)
    # I pulsanti che premono i link «risultati» e l'app, a cartella scelta
    # (vedi `_cassetto_sidebar` e `_cartella_dal_mac`).
    with st.container(key="premiNascosti"):
        st.button("results", key="vediTaratura", on_click=_vedi_taratura)
        st.button("folder", key="applicaCartella", on_click=_cartella_dal_mac)


def _controlla_aggiornamenti_ora() -> None:
    # La risposta in una finestra al centro, con OK (vedi `_modale_esito_agg`):
    # un toast in alto a destra, lontano dal clic in basso a sinistra, non si
    # vedeva (detto dall'utente).
    st.session_state["esito_agg"] = aggiornamenti.controlla_ora()
    # Il file del controllo e' appena cambiato: la sentinella farebbe un giro
    # completo, che cancella il toast prima che si veda. Si riparte da zero.
    st.session_state.pop("firma_sentinella", None)


def _chiudi_esito_agg() -> None:
    st.session_state.pop("esito_agg", None)


def _contenuto_esito_agg() -> None:
    esito, versione_ = st.session_state.get("esito_agg") or ("errore", "")
    icona = {"nuova": "au-esito-nuova", "aggiornato": "au-esito-ok"}.get(esito, "au-esito-errore")
    segno = (_svg(_I_SPUNTA, 18, 2.4) if esito == "aggiornato" else
             _svg("<path d='M12 4v11M7 10l5 5 5-5M5 20h14'/>", 18, 2.2) if esito == "nuova" else
             "<b>!</b>")
    st.markdown(
        f"<div class='au-esito-agg'><span class='au-esito-icona {icona}'>{segno}</span>"
        f"<div><b>{t('sb.esito_titolo_' + esito, versione=versione_)}</b>"
        f"<span>{t('sb.esito_testo_' + esito, versione=versione_)}</span></div></div>",
        unsafe_allow_html=True)
    app = os.environ.get("ANIMEUP_APP") == "1"
    with st.container(key="esitoAggAzioni", horizontal=True):
        if esito == "nuova" and app:
            if st.button(t("sb.esito_dopo"), key="esitoDopo"):
                _chiudi_esito_agg()
                st.rerun()
            if st.button(t("sb.aggiornamento_installa"), key="esitoInstalla", type="primary",
                         disabled=_motivo_blocco() is not None):
                _chiudi_esito_agg()
                _chiedi_aggiornamento()
                st.rerun()
        elif st.button("OK", key="esitoOk", type="primary"):
            _chiudi_esito_agg()
            st.rerun()


def _modale_esito_agg() -> None:
    """La risposta del controllo chiesto a mano, una volta per giro finche'
    non la si chiude (come la taratura: un giro della pagina non la toglie)."""
    giro = st.session_state.get("_giro")
    if st.session_state.get("esito_agg_giro") == giro:
        return
    st.session_state["esito_agg_giro"] = giro
    # Senza X (chiesto dall'utente): la si chiude con il suo pulsante, che
    # e' anche l'unico gesto che toglie davvero l'esito dalla sessione.
    st.dialog(t("sb.esito_finestra"), width="small",
              dismissible=False)(_contenuto_esito_agg)()


def _piede_sidebar(app: bool, congelata: bool) -> None:
    """In fondo alla finestra: versione e «About» a sinistra, Esci a destra.

    Nell'app chiudere la finestra non ferma niente (AnimeUp resta acceso,
    come HandBrake): per uscire davvero c'e' questo pulsante, che fa quello
    che fa ⌘Q, conferma compresa. Nella cartella portatile spegne
    l'interfaccia, come faceva «Chiudi», con la sua conferma a due passi.
    """
    with st.sidebar.container(key="piede", horizontal=True,
                              vertical_alignment="center"):
        with st.container(key="piedeSx"):
            # La versione col suo «controlla adesso»: un'icona piccola, che
            # dice subito se ce n'e' una nuova o se questa e' l'ultima.
            with st.container(key="piedeVer", horizontal=True,
                              vertical_alignment="center"):
                st.markdown(f"<div class='au-piede'><span class='au-ver'>"
                            f"{t('sb.versione', versione=__version__)}"
                            "<span class='au-info au-agg-tip' aria-hidden='true'>"
                            f"<span class='au-bolla'>{t('sb.controlla_ora')}</span>"
                            "</span></span></div>",
                            unsafe_allow_html=True)
                st.button("", icon=":material/refresh:", key="controllaAgg",
                          type="tertiary", on_click=_controlla_aggiornamenti_ora)
            st.markdown(
                "<div class='au-piede'>"
                "<a href='https://github.com/Interstellar0verdrive/AnimeUp' "
                f"target='_blank'>{t('sb.about')}</a></div>",
                unsafe_allow_html=True)
        if app:
            st.button(t("sb.esci"), key="esci", on_click=_chiedi_uscita)
            return
        conferma_off = st.session_state.get("conferma_spegni")
        armato = (isinstance(conferma_off, float)
                  and time.time() - conferma_off < 10)
        if not armato:
            if st.button(t("sb.esci"), key="esci", help=t("sb.chiudi_aiuto")):
                st.session_state["conferma_spegni"] = time.time()
                st.rerun()
        elif st.button(t("sb.chiudi_conferma"), key="fermasi_app", type="primary"):
            st.session_state.pop("conferma_spegni", None)
            _spegni_interfaccia(congelata)


def _svg(percorso: str, lato: int = 22, tratto: float = 1.8) -> str:
    """Un'icona a tratto, nel colore del testo che la contiene."""
    return (f"<svg width='{lato}' height='{lato}' viewBox='0 0 24 24' fill='none' "
            f"stroke='currentColor' stroke-width='{tratto}' stroke-linecap='round' "
            f"stroke-linejoin='round' aria-hidden='true'>{percorso}</svg>")


_I_CARTELLA = "<path d='M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/><path d='M12 11v5M9.5 13.5 12 16l2.5-2.5'/>"
_I_MAC = "<rect x='4' y='5' width='16' height='11' rx='1.5'/><path d='M2 19h20'/>"
_I_GIU = "<path d='M12 5v14M6 13l6 6 6-6'/>"
_I_SPUNTA = "<path d='M4.5 12.5 9.5 17.5 19.5 7'/>"
_I_COPIA = "<rect x='8.5' y='8.5' width='11' height='11' rx='2'/><path d='M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5'/>"
_I_ESTERNO = "<path d='M14 4h6v6'/><path d='M20 4 11 13'/><path d='M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5'/>"
GUIDA_MODELLI = "https://interstellar0verdrive.github.io/AnimeUp/guide/deep-dives/models/"
_I_ATTENZIONE = "<path d='M12 4 2.5 20h19z'/><path d='M12 10v4.5M12 17.2v.1'/>"
_I_INFO = "<circle cx='12' cy='12' r='9'/><path d='M12 7.5v5.5M12 16.3v.1'/>"
_I_AVANTI = "<path d='M9 6l6 6-6 6'/>"
_I_CLESSIDRA = ("<path d='M6.5 3h11M6.5 21h11'/><path d='M8 3v3.2a4 4 0 0 0 1.6 3.2L12 11.5l2.4-2.1"
                "A4 4 0 0 0 16 6.2V3M8 21v-3.2a4 4 0 0 1 1.6-3.2l2.4-2.1 2.4 2.1a4 4 0 0 1 1.6 3.2V21'/>")


def _pagina_inizio() -> None:
    """Inizio: da dove si parte, e cosa serve.

    Due riquadri — le due cartelle, e questo Mac — e i quattro passi di un
    lotto. Il drag and drop non c'e': i video si copiano nella cartella col
    Finder, e compaiono da soli. Era la pagina dei Sorgenti senza video;
    ora e' sempre raggiungibile, anche a lotto pieno (deciso dall'utente).
    """
    _sorgenti_vuota(vuota=not load_library())


def _sorgenti_vuota(vuota: bool = True) -> None:
    app = os.environ.get("ANIMEUP_APP") == "1"
    voce_tar = taratura.carica()
    st.markdown(
        f"<div class='au-titolo-pagina'>{t('src.vuoto_titolo' if vuota else 'tab.Inizio')}</div>"
        f"<div class='au-sotto-pagina'>{t('src.vuoto_testo')}</div>",
        unsafe_allow_html=True)
    for nota in _note_cartelle_assenti():
        st.warning(nota)
    with st.container(key="vuotoGriglia", horizontal=True):
        with st.container(key="cartelleCard"):
            st.markdown(
                "<div class='au-card-testa'>"
                f"<div class='au-tessera'>{_svg(_I_CARTELLA)}</div><div>"
                f"<div class='au-card-titolo'>{t('src.cartelle_titolo')}</div>"
                f"<div class='au-card-testo'>"
                f"{t('src.cartelle_testo' if app else 'src.cartelle_testo_cartella')}"
                "</div></div></div>", unsafe_allow_html=True)
            with st.container(key="cartelleBox"):
                st.markdown(
                    f"<div class='au-occhio'>{t('src.eti_input')}"
                    f"<span class='au-osserva'><span></span>{t('src.osserva')}</span></div>",
                    unsafe_allow_html=True)
                with st.container(key="percInput", horizontal=True,
                                  vertical_alignment="center"):
                    st.markdown(_percorso(PATHS.input, "au-percorso-grande"),
                                unsafe_allow_html=True)
                    if st.button(t("src.apri_input"), key="apriInput", type="primary",
                                 icon=":material/folder_open:"):
                        try:
                            PATHS.input.mkdir(parents=True, exist_ok=True)
                        except OSError:
                            st.toast(t("src.disco_assente"))
                        else:
                            subprocess.run(["open", str(PATHS.input)], check=False)
                    if app:
                        st.button(t("src.cambia"), key="cambiaInput",
                                  on_click=_scegli_cartella, args=("input",),
                                  disabled=_motivo_blocco() is not None)
                st.markdown(
                    "<div class='au-freccia'>"
                    f"<span>{_svg(_I_GIU, 12, 2)}</span>"
                    f"<em>{t('src.freccia')}</em><i></i></div>"
                    f"<div class='au-occhio'>{t('src.eti_output')}</div>",
                    unsafe_allow_html=True)
                with st.container(key="percOutput", horizontal=True,
                                  vertical_alignment="center"):
                    st.markdown(_percorso(PATHS.output, "au-percorso-grande"),
                                unsafe_allow_html=True)
                    if app:
                        st.button(t("src.cambia"), key="cambiaOutput",
                                  on_click=_scegli_cartella, args=("output",),
                                  disabled=_motivo_blocco() is not None)
                st.markdown(f"<div class='au-card-nota'>{t('src.lavoro_accanto')}</div>",
                            unsafe_allow_html=True)
                if st.session_state.get("cartella_cambiata"):
                    st.caption(t("sb.cartella_riavvia",
                                 cartella=_breve(st.session_state["cartella_cambiata"])))
            formati = "".join(f"<span>{e}</span>" for e in
                              (".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".webm"))
            st.markdown(
                "<div class='au-tre'>"
                f"<div><div class='au-occhio'>{t('src.formati')}</div>"
                f"<div class='au-formati'>{formati}</div></div>"
                f"<div><div class='au-occhio'>{t('src.buono')}</div>"
                f"<p>{t('src.buono_testo')}</p></div>"
                f"<div><div class='au-occhio'>{t('src.non_gestito')}</div>"
                f"<p>{t('src.non_gestito_testo')}</p></div></div>",
                unsafe_allow_html=True)
        with st.container(key="questoMac"):
            st.markdown(
                "<div class='au-card-testa au-centrata'>"
                f"<div class='au-tessera'>{_svg(_I_MAC)}</div><div>"
                f"<div class='au-card-titolo'>{t('src.mac_titolo')}</div>"
                f"<div class='au-card-testo'>"
                f"{t('src.mac_pronto' if voce_tar else 'src.mac_un_passo')}</div>"
                "</div></div>", unsafe_allow_html=True)
            _blocco_taratura(voce_tar)
            liberi = int(gb_liberi(PATHS.output))
            mancanti = [n for n, _t, s in PATHS.portability_report() if s != "ok"]
            strumenti = (f"<span class='au-chip-ok'><span></span>{t('src.strumenti_ok')}</span>"
                         if not mancanti else
                         f"<span class='au-tag au-warn'>{t('src.strumenti_mancano')}</span>")
            st.markdown(
                "<div class='au-mac-righe'>"
                f"<div><div class='au-mac-riga'><b>{t('src.mac_chip')}</b></div>"
                f"<code class='au-mac-val'>{esc(_scheda_mac())}</code>"
                f"<p>{t('src.mac_chip_testo')}</p></div>"
                f"<div><div class='au-mac-riga'><b>{t('src.spazio')}</b>"
                f"<code>{liberi} GB</code></div>"
                f"<p>{t('src.spazio_testo')}</p></div>"
                f"<div><div class='au-mac-riga'><b>{t('src.strumenti')}</b>{strumenti}</div>"
                f"<p>{t('src.strumenti_testo')}</p></div></div>",
                unsafe_allow_html=True)

    if voce_tar:
        passo0 = (f"<div class='au-passo au-passo-fatto'><div class='au-passo-testa'>"
                  f"<span class='au-spunta'>{_svg(_I_SPUNTA, 9, 2.6)}</span>"
                  f"<b>{t('src.tar_fatta')}</b><small>{t('src.fatto')}</small></div>"
                  f"<p>{t('src.passo0_fatto')}</p></div>")
    else:
        passo0 = (f"<div class='au-passo au-passo-zero'><div class='au-passo-testa'>"
                  f"<code>0</code><b>{t('src.passo0')}</b>"
                  f"<small>{t('src.tar_prima')}</small></div>"
                  f"<p>{t('src.passo0_testo')}</p></div>")
    st.markdown(
        f"<div class='au-occhio au-passi-titolo'>{t('src.passi')}</div>"
        f"<div class='au-passi'>{passo0}"
        + ("<div class='au-passo au-passo-qui'><div class='au-passo-testa'>"
           f"<code>1</code><b>{t('tab.Sorgenti')}</b><small>{t('src.qui')}</small></div>"
           if vuota else
           "<div class='au-passo'><div class='au-passo-testa'>"
           f"<code>1</code><b>{t('tab.Sorgenti')}</b></div>") +
        f"<p>{t('src.passo1_testo')}</p></div>"
        "<div class='au-passo'><div class='au-passo-testa'>"
        f"<code>2</code><b>{t('tab.Confronto')}</b></div>"
        f"<p>{t('src.passo2_testo')}</p></div>"
        "<div class='au-passo'><div class='au-passo-testa'>"
        f"<code>3</code><b>{t('tab.Lavorazione')}</b></div>"
        f"<p>{t('src.passo3_testo')}</p></div></div>",
        unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _scheda_mac() -> str:
    """«Apple M4 Max · 64 GB · macOS 26.0»: cio' su cui valgono le stime."""
    import platform
    pezzi = [taratura.chip()]
    try:
        memoria = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                     text=True, timeout=5).stdout.strip())
        pezzi.append(f"{round(memoria / 1024 ** 3)} GB")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    versione = platform.mac_ver()[0]
    if versione:
        pezzi.append(f"macOS {versione}")
    return " · ".join(p for p in pezzi if p)


def _avanzamento_taratura() -> tuple[int, str]:
    """(percentuale, «circa N minuti») della taratura in corso."""
    s = taratura.stato_fondo() or {}
    pct = round(float(s.get("fraction") or 0) * 100)
    resta = s.get("left")
    manca = tn("lav.tar_resta", max(1, round(float(resta) / 60))) if resta is not None else ""
    return pct, manca


# La percentuale si aggiorna da sola mentre la taratura va avanti: fuori da
# un fragment restava ferma al giro in cui si era chiusa la finestra (visto
# dall'utente). Finita, un giro completo rimette la data.
@st.fragment(run_every=2)
def _tar_corso_sidebar() -> None:
    if not taratura.in_corso():
        st.rerun()
        return
    pct, _manca = _avanzamento_taratura()
    st.markdown(f"<span class='au-tar-corso'><i></i>{t('sb.taratura_corso', pct=pct)}</span>",
                unsafe_allow_html=True)


@st.fragment(run_every=2)
def _tar_corso_scheda() -> None:
    if not taratura.in_corso():
        st.rerun()
        return
    pct, manca = _avanzamento_taratura()
    st.markdown(
        f"<div class='au-tar-fatta au-tar-viva'><span class='au-spunta'>{_svg(_I_CLESSIDRA, 13, 2)}</span>"
        f"<span><b>{t('src.tar_corso')}</b>"
        f"<code>{pct}%{' · ' + manca if manca else ''}</code></span></div>",
        unsafe_allow_html=True)


def _blocco_taratura(voce_tar) -> None:
    """La taratura nel riquadro «Questo Mac»: da fare, fatta e quando, o in
    corso — in ciano con la clessidra e la percentuale, come nella sidebar,
    al posto della data della taratura di prima."""
    if taratura.in_corso():
        with st.container(key="tarFatta", horizontal=True, vertical_alignment="center"):
            _tar_corso_scheda()
            if st.button(t("sb.taratura_mostra"), key="ricalibraMac"):
                _modale_taratura()
        return
    if voce_tar:
        import datetime as _dt
        quando = _dt.datetime.fromtimestamp(voce_tar["quando"]).strftime(t("fmt.data_ora"))
        with st.container(key="tarFatta", horizontal=True, vertical_alignment="center"):
            st.markdown(
                f"<div class='au-tar-fatta'><span class='au-spunta'>{_svg(_I_SPUNTA, 12, 2.4)}</span>"
                f"<span><b>{t('src.tar_fatta')}</b>"
                f"<a class='au-tar-vedi' data-preme='vediTaratura' role='button' "
                f"title='{t('sb.taratura_vedi')}'><code>{quando}</code>"
                f"{_svg(_I_AVANTI, 10, 2.2)}</a></span></div>",
                unsafe_allow_html=True)
            if taratura.in_corso():
                if st.button(t("sb.taratura_mostra"), key="ricalibraMac"):
                    _modale_taratura()
            elif st.button(t("sb.taratura_ripeti"), key="ricalibraMac",
                           type="primary" if voce_tar.get("vecchia") else "secondary",
                           disabled=_motivo_blocco() is not None):
                st.session_state.pop("tar_fase", None)
                _modale_taratura()
        # La stessa nota gialla della barra laterale, qui accanto alla
        # taratura (chiesto dall'utente): la chiave e' la stessa, il testo
        # non si duplica.
        if voce_tar.get("vecchia"):
            st.markdown(f"<div class='au-tar-nota'>{t('sb.taratura_vecchia')}</div>",
                        unsafe_allow_html=True)
        return
    altro = taratura.di_altro_mac()
    with st.container(key="tarDaFare"):
        st.markdown(
            "<div class='au-tar-testa'>"
            f"<b>{t('src.tar_titolo')}</b><small>{t('src.tar_prima')}</small></div>"
            f"<p class='au-tar-testo'>{t('src.tar_testo')}</p>"
            + (f"<div class='au-tar-nota'>{t('sb.taratura_altro_mac', chip=esc(altro))}</div>"
               if altro else f"<div class='au-tar-nota'>{t('sb.taratura_mai_avviso')}</div>"),
            unsafe_allow_html=True)
        # In corso in sottofondo (finestra chiusa): «Mostra», attivo, come
        # nella barra laterale, invece di «Calibra ora» spento.
        if taratura.in_corso():
            if st.button(t("sb.taratura_mostra"), key="calibraMac", type="primary",
                         use_container_width=True):
                _modale_taratura()
        elif st.button(t("sb.taratura_esegui"), key="calibraMac", type="primary",
                       use_container_width=True,
                       disabled=_motivo_blocco() is not None):
            st.session_state.pop("tar_fase", None)
            _modale_taratura()


def page_sorgenti(cfg: dict) -> None:
    files = load_library()
    if not files:
        _sorgenti_vuota()
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

    # Lo stato dell'analisi serve gia' qui, per la fascia in alto. La coda
    # e' gia' stata accodata da `main`, per tutte le schede: qui si legge e
    # basta.
    lavoro = analizzatore()
    corrente, in_coda = lavoro.in_corso, lavoro.in_coda
    analizzati = sum(1 for f in files
                     if library.cached_report(Path(f["path"])) is not None)
    da_fare = len(in_coda) + (1 if corrente else 0)
    in_analisi = lavoro.al_lavoro or analizzati < len(files)
    # Conta i FILE, non gli avvisi: la chip della riga ha lo stesso aspetto ma
    # conta gli avvisi di quel file.
    con_avvisi = sum(1 for f in files
                     if (r := library.cached_report(Path(f["path"]))) and r.warnings())

    # Titolo a sinistra con la cartella che si sta guardando; a destra le
    # due azioni della pagina.
    with st.container(key="testaSorgenti", horizontal=True,
                      vertical_alignment="bottom"):
        st.markdown(
            f"<div class='au-titolo-pagina'>{t('src.titolo')}</div>"
            f"<div class='au-cartella-riga'>{t('src.da_elaborare')}"
            f"<code>{esc(_breve(PATHS.input))}</code>"
            f"<span class='au-osserva'><span></span>{t('src.osserva')}</span></div>",
            unsafe_allow_html=True)
        if st.button(t("src.apri_input"), key="apriInputPieno"):
            subprocess.run(["open", str(PATHS.input)], check=False)
        # Il fumetto nostro e non `help=`: quello di Streamlit e' un
        # rettangolo senza punta, diverso da tutti gli altri (utente).
        with st.container(key="rianRiga"):
            st.markdown("<span class='au-info au-a-destra au-rian-tip' aria-hidden='true'>"
                        f"{_bolla(t('src.rianalizza_tutti_aiuto'))}</span>",
                        unsafe_allow_html=True)
            if st.button(t("src.rianalizza_tutti"), key="rianTutti", disabled=in_analisi):
                analizzatore().accoda([Path(f["path"]) for f in files],
                                      approfondita=cfg.get("approfondita", True),
                                      rifai=True)
                st.rerun()

    # Una fascia sola: quanti file, quanto video, le soglie, gli avvisi, e a
    # destra l'analisi che avanza (in ciano: e' un processo attivo, non un
    # avviso).
    chip = []
    alta = sum(1 for f in files if f["height"] >= CLEAN_SOURCE_MIN_HEIGHT)
    if alta:
        chip.append(f"<span class='au-tag au-dim'>{alta} &ge; "
                    f"{CLEAN_SOURCE_MIN_HEIGHT}p</span>")
    if len(files) - alta:
        chip.append(f"<span class='au-tag au-dim'>"
                    f"{t('src.sotto_soglia', n=len(files) - alta, soglia=CLEAN_SOURCE_MIN_HEIGHT)}"
                    "</span>")
    if con_avvisi:
        chip.append(f"<span class='au-tag au-warn au-punto'>"
                    f"{tn('src.file_con_avvisi', con_avvisi)}</span>")
    destra = ""
    if in_analisi:
        # `max(0, ...)`: la coda puo' contenere file spariti da INPUT.
        fatti = max(0, min(analizzati, len(files) - da_fare))
        destra = (f"<span class='au-fascia-analisi'>"
                  f"{t('src.analisi_barra', fatti=fatti, totale=len(files))}"
                  f"<span class='au-barra'><span style='width:"
                  f"{fatti / max(1, len(files)) * 100:.0f}%'></span></span></span>")
    st.markdown(
        "<div class='au-fascia-sorgenti'>"
        f"<b>{tn('src.n_file', len(files))}</b>"
        f"<span class='au-meta'>{t('src.di_video', durata=hms(durata))}</span>"
        f"<i></i>{''.join(chip)}{destra}</div>", unsafe_allow_html=True)
    # Il contenitore c'e' SEMPRE, anche quando non c'e' niente da dire:
    # comparendo, la nota spostava tutto di una posizione e per un
    # fotogramma Streamlit assegnava il pannello aperto alla riga precedente.
    with st.container(key="fasciaAnalisi"):
        if in_analisi:
            # La fascia ciano del design: chi analizza, quanti mancano, e che
            # intanto le altre schede si possono gia' usare.
            # Lo stesso conto della barra qui sopra («analisi 0 di 3»).
            mancano = max(1, len(files) - max(0, min(analizzati, len(files) - da_fare)))
            st.markdown(
                "<div class='au-fascia-ciano'><span></span><span>"
                f"<b>{t('src.banner_analisi')}</b>\u00a0·\u00a0"
                f"{tn('src.banner_mancano', mancano)}. {t('src.gia_aperte')}</span></div>",
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
                # Ciano: e' un processo attivo, non un avviso.
                c[3].markdown(
                    "<div class='au-analisi-corso au-s-corso'><span></span>"
                    f"{t('src.riga_in_corso')}</div><div class='au-analisi-barra'>"
                    "<span></span></div>", unsafe_allow_html=True)
            elif str(path) in in_coda:
                # `in_coda` e' un insieme, senza un primo: indicizzarlo faceva
                # cadere la pagina con due file da analizzare (il primo avvio).
                prossimo = str(path) == analizzatore().prossimo
                c[3].markdown(
                    "<div class='au-analisi-coda'><span></span>"
                    f"{t('src.riga_in_coda')}"
                    f"{' · ' + t('src.prossimo') if prossimo else ''}</div>",
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
                blocco = f"<div class='au-meta'>{_pezzi(' · '.join(sintesi))}</div>"
                chip_riga = []
                if avvisi:
                    chip_riga.append(f"<span class='au-tag au-warn au-chip-riga au-punto'>"
                                     f"{tn('src.avvisi', len(avvisi))}</span>")
                if getattr(rep, "dedup_campione", None) is not None:
                    chip_riga.append(f"<span class='au-tag au-ok au-chip-riga'>"
                                     f"{t('src.chip_dedup', quota=f'{rep.dedup_campione:.0%}')}</span>")
                if chip_riga:
                    blocco += f"<div class='au-chip-righe'>{''.join(chip_riga)}</div>"
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
                        # Centrate in verticale: titolo, stato della misura e
                        # Rianalizza stanno su UNA linea (la chip a meta'
                        # altezza non era allineata a niente, vista dall'utente).
                        testa, fondo, azione = st.columns([3, 1.35, 1],
                                                          vertical_alignment="center")
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
                        # Misurata, non si ripete qui: la chip «deduplica» sta
                        # gia' nella riga, subito sopra (tolta su richiesta
                        # dell'utente).
                        if gia_misurata is not None:
                            pass
                        # «In corso» solo se lo e' DAVVERO. Su un file troppo
                        # corto la misura non riesce, la coda lo scarta e non
                        # riprova: la prima versione avrebbe lasciato «misura
                        # in corso...» a schermo per sempre, che e' una bugia
                        # tranquilla — di quelle che si scoprono solo
                        # aspettando invano.
                        elif sempre and (str(path) == lavoro.in_corso
                                         or str(path) in lavoro.in_coda):
                            fondo.markdown(
                                "<div class='au-hint'>"
                                f"{t('src.misura_in_corso')}</div>",
                                unsafe_allow_html=True)
                        elif sempre:
                            # Una chip come nel design, intera: come testo
                            # andava a capo nella colonna stretta.
                            fondo.markdown(
                                "<span class='au-tag au-dim au-nomis'>"
                                f"{t('src.dedup_non_misurabile')}</span>",
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
                                         key=f"rianalizzaFile{i}",
                                         help=t("src.rianalizza_aiuto")):
                            lavoro.accoda([path], rifai=True)
                            st.rerun()
                        _dettagli(rep)

    # La barra d'azione in fondo: cosa conviene fare adesso, e i due passi
    # successivi. L'azione principale e' una sola, il Confronto.
    if con_avvisi:
        messaggio = tn("src.barra_avvisi", con_avvisi)
    elif in_analisi:
        messaggio = t("src.barra_analisi")
    else:
        messaggio = t("src.barra_ok")
    with st.container(key="barraSorgenti", horizontal=True,
                      vertical_alignment="center"):
        st.markdown(f"<div class='au-barra-testo'>{messaggio}</div>",
                    unsafe_allow_html=True)
        st.button(t("src.vai_lavorazione"), key="vaiLavorazione",
                  on_click=_vai, args=(SEZIONI[2],))
        st.button(t("src.vai_confronto"), key="vaiConfronto", type="primary",
                  icon=":material/arrow_forward:", icon_position="right",
                  on_click=_vai, args=(SEZIONI[1],))

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
            f"{_pezzi(str(v))}</span></div>"
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
    """Il Confronto in tre passi: Spezzoni, Modelli, Risultati.

    Prima era una pagina sola con tutto insieme — modelli, spezzoni, barra e
    risultati in fondo — e non si capiva cosa fare e in che ordine
    (segnalato dall'utente, disegnato con lui in Claude Design, tavole CF1-
    CF4). Ogni passo ha una sola azione principale, sempre in fondo a destra.
    """
    files = load_library()
    if not files:
        st.info(t("conf.nessun_file"))
        return

    # Il file scelto vive in `conf_file`, non nella chiave della tendina: la
    # tendina sta solo nel primo passo, e Streamlit butta lo stato di un
    # widget che un giro non disegna — tornando al primo passo la tendina
    # ripartiva dal primo file mentre la pagina parlava di un altro (visto
    # provandola). Senza scelta: il file del confronto in corso o dell'ultimo.
    percorsi = [f["path"] for f in files]
    prescelto = st.session_state.get("conf_file")
    if prescelto not in percorsi:
        prescelto = (confronto.stato() or {}).get("file")
    if prescelto not in percorsi:
        prescelto = percorsi[0]
    st.session_state["conf_file"] = prescelto
    entry = next(f for f in files if f["path"] == prescelto)
    path = Path(entry["path"])
    passo = _passo_confronto(path)

    # Misurati il 12/08: 8,9s su un 360p, 37s su un 720p, 49s su un 1080p.
    with st.spinner(t("conf.analisi")):
        try:
            plan = plan_for(path, cfg, entry["height"])
        except (PlanError, OSError, FFmpegError, ValueError) as exc:
            _scheda_file(files, None, entry)
            st.markdown(
                f"<div class='au-errore'><b>{esc(str(exc))}</b></div>",
                unsafe_allow_html=True)
            return

    # La praticabilita' REALE di ogni modello con le impostazioni correnti,
    # calcolata UNA volta e rispettata da tutta la pagina.
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

    _pillole_confronto(path, passo)
    if passo == 1:
        _scheda_file(files, plan, entry)
        _passo_spezzoni(plan, path)
    elif passo == 2:
        _passo_modelli(plan, path, cfg, praticabili)
    else:
        _passo_risultati(plan, path)


def _scegli_file_confronto(attuale: str) -> None:
    """La tendina del file: la chiave cambia col file, cosi' il widget
    nuovo nasce sempre sul file giusto (`index=`) e non si porta dietro uno
    stato vecchio."""
    scelto = st.session_state.get(f"file_confronto_{attuale}")
    if scelto:
        st.session_state["conf_file"] = scelto


def _vai_passo(path: str, passo: int) -> None:
    st.session_state[f"conf_passo_{path}"] = passo


def _risultati_di(path: Path) -> list[dict]:
    """I risultati gia' pronti per questo file: dal disco (sopravvivono a un
    ricaricamento e alla finestra chiusa), o quelli tenuti in sessione."""
    s = confronto.stato()
    if s and s.get("file") == str(path) and s.get("results"):
        st.session_state[f"risultati_{path}"] = s["results"]
    return st.session_state.get(f"risultati_{path}") or []


def _passo_confronto(path: Path) -> int:
    """Il passo da mostrare: il terzo se un confronto gira su questo file,
    altrimenti quello scelto; la prima volta il terzo se ci sono gia'
    risultati, il primo se no."""
    chiave = f"conf_passo_{path}"
    s = confronto.stato() or {}
    if s.get("state") == confronto.IN_CORSO and s.get("file") == str(path):
        st.session_state[chiave] = 3
    elif chiave not in st.session_state:
        st.session_state[chiave] = 3 if _risultati_di(path) else 1
    return st.session_state[chiave]


def _pillole_confronto(path: Path, passo: int) -> None:
    """I tre passi in alto: fatti in verde (cliccabili per tornarci),
    quello attuale in ciano, quelli dopo in grigio. Durante il test non si
    torna indietro: spezzoni e modelli sono quelli che stanno girando."""
    s = confronto.stato() or {}
    gira = s.get("state") == confronto.IN_CORSO and s.get("file") == str(path)
    finito = passo == 3 and not gira and bool(_risultati_di(path))
    scelti = st.session_state.get(f"scelti_{path}") or set()
    modelli = st.session_state.get(f"modelli_{path}")
    n_mod = len(modelli) if modelli is not None else 1
    orig = st.session_state.get(f"originale_{path}", True)
    if gira and s.get("segmenti"):
        # Dopo un ricaricamento la sessione e' nuova: i numeri del test
        # che gira si leggono dal test stesso.
        pezzi = s["segmenti"]
        scelti = {(g["tipo"], g["tc"]) for g in pezzi}
        chiavi_t = {g["chiave"] for g in pezzi}
        orig = "original" in chiavi_t
        n_mod = len(chiavi_t - {"original"})
    dettagli = {
        1: tn("conf.p_scelti", len(scelti)) if scelti else "",
        2: (t("conf.p_ver_orig", n=n_mod) if orig else tn("conf.n_modelli", n_mod)),
        3: "",
    }
    pezzi = []
    for i, nome in ((1, t("conf.p_clip")), (2, t("conf.p_modelli")), (3, t("conf.p_risultati"))):
        fatto = i < passo or (i == 3 and finito)
        if fatto:
            segno = f"<span class='au-pp-segno'>{_svg(_I_SPUNTA, 12, 2.4)}</span>"
            classe = "au-pp au-pp-fatto"
        elif i == passo:
            segno = ("<span class='au-pp-segno au-pp-gira'></span>" if gira and i == 3
                     else f"<span class='au-pp-segno'>{i}</span>")
            classe = "au-pp au-pp-ora"
        else:
            segno = f"<span class='au-pp-segno'>{i}</span>"
            classe = "au-pp"
        testo = (f"<span class='au-pp-nome'>{esc(nome)}"
                 + (f"<small>{esc(dettagli[i])}</small>" if fatto and dettagli[i] else "")
                 + "</span>")
        if fatto and not gira and i != passo:
            pezzi.append(f"<a class='{classe}' data-preme='confPasso{i}' role='button'>"
                         f"{segno}{testo}</a>")
        else:
            pezzi.append(f"<span class='{classe}'>{segno}{testo}</span>")
    freccia = f"<span class='au-pp-freccia'>{_svg(_I_AVANTI, 12, 2)}</span>"
    with st.container(key="confPassi", horizontal=True, vertical_alignment="center"):
        st.markdown("<nav class='au-pp-riga'>" + freccia.join(pezzi)
                    + (f"<span class='au-pp-nota'>{t('conf.bloccati')}</span>" if gira else "")
                    + "</nav>", unsafe_allow_html=True)
        if passo == 3 and not gira:
            if st.button(t("conf.cambia_test"), key="cambiaTest"):
                _vai_passo(str(path), 2 if st.session_state.get(f"scelti_{path}") else 1)
                st.rerun()
            risultati = _risultati_di(path)
            if risultati and st.button(t("conf.mostra_finder"), key="finderRisultati"):
                cartelle = {str(Path(r["cartella"]).parent) for r in risultati}
                subprocess.run(["open", sorted(cartelle)[0]], check=False)
        # I pulsanti che premono le pillole: dentro la stessa riga, nascosti,
        # cosi' non aggiungono uno spazio vuoto sotto i passi.
        with st.container(key="confNascosti"):
            for i in (1, 2, 3):
                st.button(str(i), key=f"confPasso{i}", on_click=_vai_passo, args=(str(path), i))


def _scheda_file(files: list[dict], plan, entry: dict) -> None:
    """Il file da provare e i suoi tre numeri in un riquadro solo."""
    percorsi = [f["path"] for f in files]
    nomi = {f["path"]: f["name"] for f in files}
    with st.container(key="fileCard", horizontal=True):
        with st.container(key="campoFile"):
            st.markdown(f"<div class='au-occhio'>{t('conf.file_da_provare')}</div>",
                        unsafe_allow_html=True)
            st.selectbox(t("conf.file_da_provare"), percorsi,
                         index=percorsi.index(entry["path"]),
                         key=f"file_confronto_{entry['path']}",
                         format_func=lambda pth: nomi[pth],
                         label_visibility="collapsed",
                         on_change=_scegli_file_confronto, args=(entry["path"],))
        if plan is None:
            return
        # Stesso formato delle stime in Lavorazione: ore e minuti.
        if plan.est_best_seconds < plan.est_total_seconds * 0.95:
            intero = (f"≈ {stima_hm(plan.est_best_seconds)} "
                      f"<small>{t('conf.stat_da_a', max=stima_hm(plan.est_total_seconds))}</small>")
        else:
            intero = f"≈ {stima_hm(plan.est_total_seconds)}"
        st.markdown(
            "<div class='au-stat-file'>"
            f"<div><dt>{t('conf.stat_sorgente')}</dt><dd>{esc(entry['resolution'])}</dd></div>"
            f"<div><dt>{t('conf.stat_uscita')}</dt>"
            f"<dd>{plan.target_width}×{plan.target_height}</dd></div>"
            f"<div><dt>{t('conf.stat_episodio')}"
            f"{_icona_perche(t('conf.stat_episodio_aiuto'))}</dt>"
            f"<dd>{intero}</dd></div></div>", unsafe_allow_html=True)


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


def _recupera_spezzoni(plan, path: Path) -> None:
    """La scansione lascia traccia su disco: dopo un ricaricamento o un
    riavvio i minuti spesi non sono persi e non serve ricliccare."""
    chiave = f"cand_{path}"
    if chiave in st.session_state:
        return
    try:
        # Prima il deposito (l'elenco COMPLETO, tutti i lotti); se manca —
        # file scansionati prima che il deposito esistesse — si ripiega
        # sullo schedario del primo lotto.
        recuperati = preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS, PATHS)
        if not recuperati:
            schedario = preview._schedario(plan, 2, preview.DEFAULT_SECONDS, PATHS)
            if schedario.is_file():
                recuperati = preview._leggi_schedario(schedario, float(plan.fps))
        if recuperati:
            st.session_state[chiave] = recuperati
            # E anche la memoria dei GIA' VISTI: senza, «Trova altri»
            # ripescava gli stessi otto e la pagina li mostrava doppi.
            st.session_state[f"visti_{path}"] = tuple(c.start_frame for c in recuperati)
            st.session_state.setdefault(f"thumbs_{path}", {})
    except OSError:
        pass


def _cerca_spezzoni(plan, path: Path, area) -> None:
    """Cerca (altri) spezzoni difficili e li AGGIUNGE a quelli gia' in pagina."""
    chiave = f"cand_{path}"
    gia_visti = tuple(st.session_state.get(f"visti_{path}") or ())

    def _passo(testo: str) -> None:
        area.markdown(f"<div class='au-avviso' style='margin-top:8px'>"
                      f"<span class='au-rotella'></span>{esc(testo)}"
                      f"</div>", unsafe_allow_html=True)

    # NIENTE `st.status`: ha la forma di un accordion apribile con dentro il
    # nulla. Una riga di avviso con la rotella dice le stesse cose.
    _passo(t("conf.scansione"))
    try:
        nuovi = preview.find_candidates(plan, per_kind=2, on_step=_passo,
                                        escludi=gia_visti)
        avuti = list(st.session_state.get(chiave) or [])
        nuovi = preview.solo_nuovi(avuti, nuovi or [])
        if not nuovi:
            if avuti:
                area.warning(t("conf.nessun_altro"), icon="ℹ️")
                return
            # Nessuno spezzone: si ridisegna, e la pagina lo dice invece di
            # restare sulla riga della scansione.
            st.session_state[chiave] = []
            st.rerun()
        tutti = avuti + nuovi
        st.session_state[chiave] = tutti
        st.session_state[f"visti_{path}"] = gia_visti + tuple(c.start_frame for c in nuovi)
        st.session_state.setdefault(f"thumbs_{path}", {})
        # L'elenco completo va su disco: e' cio' che la pagina ritrova dopo
        # un ricaricamento, lotti successivi compresi.
        preview.scrivi_deposito(plan, tutti, 2, preview.DEFAULT_SECONDS, PATHS)
    except Exception as exc:                   # noqa: BLE001
        area.error(t("conf.errore_analisi", errore=exc), icon="⚠️")
        return
    st.rerun()


def _scelta_iniziale(candidati) -> set:
    """Al primo giro due spezzoni gia' scelti, mai di piu': uno in movimento
    e uno scuro o fermo (il consiglio di sempre), cosi' il passo e' subito
    valido e si capisce cosa va scelto."""
    scelti: list[str] = []
    for tipi in (("motion",), ("dark", "static")):
        for c in candidati:
            if c.kind.value in tipi and c.slug not in scelti:
                scelti.append(c.slug)
                break
    if not scelti and candidati:
        scelti.append(candidati[0].slug)
    return set(scelti[:2])


def _passo_spezzoni(plan, path: Path) -> None:
    st.markdown(
        f"<div class='au-passo-titolo'>{t('conf.c_titolo')}</div>"
        f"<div class='au-passo-testo'>{t('conf.c_testo')}<br>{t('conf.c_testo2')}</div>",
        unsafe_allow_html=True)
    _recupera_spezzoni(plan, path)
    chiave = f"cand_{path}"
    # Il posto della riga d'avviso esiste SEMPRE, qui, vuoto quando non
    # serve: creato solo al bisogno, Streamlit lo metteva al posto della
    # prima riga di spezzoni, che spariva durante la ricerca.
    area = st.empty()
    if chiave not in st.session_state:
        # Si cercano da soli, appena scelto il file: prima serviva un clic
        # su un pulsante che non diceva che dopo andavano anche scelti.
        _cerca_spezzoni(plan, path, area)
        return
    candidati = st.session_state.get(chiave) or []
    if not candidati:
        st.warning(t("conf.nessuno_spezzone"))
        _barra_spezzoni(path, [], [])
        return

    thumbs = st.session_state.setdefault(f"thumbs_{path}", {})
    if f"scelti_{path}" not in st.session_state:
        st.session_state[f"scelti_{path}"] = _scelta_iniziale(candidati)
        for cand in candidati:
            st.session_state[f"c_{path}_{cand.slug}"] = (
                cand.slug in st.session_state[f"scelti_{path}"])
    scelti = st.session_state[f"scelti_{path}"]

    # Spezzoni animati e non fermi immagine: su un fotogramma solo non si vede
    # la differenza fra una scena ferma e una in movimento. Costano poco e
    # restano su disco, quindi si pagano una volta.
    mancanti = [c for c in candidati if c.slug not in thumbs]
    if mancanti:
        area.markdown(f"<div class='au-avviso' style='margin-top:8px'>"
                      f"<span class='au-rotella'></span>"
                      f"{esc(tn('conf.estraggo', len(mancanti)))}</div>",
                      unsafe_allow_html=True)
        for cand in mancanti:
            # La durata sta nel nome: cambiarla senza cambiare il nome
            # avrebbe continuato a servire i ritagli vecchi dalla cache.
            secondi = int(round(cand.frames / cand.fps))
            base = PATHS.previews / "clips" / f"{path.stem}_{cand.slug}_{secondi}s"
            clip = preview.animation(plan, cand, base.with_suffix(".mp4"))
            # Se l'estrazione fallisce resta il fermo immagine.
            thumbs[cand.slug] = clip or preview.thumbnail(plan, cand, base.with_suffix(".jpg"))
        st.rerun()

    regole_clip: list[str] = []
    for inizio in range(0, len(candidati), 4):
        for j, (col, cand) in enumerate(zip(st.columns(4), candidati[inizio:inizio + 4])):
            with col:
                # La chiave sta sul contenitore perché il CSS possa accendere
                # la card intera quando la casella dentro è spuntata.
                with st.container(key=f"clip{inizio + j}"):
                    media = thumbs.get(cand.slug)
                    if media and media.suffix == ".mp4":
                        if not _video_ciclico(media):
                            st.video(str(media), loop=True, autoplay=True, muted=True)
                    elif media:
                        st.image(str(media), use_container_width=True)
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
                        f"<div class='au-c-prove'>{esc(t('conf.prova', prove=cand.kind.tests))}.</div>",
                        unsafe_allow_html=True)
    st.markdown("<style>" + "\n".join(regole_clip) + "</style>", unsafe_allow_html=True)
    st.session_state[f"scelti_{path}"] = scelti

    # Sotto l'ultima riga: man mano che gli spezzoni crescono, scende con loro.
    with st.container(key="trovaAltriRiga", horizontal=True, horizontal_alignment="center"):
        if st.button(t("conf.trova_altri"), key="trovaAltri"):
            _cerca_spezzoni(plan, path, area)
    prescelti = [c for c in candidati if c.slug in scelti]
    _barra_spezzoni(path, prescelti, candidati)


def _barra_spezzoni(path: Path, prescelti: list, candidati: list) -> None:
    with st.container(key="barraConfronto", horizontal=True, vertical_alignment="center"):
        if prescelti:
            elenco = t("conf.e").join(
                f"{t(f'conf.tipo.{c.kind.value}').capitalize()} {c.timecode}" for c in prescelti) \
                if len(prescelti) <= 2 else ", ".join(
                f"{t(f'conf.tipo.{c.kind.value}').capitalize()} {c.timecode}" for c in prescelti[:3]) \
                + ("…" if len(prescelti) > 3 else "")
            secondi = int(round(sum(c.frames / c.fps for c in prescelti)))
            st.markdown(
                f"<div class='au-barra-due'><span class='au-barra-num'>{len(prescelti)}</span><div>"
                f"<b>{tn('conf.c_scelti', len(prescelti))}</b>"
                f"<span>{esc(t('conf.c_secondi', elenco=elenco, sec=secondi))}</span></div></div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div class='au-barra-due'><div><b>{t('conf.c_nessuno')}</b>"
                f"<span>{t('conf.c_nessuno_nota')}</span></div></div>",
                unsafe_allow_html=True)
        st.button(t("conf.avanti_modelli"), key="avantiModelli", type="primary",
                  icon=":material/arrow_forward:", icon_position="right",
                  disabled=not prescelti, on_click=_vai_passo, args=(str(path), 2))


def _consigli(plan, cfg: dict, praticabili: dict[str, str]) -> None:
    """«Suggerimenti per la scelta del modello»: la regola generale con la
    fascia di questo file accesa, e in fondo l'approfondimento tecnico della
    guida (non piu' in vista accanto ai modelli: la guida e' tecnica, e a chi
    e' incerto bastano questi suggerimenti — deciso con l'utente)."""
    h = plan.source.geometry.height
    righe = []
    for indice, (fascia, colore, modello, testo) in enumerate(
            perche_generale(plan.target_height, bool(cfg.get("forza")))):
        qui = indice == _fascia_del_file(h)
        righe.append(
            f"<div class='au-regola au-p-{colore}{' au-qui' if qui else ''}'>"
            f"<div class='au-p-fascia'>{esc(fascia)}</div>"
            f"<div class='au-p-mod'>{esc(modello)}"
            + (f"<span class='au-qui-chip'>{t('conf.questo_file_chip')}</span>" if qui else "")
            + f"</div><div class='au-p-testo'>{esc(testo)}</div></div>")
    with st.expander(f"{t('conf.consigli')} · {t('conf.consigli_sotto', h=h)}", key="consigli"):
        st.markdown(
            "<div class='au-regole'>" + "".join(righe) + "</div>"
            f"<div class='au-regole-nota'>{t('conf.regola_nota')} "
            f"<a class='au-guida' href='{GUIDA_MODELLI}' target='_blank' rel='noopener'>"
            f"{t('conf.guida_tecnica')}{_svg(_I_ESTERNO, 12, 2)}</a></div>",
            unsafe_allow_html=True)


def _fascia_del_file(h: int) -> int:
    """La riga di `perche_generale` in cui cade questo file (0, 1 o 2)."""
    if h >= CLEAN_SOURCE_MIN_HEIGHT:
        return 2
    if h >= ALTEZZA_INCERTA:
        return 1
    return 0


def _schede_modelli(plan, path: Path, praticabili: dict[str, str]) -> list[str]:
    """I modelli come schede spuntabili: cosa sono, quando sono la scelta
    giusta, e quanto costano.

    Ogni scheda ha la sua chip nello stesso punto (prima ce l'aveva solo il
    consigliato, e il suo testo stava piu' in basso degli altri): verde per
    il consigliato, grigia con «ideale per …» per gli altri. Il nome sta su
    due righe — famiglia e variante — cosi' le schede restano allineate a
    qualunque larghezza.
    """
    giudizi = (plan.recommendation.giudizi or {}) if plan.recommendation else {}
    for k in CATALOG:
        if praticabili.get(k) and st.session_state.get(f"prova_{k}_{path}"):
            st.session_state[f"prova_{k}_{path}"] = False
    # Lo specchio `modelli_` tiene la scelta fra un'uscita e un ritorno; vale
    # solo dopo che l'utente ha toccato le caselle. Prima: SOLO il consigliato.
    toccato = st.session_state.get(f"tocco_modelli_{path}")
    memoria = st.session_state.get(f"modelli_{path}") if toccato else None
    voluti = memoria if memoria is not None else {plan.model_key}
    if voluti and all(praticabili.get(k) for k in voluti):
        voluti = {plan.model_key}
    src_mpx = plan.source.geometry.width * plan.source.geometry.height / 1e6
    chiavi: list[str] = []
    with st.container(key="modelli", horizontal=True):
        for k, modello in CATALOG.items():
            morta = bool(praticabili.get(k))
            scala = preview.scale_for(k, plan)
            if morta:
                classe, testo = "au-dim", t("conf.chip_non_arriva", altezza=plan.target_height)
                meta = t("conf.solo_scala", scala=scala,
                         altezza=plan.source.geometry.height * scala)
            else:
                if k == plan.model_key:
                    classe, testo = "au-ok", t("conf.chip_ok")
                elif giudizi.get(k) == "verifica":
                    classe, testo = "au-warn", t("conf.chip_verifica")
                else:
                    classe, testo = "au-grigio", t(f"conf.ideale.{k}")
                mpx_s = modello.throughput.get(scala, min(modello.throughput.values()))
                velocita = mpx_s / src_mpx if src_mpx else None
                meta = (t("conf.velocita", fps=f"{velocita:.1f}",
                          durata=stima_hm(plan.frames / velocita)) if velocita else "")
            famiglia, _, variante = modello.label.partition(" ")
            with st.container(key=f"mod_{k}"):
                acceso = st.checkbox(
                    famiglia, value=(k in voluti) and not morta,
                    key=f"prova_{k}_{path}", disabled=morta,
                    help=praticabili.get(k) or None,
                    on_change=_tocca_modelli, args=(str(path),))
                desc = modello.description
                st.markdown(
                    f"<div class='au-m-var'>{esc(variante)}</div>"
                    f"<span class='au-tag {classe}'>{esc(testo)}</span>"
                    f"<div class='au-m-desc'>{esc(desc[:1].upper() + desc[1:])}</div>"
                    f"<div class='au-m-vel'>{_pezzi(meta)}</div>",
                    unsafe_allow_html=True)
            if acceso and not morta:
                chiavi.append(k)
    if toccato:
        st.session_state[f"modelli_{path}"] = set(chiavi)
    else:
        st.session_state.setdefault(f"modelli_{path}", set(chiavi))
    return chiavi


def _passo_modelli(plan, path: Path, cfg: dict, praticabili: dict[str, str]) -> None:
    st.markdown(
        f"<div class='au-passo-titolo'>{t('conf.m_titolo')}</div>"
        f"<div class='au-passo-testo'>{t('conf.m_testo')}<br>{t('conf.m_testo2')}</div>",
        unsafe_allow_html=True)
    _consigli(plan, cfg, praticabili)
    chiavi = _schede_modelli(plan, path, praticabili)
    riferimento = st.session_state.get(f"originale_{path}", True)
    with st.container(key="confOriginale"):
        nuovo = st.toggle(t("conf.includi_originale"), value=riferimento,
                          key=f"tog_originale_{path}")
        st.markdown(f"<div class='au-orig-nota'>{t('conf.includi_aiuto')}</div>",
                    unsafe_allow_html=True)
    if nuovo != riferimento:
        st.session_state[f"originale_{path}"] = nuovo
        st.rerun()

    candidati = st.session_state.get(f"cand_{path}") or []
    scelti = st.session_state.get(f"scelti_{path}") or set()
    prescelti = [c for c in candidati if c.slug in scelti]
    varianti = preview.variants_for(*chiavi, reference=riferimento)
    # Non durante una coda: si dividerebbero la GPU, e i tempi delle clip
    # (quelli che stimano l'episodio intero) uscirebbero falsi.
    occupato = _motivo_blocco() in ("lavoro", "taratura")
    premi = False
    with st.container(key="barraConfronto", horizontal=True, vertical_alignment="center"):
        if len(varianti) < 2:
            st.markdown(
                f"<div class='au-barra-due au-barra-giallo'><div><b>{t('conf.solo_una')}</b>"
                f"<span>{t('conf.solo_una_nota')}</span></div></div>",
                unsafe_allow_html=True)
        elif not prescelti:
            st.markdown(
                f"<div class='au-barra-due'><div><b>{t('conf.c_nessuno')}</b>"
                f"<span>{t('conf.c_nessuno_nota')}</span></div></div>",
                unsafe_allow_html=True)
        else:
            totale = preview.estimate_seconds(plan, prescelti, varianti)
            nomi = [t("conf.originale") if v.is_reference else CATALOG[v.key].label
                    for v in sorted(varianti, key=lambda v: not v.is_reference)]
            elenco = (", ".join(nomi[:-1]) + t("conf.e") + nomi[-1]) if len(nomi) > 1 else nomi[0]
            st.markdown(
                f"<div class='au-barra-due'><div>"
                f"<b>{tn('conf.n_spezzoni', len(prescelti))} × {tn('conf.n_versioni', len(varianti))}"
                f"<em> · {t('conf.circa', tempo=stima_hm(totale))}</em></b>"
                f"<span>{esc(t('conf.m_seconda', elenco=elenco))}</span></div></div>",
                unsafe_allow_html=True)
        st.button(t("conf.indietro_clip"), key="indietroClip",
                  icon=":material/arrow_back:", on_click=_vai_passo, args=(str(path), 1))
        premi = st.button(t("conf.avvia_test"), key="elaboraClip", type="primary",
                          icon=":material/arrow_forward:", icon_position="right",
                          disabled=len(varianti) < 2 or not prescelti or occupato,
                          help=t("conf.occupato") if occupato else None)
    if premi:
        _avvia_confronto(cfg, plan.source.geometry.height, path, prescelti, varianti)
        _vai_passo(str(path), 3)
        st.rerun()


def _avvia_confronto(cfg: dict, altezza: int, path: Path, candidati,
                     varianti) -> None:
    """Chiede il confronto al processo di fondo (vedi `confronto`).

    Le stesse impostazioni con cui la pagina ha costruito il suo piano, cosi'
    il processo ne costruisce uno identico.
    """
    nota = _deduplica_dei_file_avviati().get(path.name) if cfg["dedup"] else None
    richiesta = {
        "file": str(path),
        "plan": {"altezza": cfg["altezza"], "crf": cfg["crf"],
                 "preset": cfg["preset"], "disco": cfg["disco"],
                 "dedup": cfg["dedup"], "denoise": cfg["denoise"],
                 "forza": cfg["forza"], "modello": model_for(str(path), altezza),
                 "dedup_nota": list(nota) if nota else None},
        "clips": [{"kind": c.kind.value, "start_frame": c.start_frame,
                   "frames": c.frames, "motion": c.motion,
                   "brightness": c.brightness, "reason": c.reason}
                  for c in candidati],
        "models": [v.key for v in varianti if not v.is_reference],
        "reference": any(v.is_reference for v in varianti),
    }
    if confronto.avvia(richiesta):
        st.session_state.pop("conf_ferma_conferma", None)
    else:
        st.warning(t("conf.gia_in_corso"), icon="⚠️")


def _avvisi_confronto(path: Path) -> None:
    """Com'e' finito l'ultimo giro su questo file, se non e' finito bene."""
    s = confronto.stato()
    if not s or s.get("file") != str(path) or s.get("state") == confronto.IN_CORSO:
        return
    if s.get("state") == confronto.FERMATO:
        st.info(t("conf.fermato"), icon="⏹️")
    elif s.get("state") == confronto.INTERROTTO:
        st.warning(t("conf.interrotto", pulsante=t("conf.avvia_test")), icon="⚠️")
    for g in s.get("failures") or []:
        st.error(g, icon="⚠️")


def _nome_versione(k: str) -> str:
    return t("conf.originale") if k == "original" else CATALOG[k].label


def _passo_risultati(plan, path: Path) -> None:
    s = confronto.stato() or {}
    gira = s.get("state") == confronto.IN_CORSO and s.get("file") == str(path)
    risultati = _risultati_di(path)
    if gira:
        st.markdown(
            f"<div class='au-passo-titolo'>{esc(t('conf.r_titolo_corso', nome=path.name))}</div>"
            f"<div class='au-passo-testo'>{t('conf.r_corso_1')}<br>{t('conf.r_corso_2')}</div>",
            unsafe_allow_html=True)
    else:
        testa = f"<div class='au-passo-titolo'>{esc(t('conf.r_titolo', nome=path.name))}</div>"
        if risultati:
            chiavi_r = preview.ordine_lettura(risultati[0].get("file") or {})
            nomi = [t("conf.e_originale") if k == "original" else CATALOG[k].label
                    for k in chiavi_r if k == "original" or k in CATALOG]
            nomi = [n for n in nomi if n != t("conf.e_originale")] + (
                [t("conf.e_originale")] if "original" in chiavi_r else [])
            modelli_testo = (", ".join(nomi[:-1]) + t("conf.e") + nomi[-1]
                             if len(nomi) > 1 else "".join(nomi))
            testa += (f"<div class='au-passo-testo'>"
                      f"{esc(t('conf.r_testo1', clip=tn('conf.n_spezzoni', len(risultati)), modelli=modelli_testo))}"
                      f"<br>{t('conf.r_testo2')}</div>")
        # Titolo e testo in un blocco solo: separati, Streamlit ci metteva
        # 18px in mezzo e 4 sotto, al contrario della tavola.
        st.markdown(testa, unsafe_allow_html=True)
        _avvisi_confronto(path)
    with st.container(key="risultati"):
        for res in risultati:
            _clip_risultato(res, plan, path)
    st.session_state["conf_pezzi_visti"] = bool(s.get("segmenti")) if gira else False
    if gira:
        # Lo spezzone in lavorazione e quelli che aspettano: i risultati
        # compaiono uno spezzone alla volta, appena pronti.
        fatti = {(r.get("tipo"), r.get("intervallo", "").split(" ")[0]) for r in risultati}
        visti = []
        for seg in s.get("segmenti") or []:
            chiave = (seg["tipo"], seg["tc"])
            if chiave in fatti or chiave in visti:
                continue
            visti.append(chiave)
        for i, (tipo, tc) in enumerate(visti):
            stato = t("conf.in_lavorazione") if i == 0 else t("conf.in_attesa")
            st.markdown(
                f"<div class='au-attesa{' au-attesa-ora' if i == 0 else ''}'>"
                f"<b>{esc(t(f'conf.tipo.{tipo}').capitalize())}</b><code>{esc(tc)}</code>"
                f"<span>{esc(stato)}</span></div>", unsafe_allow_html=True)
    with st.container(key="barraConfronto", horizontal=True, vertical_alignment="center"):
        if confronto.in_corso():
            _avanzamento_confronto(str(path), len(risultati))
        elif risultati:
            durata = max(0.0, float(s.get("ended") or 0) - float(s.get("started") or 0)) \
                if s.get("file") == str(path) else 0.0
            st.markdown(
                f"<div class='au-barra-pronto'><span class='au-spunta'>{_svg(_I_SPUNTA, 12, 2.4)}</span>"
                f"<div><b>{t('conf.pronto')}"
                + (f"<em> · {t('conf.pronto_tempo', clip=tn('conf.n_spezzoni', len(risultati)), tempo=hms(durata))}</em>"
                   if durata else "")
                + f"</b><span>{t('conf.pronto_nota')}</span></div></div>",
                unsafe_allow_html=True)
            st.button(t("conf.avanti_lavorazione"), key="avantiLavorazione",
                      type="primary", icon=":material/arrow_forward:",
                      icon_position="right", on_click=_vai, args=(SEZIONI[2],))
        else:
            st.markdown(f"<div class='au-barra-due'><div><b>{t('conf.nessun_risultato')}</b></div></div>",
                        unsafe_allow_html=True)
            st.button(t("conf.indietro_clip"), key="indietroClip3",
                      icon=":material/arrow_back:", on_click=_vai_passo, args=(str(path), 1))


@st.fragment(run_every=2)
def _avanzamento_confronto(path: str, n_risultati: int = 0) -> None:
    """Il test in corso, riletto ogni due secondi: TUTTO il test e non solo
    la versione che gira, con una tacca per versione come i blocchi della
    Lavorazione. Quando arriva uno spezzone nuovo (o il test finisce) si
    ridisegna la pagina intera, che lo mostra."""
    s = confronto.stato()
    if not s or s.get("state") != confronto.IN_CORSO:
        st.rerun()
        return
    # Uno spezzone nuovo pronto, o i pezzi del test appena scritti (servono
    # alla pagina per mostrare cosa gira e cosa aspetta): pagina intera.
    nuovi_pezzi = bool(s.get("segmenti")) and not st.session_state.get("conf_pezzi_visti")
    if s.get("file") == path and (len(s.get("results") or []) != n_risultati or nuovi_pezzi):
        st.session_state["conf_pezzi_visti"] = True
        st.rerun()
        return
    totale = max(int(s.get("total") or 0), 1)
    fatte = int(s.get("done") or 0)
    quota = confronto.quota(s)
    altro = (f"<div class='au-prova-nota'>{t('conf.altro_file', nome=esc(Path(s['file']).name))}</div>"
             if s.get("file") != path else "")
    with st.container(key="provaTesta", horizontal=True, vertical_alignment="center"):
        st.markdown(
            "<div class='au-prova-testa'><span></span>"
            f"<b>{t('conf.prova_titolo')}<em> · {t('conf.del_totale', pct=f'{quota:.0%}')}</em></b>"
            f"<small>{t('conf.versione_di', n=min(fatte + 1, totale), tot=totale)}</small>"
            "</div>", unsafe_allow_html=True)
        # Due clic, come gli altri Ferma: il primo chiede conferma per dieci
        # secondi, il secondo ferma davvero.
        if time.time() - st.session_state.get("conf_ferma_conferma", 0) > 10:
            if st.button(t("conf.ferma"), key="ferma_confronto"):
                st.session_state["conf_ferma_conferma"] = time.time()
                st.rerun(scope="fragment")
        elif st.button(t("conf.ferma_conferma"), key="ferma_confronto_ok", type="primary"):
            st.session_state.pop("conf_ferma_conferma", None)
            confronto.ferma()
            st.rerun(scope="fragment")
    st.markdown(_barra_segmenti(s, quota) + altro, unsafe_allow_html=True)


def _barra_segmenti(s: dict, quota: float) -> str:
    """La barra del test intero con le sue tacche e, sotto, cosa e' fatto e
    cosa gira (deciso con l'utente). Una tacca piena fra uno spezzone e
    l'altro, una sottile fra le sue versioni; sotto, il nome di ogni
    spezzone (fatto, in corso, in attesa) e una riga «Ora: …» con la
    versione che gira. Oltre i 12 spezzoni i nomi non ci stanno piu' e
    resta solo la riga.

    Le etichette sono per spezzone e non per versione: l'originale pesa un
    decimo di un modello, e la sua etichetta in un pezzo cosi' corto non si
    leggeva (visto provandola)."""
    segs = s.get("segmenti") or []
    peso_tot = sum(float(g.get("peso") or 0) for g in segs) or 1.0
    fatte = int(s.get("done") or 0)
    frazione = float(s.get("fraction") or 0)
    clip_di = [(g["tipo"], g["tc"]) for g in segs]
    tacche, sx = [], 0.0
    for i, g in enumerate(segs[:-1]):
        sx += float(g.get("peso") or 0) / peso_tot * 100
        piena = clip_di[i] != clip_di[i + 1]
        tacche.append(f"<i class='{'au-tacca' if piena else 'au-tacca-fine'}' "
                      f"style='left:{sx:.2f}%'></i>")
    barra = (f"<div class='au-prova-barra au-con-tacche'><span style='width:{quota * 100:.1f}%'></span>"
             + "".join(tacche) + "</div>")
    if not segs:
        return barra
    clip: list = []
    for chiave, g in zip(clip_di, segs):
        if not clip or clip[-1][0] != chiave:
            clip.append([chiave, 0.0, 0])
        clip[-1][1] += float(g.get("peso") or 0)
        clip[-1][2] += 1
    righe = ""
    if len(clip) <= 12:
        indice, celle = 0, []
        for (tipo, tc), peso, quante in clip:
            finita = indice + quante <= fatte
            corrente = indice <= fatte < indice + quante
            classe = "au-seg-fatto" if finita else "au-seg-ora" if corrente else ""
            celle.append(f"<div style='flex:{peso / peso_tot:.4f}'><span class='{classe}'>"
                         f"{'✓ ' if finita else ''}{esc(t(f'conf.tipo.{tipo}').capitalize())} {esc(tc)}"
                         "</span></div>")
            indice += quante
        righe = f"<div class='au-seg-righe'>{''.join(celle)}</div>"
    if fatte < len(segs):
        g = segs[fatte]
        ver = t("conf.originale") if g["chiave"] == "original" else (
            CATALOG[g["chiave"]].label if g["chiave"] in CATALOG else g["chiave"])
        tipo = t(f"conf.tipo.{g['tipo']}").capitalize()
        ora = f"{tipo} {g['tc']} — {ver} · {frazione:.0%}"
        righe += (f"<div class='au-prova-nota'>{t('conf.ora')} "
                  f"<code>{esc(ora)}</code></div>")
    return barra + righe


# Una funzione e non un dizionario fisso: i testi seguono la lingua attiva.
def _spiega_indicatori() -> dict[int, str]:
    return {0: t("conf.spiega_dettaglio"), 1: t("conf.spiega_rumore")}


def _tabella_confronto(modelli: list[dict], dedup,
                       riferimento: bool = True) -> None:
    """Tempi e indicatori di una clip, affiancati: a sinistra quanto costa
    ogni modello, a destra cosa fa all'immagine.

    La colonna «rispetto al piu' veloce» compare solo da due modelli in su:
    con un modello solo contro l'ingrandito sarebbe rumore.
    """
    quota, codice = (dedup or (0.0, ""))
    come = t(f"conf.dedup_come.{codice}") if codice in ("misurata", "storico",
                                                         "prevista") else ""
    piu_veloce = min(m["secondi"] for m in modelli)
    righe = []
    for m in modelli:
        scarto = ""
        if len(modelli) > 1:
            d = m["secondi"] / piu_veloce - 1
            scarto = (t("conf.piu_veloce") if d < 0.005
                      else t("conf.piu_tempo", pct=f"{d:.0%}"))
        nome = m.get("etichetta") or m["nome"]
        righe.append(
            f"<tr><td class='au-cnf-nome'>{esc(nome)}</td>"
            f"<td>{stima_hm(m['secondi'])}</td>"
            f"<td>≈ {stima_hm(m['intero'])}</td>"
            + (f"<td class='au-cnf-scarto'>{esc(scarto)}</td>" if len(modelli) > 1 else "")
            + "</tr>")
    proiezione = (t("conf.proiezione_breve", pct=f"{quota:.0%}", come=come)
                  if come else t("conf.proiezione", come=t("conf.dedup.spenta")))
    tempi = (f"<div class='au-occhio'>{t('conf.tempo_modello')}</div>"
             "<table class='au-cnf'>"
             f"<thead><tr><th>{t('conf.th_modello')}</th><th>{t('conf.th_spezzone')}</th>"
             f"<th>{t('conf.th_episodio')}</th>"
             + (f"<th>{t('conf.th_vs')}</th>" if len(modelli) > 1 else "")
             + f"</tr></thead><tbody>{''.join(righe)}</tbody></table>"
             f"<div class='au-cnf-nota'>{esc(proiezione)}</div>")

    def _c(m, i):
        q = m.get("metriche")
        return q[i] if q and len(q) > i else None

    colonne = [(i, testo) for i, testo in
               ((0, t("conf.col_dettaglio")), (1, t("conf.col_rumore")))
               if any(_c(m, i) is not None for m in modelli)]
    if not colonne:
        # Niente indicatori: si dice PERCHE', invece di sparire in silenzio.
        indicatori = (f"<div class='au-occhio'>{t('conf.indicatori_titolo')}</div>"
                      f"<div class='au-cnf-nota'>"
                      f"{t('conf.ind_no_rif') if not riferimento else t('conf.ind_no_aree')}</div>")
    else:
        # La barra arriva fino a 4 volte l'ingrandimento semplice: il segno
        # bianco al 25% e' il suo 100%, con l'etichetta sotto.
        blocchi = []
        for m in modelli:
            barre = []
            for i, testo in colonne:
                v = _c(m, i)
                if v is None:
                    barre.append(f"<div class='au-ind'><span>{esc(testo)}</span>"
                                 "<i><u></u></i><b>—</b></div>")
                    continue
                barre.append(
                    f"<div class='au-ind'><span>{esc(testo)}</span>"
                    f"<i><em style='width:{min(v / 4, 1) * 100:.1f}%'></em><u></u></i>"
                    f"<b>{v * 100:.0f}%</b></div>")
            nome = m.get("etichetta") or m["nome"]
            blocchi.append(f"<div class='au-ind-modello'>{esc(nome)}</div>" + "".join(barre))
        spiega = _spiega_indicatori()
        indicatori = (f"<div class='au-occhio'>{t('conf.indicatori_titolo')}"
                      f"{_icona_perche(' '.join(spiega[i] for i, _t in colonne))}</div>"
                      + "".join(blocchi)
                      + "<div class='au-ind au-ind-scala'><span></span><i><s>100%</s></i><b></b></div>"
                      + f"<div class='au-cnf-nota'>{t('conf.tacca')}</div>")
    st.markdown(f"<div class='au-res-due'><div>{tempi}</div><div>{indicatori}</div></div>",
                unsafe_allow_html=True)


def _ritaglio_html(percorso: str) -> str:
    try:
        dati = base64.b64encode(Path(percorso).read_bytes()).decode()
    except OSError:
        return "<div class='au-ritaglio-vuoto'></div>"
    return f"<img class='au-ritaglio' src='data:image/png;base64,{dati}'>"


def _usa_modello(path: str, k: str) -> None:
    """«Usa per questo file»: il modello sulla riga del file in Lavorazione,
    con la possibilita' di tornare indietro (`conf_usato`)."""
    modelli = state("modelli", {})
    scelte = state("scelte_modello", set())
    st.session_state["conf_usato"] = {"file": path, "modello": k,
                                      "prima": modelli.get(path),
                                      "era_scelta": path in scelte}
    modelli[path] = k
    scelte.add(path)
    st.session_state[f"m_{path}"] = k
    st.session_state.setdefault("da_confronto", set()).add(path)


def _annulla_usa() -> None:
    u = st.session_state.pop("conf_usato", None)
    if not u:
        return
    modelli = state("modelli", {})
    scelte = state("scelte_modello", set())
    if u["prima"]:
        modelli[u["file"]] = u["prima"]
        st.session_state[f"m_{u['file']}"] = u["prima"]
    else:
        modelli.pop(u["file"], None)
        st.session_state.pop(f"m_{u['file']}", None)
    if not u["era_scelta"]:
        scelte.discard(u["file"])
    st.session_state.get("da_confronto", set()).discard(u["file"])


@st.dialog(" ", width="medium")
def _dialogo_usa_tutti(k: str) -> None:
    """«Usa per tutti i file»: prima si dice cosa cambia, file per file, e si
    lasciano fuori i file per cui quel modello sarebbe una cattiva scelta."""
    modelli = state("modelli", {})
    cambiano, esclusi = [], []
    for f in load_library():
        if not f.get("height"):
            continue
        giudizio = (recommend(f["height"]).giudizi or {}).get(k)
        if giudizio == "no":
            esclusi.append(f["name"])
            continue
        attuale = modelli.get(f["path"]) or recommend(f["height"]).model
        if attuale != k:
            cambiano.append((f, attuale))
    nome = CATALOG[k].label
    st.markdown(f"<div class='au-dialogo-titolo'>{esc(t('conf.tutti_titolo', modello=nome))}</div>",
                unsafe_allow_html=True)
    if not cambiano:
        st.markdown(f"<p class='au-dialogo-testo'>{t('conf.tutti_nessuno')}</p>",
                    unsafe_allow_html=True)
    else:
        st.markdown(
            "<ul class='au-dialogo-elenco'>" + "".join(
                f"<li><span>{esc(f['name'])}</span><code>{esc(CATALOG[a].short if a in CATALOG else a)}"
                f" → {esc(CATALOG[k].short)}</code></li>" for f, a in cambiano) + "</ul>",
            unsafe_allow_html=True)
    if esclusi:
        st.markdown(f"<p class='au-dialogo-testo'>{esc(t('conf.tutti_esclusi', modello=nome, elenco=', '.join(esclusi)))}</p>",
                    unsafe_allow_html=True)
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(t("conf.tutti_annulla"), key="usaTuttiNo"):
            st.rerun()
        if cambiano and st.button(tn("conf.tutti_applica", len(cambiano)), key="usaTuttiSi",
                                  type="primary"):
            scelte = state("scelte_modello", set())
            for f, _a in cambiano:
                modelli[f["path"]] = k
                scelte.add(f["path"])
                st.session_state[f"m_{f['path']}"] = k
                st.session_state.setdefault("da_confronto", set()).add(f["path"])
            st.session_state.pop("conf_usato", None)
            st.rerun()


def _clip_risultato(res: dict, plan, path: Path) -> None:
    tipo = t(f"conf.tipo.{res['tipo']}").capitalize()
    prove = preview.Kind(res["tipo"]).tests if res.get("tipo") in (
        k.value for k in preview.Kind) else ""
    prova = t("conf.prova", prove=prove) if prove else ""
    titolo = f"**{tipo}** `{res['intervallo']}` · {prova[:1].lower() + prova[1:]}"
    cartella = res["cartella"]
    with st.expander(titolo, expanded=True):
        file_r = res.get("file") or {}
        # In movimento: video-compare, se c'e'. Se non c'e' niente pulsante e
        # niente ripiego su altri riproduttori, ma come installarlo
        # (facoltativo; deciso con l'utente).
        nomi = preview.ordine_lettura(file_r)
        coppie = [(a, b) for i, a in enumerate(nomi) for b in nomi[i + 1:]]
        if coppie and preview.comparison_tool():
            with st.container(key=f"coppie_{cartella}", horizontal=True,
                              vertical_alignment="center"):
                st.markdown(f"<div class='au-occhio'>{t('conf.guarda')}</div>",
                            unsafe_allow_html=True)
                for x, y in coppie:
                    lx = t("conf.originale") if x == "original" else CATALOG[x].short
                    ly = t("conf.originale") if y == "original" else CATALOG[y].short
                    if st.button(t("conf.apri_coppia", a=lx, b=ly),
                                 key=f"cmp_{cartella}_{x}_{y}"):
                        ok, msg = preview.open_comparison(Path(file_r[x]), Path(file_r[y]))
                        st.session_state[f"aperto_{cartella}"] = (ok, msg)
                aperto = st.session_state.get(f"aperto_{cartella}")
                if aperto:
                    st.markdown(f"<div class='au-aperto{'' if aperto[0] else ' au-aperto-no'}'>"
                                f"{esc(aperto[1])}</div>", unsafe_allow_html=True)
        elif coppie:
            comando = "brew install video-compare"
            st.markdown(
                f"<div class='au-vc-manca'><b>{t('conf.vc_titolo')}"
                f"<em> · {t('conf.vc_opz')}</em></b>"
                f"<span>{t('conf.vc_testo')}<br>{t('conf.vc_installa')} "
                f"<code>{comando}</code><a class='au-copia' data-copia='{comando}' role='button' "
                f"title='{t('conf.copia')}'>{_svg(_I_COPIA, 13, 1.6)}</a> · "
                f"<a href='https://github.com/pixop/video-compare' target='_blank' rel='noopener'>"
                f"{t('conf.vc_github')} ↗</a></span></div>", unsafe_allow_html=True)

        ritagli = res.get("ritagli") or {}
        if ritagli:
            ordine = preview.ordine_lettura(ritagli)
            destra_di_base = plan.model_key if plan.model_key in ritagli else (
                next((k for k in ordine if k != "original"), ordine[-1]))
            sinistra_di_base = "original" if "original" in ritagli else ordine[0]
            if sinistra_di_base == destra_di_base and len(ordine) > 1:
                destra_di_base = next(k for k in ordine if k != sinistra_di_base)
            cols = st.columns(2)
            for lato, col, di_base in (("s", cols[0], sinistra_di_base),
                                       ("d", cols[1], destra_di_base)):
                with col:
                    if len(ordine) > 2:
                        scelto = st.selectbox(
                            " ", ordine, index=ordine.index(di_base),
                            key=f"rit_{lato}_{cartella}", format_func=_nome_versione,
                            label_visibility="collapsed")
                    else:
                        scelto = di_base
                    st.markdown(f"<div class='au-ritaglio-box'>{_ritaglio_html(ritagli[scelto])}</div>",
                                unsafe_allow_html=True)
                    with st.container(key=f"piedeRit_{lato}_{cartella}", horizontal=True,
                                      vertical_alignment="center"):
                        st.markdown(f"<div class='au-ritaglio-nome'>{esc(_nome_versione(scelto))}</div>",
                                    unsafe_allow_html=True)
                        if scelto != "original" and scelto in CATALOG:
                            usato = st.session_state.get("conf_usato") or {}
                            if usato.get("file") == str(path) and usato.get("modello") == scelto:
                                st.markdown(
                                    f"<div class='au-usato'>{_svg(_I_SPUNTA, 11, 2.4)}"
                                    f"{t('conf.usato')}</div>", unsafe_allow_html=True)
                                st.button(t("conf.annulla"), key=f"annulla_{lato}_{cartella}",
                                          type="tertiary", on_click=_annulla_usa)
                            else:
                                st.button(t("conf.usa_file"), key=f"usa_{lato}_{cartella}",
                                          on_click=_usa_modello, args=(str(path), scelto))
                                if st.button(t("conf.usa_tutti"), key=f"usaTutti_{lato}_{cartella}"):
                                    _dialogo_usa_tutti(scelto)
        elif res.get("foglio"):
            # I confronti fatti prima dei ritagli separati: il foglio unico,
            # alla larghezza naturale, in una striscia che scorre di lato.
            try:
                dati = base64.b64encode(Path(res["foglio"]).read_bytes()).decode()
                st.markdown(f"<div class='au-foglio'><img src='data:image/png;base64,"
                            f"{dati}'></div>", unsafe_allow_html=True)
            except OSError:
                pass

        modelli = res.get("modelli") or []
        if modelli:
            _tabella_confronto(modelli, res.get("dedup"), riferimento="original" in file_r)
        with st.container(key=f"piedeClip_{cartella}", horizontal=True,
                          vertical_alignment="center"):
            with st.expander(t("conf.n_percorsi", n=len(file_r))):
                st.markdown("".join(
                    f"<div class='au-meta'><b class='au-file-eti'>"
                    f"{esc(t('conf.file_eti', nome=(t('conf.originale_ingrandito') if k_f == 'original' else CATALOG[k_f].label)))}"
                    f"</b> {esc(str(v_f))}</div>"
                    for k_f, v_f in file_r.items()), unsafe_allow_html=True)
            if st.button(t("conf.apri_cartella_clip"), key=f"finder_conf_{cartella}"):
                subprocess.run(["open", str(cartella)], check=False)


# ===========================================================================
#  3 · Lavorazione
# ===========================================================================

def page_lavorazione(cfg: dict) -> None:
    files = load_library()
    if not files:
        st.info(t("lav.vuoto"))
        return
    # «Mostra» nel resoconto di fine coda porta alla riga di quel file.
    if (nome := st.session_state.pop("scorri_riga", None)):
        st.iframe(
            "<script>setTimeout(()=>{const D=window.parent.document;"
            f"const n={json.dumps(nome)};"
            "for(const e of D.querySelectorAll('.au-name')){"
            "if(e.textContent.trim()===n){e.scrollIntoView({behavior:'smooth',"
            "block:'center'});break;}}},700);</script>", height=1)
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
    armato = (any(l.vivo for l in monitor.lavori(recente=1.0))
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
    """Quanto e' avanti il FILE intero, 0..1: la barra della riga e il suo
    numero.

    Prima la barra seguiva la fase in corso: piena al 90% a fine estrazione
    e di nuovo vuota all'inizio dell'upscale. Sembrava l'avanzamento del
    file e non lo era (segnalato dall'utente). Ora ogni fase ha una fetta
    proporzionata a quanto dura davvero su un episodio — misurato su un
    1080p da 30.210 fotogrammi: estrazione ~13 minuti, ricerca dei ripetuti
    ~6, upscale e codifica dei blocchi ore, montaggio finale pochi minuti —
    e la barra cresce una volta sola, senza mai tornare indietro. La fase
    in corso la dicono le tappe sotto, con le loro misure.

    In codifica finale i fotogrammi sono tutti fatti per definizione: li' la
    barra segue i pacchetti scritti, prima dell'ultimo blocco e poi del file
    finale, che il monitor gia' conta.
    """
    fette = {"estrazione": (0.0, 0.04), "deduplica": (0.04, 0.06),
             "elaborazione": (0.06, 0.96), "codifica blocco": (0.06, 0.96)}
    if lav.fase in fette:
        da, a = fette[lav.fase]
        return da + (a - da) * lav.frazione
    quota = max(0.0, min(1.0, lav.codifica_frazione))
    dentro = 0.5 + quota / 2 if lav.sottopasso == "montaggio" else quota / 2
    return 0.96 + dentro * 0.04


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
    numero = "1/3" if lav.fase in ("estrazione", "deduplica") else "2/3"
    nome_fase = lav.fase if lav.fase in ("estrazione", "deduplica") else "upscale"
    # `nome_fase` si confronta qui sotto: a schermo va la sua traduzione.
    scritta_fase = {"estrazione": t("lav.av_estrazione"),
                    "deduplica": t("lav.av_deduplica")}.get(nome_fase, t("lav.av_upscale"))
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
    # Il ritmo del confronto fra fotogrammi non dice niente di quello
    # dell'upscale che verra': niente fps ne' tempo che resta, qui.
    ritmo = (monitor.andatura(campioni.get(lav.cartella.name, []))
             if nome_fase != "deduplica" else None)
    resta = (_resto_misurato(lav, campioni, stati, turno_stimato, ritmo=ritmo)
             if ritmo else None)
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
        extra = f"<span class='au-meta'>{_pezzi(_avanzamento_testo(lav, campioni, stati))}</span>"
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
        f"{_riempimento(lav) * 100:.1f}%'></span></div>"
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
    lavori = monitor.lavori(recente=1.0)
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


# Le quattro tappe di un file e la fetta della barra di ciascuna, in
# proporzione a quanto durano davvero (vedi `_riempimento`).
_TAPPE_FILE = (("lav.passo1", 0.0, 0.04), ("lav.passo2", 0.04, 0.06),
               ("lav.passo3", 0.06, 0.96), ("lav.passo4", 0.96, 1.0))
_TAPPA_DI_FASE = {"estrazione": 0, "deduplica": 1, "elaborazione": 2,
                  "codifica blocco": 2, "codifica finale": 3}
_FRECCIA_TAPPA = ("<svg class='au-freccia-passo' aria-hidden='true' width='18' height='8' "
                  "viewBox='0 0 18 8' fill='none' stroke='currentColor' stroke-width='1' "
                  "stroke-linecap='round' stroke-linejoin='round'>"
                  "<path d='M1 4h15M13 1.5 16 4l-3 2.5'></path></svg>")


def _num(n: int) -> str:
    """Un conteggio coi separatori delle migliaia della lingua attiva:
    «30210» si leggeva come un numero solo accanto a «2392»."""
    testo = f"{int(n):,}"
    return testo.replace(",", ".") if lingua_attiva() == "it" else testo


def _grassetti(testo: str) -> str:
    """`**...**` del catalogo in grassetto: l'azione e i numeri in chiaro,
    le parole attorno in grigio (vedi `.au-riga-dett`)."""
    pezzi = esc(testo).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(pezzi))


def _barra_file(lav) -> str:
    """La barra del file intero divisa nelle quattro tappe, e la fetta
    dell'upscale segnata da una lineetta a ogni confine di blocco, in
    proporzione (l'ultimo blocco di solito e' piu' corto)."""
    quota = _riempimento(lav)
    pezzi = []
    for i, (_c, da, a) in enumerate(_TAPPE_FILE):
        pieno = max(0.0, min(1.0, (quota - da) / (a - da)))
        tacche = ""
        if i == 2 and lav.blocco_dim and lav.totale > lav.blocco_dim:
            tacche = "".join(f"<b data-x='{x / lav.totale:.5f}' "
                             f"style='left:{x / lav.totale * 100:.3f}%'></b>"
                             for x in range(lav.blocco_dim, lav.totale, lav.blocco_dim))
        pezzi.append(f"<span class='au-seg' data-peso='{(a - da) * 100:g}' "
                     f"style='flex:{(a - da) * 100:g} 0 0'>"
                     f"<i style='width:{pieno * 100:.1f}%'></i>{tacche}</span>")
    return f"<span class='au-barra-file' aria-hidden='true'>{''.join(pezzi)}</span>"


def _tappe_file(lav) -> str:
    """Le quattro tappe: fatte in verde con la spunta, quella in corso nel
    colore della barra col pallino che respira, le prossime in bianco. Dopo
    il nome la fetta del file, che la pagina toglie per prima se la riga non
    ci sta (vedi lo script `au-s1`/`au-s2`)."""
    ora = _TAPPA_DI_FASE.get(lav.fase, 2)
    tappe = []
    for i, (chiave, da, a) in enumerate(_TAPPE_FILE):
        stato = "fatta" if i < ora else "ora" if i == ora else "dopo"
        segno = (f"<span class='au-tp-segno'>{_svg(_I_SPUNTA, 12, 2.2)}</span>"
                 if stato == "fatta" else "<span class='au-punto-vivo'></span>"
                 if stato == "ora" else "")
        tappe.append(
            (_FRECCIA_TAPPA if i else "")
            + f"<span class='au-tp au-tp-{stato}'>{segno}"
            f"<span><span class='au-tp-n'>{i + 1} </span>{esc(t(chiave))}</span>"
            f"<span class='au-fetta'>{da * 100:.0f}–{a * 100:.0f}%</span></span>")
    return "".join(tappe)


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

    lav = next((l for l in monitor.lavori(recente=1.0)
                if l.cartella.name == cartella), None)
    if lav is None or not lav.vivo:
        return
    campioni = st.session_state.setdefault("mon_campioni", {})
    stati = st.session_state.setdefault("mon_stati", {})
    chiave_log = "log_" + hashlib.sha1(str(cartella).encode()).hexdigest()[:10]
    log = (f"<a class='au-log' data-preme='{chiave_log}' role='button'>"
           f"{t('lav.mostra_log')}</a>" if lav.registro is not None else "")
    in_pausa = monitor.sospeso(lav) is not None
    quota = _riempimento(lav)
    perc = f"{quota:.0%}"
    blocchi = dict(n=lav.blocco_n, blocchi=lav.blocchi_totali)
    misure: list[tuple[str, str]] = []
    if in_pausa:
        # In pausa NON si campiona. I fotogrammi non avanzano perche' nessuno
        # sta lavorando, e infilare quei punti nella finestra farebbe crollare
        # il ritmo verso lo zero e sparare il «restano» all'infinito — una
        # bugia costruita su misure vere. La finestra si azzera alla ripresa.
        if lav.fase in monitor.UNITA_UPSCALE and lav.blocchi_totali:
            dettaglio = t("lav.d_pausa_blocco", perc=perc, fatti=_num(lav.blocco_fatti),
                          totale=_num(lav.blocco_totale), **blocchi)
        else:
            dettaglio = t("lav.d_pausa", perc=perc)
    else:
        monitor.aggiorna_campioni(
            campioni, stati, [(lav.cartella.name, lav.fase, lav.fatti)],
            time.time())
        ritmo = monitor.andatura(campioni.get(lav.cartella.name, []))
        resta = None
        if lav.fase in ("estrazione", "deduplica"):
            if ritmo and lav.totale:
                resta = max(0, lav.totale - lav.fatti) / ritmo
            chiave = "lav.d_estrazione" if lav.fase == "estrazione" else "lav.d_deduplica"
            dettaglio = t(chiave, fatti=_num(lav.fatti), totale=_num(lav.totale))
        elif lav.fase == "elaborazione":
            resta = _resto_misurato(lav, campioni, stati, turno, ritmo=ritmo) if ritmo else None
            if not lav.fatti:
                # Fra la ricerca dei ripetuti e il primo fotogramma ingrandito
                # (il modello si carica, il blocco si prepara): «0 di 2.958»
                # sembrava un upscale fermo.
                dettaglio = t("lav.d_preparo")
            elif lav.blocchi_totali:
                dettaglio = (t("lav.d_upscale", fatti=_num(lav.blocco_fatti),
                               totale=_num(lav.blocco_totale), **blocchi)
                             + " · " + (t("lav.sicuro_niente") if not lav.blocco_fatti
                                        else t("lav.sicuro.uno") if lav.blocco_fatti == 1
                                        else t("lav.sicuro.altri",
                                               num=_num(lav.blocco_fatti))))
            else:
                dettaglio = t("lav.d_upscale_tutto", fatti=_num(lav.fatti),
                              totale=_num(lav.totale))
        else:
            # Codifica: niente fps (la GPU e' ferma) e il ritmo dei pacchetti
            # va a raffiche — il «restano» viene dalla durata del turno
            # (misurata, o dalla taratura), non dalle raffiche: scende liscio.
            ritmo = None
            frazione = max(0.0, min(1.0, lav.codifica_frazione))
            fatto = (" · " + t("lav.d_codificato", perc=f"{frazione:.0%}")) if frazione else ""
            durata = monitor.turno_misurato(stati, lav.cartella.name) or turno
            if lav.fase == "codifica blocco":
                dettaglio = t("lav.d_codifica_blocco", **blocchi) + fatto
                if durata:
                    resta = durata * (1 - frazione)
            elif lav.sottopasso == "montaggio":
                dettaglio = t("lav.d_montaggio") + (
                    (" · " + t("lav.d_scritto", perc=f"{frazione:.0%}")) if frazione else "")
            else:
                dettaglio = t("lav.d_ultimo_blocco") + fatto
                if durata and lav.blocco_dim and lav.totale:
                    ultimo = (lav.totale % lav.blocco_dim) or lav.blocco_dim
                    resta = durata * ultimo / lav.blocco_dim * (1 - frazione)
        if ritmo:
            misure.append(("au-m-fps", f"~{ritmo:.1f} fps"))
        if resta is not None:
            misure.append(("au-m-resta", t("lav.av_restano", resta=hms(resta))))
    if monitor.trascorso(lav):
        misure.append(("au-m-trascorso",
                       t("lav.av_trascorsi", trascorso=monitor.trascorso(lav))))
    misure_html = "".join(f"<span class='au-mis {c}'>{esc(v)}</span>" for c, v in misure)
    st.markdown(
        f"<div class='au-riga-avanz{' au-ferma' if in_pausa else ''}'>"
        f"<div class='au-riga-testa'>{_barra_file(lav)}<b>{perc}</b></div>"
        f"<div class='au-riga-tappe'>{_tappe_file(lav)}"
        f"<span class='au-riga-misure'>{misure_html}</span></div>"
        f"<div class='au-riga-dett'><span>{_grassetti(dettaglio)}</span>{log}</div></div>",
        unsafe_allow_html=True)
    if lav.registro is not None:
        # Il pulsante vero resta nascosto e lo preme il link dentro il
        # riquadro: posato sopra con margini negativi non era mai allineato
        # al testo accanto (visto dall'utente). La chiave e' un'impronta del
        # nome: quello vero ha spazi e parentesi che non stanno in una classe.
        if st.button(t("lav.mostra_log"), key=chiave_log, type="tertiary"):
            subprocess.run(["open", "-R", str(lav.registro)], check=False)


def _corpo_lavorazione(cfg: dict, files: list[dict], armato: bool) -> None:
    lavori_tutti = monitor.lavori(recente=1.0)
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
            f"<div class='au-titolo-pagina'>{t('lavb.titolo_in_corso')}</div>"
            f"<div class='au-sotto-pagina au-sotto-lav'>{t('lavb.hint_in_corso')}</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='au-titolo-pagina'>{t('lavb.titolo')}</div>"
            f"<div class='au-sotto-pagina au-sotto-lav'>{t('lavb.hint')}</div>",
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
        st.selectbox(
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
        # rinominata .DEFECTIVE, quindi qui non esiste e non inganna.
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
        # rinominato .DEFECTIVE apposta perche' il rilancio lo rifaccia.
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
        # parte come .DEFECTIVE). Non e' "fatto" e non e' "mai toccato": e' la
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
            # .DEFECTIVE, quindi qui non si arriva), percio' e' un residuo —
            # una versione vecchia che la teneva per gli avvisi, una pulizia
            # interrotta, `--keep-temp`. Si libera con lo stesso Scarta in
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
                    dett = t("lavb.fermo_al", quota=f"{_riempimento(lav):.0%}",
                             fatti=lav.fatti, totale=lav.totale)
                # Solo per le righe FERME: quella viva l'ha gia' disegnata il
                # suo riquadro qui sopra, e ridisegnarla qui la
                # raddoppierebbe.
                if dett is not None:
                    st.markdown(
                        f"<div class='au-riga-avanz'>"
                        f"<div class='au-riga-barra au-riga-ferma'>"
                        f"<span style='width:{_riempimento(lav) * 100:.1f}%'>"
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
        lavori_tutti = monitor.lavori(recente=1.0)
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
                a.markdown(f"<div class='au-avvio'><span class='au-rotella'></span>"
                           f"{t('lavb.avvio_in_corso')}</div>", unsafe_allow_html=True)
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
                # In un posto suo: al clic su Avvia si trasforma subito
                # nell'avviso d'avvio (vedi sotto), invece di restare li'
                # mentre la pagina sembra bloccata.
                nota_barra = a.empty()
                nota_barra.markdown(f"<div class='au-barra-nota'>{t('lavb.tempo_minimo')} "
                                    f"{_nota_taratura()}</div>",
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
                        # Subito, PRIMA del lavoro: `_avvia` prepara i file e
                        # puo' metterci parecchi secondi, e senza un segno la
                        # pagina sembrava bloccata (segnalato dall'utente).
                        nota_barra.markdown(
                            f"<div class='au-avvio'><span class='au-rotella'></span>"
                            f"{t('lavb.avvio_in_corso')}</div>", unsafe_allow_html=True)
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
            f"<span class='au-valore'>{_pezzi(str(v))}</span></div>" for k, v in voci)
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
        uscita_file = (Path(esito["output_path"]) if esito.get("output_path")
                       else PATHS.output / str(esito.get("output") or ""))
        try:
            peso = uscita_file.stat().st_size / 1048576
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
                                      cartella=uscita_file.parent.name),
                                    key=f"finder_{plan.output.name}"):
                        subprocess.run(["open", "-R", str(uscita_file)], check=False)
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

    La CLI accetta un solo `--model` per invocazione mentre qui la scelta è
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
    # Mai due code insieme: si scavalcavano, ognuna segnava «fallito» i file
    # che l'altra stava gia' lavorando, e si toglievano i marcatori a vicenda.
    if (monitor.lancio_vivo() or monitor.catena() is not None
            or monitor.pausa() is not None):
        st.error(t("lav.avvia_gia"), icon="⚠️")
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
        comando = [str(CODICE / "animeup"), "run", "--yes",
                   "--launch", etichetta_lancio,
                   "--height", str(cfg["altezza"]), "--crf", str(cfg["crf"]),
                   "--preset", cfg["preset"], "--model", modello,
                   "--disk", str(cfg["disco"])]
        if not cfg["dedup"]:
            comando.append("--no-dedup")
        if cfg.get("pausa"):
            comando += ["--pause", str(cfg["pausa"])]
            # I gruppi dopo il primo riposano anche PRIMA di partire: sono
            # la continuazione della stessa maratona, non un lancio nuovo.
            if comandi:
                comando.append("--pause-first")
        if len(per_modello) > 1:
            comando += ["--chain-total", str(totale_catena),
                        "--chain-start", str(precedenti)]
        precedenti += len(gruppo)
        if cfg["denoise"]:
            comando.append("--denoise")
        if cfg["forza"]:
            comando.append("--force")
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
    try:
        PATHS.work.mkdir(parents=True, exist_ok=True)
        (PATHS.work / ".launch").write_text(json.dumps(
            {"pid": proc.pid, "started": time.time(), "total": totale_catena,
             "label": etichetta_lancio,
             "files": [x.source.path.name for g in per_modello.values() for x in g]}))
    except OSError:
        pass
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
    from animeup.processi import di_animeup
    return pid != os.getpid() and di_animeup(pid)


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
    mancano = primo_avvio.da_scaricare()
    voci = []
    if mancano["ffmpeg"]:
        voci.append((t("pa.ffmpeg_titolo"), t("pa.ffmpeg_testo")))
    if mancano["ncnn"]:
        voci.append((t("pa.ncnn_titolo"), t("pa.ncnn_testo")))
    classe = " au-corso" if lavoro.in_corso else ""
    with st.container(key="benvenuto"):
        st.markdown(
            f"<div class='au-pa-occhio'>{t('pa.occhio')}</div>"
            f"<div class='au-pa-titolo'>{t('pa.titolo')}</div>"
            f"<p class='au-pa-testo'>{t('pa.intro')}</p>"
            + (f"<div class='au-pa-voci{classe}'>" + "".join(
                f"<div><i></i><span><b>{esc(n)}</b>{esc(d)}</span></div>" for n, d in voci)
               + "</div>" if voci else "")
            + f"<p class='au-pa-nota'>{t('pa.nota', mb=primo_avvio.peso_mb())}</p>",
            unsafe_allow_html=True)
        if lavoro.in_corso:
            righe = lavoro.righe.righe[-4:]
            st.markdown(
                f"<div class='au-pa-stato'><span class='au-rotella'></span>{t('pa.in_corso')}</div>"
                + (f"<pre class='au-pa-log'>{esc(chr(10).join(righe))}</pre>" if righe else ""),
                unsafe_allow_html=True)
            time.sleep(1.0)
            st.rerun()
        if lavoro.errore:
            st.markdown(f"<div class='au-box-rosso'>{t('pa.errore')}</div>"
                        f"<pre class='au-pa-log'>{esc(str(lavoro.errore))}</pre>",
                        unsafe_allow_html=True)
            if st.button(t("pa.riprova"), type="primary", key="paRiprova"):
                lavoro.avvia()
                st.rerun()
            return True
        if lavoro.finita and not primo_avvio.serve():
            return False
        if st.button(t("pa.scarica"), type="primary",
                     key="paScarica"):
            lavoro.avvia()
            st.rerun()
    return True


def _taratura_da_rifare() -> bool:
    """La taratura chiede attenzione: mai fatta su questo Mac, o fatta con
    una versione vecchia (senza la misura a 1080p)."""
    try:
        voce = taratura.carica()
    except (OSError, ValueError):
        return False
    return not voce or bool(voce.get("vecchia"))


def _sidebar_chiede_attenzione() -> bool:
    """Una condizione sola per il pallino del cassetto: c'e' un avviso giallo
    nella barra laterale. Ogni avviso nuovo di quel tipo va aggiunto QUI, e
    il pallino lo segue da solo (chiesto dall'utente: non solo per gli
    aggiornamenti)."""
    nuova = aggiornamenti.disponibile(
        attivo=_impostazioni_carica().get("aggiornamenti", True))
    return bool(nuova) or _taratura_da_rifare()


def _cassetto_sidebar() -> None:
    """Sotto i 1360px la barra laterale diventa un cassetto.

    Chiesto dall'utente: con la finestra stretta la parte che conta e' quella
    principale. La barra esce dal flusso e la pagina prende tutta la
    larghezza; un pulsante a sinistra della barra dei passi la fa scorrere
    sopra il contenuto, con un velo dietro; si chiude col velo, con Esc o
    con lo stesso pulsante. Pulsante e velo vivono nella pagina madre (li
    crea questo script una volta sola), lo stato e' una classe sul body.
    """
    # Una versione nuova: un pallino giallo sul pulsante, e la prima volta che
    # quella versione compare il cassetto si apre da solo sull'avviso. Con la
    # barra chiusa l'avviso, che sta in cima alla barra, non lo vedeva
    # nessuno (chiesto dall'utente). La versione gia' mostrata la ricorda il
    # browser: riaperto, il cassetto non si spalanca a ogni avvio.
    nuova = aggiornamenti.disponibile(
        attivo=_impostazioni_carica().get("aggiornamenti", True))
    versione_nuova = json.dumps(nuova["versione"] if nuova else "")
    etichetta = json.dumps(t("sb.cassetto_agg", versione=nuova["versione"]) if nuova
                           else t("sb.cassetto"))
    cartelle = {q: {"prompt": t(_CARTELLE[q][2] + "_prompt"), "start": str(_cartella_attuale(q))}
                for q in ("input", "output")}
    formati = {"cDisco": {"testo": "{} GB"},
               "cPausa": {"testo": "{} min", "zero": t("sb.pausa_nessuna")}}
    st.iframe(
        "<script>try{const D=window.parent.document;"
        "if(!D.getElementById('au-cassetto')){"
        "const b=D.createElement('button');b.id='au-cassetto';b.type='button';"
        "b.innerHTML='<svg width=\"18\" height=\"18\" viewBox=\"0 0 24 24\" fill=\"none\" "
        "stroke=\"currentColor\" stroke-width=\"1.9\" stroke-linecap=\"round\">"
        "<path d=\"M4 7h10M18 7h2M4 17h4M12 17h8\"/><circle cx=\"16\" cy=\"7\" r=\"2\"/>"
        "<circle cx=\"10\" cy=\"17\" r=\"2\"/></svg>';"
        "const v=D.createElement('div');v.id='au-velo';"
        "const chiudi=()=>D.body.classList.remove('au-sb-aperta');"
        "b.onclick=()=>D.body.classList.toggle('au-sb-aperta');v.onclick=chiudi;"
        "D.addEventListener('keydown',e=>{if(e.key==='Escape')chiudi();});"
        "D.body.appendChild(v);D.body.appendChild(b);}"
        f"const b=D.getElementById('au-cassetto');b.title={etichetta};"
        f"b.setAttribute('aria-label',{etichetta});"
        f"const V={versione_nuova};b.classList.toggle('au-agg',{json.dumps(_sidebar_chiede_attenzione())});"
        "if(V&&window.parent.matchMedia('(max-width: 1360px)').matches){try{const L=window.parent.localStorage;"
        "if(L.getItem('auCassettoAgg')!==V){L.setItem('auCassettoAgg',V);"
        "D.body.classList.add('au-sb-aperta');}}catch(e){}}"
        # Al centro verticale della barra dei passi, che con i sottotitoli su
        # due righe e' piu' alta: si rimisura a ogni giro e a ogni resize.
        "const W=window.parent;W.auPosCassetto=()=>{const p=D.querySelector('.st-key-passi');"
        "if(p){const r=p.getBoundingClientRect();"
        "D.getElementById('au-cassetto').style.top=Math.round(r.top+r.height/2-18)+'px';}};"
        "if(!W.auPosAscolto){W.auPosAscolto=1;W.addEventListener('resize',()=>W.auPosCassetto());}"
        "W.auPosCassetto();setTimeout(W.auPosCassetto,300);setTimeout(W.auPosCassetto,1200);"
        # Il «Predefinito» cliccabile dei fumetti: preme il pulsante nascosto
        # della stessa impostazione (vedi `_icona_aiuto`).
        "if(!W.auRipristino){W.auRipristino=1;D.addEventListener('click',e=>{"
        "const a=e.target.closest&&e.target.closest('[data-ripristina],[data-preme]');if(!a)return;"
        "e.preventDefault();e.stopPropagation();"
        "const k=a.dataset.ripristina?'ripr_'+a.dataset.ripristina:a.dataset.preme;"
        "const b=D.querySelector('.st-key-'+k+' button');"
        "if(b)b.click();},true);}"
        # Mentre si trascina un cursore della sidebar l'etichetta segue il
        # pomello (Streamlit manda il valore solo al rilascio): si legge il
        # numero sotto il pomello e lo si scrive nell'etichetta, a ogni frame.
        f"W.auScatti={json.dumps(_ETICHETTE_SCATTI)};W.auFormati={json.dumps(formati)};"
        "if(!W.auTrascina){W.auTrascina=1;D.addEventListener('pointerdown',e=>{"
        "const c=e.target.closest&&e.target.closest('[data-testid=\"stSidebar\"] [class*=\"st-key-c\"]');"
        "if(!c||!c.querySelector('[data-testid=\"stSlider\"]'))return;"
        "const k=[...c.classList].find(x=>x.startsWith('st-key-c'));if(!k)return;const n=k.slice(7);"
        "const w=c.closest('[data-testid=\"stLayoutWrapper\"]')||c;"
        "let p=w.previousElementSibling;while(p&&!p.querySelector('.au-sb-val'))p=p.previousElementSibling;"
        "const eti=p&&p.querySelector('.au-sb-val');if(!eti)return;let su=false;"
        "const fine=()=>{su=true;setTimeout(()=>c.style.removeProperty('--au-p'),1500);};W.addEventListener('pointerup',fine,{once:true});"
        "const giro=()=>{if(su)return;const v=c.querySelector('[data-testid=\"stSliderThumbValue\"]');"
        "if(v){const x=parseFloat(v.textContent);if(!isNaN(x)){"
        "if(W.auScatti[n]){const l=W.auScatti[n];eti.textContent=l[Math.min(l.length-1,Math.max(0,Math.round(x)))];"
        "c.style.setProperty('--au-p',Math.min(1,Math.max(0,x/(l.length-1))));}"
        "else if(W.auFormati[n]){const f=W.auFormati[n];eti.textContent=(x===0&&f.zero)?f.zero:f.testo.replace('{}',Math.round(x));}}}"
        "requestAnimationFrame(giro);};requestAnimationFrame(giro);},true);}"
        # Nell'app «Cambia…» apre il pannello nativo (vedi `_cartella_dal_mac`):
        # il clic va all'app e non al server. Nel browser non c'e' il ponte, e
        # il pulsante fa quello di sempre.
        f"W.auCartelle={json.dumps(cartelle)};"
        "W.auCartellaScelta=()=>{const x=D.querySelector('.st-key-applicaCartella button');if(x)x.click();};"
        # Il fumetto del percorso intero si accende solo se il percorso e'
        # davvero tagliato dai puntini (vedi `_percorso`).
        # Un fumetto che uscirebbe dalla finestra si apre verso l'interno:
        # centrato sull'icona, quelli delle stime in fondo alle righe della
        # Lavorazione finivano tagliati a destra (segnalato dall'utente).
        "if(!W.auBordo){W.auBordo=1;D.addEventListener('pointerover',e=>{"
        "const i=e.target.closest&&e.target.closest('.au-info,.au-perche');if(!i)return;"
        "const b=i.querySelector('.au-bolla');if(!b)return;"
        "i.classList.remove('au-a-destra','au-a-sinistra');"
        "const r=i.getBoundingClientRect(),m=r.left+r.width/2,w=b.offsetWidth;"
        "if(m+w/2>W.innerWidth-12)i.classList.add('au-a-destra');"
        "else if(m-w/2<12)i.classList.add('au-a-sinistra');},true);}"
        # Le tappe della riga in lavorazione: se non ci stanno, via prima i
        # numeri e le fette, poi il tempo trascorso. Si ricontrolla a ogni
        # ridisegno della riga (ogni due secondi) e a ogni ridimensionamento.
        # E la barra del file a larghezze INTERE: con le fette frazionarie lo
        # stacco fra una tappa e l'altra veniva disegnato ora pieno ora quasi
        # chiuso (visto dall'utente). L'ultima fetta prende il resto.
        "if(!W.auTappe){W.auTappe=1;let att=0;const adatta=()=>{att=0;"
        "D.querySelectorAll('.au-barra-file').forEach(f=>{const s=[...f.children];if(!s.length)return;"
        "const g=parseFloat(getComputedStyle(f).columnGap)||0;const tot=Math.floor(f.getBoundingClientRect().width)-g*(s.length-1);"
        "const pesi=s.map(x=>parseFloat(x.dataset.peso)||1),somma=pesi.reduce((a,b)=>a+b,0);let usato=0;"
        "s.forEach((x,i)=>{const w=i===s.length-1?tot-usato:Math.max(14,Math.round(tot*pesi[i]/somma));usato+=w;"
        "x.style.flex='0 0 '+w+'px';x.querySelectorAll('b[data-x]').forEach(k=>{k.style.left=Math.round(w*parseFloat(k.dataset.x))+'px';});});});"
        "D.querySelectorAll('.au-riga-tappe').forEach(r=>{r.classList.remove('au-s1','au-s2');"
        "if(r.scrollWidth>r.clientWidth+1){r.classList.add('au-s1');"
        "if(r.scrollWidth>r.clientWidth+1)r.classList.add('au-s2');}});};"
        "const presto=()=>{if(!att){att=1;W.requestAnimationFrame(adatta);}};"
        "new W.MutationObserver(presto).observe(D.body,{childList:true,subtree:true});"
        "W.addEventListener('resize',presto);}"
        "if(!W.auTronco){W.auTronco=1;D.addEventListener('pointerover',e=>{"
        "const w=e.target.closest&&e.target.closest('.au-perc');if(!w)return;"
        "const c=w.querySelector('code');w.classList.toggle('au-tronco',!!c&&c.scrollWidth>c.clientWidth+1);},true);}"
        # Le tendine si allargano quanto il nome piu' lungo fra quelli in
        # vista: la lista e' a righe fisse (virtualizzata), quindi andare a
        # capo non si puo', e tagliare i nomi dei file a meta' rendeva
        # indistinguibili gli episodi di una serie (segnalato dall'utente).
        # Dal CSS non si puo': le righe sono posizionate in assoluto e non
        # danno larghezza al contenitore. Mai oltre il bordo della finestra.
        "if(!W.auTendine){W.auTendine=1;const larga=d=>{"
        "const testi=[...d.querySelectorAll('[role=\"option\"] div')];if(!testi.length)return;"
        # La larghezza del TESTO, non del suo riquadro: il riquadro segue la
        # tendina, e misurandolo ogni allargamento ne chiedeva un altro fino
        # al bordo della finestra.
        "const misura=x=>{const g=D.createRange();g.selectNodeContents(x);return g.getBoundingClientRect().width;};"
        "const serve=Math.ceil(Math.max(...testi.map(misura)))+40;const r=d.getBoundingClientRect();"
        "const w=Math.min(Math.max(serve,r.width),W.innerWidth-r.left-16);"
        "if(w>r.width+1){const su=[];for(let x=d.parentElement;x&&x!==D.body;x=x.parentElement){su.push(x);"
        "if(x.getAttribute('data-baseweb')==='popover')break;}"
        "[...su,d,...d.querySelectorAll('[role=\"listbox\"],[role=\"listbox\"] > div')]"
        ".forEach(x=>{x.style.setProperty('width',w+'px','important');"
        "x.style.setProperty('max-width','none','important');});}};"
        "new W.MutationObserver(()=>D.querySelectorAll('[data-testid=\"stSelectboxVirtualDropdown\"]')"
        # Anche sugli attributi `style`: la lista virtuale riscrive la sua
        # larghezza a ogni disegno (passaggio del mouse compreso).
        ".forEach(larga)).observe(D.body,{childList:true,subtree:true,"
        "attributes:true,attributeFilter:['style']});}"
        "if(!W.auPannello){W.auPannello=1;D.addEventListener('click',e=>{"
        "const h=W.webkit&&W.webkit.messageHandlers&&W.webkit.messageHandlers.animeup;if(!h)return;"
        "const b=e.target.closest&&e.target.closest('[class*=\"st-key-apriCartella_\"] button,"
        ".st-key-cambiaInput button,.st-key-cambiaOutput button');if(!b||b.disabled)return;"
        "e.preventDefault();e.stopPropagation();"
        "const q=/_input|Input/.test(b.closest('[class*=\"st-key-\"]').className)?'input':'output';"
        "h.postMessage(Object.assign({pick:q},W.auCartelle[q]));},true);}"
        "}catch(e){}</script>", height=1)


def _applica_tema(scelta: str) -> None:
    """I colori del tema scelto, e lo stesso tema per i widget di Streamlit.

    Le variabili si riscrivono a ogni giro (costano un `<style>` di poche
    righe). I widget nativi invece prendono il tema che Streamlit legge dal
    browser all'avvio della pagina: se non e' quello scelto lo si scrive li'
    e si ricarica, una volta sola — al giro dopo coincidono. La scelta e'
    gia' salvata su disco quando si arriva qui, quindi un ricaricamento non
    perde niente, e le lavorazioni, che sono processi a parte, non se ne
    accorgono.
    """
    if scelta not in tema.SCELTE:
        scelta = tema.SISTEMA
    # Cambiato il tema a sessione aperta, il ricaricamento che segue apre una
    # sessione nuova: selezione e modelli scelti file per file sparivano.
    # Si mettono da parte qui e la sessione nuova li riprende.
    prima = st.session_state.get("tema_applicato")
    st.session_state["tema_applicato"] = scelta
    if prima is not None and prima != scelta:
        _metti_da_parte_sessione()
    st.markdown(f"<style>{tema.css(scelta)}</style>", unsafe_allow_html=True)
    voluto = json.dumps(tema.streamlit(scelta))
    st.iframe(
        "<script>try{const W=window.parent;"
        "const K='stActiveTheme-'+W.location.pathname+'-v2';"
        f"const V={json.dumps(voluto)};"
        "if(W.localStorage.getItem(K)!==V){W.localStorage.setItem(K,V);"
        "W.location.reload();}}catch(e){}</script>", height=1)


# Le scelte della pagina che un ricaricamento non deve perdere.
_DA_TENERE = ("coda", "modelli", "scelte_modello", "rifai_comunque", "conf_file",
              "sezione")


def _file_sessione() -> Path:
    return PATHS.cache / "ui-session.json"


def _metti_da_parte_sessione() -> None:
    dati = {}
    for chiave in _DA_TENERE:
        if chiave in st.session_state:
            v = st.session_state[chiave]
            dati[chiave] = {"set": sorted(v)} if isinstance(v, set) else v
    try:
        _file_sessione().parent.mkdir(parents=True, exist_ok=True)
        _file_sessione().write_text(json.dumps({"quando": time.time(), "dati": dati}))
    except (OSError, TypeError, ValueError):
        pass


def _riprendi_sessione() -> None:
    """Una sessione nuova, nata da un cambio di tema: riprende le scelte."""
    if st.session_state.get("_sessione_ripresa"):
        return
    st.session_state["_sessione_ripresa"] = True
    try:
        salvata = json.loads(_file_sessione().read_text())
        _file_sessione().unlink(missing_ok=True)
    except (OSError, ValueError):
        return
    if not isinstance(salvata, dict) or time.time() - float(salvata.get("quando") or 0) > 60:
        return
    for chiave, v in (salvata.get("dati") or {}).items():
        if chiave in _DA_TENERE and chiave not in st.session_state:
            st.session_state[chiave] = set(v["set"]) if isinstance(v, dict) and "set" in v else v


@st.fragment(run_every=4)
def _sentinella() -> None:
    """Ridisegna la pagina quando cambia qualcosa che nessuno sta guardando.

    La pagina vuota promette che i video copiati nella cartella «compaiono
    qui in pochi secondi», ma a pagina ferma niente la rieseguiva: i file
    nuovi restavano invisibili e la barra dei passi bloccata. Lo stesso per
    un confronto o una taratura finiti mentre si guardava un'altra scheda: la
    sidebar restava bloccata finche' non si cliccava qualcosa. Qui si guarda
    poco e spesso (un elenco della cartella, due file di stato); il giro
    completo parte solo quando qualcosa cambia davvero.
    """
    from animeup.library import VIDEO_EXTENSIONS
    try:
        cartella = tuple(sorted(
            (e.name, e.stat().st_size, e.stat().st_mtime_ns)
            for e in os.scandir(PATHS.input)
            if e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTENSIONS))
    except OSError:
        cartella = ()
    # Anche il controllo degli aggiornamenti: gira in sottofondo e prima la
    # nota compariva solo al clic successivo (all'avvio, a pagina ferma, mai).
    try:
        verifica = aggiornamenti._file().stat().st_mtime
    except OSError:
        verifica = 0.0
    firma = (cartella, confronto.in_corso(), taratura.in_corso(),
             monitor.lancio_vivo(), verifica)
    prima = st.session_state.get("firma_sentinella")
    st.session_state["firma_sentinella"] = firma
    if prima is not None and firma != prima:
        if prima[0] != cartella:
            load_library.clear()
        st.rerun(scope="app")


def main() -> None:
    st.session_state["_giro"] = st.session_state.get("_giro", 0) + 1
    _riprendi_sessione()
    try:
        PATHS.ensure_dirs()
    except OSError:
        pass
    # La lingua si decide PRIMA di disegnare: l'intestazione viene prima
    # della sidebar, che e' dove la lingua si sceglie. Cambiandola, il
    # widget scrive la sessione e Streamlit rifa' il giro: qui la si trova.
    i18n.imposta(st.session_state.get("w_lingua")
                 or _impostazioni_carica()["lingua"])
    _applica_tema(st.session_state.get("w_tema")
                  or _impostazioni_carica()["tema"])
    # Il primo avvio non ha sidebar: niente cassetto (il suo pulsante restava
    # li' senza fare niente, visto dall'utente).
    if _pagina_primo_avvio():
        return
    _cassetto_sidebar()
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
    # Una cartella scelta su un disco non collegato all'avvio: si lavora sul
    # ripiego, e va detto su ogni scheda, non solo in un angolo della sidebar
    # (la pagina vuota dei Sorgenti lo dice gia' da se').
    if sezione != INIZIO:
        for nota in _note_cartelle_assenti():
            st.warning(nota)
    # Cosa la migrazione alla 1.6 non ha potuto fare (una volta per codice).
    from animeup import migrazione as _migrazione
    for codice, dati in dict(_migrazione.avvisi).items():
        st.warning(t(codice, **{k: _breve(v) for k, v in dati.items()}))
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
    if sezione == INIZIO:
        _pagina_inizio()
    elif sezione == SEZIONI[0]:
        page_sorgenti(cfg)
    elif sezione == SEZIONI[1]:
        page_confronto(cfg)
    else:
        page_lavorazione(cfg)
    # Finita (o fallita) a finestra chiusa: si riapre da sola sui risultati,
    # o non lo si saprebbe mai (segnalato dall'utente). Chiuderla la segna
    # come vista (vedi `_chiudi_taratura`).
    _s_tar = taratura.stato_fondo()
    if (_s_tar and _s_tar.get("state") in (taratura.FINITA, taratura.FALLITA)
            and not _s_tar.get("seen")):
        st.session_state["tar_aperta"] = True
    # La taratura riaperta a ogni giro finche' non la si chiude (vedi
    # `_modale_taratura`); mai insieme al resoconto: una modale alla volta.
    if st.session_state.get("tar_aperta") and not st.session_state.get("fine_da_mostrare"):
        _modale_taratura()
    elif st.session_state.get("esito_agg") and not st.session_state.get("fine_da_mostrare"):
        _modale_esito_agg()
    _sentinella()


main()
