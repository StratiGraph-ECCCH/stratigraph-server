"""The node's own Keycloak, spoken to as an administrator — for the console.

What `dev-stack/accredit.sh` and `dev-stack/offline-password.sh` did from a
terminal, the node console now does from a page (E.D., 30 October 2026): add a
person by ORCID, give them a password for the field, set a new one when it is
forgotten. The same rules, moved, not loosened:

* **one user per ORCID**, username = the iD, attribute `orcid` = the iD;
* **a password only for an iD ORCID verified once**: the user must be linked to
  the realm's ORCID identity provider (`EM_ORCID_IDP_ALIAS`, default `orcid`).
  The node attests only what was verified. The one exception is a **test
  person** on a node that allows them (`people.test_people_allowed`);
* **the password is temporary**: the person changes it at the first sign-in;
* **the password is never logged** and never returned.

How the server authenticates to Keycloak, in order of preference:

1. a confidential client with a service account (`EM_KC_ADMIN_CLIENT_ID`,
   `EM_KC_ADMIN_CLIENT_SECRET`), token from the node's realm — the production
   shape: give the service account `realm-management` → `manage-users`;
2. an admin user of the master realm (`EM_KC_ADMIN_USER`,
   `EM_KC_ADMIN_PASSWORD`) through `admin-cli` — the dev stack's shape.

Where (`EM_KC_ADMIN_URL`, e.g. `http://keycloak:8080/auth`, and `EM_KC_REALM`).
Not configured → `configured()` is False, and every caller says so instead of
pretending: the console shows «Keycloak not reachable from the server» and the
scripts still work.

Standard library only (urllib), like `accredited.py`: one more dependency for
four HTTP calls would be a bad trade.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


class KeycloakError(RuntimeError):
    """Keycloak answered, and not what was needed. Carries the HTTP status."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _env(environ: Optional[Dict[str, str]]) -> Dict[str, str]:
    return environ if environ is not None else os.environ  # type: ignore[return-value]


class KeycloakAdmin:
    def __init__(self, environ: Optional[Dict[str, str]] = None, *, opener=None) -> None:
        env = _env(environ)
        self.base = (env.get("EM_KC_ADMIN_URL") or "").rstrip("/")
        self.realm = env.get("EM_KC_REALM") or ""
        self.client_id = env.get("EM_KC_ADMIN_CLIENT_ID") or ""
        self.client_secret = env.get("EM_KC_ADMIN_CLIENT_SECRET") or ""
        self.admin_user = env.get("EM_KC_ADMIN_USER") or ""
        self.admin_password = env.get("EM_KC_ADMIN_PASSWORD") or ""
        self.orcid_idp = env.get("EM_ORCID_IDP_ALIAS") or "orcid"
        self._open = opener or urllib.request.urlopen
        self._token: Optional[str] = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def configured(self) -> bool:
        has_auth = bool(self.client_id and self.client_secret) or bool(self.admin_user and self.admin_password)
        return bool(self.base and self.realm and has_auth)

    def describe(self) -> str:
        if not self.configured():
            return "not configured (EM_KC_ADMIN_URL, EM_KC_REALM and credentials)"
        how = "service account" if self.client_id else "master admin"
        return f"{self.base} realm {self.realm} ({how})"

    def _request(self, method: str, url: str, *, form: Optional[Dict[str, str]] = None,
                 body: Any = None, token: Optional[str] = None) -> Tuple[int, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._open(req, timeout=8) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            status = exc.code
        except (urllib.error.URLError, OSError) as exc:
            raise KeycloakError(f"Keycloak is not reachable at {self.base}: {exc}") from None
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        return status, payload

    def _login(self) -> str:
        if self._token:
            return self._token
        if self.client_id and self.client_secret:
            url = f"{self.base}/realms/{self.realm}/protocol/openid-connect/token"
            form = {"grant_type": "client_credentials", "client_id": self.client_id,
                    "client_secret": self.client_secret}
        else:
            url = f"{self.base}/realms/master/protocol/openid-connect/token"
            form = {"grant_type": "password", "client_id": "admin-cli",
                    "username": self.admin_user, "password": self.admin_password}
        status, payload = self._request("POST", url, form=form)
        token = (payload or {}).get("access_token") if status == 200 else None
        if not token:
            raise KeycloakError(f"no admin token from Keycloak (HTTP {status})", status)
        self._token = token
        return token

    def _api(self, method: str, path: str, body: Any = None) -> Tuple[int, Any]:
        url = f"{self.base}/admin/realms/{self.realm}{path}"
        return self._request(method, url, body=body, token=self._login())

    # ── users ────────────────────────────────────────────────────────────────

    def user(self, orcid: str) -> Optional[Dict[str, Any]]:
        """The Keycloak user whose username is exactly this iD, or None."""
        q = urllib.parse.quote(orcid.lower())
        status, payload = self._api("GET", f"/users?exact=true&username={q}")
        if status != 200:
            raise KeycloakError(f"reading users failed (HTTP {status})", status)
        for u in payload or []:
            if str(u.get("username", "")).lower() == orcid.lower():
                return u
        return None

    def linked_to_orcid(self, user_id: str) -> bool:
        status, payload = self._api("GET", f"/users/{user_id}/federated-identity")
        if status != 200:
            raise KeycloakError(f"reading identity links failed (HTTP {status})", status)
        return any(link.get("identityProvider") == self.orcid_idp for link in payload or [])

    def has_password(self, user_id: str) -> bool:
        status, payload = self._api("GET", f"/users/{user_id}/credentials")
        if status != 200:
            return False
        return any(c.get("type") == "password" for c in payload or [])

    def ensure_user(self, orcid: str, name: str = "", *, test: bool = False) -> Dict[str, Any]:
        """Create the user for this iD, or bring its name up to date.
        → `{"id", "created": bool}`. One user per ORCID: an iD already carried by
        another username is refused, as `accredit.sh` refuses it."""
        first, _, last = (name or "").strip().partition(" ")
        body = {"username": orcid, "enabled": True, "firstName": first, "lastName": last,
                "attributes": {"orcid": [orcid], **({"em_test": ["true"]} if test else {})}}
        existing = self.user(orcid)
        if existing is None:
            status, payload = self._api(
                "GET", f"/users?q=orcid:{urllib.parse.quote(orcid)}&exact=true")
            others = [u.get("username") for u in (payload or []) if status == 200]
            if others:
                raise KeycloakError(f"{orcid} is already carried by the user «{others[0]}»: "
                                    "one user per ORCID", 409)
            status, _ = self._api("POST", "/users", body)
            if status != 201:
                raise KeycloakError(f"creating the user for {orcid} failed (HTTP {status})", status)
            created = self.user(orcid)
            return {"id": (created or {}).get("id"), "created": True}
        status, _ = self._api("PUT", f"/users/{existing['id']}", {**existing, **body})
        if status not in (200, 204):
            raise KeycloakError(f"updating the user for {orcid} failed (HTTP {status})", status)
        return {"id": existing["id"], "created": False}

    def set_enabled(self, orcid: str, enabled: bool) -> bool:
        existing = self.user(orcid)
        if existing is None:
            return False
        status, _ = self._api("PUT", f"/users/{existing['id']}", {**existing, "enabled": enabled})
        if status not in (200, 204):
            raise KeycloakError(f"changing access for {orcid} failed (HTTP {status})", status)
        return True

    def set_password(self, user_id: str, password: str, *, temporary: bool = True) -> None:
        status, payload = self._api("PUT", f"/users/{user_id}/reset-password",
                                    {"type": "password", "temporary": bool(temporary),
                                     "value": password})
        if status != 204:
            why = (payload or {}).get("error_description") or (payload or {}).get("errorMessage") or ""
            raise KeycloakError("Keycloak refused the password"
                                + (f": {why}" if why else " (the realm's password policy may want more)"),
                                status)

    def facts(self, orcid: str) -> Dict[str, Any]:
        """What the console shows beside a person: exists, enabled, linked to
        ORCID, has a password. Never raises — an unreadable fact is None."""
        out: Dict[str, Any] = {"exists": None, "enabled": None, "orcid_linked": None,
                               "password": None}
        try:
            u = self.user(orcid)
            out["exists"] = u is not None
            if u is not None:
                out["enabled"] = bool(u.get("enabled"))
                out["orcid_linked"] = self.linked_to_orcid(u["id"])
                out["password"] = self.has_password(u["id"])
        except KeycloakError:
            pass
        return out


def admin(environ: Optional[Dict[str, str]] = None) -> KeycloakAdmin:
    return KeycloakAdmin(environ)


MIN_PASSWORD = 8


def password_problem(password: Optional[str]) -> Optional[str]:
    if not password or len(password) < MIN_PASSWORD:
        return f"a password of at least {MIN_PASSWORD} characters"
    return None


def users_for(orcids: List[str], kc: KeycloakAdmin) -> Dict[str, Dict[str, Any]]:
    """`facts` for several iDs, one admin login."""
    return {o: kc.facts(o) for o in orcids}
