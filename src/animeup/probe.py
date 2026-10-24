"""Analisi del sorgente.

Obiettivo: capire *davvero* cosa contiene il file prima di toccarlo, e dirlo
in modo comprensibile e correggibile a mano.

Principi che questo modulo applica, e che la vecchia v5 sbagliava:

1. I tempi si analizzano in **tick interi di timebase**, mai in virgola mobile.
   Matroska memorizza i timestamp al millisecondo: a 23.976 fps l'intervallo
   reale è 41.708 ms e i timestamp oscillano fra 41 e 42 ms. Qualunque misura
   di "variazione" fatta in secondi vede quell'oscillazione come VFR, sempre,
   su ogni file CFR. È un falso positivo garantito, non occasionale.

2. Il framerate non si indovina da una tabella di valori plausibili: si ricava
   dalla media sull'intero span di timestamp e si aggancia a un valore standard
   solo se l'errore relativo è trascurabile.

3. VFR vero, frame mancanti e telecine sono tre patologie diverse con tre cure
   diverse. Vanno distinte, non accomunate.

4. Il sorgente non si ricomprime MAI per "sistemare" i tempi.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from pathlib import Path

from .ffmpeg import FFprobe, run_stderr
from .i18n import t
from .paths import PATHS, Paths

# --- framerate standard, per l'aggancio ------------------------------------
STANDARD_FPS: tuple[Fraction, ...] = (
    Fraction(24000, 1001),   # 23.976
    Fraction(24, 1),
    Fraction(25, 1),
    Fraction(30000, 1001),   # 29.97
    Fraction(30, 1),
    Fraction(48, 1),
    Fraction(50, 1),
    Fraction(60000, 1001),   # 59.94
    Fraction(60, 1),
    Fraction(12, 1),         # animazione "in due" già decimata
    Fraction(15, 1),
    Fraction(16, 1),
)

# Tolleranza per agganciare a un fps standard: 0.1% di errore relativo.
FPS_SNAP_TOLERANCE = 0.001


class Timebase(str, Enum):
    """Verdetto sul ritmo dei frame."""

    CFR = "cfr"
    """Costante. Include il caso quantizzato al millisecondo dei Matroska."""

    CFR_WITH_GAPS = "cfr_con_buchi"
    """Costante, ma con frame mancanti: i buchi sono multipli esatti del passo."""

    VFR = "vfr"
    """Variabile davvero: il passo cambia in modo non riconducibile a un reticolo."""

    UNKNOWN = "sconosciuto"


class FieldMode(str, Enum):
    PROGRESSIVE = "progressivo"
    INTERLACED = "interlacciato"
    TELECINE = "telecine"
    UNKNOWN = "sconosciuto"


@dataclass
class TimingReport:
    """Analisi dei tempi, ricavata dai soli pacchetti (nessuna decodifica)."""

    mode: Timebase
    fps: Fraction | None
    fps_is_standard: bool
    packets: int
    time_base: Fraction
    dominant_delta: int | None          # tick
    jitter_ticks: int                   # max_delta - min_delta fra i delta "normali"
    quantization_only: bool             # il jitter è spiegato dalla risoluzione del timebase
    gaps: int                           # buchi (delta multipli del passo)
    missing_frames: int                 # frame mancanti stimati dai buchi
    outliers: list[tuple[int, int]] = field(default_factory=list)  # (indice, delta)
    container_r_fps: Fraction | None = None
    container_avg_fps: Fraction | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def container_disagrees(self) -> bool:
        """Il framerate dichiarato dal container è incompatibile col misurato."""
        if self.fps is None or self.container_r_fps is None:
            return False
        return abs(float(self.container_r_fps) - float(self.fps)) / float(self.fps) > 0.005


@dataclass
class FieldReport:
    mode: FieldMode
    progressive: int
    tff: int
    bff: int
    undetermined: int
    repeated_fields: int
    total: int
    confidence: float

    @property
    def interlaced_ratio(self) -> float:
        return (self.tff + self.bff) / self.total if self.total else 0.0


@dataclass
class GeometryReport:
    width: int
    height: int
    sar: Fraction              # sample aspect ratio (pixel aspect)
    dar: Fraction              # display aspect ratio
    display_width: int         # larghezza a pixel quadri
    display_height: int

    @property
    def anamorphic(self) -> bool:
        return self.sar != 1


@dataclass
class DuplicateReport:
    total_frames: int
    unique_frames: int
    consecutive_duplicates: int
    run_lengths: Counter[int]

    @property
    def duplicate_ratio(self) -> float:
        return self.consecutive_duplicates / self.total_frames if self.total_frames else 0.0

    @property
    def gpu_saving(self) -> float:
        """Frazione di lavoro GPU risparmiabile deduplicando."""
        return self.duplicate_ratio

    @property
    def animation_step(self) -> int | None:
        """Passo dominante dell'animazione: 1 = "in uno", 2 = "in due", 3 = "in tre"."""
        if not self.run_lengths:
            return None
        step, _ = self.run_lengths.most_common(1)[0]
        return step


@dataclass
class SourceReport:
    path: Path
    container: str
    duration: float
    video_codec: str
    pix_fmt: str
    bit_depth: int
    color_space: str | None
    color_transfer: str | None
    color_primaries: str | None
    audio_tracks: int
    subtitle_tracks: int
    subtitle_codecs: list[str]
    chapters: int
    geometry: GeometryReport
    timing: TimingReport
    fields: FieldReport | None = None
    duplicates: DuplicateReport | None = None
    # Deduplica attesa, MISURATA su un campione di questo file (vedi
    # `dedup.stima_campionata`). None = non misurata. Prima si indovinava
    # accostando i file per numero di fotogrammi, e il criterio pescava il
    # fratello sbagliato: quasi quattro ore di errore su una stima di
    # tredici (voce 84).
    dedup_campione: float | None = None

    @property
    def frames(self) -> int:
        return self.timing.packets

    def warnings(self) -> list[str]:
        """Problemi che meritano l'attenzione dell'utente prima di partire."""
        out: list[str] = []
        # `tempi` e non `t`: `t` e' la funzione dei testi tradotti.
        tempi = self.timing
        # File troncato: il contenitore dichiara una durata ma i pacchetti
        # video finiscono molto prima. Capita coi download interrotti, e senza
        # questo avviso si scopriva DOPO ore di GPU che l'episodio si ferma a
        # metà. Soglia al 2% (e mai sotto i 2 secondi): i contenitori
        # arrotondano la durata e un piccolo scarto è fisiologico.
        if tempi.fps and self.duration > 0 and tempi.packets:
            attesi = self.duration * float(tempi.fps)
            if tempi.packets < attesi - max(2 * float(tempi.fps), attesi * 0.02):
                mancano = self.duration - tempi.packets / float(tempi.fps)
                out.append(t("probe.troncato", dichiarata=f"{self.duration:.0f}",
                             mancano=f"{mancano:.0f}"))
        if tempi.mode is Timebase.VFR:
            out.append(t("probe.vfr"))
        if tempi.mode is Timebase.CFR_WITH_GAPS:
            out.append(t("probe.buchi", mancanti=tempi.missing_frames,
                         buchi=tempi.gaps))
        if tempi.container_disagrees:
            out.append(t("probe.container_discorde",
                         dichiarato=_fps_str(tempi.container_r_fps),
                         misurato=_fps_str(tempi.fps)))
        if not tempi.fps_is_standard and tempi.fps is not None:
            out.append(t("probe.fps_non_standard", fps=_fps_str(tempi.fps)))
        if self.fields and self.fields.mode is FieldMode.INTERLACED:
            out.append(t("probe.interlacciato"))
        if self.fields and self.fields.mode is FieldMode.TELECINE:
            out.append(t("probe.telecine"))
        if self.geometry.anamorphic:
            out.append(t("probe.anamorfico", sar=self.geometry.sar,
                         larghezza=self.geometry.display_width,
                         altezza=self.geometry.display_height))
        if self.subtitle_codecs and any(c == "mov_text" for c in self.subtitle_codecs):
            out.append(t("probe.mov_text"))
        if not self.geometry.width or not self.geometry.height:
            out.append(t("probe.no_video"))
        if self.color_space in (None, "unknown"):
            # L'avviso valeva solo sopra i 720, cioe' proprio dove
            # l'assunzione e' certa; taceva sugli SD, dove invece era
            # sbagliata. Ora dice sempre cosa si e' assunto e perche'.
            hd = self.geometry.height >= 720
            out.append(t("probe.colore_hd" if hd else "probe.colore_sd"))
        return out


# ===========================================================================
#  Analisi dei tempi
# ===========================================================================

def analyze_timing(path: Path, meta: dict, paths: Paths | None = None) -> TimingReport:
    """Classifica il ritmo dei frame leggendo i soli pacchetti video.

    Nessuna decodifica: su un episodio di 24 minuti costa qualche secondo.
    """
    probe = FFprobe(paths or PATHS)
    stream = _video_stream(meta)
    time_base = _fraction(stream.get("time_base")) or Fraction(1, 1000)

    pts_list: list[int] = []
    for pts, _dur in probe.video_packets(path):
        if pts is not None:
            pts_list.append(pts)

    notes: list[str] = []
    if len(pts_list) < 3:
        return TimingReport(
            mode=Timebase.UNKNOWN, fps=None, fps_is_standard=False,
            packets=len(pts_list), time_base=time_base, dominant_delta=None,
            jitter_ticks=0, quantization_only=False, gaps=0, missing_frames=0,
            notes=["Troppi pochi pacchetti per analizzare i tempi."],
        )

    # I pacchetti arrivano in ordine di decodifica: con i B-frame i PTS non sono
    # monotoni. Ordinare è obbligatorio, ed è esattamente il passaggio che
    # mancava nella v5 (da lì venivano le "variazioni" del 100%).
    pts_list.sort()
    deltas = [b - a for a, b in zip(pts_list, pts_list[1:]) if b > a]
    if not deltas:
        return TimingReport(
            mode=Timebase.UNKNOWN, fps=None, fps_is_standard=False,
            packets=len(pts_list), time_base=time_base, dominant_delta=None,
            jitter_ticks=0, quantization_only=False, gaps=0, missing_frames=0,
            notes=["Timestamp tutti identici: container corrotto o senza tempi."],
        )

    hist = Counter(deltas)
    dominant, dominant_count = hist.most_common(1)[0]

    # Un tick è l'unita' minima rappresentabile: se il jitter sta dentro un
    # tick, non è VFR, è solo la risoluzione del container.
    # Matroska usa 1/1000 -> a 23.976 i delta legittimi sono 41 e 42.
    #
    # Ma un tick NON vale sempre uguale. Su Matroska il passo dominante è ~42
    # tick e uno vale il 2%; su AVI il time_base È 1/fps, quindi il passo
    # dominante è 1 tick e la tolleranza copre il 100%: un delta di 2 — cioè
    # un fotogramma MANCANTE — finiva fra i "normali", non veniva contato, e
    # l'fps medio usciva sbagliato. Misurato su un AVI con un solo fotogramma
    # perso: 23.876 invece di 23.976, con l'avviso "probabile rip impreciso"
    # su un rip che era pulito. La tolleranza si concede solo quando c'e'
    # davvero qualcosa da quantizzare.
    tolleranza = 1 if dominant >= 8 else 0
    normal = {d for d in hist if abs(d - dominant) <= tolleranza}
    normal_count = sum(hist[d] for d in normal)

    # Buchi: delta che sono multipli quasi esatti del passo dominante.
    # Un buco proprio in testa o in coda al file non è un rip difettoso: è il
    # taglio del clip, o la durata di visualizzazione dell'ultimo frame.
    # Un margine proporzionale alla durata diventava assurdo: su un episodio
    # da 24 minuti tollerava 14 secondi di buchi per lato. Il taglio di un
    # clip riguarda pochi fotogrammi, non una percentuale.
    edge = 2
    gaps = 0
    missing = 0          # solo buchi interni: è ciò che segnala un rip difettoso
    missing_all = 0      # tutti i buchi: serve al calcolo dell'fps, perché lo
                         # span temporale contiene comunque quei frame
    edge_gaps = 0
    outliers: list[tuple[int, int]] = []
    for idx, d in enumerate(deltas):
        if d in normal:
            continue
        ratio = d / dominant
        nearest = round(ratio)
        if nearest >= 2 and abs(ratio - nearest) < 0.15:
            missing_all += nearest - 1
            if idx < edge or idx >= len(deltas) - edge:
                edge_gaps += 1
            else:
                gaps += 1
                missing += nearest - 1
        else:
            if len(outliers) < 20:
                outliers.append((idx, d))

    total = len(deltas)
    normal_ratio = normal_count / total
    jitter = (max(normal) - min(normal)) if normal else 0
    quantization_only = jitter <= 1

    # --- framerate: dalla media sull'intero span, non da un singolo delta ---
    span = pts_list[-1] - pts_list[0]
    steps = len(pts_list) - 1 + missing_all      # i buchi contano come passi
    fps: Fraction | None = None
    if span > 0 and steps > 0:
        seconds = span * float(time_base)
        measured = steps / seconds
        fps, is_standard = _snap_fps(measured)
    else:
        is_standard = False

    # --- verdetto ---
    if normal_ratio >= 0.999 and not outliers:
        mode = Timebase.CFR
    elif normal_ratio >= 0.98 and gaps and not outliers:
        mode = Timebase.CFR_WITH_GAPS
    elif normal_ratio >= 0.95:
        mode = Timebase.CFR_WITH_GAPS if gaps else Timebase.CFR
        notes.append(
            f"{total - normal_count} intervalli fuori norma su {total}: "
            "troppo pochi per considerare il file a ritmo variabile."
        )
    else:
        mode = Timebase.VFR
        top = hist.most_common(4)
        notes.append(
            "Distribuzione degli intervalli: "
            + ", ".join(f"{d} tick x{c}" for d, c in top)
        )

    if quantization_only and mode is Timebase.CFR:
        notes.append(
            "Le piccole differenze fra i tempi dei fotogrammi sono "
            "l'arrotondamento del contenitore "
            f"({_fps_str(Fraction(1) / time_base)} tick al secondo), non un "
            "ritmo davvero variabile."
        )
    if edge_gaps:
        notes.append(
            "Il primo o l'ultimo fotogramma dura più degli altri: è il "
            "taglio del clip, non un difetto. Ignorato."
        )

    return TimingReport(
        mode=mode,
        fps=fps,
        fps_is_standard=is_standard,
        packets=len(pts_list),
        time_base=time_base,
        dominant_delta=dominant,
        jitter_ticks=jitter,
        quantization_only=quantization_only,
        gaps=gaps,
        missing_frames=missing,
        outliers=outliers,
        container_r_fps=_fraction(stream.get("r_frame_rate")),
        container_avg_fps=_fraction(stream.get("avg_frame_rate")),
        notes=notes,
    )


def _snap_fps(measured: float) -> tuple[Fraction, bool]:
    """Aggancia a un framerate standard se l'errore relativo è trascurabile."""
    best: Fraction | None = None
    best_err = float("inf")
    for candidate in STANDARD_FPS:
        err = abs(float(candidate) - measured) / measured
        if err < best_err:
            best_err, best = err, candidate
    if best is not None and best_err <= FPS_SNAP_TOLERANCE:
        return best, True
    return Fraction(measured).limit_denominator(100000), False


# ===========================================================================
#  Analisi dei campi (interlacciamento / telecine)
# ===========================================================================

_IDET_SINGLE = re.compile(
    r"Single frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*"
    r"Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
)
_IDET_MULTI = re.compile(
    r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*"
    r"Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
)
_IDET_REPEAT = re.compile(
    r"Repeated Fields:\s*Neither:\s*(\d+)\s*Top:\s*(\d+)\s*Bottom:\s*(\d+)"
)


def scan_full(path: Path, paths: Paths | None = None) -> str:
    """Una sola passata completa sul file con i filtri di analisi.

    Campionare qualche punto era una scommessa statistica su decisioni
    irreversibili: una scena a fondo nero bastava a far credere che metà
    fotogramma fosse banda da tagliare. Una scansione integrale di un episodio
    costa una quindicina di secondi contro le ore della lavorazione, quindi
    non c'e' nessuna ragione per indovinare invece di guardare.
    """
    p = paths or PATHS
    cmd = [
        str(p.ffmpeg.path), "-hide_banner", "-v", "info", "-i", str(path),
        # `limit` come FRAZIONE, non come numero assoluto: espresso in numero
        # intero è nella scala di campionamento del sorgente, quindi a 8 bit
        # il nero sta a 16 e passa la soglia 24, ma a 10 bit sta a 64 e non la
        # supera mai. Le bande nere non venivano viste su nessun sorgente a 10
        # bit, cioè su tutti gli encode anime moderni. Con la frazione ffmpeg
        # riscala da solo sulla profondita' reale: verificato, stesso identico
        # riquadro sullo stesso contenuto a 8 e a 10 bit.
        "-vf", "idet",
        "-an", "-sn", "-f", "null", "-",
    ]
    # Un tetto c'e', ed è larghissimo: la scansione completa di un
    # episodio da 24 minuti costa una quindicina di secondi.
    return run_stderr(cmd, timeout=3600)


def parse_fields(stderr: str) -> FieldReport:
    """Referto sui campi a partire dall'output di idet."""
    tff = bff = prog = undet = repeated = 0

    # ffmpeg istanzia il filtro più volte quando il grafo si riconfigura e
    # stampa un referto per ciascuna istanza; la prima è azzerata. Vale
    # l'ultimo blocco, che è quello dell'istanza che ha fatto il lavoro.
    if found := (_IDET_MULTI.findall(stderr) or _IDET_SINGLE.findall(stderr)):
        a, b, c, d = found[-1]
        tff, bff, prog, undet = int(a), int(b), int(c), int(d)
    if found := _IDET_REPEAT.findall(stderr):
        _neither, top, bottom = found[-1]
        repeated = int(top) + int(bottom)

    total = tff + bff + prog + undet
    if not total:
        return FieldReport(FieldMode.UNKNOWN, 0, 0, 0, 0, 0, 0, 0.0)

    interlaced_ratio = (tff + bff) / total
    repeat_ratio = repeated / total

    # Telecine 3:2: un quinto dei frame porta il flag di campo ripetuto, e una
    # parte dei frame risulta interlacciata perché mescola due fotogrammi.
    if repeat_ratio > 0.10 or (0.15 < interlaced_ratio < 0.65 and repeat_ratio > 0.03):
        mode = FieldMode.TELECINE
        confidence = min(1.0, max(repeat_ratio * 4, interlaced_ratio * 1.5))
    elif interlaced_ratio > 0.65:
        mode = FieldMode.INTERLACED
        confidence = interlaced_ratio
    elif interlaced_ratio < 0.10:
        mode = FieldMode.PROGRESSIVE
        confidence = 1.0 - interlaced_ratio
    else:
        mode = FieldMode.UNKNOWN
        confidence = 0.5

    return FieldReport(mode, prog, tff, bff, undet, repeated, total, confidence)


# ===========================================================================
#  Geometria: aspect ratio e bande nere
# ===========================================================================

def parse_geometry(stderr: str, meta: dict) -> GeometryReport:
    """Aspect ratio reale: pixel quadri o anamorfico."""
    stream = _video_stream(meta)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)

    sar = _fraction(stream.get("sample_aspect_ratio")) or Fraction(1)
    if sar <= 0:
        sar = Fraction(1)
    dar = _fraction(stream.get("display_aspect_ratio")) or (
        Fraction(width, height) * sar if height else Fraction(16, 9)
    )

    # Dimensioni a pixel quadri. Si ESPANDE sempre l'asse corto, non si
    # comprime mai l'altro: comprimendo si butterebbe via risoluzione reale
    # prima ancora di darla al modello di upscaling. Con SAR 480:527 la
    # versione precedente portava 710 colonne a 648, scartandone il 9%.
    fattore = float(sar) if sar else 1.0
    if fattore >= 1:
        disp_w, disp_h = round(width * fattore), height
    else:
        disp_w, disp_h = width, round(height / fattore)
    disp_w += disp_w % 2
    disp_h += disp_h % 2

    return GeometryReport(width, height, sar, dar, disp_w, disp_h)


# ===========================================================================
#  Duplicati (animazione "in due"/"in tre")
# ===========================================================================

def analyze_duplicates(
    path: Path, *, paths: Paths | None = None, video_filter: str | None = None
) -> DuplicateReport:
    """Struttura dei frame identici, per deduplicare il lavoro GPU.

    Costa una decodifica completa ma senza codifica: ~20 s per episodio.
    """
    probe = FFprobe(paths or PATHS)
    total = 0
    consecutive = 0
    runs: Counter[int] = Counter()
    previous: str | None = None
    run_length = 0

    for h in probe.frame_hashes(path, video_filter=video_filter):
        total += 1
        if h == previous:
            consecutive += 1
            run_length += 1
        else:
            if run_length:
                runs[run_length] += 1
            run_length = 1
        previous = h
    if run_length:
        runs[run_length] += 1

    unique = total - consecutive
    return DuplicateReport(total, unique, consecutive, runs)


# ===========================================================================
#  Analisi completa
# ===========================================================================

def probe_source(
    path: Path,
    *,
    with_fields: bool = True,
    with_geometry: bool = True,
    with_duplicates: bool = False,
    paths: Paths | None = None,
) -> SourceReport:
    """Analisi completa di un sorgente.

    with_duplicates costa una decodifica completa: si attiva quando serve
    pianificare la deduplica, non per una semplice ispezione.
    """
    # Normalizzato all'ingresso: con una stringa l'analisi riusciva lo stesso
    # (tutto finisce in una riga di comando) e il piano esplodeva molto dopo
    # con "'str' object has no attribute 'stem'", lontanissimo dalla causa.
    path = Path(path)
    p = paths or PATHS
    probe = FFprobe(p)
    meta = probe.format_and_streams(path)

    fmt = meta.get("format", {})
    stream = _video_stream(meta)
    duration = float(fmt.get("duration") or 0.0)

    timing = analyze_timing(path, meta, p)

    # Una sola scansione integrale alimenta sia i campi sia la geometria.
    scan = scan_full(path, p) if (with_fields or with_geometry) else ""
    geometry = (
        parse_geometry(scan, meta)
        if with_geometry
        else GeometryReport(
            int(stream.get("width") or 0), int(stream.get("height") or 0),
            Fraction(1), Fraction(16, 9),
            int(stream.get("width") or 0), int(stream.get("height") or 0),
        )
    )
    fields = parse_fields(scan) if with_fields else None
    duplicates = analyze_duplicates(path, paths=p) if with_duplicates else None

    subs = [s for s in meta.get("streams", []) if s.get("codec_type") == "subtitle"]

    return SourceReport(
        path=path,
        container=fmt.get("format_name", "?"),
        duration=duration,
        video_codec=stream.get("codec_name", "?"),
        pix_fmt=stream.get("pix_fmt", "?"),
        bit_depth=_bit_depth(stream),
        color_space=stream.get("color_space"),
        color_transfer=stream.get("color_transfer"),
        color_primaries=stream.get("color_primaries"),
        audio_tracks=sum(1 for s in meta.get("streams", []) if s.get("codec_type") == "audio"),
        subtitle_tracks=len(subs),
        subtitle_codecs=[s.get("codec_name", "?") for s in subs],
        chapters=len(meta.get("chapters", [])),
        geometry=geometry,
        timing=timing,
        fields=fields,
        duplicates=duplicates,
    )


# ===========================================================================
#  Utilita'
# ===========================================================================

def _video_stream(meta: dict) -> dict:
    for s in meta.get("streams", []):
        if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0:
            return s
    return {}


def _fraction(value: str | None) -> Fraction | None:
    """Converte una frazione di ffprobe, con qualunque separatore.

    ffprobe usa DUE convenzioni diverse: la barra per i framerate
    (`24000/1001`) e i due punti per gli aspect ratio (`480:527`). Fraction
    accetta solo la barra, quindi senza questa normalizzazione ogni SAR
    fallisce in silenzio e si finisce per trattare come a pixel quadri anche
    un DVD anamorfico, deformando l'uscita.
    """
    if not value:
        return None
    value = value.strip().replace(":", "/")
    if value in ("0/0", "N/A", "0", ""):
        return None
    try:
        frazione = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return frazione if frazione > 0 else None


def _fps_str(fps: Fraction | None) -> str:
    if fps is None:
        return "?"
    value = float(fps)
    if fps.denominator == 1:
        return f"{fps.numerator}"
    return f"{value:.3f}"


# Profondita' in bit dedotta dal formato pixel: `bits_per_raw_sample` è
# assente su molti flussi HEVC, e ripiegare su 8 faceva passare per 8 bit un
# sorgente a 10.
_CIFRE_FORMATO = re.compile(r"(\d+)(?:le|be)?$")
# Formati che nel nome portano i bit COMPLESSIVI e non quelli per componente.
_PER_COMPONENTE = {"rgb": 3, "bgr": 3, "gbr": 3, "rgba": 4, "bgra": 4}


def _bit_depth(stream: dict) -> int:
    """Bit per componente, dedotti dal formato pixel se il campo manca.

    `bits_per_raw_sample` è spesso assente sui flussi HEVC, e ripiegare su 8
    faceva passare per 8 bit un sorgente a 10.
    """
    dichiarata = stream.get("bits_per_raw_sample")
    if dichiarata and str(dichiarata).isdigit() and int(dichiarata) > 0:
        return int(dichiarata)

    pix = str(stream.get("pix_fmt") or "")
    if not (m := _CIFRE_FORMATO.search(pix)):
        return 8
    numero = int(m.group(1))
    # rgb48 vuol dire 48 bit in tutto, cioè 16 per componente; yuv420p10
    # vuol dire già 10 per componente.
    for prefisso, componenti in _PER_COMPONENTE.items():
        if pix.startswith(prefisso) and numero % componenti == 0:
            return numero // componenti
    return numero if 8 <= numero <= 16 else 8
