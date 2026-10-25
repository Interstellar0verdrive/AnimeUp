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
        varianti = preview.variants_for(*richiesta["models"],
                                        reference=richiesta["reference"])
        s["total"] = len(candidati) * len(varianti)
        salva(True)
        quota = preview.quota_dedup(plan)

        for cand in candidati:
            tipo = t(f"conf.tipo.{cand.kind.value}")

            def passo(label: str, _tipo=tipo, _c=cand) -> None:
                s["text"] = f"{_tipo} {_c.timecode} — {label}"
                s["fraction"] = 0.0
                salva(True)

            def frazione(fatti: int, attesi: int) -> None:
                s["fraction"] = min(fatti / attesi, 1.0) if attesi else 0.0
                salva()

            def finita() -> None:
                s["done"] += 1
                s["fraction"] = 0.0
                salva(True)

            # Una clip che non si elabora non porta via le altre: sono
            # indipendenti fra loro.
            try:
                res = preview.render(plan, cand, varianti, on_step=passo,
                                     on_progress=frazione, on_done=finita)
                if res.files:
                    preview.crop_sheet(res, plan)
                    s["results"].append(_riassunto(res, plan, quota, CATALOG))
            except KeyboardInterrupt:
                raise
            except Exception as exc:                       # noqa: BLE001
                s["failures"].append(f"{tipo} {cand.timecode}: {exc}")
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


def _riassunto(res, plan, quota, catalogo) -> dict:
    """Quello che la pagina mostra di una clip, in una forma da JSON.

    Tipo e intervallo e non il titolo gia' scritto: il titolo si compone al
    disegno, nella lingua di quel momento.
    """
    return {
        "cartella": str(res.folder),
        "file": {k: str(v) for k, v in res.files.items()},
        "foglio": str(res.crop_sheet) if res.crop_sheet else None,
        "tipo": res.candidate.kind.value,
        "intervallo": res.candidate.timecode_range,
        # Quanto ci ha messo OGNI modello su questa clip e cosa
        # significherebbe sull'episodio intero, deduplica compresa.
        "modelli": [
            {"chiave": k, "nome": catalogo[k].short,
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
