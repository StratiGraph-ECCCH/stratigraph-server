"""PREFLIGHT — the check an orchestrated node runs before the server starts.

`python -m app.preflight` exits 0 when the environment describes a node that can
stand on a shared platform, and exits 2 with one sentence per missing thing
when it does not. The OpenShift manifests (`deploy/openshift/`) run it as an
init container with the same environment as the server, so a pod that lacks a
required value stays in `Init:Error` and SAYS which value, instead of coming up.

WHY IT EXISTS, measured on 18 Nov 2026: the server, given an empty
environment, starts — on purpose. `node_kind.py` says «a node is never stopped
by advice», and a laptop with no configuration is a real use. Started that way
it serves `/health` 200 with `auth: dev-no-auth` (every /v1 route open) and
`memory` stores (everything gone at the first restart). That is right on a
laptop and wrong behind a public Route, and the server cannot tell the two
apart. The deployment can: so the refusal lives HERE, called by the deployment,
and the server's own behaviour on every other node is unchanged.

What it checks is the list in `deploy/openshift/README.md` («obbligatorie»),
and it reads each value through the SAME function the server reads it with —
`auth.load_settings`, `assets._s3_settings`, `documents.dsn_from_env`,
`node_kind.kind` — so the check cannot disagree with the server about what a
value means. Half-configured settings raise in those functions, and the raise
is reported here as a refusal with its own sentence.

What it does NOT check: whether the other services ANSWER. The server already refuses
to start when its object store does not answer (`assets.S3AssetStore`), and
knocks on the rest at start-up without being stopped by them (`main._lifespan`).
This is configuration, plus ONE touch of the network that is not a choice:
importing `app.assets` builds the asset store, and with S3 configured that
means HeadBucket (CreateBucket when missing) — so an object store that does not
answer is refused here, with the server's own sentence, a few seconds earlier.
"""

from __future__ import annotations

import os
import pathlib
import sys
import uuid
from typing import Dict, List, Optional


def _value(env: Dict[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _writable(directory: str) -> Optional[str]:
    """None when a file can be created and removed under `directory` (created
    if missing), else why not. Measured, not inferred from permission bits: on
    OpenShift the process runs as a uid the image never heard of, and only a
    write says whether the volume's group lets it in."""
    try:
        path = pathlib.Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".preflight-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def problems(environ: Optional[Dict[str, str]] = None) -> List[str]:
    """Every reason this environment cannot run an orchestrated node, as
    sentences naming the variable. Empty list: go."""
    env = dict(environ if environ is not None else os.environ)
    out: List[str] = []

    # 1 · what kind of node — declared, never guessed (`node_kind.py`)
    from . import node_kind
    kind = node_kind.kind(env)
    if kind == "node":
        out.append("EM_NODE_KIND is not set (or not one of personal, field, "
                   "institutional): an orchestrated node must say what it is, "
                   "because the kind decides which safe defaults apply.")

    # 2 · the public address — what every link another machine follows is
    #     built from (`handoff.public_base`), and what the Route serves
    from . import handoff
    saved = os.environ
    try:
        os.environ = env  # type: ignore[assignment]
        public = handoff.public_base()
    finally:
        os.environ = saved  # type: ignore[assignment]
    if not public:
        out.append("EM_PUBLIC_BASE is not set: the node would build every "
                   "«Open in…» link and every package for another node without "
                   "an address. Set it to the Route's https:// URL.")
    elif not public.startswith("https://"):
        out.append(f"EM_PUBLIC_BASE is {public!r}, not an https:// URL: behind "
                   f"a Route the node is reached over TLS, and a link naming "
                   f"plain http is a link that fails from outside.")

    # 3 · tokens — without both halves every /v1 route is OPEN (`auth.py`)
    try:
        # `auth` builds its authenticator AT IMPORT (`auth.py`, the module's
        # last lines), so a half-configured realm raises on the import itself
        from . import auth
        settings = auth.load_settings(env)
    except RuntimeError as exc:
        out.append(str(exc))
    else:
        if not settings.enforcing:
            out.append("OIDC_ISSUER (or TOKEN_ENDPOINT) and OIDC_AUDIENCE (or "
                       "CLIENT_ID_em) are not set: the server would start in "
                       "dev-no-auth, with every /v1 route open to anyone who "
                       "reaches the Route.")

    # 4 · the node's own state on disk — rooms, ACL, people, groups, invites,
    #     the node's SIGNING KEY, uploads in progress: all beside the snapshots
    #     (measured: `deploy/openshift/README.md`, «where it writes»)
    snapshots = _value(env, "EM_SNAPSHOT_DIR")
    if not snapshots:
        out.append("EM_SNAPSHOT_DIR is not set: rooms, access lists, people and "
                   "the node's signing key would live in memory and vanish at "
                   "the first restart. Point it at the mounted volume "
                   "(/srv/em-data/snapshots).")
    else:
        why = _writable(snapshots)
        if why:
            out.append(f"EM_SNAPSHOT_DIR={snapshots} is not writable by this "
                       f"process ({why}): the volume is missing or its group "
                       f"does not let the pod's uid in.")

    # 5 · the bytes — S3 complete, or a directory; never memory
    try:
        # importing `assets` BUILDS the store (`assets.ASSET_STORE`, at import
        # by design), so with S3 configured this import is the one network
        # touch of the preflight: the same knock the server would make, and
        # the same refusal when the store does not answer
        from .assets import _s3_settings
    except RuntimeError as exc:
        out.append(str(exc))
        return out
    try:
        s3 = _s3_settings(env)
    except RuntimeError as exc:
        out.append(str(exc))
        s3 = {"half": True}
    if not s3:
        asset_dir = _value(env, "EM_ASSET_DIR")
        if not asset_dir:
            out.append("No asset store: set EM_ASSET_S3_ENDPOINT, "
                       "EM_ASSET_S3_ACCESS_KEY, EM_ASSET_S3_SECRET_KEY and "
                       "EM_ASSET_S3_BUCKET (or, for a single replica without "
                       "S3, EM_ASSET_DIR on the volume). Without either, every "
                       "uploaded file lives in memory.")
        else:
            why = _writable(asset_dir)
            if why:
                out.append(f"EM_ASSET_DIR={asset_dir} is not writable by this "
                           f"process ({why}).")

    # 6 · the documents' database is OPTIONAL (without it the revisions live
    #     in EM_SNAPSHOT_DIR) — but half of it is a refusal, said here
    from . import documents
    try:
        documents.dsn_from_env(env)
    except RuntimeError as exc:
        out.append(str(exc))

    return out


def main(argv: Optional[List[str]] = None) -> int:
    # the modules it imports log their own start-up warnings («DEV MODE — every
    # route OPEN») as they are built; here they would print, before the verdict,
    # a description of a server that this very check is about to refuse
    import logging
    logging.disable(logging.WARNING)
    found = problems()
    if found:
        print("preflight: this node will NOT start — "
              f"{len(found)} thing(s) missing from its configuration:",
              file=sys.stderr)
        for line in found:
            print(f"  · {line}", file=sys.stderr)
        print("See deploy/openshift/README.md for every variable and its "
              "two forms.", file=sys.stderr)
        return 2
    print("preflight: configuration complete — starting.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
