"""I processi di AnimeUp, riconosciuti da quello che sono e non solo dal numero.

Lucchetti, prenotazioni, coda, pausa, taratura e confronto lasciano su disco
il PID di chi lavora. Dopo un kill -9 o uno spegnimento quel numero puo'
essere riassegnato a un processo qualunque: chiedere solo "esiste?" teneva
bloccata una lavorazione per sempre, e un Ferma tutto poteva colpire il
programma di qualcun altro. Qui si chiede anche "e' AnimeUp?".
"""

from __future__ import annotations

import os
import subprocess


def vivo(pid: int) -> bool:
    """Esiste (anche di un altro utente)? Lo zero e i negativi mai: per
    `kill` vogliono dire "il mio gruppo", che esiste sempre."""
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def di_animeup(pid: int) -> bool:
    """Vivo, non zombie, ed e' una CLI di AnimeUp (`animeup ...`, che diventa
    `python -m animeup.cli ...`). Il processo che chiede vale sempre."""
    if pid == os.getpid():
        return True
    if not vivo(pid):
        return False
    try:
        esito = subprocess.run(["ps", "-o", "state=,command=", "-p", str(pid)],
                               capture_output=True, text=True, check=False)
    except OSError:
        return True              # non si sa: meglio non buttare via niente
    riga = esito.stdout.strip()
    if esito.returncode != 0 or not riga:
        return False
    stato, _, comando = riga.partition(" ")
    if stato.startswith("Z"):
        return False             # morto, in attesa che il padre lo raccolga
    return "animeup" in comando.lower()
