"""La libreria dei file di INPUT, con analisi progressiva.

L'analisi completa costa una trentina di secondi a file. Su una serie intera
sarebbero diversi minuti di attesa a ogni apertura dell'interfaccia, il che
renderebbe inutilizzabile qualunque schermata di scelta.

Quindi due livelli:
  - lettura rapida dei metadati (istantanea), per popolare subito l'elenco;
  - analisi completa su richiesta, conservata su disco e riusata finché il
    file non cambia.
"""

from __future__ import annotations

import hashlib
import re
import json
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from fractions import Fraction
from pathlib import Path

from .ffmpeg import FFprobe
from .paths import PATHS, Paths
from .probe import SourceReport, probe_source

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".webm"}


@dataclass
class Entry:
    """Un file della libreria, con i soli dati a costo zero."""

    path: Path
    width: int
    height: int
    duration: float
    codec: str
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else "?"

    @property
    def duration_hms(self) -> str:
        s = int(self.duration)
        if s >= 3600:
            return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
        return f"{s // 60:02d}:{s % 60:02d}"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1_048_576


# I metadati già letti, per file. La chiave è l'identità del file COME STA
# ADESSO — percorso, dimensione, istante di modifica — quindi un file che non
# è cambiato non viene riletto, e uno che è cambiato non può essere scambiato
# per quello di prima.
#
# Serve perché questa scansione lancia un ffprobe PER FILE, e l'interfaccia la
# ripete da sola ogni pochi secondi: su sedici file sono sedici processi ogni
# volta (0,37 s misurati), per tutte le ore di una lavorazione, sullo stesso
# disco su cui la lavorazione sta scrivendo. Con la cache una scansione senza
# novità costa una `stat()` per file e nessun processo.
_METADATI: dict[tuple[str, int, int], "Entry"] = {}


def scan(folder: Path | None = None, paths: Paths | None = None) -> list[Entry]:
    """Elenco dei file con i metadati di base. Nessuna decodifica."""
    p = paths or PATHS
    folder = folder or p.input
    probe = FFprobe(p)

    entries: list[Entry] = []
    visti: set[tuple[str, int, int]] = set()
    for f in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            st = f.stat()
        except OSError:        # sparito fra l'elenco e la lettura
            continue
        chiave = (str(f), st.st_size, st.st_mtime_ns)
        visti.add(chiave)
        gia = _METADATI.get(chiave)
        if gia is not None:
            entries.append(gia)
            continue
        try:
            meta = probe.format_and_streams(f)
        except Exception:  # noqa: BLE001 - un file illeggibile non ferma l'elenco
            continue
        # Stessa regola di probe.py: una copertina muxata come stream video
        # non deve essere scambiata per il video vero.
        video = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
        stream = next(
            (s for s in video if not s.get("disposition", {}).get("attached_pic")),
            video[0] if video else {},
        )
        voce = Entry(
            path=f,
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
            duration=float(meta.get("format", {}).get("duration") or 0.0),
            codec=stream.get("codec_name", "?"),
            size_bytes=st.st_size,
        )
        _METADATI[chiave] = voce
        entries.append(voce)
    # Via le voci dei file che non ci sono più (o che sono cambiati): senza,
    # il dizionario crescerebbe per tutta la sessione, e in una maratona con
    # molti file entrati e usciti da INPUT diventerebbe una perdita lenta.
    for morto in [k for k in _METADATI if k not in visti]:
        del _METADATI[morto]
    return entries


# ===========================================================================
#  Analisi conservata su disco
# ===========================================================================

def _cache_path(path: Path, paths: Paths) -> Path:
    """Nome di cache univoco e di lunghezza limitata.

    Usava il solo stem: due episodi omonimi in cartelle diverse (`INPUT/` e
    `_WIP/_DA FARE 720p/` contengono per costruzione gli stessi nomi)
    condividevano lo stesso file e si invalidavano a vicenda all'infinito.
    E con un nome vicino ai 255 byte la scrittura falliva con "File name too
    long", perché l'estensione .json sforava il limite.
    """
    folder = paths.analisi
    folder.mkdir(parents=True, exist_ok=True)
    # Identità RELATIVA alla radice, come per la cartella di lavoro: usando il
    # percorso assoluto, la copia della cartella sul secondo Mac cambiava tutte
    # le chiavi e rimandava l'intera libreria "da analizzare", quindici secondi
    # a file su una serie intera, lasciando per giunta i vecchi JSON orfani.
    from .pipeline import identita_sorgente
    impronta = hashlib.sha1(
        identita_sorgente(Path(path), paths.input).encode("utf-8")
    ).hexdigest()[:12]
    breve = re.sub(r"[^\w.-]+", "_", path.stem)[:80].strip("_")
    return folder / f"{breve or 'file'}-{impronta}.json"


@lru_cache(maxsize=1)
def _analysis_version() -> str:
    """Impronta del codice di analisi.

    Serve a invalidare la cache quando cambia il MODO in cui si analizza, non
    solo quando cambia il file. Senza, una correzione a probe.py lascia in
    giro referti calcolati con la logica vecchia: è successo davvero con il
    SAR, dove dopo la correzione i file già analizzati continuavano a
    risultare a pixel quadri.

    Si usa l'impronta del sorgente e non un numero di versione a mano, così
    nessuno si dimentica di incrementarlo.
    """
    sorgente = Path(__file__).with_name("probe.py")
    try:
        return hashlib.sha1(sorgente.read_bytes()).hexdigest()[:12]
    except OSError:
        return "sconosciuta"


def _fingerprint(path: Path) -> str:
    """Cambia se cambia il file oppure il codice che lo analizza.

    Solo la DIMENSIONE, non la data di modifica: la mtime cambia per un rsync
    o per un ripristino da backup senza che un bit del contenuto sia diverso,
    e dopo una copia disco-a-disco l'intera libreria tornava da rianalizzare.
    È la stessa scelta già fatta in `pipeline._firma_estrazione`, per la
    stessa ragione.
    """
    st = path.stat()
    return f"{st.st_size}-{_analysis_version()}"


def cached_report(path: Path, paths: Paths | None = None) -> SourceReport | None:
    """Analisi già fatta per questo file, se ancora valida."""
    p = paths or PATHS
    try:
        cache = _cache_path(path, p)
        if not cache.is_file():
            return None
        data = json.loads(cache.read_text())
        if data.get("fingerprint") != _fingerprint(path):
            return None
        return _decode(data["report"], path)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        # Cache illeggibile, file sparito, nome troppo lungo: si rianalizza.
        # Nessuno di questi casi deve arrivare all'utente come traccia.
        return None


def analyse(
    path: Path, *, force: bool = False, paths: Paths | None = None
) -> SourceReport:
    """Analisi completa, riusando quella su disco quando possibile."""
    p = paths or PATHS
    if not force and (cached := cached_report(path, p)) is not None:
        return cached

    report = probe_source(path, paths=p)
    try:
        cache = _cache_path(path, p)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "fingerprint": _fingerprint(path),
            "report": _encode(report),
        }, indent=2))
        tmp.replace(cache)
    except OSError:
        pass          # senza cache si perde velocità, non correttezza
    return report


def approfondisci(
    path: Path, *, paths: Paths | None = None
) -> SourceReport | None:
    """Aggiunge al referto la deduplica MISURATA su un campione del file.

    Passo separato, e non parte di `analyse`, per una ragione di tempi: la
    misura raddoppia o triplica l'analisi (38s -> 78s su un episodio da 24
    minuti, 119s su un 1080p da 25), e si pagherebbe su OGNI file in
    cartella, compresi quelli che non verranno mai convertiti.

    NON rifa' niente di quel che c'era: la sonda non viene rieseguita, si
    parte dal referto in cassa e ci si aggiunge un campo. L'analisi veloce
    fatta prima non e' tempo buttato.
    """
    p = paths or PATHS
    report = cached_report(path, p) or analyse(path, paths=p)
    if report is None:
        return None
    if report.dedup_campione is not None:
        return report                     # gia' approfondito: non si rifa'
    from . import dedup as _dd

    quota = _dd.stima_campionata(path, report.duration, paths=p)
    if quota is None:
        return report
    report = replace(report, dedup_campione=quota)
    try:
        cache = _cache_path(path, p)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "fingerprint": _fingerprint(path),
            "report": _encode(report),
        }, indent=2))
        tmp.replace(cache)
    except OSError:
        pass
    return report


# --- serializzazione ------------------------------------------------------
# I dataclass del referto contengono Fraction, Path, Enum e Counter, che JSON
# non conosce: si convertono in stringhe e si ricostruiscono al ritorno.

def _encode(report: SourceReport) -> dict:
    # asdict() ricostruisce le sotto-mappe con type(obj)(coppie): su un
    # Counter questo CONTA le coppie invece di usarle, e run_lengths tornava
    # come {"(1, 200)": 1}. Si estrae prima, si reinserisce dopo.
    conteggi = (dict(report.duplicates.run_lengths)
                if report.duplicates is not None else None)

    def convert(value):
        if isinstance(value, Fraction):
            return {"__fraction__": str(value)}
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): convert(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(v) for v in value]
        return value

    grezzo = convert(asdict(report))
    if conteggi is not None:
        grezzo["duplicates"]["run_lengths"] = {str(k): v for k, v in conteggi.items()}
    return grezzo


def _decode(data: dict, path: Path) -> SourceReport:
    from .probe import (
        DuplicateReport, FieldMode, FieldReport,
        GeometryReport, Timebase, TimingReport,
    )
    from collections import Counter

    def frac(value) -> Fraction | None:
        if isinstance(value, dict) and "__fraction__" in value:
            return Fraction(value["__fraction__"])
        return None

    g = data["geometry"]
    geometry = GeometryReport(
        width=g["width"], height=g["height"],
        sar=frac(g["sar"]) or Fraction(1), dar=frac(g["dar"]) or Fraction(16, 9),
        display_width=g["display_width"], display_height=g["display_height"],
    )

    t = data["timing"]
    timing = TimingReport(
        mode=Timebase(t["mode"]), fps=frac(t["fps"]),
        fps_is_standard=t["fps_is_standard"], packets=t["packets"],
        time_base=frac(t["time_base"]) or Fraction(1, 1000),
        dominant_delta=t["dominant_delta"], jitter_ticks=t["jitter_ticks"],
        quantization_only=t["quantization_only"], gaps=t["gaps"],
        missing_frames=t["missing_frames"],
        outliers=[tuple(o) for o in t["outliers"]],
        container_r_fps=frac(t["container_r_fps"]),
        container_avg_fps=frac(t["container_avg_fps"]),
        notes=t["notes"],
    )

    fields = None
    if f := data.get("fields"):
        fields = FieldReport(
            mode=FieldMode(f["mode"]), progressive=f["progressive"], tff=f["tff"],
            bff=f["bff"], undetermined=f["undetermined"],
            repeated_fields=f["repeated_fields"], total=f["total"],
            confidence=f["confidence"],
        )

    duplicates = None
    if u := data.get("duplicates"):
        duplicates = DuplicateReport(
            total_frames=u["total_frames"], unique_frames=u["unique_frames"],
            consecutive_duplicates=u["consecutive_duplicates"],
            run_lengths=Counter({int(k): v for k, v in u["run_lengths"].items()}),
        )

    return SourceReport(
        path=path, container=data["container"], duration=data["duration"],
        video_codec=data["video_codec"], pix_fmt=data["pix_fmt"],
        bit_depth=data["bit_depth"], color_space=data["color_space"],
        color_transfer=data["color_transfer"], color_primaries=data["color_primaries"],
        audio_tracks=data["audio_tracks"], subtitle_tracks=data["subtitle_tracks"],
        subtitle_codecs=data["subtitle_codecs"], chapters=data["chapters"],
        geometry=geometry, timing=timing, fields=fields,
        duplicates=duplicates,
        dedup_campione=data.get("dedup_campione"),
    )
