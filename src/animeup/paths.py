"""Risoluzione dei percorsi del progetto.

Regola d'oro: tutto vive dentro la cartella del progetto. Nessun percorso
assoluto verso il sistema, così la cartella resta spostabile fra Mac diversi.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


def project_root() -> Path:
    """Radice del progetto: la cartella che contiene bin/, src/, INPUT/..."""
    env = os.environ.get("ANIMEUP_ROOT")
    if env:
        return Path(env).resolve()
    # src/animeup/paths.py -> src/animeup -> src -> root
    return Path(__file__).resolve().parents[2]


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

    # --- cartelle ---------------------------------------------------------
    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def models(self) -> Path:
        return self.bin / "models"

    @property
    def input(self) -> Path:
        return self.root / "INPUT"

    @property
    def output(self) -> Path:
        return self.root / "OUTPUT"

    # Convenzione dei nomi su disco (voluta dall'utente): MAIUSCOLO per le
    # cartelle che l'utente tocca (INPUT, OUTPUT, JOBS), minuscolo per
    # quelle interne (anteprime, registri). I nomi qui sono l'unica verità:
    # nessun altro punto del codice li conosce per esteso.

    @property
    def logs(self) -> Path:
        return self.root / "registri"

    @property
    def work(self) -> Path:
        """Working dir dei job: chunk, frame, stato per il resume.

        MAIUSCOLA e col nome della scheda della UI: è qui che vivono le
        lavorazioni interrotte riprendibili, ed è una cartella che l'utente
        ha il diritto di guardare (e di pesare, quando occupa 19 GB).
        """
        return self.root / "JOBS"

    @property
    def previews(self) -> Path:
        return self.root / "anteprime"

    def ensure_dirs(self) -> None:
        # Fino alla 1.3.2 la cartella delle lavorazioni si chiamava
        # LAVORAZIONI: con l'interfaccia in inglese e' diventata JOBS. Una
        # cartella vecchia si rinomina e basta, cosi' le lavorazioni
        # interrotte restano dove l'app le cerca.
        vecchia = self.root / "LAVORAZIONI"
        if vecchia.is_dir() and not self.work.exists():
            vecchia.rename(self.work)
        for d in (self.input, self.output, self.logs, self.work, self.previews):
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
