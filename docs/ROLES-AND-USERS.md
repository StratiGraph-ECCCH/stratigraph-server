# People, profiles and roles

StratiGraph Server · for whoever looks after a node and for anyone who wants to
know who may do what in a study. The rules on this page are the ones the server
enforces (`app/access.py`, `app/operators.py`, `app/people.py`), and the node
console (`/admin`) is where a node manager applies them.

## Two questions, asked separately

Every request a node receives raises two questions. *Who are you?* is answered
by the identity provider of the node (Keycloak), and the answer is always an
ORCID. *What may you do here?* is answered by the server itself, because it is a
question about a study the server holds and about the people who work on it.

The answer to the second question has two levels:

- a **profile on the node** says what a person may do with the node as a whole:
  create studies, manage people, look after the storage;
- a **role in a room** says what a person may do with one study: read it, write
  it, decide who else comes in.

The two levels are independent. Somebody can be a plain user of the node and the
owner of a room, or look after the whole node and be a reader in a study.

## A person is an ORCID

A node knows a person by their ORCID iD, and by nothing else. The same iD signs
every operation that person writes into a graph, owns the rooms they create and
appears in the member lists of rooms and groups. A name is shown beside it for
convenience; the iD is what the server compares.

**Adding a person.** The node manager adds a person by their ORCID and chooses,
explicitly, the profile they receive on the node. When nothing is chosen the
person is a *user*: creating studies is something a person is given, never
something they find themselves able to do.

**Signing in, with and without a network.** With a connection a person signs in
with ORCID. A node in the field often has no connection, so every person also
receives a **local password** from the node: their ORCID iD as the user name and
a password kept by the node's own Keycloak, which runs on the node and needs no
internet. The node stands as guarantor for that person until the network comes
back. The first password is temporary and is changed at the first sign-in; when
it is forgotten, the node manager sets a new temporary one.

In the node console, **People** does all of it in one place: add a person by
ORCID (the check digit is verified), choose the profile, set or reset the local
password, take somebody off the node. The server creates the Keycloak account
itself when it can reach Keycloak as an administrator (`EM_KC_ADMIN_URL` and
credentials); otherwise `dev-stack/accredit.sh` and
`dev-stack/offline-password.sh` still do it from the node. Every act is written
to the node's log, never with a password in it.

**Many people at once: the list.** The node manager can also write everybody in
one file, the node's list of accredited people (`accredited.yaml` on the
development node, `accredited.field.yaml` on a field node), and restart the
node. At every start the node adds whoever is missing, gives the profile the
list names and creates the teams with their members:

``` yaml
accredited:
  - orcid: 0000-0002-1825-0097
    name: First Manager
    profile: super            # manages the node
  - orcid: 0000-0003-1111-1112
    name: First Editor
    profile: editor           # creates rooms and teams
    groups: [Excavation team, Restoration]
  - orcid: 0000-0003-2222-2221
    name: First Archaeologist
    groups: [Excavation team] # no profile: a user
```

`profile` and `groups` are optional. A person listed **with** a profile gets
that profile at every start: the file wins, because that is where the manager
wrote it. A person listed **without** one keeps the profile given in the
console. A team is created the first time it is named, with the manager as its
owner. The list **never removes anybody**: taking a person off the node, or out
of a team, is done in the console, where it can be seen.

**The rule for passwords.** A local password is given only to an iD that ORCID
verified once on this node — the person signed in online with ORCID at least
once. The node attests only what was verified.

## Profiles on the node

| Profile | What it may do |
|----|----|
| **Super-administrator** | Looks after the node. Adds people by ORCID, chooses their profile, sets and resets their local password, revokes their access. Sees the list of every room on the node, archives and deletes rooms. Looks after the storage: the bucket, the orphan files, the quotas, the health of the services. |
| **Node editor** | Creates rooms, and becomes the owner of each room created. Creates groups, and manages each group created. Otherwise works like a user. |
| **User** | The starting profile. Enters the rooms where somebody gave them a role, or where an invitation link brought them. |

The super-administrator is what the server calls the node **operator**. The
capability comes from the deployment — the realm role `em-operator`, or the
allow-list `EM_OPERATORS` — and from nowhere else: there is no endpoint that
grants it, and nobody can give it to themselves. An empty configuration means
that nobody is an operator.

Creating rooms and groups needs the node editor profile or super-administrator.
A node can keep the older behaviour, where anybody signed in creates, with
`EM_CREATE_POLICY=anyone`. Nobody changes their own profile, and the console
refuses to demote the last super-administrator, so a node is never left without
anybody who can look after it. A profile given by the deployment (`EM_OPERATORS`
or a realm role, `em-operator` or `em-creator`) is shown in the console and
changed only there.

## Roles in a room

A room is where one study is worked on: its Extended Matrix graph, the people
who may enter and their roles. Each room has exactly one live graph, and each
live graph belongs to exactly one room.

| Role | What it may do |
|----|----|
| **Reader** (`viewer`) | Opens the room, reads the graph, sees and downloads its files, reads the conversation. |
| **Editor** (`editor`) | Everything a reader does, and writes: changes the graph, uploads files, keeps snapshots of a Blender working file, writes in the conversation. |
| **Administrator** (`admin`) | Everything an editor does, and manages the people: adds, removes and changes editors and readers, people or groups; creates and revokes invitation links; decides who sees the study (public, restricted, embargo); archives the room and brings it back. |
| **Owner** (`owner`) | One per room. Everything an administrator does, and manages the administrators, hands the room to a new owner, deletes the room. |

**Who manages whom.** The owner may assign any role, including administrator,
and may hand the room over. An administrator manages editors and readers only:
an administrator cannot change an owner or another administrator, which is what
keeps an administrator from promoting themselves. Everybody else manages nobody.
Each refusal comes with a sentence that says which of these rules applied.

**Creating a room.** Whoever creates a room is its owner, written into the
room's access list at once.

## Groups

A **group** is a team: a named list of ORCIDs. A group can hold a role in a room
— reader, editor or administrator, never owner — so a team is given access once,
instead of adding each of its members to every room where they work. A group is
managed by whoever created it.

When a person has a role of their own and one or more roles through groups, the
role that counts is **the highest**. Joining a team therefore never takes a
permission away. Leaving a team takes away only the roles that came through that
team; a role given to the person directly stays.

## Who sees the study

A study is **public** or **restricted**, and the choice belongs to the room's
administrators and owner.

- A **public** study can be read by anyone, including somebody who has not
  signed in: that is what publishing means.
- A **restricted** study is read only by people who have signed in *and* have a
  role in the room. Signing in without a role is not enough.

An **embargo** is a date. Until the date, the study behaves as restricted
whatever its declared visibility; when the date passes, the study goes back to
what it declares. The room and the Catalog follow the same rule, so the list of
published studies and the door of the room always agree.

## Invitations

An administrator or the owner can create an **invitation link** that offers the
role of editor or reader. Three things do three jobs: the link opens the door,
the ORCID says who came in, and the role comes from the link. A link
authenticates nobody, so a link pasted in the wrong chat lets nobody in without
their own sign-in. Links expire, and can be revoked at any time.

## The super-administrator inside a room

Inside a room, the super-administrator counts for the role they hold *in that
room*: an editor there is an editor, an administrator there is an administrator.
Looking after the node gives the right to archive or delete a room, and to see
its files from the storage side for maintenance; it gives no right to change the
graph or the people of a study.

One exception, for a room left without anybody who can manage it — its owner is
no longer on the node and no administrator who is remains: the
super-administrator may hand the room to a new owner (*Lifecycle* in the room's
panel), and the act is written to the node's log. It rescues the room without
entering it.

## Archiving and deleting a room

**Archiving** is the reversible gesture: the room stays readable and citable,
nobody writes in it any more, and it can be brought back. Administrators and the
owner archive; so does the super-administrator, across the node.

**Deleting** is for the owner and for the super-administrator only. The request
must repeat the id of the room, and it is refused while somebody is connected to
the room, since their session would write the document back the moment they
leave.

What a deletion removes:

- the room's record, its members, invitations and group grants;
- its pending uploads and its log of operations;
- its live graph — the em.json document, with **every revision** of it.

What a deletion keeps, and says so in its answer:

- the files: a file no other room cites becomes an **orphan**, listed for the
  super-administrator, who decides whether to remove it;
- the Blender snapshots (their register goes);
- an em.json that another room still names as a reference.

## At a glance

| In a room                                 | Reader | Editor | Admin | Owner | Super-admin |
|-------------------------------------------|--------|--------|-------|-------|-------------|
| Read the graph and the files              | ✓      | ✓      | ✓     | ✓     | by role     |
| Write the graph, upload files             |        | ✓      | ✓     | ✓     | by role     |
| Manage editors and readers, invitations   |        |        | ✓     | ✓     | by role     |
| Decide who sees the study, embargo        |        |        | ✓     | ✓     | by role     |
| Archive the room                          |        |        | ✓     | ✓     | ✓           |
| Manage administrators, hand the room over |        |        |       | ✓     | rescue only |
| Delete the room                           |        |        |       | ✓     | ✓           |

| On the node | User | Node editor | Super-admin |
|----|----|----|----|
| Enter rooms where one has a role | ✓ | ✓ | ✓ |
| Create rooms and groups |  | ✓ | ✓ |
| Add people, choose profiles, set and reset local passwords |  |  | ✓ |
| See every room, the storage, the health of the node |  |  | ✓ |

## People between nodes

A field node often works without a network, so nobody can sign in there with
ORCID for the first time. People therefore travel from the central node to the
field node, and back, in a **signed package** made in the node console
(*Transfers*). Four rules:

- **Passwords never travel.** The receiving node gives each person a new
  temporary field password; no secret, and no hash of one, leaves a node.
- **A package is accepted only from a trusted node.** Each node signs its
  packages with its own key; a node manager puts the other node's public key on
  the trust list once, comparing the fingerprint, while the field node is
  prepared with a network. A package changed after signing, or signed by a
  different key under a trusted name, is refused.
- **Profiles travel as proposals.** The receiving node's manager confirms them
  one by one. A new person arrives as a user; a profile raised on the field
  never becomes valid at the centre by itself.
- **Only the people who are needed travel**: the owners, members and teams of
  the rooms chosen for the trip, plus anybody named by hand.

A person the sending node attests ORCID verified can receive a field password on
the receiving node without signing in with ORCID there first, for as long as the
sending node stays on the trust list. People added on the field arrive at the
centre marked *to verify*.

**Handle with care.** The public part is the mechanism, written on this page;
what makes it safe is a few things each node keeps to itself:

- a **package file** holds names, ORCID iDs and profiles: it is personal data.
  Carry it by hand or over a private channel, never in an open chat, and delete
  it once it has been imported. The same goes for the node's register of people
  and its log;
- the node's **private key** (`node-key.pem`, beside the register of people):
  whoever holds it can sign packages in that node's name. It never leaves the
  node; if it may have, the other nodes take that node off their trust lists and
  a new key is made;
- the **trust list**, the names and addresses of real nodes, and the node's
  **Keycloak administration credentials** are operational information, kept by
  whoever looks after the node.

## Testing with people who do not exist

A development node can hold **test people**: iDs in the range ORCID never issues
(`0000-0000-…`), marked *test* in the console, given a password directly. They
exist only where `EM_ALLOW_TEST_PEOPLE` is on — the dev stack — and never on a
real node. The console's *Test people…* creates several at once.

For the real sign-in flow with fictitious researchers, the dev realm points at
ORCID's sandbox (`sandbox.orcid.org`): register a sandbox client and a few
sandbox accounts, add their iDs on the node, and they sign in with ORCID exactly
as real people do. The steps are in
[`dev-stack/TEST-PEOPLE.md`](../dev-stack/TEST-PEOPLE.md) in the server's
repository.

## The same rules, from the other side

The rules on this page are what a person meets. The same rules as a program
meets them — the routes, the bodies, the refusals word for word — are in
[User management, end to end](USER-MANAGEMENT.md) and
[The node's own API](NODE-ADMIN-API.md); the day they are applied for the first
time on a new node, step by step, is [The first day of an institutional
node](FIRST-DAY.md).
