"""Il registro numera l'arrivo: `seq`, l'epoca, i marcatori, le righe di prima.

Le prove 6 e 7 di `docs/SPEC-REST-LETTURA-STANZA.md` §5, sul `Journal` da solo
(le stesse, sulla porta HTTP, sono in `test_leggere_la_stanza_senza_socket.py`).
Il marcatore d'epoca è la trappola che la specifica nomina: `read()` contava
come illeggibile ogni riga senza `"op"`, e un marcatore nuovo sarebbe finito in
`/health` come registro rovinato.
"""

from __future__ import annotations

import json

from app.oplog import Journal, parse_cursor


def _op(i, ts="2026-10-17T09:00:00Z"):
    return {"op": "add_node", "id": f"US{i}", "ts": ts}


def test_ogni_riga_porta_il_suo_numero_d_arrivo_e_il_cursore_lo_dice(tmp_path):
    j = Journal(str(tmp_path / "r.oplog.jsonl"))
    epoca, numero = parse_cursor(j.cursor())
    assert numero == 0
    assert [j.append(_op(i), at="t") for i in range(3)] == [1, 2, 3]
    assert j.cursor() == f"{epoca}:3"
    stato = j.read_rows()
    assert [r["seq"] for r in stato["rows"]] == [1, 2, 3]
    assert stato["epoch"] == epoca and stato["last_seq"] == 3


def test_il_numero_sopravvive_al_processo(tmp_path):
    percorso = str(tmp_path / "r.oplog.jsonl")
    j = Journal(percorso)
    j.append(_op(1), at="t")
    j.append(_op(2), at="t")
    cursore = j.cursor()
    rinato = Journal(percorso)                       # il riavvio
    assert rinato.cursor() == cursore
    assert rinato.append(_op(3), at="t") == 3


def test_6_un_registro_buttato_e_rifatto_cambia_epoca(tmp_path):
    percorso = str(tmp_path / "r.oplog.jsonl")
    j = Journal(percorso)
    j.append(_op(1), at="t")
    vecchio = j.cursor()
    Journal(percorso).forget()                       # un'altra istanza lo butta
    assert j.append(_op(2), at="t") == 1             # questa se ne accorge
    assert parse_cursor(j.cursor())[0] != parse_cursor(vecchio)[0]


def test_7_righe_senza_seq_restano_leggibili_e_stanno_prima_del_numero_uno(
        tmp_path):
    percorso = tmp_path / "r.oplog.jsonl"
    percorso.write_text("".join(json.dumps({"at": "t", "op": _op(i)}) + "\n"
                                for i in range(2)), encoding="utf-8")
    j = Journal(str(percorso))
    assert parse_cursor(j.cursor())[1] == 2
    assert j.append(_op(9), at="t") == 3
    assert len(j.read()) == 3 and j.unreadable == 0
    stato = j.read_rows()
    assert stato["from_seq"] == 2
    assert [r["seq"] for r in stato["rows"]] == [None, None, 3]


def test_la_potatura_salva_l_epoca_e_il_segno_di_compattazione(tmp_path):
    j = Journal(str(tmp_path / "r.oplog.jsonl"), keep=3, slack=0)
    epoca = parse_cursor(j.cursor())[0]
    j.append(_op(0), at="t")
    j.mark_compacted("2026-10-17T09:00:00Z", at="t")
    for i in range(1, 8):
        j.append(_op(i), at="t")
    stato = j.read_rows()
    assert stato["epoch"] == epoca
    assert stato["compactions"] == [{"seq": 1, "upto": "2026-10-17T09:00:00Z"}]
    assert [r["seq"] for r in stato["rows"]] == [6, 7, 8]
    assert j.compacted_upto() == "2026-10-17T09:00:00Z"
    j.read()
    assert j.unreadable == 0
