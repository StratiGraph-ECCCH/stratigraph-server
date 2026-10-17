# La pila di prova RustFS

RustFS al posto di MinIO, **accanto** alla pila di sviluppo e non al suo posto
(17 ottobre 2026). Serve ad avere i numeri prima della decisione; la pila di
sviluppo (`docker-compose.dev.yml`, progetto `em-dev`) resta com'è e può restare
accesa mentre questa gira.

## Accendere

Le credenziali sono di prova e stanno fuori dal repository, in un file
`KEY=valore` con quattro righe:

```
RUSTFS_ACCESS_KEY=…
RUSTFS_SECRET_KEY=…
RUSTFS_BUCKET=em-assets
PROVA_PG_PASSWORD=…
```

Quello della prova del 17 ottobre è
`~/Documents/GitHub/_datasets/_rustfs-2026-10-17/.env.rustfs`. Senza il file la
pila non parte: niente default `rustfsadmin`.

```sh
cd dev-stack
docker-compose -p rustfs-prova \
  --env-file ../../_datasets/_rustfs-2026-10-17/.env.rustfs \
  -f docker-compose.rustfs.yml up -d
```

Con `--profile confronto` parte anche una MinIO (la **stessa** immagine pinnata
della pila di sviluppo, con un volume suo) sulla 9200, per i tempi.

| cosa | dove (solo loopback) |
|---|---|
| em-server, puntato a RustFS | `http://localhost:8100` (`/v1`, `/health`) |
| RustFS S3 | `http://localhost:9100` |
| console di RustFS | `http://localhost:9101/rustfs/console/` |
| Cantaloupe, dallo stesso bucket | `http://localhost:8183/iiif/3` |
| Postgres dei documenti | `127.0.0.1:5434` (per `pytest`, vedi sotto) |
| MinIO di confronto (`--profile confronto`) | `http://localhost:9200` |

Keycloak **non** c'è: si usa quello della pila di sviluppo in sola lettura
(l'em-server di prova ne scarica solo le chiavi pubbliche da
`host.docker.internal:8085`). I token sono quelli di `./token.sh`.

## Spegnere

```sh
docker-compose -p rustfs-prova --env-file … -f docker-compose.rustfs.yml --profile confronto down
```

`down` senza `-v`: **i volumi restano** (`rustfs-prova_rustfs_data`,
`rustfs-prova_em_data`, `rustfs-prova_em_documents_data`,
`rustfs-prova_minio_confronto_data`), e un nuovo `up` ritrova tutto. Per
buttarli, `down -v`, e solo quando la prova è finita.

## Gli smoke e i test contro questa pila

```sh
# gli smoke: la base è la porta diretta, non Caddy
python3 smoke_asset_range.py --base http://localhost:8100/v1
EM_SERVER_PORT=8100 CANTALOUPE_PORT=8183 python3 smoke_iiif.py
EM_SERVER_PORT=8100 MINIO_API_PORT=9100 MINIO_ROOT_USER=… MINIO_ROOT_PASSWORD=… python3 smoke.py

# pytest: il Postgres e lo S3 di QUESTA pila, non di quella di sviluppo
EM_TEST_PG_PORT=5434 EM_TEST_PG_PASSWORD=… \
MINIO_ENDPOINT=http://localhost:9100 MINIO_ROOT_USER=… MINIO_ROOT_PASSWORD=… \
  python -m pytest
```

`smoke_room_durable.py` e `smoke_corpus_resident.py` vogliono le stanze di seme
(`mostra`, `basilica-demo`); `seed_rooms.py` conosce solo
`https://em.localhost:8443`, quindi sulla pila di prova va lanciato con la base
spostata (lo script della prova è `_datasets/_rustfs-2026-10-17/seed-prova.py`).

## Cosa cambia rispetto a MinIO

- **L'immagine:** `rustfs/rustfs:1.0.2` (Apache-2.0), pinnata con il digest.
  Gira come utente 10001, come l'em-server.
- **Le variabili:** `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` al posto di
  `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`; `RUSTFS_VOLUMES`, `RUSTFS_ADDRESS`,
  `RUSTFS_CONSOLE_ADDRESS`, `RUSTFS_CONSOLE_ENABLE`.
- **La salute:** `GET /health` (e risponde anche al `/minio/health/live` che
  sonda la mappa del nodo). Il healthcheck usa il `curl` dell'immagine.
- **Il bucket:** creato senza `mc`, con una `PUT /<bucket>` firmata SigV4 dal
  `curl` dell'immagine di RustFS: CreateBucket di S3, nient'altro.
- **La console:** sotto `/rustfs/console/`, sulla porta 9001 del container.
- **Per l'em-server non cambia niente:** stesso client (`minio-py`), stesse
  operazioni S3. Le variabili sono `EM_ASSET_S3_*`, il nome neutro che il
  server legge per primo (ed è quello del ruolo Ansible); i vecchi `MINIO_*`
  funzionano ancora, con un avviso al primo uso. `/health` dice
  `s3 (<endpoint>, bucket <nome>)`, perché il nodo non sa quale S3 risponde.
