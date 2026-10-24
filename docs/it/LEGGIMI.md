# AnimeUp — upscaler anime locale (macOS / Apple Silicon)

Upscala episodi anime a 1080p+ con Real-ESRGAN e Real-CUGAN (ncnn-vulkan),
in locale, senza rete. Tutto vive in questa cartella: copiala su un altro
Mac e funziona identica.

---

## La mappa

```
AnimeUp/
├── Start AnimeUp.command  ← doppio click da Finder: apre l'interfaccia
├── animeup          ← lo stesso, da terminale: ./animeup ui
├── LEGGIMI.md       ← questo file
├── TARATURE.md      ← perché i parametri sono questi (misure e confronti)
│
│   —— le TUE cartelle (MAIUSCOLE: qui si mette e si prende) ——
├── INPUT/           ← metti qui gli episodi da elaborare (.mkv, .mp4…)
├── OUTPUT/          ← qui compaiono i file upscalati, e in più:
│   ├── logs/        ←   un log per ogni file lavorato
│   └── JOBS/        ←   lavorazioni in corso o interrotte, riprendibili.
│                        Una sottocartella per episodio; si svuota da sola
│                        a lavoro finito. Se pesa tanto è perché un lavoro
│                        è a metà: riprendilo o cancella la sua cartella.
├── _WIP/            ← materiale di prova e backup (gestita a mano)
│
│   —— cartelle interne (minuscole: non toccare, si gestiscono da sole) ——
├── records/         ← storico, lanci, impostazioni, taratura
├── cache/           ← analisi dei sorgenti e clip del Confronto (rigenerabile)
├── bin/             ← ffmpeg, ffprobe, modelli e binari ncnn "vendorizzati"
├── samples/         ← la clip di 20 secondi usata dalla taratura
├── src/             ← il motore (Python, pacchetto `animeup`)
├── ui/              ← l'interfaccia Streamlit (+ font in ui/static)
├── tests/           ← test di regressione: ./animeup test
├── design/          ← mockup HTML e spec grafico: è la fonte di verità della UI
└── .streamlit .venv .python .cache  ← ambiente autonomo (nascoste)
```

## Le cartelle

AnimeUp lavora con due cartelle scelte da te e tiene i propri dati a parte.

| Dove | A cosa serve |
|---|---|
| **Cartella dei video da elaborare** (`INPUT/`) | Gli episodi sorgente. Mai modificati. |
| **Cartella dei video finiti** (`OUTPUT/`) | I file finiti, più `logs/` (un log per file) e `JOBS/` (lavorazioni in corso o interrotte, una sottocartella per episodio, che si cancella da sola quando il lavoro finisce pulito). Le lavorazioni possono occupare decine di GB: conviene che questa cartella stia su un disco con spazio. |
| I dati di AnimeUp | `records/` (storico delle lavorazioni, lanci, impostazioni, taratura), `cache/` (analisi dei sorgenti, clip del Confronto: si può cancellare), `bin/` (FFmpeg, gli upscaler ncnn, i modelli e uv). |

Nell'app le due cartelle sono di default `~/Movies/AnimeUp/INPUT` e
`~/Movies/AnimeUp/OUTPUT`, e i dati di AnimeUp stanno in
`~/Library/Application Support/AnimeUp`. Nella cartella portatile invece sta
tutto dentro la cartella di AnimeUp, come nella mappa qui sopra. I nomi dei
file e il loro contenuto sono in inglese, qualunque sia la lingua
dell'interfaccia. Aggiornando dalla 1.5, la disposizione vecchia
(`registri/`, `anteprime/`, `JOBS/` in cima alla cartella) viene spostata da
sola al primo avvio; le lavorazioni interrotte restano riprendibili.

## Il flusso di lavoro ideale

1. **Copia** gli episodi in `INPUT/`.
2. **Doppio click su `Start AnimeUp.command`** (o `./animeup ui` da
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
lavorazione resta in `OUTPUT/JOBS/` e la riga mostra "interrotto", con due
pulsanti:

- **Riprendi** è *blindato*: rilancia coi parametri con cui il file era
  partito (scritti in `parameters.json` dentro la sua cartella di
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

**Già fatto, ma il file non c'è più**: se in `records/history.jsonl` risulta una pagella
con esattamente quei parametri ma l'uscita non è più in `OUTPUT/` (spostata,
archiviata), la riga lo dice invece di rifare in silenzio, e chiede conferma
prima di rimettere il file in coda. Un'uscita difettosa non conta come fatta:
resta segnata "da rifare".

**Impostazioni persistenti**: i valori della sidebar si salvano da soli in
`records/settings.json` e al riavvio tornano quelli dell'ultima
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
viene rinominato `.DEFECTIVE.mkv` invece di spacciarsi per buono: rilanciando
si rifà.

### OUTPUT/logs/
Un `.log` per ogni file lavorato, accanto ai video finiti: chi cerca il
racconto di una lavorazione lo trova dove ha trovato il video. Solo
diagnostica: si possono cancellare quando si vuole.

### OUTPUT/JOBS/
Sta dentro OUTPUT perché lo spazio che chiede è quello del disco dei video
finiti. Una cartella per lavorazione, nominata `<episodio> <data> <impronta>`.
Dentro: `frames/` (fotogrammi estratti), `chunk*-in/-up` (blocco in
elaborazione), `segments/` (pezzi già codificati), `state.json` (lo stato
per la ripresa), `running.lock` (il PID del processo attivo),
`upscaler.pgid` (per abbattere upscaler orfani dopo un crash).

- A lavoro finito **senza** avvisi la cartella si cancella da sola.
- Con avvisi resta per ispezione: la riga in UI dice "fatta · conclusa con
  avvisi". Si può cancellare a mano senza conseguenze (l'output è in OUTPUT/).
- Interrotta: si riprende dalla UI (pulsante Riprendi) o rilanciando lo
  stesso comando; la firma in `state.json` garantisce che parametri diversi
  non riciclino fotogrammi sbagliati.

### cache/ (interna, rigenerabile)
In `cache/analysis/` il referto di ogni sorgente analizzato; in
`cache/previews/` la cache della scheda Confronto: miniature, clip animate
degli spezzoni, schedario degli "spezzoni difficili" (`clips/*.json`) e i
render dei confronti, organizzati per episodio e impostazioni. **Si può svuotare in
qualunque momento**: al massimo la prossima scansione spezzoni si rifà
(qualche minuto per episodio). I render dentro sono MKV normali: copiarli
fuori per mostrarli a qualcuno è lecito.

### records/ (interna)
Qui stanno i **dati** di AnimeUp, e cancellarli riporta AnimeUp allo stato
di macchina nuova (fa eccezione `queue.log`, l'uscita dell'ultima coda
lanciata dall'interfaccia: solo diagnostica):

- `history.jsonl` — la pagella di ogni file completato (durata reale,
  deduplica misurata, avvisi, modello usato, nome dell'uscita prodotta). È
  ciò che fa dire "fatto" e "Finito in ..." nell'elenco, e rende le stime
  aderenti a questa macchina.
- `calibration.json` — la velocità misurata di questo Mac: megapixel al secondo
  per ogni modello e scala, estrazione, codifica, scansione della deduplica
  e numero di thread di salvataggio. Senza, le stime tornano ai valori di
  fabbrica, misurati altrove — e sbagliano parecchio: su questo stesso Mac
  l'estrazione di fabbrica dice 60 f/s contro 84 misurati.
- `settings.json` — le preferenze della sidebar.
- `launches.jsonl` — il diario dei lanci: compare alla prima coda avviata. Serve
  al resoconto di fine lavorazione (quanti file, quanto è durata, deduplica
  media, avvisi, quali file non sono stati completati).

Non si rompe niente a cancellarli: si perdono la storia, la taratura (dieci
minuti per rifarla con il link in sidebar) e le preferenze.

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
- **Stime tarate per macchina, storia per contenuto**: `calibration.json` misura
  l'hardware ed è indicizzato per chip — cambiando Mac va rifatta. `history.jsonl`
  riguarda invece i contenuti (quanti fotogrammi ripetuti aspettarsi, quanto
  le stime hanno sbagliato finora) e resta valido ovunque.

## L'app (AnimeUp.app)

I tuoi episodi vanno copiati in **`~/Movies/AnimeUp/INPUT`**; i video finiti
arrivano in **`~/Movies/AnimeUp/OUTPUT`**. Puoi scegliere altre cartelle,
anche su dischi esterni, nella sidebar o dalla pagina Sorgenti quando è
vuota; ognuna resta quella scelta finché non la cambi. Gli strumenti e
l'ambiente di AnimeUp stanno in `~/Library/Application Support/AnimeUp`
(circa 1 GB).

Chiudere la finestra non chiude AnimeUp: le lavorazioni in corso proseguono
in sottofondo, e un click sull'icona nel Dock riporta la finestra. **⌘Q**
esce davvero; se c'è una lavorazione in corso prima chiede conferma, poi la
ferma (la puoi riprendere più tardi, perdendo al massimo il blocco in
corso).

## Spostare la cartella / secondo Mac

Copia l'intera cartella (disco esterno incluso): al primo avvio `./animeup`
ripara da solo l'ambiente Python se serve. Non serve Homebrew né un Python
di sistema. Da Terminale si possono spostare le cartelle con delle
variabili: `ANIMEUP_INPUT` e `ANIMEUP_OUTPUT` per le due cartelle dei video,
`ANIMEUP_ROOT` per la cartella che contiene INPUT/ e OUTPUT/ di fabbrica,
`ANIMEUP_STATO` per i dati di AnimeUp (records/, cache/, bin/).

## Se qualcosa va storto

| Sintomo | Cosa fare |
|---|---|
| voglio FERMARE una lavorazione in corso | **Ferma** sulla riga del file interrompe solo quello (il resto del lancio prosegue); **Ferma tutto** nella barra in basso interrompe il file in corso e annulla i successivi. In entrambi i casi il file interrotto resta riprendibile. Senza interfaccia: `kill $(cat "OUTPUT/JOBS/<cartella>/running.lock")` |
| "un'altra lavorazione è già in corso" ma non c'è | il lucchetto è di un processo morto: si sblocca da solo al lancio successivo; se insiste, cancella `running.lock` in quella cartella di `OUTPUT/JOBS` |
| file `.DEFECTIVE.mkv` in OUTPUT | la lavorazione ha avvisi gravi: rilancia il file, si rifà da dove può |
| anteprime con blocchi verdi/rosa | cache vecchia di un file corrotto ai seek: cancella la sottocartella in `cache/previews/` e rigenera |
| la UI non parte: porta occupata | `lsof -ti :8899 \| xargs kill`, oppure `./animeup ui --porta 8900` |
| dubbi sui parametri | TARATURE.md spiega ogni scelta con le misure |

## Disinstallare

**L'app.** Esci da AnimeUp (⌘Q), poi cancella:

- `AnimeUp.app` da Applicazioni;
- `~/Library/Application Support/AnimeUp`: i suoi strumenti, l'ambiente
  Python, lo storico, le impostazioni e la taratura (circa 1 GB);
- `~/Library/Caches/io.github.interstellar0verdrive.animeup`,
  `~/Library/WebKit/io.github.interstellar0verdrive.animeup` e
  `~/Library/HTTPStorages/io.github.interstellar0verdrive.animeup`: ciò che
  salva la finestra dell'app, come ogni app per Mac che mostra contenuti web.

Per arrivare a `~/Library` dal Finder scegli **Vai → Vai alla cartella…**
(⇧⌘G) e scrivi il percorso. Oppure, nel Terminale:

```bash
rm -rf /Applications/AnimeUp.app "$HOME/Library/Application Support/AnimeUp" \
  "$HOME/Library/Caches/io.github.interstellar0verdrive.animeup" \
  "$HOME/Library/WebKit/io.github.interstellar0verdrive.animeup" \
  "$HOME/Library/HTTPStorages/io.github.interstellar0verdrive.animeup"
```

I tuoi video restano dove sono: `~/Movies/AnimeUp` (o le cartelle che hai
scelto) contiene i sorgenti, i video finiti e le eventuali lavorazioni
interrotte in `OUTPUT/JOBS`, che possono pesare parecchio. Cancella quello
che non ti serve più.

**La cartella portatile.** Chiudi la finestra del Terminale che la fa
girare, porta fuori da `INPUT/` e `OUTPUT/` i video che vuoi tenere e
cancella la cartella: tutto ciò che AnimeUp ha installato sta lì dentro.
