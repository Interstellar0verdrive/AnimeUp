"""Esecuzione del modello di upscale (realesrgan-ncnn-vulkan)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .i18n import t
from .models import CATALOG, Family, Model
from .paths import PATHS, Paths

# Quanto si tollera senza vedere un fotogramma nuovo prima di dichiarare
# piantato il modello. Generoso di proposito: il fotogramma più lento
# misurato (cugan x4 su un 720p) impiega meno di due secondi, quindi un quarto
# d'ora di immobilita' non è lentezza, è un blocco.
STALLO_SECONDI = 900


class UpscaleError(RuntimeError):
    """Il modello ha fallito o ha prodotto meno fotogrammi del previsto."""


@dataclass
class UpscaleResult:
    produced: int
    expected: int
    seconds: float

    @property
    def complete(self) -> bool:
        return self.produced == self.expected


def _build_command(
    model: Model, scale: int, src: Path, dst: Path, tile: int, jobs: str, p: Paths
) -> tuple[list[str], Path | None]:
    """Riga di comando e directory di lavoro per la famiglia di modelli scelta.

    realcugan ha due trappole, entrambe scoperte facendogli produrre immagini
    nere in silenzio:
      1. antepone la propria cartella al percorso passato con -m, quindi un
         percorso assoluto diventa un percorso doppio e i modelli non si
         trovano. Va passato un percorso RELATIVO, eseguendo dalla cartella
         del binario.
      2. l'aiuto del binario dice che -1 è "no denoise": è falso. -1
         seleziona conservative, e il no-denoise è 0.
    """
    if model.family is Family.CUGAN:
        binary = p.realcugan.path
        return (
            [
                str(binary),
                "-i", str(src), "-o", str(dst),
                "-s", str(scale),
                "-n", str(model.cugan_noise),
                "-m", model.cugan_models or "models-se",
                "-t", str(tile), "-j", jobs,
            ],
            binary.parent,
        )

    return (
        [
            str(p.realesrgan.path),
            "-i", str(src), "-o", str(dst),
            "-s", str(scale), "-n", model.model_name(scale),
            "-m", str(p.models),
            "-t", str(tile), "-j", jobs,
        ],
        None,
    )


# I gruppi di processi dei binari ncnn attualmente in volo. Servono al
# gestore di segnali della CLI: il binario gira in una SESSIONE PROPRIA (vedi
# sotto), quindi un SIGTERM alla CLI non lo raggiunge da solo — e un upscaler
# orfano continua a bruciare GPU per ore, senza sorveglianza e senza che
# nessuno se ne accorga. Misurato: cinquanta minuti di realcugan orfano dopo
# un kill "pulito" del padre.
_GRUPPI_ATTIVI: set[int] = set()
_GRUPPI_GUARDIA = threading.Lock()


def abbatti_gruppi_attivi() -> None:
    """Uccide i gruppi di processi dei binari ncnn ancora in volo."""
    with _GRUPPI_GUARDIA:
        gruppi = list(_GRUPPI_ATTIVI)
    for pgid in gruppi:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _thread_salvataggio(p: Paths) -> int:
    """I thread di salvataggio misurati su questa macchina, o il predefinito.

    Import dentro la funzione: `taratura` importa questo modulo (dentro le
    sue funzioni), e tenerli slegati in cima evita di dover ragionare
    sull'ordine di caricamento.
    """
    try:
        from .taratura import carica, core, salvataggio_predefinito
        predefinito = salvataggio_predefinito()
        grezzo = (carica(p) or {}).get("jobs_salvataggio")
        # `True` e' un intero per Python, e `int(True)` fa 1: un registro
        # ritoccato a mano riduceva i thread a UNO — cioe' peggio del valore
        # fisso di prima, che questa funzione esiste per superare — senza una
        # riga di avviso (audit del 2026-08-10).
        if isinstance(grezzo, bool) or not isinstance(grezzo, (int, float)):
            return predefinito
        quanti = int(grezzo)
        # Il tetto e' lo stesso che difende tutto il resto del codice: mai
        # piu' thread che core. Prima valeva solo dentro la taratura, e un
        # valore riletto poteva scavalcarlo.
        return quanti if 1 <= quanti <= core() else predefinito
    except Exception:      # noqa: BLE001 - senza taratura si va col predefinito
        # Non "4" fisso: su una macchina da uno o due core violerebbe il
        # tetto che tutto il resto rispetta.
        # Nemmeno qui si scavalca il tetto: `os.cpu_count()` non dipende da
        # `taratura`, quindi il ripiego d'emergenza puo' rispettarlo lo
        # stesso invece di tornare un numero fisso.
        import os as _os
        return max(1, min(4, _os.cpu_count() or 1))


def upscale_dir(
    src: Path,
    dst: Path,
    *,
    scale: int,
    model: Model | str,
    tile: int = 512,
    jobs: str | None = None,
    log: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    paths: Paths | None = None,
    pgid_file: Path | None = None,
) -> UpscaleResult:
    """Upscala tutti i PNG di una cartella con il modello indicato.

    `jobs` sono i thread di ncnn per caricamento:elaborazione:salvataggio.
    Il salvataggio e' passato da 2 a 4 dopo una misura: a scala 4 la
    compressione dei PNG in uscita era il collo di bottiglia e teneva
    animevideov3 a 1.23 Mpx/s invece di 1.87 (+52%, tempo -33%), su una
    GPU che stava ferma ad aspettare. Il tetto si vedeva bene in megapixel
    di USCITA al secondo: ~20 su qualunque macchina, M4 e M3 Pro identici.
    Su questo Mac oltre i 4 thread non cambiava piu' niente, ma quanti ne
    servano dipende dal rapporto fra GPU e core: sul MacBook Pro M3 Pro, a
    scala 4, il salvataggio limitava ancora. Percio' `jobs` non e' piu' un
    numero scritto qui: se la taratura di QUESTA macchina ne ha misurato uno
    migliore, si usa quello. Senza taratura si ricade sui 4, che restano il
    valore misurato sul Mac di riferimento. Verificato che l'uscita e'
    bit-identica: piu' thread cambiano solo la velocita', non il risultato —
    e la taratura lo riverifica ogni volta con l'impronta dei file prodotti,
    perche' un'uscita diversa e' l'unico modo in cui questa scelta
    automatica potrebbe fare danno.
    """
    p = paths or PATHS
    if jobs is None:
        jobs = f"2:2:{_thread_salvataggio(p)}"
    if isinstance(model, str):
        model = CATALOG[model]
    dst.mkdir(parents=True, exist_ok=True)
    expected = sum(1 for _ in src.glob("*.png"))
    if not expected:
        return UpscaleResult(0, 0, 0.0)

    cmd, cwd = _build_command(model, scale, src, dst, tile, jobs, p)

    start = time.monotonic()
    # Sessione propria, così l'interruzione può colpire l'INTERO gruppo. Con
    # `proc.kill()` da solo muore il figlio diretto ma non un eventuale nipote,
    # che eredita il tubo di stderr: `communicate()` non vede mai EOF e il
    # lavoro resta appeso lo stesso, con in più un processo orfano. Misurato:
    # quasi quattro minuti bloccati dopo un kill andato a buon fine.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        cwd=cwd, start_new_session=True,
    )
    with _GRUPPI_GUARDIA:
        _GRUPPI_ATTIVI.add(proc.pid)
    # Il gruppo lasciato anche SU DISCO, accanto allo stato: se questo processo
    # muore di SIGKILL nessun gestore di segnali può girare, e l'unico modo
    # per la ripresa di scoprire l'orfano è trovarne il pgid scritto qui.
    if pgid_file is not None:
        try:
            pgid_file.write_text(str(proc.pid))
        except OSError:
            pass

    def _abbatti() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()

    # Il binario stampa un progresso poco utile su stderr: si preferisce
    # contare i file effettivamente scritti, che è il dato vero.
    #
    # Lo stesso conteggio fa da rilevatore di stallo. Non c'e' un tempo massimo
    # fisso, che sarebbe sbagliato in entrambi i versi: un blocco grande è
    # legittimamente lungo, e un blocco piccolo che si pianta resterebbe lì
    # per ore. Conta invece il PROGRESSO: se per un quarto d'ora non compare
    # nemmeno un fotogramma nuovo, il processo non sta lavorando. Senza questo,
    # un lavoro Vulkan piantato — o un disco esterno che si smonta — lascia la
    # lavorazione appesa per sempre: la differenza fra un episodio fallito e
    # una notte buttata.
    stop = threading.Event()
    stallo: list[str] = []

    def watch() -> None:
        ultimo, da_quando = -1, time.monotonic()
        while not stop.wait(2.0):
            fatti = sum(1 for _ in dst.glob("*.png"))
            # La callback è di chi ci chiama (una barra di rich, un widget di
            # Streamlit) e viene invocata da un thread non principale: se
            # solleva — console chiusa, tubo rotto, server caduto — il thread
            # moriva alla prima iterazione e con lui il rilevatore di stallo,
            # in silenzio. Il progresso è un di più; la sorveglianza no.
            if on_progress:
                try:
                    on_progress(fatti, expected)
                except Exception:                          # noqa: BLE001
                    pass
            if fatti != ultimo:
                ultimo, da_quando = fatti, time.monotonic()
            elif time.monotonic() - da_quando > STALLO_SECONDI:
                stallo.append(t("mot.backend.stallo",
                                minuti=STALLO_SECONDI // 60, fatti=fatti,
                                attesi=expected))
                _abbatti()
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        stderr = proc.communicate()[1] or ""
    except BaseException:                                  # noqa: BLE001
        # BaseException e non Exception: KeyboardInterrupt e SystemExit sono
        # proprio i casi in cui il binario va abbattuto — in sessione propria
        # il Ctrl+C del terminale non lo raggiunge, e senza questo ramo
        # l'upscaler restava orfano a bruciare GPU.
        _abbatti()
        raise
    finally:
        stop.set()
        watcher.join(timeout=1.0)
        with _GRUPPI_GUARDIA:
            _GRUPPI_ATTIVI.discard(proc.pid)
        if pgid_file is not None:
            pgid_file.unlink(missing_ok=True)
    if stallo:
        # Dopo l'abbattimento si aspetta comunque la chiusura del tubo, ma con
        # un tetto: se un nipote lo tiene aperto non si resta appesi.
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass

    if stallo:
        raise UpscaleError(t("mot.backend.piantato", motivo=stallo[0]))

    # Si confrontano i NOMI, non i conteggi: contando i file, un residuo in
    # `dst` mascherava una produzione incompleta, e un fotogramma scritto con
    # un nome fuori sequenza passava per buono.
    attesi = {f.name for f in src.glob("*.png")}
    prodotti = {f.name for f in dst.glob("*.png")}
    mancanti = attesi - prodotti
    produced = len(attesi & prodotti)
    seconds = time.monotonic() - start

    if log is not None:
        with log.open("a") as fh:
            fh.write(f"\n[upscale] {' '.join(cmd)}\n")
            fh.write(f"[upscale] expected {expected}, produced {produced}, {seconds:.1f}s\n")
            for line in stderr.splitlines():
                if line.strip() and not line.rstrip().endswith("%"):
                    fh.write(f"[upscale] {line}\n")

    # Un codice d'uscita non nullo conta SEMPRE, anche se i file ci sono
    # tutti: una perdita di contesto Vulkan sull'ultimo blocco lascia immagini
    # di dimensione normale ma contenuto parziale, ed è esattamente il guasto
    # silenzioso da cui la verifica dovrebbe difendere.
    if proc.returncode != 0:
        raise UpscaleError(t("mot.backend.codice_uscita", codice=proc.returncode,
                               prodotti=produced, attesi=expected)
                           + f"\n{stderr[-600:]}")
    if mancanti:
        # Silenzioso ma letale: la numerazione dei PNG avrebbe un buco e il
        # demuxer immagini troncherebbe il video senza dire nulla.
        elenco = ", ".join(sorted(mancanti)[:5])
        raise UpscaleError(t("mot.backend.mancanti", mancanti=len(mancanti),
                               attesi=expected,
                               elenco=elenco + ("..." if len(mancanti) > 5 else "")))
    return UpscaleResult(produced, expected, seconds)
