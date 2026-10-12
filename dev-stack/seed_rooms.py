#!/usr/bin/env python3
"""Seed the demonstration rooms — the visibility pair, and the room to work in.

    python dev-stack/seed_rooms.py
    python dev-stack/seed_rooms.py --force          # …re-asserting the work room too
    python dev-stack/seed_rooms.py --room=seme-prova-2026-10-12
                                                    # only the work room, by another name

`mostra` is `visibility: public` and `scavo` is `restricted`. They are the same
study twice, on purpose: the ONLY difference between them is that one word in the
header, so a probe of the two answers the question "what does publishing change?"
without any other variable moving.

`basilica-demo` is a third room, and a different KIND of thing: a small
stratigraphy for two EMStudio clients to meet in (walkthrough Tappa 4). Which is
why it is **preserved** on a re-run — the other two are fixtures nobody edits,
this one is where somebody's editing happens, and a seed that silently replaced a
morning's work would be the worst kind of idempotent.

    curl -s -o /dev/null -w '%{http_code}\\n' http://localhost:8000/v1/rooms/mostra/iiif/img-1/manifest   # 200
    curl -s -o /dev/null -w '%{http_code}\\n' http://localhost:8000/v1/rooms/scavo/iiif/img-1/manifest    # 401

**Through the door, not into the volume** (12 October 2026). This seed used to
write `<room>.em.json` into `/srv/em-data/snapshots` with `docker exec`, and to
decide «it is already there» by testing that file. Since `EM_DOCUMENTS_*` the
server keeps documents in Postgres (`PostgresSnapshotStore`) and never reads that
directory for them — measured: the file said 6 units and 5 relations, the table
had 133 revisions of the room, and a room seeded under a new name was born
EMPTY. A seed that writes where the server does not read is a seed that only
looks like it worked.

So every room is made the way a client makes one: `POST /v1/rooms` (record,
owner, the graph it is born with), then the content as **operations**
(`POST /v1/rooms/<id>/ops`, in batches), then `PUT /v1/rooms/<id>/study-access`
for the one word that is not an operation. «Already there» is asked of the
server too: `missing_refs` in the room's description says whether its container
has anything in it, whichever store holds it.

**`--force` re-asserts, it does not erase.** The relay stamps each operation
with the time it arrives, and a node added again is a MERGE in which the newer
clock wins field by field. So a forced re-run brings the seed's units, names,
descriptions and relations back as the seed wrote them — a rename made in the
room is overwritten, a deleted unit returns — while whatever somebody ADDED stays,
and so does every revision in the history. A rewrite to a blank page is not
offered: the history is rows in a table, and the only door into a room is the
operations, which add to it.

What the document header used to carry and an operation cannot say — the work
room's `description` («Dato di dimostrazione, non uno scavo.») — no longer
travels; the room's title says the same.

The image both rooms point at is the one `smoke_iiif.py` uploads; run that first
(or after — the manifest is what needs it, not the seed).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

#: The image the two rooms annotate — the digest `smoke_iiif.py` produces. It is
#: a CONTENT address, so it is the same on every machine that runs that smoke.
IMAGE_SHA = ("sha256:4239fc67504c2b22c584d4de71b7329e"
             "3c01b2a0b716aaa198ca6c4120b00abe")

def document(room_id: str, name: str, visibility: str) -> dict:
    """One room: an image and two annotated regions. Identical but for the word."""
    return {
        "header": {"format": "em.json", "version": "1.0",
                   "visibility": visibility},
        "graphs": {room_id: {
            "graph_id": room_id,
            "name": name,
            "nodes": [
                {"id": "img-1", "node_type": "resource", "name": "Foto di scavo",
                 "data": {"checksum": IMAGE_SHA, "media_type": "image/png",
                          "residency": "reference"}},
                {"id": "reg-a", "node_type": "annotation_region", "name": "muro",
                 "data": {"shape_kind": "rect", "rect": [0.1, 0.1, 0.3, 0.2],
                          "page": 0, "resource_id": "img-1"}},
                {"id": "reg-b", "node_type": "annotation_region", "name": "soglia",
                 "data": {"shape_kind": "rect", "rect": [0.55, 0.6, 0.25, 0.25],
                          "page": 0, "resource_id": "img-1"}},
            ],
            "edges": [
                {"id": "e-a", "source": "reg-a", "target": "img-1",
                 "edge_type": "is_on_resource"},
                {"id": "e-b", "source": "reg-b", "target": "img-1",
                 "edge_type": "is_on_resource"},
            ],
        }},
        "active_graph_id": room_id,
    }


def work_room(room_id: str, name: str) -> dict:
    """A small stratigraphy — the room two clients meet in.

    Not annotated regions this time but **units and a relation**, because what
    Tappa 4 shows is one person editing and another seeing it: that needs a
    graph somebody can rename a node in, and a matrix that redraws when they do.

    Small on purpose. Six units and five relations are enough to see an edit
    arrive; a hundred would only make the screen harder to read.

    Node and edge shapes are literal here — the same idiom as the fixtures above
    — and they are the shapes s3Dgraphy's importer builds (`node_type: "US"`,
    `edge_type: "is_before"`, measured against `StratigraphicUnit`), not a guess.
    """
    units = [
        ("US1", "US 1", "Crollo di tegole sul piano di calpestio."),
        ("US2", "US 2", "Piano in cocciopesto, integro nel settore nord."),
        ("US3", "US 3", "Muro perimetrale est, opera mista."),
        ("US4", "US 4", "Fossa di spoliazione lungo il muro est."),
        ("US5", "US 5", "Riempimento della fossa, terra e frammenti."),
        ("US6", "US 6", "Fondazione del muro perimetrale."),
    ]
    #: `is_before` = the source is EARLIER. Read them as a sequence: the collapse
    #: sits on the floor, the floor abuts the wall, the robbing cuts the wall.
    relations = [("US1", "US2"), ("US2", "US3"), ("US4", "US3"),
                 ("US5", "US4"), ("US3", "US6")]
    return {
        "header": {"format": "em.json", "version": "1.0",
                   "visibility": "restricted",
                   "description": "Dato di dimostrazione, non uno scavo."},
        "graphs": {room_id: {
            "graph_id": room_id,
            "name": name,
            "nodes": [
                {"id": unit, "node_type": "US", "name": label,
                 "description": description}
                for unit, label, description in units
            ],
            "edges": [
                {"id": f"{a}__is_before__{b}", "source": a, "target": b,
                 "edge_type": "is_before"}
                for a, b in relations
            ],
        }},
        "active_graph_id": room_id,
    }


#: `preserve` = left as it is when the room already has content. See the module
#: docstring: a fixture is meant to be re-asserted, a room somebody works in is not.
ROOMS = (
    ("mostra", "Mostra (dissemination)", "public", document, False),
    ("scavo", "Scavo (in corso)", "restricted", document, False),
    ("basilica-demo", "Basilica · saggio dimostrativo", None, work_room, True),
)

#: Operations per request. The server takes up to `OPS_BATCH_MAX` (1000) and
#: holds the room's lock for the whole batch; these rooms are a handful of
#: operations, so the cap only matters to whoever reuses this for a big study.
BATCH = 200

#: The reasons the relay gives when an operation changed nothing because the
#: room already had it — `s3dgraphy.crdt.NOT_NEWS`, copied because this script
#: imports nothing that is not the standard library.
NOT_NEWS = ("stale", "idempotent", "already removed, not older")


def ops_of(doc: dict, graph_id: str) -> list:
    """The document as the operations that build it: a node, then an edge.

    No `ts` and no `author`: the relay stamps the first with the moment the
    operation arrives and writes the second from the token — an author in the
    payload would be dropped anyway. That arrival clock is what makes `--force`
    win against an older edit (see the module docstring).

    `data.lang` = `it`, because every word in these rooms is Italian and an
    `add_node` since s3dgraphy dev28 carries its language in the operation
    rather than having the study's guessed for it.
    """
    graph = doc["graphs"][graph_id]
    ops = []
    for node in graph["nodes"]:
        node = json.loads(json.dumps(node))
        node.setdefault("data", {}).setdefault("lang", "it")
        ops.append({"op": "add_node", "id": node["id"], "node": node})
    for edge in graph["edges"]:
        ops.append({"op": "add_edge", "id": edge["id"], "source": edge["source"],
                    "target": edge["target"], "edge_type": edge["edge_type"]})
    return ops


class Api:
    """The node's `/v1`, with a token from `token.sh`. Nothing else talks to it.

    The dev stack's TLS is its own internal CA, so the certificate is not
    checked: this script runs against `em.localhost` and nowhere else.
    """

    def __init__(self) -> None:
        import ssl
        self.base = f"https://{env_domain()}:{env_https_port()}/em/v1"
        self.tls = ssl.create_default_context()
        self.tls.check_hostname = False
        self.tls.verify_mode = ssl.CERT_NONE

    @staticmethod
    def token(user: str | None) -> str | None:
        args = [str(pathlib.Path(__file__).resolve().parent / "token.sh")]
        if user:
            args += ["--user", user]
        try:
            out = subprocess.run(args, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
        return lines[-1] if lines else None

    def call(self, method: str, path: str, body: dict | None = None,
             bearer: str | None = None) -> tuple[int, dict]:
        import urllib.error
        import urllib.request
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.tls,
                                        timeout=20) as answer:
                return answer.status, json.loads(answer.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"null")
            except ValueError:
                return exc.code, {}
        except urllib.error.URLError as exc:
            return 0, {"detail": f"{self.base} not reachable ({exc.reason})"}


def has_content(api: Api, owner: str, room_id: str, made: tuple) -> bool | None:
    """Does the room's container already hold something? Asked of the SERVER.

    `missing_refs` names the containers the snapshot store does not have —
    whichever store that is. The answer to `POST /rooms` carries it when the room
    was just declared (an implicit room adopted keeps its container); a 409 means
    a record existed, and then the room's own description is asked.
    """
    status, room = made
    if status != 201:
        status, room = api.call("GET", f"/rooms/{room_id}", bearer=owner)
        if status != 200:
            print(f"[ FAIL ] {room_id}: GET {status} {room.get('detail')}")
            return None
    return room_id not in (room.get("missing_refs") or [])


def seed_room(api: Api, owner: str, room_id: str, name: str,
              visibility: str | None, doc: dict, *, preserve: bool,
              force: bool) -> bool:
    """One room through the door: record, content as operations, the header word."""
    made = api.call("POST", "/rooms", {
        "room_id": room_id, "title": name, "container_refs": [room_id],
        # born with its graph NAMED: the one thing about a section an
        # operation cannot say
        "graphs": [{"graph_id": room_id, "name": name}],
        "active_graph_id": room_id}, owner)
    status, answer = made
    if status == 0 or (status not in (201, 409)) or (
            status == 409 and "already declared" not in str(answer.get("detail"))):
        print(f"[ FAIL ] {room_id}: POST /rooms {status} {answer.get('detail')}")
        return False
    full = has_content(api, owner, room_id, made)
    if full is None:
        return False
    if full and preserve and not force:
        print(f"[ kept ] {room_id} — c'era già, non l'ho toccata "
              f"(--force per riaffermare il seme)")
        return True

    ops = ops_of(doc, room_id)
    applied, already, refused = 0, 0, []
    for start in range(0, len(ops), BATCH):
        status, out = api.call("POST", f"/rooms/{room_id}/ops",
                               {"ops": ops[start:start + BATCH],
                                "graph_id": room_id}, owner)
        if status != 200:
            print(f"[ FAIL ] {room_id}: ops {status} {out.get('detail')}")
            return False
        applied += out.get("applied", 0)
        for one in out.get("refused") or []:
            # «the state already knew» is not a refusal (s3dgraphy's
            # `NOT_NEWS`): an edge that is there is the seed's answer, too
            if one.get("reason") in NOT_NEWS:
                already += 1
            else:
                refused.append(one)
    verb = "riaffermata" if full else "creata"
    print(f"[  ok  ] {room_id} — {verb}: {applied}/{len(ops)} operazioni"
          + (f", {already} già lì" if already else "")
          + (f", RIFIUTATE {refused}" if refused else ""))

    # only when the seed SAYS it: `restricted` is the default, and writing it
    # into a work room would be one more revision that changes nothing
    if visibility:
        status, out = api.call("PUT", f"/rooms/{room_id}/study-access",
                               {"visibility": visibility}, owner)
        if status != 200:
            print(f"[ FAIL ] {room_id}: study-access {status} {out.get('detail')}")
            return False
        print(f"[  ok  ] {room_id} — visibility: {out.get('visibility')}")
    return not refused


# ── roles and an invitation ──────────────────────────────────────────────────
#
# Roles and invitation links are ACTS — the ACL is written through the door that
# checks who is asking, and an invite's secret exists exactly once, in the answer
# to the request that mints it.

DEMO = "cantiere-demo"


def api_pass(api: Api, owner: str) -> bool:
    """Declare the demo room, seat three people in it, and print a link."""

    def orcid_of(jwt: str) -> str | None:
        import base64
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:                                  # noqa: BLE001
            return None
        return (claims.get("orcid") or claims.get("preferred_username")
                or claims.get("sub"))

    call = api.call
    base = api.base
    guest = api.token("viewer")
    who_owner, who_guest = orcid_of(owner), (orcid_of(guest) if guest else None)

    # 1 · the demo WORKSPACE: two containers, because a room references 1..N
    status, made = call("POST", "/rooms", {
        "room_id": DEMO, "title": "Cantiere · demo (due container)",
        "container_refs": ["basilica-demo", "scavo"]}, owner)
    if status == 409:
        print(f"[ kept ] {DEMO} — c'era già (i ruoli e il link li rifaccio)")
    elif status == 201:
        print(f"[  ok  ] {DEMO} — record + refs "
              f"{made.get('container_refs')} · owner {who_owner}")
    else:
        print(f"[ FAIL ] {DEMO}: {status} {made.get('detail')}")
        return False

    # 2 · three people, three roles. The viewer is a REAL realm user, so the
    #     read-only face can be tried by logging in as them.
    seated = []
    if who_guest:
        status, _ = call("PUT", f"/rooms/{DEMO}/members/{who_guest}",
                         {"role": "viewer"}, owner)
        seated.append(f"{who_guest} → viewer ({status})")
    # …and a third identity as editor, so a promotion has somewhere to go
    editor = "0000-0003-1415-9265"
    status, _ = call("PUT", f"/rooms/{DEMO}/members/{editor}",
                     {"role": "editor"}, owner)
    seated.append(f"{editor} → editor ({status})")
    print(f"[  ok  ] {DEMO} — ACL: owner {who_owner} · " + " · ".join(seated))

    # 3 · a link, printed. Once — the node keeps a digest, not the link.
    status, invite = call("POST", f"/rooms/{DEMO}/invites",
                          {"role": "editor"}, owner)
    if status == 201 and invite.get("token"):
        print(f"[  ok  ] {DEMO} — invite link (editor), shown ONCE:")
        print(f"           token   {invite['token']}")
        print(f"           EMStudio  <emstudio-url>?join={invite['token']}"
              f"&room={DEMO}")
        print(f"           curl      curl -sk -X POST {base}/join "
              f"-H 'Authorization: Bearer $(./dev-stack/token.sh --user viewer)' "
              f"-H 'Content-Type: application/json' "
              f"-d '{{\"token\":\"{invite['token']}\"}}'")
    else:
        print(f"[ FAIL ] {DEMO} — no invite link: {status} {invite.get('detail')}")
        return False
    return True


def main() -> int:
    force = "--force" in sys.argv
    only = next((a.split("=", 1)[1] for a in sys.argv[1:]
                 if a.startswith("--room=")), None)
    api = Api()
    owner = api.token(None)
    if not owner:
        print("no token from ./dev-stack/token.sh — is Keycloak up? Bring the "
              "stack up first:\n  docker-compose --env-file .env.dev "
              "-f docker-compose.dev.yml up -d")
        return 2
    status, health = api.call("GET", "/health")
    if status != 200:
        print(f"the node does not answer at {api.base}: {status} "
              f"{health.get('detail')}")
        return 2

    rooms = ROOMS
    if only:
        # the work room under another name: what a test seeds, and archives after
        rooms = ((only, f"Seme · {only}", None, work_room, True),)
    ok = True
    for room_id, name, visibility, build, preserve in rooms:
        doc = (build(room_id, name, visibility) if visibility is not None
               else build(room_id, name))
        ok = seed_room(api, owner, room_id, name, visibility, doc,
                       preserve=preserve, force=force) and ok
    if only:
        return 0 if ok else 1

    print()
    ok = api_pass(api, owner) and ok

    print("\nLe stanze hanno un RECORD durevole: esistono anche vuote, si "
          "elencano con\n`GET /v1/rooms`, e referenziano 1..N container. Gli "
          "inviti (`POST\n/v1/rooms/<id>/invites`) vivono accanto agli ACL.")
    print("\nPer Tappa 4 (EMStudio come client), da incollare in "
          "Impostazioni ▸ Live sync:")
    print(f"  URL     https://{env_domain()}:{env_https_port()}/em")
    print(f"  Stanza  basilica-demo")
    print("  Token   ./dev-stack/token.sh   (il campo lo chiede Mode ▾ → In a room)")
    return 0 if ok else 1


def env_domain() -> str:
    return _env("EM_DEV_DOMAIN", "em.localhost")


def env_https_port() -> str:
    return _env("HTTPS_PORT", "8443")


def _env(name: str, default: str) -> str:
    """Read `.env.dev` without importing anything: this script deliberately has
    no dependencies, so that it works while the stack is half-up."""
    import os
    import pathlib
    if os.environ.get(name):
        return os.environ[name]
    path = pathlib.Path(__file__).resolve().parent / ".env.dev"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return default


if __name__ == "__main__":
    raise SystemExit(main())
