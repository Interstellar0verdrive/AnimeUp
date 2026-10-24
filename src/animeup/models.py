"""I modelli disponibili e come sceglierli.

Due famiglie, con caratteri opposti:

  realesr-animevideov3  veloce, denoise integrato. Linee nettissime, ma tratta
                        la texture a basso contrasto come rumore e la spiana.
  realcugan             più lento (~2.7x), conserva la texture. Nella variante
                        no-denoise conserva però anche il rumore, quindi va
                        usata solo su sorgenti puliti.

Varianti scartate dopo verifica sui file reali:
  cugan pro           2 fotogrammi corrotti su 240, silenziosamente (uno con i
                      canali colore alterati, uno nero pieno). Inaffidabile.
  cugan conservative  banding visibile sulle sfumature morbide.
  x4plus-anime        più morbido e 4x più lento di animevideov3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .i18n import t


class Family(str, Enum):
    ESRGAN = "realesrgan"
    CUGAN = "realcugan"


@dataclass(frozen=True)
class Model:
    key: str
    family: Family
    # Chiavi dei testi, non i testi: il catalogo nasce all'import e la lingua
    # può cambiare ad app aperta. `label` e `description` li traducono alla
    # lettura.
    chiave_label: str
    scales: tuple[int, ...]
    throughput: dict[int, float]   # megapixel di ingresso al secondo, per scala
    denoises: bool
    chiave_description: str

    # --- parametri specifici di realcugan ---
    cugan_noise: int | None = None      # valore da passare a -n
    cugan_models: str | None = None     # cartella modelli, relativa al binario

    @property
    def label(self) -> str:
        return t(self.chiave_label)

    @property
    def description(self) -> str:
        return t(self.chiave_description)

    @property
    def short(self) -> str:
        """Etichetta compatta, per i punti dove lo spazio è poco."""
        return self.label.removeprefix("Real-ESRGAN ").removeprefix("Real-")

    def model_name(self, scale: int) -> str:
        """Nome del file di modello effettivamente usato, a scopo diagnostico.

        realesrgan lo riceve come argomento; realcugan invece lo deriva da solo
        da scala e livello di rumore, ma averlo esplicito serve nei log e nel
        piano per sapere con certezza cosa è stato eseguito.
        """
        if self.family is Family.ESRGAN:
            return f"{self.key}-x{scale}"
        return self.key.replace("{scale}", str(scale))


# L'ordine è quello in cui vengono mostrati, e non è casuale: da chi
# conserva meno a chi conserva di più. animevideov3 spiana, CUGAN con pulizia
# conserva ripulendo, CUGAN puro conserva tutto — rumore incluso. Così la
# fila si legge come una scala e non come un elenco di nomi.
#
# Throughput misurati sul lotto da 240 fotogrammi, modello caricato una volta
# sola: sono i valori di produzione, non stime da prove brevi.
CATALOG: dict[str, Model] = {
    "animevideov3": Model(
        key="realesr-animevideov3",
        family=Family.ESRGAN,
        chiave_label="mot.modello.animevideov3.label",
        scales=(2, 3, 4),
        # x4 era 1.08: misurato quando il salvataggio dei PNG girava su due
        # soli thread ed era LUI il collo di bottiglia, non la GPU. Con
        # `-j 2:2:4` (vedi backend.upscale_dir) la stessa macchina fa 1.87.
        # Si tiene 1.80, poco sotto il misurato: le stime di fabbrica
        # devono sbagliare per eccesso di prudenza, non per ottimismo.
        throughput={2: 1.95, 3: 1.79, 4: 1.80},
        denoises=True,
        chiave_description="mot.modello.animevideov3.descrizione",
    ),
    "cugan-denoise": Model(
        key="up{scale}x-denoise1x",
        family=Family.CUGAN,
        chiave_label="mot.modello.cugan-denoise.label",
        scales=(2,),            # denoise1x esiste solo per la scala 2
        throughput={2: 1.02},
        denoises=True,
        chiave_description="mot.modello.cugan-denoise.descrizione",
        cugan_noise=1,
        cugan_models="models-se",
    ),
    "cugan": Model(
        key="up{scale}x-no-denoise",
        family=Family.CUGAN,
        chiave_label="mot.modello.cugan.label",
        scales=(2, 3, 4),
        # x4 era 0.57, misurato su un campione breve dove il caricamento del
        # modello pesava più del lavoro. Ricavato dai log di due lavorazioni
        # vere (400p e 288p, 346 e 427 fotogrammi): 0.91 e 0.85. Si tiene il
        # più basso. Sbagliare per difetto qui gonfiava la stima del 50%.
        throughput={2: 1.02, 3: 0.66, 4: 0.85},
        denoises=False,
        chiave_description="mot.modello.cugan.descrizione",
        cugan_noise=0,          # ATTENZIONE: 0 = no-denoise. L'aiuto del binario
                                # dice -1, ed è sbagliato: -1 seleziona conservative.
        cugan_models="models-se",
    ),
}

DEFAULT_MODEL = "animevideov3"

# --- soglia per la raccomandazione ----------------------------------------
# Sopra questa altezza conviene conservare tutto fedelmente; sotto conviene
# ripulire. La ragione non è che i file piccoli siano necessariamente sporchi
# (non è vero: fra i campioni, il 360p era più pulito del 480p), ma che
# l'asimmetria del compromesso si ribalta:
#   - il rumore conservato cresce in area quanto il quadrato del fattore di
#     ingrandimento, quindi da 360p verso 1080p pesa nove volte più che da
#     720p verso 1080p;
#   - il dettaglio fine autentico che il denoise sacrifica è invece tanto
#     minore quanto più bassa è la risoluzione di partenza.
# Entrambi i lati spingono nella stessa direzione.
# Confini fra le tre fasce, in altezza codificata del sorgente.
#
# Non sono ragionati a tavolino: vengono dal giudizio dell'utente su sei
# lavorazioni reali (tre sorgenti x due modelli), guardate IN RIPRODUZIONE con
# video-compare, non solo sui ritagli fermi. È una differenza che conta: in
# movimento si vedono lo sfarfallio temporale e la stabilita' del dettaglio fra
# un fotogramma e l'altro, che un fermo immagine non può mostrare. I ritagli a
# 1:1 e le misure di texture qui sotto sono la conferma numerica di quel
# giudizio, non la sua fonte.
#
#   720p (Koyomimonogatari)  CUGAN nettamente meglio. Le linee nere sono più
#                            definite e gli sfondi conservano la texture, che
#                            animevideov3 spiana ("brulla gli sfondi, resa
#                            troppo morbida"). Misurato: texture 1.39 contro
#                            1.02 in una zona piatta.
#   400p (Qwaser "480p")     ancora CUGAN, ma con meno distacco.
#   288p (Qwaser "360p")     animevideov3 nettamente meglio. A quella
#                            risoluzione non c'e' dettaglio autentico da
#                            conservare: CUGAN conserva e ingrandisce la mota
#                            della compressione, animevideov3 dà ciocche
#                            pulite. Meno dettagliato, molti meno artefatti.
#
# La fascia dei 480p resta in mezzo e cambia da file a file: lì non si
# consiglia con sicurezza, si manda al Confronto. Vedi ALTEZZA_INCERTA.
CLEAN_SOURCE_MIN_HEIGHT = 560     # da qui in su (576p, 720p...) CUGAN
ALTEZZA_INCERTA = 380             # sotto questa, animevideov3

# NOTA STORICA - perché NON si usa una misura del rumore.
# È stata implementata e provata: alta frequenza nelle sole zone senza bordi.
# Si è rivelata instabile, perché dipende troppo da quali fotogrammi
# finiscono nel campione: sugli stessi tre file, misurando 1 fotogramma o 4,
# i valori cambiavano di tre volte e l'ordine relativo fra due sorgenti si
# invertiva. Una metrica instabile che guida una decisione è peggio di
# nessuna metrica: fa passare per misura quello che è solo un caso, e
# produce avvisi diversi a ogni esecuzione sullo stesso file.
# Prima di riprovarci serve una misura stabile, verificata su molti file.
# (Scartato anche l'indice di blocchettatura: il deblocking interno di H.264
# lo azzera, e un 360p molto degradato risultava "pulito".)


@dataclass
class Recommendation:
    model: str
    reason: str
    alternative: str | None = None
    # Falso nella fascia intermedia, dove la scelta dipende dal singolo file e
    # non dalla risoluzione. Serve a non far passare per consiglio quello che
    # è solo il meno peggio: chi legge deve sapere quando fidarsi e quando
    # guardare con i propri occhi.
    sicuro: bool = True
    # Il giudizio su OGNI modello della fascia, non solo sul vincitore:
    # "ok" = consigliato, "verifica" = da provare a occhio nel Confronto,
    # "no" = sconsigliato. Assente = niente da dire. È ciò che permette
    # alle schede dei modelli di colorarsi senza reinventare la politica.
    giudizi: dict = None


def recommend(height: int) -> Recommendation:
    """Propone un modello in base alla sola risoluzione del sorgente.

    Tre fasce, non due. Quella di mezzo esiste perché sul materiale reale il
    ribaltamento non è netto e dipende da quanto è sporco quel file: lì la
    base consigliata è il modello che sbaglia meno (animevideov3), e il
    candidato da verificare a occhio è il denoise leggero. Dire "verifica" e
    mandare al Confronto è più utile che tirare a indovinare con tono
    sicuro.
    """
    if height >= CLEAN_SOURCE_MIN_HEIGHT:
        return Recommendation(
            model="cugan",
            reason=t("mot.modello.consiglio_alta", altezza=height),
            giudizi={"cugan": "ok"},
        )
    if height >= ALTEZZA_INCERTA:
        # La base sicura è animevideov3: meno artefatti. Il denoise leggero
        # è il candidato da verificare a occhio quando il file merita più
        # dettaglio; il no-denoise qui amplifica il rumore di compressione.
        return Recommendation(
            model="animevideov3",
            reason=t("mot.modello.consiglio_media", altezza=height),
            alternative="cugan-denoise",
            sicuro=False,
            giudizi={"animevideov3": "ok", "cugan-denoise": "verifica",
                     "cugan": "no"},
        )
    return Recommendation(
        model="animevideov3",
        reason=t("mot.modello.consiglio_bassa", altezza=height),
        giudizi={"animevideov3": "ok", "cugan-denoise": "no", "cugan": "no"},
    )
