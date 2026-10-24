"""Testi dell'interfaccia in più lingue.

Ogni testo mostrato all'utente ha una chiave (`"sb.titolo"`) e vive nei
cataloghi `locales/<lingua>/*.json`: una cartella per lingua, con un file per
area dell'app (base, confronto, lavorazione, motore, cli) e le stesse chiavi
in ogni lingua. Il codice chiede `t("sb.titolo")` e riceve il testo nella
lingua attiva. Una chiave definita in due file è un errore, non una
sovrascrittura silenziosa.

Perché chiavi e non la frase italiana come chiave (lo stile gettext): la
lingua di fabbrica è l'inglese, e una frase italiana come chiave avrebbe reso
l'italiano la lingua "vera" e l'inglese una traduzione che può mancare.
Con le chiavi le due lingue sono pari, e un test verifica che abbiano le
stesse voci con gli stessi segnaposto.

La lingua si sceglie nella sidebar e si salva in `records/settings.json`
(chiave `lingua`), lo stesso file delle altre preferenze: così la riga di
comando parla la stessa lingua dell'interfaccia senza un'altra impostazione.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path

LINGUE: dict[str, str] = {"en": "English", "it": "Italiano"}
PREDEFINITA = "en"

_CATALOGHI = Path(__file__).resolve().parent / "locales"
_attiva: str | None = None


@cache
def catalogo(lingua: str) -> dict[str, str]:
    voci: dict[str, str] = {}
    for file in sorted((_CATALOGHI / lingua).glob("*.json")):
        for chiave, testo in json.loads(file.read_text(encoding="utf-8")).items():
            if chiave in voci:
                raise ValueError(f"{file.name}: la chiave «{chiave}» è già "
                                 f"definita in un altro file di {lingua}")
            voci[chiave] = testo
    return voci


def preferita() -> str:
    """La lingua salvata nelle impostazioni, o quella di fabbrica.

    `ANIMEUP_LANG` nell'ambiente vince su tutto: serve ai processi lanciati
    da fuori (i test chiamano `./animeup` come sottoprocesso) per parlare
    una lingua decisa, qualunque cosa ci sia scritto nelle impostazioni.
    """
    forzata = os.environ.get("ANIMEUP_LANG")
    if forzata in LINGUE:
        return forzata
    # Import qui e non in testa: `paths` non deve dipendere dai testi, e
    # chi importa solo i cataloghi (i test) non deve risolvere la radice.
    from . import su_disco
    from .paths import PATHS

    try:
        dati = su_disco.leggi(PATHS.impostazioni)
    except (OSError, ValueError):
        return PREDEFINITA
    lingua = dati.get("lingua") if isinstance(dati, dict) else None
    return lingua if lingua in LINGUE else PREDEFINITA


def imposta(lingua: str) -> None:
    global _attiva
    _attiva = lingua if lingua in LINGUE else PREDEFINITA


def attiva() -> str:
    if _attiva is None:
        imposta(preferita())
    return _attiva  # type: ignore[return-value]


def t(chiave: str, **valori: object) -> str:
    """Il testo della chiave nella lingua attiva, con i segnaposto riempiti.

    Una chiave assente non fa cadere la pagina: si ripiega sull'inglese, e in
    ultima istanza si mostra la chiave stessa, che a schermo si nota subito
    (ed è ciò che il test dei cataloghi impedisce di pubblicare).
    """
    testo = catalogo(attiva()).get(chiave)
    if testo is None:
        testo = catalogo(PREDEFINITA).get(chiave, chiave)
    return testo.format(**valori) if valori else testo


def tn(chiave: str, n: int, **valori: object) -> str:
    """Come `t`, con il singolare e il plurale: `<chiave>.uno` / `<chiave>.altri`.

    Due forme bastano per inglese e italiano; `n` è sempre disponibile come
    segnaposto.
    """
    return t(f"{chiave}.{'uno' if n == 1 else 'altri'}", n=n, **valori)
