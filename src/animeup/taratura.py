"""Taratura delle stime: un cronometro su QUESTA macchina, non un'inferenza.

Le stime a priori si reggono su tre numeri misurati sul Mac dove AnimeUp è
nato: i Mpx/s di ogni modello (catalogo), i 60 fotogrammi/s dell'estrazione
e gli 8 fotogrammi/s della codifica x265 a 1080p (plan.py). Su una macchina
diversa sbagliano tutti dello stesso fattore: la velocità del chip.

Qui si misurano quegli stessi numeri con un benchmark controllato sul clip
libero di campioni/ (Big Buck Bunny, CC-BY): ogni combinazione modello x
scala viene cronometrata sul filesystem — dal primo all'ultimo PNG
prodotto, così il caricamento del modello resta fuori dal conto (era già
successo: un campione breve aveva fatto misurare 0.57 Mpx/s a un modello
che in produzione ne fa 0.85, vedi models.py).

Il risultato vive in records/calibration.json, chiavato sul CHIP: una copia
della cartella portata su un altro Mac non sporca le stime di nessuno,
perché ogni macchina legge solo la propria voce.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .i18n import t
from .models import CATALOG
from . import su_disco
from .paths import PATHS, Paths

CLIP = "bbb-480p.mkv"
# Quanti fotogrammi del clip cronometrare per ogni combinazione: abbastanza
# da diluire il rumore di misura, pochi abbastanza da chiudere l'intero giro
# in ~10 minuti sul Mac di riferimento.
FOTOGRAMMI_MISURA = 180

# I thread di SALVATAGGIO da provare (il terzo numero di `-j` di ncnn). Il
# tetto dei ~20 Mpx/s in uscita misurato su due Mac diversi non era la GPU:
# era la scrittura dei PNG, uguale su ogni macchina perche' il valore stava
# scritto nel codice. Quanti ne servano dipende dal rapporto fra GPU e core,
# quindi si misura per macchina invece di deciderlo una volta per tutte.
#
# La griglia si e' allargata dopo una misura: sul Mac mini (10 core) il ritmo
# e' PIATTO oltre il 4 — 4.507, 4.485, 4.437 per 4, 6, 8 — quindi il 4 e' un
# ottimo vero. Sul MacBook (14 core) invece saliva ancora fino all'estremo:
# 3.241, 6.135, 8.927, 9.97 per 2, 4, 6, 8. L'8 non era il punto migliore,
# era l'ultimo che provavamo, e su una macchina veloce ci stavamo lasciando
# indietro throughput senza accorgercene.
SALVATAGGIO_DA_PROVARE = (2, 4, 6, 8, 12, 16)
# Non si provano piu' thread di salvataggio di quanti core ha la macchina:
# oltre quel punto si contendono gli stessi core e non c'e' niente da
# guadagnare, e su una macchina piccola le prove inutili allungano il giro.
# Il valore di partenza: quello scritto in backend.upscale_dir.
SALVATAGGIO_PREDEFINITO = 4
# Sotto questo guadagno non si cambia: fra due misure brevi ballano sempre
# un paio di punti, e cambiare un parametro di produzione per rumore e' il
# modo migliore di peggiorare le cose credendo di migliorarle.
GUADAGNO_MINIMO = 0.05
# La prova si fa dove il salvataggio MORDE: animevideov3 a scala 4 e' il caso
# in cui il tetto e' stato trovato. Su CUGAN comanda la GPU e i thread non
# cambiano niente (misurato), quindi provarli li' sarebbe tempo buttato.
PROVA_SALVATAGGIO = ("animevideov3", 4)
# Meno fotogrammi del giro principale: il confronto e' RELATIVO, e quattro
# prove da 180 raddoppierebbero la durata della taratura.
FOTOGRAMMI_SALVATAGGIO = 80


def core() -> int:
    """Quanti core ha questa macchina. Serve a non chiedere a ncnn piu'
    thread di salvataggio di quanti ce ne siano: e' il tetto fisico."""
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:      # noqa: BLE001
        return 1


def salvataggio_predefinito() -> int:
    """Quanti thread usare su una macchina MAI tarata.

    Non e' un numero prudente per finta: 4 e' l'ottimo MISURATO su due chip
    diversi (M4 e M3 Pro), con uscita bit-identica verificata, e su entrambi
    va meglio di 2 — del 48% e del 93%. Restare a 2 "per prudenza"
    significherebbe regalare un terzo del tempo a ogni lavorazione su ogni
    macchina nuova, cioe' scegliere un danno certo per evitarne uno ipotetico.
    L'unico limite vero e' fisico: mai piu' thread che core.
    """
    return min(SALVATAGGIO_PREDEFINITO, core())


def candidati_salvataggio() -> list[int]:
    """I valori di thread che la taratura proverà su QUESTA macchina.

    Una fonte sola, letta sia da chi esegue le prove sia da chi stima quanto
    dureranno: quando i due conti stavano in due posti, la barra prometteva
    quattro prove e il giro ne faceva sei.

    Dentro ci sono sempre due valori oltre alla griglia: il predefinito, che
    è il metro di paragone senza il quale nessun candidato è giudicabile, e
    il numero di core, che è il limite fisico — se vince quello, l'ottimo non
    è fuori dalla griglia, è dove finisce la macchina.
    """
    return sorted({n for n in SALVATAGGIO_DA_PROVARE if n <= core()}
                  | {salvataggio_predefinito(), core()})


def chip() -> str:
    """Il nome del chip, l'identità della macchina ai fini della velocità."""
    try:
        esito = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=5,
        )
        nome = esito.stdout.strip()
        if nome:
            return nome
    except (OSError, subprocess.TimeoutExpired):
        pass
    import platform
    return platform.machine() or "sconosciuto"


def _combinazioni() -> list[tuple]:
    return [(chiave, modello, scala)
            for chiave, modello in CATALOG.items()
            for scala in modello.scales]


def _misura_clip(p: Paths, sorgente: Path) -> tuple[int, int, int]:
    """Larghezza, altezza e fotogrammi del clip campione."""
    esito = subprocess.run(
        [str(p.ffprobe.path), "-v", "error", "-select_streams", "v:0",
         "-count_packets", "-show_entries",
         "stream=width,height,nb_read_packets", "-of", "csv=p=0",
         str(sorgente)],
        capture_output=True, text=True, check=True,
    )
    larghezza, altezza, pacchetti = (
        int(x) for x in esito.stdout.strip().split(",")[:3])
    return larghezza, altezza, pacchetti


def preventivo(paths: Paths | None = None, *,
               clip: Path | None = None) -> list[tuple[str, float]]:
    """Le tappe del giro, ciascuna col suo costo atteso in secondi.

    Serve a due cose: muovere la barra in proporzione al LAVORO (i nove
    passi durano tempi molto diversi) e dire quanto manca. I numeri sono
    quelli di fabbrica, o la taratura precedente se c'è: sbagliati quanto
    si vuole: chi guarda il cronometro li rimette in riga strada facendo.
    """
    p = paths or PATHS
    sorgente = clip or (p.campioni / CLIP)
    larghezza, altezza, pacchetti = _misura_clip(p, sorgente)
    src_mpx = larghezza * altezza / 1_000_000
    n_previsto = min(FOTOGRAMMI_MISURA, pacchetti)
    nota = carica(p) or {}

    tappe = [(t("mot.taratura.tappa_estrazione"),
              pacchetti / float(nota.get("estrazione_fps") or 60.0))]
    # La prova dei thread di salvataggio: quattro giri sullo stesso lotto
    # ridotto. Il costo si stima con lo stesso ritmo del modello che usa.
    _chiave_prova, _scala_prova = PROVA_SALVATAGGIO
    _ritmo_prova = (nota.get("mpxs", {}).get(_chiave_prova, {})
                    .get(str(_scala_prova))
                    or CATALOG[_chiave_prova].throughput.get(_scala_prova, 1.0))
    _quante_prove = len(candidati_salvataggio()) or 1
    tappe.append((t("mot.taratura.tappa_salvataggio"),
                  _quante_prove * FOTOGRAMMI_SALVATAGGIO
                  * src_mpx / float(_ritmo_prova)))
    for chiave, modello, scala in _combinazioni():
        ritmo = (nota.get("mpxs", {}).get(chiave, {}).get(str(scala))
                 or modello.throughput.get(
                     scala, min(modello.throughput.values())))
        tappe.append((t("mot.taratura.tappa_upscale", modello=modello.short,
                        scala=scala),
                      n_previsto * src_mpx / float(ritmo)))
    tappe.append((t("mot.taratura.tappa_codifica"),
                  n_previsto / float(nota.get("codifica_fps") or 8.0)))
    tappe.append((t("mot.taratura.tappa_scansione"),
                  pacchetti / float(nota.get("scansione_fps") or 200.0)))
    return tappe


def in_corso(paths: Paths | None = None) -> bool:
    """C'è già un giro di taratura in volo su questa macchina?

    Chiudere la finestra non ferma il giro: prosegue in sottofondo fino a
    salvare. Senza questa guardia bastava riaprirla e premere Avvia per
    averne due insieme, che si rubano la GPU (misure false) e si
    cancellano la cartella di lavoro a vicenda.
    """
    import os

    p = paths or PATHS
    marcatore = p.work / ".calibration" / "running.lock"
    try:
        pid = int(marcatore.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _file(p: Paths) -> Path:
    return p.taratura


def carica(paths: Paths | None = None, *, macchina: str | None = None) -> dict | None:
    """La voce di taratura di QUESTA macchina, o None se non è mai stata fatta."""
    p = paths or PATHS
    try:
        dati = su_disco.leggi(_file(p))
    except (OSError, ValueError):
        return None
    voce = dati.get("macchine", {}).get(macchina or chip())
    return voce if isinstance(voce, dict) else None


def throughput(model_key: str, scale: int,
               paths: Paths | None = None) -> float | None:
    """Mpx/s misurati per modello+scala su questa macchina, se esistono."""
    voce = carica(paths)
    if not voce:
        return None
    valore = voce.get("mpxs", {}).get(model_key, {}).get(str(scale))
    try:
        return float(valore) if valore else None
    except (TypeError, ValueError):
        return None


def frase_salvataggio(voce: dict | None) -> str:
    """Cosa dire, a fine taratura, sui thread di salvataggio.

    Non e' un numero che serve a lavorare: serve a capire PERCHE' questa
    macchina va cosi'. Quindi si mostra dove la taratura riferisce, e li'
    soltanto — infilato in una barra di stato sarebbe rumore.

    Non solleva mai: la legge anche l'interfaccia, e un registro ritoccato a
    mano non deve portare giu' una pagina. E non dichiara confronti che non
    sono avvenuti: se il predefinito non e' stato misurato, il paragone non
    c'e' stato e non si finge il contrario (audit del 2026-08-10).
    """
    if not isinstance(voce, dict):
        return ""
    scelti = voce.get("jobs_salvataggio")
    if not isinstance(scelti, int) or isinstance(scelti, bool):
        return ""
    ritmi: dict[int, float] = {}
    for x in (voce.get("prove_salvataggio") or []):
        if not isinstance(x, dict):
            continue
        n, r = x.get("thread"), x.get("ritmo")
        if (isinstance(n, int) and not isinstance(n, bool)
                and isinstance(r, (int, float)) and not isinstance(r, bool)
                and r > 0):
            ritmi[int(n)] = float(r)
    if not ritmi:
        return ""

    elenco = ", ".join(str(k) for k in sorted(ritmi))
    testa = t("mot.taratura.salvataggio_testa", thread=scelti)
    predefinito = salvataggio_predefinito()
    base = ritmi.get(predefinito)
    if base is None:
        # Il metro di paragone non e' stato misurato: nessun confronto e'
        # avvenuto, e dirlo e' l'unica cosa onesta.
        return t("mot.taratura.salvataggio_senza_base", testa=testa)
    if int(scelti) == predefinito:
        migliore = max(ritmi, key=lambda k: ritmi[k])
        if migliore != predefinito:
            return t("mot.taratura.salvataggio_poco", testa=testa, provati=elenco,
                     guadagno=f"{ritmi[migliore] / base - 1:.0%}")
        return t("mot.taratura.salvataggio_nessuno", testa=testa, provati=elenco)
    if int(scelti) in ritmi:
        return t("mot.taratura.salvataggio_cambiato", testa=testa,
                 predefinito=predefinito,
                 guadagno=f"{ritmi[int(scelti)] / base - 1:+.0%}")
    return testa


def _ritmo_da_mtime(cartella: Path, secondi_totali: float) -> float:
    """Fotogrammi al secondo, misurati dal primo all'ultimo PNG scritto.

    Il tempo di parete include il caricamento del modello (secondi, contro
    i minuti di lavoro): su un campione breve lo gonfia abbastanza da
    falsare la misura. Le date di modifica dei file raccontano invece solo
    il lavoro vero. Se il filesystem non collabora (date identiche), si
    ripiega sul tempo di parete: pessimista ma mai inventato.
    """
    tempi = sorted(f.stat().st_mtime for f in cartella.glob("*.png"))
    if len(tempi) < 2:
        return 0.0
    ampiezza = tempi[-1] - tempi[0]
    if ampiezza <= 0:
        return len(tempi) / secondi_totali if secondi_totali > 0 else 0.0
    return (len(tempi) - 1) / ampiezza


def esegui(paths: Paths | None = None, *, clip: Path | None = None,
           avanzamento=None) -> dict:
    """Il benchmark completo. Ritorna (e salva) la voce di questa macchina.

    `avanzamento(etichetta, indice, totale, frazione, resta)` tiene
    informato chi guarda: `frazione` e `resta` (secondi) nascono da un
    preventivo per passo, non dal loro conteggio — i nove passi durano
    tempi molto diversi fra loro, e una barra a scatti uguali direbbe 55%
    quando il lavoro vero e' a un terzo.
    """
    p = paths or PATHS
    sorgente = clip or (p.campioni / CLIP)
    if not sorgente.is_file():
        raise FileNotFoundError(t("mot.taratura.clip_mancante", percorso=sorgente,
                                  clip=CLIP))
    if in_corso(p):
        raise RuntimeError(t("mot.taratura.gia_in_corso"))

    # Accanto alle lavorazioni vere, sullo stesso disco: i thread di
    # salvataggio misurati qui valgono per i fotogrammi scritti in JOBS.
    lavoro = p.work / ".calibration"
    shutil.rmtree(lavoro, ignore_errors=True)
    (lavoro / "frames").mkdir(parents=True)
    (lavoro / "running.lock").write_text(str(os.getpid()))
    try:
        return _giro(p, sorgente, lavoro, avanzamento)
    finally:
        # Il marcatore non deve sopravvivere a un errore: dentro c'è il PID
        # del SERVER, che resta vivo, e una guardia inchiodata bloccherebbe
        # ogni taratura futura fino al riavvio.
        shutil.rmtree(lavoro, ignore_errors=True)


def _impronta(cartella: Path, quanti: int = 6) -> list[str] | None:
    """L'impronta dei primi PNG prodotti: serve a dimostrare che i thread
    cambiano SOLO la velocita'.

    Piu' thread di salvataggio non devono toccare un pixel. E' gia' stato
    verificato a mano fra 2 e 4 (bit-identici su dieci fotogrammi), ma qui il
    valore lo sceglie la macchina da sola: la prova va rifatta ogni volta,
    perche' un'uscita diversa da quella di riferimento e' l'unico modo in cui
    questa funzione potrebbe fare danno.
    """
    import hashlib

    tutti = sorted(cartella.glob("*.png"))
    if not tutti:
        return None
    # Le DIMENSIONI di tutti i file, a costo di uno `stat` a testa. Attenzione
    # a cosa dimostra: due PNG identici hanno per forza la stessa dimensione,
    # quindi una dimensione diversa e' la prova certa di un'uscita diversa —
    # ma non vale il contrario, e due file diversi della stessa dimensione
    # sfuggono. Copre il caso realistico (un PNG rigenerato cambia quasi
    # sempre dimensione) e lascia scoperto lo scambio di contenuto a parita'
    # di byte, per cui restano i campioni crittografici.
    try:
        misure = ",".join(f"{f.name}:{f.stat().st_size}" for f in tutti)
    except OSError:
        return None
    # SPARSI su tutto il lotto, primo e ULTIMO compresi: una race di
    # scrittura si manifesta a regime, e i primi fotogrammi sono i meno
    # esposti di tutti. (Il passo semplice `[::len//quanti]` lasciava fuori
    # proprio la coda del lotto — scoperto da un test.)
    n = min(quanti, len(tutti))
    if n == 1:
        scelti = [tutti[0]]
    else:
        ultimo = len(tutti) - 1
        indici = sorted({round(i * ultimo / (n - 1)) for i in range(n)})
        scelti = [tutti[i] for i in indici]
    fuori = [hashlib.sha1(misure.encode()).hexdigest()]
    for f in scelti:
        try:
            fuori.append(hashlib.sha1(f.read_bytes()).hexdigest())
        except OSError:
            # None e non []: "non ho potuto verificare" e' diverso da "ho
            # verificato e non c'era niente", e qui la differenza decide se
            # un valore entra in produzione.
            return None
    return fuori


def _prova_salvataggio(p: Paths, frames: Path,
                       lavoro: Path) -> tuple[int, list[dict]]:
    """Quanti thread di salvataggio rendono di piu' su questa macchina.

    Si prova dove il salvataggio morde davvero (animevideov3 x4) e si
    confrontano ritmi misurati sullo STESSO lotto di fotogrammi. Tre guardie,
    perche' questo valore finisce in produzione:
      - il vincitore deve battere il predefinito di almeno il GUADAGNO_MINIMO,
        o si tiene il predefinito: due misure brevi ballano sempre di qualche
        punto, e inseguire il rumore peggiora le cose;
      - l'uscita deve essere BIT-IDENTICA a quella del predefinito, o il
        valore si scarta comunque;
      - una prova che non produce tutti i fotogrammi non entra nel confronto.
    """
    from .backend import upscale_dir

    chiave, scala = PROVA_SALVATAGGIO
    modello = CATALOG[chiave]
    campione = lavoro / "campione-salv"
    campione.mkdir(exist_ok=True)
    for f in sorted(frames.glob("*.png"))[:FOTOGRAMMI_SALVATAGGIO]:
        try:
            (campione / f.name).hardlink_to(f)
        except OSError:
            shutil.copy2(f, campione / f.name)
    attesi = sum(1 for _ in campione.glob("*.png"))
    if not attesi:
        return salvataggio_predefinito(), []

    prove: list[dict] = []
    riferimento: list[str] = []
    # Il predefinito ci deve stare SEMPRE: e' il metro di paragone, e senza
    # la sua misura nessun candidato puo' essere giudicato — su una macchina
    # con meno di quattro core si facevano prove il cui esito era scartato in
    # partenza.
    # Fra i candidati c'e' SEMPRE anche il numero di core. Costa una prova e
    # compra una certezza: se a vincere e' quello, l'ottimo non sta fuori
    # dalla griglia ma sul limite della macchina, e non c'e' altro da
    # cercare. Senza, un migliore che cade sull'ultimo valore provato non si
    # distingue da un ottimo vero — ed e' esattamente l'equivoco in cui siamo
    # caduti col MacBook, dove l'8 sembrava una scelta e invece era un bordo.
    da_provare = candidati_salvataggio()
    for quanti in da_provare:
        dst = lavoro / f"salv-{quanti}"
        shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True)
        inizio = time.monotonic()
        try:
            upscale_dir(campione, dst, scale=scala, model=modello, paths=p,
                        jobs=f"2:2:{quanti}")
        except Exception:          # noqa: BLE001 - una prova storta non ferma la taratura
            shutil.rmtree(dst, ignore_errors=True)
            prove.append({"thread": quanti, "ritmo": None, "nota": "fallita"})
            continue
        durata = time.monotonic() - inizio
        try:
            fatti = sum(1 for _ in dst.glob("*.png"))
            if fatti < attesi:
                shutil.rmtree(dst, ignore_errors=True)
                prove.append({"thread": quanti, "ritmo": None,
                              "nota": f"incompleta ({fatti}/{attesi})"})
                continue
            # Anche queste due leggono il disco, e su un disco esterno una
            # lettura puo' fallire: fuori dal `try` una prova storta fermava
            # l'INTERA taratura, contro quello che il commento prometteva.
            ritmo = _ritmo_da_mtime(dst, durata)
            impronta = _impronta(dst)
        except OSError:
            shutil.rmtree(dst, ignore_errors=True)
            prove.append({"thread": quanti, "ritmo": None,
                          "nota": "lettura fallita"})
            continue
        # Il predefinito EFFETTIVO, non la costante: su una macchina con
        # meno di quattro core il valore provato e' un altro, il riferimento
        # non veniva mai raccolto e l'intera prova — minuti di GPU — era
        # buttata (audit del 2026-08-10, quinto giro).
        if quanti == salvataggio_predefinito():
            riferimento = impronta
        prove.append({"thread": quanti, "ritmo": round(ritmo, 3),
                      "impronta": impronta})
        shutil.rmtree(dst, ignore_errors=True)

    shutil.rmtree(campione, ignore_errors=True)

    return _scegli_salvataggio(prove, riferimento), prove


def _scegli_salvataggio(prove: list[dict], riferimento: list[str] | None) -> int:
    """La regola di scelta, separata dalla misura per poterla provare.

    Le guardie, e stavolta scritte in modo che NON possano spegnersi da sole
    (audit del 2026-08-10: nella prima versione bastava che una lettura di
    disco fallisse perche' il controllo sull'uscita smettesse di controllare,
    in silenzio, e un valore con uscita corrotta finisse in produzione):

      1. senza una misura VALIDA del predefinito non si cambia niente;
      2. senza l'impronta del predefinito non si cambia niente — "non ho
         potuto verificare" non e' "ho verificato ed e' uguale";
      3. un candidato senza impronta, o con impronta diversa, e' scartato;
      4. si giudica sempre rispetto al PREDEFINITO, mai rispetto al miglior
         candidato di turno: cosi' l'esito non dipende dall'ordine delle
         prove (prima le stesse misure davano 6 o 8 a seconda di come erano
         elencate).
    """
    def _numero(x: object) -> float | None:
        """Un numero VERO: niente booleani (in Python sono interi), niente
        NaN, niente infiniti. `int(inf)` solleva OverflowError, che non e'
        ne' TypeError ne' ValueError e passerebbe indenne."""
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else None

    def _ritmo(n: int) -> float:
        for v in prove:
            r = _numero(v.get("ritmo"))
            if v.get("thread") == n and r and r > 0:
                return r
        return 0.0

    predefinito = salvataggio_predefinito()
    base = _ritmo(predefinito)
    # `riferimento` dev'essere una LISTA con dentro qualcosa: `_impronta`
    # torna None quando non ha potuto verificare, e senza quel controllo un
    # None arrivava a `list()` e sollevava.
    if not base or not isinstance(riferimento, (list, tuple)) or not riferimento:
        return predefinito

    migliore, ritmo_migliore = predefinito, base
    for v in prove:
        n_thread = _numero(v.get("thread"))
        if n_thread is None or n_thread < 1:
            continue
        quanti = int(n_thread)
        r = _numero(v.get("ritmo"))
        if r is None or r <= 0:
            continue
        # Il confronto e' SEMPRE con la base, non con `ritmo_migliore`.
        if float(r) < base * (1 + GUADAGNO_MINIMO):
            continue
        impronta = v.get("impronta")
        # Solo liste: una stringa passerebbe da `list()` sciolta in
        # caratteri e potrebbe combaciare per caso con un riferimento
        # di quella forma.
        if not isinstance(impronta, (list, tuple)) or not impronta \
                or list(impronta) != list(riferimento):
            v["nota"] = ("uscita non verificabile: scartata" if not impronta
                         else "uscita diversa: scartata")
            continue
        if float(r) > ritmo_migliore:
            migliore, ritmo_migliore = quanti, float(r)
    return migliore


def _giro(p: Paths, sorgente: Path, lavoro: Path, avanzamento) -> dict:
    """Il giro vero e proprio. Chiamalo solo da `esegui`, che tiene la
    guardia e ripulisce la cartella di lavoro in ogni caso."""

    combinazioni = _combinazioni()
    larghezza, altezza, _ = _misura_clip(p, sorgente)
    src_mpx = larghezza * altezza / 1_000_000
    costi = [costo for _, costo in preventivo(p, clip=sorgente)]
    costo_totale = sum(costi) or 1.0

    passi = len(costi)
    passo = 0
    partenza = time.monotonic()

    def _di(etichetta: str) -> None:
        nonlocal passo
        passo += 1
        if not avanzamento:
            return
        fatto = sum(costi[:passo - 1])
        speso = time.monotonic() - partenza
        # Il preventivo tarato su quanto e' andata finora: se questo Mac va
        # il doppio del previsto, dal secondo passo lo dice.
        fattore = speso / fatto if fatto > 0 and speso > 0 else 1.0
        resta = (costo_totale - fatto) * fattore
        avanzamento(etichetta, passo, passi, fatto / costo_totale, resta)

    # --- 1. estrazione: gli stessi flag della produzione (encode.py) -------
    _di(t("mot.taratura.tappa_estrazione"))
    frames = lavoro / "frames"
    inizio = time.monotonic()
    subprocess.run(
        [str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-nostdin", "-y",
         "-i", str(sorgente),
         "-fps_mode", "cfr", "-r", "30",
         "-an", "-sn", "-dn",
         "-pix_fmt", "rgb24", "-sws_flags", "full_chroma_int+accurate_rnd",
         "-c:v", "png", "-pred", "mixed",
         str(frames / "%08d.png")],
        check=True, capture_output=True,
    )
    durata_estrazione = time.monotonic() - inizio
    estratti = sum(1 for _ in frames.glob("*.png"))
    if not estratti:
        raise RuntimeError(t("mot.taratura.estrazione_fallita"))
    fps_estrazione = estratti / durata_estrazione

    # Il sottoinsieme cronometrato: hard link, costo zero.
    campione = lavoro / "campione"
    campione.mkdir()
    for f in sorted(frames.glob("*.png"))[:FOTOGRAMMI_MISURA]:
        try:
            (campione / f.name).hardlink_to(f)
        except OSError:
            shutil.copy2(f, campione / f.name)
    n_campione = sum(1 for _ in campione.glob("*.png"))

    # --- 2. thread di salvataggio: quanti ne vuole QUESTA macchina ---------

    from .backend import upscale_dir
    _di(t("mot.taratura.tappa_salvataggio"))
    salvataggio, prove_salvataggio = _prova_salvataggio(p, frames, lavoro)

    # --- 3. upscale: ogni combinazione modello x scala ----------------------

    mpxs: dict[str, dict[str, float]] = {}
    cartella_per_codifica: Path | None = None
    for chiave, modello, scala in combinazioni:
        _di(t("mot.taratura.tappa_upscale", modello=modello.short, scala=scala))
        dst = lavoro / f"up-{chiave}-x{scala}"
        inizio = time.monotonic()
        upscale_dir(campione, dst, scale=scala, model=modello, paths=p,
                    jobs=f"2:2:{salvataggio}")
        durata = time.monotonic() - inizio
        fatti = sum(1 for _ in dst.glob("*.png"))
        if fatti < n_campione:
            raise RuntimeError(t("mot.taratura.upscale_incompleto",
                                 modello=modello.label, scala=scala,
                                 fatti=fatti, attesi=n_campione))
        ritmo = _ritmo_da_mtime(dst, durata)
        mpxs.setdefault(chiave, {})[str(scala)] = round(ritmo * src_mpx, 3)
        # La scala 3 di ESRGAN produce ~1440p: il campione giusto per la
        # codifica (che in produzione parte dall'uscita del modello e
        # scala a 1080p dentro x265). Le altre cartelle si buttano subito:
        # 180 PNG upscalati pesano centinaia di MB l'una.
        if chiave == "animevideov3" and scala == 3:
            cartella_per_codifica = dst
        else:
            shutil.rmtree(dst, ignore_errors=True)

    # --- 4. codifica: x265 coi parametri di produzione, uscita 1080p --------
    _di(t("mot.taratura.tappa_codifica"))
    fps_codifica = 0.0
    if cartella_per_codifica is not None:
        uscita = lavoro / "codifica.mkv"
        inizio = time.monotonic()
        subprocess.run(
            [str(p.ffmpeg.path), "-hide_banner", "-v", "error", "-nostdin",
             "-y", "-framerate", "30",
             "-i", str(cartella_per_codifica / "%08d.png"),
             # Lo specchio di encode.encode_segment: scala a 1080p nella
             # stessa passata, stesso codec/preset/profondità. (Qui manca la
             # coreografia dei tag colore, che non sposta il cronometro.)
             "-vf", "scale=1920:1080:flags=lanczos",
             "-c:v", "libx265", "-pix_fmt", "yuv420p10le",
             "-preset", "slower", "-crf", "18",
             "-an", "-sn", str(uscita)],
            check=True, capture_output=True,
        )
        durata = time.monotonic() - inizio
        if durata > 0:
            fps_codifica = n_campione / durata

    # --- 5. la scansione che misura i fotogrammi ripetuti ------------------
    _di(t("mot.taratura.tappa_scansione"))
    # Si misura sui fotogrammi GIA' ESTRATTI, esattamente come in
    # produzione: e' la stessa chiamata che fa la pipeline.
    fps_scansione = 0.0
    inizio = time.monotonic()
    try:
        from . import dedup as dd
        differenze = dd.measure_frame_differences(frames, paths=p)
    except (OSError, ValueError, RuntimeError):
        differenze = []
    durata = time.monotonic() - inizio
    if differenze and durata > 0:
        fps_scansione = len(differenze) / durata

    voce = {
        "quando": time.time(),
        "clip": sorgente.name,
        "fotogrammi_misura": n_campione,
        # La risoluzione del clip, in megapixel: estrazione e scansione
        # costano in proporzione ai pixel, e senza questo riferimento i loro
        # ritmi finivano applicati tali e quali a un 720p o a un 1080p.
        "mpx_misura": round(src_mpx, 4),
        "estrazione_fps": round(fps_estrazione, 1),
        "codifica_fps": round(fps_codifica, 2),
        "scansione_fps": round(fps_scansione, 1),
        "mpxs": mpxs,
        # Quanti thread di salvataggio vuole questa macchina, e le misure da
        # cui esce: chi rilegge il file deve poter rifare il ragionamento.
        "jobs_salvataggio": salvataggio,
        "prove_salvataggio": prove_salvataggio,
    }

    try:
        dati = su_disco.leggi(_file(p))
    except (OSError, ValueError):
        dati = {}
    dati.setdefault("versione", 1)
    dati.setdefault("macchine", {})[chip()] = voce
    p.logs.mkdir(parents=True, exist_ok=True)
    provvisorio = _file(p).with_suffix(".json.tmp")
    provvisorio.write_text(su_disco.dumps(dati, indent=2))
    provvisorio.replace(_file(p))

    return voce


# --- la taratura in un processo suo --------------------------------------
# Come il confronto: girava dentro la pagina, e un ricaricamento (o la
# sessione del browser che si chiude) poteva fermarla a meta'. Ora la pagina
# lancia `animeup taratura --fondo` staccato dalla sessione e legge a che
# punto e' da `cache/calibration-status.json`.

IN_CORSO, FINITA, FALLITA, INTERROTTA = "running", "done", "failed", "interrupted"


def file_stato(p: Paths | None = None) -> Path:
    return (p or PATHS).cache / "calibration-status.json"


def scrivi_stato(dati: dict, p: Paths | None = None) -> None:
    f = file_stato(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = f.with_name(f.name + f".{os.getpid()}.tmp")
    provvisorio.write_text(json.dumps(dati, ensure_ascii=False, indent=1))
    provvisorio.replace(f)


def stato_fondo(p: Paths | None = None) -> dict | None:
    """L'ultima taratura lanciata dalla pagina: in corso, finita o fallita.

    Una che risulta in corso ma il cui processo non c'e' piu' (Mac spento,
    processo ucciso) e' `interrupted`: non ha salvato niente.
    """
    try:
        dati = json.loads(file_stato(p).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict):
        return None
    if dati.get("state") == IN_CORSO:
        try:
            os.kill(int(dati.get("pid") or 0), 0)
        except (ProcessLookupError, ValueError):
            dati["state"] = INTERROTTA
        except OSError:
            pass
    return dati


def avvia_fondo(p: Paths | None = None) -> bool:
    """Lancia `animeup taratura --fondo`. False se una gira gia'."""
    from .paths import code_root

    p = p or PATHS
    s = stato_fondo(p)
    if in_corso(p) or (s and s.get("state") == IN_CORSO):
        return False
    try:
        tappe = [[nome, costo] for nome, costo in preventivo(p)]
    except (OSError, ValueError, subprocess.CalledProcessError):
        tappe = []
    scrivi_stato({"state": IN_CORSO, "pid": 0, "started": time.time(),
                  "steps": tappe, "index": 0, "total": len(tappe),
                  "fraction": 0.0, "left": None, "label": "",
                  "previous": carica(p), "new": None, "error": ""}, p)
    log = p.cache / "calibration.log"
    with log.open("w") as fh:
        proc = subprocess.Popen([str(code_root() / "animeup"), "taratura", "--fondo"],
                                stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    s = stato_fondo(p) or {}
    if not s.get("pid"):
        s["pid"] = proc.pid
        scrivi_stato(s, p)
    return True
