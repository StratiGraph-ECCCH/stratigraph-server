"""F1 · a file lives in ONE room; «Move here» changes its home, not its bytes.

E.D., 3 October 2026, evening: «un file sta in UNA stanza; se serve altrove si
SPOSTA di stanza (con i diritti della stanza nuova), mai condiviso tra stanze».

Measured before the change (the previous MICRO's open point 1): the same bytes
uploaded through a second room made it «one more home», so a file could be at
home in two rooms at once and every citing room's participants could read it.
What these tests hold:

* the first room the bytes come in through is their home; a later upload
  through another room is no second home, and the answer says where it lives;
* HEAD names the home (`X-EM-Home-Room`) to whoever passed the gates;
* `GET …/asset-home/{ref}` lists the rooms whose graphs cite the file and the
  ones that would hold a reference after the move;
* `POST …/asset-home/{ref}` moves it only with `confirm` and the `from_room`
  the caller saw; after it the home is the new room and ONLY it;
* who may move: owner/admin of the room the file leaves AND editor+ of the
  room it goes to;
* the old room's participants who are not in the new one lose the bytes; the
  uploader keeps reading back what they sent.
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

ANNA = "0000-0002-1825-0097"     # owner of `tempio-a` and `tempio-b`
BRUNO = "0000-0001-5109-3700"    # viewer in `tempio-a` only
CARLA = "0000-0003-1415-9265"    # owner of `sua`, nobody in A or B
ELENA = "0000-0002-9079-593X"    # editor in `tempio-a` and in `tempio-b`

PHOTO = b"\xff\xd8\xff the podium, north face"


def container(room_id, nodes=(), *, owner=ANNA):
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": owner},
            "graphs": {room_id: {"graph_id": room_id, "name": room_id,
                                 "nodes": list(nodes), "edges": []}},
            "active_graph_id": room_id}


def citing(room_id, ref, owner=ANNA):
    return container(room_id, [{"id": "foto", "node_type": "resource",
                                "name": "Foto", "data": {"checksum": ref}}],
                     owner=owner)


@pytest.fixture()
def node(monkeypatch):
    assets = InMemoryAssetStore()
    monkeypatch.setattr(main_module, "ASSET_STORE", assets)
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", InMemoryAssetHomes())
    store = InMemorySnapshotStore()
    acls = InMemoryAclStore()
    acls.put("tempio-a", Acl(owner=ANNA, members={BRUNO: "viewer",
                                                   ELENA: "editor"}).as_dict())
    acls.put("tempio-b", Acl(owner=ANNA, members={ELENA: "editor"}).as_dict())
    acls.put("sua", Acl(owner=CARLA).as_dict())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", RoomRegistry(store))
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    for room, owner in (("tempio-a", ANNA), ("tempio-b", ANNA), ("sua", CARLA)):
        store.put(room, container(room, owner=owner))
    return {"assets": assets, "store": store}


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


AUTH = {"Authorization": "Bearer t"}


def _upload(client, be, who, room, data=PHOTO):
    be(who)
    answer = client.put(f"/v1/rooms/{room}/asset?media_type=image/jpeg",
                        content=data, headers=AUTH)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _get(client, be, who, room, ref, method="GET"):
    be(who)
    return client.request(method, f"/v1/rooms/{room}/asset/{ref}", headers=AUTH)


def _cite_in_a(node, ref):
    node["store"].put("tempio-a", citing("tempio-a", ref))
    ws_module.ROOMS.forget("tempio-a")


def _view(client, be, who, room, ref):
    be(who)
    return client.get(f"/v1/rooms/{room}/asset-home/{ref}", headers=AUTH)


def _move(client, be, who, room, ref, **body):
    be(who)
    return client.post(f"/v1/rooms/{room}/asset-home/{ref}", json=body, headers=AUTH)


def test_the_first_room_is_the_home_and_head_says_so(client, node, be):
    first = _upload(client, be, ANNA, "tempio-a")
    assert first["home"] == "tempio-a"
    ref = first["ref"]
    head = _get(client, be, ANNA, "tempio-b", ref, method="HEAD")
    assert head.status_code == 200, "the uploader reads back through any door"
    assert head.headers["X-EM-Home-Room"] == "tempio-a"
    again = _upload(client, be, ANNA, "tempio-b")
    assert again["home"] == "tempio-a" and again["created"] is False, \
        "sending the bytes through B does not give them a second home"
    assert asset_homes.ASSET_HOMES.home(ref) == "tempio-a"


def test_the_view_lists_the_citing_rooms_before_the_yes(client, node, be):
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    _cite_in_a(node, ref)
    view = _view(client, be, ANNA, "tempio-b", ref)
    assert view.status_code == 200, view.text
    j = view.json()
    assert j["home"] == "tempio-a" and j["here"] is False
    assert [c["room"] for c in j["citing_rooms"]] == ["tempio-a"]
    assert j["citing_rooms"][0]["your_role"] == "owner"
    assert j["references"] == ["tempio-a"], "A will hold a reference after the move"
    assert j["can_move"] is True and j["why_not"] == ""


def test_move_here_changes_the_home_and_nothing_else(client, node, be):
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    _cite_in_a(node, ref)
    assert _get(client, be, BRUNO, "tempio-a", ref).status_code == 200, \
        "before: a viewer of A reads A's file"

    no_yes = _move(client, be, ANNA, "tempio-b", ref, from_room="tempio-a")
    assert no_yes.status_code == 400 and "tempio-a" in no_yes.json()["detail"]
    stale = _move(client, be, ANNA, "tempio-b", ref, from_room="sua", confirm=True)
    assert stale.status_code == 409
    assert asset_homes.ASSET_HOMES.home(ref) == "tempio-a", "refusals move nothing"

    moved = _move(client, be, ANNA, "tempio-b", ref, from_room="tempio-a", confirm=True)
    assert moved.status_code == 200, moved.text
    j = moved.json()
    assert j["moved"] is True and j["previous"] == "tempio-a"
    assert j["home"] == "tempio-b" and j["here"] is True
    assert j["references"] == ["tempio-a"]
    assert node["assets"].count() == 1, "no byte travelled, no second object"
    # NO DOUBLE HOME, on the server's own record
    assert asset_homes.ASSET_HOMES.home(ref) == "tempio-b"
    assert asset_homes.ASSET_HOMES.legacy_homes(ref) == []
    assert [m["to"] for m in asset_homes.ASSET_HOMES.moves(ref)] == ["tempio-b"]

    # A holds a reference now: its viewer, who is not in B, no longer reads it…
    refused = _get(client, be, BRUNO, "tempio-a", ref)
    assert refused.status_code == 403 and "tempio-b" in refused.json()["detail"]
    # …a participant of B does, whichever door they come through…
    assert _get(client, be, ELENA, "tempio-b", ref).status_code == 200
    assert _get(client, be, ELENA, "tempio-a", ref).status_code == 200
    # …and HEAD through A says where the file lives
    head = _get(client, be, ANNA, "tempio-a", ref, method="HEAD")
    assert head.headers["X-EM-Home-Room"] == "tempio-b"


def test_moving_to_the_home_is_a_no_op(client, node, be):
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    same = _move(client, be, ANNA, "tempio-a", ref, from_room="tempio-a", confirm=True)
    assert same.status_code == 200 and same.json()["moved"] is False
    assert asset_homes.ASSET_HOMES.moves(ref) == []


def test_an_upload_after_the_move_does_not_bring_the_home_back(client, node, be):
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    _move(client, be, ANNA, "tempio-b", ref, from_room="tempio-a", confirm=True)
    again = _upload(client, be, ANNA, "tempio-a")
    assert again["home"] == "tempio-b"
    assert asset_homes.ASSET_HOMES.home(ref) == "tempio-b"


def test_only_who_manages_the_old_room_may_take_the_file_out(client, node, be):
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    # ELENA is EDITOR in A — writes there, but does not decide who sees what
    view = _view(client, be, ELENA, "tempio-b", ref).json()
    assert view["can_move"] is False and "owner" in view["why_not"]
    assert _move(client, be, ELENA, "tempio-b", ref, from_room="tempio-a",
                 confirm=True).status_code == 403
    # CARLA cannot even ask where a file she cannot read lives
    assert _view(client, be, CARLA, "sua", ref).status_code == 403
    assert _move(client, be, CARLA, "sua", ref, from_room="tempio-a",
                 confirm=True).status_code == 403
    assert asset_homes.ASSET_HOMES.home(ref) == "tempio-a"


def test_the_room_it_goes_to_needs_an_editor(client, node, be, monkeypatch):
    """ANNA owns A but is only a viewer of `sua`: she may not push files in."""
    ws_module.ACL_STORE.put("sua", Acl(owner=CARLA, members={ANNA: "viewer"}).as_dict())
    ref = _upload(client, be, ANNA, "tempio-a")["ref"]
    view = _view(client, be, ANNA, "sua", ref).json()
    assert view["can_move"] is False and "editor" in view["why_not"]
    assert _move(client, be, ANNA, "sua", ref, from_room="tempio-a",
                 confirm=True).status_code == 403


def test_a_file_from_before_the_rule_is_settled_by_the_move(client, node, be):
    """An entry with two rooms and no home (written by the record before F1):
    no single home is invented; the gate keeps reading both, and a move by
    somebody who manages both settles it."""
    ref = node["assets"].put(PHOTO, "image/jpeg")["ref"]
    record = asset_homes.ASSET_HOMES
    record._save(ref.split(":")[-1], {"rooms": {"tempio-a": [ANNA], "sua": [CARLA]}})
    assert record.home(ref) is None
    assert record.legacy_homes(ref) == ["sua", "tempio-a"]
    assert _get(client, be, BRUNO, "tempio-a", ref).status_code == 200
    view = _view(client, be, ANNA, "tempio-b", ref).json()
    assert view["can_move"] is False and "sua" in view["why_not"]
    record._save(ref.split(":")[-1], {"rooms": {"tempio-a": [ANNA], "tempio-b": []}})
    moved = _move(client, be, ANNA, "tempio-b", ref, from_room=None, confirm=True)
    assert moved.status_code == 200, moved.text
    assert record.home(ref) == "tempio-b"
    assert record.moves(ref)[0]["from_legacy"] == ["tempio-a", "tempio-b"]


def test_the_move_survives_the_process(tmp_path):
    ref = "sha256:" + "cd" * 32
    homes = DirectoryAssetHomes(tmp_path)
    assert homes.record(ref, "tempio-a", ANNA) == "tempio-a"
    assert homes.record(ref, "tempio-b", ANNA) == "tempio-a"
    homes.move(ref, "tempio-b", ANNA, at="2026-10-03T21:00:00+00:00")
    again = DirectoryAssetHomes(tmp_path)
    assert again.home(ref) == "tempio-b"
    assert again.moves(ref)[0]["from"] == "tempio-a"
    assert again.homes(ref) == {"tempio-a": [ANNA], "tempio-b": [ANNA]}
