#!/usr/bin/env python3
"""T-F1 · a file lives in ONE room: «Move here», measured on the dev stack.

E.D., 3 October 2026, evening: «un file sta in UNA stanza; se serve altrove si
SPOSTA di stanza, mai condiviso tra stanze». The walk:

  1. `dev` makes rooms A and B; `viewer` is a viewer of A only;
  2. `dev` uploads a file into A (home = A) and seats a resource citing it;
  3. bringing it into B: HEAD through B answers 200 with `X-EM-Home-Room: A`,
     and sending the same bytes through B does NOT make B a second home;
  4. the view lists A as the room whose graph cites it (a reference after);
  5. no yes → 400; the yes → home = B, no byte sent again;
  6. on the server's own record (`asset-homes/<hex>.json` in the container):
     ONE home, B, and the move written down;
  7. A's viewer, not in B, is refused through A (403 naming B); HEAD through A
     names B.

    python3 dev-stack/smoke_one_home.py [--base http://localhost:8000/v1]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse

from smoke_common import (Tally, alive, arguments, body_of, call, detail_of,
                          need, orcid_of, token_for, unique)


def main() -> int:
    args = arguments(__doc__.splitlines()[0])
    base = args.base.rstrip("/")
    if not alive(base):
        return 2
    t = Tally()
    dev = need(token_for(args.owner), "a token for dev")
    viewer = need(token_for(args.viewer), "a token for viewer")
    stamp = unique("f1")
    room_a, room_b = f"{stamp}-a", f"{stamp}-b"
    q = lambda r: urllib.parse.quote(r, safe="")

    print("1 · two rooms, a viewer in A only")
    for room in (room_a, room_b):
        s, _, raw = call("POST", f"{base}/rooms", token=dev,
                         json_body={"room_id": room, "title": room})
        t.ok(s in (200, 201), f"room {room} created", f"{s} {detail_of(raw)[:80]}")
    s, _, raw = call("PUT", f"{base}/rooms/{q(room_a)}/members/{orcid_of(viewer)}",
                     token=dev, json_body={"role": "viewer"})
    t.ok(s == 200, "viewer is a viewer of A", f"{s} {detail_of(raw)[:80]}")

    print("2 · the file goes into A, and A's graph cites it")
    payload = os.urandom(64 * 1024)
    s, _, raw = call("PUT", f"{base}/rooms/{q(room_a)}/asset?media_type=model/gltf-binary",
                     token=dev, data=payload, media_type="application/octet-stream")
    info = body_of(raw)
    t.ok(s == 200 and info.get("home") == room_a, "uploaded into A, home = A",
         f"{s} home={info.get('home')}")
    ref = info["ref"]
    hexd = info["sha256"]
    s, _, raw = call("POST", f"{base}/rooms/{q(room_a)}/ops", token=dev, json_body={"ops": [
        {"op": "add_node", "id": "podio", "node": {
            "id": "podio", "node_type": "resource", "name": "podio.glb",
            "data": {"url": f"{base}/rooms/{q(room_a)}/asset/{ref}", "checksum": ref,
                     "residency": "resident"}}}]})
    t.ok(s == 200, "A's graph cites the file", f"{s} {detail_of(raw)[:80]}")
    s, _, _ = call("GET", f"{base}/rooms/{q(room_a)}/asset/{ref}", token=viewer)
    t.ok(s == 200, "before: A's viewer reads it", str(s))

    print("3 · «Bring into room» B finds it at home in A")
    s, h, _ = call("HEAD", f"{base}/rooms/{q(room_b)}/asset/{ref}", token=dev)
    t.ok(s == 200 and h.get("x-em-home-room") == room_a,
         "HEAD through B: present, X-EM-Home-Room = A", f"{s} {h.get('x-em-home-room')}")
    s, _, raw = call("PUT", f"{base}/rooms/{q(room_b)}/asset?media_type=model/gltf-binary",
                     token=dev, data=payload, media_type="application/octet-stream")
    again = body_of(raw)
    t.ok(s == 200 and again.get("created") is False and again.get("home") == room_a,
         "the same bytes sent through B: no second object, no second home",
         f"{s} created={again.get('created')} home={again.get('home')}")

    print("4 · the proposal «Move here», with the rooms that cite it")
    s, _, raw = call("GET", f"{base}/rooms/{q(room_b)}/asset-home/{ref}", token=dev)
    view = body_of(raw)
    t.ok(s == 200 and view.get("home") == room_a and view.get("can_move") is True,
         "the view: home A, you may move it", f"{s} {view.get('why_not')}")
    t.ok([c.get("room") for c in view.get("citing_rooms") or []] == [room_a]
         and view.get("references") == [room_a],
         "A's graph cites it: after the move A holds a reference",
         json.dumps(view.get("citing_rooms")))
    s, _, raw = call("GET", f"{base}/rooms/{q(room_b)}/asset-home/{ref}", token=viewer)
    t.ok(s == 200 and body_of(raw).get("can_move") is False,
         "A's viewer may ask (she reads it) but may not move it",
         f"{s} {body_of(raw).get('why_not')}")

    print("5 · the yes")
    s, _, raw = call("POST", f"{base}/rooms/{q(room_b)}/asset-home/{ref}", token=dev,
                     json_body={"from_room": room_a})
    t.ok(s == 400, "no confirm → 400, nothing moved", f"{s} {detail_of(raw)[:100]}")
    s, _, raw = call("POST", f"{base}/rooms/{q(room_b)}/asset-home/{ref}", token=viewer,
                     json_body={"from_room": room_a, "confirm": True})
    t.ok(s == 403, "a viewer of A cannot take it out of A", f"{s} {detail_of(raw)[:100]}")
    s, _, raw = call("POST", f"{base}/rooms/{q(room_b)}/asset-home/{ref}", token=dev,
                     json_body={"from_room": room_a, "confirm": True})
    moved = body_of(raw)
    t.ok(s == 200 and moved.get("moved") is True and moved.get("home") == room_b
         and moved.get("previous") == room_a, "moved: home = B, previous = A",
         f"{s} {moved.get('home')} ← {moved.get('previous')}")

    print("6 · the server's own record: one home")
    path = f"/srv/em-data/snapshots/asset-homes/{hexd[:2]}/{hexd}.json"
    out = subprocess.run(["docker", "exec", "em-dev-server", "cat", path],
                         capture_output=True, text=True)
    record = json.loads(out.stdout or "{}")
    t.ok(record.get("home") == room_b, "record: home = B", path)
    t.ok(sorted(record.get("rooms") or {}) == sorted([room_a, room_b])
         and isinstance(record.get("home"), str),
         "record: A and B only as the doors it came through, ONE home",
         json.dumps(record.get("rooms")))
    t.ok([m.get("to") for m in record.get("moves") or []] == [room_b]
         and record["moves"][0].get("from") == room_a,
         "record: the move written down (from A to B, by whom, when)",
         json.dumps(record.get("moves")))

    print("7 · A holds a reference now")
    s, _, raw = call("GET", f"{base}/rooms/{q(room_a)}/asset/{ref}", token=viewer)
    t.ok(s == 403 and room_b in detail_of(raw),
         "A's viewer, not in B: refused through A, told to ask B", f"{s} {detail_of(raw)[:100]}")
    s, h, _ = call("HEAD", f"{base}/rooms/{q(room_a)}/asset/{ref}", token=dev)
    t.ok(s == 200 and h.get("x-em-home-room") == room_b,
         "HEAD through A names B", f"{s} {h.get('x-em-home-room')}")
    s, _, raw = call("PUT", f"{base}/rooms/{q(room_a)}/asset?media_type=model/gltf-binary",
                     token=dev, data=payload, media_type="application/octet-stream")
    t.ok(s == 200 and body_of(raw).get("home") == room_b,
         "sending it through A again does not bring the home back", str(body_of(raw).get("home")))
    print(f"\n(rooms left on the node: {room_a}, {room_b})")
    return t.report("T-F1 one home")


if __name__ == "__main__":
    sys.exit(main())
