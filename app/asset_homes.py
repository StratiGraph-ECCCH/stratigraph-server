"""Which rooms brought these bytes in, and who — the home of an asset.

D-C (E.D., 3 October 2026): **an asset uploaded to a room, with no rights
declared on its resource node, is for the people of that room** — any role,
viewer and above — and not for every authenticated caller who knows its digest.

The graph already answers «who may see this» for an asset it CITES: the rooms
whose documents name the digest are its rooms. It cannot answer for an asset
that was uploaded and is not cited yet — which is exactly the state of every
file in the middle of «Porta in una stanza…»: the bytes go up first, the
resource node learns its sha256 after. And the asset store cannot answer
either, because it is content-addressed and shared across rooms on purpose
(`assets.py`): a blob has a name, not an owner.

So this is the third, thinnest record: `digest → {room: [who uploaded]}`.
Written by the upload door, read by the asset gate, and it only ever GRANTS —
a room listed here lets its participants read these bytes, an uploader may read
back what they sent. It never refuses anything by itself, which is what makes
its failure modes safe: a record that will not read grants nothing, and the
gate then answers from the graph alone.

**One home** (F1, E.D., 3 October 2026, evening). The record now also names
THE room the bytes belong to: the first one they came in through, changed only
by an explicit move («Move here», `POST /v1/rooms/{id}/asset-home/{ref}`). With
a home recorded, the gate reads the home's participants and no longer the
participants of every room whose graph cites the digest: a graph elsewhere that
cites the file holds a REFERENCE to bytes kept in another room. An unreadable
record still answers «no home known», and the gate falls back to the graph and
the door — stricter or equal, never «anybody».

Like `assets.py`, no logic about graphs: it does not know what a role is. The
gate in `main.py` resolves roles; this remembers where the bytes came in.

Kept beside the snapshots (`<EM_SNAPSHOT_DIR>/asset-homes/`, or
`EM_ASSET_HOMES_DIR`) — the same convention as the ACLs and the `.blend`
register: an operator who backs up one finds the other next to it. Local to one
machine, and `describe()` says so.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
from typing import Any, Dict, List, Optional


def _hex(digest: str) -> str:
    """`sha256:<hex>` or `<hex>` → `<hex>` lower-case, or '' for anything else."""
    text = str(digest or "").rsplit(":", 1)[-1].strip().lower()
    if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
        return text
    return ""


class _Homes:
    """The logic, on top of a load/save per digest the two stores provide.

    An entry is `{"rooms": {room: [who uploaded through it]}, "home": room,
    "moves": [...]}`. **One home** (E.D., 3 October 2026, evening: «un file sta
    in UNA stanza; se serve altrove si SPOSTA, mai condiviso tra stanze»):

    * the FIRST room the bytes came in through becomes their home; a later
      upload of the same bytes through another room is remembered as WHO holds
      them (they may read back what they sent) and does not make a second home;
    * `move()` is the only way the home changes — the gesture «Move here»,
      decided by the main module, which knows what a role is;
    * an entry written before the rule (several rooms, no `home`) has no single
      home: `home()` answers None and `legacy_homes()` names them, so the gate
      keeps the old reading for it until somebody moves it somewhere — said,
      not silently picked.
    """

    def _load(self, key: str) -> Dict[str, Any]:  # pragma: no cover — abstract
        raise NotImplementedError

    def _save(self, key: str, entry: Dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def _home_of(entry: Dict[str, Any]) -> Optional[str]:
        home = entry.get("home")
        if home:
            return str(home)
        rooms = entry.get("rooms") or {}
        return next(iter(rooms)) if len(rooms) == 1 else None

    def homes(self, digest: str) -> Dict[str, List[str]]:
        """room → who uploaded through it (every room, the home included)."""
        key = _hex(digest)
        if not key:
            return {}
        rooms = self._load(key).get("rooms") or {}
        return {str(r): [str(w) for w in (who or [])] for r, who in rooms.items()}

    def home(self, digest: str) -> Optional[str]:
        """THE room these bytes belong to, or None (never recorded, or recorded
        in several rooms before the one-home rule)."""
        key = _hex(digest)
        return self._home_of(self._load(key)) if key else None

    def legacy_homes(self, digest: str) -> List[str]:
        """The rooms of an entry from before the rule, with no single home."""
        key = _hex(digest)
        if not key:
            return []
        entry = self._load(key)
        if self._home_of(entry):
            return []
        return sorted(entry.get("rooms") or {})

    def moves(self, digest: str) -> List[Dict[str, Any]]:
        key = _hex(digest)
        return list(self._load(key).get("moves") or []) if key else []

    def record(self, digest: str, room_id: str, who: Optional[str]) -> Optional[str]:
        """An upload through `room_id`. → the home after it."""
        key = _hex(digest)
        if not key or not room_id:
            return None
        with self._lock:
            entry = self._load(key)
            rooms = entry.setdefault("rooms", {})
            home = self._home_of(entry)
            changed = room_id not in rooms
            if home is None and not rooms:
                home = room_id                      # the first room is the home
            if home and entry.get("home") != home:
                entry["home"] = home
                changed = True
            people = rooms.setdefault(room_id, [])
            if who and who not in people:
                people.append(who)
                changed = True
            if changed:
                self._save(key, entry)
            return home

    def move(self, digest: str, to_room: str, by: Optional[str],
             at: Optional[str] = None) -> Dict[str, Any]:
        """Change the home. → `{"home": to_room, "previous": room|None,
        "previous_legacy": [rooms]}`. Permission is the caller's business."""
        key = _hex(digest)
        if not key or not to_room:
            raise ValueError("a move needs a digest and a room")
        with self._lock:
            entry = self._load(key)
            previous = self._home_of(entry)
            legacy = [] if previous else sorted(entry.get("rooms") or {})
            entry.setdefault("rooms", {})
            entry["home"] = to_room
            entry.setdefault("moves", []).append({
                "from": previous, "from_legacy": legacy, "to": to_room,
                "by": by, "at": at})
            self._save(key, entry)
        return {"home": to_room, "previous": previous, "previous_legacy": legacy}


class InMemoryAssetHomes(_Homes):
    """Tests and a laptop run; dies with the process, and says so."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _load(self, key: str) -> Dict[str, Any]:
        return json.loads(json.dumps(self._data.get(key) or {}))

    def _save(self, key: str, entry: Dict[str, Any]) -> None:
        self._data[key] = json.loads(json.dumps(entry))


class DirectoryAssetHomes(_Homes):
    """One small JSON file per digest, fanned out like the asset directory.

    Per DIGEST and not per room because the question is asked by digest, on
    every asset request: one file read answers it. Written atomically, and a
    read that fails answers «no home known» — the gate then falls back to the
    graph and the door, never to «anybody».
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, key: str) -> pathlib.Path:
        return self.root / key[:2] / f"{key}.json"

    def _load(self, key: str) -> Dict[str, Any]:
        try:
            raw = json.loads(self._path(key).read_text("utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return {}
        if not isinstance(raw, dict) or not isinstance(raw.get("rooms"), dict):
            return {}
        return raw

    def _save(self, key: str, entry: Dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, sort_keys=True), "utf-8")
        tmp.replace(path)


def asset_homes_from_env(environ: Optional[Dict[str, str]] = None):
    env = environ if environ is not None else os.environ
    root = env.get("EM_ASSET_HOMES_DIR")
    if not root and env.get("EM_SNAPSHOT_DIR"):
        root = str(pathlib.Path(env["EM_SNAPSHOT_DIR"]) / "asset-homes")
    return DirectoryAssetHomes(root) if root else InMemoryAssetHomes()


def describe(store: Any) -> str:
    return {
        "InMemoryAssetHomes": "memory (not durable — dies with the process)",
        "DirectoryAssetHomes": "directory (beside the snapshots; local only)",
    }.get(type(store).__name__, type(store).__name__)


#: This process's record. Replaced by tests on the module, so read it as
#: `asset_homes.ASSET_HOMES` and never bind the name at import.
ASSET_HOMES = asset_homes_from_env()
