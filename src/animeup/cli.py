"""Interfaccia a riga di comando."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import json
import os
import signal
import subprocess
import sys

import typer
from rich.console import Console
from rich.text import Text
from rich.table import Table

from . import __version__, su_disco
from .ffmpeg import FFmpegError
from .i18n import t, tn
from .paths import PATHS, MissingToolError
from .probe import probe_source
from .report import render_source

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    # Gli aiuti di Typer si leggono all'import: per la CLI va bene, ogni
    # comando e' un processo nuovo che parte gia' nella lingua salvata.
    help=t("cli.app.aiuto"),
    rich_markup_mode="rich",
)
console = Console()


def dire(testo: str, stile: str = "") -> None:
    """Stampa una riga senza interpretare markup nel testo.

    I nomi dei rilasci anime sono pieni di parentesi quadre, e Rich le legge
    come marcatori di stile: `Serie [ita][sub]` diventava `Serie`, e un nome
    contenente `[/hd]` alzava MarkupError abortendo l'intero batch.
    """
    console.print(Text(testo, style=stile) if stile else Text(testo))


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".webm"}


def _collect(targets: list[Path] | None) -> list[Path]:
    """Espande i percorsi indicati; senza argomenti usa la cartella INPUT."""
    if not targets:
        targets = [PATHS.input]

    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files.extend(
                p for p in sorted(target.iterdir())
                if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
            )
        elif target.is_file():
            files.append(target)
        else:
            dire(t("cli.ignorato", percorso=target), "yellow")

    # Su APFS il filesystem è case-insensitive: due percorsi diversi possono
    # puntare allo stesso file. Si deduplica sul percorso risolto.
    seen: dict[Path, Path] = {}
    for f in files:
        seen.setdefault(f.resolve(), f)
    return list(seen.values())


@app.command(help=t("cli.analyze.aiuto"))
def analyze(
    targets: Annotated[
        list[Path] | None,
        typer.Argument(help=t("cli.analyze.targets")),
    ] = None,
    duplicates: Annotated[
        bool,
        typer.Option("--duplicati/--no-duplicati",
                     help=t("cli.analyze.duplicati")),
    ] = False,
    quick: Annotated[
        bool,
        typer.Option("--veloce", help=t("cli.analyze.veloce")),
    ] = False,
) -> None:
    """Analizza i sorgenti e mostra il referto, senza modificare nulla."""
    files = _collect(targets)
    if not files:
        console.print(f"[yellow]{t('cli.nessun_video')}[/yellow]")
        raise typer.Exit(0)

    for path in files:
        try:
            with console.status(t("cli.analisi_in_corso")):
                report = probe_source(
                    path,
                    with_fields=not quick,
                    with_geometry=not quick,
                    with_duplicates=duplicates,
                )
        except (OSError, FFmpegError, ValueError) as exc:
            dire(t("cli.non_analizzabile", nome=path.name, errore=exc), "red")
            continue
        render_source(report, console)


@app.command(name="plan", help=t("cli.plan.aiuto"))
def plan_cmd(
    targets: Annotated[
        list[Path] | None,
        typer.Argument(help=t("cli.opz.targets")),
    ] = None,
    altezza: Annotated[
        int, typer.Option("--altezza", help=t("cli.opz.altezza"))
    ] = 1080,
    crf: Annotated[int, typer.Option("--crf", help=t("cli.opz.crf"))] = 18,
    scala: Annotated[
        int | None,
        typer.Option("--scala", help=t("cli.opz.scala")),
    ] = None,
    denoise: Annotated[
        bool, typer.Option("--denoise/--no-denoise", help=t("cli.opz.denoise"))
    ] = False,
    dedup: Annotated[
        bool, typer.Option("--dedup/--no-dedup", help=t("cli.opz.dedup"))
    ] = True,
    forza: Annotated[bool, typer.Option("--forza",
        help=t("cli.opz.forza"))] = False,
    # `plan` è l'unico comando di sola lettura: senza queste due non poteva
    # riprodurre ciò che `run` avrebbe fatto, e mostrava blocchi, picco su
    # disco e riga di codifica diversi da quelli veri.
    preset: Annotated[str, typer.Option("--preset",
        help=t("cli.opz.preset"))] = "slower",
    disco: Annotated[float, typer.Option("--disco",
        help=t("cli.opz.disco"))] = 40.0,
    modello: Annotated[
        str | None,
        typer.Option("--modello", "-m",
                     help=t("cli.opz.modello")),
    ] = None,
) -> None:
    """Mostra cosa verrebbe fatto su ogni file, senza eseguire nulla."""
    from .plan import PlanError, build_plan
    from .report import render_plan

    files = _collect(targets)
    if not files:
        console.print(f"[yellow]{t('cli.nessun_video')}[/yellow]")
        raise typer.Exit(0)

    total = minimo = 0.0
    for path in files:
        try:
            with console.status(t("cli.analisi_in_corso")):
                report = probe_source(path, with_duplicates=False)
            plan = build_plan(
                report, target_height=altezza, crf=crf,
                denoise=denoise, dedup=dedup, forza=forza,
                preset=preset, peak_disk_gb=disco,
                scale_override=scala, model_key=modello,
                dedup_nota=_dedup_gia_misurata(path),
            )
        except (PlanError, OSError, FFmpegError, ValueError) as exc:
            dire(t("cli.non_elaborabile", nome=path.name, errore=exc), "red")
            continue
        render_plan(plan, console)
        total += plan.est_total_seconds
        minimo += plan.est_best_seconds

    if len(files) > 1:
        from .report import hms
        # Anche il totale è un intervallo: sommare i soli massimi dava un
        # numero due volte e mezzo il minimo, presentato come "il" tempo.
        quanto = (f"{hms(minimo)} - {hms(total)}" if minimo < total * 0.95
                  else hms(total))
        console.print("\n[bold]" + t("cli.plan.totale", n=len(files), quanto=quanto)
                      + "[/bold]")


@app.command(name="run", help=t("cli.run.aiuto"))
def run_cmd(
    targets: Annotated[
        list[Path] | None,
        typer.Argument(help=t("cli.opz.targets")),
    ] = None,
    altezza: Annotated[int, typer.Option("--altezza",
        help=t("cli.opz.altezza"))] = 1080,
    crf: Annotated[int, typer.Option("--crf",
        help=t("cli.opz.crf"))] = 18,
    forza: Annotated[bool, typer.Option("--forza",
        help=t("cli.opz.forza"))] = False,
    disco: Annotated[float, typer.Option("--disco",
        help=t("cli.opz.disco"))] = 40.0,
    preset: Annotated[str, typer.Option("--preset",
        help=t("cli.opz.preset"))] = "slower",
    scala: Annotated[int | None, typer.Option("--scala",
        help=t("cli.opz.scala"))] = None,
    denoise: Annotated[bool, typer.Option("--denoise/--no-denoise",
        help=t("cli.opz.denoise"))] = False,
    dedup: Annotated[bool, typer.Option("--dedup/--no-dedup",
        help=t("cli.opz.dedup"))] = True,
    conferma: Annotated[
        bool, typer.Option("--si", help=t("cli.run.si"))
    ] = False,
    tieni_temp: Annotated[
        bool, typer.Option("--tieni-temp", help=t("cli.run.tieni_temp"))
    ] = False,
    modello: Annotated[
        str | None,
        typer.Option("--modello", "-m",
                     help=t("cli.opz.modello")),
    ] = None,
    pausa: Annotated[int, typer.Option("--pausa",
        help=t("cli.run.pausa"))] = 0,
    pausa_prima: Annotated[bool, typer.Option("--pausa-prima",
        help=t("cli.run.pausa_prima"))] = False,
    catena_totale: Annotated[int, typer.Option("--catena-totale",
        help=t("cli.run.catena_totale"))] = 0,
    catena_inizio: Annotated[int, typer.Option("--catena-inizio",
        help=t("cli.run.catena_inizio"))] = 0,
    lancio: Annotated[str, typer.Option("--lancio",
        help=t("cli.run.lancio"))] = "",
) -> None:
    """Esegue la lavorazione completa."""
    from . import taratura as taratura_
    from .processi import tieni_sveglio
    # La pagina non avvia durante una taratura, ma un gruppo successivo di
    # una catena partita prima sì: si dividerebbero la GPU e la taratura
    # salverebbe numeri falsi.
    if taratura_.in_corso():
        dire(t("lav.avvia_taratura"), "yellow")
        raise typer.Exit(1)
    tieni_sveglio()
    from rich.progress import BarColumn, Progress as RichProgress, TextColumn, TimeRemainingColumn

    from .plan import PlanError, build_plan
    from .pipeline import Job, Progress
    from .report import hms, render_plan

    files = _collect(targets)
    if not files:
        console.print(f"[yellow]{t('cli.nessun_video')}[/yellow]")
        raise typer.Exit(0)

    plans = []
    scartati: list[str] = []
    for path in files:
        try:
            with console.status(t("cli.analisi_in_corso")):
                report = probe_source(path, with_duplicates=False)
            plans.append(build_plan(
                report, target_height=altezza, crf=crf, preset=preset,
                denoise=denoise, dedup=dedup, forza=forza,
                scale_override=scala, peak_disk_gb=disco, model_key=modello,
                dedup_nota=_dedup_gia_misurata(path),
            ))
        except (PlanError, OSError, FFmpegError, ValueError) as exc:
            dire(t("cli.non_elaborabile", nome=path.name, errore=exc), "red")
            scartati.append(path.name)

    # L'identita' del lancio, prima di qualunque uscita anticipata: anche i
    # rami che escono subito devono poter scrivere un record che appartenga
    # a QUESTO lancio. Dedurla da "quanti file mancano" era fragile — una
    # coda fermata a meta' non arrivava mai al totale dichiarato e il suo
    # resoconto spariva per sempre, cioe' il caso piu' frequente di tutti,
    # il Ferma tutto (audit del 2026-08-10, quinto giro).
    import time as _t
    inizio_lancio = _t.time()
    etichetta = lancio or f"{os.getpid()}-{int(inizio_lancio)}"

    if not plans:
        # Nessun file pianificabile: la coda finisce qui, e va detto. Senza
        # questo record il lancio moriva in silenzio e all'interfaccia non
        # arrivava mai la notizia che gli scarti c'erano (caso raggiungibile:
        # un file rimosso o rovinato fra l'analisi e l'avvio).
        _scrivi_lancio(inizio=inizio_lancio, fine=_t.time(),
                       previsti=scartati, riusciti=[], falliti=[],
                       scartati=scartati, interrotti=[], secondi=0.0,
                       pausa_minuti=pausa, avvisi=0, dedup=[],
                       catena_inizio=catena_inizio,
                       catena_totale=catena_totale, numero_finale=0,
                       lancio=etichetta)
        raise typer.Exit(1)

    for plan in plans:
        render_plan(plan, console)
    # `--pausa-prima` finge un file già lavorato: così anche il primo della
    # catena riposa, che è ciò che serve al secondo gruppo di un lancio.
    gia_lavorato = pausa_prima
    # `uscita_esiste` e non `output.exists()`: riconosce anche il nome
    # che il file aveva prima della distinzione upscale/supersampling.
    da_fare = [p for p in plans if not p.uscita_esiste]
    # Le pause fra un file e l'altro sono tempo che passa davvero, e il
    # totale a schermo le ignorava: con dieci file e cinque minuti di
    # respiro sono quarantacinque minuti che il marcatore di catena contava
    # e questa riga no — due numeri diversi per la stessa coda (audit del
    # 2026-08-10). Una pausa PRIMA di ogni file tranne il primo, più quella
    # iniziale se richiesta.
    # Ore e pause si contano sulla STESSA popolazione: i file che partiranno
    # davvero. Contando le ore su `plans` e le pause su `da_fare` il totale
    # prometteva il tempo anche dei già presenti — che il ciclo salta con
    # "Già presente, saltato" — e il marcatore di catena dava un terzo
    # numero ancora diverso. (Con tutte le uscite già presenti `da_fare` è
    # vuoto: nessuna pausa, nemmeno quella iniziale, che non scatterebbe.)
    respiro = ((max(0, len(da_fare) - 1) + (1 if pausa_prima else 0))
               * pausa * 60) if da_fare else 0
    total = sum(p.est_total_seconds for p in da_fare) + respiro
    minimo = sum(p.est_best_seconds for p in da_fare) + respiro
    quanto = f"{hms(minimo)} - {hms(total)}" if minimo < total * 0.95 else hms(total)
    riposo = (t("cli.run.di_cui_pause", pause=hms(respiro))
              if respiro else "")
    saltati = len(plans) - len(da_fare)
    nota_saltati = (f" ({tn('cli.run.saltati', saltati)})" if saltati else "")
    if not da_fare:
        # Chiedere "Procedo?" per un ciclo che non lavorerà nessun file, e
        # annunciare "0 file, tempo stimato 0s", è un giro a vuoto travestito
        # da lavoro.
        console.print("\n[bold]" + tn("cli.run.niente_da_fare", len(plans),
                                       cartella=PATHS.output.name)
                      + "[/bold]\n")
        # Anche questo e' un pezzo del lancio: senza il suo record, in una
        # maratona spezzata per modello il gruppo spariva e il resoconto
        # complessivo restava monco.
        _scrivi_lancio(inizio=inizio_lancio, fine=_t.time(),
                       previsti=[p.source.path.name for p in plans],
                       riusciti=[], falliti=[], scartati=scartati,
                       interrotti=[], secondi=0.0, pausa_minuti=pausa,
                       avvisi=0, dedup=[], catena_inizio=catena_inizio,
                       catena_totale=catena_totale, numero_finale=0,
                       lancio=etichetta,
                       presenti=[p.source.path.name for p in plans])
        raise typer.Exit(0)
    console.print("\n[bold]" + tn("cli.run.annuncio", len(da_fare), quanto=quanto)
                  + f"{riposo}{nota_saltati}[/bold]\n")

    if not conferma:
        # Si accettano le risposte in tutte e due le lingue, qualunque sia
        # quella della domanda.
        if input(t("cli.run.procedo") + " ").strip().lower() not in (
                "s", "si", "sì", "y", "yes"):
            console.print(t("cli.run.annullato"))
            raise typer.Exit(0)

    falliti: list[str] = []
    # Il diario del lancio: serve all'interfaccia per dire com'e' andata a
    # coda finita. Deve nascere QUI e non da lei, perche' quando la coda
    # finisce il marcatore .catena sparisce e con lui ogni traccia — e
    # perche' cosi' il resoconto c'e' anche se AnimeUp era chiuso.
    riusciti: list[str] = []
    in_volo: str | None = None
    # I file fermati col "Ferma" per-file: non sono riusciti e non sono
    # falliti, ma sparivano da ogni conto — e la modale festeggiava una coda
    # in cui un file era stato interrotto a mano.
    interrotti: list[str] = []
    secondi_lavorati = 0.0
    avvisi_totali = 0
    dedup_visti: list[float] = []
    totale_catena = catena_totale or len(da_fare)
    numero = catena_inizio
    try:
        for indice, plan in enumerate(plans):
            if plan.uscita_esiste:
                dire(t("cli.run.gia_presente", nome=plan.output.name), "dim")
                continue

            # Il marcatore di catena si scrive PRIMA della pausa: così
            # durante il riposo l'interfaccia sa già dire quale file è
            # il prossimo, e quanti ne restano.
            numero += 1
            _scrivi_catena(numero, totale_catena, plan,
                           [p for p in plans[indice:] if not p.uscita_esiste],
                           programma=plans, pausa_minuti=pausa,
                           # La pausa di QUESTO file non è ancora stata
                           # fatta: il marcatore si scrive prima (due righe
                           # più giù). Senza dirlo, il residuo nasceva già
                           # corto di una pausa intera.
                           pausa_pendente=gia_lavorato)

            # La pausa sta QUI, prima del file successivo e non dopo il
            # precedente: così non si riposa mai dopo l'ultimo, e i file
            # saltati perché già presenti non fanno scattare pause a vuoto.
            if gia_lavorato and pausa > 0:
                _pausa_respiro(pausa)
            gia_lavorato = True

            console.print(Text(f"\n{plan.source.path.name}", style="bold cyan"))
            job = Job(plan)
            # La ricetta per il "Riprendi blindato" dell'interfaccia: i
            # parametri VERI di questo lancio, nella cartella di lavorazione.
            # Il pulsante Riprendi usa QUESTI, ignorando la sidebar del
            # momento: riprendere non puo' mai buttare il lavoro fatto.
            # A file concluso la cartella sparisce, e la ricetta con lei.
            # Si scrive solo a lucchetto preso (vedi Job.ricetta): un secondo
            # lancio sullo stesso file, rifiutato, la sovrascriveva comunque.
            job.ricetta = {
                "altezza": altezza, "crf": crf, "preset": preset,
                "disco": int(disco), "dedup": dedup,
                "denoise": denoise, "forza": forza,
                "modello": plan.model_key,
                # Il totale dei fotogrammi: durante l'estrazione
                # state.json non esiste ancora e il monitor non avrebbe
                # altro modo di dire "5632 su quanti?".
                "fotogrammi": int(plan.frames or 0),
                **({"scala": scala} if scala else {}),
            }
            with RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(), TextColumn("{task.completed}/{task.total}"),
                TimeRemainingColumn(), console=console,
            ) as bar:
                task = bar.add_task(t("cli.preparazione"), total=plan.frames)
                _partito = _t.monotonic()
                # Se il comando muore qui — SIGTERM del "Ferma tutto" — non
                # si passa da nessun `append`, e quel file spariva da ogni
                # lista: il resoconto diceva "2 su 3" senza dire quale
                # mancasse. Il `finally` lo recupera.
                in_volo = plan.source.path.name
                progress = Progress(
                    stage=lambda name, detail: bar.update(task, description=f"{name}: {detail}"[:70]),
                    chunk=lambda i, n, done, tot: bar.update(task, completed=done, total=tot),
                )
                try:
                    _FILE_IN_CORSO[0] = True
                    try:
                        result = job.run(progress)
                    finally:
                        _FILE_IN_CORSO[0] = False
                except _SaltaFile:
                    # Il "Ferma" per-file dell'interfaccia: SIGUSR1. Questo
                    # file si interrompe (riprendibile: il lucchetto è già
                    # stato rilasciato dal finally di Job.run), i successivi
                    # proseguono.
                    dire(t("cli.run.interrotto", cartella=job.work.name),
                         "yellow")
                    interrotti.append(plan.source.path.name)
                    in_volo = None
                    secondi_lavorati += max(0.0, _t.monotonic() - _partito)
                    continue
                except Exception as exc:  # noqa: BLE001 - si riporta e si prosegue
                    dire(t("cli.run.fallito", errore=exc), "red")
                    dire(t("cli.run.parziale", cartella=job.work), "dim")
                    falliti.append(plan.source.path.name)
                    in_volo = None
                    # Anche il lavoro BRUCIATO e' lavoro: senza, tre ore di
                    # GPU perse in un file fallito comparivano nel resoconto
                    # come tre ore di "pause" (differenza fra orologio e
                    # lavoro).
                    secondi_lavorati += max(0.0, _t.monotonic() - _partito)
                    continue

            for w in result.warnings:
                dire(f"  ! {w}", "yellow")

            # Un'uscita CON DIFETTI non resta in OUTPUT/ col nome buono.
            # Restandoci, il rilancio vedeva `plan.output.exists()`, diceva
            # "già presente, saltato", e l'episodio mutilato non veniva più
            # riverificato da nessuno: in un lotto il `!` giallo scorreva via
            # e il danno diventava permanente. Rinominato, riparte da sola.
            if result.difettosa:
                for d in result.difetti:
                    dire(f"  ! {d}", "red")
                guasto = result.output.with_suffix(".DEFECTIVE" + result.output.suffix)
                guasto.unlink(missing_ok=True)
                try:
                    result.output.rename(guasto)
                    dire(t("cli.run.incompleta", nome=guasto.name), "red")
                except OSError as exc:
                    # Ripiegare sul nome BUONO tenendo il messaggio del
                    # successo era il peggiore dei mondi: il rilancio avrebbe
                    # visto il file già presente, l'avrebbe saltato, e
                    # sarebbe uscito 0 — cioè esattamente il danno permanente
                    # che questa parte esiste per impedire, con in più un
                    # messaggio che diceva il contrario.
                    dire(t("cli.run.incompleta_ferma", motivo=exc.strerror or exc,
                           percorso=result.output), "red")
                falliti.append(plan.source.path.name)
            else:
                console.print(
                    f"[green]  {t('cli.run.fatto')}[/green] "
                    + t("cli.run.fatto_valore", geometria=result.geometry,
                        fotogrammi=result.frames_written, durata=hms(result.seconds))
                    + (t("cli.run.fatto_dedup", quota=f"{result.dedup_saving:.0%}")
                       if result.dedup_saving else "")
                )
                console.print(Text(f"  {result.output}", style="dim"))
            in_volo = None
            if not result.difettosa:
                riusciti.append(plan.source.path.name)
            # Il tempo di QUESTO lancio, cronometrato qui. `result.seconds`
            # e' cumulativo sulle riprese (pipeline lo somma a quello gia'
            # speso nelle sessioni precedenti): usarlo faceva risultare un
            # file ripreso piu' lungo dell'intero lancio, e le "pause"
            # calcolate come differenza diventavano negative.
            secondi_lavorati += max(0.0, _t.monotonic() - _partito)
            avvisi_totali += len(result.warnings or ())
            if plan.dedup.enabled and result.dedup_saving:
                dedup_visti.append(float(result.dedup_saving))
            _scrivi_esito(plan, result)
            if result.ok and not tieni_temp:
                job.cleanup()
    finally:
        # Il marcatore di catena muore col comando, comunque finisca: un
        # "file 5 di 8" rimasto su disco farebbe credere per sempre alla
        # barra che qualcosa stia ancora lavorando.
        (PATHS.work / ".queue").unlink(missing_ok=True)
        if in_volo and in_volo not in interrotti:
            interrotti.append(in_volo)
            # E il suo tempo: il file ucciso a meta' dal Ferma tutto non
            # passa da nessuno dei `+=` del giro, quindi il suo lavoro
            # spariva. Misurato su una corsa vera: 54 secondi di GPU spesi e
            # `secondi: 0.0` nel resoconto, che poi li avrebbe presentati
            # come pausa.
            try:
                secondi_lavorati += max(0.0, _t.monotonic() - _partito)
            except NameError:      # ucciso prima ancora di cominciare
                pass
        _scrivi_lancio(
            inizio=inizio_lancio, fine=_t.time(),
            # TUTTI i file che questo comando doveva trattare, compresi
            # quelli che un piano non l'hanno mai avuto: senza, il titolo
            # della modale diceva "2 su 2" e tre righe sotto elencava un
            # file non completato.
            previsti=[p.source.path.name for p in da_fare] + scartati,
            riusciti=riusciti, falliti=falliti, scartati=scartati,
            interrotti=interrotti, secondi=secondi_lavorati,
            pausa_minuti=pausa, avvisi=avvisi_totali, dedup=dedup_visti,
            # L'interfaccia spezza una coda in un comando per MODELLO: senza
            # queste tre voci il resoconto descriveva l'ultimo spezzone e lo
            # spacciava per l'intera maratona.
            catena_inizio=catena_inizio, catena_totale=totale_catena,
            numero_finale=numero, lancio=etichetta,
            presenti=[p.source.path.name for p in plans if p not in da_fare])

    # Uscita diversa da zero se qualcosa è andato storto: con `exit 0` uno
    # script chiamante vedeva successo anche con dodici episodi falliti su
    # dodici, e un file rifiutato dal PIANO usciva già 1 — due comportamenti
    # opposti dentro lo stesso comando.
    # Anche i file rifiutati dal PIANO contano come non lavorati: uscire 0 su
    # un lotto in cui un episodio non è mai stato toccato faceva vedere
    # successo a qualunque script chiamante. Prima il conteggio raccoglieva
    # solo i guasti di Job, e i due rami dello stesso comando si comportavano
    # in modo opposto.
    non_fatti = scartati + falliti
    if non_fatti:
        dire("\n" + t("cli.run.non_completati", n=len(non_fatti), totale=len(files))
             + ", ".join(non_fatti[:5]) + (" ..." if len(non_fatti) > 5 else ""), "red")
        raise typer.Exit(1)


def _prova_binario(percorso: Path) -> str | None:
    """Esegue il binario. Ritorna None se risponde, altrimenti il motivo."""
    import subprocess
    for argomento in ("-version", "-h"):
        try:
            esito = subprocess.run(
                [str(percorso), argomento], capture_output=True,
                timeout=20, check=False,
            )
        except OSError as exc:
            return t("cli.doctor.non_eseguibile", motivo=exc.strerror or exc)
        except subprocess.TimeoutExpired:
            return t("cli.doctor.non_risponde")
        if esito.stdout or esito.stderr:
            return None
    return t("cli.doctor.nessuna_risposta")


@app.command(help=t("cli.doctor.aiuto"))
def doctor() -> None:
    """Verifica che la cartella sia autonoma e pronta all'uso."""
    console.print(f"[bold]AnimeUp {__version__}[/bold]")
    console.print(t("cli.doctor.cartella", percorso=PATHS.root) + "\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column(t("cli.doctor.dipendenza"))
    table.add_column(t("cli.doctor.stato"))
    table.add_column(t("cli.doctor.prova"))
    table.add_column(t("cli.doctor.percorso"), overflow="fold")

    portable = True
    rotti = False
    for name, tool, status in PATHS.portability_report():
        if status == "ok":
            badge = f"[green]{t('cli.doctor.vendorizzato')}[/green]"
        elif status == "sistema":
            badge = f"[yellow]{t('cli.doctor.dal_sistema')}[/yellow]"
            portable = False
        else:
            badge = f"[red]{t('cli.doctor.mancante')}[/red]"
            portable = False
        # Il binario si ESEGUE, non si guarda soltanto. Controllando solo che
        # il file esistesse e avesse il bit di esecuzione, quattro file da zero
        # byte con chmod 755 facevano dichiarare la cartella "autonoma:
        # funzionera' identica su un altro Mac". È proprio la domanda a cui
        # questo comando esiste per rispondere.
        prova = "-"
        if tool is not None:
            esito = _prova_binario(tool.path)
            if esito is None:
                prova = f"[green]{t('cli.doctor.esegue')}[/green]"
            else:
                prova = f"[red]{esito}[/red]"
                portable = False
                rotti = True
        table.add_row(name, badge, prova, str(tool.path) if tool else "-")

    console.print(table)
    console.print()

    if rotti:
        dire(t("cli.doctor.rotti"), "red")
        console.print()

    if portable:
        console.print(
            f"[green]{t('cli.doctor.autonoma')}[/green]"
        )
    else:
        console.print(
            f"[yellow]{t('cli.doctor.dipende')}[/yellow]\n"
            + t("cli.doctor.dipende_dettaglio",
                marcate=f"[yellow]{t('cli.doctor.dal_sistema')}[/yellow]",
                comando="[bold]./animeup setup[/bold]")
        )


@app.command(help=t("cli.setup.aiuto"))
def setup(
    si: Annotated[bool, typer.Option("--si", help=t("cli.setup.si"))] = False,
) -> None:
    """Scarica binari e modelli mancanti dentro bin/, per rendere la cartella portabile."""
    from .setup import vendor_all

    vendor_all(console, conferma=not si)


@app.command(help=t("cli.test.aiuto"))
def test() -> None:
    """Esegue i test di regressione (tests/run.py)."""
    # Il docstring dei test promette `./animeup test` da sempre: ora è vero.
    # Un processo separato, non un import: i test manipolano sys.path e
    # cartelle temporanee, meglio che non condividano l'interprete della CLI.
    radice = Path(__file__).resolve().parents[2]
    esito = subprocess.run([sys.executable, str(radice / "tests" / "run.py")])
    raise typer.Exit(esito.returncode)


@app.command(help=t("cli.ui.aiuto"))
def ui(
    porta: Annotated[int, typer.Option("--porta", help=t("cli.ui.porta"))] = 8899,
    rete: Annotated[bool, typer.Option("--rete", help=t("cli.ui.rete"))] = False,
    senza_browser: Annotated[bool, typer.Option(
        "--senza-browser", help=t("cli.ui.senza_browser"))] = False,
) -> None:
    """Apre l'interfaccia nel browser.

    Esisteva ed era raggiungibile solo sapendo a memoria la riga di streamlit:
    su un secondo Mac significava non trovarla affatto.
    """
    import os

    # L'interfaccia sta accanto al CODICE. Cercandola sotto `PATHS.root` non si
    # trovava quando l'utente punta ANIMEUP_ROOT a una cartella di soli dati —
    # configurazione che il lanciatore sostiene apposta.
    codice = Path(__file__).resolve().parents[2]
    app_py = codice / "ui" / "app.py"
    if not app_py.is_file():
        dire(t("cli.ui.non_trovata", percorso=app_py), "red")
        raise typer.Exit(1)

    # Una porta già occupata quasi sempre significa una sessione VECCHIA
    # rimasta aperta, e va detto invece di lasciar fallire streamlit con un
    # messaggio suo. Il caso è insidioso perché Streamlit ricarica solo
    # `ui/app.py`: i moduli importati restano quelli caricati all'avvio,
    # quindi una sessione di ore prima mostra errori su codice che nel
    # frattempo è cambiato — ed è successo davvero.
    import socket
    with socket.socket() as s:
        s.settimeout(0.4)
        occupata = s.connect_ex(("127.0.0.1", porta)) == 0
    if occupata:
        dire(t("cli.ui.occupata", porta=porta), "yellow")
        dire(t("cli.ui.vecchia"), "yellow")
        console.print(f"\n  [bold]lsof -ti :{porta} | xargs kill[/bold]\n")
        dire(t("cli.ui.altra_porta", comando=f"./animeup ui --porta {porta + 1}"),
             "dim")
        raise typer.Exit(1)

    console.print(t("cli.ui.indirizzo",
                    url=f"[bold]http://localhost:{porta}[/bold]"))
    # Si SOSTITUISCE il processo invece di generarne uno figlio: con un figlio,
    # un SIGTERM al padre lo lasciava vivo e in ascolto sulla porta, e il
    # riavvio successivo falliva. Senza padre non ci sono orfani.
    os.environ["ANIMEUP_ROOT"] = str(PATHS.root)
    # Streamlit legge il tema da `.streamlit/` nella cartella CORRENTE: si
    # parte da quella del programma, da qualunque posto si sia lanciati (l'app
    # per macOS non parte da li').
    os.chdir(codice)
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", str(app_py),
        "--server.port", str(porta),
        "--server.headless", "true" if senza_browser else "false",
        # Di fabbrica solo da questo Mac: prima il server rispondeva anche
        # agli altri dispositivi della rete, cioe' chiunque in casa (o in un
        # wifi pubblico) poteva avviare e fermare lavorazioni.
        "--server.address", "0.0.0.0" if rete else "127.0.0.1",
        "--browser.gatherUsageStats", "false",
        # Niente barra da sviluppatore di Streamlit («Deploy», menu): per chi
        # usa AnimeUp sono pulsanti che non portano da nessuna parte.
        "--client.toolbarMode", "minimal",
    ])


@app.command(name="compare", hidden=True, help=t("cli.compare.aiuto"))
def compare() -> None:
    """Il confronto delle clip chiesto dall'interfaccia (vedi `confronto`).

    Nascosto: lo lancia la pagina Confronto, staccato dalla sessione, cosi'
    un clic o un ricaricamento non lo interrompono piu'.
    """
    from . import confronto
    from .processi import tieni_sveglio
    tieni_sveglio()
    raise typer.Exit(confronto.esegui())


@app.command(help=t("cli.version.aiuto"))
def version() -> None:
    """Mostra la versione."""
    console.print(f"AnimeUp {__version__}")


@app.command(help=t("cli.tar.aiuto"))
def taratura(
    fondo: Annotated[bool, typer.Option("--fondo", hidden=True)] = False,
) -> None:
    """Misura la velocità di QUESTA macchina e tara le stime.

    Un giro di ~10 minuti sul clip libero di campioni/: estrazione, ogni
    modello a ogni scala, codifica x265. I risultati finiscono in
    records/calibration.json e da lì correggono ogni stima futura. Vuole la
    GPU libera: con una lavorazione in corso si rifiuta di partire.
    """
    from . import monitor, taratura as modulo
    from .processi import tieni_sveglio
    tieni_sveglio()

    # Con la GPU occupata i numeri uscirebbero sballati (e si darebbe
    # fastidio alla lavorazione vera): meglio un no chiaro subito.
    occupata = (any(l.vivo for l in monitor.lavori()) or monitor.catena()
                or monitor.lancio_vivo())
    if fondo:
        # Lanciata dalla pagina: niente barra nel terminale, l'avanzamento
        # va nel file di stato che la pagina rilegge.
        import os as os_
        import time as time_

        stato = modulo.stato_fondo() or {}
        stato.update({"state": modulo.IN_CORSO, "pid": os_.getpid()})
        if occupata:
            stato.update({"state": modulo.FALLITA, "error": t("cli.tar.occupata")})
            modulo.scrivi_stato(stato)
            raise typer.Exit(1)
        modulo.scrivi_stato(stato)

        def avanzamento(etichetta: str, indice: int, totale: int,
                        frazione: float, resta: float) -> None:
            stato.update({"label": etichetta, "index": indice, "total": totale,
                          "fraction": frazione, "left": resta})
            modulo.scrivi_stato(stato)

        try:
            stato["new"] = modulo.esegui(avanzamento=avanzamento)
            stato["state"] = modulo.FINITA
        except (OSError, RuntimeError, subprocess.CalledProcessError) as errore:
            stato.update({"state": modulo.FALLITA, "error": str(errore)})
        except KeyboardInterrupt:
            stato.update({"state": modulo.INTERROTTA})
        stato["ended"] = time_.time()
        modulo.scrivi_stato(stato)
        raise typer.Exit(0 if stato["state"] == modulo.FINITA else 1)
    if occupata:
        dire(t("cli.tar.occupata"), "yellow")
        raise typer.Exit(1)

    dire(t("cli.tar.inizio", chip=modulo.chip()), "cyan")
    from rich.progress import (BarColumn, Progress as RichProgress,
                               TextColumn)
    with RichProgress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as barra:
        compito = barra.add_task(t("cli.preparazione"), total=100)

        def avanzamento(etichetta: str, indice: int, totale: int,
                        frazione: float, resta: float) -> None:
            minuti = max(1, round(resta / 60))
            manca = tn("cli.tar.manca", minuti)
            barra.update(compito,
                         description=f"{etichetta} ({indice}/{totale}) "
                                     f"- {manca}",
                         completed=round(frazione * 100), total=100)

        try:
            voce = modulo.esegui(avanzamento=avanzamento)
        # Non il solo file mancante: «gia' in corso», un upscale incompleto o
        # un ffprobe che fallisce finivano in un traceback Python invece che
        # in una riga che dice cosa e' successo.
        except (OSError, RuntimeError, subprocess.CalledProcessError) as errore:
            dire(str(errore), "red")
            raise typer.Exit(1)
        barra.update(compito, completed=100, description=t("cli.tar.fatto_barra"))

    from .models import CATALOG
    tabella = Table(title=t("cli.tar.titolo", chip=modulo.chip()))
    tabella.add_column(t("cli.tar.modello"))
    tabella.add_column(t("cli.tar.scala"), justify="right")
    tabella.add_column(t("cli.tar.fabbrica"), justify="right")
    tabella.add_column(t("cli.tar.misurato"), justify="right")
    for chiave, modello in CATALOG.items():
        for scala in modello.scales:
            fabbrica = modello.throughput.get(scala)
            misurato = voce["mpxs"].get(chiave, {}).get(str(scala))
            tabella.add_row(
                modello.short, f"x{scala}",
                f"{fabbrica:.2f} Mpx/s" if fabbrica else "—",
                f"{misurato:.2f} Mpx/s" if misurato else "—",
            )
    tabella.add_row(t("cli.tar.estrazione"), "", "60 f/s",
                    f"{voce['estrazione_fps']:.0f} f/s")
    tabella.add_row(t("cli.tar.codifica"), "", "8.0 f/s",
                    f"{voce['codifica_fps']:.1f} f/s")
    console.print(tabella)
    frase = modulo.frase_salvataggio(voce)
    if frase:
        dire(frase, "dim")
    dire(t("cli.tar.fatto"), "green")


def _scrivi_esito(plan, result) -> None:
    """La pagella del file, un rigo in records/history.jsonl.

    A lavoro pulito la cartella di lavoro si autocancella e non resta NIENTE
    di leggibile: la riga dell'interfaccia non poteva dire né "fatta", né
    quanto ci ha messo davvero, né se i controlli finali hanno avvisato.
    Un rigo qui vive per sempre e costa niente.
    """
    import json as json_
    import time as time_

    try:
        PATHS.logs.mkdir(parents=True, exist_ok=True)
        with PATHS.storico.open("a") as fh:
            fh.write(su_disco.dumps({
                "file": plan.source.path.name,
                "output": plan.output.name,
                # Il percorso intero: OUTPUT si puo' cambiare dopo, e
                # «Mostra nel Finder» deve trovare il file dov'e' davvero.
                "output_path": str(plan.output),
                "secondi": round(result.seconds, 1),
                "avvisi": [str(w) for w in result.warnings],
                "difettosa": bool(result.difettosa),
                "quando": time_.time(),
                # `null` quando la deduplica era SPENTA: uno zero
                # significa "attiva, non ha trovato niente", ed e' una
                # misura buona che tiene onesto il tetto delle stime.
                "dedup": (round(float(result.dedup_saving or 0), 3)
                          if plan.dedup.enabled else None),
                "fotogrammi": int(result.frames_written or 0),
                "riprese": int(getattr(result, "riprese", 1) or 1),
                "modello": plan.model_key,
                # LA STIMA DETTA AL LANCIO, prima di sapere alcunche'.
                #
                # `previsti` qui sotto e' un'altra cosa: un ricalcolo fatto
                # DOPO, con la deduplica vera in mano. Misura quanto sbaglia
                # il modello quando gia' sa tutto, e su un file reale valeva
                # -3,5%. Costruirci sopra il TETTO di una previsione — che
                # invece non sa ne' la deduplica ne' come rendera' la
                # macchina — dava una forchetta del 7% attorno a 1, che non
                # copriva nemmeno il solo errore di ritmo misurato: e
                # Tsukimonogatari 02 e' finito +5,8% oltre il massimo
                # dichiarato (voce 85).
                #
                # Con questi tre numeri si misurano due errori diversi
                # invece di uno: quello del MODELLO (previsti contro vero) e
                # quello della PREVISIONE (est_attesa contro vero). E' il
                # secondo che deve allargare il tetto.
                "est_attesa": round(plan.est_attesa_seconds, 1),
                "est_best": round(plan.est_best_seconds, 1),
                "est_total": round(plan.est_total_seconds, 1),
                # Cosa sapeva la stima quando l'ha detto: senza questo, fra
                # un mese non si distinguera' una previsione fatta col
                # campione misurato da una fatta tirando a indovinare.
                "dedup_prevista": (round(float(plan.dedup.expected_ratio), 3)
                                   if plan.dedup.enabled else None),
                # Quanto sarebbe costato questo file secondo il modello, con
                # la deduplica VERA che ha poi avuto e al NETTO della
                # correzione già applicata. Due cautele, tutt'e due
                # necessarie perché il rapporto misuri una cosa sola:
                #  - la correzione va tolta, o il fattore misurerebbe se
                #    stesso e oscillerebbe invece di stabilizzarsi;
                #  - la deduplica dev'essere quella misurata su QUESTO file,
                #    non la mediana della cartella, altrimenti un file che
                #    ha deduplicato poco produce uno scarto enorme che viene
                #    scambiato per "lavoro non contato" e gonfia il tetto di
                #    tutti (misurato su ep05: rapporto 1,36 con la mediana,
                #    1,24 con la sua deduplica vera).
                # Un'espressione sola per tutt'e due i casi. Il vecchio
                # ripiego per la deduplica SPENTA (`est_attesa / correzione`)
                # sembrava togliere la correzione e invece ne lasciava
                # dentro il rapporto fra due fattori diversi: senza dedup
                # `est_attesa` coincide con `est_total`, che porta il fattore
                # MASSIMO, mentre si divideva per la MEDIANA — cioè 1,17
                # invece di 1,0 coi numeri di oggi (1,236 / 1,060: il 1,28
                # scritto qui prima era sbagliato). Una sola lavorazione
                # senza deduplica avvelenava la correzione di tutte le
                # successive (audit del 2026-08-10).
                "previsti": round(plan._tempo_con_dedup(
                    float(result.dedup_saving or 0) if plan.dedup.enabled
                    else 0.0, 1.0), 1),
            }) + "\n")
    except OSError:
        pass


def _scrivi_lancio(*, inizio: float, fine: float, previsti: list[str],
                   riusciti: list[str], falliti: list[str],
                   scartati: list[str], interrotti: list[str],
                   secondi: float, pausa_minuti: int, avvisi: int,
                   dedup: list[float], catena_inizio: int = 0,
                   catena_totale: int = 0, numero_finale: int = 0,
                   lancio: str = "", presenti: list[str] | None = None) -> None:
    """Com'e' andato QUESTO lancio, una riga per volta.

    Sta nel `finally` del giro: si scrive anche se la coda e' stata fermata
    a meta' o e' morta, perche' "com'e' finita" e' proprio cio' che si vuole
    sapere nei casi storti. `secondi` e' il tempo LAVORATO, non l'orologio:
    fra i due ci sono le pause e i tempi morti, e sommare quelli al lavoro
    farebbe sembrare piu' lento tutto.
    """
    import json as json_

    try:
        PATHS.logs.mkdir(parents=True, exist_ok=True)
        with PATHS.lanci.open("a") as fh:
            fh.write(su_disco.dumps({
                "inizio": round(inizio, 1), "fine": round(fine, 1),
                "previsti": previsti, "riusciti": riusciti,
                "falliti": falliti, "scartati": scartati,
                "interrotti": interrotti,
                # Gia' finiti prima di questo lancio: non sono «da fare», e
                # senza dirlo il resoconto li contava come non avviati.
                "presenti": list(presenti or []),
                "lancio": str(lancio),
                # Dove sono finiti: la cartella si puo' cambiare dopo, e il
                # resoconto deve indicare quella di allora.
                "output": str(PATHS.output),
                "catena_inizio": int(catena_inizio),
                "catena_totale": int(catena_totale),
                "numero_finale": int(numero_finale),
                "secondi": round(secondi, 1),
                "pausa_minuti": int(pausa_minuti or 0),
                "avvisi": int(avvisi),
                "dedup_medio": (round(sum(dedup) / len(dedup), 3)
                                if dedup else None),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _dedup_gia_misurata(path: Path) -> tuple[float, int] | None:
    """La deduplica gia' contata per questo sorgente, se una lavorazione
    sua esiste gia' su disco.

    Serve alle RIPRESE: un file interrotto dopo l'estrazione ha la mappa
    completa gia' pronta, e continuare a stimarlo con la mediana degli altri
    file significa buttare via il dato migliore che si ha. Senza questo,
    interfaccia e CLI mostravano due numeri diversi per lo stesso file — la
    prima leggeva la mappa, la seconda no.
    """
    from . import monitor
    # `lavori()` torna i vivi per primi e poi dal piu' recente: si prende il
    # primo che nomina questo sorgente, non l'ultimo. Con due tentativi sullo
    # stesso file vincerebbe quello abbandonato.
    for lavoro in monitor.lavori():
        if lavoro.sorgente != path.name:
            continue
        misura = monitor.dedup_esatta(lavoro.cartella)
        if misura is not None:
            return misura            # (quota, fotogrammi): il piano verifica
    return None


def _scrivi_catena(numero: int, totale: int, plan, rimanenti,
                   programma=None, pausa_minuti: int = 0,
                   pausa_pendente: bool = False) -> None:
    """Dichiara su disco a che punto è la catena: "file N di M" + stime.

    Lo legge la barra dell'interfaccia, che altrimenti — a selezione vuota —
    non avrebbe niente da dire durante una maratona: sembrava che avesse
    finito o che si fosse piantato tutto (detto dall'utente). Le stime sono
    la somma dei file che mancano, calcolate all'inizio del file corrente.
    """
    import json as json_

    # Una pausa PRIMA di ciascun file: quelle ancora da fare sono una per
    # ciascuno dei rimanenti DOPO il corrente, più quella del corrente se
    # non è ancora stata fatta — e non lo è mai, perché questo marcatore si
    # scrive apposta prima del riposo, così durante la pausa l'interfaccia
    # sa già dire chi parte dopo. Contandone una in meno il residuo restava
    # indietro di una pausa intera per tutta la durata di ogni file dal
    # secondo in poi (audit del 2026-08-10).
    respiro = (max(0, len(rimanenti) - 1)
               + (1 if pausa_pendente else 0)) * pausa_minuti * 60

    try:
        (PATHS.work / ".queue").write_text(su_disco.dumps({
            "pid": os.getpid(),
            "numero": numero,
            "totale": totale,
            "file": plan.source.path.name,
            # Le pause fra un file e l'altro sono tempo che passa davvero:
            # con dieci file in coda e cinque minuti di respiro fanno
            # quarantacinque minuti, che sparivano dal conto.
            "resta_min": (sum(p.est_best_seconds for p in rimanenti)
                          + respiro),
            "resta_max": (sum(p.est_total_seconds for p in rimanenti)
                          + respiro),
            # La quota del SOLO file corrente, cosi' l'interfaccia puo'
            # scambiarla con quanto sta misurando davvero. Senza questi due
            # numeri il residuo della coda restava la promessa fatta alla
            # partenza meno l'orologio: non imparava niente, e per quindici
            # ore ha ripetuto 10h21 su un file che ne stava impiegando 15h14
            # mentre la riga sopra, che il ritmo lo misura, diceva il numero
            # giusto (11/08).
            "file_min": (rimanenti[0].est_best_seconds if rimanenti else 0.0),
            "file_max": (rimanenti[0].est_total_seconds if rimanenti else 0.0),
            # I file DOPO quello corrente: la loro riga in interfaccia
            # mostra la chip grigia "in coda".
            "in_coda": [p.source.path.name for p in rimanenti[1:]],
            # TUTTI i file di questo lancio, lavorati compresi: è come la
            # pagina distingue i membri della catena (spunta fissa) dalla
            # scenografia (righe spente).
            "programma": [p.source.path.name for p in (programma or [])],
        }))
    except OSError:
        pass


def _pausa_respiro(minuti: int) -> None:
    """Riposo fra un file e l'altro, dichiarato su disco.

    Il marcatore `.pausa` (scadenza + PID) serve all'interfaccia: senza,
    durante la pausa nessun lucchetto esiste e la barra direbbe "GPU libera",
    invitando a lanciare un secondo lotto che collicherebbe col primo al
    risveglio. Il `finally` lo toglie anche se la pausa viene interrotta da
    un segnale (Ferma tutto compreso).
    """
    import json as json_
    import time as time_

    marker = PATHS.work / ".pause"
    try:
        marker.write_text(su_disco.dumps(
            {"fino": time_.time() + minuti * 60, "pid": os.getpid()}))
    except OSError:
        pass
    dire(t("cli.pausa", minuti=minuti), "dim")
    try:
        time_.sleep(minuti * 60)
    finally:
        # Solo se e' ancora nostro: con due code insieme si toglieva quello
        # dell'altra.
        try:
            if su_disco.loads(marker.read_text()).get("pid") == os.getpid():
                marker.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


class _SaltaFile(Exception):
    """Richiesta dell'utente: interrompi il file in corso, prosegui col resto."""


# Vero solo mentre un file lavora davvero (dentro `job.run`).
_FILE_IN_CORSO = [False]


def _salta_file(_segnale: int, _frame: object) -> None:
    # SIGUSR1 = il "Ferma" per-file dell'interfaccia. Si abbatte l'upscaler
    # (in sessione propria, il segnale da solo non lo tocca) e si solleva
    # l'eccezione che il giro dei file cattura per passare al successivo.
    # Fra un file e l'altro (pausa, preparazione) non c'e' niente da fermare:
    # l'eccezione usciva dal giro e uccideva la CLI, ma non la catena, che
    # passava al gruppo di modelli dopo come se niente fosse. Si ignora.
    if not _FILE_IN_CORSO[0]:
        return
    from . import backend
    backend.abbatti_gruppi_attivi()
    raise _SaltaFile


def _muori_pulito(_segnale: int, _frame: object) -> None:
    # Il binario ncnn gira in una sessione propria: un SIGTERM alla CLI, da
    # solo, lo lascerebbe orfano a bruciare GPU per ore. Prima si abbatte lui,
    # poi si muore. Il SystemExit attraversa `communicate()` e `subprocess.run`
    # in corso, che uccidono i loro figli (ffmpeg compreso) per conto loro,
    # e il `finally` di Job.run rilascia il lucchetto: la lavorazione resta
    # interrotta e riprendibile, senza processi appesi.
    from . import backend
    backend.abbatti_gruppi_attivi()
    raise SystemExit(143)


def main() -> None:
    signal.signal(signal.SIGTERM, _muori_pulito)
    signal.signal(signal.SIGUSR1, _salta_file)
    # Le cartelle si creano all'avvio. `ensure_dirs` esisteva e non la
    # chiamava nessuno: su un ANIMEUP_ROOT nuovo la schermata vuota diceva
    # "copia i file in .../INPUT" indicando una cartella che non c'era.
    try:
        PATHS.ensure_dirs()
    except OSError:
        pass          # radice di sola lettura: lo dirà il primo comando vero
    try:
        app()
    except MissingToolError as exc:
        dire(f"{exc}", "red")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
