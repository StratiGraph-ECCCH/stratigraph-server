# StratiGraph Server on OpenShift

The node as an image inside an institution's OpenShift. Measured on 18 November
2026; every number below comes from a run, and says which.

```
deploy/openshift/
  base/                     the node alone: Deployment (+ preflight), Service,
                            Route, ConfigMap, Secret (empty), PVC
  components/
    postgres-nostro/        «we bring it»: PostgreSQL 16 for the documents
    s3-nostro/              «we bring it»: RustFS 1.0.2 as the object store
    keycloak-nostro/        «we bring it»: Keycloak 24 in dev mode — trials only
  overlays/
    casa/                   «you tell us»: everything external is the house's
    portatile/              «we bring it»: everything ours (OpenShift Local)
  ASKING-THE-HOUSE.md       one page for the platform's administrators
```

```
oc apply -k deploy/openshift/overlays/casa        # the institutional node
oc apply -k deploy/openshift/overlays/portatile   # a node with nobody's services
```

## The boundary

Every external dependency is a **value with two forms**: *we bring it* (a
component that runs the service and writes its address into the ConfigMap) or
*you tell us* (an address, a secret, a bucket, filled in by hand). The base
assumes neither. Mix freely: `casa` + `components/postgres-nostro` is a node
whose house gives identity and storage but no database.

| dependency | «you tell us» | «we bring it» |
|---|---|---|
| identity (OIDC) | `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI` | `components/keycloak-nostro` (dev mode: **trials only**) |
| object store (S3) | `EM_ASSET_S3_ENDPOINT`, `EM_ASSET_S3_BUCKET` + the key pair in the Secret | `components/s3-nostro` |
| documents' database | `EM_DOCUMENTS_HOST`, `EM_DOCUMENTS_DB` + user/password in the Secret | `components/postgres-nostro` — or **none**: revisions then live on the volume |
| public address | the Route `host` + `EM_PUBLIC_BASE` | the router's generated name |

Not in these manifests: the node's neighbours (catalogue, field assistant,
IIIF, photogrammetry engine). They are separate images, the server only *points*
at them (`EM_CATALOG_INTERNAL`, …, all optional), and a node without them is a
whole node that says «not configured» on its page.

## Where it writes — measured

With S3 and Postgres configured, a run as `--user 54321:0` with a **read-only
root filesystem** that created a room, stored a file, archived a `.blend`, made
a group, an invitation, a person, a people package and began an upload, left
files **only** under `EM_SNAPSHOT_DIR`:

```
node-key.pem  people.json  groups.json  <room>.room.json  <room>.acl.json
<room>.invites.json  node-log.jsonl  asset-homes/  blend-backup-register/
uploads-in-progress/
```

and nothing in `/tmp` or `$HOME`. (`<room>.acl.json` comes from the k3s run
below, with real tokens: in dev mode a room gets no owner, so no ACL file.)
`node-key.pem` is the node's **signing key**:
lose the volume and every node that trusts this one stops recognising it. Hence
one PVC on `/srv/em-data`, `ReadWriteOnce`, one replica, `Recreate`. Installed
vocabularies go to `EM_VOCABULARIES_DIR`, set to the same volume (its default
is under `$HOME`, i.e. the container's own disk).

The Dockerfile's header still says «Stateless by construction: no volume» and
«scale it by adding replicas». Measured, neither holds today.

## The probes — measured

| endpoint | when it answers | how long | what it can say |
|---|---|---|---|
| `/health` | as soon as uvicorn listens | ~2 ms | in-process: versions, stores, counts |
| `/v1/node` | from the same moment | **~6 s** with unreachable neighbours | probes catalogue / IIIF / field assistant; **always 200** |

So neither answers «only when ready»: the server has no running state that is
not ready. Stores are built before the port opens (~0.5 s with nothing to knock
on, ~4 s with an unreachable realm), and a store that does not answer makes the
**process exit** — S3 after ~21 s, Postgres after ~37 s — which the kubelet sees
as a crash, not as a failed probe. `/v1/node` as a probe would restart this pod
because *another* service is down. All three probes ask `/health`; the
`startupProbe` gives 60 s.

## The preflight

Without configuration the server starts — by design, on a laptop — in
`dev-no-auth` (every `/v1` route open) and with `memory` stores (measured:
`docker run --user 54321:0` on the bare image, `/health` 200, `auth:
dev-no-auth`). Behind a public Route that is the worst outcome, and the server
cannot tell a laptop from a Route. The deployment can, so the Deployment runs
`python -m app.preflight` as an init container with the same environment: a
missing obligatory value leaves the pod in `Init:Error`, and

```
oc logs deploy/stratigraph-server -c preflight
```

names each one. `tests/test_preflight.py` removes the obligatory variables one at
a time and requires a refusal naming each, and checks that **every** variable
the code reads is classified in the tables below.

## The variables — enumerated from the code, not from a compose

Every name read in `app/` (101) plus the two the s3Dgraphy library reads for
the node. Aliases are on the same row. «Empty» and «absent» are the same for
all of them **except** where the default column says *absent only*: there an
empty value replaces the default with `""`, so leave those out of the ConfigMap.

### Obligatory

The preflight refuses to start without these.

| variable | read at | why the node cannot stand without it |
|---|---|---|
| `EM_NODE_KIND` | `app/node_kind.py:55` (older: `EM_NODE_PROFILE`) | the kind decides the safe defaults; `institutional` refuses test people |
| `EM_PUBLIC_BASE` | `app/handoff.py:220` (older: `EM_SERVER_PUBLIC_URL`) | every link and every package for another node is built from it; must be `https://…/em` |
| `OIDC_ISSUER` | `app/auth.py:115` (or `TOKEN_ENDPOINT`, `:116`) | without it, `dev-no-auth`: every route open |
| `OIDC_AUDIENCE` | `app/auth.py:137` (or `CLIENT_ID_em`, `CLIENT_ID_emserver`) | idem; half of the pair is refused by the server itself |
| `EM_SNAPSHOT_DIR` | `app/store.py:449`, and the default of every directory below | rooms, ACL, people, the node's key: memory without it. The preflight also *writes* there |
| `EM_ASSET_S3_ENDPOINT` | `app/assets.py:543` | the files. Without S3: `EM_ASSET_DIR`, or memory |
| `EM_ASSET_S3_BUCKET` | `app/assets.py:546` | created by the server if the key may (`app/assets.py:394`) |
| `EM_ASSET_S3_ACCESS_KEY` | `app/assets.py:544` | **secret** |
| `EM_ASSET_S3_SECRET_KEY` | `app/assets.py:545` | **secret** |

The four `EM_ASSET_S3_*` may be replaced, together, by `EM_ASSET_DIR` on the
volume (one replica, no object store). Half of them is refused.

### Obligatory when another is set

| variable | read at | when |
|---|---|---|
| `EM_DOCUMENTS_DB` | `app/documents.py:155` | `EM_DOCUMENTS_HOST` set |
| `EM_DOCUMENTS_USER` | `app/documents.py:156` | idem — **secret** |
| `EM_DOCUMENTS_PASSWORD` | `app/documents.py:158` | idem — **secret** |

### Secret

Everything in the Secret, and nothing else: `EM_ASSET_S3_ACCESS_KEY`,
`EM_ASSET_S3_SECRET_KEY`, `EM_DOCUMENTS_USER`, `EM_DOCUMENTS_PASSWORD`,
`EM_DOCUMENTS_DSN` (it carries the password), `EM_KC_ADMIN_CLIENT_ID`,
`EM_KC_ADMIN_CLIENT_SECRET`, `EM_KC_ADMIN_USER`, `EM_KC_ADMIN_PASSWORD`,
`NODEODM_TOKEN`.

### Optional, with a declared default

**Storage**

| variable | read at | default |
|---|---|---|
| `EM_VOCABULARIES_DIR` | s3dgraphy `authorities/packages.py:99` | `$XDG_DATA_HOME` or `$HOME/.local/share` + `/extendedmatrix/vocabularies` — the container's disk: **set it** |
| `XDG_DATA_HOME` | s3dgraphy `authorities/packages.py:110` | `$HOME/.local/share` |
| `EM_ASSET_S3_SECURE` | `app/assets.py:547` | from the endpoint: `http://` → plain, else TLS |
| `EM_ASSET_DIR` | `app/assets.py:730` | none → memory (only without S3) |
| `EM_DOCUMENTS_HOST` | `app/documents.py:151` | none → revisions as files in `EM_SNAPSHOT_DIR` |
| `EM_DOCUMENTS_PORT` | `app/documents.py:162` | `5432` |
| `EM_DOCUMENTS_DSN` | `app/documents.py:148` | none (instead of the five pieces) |
| `EM_ROOM_DIR` | `app/store.py:413` | `EM_SNAPSHOT_DIR` |
| `EM_ACL_DIR` | `app/access.py:299` | `EM_SNAPSHOT_DIR` |
| `EM_INVITE_DIR` | `app/invites.py:240` | `EM_ACL_DIR`, then `EM_SNAPSHOT_DIR` |
| `EM_PEOPLE_DIR` | `app/people.py:195` | `EM_ACL_DIR`, then `EM_SNAPSHOT_DIR` |
| `EM_NODE_KEY_FILE` | `app/transfer.py:67` | `<people dir>/node-key.pem` |
| `EM_CORPUS_DIR` | `app/corpus.py:219` | `EM_SNAPSHOT_DIR` (only without S3) |
| `EM_ASSET_HOMES_DIR` | `app/asset_homes.py:364` | `EM_SNAPSHOT_DIR/asset-homes` |
| `EM_UPLOAD_DIR` | `app/uploads.py:59` | `EM_SNAPSHOT_DIR/uploads-in-progress`, else `/tmp/em-uploads` |
| `EM_BACKUP_BUCKET` | `app/blend_backups.py:334` | the asset bucket |
| `EM_BACKUP_DIR` | `app/blend_backups.py:338` | `EM_SNAPSHOT_DIR/blend-backups` (only without S3) |
| `EM_BACKUP_REGISTER_DIR` | `app/blend_backups.py:352` | `EM_SNAPSHOT_DIR/blend-backup-register` |
| `EM_ACCREDITED_FILE` | `app/accredited.py:44` | none (no list applied at start) |
| `EM_PERSONAL_ROOT` | `app/assets.py:719` | none — personal nodes only |

**Identity and people**

| variable | read at | default |
|---|---|---|
| `OIDC_JWKS_URI` | `app/auth.py:131` | `<issuer>/protocol/openid-connect/certs` — but set it: `app/node_health.py:324` reads only this variable and, without it, the operator page says «every /v1 route is open» on a node that enforces tokens (measured) |
| `OIDC_REQUIRED_SCOPE` | `app/auth.py:138` | none |
| `EM_SERVER_ALLOW_ANON` | `app/auth.py:139` | off — **never set it here**; ignored when OIDC is configured |
| `EM_OPERATORS` | `app/operators.py:64` | none: only the realm role grants operators |
| `EM_OPERATOR_ROLE` | `app/operators.py:58` | `em-operator` |
| `EM_CREATOR_ROLE` | `app/people.py:72` | `em-creator` |
| `EM_CREATE_POLICY` | `app/people.py:78` | `editors` |
| `EM_ALLOW_TEST_PEOPLE` | `app/people.py:84` | off (refused anyway on `institutional`) |
| `EM_CORPUS_CURATORS` | `app/corpus.py:332` | none |
| `EM_CORPUS_OPEN` | `app/corpus.py:339` | off |
| `EM_KC_ADMIN_URL` | `app/keycloak_admin.py:58` | none: the node does not manage Keycloak accounts |
| `EM_KC_REALM` | `app/keycloak_admin.py:59` | none |
| `EM_ORCID_IDP_ALIAS` | `app/identity.py:132`, `app/keycloak_admin.py:64` | `orcid` (*absent only* in `identity.py`) |
| `EM_ORCID_IDP_PROBE` | `app/main.py:694` | on |
| `EM_CONSOLE_CLIENT_ID` | `app/main.py:654` | `em-console` (*absent only*) |
| `EM_CONSOLE_REDIRECT_URI` | `app/main.py:660` | none |
| `EM_CONSOLE_SCOPE` | `app/main.py:667` | `openid profile email` (*absent only*) |
| `EM_NATIVE_CLIENT_ID` | `app/main.py:673` | none |
| `EM_NODE_NAME` | `app/identity.py:119` | the authority of `EM_PUBLIC_BASE` |
| `EM_CORS_ORIGINS` | `app/main.py:369` | `*` |

**Neighbours and faces** (absent = «not configured» on the node's page)

| variable | read at | default |
|---|---|---|
| `EM_IIIF_PUBLIC` | `app/main.py:2876` (older: `EM_IIIF_BASE`) | none |
| `EM_IIIF_INTERNAL` | `app/main.py:2877` (older: `EM_IIIF_INTERNAL_BASE`) | `EM_IIIF_PUBLIC` |
| `EM_IIIF_PUBLIC_BASE` | `app/node_health.py:363` | none (console link only) |
| `EM_CATALOG_INTERNAL` | `app/node_health.py:589` | none |
| `EM_CATALOG_PUBLIC` | `app/node_health.py:389` (or `EM_CATALOG_PUBLIC_URL`) | none |
| `EM_CHATBOT_INTERNAL` | `app/node_health.py:590` | none |
| `EM_FIELD_ASSISTANT_URL` | `app/handoff.py:139` | none |
| `EM_EMSTUDIO_WEB_URL` | `app/handoff.py:122` | none |
| `EM_EMSTUDIO_INTERNAL` | `app/node_health.py:751` | none |
| `EM_KEYCLOAK_CONSOLE_URL` | `app/node_health.py:330` | none |
| `EM_ASSET_S3_CONSOLE_URL` | `app/node_health.py:285` | none |
| `EM_NODEODM_CONSOLE_URL` | `app/node_health.py:532` | none |
| `NODEODM_URL` | `app/node_health.py:734`, `app/photogrammetry.py:44` | none |
| `NODEODM_ENABLED` | `app/node_health.py:735` | unsaid |
| `NODEODM_START_HINT` | `app/node_health.py:736` | none |
| `EM_TOOLS_EMSTUDIO_DOWNLOAD` | `app/main.py:836` | `https://extendedmatrix.org/download` (*absent only*) |
| `EM_TOOLS_EMSTUDIO_MANUAL` | `app/main.py:838` | `https://docs.extendedmatrix.org` (*absent only*) |
| `EM_TOOLS_BLENDER_DOWNLOAD` | `app/main.py:839` | `https://blender.extendedmatrix.org` (*absent only*) |
| `EM_TOOLS_BLENDER_MANUAL` | `app/main.py:841` | the EM-tools installation page (*absent only*) |

**Tuning.** *Absent only* for the ones marked: there an empty value is not
a default but a crash — measured, `EM_TRASH_DAYS=''`, `EM_HEALTH_DEADLINE=''`
and `EM_OPLOG_KEEP=''` each make `import app.main` exit 1 (`int("")`); the
photogrammetry ones are the same `int()`/`float()` but were NOT measured to
fail (`import app.main` exits 0 with them empty). `EM_SAVE_AFTER_*` and
`EM_PRESENCE_*` log and keep the default.

| variable | read at | default |
|---|---|---|
| `EM_TRASH_DAYS` | `app/trash.py:27` | `30` (*absent only*) |
| `EM_BULK_ROOMS` | `app/trash.py:29` | `20` (*absent only*) |
| `EM_BULK_BYTES` | `app/trash.py:30` | 5 GiB (*absent only*) |
| `EM_TRASH_SWEEP` | `app/main.py:156` | `1` (on) |
| `EM_PHOTOGRAMMETRY_HISTORY` | `app/photogrammetry.py:48` | `50` (*absent only*) |
| `EM_PHOTOGRAMMETRY_DEADLINE` | `app/photogrammetry.py:52` | `3600` s (*absent only*) |
| `EM_HEALTH_DEADLINE` | `app/node_health.py:50` | `2.5` s (*absent only*) |
| `EM_HEALTH_TIMEOUT` | `app/node_health.py:54` | `2.0` s (*absent only*) |
| `EM_HEALTH_COUNT_CAP` | `app/node_health.py:61` | `5000` (*absent only*) |
| `EM_OPLOG_KEEP` | `app/oplog.py:147` | `10000` (*absent only*) |
| `EM_OPLOG_SLACK` | `app/oplog.py:153` | `1000` (*absent only*) |
| `EM_SAVE_AFTER_OPS` | `app/keeping.py:106` | `64` |
| `EM_SAVE_AFTER_QUIET_SECONDS` | `app/keeping.py:107` | `2.0` |
| `EM_PRESENCE_BEAT_SECONDS` | `app/presence.py:115` | `10` |
| `EM_PRESENCE_QUIET_AFTER_SECONDS` | `app/presence.py:120` | `30` |
| `OPS_BATCH_MAX` | `app/main.py:4467` | `1000` |
| `EM_ASSET_LIST_CAP` | `app/main.py:6190` | `50000` |

**Not read by the image**

| variable | read at | note |
|---|---|---|
| `EM_SERVER_HOST`, `EM_SERVER_PORT` | `app/main.py:7506` | only by `python -m app.main`; the image's `CMD` is uvicorn on `0.0.0.0:8000` |

## Gates, as run on 18 November 2026

- `kubectl apply -k … --dry-run=client` **and** `--dry-run=server` (k3s 1.31
  with the `route.openshift.io/v1` CRD from `openshift/api`) on `base`,
  `overlays/casa`, `overlays/portatile`: no error. Not run against a real
  OpenShift API server: none was available.
- `docker run --user 54321:0` on the built image: starts, `/health` 200; with
  the full configuration also with `--read-only`.
- `overlays/portatile` **applied** on the same k3s, with the pods patched as
  restricted-v2 would (`runAsUser: 1000650000`, `runAsGroup: 0`, `fsGroup`):
  all four pods Running, 0 restarts; preflight «complete»; `auth: keycloak`,
  Postgres and S3 stores; 401 without a token, room created and file stored
  with a real token from the bundled Keycloak; the room survived a restart.
- `overlays/casa` applied as committed (empty): without the Secret the kubelet
  stops the pod (`secret … not found`); with an empty Secret the pod stays in
  `Init:Error` and the preflight names `EM_PUBLIC_BASE`, the OIDC pair and the
  asset store.
- `tests/test_preflight.py`: each obligatory variable removed → refusal naming
  it; every variable the code reads is classified above.
