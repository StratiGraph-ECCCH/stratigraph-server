"""Leggere una stanza senza socket: `GET …/document` e `GET …/ops?after=`.

Le prove 1–10 di `docs/SPEC-REST-LETTURA-STANZA.md` §5, sulla porta vera
(`TestClient`), con lo store **su disco**: il registro, e quindi il feed, esiste
solo lì (`oplog.journal_for`).

La prova che giustifica il cursore sull'arrivo è la terza, **il telefono**: A
consegna operazioni con un `ts` vecchio DOPO che B ha preso il cursore. La
prova misura anche il difetto che evita: il cursore sul `ts` (quello del socket,
`Room.replay_since`) le perde.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")
pytest.importorskip("s3dgraphy", reason="s3dgraphy not importable")

from fastapi.testclient import TestClient                  # noqa: E402

from app import keeping                                    # noqa: E402
from app import main as main_module                        # noqa: E402
from app import oplog                                      # noqa: E402
from app import ws as ws_module                            # noqa: E402
from app.access import Acl, InMemoryAclStore               # noqa: E402
from app.main import app                                   # noqa: E402
from app.rooms import RoomRegistry                         # noqa: E402
from app.store import DirectorySnapshotStore, InMemorySnapshotStore  # noqa: E402

ANNA = "0000-0002-1825-0097"     # owner
CARLA = "0000-0003-1415-9265"    # editor: il telefono
DARIO = "0000-0002-9079-593X"    # editor: il desktop
BRUNO = "0000-0001-5109-3700"    # viewer
ZENO = "0000-0002-0000-0001"     # nessuno

ROOM = "senza-socket"
HEAD = {"Authorization": "Bearer t"}


def _document() -> dict:
    return {"header": {"format": "em.json", "version": "1.0",
                       "visibility": "restricted", "owner": ANNA},
            "graphs": {ROOM: {"graph_id": ROOM, "name": ROOM,
                              "nodes": [], "edges": []}},
            "active_graph_id": ROOM}


def _acls(monkeypatch):
    acls = InMemoryAclStore()
    acls.put(ROOM, Acl(owner=ANNA, members={CARLA: "editor", DARIO: "editor",
                                            BRUNO: "viewer"}).as_dict())
    monkeypatch.setattr(ws_module, "ACL_STORE", acls)


def _relay(monkeypatch, store):
    store.put(ROOM, _document())
    registry = RoomRegistry(store)
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", registry)
    monkeypatch.setattr(ws_module, "KEEPER", keeping.Keeper(
        ws_module._keep, after_ops=10_000, after_quiet=10_000))
    _acls(monkeypatch)
    return registry


@pytest.fixture()
def durevole(tmp_path, monkeypatch):
    return _relay(monkeypatch, DirectorySnapshotStore(str(tmp_path)))


@pytest.fixture()
def volatile(monkeypatch):
    return _relay(monkeypatch, InMemorySnapshotStore())


@pytest.fixture()
def chi(monkeypatch):
    """Token applicati, e scegliamo di chi sono (come `test_ops_endpoint`)."""
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


def _unit(name, at):
    return {"op": "add_node", "id": name,
            "node": {"node_type": "US", "name": f"US {name}"}, "ts": at}


def _post(client, *ops):
    risposta = client.post(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                           json={"ops": list(ops)})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _document_of(client):
    risposta = client.get(f"/v1/rooms/{ROOM}/document", headers=HEAD)
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _feed(client, after, **params):
    risposta = client.get(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                          params={"after": after, **params})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _ids(feed):
    return [voce["op"]["id"] for voce in feed["operations"]]


# ── 1 · chi può leggere ──────────────────────────────────────────────────────

def test_1_un_viewer_legge_il_documento_e_chi_non_e_della_stanza_no(
        client, durevole, chi):
    chi(CARLA)
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    chi(BRUNO)
    letto = _document_of(client)
    assert letto["role"] == "viewer" and letto["can_write"] is False
    assert letto["room_id"] == ROOM and letto["cursor"]
    assert [n["id"] for n in letto["doc"]["graphs"][ROOM]["nodes"]] == ["US1"]
    assert _feed(client, letto["cursor"])["granted"] is True
    chi(ZENO)
    assert client.get(f"/v1/rooms/{ROOM}/document",
                      headers=HEAD).status_code == 403
    assert client.get(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                      params={"after": letto["cursor"]}).status_code == 403


def test_1b_una_stanza_che_non_esiste_e_un_404_e_non_nasce(client, durevole,
                                                           chi):
    chi(ANNA)
    assert client.get("/v1/rooms/mai-nata/document",
                      headers=HEAD).status_code == 404
    assert durevole.peek("mai-nata") is None


def test_1c_una_sola_sezione_e_un_grafo_che_non_c_e(client, durevole, chi):
    chi(CARLA)
    letto = client.get(f"/v1/rooms/{ROOM}/document", headers=HEAD,
                       params={"graph_id": ROOM}).json()
    assert list(letto["doc"]["graphs"]) == [ROOM] and letto["graph_id"] == ROOM
    assert client.get(f"/v1/rooms/{ROOM}/document", headers=HEAD,
                      params={"graph_id": "altrove"}).status_code == 404


# ── 2 · il cursore del documento ─────────────────────────────────────────────

def test_2_dal_cursore_del_documento_zero_poi_una(client, durevole, chi):
    chi(CARLA)
    cursore = _document_of(client)["cursor"]
    vuoto = _feed(client, cursore)
    assert vuoto["granted"] is True and vuoto["count"] == 0
    assert vuoto["cursor"] == cursore            # niente di nuovo, stesso punto
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    una = _feed(client, cursore)
    assert una["count"] == 1 and _ids(una) == ["US1"]
    assert una["operations"][0]["graph_id"] == ROOM
    assert una["cursor"] != cursore
    assert _feed(client, una["cursor"])["count"] == 0


# ── 3 · IL TELEFONO ──────────────────────────────────────────────────────────

def test_3_il_telefono_consegna_tardi_e_chi_ha_gia_il_cursore_lo_riceve(
        client, durevole, chi):
    """Le 10–11 offline, consegna alle 11:05; il desktop ha letto alle 11:00."""
    chi(DARIO)
    _post(client, _unit("D1", "2026-10-17T10:58:00Z"))
    cursore_desktop = _document_of(client)["cursor"]
    # il cursore che il socket darebbe al desktop: il `ts` dell'ultima vista
    cursore_su_ts = "2026-10-17T10:58:00Z"

    chi(CARLA)
    _post(client, _unit("T1", "2026-10-17T10:10:00Z"),
          _unit("T2", "2026-10-17T10:40:00Z"),
          _unit("T3", "2026-10-17T10:59:00Z"))

    chi(DARIO)
    feed = _feed(client, cursore_desktop)
    assert feed["granted"] is True
    assert _ids(feed) == ["T1", "T2", "T3"]           # tutte, in ordine d'arrivo

    # …E IL DIFETTO CHE QUESTO CURSORE EVITA, misurato sulla stessa stanza:
    # il replay del socket, che filtra sul `ts`, ne vede una sola su tre.
    room = durevole.peek(ROOM)
    sul_ts = [op["id"] for op in room.replay_since(cursore_su_ts)]
    assert sul_ts == ["T3"]


# ── 4 · la potatura ──────────────────────────────────────────────────────────

def test_4_un_cursore_piu_vecchio_della_potatura_e_incomplete(client,
                                                              durevole, chi):
    chi(CARLA)
    cursore = _document_of(client)["cursor"]
    room = durevole.peek(ROOM)
    room.journal.keep, room.journal.slack = 3, 0
    for i in range(6):
        _post(client, _unit(f"US{i}", f"2026-10-17T09:0{i}:00Z"))
    feed = _feed(client, cursore)
    assert feed["granted"] is False and feed["reason"] == "incomplete"
    assert feed["horizon"] == "pruned"
    assert feed["operations"] == [] and feed["cursor"] is None
    assert feed["resync"] == f"/v1/rooms/{ROOM}/document"
    # e il documento, riletto, dà un cursore che il registro serve di nuovo
    assert _feed(client, _document_of(client)["cursor"])["granted"] is True


# ── 5 · la compattazione ─────────────────────────────────────────────────────

def _compatta_a(monkeypatch, room, upto):
    monkeypatch.setattr(room, "gc_watermark", lambda: upto)


def test_5_dopo_una_compattazione_un_operazione_piu_vecchia_e_unsafe(
        client, durevole, chi, monkeypatch):
    chi(CARLA)
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"),
          {"op": "remove_node", "id": "US1", "ts": "2026-10-17T09:10:00Z"})
    cursore = _document_of(client)["cursor"]
    room = durevole.peek(ROOM)
    _compatta_a(monkeypatch, room, "2026-10-17T10:00:00Z")
    kept = _post(client, _unit("US2", "2026-10-17T10:30:00Z"))["kept"]
    assert room.compacted_upto == "2026-10-17T10:00:00Z"
    assert kept["compaction"]["total"] >= 1          # la tomba di US1, buttata
    # il telefono torna dal sommerso: timbro delle 09:30, dopo la pulizia
    _post(client, _unit("US3", "2026-10-17T09:30:00Z"))
    feed = _feed(client, cursore)
    assert feed["granted"] is False and feed["reason"] == "unsafe"
    assert feed["compacted_upto"] == "2026-10-17T10:00:00Z"
    assert feed["cursor"] is None and feed["operations"] == []


def test_5b_una_compattazione_con_solo_operazioni_piu_nuove_non_rifiuta(
        client, durevole, chi, monkeypatch):
    """Il caso di tutti i giorni: un desktop seduto fa compattare a ogni POST."""
    chi(CARLA)
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    cursore = _document_of(client)["cursor"]
    room = durevole.peek(ROOM)
    _compatta_a(monkeypatch, room, "2026-10-17T09:00:00Z")
    _post(client, _unit("US2", "2026-10-17T09:10:00Z"))
    _compatta_a(monkeypatch, room, "2026-10-17T09:10:00Z")
    _post(client, _unit("US3", "2026-10-17T09:20:00Z"))
    feed = _feed(client, cursore)
    assert feed["granted"] is True and _ids(feed) == ["US2", "US3"]


def test_5c_una_compattazione_che_non_ha_buttato_niente_non_rende_pericoloso_niente(
        client, durevole, chi, monkeypatch):
    """Il telefono con un desktop seduto, misurato dal vivo il 17 ottobre: la
    stanza compatta a ogni consegna, quasi sempre senza togliere niente."""
    chi(CARLA)
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    cursore = _document_of(client)["cursor"]
    room = durevole.peek(ROOM)
    _compatta_a(monkeypatch, room, "2026-10-17T10:00:00Z")
    kept = _post(client, _unit("US2", "2026-10-17T10:30:00Z"))["kept"]
    assert kept["compaction"]["total"] == 0
    _post(client, _unit("US3", "2026-10-17T09:30:00Z"))      # dal sommerso
    feed = _feed(client, cursore)
    assert feed["granted"] is True and _ids(feed) == ["US2", "US3"]


# ── 6 · un registro rifatto ──────────────────────────────────────────────────

def test_6_stanza_ricostruita_e_registro_buttato_il_vecchio_cursore_e_sconosciuto(
        client, durevole, chi):
    chi(CARLA)
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    vecchio = _document_of(client)["cursor"]
    durevole.peek(ROOM).journal.forget()
    durevole.forget(ROOM)
    _post(client, _unit("US2", "2026-10-17T09:10:00Z"))
    feed = _feed(client, vecchio)
    assert feed["granted"] is False and feed["reason"] == "unknown_cursor"
    assert feed["cursor"] is None
    assert _document_of(client)["cursor"].split(":")[0] != vecchio.split(":")[0]


def test_6b_cursori_malformati_e_di_un_futuro_che_non_c_e(client, durevole,
                                                          chi):
    chi(CARLA)
    epoca = _document_of(client)["cursor"].split(":")[0]
    for cattivo in ("2026-10-17T09:00:00Z", "niente", f"{epoca}:x",
                    f"{epoca}:999", "altra:0"):
        feed = _feed(client, cattivo)
        assert feed["reason"] == "unknown_cursor", cattivo
        assert feed["cursor"] is None


# ── 7 · i registri di prima ──────────────────────────────────────────────────

def test_7_righe_senza_seq_si_leggono_e_il_cursore_li_dentro_e_began(
        client, durevole, chi):
    # un registro scritto prima del 17 ottobre: due righe senza `seq`, sul
    # disco PRIMA che la stanza si apra (come dopo un aggiornamento del nodo)
    percorso = oplog.journal_for(ws_module.SNAPSHOT_STORE, ROOM).path
    with open(percorso, "w", encoding="utf-8") as handle:
        for i in range(2):
            handle.write(json.dumps({"at": "2026-10-01T00:00:00Z",
                                     "op": _unit(f"V{i}",
                                                 f"2026-10-01T0{i}:00:00Z")})
                         + "\n")
    chi(CARLA)
    cursore = _document_of(client)["cursor"]
    epoca, numero = cursore.split(":")
    assert numero == "2"                              # le due di prima
    stanza = durevole.peek(ROOM)
    assert len(stanza.journal.read()) == 2
    assert stanza.journal.unreadable == 0             # il marcatore non è rotto
    _post(client, _unit("US1", "2026-10-17T09:00:00Z"))
    assert _ids(_feed(client, cursore)) == ["US1"]
    prima = _feed(client, f"{epoca}:1")
    assert prima["reason"] == "incomplete" and prima["horizon"] == "began"
    stanza.journal.read()
    assert stanza.journal.unreadable == 0


# ── 8 · le pagine ────────────────────────────────────────────────────────────

def test_8_il_feed_in_due_pagine_coincide_con_il_feed_in_una(client, durevole,
                                                            chi):
    chi(CARLA)
    cursore = _document_of(client)["cursor"]
    _post(client, *[_unit(f"US{i}", f"2026-10-17T09:0{i}:00Z")
                    for i in range(5)])
    intero = _feed(client, cursore)
    prima = _feed(client, cursore, limit=3)
    assert prima["has_more"] is True and prima["count"] == 3
    seconda = _feed(client, prima["cursor"], limit=3)
    assert seconda["has_more"] is False
    assert _ids(prima) + _ids(seconda) == _ids(intero)
    assert seconda["cursor"] == intero["cursor"]


def test_8b_oltre_il_tetto_e_un_413(client, durevole, chi):
    chi(CARLA)
    cursore = _document_of(client)["cursor"]
    risposta = client.get(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                          params={"after": cursore,
                                  "limit": main_module.OPS_BATCH_MAX + 1})
    assert risposta.status_code == 413


# ── 9 · senza registro durevole, e senza cursore ─────────────────────────────

def test_9_senza_registro_durevole_e_no_durable_log(client, volatile, chi):
    chi(CARLA)
    letto = _document_of(client)
    assert letto["cursor"] is None
    feed = _feed(client, "qualcosa:0")
    assert feed["granted"] is False and feed["reason"] == "no_durable_log"


def test_9b_senza_cursore_e_no_cursor_e_non_un_errore(client, durevole, chi):
    chi(CARLA)
    feed = _feed(client, "")
    assert feed["granted"] is False and feed["reason"] == "no_cursor"
    assert feed["resync"] == f"/v1/rooms/{ROOM}/document"


# ── 10 · l'annuncio ──────────────────────────────────────────────────────────

def test_10_health_annuncia_le_due_capacita(client, durevole):
    capacita = client.get("/v1/health").json()["capabilities"]
    assert capacita["room_document_read"] is True
    assert capacita["room_ops_feed"] is True


def test_10b_senza_registro_durevole_il_feed_non_si_annuncia(client, volatile):
    capacita = client.get("/v1/health").json()["capabilities"]
    assert capacita["room_document_read"] is True
    assert capacita["room_ops_feed"] is False
