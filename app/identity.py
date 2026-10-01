"""WHO is speaking, out of a verified token — one order, decided here.

The author of every operation, the owner of every room, the operator of the
node: all of them are "the identity on the caller's token". Until 2026-09-28
that was spelled out by hand in eleven places of this service, not always the
same way (`ws.py` read `orcid, ORCID, preferred_username, sub`; the HTTP
endpoints `orcid, preferred_username, sub`), and StratiField read a third list
(`orcid, orcid_id, https://orcid.org/id, preferred_username, sub`). With the
ORCID only in `orcid_id` — a realm is free to broker it there — StratiField
stamped the ORCID and the room stamped the username: **two authors for one
person**, which the merge algebra treats as two people.

**The server decides.** The order is the union of the lists, ORCID first:

1. ``orcid``, ``ORCID``, ``orcid_id``, ``https://orcid.org/id`` — the spellings
   a realm that brokers ORCID may use (in this ecosystem the ORCID iD *is* the
   identity: AUDIT1/ORCID batch);
2. ``preferred_username`` — the realm's name for the account;
3. ``sub`` — the account's subject, stable only *inside one realm* (see
   docs/SYNC-FIELD-TO-CLOUD.md §2.5 for the trap this is).

The first claim that speaks decides: a string is taken stripped, an empty or
blank one is silence. Dev mode is NOT handled here — a caller in dev mode has
no identity, and each caller says so before asking (``None``, never an
invented somebody). StratiField carries the same tuple
(``stratigraph-chatbot/app/auth.py::ORCID_CLAIMS``) and a test there compares it
with this one, byte for byte.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

#: THE order. Change it here and nowhere else; StratiField's test will then say
#: that its copy is stale.
IDENTITY_CLAIMS: Tuple[str, ...] = (
    "orcid", "ORCID", "orcid_id", "https://orcid.org/id",
    "preferred_username", "sub",
)


def identity_of(claims: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The identity in ``claims``, read in :data:`IDENTITY_CLAIMS` order."""
    for key in IDENTITY_CLAIMS:
        value = (claims or {}).get(key)
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        elif value:
            return str(value)
    return None


# ── HOW the caller signed in: ORCID, or the node's password ──────────────────
#
# «L'accesso sul campo» (E.D., 1 October 2026): with internet a person signs in
# with ORCID and the identity is *verified by ORCID*; without it, with the iD
# and a password the node gave them, and the identity is *attested by the node*.
# A signature must say which, so the token must say which.
#
# MEASURED on Keycloak 24.0.4 (the dev stack's image), 1 October 2026:
#   · `oidc-amr-mapper` exists, but `amr` came out `[]` for BOTH a password login
#     and a brokered ORCID login: its values come from per-authenticator
#     «reference» configuration that no default flow carries. Not usable as is;
#   · a brokered login leaves the user-session note `identity_provider` = the
#     IdP alias (`orcid`); a password login leaves none. The realm copies it into
#     the claim `em_idp` (`oidc-usersessionmodel-note-mapper`);
#   · absence is not evidence on its own — a realm WITHOUT that mapper also has
#     no `em_idp`. So the realm adds a hard-coded `em_auth_reported: true`
#     (`oidc-hardcoded-claim-mapper`): with it, «no IdP» means «the node's
#     password»; without it, the mode is unknown (`None`), never guessed.
#
# An explicit `em_auth` claim, if a realm ever writes one (a script mapper on
# the institutional Keycloak, say), wins over both.

AUTH_MODES: Tuple[str, ...] = ("orcid", "node_password")
#: the identity-provider aliases that ARE ORCID. `orcid` in the dev realm.
ORCID_IDP_ALIASES: Tuple[str, ...] = ("orcid",)


def _is_service_account(claims: Mapping[str, Any]) -> bool:
    name = claims.get("preferred_username")
    return isinstance(name, str) and name.startswith("service-account-")


def auth_mode_of(claims: Optional[Mapping[str, Any]], *,
                 orcid_aliases: Tuple[str, ...] = ORCID_IDP_ALIASES) -> Optional[str]:
    """``orcid`` · ``node_password`` · ``None`` (not determinable)."""
    claims = claims or {}
    explicit = claims.get("em_auth")
    if isinstance(explicit, str) and explicit.strip() in AUTH_MODES:
        return explicit.strip()
    idp = claims.get("em_idp")
    if isinstance(idp, str) and idp.strip():
        #: brokered through SOME provider; only ORCID's alias is «orcid». Another
        #: provider (an institutional SAML, say) is neither of our two modes.
        return "orcid" if idp.strip() in orcid_aliases else None
    reported = claims.get("em_auth_reported")
    if reported is True or (isinstance(reported, str) and reported.lower() == "true"):
        if _is_service_account(claims):
            return None                 # a machine, not a person with a password
        return "node_password"
    return None


# ── moved from app/main.py (dev28): the relay needs them too, and ws.py does not
# import main ───────────────────────────────────────────────────────────────

def node_name() -> str:
    """This node's name, as an attestation carries it.

    MEASURED 2026-10-01: before this there was no node-name setting at all; the
    nearest thing is `EM_PUBLIC_BASE` (what `fcn-up.sh` derives from the host it
    is given). So: `EM_NODE_NAME` when set, else the authority (`host:port`) of
    the public base — the same spelling EMStudio already shows as the witness of
    a node sign-in («verifiedBy: em.localhost:8443») — else empty.
    """
    import os
    explicit = os.environ.get("EM_NODE_NAME", "").strip()
    if explicit:
        return explicit
    from . import handoff as ho
    base = ho.public_base()
    if not base:
        return ""
    import urllib.parse
    return urllib.parse.urlsplit(base).netloc


def orcid_idp_alias() -> str:
    import os
    return os.environ.get("EM_ORCID_IDP_ALIAS", "orcid").strip()


def signature_auth(claims: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """How the sender of an op had entered, as a signature carries it:
    ``{"mode": "orcid"}`` · ``{"mode": "node_password", "attested_by": <node>}``
    · None.

    dev28 (E.D., 1 Oct 2026, decision 13): the relay stamps this on every op
    it forwards (``s3dgraphy.crdt.stamp_auth``), like the author — the client
    does not declare it any more. None in dev mode (no token, nobody to
    attest), when the realm does not say, and for a node password on a node
    that never said its name: an attestation nobody can trace back to a node
    is not one, so nothing is written rather than a nameless witness.
    """
    claims = claims or {}
    if claims.get("em_dev_mode"):
        return None
    mode = auth_mode_of(claims, orcid_aliases=(orcid_idp_alias(),))
    if mode == "orcid":
        return {"mode": "orcid"}
    if mode == "node_password":
        node = node_name()
        return {"mode": "node_password", "attested_by": node} if node else None
    return None
