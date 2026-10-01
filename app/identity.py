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
