"""People between nodes (`app/transfer.py`, E.D., 30 October 2026).

Passwords never travel; a package is signed and accepted only from a node on
the trust list; profiles travel as proposals; only the people of the chosen
rooms (plus whoever is named) travel.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app import keycloak_admin                               # noqa: E402
from app import main as main_module                          # noqa: E402
from app import people as people_module                      # noqa: E402
from app import transfer as transfer_module                  # noqa: E402
from app import ws as ws_module                              # noqa: E402
from app.access import Acl, Group, InMemoryAclStore, InMemoryGroupStore  # noqa: E402
from app.main import app                                     # noqa: E402

BRUNO = "0000-0001-5109-3700"    # operator on both nodes
ANNA = "0000-0002-1825-0097"
CARLA = "0000-0002-9079-593X"
DARIO = "0000-0001-5000-0007"
AUTH = {"Authorization": "Bearer t"}


class Node:
    """One node's state: register, access lists, groups, key, trust list."""

    def __init__(self, name):
        self.name = name
        self.people = people_module.InMemoryPeopleStore()
        self.acl = InMemoryAclStore()
        self.groups = InMemoryGroupStore()
        self.key = {}
        self.trust = {}


@pytest.fixture
def nodes(monkeypatch):
    central, field = Node("central.example"), Node("field.example")

    def be(node):
        monkeypatch.setattr(people_module, "PEOPLE_STORE", node.people)
        monkeypatch.setattr(ws_module, "ACL_STORE", node.acl)
        monkeypatch.setattr(main_module, "ACL_STORE", node.acl)
        monkeypatch.setattr(ws_module, "GROUP_STORE", node.groups)
        monkeypatch.setattr(transfer_module, "_MEMORY_KEY", node.key)
        monkeypatch.setattr(transfer_module, "_MEMORY_TRUST", node.trust)
        monkeypatch.setattr(main_module, "node_name", lambda: node.name)
        return node

    monkeypatch.setenv("EM_OPERATORS", BRUNO)
    monkeypatch.delenv("EM_ALLOW_TEST_PEOPLE", raising=False)
    monkeypatch.delenv("EM_ACCREDITED_FILE", raising=False)
    monkeypatch.delenv("EM_NODE_KEY_FILE", raising=False)
    for name in ("EM_KC_ADMIN_URL", "EM_KC_REALM", "EM_KC_ADMIN_USER", "EM_KC_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    for module in (ws_module, main_module):
        monkeypatch.setattr(module.authenticator, "settings", Enforcing())
        monkeypatch.setattr(module.authenticator, "verify", lambda token: {"orcid": BRUNO})
    return central, field, be


@pytest.fixture
def client():
    return TestClient(app)


def _central_with_a_room(central, be):
    be(central)
    people_module.registry().put(people_module.Person(ANNA, "Anna", "creator", verified_by=None))
    people_module.registry().put(people_module.Person(CARLA, "Carla", "user", verified_by="ancient.node"))
    central.acl.put("scavo", Acl(owner=ANNA, members={CARLA: "editor"}, groups={"squadra": "viewer"}).as_dict())
    ws_module.groups().put(Group("squadra", "Squadra", [DARIO], owner=ANNA))
    central.acl.put("altro", Acl(owner=BRUNO).as_dict())


def test_only_the_people_of_the_chosen_rooms_travel_and_no_password(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    assert {p["orcid"] for p in package["people"]} == {ANNA, CARLA, DARIO}
    assert package["from"] == "central.example" and package["signature"]
    assert [g["id"] for g in package["groups"]] == ["squadra"]
    text = str(package).lower()
    assert "password" not in text and "token" not in text


def test_a_package_from_an_UNTRUSTED_node_is_shown_but_not_taken(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    preview = client.post("/v1/admin/people-transfer/preview", json=package, headers=AUTH).json()
    assert preview["trusted"] is False and "trust list" in preview["why"]
    assert client.post("/v1/admin/people-transfer/import", json={"package": package},
                       headers=AUTH).status_code == 409


def test_from_a_TRUSTED_node_people_arrive_as_users_unless_a_profile_is_accepted(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    key = client.get("/v1/admin/node-key", headers=AUTH).json()
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    assert client.put("/v1/admin/trusted-nodes/central.example", json={"public_key": key["public_key"]},
                      headers=AUTH).status_code == 200
    preview = client.post("/v1/admin/people-transfer/preview", json=package, headers=AUTH).json()
    assert preview["trusted"] is True and preview["fingerprint"] == key["fingerprint"]
    done = client.post("/v1/admin/people-transfer/import",
                       json={"package": package, "accept_profiles": [ANNA]}, headers=AUTH).json()
    assert set(done["added"]) == {ANNA, CARLA, DARIO}
    assert done["profiles_applied"] == [ANNA]
    reg = people_module.registry()
    assert reg.get(ANNA).profile == "creator" and reg.get(CARLA).profile == "user"
    # Carla was attested by the sending node; Dario nobody verified
    assert reg.get(CARLA).verified_by == "central.example"
    assert DARIO in done["to_verify"] and reg.get(DARIO).verified_by is None
    assert done["groups_created"] == ["squadra"]
    assert ws_module.groups().get("squadra").has(DARIO)


def test_a_package_CHANGED_after_signing_is_refused(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    key = client.get("/v1/admin/node-key", headers=AUTH).json()
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    client.put("/v1/admin/trusted-nodes/central.example", json={"public_key": key["public_key"]}, headers=AUTH)
    forged = copy.deepcopy(package)
    forged["people"][0]["profile"] = "super"
    preview = client.post("/v1/admin/people-transfer/preview", json=forged, headers=AUTH).json()
    assert preview["trusted"] is False and "changed after it was signed" in preview["why"]


def test_a_package_signed_by_ANOTHER_key_under_a_trusted_name_is_refused(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    other = transfer_module.Ed25519PrivateKey.generate()
    client.put("/v1/admin/trusted-nodes/central.example", json={"public_key": transfer_module.public_b64(other)},
               headers=AUTH)
    preview = client.post("/v1/admin/people-transfer/preview", json=package, headers=AUTH).json()
    assert preview["trusted"] is False and "different key" in preview["why"]


def test_an_attested_person_gets_a_field_password_without_signing_in_with_ORCID_here(nodes, client, monkeypatch):
    central, field, be = nodes
    _central_with_a_room(central, be)
    key = client.get("/v1/admin/node-key", headers=AUTH).json()
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    client.put("/v1/admin/trusted-nodes/central.example", json={"public_key": key["public_key"]}, headers=AUTH)
    client.post("/v1/admin/people-transfer/import", json={"package": package}, headers=AUTH)

    class FakeKc:
        def configured(self): return True
        def user(self, orcid): return {"id": "id-" + orcid}
        def linked_to_orcid(self, user_id): return False
        def set_password(self, user_id, password, *, temporary=True): self.done = (user_id, temporary)

    fake = FakeKc()
    monkeypatch.setattr(keycloak_admin, "admin", lambda environ=None: fake)
    ok = client.post(f"/v1/admin/people/{CARLA}/password", json={"password": "campo-campo-1"}, headers=AUTH)
    assert ok.status_code == 200, ok.text
    refused = client.post(f"/v1/admin/people/{DARIO}/password", json={"password": "campo-campo-1"}, headers=AUTH)
    assert refused.status_code == 409
    # …and when the sending node leaves the trust list, its attestation stops counting
    client.delete("/v1/admin/trusted-nodes/central.example", headers=AUTH)
    assert client.post(f"/v1/admin/people/{CARLA}/password", json={"password": "campo-campo-1"},
                       headers=AUTH).status_code == 409


def test_a_profile_raised_in_the_field_does_not_count_at_the_centre_by_itself(nodes, client):
    central, field, be = nodes
    _central_with_a_room(central, be)
    central_key = client.get("/v1/admin/node-key", headers=AUTH).json()
    package = client.post("/v1/admin/people-transfer/export", json={"rooms": ["scavo"]}, headers=AUTH).json()
    be(field)
    field_key = client.get("/v1/admin/node-key", headers=AUTH).json()
    client.put("/v1/admin/trusted-nodes/central.example", json={"public_key": central_key["public_key"]}, headers=AUTH)
    client.post("/v1/admin/people-transfer/import", json={"package": package}, headers=AUTH)
    client.put(f"/v1/admin/people/{CARLA}", json={"profile": "super"}, headers=AUTH)   # raised in the field
    back = client.post("/v1/admin/people-transfer/export", json={"people": [CARLA]}, headers=AUTH).json()
    be(central)
    client.put("/v1/admin/trusted-nodes/field.example", json={"public_key": field_key["public_key"]}, headers=AUTH)
    done = client.post("/v1/admin/people-transfer/import", json={"package": back}, headers=AUTH).json()
    assert CARLA in done["updated"] and done["profiles_applied"] == []
    assert people_module.registry().get(CARLA).profile == "user"


def test_the_key_is_stable_and_kept_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("EM_NODE_KEY_FILE", str(tmp_path / "k.pem"))
    a = transfer_module.public_b64(transfer_module.node_key())
    b = transfer_module.public_b64(transfer_module.node_key())
    assert a == b and (tmp_path / "k.pem").stat().st_mode & 0o077 == 0
