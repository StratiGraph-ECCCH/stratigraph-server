# Field ↔ cloud synchronisation — what exists, what does not

**Audience:** WP4, PSNC and partners. Written for somebody who does not have this
codebase open.
**Origin:** WP4 meeting of 22 September 2026, action #9.
**Status:** a census, not a design. Every claim below was measured against the
code on 22 September 2026 by running it, not by reading it. Where a claim could
not be measured, it says so.

> **The one-sentence version.** The hard half — deciding *who wins* when the same
> study is edited in two places at once — is built, tested and running: it
> resolves **per field**, not per document, using clocks and a declared
> tie-break, and it reports the value that lost instead of discarding it. What
> is missing is not the algebra. It is the **delivery**: nothing on one node
> today knows that another node exists, or which of its changes that other node
> has not yet seen.

---

## 1 · What is already solved, and by what

The merge algebra lives in **s3Dgraphy**, the domain library shared by every
tool in the ecosystem (the desktop editor, the Blender add-on, the field
assistant and the server all call the same code). It is a plain Python module
with no network and no framework, which is why it can be proved on a table.

Measured: `s3dgraphy/crdt.py`, 997 lines; `tests/test_crdt.py`, 644 lines,
**32 tests, all passing** (`pytest tests/test_crdt.py -q` → `32 passed in
0.08s`). The whole server suite is also green: **822 passed, 2 skipped**.

### 1.1 The granularity of a difference: per **field**

The meeting minutes record this as an open question — *"at what granularity is
the diff computed, whole document or single node?"* The answer implemented here
is neither: it is **per field, with per-field clocks**.

Measured, two people editing the same unit at the same time:

| | they both stamped their fields | neither stamped fields |
|---|---|---|
| A edits `description`, B edits `note` | **both edits kept**, zero conflicts | A's whole node wins; B's `note` is lost |

This is the single most important thing on this page for anybody building a
client, so it is stated as a rule rather than as a result:

> **If you write a field, stamp it.** A writer that stamps the fields it touches
> gets true field-level merging. A writer that only stamps the node degrades,
> silently and correctly, to last-writer-wins over the whole node.

The fallback is deliberate and is the hinge the whole design turns on
(`crdt.py:192`): a node that records *no* field clocks comes from a tool that
does not keep them, so the node's own last-edit stamp answers for every field; a
node that records *some* field clocks comes from a tool that stamps what it
writes, so a field without one has **not** been touched since the node was
created, and it falls back to the *creation* stamp rather than to the last edit.
Without that second rule, one person's edit to one field would overwrite
everybody else's untouched fields.

Both of our writers stamp per field: the graph editor and the field assistant
each emit one `update_field` operation per box, carrying one timestamp for the
whole saving gesture.

### 1.2 The conflict rule: clock, then author — and the loser is named

Measured directly against `compare_clocks` (`crdt.py:126`), which returns a pair
— the ordering **and the reason**:

| situation | result | reason returned |
|---|---|---|
| later instant vs earlier | later wins | `newer` |
| same instant, two authors | smaller author id wins | `tie-author` |
| same instant, same author | equal — nothing moves | `tie-author` |
| one side has no stamp | the stamped side wins | `unstamped` |
| neither side has a stamp | equal — nothing moves | `unstamped` |

The `unstamped` reason is not cosmetic. An absent stamp is treated as
*unknown*, never as *older*, and the reason travels so that a reader is never
told "the date decided" when the date did not decide.

**Equality means equality, and that is what makes replay safe.** Re-applying the
same operation returns `0`, which is neither a win nor a loss, so nothing moves.
Delivering the same batch twice is harmless.

Every decided field produces a record like this one — measured output, not a
schema:

```json
{"node_id": "US1", "field": "data.description", "reason": "newer",
 "winner": {"by": "anna",  "at": "2026-01-03T09:00:00Z", "side": "mine"},
 "loser":  {"by": "bruno", "at": "2026-01-02T09:00:00Z", "side": "theirs"},
 "loser_value": "riporto"}
```

The losing value is carried, not dropped. In archaeology the discarded reading is
exactly what a reviewer wants to see.

### 1.3 Deletions, and resurrection as a reported event

Presence is an OR-Set with tombstones; a deletion and a concurrent edit converge
to the same answer whichever order they arrive in, and an edit **later** than a
deletion brings the node back — which is a legitimate act, so it is counted and
reported as `resurrected` rather than performed quietly.

### 1.4 Where the report actually goes — measured, and it is a split answer

The prompt for this census assumed the losing value was computed and thrown
away. Measured, that is **half true**, and the half that is true is the half
that matters for synchronisation:

* **Offline file merge → shown.** When a person integrates somebody else's file,
  the editor renders a conflict panel: *"{winner} overwrote {loser} on {node}"*,
  per field, with a **"Keep {who}'s version"** button that restores the losing
  value one node at a time. (`EMStudio/frontend/src/main.ts:3193`.)
* **Live room → dropped.** When the same decision is made by the relay, the
  writer is told `applied` and a one-word `reason`, and the per-field outcome
  list — including `loser_value` — never leaves the server process.

So the awareness surface exists, and it is wired to the path that field↔cloud
synchronisation will *not* use. That is a gap in §2, not a solved item.

### 1.5 Coverage, counted

The 32 CRDT tests, classified by name (each counted once):

| what it asserts | tests |
|---|---|
| convergence and order-independence | 6 |
| deletion, field removal and resurrection | 6 |
| garbage collection | 6 |
| field-level resolution and the clock fallback | 5 |
| the contract that writing a field stamps it | 4 |
| idempotence and refusal of a stale operation | 3 |
| a canonical digest, so the Python and TypeScript implementations cannot drift apart | 2 |

---

## 2 · What is not solved

Five items. Each was checked; two of the five turned out to be partly false as
originally stated, and they are corrected here rather than repeated.

### 2.1 There is no transport between two nodes — but the ingress already exists

**Correct as stated, and narrower than it sounds.**

There is no peer concept anywhere in the server: no node registry, no
per-peer cursor, no outbound client that speaks our own protocol. The server's
only outbound calls are health probes, identity (JWKS) and the image server.

What **does** exist, and should not be rebuilt:

| piece | where | note |
|---|---|---|
| batch operation ingress | `POST /v1/rooms/{id}/ops` | authenticated, idempotent, up to 1000 ops per call; a stale or already-applied op comes back inside `refused` on a **200**, because for a convergent system the refusal *is* the answer |
| live operation ingress | `WS /v1/rooms/{id}/ws` | the same verbs, WIRE 2 envelope |
| asset ingress | `PUT /v1/rooms/{id}/asset` | content-addressed |
| rights ingress | `POST /v1/corpus/merge` | additive, keyed by UUID, idempotent |
| the wire format | WIRE 2 | versioned; a mismatched speaker is refused with a sentence, not half-understood |
| a durable offline queue on the field side | the field assistant's bridge | append-only, `fsync`ed, **unbounded**, delivered in order and stopping at the first failure rather than reordering |

So the missing piece is **neither an endpoint nor a format**. It is three things:

1. **an egress driver** — something on node A that reads its own journal and
   posts to node B;
2. **a per-peer cursor** — "what has B already acknowledged from me", which
   nothing records today;
3. **an attribution route for a third-party push** (see 2.5, which is the reason
   1 and 2 are not simply a script).

### 2.2 The op-log ceiling — real, but it does not fail silently

**Partly false as originally stated.** The retention limit is real
(`oplog.py:119`, `KEEP_OPS = 10000`, overridable by environment). Pruning keeps
the last 10 000 lines and writes a log line saying how many it dropped; the
compaction marker is deliberately rescued from the pruned region so that a
safety check cannot disappear along with the history that justified it.

Crucially, **a client whose cursor has fallen off the back of the log is
refused, with an explanation**, and handed the whole document instead
(`ws.py:174`, reason `incomplete`): *"this room's log only reaches back to X and
your cursor is Y: a partial replay would leave you believing you are caught up."*
That is the correct behaviour and it is already there.

The arithmetic, computed from operation sizes measured on a real room
(173 bytes/op median; a full ICCD unit sheet = 29 operations):

| recording style | units/day | ops/day | ceiling reached on day | 21 days |
|---|---|---|---|---|
| trench entry (~8 fields) | 30 | 300 | 33 | 6 300 ops · 1.1 MB |
| full ICCD sheet | 10 | 290 | 34 | 6 090 ops · 1.1 MB |
| full ICCD sheet | 30 | 870 | **11.5** | 18 270 ops · 3.2 MB |
| full ICCD sheet | 50 | 1 450 | **6.9** | 30 450 ops · 5.3 MB |

**The conclusion is conditional on a design decision that has not been taken.**
If synchronisation ships *documents* (merge two em.json containers), the ceiling
is irrelevant: the container carries the state, not the history. If it ships
*operation logs*, then a three-week campaign at full-sheet rates overruns the
retention on the field node, and the log that arrives has a hole in it — and
unlike the replay path above, **nothing on the receiving side would detect
that**, because a batch posted to `/ops` carries no claim about what precedes it.

The disk cost of raising the limit is small at measured sizes (10× would be
~17 MB per room); the reason not to raise it blindly is that it is bounded by
operation *count* and not by *bytes*, so a room with very long text fields
scales differently.

### 2.3 Compaction and long offline periods are, today, incompatible

**Correct, and now measured rather than argued.**

Compaction (`crdt.py:918`) discards tombstones and field clocks older than a
given instant. Its precondition is the entire safety argument: that instant must
be one **every participant has passed**. The server computes it as the minimum
delivery watermark across *connected* members (`rooms.py:543`) — and an absent
node is not a connected member. The code says so itself: *"an absent client can
come back with an old op-log, which this cannot know about. That is the declared
limit of GC at this stage."*

Measured, using the library directly:

```
 add_edge(01 Jan) → added      remove_edge(02 Jan) → removed      live edges: 0
 A · no compaction, the old add_edge arrives again → idempotent   live edges: 0
 B · compacted at 20 Jan (1 edge dropped), same op → added        live edges: 1  ← resurrected
```

So: **an operation older than the compaction point resurrects what was deleted.**
The graph would state again that two stratigraphic units are in a relationship
after somebody had established that they are not. That is not lost work; it is a
false assertion inside an archaeological record.

There is a guard, and it is good — but it is **on the wrong door**. It protects
the WebSocket rejoin path (`ws.py:195`, reason `unsafe`: *"your cursor is older
than this room's compaction point"*). It does **not** protect `POST /ops`, which
applies each operation with no comparison against the compaction point. An
offline node delivering three weeks of work through the batch endpoint would
walk straight past it.

Two facts make this tractable rather than alarming:

* it is a **precondition of an existing function**, not a missing function: the
  caller states the instant it can justify;
* the refusal machinery, the vocabulary and the "use the snapshot instead"
  fallback all already exist and are tested end to end.

Until it is decided, this is a **constraint to write down**: a node that has been
away longer than the other node's compaction window must **resynchronise from
the document**, not replay its history.

### 2.4 Assets are not in the graph — and rights already have a route

**Partly false as originally stated.** What links an asset to the graph is its
**digest**: an operation cites `sha256:…`, the object store is indexed by the
same `sha256:…`, and there is no identifier to keep aligned between them,
because the name of the content *is* the content. The asset route
(`main.py:883`) reads the embargo from the graph on every request and never
caches it.

Rights are not stranded either. Every asset's provenance and licence live in a
**DTC corpus**, and there is already an additive, per-UUID, idempotent endpoint
for folding one node's corpus into another's (`main.py:1569`).

So moving one asset with its rights from field to cloud is, today, three calls
that all exist: upload the bytes, merge the corpus section, deliver the
operations that cite the digest — in that order, because an operation that
points at bytes nobody has yet is a false statement visible to everybody in the
room, whereas bytes nobody cites yet are merely an orphan object.

What is missing is again the **driver**: nothing enumerates which digests the
other node is missing. And one property has **not** been measured and should not
be assumed: whether the corpus merge preserves the original attributor or
re-attributes to the caller (see 2.5).

This matches what was said in the meeting — that if rights and metadata must
travel too, the transfer goes **through the services, not storage to storage**.
The services are the only place that can read the graph and decide.

### 2.5 Identity is a precondition, and there is a specific trap in it

**Correct, and there is a concrete mechanism behind it.**

Measured: the author of an operation is always the **identity on the caller's
token**, resolved as `orcid` → `preferred_username` → `sub`, and the client's own
`author` field is **dropped before anything else**, on both the WebSocket and
the HTTP path (`ws.py:651`). The comment is explicit: *"an author nobody verified
is not an author."*

This is the right rule, and it has two consequences for synchronisation:

**Good news.** The identity is an **ORCID**, mapped in the identity provider from
a user attribute rather than derived from the account. Two realms — one on the
field node, one on the cloud — that both carry the same ORCID attribute for the
same person produce the **same** author string, with no account merging needed
for the merge algebra to work. Account merging remains desirable for
administration; it is not a precondition for correct conflict resolution.

**The trap.** The fallback chain degrades **silently**. A user whose ORCID
attribute was not filled in gets `preferred_username`, or failing that `sub` —
and `sub` is the account's internal UUID **in that realm**, which is different on
the two nodes for the same human. The merge would then treat one person as two,
and the tie-break "smaller author id wins" would be deciding between two names
for the same hand. Nothing today warns that this has happened.

**The blocking one.** Because the author is taken from the *caller's* token, a
node that forwards a batch of operations written by twenty different people
would have all twenty **re-attributed to whoever pushed them**. A synchronisation
service cannot use a service account. Either the pushing node holds a token per
person (not workable for a batch), or the receiving node must be able to accept a
*verified* author from a peer it trusts — which is a trust decision, not an
implementation detail, and it is listed in §3.

---

## 3 · Decisions that remain open

Listed with what each one costs. None is chosen here.

### D1 · What travels: documents, or operations?

* **Documents** (merge two em.json containers, keyed by UUID). Uses code that
  exists and is tested; immune to the op-log ceiling (2.2); loses the fine
  ordering of who did what when; the whole container moves each time.
* **Operations** (ship the log). Cheap on the wire; preserves the record of the
  work; exposed to the ceiling in 2.2 and to the compaction hazard in 2.3, and
  both would need a new guard.
* **Both** (operations while the window allows, document when it does not).
  This is what the rejoin path already does for a *client*, so the vocabulary
  and the fallback exist. It costs one new thing: a **cursor per peer**.

### D2 · Compaction policy between nodes

Compaction and long offline periods are incompatible as things stand (2.3).
Options: never compact a room that has a known absent peer (cheap, but
bookkeeping grows without bound); keep a declared maximum offline window and
force a document resynchronisation past it (bounded, and costs an explicit
promise to the field team); or extend the existing `unsafe` refusal from the
rejoin path to the batch endpoint, so that a too-old delivery is *refused with
an explanation* rather than silently resurrecting deleted relationships. The
third option is strictly a safety improvement and is compatible with the other
two.

### D3 · Attribution across a trust boundary

See 2.5. Options: a per-person token held by the pusher (correct, impractical);
a signed, verified author carried inside the operation and accepted only from
peers on an explicit trust list (needs a new mechanism and an explicit trust
decision); or accepting that a synchronised batch is attributed to the node
rather than to the person (cheap, and it destroys the provenance that this
system exists to keep — noted because it is the default if nobody decides).

### D4 · Direction and topology

Field → cloud one-way, or bidirectional? The algebra is symmetric and costs
nothing extra either way, but bidirectional editing of the same room from two
nodes multiplies the exposure to D2. Also unresolved: whether the cloud node
runs as several replicas. Today one instance owns a room — this is a declared
and deliberate limit, not an oversight, and it is documented next to the code.

### D5 · Surfacing the losing value on the synchronised path

The per-field outcome, including the value that lost, exists at the moment of
the decision but is discarded before the answer leaves the server (1.4). A
synchronisation that resolves three weeks of concurrent work and reports only a
count would be worse in practice than the offline file merge is today. Carrying
it costs a field in a response and a place to show it; the display already
exists on the other path.

---

## 4 · What is needed from PSNC

1. **The answer to the minutes' Postgres-or-Virtuoso question — from your side,
   because ours is already determined by the facts.** In this system the
   **em.json container is the truth**, and every other form is a projection:
   RDF/Turtle, GraphML, IIIF manifests, the catalogue record. Postgres, when
   configured, is simply one of four interchangeable houses for that document
   (one row per revision, the original bytes served back unchanged), and the
   others are a directory, an object store, or memory. **There is no triple
   store in this system at all** — no Virtuoso, no Oxigraph, no Fuseki; Turtle
   is generated on demand from the container. So neither Postgres nor Virtuoso
   is the *object* of synchronisation. The object is the document, plus
   optionally its operation log. What we need to know is what **Virtuoso, on
   your side, must receive** — regenerated Turtle after each synchronisation, a
   stream of changes, or something else — and how stale it is allowed to be.

2. **A decision on D3, the trust boundary.** Whether the two identity providers
   can be arranged so the same person carries the same ORCID on both, and — if
   a node is to push work authored by other people — what mechanism you would
   accept for a verified third-party author. This is the item that blocks
   building anything, because it decides whether synchronisation is a script or
   a protocol change.

3. **The offline window you need to support, as a number.** The difference
   between three days and three weeks changes D1 and D2 (see the table in 2.2),
   and it is a field-practice question rather than an engineering one.

4. **Whether the cloud node is a single instance or replicated.** See D4.

5. **Test data of the real shape, if you have it** — a campaign's worth of
   units from a real excavation rather than our synthetic rooms. The ceiling
   arithmetic in 2.2 rests on one measured operation size and one measured sheet;
   the shape of the distribution would make it an observation instead of an
   estimate.

---

### Appendix · How to reproduce the measurements

```bash
# the merge algebra and its tests
cd s3Dgraphy && python -m pytest tests/test_crdt.py -q      # 32 passed

# the server, including replay refusal and resynchronisation end to end
cd stratigraph-server && python -m pytest -q                # 822 passed, 2 skipped

# the two most relevant suites by name
python -m pytest tests/test_resync_e2e.py tests/test_il_registro_che_dura.py -q
```

The named entry points, for a reader following the argument in the code:
`s3dgraphy/crdt.py` — `compare_clocks`, `field_clock`, `merge_payloads`,
`compact_section`; `stratigraph-server/app/ws.py` — `_replay_plan`;
`stratigraph-server/app/oplog.py` — `Journal`; `stratigraph-server/app/rooms.py`
— `gc_watermark`.
