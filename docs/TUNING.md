# AnimeUp — tuned numbers: what they're based on, and what happens if they're wrong

*Italian version: [it/TARATURE.md](it/TARATURE.md)*

This tool contains around twenty constants derived from measurements. The
measurements come from **two series and sixteen files**: Koyomimonogatari
(720p Hi444PP) and The Qwaser of Stigmata (400p and 288p). That's a narrow
sample, and it's worth knowing where this could hurt.

The distinction that matters is not "how accurate is it" but **what happens
if it's wrong**:

- **ESTIMATE** — if it's wrong, a number shown on screen is inaccurate. An
  annoyance, not damage.
- **GATE** — if it's wrong, the program refuses or interrupts legitimate
  work. A gate tuned on the wrong material can make a file impossible to
  process.

Gates deserve far more suspicion than estimates. Below, each one is listed
with its evidence and its way out.

---

## Gates

| constant | where | evidence | way out if it's wrong |
|---|---|---|---|
| `GUADAGNO_MINIMO = 1.25` | `plan.py` | the user's choice, not a measurement | `--forza` |
| final height `< 64` → refused | `plan.py` | universal (below that it isn't a target, it's a typo) | none, but the case isn't realistic |
| `PRESET_VALIDI` | `plan.py` | x265's actual list | none needed |
| CRF outside `0..51` → refused | `plan.py` | x265's actual range | none needed |
| model that can't reach the target → refused | `plan.py` | geometric, not tuned | `--forza` |
| `DEFAULT_THRESHOLD_8BIT = 16` | `dedup.py` | provable upper bound, not statistical | `--no-dedup` |
| `MAX_RUN_LIMITE = 1000` | `dedup.py` | structural sanity | none needed |
| `STALLO_SECONDI = 900` | `backend.py` | slowest frame measured < 2 s | 450× margin |

### The gate that worried me most: removed

`DEFAULT_TOLERANCE` in `validate.py` was the serious risk, and in the end the
whole mechanism was **removed**. Not out of laziness: because its inference
can't be proven.

The metric measured reliably and reproducibly (verified: it matches an
independent calculation to within 0.5 out of 255). What didn't hold up was
the step from *"this frame differs a lot"* to *"this frame is corrupted"*.
Measured on the same healthy frames:

| content | animevideov3 x3 | cugan x3 |
|---|---|---|
| real anime | 6 | 3 |
| 2 px checkerboard | 6 | **128** |
| dense noise | 10 | 13 |

Two different models differ from each other **more** than a fault does.
There is no threshold that separates the two. Nor does the trick of "redo it
with the other model" settle it, because it's precisely the difference
between models that produces the signal: you would end up replacing good
cugan frames with animevideov3 frames on dense content, which is exactly
where cugan was chosen.

The fault that had motivated the mechanism — 2 frames out of 240 — came from
`realcugan` with the **"pro"** models, which aren't in the catalogue. That
case can no longer be reached.

What remains are the protections that don't require guesswork: a non-zero
exit code from the model, missing frames compared by NAME, the stall
detector, and the check on the final file (frame count and geometry), which
ends up among the `difetti` (defects).

---

## Estimates

**Before the table, the distinction that matters.** Not all constants have
the same lifespan. There are three kinds, and mixing them up leads to
pointless discussions along the lines of "so the number written here is
wrong?".

1. **Factory estimates, replaced by measurement.** They only matter until
   the machine has been calibrated. Once calibration is done, the number
   written in the code is no longer read: `registri/taratura.json` wins. The
   factory value is a compromise across different machines, so it's
   *normal* for it not to match any particular one.
2. **Values overridden by history.** These are about content, not hardware.
   As soon as there are job reports in `esiti.jsonl`, what those files
   actually did is used instead of the theoretical value.
3. **True constants.** Nothing replaces them: they always apply, on every
   machine and with every kind of material.

| constant | where | evidence | applies until | effect if it's wrong |
|---|---|---|---|---|
| `FPS_CODIFICA = 8.0` | `plan.py` | 9.28 fps measured on 240 1080p frames, idle machine | **until calibration** → `codifica_fps` | time range shifted |
| catalogue `throughput` | `models.py` | from the logs of real jobs | **until calibration** → `mpxs` | time range |
| extraction 60 f/s, scan 200 f/s | `plan.py` (inline) | initial measurements | **until calibration** | time range |
| `MPX_TARATURA` | `plan.py` | size of the test clip | **until calibration** → `mpx_misura` | scales badly across resolutions |
| `DEDUP_MASSIMO = 0.60` | `plan.py` | observed 57%, 46%, 41%, 28%, 11% | **until the first job report** → observed deduplication | optimistic end of the range |
| `MARGINE_PESSIMISTA = 1.25` | `plan.py` | the measurements are averages; a busy scene costs more | **always** | upper bound of the range |
| `BYTES_PER_PIXEL_SOURCE = 1.05` | `plan.py` | measured 0.93–1.08 | **always** | see note below |
| `BYTES_PER_PIXEL_UPSCALED = 1.75` | `plan.py` | measured 1.43–1.75 | **always** | see note below |
| `EST_BITRATE_MBPS_1080P = 3.0` | `plan.py` | measured 0.77 on one scene; kept generous | **always** | see note below |
| `CLEAN_SOURCE_MIN_HEIGHT`, `ALTEZZA_INCERTA` | `models.py` | three comparisons judged during playback | **always** | model recommendation |

Estimates fail **forwards**: they produce an inaccurate time range. None of
them prevents you from working.

### How far the factory estimates are from reality

On this Mac (Apple M4), after calibration:

| quantity | factory | measured | difference |
|---|---|---|---|
| extraction (f/s) | 60.00 | 84.20 | **+40%** |
| x265 1080p encoding (f/s) | 8.00 | 6.57 | **−18%** |
| deduplication scan (f/s) | 200.00 | 363.90 | **+82%** |
| animevideov3 x2 (Mpx/s) | 1.95 | 1.77 | −9% |
| animevideov3 x3 (Mpx/s) | 1.79 | 1.75 | −2% |
| animevideov3 x4 (Mpx/s) | 1.80 | 1.76 | −2% |
| CUGAN light denoise x2 (Mpx/s) | 1.02 | 1.36 | **+34%** |
| CUGAN no-denoise x2 (Mpx/s) | 1.02 | 1.39 | **+36%** |
| CUGAN no-denoise x3 (Mpx/s) | 0.66 | 0.70 | +6% |
| CUGAN no-denoise x4 (Mpx/s) | 0.85 | 0.87 | +2% |

How to read this: **the factory value is not an error to be corrected**, it's
a starting point for a machine that isn't known yet. The 8.0 fps of
`FPS_CODIFICA` sits between the 9.28 measured on the test machine at the time
and the 6.57 of this Mac: neither is "the" right value, because it depends
on the machine. That's why the interface keeps pushing for calibration and
says "never calibrated" until it has been done.

The same logic applies to deduplication: `DEDUP_MASSIMO = 0.60` is the
theoretical ceiling used when nothing is known. As soon as there are job
reports, the range is built on the minimum, maximum and median **observed**
on this material, and the whole estimate is multiplied by a correction
learned from past errors. So here too: if one day a deduplication of 70% is
measured, it isn't the constant that's wrong — it has simply stopped being
the one that decides.

> **Correction to this table.** The three disk-space constants are NOT pure
> estimates: they make up `est_peak_disk_gb`, which the guard in
> `pipeline._esegui` compares with the free space and, if it doesn't fit,
> **refuses to start**. So they are a gate in every respect, and were
> misclassified here. Verified that the refusal really happens (900 MB
> volume: *"servono circa 4 GB, liberi 1 GB"* — "about 4 GB needed, 1 GB
> free"). The error measured on a real episode is +11%, within what is
> stated; `EST_BITRATE_MBPS_1080P`, however, was 8× the measured value and
> has been brought back to 3.0, because on a two-hour film going to 2160p
> that term was worth ~42 GB of phantom space against ~5 real.

---

## Save threads: the number that couldn't be written in the table

The ncnn binaries accept `-j load:proc:save`. The third number is the thread
pool that writes the PNGs, and it's not a detail: beyond a certain point the
disk is the bottleneck, not the GPU. Measured on two machines, the ceiling
was reached at around **20 Mpx/s of output** on both the M4 and the M3 Pro —
that is, the same ceiling on different GPUs, which is the signature of a
write limit.

The right value **can't be written here**, because it changes with the disk:
an internal SSD and an external USB drive don't saturate at the same point.
That's why, since 1.2, calibration **tries it on the spot** instead of
declaring it: a dedicated step processes the same clip with 2, 4, 6 and 8
threads and keeps the best, with two safeguards written into the code:

- each candidate is compared **with the baseline**, never with the current
  best, otherwise the order of the trials changed the result (the same
  measurements gave 6 or 8 depending on how you looked at them);
- a candidate is accepted only if its outputs are **identical** to those of
  the baseline, checked with a signature of all names and sizes plus six
  content hashes spread across the frames. The first version compared just
  one frame in eighty and declared itself satisfied.

Example measurement on Apple M4, 80-frame clip:

| threads | frames/s |
|---|---|
| 2 | 2.994 |
| 4 | **4.507** |
| 6 | 4.485 |
| 8 | 4.437 |

The gain from 4 upwards is within the noise, so 4 is kept. On a machine that
has never been calibrated, it starts from a cautious value (4, and never
more than the number of cores) rather than from the maximum: an aggressive
default on a small machine pays the cost of saturation without the benefit.

**Why calibration alone isn't enough to estimate an encoding pass.**
`codifica_fps` measures pure encoding, but the pass between one chunk and the
next also includes rebuilding the duplicate frames. Measured on a four-chunk
job: 234 seconds predicted by calibration against 280, 463 and 303 measured,
i.e. an underestimate of 49%. That's why, for the time remaining, the
interface uses the **measured** duration of that job's passes and falls back
on calibration only for the first chunk, when there's nothing to measure
yet.

---

## The model recommendation

`CLEAN_SOURCE_MIN_HEIGHT = 560` and `ALTEZZA_INCERTA = 380` are not gates:
the model can always be chosen by hand. They come from three comparisons
judged during playback (720p, 400p, 288p). The middle band is declared
**uncertain** precisely because three points aren't enough to draw two
boundaries.

---

## How to check on new material

The test bench in `PROVE/banco.py` generates about fifty files that **don't
resemble** the ones it was tuned on: resolutions from 96×64 to 2560×1440,
seven non-square pixel conventions (8:9, 10:11, 16:15, 32:27, 64:45, 118:81,
4:3), eleven frame rates including 11.988, 8/10/12-bit depth, 4:2:0/4:2:2/4:4:4
chroma subsampling, seven codecs, seven containers, five colour spaces.

```bash
.venv/bin/python PROVE/banco.py          # generate
.venv/bin/python PROVE/passa_banco.py    # analysis and plan: look for refusals
.venv/bin/python PROVE/esegui_banco.py   # process everything and check the result
```

If one day a file behaves strangely, the first useful question is: **which
row of these tables does it concern?**

---

## Result of the latest bench run

Analysis and plan on all 48: **no refusals, no exceptions.**

Processing through to the final file: **46 processed, 2 rightly skipped**
(already at the requested size or larger), **zero failures** — checking for
each one the frame count, duration, height, square pixels and the three
colour tags.

A few cases worth having seen work:

| file | result |
|---|---|
| `r_1920x816_scope` | → 2542×1080, CinemaScope with the aspect ratio preserved |
| `r_96x64_minuscolo` | → 384×256, the 4× limit applying and saying so |
| `a_sar_118_81` | → 1928×1080, videoconferencing-style non-square pixels |
| `a_sar_8_9_ntsc43` | → 1440×1080, NTSC 4:3 |
| `f_11988_indue` | 11.988 fps, NTSC animation "on twos" |
| `p_420_12` | 12-bit |
| `c_mpeg2.mpg`, `c_vp9.webm`, `c_mpeg4.avi` | unusual codecs and containers |
| `v_smptebars` | 83% deduplication on static content |

**What the bench found**, and the reason it's worth keeping: the frame check
was flagging in bursts on high-frequency synthetic material, and triggering
a repair **for every frame**. That led to three attempts to contain it, and
finally the decision to remove the mechanism — see above. The bench took a
piece of code apart, which is exactly the job you expect a bench to do.
