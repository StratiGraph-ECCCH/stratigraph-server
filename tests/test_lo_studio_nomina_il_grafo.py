"""Una stanza scrive uno studio, e l'operazione nomina il grafo (I-2).

MICRO-LO-STUDIO-IN-STANZA-NOMINA-IL-GRAFO, 5 ottobre 2026. Tre buchi e una
nascita:

* **T-B1** · un `graph_id` che lo studio non ha cadeva in silenzio sul grafo
  attivo (`rooms.py`, `_section`). Adesso è un rifiuto con la frase, e nulla è
  scritto.
* **T-B2** · il registro salvava l'operazione senza `graph_id`, e un replay
  finiva nel grafo attivo. Adesso la riga tiene il grafo in cui l'operazione È
  ANDATA, e il replay lo rimette nella busta; le righe vecchie lo ricostruiscono
  dal nodo che toccano.
* **B3 dal server** · un arco verso un nodo di un altro grafo dello studio è
  rifiutato (la regola è di s3Dgraphy, `crdt.edge_outside_graph`; la stanza le
  passa lo studio).
* **G2** · una stanza nasce con le sezioni dello studio — vuote — quando chi la
  crea le nomina; il contenuto arriva come operazioni, ognuna col suo grafo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as main_module                      # noqa: E402
from app import ws as ws_module                          # noqa: E402
from app.access import InMemoryAclStore                  # noqa: E402
from app.main import app                                 # noqa: E402
from app.rooms import Room, RoomRegistry, UNKNOWN_GRAPH  # noqa: E402
from app.store import InMemoryRoomStore, InMemorySnapshotStore  # noqa: E402
from app.wire import WIRE                                # noqa: E402

ANNA = "0000-0002-1825-0097"
T1 = "2026-10-05T10:00:00Z"
T2 = "2026-10-05T11:00:00Z"
T3 = "2026-10-05T12:00:00Z"


def _unit(node_id):
    return {"id": node_id, "node_type": "US", "name": node_id,
            "data": {"created_at": T1, "created_by": ANNA}}


def _study():
    """Lo scavo e il saggio 30 m più avanti: due grafi, uno studio (I-3)."""
    return {
        "header": {"format": "em.json", "version": "1.0"},
        "graphs": {
            "scavo": {"graph_id": "scavo", "name": "Scavo",
                      "nodes": [_unit("US1"), _unit("US2")], "edges": []},
            "saggio": {"graph_id": "saggio", "name": "Saggio",
                       "nodes": [_unit("US9")], "edges": []},
        },
        "active_graph_id": "scavo",
    }


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    store = InMemorySnapshotStore()
    registry = RoomRegistry(store, InMemoryRoomStore())
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", InMemoryAclStore())
    return registry


@pytest.fixture
def client():
    return TestClient(app)


def _drain_join(socket):
    assert socket.receive_json()["type"] == "host_info"
    snapshot = socket.receive_json()
    assert snapshot["type"] == "snapshot"
    assert socket.receive_json()["type"] == "presence"
    return snapshot["payload"]["doc"]


def _field(node_id, value, ts, graph_id=None):
    message = {"v": WIRE, "type": "op", "source": "test",
               "payload": {"op": "update_field", "node_id": node_id,
                           "field": "description", "value": value, "ts": ts}}
    if graph_id is not None:
        message["graph_id"] = graph_id
    return message


def _node(section, node_id):
    return next(n for n in section["nodes"] if n["id"] == node_id)


# ── T-B1 · un grafo che lo studio non ha ────────────────────────────────────

def test_b1_an_invented_graph_is_refused_by_name_and_nothing_is_written(client, fresh):
    fresh.store.put("studio", _study())
    with client.websocket_connect("/v1/rooms/studio/ws") as a:
        _drain_join(a)
        a.send_json(_field("US1", "scritto nel grafo sbagliato", T2,
                           graph_id="inventato"))
        answer = a.receive_json()
    assert answer["type"] == "op_result"
    body = answer["payload"]
    assert body["applied"] is False
    assert body["reason"] == "the graph 'inventato' is not in this study"
    assert body["code"] == UNKNOWN_GRAPH and body["graph_id"] == "inventato"
    room = fresh.peek("studio")
    assert "description" not in _node(room.document["graphs"]["scavo"], "US1"), \
        "the active graph must not receive what was meant for another"
    assert room.oplog == [] and room.unsaved == 0


def test_b1_the_connector_door_refuses_it_too(fresh):
    import asyncio
    fresh.store.put("studio", _study())
    room = asyncio.run(fresh.get("studio"))
    outcome = asyncio.run(ws_module.apply_from_connector(
        room, [{"op": "update_field", "node_id": "US1", "field": "description",
                "value": "x", "ts": T2}],
        source="test", graph_id="inventato", author=ANNA))
    assert outcome["applied"] == 0
    assert outcome["refused"][0]["code"] == UNKNOWN_GRAPH


def test_b1_not_naming_a_graph_is_still_the_active_one():
    """D-A, for the clients that do not name graphs yet."""
    room = Room("studio", _study())
    result = room.apply({"op": "update_field", "node_id": "US1",
                         "field": "description", "value": "x", "ts": T2})
    assert result["applied"] is True and result["graph_id"] == "scavo"


def test_b1_a_named_graph_receives_its_operation():
    room = Room("studio", _study())
    result = room.apply({"op": "update_field", "node_id": "US9",
                         "field": "description", "value": "nel saggio", "ts": T2},
                        "saggio")
    assert result["applied"] is True and result["graph_id"] == "saggio"
    assert _node(room.document["graphs"]["saggio"], "US9")["description"] == "nel saggio"


# ── B3 dal server · l'arco verso un altro grafo ─────────────────────────────

def test_b3_the_room_refuses_an_edge_towards_another_graph():
    room = Room("studio", _study())
    result = room.apply({"op": "add_edge", "source": "US1", "target": "US9",
                         "edge_type": "is_after", "ts": T2}, "scavo")
    assert result["applied"] is False
    assert "is in the graph 'saggio'" in result["reason"]
    assert room.document["graphs"]["scavo"]["edges"] == []


# ── T-B2 · il registro tiene il grafo ───────────────────────────────────────

def test_b2_a_replay_puts_each_operation_in_its_own_graph(client, fresh):
    fresh.store.put("studio", _study())
    with client.websocket_connect("/v1/rooms/studio/ws") as a:
        _drain_join(a)
        # where the late client stopped: an operation it had seen. A cursor
        # older than everything the log holds gets no replay at all (a partial
        # one would be worse than none), so the cursor is one the log has.
        seen = "2026-10-05T10:30:00Z"
        a.send_json(_field("US2", "visto", seen))
        assert a.receive_json()["payload"]["applied"] is True
        a.send_json(_field("US1", "nello scavo", T2))                 # not named
        assert a.receive_json()["payload"]["applied"] is True
        a.send_json(_field("US9", "nel saggio", T3, graph_id="saggio"))
        assert a.receive_json()["payload"]["applied"] is True

        with client.websocket_connect(f"/v1/rooms/studio/ws?since={seen}") as late:
            _drain_join(late)
            first, second = late.receive_json(), late.receive_json()
    assert first["type"] == second["type"] == "op"
    assert (first["payload"]["node_id"], first["graph_id"]) == ("US1", "scavo")
    assert (second["payload"]["node_id"], second["graph_id"]) == ("US9", "saggio")
    assert "graph_id" not in second["payload"], \
        "the graph is the envelope's word, not the body's"


def test_b2_the_journal_keeps_the_graph(tmp_path):
    from app.oplog import Journal
    journal = Journal(str(tmp_path / "studio.oplog.jsonl"))
    room = Room("studio", _study(), journal=journal)
    op = {"op": "update_field", "node_id": "US9", "field": "description",
          "value": "x", "ts": T2}
    result = room.apply(op, "saggio")
    room.record(op, result["graph_id"])
    reborn = Room("studio", _study(), journal=Journal(str(tmp_path / "studio.oplog.jsonl")))
    rows = reborn.replay_since(T1)
    assert reborn.replay_entry(rows[0]) == (op, "saggio")


def test_b2_an_old_row_finds_its_graph_from_its_node():
    """Le righe di prima del 5 ottobre: nessun `graph_id`. Ricostruito dal nodo
    (un UUID sta in un grafo solo), il grafo attivo solo quando nessuno lo ha."""
    room = Room("studio", _study())
    old_saggio = {"op": "update_field", "node_id": "US9", "field": "description",
                  "value": "x", "ts": T2}
    old_add = {"op": "add_node", "id": "US7", "node": _unit("US7"), "ts": T2}
    gone = {"op": "remove_node", "id": "compattato", "ts": T2}
    assert room.replay_entry(old_saggio) == (old_saggio, "saggio")
    assert room.replay_entry(old_add) == (old_add, "scavo")      # nobody has it
    assert room.replay_entry(gone) == (gone, "scavo")


def test_b2_the_fan_out_names_the_graph_also_when_the_client_did_not(client, fresh):
    fresh.store.put("studio", _study())
    with client.websocket_connect("/v1/rooms/studio/ws") as a, \
         client.websocket_connect("/v1/rooms/studio/ws") as b:
        _drain_join(a)
        _drain_join(b)
        a.receive_json()                                 # presence: B joined
        a.send_json(_field("US1", "x", T2))
        assert a.receive_json()["payload"]["graph_id"] == "scavo"
        frame = b.receive_json()
        while frame["type"] != "op":
            frame = b.receive_json()
    assert frame["graph_id"] == "scavo"


# ── G2 · la stanza nasce con le sezioni dello studio ────────────────────────

def test_g2_a_room_is_born_with_the_sections_its_creator_names(client, fresh):
    made = client.post("/v1/rooms", json={
        "room_id": "sanpietro", "title": "San Pietro",
        "graphs": [{"graph_id": "tempio", "name": "Tempio Giunone Moneta",
                    "data": {"language": "it"}},
                   {"graph_id": "saggio", "name": "Saggio"},
                   {"graph_id": "shelf", "name": "Shelf",
                    "data": {"em_collection": "ShelfGraph"}}],
        "active_graph_id": "tempio"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["missing_refs"] == ["sanpietro"], \
        "the answer to «had this room anything to lose» is read before the sections"
    assert body["born_with"] == ["tempio", "saggio", "shelf"]

    with client.websocket_connect("/v1/rooms/sanpietro/ws") as a:
        doc = _drain_join(a)
        assert set(doc["graphs"]) == {"tempio", "saggio", "shelf"}
        assert doc["active_graph_id"] == "tempio"
        assert doc["graphs"]["tempio"]["name"] == "Tempio Giunone Moneta"
        assert doc["graphs"]["shelf"]["data"] == {"em_collection": "ShelfGraph"}
        a.send_json({"v": WIRE, "type": "op", "source": "test", "graph_id": "saggio",
                     "payload": {"op": "add_node", "id": "US9", "node": _unit("US9"),
                                 "ts": T2, "lang": "it"}})
        assert a.receive_json()["payload"]["applied"] is True
    assert [n["id"] for n in fresh.peek("sanpietro").document["graphs"]["saggio"]["nodes"]] == ["US9"]


def test_g2_a_section_with_content_is_refused(client):
    made = client.post("/v1/rooms", json={
        "room_id": "pieno", "graphs": [{"graph_id": "g", "nodes": [_unit("US1")]}]})
    assert made.status_code == 400
    assert "content comes as operations" in made.json()["detail"]


def test_g2_without_sections_the_room_is_born_as_before(client, fresh):
    made = client.post("/v1/rooms", json={"room_id": "vuota", "title": "Vuota"})
    assert made.status_code == 201 and made.json()["born_with"] == []
    with client.websocket_connect("/v1/rooms/vuota/ws") as a:
        doc = _drain_join(a)
    assert list(doc["graphs"]) == ["vuota"] and doc["graphs"]["vuota"]["name"] == "Vuota"


def test_g2_sections_do_not_overwrite_a_container_that_exists(client, fresh):
    fresh.store.put("esistente", _study())
    made = client.post("/v1/rooms", json={
        "room_id": "esistente", "graphs": [{"graph_id": "altro"}]})
    assert made.status_code == 201
    assert made.json()["born_with"] == []
    assert set(fresh.store.get("esistente")["graphs"]) == {"scavo", "saggio"}
