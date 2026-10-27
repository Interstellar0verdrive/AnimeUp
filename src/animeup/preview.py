"""Anteprima: spezzoni brevi elaborati con più modelli, da confrontare.

Serve a rispondere in dieci minuti alla domanda che altrimenti costa quattro
ore: "questo preset mi piace?".

Il principio è che l'app automatizza il tedio (scegliere i punti difficili,
tagliare, elaborare, organizzare) e si ferma lì. Il giudizio sulla resa in
movimento si dà con video-compare sui file prodotti: un riproduttore
dentro una pagina web, a scala diversa da 1:1, nasconde proprio gli artefatti
che si devono giudicare.

L'unica cosa che ha senso mostrare a schermo sono i ritagli a dimensione
nativa, dove nessuna scala può mentire.
"""

from __future__ import annotations

import hashlib
import json
import re
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .ffmpeg import run_esito, run_stderr
from .i18n import t
from .models import CATALOG
from . import taratura
from .paths import PATHS, Paths
from .plan import Plan

_YMAX = re.compile(r"signalstats\.YMAX=([0-9.]+)")
_YAVG = re.compile(r"signalstats\.YAVG=([0-9.]+)")

DEFAULT_SECONDS = 10
# Margine decodificato prima dello spezzone: il salto veloce da solo lascia
# qualche fotogramma ricostruito per approssimazione, inutilizzabile.
SEEK_LEAD = 10.0

# Le impronte che il decoder h264/hevc lascia su stderr quando è partito da
# un punto che non era un vero ingresso. Con gli encode a intra-refresh — i
# fansub Hi444PP ne fanno uso — i pacchetti marcati keyframe sono solo punti
# di RECUPERO: saltarci sopra produce il verde acido misurato su un caso
# reale (croma medio 99/47 contro il 131/123 della decodifica corretta).
_SEGNI_DECODIFICA_ROTTA = (
    "error while decoding", "Reference", "top block unavailable",
    "left block unavailable", "gray chroma", "concealing errors")


def _comando_estrazione(p: Paths, src: Path, start: float,
                        *, veloce: bool, dur: float) -> list[str]:
    base = [str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y"]
    if veloce:
        # `-xerror -err_detect explode`: se il punto d'ingresso non e' un
        # vero IDR il decoder RIFIUTA (exit != 0) invece di inventare i
        # riferimenti che non ha. Solo sul salto rapido: la ridecodifica
        # dall'inizio deve invece restare tollerante, sui file davvero
        # danneggiati il concealment e' il meglio che c'e'.
        base += ["-xerror", "-err_detect", "explode"]
        coarse = max(0.0, start - SEEK_LEAD)
        base += ["-ss", f"{coarse:.3f}",
                 "-t", f"{start - coarse + dur + 0.5:.2f}",
                 "-i", str(src), "-ss", f"{start - coarse:.3f}"]
    else:
        # Nessun salto: si decodifica dall'inizio e si scarta fino a `start`.
        # Costa secondi, ma è l'unico ingresso valido quando i keyframe del
        # contenitore sono bugiardi.
        base += ["-i", str(src), "-ss", f"{start:.3f}"]
    return base


def estrai_finestra(p: Paths, src: Path, start: float, resto: list[str],
                    *, dur: float, on_step=None) -> None:
    """Estrae una finestra del sorgente in modo VERIFICATO.

    Prima il salto rapido, che sui file sani costa un decimo di secondo,
    armato di `-xerror -err_detect explode`: se il keyframe del contenitore
    e' bugiardo il decoder fallisce, e si rifa' tutto decodificando
    dall'inizio. Il verdetto primario e' il codice d'uscita — i messaggi
    nello stderr NON sono affidabili: stesso comando, stesso file, un run
    li stampa e uno no (dipende dai thread; misurato su un caso reale,
    ed e' cosi' che una miniatura verde era passata). I marcatori testuali
    restano come seconda rete per i casi in cui il flusso e' legale ma
    l'immagine no (recovery point di un encode a intra-refresh).
    """
    codice, stderr = run_esito(_comando_estrazione(p, src, start, veloce=True,
                                                   dur=dur) + resto)
    if codice == 0 and not any(segno in stderr
                               for segno in _SEGNI_DECODIFICA_ROTTA):
        return
    if on_step:
        on_step(t("mot.preview.niente_salto"))
    run_stderr(_comando_estrazione(p, src, start, veloce=False,
                                   dur=dur) + resto)


class Kind(str, Enum):
    # I valori finiscono nei nomi delle cartelle delle clip: in inglese.
    STATIC = "static"
    MOTION = "motion"
    DARK = "dark"
    BRIGHT = "bright"

    @property
    def tests(self) -> str:
        return {
            Kind.STATIC: t("mot.preview.prova_statico"),
            Kind.MOTION: t("mot.preview.prova_movimento"),
            Kind.DARK: t("mot.preview.prova_scuro"),
            Kind.BRIGHT: t("mot.preview.prova_luminoso"),
        }[self]


@dataclass
class Candidate:
    kind: Kind
    start_frame: int
    frames: int
    fps: float
    motion: float
    brightness: float
    reason: str

    @property
    def start_seconds(self) -> float:
        return self.start_frame / self.fps

    @staticmethod
    def _mmss(secondi: float) -> str:
        s = int(secondi)
        return f"{s // 60:02d}:{s % 60:02d}"

    @property
    def timecode(self) -> str:
        return self._mmss(self.start_seconds)

    @property
    def timecode_range(self) -> str:
        """Inizio e fine. Il solo inizio non dice quanto dura lo spezzone."""
        fine = self.start_seconds + self.frames / self.fps
        return f"{self.timecode} – {self._mmss(fine)}"

    @property
    def slug(self) -> str:
        return f"{self.kind.value}_{self.timecode.replace(':', 'm')}s"


@dataclass
class Variant:
    """Una configurazione da confrontare."""

    key: str            # chiave nel catalogo, oppure "original"

    @property
    def is_reference(self) -> bool:
        return self.key == "original"

    @property
    def label(self) -> str:
        # Letta a ogni uso e non fissata alla nascita: REFERENCE nasce
        # all'import, e la lingua può cambiare ad app aperta.
        if self.is_reference:
            return t("mot.preview.riferimento")
        return CATALOG[self.key].label


REFERENCE = Variant("original")


def scale_for(key: str, plan: Plan) -> int:
    """Scala valida PER QUESTO modello, non quella del piano.

    Il piano sceglie la scala per il modello del piano. Passarla tale e quale a
    una variante che non la possiede fa danni silenziosi: `-s 4` a un modello
    che ha solo `up2x-denoise1x` fa caricare in silenzio un modello di rumore
    diverso su ingressi piccoli (uscita della dimensione giusta, contenuto di
    un altro modello: si sceglierebbe guardando una bugia) e va in
    segmentation fault su 1280x720.

    Si riusa la stessa regola del piano, così la variante viene mostrata alla
    scala con cui verrebbe davvero usata.
    """
    from .plan import _choose_scale

    model = CATALOG[key]
    if plan.model_scale in model.scales:
        return plan.model_scale
    src_h = plan.source.geometry.height
    return _choose_scale(src_h, plan.target_height, model)


def variants_for(*model_keys: str, reference: bool = True) -> list[Variant]:
    out = [Variant(k) for k in model_keys if k in CATALOG]
    if reference:
        out.append(REFERENCE)
    return out


@dataclass
class PreviewResult:
    candidate: Candidate
    folder: Path
    files: dict[str, Path] = field(default_factory=dict)   # chiave variante -> file
    crop_sheet: Path | None = None
    # Lo stesso ritaglio 1:1 di ogni variante, in un file a parte: la pagina
    # ne mostra due grandi affiancati, scelti dall'utente (chiave -> PNG).
    crops: dict[str, Path] = field(default_factory=dict)
    seconds: float = 0.0
    # Secondi PER VARIANTE: servono alla proiezione "su 10 secondi ci ha
    # messo 8m 32s, quindi l'episodio intero ≈ Xh" — col totale soltanto, il
    # riferimento (veloce) annacquava i modelli (lenti).
    tempi: dict[str, float] = field(default_factory=dict)
    # Due indicatori per variante: (dettaglio fine, rumore nelle aree piatte),
    # entrambi in RAPPORTO all'originale ingrandito. `None` dove la misura
    # non ha senso su questo fotogramma. Vedi `_indicatori`.
    metriche: dict[str, tuple[float | None, float | None]] = field(
        default_factory=dict)


# ===========================================================================
#  Scelta dei candidati
# ===========================================================================

def _scan(source: Path, chain: str, key: re.Pattern[str], p: Paths) -> list[float]:
    with tempfile.TemporaryDirectory(prefix="animeup-scan-") as tmp:
        out = Path(tmp) / "m.txt"
        run_stderr([
            str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-i", str(source),
            "-vf", f"{chain},metadata=print:file={out}",
            "-an", "-sn", "-f", "null", "-",
        ])
        return [float(v) for v in key.findall(out.read_text())] if out.is_file() else []


def _schedario(plan: Plan, per_kind: int, seconds: int, p: Paths,
               lotto: int | str = 0) -> Path:
    """Dove finiscono gli spezzoni trovati, per non riscansionare due volte."""
    st = plan.source.path.stat()
    # `REGOLA_SCELTA` fa parte della firma: cambiando il modo di scegliere
    # gli spezzoni, una cassa scritta con la regola vecchia non vale piu'.
    # Senza, la distanza minima introdotta il 12/08 sarebbe rimasta
    # invisibile su tutti i file gia' scansionati — cioe' proprio quelli su
    # cui il difetto era stato notato.
    firma = (f"{plan.source.path.name}|{st.st_size}|{int(st.st_mtime)}"
             f"|{per_kind}|{seconds}|lotto{lotto}|r{REGOLA_SCELTA}")
    h = hashlib.sha1(firma.encode()).hexdigest()[:12]
    return p.previews / "clips" / f"{plan.source.path.stem[:60]}-{h}.json"


def deposito(plan: Plan, per_kind: int = 2, seconds: int = DEFAULT_SECONDS,
             paths: Paths | None = None) -> Path:
    """Dove vive l'elenco COMPLETO degli spezzoni trovati per questo file.

    Gli schedari di `_schedario` sono la cassa della SCANSIONE, uno per lotto:
    servono a non riscansionare, e infatti sono chiavati anche sul lotto. Ma
    l'interfaccia ne rileggeva uno solo, il primo, e dopo un ricaricamento il
    secondo lotto spariva dalla pagina pur essendo su disco — con le sue clip
    gia' estratte (verificato sul 360p: otto spezzoni orfani). Peggio: senza
    memoria dei gia' visti il pulsante ripescava il primo lotto e lo
    AGGIUNGEVA, mettendo in pagina otto card doppie.

    Qui invece c'e' una cosa sola: l'elenco accumulato, che e' quello che la
    pagina deve ritrovare.
    """
    return _schedario(plan, per_kind, seconds, paths or PATHS, "tutti")


def leggi_deposito(plan: Plan, per_kind: int = 2, seconds: int = DEFAULT_SECONDS,
                   paths: Paths | None = None) -> list[Candidate]:
    return _leggi_schedario(deposito(plan, per_kind, seconds, paths),
                            float(plan.fps))


def solo_nuovi(avuti: list[Candidate],
               nuovi: list[Candidate]) -> list[Candidate]:
    """Di `nuovi`, quelli che non sono gia' in `avuti`.

    Chi chiede altri spezzoni li vuole AGGIUNTI. Ma aggiungere alla cieca
    fabbrica card doppie non appena una via qualsiasi riporta indietro roba
    gia' vista — ed e' successo: dopo un ricaricamento il pulsante ripescava
    dalla cassa il primo lotto e lo appendeva a se stesso.
    """
    noti = {c.start_frame for c in avuti}
    return [c for c in nuovi if c.start_frame not in noti]


def scrivi_deposito(plan: Plan, candidati: list[Candidate], per_kind: int = 2,
                    seconds: int = DEFAULT_SECONDS,
                    paths: Paths | None = None) -> None:
    _scrivi_schedario(deposito(plan, per_kind, seconds, paths), candidati)


def _leggi_schedario(f: Path, fps: float) -> list[Candidate]:
    try:
        dati = json.loads(f.read_text())
    except (OSError, ValueError):
        return []
    try:
        return [Candidate(kind=Kind(d["kind"]), start_frame=d["start_frame"],
                          frames=d["frames"], fps=fps, motion=d["motion"],
                          brightness=d["brightness"], reason=d["reason"])
                for d in dati]
    except (KeyError, TypeError, ValueError):
        return []


def _scrivi_schedario(f: Path, candidati: list[Candidate]) -> None:
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(
            [{"kind": c.kind.value, "start_frame": c.start_frame, "frames": c.frames,
              "motion": c.motion, "brightness": c.brightness, "reason": c.reason}
             for c in candidati], indent=1))
    except OSError:
        pass          # il risultato c'e' comunque: perderlo costa una riscansione


def find_candidates(
    plan: Plan, *, per_kind: int = 2, seconds: int = DEFAULT_SECONDS,
    paths: Paths | None = None, on_step=None,
    escludi: tuple[int, ...] = (),
) -> list[Candidate]:
    """Individua spezzoni rappresentativi delle situazioni difficili.

    Due scansioni del sorgente: una misura il movimento fra fotogrammi,
    l'altra la luminosità media. Misurate su episodi interi: 28s a 360p,
    30s a 480p, 51s a 720p — non i tre minuti che l'interfaccia annunciava.

    Il risultato finisce su disco: sono minuti di scansione, e perderli perché
    l'interfaccia è stata ricaricata è successo davvero.
    """
    p = paths or PATHS
    fps = float(plan.fps)
    window = max(1, int(seconds * fps))
    passo = on_step or (lambda _t: None)

    schedario = _schedario(plan, per_kind, seconds, p, len(escludi))
    if schedario.is_file():
        gia = _leggi_schedario(schedario, fps)
        if gia:
            passo(t("mot.preview.scansione_ripresa"))
            return gia

    # format=gray forza la scala a 8 bit: senza, su un sorgente a 10 bit i
    # valori escono su 0-1023 e i numeri mostrati all'utente sono illeggibili.
    passo(t("mot.preview.scansione_movimento"))
    motion = _scan(
        plan.source.path,
        "scale=320:180,format=gray,tblend=all_mode=difference,signalstats", _YMAX, p,
    )
    passo(t("mot.preview.scansione_luminosita"))
    bright = _scan(plan.source.path, "scale=320:180,format=gray,signalstats", _YAVG, p)
    if not motion or not bright:
        return []

    n = min(len(motion), len(bright))
    if n < window * 2:
        return []

    # Medie mobili sulla finestra, per valutare lo spezzone e non il singolo frame.
    def rolling(values: list[float]) -> list[float]:
        acc = sum(values[:window])
        out = [acc / window]
        for i in range(1, n - window):
            acc += values[i + window - 1] - values[i - 1]
            out.append(acc / window)
        return out

    m_roll, b_roll = rolling(motion[:n]), rolling(bright[:n])
    count = len(m_roll)
    m_sorted, b_sorted = sorted(m_roll), sorted(b_roll)
    m_avg = sum(m_roll) / count

    def pct(values: list[float], q: float) -> float:
        return values[min(count - 1, int(count * q))]

    rules = [
        (Kind.MOTION, lambda i: m_roll[i], True,
         lambda i: t("mot.preview.motivo_movimento", movimento=f"{m_roll[i]:.0f}",
                     media=f"{m_avg:.0f}")),
        (Kind.STATIC, lambda i: -m_roll[i], True,
         lambda i: t("mot.preview.motivo_statico", movimento=f"{m_roll[i]:.0f}")),
        # Il segno della penalità era PIÙ, quindi promuoveva i punti fermi
        # invece di scartarli: la scena "scura" scelta era per costruzione
        # immobile, e la descrizione mostrata a schermo — "con movimento" —
        # era falsa. Il caso duplicava quello già coperto da `statico`,
        # lasciando due situazioni distinte su quattro.
        (Kind.DARK, lambda i: -b_roll[i] + (0 if m_roll[i] > pct(m_sorted, 0.2) else -1e6), True,
         lambda i: t("mot.preview.motivo_scuro", luminosita=f"{b_roll[i]:.0f}")),
        (Kind.BRIGHT, lambda i: b_roll[i] + (0 if m_roll[i] > pct(m_sorted, 0.3) else -1e6), True,
         lambda i: t("mot.preview.motivo_luminoso", luminosita=f"{b_roll[i]:.0f}")),
    ]

    chosen: list[Candidate] = []
    # Le posizioni gia' usate in un lotto precedente valgono come prese: e'
    # cosi' che «trova altri spezzoni» ne trova davvero ALTRI.
    taken: list[int] = list(escludi)
    # Fra due spezzoni dello STESSO tipo si pretende molta piu' distanza che
    # la sola non sovrapposizione. Senza, il secondo piu' fermo del file e'
    # quasi sempre il vicino di casa del primo: su un episodio vero sono
    # usciti due «statico» a 23:56 e 24:09 — tredici secondi, la stessa
    # scena, due prove per il prezzo di una (visto dall'utente il 12/08).
    # La distanza si rapporta a QUANTI spezzoni esisteranno in tutto, non a
    # un numero fisso: e' «spalmane N sulla durata», quindi durata diviso N.
    # Con otto esclusioni da un ottavo di file l'una, un episodio da 25
    # minuti risultava saturo e il secondo lotto ne trovava quattro tutti
    # nello stesso minuto (provato il 12/08). Rapportando, il primo lotto
    # pretende un ottavo e il secondo un sedicesimo, che e' esattamente lo
    # spazio rimasto.
    quanti = per_kind * len(rules) + len(escludi)
    distinti = max(window, count // max(1, quanti))
    for kind, score, _desc, reason in rules:
        ranked = sorted(range(count), key=score, reverse=True)
        stesso_tipo = [c.start_frame for c in chosen if c.kind is kind]
        picked = 0
        for i in ranked:
            # Niente spezzoni sovrapposti, e si evitano i titoli di testa/coda.
            if i < fps * 5 or i > count - window:
                continue
            if any(abs(i - t) < window for t in taken):
                continue
            if any(abs(i - t) < distinti for t in stesso_tipo):
                continue
            # E la stessa distanza dai lotti PRECEDENTI, qualunque tipo
            # fossero: chi chiede altri spezzoni vuole vedere altre parti
            # del film, non le stesse scene spostate di quindici secondi.
            # Senza questa riga il secondo lotto tornava sei volte su otto a
            # meno di venti secondi dal primo — cioe' le stesse scene
            # (provato il 12/08 sul 360p, prima di correggere).
            if any(abs(i - t) < distinti for t in escludi):
                continue
            chosen.append(Candidate(
                kind=kind, start_frame=i, frames=window, fps=fps,
                motion=m_roll[i], brightness=b_roll[i], reason=reason(i),
            ))
            taken.append(i)
            stesso_tipo.append(i)
            picked += 1
            if picked >= per_kind:
                break

    scelti = sorted(chosen, key=lambda c: c.start_frame)
    if scelti:
        _scrivi_schedario(schedario, scelti)
    return scelti


def thumbnail(plan: Plan, candidate: Candidate, dest: Path,
              *, width: int = 480, paths: Paths | None = None) -> Path | None:
    """Miniatura del sorgente per il carosello di scelta.

    È del sorgente e non dell'upscale: serve a scegliere DOVE guardare, non a
    giudicare la resa.
    """
    p = paths or PATHS
    dest.parent.mkdir(parents=True, exist_ok=True)
    middle = candidate.start_seconds + candidate.frames / candidate.fps / 2
    estrai_finestra(
        p, plan.source.path, middle,
        ["-frames:v", "1", "-vf", f"scale={width}:-2", str(dest)], dur=1.0)
    return dest if dest.is_file() else None


def animation(plan: Plan, candidate: Candidate, dest: Path, *, width: int = 360,
              seconds: float | None = None, fps: int = 12,
              paths: Paths | None = None, on_step=None) -> Path | None:
    """Lo spezzone intero, muto, per sceglierlo guardandolo muovere.

    Su un fermo immagine non si distingue una scena ferma da una in movimento,
    che è esattamente la differenza su cui si sta scegliendo.

    Dura quanto lo spezzone vero (`seconds=None`): un estratto più corto fa
    scegliere su una cosa diversa da quella che verrà elaborata, e tanto vale
    mostrare quella giusta — otto spezzoni interi costano 4 secondi.

    Video e non GIF: la GIF costa dodici volte tanto in byte e schiaccia i
    colori a 128, cioè fabbrica banding proprio dove si va a cercarlo.

    `-t` sta sull'INGRESSO di proposito. Sull'uscita, insieme a un
    `filter_complex`, ffmpeg continua a decodificare fino alla fine del file:
    misurati 35.7 secondi per due secondi e mezzo di spezzone, contro 1.1.

    Il ciclo lo mette Streamlit: non con l'attributo `loop` del tag (che
    infatti resta falso, e a guardare solo il DOM si conclude il contrario)
    ma con un ascoltatore sull'evento `ended` che riporta indietro il tempo e
    riparte. Quindi qui basta un giro solo dello spezzone.
    """
    p = paths or PATHS
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    inizio = candidate.start_seconds
    durata = seconds if seconds is not None else candidate.frames / candidate.fps
    estrai_finestra(
        p, plan.source.path, inizio,
        ["-t", f"{durata:.2f}",
         "-vf", f"fps={fps},scale={width}:-2:flags=lanczos",
         "-c:v", "libx264", "-crf", "26", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-an", "-sn", str(dest)],
        dur=durata, on_step=on_step)
    return dest if dest.is_file() and dest.stat().st_size > 0 else None


# ===========================================================================
#  Stima dei tempi
# ===========================================================================

# La stessa costante di plan.py, non una copia: averne due per la stessa
# grandezza significa che una delle due è sbagliata, e infatti qui era
# rimasto il 3.2 che plan.py documenta come misurato a macchina carica.


def estimate_seconds(plan: Plan, candidates: list[Candidate], variants: list[Variant]) -> float:
    """Quanto costera' l'anteprima, prima di lanciarla.

    La codifica si conta PER OGNI VARIANTE, non solo per il riferimento. La
    versione precedente la considerava gratis per le varianti col modello e la
    stimava a 200 fotogrammi al secondo per il riferimento, che a 1080p con
    `preset slower` non è fisicamente possibile: il totale usciva otto volte
    più basso del vero (129 secondi annunciati contro 1070 misurati). Uno
    strumento che esiste per evitare le sorprese di durata non può essere lui
    la sorpresa: chi accetta "due minuti" e ne aspetta venti non lo riapre.
    """
    frames = sum(c.frames for c in candidates)
    preparazione, costi = costi_varianti(plan, frames, variants)
    total = sum(gpu + codifica for gpu, codifica in costi)
    # Estrazione dello spezzone e montaggio dei ritagli, una volta sola.
    return total + preparazione + 5.0 * len(candidates)


def costi_varianti(plan: Plan, frames: int,
                   variants: list[Variant]) -> tuple[float, list[tuple[float, float]]]:
    """Secondi stimati per `frames` fotogrammi: l'estrazione, poi per ogni
    variante (GPU del modello, codifica). Gli stessi conti della stima
    d'insieme, per pezzo: il Confronto ci dimensiona la sua barra."""
    src_mpx = plan.source.geometry.width * plan.source.geometry.height / 1_000_000
    # La codifica dipende dai pixel in USCITA, non da quelli del sorgente.
    fattore_uscita = (plan.target_width * plan.target_height) / (1920 * 1080)
    # `plan.fps_codifica` porta gia' l'eventuale taratura della macchina.
    codifica = frames / max(0.1, plan.fps_codifica / max(0.05, fattore_uscita))
    costi = []
    for v in variants:
        gpu = 0.0
        if not v.is_reference:
            model = CATALOG[v.key]
            scala = scale_for(v.key, plan)
            throughput = (taratura.throughput(v.key, scala, mpx=src_mpx)
                          or model.throughput.get(
                              scala, min(model.throughput.values())))
            gpu = frames * src_mpx / throughput
        costi.append((gpu, codifica))
    return frames / 30.0, costi


# ===========================================================================
#  Esecuzione
# ===========================================================================

def render(
    plan: Plan, candidate: Candidate, variants: list[Variant],
    *, paths: Paths | None = None, on_step: object = None,
    on_progress: object = None, on_done: object = None,
    on_start: object = None,
) -> PreviewResult:
    """Elabora uno spezzone con tutte le varianti e scrive in PREVIEW/."""
    from . import encode as enc
    from .backend import upscale_dir
    import time

    p = paths or PATHS
    started = time.monotonic()
    # Il nome usava lo stem grezzo: due episodi omonimi in cartelle diverse
    # condividevano la cartella (lo stesso difetto che `library._cache_path`
    # documenta di aver corretto), due prove con bersaglio o CRF diversi si
    # sovrascrivevano in silenzio, e uno stem come `..` scriveva FUORI da
    # anteprime/. `safe_name` esisteva già e risolve tutto.
    from .pipeline import identita_sorgente, safe_name

    # Preset e scala cambiano il file prodotto quanto bersaglio e CRF: senza,
    # rifare il confronto con un preset diverso riscriveva `cugan.mkv` sopra il
    # precedente, e si sceglieva un modello guardando un file che non era
    # quello che si credeva. `output_name` in plan.py include il preset per la
    # stessa ragione.
    firma = (f"{plan.target_height}p-{plan.encoding.crf}-x{plan.model_scale}"
             f"-{plan.encoding.preset}"
             f"{'-dn' if plan.restoration.chain() else ''}")
    # Niente data nel nome: qui non distingue nulla e
    # faceva finire la STESSA prova rifatta il giorno dopo in una cartella
    # nuova, accumulando duplicati in anteprime/.
    base = safe_name(
        plan.source.path.stem,
        identita_sorgente(plan.source.path, p.input),
        con_data=False,
    )
    folder = p.previews / base / firma / candidate.slug
    folder.mkdir(parents=True, exist_ok=True)
    result = PreviewResult(candidate=candidate, folder=folder)

    for straccio in folder.glob("*.incomplete.mkv"):
        straccio.unlink(missing_ok=True)

    def _intera(f: Path) -> bool:
        # TOLLERANZA di 2, non uguaglianza: l'estrazione al confine del
        # seek consegna spesso un fotogramma in meno del richiesto
        # (misurato: 239 su 240) e il confronto stretto bocciava clip
        # perfette — il Confronto si rifaceva da capo a ogni click
        # (visto dall'utente). Un encode interrotto perde centinaia di
        # fotogrammi, non uno: la tolleranza non lo lascia passare.
        try:
            esito = subprocess.run(
                [str(p.ffprobe.path), "-v", "error",
                 "-select_streams", "v:0", "-count_packets",
                 "-show_entries", "stream=nb_read_packets",
                 "-of", "csv=p=0", str(f)],
                capture_output=True, text=True, check=False, timeout=30)
            pacchetti = int(esito.stdout.strip().splitlines()[0])
            return pacchetti >= max(1, candidate.frames - 2)
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            return False

    # I tempi MISURATI si conservano accanto alle clip: al riuso dalla
    # cache la proiezione sull'episodio intero resta disponibile (era il
    # dato che spariva sui riusi, notato dall'utente). Stessa cartella =
    # stessa firma di parametri, quindi il tempo resta rappresentativo.
    tempi_salvati: dict = {}
    try:
        dati_t = json.loads((folder / "timings.json").read_text())
        if isinstance(dati_t, dict):
            tempi_salvati = {k: float(v) for k, v in dati_t.items()}
    except (OSError, ValueError, TypeError):
        pass

    # CORSIA VELOCE: se ogni variante richiesta e' gia' in cassa, non si
    # estrae nemmeno — il click torna in un lampo, com'e' giusto che sia
    # quando non c'e' niente di nuovo da fare.
    pronte = {v.key: folder / f"{v.key}.mkv" for v in variants}
    if pronte and all(f.is_file() and _intera(f) for f in pronte.values()):
        result.files.update(pronte)
        for chiave_v in pronte:
            if chiave_v in tempi_salvati:
                result.tempi[chiave_v] = tempi_salvati[chiave_v]
        for v in variants:
            if callable(on_done):
                on_done(v.key, pronte[v.key])
        result.seconds = time.monotonic() - started
        return result

    with tempfile.TemporaryDirectory(prefix="animeup-prev-") as tmp:
        work = Path(tmp)
        frames = work / "src"
        frames.mkdir()

        # --- estrazione dello spezzone, VERIFICATA: qui i fotogrammi
        #     diventano il metro con cui si giudicano i modelli, e su un
        #     encode a intra-refresh il salto rapido consegnava campiture
        #     verdi al posto della scena ---
        chain = plan.restoration.chain()
        resto = ["-frames:v", str(candidate.frames)]
        if chain:
            resto += ["-vf", ",".join(chain)]
        resto += ["-an", "-sn", "-dn", "-pix_fmt", "rgb24",
                  "-c:v", "png", "-pred", "mixed", str(frames / "%08d.png")]
        estrai_finestra(p, plan.source.path, candidate.start_seconds, resto,
                        dur=candidate.frames / candidate.fps,
                        on_step=on_step if callable(on_step) else None)

        if not any(frames.glob("*.png")):
            return result

        # Toccare una spunta mentre il Confronto lavora fa ripartire lo
        # script di Streamlit, e il giro muore a meta' (successo). La
        # difesa e' rendere il giro RIPRENDIBILE: ogni variante si scrive
        # in modo atomico (temp + rename: se il file esiste, e' intero) e
        # le varianti gia' prodotte con questi parametri si riusano dopo
        # una verifica a conteggio pacchetti — cosi' l'interruzione costa
        # solo la variante in volo, e ricliccare Genera riparte da li'.
        for variant in variants:
            # Prima di `on_step`, che passa anche durante l'estrazione (il
            # ripiego lento): da qui in poi si lavora alla variante.
            if callable(on_start):
                on_start(variant.key)
            if on_step:
                on_step(variant.label)
            da = time.monotonic()
            out = folder / f"{variant.key}.mkv"
            if out.is_file() and _intera(out):
                # Gia' fatta in un giro precedente: si recupera anche il
                # tempo misurato allora, se conservato.
                result.files[variant.key] = out
                if variant.key in tempi_salvati:
                    result.tempi[variant.key] = tempi_salvati[variant.key]
                if callable(on_done):
                    on_done(variant.key, out)
                continue
            provvisorio = out.with_name(f"{variant.key}.incomplete.mkv")
            if variant.is_reference:
                enc.encode_segment(plan, frames, provvisorio, paths=p)
            else:
                up = work / variant.key
                upscale_dir(
                    frames, up, scale=scale_for(variant.key, plan),
                    model=variant.key, log=plan.log, paths=p,
                    # Il conteggio dei fotogrammi prodotti: è ciò che
                    # permette alla barra del Confronto una percentuale VERA
                    # invece di sembrare ferma per due minuti.
                    on_progress=on_progress if callable(on_progress) else None,
                )
                # Il conteggio puo' fermarsi qualche fotogramma prima (visto:
                # 243 su 250): l'upscale e' finito quando torna, e da qui
                # comincia la codifica.
                if callable(on_progress):
                    on_progress(1, 1)
                enc.encode_segment(plan, up, provvisorio, paths=p)
            if provvisorio.is_file():
                os.replace(provvisorio, out)
            result.tempi[variant.key] = time.monotonic() - da
            if out.is_file():
                result.files[variant.key] = out
            if callable(on_done):
                on_done(variant.key, out if out.is_file() else None)

    result.seconds = time.monotonic() - started
    try:
        unione = {**tempi_salvati, **result.tempi}
        (folder / "timings.json").write_text(json.dumps(unione, indent=2))
    except OSError:
        pass
    return result


# L'ordine in cui si leggono le varianti, ovunque: nel foglio 1:1, nella
# tabella dei tempi, negli indicatori. Prima il riferimento, poi i modelli
# dal piu' leggero al piu' pesante — animevideov3 prima di CUGAN (chiesto
# dall'utente il 12/08). Un ordine solo, deciso qui, o le tre viste si
# contraddicono e il confronto diventa un esercizio di memoria.
ORDINE = ("original", "animevideov3", "cugan", "cugan-conservative", "cugan-denoise")

# Versione della REGOLA con cui si scelgono gli spezzoni. Si alza quando la
# scelta cambia, cosi' le casse scritte con la regola vecchia non vengono
# riusate. 2 = distanza minima fra spezzoni dello stesso tipo (12/08).
# 3 = la distanza minima vale anche verso i lotti PRECEDENTI, non
# solo dentro lo stesso giro.
# 4 = la distanza si rapporta a quanti spezzoni esisteranno in tutto
# (durata/N) invece di essere un ottavo fisso, che saturava il file al
# secondo lotto.
REGOLA_SCELTA = 4


def ordine_lettura(chiavi) -> list[str]:
    """Le chiavi presenti, nell'ordine di ORDINE; le ignote in coda."""
    noti = [k for k in ORDINE if k in chiavi]
    return noti + [k for k in chiavi if k not in ORDINE]


LATO_TESSERA = 64
# Residuo minimo che una tessera deve avere GIA' SUL RIFERIMENTO perche' ci
# sia qualcosa da misurare.
#
# Nell'anime le aree piatte sono piatte DAVVERO — campiture a tinta unita e
# gradienti lentissimi — e l'ottavo piu' uniforme del fotogramma ha residuo
# ZERO: la differenza con la sfocatura sta sotto il livello e si tronca. Li'
# ogni modello dava zero, il rapporto non si poteva calcolare, e l'indicatore
# spariva dalla pagina (3 dei 7 confronti in archivio; nel Confronto vero
# fatto il 12/08 `metriche` usciva vuoto). Si portava dietro anche il
# dettaglio fine, che invece funzionava.
#
# Filtrare sulla VARIANZA non basta e sarebbe stato un secondo errore: un
# gradiente dolce misurato qui aveva varianza 11.9 e residuo comunque 0.000.
# Il discriminante e' il residuo stesso. Sopra 0.1 (circa quaranta pixel che
# differiscono di un livello su una tessera da 64x64, molto sopra il gradino
# di quantizzazione a 0.0156) i modelli si separano in modo stabile su 6 dei
# 7 casi in archivio; il settimo resta senza zone e lo dichiara, invece di
# fabbricare il rapporto 12x che veniva fuori da due sole tessere.
RESIDUO_MINIMO = 0.1
# Sotto questo numero di zone la mediana non e' una misura. Meglio nessun
# numero che un numero costruito su una manciata di tessere.
ZONE_MINIME = 8


def _residuo(grigio, x: int, y: int, lato: int = LATO_TESSERA) -> float:
    """Quanta alta frequenza c'e' in una tessera: cio' che una sfocatura
    leggera si porterebbe via."""
    from PIL import ImageChops, ImageFilter

    t = grigio.crop((x, y, x + lato, y + lato))
    r = ImageChops.difference(t, t.filter(ImageFilter.GaussianBlur(1.0)))
    dati = list(r.getdata())
    return (sum(v * v for v in dati) / max(1, len(dati))) ** 0.5


def _zone_piatte(im, *, lato: int = LATO_TESSERA) -> list[tuple[int, int]]:
    """Dove misurare il rumore: le zone piu' uniformi FRA QUELLE che qualcosa
    da misurare ce l'hanno.

    Le posizioni si scelgono UNA VOLTA SOLA, sul riferimento, e si riusano
    identiche per ogni modello. Sceglierle variante per variante — com'era —
    significa confrontare numeri presi su pezzi diversi dell'immagine, cioe'
    non confrontarli affatto.
    """
    import statistics

    grigio = im.convert("L")
    w, h = grigio.size
    tessere = []
    for y in range(0, max(1, h - lato), lato):
        for x in range(0, max(1, w - lato), lato):
            dati = list(grigio.crop((x, y, x + lato, y + lato)).getdata())
            media = sum(dati) / len(dati)
            # Quasi nero e bruciato: li' non c'e' segnale per nessuno.
            if media < 25 or media > 235:
                continue
            if _residuo(grigio, x, y, lato) <= RESIDUO_MINIMO:
                continue
            tessere.append((statistics.pvariance(dati), x, y))
    if len(tessere) < ZONE_MINIME:
        return []
    # Fra quelle misurabili, le piu' piatte: e' li' che si vede se un modello
    # aggiunge grana o al contrario spiana.
    tessere.sort(key=lambda z: z[0])
    quante = max(ZONE_MINIME, len(tessere) // 8)
    return [(x, y) for _, x, y in tessere[:quante]]


def _indicatori(im, zone: list[tuple[int, int]] | None = None,
                *, lato: int = LATO_TESSERA) -> tuple[float, float | None]:
    """(dettaglio fine, rumore nelle aree piatte) di UN fotogramma.

    Due numeri che non pretendono di dare un voto: servono a confrontare i
    modelli FRA LORO sullo stesso fotogramma, perche' un originale ad alta
    risoluzione con cui confrontarsi non esiste — si stanno inventando pixel.

    DETTAGLIO FINE: energia di cio' che una sfocatura leggera porterebbe via,
    cioe' contorni e micro-struttura. Un modello che "plastifica" ne ha meno.

    RUMORE NELLE AREE PIATTE: lo stesso residuo, misurato pero' solo nelle
    `zone` — le stesse per tutte le varianti, vedi `_zone_piatte`. Senza zone
    utilizzabili torna `None`, che vuol dire "non misurato": e' diverso da
    zero, e chi mostra i numeri deve poterlo dire.
    """
    import statistics
    from PIL import ImageChops, ImageFilter

    grigio = im.convert("L")
    alta = ImageChops.difference(grigio, grigio.filter(ImageFilter.GaussianBlur(1.2)))
    d = list(alta.getdata())
    dettaglio = (sum(v * v for v in d) / max(1, len(d))) ** 0.5

    if not zone:
        return dettaglio, None
    return dettaglio, statistics.median(
        [_residuo(grigio, x, y, lato) for x, y in zone])


def zona_dettaglio(reference, size: int = 480) -> tuple[int, int]:
    """L'angolo del ritaglio: la zona a dettaglio massimo del riferimento.

    Si cerca su una versione ridotta per non scandire milioni di pixel, poi
    si riporta alla scala piena. Una funzione sola per il foglio finale e per
    i ritagli provvisori del test in corso, cosi' mostrano la stessa zona."""
    from PIL import ImageChops, ImageFilter

    w, h = reference.size
    half = size // 2
    small = reference.convert("L").resize((w // 8, h // 8))
    edges = ImageChops.difference(small, small.filter(ImageFilter.GaussianBlur(2)))
    step = max(1, size // 16)
    best, bx, by = -1.0, w // 2, h // 2
    for y in range(0, small.height - size // 8, step):
        for x in range(0, small.width - size // 8, step):
            box = edges.crop((x, y, x + size // 8, y + size // 8))
            score = sum(box.getdata())
            if score > best:
                best, bx, by = score, x * 8, y * 8
    bx = max(0, min(w - size, bx + half - size // 2))
    by = max(0, min(h - size, by + half - size // 2))
    return bx, by


def ritaglio_provvisorio(video: Path, key: str, candidate: Candidate,
                         zona: tuple[int, int] | None = None, *, size: int = 480,
                         paths: Paths | None = None) -> tuple[Path | None, tuple[int, int] | None]:
    """Il ritaglio 1:1 di UNA versione appena finita, mentre il test va
    avanti: la pagina la mostra subito invece di aspettare tutto lo spezzone
    (tavola CF2b). La zona si sceglie sulla prima versione pronta — il
    riferimento, che si fa per primo — e si riusa per le altre: la stessa
    che `crop_sheet` scegliera' alla fine."""
    from PIL import Image

    p = paths or PATHS
    with tempfile.TemporaryDirectory(prefix="animeup-crop-") as tmp:
        shot = Path(tmp) / f"{key}.png"
        run_stderr([
            str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y",
            "-i", str(video), "-vf", f"select=eq(n\\,{candidate.frames // 2})",
            "-frames:v", "1", str(shot),
        ])
        if not shot.is_file():
            return None, zona
        im = Image.open(shot).convert("RGB")
        if zona is None:
            zona = zona_dettaglio(im, size)
        dest = video.parent / f"crop_{key}.png"
        try:
            im.crop((zona[0], zona[1], zona[0] + size, zona[1] + size)).save(dest)
        except OSError:
            return None, zona
    return dest, zona


def crop_sheet(
    result: PreviewResult, plan: Plan, *, size: int = 480,
    paths: Paths | None = None,
) -> Path | None:
    """Foglio di confronto a 1:1 reale, l'unica cosa onesta da vedere a schermo.

    Ritaglia la stessa zona da ogni variante, a dimensione nativa: a 1:1
    nessuna scala può nascondere gli artefatti. La zona si sceglie da sola,
    prendendo il punto a dettaglio più alto del fotogramma.
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    p = paths or PATHS
    if not result.files:
        return None

    grabbed: dict[str, Image.Image] = {}
    with tempfile.TemporaryDirectory(prefix="animeup-sheet-") as tmp:
        middle = result.candidate.frames // 2
        for key, video in result.files.items():
            shot = Path(tmp) / f"{key}.png"
            run_stderr([
                str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y",
                "-i", str(video), "-vf", f"select=eq(n\\,{middle})",
                "-frames:v", "1", str(shot),
            ])
            if shot.is_file():
                grabbed[key] = Image.open(shot).convert("RGB").copy()

    if not grabbed:
        return None

    # Gli indicatori si calcolano QUI: i fotogrammi sono gia' estratti e in
    # memoria, quindi costano una manciata di millisecondi. Rifarli altrove
    # significherebbe una seconda estrazione per gli stessi pixel.
    reference = grabbed.get("original") or next(iter(grabbed.values()))
    zone = _zone_piatte(reference)
    grezzi = {k: _indicatori(v, zone) for k, v in grabbed.items()}
    base = grezzi.get("original")
    if base:
        # I due indicatori si normalizzano SEPARATAMENTE: prima bastava che
        # uno dei due fosse zero per far sparire anche l'altro, e siccome il
        # rumore era quasi sempre zero (vedi RESIDUO_MINIMO) la tabella non
        # si vedeva mai. `None` = non misurato, e chi disegna lo dice.
        def _rapporto(valore, riferimento):
            if valore is None or not riferimento:
                return None
            return valore / riferimento

        result.metriche = {
            k: (_rapporto(v[0], base[0]), _rapporto(v[1], base[1]))
            for k, v in grezzi.items()}

    bx, by = zona_dettaglio(reference, size)

    for key, im in grabbed.items():
        singolo = result.folder / f"crop_{key}.png"
        try:
            im.crop((bx, by, bx + size, by + size)).save(singolo)
            result.crops[key] = singolo
        except OSError:
            pass

    order = ordine_lettura(grabbed)
    cols = min(2, len(order))
    rows = -(-len(order) // cols)
    label_h = 26
    sheet = Image.new("RGB", (size * cols, (size + label_h) * rows), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    # Font vero e leggibile al posto del bitmap di serie di PIL (~10px,
    # "titoletti piccoli", utente). Helvetica c'e' su ogni macOS; se un
    # giorno mancasse si ripiega sul default senza rompere il foglio.
    try:
        from PIL import ImageFont
        carattere = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", 15)
    except OSError:
        carattere = None
    for i, key in enumerate(order):
        cx, cy = (i % cols) * size, (i // cols) * (size + label_h)
        sheet.paste(grabbed[key].crop((bx, by, bx + size, by + size)), (cx, cy + label_h))
        name = (t("mot.preview.originale_ingrandito") if key == "original"
                else CATALOG[key].label)
        draw.text((cx + 6, cy + 6), name, fill=(235, 235, 235),
                  font=carattere)

    dest = result.folder / "comparison_1to1.png"
    sheet.save(dest)
    result.crop_sheet = dest
    return dest


# ===========================================================================
#  Confronto
# ===========================================================================

def comparison_tool() -> Path | None:
    """video-compare, se installato. Non è una dipendenza della pipeline."""
    # Anche nelle cartelle di Homebrew: l'app lancia il server con il PATH
    # minimo di macOS (/usr/bin:/bin...), dove `which` da solo non lo trova
    # e il confronto diceva «non installato» a chi
    # l'aveva in /opt/homebrew/bin (segnalato dall'utente).
    found = shutil.which("video-compare") or shutil.which(
        "video-compare", path="/opt/homebrew/bin:/usr/local/bin")
    return Path(found) if found else None


def open_comparison(left: Path, right: Path) -> tuple[bool, str]:
    """Apre due file affiancati in video-compare.

    Ritorna (riuscito, messaggio). Senza video-compare non si ripiega su
    altri riproduttori: due finestre separate non sono un confronto, e
    l'interfaccia in quel caso non offre il pulsante ma spiega come
    installarlo (deciso con l'utente).

    `--high-dpi`: un pixel del video e' un pixel dello schermo. Senza, sul
    Retina ogni pixel ne occupava quattro e il risultato si vedeva
    ingrandito e morbido, cioe' peggio di com'e'. `--window-fit-display`:
    la finestra mostra il fotogramma intero e lo riduce solo se non ci sta
    (un 4K su un MacBook); per i dettagli c'e' lo zoom con la rotella.
    """
    tool = comparison_tool()
    if not tool:
        return False, t("mot.preview.nessuno_strumento")
    # Una sessione sua: chiudendo l'app per macOS (che ferma il server e il
    # suo gruppo di processi) il confronto aperto restava ucciso.
    subprocess.Popen(
        [str(tool), "--high-dpi", "--window-fit-display", str(left), str(right)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True, t("mot.preview.aperto_video_compare", sinistra=left.name,
                   destra=right.name)


def quota_dedup(plan) -> tuple[float, str]:
    """(quanta deduplica applicare alla proiezione, da dove viene).

    Tre casi, in ordine di forza: misurata su QUESTO file (la mappa esiste
    gia' su disco), attesa dai file simili gia' lavorati, oppure nessuna —
    che e' anche il caso della deduplica spenta, dove ignorarla e' giusto.

    La provenienza e' un codice e non la frase: il risultato resta in
    sessione, e la frase si scrive al disegno nella lingua di quel momento
    (vedi `_tabella_confronto` nell'interfaccia).
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
