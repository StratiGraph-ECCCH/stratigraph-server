"""`POST …/ops` dice i conflitti per campo: chi ha perso, e il valore perso.

s3Dgraphy calcola la decisione per campo (`FieldOutcome`, con `loser_value`)
e fino al 17 ottobre 2026 la decisione «non lasciava mai il processo»
(`docs/SYNC-FIELD-TO-CLOUD.md` §1.4). Al telefono serve vederla: chi consegna
la sera il lavoro del mattino deve sapere se qualcuno ha scritto sopra.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")
pytest.importorskip("s3dgraphy", reason="s3dgraphy not importable")

from tests.test_ops_endpoint import (CARLA, HEAD, ROOM, _rename, _units,  # noqa: E402,F401
                                     client, store, whoever)


def _post(client, ops):
    risposta = client.post(f"/v1/rooms/{ROOM}/ops", headers=HEAD,
                           json={"ops": ops})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def test_una_prima_scrittura_non_e_un_conflitto(client, store, whoever):
    whoever(CARLA)
    out = _post(client, _units("US1"))
    assert out["conflicts"] == []


def test_un_valore_sovrascritto_torna_con_il_suo_valore_perso(client, store,
                                                              whoever):
    whoever(CARLA)
    _post(client, _units("US1"))
    _post(client, _rename("US1", "primo", "2026-09-13T11:00:00Z"))
    out = _post(client, _rename("US1", "secondo", "2026-09-13T12:00:00Z"))
    assert out["applied"] == 1
    [c] = out["conflicts"]
    assert c["node_id"] == "US1" and c["field"] == "name"
    assert c["applied"] is True and c["loser_value"] == "primo"
    assert c["loser"]["at"] == "2026-09-13T11:00:00Z"


def test_un_valore_vecchio_rifiutato_NON_porta_il_conflitto_e_lo_dice_il_test(
        client, store, whoever):
    """Misurato il 17 ottobre: per un `update_field` più vecchio dello stato
    s3Dgraphy risponde `stale` con `fields: []` — il valore perdente non esce
    dalla libreria. Il rifiuto c'è (`refused`), il conflitto no: completarlo è
    un cambio in s3Dgraphy, e non è di questo server inventarlo."""
    whoever(CARLA)
    _post(client, _units("US1"))
    _post(client, _rename("US1", "nuovo", "2026-09-13T12:00:00Z"))
    out = _post(client, _rename("US1", "dal sommerso", "2026-09-13T10:30:00Z"))
    assert out["applied"] == 0
    assert [r["reason"] for r in out["refused"]] == ["stale"]
    assert out["conflicts"] == []
