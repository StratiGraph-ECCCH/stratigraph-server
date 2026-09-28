"""Identità dal token: UN ordine solo, e lo decide il server.

════════════════════════════════════════════════════════════════════════════════
## COSA ERA STATO MISURATO (2026-09-28)

L'autore si leggeva dai claim in tre ordini diversi: la porta websocket
(`ws._identity`) `orcid, ORCID, preferred_username, sub`; gli undici endpoint HTTP
`orcid, preferred_username, sub`, scritti a mano uno per uno; StratiField
`orcid, orcid_id, https://orcid.org/id, preferred_username, sub`. Con l'ORCID
solo in `orcid_id` — un realm è libero di metterlo lì — StratiField firmava con
l'ORCID e la stanza con lo username: due autori per una persona, e l'algebra del
merge li tratta come due persone.

Adesso l'ordine è uno, in `app/identity.py` (l'unione delle liste, ORCID prima di
tutto), e ogni punto del servizio lo usa. StratiField ne tiene una copia e un suo
test la confronta con questa.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app import main as main_module
from app import operators as ops
from app import ws as ws_module
from app.identity import IDENTITY_CLAIMS, identity_of
from tests.test_chi_ce_e_chi_non_ce_piu import client  # noqa: F401

ORCID = "0000-0002-1825-0097"
#: un realm che mette l'ORCID SOLO in `orcid_id`
SOLO_ORCID_ID = {"orcid_id": ORCID, "preferred_username": "elisa", "sub": "3f1c-uuid"}


def test_l_ordine_e_l_unione_delle_liste_con_l_orcid_prima():
    assert IDENTITY_CLAIMS == ("orcid", "ORCID", "orcid_id", "https://orcid.org/id",
                               "preferred_username", "sub")


@pytest.mark.parametrize("claims,expected", [
    (SOLO_ORCID_ID, ORCID),
    ({"https://orcid.org/id": ORCID, "preferred_username": "elisa"}, ORCID),
    ({"ORCID": ORCID, "sub": "x"}, ORCID),
    ({"orcid": "  ", "orcid_id": ORCID}, ORCID),         # vuoto = silenzio
    ({"preferred_username": " elisa ", "sub": "x"}, "elisa"),
    ({"sub": 42}, "42"),
    ({}, None),
    (None, None),
])
def test_il_primo_claim_che_parla_decide(claims, expected):
    assert identity_of(claims) == expected


def test_la_porta_websocket_e_gli_operatori_leggono_lo_stesso_autore():
    assert ws_module._identity(SOLO_ORCID_ID) == ORCID
    assert ws_module._identity({**SOLO_ORCID_ID, "em_dev_mode": True}) is None
    assert ops.is_operator(SOLO_ORCID_ID, environ={"EM_OPERATORS": ORCID}) is True


def test_gli_endpoint_http_leggono_lo_stesso_autore(monkeypatch, client):  # noqa: F811
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(main_module.authenticator, "require_token",
                        lambda request: dict(SOLO_ORCID_ID))
    assert client.get("/v1/whoami").json()["orcid"] == ORCID
    assert client.get("/v1/admin/whoami").json()["orcid"] == ORCID


def test_nessun_punto_del_servizio_rilegge_i_claim_a_mano():
    """La lista si scrive UNA volta: un `get("preferred_username")` altrove è un
    quarto ordine che nasce."""
    app_dir = pathlib.Path(main_module.__file__).parent
    offenders = [f"{p.name}:{i}" for p in sorted(app_dir.glob("*.py")) if p.name != "identity.py"
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if re.search(r"""get\(\s*["'](preferred_username|orcid_id|ORCID)["']""", line)]
    assert offenders == []
