"""La coda delle lavorazioni per l'app nativa: avvio, stato, pausa, stop.

Era dentro `ui/app.py` (`_avvia`, `_riprendi`, `_ferma`, `_pausa`). La
lavorazione resta quella di sempre: un `animeup run` staccato (una shell con
un comando per gruppo di modello e altezza, in sequenza), che sopravvive
all'app. Qui si lancia, si legge (con `monitor`) e si comanda con i segnali e
i marcatori che la CLI conosce:

- Ferma un file: SIGUSR1 alla CLI (il file resta riprendibile, la coda va avanti).
- Ferma tutto: SIGTERM al gruppo del lancio (tutto riprendibile).
- Pausa: SIGSTOP agli operai (upscaler, ffmpeg) + il marcatore `.suspended`.
- Start Now: il marcatore `.pause-skip`, che accorcia il riposo fra due file.

Le cartelle: OUTPUT della CLI e' la cartella di lavoro scelta nell'app (li'
nascono JOBS/ e logs/); i video finiti vanno accanto agli originali
(ANIMEUP_ACCANTO=1).
"""

from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import impostazioni, monitor, su_disco, taratura
from .paths import PATHS, code_root
from .pipeline import PAUSE_TOTALI, SOSPESO


class ErroreCoda(Exception):
    def __init__(self, codice: str, messaggio: str) -> None:
        super().__init__(messaggio)
        self.codice = codice


def paths_lavoro():
    p = copy.copy(PATHS)
    p._output = impostazioni.cartella_lavoro()
    p.__dict__.pop("work", None)
    return p


def _ambiente() -> dict:
    env = dict(os.environ)
    env["ANIMEUP_OUTPUT"] = str(impostazioni.cartella_lavoro())
    env["ANIMEUP_ACCANTO"] = "1"
    env.pop("ANIMEUP_SERVE_WAIT", None)
    return env


def _e_nostro(pid: int) -> bool:
    from .processi import di_animeup
    return pid != os.getpid() and di_animeup(pid)


# ---------------------------------------------------------------------------
#  Avvio
# ---------------------------------------------------------------------------

def occupata() -> str | None:
    """Perche' non si puo' avviare adesso, o None."""
    p = paths_lavoro()
    if taratura.in_corso():
        return "calibrating"
    if monitor.lancio_vivo(p) or monitor.catena(p) is not None or monitor.pausa(p) is not None:
        return "running"
    return None


def avvia(voci: list[dict], *, ricetta: dict | None = None) -> dict:
    """Lancia `voci` (dell'elenco: id, path, model?, height?) in coda.

    Un comando per gruppo (modello, altezza): la CLI ne accetta uno per
    invocazione. I gruppi vanno in SEQUENZA in una sola shell (`;`, non
    `&&`: un gruppo che fallisce non ferma i successivi).
    """
    motivo = occupata()
    if motivo:
        raise ErroreCoda("busy", motivo)
    if not voci:
        raise ErroreCoda("bad_params", "no files")
    cfg = impostazioni.carica_native()
    if ricetta:
        cfg = {**cfg, **{k: ricetta[k] for k in ("altezza", "crf", "preset", "disco",
                                                  "dedup", "denoise", "forza") if k in ricetta}}
    from . import piani
    gruppi: dict[tuple[str, int], list[dict]] = {}
    for v in voci:
        if ricetta and ricetta.get("modello"):
            modello = ricetta["modello"]
        else:
            pl = piani.piano(Path(v["path"]), cfg, modello=v.get("model"), altezza=v.get("height"))
            modello = pl.get("model")
            if not modello:
                raise ErroreCoda("no_plan", pl.get("error") or Path(v["path"]).name)
        altezza = (ricetta or {}).get("altezza") or v.get("height") or cfg["altezza"]
        gruppi.setdefault((modello, int(altezza)), []).append(v)

    lanciatore = code_root() / "animeup"
    totale = sum(len(g) for g in gruppi.values())
    etichetta = f"{int(time.time())}-{os.getpid()}"
    comandi, precedenti = [], 0
    for (modello, altezza), gruppo in gruppi.items():
        c = [str(lanciatore), "run", "--yes", "--launch", etichetta,
             "--height", str(altezza), "--crf", str(cfg["crf"]), "--preset", cfg["preset"],
             "--model", modello, "--disk", str(cfg["disco"])]
        if not cfg["dedup"]:
            c.append("--no-dedup")
        if cfg.get("pausa"):
            c += ["--pause", str(cfg["pausa"])]
            if comandi:
                c.append("--pause-first")
        if len(gruppi) > 1:
            c += ["--chain-total", str(totale), "--chain-start", str(precedenti)]
        if cfg.get("denoise"):
            c.append("--denoise")
        if cfg.get("forza"):
            c.append("--force")
        precedenti += len(gruppo)
        c += [v["path"] for v in gruppo]
        comandi.append(" ".join(shlex.quote(a) for a in c))

    p = paths_lavoro()
    p.work.mkdir(parents=True, exist_ok=True)
    registro = PATHS.registro_coda
    registro.parent.mkdir(parents=True, exist_ok=True)
    with registro.open("a") as fh:
        proc = subprocess.Popen(["/bin/sh", "-c", "; ".join(comandi)], stdout=fh, stderr=fh,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env=_ambiente(), cwd=str(PATHS.stato))
    ordine = [v for g in gruppi.values() for v in g]
    (p.work / ".launch").write_text(json.dumps({
        "pid": proc.pid, "started": time.time(), "total": totale, "label": etichetta,
        "files": [Path(v["path"]).name for v in ordine],
        "ids": [v["id"] for v in ordine]}))
    time.sleep(0.5)
    if proc.poll() not in (None, 0):
        raise ErroreCoda("launch_failed", f"exit {proc.poll()}, see {registro}")
    return {"started": True, "pid": proc.pid, "total": totale, "groups": len(gruppi)}


def riprendi(voce: dict) -> dict:
    """Riprende un file interrotto con la SUA ricetta (parameters.json)."""
    lav = _lavoro_di(voce)
    ricetta = {}
    if lav is not None:
        try:
            ricetta = su_disco.leggi(lav.cartella / "parameters.json")
        except (OSError, ValueError):
            ricetta = {}
    return avvia([voce], ricetta=ricetta if isinstance(ricetta, dict) else None)


def scarta(voce: dict) -> dict:
    """Butta la cartella di lavoro di un file interrotto (solo dentro JOBS)."""
    lav = _lavoro_di(voce)
    p = paths_lavoro()
    if lav is None:
        return {"discarded": False}
    if lav.vivo:
        raise ErroreCoda("busy", "the job is running")
    if p.work not in lav.cartella.parents:
        raise ErroreCoda("refused", "not inside the work folder")
    shutil.rmtree(lav.cartella, ignore_errors=True)
    return {"discarded": True}


# ---------------------------------------------------------------------------
#  Comandi sul lancio in corso
# ---------------------------------------------------------------------------

def _pid_lock(lav) -> int | None:
    try:
        pid = int((lav.cartella / "running.lock").read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _e_nostro(pid) else None


def _pid_lancio() -> int | None:
    p = paths_lavoro()
    try:
        pid = int(json.loads((p.work / ".launch").read_text())["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return pid if _e_nostro(pid) else None


def _vivo() -> object | None:
    return next((l for l in monitor.lavori(paths_lavoro()) if l.vivo), None)


def ferma_file(voce: dict) -> dict:
    lav = _lavoro_di(voce)
    if lav is None or not lav.vivo:
        return {"stopped": False}
    if monitor.sospeso(lav):
        riprendi_pausa()
        time.sleep(0.5)        # i processi devono essere svegli per morire
    pid = _pid_lock(lav)
    if pid is None:
        return {"stopped": False}
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    return {"stopped": True}


def ferma_tutto() -> dict:
    lav = _vivo()
    if lav is not None and monitor.sospeso(lav):
        riprendi_pausa()
    pid = _pid_lancio() or (_pid_lock(lav) if lav else None)
    if pid is None:
        # In riposo fra due file: il marcatore porta il pid della CLI.
        pa = monitor.pausa(paths_lavoro())
        pid = pa[1] if pa and _e_nostro(pa[1]) else None
    if pid is None:
        return {"stopped": False}
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return {"stopped": True}


def _operai_sotto(pid_cli: int) -> list[int]:
    try:
        esito = subprocess.run(["ps", "-eo", "pid=,ppid=,command="],
                               capture_output=True, text=True, check=False)
    except OSError:
        return []
    figli: dict[int, list[int]] = {}
    comando: dict[int, str] = {}
    for riga in esito.stdout.splitlines():
        parti = riga.split(None, 2)
        if len(parti) < 3:
            continue
        try:
            pid, ppid = int(parti[0]), int(parti[1])
        except ValueError:
            continue
        figli.setdefault(ppid, []).append(pid)
        comando[pid] = parti[2]
    operai, coda = [], [pid_cli]
    while coda:
        n = coda.pop()
        for f in figli.get(n, []):
            coda.append(f)
            if any(x in comando.get(f, "") for x in ("realcugan", "realesrgan", "ffmpeg")):
                operai.append(f)
    return operai


def pausa() -> dict:
    """Congela subito gli operai del file in corso (SIGSTOP)."""
    lav = _vivo()
    if lav is None:
        raise ErroreCoda("not_running", "nothing to pause")
    if monitor.sospeso(lav):
        return {"paused": True}
    pid = _pid_lock(lav)
    if pid is None:
        raise ErroreCoda("not_running", "the job doesn't answer")
    operai = _operai_sotto(pid)
    if not operai:
        raise ErroreCoda("between_steps", "nothing to freeze right now: try again in a second")
    (lav.cartella / SOSPESO).write_text(su_disco.dumps({"da": time.time(), "pids": operai}))
    for o in operai:
        try:
            os.kill(o, signal.SIGSTOP)
        except OSError:
            pass
    return {"paused": True}


def riprendi_pausa() -> dict:
    lav = next((l for l in monitor.lavori(paths_lavoro()) if l.vivo and monitor.sospeso(l)), None)
    if lav is None:
        return {"resumed": False}
    dati = monitor.sospeso(lav) or {}
    pid = _pid_lock(lav)
    for o in dati.get("pids") or (_operai_sotto(pid) if pid else []):
        try:
            os.kill(int(o), signal.SIGCONT)
        except (OSError, ValueError):
            pass
    durata = max(0.0, time.time() - float(dati.get("da") or time.time()))
    conta = lav.cartella / PAUSE_TOTALI
    try:
        prima = float(conta.read_text().strip() or 0)
    except (OSError, ValueError):
        prima = 0.0
    try:
        conta.write_text(f"{prima + durata:.1f}")
    except OSError:
        pass
    (lav.cartella / SOSPESO).unlink(missing_ok=True)
    _campioni.pop(lav.cartella.name, None)
    _stati.pop(lav.cartella.name, None)
    return {"resumed": True}


def parti_ora() -> dict:
    p = paths_lavoro()
    if monitor.pausa(p) is None:
        return {"skipped": False}
    (p.work / ".pause-skip").write_text("1")
    return {"skipped": True}


# ---------------------------------------------------------------------------
#  Lo stato, per l'evento queue.progress
# ---------------------------------------------------------------------------

_campioni: dict[str, list] = {}
_stati: dict[str, dict] = {}
_serie: dict[str, list] = {}


def _ritmo_semplice(lav, fase: str, sospeso, adesso: float) -> float | None:
    """Ripiego quando la finestra di `monitor` tace: fotogrammi dell'upscale
    contati negli ultimi ~20 secondi, solo in quella fase e non in pausa."""
    nome = lav.cartella.name
    if fase != "upscale" or sospeso:
        _serie.pop(nome, None)
        return None
    serie = _serie.setdefault(nome, [])
    if serie and lav.fatti < serie[-1][1]:
        serie.clear()
    if not serie or adesso - serie[-1][0] >= 0.5:
        serie.append((adesso, lav.fatti))
    del serie[:-40]
    while len(serie) > 2 and adesso - serie[0][0] > 20:
        serie.pop(0)
    (t0, f0), (t1, f1) = serie[0], serie[-1]
    if t1 - t0 < 3 or f1 <= f0:
        return None
    return (f1 - f0) / (t1 - t0)


def _norm(nome: str) -> str:
    return monitor._normalizza(Path(nome).stem)


def _lavoro_di(voce: dict):
    nome = Path(voce["path"]).name
    chiave = _norm(nome)
    for lav in monitor.lavori(paths_lavoro()):
        if lav.sorgente and lav.sorgente == nome:
            return lav
        if _norm(lav.nome) == chiave:
            return lav
    return None


# Quote della barra per fase (come la barra a pezzi dei board): estrazione,
# fotogrammi ripetuti, upscale (diviso in blocchi), montaggio.
QUOTE = {"extract": 0.04, "dedup": 0.02, "upscale": 0.90, "assemble": 0.04}
FASI = {"estrazione": "extract", "deduplica": "dedup", "elaborazione": "upscale",
        "codifica blocco": "upscale", "codifica finale": "assemble"}


def _frazione(lav) -> tuple[str, float]:
    fase = FASI.get(lav.fase, "upscale")
    f = lav.frazione
    if fase == "extract":
        return fase, QUOTE["extract"] * f
    if fase == "dedup":
        return fase, QUOTE["extract"] + QUOTE["dedup"] * f
    if fase == "upscale":
        return fase, QUOTE["extract"] + QUOTE["dedup"] + QUOTE["upscale"] * f
    sub = lav.codifica_frazione if lav.sottopasso != "montaggio" else 0.5 + 0.5 * f
    return fase, 1 - QUOTE["assemble"] + QUOTE["assemble"] * min(1.0, max(0.0, sub))


def stato(voci: list[dict]) -> dict:
    """Tutto cio' che la coda mostra, calcolato adesso."""
    p = paths_lavoro()
    adesso = time.time()
    lavori = monitor.lavori(p)
    vivi = [(l.cartella.name, l.fase, l.fatti) for l in lavori if l.vivo and not monitor.sospeso(l)]
    monitor.aggiorna_campioni(_campioni, _stati, vivi, adesso)
    catena = monitor.catena(p)
    riposo = monitor.pausa(p)
    lancio_vivo = monitor.lancio_vivo(p)
    try:
        lancio = json.loads((p.work / ".launch").read_text())
    except (OSError, ValueError):
        lancio = {}
    esiti = monitor.esiti(p)

    file_stati = {}
    live = None
    for v in voci:
        nome = Path(v["path"]).name
        lav = _lavoro_di(v)
        e = esiti.get(monitor._normalizza(nome))
        voce: dict = {"id": v["id"]}
        if lav is not None and lav.vivo:
            fase, frazione = _frazione(lav)
            sosp = monitor.sospeso(lav)
            ritmo = monitor.andatura(_campioni.get(lav.cartella.name, [])) or _ritmo_semplice(lav, fase, sosp, adesso)
            resto = monitor.tempo_che_resta(
                lav.fatti, lav.totale, ritmo, blocchi_totali=lav.blocchi_totali,
                blocco_n=lav.blocco_n, blocco_totale=lav.blocco_dim or lav.blocco_totale,
                turno=monitor.turno_misurato(_stati, lav.cartella.name)) if fase == "upscale" else None
            voce.update({
                "state": "paused" if sosp else "running",
                "stage": fase, "fraction": round(frazione, 4),
                "chunk": lav.blocco_n, "chunks": lav.blocchi_totali,
                "chunk_done": lav.blocco_fatti, "chunk_total": lav.blocco_totale,
                "frames_done": lav.fatti, "frames_total": lav.totale,
                "fps": round(ritmo, 2) if ritmo else None,
                "left": round(resto) if resto else None,
                "elapsed": round(max(0, adesso - (lav.avviato or adesso))),
                "paused_since": (sosp or {}).get("da"),
                "log": str(lav.registro) if lav.registro else None,
            })
            live = voce
        elif e and e.get("output_path") and Path(str(e["output_path"])).exists() \
                and float(e.get("quando") or 0) >= float(v.get("added") or 0):
            voce.update({"state": "done", "seconds": e.get("secondi"),
                         "stages": e.get("fasi") or None,
                         "warnings": e.get("avvisi") or [], "defective": bool(e.get("difettosa")),
                         "output": e.get("output_path")})
        elif lav is not None:
            voce.update({"state": "interrupted", "fraction": round(_frazione(lav)[1], 4),
                         "stage": FASI.get(lav.fase, "upscale"),
                         "log": str(lav.registro) if lav.registro else None,
                         "recipe": _ricetta(lav)})
        elif lancio_vivo and v["id"] in (lancio.get("ids") or []):
            voce["state"] = "queued"
        else:
            continue
        file_stati[v["id"]] = voce

    in_corso = lancio_vivo or catena is not None or riposo is not None
    coda: dict = {"running": in_corso, "paused": bool(live and live.get("state") == "paused")}
    if in_corso:
        ids = lancio.get("ids") or []
        fatti = sum(1 for i in ids if file_stati.get(i, {}).get("state") in ("done", "interrupted"))
        coda.update({"total": int((catena or {}).get("totale") or lancio.get("total") or len(ids) or 1),
                     "position": int((catena or {}).get("numero") or fatti + 1),
                     "ids": ids, "started": lancio.get("started")})
        residuo = monitor.residuo_coda(catena, live.get("left") if live else None, adesso)
        if residuo:
            coda["left_min"], coda["left_max"] = max(0, residuo[0]), max(0, residuo[1])
            coda["finish"] = adesso + max(0, (residuo[0] + residuo[1]) / 2)
        if riposo:
            coda["resting_until"] = riposo[0]
    return {"queue": coda, "files": file_stati, "now": adesso}


_CONFRONTATE = ("altezza", "crf", "preset", "dedup", "denoise", "forza")


def _ricetta(lav) -> dict | None:
    """I valori con cui il lavoro e' partito, in inglese, se diversi da adesso."""
    try:
        r = su_disco.leggi(lav.cartella / "parameters.json")
    except (OSError, ValueError):
        return None
    if not isinstance(r, dict):
        return None
    cfg = impostazioni.carica_native()
    diversi = {k: r[k] for k in _CONFRONTATE if k in r and r[k] != cfg.get(k)}
    if not diversi:
        return None
    return {"values": su_disco.in_inglese(diversi), "model": r.get("modello")}


def sospeso_diverso(voci: list[dict]) -> dict | None:
    """Il primo file interrotto (o in pausa) partito con valori diversi."""
    for v in voci:
        lav = _lavoro_di(v)
        if lav is None or (lav.vivo and not monitor.sospeso(lav)):
            continue
        r = _ricetta(lav)
        if r:
            return {"id": v["id"], "name": Path(v["path"]).name, **r}
    return None


def ultimo_lancio() -> dict | None:
    return monitor.ultimo_lancio(paths_lavoro())
