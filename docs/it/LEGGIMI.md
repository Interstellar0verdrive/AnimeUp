# AnimeUp — upscaler anime locale (macOS / Apple Silicon)

Upscala episodi anime a 1080p+ con Real-ESRGAN e Real-CUGAN (ncnn-vulkan),
in locale, senza rete. Tutto vive in questa cartella: copiala su un altro
Mac e funziona identica.

---

## La mappa

```
AnimeUp/
├── Avvia AnimeUp.command  ← doppio click da Finder: apre l'interfaccia
├── animeup          ← lo stesso, da terminale: ./animeup ui
├── LEGGIMI.md       ← questo file
├── TARATURE.md      ← perché i parametri sono questi (misure e confronti)
│
│   —— le TUE cartelle (MAIUSCOLE: qui si mette e si prende) ——
├── INPUT/           ← metti qui gli episodi da elaborare (.mkv, .mp4…)
├── OUTPUT/          ← qui compaiono i file upscalati
├── JOBS/            ← lavorazioni in corso o interrotte, riprendibili.
│                      Una sottocartella per episodio; si svuota da sola
│                      a lavoro finito. Se pesa tanto è perché un lavoro
│                      è a metà: riprendilo o cancella la sua cartella.
├── _WIP/            ← materiale di prova e backup (gestita a mano)
│
│   —— cartelle interne (minuscole: non toccare, si gestiscono da sole) ——
├── anteprime/       ← cache della scheda Confronto (rigenerabile)
├── registri/        ← pagelle, taratura, impostazioni (+ log diagnostici)
├── bin/             ← ffmpeg, ffprobe, modelli e binari ncnn "vendorizzati"
├── src/             ← il motore (Python, pacchetto `animeup`)
├── ui/              ← l'interfaccia Streamlit (+ font in ui/static)
├── tests/           ← test di regressione: ./animeup test
├── design/          ← mockup HTML e spec grafico: è la fonte di verità della UI
└── .streamlit .venv .python .cache  ← ambiente autonomo (nascoste)
```

## Il flusso di lavoro ideale

1. **Copia** gli episodi in `INPUT/`.
2. **Doppio click su `Avvia AnimeUp.command`** (o `./animeup ui` da
   terminale) → si apre su `http://localhost:8899`. La finestra del
   Terminale che compare È il server: va lasciata aperta finché usi
   l'interfaccia. Chiudere il browser non spegne niente; chiudere il
   Terminale spegne l'interfaccia ma NON le lavorazioni in corso.
3. **Sorgenti** — controlla l'analisi di ogni file: risoluzione, framerate,
   avvisi (file troncati, formati strani). Ogni riga si apre a fisarmonica.
4. **Confronto** *(consigliato alla prima serie)* — prova i modelli su
   spezzoni difficili di 10 secondi e scegli guardando, invece di fidarti.
5. **Lavorazione** — spunta i file, conferma il modello proposto, avvia.
   Un lavoro alla volta: la GPU non si divide. Avanzamento, fps e tempo
   restante compaiono nella riga del file. Il tempo restante comprende
   anche i turni di codifica dei blocchi che mancano, non solo l'upscale:
   sono la metà abbondante del lavoro su un episodio, e ignorarli faceva
   promettere molto meno di quanto sarebbe costato.
6. Il risultato arriva in `OUTPUT/` col nome originale più i parametri,
   es. `Episodio [upscale 1080p cugan x3 crf18 dd].mkv`. A coda finita
   compare un **resoconto**: quanti file, quanto è durata, deduplica media,
   avvisi, e — se ce ne sono — quali file non sono stati completati.
7. **Per chiudere**: pulsante **"Chiudi AnimeUp"** in fondo alla sidebar
   (spegne il server; poi chiudi browser e Terminale quando vuoi). In
   alternativa chiudi la finestra del Terminale aperta al punto 2. Le
   lavorazioni in corso NON si fermano chiudendo: continuano da sole e le
   ritrovi alla prossima apertura (per fermarle davvero: Ferma / Ferma
   tutto, prima di chiudere). Se serve la via d'emergenza:
   `lsof -ti :8899 | xargs kill`

**Interruzioni**: chiudere il Mac, un crash, un kill — niente panico. La
lavorazione resta in `JOBS/` e la riga mostra "interrotto", con due
pulsanti:

- **Riprendi** è *blindato*: rilancia coi parametri con cui il file era
  partito (scritti in `parametri.json` dentro la sua cartella di
  lavorazione), qualunque cosa dica la sidebar in quel momento. Riprendere
  non può mai buttare il lavoro fatto — nemmeno la griglia dei blocchi si
  ricalcola: si adotta quella salvata, così i blocchi già codificati restano
  buoni anche se cambia lo spazio libero o lo slider dei GB.
- **Scarta** butta la lavorazione a metà di QUEL file (fotogrammi estratti,
  blocchi, stato) e libera i GB: la riga torna come nuova, per rifare con
  parametri o modello diversi. Conferma a due passi, in rosso. Non tocca mai
  né il sorgente né l'OUTPUT.

Entrambi restano spenti finché la GPU sta lavorando su un altro file: non si
riprende né si scarta a motore acceso.

**Dove conviene fermare**: il lavoro va al sicuro un blocco alla volta, non un
fotogramma alla volta. Riprendendo, il blocco in corso riparte dal suo primo
fotogramma — quelli già ingranditi di quel blocco si rifanno. Per questo la
riga dice anche "742/1778 del blocco 3 di 10": è il conto alla rovescia verso
il prossimo punto in cui un Ferma non costa niente. La percentuale della riga
resta quella dei fotogrammi passati, quindi dice dove si è arrivati, non
quanto è già al sicuro.

**Già fatto, ma il file non c'è più**: se in `esiti.jsonl` risulta una pagella
con esattamente quei parametri ma l'uscita non è più in `OUTPUT/` (spostata,
archiviata), la riga lo dice invece di rifare in silenzio, e chiede conferma
prima di rimettere il file in coda. Un'uscita difettosa non conta come fatta:
resta segnata "da rifare".

**Impostazioni persistenti**: i valori della sidebar si salvano da soli in
`registri/impostazioni.json` e al riavvio tornano quelli dell'ultima
sessione, non i default. Se c'è un file sospeso lanciato con parametri
diversi dagli attuali, la sidebar lo dice e offre un pulsante per
riallinearsi ai parametri del sospeso.

---

## Dettaglio delle cartelle

### INPUT/
Gli episodi sorgente. Lo strumento **non li modifica mai**: legge e basta.
Sottocartelle ammesse. I formati passano tutti da ffprobe: se un file è
strano lo dice la scheda Sorgenti, non un crash a metà lavoro.

### OUTPUT/
I file finiti: video HEVC 10-bit (x265, di default CRF 18 preset slower) con
**tutte le tracce originali rimontate** — audio, sottotitoli, capitoli,
allegati (font dei fansub compresi). Un file che finisce con avvisi gravi
viene rinominato `.PARZIALE.mkv` invece di spacciarsi per buono: rilanciando
si rifà.

### JOBS/
Una cartella per lavorazione, nominata `<episodio> <data> <impronta>`.
Dentro: `frames/` (fotogrammi estratti), `chunk*-in/-up` (blocco in
elaborazione), `segments/` (pezzi già codificati), `state.json` (lo stato
per la ripresa), `in-corso.lock` (il PID del processo attivo),
`upscaler.pgid` (per abbattere upscaler orfani dopo un crash).

- A lavoro finito **senza** avvisi la cartella si cancella da sola.
- Con avvisi resta per ispezione: la riga in UI dice "fatta · conclusa con
  avvisi". Si può cancellare a mano senza conseguenze (l'output è in OUTPUT/).
- Interrotta: si riprende dalla UI (pulsante Riprendi) o rilanciando lo
  stesso comando; la firma in `state.json` garantisce che parametri diversi
  non riciclino fotogrammi sbagliati.

### anteprime/ (interna, rigenerabile)
Cache della scheda Confronto: miniature, clip animate degli spezzoni,
schedario degli "spezzoni difficili" (`.spezzoni/*.json`) e i render dei
confronti, organizzati per episodio e impostazioni. **Si può svuotare in
qualunque momento**: al massimo la prossima scansione spezzoni si rifà
(qualche minuto per episodio). I render dentro sono MKV normali: copiarli
fuori per mostrarli a qualcuno è lecito.

### registri/ (interna)
Attenzione: qui convivono due cose diverse, e il nome della cartella
inganna. I **`.log`** (uno per lavorazione, più `lavorazione.log` e
`ui-server.log`) sono solo diagnostica e si possono cancellare quando si
vuole. Gli altri file invece sono **dati**, e cancellarli riporta
AnimeUp allo stato di macchina nuova:

- `esiti.jsonl` — la pagella di ogni file completato (durata reale,
  deduplica misurata, avvisi, modello usato, nome dell'uscita prodotta). È
  ciò che fa dire "fatto" e "Finito in ..." nell'elenco, e rende le stime
  aderenti a questa macchina.
- `taratura.json` — la velocità misurata di questo Mac: megapixel al secondo
  per ogni modello e scala, estrazione, codifica, scansione della deduplica
  e numero di thread di salvataggio. Senza, le stime tornano ai valori di
  fabbrica, misurati altrove — e sbagliano parecchio: su questo stesso Mac
  l'estrazione di fabbrica dice 60 f/s contro 84 misurati.
- `impostazioni.json` — le preferenze della sidebar.
- `lanci.jsonl` — il diario dei lanci: compare alla prima coda avviata. Serve
  al resoconto di fine lavorazione (quanti file, quanto è durata, deduplica
  media, avvisi, quali file non sono stati completati).

Non si rompe niente a cancellarli: si perdono la storia, la taratura (dieci
minuti per rifarla con il link in sidebar) e le preferenze. Il promemoria
sta anche in `registri/NON_CANCELLARE.txt`.

### bin/
Binari vendorizzati: `ffmpeg`, `ffprobe`, `realesrgan-ncnn-vulkan`,
`realcugan-ncnn-vulkan`, i modelli, e `uv` (gestore Python). È ciò che rende
la cartella autonoma. Se la sidebar mostra "N dipendenze dal sistema",
qualcosa manca: `./animeup setup` la ricostruisce.

### src/, ui/, tests/, design/
Il programma. `src/animeup/` è il motore (analisi → piano → estrazione →
deduplica → upscale → codifica → rimontaggio); `ui/app.py` l'interfaccia;
`tests/run.py` i test di regressione (ogni caso corrisponde a un bug reale
già avvenuto); `design/` contiene il mockup HTML che fa fede per la grafica.
**Non spostare queste cartelle**: l'ambiente Python usa percorsi assoluti.

---

## Comandi utili

```
./animeup ui              # interfaccia web (porta 8899; --porta N per cambiarla)
./animeup analyze FILE    # analisi di un sorgente, da terminale
./animeup plan FILE       # cosa farebbe, senza farlo
./animeup run FILE        # lavorazione da terminale (stessa pipeline della UI)
./animeup test            # test di regressione (vanno eseguiti dopo ogni modifica)
./animeup doctor          # controlla che la cartella sia davvero autonoma
./animeup setup           # ripristina i binari vendorizzati
```

## Decisioni tecniche in breve (il perché è in TARATURE.md)

- **Modelli**: sotto ~380p vince Real-ESRGAN animevideov3; sopra ~560p vince
  CUGAN no-denoise; in mezzo è zona dubbia e la UI propone cosa verificare.
- **Un lavoro alla volta**: due upscaler sulla stessa GPU si rallentano a
  vicenda; la UI disattiva Avvia mentre un lavoro corre.
- **Pausa fra i file** (sidebar, default 5 min, 0 = spenta): nelle maratone
  la catena riposa fra un episodio e l'altro per dare respiro a CPU e GPU.
  Durante la pausa l'Avvia resta bloccato e la barra dice quando riparte.
- **Deduplica**: l'animazione "in due/tre" ripete fotogrammi; si elaborano
  una volta sola (misurato: tempi quasi dimezzati) con verifica per blocco.
- **10-bit**: l'uscita è yuv420p10le anche da sorgenti 8-bit (meno banding);
  i binari ncnn leggono 8-bit, il dithering in ingresso mitiga.
- **Fansub Hi444PP**: certi encode hanno keyframe "finti" che corrompono i
  seek veloci (blocchi verdi); l'estrazione valida lo stderr e in caso
  ricomincia da zero. Vale per anteprime E render dei confronti.
- **Robustezza ai crash**: lucchetto con PID (+controllo zombie), pgid
  dell'upscaler su disco per abbattere orfani alla ripresa, stallo GPU
  rilevato dopo 15 minuti senza progresso.
- **Thread di salvataggio**: i binari ncnn scrivono i PNG con un pool di
  thread separato, e oltre un certo numero il disco diventa il collo di
  bottiglia invece della GPU. Il numero giusto cambia da macchina a macchina,
  quindi la taratura lo prova sul posto (2, 4, 6 e 8) e tiene il migliore.
  Su una macchina mai tarata si usa un valore prudente, non il massimo.
- **Stime tarate per macchina, storia per contenuto**: `taratura.json` misura
  l'hardware ed è indicizzato per chip — cambiando Mac va rifatta. `esiti.jsonl`
  riguarda invece i contenuti (quanti fotogrammi ripetuti aspettarsi, quanto
  le stime hanno sbagliato finora) e resta valido ovunque.

## Spostare la cartella / secondo Mac

Copia l'intera cartella (disco esterno incluso): al primo avvio `./animeup`
ripara da solo l'ambiente Python se serve. Non serve Homebrew né un Python
di sistema. L'unica variabile riconosciuta è `ANIMEUP_ROOT`, se si vuole
tenere INPUT/OUTPUT altrove.

## Se qualcosa va storto

| Sintomo | Cosa fare |
|---|---|
| voglio FERMARE una lavorazione in corso | **Ferma** sulla riga del file interrompe solo quello (il resto del lancio prosegue); **Ferma tutto** nella barra in basso interrompe il file in corso e annulla i successivi. In entrambi i casi il file interrotto resta riprendibile. Senza interfaccia: `kill $(cat "JOBS/<cartella>/in-corso.lock")` |
| "un'altra lavorazione è già in corso" ma non c'è | il lucchetto è di un processo morto: si sblocca da solo al lancio successivo; se insiste, cancella `in-corso.lock` in quella cartella di JOBS |
| file `.PARZIALE.mkv` in OUTPUT | la lavorazione ha avvisi gravi: rilancia il file, si rifà da dove può |
| anteprime con blocchi verdi/rosa | cache vecchia di un file corrotto ai seek: cancella la sottocartella in `anteprime/` e rigenera |
| la UI non parte: porta occupata | `lsof -ti :8899 \| xargs kill`, oppure `./animeup ui --porta 8900` |
| dubbi sui parametri | TARATURE.md spiega ogni scelta con le misure |
