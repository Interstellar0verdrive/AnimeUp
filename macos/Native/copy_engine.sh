#!/usr/bin/env bash
# Copies the engine (the Python program) into the app bundle:
# Contents/Resources/AnimeUp/ gets the files tracked by git, minus tests,
# docs, design, CI, the macOS sources and the data folders.
# Python itself is not bundled: the launcher downloads it with uv on the
# first launch, into the state folder.
#
# Debug builds skip this: the scheme sets ANIMEUP_CODE to the worktree, so a
# Python change needs no rebuild. EMBED_ENGINE=YES forces the copy.
set -euo pipefail

if [[ "${CONFIGURATION:-Debug}" == "Debug" && "${EMBED_ENGINE:-NO}" != "YES" ]]; then
  echo "Debug: engine not embedded (runs from \$ANIMEUP_CODE)"
  exit 0
fi

REPO="$(cd "${SRCROOT}/../.." && pwd)"
DEST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}/AnimeUp"
rm -rf "$DEST"
mkdir -p "$DEST"
git -C "$REPO" ls-files -z | while IFS= read -r -d '' f; do
  case "$f" in
    tests/*|docs/*|design/*|.github/*|macos/*|tools/*|overrides/*) continue ;;
    INPUT/*|OUTPUT/*|bin/*) continue ;;
    .gitignore|.gitattributes|mkdocs.yml|requirements-docs.txt) continue ;;
  esac
  [[ -e "$REPO/$f" ]] || continue
  printf '%s\0' "$f"
done | (cd "$REPO" && tar --null -T - -cf -) | tar -xf - -C "$DEST"
[[ -x "$DEST/animeup" ]] || { echo "error: launcher missing from the bundle" >&2; exit 1; }
echo "engine copied to $DEST"
