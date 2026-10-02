"""«Who you are» says WHY the node's ORCID way is closed (3 Oct 2026).

On the dev stack the realm's ORCID provider reads `ORCID_CLIENT_ID` from
`.env.dev`; empty, the compose fills in `orcid-client-not-registered`, and the
node's «Sign in with ORCID» sent the person to ORCID to be told «invalid
client». `/v1/auth-config` now says whether the provider has an ORCID client —
measured by starting the round trip a browser starts and reading the
`client_id` Keycloak is about to send to ORCID (measured on em-dev, Keycloak
24.0.4: auth → `/broker/orcid/login` → `<ORCID_ISSUER>/oauth/authorize?…
&client_id=orcid-client-not-registered&redirect_uri=…/broker/orcid/endpoint`).

A fake Keycloak plays the two redirects here.
"""
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import orcid_idp_probe as probe


class _FakeRealm(BaseHTTPRequestHandler):
    client_id = "orcid-client-not-registered"
    issuer = "https://sandbox.orcid.org"
    known_redirect = "org.extendedmatrix.emstudio:/oidc-return"
    seen: list = []

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        type(self).seen.append(url.path)
        if url.path.endswith("/protocol/openid-connect/auth"):
            if q.get("redirect_uri", [""])[0] != self.known_redirect:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid parameter: redirect_uri")
                return
            self.send_response(302)
            self.send_header("Set-Cookie", "AUTH_SESSION_ID=abc; Path=/")
            # Keycloak writes its FRONTEND url: the public name
            self.send_header("Location", "https://em.localhost:8443/auth/realms/em-dev/broker/orcid/login?session_code=x")
            self.end_headers()
            return
        if url.path.endswith("/broker/orcid/login"):
            if "AUTH_SESSION_ID=abc" not in (self.headers.get("Cookie") or ""):
                self.send_response(400)
                self.end_headers()
                return
            target = (f"{self.issuer}/oauth/authorize?scope=openid&response_type=code"
                      f"&client_id={urllib.parse.quote(self.client_id)}"
                      "&redirect_uri=https%3A%2F%2Fem.localhost%3A8443%2Fauth%2Frealms%2Fem-dev%2Fbroker%2Forcid%2Fendpoint")
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def realm():
    server = HTTPServer(("127.0.0.1", 0), _FakeRealm)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeRealm.seen = []
    yield f"http://127.0.0.1:{server.server_address[1]}/auth/realms/em-dev", _FakeRealm
    server.shutdown()


def _ask(internal, **kw):
    return probe.probe_orcid_idp(
        authorization_endpoint="https://em.localhost:8443/auth/realms/em-dev/protocol/openid-connect/auth",
        client_id="em-console", redirect_uri=kw.get("redirect", "org.extendedmatrix.emstudio:/oidc-return"),
        alias="orcid", public_prefix="https://em.localhost:8443/auth/realms/em-dev",
        internal_prefix=internal)


def test_no_client_is_said_with_the_client_id_keycloak_would_send(realm):
    internal, fake = realm
    fake.client_id = "orcid-client-not-registered"
    ready, why = _ask(internal)
    assert ready is False
    assert "has no ORCID client" in why and "orcid-client-not-registered" in why
    # the two hops, through the INTERNAL name, with the session cookie
    assert fake.seen == ["/auth/realms/em-dev/protocol/openid-connect/auth",
                         "/auth/realms/em-dev/broker/orcid/login"]


def test_an_orcid_client_id_is_ready(realm):
    internal, fake = realm
    fake.client_id = "APP-DBYSPGP676HKN8OE"
    assert _ask(internal) == (True, "")


def test_an_empty_issuer_is_said_too(realm):
    internal, fake = realm
    fake.client_id, fake.issuer = "APP-DBYSPGP676HKN8OE", ""
    ready, why = _ask(internal)
    fake.issuer = "https://sandbox.orcid.org"
    assert ready is False and "no ORCID address" in why


def test_a_realm_that_cannot_be_asked_claims_nothing(realm):
    internal, _ = realm
    assert _ask(internal, redirect="https://not-registered.example/") == (None, "")
    assert _ask("http://127.0.0.1:9/auth/realms/em-dev") == (None, "")


def test_the_judge_alone():
    ok = "https://orcid.org/oauth/authorize?client_id=APP-0123456789ABCDEF&x=1"
    assert probe.judge_idp_redirect(ok, "orcid") == (True, "")
    assert probe.judge_idp_redirect("https://orcid.org/oauth/authorize?client_id=", "orcid")[0] is False
    assert probe.judge_idp_redirect("/oauth/authorize?client_id=APP-0123456789ABCDEF", "orcid")[0] is False


def test_auth_config_carries_the_verdict(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main.authenticator.settings, "issuer", "https://kc.example/realms/x", raising=False)
    monkeypatch.setattr(main, "_orcid_idp_verdict", lambda issuer, client, alias: (False, "the realm's «orcid» provider has no ORCID client (client id: none)"))
    body = TestClient(main.app).get("/v1/auth-config").json()
    assert body["orcid_idp"] == "orcid"
    assert body["orcid_idp_ready"] is False
    assert "no ORCID client" in body["orcid_idp_why"]


def test_the_probe_is_cached_a_minute():
    calls = []
    clock = [100.0]
    run = lambda: calls.append(1) or (True, "")  # noqa: E731
    probe._CACHE.clear()
    probe.cached_probe("k", run, now=lambda: clock[0])
    clock[0] += 30
    probe.cached_probe("k", run, now=lambda: clock[0])
    clock[0] += 31
    probe.cached_probe("k", run, now=lambda: clock[0])
    assert len(calls) == 2
