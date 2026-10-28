"""Il motore per l'app nativa: `animeup serve`, JSON a righe su stdin/stdout.

L'app SwiftUI (2.0) avvia questo processo una volta e ci parla per tutta la
vita della finestra. Ogni riga e' un oggetto JSON:

    richiesta  {"id": 7, "method": "settings.get", "params": {}}
    risposta   {"id": 7, "result": {...}}
               {"id": 7, "error": {"code": "unknown_method", "message": "..."}}
    evento     {"event": "settings.changed", "data": {...}}

Le risposte possono arrivare in un ordine diverso dalle richieste (ognuna
gira nel suo thread): conta l'`id`. Gli eventi non hanno `id`.

Il canale e' un descrittore DEDICATO: all'avvio si fa una copia di stdout per
il protocollo, e lo stdout vero (fd 1) si gira su stderr. Cosi' una `print`
dimenticata, un messaggio di Rich o l'uscita di un sottoprocesso finiscono
nel log e non possono spezzare una riga del protocollo.

Le lavorazioni sulla GPU NON passano di qui: restano processi della riga di
comando staccati, come nella 1.6, e sopravvivono all'app.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Callable, TextIO

from . import __version__, i18n, impostazioni
from .paths import PATHS, code_root

PROTOCOLLO = 1

# Megapixel di un fotogramma 960x540: il sorgente che, a x2, esce a 1080p.
# La velocita' mostrata nell'app e' «fotogrammi al secondo a 1080p in uscita».
_MPX_540 = 960 * 540 / 1_000_000


class ErroreMetodo(Exception):
    """Un errore da riportare al chiamante, con un codice stabile."""

    def __init__(self, codice: str, messaggio: str) -> None:
        super().__init__(messaggio)
        self.codice = codice


# ---------------------------------------------------------------------------
#  I metodi
# ---------------------------------------------------------------------------

def _hello(_params: dict) -> dict:
    return {
        "engine": "animeup",
        "version": __version__,
        "protocol": PROTOCOLLO,
        "pid": os.getpid(),
        "python": platform.python_version(),
        "language": i18n.attiva(),
        "state_folder": str(PATHS.stato),
        "code_folder": str(code_root()),
    }


def _settings_get(_params: dict) -> dict:
    return _impostazioni_inglese(impostazioni.carica_native())


def _settings_set(params: dict) -> dict:
    valori = params.get("values")
    if not isinstance(valori, dict):
        raise ErroreMetodo("bad_params", "settings.set wants {\"values\": {...}}")
    # L'app parla le chiavi inglesi del file, il codice quelle italiane.
    from . import su_disco
    risultato = impostazioni.aggiorna_native(su_disco.in_italiano(valori))
    i18n.imposta(risultato["lingua"])
    inglese = _impostazioni_inglese(risultato)
    _emetti("settings.changed", inglese)
    return inglese


def _impostazioni_inglese(valori: dict) -> dict:
    from . import su_disco
    return su_disco.in_inglese(valori)


def _sysctl(nome: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", nome], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _intero(testo: str) -> int | None:
    try:
        return int(testo)
    except (TypeError, ValueError):
        return None


@cache
def _gpu_core() -> int | None:
    """I core della GPU, dal registro di IOKit (system_profiler e' lento)."""
    try:
        uscita = subprocess.run(["ioreg", "-rd1", "-c", "AGXAccelerator"],
                                capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for riga in uscita.splitlines():
        if '"gpu-core-count"' in riga:
            return _intero(riga.split("=")[-1].strip())
    return None


_NOMI_MACOS = {26: "Tahoe", 15: "Sequoia", 14: "Sonoma", 13: "Ventura"}


def _machine_info(_params: dict) -> dict:
    from . import taratura
    chip = taratura.chip()
    memoria = _intero(_sysctl("hw.memsize"))
    versione = platform.mac_ver()[0]
    try:
        maggiore = int(versione.split(".")[0])
    except ValueError:
        maggiore = 0
    return {
        "chip": chip,
        "chip_short": chip.removeprefix("Apple ").strip(),
        "cpu_cores": _intero(_sysctl("hw.physicalcpu")),
        "cpu_performance_cores": _intero(_sysctl("hw.perflevel0.physicalcpu")),
        "cpu_efficiency_cores": _intero(_sysctl("hw.perflevel1.physicalcpu")),
        "gpu_cores": _gpu_core(),
        "memory_gb": round(memoria / 1024 ** 3) if memoria else None,
        "macos_version": versione,
        "macos_name": _NOMI_MACOS.get(maggiore, ""),
        "arch": platform.machine(),
    }


def _calibration_state(_params: dict) -> dict:
    from . import taratura
    from .models import CATALOG

    voce = taratura.carica()
    fondo = taratura.stato_fondo() or {}
    stato: str
    altro = None
    if voce is None:
        altro = taratura.di_altro_mac()
        stato = "other_mac" if altro else "never"
    elif voce.get("vecchia"):
        stato = "old_version"
    else:
        stato = "done"
    modelli = []
    for chiave, modello in CATALOG.items():
        misurato = taratura.throughput(chiave, 2, mpx=_MPX_540) if voce else None
        fabbrica = modello.throughput.get(2)
        modelli.append({
            "key": chiave,
            "label": modello.label,
            "short": modello.short,
            "fps_1080p": round(misurato / _MPX_540, 2) if misurato else None,
            "factory_fps_1080p": round(fabbrica / _MPX_540, 2) if fabbrica else None,
        })
    return {
        "state": stato,
        "when": float(voce["quando"]) if voce and voce.get("quando") else None,
        "chip": (voce or {}).get("chip") or taratura.chip(),
        "other_chip": altro,
        "running": taratura.in_corso(),
        "last_run": fondo.get("state"),
        "extraction_fps": (voce or {}).get("estrazione_fps"),
        "encoding_fps_1080p": (voce or {}).get("codifica_fps"),
        "models": modelli,
    }


def _tools_status(_params: dict) -> dict:
    from . import setup

    stato = {nome: (tool, s) for nome, tool, s in PATHS.portability_report()}
    mancanti_ncnn = set(setup._ncnn_mancanti())
    voci = []
    for chiave, nome, binario in (("ffmpeg", "FFmpeg", "ffmpeg"),
                                  ("ffprobe", "FFprobe", "ffprobe"),
                                  ("realesrgan", "Real-ESRGAN", "realesrgan-ncnn-vulkan"),
                                  ("realcugan", "Real-CUGAN", "realcugan-ncnn-vulkan")):
        tool, s = stato.get(binario, (None, "mancante"))
        if binario in setup.FFMPEG_SOURCES:
            versione = setup.versione_ffmpeg(tool.path) if tool else None
            verificato = s == "ok" and versione == setup.FFMPEG_VERSIONE
            attesa = setup.FFMPEG_VERSIONE
        else:
            # Le release dei motori sono fissate e si installano solo col
            # checksum giusto: la versione e' quella della release.
            url = setup.NCNN_SOURCES[binario].url
            versione = url.split("/download/")[1].split("/")[0] if tool else None
            verificato = s == "ok" and binario not in mancanti_ncnn
            attesa = url.split("/download/")[1].split("/")[0]
        voci.append({
            "key": chiave,
            "name": nome,
            "present": tool is not None,
            "vendored": s == "ok",
            "verified": verificato,
            "version": versione,
            "expected_version": attesa,
            "path": str(tool.path) if tool else None,
        })
    return {
        "tools": voci,
        "python": {"version": platform.python_version(),
                   "short": ".".join(platform.python_version_tuple()[:2])},
        "all_verified": all(v["verified"] for v in voci),
        "bin_folder": str(PATHS.bin),
    }


def _disco(cartella: Path) -> tuple[Path | None, float, float]:
    """(cartella esistente misurata, liberi GB, totali GB) per `cartella`:
    si risale al primo antenato che c'e', come fa `gb_liberi`."""
    for candidata in (cartella, *cartella.parents):
        if candidata.parent == Path("/Volumes") and not candidata.exists():
            return None, 0.0, 0.0
        if candidata.exists():
            try:
                uso = shutil.disk_usage(candidata)
            except OSError:
                return None, 0.0, 0.0
            return candidata, uso.free / 1_073_741_824, uso.total / 1_073_741_824
    return None, 0.0, 0.0


def _volume(cartella: Path) -> str:
    parti = cartella.parts
    if len(parti) > 2 and parti[1] == "Volumes":
        return parti[2]
    return "Macintosh HD"


def _folders_state(_params: dict) -> dict:
    lavoro = impostazioni.cartella_lavoro()
    predefinita = impostazioni.cartella_lavoro_predefinita()
    misurata, libero, totale = _disco(lavoro)
    tetto, _ = impostazioni.tetto_spazio(lavoro)
    return {
        "work_folder": str(lavoro),
        "work_folder_default": str(predefinita),
        "is_default": lavoro == predefinita,
        "exists": lavoro.is_dir(),
        "reachable": misurata is not None,
        "volume": _volume(lavoro),
        "free_gb": round(libero, 1),
        "total_gb": round(totale, 1),
        "space_rule_gb": tetto,
        "space_min_gb": impostazioni.MINIMO_SPAZIO_GB,
        "space_setting_gb": impostazioni.carica_native()["disco"],
    }


def _settings_defaults(_params: dict) -> dict:
    lavoro = impostazioni.cartella_lavoro()
    return _impostazioni_inglese({**impostazioni.predefinite(lavoro), **impostazioni.SOLO_NATIVE})


# --- strumenti video --------------------------------------------------------

_installazione = threading.Lock()


def _tools_install(params: dict) -> dict:
    """Parte in un thread e risponde subito: l'avanzamento arriva come
    eventi `tools.progress`, la fine come `tools.done`."""
    from . import strumenti
    chiavi = params.get("keys")
    if chiavi is not None and not (isinstance(chiavi, list) and all(isinstance(c, str) for c in chiavi)):
        raise ErroreMetodo("bad_params", "keys must be a list of strings")
    if not _installazione.acquire(blocking=False):
        return {"started": False, "reason": "already_running"}
    da_fare = chiavi if chiavi is not None else strumenti.mancanti()

    def lavora() -> None:
        try:
            ok = strumenti.installa(da_fare, lambda e: _emetti("tools.progress", e))
            _emetti("tools.done", {"ok": ok, "status": _tools_status({})})
        finally:
            _installazione.release()

    threading.Thread(target=lavora, daemon=True, name="tools-install").start()
    return {"started": True, "keys": da_fare}


# --- aggiornamenti ----------------------------------------------------------

def _updates_state(_params: dict) -> dict:
    from . import aggiornamenti
    salvato = aggiornamenti._leggi()
    nuova = aggiornamenti.disponibile(attivo=impostazioni.carica_native().get("aggiornamenti", True))
    return {"current": __version__, "checked": salvato.get("controllato"),
            "latest": (salvato.get("ultima") or "").lstrip("v") or None,
            "available": nuova["versione"] if nuova else None,
            "url": (nuova or {}).get("url") or aggiornamenti.PAGINA_RELEASE}


def _updates_check(_params: dict) -> dict:
    from . import aggiornamenti
    esito, versione = aggiornamenti.controlla_ora()
    return {"result": {"nuova": "available", "aggiornato": "up_to_date"}.get(esito, "error"),
            "version": versione or None, **_updates_state({})}


# --- l'elenco dei video -----------------------------------------------------

_elenco = None
_elenco_lock = threading.Lock()


def elenco():
    global _elenco
    with _elenco_lock:
        if _elenco is None:
            from .elenco import Elenco
            _elenco = Elenco(_emetti_se_attivo,
                             lambda: bool(impostazioni.carica_native().get("approfondita", True)))
        return _elenco


def _emetti_se_attivo(nome: str, dati: dict) -> None:
    _emetti(nome, dati)


def _ids(params: dict, chiave: str = "ids") -> list[str]:
    ids = params.get(chiave)
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ErroreMetodo("bad_params", f"{chiave} must be a list of ids")
    return ids


def _files_list(_params: dict) -> dict:
    e = elenco()
    return {"files": e.elenco(), "activity": e.attivita()}


def _files_add(params: dict) -> dict:
    percorsi = params.get("paths")
    if not isinstance(percorsi, list) or not all(isinstance(p, str) for p in percorsi):
        raise ErroreMetodo("bad_params", "paths must be a list of strings")
    return elenco().aggiungi(percorsi, bool(params.get("subfolders", False)))


def _files_remove(params: dict) -> dict:
    return elenco().togli(_ids(params))


def _files_order(params: dict) -> dict:
    return elenco().ordina(_ids(params))


def _files_reanalyse(params: dict) -> dict:
    return elenco().rianalizza(None if params.get("all") else _ids(params))


def _files_deep(params: dict) -> dict:
    return elenco().approfondisci(_ids(params))


def _files_report(params: dict) -> dict:
    ident = params.get("id")
    voce = elenco().voce(ident) if isinstance(ident, str) else None
    if voce is None:
        raise ErroreMetodo("not_found", f"no file with id {ident!r}")
    return voce


def _plans_get(params: dict) -> dict:
    from . import piani
    voci = elenco().voci()
    ids = params.get("ids")
    if isinstance(ids, list):
        voci = [v for v in voci if v["id"] in set(ids)]
    return piani.piani(voci)


def _files_set(params: dict) -> dict:
    scelte = {k: params[k] for k in ("model", "height") if k in params}
    if not scelte:
        raise ErroreMetodo("bad_params", "files.set wants model and/or height")
    return elenco().scegli(_ids(params), **scelte)


# --- la coda delle lavorazioni -------------------------------------------

def _coda():
    from . import coda
    return coda


def _voce(ident: object) -> dict:
    v = next((v for v in elenco().voci() if v["id"] == ident), None)
    if v is None:
        raise ErroreMetodo("not_found", f"no file with id {ident!r}")
    return v


def _comando(funzione, *args) -> dict:
    c = _coda()
    try:
        esito = funzione(*args)
    except c.ErroreCoda as exc:
        raise ErroreMetodo(exc.codice, str(exc)) from exc
    _emetti_progresso(forza=True)
    return esito


def _queue_start(params: dict) -> dict:
    ids = _ids(params)
    voci = [v for v in elenco().voci() if v["id"] in set(ids)]
    voci.sort(key=lambda v: ids.index(v["id"]))
    return _comando(_coda().avvia, voci)


def _queue_status(_params: dict) -> dict:
    return _coda().stato(elenco().voci())


_ultimo_progresso: dict = {"testo": None, "in_corso": False}
_progresso_lock = threading.Lock()


def _emetti_progresso(forza: bool = False) -> None:
    """`queue.progress` se qualcosa e' cambiato (o `forza`); `queue.finished`
    quando un lancio finisce."""
    with _progresso_lock:
        try:
            st = _coda().stato(elenco().voci())
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            return
        testo = json.dumps({k: v for k, v in st.items() if k != "now"}, sort_keys=True, default=str)
        in_corso = bool(st["queue"].get("running"))
        if forza or testo != _ultimo_progresso["testo"] or in_corso:
            _emetti("queue.progress", st)
        if _ultimo_progresso["in_corso"] and not in_corso:
            _emetti("queue.finished", _queue_last({}))
        _ultimo_progresso["testo"] = testo
        _ultimo_progresso["in_corso"] = in_corso


def _osservatore() -> None:
    while True:
        time.sleep(1.0)
        if _elenco is not None:
            _emetti_progresso()
        _emetti_calibrazione()
        _emetti_confronto()


def _calibration_status(_params: dict) -> dict:
    from . import taratura
    fondo = taratura.stato_fondo() or {}
    fuori = {k: fondo.get(k) for k in ("state", "started", "index", "total", "fraction", "left",
                                       "label", "error", "seen", "ended")}
    inizi = fondo.get("step_started") or {}
    fuori["step_started"] = [inizi.get(str(i)) for i in range(len(fondo.get("steps") or []))]
    fuori["steps"] = [s[0] if isinstance(s, (list, tuple)) else s for s in (fondo.get("steps") or [])]
    fuori["running"] = taratura.in_corso() or fondo.get("state") == taratura.IN_CORSO
    fuori["log"] = str(PATHS.cache / "calibration.log")
    prima, nuova = fondo.get("previous") or {}, fondo.get("new") or {}
    righe = []
    from .models import CATALOG
    for chiave in CATALOG:
        def fps(voce):
            try:
                v = (voce.get("mpxs") or {}).get(chiave, {}).get("2")
                return round(float(v) / _MPX_540, 2) if v else None
            except (AttributeError, TypeError, ValueError):
                return None
        righe.append({"key": chiave, "before": fps(prima), "now": fps(nuova)})
    fuori["table"] = righe
    return fuori


def _calibration_start(_params: dict) -> dict:
    from . import taratura
    from . import coda
    if coda.occupata() == "running":
        raise ErroreMetodo("busy", "the queue is running")
    if not taratura.avvia_fondo():
        raise ErroreMetodo("busy", "a calibration is already running")
    _emetti_calibrazione(forza=True)
    return {"started": True}


def _calibration_stop(_params: dict) -> dict:
    from . import taratura
    fermata = taratura.ferma_fondo()
    _emetti_calibrazione(forza=True)
    return {"stopped": fermata}


def _calibration_seen(_params: dict) -> dict:
    from . import taratura
    s = taratura.stato_fondo() or {}
    if s:
        s["seen"] = True
        taratura.scrivi_stato(s)
    return {"ok": True}


_ultima_cal: dict = {"testo": None}


def _emetti_calibrazione(forza: bool = False) -> None:
    try:
        st = _calibration_status({})
    except Exception:  # noqa: BLE001
        return
    testo = json.dumps(st, sort_keys=True, default=str)
    if forza or testo != _ultima_cal["testo"]:
        _emetti("calibration.progress", st)
        if _ultima_cal["testo"] is not None and '"running": true' in _ultima_cal["testo"] and not st["running"]:
            _emetti("calibration.changed", _calibration_state({}))
    _ultima_cal["testo"] = testo


# --- il Confronto ------------------------------------------------------------

def _prova():
    from . import prova
    return prova


def _compare_call(funzione, *args, **kw):
    try:
        return funzione(*args, **kw)
    except ValueError as exc:
        raise ErroreMetodo("not_ready", str(exc)) from exc
    except RuntimeError as exc:
        raise ErroreMetodo("busy" if str(exc) == "busy" else "failed", str(exc)) from exc


def _compare_start(params: dict) -> dict:
    from . import coda
    if coda.occupata():
        raise ErroreMetodo("gpu_busy", coda.occupata() or "")
    clips = params.get("clips")
    if not isinstance(clips, list):
        raise ErroreMetodo("bad_params", "clips must be a list of start frames")
    esito = _compare_call(_prova().avvia, _voce(params.get("id")), [int(c) for c in clips],
                          [str(m) for m in params.get("models") or []], bool(params.get("reference", True)))
    _emetti_confronto(forza=True)
    return esito


def _compare_stop(_params: dict) -> dict:
    from . import confronto
    fermato = confronto.ferma()
    _emetti_confronto(forza=True)
    return {"stopped": fermato}


_ultimo_conf: dict = {"testo": None}


def _emetti_confronto(forza: bool = False) -> None:
    try:
        st = _prova().stato()
    except Exception:  # noqa: BLE001
        return
    testo = json.dumps(st, sort_keys=True, default=str)
    if forza or testo != _ultimo_conf["testo"]:
        _emetti("compare.progress", st or {})
    _ultimo_conf["testo"] = testo


def _settings_paused(_params: dict) -> dict:
    """Un file interrotto con valori diversi dalle impostazioni (ST5)."""
    return {"paused": _coda().sospeso_diverso(elenco().voci())}


def _queue_last(_params: dict) -> dict:
    from . import su_disco
    lancio = _coda().ultimo_lancio()
    return {"launch": su_disco.in_inglese(lancio) if isinstance(lancio, dict) else None}


METODI: dict[str, Callable[[dict], dict]] = {
    "hello": _hello,
    "version": _hello,
    "settings.get": _settings_get,
    "settings.set": _settings_set,
    "machine.info": _machine_info,
    "calibration.state": _calibration_state,
    "tools.status": _tools_status,
    "folders.state": _folders_state,
    "settings.defaults": _settings_defaults,
    "tools.install": _tools_install,
    "updates.state": _updates_state,
    "updates.check": _updates_check,
    "files.list": _files_list,
    "files.add": _files_add,
    "files.remove": _files_remove,
    "files.order": _files_order,
    "files.reanalyse": _files_reanalyse,
    "files.deep": _files_deep,
    "files.report": _files_report,
    "files.set": _files_set,
    "plans.get": _plans_get,
    "queue.start": _queue_start,
    "queue.status": _queue_status,
    "queue.stop": lambda p: _comando(_coda().ferma_file, _voce(p.get("id"))),
    "queue.stopAll": lambda p: _comando(_coda().ferma_tutto),
    "queue.pause": lambda p: _comando(_coda().pausa),
    "queue.resume": lambda p: _comando(_coda().riprendi_pausa),
    "queue.startNow": lambda p: _comando(_coda().parti_ora),
    "queue.last": _queue_last,
    "settings.paused": _settings_paused,
    "compare.clips": lambda p: _compare_call(_prova().clips, _voce(p.get("id"))),
    "compare.scan": lambda p: _prova().scansiona(_voce(p.get("id")), _emetti, altri=bool(p.get("more"))),
    "compare.models": lambda p: _compare_call(_prova().modelli, _voce(p.get("id")),
                                              [int(c) for c in p["clips"]] if isinstance(p.get("clips"), list) else None),
    "compare.start": _compare_start,
    "compare.stop": _compare_stop,
    "compare.status": lambda p: _prova().stato() or {},
    "compare.playable": lambda p: {"path": _compare_call(_prova().riproducibile, str(p.get("path")))},
    "compare.state": lambda p: _prova().leggi_stati(),
    "calibration.status": _calibration_status,
    "calibration.start": _calibration_start,
    "calibration.stop": _calibration_stop,
    "calibration.seen": _calibration_seen,
    "job.resume": lambda p: _comando(_coda().riprendi, _voce(p.get("id"))),
    "job.discard": lambda p: _comando(_coda().scarta, _voce(p.get("id"))),
}


# ---------------------------------------------------------------------------
#  Il canale
# ---------------------------------------------------------------------------

_uscita: TextIO | None = None
_scrittura = threading.Lock()


def _scrivi(oggetto: dict) -> None:
    riga = json.dumps(oggetto, ensure_ascii=False, separators=(",", ":"))
    with _scrittura:
        assert _uscita is not None
        _uscita.write(riga + "\n")
        _uscita.flush()


def _emetti(evento: str, dati: dict) -> None:
    if _uscita is not None:
        _scrivi({"event": evento, "data": dati})


def gestisci(richiesta: object) -> dict | None:
    """La risposta a una richiesta gia' decodificata (None: niente risposta)."""
    if not isinstance(richiesta, dict):
        return {"id": None, "error": {"code": "bad_request",
                                      "message": "a request is a JSON object"}}
    ident = richiesta.get("id")
    metodo = richiesta.get("method")
    params = richiesta.get("params") or {}
    if not isinstance(metodo, str) or not isinstance(params, dict):
        return {"id": ident, "error": {"code": "bad_request",
                                       "message": "needs a method and object params"}}
    funzione = METODI.get(metodo)
    if funzione is None:
        return {"id": ident, "error": {"code": "unknown_method",
                                       "message": f"unknown method: {metodo}"}}
    try:
        return {"id": ident, "result": funzione(params)}
    except ErroreMetodo as exc:
        return {"id": ident, "error": {"code": exc.codice, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 - il motore non deve cadere
        traceback.print_exc(file=sys.stderr)
        return {"id": ident, "error": {"code": "internal",
                                       "message": f"{type(exc).__name__}: {exc}"}}


def esegui() -> int:
    """Il ciclo: una riga letta, un lavoro nel pool; esce a stdin chiuso."""
    global _uscita
    # Il protocollo su una copia di stdout; fd 1 diventa stderr.
    _uscita = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    # I video finiti dell'app nativa vanno accanto agli originali (anche
    # nei piani mostrati, che devono dire lo stesso nome e la stessa cartella).
    os.environ.setdefault("ANIMEUP_ACCANTO", "1")
    # Nessun segnale bloccato in eredita' (l'app che ci lancia puo' averne):
    # le lavorazioni partono da qui, e Ferma / Ferma tutto vivono di segnali.
    import signal as _segnali
    _segnali.pthread_sigmask(_segnali.SIG_SETMASK, [])
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    _emetti("ready", {"version": __version__, "protocol": PROTOCOLLO,
                      "pid": os.getpid()})
    print(f"animeup serve {__version__}: ready (pid {os.getpid()})", file=sys.stderr)

    def lavora(riga: str) -> None:
        try:
            richiesta = json.loads(riga)
        except ValueError as exc:
            _scrivi({"id": None, "error": {"code": "bad_json", "message": str(exc)}})
            return
        if isinstance(richiesta, dict) and richiesta.get("method") == "shutdown":
            return
        risposta = gestisci(richiesta)
        if risposta is not None:
            _scrivi(risposta)

    if os.environ.get("ANIMEUP_SERVE_WAIT") != "1":
        threading.Thread(target=_osservatore, daemon=True, name="queue-watch").start()

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="serve") as pool:
        for riga in sys.stdin:
            riga = riga.strip()
            if not riga:
                continue
            try:
                richiesta = json.loads(riga)
            except ValueError:
                richiesta = None
            if isinstance(richiesta, dict) and richiesta.get("method") == "shutdown":
                _scrivi({"id": richiesta.get("id"), "result": {"bye": True}})
                break
            pool.submit(lavora, riga)
    # Per i test: a stdin chiuso si aspetta la fine delle analisi in corso.
    if os.environ.get("ANIMEUP_SERVE_WAIT") == "1" and _elenco is not None:
        _elenco.aspetta()
    return 0
