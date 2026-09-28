#!/usr/bin/env python3
"""Firme vere e ruoli nella stanza — i quattro utenti, contro il realm vero.

Le notti del 19 e del 22 ottobre l'autenticazione era spenta: token veri e ruoli
non erano mai stati esercitati. Questo smoke li esercita sulla stanza, con i
token che il realm di prova conia davvero:

    python dev-stack/smoke_firme_e_ruoli.py                    # dev-stack (https)
    python dev-stack/smoke_firme_e_ruoli.py --base http://localhost:8100/v1

Cosa misura, in ordine:

1. **chi non ha ruolo** (`outsider`) non entra: il socket si chiude con 4403;
2. **il viewer** entra, `can_write: false`, e la sua operazione è `denied`;
3. **due editor** (`editor`, `editor2`) scrivono, e il registro della stanza
   attribuisce a ciascuno la sua operazione (l'autore è il token, non il client);
4. **la scadenza dentro la sessione**: `editor2` entra con un token del client
   `stratifield-breve` (60 s), scrive, aspetta che scada, riscrive → `denied`
   «expired» e la porta si chiude con 4401. Il lavoro dopo la scadenza non c'è;
5. **la revoca a metà sessione**: `editor` scrive, l'owner lo toglie, la
   scrittura successiva è `denied` «withdrawn»;
6. **la porta REST** (`POST /v1/rooms/{id}/ops`): token scaduto → 401, ruolo
   tolto → 403, editor valido → 200 e autore giusto.

**Richiede il realm reimportato** (utenti `editor`, `editor2`, `outsider` e il
client `stratifield-breve`, tutti in `keycloak/realm-em-dev.json`):

    docker-compose -f docker-compose.dev.yml --env-file .env.dev \\
        up -d --force-recreate keycloak

Dura poco più di un minuto: il punto 4 aspetta davvero che il token scada.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

from smoke_common import Tally, alive, body_of, call, need, orcid_of, unique

KEYCLOAK = os.environ.get("KEYCLOAK_TOKEN_URL") or (
    "http://localhost:8085/auth/realms/em-dev/protocol/openid-connect/token")

_TLS = ssl.create_default_context()
_TLS.check_hostname = False
_TLS.verify_mode = ssl.CERT_NONE


def grant(user: str, client: str) -> dict:
    """Un token del realm per `user`, dal client che si nomina. La password è lo
    username, come il realm di prova li semina."""
    body = urllib.parse.urlencode({"grant_type": "password", "client_id": client,
                                   "username": user, "password": user}).encode()
    extra = ({"client_secret": "em-dev-secret"} if client == "em-server" else {})
    if extra:
        body += ("&" + urllib.parse.urlencode(extra)).encode()
    with urllib.request.urlopen(KEYCLOAK, body, timeout=15) as answer:
        return json.load(answer)


def ws_url(base: str, room: str, token: str) -> str:
    root = base.rstrip("/")
    root = ("wss://" + root[8:]) if root.startswith("https://") else (
        "ws://" + root[7:])
    return f"{root}/rooms/{urllib.parse.quote(room)}/ws?token={token}"


class Seat:
    """Un posto nella stanza: il join, e poi un frame alla volta."""

    def __init__(self, base: str, room: str, token: str):
        from websockets.sync.client import connect
        self.socket = connect(ws_url(base, room, token), open_timeout=10,
                              ssl=_TLS if base.startswith("https") else None)
        self.closed = None
        self.host = None
        try:
            for _ in range(3):
                frame = self.recv()
                if frame.get("type") == "host_info":
                    self.host = frame["payload"]
        except Exception as exc:                          # noqa: BLE001
            self.closed = getattr(getattr(exc, "rcvd", None), "code", None)

    def recv(self, timeout: float = 10.0) -> dict:
        return json.loads(self.socket.recv(timeout=timeout))

    def op(self, value: str, node: str = "US-smoke") -> dict:
        self.socket.send(json.dumps({
            "v": 2, "type": "op", "source": "smoke",
            "payload": {"op": "add_node", "id": node, "ts": _now(),
                        "node": {"id": node, "node_type": "US", "name": value}}}))
        while True:
            frame = self.recv()
            if frame.get("type") in ("op_result", "denied", "error"):
                return frame

    def closing_code(self) -> int | None:
        try:
            while True:
                self.recv(timeout=5)
        except Exception as exc:                          # noqa: BLE001
            return getattr(getattr(exc, "rcvd", None), "code", None)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="https://em.localhost:8443/em/v1")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    need(alive(base), "the node is not up")
    t = Tally()

    owner = need(grant("dev", "em-server").get("access_token"), "dev token")
    editor = grant("editor", "em-server")["access_token"]
    viewer = grant("viewer", "em-server")["access_token"]
    outsider = grant("outsider", "em-server")["access_token"]
    breve = grant("editor2", "stratifield-breve")
    t.ok(breve.get("expires_in") == 60, "il client breve conia token da 60 s",
         str(breve.get("expires_in")))
    ED2 = orcid_of(breve["access_token"])

    room = unique("smoke-firme")
    status, _, raw = call("POST", f"{base}/rooms", token=owner,
                          json_body={"room_id": room, "title": "smoke firme"})
    need(status in (200, 201), f"create room: {status} {raw[:200]!r}")
    for who, role in ((orcid_of(editor), "editor"), (ED2, "editor"),
                      (orcid_of(viewer), "viewer")):
        status, _, _ = call("PUT", f"{base}/rooms/{room}/members/{who}",
                            token=owner, json_body={"role": role})
        t.ok(status == 200, f"{role} {who} nella stanza", str(status))

    print("\n1 · chi non ha ruolo")
    fuori = Seat(base, room, outsider)
    t.ok(fuori.closed == 4403, "outsider: la porta si chiude con 4403",
         str(fuori.closed))

    print("\n2 · il viewer")
    vista = Seat(base, room, viewer)
    t.ok(vista.host and vista.host.get("can_write") is False,
         "viewer: entra, can_write false", json.dumps(vista.host)[:80])
    rifiuto = vista.op("dal viewer", "US-viewer")
    t.ok(rifiuto.get("type") == "denied", "viewer: la sua operazione è denied",
         rifiuto.get("payload", {}).get("reason", ""))

    print("\n3 · due editor, due autori")
    uno = Seat(base, room, editor)
    t.ok(uno.op("da editor", "US-editor").get("payload", {}).get("applied") is True,
         "editor scrive")
    due = Seat(base, room, breve["access_token"])
    t.ok(due.op("da editor2", "US-editor2").get("payload", {}).get("applied") is True,
         "editor2 scrive (token breve)")

    print("\n4 · la scadenza dentro la sessione")
    claims_exp = json.loads(__import__("base64").urlsafe_b64decode(
        breve["access_token"].split(".")[1] + "==="))["exp"]
    wait = max(0, claims_exp - time.time()) + 2
    print(f"    aspetto {wait:.0f} s che il token di editor2 scada…")
    # il battito tiene vivo il socket: la scadenza non chiude una presenza
    end = time.time() + wait
    while time.time() < end:
        due.socket.send(json.dumps({"v": 2, "type": "still_here",
                                    "source": "smoke", "payload": {}}))
        time.sleep(min(10, max(0.1, end - time.time())))
    scaduta = due.op("dopo la scadenza", "US-scaduta")
    t.ok(scaduta.get("type") == "denied"
         and "expired" in scaduta.get("payload", {}).get("reason", ""),
         "editor2: la scrittura dopo la scadenza è denied «expired»",
         scaduta.get("payload", {}).get("reason", ""))
    t.ok(due.closing_code() == 4401, "…e la porta si chiude con 4401")

    print("\n5 · la revoca a metà sessione")
    status, _, _ = call("DELETE", f"{base}/rooms/{room}/members/{orcid_of(editor)}",
                        token=owner)
    t.ok(status == 200, "l'owner toglie editor", str(status))
    revocato = uno.op("dopo la revoca", "US-revocato")
    t.ok(revocato.get("type") == "denied"
         and "withdrawn" in revocato.get("payload", {}).get("reason", ""),
         "editor: la scrittura dopo la revoca è denied «withdrawn»",
         revocato.get("payload", {}).get("reason", ""))

    print("\n6 · la porta REST")
    op = {"op": "add_node", "id": "US-rest", "ts": _now(),
          "node": {"id": "US-rest", "node_type": "US", "name": "dal REST"}}
    status, _, raw = call("POST", f"{base}/rooms/{room}/ops",
                          token=breve["access_token"], json_body={"ops": [op]})
    t.ok(status == 401, "token scaduto → 401", f"{status} {raw[:80]!r}")
    status, _, raw = call("POST", f"{base}/rooms/{room}/ops", token=editor,
                          json_body={"ops": [op]})
    t.ok(status == 403, "ruolo tolto → 403", f"{status} {raw[:80]!r}")
    fresco = grant("editor2", "stratifield-breve")["access_token"]
    status, _, raw = call("POST", f"{base}/rooms/{room}/ops", token=fresco,
                          json_body={"ops": [op]})
    t.ok(status == 200 and body_of(raw).get("applied") == 1,
         "editor2 col token rinnovato → 200", f"{status} {raw[:80]!r}")

    print("\n· il registro della stanza, per autore")
    status, _, raw = call("GET", f"{base}/rooms/{room}/changes"
                                 f"?since=1970-01-01T00:00:00Z", token=owner)
    changes = body_of(raw)
    per = changes.get("by_author") or {}
    print("    " + json.dumps(per))
    t.ok(per.get(orcid_of(editor)) == 1, "editor: 1 operazione, la sua")
    t.ok(per.get(ED2) == 2, "editor2: 2 operazioni (socket prima della "
                            "scadenza + REST dopo il rinnovo)")
    t.ok(orcid_of(viewer) not in per and orcid_of(outsider) not in per,
         "viewer e outsider: niente nel registro")
    return t.report("smoke_firme_e_ruoli")


if __name__ == "__main__":
    sys.exit(main())
