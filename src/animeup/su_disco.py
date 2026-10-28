"""I file che AnimeUp scrive, in inglese per chi li apre.

Il codice ragiona con chiavi italiane (`secondi`, `avvisi`, `macchine`...),
ma i registri, le impostazioni e la taratura li puo' aprire chiunque, e
chiunque deve leggerli in inglese a prescindere dalla lingua scelta. La
traduzione avviene QUI, sul confine: si scrive in inglese, si rilegge in
italiano. Il resto del codice non sa niente.

La rilettura accetta anche le chiavi italiane: un file scritto prima della
1.6 si legge uguale, e la migrazione (vedi `migrazione`) lo riscrive.

Le cache (analisi dei sorgenti, clip del confronto) non passano di qui: le
loro chiavi sono i nomi dei campi del codice, e nessuno le deve leggere.
"""

from __future__ import annotations

import json
from pathlib import Path

# Una parola italiana, una inglese, in TUTTI i file: la traduzione va in
# tutt'e due le direzioni e non deve mai poter scegliere. Le chiavi che
# sono gia' inglesi (file, output, dedup, crf, preset, clip, pid...) non
# compaiono.
VOCABOLARIO: dict[str, str] = {
    # impostazioni
    "altezza": "height",
    "forza": "force",
    "disco": "disk_gb",
    "pausa": "pause_between_files",
    "approfondita": "deep_analysis",
    "lingua": "language",
    "aggiornamenti": "check_updates",
    "tema": "theme",
    "cartella_lavoro": "work_folder",
    "notifiche": "notifications",
    "dock": "dock_progress",
    "tieni_lavoro": "keep_work_files",
    "installa_auto": "auto_install",
    # storico dei file (history.jsonl)
    "secondi": "seconds",
    "fasi": "stages",
    "avvisi": "warnings",
    "difettosa": "defective",
    "quando": "when",
    "fotogrammi": "frames",
    "riprese": "runs",
    "modello": "model",
    "est_attesa": "est_expected",
    "dedup_prevista": "dedup_expected",
    "previsti": "expected",
    # lanci (launches.jsonl)
    "inizio": "started",
    "fine": "ended",
    "riusciti": "succeeded",
    "falliti": "failed",
    "scartati": "skipped",
    "interrotti": "interrupted",
    "presenti": "already_done",
    "difettosi": "defective_outputs",
    "lancio": "launch",
    "catena_inizio": "queue_start",
    "catena_totale": "queue_total",
    "numero_finale": "final_number",
    "pausa_minuti": "pause_minutes",
    "dedup_medio": "dedup_mean",
    # parametri di una lavorazione (parameters.json)
    "scala": "scale",
    # la coda in corso (.queue) e la pausa fra i file (.pause)
    "numero": "number",
    "totale": "total",
    "resta_min": "remaining_min",
    "resta_max": "remaining_max",
    "in_coda": "queued",
    "programma": "schedule",
    "fino": "until",
    # stato di una lavorazione (state.json)
    "secondi_spesi": "seconds_spent",
    "interruzioni": "interruptions",
    "blocchi": "chunk_log",
    "da": "from",
    "a": "to",
    "tenuti": "kept",
    # taratura (calibration.json)
    "versione": "version",
    "macchine": "machines",
    "fotogrammi_misura": "sample_frames",
    "mpx_misura": "sample_mpx",
    "estrazione_fps": "extraction_fps",
    "codifica_fps": "encoding_fps",
    "scansione_fps": "scan_fps",
    "jobs_salvataggio": "save_jobs",
    "prove_salvataggio": "save_trials",
    "ritmo": "rate",
    "impronta": "fingerprint",
    "nota": "note",
    # controllo aggiornamenti (update-check.json)
    "controllato": "checked",
    "ultima": "latest",
}

_INVERSO = {inglese: italiano for italiano, inglese in VOCABOLARIO.items()}


def _traduci(dato, tabella: dict[str, str]):
    if isinstance(dato, dict):
        return {tabella.get(k, k): _traduci(v, tabella) for k, v in dato.items()}
    if isinstance(dato, list):
        return [_traduci(v, tabella) for v in dato]
    return dato


def in_inglese(dato):
    """Le chiavi come vanno su disco."""
    return _traduci(dato, VOCABOLARIO)


def in_italiano(dato):
    """Le chiavi come le usa il codice; quelle gia' italiane restano."""
    return _traduci(dato, _INVERSO)


def dumps(dato, **kw) -> str:
    return json.dumps(in_inglese(dato), **kw)


def loads(testo: str):
    return in_italiano(json.loads(testo))


def leggi(percorso: Path):
    """Il contenuto del file, con le chiavi del codice. Alza come `json`."""
    return loads(percorso.read_text())


def righe(testo: str) -> list:
    """Le voci di un file .jsonl; le righe rotte si saltano."""
    voci = []
    for riga in testo.splitlines():
        if not riga.strip():
            continue
        try:
            voci.append(loads(riga))
        except ValueError:
            continue
    return voci
