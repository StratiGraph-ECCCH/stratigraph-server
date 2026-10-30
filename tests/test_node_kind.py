"""The declared kind of node (E.D., 30 Oct 2026): `app/node_kind.py`."""

from app import node_kind, people


def test_il_tipo_si_dichiara():
    assert node_kind.kind({}) == "node"
    assert node_kind.kind({"EM_NODE_KIND": "field"}) == "field"
    assert node_kind.kind({"EM_NODE_KIND": "Institutional "}) == "institutional"
    assert node_kind.kind({"EM_NODE_KIND": "boh"}) == "node"
    assert node_kind.kind({"EM_NODE_PROFILE": "personal"}) == "personal"
    assert node_kind.kind({"EM_NODE_KIND": "field", "EM_NODE_PROFILE": "personal"}) == "field"


def test_il_nodo_istituzionale_rifiuta_le_persone_di_prova():
    on = {"EM_ALLOW_TEST_PEOPLE": "1"}
    assert people.test_people_allowed(on)
    assert people.test_people_allowed({**on, "EM_NODE_KIND": "field"})
    assert not people.test_people_allowed({**on, "EM_NODE_KIND": "institutional"})
    assert people.test_people_switch({**on, "EM_NODE_KIND": "institutional"})


def _codes(env, **facts):
    return {c["code"] for c in node_kind.checks(env, **facts)}


def test_i_consigli_seguono_il_tipo():
    assert _codes({}) == {"undeclared"}
    assert _codes({"EM_NODE_KIND": "personal"}) == set()
    field = _codes({"EM_NODE_KIND": "field"}, node_name="scavo", kc_configured=True)
    assert field == {"trusts-nobody"}
    assert _codes({"EM_NODE_KIND": "field"}, node_name="scavo", kc_configured=True, trusted_nodes=1) == set()
    inst = _codes({"EM_NODE_KIND": "institutional"}, public_base="https://em.localhost:8443",
                  kc_configured=False, test_people_on=True, node_name="x")
    assert inst == {"local-name", "no-kc-admin", "test-people-refused"}
    assert _codes({"EM_NODE_KIND": "institutional"}, public_base="https://em.ispc.cnr.it",
                  kc_configured=True, node_name="em.ispc.cnr.it") == set()


def test_ogni_consiglio_ha_due_lingue():
    for c in node_kind.checks({"EM_NODE_KIND": "institutional"}, test_people_on=True):
        assert c["it"] and c["en"] and c["level"] in ("bad", "warn", "info")


def test_il_nodo_dice_il_suo_tipo(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("EM_NODE_KIND", "field")
    client = TestClient(app)
    assert client.get("/v1/node").json()["kind"] == "field"
    assert client.get("/v1/health").json()["kind"] == "field"
