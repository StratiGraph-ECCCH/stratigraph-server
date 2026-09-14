"""La casa dei documenti: una tabella dove una revisione è una riga.

## Il fatto da cui si parte

`store.py` dice in testa che la verità durevole di una stanza non sta sul disco
del processo, e il suo `put` diceva **«Replace this room's snapshot»**. Le due
frasi insieme descrivono un archivio che tiene *un solo stato*: la storia esiste
solo come sequenza di operazioni nell'oplog, e nessuno stato intermedio è
indirizzabile. `rooms.py` incrementa un `Room.revision` a ogni scrittura e
accanto c'è scritto che serve a un indice derivato chiavato su
`(room_id, revision)` — ma quella chiave non aveva una tabella.

Adesso ce l'ha. Chiave `(project_id, revision)`, **ogni revisione è una riga**,
niente più sostituzione.

## Perché `doc` e `sha256` sono GENERATED e non colonne scritte

`raw bytea` è **l'unica cosa che si scrive**: sono i byte esatti del documento
entrato. Le altre due le calcola il database:

    doc     jsonb GENERATED ALWAYS AS (em_utf8_jsonb(raw)) STORED
    sha256  text  GENERATED ALWAYS AS (encode(sha256(raw), 'hex')) STORED

La ragione è tutta in una misura fatta qui sopra, su Postgres 16:

    raw  = {"b":2,"a":1,"a":3}          ← quello che è entrato
    doc  = {"a": 3, "b": 2}             ← quello che jsonb ne fa

`jsonb` **normalizza**: riordina le chiavi e scarta i duplicati. Un digest
calcolato sul `jsonb` non sarebbe il digest del file entrato, e un'impronta che
non torna non è un'impronta. Tenere `doc` e `sha256` come colonne scritte
separatamente aprirebbe il percorso in cui una si aggiorna e l'altra no:
generate, **non possono disaccordarsi per costruzione**.

E se `raw` non è JSON valido l'INSERT fallisce, perché la colonna generata non si
può calcolare. Non si archivia un documento rotto — misurato, non sperato.

## La funzione immutabile, e perché serve davvero

`convert_from(bytea, name)` in PostgreSQL è **stable, non immutable**
(`pg_proc.provolatile = 's'`, verificato), quindi non può stare dentro
un'espressione generata: Postgres rifiuta con *«generation expression is not
immutable»*. La cura è un involucro SQL dichiarato `IMMUTABLE`, e la dichiarazione
è vera **a una condizione**: che la codifica del database sia UTF8, perché è da
lì che dipende il risultato della conversione. Quindi `ensure_schema` la
**verifica** invece di darla per scontata, e si rifiuta di creare la tabella su un
database che non è UTF8. Una promessa di immutabilità su una base che può
smentirla sarebbe la bugia peggiore di tutte: silenziosa e dentro un indice.

## Dove finisce SQL e dove comincia la libreria

SQL **restringe**, la libreria **percorre**. Le ricerche generali — *quali studi
citano questo digest* — sono di contenimento e le fa il database con l'indice
GIN, in una query invece che in un ciclo su ogni documento. Le ricerche *dentro*
il grafo — raggiungibilità, catene stratigrafiche, chiusure transitive — hanno
già i loro metodi in s3Dgraphy e **non si reimplementano qui**: una CTE ricorsiva
su array estratti da `jsonb` sarebbe una seconda implementazione di una cosa che
esiste, cioè di nuovo due fonti per un fatto solo.

Questo modulo è la tabella. Lo *store* che ci scrive dentro sta in `store.py`,
accanto agli altri, perché l'interfaccia è due metodi e questa è un'altra
implementazione di quella — non un secondo meccanismo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

log = logging.getLogger("stratigraph.documents")

#: Il nome della tabella e quello della funzione. Costanti perché compaiono in
#: più query e un nome scritto due volte è un nome che può divergere.
TABLE = "documents"
UTF8_FUNCTION = "em_utf8_jsonb"


# ── lo schema ────────────────────────────────────────────────────────────────

#: `sha256(bytea)` è nativa da PostgreSQL 11 e **immutabile** (`provolatile='i'`,
#: verificato): niente `pgcrypto` da provisionare. `convert_from` invece è
#: stable, e per questo passa dall'involucro — vedi il docstring del modulo.
SCHEMA_SQL = f"""
CREATE OR REPLACE FUNCTION {UTF8_FUNCTION}(raw bytea) RETURNS jsonb
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT convert_from(raw, 'UTF8')::jsonb $$;

CREATE TABLE IF NOT EXISTS {TABLE} (
    project_id  text   NOT NULL,
    revision    bigint NOT NULL,
    raw         bytea  NOT NULL,
    doc         jsonb  GENERATED ALWAYS AS ({UTF8_FUNCTION}(raw)) STORED,
    sha256      text   GENERATED ALWAYS AS (encode(sha256(raw), 'hex')) STORED,
    written_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, revision)
);

CREATE INDEX IF NOT EXISTS {TABLE}_doc_gin ON {TABLE} USING gin (doc);

-- Il digest è una chiave di ricerca a sé: «ho già questi byte?» si chiede senza
-- sapere di quale progetto sono, ed è la domanda che rende il `put` idempotente.
CREATE INDEX IF NOT EXISTS {TABLE}_sha256 ON {TABLE} (sha256);
"""


class NotUtf8(RuntimeError):
    """Il database non è UTF8, quindi l'involucro immutabile non sarebbe vero."""


def ensure_schema(pool: Any) -> None:
    """Crea (una volta) tabella, funzione e indici — dopo aver verificato UTF8.

    L'ordine non è un dettaglio: si guarda `server_encoding` **prima**, perché
    dopo la `CREATE FUNCTION ... IMMUTABLE` la bugia è già scritta nel catalogo e
    un indice l'avrebbe già usata per decidere cosa NON ricontrollare.
    """
    with pool.connection() as conn:
        encoding = conn.execute("SHOW server_encoding").fetchone()[0]
        if str(encoding).upper().replace("-", "") != "UTF8":
            raise NotUtf8(
                f"la casa dei documenti vuole un database UTF8 e questo è "
                f"{encoding}: la colonna `doc` è generata da una funzione "
                f"dichiarata IMMUTABLE che converte da UTF8, e su una codifica "
                f"diversa quella dichiarazione sarebbe falsa. Ricrea il database "
                f"con ENCODING 'UTF8'.")
        conn.execute(SCHEMA_SQL)
        conn.commit()


# ── la connessione ───────────────────────────────────────────────────────────

def dsn_from_env(environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Il DSN che questo processo deve usare, o None se non gliene hanno dato uno.

    `EM_DOCUMENTS_DSN` per intero, oppure i pezzi alla maniera degli altri
    servizi di questa stack (`MINIO_ACCESS_KEY` e compagnia): un indirizzo, un
    utente, una parola d'ordine, un database. **Mezza configurazione è rifiutata**
    e non completata con dei default, per la stessa ragione per cui
    `assets._minio_settings` la rifiuta: un default silenzioso è un processo che
    si collega a un posto che nessuno ha scelto.
    """
    env = environ if environ is not None else os.environ
    dsn = (env.get("EM_DOCUMENTS_DSN") or "").strip()
    if dsn:
        return dsn
    host = (env.get("EM_DOCUMENTS_HOST") or "").strip()
    if not host:
        return None
    required = {
        "dbname": ("EM_DOCUMENTS_DB", (env.get("EM_DOCUMENTS_DB") or "").strip()),
        "user": ("EM_DOCUMENTS_USER", (env.get("EM_DOCUMENTS_USER") or "").strip()),
        "password": ("EM_DOCUMENTS_PASSWORD",
                     (env.get("EM_DOCUMENTS_PASSWORD") or "").strip()),
    }
    pieces = {
        "host": host,
        "port": (env.get("EM_DOCUMENTS_PORT") or "5432").strip(),
        **{field: value for field, (_name, value) in required.items()},
    }
    missing = [name for _field, (name, value) in required.items() if not value]
    if missing:
        raise RuntimeError(
            "EM_DOCUMENTS_HOST c'è ma la configurazione è a metà: manca "
            + ", ".join(missing)
            + ". Dichiarala tutta, o non dichiararla — un default qui sarebbe un "
              "database scelto da nessuno.")
    return " ".join(f"{k}={v}" for k, v in pieces.items() if v)


def redact_dsn(dsn: str) -> str:
    """L'indirizzo senza la parola d'ordine, per `/v1/health`.

    Due forme, perché il DSN ne ha due: `key=value …` e l'URL. La seconda è
    quella che si dimentica — `postgresql://utente:segreto@host/db` — ed è anche
    quella che la gente incolla nelle variabili d'ambiente, quindi trattarne una
    sola vorrebbe dire pubblicare una credenziale su una pagina di stato.
    """
    text = (dsn or "").strip()
    if "://" in text:
        head, _, tail = text.partition("://")
        userinfo, at, rest = tail.rpartition("@")
        if at and ":" in userinfo:
            userinfo = userinfo.split(":", 1)[0] + ":***"
        return f"{head}://{userinfo}{at}{rest}"
    return " ".join(p for p in text.split() if not p.startswith("password="))


def open_pool(dsn: str, *, min_size: int = 1, max_size: int = 4) -> Any:
    """Un pool di connessioni, e il perché non è una connessione sola.

    `rooms()` sta sul percorso del gate IIIF, che è il più caldo che c'è: aprire
    una connessione per ogni tile sarebbe pagare una stretta di mano per pixel.
    Il pool è `psycopg_pool`, dipendenza **opzionale** come il client MinIO — e
    come quello fallisce **qui**, alla costruzione, con una frase.
    """
    try:
        from psycopg_pool import ConnectionPool  # type: ignore
    except ImportError as exc:   # pragma: no cover — dipende dal build
        raise RuntimeError(
            "la casa dei documenti vuole `psycopg[binary,pool]`, che questo "
            "build non ha: pip install 'stratigraph-server[pg]' (oppure togli "
            "EM_DOCUMENTS_* e resta sulla directory)") from exc
    pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size,
                          open=False, kwargs={"autocommit": False})
    pool.open(wait=True, timeout=30)
    return pool


def lock_key(project_id: str) -> int:
    """La chiave del lock consigliato per un progetto.

    Calcolata **qui** e non con `hashtext()` di Postgres: `hashtext` è una
    funzione interna, non documentata come stabile fra versioni, e far dipendere
    la correttezza di una scrittura da un dettaglio interno del server è un debito
    che si paga a un upgrade.
    """
    return int.from_bytes(hashlib.sha256(project_id.encode("utf-8")).digest()[:8],
                          "big", signed=True)


# ── le ricerche generali: SQL restringe ──────────────────────────────────────

#: Il percorso di un checksum dentro un container em.json. Scritto una volta:
#: `{graphs: {<id>: {nodes: [{data: {checksum: …}}]}}}`, più la forma a grafo
#: singolo che i documenti più vecchi hanno ancora (`{nodes: […]}`).
_CHECKSUM_PATHS = (
    "$.graphs.*.nodes[*].data.checksum",
    "$.nodes[*].data.checksum",
)


def spellings(digest: str) -> List[str]:
    """Come lo stesso digest può essere SCRITTO dentro un documento.

    **Misurato, non supposto**, e la misura è la ragione per cui questa funzione
    esiste. Caricati i 122 em.json veri della dev-stack, la prima versione della
    ricerca rispondeva `[]` dove il ciclo rispondeva `['aiano']`, ed era tre
    volte più veloce: *era più veloce perché non trovava niente.* Il documento
    scrive

        "checksum": "sha256:17a423635f00f3cd…"

    cioè **col prefisso**, mentre `_normalise_digest` lo toglie. Normalizzare
    l'ago e non il pagliaio è il difetto: in un ciclo Python le due parti passano
    per la stessa funzione, in SQL il pagliaio è già scritto e non si normalizza
    senza rinunciare all'indice.

    Quindi si cercano **entrambe le grafie**, e il confronto resta uguaglianza
    esatta — che è la sola forma che l'indice GIN sa servire (`like_regex` no).

    IL LIMITE, dichiarato invece di taciuto: un documento che scrivesse il digest
    in MAIUSCOLO non verrebbe trovato da qui, mentre il ciclo di oggi lo
    troverebbe, perché `hashlib.hexdigest()` è minuscolo dappertutto in questo
    ecosistema e nessuno dei 122 documenti veri lo scrive altrimenti. Non è una
    supposizione: c'è una prova che confronta le due strade su quel corpus, e il
    giorno in cui una grafia nuova comparisse sarebbe quella a dirlo.
    """
    bare = _normalise_digest(digest)
    return [bare, f"sha256:{bare}"] if bare else []


def _jsonpath_equals(paths: Tuple[str, ...], values: List[str]) -> List[str]:
    """Una jsonpath per (percorso × grafia), non una sola con gli `||` in mezzo.

    Misurato: `jsonpath` **non ha** un `||` fra espressioni di percorso — solo
    dentro un filtro — e la forma unita è un *«syntax error at or near "||" of
    jsonpath input»* a tempo di query, cioè un difetto che sarebbe uscito in
    produzione e non qui. L'alternativa, `$.**.checksum`, sarebbe stata peggio:
    corretta come sintassi e sbagliata come domanda, perché avrebbe trovato un
    `checksum` a qualunque profondità — dentro un paradato, dentro un blocco di
    metadati — e la ricerca avrebbe risposto di più senza dirlo.

    Quindi una lista, e chi chiama le mette in OR in **SQL**, dove l'OR esiste e
    dove il pianificatore può usare l'indice per ognuna.
    """
    return [f"{p} ? (@ == {json.dumps(v)})" for p in paths for v in values]


def projects_citing_digest(pool: Any, digest: str, *,
                           latest_only: bool = True) -> List[Tuple[str, int]]:
    """Quali studi citano questo digest: `[(project_id, revision)]`.

    È la domanda che `digest_index.py` esiste per non dover fare a mano — e che
    oggi si risponde leggendo **ogni documento** dell'istanza. Qui è una query.

    `latest_only` perché la domanda quasi sempre è *«chi lo cita adesso»*: con le
    revisioni come righe, senza questo filtro un digest tolto da uno studio
    tornerebbe come risposta per sempre, che è esattamente il contrario di quello
    che un gate vuole sapere.
    """
    wanted = spellings(digest)
    if not wanted:
        return []
    paths = _jsonpath_equals(_CHECKSUM_PATHS, wanted)
    sql = build_digest_query(len(paths), latest_only=latest_only)
    with pool.connection() as conn:
        rows = conn.execute(sql, tuple(paths)).fetchall()
    return [(row[0], row[1]) for row in rows]


def build_digest_query(how_many_paths: int, *, latest_only: bool = True) -> str:
    """La query, montata in un posto solo perché una prova possa `EXPLAIN`arla.

    **L'ORDINE È TUTTO, ed è stato misurato.** La prima versione restringeva alla
    riga più recente per progetto con un `DISTINCT ON` e poi filtrava per digest:

        Subquery Scan on d … Filter: (d.doc @? …)   Rows Removed by Filter: 121
          ->  Seq Scan on documents

    Il filtro cadeva **fuori** dalla sotto-query, quindi l'indice GIN non poteva
    entrarci nemmeno se il pianificatore l'avesse voluto: la tabella nuda non
    compariva mai in una condizione. Un indice costruito con cura, e nessuna
    query capace di usarlo.

    Così invece: **il digest restringe per primo, sulla tabella nuda** — dove
    l'indice vive — e solo le poche righe sopravvissute vanno a chiedere se sono
    la revisione corrente. Il caro passa dal numero dei documenti al numero di
    quelli che citano davvero quel digest.
    """
    where = " OR ".join(["doc @? %s::jsonpath"] * how_many_paths)
    hit = (f"SELECT project_id, revision FROM {TABLE} WHERE {where}")
    if not latest_only:
        return f"{hit} ORDER BY project_id, revision"
    return (f"WITH hit AS ({hit}) "
            f"SELECT h.project_id, h.revision FROM hit h "
            f"WHERE h.revision = (SELECT max(d2.revision) FROM {TABLE} d2 "
            f"                     WHERE d2.project_id = h.project_id) "
            f"ORDER BY h.project_id")


def _normalise_digest(value: Any) -> str:
    """`sha256:ABC` e `abc` sono lo stesso digest. Stessa regola di
    `digest_index._norm`, e la ragione per cui non è importata da lì è che quel
    modulo può sparire (vedi il report): questa riga no."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return (text.rsplit(":", 1)[-1] if ":" in text else text).lower()


# ── il modo di oggi, per poterlo misurare ────────────────────────────────────

def scan_documents_for_digest(documents: Iterator[Tuple[str, Dict[str, Any]]],
                              digest: str) -> List[str]:
    """La stessa domanda, fatta come si fa oggi: un ciclo su ogni documento.

    Sta qui e non in un benchmark buttato via perché **una misura senza il suo
    termine di paragone non è una misura**, e perché il giorno in cui la query
    SQL sbaglia questa funzione è la seconda opinione.
    """
    wanted = _normalise_digest(digest)
    found: List[str] = []
    for project_id, document in documents:
        for section in _sections(document):
            hit = any(_normalise_digest(((node or {}).get("data") or {})
                                        .get("checksum")) == wanted
                      for node in (section.get("nodes") or [])
                      if isinstance(node, dict))
            if hit:
                found.append(project_id)
                break
    return found


def _sections(document: Any) -> List[Dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    graphs = document.get("graphs")
    if isinstance(graphs, dict):
        return [g for g in graphs.values() if isinstance(g, dict)]
    return [document] if "nodes" in document else []


# ── l'indice che si invalida CON la scrittura ────────────────────────────────

_SCHEMA_LOCK = threading.Lock()

#: Il segno che questo pool ha già visto lo schema. **Un attributo sul pool, non
#: una mappa chiavata su `id(pool)`**: `id()` è l'indirizzo di un oggetto e viene
#: RIUSATO quando il primo muore, quindi un pool nuovo potrebbe ereditare il
#: «fatto» di un pool chiuso e saltare la creazione della tabella. È il genere di
#: difetto che non si vede mai finché non si vede.
_SCHEMA_MARK = "_em_documents_schema_done"


def ensure_schema_once(pool: Any) -> None:
    """`ensure_schema` una volta per pool. Non è un'ottimizzazione: è che un
    `CREATE OR REPLACE FUNCTION` a ogni scrittura prende un lock sul catalogo."""
    with _SCHEMA_LOCK:
        if getattr(pool, _SCHEMA_MARK, False):
            return
    ensure_schema(pool)
    with _SCHEMA_LOCK:
        setattr(pool, _SCHEMA_MARK, True)


# ── il trasloco ──────────────────────────────────────────────────────────────

def migrate_directory(pool: Any, directory: str, *, dry_run: bool = False
                      ) -> Dict[str, Any]:
    """I `<stanza>.em.json` di una directory diventano la revisione 0 in tabella.

    **Non è un extra: senza, una stanza che esisteva si apre VUOTA.** Il relay
    chiede il documento allo store, e lo store nuovo non ha mai visto quei file.
    Misurato sulla dev-stack di E.D.: 122 documenti nel volume, zero righe in
    tabella, 122 stanze che sarebbero ripartite da un container vuoto.

    **I BYTE DEL FILE, non un `put`.** `put` riserializza, e una migrazione che
    riserializza cambia l'impronta di ogni documento che trasloca: il criterio di
    questa notte — byte in, gli stessi byte fuori — varrebbe da domani in poi e
    non per quello che c'era prima. Qui entra il file com'è.

    **Idempotente per costruzione**, e non con un flag: un progetto che ha già
    righe non viene toccato. Rieseguirla dopo aver lavorato non sovrascrive il
    lavoro con il file vecchio, che è l'unico modo in cui una migrazione può
    fare danno.

    **Non cancella niente.** I file restano dove sono: in quella directory ci
    sono anche gli ACL, gli inviti e l'oplog, e un trasloco che porta via una
    cosa sola non è autorizzato a fare pulizia intorno.
    """
    root = pathlib.Path(directory)
    esito: Dict[str, Any] = {"traslocati": [], "gia_presenti": [], "rotti": [],
                             "directory": str(root)}
    if not root.is_dir():
        raise FileNotFoundError(f"non c'è nessuna directory {root}")

    ensure_schema_once(pool)
    for path in sorted(root.glob("*.em.json")):
        project = path.name[: -len(".em.json")]
        byte = path.read_bytes()
        with pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key(project),))
            gia = conn.execute(
                f"SELECT count(*) FROM {TABLE} WHERE project_id = %s",
                (project,)).fetchone()[0]
            if gia:
                esito["gia_presenti"].append(project)
                conn.commit()
                continue
            if dry_run:
                esito["traslocati"].append(project)
                conn.rollback()
                continue
            try:
                conn.execute(f"INSERT INTO {TABLE} (project_id, revision, raw) "
                             f"VALUES (%s, 0, %s)", (project, byte))
                conn.commit()
            except Exception as exc:        # noqa: BLE001
                # NON un difetto di programmazione: è un FILE che non è JSON,
                # cioè un fatto sul dato. Si dice quale e si va avanti, perché
                # fermarsi al primo lascerebbe il trasloco a metà senza dire
                # quanti altri erano buoni.
                conn.rollback()
                esito["rotti"].append({"project": project,
                                       "perche": str(exc).strip().splitlines()[0]})
                continue
            esito["traslocati"].append(project)
    return esito


# ── i residui del trasloco ───────────────────────────────────────────────────

#: I tre esiti di una verifica, e **tre comportamenti diversi**. Non è un
#: booleano «si può cancellare o no»: `assente` e `diverso` sono due guasti
#: differenti, con due cure differenti, e appiattirli su «no» toglierebbe
#: proprio l'informazione per cui questo strumento esiste.
VERIFICATO, ASSENTE, DIVERSO = "verificato", "assente", "diverso"

#: Cosa NON è un documento di stanza, e quindi non riguarda questo strumento.
#: **Contati sul volume vivo il 13-09-2026**, perché un elenco dedotto dal codice
#: avrebbe saltato gli ultimi due — e sono i due che non finiscono in `.json`
#: accanto a un nome di stanza, cioè quelli che un glob scritto a occhio
#: prenderebbe o lascerebbe per caso:
#:
#:     .room.json   295   RoomStore          .oplog.jsonl   87   Journal
#:     .acl.json    371   AclStore           .invites.json  18   Invites
#:     .room.tmp      1   una `put` mai conclusa (orfana, vecchia)
#:     groups.json    1   access.GroupStore
#:     blend-backup-register/  8 voci   blend_backups
#:
#: Sono SEI registri, non quattro. L'oplog in particolare ci vive tuttora,
#: perché `store_from_env` gli passa ancora `journal_root`. Uno strumento che
#: traslocava i documenti non è autorizzato a fare pulizia intorno, e infatti il
#: glob di `verify_directory` è `*.em.json` e nient'altro.
ALTRI_REGISTRI = (".room.json", ".acl.json", ".oplog.jsonl", ".invites.json",
                  ".room.tmp", "groups.json", "blend-backup-register")


def digest_of(byte: bytes) -> str:
    """L'impronta dei byte, nella stessa grafia della colonna generata.

    La colonna è `encode(sha256(raw), 'hex')`: minuscola, senza prefisso. Qui si
    calcola allo stesso modo **in Python**, perché il confronto deve essere fra
    ciò che c'è sul disco e ciò che il database ha calcolato da sé — far
    calcolare al database anche il primo dei due vorrebbe dire chiedergli se è
    d'accordo con se stesso.
    """
    return hashlib.sha256(byte).hexdigest()


def verify_directory(pool: Any, directory: str) -> Dict[str, Any]:
    """Per ogni `.em.json` della directory: **esiste una riga con esattamente
    questi byte?** → `{"verificati": […], "assenti": […], "diversi": […]}`.

    Il confronto è sul **digest dei byte**, non sul nome e non sulla data. Un
    nome dice quale progetto, non quale contenuto; una data dice quando il file
    è stato scritto, che dopo una copia o un `rsync` non vuol dire più niente.
    L'unica domanda che autorizza a cancellare un file è «questi byte sono al
    sicuro da un'altra parte», e a quella risponde solo l'impronta.

    I tre esiti:

    * **verificato** — esiste una riga con quel digest per quel progetto: il
      file è rimovibile;
    * **assente** — nessuna riga con quei byte, per nessuna revisione: il file
      **non si tocca**, ed è un risultato da gridare, perché vuol dire che il
      trasloco ha saltato qualcosa;
    * **diverso** — il progetto ha delle righe, ma nessuna con quei byte: il
      file **non si tocca**, e si dice quali digest ci sono invece, perché è o
      una revisione più vecchia del documento o un documento che è cambiato
      dopo il trasloco — e quelle due cose si distinguono guardando le
      revisioni, non indovinando.

    **Non cancella niente**, mai, in nessun caso. Chi cancella è `_main`, con un
    argomento esplicito, e solo i verificati.
    """
    root = pathlib.Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"non c'è nessuna directory {root}")

    ensure_schema_once(pool)
    esito: Dict[str, Any] = {"directory": str(root), "verificati": [],
                             "assenti": [], "diversi": []}
    for path in sorted(root.glob("*.em.json")):
        project = path.name[: -len(".em.json")]
        byte = path.read_bytes()
        atteso = digest_of(byte)
        with pool.connection() as conn:
            righe = conn.execute(
                f"SELECT revision, sha256 FROM {TABLE} WHERE project_id = %s "
                f"ORDER BY revision", (project,)).fetchall()
            conn.rollback()
        digest_in_tabella = {str(r[1]) for r in righe}
        voce = {"project": project, "file": path.name,
                "byte": len(byte), "digest": atteso}
        if atteso in digest_in_tabella:
            #: quale revisione li tiene: serve a chi legge l'elenco per capire
            #: se il file è la revisione 0 (il trasloco) o una più recente
            voce["revisione"] = next(int(r[0]) for r in righe
                                     if str(r[1]) == atteso)
            esito["verificati"].append(voce)
        elif not righe:
            esito["assenti"].append(voce)
        else:
            voce["in_tabella"] = [{"revisione": int(r[0]), "digest": str(r[1])}
                                  for r in righe]
            esito["diversi"].append(voce)
    return esito


def remove_verified(esito: Dict[str, Any]) -> Dict[str, Any]:
    """Toglie **solo** i file che `verify_directory` ha verificato.

    Prende l'esito e non la directory, di proposito: così non esiste un percorso
    in cui si cancella senza aver prima verificato: il parametro *è* la verifica.
    """
    root = pathlib.Path(esito["directory"])
    tolti, falliti = [], []
    for voce in esito["verificati"]:
        try:
            (root / voce["file"]).unlink()
            tolti.append(voce["file"])
        except OSError as exc:
            #: un permesso o un file già sparito è un fatto sul disco, non un
            #: difetto del codice: si dice quale e si va avanti
            falliti.append({"file": voce["file"], "perche": str(exc)})
    return {"tolti": tolti, "falliti": falliti}


def _main(argv: List[str]) -> int:
    """`python -m app.documents --from /srv/em-data/snapshots [--verify]`

    Dentro il container, dove la directory degli snapshot è montata e dove il
    nome di servizio `postgres` si risolve. `--dry-run` per guardare prima.

    Due verbi e non uno, perché sono due gesti diversi: **traslocare** porta i
    file dentro, **verificare** dice se i byte che sono dentro sono gli stessi
    dei file — ed è la domanda che va fatta *prima* di togliere qualcosa.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Porta i <stanza>.em.json di una directory nella tabella "
                    "dei documenti, come revisione 0 — oppure verifica che i "
                    "byte dei file siano già in tabella.")
    parser.add_argument("--from", dest="directory",
                        default=os.environ.get("EM_SNAPSHOT_DIR", ""),
                        help="la directory degli snapshot (default: "
                             "EM_SNAPSHOT_DIR)")
    parser.add_argument("--dry-run", action="store_true",
                        help="dice cosa farebbe, senza scrivere")
    parser.add_argument("--verify", action="store_true",
                        help="non trasloca: dice, per ogni file, se esiste in "
                             "tabella una riga con ESATTAMENTE quei byte")
    parser.add_argument("--remove-verified", action="store_true",
                        help="con --verify: toglie dal disco i file verificati "
                             "(e SOLO quelli). Senza questo argomento non si "
                             "cancella niente")
    args = parser.parse_args(argv)

    if not args.directory:
        parser.error("serve --from, o EM_SNAPSHOT_DIR nell'ambiente")
    if args.remove_verified and not args.verify:
        #: cancellare senza aver verificato non è un'opzione che si sbaglia a
        #: digitare: è la cosa che questo strumento esiste per impedire
        parser.error("--remove-verified vale solo con --verify: non si toglie "
                     "un file senza aver prima chiesto se i suoi byte sono al "
                     "sicuro")
    dsn = dsn_from_env()
    if not dsn:
        parser.error("EM_DOCUMENTS_* non è configurato: non c'è nessuna casa "
                     "in cui traslocare")

    pool = open_pool(dsn)
    try:
        if args.verify:
            return _verifica(pool, args)
        return _trasloco(pool, args)
    finally:
        pool.close()


def _trasloco(pool: Any, args: Any) -> int:
    esito = migrate_directory(pool, args.directory, dry_run=args.dry_run)
    prefisso = "(prova) " if args.dry_run else ""
    print(f"{prefisso}dalla directory {esito['directory']}")
    print(f"  traslocati   : {len(esito['traslocati'])}")
    print(f"  già presenti : {len(esito['gia_presenti'])} (non toccati)")
    print(f"  rotti        : {len(esito['rotti'])}")
    for rotto in esito["rotti"]:
        print(f"    · {rotto['project']}: {rotto['perche']}")
    return 1 if esito["rotti"] else 0


def _verifica(pool: Any, args: Any) -> int:
    """Elenca, e cancella **solo** se glielo si chiede per nome.

    Il valore d'uscita distingue i due guasti dal nulla di fatto: **2** se
    qualche file non è al sicuro (assente o diverso), 0 se sono tutti
    verificati. Un `grep` su un elenco è una lettura; un valore d'uscita è una
    cosa che uno script può guardare.
    """
    esito = verify_directory(pool, args.directory)
    print(f"nella directory {esito['directory']}")
    print(f"  verificati : {len(esito['verificati'])} (i byte sono in tabella)")
    print(f"  assenti    : {len(esito['assenti'])} (NESSUNA riga con quei byte)")
    print(f"  diversi    : {len(esito['diversi'])} (righe sì, ma altri byte)")

    for voce in esito["assenti"]:
        #: da gridare: vuol dire che il trasloco ha saltato qualcosa, e quel
        #: documento esiste in un posto solo
        print(f"    ASSENTE  {voce['file']}  ({voce['byte']} byte, "
              f"{voce['digest'][:12]}…)")
    for voce in esito["diversi"]:
        presenti = ", ".join(f"r{r['revisione']}={r['digest'][:12]}…"
                             for r in voce["in_tabella"])
        print(f"    DIVERSO  {voce['file']}  file={voce['digest'][:12]}… "
              f"| in tabella: {presenti}")

    if not args.remove_verified:
        if esito["verificati"]:
            print(f"\n  non è stato cancellato niente. Per togliere i "
                  f"{len(esito['verificati'])} verificati:")
            print(f"    python -m app.documents --from {esito['directory']} "
                  f"--verify --remove-verified")
        return 2 if (esito["assenti"] or esito["diversi"]) else 0

    tolti = remove_verified(esito)
    print(f"\n  tolti dal disco : {len(tolti['tolti'])}")
    print(f"  non tolti       : {len(tolti['falliti'])}")
    for guasto in tolti["falliti"]:
        print(f"    · {guasto['file']}: {guasto['perche']}")
    #: gli assenti e i diversi restano dove sono, e il valore d'uscita continua
    #: a dirlo: aver cancellato i buoni non rende meno grave che ce ne siano di
    #: non al sicuro
    return 2 if (esito["assenti"] or esito["diversi"] or tolti["falliti"]) else 0


if __name__ == "__main__":   # pragma: no cover — è uno strumento, non una rotta
    import sys

    raise SystemExit(_main(sys.argv[1:]))
