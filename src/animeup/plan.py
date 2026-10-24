"""Dal referto di analisi al piano di lavorazione.

Questo modulo non esegue nulla: traduce quello che il file *e'* in quello che
va *fatto*, e lo rende ispezionabile prima di spendere ore di GPU.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .models import CATALOG, Model, Recommendation, recommend
from . import storico, taratura
from .i18n import t
from .paths import PATHS, Paths
from .probe import FieldMode, SourceReport, Timebase

# Peso medio di un PNG, in byte per pixel.

# Misurati con il comando esatto di extract_frames (png -pred mixed) su
# materiale reale: 0.95-1.02 per i sorgenti, ~1.7 per gli upscalati (più
# lisci, comprimono meglio). I valori precedenti (2.3 e 1.8) erano stime a
# occhio e sovrastimavano i sorgenti di due-tre volte.
BYTES_PER_PIXEL_SOURCE = 1.05
BYTES_PER_PIXEL_UPSCALED = 1.75

# Bitrate video atteso a 1080p con x265 crf 18 preset slower su animazione,
# in megabit al secondo. Serve solo a stimare quanto occupano i SEGMENTI, che
# restano tutti su disco fino all'assemblaggio, e il file finale, che viene
# scritto sullo stesso volume. Contarli non è un dettaglio: su un episodio
# 1080p sono una decina di GB, cioè abbastanza da far riempire il disco a
# metà lavorazione dopo che la guardia aveva detto di sì.
# Il valore è volutamente generoso, ma non assurdo: misurato 0,77 Mbps su una
# scena reale, e l'anime a crf 18 sta di solito fra 2 e 4. Stava a 6.0, cioè
# otto volte il misurato: irrilevante su un episodio da 24 minuti (~1 GB di
# fantasma) ma su un film di due ore verso 2160p diventavano ~42 GB stimati
# contro ~5 reali, e questa costante entra in un CANCELLO — la guardia che
# rifiuta di partire per spazio insufficiente.
EST_BITRATE_MBPS_1080P = 3.0

# Fotogrammi al secondo di x265 crf18 preset slower a 1080p 10 bit.
# Misurato 9.28 su 240 fotogrammi veri, a macchina scarica. Il valore
# precedente (3.2) veniva da una misura presa mentre la macchina era sotto
# carico 24-49, e faceva sovrastimare la codifica di tre volte.
# Qui si tiene 8.0: leggermente prudente, perché una scena molto mossa
# comprime più lentamente di quella misurata.
FPS_CODIFICA = 8.0

# Quota MASSIMA di fotogrammi che la deduplica riesce a saltare. Misurato su
# materiale reale: 57%, 46%, 41%, 28%, 11%. Serve a dare il PAVIMENTO
# dell'intervallo, quindi va preso il massimo osservato con un filo di
# margine: usando la mediana, l'estremo ottimista veniva mancato per
# costruzione in metà dei casi.
DEDUP_MASSIMO = 0.60

# Margine sul caso peggiore: la stima del tempo è fatta di misure medie, e su
# una scena molto mossa tutto costa di più. Un tetto che si buca non è un
# tetto.
MARGINE_PESSIMISTA = 1.25

# Il clip campione della taratura (`campioni/bbb-480p.mkv`): 854x480. Serve a
# riportare alla risoluzione vera i ritmi misurati su di lui — estrazione e
# scansione lavorano sui fotogrammi SORGENTE, quindi costano in proporzione
# ai pixel. (La codifica no: quella e' gia' misurata a 1080p, come esce.)
MPX_TARATURA = 854 * 480 / 1_000_000

# Rapporto di riduzione ideale dopo il modello: a 2.0 la media dei pixel è un
# antialiasing esatto. Ci si avvicina il più possibile.
IDEAL_DOWNSCALE = 2.0

DEFAULT_TARGET_HEIGHT = 1080

# Confine di ciò che questo strumento fa: ingrandimenti da 1.25x in su.
# Sotto, si spendono le stesse ore per una manciata di pixel — e a parita' di
# dimensioni o verso il basso non c'e' proprio niente da guadagnare.
GUADAGNO_MINIMO = 1.25
DEFAULT_PEAK_DISK_GB = 40.0

# Un blocco non superi mai questo, nemmeno su un disco enorme: e' un TETTO,
# non un obiettivo. Serve a impedire che con 500 GB dedicati un blocco solo
# se ne prenda 300 perche' puo' — e con lui tutto il lavoro che un incidente
# porterebbe via.
TETTO_BLOCCO_GB = 40.0

# Mai meno di tre blocchi. Un blocco e' atomico: interrotto, riparte da capo.
# Con due blocchi un blackout costa mezzo file; con tre, un terzo. Il prezzo
# di questa scelta e' misurato ed e' piccolo: 1,16 minuti di costo fisso per
# blocco (undici blocchi misurati su due macchine l'11/08).
BLOCCHI_MINIMI = 3

# ...e mai piu' di venti, nemmeno per rispettare il tetto. Oltre, il costo
# fisso (~1 minuto a blocco) comincia a mangiare piu' di quanto lo
# spezzettamento faccia risparmiare — e su un file lungo il tetto non si
# onora comunque, perche' il picco lo fanno i fotogrammi sorgente. Meglio
# dirlo che degenerare: e' il limite che impedisce i 146 blocchi visti prima
# della riscrittura.
BLOCCHI_MASSIMI = 20

# ...e mai blocchi da briciole: sotto questa soglia il minuto fisso comincia
# a pesare piu' del lavoro contenuto. Misurato sul MacBook: un blocco da
# 1.000 fotogrammi dura ~14 minuti, di cui 1,2 fissi (8%); uno da 300
# durerebbe ~5, di cui 1,2 fissi (23%).
BLOCCO_MINIMO_FOTOGRAMMI = 800


class PlanError(RuntimeError):
    """Il file non è processabile con i parametri richiesti.

    `sintesi` è la versione da tabella: due o tre parole che dicono QUALE
    ostacolo si è incontrato. Il messaggio lungo resta per chi vuole sapere
    perché e cosa fare, ma in una cella di elenco non ci sta, e ridurlo a
    "non elaborabile" non dice niente a nessuno.
    """

    def __init__(self, messaggio: str, sintesi: str | None = None) -> None:
        super().__init__(messaggio)
        # Il predefinito si traduce qui e non nella firma: la firma si
        # valuta una volta sola, all'import, nella lingua di allora.
        self.sintesi = sintesi if sintesi is not None else t("mot.plan.sintesi_default")


def output_name(
    stem: str,
    *,
    target_height: int,
    scale: int,
    model_tag: str,
    crf: int,
    denoise: bool = False,
    dedup: bool = False,
    preset: str = "slower",
    etichetta: str = "upscale",
) -> str:
    """Nome d'uscita: nome originale intatto, più i parametri di lavorazione.

    Il nome originale non si tocca: serve a riconoscere l'episodio e a farne
    quello che si vuole a valle. Il suffisso serve a distinguere due passaggi
    diversi sullo stesso sorgente, che è l'unica ambiguita' che conta.

    `preset` c'e' perché cambia il risultato, e due lavorazioni con preset
    diverso finivano sullo stesso file, la seconda sopra la prima, senza un
    avviso. Compare solo quando non è quello predefinito, per non allungare
    ogni nome con un dettaglio che di norma non cambia.
    """
    flags = ""
    if denoise:
        flags += " dn"
    if dedup:
        flags += " dd"
    if preset != "slower":
        flags += f" {preset}"
    return (f"{stem} [{etichetta} {target_height}p {model_tag} "
            f"x{scale} crf{crf}{flags}]")


@dataclass
class Restoration:
    """Filtri applicati al sorgente prima dell'upscale."""

    deinterlace: str | None = None
    denoise: str | None = None
    notes: list[str] = field(default_factory=list)

    def chain(self) -> list[str]:
        return [f for f in (self.deinterlace, self.denoise) if f]


@dataclass
class Dedup:
    enabled: bool
    threshold: str
    expected_ratio: float
    reason: str
    # `expected_ratio` viene da una previsione (i fotogrammi identici al bit
    # contati su un campione) oppure dalla mappa VERA di questo file. Sono
    # due cose diversissime — sulle puntate di Koyomimonogatari la previsione
    # dice meno del 2% e la misura un terzo — e chi legge la stima ha diritto
    # di sapere quale delle due sta guardando.
    misurata: bool = False


@dataclass
class Encoding:
    codec: str
    pix_fmt: str
    crf: int
    preset: str
    params: str
    color_args: list[str]
    # Matrice con cui swscale deve convertire i PNG (RGB) in YUV. Deve essere
    # LA STESSA che si scrive nell'etichetta: sono due cose diverse e vanno
    # tenute insieme a mano, perché l'etichetta non governa la conversione.
    swscale_matrix: str = "bt709"
    # I tre tag da riapporre sul fotogramma prima della codifica, nell'ordine
    # primaries, transfer, matrix.
    color_tags: tuple[str, str, str] = ("bt709", "bt709", "bt709")


@dataclass
class Plan:
    source: SourceReport
    output: Path
    log: Path

    target_width: int
    target_height: int
    model: Model
    model_key: str
    model_scale: int
    model_name: str
    model_width: int
    model_height: int
    downscale: float

    restoration: Restoration
    dedup: Dedup
    encoding: Encoding

    fps: Fraction
    frames: int
    chunk_size: int
    chunks: int

    est_gpu_seconds: float
    est_peak_disk_gb: float
    recommendation: Recommendation | None = None
    warnings: list[str] = field(default_factory=list)
    # Ritmi delle fasi fuori GPU: di fabbrica, oppure misurati da
    # `./animeup taratura` su questa macchina. Vivono nel piano perché le
    # proprieta' di stima non hanno accesso ai Paths.
    fps_estrazione: float = 60.0
    fps_codifica: float = FPS_CODIFICA
    stime_tarate: bool = False
    # La deduplica attesa secondo le lavorazioni gia' fatte (vedi
    # `storico.deduplica`). Quando c'e', la forchetta nasce da quello che
    # e' successo davvero invece che dai due estremi teorici.
    dedup_storico: object | None = None
    # La scansione che misura le differenze fra fotogrammi: era fissa a 200
    # f/s "a memoria". Vale l'1% della stima, ma non c'e' motivo di tenere
    # un numero inventato dove se ne puo' misurare uno.
    fps_scansione: float = 200.0
    # I due ritmi qui sopra sono fotogrammi/secondo MISURATI SUL CLIP DELLA
    # TARATURA, che e' un 480p: estrarre e scandire un 720p costa piu' del
    # doppio a fotogramma. Senza questo riferimento i due numeri venivano
    # applicati tali e quali a qualunque risoluzione (audit del 2026-08-10).
    # Le tarature scritte prima che il campo esistesse non lo portano: il
    # ripiego e' il clip campione distribuito con AnimeUp, che e' quello con
    # cui sono state fatte.
    mpx_taratura: float = MPX_TARATURA
    # Lo scarto fra promesso e impiegato, misurato sulle pagelle: copre
    # cio' che nessuna voce conta (montaggio, controlli finali, tempi
    # morti). None = nessuna storia, nessuna correzione.
    correzione_storico: object | None = None
    # Il nome che questo lavoro avrebbe avuto con la vecchia etichetta unica
    # «upscale». Vale solo per il supersampling, e serve a non far risultare
    # da rifare i file gia' prodotti.
    uscita_storica: Path | None = None

    @property
    def uscite_note(self) -> tuple[Path, ...]:
        """Tutti i nomi sotto cui questo lavoro puo' gia' esistere.

        Il primo e' quello di oggi. Chi deve decidere «e' gia' fatto?» va
        confrontato con TUTTI, o un cambio di etichetta cancella la storia.
        """
        if self.uscita_storica is None:
            return (self.output,)
        return (self.output, self.uscita_storica)

    @property
    def uscita_esiste(self) -> bool:
        """Il file finale c'e' gia', con questo nome o con quello vecchio."""
        return any(p.exists() for p in self.uscite_note)

    @property
    def correzione(self) -> float:
        """Il fattore per la stima CENTRALE (1.0 senza storia)."""
        c = self.correzione_storico
        return float(c.attesa) if c is not None else 1.0

    @property
    def _correzione_tetto(self) -> float:
        """Il fattore per il TETTO: il caso peggiore gia' visto.

        Senza storia si ripiega sul margine a occhio del 25%: un tetto
        senza margine NON e' un tetto — misurato il 2026-08-10, la stima
        massima di un file dava 2h15m e la lavorazione ne impiego' 2h35m.
        """
        c = self.correzione_storico
        return float(c.massimo) if c is not None else MARGINE_PESSIMISTA

    @property
    def _correzione_pavimento(self) -> float:
        """Il fattore per il PAVIMENTO: il caso migliore già visto.

        Simmetrico del tetto. Senza di lui il pavimento coincideva con la
        stima di un giro perfetto, e la realtà può essere un po' meglio del
        modello: su ep01 il vero (5.14 h) è finito SOTTO il minimo
        dichiarato (5.24 h) — un intervallo che non contiene il vero non
        serve a niente. Senza storia resta 1.0, cioè il comportamento di
        prima: non si inventa un margine ottimista a occhio.
        """
        c = self.correzione_storico
        return float(c.minimo) if c is not None else 1.0

    def _fuori_gpu(self) -> float:
        """Tutto ciò che NON è la GPU, e che gira in sequenza con lei.

        Sono tre cose in sequenza: l'estrazione dei fotogrammi, la scansione
        che misura le differenze per la deduplica, e la codifica dei segmenti.
        Nessuna si sovrappone all'upscale — i blocchi scorrono in un ciclo
        semplice — quindi si sommano.
        """
        if not self.frames:
            return 0.0
        fattore = (self.target_width * self.target_height) / (1920 * 1080)
        # Estrazione e scansione lavorano sui fotogrammi SORGENTE: un 720p
        # ha 2,25 volte i pixel del clip da cui vengono i ritmi misurati, e
        # costa in proporzione. Prima i due numeri si applicavano tali e
        # quali a qualunque risoluzione.
        g = self.source.geometry
        peso = ((g.width * g.height) / 1_000_000
                / max(0.01, self.mpx_taratura))
        estrazione = self.frames * peso / max(1.0, self.fps_estrazione)
        misura_dedup = (self.frames * peso / max(1.0, self.fps_scansione)
                        if self.dedup.enabled else 0.0)
        codifica = self.frames * fattore / max(0.1, self.fps_codifica)
        return estrazione + misura_dedup + codifica

    def _tempo_con_dedup(self, quota: float,
                         fattore: float | None = None) -> float:
        """Quanto costerebbe il file se la deduplica risparmiasse `quota`."""
        upscalati = round(self.frames * (1 - quota))
        gpu = (self.est_gpu_seconds / max(1, self.frames_to_upscale)
               * upscalati) if self.frames_to_upscale else 0.0
        corr = self.correzione if fattore is None else fattore
        return (gpu + self._fuori_gpu()) * corr

    @property
    def dedup_incerta(self) -> bool:
        """Non sappiamo quanti fotogrammi ripetuti troveremo.

        Vero solo quando la deduplica e' accesa, c'e' una storia da cui
        pescare e nessuno ha ancora contato i fotogrammi di QUESTO file. Sta
        in un posto solo perche' i tre estremi devono decidere insieme: il
        controllo era ripetuto tre volte come `not expected_ratio`, e una
        deduplica misurata pari a zero — un file senza un solo fotogramma
        ripetuto, che esiste — e' un numero falso in Python: sarebbe tornata
        di soppiatto la mediana degli altri file al posto della misura.
        """
        return (self.dedup.enabled and self.dedup_storico is not None
                and not self.dedup.expected_ratio
                and not self.dedup.misurata)

    def _grezzo_tetto(self) -> float:
        """Il caso peggiore, SENZA nessun fattore di correzione."""
        if self.dedup_incerta:
            return self._tempo_con_dedup(self.dedup_storico.minimo, 1.0)
        # Con la deduplica misurata su questo file il risparmio e' gia'
        # dentro `est_gpu_seconds`; con la deduplica spenta non c'e'.
        return self.est_gpu_seconds + self._fuori_gpu()

    def _grezzo_pavimento(self) -> float:
        """Il caso migliore, SENZA nessun fattore di correzione."""
        # NON si passa da `dedup_incerta`: quella e' falsa anche quando la
        # storia manca del tutto, e li' il pavimento teorico dell'ultima riga
        # serve eccome. Qui la domanda e' un'altra — sappiamo gia' quanti
        # fotogrammi ripetuti ci sono? — e la risposta e' si' se li abbiamo
        # contati, se la sonda li ha previsti, o se la deduplica e' spenta.
        if (not self.dedup.enabled or self.dedup.expected_ratio
                or self.dedup.misurata):
            # Nessuna incertezza sulla deduplica: pavimento e tetto poggiano
            # sulla stessa base, e li separano solo i fattori.
            return self._grezzo_tetto()
        if self.dedup_storico is not None:
            return self._tempo_con_dedup(self.dedup_storico.massimo, 1.0)
        return self.est_gpu_seconds * (1 - DEDUP_MASSIMO) + self._fuori_gpu()

    @property
    def est_total_seconds(self) -> float:
        """Il TETTO.

        Con una storia alle spalle e' il caso PEGGIORE gia' visto su questa
        cartella; senza, resta l'ipotesi teorica "nessun fotogramma
        ripetuto" con un margine del 25%. Quel margine nasceva dal fatto
        che le velocita' erano stime a occhio: dove sono misurate (taratura)
        e la deduplica viene dai file veri, sommarlo sarebbe contarlo due
        volte — su ep02 avrebbe portato una stima di 5.40 h, giusta al 6%,
        a 6.75 h, sbagliata del 17%.
        """
        return self._grezzo_tetto() * self._correzione_tetto

    @property
    def est_attesa_seconds(self) -> float:
        """La stima su cui si scommette: la deduplica MEDIANA gia' vista.

        E' il numero da mostrare quando c'e' una storia alle spalle; la
        forchetta resta per dire quanto puo' ballare.
        """
        if self.dedup_incerta:
            return self._tempo_con_dedup(self.dedup_storico.attesa)
        # Il centro dei due casi GREZZI, poi il fattore mediano. Prima si
        # faceva la media dei due estremi gia' corretti e la si riportava
        # indietro dividendo per la media dei fattori: torna solo se i due
        # estremi poggiano sulla stessa base, e con la deduplica accesa ma
        # senza storia non e' cosi' (il pavimento toglie il 40% dei
        # fotogrammi, il tetto no). Restava dentro un residuo: fattore vero
        # 1,104 invece di 1,060 sul clip di prova, fino a +31% con una
        # forchetta larga (audit del 2026-08-10).
        return ((self._grezzo_pavimento() + self._grezzo_tetto()) / 2
                * self.correzione)

    @property
    def est_best_seconds(self) -> float:
        """Il pavimento: la deduplica trova tutto quello che può trovare.

        Con una storia alle spalle e' il caso MIGLIORE gia' visto qui;
        senza, l'estremo teorico. Si usava il valore massimo osservato in
        assoluto e non la mediana perche' con la mediana l'estremo
        ottimista veniva mancato per costruzione circa meta' delle volte
        (tre casi reali su sei finivano sotto il minimo dichiarato): un
        intervallo serve a contenere il vero, non a centrarlo.
        """
        # La deduplica MISURATA su questo file batte la storia degli altri:
        # e' il dato migliore che abbiamo, e prima veniva scartato. Quando
        # non c'e' piu' incertezza sulla deduplica (misurata, o spenta)
        # resta quella sul lavoro non contato, che ha anch'essa un minimo
        # MISURATO: prima li' si tornava il tetto tale e quale, cioe' il
        # pavimento portava il fattore del PEGGIOR caso visto, e i tre
        # numeri collassavano su uno solo (ottimo 875 s, atteso 837 s:
        # l'ordine si rompeva — misurato durante l'audit).
        return self._grezzo_pavimento() * self._correzione_pavimento

    @property
    def ivtc(self) -> bool:
        """L'inverse telecine cambia il numero di fotogrammi in uscita.

        DORMIENTE: da quando il deinterlacciamento è stato tolto (vedi
        `_build_restoration`), nessun filtro produce più `decimate`, quindi
        questa proprietà è sempre falsa. Il meccanismo resta perché è
        corretto e perché senza di esso reintrodurre l'IVTC domani
        significherebbe rifare da capo il bug che ha prodotto un video
        accelerato del 25% con l'audio fuori sincrono.
        """
        return any(f.split("=")[0] == "decimate"
                   for filtro in self.restoration.chain()
                   for f in filtro.split(","))

    def timing_args(self) -> list[str]:
        """Normalizzazione temporale, identica in ogni passata sul sorgente.

        Estrazione e misura per la deduplica DEVONO vedere lo stesso insieme
        di fotogrammi: se una delle due applica il reticolo costante e l'altra
        no, i conteggi divergono di qualche unità e la mappa punta a indici
        inesistenti.
        """
        # Con l'inverse telecine attivo NON si impone il reticolo del
        # container: `decimate` ha appena tolto un fotogramma su cinque, e
        # `-r 29.97` lo rimetterebbe duplicandolo, annullando il lavoro e
        # facendo elaborare alla GPU il 25% di fotogrammi in più.
        if self.ivtc:
            return ["-fps_mode", "passthrough"]
        return ["-fps_mode", "cfr", "-r", str(self.fps)]

    @property
    def frames_to_upscale(self) -> int:
        if not self.dedup.enabled:
            return self.frames
        return round(self.frames * (1 - self.dedup.expected_ratio))


# ===========================================================================
#  Geometria e scelta della scala
# ===========================================================================

def _target_size(
    report: SourceReport, target_height: int
) -> tuple[int, int]:
    """Dimensioni finali a pixel quadri, preservando l'aspect ratio reale.

    Si fissa l'altezza e si ricava la larghezza dal rapporto vero: così un
    4:3 resta 4:3 e un anamorfico non viene schiacciato.
    """
    g = report.geometry
    src_w, src_h = g.display_width, g.display_height

    if not src_h:
        raise PlanError(t("mot.plan.altezza_sconosciuta"))
    # Controllato QUI, dove il bersaglio entra per la prima volta: più avanti
    # `scale * src_h / target_h` divideva per zero e usciva un traceback grezzo
    # invece di un messaggio, e un bersaglio negativo produceva un piano con
    # uscita "-132x-100" senza obiezioni.
    if target_height < 64:
        raise PlanError(t("mot.plan.altezza_minima", altezza=target_height))

    height = min(target_height, src_h * 4)   # non oltre il 4x del sorgente
    width = round(src_w * height / src_h)
    return width + (width % 2), height + (height % 2)


def _choose_scale(src_h: int, target_h: int, model: Model) -> int:
    """Sceglie la scala del modello che avvicina di più il rapporto ideale.

    Upscalare oltre il bersaglio e poi ridurre non è spreco: la media dei
    pixel è un antialiasing che smorza ringing e sfarfallio del modello.
    Il caso perfetto è la riduzione esatta 2:1.

    Se NESSUNA scala arriva al bersaglio (sorgente minuscolo, o modello con
    una sola scala disponibile) si ripiega sulla PIÙ ALTA, non sulla più
    bassa: il divario che resterà da colmare con lanczos è il più piccolo
    possibile. Ripiegare sulla minima faceva produrre 1024x576 a un sorgente
    288p e poi lasciava a lanczos il salto fino a 1080p — cioè proprio
    l'interpolazione che questo strumento esiste per evitare, in silenzio.
    Chi chiama è comunque tenuto a confrontare `model_height` col bersaglio e
    ad avvisare.
    """
    best, best_score = max(model.scales), float("inf")
    for scale in sorted(model.scales):
        downscale = scale * src_h / target_h
        if downscale < 0.999:        # il modello non arriverebbe al bersaglio
            continue
        score = abs(downscale - IDEAL_DOWNSCALE)
        # A parita' di bonta', si preferisce la scala più bassa: costa meno.
        if score < best_score - 1e-9:
            best, best_score = scale, score
    return best


# ===========================================================================
#  Restauro
# ===========================================================================

def _build_restoration(
    report: SourceReport, *, denoise: bool
) -> Restoration:
    """Filtri applicati prima dell'upscale.

    Il deinterlacciamento NON c'e', deliberatamente. Due ragioni:

    - il rilevamento non sa distinguere il telecine hard dall'interlacciato
      vero (il telecine non porta i flag di campo ripetuto e finisce
      classificato "interlacciato"), e applicare la cura sbagliata DISTRUGGE
      i fotogrammi progressivi originali invece di recuperarli;
    - anche funzionando, sarebbe una versione mediocre di quello che fanno
      strumenti dedicati, con rilevatori di pettine per fotogramma e anni di
      collaudo alle spalle.

    Un sorgente interlacciato va preparato a parte, prima. Qui ci si limita a
    segnalarlo.

    Il denoise resta, ma solo a richiesta: nessuna analisi automatica decide
    al posto dell'utente se serve. La misura del rumore è stata provata e
    scartata perché instabile (vedi models.py), quindi la decisione si prende
    guardando il confronto, non fidandosi di un numero.
    """
    r = Restoration()
    fields = report.fields

    if fields and fields.mode in (FieldMode.INTERLACED, FieldMode.TELECINE):
        r.notes.append(t("mot.plan.interlacciato"))

    if denoise:
        # Conservativo: toglie il rumore di compressione senza spianare le
        # texture. Real-ESRGAN amplifica il rumore, quindi va tolto prima.
        r.denoise = "hqdn3d=1.5:1.5:6:6"
        r.notes.append(t("mot.plan.denoise"))

    return r


# ===========================================================================
#  Deduplica
# ===========================================================================

# Soglia conservativa: interviene solo su fotogrammi praticamente identici.
DEDUP_CONSERVATIVE = "hi=128:lo=64:frac=0.02"
DEDUP_STANDARD = "hi=768:lo=320:frac=0.33"


def _plan_dedup(report: SourceReport, *, enabled: bool) -> Dedup:
    if not enabled:
        return Dedup(False, "", 0.0, t("mot.plan.dedup_disattivata"))

    # PRIMA di tutto la misura su campione, quando c'e': e' l'unico numero
    # che parla di QUESTO file. Gli altri rami indovinano — o dai duplicati
    # bit-esatti (che su un encode a 10 bit il dithering azzera), o dai file
    # simili per taglia, criterio che pescava il fratello sbagliato (voce 84).
    campione = getattr(report, "dedup_campione", None)
    if campione is not None:
        return Dedup(True, DEDUP_CONSERVATIVE, campione,
                     t("mot.plan.dedup_campione", quota=f"{campione:.0%}"))

    d = report.duplicates
    if d is None:
        return Dedup(True, DEDUP_CONSERVATIVE, 0.0, t("mot.plan.dedup_all_avvio"))

    # I duplicati *esatti* sono un limite inferiore: su encode a 10 bit il
    # dithering rende ogni frame diverso al bit pur essendo identico a vedersi.
    if d.duplicate_ratio > 0.02:
        return Dedup(True, DEDUP_CONSERVATIVE, d.duplicate_ratio,
                     t("mot.plan.dedup_identici", quota=f"{d.duplicate_ratio:.0%}"))
    return Dedup(True, DEDUP_CONSERVATIVE, 0.0, t("mot.plan.dedup_nessun_esatto"))


# ===========================================================================
#  Codifica
# ===========================================================================

# I preset che x265 conosce. Senza controllo, un refuso ("slowest", "veryslower")
# arrivava fino a x265 e faceva fallire la codifica DOPO l'upscale, cioè dopo
# le ore che costa.
PRESET_VALIDI = ("ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow", "placebo")


def _build_encoding(report: SourceReport, crf: int, preset: str) -> Encoding:
    if preset not in PRESET_VALIDI:
        raise PlanError(t("mot.plan.preset_sconosciuto", preset=preset,
                          validi=", ".join(PRESET_VALIDI)))
    if not 0 <= crf <= 51:
        raise PlanError(t("mot.plan.crf_fuori_scala", crf=crf))
    # I frame passano per PNG (RGB) e perdono ogni tag: vanno riscritti
    # espliciti, altrimenti il lettore tira a indovinare lo spazio colore.
    # Sorgente che NON dichiara il colore: si applica la convenzione, cioe'
    # cio' che fa qualunque lettore e qualunque codificatore. Sotto i 720
    # di altezza il materiale e' a definizione standard e la matrice e'
    # BT.601; da li' in su e' BT.709.
    #
    # Provato a DEDURLA dai pixel (contando i colori che finiscono fuori
    # gamut decodificando con l'una e con l'altra): il metodo e' stato
    # validato sui dodici Koyomimonogatari, che dichiarano bt709, e ne ha
    # sbagliati undici su dodici, con una preferenza sistematica per il
    # 601. Misurare e' meglio che indovinare, ma una misura che non
    # riconosce nemmeno i casi noti e' peggio di una convenzione.
    predefinito = ("bt709" if (report.geometry.height or 0) >= 720
                   else "smpte170m")
    space = report.color_space or predefinito
    trc = report.color_transfer or predefinito
    prim = report.color_primaries or predefinito
    if space in ("unknown", None):
        space = trc = prim = predefinito

    # Parametri tarati per l'animazione: deblocking negativo e SAO spento
    # preservano le linee nette, aq-mode 3 protegge le campiture piatte dal
    # banding, psy-rd tiene la texture invece di spianarla.
    params = ":".join([
        f"crf={crf}",
        "aq-mode=3",
        "aq-strength=0.8",
        "psy-rd=1.5",
        "psy-rdoq=2.0",
        "rdoq-level=2",
        "deblock=-1,-1",
        "sao=0",
        "bframes=8",
        "ref=5",
        "rc-lookahead=60",
        "no-strong-intra-smoothing=1",
    ])

    # I tag colore devono stare DENTRO -x265-params, non nei flag ffmpeg.
    # Verificato: con -color_trc/-color_primaries il file esce
    # `bt709,unknown,unknown` — sopravvive solo la matrice. Mettendoli nei
    # parametri di x265 escono tutti e tre. E i due meccanismi si annullano a
    # vicenda: usandoli insieme si torna a `unknown`, quindi i flag ffmpeg si
    # tolgono del tutto.
    #
    params += (
        f":colorprim={prim}:transfer={trc}:colormatrix={space}:range=limited"
    )

    # E QUI la conversione vera. L'etichetta dice al lettore come interpretare
    # i campioni; NON dice a swscale come produrli. Senza indicazione esplicita
    # swscale converte sempre in BT.601, qualunque sia la risoluzione: il
    # risultato veniva convertito in 601 ed etichettato 709, cioè sbagliato
    # esattamente sui sorgenti HD, che sono la maggioranza.
    #
    # Misurato su barre SMPTE a 1920x1080, giro completo estrazione+codifica,
    # scostamento medio su RGB rispetto al sorgente:
    #     sorgente bt709   senza indicazione 5.45   con indicazione 1.51
    #     sorgente bt601   senza indicazione 1.27   con indicazione 4.39
    # cioè prima era giusto solo per caso, e solo per i sorgenti SD.
    matrice = _MATRICE_SWSCALE.get(space, "bt709")

    return Encoding(
        codec="libx265",
        pix_fmt="yuv420p10le",
        crf=crf,
        preset=preset,
        params=params,
        color_args=[],
        swscale_matrix=matrice,
        color_tags=(prim, trc, space),
    )


# I nomi che usa ffprobe per lo spazio colore non coincidono sempre con quelli
# che accetta swscale in `out_color_matrix`.
_MATRICE_SWSCALE = {
    "bt709": "bt709",
    "bt470bg": "bt601",
    "smpte170m": "bt601",
    "smpte240m": "smpte240m",
    "bt601": "bt601",
    "fcc": "fcc",
    "bt2020nc": "bt2020",
    "bt2020_ncl": "bt2020",
    "bt2020c": "bt2020",
}


# ===========================================================================
#  Composizione del piano
# ===========================================================================

def dimensiona_blocchi(frames: int, up_mb: float, disponibile: float,
                      margine: float) -> int:
    """Quanti fotogrammi mettere in un blocco. Funzione PURA, per i test.

    Stava dentro `build_plan`, e il test la riscriveva per poterla provare:
    mutando il codice vero il test non cadeva, cioe' sorvegliava una copia
    invece del codice spedito (trovato in audit, ed e' la stessa classe di
    difetto gia' vista in tre test la mattina dell'11/08). Estratta qui, la
    prova e la produzione eseguono le stesse righe.

    `disponibile` e' cio' che resta del TETTO CHIESTO dopo i fotogrammi
    sorgente e il video; `margine` e' cio' che resta dello spazio FISICO.
    Quando il primo e' negativo — il tetto non e' onorabile — comanda il
    secondo: si sforera' comunque, e l'avviso lo dice, ma spezzettare non
    recupera un giga perche' il picco lo fanno i sorgenti.

    Tre limiti e vince il piu' stretto, piu' un pavimento:
      - lo SPAZIO che avanza;
      - il TETTO PER BLOCCO, che pero' si allarga se rispettarlo
        costringerebbe a piu' di `BLOCCHI_MASSIMI` blocchi e la capienza
        c'e' (senza, un film 4K di due ore usciva in 59 blocchi e uno di tre
        ore in 88, col disco mezzo vuoto: 68 e 102 minuti di solo costo
        fisso);
      - almeno `BLOCCHI_MINIMI` blocchi, perche' un blocco e' atomico e un
        blackout non deve portarsi via mezzo file;
      - mai sotto `BLOCCO_MINIMO_FOTOGRAMMI`, sotto cui il minuto fisso pesa
        piu' del lavoro contenuto.
    """
    if not up_mb or not frames:
        return 2000
    da_tetto = int(TETTO_BLOCCO_GB * 1024 / up_mb)
    capienza = disponibile if disponibile > 0 else margine
    ideale = -(-frames // BLOCCHI_MASSIMI)
    if ideale > da_tetto and ideale * up_mb / 1024 <= capienza:
        da_tetto = ideale
    da_spazio = int(max(disponibile, 0) * 1024 / up_mb)
    if da_spazio < ideale:
        # Rispettare il tetto costerebbe piu' blocchi di quanti ne valga la
        # pena. Senza questa riga, dedicare PIU' spazio poteva produrre PIU'
        # blocchi: su un episodio misurato, 10 GB davano 12 blocchi e 40 GB
        # ne davano 44.
        da_spazio = min(da_tetto, ideale)
    cs = min(da_spazio, da_tetto, -(-frames // BLOCCHI_MINIMI))
    return min(max(cs, BLOCCO_MINIMO_FOTOGRAMMI), frames)


def build_plan(
    report: SourceReport,
    *,
    target_height: int = DEFAULT_TARGET_HEIGHT,
    crf: int = 18,
    preset: str = "slower",
    denoise: bool = False,
    dedup: bool = True,
    forza: bool = False,
    peak_disk_gb: float = DEFAULT_PEAK_DISK_GB,
    scale_override: int | None = None,
    model_key: str | None = None,
    paths: Paths | None = None,
    dedup_nota: float | None = None,
) -> Plan:
    """Costruisce il piano di lavorazione per un sorgente già analizzato.

    Senza `model_key` si adotta il modello consigliato per la risoluzione del
    sorgente, ma la raccomandazione resta visibile nel piano insieme al motivo.

    `dedup_nota` è la deduplica MISURATA su questo preciso file, quando la si
    conosce già (`monitor.dedup_esatta`, disponibile pochi minuti dopo la
    partenza). Con quella in mano non si stima più niente sulla deduplica: il
    pavimento e il tetto si stringono su un solo numero e resta la sola
    incertezza del modello, che sulle pagelle del 12/08 vale l'1,7% in media
    e non ha mai superato il 3,2%.
    """
    p = paths or PATHS
    g = report.geometry

    target_w, target_h = _target_size(report, target_height)
    src_w, src_h = g.width, g.height

    # Questo strumento fa UPSCALE. Se il sorgente è già alla dimensione
    # richiesta o più grande, non c'e' niente da fare: ridimensionare verso il
    # basso non è il suo mestiere, e ricomprimere per arrivare alla stessa
    # dimensione è una perdita generazionale in cambio di nulla.
    disp_h = g.display_height
    disp_w = round(g.display_width)
    restoration = _build_restoration(report, denoise=denoise)

    guadagno = target_h / disp_h if disp_h else 0.0
    if guadagno < GUADAGNO_MINIMO and not forza:
        if disp_h >= target_h:
            bersaglio = f"{target_w}x{target_h}"
            if disp_h == target_h:
                motivo = t("mot.plan.gia_uguale", larghezza=disp_w,
                           altezza=disp_h, bersaglio=bersaglio)
            else:
                motivo = t("mot.plan.gia_piu_grande", larghezza=disp_w,
                           altezza=disp_h, bersaglio=bersaglio)
        else:
            motivo = t("mot.plan.guadagno_piccolo",
                       da=f"{disp_w}x{disp_h}", a=f"{target_w}x{target_h}",
                       guadagno=f"{guadagno:.2f}", soglia=GUADAGNO_MINIMO)
        raise PlanError(
            t("mot.plan.niente_da_fare", motivo=motivo),
            t("mot.plan.sintesi_troppo_piccolo"),
        )


    suggestion = recommend(src_h)
    chosen = model_key or suggestion.model
    if chosen not in CATALOG:
        raise PlanError(t("mot.plan.modello_sconosciuto", modello=chosen,
                          disponibili=", ".join(CATALOG)))
    model = CATALOG[chosen]

    scale = scale_override or _choose_scale(src_h, target_h, model)
    if scale not in model.scales:
        raise PlanError(
            t("mot.plan.scala_non_supportata", modello=model.label, scala=scale,
              disponibili=", ".join(str(s) for s in model.scales)),
            t("mot.plan.sintesi_scala"),
        )

    model_w, model_h = src_w * scale, src_h * scale
    downscale = model_h / target_h if target_h else 1.0

    dedup_plan = _plan_dedup(report, enabled=dedup)
    encoding = _build_encoding(report, crf, preset)

    # Ripiego a scalare: misurato -> dichiarato dal container -> 23.976.
    # Prima si saltava dritti a 23.976, e su un sorgente PAL il reticolo
    # costante buttava via 60 fotogrammi al minuto senza dirlo.
    fps = (report.timing.fps or report.timing.container_r_fps
           or report.timing.container_avg_fps or Fraction(24000, 1001))
    frames = report.timing.packets + report.timing.missing_frames

    # L'inverse telecine toglie un fotogramma su cinque: se fps e conteggio
    # restassero quelli del contenitore, i 4/5 dei fotogrammi verrebbero
    # codificati al framerate pieno e il video uscirebbe accelerato del 25%,
    # con l'audio del sorgente rimontato invariato. Su un episodio da 24
    # minuti sono quasi cinque minuti di scarto.
    if any(f.split("=")[0] == "decimate"
           for filtro in restoration.chain() for f in filtro.split(",")):
        fps = fps * Fraction(4, 5)
        frames = round(frames * 4 / 5)

    # --- dimensionamento dei blocchi in base allo spazio disponibile ---
    src_mb = src_w * src_h * BYTES_PER_PIXEL_SOURCE / 1_048_576
    up_mb = model_w * model_h * BYTES_PER_PIXEL_UPSCALED / 1_048_576


    # I fotogrammi SORGENTE si estraggono tutti in una volta e restano su
    # disco per l'intera lavorazione: pesano quanto l'episodio, non quanto un
    # blocco. Solo gli upscalati sono a blocchi. Contarli entrambi come "per
    # blocco" faceva dichiarare 40 GB di picco quando sul disco ce n'erano 56.
    sorgenti_gb = frames * src_mb / 1024 if frames else 0.0

    # I segmenti codificati si accumulano in `segments/` fino all'assemblaggio
    # e il file finale nasce in OUTPUT/, sullo stesso volume: al picco ci sono
    # entrambi, cioè due volte il video finito.
    durata = report.duration or (float(frames / fps) if frames and fps else 0.0)
    bitrate_mbps = EST_BITRATE_MBPS_1080P * (target_w * target_h) / (1920 * 1080)
    uscita_gb = bitrate_mbps * durata / 8 / 1024 if durata else 0.0
    video_gb = 2 * uscita_gb

    free_gb = shutil.disk_usage(p.root).free / 1_073_741_824

    # --- LO SPAZIO SI SPENDE IN ORDINE, e l'ordine non e' negoziabile ---
    #
    # `peak_disk_gb` e' il TETTO COMPLESSIVO che l'utente dedica a questo
    # file, non la dimensione di un blocco. Prima si pagano i fotogrammi
    # sorgente (estratti tutti insieme, restano per tutta la lavorazione) e i
    # segmenti piu' il file finale; solo quello che avanza puo' andare ai
    # blocchi.
    #
    # Prima non era cosi': il numero chiesto all'utente governava i soli
    # fotogrammi ingranditi, e con 40 GB impostati il picco vero era 40 GB su
    # un episodio (per coincidenza), 165 su un film da due ore, 359 a 1080p.
    # E quando i sorgenti si mangiavano il bilancio, il blocco crollava in
    # silenzio al minimo di sicurezza: 146 blocchi senza che nessuno lo
    # dicesse.
    incomprimibile = sorgenti_gb + video_gb
    # Il disco non si riempie fino all'orlo nemmeno se l'utente lo chiede:
    # sotto una certa soglia macOS stesso comincia a soffrire.
    disponibile = min(float(peak_disk_gb), free_gb * 0.85) - incomprimibile

    chunk_size = dimensiona_blocchi(
        frames, up_mb, disponibile, free_gb * 0.85 - incomprimibile)
    chunks = max(1, -(-frames // chunk_size)) if frames else 1

    # La misura sul file vero scavalca qualunque previsione: la sonda che
    # decide `expected_ratio` conta i fotogrammi identici al bit e su questo
    # materiale ne trova meno del 2%, mentre la deduplica vera — che lavora a
    # soglia, non a uguaglianza esatta — ne toglie un terzo.
    #
    # Ma solo se la mappa parla di QUESTO file. La cartella di lavoro non
    # dipende dai parametri: cambiare bersaglio o accendere il denoise
    # riusa la stessa cartella, e la mappa che c'e' dentro e' stata misurata
    # su un'ALTRA estrazione. Quando i fotogrammi non coincidono la si
    # scarta e si torna allo storico, che almeno non finge di aver contato.
    quanti_nota = None
    if isinstance(dedup_nota, tuple):
        dedup_nota, quanti_nota = dedup_nota
    if (quanti_nota is not None and frames
            and abs(int(quanti_nota) - frames) > max(2, frames * 0.01)):
        dedup_nota = None
    if (dedup_plan.enabled and dedup_nota is not None
            and 0 <= float(dedup_nota) < 1):
        dedup_plan = Dedup(
            enabled=True, threshold=dedup_plan.threshold,
            expected_ratio=float(dedup_nota),
            reason=t("mot.plan.dedup_misurata", quota=f"{float(dedup_nota):.0%}"),
            misurata=True,
        )

    # --- stima dei tempi ---
    upscale_frames = (
        round(frames * (1 - dedup_plan.expected_ratio))
        if dedup_plan.enabled else frames
    )
    src_mpx = src_w * src_h / 1_000_000
    # La taratura di questa macchina, se esiste, vince sui numeri di
    # fabbrica del catalogo (che sono misure di UN Mac specifico).
    misurato = taratura.throughput(chosen, scale, paths=p)
    throughput = misurato or model.throughput.get(
        scale, min(model.throughput.values()))
    voce_taratura = taratura.carica(p)
    est_gpu = upscale_frames * src_mpx / throughput

    warnings: list[str] = []
    if target_h < target_height:
        # Il limite del 4x abbassava il bersaglio senza dirlo: chi chiedeva
        # 1080p da un 240p si ritrovava 960p e lo scopriva solo leggendo il
        # nome del file.
        warnings.append(t("mot.plan.bersaglio_abbassato", chiesto=target_height,
                          ottenuto=target_h, sorgente=f"{src_w}x{src_h}"))
    if model_h < target_h:
        # Il divario lo colmerebbe lanczos in fase di codifica: interpolazione
        # pura, cioè esattamente ciò che si stanno pagando ore di GPU per
        # evitare, e per giunta in silenzio. Ci si ferma, come per la soglia di
        # ingrandimento minimo, perché il rimedio esiste sempre: un altro
        # modello, oppure un bersaglio più basso.
        # Con la scala FORZATA a mano, cambiare modello non serve a niente: il
        # limite lo ha imposto chi ha scritto `--scala`. Suggerire un altro
        # modello sarebbe un'istruzione sbagliata, e le istruzioni sbagliate
        # costano più del silenzio.
        if scale_override:
            rimedio = t("mot.plan.rimedio_scala_forzata", scala=scale_override,
                        altezza=model_h)
        else:
            alternative = sorted(
                k for k, m in CATALOG.items()
                if k != chosen and src_h * max(m.scales) >= target_h
            )
            rimedio = (
                t("mot.plan.rimedio_scegli", modelli=t("mot.plan.o").join(
                    CATALOG[k].short for k in alternative))
                if alternative else
                t("mot.plan.rimedio_nessuno", sorgente=f"{src_w}x{src_h}",
                  altezza=model_h)
            )
        messaggio = t("mot.plan.non_arriva", modello=model.label,
                      massimo=f"{model_w}x{model_h}",
                      bersaglio=f"{target_w}x{target_h}", rimedio=rimedio)
        if not forza:
            raise PlanError(messaggio, t("mot.plan.sintesi_non_arriva",
                                         altezza=target_h))
        warnings.append(t("mot.plan.forzato", messaggio=messaggio))
    if forza and guadagno < GUADAGNO_MINIMO:
        warnings.append(t("mot.plan.forzato_guadagno",
                          guadagno=f"{guadagno:.2f}", soglia=GUADAGNO_MINIMO))
    if report.timing.mode is Timebase.VFR:
        warnings.append(t("mot.plan.vfr", fps=f"{float(fps):.3f}"))
    if "mov_text" in report.subtitle_codecs:
        warnings.append(t("mot.plan.mov_text"))
    if free_gb < 60:
        warnings.append(t("mot.plan.spazio_ridotto", liberi=f"{free_gb:.0f}"))
    # Lo spazio dedicato non basta nemmeno per cio' che NON si puo' spezzare.
    # Va detto qui, prima di partire, con il numero che serve: e' l'unico modo
    # per non ritrovarsi a scoprirlo con il disco pieno a meta' coda. Prima
    # l'app ripiegava in silenzio su blocchi minuscoli e andava avanti lo
    # stesso, sforando di quattro o nove volte lo spazio chiesto.
    if incomprimibile > float(peak_disk_gb):
        warnings.append(t(
            "mot.plan.spazio_insufficiente", servono=f"{incomprimibile:.0f}",
            dedicati=f"{float(peak_disk_gb):.0f}",
            picco=f"{sorgenti_gb + video_gb + chunk_size * up_mb / 1024:.0f}"))
    elif disponibile < TETTO_BLOCCO_GB and chunks > BLOCCHI_MINIMI:
        warnings.append(t("mot.plan.spazio_stretto",
                          restano=f"{max(disponibile, 0):.0f}", blocchi=chunks))

    # «upscale» solo se il bersaglio e' PIU' ALTO del sorgente. A parita' di
    # altezza (o sotto, col forza) il modello ingrandisce e poi si riduce:
    # e' supersampling, non upscale — e chiamarlo upscale nel nome del file
    # e' semplicemente falso (fatto notare dall'utente il 12/08 guardando
    # «Monogatari S06E02 [1080p] ... [upscale 1080p ...]»).
    etichetta = "upscale" if target_h > disp_h else "supersampling"
    voci = dict(target_height=target_h, scale=scale, model_tag=chosen,
                crf=crf, denoise=denoise, dedup=dedup_plan.enabled,
                preset=preset)
    name = output_name(report.path.stem, etichetta=etichetta, **voci)
    # Il nome che lo STESSO lavoro avrebbe avuto prima di questa distinzione.
    # Serve solo a riconoscere le uscite gia' prodotte: senza, un file finito
    # ieri risulterebbe da rifare — dieci ore buttate per una parola.
    nome_storico = (output_name(report.path.stem, etichetta="upscale", **voci)
                    if etichetta != "upscale" else None)
    return Plan(
        source=report,
        output=p.output / f"{name}.mkv",
        uscita_storica=(p.output / f"{nome_storico}.mkv"
                        if nome_storico else None),
        log=p.logs / f"{name}.log",
        target_width=target_w,
        target_height=target_h,
        model=model,
        model_key=chosen,
        model_scale=scale,
        model_name=model.model_name(scale),
        model_width=model_w,
        model_height=model_h,
        downscale=downscale,
        restoration=restoration,
        dedup=dedup_plan,
        encoding=encoding,
        fps=fps,
        frames=frames,
        chunk_size=chunk_size,
        chunks=chunks,
        est_gpu_seconds=est_gpu,
        est_peak_disk_gb=sorgenti_gb + video_gb + chunk_size * up_mb / 1024,
        recommendation=suggestion,
        warnings=warnings,
        fps_estrazione=float((voce_taratura or {}).get("estrazione_fps")
                             or 60.0),
        fps_codifica=float((voce_taratura or {}).get("codifica_fps")
                           or FPS_CODIFICA),
        fps_scansione=float((voce_taratura or {}).get("scansione_fps")
                            or 200.0),
        mpx_taratura=float((voce_taratura or {}).get("mpx_misura")
                           or MPX_TARATURA),
        stime_tarate=misurato is not None,
        # Serve solo a chi la deduplica la fa davvero: senza, la forchetta
        # resterebbe quella teorica anche avendo la storia. `simili_a` tiene
        # fuori i file che durano tutt'altro: e' li' che lo storico sbaglia
        # forte (vedi `storico._somiglia`).
        dedup_storico=(storico.deduplica(p, simili_a=frames)
                       if dedup_plan.enabled else None),
        correzione_storico=storico.correzione(p, simili_a=frames),
    )
