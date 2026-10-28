#!/usr/bin/env python
"""Test di regressione.

Perche' esistono: in una sola sessione di sviluppo tre correzioni ne hanno
rotta un'altra. Ogni caso qui sotto corrisponde a un bug REALMENTE avvenuto o
a un'assunzione su cui poggia la pipeline. Vanno eseguiti dopo ogni modifica.

    ./animeup test        (oppure)     .venv/bin/python tests/run.py

Niente dipendenze esterne: asserzioni e un riepilogo.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
from animeup import dedup, library  # noqa: E402
from animeup.models import CATALOG, recommend  # noqa: E402
from animeup.paths import PATHS, MissingToolError  # noqa: E402
from animeup.pipeline import safe_name  # noqa: E402
from animeup.plan import build_plan, output_name  # noqa: E402
from animeup.probe import Timebase, probe_source  # noqa: E402
from animeup import i18n  # noqa: E402

# I casi controllano anche testi a schermo, scritti in italiano: la lingua si
# fissa qui, invece di dipendere da cosa ha scelto l'utente nella sidebar.
i18n.imposta("it")
# Anche per i sottoprocessi (`./animeup ...`): leggono la lingua da soli, e
# senza questo parlerebbero quella salvata nelle impostazioni dell'utente.
os.environ["ANIMEUP_LANG"] = "it"

# I campioni veri sono rip di anime con tracce fansub: restano sul disco di
# chi sviluppa e non si pubblicano. Dove mancano (un clone pulito, la CI) si
# usano gli equivalenti sintetici di `tests/fixtures.py`, con gli stessi nomi.
# ANIMEUP_TEST_FIXTURES=1 li forza anche dove i veri ci sono, per provare
# quel ramo senza spostare niente.
CAMPIONI_VERI = ROOT / "_WIP" / "_TESTING"
SINTETICI = (os.environ.get("ANIMEUP_TEST_FIXTURES") == "1"
             or not CAMPIONI_VERI.is_dir())
CAMPIONI = fixtures.CARTELLA if SINTETICI else CAMPIONI_VERI
FFMPEG = str(PATHS.ffmpeg.path)

_casi: list = []


def caso(nome: str):
    def dec(fn):
        _casi.append((nome, fn))
        return fn
    return dec


def ffmpeg(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", *args],
                   check=True, capture_output=True)


class Saltato(Exception):
    """Il caso non puo' girare qui. Si conta a parte: non e' un passato."""


@functools.cache
def _gpu_assente() -> str | None:
    """Perche' l'upscaler non puo' girare su questa macchina, o None.

    Sui runner macOS di GitHub (macchine virtuali) Vulkan->Metal spesso non
    trova un dispositivo usabile. Non si indovina dal modello di macchina: si
    prova davvero, su un'immagine 16x16, una volta per corsa. Il binario puo'
    anche uscire con 0 senza scrivere niente, quindi conta il file prodotto.
    ANIMEUP_TEST_NO_GPU=1 simula il guasto.
    """
    if os.environ.get("ANIMEUP_TEST_NO_GPU") == "1":
        return "GPU assente (simulata con ANIMEUP_TEST_NO_GPU=1)"
    with tempfile.TemporaryDirectory() as t:
        src, dst = Path(t) / "p.png", Path(t) / "q.png"
        ffmpeg("-f", "lavfi", "-i", "color=gray:s=16x16", "-frames:v", "1", str(src))
        try:
            esito = subprocess.run(
                [str(PATHS.realesrgan.path), "-i", str(src), "-o", str(dst),
                 "-n", "realesr-animevideov3", "-s", "2", "-m", str(PATHS.models)],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired, MissingToolError) as exc:
            return f"upscaler non eseguibile: {exc}"
        if esito.returncode or not dst.is_file() or not dst.stat().st_size:
            righe = esito.stderr.strip().splitlines()
            return "nessuna GPU usabile dall'upscaler" + (f": {righe[-1]}" if righe else "")
    return None


def serve_gpu() -> None:
    """In testa a ogni caso che esegue DAVVERO realesrgan o realcugan.

    Oggi nessun caso lo fa (quelli sull'upscaler usano un binario finto o si
    fermano prima): la sonda parte solo alla prima chiamata, quindi finche'
    resta cosi' non costa niente."""
    if (motivo := _gpu_assente()) is not None:
        raise Saltato(motivo)


# ===========================================================================
#  Analisi dei tempi
# ===========================================================================

@caso("CFR non viene scambiato per VFR")
def _() -> None:
    """La v5 dichiarava VFR ogni file a 23.976, per un arrotondamento al ms."""
    for nome in ("TEST-CFR-23-976fps---17s.mkv", "TEST-CFR-23-976fps---2min.mkv",
                 "TEST-CFR-24fps---2min.mkv"):
        r = probe_source(CAMPIONI / nome, with_fields=False,
                         with_geometry=False)
        assert r.timing.mode is Timebase.CFR, f"{nome}: atteso CFR, ottenuto {r.timing.mode}"


@caso("il framerate misurato prevale su quello dichiarato")
def _() -> None:
    """Due campioni dichiarano 29.97 nel container ma sono 23.976 e 24."""
    attesi = {
        "TEST-CFR-23-976fps---2min.mkv": Fraction(24000, 1001),
        "TEST-CFR-24fps---2min.mkv": Fraction(24, 1),
    }
    for nome, atteso in attesi.items():
        r = probe_source(CAMPIONI / nome, with_fields=False,
                         with_geometry=False)
        assert r.timing.fps == atteso, f"{nome}: atteso {atteso}, ottenuto {r.timing.fps}"
        assert r.timing.container_disagrees, f"{nome}: il disaccordo col container non è segnalato"


@caso("un video di pochissimi fotogrammi non fa esplodere l'analisi")
def _() -> None:
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "corto.mkv"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=24", "-frames:v", "3",
               "-c:v", "libx264", str(f))
        r = probe_source(f, with_fields=False, with_geometry=False)
        assert r.timing.packets == 3, f"attesi 3 pacchetti, {r.timing.packets}"


# ===========================================================================
#  Geometria e pianificazione
# ===========================================================================

@caso("i pixel non quadri non deformano l'uscita")
def _() -> None:
    """710x480 con SAR 480:527: l'uscita deve conservare il rapporto reale."""
    r = probe_source(CAMPIONI / "TEST-CFR-23-976fps---2min.mkv", with_fields=False)
    assert r.geometry.anamorphic, "il campione dovrebbe avere pixel non quadri"
    p = build_plan(r, target_height=1080)
    atteso = float(r.geometry.dar)
    ottenuto = p.target_width / p.target_height
    assert abs(atteso - ottenuto) / atteso < 0.02, \
        f"aspect ratio deformato: atteso {atteso:.3f}, ottenuto {ottenuto:.3f}"


@caso("le dimensioni d'uscita sono sempre pari")
def _() -> None:
    """Una dimensione dispari fa fallire yuv420p."""
    for nome in ("TEST-CFR-23-976fps---17s.mkv", "TEST-CFR-23-976fps---2min.mkv",
                 "clip20s.mkv"):
        p = build_plan(probe_source(CAMPIONI / nome, with_fields=False))
        assert p.target_width % 2 == 0 and p.target_height % 2 == 0, \
            f"{nome}: {p.target_width}x{p.target_height} ha una dimensione dispari"


@caso("la scala scelta raggiunge sempre il bersaglio")
def _() -> None:
    from animeup.plan import PlanError
    for nome in ("TEST-CFR-23-976fps---17s.mkv", "clip20s.mkv"):
        r = probe_source(CAMPIONI / nome, with_fields=False)
        for altezza in (720, 1080, 1440):
            try:
                p = build_plan(r, target_height=altezza)
            except PlanError:
                continue          # bersaglio non più grande del sorgente
            assert p.model_height >= p.target_height, \
                f"{nome}@{altezza}: il modello produce {p.model_height}, bersaglio {p.target_height}"


@caso("il consiglio sul modello riflette il confronto fatto a occhio")
def _() -> None:
    """Tre fasce, non due, e vengono da lavorazioni reali guardate a 1:1:
    720p e 400p vinte da CUGAN, 288p vinta nettamente da animevideov3. In
    mezzo non c'e' un vincitore, e il consiglio deve DIRLO invece di fingere
    una certezza: è la stessa regola per cui l'analisi del dettaglio è
    stata tolta."""
    for h in (1080, 720, 576):
        r = recommend(h)
        assert r.model == "cugan" and r.sicuro, f"{h}p: {r.model} sicuro={r.sicuro}"
    for h in (360, 288, 240):
        r = recommend(h)
        assert r.model == "animevideov3" and r.sicuro, f"{h}p: {r.model}"
    for h in (480, 400):
        r = recommend(h)
        assert not r.sicuro, f"{h}p è dato per certo, ma è la fascia dubbia"
        assert r.alternative, f"{h}p: manca l'alternativa da provare"


@caso("il nome d'uscita conserva l'originale e distingue i parametri")
def _() -> None:
    stem = "[Gruppo] Serie - 01 [720p][ABC12345]"
    a = output_name(stem, target_height=1080, scale=3, model_tag="cugan", crf=18)
    b = output_name(stem, target_height=1080, scale=3, model_tag="animevideov3", crf=18)
    assert stem in a, "il nome originale non è conservato"
    assert a != b, "due modelli diversi producono lo stesso nome"


# ===========================================================================
#  Deduplica
# ===========================================================================

@caso("la mappa di deduplica è internamente coerente")
def _() -> None:
    diffs = [0.0, 0.0, 200.0, 0.0, 0.0, 0.0, 300.0, 0.0]
    m = dedup.build_map(diffs, bit_depth=8, max_run=5)
    assert m.total == len(diffs) + 1
    assert len(m.source_of) == m.total
    tenuti = set(m.keep)
    assert m.source_of[0] == 0, "il primo fotogramma deve puntare a se stesso"
    for i, s in enumerate(m.source_of):
        assert s in tenuti, f"il fotogramma {i} punta a {s}, che non viene elaborato"
        assert s <= i, f"il fotogramma {i} punta in avanti, a {s}"


@caso("il tetto agli scarti consecutivi viene rispettato")
def _() -> None:
    m = dedup.build_map([0.0] * 100, bit_depth=8, max_run=5)
    assert m.longest_run <= 5, f"sequenza da {m.longest_run}, tetto 5"


@caso("nessun fotogramma con movimento reale viene scartato")
def _() -> None:
    diffs = [0.0, 1.0, 90.0, 0.0, 2.0, 150.0, 0.0]
    m = dedup.build_map(diffs, bit_depth=8)
    esito = dedup.audit(diffs, m)
    assert esito.ok, f"violazioni: {esito.violations}"


@caso("la deriva accumulata forza un nuovo riferimento")
def _() -> None:
    """Dieci scarti da 10 sommano 100: oltre soglia, non devono passare."""
    m = dedup.build_map([10.0] * 10, bit_depth=8, max_run=50)
    esito = dedup.audit([10.0] * 10, m)
    assert esito.ok, "una dissolvenza lenta resterebbe congelata"


@caso("un solo fotogramma non rompe la mappa")
def _() -> None:
    m = dedup.build_map([], bit_depth=8)
    assert m.total == 1 and m.keep == [0] and m.source_of == [0]


# ===========================================================================
#  Verifica dei fotogrammi
# ===========================================================================

@caso("i tag colore arrivano davvero nel file codificato")
def _() -> None:
    """I flag ffmpeg scrivevano solo la matrice: trasferimento e primarie
    restavano 'unknown' e il lettore tirava a indovinare."""
    import subprocess as sp
    from animeup import encode as enc
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    plan = build_plan(r)
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "f"
        d.mkdir()
        ffmpeg("-f", "lavfi", "-i", "color=red:s=1280x720:r=24", "-frames:v", "3",
               "-pix_fmt", "rgb24", str(d / "%08d.png"))
        out = Path(t) / "o.mkv"
        enc.encode_segment(plan, d, out)
        got = sp.run([str(PATHS.ffprobe.path), "-v", "error", "-select_streams", "v:0",
                      "-show_entries",
                      "stream=color_space,color_transfer,color_primaries",
                      "-of", "csv=p=0", str(out)],
                     capture_output=True, text=True).stdout.strip()
    assert "unknown" not in got, f"tag incompleti: {got}"


@caso("il conteggio dei fotogrammi non viene confuso con la geometria")
def _() -> None:
    """verify_output riconosceva i campi confrontandoli con i valori attesi:
    su una geometria sbagliata la larghezza faceva da conteggio."""
    import subprocess as sp
    from animeup import encode as enc
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    plan = build_plan(r)
    with tempfile.TemporaryDirectory() as t:
        finto = Path(t) / "sbagliato.mkv"
        # geometria diversa da quella attesa dal piano, 30 fotogrammi
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1904x1080:r=24", "-frames:v", "30",
               "-c:v", "libx264", "-preset", "ultrafast", str(finto))
        object.__setattr__(plan, "output", finto)
        fotogrammi, geometria = enc.verify_output(plan, 30)
    assert fotogrammi == 30, f"conteggio {fotogrammi} invece di 30"
    assert geometria == "1904x1080", f"geometria {geometria}"








@caso("un sorgente interlacciato viene segnalato ma non trattato")
def _() -> None:
    """Il rilevamento non distingue telecine da interlacciato, e la cura
    sbagliata distrugge i fotogrammi originali: si segnala e basta."""
    from animeup.probe import FieldMode, FieldReport
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    r.fields = FieldReport(FieldMode.INTERLACED, 0, 90, 0, 0, 0, 100, 0.9)
    p = build_plan(r, target_height=1080)
    assert not p.restoration.chain(), "non deve applicare nessun filtro da solo"
    assert any("interlacciato" in n for n in p.restoration.notes), \
        f"nessuna segnalazione: {p.restoration.notes}"


@caso("una lavorazione che non ci sta sul disco viene rifiutata")
def _() -> None:
    from animeup.pipeline import Job, JobError
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    p = build_plan(r)
    p.est_peak_disk_gb = 999_999.0
    try:
        Job(p).run()
    except JobError as exc:
        assert "spazio insufficiente" in str(exc)
        return
    raise AssertionError("è partita comunque e riempirebbe il disco")


@caso("la verifica della deduplica intercetta gli sfasamenti")
def _() -> None:
    """La versione precedente era una tautologia: zero violazioni su
    ventimila mappe casuali, e non leggeva mai source_of."""
    import copy
    diffs = [0.0, 0.0, 200.0, 0.0, 0.0, 0.0, 300.0, 0.0]
    base = dedup.build_map(diffs, bit_depth=8, max_run=5)
    assert dedup.audit(diffs, base).ok, "falso positivo su una mappa sana"

    sabotaggi = {
        "sfasato di uno": lambda m: m.source_of.__setitem__(
            slice(None), [0] + m.source_of[:-1]),
        "punta a un frame non elaborato": lambda m: m.source_of.__setitem__(3, 99),
        "punta in avanti": lambda m: m.source_of.__setitem__(1, 5),
        "troncato": lambda m: m.source_of.__setitem__(slice(None), m.source_of[:-2]),
    }
    for nome, rompi in sabotaggi.items():
        m = copy.deepcopy(base)
        rompi(m)
        assert not dedup.audit(diffs, m).ok, f"sfuggito: {nome}"


@caso("nessun falso positivo della verifica su mappe legittime")
def _() -> None:
    import random
    random.seed(7)
    for _ in range(200):
        diffs = [random.choice([0.0, 1.0, 5.0, 30.0, 200.0])
                 for _ in range(random.randint(0, 40))]
        m = dedup.build_map(diffs, bit_depth=8, max_run=random.choice([2, 5, 10]))
        assert dedup.audit(diffs, m).ok, f"falso positivo su {diffs[:6]}"


@caso("i nomi di cartella sono privi di caratteri che rompono i modelli")
def _() -> None:
    for stem in ("[Gruppo] Serie - 01 [720p][ABC12345]",
                 "Serie con 'apostrofo' e \"virgolette\"",
                 "Serie * con ? caratteri {strani}",
                 "Série avec des accents éàü"):
        n = safe_name(stem, stem, 0)
        assert not any(c in n for c in "[]{}*?"), f"{stem!r} -> {n!r}"


@caso("due nomi diversi non collidono una volta ripuliti")
def _() -> None:
    a = safe_name("[A] Serie [720p]")
    b = safe_name("(A) Serie (720p)")
    assert a != b, f"collisione: {a!r}"


@caso("il SAR minore di 1 espande, non comprime")
def _() -> None:
    """Comprimendo si buttava via il 9% delle colonne prima dell'upscale."""
    r = probe_source(CAMPIONI / "TEST-CFR-23-976fps---2min.mkv", with_fields=False)
    g = r.geometry
    assert g.display_width >= g.width, \
        f"larghezza compressa: {g.width} -> {g.display_width}"
    assert g.display_height >= g.height, \
        f"altezza compressa: {g.height} -> {g.display_height}"


@caso("la profondita' di bit si deduce dal formato pixel")
def _() -> None:
    from animeup.probe import _bit_depth
    attesi = {"yuv420p": 8, "yuv420p10le": 10, "yuv444p10le": 10,
              "yuv420p12le": 12, "rgb48be": 16, "rgb24": 8}
    for pix, atteso in attesi.items():
        got = _bit_depth({"pix_fmt": pix})
        assert got == atteso, f"{pix}: {got} invece di {atteso}"


@caso("due file omonimi in cartelle diverse non condividono la cache")
def _() -> None:
    from animeup.library import _cache_path
    with tempfile.TemporaryDirectory() as t:
        a, b = Path(t) / "A" / "ep01.mkv", Path(t) / "B" / "ep01.mkv"
        a.parent.mkdir(); b.parent.mkdir()
        a.touch(); b.touch()
        assert _cache_path(a, PATHS) != _cache_path(b, PATHS), \
            "stessa cache per file diversi"


@caso("un nome lunghissimo non fa fallire la cache")
def _() -> None:
    from animeup.library import _cache_path
    with tempfile.TemporaryDirectory() as t:
        lungo = Path(t) / ("x" * 200 + ".mkv")
        nome = _cache_path(lungo, PATHS).name
        assert len(nome.encode()) < 240, f"nome di cache da {len(nome)} byte"


@caso("il Counter dei duplicati sopravvive al giro su disco")
def _() -> None:
    from collections import Counter
    from animeup.probe import DuplicateReport
    r = probe_source(CAMPIONI / "TEST-CFR-23-976fps---17s.mkv", with_fields=False,
                     with_geometry=False)
    r.duplicates = DuplicateReport(1000, 700, 300, Counter({1: 200, 2: 150, 3: 50}))
    ricostruito = library._decode(library._encode(r), r.path)
    assert ricostruito.duplicates is not None, "i duplicati si perdono"
    assert dict(ricostruito.duplicates.run_lengths) == {1: 200, 2: 150, 3: 50}, \
        f"conteggi corrotti: {dict(ricostruito.duplicates.run_lengths)}"
    # la lunghezza più frequente è 1 (200 occorrenze), non 2
    assert ricostruito.duplicates.animation_step == 1


@caso("la cartella di lavoro non collide fra file omonimi")
def _() -> None:
    a = safe_name("ep01", "/percorso/A/ep01.mkv", 0)
    b = safe_name("ep01", "/percorso/B/ep01.mkv", 0)
    assert a != b, f"collisione: {a}"


@caso("i caratteri che rompono ffmpeg spariscono dal nome di lavoro")
def _() -> None:
    """Il % è il più insidioso: il muxer image2 lo legge come segnaposto."""
    for stem in ("Serie al 50% - 01", "JoJo's Bizarre Adventure",
                 "[Gruppo] Serie [720p]", 'Serie "tra virgolette"'):
        n = safe_name(stem, stem, 0)
        assert not any(c in n for c in "%[]{}*?'\"`$"), f"{stem!r} -> {n!r}"


# ===========================================================================
#  Ripresa e regressioni
# ===========================================================================

@caso("i fotogrammi estratti sopravvivono a un cambio di codifica")
def _() -> None:
    """Con un'unica firma, cambiare preset o CRF cancellava ore di estrazione."""
    from animeup.pipeline import _firma_estrazione, _signature
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    a = build_plan(r, crf=18, preset="slower")
    b = build_plan(r, crf=22, preset="medium")
    assert _firma_estrazione(a) == _firma_estrazione(b), \
        "i fotogrammi verrebbero riestratti per un cambio di sola codifica"
    assert _signature(a) != _signature(b), \
        "due codifiche diverse condividerebbero gli stessi segmenti"


@caso("la firma non cambia al variare dello spazio libero")
def _() -> None:
    """chunk_size dipende dal disco: in firma buttava via il lavoro da solo."""
    from animeup.pipeline import _signature
    # serve un file abbastanza lungo: su un clip corto la dimensione del
    # blocco viene comunque limitata al numero di fotogrammi e i due casi
    # coinciderebbero senza dimostrare nulla
    r = probe_source(CAMPIONI / "TEST-VFR-approx-23-976fps---7min.mp4",
                     with_fields=False)
    a = build_plan(r, peak_disk_gb=8)
    b = build_plan(r, peak_disk_gb=100)
    assert a.chunk_size != b.chunk_size, "il caso di prova non è significativo"
    assert _signature(a) == _signature(b), \
        "la firma cambia con lo spazio libero e invalida il lavoro svolto"


@caso("i segmenti si riusano solo se coprono lo stesso intervallo")
def _() -> None:
    """Riusandoli per numero d'ordine, cambiare la dimensione dei blocchi
    rimontava fotogrammi duplicati e fuori ordine."""
    import inspect
    from animeup import pipeline
    # Sul MODULO e non su un metodo preciso: legandolo a `Job.run` il caso
    # diventava verde/rosso a seconda di come è spezzato il metodo, non di
    # cosa fa il codice.
    sorgente = inspect.getsource(pipeline)
    assert "fatti.get((start, stop))" in sorgente, \
        "i segmenti vengono ancora riusati per indice invece che per intervallo"
    assert "seg{start:08d}-{stop:08d}.mkv" in sorgente, \
        "i segmenti sono ancora NOMINATI per indice: registrarli per " \
        "intervallo senza rinominarli non ripara niente"


@caso("sotto la soglia minima di ingrandimento non si parte")
def _() -> None:
    """Lo strumento fa upscale, e solo quando il guadagno vale le ore."""
    from animeup.plan import GUADAGNO_MINIMO, PlanError
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    assert r.geometry.display_height == 720
    for altezza in (480, 720, 800):        # verso il basso, uguale, 1.11x
        try:
            build_plan(r, target_height=altezza)
        except PlanError as exc:
            assert "nulla da fare" in str(exc), f"{altezza}p: {exc}"
        else:
            raise AssertionError(f"{altezza}p: avrebbe dovuto rifiutare")

    sopra = build_plan(r, target_height=1080)      # 1.5x
    assert sopra.model_scale >= 2

    forzato = build_plan(r, target_height=800, forza=True)
    assert any("Forzato" in w for w in forzato.warnings), \
        f"forzando manca l'avviso: {forzato.warnings}"


@caso("il montaggio intreccia le tracce: audio udibile anche dopo un seek")
def _() -> None:
    """Il caso ep01: con un sorgente che porta sottotitoli sparsi, il muxer
    scriveva TUTTO l'audio in testa al file — pacchetti intatti, ma ogni
    player (che legge in avanti) restava muto. Qui si monta un file con la
    stessa trappola e si pretende che l'audio risponda al seek a metà file,
    cioè il controllo che ora fa anche la pipeline a ogni chiusura."""
    import subprocess as sp
    from animeup import encode as enc
    from animeup.paths import PATHS as _P
    with tempfile.TemporaryDirectory() as td_:
        td = Path(td_)
        ass = td / "s.ass"
        ass.write_text(
            "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
            "MarginV, Encoding\n"
            "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,"
            "&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
            "MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,Prova\n"
            "Dialogue: 0,0:00:18.00,0:00:19.50,Default,,0,0,0,,Fine\n")
        src = td / "sorgente.mkv"
        sp.run([str(_P.ffmpeg.path), "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=duration=20:size=160x90:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                "-i", str(ass), "-map", "0:v", "-map", "1:a", "-map", "2:s",
                # NIENTE -shortest: con una traccia sottotitoli ffmpeg si
                # impicca alla chiusura (successo qui: file completo scritto
                # e processo appeso per sempre). Le durate sono esplicite.
                "-c:v", "libx265", "-preset", "ultrafast", "-crf", "32",
                "-c:a", "libopus", "-c:s", "ass", str(src)],
               check=True, capture_output=True)
        segmenti = []
        for i in range(2):
            seg = td / f"seg{i}.mkv"
            sp.run([str(_P.ffmpeg.path), "-nostdin", "-v", "error", "-y",
                    "-ss", str(i * 10), "-t", "10", "-i", str(src),
                    "-map", "0:v", "-c:v", "libx265", "-preset", "ultrafast",
                    "-crf", "32", "-an", str(seg)],
                   check=True, capture_output=True)
            segmenti.append(seg)
        r = probe_source(src, with_fields=False)
        piano = build_plan(r, forza=True)
        piano.output = td / "montato.mkv"
        piano.log = td / "montaggio.log"
        enc.concat_and_mux(piano, segmenti, td)
        assert piano.output.is_file(), "montaggio non riuscito"
        assert enc.audio_risponde_al_seek(piano), \
            "audio muto dopo il seek: interleaving rotto nel montaggio"


@caso("la ripresa adotta la griglia dei blocchi salvata")
def _() -> None:
    """Il ricalcolo della griglia dipende da slider GB e spazio libero del
    momento: se sposta gli intervalli, i segmenti gia' codificati non
    combaciano piu' e si rifanno (lavoro buttato). Con segmenti in cassa la
    griglia SALVATA deve vincere; senza, vince quella fresca."""
    import json as _json
    from animeup.pipeline import Job, _signature
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    job = Job(build_plan(r))
    job.work.mkdir(parents=True, exist_ok=True)
    try:
        originale = job.plan.chunk_size
        diversa = max(1, originale - 37)
        job.state_path.write_text(_json.dumps({
            "signature": _signature(job.plan),
            "segments": [[0, diversa, f"seg{0:08d}-{diversa:08d}.mkv"]],
            "extracted": 0, "chunk": diversa,
        }))
        job._load_state()
        assert job.plan.chunk_size == diversa, \
            f"griglia non adottata: {job.plan.chunk_size} != {diversa}"
        assert job.state["chunk"] == diversa

        # Senza segmenti non c'e' nulla da proteggere: griglia ricalcolata.
        job2 = Job(build_plan(r))
        job2.state_path.write_text(_json.dumps({
            "signature": _signature(job2.plan),
            "segments": [], "extracted": 0, "chunk": diversa,
        }))
        job2._load_state()
        assert job2.plan.chunk_size == originale, \
            f"senza segmenti doveva ricalcolare: {job2.plan.chunk_size}"
    finally:
        shutil.rmtree(job.work, ignore_errors=True)


@caso("uno stato illeggibile non blocca l'episodio per sempre")
def _() -> None:
    from animeup.pipeline import Job
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    job = Job(build_plan(r))
    job.work.mkdir(parents=True, exist_ok=True)
    try:
        for contenuto in ("null", "[]", "{non json", '"stringa"'):
            job.state_path.write_text(contenuto)
            job._load_state()          # non deve sollevare
            assert isinstance(job.state, dict)
    finally:
        shutil.rmtree(job.work, ignore_errors=True)


# ===========================================================================
#  Cache dell'analisi
# ===========================================================================

@caso("il giro su disco dell'analisi non perde nulla")
def _() -> None:
    f = CAMPIONI / "TEST-CFR-23-976fps---2min.mkv"
    originale = probe_source(f)
    with tempfile.TemporaryDirectory() as t:
        finto = Path(t) / "analisi.json"
        finto.write_text(__import__("json").dumps({
            "fingerprint": library._fingerprint(f),
            "report": library._encode(originale),
        }))
        ricostruito = library._decode(
            __import__("json").loads(finto.read_text())["report"], f)

    confronti = [
        ("fps", originale.timing.fps, ricostruito.timing.fps),
        ("modo", originale.timing.mode, ricostruito.timing.mode),
        ("pacchetti", originale.timing.packets, ricostruito.timing.packets),
        ("timebase", originale.timing.time_base, ricostruito.timing.time_base),
        ("sar", originale.geometry.sar, ricostruito.geometry.sar),
        ("dar", originale.geometry.dar, ricostruito.geometry.dar),
        ("larghezza", originale.geometry.width, ricostruito.geometry.width),
        ("profondita", originale.bit_depth, ricostruito.bit_depth),
        ("sottotitoli", originale.subtitle_codecs, ricostruito.subtitle_codecs),
    ]
    for nome, a, b in confronti:
        assert a == b, f"{nome}: {a!r} != {b!r}"
    if originale.timing.outliers:
        assert originale.timing.outliers == ricostruito.timing.outliers, \
            "le anomalie temporali si perdono nel giro su disco"


@caso("un piano costruito dalla cache è identico a uno costruito a caldo")
def _() -> None:
    f = CAMPIONI / "TEST-CFR-23-976fps---2min.mkv"
    a = build_plan(probe_source(f))
    b = build_plan(library.analyse(f))
    for campo in ("target_width", "target_height", "model_scale", "model_key",
                  "frames", "chunk_size"):
        assert getattr(a, campo) == getattr(b, campo), \
            f"{campo}: a caldo {getattr(a, campo)}, da cache {getattr(b, campo)}"


# ===========================================================================
#  Quarto giro di verifica
# ===========================================================================

def _sorgente_288p(dst: Path) -> Path:
    """Un 288p sintetico: la fascia tipica dei fansub vecchi."""
    f = dst / "s288.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=512x288:r=24000/1001", "-t", "2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
    return f


@caso("--force arriva davvero fino al piano, da CLI")
def _() -> None:
    """`--force` (allora `--forza`) era dichiarato in `plan` e in `run` ma non veniva mai passato
    a `build_plan`: l'opzione non faceva niente e la soglia di 1.25x era
    invalicabile. Stessa classe di difetto di `--model`, già corretta."""
    out = subprocess.run(
        [str(ROOT / "animeup"), "plan", "--height", "800", "--force",
         str(CAMPIONI / "clip20s.mkv")],
        capture_output=True, text=True, timeout=300,
    )
    # Il rifiuto si cerca in tutte e due le lingue: il lanciatore parla
    # quella salvata, che qui non e' fissata.
    rifiuti = [i18n.catalogo(lingua)["cli.non_elaborabile"].format(nome="", errore="")
               for lingua in i18n.LINGUE]
    assert not any(r in out.stdout for r in rifiuti), \
        "--force non viene passato a build_plan: rifiuta comunque"
    # La CLI parla la lingua salvata nelle impostazioni, non quella fissata
    # qui per i test: l'avviso si cerca nella sua.
    forzato = i18n.catalogo(i18n.preferita())["mot.plan.forzato"].split(":")[0]
    assert forzato in out.stdout, \
        "--force passa ma l'avviso non arriva a schermo"


@caso("le opzioni della CLI hanno nomi inglesi")
def _() -> None:
    """Le opzioni erano nate in italiano (`--forza`, `--si`, `--altezza`…) e
    un utente inglese se le trovava nell'aiuto. Ora sono solo inglesi."""
    aiuto = subprocess.run([str(ROOT / "animeup"), "run", "--help"],
                           capture_output=True, text=True, timeout=120,
                           env={**os.environ, "COLUMNS": "200", "NO_COLOR": "1",
                                "TERM": "dumb"}).stdout
    # Sul runner di GitHub l'aiuto esce a colori e i codici spezzano «--yes»
    # in «-» e «-yes»: si tolgono comunque, qualunque terminale sia.
    import re
    aiuto = re.sub(r"\x1b\[[0-9;]*m", "", aiuto)
    assert "--yes" in aiuto and "--height" in aiuto and "--force" in aiuto, aiuto[-600:]
    for vecchio in ("--si ", "--altezza", "--forza", "--disco", "--modello", "--pausa"):
        assert vecchio not in aiuto, f"{vecchio} ancora nell'aiuto"


@caso("l'interfaccia non lancia due lavorazioni in parallelo")
def _() -> None:
    """Un lotto con due modelli diversi faceva partire due `Popen` senza mai
    attendere: ognuna vedeva tutto il disco libero e insieme lo riempivano,
    contendendosi per giunta la stessa GPU."""
    import inspect
    sorgente = (ROOT / "ui" / "app.py").read_text()
    inizio = sorgente.index("def _avvia(")
    corpo = sorgente[inizio:sorgente.index("\ndef ", inizio + 1)]
    assert corpo.count("Popen") == 1, \
        "_avvia fa ancora una Popen per gruppo invece di accodarli"
    assert '"; ".join' in corpo, "i gruppi non vengono messi in sequenza"
    del inspect


@caso("lo spazio impegnato da un'altra lavorazione viene contato")
def _() -> None:
    """Ogni processo interrogava `shutil.disk_usage` per conto suo e vedeva
    tutto libero: due lavorazioni che insieme non ci stanno passavano
    entrambe il controllo."""
    import json
    import os

    from animeup import pipeline as pl
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        libero_gb = shutil.disk_usage(paths.root).free / 1_073_741_824
        r = probe_source(_sorgente_288p(Path(t)), with_fields=False)
        piano = build_plan(r, target_height=1080, paths=paths)
        piano.est_peak_disk_gb = libero_gb * 0.6   # da sola ci sta, in due no

        # Si simula l'altra lavorazione: viva (il PID è questo processo) e
        # con la sua prenotazione già scritta. Un file per processo, non un
        # JSON condiviso: con quello, venti lavorazioni avviate insieme ne
        # lasciavano registrata una sola.
        registro = paths.work / ".reservations"
        registro.mkdir(parents=True, exist_ok=True)
        (registro / f"{os.getpid()}.gb").write_text(f"{libero_gb * 0.6:.3f}")

        try:
            pl.Job(piano, paths=paths).run()
        except pl.JobError as exc:
            assert "già impegnati" in str(exc), str(exc)
        else:
            raise AssertionError(
                f"due lavorazioni da {libero_gb * 0.6:.0f} GB sono passate "
                f"entrambe con {libero_gb:.0f} GB liberi")


@caso("una prenotazione di un processo morto non blocca il disco per sempre")
def _() -> None:
    """Altrimenti un crash rendeva impossibile ripartire."""
    from animeup.pipeline import _prenotazioni

    with tempfile.TemporaryDirectory() as t:
        registro = Path(t) / ".reservations"
        registro.mkdir()
        # PID 999999: fuori dal massimo di macOS, quindi certamente morto.
        (registro / "999999.gb").write_text("500.0")
        assert _prenotazioni(registro) == {}, "una voce morta resta impegnata"
        assert not list(registro.glob("*.gb")), "la voce morta non viene ripulita"
        (registro / "nonunpid.gb").write_text("5")
        (registro / "0.gb").write_text("5")
        (registro / "-1.gb").write_text("5")
        assert _prenotazioni(registro) == {}, "PID assurdi accettati"


@caso("l'anteprima non chiede al modello una scala che non ha")
def _() -> None:
    """`preview.render` passava `plan.model_scale` a OGNI variante, ma la
    scala è scelta per il modello del PIANO. Chiedere `-s 4` a un modello che
    ha solo `up2x-denoise1x` fa caricare in silenzio un modello diverso sugli
    ingressi piccoli e va in segmentation fault a 1280x720."""
    from animeup.preview import scale_for

    with tempfile.TemporaryDirectory() as t:
        r = probe_source(_sorgente_288p(Path(t)), with_fields=False)
        piano = build_plan(r, target_height=1080)
        for chiave in CATALOG:              # il multiselect li offre tutti
            scala = scale_for(chiave, piano)
            assert scala in CATALOG[chiave].scales, (
                f"variante {chiave}: riceverebbe -s {scala}, ma dichiara "
                f"solo {CATALOG[chiave].scales}")
            # Il file di modello deve esistere DAVVERO: quando manca, il
            # binario non protesta, carica in silenzio qualcos'altro e si
            # sceglierebbe guardando una bugia. Le due famiglie tengono i
            # pesi in posti diversi.
            from animeup.models import Family
            m = CATALOG[chiave]
            cartella = (PATHS.realcugan.path.parent / (m.cugan_models or "models-se")
                        if m.family is Family.CUGAN else PATHS.models)
            atteso = m.model_name(scala)
            assert (cartella / f"{atteso}.param").is_file(), \
                f"il file di modello {atteso} non esiste in {cartella.name}/"


@caso("un modello che non arriva al bersaglio non parte in silenzio")
def _() -> None:
    """Ripiegando sulla scala PIU' BASSA, un 288p con `cugan-denoise` usciva a
    1024x576 e lanczos lo portava a 1080p: cioè proprio l'interpolazione che
    questo strumento esiste per evitare, senza un avviso."""
    from animeup.plan import PlanError

    with tempfile.TemporaryDirectory() as t:
        r = probe_source(_sorgente_288p(Path(t)), with_fields=False)
        for chiave in CATALOG:
            try:
                p = build_plan(r, target_height=1080, model_key=chiave)
            except PlanError as exc:
                assert "sotto il bersaglio" in str(exc), str(exc)
                continue
            assert p.model_height >= p.target_height, (
                f"{chiave}: produce {p.model_width}x{p.model_height} per un "
                f"bersaglio {p.target_width}x{p.target_height}, senza dirlo")
        # Con --force si procede, ma l'avviso c'e'.
        p = build_plan(r, target_height=1080, model_key="cugan-denoise",
                       forza=True)
        assert any("sotto il bersaglio" in w for w in p.warnings), p.warnings


@caso("una mappa di deduplica malformata non viene 'riparata'")
def _() -> None:
    """La riparazione promuove a "da elaborare" e va bene per uno scostamento
    di contenuto. Su un guasto STRUTTURALE non ripara niente: con la
    sentinella (-1) riscriveva l'ULTIMO elemento e lasciava la mappa rotta ma
    dichiarata sana, per poi far fallire l'elaborazione su 00000000.png."""
    diffs = [0.0] * 10
    m = dedup.build_map(diffs, bit_depth=8, max_run=5)
    m.source_of = m.source_of[:-3]
    esito = dedup.audit(diffs, m)
    assert not esito.ok
    assert esito.violations == [], \
        "un guasto strutturale finisce fra i riparabili"
    assert esito.structural, "il guasto strutturale non viene segnalato"


@caso("la riparazione non lascia doppioni in keep")
def _() -> None:
    """Un fotogramma già in keep veniva aggiunto una seconda volta: `unique`
    e quindi il risparmio mostrato all'utente erano sbagliati, e i doppioni
    finivano in dedup.json."""
    diffs = [0.0, 0.0, 200.0, 0.0, 0.0, 0.0, 300.0, 0.0]
    m = dedup.build_map(diffs, bit_depth=8, max_run=5)
    incriminati = [(i, 0.0) for i in list(m.keep)[:2]]
    for index, _ in incriminati:
        m.source_of[index] = index
    m.keep = sorted(set(m.keep) | {i for i, _ in incriminati})
    assert len(m.keep) == len(set(m.keep)), f"doppioni in keep: {m.keep}"
    assert dedup.audit(diffs, m).ok


@caso("una mappa riletta da disco viene ricontrollata")
def _() -> None:
    """La firma dice che la mappa parla dello stesso video, non che sia sana:
    il file può essere stato troncato o modificato a mano."""
    diffs = [0.0] * 10
    m = dedup.build_map(diffs, bit_depth=8, max_run=5)
    assert dedup.structure_ok(m)
    m.source_of[5] = 9                      # riferimento in avanti
    assert not dedup.structure_ok(m)
    m = dedup.build_map(diffs, bit_depth=8, max_run=5)
    m.keep = m.keep + m.keep[:1]            # doppione
    assert not dedup.structure_ok(m)


@caso("il lanciatore rispetta un ANIMEUP_ROOT impostato dall'utente")
def _() -> None:
    """Sovrascriverlo rendeva impossibile lavorare fuori dalla cartella del
    progetto, e chi ci provava vedeva work/ e OUTPUT/ finire qui dentro."""
    import os
    with tempfile.TemporaryDirectory() as t:
        out = subprocess.run(
            [str(ROOT / "animeup"), "doctor"],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "ANIMEUP_ROOT": t},
        )
        assert t in out.stdout, \
            f"ANIMEUP_ROOT ignorato: doctor lavora ancora altrove\n{out.stdout[:400]}"


@caso("la stima del picco su disco conta segmenti e file finale")
def _() -> None:
    """Contava solo sorgenti + un blocco: i segmenti restano tutti su disco
    fino all'assemblaggio e l'uscita nasce sullo stesso volume. Su un episodio
    1080p sono una decina di GB, abbastanza da riempire il disco DOPO che la
    guardia aveva detto di si'."""
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    p = build_plan(r, target_height=1080)
    sorgenti = p.frames * p.source.geometry.width * p.source.geometry.height \
        * 1.05 / 1_048_576 / 1024
    blocco = p.chunk_size * p.model_width * p.model_height * 1.75 / 1_048_576 / 1024
    assert p.est_peak_disk_gb > sorgenti + blocco, \
        "la stima non tiene conto di segmenti e uscita"


@caso("due lavorazioni sullo stesso file non partono insieme")
def _() -> None:
    """Condividono la cartella di lavoro (i fotogrammi estratti sono gli
    stessi, ed è voluto): girare insieme però significa sovrascriversi stato
    e segmenti a vicenda, e scoprirlo solo alla fine."""
    import os

    from animeup import pipeline as pl
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        r = probe_source(_sorgente_288p(Path(t)), with_fields=False)
        piano = build_plan(r, target_height=1080, paths=paths)
        piano.est_peak_disk_gb = 0.01
        job = pl.Job(piano, paths=paths)
        job.work.mkdir(parents=True, exist_ok=True)
        # Un lucchetto di un processo VIVO (questo).
        (job.work / "running.lock").write_text(str(os.getpid() + 0))
        # Il proprio PID non deve bloccare se stessi, quindi se ne finge un
        # altro certamente vivo: il processo padre.
        (job.work / "running.lock").write_text(str(os.getppid()))
        try:
            job.run()
        except pl.JobError as exc:
            assert "già in corso" in str(exc), str(exc)
        else:
            raise AssertionError("il lucchetto non ha fermato la seconda")

        # Un lucchetto di un processo morto non deve bloccare la ripresa.
        (job.work / "running.lock").write_text("999999")
        try:
            job.run()
        except pl.JobError as exc:
            assert "già in corso" not in str(exc), \
                "un lucchetto morto blocca la ripresa per sempre"
        except Exception:                                     # noqa: BLE001
            pass


# ===========================================================================
#  Quinto giro di verifica
# ===========================================================================

@caso("il colore non viene convertito con una matrice e etichettato con un'altra")
def _() -> None:
    """I PNG sono RGB e non portano tag: senza `out_color_matrix` swscale
    converte SEMPRE in BT.601, mentre l'etichetta diceva quello del sorgente.
    Sbagliato esattamente sui sorgenti HD, che sono la maggioranza. Il caso
    precedente controllava solo che i tag ci fossero, mai che i DATI
    corrispondessero: è passato verde per tutto il tempo in cui il difetto
    c'era."""
    from animeup import encode as enc

    def rgb(f: Path, n: int = 3) -> bytes:
        return subprocess.run(
            [FFMPEG, "-hide_banner", "-v", "error", "-i", str(f), "-frames:v", str(n),
             "-vf", "scale=640:360", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True, check=True).stdout

    for matrice in ("bt709", "bt470bg"):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            src = d / "src.mkv"
            ffmpeg("-f", "lavfi", "-i", "smptehdbars=s=1280x720:r=24", "-t", "0.3",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10",
                   "-colorspace", matrice, "-color_primaries", "bt709",
                   "-color_trc", "bt709", str(src))
            r = probe_source(src, with_fields=False)
            p = build_plan(r, target_height=1080)
            frames = d / "f"; frames.mkdir()
            enc.extract_frames(p, frames)
            seg = d / "seg.mkv"
            enc.encode_segment(p, frames, seg)

            a, b = rgb(src), rgb(seg)
            n = min(len(a), len(b))
            medio = sum(abs(a[i] - b[i]) for i in range(n)) / n
            assert medio < 1.5, (
                f"sorgente {matrice}: scostamento medio su RGB {medio:.2f} "
                "dopo il giro completo — la matrice di conversione non "
                "corrisponde all'etichetta")
            # E i tre tag devono sopravvivere: chiedere la matrice a swscale
            # da sola faceva uscire "bt709,unknown,unknown".
            got = subprocess.run(
                [str(PATHS.ffprobe.path), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=color_space,color_transfer,color_primaries",
                 "-of", "csv=p=0", str(seg)],
                capture_output=True, text=True).stdout.strip()
            assert "unknown" not in got, f"tag incompleti: {got}"


@caso("la deduplica vede i cambiamenti di colore, non solo di luminanza")
def _() -> None:
    """`signalstats` riporta il massimo del piano Y: un cambiamento di colore a
    luminanza costante gli risultava ZERO e il fotogramma veniva scartato,
    mentre il modulo dichiara "nessun singolo pixel oltre la soglia". Sul primo
    episodio reale il caso peggiore era una dissolvenza di colore misurata
    15.59 invece di 39."""
    from animeup.dedup import measure_frame_differences

    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        # Tre fotogrammi: il secondo identico al primo, il terzo cambia SOLO
        # in colore su un rettangolo, a luminanza quasi costante.
        try:
            from PIL import Image
        except ImportError:                      # pragma: no cover
            return
        for i, colore in enumerate(((100, 0, 0), (100, 0, 0), (0, 51, 0)), start=1):
            im = Image.new("RGB", (64, 64), (10, 10, 10))
            im.paste(Image.new("RGB", (44, 44), colore), (10, 10))
            im.save(d / f"{i:08d}.png")

        diffs = measure_frame_differences(d)
        assert len(diffs) == 2, diffs
        assert diffs[0] == 0.0, f"due fotogrammi identici danno {diffs[0]}"
        # Lo scostamento vero è 100/255 sul canale rosso.
        assert diffs[1] >= 90, (
            f"un cambiamento di colore da 100 livelli è stato misurato "
            f"{diffs[1]}: la metrica è cieca al colore")


@caso("la cache dell'analisi sopravvive alla copia su un altro disco")
def _() -> None:
    """Chiave sul percorso ASSOLUTO e impronta con la mtime: erano i due
    errori già corretti in pipeline.py, mai riportati qui. Dopo la copia sul
    secondo Mac l'intera libreria tornava da rianalizzare."""
    from animeup import library
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        a, b = Path(t) / "disco1", Path(t) / "disco2"
        for radice in (a, b):
            (radice / "INPUT").mkdir(parents=True)
            shutil.copy2(CAMPIONI / "clip20s.mkv", radice / "INPUT" / "ep.mkv")
        # mtime diversa, come dopo un rsync o un ripristino da backup
        os.utime(b / "INPUT" / "ep.mkv", (1_600_000_000, 1_600_000_000))

        ca = library._cache_path(a / "INPUT" / "ep.mkv", Paths(a))
        cb = library._cache_path(b / "INPUT" / "ep.mkv", Paths(b))
        assert ca.name == cb.name, \
            f"la chiave cambia con la radice: {ca.name} contro {cb.name}"
        assert (library._fingerprint(a / "INPUT" / "ep.mkv")
                == library._fingerprint(b / "INPUT" / "ep.mkv")), \
            "l'impronta cambia con la sola data di modifica"


@caso("il lanciatore rifiuta un ambiente che importa da un'altra cartella")
def _() -> None:
    """Dopo la copia, il `.pth` dell'ambiente virtuale punta ancora al disco
    vecchio: `import animeup` riusciva da LA', quindi `uv sync` non partiva e
    non si riparava niente. Nessun errore, e la lavorazione girava col codice
    vecchio scrivendo work/ e OUTPUT/ sull'altro disco."""
    testo = (ROOT / "animeup").read_text()
    assert "animeup.__file__" in testo, \
        "il lanciatore controlla ancora solo che l'importazione riesca"
    assert "startswith" in testo, "manca il confronto con la radice"


@caso("due lavorazioni con parametri diversi non finiscono sullo stesso file")
def _() -> None:
    """Il preset cambia il risultato e non entrava nel nome: la seconda corsa
    sovrascriveva la prima."""
    comune = dict(target_height=1080, scale=3, model_tag="cugan", crf=18)
    base = output_name("ep", **comune)
    assert base != output_name("ep", **comune, preset="veryslow")
    assert base == output_name("ep", **comune, preset="slower"), \
        "il preset predefinito non deve comparire nel nome"


@caso("la stima dei tempi conta la codifica, che non è gratis")
def _() -> None:
    """Il fattore era 1.15, giustificato con una sovrapposizione che non
    esiste: la pipeline è seriale. Misurato 1.97 su un caso reale, cioè 3.1
    ore promesse contro 5.4 vere su un episodio."""
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    # Paths ISOLATI: con lo storico delle lavorazioni vere il tetto diventa
    # il peggior caso OSSERVATO, che sta legittimamente sotto l'ipotesi
    # "nessun fotogramma ripetuto" — e questo caso verifica proprio
    # quell'ipotesi. Senza isolamento il test dipenderebbe da quanti file
    # ha lavorato chi lo esegue.
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as t_vuoto:
        p = build_plan(r, target_height=1080, paths=Paths(Path(t_vuoto)))
    from animeup.plan import FPS_CODIFICA
    fattore = (p.target_width * p.target_height) / (1920 * 1080)
    codifica_attesa = p.frames * fattore / FPS_CODIFICA
    extra = p.est_total_seconds - p.est_gpu_seconds
    assert extra >= codifica_attesa * 0.9, (
        f"oltre la GPU la stima aggiunge solo {extra:.0f}s, ma la codifica di "
        f"{p.frames} fotogrammi ne costa {codifica_attesa:.0f}")
    # NON si asserisce più un rapporto minimo sulla GPU: con un modello lento
    # e una codifica veloce il rapporto può legittimamente stare sotto 1.15,
    # e infatti ci sta. Cio' che conta è che la codifica sia contata per
    # quello che costa, verificato sopra.
    assert p.est_best_seconds <= p.est_total_seconds, \
        "l'estremo ottimista non può superare quello pessimista"


@caso("un bersaglio assurdo viene rifiutato, non fatto esplodere")
def _() -> None:
    """`--height 0 --force` usciva con ZeroDivisionError e un traceback;
    `--height -100` produceva un piano con uscita -132x-100."""
    from animeup.plan import PlanError
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    for altezza in (0, -100, 8):
        try:
            build_plan(r, target_height=altezza, forza=True)
        except PlanError:
            pass
        else:
            raise AssertionError(f"altezza {altezza} accettata")


@caso("un preset o un CRF inventati si fermano prima delle ore di GPU")
def _() -> None:
    from animeup.plan import PlanError
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    for kwargs in ({"preset": "slowest"}, {"crf": 99}, {"crf": -1}):
        try:
            build_plan(r, target_height=1080, **kwargs)
        except PlanError:
            pass
        else:
            raise AssertionError(f"{kwargs} accettato")


@caso("l'anteprima non fa collidere prove diverse nella stessa cartella")
def _() -> None:
    """Il nome usava lo stem grezzo: due episodi omonimi in cartelle diverse
    condividevano la cartella, due bersagli diversi si sovrascrivevano, e uno
    stem `..` scriveva FUORI da anteprime/."""
    from animeup.pipeline import identita_sorgente, safe_name
    sorgente = (ROOT / "src" / "animeup" / "preview.py").read_text()
    assert "safe_name(" in sorgente, "preview.render non usa safe_name"
    assert "plan.target_height" in sorgente and "plan.encoding.crf" in sorgente, \
        "i parametri del piano non entrano nel nome della cartella"
    # E `safe_name` neutralizza davvero i casi che scrivevano fuori.
    for stem in ("..", ".", "", "ep\n01"):
        nome = safe_name(stem, identita_sorgente(Path("/x/y.mkv"), Path("/x")))
        assert "/" not in nome and "\n" not in nome and nome not in ("..", "."), nome


@caso("la regola dello spezzone scuro cerca il movimento, non l'immobilita'")
def _() -> None:
    """Il segno della penalità era invertito: promuoveva i punti fermi invece
    di scartarli, quindi il candidato "scuro" era per costruzione statico e la
    descrizione mostrata a schermo ("con movimento") era falsa."""
    sorgente = (ROOT / "src" / "animeup" / "preview.py").read_text()
    riga = next(r for r in sorgente.splitlines() if "Kind.DARK" in r and "lambda" in r)
    assert "else -1e6" in riga, f"penalità ancora col segno sbagliato: {riga.strip()}"


@caso("chi si rifiuta di partire non cancella il lucchetto di chi lavora")
def _() -> None:
    """Il `finally` lo cancellava sempre: il processo respinto distruggeva la
    mutua esclusione che aveva appena rispettato, e il tentativo dopo entrava
    in concorrenza con la lavorazione viva."""
    import os as _os

    from animeup import pipeline as pl
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        (Path(t) / "INPUT").mkdir(parents=True)
        src = Path(t) / "INPUT" / "s.mkv"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=512x288:r=24000/1001", "-t", "1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
        r = probe_source(src, with_fields=False)
        piano = build_plan(r, target_height=1080, paths=paths)
        job = pl.Job(piano, paths=paths)
        job.work.mkdir(parents=True, exist_ok=True)
        lock = job.work / "running.lock"
        lock.write_text(str(_os.getppid()))       # un processo vivo, non noi
        try:
            job.run()
        except pl.JobError:
            pass
        assert lock.is_file(), \
            "il processo respinto ha cancellato il lucchetto di quello attivo"


@caso("due processi che scrivono insieme non si rubano il file d'appoggio")
def _() -> None:
    """Il temporaneo aveva un nome fisso: il primo lo rinominava e il secondo
    moriva con un FileNotFoundError su un percorso .tmp incomprensibile. Su
    venticinque coppie succedeva undici volte, e proprio sul registro che
    serve a coordinare più lavorazioni."""
    from animeup.pipeline import _scrivi_atomico
    sorgente = (ROOT / "src" / "animeup" / "pipeline.py").read_text()
    assert "os.getpid()}.tmp" in sorgente, \
        "il file d'appoggio ha ancora un nome uguale per tutti i processi"
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "x.json"
        _scrivi_atomico(f, '{"a": 1}')
        assert f.read_text() == '{"a": 1}'
        assert not list(Path(t).glob("*.tmp")), "temporaneo non ripulito"


@caso("un segmento troncato non viene riusato per sempre")
def _() -> None:
    """Bastava `is_file()`: un segmento a zero byte lasciato da uno spegnimento
    restava registrato e nulla lo invalidava mai. Il video finale usciva corto
    e al rilancio la CLI diceva "già presente, saltato"."""
    from animeup.pipeline import _segmento_valido

    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        buono = d / "seg.mkv"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=64x64:r=24", "-frames:v", "10",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(buono))
        assert _segmento_valido(buono, 10, PATHS), "un segmento sano viene rifiutato"
        assert not _segmento_valido(buono, 11, PATHS), \
            "il conteggio dei fotogrammi non viene controllato"
        vuoto = d / "vuoto.mkv"
        vuoto.write_bytes(b"")
        assert not _segmento_valido(vuoto, 10, PATHS)
        assert not _segmento_valido(d / "assente.mkv", 10, PATHS)


@caso("una prenotazione con PID assurdo non blocca il disco per sempre")
def _() -> None:
    """`os.kill(0, 0)` e `os.kill(-1, 0)` riescono SEMPRE: quelle voci non
    venivano mai scartate, dentro un file nascosto che nessun messaggio
    d'errore nomina."""
    from animeup.pipeline import _prenotazioni

    with tempfile.TemporaryDirectory() as t:
        registro = Path(t) / ".reservations"
        registro.mkdir()
        for nome, valore in (("0", "5"), ("-1", "5"), ("999999", "500"),
                             ("nonunpid", "5")):
            (registro / f"{nome}.gb").write_text(valore)
        assert _prenotazioni(registro) == {}, "voci assurde accettate"
        assert not list(registro.glob("*.gb")), "le voci morte non si ripuliscono"


# ===========================================================================

@caso("il ritmo del monitoraggio non inventa numeri")
def _() -> None:
    """fps ed ETA vengono dalla finestra di campioni: niente risposta con un
    campione solo, con una finestra troppo corta o senza avanzamento — meglio
    nessun numero che un numero inventato."""
    from animeup.monitor import andatura

    assert andatura([]) is None
    assert andatura([(0.0, 10)]) is None
    assert andatura([(0.0, 10), (2.0, 20)]) is None      # finestra < 3s
    assert andatura([(0.0, 10), (10.0, 10)]) is None     # fermo
    assert andatura([(0.0, 10), (10.0, 30)]) == 2.0
    # la finestra guarda estremi, non la media dall'avvio
    assert andatura([(0.0, 0), (60.0, 60), (70.0, 80)]) == 80 / 70


@caso("il monitoraggio legge lo stato dei lavori senza toccarlo")
def _() -> None:
    """Il pannello dice vivo/interrotto e l'avanzamento vero leggendo solo
    ciò che la pipeline lascia per la ripresa. Sola lettura verificata sul
    filesystem: un monitor che scrive è un monitor che un giorno interrompe
    una lavorazione da otto ore per un bug suo."""
    import json
    import subprocess as sp

    from animeup import monitor
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        firma = ("ep.mkv|123||-fps_mode cfr -r 24/1|1000|up2x-no-denoise|2"
                 "|1920|1080|x|y|slower|k|True|24/1")

        vivo = paths.work / "ep 2026-01-01 abcdef01"
        (vivo / "chunk0000-up").mkdir(parents=True)
        # La forma VERA dei segmenti è la tripla [inizio, fine, nome]; la
        # stringa nuda resta accettata per compatibilita'. Il primo monitor
        # assumeva solo stringhe e cadeva sul primo lavoro con un segmento
        # già codificato.
        (vivo / "state.json").write_text(json.dumps(
            {"signature": firma,
             "segments": [[0, 400, "seg00000000-00000400.mkv"],
                          "seg00000000-00000300.mkv"],
             "extracted": 1000}))
        # Un processo VERO: `_processo_vivo` risponde "lo tiene qualcun
        # altro?", quindi al PID di questo stesso processo direbbe no.
        figlio = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)", "animeup-finto"])
        (vivo / "running.lock").write_text(str(figlio.pid))
        (vivo / "chunk0000-up" / "00000550.png").write_bytes(b"")

        morto = paths.work / "altro 2026-01-01 abcdef02"
        morto.mkdir(parents=True)
        (morto / "state.json").write_text(json.dumps(
            {"signature": firma, "segments": [], "extracted": 300}))
        (morto / "running.lock").write_text("999999")

        prima = sorted(str(f) for f in paths.work.rglob("*"))
        letti = monitor.lavori(paths)
        assert [l.vivo for l in letti] == [True, False],             [l.vivo for l in letti]
        v, m = letti
        assert (v.fatti, v.totale, v.fase) == (550, 1000, "elaborazione"),             (v.fatti, v.totale, v.fase)
        # Il punto nel blocco: dimensione dedotta dal primo segmento (400),
        # 2 segmenti registrati -> blocco corrente = 3 di ceil(1000/400) = 3,
        # avanzamento nel blocco = 550 - 400 = 150 su min(400, 1000-400).
        assert (v.blocco_fatti, v.blocco_totale) == (150, 400),             (v.blocco_fatti, v.blocco_totale)
        assert (v.blocco_n, v.blocchi_totali) == (3, 3),             (v.blocco_n, v.blocchi_totali)
        assert (m.fase, m.fatti) == ("estrazione", 300), (m.fase, m.fatti)
        assert m.modello == "CUGAN no-denoise", m.modello
        assert v.frazione == 0.55
        dopo = sorted(str(f) for f in paths.work.rglob("*"))
        assert prima == dopo, "il monitor ha scritto dove doveva solo leggere"
        figlio.terminate()


@caso("il monitoraggio vede l'estrazione appena nata, senza state.json")
def _() -> None:
    """`state.json` nasce a FINE estrazione: per i primi ~10 minuti di un
    episodio nuovo esiste solo il lucchetto, e il monitor che lo ignorava
    rendeva la pagina cieca — "sembra tutto fermo e non posso nemmeno
    fermarlo" (successo davvero). Un lucchetto vivo È una lavorazione."""
    import subprocess as sp

    from animeup import monitor
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        d = paths.work / "ep 2026-01-01 abcdef01"
        (d / "frames").mkdir(parents=True)
        for n in range(1, 8):
            (d / "frames" / f"{n:08d}.png").write_bytes(b"")
        figlio = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)", "animeup-finto"])
        (d / "running.lock").write_text(str(figlio.pid))

        letti = monitor.lavori(paths)
        assert len(letti) == 1, f"attesa 1 lavorazione, trovate {len(letti)}"
        lav = letti[0]
        assert lav.vivo and lav.fase == "estrazione", (lav.vivo, lav.fase)
        assert lav.fatti == 7, f"attesi 7 fotogrammi estratti, {lav.fatti}"
        assert lav.totale == 0, "senza ricetta il totale non può essere noto"

        # Con la ricetta (parametri.json, scritta prima dell'estrazione) il
        # monitor sa anche "su quanti": la riga può dire 7/13233.
        import json as json_
        (d / "parameters.json").write_text(json_.dumps({"fotogrammi": 13233}))
        lav = monitor.lavori(paths)[0]
        assert lav.totale == 13233, f"totale dalla ricetta: {lav.totale}"

        # Col lucchetto MORTO la cartella non è una lavorazione in corso:
        # è un residuo, e non deve inventarsi una riga.
        figlio.kill()
        figlio.wait()
        assert monitor.lavori(paths) == [], "un lucchetto morto genera righe"


@caso("la pausa fra due file si dichiara su disco e scade da sola")
def _() -> None:
    """Durante la pausa (`--pause`) nessun lucchetto esiste, ma la catena è
    viva: senza il marcatore la barra direbbe "GPU libera" e un secondo
    lancio colliderebbe col primo al risveglio. Un marcatore scaduto, di un
    processo morto o illeggibile deve valere come assente."""
    import json
    import time as t_
    import subprocess as sp

    from animeup import monitor
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        paths.work.mkdir(parents=True)
        m = paths.work / ".pause"
        figlio = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)", "animeup-finto"])

        m.write_text(json.dumps({"fino": t_.time() + 120, "pid": figlio.pid}))
        viva = monitor.pausa(paths)
        assert viva is not None and viva[1] == figlio.pid, "pausa valida non vista"

        m.write_text(json.dumps({"fino": t_.time() - 5, "pid": figlio.pid}))
        assert monitor.pausa(paths) is None, "pausa scaduta creduta viva"

        m.write_text(json.dumps({"fino": t_.time() + 120, "pid": 999999}))
        assert monitor.pausa(paths) is None, "pausa di un processo morto"

        m.write_text("non è json")
        assert monitor.pausa(paths) is None, "marcatore rotto fa esplodere"

        figlio.kill()
        figlio.wait()


@caso("il monitoraggio riconosce il blocco in codifica (GPU ferma, CPU su)")
def _() -> None:
    """A blocco upscalato per intero (chunk-up pieno quanto chunk-in) la
    pipeline codifica in x265: 3-4 minuti a GPU ferma in cui il ritmo mobile
    crollava e la ETA esplodeva — "che succede?" (successo). Va dichiarato
    come fase, non lasciato sembrare un guasto."""
    import json
    import subprocess as sp

    from animeup import monitor
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t:
        paths = Paths(Path(t))
        firma = ("ep.mkv|123||-fps_mode cfr -r 24/1|1000|up2x-no-denoise|2"
                 "|1920|1080|x|y|slower|k|True|24/1")
        d = paths.work / "ep 2026-01-01 abcdef01"
        (d / "chunk0002-in").mkdir(parents=True)
        (d / "chunk0002-up").mkdir(parents=True)
        for n in range(1, 4):
            (d / "chunk0002-in" / f"{n:08d}.png").write_bytes(b"")
            (d / "chunk0002-up" / f"{n:08d}.png").write_bytes(b"")
        (d / "state.json").write_text(json.dumps(
            {"signature": firma, "segments": [], "extracted": 1000}))
        figlio = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)", "animeup-finto"])
        (d / "running.lock").write_text(str(figlio.pid))

        lav = monitor.lavori(paths)[0]
        assert lav.fase == "codifica blocco", lav.fase

        # Con l'upscale ancora in corso (up < in) resta "elaborazione".
        (d / "chunk0002-in" / "00000004.png").write_bytes(b"")
        lav = monitor.lavori(paths)[0]
        assert lav.fase == "elaborazione", lav.fase

        figlio.terminate()
        figlio.wait()


@caso("un lucchetto con dentro uno zombie non blocca la ripresa")
def _() -> None:
    """`kill(pid, 0)` risponde "esiste" anche per un processo morto che il
    padre non ha ancora raccolto. Trattarlo da vivo teneva il lucchetto
    occupato — e il monitor mostrava "in corso" un lavoro ucciso col SIGKILL —
    finché il padre non usciva. Misurato dopo un kill -9 dalla UI."""
    import time as t_
    import subprocess as sp

    from animeup.pipeline import _processo_vivo

    with tempfile.TemporaryDirectory() as t:
        figlio = sp.Popen(["true"])       # niente wait(): morto ma non raccolto
        for _giro in range(50):
            t_.sleep(0.1)
            esito = sp.run(["ps", "-o", "state=", "-p", str(figlio.pid)],
                           capture_output=True, text=True, check=False)
            if esito.stdout.strip().startswith("Z"):
                break
        else:
            raise AssertionError("il figlio non è mai diventato zombie")
        lock = Path(t) / "running.lock"
        lock.write_text(str(figlio.pid))
        assert not _processo_vivo(lock), "uno zombie giudicato vivo"
        figlio.wait()


@caso("la ripresa abbatte l'upscaler orfano, e solo quello")
def _() -> None:
    """Dopo un SIGKILL alla CLI nessun gestore di segnali gira: il binario
    ncnn, in sessione propria, resta orfano a scrivere PNG nella cartella.
    Riprendere a quel punto vorrebbe dire due processi sugli stessi file.
    Il pgid lasciato su disco permette di trovarlo e abbatterlo — ma SOLO se
    il comando è davvero un upscaler: un PID riusato da un processo
    qualunque deve sopravvivere."""
    import subprocess as sp

    from animeup.pipeline import _abbatti_orfano

    with tempfile.TemporaryDirectory() as t:
        work = Path(t)

        # Un finto upscaler: /bin/sleep sotto altro nome, così il comando
        # contiene "realcugan" senza scomodare la GPU.
        finto = work / "realcugan-finto"
        shutil.copy("/bin/sleep", finto)
        finto.chmod(0o755)
        orfano = sp.Popen([str(finto), "30"], start_new_session=True)
        (work / "upscaler.pgid").write_text(str(orfano.pid))
        _abbatti_orfano(work)
        assert orfano.wait(timeout=5) == -9, "l'orfano non è stato abbattuto"
        assert not (work / "upscaler.pgid").exists(), "pgid rimasto su disco"

        # Un processo innocente col pgid riusato: non va toccato.
        innocente = sp.Popen(["sleep", "30"], start_new_session=True)
        (work / "upscaler.pgid").write_text(str(innocente.pid))
        _abbatti_orfano(work)
        assert innocente.poll() is None, "ucciso un processo che non era nostro"
        assert not (work / "upscaler.pgid").exists(), "pgid rimasto su disco"
        innocente.kill()
        innocente.wait()


@caso("la taratura parla solo per la macchina che l'ha fatta")
def _() -> None:
    """registri/taratura.json è chiavato sul chip: una copia della cartella
    portata su un altro Mac non deve sporcare le stime di nessuno. La voce
    di un chip diverso va ignorata come se non esistesse."""
    import json

    from animeup import taratura
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        paths.taratura.write_text(json.dumps({
            "versione": 1,
            "macchine": {
                "Chip Immaginario X9": {
                    "quando": 0, "estrazione_fps": 120, "codifica_fps": 16,
                    "mpxs": {"animevideov3": {"3": 3.58}},
                },
            },
        }))
        # Il chip vero di questa macchina non è nel file: niente taratura.
        assert taratura.carica(paths) is None, "voce altrui presa per propria"
        assert taratura.throughput("animevideov3", 3, paths) is None

        # Con la voce del chip GIUSTO invece i numeri arrivano.
        assert taratura.carica(paths, macchina="Chip Immaginario X9") is not None
        dati = json.loads(paths.taratura.read_text())
        dati["macchine"][taratura.chip()] = dati["macchine"].pop(
            "Chip Immaginario X9")
        paths.taratura.write_text(json.dumps(dati))
        assert taratura.throughput("animevideov3", 3, paths) == 3.58
        assert taratura.throughput("animevideov3", 4, paths) is None, \
            "scala mai misurata: deve ricadere sulla fabbrica"


@caso("la taratura di un altro Mac con lo stesso chip non vale qui")
def _() -> None:
    """Dall'1.6.8 la voce porta l'impronta del Mac: una cartella portata su
    un altro Mac, anche con lo stesso chip, non si porta dietro stime non
    sue. Le voci di prima (senza impronta) valgono ancora sul loro chip,
    marcate `vecchia` perche' la pagina chieda di rifarle."""
    import json

    from animeup import taratura
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        voce = {"quando": 0, "mpxs": {"cugan": {"2": 1.5}}, "mpx_misura": 0.41,
                "id": "mac-di-qualcun-altro", "chip": taratura.chip()}
        paths.taratura.write_text(json.dumps({"versione": 1, "macchine": {
            "mac-di-qualcun-altro": voce}}))
        assert taratura.carica(paths) is None, "presa la voce di un altro Mac"
        assert taratura.di_altro_mac(paths) == taratura.chip()

        # La stessa voce col nome del chip e senza impronta: e' di prima.
        vecchia = {k: v for k, v in voce.items() if k not in ("id", "chip")}
        paths.taratura.write_text(json.dumps({"versione": 1, "macchine": {
            taratura.chip(): vecchia}}))
        trovata = taratura.carica(paths)
        assert trovata is not None and trovata.get("vecchia"), trovata

        # E la voce con l'impronta di QUESTO Mac vince.
        mia = dict(voce, id=taratura.macchina_id())
        paths.taratura.write_text(json.dumps({"versione": 1, "macchine": {
            taratura.macchina_id(): mia, taratura.chip(): vecchia}}))
        trovata = taratura.carica(paths)
        assert trovata is not None and not trovata.get("vecchia"), trovata


@caso("il ritmo di un modello si legge fra la misura 480p e quella 1080p")
def _() -> None:
    """La GPU rende di piu' sui fotogrammi grandi: un 1080p prende la misura
    grande, un 720p sta in mezzo, un 480p la piccola, e fuori dall'intervallo
    vale la piu' vicina. Senza la misura grande si resta alla piccola."""
    import json

    from animeup import taratura
    from animeup.paths import Paths

    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        voce = {"quando": 0, "id": taratura.macchina_id(),
                "mpx_misura": 0.4, "mpxs": {"cugan": {"2": 1.5}},
                "mpx_grande": 2.0, "mpxs_grande": {"cugan": {"2": 2.5}}}
        paths.taratura.write_text(json.dumps({"versione": 1, "macchine": {
            taratura.macchina_id(): voce}}))
        r = lambda mpx: taratura.throughput("cugan", 2, paths, mpx=mpx)  # noqa: E731
        assert r(2.0736) == 2.5 and r(0.2) == 1.5, (r(2.0736), r(0.2))
        assert abs(r(1.2) - 2.0) < 1e-9, r(1.2)
        assert taratura.throughput("cugan", 2, paths) == 1.5, "senza mpx: la piccola"
        assert taratura.throughput("cugan", 3, paths, mpx=2.0) is None


@caso("il ritmo della taratura ignora il caricamento del modello")
def _() -> None:
    """Il cronometro parte dal PRIMO PNG scritto, non dal lancio del
    processo: su un campione breve il caricamento del modello (secondi)
    aveva gia' falsato una misura di produzione (0.57 contro 0.85 Mpx/s,
    vedi models.py)."""
    import os

    from animeup.taratura import _ritmo_da_mtime

    with tempfile.TemporaryDirectory() as t_:
        d = Path(t_)
        # 5 fotogrammi scritti uno al secondo: 4 intervalli in 4 secondi.
        for i in range(5):
            f = d / f"{i:08d}.png"
            f.write_bytes(b"")
            os.utime(f, (1000 + i, 1000 + i))
        assert _ritmo_da_mtime(d, 60.0) == 1.0, "4 fotogrammi in 4 secondi"
        # Date identiche (filesystem senza precisione): si ripiega sul tempo
        # di parete, mai su un numero inventato.
        for f in d.glob("*.png"):
            os.utime(f, (2000, 2000))
        assert _ritmo_da_mtime(d, 10.0) == 0.5


@caso("il piano stima coi numeri tarati quando esistono")
def _() -> None:
    """Con la taratura sul disco, build_plan deve usare i Mpx/s misurati e i
    ritmi di estrazione/codifica della macchina — e dichiararlo nel piano
    (`stime_tarate`), perché l'interfaccia dica con che titolo parla."""
    import json

    from animeup import taratura
    from animeup.paths import Paths
    from animeup.plan import build_plan

    sorgente = probe_source(CAMPIONI / "TEST-CFR-24fps---2min.mkv",
                            with_fields=False)
    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        prima = build_plan(sorgente, paths=paths)
        assert not prima.stime_tarate

        paths.taratura.write_text(json.dumps({
            "versione": 1,
            "macchine": {taratura.chip(): {
                "quando": 0, "estrazione_fps": 120.0, "codifica_fps": 16.0,
                "mpxs": {prima.model_key: {str(prima.model_scale): 100.0}},
            }},
        }))
        dopo = build_plan(sorgente, paths=paths)
        assert dopo.stime_tarate, "taratura presente ma non adottata"
        assert dopo.fps_estrazione == 120.0 and dopo.fps_codifica == 16.0
        assert dopo.est_gpu_seconds < prima.est_gpu_seconds, \
            "100 Mpx/s misurati devono abbattere la stima GPU"
        assert dopo.est_total_seconds < prima.est_total_seconds


@caso("la forchetta delle stime nasce dalle lavorazioni gia' fatte")
def _() -> None:
    """Senza storia la stima usa gli estremi teorici (0% e 60% di
    deduplica) piu' un margine del 25%: una forchetta larghissima, l'unica
    onesta quando non si sa niente. Con le pagelle alle spalle diventa il
    peggiore e il migliore dei casi VISTI DAVVERO, e la mediana e' il
    numero su cui scommettere."""
    import json

    from animeup.paths import Paths
    from animeup.plan import build_plan
    from animeup import storico

    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        vuoto = build_plan(r, target_height=1080, paths=paths)
        assert vuoto.dedup_storico is None, "senza pagelle non c'e' storia"
        larghezza_teorica = (vuoto.est_total_seconds
                             / max(1e-9, vuoto.est_best_seconds))

        with paths.storico.open("w") as fh:
            for quota in (0.41, 0.39, 0.36, 0.32):
                fh.write(json.dumps({"file": "x.mkv", "dedup": quota}) + "\n")
        d = storico.deduplica(paths)
        assert d and d.campioni == 4 and d.affidabile
        assert abs(d.attesa - 0.375) < 0.001, d.attesa   # mediana di 4 valori
        assert (d.minimo, d.massimo) == (0.32, 0.41)

        con = build_plan(r, target_height=1080, paths=paths)
        assert con.dedup_storico is not None
        # La forchetta si stringe, e l'atteso ci sta in mezzo.
        larghezza = con.est_total_seconds / max(1e-9, con.est_best_seconds)
        assert larghezza < larghezza_teorica, (larghezza, larghezza_teorica)
        assert (con.est_best_seconds <= con.est_attesa_seconds
                <= con.est_total_seconds)
        # Un valore anomalo NON trascina la mediana (e' il motivo per cui si
        # usa lei e non la media).
        with paths.storico.open("a") as fh:
            fh.write(json.dumps({"file": "y.mkv", "dedup": 0.95}) + "\n")
        assert abs(storico.deduplica(paths).attesa - 0.39) < 0.001


@caso("le pause fra i file entrano nel totale della coda, non nel file")
def _() -> None:
    """Con dieci file e cinque minuti di respiro sono quarantacinque minuti
    di attesa reale, che sparivano dal conto. Ma la stima del SINGOLO file
    deve restare pulita: li' si chiede quanto ci vuole a finire quello."""
    import json

    from animeup.paths import Paths
    from animeup.plan import build_plan

    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    with tempfile.TemporaryDirectory() as t_:
        paths = Paths(Path(t_))
        paths.logs.mkdir(parents=True)
        piano = build_plan(r, target_height=1080, paths=paths)

        # La stima del file non contiene nessuna pausa, comunque sia
        # configurata la coda: e' una proprieta' del piano, che le pause
        # non le conosce affatto.
        assert "pausa" not in repr(piano.est_total_seconds)

        # Il totale della coda: N file -> N-1 pause.
        for quanti, pausa_min in ((1, 5), (10, 5), (10, 0)):
            attesa = max(0, quanti - 1) * pausa_min * 60
            totale = piano.est_total_seconds * quanti + attesa
            assert totale >= piano.est_total_seconds * quanti
            if quanti == 10 and pausa_min == 5:
                assert attesa == 45 * 60, attesa

        # E il fattore correttivo nasce dalle pagelle: senza, vale 1.
        from animeup import storico
        assert storico.correzione(paths) is None
        assert piano.correzione == 1.0
        with paths.storico.open("w") as fh:
            for reali, previsti in ((1060, 1000), (1080, 1000), (1040, 1000)):
                fh.write(json.dumps({"secondi": reali,
                                     "previsti": previsti}) + "\n")
        c = storico.correzione(paths)
        assert abs(c.attesa - 1.06) < 0.001, c
        # Il TETTO usa il caso peggiore visto, non la mediana.
        assert abs(c.massimo - 1.08) < 0.001, c
        piu_onesto = build_plan(r, target_height=1080, paths=paths)
        assert piu_onesto.correzione == c.attesa
        assert piu_onesto._correzione_tetto == c.massimo
        assert piu_onesto.est_total_seconds > piano.est_total_seconds * 0.5


@caso("un sorgente senza tag colore segue la convenzione SD/HD")
def _() -> None:
    """Si assumeva BT.709 per tutti: giusto sull'HD, sbagliato sul
    materiale a definizione standard, che per convenzione e' BT.601 (e su
    barre SMPTE la matrice sbagliata costa 4-5 di scostamento medio contro
    1.3-1.5). Dedurla dai pixel non funziona: provato contando i colori
    fuori gamut, sbagliava undici file noti su dodici."""
    from animeup.plan import build_plan

    for nome, atteso in (("TEST-CFR-24fps---2min.mkv", None),):
        r = probe_source(CAMPIONI / nome, with_fields=False)
        p = build_plan(r)
        _, _, space = p.encoding.color_tags
        if r.color_space in (None, "unknown"):
            atteso = "bt709" if r.geometry.height >= 720 else "smpte170m"
            assert space == atteso, (nome, r.geometry.height, space)
            assert p.encoding.swscale_matrix == (
                "bt709" if r.geometry.height >= 720 else "bt601")
        else:
            # Un tag dichiarato non si tocca mai: la convenzione vale solo
            # dove il dato manca.
            assert space == r.color_space, (nome, space, r.color_space)


# ===========================================================================
#  Le pause, le stime e le pagelle (audit del 2026-08-10)
#
#  REGOLA DI QUESTO BLOCCO: ogni caso deve ESEGUIRE il codice sorvegliato,
#  non riscriverne la formula. Un test che riscrive la formula e la confronta
#  con se stessa passa anche col difetto rimesso dentro, e da' falsa
#  sicurezza — successo davvero, su quattro casi su cinque, il 2026-08-10.
# ===========================================================================


class _PathsFinti:
    """Un `Paths` quel tanto che basta a `cli._scrivi_catena` e `_scrivi_esito`."""

    def __init__(self, radice: Path) -> None:
        self.work = radice / "JOBS"
        self.logs = radice / "records"
        self.output = radice / "OUTPUT"
        self.storico = self.logs / "history.jsonl"
        self.lanci = self.logs / "launches.jsonl"
        for d in (self.work, self.logs, self.output):
            d.mkdir(parents=True, exist_ok=True)


def _con_paths_finti(fn):
    """Esegue `fn(paths)` con `cli.PATHS` dirottato su una cartella usa-e-getta."""
    from animeup import cli

    with tempfile.TemporaryDirectory() as tmp:
        finti = _PathsFinti(Path(tmp))
        vero = cli.PATHS
        cli.PATHS = finti
        try:
            return fn(finti)
        finally:
            cli.PATHS = vero


@caso("il marcatore di catena conta le pause che restano DAVVERO")
def _pause_marcatore():
    """Si esegue `_scrivi_catena` e si rilegge il file che scrive.

    Il marcatore nasce PRIMA del riposo del file corrente: contando solo le
    pause dei successivi il residuo era corto di una pausa intera per ogni
    file dal secondo in poi, e la fascia in basso ci calcola sopra l'ora di
    fine.
    """
    import json as json_
    from animeup import cli
    from animeup.plan import build_plan
    from animeup.probe import probe_source

    piano = build_plan(probe_source(CAMPIONI / "clip20s.mkv"),
                       target_height=1080, crf=18, dedup=False)
    PAUSA, N = 5, 5

    def prova(finti):
        for k in range(1, N + 1):
            rimanenti = [piano] * (N - k + 1)
            pendente = k > 1          # il primo file di un lancio non riposa
            cli._scrivi_catena(k, N, piano, rimanenti, programma=[piano],
                               pausa_minuti=PAUSA, pausa_pendente=pendente)
            from animeup import su_disco
            dati = su_disco.loads((finti.work / ".queue").read_text())
            solo_lavoro = sum(x.est_best_seconds for x in rimanenti)
            pause_dichiarate = dati["resta_min"] - solo_lavoro
            # Le pause che verranno eseguite da qui alla fine: una prima di
            # ciascuno dei successivi, piu' quella del corrente se pendente.
            attese = ((len(rimanenti) - 1) + (1 if pendente else 0)) * PAUSA * 60
            assert abs(pause_dichiarate - attese) < 1, (k, pause_dichiarate, attese)

    _con_paths_finti(prova)


@caso("il totale della CLI conta ore e pause sugli stessi file")
def _totale_cli_coerente():
    """Ore su tutti i piani e pause sui soli da fare erano due popolazioni
    diverse: il totale prometteva il tempo anche dei già presenti, che il
    ciclo salta con "Già presente, saltato"."""
    import inspect
    from animeup import cli

    sorgente = inspect.getsource(cli.run_cmd)
    inizio = sorgente.index("da_fare = [p for p in plans")
    pezzo = sorgente[inizio:sorgente.index("if not conferma", inizio)]
    for voce in ("sum(p.est_total_seconds for p in da_fare)",
                 "sum(p.est_best_seconds for p in da_fare)"):
        assert voce in pezzo, f"il totale non usa da_fare: manca {voce}"
    # Con tutte le uscite già presenti non si annuncia nessuna pausa.
    assert "if da_fare else 0" in pezzo


@caso("`previsti` nella pagella non dipende dal fattore di correzione")
def _previsti_grezzi():
    """Si esegue `cli._scrivi_esito` e si rilegge la pagella che scrive.

    Se `previsti` portasse dentro la correzione, il rapporto fra impiegato e
    previsto misurerebbe anche se stesso e oscillerebbe invece di
    stabilizzarsi. Il caso gira con DUE correzioni molto diverse e con la
    deduplica accesa e spenta: il numero non deve muoversi.
    """
    import dataclasses
    import json as json_
    from animeup import cli, storico
    from animeup.plan import build_plan
    from animeup.probe import probe_source

    class _EsitoFinto:
        def __init__(self, dedup):
            self.seconds = 3600.0
            self.warnings = []
            self.difettosa = False
            self.dedup_saving = dedup
            self.frames_written = 100
            self.riprese = 1

    referto = probe_source(CAMPIONI / "clip20s.mkv")
    for dedup_acceso in (True, False):
        base = build_plan(referto, target_height=1080, crf=18,
                          dedup=dedup_acceso)
        letti = []
        for corr in (None,
                     storico.Correzione(1.06, 1.24, 0.98, 5),
                     storico.Correzione(2.40, 2.50, 0.40, 9)):
            piano = dataclasses.replace(base, correzione_storico=corr)

            def prova(finti, piano=piano):
                cli._scrivi_esito(piano, _EsitoFinto(0.30 if dedup_acceso else 0))
                riga = finti.storico.read_text().strip()
                from animeup import su_disco
                return su_disco.loads(riga)["previsti"]

            letti.append(_con_paths_finti(prova))
        assert max(letti) - min(letti) < 1, (dedup_acceso, letti)
        # e non e' zero per sbaglio
        assert letti[0] > 1, letti


@caso("la stima centrale porta ESATTAMENTE il fattore mediano")
def _centro_col_fattore_mediano():
    """Il centro deve valere `(grezzo_pavimento + grezzo_tetto)/2 * mediana`.

    Prima si faceva la media dei due estremi GIA' corretti e la si riportava
    indietro dividendo per la media dei fattori: torna solo se i due estremi
    poggiano sulla stessa base grezza, e con la deduplica accesa senza storia
    non e' cosi'. Restava dentro un residuo (1,104 invece di 1,060), che una
    banda di tolleranza larga non avrebbe visto — ed e' il motivo per cui
    qui si controlla il valore esatto.
    """
    import dataclasses
    from animeup import storico
    from animeup.plan import build_plan
    from animeup.probe import probe_source

    corr = storico.Correzione(attesa=1.06, massimo=1.24, minimo=0.98,
                              campioni=5)
    referto = probe_source(CAMPIONI / "clip20s.mkv")
    visti = 0
    for dedup in (True, False):
        piano = dataclasses.replace(
            build_plan(referto, target_height=1080, crf=18, dedup=dedup),
            correzione_storico=corr, dedup_storico=None)
        b, a, t = (piano.est_best_seconds, piano.est_attesa_seconds,
                   piano.est_total_seconds)
        assert b <= a <= t, (dedup, b, a, t)
        centro = (piano._grezzo_pavimento() + piano._grezzo_tetto()) / 2
        assert abs(a / centro - corr.attesa) < 1e-9, (dedup, a / centro)
        # gli estremi portano il loro, di fattore
        assert abs(b / piano._grezzo_pavimento() - corr.minimo) < 1e-9
        assert abs(t / piano._grezzo_tetto() - corr.massimo) < 1e-9
        visti += 1
    assert visti == 2


@caso("ordine ottimo <= atteso <= tetto in ogni combinazione")
def _ordine_delle_stime():
    """La matrice completa: e' l'invariante che due correzioni di fila hanno
    rotto, ed e' quello che nessun caso sorvegliava."""
    import dataclasses
    import itertools
    from animeup import storico
    from animeup.plan import build_plan
    from animeup.probe import probe_source

    referto = probe_source(CAMPIONI / "clip20s.mkv")
    base = {d: build_plan(referto, target_height=1080, crf=18, dedup=d)
            for d in (True, False)}
    correzioni = [None,
                  storico.Correzione(1.06, 1.24, 0.98, 5),
                  storico.Correzione(0.99, 1.24, 0.98, 5),   # mediana ~ minimo
                  storico.Correzione(1.23, 1.24, 0.98, 5),   # mediana ~ massimo
                  storico.Correzione(1.10, 1.10, 1.10, 5),   # tutti uguali
                  storico.Correzione(1.50, 2.50, 1.20, 5),   # minimo > 1
                  storico.Correzione(0.70, 0.90, 0.40, 5)]   # massimo < 1
    deduplicazioni = [None,
                      storico.Deduplica(.36, .26, .41, 5),
                      storico.Deduplica(0., 0., 0., 5),
                      storico.Deduplica(.41, .26, .41, 5)]
    for dedup, c, d, ratio in itertools.product(
            (True, False), correzioni, deduplicazioni, (0.0, 0.35, 0.9)):
        piano = base[dedup]
        piano = dataclasses.replace(
            piano, correzione_storico=c, dedup_storico=d,
            dedup=dataclasses.replace(piano.dedup, expected_ratio=ratio))
        b, a, t = (piano.est_best_seconds, piano.est_attesa_seconds,
                   piano.est_total_seconds)
        assert b <= a <= t, (dedup, c, d, ratio, b, a, t)
        assert b >= 0 and t > 0


# ===========================================================================
#  Lo stato di una riga di Lavorazione (audit del 2026-08-10)
# ===========================================================================

@caso("nessuna riga di Lavorazione può dire due cose diverse su se stessa")
def _stato_riga_coerente():
    """La tabella di verità delle quattro condizioni, ricostruita dal
    sorgente dell'interfaccia e verificata riga per riga.

    Ogni combinazione deve dare una chip, dei pulsanti e una decisione sulla
    coda che non si contraddicono. Il difetto trovato: la riga diceva
    "interrotto" con Riprendi e Scarta mentre la barra diceva "già lavorato,
    per ora viene saltato", perché lo stesso giudizio era scritto in due
    punti lontani con due condizioni diverse.
    """
    sorgente = (ROOT / "ui" / "app.py").read_text()
    # Una variabile SOLA per il giudizio, usata da entrambe le meta'.
    assert "gia_prodotta = archiviata and not interrotto" in sorgente
    assert "risulta_fatta = fatta or gia_prodotta" in sorgente
    assert sorgente.count("if gia_prodotta and chiave not in rifai_comunque") == 1
    assert "archiviata and chiave not in rifai_comunque" not in sorgente
    # Un'uscita difettosa non e' lavoro archiviato (la pagella si scrive lo
    # stesso, col nome dell'uscita BUONA, mentre il file e' un .DEFECTIVE).
    assert 'not esito.get("difettosa")' in sorgente
    assert "elif difettosa:" in sorgente
    # Riprendi senza referto leggeva `piano.model_key` su None.
    assert "disabled=(gpu_occupata or piano is None" in sorgente
    # Sulla riga conclusa con la cartella rimasta c'e' lo Scarta, mai il
    # Riprendi: quello resta legato a `interrotto and not concluso`.
    assert "if interrotto and (not concluso or scarta_in_conferma):" in sorgente

    def stato(uscita, pagella, difetto, interrotto):
        fatta = uscita
        archiviata = pagella and not difetto
        gia_prodotta = archiviata and not interrotto
        risulta = fatta or gia_prodotta
        rotta = pagella and difetto and not fatta
        concluso = interrotto and fatta
        chip = ("da rifare" if (rotta and not risulta) else
                "fatto" if risulta else
                "interrotto" if interrotto else "giudizio")
        pulsanti = interrotto and not concluso
        in_coda = (not fatta) and not gia_prodotta
        # Le tre contraddizioni possibili.
        assert not (chip == "interrotto" and not in_coda), "interrotto ma saltato"
        assert not (chip == "fatto" and pulsanti), "fatto ma con Riprendi"
        assert not (chip == "da rifare" and not in_coda), "da rifare ma saltato"

    for uscita in (0, 1):
        for pagella in (0, 1):
            for difetto in (0, 1):
                for interrotto in (0, 1):
                    if difetto and not pagella:
                        continue      # un difetto implica una pagella
                    stato(uscita, pagella, difetto, interrotto)



# ===========================================================================
#  I thread di salvataggio, misurati per macchina (voce 28)
# ===========================================================================

@caso("la scelta dei thread non si spegne mai da sola")
def _scelta_thread_salvataggio():
    """La regola che decide un parametro di PRODUZIONE.

    La prima versione aveva tre `and` che, quando mancava un pezzo, facevano
    PASSARE invece di scartare: bastava che una lettura di disco fallisse
    perche' la verifica sull'uscita smettesse di verificare, in silenzio.
    Qui si prova ogni modo in cui un pezzo puo' mancare.
    """
    from animeup.taratura import _scegli_salvataggio, salvataggio_predefinito

    pre = salvataggio_predefinito()
    casi = [
        ("guadagno netto e uscita uguale",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 8, "ritmo": 2.4, "impronta": ["a"]}], ["a"], 8),
        ("guadagno dentro il rumore",
         [{"thread": pre, "ritmo": 1.50, "impronta": ["a"]},
          {"thread": 8, "ritmo": 1.53, "impronta": ["a"]}], ["a"], pre),
        ("pareggio esatto sulla soglia: passa",
         [{"thread": pre, "ritmo": 1.00, "impronta": ["a"]},
          {"thread": 8, "ritmo": 1.05, "impronta": ["a"]}], ["a"], 8),
        ("uscita diversa",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 8, "ritmo": 9.0, "impronta": ["X"]}], ["a"], pre),
        ("candidato SENZA impronta: non verificabile, si scarta",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 8, "ritmo": 9.0}], ["a"], pre),
        ("RIFERIMENTO senza impronta: non si cambia niente",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 8, "ritmo": 9.0, "impronta": ["X"]}], [], pre),
        ("predefinito non misurato",
         [{"thread": 8, "ritmo": 3.0, "impronta": ["a"]}], ["a"], pre),
        ("prova fallita non vale come velocissima",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 8, "ritmo": None, "impronta": ["a"]}], ["a"], pre),
        ("ritmo booleano o negativo",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a"]},
          {"thread": 6, "ritmo": True, "impronta": ["a"]},
          {"thread": 8, "ritmo": -5, "impronta": ["a"]}], ["a"], pre),
        ("impronte di lunghezza diversa",
         [{"thread": pre, "ritmo": 1.0, "impronta": ["a", "b"]},
          {"thread": 8, "ritmo": 9.0, "impronta": ["a"]}], ["a", "b"], pre),
    ]
    for nome, prove, riferimento, atteso in casi:
        ris = _scegli_salvataggio([dict(x) for x in prove], riferimento)
        assert ris == atteso, (nome, ris, atteso)

    # L'esito non deve dipendere dall'ORDINE delle prove: prima le stesse
    # misure davano 6 o 8 a seconda di come erano elencate, perche' ogni
    # candidato veniva confrontato col migliore di turno invece che col
    # predefinito.
    import itertools
    misure = [{"thread": pre, "ritmo": 1.00, "impronta": ["a"]},
              {"thread": 6, "ritmo": 1.10, "impronta": ["a"]},
              {"thread": 8, "ritmo": 1.14, "impronta": ["a"]}]
    esiti = {_scegli_salvataggio([dict(x) for x in ordine], ["a"])
             for ordine in itertools.permutations(misure)}
    assert esiti == {8}, esiti


@caso("l'impronta guarda fotogrammi SPARSI, non solo i primi")
def _impronta_sparsa():
    """Una race di scrittura si manifesta a regime: verificare i primi sei
    file di ottanta copriva l'1,25% del lotto, e sempre la parte meno
    esposta."""
    from animeup.taratura import _impronta

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Tutti della STESSA dimensione: cosi' un cambio di contenuto non
        # puo' essere colto dalla firma delle dimensioni, e il test misura
        # davvero dove guardano i campioni crittografici. Con contenuti di
        # lunghezza diversa il caso passava anche campionando solo i primi
        # sei — cioe' col difetto storico dentro (audit del 2026-08-10).
        for i in range(80):
            (d / f"{i:08d}.png").write_bytes(bytes([i]) * 16)
        impronta = _impronta(d, quanti=6)
        assert impronta and len(impronta) == 7, impronta   # 6 + le dimensioni

        def cambia(indice: int) -> bool:
            nome = d / f"{indice:08d}.png"
            prima = nome.read_bytes()
            nome.write_bytes(b"Z" * len(prima))      # stessa dimensione
            diverso = _impronta(d, quanti=6) != impronta
            nome.write_bytes(prima)
            return diverso

        # Il PRIMO e l'ULTIMO devono essere fra i campioni: il primo era
        # l'unico guardato nella versione vecchia, l'ultimo restava fuori dal
        # campionamento a passo fisso.
        assert cambia(0), "il primo fotogramma non e' campionato"
        assert cambia(79), "l'ultimo fotogramma non e' campionato"
        # E i campioni devono essere SPARSI: almeno uno oltre la prima
        # manciata, o si torna a guardare i primi sei in fila.
        assert any(cambia(i) for i in range(20, 79)), "campioni non sparsi"
        assert _impronta(d, quanti=6) == impronta
        # cartella vuota o illeggibile -> None ("non ho potuto verificare"),
        # che e' diverso da [] e la regola di scelta lo distingue
        assert _impronta(Path(tmp) / "non-esiste") is None


@caso("mai piu' thread di salvataggio che core, anche su macchina piccola")
def _thread_non_oltre_i_core():
    """Il tetto e' fisico. Si simula una macchina da 2 core: il tetto deve
    valere davvero, non solo essere vero per caso su questo Mac."""
    import os as _os
    from animeup import backend, taratura

    vero = _os.cpu_count
    try:
        _os.cpu_count = lambda: 2
        assert taratura.core() == 2
        assert taratura.salvataggio_predefinito() == 2
        # il valore riletto in produzione non puo' scavalcare il tetto
        assert backend._thread_salvataggio(PATHS) <= 2
    finally:
        _os.cpu_count = vero
    assert taratura.core() >= 1
    assert taratura.salvataggio_predefinito() <= taratura.core()


def _otto_core(fn):
    """Il caso gira come su una macchina da 8 core, qualunque sia la vera.

    I valori provati (fino a 8 thread) presuppongono almeno 8 core, e il
    codice li taglia giustamente al numero vero: sul runner di GitHub, che
    ne ha 3, l'8 diventava impossibile e il caso falliva per la macchina,
    non per il codice."""
    import functools
    import os as _os

    @functools.wraps(fn)
    def dentro():
        vero = _os.cpu_count
        _os.cpu_count = lambda: 8
        try:
            return fn()
        finally:
            _os.cpu_count = vero
    return dentro


@caso("la produzione legge i thread misurati, e rifiuta tutto il resto")
@_otto_core
def _thread_dalla_taratura():
    import json as json_
    from animeup import backend, taratura

    class _PathsFinti:
        def __init__(self, radice):
            self.logs = radice
            self.root = radice
            self.taratura = radice / "taratura.json"
            self.work = radice / "JOBS"

    with tempfile.TemporaryDirectory() as tmp:
        finti = _PathsFinti(Path(tmp))
        macchina = taratura.chip()
        pre = taratura.salvataggio_predefinito()

        def scrivi(valore):
            (Path(tmp) / "taratura.json").write_text(json_.dumps(
                {"versione": 1,
                 "macchine": {macchina: {"jobs_salvataggio": valore}}}))

        assert backend._thread_salvataggio(finti) == pre
        scrivi(8)
        assert backend._thread_salvataggio(finti) == 8
        # `True` vale 1 per Python: passava il controllo e riduceva i thread
        # a UNO, cioe' peggio del valore fisso che questa funzione supera.
        for assurdo in (True, False, 0, -3, 999, 15.99, "otto", " 8 ", None):
            scrivi(assurdo)
            assert backend._thread_salvataggio(finti) == pre, assurdo


@caso("la prova dei thread arriva davvero fino al valore salvato")
@_otto_core
def _prova_thread_intera():
    """Fra la misura e la produzione c'era una zona scoperta: i test
    provavano la regola come funzione pura, ma nessuno verificava che
    l'impronta venisse raccolta, che il riferimento venisse popolato e che la
    scelta finisse nel registro. E' proprio lì che stava il difetto grave."""
    from animeup import backend, taratura

    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        frames = radice / "frames"
        frames.mkdir()
        for i in range(20):
            (frames / f"{i:08d}.png").write_bytes(bytes([i % 251]))

        class _PathsFinti:
            def __init__(self, r):
                self.logs = r
                self.root = r
                self.taratura = r / "taratura.json"
                self.work = r / "JOBS"

        # Un upscaler finto: veloce quanto piu' thread ha, e a 8 produce
        # un'uscita DIVERSA — cioe' il caso che la guardia deve fermare.
        def finto(src, dst, *, scale, model, paths=None, jobs=None, **resto):
            n = int(str(jobs).rsplit(":", 1)[-1])
            dst.mkdir(parents=True, exist_ok=True)
            for f in sorted(src.glob("*.png")):
                corpo = f.read_bytes()
                (dst / f.name).write_bytes(
                    corpo + (b"X" if n == 8 else b""))
            return None

        vero = backend.upscale_dir
        try:
            backend.upscale_dir = finto
            scelto, prove = taratura._prova_salvataggio(
                _PathsFinti(radice), frames, radice)
        finally:
            backend.upscale_dir = vero

        assert prove, "nessuna prova registrata"
        # L'impronta va conservata INTERA: troncarla a un elemento lascia
        # solo la firma delle dimensioni, cioe' il difetto storico ("un
        # fotogramma su ottanta") travestito da controllo.
        for x in prove:
            if not x.get("ritmo"):
                continue
            impronta = x.get("impronta") or []
            assert len(impronta) >= 2, (x["thread"], impronta)
        # L'8 produce un'uscita DIVERSA: non deve vincere mai, qualunque
        # ritmo abbia misurato. (Un altro valore puo' vincere legittimamente:
        # col finto i tempi dipendono dalle date dei file, non dai thread.)
        assert scelto != 8, (scelto, prove)
        # E l'impronta dell'8 dev'essere davvero diversa dalle altre: se
        # fossero tutte uguali, il finto non starebbe provando niente.
        per_thread = {x["thread"]: x.get("impronta") for x in prove
                      if x.get("ritmo")}
        assert per_thread.get(8) and per_thread[8] != per_thread.get(
            taratura.salvataggio_predefinito()), per_thread


@caso("la taratura prevede anche il passo dei thread di salvataggio")
def _preventivo_col_passo_nuovo():
    from animeup import taratura

    tappe = taratura.preventivo(PATHS)
    nomi = [n for n, _ in tappe]
    assert "thread di salvataggio" in nomi, nomi
    # ogni tappa deve costare qualcosa, o la barra le darebbe larghezza zero
    assert all(s > 0 for _, s in tappe), tappe



# ===========================================================================
#  Il resoconto di fine coda: identita' del lancio (audit del 2026-08-10)
# ===========================================================================

@caso("il resoconto sopravvive a una coda FERMATA a meta'")
def _resoconto_coda_fermata():
    """Il caso piu' frequente di tutti — il Ferma tutto del mattino — e per
    un giro non produceva piu' niente: la prima versione deduceva l'identita'
    della catena da "quanti file mancano al totale", e una coda fermata a
    quel totale non ci arriva mai."""
    import json as json_
    from animeup import monitor

    class _P:
        def __init__(self, d):
            self.logs = d
            self.lanci = d / "lanci.jsonl"

    def rec(**kw):
        base = dict(inizio=100, fine=200, previsti=[], riusciti=[],
                    falliti=[], scartati=[], interrotti=[], secondi=0,
                    avvisi=0, dedup_medio=None, pausa_minuti=5, lancio="L1")
        base.update(kw)
        return base

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        def scrivi(righe):
            (d / "lanci.jsonl").write_text(
                "".join(json_.dumps(r, ensure_ascii=False) + "\n"
                        for r in righe))

        # coda singola fermata dopo il primo file
        scrivi([rec(lancio="", previsti=["a", "b", "c"], riusciti=["a"],
                    secondi=90)])
        r = monitor.ultimo_lancio(_P(d))
        assert r and r["riusciti"] == ["a"] and len(r["previsti"]) == 3, r

        # maratona a due gruppi, il secondo fermato: si fondono lo stesso
        scrivi([rec(previsti=["a", "b"], riusciti=["a", "b"], secondi=100),
                rec(previsti=["c", "d"], riusciti=["c"], secondi=50)])
        r = monitor.ultimo_lancio(_P(d))
        assert r and len(r["riusciti"]) == 3 and r["secondi"] == 150, r

        # due lanci DIVERSI di fila non devono mai fondersi: prima bastava
        # che avessero lo stesso numero di file per sommare ore mai esistite
        scrivi([rec(lancio="VECCHIO", previsti=["v1", "v2", "v3"],
                    riusciti=["v1"], secondi=3000, inizio=1, fine=3001),
                rec(lancio="NUOVO", previsti=["n1", "n2"],
                    riusciti=["n1", "n2"], secondi=60)])
        r = monitor.ultimo_lancio(_P(d))
        assert r and r["previsti"] == ["n1", "n2"] and r["secondi"] == 60, r

        # record malformati: la pagina non deve rompersi (ultimo_lancio gira
        # a ogni disegno)
        for storto in ({"lancio": "L", "fine": 1, "inizio": None,
                        "dedup_medio": "molto", "previsti": "bcd"},
                       {"lancio": "L", "fine": 1, "pausa_minuti": [1],
                        "secondi": True, "avvisi": "tre"}):
            scrivi([storto, rec()])
            monitor.ultimo_lancio(_P(d))     # non deve sollevare


@caso("ogni comando di un lancio porta la stessa etichetta")
def _etichetta_del_lancio():
    """E' l'unica cosa che lega i pezzi di una maratona spezzata per
    modello: dedurla dai numeri e' gia' costato una regressione."""
    import inspect
    from animeup import cli

    sorgente = inspect.getsource(cli.run_cmd)
    assert 'etichetta = lancio or' in sorgente
    # tutte le scritture del diario devono portarla
    assert sorgente.count("lancio=etichetta") == 3, sorgente.count("lancio=etichetta")
    # e l'identita' nasce PRIMA delle uscite anticipate
    assert (sorgente.index("etichetta = lancio or")
            < sorgente.index("if not plans:")), "identita' troppo tardi"

    interfaccia = (ROOT / "ui" / "app.py").read_text()
    assert '"--launch", etichetta_lancio' in interfaccia


@caso("il tempo bruciato da un file fallito non diventa una pausa")
def _tempo_dei_falliti():
    """`secondi` e' il tempo lavorato; la modale ricava le pause come
    differenza con l'orologio. Un file fallito che non contribuiva niente
    faceva comparire le sue ore come riposo."""
    import inspect
    from animeup import cli

    sorgente = inspect.getsource(cli.run_cmd)
    # ogni `continue` del giro dei file, dopo l'avvio del cronometro, deve
    # aver sommato il tempo speso
    dopo = sorgente[sorgente.index("_partito = _t.monotonic()"):]
    for etichetta in ("interrotti.append", "falliti.append"):
        pezzo = dopo[dopo.index(etichetta):]
        pezzo = pezzo[:pezzo.index("continue")]
        assert "secondi_lavorati +=" in pezzo, etichetta



# Registrazione VERA di una lavorazione (lungo.mkv, 600 fotogrammi, Apple M4,
# 10/08/2026): terne (secondi dall'avvio, fase, fotogrammi fatti) lette da
# `monitor.lavori()` ogni 2 secondi. Serve a rigiocare il ritmo su dati veri
# invece che su una curva inventata: il ritmo reale dell'upscale, contato sui
# PNG, era 4.20 f/s.
_REGISTRAZIONE = [
    (2.0, "estrazione", 47), (4.2, "estrazione", 267), (6.2, "estrazione", 455),
    (8.2, "elaborazione", 0), (10.2, "elaborazione", 0),
    (12.2, "elaborazione", 8), (14.2, "elaborazione", 16),
    (16.3, "elaborazione", 26), (18.3, "elaborazione", 34),
    (20.3, "elaborazione", 42), (22.3, "elaborazione", 52),
    (24.3, "elaborazione", 60), (26.3, "elaborazione", 68),
    (28.3, "elaborazione", 76), (30.3, "elaborazione", 99),
    (32.4, "elaborazione", 130), (34.4, "elaborazione", 138),
    (36.4, "elaborazione", 146), (38.4, "elaborazione", 154),
    (40.4, "elaborazione", 164), (42.4, "elaborazione", 172),
    (44.4, "elaborazione", 180), (46.5, "elaborazione", 188),
    (48.5, "elaborazione", 198), (50.5, "elaborazione", 206),
    (52.5, "elaborazione", 214), (54.5, "elaborazione", 224),
    (56.5, "elaborazione", 232), (58.5, "elaborazione", 240),
    (60.5, "elaborazione", 248), (62.5, "elaborazione", 258),
    (64.6, "elaborazione", 266), (66.6, "elaborazione", 274),
    (68.6, "elaborazione", 282), (70.6, "elaborazione", 292),
    (72.6, "elaborazione", 300), (74.7, "elaborazione", 308),
    (76.7, "elaborazione", 316), (78.7, "elaborazione", 324),
    (80.7, "elaborazione", 334), (82.7, "elaborazione", 342),
    (84.7, "elaborazione", 350), (86.7, "elaborazione", 358),
    (88.7, "elaborazione", 366), (90.8, "elaborazione", 374),
    (92.8, "elaborazione", 384), (94.8, "elaborazione", 392),
    (96.8, "elaborazione", 400), (98.8, "elaborazione", 408),
    (100.8, "elaborazione", 416),
]
def _ritmo_vero() -> float:
    """Il ritmo di riferimento, RICAVATO dalla registrazione e non scritto a
    mano: la pendenza dell'indice su tutta l'elaborazione.

    Deve essere l'indice e non i PNG prodotti. La riga della Lavorazione fa
    `(lav.totale - lav.fatti) / ritmo`, e sia `totale` sia `fatti` sono
    indici sulla linea del tempo del sorgente: i fotogrammi che restano
    conterranno ripetizioni come quelli gia' passati, quindi e' l'indice a
    prevedere quanto manca. Il conteggio dei PNG da' un numero piu' basso
    (qui il 10% in meno, che e' la deduplica) ed e' la grandezza sbagliata
    per questa divisione."""
    p = [(t, n) for t, f, n in _REGISTRAZIONE if f == "elaborazione" and n]
    return (p[-1][1] - p[0][1]) / (p[-1][0] - p[0][0])


def _ritmi_mostrati():
    """Rigioca la registrazione attraverso il codice vero e restituisce, per
    ogni giro dell'upscale, la coppia (istante, ritmo mostrato o None)."""
    from animeup import monitor

    campioni, stati, fuori = {}, {}, []
    for t, fase, fatti in _REGISTRAZIONE:
        monitor.aggiorna_campioni(campioni, stati, [("x", fase, fatti)], t)
        if fase == "elaborazione":
            fuori.append((t, monitor.andatura(campioni.get("x", []))))
    return fuori


@caso("il ritmo non mescola i fotogrammi estratti con quelli ingranditi")
def _ritmo_niente_estrazione():
    """`fatti` conta cose diverse a seconda della fase: in estrazione i
    fotogrammi tirati fuori (decine al secondo), in elaborazione quelli
    ingranditi (pochi al secondo), col secondo conteggio che riparte da zero.
    Senza azzerare la finestra al passaggio, i campioni dell'estrazione
    restano dentro e il ritmo pubblicato e' quello dell'estrazione.

    Misurato togliendo l'azzeramento da questa registrazione: primo numero
    pubblicato 97.14 f/s a t=8.2, cioe' VENTUNO VOLTE il vero (4.605), e
    cade sull'assert del primo numero qui sotto."""
    vero = _ritmo_vero()
    ritmi = [(t, r) for t, r in _ritmi_mostrati() if r]
    assert ritmi, "nessun ritmo pubblicato in tutta la registrazione"
    # il PRIMO numero che l'utente vede deve gia' essere buono: pubblicarne
    # uno sbagliato e correggerlo dopo un minuto e mezzo e' peggio che tacere.
    # E' questa la riga che uccide il difetto dell'estrazione (97.14 contro
    # 4.605): il ciclo sotto e' una seconda rete, non la prima.
    t_primo, r_primo = ritmi[0]
    scarto = abs(r_primo - vero) / vero
    assert scarto < 0.10, f"primo ritmo {r_primo:.2f} a {t_primo}s ({scarto:.0%})"
    # NESSUN numero pubblicato, mai, deve essere fuori scala. La forchetta e'
    # asimmetrica per un motivo misurato: verso l'alto un transitorio esiste
    # ed e' legittimo — `fatti` e' un indice sulla linea del tempo del
    # sorgente, quindi attraversando una sequenza di fotogrammi ripetuti
    # avanza a scatti (qui +31% al massimo, riassorbito in un minuto) —
    # mentre verso il basso, su questa registrazione, il minimo osservato e'
    # 0.907 del vero e non c'e' meccanismo noto che lo spinga piu' giu'.
    for t, r in ritmi:
        assert 0.85 < r / vero < 1.45, f"ritmo {r:.2f} a {t}s, vero {vero:.2f}"


@caso("prima del primo fotogramma ingrandito il ritmo tace")
def _ritmo_tace_nel_tempo_morto():
    """Fra la fine dell'estrazione e il primo fotogramma ci sono scansione
    della deduplica, collegamenti e caricamento del modello: `fatti` resta a
    zero. Uno zero non e' un ritmo lento, e ancorava la finestra al tempo
    morto. Si verifica che quei giri non lascino campioni."""
    from animeup import monitor

    campioni, stati = {}, {}
    for t, fase, fatti in _REGISTRAZIONE:
        monitor.aggiorna_campioni(campioni, stati, [("x", fase, fatti)], t)
        if fase == "elaborazione" and not fatti:
            assert not campioni.get("x"), f"campione a zero tenuto a {t}s"
    # il tetto della finestra si verifica CHIEDENDONE uno diverso da quello
    # di serie: confrontare il risultato con la costante che lo produce non
    # potrebbe mai fallire.
    campioni, stati = {}, {}
    for i in range(20):
        monitor.aggiorna_campioni(
            campioni, stati, [("x", "elaborazione", i + 1)], float(i), quanti=5)
    assert len(campioni["x"]) == 5, len(campioni["x"])
    assert campioni["x"][0] == (15.0, 16), campioni["x"][0]


@caso("la finestra del ritmo si azzera a ogni cambio di fase")
def _ritmo_azzera_al_cambio():
    from animeup import monitor

    campioni, stati = {}, {}
    for t in (0.0, 2.0, 4.0):
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", int(t) + 1)], t)
    assert len(campioni["x"]) == 3
    # Il cambio turno della codifica azzera, e SEGUITA a non campionare per
    # tutti i giri che dura: e' un tempo morto di minuti a GPU ferma, e i
    # campioni piatti facevano esplodere la ETA alla ripartenza. Il
    # conteggio qui resta uguale all'ultimo buono (5), che e' quello che il
    # filesystem produce davvero — passando un numero piu' basso sarebbe la
    # regola 3 a scartarlo, e questa verifica direbbe poco.
    for t in (6.0, 8.0, 10.0):
        monitor.aggiorna_campioni(campioni, stati, [("x", "codifica blocco", 5)], t)
        assert not campioni.get("x"), f"campione tenuto durante la codifica a {t}s"
    # Un cambio QUALUNQUE deve azzerare. Non si passa da "codifica blocco",
    # che azzererebbe per conto suo e renderebbe la verifica cieca (il primo
    # tentativo di questo caso lo faceva, e passava anche senza la regola).
    # Il giro per l'estrazione e' anche realistico: al confine fra due
    # blocchi la fase ci torna davvero, quando il conteggio dei fotogrammi
    # estratti non coincide con la stima nella firma.
    for t in (12.0, 14.0, 16.0):
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", int(t) * 10)], t)
    assert len(campioni["x"]) == 3
    monitor.aggiorna_campioni(campioni, stati, [("x", "estrazione", 900)], 18.0)
    assert campioni["x"] == [(18.0, 900)], campioni["x"]
    monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", 130)], 20.0)
    assert campioni["x"] == [(20.0, 130)], campioni["x"]
    # Un lavoro che sparisce non lascia residui utilizzabili: la finestra si
    # svuota e dello stato restano SOLO i turni di codifica misurati, che
    # appartengono al file e non alla sessione (vedi il caso apposta). Fase,
    # riferimento e cronometro non devono sopravvivere: sono proprio i valori
    # che, se restassero, mentirebbero alla ripresa.
    monitor.aggiorna_campioni(campioni, stati, [], 22.0)
    assert not campioni
    assert set(stati["x"]) <= {"turni_n", "turni_somma"}, stati["x"]


@caso("un conteggio che torna indietro non entra nella finestra")
def _ritmo_conteggio_allindietro():
    """A fine blocco la pipeline cancella le cartelle `chunk*` prima che il
    segmento finito sia registrato nello stato: per qualche giro `fatti` cala
    restando in "elaborazione". Quel campione faceva da ancora per tutta la
    finestra — misurato: ~25 fps mostrati contro 4 veri, e il tempo che resta
    da due ore a venti minuti.

    La scena riproduce quello che il filesystem fa davvero: il conteggio
    scende a un valore qualunque fra l'inizio del blocco e il picco (dipende
    da quanti PNG il `rmtree` ha gia' portato via), poi `_registra()` scrive
    il segmento e il conteggio TORNA ESATTAMENTE AL PICCO. La prima stesura
    faceva ripartire da 69 sopra il picco: un errore di cinquecento secondi
    che non veniva dal codice ma dalla scena, e che costringeva la
    tolleranza a essere larga il triplo del necessario."""
    from animeup import monitor

    PICCO, TOTALE, RITMO = 3951, 34000, 4.0

    # il valore in cui il giro cade mentre le cartelle spariscono: a inizio
    # blocco, a meta' cancellazione, e il caso di confine in cui non e'
    # ancora sceso per niente (uguale al picco: non deve essere scartato,
    # o dopo ogni blocco si resterebbe muti per una finestra intera)
    for sporco in (2000, 3100, PICCO):
        campioni, stati = {}, {}
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", PICCO)], -5.0)
        monitor.aggiorna_campioni(campioni, stati, [("x", "codifica blocco", PICCO)], 0.0)
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", sporco)], 5.0)
        # `_registra()` ha scritto il segmento: si riparte dal picco esatto
        for i in range(0, 20):
            monitor.aggiorna_campioni(
                campioni, stati,
                [("x", "elaborazione", PICCO + int(RITMO * 2) * i)], 10.0 + 2 * i)
        # LA regola, detta senza numeri: il valore sporco non diventa mai
        # l'ancora della finestra. Togliendo la regola 3 l'ancora e' 2000 o
        # 3100 e questa riga cade da sola.
        assert campioni["x"][0][1] >= PICCO, (
            f"ancora {campioni['x'][0]} col giro sporco a {sporco}")
        ritmo = monitor.andatura(campioni["x"])
        resta = (TOTALE - campioni["x"][-1][1]) / ritmo
        vero = (TOTALE - campioni["x"][-1][1]) / RITMO
        # Forchetta asimmetrica, e misurata. Sotto il picco: stima ESATTA.
        # Nel caso di confine (conteggio uguale al picco) il campione viene
        # tenuto — giusto, perche' uno fermo davvero deve far scendere il
        # ritmo — e si porta dentro i secondi morti del turno di codifica:
        # +13.2% di attesa, pessimista e riassorbito. Sopra, invece, il
        # difetto rende la stima OTTIMISTA di sei volte (1245s contro 7405),
        # ed e' la direzione che non si tollera.
        scarto = (resta - vero) / vero
        assert -0.05 < scarto < 0.20, (
            f"restano {resta:.0f}s invece di {vero:.0f}s ({scarto:+.0%}) "
            f"col giro sporco a {sporco}")


@caso("aprire la pagina durante la codifica di un blocco non falsa il ritmo")
def _ritmo_pagina_aperta_in_codifica():
    """La regola 3 ha bisogno di un valore buono di riferimento. Se il PRIMO
    giro che la sessione vede cade in "codifica blocco" — e quella fase
    occupa il 62-72% del tempo di un blocco, misurato dal vivo — il
    riferimento restava vuoto e il valore sporco del confine entrava come
    ancora: 32.9 fps mostrati e «restano 00:16:19» invece di 02:14:27.
    Qui NON si mette nessun campione buono prima: e' il punto cieco."""
    from animeup import monitor

    campioni, stati = {}, {}
    monitor.aggiorna_campioni(campioni, stati, [("x", "codifica blocco", 1620)], 0.0)
    monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", 810)], 2.0)
    for i in range(1, 15):
        monitor.aggiorna_campioni(
            campioni, stati, [("x", "elaborazione", 1620 + 8 * i)], 2.0 + 2 * i)
    assert campioni["x"][0][1] >= 1620, f"ancora sporca {campioni['x'][0]}"
    ritmo = monitor.andatura(campioni["x"])
    assert abs(ritmo - 4.0) < 0.2, f"ritmo {ritmo:.2f} invece di 4.00"


@caso("dopo un ribasso vero del conteggio il ritmo torna, non sparisce")
def _ritmo_ribasso_definitivo():
    """La regola 3 scarta i cali. Ma il conteggio puo' ribassarsi DAVVERO
    restando in "elaborazione": la pipeline riscrive l'elenco dei segmenti
    con un estremo piu' basso, per esempio riprendendo con blocchi di
    dimensione diversa. Senza una via d'uscita si scartava per sempre: o
    silenzio per ore, o — misurato — un ritmo congelato calcolato su istanti
    vecchi, che sembra vivo. Si pretende che il numero torni, e che sia
    quello giusto."""
    from animeup import monitor

    campioni, stati = {}, {}
    for i in range(10):
        monitor.aggiorna_campioni(
            campioni, stati, [("y", "elaborazione", 2000 + 8 * i)], float(i * 2))
    assert abs(monitor.andatura(campioni["y"]) - 4.0) < 0.1
    muti, primo = 0, None
    for i in range(60):
        monitor.aggiorna_campioni(
            campioni, stati, [("y", "elaborazione", 810 + 8 * i)], 20.0 + 2 * i)
        r = monitor.andatura(campioni.get("y", []))
        if not r:
            muti += 1
        elif primo is None:
            primo = r
    # mentre si scarta non si pubblica un numero vecchio...
    assert muti, "ha continuato a pubblicare un ritmo durante il ribasso"
    # ...ma il silenzio non puo' durare all'infinito
    assert muti < 20, f"{muti} giri senza numero: la via d'uscita non scatta"
    assert primo is not None and abs(primo - 4.0) < 0.2, (
        f"dopo il ribasso il ritmo vale {primo}")


@caso("il ritmo insegue l'andatura vera quando la GPU rallenta")
def _ritmo_insegue():
    """La finestra e' mobile per un motivo, scritto in `andatura`: una media
    dall'inizio darebbe una ETA che si allunga mentre la guardi. Ma la
    lunghezza della finestra non era fissata da niente — passava anche 1000,
    cioe' la finestra spenta, che e' esattamente cio' che il modulo dice di
    voler evitare. Qui la macchina rallenta da 8 a 1 fotogramma al secondo
    (succede: un altro lavoro che parte, il termico che rientra) e si
    pretende che il numero mostrato ci arrivi in un tempo ragionevole."""
    from animeup import monitor

    campioni, stati, t, fatti = {}, {}, 0.0, 0
    for _ in range(60):                      # regime veloce
        fatti += 16
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", fatti)], t)
        t += 2.0
    assert abs(monitor.andatura(campioni["x"]) - 8.0) < 0.1
    inizio_lento = t
    for _ in range(60):                      # la GPU rallenta di otto volte
        fatti += 2
        monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", fatti)], t)
        t += 2.0
        if abs(monitor.andatura(campioni["x"]) - 1.0) < 0.15:
            break
    ritardo = t - inizio_lento
    # con la finestra di serie ci vuole poco piu' della finestra stessa;
    # con la finestra spenta non ci arriverebbe mai
    assert abs(monitor.andatura(campioni["x"]) - 1.0) < 0.15, (
        f"dopo {ritardo:.0f}s il ritmo mostrato e' ancora "
        f"{monitor.andatura(campioni['x']):.2f} invece di 1.0")
    assert ritardo < 150, f"ci ha messo {ritardo:.0f}s ad accorgersene"


@caso("la durata dei turni di codifica si misura, e solo se e' credibile")
def _turni_misurati():
    """Il tempo che resta deve sommare i turni di codifica dei blocchi che
    mancano, e la loro durata si misura su QUESTA lavorazione: la taratura
    li sottostima del 49% (234 s previsti contro 280/463/303 misurati),
    perche' il turno comprende anche la ricostruzione dei fotogrammi
    duplicati. Si tiene la media, non l'ultimo: prendendo l'ultimo l'errore
    peggiore passava da -24% a +35%.

    La misura vale solo se il turno e' stato guardato per intero, con la
    cadenza vera dell'interfaccia. Questa funzione gira SOLO mentre la
    scheda Lavorazione e' a video: passando altrove i giri si fermano ma lo
    stato resta, e senza accorgersene si misuravano 910 secondi per un turno
    da 350 (uscendo a meta') oppure 10 secondi (rientrando poco prima della
    fine). In riga diventavano +148% e -35%."""
    from animeup import monitor

    def corsa(passi, passo=5.0):
        """Rigioca una sequenza (fase, fotogrammi, quanti giri) alla cadenza
        vera dell'interfaccia, e rende (campioni, stati)."""
        campioni, stati, t = {}, {}, 0.0
        for fase, fatti, quanti in passi:
            for _ in range(quanti):
                monitor.aggiorna_campioni(campioni, stati, [("x", fase, fatti)], t)
                t += passo
        return campioni, stati

    # un turno intero, guardato dall'inizio alla fine: 60 giri da 5 s = 300 s
    _, stati = corsa([("elaborazione", 10, 4), ("codifica blocco", 20, 60),
                      ("elaborazione", 30, 4)])
    assert abs(monitor.turno_misurato(stati, "x") - 300.0) < 0.01
    # due turni, 300 e 100: la media e' 200, non l'ultimo
    _, stati = corsa([("elaborazione", 10, 4), ("codifica blocco", 20, 60),
                      ("elaborazione", 30, 4), ("codifica blocco", 40, 20),
                      ("elaborazione", 50, 4)])
    assert abs(monitor.turno_misurato(stati, "x") - 200.0) < 0.01

    # --- i casi in cui NON si deve misurare niente ---
    campioni, stati = {}, {}
    # si esce dalla pagina a meta' turno e si torna dopo un quarto d'ora
    monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", 800)], 0.0)
    monitor.aggiorna_campioni(campioni, stati, [("x", "codifica blocco", 810)], 5.0)
    monitor.aggiorna_campioni(campioni, stati, [("x", "elaborazione", 820)], 920.0)
    assert monitor.turno_misurato(stati, "x") is None, "turno lungo per finta"
    # si rientra dieci secondi prima della fine del turno
    campioni, stati = {}, {}
    monitor.aggiorna_campioni(campioni, stati, [("y", "elaborazione", 800)], 0.0)
    monitor.aggiorna_campioni(campioni, stati, [("y", "codifica blocco", 810)], 900.0)
    monitor.aggiorna_campioni(campioni, stati, [("y", "elaborazione", 820)], 910.0)
    assert monitor.turno_misurato(stati, "y") is None, "turno corto per finta"
    # l'orologio di parete torna indietro durante il turno
    campioni, stati = {}, {}
    monitor.aggiorna_campioni(campioni, stati, [("z", "elaborazione", 10)], 1000.0)
    monitor.aggiorna_campioni(campioni, stati, [("z", "codifica blocco", 20)], 1005.0)
    monitor.aggiorna_campioni(campioni, stati, [("z", "elaborazione", 30)], 1002.0)
    assert monitor.turno_misurato(stati, "z") is None, "turno negativo in media"


@caso("i turni misurati sopravvivono a un Ferma, la forma vecchia non uccide la pagina")
def _stati_robusti():
    """Due difese su una struttura che ha gia' cambiato forma tre volte.

    La prima: i turni appartengono al FILE, non alla sessione. Un solo giro
    in cui il lavoro non risulta vivo — cosa che capita a ogni Ferma e
    Riprendi — buttava le misure e faceva ricadere la stima sulla taratura,
    che sottostima del 49%.

    La seconda: una forma vecchia sopravvissuta in una sessione aperta
    faceva morire la pagina in modo PERMANENTE, perche' l'eccezione partiva
    prima della riscrittura e il valore malato restava li'."""
    from animeup import monitor

    campioni, stati, t = {}, {}, 0.0
    for fase, quanti in (("elaborazione", 4), ("codifica blocco", 40),
                         ("elaborazione", 4)):
        for _ in range(quanti):
            monitor.aggiorna_campioni(campioni, stati, [("v", fase, 10)], t)
            t += 5.0
    assert abs(monitor.turno_misurato(stati, "v") - 200.0) < 0.01
    monitor.aggiorna_campioni(campioni, stati, [], t)      # il lavoro sparisce
    assert not campioni, "campioni di un lavoro morto tenuti"
    assert abs(monitor.turno_misurato(stati, "v") - 200.0) < 0.01, "turni buttati"

    # una forma vecchia (tupla) non deve sollevare, e deve autoripararsi
    campioni, stati = {}, {"w": ("elaborazione", 20, 0)}
    monitor.aggiorna_campioni(campioni, stati, [("w", "elaborazione", 30)], 0.0)
    assert isinstance(stati["w"], dict), stati["w"]
    assert monitor.turno_misurato(stati, "w") is None


@caso("il tempo che resta somma i turni di codifica che mancano")
def _tempo_che_resta_somma_i_turni():
    """Il conto viveva dentro l'interfaccia e nessun test lo eseguiva: sei
    mutazioni contemporanee — fra cui SOTTRARRE i turni invece di sommarli —
    lasciavano la suite verde. Ora sta in `monitor` e si esegue."""
    from animeup import monitor

    # 1000 fotogrammi mancanti a 4 f/s = 250 s di solo upscale
    solo = monitor.tempo_che_resta(1000, 2000, 4.0)
    assert abs(solo - 250.0) < 0.01, solo
    # con 3 turni ancora da fare (blocco 1 di 4) da 300 s l'uno: +900 s
    con = monitor.tempo_che_resta(1000, 2000, 4.0, blocchi_totali=4,
                                  blocco_n=1, turno=300.0)
    assert abs(con - 1150.0) < 0.01, con
    assert con > solo, "i turni vanno SOMMATI, non sottratti"
    # l'ultimo blocco non ha turni dopo di se'
    ultimo = monitor.tempo_che_resta(1900, 2000, 4.0, blocchi_totali=4,
                                     blocco_n=4, turno=300.0)
    assert abs(ultimo - 25.0) < 0.01, ultimo
    # e nemmeno un file a blocco unico
    unico = monitor.tempo_che_resta(1000, 2000, 4.0, blocchi_totali=1,
                                    blocco_n=1, turno=300.0)
    assert abs(unico - 250.0) < 0.01, unico
    # blocchi non noti (zero): non si inventa nessun turno
    ignoti = monitor.tempo_che_resta(1000, 2000, 4.0, turno=300.0)
    assert abs(ignoti - 250.0) < 0.01, ignoti
    # senza turno misurato ne' stimato si somma solo l'upscale
    senza = monitor.tempo_che_resta(1000, 2000, 4.0, blocchi_totali=4,
                                    blocco_n=1, turno=None)
    assert abs(senza - 250.0) < 0.01, senza
    # senza ritmo non si risponde: meglio tacere che inventare
    assert monitor.tempo_che_resta(1000, 2000, None) is None
    assert monitor.tempo_che_resta(1000, 2000, 0.0) is None


@caso("il tempo che resta viene dai blocchi finiti, non dall'ultimo minuto")
def _tempo_dai_blocchi_finiti():
    """Un Monogatari da 11 blocchi: 35 minuti l'uno, ma la GPU rallentata per
    qualche minuto faceva dire alla riga 6:52 invece di 4:40 (utente)."""
    import json as _json
    from animeup import monitor

    with tempfile.TemporaryDirectory() as t:
        c = Path(t)
        (c / "segments").mkdir()
        blocco, totale, ciclo = 2958, 32368, 35 * 60.0
        avvio = 1_000_000.0
        (c / "running.lock").write_text("1")
        os.utime(c / "running.lock", (avvio, avvio))
        (c / "dedup.json").write_text("{}")
        os.utime(c / "dedup.json", (avvio + 420, avvio + 420))
        segmenti = []
        for i in range(2):
            nome = f"seg{i * blocco:08d}-{(i + 1) * blocco:08d}.mkv"
            (c / "segments" / nome).write_text("x")
            quando = avvio + 420 + ciclo * (i + 1)
            os.utime(c / "segments" / nome, (quando, quando))
            segmenti.append([i * blocco, (i + 1) * blocco, nome])
        (c / "state.json").write_text(_json.dumps({"segments": segmenti}))

        misura = monitor.ritmo_blocchi(c)
        assert misura is not None
        assert abs(misura[0] - ciclo / blocco) < 1e-6, misura
        assert misura[1] == 2 * blocco
        # 25 minuti dentro il terzo blocco: ne restano 10, più gli altri 8
        # (l'ultimo è il resto, 2.788 fotogrammi, e costa in proporzione)
        adesso = misura[2] + 25 * 60
        resta = monitor.resto_da_blocchi(misura, totale, adesso, blocco)
        atteso = ciclo / blocco * (totale - 2 * blocco) - 25 * 60
        assert abs(resta - atteso) < 0.01, (resta, atteso)
        assert 4.5 * 3600 < resta < 4.8 * 3600, resta
        # il blocco in corso lento non fa promettere meno dei blocchi dopo
        tardi = monitor.resto_da_blocchi(misura, totale, misura[2] + 3 * 3600, blocco)
        assert abs(tardi - ciclo / blocco * (totale - 3 * blocco)) < 0.01, tardi

        # un'interruzione: la corsa ripartita dopo i due segmenti non li
        # misura (conterebbero anche il tempo da spento)
        os.utime(c / "running.lock", (avvio + 10 * 3600, avvio + 10 * 3600))
        assert monitor.ritmo_blocchi(c) is None
    with tempfile.TemporaryDirectory() as t:
        # nessun blocco finito: si torna al ritmo misurato
        assert monitor.ritmo_blocchi(Path(t)) is None
    # arrivati oltre il totale non si promette tempo negativo
    assert monitor.tempo_che_resta(2100, 2000, 4.0) == 0.0


@caso("il tempo che resta arriva a fine file, non a fine upscale")
def _tempo_che_resta_conta_la_coda():
    """Dopo l'ultimo blocco non c'e' un altro turno, ma la sua codifica va
    fatta lo stesso e poi c'e' il montaggio. Ignorarli rendeva la riga
    ottimista proprio alla fine, dove la si guarda di piu': misurato,
    diceva 1:14 quando ne servivano 5:32.

    La coda costa in proporzione ai fotogrammi dell'ultimo blocco, che sono
    il resto della divisione e quindi meno di un blocco pieno. Verificato
    sulla corsa a quattro blocchi: 568 su 810 di un turno medio da 349 s
    danno 244 s contro 258 misurati."""
    from animeup import monitor

    # ultimo blocco in corso: nessun turno davanti, ma la coda si', e vale
    # 568/810 di un turno
    resta = monitor.tempo_che_resta(2900, 2998, 4.0, blocchi_totali=4,
                                    blocco_n=4, blocco_totale=810, turno=349.0)
    atteso = (2998 - 2900) / 4.0 + 349.0 * (2998 - 3 * 810) / 810
    assert abs(resta - atteso) < 0.01, (resta, atteso)
    assert abs(resta - 269.3) < 1.0, resta
    # senza la coda il numero sarebbe meno della meta'
    senza = monitor.tempo_che_resta(2900, 2998, 4.0, blocchi_totali=4,
                                    blocco_n=4, turno=349.0)
    assert senza < resta / 2, (senza, resta)
    # un blocco pieno esatto: la coda vale un turno intero
    pieno = monitor.tempo_che_resta(3240, 3240, 4.0, blocchi_totali=4,
                                    blocco_n=4, blocco_totale=810, turno=300.0)
    assert abs(pieno - 300.0) < 0.01, pieno
    # file a blocco unico: nessun turno in mezzo, ma la coda c'e'
    unico = monitor.tempo_che_resta(800, 810, 4.0, blocchi_totali=1,
                                    blocco_n=1, blocco_totale=810, turno=300.0)
    assert abs(unico - (2.5 + 300.0)) < 0.01, unico
    # dati incoerenti (blocchi che non tornano col totale): niente coda
    # inventata, si resta al conto di prima
    storto = monitor.tempo_che_resta(100, 2998, 4.0, blocchi_totali=2,
                                     blocco_n=1, blocco_totale=10, turno=300.0)
    assert abs(storto - ((2998 - 100) / 4.0 + 300.0)) < 0.01, storto


@caso("il turno stimato dalla taratura scala con i pixel dell'uscita")
def _turno_da_taratura():
    """Ripiego per il PRIMO blocco, quando non c'e' ancora niente da
    misurare. La formula e' la stessa di `plan._fuori_gpu`: se cambia una
    delle due, le stime del piano e quelle della riga divergono in silenzio.

    Verifica col caso vero della corsa a quattro blocchi: 810 fotogrammi a
    2560x1440 con codifica misurata 6.16 f/s danno 233.8 s, contro i 280,
    463 e 303 poi misurati davvero."""
    from animeup import monitor

    t = monitor.turno_da_taratura(810, 2560, 1440, 6.16)
    assert abs(t - 233.77) < 0.5, t
    # a 1080p (i pixel a cui la codifica e' tarata) il fattore vale 1
    assert abs(monitor.turno_da_taratura(810, 1920, 1080, 6.16)
               - 810 / 6.16) < 0.01
    # e a 2160p costa quattro volte tanto
    a = monitor.turno_da_taratura(100, 1920, 1080, 8.0)
    b = monitor.turno_da_taratura(100, 3840, 2160, 8.0)
    assert abs(b / a - 4.0) < 0.001, (a, b)
    # dati mancanti: niente numero inventato
    assert monitor.turno_da_taratura(0, 1920, 1080, 8.0) is None
    assert monitor.turno_da_taratura(810, 0, 1080, 8.0) is None
    # una codifica dichiarata a zero non deve dividere per zero
    assert monitor.turno_da_taratura(810, 1920, 1080, 0.0) > 0


@caso("il link della taratura vive DENTRO la sua riga di sidebar")
def _taratura_nella_sidebar():
    """Il pulsante che apre la taratura e' posizionato dal CSS a destra
    della riga "Taratura", e quel CSS e' agganciato a
    `[data-testid="stSidebar"]`: se la chiamata esce dal contenitore della
    riga, il pulsante finisce in cima all'area principale, orfano della sua
    etichetta, e chi cerca la taratura non la trova piu'.

    E' successo davvero: una de-indentazione di quattro spazi durante un
    lavoro sul CSS lo ha spostato, e ci e' voluto un giorno e la
    segnalazione dell'utente per accorgersene — nessun test guardava dove
    finiscono gli elementi.

    Si verifica sull'ALBERO SINTATTICO, non sul testo: cosi' non passa una
    riscrittura che sposta la chiamata mantenendo le stesse parole."""
    import ast

    albero = ast.parse((ROOT / "ui" / "app.py").read_text())

    def chiave(nodo):
        """La stringa passata come `key=` a questa chiamata, se c'e'."""
        for kw in getattr(nodo, "keywords", []):
            if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                return kw.value.value
        return None

    def contiene_bottone(nodo):
        return any(isinstance(n, ast.Call) and chiave(n) == "apriTaratura"
                   for n in ast.walk(nodo))

    dentro = False
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.With):
            continue
        # il `with` che apre il contenitore della riga della taratura
        apre_la_riga = any(
            isinstance(e.context_expr, ast.Call)
            and chiave(e.context_expr) == "cTarRiga"
            for e in nodo.items)
        if apre_la_riga and contiene_bottone(nodo):
            dentro = True
            break
    assert dentro, ("il pulsante della taratura non sta dentro il contenitore "
                    "cTarRiga: finira' nell'area principale")


@caso("la griglia dei thread di salvataggio arriva fino ai core della macchina")
def _candidati_salvataggio():
    """Provare solo 2, 4, 6, 8 bastava sul Mac mini, dove il ritmo e' piatto
    oltre il 4 (4.507, 4.485, 4.437) e quindi il 4 e' un ottimo vero. Sul
    MacBook a 14 core saliva ancora fino all'estremo (3.241, 6.135, 8.927,
    9.97): l'8 non era una scelta, era un bordo, e si perdeva throughput.

    Fra i candidati ci deve essere SEMPRE il numero di core: se vince
    quello, l'ottimo non sta fuori dalla griglia ma sul limite fisico della
    macchina, e la differenza fra le due cose e' tutta."""
    from unittest import mock
    from animeup import taratura

    def con_core(n):
        with mock.patch.object(taratura, "core", lambda: n):
            return taratura.candidati_salvataggio()

    # macchina grande: si arriva oltre l'8, e i core ci sono sempre
    assert con_core(14) == [2, 4, 6, 8, 12, 14], con_core(14)
    assert con_core(24) == [2, 4, 6, 8, 12, 16, 24], con_core(24)
    # macchina di questo Mac mini
    assert con_core(10) == [2, 4, 6, 8, 10], con_core(10)
    # macchina piccola: niente prove impossibili, e il predefinito resta
    assert con_core(4) == [2, 4], con_core(4)
    assert con_core(2) == [2], con_core(2)
    assert con_core(1) == [1], con_core(1)
    # in ogni caso il numero di core c'e', e nessun candidato lo supera
    for n in (1, 2, 3, 4, 6, 8, 10, 14, 16, 32):
        c = con_core(n)
        assert n in c, (n, c)
        assert max(c) <= n, (n, c)
        assert c == sorted(set(c)), (n, c)

    # chi stima la durata e chi esegue le prove devono contare le STESSE
    # prove: quando i due conti stavano in due posti, la barra prometteva
    # quattro prove e il giro ne faceva sei
    sorgente = (ROOT / "src" / "animeup" / "taratura.py").read_text()
    assert sorgente.count("candidati_salvataggio()") >= 2, sorgente.count(
        "candidati_salvataggio()")


@caso("l'elenco dei sorgenti ha una cache sola, col tempo che dichiara")
def _cache_dei_sorgenti():
    """`load_library` aveva DUE `@st.cache_data` impilati, 30 secondi sopra
    8: quello esterno catturava il risultato di quello interno, quindi il
    tempo vero era 30 e un file appena messo in INPUT si faceva aspettare
    quattro volte il tempo dichiarato nel commento.

    Si verifica sull'albero sintattico, cosi' non basta riscrivere la riga
    con altre parole per aggirarlo."""
    import ast

    albero = ast.parse((ROOT / "ui" / "app.py").read_text())
    trovata = None
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "load_library":
            trovata = nodo
            break
    assert trovata is not None, "load_library non c'e' piu'"

    cache = []
    for d in trovata.decorator_list:
        f = d.func if isinstance(d, ast.Call) else d
        if isinstance(f, ast.Attribute) and f.attr.startswith("cache_"):
            cache.append(d)
    assert len(cache) == 1, f"{len(cache)} decoratori di cache impilati"
    ttl = next((kw.value.value for kw in cache[0].keywords
                if kw.arg == "ttl" and isinstance(kw.value, ast.Constant)), None)
    # Corto per forza: e' il tempo massimo che un file nuovo in INPUT puo'
    # restare invisibile a chi lo ha appena copiato.
    assert ttl is not None and 0 < ttl <= 15, f"ttl {ttl}"


@caso("un file gia' letto non viene riletto a ogni scansione")
def _scan_non_rilegge():
    """`library.scan` lancia un ffprobe PER FILE, e l'interfaccia la ripete da
    sola ogni pochi secondi: su sedici file erano sedici processi ogni volta
    (0,37 s misurati) per tutte le ore di una lavorazione, sullo stesso disco
    su cui la lavorazione scrive. I metadati di un file che non e' cambiato
    non possono cambiare, quindi si rileggono solo quando cambia davvero
    qualcosa — nome, dimensione o data di modifica."""
    import shutil, tempfile
    from pathlib import Path
    from animeup import library
    from animeup.ffmpeg import FFprobe

    letture = []
    vero = FFprobe.format_and_streams

    def contando(self, path):
        letture.append(Path(path).name)
        return vero(self, path)

    sorgente = next(CAMPIONI.glob("*.mkv"), None) or next(CAMPIONI.glob("*.mp4"))
    with tempfile.TemporaryDirectory() as tmp:
        cartella = Path(tmp)
        uno = cartella / "uno.mkv"
        shutil.copy2(sorgente, uno)
        library._METADATI.clear()
        originale = FFprobe.format_and_streams
        FFprobe.format_and_streams = contando
        try:
            a = library.scan(cartella)
            assert len(a) == 1 and letture == ["uno.mkv"], (a, letture)
            # seconda scansione: nessuna rilettura
            letture.clear()
            b = library.scan(cartella)
            assert not letture, f"riletto senza motivo: {letture}"
            assert [e.name for e in b] == ["uno.mkv"]
            assert b[0].width == a[0].width and b[0].duration == a[0].duration

            # un file NUOVO si legge, il vecchio no
            due = cartella / "due.mkv"
            shutil.copy2(sorgente, due)
            letture.clear()
            c = library.scan(cartella)
            assert letture == ["due.mkv"], letture
            assert len(c) == 2

            # un file CAMBIATO si rilegge: la chiave non e' solo il nome
            import os, time
            os.utime(uno, (time.time() + 10, time.time() + 10))
            letture.clear()
            library.scan(cartella)
            assert letture == ["uno.mkv"], letture

            # un file sparito non lascia residui nel dizionario
            due.unlink()
            library.scan(cartella)
            assert all(Path(k[0]).name != "due.mkv" for k in library._METADATI), \
                library._METADATI
        finally:
            FFprobe.format_and_streams = originale
            library._METADATI.clear()


@caso("«Consigliato per ciascuno» applica davvero il consigliato")
def _consigliato_per_ciascuno():
    """Era il RITIRO della scelta: ogni riga tornava al suo "vero", che su un
    file gia' convertito e' il modello della pagella. Su una serie lavorata
    ieri con animevideov3 il comando non cambiava niente — prometteva il
    consigliato e restituiva lo storico.

    Si verifica sull'albero sintattico che il ramo "auto" SCRIVA il modello
    consigliato, invece di limitarsi a togliere il file dall'insieme delle
    scelte."""
    import ast

    sorgente = (ROOT / "ui" / "app.py").read_text()
    albero = ast.parse(sorgente)
    fn = next((n for n in ast.walk(albero)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_applica_modello_tutti"), None)
    assert fn is not None, "_applica_modello_tutti non c'e' piu'"

    # il ramo che confronta la scelta con "auto"
    ramo = None
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.If):
            continue
        for c in ast.walk(nodo.test):
            if isinstance(c, ast.Constant) and c.value == "auto":
                ramo = nodo
                break
        if ramo is not None:
            break
    assert ramo is not None, "il ramo 'auto' non c'e' piu'"

    corpo = "".join(ast.dump(n) for n in ramo.body)
    assert "recommend" in corpo, (
        "il ramo 'auto' non chiama recommend: promette il consigliato e "
        "restituisce altro")
    # e non si limita a togliere dalla lista delle scelte
    assert "discard" not in corpo or "add" in corpo, corpo[:200]

    # il consigliato per un 720p e' CUGAN, non animevideov3: e' il caso da
    # cui e' nata la segnalazione
    from animeup.models import recommend
    assert recommend(720).model == "cugan", recommend(720).model
    assert recommend(400).model == "animevideov3", recommend(400).model


@caso("l'orario di fine dice il GIORNO quando non e' oggi")
def _quando_finisce():
    """«fra le 23:48 e le 02:43» non dice a chi legge di sera che le 02:43
    sono di domani: il lettore deve dedurlo dall'ordine dei numeri. Su una
    coda che dura giorni — quattro episodi da dieci ore arrivano a
    dopodomani — diventa indecifrabile. Segnalato dall'utente su entrambe le
    macchine."""
    import datetime as dt
    from animeup.report import quando_finisce

    base = dt.datetime(2026, 8, 11, 22, 0).timestamp()      # oggi alle 22:00
    def q(h1, h2):
        return quando_finisce(base + h1 * 3600, base + h2 * 3600, base)

    # stessa giornata: nessun giorno, sarebbe rumore
    assert q(0.5, 1.0) == "fra le 22:30 e le 23:00", q(0.5, 1.0)
    # si scavalla la mezzanotte: il giorno sta sull'estremo che lo cambia
    assert q(1.8, 4.7) == "fra le 23:48 e le 02:42 di domani", q(1.8, 4.7)
    # entrambi domani: un giorno solo, alla fine
    assert q(11, 13) == "fra le 09:00 e le 11:00 di domani", q(11, 13)
    # giorni DIVERSI: si nominano tutti e due
    assert q(25.8, 28.7) == "fra le 23:48 di domani e le 02:42 di dopodomani", q(25.8, 28.7)
    # oltre dopodomani si passa alla data, che "fra tre giorni" non si legge
    assert q(50, 74) == "fra le 00:00 del 14/08 e le 00:00 del 15/08", q(50, 74)
    # un orario solo
    assert quando_finisce(base + 30 * 3600, base + 30 * 3600, base) == \
        "alle 04:00 di dopodomani"
    assert quando_finisce(base + 3600, base + 3600, base) == "alle 23:00"


@caso("la versione e' scritta in un posto solo, e le due copie coincidono")
def _versione_coerente():
    """Il numero vive in `animeup.__version__`: CLI e interfaccia lo leggono
    da li'. `pyproject.toml` pero' ne tiene una copia sua, che e' l'unica che
    puo' divergere — ed e' proprio quella che finisce nel pacchetto."""
    import animeup

    testo = (ROOT / "pyproject.toml").read_text()
    riga = next(r for r in testo.splitlines() if r.startswith("version"))
    dichiarata = riga.split("=", 1)[1].strip().strip('"')
    assert dichiarata == animeup.__version__, (dichiarata, animeup.__version__)
    # e nessuno se la riscrive a mano da qualche parte
    interfaccia = (ROOT / "ui" / "app.py").read_text()
    assert "from animeup import __version__" in interfaccia
    assert f'v{animeup.__version__}"' not in interfaccia, "versione scritta a mano"


@caso("l'interfaccia delega a monitor la finestra del ritmo")
def _interfaccia_usa_la_funzione():
    interfaccia = (ROOT / "ui" / "app.py").read_text()
    assert "monitor.aggiorna_campioni(" in interfaccia
    # e non tiene piu' una sua copia della regola
    assert "del serie[:-30]" not in interfaccia


@caso("nessun posizionamento ancorato: i due motori non lo fanno uguale")
def _niente_ancoraggio():
    """L'ancoraggio CSS (`anchor-name`, `position-anchor`, `anchor()`) e'
    stato tolto del tutto, e non per gusto: misurato dentro Safari 26.6 con
    gli Apple Events, su venti fumetti undici finivano al posto giusto e
    NOVE a seicento pixel di distanza, piantati rispetto alla finestra. Su
    Chrome gli stessi venti erano tutti a scarto zero.

    Nessuna guardia `@supports` puo' separare i due casi: Safari dichiara di
    supportare tutte e sette le proprieta' dell'ancoraggio, e infatti la
    guardia irrobustita non cambio' niente.

    Il ripiego — posizione assoluta e meta' larghezza di spostamento — e'
    stato misurato a scarto ZERO in entrambi i motori. Costa il taglio dei
    fumetti delle righe in cima all'area che scorre; in cambio nessun
    fumetto finisce dall'altra parte dello schermo.

    Se qualcuno rimette l'ancoraggio, questo test glielo ricorda."""
    import re

    css = (ROOT / "ui" / "app.py").read_text()
    vive = []
    for riga in css.splitlines():
        nuda = riga.strip()
        if nuda.startswith(("*", "/*", "#")):
            continue                      # i commenti raccontano la storia
        if re.search(r"(anchor-name:|position-anchor:|anchor\(|anchor-center)", nuda):
            vive.append(nuda[:70])
    assert not vive, ("e' tornato il posizionamento ancorato, che su Safari "
                      f"sbaglia di seicento pixel: {vive[:3]}")


@caso("la scheda del modello dichiara che il suo tempo e' di SOLO upscale")
def _scheda_modello_dice_solo_upscale():
    """Sulla scheda di ogni modello il numero e' `fotogrammi / velocita`:
    il solo ingrandimento, senza deduplica, codifica e turni fra i blocchi.
    Il riquadro sopra, «EPISODIO INTERO», mostra invece il totale.

    Diceva «per l'intero file» in tutti e due i posti. A 1080p la differenza
    e' piccola — 11m contro 13m — e passa inosservata; a 1440p diventa 11m
    contro 20m, e chi legge pensa a un errore dell'app.

    Il test lega la formula alla frase: se qualcuno cambia il calcolo per
    farci stare il totale, la frase va cambiata con lui."""
    import re

    testo = (ROOT / "ui" / "app.py").read_text()
    i = testo.index("plan.frames / velocita")
    # La frase sta nel catalogo: qui si lega la formula alla sua chiave.
    intorno = testo[i - 200:i + 200]
    assert 't("conf.velocita"' in intorno, (
        "la scheda del modello non usa piu' la frase del solo upscale")
    frase = i18n.catalogo("it")["conf.velocita"]
    assert "solo upscale" in frase and "upscale only" in i18n.catalogo("en")["conf.velocita"], (
        "la scheda del modello e' tornata a dire qualcosa d'altro: quel "
        "numero e' il solo upscale e deve dirlo")
    assert "per l'intero file" not in frase, (
        "«per l'intero file» sulla scheda: e' la stessa frase del riquadro "
        "EPISODIO INTERO, che pero' mostra il TOTALE")


@caso("un avviso non tiene su disco la cartella di lavoro, un difetto si'")
def _avviso_non_conserva():
    """`JobResult.ok` decide se la CLI cancella la cartella di lavoro, che
    contiene TUTTI i fotogrammi sorgente estratti: 31 GB per un episodio da
    24 minuti a 720p, 156 per un film da due ore, 350 a 1080p.

    Chiedeva anche `not self.warnings`, cioe' una nota qualsiasi conservava
    quei giga per sempre. L'unico avviso comparso nei registri veri e' «Durata
    in parte stimata: il file e' stato interrotto e ripreso» — una nota sul
    cronometro che si portava dietro trenta giga. Con una coda di film,
    bastavano due avvisi per riempire un disco da 1 TB e far fallire tutto il
    resto della coda (scenario descritto da Interstellar0verdrive, verificato nel codice).

    La regola: si conserva per un DIFETTO — il file prodotto e' inservibile e
    serve capire perche' — non per una nota."""
    import dataclasses
    from animeup.pipeline import JobResult

    campi = {f.name: f for f in dataclasses.fields(JobResult)}
    obbligatori = [n for n, f in campi.items()
                   if f.default is dataclasses.MISSING
                   and f.default_factory is dataclasses.MISSING]

    def esito(**kw):
        args = {n: (None if n == "output" else 0) for n in obbligatori}
        args.update(kw)
        return JobResult(**args)

    intero = dict(frames_written=100, frames_expected=100)
    assert esito(**intero, warnings=["nota innocua"]).ok, (
        "un avviso conserva ancora la cartella: sono 31 GB per episodio")
    assert not esito(**intero, difetti=["file rotto"]).ok, (
        "un difetto DEVE conservare la cartella: senza il lavoro, il guasto "
        "non e' diagnosticabile")
    assert not esito(frames_written=99, frames_expected=100).ok, (
        "fotogrammi mancanti: la cartella va conservata")
    # e l'avviso resta un'informazione, non sparisce
    assert esito(**intero, warnings=["nota"]).warnings == ["nota"]


@caso("lo spazio dedicato e' un TETTO, e i blocchi non degenerano mai")
def _blocchi_ragionevoli():
    """La dimensione dei blocchi la calcola `plan.dimensiona_blocchi`, che
    questo test CHIAMA invece di riscriverla. La versione precedente rifaceva
    la formula al suo interno: mutando il codice di produzione non cadeva,
    cioe' sorvegliava una copia (trovato in audit, stessa classe di difetto
    gia' vista in tre test la mattina dell'11/08).

    I tre modi in cui il dimensionamento ha degenerato, tutti coi numeri
    veri:
    - il numero chiesto all'utente governava i soli fotogrammi ingranditi,
      quindi con 40 GB impostati il picco era 165 GB su un film di due ore;
    - col budget appena stretto si stringeva fino al pavimento: 10 GB
      davano 12 blocchi e 40 GB ne davano 44, cioe' PIU' spazio dava un
      risultato PEGGIORE;
    - col tetto di 40 GB per blocco e fotogrammi 4K da 13,8 MB uscivano 59
      blocchi su un film di due ore e 88 su tre, col disco mezzo vuoto."""
    from animeup.plan import (BYTES_PER_PIXEL_SOURCE, BYTES_PER_PIXEL_UPSCALED,
                              EST_BITRATE_MBPS_1080P, BLOCCHI_MINIMI,
                              BLOCCHI_MASSIMI, dimensiona_blocchi)

    def scenario(w, h, minuti, dedicato, tw=1920, th=1080, libero=600.0):
        """Ingressi preparati come in `build_plan`, poi LA FUNZIONE VERA."""
        n = int(minuti * 60 * 23.976)
        src = w * h * BYTES_PER_PIXEL_SOURCE / 1_048_576
        up = tw * th * BYTES_PER_PIXEL_UPSCALED / 1_048_576
        uscita = EST_BITRATE_MBPS_1080P * (tw*th)/(1920*1080) * (minuti*60)/8/1024
        incompr = n * src / 1024 + 2 * uscita
        disponibile = min(float(dedicato), libero * 0.85) - incompr
        cs = dimensiona_blocchi(n, up, disponibile, libero * 0.85 - incompr)
        return cs, max(1, -(-n // cs)), incompr + cs * up / 1024

    _, blocchi, _ = scenario(1280, 720, 4, 200)
    assert blocchi >= BLOCCHI_MINIMI, f"solo {blocchi} blocchi su una clip"

    # PIU' SPAZIO NON PUO' DARE PIU' BLOCCHI: e' la proprieta' che il difetto
    # delle 21:00 violava, ed e' l'unica che si possa controllare senza
    # rifare i conti.
    prec = None
    for gb in (10, 20, 40, 60, 80, 120, 200, 400):
        _, blocchi, _ = scenario(1280, 720, 24, gb)
        if prec is not None:
            assert blocchi <= prec, (
                f"con {gb} GB escono {blocchi} blocchi, con meno spazio ne "
                f"uscivano {prec}: piu' spazio non puo' peggiorare")
        prec = blocchi

    for w, h, minuti, tw, th, gb, libero in (
            (1920, 1080, 120, 3840, 2160, 500, 2000),
            (1920, 1080, 180, 3840, 2160, 500, 2000),
            (1920, 1080, 120, 3840, 2160, 100, 2000),
            (1280,  720,  24, 1920, 1080,  40,   45)):
        _, blocchi, _ = scenario(w, h, minuti, gb, tw, th, libero)
        assert blocchi <= BLOCCHI_MASSIMI + 1, (
            f"{minuti}m {tw}x{th} con {gb} GB: {blocchi} blocchi, cioe' "
            f"{blocchi * 1.16:.0f} minuti di solo costo fisso")

    _, _, picco = scenario(1280, 720, 24, 40)
    assert picco <= 41, f"picco {picco:.0f} GB contro 40 dedicati"


@caso("una pausa aperta non sopravvive alla fine della lavorazione")
def _pausa_non_resta_aperta():
    """`.sospeso` dice «dei processi sono congelati ADESSO», e
    `sospensione()` conta da quell'istante fino a ora. Se il marcatore
    sopravvive alla lavorazione che lo aveva, quel conto cresce di un secondo
    al secondo per sempre.

    Trovato in audit provandolo davvero: pausa, poi Ferma tutto. I processi
    muoiono tutti — verificato, zero residui — ma il marcatore resta. Il file
    ripreso il giorno dopo avrebbe registrato in pagella «lavoro meno pausa»
    con una pausa di ore, cioe' un tempo NEGATIVO, e le pagelle sono i dati
    da cui l'app impara a stimare i file successivi.

    La cura sta in `pipeline`, subito dopo la presa del lucchetto: se stiamo
    cominciando, nessun processo nostro puo' essere congelato."""
    import ast

    sorgente = (ROOT / "src" / "animeup" / "pipeline.py").read_text()
    assert "(self.work / SOSPESO).unlink(missing_ok=True)" in sorgente, (
        "sparita la chiusura del marcatore di pausa all'avvio: una pausa "
        "rimasta aperta fara' registrare tempi negativi")

    # e la chiusura deve stare DOPO la presa del lucchetto, non prima: prima
    # cancellerebbe il marcatore di una lavorazione altrui ancora viva
    albero = ast.parse(sorgente)
    testo = sorgente.splitlines()
    riga_lucchetto = next(n for n, r in enumerate(testo)
                          if "self._lucchetto_mio = True" in r)
    riga_pulizia = next(n for n, r in enumerate(testo)
                        if "(self.work / SOSPESO).unlink" in r)
    assert riga_pulizia > riga_lucchetto, (
        "la pulizia del marcatore avviene PRIMA di aver preso il lucchetto: "
        "cosi' si cancella la pausa di una lavorazione altrui ancora viva")

    # la contabilita' non deve mai poter sottrarre piu' di quanto abbia contato
    from animeup.pipeline import sospensione, PAUSE_TOTALI
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / PAUSE_TOTALI).write_text("-999")
    assert sospensione(d) == 0.0, "una pausa negativa AGGIUNGE tempo alla durata"


@caso("la deduplica esatta si legge dalla mappa, non dai blocchi")
def _dedup_esatta_dalla_mappa():
    """La mappa completa esiste PRIMA del primo blocco, e i blocchi mentono.

    Misurato il 12/08 su Koyomimonogatari 12 (deduplica vera 31,8%): i dieci
    blocchi vanno dal 3,9% al 54,5%, e chi si fidasse del primo stimerebbe il
    54,5% — cioe' il file un terzo piu' corto del vero. Sono i numeri veri di
    quel file, rimessi qui dentro perche' la regola non si perda.
    """
    import json
    import tempfile
    from pathlib import Path
    from animeup import monitor

    d = Path(tempfile.mkdtemp())
    # 17.503 fotogrammi, 11.939 tenuti: i numeri veri del file.
    tenuti = list(range(11939))
    (d / "dedup.json").write_text(json.dumps({"total": 17503, "keep": tenuti}))
    quota, totale = monitor.dedup_esatta(d)
    # Il valore ESATTO, non "circa": una tolleranza larga lascia passare un
    # errore di un fotogramma nel denominatore, che e' il modo tipico in cui
    # questi conti si rompono (provato in audit: uno scarto di 0,0002 sotto
    # una soglia di 0,001 non veniva visto).
    assert quota == 1 - 11939 / 17503, f"deduplica letta male: {quota}"
    assert totale == 17503, "il totale serve per il filtro di somiglianza"

    # Il primo blocco da solo direbbe 54,5%: la funzione dei blocchi resta,
    # ma non deve essere quella su cui si stima.
    (d / "state.json").write_text(json.dumps(
        {"blocchi": [{"da": 0, "a": 1752, "tenuti": 797}]}))
    parziale, quanti = monitor.dedup_misurata(d)
    assert quanti == 1 and abs(parziale - 0.545) < 0.002
    assert abs(parziale - quota) > 0.2, (
        "se le due misure coincidessero questo test non direbbe piu' niente")

    # niente mappa, niente numero: mai un ripiego inventato
    vuota = Path(tempfile.mkdtemp())
    assert monitor.dedup_esatta(vuota) is None
    (vuota / "dedup.json").write_text('{"total": 0, "keep": []}')
    assert monitor.dedup_esatta(vuota) is None, "un totale a zero divide per zero"


@caso("lo storico stima su file che durano quanto questo")
def _storico_guarda_i_simili():
    """Il caso vero: undici puntate da ~17.000 fotogrammi al 32% e un film da
    34.765 al 6,5%. Chiedere la stima per un altro film non deve tirare
    dentro le puntate, ed e' esattamente l'errore che il 12/08 e' costato il
    47% su Tsukimonogatari."""
    import json
    import tempfile
    from pathlib import Path
    from animeup import storico
    from animeup.paths import Paths

    radice = Path(tempfile.mkdtemp())
    (radice / "records").mkdir()
    (radice / "OUTPUT" / "JOBS").mkdir(parents=True)
    righe = [{"dedup": q, "fotogrammi": f, "secondi": 100.0, "previsti": 100.0}
             for q, f in [(0.322, 18098), (0.257, 15657), (0.365, 17508),
                          (0.352, 17580), (0.276, 18343), (0.325, 19472),
                          (0.065, 34765), (0.070, 33900)]]
    (radice / "records" / "history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in righe))
    p = Paths(radice)

    puntata = storico.deduplica(p, simili_a=17500)
    assert puntata is not None and 0.30 < puntata.attesa < 0.34, (
        f"una puntata deve stimare come le puntate: {puntata}")
    film = storico.deduplica(p, simili_a=34000)
    assert film is not None and film.attesa < 0.10, (
        f"un film lungo il doppio non stima come le puntate: {film}")

    # Con meno di due simili si torna a TUTTO: una forchetta larga su tutto
    # e' meglio di una stretta su niente.
    solitario = storico.deduplica(p, simili_a=3000)
    assert solitario is not None and solitario.campioni == 8

    # La lavorazione VIVA entra prima di lasciare una pagella: e' il punto
    # che salva la coda quando il primo file dell'infornata non somiglia a
    # niente di gia' visto.
    cartella = radice / "OUTPUT" / "JOBS" / "in-corso"
    cartella.mkdir()
    (cartella / "dedup.json").write_text(json.dumps(
        {"total": 34000, "keep": list(range(31000))}))
    dopo = storico.deduplica(p, simili_a=34000)
    assert dopo is not None and dopo.campioni == 3, (
        "la misura del file in corso non e' stata contata")

    # Una mappa monca — "tenuti zero fotogrammi", cioe' deduplica 1.0 — non
    # deve entrare nella mediana: sarebbe un file che non costa niente. Le
    # pagelle quel valore lo scartano da sempre, le misure vive entravano
    # dritte (audit del 12/08).
    (cartella / "dedup.json").write_text(json.dumps({"total": 34000, "keep": []}))
    monco = storico.deduplica(p, simili_a=34000)
    assert monco is not None and monco.massimo < 1.0, (
        f"una mappa che non tiene nessun fotogramma e' entrata: {monco}")

    # Una pagella di taglia IGNOTA non e' simile a niente: trattarla come
    # simile a tutto rimetteva dentro proprio i file che il filtro esclude.
    (radice / "records" / "history.jsonl").write_text("\n".join(
        [json.dumps(r) for r in righe]
        + [json.dumps({"dedup": 0.99, "secondi": 10.0, "previsti": 10.0})]))
    (cartella / "dedup.json").write_text(json.dumps(
        {"total": 34000, "keep": list(range(31000))}))
    pulito = storico.deduplica(p, simili_a=17500)
    assert pulito is not None and pulito.massimo < 0.5, (
        f"una pagella senza taglia e' entrata fra i simili: {pulito}")

    # UN solo simile: il centro lo decide lui, la forchetta resta larga. E'
    # il caso vero di Tsukimonogatari 02, che ha un unico precedente della
    # sua taglia: stimarlo col 32% delle puntate rifarebbe l'errore del 47%.
    import shutil
    shutil.rmtree(cartella)
    solo_uno = [r for r in righe if r["fotogrammi"] != 33900]
    (radice / "records" / "history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in solo_uno))
    unico = storico.deduplica(p, simili_a=34765)
    assert unico is not None and abs(unico.attesa - 0.065) < 1e-6, (
        f"il solo file della stessa taglia non decide il centro: {unico}")
    assert unico.minimo < 0.10 < unico.massimo, (
        "con un solo campione la forchetta deve restare quella larga")
    assert not unico.affidabile, "un aneddoto non deve spacciarsi per storia"


@caso("la deduplica misurata azzera l'incertezza sulla deduplica")
def _dedup_nota_stringe_la_forchetta():
    """Con la mappa in mano non si stima piu' quanti fotogrammi ripetuti ci
    saranno: si sa. Quel che resta e' lo scarto del modello, che sulle
    pagelle del 12/08 vale l'1,7% in media."""
    import inspect
    from animeup import plan as plan_mod

    firma = inspect.signature(plan_mod.build_plan)
    assert "dedup_nota" in firma.parameters, (
        "sparito il parametro con cui il piano riceve la deduplica vera")

    sorgente = inspect.getsource(plan_mod.build_plan)
    assert "misurata=True" in sorgente, (
        "la deduplica misurata non si dichiara tale: l'interfaccia non puo' "
        "piu' distinguerla da una previsione, e il fumetto direbbe che la "
        "durata dipende da qualcosa che invece e' gia' noto")

    # E l'interfaccia deve passarglielo davvero, altrimenti il parametro
    # esiste e non lo usa nessuno.
    app = (ROOT / "ui" / "app.py").read_text()
    assert "dedup_nota=nota" in app, "plan_for non passa la deduplica misurata"
    assert "dedup_esatta" in app, "l'interfaccia non legge la mappa vera"

    # Una deduplica misurata pari a ZERO — un file senza un solo fotogramma
    # ripetuto — e' un numero falso in Python: senza il controllo esplicito
    # la mediana degli ALTRI file rientrava di soppiatto al posto della
    # misura, e il file veniva promesso ore piu' corto del vero.
    from pathlib import Path as _P
    campione = next(iter(sorted(CAMPIONI.glob("*.mkv"))), None)
    if campione is not None:
        from animeup import library
        rapporto = library.analyse(_P(campione))

        # La mappa vale solo se parla di QUESTA estrazione. La cartella di
        # lavoro non dipende dai parametri: cambiare bersaglio o accendere il
        # denoise riusa la stessa cartella, e dentro c'e' una mappa contata
        # su un altro insieme di fotogrammi.
        quanti = plan_mod.build_plan(rapporto).frames
        giusta = plan_mod.build_plan(rapporto, dedup_nota=(0.42, quanti))
        assert giusta.dedup.misurata and giusta.dedup.expected_ratio == 0.42, (
            "una mappa che parla di questo file dev'essere usata")
        sbagliata = plan_mod.build_plan(rapporto,
                                        dedup_nota=(0.42, quanti * 2))
        assert not sbagliata.dedup.misurata, (
            "una mappa contata su un'altra estrazione e' stata usata lo stesso")
        # e la coppia dev'essere quella che `dedup_esatta` restituisce
        assert "return max(0.0, 1.0 - quanti / totale), totale" in (
            ROOT / "src" / "animeup" / "monitor.py").read_text(), (
            "dedup_esatta non torna piu' anche il conteggio: il piano non "
            "puo' piu' verificare che la mappa sia sua")

        misurato = plan_mod.build_plan(rapporto, dedup_nota=0.0)
        spenta = plan_mod.build_plan(rapporto, dedup=False)
        assert misurato.dedup.misurata and not misurato.dedup_incerta
        assert abs(misurato.est_attesa_seconds
                   - spenta.est_attesa_seconds) < spenta.est_attesa_seconds * 0.02, (
            "con deduplica misurata a zero la stima deve valere quanto una "
            "lavorazione senza deduplica, non quanto la mediana degli altri")
        # e i tre numeri devono restare in ordine in ogni regime
        for pl in (misurato, spenta, plan_mod.build_plan(rapporto)):
            assert (pl.est_best_seconds <= pl.est_attesa_seconds
                    <= pl.est_total_seconds), "forchetta fuori ordine"


@caso("il residuo della coda usa la misura, non la promessa")
def _fascia_impara():
    """La fascia in basso sottraeva l'orologio a una promessa fatta al lancio
    e non imparava mai: per quindici ore ha ripetuto 10h21 su un file che ne
    stava impiegando 15h14, mentre la riga sopra — che il ritmo lo misura —
    diceva il numero giusto."""
    from animeup import monitor

    app = (ROOT / "ui" / "app.py").read_text()
    assert "def _resto_misurato(" in app, (
        "il conto del residuo misurato non e' piu' in un posto solo: riga e "
        "fascia possono divergere sullo stesso file")

    # e la CLI deve dichiarare la quota del file corrente, altrimenti non
    # c'e' niente da sostituire
    cli = (ROOT / "src" / "animeup" / "cli.py").read_text()
    for campo in ('"file_min"', '"file_max"'):
        assert campo in cli, f"il marcatore della catena non scrive {campo}"

    # Il conto vero, esercitato: coda da 10.000-14.000 s di cui 6.000-9.000
    # sono il file in corso, marcatore scritto un'ora fa.
    marcatore = {"resta_min": 10000, "resta_max": 14000, "scritto": 1000.0,
                 "file_min": 6000, "file_max": 9000}
    adesso = 4600.0                                  # 3.600 s dopo lo scritto

    vecchio = monitor.residuo_coda(marcatore, None, adesso)
    assert vecchio == (6400.0, 10400.0), (
        f"senza misura si invecchia il marcatore e basta: {vecchio}")

    nuovo = monitor.residuo_coda(marcatore, 3000, adesso)
    assert nuovo == (7000.0, 8000.0), (
        f"con la misura la quota del file in corso si SOSTITUISCE: {nuovo}")

    # Un marcatore vecchio, senza i due campi, non deve far contare il file
    # corrente due volte: si resta al conto di prima.
    antico = {k: v for k, v in marcatore.items() if not k.startswith("file_")}
    assert monitor.residuo_coda(antico, 3000, adesso) == (6400.0, 10400.0), (
        "un marcatore senza `file_max` non deve entrare nel regime nuovo")

    # Niente marcatore, marcatore vuoto, marcatore senza residui: None, mai
    # un'eccezione e mai un numero inventato.
    for cattivo in (None, {}, {"resta_max": 0}, {"resta_max": "x"}, []):
        assert monitor.residuo_coda(cattivo, 3000, adesso) is None, cattivo

    # Campi storti: si degrada, non si esplode, e l'ordine regge.
    storto = {"resta_min": "x", "resta_max": 14000, "file_max": None,
              "scritto": "y"}
    mn, mx = monitor.residuo_coda(storto, None, adesso)
    assert mn <= mx

    # L'ordine dei due estremi non deve poter rompersi con nessuna misura.
    for misura in (0, 1, 3000, 99999, -50):
        mn, mx = monitor.residuo_coda(marcatore, misura, adesso)
        assert mn <= mx, f"forchetta rovesciata con misura {misura}"

    # La fascia deve prendere il lavoro vivo PER NOME e solo nelle fasi in
    # cui il ritmo misura l'upscale: in estrazione il «restano» e' il tempo
    # per finire di estrarre, e letto come tempo del file toglie ore.
    assert 'l.sorgente == catena_ora.get("file")' in app, (
        "la fascia prende il primo lavoro vivo che capita, non quello della "
        "catena")
    assert "l.fase in monitor.UNITA_UPSCALE" in app, (
        "la fascia userebbe il ritmo dell'estrazione come se fosse quello "
        "dell'upscale")
    # E finche' non si e' cronometrato un turno di codifica la misura non
    # copre i turni che restano: nel primo blocco la fascia prometterebbe
    # una ventina di minuti in meno del vero.
    assert "misurabile = (" in app and "turno_misurato(_stati" in app, (
        "la fascia sostituisce la stima anche quando la misura non conta "
        "ancora i turni di codifica")


@caso("la correzione si prende dai file che durano quanto questo")
def _correzione_per_taglia():
    """Il fattore di correzione veniva da TUTTE le pagelle, clip di prova
    comprese. Misurato il 12/08 su questa cartella: i sei episodi veri stanno
    fra 0,98 e 1,24 (mediana 1,066), le clip di prova da uno-cinque minuti a
    1,21, 1,32 e 1,39 — e tiravano la mediana di tutti a 1,133. Il costo
    fisso di un blocco pesa quanto pesa su un file di due minuti, e non ha
    niente da dire su un episodio di ventiquattro: ogni stima usciva gonfiata
    del 6%, e il TETTO veniva interamente da una clip di prova.

    Sui file veri di questa cartella lo scarto medio e' sceso dal 20,3% al
    8,9% (a parita' di modello, confrontando ogni stima col tempo vero)."""
    import json
    import tempfile
    from pathlib import Path
    from animeup import storico
    from animeup.paths import Paths

    radice = Path(tempfile.mkdtemp())
    (radice / "records").mkdir()
    (radice / "OUTPUT" / "JOBS").mkdir(parents=True)
    # sei episodi veri e tre clip di prova, con i rapporti misurati
    righe = ([{"secondi": 100.0 * r, "previsti": 100.0, "fotogrammi": f,
               "dedup": 0.3}
              for r, f in [(0.98, 19712), (1.07, 17122), (1.03, 19712),
                           (1.06, 18098), (1.24, 15657), (1.13, 34765)]]
             + [{"secondi": 100.0 * r, "previsti": 100.0, "fotogrammi": f,
                 "dedup": 0.2}
                for r, f in [(1.21, 5798), (1.39, 4856), (1.32, 1575)]])
    (radice / "records" / "history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in righe))
    p = Paths(radice)

    episodio = storico.correzione(p, simili_a=18000)
    assert episodio is not None and abs(episodio.attesa - 1.06) < 0.02, (
        f"un episodio non si corregge con le clip di prova: {episodio}")
    assert episodio.massimo < 1.3, (
        "il tetto di un episodio viene ancora da una clip di prova")

    clip = storico.correzione(p, simili_a=1800)
    assert clip is not None and clip.attesa > 1.2, (
        f"una clip corta deve correggersi con le clip corte: {clip}")

    tutto = storico.correzione(p)
    assert abs(tutto.attesa - 1.133) < 0.02, (
        "senza `simili_a` deve restare il comportamento di prima")

    # e il piano deve chiederla per taglia, altrimenti il filtro non serve
    fonte = (ROOT / "src" / "animeup" / "plan.py").read_text()
    assert "storico.correzione(p, simili_a=frames)" in fonte, (
        "il piano chiede ancora la correzione senza dire di che taglia e' "
        "il file")


@caso("a deduplica SPENTA i conti reggono e nessuna misura rientra")
def _senza_deduplica_regge():
    """Chiesto dall'utente il 12/08: spegnendo la deduplica dalla sidebar,
    tornano i conti o si rompe qualcosa?

    Tre cose devono valere insieme: si elaborano TUTTI i fotogrammi; la
    forchetta resta ordinata pur avendo pavimento e tetto sulla stessa base;
    e una mappa rimasta su disco da una lavorazione precedente NON deve
    rientrare dalla finestra."""
    from pathlib import Path as _P
    from animeup import library, plan as plan_mod

    campione = next(iter(sorted(CAMPIONI.glob("*.mkv"))), None)
    if campione is None:
        return
    rapporto = library.analyse(_P(campione))

    spenta = plan_mod.build_plan(rapporto, dedup=False)
    assert spenta.frames_to_upscale == spenta.frames, (
        "senza deduplica si devono elaborare tutti i fotogrammi")
    assert not spenta.dedup.misurata and spenta.dedup_storico is None
    assert (spenta.est_best_seconds <= spenta.est_attesa_seconds
            <= spenta.est_total_seconds), "forchetta fuori ordine"

    # una mappa presente non deve cambiare NIENTE a deduplica spenta
    con_mappa = plan_mod.build_plan(rapporto, dedup=False,
                                    dedup_nota=(0.41, rapporto.timing.packets))
    assert not con_mappa.dedup.misurata, (
        "una mappa rientra anche con la deduplica spenta")
    assert con_mappa.est_attesa_seconds == spenta.est_attesa_seconds, (
        "la mappa ha cambiato la stima pur essendo la deduplica spenta")

    # e il pipeline non deve nemmeno SCRIVERE una mappa quando e' spenta,
    # altrimenti la lavorazione successiva se la ritrova come se fosse sua
    fonte = (ROOT / "src" / "animeup" / "pipeline.py").read_text()
    assert "if not plan.dedup.enabled:" in fonte, (
        "la mappa di deduplica viene costruita anche a deduplica spenta")

    # Nel resoconto, uno ZERO misurato non deve sparire: sparendo diventa
    # indistinguibile da «deduplica spenta», che scrive `null`.
    app = (ROOT / "ui" / "app.py").read_text()
    assert 'lancio.get("dedup_medio") is not None' in app, (
        "una deduplica misurata allo zero sparisce dal resoconto e si "
        "confonde con la deduplica spenta")


@caso("la barra della riga non torna mai indietro")
def _barra_monotona():
    """In fase 3 i fotogrammi sono tutti fatti, quindi una barra guidata dal
    loro conteggio e' piena mentre il testo accanto dice «26%»: due misure
    diverse una sopra l'altra (segnalato dall'utente il 12/08).

    La cura non puo' pero' far CROLLARE la barra entrando in fase 3, che e'
    peggio del difetto: la prima versione di `_riempimento` la portava dal
    100% al 13%. Le prime due fasi si fermano al 90%, l'ultimo decimo e'
    della codifica finale e del montaggio."""
    app = (ROOT / "ui" / "app.py").read_text()
    assert "def _riempimento(" in app, (
        "sparita la funzione che decide il riempimento della barra")
    assert "_riempimento(lav) * 100" in app, (
        "la barra e' tornata a seguire i soli fotogrammi: in fase 3 sara' "
        "piena mentre il testo dice un quarto")

    # il conto, eseguito: deve crescere e non scendere mai
    class L:
        def __init__(s, fase, fr, cf, sp):
            s.fase, s.frazione, s.codifica_frazione, s.sottopasso = fase, fr, cf, sp

    def riemp(l):
        if l.fase != "codifica finale":
            return l.frazione * 0.9
        q = max(0.0, min(1.0, l.codifica_frazione))
        d = 0.5 + q / 2 if l.sottopasso == "montaggio" else q / 2
        return 0.9 + d * 0.1

    seq = [L("estrazione", 0.3, 0, ""), L("elaborazione", 0.5, 0, ""),
           L("elaborazione", 1.0, 0, ""), L("codifica finale", 1.0, 0.0, "codifica"),
           L("codifica finale", 1.0, 0.26, "codifica"),
           L("codifica finale", 1.0, 1.0, "codifica"),
           L("codifica finale", 1.0, 0.4, "montaggio"),
           L("codifica finale", 1.0, 1.0, "montaggio")]
    valori = [riemp(l) for l in seq]
    assert valori == sorted(valori), f"la barra torna indietro: {valori}"
    assert abs(valori[-1] - 1.0) < 1e-9, "a lavoro finito la barra non e' piena"
    assert valori[2] == 0.9, "l'upscale finito deve fermarsi al 90%"


@caso("a parita' di altezza si chiama supersampling, e il vecchio nome vale")
def _supersampling_nel_nome():
    """1080p -> modello x2 -> 2160p -> riduzione a 1080p NON e' un upscale:
    e' supersampling, e chiamarlo upscale nel nome del file e' falso (fatto
    notare dall'utente il 12/08).

    La parte delicata non e' la parola, e' la MIGRAZIONE: l'app riconosce
    «gia' fatto» dal nome del file, in quattro punti nella CLI e due
    nell'interfaccia. Cambiando etichetta senza compatibilita', un file
    prodotto ieri risulterebbe da rifare — e su questi tempi vuol dire dieci
    ore buttate per una parola."""
    from animeup.plan import output_name

    n = output_name("x", target_height=1080, scale=2, model_tag="cugan", crf=18)
    assert n.startswith("x [upscale 1080p"), n
    s = output_name("x", target_height=1080, scale=2, model_tag="cugan", crf=18,
                    etichetta="supersampling")
    assert s.startswith("x [supersampling 1080p"), s

    fonte = (ROOT / "src" / "animeup" / "plan.py").read_text()
    assert 'etichetta = "upscale" if target_h > disp_h else "supersampling"' in fonte, (
        "la scelta della parola non guarda piu' l'altezza del sorgente")
    assert "def uscite_note" in fonte and "def uscita_esiste" in fonte, (
        "sparita la compatibilita' col nome vecchio")

    # E nessuno deve piu' decidere «gia' fatto» dal solo nome nuovo. Si
    # guarda l'ALBERO SINTATTICO e non il testo: i commenti citano la forma
    # vecchia per spiegare perche' e' stata tolta, ed e' giusto che restino.
    # (La prima versione di questa asserzione falliva sui propri commenti,
    # per la seconda volta in una giornata.)
    import ast as _ast
    for relativo in ("src/animeup/cli.py", "ui/app.py"):
        albero = _ast.parse((ROOT / relativo).read_text())
        for n in _ast.walk(albero):
            if (isinstance(n, _ast.Call)
                    and isinstance(n.func, _ast.Attribute)
                    and n.func.attr == "exists"
                    and isinstance(n.func.value, _ast.Attribute)
                    and n.func.value.attr == "output"):
                raise AssertionError(
                    f"{relativo}:{n.lineno} decide «gia' fatto» dal solo "
                    f"nome nuovo: i file gia' prodotti risulterebbero da "
                    f"rifare")
    app = (ROOT / "ui" / "app.py").read_text()
    assert 'esito.get("output") in {u.name for u in piano.uscite_note}' in app, (
        "la pagella non si aggancia piu' a un'uscita col nome vecchio")


@caso("la deduplica attesa si misura sul file, non si indovina dai fratelli")
def _dedup_campione_governa_la_stima():
    """Voce 84. Il criterio vecchio accostava i file per numero di
    fotogrammi, e pescava il fratello sbagliato: per Monogatari S06E02
    (rilascio TV, deduplica vera 33,4%) sceglieva Tsukimonogatari 01 (BD,
    6,5%) perche' avevano 34.841 e 34.765 fotogrammi. Quasi quattro ore di
    errore su una stima di tredici.

    Provati e scartati sui dati, prima di arrivare qui: i bit per pixel (non
    separano — Koyomi TV sta a 0,0975 e un BD a 0,1016) e la sonda dei
    duplicati bit-esatti (mai compilata, e su encode a 10 bit il dithering
    la azzera per costruzione)."""
    from dataclasses import replace

    rep = probe_source(CAMPIONI / "TEST-CFR-23-976fps---2min.mkv",
                       with_fields=False)

    # 1. Col campione misurato, la stima usa QUEL numero e lo dice.
    con = build_plan(replace(rep, dedup_campione=0.41), target_height=1080)
    assert abs(con.dedup.expected_ratio - 0.41) < 1e-9, (
        f"la deduplica misurata sul file viene ignorata: "
        f"{con.dedup.expected_ratio}")
    assert "campione" in con.dedup.reason, (
        f"non si dice da dove viene il numero: «{con.dedup.reason}»")

    # 2. Un campione a ZERO non e' «non lo so»: e' una misura, e va usata.
    zero = build_plan(replace(rep, dedup_campione=0.0), target_height=1080)
    assert zero.dedup.expected_ratio == 0.0
    assert "campione" in zero.dedup.reason, (
        "uno zero misurato viene scambiato per assenza di misura")

    # 3. Senza campione si torna ai rami di prima, senza esplodere.
    senza = build_plan(replace(rep, dedup_campione=None), target_height=1080)
    assert senza.dedup.expected_ratio == 0.0
    assert "campione" not in senza.dedup.reason

    # 4. E la stima deve CAMBIARE: se i due piani danno lo stesso tempo, il
    #    numero misurato non sta arrivando dove serve.
    assert con.est_attesa_seconds < senza.est_attesa_seconds, (
        f"con il 41% di deduplica la stima non si accorcia: "
        f"{con.est_attesa_seconds:.0f}s contro {senza.est_attesa_seconds:.0f}s")


@caso("la pagella registra anche la stima detta AL LANCIO")
def _pagella_con_stima_di_partenza():
    """Voce 85. `previsti` e' un ricalcolo fatto DOPO, con la deduplica vera
    in mano: misura quanto sbaglia il modello quando gia' sa tutto (-3,5% su
    un file reale). Il TETTO di una previsione va invece allargato
    sull'errore della PREVISIONE — e senza registrarla, quell'errore non si
    puo' nemmeno calcolare. Tsukimonogatari 02 e' finito +5,8% oltre il
    massimo dichiarato proprio per questo."""
    import ast as _ast

    fonte = (ROOT / "src" / "animeup" / "cli.py").read_text()
    fn = next(n for n in _ast.parse(fonte).body
              if isinstance(n, _ast.FunctionDef) and n.name == "_scrivi_esito")
    scritto = _ast.unparse(fn)
    for chiave, perche in (
            ("est_attesa", "la previsione centrale detta al lancio"),
            ("est_best", "il minimo della forchetta dichiarata"),
            ("est_total", "il massimo, cioe' il tetto che si e' bucato"),
            ("dedup_prevista", "cosa sapeva la stima quando l'ha detta")):
        assert f"'{chiave}'" in scritto or f'"{chiave}"' in scritto, (
            f"la pagella non registra `{chiave}`: {perche}")
    # E devono venire dal PIANO, non dal risultato: il risultato sa gia'
    # tutto, e registrarlo qui rifarebbe il ricalcolo a posteriori con un
    # nome nuovo. Il controllo sta sull'ALBERO e non sul testo: `unparse`
    # rende l'intero dizionario su UNA riga, e un «contiene plan.» trovava
    # sempre qualcosa (sfuggito alla prima prova di mutazione).
    coppie = {}
    for nodo in _ast.walk(fn):
        if isinstance(nodo, _ast.Dict):
            for k, v in zip(nodo.keys, nodo.values):
                if isinstance(k, _ast.Constant):
                    coppie[k.value] = v
    for chiave in ("est_attesa", "est_best", "est_total"):
        valore = coppie.get(chiave)
        assert valore is not None, f"`{chiave}` non e' nella pagella"
        nomi = {n.id for n in _ast.walk(valore) if isinstance(n, _ast.Name)}
        assert "plan" in nomi, (
            f"`{chiave}` non viene dal piano di partenza ma da {sorted(nomi)}: "
            f"registrerebbe di nuovo il ricalcolo a posteriori")


@caso("ogni interruttore della sidebar viene ricordato fra un avvio e l'altro")
def _interruttori_ricordati():
    """Il difetto: l'elenco delle chiavi booleane da rileggere dal salvato
    era scritto A MANO — («dedup», «denoise», «forza») — e al primo
    interruttore aggiunto («Analisi approfondita») il valore salvato veniva
    scartato in silenzio. Nessun errore: sembrava solo che l'app non
    ricordasse. Verificato in pagina il 12/08: spento su disco, tornava
    acceso al riavvio.

    Ricavando le chiavi dai valori di fabbrica il difetto non puo' tornare
    per un interruttore futuro, che e' il punto."""
    import ast as _ast
    from unittest import mock
    from animeup import impostazioni

    # Le regole stanno nel motore (`animeup.impostazioni`), che le serve
    # all'interfaccia web e all'app nativa.
    fonte = (ROOT / "src" / "animeup" / "impostazioni.py").read_text()
    albero = _ast.parse(fonte)
    fn = next(n for n in albero.body
              if isinstance(n, _ast.FunctionDef) and n.name == "pulite")
    corpo = _ast.unparse(fn)

    # Nessun elenco di chiavi scritto a mano: si ciclano i valori di fabbrica.
    assert "PREDEFINITE.items()" in corpo, (
        "le chiavi booleane non si ricavano piu' dai valori di fabbrica: "
        "un interruttore aggiunto domani non verra' ricordato, e senza errori")

    # E ogni booleano dei valori di fabbrica deve sopravvivere al giro
    # completo salva -> rileggi, in ENTRAMBI i versi.
    fdef = next(n for n in albero.body
                if isinstance(n, _ast.Assign)
                and any(getattr(x, "id", "") == "PREDEFINITE" for x in n.targets))
    fabbrica = _ast.literal_eval(fdef.value)
    booleani = [k for k, v in fabbrica.items() if isinstance(v, bool)]
    assert booleani, "nessun interruttore fra i valori di fabbrica"

    with mock.patch.object(impostazioni, "tetto_spazio", lambda _c=None: (500, 600)):
        for chiave in booleani:
            for valore in (True, False):
                fuori = impostazioni.pulite({chiave: valore})
                assert fuori[chiave] is valore, (
                    f"l'interruttore «{chiave}» salvato a {valore} torna "
                    f"{fuori[chiave]}: l'app non ricorda quello che si e' scelto")

    # E l'interfaccia web non ne ha una copia sua: usa quelle del motore.
    app = (ROOT / "ui" / "app.py").read_text()
    assert "_IMPOSTAZIONI_DEFAULT = impostazioni.PREDEFINITE" in app
    assert "return impostazioni.pulite(dati, PATHS.output)" in app


@caso("la regola dello spazio si comporta bene su ogni disco")
def _regola_spazio_si_comporta():
    """Il test gemello controlla che il TESTO della regola non cambi; questo
    la esegue. Un `0.85` che diventasse `0.58`, o un `min` che diventasse
    `max`, passerebbero indisturbati da un controllo sulle stringhe — e il
    difetto si vedrebbe solo su un disco molto pieno o molto vuoto, cioe'
    non su quello di chi ha scritto il codice."""
    import ast as _ast
    import types as _types

    from unittest import mock
    from animeup import impostazioni

    def tetto(libero_gb):
        with mock.patch.object(impostazioni, "gb_liberi", lambda _p: libero_gb):
            return impostazioni.tetto_spazio(ROOT), impostazioni.MINIMO_SPAZIO_GB

    for libero in (10, 45, 60, 100, 300, 716, 2000):
        (t_gb, letto), minimo = tetto(libero)
        atteso = max(min(int(libero * 0.85), libero - 40), minimo + 1)
        assert t_gb == atteso, (
            f"con {libero} GB liberi il tetto e' {t_gb}, non {atteso}: la "
            f"regola «il piu' prudente fra l'85% e tutto-meno-40» non vale piu'")
        assert letto == libero, f"lo spazio libero letto e' {letto}, non {libero}"

    # I due regimi devono esserci ENTRAMBI, o il `min` non sta facendo nulla:
    # su un disco vuoto comanda la percentuale, su uno pieno il margine fisso.
    (vuoto, _), _ = tetto(2000)
    (pieno, _), _ = tetto(100)
    assert vuoto == int(2000 * 0.85), (
        "su un disco vuoto non comanda piu' la percentuale")
    assert pieno == 100 - 40, (
        "su un disco quasi pieno non comanda piu' il margine di 40 GB: "
        "l'85% lascerebbe al sistema molto meno del dovuto")


@caso("un pulsante dentro un fragment che scrive in sessione deve rilanciare")
def _pulsanti_nei_fragment_rilanciano():
    """La voce 83, e la regola che la generalizza.

    «Avvia la lavorazione» vive dentro `_fascia_viva`, che e' un fragment.
    Un click dentro un fragment riesegue SOLO il fragment: il rimedio in
    fondo al corpo (`pop("appena_avviata")` -> `st.rerun()`) non veniva
    raggiunto mai. Senza giro principale `armato` restava falso, il fragment
    rinasceva con `run_every=None`, e nessuno guardava piu' il disco: la
    pagina restava allo stato PRE-lancio per tutta la lavorazione, col
    riquadro verde ancora a schermo perche' nessun giro l'aveva cancellato.

    Riprodotto in banco di prova il 12/08 con un fragment finto: dopo il
    click il corpo principale non veniva eseguito nemmeno una volta.

    La regola: se un pulsante dentro un fragment scrive in sessione, quello
    che ha scritto serve a QUALCUNO FUORI — e fuori nessuno girera' se non
    lo si chiede esplicitamente."""
    import ast as _ast

    albero = _ast.parse((ROOT / "ui" / "app.py").read_text())
    frammenti = [n for n in _ast.walk(albero)
                 if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and any("fragment" in _ast.unparse(d) for d in n.decorator_list)]
    assert frammenti, ("nessun fragment in ui/app.py: o e' stato tolto, o "
                       "questo test non sta piu' guardando niente")

    colpevoli = []
    for f in frammenti:
        for nodo in _ast.walk(f):
            if not isinstance(nodo, _ast.If):
                continue
            if "st.button" not in _ast.unparse(nodo.test):
                continue
            corpo = "\n".join(_ast.unparse(s) for s in nodo.body)
            if "st.session_state[" in corpo and "st.rerun" not in corpo:
                colpevoli.append((nodo.lineno,
                                  _ast.unparse(nodo.test)[:60]))

    assert not colpevoli, (
        "dentro un fragment ci sono pulsanti che scrivono in sessione senza "
        "chiedere un giro completo: cio' che scrivono non lo leggera' nessuno "
        "e la pagina restera' ferma allo stato di prima (voce 83). "
        + "; ".join(f"riga {r}: {e}" for r, e in colpevoli))


@caso("la tabella degli indicatori regge anche le misure mancanti")
def _tabella_indicatori_disegna():
    """Il pezzo di pagina che disegna i numeri, eseguito davvero.

    Non e' teoria: una riga sbagliata qui ha gia' ucciso la pagina con un
    `NameError` a confronto finito. E ora un indicatore puo' valere `None`
    — «non misurato» — che moltiplicato per 100 fa esplodere tutto.

    `ui/app.py` non si puo' importare (eseguirebbe l'intera pagina), quindi
    si estrae dall'ALBERO la funzione e la si esegue con un `st` finto."""
    import ast as _ast

    sorgente = (ROOT / "ui" / "app.py").read_text()
    albero = _ast.parse(sorgente)
    voluti = ("_tabella_confronto", "_spiega_indicatori")
    pezzi = [n for n in albero.body
             if (isinstance(n, _ast.FunctionDef) and n.name in voluti)
             or (isinstance(n, _ast.Assign)
                 and any(getattr(b, "id", None) in voluti for b in n.targets))]
    assert len(pezzi) == 2, f"non trovo {voluti} in ui/app.py: {len(pezzi)}"

    uscita: list[str] = []

    class _St:
        @staticmethod
        def markdown(html, **_k):
            uscita.append(html)

    ambiente = {"st": _St, "esc": lambda s: str(s),
                "stima_hm": lambda s: f"{s:.0f}s", "t": i18n.t,
                "_icona_perche": lambda testo: f"<span title='{testo}'></span>"}
    exec(compile(_ast.Module(body=pezzi, type_ignores=[]), "app", "exec"),
         ambiente)
    tabella = ambiente["_tabella_confronto"]

    def _righe(*metriche):
        return [{"nome": f"m{i}", "secondi": 10.0 + i, "intero": 100.0,
                 "metriche": q} for i, q in enumerate(metriche)]

    # 1. Entrambi gli indicatori: due colonne e due spiegazioni.
    uscita.clear()
    tabella(_righe((1.0, 1.0), (2.5, 3.0)), (0.3, "misurata"))
    tutto = "".join(uscita)
    assert "dettaglio fine" in tutto.lower() and "rumore nelle aree piatte" in tutto.lower()
    assert "250%" in tutto and "300%" in tutto, (
        f"i rapporti non finiscono in tabella: {tutto[-400:]}")
    assert "Dettaglio fine</b>" in tutto and "Rumore nelle aree piatte</b>" in tutto

    # 2. Rumore non misurabile su NESSUNO: la colonna sparisce del tutto,
    #    e con lei la sua spiegazione — ma il dettaglio resta.
    uscita.clear()
    tabella(_righe((1.0, None), (2.5, None)), (0.0, "spenta"))
    tutto = "".join(uscita)
    assert "dettaglio fine" in tutto.lower(), (
        "sparito anche il dettaglio fine: era il difetto di partenza, un "
        "indicatore mancante che si portava via l'altro")
    assert "rumore nelle aree piatte" not in tutto.lower(), (
        "resta una colonna di trattini per una misura che non esiste")
    assert "Rumore nelle aree piatte</b>" not in tutto, (
        "si spiega come leggere una colonna che non viene mostrata")

    # 3. Nessuna delle due misure, per nessuno: degli indicatori non si
    #    disegna proprio niente. Non e' il caso 2: qui la tupla c'e' ed e'
    #    piena di `None`, quindi il controllo "ha metriche?" la fa passare.
    uscita.clear()
    tabella(_righe((None, None), (None, None)), None)
    tutto = "".join(uscita)
    assert "<th>dettaglio fine</th>" not in tutto.lower(), (
        "si disegna la tabella degli indicatori senza un solo numero "
        f"da mettere sotto: {tutto[-300:]}")
    assert "non disponibili" in tutto, (
        "gli indicatori spariscono senza dire perche': chi guarda va a "
        "cercare un difetto dove non c'e'")
    assert "aree abbastanza uniformi" in tutto, (
        "col riferimento presente la causa e' il fotogramma, e va detta")

    # 3-bis. Stesso vuoto, ma perche' manca il riferimento: causa diversa,
    #        spiegazione diversa.
    uscita.clear()
    tabella(_righe(None, None), None, riferimento=False)
    tutto = "".join(uscita)
    assert "originale ingrandito" in tutto, (
        "senza il riferimento non si spiega che e' quello a mancare")

    # 3-ter. Un modello misurato e uno no: chi manca resta in tabella con un
    #        trattino, non sparisce lasciando due tabelle di lunghezza diversa.
    uscita.clear()
    tabella([{"nome": "primo", "secondi": 10.0, "intero": 100.0,
              "metriche": (1.8, 2.6)},
             {"nome": "secondo", "secondi": 14.0, "intero": 140.0,
              "metriche": None}], None)
    # Gli indicatori vengono dopo la tabella dei tempi, come barre.
    corpo = "".join(uscita).split("</table>")[-1]
    assert "secondo" in corpo, (
        "il modello senza misure sparisce dagli indicatori: la tabella esce "
        "piu' corta di quella dei tempi e nessuno dice perche'")
    assert "—" in corpo, "manca il trattino di «non misurato»"

    # 3-quater. E al punto di CHIAMATA il flag deve venire dai dati: una
    #           costante li' dentro renderebbe la spiegazione sempre sbagliata
    #           in uno dei due casi, senza che nessun test se ne accorga
    #           (sfuggita alla prima prova di mutazione).
    chiamate = [n for n in _ast.walk(albero)
                if isinstance(n, _ast.Call)
                and getattr(n.func, "id", None) == "_tabella_confronto"]
    assert chiamate, "non trovo la chiamata a _tabella_confronto"
    for c in chiamate:
        arg = next((k.value for k in c.keywords if k.arg == "riferimento"), None)
        assert arg is not None, (
            "la tabella viene chiamata senza dire se il riferimento c'e': "
            "si affida al valore di comodo della firma")
        assert not isinstance(arg, _ast.Constant), (
            "il flag del riferimento e' una costante al punto di chiamata: "
            "la spiegazione del perche' mancano gli indicatori sarebbe "
            "sempre sbagliata in uno dei due casi")

    # 3-quinquies. Tupla piu' corta del numero di indicatori: capita se un
    #              giorno se ne aggiunge uno e in sessione restano misure
    #              vecchie. Deve uscire un trattino, non un IndexError che
    #              porta giu' la pagina.
    uscita.clear()
    tabella([{"nome": "corto", "secondi": 10.0, "intero": 100.0,
              "metriche": (1.5,)}], None)
    tutto = "".join(uscita)
    assert "150%" in tutto, "il valore presente nella tupla corta non compare"

    # 4. Misto: chi ce l'ha mostra il numero, chi no un trattino.
    uscita.clear()
    tabella(_righe((1.0, 1.0), (2.5, None)), None)
    tutto = "".join(uscita)
    assert "—" in tutto, "la misura mancante non e' segnalata"
    assert "100%" in tutto, "sparito il numero di chi la misura ce l'ha"


@caso("il rumore nelle aree piatte si misura anche sull'anime")
def _indicatore_aree_piatte():
    """Il difetto: nell'anime le aree piatte sono piatte DAVVERO — campiture
    a tinta unita e gradienti lentissimi — e l'ottavo piu' uniforme del
    fotogramma ha residuo zero, perche' la differenza con la sfocatura sta
    sotto il livello e si tronca a 0. Ogni modello dava zero, il rapporto
    non si poteva calcolare, e la tabella spariva: misurata su 3 dei 7
    confronti in archivio, e nel Confronto vero fatto oggi `metriche`
    usciva VUOTO. Spariva anche il dettaglio fine, che invece funzionava.

    E le zone vanno scelte una volta sola sul riferimento: prendendo «le
    piu' piatte di ciascuno» si confrontano numeri presi su pezzi diversi
    dell'immagine, cioe' non si confronta niente."""
    from animeup import preview
    from PIL import Image

    lato = preview.LATO_TESSERA

    def _tela(rumore: int, colonne: int = 12, righe: int = 6) -> Image.Image:
        """Un fotogramma fatto come un fotogramma d'anime vero: un quarto a
        tinta unita, un quarto di GRADIENTE (piatto ma non costante, e con
        varianza tutt'altro che nulla: e' questo che mandava a zero la
        misura, e che un filtro sulla sola varianza non fermava), meta' con
        micro-struttura. Piu' `rumore` sovrapposto, per la variante
        "sporca"."""
        im = Image.new("L", (lato * colonne, lato * righe), 128)
        px = im.load()
        q = lato * 2          # ogni banda larga due tessere
        for y in range(im.height):
            for x in range(im.width):
                if x < q:
                    v = 128                       # campitura a tinta unita
                elif x < 2 * q:
                    # Gradiente ripido: varianza ~12, residuo 0.000. Un
                    # filtro sulla sola varianza lo lascerebbe passare, ed
                    # e' il motivo per cui non si filtra sulla varianza.
                    v = 122 + (x - q) * 24 // q
                elif x < 3 * q:
                    v = 12 + (10 if (y // 2) % 2 else 0)    # texture nel nero
                elif x < 4 * q:
                    v = 245 + (10 if (y // 2) % 2 else 0)   # texture bruciata
                elif x < 5 * q:
                    v = 128 + (10 if (y // 2) % 2 else 0)   # texture LIEVE
                else:
                    # Texture FORTE: misurabile quanto la lieve, ma tutt'altro
                    # che un'area piatta. Se le zone finiscono qui, non si sta
                    # piu' misurando il rumore nelle aree piatte.
                    v = 128 + (40 if (y // 2) % 2 else 0)
                if rumore:
                    v += (x * 7 + y * 13) % rumore
                px[x, y] = max(0, min(255, v))
        return im.convert("RGB")

    piatta, sporca = _tela(0), _tela(9)
    q = lato * 2

    # Le PREMESSE del test, dichiarate invece che sperate: la banda del
    # gradiente deve avere varianza alta e residuo nullo, altrimenti questo
    # test non sta piu' provando cio' che dice di provare.
    import statistics as _st
    _g = piatta.convert("L")
    _dati = list(_g.crop((q, 0, q + lato, lato)).getdata())
    assert _st.pvariance(_dati) > 8, (
        f"la banda del gradiente ha varianza {_st.pvariance(_dati):.1f}: "
        f"troppo bassa perche' il test dimostri che la varianza non basta")
    assert preview._residuo(_g, q, 0) == 0.0, (
        "la banda del gradiente ha residuo non nullo: non riproduce piu' il "
        "caso che svuotava la tabella")

    zone = preview._zone_piatte(piatta)
    assert zone, ("nessuna zona misurabile su un fotogramma che ha meta' "
                  "campitura e meta' texture: l'indicatore sparisce")
    assert len(zone) >= preview.ZONE_MINIME, (
        f"solo {len(zone)} zone: una mediana su cosi' poche non e' una misura")
    # Nessuna zona sulla campitura ne' sul gradiente: li' ogni modello da'
    # zero, ed e' esattamente il caso che svuotava la tabella.
    # L'unica banda legittima e' l'ultima: campitura e gradiente non hanno
    # niente da misurare, nero e bruciato non hanno segnale per nessuno.
    assert all(4 * q <= x < 5 * q for x, _y in zone), (
        f"zone fuori dalla banda a texture lieve [{4 * q}, {5 * q}): sotto "
        f"ci sono campitura, gradiente, nero e bruciato — dove ogni modello "
        f"risulta identico — e sopra la texture forte, che area piatta non "
        f"e' affatto: {zone}")

    # Le STESSE zone su due varianti: la sporca deve risultare piu' rumorosa,
    # ed entrambe devono dare un numero vero (non `None`, non 0).
    _, base = preview._indicatori(piatta, zone)
    _, alto = preview._indicatori(sporca, zone)
    assert base is not None and base > 0, (
        f"il riferimento misura {base}: il rapporto non si puo' calcolare e "
        f"la tabella degli indicatori sparisce dalla pagina")
    assert alto > base, (
        f"un fotogramma piu' sporco ({alto:.4f}) non risulta piu' rumoroso "
        f"del pulito ({base:.4f})")

    # Senza zone utilizzabili si dice «non misurato», non «zero».
    _, niente = preview._indicatori(piatta, [])
    assert niente is None, (
        "senza zone l'indicatore torna un numero invece di dichiararsi non "
        "misurato: 0 e «non lo so» finirebbero indistinguibili in tabella")

    # E se le zone buone sono quattro gatti, meglio nessun numero che una
    # mediana su due tessere — che in un caso reale usciva 12x.
    minuscola = _tela(0, colonne=14, righe=1)
    assert preview._zone_piatte(minuscola) == [], (
        "con pochissime zone valide l'indicatore produce lo stesso un "
        "numero, costruito su una manciata di tessere")


@caso("gli spezzoni del secondo lotto sopravvivono a un ricaricamento")
def _deposito_tutti_i_lotti():
    """Il difetto: la pagina rileggeva un solo schedario, quello del PRIMO
    lotto. Chi premeva «trova altri 8» e poi ricaricava perdeva il secondo
    lotto dalla pagina — con le sue clip gia' estratte, ancora su disco e
    orfane (verificato sul 360p, 12/08). E siccome nemmeno la memoria dei
    gia' visti si recuperava, ripremere il pulsante ripescava dalla cassa
    gli stessi otto e li AGGIUNGEVA: otto card doppie."""
    from animeup import preview

    class _P:
        fps = 24.0
        class source:
            path = ROOT / "tests" / "run.py"     # basta un file che esista

    def _c(f):
        return preview.Candidate(kind=preview.Kind.STATIC, start_frame=f,
                                 frames=240, fps=24.0, motion=1.0,
                                 brightness=1.0, reason="")

    with tempfile.TemporaryDirectory() as tmp:
        paths = PATHS.__class__(root=Path(tmp))
        primo = [_c(1000), _c(2000)]
        secondo = [_c(9000), _c(9500)]

        # Il deposito NON deve coincidere con nessuno schedario di lotto,
        # altrimenti l'elenco completo sovrascrive una cassa di scansione.
        dep = preview.deposito(_P, 2, preview.DEFAULT_SECONDS, paths)
        per_lotto = {preview._schedario(_P, 2, preview.DEFAULT_SECONDS, paths, n)
                     for n in (0, 2, 4, 8)}
        assert dep not in per_lotto, "il deposito calpesta la cassa di un lotto"

        preview.scrivi_deposito(_P, primo + secondo, 2,
                                preview.DEFAULT_SECONDS, paths)
        riletti = preview.leggi_deposito(_P, 2, preview.DEFAULT_SECONDS, paths)
        assert [c.start_frame for c in riletti] == [1000, 2000, 9000, 9500], (
            f"il deposito non restituisce tutti i lotti: "
            f"{[c.start_frame for c in riletti]}")

    # E l'aggiunta non deve mai duplicare: ripescare il primo lotto e
    # riaggiungerlo era esattamente il caso visto in pagina.
    assert preview.solo_nuovi(primo, primo) == [], (
        "gli stessi spezzoni vengono aggiunti una seconda volta")
    assert [c.start_frame for c in preview.solo_nuovi(primo, secondo)] == [
        9000, 9500], "gli spezzoni davvero nuovi vengono scartati"
    misto = preview.solo_nuovi(primo, [primo[0], secondo[0]])
    assert [c.start_frame for c in misto] == [9000], (
        "il filtro non distingue i nuovi dai gia' visti dentro lo stesso lotto")


@caso("la testata resta appiccicata in cima, e la linea arriva ai bordi")
def _testata_sticky_e_linea_intera():
    """Due cose che devono valere INSIEME, e la seconda ha rotto la prima.

    La linea sotto le schede non arrivava ai bordi su una finestra larga
    (misurato: 105 px scoperti a sinistra, 115 a destra a 1920). Per
    ancorare l'elemento che la disegna avevo aggiunto `position: relative`
    al contenitore — che pero' sovrascrive il `position: sticky` dichiarato
    poche righe sopra, e la testata ha smesso di restare in cima. Notato
    dall'utente in dieci secondi.

    `sticky` e' gia' una posizione e fa da contenitore a un figlio assoluto:
    quel `relative` non serviva proprio."""
    app = (ROOT / "ui" / "app.py").read_text()
    # Si parte dal `top:` delle schede, non dal selettore: quel selettore
    # compare DUE volte (una in una lista con la fascia del marchio) e
    # partendo da li' si finisce nella regola sbagliata, senza lo sticky.
    # (45px da quando il marchio sopra le schede non c'e' piu'.)
    blocco = app[app.index("position: sticky; top: 45px; z-index: 25"):]
    blocco = blocco[:blocco.index("}}") + 2]
    # Via i commenti PRIMA di cercare: dentro c'e' scritto perche' certe
    # dichiarazioni non vanno messe, e cercandole nel testo grezzo si
    # trovano le spiegazioni invece del codice. E' il terzo test in una
    # giornata che inciampa nei propri commenti: qui si toglie e basta.
    import re as _re
    blocco = _re.sub(r"/\*.*?\*/", "", blocco, flags=_re.S)

    assert "position: sticky" in blocco, "la fascia delle schede non e' piu' sticky"
    assert "position: relative" not in blocco, (
        "e' tornato un `position: relative` dopo lo `sticky`: lo sovrascrive "
        "e la testata smette di restare in cima")
    assert "box-shadow: -400px" in blocco, (
        "sparite le ombre laterali: la linea torna larga quanto il contenuto")
    assert "border-bottom" not in blocco, (
        "e' tornato il bordo, che si ferma al box e non puo' arrivare ai bordi")


@caso("nessun nome non definito nell'interfaccia e nei moduli")
def _niente_nomi_fantasma():
    """Un `NameError` in un ramo che gira solo dentro il browser.

    Successo il 12/08: cambiando un ciclo da `for k, sec in ...` a
    `for k in ...` e' rimasto un `sec` dentro la comprehension. La pagina
    e' morta a fine confronto, e nessuno dei 126 test se n'e' accorto —
    guardano il TESTO del sorgente, e quel codice si esegue solo dopo aver
    generato uno spezzone.

    Qui si compila il modulo (senza eseguirlo: importarlo farebbe partire
    Streamlit) e si cercano i nomi che il compilatore risolve come GLOBALI
    ma che nel modulo non esistono. E' esattamente la forma che prende una
    variabile rimasta orfana dopo una modifica.
    """
    import ast
    import builtins
    import dis

    for relativo in ("ui/app.py", "src/animeup/plan.py",
                     "src/animeup/monitor.py", "src/animeup/preview.py",
                     "src/animeup/storico.py", "src/animeup/cli.py",
                     "src/animeup/pipeline.py"):
        percorso = ROOT / relativo
        sorgente = percorso.read_text()
        albero = ast.parse(sorgente)

        # I dunder di modulo esistono a tempo di esecuzione ma non compaiono
        # nell'albero sintattico: non sono nomi orfani.
        definiti = set(dir(builtins)) | {
            "__file__", "__name__", "__doc__", "__package__", "__spec__",
            "__loader__", "__builtins__", "__debug__", "__annotations__",
            "__dict__", "__class__", "__qualname__", "__module__"}
        for n in ast.walk(albero):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definiti.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                definiti.add(n.id)
            elif isinstance(n, ast.alias):
                definiti.add((n.asname or n.name).split(".")[0])
            elif isinstance(n, ast.arg):
                definiti.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                definiti.add(n.name)
            elif isinstance(n, ast.Global):
                definiti.update(n.names)

        def codici(c):
            yield c
            for k in c.co_consts:
                if hasattr(k, "co_code"):
                    yield from codici(k)

        fantasmi = set()
        for c in codici(compile(sorgente, str(percorso), "exec")):
            for istr in dis.get_instructions(c):
                if istr.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                    nome = istr.argval
                    if isinstance(nome, str) and nome not in definiti:
                        fantasmi.add(nome)
        assert not fantasmi, (
            f"{relativo}: nomi usati ma mai definiti — {sorted(fantasmi)}. "
            f"E' la forma di una variabile rimasta orfana dopo una modifica, "
            f"e in un ramo raro diventa una pagina rossa")


@caso("gli spezzoni si spargono sul file, e «altri 8» ne trova di diversi")
def _spezzoni_sparsi():
    """Due spezzoni dello STESSO tipo non devono raccontare la stessa scena.

    Il difetto, visto dall'utente il 12/08: due «statico» a 23:56 e 24:09 —
    tredici secondi, la stessa scena, due prove per il prezzo di una. La
    causa era che l'unico vincolo fra candidati era la non sovrapposizione.

    E la distanza si RAPPORTA a quanti spezzoni esisteranno in tutto: con un
    valore fisso, dopo il primo lotto un episodio da 25 minuti risultava
    saturo e «trova altri 8» ne restituiva quattro, tutti nello stesso
    minuto (provato prima di correggere)."""
    fonte = (ROOT / "src" / "animeup" / "preview.py").read_text()

    assert "quanti = per_kind * len(rules) + len(escludi)" in fonte, (
        "la distanza minima non si rapporta piu' al numero di spezzoni: con "
        "un valore fisso il secondo lotto non ha piu' spazio")
    assert "distinti = max(window, count // max(1, quanti))" in fonte
    for controllo in ("for t in stesso_tipo", "for t in escludi"):
        assert f"if any(abs(i - t) < distinti {controllo}):" in fonte, (
            f"sparito il controllo di distanza «{controllo}»: gli spezzoni "
            f"tornano a raccontare la stessa scena")

    # La regola ha una VERSIONE, e finisce nella firma della cassa: senza,
    # i file gia' scansionati continuerebbero a servire le scelte vecchie —
    # cioe' proprio quelli su cui il difetto era stato notato.
    assert "REGOLA_SCELTA" in fonte
    assert "|r{REGOLA_SCELTA}" in fonte, (
        "la versione della regola non entra nella firma della cassa")

    # e l'interfaccia deve passare le posizioni gia' viste
    app = (ROOT / "ui" / "app.py").read_text()
    assert "escludi=gia_visti" in app, (
        "il secondo lotto non esclude le posizioni gia' mostrate")
    assert 't("conf.trova_altri"), key="trovaAltri"' in app, (
        "il pulsante non dice piu' che cerchera' spezzoni DIVERSI")
    assert i18n.catalogo("it")["conf.trova_altri"] == "Trova altri 8 spezzoni", (
        "il pulsante non dice piu' che cerchera' spezzoni DIVERSI")


@caso("il confronto ha un ordine solo, e gli indicatori si sanno leggere")
def _confronto_ordine_e_indicatori():
    """Chiesto dall'utente il 12/08: animevideov3 prima di CUGAN ovunque, e
    due righe che spiegano come si leggono i due indicatori — «altrimenti e'
    inutile». Un ordine deciso in un posto solo, o le tre viste (foglio 1:1,
    tabella dei tempi, indicatori) si contraddicono."""
    from animeup import preview

    assert preview.ORDINE[:3] == ("original", "animevideov3", "cugan"), (
        "l'ordine di lettura del confronto e' cambiato")
    assert preview.ordine_lettura({"cugan": 1, "animevideov3": 1}) == [
        "animevideov3", "cugan"], "animevideov3 non viene piu' per primo"
    # una chiave sconosciuta non deve sparire dal confronto
    assert preview.ordine_lettura({"pippo": 1, "cugan": 1}) == ["cugan", "pippo"]

    app = (ROOT / "ui" / "app.py").read_text()
    # Le frasi stanno nel catalogo italiano, non piu' nel codice.
    testi = "\n".join(i18n.catalogo("it").values())
    for pezzo in ("Dettaglio fine", "Rumore nelle aree piatte",
                  "effetto plastica", "più dettaglio non significa più fedele"):
        assert pezzo in testi, (
            f"sparita la spiegazione degli indicatori: «{pezzo}». Due "
            f"percentuali senza istruzioni non dicono niente a nessuno")
    assert "Il giudice resta" in testi, (
        "sparita l'avvertenza che l'occhio decide e i numeri no")

    # la proiezione deve tenere conto della deduplica, non ignorarla.
    # Controllo sul TESTO: la proiezione si calcola nel processo del
    # confronto (`confronto._riassunto`). Verifica che il fattore sia
    # applicato dove va applicato — la prova di mutazione ha mostrato che
    # senza questa riga togliere il fattore passava inosservato.
    motore = (ROOT / "src" / "animeup" / "confronto.py").read_text()
    assert "def quota_dedup(" in (ROOT / "src" / "animeup" / "preview.py").read_text()
    assert "* (1 - quota[0])" in motore, (
        "la proiezione sull'episodio intero non moltiplica piu' per la "
        "quota di deduplica: torna a promettere ore che non servono")
    # Si cerca il TESTO RESO, non la frase in generale: il commento del
    # codice cita quello vecchio per spiegare perche' e' stato tolto, ed e'
    # giusto che resti. (Colto dalla prova di mutazione: la prima versione
    # di questa asserzione falliva sul proprio commento.)
    assert "a questo ritmo (stima senza" not in app, (
        "e' tornata la proiezione che ignora la deduplica: su un file al "
        "33% sbagliava di quattro ore e mezza")

    # E gli indicatori vanno calcolati DOVE i fotogrammi ci sono gia'.
    # Sull'ALBERO e non sul testo: la prima versione confrontava la riga
    # parola per parola e si e' rotta al primo ritocco alla riga stessa,
    # che non c'entrava niente con la cosa da difendere.
    import ast as _ast

    fonte = (ROOT / "src" / "animeup" / "preview.py").read_text()
    corpo = next(f for f in _ast.parse(fonte).body
                 if isinstance(f, _ast.FunctionDef) and f.name == "crop_sheet")
    chiamate = [n.func.id for n in _ast.walk(corpo)
                if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)]
    assert "_indicatori" in chiamate, (
        "`crop_sheet` non calcola piu' gli indicatori: verrebbero da una "
        "seconda estrazione degli stessi pixel")
    assert chiamate.count("run_stderr") == 1, (
        f"`crop_sheet` estrae fotogrammi {chiamate.count('run_stderr')} "
        f"volte: gli indicatori devono riusare quelli gia' presi per il "
        f"foglio, non chiederne altri")


@caso("uno stesso file non conta due volte nello storico")
def _niente_doppioni_nello_storico():
    """Una lavorazione conclusa CON AVVISI conserva la cartella di lavoro
    (per il controllo) e ha gia' lasciato la sua pagella: la stessa misura
    entra due volte e pesa il doppio delle altre.

    Misurato in audit il 12/08 su quattro episodi al 26/32/36/41%: con la
    cartella del primo rimasta sul disco la mediana passava da 0,340 a
    0,320, cioe' un 3% sul tempo, per un file solo."""
    import json
    import tempfile
    from pathlib import Path
    from animeup import storico
    from animeup.paths import Paths

    radice = Path(tempfile.mkdtemp())
    (radice / "records").mkdir()
    (radice / "OUTPUT" / "JOBS").mkdir(parents=True)
    righe = [{"secondi": 100.0, "previsti": 100.0, "fotogrammi": n, "dedup": q}
             for q, n in [(0.26, 17000), (0.32, 17500),
                          (0.36, 18000), (0.41, 18500)]]
    (radice / "records" / "history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in righe))
    p = Paths(radice)

    c = radice / "OUTPUT" / "JOBS" / "con-avvisi"
    c.mkdir()
    (c / "dedup.json").write_text(json.dumps(
        {"total": 17000, "keep": list(range(round(17000 * 0.74)))}))
    d = storico.deduplica(p, simili_a=17500)
    assert d is not None and d.campioni == 4 and abs(d.attesa - 0.34) < 1e-9, (
        f"la cartella superstite ha fatto contare due volte lo stesso file: {d}")

    # ...ma una lavorazione NUOVA, che una pagella non ce l'ha ancora, deve
    # entrare eccome: e' tutto il senso di guardare le mappe vive.
    c2 = radice / "OUTPUT" / "JOBS" / "in-corso"
    c2.mkdir()
    (c2 / "dedup.json").write_text(json.dumps(
        {"total": 17600, "keep": list(range(round(17600 * 0.95)))}))
    d2 = storico.deduplica(p, simili_a=17500)
    assert d2 is not None and d2.campioni == 5 and d2.minimo < 0.06, (
        f"la misura di una lavorazione nuova non e' entrata: {d2}")

    # Il riconoscimento non puo' essere il solo conteggio dei fotogrammi:
    # due puntate della stessa serie possono averlo identico (Koyomi 01 e 02
    # hanno entrambe 19.712 fotogrammi, con deduplica 41,0% e 35,9%).
    c3 = radice / "OUTPUT" / "JOBS" / "stessa-taglia-altra-dedup"
    c3.mkdir()
    (c3 / "dedup.json").write_text(json.dumps(
        {"total": 17000, "keep": list(range(round(17000 * 0.59)))}))
    d3 = storico.deduplica(p, simili_a=17500)
    assert d3 is not None and d3.campioni == 6, (
        f"un file di pari lunghezza ma altra deduplica e' stato scartato "
        f"come doppione: {d3}")


@caso("la finestra si stringe sui SIMILI, non sulle ultime pagelle qualunque")
def _finestra_dopo_il_filtro():
    """Il filtro di taglia non serve a niente se la finestra si applica
    prima: dieci prove corte di fila spingono fuori tutti gli episodi veri, e
    l'episodio successivo viene stimato sulle prove.

    Misurato in audit il 12/08 con due episodi al 35% dietro dieci clip al
    5%: l'episodio riceveva 5% di deduplica e 1,30 di correzione invece di
    35% e 1,00. Sul Mac mini mancava poco — dieci pagelle in tutto, di cui
    quattro di prova, con una finestra da dieci."""
    import json
    import tempfile
    from pathlib import Path
    from animeup import storico
    from animeup.paths import Paths

    assert storico.FINESTRA_LETTURA > storico.FINESTRA, (
        "si leggono tante pagelle quante ne contano: il filtro di taglia "
        "non ha piu' nulla da cui pescare")

    radice = Path(tempfile.mkdtemp())
    (radice / "records").mkdir()
    (radice / "OUTPUT" / "JOBS").mkdir(parents=True)
    # Le clip devono essere PIU' della finestra, o il taglio non si vede:
    # con esattamente dieci, togliere il `[:FINESTRA]` non cambia niente e
    # la mutazione passa inosservata (provato in audit).
    quante_clip = storico.FINESTRA + 4
    righe = ([{"secondi": 100.0, "previsti": 100.0,
               "fotogrammi": 18000, "dedup": 0.35}] * 2
             + [{"secondi": 130.0, "previsti": 100.0,
                 "fotogrammi": 1800, "dedup": 0.05}] * quante_clip)
    (radice / "records" / "history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in righe))
    p = Paths(radice)

    d = storico.deduplica(p, simili_a=18000)
    assert d is not None and abs(d.attesa - 0.35) < 1e-9, (
        f"l'episodio e' stato stimato sulle clip: {d}")
    c = storico.correzione(p, simili_a=18000)
    assert c is not None and abs(c.attesa - 1.0) < 1e-9, (
        f"la correzione dell'episodio viene dalle clip: {c}")

    # e una clip deve continuare a stimarsi sulle clip, non sugli episodi
    dc = storico.deduplica(p, simili_a=1800)
    assert dc is not None and abs(dc.attesa - 0.05) < 1e-9

    # Una riga che e' JSON VALIDO ma non un oggetto — `12345`, `null`, `[]` —
    # faceva alzare AttributeError sulla `.get()`, cioe' la pagina cadeva
    # per una riga storta in un registro (trovato in audit il 12/08).
    sporco = Path(tempfile.mkdtemp())
    (sporco / "registri").mkdir()
    (sporco / "OUTPUT" / "JOBS").mkdir(parents=True)
    (sporco / "records").mkdir()
    (sporco / "records" / "history.jsonl").write_text("\n".join(
        ["{rotta", "", "null", "12345", "[]", '"testo"']
        + [json.dumps(r) for r in righe[:3]]))
    sp = Paths(sporco)
    assert storico.deduplica(sp, simili_a=18000) is not None
    assert storico.correzione(sp, simili_a=18000) is not None

    # la finestra deve comunque STRINGERE: non piu' di FINESTRA campioni
    assert dc.campioni == storico.FINESTRA, (
        "la finestra non stringe piu' niente: tutta la storia entra nella "
        "stima, materiale di due anni fa compreso")


@caso("lo spazio predefinito e' la regola, non il minimo del cursore")
def _spazio_predefinito_e_una_regola():
    """Il predefinito di `disco` e' «il piu' prudente fra l'85% del libero e
    tutto meno 40 GB», concordato con l'utente l'11/08. Scritto come costante
    valeva `MINIMO_SPAZIO_GB`, e su un disco con 606 GB liberi
    l'impostazione si e' ritrovata a 50 GB senza che nessuno l'avesse scelta
    — mentre il fumetto ne annunciava 40, che non era il predefinito di
    nessun ramo del codice (segnalato dall'utente il 12/08)."""
    app = (ROOT / "src" / "animeup" / "impostazioni.py").read_text()

    assert '"disco": None' in app, (
        "il predefinito di `disco` e' tornato un numero fisso: su un disco "
        "diverso da quello di chi l'ha scritto sara' sbagliato")
    assert "puliti = predefinite(cartella)" in app, (
        "la sanificazione riparte dai valori di fabbrica grezzi, dove "
        "`disco` non ha ancora un numero")

    # Nessun 40 residuo dove si parla di spazio nella pagina: era la stringa
    # mostrata a schermo come predefinito, e il ripiego della sessione non
    # seminata.
    pagina = (ROOT / "ui" / "app.py").read_text()
    assert 'predefinito=f"40 GB' not in pagina, (
        "il fumetto annuncia ancora 40 GB come predefinito")
    assert 'st.session_state.get("w_disco", 40)' not in pagina, (
        "il ripiego del cursore e' ancora 40")

    # E la regola dev'essere quella: piu' prudente fra 85% e libero-40.
    fonte = app[app.index("def tetto_spazio"):]
    fonte = fonte[:fonte.index("\n\n\n")]
    assert "0.85" in fonte and "libero - 40" in fonte, (
        "la regola dello spazio predefinito e' cambiata senza dirlo")

    # E si RICALCOLA a ogni avvio, ignorando il salvato: e' la cura del
    # difetto tornato due volte il 12/08 (`disco` al minimo del cursore su un
    # disco quasi vuoto, scritto da una sessione con la chiave non seminata).
    # Senza questa riga il valore sbagliato sopravvive a ogni ricaricamento.
    carica = app[app.index("def carica("):]
    carica = carica[:carica.index("\ndef ", 1)]
    assert 'puliti["disco"] = tetto_spazio(cartella)[0]' in carica, (
        "lo spazio per file non si ricalcola piu' a ogni avvio")
    assert "if not valido" not in carica, (
        "e' tornato il ramo che rispetta il valore salvato: un minimo finito "
        "su disco tornerebbe a sopravvivere ai ricaricamenti")


# ===========================================================================
#  Lingue
# ===========================================================================

def _chiavi_usate() -> set[str]:
    """Le chiavi passate a `t`/`tn` come letterali, in tutto il codice."""
    import ast
    usate: set[str] = set()
    for f in [ROOT / "ui" / "app.py", *(ROOT / "src" / "animeup").glob("*.py")]:
        for nodo in ast.walk(ast.parse(f.read_text())):
            if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id in ("t", "tn") and nodo.args
                    and isinstance(nodo.args[0], ast.Constant)
                    and isinstance(nodo.args[0].value, str)):
                continue
            chiave = nodo.args[0].value
            if nodo.func.id == "tn":
                usate |= {f"{chiave}.uno", f"{chiave}.altri"}
            else:
                usate.add(chiave)
    return usate


@caso("le lingue hanno le stesse voci, con gli stessi segnaposto")
def _() -> None:
    """Una voce che manca in una lingua ripiega sull'inglese in silenzio: a
    schermo si vedrebbe una frase sola nell'altra lingua, in mezzo al resto."""
    import string
    cataloghi = {lingua: i18n.catalogo(lingua) for lingua in i18n.LINGUE}
    riferimento = cataloghi[i18n.PREDEFINITA]
    for lingua, cat in cataloghi.items():
        assert cat.keys() == riferimento.keys(), (
            lingua, sorted(cat.keys() ^ riferimento.keys()))

    def segnaposto(testo: str) -> set[str]:
        return {campo for _, campo, _, _ in string.Formatter().parse(testo) if campo}

    for chiave, testo in riferimento.items():
        for lingua, cat in cataloghi.items():
            assert segnaposto(cat[chiave]) == segnaposto(testo), (lingua, chiave)


@caso("ogni testo chiesto dal codice esiste nei cataloghi")
def _() -> None:
    """Una chiave assente non rompe la pagina: mostra la chiave stessa. Che
    e' peggio, perche' nessuno se ne accorge prima di averla vista."""
    from animeup.probe import FieldMode
    from animeup.preview import Kind
    import ast
    sezioni = ast.literal_eval(next(
        r.split("=", 1)[1] for r in (ROOT / "ui" / "app.py").read_text().splitlines()
        if r.startswith("SEZIONI = ")))
    # Le chiavi composte a runtime: le schede e i valori degli enum.
    attese = (_chiavi_usate()
              | {f"tab.{s}" for s in sezioni}
              | {f"enum.ritmo.{v.value}" for v in Timebase}
              | {f"enum.campi.{v.value}" for v in FieldMode}
              | {f"conf.tipo.{v.value}" for v in Kind})
    mancanti = sorted(attese - i18n.catalogo(i18n.PREDEFINITA).keys())
    assert not mancanti, mancanti


@caso("ogni chiamata ai testi passa i segnaposto che il testo si aspetta")
def _() -> None:
    """Un segnaposto in piu' o in meno fa sollevare `format` solo quando
    quel testo viene disegnato: magari in una schermata che si vede una
    volta al mese. Qui si confrontano chiamata e testo per tutto il codice."""
    import ast
    import string
    voci = i18n.catalogo(i18n.PREDEFINITA)
    errori = []
    for f in [ROOT / "ui" / "app.py", *(ROOT / "src" / "animeup").glob("*.py")]:
        for nodo in ast.walk(ast.parse(f.read_text())):
            if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id in ("t", "tn") and nodo.args
                    and isinstance(nodo.args[0], ast.Constant)
                    and isinstance(nodo.args[0].value, str)):
                continue
            if any(k.arg is None for k in nodo.keywords):
                continue                      # **diz: non verificabile qui
            passati = {k.arg for k in nodo.keywords}
            chiave = nodo.args[0].value
            if nodo.func.id == "tn":
                passati.add("n")
                chiavi = [f"{chiave}.uno", f"{chiave}.altri"]
            else:
                chiavi = [chiave]
            for c in chiavi:
                if c not in voci:
                    continue                  # lo dice gia' un altro caso
                attesi = {campo for _, campo, _, _ in
                          string.Formatter().parse(voci[c]) if campo}
                # `tn` passa sempre `n`: il testo puo' anche non usarlo.
                if nodo.func.id == "tn":
                    attesi.add("n")
                if attesi != passati:
                    errori.append(f"{f.name}:{nodo.lineno} {c}: attesi "
                                  f"{sorted(attesi)}, passati {sorted(passati)}")
    assert not errori, "\n".join(errori)


@caso("la cartella LAVORAZIONI di prima della 1.4 diventa JOBS, col contenuto")
def _() -> None:
    """Rinominata la cartella, una lavorazione interrotta sotto il nome vecchio
    sarebbe sparita dall'elenco senza un avviso. Dalla 1.6 JOBS sta dentro
    OUTPUT, e la lavorazione deve arrivarci."""
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        (radice / "LAVORAZIONI" / "episodio 2026-08-10 abcd1234").mkdir(parents=True)
        p = Paths(radice)
        p.ensure_dirs()
        assert not (radice / "LAVORAZIONI").exists()
        assert (p.work / "episodio 2026-08-10 abcd1234").is_dir()
        assert p.work == (radice / "OUTPUT" / "JOBS").resolve(), p.work


@caso("i colori stanno solo in tema.py: nell'interfaccia nessun colore scritto a mano")
def _() -> None:
    """Prima erano 117 colori sparsi nel CSS: cambiarne uno voleva dire
    cercarlo in venti posti, e un tema chiaro era impensabile. Ora il CSS usa
    solo variabili, e le variabili nascono da `tema.py`."""
    import re as _re
    app = (ROOT / "ui" / "app.py").read_text()
    # Le entita' HTML (&#9888;) non sono colori.
    trovati = [m.group(0) for m in _re.finditer(
        r"(?<!&)#[0-9A-Fa-f]{6}\b|(?<!&)#[0-9A-Fa-f]{3}\b|rgba?\(\s*\d+\s*,", app)]
    assert not trovati, f"colori scritti a mano nell'interfaccia: {trovati[:5]}"


@caso("Streamlit e il CSS usano gli stessi colori, in tutti e due i temi")
def _() -> None:
    import tomllib
    from animeup import tema
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    for i, nome in enumerate(("dark", "light")):
        sezione = cfg["theme"][nome]
        attesi = {"primaryColor": "primaryStrong", "backgroundColor": "bg",
                  "secondaryBackgroundColor": "surface", "textColor": "textPrimary",
                  "borderColor": "borderColor", "linkColor": "primaryText",
                  "greenColor": "green", "yellowColor": "yellow", "redColor": "red"}
        for chiave, token in attesi.items():
            assert sezione[chiave].upper() == tema.TOKEN[token][i].upper(), (
                f"{nome}.{chiave} = {sezione[chiave]}, ma {token} vale "
                f"{tema.TOKEN[token][i]}")
        laterale = sezione["sidebar"]
        assert laterale["backgroundColor"].upper() == tema.TOKEN["sidebar"][i].upper()
    assert "prefers-color-scheme: light" in tema.css(tema.SISTEMA)
    assert "prefers-color-scheme" not in tema.css(tema.SCURO)
    assert tema.streamlit(tema.CHIARO) == "Light" and tema.streamlit("boh") == "System"


@caso("il confronto in un processo suo: uno alla volta, e chi muore risulta interrotto")
def _() -> None:
    """Il confronto girava dentro la pagina e un clic lo uccideva. Ora gira
    staccato: la pagina deve capire se e' vivo, rifiutarne un secondo, e non
    credere vivo per sempre un processo morto (Mac spento a meta')."""
    import json as _json
    from animeup import confronto
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as tmp:
        p = Paths(Path(tmp))
        assert confronto.stato(p) is None and not confronto.in_corso(p)
        c = confronto.cartella(p)
        c.mkdir(parents=True)
        vivo = {"state": "running", "pid": os.getpid(), "file": "/x/a.mkv",
                "total": 4, "done": 1, "fraction": 0.5, "results": []}
        (c / "status.json").write_text(_json.dumps(vivo))
        assert confronto.in_corso(p), "un confronto vivo non risulta in corso"
        assert confronto.avvia({"file": "/x/b.mkv"}, p) is False, \
            "partito un secondo confronto mentre il primo gira"
        morto = dict(vivo, pid=999999)
        (c / "status.json").write_text(_json.dumps(morto))
        assert confronto.stato(p)["state"] == confronto.INTERROTTO
        assert not confronto.in_corso(p)
        assert confronto.ferma(p) is False, "fermato un confronto che non c'e'"
        (c / "status.json").write_text("{rotto")
        assert confronto.stato(p) is None
    app = (ROOT / "ui" / "app.py").read_text()
    assert "conf.fragile" not in app and "def _genera(" not in app, \
        "il confronto gira ancora dentro la pagina"


@caso("la disposizione di prima della 1.6 passa a quella nuova senza perdere niente")
def _() -> None:
    """Registri e impostazioni vanno nello stato, in inglese; JOBS e i log
    dei file dentro OUTPUT; una lavorazione sospesa resta riprendibile e
    lo storico resta leggibile dalle stime. Rilanciare non cambia niente."""
    import json as _json
    from animeup import storico, su_disco
    from animeup.migrazione import _fatte
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        reg = radice / "registri"
        reg.mkdir()
        (reg / "esiti.jsonl").write_text("".join(_json.dumps(
            {"file": f"ep{i}.mkv", "secondi": 100.0 + i, "dedup": 0.3,
             "fotogrammi": 30000, "quando": i}) + "\n" for i in range(3)))
        (reg / "impostazioni.json").write_text(_json.dumps(
            {"altezza": 1080, "lingua": "it", "pausa": 5}))
        (reg / "taratura.json").write_text(_json.dumps(
            {"versione": 1, "macchine": {"Chip X": {"codifica_fps": 16}}}))
        (reg / "ep0 [upscale 1080p cugan x3 crf18 dd].log").write_text("[cmd] x\n")
        lav = radice / "JOBS" / "ep0 2026-10-23 fc158b30"
        lav.mkdir(parents=True)
        (lav / "parametri.json").write_text(_json.dumps(
            {"altezza": 1080, "modello": "cugan", "fotogrammi": 32374}))
        (lav / "state.json").write_text(_json.dumps(
            {"signature": "s", "extracted": 5, "secondi_spesi": 12.5,
             "blocchi": [{"da": 0, "a": 10, "tenuti": 8}]}))
        (lav / ".sospeso").write_text(_json.dumps({"da": 1.0, "pids": [1]}))
        (radice / "JOBS" / ".analisi").mkdir()
        (radice / "JOBS" / ".analisi" / "ep0-x.json").write_text("{}")
        (radice / "anteprime" / "ep0 fc158b30").mkdir(parents=True)
        (radice / "anteprime" / "ep0 fc158b30" / "originale.mkv").write_text("")
        (radice / "OUTPUT").mkdir()
        (radice / "OUTPUT" / "ep1.mkv.inlavorazione").write_text("")
        (radice / "OUTPUT" / "ep2 [upscale].PARZIALE.mkv").write_text("")

        for _ in range(2):
            _fatte.clear()
            p = Paths(radice)
            p.ensure_dirs()

        assert not reg.exists() and not (radice / "JOBS").exists()
        assert not (radice / "anteprime").exists()
        storia = p.storico.read_text()
        assert '"seconds"' in storia and '"secondi"' not in storia, storia
        assert len(storia.splitlines()) == 3, "righe perse o doppie"
        assert '"language": "it"' in p.impostazioni.read_text()
        assert '"machines"' in p.taratura.read_text()
        assert (p.job_logs / "ep0 [upscale 1080p cugan x3 crf18 dd].log").is_file()
        nuova = p.work / "ep0 2026-10-23 fc158b30"
        assert su_disco.leggi(nuova / "parameters.json")["fotogrammi"] == 32374
        stato = (nuova / "state.json").read_text()
        assert '"seconds_spent"' in stato and '"from"' in stato, stato
        assert su_disco.leggi(nuova / ".suspended")["da"] == 1.0
        assert (p.analisi / "ep0-x.json").is_file()
        assert (radice / "OUTPUT" / "ep1.mkv.incomplete").is_file()
        assert (radice / "OUTPUT" / "ep2 [upscale].DEFECTIVE.mkv").is_file()
        # Le stime leggono lo storico migrato come prima.
        assert len(storico._pagelle(p)) == 3


@caso("con ANIMEUP_ROOT i dati vanno altrove, ma i binari restano col programma")
def _() -> None:
    """Puntando ANIMEUP_ROOT a una cartella di soli dati, bin/ veniva cercato
    li': ffmpeg e i motori sparivano e la sidebar segnava «dipendenze dal
    sistema», mentre il lanciatore li cercava (giustamente) accanto al codice."""
    from animeup.paths import Paths, code_root
    vecchio = os.environ.get("ANIMEUP_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ANIMEUP_ROOT"] = tmp
        try:
            p = Paths()
            assert p.root == Path(tmp).resolve(), p.root
            assert p.input == Path(tmp).resolve() / "INPUT"
            assert p.bin == code_root() / "bin", p.bin
            # Anche il clip della taratura viaggia col programma: cercato
            # nella cartella dati, la taratura dall'interfaccia restava appesa.
            assert p.campioni == code_root() / "samples", p.campioni
            assert (p.campioni / "bbb-480p.mkv").is_file()
        finally:
            if vecchio is None:
                os.environ.pop("ANIMEUP_ROOT", None)
            else:
                os.environ["ANIMEUP_ROOT"] = vecchio
        # Una radice esplicita resta autosufficiente: i test ci contano.
        assert Paths(Path(tmp)).bin == Path(tmp).resolve() / "bin"


@caso("ffmpeg e' fissato a una release, con checksum, e la versione si legge")
def _() -> None:
    """Con «l'ultima snapshot» due installazioni a una settimana di distanza
    codificavano con due ffmpeg diversi: un difetto non si riproduceva."""
    from animeup import setup as st_
    assert set(st_.FFMPEG_SOURCES) == set(st_.FFMPEG_SHA256) == {"ffmpeg", "ffprobe"}
    for nome, url in st_.FFMPEG_SOURCES.items():
        assert "latest" not in url and "snapshot" not in url, url
        assert st_.FFMPEG_VERSIONE in url, url
        assert len(st_.FFMPEG_SHA256[nome]) == 64, nome
    with tempfile.TemporaryDirectory() as tmp:
        finto = Path(tmp) / "ffmpeg"
        finto.write_text("#!/bin/sh\necho 'ffmpeg version 9.0.2-https://www.martin-riedl.de Copyright'\n")
        finto.chmod(0o755)
        assert st_.versione_ffmpeg(finto) == "9.0.2"
        finto.write_text("#!/bin/sh\necho 'ffmpeg version N-125892-g406c5a37aa-https://x Copyright'\n")
        assert st_.versione_ffmpeg(finto) == "N"
        finto.write_text("#!/bin/sh\necho 'qualcos altro'\n")
        assert st_.versione_ffmpeg(finto) is None
        assert st_.versione_ffmpeg(Path(tmp) / "non-esiste") is None


@caso("l'avviso di aggiornamento: solo versioni piu' nuove, mai la rete in primo piano")
def _() -> None:
    import json as _json
    import time as _time
    from animeup import aggiornamenti as agg
    assert agg.versione("v1.4.2") == (1, 4, 2) == agg.versione("1.4.2")
    assert agg.versione("v2.0.0-beta") is None and agg.versione("") is None
    assert agg.versione("1.10.0") > agg.versione("1.9.9")
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "aggiornamenti.json"
        vero = agg._file
        agg._file = lambda: cache
        vera_rete = agg._chiedi_a_github
        chieste = []
        agg._chiedi_a_github = lambda: chieste.append(1)
        agg._avvio_controllato = False
        try:
            adesso = _time.time()
            cache.write_text(_json.dumps({"controllato": adesso, "ultima": "v0.0.1"}))
            # A ogni avvio si chiede comunque, anche con un controllo fresco;
            # poi, nella stessa sessione, si legge la cache.
            agg.disponibile(adesso=adesso)
            agg.disponibile(adesso=adesso)
            _time.sleep(0.2)
            assert len(chieste) == 1, chieste
            # Controllo recente: si legge la cache, nessun thread di rete.
            cache.write_text(_json.dumps({"controllato": adesso, "ultima": "v999.0.0",
                                          "url": "https://example.invalid/r"}))
            nuova = agg.disponibile(adesso=adesso)
            assert nuova == {"versione": "999.0.0", "url": "https://example.invalid/r"}, nuova
            assert agg.disponibile(attivo=False, adesso=adesso) is None
            cache.write_text(_json.dumps({"controllato": adesso, "ultima": "v0.0.1"}))
            assert agg.disponibile(adesso=adesso) is None
            cache.write_text("non e' json")
            # Cache rotta: nessuna eccezione. (Il thread di rete parte, ma il
            # risultato arriva su disco e non si aspetta.)
            agg._chiedi_a_github = lambda: None
            assert agg.disponibile(adesso=adesso) is None
        finally:
            agg._file = vero
            agg._chiedi_a_github = vera_rete


@caso("con ANIMEUP_STATO i binari scaricati stanno fuori dal programma")
def _() -> None:
    """L'app per macOS non si modifica: Python, ambiente e bin/ vanno nella
    cartella di stato (~/Library/Application Support/AnimeUp)."""
    from animeup.paths import Paths, code_root
    vecchio = os.environ.get("ANIMEUP_STATO")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ANIMEUP_STATO"] = tmp
        try:
            p = Paths()
            assert p.bin == Path(tmp).resolve() / "bin", p.bin
            assert p.campioni == code_root() / "samples", p.campioni
        finally:
            if vecchio is None:
                os.environ.pop("ANIMEUP_STATO", None)
            else:
                os.environ["ANIMEUP_STATO"] = vecchio
    lanciatore = (ROOT / "animeup").read_text()
    for chiave in ('UV_PYTHON_INSTALL_DIR="$STATO/.python"',
                   'UV_PROJECT_ENVIRONMENT="$STATO/.venv"', 'UV="$STATO/bin/uv"'):
        assert chiave in lanciatore, chiave


@caso("l'interfaccia di fabbrica risponde solo da questo Mac")
def _() -> None:
    """Il server ascoltava su tutte le interfacce: chiunque sulla stessa rete
    poteva avviare e fermare lavorazioni. Ora serve --network per aprirlo."""
    cli = (ROOT / "src" / "animeup" / "cli.py").read_text()
    assert '"--server.address", "0.0.0.0" if rete else "127.0.0.1"' in cli
    assert 'typer.Option("--network"' in cli


@caso("la lingua salvata torna al riavvio, e una sconosciuta non rompe niente")
def _() -> None:
    import json as _json
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as tmp:
        radice = Paths(Path(tmp))
        radice.logs.mkdir(parents=True)
        import animeup.paths as _paths
        salvato = _paths.PATHS
        _paths.PATHS = radice
        # Il resto della suite forza l'italiano dall'ambiente: qui si prova
        # proprio cio' che l'ambiente scavalca, quindi lo si toglie.
        forzata = os.environ.pop("ANIMEUP_LANG", None)
        try:
            assert i18n.preferita() == i18n.PREDEFINITA
            radice.impostazioni.write_text(_json.dumps({"lingua": "it"}))
            assert i18n.preferita() == "it"
            radice.impostazioni.write_text(_json.dumps({"lingua": "xx"}))
            assert i18n.preferita() == i18n.PREDEFINITA
            # L'ambiente vince sul salvato.
            radice.impostazioni.write_text(_json.dumps({"lingua": "en"}))
            os.environ["ANIMEUP_LANG"] = "it"
            assert i18n.preferita() == "it"
        finally:
            _paths.PATHS = salvato
            if forzata is None:
                os.environ.pop("ANIMEUP_LANG", None)
            else:
                os.environ["ANIMEUP_LANG"] = forzata
    i18n.imposta("en")
    assert i18n.t("tab.Sorgenti") == "Sources"
    assert i18n.tn("src.avvisi", 1) == "1 warning"
    assert i18n.tn("src.avvisi", 3) == "3 warnings"
    i18n.imposta("xx")
    assert i18n.attiva() == i18n.PREDEFINITA
    i18n.imposta("it")
    assert i18n.t("tab.Sorgenti") == "Sorgenti"


def _app_pezzi(*nomi: str) -> list:
    """Le funzioni (e le costanti) di ui/app.py coi nomi dati, pronte per
    `exec`: l'app intera non si importa fuori da Streamlit."""
    import ast as _ast
    albero = _ast.parse((ROOT / "ui" / "app.py").read_text())
    pezzi = [n for n in albero.body
             if (isinstance(n, _ast.FunctionDef) and n.name in nomi)
             or (isinstance(n, _ast.Assign)
                 and any(getattr(b, "id", None) in nomi for b in n.targets))]
    assert len(pezzi) == len(nomi), f"non trovo tutti {nomi} in ui/app.py"
    return pezzi


def _esegui_app(pezzi: list, ambiente: dict) -> dict:
    import ast as _ast
    exec(compile(_ast.Module(body=pezzi, type_ignores=[]), "app", "exec"),
         ambiente)
    return ambiente


@caso("con una taratura in corso Avvia e Riprendi non partono")
def _() -> None:
    """Le due cose si dividerebbero la GPU e la taratura salverebbe numeri
    falsi. La taratura rifiutava gia' di partire durante una lavorazione;
    il contrario no: `taratura.in_corso()` non veniva mai guardato."""
    import ast as _ast
    import types as _types
    from animeup import taratura

    # 1. Il marcatore: vivo se il PID esiste, morto se no.
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        finti = _types.SimpleNamespace(root=radice, work=radice / "JOBS",
                                       cache=radice / "cache")
        assert not taratura.in_corso(finti), "nessun marcatore, eppure in corso"
        marcatore = radice / "JOBS" / ".calibration" / "running.lock"
        marcatore.parent.mkdir(parents=True)
        import subprocess as _sp
        estraneo = _sp.Popen(["sleep", "30"])
        finto = _sp.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                           "animeup-finto"])
        try:
            # Dopo uno spegnimento il numero puo' essere di chiunque.
            marcatore.write_text(str(estraneo.pid))
            assert not taratura.in_corso(finti), "un PID riciclato blocca la taratura"
            marcatore.write_text(str(finto.pid))
            assert taratura.in_corso(finti), "il PID e' vivo ma non risulta in corso"
        finally:
            estraneo.kill()
            finto.kill()

    # 2. `_avvia` si ferma PRIMA di lanciare qualunque cosa.
    class _Lanciato(Exception):
        pass

    def _vietato(*_a, **_k):
        raise _Lanciato()

    errori: list[str] = []
    stato = {"tarando": True}
    ambiente = _esegui_app(_app_pezzi("_avvia", "_riprendi"), {
        "taratura": _types.SimpleNamespace(in_corso=lambda: stato["tarando"]),
        "monitor": _types.SimpleNamespace(lancio_vivo=lambda: False,
                                          catena=lambda: None, pausa=lambda: None),
        "st": _types.SimpleNamespace(error=lambda m, **_k: errori.append(m)),
        "t": i18n.t,
        # Oltre la guardia la prima cosa che si tocca e' il registro: se ci
        # si arriva, la guardia non ha fermato niente.
        "PATHS": type("Registri", (), {
            "registro_coda": property(lambda _s: _vietato())})(),
        "_leggi_parametri": lambda _c: {},
        "Path": Path,
    })
    assert ambiente["_avvia"]([], {}) is False, "Avvia e' partito durante la taratura"
    assert ambiente["_riprendi"](None, None, {}) is False, \
        "Riprendi e' partito durante la taratura"
    assert errori and all("calibrazione" in e for e in errori), errori
    stato["tarando"] = False
    try:
        ambiente["_avvia"]([], {})
    except _Lanciato:
        pass
    else:
        raise AssertionError("senza taratura la guardia blocca lo stesso")

    # 3. I pulsanti sono spenti, non solo la funzione che chiamano.
    albero = _ast.parse((ROOT / "ui" / "app.py").read_text())
    spenti = set()
    for n in _ast.walk(albero):
        if not (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
                and n.func.attr == "button" and n.args
                and isinstance(n.args[0], _ast.Call)
                and isinstance(n.args[0].args[0], _ast.Constant)):
            continue
        disab = next((k.value for k in n.keywords if k.arg == "disabled"), None)
        if disab is not None and any(isinstance(x, _ast.Name) and x.id == "tarando"
                                     for x in _ast.walk(disab)):
            spenti.add(n.args[0].args[0].value)
    assert {"lavb.avvia", "lavb.riprendi"} <= spenti, \
        f"pulsanti spenti durante la taratura: {sorted(spenti)}"


@caso("una riga conclusa con la cartella rimasta in JOBS si puo' scartare")
def _() -> None:
    """La riga diceva «concluso con avvisi … la cartella resta per
    controllo», ma gli avvisi non trattengono piu' la cartella (solo i
    difetti, e allora l'uscita diventa .DEFECTIVE). E non aveva Scarta: quei
    GB non si liberavano dall'interfaccia."""
    import ast as _ast
    from animeup.pipeline import JobResult
    # Il presupposto dell'etichetta: un avviso non trattiene la cartella.
    campi = {f: None for f in JobResult.__dataclass_fields__}
    r = JobResult(**{**campi, "frames_written": 10, "frames_expected": 10,
                  "warnings": ["nota"], "difetti": []})
    assert r.ok, "un avviso trattiene di nuovo la cartella: rivedi l'etichetta"

    for lingua in ("en", "it"):
        i18n.imposta(lingua)
        testo = i18n.t("lavb.concluso_residuo")
        assert "JOBS" in testo and i18n.t("lavb.scarta") in testo, testo
        assert not any(p in testo.lower() for p in ("warning", "avvis")), testo
    i18n.imposta("it")

    albero = _ast.parse((ROOT / "ui" / "app.py").read_text())
    trovato = False
    for n in _ast.walk(albero):
        if not (isinstance(n, _ast.BoolOp) and isinstance(n.op, _ast.And)):
            continue
        nomi = [v.id for v in n.values if isinstance(v, _ast.Name)]
        pulsanti = [v for v in n.values if isinstance(v, _ast.Call)
                    and getattr(v.func, "attr", "") == "button"
                    and _ast.dump(v.args[0]).count("lavb.scarta")]
        if "concluso" in nomi and pulsanti:
            trovato = True
    assert trovato, "nessuno Scarta sulle righe concluse con la cartella in JOBS"


@caso("lo spazio su disco non conta come differenza col file sospeso")
def _() -> None:
    """Si ricalcola a ogni avvio, quindi non coincideva mai con quello
    salvato: l'avviso in sidebar scattava per lui e basta, e «Riporta la
    sidebar…» rimetteva uno spazio vecchio."""
    import ast as _ast
    pezzi = _app_pezzi("_IMPOSTAZIONI_DEFAULT", "_FUORI_DAL_CONFRONTO",
                       "_diversi_dal_sospeso", "_ripristina_parametri")
    stato: dict = {}

    class _St:
        session_state = stato

    from animeup import impostazioni
    ambiente = _esegui_app(pezzi, {"st": _St, "impostazioni": impostazioni,
                                   "_impostazioni_pulite": lambda r: dict(r)})
    fabbrica = ambiente["_IMPOSTAZIONI_DEFAULT"]
    assert "disco" in fabbrica, "lo spazio non e' piu' un'impostazione?"
    diversi = ambiente["_diversi_dal_sospeso"]
    attuali = dict(fabbrica, disco=120)
    assert diversi(dict(fabbrica, disco=80), attuali) == [], \
        "solo lo spazio e' diverso, eppure scatta l'avviso"
    altro = 20 if fabbrica["crf"] != 20 else 21
    assert diversi(dict(fabbrica, disco=80, crf=altro), attuali) == ["crf"]
    ambiente["_ripristina_parametri"](dict(fabbrica, disco=80, crf=altro))
    assert "w_disco" not in stato, "il ripristino rimette uno spazio vecchio"
    assert stato.get("w_crf") == altro, "il ripristino non rimette piu' il CRF"


@caso("gli avvisi su telecine e interlacciato non promettono una correzione")
def _() -> None:
    """Dicevano «va applicato l'inverse telecine», come se ci pensasse
    AnimeUp: che invece non deinterlaccia e non fa inverse telecine."""
    from animeup.plan import Plan
    assert "ivtc" in Plan.__dict__, "Plan.ivtc sparito: rivedi questo caso"
    for lingua, strumento, promesse in (
            ("en", "dedicated tool", ("is needed", "will be")),
            ("it", "strumento dedicato", ("va applicato", "verrà"))):
        i18n.imposta(lingua)
        for chiave in ("probe.telecine", "probe.interlacciato"):
            testo = i18n.t(chiave)
            assert "AnimeUp" in testo and strumento in testo, f"{lingua} {chiave}: {testo}"
            assert not any(p in testo.lower() for p in promesse), f"{lingua} {chiave}: {testo}"
    i18n.imposta("it")


@caso("la regola generale non consiglia il denoise leggero dove non arriva")
def _() -> None:
    """Il denoise leggero esiste solo a x2: a 1080p non arriva dai sorgenti
    fra 380 e 539 righe, proprio la fascia in cui la regola lo consigliava."""
    import dataclasses
    from animeup.models import altezza_minima
    from animeup.plan import PlanError
    from animeup.models import ALTEZZA_INCERTA, CLEAN_SOURCE_MIN_HEIGHT

    # 1. La soglia coincide con quella del piano, al pixel.
    r = probe_source(CAMPIONI / "clip20s.mkv", with_fields=False)
    for uscita in (720, 1080):
        minimo = altezza_minima("cugan-denoise", uscita)
        for h in (minimo - 2, minimo):
            g = dataclasses.replace(r.geometry, width=h * 4 // 3 // 2 * 2,
                                    height=h, display_width=h * 4 // 3 // 2 * 2,
                                    display_height=h, sar=Fraction(1))
            prova = dataclasses.replace(r, geometry=g)
            try:
                build_plan(prova, target_height=uscita, model_key="cugan-denoise")
                arriva = True
            except PlanError:
                arriva = False
            assert arriva == (h >= minimo), \
                f"{h}p -> {uscita}p: piano {arriva}, soglia {minimo}"

    # 2. La regola segue l'altezza d'uscita.
    ambiente = _esegui_app(_app_pezzi("perche_generale"), {
        "t": i18n.t, "altezza_minima": altezza_minima,
        "ALTEZZA_INCERTA": ALTEZZA_INCERTA,
        "CLEAN_SOURCE_MIN_HEIGHT": CLEAN_SOURCE_MIN_HEIGHT, "CATALOG": CATALOG})
    regola = ambiente["perche_generale"]

    def mezzo(*a, **k):
        return regola(*a, **k)[1]

    assert mezzo(720)[2] == i18n.t("conf.pg.mezzo_modello"), mezzo(720)
    a1080 = mezzo(1080)
    assert "540" in a1080[2] and "540" in a1080[3], a1080
    assert mezzo(1080, forza=True)[2] == i18n.t("conf.pg.mezzo_modello")
    a1440 = mezzo(1440)
    assert a1440[1] == "verde" and a1440[2] == CATALOG["animevideov3"].label, a1440


@caso("le chip della fascia dei Sorgenti dicono cosa contano")
def _() -> None:
    """«N avvisi» in alto contava i FILE, quello sulla riga gli avvisi del
    file: stesso aspetto, significato diverso. E «N sotto soglia» non
    diceva quale soglia."""
    from animeup.models import CLEAN_SOURCE_MIN_HEIGHT
    i18n.imposta("en")
    assert i18n.tn("src.file_con_avvisi", 2) == "2 files with warnings"
    assert i18n.tn("src.file_con_avvisi", 1) == "1 file with warnings"
    assert str(CLEAN_SOURCE_MIN_HEIGHT) in i18n.t(
        "src.sotto_soglia", n=3, soglia=CLEAN_SOURCE_MIN_HEIGHT)
    i18n.imposta("it")
    app = (ROOT / "ui" / "app.py").read_text()
    assert "tn('src.file_con_avvisi', con_avvisi)" in app, \
        "la chip della fascia non usa piu' il conteggio dei file"


@caso("con la sidebar congelata ogni interruttore e' spento davvero")
def _() -> None:
    """«Analisi approfondita» era solo ingrigito dal CSS: raggiungibile da
    tastiera mentre gli altri erano `disabled`."""
    import ast as _ast
    albero = _ast.parse((ROOT / "ui" / "app.py").read_text())
    senza = []
    for n in _ast.walk(albero):
        if not (isinstance(n, _ast.Call) and getattr(n.func, "attr", "") == "toggle"):
            continue
        chiave = next((k.value.value for k in n.keywords if k.arg == "key"
                       and isinstance(k.value, _ast.Constant)), "")
        if not chiave.startswith("w_"):
            continue
        if not any(k.arg == "disabled" and _ast.dump(k.value).count("congelata")
                   for k in n.keywords):
            senza.append(chiave)
    assert not senza, f"interruttori non spenti con la sidebar congelata: {senza}"


@caso("un sorgente dal nome lunghissimo ha un nome d'uscita valido")
def _() -> None:
    """Oltre i 255 byte il controllo dell'uscita alzava ENAMETOOLONG e la coda
    intera moriva prima di cominciare."""
    from animeup.plan import output_name
    for stem in ("a" * 240, "アニメ" * 40, "ok"):
        nome = output_name(stem, target_height=1080, scale=4, model_tag="animevideov3",
                           crf=18, denoise=True, dedup=True, preset="veryslow")
        assert len((nome + ".mkv.incomplete").encode("utf-8")) <= 255, len(nome)
    assert output_name("ok", target_height=1080, scale=2, model_tag="m",
                       crf=18).startswith("ok ["), "un nome corto non si tocca"


@caso("un disco esterno scollegato non ha lo spazio del disco di avvio")
def _() -> None:
    from animeup.paths import gb_liberi
    assert gb_liberi(Path("/Volumes/AnimeUpNonEsiste/OUTPUT")) == 0.0
    assert gb_liberi(Path(tempfile.gettempdir()) / "non" / "ancora") > 0


@caso("rinominare la cartella dei video da elaborare non perde il lavoro fatto")
def _() -> None:
    """L'identita' del sorgente conteneva il nome della cartella: spostati i
    video in una cartella nuova, le lavorazioni interrotte ripartivano da capo."""
    from animeup.pipeline import identita_sorgente
    a = identita_sorgente(Path("/v/INPUT/ep.mkv"), Path("/v/INPUT"))
    b = identita_sorgente(Path("/w/Anime Folder/ep.mkv"), Path("/w/Anime Folder"))
    assert a == b == "INPUT/ep.mkv", (a, b)
    assert identita_sorgente(Path("/altrove/ep.mkv"), Path("/v/INPUT")) == "/altrove/ep.mkv"


@caso("la migrazione non perde niente nei casi storti")
def _() -> None:
    """Dall'audit: la stessa cartella scritta in due modi si cancellava da
    sola; storici fusi due volte; la taratura vecchia cancellata se c'era gia'
    quella nuova; una 1.5 ancora al lavoro derubata dei suoi file."""
    import json as _json
    import os as _os
    from animeup import migrazione
    from animeup.paths import Paths
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp) / "data"
        lav = radice / "JOBS" / "ep 2026-10-23 abcd1234"
        lav.mkdir(parents=True)
        (lav / "frame.png").write_bytes(b"x" * 1000)
        reg = radice / "registri"
        reg.mkdir()
        (reg / "esiti.jsonl").write_text(_json.dumps({"file": "a", "quando": 1}) + "\n")
        (reg / "taratura.json").write_text(_json.dumps(
            {"macchine": {"Apple M1": {"quando": 5}}}))
        stato = Path(tmp) / "stato"
        (stato / "records").mkdir(parents=True)
        (stato / "records" / "calibration.json").write_text(_json.dumps(
            {"machines": {"Apple M4": {"when": 9}}}))
        # Una 1.5 al lavoro: non si tocca niente.
        (lav / "in-corso.lock").write_text(str(_os.getpid()))
        variante = Path(tmp) / "DATA"   # APFS: la radice stessa, in maiuscolo

        def _p():
            q = Paths(radice)
            q._output, q._stato = variante, stato
            return q
        try:
            migrazione._fatte.clear()
            _p().ensure_dirs()
            assert (reg / "esiti.jsonl").exists(), "spostato sotto una 1.5 al lavoro"
            assert ("mig.rimandata", {}) in migrazione.avvisi
            (lav / "in-corso.lock").unlink()
            for _ in range(2):
                migrazione._fatte.clear()
                _p().ensure_dirs()
            assert (lav / "frame.png").is_file() or any(
                Path(tmp).rglob("frame.png")), "la lavorazione e' sparita"
            assert sum(1 for f in Path(tmp).rglob("frame.png")) == 1
            cal = _json.loads((stato / "records" / "calibration.json").read_text())
            assert set(cal["machines"]) == {"Apple M1", "Apple M4"}, cal
            righe = (stato / "records" / "history.jsonl").read_text().splitlines()
            assert len(righe) == 1, righe
            # Un vecchio file rimasto (non cancellabile) non raddoppia lo storico.
            reg.mkdir(exist_ok=True)
            (reg / "esiti.jsonl").write_text(_json.dumps({"file": "a", "quando": 1}) + "\n")
            migrazione._fatte.clear()
            _p().ensure_dirs()
            assert len((stato / "records" / "history.jsonl").read_text().splitlines()) == 1
        finally:
            pass


# ===========================================================================
#  Il motore dell'app nativa (`animeup serve`)
# ===========================================================================

def _serve(righe: list[str], stato: Path, codice: str | None = None,
           ambiente: dict | None = None) -> tuple[list[dict], str]:
    """Lancia il motore con `righe` su stdin; ritorna (messaggi, stderr).

    Ogni riga di stdout DEVE essere JSON: e' il punto del canale dedicato."""
    env = {**os.environ, "ANIMEUP_STATO": str(stato),
           "ANIMEUP_WORK": str(stato / "Jobs"),
           "PYTHONPATH": str(ROOT / "src"), **(ambiente or {})}
    env.pop("ANIMEUP_LANG", None)
    comando = ([sys.executable, "-c", codice] if codice
               else [sys.executable, "-m", "animeup.cli", "serve"])
    esito = subprocess.run(comando, input="\n".join(righe) + "\n",
                           capture_output=True, text=True, env=env, timeout=120)
    assert esito.returncode == 0, esito.stderr[-2000:]
    import json as _json
    messaggi = []
    for riga in esito.stdout.splitlines():
        try:
            messaggi.append(_json.loads(riga))
        except ValueError:
            raise AssertionError(f"riga non JSON sul canale del protocollo: {riga!r}")
    return messaggi, esito.stderr


def _risposte(messaggi: list[dict]) -> dict:
    return {m["id"]: m for m in messaggi if "id" in m and m["id"] is not None}


@caso("serve: risponde a ogni metodo, per id, e dice prima di essere pronto")
def _() -> None:
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        metodi = ["hello", "machine.info", "calibration.state", "tools.status",
                  "folders.state", "settings.get"]
        righe = [_json.dumps({"id": i, "method": m}) for i, m in enumerate(metodi, 1)]
        messaggi, err = _serve(righe, Path(tmp))
        assert messaggi[0].get("event") == "ready", messaggi[:1]
        r = _risposte(messaggi)
        for i, m in enumerate(metodi, 1):
            assert "result" in r.get(i, {}), (m, r.get(i), err[-800:])
        from animeup import __version__
        assert r[1]["result"]["version"] == __version__
        assert r[1]["result"]["protocol"] == 1
        info = r[2]["result"]
        assert info["chip"] and info["arch"], info
        cal = r[3]["result"]
        assert cal["state"] == "never" and cal["when"] is None, cal
        assert [x["key"] for x in cal["models"]][:1] == ["animevideov3"]
        attrezzi = {x["key"]: x for x in r[4]["result"]["tools"]}
        assert set(attrezzi) == {"ffmpeg", "ffprobe", "realesrgan", "realcugan"}
        # Una cartella di stato vuota non ha binari suoi: niente e' verificato.
        assert not r[4]["result"]["all_verified"]
        assert r[4]["result"]["python"]["short"].startswith("3.")
        cartelle = r[5]["result"]
        assert cartelle["work_folder"] == str(Path(tmp) / "Jobs"), cartelle
        assert cartelle["is_default"] and not cartelle["exists"]
        assert cartelle["space_rule_gb"] > cartelle["space_min_gb"]
        imp = r[6]["result"]
        # Le chiavi come sul file, in inglese.
        assert imp["language"] == "en" and imp["height"] == 1080, imp
        assert imp["disk_gb"] == cartelle["space_rule_gb"], (imp, cartelle)
        # Niente cartelle della 1.6 create dal motore.
        assert not (Path(tmp) / "INPUT").exists()


@caso("serve: gli errori tornano come errori, e il motore non cade")
def _() -> None:
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        righe = ["questo non e' JSON",
                 _json.dumps({"id": 1, "method": "niente.di.simile"}),
                 _json.dumps({"id": 2, "method": "settings.set", "params": {"values": 3}}),
                 _json.dumps([1, 2]),
                 _json.dumps({"id": 3, "method": "hello"})]
        messaggi, _err = _serve(righe, Path(tmp))
        r = _risposte(messaggi)
        assert r[1]["error"]["code"] == "unknown_method", r[1]
        assert r[2]["error"]["code"] == "bad_params", r[2]
        assert "result" in r[3], "dopo gli errori il motore non risponde piu'"
        codici = sorted(m["error"]["code"] for m in messaggi
                        if m.get("id") is None and "error" in m)
        assert codici == ["bad_json", "bad_request"], codici


@caso("serve: le impostazioni si salvano, sanificate, e lo si annuncia")
def _() -> None:
    import json as _json
    from animeup import su_disco
    with tempfile.TemporaryDirectory() as tmp:
        stato = Path(tmp)
        valori = {"language": "it", "height": 1440, "crf": 3, "dedup": False,
                  "work_folder": str(stato / "Altrove"), "inventata": 1}
        righe = [_json.dumps({"id": 1, "method": "settings.set",
                              "params": {"values": valori}}),
                 _json.dumps({"id": 2, "method": "folders.state"})]
        messaggi, err = _serve(righe, stato)
        r = _risposte(messaggi)
        fuori = r[1]["result"]
        assert fuori["language"] == "it" and fuori["height"] == 1440, fuori
        assert fuori["crf"] == 18, "un CRF sotto il minimo e' passato"
        assert fuori["dedup"] is False and "inventata" not in fuori
        assert any(m.get("event") == "settings.changed" for m in messaggi)
        salvato = su_disco.leggi(stato / "records" / "settings.json")
        assert salvato["lingua"] == "it" and salvato["cartella_lavoro"] == str(stato / "Altrove")
        # Il file in inglese, per chi lo apre.
        grezzo = _json.loads((stato / "records" / "settings.json").read_text())
        assert grezzo["work_folder"] == str(stato / "Altrove") and "lingua" not in grezzo
        # La cartella di lavoro scelta vale subito (l'ordine fra le due
        # risposte non e' garantito: si rilegge in un secondo giro).
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "folders.state"})], stato)
        cartelle = _risposte(messaggi)[1]["result"]
        assert cartelle["work_folder"] == str(stato / "Altrove") and not cartelle["is_default"]


@caso("serve: una print dimenticata non sporca il canale del protocollo")
def _() -> None:
    import json as _json
    codice = ("import sys, subprocess\n"
              "import animeup.serve as s\n"
              "def rumore(p):\n"
              "    print('rumore da print')\n"
              "    subprocess.run(['echo', 'rumore da un sottoprocesso'])\n"
              "    return {'ok': True}\n"
              "s.METODI['rumore'] = rumore\n"
              "raise SystemExit(s.esegui())\n")
    with tempfile.TemporaryDirectory() as tmp:
        messaggi, err = _serve([_json.dumps({"id": 1, "method": "rumore"})],
                               Path(tmp), codice=codice)
        assert _risposte(messaggi)[1]["result"] == {"ok": True}
        assert "rumore da print" in err and "rumore da un sottoprocesso" in err, err


@caso("serve: una taratura di un altro Mac o vecchia si riconosce")
def _() -> None:
    import json as _json
    from animeup import taratura
    with tempfile.TemporaryDirectory() as tmp:
        stato = Path(tmp)
        (stato / "records").mkdir()
        f = stato / "records" / "calibration.json"
        f.write_text(_json.dumps({"version": 1, "machines": {
            "mac-altro": {"id": "mac-altro", "chip": "Apple M1", "when": 1.0}}}))
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "calibration.state"})], stato)
        cal = _risposte(messaggi)[1]["result"]
        assert cal["state"] == "other_mac" and cal["other_chip"] == "Apple M1", cal
        # Una voce di prima dell'1.6.8: chiavata sul chip, senza impronta.
        f.write_text(_json.dumps({"version": 1, "machines": {
            taratura.chip(): {"chip": taratura.chip(), "when": 1700000000.0,
                              "mpxs": {"animevideov3": {"2": 2.0}}}}}))
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "calibration.state"})], stato)
        cal = _risposte(messaggi)[1]["result"]
        assert cal["state"] == "old_version" and cal["when"] == 1700000000.0, cal
        v3 = next(m for m in cal["models"] if m["key"] == "animevideov3")
        assert v3["fps_1080p"] == round(2.0 / (960 * 540 / 1e6), 2), v3
        # E una fatta qui: chiavata sull'impronta di questo Mac.
        f.write_text(_json.dumps({"version": 1, "machines": {
            taratura.macchina_id(): {"id": taratura.macchina_id(), "chip": taratura.chip(),
                                     "when": 1800000000.0,
                                     "mpxs": {"animevideov3": {"2": 3.0}}}}}))
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "calibration.state"})], stato)
        assert _risposte(messaggi)[1]["result"]["state"] == "done"


@caso("serve: i video si aggiungono, si espandono, si analizzano e si tolgono")
def _() -> None:
    import json as _json
    import shutil as _sh
    with tempfile.TemporaryDirectory() as tmp:
        stato = Path(tmp) / "stato"
        video = Path(tmp) / "video"
        (video / "Sotto").mkdir(parents=True)
        (video / "Vuota").mkdir()
        _sh.copy(CAMPIONI / "clip20s.mkv", video / "A [480p].mkv")
        _sh.copy(CAMPIONI / "TEST-CFR-23-976fps---17s.mkv", video / "Sotto" / "B.mkv")
        (video / "note.txt").write_text("x")
        righe = [
            _json.dumps({"id": 1, "method": "files.add",
                         "params": {"paths": [str(video)], "subfolders": False}}),
            _json.dumps({"id": 2, "method": "files.add",
                         "params": {"paths": [str(video / "Vuota")], "subfolders": True}}),
            _json.dumps({"id": 3, "method": "files.add",
                         "params": {"paths": [str(video)], "subfolders": True}}),
        ]
        messaggi, err = _serve(righe, stato, ambiente={"ANIMEUP_SERVE_WAIT": "1"})
        r = _risposte(messaggi)
        assert len(r[1]["result"]["added"]) == 1 and r[1]["result"]["unsupported"] == 1, r[1]
        assert r[2]["result"]["empty_folders"] == [str(video / "Vuota")], r[2]
        assert len(r[3]["result"]["added"]) == 1 and r[3]["result"]["already"] == 1, r[3]
        eventi = [m.get("event") for m in messaggi if "event" in m]
        assert eventi.count("file.added") == 2, eventi
        assert eventi.count("analysis.done") == 2, (eventi, err[-1500:])
        fatto = next(m["data"] for m in messaggi if m.get("event") == "analysis.done")
        assert fatto["state"] == "ready" and fatto["report"]["width"] > 0, fatto
        assert "warnings" in fatto["report"] and fatto["report"]["fps_text"], fatto
        # L'elenco sopravvive al riavvio, nello stesso ordine; si toglie un file.
        ids = r[1]["result"]["added"] + r[3]["result"]["added"]
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "files.list"}),
                              _json.dumps({"id": 2, "method": "files.remove", "params": {"ids": ids[:1]}}),
                              _json.dumps({"id": 3, "method": "files.report", "params": {"id": "nessuno"}})],
                             stato)
        r = _risposte(messaggi)
        assert [f["id"] for f in r[1]["result"]["files"]] == ids, r[1]
        assert all(f["state"] == "ready" for f in r[1]["result"]["files"]), r[1]
        assert r[2]["result"]["removed"] == 1
        assert r[3]["error"]["code"] == "not_found"
        salvato = _json.loads((stato / "records" / "files.json").read_text())
        assert [f["id"] for f in salvato["files"]] == ids[1:]


@caso("serve: i piani seguono il modello e l'altezza scelti per file")
def _() -> None:
    import json as _json
    import shutil as _sh
    with tempfile.TemporaryDirectory() as tmp:
        stato = Path(tmp) / "stato"
        video = Path(tmp) / "video"
        video.mkdir()
        _sh.copy(CAMPIONI / "TEST-CFR-23-976fps---17s.mkv", video / "A.mkv")
        messaggi, err = _serve([_json.dumps({"id": 1, "method": "files.add",
                                             "params": {"paths": [str(video)]}})],
                               stato, ambiente={"ANIMEUP_SERVE_WAIT": "1"})
        ident = _risposte(messaggi)[1]["result"]["added"][0]
        # Le richieste girano in parallelo: un giro per ognuna, in ordine.
        r = {}
        for i, riga in enumerate([
                _json.dumps({"id": 1, "method": "plans.get"}),
                _json.dumps({"id": 2, "method": "files.set",
                             "params": {"ids": [ident], "model": "cugan", "height": 720}}),
                _json.dumps({"id": 3, "method": "files.set", "params": {"ids": [ident]}})], 1):
            messaggi, err = _serve([riga], stato)
            r.update(_risposte(messaggi))
        piano = r[1]["result"]["plans"][ident]
        assert piano["ready"] and piano["model"] == piano["recommended"], piano
        assert piano["estimate"] > 0 and piano["chunks"] >= 1, piano
        assert {m["key"] for m in piano["models"]} >= {"animevideov3", "cugan"}
        assert piano["height_is_default"] and piano["height"] == 1080
        assert r[3]["error"]["code"] == "bad_params"
        messaggi, _ = _serve([_json.dumps({"id": 1, "method": "plans.get", "params": {"ids": [ident]}})], stato)
        piano = _risposte(messaggi)[1]["result"]["plans"][ident]
        assert piano["model"] == "cugan" and piano["height"] == 720 and not piano["height_is_default"], piano
        assert piano["output_height"] == 720, piano
        assert piano["output_folder"] == str(video.resolve())

@caso("strumenti: lo scaricamento riprende da dove si era fermato")
def _() -> None:
    import hashlib as _hl
    import http.server
    import threading as _th
    from unittest import mock
    from animeup import strumenti

    dati = os.urandom(300_000)
    richieste = []

    class Gestore(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            intervallo = self.headers.get("Range")
            richieste.append(intervallo)
            inizio = int(intervallo.split("=")[1].rstrip("-")) if intervallo else 0
            self.send_response(206 if intervallo else 200)
            self.send_header("Content-Length", str(len(dati) - inizio))
            self.end_headers()
            self.wfile.write(dati[inizio:])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gestore)
    _th.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/pacchetto.zip"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            finti = mock.patch.object(strumenti, "_cartella_parziali", lambda: Path(tmp))
            with finti:
                (Path(tmp) / "p.zip.part").write_bytes(dati[:100_000])
                visti = []
                f = strumenti.scarica(url, "p.zip", _hl.sha256(dati).hexdigest(),
                                      lambda a, b: visti.append((a, b)))
                assert f.read_bytes() == dati
                assert richieste == ["bytes=100000-"], richieste
                assert visti[-1] == (len(dati), len(dati)), visti[-1:]
                # Gia' completo: nessuna richiesta in piu'.
                strumenti.scarica(url, "p.zip", _hl.sha256(dati).hexdigest(), lambda a, b: None)
                assert len(richieste) == 1
                # Checksum sbagliato: errore, e il parziale non resta.
                try:
                    strumenti.scarica(url, "q.zip", "0" * 64, lambda a, b: None)
                    raise AssertionError("un checksum sbagliato e' passato")
                except ValueError:
                    pass
                assert not (Path(tmp) / "q.zip.part").exists()
                assert not (Path(tmp) / "q.zip").exists()
    finally:
        server.shutdown()


def main() -> int:
    if SINTETICI:
        # Detto a schermo: un verde sui sintetici non e' un verde sui veri.
        inizio = time.monotonic()
        fixtures.prepara(FFMPEG)
        perche = ("forzati da ANIMEUP_TEST_FIXTURES" if CAMPIONI_VERI.is_dir()
                  else f"{CAMPIONI_VERI} non c'e'")
        print(f"campioni SINTETICI in {CAMPIONI} ({perche}; pronti in "
              f"{time.monotonic() - inizio:.1f}s)")

    # Un filtro sul nome: le prove di mutazione rilanciano lo stesso caso
    # decine di volte, e far girare ogni volta l'intera suite su un disco
    # esterno costa minuti (una sequenza di mutazioni e' finita in timeout
    # a meta', lasciando il codice mutato sul disco).
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    casi = [(n, f) for n, f in _casi if filtro in n]
    if not casi:
        print(f"nessun caso corrisponde a «{filtro}»")
        return 2
    if filtro:
        # Detto FORTE: «12/12 passati» in fondo a una corsa parziale ha
        # esattamente l'aspetto di una suite verde, e il filtro serve alle
        # prove di mutazione — cioe' proprio ai momenti in cui ci si fida
        # del verde per decidere qualcosa.
        print(f"** CORSA PARZIALE: solo {len(casi)} casi, quelli che contengono "
              f"«{filtro}», su {len(_casi)} totali **")

    passati, saltati, falliti = 0, [], []
    for nome, fn in casi:
        try:
            fn()
        except Saltato as exc:
            saltati.append((nome, str(exc)))
            print(f"  SALTATO  {nome}  ({exc})")
        except Exception as exc:  # noqa: BLE001 - si riporta tutto
            falliti.append((nome, exc, traceback.format_exc()))
            print(f"  FALLITO  {nome}")
        else:
            passati += 1
            print(f"  ok       {nome}")

    # I saltati si contano a parte: «140/144 passati, 4 saltati» non deve
    # avere l'aspetto di una suite verde al completo.
    print(f"\n{passati}/{len(casi)} passati"
          + (f", {len(saltati)} saltati" if saltati else "")
          + (f"  (parziale: filtro «{filtro}»)" if filtro else ""))
    for nome, motivo in saltati:
        print(f"  saltato: {nome} — {motivo}")
    for nome, exc, tb in falliti:
        print(f"\n--- {nome} ---\n{exc}")
        print("\n".join(tb.strip().splitlines()[-6:]))
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
