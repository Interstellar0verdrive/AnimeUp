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


METODI: dict[str, Callable[[dict], dict]] = {
    "hello": _hello,
    "version": _hello,
    "settings.get": _settings_get,
    "settings.set": _settings_set,
    "machine.info": _machine_info,
    "calibration.state": _calibration_state,
    "tools.status": _tools_status,
    "folders.state": _folders_state,
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
    return 0
