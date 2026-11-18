# StratiGraph Server

StratiGraph Server is the node of the Extended Matrix ecosystem: the place
where a study lives as a room, where the people who work on it are known by
their ORCID iD, and where StratiField in the trench, EMStudio on a laptop and
EM-tools in Blender meet the same graph. One node can be a laptop on a dig, a
machine in an institution, or a project's server; it is the same service,
differently addressed.

These pages are written for three readers. Two of them have pages already; the
third does not yet, and this door says so rather than pretending otherwise.

## You look after a node

You install it, decide who may use it, keep its storage in order, and are the
one people ask when something does not open. Start from the map of the pieces,
then the deployment; the console is where you will spend your days.

```{toctree}
:maxdepth: 1
:caption: Who looks after a node

ARCHITECTURE-SYSTEM
DEPLOYMENT
URL-TOPOLOGY
NODE-CONSOLE
USER-MANAGEMENT
SYNC-FIELD-TO-CLOUD
HERIVERSE-IMMAGINI
```

## You build a client

You write a tool, a page, a script or an app that talks to a node. Every page
below shows requests that were really run against a node, with what came back.
The clickable reference of every route is `/docs` on any node.

```{toctree}
:maxdepth: 1
:caption: Who builds a client

REST-API
NODE-ADMIN-API
VOCABULARIES-API
BLEND-BACKUPS
SPEC-REST-LETTURA-STANZA
```

## You work in a room

You dig, record, draw, check and sign; a room is where your study is, and the
node is not something you should have to think about. **There is no manual for
you here yet, and it is being written.** It will not live in this repository:
a working day goes through StratiField, EMStudio and the catalogue, and the node
is only the place where they meet, so the manual belongs to the whole
ecosystem rather than to the server. Where exactly it will be published is
still to be decided; when it exists, this section will point to it.
