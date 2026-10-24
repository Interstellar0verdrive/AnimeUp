"""Resa a schermo dei referti di analisi."""

from __future__ import annotations

from fractions import Fraction

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .i18n import t, tn
from .models import CATALOG
from .probe import FieldMode, SourceReport, Timebase


# Funzioni e non costanti: le etichette vanno lette nella lingua attiva al
# momento di disegnare, non a quello dell'import.
def _timebase_style() -> dict:
    return {
        Timebase.CFR: ("verde", "green", "CFR"),
        Timebase.CFR_WITH_GAPS: ("giallo", "yellow", t("cli.rep.cfr_buchi")),
        Timebase.VFR: ("giallo", "yellow", "VFR"),
        Timebase.UNKNOWN: ("rosso", "red", t("cli.rep.non_determinato")),
    }


def _field_style() -> dict:
    return {
        FieldMode.PROGRESSIVE: ("green", t("cli.rep.progressivo")),
        FieldMode.INTERLACED: ("yellow", t("cli.rep.interlacciato")),
        FieldMode.TELECINE: ("yellow", t("cli.rep.telecine")),
        FieldMode.UNKNOWN: ("dim", t("cli.rep.non_determinato")),
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
        return t("cli.rep.domani")
    if salto == 2:
        return t("cli.rep.dopodomani")
    return t("cli.rep.del_giorno", data=quel.strftime(t("cli.rep.fmt_giorno")))


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
        return t("cli.rep.alle", ora=hh(massimo)) + (f" {g_max}" if g_max else "")
    primo = t("cli.rep.le", ora=hh(minimo)) + (f" {g_min}" if g_min and g_min != g_max else "")
    secondo = t("cli.rep.le", ora=hh(massimo)) + (f" {g_max}" if g_max else "")
    return t("cli.rep.fra", primo=primo, secondo=secondo)


def render_plan(plan, console: Console) -> None:
    """Mostra cosa verrebbe fatto, prima di farlo."""
    s = plan.source
    g = s.geometry

    tab = Table.grid(padding=(0, 2))
    tab.add_column(style="dim", justify="right")
    tab.add_column()

    src = f"{g.width}x{g.height}"
    tab.add_row(t("cli.rep.sorgente"), t("cli.rep.sorgente_valore", geometria=src,
                fps=f"{float(plan.fps):.3f}", frame=plan.frames))

    tab.add_row(t("cli.rep.modello"), Text(plan.model.label, style="bold"))
    rec = plan.recommendation
    if rec is not None:
        if rec.model == plan.model_key:
            # Nella fascia intermedia non è un consiglio, è un ripiego: va
            # detto, altrimenti passa per certezza quello che è un "dipende".
            testa = t("cli.rep.consigliato") if rec.sicuro else t("cli.rep.partenza")
            tab.add_row("", Text(f"{testa}: {rec.reason}",
                               style="dim" if rec.sicuro else "yellow"))
        else:
            # Anche qui `sicuro` conta: nella fascia intermedia non esiste un
            # consiglio da cui discostarsi, quindi rimproverare chi ha scelto a
            # mano — dopo che l'app stessa gli ha detto di provare entrambi —
            # non ha senso. Titolo e motivazione si contraddicevano nella
            # stessa riga.
            if rec.sicuro:
                tab.add_row("", Text(
                    t("cli.rep.scelto_consigliato",
                      modello=CATALOG[rec.model].label, motivo=rec.reason),
                    style="yellow",
                ))
            else:
                tab.add_row("", Text(t("cli.rep.scelto", motivo=rec.reason), style="dim"))

    tab.add_row(
        t("cli.rep.catena"),
        f"{plan.model_name}  ({plan.model_width}x{plan.model_height})"
        f"  ->  " + t("cli.rep.riduzione", rapporto=f"{plan.downscale:.2f}")
        + (f"  [{t('cli.rep.supersampling')}]" if abs(plan.downscale - 2.0) < 0.02 else ""),
    )
    tab.add_row(t("cli.rep.uscita"), Text(f"{plan.target_width}x{plan.target_height}", style="bold green"))

    if steps := plan.restoration.chain():
        tab.add_row(t("cli.rep.restauro"), " , ".join(steps))
    else:
        tab.add_row(t("cli.rep.restauro"), Text(t("cli.rep.restauro_nessuno"), style="dim"))

    d = plan.dedup
    if d.enabled:
        detail = t("cli.rep.dedup_attiva", motivo=d.reason)
        if d.expected_ratio:
            detail += t("cli.rep.dedup_da_elaborare", n=plan.frames_to_upscale)
        tab.add_row(t("cli.rep.dedup"), detail)
    else:
        tab.add_row(t("cli.rep.dedup"), Text(t("cli.rep.dedup_spenta"), style="dim"))

    e = plan.encoding
    tab.add_row(t("cli.rep.codifica"), f"{e.codec} {e.pix_fmt}  CRF {e.crf}  preset {e.preset}")
    tab.add_row("", Text(e.params, style="dim"))

    tab.add_row(
        t("cli.rep.esecuzione"),
        tn("cli.rep.esecuzione_valore", plan.chunks, frame=plan.chunk_size,
           picco=f"{plan.est_peak_disk_gb:.0f}"),
    )
    # Intervallo, non un numero: quanto si risparmia dipende dalla deduplica,
    # che si misura solo dopo l'estrazione. Un numero solo era sbagliato in un
    # verso o nell'altro qualunque valore si scegliesse.
    if plan.est_best_seconds < plan.est_total_seconds * 0.95:
        tempo = Text(f"{hms(plan.est_best_seconds)} - {hms(plan.est_total_seconds)}",
                     style="bold")
        tab.add_row(t("cli.rep.tempo"), tempo)
        tab.add_row("", Text(t("cli.rep.tempo_forchetta"), style="dim"))
    else:
        tab.add_row(t("cli.rep.tempo"), Text(hms(plan.est_total_seconds), style="bold"))
    # Text() e non una stringa: i nomi dei rilasci anime sono pieni di
    # parentesi quadre, che Rich interpreterebbe come marcatori di stile
    # facendo sparire pezzi di nome.
    tab.add_row(t("cli.rep.file_finale"), Text(plan.output.name))

    body: list = [tab]
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
    tempi = report.timing

    # --- identità del file ---
    ident = Table.grid(padding=(0, 2))
    ident.add_column(style="dim", justify="right")
    ident.add_column()
    ident.add_row(t("cli.rep.durata"), hms(report.duration))
    ident.add_row("Video", f"{report.video_codec} {report.pix_fmt} ({report.bit_depth} bit)")

    geom = f"{g.width}x{g.height}"
    if g.anamorphic:
        geom += t("cli.rep.anamorfico", sar=g.sar, larghezza=g.display_width,
                  altezza=g.display_height)
    ident.add_row(t("cli.rep.geometria"), geom)

    colour = report.color_space or t("cli.rep.colore_assenti")
    ident.add_row(t("cli.rep.tag_colore"), colour)
    ident.add_row(
        t("cli.rep.tracce"),
        t("cli.rep.tracce_valore", audio=report.audio_tracks,
          sottotitoli=report.subtitle_tracks)
        + (f" ({', '.join(report.subtitle_codecs)})" if report.subtitle_codecs else "")
        + t("cli.rep.capitoli", n=report.chapters),
    )

    # --- tempi ---
    timing = Table.grid(padding=(0, 2))
    timing.add_column(style="dim", justify="right")
    timing.add_column()

    _, colour_name, label = _timebase_style()[tempi.mode]
    timing.add_row(t("cli.rep.verdetto"), Text(label, style=f"bold {colour_name}"))
    timing.add_row(
        "Framerate",
        fps_str(tempi.fps) + ("" if tempi.fps_is_standard
                              else f"  [{t('cli.rep.non_standard')}]"),
    )
    timing.add_row(t("cli.rep.frame"), f"{tempi.packets}")
    timing.add_row(
        "Timebase",
        f"1/{tempi.time_base.denominator} s"
        + (tn("cli.rep.passo_tick", tempi.dominant_delta) if tempi.dominant_delta else ""),
    )
    timing.add_row(
        "Jitter",
        tn("cli.rep.tick", tempi.jitter_ticks)
        + (t("cli.rep.solo_quantizzazione") if tempi.quantization_only else ""),
    )
    if tempi.gaps:
        timing.add_row(t("cli.rep.buchi"), t("cli.rep.buchi_valore", buchi=tempi.gaps,
                                             mancanti=tempi.missing_frames))

    if tempi.container_r_fps is not None:
        style = "yellow" if tempi.container_disagrees else "dim"
        timing.add_row(
            t("cli.rep.container"),
            Text(
                f"r={fps_str(tempi.container_r_fps)}  avg={fps_str(tempi.container_avg_fps)}",
                style=style,
            ),
        )

    if report.fields:
        f = report.fields
        colour_name, label = _field_style()[f.mode]
        timing.add_row(
            t("cli.rep.campi"),
            Text(
                t("cli.rep.campi_valore", etichetta=label,
                  confidenza=f"{f.confidence:.0%}",
                  quota=f"{f.interlaced_ratio:.0%}", totale=f.total),
                style=colour_name,
            ),
        )

    if report.duplicates:
        d = report.duplicates
        step = d.animation_step
        desc = {1: t("cli.rep.in_uno"), 2: t("cli.rep.in_due"),
                3: t("cli.rep.in_tre")}.get(step or 0) or t("cli.rep.passo", n=step)
        timing.add_row(
            t("cli.rep.duplicati"),
            t("cli.rep.duplicati_valore", quota=f"{d.duplicate_ratio:.1%}",
              doppi=d.consecutive_duplicates, totale=d.total_frames, passo=desc),
        )

    body: list = [ident, Text(), Text(t("cli.rep.tempi"), style="bold dim"), timing]

    for note in tempi.notes:
        body.append(Text(f"  · {note}", style="dim"))

    warnings = report.warnings()
    if warnings:
        body.append(Text())
        body.append(Text(t("cli.rep.da_sapere"), style="bold yellow"))
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
