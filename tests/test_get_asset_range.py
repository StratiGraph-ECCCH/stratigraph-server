"""`get_asset` answers HEAD and Range — and the gate bites every piece.

NIGHT-RISORSA-FILE (EMStudio) measured it: `GET /v1/rooms/{room}/asset/{ref}`
answered **200 with every byte** to a Range and **405** to a HEAD. EMStudio's
viewer reads a `.3tz` from its END, one tile per offset; against this store it
had to download the whole archive — 199 MB for TempluMare, where the tiles it
showed were 175 KB.

What these tests defend:

* HEAD is the GET without a body: the same headers, the same refusals;
* one interval → 206 with `Content-Range`; past the end → 416 with
  `bytes */<size>`; several → 200 with everything (the declared choice);
* `If-Range` with another ETag → 200 with everything;
* an embargo answers the same with and without a Range — 22 bytes of an
  embargoed file are an embargoed file;
* the bytes come from the store's RANGED read, not from a full read sliced;
* the `.3tz` of dtcstamp's case 20 opens with the requests EMStudio's plugin
  makes (`frontend/src/tiles3tz.ts`: `bytes=-1` for the size, the last
  kilobyte, the index's local header, the index, a tile), every one a 206.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import re
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import ws as ws_module
from app.access import Acl, InMemoryAclStore
from app.assets import (DirectoryAssetStore, InMemoryAssetStore,
                        MinioAssetStore)
from app.main import _byte_range
from app.rooms import RoomRegistry
from app.store import InMemorySnapshotStore

ANNA = "0000-0002-1825-0097"     # owner
CARLA = "0000-0003-1415-9265"    # editor
BRUNO = "0000-0001-5109-3700"    # viewer
AUTH = {"Authorization": "Bearer t"}

DATA = pathlib.Path(__file__).resolve().parent / "data"
#: dtcstamp/conformance/data/small-tileset-canonical.3tz, case 20 — copied, and
#: pinned by its digest so a drift in the copy is a red test, not a mystery
CASE_20 = DATA / "small-tileset-canonical.3tz"
CASE_20_SHA256 = "75b111b73bbd230e5083091304a53e19d1ad4495763b16f318c803bdec86f0bf"

BYTES = bytes(range(256)) * 4                 # 1024 bytes, each offset readable
SECRET = b"\x89PNG\r\n\x1a\n" + b"under embargo" * 20


# ── the room ────────────────────────────────────────────────────────────────

class CountingStore(InMemoryAssetStore):
    """The in-memory store, telling which read the route used."""

    def __init__(self):
        super().__init__()
        self.full_reads = 0
        self.ranged_reads = []

    def get(self, ref):
        self.full_reads += 1
        return super().get(ref)

    def read_range(self, ref, start, length):
        self.ranged_reads.append((start, length))
        return super().read_range(ref, start, length)


def _document(room_id: str, *, embargoed: str) -> dict:
    nodes = [
        {"id": "img", "node_type": "resource", "name": "Prospetto",
         "data": {"checksum": embargoed, "media_type": "image/png"}},
        {"id": "emb", "node_type": "embargo", "name": "2099-01-01",
         "data": {"embargo_end": "2099-01-01", "reason": "in corso di studio"}},
        {"id": "aut", "node_type": "author", "name": "Anna",
         "data": {"orcid": ANNA}},
        {"id": "lic", "node_type": "license", "name": "CC-BY-4.0",
         "data": {"license_type": "CC-BY-4.0"}},
    ]
    edges = [
        {"id": "e1", "source": "img", "target": "emb", "edge_type": "has_embargo"},
        {"id": "e2", "source": "img", "target": "aut", "edge_type": "has_author"},
        {"id": "e3", "source": "img", "target": "lic", "edge_type": "has_license"},
    ]
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": ANNA},
            "graphs": {room_id: {"graph_id": room_id, "name": room_id,
                                 "nodes": nodes, "edges": edges}},
            "active_graph_id": room_id}


@pytest.fixture()
def room(monkeypatch):
    from app import main as main_module

    store = CountingStore()
    refs = {"plain": store.put(BYTES, "application/octet-stream")["ref"],
            "secret": store.put(SECRET, "image/png")["ref"],
            "case20": store.put(CASE_20.read_bytes(), "application/vnd.3tz")["ref"]}
    monkeypatch.setattr(main_module, "ASSET_STORE", store)

    snapshots = InMemorySnapshotStore()
    snapshots.put("scavo", _document("scavo", embargoed=refs["secret"]))
    acls = InMemoryAclStore()
    acls.put("scavo", Acl(owner=ANNA, members={CARLA: "editor",
                                               BRUNO: "viewer"}).as_dict())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", snapshots)
    monkeypatch.setattr(ws_module, "ROOMS", RoomRegistry(snapshots))
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    return {**refs, "store": store}


def _authenticators():
    """The authenticator `app.main` uses AND the one `app.ws` holds.

    Usually one object. `tests/test_auth.py` reloads `app.auth` and `app.main`,
    after which they are two — and patching only the `ws` one leaves the route
    in open dev mode (measured: the embargo test passed alone and served the
    bytes in the full suite)."""
    from app import main as main_module
    seen = []
    for a in (main_module.authenticator, ws_module.authenticator):
        if all(a is not s for s in seen):
            seen.append(a)
    return seen


@pytest.fixture()
def whoever(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    for a in _authenticators():
        monkeypatch.setattr(a, "settings", Enforcing())

    def be(orcid):
        for a in _authenticators():
            monkeypatch.setattr(a, "verify",
                                lambda token: ({"orcid": orcid} if orcid else {}))
            monkeypatch.setattr(a, "require_token",
                                lambda request: ({"orcid": orcid} if orcid else {}))
    return be


@pytest.fixture()
def client():
    from app import main as main_module       # the module as it is NOW
    return TestClient(main_module.app)


def url(ref: str) -> str:
    return f"/v1/rooms/scavo/asset/{ref}"


def _same_headers(a, b, *, but=()):
    """The headers that describe the resource, compared — not the ones that
    describe one transfer (`date`, `content-range`)."""
    keys = {"etag", "accept-ranges", "content-type", "content-length",
            "x-em-license", "x-em-license-default", "x-em-embargo",
            "x-em-author"} - set(but)
    return ({k: a.headers.get(k) for k in keys},
            {k: b.headers.get(k) for k in keys})


# ── HEAD ────────────────────────────────────────────────────────────────────

def test_head_and_get_carry_the_same_headers_and_head_no_body(client, room, whoever):
    whoever(CARLA)
    got = client.get(url(room["secret"]), headers=AUTH)
    head = client.head(url(room["secret"]), headers=AUTH)
    assert got.status_code == head.status_code == 200
    left, right = _same_headers(got, head)
    assert left == right
    assert head.headers["content-length"] == str(len(SECRET))
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["x-em-embargo"] == "2099-01-01"
    assert head.content == b""


def test_head_moves_no_bytes(client, room, whoever):
    whoever(CARLA)
    store = room["store"]
    client.head(url(room["plain"]), headers=AUTH)
    assert store.full_reads == 0 and store.ranged_reads == []


def test_head_is_refused_exactly_as_get(client, room, whoever):
    for orcid in (BRUNO, None):
        whoever(orcid)
        got = client.get(url(room["secret"]), headers=AUTH if orcid else {})
        head = client.head(url(room["secret"]), headers=AUTH if orcid else {})
        assert got.status_code in (401, 403)
        assert head.status_code == got.status_code
        assert head.content == b""


def test_head_of_a_missing_asset_is_404_like_get(client, room, whoever):
    whoever(CARLA)
    ghost = "sha256:" + "0" * 64
    assert client.get(url(ghost), headers=AUTH).status_code == 404
    assert client.head(url(ghost), headers=AUTH).status_code == 404


# ── Range ───────────────────────────────────────────────────────────────────

def test_the_first_hundred_bytes(client, room, whoever):
    whoever(BRUNO)
    r = client.get(url(room["plain"]), headers={**AUTH, "Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.content == BYTES[:100]
    assert r.headers["content-range"] == f"bytes 0-99/{len(BYTES)}"
    assert r.headers["content-length"] == "100"
    assert r.headers["accept-ranges"] == "bytes"


def test_the_tail_the_3tz_plugin_asks_for(client, room, whoever):
    """`bytes=-22` is the EOCD's size; EMStudio's `httpSource.size()` actually
    opens with `bytes=-1` — both are suffixes and both are answered."""
    whoever(BRUNO)
    for n in (22, 1):
        r = client.get(url(room["plain"]), headers={**AUTH, "Range": f"bytes=-{n}"})
        assert r.status_code == 206
        assert r.content == BYTES[-n:]
        assert r.headers["content-range"] == \
            f"bytes {len(BYTES) - n}-{len(BYTES) - 1}/{len(BYTES)}"


def test_an_open_interval_and_one_clipped_at_the_end(client, room, whoever):
    whoever(BRUNO)
    r = client.get(url(room["plain"]), headers={**AUTH, "Range": "bytes=1000-"})
    assert (r.status_code, r.content) == (206, BYTES[1000:])
    r = client.get(url(room["plain"]), headers={**AUTH, "Range": "bytes=1000-99999"})
    assert (r.status_code, r.content) == (206, BYTES[1000:])
    assert r.headers["content-range"] == "bytes 1000-1023/1024"


def test_past_the_end_is_416_with_the_size(client, room, whoever):
    whoever(BRUNO)
    for spec in ("bytes=1024-", "bytes=5000-6000", "bytes=-0"):
        r = client.get(url(room["plain"]), headers={**AUTH, "Range": spec})
        assert r.status_code == 416, spec
        assert r.headers["content-range"] == "bytes */1024"


def test_several_intervals_get_the_whole_file(client, room, whoever):
    """The declared choice: a 200 is a correct answer to any Range, and no
    reader here parses `multipart/byteranges`."""
    whoever(BRUNO)
    r = client.get(url(room["plain"]), headers={**AUTH, "Range": "bytes=0-9,20-29"})
    assert (r.status_code, r.content) == (200, BYTES)
    assert "content-range" not in r.headers


def test_a_range_that_does_not_parse_is_ignored(client, room, whoever):
    whoever(BRUNO)
    for spec in ("bytes=abc", "items=0-9", "bytes=9-0", "bytes="):
        r = client.get(url(room["plain"]), headers={**AUTH, "Range": spec})
        assert (r.status_code, r.content) == (200, BYTES), spec


def test_if_range_with_another_etag_gets_everything(client, room, whoever):
    whoever(BRUNO)
    etag = f'"{room["plain"]}"'
    same = client.get(url(room["plain"]),
                      headers={**AUTH, "Range": "bytes=0-9", "If-Range": etag})
    assert (same.status_code, same.content) == (206, BYTES[:10])
    other = client.get(url(room["plain"]),
                       headers={**AUTH, "Range": "bytes=0-9", "If-Range": '"x"'})
    assert (other.status_code, other.content) == (200, BYTES)


def test_a_range_is_read_ranged_from_the_store(client, room, whoever):
    whoever(BRUNO)
    store = room["store"]
    client.get(url(room["plain"]), headers={**AUTH, "Range": "bytes=10-19"})
    assert store.ranged_reads == [(10, 10)]
    assert store.full_reads == 0, "a range must not cost the whole file"


def test_an_embargo_answers_the_same_with_and_without_a_range(client, room, whoever):
    for orcid in (BRUNO, None):
        whoever(orcid)
        auth = AUTH if orcid else {}
        whole = client.get(url(room["secret"]), headers=auth)
        part = client.get(url(room["secret"]), headers={**auth, "Range": "bytes=0-21"})
        tail = client.get(url(room["secret"]), headers={**auth, "Range": "bytes=-22"})
        assert whole.status_code in (401, 403)
        assert part.status_code == tail.status_code == whole.status_code
        assert part.content == tail.content == whole.content
    # …and the editor gets the piece, with the embargo said
    whoever(CARLA)
    part = client.get(url(room["secret"]), headers={**AUTH, "Range": "bytes=0-7"})
    assert (part.status_code, part.content) == (206, SECRET[:8])
    assert part.headers["x-em-embargo"] == "2099-01-01"


def test_the_range_parser_on_its_own():
    assert _byte_range(None, 10) is None
    assert _byte_range("bytes=0-0", 10) == (0, 0)
    assert _byte_range("bytes=-3", 10) == (7, 9)
    assert _byte_range("bytes=-30", 10) == (0, 9)
    assert _byte_range("bytes=4-", 10) == (4, 9)
    assert _byte_range("bytes=10-", 10) == "416"
    assert _byte_range("bytes=0-1, 3-4", 10) is None


# ── the three stores read a range without reading the rest ──────────────────

def test_every_store_offers_a_ranged_read():
    for cls in (InMemoryAssetStore, DirectoryAssetStore, MinioAssetStore):
        assert callable(getattr(cls, "read_range", None)), cls.__name__


def test_the_directory_store_reads_a_range(tmp_path):
    store = DirectoryAssetStore(tmp_path)
    ref = store.put(BYTES, "application/octet-stream")["ref"]
    assert store.read_range(ref, 1000, 50) == BYTES[1000:]
    assert store.read_range(ref, 3, 4) == BYTES[3:7]
    assert store.read_range("sha256:" + "0" * 64, 0, 1) is None


# ── the .3tz, read the way EMStudio reads it ────────────────────────────────

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


def test_the_case_20_archive_is_the_one_dtcstamp_names():
    assert hashlib.sha256(CASE_20.read_bytes()).hexdigest() == CASE_20_SHA256


def test_the_case_20_3tz_opens_with_the_plugins_requests(client, room, whoever):
    whoever(BRUNO)
    src = HttpSource(client, url(room["case20"]), AUTH)
    entries = open_3tz(src)
    tile = read_entry(src, entries, "Data/c02/e0002.b3dm")
    with zipfile.ZipFile(CASE_20) as z:
        assert tile == z.read("Data/c02/e0002.b3dm")
        assert len(entries) == len(z.infolist()) - 1       # the index indexes the rest
    assert set(src.statuses) == {206}, src.statuses


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


def test_a_tile_costs_a_tile_and_not_the_archive(client, room, whoever):
    """The TempluMare measurement in small: 8 tiles of 256 KB, one asked."""
    whoever(BRUNO)
    archive = _big_3tz(256 * 1024)
    ref = room["store"].put(archive, "application/vnd.3tz")["ref"]
    room["store"].full_reads = 0
    src = HttpSource(client, url(ref), AUTH)
    entries = open_3tz(src)
    tile = read_entry(src, entries, "Data/t05.b3dm")
    assert tile == bytes([5]) * 256 * 1024
    assert set(src.statuses) == {206}
    assert room["store"].full_reads == 0
    assert src.moved < 256 * 1024 + 2048, (src.moved, len(archive))
    assert len(archive) > 8 * src.moved / 2
