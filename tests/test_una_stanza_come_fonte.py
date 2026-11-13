"""Una stanza come FONTE accanto a un file (MICRO-PIU-FONTI, 13 nov 2026).

EMStudio apre insieme un em.json locale, una stanza (dal vivo) e una stanza
letta da un nodo (in sola lettura), e tra le fonti COPIA, non sposta. Dal lato
del nodo serve poco, e queste prove dicono che c'è già, sulla porta vera:

1. **la lettura**: `GET …/document` dà a chiunque sia della stanza (anche un
   viewer) il documento, il cursore e l'istante — lo STATO che la provenienza di
   una copia nomina; chi non è della stanza non legge;
2. **la scrittura della copia**: le operazioni di «Copia in…» (gli ID
   conservati, `data.derived_from` sui nodi, le relazioni) entrano per
   `POST …/ops` di un editor e restano come sono; un viewer no;
3. **i diritti**: un asset che esce «segnalato» porta con sé il suo embargo, e
   la stanza che lo riceve lo dice (`asset_rights`) come lo dice di ogni suo
   file — l'embargo continua a valere dove arriva.

Nessuna migrazione dei dati: nessuna stanza esistente cambia.
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
from app.main import app                                   # noqa: E402
from app.rooms import RoomRegistry                         # noqa: E402
from app.store import DirectorySnapshotStore               # noqa: E402

ANNA = "0000-0002-1825-0097"     # owner
CARLA = "0000-0003-1415-9265"    # editor: chi copia
BRUNO = "0000-0001-5109-3700"    # viewer: chi legge la stanza come fonte
ZENO = "0000-0002-0000-0001"     # nessuno

ROOM = "una-fonte"
HEAD = {"Authorization": "Bearer t"}
AT = "2026-11-13T05:00:00Z"
DIGEST = "sha256:" + "ab" * 32
ORIGIN = {"kind": "file", "source": "TempluMare_v9.em.json",
          "locator": "/tmp/fonti-b/TempluMare_v9.em.json",
          "graph_id": "6af9866e-96a9-5c99-a6b1-78524ae2e2c2",
          "state": {"version": "36", "at": AT}, "copied_at": AT}


def _document() -> dict:
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": ANNA},
            "graphs": {ROOM: {"graph_id": ROOM, "name": ROOM,
                              "nodes": [], "edges": []}},
            "active_graph_id": ROOM}


@pytest.fixture()
def stanza(tmp_path, monkeypatch):
    store = DirectorySnapshotStore(str(tmp_path))
    store.put(ROOM, _document())
    registry = RoomRegistry(store)
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "KEEPER", keeping.Keeper(
        ws_module._keep, after_ops=10_000, after_quiet=10_000))
    acls = InMemoryAclStore()
    acls.put(ROOM, Acl(owner=ANNA, members={CARLA: "editor",
                                            BRUNO: "viewer"}).as_dict())
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    return registry


@pytest.fixture()
def chi(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(ws_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())

    def be(orcid):
        claims = {"orcid": orcid} if orcid else {}
        for module in (ws_module, main_module):
            monkeypatch.setattr(module.authenticator, "require_token",
                                lambda request: claims)
        monkeypatch.setattr(ws_module.authenticator, "verify",
                            lambda token: claims)
    return be


@pytest.fixture()
def client():
    return TestClient(app)


def _node(node_id, node_type, name, **data):
    return {"op": "add_node", "id": node_id, "ts": AT,
            "node": {"id": node_id, "node_type": node_type, "name": name,
                     "data": {**data, "derived_from": ORIGIN}}}


def _edge(source, edge_type, target):
    return {"op": "add_edge", "id": f"{source}_{edge_type}_{target}", "ts": AT,
            "source": source, "target": target, "edge_type": edge_type}


#: what «Copia in…» sends for one unit with its proxy and a file under embargo,
#: let out signalled: the ids of the source, the provenance on every node
COPIA = [
    _node("38961f2e", "US", "SU002", description="Foundation of the Columnade"),
    _node("p-1", "property", "Dimension.height", value="5.14"),
    _node("s-1", "semantic_shape", "Shape for SU002"),
    _node("r-1", "resource", "rilievo riservato", url="RB/riservato.tif",
          checksum=DIGEST, embargo_signalled="2099-06-30"),
    _node("emb-1", "embargo", "Embargo", embargo_end="2099-06-30"),
    _edge("38961f2e", "has_property", "p-1"),
    _edge("p-1", "has_semantic_shape", "s-1"),
    _edge("s-1", "has_linked_resource", "r-1"),
    _edge("r-1", "has_embargo", "emb-1"),
]


def _post(client, ops, status=200):
    risposta = client.post(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                           json={"ops": list(ops)})
    assert risposta.status_code == status, risposta.text
    return risposta.json()


def _read(client):
    risposta = client.get(f"/v1/rooms/{ROOM}/document", headers=HEAD)
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


# ── 1 · la lettura: la stanza come fonte, il suo stato ───────────────────────

def test_1_un_viewer_legge_la_stanza_con_il_suo_stato_chi_non_e_della_stanza_no(
        client, stanza, chi):
    chi(BRUNO)
    letto = _read(client)
    assert letto["role"] == "viewer" and letto["can_write"] is False
    # lo stato che la provenienza di una copia dalla stanza nomina
    assert letto["cursor"] and letto["taken_at"]
    chi(ZENO)
    assert client.get(f"/v1/rooms/{ROOM}/document",
                      headers=HEAD).status_code == 403


# ── 2 · la scrittura della copia ─────────────────────────────────────────────

def test_2_la_copia_entra_con_gli_id_e_la_provenienza(client, stanza, chi):
    chi(CARLA)
    risposta = _post(client, COPIA)
    assert risposta["applied"] == len(COPIA), risposta
    chi(BRUNO)
    grafo = _read(client)["doc"]["graphs"][ROOM]
    nodi = {n["id"]: n for n in grafo["nodes"]}
    assert set(nodi) == {"38961f2e", "p-1", "s-1", "r-1", "emb-1"}
    # la provenienza è dei dati del nodo: la stanza la tiene com'è
    for n in nodi.values():
        assert n["data"]["derived_from"] == ORIGIN, n
    assert nodi["38961f2e"]["data"]["description"] == "Foundation of the Columnade"
    archi = {(e["source"], e["edge_type"], e["target"]) for e in grafo["edges"]}
    assert ("r-1", "has_embargo", "emb-1") in archi
    assert ("38961f2e", "has_property", "p-1") in archi


def test_2b_un_viewer_non_scrive_la_copia(client, stanza, chi):
    chi(BRUNO)
    client.post(f"/v1/rooms/{ROOM}/ops", headers=HEAD, json={"ops": COPIA[:1]})
    chi(CARLA)
    assert _read(client)["doc"]["graphs"][ROOM]["nodes"] == []


def test_2c_la_stessa_copia_due_volte_non_raddoppia_niente(client, stanza, chi):
    chi(CARLA)
    _post(client, COPIA)
    _post(client, COPIA)
    grafo = _read(client)["doc"]["graphs"][ROOM]
    assert len(grafo["nodes"]) == 5 and len(grafo["edges"]) == 4


# ── 3 · i diritti: l'embargo viaggia con l'asset ─────────────────────────────

def test_3_un_asset_uscito_segnalato_resta_sotto_embargo_nella_stanza(
        client, stanza, chi):
    from s3dgraphy import api as em
    chi(CARLA)
    _post(client, COPIA)
    documento = _read(client)["doc"]
    diritti = em.asset_rights(documento, DIGEST)
    assert diritti is not None and diritti["resource_id"] == "r-1"
    assert diritti["embargo"] == "2099-06-30"
    assert diritti["embargo_active"] is True
