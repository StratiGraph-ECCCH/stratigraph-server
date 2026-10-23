"""La documentazione dice il vero: `/docs`, `openapi.json` e il README contro
il codice.

Misura, non ripete se stessa: le rotte si leggono dai router (`v1`,
`v1_public`, `ws_router`, e quelle appese ad `app`), non da un elenco scritto
qui; il README si legge dal file. Il 17 ottobre 2026 la tabella del README
elencava 8 operazioni su 77 e la frase sotto diceva 49: questo test esiste
perché una tabella a mano resta indietro senza che nessuno se ne accorga.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from fastapi.routing import APIRoute, APIWebSocketRoute     # noqa: E402
from fastapi.testclient import TestClient                   # noqa: E402

from app import main                                        # noqa: E402

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


@pytest.fixture(scope="module")
def spec():
    return TestClient(main.app).get("/openapi.json").json()


def _routes():
    """Ogni rotta HTTP documentabile, dai router veri."""
    for router in (main.v1, main.v1_public, main.ws_router):
        for route in router.routes:
            if isinstance(route, APIRoute) and route.include_in_schema:
                yield route
    for route in main.app.routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            yield route


def _operations(spec):
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            yield method.upper(), path, operation


def test_ogni_rotta_ha_un_riassunto_di_una_riga_e_un_tag():
    senza = [(sorted(r.methods), r.path) for r in _routes()
             if not r.summary or "\n" in r.summary or not r.tags]
    assert senza == []


def test_ogni_tag_usato_ha_una_descrizione_e_nessuna_descrizione_e_orfana(spec):
    usati = {t for _m, _p, op in _operations(spec) for t in op.get("tags", [])}
    descritti = {t["name"]: t.get("description", "") for t in spec["tags"]}
    assert usati - set(descritti) == set()
    assert set(descritti) - usati == set()
    assert all(len(d) > 20 for d in descritti.values())


def test_ogni_rotta_dichiara_che_cosa_risponde():
    mute = [(sorted(r.methods), r.path) for r in _routes()
            if r.response_model is None and not r.responses
            and r.response_class.__class__.__name__ == "DefaultPlaceholder"]
    assert mute == []


def test_le_rotte_col_token_mostrano_il_lucchetto_e_le_pubbliche_no(spec):
    chiuse = {(m, r.path_format) for r in main.v1.routes
              if isinstance(r, APIRoute) for m in r.methods}
    for method, path, operation in _operations(spec):
        assert ("security" in operation) == ((method, path) in chiuse), \
            (method, path)
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"


def test_try_it_out_funziona_dietro_un_prefisso(spec):
    """Misurato il 17 ottobre: dietro `/em` la pagina di FastAPI chiedeva
    `/openapi.json` (404). Il server relativo e la pagina che legge
    `openapi.json` relativo funzionano a `/em/` e a `/`."""
    assert spec["servers"][0]["url"] == "."
    pagina = TestClient(main.app).get("/docs").text
    assert "url: 'openapi.json'" in pagina or 'url: "openapi.json"' in pagina


def test_la_tabella_del_README_elenca_esattamente_le_rotte_di_OpenAPI(spec):
    righe = re.findall(r"^\| `([A-Z, ]+) (/[^`]*)` \|", README.read_text(
        encoding="utf-8"), flags=re.M)
    nel_readme = {(m.strip(), p) for metodi, p in righe for m in metodi.split(",")}
    in_openapi = {(m, p) for m, p, _op in _operations(spec)}
    assert in_openapi - nel_readme == set(), "mancano nel README"
    assert nel_readme - in_openapi == set(), "il README ne elenca di inesistenti"


def test_le_capacita_annunciate_corrispondono_a_rotte_che_esistono(spec):
    """`/v1/health` annuncia `capabilities` perché un client non scopra un 501
    provando: ognuna deve nominare una rotta che c'è."""
    porta = {"validate": ("POST", "/v1/validate"),
             "export_ttl": ("POST", "/v1/export-ttl"),
             "reproject": ("POST", "/v1/reproject"),
             "resolve_authority": ("GET", "/v1/resolve-authority"),
             "room_document_read": ("GET", "/v1/rooms/{room_id}/document"),
             "room_ops_feed": ("GET", "/v1/rooms/{room_id}/ops")}
    #: …e quelle del SOCKET, che OpenAPI non descrive (23 ott 2026: i frame
    #: `layout`): legate alla rotta websocket, che deve esserci
    del_socket = {"room_layout": "/v1/rooms/{room_id}/ws"}
    capacita = TestClient(main.app).get("/v1/health").json()["capabilities"]
    assert set(capacita) == set(porta) | set(del_socket), \
        "una capacità nuova va legata a una rotta"
    in_openapi = {(m, p) for m, p, _op in _operations(spec)}
    assert {porta[c] for c in capacita if c in porta} <= in_openapi
    socket = {r.path for r in main.ws_router.routes
              if isinstance(r, APIWebSocketRoute)}
    assert set(del_socket.values()) <= socket


def test_il_socket_che_OpenAPI_non_descrive_e_nominato_nella_descrizione(spec):
    socket = [r.path for r in main.ws_router.routes
              if isinstance(r, APIWebSocketRoute)]
    assert socket and all(p in spec["info"]["description"] for p in socket)


def test_l_intestazione_non_dice_piu_sola_lettura(spec):
    testo = spec["info"]["summary"] + spec["info"]["description"]
    assert "read-only" not in testo and "P0" not in testo


def test_gli_esempi_sono_risposte_vere_della_stessa_forma(spec):
    """Catturati dal vivo il 17 ottobre: qui si controlla che abbiano ancora la
    forma che il modello dichiara, così un esempio non resta indietro."""
    def chiavi(path, method):
        media = (spec["paths"][path][method]["responses"]["200"]["content"]
                 ["application/json"])
        return [e["value"] for e in media["examples"].values()]
    for valore in chiavi("/v1/rooms/{room_id}/document", "get"):
        assert set(main.RoomDocument.model_fields) == set(valore)
    for valore in chiavi("/v1/rooms/{room_id}/ops", "get"):
        assert set(valore) <= set(main.RoomOpsFeed.model_fields)
    for valore in chiavi("/v1/rooms/{room_id}/ops", "post"):
        assert set(valore) == set(main.OpsOut.model_fields)


def test_ogni_operazione_ha_un_operationId_suo_e_stabile(spec):
    """Le rotte GET+HEAD avevano lo stesso id, e il suffisso cambiava da un
    processo all'altro (misurato il 17 ottobre): un client generato da
    OpenAPI ne avrebbe perso una, e uno snapshot non sarebbe mai uguale."""
    ids = [(op["operationId"], m) for m, _p, op in _operations(spec)]
    assert len({i for i, _m in ids}) == len(ids)
    assert all(i.endswith("_" + m.lower()) for i, m in ids)
