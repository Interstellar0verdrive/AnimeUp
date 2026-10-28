"""Il Confronto per l'app nativa: spezzoni, modelli, prova, risultati.

Riusa i pezzi della 1.6: `preview.find_candidates` (con il deposito degli
spezzoni gia' trovati e le miniature), `confronto.avvia/ferma/stato` (la prova
in un processo staccato, `animeup compare`). Qui si aggiungono:

- la scansione in un thread, con eventi (`compare.scan.progress/done/failed`);
- lo stato del percorso per file (spezzoni scelti, modelli), su disco;
- copie `.mp4` (hvc1) delle clip, che AVPlayer sa riprodurre: le prove restano
  `.mkv` come per la riga di comando, la copia e' un remux senza ricodifica.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import impostazioni, library, preview
from .models import CATALOG
from .paths import PATHS

Evento = Callable[[str, dict], None]


def _file_stato() -> Path:
    return PATHS.logs / "compare.json"


def leggi_stati() -> dict:
    try:
        d = json.loads(_file_stato().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def salva_stato(ident: str, dati: dict) -> dict:
    tutti = leggi_stati()
    tutti[ident] = {**(tutti.get(ident) or {}), **dati}
    f = _file_stato()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(tutti, indent=1))
    return tutti[ident]


def _piano(voce: dict):
    from .plan import build_plan
    from . import piani
    report = library.cached_report(Path(voce["path"]))
    if report is None:
        raise ValueError("not analysed yet")
    cfg = impostazioni.carica_native()
    pl = piani.piano(Path(voce["path"]), cfg, modello=voce.get("model"), altezza=voce.get("height"))
    modello = pl.get("model")
    if not modello:
        raise ValueError(pl.get("error") or "no plan")
    plan = build_plan(report, target_height=voce.get("height") or cfg["altezza"], crf=cfg["crf"],
                      preset=cfg["preset"], peak_disk_gb=cfg["disco"], dedup=cfg["dedup"],
                      denoise=cfg["denoise"], forza=cfg["forza"], model_key=modello,
                      paths=piani._paths_lavoro(),
                      dedup_nota=report.dedup_campione if cfg["dedup"] else None)
    return plan, cfg, modello


def _miniatura(plan, cand) -> str | None:
    base = PATHS.previews / "clips" / f"{plan.source.path.stem[:60]}_{cand.slug}"
    jpg = base.with_suffix(".jpg")
    if not jpg.is_file():
        try:
            preview.thumbnail(plan, cand, jpg, width=480)
        except Exception:  # noqa: BLE001
            return None
    return str(jpg) if jpg.is_file() else None


def _clip(c, miniatura: str | None) -> dict:
    return {"kind": c.kind.value, "start_frame": c.start_frame, "frames": c.frames,
            "start": round(c.start_seconds, 2), "range": c.timecode_range,
            "motion": c.motion, "brightness": c.brightness, "reason": c.reason,
            "thumbnail": miniatura}


def clips(voce: dict) -> dict:
    """Gli spezzoni gia' trovati per questo file (dal deposito), senza scansionare."""
    plan, _cfg, _m = _piano(voce)
    trovati = preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS, PATHS)
    stato = leggi_stati().get(voce["id"]) or {}
    return {"id": voce["id"], "clips": [_clip(c, _miniatura(plan, c)) for c in trovati],
            "selected": stato.get("clips"), "exhausted": bool(stato.get("exhausted")),
            "duration": plan.source.duration}


_scansioni: set[str] = set()
_lock = threading.Lock()


def scansiona(voce: dict, evento: Evento, *, altri: bool = False) -> dict:
    """Cerca (altri) spezzoni in un thread; risponde subito."""
    ident = voce["id"]
    with _lock:
        if ident in _scansioni:
            return {"started": False, "reason": "already_running"}
        _scansioni.add(ident)

    def lavora() -> None:
        try:
            plan, _cfg, _m = _piano(voce)
            avuti = preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS, PATHS)
            if avuti and not altri:
                evento("compare.scan.done", clips(voce))
                return
            evento("compare.scan.progress", {"id": ident, "text": "", "started": time.time()})
            nuovi = preview.find_candidates(
                plan, per_kind=2, escludi=tuple(c.start_frame for c in avuti),
                on_step=lambda testo: evento("compare.scan.progress", {"id": ident, "text": testo}))
            nuovi = preview.solo_nuovi(avuti, nuovi or [])
            tutti = avuti + nuovi
            preview.scrivi_deposito(plan, tutti, 2, preview.DEFAULT_SECONDS, PATHS)
            if altri and not nuovi:
                salva_stato(ident, {"exhausted": True})
            for c in nuovi:
                _miniatura(plan, c)
            fuori = clips(voce)
            fuori["new"] = len(nuovi)
            evento("compare.scan.done", fuori)
        except Exception as exc:  # noqa: BLE001
            evento("compare.scan.failed", {"id": ident, "error": f"{exc}"})
        finally:
            with _lock:
                _scansioni.discard(ident)

    threading.Thread(target=lavora, daemon=True, name=f"scan-{ident}").start()
    return {"started": True}


def modelli(voce: dict, scelti: list[int] | None) -> dict:
    """Il passo dei modelli: banda guida, schede con giudizio, ritmo e stima."""
    from . import piani, taratura
    from .models import recommend
    plan, cfg, modello = _piano(voce)
    report = plan.source
    pl = piani.piano(Path(voce["path"]), cfg, modello=voce.get("model"), altezza=voce.get("height"))
    trovati = preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS, PATHS)
    scelte = [c for c in trovati if scelti is None or c.start_frame in scelti]
    consiglio = recommend(report.geometry.display_height)
    schede = []
    for m in pl.get("models") or []:
        chiave = m["key"]
        ritmo = taratura.throughput(chiave, preview.scale_for(chiave, plan) if not m.get("unreachable") else 2,
                                    mpx=report.geometry.width * report.geometry.height / 1e6)
        schede.append({**m, "fps": round(ritmo / (report.geometry.width * report.geometry.height / 1e6), 2)
                       if ritmo else None,
                       "clip_seconds": round(preview.estimate_seconds(plan, scelte, [preview.Variant(chiave)]))
                       if scelte and not m.get("unreachable") else None})
    return {"id": voce["id"], "models": schede, "recommended": consiglio.model, "reason": consiglio.reason,
            "sure": consiglio.sicuro, "height": plan.target_height, "source_height": report.geometry.display_height,
            "reference_seconds": round(preview.estimate_seconds(plan, scelte, [preview.REFERENCE]))
            if scelte else None, "clips": len(scelte), "calibrated": taratura.carica() is not None}


def avvia(voce: dict, clip_scelte: list[int], chiavi: list[str], originale: bool) -> dict:
    from . import confronto
    plan, cfg, modello = _piano(voce)
    trovati = {c.start_frame: c for c in preview.leggi_deposito(plan, 2, preview.DEFAULT_SECONDS, PATHS)}
    scelte = [trovati[s] for s in clip_scelte if s in trovati]
    if not scelte:
        raise ValueError("no clips")
    report = plan.source
    richiesta = {
        "file": str(report.path),
        "id": voce["id"],
        "plan": {"altezza": plan.target_height, "crf": cfg["crf"], "preset": cfg["preset"],
                 "disco": cfg["disco"], "dedup": cfg["dedup"], "denoise": cfg["denoise"],
                 "forza": cfg["forza"], "modello": modello,
                 "dedup_nota": None},
        "clips": [{"kind": c.kind.value, "start_frame": c.start_frame, "frames": c.frames,
                   "motion": c.motion, "brightness": c.brightness, "reason": c.reason} for c in scelte],
        "models": [k for k in chiavi if k in CATALOG],
        "reference": bool(originale),
    }
    salva_stato(voce["id"], {"clips": clip_scelte, "models": chiavi, "reference": originale})
    if not confronto.avvia(richiesta):
        raise RuntimeError("busy")
    return {"started": True}


def stato() -> dict | None:
    from . import confronto
    s = confronto.stato()
    if not s:
        return None
    s = dict(s)
    s["quota"] = confronto.quota(s)
    try:
        s["request"] = json.loads((confronto.cartella() / "request.json").read_text())
    except (OSError, ValueError):
        s["request"] = None
    s["log"] = str(confronto.cartella() / "compare.log")
    return s


def riproducibile(percorso: str) -> str:
    """Una copia .mp4 (hvc1) del file, per AVPlayer. Remux, niente ricodifica."""
    src = Path(percorso)
    dst = src.with_suffix(".mp4")
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return str(dst)
    tmp = dst.with_name(dst.stem + ".tmp.mp4")
    sonda = subprocess.run([str(PATHS.ffprobe.path), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True, check=False).stdout.strip()
    tag = ["-tag:v", "hvc1"] if sonda == "hevc" else []
    esito = subprocess.run([str(PATHS.ffmpeg.path), "-hide_banner", "-v", "error", "-y", "-i", str(src),
                            "-map", "0:v:0", "-c", "copy", *tag, "-movflags", "+faststart", str(tmp)],
                           capture_output=True, text=True, check=False)
    if esito.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(esito.stderr.strip()[-300:] or "remux failed")
    tmp.replace(dst)
    return str(dst)
