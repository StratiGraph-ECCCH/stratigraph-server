#!/usr/bin/env bash
# note-di-rilascio — le note di una versione, dai commit dall'ultimo tag
# (E.D., 31 ott 2026: note di rilascio a ogni versione; fatto il 6 nov).
#
#   ./scripts/note-di-rilascio.sh 1.6.0-dev.57 ghcr.io/org/immagine sha256:… 1.6.0.dev93
#
# Stampa Markdown su stdout, in inglese perché le leggono i partner. La chiama il workflow `immagine` dopo il tag e
# la passa a `gh release create`; a mano serve a vedere cosa uscirà.
#
# Cosa c'è: l'immagine con il suo digest (il nome che non si muove), la
# s3Dgraphy dentro, e i commit dall'ultima versione. I commit della catena
# automatica (allineamenti a una nuova s3Dgraphy) non si elencano uno per uno:
# si contano e si dice da quale versione a quale.
set -euo pipefail
versione="${1:?la versione, p. es. 1.6.0-dev.57}"
immagine="${2:-}"
digest="${3:-}"
s3d="${4:-}"
tag="v${versione}"

# l'ultimo tag di versione PRIMA di questo, fra quelli raggiungibili da qui
prima=$(git tag --merged HEAD --list 'v*' --sort=-v:refname | grep -vxF "$tag" | head -1 || true)
range="${prima:+${prima}..}HEAD"
repo=$(basename "$(git rev-parse --show-toplevel)")

catena='^(Pin s3dgraphy|Vendor the schede|build: dev release|chore\(deps\))'
tutti=$(git log --no-merges --format='%h%x09%s' "$range")
lavoro=$(printf '%s\n' "$tutti" | awk -F'\t' -v re="$catena" 'NF && $2 !~ re')
auto=$(printf '%s\n' "$tutti" | awk -F'\t' -v re="$catena" 'NF && $2 ~ re')

echo "## ${repo} ${versione}"
echo
if [ -n "$immagine" ]; then
  echo "- Image: \`${immagine}:${versione}\`"
  [ -n "$digest" ] && echo "- Digest: \`${digest}\` — the name to cite in a reproducible deployment"
fi
[ -n "$s3d" ] && echo "- s3Dgraphy: ${s3d}"
echo
if [ -n "$prima" ]; then
  echo "### What changed since ${prima}"
else
  echo "### What it contains"
fi
echo
if [ -n "$lavoro" ]; then
  printf '%s\n' "$lavoro" | while IFS=$'\t' read -r h s; do echo "- ${s} (\`${h}\`)"; done
else
  echo "- No change beyond the alignments below."
fi
if [ -n "$auto" ]; then
  n=$(printf '%s\n' "$auto" | grep -c .)
  da=$(printf '%s\n' "$auto" | tail -1 | grep -oE '1\.[0-9]+\.[0-9]+\.?(dev|rc)?[0-9]*' | head -1 || true)
  a=$(printf '%s\n' "$auto" | head -1 | grep -oE '1\.[0-9]+\.[0-9]+\.?(dev|rc)?[0-9]*' | head -1 || true)
  echo
  echo "### Automatic alignments"
  echo
  if [ -n "$da" ] && [ -n "$a" ] && [ "$da" != "$a" ]; then
    echo "- ${n} commit(s) from the release chain: s3Dgraphy from ${da} to ${a}."
  else
    echo "- ${n} commit(s) from the release chain${a:+ (s3Dgraphy ${a})}."
  fi
fi
