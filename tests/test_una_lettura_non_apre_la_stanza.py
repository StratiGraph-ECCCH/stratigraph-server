"""Una lettura su una stanza non dichiarata non apre una copia di lavoro.

MICRO-HEAD-NON-APRE-LA-STANZA, 16 ottobre 2026. Misurato il 15 ottobre
(s3Dgraphy, room-import, fase C, punto 2): un HEAD
`…/rooms/<id>/asset/sha256:…` su una stanza non ancora creata passava da
`rooms().get`, che costruiva una copia vuota e la TENEVA. Il `POST /v1/rooms`
successivo scriveva le sezioni nello store, la copia in memoria restava vuota,
la semina era rifiutata («the graph … is not in this study») e alla chiusura la
copia vuota veniva salvata sopra le sezioni.

Adesso una lettura (HEAD/GET di asset, asset-home, manifest IIIF, GET del
record) su una stanza che non c'è risponde 404 e non apre niente.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main as main_module                      # noqa: E402
from app import ws as ws_module                          # noqa: E402
from app.access import InMemoryAclStore                  # noqa: E402
from app.assets import InMemoryAssetStore                # noqa: E402
from app.main import app                                 # noqa: E402
from app.rooms import RoomRegistry                       # noqa: E402
from app.store import InMemoryRoomStore, InMemorySnapshotStore  # noqa: E402
from app.wire import WIRE                                # noqa: E402

T = "2026-10-16T10:00:00Z"
BYTES = b"una foto del muro 3"
REF = "sha256:" + hashlib.sha256(BYTES).hexdigest()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    store = InMemorySnapshotStore()
    registry = RoomRegistry(store, InMemoryRoomStore())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", InMemoryAclStore())
    monkeypatch.setattr(main_module, "ASSET_STORE", InMemoryAssetStore())
    return registry


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, room):
    put = client.put(f"/v1/rooms/{room}/asset", content=BYTES,
                     params={"media_type": "image/jpeg"})
    assert put.status_code in (200, 201), put.text
    assert put.json()["ref"] == REF


def test_le_letture_su_una_stanza_che_non_ce_rispondono_404_e_non_la_aprono(
        client, fresh):
    _upload(client, "altrove")
    reads = [
        ("HEAD", f"/v1/rooms/nuova/asset/{REF}"),
        ("GET", f"/v1/rooms/nuova/asset/{REF}"),
        ("GET", f"/v1/rooms/nuova/asset-home/{REF}"),
        ("GET", "/v1/rooms/nuova"),
        ("GET", "/v1/rooms/nuova/members"),
    ]
    for method, url in reads:
        answer = client.request(method, url)
        assert answer.status_code == 404, (method, url, answer.status_code)
    assert fresh.peek("nuova") is None, "a read opened the room"
    assert "nuova" not in fresh.rooms()
    assert fresh.store.get("nuova") is None


def test_head_prima_della_nascita_poi_la_semina_e_accettata(client, fresh):
    """Il caso del referto, nell'ordine: HEAD, POST /v1/rooms con le sezioni,
    semina nella sezione — accettata, e la sezione resta nello store."""
    _upload(client, "altrove")
    before = client.head(f"/v1/rooms/templu/asset/{REF}").status_code

    made = client.post("/v1/rooms", json={
        "room_id": "templu", "title": "Templu Mare",
        "graphs": [{"graph_id": "tm-v32", "name": "Templu Mare v3.2"}],
        "active_graph_id": "tm-v32"})
    assert made.status_code == 201, made.text
    assert made.json()["born_with"] == ["tm-v32"]

    # dopo la nascita la stessa lettura trova la stanza (l'asset è d'altrove,
    # e in modalità dev passa): non più 404
    assert client.head(f"/v1/rooms/templu/asset/{REF}").status_code == 200

    with client.websocket_connect("/v1/rooms/templu/ws") as a:
        assert a.receive_json()["type"] == "host_info"
        snapshot = a.receive_json()
        assert set(snapshot["payload"]["doc"]["graphs"]) == {"tm-v32"}
        assert a.receive_json()["type"] == "presence"
        a.send_json({"v": WIRE, "type": "op", "source": "test",
                     "graph_id": "tm-v32",
                     "payload": {"op": "add_node", "id": "US1",
                                 "node": {"id": "US1", "node_type": "US",
                                          "name": "US1", "data": {}},
                                 "ts": T, "lang": "it"}})
        ack = a.receive_json()
        assert ack["payload"]["applied"] is True, ack
    graphs = fresh.peek("templu").document["graphs"]
    assert [n["id"] for n in graphs["tm-v32"]["nodes"]] == ["US1"]
    assert before == 404


def test_una_copia_aperta_prima_della_nascita_non_nasconde_le_sezioni(
        client, fresh):
    """Anche quando la copia c'è (una sessione entrata prima e uscita senza
    scrivere), la nascita la lascia andare: la prossima apertura legge le
    sezioni."""
    with client.websocket_connect("/v1/rooms/presto/ws") as a:
        assert a.receive_json()["type"] == "host_info"
    assert fresh.peek("presto") is not None
    made = client.post("/v1/rooms", json={
        "room_id": "presto",
        "graphs": [{"graph_id": "scavo", "name": "Scavo"}],
        "active_graph_id": "scavo"})
    assert made.status_code == 201, made.text
    assert fresh.peek("presto") is None
    with client.websocket_connect("/v1/rooms/presto/ws") as a:
        assert a.receive_json()["type"] == "host_info"
        assert set(a.receive_json()["payload"]["doc"]["graphs"]) == {"scavo"}


def test_una_stanza_di_prima_del_registro_si_legge_ancora(client, fresh):
    """Una stanza implicita — il suo contenitore nello store, nessun record —
    esiste: una lettura la trova come prima."""
    fresh.store.put("vecchia", {
        "header": {"format": "em.json", "version": "1.0"},
        "graphs": {"vecchia": {"graph_id": "vecchia", "nodes": [], "edges": []}},
        "active_graph_id": "vecchia"})
    _upload(client, "vecchia")
    assert client.head(f"/v1/rooms/vecchia/asset/{REF}").status_code == 200
    assert client.get("/v1/rooms/vecchia").status_code == 200
