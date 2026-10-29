#!/usr/bin/env bash
# ==========================================================================
#  tools/build_native.sh - builds the native AnimeUp 2.0 app (Release)
#
#    tools/build_native.sh [output_dir]     ->  <output_dir>/AnimeUp.app + .zip
#
#  The app embeds the engine (the Python program, files tracked by git) in
#  Contents/Resources/AnimeUp; Python itself and the video tools are
#  downloaded on the first launch into ~/Library/Application Support/AnimeUp 2.
#  Ad-hoc signed (no Developer ID). Needs Xcode 26 or later.
# ==========================================================================
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-$REPO/dist/native}" && cd "${1:-$REPO/dist/native}" && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
xcodebuild -project "$REPO/macos/Native/AnimeUp.xcodeproj" -scheme AnimeUp -configuration Release \
  -derivedDataPath "$REPO/build/xcode-release" build -quiet
APP="$REPO/build/xcode-release/Build/Products/Release/AnimeUp.app"
[[ -x "$APP/Contents/Resources/AnimeUp/animeup" ]] || { echo "error: engine not embedded" >&2; exit 1; }
rm -rf "$OUT/AnimeUp.app"
ditto "$APP" "$OUT/AnimeUp.app"
codesign --force --deep --sign - "$OUT/AnimeUp.app"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$OUT/AnimeUp.app/Contents/Info.plist")"
find "$OUT/AnimeUp.app" \( -name '._*' -o -name .DS_Store \) -delete
(cd "$OUT" && rm -f "AnimeUp-v$VERSION-macos-app.zip" && ditto -c -k --norsrc --noextattr --noacl --keepParent AnimeUp.app "AnimeUp-v$VERSION-macos-app.zip")
echo "built $OUT/AnimeUp.app and $OUT/AnimeUp-v$VERSION-macos-app.zip"
