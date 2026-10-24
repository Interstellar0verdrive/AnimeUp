"""Wrapper sottili su ffmpeg/ffprobe.

Nessuna logica di dominio qui: solo esecuzione, parsing e gestione errori.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

from .paths import PATHS, Paths


class FFmpegError(RuntimeError):
    """ffmpeg/ffprobe ha restituito un errore."""

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str) -> None:
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stderr = stderr.strip()
        tail = "\n".join(self.stderr.splitlines()[-8:])
        super().__init__(f"comando fallito (exit {returncode}):\n{tail}")


def run(cmd: Sequence[str], *, timeout: float | None = None) -> str:
    """Esegue un comando e ritorna stdout, alzando FFmpegError su fallimento."""
    proc = subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, proc.stderr)
    return proc.stdout


def run_stderr(
    cmd: Sequence[str], *, timeout: float | None = None,
    cwd: Path | None = None,
) -> str:
    """Esegue un comando e ritorna stderr, senza considerarlo un errore.

    Alcuni filtri di analisi (idet, cropdetect) scrivono il loro referto su
    stderr anche quando l'esecuzione va a buon fine: qui lo stderr è il dato,
    non la diagnostica.

    `cwd` serve a passare a ffmpeg percorsi RELATIVI: il muxer image2 legge il
    carattere `%` come segnaposto anche in una componente di directory, quindi
    con un disco chiamato "Pieno al 50%" nessun percorso assoluto funziona.
    """
    return run_esito(cmd, timeout=timeout, cwd=cwd)[1]


def run_esito(
    cmd: Sequence[str], *, timeout: float | None = None,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Come run_stderr, ma riporta anche il codice d'uscita.

    Serve a chi usa `-xerror`: lì l'esito È il verdetto (il decoder rifiuta
    invece di inventare), e lo stderr da solo non basta — gli stessi errori
    di decodifica a volte vengono stampati e a volte no, a seconda dei
    thread (misurato: stesso comando, stesso file, un run parla e uno tace).
    """
    proc = subprocess.run(
        list(cmd), capture_output=True, text=True, timeout=timeout,
        cwd=str(cwd) if cwd is not None else None, check=False,
    )
    return proc.returncode, proc.stderr


def stream_lines(cmd: Sequence[str]) -> Iterator[str]:
    """Esegue un comando restituendo stdout riga per riga, senza bufferizzare tutto.

    Serve per gli output lunghi (un hash o un timestamp per frame: centinaia di
    migliaia di righe su un episodio) che non ha senso tenere in memoria.
    """
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None and proc.stderr is not None

    # stderr va svuotato IN PARALLELO alla lettura di stdout. Leggendolo solo
    # alla fine, un processo che scrive molto su stderr (un file danneggiato
    # produce migliaia di righe anche con -v error) riempie il buffer del
    # sistema operativo, si blocca in attesa che qualcuno legga, e noi restiamo
    # in attesa di stdout: stallo perfetto, senza messaggi.
    raccolto: list[str] = []

    def drena() -> None:
        try:
            for riga in proc.stderr:                       # type: ignore[union-attr]
                if len(raccolto) < 400:                    # basta per diagnosticare
                    raccolto.append(riga)
        except (ValueError, OSError):
            pass

    pompa = threading.Thread(target=drena, daemon=True)
    pompa.start()
    try:
        yield from (line.rstrip("\n") for line in proc.stdout)
    finally:
        proc.stdout.close()
        code = proc.wait()
        pompa.join(timeout=5.0)
        try:
            proc.stderr.close()
        except (ValueError, OSError):
            pass
        if code != 0:
            raise FFmpegError(cmd, code, "".join(raccolto))


class FFprobe:
    """Interrogazioni su un file multimediale."""

    def __init__(self, paths: Paths | None = None) -> None:
        self.paths = paths or PATHS

    def _base(self) -> list[str]:
        return [str(self.paths.ffprobe.path), "-v", "error"]

    def json(self, path: Path, *args: str) -> dict:
        cmd = [*self._base(), "-of", "json", *args, str(path)]
        return json.loads(run(cmd) or "{}")

    def format_and_streams(self, path: Path) -> dict:
        """Metadati completi di container e stream. Nessuna decodifica."""
        return self.json(path, "-show_format", "-show_streams", "-show_chapters")

    def video_packets(self, path: Path) -> Iterator[tuple[int | None, int | None]]:
        """(pts, duration) di ogni pacchetto video, in tick di timebase.

        Solo demux: non decodifica nulla, quindi è rapido anche su un film.
        Lavorare in interi evita gli errori di arrotondamento che rendono
        inaffidabile qualunque analisi VFR fatta in virgola mobile.
        """
        cmd = [
            *self._base(),
            "-select_streams", "v:0",
            "-show_entries", "packet=pts,duration",
            "-of", "csv=p=0",
            str(path),
        ]
        for line in stream_lines(cmd):
            if not line:
                continue
            parts = line.split(",")
            pts = _to_int(parts[0]) if parts else None
            dur = _to_int(parts[1]) if len(parts) > 1 else None
            yield pts, dur

    def frame_hashes(self, path: Path, *, video_filter: str | None = None) -> Iterator[str]:
        """Hash di ogni frame decodificato, in ordine di presentazione.

        Usato per individuare i frame identici (animazione "in due"/"in tre")
        e per riconoscere i pattern di telecine e di duplicazione.
        """
        cmd = [str(self.paths.ffmpeg.path), "-v", "error", "-i", str(path), "-an", "-sn", "-dn"]
        if video_filter:
            cmd += ["-vf", video_filter]
        cmd += ["-f", "framehash", "-hash", "murmur3", "-"]
        for line in stream_lines(cmd):
            if not line or line.startswith("#"):
                continue
            yield line.rsplit(",", 1)[-1].strip()


def _to_int(value: str) -> int | None:
    value = value.strip()
    if not value or value == "N/A":
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return None
