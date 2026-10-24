"""La preparazione del primo avvio, pilotata dall'interfaccia.

Finora i binari (FFmpeg, i motori di upscale, i modelli) si scaricavano con
`./animeup setup`, nella finestra del Terminale. L'app per macOS il Terminale
non lo mostra: la stessa preparazione deve poter partire da un pulsante e
raccontare i suoi passi a schermo. La logica resta quella di `setup.py`; qui
c'è solo il modo di farla girare in sottofondo e di leggerne l'avanzamento.
"""

from __future__ import annotations

import io
import threading

from rich.console import Console

from . import setup
from .paths import PATHS


def da_scaricare() -> dict[str, list[str]]:
    """Cosa manca, diviso come lo divide `setup`: FFmpeg e motori ncnn."""
    return {"ffmpeg": setup._ffmpeg_mancanti(), "ncnn": setup._ncnn_mancanti()}


def serve() -> bool:
    """La preparazione serve se manca qualcosa di indispensabile.

    «Indispensabile» vuol dire assente del tutto, oppure (per FFmpeg) di una
    versione diversa da quella fissata: un ffmpeg di sistema basterebbe a
    partire, ma non e' quello con cui AnimeUp e' provato.
    """
    mancano = da_scaricare()
    return bool(mancano["ffmpeg"] or mancano["ncnn"])


def peso_mb() -> int:
    """Lo stesso conto approssimato che `setup` annuncia prima di partire."""
    mancano = da_scaricare()
    return 40 * len(mancano["ffmpeg"]) + 50 * len(mancano["ncnn"])


class _Righe(io.TextIOBase):
    """Raccoglie le righe che `setup` stampa, per mostrarle nella pagina."""

    def __init__(self) -> None:
        self.righe: list[str] = []
        self._coda = ""

    def write(self, testo: str) -> int:
        self._coda += testo
        *complete, self._coda = self._coda.split("\n")
        self.righe.extend(r for r in (x.strip() for x in complete) if r)
        return len(testo)


class Preparazione:
    """Un giro di setup in un thread, con lo stato leggibile da fuori."""

    def __init__(self) -> None:
        self.righe = _Righe()
        self.finita = False
        self.errore: str | None = None
        self._thread: threading.Thread | None = None

    @property
    def in_corso(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def avvia(self) -> None:
        if self.in_corso:
            return
        self.righe = _Righe()
        self.finita, self.errore = False, None
        self._thread = threading.Thread(target=self._esegui, daemon=True)
        self._thread.start()

    def _esegui(self) -> None:
        try:
            PATHS.bin.mkdir(parents=True, exist_ok=True)
            setup.vendor_all(Console(file=self.righe, width=200, no_color=True,
                                     force_terminal=False),
                             conferma=False)
            if serve():
                # `setup` non solleva: dice cosa e' andato storto e prosegue.
                # Se a giro finito manca ancora qualcosa, quello e' l'errore.
                self.errore = "\n".join(self.righe.righe[-6:])
        except Exception as exc:  # noqa: BLE001 - va mostrato, non perso
            self.errore = str(exc)
        finally:
            self.finita = True
