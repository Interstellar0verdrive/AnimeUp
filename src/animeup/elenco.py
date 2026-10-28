"""L'elenco dei video dell'app nativa e la coda delle loro analisi.

Nella 1.6 i video erano i file della cartella INPUT; nella 2.0 sono quelli
che l'utente apre o trascina (Open Videos…, una cartella, il Finder), e
restano dove sono. L'elenco vive nello stato (`records/files.json`): id,
percorso e ordine. Le analisi restano nella cache di sempre
(`library.cached_report`), quindi un file gia' analizzato non si rifa'.

La coda delle analisi era `Analizzatore` dentro `ui/app.py`: qui e' del
motore, gira in un thread, un file alla volta (ogni analisi decodifica il
video per intero: due insieme si rubano il disco e non finiscono prima), e
racconta cosa fa con degli eventi (`file.added`, `analysis.started`,
`analysis.done`, `analysis.failed`, `files.changed`).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

from . import library
from .i18n import t
from .paths import PATHS

ESTENSIONI = (".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".webm")

Evento = Callable[[str, dict], None]


def _file_elenco() -> Path:
    return PATHS.logs / "files.json"


def id_di(percorso: Path) -> str:
    return hashlib.sha1(str(percorso).encode("utf-8")).hexdigest()[:12]


def espandi(percorsi: list[str], sottocartelle: bool) -> dict:
    """I video dentro `percorsi` (file o cartelle), e cosa si e' lasciato fuori.

    Ritorna {"files": [Path], "unsupported": n, "missing": [str],
    "empty_folders": [str]}. Le cartelle e i file nascosti si saltano.
    """
    trovati: list[Path] = []
    non_video = 0
    mancanti: list[str] = []
    vuote: list[str] = []
    for grezzo in percorsi:
        p = Path(grezzo).expanduser()
        if p.is_file():
            if p.suffix.lower() in ESTENSIONI:
                trovati.append(p.resolve())
            else:
                non_video += 1
        elif p.is_dir():
            dentro: list[Path] = []
            if sottocartelle:
                for radice, cartelle, nomi in os.walk(p):
                    cartelle[:] = sorted(c for c in cartelle if not c.startswith("."))
                    for nome in sorted(nomi):
                        if nome.startswith("."):
                            continue
                        f = Path(radice) / nome
                        if f.suffix.lower() in ESTENSIONI:
                            dentro.append(f.resolve())
                        else:
                            non_video += 1
            else:
                for f in sorted(p.iterdir()):
                    if f.name.startswith(".") or not f.is_file():
                        continue
                    if f.suffix.lower() in ESTENSIONI:
                        dentro.append(f.resolve())
                    else:
                        non_video += 1
            if not dentro:
                vuote.append(str(p))
            trovati.extend(dentro)
        else:
            mancanti.append(str(p))
    # APFS non distingue maiuscole: due percorsi possono essere lo stesso file.
    visti: dict[str, Path] = {}
    for f in trovati:
        visti.setdefault(str(f).lower(), f)
    return {"files": list(visti.values()), "unsupported": non_video,
            "missing": mancanti, "empty_folders": vuote}


def _riassunto(report) -> dict:
    """Il referto come lo mostra l'app: i campi gia' pronti per una riga e
    per i gruppi Tempi / Immagine / Tracce."""
    tempi = report.timing
    geo = report.geometry
    fps = tempi.fps
    dup = report.duplicates
    from .probe import _fps_str
    return {
        "container": report.container,
        "duration": report.duration,
        "video_codec": report.video_codec,
        "pix_fmt": report.pix_fmt,
        "bit_depth": report.bit_depth,
        "color_space": report.color_space,
        "color_primaries": report.color_primaries,
        "color_transfer": report.color_transfer,
        "audio_tracks": report.audio_tracks,
        "subtitle_tracks": report.subtitle_tracks,
        "subtitle_codecs": list(report.subtitle_codecs),
        "chapters": report.chapters,
        "width": geo.width,
        "height": geo.height,
        "display_width": geo.display_width,
        "display_height": geo.display_height,
        "sar": str(geo.sar),
        "anamorphic": geo.anamorphic,
        "fps": float(fps) if fps else None,
        "fps_text": _fps_str(fps) if fps else None,
        "fps_fraction": f"{fps.numerator}/{fps.denominator}" if fps else None,
        "timebase": tempi.mode.value,
        "frames": tempi.packets,
        "fields": report.fields.mode.value if report.fields else None,
        "dedup_measured": report.dedup_campione,
        "dedup_ratio": dup.duplicate_ratio if dup else None,
        "warnings": report.warnings(),
    }


class Elenco:
    """L'elenco persistente e la sua coda di analisi."""

    def __init__(self, evento: Evento, approfondita: Callable[[], bool]) -> None:
        self._evento = evento
        self._approfondita = approfondita
        self._lock = threading.RLock()
        self._voci: list[dict] = self._leggi()
        self._coda: list[str] = []             # id da analizzare
        self._profonde: set[str] = set()       # id con la misura della deduplica
        self._rifare: set[str] = set()         # id da rifare da capo
        self._in_corso: str | None = None
        self._iniziato: float | None = None
        self._falliti: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        # All'avvio: si rimette in coda cio' che non ha un referto.
        self._accoda([v["id"] for v in self._voci], solo_mancanti=True)

    # --- persistenza ---------------------------------------------------
    def _leggi(self) -> list[dict]:
        try:
            dati = json.loads(_file_elenco().read_text())
        except (OSError, ValueError):
            return []
        voci = dati.get("files") if isinstance(dati, dict) else None
        fuori = []
        for v in voci or []:
            if isinstance(v, dict) and isinstance(v.get("path"), str):
                voce = {"id": v.get("id") or id_di(Path(v["path"])),
                        "path": v["path"], "added": v.get("added") or time.time()}
                if v.get("no_dedup"):
                    voce["no_dedup"] = True
                if isinstance(v.get("model"), str):
                    voce["model"] = v["model"]
                if v.get("height") in (720, 1080, 1440, 2160):
                    voce["height"] = v["height"]
                fuori.append(voce)
        return fuori

    def _scrivi(self) -> None:
        f = _file_elenco()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "files": self._voci}, indent=1, ensure_ascii=False))
        tmp.replace(f)

    # --- lettura -------------------------------------------------------
    def _stato(self, voce: dict) -> dict:
        p = Path(voce["path"])
        fuori: dict = {"id": voce["id"], "path": voce["path"], "name": p.name,
                       "added": voce["added"], "dedup_unmeasurable": bool(voce.get("no_dedup")),
                       "model": voce.get("model"), "height": voce.get("height")}
        try:
            fuori["size"] = p.stat().st_size
            esiste = True
        except OSError:
            fuori["size"] = None
            esiste = False
        report = library.cached_report(p) if esiste else None
        if report is not None:
            fuori["report"] = _riassunto(report)
        if not esiste:
            stato = "missing"
        elif voce["id"] == self._in_corso:
            stato = "analysing"
            fuori["analysis_started"] = self._iniziato
            fuori["deep"] = voce["id"] in self._profonde
        elif voce["id"] in self._coda:
            stato = "queued"
        elif voce["id"] in self._falliti and report is None:
            stato = "failed"
            fuori["error"] = self._falliti[voce["id"]]
        elif report is None:
            stato = "queued"
        else:
            stato = "ready"
        fuori["state"] = stato
        return fuori

    def elenco(self) -> list[dict]:
        with self._lock:
            voci = list(self._voci)
        return [self._stato(v) for v in voci]

    def voce(self, ident: str) -> dict | None:
        with self._lock:
            v = next((v for v in self._voci if v["id"] == ident), None)
        return self._stato(v) if v else None

    def attivita(self) -> dict:
        with self._lock:
            ids = [v["id"] for v in self._voci]
            corso = self._in_corso
            coda = list(self._coda)
        if corso is None:
            return {"running": False}
        da_fare = [i for i in ids if i == corso or i in coda]
        nome = next((Path(v["path"]).name for v in self._voci if v["id"] == corso), "")
        return {"running": True, "id": corso, "name": nome, "started": self._iniziato,
                "index": len(ids) - len(da_fare) + 1, "total": len(ids)}

    # --- modifiche -----------------------------------------------------
    def aggiungi(self, percorsi: list[str], sottocartelle: bool) -> dict:
        esito = espandi(percorsi, sottocartelle)
        nuovi, gia = [], 0
        with self._lock:
            presenti = {v["id"] for v in self._voci}
            for f in esito["files"]:
                ident = id_di(f)
                if ident in presenti:
                    gia += 1
                    continue
                voce = {"id": ident, "path": str(f), "added": time.time()}
                self._voci.append(voce)
                presenti.add(ident)
                nuovi.append(ident)
            if nuovi:
                self._scrivi()
        for ident in nuovi:
            self._evento("file.added", self.voce(ident) or {"id": ident})
        self._accoda(nuovi, solo_mancanti=True)
        if nuovi:
            self._evento("files.changed", {})
        return {"added": nuovi, "already": gia, "unsupported": esito["unsupported"],
                "missing": esito["missing"], "empty_folders": esito["empty_folders"]}

    def togli(self, ids: list[str]) -> dict:
        via = set(ids)
        with self._lock:
            prima = len(self._voci)
            self._voci = [v for v in self._voci if v["id"] not in via]
            self._coda = [i for i in self._coda if i not in via]
            tolti = prima - len(self._voci)
            if tolti:
                self._scrivi()
        if tolti:
            self._evento("files.changed", {})
        return {"removed": tolti}

    def voci(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._voci]

    def scegli(self, ids: list[str], **scelte) -> dict:
        """Modello e/o altezza d'uscita per file. None torna al predefinito."""
        from .models import CATALOG
        via = set(ids)
        with self._lock:
            for v in self._voci:
                if v["id"] not in via:
                    continue
                if "model" in scelte:
                    if scelte["model"] in CATALOG:
                        v["model"] = scelte["model"]
                    else:
                        v.pop("model", None)
                if "height" in scelte:
                    if scelte["height"] in (720, 1080, 1440, 2160):
                        v["height"] = scelte["height"]
                    else:
                        v.pop("height", None)
            self._scrivi()
        self._evento("files.changed", {})
        return {"ok": True}

    def ordina(self, ids: list[str]) -> dict:
        with self._lock:
            per_id = {v["id"]: v for v in self._voci}
            nuovo = [per_id[i] for i in ids if i in per_id]
            nuovo += [v for v in self._voci if v["id"] not in set(ids)]
            self._voci = nuovo
            self._scrivi()
        self._evento("files.changed", {})
        return {"ok": True}

    def rianalizza(self, ids: list[str] | None) -> dict:
        with self._lock:
            tutti = [v["id"] for v in self._voci]
            scelti = tutti if ids is None else [i for i in ids if i in set(tutti)]
            for v in self._voci:
                if v["id"] in set(scelti):
                    v.pop("no_dedup", None)
            for i in scelti:
                self._rifare.add(i)
                self._falliti.pop(i, None)
        self._accoda(scelti, solo_mancanti=False)
        self._evento("files.changed", {})
        return {"queued": len(scelti)}

    def approfondisci(self, ids: list[str]) -> dict:
        with self._lock:
            for i in ids:
                self._profonde.add(i)
        self._accoda(ids, solo_mancanti=False)
        self._evento("files.changed", {})
        return {"queued": len(ids)}

    def aspetta(self, limite: float = 600) -> None:
        fine = time.monotonic() + limite
        while time.monotonic() < fine:
            with self._lock:
                filo = self._thread
            if filo is None or not filo.is_alive():
                return
            filo.join(timeout=0.5)

    # --- la coda -------------------------------------------------------
    def _accoda(self, ids: list[str], *, solo_mancanti: bool) -> None:
        profonda = self._approfondita()
        with self._lock:
            per_id = {v["id"]: v for v in self._voci}
        da_fare = []
        for i in ids:
            v = per_id.get(i)
            if v is None:
                continue
            if solo_mancanti:
                r = library.cached_report(Path(v["path"]))
                if r is not None and not (profonda and r.dedup_campione is None
                                          and not v.get("no_dedup")
                                          and i not in self._falliti):
                    continue
            da_fare.append(i)
        with self._lock:
            for i in da_fare:
                if profonda:
                    self._profonde.add(i)
                if i != self._in_corso and i not in self._coda:
                    self._coda.append(i)
            if self._coda and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._lavora, daemon=True,
                                                name="analysis")
                self._thread.start()

    def _lavora(self) -> None:
        while True:
            with self._lock:
                if not self._coda:
                    self._in_corso = None
                    self._iniziato = None
                    return
                ident = self._coda.pop(0)
                voce = next((v for v in self._voci if v["id"] == ident), None)
                if voce is None:
                    continue
                self._in_corso = ident
                self._iniziato = time.time()
                profonda = ident in self._profonde
                da_capo = ident in self._rifare
                self._rifare.discard(ident)
            p = Path(voce["path"])
            self._evento("analysis.started", {"id": ident, "name": p.name,
                                              "started": self._iniziato, "deep": profonda,
                                              **self.attivita()})
            try:
                if not p.is_file():
                    raise FileNotFoundError(t("nat.files.missing_file"))
                if da_capo or library.cached_report(p) is None:
                    library.analyse(p, force=True)
                    if profonda:
                        # Il referto veloce prima: l'app lo mostra mentre
                        # la misura della deduplica continua.
                        self._evento("analysis.progress", {"id": ident, "stage": "measuring",
                                                           "file": self._stato(voce)})
                if profonda:
                    esito = library.approfondisci(p)
                    if esito is None or esito.dedup_campione is None:
                        # Troppo corto per misurare: non si riprova a ogni
                        # avvio (si ricorda nell'elenco).
                        with self._lock:
                            voce["no_dedup"] = True
                            self._scrivi()
            except Exception as exc:  # noqa: BLE001 - un file rotto non ferma la coda
                with self._lock:
                    self._falliti[ident] = f"{exc}"
                    self._profonde.discard(ident)
                    self._in_corso = None
                self._evento("analysis.failed", {"id": ident, "error": str(exc)})
                continue
            with self._lock:
                self._profonde.discard(ident)
                self._in_corso = None
            self._evento("analysis.done", self._stato(voce))
