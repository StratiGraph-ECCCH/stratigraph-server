#!/usr/bin/env python3
"""`get_asset` answers HEAD and Range on the LIVE node, through Caddy.

`tests/test_get_asset_range.py` proves the route in-process. What it cannot
prove is the chain a viewer actually walks: the browser's Range crosses Caddy,
reaches StratiGraph Server, and becomes a ranged GET on MinIO. This drives that
chain with the requests EMStudio's `.3tz` reader makes
(`frontend/src/tiles3tz.ts`: `bytes=-1` for the size, the last kilobyte, the
index, a tile) and measures the bytes that moved.

    cd dev-stack && ../.venv/bin/python smoke_asset_range.py
"""

from __future__ import annotations

import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tests"))
sys.path.insert(0, str(HERE.parent))           # `app`, which the test module imports

from smoke_common import (_TLS, Tally, alive, arguments, body_of, call,  # noqa: E402
                          detail_of, need, token_for, unique)
from test_get_asset_range import _big_3tz, open_3tz, read_entry  # noqa: E402

CASE_20 = HERE.parent / "tests" / "data" / "small-tileset-canonical.3tz"


def fetch(method, url, token, headers=None):
    request = urllib.request.Request(url, method=method, headers={
        "Authorization": f"Bearer {token}", **(headers or {})})
    try:
        with urllib.request.urlopen(request, context=_TLS, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


class LiveSource:
    """`test_get_asset_range.HttpSource`, over the network."""

    def __init__(self, url, token):
        self.url, self.token = url, token
        self.statuses, self.moved = [], 0

    def _get(self, rng):
        status, headers, body = fetch("GET", self.url, self.token, {"Range": rng})
        self.statuses.append(status)
        self.moved += len(body)
        return headers, body

    def size(self):
        headers, _ = self._get("bytes=-1")
        return int(headers.get("content-range", "/0").rsplit("/", 1)[1])

    def read(self, offset, length):
        return self._get(f"bytes={offset}-{offset + length - 1}")[1]


def main() -> int:
    args = arguments(__doc__ or "")
    base = args.base.rstrip("/")
    if not alive(base):
        return 2
    token = need(token_for(args.owner), "no owner token")
    tally = Tally()
    room_id = unique("smoke-range")
    status, _, raw = call("POST", f"{base}/rooms", token=token,
                          json_body={"room_id": room_id, "title": "range smoke"})
    tally.ok(status in (200, 201), f"a room to work in ({status})", detail_of(raw))

    big = _big_3tz(512 * 1024)                     # 8 tiles of 512 KB, ~4 MB
    refs = {}
    for name, data in (("case20", CASE_20.read_bytes()), ("big", big)):
        status, _, raw = call("PUT", f"{base}/rooms/{room_id}/asset"
                              f"?media_type=application/vnd.3tz",
                              token=token, data=data)
        refs[name] = body_of(raw).get("ref")
        tally.ok(status == 200 and refs[name], f"upload {name} ({len(data)} B)")

    url = f"{base}/rooms/{room_id}/asset/{refs['big']}"
    sg, hg, bg = fetch("GET", url, token)
    sh, hh, bh = fetch("HEAD", url, token)
    keys = ("etag", "content-type", "content-length", "accept-ranges", "x-em-license")
    tally.ok(sh == 200 and bh == b"", f"HEAD answers {sh} with no body")
    tally.ok({k: hg.get(k) for k in keys} == {k: hh.get(k) for k in keys},
             "HEAD and GET carry the same headers",
             str({k: hh.get(k) for k in keys}))

    s, h, b = fetch("GET", url, token, {"Range": "bytes=0-99"})
    tally.ok((s, len(b)) == (206, 100), f"bytes=0-99 → {s}, {len(b)} B",
             h.get("content-range", ""))
    s, h, b = fetch("GET", url, token, {"Range": "bytes=-22"})
    tally.ok((s, b) == (206, big[-22:]), f"bytes=-22 → {s}, the tail",
             h.get("content-range", ""))
    s, h, _ = fetch("GET", url, token, {"Range": f"bytes={len(big)}-"})
    tally.ok(s == 416 and h.get("content-range") == f"bytes */{len(big)}",
             f"past the end → {s}", h.get("content-range", ""))

    for name, path, expect in (("case20", "Data/c02/e0002.b3dm", None),
                               ("big", "Data/t05.b3dm", bytes([5]) * 512 * 1024)):
        src = LiveSource(f"{base}/rooms/{room_id}/asset/{refs[name]}", token)
        try:
            tile = read_entry(src, open_3tz(src), path)
        except Exception as exc:                    # noqa: BLE001 — a 200 is not a range
            tally.ok(False, f"{name}: the plugin's reads",
                     f"{type(exc).__name__}: {exc}; statuses {src.statuses}")
            continue
        tally.ok(set(src.statuses) == {206},
                 f"{name}: the plugin's {len(src.statuses)} requests all 206")
        if expect is not None:
            tally.ok(tile == expect and src.moved < len(big) // 4,
                     f"{name}: one tile cost {src.moved} B of a {len(big)} B archive")

    call("POST", f"{base}/admin/rooms/{room_id}/archive", token=token)
    return tally.report("asset range")


if __name__ == "__main__":
    sys.exit(main())
