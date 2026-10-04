#!/usr/bin/env bash
# bump-s3dgraphy.sh — allinea StratiGraph Server a una nuova s3dgraphy pubblicata su PyPI.
# Aggiorna il pin ESATTO in pyproject.toml (il posto solo, tiene gli extra
# [geo,rdf] e cambia solo il numero) e le sue due COPIE — il default di
# `ARG S3DGRAPHY_VERSION=` nel Dockerfile e l'anchor `x-s3dgraphy-version` del
# compose del dev-stack —, mostra il diff, e — con --build — ricostruisce
# e riavvia StratiGraph Server nel dev-stack (il bump della versione fa da cache-bust del layer).
# Quando sposta il pin conta anche un'iterazione del server stesso (devN → devN+1,
# una volta per commit): è il numero che `/v1/health` dice in `version`.
#
#   ./bump-s3dgraphy.sh 1.6.0.dev15            # imposta questa versione
#   ./bump-s3dgraphy.sh --latest              # prende l'ultima da PyPI (pre comprese)
#   ./bump-s3dgraphy.sh 1.6.0.dev15 --build   # bumpa E ricostruisce+riavvia StratiGraph Server
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"                          # stratigraph-server (dove stanno pyproject.toml + Dockerfile)

BUILD="no"; VER=""
for a in "$@"; do
  case "$a" in
    --build)  BUILD="yes" ;;
    --latest) VER="__latest__" ;;
    -* )      echo "flag sconosciuto: $a"; exit 2 ;;
    * )       VER="$a" ;;
  esac
done
[ -n "$VER" ] || { echo "uso: ./bump-s3dgraphy.sh <versione|--latest> [--build]"; exit 2; }

# --latest: chiede a PyPI l'ultima, pre-release comprese (best-effort; se fallisce, passala a mano)
if [ "$VER" = "__latest__" ]; then
  echo "▶ cerco l'ultima s3dgraphy su PyPI (pre comprese)…"
  VER=$(pip index versions --pre s3dgraphy 2>/dev/null \
        | sed -n 's/.*[Aa]vailable versions: *//p' | tr ',' '\n' | head -1 | tr -d ' ')
  [ -n "$VER" ] || { echo "✗ non riesco a leggere la versione da PyPI; passala a mano."; exit 1; }
  echo "  ultima = $VER"
fi

# forma plausibile (es. 1.6.0 o 1.6.0.dev15)
echo "$VER" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(\.dev[0-9]+)?$' \
  || { echo "✗ versione sospetta: '$VER' (attesa tipo 1.6.0.dev15)"; exit 1; }

# sostituisci OVUNQUE compaia il pin: tiene s3dgraphy[...]== , cambia solo la versione.
# Le righe di commento che nominano una vecchia dev NON hanno '==' e restano intatte.
for f in pyproject.toml Dockerfile dev-stack/docker-compose.dev.yml; do
  [ -f "$f" ] || { echo "✗ $f non trovato — sei in stratigraph-server?"; exit 1; }
done
# LA VERSIONE DEL SERVER SEGUE I RELEASE (W3, 4 ottobre 2026). `/v1/health`
# diceva `"version": "1.6.0.dev1"` da settembre, mentre il pin andava da dev17 a
# dev35: un numero che nessuno muoveva. Ora, quando QUESTO script sposta il pin,
# il server conta un'iterazione in più — `1.6.0.devN` → `devN+1` in
# `app/__init__.py` e nel `version` di pyproject.toml, le due righe che
# `tests/test_version.py` tiene uguali. Una sola volta per commit: se la
# versione nel working tree è già diversa da quella in HEAD, è già stata
# contata. Se s3Dgraphy cambia lingua (1.6 → 1.7), il server riparte da
# `<lingua>.0.dev1`: le prime due cifre sono quelle della lingua.
OLD_PIN=$(sed -nE 's/.*"s3dgraphy(\[[a-z,]*\])?==([^"]+)".*/\2/p' pyproject.toml | head -1)
OWN=""
[ -f app/__init__.py ] && OWN=$(sed -nE 's/^__version__ = "([^"]+)"/\1/p' app/__init__.py)
OWN_HEAD=$(git --no-pager show HEAD:app/__init__.py 2>/dev/null | sed -nE 's/^__version__ = "([^"]+)"/\1/p' || true)
NEXT=""
if [ "$OLD_PIN" != "$VER" ] && [ -n "$OWN" ] && { [ -z "$OWN_HEAD" ] || [ "$OWN" = "$OWN_HEAD" ]; }; then
  LANG_V=$(echo "$VER" | cut -d. -f1-2); LANG_OWN=$(echo "$OWN" | cut -d. -f1-2)
  if [ "$LANG_V" != "$LANG_OWN" ]; then
    NEXT="$LANG_V.0.dev1"
  elif echo "$OWN" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]+$'; then
    NEXT="${OWN%.dev*}.dev$(( ${OWN##*.dev} + 1 ))"
  else
    echo "⚠ la versione del server ($OWN) non è una .devN: contala a mano in app/__init__.py e pyproject.toml"
  fi
fi

sed -E -i.bak "s/(s3dgraphy(\[[a-z,]*\])?==)[0-9][A-Za-z0-9.]*/\1${VER}/g" pyproject.toml
if [ -n "$NEXT" ]; then
  sed -E -i.bak "s/^version = \"[^\"]*\"/version = \"${NEXT}\"/" pyproject.toml
  sed -E -i.bak "s/^__version__ = \"[^\"]*\"/__version__ = \"${NEXT}\"/" app/__init__.py
  rm -f app/__init__.py.bak
  echo "▶ il server conta un'iterazione: $OWN → $NEXT (app/__init__.py + pyproject.toml)"
fi
# le due copie: il default dell'ARG e l'anchor del compose
sed -E -i.bak "s/^(ARG S3DGRAPHY_VERSION=).*/\1${VER}/" Dockerfile
sed -E -i.bak "s/^(x-s3dgraphy-version: &s3dgraphy_version \"\\\$\{S3DGRAPHY_VERSION:-)[^}]*(\}\")/\1${VER}\2/" \
  dev-stack/docker-compose.dev.yml
rm -f pyproject.toml.bak Dockerfile.bak dev-stack/docker-compose.dev.yml.bak

echo "▶ pin aggiornato a s3dgraphy[geo,rdf]==$VER. Diff:"
# --no-pager (dev29, C1): dentro ./em.sh release un pager aperto qui fermava
# il release su «:» finché non si premeva q
git --no-pager diff -- pyproject.toml Dockerfile dev-stack/docker-compose.dev.yml app/__init__.py 2>/dev/null || echo "  (git non disponibile: controlla i file a mano)"

# la guardia che tiene le tre righe una: se un sed non ha preso, lo dice qui
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_s3dgraphy_pin.py -k "not what_is_installed" \
    || { echo "✗ le tre righe non coincidono: guarda il diff qui sopra"; exit 1; }
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_version.py -k "pyproject_and_the_package_agree" \
    || { echo "✗ app/__init__.py e pyproject.toml non dicono la stessa versione del server"; exit 1; }
fi

if [ "$BUILD" = "yes" ]; then
  # CON `--env-file .env.dev`, come `fcn-up.sh`. Il 2 ottobre 2026 questa riga
  # non lo diceva: `up -d` ha RICREATO il server con l'ambiente della shell, cioè
  # senza le chiavi di MinIO, e il server è andato in crash a ripetizione. Senza
  # `.env.dev` ci si ferma PRIMA di toccare il container, col messaggio di
  # `fcn-up.sh` (`sg_need_env_dev`, in `dev-stack/platform.sh`).
  ( cd dev-stack
    . ./platform.sh
    sg_need_env_dev || exit 1
    sg_compose_array || exit 1
    COMPOSE+=(--env-file .env.dev -f docker-compose.dev.yml)
    echo "▶ ricostruisco StratiGraph Server nel dev-stack…"
    "${COMPOSE[@]}" build stratigraph-server \
      && "${COMPOSE[@]}" up -d stratigraph-server ) \
    || { echo "✗ StratiGraph Server NON ricostruito: il pin è aggiornato, il container no."; exit 1; }
  echo "✔ StratiGraph Server ricostruito e riavviato con s3dgraphy $VER."
else
  echo "  Per applicarlo:  ./bump-s3dgraphy.sh $VER --build"
  echo "  (o:  cd dev-stack && docker-compose --env-file .env.dev -f docker-compose.dev.yml build stratigraph-server && … up -d stratigraph-server)"
fi
