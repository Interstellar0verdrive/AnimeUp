"""Orchestrazione della lavorazione a blocchi.

Perché a blocchi: un episodio da 14 minuti a 1080p produce circa 280 GB di
fotogrammi upscalati. Lavorando a blocchi il picco scende a poche decine di
GB, un'interruzione non costa tutto il lavoro fatto, e un guasto emerge dopo
minuti invece che dopo ore.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import dedup as dd
from . import su_disco
from . import encode as enc
from .backend import upscale_dir
from .i18n import t
from .paths import PATHS, Paths, gb_liberi
from .plan import Plan


@dataclass
class Progress:
    """Callback di avanzamento, tutti opzionali."""

    stage: object = None          # (nome_fase: str, dettaglio: str) -> None
    chunk: object = None          # (indice, totale, fatti, totali_frame) -> None

    def say(self, name: str, detail: str = "") -> None:
        if self.stage:
            self.stage(name, detail)

    def step(self, index: int, total: int, done: int, frames: int) -> None:
        if self.chunk:
            self.chunk(index, total, done, frames)


@dataclass
class JobResult:
    output: Path
    frames_expected: int
    frames_written: int
    geometry: str
    seconds: float
    dedup_saving: float
    audit_violations: int
    # Quante volte il file e' stato lavorato in tutto (1 = passata dritta).
    # NON e' un avviso: `JobResult.ok` deve restare vero, o la CLI non
    # pulirebbe piu' la cartella di lavoro di nessun file interrotto.
    riprese: int = 1
    warnings: list[str] = field(default_factory=list)
    # Difetti del FILE PRODOTTO, tenuti separati dagli avvisi: un avviso può
    # essere una nota sul sorgente e non impedisce di tenere il risultato, un
    # difetto invece rende il file inservibile e va trattato come un guasto.
    difetti: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Si può cancellare la cartella di lavoro.

        Conta un DIFETTO, non un avviso. Prima qui c'era anche
        `not self.warnings`, e voleva dire che una nota qualsiasi conservava
        per sempre tutti i fotogrammi sorgente estratti: 31 GB per un
        episodio da 24 minuti a 720p, 156 per un film da due ore, 350 a
        1080p. L'unico avviso comparso finora nei registri è «Durata in parte
        stimata: il file è stato interrotto e ripreso» — una nota sul
        CRONOMETRO che si portava dietro trenta giga.

        Lo scenario, descritto da Interstellar0verdrive prima che lo verificassi: una coda
        di tre film, i primi due chiudono con un avviso, e il terzo trova il
        disco pieno. Non è un crash — il controllo di spazio lo rifiuta prima
        di estrarre — ma la catena scrive «Fallito» e prosegue col prossimo,
        che fallisce uguale: una coda che muore in piedi, e te ne accorgi la
        mattina dopo.

        La distinzione giusta era già qui accanto e non era usata: `difetti`
        significa che il file prodotto è inservibile e allora sì che il
        lavoro va conservato per capire cosa è andato storto; `warnings` sono
        note, e una nota non vale trenta giga. L'avviso resta scritto nella
        pagella e sulla riga: cambia solo che non occupa più il disco.
        """
        return (self.frames_written == self.frames_expected
                and not self.difetti)

    @property
    def difettosa(self) -> bool:
        """Il file prodotto NON è utilizzabile."""
        return bool(self.difetti)


class JobError(RuntimeError):
    """La lavorazione non è arrivata in fondo."""


# ---------------------------------------------------------------------------
#  La pausa: due file nella cartella di lavoro, letti da qui e scritti
#  dall'interfaccia. Il meccanismo vero è congelare i processi figli
#  (`SIGSTOP` all'upscaler o al codificatore) e risvegliarli con `SIGCONT`:
#  provato l'11/08 su entrambe le fasi, con verifica byte per byte dei PNG
#  prodotti e decodifica integrale del video. Non si perde un fotogramma,
#  perché sia l'upscaler sia ffmpeg scrivono un pezzo alla volta e fra un
#  pezzo e l'altro non hanno niente di aperto.
#
#    `.sospeso`      c'è solo MENTRE è in pausa: dice da quando e quali PID.
#    `.pause_totali` i secondi di pausa accumulati in questa corsa.
#
#  Due file e non uno perché rispondono a domande diverse: il primo è uno
#  stato ("adesso è fermo?"), il secondo è un totale che sopravvive alle
#  pause successive.
SOSPESO = ".suspended"
PAUSE_TOTALI = ".paused_seconds"


def _chiudi_pausa_aperta(work: Path) -> None:
    """Fermata da sospesa: la pausa finisce adesso, non alla ripresa.

    Il marcatore aperto si cancella alla ripresa (vedi `_esegui`) senza
    contare niente, e le ore passate in pausa prima del Ferma finivano nella
    durata del file come lavoro. Si chiudono qui, nel totale delle pause.
    """
    try:
        da = float(su_disco.leggi(work / SOSPESO).get("da") or 0)
    except (OSError, ValueError, AttributeError):
        return
    if da <= 0:
        return
    totale = 0.0
    try:
        totale = max(0.0, float((work / PAUSE_TOTALI).read_text().strip() or 0))
    except (OSError, ValueError):
        pass
    try:
        (work / PAUSE_TOTALI).write_text(f"{totale + max(0.0, time.time() - da):.1f}")
        (work / SOSPESO).unlink(missing_ok=True)
    except OSError:
        pass


def sospensione(work: Path) -> float:
    """Secondi di pausa da scontare, compresa quella in corso.

    Si somma anche la pausa APERTA: se il file finisse mentre è sospeso non
    potrebbe (è sospeso), ma questa funzione viene letta anche
    dall'interfaccia per mostrare il tempo trascorso, e lì la differenza si
    vede eccome.
    """
    totale = 0.0
    try:
        # `max(0, ...)`: un totale negativo non esiste, e se il file venisse
        # scritto male finirebbe per AGGIUNGERE tempo alla durata invece di
        # toglierlo — cioe' gonfiare la pagella, che e' esattamente il danno
        # che questa funzione esiste per evitare. Trovato in audit.
        totale = max(0.0, float((work / PAUSE_TOTALI).read_text().strip() or 0))
    except (OSError, ValueError):
        pass
    try:
        dati = su_disco.leggi(work / SOSPESO)
        da = float(dati.get("da") or 0)
        if da:
            totale += max(0.0, time.time() - da)
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        pass
    return totale


# Caratteri che, dentro un percorso, hanno un significato per qualche pezzo
# della catena. Ognuno di questi ha causato un guasto reale o è stato
# verificato come pericoloso:
#   %        il muxer image2 lo legge come segnaposto anche in una directory:
#            "Serie al 50%" fa fallire l'intera estrazione
#   [ ] * ?  con -pattern_type glob diventano modelli e non corrispondono a nulla
#   ' "      il demuxer concat cita i percorsi fra apici
#   ` $      espansioni della shell, se un percorso finisse in una riga di comando
_PERICOLOSI = re.compile(r"[%\[\]{}*?!@'\"`$;:]")

# La sola forma che un nome di segmento può avere. Tutto il resto, riletto da
# uno stato manomesso o scritto da un'altra versione, si butta.
_NOME_SEGMENTO = re.compile(r"seg\d{8}-\d{8}\.mkv")


def safe_name(stem: str, identita: str = "", quando: float | None = None,
              *, con_data: bool = True) -> str:
    """Nome di cartella di lavoro sicuro, univoco e leggibile.

    Tre requisiti, in quest'ordine:

    - sicuro: privo dei caratteri sopra;
    - univoco: con un'impronta del percorso completo, perché due episodi
      omonimi in cartelle diverse condividerebbero la cartella di lavoro e il
      secondo cancellerebbe i fotogrammi del primo;
    - leggibile: con la data, così guardando `work/` si capisce a colpo
      d'occhio a quando risale ciascuna lavorazione e quali si possono
      buttare. Un'impronta esadecimale da sola non dice niente a nessuno.
    """
    ripulito = _PERICOLOSI.sub("_", stem)
    # Anche i caratteri di controllo: un a capo dentro un nome di file è
    # legittimo su macOS e produceva una cartella di lavoro con un a capo nel
    # nome, illeggibile in ogni elenco e ostile a qualunque comando.
    ripulito = re.sub(r"[\x00-\x1f\x7f/\\]", "_", ripulito)
    ripulito = re.sub(r"_{2,}", "_", ripulito).strip("_ .") or "senza-nome"
    impronta = hashlib.sha1((identita or stem).encode("utf-8")).hexdigest()[:8]
    if not con_data:
        # Le anteprime non ne hanno bisogno: la data lì non distingue nulla e
        # farebbe finire la stessa prova, rifatta il giorno dopo, in una
        # cartella nuova.
        return f"{ripulito[:80]} {impronta}"
    data = datetime.fromtimestamp(quando if quando is not None else time.time())
    return f"{ripulito[:80]} {data:%Y-%m-%d} {impronta}"


def identita_sorgente(path: Path, cartella_input: Path) -> str:
    """Come si identifica un sorgente, in modo che sopravviva alla copia.

    L'impronta della cartella di lavoro nasceva dal percorso ASSOLUTO. Sul
    secondo Mac — dove la cartella viene copiata su un altro disco esterno, che
    è esattamente il modo in cui questo progetto è fatto per essere usato —
    il percorso cambia, l'impronta cambia, e sedici gigabyte di fotogrammi già
    estratti diventano invisibili: si ri-estrae tutto da capo e i vecchi
    restano orfani senza che nulla lo dica. Bastava rinominare la cartella di
    progetto per ottenere lo stesso effetto.

    Per i file dentro la cartella dei video da elaborare si usa quindi il
    percorso RELATIVO a quella cartella, che la copia conserva, preceduto da
    `INPUT/` qualunque sia il suo nome: con la disposizione di sempre e'
    l'identita' della 1.5, e dalla 1.6 la cartella si puo' scegliere e
    rinominare senza perdere il lavoro gia' fatto. Per quelli fuori resta
    l'assoluto: non c'e' niente di meglio, ed è comunque il caso raro.
    """
    try:
        return str(Path("INPUT") / path.resolve().relative_to(cartella_input.resolve()))
    except (ValueError, OSError):
        return str(path.resolve())


def _firma_estrazione(plan: Plan) -> str:
    """Cosa rende validi i FOTOGRAMMI già estratti.

    Separata da quella dei segmenti perché i fotogrammi non dipendono da come
    verranno codificati: cambiare preset o CRF non deve costringere a rifare
    ore di decodifica. Tenendo un'unica firma, il solo fatto di aggiungere un
    campo cancellava 19.712 fotogrammi già estratti.
    """
    try:
        st = plan.source.path.stat()
        # Solo la dimensione: la data di modifica cambia per un rsync o un
        # ripristino da backup, senza che un bit del contenuto sia diverso.
        identita = str(st.st_size)
    except OSError:
        identita = "?"
    return "|".join(str(x) for x in (
        plan.source.path.name, identita,
        ",".join(plan.restoration.chain()),
        " ".join(plan.timing_args()),
    ))


def _signature(plan: Plan) -> str:
    """Identifica i parametri che, se cambiano, invalidano il lavoro svolto.

    Regola: entra qui SOLO ciò che cambia il contenuto dei fotogrammi o dei
    segmenti già prodotti. Due errori opposti sono possibili e sono entrambi
    costosi.

    Ci finiva `chunk_size`, che però è calcolato dallo spazio libero al
    momento del piano: bastava che il disco fosse un po' più pieno perché la
    firma cambiasse da sola, il lavoro venisse buttato e l'estrazione rifatta
    da capo. La ripresa era rotta proprio sui dischi stretti, cioè l'unico
    caso per cui la lavorazione a blocchi esiste.

    Mancavano invece `preset` e la deduplica, che il contenuto lo cambiano
    eccome: riprendendo con un preset diverso si concatenavano segmenti
    codificati in due modi dentro lo stesso file.

    C'e' anche l'identita' del sorgente (dimensione e data), perché due file
    omonimi in cartelle diverse condividerebbero la stessa cartella di lavoro.
    """
    e = plan.encoding
    return "|".join(str(x) for x in (
        _firma_estrazione(plan), plan.frames,
        plan.model_name, plan.model_scale,
        plan.target_width, plan.target_height,
        e.codec, e.pix_fmt, e.preset, e.params,
        plan.dedup.enabled, str(plan.fps),
    ))


def _scrivi_atomico(path: Path, testo: str) -> None:
    """Scrittura che non può lasciare un file a metà.

    `write_text` tronca e riscrive: un'interruzione o un disco pieno nel mezzo
    lascia un JSON monco. Su `dedup.json` (centinaia di KB) la finestra è
    larga, e il risultato è una lavorazione bloccata per sempre. E il disco
    pieno non è un'ipotesi remota: è la lavorazione stessa a riempirlo.
    """
    # Il temporaneo porta il PID: con un nome fisso due processi che scrivono
    # insieme usano lo STESSO file d'appoggio, il primo lo rinomina e il
    # secondo muore con un FileNotFoundError su un percorso ".tmp" che non
    # significa niente per chi legge. Su venticinque coppie lanciate insieme
    # succedeva undici volte — e proprio sul registro che serve a coordinare
    # più lavorazioni contemporanee.
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        tmp.write_text(testo)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# Tetto oltre il quale una prenotazione non è un numero, è spazzatura: mille
# terabyte non stanno su nessun disco esterno.
MAX_PRENOTAZIONE_GB = 1_000_000.0

# Oltre questa quota di fotogrammi segnalati in un blocco, non è il modello ad
# essersi guastato: è la verifica a non calzare sul contenuto. Il guasto vero
# osservato era lo 0,8%; qui si lascia venti volte quel valore prima di


def _prenota(cartella: Path, gb: float) -> None:
    """Registra lo spazio impegnato da QUESTO processo, in un file suo.

    Un unico JSON condiviso non funzionava: leggere-modificare-riscrivere non
    è atomico, e ogni processo salvava la fotografia che aveva letto. Con
    venti lavorazioni avviate insieme ne restava registrata UNA: centonovanta
    gigabyte impegnati e invisibili, cioè il contrario di ciò che il registro
    serve a fare. Un file per processo non ha corse: nessuno scrive quello di
    un altro.
    """
    cartella.mkdir(parents=True, exist_ok=True)
    _scrivi_atomico(cartella / f"{os.getpid()}.gb", f"{gb:.3f}")


def _rilascia(cartella: Path) -> None:
    (cartella / f"{os.getpid()}.gb").unlink(missing_ok=True)


def _prenotazioni(cartella: Path) -> dict[str, float]:
    """Spazio impegnato dalle lavorazioni ATTUALMENTE in corso, in GB."""
    vivi: dict[str, float] = {}
    if not cartella.is_dir():
        return vivi
    for voce in cartella.glob("*.gb"):
        try:
            numero = int(voce.stem)
        except ValueError:
            voce.unlink(missing_ok=True)
            continue
        if numero <= 0:
            voce.unlink(missing_ok=True)
            continue
        from .processi import di_animeup
        if not di_animeup(numero):
            voce.unlink(missing_ok=True)      # morto, o il numero e' d'altri
            continue
        try:
            valore = float(voce.read_text().strip())
        except (OSError, ValueError):
            continue
        if valore != valore or not 0 <= valore <= MAX_PRENOTAZIONE_GB:
            continue
        vivi[str(numero)] = valore
    return vivi


def _segmento_valido(segment: Path, attesi: int, paths: Paths) -> bool:
    """Il segmento esiste ED è completo.

    Fidarsi di `is_file()` non basta: uno spegnimento lascia file troncati (su
    APFS il journal protegge i metadati, non i dati) e un segmento a zero byte
    restava registrato per sempre, perché niente lo invalidava mai. Il video
    finale usciva corto, e al rilancio la CLI vedeva l'uscita già presente e
    diceva "saltato": l'episodio restava rotto senza rimedio automatico.

    Costa una lettura dei pacchetti per segmento, cioè meno di un secondo
    contro le ore che protegge.
    """
    try:
        if not segment.is_file() or segment.stat().st_size < 1024:
            return False
    except OSError:
        return False
    esito = subprocess.run(
        [str(paths.ffprobe.path), "-v", "error", "-select_streams", "v:0",
         "-count_packets", "-show_entries", "stream=nb_read_packets",
         "-of", "csv=p=0", str(segment)],
        capture_output=True, text=True, check=False,
    )
    if esito.returncode != 0:
        return False
    letti = esito.stdout.strip().splitlines()
    return bool(letti) and letti[0].strip().isdigit() and int(letti[0]) == attesi


def _processo_vivo(lock: Path) -> bool:
    """Il PID scritto nel lucchetto corrisponde a un processo ancora attivo?

    Senza questo controllo un crash o uno spegnimento lasciava il lucchetto
    appeso e la lavorazione diventava impossibile da riprendere: l'utente si
    sarebbe trovato a cancellare file a mano per ripartire, che è il momento
    peggiore per chiedergli di farlo.
    """
    try:
        testo = lock.read_text().strip()
    except OSError:
        return False        # sparito nel frattempo: nessuno lo tiene
    except (UnicodeDecodeError, ValueError):
        return False        # contenuto binario: non è un lucchetto nostro
    if not testo:
        # Vuoto: non è "morto", è "non lo so". Prima si rispondeva morto e si
        # cancellava il lucchetto di chi stava lavorando. Si guarda l'eta': un
        # lucchetto appena creato è quasi certamente di qualcuno che sta
        # ancora scrivendoci dentro; uno vecchio è un residuo.
        try:
            return (time.time() - lock.stat().st_mtime) < 60
        except OSError:
            return False
    try:
        pid = int(testo)
    except ValueError:
        return False        # illeggibile: si considera morto, non si blocca
    if pid == os.getpid():
        return False
    # Vivo, non ZOMBIE (morto ma non ancora raccolto dal padre: teneva il
    # lucchetto occupato, visto dopo un kill -9 dalla UI) e davvero AnimeUp:
    # dopo uno spegnimento il numero puo' essere di un processo qualunque.
    from .processi import di_animeup
    return di_animeup(pid)


def _abbatti_orfano(work: Path) -> None:
    """Uccide l'upscaler orfano di una lavorazione morta male, se c'e'.

    Un SIGKILL alla CLI non lascia girare nessun gestore di segnali: il
    binario ncnn, in sessione propria, sopravvive e continua a scrivere PNG
    nella cartella. Riprendere la lavorazione a quel punto significherebbe
    DUE processi che scrivono gli stessi file. Il pgid lasciato su disco da
    `upscale_dir` permette di trovarlo e abbatterlo prima di ripartire.
    """
    pgid_file = work / "upscaler.pgid"
    try:
        pgid = int(pgid_file.read_text().strip())
    except (OSError, ValueError):
        return
    # Il pgid può essere stato RIUSATO da un processo qualunque dopo un
    # riavvio: si uccide solo se il comando è davvero un upscaler nostro.
    try:
        esito = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pgid)],
            capture_output=True, text=True, check=False,
        )
        comando = esito.stdout.strip() if esito.returncode == 0 else ""
        if comando and ("ncnn" in comando or "realesrgan" in comando
                        or "realcugan" in comando):
            os.killpg(pgid, signal.SIGKILL)
            for _ in range(25):          # max 5 secondi: poi si va comunque
                time.sleep(0.2)
                try:
                    os.kill(pgid, 0)
                except ProcessLookupError:
                    break
    except (OSError, PermissionError):
        pass
    pgid_file.unlink(missing_ok=True)


class Job:
    """Una lavorazione completa, ripartibile."""

    def __init__(self, plan: Plan, *, paths: Paths | None = None) -> None:
        self.plan = plan
        self.paths = paths or PATHS
        # La data serve solo a rendere leggibile l'elenco delle lavorazioni,
        # non a distinguerle: l'univocita' la garantisce l'impronta del
        # percorso. Se una cartella per questo sorgente esiste già si
        # riusa quella, qualunque data porti: la mtime del sorgente cambia
        # per un rsync o un ripristino da backup, e prendendola come parte
        # del nome il lavoro già fatto restava orfano.
        base = safe_name(
            plan.source.path.stem,
            identita_sorgente(plan.source.path, self.paths.input),
        )
        impronta = base.rsplit(" ", 1)[-1]
        # Impronta della convenzione PRECEDENTE (percorso assoluto). Va ancora
        # cercata, altrimenti passare a quella portabile avrebbe reso invisibile
        # il lavoro già svolto con la vecchia: la stessa cosa che la modifica
        # serve a impedire.
        legacy = hashlib.sha1(
            str(plan.source.path.resolve()).encode("utf-8")
        ).hexdigest()[:8]
        # Se ne combaciano più d'una si prende la PIÙ RECENTE (la data è in
        # testa al nome, quindi l'ordine alfabetico è cronologico): prendendo
        # la più vecchia si ripartiva da un lavoro superato e l'altro restava
        # orfano su disco per sempre, senza che nessuno lo dicesse.
        esistenti: list[Path] = []
        if self.paths.work.is_dir():
            viste = set()
            for chiave in (impronta, legacy):
                for d in self.paths.work.glob(f"* {chiave}"):
                    if d.is_dir() and d not in viste:
                        viste.add(d)
                        esistenti.append(d)
            esistenti.sort()
        self.work = esistenti[-1] if esistenti else self.paths.work / base
        self.abbandonate = esistenti[:-1]

        # La rinomina dall'impronta vecchia a quella nuova NON si fa qui: il
        # costruttore gira anche quando si vuole solo ISPEZIONARE un piano, e
        # spostare la cartella sotto i piedi di una lavorazione viva le faceva
        # trovare `frames/` vuota e ri-estrarre sedici gigabyte in silenzio.
        # Si rimanda a dopo l'acquisizione del lucchetto.
        self._da_rinominare = (
            self.paths.work / base
            if (self.work.is_dir() and self.work.name.endswith(f" {legacy}")
                and legacy != impronta)
            else None
        )

        self._lucchetto_mio = False
        # I parametri di questo lancio, scritti in parameters.json SOLO a
        # lucchetto preso: sono la ricetta del Riprendi dell'interfaccia.
        self.ricetta: dict | None = None
        self._avvisi: list[str] = []
        self.frames_dir = self.work / "frames"
        self.segments_dir = self.work / "segments"
        self.state_path = self.work / "state.json"
        self.state: dict = {}

    # --- stato per la ripresa -------------------------------------------
    def _load_state(self) -> None:
        # In coda alla funzione lo stato riceve anche `chunk` (la dimensione
        # del blocco): il monitor ne ha bisogno da SUBITO per il "blocco 2 di
        # 10" della riga, e da disco non è deducibile prima del 1° segmento.
        self.__load_state()
        self.state["chunk"] = self.plan.chunk_size

    def __load_state(self) -> None:
        if self.state_path.is_file():
            try:
                state = su_disco.leggi(self.state_path)
            except (json.JSONDecodeError, OSError, ValueError, UnicodeDecodeError):
                state = {}
            if isinstance(state, dict):
                # I fotogrammi si conservano anche se cambia la codifica: si
                # butta solo ciò che dipende davvero da ciò che è cambiato.
                estratti = (state.get("extracted", 0)
                            if state.get("extraction") == _firma_estrazione(self.plan)
                            else 0)
                if state.get("signature") == _signature(self.plan):
                    self.state = state
                    self.state["extracted"] = estratti
                    # La griglia dei blocchi si ADOTTA dallo stato salvato,
                    # non si ricalcola: il ricalcolo dipende dallo slider GB
                    # e dallo spazio libero del momento, e uno spostamento
                    # qualsiasi sfratta i segmenti gia' codificati (che si
                    # riusano solo a intervalli identici). Solo se c'e'
                    # davvero lavoro da proteggere: senza segmenti fatti la
                    # griglia fresca e' piu' onesta col disco di oggi.
                    try:
                        salvato = int(state.get("chunk") or 0)
                    except (TypeError, ValueError):
                        salvato = 0
                    if (salvato > 0 and state.get("segments")
                            and salvato != self.plan.chunk_size):
                        self.plan.chunk_size = salvato
                        self.plan.chunks = max(
                            1, -(-self.plan.frames // salvato))
                    return
                self.state = {
                    "signature": _signature(self.plan),
                    "extraction": _firma_estrazione(self.plan),
                    "segments": [], "extracted": estratti,
                }
                return
        self.state = {
            "signature": _signature(self.plan),
            "extraction": _firma_estrazione(self.plan),
            "segments": [], "extracted": 0,
        }

    def _segna_tempo_speso(self, secondi: float) -> None:
        if not isinstance(self.state, dict) or not self.state:
            return                      # mai caricato: non c'è nulla da sommare
        try:
            self.state["secondi_spesi"] = round(
                float(self.state.get("secondi_spesi") or 0) + secondi, 1)
            # Ogni passaggio di qui e' un'interruzione: serve a spiegare,
            # a lavoro finito, perche' il totale supera quello di una
            # passata dritta (a ogni ripresa il blocco in corso si rifa').
            self.state["interruzioni"] = int(
                self.state.get("interruzioni") or 0) + 1
            self._save_state()
        except (OSError, TypeError, ValueError):
            pass

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _scrivi_atomico(self.state_path, su_disco.dumps(self.state, indent=2))

    # --- esecuzione -------------------------------------------------------
    def run(self, progress: Progress | None = None) -> JobResult:
        """Esegue la lavorazione, rilasciando il lucchetto in ogni caso.

        Anche su eccezione o interruzione da tastiera: un lucchetto rimasto
        appeso dopo un errore bloccherebbe ogni ripresa successiva, che è
        esattamente il momento in cui serve poter ripartire.
        """
        partita = time.time()
        completato = False
        try:
            esito = self._esegui(progress)
            completato = True
            return esito
        finally:
            if not completato:
                if self._lucchetto_mio:
                    _chiudi_pausa_aperta(self.work)
                # Interrotto o fallito: i minuti spesi non devono sparire
                # dalla contabilità. "Finito in 02h 26m" su un file lavorato
                # in due riprese contava solo l'ultima (visto dall'utente):
                # il totale si accumula qui e si somma al completamento.
                self._segna_tempo_speso(max(0.0, time.time() - partita))
            # SOLO se il lucchetto è nostro. Cancellandolo comunque, il
            # processo che si era appena rifiutato di partire perché un altro
            # stava lavorando distruggeva la mutua esclusione che aveva appena
            # rispettato: il tentativo successivo entrava e i due si
            # cancellavano i fotogrammi a vicenda. Lo stesso valeva per un
            # rifiuto per spazio insufficiente, che avviene prima ancora del
            # controllo del lucchetto.
            if self._lucchetto_mio:
                (self.work / "running.lock").unlink(missing_ok=True)
                self._lucchetto_mio = False
            # Un'eccezione qui dentro nasconderebbe l'errore vero (per esempio
            # il disco pieno che ha fatto fallire la lavorazione).
            try:
                _rilascia(self.paths.work / ".reservations")
            except OSError:
                pass

    def _esegui(self, progress: Progress | None = None) -> JobResult:
        p = progress or Progress()
        started = time.time()
        plan = self.plan
        # La stessa lista che i blocchi usano per far risalire gli avvisi:
        # `p.say` finisce in una barra di avanzamento troncata, non è un
        # canale di segnalazione.
        warnings: list[str] = self._avvisi

        # Si controlla PRIMA di cominciare. Riempire il disco a metà
        # lavorazione non rovina solo questo file: blocca il sistema e può
        # corrompere lo stato di altri lavori in corso.
        libero_gb = gb_liberi(self.paths.output)
        gia_fatto = sum(
            f.stat().st_size for f in self.frames_dir.glob("*.png")
        ) / 1_073_741_824 if self.frames_dir.is_dir() else 0.0
        serve = plan.est_peak_disk_gb - gia_fatto

        # Si prova a scrivere DOVE finira' il risultato, prima di cominciare.
        # Il permesso mancante si scopriva al mux, cioè dopo tutta la GPU: su
        # un episodio da quattro ore, quattro ore buttate per un chmod.
        try:
            plan.output.parent.mkdir(parents=True, exist_ok=True)
            sonda = plan.output.parent / f".animeup-prova-{os.getpid()}"
            sonda.write_bytes(b"")
            sonda.unlink()
        except OSError as exc:
            raise JobError(t("mot.pipe.non_scrivibile",
                               cartella=plan.output.parent,
                               errore=exc.strerror or exc)) from exc

        self.paths.work.mkdir(parents=True, exist_ok=True)
        registro = self.paths.work / ".reservations"
        altrui = sum(_prenotazioni(registro).values())
        if serve > libero_gb - altrui:
            raise JobError(
                (t("mot.pipe.spazio_altrui", servono=f"{serve:.0f}",
                   liberi=f"{libero_gb:.0f}", altrui=f"{altrui:.0f}")
                 if altrui else
                 t("mot.pipe.spazio", servono=f"{serve:.0f}",
                   liberi=f"{libero_gb:.0f}"))
            )
        # Si prenota PRIMA di cominciare, così una lavorazione avviata subito
        # dopo trova lo spazio già impegnato invece di contarlo due volte.
        _prenota(registro, serve)

        self.work.mkdir(parents=True, exist_ok=True)
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        plan.log.parent.mkdir(parents=True, exist_ok=True)

        # Due lavorazioni sullo stesso sorgente condividono la cartella (è
        # voluto: i fotogrammi estratti sono gli stessi). Girare INSIEME però
        # no: si sovrascriverebbero lo stato e i segmenti a vicenda, e il
        # danno si scoprirebbe solo alla fine.
        # Il lucchetto si crea GIA' PIENO, con un collegamento fisico.
        #
        # `O_CREAT|O_EXCL` da solo non basta, ed è un errore che ho già fatto
        # una volta qui: fra la creazione e la scrittura del PID il file esiste
        # ma è VUOTO. Chi arriva in quella finestra prende FileExistsError,
        # legge un file vuoto, `int('')` fallisce, `_processo_vivo` risponde
        # "morto" — e cancella il lucchetto di una lavorazione viva per
        # entrarci dentro. Misurato: due processi dentro insieme, e cinquecento
        # fotogrammi su cinquecento distrutti.
        #
        # `os.link` invece è atomico e fallisce se la destinazione esiste: il
        # contenuto viene scritto PRIMA che il lucchetto sia visibile, quindi
        # non può mai essere letto vuoto.
        lock = self.work / "running.lock"
        provvisorio = self.work / f".lock-{os.getpid()}"
        for _tentativo in range(3):
            provvisorio.unlink(missing_ok=True)
            provvisorio.write_text(str(os.getpid()))
            try:
                os.link(provvisorio, lock)
            except FileExistsError:
                if _processo_vivo(lock):
                    provvisorio.unlink(missing_ok=True)
                    raise JobError(t("mot.pipe.gia_in_corso",
                                     cartella=self.work.name,
                                     lucchetto=lock)) from None
                # Sembra di un processo morto. Toglierlo di mezzo è però
                # pericoloso: fra il giudizio "è morto" e la rimozione, un
                # ALTRO processo può averlo già rubato e messo il proprio,
                # vivo. Cancellandolo alla cieca si buttava fuori chi stava
                # lavorando — misurato: due processi dentro insieme.
                # Si rimuove SOLO se è ancora lo stesso identico file, cioè
                # se l'inode non è cambiato.
                try:
                    morto = lock.stat().st_ino
                    if not _processo_vivo(lock) and lock.stat().st_ino == morto:
                        lock.unlink()
                except OSError:
                    pass
                continue

            # Il collegamento c'e'. Resta da dimostrare che il lucchetto sia
            # DAVVERO il nostro: finché teniamo il temporaneo, i due nomi
            # puntano allo stesso inode, e confrontarli è una prova, non una
            # speranza. Se qualcuno ce l'ha rubato nel frattempo, si riprova.
            try:
                mio = provvisorio.stat().st_ino == lock.stat().st_ino
            except OSError:
                mio = False
            provvisorio.unlink(missing_ok=True)
            if not mio:
                continue
            self._lucchetto_mio = True
            if self.ricetta is not None:
                try:
                    (self.work / "parameters.json").write_text(
                        su_disco.dumps(self.ricetta, indent=2))
                except OSError:
                    pass
            break
        else:
            raise JobError(t("mot.pipe.lucchetto", lucchetto=lock))

        # UNA PAUSA APERTA QUI NON PUO' ESISTERE, e va chiusa.
        #
        # Il marcatore `.sospeso` dice «dei processi sono congelati adesso».
        # Se siamo qui, il lucchetto è nostro e stiamo cominciando: qualunque
        # processo congelato di prima è morto insieme alla lavorazione che lo
        # aveva. Ma il marcatore resta sul disco, e `sospensione()` continua a
        # contare da quell'istante — un secondo al secondo, per sempre.
        #
        # Trovato in audit provandolo davvero: pausa, poi Ferma tutto. I
        # processi muoiono tutti (verificato: zero residui), il marcatore no.
        # Riprendendo quel file il giorno dopo, la pagella avrebbe fatto
        # «lavoro meno pausa» con una pausa di ore, registrando un tempo
        # NEGATIVO — e le pagelle sono i dati da cui l'app impara a stimare.
        # Lo stesso vale per un blackout o un riavvio a lavorazione congelata.
        (self.work / SOSPESO).unlink(missing_ok=True)

        # Adesso che il lucchetto è nostro, il ponte si può attraversare in
        # sicurezza: nessun altro processo sta lavorando in questa cartella.
        if self._da_rinominare is not None and not self._da_rinominare.exists():
            try:
                self.work.rename(self._da_rinominare)
                self.work = self._da_rinominare
                self.frames_dir = self.work / "frames"
                self.segments_dir = self.work / "segments"
                self.state_path = self.work / "state.json"
                lock = self.work / "running.lock"
            except OSError:
                pass          # si continua con la vecchia: peggio, ma funziona

        for vecchia in self.abbandonate:
            # Va in `note` e non in `warnings`: `JobResult.ok` richiede
            # `not warnings`, e la CLI pulisce la cartella di lavoro solo
            # quando l'esito è ok. Un avviso che si ripresenta a ogni lancio
            # avrebbe reso `--keep-temp` permanentemente attivo senza dirlo,
            # lasciando su disco due cartelle da sedici gigabyte l'una.
            p.say(t("mot.pipe.fase_cartelle"),
                  t("mot.pipe.cartella_abbandonata", cartella=vecchia.name))
        # Il lucchetto è nostro, ma se il proprietario precedente è morto di
        # SIGKILL il suo upscaler può essere ancora vivo dentro la cartella.
        _abbatti_orfano(self.work)
        self._load_state()

        # --- 1. estrazione ------------------------------------------------
        # Prima si estrae, poi si misura: la deduplica deve guardare gli
        # stessi identici fotogrammi che verranno elaborati.
        # La ripresa si fida del conteggio REGISTRATO e verificato sul disco,
        # non della stima del piano: l'estrazione con reticolo costante rende
        # regolarmente qualche fotogramma in più o in meno dei pacchetti del
        # sorgente (misurato su 5 file di prova su 6). Confrontando con la
        # stima, ogni rilancio rifaceva l'estrazione all'infinito senza mai
        # avanzare.
        p.say(t("mot.pipe.fase_estrazione"), t("mot.pipe.estrazione"))
        registrati = self.state.get("extracted", 0)
        sul_disco = sum(1 for _ in self.frames_dir.glob("*.png")) if self.frames_dir.is_dir() else 0
        if registrati and registrati == sul_disco:
            extracted = registrati
        else:
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            extracted = enc.extract_frames(plan, self.frames_dir, paths=self.paths)
            self.state["extracted"] = extracted
            self._save_state()

        if not extracted:
            raise JobError(t("mot.pipe.estrazione_vuota"))
        if abs(extracted - plan.frames) > max(2, plan.frames * 0.01):
            warnings.append(t("mot.pipe.estratti_diversi", estratti=extracted,
                              stimati=plan.frames))
        total_frames = extracted

        # --- 2. mappa di deduplica, sui fotogrammi appena estratti ---------
        dmap = self._dedup_map(p, warnings, total_frames)

        # --- 3. blocchi ----------------------------------------------------
        chunks = self._chunk_ranges(total_frames)

        # I segmenti si registrano con l'INTERVALLO che coprono, non con il
        # loro numero d'ordine. La dimensione dei blocchi dipende dallo spazio
        # libero, che la lavorazione stessa consuma: al secondo giro i confini
        # sono diversi, e riusare "il segmento numero 3" significava rimontare
        # fotogrammi sbagliati, duplicati e fuori ordine, senza che nessun
        # controllo se ne accorgesse.
        fatti: dict[tuple[int, int], Path] = {}
        for voce in self.state.get("segments") or []:
            # Le voci non conformi si scartano in silenzio: una tripla
            # malformata alzava l'eccezione dentro run(), e ogni rilancio
            # ritrovava lo stesso stato e falliva identico, per sempre.
            try:
                inizio, fine, percorso = voce
                # Solo il NOME, risolto sotto la cartella di lavoro corrente.
                # Registrando il percorso assoluto, dopo una copia su un altro
                # disco i segmenti non si trovavano più e si ricodificavano
                # tutti benché i file fossero lì sotto il nome giusto; e se
                # il vecchio percorso esisteva ancora (primo disco montato) si
                # leggevano da LA', cioè dal lavoro sbagliato.
                nome = Path(str(percorso)).name
                # Il nome deve essere quello che questo codice produce, e
                # nient'altro. Con `""`, `"."`, `".."` o `"/"` il basename è
                # vuoto e `segments_dir / ""` diventa la CARTELLA dei segmenti:
                # la spazzata dei residui li cancellava tutti, e poi si provava
                # a fare `unlink` su una directory. Ogni rilancio falliva
                # identico, cioè proprio il guasto permanente che il resto di
                # questo blocco esiste per evitare.
                if not _NOME_SEGMENTO.fullmatch(nome):
                    continue
                fatti[(int(inizio), int(fine))] = self.segments_dir / nome
            except (TypeError, ValueError):
                continue

        def _registra() -> None:
            self.state["segments"] = [
                [a, b, v.name] for (a, b), v in sorted(fatti.items())
            ]
            # La dimensione del blocco entra nello stato per il MONITOR: da
            # sola non è deducibile da disco finché il primo segmento non
            # esiste, e il "blocco 2 di 10" della riga la vuole subito.
            self.state["chunk"] = self.plan.chunk_size
            # Il conteggio VERO dei fotogrammi entra nello stato accanto ai
            # segmenti. Non sta in `_signature` (che porta la *stima* del
            # piano): se una ri-estrazione ne rende un numero diverso — e
            # succede fra build diverse di ffmpeg, cioè proprio fra i due Mac
            # — i segmenti costruiti sull'insieme vecchio venivano riusati sul
            # nuovo, sfasati di un fotogramma, senza un avviso.
            self.state["segments_extracted"] = self.state.get("extracted", 0)
            self._save_state()

        # Uno stato SENZA la chiave viene da una versione precedente, e non
        # dice niente su quanti fotogrammi c'erano quando i segmenti sono stati
        # prodotti: va trattato come non valido, non come valido.
        # Accettandolo (`is not None`) la guardia saltava proprio nel caso per
        # cui esiste — lavorazione interrotta col codice vecchio, trasloco,
        # ri-estrazione con un fotogramma di differenza — e quaranta fotogrammi
        # su quarantuno del file finale venivano dall'estrazione precedente,
        # senza un avviso.
        if fatti and self.state.get("segments_extracted") != self.state.get("extracted", 0):
            p.say(t("mot.pipe.fase_segmenti"), t("mot.pipe.segmenti_non_validi"))
            fatti.clear()

        # Le cartelle di blocco sono intitolate per INDICE e si ripuliscono
        # solo quando quell'indice viene rielaborato. Se al rilancio i blocchi
        # diventano meno numerosi (disco liberato, quindi blocchi più grandi)
        # gli indici alti non esistono più e i residui restano per sempre —
        # proprio sul disco che la lavorazione a blocchi esiste per non
        # riempire: su un episodio reale sono ventidue gigabyte per indice
        # abbandonato. Sono tutte cartelle di passaggio: si spazzano qui.
        for residuo in self.work.glob("chunk*"):
            if residuo.is_dir():
                shutil.rmtree(residuo, ignore_errors=True)
        # Stessa fuga per i segmenti sfrattati da giri precedenti: le voci
        # sparivano dallo stato, i file no.
        attesi = {v.name for v in fatti.values()}
        for residuo in self.segments_dir.glob("seg*.mkv"):
            if residuo.name not in attesi:
                residuo.unlink(missing_ok=True)

        prodotti: list[Path] = []
        for index, (start, stop) in enumerate(chunks):
            gia = fatti.get((start, stop))
            if gia is not None and _segmento_valido(gia, stop - start, self.paths):
                prodotti.append(gia)
                p.step(index + 1, len(chunks), stop, total_frames)
                continue
            if gia is not None:
                p.say(t("mot.pipe.fase_segmenti"),
                      t("mot.pipe.segmento_rifatto", segmento=gia.name))
            segment = self._process_chunk(index, start, stop, dmap, p, len(chunks), total_frames)
            # Si espelle ogni voce che si sovrappone all'intervallo appena
            # prodotto: restavano registrate voci di giri precedenti con
            # confini diversi, e al giro dopo tornavano buone rimontando
            # fotogrammi duplicati. I FILE sfrattati si cancellano, altrimenti
            # restano su disco per sempre senza che nulla li nomini.
            for chiave in [k for k in fatti if k[0] < stop and k[1] > start]:
                vecchio = fatti.pop(chiave)
                if vecchio != segment:
                    vecchio.unlink(missing_ok=True)
            fatti[(start, stop)] = segment
            prodotti.append(segment)
            _registra()

        # --- 4. assemblaggio ----------------------------------------------
        _registra()

        p.say(t("mot.pipe.fase_assemblaggio"), t("mot.pipe.assemblaggio"))
        # Il file resta col nome provvisorio finche' non e' verificato: un
        # Ferma fra la rinomina e i controlli lasciava in OUTPUT un file col
        # nome buono mai controllato, che il rilancio saltava come «gia'
        # fatto» (niente pagella, cartella di lavoro orfana, difetti mai
        # segnalati). Cosi' un'interruzione qui rifa' solo l'assemblaggio.
        provvisorio = enc.concat_and_mux(plan, prodotti, self.work, paths=self.paths,
                                         rinomina=False)

        written, geometry = enc.verify_output(plan, total_frames, paths=self.paths,
                                              file=provvisorio)
        atteso = f"{plan.target_width}x{plan.target_height}"
        # Questi sono DIFETTI del file, non note: un video più corto del
        # sorgente o di geometria sbagliata non è un risultato con una
        # riserva, è un risultato da buttare.
        difetti: list[str] = []
        if not written:
            warnings.append(t("mot.pipe.non_verificabile"))
        elif written != total_frames:
            difetti.append(t("mot.pipe.fotogrammi_diversi", scritti=written,
                             attesi=total_frames))
        if geometry != atteso:
            difetti.append(t("mot.pipe.geometria_diversa", geometria=geometry,
                             attesa=atteso))
        if not enc.audio_risponde_al_seek(plan, paths=self.paths, file=provvisorio):
            difetti.append(t("mot.pipe.audio_seek"))
        os.replace(provvisorio, plan.output)

        return JobResult(
            output=plan.output,
            frames_expected=total_frames,
            frames_written=written,
            geometry=geometry,
            # Il tempo VERO complessivo: le corse interrotte precedenti
            # (accumulate in `secondi_spesi`) più questa, MENO le pause.
            #
            # Le pause le mette l'interfaccia congelando i processi figli
            # (vedi `sospensione` più sotto): la CLI resta viva ad aspettare,
            # quindi il suo orologio continua a girare anche mentre non si
            # lavora. Senza questa sottrazione un file messo in pausa tre ore
            # risulterebbe durato tre ore di più, e quel numero finisce nella
            # pagella — cioè proprio nei dati da cui l'app impara a stimare.
            # Un'ora di pausa avvelenerebbe le stime di tutti i file dopo.
            # Tutto sull'orologio di parete, come la sospensione: il
            # monotonic si ferma mentre il Mac dorme, e mescolarli dava
            # durate sbagliate, perfino negative.
            seconds=max(0.0, float(self.state.get("secondi_spesi") or 0)
                        + time.time() - started - sospensione(self.work)),
            riprese=int(self.state.get("interruzioni") or 0) + 1,
            dedup_saving=dmap.saving if dmap else 0.0,
            audit_violations=self.state.get("audit_violations", 0),
            warnings=warnings,
            difetti=difetti,
        )

    # --- fasi -------------------------------------------------------------
    def _dedup_map(
        self, p: Progress, warnings: list[str], total_frames: int
    ) -> dd.DedupMap | None:
        plan = self.plan
        if not plan.dedup.enabled:
            return None

        # Una cache illeggibile si rifà: prima una JSONDecodeError usciva da
        # Job.run e bloccava l'episodio per sempre, perché ogni rilancio
        # ritrovava lo stesso file monco.
        # Chiavata sull'ESTRAZIONE e non sulla firma completa: la mappa
        # dipende solo dai fotogrammi, quindi cambiare CRF o preset non deve
        # costringere a rimisurare l'intera sequenza.
        firma_mappa = (f"{_firma_estrazione(plan)}|{plan.dedup.enabled}"
                       f"|{total_frames}|m{dd.METRIC_VERSION}")
        cache = self.work / "dedup.json"
        if cache.is_file():
            try:
                data = json.loads(cache.read_text())
                if not isinstance(data, dict):
                    raise ValueError("cache non valida")
                if data.get("signature") == firma_mappa:
                    ripresa = dd.DedupMap(
                        total=data["total"], keep=data["keep"],
                        source_of=data["source_of"], runs=data["runs"],
                        threshold=data["threshold"], max_run=data["max_run"],
                        capped=data["capped"],
                    )
                    # La firma dice solo che la mappa parla dello stesso
                    # video, non che sia sana: il file può essere stato
                    # troncato o modificato. Le differenze non ci sono più,
                    # ma le invarianti strutturali si controllano lo stesso.
                    if not dd.structure_ok(ripresa):
                        raise ValueError("mappa riletta malformata")
                    return ripresa
            except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                    AttributeError, OSError, UnicodeDecodeError):
                cache.unlink(missing_ok=True)

        p.say(t("mot.pipe.fase_deduplica"), t("mot.pipe.misura_differenze"))
        diffs = dd.measure_frame_differences(self.frames_dir, paths=self.paths)
        if not diffs:
            warnings.append(t("mot.pipe.misura_fallita"))
            return None
        if len(diffs) + 1 != total_frames:
            warnings.append(t("mot.pipe.misura_sfasata", misurati=len(diffs) + 1,
                              attesi=total_frames))
            return None

        # I fotogrammi estratti sono a 8 bit per scelta (vedi extract_frames):
        # la soglia va rapportata a quella scala, non a quella del sorgente.
        dmap = dd.build_map(diffs, bit_depth=8)

        # Controllo indipendente prima di fidarsi della mappa.
        result = dd.audit(diffs, dmap)
        self.state["audit_violations"] = len(result.violations)
        self.state["audit_structural"] = len(result.structural)

        if result.structural:
            # Mappa malformata. Promuovere i singoli fotogrammi non ripara
            # niente — anzi, con la sentinella (-1) scriveva sull'ULTIMO
            # elemento e lasciava la mappa rotta ma dichiarata sana, per poi
            # far fallire l'elaborazione con un FileNotFoundError su
            # 00000000.png, incomprensibile a chiunque. Si rinuncia alla
            # deduplica e si elaborano tutti i fotogrammi: si perde tempo, non
            # correttezza.
            warnings.append(t("mot.pipe.dedup_disattivata"))
            return None

        if result.violations:
            warnings.append(t("mot.pipe.falsi_duplicati",
                              n=len(result.violations)))
            # Riparazione chirurgica: si promuovono a "da elaborare" solo i
            # fotogrammi incriminati, senza rifare l'intero episodio.
            # `keep` va tenuto senza ripetizioni, altrimenti `unique` e
            # `saving` mentono e il numero finisce sia in dedup.json sia sotto
            # gli occhi dell'utente.
            for index, _drift in result.violations:
                dmap.source_of[index] = index
            dmap.keep = sorted(set(dmap.keep) | {i for i, _ in result.violations})

        _scrivi_atomico(cache, json.dumps({
            "signature": firma_mappa, "total": dmap.total, "keep": dmap.keep,
            "source_of": dmap.source_of, "runs": dmap.runs,
            "threshold": dmap.threshold, "max_run": dmap.max_run, "capped": dmap.capped,
        }))
        p.say(t("mot.pipe.fase_deduplica"), dd.describe(dmap))
        return dmap

    def _chunk_ranges(self, total: int) -> list[tuple[int, int]]:
        size = max(1, self.plan.chunk_size)
        return [(s, min(s + size, total)) for s in range(0, total, size)]

    def _process_chunk(
        self, index: int, start: int, stop: int,
        dmap: dd.DedupMap | None, p: Progress, chunks: int, total: int,
    ) -> Path:
        plan = self.plan
        chunk_in = self.work / f"chunk{index:04d}-in"
        chunk_up = self.work / f"chunk{index:04d}-up"
        chunk_full = self.work / f"chunk{index:04d}-full"
        for d in (chunk_in, chunk_up, chunk_full):
            shutil.rmtree(d, ignore_errors=True)
        chunk_in.mkdir(parents=True)

        indices = list(range(start, stop))
        if dmap:
            # Una sequenza di duplicati può attraversare il confine fra due
            # blocchi: il fotogramma di riferimento va incluso comunque.
            needed = sorted({dmap.source_of[i] for i in indices})
            mapping = dmap.source_of
        else:
            needed = indices
            mapping = list(range(total))

        for frame in needed:
            source = self.frames_dir / f"{frame + 1:08d}.png"
            target = chunk_in / f"{frame + 1:08d}.png"
            try:
                target.hardlink_to(source)
            except OSError:
                shutil.copy2(source, target)

        # QUANTI FOTOGRAMMI CONTIENE DAVVERO QUESTO BLOCCO, scritto adesso.
        # A blocco finito la cartella `chunkNNNN-in` viene cancellata e questo
        # numero sparisce: restano gli estremi del segmento, che sono indici
        # del sorgente e non dicono quanto lavoro c'era dentro. Senza, la
        # deduplica REALE di un file non e' ricostruibile a posteriori — ed e'
        # esattamente il dato che serve per correggere la stima invece di
        # ripetere per ore la percentuale indovinata all'inizio.
        # Misurato l'11/08: dentro un solo episodio la deduplica e' passata
        # dal 9,3% al 55,8% da un blocco all'altro.
        # Si SOSTITUISCE la voce di questo blocco, non si aggiunge: una
        # lavorazione ripresa rifa' da capo il blocco che era in corso, e
        # appendendo si ritrovavano due voci identiche per lo stesso `da`
        # (verificato in audit su una ripresa vera). La percentuale non
        # cambiava — i valori sono gli stessi — ma il CONTEGGIO dei blocchi
        # si', ed e' proprio quel numero a dire quanto fidarsi della misura.
        # E la lista cresceva a ogni ripresa, senza fine.
        blocchi = [b for b in self.state.get("blocchi", [])
                   if not (isinstance(b, dict) and b.get("da") == start)]
        blocchi.append({"da": start, "a": stop, "tenuti": len(needed)})
        self.state["blocchi"] = blocchi
        self._save_state()

        p.say(
            t("mot.pipe.fase_upscale"),
            t("mot.pipe.blocco_upscale", blocco=index + 1, blocchi=chunks,
              fotogrammi=len(needed)),
        )
        upscale_dir(
            chunk_in, chunk_up,
            scale=plan.model_scale, model=plan.model,
            log=plan.log, paths=self.paths,
            on_progress=lambda done, exp: p.step(index + 1, chunks, start + done, total),
            pgid_file=self.work / "upscaler.pgid",
        )

        enc.materialise_duplicates(chunk_up, mapping, indices, chunk_full)

        segment = self.segments_dir / f"seg{start:08d}-{stop:08d}.mkv"
        p.say(t("mot.pipe.fase_codifica"),
              t("mot.pipe.blocco_codifica", blocco=index + 1, blocchi=chunks))
        enc.encode_segment(plan, chunk_full, segment, start_number=1, paths=self.paths)

        for d in (chunk_in, chunk_up, chunk_full):
            shutil.rmtree(d, ignore_errors=True)
        p.step(index + 1, chunks, stop, total)
        return segment

    def _forse_disco_pieno(self) -> str:
        """Aggiunge la causa vera quando lo spazio è finito.

        Riempiendosi il disco a metà lavorazione, il modello usciva con codice
        0 scrivendo file troncati e l'errore diceva "sequenza non contigua o
        illeggibile": mandava a caccia di fotogrammi corrotti chi doveva solo
        liberare spazio.
        """
        try:
            libero = gb_liberi(self.paths.output)
        except OSError:
            return ""
        if libero < 2.0:
            return t("mot.pipe.disco_pieno", liberi=f"{libero:.1f}")
        return ""

    def cleanup(self) -> None:
        """Rimuove la cartella di lavoro. Da chiamare solo a esito positivo."""
        shutil.rmtree(self.work, ignore_errors=True)
