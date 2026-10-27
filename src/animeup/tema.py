"""I colori dell'interfaccia: due temi, un posto solo.

Ogni colore e' un token con due valori, scuro e chiaro, presi dalla tavola
dei token del design (artboard "Token sheet"). Il CSS dell'interfaccia usa
SOLO queste variabili: un colore scritto a mano nel foglio di stile e' un
difetto, e un test lo cerca.

Le tinte trasparenti si scrivono `rgb(var(--primaryRgb) / .1)`: per questo
i colori che servono velati hanno anche la terna RGB.

La scelta dell'utente (Sistema / Scuro / Chiaro) decide quali blocchi
scrivere: Scuro e Chiaro ne scrivono uno, Sistema li scrive tutti e due e
lascia scegliere a `prefers-color-scheme`, come fa Streamlit col suo tema.
"""

from __future__ import annotations

SISTEMA, SCURO, CHIARO = "system", "dark", "light"
SCELTE = (SISTEMA, SCURO, CHIARO)

# nome: (scuro, chiaro)
TOKEN: dict[str, tuple[str, str]] = {
    # superfici
    "bg":              ("#101113", "#F6F7F9"),
    "surface":         ("#17191C", "#FFFFFF"),
    "insetBackground": ("#131518", "#F1F3F5"),
    "surfaceHover":    ("#1C1F23", "#EEF0F2"),
    # Scheda non aperta sotto il puntatore: in chiaro surfaceHover si
    # confondeva col fondo della pagina (#F6F7F9), quasi invisibile.
    "tabHover":        ("#1C1F23", "#E6E9ED"),
    "rowBg":           ("#191F22", "#FFFFFF"),
    "rowBgHover":      ("#1F262A", "#F7F9FA"),
    "sidebar":         ("#1A1D21", "#ECEEF1"),
    "sidebar2":        ("#22262B", "#E3E6EA"),
    "sidebarCard":     ("#1E2125", "#F5F6F8"),
    "clipBg":          ("#000000", "#000000"),
    # bordi
    "borderColor":     ("#26292E", "#E1E4E8"),
    "borderStrong":    ("#33373D", "#CDD1D6"),
    "borderFaint":     ("#2B2F34", "#DADDE2"),
    "borderHover":     ("#40454C", "#B9BEC4"),
    "borderHover2":    ("#565C66", "#A9AFB6"),
    "rowLine":         ("#1F2226", "#ECEEF1"),
    "idleEdge":        ("#3A3F46", "#8A9099"),
    "locked":          ("#2E3238", "#D5D9DE"),
    # testi
    "textPrimary":     ("#E8EAED", "#16181B"),
    "textCode":        ("#C6CBD2", "#3A3F46"),
    "textSecondary":   ("#9BA1A9", "#5C626A"),
    "textTertiary":    ("#80868E", "#656B73"),
    "grayText":        ("#B7BCC3", "#4A5058"),
    "dot":             ("#5A6068", "#80868E"),
    # accento: una tinta per tema, cambia solo l'intensita'.
    # `primary` per cio' che non si clicca (barre, bordi delle righe,
    # selezione, cerchio della scheda, badge); `primaryStrong` per i comandi
    # (pulsanti pieni, interruttori, caselle, cursori); `primaryText` per il
    # testo e i pulsanti a contorno.
    "primary":         ("#2AC9DE", "#10AFCB"),
    "primaryStrong":   ("#2AC9DE", "#0E99B1"),
    "primaryText":     ("#2AC9DE", "#0B7284"),
    "primaryHover":    ("#57D4E5", "#0F9FB9"),
    # premuto: un passo piu' scuro dello stesso ciano (mancava, e lo sfondo
    # del pulsante spariva durante il clic)
    "primaryActive":   ("#1FB3C6", "#0C8599"),
    "onPrimary":       ("#07282C", "#FFFFFF"),
    # il fondo dei pulsanti secondari: in scuro un filo piu' chiaro della
    # superficie, o non si leggevano come pulsanti (segnalato dall'utente);
    # in chiaro resta il bianco di prima
    "buttonFill":      ("#1C1F23", "#FFFFFF"),   # = surfaceHover, come nelle tavole
    "knobOn":          ("#07282C", "#FFFFFF"),
    # interruttore spento: tono su tono col fondo (in chiaro: chiaro, non grigio scuro)
    "toggleOff":       ("#3A3F46", "#D5D9DF"),
    "knobOff":         ("#9BA1A9", "#FFFFFF"),
    # rampe di stato: colore (bordi, pallini), fondo, testo
    "green":           ("#45D483", "#12A150"),
    "greenBg":         ("#10251A", "#E6F5EC"),
    "greenText":       ("#7FE3AC", "#146C3E"),
    # verde pieno con testo bianco: i passi gia' fatti del Confronto
    "greenSolid":      ("#17784A", "#12804A"),
    "onGreen":         ("#FFFFFF", "#FFFFFF"),
    "yellow":          ("#F2B84B", "#F5B400"),
    "yellowBg":        ("#2A2110", "#FFF0C4"),
    "yellowText":      ("#F5CB78", "#7F5300"),
    # la CTA gialla piena (l'avviso di aggiornamento): testo scuro su tutti e due
    "yellowHover":     ("#F5C66A", "#E8A800"),
    "yellowActive":    ("#DDA43A", "#D29A00"),
    "onYellow":        ("#2A1D05", "#1F1500"),
    # i puntini dei cursori sulla parte gia' colorata di ciano
    "dotOnFill":       ("#F2FDFF", "#FFFFFF"),
    "red":             ("#F26D6D", "#D9402E"),
    "redBg":           ("#2A1414", "#FDECEC"),
    "redText":         ("#F59B9B", "#B42323"),
    # CTA rosse piene: in scuro un rosso un po' piu' cupo con testo bianco
    # (il nero sul rosso chiaro si leggeva poco, detto dall'utente). 4,8:1.
    "redFill":         ("#CC4141", "#C62F25"),
    "redHover":        ("#D94848", "#B02A21"),
    "onRed":           ("#FFFFFF", "#FFFFFF"),
    "blue":            ("#4DA3FF", "#1F6FD1"),
    "blueBg":          ("#101C2B", "#E8F1FC"),
    "blueText":        ("#8CC2FF", "#1A5BB0"),
    "gray":            ("#8A9099", "#6B7179"),
    "grayBg":          ("#1C1F23", "#EEF0F2"),
}

# Le terne per le velature: `rgb(var(--xRgb) / alfa)`.
TERNE: dict[str, tuple[str, str]] = {
    "primaryRgb":  ("42 201 222", "16 175 203"),
    "greenRgb":    ("69 212 131", "18 161 80"),
    "yellowRgb":   ("242 184 75", "245 180 0"),
    "redRgb":      ("242 109 109", "217 64 46"),
    "blueRgb":     ("77 163 255", "31 111 209"),
    "grayRgb":     ("138 144 153", "107 113 121"),
    "textGrayRgb": ("183 188 195", "74 80 88"),
    "bgRgb":       ("16 17 19", "246 247 249"),
    "sidebarRgb":  ("26 29 33", "236 238 241"),       # = sidebar, per le sfumature
    # Ombre: nere sul tema scuro, blu notte appena accennato sul chiaro.
    "shadowRgb":   ("0 0 0", "16 24 40"),
    # Le velature "piu' chiaro del fondo" del tema scuro, che sul chiaro
    # devono diventare "piu' scuro del fondo".
    "overlayRgb":  ("255 255 255", "0 0 0"),
    # Il fondo della riga aperta in Sorgenti: sullo scuro la velatura di
    # sempre, sul chiaro bianca come le righe chiuse (utente).
    "openRowBg":   ("rgb(255 255 255 / .03)", "#FFFFFF"),
    # ...e il pannello dei dettagli che si apre sotto (Sorgenti e Lavorazione).
    "openPanelBg": ("var(--insetBackground)", "#FFFFFF"),
    # La tinta ciano tenue degli stati attivi (etichetta «in corso»):
    # usata dal CSS da tempo ma mai definita, quindi restava trasparente.
    "primaryBg":   ("rgb(var(--primaryRgb) / .12)", "rgb(var(--primaryRgb) / .12)"),
    # I riquadri tratteggiati delle versioni che arrivano (Confronto in
    # corso): sul chiaro i bordi di sempre si vedevano appena (utente).
    "dashBorder":  ("var(--borderColor)", "#AEB4BB"),
    "dashActive":  ("rgb(var(--primaryRgb) / .35)", "rgb(var(--primaryRgb) / .7)"),
    # Pulsanti a contorno d'accento (Riprendi, Pausa, Usa per questo file):
    # sullo scuro il ciano brillante basta; sul chiaro il contorno al 55% si
    # vedeva appena (utente), quindi bordo pieno e una tinta di fondo.
    "accentLine":  ("rgb(var(--primaryRgb) / .55)", "var(--primaryStrong)"),
    "accentFill":  ("transparent", "rgb(var(--primaryRgb) / .07)"),
}


def _blocco(indice: int) -> str:
    righe = [f"--{k}: {v[indice]};" for k, v in TOKEN.items()]
    righe += [f"--{k}: {v[indice]};" for k, v in TERNE.items()]
    righe.append(f"color-scheme: {'dark' if indice == 0 else 'light'};")
    return " ".join(righe)


def css(scelta: str) -> str:
    """Le variabili per la scelta dell'utente, pronte per un `<style>`."""
    if scelta == CHIARO:
        return f":root {{ {_blocco(1)} }}"
    if scelta == SCURO:
        return f":root {{ {_blocco(0)} }}"
    return (f":root {{ {_blocco(0)} }}\n"
            f"@media (prefers-color-scheme: light) {{ :root {{ {_blocco(1)} }} }}")


def streamlit(scelta: str) -> str:
    """Il nome che Streamlit da' allo stesso tema nel browser."""
    return {SCURO: "Dark", CHIARO: "Light"}.get(scelta, "System")
