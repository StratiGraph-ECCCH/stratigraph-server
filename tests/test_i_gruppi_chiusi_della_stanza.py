"""I gruppi chiusi viaggiano nella stanza (23 ott 2026, decisione di E.D.: tutto condiviso).

Fino a oggi lo stato aperto/chiuso dei gruppi restava sullo schermo di ognuno:
la stanza teneva le posizioni (`layout`) ma non `layout.folded_groups`, e chi
entrava riceveva i gruppi come li aveva lasciati l'import. Ora il frame
`layout` porta anche `folded: {id: chiuso?}`, la stanza lo tiene nel documento
e lo passa agli altri: **aprire un gruppo lo apre a tutti**.

Un gruppo del grafo va in `layout.folded_groups` (la lista che un em.json già
tiene); il gruppo che una vista fa per i paradati sciolti di un'unità
(EMStudio, `implicit-pd:<unità>`, chiuso se nessuno lo apre) in
`layout.open_implicit`, la lista degli aperti.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")
pytest.importorskip("s3dgraphy", reason="s3dgraphy not importable")

from tests.test_le_posizioni_della_stanza import (  # noqa: E402,F401
    ANNA, BRUNO, CARLO, ELISA, ROOM, US1, _entra, _esci, _fino_a, _layout, _sezione,
    chi, client, relay, store)


def _folds(folded, positions=None, **extra):
    frame = _layout("", positions if positions is not None else {}, folded=folded, **extra)
    if positions is None:
        del frame["payload"]["positions"]
    return frame


def test_la_porta_dice_che_i_gruppi_chiusi_viaggiano(relay, chi, client):
    socket, ws, host, _ = _entra(client, chi, ELISA)
    try:
        assert host["layout_folded"] is True
    finally:
        _esci(socket)
    health = client.get("/v1/health").json()
    assert health["capabilities"]["room_layout_folded"] is True


def test_chiudere_un_gruppo_lo_chiude_a_tutti_e_resta_per_chi_entra_dopo(relay, chi, client, store):
    sa, a, _, _ = _entra(client, chi, ELISA)
    sb, b, _, _ = _entra(client, chi, CARLO)
    try:
        a.send_json(_folds({"PD1": True}))
        arrivato = _fino_a(b, "layout")
        assert arrivato is not None
        assert arrivato["payload"]["folded"] == {"PD1": True}
        assert arrivato["payload"]["positions"] == {}
        assert arrivato["graph_id"] == ROOM
        # nessuna risposta a chi l'ha mandato quando va tutto bene
        assert _fino_a(a, "layout_result") is None
        assert _sezione(relay)["layout"]["folded_groups"] == ["PD1"]
        # …e lo riapre: aperto per tutti
        b.send_json(_folds({"PD1": False}))
        assert _fino_a(a, "layout")["payload"]["folded"] == {"PD1": False}
        assert _sezione(relay)["layout"]["folded_groups"] == []
        a.send_json(_folds({"PD1": True}))
        _fino_a(b, "layout")
    finally:
        _esci(sa)
        _esci(sb)
    # chi entra dopo lo riceve nell'istantanea
    sc, c, _, snap = _entra(client, chi, ANNA)
    try:
        assert snap["doc"]["graphs"][ROOM]["layout"]["folded_groups"] == ["PD1"]
    finally:
        _esci(sc)
    # …e la lettura REST
    chi(BRUNO)
    answer = client.get(f"/v1/rooms/{ROOM}/document", headers={"Authorization": "Bearer t"})
    assert answer.status_code == 200
    assert answer.json()["doc"]["graphs"][ROOM]["layout"]["folded_groups"] == ["PD1"]


def test_i_gruppi_della_vista_si_aprono_per_tutti(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, ELISA)
    sb, b, _, _ = _entra(client, chi, CARLO)
    try:
        a.send_json(_folds({"implicit-pd:US1": False}))
        assert _fino_a(b, "layout")["payload"]["folded"] == {"implicit-pd:US1": False}
        lay = _sezione(relay)["layout"]
        assert lay["open_implicit"] == ["implicit-pd:US1"]
        assert "implicit-pd:US1" not in lay.get("folded_groups", [])
        a.send_json(_folds({"implicit-pd:US1": True}))
        _fino_a(b, "layout")
        assert "open_implicit" not in _sezione(relay)["layout"]
    finally:
        _esci(sa)
        _esci(sb)


def test_posizioni_e_gruppi_nello_stesso_frame(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, ELISA)
    sb, b, _, _ = _entra(client, chi, CARLO)
    try:
        a.send_json(_folds({"PD1": True}, positions={"US1": US1}))
        f = _fino_a(b, "layout")["payload"]
        assert f["positions"] == {"US1": US1} and f["folded"] == {"PD1": True}
        lay = _sezione(relay)["layout"]
        assert lay["positions"]["US1"] == US1 and lay["folded_groups"] == ["PD1"]
    finally:
        _esci(sa)
        _esci(sb)


def test_un_id_che_il_grafo_non_ha_e_scartato_e_detto(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, ELISA)
    try:
        a.send_json(_folds({"NESSUNO": True, "implicit-pd:NESSUNO": False, "PD1": "sì"}))
        r = _fino_a(a, "layout_result")
        assert r is not None
        assert sorted(r["payload"]["dropped"]) == ["NESSUNO", "PD1", "implicit-pd:NESSUNO"]
        assert r["payload"]["applied"] is False
        assert not _sezione(relay).get("layout", {}).get("folded_groups")
    finally:
        _esci(sa)


def test_un_folded_che_non_e_un_oggetto_e_rifiutato(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, ELISA)
    try:
        a.send_json(_folds(["PD1"]))
        r = _fino_a(a, "layout_result")
        assert r["payload"]["code"] == "layout_malformed"
    finally:
        _esci(sa)


def test_un_lettore_non_apre_ne_chiude_i_gruppi(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, BRUNO)
    sb, b, _, _ = _entra(client, chi, CARLO)
    try:
        a.send_json(_folds({"PD1": True}))
        negato = _fino_a(a, "denied")
        assert negato is not None and negato["payload"]["verb"] == "layout"
        assert _fino_a(b, "layout") is None
        assert not _sezione(relay).get("layout", {}).get("folded_groups")
    finally:
        _esci(sa)
        _esci(sb)


def test_aprire_e_chiudere_conta_come_lavoro_non_tenuto(relay, chi, client):
    sa, a, _, _ = _entra(client, chi, ELISA)
    try:
        room = relay.peek(ROOM)
        prima = room.unsaved
        a.send_json(_folds({"PD1": True}))
        _fino_a(a, "layout_result")
        assert relay.peek(ROOM).unsaved == prima + 1
    finally:
        _esci(sa)


def test_i_gruppi_chiusi_restano_sul_disco(relay, chi, client, store):
    """Salvati come le posizioni: `request_save` li scrive, e la stanza
    dimenticata e riaperta da zero li ha."""
    from app.wire import WIRE
    sa, a, _, _ = _entra(client, chi, ELISA)
    try:
        a.send_json(_folds({"PD1": True, "implicit-pd:US2": False}))
        _fino_a(a, "layout_result")
        a.send_json({"v": WIRE, "type": "request_save", "source": "t", "payload": {}})
        assert _fino_a(a, "snapshot_written") is not None
    finally:
        _esci(sa)
    relay.forget(ROOM)
    on_disk = store.get(ROOM)["graphs"][ROOM]["layout"]
    assert on_disk["folded_groups"] == ["PD1"]
    assert on_disk["open_implicit"] == ["implicit-pd:US2"]


def test_la_stanza_ricorda_da_quali_gruppi_si_e_partiti(relay, chi, client):
    """`folded_from`: lo stato dei gruppi prima del primo cambiamento, la base
    su cui chi entra dopo calcola la sua vista (come `moved_from`); un layout
    intero lo azzera."""
    sa, a, _, _ = _entra(client, chi, ELISA)
    try:
        a.send_json(_folds({"PD1": True}))
        _fino_a(a, "layout_result")
        a.send_json(_folds({"implicit-pd:US1": False}))
        _fino_a(a, "layout_result")
        lay = _sezione(relay)["layout"]
        assert lay["folded_from"] == {"folded_groups": [], "open_implicit": []}
        assert lay["folded_groups"] == ["PD1"] and lay["open_implicit"] == ["implicit-pd:US1"]
        a.send_json(_layout("", {"US1": US1}, whole=True))
        _fino_a(a, "layout_result")
        assert "folded_from" not in _sezione(relay)["layout"]
        a.send_json(_folds({"PD1": False}))
        _fino_a(a, "layout_result")
        assert _sezione(relay)["layout"]["folded_from"] == {"folded_groups": ["PD1"], "open_implicit": ["implicit-pd:US1"]}
    finally:
        _esci(sa)
