"""Il modo d'accesso lo timbra il relay, dal token — come l'autore.

════════════════════════════════════════════════════════════════════════════════
E.D. (1 ott 2026, decisione 13 del referto dev27): «il modo d'accesso lo timbra
il relay del server dal token, come l'autore. Il client non lo dichiara più.»

MISURATO PRIMA: il relay (`ws._handle`, verbo `op`) toglieva l'`author` del
client e metteva quello del token, ma l'`auth` dell'op — `created_auth` /
`modified_auth` nel grafo — era la dichiarazione del client, così com'era.
Adesso il modo è quello che la porta legge dal token
(`identity.signature_auth`) e `s3dgraphy.api.stamp_auth` lo scrive in ogni posto
dove un'op può portarne uno; una correzione si conta sulla stanza.
Due porte, la stessa regola: il socket e `POST /v1/rooms/{id}/ops`.
"""

from __future__ import annotations

import json

import pytest

from app import identity
from app import main as main_module
from app import ws as ws_module
from app.wire import WIRE
from tests.test_chi_ce_e_chi_non_ce_piu import (ELISA, ROOM, _drain_join,  # noqa: F401
                                                acls, client, relay)

T = "2026-11-01T09:00:00Z"
FIELD = {"mode": "node_password", "attested_by": "fcn-prova"}


@pytest.fixture
def token(monkeypatch):
    """Chi entra, e con quale modo: i claim di un token vero del realm."""
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(ws_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())
    monkeypatch.setenv("EM_NODE_NAME", "fcn-prova")

    def be(**claims):
        claims = {"orcid": ELISA, **claims}
        monkeypatch.setattr(ws_module.authenticator, "verify", lambda t: claims)
        monkeypatch.setattr(main_module.authenticator, "require_token",
                            lambda request: claims)
    return be


def _add(node_id, **extra):
    return {"v": WIRE, "type": "op", "source": "test",
            "payload": {"op": "add_node", "id": node_id, "ts": T,
                        "node": {"id": node_id, "node_type": "US", "name": node_id,
                                 "data": {"lang": "it"}}, **extra}}


def _node(node_id):
    doc = ws_module.ROOMS.peek(ROOM).document
    return next(n for n in doc["graphs"][ROOM]["nodes"] if n["id"] == node_id)


# ── la porta legge il modo ───────────────────────────────────────────────────

@pytest.mark.parametrize("claims, auth", [
    ({"em_idp": "orcid", "em_auth_reported": True}, {"mode": "orcid"}),
    ({"em_auth_reported": True}, FIELD),
    ({}, None),
    ({"em_dev_mode": True, "em_auth": "orcid"}, None),
])
def test_signature_auth(monkeypatch, claims, auth):
    monkeypatch.setenv("EM_NODE_NAME", "fcn-prova")
    assert identity.signature_auth(claims) == auth


def test_a_node_password_on_a_node_with_no_name_signs_nothing(monkeypatch):
    monkeypatch.delenv("EM_NODE_NAME", raising=False)
    monkeypatch.delenv("EM_PUBLIC_BASE", raising=False)
    assert identity.signature_auth({"em_auth_reported": True}) is None


# ── il socket ────────────────────────────────────────────────────────────────

def test_orcid_declared_from_a_node_password_token_lands_as_node_password(
        relay, token, client):
    token(em_auth_reported=True)                      # the node's password
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        elisa.send_json(_add("US50", auth="orcid"))   # …and the client says ORCID
        result = elisa.receive_json()["payload"]
        assert result["applied"] is True
        assert result["op"]["auth"] == FIELD
    data = _node("US50")["data"]
    assert data["created_auth"] == FIELD and data["modified_auth"] == FIELD
    assert data["created_by"] == ELISA
    assert ws_module.ROOMS.peek(ROOM).auth_corrected == 1


def test_an_op_without_a_mode_takes_the_token_s(relay, token, client):
    token(em_idp="orcid", em_auth_reported=True)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        elisa.send_json(_add("US51"))
        assert elisa.receive_json()["payload"]["op"]["auth"] == {"mode": "orcid"}
    assert _node("US51")["data"]["created_auth"] == {"mode": "orcid"}
    assert ws_module.ROOMS.peek(ROOM).auth_corrected == 0


def test_a_signature_written_field_by_field_is_the_token_s_too(relay, token, client):
    token(em_auth_reported=True)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        elisa.send_json({"v": WIRE, "type": "op", "source": "test",
                         "payload": {"op": "update_field", "node_id": "US1",
                                     "field": "data.validated_auth",
                                     "value": {"mode": "orcid"}, "ts": T}})
        assert elisa.receive_json()["payload"]["applied"] is True
    assert _node("US1")["data"]["validated_auth"] == FIELD


def test_THE_BREAK_without_the_stamp_the_client_s_word_would_land(
        relay, token, client, monkeypatch):
    # the guard switched off: the relay forwards what the client said
    monkeypatch.setattr(ws_module, "_stamp_auth", lambda room, op, auth, who: op)
    token(em_auth_reported=True)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        elisa.send_json(_add("US52", auth="orcid"))
        elisa.receive_json()
    assert _node("US52")["data"]["created_auth"] == {"mode": "orcid"}


# ── la porta REST ────────────────────────────────────────────────────────────

def test_the_rest_door_stamps_the_same(relay, token, client):
    token(em_auth_reported=True)
    body = {"ops": [_add("US53", auth="orcid")["payload"]]}
    res = client.post(f"/v1/rooms/{ROOM}/ops", json=body,
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 200, res.text
    assert res.json()["applied"] == 1
    assert _node("US53")["data"]["created_auth"] == FIELD
    assert ws_module.ROOMS.peek(ROOM).auth_corrected == 1


# ── il realm in due lingue ───────────────────────────────────────────────────

def test_the_realm_speaks_italian_and_english():
    """The committed realm — the rendered `realm-em-dev.<host>.json` is a copy
    of it (`render_realm.py`, git-ignored), so it follows at the next
    `fcn-up.sh`. The texts it overrides exist in both languages since dev27."""
    from pathlib import Path
    realms = [Path(__file__).resolve().parents[1] / "dev-stack" / "keycloak"
              / "realm-em-dev.json"]
    for path in realms:
        realm = json.loads(path.read_text(encoding="utf-8"))
        assert realm.get("internationalizationEnabled") is True, path.name
        assert sorted(realm.get("supportedLocales") or []) == ["en", "it"], path.name
        assert realm.get("defaultLocale") == "en", path.name
        assert sorted(realm.get("localizationTexts") or {}) == ["en", "it"], path.name


def test_the_realm_rendered_for_another_host_keeps_the_two_languages():
    import importlib.util as ilu
    from pathlib import Path
    dev = Path(__file__).resolve().parents[1] / "dev-stack"
    spec = ilu.spec_from_file_location("render_realm", dev / "render_realm.py")
    rr = ilu.module_from_spec(spec)
    spec.loader.exec_module(rr)
    realm = json.loads((dev / "keycloak" / "realm-em-dev.json").read_text(encoding="utf-8"))
    rendered, _added = rr.rendi(realm, host="fcn.local", porta=8443)
    assert rendered["internationalizationEnabled"] is True
    assert rendered["supportedLocales"] == ["it", "en"]
    assert rendered["defaultLocale"] == "en"
