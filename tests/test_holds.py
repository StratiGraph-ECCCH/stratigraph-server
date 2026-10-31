"""Chi tiene un `.blend`: il verbo `hold` e il frame `holds` (31 ott 2026).

MICRO-BLEND-OFFICINA-2, decisioni di E.D. D7 e D8: chi apre un `.blend` per
modificarlo lo prende nella stanza, gli altri lo vedono e lavorano in sola
lettura; la prenotazione si rinnova da sé e cade dopo 15 minuti senza segno;
si lascia a mano (chi amministra la stanza può forzarla). Effimera come la
presenza: un riavvio la perde e il prossimo `renew` la riprende.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from fastapi.testclient import TestClient                  # noqa: E402

from app import holds as holds_module                      # noqa: E402
from app import keeping                                    # noqa: E402
from app import main as main_module                        # noqa: E402
from app import ws as ws_module                            # noqa: E402
from app.access import Acl, InMemoryAclStore               # noqa: E402
from app.rooms import RoomRegistry                         # noqa: E402
from app.store import DirectorySnapshotStore               # noqa: E402
from app.wire import WIRE                                  # noqa: E402

ROOM = "prenotazioni"
ANNA = "0000-0002-1825-0097"       # proprietaria
ELISA = "0000-0001-5109-3700"      # editor
CARLO = "0000-0003-1415-9265"      # editor
BRUNO = "0000-0002-9079-593X"      # viewer
KEY = "SB/GreatTemple_2026_v2.blend"


def _document():
    return {"header": {"format": "em.json", "version": "1.0", "owner": ANNA},
            "graphs": {ROOM: {"graph_id": ROOM, "name": ROOM, "nodes": [], "edges": []}},
            "active_graph_id": ROOM}


@pytest.fixture
def relay(monkeypatch, tmp_path):
    store = DirectorySnapshotStore(str(tmp_path))
    acls = InMemoryAclStore()
    acls.put(ROOM, Acl(owner=ANNA, members={ELISA: "editor", CARLO: "editor",
                                            BRUNO: "viewer"}).as_dict())
    store.put(ROOM, _document())
    registry = RoomRegistry(store)
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    monkeypatch.setattr(main_module, "ROOMS", registry, raising=False)
    monkeypatch.setattr(ws_module, "KEEPER", keeping.Keeper(
        ws_module._keep, after_ops=10_000, after_quiet=10_000))
    return registry


@pytest.fixture
def chi(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(ws_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())

    def be(orcid):
        claims = {"orcid": orcid} if orcid else {}
        monkeypatch.setattr(ws_module.authenticator, "verify", lambda token: claims)
        for module in (ws_module, main_module):
            monkeypatch.setattr(module.authenticator, "require_token", lambda request: claims)
    return be


@pytest.fixture
def client():
    return TestClient(main_module.app)


def _entra(client, chi, orcid):
    chi(orcid)
    socket = client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t")
    ws = socket.__enter__()
    host = ws.receive_json()
    ws.receive_json()                                    # snapshot
    ws.receive_json()                                    # presence
    return socket, ws, host["payload"]


def _hold(action, key=KEY, **extra):
    return {"v": WIRE, "type": "hold", "source": "test",
            "payload": {"action": action, "key": key, "host": "mac-ed", "client": "blender", **extra}}


_SENTINELLA = {"v": WIRE, "type": "request_snapshot", "source": "test", "payload": {}}


def _fino_a(ws, tipo, limite=10):
    """Legge finché arriva `tipo`; `None` se arriva prima la risposta alla
    sentinella (il frame non è stato mandato)."""
    ws.send_json(_SENTINELLA)
    for _ in range(limite):
        frame = ws.receive_json()
        if frame["type"] == tipo:
            while ws.receive_json()["type"] != "snapshot":
                pass
            return frame
        if frame["type"] == "snapshot":
            return None
    raise AssertionError(f"nessun frame {tipo!r}")


def test_la_porta_e_health_dicono_holds(relay, chi, client):
    socket, ws, host = _entra(client, chi, ELISA)
    try:
        assert host["holds"] is True and host["holds_ttl_seconds"] == 900
        ws.send_json({"v": WIRE, "type": "client_info", "source": "t", "payload": {}})
        assert ws.receive_json()["payload"]["holds"] is True
    finally:
        socket.__exit__(None, None, None)
    assert client.get("/v1/health").json()["capabilities"]["room_holds"] is True


def test_prendere_rifiutare_rinnovare_lasciare(relay, chi, client):
    s_e, elisa, _ = _entra(client, chi, ELISA)
    s_c, carlo, _ = _entra(client, chi, CARLO)
    try:
        elisa.receive_json()                             # presence: entra Carlo
        elisa.send_json(_hold("take"))
        got = elisa.receive_json()
        assert got["type"] == "holds"
        h = got["payload"]["holds"][0]
        assert (h["key"], h["person"], h["host"], h["client"]) == (KEY, ELISA, "mac-ed", "blender")
        assert got["payload"]["ttl_seconds"] == 900
        # …e lo vede anche Carlo
        assert carlo.receive_json()["payload"]["holds"][0]["person"] == ELISA
        # Carlo non lo prende né lo rinnova né lo lascia
        for action in ("take", "renew", "release"):
            carlo.send_json(_hold(action))
            r = carlo.receive_json()
            assert r["type"] == "hold_refused" and r["payload"]["action"] == action
            assert r["payload"]["holder"]["person"] == ELISA
        # il rinnovo di Elisa non dice niente di nuovo a nessuno
        since = h["since"]
        elisa.send_json(_hold("renew"))
        assert _fino_a(carlo, "holds") is None
        assert relay.peek(ROOM).holds.holder(KEY)["since"] == since
        # lasciare: tutti vedono la lista vuota
        elisa.send_json(_hold("release"))
        assert elisa.receive_json()["payload"]["holds"] == []
        assert carlo.receive_json()["payload"]["holds"] == []
        carlo.send_json(_hold("take"))
        assert carlo.receive_json()["payload"]["holds"][0]["person"] == CARLO
    finally:
        s_c.__exit__(None, None, None)
        s_e.__exit__(None, None, None)


def test_la_proprietaria_forza_un_editor_no(relay, chi, client):
    s_e, elisa, _ = _entra(client, chi, ELISA)
    try:
        elisa.send_json(_hold("take"))
        elisa.receive_json()
    finally:
        s_e.__exit__(None, None, None)                   # uscire NON libera
    assert relay.peek(ROOM).holds.holder(KEY)["person"] == ELISA
    s_c, carlo, _ = _entra(client, chi, CARLO)
    try:
        frame = carlo.receive_json()                     # holds alla porta
        assert frame["type"] == "holds" and frame["payload"]["holds"][0]["person"] == ELISA
        carlo.send_json(_hold("release", force=True))
        assert carlo.receive_json()["type"] == "hold_refused"
    finally:
        s_c.__exit__(None, None, None)
    s_a, anna, _ = _entra(client, chi, ANNA)
    try:
        frame = anna.receive_json()                      # holds alla porta: Elisa lo tiene
        assert frame["type"] == "holds" and frame["payload"]["holds"][0]["person"] == ELISA
        anna.send_json(_hold("release", force=True))
        assert anna.receive_json()["payload"]["holds"] == []
    finally:
        s_a.__exit__(None, None, None)


def test_un_lettore_vede_ma_non_prende(relay, chi, client):
    s_b, bruno, _ = _entra(client, chi, BRUNO)
    try:
        bruno.send_json(_hold("take"))
        r = bruno.receive_json()
        assert r["type"] == "hold_refused" and "read-only" in r["payload"]["reason"]
        assert relay.peek(ROOM).holds.alive() == []
    finally:
        s_b.__exit__(None, None, None)


def test_una_chiave_sbagliata_e_detta(relay, chi, client):
    s_e, elisa, _ = _entra(client, chi, ELISA)
    try:
        for bad in ("", "a\x00b", "x" * 513):
            elisa.send_json(_hold("take", key=bad))
            assert elisa.receive_json()["type"] == "hold_refused"
        elisa.send_json(_hold("grab"))
        assert elisa.receive_json()["type"] == "hold_refused"
    finally:
        s_e.__exit__(None, None, None)


def test_scade_dopo_15_minuti_senza_segno_e_il_rinnovo_dopo_un_riavvio_riprende():
    t = [1000.0]
    hs = holds_module.Holds(clock=lambda: t[0], wall=lambda: 1.7e9 + t[0])
    assert hs.apply("take", KEY, person=ELISA)["ok"]
    t[0] += 899
    assert hs.holder(KEY) is not None
    assert hs.apply("take", KEY, person=CARLO)["ok"] is False
    t[0] += 2                                            # 901 s senza segno
    assert hs.holder(KEY) is None and hs.alive() == []
    assert hs.apply("take", KEY, person=CARLO)["ok"]
    # un riavvio: tutto perso; il renew della stessa persona vale come take
    fresh = holds_module.Holds(clock=lambda: t[0], wall=lambda: 1.7e9 + t[0])
    got = fresh.apply("renew", KEY, person=CARLO, host="pc-lab")
    assert got["ok"] and got["changed"] and fresh.holder(KEY)["host"] == "pc-lab"
    # rinnovare tiene `since`
    since = fresh.holder(KEY)["since"]
    t[0] += 60
    fresh.apply("renew", KEY, person=CARLO, host="pc-lab")
    assert fresh.holder(KEY)["since"] == since and fresh.holder(KEY)["renewed"] > since
