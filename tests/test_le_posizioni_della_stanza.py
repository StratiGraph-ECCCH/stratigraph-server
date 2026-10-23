"""Le posizioni viaggiano nelle stanze: il frame `layout` (23 ott 2026).

Prima di oggi il relay applicava le cinque operazioni del grafo e lasciava
cadere un frame che non conosceva: un'unità trascinata nella Matrix, o un
combinatore spostato dentro un gruppo, restavano sullo schermo di chi li aveva
mossi (misurato da EMStudio, referto «corsia e gruppi in stanza», Parte 2).

Il frame è `{space, positions, whole?, swimlanes?, canvas?}`, con il grafo nella
busta. `space` vuoto è la Matrix (`layout.positions`), un id di gruppo è
l'interno del gruppo (`layout.group_spaces`). Queste prove guardano le risposte
vere del socket e della porta REST, e il documento che la stanza scrive.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")
pytest.importorskip("s3dgraphy", reason="s3dgraphy not importable")

from fastapi.testclient import TestClient                  # noqa: E402

from app import keeping                                    # noqa: E402
from app import main as main_module                        # noqa: E402
from app import ws as ws_module                            # noqa: E402
from app.access import Acl, InMemoryAclStore               # noqa: E402
from app.rooms import RoomRegistry                         # noqa: E402
from app.store import DirectorySnapshotStore               # noqa: E402
from app.wire import WIRE                                  # noqa: E402

ROOM = "posizioni"
ANNA = "0000-0002-1825-0097"       # proprietaria
ELISA = "0000-0001-5109-3700"      # editor
CARLO = "0000-0003-1415-9265"      # editor
BRUNO = "0000-0002-9079-593X"      # viewer
T1 = "2026-10-23T09:00:00Z"

US1 = {"x": 100.0, "y": 200.0, "w": 120.0, "h": 30.0}
US1_MOSSA = {"x": 180.0, "y": 200.0, "w": 120.0, "h": 30.0}
COMB = {"x": 63.0, "y": 250.0, "w": 90.0, "h": 40.0}


def _document():
    nodes = [{"id": i, "node_type": t, "name": i,
              "data": {"created_at": T1, "created_by": ANNA}}
             for i, t in (("US1", "US"), ("US2", "US"), ("PD1", "ParadataNodeGroup"),
                          ("COMB1", "CombinerNode"), ("PROP1", "PropertyNode"))]
    return {"header": {"format": "em.json", "version": "1.0", "owner": ANNA},
            "graphs": {ROOM: {"graph_id": ROOM, "name": ROOM,
                              "nodes": nodes, "edges": []}},
            "active_graph_id": ROOM}


@pytest.fixture
def store(tmp_path):
    return DirectorySnapshotStore(str(tmp_path))


@pytest.fixture
def relay(monkeypatch, store):
    acls = InMemoryAclStore()
    acls.put(ROOM, Acl(owner=ANNA, members={ELISA: "editor", CARLO: "editor",
                                            BRUNO: "viewer"}).as_dict())
    store.put(ROOM, _document())
    registry = RoomRegistry(store)
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    monkeypatch.setattr(main_module, "ROOMS", registry, raising=False)
    # la rete dei salvataggi lontana: qui si salva quando lo si chiede
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
        monkeypatch.setattr(ws_module.authenticator, "verify",
                            lambda token: claims)
        for module in (ws_module, main_module):
            monkeypatch.setattr(module.authenticator, "require_token",
                                lambda request: claims)
    return be


@pytest.fixture
def client():
    return TestClient(main_module.app)


def _entra(client, chi, orcid, since=None):
    chi(orcid)
    url = f"/v1/rooms/{ROOM}/ws?token=t" + (f"&since={since}" if since else "")
    socket = client.websocket_connect(url)
    ws = socket.__enter__()
    host = ws.receive_json()
    snap = ws.receive_json()
    ws.receive_json()                                    # presence
    return socket, ws, host["payload"], snap["payload"]


def _esci(socket):
    socket.__exit__(None, None, None)


def _layout(space, positions, graph_id=ROOM, **extra):
    frame = {"v": WIRE, "type": "layout", "source": "emstudio",
             "payload": {"space": space, "positions": positions, **extra}}
    if graph_id:
        frame["graph_id"] = graph_id
    return frame


_SENTINELLA = {"v": WIRE, "type": "request_snapshot", "source": "test",
               "payload": {}}


def _fino_a(ws, tipo, limite=8):
    """Legge finché arriva `tipo`, o la risposta alla sentinella (allora il
    frame atteso non è stato mandato: `None`)."""
    ws.send_json(_SENTINELLA)
    for _ in range(limite):
        frame = ws.receive_json()
        if frame["type"] == tipo:
            # …e la risposta alla sentinella, che arriva dopo: lasciata nella
            # coda farebbe credere alla prossima attesa che non è arrivato niente
            while ws.receive_json()["type"] != "snapshot":
                pass
            return frame
        if frame["type"] == "snapshot":
            return None
    raise AssertionError(f"nessun frame {tipo!r} in {limite} letture")


def _sezione(relay):
    return relay.peek(ROOM).document["graphs"][ROOM]


# ═══ 1 · la porta lo dice ═══════════════════════════════════════════════════

def test_la_stanza_dichiara_layout_alla_porta_e_in_health(relay, chi, client):
    socket, ws, host, _ = _entra(client, chi, ELISA)
    try:
        assert host["layout"] is True
        assert host["layout_limits"] == {
            "frame_max_bytes": ws_module.LAYOUT_FRAME_MAX_BYTES,
            "frames_per_window": ws_module.LAYOUT_FRAMES_PER_WINDOW,
            "window_seconds": ws_module.LAYOUT_WINDOW_SECONDS}
        # …e la risposta a `client_info`, che è un altro `host_info`
        ws.send_json({"v": WIRE, "type": "client_info", "source": "t",
                      "payload": {"saves_itself": False}})
        assert ws.receive_json()["payload"]["layout"] is True
    finally:
        _esci(socket)
    health = client.get("/v1/health").json()
    assert health["capabilities"]["room_layout"] is True
    assert health["limits"]["layout_frame_max_bytes"] == ws_module.LAYOUT_FRAME_MAX_BYTES
    assert health["limits"]["layout_frames_per_window"] == ws_module.LAYOUT_FRAMES_PER_WINDOW


# ═══ 2 · chi può muovere ════════════════════════════════════════════════════

def test_un_lettore_non_sposta_niente(relay, chi, client):
    s_b, bruno, host, _ = _entra(client, chi, BRUNO)
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    try:
        assert host["can_write"] is False
        bruno.receive_json()                             # presence: entra Elisa
        bruno.send_json(_layout("", {"US1": US1_MOSSA}))
        denied = _fino_a(bruno, "denied")
        assert denied and denied["payload"]["verb"] == "layout"
        assert "layout" not in _sezione(relay)
        # …e a Elisa non arriva niente
        assert _fino_a(elisa, "layout") is None
    finally:
        _esci(s_e)
        _esci(s_b)


def test_un_editor_sposta_e_gli_altri_lo_vedono_lui_no(relay, chi, client):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    s_c, carlo, _, _ = _entra(client, chi, CARLO)
    try:
        elisa.receive_json()                             # presence: entra Carlo
        elisa.send_json(_layout("", {"US1": US1_MOSSA}))
        arrivato = _fino_a(carlo, "layout")
        assert arrivato is not None
        assert arrivato["graph_id"] == ROOM
        body = arrivato["payload"]
        assert body["space"] == "" and body["positions"] == {"US1": US1_MOSSA}
        assert body["author"] == ELISA and body["connection_id"]
        # chi l'ha mandato non riceve né l'eco né una risposta: tutto bene
        assert _fino_a(elisa, "layout") is None
        assert _fino_a(elisa, "layout_result") is None
        assert _sezione(relay)["layout"]["positions"] == {"US1": US1_MOSSA}
        # da dove era partita (non aveva posto): per chi entra dopo
        assert _sezione(relay)["layout"]["moved_from"] == {"US1": None}
    finally:
        _esci(s_c)
        _esci(s_e)


# ═══ 3 · dove si tiene, e chi entra dopo ════════════════════════════════════

def test_matrix_e_gruppo_restano_per_chi_esce_e_rientra_e_per_chi_entra_dopo(
        relay, chi, client, store):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    s_c, carlo, _, _ = _entra(client, chi, CARLO)
    elisa.receive_json()
    elisa.send_json(_layout("", {"US1": US1_MOSSA}))
    elisa.send_json(_layout("PD1", {"COMB1": COMB}))
    assert _fino_a(carlo, "layout")["payload"]["space"] == ""
    # Carlo esce e rientra
    _esci(s_c)
    elisa.receive_json()                                 # presence: Carlo esce
    s_c, carlo, _, snap = _entra(client, chi, CARLO)
    layout = snap["doc"]["graphs"][ROOM]["layout"]
    assert layout["positions"] == {"US1": US1_MOSSA}
    assert layout["group_spaces"] == {"PD1": {"COMB1": COMB}}
    # un terzo che entra dopo
    s_a, anna, _, snap3 = _entra(client, chi, ANNA)
    assert snap3["doc"]["graphs"][ROOM]["layout"] == layout
    for s in (s_a, s_c, s_e):
        _esci(s)
    # …e quando nessuno resta, sul disco: la stanza riaperta da zero le ha
    relay.forget(ROOM)
    on_disk = store.get(ROOM)["graphs"][ROOM]["layout"]
    assert on_disk["positions"] == {"US1": US1_MOSSA}
    assert on_disk["group_spaces"] == {"PD1": {"COMB1": COMB}}


def test_chi_rientra_col_cursore_le_trova_nell_istantanea_e_il_replay_resta_di_op(
        relay, chi, client):
    """Le posizioni non vanno nel registro (si rigioca con `em.apply_op`, che
    non le sa applicare): l'istantanea, che parte sempre prima del replay, le
    porta già."""
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    for value, ts in (("muro", "2026-10-23T10:00:00Z"),
                      ("muro in opus", "2026-10-23T10:05:00Z")):
        elisa.send_json({"v": WIRE, "type": "op", "source": "t", "graph_id": ROOM,
                         "payload": {"op": "update_field", "node_id": "US1",
                                     "field": "description", "value": value,
                                     "ts": ts}})
        assert elisa.receive_json()["payload"]["applied"] is True
    elisa.send_json(_layout("", {"US1": US1_MOSSA}))
    _fino_a(elisa, "layout_result")
    room = relay.peek(ROOM)
    assert all(row.get("op") for row in room.oplog)
    assert len(room.oplog) == 2
    s_c, carlo, host, snap = _entra(client, chi, CARLO, since="2026-10-23T10:00:00Z")
    try:
        assert host["replay"]["granted"] is True
        assert snap["doc"]["graphs"][ROOM]["layout"]["positions"] == {"US1": US1_MOSSA}
        replay = carlo.receive_json()
        assert replay["type"] == "op" and replay["payload"]["node_id"] == "US1"
    finally:
        _esci(s_c)
        _esci(s_e)


def test_la_lettura_REST_della_stanza_porta_le_posizioni(relay, chi, client):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    elisa.send_json(_layout("PD1", {"COMB1": COMB}))
    _fino_a(elisa, "layout_result")
    _esci(s_e)
    chi(BRUNO)
    answer = client.get(f"/v1/rooms/{ROOM}/document",
                        headers={"Authorization": "Bearer t"})
    assert answer.status_code == 200
    layout = answer.json()["doc"]["graphs"][ROOM]["layout"]
    assert layout["group_spaces"] == {"PD1": {"COMB1": COMB}}


def test_una_posizione_e_lavoro_da_tenere(relay, chi, client, store):
    """Conta per la rete dei salvataggi come un'operazione, e `request_save`
    la scrive."""
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    try:
        room = relay.peek(ROOM)
        prima, rev = room.unsaved, room.revision
        elisa.send_json(_layout("", {"US1": US1_MOSSA}))
        _fino_a(elisa, "layout_result")
        assert room.unsaved == prima + 1 and room.revision == rev + 1
        elisa.send_json({"v": WIRE, "type": "request_save", "source": "t",
                         "payload": {}})
        assert _fino_a(elisa, "snapshot_written") is not None
        assert store.get(ROOM)["graphs"][ROOM]["layout"]["positions"] == {"US1": US1_MOSSA}
        assert room.unsaved == 0
    finally:
        _esci(s_e)


# ═══ 4 · vince l'ultimo, si toglie, si sostituisce ═══════════════════════════

def test_vince_l_ultimo_arrivato_e_null_toglie(relay, chi, client):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    s_c, carlo, _, _ = _entra(client, chi, CARLO)
    try:
        elisa.receive_json()
        elisa.send_json(_layout("", {"US1": US1, "US2": US1}))
        _fino_a(carlo, "layout")
        carlo.send_json(_layout("", {"US1": US1_MOSSA}))
        _fino_a(elisa, "layout")
        assert _sezione(relay)["layout"]["positions"] == {"US1": US1_MOSSA, "US2": US1}
        elisa.send_json(_layout("", {"US2": None}))
        arrivato = _fino_a(carlo, "layout")
        assert arrivato["payload"]["positions"] == {"US2": None}
        assert _sezione(relay)["layout"]["positions"] == {"US1": US1_MOSSA}
        # in un gruppo: tolta l'ultima voce, lo spazio sparisce
        elisa.send_json(_layout("PD1", {"COMB1": COMB}))
        _fino_a(carlo, "layout")
        elisa.send_json(_layout("PD1", {"COMB1": None}))
        _fino_a(carlo, "layout")
        assert _sezione(relay)["layout"]["group_spaces"] == {}
    finally:
        _esci(s_c)
        _esci(s_e)


def test_ricalcola_layout_sostituisce_la_matrix_intera(relay, chi, client):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    s_c, carlo, _, _ = _entra(client, chi, CARLO)
    try:
        elisa.receive_json()
        elisa.send_json(_layout("", {"US1": US1, "US2": US1}))
        _fino_a(carlo, "layout")
        lanes = [{"epoch_id": "E1", "y": 0, "height": 300}]
        elisa.send_json(_layout("", {"US1": US1_MOSSA}, whole=True,
                                swimlanes=lanes, canvas={"width": 900, "height": 300}))
        body = _fino_a(carlo, "layout")["payload"]
        assert body["whole"] is True and body["swimlanes"] == lanes
        layout = _sezione(relay)["layout"]
        assert layout["positions"] == {"US1": US1_MOSSA}     # US2 è andata
        assert layout["swimlanes"] == lanes
        assert layout["canvas"] == {"width": 900, "height": 300}
        # un layout intero ricomincia: nessun nodo «mosso da»
        assert "moved_from" not in layout
        # …poi Carlo sposta US1 e mette US2: la stanza ricorda da dove
        carlo.send_json(_layout("", {"US1": US1, "US2": US1}))
        _fino_a(elisa, "layout")
        carlo.send_json(_layout("", {"US1": {**US1, "x": 5.0}}))
        _fino_a(elisa, "layout")
        assert layout["moved_from"] == {"US1": US1_MOSSA, "US2": None}
        assert layout["positions"]["US1"]["x"] == 5.0
    finally:
        _esci(s_c)
        _esci(s_e)


# ═══ 5 · i limiti ═══════════════════════════════════════════════════════════

def test_solo_nodi_che_il_grafo_ha(relay, chi, client):
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    s_c, carlo, _, _ = _entra(client, chi, CARLO)
    try:
        elisa.receive_json()
        elisa.send_json(_layout("", {"US1": US1, "FANTASMA": US1,
                                     "US2": {"x": "a", "y": 0, "w": 1, "h": 1}}))
        result = _fino_a(elisa, "layout_result")
        assert result["payload"]["dropped"] == ["FANTASMA", "US2"]
        assert _fino_a(carlo, "layout")["payload"]["positions"] == {"US1": US1}
        assert _sezione(relay)["layout"]["positions"] == {"US1": US1}
        # un'istanza dentro un gruppo (`<maestro>##<gruppo>`) conta per il maestro
        elisa.send_json(_layout("PD1", {"PROP1##PD1": COMB}))
        assert _fino_a(carlo, "layout")["payload"]["positions"] == {"PROP1##PD1": COMB}
        # un gruppo che il grafo non ha: rifiutato, niente scritto
        elisa.send_json(_layout("PD9", {"COMB1": COMB}))
        refused = _fino_a(elisa, "layout_result")["payload"]
        assert refused["applied"] is False and refused["code"] == "unknown_space"
        assert "PD9" not in _sezione(relay)["layout"].get("group_spaces", {})
        # un grafo che lo studio non ha
        elisa.send_json(_layout("", {"US1": US1}, graph_id="altro"))
        assert _fino_a(elisa, "layout_result")["payload"]["code"] == "unknown_graph"
        # e la forma
        elisa.send_json({"v": WIRE, "type": "layout", "source": "t",
                         "payload": {"positions": {"US1": US1}}})
        assert _fino_a(elisa, "layout_result")["payload"]["code"] == "layout_malformed"
    finally:
        _esci(s_c)
        _esci(s_e)


def test_un_frame_troppo_grande_e_rifiutato(relay, chi, client, monkeypatch):
    monkeypatch.setattr(ws_module, "LAYOUT_FRAME_MAX_BYTES", 100)
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    try:
        elisa.send_json(_layout("", {"US1": US1, "US2": US1, "COMB1": US1}))
        refused = _fino_a(elisa, "layout_result")["payload"]
        assert refused["code"] == "layout_too_large" and refused["limit"] == 100
        assert "layout" not in _sezione(relay)
    finally:
        _esci(s_e)


def test_troppi_frame_in_una_finestra_sono_rifiutati(relay, chi, client, monkeypatch):
    monkeypatch.setattr(ws_module, "LAYOUT_FRAMES_PER_WINDOW", 3)
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    try:
        for x in (1.0, 2.0, 3.0):
            elisa.send_json(_layout("", {"US1": {**US1, "x": x}}))
        elisa.send_json(_layout("", {"US1": {**US1, "x": 4.0}}))
        refused = _fino_a(elisa, "layout_result")["payload"]
        assert refused["code"] == "layout_too_fast"
        assert _sezione(relay)["layout"]["positions"]["US1"]["x"] == 3.0
    finally:
        _esci(s_e)


def test_le_posizioni_non_toccano_il_grafo(relay, chi, client):
    """Nessun nodo, arco, orologio di campo cambia: s3Dgraphy non è chiamato."""
    import copy
    s_e, elisa, _, _ = _entra(client, chi, ELISA)
    try:
        prima = copy.deepcopy({k: v for k, v in _sezione(relay).items()
                               if k != "layout"})
        elisa.send_json(_layout("", {"US1": US1_MOSSA}))
        _fino_a(elisa, "layout_result")
        dopo = {k: v for k, v in _sezione(relay).items() if k != "layout"}
        assert dopo == prima
    finally:
        _esci(s_e)
