"""Avviso di nuove versioni: al massimo un controllo al giorno, mai bloccante.

Si chiede a GitHub qual è l'ultima release pubblicata e la si confronta con la
versione in uso. Niente aggiornamento automatico: si mostra una nota con il
link alla pagina della release, e l'utente decide. Il controllo è l'unica
connessione che AnimeUp fa da solo dopo il primo avvio, ed è spegnibile.

Il risultato vive in `registri/aggiornamenti.json`, così un riavvio non ripete
la richiesta e l'interfaccia legge un file invece di aspettare la rete: la
richiesta vera gira in un thread, e la nota compare al giro successivo.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__
from .paths import PATHS

REPO = "Interstellar0verdrive/AnimeUp"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGINA_RELEASE = f"https://github.com/{REPO}/releases/latest"
OGNI_SECONDI = 24 * 3600

_in_volo = threading.Lock()


def _file() -> Path:
    return PATHS.logs / "aggiornamenti.json"


def versione(testo: str) -> tuple[int, ...] | None:
    """«v1.4.2» o «1.4.2» → (1, 4, 2). Un'etichetta che non è una versione
    (una pre-release con suffisso, un nome a caso) non conta come più nuova."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (testo or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _leggi() -> dict:
    try:
        dati = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def _scrivi(dati: dict) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(json.dumps(dati, indent=2))
    except OSError:
        pass


def _chiedi_a_github() -> None:
    """La richiesta vera. Qualunque errore (offline, limite di GitHub) vale
    come «controllato, niente di nuovo»: si riprova domani, senza avvisi."""
    if not _in_volo.acquire(blocking=False):
        return
    try:
        esito = {"controllato": time.time()}
        try:
            richiesta = urllib.request.Request(API, headers={
                "User-Agent": f"AnimeUp/{__version__}",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(richiesta, timeout=6) as risposta:  # noqa: S310
                dati = json.loads(risposta.read().decode("utf-8"))
            esito["ultima"] = str(dati.get("tag_name") or "")
            esito["url"] = str(dati.get("html_url") or PAGINA_RELEASE)
        except Exception:  # noqa: BLE001 - la rete non deve mai rompere l'app
            pass
        _scrivi(esito)
    finally:
        _in_volo.release()


def disponibile(*, attivo: bool = True, adesso: float | None = None) -> dict | None:
    """La versione più nuova da segnalare, se c'è: {"versione", "url"}.

    Non aspetta mai la rete. Se l'ultimo controllo ha più di un giorno ne
    avvia uno in sottofondo e intanto risponde con quanto già saputo.
    """
    if not attivo:
        return None
    adesso = time.time() if adesso is None else adesso
    salvato = _leggi()
    if adesso - float(salvato.get("controllato") or 0) > OGNI_SECONDI:
        threading.Thread(target=_chiedi_a_github, daemon=True).start()
    ultima, attuale = versione(salvato.get("ultima", "")), versione(__version__)
    if ultima and attuale and ultima > attuale:
        return {"versione": salvato["ultima"].lstrip("v"),
                "url": salvato.get("url") or PAGINA_RELEASE}
    return None
