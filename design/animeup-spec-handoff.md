# AnimeUp · Spec tema e componenti — handoff per implementazione Streamlit

Target: Streamlit 1.61, tema via `config.toml` + CSS custom iniettato con `st.markdown(unsafe_allow_html=True)`.
Riferimento visivo: `animeup-mockup-v2.html`. In caso di dubbio fa fede il mockup.

---

## 1 · Tema — `.streamlit/config.toml`

Chiavi con i nomi esatti di Streamlit. Trascrivere così com'è.

```toml
[theme]
base = "dark"
primaryColor = "#2AC9DE"
backgroundColor = "#101113"
secondaryBackgroundColor = "#17191C"
textColor = "#E8EAED"
borderColor = "#26292E"
linkColor = "#55D8EA"
codeBackgroundColor = "#15171A"
codeTextColor = "#C6CBD2"

yellowColor = "#F2B84B"
yellowBackgroundColor = "#2A2110"
yellowTextColor = "#F5CB78"
greenColor = "#45D483"
greenBackgroundColor = "#10251A"
greenTextColor = "#7FE3AC"
redColor = "#F26D6D"
redBackgroundColor = "#2A1414"
redTextColor = "#F59B9B"
blueColor = "#4DA3FF"
blueBackgroundColor = "#101C2B"
blueTextColor = "#8CC2FF"
orangeColor = "#F2934B"
orangeBackgroundColor = "#2A1D10"
orangeTextColor = "#F5B67E"
violetColor = "#9AA0B4"
violetBackgroundColor = "#1B1D24"
violetTextColor = "#B9BECD"
grayColor = "#8A9099"
grayBackgroundColor = "#1C1F23"
grayTextColor = "#B7BCC3"

baseRadius = "8px"
buttonRadius = "6px"
showWidgetBorder = false
showSidebarBorder = true

font = "Inter"
headingFont = "Inter"
codeFont = "JetBrains Mono"
baseFontSize = 14
baseFontWeight = 400
headingFontSizes = ["24px", "18px", "15px", "13px", "12px", "11px"]
headingFontWeights = [600, 600, 600, 600, 500, 500]
codeFontSize = "12px"

[[theme.fontFaces]]
family = "Inter"
url = "app/static/Inter-Regular.woff2"
weight = 400
[[theme.fontFaces]]
family = "Inter"
url = "app/static/Inter-Medium.woff2"
weight = 500
[[theme.fontFaces]]
family = "Inter"
url = "app/static/Inter-SemiBold.woff2"
weight = 600
[[theme.fontFaces]]
family = "Inter"
url = "app/static/Inter-Bold.woff2"
weight = 700
[[theme.fontFaces]]
family = "JetBrains Mono"
url = "app/static/JetBrainsMono-Regular.woff2"
weight = 400
[[theme.fontFaces]]
family = "JetBrains Mono"
url = "app/static/JetBrainsMono-Medium.woff2"
weight = 500

[theme.sidebar]
backgroundColor = "#1A1D21"
secondaryBackgroundColor = "#22262B"
borderColor = "#33373D"
```

Note sui percorsi `fontFaces`: adattare `url` alla posizione reale dei woff2 nella cartella `static/` del progetto (serviti in locale, nessuna rete).

Semantica delle rampe (non cambiare gli usi):
- **verde** = analizzato / ok
- **giallo** = avviso (mai per stato attivo)
- **rosso** = solo errori veri (mai decorativo)
- **primaryColor (ciano)** = processo attivo, scheda attiva, azione primaria, riga selezionata
- **grigio** = in coda / neutro
- blu, arancio, viola: non usati dalla UI; i valori servono solo a neutralizzarli se un componente li pesca.

---

## 2 · Colori extra-tema (solo CSS custom)

Non esistono come token Streamlit; definirli come CSS custom properties in cima al blocco di stile iniettato:

```css
:root{
  --surfaceHover:  #1C1F23;  /* fondo riga/card in hover */
  --insetBackground:#131518; /* pannello dettagli dentro la riga espansa */
  --borderStrong:  #33373D;  /* bordi in hover, tracce slider, bordo checkbox */
  --textSecondary: #9BA1A9;  /* testo di secondo livello */
  --textTertiary:  #686E76;  /* etichette maiuscole, metadati minimi */
  --primaryBg:     rgba(42,201,222,.10); /* fondo stato attivo (step, clip selezionata) */
  --primaryHover:  #55D8EA;
  --primaryActive: #1FB2C6;
  --idleEdge:      #3A3F46;  /* bordo di stato "in coda" */
  --rowSelectedBg: #191F22;  /* fondo riga selezionata in Lavorazione */
}
```

Testo su fondi ciano pieni (pulsante primario, numero step attivo): `#08262B`, mai bianco.

---

## 3 · Scala spaziature (base 4)

| Passo | Uso |
|---|---|
| 4 px | interno dei chip, gap icona–testo |
| 8 px | gap tra chip, tra label e valore, gap verticale tra le righe della lista |
| 12 px | padding verticale della riga (11 effettivi nel mockup), gap interni al pannello dettagli |
| 16 px | padding orizzontale di righe e card, gap tra colonne della griglia |
| 24 px | tra gruppi della sidebar, tra riepilogo e lista, tra stepper e contenuto |
| 32 px | tra sezioni della pagina |
| 48 px | padding orizzontale del main, sopra un cambio di contesto |

Regola: 4–8 dentro un elemento, 12–16 dentro un componente, 24+ tra componenti. Nessun valore fuori scala (niente 10, 20…).

**Griglia della lista Sorgenti** (intestazione e righe condividono la stessa): `minmax(0,1fr) 92px 64px 300px 28px`, gap 16.
**Griglia Lavorazione**: `15px minmax(0,1fr) 92px 64px 250px 150px`, gap 16.
Vincolo critico di allineamento: l'intestazione colonne deve replicare il box-model delle righe — bordo sinistro 3px trasparente + bordo 1px trasparente + padding orizzontale 16/17 — altrimenti le colonne slittano di 4px.

---

## 4 · Scala tipografica

| Misura | Font / peso | Uso |
|---|---|---|
| 24 / 600 / −0.02em | Inter | titolo di pagina (uno per schermata) |
| 18 / 600 / −0.01em | Inter | titolo di sezione |
| 14 / 500 | Inter | nome file, label controlli, testo dello stepper |
| 13 / 400 | Inter | testo corrente, descrizioni |
| 13 / 400 tabular | JB Mono | risoluzione, durata (celle numeriche) |
| 12.5 / 400 tabular | JB Mono | valori del pannello dettagli, stat Confronto (19px lì) |
| 11.5 / 400 | JB Mono | codec·peso sotto il nome, sintesi analisi, stime |
| 10.5 / 600 / +0.1em / MAIUSC | Inter | etichette campo, intestazioni colonna, titoli gruppo |

Regole ferree:
- Ogni valore tecnico (numeri, codec, timecode, risoluzioni) → JetBrains Mono con `font-variant-numeric: tabular-nums`.
- Colonne numeriche → allineate a destra.
- Nome file → `-webkit-line-clamp: 2`, mai su più di due righe.

---

## 5 · Stati dei componenti

### Riga sorgente
| Stato | Valori |
|---|---|
| riposo | fondo `secondaryBackgroundColor`, bordo 1px `borderColor`, bordo sinistro 3px nel colore di stato |
| hover | fondo `--surfaceHover`, bordo `--borderStrong`; nient'altro cambia |
| espansa | bordo perimetrale `--borderStrong`, chevron ruotato 180°, pannello su `--insetBackground` |
| bordo di stato | in coda `--idleEdge` · in corso `primaryColor` · analizzato `greenColor` · avviso `yellowColor` |
| in coda | contenuto della testata a opacità 0.72 |

### Cella analisi (dentro la riga)
- analizzato: sintesi mono 11.5 `--textSecondary`; se c'è avviso, chip ambra che **va a capo** se non entra (flex-wrap, mai troncare)
- in corso: puntino ciano pulsante (1.2s, solo opacity) + "analisi in corso · N%" in `--primaryHover` + barra 3px sotto
- in coda: puntino grigio `#4A5058` + "in coda"

### Chip di stato
Fondo al ~10% del colore di rampa, testo nella variante `*TextColor`, bordo al ~25%, raggio pieno (999px), mono 11. Non interattivi: nessun hover. Il chip avviso ha un puntino pieno 5px prima del testo.

### Pulsante primario (uno per schermata)
| Stato | Fondo | Testo |
|---|---|---|
| riposo | `primaryColor` | `#08262B`, peso 600 |
| hover | `--primaryHover` | idem |
| attivo | `--primaryActive` | idem |

### Pulsante secondario
riposo: trasparente, bordo `--borderStrong`, testo `codeTextColor` → hover: fondo `grayBackgroundColor`, testo pieno.

### Pulsante icona (28×28) e ghost
riposo: icona/testo terziario, nessun fondo (ghost: bordo `borderColor`) → hover: fondo `grayBackgroundColor`, colore pieno.

### Stepper (navigazione primaria)
| Stato | Valori |
|---|---|
| riposo | segmento su `secondaryBackgroundColor`, bordo `borderColor`, testo `--textSecondary` 14px, numero in cerchio 22px bordato |
| hover | testo pieno, bordo `--borderStrong` |
| attivo | fondo `--primaryBg`, bordo `rgba(42,201,222,.45)`, testo pieno peso 600, cerchio pieno ciano con cifra `#08262B` |

### Card spezzone (Confronto)
riposo: card `secondaryBackgroundColor` bordo `borderColor` → hover: bordo `--borderStrong` → selezionata: bordo `rgba(42,201,222,.55)` + fondo `--primaryBg` + checkbox piena.

### Riga Lavorazione
non selezionata: bordo sinistro `--borderStrong`, nome file e selettore modello attenuati (testo secondario / opacità .55) → selezionata: bordo sinistro `primaryColor`, fondo `--rowSelectedBg`, contenuto pieno.

### Pannello dettagli (riga espansa)
Fondo `--insetBackground`, bordo superiore `borderColor`, entrata 180ms (opacity + translateY −3px). Titoli gruppo: 10.5 maiuscolo con hairline `::after`. Griglia valori 4 colonne, gap 12×28. I valori problematici (SAR, colore non taggato) in `yellowTextColor`. Banner avviso: fondo `yellowBackgroundColor`, bordo sinistro 3px `yellowColor`, testo 12px `yellowTextColor`.

### Slider e toggle (widget nativi)
Nessun CSS strutturale: si colorano da soli con `primaryColor`. Valore corrente accanto alla label in mono 12 (`codeTextColor`). Toggle off: traccia `--borderStrong`, label in `--textSecondary`.

---

## 6 · Note d'implementazione Streamlit

1. **Righe con stato**: ogni riga in un `st.container(key=f"row_{i}_{stato}")` → Streamlit genera la classe `st-key-row_{i}_{stato}`. Il CSS definisce una regola per stato (`[class*="_done"]`, `[class*="_warn"]`, ecc.) che imposta il `border-left`. La key va ricomposta a ogni rerun col nome dello stato corrente.
2. **Selezione con evidenza card/riga**: `div[class*="st-key-clip_"]:has(input:checked){...}` — funziona perché la checkbox sta dentro il container keyed. Stessa tecnica per le righe di Lavorazione.
3. **Nascondere il chrome**: `[data-testid="stToolbar"]{display:none}` (via anche header decoration se presente).
4. **Animazioni**: solo di ENTRATA (pannello 180ms, pulse del puntino). Nessuna animazione di uscita: il framework rimuove il nodo prima del CSS — comportamento accettato, non aggirare. Avvolgere le animazioni in `@media (prefers-reduced-motion: reduce)` per disattivarle.
5. **HTML libero** (chip, celle analisi, riepilogo, marchio, stat): solo dentro `st.markdown(..., unsafe_allow_html=True)`. Mai avvolgere widget nativi in markup proprio.
6. **Stepper**: `st.tabs` o radio orizzontale ristilizzato con i valori della sezione 5. Il numero nel cerchio può essere HTML dentro la label solo se si usa markdown custom al posto delle tab native — in alternativa tab native ristilizzate senza cerchio, accettabile.
7. **Barra di avvio (Lavorazione)**: container keyed con `position: sticky; bottom: 0; backdrop-filter: blur(8px)` su fondo `rgba(16,17,19,.92)`.
8. **Ordine gerarchico di ogni riga** (criterio per qualunque dubbio di stile): 1° bordo di stato + nome file → 2° risoluzione/durata → 3° chip avviso se presente → solo se cercato: codec·peso e sintesi analisi. Se un'aggiunta rompe quest'ordine di lettura, è sbagliata.
