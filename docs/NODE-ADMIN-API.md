# The node's own API: people, a key, a trash, and trust

*StratiGraph Server · written for whoever builds a client for the node console,
or scripts what the console does. Every request and response on this page was
run against the dev stack on 18 November 2026, between 20:34 and 20:37 UTC, in
two rooms made for it (`admin-2026-11-18` and `scavo-orfano-2026-11-18`) and
with two test people (`0000-0000-0000-0415`, `0000-0000-0000-0423`). Nothing is
written by hand except the abridgements, which say so, and the indentation of
the JSON. For the clickable reference, open `/docs` on any node and look under
the tag **node**.*

## Who may knock on this door

The node console (`/em/home/` on the dev stack) is a web page; everything it shows and
everything it changes goes through the routes on this page. They all live under
`/v1/admin/`, and **every one of them but one wants the operator capability**: the
realm role `em-operator`, or an ORCID iD in `EM_OPERATORS`
(`docs/USER-MANAGEMENT.md`; on OpenShift, `deploy/openshift/README.md`).
Owning a room does not give it, and no route can grant it — not even to the
person asking.

Below, `$TOKEN` is a token of the dev stack's `dev` user, an operator through
`EM_OPERATORS`; `$VIEWER` is a token of `viewer`, an ordinary person. Both come
from `dev-stack/token.sh`. `$NODE` is `https://em.localhost:8443/em`.

**The one question that never refuses.** Before it draws anything, the console
asks whether you are an operator. That question answers `200` for everybody,
because a page that says *«you are not an operator, and this is how one
becomes one»* teaches more than a page that shows an error:

```bash
curl -s -H "Authorization: Bearer $VIEWER" $NODE/v1/admin/whoami
```

```json
{"operator": false, "orcid": "0000-0001-5109-3700",
 "capability": "realm role «em-operator» or 1 allow-listed ORCID(s)", "auth": "keycloak"}
```

**Every other route refuses, and says why.** Without a token it is a `401`;
with a token that is not an operator's it is a `403`, always with the same
sentence — this is what a client should show, rather than retrying:

```bash
curl -s -H "Authorization: Bearer $VIEWER" $NODE/v1/admin/people
```

```json
{"detail": "this is the node's console, and it needs the OPERATOR capability — the realm role «em-operator», or an entry in EM_OPERATORS. Owning a room does not grant it (and no endpoint here can): ask whoever runs this node. Per-room management lives in the room's own API."}
```

The token in that last request belonged, on the night of the test, to a person
who had just created a room and owned it: same `403`.

## What kind of node am I

`GET /v1/admin/node-kind` says what the node was declared to be
(`EM_NODE_KIND`) and what that kind of node still lacks. The checks are advice,
in Italian and English, at three levels (`bad`, `warn`, `info`); the one rule
behind them is that an institutional node refuses test people.

```bash
curl -s -H "Authorization: Bearer $TOKEN" $NODE/v1/admin/node-kind
```

```json
{
  "kind": "field",
  "declared": true,
  "word_it": "nodo da campo",
  "word_en": "field node",
  "checks": [
    {"level": "info", "code": "test-people-on",
     "it": "Le persone di prova sono accese: va bene per le prove, spegnile prima di andare sul campo.",
     "en": "Test people are on: fine for trials, turn them off before going to the field."},
    {"level": "warn", "code": "trusts-nobody",
     "it": "Il nodo da campo non ha ancora nessun nodo di fiducia: aggiungi la chiave del nodo istituzionale (Trasferimenti) prima di partire, finché c'è rete.",
     "en": "The field node trusts no node yet: add the institutional node's key (Transfers) before leaving, while there is a network."}
  ]
}
```

## A node has people

A node knows a person by their **ORCID iD**, and by a profile: `super` (looks
after the node), `creator` (may create rooms), `user`. The list is
`GET /v1/admin/people` — the register, the accredited list, the operators the
deployment names, and everybody who holds a role in a room or a group, each
with where their profile comes from. `?keycloak=true` adds, for each person,
what the identity service knows of them (one more call each).

**Adding someone is putting them by iD.** `PUT /v1/admin/people/{orcid}` adds a
person, or changes their name or profile; a person put without a profile is a
`user`. The answer says what happened in Keycloak too:

```bash
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Prova Quarantuno"}' $NODE/v1/admin/people/0000-0000-0000-0415
```

```json
{
  "orcid": "0000-0000-0000-0415",
  "name": "Prova Quarantuno",
  "profile": "user",
  "profile_source": "register",
  "test": true,
  "registered": true,
  "listed": false,
  "rooms": 0,
  "rooms_owned": [],
  "groups": [],
  "added_by": "0000-0002-1825-0097",
  "added_at": "2026-11-18T20:35:21+00:00",
  "keycloak": {"exists": true, "enabled": true, "orcid_linked": false, "password": false},
  "notes": ["account created in Keycloak"]
}
```

The same request again with `"profile": "creator"` changes the profile and
answers with the same shape (`"notes": ["Keycloak account up to date"]`).

What it refuses, each with its sentence: an iD whose check digit is wrong; a
test iD (`0000-0000-…`, the range ORCID never issues) on a node that does not
allow test people; the last super-administrator demoted (`409`); a profile the
deployment fixes, through `EM_OPERATORS` or a realm role (`409`); and a change
to **your own** profile:

```bash
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"profile": "user"}' $NODE/v1/admin/people/0000-0002-1825-0097
```

```json
{"detail": "your own profile is changed by another super-administrator: the capability to look after a node is never self-granted"}
```

**A password for the field.** `POST /v1/admin/people/{orcid}/password` gives a
person the password they sign in with when there is no network, and the node
attests who they are. Only for an iD that ORCID verified once on this node — or
that a trusted node says ORCID verified (see below) — or a test person on a node
that allows them. The password is temporary unless `"temporary": false`, never
logged and never returned:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"password": "trincea-nord-41", "temporary": true}' \
  $NODE/v1/admin/people/0000-0000-0000-0415/password
```

```json
{"orcid": "0000-0000-0000-0415", "password": "set", "temporary": true}
```

A password shorter than eight characters is a `400`
(`"a password of at least 8 characters"`); a person with no account on the
node is a `404`; an iD never verified is a `409` that says what to do first;
and when the server cannot reach Keycloak's admin API the answer is `503` and
names `dev-stack/offline-password.sh`.

**Taking someone off.** `DELETE /v1/admin/people/{orcid}` takes the person out
of the register, of every room where they hold a role of their own, of every
group, and **disables** their Keycloak account (it does not delete it: what
they signed stays signed by their iD). Rooms they *own* are not touched — they
are listed, because such a room now needs a new owner. Here a test person who
had created a room on their own is taken off:

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $NODE/v1/admin/people/0000-0000-0000-0423
```

```json
{"orcid": "0000-0000-0000-0423", "removed": true, "rooms_left": [],
 "rooms_owned": ["scavo-orfano-2026-11-18"], "groups_left": [],
 "keycloak": "account disabled", "still_listed": false}
```

You cannot take yourself off, nor an operator the deployment names, nor the
last super-administrator.

## The one time the node steps into a room

Inside a room, the node's operator counts only for the role they hold there.
There is one exception: a room left with **nobody who can manage it** — its
owner is no longer on the node, and no administrator of the room is.
`PUT /v1/admin/rooms/{room_id}/owner` hands such a room to a new owner, and
the act goes to the node's log. On the room the person above left behind:

```bash
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"orcid": "0000-0002-1825-0097"}' \
  $NODE/v1/admin/rooms/scavo-orfano-2026-11-18/owner
```

```json
{"room": "scavo-orfano-2026-11-18", "owner": "0000-0002-1825-0097",
 "members": [], "groups": [], "your_role": "owner"}
```

On a room that still has somebody who can manage it, the node does not step in:

```json
{"detail": "this room still has somebody who can manage it (0000-0002-1825-0097): they hand it over from the room. The node steps in only when nobody can."}
```

## What the console did, and who did it

`GET /v1/admin/log?limit=N` (1 to 1000, default 100) is the node's log, oldest
first: people added, changed and taken off, passwords set (never the
password), trust given and withdrawn, packages exported and imported, rooms
rescued. The last two lines after the rescue above:

```json
[
  {"at": "2026-11-18T20:36:05+00:00", "kind": "person.remove", "by": "0000-0002-1825-0097",
   "orcid": "0000-0000-0000-0423", "rooms": [], "groups": []},
  {"at": "2026-11-18T20:36:05+00:00", "kind": "room.rescue", "by": "0000-0002-1825-0097",
   "room": "scavo-orfano-2026-11-18", "previous": "0000-0000-0000-0423",
   "owner": "0000-0002-1825-0097"}
]
```

## A node has a key, and trusts other nodes by name

People move between nodes — a field node goes out with the people of a dig, and
comes back. They travel as a **signed package**, and a node accepts a package
only from a node on its **trust list**: an explicit list of names, each with an
Ed25519 public key. Nothing is trusted by default; nothing is trusted by being
reachable.

**This node's key**, to give to the other node's operator:

```bash
curl -s -H "Authorization: Bearer $TOKEN" $NODE/v1/admin/node-key
```

```json
{"node": "em.localhost:8443", "public_key": "lU4HJvVretoyFHAM6bYN0c/+PLzH59bts91sTtAup6Q=",
 "fingerprint": "26:47:b4:5f:c3:49:7e:96:fc:08:4a:04"}
```

The fingerprint is there to be read aloud on the phone: the two operators
compare twelve bytes, not forty-four characters.

**Trusting a node** is `PUT /v1/admin/trusted-nodes/{name}` with its key; the
name must be the one its packages say they come from (`from`). **The list** is
`GET /v1/admin/trusted-nodes`, **forgetting one** is
`DELETE /v1/admin/trusted-nodes/{name}`. The dev stack has one node, so on the
night of the test it was told to trust *itself*, under its own name — the only
way to run a whole round trip on one machine; between two real nodes the key
comes from the other one.

```bash
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"public_key": "lU4HJvVretoyFHAM6bYN0c/+PLzH59bts91sTtAup6Q="}' \
  "$NODE/v1/admin/trusted-nodes/em.localhost:8443"
```

```json
{"public_key": "lU4HJvVretoyFHAM6bYN0c/+PLzH59bts91sTtAup6Q=",
 "fingerprint": "26:47:b4:5f:c3:49:7e:96:fc:08:4a:04",
 "added_by": "0000-0002-1825-0097", "added_at": "2026-11-18T20:35:38+00:00"}
```

`GET /v1/admin/trusted-nodes` then answers with an object keyed by name, each
entry the same four fields. A key that is not one is a `400`
(`"not an Ed25519 public key (base64, 32 bytes)"`). Forgetting answers
`{"node": "em.localhost:8443", "removed": true}`, and `"removed": false` the
second time — not an error.

## A package of people: export, preview, import

**Export** — `POST /v1/admin/people-transfer/export` with the rooms (and,
optionally, other iDs) whose people should travel. The package holds the
owners, members and team members of those rooms, and for each person: iD,
name, the profile *proposed*, whether this node attests that ORCID verified the
iD, the groups. **No password, no token.** It is signed with the node's key.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"rooms": ["admin-2026-11-18"], "people": []}' \
  $NODE/v1/admin/people-transfer/export > package.json
```

```json
{
  "format": "em-people-transfer",
  "version": 1,
  "from": "em.localhost:8443",
  "made_at": "2026-11-18T20:35:30+00:00",
  "made_by": "0000-0002-1825-0097",
  "rooms": ["admin-2026-11-18"],
  "people": [
    {"orcid": "0000-0000-0000-0415", "name": "Prova Quarantuno", "profile": "creator",
     "verified": false, "test": true, "groups": []},
    {"orcid": "0000-0002-1825-0097", "name": "Dev User", "profile": "super",
     "verified": false, "test": false, "groups": []}
  ],
  "groups": [],
  "public_key": "lU4HJvVretoyFHAM6bYN0c/+PLzH59bts91sTtAup6Q=",
  "signature": "2sfGhBF4BU03wEdLi4hI+zk1s1FiS1F8B85OXaxQsiyrWjqWK5KcluN1PJAyEeEXjRIEW6EIO2LGZ4yepwsuAA=="
}
```

**Preview** — `POST /v1/admin/people-transfer/preview` with the package as the
body. **It changes nothing.** It says whether the package is trusted and, if
not, why; and for each person the profile proposed beside the one they have
here today (`current`, `null` for someone new), and why an iD could not come
in (`refused`). Before the sending node was on the trust list:

```json
{
  "trusted": false,
  "why": "the node «em.localhost:8443» is not on this node's trust list: add its public key (fingerprint 26:47:b4:5f:c3:49:7e:96:fc:08:4a:04) first",
  "sender": "em.localhost:8443",
  "fingerprint": "26:47:b4:5f:c3:49:7e:96:fc:08:4a:04",
  "made_at": "2026-11-18T20:35:30+00:00",
  "made_by": "0000-0002-1825-0097",
  "rooms": ["admin-2026-11-18"],
  "people": [
    {"orcid": "0000-0000-0000-0415", "name": "Prova Quarantuno", "proposed": "creator",
     "current": "creator", "verified": false, "test": true, "groups": [], "refused": null},
    {"orcid": "0000-0002-1825-0097", "name": "Dev User", "proposed": "super",
     "current": "super", "verified": false, "test": false, "groups": [], "refused": null}
  ],
  "groups": []
}
```

After trusting it, the same preview says `"trusted": true, "why": ""`. And with
the package changed by hand after signing — one proposed profile raised to
`super` — the preview still shows the content, but refuses it:

```json
{"trusted": false,
 "why": "the signature does not match the content: the package was changed after it was signed",
 "…": "the rest as above, with \"proposed\": \"super\" for 0000-0000-0000-0415 (abridged here)"}
```

**Import** — `POST /v1/admin/people-transfer/import` with
`{"package": …, "include": [iDs], "accept_profiles": [iDs]}`. An untrusted
package is a `409` with the same `why` as the preview. `include` chooses who
comes in (absent: everybody); a proposed profile is applied only to the iDs in
`accept_profiles` — everybody else keeps the profile they have here, and a new
person arrives as a `user`. Passwords never travel: each person gets a new one
on this node. A person the sender attests ORCID verified can receive a field
password here without signing in with ORCID first; the others are listed in
`to_verify`.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"package\": $(cat package.json), \"include\": [\"0000-0000-0000-0415\"], \"accept_profiles\": []}" \
  $NODE/v1/admin/people-transfer/import
```

```json
{"added": [], "updated": ["0000-0000-0000-0415"], "profiles_applied": [],
 "to_verify": ["0000-0000-0000-0415"], "groups_created": [],
 "groups_already_here": [], "notes": []}
```

## A node has a trash

Nothing the console removes goes away at once. A room or a file goes into the
**trash** first, stays there thirty days, and only then does the node empty it
by itself — the only deletion the node ever makes on its own. Removing for good
before then is a second, explicit gesture.

**What is in it** — `GET /v1/admin/trash`: the rooms and the files, each with
`purge_after`, the thresholds above which an operation in bulk asks for an
explicit confirmation (`bulk_rooms`, `bulk_bytes`), and the days:

```json
{
  "days": 30,
  "rooms": [
    {"room_id": "scavo-orfano-2026-11-18", "title": "Scavo rimasto senza nessuno",
     "trashed_at": "2026-11-18T20:36:19Z", "trashed_by": "0000-0002-1825-0097",
     "purge_after": "2026-12-18T20:36:19Z", "owner": "0000-0002-1825-0097",
     "…": "the rest of the room's description (abridged here)"},
    "… fourteen more rooms, trashed earlier on the dev stack (abridged here)"
  ],
  "assets": [],
  "bulk_rooms": 20,
  "bulk_bytes": 5368709120
}
```

A room goes in with `DELETE /v1/rooms/{room_id}` and comes out with
`POST /v1/rooms/{room_id}/restore` — both room routes, in `docs/REST-API.md`.

**The files.** `GET /v1/admin/assets` lists every file the node holds — size,
the rooms whose documents cite it, its home room, who brought it in, and a
`state`: `in_use`, `orphan` (no room cites it), `trash`, `missing` (cited but
not in the store). Filters: `state`, `room`, `by` (an uploader's iD), `limit`.
A 57-byte note uploaded into a room but not yet cited by its graph:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$NODE/v1/admin/assets?room=scavo-orfano-2026-11-18"
```

```json
{"assets": [{"ref": "sha256:4308470d5962ef571532407133917510eeec0c3625d33e5da8908697548ee1a6",
             "size": 57, "rooms": [], "home": "scavo-orfano-2026-11-18",
             "uploaded_by": ["0000-0002-1825-0097"], "state": "orphan"}],
 "matched": 1, "bytes": 57, "truncated": false, "listed_from": "bucket listing (em-assets)"}
```

`DELETE /v1/admin/assets/{ref}` puts it in the trash. It refuses (`409`, with
the list of rooms) while any room or the resident corpus still points at the
bytes: an asset is addressed by its content, and removing it for one record
would take it from all of them.

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  $NODE/v1/admin/assets/sha256:4308470d5962ef571532407133917510eeec0c3625d33e5da8908697548ee1a6
```

```json
{"ref": "sha256:4308470d5962ef571532407133917510eeec0c3625d33e5da8908697548ee1a6",
 "removed": false, "rooms": [], "corpus": false, "in_trash": true,
 "purge_after": "2026-12-18T20:36:16Z"}
```

From there, `?for_good=true` on the same `DELETE` removes the bytes; and
`POST /v1/admin/assets/{ref}/restore` takes them back:

```json
{"ref": "sha256:4308470d5962ef571532407133917510eeec0c3625d33e5da8908697548ee1a6",
 "removed": false, "rooms": [], "corpus": false, "in_trash": false, "purge_after": null}
```

Asked again, it is a `404`: `"no asset 'sha256:…' in the trash here"` (the
digest abridged here). Over 5 GB in an hour, removing asks for `?bulk=true`.

## The rest of the console's routes

These were already described in `docs/REST-API.md` and `docs/NODE-CONSOLE.md`;
they are listed here so the console's whole API is on one page.

| endpoint | what it does |
|---|---|
| `GET /v1/admin/whoami` | Am I an operator? — `200` for everybody |
| `GET /v1/admin/rooms` | Every room on the node, declared or not, archived or not |
| `POST /v1/admin/rooms/{room_id}/archive` | Archive any room of the node |
| `GET /v1/admin/storage` | What the node holds, and what does not line up |
| `GET /v1/admin/assets/orphans` | Assets a room's deletion left with no room |
| `GET, HEAD /v1/admin/assets/{ref}` | Download any asset, through no room |
| `GET /v1/admin/health` | The node's services, and how they are doing |

## Where to read more

The console as a person sees it is `docs/NODE-CONSOLE.md`; profiles, roles and
the rules about people, and `EM_OPERATORS`, are `docs/USER-MANAGEMENT.md`;
testing with people who do not exist is `dev-stack/TEST-PEOPLE.md`.
`EM_NODE_KIND` and `EM_ALLOW_TEST_PEOPLE` are in `docs/DEPLOYMENT.md`.
