#!/usr/bin/env bash
# Doppio click da Finder: apre AnimeUp nel browser.
#
# Se il server e' gia' acceso (finestra del Terminale gia' aperta, o avviato
# a mano) non ne parte un secondo: si riapre solo il browser. Chiudere la
# finestra del BROWSER non ferma niente; chiudere la finestra del TERMINALE
# spegne l'interfaccia ma NON le lavorazioni in corso, che sono processi
# separati e continuano (e si ritrovano riaprendo AnimeUp).
set -euo pipefail
cd "$(dirname "$0")"

# La lingua salvata dall'interfaccia, letta senza Python (al primo avvio
# l'ambiente non c'e' ancora); di fabbrica si parla inglese.
IMPOSTAZIONI="${ANIMEUP_ROOT:-.}/registri/impostazioni.json"
LINGUA=""
if [[ -r "$IMPOSTAZIONI" ]]; then
  LINGUA="$(sed -n 's/.*"lingua"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$IMPOSTAZIONI" | head -n 1 || true)"
fi

PORTA=8899
if lsof -ti :"$PORTA" >/dev/null 2>&1; then
  if [[ "$LINGUA" == "it" ]]; then
    echo "AnimeUp e' gia' in esecuzione: apro il browser."
  else
    echo "AnimeUp is already running: opening the browser."
  fi
  open "http://localhost:$PORTA"
  exit 0
fi

# Primo avvio (o bin/ svuotata): prima binari e modelli, che il setup scarica
# chiedendo conferma qui, nella finestra del Terminale.
for b in ffmpeg ffprobe realesrgan-ncnn-vulkan realcugan-ncnn-vulkan; do
  if [[ ! -x "bin/$b" ]]; then
    ./animeup setup
    break
  fi
done

exec ./animeup ui --porta "$PORTA"
