"""N2 (E.D., 4 Oct 2026) · the personal node: the files stay in the folders.

T-N2b: on a personal node «Upload to the room» of a file of the EM tree does
not grow the node's storage; the bytes are read back through the reference,
checked; a file outside the tree is refused; a changed file is no longer those
bytes. `/health` says the profile and the sentence the desks show.
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.assets import DirectoryAssetStore, ReferenceAssetStore, asset_store_from_env
from app.main import app

AUTH = {"Authorization": "Bearer t"}


@pytest.fixture()
def personal(tmp_path, monkeypatch):
    root = tmp_path / "Scavo"
    (root / "EM" / "DosCo").mkdir(parents=True)
    photo = root / "EM" / "DosCo" / "D.01.jpg"
    photo.write_bytes(b"\xff\xd8 the north face" * 1000)
    store = ReferenceAssetStore(root, DirectoryAssetStore(tmp_path / "node-assets"))
    monkeypatch.setattr(main_module, "ASSET_STORE", store)
    monkeypatch.setenv("EM_NODE_PROFILE", "personal")
    from app import asset_homes
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", asset_homes.InMemoryAssetHomes())
    return {"root": root, "photo": photo, "store": store, "tmp": tmp_path}


def test_the_store_is_chosen_by_the_profile(tmp_path):
    env = {"EM_NODE_PROFILE": "personal", "EM_PERSONAL_ROOT": str(tmp_path),
           "EM_ASSET_DIR": str(tmp_path / "a")}
    assert isinstance(asset_store_from_env(env), ReferenceAssetStore)
    assert type(asset_store_from_env({"EM_ASSET_DIR": str(tmp_path / "a")})).__name__ == "DirectoryAssetStore"


def test_t_n2b_upload_by_reference_does_not_grow_the_node(personal):
    client = TestClient(app)
    before = personal["store"].stored_bytes()
    digest = hashlib.sha256(personal["photo"].read_bytes()).hexdigest()
    answer = client.post("/v1/rooms/scavo/asset-reference", headers=AUTH,
                         json={"path": str(personal["photo"]), "sha256": f"sha256:{digest}"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["ref"] == f"sha256:{digest}"
    assert personal["store"].stored_bytes() == before == 0
    head = client.head(f"/v1/rooms/scavo/asset/sha256:{digest}", headers=AUTH)
    assert head.status_code == 200
    got = client.get(f"/v1/rooms/scavo/asset/sha256:{digest}", headers=AUTH)
    assert got.status_code == 200 and got.content == personal["photo"].read_bytes()
    # the file changes: it is no longer those bytes
    personal["photo"].write_bytes(b"something else")
    assert client.get(f"/v1/rooms/scavo/asset/sha256:{digest}", headers=AUTH).status_code == 404


def test_outside_the_tree_or_other_bytes_are_refused(personal, tmp_path):
    client = TestClient(app)
    other = tmp_path / "elsewhere.jpg"
    other.write_bytes(b"x")
    assert client.post("/v1/rooms/scavo/asset-reference", headers=AUTH,
                       json={"path": str(other)}).status_code == 403
    assert client.post("/v1/rooms/scavo/asset-reference", headers=AUTH,
                       json={"path": str(personal["photo"]), "sha256": "sha256:" + "0" * 64}
                       ).status_code == 422


def test_a_node_that_keeps_bytes_says_to_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "ASSET_STORE", DirectoryAssetStore(tmp_path / "a"))
    client = TestClient(app)
    assert client.post("/v1/rooms/scavo/asset-reference", headers=AUTH,
                       json={"path": "/x"}).status_code == 409


def test_health_says_the_profile_and_the_sentence(personal):
    h = TestClient(app).get("/health").json()
    assert h["profile"] == "personal"
    assert "backed-up disk" in h["custody"]
