"""THE PEOPLE OF A NODE — who is known here, and with which profile.

Decided by E.D. on 30 October 2026, with the node console's desk in front of
him. Two levels answer «what may you do», and they are kept apart on purpose:

* a **role in a room** (`access.py`) says what a person may do with one study;
* a **profile on the node** (this module) says what a person may do with the
  node as a whole.

## The three profiles

* **super** — looks after the node: people, every room's lifecycle, storage.
  The capability `operators.py` has always called the OPERATOR.
* **creator** — the *node editor*: creates rooms (and becomes their owner) and
  creates groups (and manages them).
* **user** — the starting profile: enters the rooms where somebody gave them a
  role, or where an invitation brought them.

**Nobody becomes a creator by accident.** A person added without a profile is a
user, and from today creating a room or a group needs the creator profile (or
super). The rule is a node setting, `EM_CREATE_POLICY`: `editors` (the default)
or `anyone` (the behaviour before 30 October, for a node that wants it).

## Where a profile comes from

1. the deployment: the realm role `em-operator` or `EM_OPERATORS` make a super,
   the realm role `em-creator` (`EM_CREATOR_ROLE`) makes a creator. Fixed by
   whoever runs the realm; the console shows them and does not change them;
2. **this registry**: `people.json` beside the access lists, written only by
   the node console, i.e. only by somebody who is already super.

The registry can make somebody a super, and that does not break the rule
`operators.py` protects — *the capability cannot be self-granted*: the console
refuses a change to the caller's own profile, and refuses to demote the last
super of the node.

## Test people

A node in development may hold **test people**: identities with an iD in the
range ORCID never issues (`0000-0000-…`), marked `test`, given a password
directly instead of through ORCID. Only where `EM_ALLOW_TEST_PEOPLE` is on —
never on a production node, where every person is somebody ORCID verified once.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import threading
from typing import Any, Dict, Iterable, List, Optional, Protocol

from .accredited import check_digit_ok, normalize

PROFILES = ("user", "creator", "super")
_RANK = {"user": 0, "creator": 1, "super": 2}

DEFAULT_CREATOR_ROLE = "em-creator"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _env(environ: Optional[Dict[str, str]]) -> Dict[str, str]:
    return environ if environ is not None else os.environ  # type: ignore[return-value]


def creator_role(environ: Optional[Dict[str, str]] = None) -> str:
    env = _env(environ)
    return (env.get("EM_CREATOR_ROLE") or DEFAULT_CREATOR_ROLE).strip() or DEFAULT_CREATOR_ROLE


def create_policy(environ: Optional[Dict[str, str]] = None) -> str:
    """`editors` (default) or `anyone`. Anything else reads as `editors`:
    a typo must close the door, not open it."""
    value = (_env(environ).get("EM_CREATE_POLICY") or "editors").strip().lower()
    return "anyone" if value == "anyone" else "editors"


def test_people_switch(environ: Optional[Dict[str, str]] = None) -> bool:
    """What the configuration asks for, before the node's kind has its say."""
    return (_env(environ).get("EM_ALLOW_TEST_PEOPLE") or "").strip().lower() in ("1", "true", "yes", "on")


def test_people_allowed(environ: Optional[Dict[str, str]] = None) -> bool:
    """On only where the configuration asks for it AND the node is not
    institutional: an institutional node refuses fictitious people whatever the
    switch says (`app/node_kind.py`)."""
    from . import node_kind
    return test_people_switch(environ) and node_kind.kind(environ) != "institutional"


def is_test_orcid(orcid: Optional[str]) -> bool:
    """The range ORCID does not issue (`0000-0000-…`): safe for fictitious people."""
    return bool(orcid) and str(orcid).startswith("0000-0000-")


def test_orcid(n: int) -> str:
    """The n-th test iD, with a correct ISO 7064 11,2 check digit."""
    base = f"00000000{int(n):07d}"[-15:]
    total = 0
    for ch in base:
        total = (total + int(ch)) * 2
    result = (12 - total % 11) % 11
    check = "X" if result == 10 else str(result)
    digits = base + check
    return f"{digits[0:4]}-{digits[4:8]}-{digits[8:12]}-{digits[12:16]}"


class Person:
    """One person the node knows. Data, with the iD normalised."""

    def __init__(self, orcid: str, name: str = "", profile: str = "user",
                 added_by: Optional[str] = None, added_at: Optional[str] = None,
                 updated_at: Optional[str] = None, test: bool = False,
                 verified_by: Optional[str] = None) -> None:
        self.orcid = normalize(orcid) or ""
        self.name = str(name or "").strip()
        self.profile = profile if profile in PROFILES else "user"
        self.added_by = normalize(added_by)
        self.added_at = added_at or _now()
        self.updated_at = updated_at or self.added_at
        self.test = bool(test)
        #: the TRUSTED node that attests ORCID verified this iD (a person who
        #: arrived in a signed transfer package, `transfer.py`). None when this
        #: node verified them itself, or nobody did.
        self.verified_by = verified_by or None

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Person":
        return cls(raw.get("orcid") or "", raw.get("name") or "", raw.get("profile") or "user",
                   raw.get("added_by"), raw.get("added_at"), raw.get("updated_at"),
                   bool(raw.get("test")), raw.get("verified_by"))

    def as_dict(self) -> Dict[str, Any]:
        return {"orcid": self.orcid, "name": self.name, "profile": self.profile,
                "added_by": self.added_by, "added_at": self.added_at,
                "updated_at": self.updated_at, "test": self.test,
                "verified_by": self.verified_by}


# ── the store: one document, like the group registry ─────────────────────────

class PeopleStore(Protocol):
    def load(self) -> Dict[str, Any]: ...

    def save(self, data: Dict[str, Any]) -> None: ...


class InMemoryPeopleStore:
    def __init__(self) -> None:
        self._raw = "{}"
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(self._raw)

    def save(self, data: Dict[str, Any]) -> None:
        blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
        with self._lock:
            self._raw = blob


class DirectoryPeopleStore:
    """`people.json` beside the access lists, written atomically."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "people.json"
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return {}
            return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
                           encoding="utf-8")
            tmp.replace(self.path)

    def describe(self) -> str:
        return f"directory ({self.path})"


def people_store_from_env(environ: Optional[Dict[str, str]] = None) -> PeopleStore:
    env = _env(environ)
    directory = env.get("EM_PEOPLE_DIR") or env.get("EM_ACL_DIR") or env.get("EM_SNAPSHOT_DIR")
    if directory:
        return DirectoryPeopleStore(directory)
    return InMemoryPeopleStore()


class People:
    """The registry, read through to the store every time (a profile change must
    count at the next request, as a membership change does)."""

    def __init__(self, store: PeopleStore) -> None:
        self.store = store

    def all(self) -> Dict[str, Person]:
        raw = self.store.load() or {}
        out: Dict[str, Person] = {}
        for orcid, entry in (raw.get("people") or {}).items():
            person = Person.from_dict({**entry, "orcid": orcid})
            if person.orcid:
                out[person.orcid] = person
        return out

    def get(self, orcid: Optional[str]) -> Optional[Person]:
        key = normalize(orcid)
        return self.all().get(key) if key else None

    def put(self, person: Person) -> Person:
        raw = self.store.load() or {}
        people = raw.setdefault("people", {})
        person.updated_at = _now()
        entry = person.as_dict()
        entry.pop("orcid", None)
        people[person.orcid] = entry
        self.store.save(raw)
        return person

    def remove(self, orcid: str) -> bool:
        key = normalize(orcid)
        raw = self.store.load() or {}
        people = raw.get("people") or {}
        if key not in people:
            return False
        del people[key]
        raw["people"] = people
        self.store.save(raw)
        return True


#: The process's registry, as `ws.GROUP_STORE` is for groups.
PEOPLE_STORE = people_store_from_env()


def registry() -> People:
    return People(PEOPLE_STORE)


# ── profiles ────────────────────────────────────────────────────────────────

def _roles_in(claims: Dict[str, Any]) -> Iterable[str]:
    from .operators import _roles_in as roles
    return roles(claims)


def registry_profile(orcid: Optional[str]) -> Optional[str]:
    """The profile the registry gives this iD, or None. Never raises: a registry
    that will not read gives nothing, so it can only ever withhold a profile."""
    key = normalize(orcid)
    if not key:
        return None
    try:
        person = registry().get(key)
    except (OSError, ValueError):
        return None
    return person.profile if person else None


def profile_of(claims: Optional[Dict[str, Any]], *,
               environ: Optional[Dict[str, str]] = None) -> str:
    """`super`, `creator` or `user` for this caller. Dev mode is super, for the
    reason `operators.is_operator` gives: no identities, nothing to tell apart."""
    from .identity import identity_of
    from .operators import is_operator
    if not claims:
        return "user"
    if claims.get("em_dev_mode") or is_operator(claims, environ=environ):
        return "super"
    who = identity_of(claims)
    stored = registry_profile(who)
    if stored == "super":
        return "super"
    if stored == "creator" or creator_role(environ) in set(_roles_in(claims)):
        return "creator"
    return "user"


def may_create(claims: Optional[Dict[str, Any]], what: str = "a room", *,
               environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """None when this caller may create `what`; otherwise the sentence that says
    why not and who can change it."""
    if claims and claims.get("em_dev_mode"):
        return None
    if create_policy(environ) == "anyone":
        return None
    if _RANK[profile_of(claims, environ=environ)] >= _RANK["creator"]:
        return None
    return (f"creating {what} needs the node editor profile: on this node a person "
            "starts as a user, and somebody who looks after the node gives the "
            "editor profile in the console (People). Being given a role in a room "
            "is unchanged.")


def valid_orcid(orcid: Optional[str], *, environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The normalised iD, or None when it is not one this node accepts."""
    key = normalize(orcid)
    if not key or not check_digit_ok(key):
        return None
    if is_test_orcid(key) and not test_people_allowed(environ):
        return None
    return key


# ── the node's log: what the console did, and who did it ─────────────────────
#
# One JSON line per act (a person added or changed, a password set, a person
# taken off, a room rescued), beside the register. Never a password, never a
# token: what was done, to whom, by whom, when.

_MEMORY_LOG: List[Dict[str, Any]] = []


def log_event(kind: str, *, by: Optional[str], **fields: Any) -> Dict[str, Any]:
    entry = {"at": _now(), "kind": kind, "by": by, **fields}
    store = PEOPLE_STORE
    root = getattr(store, "root", None)
    if root is None:
        _MEMORY_LOG.append(entry)
        return entry
    try:
        with open(pathlib.Path(root) / "node-log.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        _MEMORY_LOG.append(entry)
    return entry


def read_log(limit: int = 200) -> List[Dict[str, Any]]:
    root = getattr(PEOPLE_STORE, "root", None)
    lines: List[Dict[str, Any]] = []
    if root is not None:
        path = pathlib.Path(root) / "node-log.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    continue
    return (lines + _MEMORY_LOG)[-limit:]
