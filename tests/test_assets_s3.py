"""`S3AssetStore` against a REAL S3 endpoint — the deployment store, exercised.

Not a mock we wrote: what can go wrong in this class is the S3 client's own
behaviour against a server (how a missing key is reported, whether a HEAD costs a
download, what `ContentType` survives a round trip, whether a ranged GET sends the
range), and a fake of our own would agree with whatever we assumed. So these
tests talk to an S3 server: the RustFS of the dev stack, or any S3-compatible
endpoint you point them at.

    # the dev stack's object store up (dev-stack/README-DEV.md), then simply:
    pytest tests/test_assets_s3.py
    # …or anywhere else:
    EM_TEST_S3_ENDPOINT=http://host:9000 \\
    EM_TEST_S3_ACCESS_KEY=… EM_TEST_S3_SECRET_KEY=… pytest tests/test_assets_s3.py

`EM_TEST_S3_*`, like `EM_TEST_PG_*` in `conftest.py`, and NOT the node's own
`EM_ASSET_S3_*`: those would configure the stores every other test module
builds at import, and two of four is a half-configured store the node rightly
refuses. Without them the keys are read from `dev-stack/.env.dev`
(`RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY`) — the dev stack's own, the ones it
gives StratiGraph Server. There is **no default key**: a test that falls back to
a well-known vendor password measures a store nobody should be running. The
endpoint defaults to `http://localhost:<RUSTFS_API_PORT or 9000>`.

They **skip** — loudly, with the reason — when the credentials are not given,
when nothing answers at the endpoint, or when `boto3` is not installed, so the
suite stays runnable on a machine with no Docker. A skip here means "not
measured", never "passed".

Every test works in a bucket of its own (see the fixture), and the bucket goes
away afterwards: the store's own bucket is never written.
"""

from __future__ import annotations

import os
import pathlib
import socket
import sys
import uuid
from urllib.parse import urlsplit

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))



def _env_dev() -> dict:
    """`dev-stack/.env.dev` as KEY=value, or {} — it is gitignored, and absent
    on a machine without the stack."""
    out = {}
    try:
        text = (_REPO / "dev-stack" / ".env.dev").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            out[key.strip()] = value.strip()
    return out


_DEV = _env_dev()
ENDPOINT = (os.environ.get("EM_TEST_S3_ENDPOINT")
            or f"http://localhost:{_DEV.get('RUSTFS_API_PORT') or '9000'}")
ACCESS_KEY = (os.environ.get("EM_TEST_S3_ACCESS_KEY")
              or _DEV.get("RUSTFS_ACCESS_KEY") or "")
SECRET_KEY = (os.environ.get("EM_TEST_S3_SECRET_KEY")
              or _DEV.get("RUSTFS_SECRET_KEY") or "")
SECURE = ENDPOINT.startswith("https://")

pytest.importorskip("boto3", reason="the `boto3` client is not installed "
                                    "(pip install StratiGraph Server[s3])")

if not (ACCESS_KEY and SECRET_KEY):
    pytest.skip("no S3 keys: neither EM_TEST_S3_ACCESS_KEY / _SECRET_KEY nor "
                "RUSTFS_* in dev-stack/.env.dev — there is no default key on "
                "purpose", allow_module_level=True)


def _reachable() -> bool:
    parts = urlsplit(ENDPOINT if "://" in ENDPOINT else f"http://{ENDPOINT}")
    try:
        with socket.create_connection(
                (parts.hostname, parts.port or (443 if SECURE else 80)),
                timeout=1.5):
            return True
    except OSError:
        return False


if not _reachable():
    pytest.skip(f"nothing answers at {ENDPOINT} — start the dev stack's object "
                f"store (dev-stack/README-DEV.md) to measure this",
                allow_module_level=True)


from app import s3client  # noqa: E402
from app.assets import S3AssetStore, content_id  # noqa: E402
from app.blend_backups import BACKUP_PREFIX, S3BackupBlobs, digest_of  # noqa: E402
from app.corpus import S3CorpusStore  # noqa: E402


@pytest.fixture()
def store():
    """A store on a bucket of its own, removed afterwards.

    Its own bucket because these tests write, and a test that leaves objects in
    the bucket the dev stack uses would make the next run's dedup assertions
    depend on the previous run.
    """
    bucket = f"em-test-{uuid.uuid4().hex[:10]}"
    store = S3AssetStore(endpoint=ENDPOINT, access_key=ACCESS_KEY,
                         secret_key=SECRET_KEY, bucket=bucket, secure=SECURE)
    try:
        yield store
    finally:
        client = store._client
        for obj in list(s3client.iter_objects(client, bucket)):
            client.delete_object(Bucket=bucket, Key=obj["key"])
        client.delete_bucket(Bucket=bucket)


def _keys(store) -> list:
    return [o["key"] for o in s3client.iter_objects(store._client, store.bucket)]


# ── the interface, against the real thing ───────────────────────────────────

def test_put_then_get_is_byte_exact(store):
    payload = b"\x00\x01glTF binary-ish bytes\xff" * 64
    info = store.put(payload, "model/gltf-binary")
    assert info["created"] is True
    assert store.get(info["ref"]) == payload


def test_the_object_key_is_the_digest(store):
    payload = b"the key is the content"
    info = store.put(payload, "text/plain")
    assert info["ref"] == content_id(payload)
    # …and the object really is under that name in the bucket
    key = info["ref"].split(":", 1)[1]
    stat = store._client.head_object(Bucket=store.bucket, Key=key)
    assert stat["ContentLength"] == len(payload)


def test_the_same_bytes_twice_are_one_object(store):
    payload = b"dedup is a property of the naming, not of a check"
    first, second = store.put(payload, "text/plain"), store.put(payload, "text/plain")
    assert first["ref"] == second["ref"]
    assert second["created"] is False
    assert len(_keys(store)) == 1


def test_head_answers_without_downloading(store):
    """A hundred-megabyte asset must not have to travel to answer "is it there"."""
    payload = b"x" * 100_000
    info = store.put(payload, "image/png")
    meta = store.head(info["ref"])
    assert meta["size"] == len(payload)
    assert meta["media_type"] == "image/png"
    assert meta["sha256"] == info["sha256"]


def test_a_range_is_an_s3_ranged_get(store):
    """`read_range` (2026-10-24, for HTTP Range on `get_asset`): the bytes
    asked, and the tail a `.3tz` reader asks for first — from the server."""
    payload = bytes(range(256)) * 400
    info = store.put(payload, "application/vnd.3tz")
    assert store.read_range(info["ref"], 1000, 100) == payload[1000:1100]
    assert store.read_range(info["ref"], len(payload) - 22, 22) == payload[-22:]
    assert store.read_range(info["ref"], 0, 1) == payload[:1]
    # an empty interval is nothing, not the whole tail of the object
    assert store.read_range(info["ref"], 5, 0) == b""


def test_a_reference_nobody_stored_is_absent_not_an_error(store):
    missing = "sha256:" + "0" * 64
    assert store.get(missing) is None
    assert store.head(missing) is None
    assert store.read_range(missing, 0, 1) is None
    assert store.read_range(missing, 0, 0) is None


def test_two_different_contents_are_two_objects(store):
    a = store.put(b"one", "text/plain")
    b = store.put(b"two", "text/plain")
    assert a["ref"] != b["ref"]
    assert store.get(a["ref"]) == b"one" and store.get(b["ref"]) == b"two"


def test_put_file_is_a_multipart_upload_and_keeps_its_type(store, tmp_path):
    """The streamed upload door (`put_file`): a file larger than one part, so
    the multipart path is the one measured — and the type it was given is the
    type a HEAD reads back. Twice is still once."""
    import hashlib

    payload = os.urandom(9 * 1024 * 1024 + 123)        # > the 8 MiB part size
    path = tmp_path / "big.glb"
    path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()

    info = store.put_file(path, sha, len(payload), "model/gltf-binary")
    assert info == {"ref": f"sha256:{sha}", "sha256": sha,
                    "media_type": "model/gltf-binary", "size": len(payload),
                    "created": True}
    assert store.head(info["ref"])["media_type"] == "model/gltf-binary"
    assert store.head(info["ref"])["size"] == len(payload)
    assert store.read_range(info["ref"], 8 * 1024 * 1024 - 5, 10) == \
        payload[8 * 1024 * 1024 - 5: 8 * 1024 * 1024 + 5], "across the part seam"
    assert store.put_file(path, sha, len(payload),
                          "model/gltf-binary")["created"] is False
    assert _keys(store) == [sha]


def test_delete_says_what_it_did_and_is_idempotent(store):
    info = store.put(b"to be forgotten", "text/plain")
    assert store.delete(info["ref"]) == {"ref": info["ref"], "removed": True}
    assert store.get(info["ref"]) is None
    assert store.delete(info["ref"]) == {"ref": info["ref"], "removed": False}
    assert _keys(store) == []


def test_ensuring_the_bucket_twice_is_not_an_error(store):
    """Two processes starting together both build the store: the second must
    not refuse to start for a bucket the first just made."""
    again = S3AssetStore(endpoint=ENDPOINT, access_key=ACCESS_KEY,
                         secret_key=SECRET_KEY, bucket=store.bucket, secure=SECURE)
    assert again.bucket == store.bucket


# ── the other two S3 stores on the same client ──────────────────────────────

def test_the_backups_live_under_their_prefix_and_round_trip(store):
    blobs = S3BackupBlobs(ENDPOINT, ACCESS_KEY, SECRET_KEY, store.bucket,
                          secure=SECURE)
    blend = b"BLENDER-v300" + os.urandom(2048)
    first = blobs.put(blend)
    assert first == {"sha256": digest_of(blend), "size": len(blend),
                     "created": True}
    assert blobs.put(blend)["created"] is False
    assert blobs.get(first["sha256"]) == blend
    assert blobs.head(first["sha256"]) == {"sha256": first["sha256"],
                                           "size": len(blend)}
    assert _keys(store) == [f"{BACKUP_PREFIX}{first['sha256']}"]
    head = store._client.head_object(Bucket=store.bucket,
                                     Key=f"{BACKUP_PREFIX}{first['sha256']}")
    assert head["ContentType"] == "application/x-blender"
    # …and an asset with the same digest is NOT this backup
    assert store.get(f"sha256:{first['sha256']}") is None
    assert blobs.get("0" * 64) is None and blobs.head("0" * 64) is None
    assert blobs.get("not a digest") is None


def test_the_corpus_is_one_replaceable_object(store):
    corpus = S3CorpusStore(ENDPOINT, ACCESS_KEY, SECRET_KEY, store.bucket,
                           secure=SECURE)
    assert corpus.get() is None, "no corpus yet is None, not an error"
    corpus.put({"graph_id": "dtc", "nodes": [{"id": "è"}], "edges": []})
    corpus.put({"graph_id": "dtc", "nodes": [], "edges": []})
    assert corpus.get() == {"graph_id": "dtc", "nodes": [], "edges": []}
    assert _keys(store) == [S3CorpusStore.OBJECT_KEY]
    head = store._client.head_object(Bucket=store.bucket,
                                     Key=S3CorpusStore.OBJECT_KEY)
    assert head["ContentType"] == "application/json"


def test_the_s3_snapshot_store_still_refuses_with_a_sentence():
    """Declared, not wired: a deployment keeps its snapshots in Postgres."""
    from app.store import S3SnapshotStore

    with pytest.raises(NotImplementedError, match="S3 snapshot store"):
        S3SnapshotStore(ENDPOINT, ACCESS_KEY, SECRET_KEY, "em-snapshots")


# ── refusing what it cannot honour ──────────────────────────────────────────

def test_a_store_that_cannot_reach_its_bucket_refuses_to_be_built():
    """At construction, with a sentence — not at the first upload, from inside
    somebody's request."""
    with pytest.raises(RuntimeError) as exc:
        S3AssetStore(endpoint="http://127.0.0.1:1", access_key="k",
                     secret_key="s", bucket="nowhere", secure=False)
    assert "127.0.0.1:1" in str(exc.value)
    assert "did not answer" in str(exc.value)


def test_wrong_credentials_are_a_startup_failure_too(store):
    with pytest.raises(RuntimeError) as exc:
        S3AssetStore(endpoint=ENDPOINT, access_key="not-the-key",
                     secret_key="not-the-secret", bucket=store.bucket,
                     secure=SECURE)
    message = str(exc.value)
    assert store.bucket in message
    assert "credentials" in message      # names the likely cause, not a code
