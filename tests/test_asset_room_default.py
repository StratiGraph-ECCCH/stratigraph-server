"""D-C · an asset nobody has published is for the people of its room.

Decided by E.D. on 3 October 2026 («visibile solo alla stanza»), and measured
the same day on the dev node before anything changed:

    dev  PUT  /v1/rooms/dc-measure-2026-10-03/asset         → 200
    viewer (member of nothing) GET …/asset/sha256:352e…    → 200   ← the hole
    no token                   GET …/asset/sha256:352e…    → 401   (the router)

A digest travels in manifests and documents; serving its bytes to any token was
publication by default. What these tests hold:

* bytes with **no licence declared** anywhere are refused (403) to an
  authenticated stranger and served to every participant of their room, viewer
  included — whether the graph cites them yet or not;
* **the uploader** reads back what they sent; going through ANOTHER room — even
  one the stranger owns — does not open them;
* a **declared licence** publishes them: served to any token, as before;
* a **public** study's room keeps its files public (`role_of` gives everybody
  `viewer` there — one rule, not a second one in the gate);
* bytes with no known home (uploaded before the record existed, cited by
  nothing) belong to the room the request came through;
* HEAD answers what GET answers: the «do you have it?» question does not leak
  the bytes' size to somebody refused the bytes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import asset_homes                              # noqa: E402
from app import main as main_module                      # noqa: E402
from app import ws as ws_module                          # noqa: E402
from app.access import Acl, InMemoryAclStore             # noqa: E402
from app.asset_homes import DirectoryAssetHomes, InMemoryAssetHomes  # noqa: E402
from app.assets import InMemoryAssetStore                # noqa: E402
from app.main import app                                 # noqa: E402
from app.rooms import RoomRegistry                       # noqa: E402
from app.store import InMemorySnapshotStore              # noqa: E402

ANNA = "0000-0002-1825-0097"     # owner of `scavo`
BRUNO = "0000-0001-5109-3700"    # viewer in `scavo`
CARLA = "0000-0003-1415-9265"    # nobody in `scavo`; owner of `sua`
DARIO = "0000-0002-9079-593X"    # nobody anywhere

PHOTO = b"\xff\xd8\xff raw photo of the north section"
NOTE = b"a document the graph cites with no rights"
OLD = b"bytes from before the record existed"


def container(room_id: str, nodes=(), edges=(), *, owner=ANNA,
              visibility="restricted") -> dict:
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": visibility, "owner": owner},
            "graphs": {room_id: {"graph_id": room_id, "name": room_id,
                                 "nodes": list(nodes), "edges": list(edges)}},
            "active_graph_id": room_id}


@pytest.fixture()
def node(monkeypatch):
    assets = InMemoryAssetStore()
    monkeypatch.setattr(main_module, "ASSET_STORE", assets)
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", InMemoryAssetHomes())
    store = InMemorySnapshotStore()
    acls = InMemoryAclStore()
    acls.put("scavo", Acl(owner=ANNA, members={BRUNO: "viewer"}).as_dict())
    acls.put("sua", Acl(owner=CARLA).as_dict())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", RoomRegistry(store))
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    store.put("scavo", container("scavo"))
    store.put("sua", container("sua", owner=CARLA))
    return {"assets": assets, "store": store}


@pytest.fixture()
def be(monkeypatch):
    """Enforcing, and the token is whoever we say — on BOTH modules (see
    `test_rooms_register.py::enforcing` for the reload hazard this avoids)."""
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


AUTH = {"Authorization": "Bearer t"}


def _upload(client, be, who, room, data, media="image/jpeg"):
    be(who)
    answer = client.put(f"/v1/rooms/{room}/asset?media_type={media}",
                        content=data, headers=AUTH)
    assert answer.status_code == 200, answer.text
    return answer.json()["ref"]


def _get(client, be, who, room, ref, method="GET"):
    be(who)
    return client.request(method, f"/v1/rooms/{room}/asset/{ref}", headers=AUTH)


def test_uploaded_bytes_are_for_the_room_and_not_for_any_token(client, node, be):
    """The measured hole, closed: uploaded and not cited yet — the state of every
    file in the middle of «Porta in una stanza…»."""
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    refused = _get(client, be, DARIO, "scavo", ref)
    assert refused.status_code == 403
    assert "scavo" in refused.json()["detail"], "the refusal names the room to ask"
    assert _get(client, be, BRUNO, "scavo", ref).status_code == 200, \
        "a viewer is a participant: «any role» means viewer too"
    assert _get(client, be, ANNA, "scavo", ref).content == PHOTO


def test_head_refuses_what_get_refuses(client, node, be):
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    head = _get(client, be, DARIO, "scavo", ref, method="HEAD")
    assert head.status_code == 403
    assert head.headers.get("content-length") != str(len(PHOTO))
    assert _get(client, be, BRUNO, "scavo", ref, method="HEAD").status_code == 200


def test_another_room_is_not_a_way_around_it(client, node, be):
    """CARLA owns `sua`; naming it in the URL does not make ANNA's photo hers."""
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    assert _get(client, be, CARLA, "sua", ref).status_code == 403
    assert _get(client, be, CARLA, "stanza-inventata", ref).status_code == 403


def test_the_uploader_reads_back_what_they_sent(client, node, be):
    """DARIO is in no room, uploads through a name nobody ever opened (what
    `smoke.py` does): his own bytes come back to him, and to nobody else."""
    ref = _upload(client, be, DARIO, "mai-aperta", OLD + b"!")
    assert _get(client, be, DARIO, "mai-aperta", ref).status_code == 200
    assert _get(client, be, CARLA, "mai-aperta", ref).status_code == 403


def test_a_cited_asset_with_no_licence_is_still_the_rooms(client, node, be):
    ref = _upload(client, be, ANNA, "scavo", NOTE, "text/plain")
    node["store"].put("scavo", container("scavo", nodes=[
        {"id": "nota", "node_type": "resource", "name": "Nota",
         "data": {"checksum": ref}}]))
    ws_module.ROOMS.forget("scavo")
    assert _get(client, be, DARIO, "scavo", ref).status_code == 403
    assert _get(client, be, BRUNO, "scavo", ref).status_code == 200


def test_a_declared_licence_publishes_the_bytes(client, node, be):
    """The licence is the act of publishing: from then on any token reads it,
    and the licence travels in the header as before."""
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    node["store"].put("scavo", container("scavo", nodes=[
        {"id": "foto", "node_type": "resource", "name": "Foto",
         "data": {"checksum": ref}},
        {"id": "lic", "node_type": "license", "name": "CC-BY-4.0",
         "data": {"license_type": "CC-BY-4.0"}}],
        edges=[{"id": "e", "source": "foto", "target": "lic",
                "edge_type": "has_license"}]))
    ws_module.ROOMS.forget("scavo")
    served = _get(client, be, DARIO, "scavo", ref)
    assert served.status_code == 200 and served.content == PHOTO
    assert served.headers["X-EM-License"] == "CC-BY-4.0"
    # …and through any door: the bytes are published, not the room
    assert _get(client, be, CARLA, "sua", ref).status_code == 200


def test_a_public_study_keeps_its_files_public(client, node, be):
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    node["store"].put("scavo", container("scavo", visibility="public"))
    ws_module.ROOMS.forget("scavo")
    assert _get(client, be, DARIO, "scavo", ref).status_code == 200


def test_bytes_with_no_known_home_belong_to_the_door(client, node, be):
    """Uploaded before the record existed and cited by nothing: the room the
    request came through is the only home anybody can name."""
    ref = node["assets"].put(OLD, "application/octet-stream")["ref"]
    assert _get(client, be, BRUNO, "scavo", ref).status_code == 200
    assert _get(client, be, DARIO, "scavo", ref).status_code == 403
    assert _get(client, be, DARIO, "invented", ref).status_code == 403, \
        "an invented room grants nothing: no bootstrap on the way to a file"


def test_dedup_does_not_make_a_second_home(client, node, be):
    """CARLA uploads the same bytes into `sua`: she has proved she holds them
    and reads them back — but `sua` is NOT a second home (F1, E.D. 3 Oct
    evening: one file, one room). The answer says where the file lives."""
    ref = _upload(client, be, ANNA, "scavo", PHOTO)
    be(CARLA)
    again = client.put("/v1/rooms/sua/asset?media_type=image/jpeg",
                       content=PHOTO, headers=AUTH).json()
    assert again["ref"] == ref and node["assets"].count() == 1
    assert again["home"] == "scavo" and again["created"] is False
    assert _get(client, be, CARLA, "sua", ref).status_code == 200
    assert asset_homes.ASSET_HOMES.home(ref) == "scavo"
    assert set(asset_homes.ASSET_HOMES.homes(ref)) == {"scavo", "sua"}, \
        "who uploaded through which room is still remembered"


def test_the_record_of_homes_survives_the_process(tmp_path):
    homes = DirectoryAssetHomes(tmp_path)
    ref = "sha256:" + "ab" * 32
    homes.record(ref, "scavo", ANNA)
    homes.record(ref, "scavo", ANNA)            # idempotent
    homes.record(ref, "sua", None)              # dev mode: a room, nobody named
    again = DirectoryAssetHomes(tmp_path).homes(ref)
    assert again == {"scavo": [ANNA], "sua": []}
    assert DirectoryAssetHomes(tmp_path).home(ref) == "scavo"
    assert DirectoryAssetHomes(tmp_path).homes("not-a-digest") == {}
