"""Deduplica dei fotogrammi identici.

L'animazione giapponese è spesso disegnata "in due" o "in tre": lo stesso
disegno resta in scena per 2-3 fotogrammi. Nel master quei fotogrammi sono
identici; nel file codificato differiscono per il solo rumore di dithering,
quindi un confronto bit a bit non li riconosce.

Criterio adottato, volutamente dimostrabile invece che euristico:

    si scarta un fotogramma solo se NESSUN SINGOLO PIXEL, SU NESSUNO DEI TRE
    CANALI, si discosta dal fotogramma di riferimento più della soglia.

Non è una stima di somiglianza: è un limite superiore sull'errore. Se una
bocca si muove, quei pixel cambiano molto e il fotogramma viene tenuto. Ed è
un MASSIMO, non una media: che i pixel in movimento siano due o duemila non
cambia nulla, il che è precisamente la garanzia che serve sull'animazione a
inquadratura fissa.

"Su nessuno dei tre canali" è stato una correzione, non il progetto
originale. La prima versione misurava con `signalstats`, che riporta il
massimo del piano Y: un cambiamento di colore a luminanza costante le
risultava ZERO, e la garanzia scritta qui sopra era semplicemente falsa. Con
la soglia a 16 passavano indisturbati 163 livelli di blu, 62 di rosso, 31 di
verde su un singolo pixel. Non era teorico: sul primo episodio reale il caso
peggiore era una dissolvenza di colore nei titoli di testa, 39/255 su un
quarto del quadro, misurata come 15.59 e quindi scartata. Misurare i tre piani
costa il 4,7% di risparmio in meno (45,8% -> 41,1%) ed è un affare.

Due protezioni ulteriori:
  - il confronto è sempre con l'ultimo fotogramma TENUTO, non col precedente,
    così una dissolvenza lenta non resta congelata sommando scarti minimi;
  - un tetto al numero di scarti consecutivi limita il raggio d'azione di un
    eventuale errore di implementazione a una frazione di secondo.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .ffmpeg import run_stderr
from .paths import PATHS, Paths

_YMAX = re.compile(r"YMAX=([0-9.]+)")

# Soglia in scala 8 bit: uno scostamento di 16/255 su un singolo pixel non è
# percepibile. Viene riscalata sulla profondita' di bit reale del sorgente,
# altrimenti su un file a 10 bit sarebbe quattro volte più permissiva.
DEFAULT_THRESHOLD_8BIT = 16.0

# Massimo numero di fotogrammi consecutivi scartabili. Misurato sul materiale
# reale, stringere a 5 costa lo 0,1% di lavoro in più: si tratta di una
# protezione praticamente gratuita.
DEFAULT_MAX_RUN = 5

# Tetto oltre il quale un `max_run` non è più una protezione ma un numero
# scritto per sbaglio: 1000 fotogrammi sono quaranta secondi di fila copiati
# da un solo disegno, che non è animazione "in due", è un guasto.
MAX_RUN_LIMITE = 1000

# Versione della METRICA. Entra nella chiave della cache: una mappa costruita
# con la vecchia misura cieca al colore non va riusata con la nuova, altrimenti
# si conserverebbe proprio il difetto che la correzione elimina.
METRIC_VERSION = 2


@dataclass
class DedupMap:
    """Quali fotogrammi elaborare e da dove copiare gli altri."""

    total: int
    keep: list[int]                      # indici 0-based da dare al modello
    source_of: list[int]                 # per ogni indice, il keep da cui copiare
    runs: list[int] = field(default_factory=list)
    threshold: float = 0.0
    max_run: int = DEFAULT_MAX_RUN
    capped: int = 0                      # scarti impediti dal tetto

    @property
    def unique(self) -> int:
        return len(self.keep)

    @property
    def saving(self) -> float:
        return 1.0 - self.unique / self.total if self.total else 0.0

    @property
    def longest_run(self) -> int:
        return max(self.runs, default=0)

    def keep_set(self) -> set[int]:
        return set(self.keep)


@dataclass
class DedupAudit:
    """Esito del controllo indipendente sulla mappa di deduplica.

    Le due liste sono separate perché richiedono rimedi opposti:

      `violations`  scostamento di contenuto oltre la soglia. Riparabile: si
                    promuove il fotogramma a "da elaborare" e il difetto
                    sparisce.
      `structural`  la mappa è malformata (riferimento in avanti, origine
                    inesistente, indice sfasato, tetto aggirato). Promuovere
                    non ripara niente: la mappa va buttata.

    Tenerle nella stessa lista faceva applicare la riparazione buona al guasto
    sbagliato, e il risultato era una mappa ancora rotta ma dichiarata sana.
    """

    checked: int
    violations: list[tuple[int, float]]
    structural: list[tuple[int, float]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations and not self.structural


def measure_frame_differences(
    frames_dir: Path,
    *,
    pattern: str = "%08d.png",
    paths: Paths | None = None,
) -> list[float]:
    """Differenza massima su singolo pixel fra fotogrammi consecutivi.

    La misura si fa sui fotogrammi GIA' ESTRATTI, non sul sorgente. È la sola
    forma che garantisce l'allineamento: due passate distinte sullo stesso
    video possono restituire conteggi diversi di una o due unità (reticolo
    temporale, fotogramma finale, filtri che consumano un ingresso), e uno
    scarto di un solo indice manda la mappa a puntare a fotogrammi sbagliati.
    Misurando ciò che verrà realmente elaborato, il problema non esiste.
    """
    p = paths or PATHS
    with tempfile.TemporaryDirectory(prefix="animeup-diff-") as tmp:
        metrics = Path(tmp) / "ymax.txt"
        # Massimo sui TRE piani RGB, non sulla sola luminanza. Vedi il
        # commento in testa al modulo: `signalstats` da solo misura Y, e un
        # cambiamento di colore a luminanza costante gli risulta zero.
        # `blend=lighten` prende il massimo pixel per pixel, quindi due
        # innesti danno il massimo dei tre piani; `signalstats` lo legge da
        # un'immagine in scala di grigi, dove Y coincide col valore.
        grafo = (
            "[0:v]tblend=all_mode=difference,format=gbrp,split=3[a][b][c];"
            "[a]extractplanes=r[r];[b]extractplanes=g[g];[c]extractplanes=b[bl];"
            "[r][g]blend=all_mode=lighten[rg];"
            "[rg][bl]blend=all_mode=lighten,signalstats,"
            f"metadata=print:key=lavfi.signalstats.YMAX:file={metrics}[out]"
        )
        cmd = [
            str(p.ffmpeg.path), "-hide_banner", "-v", "error",
            # Il percorso si passa RELATIVO, con la cwd sulla cartella: il
            # muxer image2 legge `%` come segnaposto anche in una componente
            # di directory, quindi un disco chiamato "Pieno al 50%" faceva
            # fallire la misura e spegneva la deduplica senza spiegazioni.
            "-i", pattern,
            "-filter_complex", grafo, "-map", "[out]",
            "-an", "-sn", "-f", "null", "-",
        ]
        # Misurato sui fotogrammi veri: 102 fotogrammi al secondo,
        # cioè circa tre minuti su un episodio intero. La misura sui
        # tre piani costa 1.4 volte quella sulla sola luminanza.
        run_stderr(cmd, cwd=frames_dir, timeout=4 * 3600)
        if not metrics.is_file():
            return []
        return [float(m) for m in _YMAX.findall(metrics.read_text())]


FINESTRE_CAMPIONE = 6
SECONDI_CAMPIONE = 4.0


def stima_campionata(
    src: Path, durata: float, *, finestre: int = FINESTRE_CAMPIONE,
    secondi: float = SECONDI_CAMPIONE, paths: Paths | None = None,
) -> float | None:
    """Quanta deduplica ci si aspetta su QUESTO file, misurata su un campione.

    Prima si tirava a indovinare accostando i file per numero di fotogrammi, e
    il criterio pescava il fratello sbagliato: per Monogatari S06E02 (rilascio
    TV, deduplica vera 33,4%) sceglieva Tsukimonogatari 01 (BD, 6,5%) perche'
    avevano 34.841 e 34.765 fotogrammi. Quasi quattro ore di errore su una
    stima di tredici (voce 84).

    Qui invece si misura, con la stessa regola della deduplica vera — stesse
    differenze, stessa soglia, stesso `build_map` — su sei finestre da quattro
    secondi sparse per il file. Validata contro le deduplica vere:

        Koyomimonogatari 01 (TV)   0,410 vero   0,410 stimato
        Tsukimonogatari 02 (BD)    0,133 vero   0,127 stimato
        Tsukimonogatari 03 (BD)    0,145 vero   0,113 stimato

    cioe' 1,3 punti di errore medio contro i 26,9 dello sbaglio che sostituisce.

    UNA SOLA passata di decodifica, con `select`, non sei salti: costa la
    meta' (32-46 s invece di 61-108) e soprattutto evita il salto rapido, che
    su questi encode a intra-refresh consegna fotogrammi ricostruiti — con
    quelli la stima usciva 0,005 su un file che sta al 41%.

    Torna `None` se non si e' potuto misurare: e' diverso da «zero», e chi
    stima deve poter distinguere i due casi.
    """
    p = paths or PATHS
    if durata <= 0:
        return None
    a, b = durata * 0.08, durata * 0.92
    if b - a < secondi * 2:
        return None
    passo = (b - a) / max(1, finestre)
    # Le virgole vanno protette con la barra: dentro un filtergraph separano
    # i FILTRI, e `between(t,116,120)` faceva cercare a ffmpeg un filtro
    # chiamato «116.00».
    sel = "+".join(
        f"between(t\\,{a + passo * k:.2f}\\,{a + passo * k + secondi:.2f})"
        for k in range(finestre))
    with tempfile.TemporaryDirectory(prefix="animeup-campione-") as tmp:
        d = Path(tmp)
        run_stderr([
            str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y",
            "-i", str(src), "-vf", f"select={sel}",
            "-fps_mode", "passthrough", "-an", "-sn", "-dn",
            "-pix_fmt", "rgb24", "-c:v", "png", "-pred", "mixed",
            str(d / "%08d.png"),
        ])
        if len(list(d.glob("*.png"))) < finestre * 4:
            return None
        diffs = measure_frame_differences(d, paths=p)
        if len(diffs) < 20:
            return None
        # `bit_depth=8` perche' i fotogrammi sono stati estratti in rgb24,
        # come fa la pipeline vera: e' la stessa scala su cui e' tarata la
        # soglia.
        m = build_map(diffs, bit_depth=8)
        return max(0.0, 1.0 - len(m.keep) / m.total)


def build_map(
    diffs: list[float],
    *,
    bit_depth: int = 8,
    threshold_8bit: float = DEFAULT_THRESHOLD_8BIT,
    max_run: int = DEFAULT_MAX_RUN,
) -> DedupMap:
    """Costruisce la mappa a partire dalle differenze fra fotogrammi.

    `diffs[i]` è la differenza fra il fotogramma i+1 e il fotogramma i.
    """
    total = len(diffs) + 1
    scale = (2 ** bit_depth - 1) / 255.0
    threshold = threshold_8bit * scale

    keep = [0]
    source_of = [0]
    runs: list[int] = []
    drift = 0.0
    run = 0
    capped = 0

    for index, delta in enumerate(diffs, start=1):
        # Somma degli scostamenti dall'ultimo tenuto: è un limite superiore
        # della differenza reale dal riferimento (disuguaglianza triangolare),
        # quindi sbaglia sempre per eccesso di prudenza.
        drift += delta
        hit_cap = run >= max_run
        if drift <= threshold and not hit_cap:
            run += 1
            source_of.append(keep[-1])
        else:
            if hit_cap and drift <= threshold:
                capped += 1
            if run:
                runs.append(run)
            run = 0
            drift = 0.0
            keep.append(index)
            source_of.append(index)
    if run:
        runs.append(run)

    return DedupMap(
        total=total, keep=keep, source_of=source_of, runs=runs,
        threshold=threshold, max_run=max_run, capped=capped,
    )


def structure_ok(dmap: DedupMap) -> bool:
    """Invarianti strutturali sole, senza bisogno delle differenze misurate.

    Serve a controllare una mappa RILETTA DA DISCO: lì le differenze non ci
    sono più, ma la mappa può essere stata troncata, modificata a mano o
    scritta da una versione precedente con un'altra convenzione. Senza questo
    controllo una mappa malformata arrivava intatta fino all'elaborazione e
    falliva con un FileNotFoundError su un nome di file inesistente.
    """
    if len(dmap.source_of) != dmap.total or dmap.total < 1:
        return False
    # Un `max_run` assurdo riletto da disco annullerebbe il tetto senza che
    # nulla lo dica. Il limite è un tetto ASSOLUTO e non `total`: una sequenza
    # di quattro fotogrammi col tetto predefinito a 5 è legittima, e
    # confrontarlo con `total` la rifiutava.
    if not isinstance(dmap.max_run, int) or isinstance(dmap.max_run, bool):
        return False
    if not 0 <= dmap.max_run <= MAX_RUN_LIMITE:
        return False
    keep = dmap.keep_set()
    if len(keep) != len(dmap.keep):
        return False
    # Gli indici di `keep` devono ESISTERE. Controllando solo che ogni
    # `source_of[i]` fosse dentro `keep` non si guardava mai il contenuto di
    # `keep`: un indice negativo o fuori intervallo passava indisturbato, e
    # `unique` e il risparmio mostrato all'utente diventavano falsi.
    if any(not isinstance(i, int) or not 0 <= i < dmap.total for i in dmap.keep):
        return False
    if 0 not in keep:
        return False        # il primo fotogramma non si copia da nessuno
    return all(
        origine <= index
        and origine in keep
        and (origine == index) == (index in keep)
        and index - origine <= dmap.max_run
        for index, origine in enumerate(dmap.source_of)
    )


def audit(diffs: list[float], dmap: DedupMap) -> DedupAudit:
    """Controllo della mappa, sulla struttura che viene davvero usata.

    La versione precedente era una tautologia: ricalcolava la deriva con la
    stessa formula, la stessa soglia e gli stessi azzeramenti di `build_map`,
    quindi non poteva produrre violazioni per costruzione (verificato: zero su
    ventimila mappe casuali). E soprattutto non leggeva mai `source_of`, che
    è l'unica struttura che decide da quale fotogramma si copia — cioè
    esattamente ciò che il controllo dichiarava di sorvegliare.

    Qui si verificano invarianti su `source_of`, ciascuno scelto perché
    intercetta un guasto concreto:

      source_of[i] <= i            un riferimento in avanti punterebbe a un
                                   fotogramma non ancora prodotto
      source_of[i] in keep         altrimenti si copia da un file che nessuno
                                   scrivera': buco nel video finale
      (source_of[i] == i) == (i in keep)
                                   è questa a beccare lo sfasamento di un
                                   indice, il guasto più insidioso perché
                                   lascia tutti i conteggi corretti
      i - source_of[i] <= max_run  il tetto agli scarti consecutivi aggirato
      somma dei delta <= soglia    l'unica prova di CONTENUTO: ricalcolata dai
                                   dati grezzi usando source_of come tesi,
                                   non keep

    I primi quattro sono guasti strutturali: la promozione a "da elaborare"
    non li sana, vanno trattati come errore. Solo l'ultimo è riparabile.
    Escono infatti in `structural`, lista distinta da `violations`.
    """
    violations: list[tuple[int, float]] = []
    structural: list[tuple[int, float]] = []
    keep = dmap.keep_set()

    if len(dmap.source_of) != dmap.total or dmap.total != len(diffs) + 1:
        structural.append((-1, float(len(dmap.source_of))))
        return DedupAudit(checked=dmap.total, violations=[], structural=structural)

    for index, origine in enumerate(dmap.source_of):
        if origine > index or origine not in keep:
            structural.append((index, float(origine)))
            continue
        if (origine == index) != (index in keep):
            structural.append((index, float(origine)))
            continue
        if index - origine > dmap.max_run:
            structural.append((index, float(index - origine)))
            continue
        if origine == index:
            continue    # tenuto: non è stato copiato da nessuno, niente da provare
        # Prova sul contenuto: quanto si discosta davvero il fotogramma dal
        # riferimento da cui verrà copiato.
        scostamento = sum(diffs[origine:index])
        if scostamento > dmap.threshold:
            violations.append((index, scostamento))

    return DedupAudit(checked=dmap.total, violations=violations,
                      structural=structural)


def describe(dmap: DedupMap) -> str:
    """Riga di riepilogo leggibile."""
    return (
        f"{dmap.unique}/{dmap.total} fotogrammi da elaborare "
        f"({dmap.saving:.1%} risparmiato) - sequenze max {dmap.longest_run}, "
        f"media {sum(dmap.runs)/len(dmap.runs):.1f}" if dmap.runs
        else f"{dmap.unique}/{dmap.total} fotogrammi da elaborare"
    )
