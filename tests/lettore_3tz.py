"""EMStudio's `.3tz` reader, in Python and in the standard library only.

`EMStudio/frontend/src/tiles3tz.ts` (`httpSource` + `Archive3tz.open` /
`readEntry`) for the canonical case — no zip64, no comment — making the same
requests in the same order: `bytes=-1` for the size, the last kilobyte (EOCD and
the directory's tail), the index's local header, the index, then for a tile its
local header, its name and its bytes.

Standard library only, ON PURPOSE: `tests/test_get_asset_range.py` drives it
in-process and `dev-stack/smoke_asset_range.py` drives it over the network from
the node itself, where there is a `python3` and no virtualenv.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile

SIG_EOCD, SIG_CDH, SIG_LFH = 0x06054B50, 0x02014B50, 0x04034B50
INDEX_NAME = b"@3dtilesIndex1@"


class HttpSource:
    """`httpSource` of `EMStudio/frontend/src/tiles3tz.ts`, in Python: the
    size from a `bytes=-1`, every read an explicit `bytes=a-b`, and a record of
    what came back."""

    def __init__(self, client, path, headers):
        self.client, self.path, self.headers = client, path, headers
        self.statuses, self.moved, self.total = [], 0, None

    def size(self):
        r = self.client.get(self.path, headers={**self.headers, "Range": "bytes=-1"})
        self.statuses.append(r.status_code)
        self.moved += len(r.content)
        self.total = int(re.search(r"/(\d+)\s*$", r.headers["content-range"]).group(1))
        return self.total

    def read(self, offset, length):
        r = self.client.get(self.path, headers={
            **self.headers, "Range": f"bytes={offset}-{offset + length - 1}"})
        self.statuses.append(r.status_code)
        self.moved += len(r.content)
        return r.content


def _key(path: str) -> tuple:
    d = hashlib.md5(path.encode()).digest()
    return struct.unpack("<QQ", d)


def open_3tz(src: HttpSource) -> dict:
    """`Archive3tz.open` for the canonical case (no zip64, no comment)."""
    size = src.size()
    tail_len = min(size, 1024)
    tail = src.read(size - tail_len, tail_len)
    e = max(i for i in range(len(tail) - 21)
            if struct.unpack_from("<I", tail, i)[0] == SIG_EOCD)
    cd_size, cd_offset = struct.unpack_from("<II", tail, e + 12)
    # the directory's tail is inside the kilobyte already read (tiles3tz.ts
    # `cdTailOf`: no new request when it is)
    base = size - tail_len
    cd = tail[cd_offset - base:cd_offset + cd_size - base] if cd_offset >= base \
        else src.read(cd_offset, cd_size)
    rec = max(i for i in range(len(cd) - 45)
              if struct.unpack_from("<I", cd, i)[0] == SIG_CDH
              and cd[i + 46:i + 46 + len(INDEX_NAME)] == INDEX_NAME)
    isize = struct.unpack_from("<I", cd, rec + 20)[0]
    lho = struct.unpack_from("<I", cd, rec + 42)[0]
    lfh = src.read(lho, 30)
    assert struct.unpack_from("<I", lfh, 0)[0] == SIG_LFH
    nlen, xlen = struct.unpack_from("<HH", lfh, 26)
    index = src.read(lho + 30 + nlen + xlen, isize)
    entries = {}
    for i in range(0, len(index), 24):
        hi, lo, off = struct.unpack_from("<QQQ", index, i)
        entries[(hi, lo)] = off
    return entries


def read_entry(src: HttpSource, entries: dict, path: str) -> bytes:
    off = entries[_key(path)]
    head = src.read(off, 30)
    assert struct.unpack_from("<I", head, 0)[0] == SIG_LFH
    method, = struct.unpack_from("<H", head, 8)
    csize, = struct.unpack_from("<I", head, 18)
    nlen, xlen = struct.unpack_from("<HH", head, 26)
    name = src.read(off + 30, nlen + xlen)[:nlen].decode()
    assert name == path
    assert method == 0, "a canonical 3tz stores its tiles"
    return src.read(off + 30 + nlen + xlen, csize)


def _big_3tz(tile_bytes: int) -> bytes:
    """A canonical-shaped `.3tz` big enough that reading it whole and reading
    it by tile are different numbers: stored entries, the index last."""
    files = {"tileset.json": b'{"asset":{"version":"1.0"}}',
             **{f"Data/t{i:02d}.b3dm": bytes([i]) * tile_bytes for i in range(8)}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data)
        offsets = {i.filename: i.header_offset for i in z.infolist()}
        index = b"".join(struct.pack("<QQQ", *_key(n), offsets[n])
                         for n in sorted(offsets, key=_key))
        z.writestr(zipfile.ZipInfo("@3dtilesIndex1@", (1980, 1, 1, 0, 0, 0)), index)
    return buf.getvalue()
