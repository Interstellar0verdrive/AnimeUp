"""Dalla disposizione di prima della 1.6 a quella nuova, una volta sola.

Prima tutto stava in una cartella (`INPUT/`, `OUTPUT/`, `JOBS/`,
`anteprime/`, `registri/`), con nomi e chiavi in italiano. Dalla 1.6:

  - registri, impostazioni e taratura vanno nello STATO (`records/`), con
    nomi e chiavi in inglese; le cache in `cache/`;
  - le lavorazioni (`JOBS/`) e i log di ogni file (`logs/`) vanno dentro
    OUTPUT, sullo stesso disco dei video finiti;
  - le clip del confronto (`anteprime/`) si scartano: sono una cache, con
    nomi di file italiani, e il confronto le rifa' quando servono;
  - i marcatori dentro le lavorazioni prendono il nome inglese, cosi' una
    lavorazione interrotta con la 1.5 si riprende con la 1.6.

Ogni passo controlla da se' se c'e' qualcosa da fare: rilanciarla non fa
niente, e un passo che fallisce (disco pieno, permessi) lascia i file dove
stavano invece di perderli. Nessun passo cancella dati che non abbia prima
riscritto altrove, salvo le cache.
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

# Cosa la migrazione non ha potuto fare, per l'interfaccia: codici con i
# loro dati, tradotti dalla pagina. Vale per l'ultimo `migra` di questo
# processo.
avvisi: list[tuple[str, dict]] = []


def migra(paths) -> None:
    """Porta `paths` alla disposizione della 1.6. Silenziosa e ripetibile.

    Un processo alla volta (un lucchetto nello stato): due avvii insieme
    fondevano gli storici due volte. E niente si sposta da sotto i piedi di
    una 1.5 ancora al lavoro: l'aggiornamento della 1.5 lascia girare le
    lavorazioni, e spostarle a meta' le faceva fallire. Si riprova al
    prossimo avvio, quando ha finito.
    """
    chiave = f"{paths.root}|{paths.stato}|{paths.output}"
    if chiave in _fatte:
        return
    _fatte.add(chiave)
    avvisi.clear()
    radice = paths.root
    try:
        paths.stato.mkdir(parents=True, exist_ok=True)
        lucchetto = open(paths.stato / ".migration.lock", "w")
    except OSError:
        lucchetto = None
    try:
        if lucchetto is not None:
            import fcntl
            fcntl.flock(lucchetto, fcntl.LOCK_EX)
        passi = [_lavorazioni_vecchie, _registri, _jobs, _anteprime,
                 _provvisori, _taratura_in_corso]
        if _vecchia_al_lavoro(radice):
            avvisi.append(("mig.rimandata", {}))
            passi = [_anteprime]
        for passo in passi:
            try:
                passo(paths, radice)
            except OSError as exc:
                # Un passo a meta' lascia i file vecchi al loro posto: al
                # prossimo avvio si riprova.
                avvisi.append(("mig.errore", {"dettaglio": str(exc)}))
    finally:
        if lucchetto is not None:
            lucchetto.close()


def _pid_vivo(testo: str) -> bool:
    import json
    try:
        dato = json.loads(testo)
        pid = int(dato.get("pid") if isinstance(dato, dict) else dato)
    except (ValueError, TypeError, AttributeError):
        return False
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _vecchia_al_lavoro(radice: Path) -> bool:
    """Una 1.5 (o prima) sta lavorando nella disposizione vecchia?"""
    jobs = radice / "JOBS"
    candidati = [jobs / ".catena", jobs / ".pausa",
                 radice / ".cache" / "taratura" / "in-corso.lock"]
    if jobs.is_dir():
        try:
            candidati += [d / "in-corso.lock" for d in jobs.iterdir() if d.is_dir()]
        except OSError:
            pass
    for f in candidati:
        try:
            if f.is_file() and _pid_vivo(f.read_text()):
                return True
        except OSError:
            continue
    return False


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


def _quando(riga: str) -> float:
    import json
    try:
        d = json.loads(riga)
        return float(d.get("when") or d.get("ended") or d.get("started") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _unisci_righe(*testi: str) -> str:
    """Due cronologie in una: senza doppioni (una fusione ripetuta, perche'
    il vecchio file non si e' potuto togliere, non raddoppia niente) e in
    ordine di tempo, qualunque delle due sia la piu' recente."""
    viste: set[str] = set()
    righe = []
    for testo in testi:
        for riga in testo.splitlines():
            if riga.strip() and riga not in viste:
                viste.add(riga)
                righe.append(riga)
    righe.sort(key=_quando)          # stabile: a parita' resta l'ordine
    return "".join(r + "\n" for r in righe)


def _unisci_tarature(vecchio: str, nuovo: str) -> str | None:
    """Le tarature sono per macchina: si tengono tutte, e per la stessa
    macchina la piu' recente."""
    import json
    try:
        a, b = json.loads(vecchio), json.loads(nuovo)
        ma, mb = a.get("machines") or {}, b.get("machines") or {}
        if not isinstance(ma, dict) or not isinstance(mb, dict):
            return None
    except (ValueError, AttributeError):
        return None
    for chip, voce in ma.items():
        altra = mb.get(chip)
        recente = lambda v: float(v.get("when") or 0) if isinstance(v, dict) else 0.0
        if altra is None or recente(voce) > recente(altra):
            mb[chip] = voce
    b["machines"] = mb
    return json.dumps(b, indent=2)


def _scrivi(destinazione: Path, testo: str) -> None:
    provvisorio = destinazione.with_name(f"{destinazione.name}.{os.getpid()}.tmp")
    provvisorio.write_text(testo)
    provvisorio.replace(destinazione)


def _da_parte(perdente: Path, destinazione: Path) -> None:
    """Il file che non vince resta accanto, mai cancellato."""
    try:
        perdente.replace(destinazione.with_name(destinazione.name + ".old"))
    except OSError:
        pass


def _stesso_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _sposta_file(vecchio: Path, nuovo: Path) -> None:
    """Un file vecchio al posto nuovo, tradotto se e' un registro.

    Niente si cancella senza essere stato riscritto altrove: le cronologie
    `.jsonl` e i log si fondono, le tarature si uniscono macchina per
    macchina, e per il resto vince il file piu' recente mentre l'altro
    resta accanto con `.old`. Lo stesso file con due nomi (maiuscole,
    collegamenti) non si tocca: prima si cancellava se stesso.
    """
    if nuovo.exists() and _stesso_file(vecchio, nuovo):
        return
    nuovo.parent.mkdir(parents=True, exist_ok=True)
    nome = vecchio.name
    if vecchio.is_dir():
        if not nuovo.exists():
            _muovi(vecchio, nuovo)
            return
        for figlio in list(vecchio.iterdir()):
            try:
                _sposta_file(figlio, nuovo / figlio.name)
            except OSError as exc:
                avvisi.append(("mig.errore", {"dettaglio": str(exc)}))
        _togli_se_vuota(vecchio)
        return
    if nome in _DA_TRADURRE:
        testo = _tradotto(nome, vecchio.read_text(errors="replace"))
        if not nuovo.exists():
            _scrivi(nuovo, testo)
            vecchio.unlink()
            return
        attuale = nuovo.read_text(errors="replace")
        if nome.endswith(".jsonl"):
            _scrivi(nuovo, _unisci_righe(testo, attuale))
            vecchio.unlink()
            return
        if nome == "taratura.json":
            unita = _unisci_tarature(testo, attuale)
            if unita is not None:
                _scrivi(nuovo, unita)
                vecchio.unlink()
                return
        if vecchio.stat().st_mtime > nuovo.stat().st_mtime:
            _da_parte(nuovo, nuovo)
            _scrivi(nuovo, testo)
            vecchio.unlink()
        else:
            _scrivi(vecchio, testo)
            _da_parte(vecchio, nuovo)
        return
    if not nuovo.exists():
        _muovi(vecchio, nuovo)
        return
    if nome.endswith(".log"):
        _scrivi(nuovo, vecchio.read_text(errors="replace")
                + nuovo.read_text(errors="replace"))
        vecchio.unlink()
        return
    a, b = vecchio.stat(), nuovo.stat()
    if a.st_size == b.st_size and a.st_mtime <= b.st_mtime:
        vecchio.unlink()                 # la stessa copia, gia' arrivata
    elif a.st_mtime > b.st_mtime:
        _da_parte(nuovo, nuovo)
        _muovi(vecchio, nuovo)
    else:
        _da_parte(vecchio, nuovo)


def _muovi(vecchio: Path, nuovo: Path) -> None:
    """Sullo stesso disco una rinomina; altrimenti copia con un nome
    provvisorio e rinomina alla fine, cosi' una copia a meta' non prende
    mai il posto dell'originale."""
    if _stesso_disco(vecchio, nuovo.parent):
        vecchio.rename(nuovo)
        return
    provvisorio = nuovo.with_name(f"{nuovo.name}.{os.getpid()}.part")
    if vecchio.is_dir():
        shutil.copytree(vecchio, provvisorio)
    else:
        shutil.copy2(vecchio, provvisorio)
    provvisorio.rename(nuovo)
    if vecchio.is_dir():
        shutil.rmtree(vecchio)
    else:
        vecchio.unlink()


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
        # Uno alla volta: un file illeggibile non deve nascondere tutti gli
        # altri (impostazioni, taratura, storico) a ogni avvio.
        try:
            if voce.name in _REGISTRI:
                _sposta_file(voce, paths.logs / _REGISTRI[voce.name])
            elif voce.suffix == ".log":
                # Il log di un file lavorato: accanto ai video finiti.
                _sposta_file(voce, paths.job_logs / voce.name)
        except OSError as exc:
            avvisi.append(("mig.errore", {"dettaglio": str(exc)}))
    _togli_se_vuota(vecchia)


def _rinomina_marcatori(cartella: Path) -> None:
    for vecchio, nuovo in _MARCATORI.items():
        if (cartella / vecchio).exists():
            _sposta_file(cartella / vecchio, cartella / nuovo)


def _jobs(paths, radice: Path) -> None:
    vecchia = radice / "JOBS"
    paths.work.parent.mkdir(parents=True, exist_ok=True)
    if (vecchia.is_dir() and vecchia.resolve() != paths.work.resolve()
            and not _stesso_file(vecchia, paths.work)):
        analisi = vecchia / ".analisi"
        if analisi.is_dir():
            _sposta_file(analisi, paths.analisi)
        if not _stesso_disco(vecchia, paths.work.parent):
            # Decine di GB da copiare all'avvio, con la pagina ferma e il
            # rischio di una copia a meta': si lascia fare all'utente.
            if any(d.is_dir() and not d.name.startswith(".") for d in vecchia.iterdir()):
                avvisi.append(("mig.jobs_altro_disco",
                               {"vecchia": str(vecchia), "nuova": str(paths.work)}))
        elif not paths.work.exists():
            vecchia.rename(paths.work)
        else:
            for figlio in list(vecchia.iterdir()):
                if figlio.name in (".DS_Store", ".gitkeep"):
                    continue
                try:
                    _sposta_file(figlio, paths.work / figlio.name)
                except OSError as exc:
                    avvisi.append(("mig.errore", {"dettaglio": str(exc)}))
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
        try:
            _rinomina_marcatori(lavoro)
            stato = lavoro / "state.json"
            try:
                testo = stato.read_text()
            except OSError:
                continue
            if any(f'"{k}"' in testo for k in ("secondi_spesi", "interruzioni",
                                                 "blocchi")):
                _scrivi(stato, _tradotto("state.json", testo))
        except OSError as exc:
            avvisi.append(("mig.errore", {"dettaglio": str(exc)}))


def _anteprime(paths, radice: Path) -> None:
    # Una cache: originale.mkv, confronto_1a1.png, cartelle "movimento_…".
    # Tradurla file per file non vale il rischio; il confronto la rifa'.
    shutil.rmtree(radice / "anteprime", ignore_errors=True)


def _provvisori(paths, radice: Path) -> None:
    # Il video che si sta scrivendo porta un suffisso finche' non e' finito;
    # quello che non ha passato i controlli finali ne porta un altro.
    for cartella in {paths.output, radice / "OUTPUT"}:
        if cartella.is_dir():
            for f in cartella.glob("*.inlavorazione"):
                f.rename(f.with_name(f.name[:-len(".inlavorazione")]
                                     + ".incomplete"))
            for f in cartella.glob("*.PARZIALE.*"):
                f.rename(f.with_name(f.name.replace(".PARZIALE.", ".DEFECTIVE.")))


def _taratura_in_corso(paths, radice: Path) -> None:
    # La cartella di lavoro di una taratura: solo file temporanei.
    shutil.rmtree(radice / ".cache" / "taratura", ignore_errors=True)


def _stesso_disco(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False
