"""Installazione degli strumenti video per l'app nativa, con l'avanzamento.

Gli stessi pacchetti fissati di `setup` (stessi URL, stessi checksum, stesse
verifiche), ma raccontati passo per passo a chi guarda: quale strumento,
quanti byte, e com'e' finita. `setup.vendor_all` resta la via della riga di
comando; questa la usa `animeup serve` (metodo `tools.install`).

Ripresa: lo scaricato parziale vive in `cache/downloads/<nome>.part`, e un
nuovo tentativo chiede al server solo il resto (HTTP Range). Un archivio
finito ma col checksum sbagliato si butta: non si installa mai.
"""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__, setup
from .paths import PATHS

# Le dimensioni da mostrare prima di cominciare (MB, arrotondate), finche'
# il server non dice quelle vere.
DIMENSIONI_MB = {"ffmpeg": 38, "realesrgan": 46, "realcugan": 96}

Avanzamento = Callable[[dict], None]


class Interrotto(Exception):
    pass


@dataclass
class Voce:
    chiave: str          # ffmpeg | realesrgan | realcugan
    binari: tuple[str, ...]


VOCI = (Voce("ffmpeg", ("ffmpeg", "ffprobe")),
        Voce("realesrgan", ("realesrgan-ncnn-vulkan",)),
        Voce("realcugan", ("realcugan-ncnn-vulkan",)))


def mancanti() -> list[str]:
    """Le voci da installare: un binario assente, preso dal sistema, di
    un'altra versione, o senza i suoi modelli."""
    ff = set(setup._ffmpeg_mancanti())
    ncnn = set(setup._ncnn_mancanti())
    fuori = []
    for v in VOCI:
        if any(b in ff or b in ncnn for b in v.binari):
            fuori.append(v.chiave)
    return fuori


def _cartella_parziali() -> Path:
    d = PATHS.cache / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scarica(url: str, nome: str, sha256: str, avanza: Callable[[int, int], None],
            fermo: Callable[[], bool] = lambda: False) -> Path:
    """Scarica `url` in `cache/downloads/<nome>`, riprendendo un `.part`.

    Ritorna il file completo, col checksum verificato. Alza in caso di rete,
    checksum o interruzione; il `.part` resta per la prossima volta (tranne
    col checksum sbagliato, dove si ricomincia da zero).
    """
    finale = _cartella_parziali() / nome
    if finale.is_file() and setup._sha256(finale) == sha256:
        dim = finale.stat().st_size
        avanza(dim, dim)
        return finale
    parziale = finale.with_name(nome + ".part")
    gia = parziale.stat().st_size if parziale.is_file() else 0
    intestazioni = {"User-Agent": f"animeup/{__version__}", "Accept": "*/*"}
    if gia:
        intestazioni["Range"] = f"bytes={gia}-"
    richiesta = urllib.request.Request(url, headers=intestazioni)  # noqa: S310
    try:
        risposta = urllib.request.urlopen(richiesta, timeout=60)  # noqa: S310
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and gia:      # gia' tutto: si verifica sotto
            risposta = None
        else:
            raise
    if risposta is not None:
        with risposta:
            ripresa = gia and risposta.status == 206
            if not ripresa:
                gia = 0
            lunghezza = int(risposta.headers.get("Content-Length") or 0)
            totale = gia + lunghezza if lunghezza else 0
            with parziale.open("ab" if ripresa else "wb") as f:
                fatti = gia
                while True:
                    if fermo():
                        raise Interrotto()
                    blocco = risposta.read(1 << 16)
                    if not blocco:
                        break
                    f.write(blocco)
                    fatti += len(blocco)
                    avanza(fatti, totale or fatti)
    if setup._sha256(parziale) != sha256:
        parziale.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {nome}")
    parziale.replace(finale)
    return finale


def _installa_ffmpeg(avanza, fermo) -> None:
    nomi = ("ffmpeg", "ffprobe")
    fatti: dict[str, tuple[int, int]] = {n: (0, 0) for n in nomi}

    def parziale(nome):
        def f(a, b):
            fatti[nome] = (a, b)
            avanza(sum(x for x, _ in fatti.values()), sum(y for _, y in fatti.values()))
        return f

    PATHS.bin.mkdir(parents=True, exist_ok=True)
    for nome in nomi:
        archivio = scarica(setup.FFMPEG_SOURCES[nome], f"{nome}-{setup.FFMPEG_VERSIONE}.zip",
                           setup.FFMPEG_SHA256[nome], parziale(nome), fermo)
        dest = PATHS.bin / nome
        if not setup._extract(archivio, nome, dest):
            raise ValueError(f"{nome} not found in the archive")
        if not setup._is_static(dest):
            dest.unlink(missing_ok=True)
            raise ValueError(f"{nome} is not a static build")
        if (mancano := setup._capabilities_ok(dest, nome)):
            dest.unlink(missing_ok=True)
            raise ValueError(f"{nome} lacks {', '.join(mancano)}")


def _installa_ncnn(binario: str, avanza, fermo) -> None:
    pacchetto = setup.NCNN_SOURCES[binario]
    archivio = scarica(pacchetto.url, Path(pacchetto.url).name, pacchetto.sha256, avanza, fermo)
    with tempfile.TemporaryDirectory() as tmp:
        estratto = Path(tmp) / "estratto"
        with zipfile.ZipFile(archivio) as z:
            z.extractall(estratto)
        sorgente = estratto / pacchetto.binario
        cartelle = [estratto / c for c in pacchetto.cartelle]
        if not sorgente.is_file() or not all(c.is_dir() for c in cartelle):
            raise ValueError(f"unexpected content in {archivio.name}")
        PATHS.bin.mkdir(parents=True, exist_ok=True)
        dest = PATHS.bin / binario
        shutil.copy2(sorgente, dest)
        dest.chmod(0o755)
        for cartella in cartelle:
            shutil.copytree(cartella, PATHS.bin / cartella.name, dirs_exist_ok=True)


def installa(chiavi: list[str] | None, evento: Avanzamento,
             fermo: Callable[[], bool] = lambda: False) -> bool:
    """Installa le voci chieste (di fabbrica: quelle che mancano).

    Eventi: {"key", "state": "waiting"|"running"|"done"|"failed",
    "bytes", "total", "error"?}. Si ferma alla prima voce che fallisce:
    le altre restano «waiting», e un nuovo giro riparte da li'.
    """
    da_fare = [c for c in (chiavi if chiavi is not None else mancanti())
               if c in {v.chiave for v in VOCI}]
    for chiave in da_fare:
        evento({"key": chiave, "state": "waiting", "bytes": 0,
                "total": DIMENSIONI_MB[chiave] * 1_000_000})
    for chiave in da_fare:
        ultimo = [0.0]

        def avanza(fatti: int, totale: int, chiave=chiave) -> None:
            import time
            adesso = time.monotonic()
            if adesso - ultimo[0] < 0.2 and fatti < totale:
                return
            ultimo[0] = adesso
            evento({"key": chiave, "state": "running", "bytes": fatti, "total": totale})

        evento({"key": chiave, "state": "running", "bytes": 0,
                "total": DIMENSIONI_MB[chiave] * 1_000_000})
        try:
            if chiave == "ffmpeg":
                _installa_ffmpeg(avanza, fermo)
            else:
                binario = {"realesrgan": "realesrgan-ncnn-vulkan",
                           "realcugan": "realcugan-ncnn-vulkan"}[chiave]
                _installa_ncnn(binario, avanza, fermo)
        except Interrotto:
            evento({"key": chiave, "state": "failed", "error": "interrupted"})
            return False
        except Exception as exc:  # noqa: BLE001 - rete, checksum, formato
            evento({"key": chiave, "state": "failed", "error": f"{type(exc).__name__}: {exc}"})
            return False
        evento({"key": chiave, "state": "done"})
    return True
