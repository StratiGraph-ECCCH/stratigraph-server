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


class InMemoryAssetHomes:
    """Tests and a laptop run; dies with the process, and says so."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, List[str]]] = {}
        self._lock = threading.Lock()

    def homes(self, digest: str) -> Dict[str, List[str]]:
        with self._lock:
            found = self._data.get(_hex(digest)) or {}
            return {room: list(who) for room, who in found.items()}

    def record(self, digest: str, room_id: str, who: Optional[str]) -> None:
        key = _hex(digest)
        if not key or not room_id:
            return
        with self._lock:
            entry = self._data.setdefault(key, {})
            people = entry.setdefault(room_id, [])
            if who and who not in people:
                people.append(who)


class DirectoryAssetHomes:
    """One small JSON file per digest, fanned out like the asset directory.

    Per DIGEST and not per room because the question is asked by digest, on
    every asset request: one file read answers it. Written atomically, and a
    read that fails answers «no home known» — this record only grants, so not
    reading it can only make the gate stricter, never looser.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key: str) -> pathlib.Path:
        return self.root / key[:2] / f"{key}.json"

    def homes(self, digest: str) -> Dict[str, List[str]]:
        key = _hex(digest)
        if not key:
            return {}
        try:
            raw = json.loads(self._path(key).read_text("utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return {}
        rooms = raw.get("rooms") if isinstance(raw, dict) else None
        if not isinstance(rooms, dict):
            return {}
        return {str(r): [str(w) for w in (who or [])] for r, who in rooms.items()}

    def record(self, digest: str, room_id: str, who: Optional[str]) -> None:
        key = _hex(digest)
        if not key or not room_id:
            return
        with self._lock:
            rooms = self.homes(key)
            if room_id in rooms and (not who or who in rooms[room_id]):
                return                      # nothing new: no write
            people = rooms.setdefault(room_id, [])
            if who and who not in people:
                people.append(who)
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_text(json.dumps({"rooms": rooms}, ensure_ascii=False,
                                      sort_keys=True), "utf-8")
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
