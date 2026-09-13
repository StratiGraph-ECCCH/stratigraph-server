"""Where a room's durable truth lives — outside this process.

P4.2 introduces the first component of StratiGraph Server that **holds state**, and this
module is one of the three fences that keep that introduction honest (the others
are in `rooms.py`: convergence stays in the library, presence stays ephemeral).

The fence here: **the durable truth is not on the process's disk.** A room's
snapshot goes to an object store — MinIO in the deployment — and what StratiGraph Server
keeps in RAM is a *working copy* that can be rebuilt from it. The process may die
and come back; the study does not live inside it. That is what keeps rule 2 of
this repo (stateless, 12-factor) meaningful in the presence of a relay: the state
is *held*, not *owned*.

The interface is deliberately two methods. A snapshot store is a key-value store
of documents, and anything richer here would be logic — which belongs in the
library, not in the transport.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import threading
from typing import Any, Dict, List, Optional, Protocol, Tuple


class SnapshotStore(Protocol):
    """Get and put a room's container document. Nothing else."""

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        """The last snapshot of this room, or None if it was never written."""

    def put(self, room_id: str, document: Dict[str, Any]) -> None:
        """Write this room's current state, and make it the one `get` returns.

        NOT «replace», which is what this line said until the documents got a
        house of their own: `PostgresSnapshotStore` **appends a revision** and
        keeps the ones before it, so a store is free to remember. What the
        interface promises is only that `get` answers with the last thing
        written — whether the previous one survives is the store's business, and
        a caller that needed it to be destroyed was relying on an accident.
        """


class InMemorySnapshotStore:
    """For tests and for a single-process laptop run.

    It is NOT the deployment target, and saying so matters: an in-memory store
    dies with the process, which is precisely the property the MinIO
    implementation exists to remove. Copies on the way in and out, so a caller
    that keeps mutating its working copy cannot rewrite history.
    """

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            raw = self._data.get(room_id)
        return json.loads(raw) if raw is not None else None

    def put(self, room_id: str, document: Dict[str, Any]) -> None:
        blob = json.dumps(document, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        with self._lock:
            self._data[room_id] = blob

    def rooms(self) -> list[str]:
        with self._lock:
            return sorted(self._data)


class DirectorySnapshotStore:
    """A directory of `<room>.em.json` files.

    For a **local** run and for tests that want to see the bytes. Explicitly not
    the production answer: a path on the process's filesystem is exactly the
    thing rule 2 warns about, and a deployment that used this would have two
    replicas with two different truths. It exists because "run it on a laptop"
    is a real use, and because a test that can open the file proves the snapshot
    was actually written rather than remembered.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, room_id: str) -> pathlib.Path:
        # room ids come from a URL; keep them from walking out of the directory
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in room_id)
        return self.root / f"{safe}.em.json"

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(room_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, room_id: str, document: Dict[str, Any]) -> None:
        path = self._path(room_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)     # atomic: a reader never sees half a snapshot

    def rooms(self) -> list[str]:
        """Which rooms this directory holds. Same method the memory store has —
        the IIIF gate asks it, because a image request carries no room id and
        the question has to be put to every room there is."""
        return sorted(p.name[: -len(".em.json")]
                      for p in self.root.glob("*.em.json"))


class PostgresSnapshotStore:
    """I documenti a casa loro: una tabella, e ogni revisione è una riga.

    **Un'altra implementazione dell'interfaccia qui sopra, non un secondo
    meccanismo accanto.** Due metodi (più `rooms()`, che il gate IIIF chiede a
    tutti gli store perché un identificatore di immagine non porta una stanza):
    tutto quello che questa tabella compra in più — cercare per contenimento,
    rileggere una revisione vecchia — sta in `documents.py` e si chiede a quello,
    non allo store. La recinzione dei due metodi regge.

    ## Le due decisioni prese qui, perché nessun altro le prende

    **`revision` è del NEGOZIO, non della stanza.** `Room.revision` riparte da
    zero ogni volta che una stanza viene ricostruita dallo store — è il motivo
    per cui `Room.instance` esiste — quindi usarlo come chiave farebbe
    collidere la prima scrittura dopo un riavvio con la prima di ieri. Il numero
    che va in tabella è un contatore per progetto, monotòno, che non riparte:
    `max(revision) + 1`, sotto un advisory lock (`documents.lock_key`) perché due
    scritture in parallelo calcolerebbero lo stesso numero e la seconda
    sbatterebbe contro la chiave primaria.

    **Scrivere gli stessi byte non è una revisione.** Se il digest entrante è
    quello dell'ultima riga, non si inserisce niente. Un `put` che non cambia
    nulla — un salvataggio differito, una compattazione che non ha compattato —
    non deve far avanzare la storia: è la stessa regola per cui la versione di un
    progetto la decide l'impronta e non il tasto salva.

    ## Cosa si serve, e cosa no

    `get` legge **`raw`**, mai `doc`. Sono gli stessi byte entrati; `doc` è la
    loro proiezione normalizzata da jsonb — chiavi riordinate, duplicati scartati
    — ed esiste solo perché SQL possa cercarci dentro. Servire `doc` vorrebbe
    dire restituire un documento che non ha più l'impronta con cui è arrivato.
    """

    def __init__(self, dsn: str, *, journal_root: Optional[str] = None,
                 pool: Any = None) -> None:
        from . import documents as docs

        self._docs = docs
        self.dsn = dsn
        self._pool = pool if pool is not None else docs.open_pool(dsn)
        docs.ensure_schema_once(self._pool)
        #: DOVE VA L'OPLOG, che non è dove vanno i documenti — e il nome lo dice.
        #: Il registro di riproduzione è un log in coda, non un documento
        #: versionato, e stanotte non si trasloca: `oplog.journal_for` lo cerca
        #: qui. `None` significa nessun registro durevole, e `/v1/health` lo dice
        #: invece di lasciarlo scoprire a un riavvio.
        self.journal_root = journal_root

    @property
    def pool(self) -> Any:
        return self._pool

    def close(self) -> None:
        """Chiude il pool. Per uno STRUMENTO che finisce, non per il server.

        Nel server il pool vive quanto il processo e non si chiude mai: è la
        cosa giusta. In uno script no, e senza questo metodo `psycopg_pool` si
        chiude da solo nel distruttore **durante lo spegnimento
        dell'interprete** — dove non si possono più unire thread. Misurato:
        `PythonFinalizationError: cannot join thread at interpreter shutdown`,
        stampato dopo l'ultima riga di output. Un rumore, non un guasto — ma un
        rumore che a chi guarda sembra un guasto.
        """
        self._pool.close()

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        sql = (f"SELECT raw FROM {self._docs.TABLE} WHERE project_id = %s "
               f"ORDER BY revision DESC LIMIT 1")
        with self._pool.connection() as conn:
            row = conn.execute(sql, (room_id,)).fetchone()
        if row is None:
            return None
        return json.loads(bytes(row[0]).decode("utf-8"))

    def put(self, room_id: str, document: Dict[str, Any]) -> None:
        blob = json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        with self._pool.connection() as conn:
            # Nella STESSA transazione dell'inserimento: il lock cade al commit,
            # quindi non c'è una finestra fra «ho scelto il numero» e «l'ho
            # usato». Vedi `documents.lock_key` per perché la chiave la calcola
            # Python e non `hashtext()`.
            conn.execute("SELECT pg_advisory_xact_lock(%s)",
                         (self._docs.lock_key(room_id),))
            last = conn.execute(
                f"SELECT revision, sha256 FROM {self._docs.TABLE} "
                f"WHERE project_id = %s ORDER BY revision DESC LIMIT 1",
                (room_id,)).fetchone()
            if last is not None and last[1] == digest:
                conn.commit()          # rilascia il lock; niente da scrivere
                return
            conn.execute(
                f"INSERT INTO {self._docs.TABLE} (project_id, revision, raw) "
                f"VALUES (%s, %s, %s)",
                (room_id, (last[0] + 1) if last is not None else 0, blob))
            conn.commit()

    def rooms(self) -> List[str]:
        """Quali progetti questa tabella tiene. Lo stesso metodo che hanno gli
        altri due store, e per la stessa ragione: il gate IIIF non ha una stanza
        da cui partire e deve poter porre la domanda a tutte."""
        sql = f"SELECT DISTINCT project_id FROM {self._docs.TABLE} ORDER BY 1"
        with self._pool.connection() as conn:
            return [row[0] for row in conn.execute(sql).fetchall()]

    # ── quello che la tabella compra in più ──────────────────────────────────
    #
    # Non fa parte di `SnapshotStore`: sono letture sulla stessa tabella, e
    # stanno qui perché sanno già a quale pool chiedere. Nessun percorso del
    # relay le usa — sono per un operatore, per una prova, e per il giorno in cui
    # citare uno stato di uno studio smetterà di essere un'intenzione.

    def revisions(self, room_id: str) -> List[Dict[str, Any]]:
        sql = (f"SELECT revision, sha256, written_at, octet_length(raw) "
               f"FROM {self._docs.TABLE} WHERE project_id = %s ORDER BY revision")
        with self._pool.connection() as conn:
            rows = conn.execute(sql, (room_id,)).fetchall()
        return [{"revision": r[0], "sha256": r[1], "written_at": r[2],
                 "bytes": r[3]} for r in rows]

    def raw_at(self, room_id: str, revision: Optional[int] = None
               ) -> Optional[Tuple[bytes, int, str]]:
        """I BYTE di una revisione, com'erano: `(raw, revision, sha256)`.

        Il metodo su cui si misura il criterio di accettazione di questa notte —
        byte in, gli stessi byte fuori, impronta identica — e per farlo deve
        restituire `raw`, non una ri-serializzazione di `get`.
        """
        where = "project_id = %s" + ("" if revision is None else " AND revision = %s")
        order = "" if revision is not None else " ORDER BY revision DESC LIMIT 1"
        args: Tuple[Any, ...] = ((room_id,) if revision is None
                                 else (room_id, revision))
        sql = (f"SELECT raw, revision, sha256 FROM {self._docs.TABLE} "
               f"WHERE {where}{order}")
        with self._pool.connection() as conn:
            row = conn.execute(sql, args).fetchone()
        return (bytes(row[0]), row[1], row[2]) if row is not None else None


class MinioSnapshotStore:
    """The deployment target — **not implemented tonight, and it says so.**

    The shape is already fixed by the interface above: a bucket, one object per
    room, `get`/`put`. What it needs is the bucket and the credentials the shared
    infrastructure will provide (the mail-spec to Romano: realm + bucket +
    routing), and the `minio` client as an optional dependency — so a build
    without it fails at construction with a sentence, not at the first snapshot
    with a stack trace.

    Left as a class rather than a comment because the point of the interface is
    that the swap is a line of configuration, and an empty class makes that
    concrete: when the bucket exists, this is where it goes.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError(
            "the MinIO snapshot store is the P4.2 deployment target and is not "
            "wired yet: it needs the shared bucket + credentials. Use "
            "InMemorySnapshotStore (tests) or DirectorySnapshotStore (local).")


# ── the room's own durable record ────────────────────────────────────────────
#
# A room is more than the container it works on: it has a name, a creator, and a
# list of container references (`rooms.RoomDescriptor`). That record is small and
# it is *state*, so it belongs here beside the snapshots rather than in the relay
# — which is fenced off from the filesystem on purpose.
#
# Three methods and not two, because a register you cannot enumerate is not a
# register: `ids()` is what makes "list the rooms" answerable at all.

class RoomStore(Protocol):
    """Get, put and list room descriptors. Three methods, and the third is the
    one the snapshot store does not need: a register you cannot enumerate is not
    a register."""

    def get(self, room_id: str) -> Optional[Dict[str, Any]]: ...

    def put(self, room_id: str, record: Dict[str, Any]) -> None: ...

    def ids(self) -> List[str]: ...


class InMemoryRoomStore:
    """Tests and a single-process laptop. Dies with the process, and says so."""

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            raw = self._data.get(room_id)
        return json.loads(raw) if raw is not None else None

    def put(self, room_id: str, record: Dict[str, Any]) -> None:
        blob = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._lock:
            self._data[room_id] = blob

    def ids(self) -> List[str]:
        with self._lock:
            return sorted(self._data)


class DirectoryRoomStore:
    """A directory of `<room>.room.json` files, written atomically.

    Beside the snapshots and the ACLs, for the reason the ACL store gives: they
    are the same room's state, and an operator who backs one up should not find
    the others somewhere else.
    """

    def __init__(self, root: str) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, room_id: str) -> pathlib.Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in room_id)
        return self.root / f"{safe}.room.json"

    def get(self, room_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(room_id)
        if not path.is_file():
            return None
        # Allowed to raise, like the ACL store: a record that will not parse must
        # not read as "this room was never declared".
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, room_id: str, record: Dict[str, Any]) -> None:
        path = self._path(room_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1,
                                  sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def ids(self) -> List[str]:
        return sorted(p.name[: -len(".room.json")]
                      for p in self.root.glob("*.room.json"))


def room_store_from_env(environ: Optional[Dict[str, str]] = None) -> RoomStore:
    """`EM_ROOM_DIR`, else beside the snapshots (`EM_SNAPSHOT_DIR`), else memory
    — the same order and the same honesty as the ACL store."""
    env = environ if environ is not None else os.environ
    directory = env.get("EM_ROOM_DIR") or env.get("EM_SNAPSHOT_DIR")
    if directory:
        return DirectoryRoomStore(directory)
    return InMemoryRoomStore()


def describe_rooms(store: RoomStore) -> str:
    return {
        "InMemoryRoomStore": "memory (not durable — dies with the process)",
        "DirectoryRoomStore": "directory (beside the snapshots)",
    }.get(type(store).__name__, type(store).__name__)


def store_from_env(environ: Optional[Dict[str, str]] = None) -> SnapshotStore:
    """The store this process should use, chosen by configuration.

    Precedence, and ogni gradino risponde a «che cosa ha chiesto l'operatore?»:

    1. **Postgres** quando `EM_DOCUMENTS_*` c'è — la casa dei documenti
       (`documents.py`), dove una revisione è una riga. Mezza configurazione
       solleva invece di ripiegare: un ripiego silenzioso qui sarebbe un
       deployment che crede di avere la storia e ha una directory.
    2. `EM_SNAPSHOT_DIR` — la directory, per una corsa locale. **Resta**: una
       stanza su un portatile senza database è un uso vero, non un residuo.
    3. niente — in memoria, onesto su un portatile e rumorosamente sbagliato in
       un deployment, che è il motivo per cui `/v1/health` dice quale dei tre è
       in uso invece di lasciare a un operatore il dubbio se i suoi documenti
       sopravvivano a un riavvio.

    `EM_SNAPSHOT_DIR` non diventa inutile quando c'è Postgres: **l'oplog resta
    lì**. Il registro di riproduzione è un log in coda, una cosa diversa da un
    documento versionato, e non trasloca stanotte — lo store lo dice
    esplicitamente con `journal_root` invece di lasciarlo indovinare a
    `oplog.journal_for`.
    """
    env = environ if environ is not None else os.environ
    directory = env.get("EM_SNAPSHOT_DIR")
    from . import documents as docs

    dsn = docs.dsn_from_env(env)
    if dsn:
        return PostgresSnapshotStore(dsn, journal_root=directory)
    if directory:
        return DirectorySnapshotStore(directory)
    return InMemorySnapshotStore()


def describe(store: SnapshotStore) -> str:
    """A word for `/v1/health`: which store is holding the truth."""
    if isinstance(store, PostgresSnapshotStore):
        # L'indirizzo SENZA la parola d'ordine: `/v1/health` è una pagina che si
        # incolla in un messaggio quando qualcosa non va.
        from . import documents as docs

        return (f"postgres ({docs.redact_dsn(store.dsn)}) — "
                f"every revision a row")
    return {
        "InMemorySnapshotStore": "memory (not durable — dies with the process)",
        "DirectorySnapshotStore": "directory (local only — not for replicas)",
        "MinioSnapshotStore": "minio",
    }.get(type(store).__name__, type(store).__name__)


def deep_copy(document: Dict[str, Any]) -> Dict[str, Any]:
    """A working copy that cannot alias the snapshot it came from."""
    return copy.deepcopy(document)
