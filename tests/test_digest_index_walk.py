"""L'indice dei digest cammina UNA volta per stanza, e il nodo resta vivo mentre cammina.

Misurato il 19 novembre 2026 (`.claude/wip/reports/2026-11-19-i-diecimila-documenti.md`):
`digest_index._scan` chiamava `em.asset_rights(document, digest)` per ogni
checksum, e ognuna di quelle chiamate rileggeva tutto il documento. Quadratico:
130,6 s su una stanza da 10.000 documenti — e il cammino girava dentro un
gestore `async`, quindi per tutto quel tempo il nodo non rispondeva a nessuno,
`/health` compreso. Il primo `GET` di un audio, con due stanze da 10.000 aperte,
ha impiegato 254–291 s.

Tre cose difese qui, e ognuna fa rosso col cammino vecchio:

1. **la stessa risposta** — la passata unica dà, digest per digest, ciò che dava
   `asset_rights` sul documento intero, su ogni forma che il modulo dei diritti
   legge (diretto, catena DTC nei due versi, lapidi, id ripetuti, più grafi) e su
   grafi casuali;
2. **la soglia** — 10.000 documenti in meno di `SOGLIA_10K_S`;
3. **il nodo vivo** — `/health` risponde mentre un cammino è in corso.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import threading
import time

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")
httpx = pytest.importorskip("httpx")

from app import digest_index                                 # noqa: E402
from app.rooms import Room                                   # noqa: E402

TS = "2026-11-19T12:00:00Z"


def _sha(i: object) -> str:
    return "sha256:" + hashlib.sha256(str(i).encode()).hexdigest()


def _both_ways(document: dict) -> tuple:
    assert digest_index._READER is not None, \
        "s3dgraphy's reader moved: the index walks slowly — right, but quadratic"
    return (digest_index._scan_in_one_pass(document, *digest_index._READER),
            digest_index._scan_slowly(document))


# ── 1 · la stessa risposta ───────────────────────────────────────────────────

def _forme() -> dict:
    """Ogni strada che `s3dgraphy.rights` percorre, una per nodo."""
    nodes = [
        # diretto, scritto resource → dichiarazione
        {"id": "dir", "node_type": "resource", "data": {"checksum": _sha("dir")}},
        {"id": "lic1", "node_type": "license", "name": "CC-BY-4.0",
         "data": {"license_type": "CC-BY-4.0", "attributed_by": "0000-0002-1825-0097",
                  "attributed_at": TS}},
        # diretto, scritto al contrario (dichiarazione → resource)
        {"id": "rev", "node_type": "resource", "data": {"checksum": _sha("rev")}},
        {"id": "emb1", "node_type": "embargo", "name": "2099-01-01",
         "data": {"embargo_end": "2099-01-01"}},
        # attraverso la catena: un DTC con licenza per tutta la campagna, e i
        # due versi dei tre archi di catena
        {"id": "dtc", "node_type": "process", "data": {}},
        {"id": "lic2", "node_type": "license", "name": "CC0-1.0", "data": {}},
        {"id": "aut", "node_type": "author", "name": "Anna",
         "data": {"orcid": "0000-0002-1825-0097"}},
        {"id": "c1", "node_type": "resource", "data": {"checksum": _sha("c1")}},
        {"id": "c2", "node_type": "resource", "data": {"checksum": "SHA256:"
                                                       + _sha("c2").split(":")[1].upper()}},
        {"id": "c3", "node_type": "resource", "data": {"checksum": _sha("c3")}},
        # diretto batte catena
        {"id": "both", "node_type": "resource", "data": {"checksum": _sha("both")}},
        {"id": "lic3", "node_type": "license", "name": "CC-BY-NC-4.0", "data": {}},
        # nessun diritto: c'è, e non dice niente (non è `None`)
        {"id": "muto", "node_type": "resource", "data": {"checksum": _sha("muto")}},
        # lo stesso digest due volte: vince il primo vivo
        {"id": "dup1", "node_type": "resource", "data": {"checksum": _sha("dup")}},
        {"id": "dup2", "node_type": "resource", "data": {"checksum": _sha("dup")}},
        {"id": "lic4", "node_type": "license", "name": "MIT", "data": {}},
        # un id ripetuto: vince l'ultimo nodo con quell'id
        {"id": "twice", "node_type": "license", "name": "PRIMA", "data": {}},
        {"id": "twice", "node_type": "license", "name": "DOPO", "data": {}},
        {"id": "tw", "node_type": "resource", "data": {"checksum": _sha("tw")}},
        # la lapide: una licenza tolta non parla più
        {"id": "gone", "node_type": "resource", "data": {"checksum": _sha("gone")}},
        {"id": "lic5", "node_type": "license", "name": "TOLTA", "data": {}},
        # un nodo senza id e uno con `data` non dict non rompono niente
        {"node_type": "resource", "data": {"checksum": _sha("anon")}},
        {"id": "strano", "data": "non un dict"},
    ]
    edges = [
        {"id": "e1", "source": "dir", "target": "lic1", "edge_type": "has_license"},
        {"id": "e2", "source": "emb1", "target": "rev", "edge_type": "has_embargo"},
        {"id": "e3", "source": "dtc", "target": "lic2", "edge_type": "has_license"},
        {"id": "e4", "source": "dtc", "target": "aut", "edge_type": "has_author"},
        {"id": "e5", "source": "dtc", "target": "c1", "edge_type": "dtc_had_output"},
        {"id": "e6", "source": "c2", "target": "dtc", "edge_type": "dtc_had_input"},
        {"id": "e7", "source": "c3", "target": "dtc", "edge_type": "has_linked_resource"},
        {"id": "e8", "source": "both", "target": "dtc", "edge_type": "has_linked_resource"},
        {"id": "e9", "source": "both", "target": "lic3", "edge_type": "has_license"},
        {"id": "e10", "source": "dup1", "target": "lic4", "edge_type": "has_license"},
        {"id": "e11", "source": "tw", "target": "twice", "edge_type": "has_license"},
        {"id": "e12", "source": "gone", "target": "lic5", "edge_type": "has_license"},
        {"id": "e13", "source": "dir", "target": "c1", "edge_type": "is_after"},
    ]
    return {"graphs": {"g": {"nodes": nodes, "edges": edges}}}


def test_la_passata_unica_dice_cio_che_diceva_il_cammino_per_digest():
    room = Room("forme", _forme())
    room.apply({"op": "remove_node", "id": "lic5", "ts": TS})
    room.apply({"op": "remove_node", "id": "dup1", "ts": TS})
    fast, slow = _both_ways(room.document)
    assert fast == slow
    # …e non per caso vuoto: le forme sono state lette davvero
    assert fast[_sha("dir").split(":")[1]]["license"] == "CC-BY-4.0"
    assert fast[_sha("rev").split(":")[1]]["embargo"] == "2099-01-01"
    assert {fast[_sha(c).split(":")[1]]["via"] for c in ("c1", "c2", "c3")} == {"dtc"}
    assert fast[_sha("both").split(":")[1]]["license"] == "CC-BY-NC-4.0"
    assert fast[_sha("tw").split(":")[1]]["license"] == "DOPO"
    assert fast[_sha("gone").split(":")[1]]["license"] is None
    assert fast[_sha("dup").split(":")[1]]["resource_id"] == "dup2"
    assert fast[_sha("muto").split(":")[1]]["via"] is None


def test_piu_grafi_il_primo_che_ha_il_digest_vivo_risponde():
    def sezione(lic):
        return {"nodes": [{"id": "r", "data": {"checksum": _sha("x")}},
                          {"id": "l", "name": lic, "data": {}}],
                "edges": [{"id": "e", "source": "r", "target": "l",
                           "edge_type": "has_license"}]}
    doc = {"graphs": {"vuoto": {"nodes": [], "edges": []},
                      "a": sezione("PRIMO"), "b": sezione("SECONDO")}}
    room = Room("grafi", doc)
    fast, slow = _both_ways(room.document)
    assert fast == slow and fast[_sha("x").split(":")[1]]["license"] == "PRIMO"
    # tolto il portatore nel primo grafo, risponde il secondo — in tutti e due
    room.apply({"op": "remove_node", "id": "r", "ts": TS}, graph_id="a")
    fast, slow = _both_ways(room.document)
    assert fast == slow and fast[_sha("x").split(":")[1]]["license"] == "SECONDO"


@pytest.mark.parametrize("seed", range(40))
def test_su_grafi_casuali_le_due_strade_coincidono(seed):
    """Quello che le forme scritte a mano non pensano: grafi casuali, piccoli e
    fitti, con ogni tipo di arco che il cammino legge e qualcuno che non legge,
    id ripetuti, checksum condivisi, e lapidi su nodi e archi."""
    rnd = random.Random(seed)
    ids = [f"n{i}" for i in range(rnd.randint(4, 30))]
    kinds = ["has_license", "has_embargo", "has_author", "has_linked_resource",
             "dtc_had_output", "dtc_had_input", "is_after"]
    graphs = {}
    for g in range(rnd.randint(1, 3)):
        nodes = []
        for i in range(rnd.randint(3, 40)):
            data = {}
            if rnd.random() < 0.4:
                data["checksum"] = _sha(rnd.randint(0, 8))
            if rnd.random() < 0.3:
                data["license_type"] = rnd.choice(["CC-BY-4.0", "CC0-1.0", ""])
            if rnd.random() < 0.2:
                data["attributed_by"] = rnd.choice(["0000-0002-1825-0097",
                                                    "0000-0003-1415-9265"])
            if rnd.random() < 0.2:
                data["orcid"] = "0000-0001-5109-3700"
            nodes.append({"id": rnd.choice(ids), "name": rnd.choice(
                ["2099-01-01", "2001-01-01", "Anna", "MIT", ""]), "data": data})
        edges = [{"id": f"g{g}e{j}", "source": rnd.choice(ids),
                  "target": rnd.choice(ids), "edge_type": rnd.choice(kinds)}
                 for j in range(rnd.randint(0, 60))]
        graphs[f"g{g}"] = {"nodes": nodes, "edges": edges}
    room = Room("caso", {"graphs": graphs})
    for _ in range(rnd.randint(0, 5)):
        gid = rnd.choice(list(graphs))
        if rnd.random() < 0.5:
            room.apply({"op": "remove_node", "id": rnd.choice(ids), "ts": TS},
                       graph_id=gid)
        elif graphs[gid]["edges"]:
            room.apply({"op": "remove_edge", "ts": TS,
                        "id": rnd.choice(graphs[gid]["edges"])["id"]}, graph_id=gid)
    fast, slow = _both_ways(room.document)
    assert fast == slow


# ── 2 · la soglia ────────────────────────────────────────────────────────────

#: LA SOGLIA, e perché questo numero.
#:
#: Il cammino di una stanza si rifà dopo ogni scrittura in quella stanza, e il
#: primo che chiede un file dopo la scrittura lo aspetta. Il giorno della misura
#: una stanza da 1.000 documenti costava 1,27 s di cammino, e il resoconto l'ha
#: chiamata «la taglia che oggi consiglieremmo». La soglia dice: **una stanza da
#: 10.000 non costa più di quanto costava una da 1.000 prima del rimedio**.
#: Arrotondata a 1,5 s.
#:
#: E la distanza dai due lati: misurato sul portatile dello sviluppo il 19 nov
#: 2026 il cammino nuovo fa 10.000 documenti in 0,06 s (forma ARCH) — venticinque
#: volte sotto la soglia, abbastanza per una macchina di CI lenta; il cammino
#: vecchio ne faceva 139,5 s — novanta volte sopra, quindi un ritorno al
#: quadrato non passa per fortuna. Un ritorno a qualcosa di «solo» dieci volte
#: più lento del rimedio passerebbe: non è il compito di questa soglia.
SOGLIA_10K_S = 1.5


def _stanza_arch(n: int, campagna: bool) -> dict:
    """Come la stanza di ARCH: per ogni audio una trascrizione (`document`) e la
    risorsa col checksum, legate da `has_linked_resource`. Con `campagna`, anche
    UN processo con licenza e autore legato a tutte le risorse — la forma in cui
    una campagna intera prende una licenza sola, e quella in cui una passata
    sbagliata tornerebbe quadratica dal lato del DTC."""
    nodes, edges = [], []
    if campagna:
        nodes += [{"id": "DTC", "node_type": "process", "data": {}},
                  {"id": "LIC", "node_type": "license", "name": "CC-BY-4.0", "data": {}},
                  {"id": "AUT", "node_type": "author", "name": "ARCH", "data": {}}]
        edges += [{"id": "dl", "source": "DTC", "target": "LIC", "edge_type": "has_license"},
                  {"id": "da", "source": "DTC", "target": "AUT", "edge_type": "has_author"}]
    for i in range(n):
        rid, did = f"R.{i:05d}", f"D.{i:05d}"
        nodes.append({"id": rid, "node_type": "resource", "name": f"{rid}.ogg",
                      "data": {"checksum": _sha(f"a-{i}")}})
        nodes.append({"id": did, "node_type": "document", "name": did,
                      "description": "Trascrizione " * 20, "data": {}})
        edges.append({"id": f"{did}__hlr__{rid}", "edge_type": "has_linked_resource",
                      "source": did, "target": rid})
        if campagna:
            edges.append({"id": f"DTC__out__{rid}", "edge_type": "dtc_had_output",
                          "source": "DTC", "target": rid})
    return {"graphs": {"g": {"nodes": nodes, "edges": edges}}}


@pytest.mark.parametrize("campagna", [False, True], ids=["arch", "campagna"])
def test_diecimila_documenti_si_camminano_sotto_la_soglia(campagna):
    doc = _stanza_arch(10_000, campagna)
    t = time.perf_counter()
    out = digest_index._scan(doc)
    took = time.perf_counter() - t
    assert len(out) == 10_000
    if campagna:
        assert {r["license"] for r in out.values()} == {"CC-BY-4.0"}
    assert took < SOGLIA_10K_S, (
        f"10.000 documenti in {took:.2f} s, soglia {SOGLIA_10K_S} s: il cammino "
        f"dell'indice è tornato a crescere col quadrato (vedi SOGLIA_10K_S)")


# ── 3 · il nodo vivo ─────────────────────────────────────────────────────────

def test_health_risponde_mentre_l_indice_cammina(monkeypatch):
    """Il cammino lo teniamo aperto a mano — un `_scan` che entra, lo dice, e
    aspetta un segnale — e intanto chiediamo `/health` sullo STESSO ciclo degli
    eventi del `GET` che l'ha fatto partire. Se il cammino gira sul ciclo,
    `/health` arriva solo quando il cammino ha finito, e il test lo vede."""
    from httpx import ASGITransport

    from app import main as main_module
    from app import ws as ws_module
    from app.assets import InMemoryAssetStore
    from app.store import InMemorySnapshotStore
    from app.rooms import RoomRegistry

    assets = InMemoryAssetStore()
    ref = assets.put(b"OggS un audio qualunque", "audio/ogg")["ref"]
    monkeypatch.setattr(main_module, "ASSET_STORE", assets)
    store = InMemorySnapshotStore()
    store.put("ascolto", {"header": {"format": "em.json", "version": "1.0",
                                     "visibility": "public"},
                          "graphs": {"g": {"nodes": [
                              {"id": "R", "node_type": "resource",
                               "data": {"checksum": ref}}], "edges": []}}})
    monkeypatch.setattr(ws_module, "SNAPSHOT_STORE", store)
    monkeypatch.setattr(ws_module, "ROOMS", RoomRegistry(store))
    digest_index.INDEX.forget("ascolto")

    entrato, via = threading.Event(), threading.Event()
    stato = {"in_cammino": False}
    vero = digest_index._scan

    def cammino_lungo(document):
        stato["in_cammino"] = True
        entrato.set()
        via.wait(timeout=5)          # col cammino vecchio: il ciclo resta fermo qui
        stato["in_cammino"] = False
        return vero(document)

    monkeypatch.setattr(digest_index, "_scan", cammino_lungo)

    async def scena():
        transport = ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://nodo") as c:
            audio = asyncio.create_task(c.get(f"/v1/rooms/ascolto/asset/{ref}"))
            while not entrato.is_set():
                await asyncio.sleep(0.005)
            t = time.perf_counter()
            health = await c.get("/v1/health")
            risposta = (health.status_code, stato["in_cammino"],
                        time.perf_counter() - t)
            via.set()
            return risposta, await audio

    (codice, durante, quanto), audio = asyncio.run(scena())
    assert codice == 200
    assert durante, ("/health ha risposto solo a cammino finito: il cammino "
                     "dell'indice tiene il ciclo degli eventi")
    assert quanto < 2, f"/health in {quanto:.2f} s mentre l'indice cammina"
    assert audio.status_code == 200 and audio.content == b"OggS un audio qualunque"
