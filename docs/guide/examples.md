---
title: Examples
description: "Real before-and-after examples: the same frame plainly enlarged and upscaled by AnimeUp, with the model each kind of source wants."
---

<span class="eyebrow">Appendix · Examples</span>

# Examples

What AnimeUp does, on five kinds of source. Each picture was shrunk to the size of a real episode, then upscaled by AnimeUp: the left side is that small frame plainly enlarged, the right side the model's real output, untouched. Drag across a picture to compare, or open it at **1:1** to see every pixel.

!!! info "How these pictures were made"
    The pictures were drawn for this guide, then shrunk to the size of a real episode, with the compression of a real video file (the 540p one with the heavy compression of a low-bitrate web file). Nothing on the right was retouched: it's what the model produced from the small frame, the same way the app runs it.

## A clean 720p file, to 1440p

<div class="au-hero" tabindex="0" role="img" style="--zx:-50%;--zy:-49.07%;--zw:168.42%" data-before="720p · the original" data-after="1440p · AnimeUp" aria-label="A rainy night street at 720p, plainly enlarged on the left and upscaled to 1440p by Real-CUGAN no-denoise on the right. Drag to compare.">
  <img class="au-hero__pic" src="../img/v2/hero2-after.jpg" alt="">
  <span class="au-hero__clip"><img class="au-hero__pic" src="../img/v2/hero2-before.jpg" alt=""></span>
  <span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span>
  <img src="../img/v2/ex-labels-720-1440.webp" alt="">
  <button class="au-hero__zoom" type="button" title="Open at 100%, one picture pixel per screen pixel"><svg class="au-hero__zoomicon" width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1h4v4M11 1 7.2 4.8M5 11H1V7M1 11l3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>1:1</button>
</div>

**720p → 1440p · Real-CUGAN no-denoise**, the model AnimeUp recommends from 560 lines up.

**What to look at:** the pattern on the yukata, the paper of the lanterns, the wood grain of the houses, the leaves along the railing. A clean source has real detail to keep, and Real-CUGAN keeps it where Real-ESRGAN animevideov3 would flatten it into smooth patches.

## A DVD-size 480p file, to 1080p

<div class="au-hero" tabindex="0" role="img" style="--zx:-26.32%;--zy:-18.71%;--zw:126.32%" data-before="480p · the original" data-after="1080p · AnimeUp" aria-label="A seaside station at 480p, plainly enlarged on the left and upscaled to 1080p by Real-ESRGAN animevideov3 on the right. Drag to compare.">
  <img class="au-hero__pic" src="../img/v2/hero-after.jpg" alt="" loading="lazy">
  <span class="au-hero__clip"><img class="au-hero__pic" src="../img/v2/hero-before.jpg" alt="" loading="eager"></span>
  <span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span>
  <img src="../img/v2/ex-labels-480-1080.webp" alt="" loading="lazy">
  <button class="au-hero__zoom" type="button" title="Open at 100%, one picture pixel per screen pixel"><svg class="au-hero__zoomicon" width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1h4v4M11 1 7.2 4.8M5 11H1V7M1 11l3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>1:1</button>
</div>

**480p → 1080p · Real-ESRGAN animevideov3**, the model AnimeUp recommends below 560 lines.

**What to look at:** the level crossing and its stripes, the bus, the bicycles and the railings, then the houses on the hill behind. At 480p every line turns grey and soft; animevideov3 redraws them black, straight and clean, and cleans the colour around them. It's made for this kind of drawing: firm outlines and flat colours.

!!! tip "Where animevideov3 is less at ease"
    Strokes thinner than a pixel of the small frame (single eyelashes, hair strands, fine hatching) are already gone in a 480p file, so no model can bring them back. animevideov3 draws clean lines from what's left; Compare shows you how a model treats your own episode before you commit to it.

## An old TV episode at 360p, to 1080p

<div class="au-hero" tabindex="0" role="img" style="--zx:0%;--zy:-22.22%;--zw:200%" data-before="360p · the original" data-after="1080p · AnimeUp" aria-label="A starship at a space station at 360p, plainly enlarged on the left and upscaled to 1080p by Real-ESRGAN animevideov3 on the right. Drag to compare.">
  <img class="au-hero__pic" src="../img/v2/ex4-after.jpg" alt="" loading="lazy">
  <span class="au-hero__clip"><img class="au-hero__pic" src="../img/v2/ex4-before.jpg" alt="" loading="eager"></span>
  <span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span>
  <img src="../img/v2/ex-labels-360-1080.webp" alt="" loading="lazy">
  <button class="au-hero__zoom" type="button" title="Open at 100%, one picture pixel per screen pixel"><svg class="au-hero__zoomicon" width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1h4v4M11 1 7.2 4.8M5 11H1V7M1 11l3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>1:1</button>
</div>

**360p → 1080p · Real-ESRGAN animevideov3**, three times the size, from the smallest kind of file you're likely to have.

**What to look at:** the pilot's hair, the harness straps and the red stripes of the flight suit, then the station and the ship behind, all panel lines and lit windows. At 360p they are a jagged, muddy blur; animevideov3 draws them back as clean black outlines and flat colour. One honest detail: a few of the tiniest stars, a single pixel in the 360p file, go with the noise it cleans away.

## A badly compressed 540p web rip, to 1080p

<div class="au-hero" tabindex="0" role="img" style="--zx:0%;--zy:-70.37%;--zw:200%" data-before="540p · badly compressed web rip" data-after="1080p · AnimeUp" aria-label="A lake at dawn from a badly compressed 540p web rip, plainly enlarged on the left and upscaled to 1080p by Real-CUGAN light denoise on the right. Drag to compare.">
  <img class="au-hero__pic" src="../img/v2/ex5-after.jpg" alt="" loading="lazy">
  <span class="au-hero__clip"><img class="au-hero__pic" src="../img/v2/ex5-before.jpg" alt="" loading="eager"></span>
  <span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span>
  <img src="../img/v2/ex-labels-540-1080.webp" alt="" loading="lazy">
  <button class="au-hero__zoom" type="button" title="Open at 100%, one picture pixel per screen pixel"><svg class="au-hero__zoomicon" width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1h4v4M11 1 7.2 4.8M5 11H1V7M1 11l3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>1:1</button>
</div>

**540p → 1080p · Real-CUGAN light denoise**, for sources that aren't clean. In the app it's the model "worth checking" between 380 and 560 lines.

**What to look at:** the grass, the flowers and the planks of the pier, then the water and the rocks behind. The 540p file was saved the way the worst web rips are, at a starved bitrate: its gradients break into blocks, its edges into smudges. Light denoise cleans that dirt away and keeps the drawing: the grass and the wood stay crisp, the water goes smooth again. Without the denoise, Real-CUGAN no-denoise would enlarge the blocks along with the picture.

## A painted 720p frame, to 4K

<div class="au-hero" tabindex="0" role="img" style="--zx:-46.05%;--zy:-49.07%;--zw:252.63%" data-before="720p · the original" data-after="2160p · AnimeUp" aria-label="A painted greenhouse library at 720p, plainly enlarged on the left and upscaled to 2160p by Real-CUGAN conservative on the right. Drag to compare.">
  <img class="au-hero__pic" src="../img/v2/ex3-after.jpg" alt="" loading="lazy">
  <span class="au-hero__clip"><img class="au-hero__pic" src="../img/v2/ex3-before.jpg" alt="" loading="eager"></span>
  <span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span>
  <img src="../img/v2/ex-labels-720-2160.webp" alt="" loading="lazy">
  <button class="au-hero__zoom" type="button" title="Open at 100%, one picture pixel per screen pixel"><svg class="au-hero__zoomicon" width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1h4v4M11 1 7.2 4.8M5 11H1V7M1 11l3.8-3.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>1:1</button>
</div>

**720p → 2160p · Real-CUGAN conservative**, the most faithful model, for grain and painted texture.

**What to look at:** open it at 1:1. The book spines, the iron frames, the ferns and the flowers stay crisp at three times the size, where the plain enlargement turns them into a soft blur. Conservative keeps the most of what the painting had, leftovers included, so it suits clean, richly painted sources best.

## Try it on your own episodes

These are five cases; your series is another one. [Compare](06-compare.md) renders the hardest clips of your own file with each model and shows them side by side, exactly like these pictures, before you start the queue.

[Next: Designing AnimeUp 2.0 →](deep-dives/design.md)
