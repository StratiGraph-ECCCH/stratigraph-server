"""Big uploads: bytes that arrive as a stream, and uploads that survive a cut.

U1 (MICRO-LA-BARRA-E-LE-STANZE, 3 October 2026). E.D. decided that **everything
goes up to the asset storage, raw photographs included** — it is also the
safety copy. Measured the same day: `PUT /v1/rooms/{id}/asset` did
`await request.body()`, so a 2 GB file was a 2 GB `bytes` inside the server
(twice, briefly, while the store copied it), and a connection that dropped at
1.9 GB started again from zero. Fine for a document; not for hundreds of GB of
photogrammetry.

Two things, both transport, no logic about graphs (same rule as `assets.py`):

* **`receive_stream`** — the body is read chunk by chunk into a file on disk,
  hashing as it goes, and the file is handed to the store with `put_file`. The
  server holds one chunk (≈64 KiB from uvicorn) at a time.
* **`UploadSessions`** — a resumable upload: declare the size, send pieces with
  their offset, ask where you are after a cut, and when the last byte lands the
  file is verified (sha256) and stored. The partial file IS the state: its
  length is the offset, so there is nothing to keep in step with it, and a
  restart of the server finds every session where it was left.

**Where the partial bytes live.** `EM_UPLOAD_DIR`; failing that beside the
snapshots (`<EM_SNAPSHOT_DIR>/uploads-in-progress`), the convention every other
durable record here follows; failing that the system temp directory — which
survives a restart of the process but not of the machine, and `describe()`
says so.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import tempfile
import threading
import uuid
from typing import Any, AsyncIterator, Dict, Optional, Tuple

#: `sha256:<hex>` or `<hex>` → `<hex>`; anything else is not a digest
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")


def normalise_sha256(value: Any) -> Optional[str]:
    """The bare lower-case hex of a sha256 written either way, or None."""
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return text if _HEX64.match(text) else None


def upload_dir_from_env(environ: Optional[Dict[str, str]] = None) -> pathlib.Path:
    env = environ if environ is not None else os.environ
    root = env.get("EM_UPLOAD_DIR")
    if not root and env.get("EM_SNAPSHOT_DIR"):
        root = str(pathlib.Path(env["EM_SNAPSHOT_DIR"]) / "uploads-in-progress")
    if not root:
        root = str(pathlib.Path(tempfile.gettempdir()) / "em-uploads")
    path = pathlib.Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def receive_stream(chunks: AsyncIterator[bytes], target: pathlib.Path, *,
                         append: bool = False, hasher: Any = None,
                         limit: Optional[int] = None) -> Tuple[int, bool]:
    """Write an async stream of chunks to `target`; return `(written, over)`.

    `over` is True when the stream went past `limit` bytes: the writing stops
    at the limit (nothing past it touches the disk) and the caller refuses.
    The file is flushed chunk by chunk and closed in a `finally`, so when the
    client goes away in the middle (`ClientDisconnect`, raised out of the
    stream) every byte that DID arrive is on disk — which is what makes the
    offset after a cut the true one.
    """
    written = 0
    over = False
    with open(target, "ab" if append else "wb") as fh:
        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                if limit is not None and written + len(chunk) > limit:
                    chunk = chunk[:max(0, limit - written)]
                    over = True
                if chunk:
                    fh.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    written += len(chunk)
                if over:
                    break
        finally:
            fh.flush()
    return written, over


def sha256_of_file(path: pathlib.Path, block: int = 1024 * 1024) -> str:
    """The digest of a file read a megabyte at a time — the completion check of
    a resumable upload, whose hash cannot be carried across a restart (hashlib's
    state does not serialise), so the file is read once more at the end."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for piece in iter(lambda: fh.read(block), b""):
            digest.update(piece)
    return digest.hexdigest()


class UploadSessions:
    """Resumable uploads on disk: `<id>.json` (what was declared) + `<id>.part`
    (what has arrived). The offset is the length of the `.part` — read from the
    file every time, never remembered, so it cannot disagree with the bytes."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        #: upload ids with a PATCH in flight: two writers appending to one file
        #: would interleave their bytes, so the second is refused (409)
        self._busy: set = set()

    # ── paths ────────────────────────────────────────────────────────────────

    def _meta(self, upload_id: str) -> pathlib.Path:
        return self.root / f"{upload_id}.json"

    def part(self, upload_id: str) -> pathlib.Path:
        return self.root / f"{upload_id}.part"

    def temp_file(self) -> pathlib.Path:
        """A fresh file name for a streamed PUT, on the same disk as the
        sessions (so `put_file` on a directory store can be a rename)."""
        return self.root / f"put-{uuid.uuid4().hex}.part"

    # ── the session ──────────────────────────────────────────────────────────

    def create(self, *, room_id: str, size: int, media_type: str,
               sha256: Optional[str], author: Optional[str]) -> Dict[str, Any]:
        upload_id = uuid.uuid4().hex
        record = {
            "upload_id": upload_id, "room_id": room_id, "size": int(size),
            "media_type": media_type, "sha256": sha256, "author": author,
            "created_at": datetime.datetime.now(datetime.timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.part(upload_id).write_bytes(b"")
        tmp = self._meta(upload_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), "utf-8")
        tmp.replace(self._meta(upload_id))
        return {**record, "offset": 0}

    def get(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """The session with its CURRENT offset, or None. An id that is not one
        this class could have minted is None too: it becomes a path."""
        if not _UPLOAD_ID.match(str(upload_id or "")):
            return None
        try:
            record = json.loads(self._meta(upload_id).read_text("utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None
        part = self.part(upload_id)
        record["offset"] = part.stat().st_size if part.is_file() else 0
        return record

    def drop(self, upload_id: str) -> None:
        if not _UPLOAD_ID.match(str(upload_id or "")):
            return
        self.part(upload_id).unlink(missing_ok=True)
        self._meta(upload_id).unlink(missing_ok=True)

    def claim(self, upload_id: str) -> bool:
        """Mark a PATCH in flight; False when one already is."""
        with self._lock:
            if upload_id in self._busy:
                return False
            self._busy.add(upload_id)
            return True

    def release(self, upload_id: str) -> None:
        with self._lock:
            self._busy.discard(upload_id)


def describe(sessions: UploadSessions) -> str:
    where = str(sessions.root)
    if where.startswith(tempfile.gettempdir()):
        return f"temp directory ({where} — survives a restart of the process, " \
               f"not of the machine)"
    return f"directory ({where})"


#: This process's sessions. Replaced by tests on the module, so read it as
#: `uploads.SESSIONS` and never bind the name at import.
SESSIONS = UploadSessions(upload_dir_from_env())
