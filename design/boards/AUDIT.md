# Hand-written colours: boards and app (light theme audit, Nov 2026)

## Boards (Native screens)

Every rule, with its reason, is in `RULES` in `make_light.py`; run
`make_light.py audit <dir>` on the light twins to list what is left. In short:

| Kept as it is | Why |
|---|---|
| traffic lights `#FF5F57 #FEBC2E #28C840` | system colours, same in light |
| `#000` behind videos, masks | a picture is black behind; masks only use alpha |
| white on the red button | 5.04 : 1 on `#CD3725`, both themes |
| captions, handle and key caps on a video frame | they sit on the picture, not on the window |
| slider knob `#fff` | white in both themes, as in macOS |
| Dock badge `#FF3B30`, progress over the Dock icon | drawn on the icon, not the window |

| Mapped | Light value |
|---|---|
| accent glow `rgba(42,201,222,…)` | `rgba(39,147,219,…)` (C1) |
| sheets `#22252A` | `#F3F4F6` (new AU.sheet light) |
| AnimeUp alerts `#26292E` | `#F6F7F9` (new AU.alert light) |
| menus `rgba(44,47,53,.97)`, `rgba(48,51,56,.96)` | `rgba(246,246,248,.97)` (as DSControlsLight) |
| scrims `rgba(0,0,0,.55/.35)` | `rgba(16,24,40,.22/.14)` |
| shadows `rgba(0,0,0,a)` | `rgba(16,24,40,a/2)` |
| white veils and hairlines `rgba(255,255,255,a)` | `rgba(0,0,0,a)` |
| captions on the desk `#c9d1e0` | `#3A3F46` (text-code) |
| notice button `.not` (ochre, dark ink) | white, `yellow-text` on a `yellow-line` border (6.69 : 1): it sits inside the yellow note |
| `--red-soft` (failed rows and cards) | `rgba(205,55,37,.10)`: at `.05` it read as grey |
| macOS chrome: menu bar, notification banner, open panel, wallpaper | their macOS light look |

## App (Swift)

| Where | What | Decision |
|---|---|---|
| `AnimeUpApp.swift:14,34`, `MainView.swift:21,24,28`, `CompareView.swift:747` | `.preferredColorScheme(.dark)` | replace with the Settings › General theme (System / Light / Dark) |
| `DebugSnapshot.swift:249,275,315,338,362` | `\.colorScheme, .dark` | follow the same theme, so snapshots can be taken in light |
| `Chrome.swift:81-82`, `Components.swift:544`, `EmptyStates.swift:464`, `CompareView.swift:697` | black shadows | a shadow token: black in dark, `rgb(16,24,40)` at half strength in light |
| `SettingsKit.swift:167` | segment shadow | `--seg-shadow` (`.4` dark, `.15` light) |
| `Components.swift:777` | selected chip `black .18` | a token (dark: black .18, light: black .08) |
| `SettingsKit.swift:39-41,207-209` | slider knob white + shadow | keep (white knob in both themes) |
| `Buttons.swift:115` | white on the red button | keep |
| `StartView.swift:260` | gradient mask | keep (alpha only) |
| `EmptyStates.swift:449-477`, `SplitPlayer.swift`, `CompareView.swift:377-379` | handle, captions and frames on a video | keep |
| `EmptyStates.swift:488-509` | sunset illustration | keep (a picture) |
| `AppModel+Run.swift:302-307` | progress drawn on the Dock icon | keep (the icon does not follow the window theme) |
| `Tokens.swift` `redSoft` | light `rgba(217,64,46,.05)` | `rgba(205,55,37,.10)`, as in the boards |
| `Buttons.swift:116` `.notice` | `onYellow` on `yellow` | light: surface fill, `yellowText`, `yellowLine` border |
| `Tokens.swift` `sheet`, `alert` | light "to be drawn" | `#F3F4F6`, `#F6F7F9` once the boards are approved |

## Contrast (light), `make_light.py contrast`

Text tokens on every light ground (bg, surface, raised, sheet, alert, the
tints over surface, green/yellow/red backgrounds): all ≥ 4.5 : 1. Lowest:
text-3 on red-tint 4.55, primary-text on red-tint 4.77. Buttons: white on
primary 4.97, on primary-hover 4.51, on primary-press 5.81; white on red 5.04,
on red-hover 4.61; on-yellow on yellow 9.02.

## Applied (12 Nov 2026)

- App: the forced dark appearance is gone; Settings › General › Appearance
  (System / Light / Dark) sets `NSApp.appearance`, read from `settings.json`
  before the window opens and applied again on every change. Debug snapshots
  follow it. New tokens: `AU.shadow` (black in dark, `rgb(16,24,40)` at half
  strength in light), `AU.segShadow`, `AU.chipOnAccent`, the `notice*` set;
  `AU.sheet` / `AU.alert` / `AU.redSoft` have their light values.
- Design file: page "Guide · light" with the light twins of the guide's boards
  (`make_light.py`, guide rules and `BOARD_FIX`), and light thumbnails of the
  screens in `gassets/scr2light`. Pictures exported by `export_light.py` and
  `export_rows.py`; `guide_light_md.py` gives the pages their theme switch.
- Left dark on purpose: the 1.6 frame of the renewal wipe (1.6 was shot in its
  dark theme), the design-system covers (already a dark and a light one), and
  pictures that only sit on a photo (example labels, cover overlay).
