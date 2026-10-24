"""Stato dei lavori in corso, letto da disco e basta.

Il pannello di monitoraggio NON parla con i processi: legge quello che la
pipeline lascia già per la ripresa — il lucchetto col PID, `state.json`, i
PNG dei blocchi — e lo traduce in avanzamento. Sola lettura per costruzione:
un monitor che può scrivere è un monitor che un giorno interrompe una
lavorazione da otto ore per un bug suo.

L'avanzamento è esatto senza chiedere niente alla pipeline: i PNG dei
blocchi portano nel nome l'indice del fotogramma SORGENTE (00000392.png = il
fotogramma 392 dell'episodio), quindi il massimo indice elaborato diviso il
totale dichiarato in `state.json` è la percentuale vera, buchi della
deduplica inclusi.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import su_disco
from .models import CATALOG
from .paths import PATHS, Paths
from .pipeline import _processo_vivo

_SEGMENTO = re.compile(r"seg(\d{8})-(\d{8})\.mkv")
_CODA_DIR = re.compile(r" \d{4}-\d{2}-\d{2} [0-9a-f]{8}$")
# La firma in state.json è una catena di campi separati da `|`; qui servono
# solo posizioni fisse: [4] fotogrammi totali, [5] modello del binario.
# Il nome mostrato è il `short` del catalogo, letto al momento: tradotto
# nella lingua attiva, e non una copia che può restare indietro.
_MODELLI_LEGGIBILI = (
    ("animevideov3", "animevideov3"),
    ("denoise1x", "cugan-denoise"),
    ("no-denoise", "cugan"),
)


def _frazione_pacchetti(file: Path, su_totale: int) -> float | None:
    """Pacchetti video già scritti in `file`, in rapporto a `su_totale`.

    È la percentuale MISURATA di una codifica in corso: matroska cresce a
    cluster leggibili, quindi si può contare senza disturbare chi scrive.
    None se il file non c'è ancora o non è leggibile."""
    if not su_totale or not file.is_file():
        return None
    import subprocess
    try:
        esito = subprocess.run(
            [str(PATHS.ffprobe.path), "-v", "error",
             "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets",
             "-of", "csv=p=0", str(file)],
            capture_output=True, text=True, check=False, timeout=10)
        pacchetti = int(esito.stdout.strip().splitlines()[0])
        return min(pacchetti / su_totale, 1.0)
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


@dataclass
class StatoLavoro:
    cartella: Path
    nome: str               # lo stem del sorgente, senza data e impronta
    sorgente: str           # il NOME FILE del sorgente, dalla firma: è la
                            # chiave con cui la riga dell'elenco si riconosce
    vivo: bool              # il PID nel lucchetto è un processo attivo
    fase: str               # "estrazione" | "elaborazione"
    fatti: int              # fotogrammi sorgente già superati
    totale: int
    modello: str
    avviato: float | None   # quando è partito (mtime del lucchetto)
    registro: Path | None   # il log di questo lavoro, se esiste
    # Il punto DENTRO il blocco corrente, in fotogrammi SORGENTE (la stessa
    # metrica del contatore globale): serve alla riga per dire "742/1778 del
    # blocco 3 di 10" — cioè quanto manca al prossimo punto di salvataggio,
    # che è il momento giusto per un Ferma indolore. Zero = non noto.
    blocco_fatti: int = 0
    blocco_totale: int = 0
    blocco_n: int = 0
    blocchi_totali: int = 0
    # Quanto è avanti la CODIFICA del blocco corrente (0..1): misurata
    # contando i pacchetti del segmento in scrittura, non stimata dal tempo.
    codifica_frazione: float = 0.0
    # In "codifica finale", quale dei due sottopassi è in corso:
    # "codifica" (l'ultimo blocco sta passando in x265) oppure "montaggio"
    # (il file finale .inlavorazione sta crescendo in OUTPUT). Vuoto altrove.
    sottopasso: str = ""

    @property
    def frazione(self) -> float:
        return min(self.fatti / self.totale, 1.0) if self.totale else 0.0

    def ultima_riga(self) -> str:
        if not self.registro:
            return ""
        try:
            code = self.registro.read_bytes()[-4096:].decode("utf-8", "replace")
        except OSError:
            return ""
        righe = [r.strip() for r in code.splitlines() if r.strip()]
        return righe[-1] if righe else ""


def _leggi(cartella: Path, logs: Path) -> StatoLavoro | None:
    stato_path = cartella / "state.json"
    if not stato_path.is_file():
        # `state.json` nasce solo A FINE estrazione: per i primi ~10 minuti
        # di ogni episodio nuovo esiste solo il lucchetto (e frames/ che si
        # riempie). Ignorare la cartella qui rendeva la pagina cieca proprio
        # in quella finestra — "sembra tutto fermo e non posso nemmeno
        # fermarlo" (successo). Un lucchetto vivo È una lavorazione.
        lock = cartella / "running.lock"
        if not lock.is_file() or not _processo_vivo(lock):
            return None
        frames_dir = cartella / "frames"
        estratti = (sum(1 for f in frames_dir.glob("*.png"))
                    if frames_dir.is_dir() else 0)
        nome = _CODA_DIR.sub("", cartella.name)
        # Il totale sta nella ricetta (parametri.json), scritta PRIMA che
        # l'estrazione parta: senza, "5632 fotogrammi estratti" non dice
        # quanto manca. Le lavorazioni di CLI vecchie non ce l'hanno: 0.
        try:
            totale = int(su_disco.loads(
                (cartella / "parameters.json").read_text()
            ).get("fotogrammi") or 0)
        except (OSError, ValueError):
            totale = 0
        try:
            avviato = lock.stat().st_mtime
        except OSError:
            avviato = None
        return StatoLavoro(cartella=cartella, nome=nome, sorgente="",
                           vivo=True, fase="estrazione", fatti=estratti,
                           totale=totale, modello="?", avviato=avviato,
                           registro=_registro_di(nome, logs))
    try:
        stato = su_disco.loads(stato_path.read_text())
    except (OSError, ValueError):
        return None

    parti = str(stato.get("signature", "")).split("|")
    sorgente = parti[0] if parti else ""
    totale = int(parti[4]) if len(parti) > 5 and parti[4].isdigit() else 0
    modello = parti[5] if len(parti) > 5 else "?"
    for pezzo, chiave in _MODELLI_LEGGIBILI:
        if pezzo in modello:
            modello = CATALOG[chiave].short
            break

    # Il fotogramma più avanzato: fine dell'ultimo segmento codificato, o il
    # PNG più alto fra i blocchi in corso di upscale.
    # I segmenti in state.json sono triple [inizio, fine, nome] — scoperto sul
    # campo: il primo monitor assumeva stringhe e la pagina cadeva con un
    # TypeError, ma solo quando un segmento era GIA' codificato, cioè quasi
    # mai durante l'upscale. Si accettano entrambe le forme e si ignora il
    # resto: uno state.json strano deve dare un avanzamento monco, non una
    # pagina rossa.
    fatti = 0
    fine_segmenti = 0        # dove finisce l'ultimo blocco già impacchettato
    n_segmenti = 0
    for voce in stato.get("segments", []):
        if isinstance(voce, (list, tuple)) and len(voce) >= 3:
            try:
                fine_segmenti = max(fine_segmenti, int(voce[1]))
                n_segmenti += 1
            except (TypeError, ValueError):
                pass
            continue
        if isinstance(voce, str):
            m = _SEGMENTO.fullmatch(voce)
            if m:
                fine_segmenti = max(fine_segmenti, int(m.group(2)))
                n_segmenti += 1
    fatti = fine_segmenti
    for chunk in cartella.glob("chunk*-up"):
        for png in chunk.glob("*.png"):
            if png.stem.isdigit():
                fatti = max(fatti, int(png.stem))

    # Il punto dentro il blocco corrente. La dimensione del blocco viene da
    # `chunk` nello stato (lo scrive la pipeline nuova) o, in mancanza, dal
    # primo segmento già fatto: da un episodio al primo blocco con la
    # pipeline vecchia non è deducibile, e la riga tacerà — meglio di un
    # numero inventato.
    blocco = int(stato.get("chunk") or 0)
    if not blocco and n_segmenti:
        primo = stato.get("segments", [None])[0]
        if isinstance(primo, (list, tuple)) and len(primo) >= 2:
            try:
                blocco = int(primo[1]) - int(primo[0])
            except (TypeError, ValueError):
                pass

    estratti = int(stato.get("extracted") or 0)
    if fatti >= totale > 0:
        # Tutti i fotogrammi sono passati per la GPU: resta la codifica del
        # segmento e il montaggio finale. Dirlo evita il "perché è fermo al
        # 100%?" — non è fermo, sta codificando.
        fase = "codifica finale"
    elif fatti:
        fase = "elaborazione"
    elif estratti and totale and estratti < totale:
        fase, fatti = "estrazione", estratti
    else:
        fase = "elaborazione"

    # Il "cambio turno" GPU→CPU: a blocco upscalato per intero (chunk-up
    # pieno quanto chunk-in) la pipeline sta codificando in x265 — 3-4 minuti
    # a GPU ferma in cui il conteggio non avanza, il ritmo mobile crollava e
    # la ETA esplodeva ("che succede?", successo). Riconoscerlo dal
    # filesystem permette di DIRLO invece di sembrare rotti.
    if fase == "elaborazione":
        for dentro in cartella.glob("chunk*-in"):
            n_in = sum(1 for _ in dentro.glob("*.png"))
            su = cartella / (dentro.name[:-3] + "-up")
            if n_in and sum(1 for _ in su.glob("*.png")) >= n_in:
                fase = "codifica blocco"
                break

    lock = cartella / "running.lock"
    vivo = lock.is_file() and _processo_vivo(lock)
    avviato = None
    if lock.is_file():
        try:
            avviato = lock.stat().st_mtime
        except OSError:
            pass

    nome = _CODA_DIR.sub("", cartella.name)
    registro = _registro_di(nome, logs)

    b_fatti = b_tot = b_n = b_tutti = 0
    if blocco and totale and fatti < totale:
        b_n = n_segmenti + 1
        b_tutti = -(-totale // blocco)          # arrotonda in su
        b_tot = min(blocco, totale - fine_segmenti)
        b_fatti = max(0, min(fatti - fine_segmenti, b_tot))

    # Durante la codifica del blocco il segmento in scrittura è leggibile
    # (matroska cresce a cluster): contarne i pacchetti contro i fotogrammi
    # del blocco dà la percentuale VERA della codifica — chiesta
    # dall'utente, e coerente col principio "nessun numero inventato".
    codifica = 0.0
    sottopasso = ""
    if fase == "codifica blocco" and b_tot:
        in_scrittura = (cartella / "segments" /
                        f"seg{fine_segmenti:08d}-{fine_segmenti + b_tot:08d}.mkv")
        frazione = _frazione_pacchetti(in_scrittura, b_tot)
        if frazione is not None:
            codifica = frazione

    # La fase finale ha due sottopassi, entrambi misurabili con la stessa
    # tecnica dei pacchetti contati (chiesta dall'utente: "anche in codifica
    # e montaggio la %"): prima l'ULTIMO blocco passa in x265 (il segmento
    # cresce in segments/), poi il montaggio scrive il file .inlavorazione
    # in OUTPUT. Il nome del file finale non è ricostruibile dal nome della
    # cartella (che è sanificato): si riconosce per prefisso dal nome VERO
    # del sorgente, che sta nella firma.
    if fase == "codifica finale":
        finale = None
        stem = Path(sorgente).stem if sorgente else ""
        if stem:
            try:
                for cand in PATHS.output.iterdir():
                    if (cand.name.endswith(".incomplete")
                            and cand.name.startswith(stem)):
                        finale = cand
                        break
            except OSError:
                pass
        resto = max(0, totale - fine_segmenti)
        if finale is not None:
            sottopasso = "montaggio"
            frazione = _frazione_pacchetti(finale, totale)
            if frazione is not None:
                codifica = frazione
        elif resto:
            sottopasso = "codifica"
            in_scrittura = (cartella / "segments" /
                            f"seg{fine_segmenti:08d}-{totale:08d}.mkv")
            frazione = _frazione_pacchetti(in_scrittura, resto)
            if frazione is not None:
                codifica = frazione
        else:
            sottopasso = "montaggio"
    return StatoLavoro(cartella=cartella, nome=nome, sorgente=sorgente,
                       vivo=vivo, fase=fase,
                       fatti=min(fatti, totale) if totale else fatti,
                       totale=totale, modello=modello, avviato=avviato,
                       registro=registro,
                       blocco_fatti=b_fatti, blocco_totale=b_tot,
                       blocco_n=b_n, blocchi_totali=b_tutti,
                       codifica_frazione=codifica,
                       sottopasso=sottopasso)


def _registro_di(nome: str, logs: Path) -> Path | None:
    """Il log di questo lavoro, se esiste.

    Il registro porta il nome del file d'uscita, che inizia con lo stem del
    SORGENTE — ma la cartella usa `safe_name`, che sostituisce le parentesi:
    "[Omnivium] Koyo..." diventa "Omnivium_ Koyo...". Si confronta quindi la
    forma normalizzata (solo lettere e cifre), che sopravvive a entrambe.
    """
    chiave = _normalizza(nome)
    if not chiave:
        return None
    try:
        candidati = [f for f in logs.glob("*.log")
                     if _normalizza(f.name).startswith(chiave)]
    except OSError:
        return None
    candidati.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return candidati[0] if candidati else None


def _normalizza(testo: str) -> str:
    return re.sub(r"[^a-z0-9]", "", testo.lower())


# La usa anche l'interfaccia, per riconoscere quale riga dell'elenco
# corrisponde a un lavoro: stessa normalizzazione, stessa chiave.
chiave_nome = _normalizza


def lavori(paths: Paths | None = None) -> list[StatoLavoro]:
    """Tutti i lavori presenti in WORK, vivi per primi, più recenti prima."""
    p = paths or PATHS
    if not p.work.is_dir():
        return []
    trovati = []
    for cartella in p.work.iterdir():
        if not cartella.is_dir():
            continue
        lavoro = _leggi(cartella, p.job_logs)
        if lavoro is not None:
            trovati.append(lavoro)
    trovati.sort(key=lambda l: (not l.vivo, -(l.avviato or 0)))
    return trovati


def esiti(paths: Paths | None = None) -> dict[str, dict]:
    """Gli esiti delle lavorazioni concluse, per chiave normalizzata.

    Li scrive la CLI a fine file (records/history.jsonl): durata reale,
    avvisi, esito. Servono alla riga dell'elenco DOPO che la cartella di
    lavoro si è autopulita — senza, un episodio finito non lasciava niente
    di leggibile e la riga tornava muta. L'ultima voce per file vince: un
    rilancio sovrascrive la pagella vecchia.
    """
    p = paths or PATHS
    fuori: dict[str, dict] = {}
    try:
        righe = p.storico.read_text().splitlines()
    except OSError:
        return fuori
    for riga in righe:
        try:
            d = su_disco.loads(riga)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("file"):
            fuori[_normalizza(str(d["file"]))] = d
    return fuori


def pausa(paths: Paths | None = None) -> tuple[float, int] | None:
    """(scadenza, pid) se una catena di lavorazioni sta riposando fra due file.

    Il marcatore lo scrive la CLI (`--pausa`); qui si legge e basta, come
    tutto il resto. Un marcatore scaduto o di un processo morto vale come
    assente: non si cancella (sola lettura), lo toglierà la CLI o il
    prossimo giro di pausa lo sovrascrivera'.
    """
    import os

    p = paths or PATHS
    try:
        dati = su_disco.loads((p.work / ".pause").read_text())
        fino, pid = float(dati["fino"]), int(dati["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if fino < time.time():
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass                    # esiste, di un altro utente: vale come vivo
    return (fino, pid)


def catena(paths: Paths | None = None) -> dict | None:
    """A che punto è la catena di lavorazioni, se una è in corso.

    Dizionario con numero, totale, file, resta_min, resta_max, in_coda,
    programma — scritto dalla CLI all'inizio di ogni file — piu' `scritto`,
    che aggiunge questa funzione: il momento in cui quel marcatore e' nato,
    senza il quale i due residui non si possono invecchiare. Come per la
    pausa: qui si legge e basta, e un marcatore di un processo morto vale
    come assente.
    """
    import os

    p = paths or PATHS
    marcatore = p.work / ".queue"
    try:
        dati = su_disco.loads(marcatore.read_text())
        pid = int(dati["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # Quando è stato scritto: il marcatore nasce all'inizio di ogni file e
    # non viene più toccato, quindi `resta_min/max` invecchiano. Chi legge
    # deve poter sottrarre il tempo passato, altrimenti l'ora di fine
    # calcolata sull'adesso indietreggia di un minuto al minuto (visto il
    # 2026-08-10: la fascia diceva 14:43 per un file che finiva alle 13:23).
    try:
        dati["scritto"] = marcatore.stat().st_mtime
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    return dati


def residuo_coda(catena: dict | None, resto_file: float | None,
                 adesso: float | None = None) -> tuple[float, float] | None:
    """Quanto manca a TUTTA la coda: (minimo, massimo), o None.

    Sta qui e non nell'interfaccia perche' sia eseguibile da un test. E' lo
    stesso motivo di `tempo_che_resta`, e qui pesa di piu': questo conto
    mescola una MISURA (il file in corso) con delle STIME (i file che
    seguono), e uno sbaglio nel mescolarli non si vede guardando la pagina —
    si vede solo ore dopo, quando l'ora di fine promessa passa e il lavoro
    continua.

    Due regimi:

    - Senza niente di misurato si invecchia il marcatore: i due residui sono
      stati scritti all'inizio del file corrente, e vanno diminuiti del tempo
      passato da allora, o l'ora di fine calcolata sull'adesso indietreggia
      di un minuto al minuto.
    - Con il file in corso MISURATO, la sua quota non si invecchia: si
      sostituisce. Il resto della coda resta stimato, perche' quei file non
      sono ancora partiti e non c'e' niente da misurare. Prima si sottraeva
      l'orologio a una promessa e non si imparava mai: per quindici ore la
      fascia ha ripetuto 10h21 su un file che ne stava impiegando 15h14,
      mentre la riga sopra diceva il numero giusto (11/08).

    I marcatori scritti prima che `file_min`/`file_max` esistessero non li
    portano: li' si resta al primo regime, invece di sottrarre zero e
    contare il file corrente due volte.
    """
    if not isinstance(catena, dict):
        return None
    # `_numero` torna None su qualunque cosa non sia un numero vero: i
    # marcatori li scrive un processo che puo' morire a meta' riga.
    resta_max = _numero(catena.get("resta_max")) or 0.0
    if resta_max <= 0:
        return None
    resta_min = _numero(catena.get("resta_min")) or 0.0
    quota_min = _numero(catena.get("file_min")) or 0.0
    quota_max = _numero(catena.get("file_max")) or 0.0

    if resto_file is not None and quota_max > 0:
        resto = max(0.0, float(resto_file))
        return (resto + max(0.0, resta_min - quota_min),
                resto + max(0.0, resta_max - quota_max))

    ora = adesso if adesso is not None else time.time()
    passato = max(0.0, ora - (_numero(catena.get("scritto")) or ora))
    return (resta_min - passato, resta_max - passato)


def dedup_esatta(cartella: Path) -> tuple[float, int] | None:
    """La deduplica ESATTA di questo file: (quota, fotogrammi totali).

    E' la sola misura di deduplica su cui si possa stimare, e non richiede
    di aspettare nemmeno un blocco: la mappa si costruisce in una volta
    sola sul file INTERO subito dopo l'estrazione, prima che il primo blocco
    parta (`pipeline._dedup_map`). Su Koyomimonogatari 12, misurato il
    12/08: lucchetto alle 23:02:53, `dedup.json` alle 23:09:12, cioe' sei
    minuti dentro una lavorazione di tre ore.

    Da preferire SEMPRE a `dedup_misurata`, che guarda i blocchi gia' fatti
    e nella prima meta' del file mente di venti punti (vedi li').
    """
    try:
        dati = json.loads((cartella / "dedup.json").read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    # Il file lo scrive un processo che puo' morire a meta': ogni campo va
    # verificato prima di crederci, e un `total` a zero manderebbe in
    # divisione per zero l'intera pagina.
    if not isinstance(dati, dict):
        return None
    totale, tenuti = dati.get("total"), dati.get("keep")
    if not isinstance(totale, int) or totale <= 0:
        return None
    if not isinstance(tenuti, list):
        return None
    quanti = len(set(tenuti))
    if quanti > totale:
        return None
    return max(0.0, 1.0 - quanti / totale), totale


def dedup_misurata(cartella: Path) -> tuple[float, int] | None:
    """La deduplica dei blocchi GIA' FATTI, e su quanti blocchi.

    ATTENZIONE: non usarla per correggere una stima. Serve a raccontare cosa
    e' successo finora, non a prevedere cosa succedera'.

    Misurato il 12/08 sulla mappa completa di Koyomimonogatari 12 (deduplica
    vera 31,8%), blocco per blocco: 54,5 - 49,9 - 30,4 - 52,9 - 43,7 - 19,4 -
    6,3 - 7,8 - 3,9 - 49,2%. Non e' rumore, e' la struttura dell'episodio:
    sigle ferme in testa e in coda, corpo centrale in movimento. Chi si
    fidasse del primo blocco stimerebbe il 54,5% invece del 31,8% e
    prometterebbe il file un terzo piu' corto del vero; la mediana storica,
    che non impara niente, sullo stesso file sbaglia del 2%.

    Per stimare c'e' `dedup_esatta`, che il numero giusto ce l'ha da subito.
    """
    try:
        dati = su_disco.loads((cartella / "state.json").read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    # Ogni voce va guardata con sospetto: `state.json` lo scrive un processo
    # che puo' essere ucciso a meta' scrittura, e una lettura che solleva
    # qui farebbe cadere l'intera pagina per un file di stato malformato.
    # Trovato in audit: con `blocchi` non lista, o con valori non numerici,
    # questa funzione sollevava AttributeError e ValueError.
    blocchi = dati.get("blocchi")
    if not isinstance(blocchi, list):
        return None
    nominali = tenuti = 0
    validi = 0
    for b in blocchi:
        if not isinstance(b, dict):
            continue
        try:
            da, a, t = int(b.get("da", 0)), int(b.get("a", 0)), int(b.get("tenuti", 0))
        except (TypeError, ValueError):
            continue
        n = a - da
        if n <= 0 or t <= 0:
            continue
        # Piu' fotogrammi tenuti che nominali non e' possibile: se capita, il
        # blocco e' scritto male e non deve inquinare la media.
        nominali += n
        tenuti += min(t, n)
        validi += 1
    if not nominali or not validi:
        return None
    return max(0.0, 1.0 - tenuti / nominali), validi


def sospeso(lavoro: StatoLavoro) -> dict | None:
    """Il marcatore di pausa di questa lavorazione, se e' in pausa.

    Contiene l'istante di inizio (`da`) e i PID congelati. La pausa vera e'
    un `SIGSTOP` ai processi figli; questo file serve a raccontarlo, e a far
    ritrovare i congelati se l'interfaccia muore nel frattempo — un processo
    fermato resta fermo per sempre, e senza un segno in giro nessuno saprebbe
    piu' quale risvegliare.
    """
    from .pipeline import SOSPESO
    try:
        dati = su_disco.loads((lavoro.cartella / SOSPESO).read_text())
        return dati if isinstance(dati, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def trascorso(lavoro: StatoLavoro) -> str:
    """Da quanto lavora, SENZA contare le pause.

    L'orologio non basta: durante una pausa i processi sono congelati e non
    si lavora, ma il tempo passa. Contarlo direbbe una bugia a schermo e —
    peggio — finirebbe nella pagella, cioe' nei dati da cui l'app impara a
    stimare i file successivi.
    """
    if not lavoro.avviato:
        return ""
    from .pipeline import sospensione
    s = int(max(0.0, time.time() - lavoro.avviato - sospensione(lavoro.cartella)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def andatura(campioni: list[tuple[float, int]]) -> float | None:
    """Fotogrammi al secondo dalla finestra di campioni (istante, fatti).

    Il ritmo si misura fra il campione più vecchio e il più recente della
    finestra, NON dall'avvio: l'estrazione corre a decine di fotogrammi al
    secondo e l'upscale a uno o due, e una media dall'inizio produrrebbe una
    ETA ottimista che si allunga mentre la guardi. Sotto i 3 secondi o senza
    avanzamento non si risponde: meglio nessun numero che un numero inventato.
    """
    if len(campioni) < 2:
        return None
    (t0, f0), (t1, f1) = campioni[0], campioni[-1]
    if t1 - t0 < 3 or f1 <= f0:
        return None
    return (f1 - f0) / (t1 - t0)


FINESTRA_RITMO = 30


# Le fasi in cui `fatti` conta la STESSA cosa: fotogrammi passati per la GPU.
# Fra queste due il conteggio prosegue, quindi il riferimento sopravvive al
# cambio turno — ed è proprio lì che serve (vedi la regola 3).
UNITA_UPSCALE = ("elaborazione", "codifica blocco")

# Quanti cali di fila prima di credere che il conteggio si sia ribassato per
# davvero invece di essere l'artefatto di un confine di blocco. Con un giro
# ogni due secondi sono una ventina di secondi senza numero: molto più della
# finestra sporca di un confine (osservata sotto il secondo, campionando a
# 1 Hz su tre confini veri) e molto meno delle ore che costava non avere
# alcuna via d'uscita.
SCARTI_PRIMA_DI_ARRENDERSI = 10

# Quanto puo' passare fra due osservazioni perche' restino confrontabili.
# Il giro dell'interfaccia e' di pochi secondi: un buco piu' lungo di questo
# vuol dire che non si stava guardando, e cio' che si trova al ritorno non
# racconta niente di quello che e' successo in mezzo.
BUCO_MASSIMO = 60.0


def aggiorna_campioni(
    campioni: dict[str, list[tuple[float, int]]],
    stati: dict[str, dict],
    vivi: list[tuple[str, str, int]],
    adesso: float,
    quanti: int = FINESTRA_RITMO,
) -> None:
    """Aggiunge un campione per ogni lavoro vivo, tenendo la finestra pulita.

    `vivi` sono terne (nome della cartella, fase, fotogrammi fatti). La
    funzione lavora sui due dizionari in luogo: `campioni` è la finestra da
    cui `andatura` ricava il ritmo, `stati` tiene per ogni lavoro un
    dizionario con `fase` e `visto` (l'ultimo conteggio ritenuto buono),
    `scartati`, `visto_a` (quando lo si è guardato l'ultima volta) e il
    cronometro dei turni di codifica (`turno_da`, `turni_n`, `turni_somma`).
    La forma è interna e ha già cambiato pelle più volte: chi la riceve la
    normalizza, e chi la legge lo fa solo attraverso `turno_misurato`.

    Tre regole, e sono la stessa: nella finestra ci va solo roba omogenea.

    1. Si azzera a OGNI cambio di fase. `fatti` conta cose diverse in fasi
       diverse — in estrazione i fotogrammi tirati fuori, in elaborazione
       quelli ingranditi, e il secondo conteggio riparte da zero — quindi un
       campione dell'estrazione rimasto in finestra ancorava il calcolo a un
       numero che non c'entrava niente. Osservato dal vivo sull'interfaccia,
       col codice di allora: 1.84 fps mostrati, cioè esattamente
       (99-47)/(30.3-2.0), col 47 preso dall'estrazione. È storia, non una
       cosa riproducibile oggi togliendo questa regola — per quella vale la
       tabella in fondo, che si rigioca sulla registrazione.
    2. Prima che esca il primo fotogramma non si campiona. Fra la fine
       dell'estrazione e il primo fotogramma ingrandito ci sono la scansione
       della deduplica, i collegamenti del blocco e il caricamento del
       modello: `fatti` resta a zero, e uno zero non è un ritmo lento, è
       l'assenza di ritmo. Ancorava la finestra al tempo morto.
    3. Un conteggio che TORNA INDIETRO si butta, non si registra. Restando
       nella stessa fase, `fatti` può calare: a fine blocco la pipeline
       cancella le cartelle `chunk*` (pipeline.py, in fondo a
       `_process_chunk`) PRIMA che il segmento finito venga registrato nello
       stato, e per qualche giro il conteggio è il massimo fra un segmento
       che non c'è ancora e una cartella che sta sparendo. Un campione così
       fa da ancora per tutta la lunghezza della finestra: misurato, il ritmo
       mostrato saliva a 25 fps e il tempo che resta scendeva da due ore a
       venti minuti. Succede a ogni blocco, non una volta per file. Il
       riferimento sopravvive al turno di codifica proprio per riconoscere
       questi valori appena il turno finisce.

    L'effetto della regola 1, misurato rigiocando la registrazione di una
    lavorazione vera che sta in tests/run.py (ritmo di riferimento 4.605
    f/s, cioè la pendenza dell'indice):

      senza la regola  primo numero 97.14 f/s a 8.2 s   (ventuno volte il
                       vero: è il ritmo dell'estrazione rimasto in finestra)
      con la regola    primo numero  4.39 f/s a 16.3 s  (entro il 5%)

    Il numero giusto arriva otto secondi dopo quello sbagliato, ed è il
    baratto che questo modulo sceglie ovunque: meglio tacere che inventare.
    """
    nomi = {nome for nome, _, _ in vivi}
    for morto in [k for k in campioni if k not in nomi]:
        del campioni[morto]
    for morto in [k for k in stati if k not in nomi]:
        # I turni misurati NON si buttano: appartengono al file, non alla
        # sessione, e un solo giro in cui il lavoro non risulta vivo — cosa
        # che capita a ogni Ferma e Riprendi — faceva ricadere la stima
        # sulla taratura, che sottostima del 49%. Del resto si fa piazza
        # pulita: fase, riferimento e cronometro non valgono più niente.
        vecchio = stati[morto] if isinstance(stati[morto], dict) else {}
        stati[morto] = {"turni_n": vecchio.get("turni_n", 0),
                        "turni_somma": vecchio.get("turni_somma", 0.0)}
    for nome, fase, fatti in vivi:
        stato = stati.get(nome)
        # La forma di questo stato è già cambiata tre volte. Una forma
        # vecchia sopravvissuta in una sessione aperta faceva morire la
        # pagina in modo PERMANENTE: l'eccezione partiva prima della
        # riscrittura, quindi il valore malato restava lì e ogni giro
        # successivo ci ricadeva. Si normalizza e si riparte.
        if not isinstance(stato, dict):
            stato = {}
        prima = stato.get("fase")
        visto = stato.get("visto")
        scartati = stato.get("scartati", 0)
        # Quanto dura un turno di codifica lo si MISURA su questa
        # lavorazione, invece di dedurlo dalla taratura: il turno comprende
        # anche la ricostruzione dei fotogrammi duplicati, che la taratura
        # non misura, e infatti la sottostimava del 49% (confronto fra 234 s
        # previsti e 280/463/303 s misurati su una corsa a quattro blocchi).
        turno_da = stato.get("turno_da")
        turni_n = stato.get("turni_n", 0)
        turni_somma = stato.get("turni_somma", 0.0)
        # Questa funzione gira solo mentre la scheda Lavorazione è a video.
        # Passando a un'altra scheda i giri si fermano ma lo stato resta, e
        # `prima` diventa "l'ultima fase VISTA", non l'ultima avvenuta.
        # Senza accorgersene: lasciando la pagina a metà turno il cronometro
        # continuava a correre e misurava 910 secondi per un turno da 350;
        # rientrando dieci secondi prima della fine ne misurava dieci. In
        # media ci restavano per tutto il file, sbagliando la riga del
        # +148% o del -35% (misurato).
        buco = adesso - stato["visto_a"] if "visto_a" in stato else 0.0
        if buco > BUCO_MASSIMO:
            turno_da = None      # qualunque turno in corso non è misurabile
            prima = None         # e la fase di prima non è più una notizia
            campioni.pop(nome, None)   # né lo sono i campioni di allora
        if fase == "codifica blocco":
            # Il cronometro parte solo se si è VISTO il turno cominciare.
            if turno_da is None and prima is not None and prima != fase:
                turno_da = adesso
        elif turno_da is not None:
            # Si tiene la MEDIA dei turni visti, non l'ultimo: i turni
            # ballano parecchio (misurati 280, 463 e 303 secondi sulla
            # stessa corsa) e prendere l'ultimo faceva sbagliare la stima
            # del +35% invece del -27%, con l'errore medio da 15% a 19%
            # (ricalcolati dalla registrazione, non a memoria).
            # `adesso` viene da un orologio di parete, che può tornare
            # indietro: un turno negativo finiva in media e la riga
            # scriveva «restano -00:13:20» (misurato). Si scarta.
            durata = adesso - turno_da
            if durata > 0:
                turni_n, turni_somma = turni_n + 1, turni_somma + durata
            turno_da = None
        if prima not in (None, fase):
            campioni.pop(nome, None)
            if not (fase in UNITA_UPSCALE and prima in UNITA_UPSCALE):
                visto = None
            scartati = 0
        # Durante la codifica del blocco la GPU è ferma per minuti: i
        # campioni piatti sporcavano il ritmo alla ripartenza (la ETA diceva
        # 8 ore invece di 6, misurato dall'utente).
        if fase == "codifica blocco":
            campioni.pop(nome, None)
            # Il conteggio va ricordato ANCHE qui, perché in questa fase è
            # per costruzione il massimo del blocco appena finito. Senza,
            # la regola 3 resta senza riferimento tutte le volte che la
            # pagina viene aperta mentre un blocco è in codifica — cioè due
            # volte su tre (misurato dal vivo: la codifica occupa il 62-72%
            # del tempo di un blocco) — e il difetto si ripresentava tale e
            # quale: 32.9 fps mostrati e «restano 16 minuti» invece di 2h14.
            if fatti:
                visto = max(visto or 0, fatti)
        elif not fatti:
            pass
        elif visto is not None and fatti < visto:
            # Finché si scarta non si pubblica NIENTE: lasciando la finestra
            # ferma, `andatura` continuerebbe a rispondere su istanti vecchi
            # — un ritmo congelato che sembra vivo, peggio del silenzio.
            campioni.pop(nome, None)
            scartati += 1
            if scartati >= SCARTI_PRIMA_DI_ARRENDERSI:
                # Il calo non era l'artefatto di un confine di blocco: il
                # conteggio si è ribassato per davvero. Succede — la
                # pipeline può riscrivere l'elenco dei segmenti con un
                # estremo più basso, per esempio riprendendo una lavorazione
                # con blocchi di dimensione diversa perché è cambiato lo
                # spazio libero. Senza questa uscita si scartava per sempre:
                # su un episodio vero sono ore senza più un tempo stimato.
                # Si prende atto del nuovo livello, ma NON lo si mette in
                # finestra: farebbe da ancora bassa esattamente come il
                # valore sporco che la regola serve a togliere.
                visto, scartati = fatti, 0
        else:
            visto, scartati = fatti, 0
            serie = campioni.setdefault(nome, [])
            serie.append((adesso, fatti))
            del serie[:-quanti]
        stati[nome] = {"fase": fase, "visto": visto, "scartati": scartati,
                       "turno_da": turno_da, "turni_n": turni_n,
                       "turni_somma": turni_somma, "visto_a": adesso}


def turno_da_taratura(blocco_totale: int, larghezza: int, altezza: int,
                      fps_codifica: float) -> float | None:
    """Quanto costerà il turno di codifica di UN blocco, secondo la taratura.

    Serve solo finché non se n'è misurato uno vero su questa lavorazione: da
    lì in poi vince la misura. È una sottostima NOTA — il turno comprende
    anche la ricostruzione dei fotogrammi duplicati, che la taratura non
    misura, e su una corsa vera prevedeva 234 s contro 280/463/303 reali —
    ma sommare un turno sottostimato resta molto più vicino al vero che
    fingere che i turni non esistano.

    La formula è la stessa di `plan._fuori_gpu`: i fotogrammi del blocco per
    il rapporto fra i pixel dell'uscita e quelli a cui la codifica è tarata.
    """
    if not blocco_totale or not larghezza or not altezza:
        return None
    fattore = (larghezza * altezza) / (1920 * 1080)
    return blocco_totale * fattore / max(0.1, fps_codifica)


def tempo_che_resta(fatti: int, totale: int, ritmo: float | None, *,
                    blocchi_totali: int = 0, blocco_n: int = 0,
                    blocco_totale: int = 0,
                    turno: float | None = None) -> float | None:
    """Quanto manca alla fine del FILE: upscale, turni di codifica e coda.

    Tre pezzi, e i primi due erano quelli che mancavano.

    1. L'upscale che resta, al ritmo misurato.
    2. I turni di codifica fra un blocco e il successivo. Lì la GPU si ferma
       e la CPU codifica: quel tempo non sta nel ritmo dell'upscale, e
       ignorarlo faceva promettere molto meno di quanto sarebbe costato.
       Misurato su una corsa a quattro blocchi: i tre turni sono costati
       1046 secondi, il 57% del tempo speso fino a fine upscale, e a dieci
       minuti dall'inizio la riga diceva «restano 7 minuti» quando ne
       servivano 20.
    3. La coda: l'ultimo blocco non ha un turno DOPO di sé, ma la sua
       codifica va fatta lo stesso, e poi c'è il montaggio. Costa in
       proporzione ai fotogrammi che l'ultimo blocco contiene — che sono
       meno di un blocco pieno, perché è il resto della divisione.
       Verificato sulla stessa corsa: 568 fotogrammi su 810, cioè 0,701 di
       un turno medio da 349 s, dà 244 s contro i 258 misurati. I 13 s di
       differenza sono il montaggio, che non si modella: sta dentro il
       rumore della proporzione.
    """
    if not ritmo or ritmo <= 0:
        return None
    resta = max(0, totale - fatti) / ritmo
    if not turno:
        return resta
    resta += max(0, (blocchi_totali or 1) - (blocco_n or 1)) * turno
    if blocchi_totali and blocco_totale:
        ultimo = totale - (blocchi_totali - 1) * blocco_totale
        if 0 < ultimo <= blocco_totale:
            resta += turno * ultimo / blocco_totale
    return resta


def turno_misurato(stati: dict, nome: str) -> float | None:
    """Quanto dura in media un turno di codifica di questo lavoro, sui turni
    visti per intero. `None` finché non se n'è visto nessuno: è il primo
    blocco, e a quel punto chi chiama decide se ripiegare sulla taratura o
    tacere."""
    stato = stati.get(nome) or {}
    n = stato.get("turni_n", 0)
    return stato["turni_somma"] / n if n else None


def _numero(valore: object) -> float | None:
    """Il valore come numero, o None. Un record manomesso non deve arrivare
    all'interfaccia e farla esplodere su una `float()`."""
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    return float(valore)


def ultimo_lancio(paths: Paths | None = None) -> dict | None:
    """L'ultimo LANCIO — non l'ultimo comando — se ce n'e' uno.

    L'interfaccia spezza una coda in un comando per MODELLO, quindi una
    maratona lascia piu' record. Si rimettono insieme per ETICHETTA: e'
    quella che li lega, e non si deduce da nient'altro. La prima versione la
    deduceva da "quanti file mancano al totale", e una coda fermata a meta'
    — cioe' il caso piu' frequente — non arrivava mai a quel totale e il suo
    resoconto spariva per sempre; e due lanci diversi con lo stesso numero di
    file potevano fondersi fra loro, sommando ore che non c'erano state
    (audit del 2026-08-10, quinto giro).

    Non si pretende che il lancio sia "completo": non e' una cosa che si
    possa sapere da qui, e non serve — a decidere se c'e' ancora qualcosa in
    corso ci pensa il marcatore di catena, che chi chiama guarda gia'.

    Vive su disco e non in memoria apposta: il resoconto deve esserci anche
    se l'interfaccia era chiusa mentre la coda lavorava.
    """
    p = paths or PATHS
    try:
        # `errors="replace"`: un file troncato a meta' di un carattere
        # accentato — i nomi dei rilasci anime ne sono pieni — sollevava
        # UnicodeDecodeError, che NON e' una OSError, e da li' in poi la
        # pagina si rompeva a ogni giro.
        testo = p.lanci.read_text(errors="replace")
    except OSError:
        return None

    pezzi: list[dict] = []
    etichetta: object = None
    for riga in reversed(testo.splitlines()):
        try:
            dato = su_disco.loads(riga)
        except ValueError:
            continue
        if not isinstance(dato, dict) or _numero(dato.get("fine")) is None:
            continue
        mia = dato.get("lancio")
        if etichetta is None:
            etichetta = mia
        elif mia != etichetta:
            break            # comincia un altro lancio: si smette
        pezzi.append(dato)
        # Senza etichetta (record vecchi, o CLI lanciata a mano una volta
        # sola) non c'e' niente da rimettere insieme.
        if not isinstance(etichetta, str) or not etichetta:
            break
    if not pezzi:
        return None
    if len(pezzi) == 1:
        return pezzi[0]

    def _lista(d: dict, chiave: str) -> list:
        v = d.get(chiave)
        # Non un iterabile qualunque: una stringa si scioglierebbe in
        # lettere, e "bcd" diventerebbe tre file.
        return list(v) if isinstance(v, (list, tuple)) else []

    def _unisci(chiave: str) -> list:
        fuori: list = []
        for d in reversed(pezzi):
            fuori.extend(_lista(d, chiave))
        return fuori

    inizi = [x for x in (_numero(d.get("inizio")) for d in pezzi)
             if x is not None]
    fini = [x for x in (_numero(d.get("fine")) for d in pezzi)
            if x is not None]
    dedup = [x for x in (_numero(d.get("dedup_medio")) for d in pezzi)
             if x is not None]
    pause = [x for x in (_numero(d.get("pausa_minuti")) for d in pezzi)
             if x is not None]
    return {
        "lancio": etichetta,
        # `fini` non e' mai vuota: il filtro all'ingresso lo garantisce.
        "inizio": min(inizi) if inizi else min(fini),
        "fine": max(fini),
        "previsti": _unisci("previsti"), "riusciti": _unisci("riusciti"),
        "falliti": _unisci("falliti"), "scartati": _unisci("scartati"),
        "interrotti": _unisci("interrotti"),
        "secondi": sum(_numero(d.get("secondi")) or 0 for d in pezzi),
        "avvisi": int(sum(_numero(d.get("avvisi")) or 0 for d in pezzi)),
        "dedup_medio": (round(sum(dedup) / len(dedup), 3) if dedup else None),
        # La pausa piu' lunga fra i pezzi: e' un'impostazione, non una somma.
        "pausa_minuti": max(pause) if pause else None,
    }
