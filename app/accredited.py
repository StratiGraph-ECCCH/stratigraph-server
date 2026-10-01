"""WHO MAY COME IN FROM THE FIELD: the node's list of accredited ORCID iDs.

Decided by E.D. on 1 October 2026 (brain, «L'accesso sul campo»): **a user is
an ORCID**. With internet you sign in with ORCID; without it, with the iD and a
password the node gave you — and the node stands as guarantor until the network
comes back. Nobody gets on the field without passing through the accreditation
first, once, online:

1. the node manager writes the iD in this list (``dev-stack/accredited.yaml``);
2. ``dev-stack/accredit.sh`` creates the Keycloak user, username = the iD;
3. the person signs in once with real ORCID — Keycloak LINKS that user to the
   ORCID identity provider (it never creates one: the first-login flow is
   «detect existing user» + «link», see ``dev-stack/keycloak/README.md``);
4. only then ``dev-stack/offline-password.sh <iD>`` gives the offline password.

This module is the one reader of the list, for two callers that must agree:
StratiGraph Server (``/v1/whoami`` answers ``accredited: true|false``) and the
two scripts, which run on the host with whatever ``python3`` is there. Hence
**standard library only**, and runnable as a file
(``python3 app/accredited.py --tsv dev-stack/accredited.yaml``).

**Why a YAML subset and not PyYAML.** Measured on 1 October 2026: the host's
``python3`` has no ``yaml`` module, and the server does not declare it. The file
is a list of pairs, so the reader accepts exactly this shape and refuses
anything else with the line number — a list of who may enter must not be read
«more or less»::

    accredited:
      - orcid: 0000-0002-1825-0097
        name: Josiah Carberry

Every iD is checked with its ISO 7064 11,2 check digit: a mistyped iD is a
person who will be refused at the door with nobody understanding why.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

#: the variable that names the file inside the server process
ENV_FILE = "EM_ACCREDITED_FILE"

_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class AccreditedListError(ValueError):
    """The list cannot be read as written. Carries the line number."""


def normalize(orcid: object) -> Optional[str]:
    """One spelling: bare iD, upper-case ``X``. URLs (``https://orcid.org/…``)
    are the same person — the rule ``access._norm`` uses, kept here because this
    module must run without the package."""
    if orcid in (None, ""):
        return None
    text = str(orcid).strip()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip("/").upper() or None


def check_digit_ok(orcid: str) -> bool:
    """ISO 7064 MOD 11-2, the ORCID check digit."""
    if not _ID.match(orcid or ""):
        return False
    digits = orcid.replace("-", "")
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    result = (12 - total % 11) % 11
    return digits[-1] == ("X" if result == 10 else str(result))


def _value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    if " #" in raw:                       # a trailing comment
        raw = raw.split(" #", 1)[0].rstrip()
    return raw


def parse(text: str) -> List[Dict[str, str]]:
    """``[{orcid, name}]`` in file order. Raises :class:`AccreditedListError`."""
    entries: List[Dict[str, str]] = []
    seen_root = False
    current: Optional[Dict[str, str]] = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not seen_root:
            if stripped in ("accredited:", "accredited: []"):
                seen_root = True
                continue
            raise AccreditedListError(
                f"line {number}: the file starts with `accredited:` "
                f"(found {stripped!r})")
        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            stripped = stripped[2:].strip()
        elif current is None or not line.startswith((" ", "\t")):
            raise AccreditedListError(
                f"line {number}: expected `- orcid: …` (found {stripped!r})")
        key, sep, raw = stripped.partition(":")
        key = key.strip()
        if not sep or key not in ("orcid", "name"):
            raise AccreditedListError(
                f"line {number}: only `orcid:` and `name:` are read "
                f"(found {stripped!r})")
        if key in current:
            raise AccreditedListError(f"line {number}: `{key}` twice in one entry")
        current[key] = _value(raw)

    seen: Dict[str, int] = {}
    for index, entry in enumerate(entries, 1):
        orcid = normalize(entry.get("orcid"))
        if not orcid:
            raise AccreditedListError(f"entry {index}: no `orcid:`")
        if not check_digit_ok(orcid):
            raise AccreditedListError(
                f"entry {index}: {entry.get('orcid')!r} is not an ORCID iD "
                f"(format 0000-0000-0000-000X, with its check digit)")
        if orcid in seen:
            raise AccreditedListError(
                f"entry {index}: {orcid} is already entry {seen[orcid]}")
        seen[orcid] = index
        entry["orcid"] = orcid
        entry["name"] = (entry.get("name") or "").strip()
    return entries


def load(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read())


#: (path, mtime) → iDs. The list changes by hand, rarely; re-reading it on every
#: `/v1/whoami` would be harmless but the mtime check is just as honest.
_cache: Dict[str, Tuple[float, frozenset]] = {}


def accredited_ids(environ: Optional[Dict[str, str]] = None) -> Optional[frozenset]:
    """The iDs of the list named by ``EM_ACCREDITED_FILE``.

    ``None`` when the node names no list (nobody is accredited *by this node*:
    ``accredited`` is then false for everybody, never true by default). A list
    that is named but unreadable raises — a node must not answer «not
    accredited» for a file it could not read.
    """
    env = environ if environ is not None else os.environ
    path = (env.get(ENV_FILE) or "").strip()
    if not path:
        return None
    mtime = os.stat(path).st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    ids = frozenset(entry["orcid"] for entry in load(path))
    _cache[path] = (mtime, ids)
    return ids


def is_accredited(orcid: object, environ: Optional[Dict[str, str]] = None) -> bool:
    ids = accredited_ids(environ)
    key = normalize(orcid)
    return bool(ids and key and key in ids)


def _main(argv: List[str]) -> int:
    """``--tsv FILE``: one ``iD<TAB>name`` per line; ``--check ID``: exit 0 if the
    iD is well formed. Errors on stderr, exit 2. Used by the dev-stack scripts."""
    if len(argv) == 2 and argv[0] == "--tsv":
        try:
            entries = load(argv[1])
        except (OSError, AccreditedListError) as exc:
            print(f"✖ {argv[1]}: {exc}", file=sys.stderr)
            return 2
        for entry in entries:
            print(f"{entry['orcid']}\t{entry['name']}")
        return 0
    if len(argv) == 2 and argv[0] == "--check":
        orcid = normalize(argv[1]) or ""
        if not check_digit_ok(orcid):
            print(f"✖ {argv[1]!r} is not an ORCID iD (0000-0000-0000-000X, "
                  f"with its check digit)", file=sys.stderr)
            return 2
        print(orcid)
        return 0
    print("usage: accredited.py --tsv FILE | --check ID", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
