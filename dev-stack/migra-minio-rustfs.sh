#!/usr/bin/env bash
# migra-minio-rustfs — porta gli asset dalla vecchia MinIO a RustFS. UNA volta.
#
#   ./migra-minio-rustfs.sh          # dopo il pull che ha tolto MinIO dal compose
#
# Cosa fa, in ordine, e niente di più:
#
#   1. `.env.dev`: se mancano RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY / RUSTFS_BUCKET
#      li AGGIUNGE in fondo con i valori di MINIO_ROOT_USER / MINIO_ROOT_PASSWORD
#      / MINIO_BUCKET (stesse chiavi, nomi nuovi; i valori non si stampano). Le
#      righe MINIO_* restano: il compose non le legge più, e toglierle è tuo.
#   2. ricostruisce l'immagine del server (ora parla S3 con boto3) e ferma i tre
#      servizi che scrivono nel bucket, così la copia non insegue un bersaglio;
#   3. la SORGENTE: il container `em-dev-minio` se c'è ancora; se no una MinIO
#      temporanea (`em-dev-minio-migra`, la stessa immagine pinnata di prima)
#      sopra il volume `em-dev_minio_data`, che si toglie alla fine;
#   4. accende `rustfs` + `rustfs-init` su porte di passaggio (9010/9011), perché
#      la 9000/9001 dell'host può essere ancora della MinIO;
#   5. copia e VERIFICA (`migra_minio_rustfs.py`: conteggi, byte, sha256 di un
#      campione); se qualcosa non torna esce con 1 e non tocca altro;
#   6. toglie i container della MinIO (il VOLUME resta: è la copia di sicurezza).
#      E quello di Caddy, che `fcn-up.sh` ricrea con il `Caddyfile.dev` nuovo.
#
# Poi: `./fcn-up.sh`, come sempre — rimette RustFS sulle porte di sempre.
# Idempotente: un secondo giro salta ciò che è già copiato.
# Il volume `em-dev_minio_data` NON si cancella qui; quando la pila su RustFS ti
# basta, `docker volume rm em-dev_minio_data` è una decisione tua.
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"                     # stratigraph-server/dev-stack
. ./platform.sh
sg_need_env_dev || exit 1
sg_compose_array || exit 1

PROGETTO=em-dev
RETE="${PROGETTO}_default"
VOLUME_MINIO="${PROGETTO}_minio_data"
MINIO_IMG='quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z'

valore() { sed -n "s/^$1=//p" .env.dev | tail -1; }

# ── 1 · le chiavi, con i nomi nuovi ─────────────────────────────────────────
aggiunte=0
for coppia in RUSTFS_ACCESS_KEY:MINIO_ROOT_USER RUSTFS_SECRET_KEY:MINIO_ROOT_PASSWORD \
              RUSTFS_BUCKET:MINIO_BUCKET; do
  nuovo="${coppia%%:*}"; vecchio="${coppia##*:}"
  [ -n "$(valore "$nuovo")" ] && continue
  v="$(valore "$vecchio")"
  if [ -z "$v" ]; then
    echo "✖ .env.dev non ha né $nuovo né $vecchio: scrivilo a mano (vedi .env.dev.example)." >&2
    exit 1
  fi
  [ "$aggiunte" = 0 ] && printf '\n# --- object store: RustFS (aggiunte da migra-minio-rustfs.sh) ---\n' >> .env.dev
  printf '%s=%s\n' "$nuovo" "$v" >> .env.dev
  aggiunte=$((aggiunte + 1))
done
echo "▶ .env.dev: $aggiunte chiavi RUSTFS_* aggiunte (i valori sono quelli MINIO_* di prima)"

SRC_ACCESS="$(valore MINIO_ROOT_USER)"; SRC_SECRET="$(valore MINIO_ROOT_PASSWORD)"
SRC_BUCKET="$(valore MINIO_BUCKET)"; SRC_BUCKET="${SRC_BUCKET:-$(valore RUSTFS_BUCKET)}"
if [ -z "$SRC_ACCESS" ] || [ -z "$SRC_SECRET" ]; then
  echo "✖ servono ancora MINIO_ROOT_USER e MINIO_ROOT_PASSWORD in .env.dev per LEGGERE" >&2
  echo "  la vecchia MinIO. Rimettile (o lancia questo script prima di toglierle)." >&2
  exit 1
fi

COMPOSE+=(--env-file .env.dev -f docker-compose.dev.yml)

# ── 2 · l'immagine nuova, e il bucket fermo ─────────────────────────────────
echo "▶ ricostruisco l'immagine del server (boto3)…"
"${COMPOSE[@]}" build stratigraph-server
echo "▶ fermo chi scrive nel bucket (server, catalogo, chatbot)…"
"${COMPOSE[@]}" stop stratigraph-server stratigraph-catalog stratigraph-chatbot >/dev/null 2>&1 || true

# ── 3 · la sorgente ─────────────────────────────────────────────────────────
TEMPORANEA=no
if docker inspect em-dev-minio >/dev/null 2>&1; then
  docker start em-dev-minio >/dev/null
  SRC_HOST=minio
  echo "▶ sorgente: il container em-dev-minio"
elif docker volume inspect "$VOLUME_MINIO" >/dev/null 2>&1; then
  docker rm -f em-dev-minio-migra >/dev/null 2>&1 || true
  docker run -d --name em-dev-minio-migra --network "$RETE" --network-alias minio-migra \
    -e MINIO_ROOT_USER="$SRC_ACCESS" -e MINIO_ROOT_PASSWORD="$SRC_SECRET" \
    -v "$VOLUME_MINIO":/data "$MINIO_IMG" server /data >/dev/null
  TEMPORANEA=yes
  SRC_HOST=minio-migra
  echo "▶ sorgente: una MinIO temporanea sul volume $VOLUME_MINIO"
else
  echo "✖ niente da migrare: né il container em-dev-minio né il volume $VOLUME_MINIO." >&2
  echo "  Se è una pila nuova, basta ./fcn-up.sh." >&2
  exit 1
fi
for _ in $(seq 1 30); do
  docker run --rm --network "$RETE" --entrypoint python stratigraph-server:dev -c \
    "import urllib.request,sys; urllib.request.urlopen('http://$SRC_HOST:9000/minio/health/ready', timeout=2)" \
    >/dev/null 2>&1 && break
  sleep 2
done

# ── 4 · RustFS, su porte di passaggio ───────────────────────────────────────
echo "▶ accendo rustfs + rustfs-init (porte di passaggio 9010/9011)…"
RUSTFS_API_PORT=9010 RUSTFS_CONSOLE_PORT=9011 "${COMPOSE[@]}" up -d rustfs rustfs-init
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' em-dev-rustfs 2>/dev/null)" = healthy ] && break
  sleep 2
done

# ── 5 · copia e verifica ────────────────────────────────────────────────────
echo "▶ copio e verifico…"
esito=0
docker run --rm -i --network "$RETE" --entrypoint python \
  -e MIGRA_SRC_HOST="$SRC_HOST" -e MIGRA_SRC_ACCESS="$SRC_ACCESS" \
  -e MIGRA_SRC_SECRET="$SRC_SECRET" -e MIGRA_SRC_BUCKET="$SRC_BUCKET" \
  -e RUSTFS_ACCESS_KEY="$(valore RUSTFS_ACCESS_KEY)" \
  -e RUSTFS_SECRET_KEY="$(valore RUSTFS_SECRET_KEY)" \
  -e RUSTFS_BUCKET="$(valore RUSTFS_BUCKET)" \
  stratigraph-server:dev - < migra_minio_rustfs.py || esito=$?

if [ "$esito" != 0 ]; then
  echo "✖ la copia non torna: NON tolgo niente. La MinIO e il suo volume sono come prima." >&2
  [ "$TEMPORANEA" = yes ] && docker rm -f em-dev-minio-migra >/dev/null 2>&1
  exit "$esito"
fi

# ── 6 · via i container di MinIO; il volume resta ───────────────────────────
docker rm -f em-dev-minio em-dev-minio-init em-dev-minio-migra >/dev/null 2>&1 || true
# …e Caddy, perché `fcn-up.sh` lo ricrea: `Caddyfile.dev` è montato come FILE, e
# un `git pull` che lo riscrive gli dà un inode nuovo che il container in piedi
# non vede (misurato il 18 ottobre: dopo `fcn-up.sh` serviva ancora
# `/assets/*` → `minio:9000`). Il volume `caddy_data`, cioè la CA, resta.
docker rm -f em-dev-caddy >/dev/null 2>&1 || true
echo "✔ fatto. I container di MinIO sono tolti; il volume $VOLUME_MINIO resta come copia."
echo "  Ora:  ./fcn-up.sh    (RustFS torna sulla 9000/9001)"
