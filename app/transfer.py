"""PEOPLE BETWEEN NODES — the field node and the central one (E.D., 30 Oct 2026).

A field node often has no network, so nobody can sign in there with ORCID for
the first time — and a node gives a field password only to an iD ORCID verified.
The field node therefore has to believe the central node when it says «I
verified this iD». That is a trust decision, and it was made like this:

1. **Passwords do not travel.** The receiving node gives each person a new
   temporary password. A secret, or its hash, never leaves a node.
2. **The package is signed** by the node that makes it (Ed25519, one key per
   node, kept beside the register), and a node accepts a package only from a
   node its manager put on the **trust list** — once, while preparing the field
   node with a network.
3. **Profiles travel as proposals.** The receiving node's manager confirms them
   one by one; a profile raised on the field never becomes valid at the centre
   by itself.
4. **Who travels**: the people of the rooms that leave for the field, plus whoever
   the manager adds — not the whole node. On the way back, people added in the
   field arrive «to verify».

What a package carries per person: iD, name, the proposed profile, whether the
sending node attests ORCID verified the iD, the groups. Nothing else: no
password, no token, no e-mail.

The room roles travel with the rooms (that is the synchronisation of studies,
`docs/SYNC-FIELD-TO-CLOUD.md`), not here; the groups do travel, because a grant
to a team in a room means nothing on a node that does not know the team.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import pathlib
import threading
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

FORMAT = "em-people-transfer"
VERSION = 1

_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _root() -> Optional[pathlib.Path]:
    from . import people
    root = getattr(people.PEOPLE_STORE, "root", None)
    return pathlib.Path(root) if root is not None else None


# ── the node's key ───────────────────────────────────────────────────────────

_MEMORY_KEY: Dict[str, Any] = {}


def _key_path() -> Optional[pathlib.Path]:
    explicit = os.environ.get("EM_NODE_KEY_FILE")
    if explicit:
        return pathlib.Path(explicit)
    root = _root()
    return (root / "node-key.pem") if root is not None else None


def node_key() -> Ed25519PrivateKey:
    """This node's signing key, made the first time it is needed. On disk
    (`node-key.pem`, mode 0600) when the register is on disk."""
    path = _key_path()
    with _lock:
        if path is None:
            if "key" not in _MEMORY_KEY:
                _MEMORY_KEY["key"] = Ed25519PrivateKey.generate()
            return _MEMORY_KEY["key"]
        if path.is_file():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[return-value]
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
        return key


def public_b64(key: Optional[Ed25519PrivateKey] = None) -> str:
    raw = (key or node_key()).public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def fingerprint(public_key_b64: str) -> str:
    """Twelve hex pairs a person can read out on the phone and compare."""
    digest = hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:24]
    return ":".join(digest[i:i + 2] for i in range(0, 24, 2))


# ── the trust list ───────────────────────────────────────────────────────────

_MEMORY_TRUST: Dict[str, Any] = {}


def _trust_path() -> Optional[pathlib.Path]:
    root = _root()
    return (root / "trusted-nodes.json") if root is not None else None


def trusted() -> Dict[str, Dict[str, Any]]:
    path = _trust_path()
    if path is None:
        return dict(_MEMORY_TRUST)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("nodes", {})


def _save_trust(nodes: Dict[str, Any]) -> None:
    path = _trust_path()
    if path is None:
        _MEMORY_TRUST.clear()
        _MEMORY_TRUST.update(nodes)
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"nodes": nodes}, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    tmp.replace(path)


def valid_public_key(text: str) -> Optional[str]:
    try:
        raw = base64.b64decode(str(text).strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError):
        return None
    return base64.b64encode(raw).decode()


def trust(name: str, public_key: str, by: Optional[str]) -> Dict[str, Any]:
    key = valid_public_key(public_key)
    if not key:
        raise ValueError("not an Ed25519 public key (base64, 32 bytes)")
    nodes = trusted()
    nodes[name] = {"public_key": key, "fingerprint": fingerprint(key), "added_by": by, "added_at": _now()}
    _save_trust(nodes)
    return nodes[name]


def distrust(name: str) -> bool:
    nodes = trusted()
    if name not in nodes:
        return False
    del nodes[name]
    _save_trust(nodes)
    return True


def is_trusted_node(name: Optional[str]) -> bool:
    return bool(name) and name in trusted()


# ── the package ──────────────────────────────────────────────────────────────

def _canonical(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = node_key()
    return {**payload, "public_key": public_b64(key),
            "signature": base64.b64encode(key.sign(_canonical(payload))).decode()}


def check(package: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """`(trusted, why, payload)`. Trusted means: the format is ours, the
    signature is good, and the signing key is the one this node's trust list
    holds for the sending node's name."""
    if not isinstance(package, dict) or package.get("format") != FORMAT:
        return False, "not a people transfer package", {}
    if int(package.get("version") or 0) != VERSION:
        return False, f"package version {package.get('version')} is not understood here", {}
    payload = {k: v for k, v in package.items() if k not in ("signature", "public_key")}
    sender = str(package.get("from") or "")
    try:
        raw = base64.b64decode(str(package.get("public_key") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(raw).verify(
            base64.b64decode(str(package.get("signature") or ""), validate=True), _canonical(payload))
    except (ValueError, TypeError, InvalidSignature):
        return False, "the signature does not match the content: the package was changed after it was signed", payload
    known = trusted().get(sender)
    if not known:
        return False, (f"the node «{sender}» is not on this node's trust list: add its public key "
                       f"(fingerprint {fingerprint(base64.b64encode(raw).decode())}) first"), payload
    if known.get("public_key") != base64.b64encode(raw).decode():
        return False, (f"the package says it comes from «{sender}», but it is signed with a "
                       "different key from the one this node trusts for that name"), payload
    return True, "", payload


def build(*, sender: str, by: Optional[str], rooms: List[str], people: List[Dict[str, Any]],
          groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    return sign({"format": FORMAT, "version": VERSION, "from": sender, "made_at": _now(),
                 "made_by": by, "rooms": sorted(rooms), "people": people, "groups": groups})
