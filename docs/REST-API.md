# The REST door of a room

*StratiGraph Server · written for project partners and for anyone building a
client. Every request and response on this page was run against the dev stack
on 17 October 2026, in the room `rest-2026-10-16`; nothing here is written by
hand except the abridgements, which say so. For the clickable reference, open
`/docs` on any node (`https://em.localhost:8443/em/docs` on the dev stack).*

## Two doors into the same room

A room is where a study is worked on: one Extended Matrix graph, the people who
may enter, and their roles. Since the beginning a room has had one door, a live
connection — the WebSocket `/v1/rooms/{room_id}/ws` — through which EMStudio,
EM-tools for Blender and StratiField on a tablet sit inside the room and see
every change the moment it is made. That door assumes that whoever uses it stays.
A phone does not stay. It is taken out of a pocket, used for a minute at the
edge of a trench, and put away again; the connection drops each time, and often
there is no network at all for an hour.

So a room now has a second door, made of ordinary requests. Whoever uses it
comes in, reads, writes, and leaves, and when they come back they ask what
happened while they were away. Both doors open onto the same room and the same
operations: a change written through one is seen through the other, and nobody
has to know which door the others are using.

What travels through both doors is the same thing: *operations*. Nobody uploads
a new version of the study. Every edit is a small, self-contained statement —
add a unit, set a field, link two units — stamped with who made it and when.
The room applies each one with the same library that EMStudio and EM-tools use,
and because operations are idempotent, receiving one twice changes nothing.
When two people change the same field, the more recent stamp wins and the
answer says whose value lost and what it was.

## The phone's cycle

The cycle has four steps, and they are the same whether the phone was away for
a minute or for a day. Every request carries a bearer token from the node's
identity service (`GET /v1/auth-config` says where to get one); below it is
`$TOKEN`.

**1 · Open: read the document and keep the cursor.** The first request returns
the room's document as it is now — the same document the socket sends to whoever
joins — together with a *cursor*: an opaque mark of the point the document
corresponds to. The role and whether it may write come with it, so the phone
knows before trying.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://em.localhost:8443/em/v1/rooms/rest-2026-10-16/document
```

```json
{
  "room_id": "rest-2026-10-16",
  "cursor": "d33795c2:4",
  "taken_at": "2026-10-17T08:21:56Z",
  "role": "editor",
  "can_write": true,
  "gc_watermark": null,
  "graph_id": null,
  "doc": {
    "header": {
      "format": "em.json",
      "version": "1.0"
    },
    "graphs": {
      "rest-2026-10-16": {
        "graph_id": "rest-2026-10-16",
        "name": "REST · prova della porta senza socket, 17 ottobre",
        "nodes": [
          {
            "id": "US1",
            "node_type": "US",
            "name": "US 1",
            "…": "…"
          },
          {
            "id": "US2",
            "node_type": "US",
            "name": "US 2",
            "…": "…"
          },
          {
            "id": "US3",
            "node_type": "US",
            "name": "US 3",
            "…": "…"
          }
        ],
        "edges": [
          {
            "id": "US1__is_before__US2",
            "…": "…"
          }
        ]
      }
    },
    "…": "the rest of the em.json (abridged here)"
  }
}
```

The document and the cursor come from the same instant: the server reads one
and serializes the other without letting anything else happen in between. A
cursor ahead of its document would make the phone skip operations; that cannot
happen. Someone who is not a member of the room gets `403` (`{"detail": "not a
member of this room"}`), and a room that does not exist is a `404` and is not
created by being asked about.

**2 · Write.** The phone sends its operations in batches. A refusal is not an
error: an operation that is older than what the room already holds, or that was
already applied, comes back inside `refused` with a `200`, because sending it
again would be refused again for ever. A retry after a timeout is therefore
safe. Here a second editor rewrites a description that the first had written a
second earlier, and the answer reports it in `conflicts`, with the value that
lost:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"ops": [{"op": "update_field", "node_id": "US2", "field": "description",
                "value": "Piano in cocciopesto, lacunoso a sud.", "ts": "2026-10-17T08:21:57.299Z"}]}' \
  https://em.localhost:8443/em/v1/rooms/rest-2026-10-16/ops
```

```json
{
  "applied": 1,
  "refused": [],
  "kept": {
    "at": "2026-10-17T08:21:57Z",
    "gc_watermark": null,
    "…": "what the store kept (abridged here)"
  },
  "conflicts": [
    {
      "op": "update_field",
      "id": null,
      "applied": true,
      "node_id": "US2",
      "field": "description",
      "reason": "newer",
      "winner": {
        "by": "0000-0003-2222-2221",
        "at": "2026-10-17T08:21:57.299Z",
        "side": "op"
      },
      "loser": {
        "by": "0000-0003-1111-1112",
        "at": "2026-10-17T08:21:56Z",
        "side": "state"
      },
      "loser_value": "Piano in cocciopesto, integro nel settore nord."
    }
  ]
}
```

**3 · Do not move the cursor after writing.** The operations the phone has just
sent will come back in the feed, together with everybody else's. They are
recognised and change nothing (they are idempotent). A cursor pushed forward by
the phone itself would jump over whatever others wrote in the meantime.

**4 · Come back: ask what arrived after the cursor.** On its return the phone
asks for the operations that reached the room after its cursor, in the order
they *arrived at the server*. Each one has the shape of an operation frame of
the socket (`graph_id` and `op`), so a client needs one reader for both doors.
The `cursor` of the answer becomes the new one; `has_more` says there is another
page (`limit`, at most the `ops_batch_max` that `/v1/health` announces).

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://em.localhost:8443/em/v1/rooms/rest-2026-10-16/ops?after=d33795c2:4"
```

```json
{
  "room_id": "rest-2026-10-16",
  "granted": true,
  "after": "d33795c2:4",
  "cursor": "d33795c2:5",
  "count": 1,
  "has_more": false,
  "operations": [
    {
      "graph_id": "rest-2026-10-16",
      "op": {
        "op": "update_field",
        "node_id": "US2",
        "field": "description",
        "value": "Piano in cocciopesto, lacunoso a sud.",
        "ts": "2026-10-17T08:21:57.299Z",
        "author": "0000-0003-2222-2221",
        "auth": {
          "mode": "node_password",
          "attested_by": "em.localhost:8443"
        }
      }
    }
  ],
  "reason": null,
  "detail": null,
  "resync": null,
  "horizon": null,
  "compacted_upto": null
}
```

Asked again from the new cursor, the feed answers with nothing new and the same
cursor:

```json
{
  "room_id": "rest-2026-10-16",
  "granted": true,
  "after": "d33795c2:5",
  "cursor": "d33795c2:5",
  "count": 0,
  "has_more": false,
  "operations": [],
  "reason": null,
  "detail": null,
  "resync": null,
  "horizon": null,
  "compacted_upto": null
}
```

Why the order of arrival, and not the time written in each operation: the time
in an operation is the clock of whoever wrote it, kept on purpose so that a note
dictated in the trench at ten o'clock still says ten o'clock when it is
delivered at six. A phone that was offline from ten to eleven delivers, at five
past eleven, operations stamped between ten and eleven. Someone who had read the
room at eleven and asked «what is newer than eleven?» would never see them. The
cursor of this door counts arrivals, so they are seen. (The socket still uses
the written time for its own re-join; that is noted, and not changed here.)

**When the server cannot serve a cursor**, it says so with a `200`,
`granted: false`, a reason and a sentence — and **no new cursor**, because the
only way to get a new cursor is to read the document again. The reasons are
`no_cursor` (a first look), `no_durable_log` (this node keeps no log on disk),
`unknown_cursor` (malformed, from another room, or from a log that has since
been rebuilt), `incomplete` (the log no longer reaches back that far, `pruned`,
or never did, `began`) and `unsafe` (after the cursor, an operation arrived that is older than a
clean-up in which the room had already thrown some bookkeeping away). The remedy is always the same:
read the document again, then re-apply the phone's own unconfirmed work on top.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://em.localhost:8443/em/v1/rooms/rest-2026-10-16/ops?after=00000000:0"
```

```json
{
  "room_id": "rest-2026-10-16",
  "granted": false,
  "after": null,
  "cursor": null,
  "count": 0,
  "has_more": false,
  "operations": [],
  "reason": "unknown_cursor",
  "detail": "this cursor does not belong to this room's log — malformed, from another room, or from a log that has since been rebuilt: read the document.",
  "resync": "/v1/rooms/rest-2026-10-16/document",
  "horizon": null,
  "compacted_upto": null
}
```

## Two more questions a returning person asks

*What changed since I last looked*, counted rather than replayed — who wrote, how
many operations, which units — is `GET …/changes?since=<instant>`:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://em.localhost:8443/em/v1/rooms/rest-2026-10-16/changes?since=2026-10-17T08:21:56Z"
```

```json
{
  "since": "2026-10-17T08:21:56Z",
  "readable_from": "2026-10-17T08:21:56.001Z",
  "replayable_from": "2026-10-17T08:21:56.001Z",
  "durable": true,
  "operations": 1,
  "by_author": {
    "0000-0003-2222-2221": 1
  },
  "by_verb": {
    "update_field": 1
  },
  "units": [
    {
      "id": "US2",
      "operations": 1,
      "what": [
        {
          "verb": "update_field",
          "said": "corretta",
          "times": 1
        }
      ],
      "authors": [
        "0000-0003-2222-2221"
      ],
      "first_at": "2026-10-17T08:21:57.299Z",
      "last_at": "2026-10-17T08:21:57.299Z"
    }
  ],
  "oldest": "2026-10-17T08:21:57.299Z",
  "newest": "2026-10-17T08:21:57.299Z",
  "complete": true,
  "horizon": null,
  "truncated": false
}
```

*Who is here*, and who wrote recently even without sitting in the room (a REST
client never sits), is `GET …/who?since=<instant>`:

```json
{
  "seated": [],
  "wrote_recently": [
    {
      "author": "0000-0003-2222-2221",
      "last_at": "2026-10-17T08:21:57Z",
      "nodes_touched": 1,
      "seated": false
    }
  ],
  "left": [],
  "recent_after": "2026-10-17T08:21:56Z",
  "beat": {
    "every_seconds": 10.0,
    "quiet_after_seconds": 30.0
  },
  "counts": {
    "seated": 0,
    "in": 0,
    "quiet": 0,
    "left": 0,
    "wrote_recently": 1
  }
}
```

## Every route

Grouped as `/docs` groups them; `token` says whether a bearer token is needed.
The same table is in the README, and a test fails if either disagrees with the
code.

| endpoint | what it does | token |
|---|---|---|
| `GET /v1/auth-config` | How to sign in to this node: realm, client and endpoints *(meta)* | — |
| `GET /v1/node` | What this node offers: its services and where they live *(meta)* | — |
| `GET /v1/health` | Liveness, versions and what this node can do *(meta)* | — |
| `GET /v1/whoami` | Who this token says you are *(meta)* | yes |
| `POST /v1/health/reach` | Knock now on every dependency, and refresh the health *(meta)* | yes |
| `GET /health` | Unversioned probe alias — same payload as /v1/health *(meta)* | — |
| `GET /open` | The web half of an «Open in…» link (an HTML page) *(rooms)* | — |
| `POST /v1/handoff/parse` | Read an «Open in…» link: which server, which room *(rooms)* | — |
| `GET /v1/rooms` | The rooms you have a role in *(rooms)* | yes |
| `POST /v1/rooms` | Create a room *(rooms)* | yes |
| `GET /v1/rooms/{room_id}` | One room: its title, its containers, its state *(rooms)* | yes |
| `DELETE /v1/rooms/{room_id}` | Delete a room (its assets stay, as orphans) *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/who` | Who is in the room now, and who wrote recently *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/waiting` | What waits for a signature: fields a model composed, not yet validated *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/statistics` | What the room holds: nodes, edges, epochs, gaps *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/operators` | Who has written in this room *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/changes` | What changed since an instant — counted, not replayed *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/document` | The room's document now, with the cursor to resume from *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/ops` | The operations that arrived after a cursor (the REST replay) *(rooms)* | yes |
| `POST /v1/rooms/{room_id}/ops` | Write graph operations into a room, over HTTP *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/chat` | What was said in the room, in order *(rooms)* | yes |
| `POST /v1/rooms/{room_id}/archive` | Archive a room, or bring it back *(rooms)* | yes |
| `POST /v1/rooms/{room_id}/invites` | Create an invitation link to a room *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/invites` | The invitation links of a room *(rooms)* | yes |
| `DELETE /v1/rooms/{room_id}/invites/{token_id}` | Revoke an invitation link *(rooms)* | yes |
| `POST /v1/join` | Accept an invitation link and enter the room *(rooms)* | yes |
| `GET /v1/rooms/{room_id}/open` | How to open this room in a tool, without typing anything *(rooms)* | yes |
| `PUT /v1/rooms/{room_id}/asset` | Store a file in a room, addressed by its content *(assets)* | yes |
| `POST /v1/rooms/{room_id}/asset-reference` | On a personal node, put a project's file in the room by reference *(assets)* | yes |
| `GET /v1/rooms/{room_id}/asset-home/{ref}` | Where a file lives, which rooms cite it, and what you may do *(assets)* | yes |
| `POST /v1/rooms/{room_id}/asset-home/{ref}` | Make this room the file's only home (no bytes travel) *(assets)* | yes |
| `POST /v1/rooms/{room_id}/uploads` | Start a resumable upload of a large file *(assets)* | yes |
| `GET, HEAD /v1/rooms/{room_id}/uploads/{upload_id}` | How far a resumable upload has got *(assets)* | yes |
| `PATCH /v1/rooms/{room_id}/uploads/{upload_id}` | Send the next piece of a resumable upload *(assets)* | yes |
| `DELETE /v1/rooms/{room_id}/uploads/{upload_id}` | Abandon a resumable upload *(assets)* | yes |
| `GET, HEAD /v1/rooms/{room_id}/asset/{ref}` | Download an asset of a room (Range requests welcome) *(assets)* | yes |
| `PUT /v1/rooms/{room_id}/blend-backup` | Keep a snapshot of a working Blender file *(assets)* | yes |
| `GET /v1/rooms/{room_id}/blend-backups` | Your Blender snapshots in this room, newest first *(assets)* | yes |
| `GET /v1/rooms/{room_id}/blend-backup/{sha256}` | One Blender snapshot back, byte for byte *(assets)* | yes |
| `GET /v1/rooms/{room_id}/blend-packages` | The Blender scene packages of a room, newest first *(assets)* | yes |
| `GET /v1/rooms/{room_id}/blend-package/{sha256}` | One Blender scene package, byte for byte *(assets)* | yes |
| `GET /v1/rooms/{room_id}/members` | Who is in a room, and with which role *(access)* | yes |
| `PUT /v1/rooms/{room_id}/members/{orcid}` | Give someone a role in a room, or hand the room to a new owner *(access)* | yes |
| `DELETE /v1/rooms/{room_id}/members/{orcid}` | Take a person out of a room *(access)* | yes |
| `PUT /v1/rooms/{room_id}/groups/{group_id}` | Give a team a role in a room *(access)* | yes |
| `DELETE /v1/rooms/{room_id}/groups/{group_id}` | Take a team's role in a room away *(access)* | yes |
| `GET /v1/rooms/{room_id}/study-access` | Who may see the study: visibility and embargo *(access)* | yes |
| `PUT /v1/rooms/{room_id}/study-access` | Change who may see the study *(access)* | yes |
| `GET /v1/groups` | Every group this node knows *(access)* | yes |
| `PUT /v1/groups/{group_id}` | Create a group, or replace one you own *(access)* | yes |
| `DELETE /v1/groups/{group_id}` | Delete a group *(access)* | yes |
| `PUT /v1/groups/{group_id}/members/{orcid}` | Add a person to a group *(access)* | yes |
| `DELETE /v1/groups/{group_id}/members/{orcid}` | Take a person out of a group *(access)* | yes |
| `GET /v1/corpus` | The node's documentation corpus: the slice a study needs *(corpus)* | yes |
| `GET /v1/corpus/neighbourhood` | What made a file, and what it went on to make *(corpus)* | yes |
| `POST /v1/corpus/append` | One documentation act on the node's corpus *(corpus)* | yes |
| `POST /v1/corpus/merge` | Fold a project's file corpus into the node's corpus *(corpus)* | yes |
| `POST /v1/validate` | Check a document's format, and count what it holds *(graph)* | yes |
| `POST /v1/export-ttl` | Export a graph as Linked Data (Turtle) *(graph)* | yes |
| `POST /v1/reproject` | Move coordinates from one reference system to another *(geo)* | yes |
| `GET /v1/resolve-authority` | Look a term up in an authority (a thesaurus, a gazetteer) *(authority)* | yes |
| `POST /v1/resolve-authority` | Look several terms up in an authority at once *(authority)* | yes |
| `GET /v1/iiif-authz` | May the caller of this image request have it? (asked by the image proxy) *(iiif)* | — |
| `GET /v1/rooms/{room_id}/iiif/{target_id}/manifest` | The IIIF manifest of one item of a room *(iiif)* | — |
| `POST /v1/photogrammetry` | Reconstruct a set of photographs into a placed 3D model *(photogrammetry)* | yes |
| `GET /v1/photogrammetry/{job_id}` | How a photogrammetry job is going *(photogrammetry)* | yes |
| `GET /v1/admin/whoami` | Am I an operator of this node? *(node)* | yes |
| `GET /v1/admin/rooms` | Every room on this node (operators) *(node)* | yes |
| `GET /v1/admin/storage` | What the node holds, and what does not line up (operators) *(node)* | yes |
| `DELETE /v1/admin/assets/{ref}` | Remove an asset from the node (operators) *(node)* | yes |
| `GET, HEAD /v1/admin/assets/{ref}` | Download any asset, through no room (operators) *(node)* | yes |
| `GET /v1/admin/assets/orphans` | Assets a room's deletion left with no room (operators) *(node)* | yes |
| `GET /v1/admin/health` | The node's services, and how they are doing (operators) *(node)* | yes |
| `POST /v1/admin/rooms/{room_id}/archive` | Archive any room of the node (operators) *(node)* | yes |

## Where to read more

The long description of each route, on `/docs`, is the reference for what it
does and why. The design of the two reading routes, with the decisions and what
was measured, is `docs/SPEC-REST-LETTURA-STANZA.md`; synchronisation between the
field and the node is `docs/SYNC-FIELD-TO-CLOUD.md`.
