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
