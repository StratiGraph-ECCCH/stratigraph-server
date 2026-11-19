# StratiGraph Server

StratiGraph Server is the node of the Extended Matrix ecosystem: the place
where a study lives as a room, where the people who work on it are known by
their ORCID iD, and where StratiField in the trench, EMStudio on a laptop and
EM-tools in Blender meet the same graph. One node can be a laptop on a dig, a
machine in an institution, or a project's server; it is the same service,
differently addressed.

This manual has two parts, for two ways of meeting a node. They describe the
same rooms, the same roles and the same refusals, from the two sides, and each
page points across when the other side has the answer: from the room's guide
to its REST door, and back.

## Working in a room

You dig, record, draw, check and sign; a room is where your study is, and the
node is not something you should have to think about. This part is how a room
looks from inside: signing in, your rooms, sharing one with your team and
deciding who sees it, who may do what, and what the node has published.

```{toctree}
:maxdepth: 2
:caption: Working in a room

ROOM-GUIDE
ROLES-AND-USERS
CATALOGUE
```

The field node — the node that travels to the excavation, and how it is
prepared before leaving — is in
[StratiField's manual](https://github.com/StratiGraph-ECCCH/stratigraph-stratifield/blob/main/docs/index.md).

## Building and running a node

You install a node, look after it, or write a tool that talks to it. Every page
below shows requests that were really run against a node, with what came back;
the clickable reference of every route is `/docs` on any node.

**Running a node.** Start from the map of the pieces, then from how a node is
switched on — on your computer, or the whole system on a host. For the day a
new node opens — who the first operator is, who may create rooms, what an
invited colleague sees before they have one — read
[the first day of an institutional node](FIRST-DAY.md). The console is where a
node manager spends their days.

**Building a client.** The REST door of a room, the node's own API, the
vocabularies, the snapshots of a Blender file, and the specification of the two
reading routes.

```{toctree}
:maxdepth: 1
:caption: Building and running a node

ARCHITECTURE-SYSTEM
DEPLOYMENT
URL-TOPOLOGY
FIRST-DAY
NODE-CONSOLE
USER-MANAGEMENT
SYNC-FIELD-TO-CLOUD
HERIVERSE-IMMAGINI
REST-API
NODE-ADMIN-API
VOCABULARIES-API
BLEND-BACKUPS
SPEC-REST-LETTURA-STANZA
```
