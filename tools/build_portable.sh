#!/usr/bin/env bash
# ==========================================================================
#  tools/build_portable.sh - builds and tests the portable folder (no app)
#
#    tools/build_portable.sh [output_dir]  ->  <output_dir>/AnimeUp-vX-macos-arm64.zip
#
#  The folder is the engine as committed (git archive HEAD, so commit first)
#  plus the upscalers, their models and uv from bin/. FFmpeg is not bundled
#  (GPLv3): the first `./animeup setup` downloads the pinned build. The
#  guide's pictures are left out: the guide is online.
#
#  Then it tests the zip the way a user gets it: unzipped from scratch,
#  quarantined, with a bare PATH (no /usr/sbin, no Homebrew), running setup,
#  doctor and the test suite. Any failure stops the script with exit 1.
# ==========================================================================
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-$REPO/dist/portable}" && cd "${1:-$REPO/dist/portable}" && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml" | head -1)"
ZIP="AnimeUp-v$VERSION-macos-arm64.zip"

[[ -z "$(git -C "$REPO" status --porcelain -- src animeup pyproject.toml uv.lock)" ]] \
  || { echo "error: uncommitted engine changes; the zip is built from HEAD" >&2; exit 1; }
for f in uv realesrgan-ncnn-vulkan realcugan-ncnn-vulkan models models-nose models-pro models-se; do
  [[ -e "$REPO/bin/$f" ]] || { echo "error: bin/$f missing (run ./animeup setup)" >&2; exit 1; }
done

STAGE="$(mktemp -d)"; TEST="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$TEST"' EXIT
mkdir -p "$STAGE/AnimeUp/bin"
git -C "$REPO" archive HEAD | tar -x -C "$STAGE/AnimeUp" --exclude 'docs/guide/img' --exclude 'docs/images'
for f in uv realesrgan-ncnn-vulkan realcugan-ncnn-vulkan models models-nose models-pro models-se; do
  ditto "$REPO/bin/$f" "$STAGE/AnimeUp/bin/$f"
done
find "$STAGE" \( -name '._*' -o -name .DS_Store \) -delete
rm -f "$OUT/$ZIP"
(cd "$STAGE" && ditto -c -k --norsrc --noextattr --noacl --keepParent AnimeUp "$OUT/$ZIP")
echo "built $OUT/$ZIP ($(du -h "$OUT/$ZIP" | cut -f1))"

# --- the test, as a user would run it -------------------------------------
ditto -x -k "$OUT/$ZIP" "$TEST"
cd "$TEST/AnimeUp"
xattr -w -r com.apple.quarantine "0083;00000000;Safari;" . 2>/dev/null || true
bare() { env -i HOME="$HOME" PATH=/usr/bin:/bin "$@"; }
[[ "$(bare ./animeup version | tail -1)" == "AnimeUp $VERSION" ]] \
  || { echo "error: the folder doesn't say AnimeUp $VERSION" >&2; exit 1; }
bare ./animeup setup --yes > "$TEST/setup.log" 2>&1 || { tail -20 "$TEST/setup.log"; exit 1; }
bare ./animeup doctor > "$TEST/doctor.log" 2>&1 || { tail -20 "$TEST/doctor.log"; exit 1; }
bare ./animeup test > "$TEST/test.log" 2>&1 || { grep -E "FALLITO|passati" "$TEST/test.log"; exit 1; }
grep -E "passati" "$TEST/test.log"
echo "tested: setup, doctor and the suite pass from a fresh, quarantined copy with a bare PATH"
