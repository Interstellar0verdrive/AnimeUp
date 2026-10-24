"""Resa a schermo dei referti di analisi."""

from __future__ import annotations

from fractions import Fraction

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import CATALOG
from .probe import FieldMode, SourceReport, Timebase


_TIMEBASE_STYLE = {
    Timebase.CFR: ("verde", "green", "CFR"),
    Timebase.CFR_WITH_GAPS: ("giallo", "yellow", "CFR con frame mancanti"),
    Timebase.VFR: ("giallo", "yellow", "VFR"),
    Timebase.UNKNOWN: ("rosso", "red", "non determinato"),
}

_FIELD_STYLE = {
    FieldMode.PROGRESSIVE: ("green", "progressivo"),
    FieldMode.INTERLACED: ("yellow", "interlacciato"),
    FieldMode.TELECINE: ("yellow", "telecine 3:2"),
    FieldMode.UNKNOWN: ("dim", "non determinato"),
}


def fps_str(fps: Fraction | None) -> str:
    if fps is None:
        return "?"
    if fps.denominator == 1:
        return str(fps.numerator)
    return f"{float(fps):.3f} ({fps.numerator}/{fps.denominator})"


def hms(seconds: float) -> str:
    s = int(seconds + 0.5)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def stima_hm(seconds: float) -> str:
    """Durata per le STIME: "02h 30m", o "45m" sotto l'ora.

    Niente secondi: una stima che dice 05:06:52 promette una precisione che
    non ha, e il formato a due punti costringe a contare i gruppi di cifre
    per capire se sono ore o minuti (detto dall'utente, e aveva ragione).
    """
    minuti = max(1, round(seconds / 60))
    ore, m = divmod(minuti, 60)
    return f"{ore:02d}h {m:02d}m" if ore else f"{m}m"


def _giorno_di(istante: float, adesso: float) -> str:
    """Come si nomina il giorno di `istante` visto da `adesso`.

    Vuoto se è oggi: un orario senza altro si intende oggi, e aggiungerlo
    sarebbe rumore.
    """
    import datetime as _dt
    oggi = _dt.datetime.fromtimestamp(adesso).date()
    quel = _dt.datetime.fromtimestamp(istante).date()
    salto = (quel - oggi).days
    if salto <= 0:
        return ""
    if salto == 1:
        return "di domani"
    if salto == 2:
        return "di dopodomani"
    return f"del {quel.strftime('%d/%m')}"


def quando_finisce(minimo: float, massimo: float,
                   adesso: float | None = None) -> str:
    """L'orario di fine, col GIORNO quando non è oggi.

    «fra le 23:48 e le 02:43» non dice niente a chi legge di sera: le 02:43
    sono di domani, ma la riga non lo dichiara e il lettore deve dedurlo
    dall'ordine dei numeri. Su una coda che dura giorni — quattro episodi da
    dieci ore l'uno arrivano a dopodomani — diventa proprio indecifrabile
    (segnalato dall'utente su entrambe le macchine).

    Regola: il giorno si scrive sull'ultimo estremo se non è oggi, e anche
    sul primo se i due cadono in giorni diversi. Cosí «fra le 23:48 e le
    02:43 di domani» resta corto quando basta, e diventa «fra le 23:48 di
    domani e le 02:43 di dopodomani» quando serve davvero.

    `minimo` e `massimo` sono istanti assoluti, non durate.
    """
    import time as _t
    ora = adesso if adesso is not None else _t.time()
    hh = lambda x: _t.strftime("%H:%M", _t.localtime(x))          # noqa: E731
    g_min, g_max = _giorno_di(minimo, ora), _giorno_di(massimo, ora)
    if minimo >= massimo:
        return f"alle {hh(massimo)}{' ' + g_max if g_max else ''}"
    primo = f"le {hh(minimo)}" + (f" {g_min}" if g_min and g_min != g_max else "")
    secondo = f"le {hh(massimo)}" + (f" {g_max}" if g_max else "")
    return f"fra {primo} e {secondo}"


def render_plan(plan, console: Console) -> None:
    """Mostra cosa verrebbe fatto, prima di farlo."""
    s = plan.source
    g = s.geometry

    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", justify="right")
    t.add_column()

    src = f"{g.width}x{g.height}"
    t.add_row("Sorgente", f"{src}  {float(plan.fps):.3f} fps  {plan.frames} frame")

    t.add_row("Modello", Text(plan.model.label, style="bold"))
    rec = plan.recommendation
    if rec is not None:
        if rec.model == plan.model_key:
            # Nella fascia intermedia non è un consiglio, è un ripiego: va
            # detto, altrimenti passa per certezza quello che è un "dipende".
            testa = "consigliato" if rec.sicuro else "scelta di partenza"
            t.add_row("", Text(f"{testa}: {rec.reason}",
                               style="dim" if rec.sicuro else "yellow"))
        else:
            # Anche qui `sicuro` conta: nella fascia intermedia non esiste un
            # consiglio da cui discostarsi, quindi rimproverare chi ha scelto a
            # mano — dopo che l'app stessa gli ha detto di provare entrambi —
            # non ha senso. Titolo e motivazione si contraddicevano nella
            # stessa riga.
            if rec.sicuro:
                t.add_row("", Text(
                    f"scelto a mano. Per questo sorgente sarebbe consigliato "
                    f"{CATALOG[rec.model].label}: {rec.reason}",
                    style="yellow",
                ))
            else:
                t.add_row("", Text(f"scelto a mano. {rec.reason}", style="dim"))

    t.add_row(
        "Catena",
        f"{plan.model_name}  ({plan.model_width}x{plan.model_height})"
        f"  ->  riduzione {plan.downscale:.2f}:1"
        + ("  [supersampling esatto]" if abs(plan.downscale - 2.0) < 0.02 else ""),
    )
    t.add_row("Uscita", Text(f"{plan.target_width}x{plan.target_height}", style="bold green"))

    if steps := plan.restoration.chain():
        t.add_row("Restauro", " , ".join(steps))
    else:
        t.add_row("Restauro", Text("nessuno (sorgente pulito)", style="dim"))

    d = plan.dedup
    if d.enabled:
        detail = f"attiva - {d.reason}"
        if d.expected_ratio:
            detail += f"  (~{plan.frames_to_upscale} frame da elaborare)"
        t.add_row("Deduplica", detail)
    else:
        t.add_row("Deduplica", Text("disattivata", style="dim"))

    e = plan.encoding
    t.add_row("Codifica", f"{e.codec} {e.pix_fmt}  CRF {e.crf}  preset {e.preset}")
    t.add_row("", Text(e.params, style="dim"))

    t.add_row(
        "Esecuzione",
        f"{plan.chunks} blocchi da {plan.chunk_size} frame"
        f"  -  picco su disco ~{plan.est_peak_disk_gb:.0f} GB",
    )
    # Intervallo, non un numero: quanto si risparmia dipende dalla deduplica,
    # che si misura solo dopo l'estrazione. Un numero solo era sbagliato in un
    # verso o nell'altro qualunque valore si scegliesse.
    if plan.est_best_seconds < plan.est_total_seconds * 0.95:
        tempo = Text(f"{hms(plan.est_best_seconds)} - {hms(plan.est_total_seconds)}",
                     style="bold")
        t.add_row("Tempo stimato", tempo)
        t.add_row("", Text("il minimo se la deduplica trova i fotogrammi ripetuti "
                           "che l'animazione di solito ha, il massimo se non ne "
                           "trova nessuno", style="dim"))
    else:
        t.add_row("Tempo stimato", Text(hms(plan.est_total_seconds), style="bold"))
    # Text() e non una stringa: i nomi dei rilasci anime sono pieni di
    # parentesi quadre, che Rich interpreterebbe come marcatori di stile
    # facendo sparire pezzi di nome.
    t.add_row("File finale", Text(plan.output.name))

    body: list = [t]
    for note in plan.restoration.notes:
        body.append(Text(f"  · {note}", style="dim"))
    if plan.warnings:
        body.append(Text())
        for w in plan.warnings:
            body.append(Text(f"  ! {w}", style="yellow"))

    console.print(
        Panel(
            Group(*body),
            title=Text(s.path.name, style="bold"),
            border_style="magenta",
            padding=(1, 2),
        )
    )


def render_source(report: SourceReport, console: Console) -> None:
    """Stampa il referto completo di un sorgente."""
    g = report.geometry
    t = report.timing

    # --- identità del file ---
    ident = Table.grid(padding=(0, 2))
    ident.add_column(style="dim", justify="right")
    ident.add_column()
    ident.add_row("Durata", hms(report.duration))
    ident.add_row("Video", f"{report.video_codec} {report.pix_fmt} ({report.bit_depth} bit)")

    geom = f"{g.width}x{g.height}"
    if g.anamorphic:
        geom += f"  SAR {g.sar}  ->  {g.display_width}x{g.display_height} a pixel quadri"
    ident.add_row("Geometria", geom)

    colour = report.color_space or "assenti"
    ident.add_row("Tag colore", colour)
    ident.add_row(
        "Tracce",
        f"{report.audio_tracks} audio, {report.subtitle_tracks} sottotitoli"
        + (f" ({', '.join(report.subtitle_codecs)})" if report.subtitle_codecs else "")
        + f", {report.chapters} capitoli",
    )

    # --- tempi ---
    timing = Table.grid(padding=(0, 2))
    timing.add_column(style="dim", justify="right")
    timing.add_column()

    _, colour_name, label = _TIMEBASE_STYLE[t.mode]
    timing.add_row("Verdetto", Text(label, style=f"bold {colour_name}"))
    timing.add_row(
        "Framerate",
        fps_str(t.fps) + ("" if t.fps_is_standard else "  [non standard]"),
    )
    timing.add_row("Frame", f"{t.packets}")
    timing.add_row(
        "Timebase",
        f"1/{t.time_base.denominator} s"
        + (f"  passo {t.dominant_delta} tick" if t.dominant_delta else ""),
    )
    timing.add_row(
        "Jitter",
        f"{t.jitter_ticks} tick"
        + ("  (solo quantizzazione del container)" if t.quantization_only else ""),
    )
    if t.gaps:
        timing.add_row("Buchi", f"{t.gaps} ({t.missing_frames} frame mancanti)")

    if t.container_r_fps is not None:
        style = "yellow" if t.container_disagrees else "dim"
        timing.add_row(
            "Container dichiara",
            Text(
                f"r={fps_str(t.container_r_fps)}  avg={fps_str(t.container_avg_fps)}",
                style=style,
            ),
        )

    if report.fields:
        f = report.fields
        colour_name, label = _FIELD_STYLE[f.mode]
        timing.add_row(
            "Campi",
            Text(
                f"{label}  (confidenza {f.confidence:.0%}, "
                f"{f.interlaced_ratio:.0%} frame interlacciati su {f.total} campionati)",
                style=colour_name,
            ),
        )

    if report.duplicates:
        d = report.duplicates
        step = d.animation_step
        desc = {1: "in uno", 2: "in due", 3: "in tre"}.get(step or 0, f"passo {step}")
        timing.add_row(
            "Duplicati",
            f"{d.duplicate_ratio:.1%} dei frame ({d.consecutive_duplicates} su {d.total_frames})"
            f"  - animazione prevalentemente {desc}",
        )

    body: list = [ident, Text(), Text("TEMPI", style="bold dim"), timing]

    for note in t.notes:
        body.append(Text(f"  · {note}", style="dim"))

    warnings = report.warnings()
    if warnings:
        body.append(Text())
        body.append(Text("DA SAPERE", style="bold yellow"))
        for w in warnings:
            body.append(Text(f"  ! {w}", style="yellow"))

    console.print(
        Panel(
            Group(*body),
            title=Text(report.path.name, style="bold"),
            border_style="cyan",
            padding=(1, 2),
        )
    )
