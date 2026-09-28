"""Una sessione aperta non sopravvive al proprio token.

════════════════════════════════════════════════════════════════════════════════
## COSA ERA STATO MISURATO

La porta websocket (`ws.room_socket`) verificava il token **una volta sola**, al
join. Il ruolo si rilegge a ogni scrittura dal 30 settembre (§4 di
`test_chi_ce_e_chi_non_ce_piu.py`), il token no: una sessione aperta alle 9 con
un token da un'ora scriveva ancora alle 17, firmata da una credenziale che il
realm aveva smesso di garantire da sette ore.

Adesso il membro porta l'`exp` del token con cui è entrato, e a ogni verbo che
scrive (o che rilegge il documento intero) il cancello lo confronta con
l'orologio. Scaduto → `denied` con la frase, e la porta si chiude con **4401**:
la stessa parola del join rifiutato, perché il rimedio è lo stesso.

La porta REST (`POST /v1/rooms/{id}/ops`) non ha sessione: verifica il token a
ogni richiesta, quindi lì la scadenza c'era già. Ne resta una prova qui,
perché «c'era già» è una frase che si ripete finché qualcuno non la misura.

**La regola di casa**: ogni guardia si dimostra su un caso che la fa scattare,
e poi spegnendola — il test della rottura rimisura il danno sullo stesso giro.
"""

from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app import main as main_module
from app import ws as ws_module
from tests.test_chi_ce_e_chi_non_ce_piu import (ELISA, ROOM, _drain_join,  # noqa: F401
                                                _op, acls, client, relay)

#: l'istante del join, e la scadenza del token un'ora dopo
T0 = 1_790_000_000.0
EXP = T0 + 3600


@pytest.fixture
def firma(monkeypatch):
    """Una firma con la sua scadenza, e un orologio che si può spostare."""
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(ws_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())
    orologio = {"now": T0}
    monkeypatch.setattr(ws_module.time, "time", lambda: orologio["now"])

    def be(orcid, *, exp=EXP, key="orcid"):
        claims = {key: orcid, "exp": exp}
        monkeypatch.setattr(ws_module.authenticator, "verify",
                            lambda token: claims)
        monkeypatch.setattr(main_module.authenticator, "require_token",
                            lambda request: claims)
        return orologio
    return be


def _documento():
    return json.dumps(ws_module.ROOMS.peek(ROOM).document, ensure_ascii=False)


def test_LA_SCRITTURA_DOPO_LA_SCADENZA_E_RIFIUTATA_e_la_porta_si_chiude(
        relay, firma, client):
    orologio = firma(ELISA)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        assert _drain_join(elisa)["can_write"] is True
        elisa.send_json(_op("prima della scadenza", "2026-10-25T09:00:00Z"))
        assert elisa.receive_json()["payload"]["applied"] is True

        # …passa l'ora, e un secondo
        orologio["now"] = EXP + 1
        elisa.send_json(_op("dopo la scadenza", "2026-10-25T10:00:01Z"))
        rifiuto = elisa.receive_json()
        assert rifiuto["type"] == "denied"
        assert "expired" in rifiuto["payload"]["reason"]
        assert rifiuto["payload"]["verb"] == "op"
        with pytest.raises(WebSocketDisconnect) as chiusa:
            elisa.receive_json()
    assert chiusa.value.code == 4401

    # IL FRAME È LA CORTESIA, QUESTA È LA GUARDIA
    assert "prima della scadenza" in _documento()
    assert "dopo la scadenza" not in _documento()


def test_E_SPENTA_LA_GUARDIA_la_scrittura_scaduta_PASSEREBBE(
        relay, firma, client, monkeypatch):
    """La rottura, rimisurata: con `_lapsed` spento la stessa scrittura entra.
    È la prova che il rifiuto di sopra lo fa la guardia e non altro."""
    orologio = firma(ELISA)
    monkeypatch.setattr(ws_module, "_lapsed", lambda member, **_: False)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        orologio["now"] = EXP + 3600 * 7
        elisa.send_json(_op("sette ore dopo", "2026-10-25T17:00:00Z"))
        assert elisa.receive_json()["payload"]["applied"] is True
    assert "sette ore dopo" in _documento()


def test_PRIMA_DELLA_SCADENZA_si_scrive_fino_all_ultimo_secondo(relay, firma,
                                                                client):
    orologio = firma(ELISA)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        orologio["now"] = EXP - 1
        elisa.send_json(_op("all'ultimo secondo", "2026-10-25T09:59:59Z"))
        assert elisa.receive_json()["payload"]["applied"] is True


def test_LA_RILETTURA_DEL_DOCUMENTO_si_chiude_anche_lei(relay, firma, client):
    """Una stanza sotto embargo non si rilegge con una firma scaduta: il
    documento intero è contenuto, non presenza."""
    orologio = firma(ELISA)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        orologio["now"] = EXP + 1
        elisa.send_json({"v": 2, "type": "request_snapshot", "source": "t",
                         "payload": {}})
        assert elisa.receive_json()["type"] == "denied"
        with pytest.raises(WebSocketDisconnect) as chiusa:
            elisa.receive_json()
    assert chiusa.value.code == 4401


def test_IL_BATTITO_NON_CHIUDE_una_presenza_non_e_un_contenuto(relay, firma,
                                                                 client):
    """Un EMStudio fermo da un quarto d'ora batte ancora (`still_here`): non
    lo si butta fuori per non aver lavorato. Si chiude alla prima cosa che
    cambierebbe la stanza."""
    orologio = firma(ELISA)
    with client.websocket_connect(f"/v1/rooms/{ROOM}/ws?token=t") as elisa:
        _drain_join(elisa)
        orologio["now"] = EXP + 1
        elisa.send_json({"v": 2, "type": "still_here", "source": "t",
                         "payload": {}})
        elisa.send_json(_op("dopo il battito", "2026-10-25T10:00:02Z"))
        assert elisa.receive_json()["type"] == "denied"


def test_IL_MODO_SVILUPPO_NON_SCADE():
    """Senza OIDC non c'è un token, quindi non c'è niente che scada."""
    from app.rooms import Member

    m = Member(connection_id="c", author=None, dev_mode=True)
    m.token_exp = 0
    assert ws_module._lapsed(m, now=10**10) is False
    senza = Member(connection_id="d", author="x")
    assert ws_module._lapsed(senza, now=10**10) is False


def test_LA_PORTA_REST_LEGGE_L_IDENTITA_COME_IL_SOCKET(relay, firma, client):
    """`_acting_role` aveva una sua lettura dei claim, che saltava `ORCID`: un
    realm che scrive la chiave in maiuscolo dava due identità alla stessa
    persona, una per il socket e una per il REST. Ora è `ws._identity`."""
    firma(ELISA, key="ORCID")
    risposta = client.post(f"/v1/rooms/{ROOM}/ops", json={"ops": [
        {"op": "update_field", "node_id": "US1", "field": "description",
         "value": "dal REST", "ts": "2026-10-25T09:30:00Z"}]})
    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["applied"] == 1
    assert "dal REST" in _documento()
