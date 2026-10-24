#!/usr/bin/env bash
# ==========================================================================
#  tools/build_app.sh - builds AnimeUp.app
#
#    tools/build_app.sh <output_dir>        ->  <output_dir>/AnimeUp.app
#
#  The bundle:
#    Contents/MacOS/AnimeUp          the Swift shell (macos/AnimeUp/*.swift)
#    Contents/Resources/AnimeUp/     the program: the files tracked by git,
#                                    minus tests, docs, design, CI and the
#                                    data folders (no bin/, no .venv)
#    Contents/Resources/Assets.car + AnimeUp.icns, from the icon in macos/icon/
#    Contents/Info.plist             version from pyproject.toml
#
#  Unsigned for distribution (no Apple Developer account): only an ad-hoc
#  signature, so users approve it once in System Settings > Privacy &
#  Security > Open Anyway.
#
#  Needs: Command Line Tools (swiftc, codesign, sips, iconutil, plutil).
# ==========================================================================
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output_dir>" >&2
  exit 2
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$(mkdir -p "$1" && cd "$1" && pwd)"
APP="$OUT_DIR/AnimeUp.app"
BUNDLE_ID="io.github.interstellar0verdrive.animeup"

for tool in swiftc codesign sips iconutil plutil git; do
  command -v "$tool" >/dev/null || { echo "ERROR: '$tool' not found (install the Command Line Tools: xcode-select --install)" >&2; exit 1; }
done

# --- version, from [project] in pyproject.toml ---
VERSION="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$REPO/pyproject.toml" | head -n 1)"
[[ -n "$VERSION" ]] || { echo "ERROR: no version in pyproject.toml" >&2; exit 1; }
echo "AnimeUp $VERSION -> $APP"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/AnimeUp"

# --- 1. the Swift shell ---
echo "  compiling the app shell..."
swiftc -O -swift-version 5 -target arm64-apple-macos13.0 \
  -framework AppKit -framework WebKit \
  "$REPO"/macos/AnimeUp/*.swift \
  -o "$APP/Contents/MacOS/AnimeUp"

# --- 2. the program ---
# Files tracked by git, taken from the working tree (so a build reflects the
# checkout it's run from). Untracked files never get in: bin/, .venv, _WIP/,
# registri/... Tracked but not needed at run time: left out.
echo "  copying the program..."
if [[ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]]; then
  echo "  note: the working tree has uncommitted changes; they are included." >&2
fi
git -C "$REPO" ls-files -z | while IFS= read -r -d '' f; do
  case "$f" in
    tests/*|docs/*|design/*|.github/*|macos/*|tools/*) continue ;;
    INPUT/*|OUTPUT/*|JOBS/*|registri/*|anteprime/*|bin/*) continue ;;
    .gitignore|.gitattributes|"Avvia AnimeUp.command") continue ;;
  esac
  [[ -e "$REPO/$f" ]] || continue          # deleted in the working tree
  printf '%s\0' "$f"
done | (cd "$REPO" && tar --null -T - -cf -) | tar -xf - -C "$APP/Contents/Resources/AnimeUp"
[[ -x "$APP/Contents/Resources/AnimeUp/animeup" ]] || { echo "ERROR: launcher missing from the bundle" >&2; exit 1; }

# --- 3. the icon ---
# The two masters (1024 px, transparent corners) become an Icon Composer icon
# (macos/icon/icon.json: the light layer by default, the dark one for the dark
# appearance). Compiled by Xcode's actool into Assets.car, macOS itself picks
# the variant from the user's icon style (System Settings → Appearance), in
# Finder, Launchpad and the Dock alike, and draws it on the system icon grid.
# actool needs Xcode 26 or later; without it (e.g. on CI) the build falls
# back to a classic .icns made from the light master.
echo "  building the icon..."
ICON_SRC="$WORK/AnimeUp.icon"
mkdir -p "$ICON_SRC/Assets"
cp "$REPO/macos/icon/icon.json" "$ICON_SRC/icon.json"
cp "$REPO/macos/icon/AnimeUp-Light-1024.png" "$REPO/macos/icon/AnimeUp-Dark-1024.png" "$ICON_SRC/Assets/"
ACTOOL=""
for dev in "$(xcode-select -p 2>/dev/null)" /Applications/Xcode.app/Contents/Developer; do
  [[ -x "$dev/usr/bin/actool" ]] && { ACTOOL="$dev/usr/bin/actool"; break; }
done
ICON_NAME=""
mkdir -p "$WORK/icon-out"
if [[ -n "$ACTOOL" ]] && "$ACTOOL" "$ICON_SRC" --compile "$WORK/icon-out" --platform macosx \
     --minimum-deployment-target 13.0 --app-icon AnimeUp \
     --output-partial-info-plist "$WORK/icon-out/partial.plist" >/dev/null 2>&1 \
   && [[ -f "$WORK/icon-out/Assets.car" ]]; then
  cp "$WORK/icon-out/Assets.car" "$WORK/icon-out/AnimeUp.icns" "$APP/Contents/Resources/"
  ICON_NAME="AnimeUp"
  echo "    Icon Composer icon (light/dark) via $ACTOOL"
else
  ICONSET="$WORK/AnimeUp.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$REPO/macos/icon/AnimeUp-Light-1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$REPO/macos/icon/AnimeUp-Light-1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AnimeUp.icns"
  echo "    no actool from Xcode 26+: classic .icns (light only)"
fi

# --- 4. Info.plist ---
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>     <string>en</string>
  <key>CFBundleLocalizations</key>         <array><string>en</string><string>it</string></array>
  <key>CFBundleExecutable</key>            <string>AnimeUp</string>
  <key>CFBundleIconFile</key>              <string>AnimeUp</string>
$( [[ -n "$ICON_NAME" ]] && echo "  <key>CFBundleIconName</key>              <string>$ICON_NAME</string>" )
  <key>CFBundleIdentifier</key>            <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key> <string>6.0</string>
  <key>CFBundleName</key>                  <string>AnimeUp</string>
  <key>CFBundleDisplayName</key>           <string>AnimeUp</string>
  <key>CFBundlePackageType</key>           <string>APPL</string>
  <key>CFBundleShortVersionString</key>    <string>$VERSION</string>
  <key>CFBundleVersion</key>               <string>$VERSION</string>
  <key>LSMinimumSystemVersion</key>        <string>13.0</string>
  <key>LSArchitecturePriority</key>        <array><string>arm64</string></array>
  <key>LSApplicationCategoryType</key>     <string>public.app-category.video</string>
  <key>NSHighResolutionCapable</key>       <true/>
  <key>NSPrincipalClass</key>              <string>NSApplication</string>
  <key>NSSupportsAutomaticTermination</key> <false/>
  <key>NSSupportsSuddenTermination</key>   <false/>
  <key>NSHumanReadableCopyright</key>      <string>MIT License</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>     <true/>
    <key>NSExceptionDomains</key>
    <dict>
      <key>127.0.0.1</key>
      <dict><key>NSExceptionAllowsInsecureHTTPLoads</key> <true/></dict>
      <key>localhost</key>
      <dict><key>NSExceptionAllowsInsecureHTTPLoads</key> <true/></dict>
    </dict>
  </dict>
</dict>
</plist>
EOF
plutil -lint -s "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# --- 5. ad-hoc signature ---
echo "  signing (ad hoc)..."
xattr -cr "$APP"
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"

echo
echo "Built: $APP"
echo "Size:  $(du -sh "$APP" | cut -f1)"
