"""I documenti a casa loro: byte in, gli stessi byte fuori.

## Perché questo file esiste e cosa si rifiuta di fare

Il criterio di accettazione della casa dei documenti è uno solo e non è
un'opinione: **i byte entrati devono uscire identici, con la stessa impronta.**
Tutto il resto dello schema — la colonna `doc` generata, l'indice GIN, il rifiuto
di un documento rotto — è al servizio di quella frase, e ognuna di queste prove
la misura su un documento vero invece che su `{"a": 1}`.

`{"a": 1}` non avrebbe misurato niente: `jsonb` normalizza solo quando c'è
qualcosa da normalizzare, e un documento di due byte non ha chiavi fuori ordine,
né duplicati, né UTF-8 multibyte. Le tre cose che possono rompere la fedeltà dei
byte sono esattamente quelle, quindi ci vuole un em.json vero — e ce n'è uno da
590 KB nel corpus di esempio, che è il più grande su questa macchina.

## Perché saltano senza un database, invece di fingere

Non c'è un finto Postgres in questo file. Un doppio di una tabella con due
colonne **generate** dovrebbe reimplementare la normalizzazione di `jsonb` per
poterla contraddire, cioè dovrebbe sapere già la risposta che qui si sta
misurando. `EM_TEST_DOCUMENTS_DSN` punta a un Postgres vero; senza, le prove
saltano dicendo perché — un salto dichiarato vale più di un verde inventato.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import uuid

import pytest

from app import documents as docs
from app.store import (DirectorySnapshotStore, PostgresSnapshotStore,
                       describe, store_from_env)

DSN = os.environ.get("EM_TEST_DOCUMENTS_DSN", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="serve un Postgres vero: EM_TEST_DOCUMENTS_DSN='host=… dbname=… "
           "user=… password=…'. Un doppio in memoria non può misurare una "
           "colonna generata.")


# ── i documenti su cui si misura ─────────────────────────────────────────────

def _candidates() -> list[pathlib.Path]:
    """Gli em.json veri che questa macchina ha, dal più grande al più piccolo.

    Cercati **fuori dal repo** di proposito: `stratigraph-server` non ne ha
    nemmeno uno fra le sue fixture (misurato: zero `*.em.json` in `tests/`), e i
    documenti veri di questo ecosistema stanno nei repo vicini. Se non ce n'è
    nessuno le prove saltano — non inventano un documento.
    """
    github = pathlib.Path(__file__).resolve().parent.parent.parent
    found: list[pathlib.Path] = []
    for where in ("EXAMPLES_EM_AI_WORKFLOW", "s3Dgraphy/tests/fixtures",
                  "EMStudio/frontend/testdata"):
        base = github / where
        if base.is_dir():
            found.extend(p for p in base.rglob("*.em.json") if p.is_file())
    return sorted(found, key=lambda p: p.stat().st_size, reverse=True)


@pytest.fixture(scope="module")
def documento() -> pathlib.Path:
    found = _candidates()
    if not found:
        pytest.skip("nessun em.json vero su questa macchina")
    return found[0]


@pytest.fixture()
def store(tmp_path):
    """Uno store vero su un database vero, che si porta via quello che scrive."""
    created = PostgresSnapshotStore(DSN, journal_root=str(tmp_path))
    yield created
    with created.pool.connection() as conn:
        conn.execute(f"DELETE FROM {docs.TABLE} WHERE project_id LIKE %s",
                     ("prova-%",))
        conn.commit()


def _id() -> str:
    return "prova-" + uuid.uuid4().hex[:12]


# ── S1 · il criterio di accettazione ─────────────────────────────────────────

def test_byte_in_byte_fuori_su_un_em_json_vero(store, documento):
    """LA prova della notte, nella forma letterale: i byte del file.

    Non si passa da `put`, che riserializza: qui entrano **i byte esatti del file
    su disco** e si misura che quelli escano, con l'impronta che il database ha
    calcolato da sé. Un em.json vero e non un documento inventato, perché sono le
    chiavi fuori ordine, i duplicati e l'UTF-8 multibyte le tre cose che possono
    rompere la fedeltà, e un documento inventato non ne ha nessuna delle tre.
    """
    byte = documento.read_bytes()
    atteso = hashlib.sha256(byte).hexdigest()
    project = _id()
    with store.pool.connection() as conn:
        conn.execute(f"INSERT INTO {docs.TABLE} (project_id, revision, raw) "
                     f"VALUES (%s, 0, %s)", (project, byte))
        conn.commit()

    raw, revision, sha = store.raw_at(project)
    assert revision == 0
    assert raw == byte, (
        f"{documento.name} ({len(byte)} byte): usciti diversi da come sono "
        f"entrati")
    assert sha == atteso, (
        "l'impronta generata dal database non è quella del file entrato")


def test_il_giro_completo_dello_store_e_fedele(store, documento):
    """E la stessa cosa passando da `put`/`get`, che è la strada che il relay fa.

    Qui i byte non sono quelli del file — `put` riserializza — quindi quello che
    si misura è l'altra metà: che il documento riletto sia quello scritto, e che
    l'impronta in tabella sia quella dei byte che ci sono davvero.
    """
    entrato = json.loads(documento.read_text(encoding="utf-8"))
    project = _id()
    store.put(project, entrato)

    raw, _revision, sha = store.raw_at(project)
    assert sha == hashlib.sha256(raw).hexdigest()
    assert store.get(project) == entrato


def test_jsonb_normalizza_e_per_questo_il_digest_sta_sui_byte(store):
    """La ragione per cui `sha256` è generato da `raw` e non da `doc`.

    Byte scelti perché `jsonb` li cambia di sicuro: chiavi fuori ordine, una
    chiave duplicata, e UTF-8 multibyte. Se l'impronta fosse calcolata sul
    `jsonb` questo test la vedrebbe cambiare.
    """
    project = _id()
    byte = b'{"b": 2, "a": 1, "a": 3, "n": "citt\xc3\xa0"}'
    with store.pool.connection() as conn:
        conn.execute(f"INSERT INTO {docs.TABLE} (project_id, revision, raw) "
                     f"VALUES (%s, 0, %s)", (project, byte))
        conn.commit()
        raw, doc, sha = conn.execute(
            f"SELECT raw, doc, sha256 FROM {docs.TABLE} WHERE project_id = %s",
            (project,)).fetchone()

    assert bytes(raw) == byte, "i byte in tabella non sono quelli entrati"
    assert sha == hashlib.sha256(byte).hexdigest()
    assert doc == {"a": 3, "b": 2, "n": "città"}
    assert json.dumps(doc, ensure_ascii=False,
                      separators=(", ", ": ")).encode("utf-8") != byte, (
        "jsonb doveva normalizzare questi byte; se non lo fa, il test non sta "
        "più misurando la ragione per cui le colonne sono generate")


def test_un_documento_rotto_non_entra(store):
    """Non si archivia un documento che non è JSON: la colonna generata non si
    può calcolare, e l'INSERT fallisce **prima** di avere una riga."""
    import psycopg

    project = _id()
    with store.pool.connection() as conn:
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            conn.execute(f"INSERT INTO {docs.TABLE} (project_id, revision, raw) "
                         f"VALUES (%s, 0, %s)", (project, b"non sono json"))
        conn.rollback()
        resto = conn.execute(f"SELECT count(*) FROM {docs.TABLE} "
                             f"WHERE project_id = %s", (project,)).fetchone()[0]
    assert resto == 0


def test_utf8_valido_ma_non_json_e_utf8_rotto(store):
    """Due modi diversi di essere inaccettabile, e devono fallire tutti e due.

    Il secondo è quello che si dimentica: byte che non sono UTF-8 affatto. Lì non
    fallisce il cast a `jsonb` ma la conversione dentro l'involucro immutabile —
    ed è giusto che fallisca lì, perché una tabella che accettasse byte non-UTF8
    avrebbe una colonna `doc` impossibile da calcolare per sempre.
    """
    import psycopg

    with store.pool.connection() as conn:
        for byte in (b"[1, 2,", b"\xff\xfe non sono utf8"):
            with pytest.raises(psycopg.Error):
                conn.execute(
                    f"INSERT INTO {docs.TABLE} (project_id, revision, raw) "
                    f"VALUES (%s, 0, %s)", (_id(), byte))
            conn.rollback()


# ── S1 · ogni revisione è una riga ───────────────────────────────────────────

def test_ogni_revisione_e_una_riga_e_la_precedente_resta(store):
    project = _id()
    store.put(project, {"nodes": [], "passo": 1})
    store.put(project, {"nodes": [], "passo": 2})
    store.put(project, {"nodes": [], "passo": 3})

    storia = store.revisions(project)
    assert [r["revision"] for r in storia] == [0, 1, 2]
    assert store.get(project)["passo"] == 3
    assert json.loads(store.raw_at(project, 0)[0])["passo"] == 1, (
        "la prima revisione non è più leggibile: `put` ha sostituito invece di "
        "aggiungere")


def test_scrivere_gli_stessi_byte_non_e_una_revisione(store):
    """Un salvataggio che non cambia niente non fa avanzare la storia."""
    project = _id()
    documento = {"nodes": [], "passo": 1}
    store.put(project, documento)
    store.put(project, dict(documento))
    store.put(project, documento)
    assert [r["revision"] for r in store.revisions(project)] == [0]


def test_rooms_elenca_i_progetti(store):
    """Il terzo metodo, quello che il gate IIIF chiede a ogni store."""
    a, b = _id(), _id()
    store.put(a, {"nodes": []})
    store.put(b, {"nodes": []})
    elenco = store.rooms()
    assert a in elenco and b in elenco


# ── S4 · SQL restringe ───────────────────────────────────────────────────────

def _con_digest(digest: str) -> dict:
    return {"graphs": {"g": {"nodes": [
        {"id": "n1", "data": {"checksum": digest}},
        {"id": "n2", "data": {}},
    ]}}}


def test_ricerca_per_digest_trova_solo_chi_lo_cita(store):
    cercato = "a" * 64
    altro = "b" * 64
    mio, estraneo = _id(), _id()
    store.put(mio, _con_digest(cercato))
    store.put(estraneo, _con_digest(altro))

    trovati = [p for p, _r in docs.projects_citing_digest(store.pool, cercato)]
    assert mio in trovati
    assert estraneo not in trovati


def test_la_ricerca_accetta_il_digest_scritto_nei_due_modi(store):
    cercato = "c" * 64
    mio = _id()
    store.put(mio, _con_digest(cercato))
    for scritto in (cercato, cercato.upper(), f"sha256:{cercato}"):
        trovati = [p for p, _r in docs.projects_citing_digest(store.pool, scritto)]
        assert mio in trovati, f"non trovato quando scritto «{scritto}»"


def test_la_ricerca_guarda_lultima_revisione_non_la_storia(store):
    """Un digest TOLTO da uno studio non deve continuare a rispondere.

    È la differenza fra una tabella di revisioni e un archivio che accumula: con
    `latest_only` la domanda è «chi lo cita adesso», che è quella che un gate
    fa. La storia è ancora lì e si può chiedere — ma va chiesta.
    """
    cercato = "d" * 64
    mio = _id()
    store.put(mio, _con_digest(cercato))
    store.put(mio, {"graphs": {"g": {"nodes": []}}})

    assert mio not in [p for p, _r in docs.projects_citing_digest(store.pool, cercato)]
    assert mio in [p for p, _r in docs.projects_citing_digest(
        store.pool, cercato, latest_only=False)]


def test_il_digest_scritto_COL_PREFISSO_si_trova_cercandolo_NUDO(store):
    """Il difetto vero, quello misurato sui 122 documenti della dev-stack.

    Là dentro il checksum è scritto `"sha256:17a4…"`, col prefisso, mentre chi
    cerca lo normalizza togliendolo: la prima versione della query rispondeva
    `[]` dove il ciclo rispondeva `['aiano']`, **ed era tre volte più veloce
    proprio perché non trovava niente.** Questo test è la forma minima di quella
    misura, e l'avrebbe visto.
    """
    nudo = "e" * 64
    mio = _id()
    store.put(mio, _con_digest(f"sha256:{nudo}"))
    assert mio in [p for p, _r in docs.projects_citing_digest(store.pool, nudo)]
    assert mio in [p for p, _r in docs.projects_citing_digest(
        store.pool, f"sha256:{nudo}")]


def test_la_ricerca_e_fatta_in_modo_che_lindice_POSSA_servirla(store):
    """La forma della query, misurata sul piano e non sul cronometro.

    Su 122 documenti la tabella sta in 29 pagine e il pianificatore sceglie la
    scansione sequenziale **a ragione**: un tempo qui non direbbe niente. Quello
    che si può misurare adesso è l'altra cosa, che è quella che era rotta —
    **che la query sia scritta in modo che l'indice possa entrarci.** La prima
    versione restringeva alla revisione corrente con un `DISTINCT ON` e filtrava
    fuori dalla sotto-query: l'indice GIN non compariva nel piano nemmeno
    vietando la scansione sequenziale, perché la tabella nuda non era mai in una
    condizione.

    Quindi si vietano le strade che NON passano dall'indice — la scansione
    sequenziale e quella sulla chiave primaria — e si guarda se ne resta una. Un
    indice che nessuna query sa usare è un costo di scrittura e basta.

    Si vieta anche `indexscan`, e non è un accanimento: in questa tabella di
    prova ci sono poche righe, e con la sola `seqscan` spenta il pianificatore
    sceglie la chiave primaria — che risponde correttamente e non dimostra
    niente sulla forma della query.
    """
    mio = _id()
    store.put(mio, _con_digest("f" * 64))
    paths = docs._jsonpath_equals(docs._CHECKSUM_PATHS, docs.spellings("f" * 64))
    sql = docs.build_digest_query(len(paths), latest_only=True)

    with store.pool.connection() as conn:
        conn.execute("SET LOCAL enable_seqscan = off")
        conn.execute("SET LOCAL enable_indexscan = off")
        piano = "\n".join(r[0] for r in conn.execute(
            "EXPLAIN (ANALYZE) " + sql, tuple(paths)).fetchall())
        conn.rollback()

    assert "documents_doc_gin" in piano, (
        "l'indice GIN non compare nel piano nemmeno vietando la seq scan: la "
        f"query non è scritta in modo che possa servirla.\n{piano}")
    assert "Bitmap Index Scan" in piano


def test_la_ricerca_sql_dice_la_stessa_cosa_del_ciclo_di_oggi(store):
    """Le due strade sullo stesso dato: **la misura che conta è che concordino.**

    Un numero che migliora senza una causa è un difetto finché non si dimostra il
    contrario, e la causa qui può essere anche che la query semplicemente non
    trova quello che il ciclo trovava. Quindi prima di misurare il tempo si
    misura l'accordo, e su documenti veri — su tutti quelli che ne hanno uno, non
    sul primo che capita.
    """
    provati = 0
    for path in _candidates()[:40]:
        contenuto = json.loads(path.read_text(encoding="utf-8"))
        digest = _un_digest_qualsiasi(contenuto)
        if digest is None:
            continue
        project = _id()
        store.put(project, contenuto)
        da_sql = sorted(p for p, _r in docs.projects_citing_digest(store.pool, digest)
                        if p == project)
        da_ciclo = sorted(docs.scan_documents_for_digest([(project, contenuto)],
                                                         digest))
        assert da_sql == da_ciclo == [project], (
            f"{path.name}: SQL e ciclo non concordano sul digest {digest}")
        provati += 1
    if not provati:
        pytest.skip("nessun em.json vero su questa macchina cita un checksum")


def _un_digest_qualsiasi(documento: dict):
    for section in docs._sections(documento):
        for node in section.get("nodes") or []:
            if isinstance(node, dict):
                found = (node.get("data") or {}).get("checksum")
                if found:
                    return str(found)
    return None


# ── la configurazione, e la mezza configurazione ─────────────────────────────

def test_store_from_env_sceglie_postgres_e_tiene_la_directory_per_loplog(tmp_path):
    scelto = store_from_env({"EM_DOCUMENTS_DSN": DSN,
                             "EM_SNAPSHOT_DIR": str(tmp_path)})
    assert isinstance(scelto, PostgresSnapshotStore)
    assert scelto.journal_root == str(tmp_path), (
        "l'oplog è sparito nel trasloco: `journal_for` non trova più dove "
        "scrivere e una stanza resta senza riproduzione dopo un riavvio")
    assert "postgres" in describe(scelto)
    assert "password" not in describe(scelto).lower()


def test_senza_postgres_resta_la_directory(tmp_path):
    scelto = store_from_env({"EM_SNAPSHOT_DIR": str(tmp_path)})
    assert isinstance(scelto, DirectorySnapshotStore)


def test_loplog_trova_casa_anche_con_postgres(tmp_path):
    """La riga di `oplog.journal_for` che non c'era, misurata da fuori."""
    from app.oplog import journal_for

    scelto = store_from_env({"EM_DOCUMENTS_DSN": DSN,
                             "EM_SNAPSHOT_DIR": str(tmp_path)})
    registro = journal_for(scelto, "una-stanza")
    assert registro is not None
    assert str(tmp_path) in str(registro.path)


def test_mezza_configurazione_e_rifiutata():
    """Un host senza le credenziali non diventa un default: solleva."""
    with pytest.raises(RuntimeError) as errore:
        docs.dsn_from_env({"EM_DOCUMENTS_HOST": "db"})
    assert "EM_DOCUMENTS_DB" in str(errore.value)


def test_nessuna_configurazione_non_e_un_errore():
    assert docs.dsn_from_env({}) is None


def test_la_parola_dordine_non_finisce_su_health():
    assert docs.redact_dsn("host=db dbname=em user=em password=segreto") == (
        "host=db dbname=em user=em")
    assert docs.redact_dsn("postgresql://em:segreto@db:5432/em") == (
        "postgresql://em:***@db:5432/em")
    assert "segreto" not in docs.redact_dsn("postgresql://em:segreto@db/em")
