# AnimeUp — numeri tarati: su cosa, e cosa succede se sbagliano

Questo strumento contiene una ventina di costanti ricavate da misure. Le misure
vengono da **due serie e sedici file**: Koyomimonogatari (720p Hi444PP) e The
Qwaser of Stigmata (400p e 288p). È un campione stretto, e vale la pena sapere
dove questo può fare male.

La distinzione che conta non è "quanto è precisa" ma **cosa succede se è
sbagliata**:

- **STIMA** — se sbaglia, un numero mostrato è impreciso. Fastidio, non danno.
- **CANCELLO** — se sbaglia, il programma rifiuta o interrompe lavoro
  legittimo. Un cancello tarato su materiale sbagliato può rendere un file
  impossibile da elaborare.

I cancelli vanno guardati con sospetto molto maggiore delle stime. Sotto,
ciascuno con la sua evidenza e la sua via d'uscita.

---

## Cancelli

| costante | dove | evidenza | via d'uscita se sbaglia |
|---|---|---|---|
| `GUADAGNO_MINIMO = 1.25` | `plan.py` | scelta dell'utente, non una misura | `--forza` |
| altezza finale `< 64` → rifiuto | `plan.py` | universale (sotto non è un bersaglio, è un refuso) | nessuna, ma il caso non è reale |
| `PRESET_VALIDI` | `plan.py` | l'elenco vero di x265 | nessuna necessaria |
| CRF fuori `0..51` → rifiuto | `plan.py` | l'intervallo vero di x265 | nessuna necessaria |
| modello che non arriva al bersaglio → rifiuto | `plan.py` | geometrico, non tarato | `--forza` |
| `DEFAULT_THRESHOLD_8BIT = 16` | `dedup.py` | limite superiore dimostrabile, non statistico | `--no-dedup` |
| `MAX_RUN_LIMITE = 1000` | `dedup.py` | sanità strutturale | nessuna necessaria |
| `STALLO_SECONDI = 900` | `backend.py` | fotogramma più lento misurato < 2 s | margine 450× |

### Il cancello che mi preoccupava di piu': tolto

`DEFAULT_TOLERANCE` in `validate.py` era il rischio serio, e alla fine il
meccanismo intero e' stato **rimosso**. Non per pigrizia: perche' la sua
inferenza non e' dimostrabile.

Il metro misurava in modo affidabile e riproducibile (verificato: coincide col
calcolo indipendente entro 0,5 su 255). Quello che non reggeva era il passaggio
da *"questo fotogramma si discosta molto"* a *"questo fotogramma e' corrotto"*.
Misurato sugli stessi fotogrammi sani:

| contenuto | animevideov3 x3 | cugan x3 |
|---|---|---|
| anime vero | 6 | 3 |
| scacchiera 2 px | 6 | **128** |
| rumore fitto | 10 | 13 |

Due modelli diversi si discostano fra loro **piu'** di quanto si discosti un
guasto. Non esiste una soglia che separi le due cose. E nemmeno il trucco di
"rifallo con l'altro modello" dirime, perche' e' proprio la differenza fra
modelli a produrre il segnale: si finirebbe a sostituire buoni fotogrammi cugan
con fotogrammi animevideov3 sul contenuto fitto, cioe' esattamente dove cugan
e' stato scelto.

Il guasto che aveva motivato il meccanismo — 2 fotogrammi su 240 — veniva da
`realcugan` con i modelli **"pro"**, che non sono nel catalogo. Il caso non e'
piu' raggiungibile.

Restano le protezioni che non richiedono di indovinare: codice di uscita del
modello diverso da zero, fotogrammi mancanti confrontati per NOME, rilevatore
di stallo, e la verifica del file finale (numero di fotogrammi e geometria) che
finisce fra i `difetti`.

---

## Stime

**Prima della tabella, la distinzione che conta.** Non tutte le costanti hanno
la stessa vita. Ce ne sono di tre tipi, e confonderli porta a discussioni
inutili del tipo «ma allora il numero scritto qui è sbagliato?».

1. **Valori di fabbrica, sostituiti dalla misura.** Servono solo finché la
   macchina non è stata tarata. Fatta la taratura, il numero scritto nel
   codice non viene più letto: vince `registri/taratura.json`. Il valore di
   fabbrica è un compromesso fra macchine diverse, quindi è *normale* che non
   coincida con nessuna in particolare.
2. **Valori scavalcati dalla storia.** Riguardano i contenuti, non
   l'hardware. Appena ci sono pagelle in `esiti.jsonl`, si usa quello che
   questi file hanno fatto davvero invece del valore teorico.
3. **Costanti vere.** Non le sostituisce niente: valgono sempre, su ogni
   macchina e con ogni materiale.

| costante | dove | evidenza | vale finché | effetto se sbaglia |
|---|---|---|---|---|
| `FPS_CODIFICA = 8.0` | `plan.py` | 9,28 fps misurati su 240 fotogrammi 1080p, macchina scarica | **fino alla taratura** → `codifica_fps` | intervallo di tempo spostato |
| `throughput` del catalogo | `models.py` | dai log di lavorazioni vere | **fino alla taratura** → `mpxs` | intervallo di tempo |
| estrazione 60 f/s, scansione 200 f/s | `plan.py` (in linea) | misure iniziali | **fino alla taratura** | intervallo di tempo |
| `MPX_TARATURA` | `plan.py` | dimensione dello spezzone di prova | **fino alla taratura** → `mpx_misura` | scala male fra risoluzioni |
| `DEDUP_MASSIMO = 0.60` | `plan.py` | osservati 57%, 46%, 41%, 28%, 11% | **fino alla prima pagella** → deduplica osservata | estremo ottimista dell'intervallo |
| `MARGINE_PESSIMISTA = 1.25` | `plan.py` | le misure sono medie; una scena mossa costa di più | **sempre** | tetto dell'intervallo |
| `BYTES_PER_PIXEL_SOURCE = 1.05` | `plan.py` | misurato 0,93–1,08 | **sempre** | vedi nota sotto |
| `BYTES_PER_PIXEL_UPSCALED = 1.75` | `plan.py` | misurato 1,43–1,75 | **sempre** | vedi nota sotto |
| `EST_BITRATE_MBPS_1080P = 3.0` | `plan.py` | misurato 0,77 su una scena; tenuto generoso | **sempre** | vedi nota sotto |
| `CLEAN_SOURCE_MIN_HEIGHT`, `ALTEZZA_INCERTA` | `models.py` | tre confronti giudicati in riproduzione | **sempre** | consiglio sul modello |

Le stime sbagliano **in avanti**: producono un intervallo di tempo poco
accurato. Nessuna impedisce di lavorare.

### Quanto sono lontani i valori di fabbrica dal vero

Su questo Mac (Apple M4), dopo la taratura:

| grandezza | di fabbrica | misurato | scarto |
|---|---|---|---|
| estrazione (f/s) | 60,00 | 84,20 | **+40%** |
| codifica x265 1080p (f/s) | 8,00 | 6,57 | **−18%** |
| scansione deduplica (f/s) | 200,00 | 363,90 | **+82%** |
| animevideov3 x2 (Mpx/s) | 1,95 | 1,77 | −9% |
| animevideov3 x3 (Mpx/s) | 1,79 | 1,75 | −2% |
| animevideov3 x4 (Mpx/s) | 1,80 | 1,76 | −2% |
| CUGAN denoise leggero x2 (Mpx/s) | 1,02 | 1,36 | **+34%** |
| CUGAN no-denoise x2 (Mpx/s) | 1,02 | 1,39 | **+36%** |
| CUGAN no-denoise x3 (Mpx/s) | 0,66 | 0,70 | +6% |
| CUGAN no-denoise x4 (Mpx/s) | 0,85 | 0,87 | +2% |

Da leggere così: **il valore di fabbrica non è un errore da correggere**, è un
punto di partenza per una macchina che non si conosce ancora. Gli 8,0 fps di
`FPS_CODIFICA` stanno fra i 9,28 misurati sul banco di allora e i 6,57 di
questo Mac: nessuno dei due è «il» valore giusto, perché dipende dalla
macchina. È il motivo per cui l'interfaccia insiste sulla taratura e dichiara
«mai tarato» finché non è stata fatta.

La stessa logica vale per la deduplica: `DEDUP_MASSIMO = 0.60` è il tetto
teorico che si usa quando non si sa niente. Appena ci sono pagelle, la
forchetta si costruisce sul minimo, il massimo e la mediana **osservati** su
questo materiale, e l'intera stima viene moltiplicata per una correzione
imparata dagli scarti passati. Quindi anche qui: se un domani si misura una
deduplica del 70%, non è la costante a essere sbagliata — è che ha smesso di
essere quella che decide.

> **Correzione a questa tabella.** Le tre costanti dello spazio NON sono pure
> stime: compongono `est_peak_disk_gb`, che la guardia in `pipeline._esegui`
> confronta con lo spazio libero e, se non torna, **rifiuta di partire**. Sono
> quindi un cancello a tutti gli effetti, ed erano classificate male qui.
> Verificato che il rifiuto avviene davvero (volume da 900 MB: *"servono circa
> 4 GB, liberi 1 GB"*). L'errore misurato su un episodio reale è +11%, dentro
> il dichiarato; `EST_BITRATE_MBPS_1080P` era però 8× il valore misurato ed è
> stato riportato a 3,0, perché su un film di due ore verso 2160p il termine
> valeva ~42 GB di fantasma contro ~5 reali.

---

## Thread di salvataggio: il numero che non si poteva scrivere in tabella

I binari ncnn accettano `-j carica:elabora:salva`. Il terzo numero è il pool di
thread che scrive i PNG, e non è un dettaglio: oltre un certo punto è il disco
a fare da collo di bottiglia, non la GPU. Misurato su due macchine, il tetto
arrivava intorno ai **20 Mpx/s in uscita** sia su M4 sia su M3 Pro — cioè lo
stesso tetto su GPU diverse, che è la firma di un limite di scrittura.

Il valore giusto **non è scrivibile qui**, perché cambia col disco: un SSD
interno e un disco esterno via USB non hanno lo stesso punto di saturazione.
Per questo dalla 1.2 la taratura lo **prova sul posto** invece di dichiararlo:
un passo dedicato elabora lo stesso spezzone con 2, 4, 6 e 8 thread e tiene il
migliore, con due cautele scritte nel codice:

- si confronta ogni candidato **con la base**, mai col migliore corrente,
  altrimenti l'ordine delle prove cambiava il risultato (le stesse misure
  davano 6 oppure 8 a seconda di come si guardavano);
- si accetta un candidato solo se le uscite sono **identiche** a quelle della
  base, verificate con la firma di tutti i nomi e dimensioni più sei impronte
  sparse del contenuto. La prima versione confrontava un fotogramma solo su
  ottanta e si dichiarava soddisfatta.

Misura di esempio su Apple M4, spezzone da 80 fotogrammi:

| thread | fotogrammi/s |
|---|---|
| 2 | 2,994 |
| 4 | **4,507** |
| 6 | 4,485 |
| 8 | 4,437 |

Il guadagno da 4 in su è dentro il rumore, quindi si tiene 4. Su una macchina
mai tarata si parte da un valore prudente (4, comunque non oltre il numero di
core) invece che dal massimo: un default aggressivo su una macchina piccola
paga il costo della saturazione senza il beneficio.

**Perché non basta la taratura per stimare un turno di codifica.** `codifica_fps`
misura la codifica pura, ma il turno fra un blocco e il successivo comprende
anche la ricostruzione dei fotogrammi duplicati. Misurato su una lavorazione a
quattro blocchi: 234 secondi previsti dalla taratura contro 280, 463 e 303
misurati, cioè una sottostima del 49%. Per questo l'interfaccia, per il tempo
che resta, usa la durata **misurata** dei turni di quella lavorazione e ripiega
sulla taratura solo per il primo blocco, quando non c'è ancora niente da
misurare.

---

## Il consiglio sul modello

`CLEAN_SOURCE_MIN_HEIGHT = 560` e `ALTEZZA_INCERTA = 380` non sono cancelli: il
modello resta sempre scegliibile a mano. Vengono da tre confronti giudicati in
riproduzione (720p, 400p, 288p). La fascia intermedia si dichiara **incerta**
proprio perché tre punti non bastano a tracciare due confini.

---

## Come verificare su materiale nuovo

Il banco in `PROVE/banco.py` genera una cinquantina di file che **non
assomigliano** a quelli su cui si è tarato: risoluzioni da 96×64 a 2560×1440,
sette convenzioni di pixel non quadri (8:9, 10:11, 16:15, 32:27, 64:45,
118:81, 4:3), undici framerate compreso 11,988, profondità 8/10/12 bit,
sottocampionamenti 4:2:0/4:2:2/4:4:4, sette codec, sette contenitori, cinque
spazi colore.

```bash
.venv/bin/python PROVE/banco.py          # genera
.venv/bin/python PROVE/passa_banco.py    # analisi e piano: cerca rifiuti
.venv/bin/python PROVE/esegui_banco.py   # elabora tutto e verifica il risultato
```

Se un giorno un file si comporta in modo strano, la prima domanda utile è:
**quale riga di questa tabella lo riguarda?**

---

## Esito dell'ultima passata sul banco

Analisi e piano su tutti e 48: **nessun rifiuto, nessuna eccezione.**

Elaborazione fino al file finale: **46 elaborati, 2 saltati a ragione** (già
alla dimensione richiesta o più grandi), **zero guasti** — verificando su
ciascuno il numero di fotogrammi, la durata, l'altezza, i pixel quadri e i tre
tag colore.

Qualche caso che vale la pena aver visto funzionare:

| file | esito |
|---|---|
| `r_1920x816_scope` | → 2542×1080, cinemascope con il rapporto conservato |
| `r_96x64_minuscolo` | → 384×256, il limite 4× che si applica e lo dichiara |
| `a_sar_118_81` | → 1928×1080, pixel non quadri da videoconferenza |
| `a_sar_8_9_ntsc43` | → 1440×1080, NTSC 4:3 |
| `f_11988_indue` | 11,988 fps, animazione "in due" NTSC |
| `p_420_12` | 12 bit |
| `c_mpeg2.mpg`, `c_vp9.webm`, `c_mpeg4.avi` | codec e contenitori fuori dal solito |
| `v_smptebars` | deduplica all'83% su contenuto fermo |

**Quello che il banco ha trovato**, ed è il motivo per cui vale la pena
tenerlo: la verifica dei fotogrammi segnalava a raffica su materiale sintetico
ad alta frequenza, e faceva partire una riparazione **per ogni fotogramma**.
Da lì sono nati tre tentativi di contenerla, e infine la decisione di togliere
il meccanismo — vedi sopra. Il banco ha smontato un pezzo di codice, che è
esattamente il lavoro che ci si aspetta da un banco.
