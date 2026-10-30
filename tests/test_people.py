"""The people of a node: profiles, the console's register, passwords, rescue.

Decided by E.D. on 30 October 2026 (`app/people.py`):

* a person starts as a USER; creating a room or a group needs the NODE EDITOR
  profile (`creator`) or SUPER;
* people are added by ORCID, with the profile chosen explicitly;
* the field password is given only to an iD ORCID verified once — or to a test
  person on a node that allows them;
* inside a room the super-administrator counts for the role held there; the one
  exception is a room nobody can manage any more, which can be handed over.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import asset_homes as homes_module                 # noqa: E402
from app import keycloak_admin                               # noqa: E402
from app import main as main_module                          # noqa: E402
from app import operators as ops                             # noqa: E402
from app import people as people_module                      # noqa: E402
from app import ws as ws_module                              # noqa: E402
from app.access import Acl, InMemoryAclStore, InMemoryGroupStore, Role  # noqa: E402
from app.assets import InMemoryAssetStore                    # noqa: E402
from app.invites import InMemoryInviteStore                  # noqa: E402
from app.main import app                                     # noqa: E402
from app.rooms import RoomRegistry                           # noqa: E402
from app.store import InMemoryRoomStore, InMemorySnapshotStore  # noqa: E402

ANNA = "0000-0002-1825-0097"     # an ordinary person
BRUNO = "0000-0001-5109-3700"    # the node's operator (EM_OPERATORS)
CARLA = "0000-0002-9079-593X"    # somebody the console adds
AUTH = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def instance(monkeypatch):
    snapshots = InMemorySnapshotStore()
    registry = RoomRegistry(snapshots, InMemoryRoomStore())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", snapshots)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", InMemoryAclStore())
    monkeypatch.setattr(main_module, "ACL_STORE", ws_module.ACL_STORE)
    monkeypatch.setattr(ws_module, "GROUP_STORE", InMemoryGroupStore())
    monkeypatch.setattr(main_module, "INVITE_STORE", InMemoryInviteStore())
    monkeypatch.setattr(people_module, "PEOPLE_STORE", people_module.InMemoryPeopleStore())
    monkeypatch.setattr(people_module, "_MEMORY_LOG", [])
    monkeypatch.setenv("EM_CREATE_POLICY", "editors")
    monkeypatch.delenv("EM_ALLOW_TEST_PEOPLE", raising=False)
    monkeypatch.setenv("EM_OPERATORS", BRUNO)
    monkeypatch.delenv("EM_ACCREDITED_FILE", raising=False)
    for name in ("EM_KC_ADMIN_URL", "EM_KC_REALM", "EM_KC_ADMIN_USER", "EM_KC_ADMIN_PASSWORD",
                 "EM_KC_ADMIN_CLIENT_ID", "EM_KC_ADMIN_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    return registry


@pytest.fixture
def be(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    for module in (ws_module, main_module):
        monkeypatch.setattr(module.authenticator, "settings", Enforcing())

    def as_(orcid, **extra):
        claims = ({"orcid": orcid} if orcid else {})
        claims.update(extra)
        for module in (ws_module, main_module):
            monkeypatch.setattr(module.authenticator, "verify", lambda token: dict(claims))
    return as_


@pytest.fixture
def client():
    return TestClient(app)


# ── who may create ───────────────────────────────────────────────────────────

def test_a_USER_cannot_create_a_room_and_is_told_why(be, client):
    be(ANNA)
    answer = client.post("/v1/rooms", json={"room_id": "scavo"}, headers=AUTH)
    assert answer.status_code == 403
    assert "node editor" in answer.json()["detail"]


def test_a_NODE_EDITOR_creates_a_room_and_owns_it(be, client):
    people_module.registry().put(people_module.Person(ANNA, "Anna", "creator"))
    be(ANNA)
    answer = client.post("/v1/rooms", json={"room_id": "scavo"}, headers=AUTH)
    assert answer.status_code == 201, answer.text
    assert answer.json()["owner"] == ANNA


def test_the_realm_role_em_creator_also_makes_an_editor(be, client):
    be(ANNA, realm_access={"roles": ["em-creator"]})
    assert client.post("/v1/rooms", json={"room_id": "scavo"}, headers=AUTH).status_code == 201


def test_the_operator_creates_rooms(be, client):
    be(BRUNO)
    assert client.post("/v1/rooms", json={"room_id": "scavo"}, headers=AUTH).status_code == 201


def test_the_policy_ANYONE_keeps_the_old_behaviour(be, client, monkeypatch):
    monkeypatch.setenv("EM_CREATE_POLICY", "anyone")
    be(ANNA)
    assert client.post("/v1/rooms", json={"room_id": "scavo"}, headers=AUTH).status_code == 201


def test_a_typo_in_the_policy_closes_the_door():
    assert people_module.create_policy({"EM_CREATE_POLICY": "anybody"}) == "editors"


def test_a_USER_cannot_create_a_group_but_an_editor_can(be, client):
    be(ANNA)
    body = {"id": "squadra", "name": "Squadra", "members": [ANNA]}
    assert client.put("/v1/groups/squadra", json=body, headers=AUTH).status_code == 403
    people_module.registry().put(people_module.Person(ANNA, "Anna", "creator"))
    assert client.put("/v1/groups/squadra", json=body, headers=AUTH).status_code == 200


# ── the register ─────────────────────────────────────────────────────────────

def test_a_person_is_added_by_ORCID_and_starts_as_a_user(be, client):
    be(BRUNO)
    answer = client.put(f"/v1/admin/people/{CARLA}", json={"name": "Carla"}, headers=AUTH)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["profile"] == "user" and body["registered"] is True
    assert any("Keycloak is not reachable" in n for n in body["notes"])


def test_an_iD_with_a_wrong_check_digit_is_refused(be, client):
    be(BRUNO)
    answer = client.put("/v1/admin/people/0000-0002-1825-0098", json={}, headers=AUTH)
    assert answer.status_code == 400


def test_TEST_iDs_only_where_the_node_allows_test_people(be, client, monkeypatch):
    be(BRUNO)
    test_id = people_module.test_orcid(7)
    assert people_module.is_test_orcid(test_id)
    assert client.put(f"/v1/admin/people/{test_id}", json={}, headers=AUTH).status_code == 400
    monkeypatch.setenv("EM_ALLOW_TEST_PEOPLE", "1")
    answer = client.put(f"/v1/admin/people/{test_id}", json={"name": "Prova Sette"}, headers=AUTH)
    assert answer.status_code == 200 and answer.json()["test"] is True


def test_the_test_iD_generator_writes_valid_check_digits():
    from app.accredited import check_digit_ok
    assert all(check_digit_ok(people_module.test_orcid(n)) for n in range(1, 60))


def test_a_USER_cannot_reach_the_register(be, client):
    be(ANNA)
    assert client.get("/v1/admin/people", headers=AUTH).status_code == 403
    assert client.put(f"/v1/admin/people/{ANNA}", json={"profile": "super"},
                      headers=AUTH).status_code == 403


def test_a_super_in_the_register_is_an_operator_of_the_node(be, client):
    people_module.registry().put(people_module.Person(CARLA, "Carla", "super"))
    assert ops.is_operator({"orcid": CARLA}) is True
    be(CARLA)
    assert client.get("/v1/admin/people", headers=AUTH).status_code == 200


def test_nobody_changes_their_OWN_profile(be, client):
    people_module.registry().put(people_module.Person(CARLA, "Carla", "super"))
    be(CARLA)
    answer = client.put(f"/v1/admin/people/{CARLA}", json={"profile": "user"}, headers=AUTH)
    assert answer.status_code == 403
    assert "never self-granted" in answer.json()["detail"]


def test_the_LAST_super_cannot_be_demoted(be, client, monkeypatch):
    monkeypatch.setenv("EM_OPERATORS", "")
    reg = people_module.registry()
    reg.put(people_module.Person(CARLA, "Carla", "super"))
    reg.put(people_module.Person(ANNA, "Anna", "super"))
    be(ANNA)
    assert client.put(f"/v1/admin/people/{CARLA}", json={"profile": "creator"},
                      headers=AUTH).status_code == 200
    be(CARLA)
    # Carla is now a creator, not an operator: she cannot touch the register
    assert client.put(f"/v1/admin/people/{ANNA}", json={"profile": "user"},
                      headers=AUTH).status_code == 403
    assert people_module._RANK  # Anna stays the only super
    assert reg.get(ANNA).profile == "super"


def test_a_profile_fixed_by_the_deployment_is_not_changed_here(be, client):
    people_module.registry().put(people_module.Person(CARLA, "Carla", "super"))
    be(CARLA)
    answer = client.put(f"/v1/admin/people/{BRUNO}", json={"profile": "user"}, headers=AUTH)
    assert answer.status_code == 409


def test_the_list_holds_the_register_the_operators_and_the_room_members(be, client):
    ws_module.ACL_STORE.put("scavo", Acl(owner=ANNA, members={CARLA: "editor"}).as_dict())
    be(BRUNO)
    body = client.get("/v1/admin/people", headers=AUTH).json()
    seen = {p["orcid"]: p for p in body["people"]}
    assert {ANNA, BRUNO, CARLA} <= set(seen)
    assert seen[BRUNO]["profile"] == "super" and seen[BRUNO]["profile_source"] == "deployment"
    assert seen[ANNA]["rooms_owned"] == ["scavo"]
    assert body["create_policy"] == "editors"


def test_taking_somebody_off_the_node(be, client):
    ws_module.ACL_STORE.put("scavo", Acl(owner=ANNA, members={CARLA: "editor"}).as_dict())
    ws_module.ACL_STORE.put("mostra", Acl(owner=CARLA).as_dict())
    ws_module.groups().put(main_module.Group("squadra", "Squadra", [CARLA, ANNA], owner=ANNA))
    be(BRUNO)
    answer = client.delete(f"/v1/admin/people/{CARLA}", headers=AUTH)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["rooms_left"] == ["scavo"] and body["rooms_owned"] == ["mostra"]
    assert body["groups_left"] == ["squadra"]
    assert CARLA not in ws_module.load_acl("scavo").members
    assert not ws_module.groups().get("squadra").has(CARLA)


def test_nobody_takes_THEMSELVES_off(be, client):
    people_module.registry().put(people_module.Person(CARLA, "Carla", "super"))
    be(CARLA)
    assert client.delete(f"/v1/admin/people/{CARLA}", headers=AUTH).status_code == 403


# ── passwords for the field ──────────────────────────────────────────────────

class FakeKeycloak:
    def __init__(self, linked=True):
        self.linked = linked
        self.users = {}
        self.passwords = {}

    def configured(self):
        return True

    def describe(self):
        return "fake"

    def user(self, orcid):
        return self.users.get(orcid)

    def ensure_user(self, orcid, name="", *, test=False):
        created = orcid not in self.users
        self.users.setdefault(orcid, {"id": "id-" + orcid, "username": orcid, "enabled": True})
        return {"id": self.users[orcid]["id"], "created": created}

    def linked_to_orcid(self, user_id):
        return self.linked

    def set_password(self, user_id, password, *, temporary=True):
        self.passwords[user_id] = (password, temporary)

    def set_enabled(self, orcid, enabled):
        if orcid in self.users:
            self.users[orcid]["enabled"] = enabled
            return True
        return False

    def facts(self, orcid):
        u = self.users.get(orcid)
        return {"exists": u is not None, "enabled": (u or {}).get("enabled"),
                "orcid_linked": self.linked if u else None, "password": None}


@pytest.fixture
def kc(monkeypatch):
    fake = FakeKeycloak()
    monkeypatch.setattr(keycloak_admin, "admin", lambda environ=None: fake)
    return fake


def test_adding_a_person_creates_the_account(be, client, kc):
    be(BRUNO)
    body = client.put(f"/v1/admin/people/{CARLA}", json={"name": "Carla"}, headers=AUTH).json()
    assert CARLA in kc.users and "account created in Keycloak" in body["notes"]


def test_a_password_for_an_iD_ORCID_verified(be, client, kc):
    kc.ensure_user(CARLA)
    be(BRUNO)
    answer = client.post(f"/v1/admin/people/{CARLA}/password",
                         json={"password": "tempio-grande-1"}, headers=AUTH)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"orcid": CARLA, "password": "set", "temporary": True}
    assert kc.passwords["id-" + CARLA] == ("tempio-grande-1", True)
    # never written to the log
    assert all("tempio" not in str(e) for e in people_module.read_log())


def test_NO_password_for_an_iD_ORCID_never_verified(be, client, kc):
    kc.linked = False
    kc.ensure_user(CARLA)
    be(BRUNO)
    answer = client.post(f"/v1/admin/people/{CARLA}/password",
                         json={"password": "tempio-grande-1"}, headers=AUTH)
    assert answer.status_code == 409
    assert "never signed in with ORCID" in answer.json()["detail"]


def test_a_TEST_person_gets_a_password_where_test_people_are_allowed(be, client, kc, monkeypatch):
    monkeypatch.setenv("EM_ALLOW_TEST_PEOPLE", "1")
    kc.linked = False
    test_id = people_module.test_orcid(3)
    kc.ensure_user(test_id)
    be(BRUNO)
    assert client.post(f"/v1/admin/people/{test_id}/password",
                       json={"password": "prova-prova"}, headers=AUTH).status_code == 200


def test_a_short_password_is_refused_and_an_unknown_person_is_404(be, client, kc):
    be(BRUNO)
    assert client.post(f"/v1/admin/people/{CARLA}/password", json={"password": "corta"},
                       headers=AUTH).status_code == 400
    assert client.post(f"/v1/admin/people/{CARLA}/password", json={"password": "abbastanza-lunga"},
                       headers=AUTH).status_code == 404


def test_without_Keycloak_the_answer_names_the_script(be, client):
    be(BRUNO)
    answer = client.post(f"/v1/admin/people/{CARLA}/password",
                         json={"password": "abbastanza-lunga"}, headers=AUTH)
    assert answer.status_code == 503 and "offline-password.sh" in answer.json()["detail"]


# ── the rescue ───────────────────────────────────────────────────────────────

def test_a_room_whose_owner_is_still_on_the_node_is_NOT_rescued(be, client):
    people_module.registry().put(people_module.Person(ANNA, "Anna", "user"))
    ws_module.ACL_STORE.put("scavo", Acl(owner=ANNA).as_dict())
    be(BRUNO)
    answer = client.put("/v1/admin/rooms/scavo/owner", json={"orcid": CARLA}, headers=AUTH)
    assert answer.status_code == 409


def test_a_room_nobody_can_manage_is_handed_to_a_new_owner_and_logged(be, client):
    ws_module.ACL_STORE.put("scavo", Acl(owner=ANNA, members={CARLA: "editor"}).as_dict())
    be(BRUNO)
    answer = client.put("/v1/admin/rooms/scavo/owner", json={"orcid": CARLA}, headers=AUTH)
    assert answer.status_code == 200, answer.text
    acl = ws_module.load_acl("scavo")
    assert acl.owner == CARLA and CARLA not in acl.members
    assert people_module.read_log()[-1]["kind"] == "room.rescue"


def test_an_administrator_still_on_the_node_blocks_the_rescue(be, client):
    people_module.registry().put(people_module.Person(CARLA, "Carla", "user"))
    ws_module.ACL_STORE.put("scavo", Acl(owner=ANNA, members={CARLA: "admin"}).as_dict())
    be(BRUNO)
    assert client.put("/v1/admin/rooms/scavo/owner", json={"orcid": CARLA},
                      headers=AUTH).status_code == 409


# ── the bucket, file by file ─────────────────────────────────────────────────

def test_the_files_listing_names_orphans_and_sizes(be, client, monkeypatch):
    store = InMemoryAssetStore()
    used = store.put(b"x" * 100, "image/png")["ref"]
    alone = store.put(b"y" * 7, "text/plain")["ref"]
    monkeypatch.setattr(main_module, "ASSET_STORE", store)
    monkeypatch.setattr(homes_module, "ASSET_HOMES", homes_module.InMemoryAssetHomes())
    doc = {"header": {"format": "em.json", "version": "1.0", "owner": ANNA},
           "graphs": {"g": {"graph_id": "g", "name": "g",
                            "nodes": [{"id": "r1", "type": "document",
                                       "data": {"checksum": used}}], "edges": []}},
           "active_graph_id": "g"}
    ws_module.SNAPSHOT_STORE.put("scavo", doc)
    be(BRUNO)
    body = client.get("/v1/admin/assets", headers=AUTH).json()
    states = {a["ref"]: (a["state"], a["size"]) for a in body["assets"]}
    assert states[alone] == ("orphan", 7)
    orphans = client.get("/v1/admin/assets?state=orphan", headers=AUTH).json()
    assert [a["ref"] for a in orphans["assets"]] == [alone]
