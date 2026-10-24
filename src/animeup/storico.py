"""Cosa dicono le lavorazioni gia' fatte, per stimare meglio le prossime.

Riguarda i CONTENUTI, non la macchina: e' il gemello di `taratura`, che
misura invece l'hardware. Vive separato perche' le due cose hanno vite
diverse — cambiando Mac la taratura va rifatta, la storia dei file no.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .paths import PATHS, Paths

# Quante pagelle CONTANO, fra quelle che somigliano al file da stimare. Una
# finestra e non tutta la storia: il materiale di due anni fa puo' non
# somigliare a quello di oggi.
FINESTRA = 10

# Quante se ne LEGGONO per trovarne dieci simili. Sono due numeri diversi, e
# confonderli annullava il filtro di taglia: leggendo solo le ultime dieci
# pagelle, dieci prove corte di fila spingono fuori dalla finestra tutti gli
# episodi veri, e l'episodio successivo viene stimato sulle prove. Misurato
# in audit con due episodi al 35% dietro dieci clip al 5%: l'episodio
# riceveva 5%, e una correzione di 1,30 invece di 1,00. Sul Mac mini la
# situazione era gia' a un passo — dieci pagelle in tutto, di cui quattro
# di prova.
FINESTRA_LETTURA = 60


@dataclass(frozen=True)
class Deduplica:
    """Quanti fotogrammi ripetuti aspettarsi, secondo i file gia' fatti."""

    attesa: float           # la mediana: il valore su cui si stima
    minimo: float           # il caso meno favorevole fra quelli osservati
    massimo: float          # il piu' favorevole
    campioni: int           # su quante lavorazioni

    @property
    def affidabile(self) -> bool:
        """Con un solo file non c'e' una forchetta, solo un aneddoto."""
        return self.campioni >= 2


def _mediana(valori: list[float]) -> float:
    ordinati = sorted(valori)
    meta = len(ordinati) // 2
    if len(ordinati) % 2:
        return ordinati[meta]
    return (ordinati[meta - 1] + ordinati[meta]) / 2


def _pagelle(p: Paths) -> list[dict]:
    """Le pagelle, dalla PIU' RECENTE, fino a `FINESTRA_LETTURA`.

    Si legge largo e si stringe dopo, in `_scegli`: la finestra vera va
    applicata ai file SIMILI, non a tutti indistintamente.
    """
    try:
        righe = (p.logs / "esiti.jsonl").read_text().splitlines()
    except OSError:
        return []
    fuori: list[dict] = []
    for riga in reversed(righe):
        if len(fuori) >= FINESTRA_LETTURA:
            break
        try:
            dato = json.loads(riga)
        except ValueError:
            continue
        # Non basta che la riga sia JSON valido: `12345`, `null` e `[]` lo
        # sono, e su quelli la `.get()` di chi legge alza AttributeError —
        # cioe' l'intera pagina cade per una riga storta in un registro.
        # Trovato in audit il 12/08 provando un `esiti.jsonl` sporco.
        if isinstance(dato, dict):
            fuori.append(dato)
    return fuori


@dataclass(frozen=True)
class Correzione:
    """Di quanto sbagliamo di solito, e di quanto nei casi estremi."""

    attesa: float           # la mediana: corregge la stima centrale
    massimo: float          # il caso peggiore visto: alza il TETTO
    minimo: float           # il caso migliore visto: abbassa il PAVIMENTO
    campioni: int


def correzione(paths: Paths | None = None, *,
               simili_a: int | None = None) -> Correzione | None:
    """Quanto sbagliamo di solito, misurato: (fattore, quante lavorazioni).

    Le pagelle registrano sia il tempo PREVISTO sia quello impiegato: il
    loro rapporto dice cosa non stiamo contando (montaggio, controlli di
    chiusura, tempi morti fra un blocco e l'altro). Sulle prime lavorazioni
    misurate valeva circa 1.06, cioe' un 6% di lavoro reale che nessuna
    voce della stima copriva.

    Prende il posto del vecchio margine fisso del 25%: quello era un
    pudore deciso a occhio, questo e' uno scarto misurato che si aggiorna
    da solo. Mediana e non media, e un tetto largo, perche' una singola
    lavorazione andata storta non deve spostare le stime di tutte.
    """
    tutti: list[tuple[float, int]] = []
    for dato in _pagelle(paths or PATHS):
        reali, previsti = dato.get("secondi"), dato.get("previsti")
        try:
            r = float(reali) / float(previsti)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if 0.4 <= r <= 2.5:            # fuori di qui e' un caso anomalo
            fotogrammi = dato.get("fotogrammi")
            tutti.append((r, int(fotogrammi)
                          if isinstance(fotogrammi, int) else 0))
    return _scegli(tutti, simili_a, Correzione)


def _scegli(campioni: list[tuple[float, int]], simili_a: int | None, forma):
    """La mediana e gli estremi, presi dai file che somigliano a questo.

    Regola unica per la deduplica e per la correzione, perche' e' lo stesso
    problema: un file corto e uno lungo non si assomigliano in NIENTE, e
    mescolarli sposta la stima di tutti.

    Sulla correzione lo scarto e' misurato (12/08, nove pagelle di questa
    cartella): i sei episodi veri stanno fra 0,98 e 1,24, mediana 1,066; le
    tre clip di prova da uno-cinque minuti stanno a 1,21, 1,32 e 1,39, e
    tirano la mediana di tutti a 1,133. Il costo fisso di un blocco pesa
    quanto pesa su un file di due minuti, e quel peso non ha niente da dire
    su un episodio di ventiquattro. Il tetto poi veniva INTERAMENTE da una
    clip di prova.

    Tre regimi, come per la deduplica: due o piu' simili e si stima su
    quelli; UN solo simile e il centro lo decide lui mentre la forchetta
    resta larga; nessuno, e si torna a tutto quanto.
    """
    # La finestra si applica QUI, dopo aver scelto i simili, e non alla
    # lettura: stringerla prima significa che dieci prove corte di fila
    # buttano fuori tutti gli episodi veri, e il filtro di taglia non ha piu'
    # niente su cui lavorare (misurato in audit il 12/08).
    ovunque = [v for v, _ in campioni][:FINESTRA]
    simili = [v for v, n in campioni
              if simili_a is None
              or _somiglia(n, simili_a, BANDA_SOMIGLIANZA)][:FINESTRA]
    if len(simili) >= 2:
        return forma(attesa=_mediana(simili), minimo=min(simili),
                     massimo=max(simili), campioni=len(simili))
    if len(simili) == 1 and len(ovunque) >= 2:
        return forma(attesa=simili[0], minimo=min(ovunque),
                     massimo=max(ovunque), campioni=1)
    if len(ovunque) < 2:
        return None
    return forma(attesa=_mediana(ovunque), minimo=min(ovunque),
                 massimo=max(ovunque), campioni=len(ovunque))


# Le mappe gia' lette: cartella -> ((quando, quanto grande), misura). Una
# mappa si scrive una volta sola e non cambia piu', ma `deduplica` viene
# chiamata una volta PER FILE a ogni ridisegno della pagina: con venti file
# in elenco erano venti letture di un JSON da 113 KB per mostrare gli stessi
# numeri. Misurato: 0,73 ms a chiamata con una mappa viva, 1,45 con due.
#
# UNA voce per cartella, che si sostituisce da sola: la prima versione teneva
# la firma dentro la chiave e per ripulire le voci vecchie doveva SCORRERE il
# dizionario. L'interfaccia riesegue lo script in un thread per scheda
# aperta, e scorrere un dizionario mentre un altro thread ci scrive alza
# «dictionary changed size during iteration» — una pagina rossa ogni tanto,
# di quelle che non si riproducono mai a comando.
_MAPPE_LETTE: dict[str, tuple[tuple[int, int], tuple[float, int] | None]] = {}


def _misure_vive(p: Paths) -> list[tuple[float, int]]:
    """Le deduplica ESATTE dei file in lavorazione adesso.

    Un file che sta girando ha gia' la sua mappa completa su disco molto
    prima di finire, e quindi molto prima di lasciare una pagella. Aspettare
    la pagella significa lasciare la coda intera appesa allo storico anche
    quando il primo file dell'infornata ha gia' detto, misurando, che questo
    materiale non somiglia a quello di ieri.
    """
    # Import TARDIVO e non in testa: la catena e' monitor -> pipeline -> plan
    # -> storico, quindi in testa sarebbe un ciclo. Spostarlo di sopra rompe
    # l'avvio dell'app, non un test.
    from . import monitor
    fuori: list[tuple[float, int]] = []
    try:
        cartelle = sorted(d for d in p.work.iterdir() if d.is_dir())
    except OSError:
        return fuori
    for cartella in cartelle:
        try:
            st = (cartella / "dedup.json").stat()
        except OSError:
            continue
        firma = (st.st_mtime_ns, st.st_size)
        voce = _MAPPE_LETTE.get(str(cartella))
        if voce is None or voce[0] != firma:
            # Riletta solo se il file e' cambiato: una ripresa con soglia
            # diversa riscrive la mappa, e la vecchia non deve sopravviverle.
            voce = (firma, monitor.dedup_esatta(cartella))
            _MAPPE_LETTE[str(cartella)] = voce
        misura = voce[1]
        # La stessa scala pretesa dalle pagelle. Una mappa monca puo' dire
        # "tenuti zero fotogrammi", cioe' deduplica 1.0: un file che non
        # costa niente. Le pagelle quel valore lo scartano da sempre; le
        # misure vive entravano invece dritte nella mediana (audit del 12/08).
        if misura is not None and 0 <= misura[0] < 1:
            fuori.append(misura)
    return fuori


def _somiglia(fotogrammi: int, riferimento: int, banda: float) -> bool:
    """Due file si somigliano se durano piu' o meno uguale.

    E' l'unico discrimine che i dati sostengono. Misurato il 12/08 su
    dodici puntate di Koyomimonogatari (15.657-21.535 fotogrammi): deduplica
    fra il 25,7% e il 41,0%, mediana 32,4%, scarto tipico 4,7 punti — cioe'
    circa il 7% sul tempo. Tsukimonogatari, stesso studio e stessa
    risoluzione ma 34.765 fotogrammi, sta al 6,5%: ventisei punti piu' in
    la', ed e' il file che ha fatto sbagliare una stima del 47%.

    La durata li separa, la risoluzione no. Niente titoli, niente nomi di
    serie: solo il conteggio dei fotogrammi.
    """
    if riferimento <= 0:
        return True
    if fotogrammi <= 0:
        # Taglia ignota: NON e' un simile. Le pagelle vecchie non scrivevano
        # `fotogrammi`, e trattarle come simili a tutto rimetteva dentro
        # proprio i file che il filtro esiste per escludere — provato in
        # audit, una pagella senza taglia al 99% di deduplica entrava in una
        # richiesta per 17.000 fotogrammi e ne spostava il massimo. Restano
        # comunque disponibili per il ripiego, quando i simili non bastano.
        return False
    return riferimento / (1 + banda) <= fotogrammi <= riferimento * (1 + banda)


# Quanto puo' essere piu' lungo o piu' corto un file per contare ancora come
# "simile". Il 40% tiene insieme le dodici puntate di una serie (fra la piu'
# corta e la piu' lunga ballano gia' il 38%) e lascia fuori un film o una
# puntata doppia, che e' esattamente il caso che rompeva le stime.
BANDA_SOMIGLIANZA = 0.40


def deduplica(paths: Paths | None = None, *,
              simili_a: int | None = None) -> Deduplica | None:
    """La deduplica attesa per un file di `simili_a` fotogrammi.

    Due fonti, nell'ordine: le lavorazioni IN CORSO, che hanno la mappa
    esatta gia' pronta, e le pagelle dei file finiti. Poi il filtro di
    somiglianza: si stima su file che durano quanto questo, non su tutto
    quello che e' passato di qui (vedi `_somiglia` per i numeri che lo
    giustificano).

    Se dopo il filtro restano meno di due campioni si torna alla finestra
    intera: una forchetta larga costruita su tutto e' comunque meglio di una
    stretta costruita su niente.
    """
    p = paths or PATHS
    dalle_pagelle: list[tuple[float, int]] = []
    for dato in _pagelle(p):                # stessa finestra di `correzione`
        # Lo ZERO e' una misura legittima — "su questo file la deduplica
        # non ha trovato niente" — ed e' il caso peggiore, cioe' quello che
        # tiene onesto il tetto. Buttarlo restringeva la forchetta proprio
        # dove serviva larga. Le lavorazioni con deduplica SPENTA scrivono
        # `null` (vedi cli._scrivi_esito) e restano fuori da sole.
        quota = dato.get("dedup")
        if not isinstance(quota, (int, float)) or not 0 <= float(quota) < 1:
            continue
        fotogrammi = dato.get("fotogrammi")
        dalle_pagelle.append((float(quota),
                              int(fotogrammi) if isinstance(fotogrammi, int)
                              else 0))

    # Un file che ha finito CON AVVISI conserva la cartella di lavoro (e
    # quindi la sua mappa) e ha gia' lasciato una pagella: contato due volte
    # pesa il doppio degli altri sulla mediana. Provato in audit su quattro
    # episodi: la mediana passava da 0,340 a 0,320, cioe' un 3% sul tempo,
    # per un file solo rimasto sul disco.
    #
    # Si riconosce per conteggio dei fotogrammi E quota: il solo conteggio
    # non basta, due puntate della stessa serie possono averlo identico
    # (Koyomimonogatari 01 e 02 hanno entrambe 19.712 fotogrammi, con
    # deduplica 41,0% e 35,9%).
    gia_viste = {(n, round(q, 3)) for q, n in dalle_pagelle}
    vive = [(q, n) for q, n in _misure_vive(p)
            if (n, round(q, 3)) not in gia_viste]
    # Le vive davanti: sono le piu' recenti, e la finestra si conta da li'.
    tutti = vive + dalle_pagelle

    # Stessa regola della correzione, scritta una volta sola: su
    # Tsukimonogatari 02 il ripiego alla mediana di tutti significherebbe
    # stimare col 29% delle puntate invece che col 6,5% misurato sull'unico
    # film della stessa taglia — cioe' rifare l'errore del 47%.
    return _scegli(tutti, simili_a, Deduplica)
