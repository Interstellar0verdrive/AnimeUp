"""Campioni sintetici per i test, al posto di quelli veri.

I campioni veri (`_WIP/_TESTING/`) sono rip di anime con tracce fansub: non si
possono pubblicare, quindi su un clone pulito e in CI non ci sono. Qui si
ricostruiscono con ffmpeg — sorgenti lavfi, audio sinusoidale, sottotitoli
.ass scritti al volo, font OFL presi da `tests/fonts/` — ripetendo SOLO le
proprieta' su cui i casi poggiano: codec, profilo, formato pixel, geometria e
SAR, timebase del contenitore, framerate misurato e quello DICHIARATO (due
campioni dichiarano 29.97 e sono 23.976 e 24), tag colore, tracce audio,
sottotitoli e allegati. Nessun byte dei file veri.

Le durate sono le piu' corte che i casi consentono: l'unica eccezione e' il
finto "7min", che deve restare abbastanza lungo perche' la dimensione dei
blocchi dipenda davvero dallo spazio concesso.

Si generano una volta in `tests/.fixtures/` e si riusano finche' questa
ricetta non cambia: l'impronta del file sta in `.ricetta`.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARTELLA = ROOT / "tests" / ".fixtures"
FONT = ROOT / "tests" / "fonts"

# L'animazione "in due": ogni disegno resta per due fotogrammi, come negli
# anime veri. Si genera a meta' ritmo e `fps` raddoppia i fotogrammi.
IN_DUE_23976 = "r=12000/1001,fps=24000/1001"
IN_DUE_24 = "r=12,fps=24"

# Esegue ffmpeg con gli argomenti dati (vedi `prepara`).
Esegui = Callable[[list[str]], None]


def _ass(lingua: str, fine: float, font: str = "Arial") -> str:
    """Un .ass minimo, con qualche battuta distribuita fino a `fine` secondi."""
    battute = {"eng": ("Test line", "Another line", "Last line"),
               "ita": ("Riga di prova", "Un'altra riga", "Ultima riga")}[lingua]
    passo = fine / len(battute)

    def tempo(s: float) -> str:
        return f"{int(s // 3600)}:{int(s // 60) % 60:02d}:{s % 60:05.2f}"

    eventi = "".join(
        f"Dialogue: 0,{tempo(i * passo + 0.5)},{tempo((i + 1) * passo)},"
        f"Default,,0,0,0,,{testo}\n"
        for i, testo in enumerate(battute))
    return (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 640\nPlayResY: 360\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},24,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,20,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n" + eventi)


def _sine(freq: int, durata: float, rate: int = 48000) -> list[str]:
    return ["-f", "lavfi", "-i",
            f"sine=frequency={freq}:sample_rate={rate}:duration={durata}"]


def _predefinite(*tipi: str) -> list[str]:
    """Prima traccia di ogni tipo marcata predefinita, come nei rip veri:
    il muxer Matroska di ffmpeg non ne marca nessuna."""
    return [x for tipo in tipi for x in (f"-disposition:{tipo}:0", "default")]


def _cfr_17s(ff: Esegui, dst: Path, tmp: Path) -> None:
    """HEVC Main 704x400 a 23.976, AAC stereo: Matroska al millisecondo."""
    durata = 4
    ff(["-f", "lavfi", "-i", f"mandelbrot=s=704x400:{IN_DUE_23976}",
        *_sine(440, durata), "-t", str(durata),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
        "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-c:a", "aac", "-ac", "2", "-b:a", "96k",
        *_predefinite("v", "a"), str(dst)])


def _cfr_23976_2min(ff: Esegui, dst: Path, tmp: Path) -> None:
    """H.264 High 710x480 anamorfico (SAR 480:527), AC-3, sottotitoli ASS.

    Il contenitore DICHIARA 29.97 (DefaultDuration) ma i timestamp sono a
    23.976: `-r` su una copia di flusso cambia la sola dichiarazione. E i
    sottotitoli durano oltre il video, come nel vero: il contenitore dichiara
    tre secondi in piu' di quanti ne abbia il video.
    """
    durata = 6
    video = tmp / "v.mkv"
    ff(["-f", "lavfi", "-i", f"testsrc2=s=710x480:{IN_DUE_23976}", "-t", str(durata),
        "-vf", "setsar=480/527:max=1000", "-c:v", "libx264", "-preset", "veryfast",
        "-profile:v", "high", "-pix_fmt", "yuv420p", str(video)])
    ass = tmp / "s.ass"
    ass.write_text(_ass("eng", durata + 3))
    ff(["-i", str(video), *_sine(330, durata), "-i", str(ass),
        "-map", "0:v", "-map", "1:a", "-map", "2:s",
        "-c:v", "copy", "-r:v", "30000/1001",
        "-c:a", "ac3", "-ac", "2", "-c:s", "ass",
        "-metadata:s:a:0", "language=jpn", "-metadata:s:s:0", "language=eng",
        *_predefinite("v", "a", "s"), str(dst)])


def _cfr_24_2min(ff: Esegui, dst: Path, tmp: Path) -> None:
    """H.264 High 640x480 a 24 tondi dichiarato 29.97, due Vorbis (jpn
    predefinita, eng), ASS e due font allegati. Nessun tag colore."""
    durata = 6
    video = tmp / "v.mkv"
    ff(["-f", "lavfi", "-i", f"testsrc2=s=640x480:{IN_DUE_24}", "-t", str(durata),
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
        "-pix_fmt", "yuv420p", str(video)])
    ass = tmp / "s.ass"
    ass.write_text(_ass("eng", durata, font="Inter"))
    ff(["-i", str(video), *_sine(440, durata), *_sine(660, durata), "-i", str(ass),
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s",
        "-c:v", "copy", "-r:v", "30000/1001",
        "-c:a", "libvorbis", "-ac", "2", "-q:a", "1", "-c:s", "ass",
        "-attach", str(FONT / "Inter_18pt-Regular.ttf"),
        "-attach", str(FONT / "JetBrainsMono-Regular.ttf"),
        "-metadata:s:t:0", "mimetype=application/x-truetype-font",
        "-metadata:s:t:1", "mimetype=application/x-truetype-font",
        "-metadata:s:v:0", "language=jpn",
        "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=eng",
        *_predefinite("v", "a", "s"), "-disposition:a:1", "0",
        "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=ass",
        str(dst)])


def _vfr_7min(ff: Esegui, dst: Path, tmp: Path) -> None:
    """MP4 a 23.976 su timebase 1/90000: il passo vero e' 3753,75 tick e
    l'arrotondamento lo fa oscillare fra 3753 e 3754 — "VFR approssimato"
    per chi guarda in secondi, CFR per l'analisi. Tag colore SD completi.

    Tre minuti e non sette: bastano perche' 8 e 100 GB diano blocchi diversi
    (oltre ~2400 fotogrammi il minimo di tre blocchi supera il pavimento di
    800), che e' l'unica cosa per cui un caso lo usa.
    """
    durata = 180
    ff(["-f", "lavfi", "-i", f"testsrc2=s=640x480:{IN_DUE_23976}",
        *_sine(440, durata, rate=44100), "-t", str(durata),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
        "-crf", "34", "-pix_fmt", "yuv420p",
        # `setparams` e non le opzioni -color_*: con un filtro davanti
        # l'encoder prende i tag dai fotogrammi e scriveva la sola matrice.
        "-vf", "setparams=range=tv:colorspace=smpte170m:"
               "color_primaries=smpte170m:color_trc=bt709",
        "-video_track_timescale", "90000",
        "-c:a", "aac", "-ac", "2", "-b:a", "64k", str(dst)])


def _clip20s(ff: Esegui, dst: Path, tmp: Path) -> None:
    """H.264 High 4:4:4 Predictive a 10 bit, 1280x720, sola matrice BT.709
    dichiarata (trasferimento e primarie no), Opus, ASS in italiano."""
    durata = 4
    ass = tmp / "s.ass"
    ass.write_text(_ass("ita", durata))
    ff(["-f", "lavfi", "-i", f"testsrc2=s=1280x720:{IN_DUE_23976}",
        *_sine(550, durata), "-i", str(ass), "-t", str(durata),
        "-map", "0:v", "-map", "1:a", "-map", "2:s",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv444p10le",
        "-colorspace", "bt709", "-color_range", "tv",
        "-c:a", "libopus", "-ac", "2", "-b:a", "96k", "-c:s", "ass",
        "-metadata:s:v:0", "language=jpn", "-metadata:s:a:0", "language=jpn",
        "-metadata:s:s:0", "language=ita", *_predefinite("v", "a", "s"),
        str(dst)])


# Nome -> ricetta. I nomi sono quelli dei campioni veri: i casi li citano.
RICETTE = {
    "TEST-CFR-23-976fps---17s.mkv": _cfr_17s,
    "TEST-CFR-23-976fps---2min.mkv": _cfr_23976_2min,
    "TEST-CFR-24fps---2min.mkv": _cfr_24_2min,
    "TEST-VFR-approx-23-976fps---7min.mp4": _vfr_7min,
    "clip20s.mkv": _clip20s,
}


def _impronta() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def prepara(ffmpeg: str) -> Path:
    """Genera i campioni che mancano e torna la cartella che li contiene.

    Una ricetta cambiata invalida tutto: un campione vecchio con le
    proprieta' sbagliate farebbe fallire (o passare) i casi per il motivo
    sbagliato.
    """
    stampo = CARTELLA / ".ricetta"
    if CARTELLA.is_dir() and (not stampo.is_file()
                              or stampo.read_text().strip() != _impronta()):
        shutil.rmtree(CARTELLA)
    CARTELLA.mkdir(parents=True, exist_ok=True)

    def ff(args: list[str]) -> None:
        subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y",
                        *args], check=True, capture_output=True, timeout=600)

    for nome, ricetta in RICETTE.items():
        dst = CARTELLA / nome
        if dst.is_file():
            continue
        # Prima in una cartella d'appoggio e poi al suo posto: un'interruzione
        # a meta' non lascia un campione troncato che verrebbe riusato.
        appoggio = CARTELLA / f".in-corso-{nome}"
        shutil.rmtree(appoggio, ignore_errors=True)
        appoggio.mkdir()
        try:
            ricetta(ff, appoggio / nome, appoggio)
            (appoggio / nome).replace(dst)
        finally:
            shutil.rmtree(appoggio, ignore_errors=True)
    stampo.write_text(_impronta() + "\n")
    return CARTELLA
