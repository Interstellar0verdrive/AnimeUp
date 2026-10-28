# AnimeUp 2.0 — the native macOS app

The SwiftUI app that replaces the Streamlit interface. The engine is still the
Python program in `src/animeup`: the app starts it once as a sidecar
(`animeup serve`, JSON lines over stdin/stdout) and the heavy jobs (queue,
Compare tests, calibration) stay detached `animeup` command-line processes,
as in 1.6.

```
macos/Native/
  AnimeUp.xcodeproj      the app target (macOS 26, file-system synchronised folder)
  AnimeUp/               the app: windows, views, the model that talks to the engine
  AnimeUpKit/            local Swift package
    Sources/Models       Codable mirrors of the engine's replies, the localiser
    Sources/Engine       EngineClient: spawns and talks to `animeup serve`
    Sources/DesignSystem colour tokens, type styles, buttons, AnimeUp's own views
  copy_engine.sh         Release build phase: embeds the engine in the bundle
```

## Run it in Xcode

1. Open `macos/Native/AnimeUp.xcodeproj` (Xcode 26 or later).
2. Pick the **AnimeUp** scheme and run (⌘R).

The Debug scheme runs the engine straight from this checkout, so a change to
the Python code needs no rebuild: quit and run again. Its environment
variables (Product › Scheme › Edit Scheme › Run › Arguments):

| Variable | Debug value | What it does |
|---|---|---|
| `ANIMEUP_CODE` | `$(SRCROOT)/../..` | where the engine is (this checkout) |
| `ANIMEUP_STATO` | `~/Library/Application Support/AnimeUp-dev` | the state folder: Python, `bin/`, `records/` |
| `ANIMEUP_WORK` | `/Volumes/USB_1TB/AnimeUp-native-test/Jobs` | default folder for work files |

Without them, a Release build uses the engine inside the bundle and the state
folder `~/Library/Application Support/AnimeUp 2` (no migration from 1.6), with
work files in `~/Movies/AnimeUp Jobs`. Finished videos always go next to the
originals.

From the command line:

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project macos/Native/AnimeUp.xcodeproj -scheme AnimeUp \
  -configuration Debug -derivedDataPath build/xcode build
ANIMEUP_CODE=$PWD \
ANIMEUP_STATO="$HOME/Library/Application Support/AnimeUp-dev" \
ANIMEUP_WORK=/Volumes/USB_1TB/AnimeUp-native-test/Jobs \
  build/xcode/Build/Products/Debug/AnimeUp.app/Contents/MacOS/AnimeUp
```

## Dev state and test folders

- `~/Library/Application Support/AnimeUp-dev`: the dev app's state. It has its
  own copy of the video tools in `bin/`, the Python environment, the list of
  videos (`records/files.json`), settings, calibration (done on this Mac) and
  logs: `records/engine.log` (engine), `records/app.log` (app),
  `records/queue.log` (jobs).
- `/Volumes/USB_1TB/AnimeUp-native-test/videos`: a few short test videos
  (copies). Finished videos appear next to them.
- `/Volumes/USB_1TB/AnimeUp-native-test/Jobs`: work files and job logs.

## See the first-launch tools window

Point `ANIMEUP_STATO` at an empty folder, for example
`/Volumes/USB_1TB/AnimeUp-native-test/fresh-state` (delete it first). On the
first run the app downloads uv and Python, then the video tools, with the
tools window in front. Don't empty `AnimeUp-dev` itself unless you want to
download everything again there.

## Tests

```sh
./animeup test                                   # engine (Python)
cd macos/Native/AnimeUpKit && swift test         # Swift package
```

## Release zip

```sh
tools/build_native.sh            # -> dist/native/AnimeUp.app and AnimeUp-v2.0-native.zip
```

The engine (the files tracked by git) is copied into
`Contents/Resources/AnimeUp`; Python and the video tools are downloaded on the
first launch. The signature is ad hoc (no Developer ID yet).

## Snapshots without screen recording

Debug builds can render their own pages to PNG: set `ANIMEUP_SNAPSHOT=<prefix>`
plus one of `ANIMEUP_SNAPSHOT_SETTINGS=1`, `ANIMEUP_SNAPSHOT_SHEETS=1`,
`ANIMEUP_SNAPSHOT_COMPARE=<file name part>`, `ANIMEUP_SNAPSHOT_RUN=<file name
part>` (see `AnimeUp/DebugSnapshot.swift`). AppKit controls (switches, sliders,
menus, the video player) show as placeholders in these images.

## Known gaps

- Light appearance: the app is dark only for now.
- No Sparkle updates yet: Check for Updates only checks GitHub.
- The release uses the same bundle identifier as the 1.6 app.
- Compare: the player's split, hover and 1:1 haven't been checked by eye in the
  real window yet.
- Queue: no "Pause After This File", no Open Recent.
- Calibration: per-step times aren't shown in the checklist.
