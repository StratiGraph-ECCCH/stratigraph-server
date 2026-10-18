"""`/health` deve BUSSARE a ciò che dichiara.

Prima di stanotte ogni riga di `/health` era una rilettura della
configurazione: «asset_store: s3 (http://rustfs:9000, bucket em-assets)» si
stampava identica con l'object store acceso, spento o mai esistito.

Non è un'astrazione. Il 24 settembre il chatbot è stato puntato a un nome di
servizio che su quella rete non esiste, ha ripiegato in silenzio sul suo
container locale, e il suo `/health` ha continuato a dichiarare quella
destinazione per tutta la notte: le schede di una prova intera sono finite nel
posto sbagliato con tutti i semafori verdi.

Quattro guardie, e ognuna è dimostrata sul caso che la fa scattare:

1. una dipendenza raggiungibile risponde `reached`, col tempo che ci ha messo;
2. una **rotta davvero** risponde `unreachable` **con la ragione** — non un
   booleano, una frase;
3. una assente per configurazione risponde `off` e **non conta come guasto**:
   è la regola di casa, assente = funzione spenta;
4. `/health` **non bussa**: chiamarlo non muove l'istante dell'ultima bussata.
   È il vincolo «mai in un ciclo che martella», verificato sull'effetto —
   l'healthcheck di Docker gira ogni pochi secondi e non deve comporre il
   numero dell'identity provider ogni volta.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from fastapi.testclient import TestClient                  # noqa: E402

from app import main as main_module                        # noqa: E402
from app import reach                                      # noqa: E402
from app.main import app                                   # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


# ── le tre risposte ─────────────────────────────────────────────────────────

def test_una_dipendenza_raggiungibile(tmp_path):
    (tmp_path / "una.json").write_text("{}", encoding="utf-8")
    knock = reach.knock("snapshot_store", "directory",
                        reach.probe_directory(str(tmp_path)))
    assert knock.state == reach.REACHED
    assert "1 entries" in knock.detail
    assert knock.at and knock.ms is not None


def test_una_dipendenza_rotta_dice_perche(tmp_path):
    """IL CASO CHE LA FA SCATTARE, e la rottura è vera: la cartella non c'è.

    Il valore non è `False`: è la frase. Una spia rossa senza la sua ragione
    costringe l'operatore a indovinare, che è come si arriva a puntare un
    servizio a un nome che non esiste."""
    manca = tmp_path / "non-montata"
    knock = reach.knock("snapshot_store", "directory",
                        reach.probe_directory(str(manca)))
    assert knock.state == reach.UNREACHABLE
    assert "FileNotFoundError" in knock.detail
    assert str(manca) in knock.detail


def test_assente_per_configurazione_non_e_un_guasto():
    """Uno store in memoria su un portatile non è rosso: è spento. Dipingerlo
    di rosso insegnerebbe a ignorare il rosso."""
    knock = reach.knock("asset_store", "memory", None)
    assert knock.state == reach.OFF
    assert "not a fault" in knock.detail
    stato = reach.Reachability(at=knock.at, why="test", knocks=[knock])
    assert stato.all_reached is True, "una spenta non è un guasto"


def test_una_rotta_e_una_spenta_insieme(tmp_path):
    """La somma: `all_reached` guarda solo le irraggiungibili."""
    rotta = reach.knock("a", "directory",
                        reach.probe_directory(str(tmp_path / "niente")))
    spenta = reach.knock("b", "memory", None)
    stato = reach.Reachability(at=rotta.at, why="test",
                               knocks=[rotta, spenta])
    payload = stato.as_dict()
    assert payload["summary"] == {reach.UNREACHABLE: 1, reach.OFF: 1}
    assert stato.all_reached is False


def test_non_aver_bussato_e_uno_stato_non_una_lista_vuota():
    """Una `dependencies: []` senza altro si legge «tutto a posto»."""
    payload = reach.Reachability().as_dict()
    assert payload["at"] is None
    assert payload["why"] == "never knocked"
    assert payload["dependencies"] == []


# ── la rotta, e chi la usa oggi ─────────────────────────────────────────────

def test_health_risponde_ancora_a_chi_la_usa_oggi(client):
    """Docker ci fa l'healthcheck: la rotta senza versione, 200, e i campi che
    aveva prima ancora al loro posto."""
    answer = client.get("/health")
    assert answer.status_code == 200
    body = answer.json()
    for chiave in ("ok", "service", "version", "auth", "snapshot_store",
                   "asset_store", "rooms"):
        assert chiave in body, chiave
    assert body["ok"] is True


def test_health_riporta_la_bussata_ma_non_bussa(client, monkeypatch):
    """IL VINCOLO, VERIFICATO SULL'EFFETTO.

    Si conta quante volte una prova viene eseguita mentre `/health` viene
    chiamato tre volte: deve restare **zero**. Se un domani `health()`
    chiamasse `knock()`, ogni healthcheck di Docker comporrebbe il numero del
    realm — e questo test diventa rosso invece di scoprirlo un operatore."""
    bussate = []
    vera = reach.knock

    def contando(name, declared, probe):
        if probe is not None:
            bussate.append(name)
        return vera(name, declared, probe)

    monkeypatch.setattr(main_module.reach_module, "knock", contando)
    for _ in range(3):
        body = client.get("/health").json()
    assert bussate == [], f"/health ha bussato: {bussate}"
    assert "reachability" in body
    assert set(body["reachability"]) == {"at", "why", "summary", "dependencies"}


def test_bussare_su_richiesta_aggiorna_listante(client):
    """`POST /v1/health/reach` è l'unica porta che bussa, ed è sotto `/v1`,
    quindi vuole un token: bussare a spese di chi ospita è cosa da operatore."""
    first = client.post("/v1/health/reach")
    assert first.status_code == 200
    body = first.json()
    assert body["why"] == "request"
    assert body["at"]
    nomi = [d["name"] for d in body["dependencies"]]
    assert {"snapshot_store", "asset_store", "auth"} <= set(nomi)
    # ogni voce porta la sua dichiarazione accanto al suo fatto
    for dependency in body["dependencies"]:
        assert dependency["declared"], dependency
        assert dependency["state"] in (reach.REACHED, reach.UNREACHABLE,
                                       reach.OFF)
        assert dependency["at"]


def test_la_bussata_finisce_dentro_health(client):
    """Le due rotte parlano dello stesso registro: bussare cambia ciò che
    `/health` racconta, senza che `/health` abbia bussato."""
    client.post("/v1/health/reach")
    body = client.get("/health").json()["reachability"]
    assert body["why"] == "request"
    assert body["summary"], body


def test_lo_stesso_elenco_per_lavvio_e_per_la_richiesta():
    """Due implementazioni di «cosa siamo andati a toccare» sarebbero due
    elenchi che si allontanano: `knock()` è una sola, e l'avvio la chiama."""
    import inspect
    source = inspect.getsource(main_module)
    assert source.count("def knock(") == 1
    assert 'knock("startup")' in source
    assert 'knock("request")' in source


# ── Postgres, la casa dei documenti ─────────────────────────────────────────
#
# Misurato il 12 ottobre: con `EM_DOCUMENTS_*` presenti `/v1/health` diceva
# `snapshot_store: off` — «absent by configuration» — nella stessa risposta che
# dichiarava «postgres (…) — every revision a row», con 134 righe in tabella.
# `_probe_for` conosceva memoria, S3 e directory; Postgres no.

class _Conn:
    def __init__(self, answer):
        self.answer = answer
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *args):
        self.sql.append(sql)
        if isinstance(self.answer, Exception):
            raise self.answer
        answer = self.answer

        class _Cursor:
            def fetchone(self):
                return answer
        return _Cursor()


class _Pool:
    def __init__(self, answer):
        self.conn = _Conn(answer)

    def connection(self, timeout=None):
        return self.conn


def _store(answer, journal_root=None):
    """Lo store VERO, con un pool finto: è la classe che `_probe_for` deve
    riconoscere, non una sua imitazione. Il pool è marcato come già migrato,
    così `ensure_schema_once` non gli parla. Con `journal_root`, la directory
    dell'oplog che NON va sondata al posto del database."""
    from app import documents
    from app.store import PostgresSnapshotStore
    pool = _Pool(answer)
    setattr(pool, documents._SCHEMA_MARK, True)
    return PostgresSnapshotStore(
        "postgresql://em:segreto@postgres:5432/em_documents",
        journal_root=journal_root, pool=pool)


def test_postgres_raggiunto_col_suo_tempo(tmp_path):
    store = _store((1,), journal_root=str(tmp_path))
    probe = main_module._probe_for(store)
    assert probe is not None, "Postgres non è una funzione spenta"
    knock = reach.knock("snapshot_store", "postgres", probe)
    assert knock.state == reach.REACHED
    assert knock.ms is not None
    assert "select 1" in knock.detail
    assert "segreto" not in knock.detail, "la parola d'ordine non si stampa"
    assert store.pool.conn.sql == ["SELECT 1"]


def test_postgres_che_tace_dice_perche():
    store = _store(ConnectionError("connection refused"))
    knock = reach.knock("snapshot_store", "postgres",
                        main_module._probe_for(store))
    assert knock.state == reach.UNREACHABLE
    assert "connection refused" in knock.detail
