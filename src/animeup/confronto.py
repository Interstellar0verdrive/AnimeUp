"""Il confronto delle clip in un processo suo, come le lavorazioni.

Prima le clip si elaboravano dentro la pagina: Streamlit riesegue lo script
a ogni clic, e qualunque interazione (un clic, un ricaricamento, la finestra
chiusa) uccideva il giro a meta'. Ora la pagina scrive la richiesta e lancia
`animeup compare`, che lavora staccato dalla sessione e racconta a che punto
e' in `stato.json`; la pagina si limita a rileggerlo.

Un confronto alla volta. Tutto vive in `cache/compare/`:

  request.json   cosa fare: sorgente, impostazioni del piano, clip, modelli
  status.json    a che punto e': stato, avanzamento, guasti, risultati
  compare.log    l'uscita del processo, per capire un fallimento
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from .paths import PATHS, Paths, code_root

IN_CORSO, FINITO, FERMATO, FALLITO, INTERROTTO = (
    "running", "done", "stopped", "failed", "interrupted")
# La fase del pezzo in corso mentre si estraggono i fotogrammi dello spezzone.
PREPARA = "preparing"


def cartella(p: Paths | None = None) -> Path:
    return (p or PATHS).cache / "compare"


def _scrivi(f: Path, dati: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = f.with_name(f.name + f".{os.getpid()}.tmp")
    provvisorio.write_text(json.dumps(dati, ensure_ascii=False, indent=1))
    provvisorio.replace(f)


def _vivo(pid: int) -> bool:
    from .processi import di_animeup
    return di_animeup(pid)


def stato(p: Paths | None = None) -> dict | None:
    """L'ultimo confronto: quello in corso, o l'ultimo finito.

    Un processo che risulta in corso ma non esiste piu' (Mac spento, processo
    ucciso) diventa `interrupted`: le clip gia' fatte restano in cache e il
    prossimo giro le riusa.
    """
    try:
        dati = json.loads((cartella(p) / "status.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict):
        return None
    if dati.get("state") == IN_CORSO:
        try:
            pid = int(dati.get("pid") or 0)
        except (ValueError, TypeError):
            pid = 0
        # Il pid 0 e' l'attimo fra lo stato scritto e il processo lanciato;
        # se il lancio e' fallito non deve restare «in corso» per sempre.
        appena = pid == 0 and time.time() - float(dati.get("started") or 0) < 15
        if not appena and not _vivo(pid):
            dati["state"] = INTERROTTO
    return dati


def in_corso(p: Paths | None = None) -> bool:
    s = stato(p)
    return bool(s and s.get("state") == IN_CORSO)


def avvia(richiesta: dict, p: Paths | None = None) -> bool:
    """Lancia `animeup compare` per `richiesta`. False se uno gira gia'."""
    p = p or PATHS
    if in_corso(p):
        return False
    c = cartella(p)
    _scrivi(c / "request.json", richiesta)
    # Lo stato nasce SUBITO, prima che il processo parta: la pagina che si
    # ridisegna un attimo dopo deve gia' vedere "in corso", non il giro
    # vecchio finito.
    _scrivi(c / "status.json", {"state": IN_CORSO, "pid": 0, "file": richiesta["file"],
                                "started": time.time(), "total": 0, "done": 0,
                                "fraction": 0.0, "text": "", "failures": [],
                                "results": []})
    with (c / "compare.log").open("w") as log:
        proc = subprocess.Popen([str(code_root() / "animeup"), "compare"],
                                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    s = stato(p) or {}
    if not s.get("pid"):
        s["pid"] = proc.pid
        _scrivi(c / "status.json", s)
    return True


def ferma(p: Paths | None = None) -> bool:
    """SIGTERM al gruppo del confronto: le clip finite restano in cache."""
    s = stato(p)
    if not s or s.get("state") != IN_CORSO:
        return False
    pid = int(s.get("pid") or 0)
    if pid <= 1 or not _vivo(pid):
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return False
    return True


def esegui(p: Paths | None = None) -> int:
    """Il lavoro vero, nel processo lanciato da `avvia` (`animeup compare`)."""
    from . import library, preview
    from .i18n import t
    from .models import CATALOG
    from .plan import build_plan

    p = p or PATHS
    c = cartella(p)
    richiesta = json.loads((c / "request.json").read_text())
    s = {"state": IN_CORSO, "pid": os.getpid(), "file": richiesta["file"],
         "started": time.time(), "total": 0, "done": 0, "fraction": 0.0,
         "text": "", "failures": [], "results": []}
    _scrivi(c / "status.json", s)

    def fermato(*_a):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, fermato)
    ultimo = [0.0]

    def salva(forza: bool = False) -> None:
        # La sorveglianza dei fotogrammi chiama spesso: su disco una volta
        # al secondo basta alla pagina, che rilegge ogni due.
        adesso = time.monotonic()
        if forza or adesso - ultimo[0] >= 1.0:
            ultimo[0] = adesso
            _scrivi(c / "status.json", s)

    try:
        cfg = richiesta["plan"]
        nota = cfg.get("dedup_nota")
        plan = build_plan(
            library.analyse(Path(richiesta["file"])), target_height=cfg["altezza"],
            crf=cfg["crf"], preset=cfg["preset"], peak_disk_gb=cfg["disco"],
            dedup=cfg["dedup"], denoise=cfg["denoise"], forza=cfg["forza"],
            model_key=cfg["modello"], dedup_nota=tuple(nota) if nota else None)
        candidati = [preview.Candidate(
            kind=preview.Kind(d["kind"]), start_frame=d["start_frame"],
            frames=d["frames"], fps=float(plan.fps), motion=d["motion"],
            brightness=d["brightness"], reason=d["reason"])
            for d in richiesta["clips"]]
        # L'originale ingrandito PRIMA dei modelli: costa secondi e la pagina
        # lo mostra subito, come metro per le versioni che arrivano (tavola
        # CF2b; prima veniva per ultimo e lo spezzone restava vuoto per minuti).
        varianti = sorted(preview.variants_for(*richiesta["models"],
                                               reference=richiesta["reference"]),
                          key=lambda v: not v.is_reference)
        s["total"] = len(candidati) * len(varianti)
        # I pezzi della barra, nell'ordine in cui si fanno: uno per spezzone
        # e versione, largo quanto il TEMPO che si prevede costi (la stessa
        # stima che la pagina annuncia prima del via). A pezzi uguali
        # l'originale, una codifica di secondi, valeva quanto un modello da
        # minuti: la barra correva a meta' e poi restava ferma. L'estrazione
        # dello spezzone sta nel primo pezzo di ogni spezzone (`prep`): e' li'
        # che si aspetta prima che parta qualcosa.
        segmenti = []
        for cand in candidati:
            prep, costi = preview.costi_varianti(plan, cand.frames, varianti)
            for i, (v, (gpu, cod)) in enumerate(zip(varianti, costi)):
                p0 = prep if i == 0 else 0.0
                segmenti.append({"tipo": cand.kind.value, "tc": cand.timecode,
                                 "intervallo": cand.timecode_range,
                                 "chiave": v.key, "peso": p0 + gpu + cod,
                                 "prep": p0, "gpu": gpu, "cod": cod})
        s["segmenti"] = segmenti
        # Le versioni gia' pronte dello spezzone in corso, una per una, con il
        # loro ritaglio: la pagina le mostra senza aspettare le altre.
        s["parziali"] = {}
        salva(True)
        quota = preview.quota_dedup(plan)

        for cand in candidati:
            tipo = t(f"conf.tipo.{cand.kind.value}")
            zona = [None]         # la zona dei ritagli, scelta sulla prima versione
            pezzo = f"{cand.kind.value}|{cand.timecode}"
            s["parziali"][pezzo] = {}
            fine = s["done"] + len(varianti)   # il primo pezzo dello spezzone dopo
            # Finche' non parte la prima variante si estraggono i fotogrammi:
            # nessun numero vero da mostrare, la pagina dice «Preparazione».
            s["fase"] = PREPARA
            s["fraction"] = 0.0
            s["ora_da"] = time.time()
            salva(True)

            def inizia(chiave) -> None:
                s["fase"] = ""
                # L'originale e' solo codifica: comincia subito (vedi `quota_pezzo`).
                s["cod_da"] = time.time() if chiave == "original" else None

            def passo(label: str, _tipo=tipo, _c=cand) -> None:
                s["text"] = f"{_tipo} {_c.timecode} — {label}"
                s["fraction"] = 0.0
                # Da quando gira il pezzo attuale: serve alla stima del tempo.
                s["ora_da"] = time.time()
                salva(True)

            def frazione(fatti: int, attesi: int) -> None:
                s["fraction"] = min(fatti / attesi, 1.0) if attesi else 0.0
                # Fotogrammi tutti prodotti: da qui la codifica, che non conta.
                # Salvato subito: durante la codifica nessuno scrive piu', e
                # con il limite di una scrittura al secondo andava perso.
                if s["fraction"] >= 1.0 and not s.get("cod_da"):
                    s["cod_da"] = time.time()
                    salva(True)
                    return
                salva()

            def finita(chiave=None, file=None, _c=cand, _z=zona, _p=pezzo) -> None:
                if chiave and file:
                    try:
                        ritaglio, _z[0] = preview.ritaglio_provvisorio(file, chiave, _c, _z[0])
                        if ritaglio:
                            s["parziali"][_p][chiave] = str(ritaglio)
                    except Exception:                      # noqa: BLE001
                        pass
                s["done"] += 1
                s["fraction"] = 0.0
                s["cod_da"] = None
                # Dopo l'ultima versione si monta il foglio dei ritagli e poi
                # si estrae lo spezzone dopo: per la pagina e' gia' attesa.
                s["fase"] = PREPARA if s["done"] >= fine else ""
                salva(True)

            # Una clip che non si elabora non porta via le altre: sono
            # indipendenti fra loro.
            try:
                res = preview.render(plan, cand, varianti, on_step=passo,
                                     on_progress=frazione, on_done=finita,
                                     on_start=inizia)
                if res.files:
                    preview.crop_sheet(res, plan)
                    s["results"].append(_riassunto(res, plan, quota, CATALOG))
            except KeyboardInterrupt:
                raise
            except Exception as exc:                       # noqa: BLE001
                s["failures"].append(f"{tipo} {cand.timecode}: {exc}")
            # Uno spezzone fallito a meta' non lascia la barra indietro sui
            # pezzi dei successivi.
            s["done"] = fine
            salva(True)
        s["state"] = FINITO
    except KeyboardInterrupt:
        s["state"] = FERMATO
    except Exception as exc:                               # noqa: BLE001
        s["state"] = FALLITO
        s["failures"].append(str(exc))
    s["ended"] = time.time()
    s["text"] = ""
    _scrivi(c / "status.json", s)
    return 0 if s["state"] == FINITO else 1


def quota_pezzo(s: dict) -> float:
    """Quanto e' avanti il pezzo in corso, 0..1, in tempo: l'estrazione (se
    il pezzo la porta) conta intera appena finita, la GPU per i fotogrammi
    prodotti, la codifica finale sul tempo previsto. Durante l'estrazione
    e' zero: la pagina mostra «Preparazione» invece di un numero."""
    segs = s.get("segmenti") or []
    fatte = int(s.get("done") or 0)
    frazione = float(s.get("fraction") or 0)
    if fatte >= len(segs):
        return 0.0
    g = segs[fatte]
    peso = float(g.get("peso") or 0)
    if peso <= 0:
        return frazione
    if s.get("fase") == PREPARA:
        return 0.0
    fatto = float(g.get("prep") or 0) + float(g.get("gpu") or 0) * frazione
    # La codifica non dice a che punto e': avanza sul tempo previsto, senza
    # passare il 95% (se dura di piu' aspetta li', non arriva al 100% prima).
    # Senza, il numero restava fermo un minuto e poi saltava (63% → 100%).
    cod = float(g.get("cod") or 0)
    if cod > 0 and s.get("cod_da"):
        fatto += cod * min((time.time() - float(s["cod_da"])) / cod, 0.95)
    return min(fatto / peso, 1.0)


def quota(s: dict) -> float:
    """Quanto e' avanti il giro di prova, 0..1, in TEMPO: i pezzi fatti piu'
    la parte di quello in corso, ciascuno col suo peso. E' il numero che si
    legge ovunque — barra, «% del test», scheda — e da cui si stima il tempo
    che manca; la barra disegna i pezzi larghi quanto il loro peso, cosi'
    numero e riempimento tornano.

    Uno stato scritto prima dei pesi si conta a versioni."""
    segs = s.get("segmenti") or []
    fatte = int(s.get("done") or 0)
    pesi = [float(g.get("peso") or 0) for g in segs]
    totale = sum(pesi)
    if totale > 0:
        fatto = sum(pesi[:fatte]) + (pesi[fatte] * quota_pezzo(s) if fatte < len(pesi) else 0)
        return max(0.0, min(fatto / totale, 1.0))
    n = max(int(s.get("total") or 0), 1)
    return min((fatte + float(s.get("fraction") or 0)) / n, 1.0)


def _riassunto(res, plan, quota, catalogo) -> dict:
    """Quello che la pagina mostra di una clip, in una forma da JSON.

    Tipo e intervallo e non il titolo gia' scritto: il titolo si compone al
    disegno, nella lingua di quel momento.
    """
    return {
        "cartella": str(res.folder),
        "file": {k: str(v) for k, v in res.files.items()},
        "foglio": str(res.crop_sheet) if res.crop_sheet else None,
        "ritagli": {k: str(v) for k, v in res.crops.items()},
        "tipo": res.candidate.kind.value,
        "intervallo": res.candidate.timecode_range,
        # Quanto ci ha messo OGNI modello su questa clip e cosa
        # significherebbe sull'episodio intero, deduplica compresa.
        "modelli": [
            {"chiave": k, "nome": catalogo[k].short, "etichetta": catalogo[k].label,
             "secondi": res.tempi[k],
             "intero": res.tempi[k] * plan.frames / max(res.candidate.frames, 1)
                       * (1 - quota[0]),
             "metriche": res.metriche.get(k)}
            for k in _ordine(res)
            if k in catalogo and res.tempi.get(k, 0) >= 5
        ],
        "dedup": list(quota),
    }


def _ordine(res):
    from . import preview
    return preview.ordine_lettura(res.tempi)
