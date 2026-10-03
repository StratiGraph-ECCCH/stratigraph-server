#!/usr/bin/env python3
"""A big file into a room: ask first, send in pieces, resume after a cut.

U1 (MICRO-LA-BARRA-E-LE-STANZE, 3 October 2026). The client side of the
contract in `app/main.py` (`put_asset`, `start_upload`, `continue_upload`),
written the way EMStudio and EMtools are to follow it — and the tool that
measured it against the live stack with a 2 GB file:

    python dev-stack/smoke_big_upload.py --file big.bin --room u1-proof
    python dev-stack/smoke_big_upload.py --file big.bin --room u1-proof --stop-at 0.5
    python dev-stack/smoke_big_upload.py --file big.bin --room u1-proof --resume <id>
    python dev-stack/smoke_big_upload.py --file big.bin --room u1-proof --put

What it does, in the client's order:

1. sha256 of the local file, read a megabyte at a time (never all of it);
2. **HEAD /rooms/{room}/asset/sha256:<hex>** — 200: the room has it, nothing is
   sent; 404: send it; 403: it exists but is not yours to read (D-C) — send it
   anyway, the server dedups and your room becomes one of its homes;
3. **POST /rooms/{room}/uploads** {size, sha256, media_type} → upload_id;
4. **PATCH …/uploads/{id}** with `Upload-Offset`, one piece at a time, streamed
   from the file, with progress; a 409 carries the server's offset and the
   client goes on from there;
5. `--stop-at 0.5` stops (like a killed client) after half and prints the id;
   `--resume <id>` asks **HEAD …/uploads/{id}** for `Upload-Offset` and goes on;
6. on the last piece the answer is `complete: true` with the asset: its sha256
   must be the local one.

`--put` uses the one-shot streamed `PUT …/asset?expected_sha256=` instead.

Nothing is decided here; it calls, it checks, it prints.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import pathlib
import sys
import time
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from smoke_common import DEFAULT_BASE, Tally, _TLS, token_for  # noqa: E402

MIB = 1024 * 1024


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for piece in iter(lambda: fh.read(MIB), b""):
            digest.update(piece)
    return digest.hexdigest()


class Node:
    """One connection per request, bodies streamed from file objects:
    `http.client` reads a file body in blocks, so the client holds a block,
    never the file."""

    def __init__(self, base: str, token: str) -> None:
        url = urllib.parse.urlsplit(base.rstrip("/"))
        self.https = url.scheme == "https"
        self.host = url.netloc
        self.prefix = url.path
        self.token = token

    def request(self, method: str, path: str, *, body=None, headers=None):
        conn = (http.client.HTTPSConnection(self.host, context=_TLS, timeout=600)
                if self.https else
                http.client.HTTPConnection(self.host, timeout=600))
        all_headers = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        try:
            conn.request(method, self.prefix + path, body=body, headers=all_headers)
            answer = conn.getresponse()
            data = answer.read()
            return answer.status, {k.lower(): v for k, v in answer.getheaders()}, data
        finally:
            conn.close()


class Window:
    """A file object over [start, start+length) of a file: the PATCH body."""

    def __init__(self, path: pathlib.Path, start: int, length: int) -> None:
        self.fh = open(path, "rb")
        self.fh.seek(start)
        self.left = length

    def read(self, n: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        n = self.left if n is None or n < 0 else min(n, self.left)
        data = self.fh.read(n)
        self.left -= len(data)
        return data

    def close(self) -> None:
        self.fh.close()


def progress(done: int, total: int, started: float) -> None:
    rate = done / max(time.time() - started, 1e-6) / MIB
    print(f"\r    {done / MIB:9.1f} / {total / MIB:.1f} MiB  "
          f"({100 * done / total:5.1f} %)  {rate:6.1f} MiB/s", end="", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--user", default=None, help="realm user (default dev)")
    parser.add_argument("--room", required=True)
    parser.add_argument("--file", required=True, type=pathlib.Path)
    parser.add_argument("--media-type", default="application/octet-stream")
    parser.add_argument("--chunk-mb", type=int, default=64)
    parser.add_argument("--stop-at", type=float, default=None,
                        help="stop after this fraction, like a killed client")
    parser.add_argument("--resume", default=None, help="an upload_id to resume")
    parser.add_argument("--put", action="store_true",
                        help="one streamed PUT instead of the resumable upload")
    args = parser.parse_args()

    tally = Tally()
    token = token_for(args.user)
    if not token:
        return 2
    node = Node(args.base, token)
    room = urllib.parse.quote(args.room, safe="")
    size = args.file.stat().st_size

    print(f"file   : {args.file} ({size / MIB:.1f} MiB)")
    t0 = time.time()
    digest = sha256_of(args.file)
    print(f"sha256 : {digest}  ({time.time() - t0:.1f} s)")

    # ── 1 · the question asked FIRST ─────────────────────────────────────────
    status, _, _ = node.request("HEAD", f"/rooms/{room}/asset/sha256:{digest}")
    print(f"HEAD asset → {status}")
    if status == 200 and not args.resume:
        tally.ok(True, "the room already has these bytes: nothing to send")
        return tally.report("big upload")

    if args.put:
        started = time.time()
        with open(args.file, "rb") as fh:
            status, _, data = node.request(
                "PUT", f"/rooms/{room}/asset?media_type="
                       f"{urllib.parse.quote(args.media_type)}&expected_sha256={digest}",
                body=fh, headers={"Content-Length": str(size),
                                  "Content-Type": args.media_type})
        took = time.time() - started
        info = json.loads(data or b"{}")
        tally.ok(status == 200, "streamed PUT accepted", f"{status} in {took:.1f} s")
        tally.ok(info.get("sha256") == digest, "the stored sha256 is the local one",
                 str(info.get("sha256")))
        tally.ok(info.get("size") == size, "the stored size is the local one",
                 str(info.get("size")))
        return tally.report("big upload (PUT)")

    # ── 2 · open or resume ──────────────────────────────────────────────────
    if args.resume:
        upload_id = args.resume
        status, headers, _ = node.request("HEAD", f"/rooms/{room}/uploads/{upload_id}")
        if not tally.ok(status == 200, "the server still has the upload", str(status)):
            return tally.report("big upload")
        offset = int(headers["upload-offset"])
        print(f"resume : {upload_id} at offset {offset} "
              f"({100 * offset / size:.1f} %) — the SERVER's word")
    else:
        status, _, data = node.request(
            "POST", f"/rooms/{room}/uploads",
            body=json.dumps({"size": size, "sha256": digest,
                             "media_type": args.media_type}).encode(),
            headers={"Content-Type": "application/json"})
        if not tally.ok(status == 201, "upload opened", f"{status} {data[:120]!r}"):
            return tally.report("big upload")
        upload_id = json.loads(data)["upload_id"]
        offset = 0
        print(f"upload : {upload_id}")

    # ── 3 · the pieces ──────────────────────────────────────────────────────
    chunk = args.chunk_mb * MIB
    stop = int(size * args.stop_at) if args.stop_at else None
    started, first = time.time(), offset
    result = None
    while offset < size:
        if stop is not None and offset >= stop:
            print(f"\n    stopped at {offset} bytes, like a killed client")
            print(f"    resume with: --resume {upload_id}")
            tally.ok(True, "interrupted on purpose", f"offset {offset}")
            return tally.report("big upload (interrupted)")
        length = min(chunk, size - offset)
        window = Window(args.file, offset, length)
        try:
            status, headers, data = node.request(
                "PATCH", f"/rooms/{room}/uploads/{upload_id}", body=window,
                headers={"Upload-Offset": str(offset),
                         "Content-Length": str(length),
                         "Content-Type": "application/offset+octet-stream"})
        finally:
            window.close()
        if status == 409 and "upload-offset" in headers:
            offset = int(headers["upload-offset"])       # the server's word
            continue
        if status != 200:
            print()
            tally.ok(False, "piece accepted", f"{status} {data[:200]!r}")
            return tally.report("big upload")
        result = json.loads(data)
        offset = int(result["offset"])
        progress(offset - first, size - first, started)
        if result.get("complete"):
            break
    print()
    took = time.time() - started
    asset = (result or {}).get("asset") or {}
    tally.ok(bool(result and result.get("complete")), "the upload is complete",
             f"{(size - first) / MIB:.0f} MiB in {took:.1f} s")
    tally.ok(asset.get("sha256") == digest, "the stored sha256 is the local one",
             str(asset.get("sha256")))
    status, headers, _ = node.request("HEAD", f"/rooms/{room}/asset/sha256:{digest}")
    tally.ok(status == 200 and headers.get("content-length") == str(size),
             "HEAD now answers 200 with the size", f"{status} {headers.get('content-length')}")
    return tally.report("big upload")


if __name__ == "__main__":
    sys.exit(main())
