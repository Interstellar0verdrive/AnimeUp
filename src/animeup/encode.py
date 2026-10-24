"""Estrazione dei fotogrammi, codifica dei segmenti e assemblaggio finale."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from .ffmpeg import FFmpegError
from .paths import PATHS, Paths
from .plan import Plan

# Sottotitoli testuali che MKV non sa copiare: vanno convertiti, altrimenti il
# mux fallisce dopo ore di elaborazione già spese.
UNCOPYABLE_SUBTITLES = {"mov_text", "eia_608", "eia_708", "dvb_teletext"}

# Sottotitoli grafici: NON convertibili in testo. Vanno copiati così come
# sono; tentare di trasformarli in SRT fa fallire il mux con
# "only possible from text to text or bitmap to bitmap".
BITMAP_SUBTITLES = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


# Tetto di durata per una singola invocazione di ffmpeg. NON è una stima del
# tempo di lavoro: è il confine oltre il quale non sta più lavorando. Le
# operazioni più lunghe misurate stanno sotto i venti minuti; sei ore non
# scattano mai su un lavoro sano, ma impediscono a un disco esterno che si
# smonta di lasciare la lavorazione appesa fino al mattino dopo.
TETTO_SECONDI = 6 * 3600


def _run(cmd: list[str], log: Path | None,
         timeout: float | None = TETTO_SECONDI) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(
            cmd, -1,
            f"ffmpeg non risponde da {TETTO_SECONDI // 3600} ore: interrotto. "
            "Controlla che il disco sia ancora collegato, poi rilancia."
        ) from exc
    if log is not None:
        with log.open("a") as fh:
            fh.write(f"\n[cmd] {' '.join(cmd)}\n")
            if proc.stderr.strip():
                fh.write(proc.stderr[-4000:] + "\n")
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, proc.stderr)


def extract_frames(
    plan: Plan,
    dst: Path,
    *,
    on_progress: Callable[[int], None] | None = None,
    paths: Paths | None = None,
) -> int:
    """Estrae i fotogrammi del sorgente in PNG, in una sola passata sequenziale.

    Niente seek: su encode con molti reference frame il salto veloce produce
    fotogrammi ricostruiti per approssimazione. Si decodifica dall'inizio.
    """
    p = paths or PATHS
    dst.mkdir(parents=True, exist_ok=True)

    chain = plan.restoration.chain()
    cmd = [str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y", "-i", str(plan.source.path)]
    if chain:
        cmd += ["-vf", ",".join(chain)]
    cmd += [
        # Reticolo costante: i fotogrammi mancanti vengono ripetuti e quelli in
        # eccesso scartati, senza mai ricomprimere il sorgente. Gli stessi
        # argomenti li usa la misura per la deduplica, così le due passate
        # vedono lo stesso identico insieme di fotogrammi.
        *plan.timing_args(),
        "-an", "-sn", "-dn",
        # 8 bit e non 16: il modello lavora comunque a 8 bit al suo interno e
        # restituisce sempre 8 bit (verificato: uscite da ingressi a 8 e a 16
        # bit differiscono di 49.7 dB, cioè nulla). Estrarre a 16 bit
        # quadruplicherebbe il peso dei fotogrammi sorgente per niente.
        # La riduzione da 10 a 8 bit la facciamo qui con dithering, che è
        # meglio del troncamento secco fatto dal caricatore del modello.
        "-pix_fmt", "rgb24", "-sws_flags", "full_chroma_int+accurate_rnd",
        "-c:v", "png", "-pred", "mixed",
        str(dst / "%08d.png"),
    ]
    _run(cmd, plan.log)
    count = sum(1 for _ in dst.glob("*.png"))
    if on_progress:
        on_progress(count)
    return count


def materialise_duplicates(
    upscaled: Path, mapping: list[int], indices: list[int], dst: Path
) -> int:
    """Ricostruisce la sequenza completa a partire dai soli fotogrammi elaborati.

    I duplicati diventano hard link: costo su disco nullo e contenuto
    bit-identico all'originale elaborato.
    """
    dst.mkdir(parents=True, exist_ok=True)
    written = 0
    for position, frame_index in enumerate(indices, start=1):
        source = upscaled / f"{mapping[frame_index] + 1:08d}.png"
        target = dst / f"{position:08d}.png"
        # `lexists` e non `exists`: quest'ultimo segue il symlink e su un link
        # rotto dice "non c'e'", quindi non si cancellava niente, l'hardlink
        # falliva e il ripiego scriveva ATTRAVERSO il link, cioè fuori dalla
        # cartella di destinazione.
        if os.path.lexists(target):
            target.unlink()
        try:
            target.hardlink_to(source)
        except OSError:
            target.write_bytes(source.read_bytes())
        written += 1
    return written


def encode_segment(
    plan: Plan,
    frames: Path,
    out: Path,
    *,
    start_number: int = 1,
    paths: Paths | None = None,
) -> None:
    """Codifica una sequenza di PNG in un segmento video, senza audio."""
    p = paths or PATHS
    e = plan.encoding
    # `out_color_matrix` è obbligatorio. I PNG sono RGB e non portano nessun
    # tag; senza indicazione swscale converte SEMPRE in BT.601, mentre
    # l'etichetta scritta nel file dice quello che dice il sorgente. Il
    # risultato veniva convertito in 601 ed etichettato 709 — sbagliato
    # esattamente sui sorgenti HD, che sono la maggioranza. Misurato su barre
    # SMPTE a 1080p: scostamento medio su RGB 5.45 prima, 1.51 dopo.
    # `in_range=full` perché il PNG è a range pieno, `out_range=tv` perché
    # è quello che dichiara `range=limited` nei parametri di x265.
    #
    # `setparams` dopo, e serve: chiedendo a swscale una matrice esplicita, il
    # fotogramma esce marcato solo con quella e ffmpeg finisce per scrivere
    # `bt709,unknown,unknown`, perdendo primarie e curva. Riapporre i tre tag
    # sul fotogramma li fa arrivare tutti nel file. Provate quattro
    # combinazioni: solo x265-params (tag giusti, colore sbagliato 4.68); con
    # out_color_matrix (colore giusto 0.13, tag monchi); coi flag ffmpeg (tag
    # monchi lo stesso); con setparams (tag giusti E colore giusto).
    prim, trc, space = e.color_tags
    scale = (
        f"scale={plan.target_width}:{plan.target_height}:flags=lanczos"
        f":out_color_matrix={e.swscale_matrix}:in_range=full:out_range=tv"
        f",setsar=1"
        f",setparams=color_primaries={prim}:color_trc={trc}:colorspace={space}"
    )
    cmd = [
        str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y",
        "-framerate", str(plan.fps),
        "-start_number", str(start_number),
        "-i", str(frames / "%08d.png"),
        # Il downscale al bersaglio avviene qui, nella stessa passata della
        # codifica: nessuna generazione intermedia, una sola compressione.
        "-vf", scale,
        "-c:v", e.codec, "-pix_fmt", e.pix_fmt,
        "-preset", e.preset, "-x265-params", e.params,
        *e.color_args,
        "-an", "-sn",
        str(out),
    ]
    _run(cmd, plan.log)


def concat_and_mux(
    plan: Plan, segments: list[Path], work: Path, *, paths: Paths | None = None
) -> None:
    """Unisce i segmenti e vi rimonta audio, sottotitoli e capitoli."""
    p = paths or PATHS
    # Il demuxer concat cita i percorsi fra apici singoli: un apostrofo nel
    # nome (frequente in italiano, "La principessa d'argento") chiude la
    # citazione a metà e l'assemblaggio finale fallisce DOPO ore di upscale.
    # La convenzione di ffmpeg per l'apostrofo dentro gli apici è '\''.
    listing = work / "segments.txt"
    listing.write_text("".join(
        "file '{}'\n".format(s.as_posix().replace("'", r"'\''")) for s in segments
    ))

    # Si converte SOLO la traccia che non si può copiare, non tutte: una sola
    # mov_text in mezzo forzava la conversione anche delle ASS, distruggendone
    # posizionamento e stili. E i sottotitoli grafici non si convertono affatto
    # in testo: vanno copiati, altrimenti il mux fallisce a lavorazione finita.
    codec_per_traccia: list[str] = []
    for indice, codec in enumerate(plan.source.subtitle_codecs):
        if codec in BITMAP_SUBTITLES:
            codec_per_traccia += [f"-c:s:{indice}", "copy"]
        elif codec in UNCOPYABLE_SUBTITLES:
            codec_per_traccia += [f"-c:s:{indice}", "srt"]
        else:
            codec_per_traccia += [f"-c:s:{indice}", "copy"]

    plan.output.parent.mkdir(parents=True, exist_ok=True)
    # Si scrive su un nome PROVVISORIO e si rinomina solo a mux riuscito:
    # scrivendo direttamente sul nome buono, un'interruzione a metà
    # assemblaggio (Ferma, crash, spegnimento) lasciava in OUTPUT un file
    # troncato che il rilancio vedeva "già presente" e saltava PER SEMPRE.
    # La rinomina sullo stesso volume è atomica: o il file intero, o niente.
    # `-f matroska` esplicito: senza estensione .mkv ffmpeg non saprebbe
    # quale contenitore usare.
    provvisorio = plan.output.with_name(plan.output.name + ".inlavorazione")
    cmd = [
        str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-i", str(plan.source.path),
        "-map", "0:v:0", "-map", "1:a?", "-map", "1:s?", "-map", "1:t?",
        "-map_chapters", "1",
        "-c:v", "copy", "-c:a", "copy", *codec_per_traccia,
        # SENZA questo, con un sorgente che porta sottotitoli sparsi e font,
        # il muxer svuotava l'intera coda audio IN TESTA al file (misurato:
        # tutto l'audio nei primi 15 MB, il video dopo): i player leggono in
        # avanti, l'audio "finiva" subito e la traccia risultava muta, coi
        # sottotitoli invisibili — dati intatti, contenitore inguardabile
        # (successo, ep01). Con delta 0 il muxer attende un pacchetto per
        # OGNI traccia e intreccia rigorosamente per timestamp.
        "-max_interleave_delta", "0",
        "-f", "matroska", str(provvisorio),
    ]
    try:
        _run(cmd, plan.log)
    except BaseException:
        # Interrotti o falliti: il mezzo file non deve restare a ingombrare.
        provvisorio.unlink(missing_ok=True)
        raise
    os.replace(provvisorio, plan.output)


def verify_output(plan: Plan, expected_frames: int, *, paths: Paths | None = None) -> tuple[int, str]:
    """Controlla che il file finale abbia i fotogrammi e la geometria attesi."""
    p = paths or PATHS
    # I campi si leggono per NOME. Riconoscerli confrontandoli con i valori
    # attesi era circolare: se la geometria era sbagliata, la larghezza finiva
    # a fare da conteggio di fotogrammi e un file deforme passava la verifica.
    probe = subprocess.run(
        [
            str(p.ffprobe.path), "-v", "error", "-select_streams", "v:0",
            "-count_packets",
            "-show_entries", "stream=width,height,nb_read_packets",
            "-of", "default=nw=1:nk=0", str(plan.output),
        ],
        capture_output=True, text=True, check=False,
    ).stdout
    campi: dict[str, int] = {}
    for riga in probe.splitlines():
        chiave, _, valore = riga.partition("=")
        if valore.strip().isdigit():
            campi[chiave.strip()] = int(valore.strip())

    larghezza = campi.get("width", 0)
    altezza = campi.get("height", 0)
    fotogrammi = campi.get("nb_read_packets", 0)
    return fotogrammi, f"{larghezza or '?'}x{altezza or '?'}"


def audio_risponde_al_seek(plan: Plan, *, paths: Paths | None = None) -> bool:
    """Fa quello che farà il player: salta a metà file e prova a SENTIRE.

    Il conteggio dei pacchetti non basta: nel caso reale (ep01) i pacchetti
    c'erano tutti e si decodificavano pure, ma erano scritti tutti in testa
    al file — e qualunque player, che legge in avanti, restava muto. Il
    seek-e-decodifica è l'unico controllo che vede il file come lo vedrà
    chi lo guarda. True anche quando non c'è audio da controllare.
    """
    p = paths or PATHS
    if not getattr(plan.source, "audio_tracks", 0):
        return True
    meta = max(1.0, float(plan.source.duration) / 2)
    esito = subprocess.run(
        [str(p.ffmpeg.path), "-hide_banner", "-v", "info",
         "-ss", f"{meta:.3f}", "-t", "2", "-i", str(plan.output),
         "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False, timeout=120,
    )
    return "mean_volume" in esito.stderr


def fps_fraction(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"
