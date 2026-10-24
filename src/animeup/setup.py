"""Vendorizzazione dei binari esterni (e dei modelli) dentro bin/.

Perché serve: l'ffmpeg di Homebrew è collegato dinamicamente a decine di
librerie in /opt/homebrew. Copiarlo non basta, e su un Mac senza Homebrew non
parte. Serve una build statica, che non dipende da nulla di esterno.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from . import __version__
from .i18n import t
from .paths import PATHS

# Build statiche per macOS arm64, verificate: Mach-O arm64 con zero dipendenze
# fuori da /usr/lib e /System, quindi funzionanti su un Mac senza Homebrew.
# (evermeet.cx, il canale più noto, è esplicitamente solo Intel.)
FFMPEG_SOURCES: dict[str, str] = {
    "ffmpeg": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/snapshot/ffmpeg.zip",
    "ffprobe": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/snapshot/ffprobe.zip",
}

@dataclass(frozen=True)
class Pacchetto:
    """Una release upstream fissata: URL, checksum e cosa prenderne."""

    url: str
    sha256: str
    binario: str                # percorso del binario dentro l'archivio
    cartelle: tuple[str, ...]   # cartelle di modelli da copiare in bin/


# Release ufficiali, verificate byte per byte contro i binari con cui sono
# state fatte le tarature. Sono le ultime pubblicate: i progetti sono fermi
# dal 2022, quindi fissarle non fa perdere aggiornamenti.
NCNN_SOURCES: dict[str, Pacchetto] = {
    "realesrgan-ncnn-vulkan": Pacchetto(
        url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
            "realesrgan-ncnn-vulkan-20220424-macos.zip",
        sha256="e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a",
        binario="realesrgan-ncnn-vulkan",
        cartelle=("models",),
    ),
    "realcugan-ncnn-vulkan": Pacchetto(
        url="https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/"
            "realcugan-ncnn-vulkan-20220728-macos.zip",
        sha256="0df908cbb98b480f85897221b96d37b0bdb70f82d81b2c7037fe950dd5c0fa33",
        binario="realcugan-ncnn-vulkan-20220728-macos/realcugan-ncnn-vulkan",
        cartelle=tuple(
            f"realcugan-ncnn-vulkan-20220728-macos/{d}"
            for d in ("models-se", "models-pro", "models-nose")
        ),
    ),
}


# Cio' che la pipeline usa davvero: se una build ne fosse priva, meglio
# accorgersene adesso che a metà di un batch da venti ore.
REQUIRED_ENCODERS = ("libx265", "libx264")
REQUIRED_FILTERS = (
    "idet", "cropdetect", "mpdecimate", "signalstats",
    "tblend", "bwdif", "fieldmatch", "decimate", "psnr", "scale",
)


def _is_static(binary: Path) -> bool:
    """Un binario è portabile se dipende solo dalle librerie di sistema."""
    try:
        out = subprocess.run(
            ["otool", "-L", str(binary)], capture_output=True, text=True, check=False
        ).stdout
    except FileNotFoundError:
        return False
    deps = [
        line.strip().split(" ")[0]
        for line in out.splitlines()[1:]
        if line.strip()
    ]
    return all(
        d.startswith("/usr/lib/") or d.startswith("/System/") for d in deps
    )


def _download(url: str, dest: Path) -> None:
    """Scarica un file.

    Con lo user-agent predefinito di urllib diversi server rispondono 403:
    va dichiarato un client normale, altrimenti il download fallisce anche
    quando l'URL è perfettamente valido.
    """
    request = urllib.request.Request(  # noqa: S310 - URL mostrato e confermato
        url,
        headers={
            "User-Agent": f"animeup/{__version__} (+https://ffmpeg.org)",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
        dest.write_bytes(response.read())


def _capabilities_ok(binary: Path, name: str) -> list[str]:
    """Verifica che la build scaricata sappia fare ciò che serve."""
    if name != "ffmpeg":
        return []
    missing: list[str] = []
    for flag, needed in (("-encoders", REQUIRED_ENCODERS), ("-filters", REQUIRED_FILTERS)):
        out = subprocess.run(
            [str(binary), "-hide_banner", flag],
            capture_output=True, text=True, check=False,
        ).stdout
        words = set(out.split())
        missing += [item for item in needed if item not in words]
    return missing


def _extract(archive: Path, name: str, dest: Path) -> bool:
    """Estrae il binario `name` dall'archivio scaricato."""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmpdir)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                t.extractall(tmpdir, filter="data")
        else:
            return False

        for candidate in tmpdir.rglob(name):
            if candidate.is_file():
                shutil.copy2(candidate, dest)
                dest.chmod(0o755)
                return True
    return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffmpeg_mancanti() -> list[str]:
    return [
        name for name, _tool, status in PATHS.portability_report()
        if name in FFMPEG_SOURCES and status != "ok"
    ]


def _ncnn_mancanti() -> list[str]:
    """Motori da scaricare: binario non vendorizzato o modelli assenti.

    Il binario da solo non basta: senza la sua cartella di modelli parte e
    fallisce al primo fotogramma, cioè a lavorazione già avviata.
    """
    stato = {name: status for name, _tool, status in PATHS.portability_report()}
    mancanti = []
    for name, pacchetto in NCNN_SOURCES.items():
        modelli_ok = all(
            any((PATHS.bin / Path(c).name).glob("*.bin")) for c in pacchetto.cartelle
        )
        if stato.get(name) != "ok" or not modelli_ok:
            mancanti.append(name)
    return mancanti


def _vendor_ffmpeg(console: Console, missing: list[str]) -> None:
    for name in missing:
        url = FFMPEG_SOURCES[name]
        dest = PATHS.bin / name
        console.print(t("cli.setup.scarico", nome=name))
        try:
            with tempfile.NamedTemporaryFile(suffix=".archive", delete=False) as tmp:
                archive = Path(tmp.name)
            _download(url, archive)
            ok = _extract(archive, name, dest)
            archive.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - qualunque errore di rete o formato
            console.print(
                f"[red]{t('cli.setup.fallito', errore=exc)}[/red]\n"
                f"[dim]{t('cli.setup.ripiego_ffmpeg', url=url, nome=name, cartella=PATHS.bin)}[/dim]"
            )
            continue

        if not ok:
            console.print(f"[red]{t('cli.setup.non_trovato', nome=name)}[/red]")
            continue

        if not _is_static(dest):
            console.print(
                f"[yellow]{t('cli.setup.non_statico', nome=name)}[/yellow]"
            )
            continue

        if lacking := _capabilities_ok(dest, name):
            console.print(
                f"[red]{t('cli.setup.incompleto', nome=name, mancanti=', '.join(lacking))}[/red]\n"
                f"[red]{t('cli.setup.rimosso')}[/red]"
            )
            dest.unlink(missing_ok=True)
            continue

        console.print(f"[green]{t('cli.setup.ffmpeg_ok', nome=name)}[/green]")


def _vendor_ncnn(console: Console, missing: list[str]) -> None:
    for name in missing:
        pacchetto = NCNN_SOURCES[name]
        console.print(t("cli.setup.scarico_modelli", nome=name))
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "pacchetto.zip"
            try:
                _download(pacchetto.url, archive)
            except Exception as exc:  # noqa: BLE001 - qualunque errore di rete
                console.print(
                    f"[red]{t('cli.setup.fallito', errore=exc)}[/red]\n"
                    f"[dim]{t('cli.setup.ripiego_ncnn', url=pacchetto.url, cartella=PATHS.bin)}[/dim]"
                )
                continue

            # La release è fissata: un archivio diverso da quello verificato
            # non si installa, che sia corrotto o sostituito a monte.
            if (trovato := _sha256(archive)) != pacchetto.sha256:
                console.print(
                    f"[red]{t('cli.setup.checksum', nome=name, trovato=trovato)}[/red]"
                )
                continue

            estratto = tmpdir / "estratto"
            with zipfile.ZipFile(archive) as z:
                z.extractall(estratto)

            binario = estratto / pacchetto.binario
            cartelle = [estratto / c for c in pacchetto.cartelle]
            if not binario.is_file() or not all(c.is_dir() for c in cartelle):
                console.print(f"[red]{t('cli.setup.contenuto', nome=name)}[/red]")
                continue

            dest = PATHS.bin / name
            shutil.copy2(binario, dest)
            dest.chmod(0o755)
            for cartella in cartelle:
                shutil.copytree(cartella, PATHS.bin / cartella.name, dirs_exist_ok=True)

        console.print(f"[green]{t('cli.setup.ncnn_ok', nome=name)}[/green]")


def vendor_all(console: Console, *, conferma: bool = True) -> None:
    """Scarica in bin/ i binari e i modelli che mancano, previa conferma."""
    if platform.machine() != "arm64":
        console.print(
            f"[yellow]{t('cli.setup.architettura', arch=platform.machine())}[/yellow]"
        )
        return

    ffmpeg = _ffmpeg_mancanti()
    ncnn = _ncnn_mancanti()
    if not ffmpeg and not ncnn:
        console.print(f"[green]{t('cli.setup.gia_tutti')}[/green]")
        return

    console.print(t("cli.setup.verranno") + "\n")
    for name in ffmpeg:
        console.print(t("cli.setup.voce_ffmpeg", nome=name, url=FFMPEG_SOURCES[name]))
    for name in ncnn:
        console.print(t("cli.setup.voce_ncnn", nome=name, url=NCNN_SOURCES[name].url))
    console.print(
        f"\n[dim]{t('cli.setup.peso', mb=40 * len(ffmpeg) + 50 * len(ncnn))}[/dim]"
    )

    # Si accettano le risposte in tutte e due le lingue, qualunque sia
    # quella della domanda.
    if conferma and input("\n" + t("cli.setup.procedo") + " ").strip().lower() not in (
            "s", "si", "sì", "y", "yes"):
        console.print(t("cli.setup.annullato"))
        return

    PATHS.bin.mkdir(parents=True, exist_ok=True)
    _vendor_ffmpeg(console, ffmpeg)
    _vendor_ncnn(console, ncnn)

    console.print("\n" + t("cli.setup.verifica", comando="[bold]./animeup doctor[/bold]"))
