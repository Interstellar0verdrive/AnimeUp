"""Dalla disposizione di prima della 1.6 a quella nuova, una volta sola.

Prima tutto stava in una cartella (`INPUT/`, `OUTPUT/`, `JOBS/`,
`anteprime/`, `registri/`), con nomi e chiavi in italiano. Dalla 1.6:

  - registri, impostazioni e taratura vanno nello STATO (`records/`), con
    nomi e chiavi in inglese; le cache in `cache/`;
  - le lavorazioni (`JOBS/`) e i log di ogni file (`logs/`) vanno dentro
    OUTPUT, sullo stesso disco dei video finiti;
  - i marcatori dentro le lavorazioni prendono il nome inglese, cosi' una
    lavorazione interrotta con la 1.5 si riprende con la 1.6.

Ogni passo controlla da se' se c'e' qualcosa da fare: rilanciarla non fa
niente, e un passo che fallisce (disco pieno, permessi) lascia i file dove
stavano invece di perderli. Nessun passo cancella dati che non abbia prima
riscritto altrove.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import su_disco

# Il nome vecchio dentro `registri/` e quello nuovo dentro `records/`.
_REGISTRI = {
    "esiti.jsonl": "history.jsonl",
    "lanci.jsonl": "launches.jsonl",
    "impostazioni.json": "settings.json",
    "taratura.json": "calibration.json",
    "aggiornamenti.json": "update-check.json",
    "lavorazione.log": "queue.log",
    "interfaccia.log": "interface.log",
    ".ultimo-lancio-visto": ".last-launch-seen",
}

# I marcatori nella cartella delle lavorazioni e in ciascuna lavorazione.
_MARCATORI = {
    ".prenotazioni": ".reservations",
    ".catena": ".queue",
    ".pausa": ".pause",
    "parametri.json": "parameters.json",
    ".sospeso": ".suspended",
    ".pause_totali": ".paused_seconds",
    "in-corso.lock": "running.lock",
}

# File JSON (o JSONL) le cui chiavi vanno tradotte quando si spostano.
_DA_TRADURRE = {"esiti.jsonl", "lanci.jsonl", "impostazioni.json",
                "taratura.json", "aggiornamenti.json", ".catena", ".pausa",
                "parametri.json", ".sospeso"}

_fatte: set[str] = set()


def migra(paths) -> None:
    """Porta `paths` alla disposizione della 1.6. Silenziosa e ripetibile."""
    chiave = f"{paths.root}|{paths.stato}|{paths.output}"
    if chiave in _fatte:
        return
    _fatte.add(chiave)
    radice = paths.root
    for passo in (_lavorazioni_vecchie, _registri, _jobs, _anteprime,
                  _provvisori, _taratura_in_corso):
        try:
            passo(paths, radice)
        except OSError:
            # Un passo a meta' lascia i file vecchi al loro posto: al
            # prossimo avvio si riprova.
            continue


def _tradotto(nome: str, testo: str) -> str:
    """Il contenuto di un file vecchio, con le chiavi in inglese."""
    if nome.endswith(".jsonl"):
        righe = []
        for riga in testo.splitlines():
            if not riga.strip():
                continue
            try:
                righe.append(su_disco.dumps(su_disco.loads(riga),
                                            ensure_ascii=False))
            except ValueError:
                righe.append(riga)        # una riga rotta resta com'era
        return "".join(r + "\n" for r in righe)
    try:
        dato = su_disco.loads(testo)
    except ValueError:
        return testo
    return su_disco.dumps(dato, indent=2)


def _sposta_file(vecchio: Path, nuovo: Path) -> None:
    """Un file vecchio al posto nuovo, tradotto se e' un registro.

    Se il nuovo esiste gia' vince lui, salvo gli storici `.jsonl`, dove le
    righe vecchie vanno PRIMA delle nuove: e' la stessa cronologia.
    """
    nuovo.parent.mkdir(parents=True, exist_ok=True)
    nome = vecchio.name
    if nome in _DA_TRADURRE:
        testo = _tradotto(nome, vecchio.read_text(errors="replace"))
        if nuovo.exists():
            if not nome.endswith(".jsonl"):
                vecchio.unlink()
                return
            testo += nuovo.read_text(errors="replace")
        provvisorio = nuovo.with_name(nuovo.name + ".tmp")
        provvisorio.write_text(testo)
        provvisorio.replace(nuovo)
        vecchio.unlink()
        return
    if nuovo.exists():
        if vecchio.is_dir():
            for figlio in list(vecchio.iterdir()):
                _sposta_file(figlio, nuovo / figlio.name)
            _togli_se_vuota(vecchio)
        else:
            vecchio.unlink()
        return
    shutil.move(str(vecchio), str(nuovo))


def _togli_se_vuota(cartella: Path) -> None:
    (cartella / ".DS_Store").unlink(missing_ok=True)
    (cartella / ".gitkeep").unlink(missing_ok=True)
    try:
        cartella.rmdir()
    except OSError:
        pass


def _lavorazioni_vecchie(paths, radice: Path) -> None:
    # Fino alla 1.3.2 la cartella delle lavorazioni si chiamava LAVORAZIONI.
    vecchia = radice / "LAVORAZIONI"
    if vecchia.is_dir() and not (radice / "JOBS").exists():
        vecchia.rename(radice / "JOBS")


def _registri(paths, radice: Path) -> None:
    vecchia = radice / "registri"
    if not vecchia.is_dir():
        return
    for voce in list(vecchia.iterdir()):
        if voce.name in _REGISTRI:
            _sposta_file(voce, paths.logs / _REGISTRI[voce.name])
        elif voce.suffix == ".log":
            # Il log di un file lavorato: accanto ai video finiti.
            _sposta_file(voce, paths.job_logs / voce.name)
    _togli_se_vuota(vecchia)


def _rinomina_marcatori(cartella: Path) -> None:
    for vecchio, nuovo in _MARCATORI.items():
        if (cartella / vecchio).exists():
            _sposta_file(cartella / vecchio, cartella / nuovo)


def _jobs(paths, radice: Path) -> None:
    vecchia = radice / "JOBS"
    if vecchia.is_dir() and vecchia.resolve() != paths.work.resolve():
        analisi = vecchia / ".analisi"
        if analisi.is_dir():
            _sposta_file(analisi, paths.analisi)
        paths.work.parent.mkdir(parents=True, exist_ok=True)
        if not paths.work.exists() and _stesso_disco(vecchia, paths.work.parent):
            vecchia.rename(paths.work)
        else:
            for figlio in list(vecchia.iterdir()):
                if figlio.name in (".DS_Store", ".gitkeep"):
                    continue
                _sposta_file(figlio, paths.work / figlio.name)
            _togli_se_vuota(vecchia)
    if not paths.work.is_dir():
        return
    analisi = paths.work / ".analisi"
    if analisi.is_dir():
        _sposta_file(analisi, paths.analisi)
    _rinomina_marcatori(paths.work)
    for lavoro in paths.work.iterdir():
        if not lavoro.is_dir() or lavoro.name.startswith("."):
            continue
        _rinomina_marcatori(lavoro)
        stato = lavoro / "state.json"
        try:
            testo = stato.read_text()
        except OSError:
            continue
        if any(f'"{k}"' in testo for k in ("secondi_spesi", "interruzioni",
                                             "blocchi")):
            provvisorio = stato.with_name("state.json.tmp")
            provvisorio.write_text(_tradotto("state.json", testo))
            provvisorio.replace(stato)


def _anteprime(paths, radice: Path) -> None:
    vecchia = radice / "anteprime"
    if vecchia.is_dir():
        _sposta_file(vecchia, paths.previews)
    if not paths.previews.is_dir():
        return
    if (paths.previews / ".spezzoni").is_dir():
        _sposta_file(paths.previews / ".spezzoni", paths.previews / "clips")
    for cartella in paths.previews.iterdir():
        if not cartella.is_dir():
            continue
        if (cartella / "tempi.json").exists():
            _sposta_file(cartella / "tempi.json", cartella / "timings.json")
        for straccio in cartella.glob("*.inlavorazione.mkv"):
            straccio.unlink(missing_ok=True)


def _provvisori(paths, radice: Path) -> None:
    # Il video che si sta scrivendo porta un suffisso finche' non e' finito.
    for cartella in {paths.output, radice / "OUTPUT"}:
        if cartella.is_dir():
            for f in cartella.glob("*.inlavorazione"):
                f.rename(f.with_name(f.name[:-len(".inlavorazione")]
                                     + ".incomplete"))


def _taratura_in_corso(paths, radice: Path) -> None:
    # La cartella di lavoro di una taratura: solo file temporanei.
    shutil.rmtree(radice / ".cache" / "taratura", ignore_errors=True)


def _stesso_disco(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False
