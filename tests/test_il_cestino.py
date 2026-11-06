"""Il cestino di 30 giorni e la soglia sul blocco (E.D., 31 ott – 6 nov 2026).

«Concordo su cestino e soglia sul blocco.» Cancellare una stanza o un file
del nodo li mette nel cestino; si riprendono per trenta giorni; poi il nodo li
vuota. Prima, toglierli davvero è un secondo gesto. E oltre 20 stanze, o 5 GB,
in un'ora, il nodo chiede una conferma esplicita.

Le fixture sono quelle di `test_cancellare_una_stanza.py`: la stessa stanza
`scavo`, con tutto quello che una stanza può avere.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import trash as trash_module
from tests.test_cancellare_una_stanza import (  # noqa: F401 — fixture
    ANNA, AUTH, BRUNO, OSCAR, _delete, _files_of, _make_room, be, client, node,
    scavo)


def _trash(client, be, room_id, who=ANNA, **query):
    return _delete(client, be, room_id, who=who, for_good=False)


def test_IL_PRIMO_GESTO_mette_nel_cestino_e_NON_TOCCA_NIENTE(client, be, node,
                                                              scavo):
    before = _files_of(node, "scavo")
    answer = _trash(client, be, "scavo")
    assert answer.status_code == 200, answer.text
    said = answer.json()
    assert said["in_trash"] is True and said["purge_after"]
    assert said["removed"] == {} and said["orphaned"] == []
    #: i file sono tutti lì (il registro ha in più il segno del cestino)
    assert _files_of(node, "scavo") == before
    assert node["assets"].head(scavo["glb"]) is not None


def test_NEL_CESTINO_non_si_apre_e_non_e_fra_le_tue(client, be, node, scavo):
    _trash(client, be, "scavo")
    be(ANNA)
    assert "scavo" not in [r["room_id"] for r in
                           client.get("/v1/rooms", headers=AUTH).json()]
    opened = client.get("/v1/rooms/scavo", headers=AUTH)
    assert opened.status_code in (404, 410), opened.text
    with pytest.raises(Exception):
        import asyncio
        asyncio.run(node["registry"].get("scavo"))


def test_SI_RIPRENDE_com_era(client, be, node, scavo):
    _trash(client, be, "scavo")
    be(ANNA)
    back = client.post("/v1/rooms/scavo/restore", headers=AUTH)
    assert back.status_code == 200, back.text
    assert back.json()["trashed_at"] is None
    assert "scavo" in [r["room_id"] for r in
                       client.get("/v1/rooms", headers=AUTH).json()]
    assert client.get("/v1/rooms/scavo", headers=AUTH).status_code == 200


def test_LO_RIPRENDE_CHI_POTEVA_CANCELLARLA(client, be, node, scavo):
    _trash(client, be, "scavo")
    be(BRUNO)
    assert client.post("/v1/rooms/scavo/restore",
                       headers=AUTH).status_code == 403
    be(OSCAR)
    assert client.post("/v1/rooms/scavo/restore",
                       headers=AUTH).status_code == 200


def test_VIA_DAVVERO_solo_dal_cestino(client, be, node, scavo):
    be(ANNA)
    refused = client.request("DELETE", "/v1/rooms/scavo", headers=AUTH,
                             json={"confirm": "scavo", "for_good": True})
    assert refused.status_code == 409 and "trash" in refused.json()["detail"]
    assert "scavo.em.json" in _files_of(node, "scavo")


def test_L_OPERATORE_VEDE_IL_CESTINO(client, be, node, scavo):
    _trash(client, be, "scavo")
    be(OSCAR)
    seen = client.get("/v1/admin/trash", headers=AUTH)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["days"] == trash_module.TRASH_DAYS
    assert [r["room_id"] for r in body["rooms"]] == ["scavo"]
    be(ANNA)
    assert client.get("/v1/admin/trash", headers=AUTH).status_code == 403


def test_IL_NODO_VUOTA_SOLO_QUELLO_SCADUTO(client, be, node, scavo):
    import asyncio
    from app import main
    _trash(client, be, "scavo")
    oggi = datetime.now(timezone.utc)
    #: oggi: non è scaduto niente
    done = asyncio.run(main.empty_due_trash(oggi))
    assert done["rooms"] == [] and "scavo.em.json" in _files_of(node, "scavo")
    #: fra trentun giorni: via, e gli asset diventano orfani come prima
    done = asyncio.run(main.empty_due_trash(oggi + timedelta(days=31)))
    assert done["rooms"] == ["scavo"], done
    assert _files_of(node, "scavo") == []
    assert node["homes"].orphan(scavo["glb"]) is not None


def test_UN_FILE_nel_cestino_poi_ripreso_poi_via(client, be, node, scavo):
    _delete(client, be, "scavo")                     # la stanza, via davvero
    be(OSCAR)
    ref = scavo["glb"]
    first = client.delete(f"/v1/admin/assets/{ref}", headers=AUTH)
    assert first.json()["in_trash"] is True
    assert node["assets"].head(ref) is not None
    orfani = client.get("/v1/admin/assets/orphans", headers=AUTH).json()
    assert ref not in [o["ref"] for o in orfani]    # sta nel cestino, non qui
    back = client.post(f"/v1/admin/assets/{ref}/restore", headers=AUTH)
    assert back.status_code == 200
    orfani = client.get("/v1/admin/assets/orphans", headers=AUTH).json()
    assert ref in [o["ref"] for o in orfani]
    refused = client.delete(f"/v1/admin/assets/{ref}?for_good=true",
                            headers=AUTH)
    assert refused.status_code == 409
    client.delete(f"/v1/admin/assets/{ref}", headers=AUTH)
    gone = client.delete(f"/v1/admin/assets/{ref}?for_good=true", headers=AUTH)
    assert gone.json()["removed"] is True and node["assets"].head(ref) is None


def test_LA_SOGLIA_SUL_BLOCCO_chiede_la_conferma(client, be, node, scavo,
                                                 monkeypatch):
    monkeypatch.setattr(trash_module, "BULK_ROOMS", 1)
    _make_room(client, be, "mostra")
    assert _trash(client, be, "scavo").status_code == 200
    stopped = _trash(client, be, "mostra")
    assert stopped.status_code == 409 and "bulk" in stopped.json()["detail"]
    be(ANNA)
    passed = client.request("DELETE", "/v1/rooms/mostra?bulk=true",
                            headers=AUTH, json={"confirm": "mostra"})
    assert passed.status_code == 200 and passed.json()["in_trash"] is True
