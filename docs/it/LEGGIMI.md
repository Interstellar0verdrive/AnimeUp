# AnimeUp

**Upscaler anime per Mac con Apple Silicon, in locale e senza rete.**

AnimeUp è un'app per Mac che rende belli su uno schermo moderno gli anime a
risoluzione DVD o web (tipicamente da 240p a 720p). Ingrandisce ogni
fotogramma con un modello di intelligenza artificiale sulla GPU del Mac
([Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) e
[Real-CUGAN](https://github.com/bilibili/ailab/tree/main/Real-CUGAN)) e
scrive un nuovo video accanto all'originale, con tutto l'audio, i
sottotitoli, i capitoli e i font.

Tutto succede sul tuo Mac: niente upload, niente account, e dopo il primo
avvio AnimeUp funziona offline. L'app è in italiano e in inglese
(Impostazioni › Generali).

## Cosa fa

- **Analizza ogni video appena arriva**: frame rate, interlacciamento,
  tracce, file troncati. I problemi si vedono prima di cominciare, non a metà.
- **Ti fa scegliere il modello a occhio**: trova i momenti più difficili di un
  episodio, li elabora con ogni modello e te li mostra affiancati.
- **Lavora a blocchi**: fermare, chiudere l'app o un crash costano al massimo
  il blocco in corso, e il lavoro riprende da lì.
- **Ti dice quanto ci vorrà**, dalla velocità reale del tuo Mac, misurata con
  una calibrazione di circa 10 minuti.

## Requisiti

- Un Mac con **Apple Silicon** (M1 o successivi) e **macOS 26** o successivo.
- Internet **solo al primo avvio**, per scaricare gli strumenti video (circa
  220 MB, ognuno verificato col suo checksum).
- Spazio su disco: un episodio può occupare temporaneamente decine di GB
  mentre viene elaborato. AnimeUp mostra quanto ne usa e permette di
  fissare un limite.

## Installazione

1. Scarica `AnimeUp-v2.0.0-macos-app.zip` dall'[ultima
   release](https://github.com/Interstellar0verdrive/AnimeUp/releases/latest),
   scompattalo e trascina **AnimeUp.app** in Applicazioni.
2. Aprila. La prima volta macOS la blocca, perché AnimeUp non è firmata con un
   Apple Developer ID: apri **Impostazioni di Sistema › Privacy e
   sicurezza**, scorri fino al messaggio su AnimeUp e fai clic su **Apri
   comunque**. Va fatto una volta sola.
3. Al primo avvio AnimeUp scarica i suoi strumenti (FFmpeg, Real-ESRGAN,
   Real-CUGAN, Python). Poi funziona offline.

## Come si usa

1. **Calibra** il Mac una volta, circa 10 minuti con la GPU libera.
2. **Aggiungi i video**: trascina file o cartelle intere sulla finestra.
3. **Confronta** i modelli su qualche clip difficile, se vuoi scegliere a
   occhio.
4. **Avvia la coda** e seguila: pausa, stop, ripresa e Rifai, senza perdere
   il lavoro fatto.

I video finiti vanno accanto agli originali, con il nome originale più i
parametri usati, per esempio
`Episodio 01 [upscale 1080p cugan x3 crf18 dd].mkv`.

## Per saperne di più

La [guida](https://interstellar0verdrive.github.io/AnimeUp/guide/) è in
inglese e spiega ogni pagina dell'app, i modelli e gli studi di confronto, e
lo studio di design dietro la 2.0. Le misure dietro ogni valore predefinito
sono in [TARATURE.md](TARATURE.md).

AnimeUp è software libero, sotto licenza
[GNU GPL v3 o successiva](../../LICENSE).
