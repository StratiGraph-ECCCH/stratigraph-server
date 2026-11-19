# The first day of an institutional node

*StratiGraph Server · written for whoever opens a node for an institution and
has to decide, on day one, who comes in and how. Every request and answer on
this page was run against the dev stack on 19 November 2026, between 05:54 and
06:19 UTC, with the server restarted as an institutional node
(`EM_NODE_KIND=institutional`, `EM_ALLOW_TEST_PEOPLE=0`) and everything else as
the dev stack has it. The node's sentences are copied as it said them; where a
JSON answer is shortened, it says so.*

The other pages describe the pieces: who an operator is
([USER-MANAGEMENT.md](USER-MANAGEMENT.md)), what the console's API does
([NODE-ADMIN-API.md](NODE-ADMIN-API.md)), what a deployment sets
([DEPLOYMENT.md](DEPLOYMENT.md), and on OpenShift `deploy/openshift/README.md`).
This page puts them in the order in which a real node meets them, with three
people instead of three letters. Where the order has a hole — a step that today
is done by hand, or that asks somebody to edit a file — the page says so in a
box headed **Today this is done like this**, rather than drawing a smooth road
over it.

## The three people

* **Giulia Marchetti** directs the excavation at Podere Sette for her
  institute. The institute's IT team installs the node and names her, in the
  deployment, as the person who looks after it: she is the **first operator**.
* **Tommaso Riva** is her PhD student. He records the stratigraphic units in
  the field and at the desk. On day one he is a person the node does not yet
  know.
* **Hanna Lindqvist** is a ceramics specialist at another institute. Giulia
  wants her to read the study, not to write in it.

On the dev stack they sign in with three accounts of the development realm:
Giulia is `dev` (iD `0000-0002-1825-0097`, the iD ORCID itself uses in its
documentation), Tommaso is `editor2` (`0000-0003-2222-2221`), Hanna is
`outsider` (`0000-0003-3333-3330`). The two last iDs have a valid check digit
and belong to nobody. That is why, in the answers below, the `name` the token
carries is the realm's (`Dev User`, `Editor Due`, `Outsider Nessuno`) and not
theirs: the node shows the name the identity provider gives it.

`$NODE` is `https://em.localhost:8443/em`; `$GIULIA`, `$TOMMASO` and `$HANNA`
are their tokens (`dev-stack/token.sh --user <account>`).

## 0 · Before anybody signs in: what the deployment decides

Three settings decide the first day, and none of them is in the console:

| setting | on this node | what it means on day one |
|---|---|---|
| `EM_NODE_KIND` | `institutional` | the node refuses test people whatever else says so |
| `EM_OPERATORS` | `0000-0002-1825-0097` | Giulia is an operator because the deployment says so; the alternative is the realm role `em-operator` |
| `EM_CREATE_POLICY` | `editors` (the default) | a person starts as a *user*: creating a room needs the node editor profile (`creator`) or an operator (`super`) |

The node says what it was told:

```bash
curl -s $NODE/v1/health
```

```json
{"ok": true, "service": "stratigraph-server", "version": "1.6.0.dev86",
 "kind": "institutional", "auth": "keycloak",
 "operators": "realm role «em-operator» or 1 allow-listed ORCID(s)",
 "…": "the rest of the health payload (abridged here)"}
```

> **Today this is done like this · the first operator's account.**
> Naming Giulia in `EM_OPERATORS` makes her an operator *once she is in*; it
> does not let her in. The realm the node ships with
> (`dev-stack/keycloak/realm-em-dev.json`) lets a person come in through ORCID
> only if a Keycloak user with **username = the iD** already exists: its
> first-login flow (`em accredited first login`) links an existing user and
> never creates one. Anybody else is stopped by Keycloak with the realm's
> sentence: *«The ORCID iD {0} is not accredited on this node. Ask the node
> manager to add it to the list of accredited iDs, then sign in again.»* (the
> text is the realm's `federatedIdentityUnavailableMessage`; the sign-in itself
> was not repeated today, because the dev stack has no ORCID client
> registered).
>
> For everybody after Giulia the console makes that user (step 3). For Giulia
> nobody can, because nobody is inside yet. Today her user is made **outside
> the node**: either her iD is written in `dev-stack/accredited.yaml` and
> `dev-stack/accredit.sh` is run against the realm, or the realm's
> administrator creates it by hand in Keycloak's admin console (username = the
> iD, attribute `orcid` = the iD). On OpenShift there is no job that runs
> `accredit.sh`: it is the second way.

> **Today this is done like this · the operator on OpenShift.**
> `deploy/openshift/base/configmap.yaml` ships `EM_OPERATORS: ""`, which means
> *only the realm role `em-operator` makes an operator*, and the realm file
> defines no realm role at all (`roles.realm` is empty). A node installed from
> the manifests as they are has **no operator**. One of two things is done by
> hand before day one: an iD written in the overlay's `config.env`
> (`EM_OPERATORS=`), or the role `em-operator` created in Keycloak and given to
> Giulia's user.

> **Today this is done like this · the development accounts.**
> The same realm file carries the dev stack's five accounts — `dev`, `viewer`,
> `editor`, `editor2`, `outsider` — each with its username as its password.
> A realm imported from it (which is what `components/keycloak-nostro` does)
> has them too. On a node that real people use, they are deleted by hand in
> Keycloak's admin console after the import.

## 1 · Giulia's first entry

She signs in and asks the node who she is. The answer is the same question the
house (`/em/home/`) asks before it draws anything:

```bash
curl -s -H "Authorization: Bearer $GIULIA" $NODE/v1/whoami
```

```json
{"orcid": "0000-0002-1825-0097", "name": "Dev User", "enforcing": true,
 "auth_mode": "node_password", "attested_by": "em.localhost:8443",
 "accredited": true, "profile": "super", "may_create": true}
```

`profile: super` comes from the deployment, not from a register: nobody wrote
it anywhere inside the node. (`auth_mode` is `node_password` because on the dev
stack she signed in with the realm's password; through ORCID it reads
`orcid`.) The console's own question gives the same answer from the other side:

```bash
curl -s -H "Authorization: Bearer $GIULIA" $NODE/v1/admin/whoami
```

```json
{"operator": true, "orcid": "0000-0002-1825-0097",
 "capability": "realm role «em-operator» or 1 allow-listed ORCID(s)", "auth": "keycloak"}
```

The node also tells her what an institutional node still lacks. On the dev
stack it has one thing to say, and it is true:

```bash
curl -s -H "Authorization: Bearer $GIULIA" $NODE/v1/admin/node-kind
```

```json
{"kind": "institutional", "declared": true, "word_it": "nodo istituzionale",
 "word_en": "institutional node",
 "checks": [{"level": "warn", "code": "local-name",
   "it": "L'indirizzo https://em.localhost:8443/em non è un nome pubblico in https: dall'esterno non si raggiunge.",
   "en": "The address https://em.localhost:8443/em is not a public https name: it cannot be reached from outside."}]}
```

Two things she cannot do, and the node says why. She cannot add a test person
on this kind of node:

```bash
curl -s -X PUT -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"name": "Prova Uno"}' $NODE/v1/admin/people/0000-0000-0000-001X
```

```json
{"detail": "test iDs (0000-0000-…) are accepted only on a node with test people (EM_ALLOW_TEST_PEOPLE)"}
```

and she cannot change her own profile, or take herself off the node:

```json
{"detail": "your own profile is changed by another super-administrator: the capability to look after a node is never self-granted"}
```

```json
{"detail": "you cannot take yourself off the node"}
```

(`PUT /v1/admin/people/0000-0002-1825-0097` with `{"profile": "user"}` → `403`;
`DELETE /v1/admin/people/0000-0002-1825-0097` → `403`.)

## 2 · Who may create a room on day one

Giulia may, because an operator may. Tommaso, signed in for the first time,
may not — and the node tells him who can change that:

```bash
curl -s -H "Authorization: Bearer $TOMMASO" $NODE/v1/whoami
```

```json
{"orcid": "0000-0003-2222-2221", "name": "Editor Due", "enforcing": true,
 "auth_mode": "node_password", "attested_by": "em.localhost:8443",
 "accredited": true, "profile": "user", "may_create": false}
```

```bash
curl -s -X POST -H "Authorization: Bearer $TOMMASO" -H "Content-Type: application/json" \
  -d '{"room_id": "tommaso-prova", "title": "x"}' $NODE/v1/rooms
```

```json
{"detail": "creating a room needs the node editor profile: on this node a person starts as a user, and somebody who looks after the node gives the editor profile in the console (People). Being given a role in a room is unchanged."}
```

So on day one **only Giulia creates rooms**, unless the deployment set
`EM_CREATE_POLICY=anyone` or gives the realm role `em-creator`.

## 3 · The room, and the student in it

Giulia opens the room for the season:

```bash
curl -s -X POST -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"room_id": "podere-sette-2026", "title": "Podere Sette — Area 2, campagna 2026"}' \
  $NODE/v1/rooms
```

```json
{"room_id": "podere-sette-2026", "title": "Podere Sette — Area 2, campagna 2026",
 "container_refs": ["podere-sette-2026"], "created_by": "0000-0002-1825-0097",
 "created_at": "2026-11-19T05:54:52Z", "implicit": false,
 "owner": "0000-0002-1825-0097", "members": [], "your_role": "owner",
 "missing_refs": ["podere-sette-2026"], "born_with": [], "…": "(abridged)"}
```

She is its owner because she created it. Then she makes Tommaso known to the
node (People → *Add a person*, which is this request) and gives him a role in
the room:

```bash
curl -s -X PUT -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"name": "Tommaso Riva", "profile": "user"}' $NODE/v1/admin/people/0000-0003-2222-2221
curl -s -X PUT -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"role": "editor"}' $NODE/v1/rooms/podere-sette-2026/members/0000-0003-2222-2221
```

```json
{"room": "podere-sette-2026", "owner": "0000-0002-1825-0097",
 "members": [{"orcid": "0000-0003-2222-2221", "role": "editor"}], "groups": [], "your_role": "owner"}
```

The first answer, the person's card, ends with a note that matters on a real
node:

```json
"notes": ["Keycloak: 0000-0003-2222-2221 is already carried by the user «editor2»: one user per ORCID"]
```

That note is the dev realm speaking, not the node failing: the console looks
for the Keycloak user whose **username is the iD**, and the dev realm's seeded
accounts are called `dev`, `editor2`, `outsider`. On a realm where people are
made by the console or by `accredit.sh` the same request answers differently —
measured with a fresh iD, `0000-0003-6666-6668`, standing in for a colleague
who has never been here:

```json
{"orcid": "0000-0003-6666-6668", "name": "Hanna Lindqvist", "profile": "user",
 "profile_source": "register", "registered": true, "rooms": 0,
 "keycloak": {"exists": true, "enabled": true, "orcid_linked": false, "password": false},
 "notes": ["account created in Keycloak"], "…": "(abridged)"}
```

That account is what lets the person through the realm's door the first time
they sign in with ORCID. A field password comes only after that sign-in:

```bash
curl -s -X POST -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"password": "…"}' $NODE/v1/admin/people/0000-0003-6666-6668/password
```

```json
{"detail": "0000-0003-6666-6668 never signed in with ORCID on this node. The node attests only an iD ORCID verified once: the person signs in online with ORCID first, then the password can be given."}
```

and an iD typed wrong is caught by its check digit before anything is made:

```json
{"detail": "'0000-0003-6666-6667' is not an ORCID iD (check digit)"}
```

Tommaso writes the first unit. The author is his token, not anything he could
type:

```bash
curl -s -X POST -H "Authorization: Bearer $TOMMASO" -H "Content-Type: application/json" \
  -d '{"ops": [{"op": "add_node", "id": "US1", "node": {"id": "US1", "node_type": "US",
       "name": "US1", "description": "Strato di humus, bruno scuro, sciolto.", "data": {"lang": "it"}}}]}' \
  $NODE/v1/rooms/podere-sette-2026/ops
```

```json
{"applied": 1, "refused": [], "conflicts": [],
 "kept": {"at": "2026-11-19T05:54:52Z", "oplog": 1, "…": "(abridged)"}}
```

Later in the season Giulia makes him a node editor, so that he can open the
room for his own thesis survey:

```bash
curl -s -X PUT -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"profile": "creator"}' $NODE/v1/admin/people/0000-0003-2222-2221
curl -s -H "Authorization: Bearer $TOMMASO" $NODE/v1/whoami
```

```json
{"orcid": "0000-0003-2222-2221", "profile": "creator", "may_create": true, "…": "(abridged)"}
```

## 4 · The invitation, and what Hanna sees before she has a room

Giulia makes a link that lets one person in as a reader, for a week:

```bash
curl -s -X POST -H "Authorization: Bearer $GIULIA" -H "Content-Type: application/json" \
  -d '{"role": "viewer", "ttl_seconds": 604800, "max_uses": 1}' \
  $NODE/v1/rooms/podere-sette-2026/invites
```

```json
{"token_id": "51412ed823242533", "room_id": "podere-sette-2026", "role": "viewer",
 "state": "live", "created_by": "0000-0002-1825-0097", "created_at": "2026-11-19T05:54:52Z",
 "expires_at": 1795672492, "max_uses": 1, "uses": 0, "revoked_at": null, "accepted_by": [],
 "token": "51412ed823242533.lGqPx…"}
```

(The token is shortened here; the node shows it once and keeps only its
digest.)

> **Today this is done like this · getting the link to Hanna.** The node sends
> no e-mail. Giulia copies the link (the console has a copy button) and sends it
> herself.

> **Today this is done like this · a colleague from outside.** On a realm with
> the node's first-login flow, Hanna cannot sign in at all until her iD has a
> user there (step 0). The link opens a door to the room; it does not open the
> realm. So before the link is any use, an **operator** adds Hanna in People —
> and a room owner who is not an operator cannot, because `/v1/admin/people`
> is the console's. On a realm that creates users at the first ORCID sign-in,
> this step disappears.

Hanna has signed in and has not used the link yet. This is everything the node
tells her, asked one door at a time:

| she asks | the node answers |
|---|---|
| `GET /v1/whoami` | `200` `{"orcid": "0000-0003-3333-3330", "name": "Outsider Nessuno", "enforcing": true, "auth_mode": "node_password", "attested_by": "em.localhost:8443", "accredited": false, "profile": "user", "may_create": false}` |
| `GET /v1/admin/whoami` | `200` `{"operator": false, "orcid": "0000-0003-3333-3330", "capability": "realm role «em-operator» or 1 allow-listed ORCID(s)", "auth": "keycloak"}` |
| `GET /v1/rooms` | `200` `[]` |
| `GET /v1/rooms/podere-sette-2026` | `403` *not a member of this room* |
| `GET /v1/rooms/podere-sette-2026/document` | `403` *not a member of this room* |
| `GET /v1/rooms/podere-sette-2026/members` | `403` *reading the member list needs admin or owner* |
| `GET /v1/rooms/nessuna-stanza-cosi/document` | `404` *no room 'nessuna-stanza-cosi' here* |
| `POST /v1/rooms` | `403` *creating a room needs the node editor profile: on this node a person starts as a user, and somebody who looks after the node gives the editor profile in the console (People). Being given a role in a room is unchanged.* |
| `GET /v1/admin/people` | `403` *this is the node's console, and it needs the OPERATOR capability — the realm role «em-operator», or an entry in EM_OPERATORS. Owning a room does not grant it (and no endpoint here can): ask whoever runs this node. Per-room management lives in the room's own API.* |

So: an empty list, a refusal that names the room she asked for without saying
who is in it, and a sentence that tells her who can change each thing. Her
list of rooms is not a catalogue of the node: a room she has no role in is not
listed, and asking for it by name tells her only that she is not a member.

The house page draws the same answers. Its strings for this state are, in
English, *«Creating a room needs the node editor profile: ask whoever looks
after this node. You can still work in the rooms where you have a role.»*
(`rooms.needsEditor` in `app/node_admin/i18n.js`; the page was not rendered in
a browser for this document, because the house signs in through the realm and
the headless test harness does not).

Then she follows the link:

```bash
curl -s -X POST -H "Authorization: Bearer $HANNA" -H "Content-Type: application/json" \
  -d '{"token": "51412ed823242533.lGqPx…"}' $NODE/v1/join
```

```json
{"room_id": "podere-sette-2026", "title": "Podere Sette — Area 2, campagna 2026",
 "role": "viewer", "already_had": false}
```

The link was for one use, and it says so the second time:

```json
{"detail": "that invitation is used up"}
```

Now `GET /v1/rooms` lists the room with `"your_role": "viewer"`, and the
document opens with `"role": "viewer", "can_write": false` and Tommaso's US1 in
it, signed `created_by: 0000-0003-2222-2221`. If she tries to change it:

```json
{"detail": "writing operations into this room needs editor or above: it changes the graph everybody else is reading"}
```

## 5 · Taking somebody out

There are two different acts, and they are kept apart.

**Out of a room.** At the end of the study Giulia takes Hanna out of
`podere-sette-2026` (`DELETE /v1/rooms/podere-sette-2026/members/0000-0003-3333-3330`):

```json
{"room": "podere-sette-2026", "owner": "0000-0002-1825-0097",
 "members": [{"orcid": "0000-0003-2222-2221", "role": "editor"}], "groups": [], "your_role": "owner"}
```

It takes effect at the next request: Hanna's document, a moment later, is
`403` *not a member of this room*. The access list is read on every request; no
token has to expire for this.

**Off the node.** `DELETE /v1/admin/people/<iD>` takes a person out of the
register, out of every room where they hold a role of their own, out of every
group, and **disables** their Keycloak account (it does not delete it: what
they signed stays signed by their iD). Rooms they *own* are listed and not
touched; such a room needs a new owner (`PUT /v1/admin/rooms/{room_id}/owner`).
With the fresh iD of step 3:

```json
{"orcid": "0000-0003-6666-6668", "removed": true, "rooms_left": [], "rooms_owned": [],
 "groups_left": [], "keycloak": "account disabled", "still_listed": false}
```

Adding the same iD again (`PUT /v1/admin/people/0000-0003-6666-6668`) enabled
the account again: *«Keycloak account up to date»*, `"enabled": true`.

> **Today this is done like this · the dev realm's accounts, and a token
> already issued.** For Hanna's dev-realm account the same request answered
> `"keycloak": "no Keycloak account"` — the console found no user whose
> username is her iD (it is called `outsider`) — so the account was **not**
> disabled, and a token issued to her before the request still answered
> `GET /v1/whoami` with `200` afterwards. Her rooms were already gone, so it
> opened nothing; but on a realm whose usernames are not the iDs, taking a
> person off the node means disabling the account by hand in Keycloak. On any
> realm, an access token already issued lives until it expires (one hour in
> the dev realm, `accessTokenLifespan` 3600); what protects the rooms in the
> meantime is that the access list is read on every request.

The deployment's operator cannot be taken off from the console at all, not
even by another super-administrator. Measured at 06:19 UTC with Tommaso made
`super` for the purpose (and put back to `user` right after):
`DELETE /v1/admin/people/0000-0002-1825-0097` → `409` *this person is an
operator named by the deployment (EM_OPERATORS): they leave the node there, not
in the console*; `PUT` with `{"profile": "user"}` → `409` *this person's
profile is set by the deployment (EM_OPERATORS or a realm role) and is changed
there, not in the console*. The last super-administrator in the register cannot
be removed or demoted either.

## The first day, as a checklist

1. **Deployment:** `EM_NODE_KIND=institutional`; the first operator's iD in
   `EM_OPERATORS`, or the realm role `em-operator` created and given.
2. **Realm, by hand:** the first operator's user (username = iD, attribute
   `orcid` = iD); the five development accounts deleted if the realm came
   from the dev file; an ORCID client registered (`ORCID_CLIENT_ID`,
   `ORCID_CLIENT_SECRET`).
3. **The operator signs in** and checks `GET /v1/admin/node-kind`.
4. **The operator adds the people** who will work (People), with the profile
   each needs: `creator` for whoever opens rooms, `user` for everybody else.
5. **Rooms** are created by the operator or a creator; roles are given in the
   room, directly or by a link.
6. **A colleague from outside** is added in People *before* the link is sent.
7. **Removing** is per room (the owner) or per node (the operator), and on a
   realm whose usernames are not iDs the Keycloak account is disabled by hand.
