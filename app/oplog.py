"""Il registro della stanza, che dura.

════════════════════════════════════════════════════════════════════════════════
## COSA C'ERA GIÀ, E COSA MANCAVA

Quasi tutto c'era. Il join accetta `?since=`, `replay_since()` è corretta,
`host_info` annuncia `compacted_upto` con la regola scritta accanto. Mancava una
cosa sola: **il registro viveva in memoria e moriva col processo**, tagliato a
`OPLOG_LIMIT = 512`.

Misurato prima di scrivere una riga, sulla dev-stack:

    scritte 6 operazioni · cursore 2026-09-28T10:05:00Z
    rientro con since=…10:02:00Z  → 3 operazioni riprodotte  ✓
    docker restart em-dev-server
    LO STESSO rientro               → 0 operazioni riprodotte

## DUE MEMORIE, DUE MESTIERI

`Room.oplog` resta quello che era: una **finestra in memoria** di 512
operazioni, veloce, che serve il caso normale — un client che si riaffaccia dopo
qualche minuto.

Questo file è la **memoria profonda**: un JSONL accanto allo snapshot, che
sopravvive al riavvio e tiene molto più indietro. Si legge solo quando la
finestra in memoria non arriva abbastanza indietro, cioè quasi mai.

Non dentro l'`em.json`: quello è un formato che l'ecosistema intero sa leggere,
e infilarci una coda di operazioni ne farebbe un formato nostro. È la stessa
ragione per cui il ponte di StratiField sta accanto al container e non dentro.

════════════════════════════════════════════════════════════════════════════════
## QUANTO TIENE, E PERCHÉ QUEL NUMERO

**Misurato**, mandando una scheda ICCD intera sul socket di una stanza vera:

    add_node        324 byte (mediana)
    update_field    155 byte (mediana)
    add_edge        176 byte
    ── una scheda ICCD: 29 operazioni, 5019 byte  →  173 byte per operazione

Il caso che deve coprire è **un telefono via due giorni su uno scavo attivo**.
Una squadra che registra trenta unità al giorno — che è molto — fa 60 schede in
due giorni: **~1740 operazioni, ~300 KB**.

`KEEP_OPS = 10_000` copre quel caso **cinque volte e mezzo** e costa, alla
dimensione misurata, **1,7 MB per stanza** — meno del documento più grande di
questo nodo (`sarmizegetusa`, 2,3 MB). Il tetto è `KEEP_OPS × la dimensione di
un'operazione`: una stanza le cui operazioni fossero dieci volte più grandi
(descrizioni lunghissime) farebbe un registro da 17 MB, ed è il caso da
guardare. **Dichiarato, non sorvegliato**: un secondo limite sui byte
sorveglierebbe un caso che non ho visto, e il primo è già verificabile.

## A CONTEGGIO E NON A TEMPO, e la ragione non è la comodità

Il registro è ordinato dal `ts` delle operazioni, che è **l'orologio del
client** — il relay lo onora apposta, perché una nota dettata in trincea alle 10
e sincronizzata alle 18 deve portare le 10. Potare a tempo su quel campo
vorrebbe dire che **un client con l'orologio sbagliato pota il registro della
stanza**: una ritenzione controllata da chi scrive.

Ogni riga porta anche `at`, l'istante in cui il **server** l'ha ricevuta. Non
serve alla riproduzione — quella usa il `ts` — e costa trenta byte: serve a
leggere il registro, che è l'altro mestiere (vedi «rigiocabile e leggibile» in
fondo), e sarebbe la base di una ritenzione a tempo se un giorno la si volesse.

## E NON DIPENDE DAL WATERMARK

`gc_watermark()` misura la **consegna** e non l'applicazione — misurato il 27
settembre — e **un client su tre manda `ack`**. Un registro la cui durata
dipendesse da quel numero si accorcerebbe da solo per ragioni che nessuno
controlla. La ritenzione è una politica di questo file, e di nessun altro.

════════════════════════════════════════════════════════════════════════════════
## LA SCRITTURA: FLUSH SÌ, FSYNC NO — con i numeri

    flush soltanto   mediana 0,005 ms · p95 0,007 ms
    flush + fsync    mediana 0,361 ms · p95 1,549 ms
    (un'operazione sul socket, misurata il 26/09: 0,1 ms)

`fsync` moltiplicherebbe per quattro il costo di un'operazione, e per quindici
al novantacinquesimo percentile. E **non comprerebbe niente**: `store.put`, che
scrive il documento, non fa `fsync`. Un `fsync` qui renderebbe il registro più
durevole del documento che accompagna — e una mancanza di corrente che perde la
coda del registro perde anche quella del documento.

La morte del processo — `docker restart`, che è il caso frequente — non perde
niente in nessuno dei due: le scritture bufferizzate sono del sistema
operativo, non del processo.

**Diverso dal ponte di StratiField, che invece fa `fsync`**, e la differenza è
la ragione: là la coda è **l'unica copia** di quel lavoro; qui il registro
accompagna un documento che lo stesso processo scrive sullo stesso ritmo.

## UN SOLO SCRITTORE, E NESSUN LUCCHETTO FRA PROCESSI

Il ponte usa `flock` perché due processi hanno condiviso quella coda per caso.
Qui no: **una stanza vive in un processo solo** — `RoomRegistry` è la copia di
lavoro di *questo* relay, e due relay sullo stesso snapshot sarebbero già un
problema molto più grande di un registro. E la scrittura è un `append`, che il
sistema operativo serializza da sé quando il file è aperto in `"a"`.

Il lucchetto c'è comunque **fra i thread**, perché la potatura riscrive il file
e non deve incrociare un `append`.

════════════════════════════════════════════════════════════════════════════════
## IL NUMERO D'ARRIVO (`seq`) E L'EPOCA — dal 17 ottobre 2026

Il registro è ordinato dall'arrivo, ma fino a qui lo si interrogava sul `ts`,
che è l'orologio del client. Per il socket e per `/changes` va bene così; per un
**cursore** no. Misurato prima di scrivere (letto nel codice dei tre client, 12 e
17 ottobre): StratiField consegna la sua coda
(anche da `POST /ops`) con il `ts` del momento in cui la scheda è stata dettata,
EMStudio ed EMtools rientrano con `since` = il `ts` dell'ultima operazione vista.
Un telefono che consegna alle 11:05 il lavoro delle 10 resta invisibile a chi ha
già un cursore «10:58». Vedi `docs/SPEC-REST-LETTURA-STANZA.md` §2.

Quindi ogni riga scritta da qui in avanti porta `seq`, un intero che cresce di
uno per stanza **nell'ordine in cui il server ha ricevuto**, e il registro porta
una riga-marcatore `{"epoch": …, "from_seq": …}`: un registro buttato e rifatto
riparte da `seq` 1 con un'epoca nuova, e un cursore della vita precedente non
può più sembrare valido. Il cursore che le rotte REST danno al client è
`"<epoca>:<seq>"`, opaco.

Le righe di prima, senza `seq`, restano leggibili e non contano come rovinate.
Quando un registro vecchio riceve la sua epoca, `from_seq` è il numero di righe
senza `seq` che contiene: quelle stanno «prima del numero 1» e un cursore non le
può indirizzare (la risposta è `incomplete`, orizzonte `began`).

Il socket **non cambia** in questa versione: `since` resta un `ts`.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("stratigraph.oplog")

#: Quante operazioni tiene un registro. Il conto sta in cima al file.
KEEP_OPS = int(os.environ.get("EM_OPLOG_KEEP", "10000"))

#: Quanto lo si lascia crescere oltre il tetto prima di potarlo. Potare
#: riscrive il file: farlo a ogni operazione oltre il tetto significherebbe
#: riscrivere 1,7 MB per ogni operazione di una stanza attiva. Con questo
#: margine si riscrive una volta ogni mille.
SLACK = int(os.environ.get("EM_OPLOG_SLACK", "1000"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_marker(voce: Dict[str, Any]) -> bool:
    """Un segno e non un'operazione: compattazione o epoca. Un marcatore che
    non passasse di qui finirebbe nel contatore `unreadable` e in `/health`
    come registro rovinato — la trappola che la specifica nomina."""
    return "op" not in voce and ("compacted_upto" in voce or "epoch" in voce)


def parse_cursor(cursor: Optional[str]) -> Optional[Tuple[str, int]]:
    """`"<epoca>:<seq>"` → `(epoca, seq)`, o `None` se non è un cursore."""
    if not cursor or ":" not in str(cursor):
        return None
    epoca, _, numero = str(cursor).partition(":")
    if not epoca or not numero.isdigit():
        return None
    return epoca, int(numero)


class Journal:
    """Un registro durevole per una stanza: JSONL, in append, accanto al documento.

    Non decide niente sulla riproduzione: tiene le righe e le ridà in ordine.
    Chi può rigiocarle, e fino a dove, lo decide `app/ws.py` — perché è lì che
    si sa cosa la stanza ha già compattato.
    """

    def __init__(self, path: str, *, keep: int = KEEP_OPS,
                 slack: int = SLACK) -> None:
        self.path = pathlib.Path(path)
        self.keep = keep
        self.slack = slack
        self._lock = threading.Lock()
        #: quante righe ci sono, senza rileggere il file a ogni append. Conta
        #: dal disco la prima volta e poi si tiene aggiornato.
        self._count: Optional[int] = None
        #: righe illeggibili incontrate leggendo. Contate e non nascoste: un
        #: registro che salta righe in silenzio è peggio di uno che non c'è.
        self.unreadable = 0
        #: L'EPOCA e il numero d'arrivo, letti dal disco la prima volta che
        #: servono e poi tenuti in memoria (vedi la testa del file). `_seq` è
        #: l'ultimo numero scritto; `None` = non ancora letto.
        self._epoch: Optional[str] = None
        self._from_seq = 0
        self._seq: Optional[int] = None

    # ── scrivere ────────────────────────────────────────────────────────────

    def mark_compacted(self, upto: str, *, at: str) -> None:
        """Segna fin dove la stanza è stata compattata.

        ════════════════════════════════════════════════════════════════════
        PERCHÉ STA QUI DENTRO E NON ALTROVE

        `Room.compacted_upto` vive in memoria e riparte da `None` a ogni
        riavvio. Finché il registro moriva col processo era coerente: nessun
        registro, nessuna riproduzione, nessun pericolo.

        Con un registro che dura, no. Dopo un riavvio il documento sul disco è
        **già compattato** e `compacted_upto` sarebbe `None`: il rifiuto che
        impedisce la resurrezione di un arco non scatterebbe **proprio quando
        il registro comincia a contare**. La guardia sarebbe evaporata nel
        momento in cui serve.

        Quindi il punto di compattazione sta nel registro, che è il file la cui
        vita coincide con quella della riproduzione: **una guardia non deve
        poter sopravvivere alla prova che la giustifica, né il contrario.**
        """
        with self._lock:
            self._load_state()
            self._ensure_epoch()
            # IL SEGNO PORTA IL NUMERO D'ARRIVO a cui è stato scritto: è così
            # che una lettura per cursore sa se una compattazione è venuta DOPO
            # il documento che il client ha in mano.
            riga = json.dumps({"at": at, "compacted_upto": upto,
                               "seq": self._seq}, ensure_ascii=False)
            self._write(riga)

    def compacted_upto(self) -> Optional[str]:
        """L'ultimo punto di compattazione segnato, o `None`."""
        if not self.path.is_file():
            return None
        trovato = None
        with self._lock:
            for riga in self.path.read_text(encoding="utf-8").splitlines():
                if "compacted_upto" not in riga:
                    continue
                try:
                    voce = json.loads(riga)
                except ValueError:
                    continue
                segno = voce.get("compacted_upto")
                if segno and (trovato is None or str(segno) > trovato):
                    trovato = str(segno)
        return trovato

    def append(self, op: Dict[str, Any], *, at: str) -> int:
        """Una riga. `at` è l'istante del SERVER, e non è il `ts` dell'operazione.

        Restituisce il suo `seq`, il numero d'arrivo (vedi la testa del file).
        """
        with self._lock:
            self._load_state()
            self._ensure_epoch()
            seq = int(self._seq or 0) + 1
            riga = json.dumps({"at": at, "seq": seq, "op": op},
                              ensure_ascii=False)
            self._write(riga)
            self._seq = seq
            if self._count > self.keep + self.slack:
                self._prune()
            return seq

    def _write(self, riga: str) -> None:
        """Sotto il lucchetto di chi chiama."""
        if self._count is None:
            self._count = self._count_lines()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(riga + "\n")
            handle.flush()
        self._count += 1

    def _load_state(self) -> None:
        """Epoca, `from_seq` e ultimo `seq`, dal disco. Una volta sola.

        Sotto il lucchetto di chi chiama. Un registro vecchio senza epoca
        lascia `_epoch` a `None`: la riceve alla prima scrittura (o al primo
        cursore chiesto), con `from_seq` = le righe di prima.
        """
        if self._seq is not None and self.path.is_file():
            return
        # …E UN FILE SPARITO È UNA VITA FINITA. `forget` di un'altra istanza
        # (la cancellazione di una stanza apre un `Journal` suo) butta il file
        # sotto i piedi di questa: senza questa riga l'epoca in memoria
        # sopravvivrebbe al registro, e un cursore della vita di prima
        # continuerebbe a sembrare buono.
        epoca, da, ultimo, vecchie, righe = None, 0, 0, 0, 0
        if self.path.is_file():
            for riga in self.path.read_text(encoding="utf-8").splitlines():
                if not riga.strip():
                    continue
                righe += 1
                try:
                    voce = json.loads(riga)
                except ValueError:
                    continue
                if not isinstance(voce, dict):
                    continue
                if "epoch" in voce and "op" not in voce:
                    epoca = str(voce["epoch"])
                    da = int(voce.get("from_seq") or 0)
                    continue
                if isinstance(voce.get("seq"), int) and "op" in voce:
                    ultimo = max(ultimo, voce["seq"])
                elif "op" in voce:
                    vecchie += 1
        if epoca is None:
            da = vecchie + ultimo
        self._epoch, self._from_seq = epoca, da
        self._seq = max(ultimo, da)
        self._count = righe

    def _ensure_epoch(self) -> None:
        """Sotto il lucchetto. Scrive il marcatore d'epoca se manca."""
        if self._epoch is not None:
            return
        self._epoch = secrets.token_hex(4)
        self._write(json.dumps({"at": _now(), "epoch": self._epoch,
                                "from_seq": self._from_seq},
                               ensure_ascii=False))

    def cursor(self) -> str:
        """Il cursore di ADESSO: `"<epoca>:<ultimo seq>"`.

        Può scrivere il marcatore d'epoca, una volta nella vita del registro.
        Chiamata in un tratto sincrono insieme alla lettura del documento, è
        il punto da cui un client riparte (`GET …/document`).
        """
        with self._lock:
            self._load_state()
            self._ensure_epoch()
            return f"{self._epoch}:{self._seq}"

    def _count_lines(self) -> int:
        if not self.path.is_file():
            return 0
        with open(self.path, "rb") as handle:
            return sum(1 for _ in handle)

    def _prune(self) -> None:
        """Tiene le ultime `keep` righe. Sotto il lucchetto di chi chiama.

        Riscrittura su `.tmp` e `replace`, come lo store: se il nodo muore a
        metà, quello che resta sul disco è il registro di prima — vecchio, e
        leggibile. Un registro troncato a metà riga non lo sarebbe.
        """
        try:
            righe = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:                # noqa: BLE001
            log.warning("oplog: non ho potuto potare %s: %s", self.path, exc)
            return
        resto = righe[-self.keep:]
        # IL SEGNO DI COMPATTAZIONE NON SI POTA. Se cadesse fuori dalla
        # finestra, dopo una potatura il rifiuto smetterebbe di scattare — e
        # sarebbe una guardia che sparisce da sola, in silenzio, su una stanza
        # attiva. Si ripesca il più recente e si rimette in testa.
        segno = None
        for riga in righe:
            if "compacted_upto" in riga:
                try:
                    voce = json.loads(riga)
                except ValueError:
                    continue
                if voce.get("compacted_upto"):
                    segno = riga
        if segno is not None and segno not in resto:
            resto.insert(0, segno)
        # …E NEMMENO QUELLO D'EPOCA: senza, il registro riletto dopo una
        # potatura non saprebbe più a quale vita appartengono i suoi numeri, e
        # ne inventerebbe una nuova — ogni cursore in mano ai client diventerebbe
        # `unknown_cursor` per una potatura, cioè per niente.
        epoca = next((r for r in righe if '"epoch"' in r and '"op"' not in r),
                     None)
        if epoca is not None and epoca not in resto:
            resto.insert(0, epoca)
        temporaneo = self.path.with_suffix(self.path.suffix + ".tmp")
        temporaneo.write_text("\n".join(resto) + "\n", encoding="utf-8")
        temporaneo.replace(self.path)
        self._count = len(resto)
        log.info("oplog: %s potato da %d a %d righe",
                 self.path.name, len(righe), len(resto))

    # ── leggere ─────────────────────────────────────────────────────────────

    def read(self) -> List[Dict[str, Any]]:
        """Le operazioni, in ordine di arrivo.

        Una riga illeggibile si salta e si CONTA. Perdere il resto del registro
        per un byte storto sarebbe il difetto che questo file esiste per
        chiudere, in miniatura — ed è la stessa scelta del ponte.
        """
        if not self.path.is_file():
            return []
        fuori: List[Dict[str, Any]] = []
        rotte = 0
        with self._lock:
            for riga in self.path.read_text(encoding="utf-8").splitlines():
                if not riga.strip():
                    continue
                try:
                    voce = json.loads(riga)
                except ValueError:
                    rotte += 1
                    continue
                if isinstance(voce, dict) and _is_marker(voce):
                    continue          # un segno, non un'operazione
                try:
                    fuori.append(voce["op"])
                except (KeyError, TypeError):
                    rotte += 1
        self.unreadable = rotte
        if rotte:
            log.warning("oplog: %d righe illeggibili in %s, saltate",
                        rotte, self.path)
        return fuori

    def read_rows(self) -> Dict[str, Any]:
        """Il registro per intero, righe e segni, **in una lettura**.

        `rows` sono le righe d'operazione intere (`at`, `seq` se c'è, `op`), in
        ordine di arrivo; `compactions` i segni di compattazione con il loro
        `seq`; `epoch` e `from_seq` dal marcatore. `read()` resta com'è perché
        altri la usano.

        Rilegge il file a ogni chiamata, come `read()`: il costo è misurato nel
        referto della MICRO del 16 ottobre (`.claude/wip/reports/2026-10-16-rest-completa/`).
        """
        fuori: Dict[str, Any] = {"epoch": None, "from_seq": 0, "rows": [],
                                 "compactions": [], "last_seq": 0}
        if not self.path.is_file():
            return fuori
        with self._lock:
            testo = self.path.read_text(encoding="utf-8")
        # EPOCA, `from_seq` e ultimo numero DAL FILE letto adesso, non dalla
        # memoria di questa istanza: è il file che il cursore deve riconoscere.
        vecchie = 0
        for riga in testo.splitlines():
            if not riga.strip():
                continue
            try:
                voce = json.loads(riga)
            except ValueError:
                continue
            if not isinstance(voce, dict):
                continue
            if "epoch" in voce and "op" not in voce:
                fuori["epoch"] = str(voce["epoch"])
                fuori["from_seq"] = int(voce.get("from_seq") or 0)
                continue
            if "compacted_upto" in voce and "op" not in voce:
                fuori["compactions"].append(
                    {"seq": voce.get("seq"), "upto": voce.get("compacted_upto")})
                continue
            if "op" in voce:
                seq = voce.get("seq")
                if isinstance(seq, int):
                    fuori["last_seq"] = max(fuori["last_seq"], seq)
                else:
                    vecchie += 1
                fuori["rows"].append({"at": voce.get("at"), "seq": seq,
                                      "op": voce["op"]})
        if fuori["epoch"] is None:
            # un registro di prima, che nessuno ha ancora numerato
            fuori["from_seq"] = vecchie
        fuori["last_seq"] = max(fuori["last_seq"], fuori["from_seq"])
        return fuori

    def since(self, cursor: str) -> List[Dict[str, Any]]:
        """Le operazioni con un `ts` successivo al cursore.

        Lo stesso confronto di `Room.replay_since`: lessicografico su un ISO in
        UTC, che per quel formato è l'ordine cronologico.
        """
        return [op for op in self.read() if str(op.get("ts") or "") > cursor]

    def oldest(self) -> Optional[str]:
        """Il `ts` più vecchio che questo registro tiene ancora — cioè **fin dove
        si può guardare indietro**. `None` se il registro è vuoto.

        Serve al rifiuto: un cursore più vecchio di questo non può ricevere un
        replay completo, e riceverne uno parziale sarebbe peggio del niente —
        il client crederebbe di essere allineato.
        """
        righe = self.read()
        istanti = [str(op.get("ts") or "") for op in righe if op.get("ts")]
        return min(istanti) if istanti else None

    def __len__(self) -> int:
        with self._lock:
            if self._count is None:
                self._count = self._count_lines()
            return self._count

    def describe(self) -> Dict[str, Any]:
        with self._lock:
            self._load_state()
            epoca, ultimo = self._epoch, self._seq
        return {"entries": len(self), "keep": self.keep,
                "path": str(self.path), "unreadable": self.unreadable,
                "compacted_upto": self.compacted_upto(),
                "epoch": epoca, "seq": ultimo}

    def forget(self) -> None:
        """Butta il registro. Usata solo dai test e da chi dismette una stanza."""
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._count = 0
            # …e la sua vita: il prossimo registro ha un'epoca nuova
            self._epoch, self._from_seq, self._seq = None, 0, None


def journal_for(store: Any, room_id: str) -> Optional[Journal]:
    """Il registro che accompagna una stanza, **se c'è un posto dove metterlo**.

    Accanto agli snapshot quando lo store è una directory; `None` quando è in
    memoria — su un portatile senza `EM_SNAPSHOT_DIR` non c'è niente che
    sopravviva al processo, e un registro che finge di durare sarebbe peggio di
    nessun registro. `/health` dice quale dei due.

    `journal_root` PRIMA di `root`, e non è una preferenza: uno store che tiene i
    documenti altrove — `PostgresSnapshotStore` — non ha un `root`, e senza
    questa riga il registro sarebbe sparito in silenzio il giorno del trasloco,
    lasciando una stanza senza riproduzione dopo un riavvio e nessuna frase a
    dirlo. Il registro è un log in coda, non un documento versionato: la sua casa
    è una domanda a parte, e lo store la risponde per nome invece di lasciarla
    dedurre da un attributo che significa un'altra cosa.
    """
    root = getattr(store, "journal_root", None) or getattr(store, "root", None)
    if root is None:
        return None
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in room_id)
    return Journal(str(pathlib.Path(root) / f"{safe}.oplog.jsonl"))


def describe(journal: Optional[Journal]) -> str:
    if journal is None:
        return "memory only (dies with the process — no replay after a restart)"
    return f"durable, keeping {journal.keep} operations per room"
