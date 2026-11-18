# StratiGraph node — what we need from the platform

*For the administrators of the OpenShift cluster that will host the node. One
page; the details behind every line are in `README.md` next to this file.*

**What it is.** StratiGraph Server is a web service (Python, one container,
HTTP on port 8000) where archaeologists work together on stratigraphic
documents: shared "rooms", the files that belong to them (3D models, images,
PDFs), and the people allowed in. It runs as **one pod**, as an arbitrary
non-root UID (built and tested for `restricted-v2`: group-0 ownership, numeric
`USER`, read-only root filesystem). It is not horizontally scalable today.

## Services we would like you to provide

| | what | requirement | if you cannot |
|---|---|---|---|
| 1 | **OpenID Connect provider** (Keycloak) | a realm and a client for the node; tokens are JWTs signed RS256/384/512 or ES256/384, with the client id in `aud` (Keycloak: an *audience* mapper) and the user's ORCID iD in a claim (`orcid` is the one we use; a *user attribute* mapper). Ideally ORCID as an identity provider of the realm. Tested against Keycloak 24 | we can run a Keycloak for trials only — not suitable for production |
| 2 | **S3-compatible object store** | one bucket (the node creates it if its key may); path-style addressing, AWS Signature v4. The node signs for region **`us-east-1`** and cannot be told another today — please tell us if your store refuses that | we can run RustFS in the project, on a volume you give us |
| 3 | **PostgreSQL** (optional) | one database, one user owning it. Tested with 16 | the node keeps document revisions on its own volume instead |

## What we need to receive

- **A project (namespace)**, and permission to create there: Deployment,
  Service, Route, ConfigMap, Secret, PersistentVolumeClaim.
- **A hostname** for the Route, with TLS at the edge (your certificate or the
  router's). The node lives under the path **`/em`** of that host; the identity
  service can share the host under `/auth` if it is ours.
- **The image**: either pulled from `ghcr.io/stratigraph-eccch/stratigraph-server`
  or mirrored into your registry — tell us which.
- **A persistent volume**, ReadWriteOnce, **20 GiB** to start (an estimate:
  small records plus large uploads in transit). It holds the node's signing
  key and its people and access lists — it must be backed up.
- **These values** (addresses, not secrets): the OIDC issuer URL, the client id
  (audience), the S3 endpoint and bucket name, the PostgreSQL host and database
  name if any.
- **These secrets**, through whatever channel you use — we never need to see
  them if you create the Secret yourselves: the S3 access key and secret key;
  the PostgreSQL user and password if any; optionally a Keycloak service-account
  client id and secret allowed to manage users in the realm (so the node can set
  local passwords; without it that feature is off).

## Network

**Inbound:** HTTPS through the Route only. Rooms use **WebSockets** (kept alive
by a ping every 20 s); uploads can be large and slow, so the Route asks for a
5-minute idle timeout (`haproxy.router.openshift.io/timeout: 5m`). No request
body limit is needed beyond the file sizes your users work with.

**Outbound** from the pod:

| to | port | when |
|---|---|---|
| the OIDC provider (its certificate URL) | 443 (or internal) | at start, and to verify tokens |
| the S3 endpoint | 443 (or internal) | always — the pod **refuses to start** if it does not answer |
| PostgreSQL | 5432 | always, if configured — same refusal |
| `github.com` / `objects.githubusercontent.com` | 443 | only when an operator installs or updates a vocabulary |

Nothing else. Optional neighbour services (catalogue, field assistant, IIIF
image server, photogrammetry engine) are separate images and not part of this
request.

## Resources

Measured idle with S3 and PostgreSQL: **~116 MiB** of memory. We request
100m CPU / 256 MiB and limit memory to 2 GiB for operations on large documents.

## How you will know it is wrong

The pod runs a check before the server starts. If any value above is missing,
the pod stays in `Init:Error` and `oc logs deploy/stratigraph-server -c
preflight` names each missing value in a sentence. Health: `GET /em/health`.
