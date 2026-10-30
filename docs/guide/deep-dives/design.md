---
title: Designing AnimeUp 2.0
description: "The design study behind AnimeUp 2.0: why a native app, the hybrid approach, the design system, the study of states and the rules that came out of it."
---

<span class="eyebrow">Appendix · Design</span>

# Designing AnimeUp 2.0

<div class="au-fade" role="img" aria-label="The boards of AnimeUp’s design system, seen from afar: foundations, buttons, controls and patterns, in the dark theme and in the light one">
  <img src="../../img/v2/ds-cover-dark.png" alt="">
  <img src="../../img/v2/ds-cover-light.png" alt="">
  <svg class="au-fade__edge" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="0" x2="0" y2="0" vector-effect="non-scaling-stroke"/></svg>
</div>

How AnimeUp went from a page in the browser to a Mac app, and the decisions behind what you see. This page is for the curious, and for designers: you don't need it to use AnimeUp.

## Where it started

Up to 1.6, AnimeUp was a web page opened in the browser, built with [Streamlit](https://streamlit.io). It was a great way to start: a few lines of Python, and I could try ideas on real files the same evening. But the further the design went, the harder it pushed back:

- **A design system was a fight.** Streamlit draws its own widgets; giving them AnimeUp's look meant patching each one from outside, against internal names that could change with any update.
- **Responsive was bent, not designed.** The layout is a column of blocks Streamlit decides for you.
- **Every click reran the page.** The page flickered, scroll jumped, open rows closed.
- **The Mac was out of reach.** No native folder picker, notifications, Dock progress or quit confirmation without workarounds.
- **It lived in a tab.** Address bar, refresh, imitation dialogs, and work running with nothing on screen once the tab was closed.

<div class="au-swap" role="img" aria-label="AnimeUp 1.6, a page in the browser, giving way to AnimeUp 2.0, a native Mac app, in the same place">
  <img src="../../img/v2/renewal-20d-dark.png" alt="" loading="eager">
  <img class="au-swap__from" src="../../img/v2/renewal-16d-dark.png" alt="" loading="eager">
  <span class="au-swap__sun" aria-hidden="true"></span>
</div>

## The approach: native frame, own content

For 2.0 I started again in SwiftUI, with the same engine underneath and one goal: an app that behaves like every other Mac app, without losing what made AnimeUp recognisable, nor the skeleton of how it works: add videos, compare, process.

- **The frame is the Mac's.** Glass sidebar, Settings window, sheets, alerts, menus, notifications, Dock progress, SF Pro and SF Symbols. Nothing the Mac already does is redrawn.
- **The content is AnimeUp's.** File rows that are their own progress bars, the four steps and their chunks, the comparison player, the calibration charts, one cyan accent.

![AnimeUp 2.0: Compare picking the clips to test in a narrow window, with the pages as tabs at the top, and in front the Queue in a wide window, running a file with its drawer open](../img/v2/narrow-clips-and-queue-dark.png){ .au }

Every screen was then drawn against a design system built first: colours, type, spacing and every component with all its states. Not just the pages, but each of their states: empty, analysing, running, paused, stopped, failed, a full disk, a disconnected drive, a narrow window. More than a hundred boards, each reviewed, often several times, before a line of code; the app was then built on the same tokens and components, and any difference between the two was a bug.

![The screens drawn for AnimeUp 2.0 on one plane, with three of them raised in the light theme](../img/v2/all-screens-plane-dark.png){ .au }

## The design system

### Colour

![Accent and status colours](../img/v2/GuideDsColour.png){ .au }

- **One accent, one meaning.** Cyan says "AnimeUp is working" or "this is the way forward": the primary button, the progress, the current page. It's never decoration.
- **Status always comes in three**: a text colour, a tint and a line. Green is done, yellow is worth a look, red is stopped or failed. A status is never colour alone: it always has a word and, where it fits, an icon.
- **Surfaces in four levels**, from back to front: window, sidebar glass, surface, raised, plus an inset level for what sits inside a card.

### Type

Eight styles only, rounded to whole points and aligned with the macOS text styles (13 pt body). Numbers that change (times, frames, sizes) are in SF Mono, so they don't jump as they tick.

### Buttons

![Button roles and their states](../img/v2/GuideDsButtons.png){ .au }

Six roles, three sizes, five states. A button is chosen by **what it does**, never by where it sits:

| Role | Used for |
|---|---|
| Primary | The one way forward in a view: **at most one per view** |
| Secondary | Everything else |
| Destructive | Ends or throws away work: outlined, so it never shouts louder than the primary |
| Confirm destructive | Solid red, only inside the alert that asks for confirmation |
| In a note | Takes the colour of its note: the yellow update note, for instance |
| Plain | Icon-only actions; they get a tooltip |

Disabled is always 40% opacity of the same button. Hover only lightens the same fill, it never changes colour family.

### Notes

One shape for every message: an icon, a bold title, the text, and the note's actions, all in the status colour. A note never says only that something is wrong: it says what AnimeUp will do about it, or what you can do.

## The study of states

A file in AnimeUp lives through many states, and the row in the Queue has to show each one at a glance, from across the room, while you're doing something else.

![The states of a Queue row](../img/v2/GuideDsStates.png){ .au }

- **The row is its own progress bar.** A soft fill grows behind the row while it runs, with a slow wave moving through it; a thin bar along its bottom edge is split into the four steps, and the upscale into its chunks.
- **Paused is yellow and still.** No wave, no breathing dot: nothing moves, because nothing is happening.
- **Done is a static full fill**, green, or yellow when the file has warnings.
- **Failed is red**, and says where it stopped.

### Bars split by the real work

![The four steps on the bar](../img/v2/GuideBar.png){ .au }

Progress bars are split into pieces sized by their real share of the work, measured on real episodes: extraction is about 3% of the time, repeated frames 2%, the upscale 94%, assembly 1%. A bar drawn to those shares would make the three short steps almost invisible, so on the bar they get a little more room (5%, 3% and 2%), taken from the upscale's 90%, and the fill is mapped so the pace stays even across the whole bar.

### Times that hold still

A time left that jumps every second is a time nobody trusts. The time left of a file comes from how long its finished chunks really took, and the queue's finish time moves only when the estimate really changes, at most once a minute. This is as much a design decision as a technical one.

## Rules fixed along the way

Some rules only appeared while reviewing real screens, and then applied everywhere:

- Texts side by side on one line share the same baseline.
- A page's intro runs on two lines of similar length, the second slightly longer.
- Never name a colour in a text ("the white mark"): it changes between light and dark.
- Always the full file name with its extension, never a shortened one.
- Clip times are a range: 05:28 – 05:38.
- **Next:** buttons have a trailing arrow; **Back** stays plain.
- Inside alerts every icon is an outline; small icons inside text are filled.
- English buttons in title case, Italian in sentence case, as Apple does.
- Long lists end with a fade, so it's clear there's more.
- Estimates read "~ 34m", with a space after the tilde.
- Warnings use the filled yellow triangle, errors the filled red octagon, always with the "!" drawn in.
- Small graphic pieces (an icon and a value, a line) rather than empty space, and never walls of text.

## Words

The wording went through the same reviews as the pixels. Two examples:

- A finished file you redo with the same model would overwrite its video. The first draft offered "Keep It as It Is"; it became **Don't Redo**, which says what happens, and the question moved into the note, in bold: "Are you sure you want to overwrite it?".
- Each Settings row shows its default under its description ("Default: 18"), so nobody has to remember what it was.

## What's next

2.0 is dark only. The light theme was designed alongside the dark one in the first boards, and comes back once the dark one has settled. The pictures in this guide will follow the theme of the page when it does.

[Next: How a job works inside →](how-it-works.md)
