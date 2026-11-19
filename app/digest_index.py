"""digest → embargo, for the hottest path there is.

Every IIIF tile is a request, and every request asks the same question: *is the
picture with this sha256 under embargo, and may this caller have it?* Answering
it honestly means reading the graph — and, because a IIIF identifier carries no
room, reading **every room this instance holds**. That is O(rooms) per tile, on
the one path a viewer hits hundreds of times while somebody pans an image.

So: an index. And the whole design of it is in one decision —

    it is invalidated by the WRITE, never by a clock.

A cache with a TTL would be a *cache of an embargo*: for up to N seconds it
would answer with a rule that is no longer the rule, which is exactly what the
asset gate promises not to do ("the store consults the graph; it does not keep a
second copy of it"). A room bumps `Room.revision` when its document changes; this
index remembers the revision it read and rebuilds the moment it differs. There is
no window in which it can be stale — the invalidation is the event, not the
timer.

It is **derived**, in the same sense the Catalog's index is: throw it away and it
comes back from the documents. Nothing depends on it being warm, and a miss is
not an error — it is a read.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from s3dgraphy import api as em


class DigestIndex:
    """Which rooms say something about which digest, kept in step with the rooms.

    The entry per room is `{digest: rights}` — the rights dict `asset_rights`
    returns, minus nothing: storing a boolean "embargoed" would freeze a verdict
    that is computed from today's date, and an embargo that expires tomorrow
    would still be refusing the file. What is cached is what the GRAPH SAYS; the
    *verdict* is recomputed on every question.
    """

    def __init__(self) -> None:
        # keyed by room id → (which working copy, which revision, what it says)
        self._by_room: Dict[str, Tuple[str, int, Dict[str, Dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        #: room id → the lock its (re)build holds, so a stale room is walked once
        self._building: Dict[str, threading.Lock] = {}

    def rooms_for(self, digest: str, rooms: List[Tuple[str, Any]]
                  ) -> List[str]:
        """Which of these rooms mention this digest at all.

        `rooms` is `[(room_id, room_or_None)]` — a live `Room` when the instance
        holds one. A room that is not live is not indexed and is reported as a
        candidate, because "I have not read it" must never read as "it says
        nothing": the caller then does the real read, which is the fallback this
        index is allowed to have.
        """
        wanted = _norm(digest)
        out: List[str] = []
        for room_id, room in rooms:
            if room is None:
                out.append(room_id)         # unread: ask properly
                continue
            entry = self._entry(room_id, room)
            if entry is None or wanted in entry:
                out.append(room_id)
        return out

    def rights(self, room_id: str, room: Any, digest: str
               ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """`(known, rights)` for this digest in this room.

        `known=False` means the index could not answer and the caller must read
        the graph — a miss, not a "no". Distinguishing the two is the difference
        between an index and a hole in the gate.
        """
        entry = self._entry(room_id, room)
        if entry is None:
            return False, None
        return True, entry.get(_norm(digest))

    # ── the same two questions, off the event loop ───────────────────────────
    #
    # A rebuild walks a whole document. Inside an `async` handler that walk held
    # the event loop: measured on 19 Nov 2026 with two 10.000-document rooms
    # open, `/health` did not answer for the 254–291 s the first audio GET took.
    # These run the question in a worker thread, so a long walk costs the one
    # request that needs it and nobody else.

    async def rooms_for_async(self, digest: str, rooms: List[Tuple[str, Any]]
                              ) -> List[str]:
        return await _off_loop(self.rooms_for, digest, rooms)

    async def rights_async(self, room_id: str, room: Any, digest: str
                           ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        return await _off_loop(self.rights, room_id, room, digest)

    def forget(self, room_id: str) -> None:
        with self._lock:
            self._by_room.pop(room_id, None)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"rooms": len(self._by_room),
                    "digests": sum(len(e) for _i, _rev, e in self._by_room.values())}

    # ── the build, and the one condition that triggers it ────────────────────

    def _entry(self, room_id: str, room: Any) -> Optional[Dict[str, Dict[str, Any]]]:
        revision = getattr(room, "revision", None)
        instance = getattr(room, "instance", None)
        if revision is None or instance is None:
            return None                     # not a room we can track
        with self._lock:
            cached = self._by_room.get(room_id)
            # BOTH halves of the key: the revision says the document changed,
            # the instance says it is a different working copy altogether. A
            # room rebuilt from the store starts again at revision 0, and
            # keying on the number alone hands it the previous room's answers.
            if cached is not None and cached[0] == instance and cached[1] == revision:
                return cached[2]
        # Built OUTSIDE the index lock: it walks a document, and holding that
        # lock across the walk would serialise every tile request behind one
        # room's scan. A per-room lock instead, so two requests arriving
        # together for a stale room walk it ONCE — the second waits and reads.
        with self._lock:
            building = self._building.setdefault(room_id, threading.Lock())
        with building:
            with self._lock:
                cached = self._by_room.get(room_id)
                if cached is not None and cached[0] == instance and cached[1] == revision:
                    return cached[2]
            try:
                built = _scan(room.document)
            except Exception:               # noqa: BLE001 — unreadable: no index
                return None
            # The walk may run in a worker thread (`rooms_for_async`) while the
            # event loop applies a write to this very document. If the revision
            # moved under it, what it read is a mixture of before and after: not
            # an answer. A miss, and the caller reads the graph properly.
            if (getattr(room, "revision", None) != revision
                    or getattr(room, "instance", None) != instance):
                return None
            with self._lock:
                self._by_room[room_id] = (instance, revision, built)
            return built


def _scan(document: Any) -> Dict[str, Dict[str, Any]]:
    """Every digest this document mentions, with what it says about it.

    One walk per room per revision, instead of one walk per room per REQUEST —
    and, since 19 Nov 2026, one walk per room per revision **in all**, instead of
    one per digest. It used to call `em.asset_rights(document, digest)` for every
    checksum, and each of those calls re-reads the whole document: quadratic.
    Measured in process on 10.000 audio documents (document + resource + edge),
    the walk took minutes, and it ran inside an `async` handler — the node
    answered nobody, `/health` included, for the whole of it.

    **What did NOT change is who decides.** The rights are still computed by
    s3dgraphy's `asset_rights`, the same function, the same rules (direct beats
    chain, tombstones do not speak, first alive resource wins). What this does is
    hand it a SMALLER document per digest: the sub-sequence of the room's nodes
    and edges that its walk can possibly look at for that digest — every node
    carrying the checksum, every rights or chain edge touching those nodes, every
    rights edge touching the chain steps they reach, and the nodes at the other
    end. Kept in the original ORDER, because order is part of the rule (the first
    licence edge wins, the first alive resource wins, the last node with a given
    id is the one a lookup finds). Built once per room, from one pass that
    indexes edges by endpoint.

    Over-inclusion is harmless (the walk ignores what it does not need); omission
    would be a hole. So the slice errs wide — tombstones included, both edge
    directions included — and `tests/test_digest_index_walk.py` checks the answer
    against the full-document one on every shape the rights module reads.

    If s3dgraphy's reader changes shape (the names below are its internals), this
    falls back to the old per-digest walk: slow, never wrong.
    """
    if _READER is None:
        return _scan_slowly(document)
    return _scan_in_one_pass(document, *_READER)


def _scan_slowly(document: Any) -> Dict[str, Dict[str, Any]]:
    """The walk as it was: `asset_rights` on the whole document, per digest."""
    out: Dict[str, Dict[str, Any]] = {}
    for section in _sections(document):
        for node in section.get("nodes") or []:
            data = node.get("data") if isinstance(node, dict) else None
            digest = _norm(data.get("checksum") if isinstance(data, dict) else None)
            if not digest or digest in out:
                continue
            rights = em.asset_rights(document, digest)
            if rights is not None:
                out[digest] = rights
    return out


def _scan_in_one_pass(document: Any, sections_of: Any, field: Any, text: Any,
                      chain_edges: Any, rights_edges: Any
                      ) -> Dict[str, Dict[str, Any]]:
    # Per section: where each digest sits, which nodes carry each id, and which
    # edges touch each id — split by the two kinds the rights walk follows.
    prepared = []
    order: List[str] = []                      # digests, first-seen order
    seen = set()
    for section in sections_of(document):
        if not isinstance(section, dict):
            continue
        nodes = list(section.get("nodes") or [])
        edges = list(section.get("edges") or [])
        by_digest: Dict[str, List[int]] = {}
        by_id: Dict[str, List[int]] = {}
        for i, node in enumerate(nodes):
            by_id.setdefault(str(field(node, "id", "node_id")), []).append(i)
            data = field(node, "data")
            digest = _norm(data.get("checksum") if isinstance(data, dict) else None)
            if digest:
                by_digest.setdefault(digest, []).append(i)
                if digest not in seen:
                    seen.add(digest)
                    order.append(digest)
        rights_at: Dict[str, List[int]] = {}
        chain_at: Dict[str, List[int]] = {}
        for j, edge in enumerate(edges):
            kind = text(field(edge, "edge_type", "type")) or ""
            if kind in rights_edges:
                target_map = rights_at
            elif kind in chain_edges:
                target_map = chain_at
            else:
                continue                       # the rights walk never reads it
            source = str(field(edge, "source", "edge_source") or "")
            target = str(field(edge, "target", "edge_target") or "")
            target_map.setdefault(source, []).append(j)
            if target != source:
                target_map.setdefault(target, []).append(j)
        prepared.append((nodes, edges, by_digest, by_id, rights_at, chain_at))

    def ends(edge: Any) -> Tuple[str, str]:
        return (str(field(edge, "source", "edge_source") or ""),
                str(field(edge, "target", "edge_target") or ""))

    out: Dict[str, Dict[str, Any]] = {}
    for digest in order:
        graphs: Dict[str, Dict[str, Any]] = {}
        for k, (nodes, edges, by_digest, by_id, rights_at, chain_at) in enumerate(prepared):
            carriers = by_digest.get(digest)
            if not carriers:
                continue                       # the walk skips this section too
            node_ix = set(carriers)
            edge_ix = set()
            for i in carriers:
                rid = str(field(nodes[i], "id", "node_id"))
                edge_ix.update(rights_at.get(rid, ()))
                for j in chain_at.get(rid, ()):
                    edge_ix.add(j)
                    for step in ends(edges[j]):
                        edge_ix.update(rights_at.get(step, ()))
            for j in list(edge_ix):
                for end in ends(edges[j]):
                    node_ix.update(by_id.get(end, ()))
            graphs[str(k)] = {"nodes": [nodes[i] for i in sorted(node_ix)],
                              "edges": [edges[j] for j in sorted(edge_ix)]}
        rights = em.asset_rights({"graphs": graphs}, digest) if graphs else None
        if rights is not None:
            out[digest] = rights
    return out


def _reader() -> Optional[Tuple[Any, ...]]:
    """s3dgraphy's own readers, so the slice is cut by the SAME rules the walk
    reads with. Private names: if they move, `None`, and `_scan` walks slowly."""
    try:
        from s3dgraphy import rights as r
        return (r._sections, r._field, r._text,
                frozenset(r._CHAIN_EDGES), frozenset(r._RIGHTS_EDGES))
    except Exception:                           # noqa: BLE001 — slow, not wrong
        return None


_READER = _reader()


async def _off_loop(fn: Any, *args: Any) -> Any:
    import asyncio
    return await asyncio.to_thread(fn, *args)


def _sections(document: Any) -> List[Dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    graphs = document.get("graphs")
    if isinstance(graphs, dict):
        return [g for g in graphs.values() if isinstance(g, dict)]
    return [document] if "nodes" in document else []


def _norm(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return (text.rsplit(":", 1)[-1] if ":" in text else text).lower()


#: One index per process. Derived state, so it is created here rather than
#: configured: there is nothing to choose, and losing it costs a rebuild.
INDEX = DigestIndex()
