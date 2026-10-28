"""I piani e le stime dei file dell'elenco, per l'app nativa (metodo `plans.get`).

Per ogni file analizzato: il modello scelto (di fabbrica quello consigliato
per la risoluzione), il giudizio su ogni modello («ok», «verifica», «no»,
oppure non raggiungibile con il perche'), e il piano vero di `build_plan`
con la sua stima. Le scelte per file (modello, altezza d'uscita) vivono
nell'elenco (`elenco.Elenco.scegli`).

Lo spazio si misura sulla cartella di lavoro scelta nell'app: e' li' che
vanno fotogrammi e blocchi. I video finiti vanno accanto agli originali.
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import impostazioni, library, taratura
from .models import CATALOG, recommend
from .paths import PATHS
from .plan import PlanError, build_plan


def _paths_lavoro():
    """Una copia di PATHS con OUTPUT sulla cartella di lavoro: build_plan
    misura lo spazio libero su `output`."""
    p = copy.copy(PATHS)
    p._output = impostazioni.cartella_lavoro()
    return p


def piano(percorso: Path, cfg: dict, *, modello: str | None, altezza: int | None) -> dict:
    report = library.cached_report(percorso)
    if report is None:
        return {"ready": False}
    p = _paths_lavoro()
    h_uscita = altezza or cfg["altezza"]
    consiglio = recommend(report.geometry.display_height)
    giudizi = consiglio.giudizi or {}

    def costruisci(chiave: str):
        return build_plan(report, target_height=h_uscita, crf=cfg["crf"], preset=cfg["preset"],
                          peak_disk_gb=cfg["disco"], dedup=cfg["dedup"], denoise=cfg["denoise"],
                          forza=cfg["forza"], model_key=chiave, paths=p,
                          dedup_nota=report.dedup_campione if cfg["dedup"] else None)

    modelli = []
    piani = {}
    for chiave, m in CATALOG.items():
        voce = {"key": chiave, "label": m.label, "verdict": giudizi.get(chiave)}
        try:
            pl = costruisci(chiave)
            piani[chiave] = pl
            voce["estimate"] = round(pl.est_attesa_seconds)
        except PlanError as exc:
            voce["unreachable"] = getattr(exc, "sintesi", None) or str(exc)
        modelli.append(voce)

    scelto = modello if modello in piani else (consiglio.model if consiglio.model in piani
                                                else next(iter(piani), None))
    fuori = {"ready": True, "recommended": consiglio.model, "reason": consiglio.reason,
             "sure": consiglio.sicuro, "models": modelli, "model": scelto,
             "height": h_uscita, "height_is_default": altezza is None,
             "verdict": giudizi.get(scelto) if scelto else None}
    if scelto is None:
        errori = [v.get("unreachable") for v in modelli if v.get("unreachable")]
        fuori["error"] = errori[0] if errori else "no plan"
        return fuori
    pl = piani[scelto]
    fuori.update({
        "estimate": round(pl.est_attesa_seconds),
        "estimate_best": round(pl.est_best_seconds),
        "estimate_worst": round(pl.est_total_seconds),
        "calibrated": pl.stime_tarate,
        "model_label": pl.model.label,
        "scale": pl.model_scale,
        "downscale": round(pl.downscale, 3),
        "model_width": pl.model_width,
        "model_height": pl.model_height,
        "output_width": pl.target_width,
        "output_height": pl.target_height,
        "frames": pl.frames,
        "chunks": pl.chunks,
        "chunk_size": pl.chunk_size,
        "codec": pl.encoding.codec,
        "pix_fmt": pl.encoding.pix_fmt,
        "crf": pl.encoding.crf,
        "preset": pl.encoding.preset,
        "restoration": pl.restoration.chain(),
        "dedup": pl.dedup.enabled,
        "dedup_ratio": pl.dedup.expected_ratio,
        "dedup_measured": pl.dedup.misurata or report.dedup_campione is not None,
        "output_name": pl.output.name,
        "output_folder": str(percorso.parent),
        "peak_disk_gb": round(pl.est_peak_disk_gb, 1),
        "warnings": list(pl.warnings),
        "disk_warnings": list(pl.avvisi_disco),
    })
    return fuori


def piani(voci: list[dict]) -> dict:
    """I piani di tutte le voci analizzate: {id: piano}, piu' la taratura."""
    cfg = impostazioni.carica_native()
    fuori = {}
    for v in voci:
        try:
            fuori[v["id"]] = piano(Path(v["path"]), cfg, modello=v.get("model"),
                                   altezza=v.get("height"))
        except Exception as exc:  # noqa: BLE001 - un file non deve far cadere gli altri
            fuori[v["id"]] = {"ready": True, "error": f"{type(exc).__name__}: {exc}", "models": []}
    voce_tar = taratura.carica()
    return {"plans": fuori, "calibrated_when": float(voce_tar["quando"]) if voce_tar else None}
