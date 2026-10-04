"""Q11 · EM Tools in Blender signs in to the dev node — the realm's half.

Measured on 4 October 2026: Blender's sign-in opened the browser with the
browser client `em-console` and a loopback return, `http://127.0.0.1:<port>/`,
and Keycloak answered «Invalid parameter: redirect_uri» — `em-console` admits
pages, not the loopback. Blender meanwhile waited on its UI thread.

The rule that works, MEASURED on this image (Keycloak 24.0.4, a throwaway
container with five clients): a redirect URI registered as `http://127.0.0.1/`
admits `http://127.0.0.1:54321/` (the port on the loopback is ignored, RFC 8252
§7.3), keeps the PATH exact (`/other` refused), and `http://[::1]/*` does NOT
admit `[::1]:54321`. A URI with a port (`:8000/*`) admits that port only.
"""

from __future__ import annotations

import json
import pathlib

from app import main as main_module

_REPO = pathlib.Path(__file__).resolve().parent.parent
REALM = json.loads((_REPO / "dev-stack" / "keycloak" / "realm-em-dev.json")
                   .read_text(encoding="utf-8"))
COMPOSE = (_REPO / "dev-stack" / "docker-compose.dev.yml").read_text(encoding="utf-8")


def _client(cid):
    return next(c for c in REALM["clients"] if c["clientId"] == cid)


def test_the_native_client_is_public_pkce_and_returns_only_to_the_loopback():
    tools = _client("em-tools")
    assert tools["publicClient"] is True and tools["standardFlowEnabled"] is True
    assert tools["attributes"]["pkce.code.challenge.method"] == "S256"
    assert tools["directAccessGrantsEnabled"] is False
    assert tools["implicitFlowEnabled"] is False
    # exactly the loopback, no port (any port is admitted), no wildcard path
    assert tools["redirectUris"] == ["http://127.0.0.1/"]
    assert tools["webOrigins"] == []        # no page: no CORS


def test_its_token_is_the_same_token_as_the_consoles_for_the_node():
    """Same audience, same identity claims: the node cannot tell which door."""
    names = lambda c: sorted(m["name"] for m in c["protocolMappers"])  # noqa: E731
    assert names(_client("em-tools")) == names(_client("em-console"))


def test_the_loopback_stays_off_the_browser_client():
    assert not any(u.startswith("http://127.0.0.1/")
                   for u in _client("em-console")["redirectUris"])


def test_the_dev_node_names_it(monkeypatch):
    assert 'EM_NATIVE_CLIENT_ID: "${EM_NATIVE_CLIENT_ID:-em-tools}"' in COMPOSE

    from fastapi.testclient import TestClient

    class Enforcing:
        enforcing = True
        issuer = "https://sso.example.org/realms/em"

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())
    monkeypatch.setenv("EM_ORCID_IDP_PROBE", "0")
    client = TestClient(main_module.app)
    monkeypatch.delenv("EM_NATIVE_CLIENT_ID", raising=False)
    assert client.get("/v1/auth-config").json()["native_client_id"] == ""
    monkeypatch.setenv("EM_NATIVE_CLIENT_ID", "em-tools")
    answer = client.get("/v1/auth-config").json()
    assert answer["native_client_id"] == "em-tools"
    assert answer["client_id"] == "em-console"      # the pages' client unchanged
