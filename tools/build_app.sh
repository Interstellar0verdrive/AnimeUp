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
#    Contents/Resources/AnimeUp.icns (light) and AnimeUp-Dark.icns, built
#    from the masters in macos/icon/
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
# Two masters (1024 px, transparent corners): Light is the bundle icon that
# Finder and Launchpad show; Dark is swapped in on the Dock by the app itself
# when macOS is in dark mode (see macos/AnimeUp/DockIcon.swift).
echo "  building the icons..."
for variant in Light Dark; do
  master="$REPO/macos/icon/AnimeUp-$variant-1024.png"
  [[ -f "$master" ]] || { echo "ERROR: missing $master" >&2; exit 1; }
  ICONSET="$WORK/AnimeUp-$variant.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$master" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$master" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  name="AnimeUp"; [[ "$variant" == "Dark" ]] && name="AnimeUp-Dark"
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$name.icns"
done

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
