"""Cancellare una stanza — e tenere i suoi asset (MICRO «spazio 3D 2», Parte 6).

E.D., 16 ottobre 2026: l'API del nodo non aveva nessuna operazione per
cancellare una stanza. Adesso c'è, con le tre proprietà che `RoomRegistry.archive`
prometteva da settembre («a separate act with a separate name and a
confirmation»):

* `DELETE /v1/rooms/{id}` — al PROPRIETARIO della stanza e all'OPERATORE del nodo,
  a nessun altro (un admin della stanza dà ruoli, non decide se la stanza esiste);
* con il nome della stanza ripetuto nel corpo, `{"confirm": "<id>"}`;
* **gli asset restano.** Lo store è indirizzato dal contenuto e condiviso fra le
  stanze: un asset che nessun'altra stanza tiene diventa ORFANO — resta nello
  store, con la data e la stanza d'origine — e si vede in
  `GET /v1/admin/assets/orphans`. Si cancella, uno per volta, con
  `DELETE /v1/admin/assets/{ref}`, che rifiuta (409) un asset ancora citato. Si
  RIUSA caricando gli stessi byte in una stanza: lo store non li prende due
  volte, e l'asset torna a casa.

Gli store sono quelli su DIRECTORY (snapshot, registro, ACL, inviti, oplog,
case degli asset) dentro `tmp_path`, così «tutto quello che è della stanza è
sparito» si misura guardando i file, non fidandosi delle risposte.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from fastapi.testclient import TestClient                    # noqa: E402

from app import asset_homes                                  # noqa: E402
from app import main as main_module                          # noqa: E402
from app import oplog as oplog_module                        # noqa: E402
from app import uploads as uploads_module                    # noqa: E402
from app import ws as ws_module                              # noqa: E402
from app.access import Acl, DirectoryAclStore                # noqa: E402
from app.asset_homes import DirectoryAssetHomes              # noqa: E402
from app.assets import InMemoryAssetStore                    # noqa: E402
from app.blend_backups import (BlendBackups, InMemoryBackupBlobs,  # noqa: E402
                               InMemoryBackupRegister)
from app.corpus import InMemoryCorpusStore, ResidentCorpus   # noqa: E402
from app.invites import DirectoryInviteStore                 # noqa: E402
from app.main import app                                     # noqa: E402
from app.rooms import RoomRegistry                           # noqa: E402
from app.store import DirectoryRoomStore, DirectorySnapshotStore  # noqa: E402
from app.uploads import UploadSessions                       # noqa: E402

ANNA = "0000-0002-1825-0097"     # proprietaria di `scavo`
BRUNO = "0000-0001-5109-3700"    # editor in `scavo`
DORA = "0000-0003-1415-9265"     # admin (della stanza) in `scavo`
ELIO = "0000-0002-9079-593X"     # estraneo
OSCAR = "0000-0001-2345-6789"    # l'operatore del nodo, membro di niente

GLB = b"glTF\x02\x00\x00\x00" + b"US 1, la prova" * 40
FOTO = b"\xff\xd8\xff il podio, lato nord"
AUTH = {"Authorization": "Bearer t"}


def container(room_id, refs=(), *, owner=ANNA):
    nodes = [{"id": f"r{i}", "node_type": "resource", "name": f"R{i}",
              "data": {"checksum": ref}} for i, ref in enumerate(refs)]
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": owner},
            "graphs": {room_id: {"graph_id": room_id, "name": room_id,
                                 "nodes": nodes, "edges": []}},
            "active_graph_id": room_id}


@pytest.fixture()
def node(tmp_path, monkeypatch):
    snap = tmp_path / "snap"
    snapshots = DirectorySnapshotStore(snap)
    registry = RoomRegistry(snapshots, DirectoryRoomStore(str(snap)))
    acls = DirectoryAclStore(snap)
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", snapshots)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)
    monkeypatch.setattr(main_module, "INVITE_STORE", DirectoryInviteStore(str(snap)))
    assets = InMemoryAssetStore()
    monkeypatch.setattr(main_module, "ASSET_STORE", assets)
    homes = DirectoryAssetHomes(tmp_path / "homes")
    monkeypatch.setattr(asset_homes, "ASSET_HOMES", homes)
    monkeypatch.setattr(uploads_module, "SESSIONS",
                        UploadSessions(tmp_path / "uploads"))
    backups = BlendBackups(InMemoryBackupBlobs(), InMemoryBackupRegister())
    monkeypatch.setattr(main_module, "BACKUPS", backups)
    corpus = ResidentCorpus(InMemoryCorpusStore())
    monkeypatch.setattr(main_module, "RESIDENT", corpus)
    monkeypatch.setattr(main_module, "CORPUS_STORE", corpus.store)
    monkeypatch.setenv("EM_OPERATORS", OSCAR)
    return {"snap": snap, "snapshots": snapshots, "registry": registry,
            "acls": acls, "assets": assets, "homes": homes,
            "backups": backups, "corpus": corpus, "tmp": tmp_path}


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


def _make_room(client, be, room_id, *, who=ANNA):
    be(who)
    made = client.post("/v1/rooms", headers=AUTH,
                       json={"room_id": room_id, "title": room_id})
    assert made.status_code == 201, made.text


def _upload(client, be, room_id, data, *, who=ANNA, media="model/gltf-binary"):
    be(who)
    answer = client.put(f"/v1/rooms/{room_id}/asset?media_type={media}",
                        content=data, headers=AUTH)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _cite(node, room_id, *refs, owner=ANNA):
    node["snapshots"].put(room_id, container(room_id, refs, owner=owner))
    node["registry"].forget(room_id)


def _delete(client, be, room_id, *, who=ANNA, confirm=None, body=True):
    be(who)
    kwargs = {"headers": AUTH}
    if body:
        kwargs["json"] = {"confirm": room_id if confirm is None else confirm}
    return client.request("DELETE", f"/v1/rooms/{room_id}", **kwargs)


def _orphans(client, be, query=""):
    be(OSCAR)
    answer = client.get(f"/v1/admin/assets/orphans{query}", headers=AUTH)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _files_of(node, room_id):
    return sorted(p.name for p in node["snap"].iterdir()
                  if p.name.startswith(room_id + "."))


@pytest.fixture()
def scavo(client, be, node):
    """Una stanza con tutto quello che una stanza può avere."""
    _make_room(client, be, "scavo")
    glb = _upload(client, be, "scavo", GLB)["ref"]
    _cite(node, "scavo", glb)
    be(ANNA)
    assert client.put(f"/v1/rooms/scavo/members/{BRUNO}", headers=AUTH,
                      json={"role": "editor"}).status_code == 200
    assert client.put(f"/v1/rooms/scavo/members/{DORA}", headers=AUTH,
                      json={"role": "admin"}).status_code == 200
    acl = Acl.from_dict(node["acls"].get("scavo"))
    acl.groups["squadra"] = acl.members[BRUNO]
    node["acls"].put("scavo", acl.as_dict())
    assert client.post("/v1/rooms/scavo/invites", headers=AUTH,
                       json={"role": "viewer"}).status_code == 201
    assert client.post("/v1/rooms/scavo/uploads", headers=AUTH,
                       json={"size": 4096}).status_code == 201
    node["backups"].archive("scavo", b"BLENDER-v402 una scena", orcid=ANNA)
    journal = oplog_module.journal_for(node["snapshots"], "scavo")
    journal.append({"op": "add_node", "id": "x"}, at="2026-10-16T08:00:00Z")
    assert _files_of(node, "scavo") == ["scavo.acl.json", "scavo.em.json",
                                        "scavo.invites.json",
                                        "scavo.oplog.jsonl", "scavo.room.json"]
    return {"glb": glb}


# ═══ 1 · CHI PUÒ ═══════════════════════════════════════════════════════════

def test_LA_PROPRIETARIA_cancella_e_TUTTO_QUELLO_DELLA_STANZA_se_ne_va(
        client, be, node, scavo):
    answer = _delete(client, be, "scavo")
    assert answer.status_code == 200, answer.text
    said = answer.json()
    assert said["deleted_as"] == "owner" and said["deleted_by"] == ANNA
    assert said["complete"] is True and said["errors"] == []
    removed = said["removed"]
    assert removed["containers"] == ["scavo"]
    assert removed["record"] is True and removed["acl"] is True
    assert removed["oplog"] is True
    assert removed["invites"] == 1 and removed["uploads"] == 1
    assert removed["members"] == 2 and removed["group_grants"] == 1
    assert removed["blend_records"] == 1 and len(said["blend_blobs_kept"]) == 1

    #: …misurato sui file, non sulla risposta
    assert _files_of(node, "scavo") == []
    assert node["registry"].peek("scavo") is None
    assert uploads_module.SESSIONS.for_room("scavo") == []
    assert node["backups"].register.records("scavo") == []
    #: …e per l'API la stanza non c'è più
    be(ANNA)
    assert client.get("/v1/rooms/scavo", headers=AUTH).status_code == 404
    assert "scavo" not in [r["room_id"] for r in
                           client.get("/v1/rooms", headers=AUTH).json()]
    #: …e quel 404 non ha riaperto niente
    assert node["registry"].peek("scavo") is None
    assert _files_of(node, "scavo") == []


def test_L_OPERATORE_DEL_NODO_cancella_senza_essere_nella_stanza(
        client, be, node, scavo):
    answer = _delete(client, be, "scavo", who=OSCAR)
    assert answer.status_code == 200, answer.text
    assert answer.json()["deleted_as"] == "operator"
    assert _files_of(node, "scavo") == []


@pytest.mark.parametrize("who", [BRUNO, DORA, ELIO], ids=["editor", "admin", "estraneo"])
def test_UN_MEMBRO_o_UN_ESTRANEO_no(client, be, node, scavo, who):
    """Anche un ADMIN della stanza: dà i ruoli, non decide se la stanza esiste."""
    answer = _delete(client, be, "scavo", who=who)
    assert answer.status_code == 403
    assert "owner" in answer.json()["detail"]
    assert len(_files_of(node, "scavo")) == 5


@pytest.mark.parametrize("confirm,body", [(None, False), ("", True),
                                          ("Scavo", True), ("mostra", True)],
                         ids=["senza-corpo", "vuota", "maiuscola", "altra-stanza"])
def test_SENZA_LA_CONFERMA_GIUSTA_non_si_tocca_niente(client, be, node, scavo,
                                                      confirm, body):
    answer = _delete(client, be, "scavo", confirm=confirm, body=body)
    assert answer.status_code == 400
    assert '"confirm": "scavo"' in answer.json()["detail"]
    assert len(_files_of(node, "scavo")) == 5
    assert _orphans(client, be) == []


def test_UNA_STANZA_CHE_NON_C_E_e_404_e_non_nasce(client, be, node):
    answer = _delete(client, be, "mai-fatta")
    assert answer.status_code == 404
    assert node["registry"].peek("mai-fatta") is None
    assert _files_of(node, "mai-fatta") == []


def test_UN_FANTASMA_IN_MEMORIA_non_e_una_stanza_e_non_resta(client, be, node):
    """La trappola del 15 ottobre: una copia vuota in memoria, costruita da una
    lettura, senza registro e senza contenitore. Non rende cancellabile niente
    (404) — e non viene lasciata lì."""
    import asyncio
    asyncio.run(node["registry"].get("fantasma"))
    assert node["registry"].peek("fantasma") is not None
    assert _delete(client, be, "fantasma").status_code == 404
    assert node["registry"].peek("fantasma") is None
    assert _files_of(node, "fantasma") == []


def test_CON_QUALCUNO_DENTRO_e_409(client, be, node, scavo):
    """Una sessione che esce dopo la cancellazione riscriverebbe il documento."""
    import asyncio
    room = asyncio.run(node["registry"].get("scavo"))
    room.sockets["c1"] = object()
    answer = _delete(client, be, "scavo")
    assert answer.status_code == 409
    assert "Leave the room" in answer.json()["detail"]
    assert len(_files_of(node, "scavo")) == 5


def test_UN_CONTENITORE_CHE_UN_ALTRA_STANZA_NOMINA_resta(client, be, node, scavo):
    be(ANNA)
    client.post("/v1/rooms", headers=AUTH,
                json={"room_id": "lettura", "container_refs": ["lettura", "scavo"]})
    said = _delete(client, be, "scavo").json()
    assert said["containers_kept"] == ["scavo"] and said["removed"]["containers"] == []
    assert node["snapshots"].get("scavo") is not None
    assert "scavo.room.json" not in _files_of(node, "scavo")


# ═══ 2 · GLI ASSET RESTANO, E QUELLI DI NESSUNO SONO ORFANI ═════════════════

def test_GLI_ASSET_RESTANO_e_diventano_orfani_con_ORIGINE_e_DATA(
        client, be, node, scavo):
    said = _delete(client, be, "scavo").json()
    glb = scavo["glb"]
    assert said["orphaned"] == [glb]
    assert said["assets"] == [{"ref": glb, "orphan": True, "still_held_by": [],
                               "in_corpus": False, "present": True}]
    #: i byte non si sono mossi
    assert node["assets"].get(glb) == GLB
    listed = _orphans(client, be)
    assert len(listed) == 1
    orphan = listed[0]
    assert orphan["ref"] == glb and orphan["sha256"] == glb.split(":", 1)[1]
    assert orphan["media_type"] == "model/gltf-binary"
    assert orphan["size"] == len(GLB)
    assert orphan["origin_room"] == "scavo" and orphan["deleted_by"] == ANNA
    assert orphan["orphaned_at"] == said["deleted_at"]
    #: …e il segno DURA: un processo nuovo lo rilegge dal disco
    again = DirectoryAssetHomes(node["tmp"] / "homes")
    assert again.orphan(glb)["origin_room"] == "scavo"
    assert again.home(glb) is None and again.rooms_of(glb) == []


def test_UN_ASSET_CHE_UN_ALTRA_STANZA_CITA_non_e_orfano(client, be, node, scavo):
    _make_room(client, be, "mostra")
    _cite(node, "mostra", scavo["glb"])
    said = _delete(client, be, "scavo").json()
    assert said["orphaned"] == []
    assert said["assets"][0]["still_held_by"] == ["mostra"]
    assert _orphans(client, be) == []
    #: …e quando se ne va anche l'ultima, lo è — con l'ULTIMA come origine
    said = _delete(client, be, "mostra").json()
    assert said["orphaned"] == [scavo["glb"]]
    assert [o["origin_room"] for o in _orphans(client, be)] == ["mostra"]


def test_CARICATO_IN_DUE_STANZE_la_casa_passa_all_altra(client, be, node, scavo):
    _make_room(client, be, "mostra")
    _upload(client, be, "mostra", GLB)
    assert node["homes"].home(scavo["glb"]) == "scavo"
    said = _delete(client, be, "scavo").json()
    assert said["orphaned"] == [] and said["assets"][0]["still_held_by"] == ["mostra"]
    assert node["homes"].home(scavo["glb"]) == "mostra"
    assert node["homes"].moves(scavo["glb"])[-1]["why"] == "room deleted"


def test_UN_ASSET_DOCUMENTATO_NEL_CORPUS_non_e_orfano(client, be, node, scavo):
    node["corpus"].store.put({"graph_id": "corpus", "edges": [], "nodes": [
        {"id": "r", "node_type": "resource", "name": "R",
         "data": {"checksum": scavo["glb"]}}]})
    said = _delete(client, be, "scavo").json()
    assert said["orphaned"] == [] and said["assets"][0]["in_corpus"] is True


def test_I_FILTRI_tipo_e_date(client, be, node, scavo):
    _upload(client, be, "scavo", FOTO, media="image/jpeg")
    _delete(client, be, "scavo")
    assert len(_orphans(client, be)) == 2
    assert [o["media_type"] for o in _orphans(client, be, "?type=model")] == \
        ["model/gltf-binary"]
    assert [o["media_type"] for o in _orphans(client, be, "?type=image/jpeg")] == \
        ["image/jpeg"]
    assert _orphans(client, be, "?type=text") == []
    day = _orphans(client, be)[0]["orphaned_at"][:10]
    assert len(_orphans(client, be, f"?since={day}&until={day}")) == 2
    assert _orphans(client, be, "?since=2999-01-01") == []
    assert _orphans(client, be, "?until=2000-01-01") == []


def test_L_ELENCO_DEGLI_ORFANI_e_dell_operatore(client, be, node, scavo):
    _delete(client, be, "scavo")
    be(ANNA)
    assert client.get("/v1/admin/assets/orphans", headers=AUTH).status_code == 403


# ═══ 3 · CANCELLARE UN ASSET: MAI UNO CITATO, SÌ UN ORFANO ══════════════════

def test_L_ADMIN_RIFIUTA_UN_ASSET_CITATO_e_TOGLIE_UN_ORFANO(client, be, node, scavo):
    _make_room(client, be, "mostra")
    _cite(node, "mostra", scavo["glb"])
    be(OSCAR)
    refused = client.delete(f"/v1/admin/assets/{scavo['glb']}", headers=AUTH)
    assert refused.status_code == 409 and "scavo" in refused.json()["detail"]
    _delete(client, be, "scavo")
    _delete(client, be, "mostra")
    assert [o["ref"] for o in _orphans(client, be)] == [scavo["glb"]]
    be(OSCAR)
    done = client.delete(f"/v1/admin/assets/{scavo['glb']}", headers=AUTH)
    assert done.status_code == 200 and done.json()["removed"] is True
    assert node["assets"].head(scavo["glb"]) is None
    assert _orphans(client, be) == []
    #: …e il suo record se n'è andato con i byte
    assert node["homes"].orphan(scavo["glb"]) is None
    assert node["homes"].rooms_of(scavo["glb"]) == []


# ═══ 4 · UN ORFANO SI RIUSA: GLI STESSI BYTE NON SI RIMETTONO ═══════════════

def test_RICARICARE_UN_ORFANO_lo_ricollega_senza_duplicarlo(client, be, node, scavo):
    _delete(client, be, "scavo")
    objects = node["assets"].count()
    _make_room(client, be, "scavo-2")
    #: misurato: HEAD nella stanza nuova dice 200 — un orfano non ha casa, e
    #: allora la casa è la porta (D-C, `_participants_gate`)
    be(ANNA)
    head = client.head(f"/v1/rooms/scavo-2/asset/{scavo['glb']}", headers=AUTH)
    assert head.status_code == 200 and "X-EM-Home-Room" not in head.headers
    again = _upload(client, be, "scavo-2", GLB)
    assert again["ref"] == scavo["glb"]
    assert again["created"] is False and again["home"] == "scavo-2"
    assert node["assets"].count() == objects
    assert _orphans(client, be) == []
    assert node["homes"].orphan(scavo["glb"]) is None
    assert node["homes"].home(scavo["glb"]) == "scavo-2"


def test_CITARLO_IN_UN_GRAFO_lo_toglie_dall_elenco(client, be, node, scavo):
    """La seconda via, senza ricaricare: una stanza il cui grafo lo cita."""
    _delete(client, be, "scavo")
    _make_room(client, be, "scavo-2")
    _cite(node, "scavo-2", scavo["glb"])
    assert _orphans(client, be) == []


def test_CARICARLO_IN_UNA_STANZA_CHE_NON_C_E_non_lo_riprende(client, be, node, scavo):
    _delete(client, be, "scavo")
    _upload(client, be, "nessuna", GLB)
    assert [o["ref"] for o in _orphans(client, be)] == [scavo["glb"]]
