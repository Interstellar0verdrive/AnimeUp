"""Le preferenze dell'utente: valori di fabbrica, sanificazione, lettura e
scrittura di `records/settings.json`.

Stavano dentro `ui/app.py`, dove solo Streamlit poteva usarle. L'app nativa
(2.0) le chiede al motore (`animeup serve`), quindi vivono qui e l'interfaccia
web le importa: una regola sola per tutte e due, invece di due copie che
prima o poi divergono.

Le chiavi sono quelle italiane del codice; su disco vanno in inglese, e la
traduzione la fa `su_disco` sul confine.
"""

from __future__ import annotations

from pathlib import Path

from . import i18n, su_disco, tema
from .paths import PATHS, gb_liberi

# Sotto questa soglia non si lavora: i soli fotogrammi sorgente di un
# episodio da 24 minuti a 720p ne occupano 31, e un blocco ci si aggiunge.
# Offrire 10 GB nel cursore significava offrire un'impostazione con cui
# nessun file puo' essere lavorato. (Soglia proposta da Interstellar0verdrive l'11/08.)
MINIMO_SPAZIO_GB = 50


def tetto_spazio(cartella: Path | None = None) -> tuple[int, int]:
    """(tetto consigliato, spazio libero) in GB, per lo spazio per file.

    Il tetto e' il PIU' PRUDENTE fra l'85% del libero e «tutto meno 40 GB».
    La percentuale da sola non basta: su un disco quasi pieno l'85% di 60 GB
    lascerebbe nove giga al sistema, che sono pochi. Su un disco vuoto vince
    invece la percentuale, e il margine assoluto non stringe inutilmente.

    Questo numero e' un TETTO, non una prenotazione: l'app occupa quello che
    il file chiede, non quello che gli si concede. Un tetto generoso non
    costa niente, serve solo a non farsi rifiutare una lavorazione che ci
    starebbe. (Regola concordata con l'utente l'11/08.)

    Il tetto non scende mai sotto `MINIMO_SPAZIO_GB + 1`: non e' generosita'
    ma la larghezza minima di un cursore. Con un disco cosi' pieno non si
    lavora comunque, e a dirlo dev'essere il rifiuto della lavorazione —
    «servono almeno N GB, liberi M» — non un cursore che sparisce.

    `cartella` e' dove finiscono i file di lavoro: di fabbrica OUTPUT (la
    1.6), la cartella di lavoro scelta nell'app nativa.
    """
    try:
        libero = int(gb_liberi(cartella if cartella is not None else PATHS.output))
    except OSError:
        return 120, 120
    return max(MINIMO_SPAZIO_GB + 1,
               min(int(libero * 0.85), libero - 40)), libero


PREDEFINITE = {
    "altezza": 1080, "crf": 18, "preset": "slower", "dedup": True,
    "denoise": False, "forza": False, "disco": None,
    "pausa": 5,
    # Acceso di fabbrica: la stima serve a decidere PRIMA di lanciare, e
    # senza la misura sul file la deduplica si deduce dai file simili per
    # taglia — criterio che pesca il fratello sbagliato (voce 84).
    "approfondita": True,
    # Scritto per esteso e non `i18n.PREDEFINITA`: il dizionario deve restare
    # un letterale, i test lo leggono cosi'. Sono la stessa cosa.
    "lingua": "en",
    # Un controllo su GitHub a ogni avvio, spegnibile: e' l'unica connessione
    # che AnimeUp fa da solo dopo il primo avvio.
    "aggiornamenti": True,
    # Sistema, Scuro o Chiaro (vedi `animeup.tema`).
    "tema": "system",
}

# Le preferenze che esistono solo nell'app nativa. Fuori da PREDEFINITE:
# l'interfaccia web scrive tutte e sole quelle chiavi, e una chiave in piu'
# che lei non conosce la farebbe cadere al salvataggio.
SOLO_NATIVE = {
    # La cartella dei file di lavoro; None = quella di fabbrica (vedi
    # `cartella_lavoro_predefinita`).
    "cartella_lavoro": None,
    # Notifiche di macOS e avanzamento sull'icona del Dock.
    "notifiche": True,
    "dock": True,
    # Dopo un file finito: False = si cancellano i file di lavoro (il log
    # resta sempre), True = si tiene tutto.
    "tieni_lavoro": False,
    # Scaricare e installare gli aggiornamenti da soli (mai durante una coda).
    "installa_auto": False,
}


def predefinite(cartella: Path | None = None) -> dict:
    """I valori di fabbrica, con lo spazio risolto sul disco di ADESSO.

    `disco` non puo' stare nel dizionario come numero fisso: il suo
    predefinito e' una REGOLA — il piu' prudente fra l'85% del libero e
    «tutto meno 40 GB» — e dipende dal disco su cui gira l'app. Scritto come
    costante valeva `MINIMO_SPAZIO_GB`, cioe' il minimo del cursore, ed e'
    cosi' che su un disco con 606 GB liberi l'impostazione si e' ritrovata a
    50 GB senza che nessuno l'avesse scelta (segnalato dall'utente il 12/08).
    """
    valori = dict(PREDEFINITE)
    valori["disco"] = tetto_spazio(cartella)[0]
    return valori


def pulite(dati: object, cartella: Path | None = None) -> dict:
    """Il salvato, controllato valore per valore: un file manomesso o di una
    versione futura non deve poter rompere i controlli dell'interfaccia (che
    con un valore fuori scala sollevano eccezione, non avvisano).

    Serve anche alla ricetta di un file sospeso (`parameters.json`).
    """
    if not isinstance(dati, dict):
        dati = {}
    puliti = predefinite(cartella)
    if dati.get("altezza") in (720, 1080, 1440, 2160):
        puliti["altezza"] = dati["altezza"]
    if dati.get("preset") in ("medium", "slow", "slower", "veryslow"):
        puliti["preset"] = dati["preset"]
    if dati.get("lingua") in i18n.LINGUE:
        puliti["lingua"] = dati["lingua"]
    if dati.get("tema") in tema.SCELTE:
        puliti["tema"] = dati["tema"]
    for chiave, minimo, massimo in (("crf", 14, 24),
                                    ("disco", MINIMO_SPAZIO_GB, tetto_spazio(cartella)[0]),
                                    ("pausa", 0, 30)):
        try:
            grezzo = int(dati[chiave])
            if isinstance(dati[chiave], bool) or grezzo < minimo:
                # SOTTO il minimo non si stringe: si scarta. Stringere
                # significherebbe presentare all'utente il valore piu' piccolo
                # possibile come se l'avesse scelto lui — ed e' esattamente
                # cosa e' successo con `disco`, ritrovato a 10 GB (il minimo
                # del cursore) su un disco da 600 liberi.
                # SOPRA il massimo invece si stringe, perche' li' il limite
                # e' fisico — il disco e' quello.
                raise ValueError(f"{chiave} fuori scala: {dati[chiave]!r}")
            puliti[chiave] = min(massimo, grezzo)
        except (KeyError, TypeError, ValueError):
            pass
    # Le chiavi booleane si RICAVANO dai valori di fabbrica, non si elencano
    # a mano: l'elenco scritto a mano diceva ("dedup", "denoise", "forza") e
    # al primo interruttore aggiunto — «Analisi approfondita» — il valore
    # salvato veniva scartato in silenzio e tornava sempre il predefinito.
    for chiave, fabbrica in PREDEFINITE.items():
        if isinstance(fabbrica, bool) and isinstance(dati.get(chiave), bool):
            puliti[chiave] = dati[chiave]
    return puliti


def _leggi_grezzo() -> dict:
    try:
        dati = su_disco.leggi(PATHS.impostazioni)
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def carica(cartella: Path | None = None) -> dict:
    """Le preferenze salvate, sanificate.

    Lo spazio per file si RICALCOLA a ogni avvio dalla regola — il piu'
    prudente fra l'85% del libero e «tutto meno 40 GB» — e il valore salvato
    si ignora, anche se valido. Deciso dall'utente il 12/08: un minimo finito
    su disco per sbaglio era indistinguibile da una scelta vera, e
    ricalcolando sempre non puo' sopravvivere a un ricaricamento. E' un
    TETTO, non una prenotazione: alzarlo non costa niente.
    """
    puliti = pulite(_leggi_grezzo(), cartella)
    puliti["disco"] = tetto_spazio(cartella)[0]
    return puliti


def scrivi(cfg: dict) -> None:
    """Salva le preferenze dell'interfaccia web (tutte e sole le sue chiavi).

    Le chiavi dell'app nativa gia' sul file restano: le due interfacce non
    girano sullo stesso stato, ma un file non deve perdere niente per essere
    passato da una all'altra.
    """
    try:
        PATHS.impostazioni.parent.mkdir(parents=True, exist_ok=True)
        extra = {k: v for k, v in _leggi_grezzo().items() if k in SOLO_NATIVE}
        PATHS.impostazioni.write_text(su_disco.dumps(
            {**{k: cfg[k] for k in PREDEFINITE}, **extra}, indent=2))
    except OSError:
        pass


# --- app nativa ------------------------------------------------------------

def cartella_lavoro_predefinita() -> Path:
    """Dove vanno i file di lavoro se l'utente non ha scelto: ~/Movies/AnimeUp
    Jobs. `ANIMEUP_WORK` la sposta (l'app di sviluppo la tiene in una cartella
    di prova, lontano dai lavori veri)."""
    import os
    env = os.environ.get("ANIMEUP_WORK")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Movies" / "AnimeUp Jobs"


def native_pulite(dati: object) -> dict:
    """Le chiavi solo native, controllate come le altre."""
    puliti = dict(SOLO_NATIVE)
    if isinstance(dati, dict):
        cartella = dati.get("cartella_lavoro")
        if isinstance(cartella, str) and cartella.startswith("/"):
            puliti["cartella_lavoro"] = cartella
        for chiave, fabbrica in SOLO_NATIVE.items():
            if isinstance(fabbrica, bool) and isinstance(dati.get(chiave), bool):
                puliti[chiave] = dati[chiave]
    return puliti


def cartella_lavoro() -> Path:
    scelta = native_pulite(_leggi_grezzo())["cartella_lavoro"]
    return Path(scelta) if scelta else cartella_lavoro_predefinita()


def carica_native() -> dict:
    """Tutte le preferenze come le vede l'app nativa: le comuni (con lo
    spazio misurato sulla cartella di lavoro) piu' le sue."""
    grezzo = _leggi_grezzo()
    native = native_pulite(grezzo)
    cartella = Path(native["cartella_lavoro"]) if native["cartella_lavoro"] \
        else cartella_lavoro_predefinita()
    puliti = pulite(grezzo, cartella)
    puliti["disco"] = tetto_spazio(cartella)[0]
    return {**puliti, **native}


def aggiorna_native(cambi: dict) -> dict:
    """Unisce `cambi` al salvato, sanifica e scrive. Ritorna il risultato.

    Le chiavi sconosciute si ignorano; un valore non valido torna a quello
    di prima (o di fabbrica), come per un file ritoccato a mano.
    """
    grezzo = _leggi_grezzo()
    unito = {**grezzo, **{k: v for k, v in cambi.items()
                          if k in PREDEFINITE or k in SOLO_NATIVE}}
    native = native_pulite(unito)
    cartella = Path(native["cartella_lavoro"]) if native["cartella_lavoro"] \
        else cartella_lavoro_predefinita()
    puliti = pulite(unito, cartella)
    PATHS.impostazioni.parent.mkdir(parents=True, exist_ok=True)
    PATHS.impostazioni.write_text(su_disco.dumps({**puliti, **native}, indent=2))
    return {**puliti, **native}
