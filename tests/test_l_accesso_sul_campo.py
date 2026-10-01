"""L'accesso sul campo: un utente è un ORCID, e offline il nodo fa da garante.

Decisione di E.D., 1 ottobre 2026. Con internet si entra con ORCID (identità
*verificata da ORCID*); senza, con l'iD e una password del nodo (identità
*attestata dal nodo*). Nessuno ha la password se non è entrato prima una volta
con ORCID vero, e nessuno entra con ORCID se il responsabile non l'ha accreditato.

Le prove, nell'ordine in cui la cosa succede:

* **la lista** (`app/accredited.py`): letta in un modo solo, rifiutata con la riga
  quando è scritta male — una lista di chi entra non si legge «più o meno»;
* **il realm**: l'IdP ORCID senza segreti nel file, il primo accesso che COLLEGA e
  non crea (così un iD non accreditato è rifiutato), e i due claim che dicono il
  modo d'accesso. Misurati dal vero su Keycloak 24.0.4 in un container usa e
  getta: il referto C della dev27;
* **`/v1/whoami`** con i due modi, con token finti come gli altri test;
* **gli script** contro un'API di amministrazione finta: `offline-password.sh`
  rifiuta un utente mai entrato con ORCID, e la password non esce mai.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

import pytest

from app import accredited as acc
from app import main as main_module
from app.identity import auth_mode_of
from tests.test_chi_ce_e_chi_non_ce_piu import client  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parent.parent
DEV = REPO / "dev-stack"
REALM = json.loads((DEV / "keycloak" / "realm-em-dev.json").read_text(encoding="utf-8"))

A = "0000-0003-4444-444X"          # accreditata (cifra di controllo X)
B = "0000-0003-5555-5559"          # mai accreditata


# ── la lista ─────────────────────────────────────────────────────────────────

def test_la_lista_si_legge_e_normalizza_l_iD():
    entries = acc.parse(
        "# commento\naccredited:\n"
        f"  - orcid: https://orcid.org/{A.lower()}\n    name: Persona A\n"
        "  - orcid: '0000-0002-1825-0097'   \n    name: \"Dev User\"\n")
    assert entries == [{"orcid": A, "name": "Persona A"},
                       {"orcid": "0000-0002-1825-0097", "name": "Dev User"}]


@pytest.mark.parametrize("text,piece", [
    ("people:\n  - orcid: 0000-0002-1825-0097\n", "line 1"),
    ("accredited:\n  - orcid: 0000-0002-1825-0098\n", "check digit"),
    ("accredited:\n  - orcid: 0000-0002-1825-0097\n    mail: x@y\n", "line 3"),
    ("accredited:\n  - orcid: 0000-0002-1825-0097\n  - orcid: 0000-0002-1825-0097\n",
     "already entry 1"),
    ("accredited:\n  - name: Senza iD\n", "no `orcid:`"),
])
def test_una_lista_scritta_male_e_rifiutata_con_la_ragione(text, piece):
    with pytest.raises(acc.AccreditedListError) as err:
        acc.parse(text)
    assert piece in str(err.value)


def test_la_lista_del_dev_stack_si_legge():
    ids = [e["orcid"] for e in acc.load(str(DEV / "accredited.yaml"))]
    assert "0000-0002-1825-0097" in ids and B not in ids


def test_senza_lista_nessuno_e_accreditato_e_non_il_contrario(tmp_path):
    assert acc.is_accredited(A, {}) is False
    f = tmp_path / "a.yaml"
    f.write_text(f"accredited:\n  - orcid: {A}\n", encoding="utf-8")
    env = {acc.ENV_FILE: str(f)}
    assert acc.is_accredited(A.lower(), env) is True
    assert acc.is_accredited(f"https://orcid.org/{A}", env) is True
    assert acc.is_accredited(B, env) is False


# ── il realm ─────────────────────────────────────────────────────────────────

def _idp() -> Dict[str, Any]:
    (orcid,) = [p for p in REALM.get("identityProviders", []) if p["alias"] == "orcid"]
    return orcid


def test_il_realm_ha_l_IdP_ORCID_senza_segreti_nel_file():
    idp = _idp()
    cfg = idp["config"]
    assert idp["providerId"] == "oidc" and idp["enabled"] is True
    assert cfg["clientId"] == "${ORCID_CLIENT_ID}"
    assert cfg["clientSecret"] == "${ORCID_CLIENT_SECRET}"
    assert cfg["issuer"] == "${ORCID_ISSUER}"
    assert cfg["tokenUrl"] == "${ORCID_ISSUER}/oauth/token"
    assert cfg["defaultScope"] == "openid"
    #: l'iD diventa nome utente e attributo `orcid`
    mappers = {m["identityProviderMapper"]: m["config"]
               for m in REALM["identityProviderMappers"]
               if m["identityProviderAlias"] == "orcid"}
    assert mappers["oidc-username-idp-mapper"]["template"] == "${CLAIM.sub}"
    assert mappers["oidc-user-attribute-idp-mapper"]["claim"] == "sub"
    assert mappers["oidc-user-attribute-idp-mapper"]["user.attribute"] == "orcid"


def test_un_iD_non_accreditato_e_rifiutato_alla_porta():
    """Il primo accesso COLLEGA un utente che esiste e non ne CREA nessuno: chi non
    è stato accreditato (nessun utente) si ferma, con la ragione. Misurato dal
    vero: «The ORCID iD 0000-0003-5555-5559 is not accredited on this node…»."""
    flow_alias = _idp()["firstBrokerLoginFlowAlias"]
    (flow,) = [f for f in REALM["authenticationFlows"] if f["alias"] == flow_alias]
    steps = [(e["authenticator"], e["requirement"])
             for e in flow["authenticationExecutions"]]
    assert steps == [("idp-detect-existing-broker-user", "REQUIRED"),
                     ("idp-auto-link", "REQUIRED")]
    assert REALM["registrationAllowed"] is False
    message = REALM["localizationTexts"]["en"]["federatedIdentityUnavailableMessage"]
    assert "not accredited" in message and "{0}" in message


def test_il_profilo_dichiara_orcid_perche_l_API_altrimenti_lo_butta():
    (component,) = REALM["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(component["config"]["kc.user.profile.config"][0])
    attrs = {a["name"]: a for a in profile["attributes"]}
    assert attrs["orcid"]["permissions"]["edit"] == ["admin"]
    #: nessun campo obbligatorio che fermi l'accesso al «completa il profilo»
    assert not any("required" in a for a in attrs.values())


def test_ogni_client_che_porta_l_orcid_dice_anche_il_modo():
    for c in REALM["clients"]:
        names = {m["name"]: m for m in c.get("protocolMappers", [])}
        if "orcid" not in names:
            continue
        assert names["em-idp"]["config"]["user.session.note"] == "identity_provider"
        assert names["em-idp"]["config"]["claim.name"] == "em_idp"
        assert names["em-auth-reported"]["config"]["claim.name"] == "em_auth_reported"
        assert names["em-auth-reported"]["config"]["claim.value"] == "true"


def test_il_compose_passa_le_credenziali_dall_ambiente():
    text = (DEV / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert 'ORCID_CLIENT_ID: "${ORCID_CLIENT_ID:-orcid-client-not-registered}"' in text
    assert 'ORCID_CLIENT_SECRET: "${ORCID_CLIENT_SECRET:-orcid-secret-not-set}"' in text
    assert "./accredited.yaml:/srv/em-node/accredited.yaml:ro" in text
    assert 'EM_ACCREDITED_FILE: "/srv/em-node/accredited.yaml"' in text


# ── il modo d'accesso, dai claim ─────────────────────────────────────────────

@pytest.mark.parametrize("claims,mode", [
    ({"em_idp": "orcid", "em_auth_reported": True}, "orcid"),
    ({"em_auth_reported": True, "preferred_username": A.lower()}, "node_password"),
    ({"em_auth_reported": "true"}, "node_password"),
    #: un realm che non lo dice: non si indovina
    ({"preferred_username": "dev"}, None),
    #: un altro fornitore d'identità non è nessuno dei due modi
    ({"em_idp": "idem-saml", "em_auth_reported": True}, None),
    #: una macchina, non una persona con una password
    ({"em_auth_reported": True, "preferred_username": "service-account-em-server"}, None),
    #: un claim esplicito vince
    ({"em_auth": "orcid", "em_auth_reported": True}, "orcid"),
    ({}, None), (None, None),
])
def test_il_modo_d_accesso(claims, mode):
    assert auth_mode_of(claims) == mode


# ── /v1/whoami ───────────────────────────────────────────────────────────────

@pytest.fixture
def campo(monkeypatch, tmp_path):
    lista = tmp_path / "accredited.yaml"
    lista.write_text(f"accredited:\n  - orcid: {A}\n    name: Persona A\n",
                     encoding="utf-8")
    monkeypatch.setenv("EM_ACCREDITED_FILE", str(lista))
    monkeypatch.setenv("EM_NODE_NAME", "fcn-prova")

    class Enforcing:
        enforcing = True
        issuer = "https://fcn.local:8443/auth/realms/em-dev"

        def describe(self):
            return "keycloak"

    monkeypatch.setattr(main_module.authenticator, "settings", Enforcing())

    def con(claims):
        monkeypatch.setattr(main_module.authenticator, "require_token",
                            lambda request: dict(claims))
    return con


def test_whoami_con_ORCID(campo, client):  # noqa: F811
    campo({"orcid": A, "name": "Persona A", "em_idp": "orcid", "em_auth_reported": True})
    assert client.get("/v1/whoami").json() == {
        "orcid": A, "name": "Persona A", "enforcing": True,
        "auth_mode": "orcid", "attested_by": None, "accredited": True}


def test_whoami_con_la_password_del_nodo(campo, client):  # noqa: F811
    campo({"orcid": A, "name": "Persona A", "em_auth_reported": True})
    assert client.get("/v1/whoami").json() == {
        "orcid": A, "name": "Persona A", "enforcing": True,
        "auth_mode": "node_password", "attested_by": "fcn-prova", "accredited": True}


def test_il_garante_senza_nome_e_l_autorita_dell_indirizzo_pubblico(
        campo, client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("EM_NODE_NAME")
    monkeypatch.setenv("EM_PUBLIC_BASE", "https://fcn.local:8443/em")
    campo({"orcid": A, "em_auth_reported": True})
    assert client.get("/v1/whoami").json()["attested_by"] == "fcn.local:8443"
    monkeypatch.delenv("EM_PUBLIC_BASE")
    monkeypatch.delenv("EM_SERVER_PUBLIC_URL", raising=False)
    assert client.get("/v1/whoami").json()["attested_by"] is None


def test_un_iD_non_accreditato_lo_dice(campo, client):  # noqa: F811
    campo({"orcid": B, "em_idp": "orcid", "em_auth_reported": True})
    body = client.get("/v1/whoami").json()
    assert (body["auth_mode"], body["accredited"]) == ("orcid", False)


def test_un_realm_che_non_dice_il_modo_resta_null(campo, client):  # noqa: F811
    campo({"orcid": A})
    body = client.get("/v1/whoami").json()
    assert (body["auth_mode"], body["attested_by"]) == (None, None)


def test_una_lista_illeggibile_e_un_guasto_non_un_no(campo, client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EM_ACCREDITED_FILE", "/nonexistent/accredited.yaml")
    campo({"orcid": A, "em_auth_reported": True})
    answer = client.get("/v1/whoami")
    assert answer.status_code == 503 and "accredited list" in answer.json()["detail"]


def test_auth_config_dice_l_alias_ORCID_e_il_nome_del_nodo(campo, client):  # noqa: F811
    body = client.get("/v1/auth-config").json()
    assert (body["orcid_idp"], body["node_name"]) == ("orcid", "fcn-prova")


# ── gli script, contro un'API di amministrazione finta ───────────────────────

class FakeKeycloak:
    """Quanto basta dell'API di amministrazione: token, utenti, collegamenti."""

    def __init__(self):
        self.users: Dict[str, Dict[str, Any]] = {}
        self.links: Dict[str, List[Dict[str, str]]] = {}
        self.calls: List[tuple] = []
        self.bodies: List[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode() if n else ""
                fake.bodies.append(raw)
                return raw

            def do_POST(self):
                fake.calls.append(("POST", self.path))
                raw = self._body()
                if self.path.endswith("/protocol/openid-connect/token"):
                    return self._send(200, {"access_token": "fake-admin-token"})
                if self.path == "/admin/realms/em-dev/users":
                    user = json.loads(raw)
                    uid = f"id-{len(fake.users) + 1}"
                    fake.users[uid] = {**user, "id": uid,
                                       "username": user["username"].lower()}
                    return self._send(201)
                self._send(404)

            def do_PUT(self):
                fake.calls.append(("PUT", self.path))
                raw = self._body()
                parts = self.path.split("/")
                if self.path.endswith("/reset-password"):
                    fake.password_body = json.loads(raw)
                    return self._send(204)
                fake.users[parts[-1]].update(json.loads(raw))
                return self._send(204)

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                assert self.headers["Authorization"] == "Bearer fake-admin-token"
                from urllib.parse import parse_qs, urlparse
                url = urlparse(self.path)
                q = parse_qs(url.query)
                if url.path == "/admin/realms/em-dev/users":
                    if "username" in q:
                        want = q["username"][0].lower()
                        return self._send(200, [u for u in fake.users.values()
                                                if u["username"] == want])
                    if "q" in q:
                        key, _, value = q["q"][0].partition(":")
                        return self._send(200, [
                            u for u in fake.users.values()
                            if value in (u.get("attributes") or {}).get(key, [])])
                if url.path.endswith("/federated-identity"):
                    return self._send(200, fake.links.get(url.path.split("/")[-2], []))
                if url.path.startswith("/admin/realms/em-dev/users/"):
                    return self._send(200, fake.users[url.path.split("/")[-1]])
                self._send(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add(self, username, orcid, *, linked=False):
        uid = f"id-{len(self.users) + 1}"
        self.users[uid] = {"id": uid, "username": username.lower(),
                           "attributes": {"orcid": [orcid]}}
        if linked:
            self.links[uid] = [{"identityProvider": "orcid", "userId": "x",
                                "userName": "x"}]
        return uid


@pytest.fixture
def kc():
    fake = FakeKeycloak()
    yield fake
    fake.server.shutdown()


def _run(script, *args, kc, stdin=""):
    env = {**os.environ, "KC_URL": fake_url(kc), "KEYCLOAK_ADMIN": "admin",
           "KEYCLOAK_ADMIN_PASSWORD": "admin-pw-not-to-print", "DEV_REALM": "em-dev"}
    return subprocess.run(["bash", str(DEV / script), *args], input=stdin,
                          capture_output=True, text=True, env=env, timeout=60)


def fake_url(kc):
    return kc.url


needs_tools = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("curl")),
                                 reason="bash and curl run the dev-stack scripts")


@needs_tools
def test_offline_password_rifiuta_chi_non_e_mai_entrato_con_ORCID(kc):
    kc.add(A, A, linked=False)
    done = _run("offline-password.sh", A, kc=kc, stdin="Campo-1234\nCampo-1234\n")
    assert done.returncode == 4, done.stderr
    assert "never signed in with ORCID" in done.stderr
    assert not [c for c in kc.calls if c[1].endswith("/reset-password")]


@needs_tools
def test_offline_password_rifiuta_un_iD_senza_utente(kc):
    done = _run("offline-password.sh", B, kc=kc, stdin="Campo-1234\nCampo-1234\n")
    assert done.returncode == 3 and "not accredited" in done.stderr
    assert not [c for c in kc.calls if c[0] == "PUT"]


@needs_tools
def test_offline_password_rifiuta_un_iD_scritto_male_senza_chiamare(kc):
    done = _run("offline-password.sh", "0000-0003-5555-5558", kc=kc)
    assert done.returncode == 2 and kc.calls == []


@needs_tools
def test_offline_password_per_chi_e_collegato_temporanea_e_mai_stampata(kc):
    kc.add(A, A, linked=True)
    done = _run("offline-password.sh", A, kc=kc, stdin="Campo-1234\nCampo-1234\n")
    assert done.returncode == 0, done.stderr
    assert kc.password_body == {"type": "password", "temporary": True,
                                "value": "Campo-1234"}
    for secret in ("Campo-1234", "admin-pw-not-to-print", "fake-admin-token"):
        assert secret not in done.stdout + done.stderr


@needs_tools
def test_offline_password_due_voci_diverse_non_cambiano_niente(kc):
    kc.add(A, A, linked=True)
    done = _run("offline-password.sh", A, kc=kc, stdin="Campo-1234\nCampo-9999\n")
    assert done.returncode == 2 and "differ" in done.stderr
    assert not [c for c in kc.calls if c[1].endswith("/reset-password")]


@needs_tools
def test_accredit_crea_aggiorna_e_non_raddoppia(kc, tmp_path):
    kc.add("dev", "0000-0002-1825-0097")
    lista = tmp_path / "a.yaml"
    lista.write_text(f"accredited:\n  - orcid: {A}\n    name: Persona Accreditata\n"
                     "  - orcid: 0000-0002-1825-0097\n    name: Dev User\n",
                     encoding="utf-8")
    first = _run("accredit.sh", str(lista), kc=kc)
    assert first.returncode == 0, first.stderr
    assert "1 created" in first.stdout and "already carried by user «dev»" in first.stdout
    (made,) = [u for u in kc.users.values() if u["username"] == A.lower()]
    assert made["attributes"] == {"orcid": [A]}
    assert (made["firstName"], made["lastName"]) == ("Persona", "Accreditata")
    again = _run("accredit.sh", str(lista), kc=kc)
    assert "0 created" in again.stdout and "1 unchanged" in again.stdout
    assert "admin-pw-not-to-print" not in first.stdout + first.stderr


@needs_tools
def test_accredit_con_una_lista_sbagliata_non_tocca_keycloak(kc, tmp_path):
    lista = tmp_path / "a.yaml"
    lista.write_text("accredited:\n  - orcid: 0000-0003-5555-5558\n", encoding="utf-8")
    done = _run("accredit.sh", str(lista), kc=kc)
    assert done.returncode == 2 and "check digit" in done.stderr
    assert kc.calls == []
