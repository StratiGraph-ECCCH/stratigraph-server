#!/usr/bin/env bash
# verifica-contenuto · l'etichetta dice il vero su cosa c'è dentro l'immagine
#
#   ./scripts/verifica-contenuto.sh stratigraph-server:v1.2.3
#
# ── PERCHÉ DUE FONTI E NON UNA ───────────────────────────────────────────────
#
# L'etichetta `org.stratigraph.s3dgraphy.version` porta ciò che il build ha
# CHIESTO (l'argomento `S3DGRAPHY_VERSION`); il file `/licenses/s3dgraphy-version`
# porta ciò che pip ha DATO, scritto da pip stesso nel momento in cui lo
# decideva. Una sola delle due non avrebbe niente contro cui essere sbagliata:
# un'etichetta scritta a mano è una promessa, e una promessa che nessuno
# confronta con la merce è una decorazione.
#
# Il giorno in cui `S3DGRAPHY_VERSION` diventasse un range — o in cui qualcuno
# mettesse l'etichetta «a occhio» — le due smetterebbero di coincidere e questo
# diventa rosso.
#
# Legge il file DALL'IMMAGINE, non dal Dockerfile: `docker run … cat`. È la
# stessa regola per cui la licenza si prova con un `cat` e non con il `COPY`.
#
# MUTAZIONE: costruisci con un `S3DGRAPHY_VERSION` diverso da quello che pip
# installerebbe (per esempio mettendo l'etichetta a mano) → rosso.
set -euo pipefail

IMG="${1:-}"
[ -n "$IMG" ] || { echo "uso: $0 <immagine>" >&2; exit 2; }

echo "▶ contenuto dichiarato di $IMG"

etichetta="$(docker image inspect \
  --format '{{index .Config.Labels "org.stratigraph.s3dgraphy.version"}}' "$IMG" 2>/dev/null || true)"
if [ -z "$etichetta" ] || [ "$etichetta" = "<no value>" ]; then
  echo "  ✗ l'immagine non porta org.stratigraph.s3dgraphy.version: chi la"
  echo "    specchia non ha modo di sapere quale libreria c'è dentro."
  exit 1
fi
echo "  · etichetta (ciò che il build ha CHIESTO): $etichetta"

dentro="$(docker run --rm --entrypoint sh "$IMG" -c 'cat /licenses/s3dgraphy-version' 2>/dev/null | tr -d '[:space:]' || true)"
if [ -z "$dentro" ]; then
  echo "  ✗ /licenses/s3dgraphy-version non c'è o è vuoto: l'immagine non sa"
  echo "    dire cosa contiene, e l'etichetta resta una promessa non verificata."
  exit 1
fi
echo "  · dentro    (ciò che pip ha DATO):        $dentro"

if [ "$etichetta" != "$dentro" ]; then
  echo "  ✗ NON COINCIDONO. L'etichetta promette $etichetta e l'immagine"
  echo "    contiene $dentro: chi si fida dell'etichetta si fida di una"
  echo "    versione che non è lì."
  exit 1
fi
echo "  ✓ l'etichetta e il contenuto dicono la stessa cosa"

#: e il verbale completo, che è ciò che rende confrontabili due build dello
#: stesso tag: le altre dipendenze sono chieste con dei RANGE, quindi due
#: build possono differire legittimamente — ma solo in modo VISIBILE.
n="$(docker run --rm --entrypoint sh "$IMG" -c 'wc -l < /licenses/installed.txt' 2>/dev/null | tr -d '[:space:]' || echo 0)"
[ "${n:-0}" -gt 10 ] || { echo "  ✗ /licenses/installed.txt ha $n righe: non è un verbale"; exit 1; }
echo "  ✓ /licenses/installed.txt elenca $n pacchetti con la versione risolta"
