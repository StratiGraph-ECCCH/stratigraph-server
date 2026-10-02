"""Does the realm's ORCID identity provider have an ORCID client? — measured.

`/v1/auth-config` names the alias (`orcid_idp`) and EMStudio offers «Sign in to
StratiGraph with ORCID» on it. Until 3 October 2026 nothing said whether that
provider could work: on the dev stack `.env.dev` leaves `ORCID_CLIENT_ID` empty,
the compose fills in `orcid-client-not-registered`, and the button sent the
person to ORCID to be told «invalid client». An offer that fails is worse than
no offer: the panel must say WHY the way is closed.

The answer is MEASURED, not configured: the realm belongs to whoever runs the
Keycloak (on an institutional node, somebody else), so the server cannot know
the provider's credentials — it can only ask the realm what a browser would get.
It starts the same round trip a browser starts (`kc_idp_hint=<alias>`), follows
Keycloak's two redirects without following the last one, and reads the
`client_id` Keycloak is about to send to ORCID. An ORCID client id has one shape,
`APP-` and sixteen characters (the Public API's, sandbox and production alike);
anything else is a provider with no client.

Three answers, never two: `True` (a client is there — whether ORCID ANSWERS is
the caller's to measure, since that is what fails on the field), `False` with
the reason, and `None` when the realm could not be asked (no issuer, the probe's
redirect not registered, the realm not reachable) — then nothing is claimed and
the way is offered as before.

No secret is read and none could be: the secret never leaves Keycloak.
"""
from __future__ import annotations

import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple

ORCID_CLIENT_ID = re.compile(r"^APP-[A-Z0-9]{16}$")

Verdict = Tuple[Optional[bool], str]


def judge_idp_redirect(location: str, alias: str) -> Verdict:
    """Keycloak's redirect towards the provider → ready, or why not."""
    parts = urllib.parse.urlsplit(location)
    if not parts.scheme.startswith("http") or not parts.netloc:
        return False, (f"the realm's «{alias}» provider has no ORCID address "
                       f"(it sends the browser to {location!r})")
    client = urllib.parse.parse_qs(parts.query).get("client_id", [""])[0]
    if not ORCID_CLIENT_ID.match(client):
        shown = client or "none"
        return False, (f"the realm's «{alias}» provider has no ORCID client "
                       f"(client id: {shown})")
    return True, ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())


def _location(opener: urllib.request.OpenerDirector, url: str, timeout: float) -> Optional[str]:
    try:
        with opener.open(url, timeout=timeout):
            return None                       # a 200: a page, not a redirect
    except urllib.error.HTTPError as answer:
        if answer.code in (301, 302, 303, 307, 308):
            return answer.headers.get("Location")
        return None


def probe_orcid_idp(*, authorization_endpoint: str, client_id: str, redirect_uri: str,
                    alias: str, public_prefix: str = "", internal_prefix: str = "",
                    opener_factory: Callable[[], urllib.request.OpenerDirector] = _opener,
                    timeout: float = 3.0) -> Verdict:
    """Ask the realm what a browser would get on the way to ORCID.

    `public_prefix` → `internal_prefix` rewrites the realm's own addresses for a
    server that reaches Keycloak by another name (the dev stack: the issuer is
    `https://em.localhost:8443/auth/realms/em-dev`, the container reaches
    `http://keycloak:8080/auth/realms/em-dev`).
    """
    if not (authorization_endpoint and client_id and redirect_uri and alias):
        return None, ""

    def inside(url: str) -> str:
        if public_prefix and internal_prefix and url.startswith(public_prefix):
            return internal_prefix + url[len(public_prefix):]
        return url

    query = urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "scope": "openid",
        "redirect_uri": redirect_uri, "state": "orcid-idp-probe",
        # a challenge for a verifier nobody holds: the round trip can never end
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256", "kc_idp_hint": alias,
    })
    opener = opener_factory()
    try:
        first = _location(opener, inside(f"{authorization_endpoint}?{query}"), timeout)
        if not first or f"/broker/{alias}/" not in first:
            return None, ""                   # no broker hop: nothing to judge
        second = _location(opener, inside(urllib.parse.urljoin(authorization_endpoint, first)), timeout)
    except (urllib.error.URLError, OSError, ValueError):
        return None, ""
    if second is None:
        return None, ""
    return judge_idp_redirect(second, alias)


_CACHE: dict = {}
_TTL = 60.0


def cached_probe(key: str, run: Callable[[], Verdict], now: Callable[[], float] = time.monotonic) -> Verdict:
    """One probe a minute per realm: `/v1/auth-config` is read by every panel."""
    hit = _CACHE.get(key)
    if hit and now() - hit[0] < _TTL:
        return hit[1]
    verdict = run()
    _CACHE[key] = (now(), verdict)
    return verdict
