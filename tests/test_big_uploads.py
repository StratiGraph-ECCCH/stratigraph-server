"""U1 · big uploads: a stream into the store, and an upload that survives a cut.

Measured on 3 October 2026 before anything changed: `PUT …/asset` did
`await request.body()` — a 2 GB file was a 2 GB `bytes` in the server — and an
upload cut at 1.9 GB started again from zero. What these tests hold (the 2 GB
proof with the server's memory sampled is `dev-stack/smoke_big_upload.py`,
against the live stack; these are the contract):

* the PUT never asks for the whole body: `Request.body` is booby-trapped here,
  and the upload still works — same answer as before, `created` and `author`
  included, dedup included;
* `expected_sha256` that does not match the bytes → 422, nothing stored;
* a resumable upload interrupted at half resumes from the offset the SERVER
  reports, and the stored file is the original, digest for digest;
* the wrong offset → 409 with the right one; a piece past the size → 413;
* a declared sha256 the bytes do not match → 422 and the upload is discarded;
* the session lives on disk: a new process (a new `UploadSessions` on the same
  directory) carries on where the old one stopped;
* a cut in the middle of a piece keeps what arrived;
* nobody else can see, continue or abandon your upload (404);
* the HEAD that a client asks FIRST answers 200 / 404 by digest, with no body.
"""

from __future__ import annotations

import asyncio
import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect, Request

from app import asset_homes                              # noqa: E402
from app import main as main_module                      # noqa: E402
from app import uploads                                  # noqa: E402
from app import ws as ws_module                          # noqa: E402
from app.asset_homes import InMemoryAssetHomes           # noqa: E402
from app.assets import DirectoryAssetStore, InMemoryAssetStore  # noqa: E402
from app.main import app                                 # noqa: E402
from app.uploads import UploadSessions, receive_stream   # noqa: E402

ANNA = "0000-0002-1825-0097"
DARIO = "0000-0002-9079-593X"
AUTH = {"Authorization": "Bearer t"}

BIG = os.urandom(3 * 1024 * 1024 + 17)       # 3 MiB and a bit: several chunks
DIGEST = hashlib.sha256(BIG).hexdigest()


@pytest.fixture()
def node(monkeypatch, tmp_path):
    store = InMemoryAssetStore()
    monkeypatch.setattr(main_module, "ASSET_STORE", store)
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", InMemoryAssetHomes())
    monkeypatch.setattr(uploads, "SESSIONS", UploadSessions(tmp_path / "up"))
    return store


@pytest.fixture()
def be(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    for module in (ws_module, main_module):
        monkeypatch.setattr(module.authenticator, "settings", Enforcing())

    def as_(orcid):
        for module in (ws_module, main_module):
            monkeypatch.setattr(module.authenticator, "verify",
                                lambda token: ({"orcid": orcid} if orcid else {}))
    return as_


@pytest.fixture()
def client():
    return TestClient(app)


def _pieces(data: bytes, size: int = 64 * 1024):
    for i in range(0, len(data), size):
        yield data[i:i + size]


# ── the streamed PUT ────────────────────────────────────────────────────────

def test_the_put_never_holds_the_whole_body(client, node, be, monkeypatch):
    """`Request.body()` is what buffered 2 GB. Booby-trapped: if the door asks
    for it, the test fails — and the upload still answers as it always did."""
    async def no_body(self):
        raise AssertionError("put_asset read the whole body into memory")
    monkeypatch.setattr(Request, "body", no_body)
    be(ANNA)
    answer = client.put("/v1/rooms/scavo/asset?media_type=image/tiff",
                        content=_pieces(BIG), headers=AUTH)
    assert answer.status_code == 200, answer.text
    info = answer.json()
    assert info == {"ref": f"sha256:{DIGEST}", "sha256": DIGEST,
                    "media_type": "image/tiff", "size": len(BIG),
                    "created": True, "author": ANNA}
    assert node.get(info["ref"]) == BIG
    again = client.put("/v1/rooms/scavo/asset?media_type=image/tiff",
                       content=BIG, headers=AUTH).json()
    assert again["created"] is False and node.count() == 1
    # …and the temporary file is gone
    assert list(uploads.SESSIONS.root.iterdir()) == []


def test_a_put_whose_bytes_are_not_the_declared_ones_stores_nothing(client, node, be):
    be(ANNA)
    wrong = client.put(f"/v1/rooms/scavo/asset?expected_sha256={'0' * 64}",
                       content=BIG, headers=AUTH)
    assert wrong.status_code == 422 and DIGEST in wrong.json()["detail"]
    assert node.count() == 0
    right = client.put("/v1/rooms/scavo/asset", content=BIG,
                       headers={**AUTH, "X-EM-Expected-SHA256": f"sha256:{DIGEST}"})
    assert right.status_code == 200


def test_the_directory_store_takes_the_file_without_reading_it(tmp_path):
    store = DirectoryAssetStore(tmp_path / "assets")
    source = tmp_path / "in.part"
    source.write_bytes(BIG)
    info = store.put_file(source, DIGEST, len(BIG), "image/tiff")
    assert info["created"] and store.get(info["ref"]) == BIG
    assert store.head(info["ref"])["media_type"] == "image/tiff"
    source.write_bytes(BIG)
    assert store.put_file(source, DIGEST, len(BIG), "image/tiff")["created"] is False


# ── the question asked FIRST ────────────────────────────────────────────────

def test_head_by_digest_answers_200_or_404_without_a_body(client, node, be):
    be(ANNA)
    ref = f"sha256:{DIGEST}"
    assert client.head(f"/v1/rooms/scavo/asset/{ref}", headers=AUTH).status_code == 404
    client.put("/v1/rooms/scavo/asset", content=BIG, headers=AUTH)
    head = client.head(f"/v1/rooms/scavo/asset/{ref}", headers=AUTH)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(BIG))


# ── the resumable upload ────────────────────────────────────────────────────

def _start(client, size=len(BIG), sha=DIGEST, room="scavo"):
    answer = client.post(f"/v1/rooms/{room}/uploads", headers=AUTH,
                         json={"size": size, "sha256": sha,
                               "media_type": "image/jpeg"})
    assert answer.status_code == 201, answer.text
    return answer.json()


def _patch(client, upload_id, offset, data, room="scavo"):
    return client.patch(f"/v1/rooms/{room}/uploads/{upload_id}", content=data,
                        headers={**AUTH, "Upload-Offset": str(offset)})


def test_cut_at_half_resumed_from_the_servers_offset(client, node, be):
    be(ANNA)
    started = _start(client)
    assert started["offset"] == 0 and started["size"] == len(BIG)
    up = started["upload_id"]
    half = len(BIG) // 2
    first = _patch(client, up, 0, _pieces(BIG[:half]))
    assert first.status_code == 200 and first.json()["offset"] == half
    assert first.json()["complete"] is False
    assert node.count() == 0, "nothing is stored before the last byte"

    # …the client dies. A new one asks where the upload is:
    where = client.head(f"/v1/rooms/scavo/uploads/{up}", headers=AUTH)
    assert where.status_code == 200
    offset = int(where.headers["Upload-Offset"])
    assert offset == half and where.headers["Upload-Length"] == str(len(BIG))

    last = _patch(client, up, offset, _pieces(BIG[offset:]))
    assert last.status_code == 200, last.text
    done = last.json()
    assert done["complete"] is True and done["offset"] == len(BIG)
    assert done["asset"]["sha256"] == DIGEST and done["asset"]["author"] == ANNA
    assert node.get(f"sha256:{DIGEST}") == BIG
    # the session is gone, and the room is recorded as the bytes' home (D-C)
    assert client.head(f"/v1/rooms/scavo/uploads/{up}",
                       headers=AUTH).status_code == 404
    assert asset_homes.ASSET_HOMES.homes(DIGEST) == {"scavo": [ANNA]}


def test_the_wrong_offset_is_a_409_that_says_the_right_one(client, node, be):
    be(ANNA)
    up = _start(client)["upload_id"]
    _patch(client, up, 0, BIG[:1000])
    wrong = _patch(client, up, 0, BIG[:1000])          # a retry of a piece it has
    assert wrong.status_code == 409
    assert wrong.json()["offset"] == 1000 and wrong.headers["Upload-Offset"] == "1000"
    assert client.patch(f"/v1/rooms/scavo/uploads/{up}", content=b"x",
                        headers=AUTH).status_code == 400, "no Upload-Offset"


def test_a_piece_past_the_size_is_413_and_nothing_past_it_is_kept(client, node, be):
    be(ANNA)
    up = _start(client, size=10, sha=None)["upload_id"]
    too_much = _patch(client, up, 0, b"0123456789ABC")
    assert too_much.status_code == 413 and too_much.json()["offset"] == 10
    # the file is complete at its size: an empty PATCH at the end finishes it
    done = _patch(client, up, 10, b"")
    assert done.json()["complete"] is True
    assert node.get(done.json()["asset"]["ref"]) == b"0123456789"


def test_bytes_that_are_not_the_declared_file_are_discarded(client, node, be):
    be(ANNA)
    up = _start(client, size=len(BIG), sha="1" * 64)["upload_id"]
    refused = _patch(client, up, 0, BIG)
    assert refused.status_code == 422 and DIGEST in refused.json()["detail"]
    assert node.count() == 0
    assert client.get(f"/v1/rooms/scavo/uploads/{up}",
                      headers=AUTH).status_code == 404, "discarded, not resumable"


def test_the_session_survives_the_process(client, node, be, monkeypatch):
    """A restart is a new `UploadSessions` on the same directory: the offset is
    the length of the partial file, so it is exactly where it was."""
    be(ANNA)
    up = _start(client)["upload_id"]
    _patch(client, up, 0, BIG[:12345])
    monkeypatch.setattr(uploads, "SESSIONS", UploadSessions(uploads.SESSIONS.root))
    status = client.get(f"/v1/rooms/scavo/uploads/{up}", headers=AUTH).json()
    assert status["offset"] == 12345
    assert _patch(client, up, 12345, BIG[12345:]).json()["complete"] is True


def test_a_cut_mid_piece_keeps_what_arrived(tmp_path):
    """What a killed client looks like from inside the server: the stream raises
    `ClientDisconnect` after some chunks. Those chunks are on disk."""
    async def cut_after_two():
        yield b"a" * 1000
        yield b"b" * 500
        raise ClientDisconnect()

    target = tmp_path / "x.part"
    with pytest.raises(ClientDisconnect):
        asyncio.run(receive_stream(cut_after_two(), target, append=True))
    assert target.read_bytes() == b"a" * 1000 + b"b" * 500


def test_nobody_else_sees_or_touches_your_upload(client, node, be):
    be(ANNA)
    up = _start(client)["upload_id"]
    _patch(client, up, 0, BIG[:100])
    be(DARIO)
    assert client.head(f"/v1/rooms/scavo/uploads/{up}", headers=AUTH).status_code == 404
    assert _patch(client, up, 100, BIG[100:200]).status_code == 404
    assert client.delete(f"/v1/rooms/scavo/uploads/{up}",
                         headers=AUTH).status_code == 404
    be(ANNA)
    assert client.get(f"/v1/rooms/altra/uploads/{up}",
                      headers=AUTH).status_code == 404, "the room is part of it"
    assert client.delete(f"/v1/rooms/scavo/uploads/{up}",
                         headers=AUTH).status_code == 204
    assert client.head(f"/v1/rooms/scavo/uploads/{up}", headers=AUTH).status_code == 404


def test_an_upload_id_is_never_a_path(client, node, be):
    be(ANNA)
    assert client.get("/v1/rooms/scavo/uploads/..%2F..%2Fetc",
                      headers=AUTH).status_code == 404


def test_a_malformed_declared_sha256_is_refused_up_front(client, node, be):
    be(ANNA)
    answer = client.post("/v1/rooms/scavo/uploads", headers=AUTH,
                         json={"size": 10, "sha256": "nope"})
    assert answer.status_code == 422
    assert client.post("/v1/rooms/scavo/uploads", headers=AUTH,
                       json={"size": 0}).status_code == 422
