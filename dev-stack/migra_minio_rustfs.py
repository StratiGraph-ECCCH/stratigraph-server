"""Copia il bucket della vecchia MinIO nel bucket di RustFS — UNA volta.

Lo lancia `migra-minio-rustfs.sh`, dentro l'immagine del server (che ha boto3),
sulla rete di compose `em-dev`: legge da `http://<MIGRA_SRC_HOST>:9000` e scrive
in `http://rustfs:9000`. Non lo si chiama a mano.

Dalla MinIO: list, head, get e nient'altro — nessuna put, nessuna remove, nessuna
policy. Il volume `em-dev_minio_data` resta com'è: è la copia di sicurezza finché
E.D. non decide di buttarlo.

Idempotente: un oggetto che in RustFS c'è già con la stessa dimensione si salta,
quindi un secondo giro dopo un'interruzione riprende da dove era.

Poi conta oggetti e byte di qua e di là, e RICALCOLA lo sha256 di un campione
di oggetti per impronta (chiave di 64 hex) letti da RustFS, confrontandolo con
la chiave: un conteggio uguale non dice che i byte sono giusti, l'impronta sì.
Esce con 0 solo se tutto torna.

Le credenziali arrivano dall'ambiente del container e non si stampano.
"""
from __future__ import annotations

import hashlib
import os
import random
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

HEX = set("0123456789abcdef")
CAMPIONE = int(os.environ.get("MIGRA_CAMPIONE", "50"))


def client(endpoint: str, access: str, secret: str):
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=access,
        aws_secret_access_key=secret, region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4",
                      retries={"max_attempts": 5, "mode": "standard"},
                      connect_timeout=5, read_timeout=120))


def oggetti(c, bucket: str) -> dict:
    out = {}
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for o in page.get("Contents", []):
            out[o["Key"]] = o["Size"]
    return out


def main() -> int:
    src = client(f"http://{os.environ['MIGRA_SRC_HOST']}:9000",
                 os.environ["MIGRA_SRC_ACCESS"], os.environ["MIGRA_SRC_SECRET"])
    dst = client("http://rustfs:9000",
                 os.environ["RUSTFS_ACCESS_KEY"], os.environ["RUSTFS_SECRET_KEY"])
    sb, db = os.environ["MIGRA_SRC_BUCKET"], os.environ["RUSTFS_BUCKET"]

    try:
        dst.head_bucket(Bucket=db)
    except ClientError:
        dst.create_bucket(Bucket=db)

    t0 = time.time()
    sorgente = oggetti(src, sb)
    print(f"MinIO  {sb}: {len(sorgente)} oggetti, {sum(sorgente.values())} B "
          f"(elenco in {time.time() - t0:.1f} s)", flush=True)
    gia = oggetti(dst, db)

    copiati = saltati = 0
    t0 = time.time()
    for i, (key, size) in enumerate(sorted(sorgente.items()), 1):
        if gia.get(key) == size:
            saltati += 1
            continue
        head = src.head_object(Bucket=sb, Key=key)
        body = src.get_object(Bucket=sb, Key=key)["Body"]
        try:
            # upload_fileobj fa il multipart da sé sopra gli 8 MiB: un glb da un
            # giga non passa per la memoria tutto intero
            dst.upload_fileobj(
                body, db, key,
                ExtraArgs={"ContentType": head.get("ContentType")
                           or "application/octet-stream",
                           **({"Metadata": head["Metadata"]}
                              if head.get("Metadata") else {})})
        finally:
            body.close()
        copiati += 1
        if i % 200 == 0:
            print(f"  … {i}/{len(sorgente)}", flush=True)
    print(f"copiati {copiati}, già presenti {saltati} "
          f"({time.time() - t0:.1f} s)", flush=True)

    # ── la verifica ─────────────────────────────────────────────────────────
    arrivo = oggetti(dst, db)
    mancano = [k for k, s in sorgente.items() if arrivo.get(k) != s]
    print(f"RustFS {db}: {len(arrivo)} oggetti, {sum(arrivo.values())} B")
    if mancano:
        print(f"✖ {len(mancano)} oggetti mancano o hanno un'altra dimensione, "
              f"per esempio {mancano[:3]}")
        return 1
    impronte = [k for k in sorgente if len(k) == 64 and set(k) <= HEX]
    scelti = random.sample(impronte, min(CAMPIONE, len(impronte)))
    sbagliati = []
    for k in scelti:
        h = hashlib.sha256()
        body = dst.get_object(Bucket=db, Key=k)["Body"]
        try:
            for chunk in iter(lambda: body.read(1 << 20), b""):
                h.update(chunk)
        finally:
            body.close()
        if h.hexdigest() != k:
            sbagliati.append(k)
    print(f"sha256 ricalcolato su {len(scelti)} oggetti per impronta "
          f"(su {len(impronte)}): {len(scelti) - len(sbagliati)} giusti")
    if sbagliati:
        print(f"✖ impronte sbagliate: {sbagliati[:3]}")
        return 1
    print("✔ tutto copiato, tutto verificato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
