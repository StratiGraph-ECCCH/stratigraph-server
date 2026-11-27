"""The one door: an object and its story in the same request.

`POST /v1/rooms/{room}/objects` (`app/objects.py`, decision of E.D. 27 November
2026). What these tests defend:

* **a deposit nobody may make costs nothing**: a viewer is refused, and the role
  is read before the body;
* **nothing enters the store before the record holds** — asserted by looking at
  the STORE after a refusal, not at the answer, because an answer can say 422
  while the bytes are already lying there under their digest;
* **the record is first on the wire**: the `dtc` part before the `file` part, so
  that a refusal can one day happen before the body is read at all;
* **one read tells the whole story**: after a deposit the corpus names the file,
  its licence and the act that brought it in — which is the whole point of
  replacing five acts with one;
* **a claim that would be false is refused**: a technique on a retrieval says
  how bytes were made by something that did not make them;
* **the responsible is accredited or nobody**: the person who answers for
  publishing is an iD this node knows, never a string a client typed;
* **a big lot is sent where big lots go**, and the refusal names that door;
* and the **old door says it is deprecated**, in the answer, naming its
  successor and the version that removes it.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import asset_homes                                  # noqa: E402
from app import objects as objects_module                    # noqa: E402
from app import ws as ws_module                              # noqa: E402
from app.access import Acl, InMemoryAclStore                 # noqa: E402
from app.asset_homes import InMemoryAssetHomes               # noqa: E402
from app.corpus import InMemoryCorpusStore, ResidentCorpus   # noqa: E402
from app.rooms import RoomRegistry                           # noqa: E402
from app.store import InMemorySnapshotStore                  # noqa: E402

ANNA = "0000-0002-1825-0097"     # owner
CARLA = "0000-0003-1415-9265"    # editor
BRUNO = "0000-0001-5109-3700"    # viewer

PIXELS = b"\x89PNG\r\n\x1a\n" + b"a stable fake photograph"
HEAD = {"Authorization": "Bearer t"}


def _ref(blob: bytes) -> str:
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def document(room_id: str) -> dict:
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": ANNA},
            "graphs": {room_id: {"graph_id": room_id, "name": room_id,
                                 "nodes": [], "edges": []}},
            "active_graph_id": room_id}


def record(**over) -> dict:
    """A deposit that holds. Each test breaks exactly one thing in it."""
    body = {
        "profile": "em-bucket-dtc/1",
        "formalism": "dtc",
        "object": {"name": "nord.png", "media_type": "image/png"},
        "who": {"author": "Anna Rossi", "author_orcid": ANNA},
        "when": {},
        "source": {"dtc_kind": "ingest"},
        "transformation": {},
        "rights": {"license": "CC-BY-4.0"},
        "target": {"room": "scavo", "lot_name": "Consegna del 27"},
    }
    for block, value in over.items():
        if isinstance(value, dict) and isinstance(body.get(block), dict):
            body[block] = {**body[block], **value}
        else:
            body[block] = value
    return body


@pytest.fixture()
def node(monkeypatch):
    """An empty node with one room, a store nobody else writes to, and a corpus
    that dies with the test."""
    from app.assets import InMemoryAssetStore
    from app import main as main_module

    assets = InMemoryAssetStore()
    monkeypatch.setattr(main_module, "ASSET_STORE", assets)
    corpus = ResidentCorpus(InMemoryCorpusStore())
    monkeypatch.setattr(main_module, "RESIDENT", corpus)
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", InMemoryAssetHomes())

    store = InMemorySnapshotStore()
    store.put("scavo", document("scavo"))
    acls = InMemoryAclStore()
    acls.put("scavo", Acl(owner=ANNA,
                          members={CARLA: "editor", BRUNO: "viewer"}).as_dict())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", RoomRegistry(store))
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    return {"assets": assets, "corpus": corpus}


@pytest.fixture()
def whoever(monkeypatch):
    """Tokens are enforced, and we choose whose they are.

    Patched on BOTH the relay's authenticator and the one `main` holds now:
    `tests/test_auth.py` reloads `app.main`, and a module that reads the door
    through `sys.modules` (this one does, and so does `app/objects.py`) would
    otherwise be talking to a second authenticator — in dev mode, where
    everybody may write and nobody has a name.
    """
    from app import main as main_module

    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    for holder in {id(ws_module.authenticator): ws_module.authenticator,
                   id(main_module.authenticator): main_module.authenticator}.values():
        monkeypatch.setattr(holder, "settings", Enforcing())

    def be(orcid):
        claims = {"orcid": orcid} if orcid else {}
        for holder in {id(ws_module.authenticator): ws_module.authenticator,
                       id(main_module.authenticator): main_module.authenticator}.values():
            monkeypatch.setattr(holder, "verify", lambda token: claims)
            monkeypatch.setattr(holder, "require_token", lambda request: claims)
    return be


@pytest.fixture()
def client():
    """The app as it is NOW — not the one imported when this module was read:
    a reload earlier in the suite leaves those two different objects."""
    from app import main as main_module

    return TestClient(main_module.app)


def deposit(client, body: dict, blob: bytes | None = PIXELS, *, order=("dtc", "file")):
    parts = {"dtc": (None, json.dumps(body), "application/json")}
    if blob is not None:
        parts["file"] = ("nord.png", blob, "image/png")
    ordered = [(name, parts[name]) for name in order if name in parts]
    return client.post("/v1/rooms/scavo/objects", files=ordered, headers=HEAD)


# ── who may ──────────────────────────────────────────────────────────────────

def test_a_viewer_may_not_deposit_and_the_bytes_never_touch_the_store(
        client, node, whoever):
    whoever(BRUNO)
    answer = deposit(client, record())
    assert answer.status_code == 403, answer.text
    assert "editor" in answer.json()["detail"]
    assert node["assets"].head(_ref(PIXELS)) is None, \
        "the role is read before the body: a refused caller costs no disk"


# ── nothing enters before the record holds ───────────────────────────────────

@pytest.mark.parametrize("broken,word", [
    ({"rights": {"license": ""}}, "rights.license"),
    ({"source": {"dtc_kind": ""}}, "source.dtc_kind"),
    ({"source": {"dtc_kind": "fotografia"}}, "vocabulary"),
    ({"object": {"media_type": ""}}, "object.media_type"),
    ({"source": {"dtc_kind": "download"}}, "retrieved_from"),
    ({"source": {"dtc_kind": "photo"}}, "when.made_at"),
    ({"when": {"made_at": "27/11/2026"}}, "when.made_at"),
    ({"target": {"room": "un-altra"}}, "target.room"),
    ({"profile": "em-bucket-dtc/2"}, "em-bucket-dtc/1"),
])
def test_a_record_that_does_not_hold_is_refused_by_name_and_stores_nothing(
        client, node, whoever, broken, word):
    whoever(CARLA)
    answer = deposit(client, record(**broken))
    assert answer.status_code == 422, answer.text
    assert word in answer.json()["detail"], answer.json()["detail"]
    assert node["assets"].head(_ref(PIXELS)) is None, \
        "the refusal left the bytes in the store: the window this door closes"


def test_a_technique_on_a_retrieval_is_a_claim_about_bytes_it_did_not_make(
        client, node, whoever):
    whoever(CARLA)
    answer = deposit(client, record(transformation={"technique": "SfM"}))
    assert answer.status_code == 422
    assert "transformation" in answer.json()["detail"]


def test_the_record_comes_first_on_the_wire(client, node, whoever):
    whoever(CARLA)
    answer = deposit(client, record(), order=("file", "dtc"))
    assert answer.status_code == 400
    assert "`dtc` part comes first" in answer.json()["detail"]


# ── a deposit that holds ─────────────────────────────────────────────────────

def test_one_call_leaves_the_bytes_and_the_whole_story(client, node, whoever):
    whoever(CARLA)
    answer = deposit(client, record(source={"dtc_kind": "photo"},
                                    when={"made_at": "2026-09-14"},
                                    transformation={"technique": "SfM",
                                                    "software": "Metashape 2.1"}))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ref"].startswith("sha256:") and body["created"] is True
    assert body["size"] == len(PIXELS)
    assert body["home"] == "scavo"
    assert node["assets"].head(body["ref"]) is not None

    told = client.get("/v1/corpus", params={"sha256": body["ref"]}, headers=HEAD)
    assert told.status_code == 200, told.text
    story = json.dumps(told.json())
    for said in ("CC-BY-4.0", "photo", "Metashape 2.1", "2026-09-14"):
        assert said in story, f"one read should tell {said!r}: {story[:400]}"


def test_the_same_bytes_twice_are_one_object_and_one_story(client, node, whoever):
    whoever(CARLA)
    first = deposit(client, record())
    second = deposit(client, record())
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["ref"] == second.json()["ref"]
    assert second.json()["created"] is False, "the same bytes are the same object"
    nodes = node["corpus"].read().get("nodes") or []
    resources = [n for n in nodes
                 if (n.get("data") or {}).get("checksum") == first.json()["ref"]]
    assert len(resources) == 1, "the acts are idempotent: a retry doubles nothing"


def test_a_record_alone_describes_bytes_the_node_already_holds(client, node, whoever):
    whoever(CARLA)
    ref = node["assets"].put(PIXELS, "image/png")["ref"]
    answer = client.post("/v1/rooms/scavo/objects", headers=HEAD,
                         json=record(object={"sha256": ref}))
    assert answer.status_code == 200, answer.text
    assert answer.json()["ref"] == ref and answer.json()["created"] is False


def test_a_record_about_bytes_nobody_sent_is_refused(client, node, whoever):
    whoever(CARLA)
    absent = "sha256:" + "0" * 64
    answer = client.post("/v1/rooms/scavo/objects", headers=HEAD,
                         json=record(object={"sha256": absent}))
    assert answer.status_code == 404
    assert "holds no" in answer.json()["detail"]


# ── who answers for publishing ───────────────────────────────────────────────

def test_the_responsible_is_an_accredited_id_or_the_deposit_is_refused(
        client, node, whoever, monkeypatch):
    whoever(CARLA)
    monkeypatch.setattr(objects_module.accredited_module, "is_accredited",
                        lambda orcid, environ=None: orcid == ANNA)

    refused = deposit(client, record(who={"responsible": BRUNO}))
    assert refused.status_code == 422
    assert BRUNO in refused.json()["detail"] and "accredited" in refused.json()["detail"]

    taken = deposit(client, record(who={"responsible": ANNA}))
    assert taken.status_code == 200, taken.text
    assert taken.json()["responsible"] == ANNA
    assert ANNA in json.dumps(node["corpus"].read()), \
        "who answers for the object is written down, not only checked"


def test_without_a_responsible_the_depositor_answers(client, node, whoever):
    whoever(CARLA)
    answer = deposit(client, record())
    assert answer.status_code == 200, answer.text
    assert answer.json()["responsible"] == CARLA


# ── the ceiling ──────────────────────────────────────────────────────────────

def test_a_lot_too_big_for_one_piece_is_sent_to_the_door_that_resumes(
        client, node, whoever, monkeypatch):
    whoever(CARLA)
    monkeypatch.setattr(objects_module, "SINGLE_POST_LIMIT", 16)
    answer = deposit(client, record(), blob=b"x" * 64)
    assert answer.status_code == 413
    assert "/uploads" in answer.json()["detail"], \
        "a refusal that does not say where to go is a dead end"


# ── the old door ─────────────────────────────────────────────────────────────

def test_the_old_door_says_it_is_deprecated_and_names_its_successor(
        client, node, whoever):
    whoever(CARLA)
    answer = client.put("/v1/rooms/scavo/asset", content=PIXELS, headers=HEAD,
                        params={"media_type": "image/png"})
    assert answer.status_code == 200
    assert answer.headers.get("deprecation") == "true"
    assert "/v1/rooms/scavo/objects" in answer.headers.get("link", "")
    assert answer.headers.get("x-em-removed-in") == "1.8"


# ── the profile ──────────────────────────────────────────────────────────────

def test_the_profile_lists_the_kinds_the_datamodel_declares(client, node, whoever):
    whoever(CARLA)
    answer = client.get("/v1/dtc/profile/em-bucket-dtc/1", headers=HEAD)
    assert answer.status_code == 200
    kinds = {k["kind"]: k["family"] for k in answer.json()["acquisition_kinds"]}
    assert kinds.get("photo") == "capture" and kinds.get("download") == "retrieval"
    assert "the token's identity" in answer.json()["the_depositor"]
