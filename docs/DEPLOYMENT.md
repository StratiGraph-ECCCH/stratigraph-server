# Running a node

A node is switched on in one of two places, and this page tells both: **on your
computer**, from the `dev-stack` folder of this repository — the development
node, and the same scripts that prepare a field node — and **on a host**, the
whole system behind one name, with the playbook. The two roads a node's
services come by (built from the code, or downloaded as published images) are
told once, in the first half, because they belong to the scripts that switch a
node on and not to the place it runs.

## On your computer — the development node

StratiGraph Server · the development node, for whoever runs a node on a laptop
to work, to test tools against it, or to show it. The field node on a Raspberry
Pi is the same software set up for the excavation: see
[the field node](https://github.com/StratiGraph-ECCCH/stratigraph-stratifield/blob/main/docs/FIELD-NODE.md), in
StratiField's manual. Everything about the stack beyond switching it on — the
prerequisites per platform, the trust of the certificate, the history of each
choice — is in [`dev-stack/README-DEV.md`](../dev-stack/README-DEV.md).

### What is running

The node is a set of programs, each in its own Docker container, started
together by one script. On a Mac they run inside Colima, the small virtual
machine that gives macOS a Docker. One node, one set of containers:

| Container | What it is |
|----|----|
| `em-dev-caddy` | The front door: https on port 8443, with the node's own certificate. |
| `em-dev-keycloak` | Who you are: sign-in with ORCID or with the node's password. |
| `em-dev-server` | The rooms: the live graphs, the relay of every change, the console. |
| `em-dev-chatbot` | StratiField, the field assistant for the phone. |
| `em-dev-catalog` | The catalogue of published studies. |
| `em-dev-cantaloupe`, `em-dev-rustfs`, `em-dev-postgres` | Images (IIIF), the file store (the bucket), the database. |

Once started, the containers come back by themselves until you switch them off.
To see what is on:

    docker ps

The same node answers at three addresses, and they are not three nodes:

- `https://em.localhost:8443` — from this computer only;
- `https://<host>:8443` — from the other devices on the same network (see
  below);
- `http://localhost:8000` — the rooms server reached directly, without the front
  door; tools use it when they run on the same computer.

### Switching it on and off

All the commands are run from the `dev-stack` folder of the server:

    cd ~/Documents/GitHub/stratigraph-server/dev-stack

| Command | What it does |
|----|----|
| `./fcn-up.sh` | Switches the node on. The first time it builds the images (some minutes); after that it reuses them. |
| `./fcn-up.sh --offline` | Switches it on without building and without the EMStudio development server: two or three minutes, no network needed. The usual way after a restart. |
| `./fcn-up.sh 192.168.1.214` | Switches it on for the other devices of the network, at that address. The address is remembered: the next times `./fcn-up.sh --offline` is enough. |
| `./fcn-up.sh --demo` | Also fills it with demonstration studies, rooms and images. |
| `./fcn-down.sh` | Switches it off. Studies, rooms, files and accounts stay. |
| `./fcn-down.sh --colima` | Switches it off and frees the Mac's memory too. |
| `./fcn-down.sh --wipe` | Switches it off and **deletes everything**: studies, rooms, files, accounts and the certificate. Only for a fresh start. |

Every script explains itself, with examples:

    ./fcn-up.sh --help
    ./fcn-down.sh --help

```{warning}
**After every restart, sign in again.** On the development node the sign-in
service keeps its sessions inside its container, so they do not survive a
restart. A browser shows the sign-in page again; EMStudio shows *connection
lost* and retries forever — in its panel of the node, choose *Sign in as
another user*. StratiField on the phone asks for the signature again. The
field node keeps the sessions on disk and does not have this problem.
```

### From the code, or from the published images

The node can be started by two roads, and both are kept:

|  | **source** — for whoever writes the code | **images** — for a node that only has to run |
|----|----|----|
| Where the services come from | Built on this computer from the repositories side by side (`stratigraph-chatbot`, `stratigraph-catalog`, `EMStudio`…); a change to the code shows without rebuilding. | Downloaded ready-made from `ghcr.io/stratigraph-eccch`, for Intel and ARM machines alike (a Raspberry Pi 5 included). Nothing is built, and only `stratigraph-server` needs to be on the computer. |
| Compose files | `docker-compose.dev.yml` | `docker-compose.dev.yml` + `docker-compose.images.yml` |
| Forms (schede), EMStudio reader | From the checkouts beside it: `stratigraph-templates/templates` mounted as a development override, `EMStudio/frontend/dist` mounted. | Inside the images: the compiled schede vendored in the StratiField image, the reader built into the catalogue image (`/srv/em-reader-dist`). |
| s3Dgraphy | The version pinned once in `docker-compose.dev.yml` (the anchor `x-s3dgraphy-version`), or your own checkout with `--local-s3d`. | The wheel inside each image, the same version as the anchor. |
| EMStudio dev server (`/em/studio/`) | Started on the host if the checkout has `node_modules`. | Off (`--studio` still forces it if a checkout is there). |
| Docker Compose | Any version 2. | 2.24.4 or newer (`!override`): the scripts check it and say so. |

**Use `source`** when you are changing code in any of the repositories — the
whole point is that an edit shows without rebuilding an image. **Use `images`**
for a node that only has to *run*: the field node (`EM_NODE_KIND=field`, first
target a Raspberry Pi 5 8 GB on Raspberry Pi OS 64-bit), a demo machine, and
tomorrow the institutional node. The overlay knows nothing about hardware or
node kind.

The field node goes by images; every other node by source. To choose by hand,
add `--images` or `--source` to `./fcn-install.sh` and `./fcn-up.sh`, or write
`EM_NODE_ROAD=images` (or `source`) in `dev-stack/.env.dev`.

On the images road, `./fcn-install.sh` downloads the images as its last step —
do it at home, with the network — and `./fcn-up.sh` downloads them again (only
what changed) before switching on; `./fcn-up.sh --offline` starts with what the
computer already has. If the download fails the script says the likely reason:
no network, a version not yet published, or an image not made for this kind of
processor. The versions are written in one place,
`dev-stack/docker-compose.images.yml`: its three `image:` lines, never `latest`.
Raising one is editing that line. Each tag exists on GHCR only after the
`immagine` workflow of its repository has run (it publishes `1.6.0-dev.N` from
`version = "1.6.0.devN"` in `pyproject.toml`).

`tests/test_la_strada_delle_immagini.py` holds the road to its promise: no
service with `build:`, no `../` mount, every data volume still in place, every
tag explicit. *Decided by E.D. on 1 November 2026: both roads stay alive.*

### Reaching it from the phone

The phone must be on the same Wi-Fi as the computer, and it must trust the
node's certificate once (the certificate file is created by `fcn-up.sh`; on an
iPhone, open it, install the profile, then enable it in *Settings → General →
About → Certificate Trust Settings*).

The computer is reached by **name** (`my-mac.local`) or by **address**
(`192.168.1.214`). The name is nicer and survives a change of address, but many
home and office routers do not let these names through: Safari then says it
*cannot find the server* even though the computer answers. In that case use the
address:

    ./fcn-up.sh 192.168.1.214

and ask the router to always give the computer the same address (usually called
*DHCP reservation* or *static lease*). Find the address with
`ipconfig getifaddr en0` on a Mac, `hostname -I` on Linux.

The quickest way onto the phone is the **QR code** of a room: in *Your rooms*,
the *On the phone* button of each room shows it. Frame it with the phone's
camera and StratiField opens in that room.

On the Mac itself, keep using `em.localhost` in EMStudio. Recent versions of
macOS ask an app for permission before it contacts an address of the local
network (*System Settings → Privacy & Security → Local Network*), and EMStudio
may not have it yet; `em.localhost` stays inside the computer and does not need
it.

### Cleaning up rooms

The node's address opens its door and, after signing in, its house. For an
operator the house has, under *Your rooms* and *Tools*, the sections of the
node: *Rooms*, *People*, *Groups*, *Permissions*, *Transfers*, *Memory and
bucket*, *Trash*, *Node health*. Rooms are cleaned up in *Rooms*.

- The chips on top filter the list: *Active*, *Archived*, *Implicit*. Implicit
  rooms are those nobody declared — usually the automatic tests made them. A
  banner offers to delete them all at once.
- Tick the rooms on the left (the box in the header ticks all the listed ones).
  A bar appears with what can be done to all of them together: *Archive*,
  *Restore*, *Into the trash…*. The choice survives a change of filter.
- Removing puts the rooms in the **trash** for 30 days. A room in the trash no
  longer opens and leaves every list, but nothing of it is touched: its owner or
  the operator takes it back, as it was, from *Trash*. After 30 days the node
  deletes it with its em.json, its revisions, its members and its invitations;
  its files stay in the bucket and become orphans if no other room cites them.
  *Delete now…* in *Trash* does the same at once, after you type the room's
  name.
- Orphan files go through the same trash, from *Memory and bucket*.
- **Operations in bulk.** Over 20 rooms, or 5 GB of files, removed by the same
  person within an hour, the node asks for one more confirmation: the console
  makes you type *IN BULK* and the number. The node counts, not the page, so the
  threshold holds for a script too.
- Archiving deletes nothing: the room stays readable and can be restored.

Clicking a row opens the room on the right, with its people, invitations,
visibility, memory and lifecycle.

### When something does not answer

| What you see | What to do |
|----|----|
| The phone says *node absent*, Safari *cannot find the server* | The name `.local` does not get through the router: switch the node on at the address (above). |
| EMStudio: *connection lost — retry* | The node was restarted: *Sign in as another user* on that node. |
| EMStudio: *does not answer* for an address like `192.168.…` | Probably the *Local Network* permission of macOS. On the same Mac, use `em.localhost:8443`. |
| Sign-in fails with *Invalid parameter: redirect_uri* | The page was opened at an address the node was not started for. Use the address shown at the end of `./fcn-up.sh`, or restart it with yours. |
| Nothing answers at all | `docker ps`: if the list is empty, `./fcn-up.sh --offline`. |

---

## On a host — the whole system

*One playbook, one host, everything behind TLS. This half says what you need
before you start, what the single command does, and what to check afterwards.*

The map of the pieces is [`ARCHITECTURE-SYSTEM.md`](ARCHITECTURE-SYSTEM.md);
this is the operational half. The playbook itself lives in the
[`heriverse-ansible`](https://github.com/StratiGraph-ECCCH/heriverse-ansible) repository.

> **The object store is RustFS** (`rustfs/rustfs:1.0.2`, pinned with its
> digest), in this role as on the dev stack. StratiGraph Server and the two
> sibling services talk to it with `boto3` and read only `EM_ASSET_S3_*`.

---

### What comes up

Nine containers behind one Caddy, which terminates TLS and routes by path:

| public route | container | what it serves |
|---|---|---|
| `/` | heriverse | the 3D front end |
| `/server/*` | heriverse-server | Heriverse's own API |
| `/auth/*` | keycloak | identity — one realm for everything |
| `/couchdb/*` | couchdb | documents (Heriverse's scenes, and the Catalog's index) |
| `/em/*` | **StratiGraph Server** | rooms: the live graph, its assets, the WebSocket |
| `/catalog/*` | **StratiGraph Catalog** | the studies as published: search, HDT view, "open in…" |
| `/iiif/*` | cantaloupe | the IIIF Image API, straight out of the bucket |
| `/assets/*` | rustfs | the object store's own S3 API |

Caddy obtains and renews the certificate itself. That single origin is not
cosmetic: it is what removes mixed-content errors, and it is what makes a token
in a query string defensible for a viewer that cannot set a header.

---

### Prerequisites — the part that is ops, and is yours

1. **A host.** Linux, Docker installed (the role does not install it), enough
   disk for the object store. This is where the studies will live.
2. **A domain pointing at it.** Caddy needs a name it can prove, over ports 80
   and 443. Without a real name there is no public certificate, and everything
   below still works but only over an internal CA nobody trusts.
3. **The images.** `StratiGraph Server` and `StratiGraph Catalog` are built from the `Dockerfile`
   in each repo and pushed to the registry the defaults name
   (`git.3dresearch.it:5050/stratigraph/…`). Change `em_server_image` /
   `em_catalog_image` if they live somewhere else.
4. **The secrets, from outside the repository.** RustFS's keys
   (`rustfs_access_key` / `rustfs_secret_key`) and CouchDB's. There are **no defaults** for them, deliberately: a default
   password is the same password on every deployment. Put them in the inventory,
   in an Ansible Vault file, or in the environment.

> Verified: rendering the compose template **without** the CouchDB credentials
> fails at that task with `'couchdb_user' is undefined`. That is the intended
> behaviour — the alternative is a catalogue that comes up with a password
> somebody could read in a git history.

---

### Two shapes, and the certificate tells them apart

Everything above describes one host with a public name. There are two deployments
in front of us and only one of them looks like that. The difference is not the
services — those are the same — it is how the origin gets a certificate, and that
decides what has to be true about the network.

#### The node says which kind it is — `EM_NODE_KIND`

Same server everywhere; the node **declares** its kind and is held to that
kind's safe defaults (`app/node_kind.py`):

| `EM_NODE_KIND` | what it is | what the server does with it |
|---|---|---|
| `institutional` | an institution's node, public name, ORCID sign-in | **refuses test people** even if `EM_ALLOW_TEST_PEOPLE` is on; warns when the public name is local or not https, or Keycloak cannot be managed from the server |
| `field` | the Field Computing Node, often offline | warns while the trust list is empty (the team cannot arrive) and while test people are on |
| `personal` | one person's computer (also `EM_NODE_PROFILE=personal`) | nothing to manage |
| *(unset)* | `node` | works as before; the console asks to declare the kind |

The kind shows in `/v1/node`, `/v1/health`, the console's bar and its *Node
health* panel (`GET /v1/admin/node-kind` lists what is missing, in sentences).
The dev stack declares itself `field`.

#### The institutional node — a public name

The templates already assume this shape: `Caddyfile.j2` opens with
`{{ server_name }} {` and carries **no `tls` directive**, so Caddy obtains and
renews the certificate by itself over ports 80 and 443. Nothing is handed to it.

"We already have certificates" is usually the wrong shape of answer, because a
host is one of three things and only the first works as the templates stand:

1. **Caddy is the front door.** Public A record, 80 and 443 reachable from the
   internet. ACME does the rest, including renewal. This is today's default.
2. **The institution terminates TLS** on its own reverse proxy and forwards to
   us. Then Caddy must **not** attempt ACME — it would fail and keep retrying —
   the site block has to be plain `http://`, and the proxy has to forward the
   headers the services read. A small change to the template, but not an
   automatic one.
3. **Certificates handed over as files.** `tls /path/fullchain.pem /path/key.pem`
   — and somebody owns the renewal, which is the half that is forgotten and then
   expires on a Sunday.

Two institutional nodes are **two deployments**, not one with two names: the
realm, the bucket, the studies and the audience are per-instance, and a handoff
link names the host it was asked from — so a study opened from one node points at
that node. That is correct behaviour, and not something to paper over with a
shared name.

#### The Field Computing Node — a local network, no public reachability

The prerequisite above says that without a real name everything still works "but
only over an internal CA nobody trusts". On an FCN that sentence understates the
cost, because of what a browser withholds from a page it does not consider a
secure context: **camera, microphone and geolocation**. The field assistant is
exactly those three. So on a node in a trench, TLS that browsers trust is not
polish — it is the feature.

Three ways, in the order worth trying:

1. **A real subdomain resolved to a private address, with a DNS-01 certificate.**
   `fcn.<domain>` → `192.168.x.x`, and Caddy proves the name by writing a TXT
   record instead of by being reachable. The result is a publicly trusted
   certificate on a network with no inbound path, and **nothing to install on any
   phone**. The cost is real and worth stating: the stock `caddy:2-alpine` image
   has no DNS providers compiled in, so this needs a Caddy built with the
   provider plugin and an API credential for the zone. This is the one to aim
   for.

   **Two things that are easy to get wrong here, because they concern different
   moments.** *Issuing* the certificate needs the node to reach the internet
   outbound — to Let's Encrypt and to the DNS provider's API — for a few seconds;
   it needs no inbound path, no public address and no open port. *Using* it needs
   nothing at all: a certificate is a signed file with a date on it, and a browser
   checks the signature and the clock, never the internet. So the node is issued
   or renewed wherever it has connectivity — at base, on a phone hotspot, the
   evening before leaving — and then works for the rest of its ~90 days on a
   network with no uplink whatsoever. Plan the renewal before a campaign, not
   during one.

   The second is **name resolution in the field**, and it bites at use time
   rather than at issue time. The `A` record is public and points at a private
   address, which is legitimate and common; but a phone on a trench network with
   no uplink cannot ask a public resolver anything. So the field router (or the
   node itself) has to answer for that name locally — a DNS override on the
   access point mapping `fcn.<domain>` to the node's LAN address. Without it the
   certificate is perfect and nobody can reach the name it certifies. Note also
   that some resolvers refuse to return private addresses for public names
   ("DNS rebinding protection"); the local override sidesteps that too.
2. **The internal CA, trusted per device** (`tls internal` — what the dev stack
   does). Free, and it works, but every phone that will record anything has to
   install *and* trust that CA. On iOS those are two separate steps in two
   different settings screens, once per device — to be done before leaving for
   the site, not in a trench with no signal.
3. **Plain HTTP.** Not an option here. It is the configuration in which the
   assistant quietly loses the three permissions it exists for, and says nothing
   about it.

There is no fourth way. A certificate that browsers trust is one signed by a CA
they already carry, and no public CA signs anything without some contact with the
internet at some point. Either the node touches the network occasionally (1), or
the trust is installed by hand on each device (2).

The field assistant is **not in the playbook yet**: `heriverse-ansible` carries
the other nine services and not this one. When it lands its route is `/chat/*`,
under the same rule as everything else on this page — one origin, one
certificate.

---

### The command

```bash
ansible-playbook -i <inventory> playbook/heriverse.yml
```

It creates the service user, clones the Heriverse compose repository, writes the
**rendered** `docker-compose.yml` and `Caddyfile` over the ones in it, brings the
stack up and runs the entrypoint.

Two notes for whoever runs it:

* the repository has `role/` (singular), so the playbook cannot resolve the role
  `heriverse` without help. Point `ANSIBLE_ROLES_PATH` at a directory containing
  it under that name, or add an `ansible.cfg`. *Reported, not changed: it is the
  repository's own arrangement, not a typo of ours.*
* the role uses `community.docker.docker_compose_v2`, so that collection must be
  installed (`ansible-galaxy collection install community.docker`).

#### Variables worth knowing

| variable | default | what it decides |
|---|---|---|
| `server_name` | `heriverse.example.com` | **the** domain. Everything public is derived from it |
| `em_server_enabled` / `em_catalog_enabled` | `true` | whether the StratiGraph services come up at all |
| `rustfs_enabled` | `true` | object store on (RustFS, plus the one-shot `rustfs-init` that makes the bucket). Off ⇒ StratiGraph Server falls back to a directory (single instance only) |
| `iiif_enabled` | `true` | Cantaloupe on. Needs the object store |
| `em_catalog_couchdb_enabled` | `true` | the Catalog's index in CouchDB. Off ⇒ SQLite on a volume |
| `em_server_audience` / `em_catalog_audience` | `StratiGraph Server` | the audience each service requires in a token |
| `rustfs_access_key` / `rustfs_secret_key`, `couchdb_user` / `_password` | **none** | from the inventory or the Vault |
| `rustfs_image`, `rustfs_bucket`, `rustfs_api_port` / `rustfs_console_port` | `rustfs/rustfs:1.0.2`, `em-assets`, `9000` / `9001` | the store, its bucket and its ports |
| `em_asset_s3_console_url` | empty | the RustFS console link the node map offers (`EM_ASSET_S3_CONSOLE_URL`) |
| `EM_CORPUS_CURATORS` (env on StratiGraph Server) | **empty** | the ORCIDs allowed to read the **whole** resident DTC corpus. The register's per-file **slice** (`GET /v1/corpus?sha256=…`) is open to any authenticated caller — that is what clients use — but the lot is the provenance of every study on the instance, so it is a curation read and it is **off until somebody is named**. A refusal is a 403 that says so |
| `EM_CORPUS_OPEN` (env on StratiGraph Server) | unset | `1` opens the whole read to any authenticated caller. For a single-user instance; kept as one visible setting rather than a special case in the code |
| `EM_CORPUS_DIR` (env on StratiGraph Server) | falls back to `EM_SNAPSHOT_DIR` | where the resident corpus lives **when there is no object store**. With the S3 store configured the register rides in the same bucket as the assets it describes (`em/corpus.em.json`) and needs no setting |
| `EM_VOCABULARIES_DIR` (env on StratiGraph Server) | the platform's user folder (`~/.local/share/extendedmatrix/vocabularies` in the container) | the node's **vocabulary folder** — s3Dgraphy's `vocab_dir()`, the same one every EM tool shares on a desktop. What is installed there (by an operator, `POST /v1/vocab/install`, or by copying package folders in) is served as `GET /v1/vocabularies/catalog.json` and `/v1/vocabularies/<id>.emvocab.zip`, tiers A and B only. Point it at a mounted volume, or the vocabularies go with the container |

The URL topology is **already correct** in the templates: StratiGraph Server writes
`https://<server_name>/iiif/3` into its manifests and dials
`http://cantaloupe:8182/iiif/3` to measure images; StratiGraph Catalog writes
`https://<server_name>` into its "open in…" answers and reaches RustFS and CouchDB
by service name. Nothing about it has to be assembled by hand — see
[`URL-TOPOLOGY.md`](URL-TOPOLOGY.md) for why the two forms are two variables.

---

### Checking it without deploying

Everything below was **executed** while writing this page, against the templates
as they stand. None of it needs a host.

Render the compose template with example values and let Docker judge it:

```bash
ansible-playbook render.yml -e tpl_src=role/templates/docker-compose.yml.j2 -e tpl_dest=/tmp/dc.yml
docker-compose -f /tmp/dc.yml config
```

Measured (18 October 2026): **VALID**, twelve services — `caddy cantaloupe
couchdb heriverse heriverse-server keycloak postgres rustfs rustfs-init
stratigraph-catalog stratigraph-chatbot stratigraph-server` — and the volumes
`chatbot_data couchdb_config couchdb_data em_catalog_data em_data
em_documents_data keycloak_data rustfs_data`.

With the Catalog on its SQLite index and no object store
(`em_catalog_couchdb_enabled: false`, `rustfs_enabled: false`,
`iiif_enabled: false`): **VALID**, nine services, StratiGraph Server on
`EM_ASSET_DIR`, and the StratiGraph Catalog block
carries `EM_CATALOG_DB` instead of `COUCHDB_URL`. The config gating works in
both directions, which is the point of testing the *off* case at all.

Let Caddy judge its own file:

```bash
docker run --rm -v "$PWD:/work:ro" caddy:2-alpine caddy validate --config /work/Caddyfile --adapter caddyfile
```

Measured: **Valid configuration**, with all four StratiGraph routes present —
`/em/*`, `/catalog/*`, `/iiif/*`, `/assets/*`.

And the playbook itself:

```bash
ansible-galaxy collection install community.docker
ANSIBLE_ROLES_PATH=<dir containing role as "heriverse"> ansible-playbook --syntax-check playbook/heriverse.yml
```

Measured: **green**.

---

### After a deploy

```bash
curl -s https://<server_name>/em/v1/health | jq
curl -s https://<server_name>/catalog/health | jq
```

What to look for, in both answers:

* `"auth": "keycloak"` — **not** `dev-no-auth`. If it says the latter, the
  service did not get its OIDC environment and is answering to anybody;
* StratiGraph Server: `"asset_store": "s3 (…)"` — if it says `memory`, uploads are
  living in a process and will vanish with it;
* StratiGraph Catalog: `"container_store": "s3 (…)"` and `"index": "couchdb (…)"`.

Then the one that proves the architecture rather than the wiring:

```bash
curl -s -X POST https://<server_name>/catalog/reindex -H "Authorization: Bearer $TOKEN" | jq
```

It rebuilds the catalogue's index from the containers in the bucket. If it
answers with the number of studies you expect, the index is a projection and the
bucket is the truth — which is the property that makes the backup policy simple:
**back up the bucket** (and CouchDB, for Heriverse's own documents). The Catalog
index is derivable; the studies are not.

---

### Changing the realm after the first deploy

**Editing the realm JSON does not change a realm that already exists.** Keycloak's
`--import-realm` imports only when the realm is *absent*; on every later boot it
finds the realm and skips the file. So a change written into the repository,
committed and deployed, can sit there looking done and never be in effect —
and nothing says so. The symptom arrives later and elsewhere: a redirect URI
that is "clearly configured" and still refused, a mapper that is in git and not
in the token.

Measured on the dev stack, 2026-08-31, while adding the field assistant's client
configuration: the change had to be applied **twice** to be both real and
durable —

* **to the running realm**, through Keycloak's admin API, which is what takes
  effect now;
* **into the JSON**, which is what a *new* deployment (or a `--wipe`) will get.

Neither half is optional. The JSON alone is a plan; the admin API alone is a
change that the next fresh node will not inherit. Whoever edits a realm on a
live host should say, in the same breath, that they did both — and a realm
change that cannot be verified in a token is not verified at all: decode one and
look.

---

### What this page does not cover

* **OpenShift.** The node alone, as an image in an institution's cluster, is
  [`deploy/openshift/`](../deploy/openshift/README.md) — manifests, the
  variables classified, and the page for the cluster's administrators.
* **Turning the host on** — provisioning the machine, the DNS record, the
  firewall. That is ops, and it is deliberately outside the playbook.
* **The production Catalog's own features** — PID/DOI minting, FAIR publication,
  the browse UI. Those are 3DR's, on the WP6 infrastructure; what deploys here is
  our reference implementation of the contract.
* **Backups and monitoring.** Named, not solved: the bucket is the study data,
  `em_data` is the room documents, CouchDB holds documents for two systems.
