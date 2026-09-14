"""Import paths for the test suite, in one place.

Two entries, and the order is the point:

* the repo root, so ``app`` is importable without installing StratiGraph Server;
* **the s3Dgraphy checkout ahead of any installed wheel**, because StratiGraph Server is
  developed against the reference implementation as it is *now*. A test that
  silently validated against last week's published dev would pass while the thing
  it describes was already different.

This used to live at the top of each test module. One copy per file is one copy too
many: the day the layout changes, the file nobody remembered keeps the old path and
fails in a way that looks like a code problem.
"""

from __future__ import annotations

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CHECKOUT = _REPO.parent / "s3Dgraphy" / "src"
if _CHECKOUT.is_dir() and str(_CHECKOUT) not in sys.path:
    sys.path.insert(0, str(_CHECKOUT))


# ══════════════════════════════════════════════════════════════════════════
# IL DATABASE DELLE PROVE — suo, usato, e buttato
# ══════════════════════════════════════════════════════════════════════════
#
# **Le prove non scrivono mai nel database vivo.** Non «di solito», non «se uno
# sta attento»: mai. Puntare le prove su `em_documents` sarebbe la comodità che
# prima o poi cancella i 122 documenti di qualcuno — e una fixture che fa
# `DELETE FROM documents WHERE project_id LIKE 'prova-%'` su quel database è già
# a un carattere di distanza dal disastro.
#
# Quindi: il giro di test trova il server, **si crea un database suo** con un
# nome che nessun altro può avere, lo usa, e alla fine lo lascia com'era.
#
# Il server è quello della dev-stack, che pubblica già la 5433 su localhost
# (`POSTGRES_PORT` nel compose, 5433 e non 5432 perché su una macchina da
# archeologi il 5432 è quasi sempre di PyArchInit). Non serve un servizio nuovo:
# serve un database nuovo dentro quello che c'è.

import os as _os
import uuid as _uuid

import pytest as _pytest

#: Come si raggiunge il SERVER (non il database) su cui creare quello di prova.
#: Si legge `EM_TEST_PG_*` e si ripiega sui valori del compose della dev-stack,
#: che sono pubblici e stanno in `docker-compose.dev.yml`: qui un default non è
#: «un posto scelto da nessuno» come in `dsn_from_env`, è *il* posto che questo
#: repo dichiara di avere in piedi per svilupparci sopra.
_PG = {
    "host": _os.environ.get("EM_TEST_PG_HOST", "127.0.0.1"),
    "port": _os.environ.get("EM_TEST_PG_PORT", "5433"),
    "user": _os.environ.get("EM_TEST_PG_USER", "em"),
    "password": _os.environ.get("EM_TEST_PG_PASSWORD", "em"),
}

#: Il database di servizio su cui ci si collega per poterne creare un altro:
#: `CREATE DATABASE` non si può dare stando dentro il database che si crea.
_MAINTENANCE = _os.environ.get("EM_TEST_PG_MAINTENANCE", "postgres")

#: Il database VIVO, che queste prove non devono toccare nemmeno per sbaglio.
#: Serve a un'asserzione, non a una connessione.
DATABASE_VIVO = _os.environ.get("EM_DOCUMENTS_DB", "em_documents")

COME_FARLE_GIRARE = (
    "Serve un Postgres. La dev-stack ne ha già uno: "
    "`cd dev-stack && ./fcn-up.sh` (oppure "
    "`docker compose -f dev-stack/docker-compose.dev.yml up -d postgres`), "
    "poi `python -m pytest`. Il giro si crea un database suo — "
    "em_test_<casuale> — e lo cancella alla fine: il database vivo "
    f"({DATABASE_VIVO}) non viene toccato. "
    "Per puntare altrove: EM_TEST_PG_HOST / _PORT / _USER / _PASSWORD."
)


def _dsn(dbname: str) -> str:
    return " ".join([f"host={_PG['host']}", f"port={_PG['port']}",
                     f"dbname={dbname}", f"user={_PG['user']}",
                     f"password={_PG['password']}"])


def _server_raggiungibile() -> str:
    """`""` se il server c'è, altrimenti la ragione per cui non c'è.

    Si prova a collegarsi al database di **servizio**, non a quello di prova:
    quello di prova non esiste ancora, ed è giusto così.
    """
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        return (f"manca psycopg ({exc}): pip install -e '.[dev]'")
    try:
        with psycopg.connect(_dsn(_MAINTENANCE), connect_timeout=3):
            return ""
    except Exception as exc:               # noqa: BLE001 — è una diagnosi
        prima_riga = str(exc).strip().splitlines()[0] if str(exc).strip() else exc
        return f"nessun Postgres su {_PG['host']}:{_PG['port']} ({prima_riga})"


@_pytest.fixture(scope="session")
def documents_dsn() -> str:
    """Un database tutto suo, per questo giro di prove. Creato e poi buttato.

    Il nome porta un UUID: due giri in parallelo non si pestano i piedi, e
    nessun database di lavoro può chiamarsi così per caso.

    `ENCODING 'UTF8'` esplicito perché `ensure_schema` lo pretende — e su una
    macchina il cui `template1` non fosse UTF8 la prova fallirebbe con il
    messaggio giusto invece che con uno strano.
    """
    motivo = _server_raggiungibile()
    if motivo:
        _pytest.skip(f"{motivo}. {COME_FARLE_GIRARE}")

    import psycopg  # type: ignore

    nome = "em_test_" + _uuid.uuid4().hex[:16]
    with psycopg.connect(_dsn(_MAINTENANCE), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{nome}" ENCODING \'UTF8\' '
                     f"TEMPLATE template0")
    try:
        yield _dsn(nome)
    finally:
        with psycopg.connect(_dsn(_MAINTENANCE), autocommit=True) as conn:
            #: `WITH (FORCE)` perché il pool delle prove può avere ancora una
            #: connessione aperta quando la sessione finisce, e un database che
            #: non si riesce a cancellare resta lì a sporcare il server di
            #: qualcun altro. Da PostgreSQL 13.
            conn.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')


def pytest_report_header(config):
    """Dire all'INIZIO se le prove del database gireranno o no.

    Un giro che le salta lo dice in fondo, in una riga che scorre via. Detto in
    testa, chi lancia le prove sa già se sta misurando tutto o una parte.
    """
    motivo = _server_raggiungibile()
    if motivo:
        return [f"documenti: SALTATE — {motivo}", f"documenti: {COME_FARLE_GIRARE}"]
    return [f"documenti: Postgres su {_PG['host']}:{_PG['port']} — "
            f"il giro si crea un database suo (il vivo, {DATABASE_VIVO}, "
            f"non si tocca)"]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """E rendere le prove SALTATE visibili alla fine.

    Venti prove che spariscono in fondo a un sommario sono venti prove che
    nessuno rimette in piedi: una prova saltata è una prova che marcisce, e una
    regressione nel codice che copre non si vedrebbe. Qui si elencano per file,
    con il conto, e si dice come farle girare.
    """
    saltate = terminalreporter.stats.get("skipped", [])
    if not saltate:
        return
    per_file: dict = {}
    for report in saltate:
        percorso = str(getattr(report, "nodeid", "?")).split("::")[0]
        per_file[percorso] = per_file.get(percorso, 0) + 1
    terminalreporter.write_sep("=", f"{len(saltate)} PROVE SALTATE", yellow=True)
    for percorso, quante in sorted(per_file.items(), key=lambda kv: -kv[1]):
        terminalreporter.write_line(f"  {quante:>3}  {percorso}")
    motivo = _server_raggiungibile()
    if motivo:
        terminalreporter.write_line("")
        terminalreporter.write_line(f"  {COME_FARLE_GIRARE}")
