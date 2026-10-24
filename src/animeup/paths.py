"""Risoluzione dei percorsi del progetto.

Tre posti, scelti indipendentemente:
  - INPUT, i video da elaborare (ANIMEUP_INPUT);
  - OUTPUT, i video finiti, con accanto i log di ogni file (`logs/`) e le
    lavorazioni in corso o interrotte (`JOBS/`), che stanno sullo stesso
    disco perche' e' li' che serve lo spazio (ANIMEUP_OUTPUT);
  - lo STATO, cio' che serve all'app nel tempo: registri, impostazioni,
    taratura e cache (ANIMEUP_STATO).
Senza variabili tutto sta dentro la cartella del programma (o in
ANIMEUP_ROOT), cosi' la cartella portatile resta spostabile fra Mac diversi.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


def code_root() -> Path:
    """La cartella del programma: lanciatore, sorgenti e bin/."""
    # src/animeup/paths.py -> src/animeup -> src -> root
    return Path(__file__).resolve().parents[2]


def stato_root() -> Path:
    """Dove vive cio' che AnimeUp scarica: per i binari, la cartella bin/.

    Di fabbrica coincide col programma. L'app per macOS la sposta in
    ~/Library/Application Support/AnimeUp (variabile ANIMEUP_STATO, impostata
    dal lanciatore), perche' il pacchetto .app non si modifica.
    """
    env = os.environ.get("ANIMEUP_STATO")
    return Path(env).resolve() if env else code_root()


def project_root() -> Path:
    """La radice di partenza: INPUT/ e OUTPUT/ stanno qui se non scelti.

    Coincide con quella del programma, salvo un ANIMEUP_ROOT impostato. E'
    anche dove le versioni prima della 1.6 tenevano tutto, ed e' da qui che
    `migrazione` riprende registri e lavorazioni.
    """
    env = os.environ.get("ANIMEUP_ROOT")
    if env:
        return Path(env).resolve()
    return code_root()


def gb_liberi(cartella: Path) -> float:
    """Lo spazio libero sul disco di `cartella`, in GB.

    La cartella puo' non esistere ancora (OUTPUT appena scelto, JOBS mai
    usato): si misura sul primo antenato che c'e', che sta sullo stesso disco.
    """
    for candidata in (cartella, *cartella.parents):
        if candidata.exists():
            return shutil.disk_usage(candidata).free / 1_073_741_824
    return shutil.disk_usage("/").free / 1_073_741_824


class MissingToolError(RuntimeError):
    """Un binario indispensabile non è stato trovato."""


@dataclass(frozen=True)
class Tool:
    """Un binario esterno, con l'informazione su dove è stato trovato."""

    name: str
    path: Path
    vendored: bool

    def __str__(self) -> str:  # pragma: no cover - solo diagnostica
        return str(self.path)


class Paths:
    """Percorsi del progetto e localizzazione dei binari esterni."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or project_root()).resolve()
        self._radice_esplicita = root is not None
        # I binari stanno col PROGRAMMA, non coi dati. Con ANIMEUP_ROOT su una
        # cartella di soli dati si cercavano dentro di lei, dove non ci sono:
        # si ripiegava su quelli di sistema (o su niente), mentre lanciatore e
        # setup li mettono accanto al codice. Una radice passata a mano (test,
        # strumenti) resta invece autosufficiente, bin/ compreso.
        self._bin = (self.root if root is not None else stato_root()) / "bin"
        # Le cartelle scelte dall'utente valgono solo per la radice di
        # sistema: una radice passata a mano (test, strumenti) resta tutta
        # dentro se stessa.
        def _scelta(nome: str) -> Path | None:
            valore = None if self._radice_esplicita else os.environ.get(nome)
            return Path(valore).expanduser().resolve() if valore else None

        self._input = _scelta("ANIMEUP_INPUT") or self.root / "INPUT"
        self._output = _scelta("ANIMEUP_OUTPUT") or self.root / "OUTPUT"
        # Lo stato segue ANIMEUP_STATO (l'app: Application Support); senza,
        # resta con i dati, come prima della 1.6.
        self._stato = _scelta("ANIMEUP_STATO") or self.root

    # --- cartelle ---------------------------------------------------------
    @property
    def bin(self) -> Path:
        return self._bin

    @property
    def campioni(self) -> Path:
        """I clip liberi della taratura: viaggiano col programma."""
        return (self.root if self._radice_esplicita else code_root()) / "samples"

    @property
    def models(self) -> Path:
        return self.bin / "models"

    @property
    def input(self) -> Path:
        return self._input

    @property
    def output(self) -> Path:
        return self._output

    # Convenzione dei nomi su disco (voluta dall'utente): MAIUSCOLO per le
    # cartelle che l'utente tocca (INPUT, OUTPUT, JOBS), minuscolo per
    # quelle interne. Tutto in inglese, qualunque sia la lingua scelta: chi
    # apre il Finder deve capire senza sapere l'italiano. I nomi qui sono
    # l'unica verità: nessun altro punto del codice li conosce per esteso.

    @property
    def stato(self) -> Path:
        return self._stato

    @property
    def logs(self) -> Path:
        """I registri dell'app: storico, lanci, impostazioni, taratura."""
        return self._stato / "records"

    @property
    def job_logs(self) -> Path:
        """Il log di ogni file lavorato, accanto ai video finiti.

        Nessuna stima li legge: raccontano la singola lavorazione, e chi la
        cerca la cerca dove ha trovato il video.
        """
        return self._output / "logs"

    @property
    def work(self) -> Path:
        """Working dir dei job: chunk, frame, stato per il resume.

        MAIUSCOLA e col nome della scheda della UI: è qui che vivono le
        lavorazioni interrotte riprendibili, ed è una cartella che l'utente
        ha il diritto di guardare (e di pesare, quando occupa 19 GB). Sta
        dentro OUTPUT perche' lo spazio che chiede e' quello del disco dei
        video finiti.
        """
        return self._output / "JOBS"

    @property
    def cache(self) -> Path:
        return self._stato / "cache"

    @property
    def previews(self) -> Path:
        """Le clip del confronto."""
        return self.cache / "previews"

    @property
    def analisi(self) -> Path:
        """Il referto di ogni sorgente analizzato."""
        return self.cache / "analysis"

    # --- i file dei registri ---------------------------------------------
    @property
    def storico(self) -> Path:
        return self.logs / "history.jsonl"

    @property
    def lanci(self) -> Path:
        return self.logs / "launches.jsonl"

    @property
    def impostazioni(self) -> Path:
        return self.logs / "settings.json"

    @property
    def taratura(self) -> Path:
        return self.logs / "calibration.json"

    @property
    def registro_coda(self) -> Path:
        """L'uscita del terminale dell'ultima coda lanciata dall'interfaccia."""
        return self.logs / "queue.log"

    def ensure_dirs(self) -> None:
        from .migrazione import migra

        migra(self)
        for d in (self.input, self.output, self.logs, self.work,
                  self.previews, self.analisi):
            d.mkdir(parents=True, exist_ok=True)

    # --- binari esterni ---------------------------------------------------
    def _find(self, name: str, *, required: bool = True) -> Tool | None:
        """Cerca prima in bin/ (portabile), poi nel PATH (comodo ma non portabile)."""
        vendored = self.bin / name
        if vendored.is_file() and os.access(vendored, os.X_OK):
            return Tool(name, vendored, vendored=True)

        system = shutil.which(name)
        if system:
            return Tool(name, Path(system), vendored=False)

        if required:
            # Import qui e non in testa: vedi `i18n.preferita`, che importa
            # `paths` a sua volta.
            from .i18n import t

            raise MissingToolError(t("mot.paths.binario_mancante", nome=name,
                                     cartella=self.bin))
        return None

    @cached_property
    def ffmpeg(self) -> Tool:
        return self._find("ffmpeg")  # type: ignore[return-value]

    @cached_property
    def ffprobe(self) -> Tool:
        return self._find("ffprobe")  # type: ignore[return-value]

    @cached_property
    def realesrgan(self) -> Tool:
        return self._find("realesrgan-ncnn-vulkan")  # type: ignore[return-value]

    @cached_property
    def realcugan(self) -> Tool:
        return self._find("realcugan-ncnn-vulkan")  # type: ignore[return-value]

    def portability_report(self) -> list[tuple[str, Tool | None, str]]:
        """Stato di portabilità di ogni dipendenza esterna.

        Ritorna (nome, tool, stato) con stato in {ok, sistema, mancante}.
        """
        rows: list[tuple[str, Tool | None, str]] = []
        for name in ("ffmpeg", "ffprobe", "realesrgan-ncnn-vulkan", "realcugan-ncnn-vulkan"):
            try:
                tool = self._find(name, required=False)
            except MissingToolError:  # pragma: no cover - required=False non alza
                tool = None
            if tool is None:
                rows.append((name, None, "mancante"))
            elif tool.vendored:
                rows.append((name, tool, "ok"))
            else:
                rows.append((name, tool, "sistema"))
        return rows


PATHS = Paths()
