"""The vocabularies this node has, served (MICRO-PL02 «gestore dei vocabolari»,
residue (1) of MICRO-U, E.D. 18 Nov 2026).

A node is one of the places a vocabulary package comes from (s3Dgraphy's
``carrier_of_origin``: ``node:<host>``). Its folder is the machine's vocabulary
folder of ``s3dgraphy.authorities.packages.vocab_dir()`` — ``EM_VOCABULARIES_DIR``
when set — and what it holds is offered two ways:

* **as packages**, for another machine's vocabulary manager —
  ``GET /v1/vocabularies/catalog.json`` (the catalogue format of
  ``vocab_catalog``) and ``GET /v1/vocabularies/<id>.emvocab.zip[?version=]``,
  the package rebuilt from the folder;
* **as the read routes of EMStudio's desktop bridge** (``tools/em_vocab.py``),
  under ``/v1/vocab/*`` with the same request and answer shapes, so the web page
  works on the node without a bridge: ``installed``, ``search``, ``concepts``,
  ``catalog``, ``updates``.

**Tier C never leaves the node** — not its stub, not a local copy, not a label
found in one: every read below filters to tiers A and B, and the package route
answers 403 with the reason. The routes are public (a tier A/B package is made to
travel); the WRITE routes of the bridge (install, remove, fetch-local) hang off
``v1`` (a token) and also need the node's OPERATOR capability — the same check
as ``/v1/admin/*`` (``operators.is_operator``).

The library facade ``s3dgraphy.vocabularies`` (versions side by side, MICRO-PL02)
is used when present; with an older s3Dgraphy (the pinned dev121 has only
MICRO-U's ``packages``) the folder is read here, in both layouts —
``<dir>/<id>/manifest.json`` and ``<dir>/<id>/<version>/manifest.json`` — and the
zip rebuilt the same way the facade's ``vocab_package_bytes`` does.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from . import auth as auth_module
from . import operators as ops

#: The tiers whose packages may travel (D-16): A with attribution, B as an
#: unmodified file. C is a pointer and a copy on one machine only.
TRAVELLING = ("A", "B")
SUFFIX = ".emvocab.zip"
#: what an installed manifest says about THIS machine, not about the package
_LOCAL_KEYS = ("installed", "carriers", "removed_carriers", "copy_of", "owner")
#: the catalogue's fields, in the order `vocab_catalog` documents them
_CATALOG_KEYS = ("id", "version", "snapshot_date", "title", "languages", "license",
                 "tier", "attribution", "serves", "sha256")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")

#: The routes, declared here and MOUNTED by `main` on its own routers
#: (:func:`mount`): this FastAPI keeps an included router as one opaque entry,
#: so `/docs`' lock (read from `v1.routes`) and the README's route table would
#: not see them. Public reads go on `v1_public`; the writes on `v1` (a token).
_ROUTES: List[Tuple[str, str, str, Dict[str, Any], Any]] = []


def _route(where: str, method: str, path: str, **kw):
    def deco(fn):
        _ROUTES.append((where, method, path, kw, fn))
        return fn
    return deco


class _Declare:
    def __init__(self, where: str):
        self.where = where

    def get(self, path: str, **kw):
        return _route(self.where, "GET", path, **kw)

    def post(self, path: str, **kw):
        return _route(self.where, "POST", path, **kw)


#: public: tiers A/B only, by construction
public = _Declare("public")
#: on `v1` (token) — and each route asks for the operator capability
operated = _Declare("token")


def mount(public_router: APIRouter, token_router: APIRouter) -> None:
    """Add the routes to `main`'s `v1_public` and `v1`."""
    for where, method, path, kw, fn in _ROUTES:
        router = public_router if where == "public" else token_router
        router.add_api_route(path, fn, methods=[method], tags=["vocabularies"], **kw)


# ── the library, whichever version is installed ────────────────────────────

def _packages():
    try:
        from s3dgraphy.authorities import packages
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=(
            "vocabularies unavailable — this build's s3dgraphy has no "
            f"authorities.packages ({exc})"))
    return packages


def _facade():
    """`s3dgraphy.vocabularies` (MICRO-PL02), or None on an older s3Dgraphy."""
    try:
        from s3dgraphy import vocabularies
    except ImportError:
        return None
    return vocabularies if hasattr(vocabularies, "vocab_package_bytes") else None


def _refuse(status: int, error: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error}, status_code=status)


def _vkey(v: Any):
    return [(0, int(x), "") if x.isdigit() else (1, 0, x)
            for x in re.split(r"[.\-+_]", str(v or ""))]


def _newest_first(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (str(r.get("snapshot_date") or ""),
                                       _vkey(r.get("version"))), reverse=True)


# ── the folder, every version ───────────────────────────────────────────────

def _scan(P) -> List[Tuple[Path, Dict[str, Any]]]:
    """``[(folder, manifest)]`` of every installed version, both layouts."""
    root = P.vocab_dir()
    out: List[Tuple[Path, Dict[str, Any]]] = []
    if not root.is_dir():
        return out
    for base in sorted(root.iterdir()):
        if not base.is_dir() or base.name.startswith((".", "_")):
            continue
        if (base / "manifest.json").is_file():
            folders = [base]
        else:
            folders = [f for f in sorted(base.iterdir()) if f.is_dir()
                       and not f.name.startswith(".") and (f / "manifest.json").is_file()]
        for f in folders:
            try:
                m = json.loads((f / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("id"):
                out.append((f, m))
    return out


def _rows(P) -> List[Dict[str, Any]]:
    """One summary per installed VERSION, every tier, with ``status``."""
    V = _facade()
    if V is not None:
        return list(V.vocab_installed(all_versions=True))
    rows = []
    for folder, m in _scan(P):
        src = m.get("source") or {}
        if not src:
            status = "stub"
        elif (folder / str(src.get("file") or "")).is_file():
            status = "ready"
        else:
            status = "broken"
        rows.append({**{k: m.get(k) for k in _CATALOG_KEYS if k != "sha256"},
                     "sha256": src.get("sha256"), "status": status})
    return rows


def _travelling(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The versions that may leave the node: tier A/B, source here."""
    return [r for r in rows if r.get("tier") in TRAVELLING and r.get("status") == "ready"]


def _package_url(vid: str, version: Any, newest: bool) -> str:
    url = f"{vid}{SUFFIX}"
    if not newest:
        url += "?version=" + urllib.parse.quote(str(version), safe="")
    return url


def node_catalog(P) -> List[Dict[str, Any]]:
    """The packages this node serves, in `vocab_catalog`'s format (url relative
    to the catalogue: `<id>.emvocab.zip`, `?version=` when not the newest)."""
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in _travelling(_rows(P)):
        by_id.setdefault(str(r["id"]), []).append(r)
    out = []
    for vid in sorted(by_id):
        for i, r in enumerate(_newest_first(by_id[vid])):
            item = {k: r.get(k) for k in _CATALOG_KEYS}
            item["url"] = _package_url(vid, r.get("version"), newest=(i == 0))
            out.append(item)
    return out


def _fallback_package_bytes(P, vid: str, version: str) -> bytes:
    """The zip `s3dgraphy.vocabularies.vocab_package_bytes` makes, for an
    s3Dgraphy that does not have it yet."""
    for folder, m in _scan(P):
        if m.get("id") != vid or str(m.get("version")) != str(version):
            continue
        if m.get("tier") not in TRAVELLING:
            raise P.PackageError(f"{vid}: tier {m.get('tier')} — not redistributable")
        src = m.get("source") or {}
        path = folder / str(src.get("file") or "")
        if not src.get("file") or not path.is_file():
            raise P.PackageError(f"{vid}: no source here")
        out = {k: v for k, v in m.items() if k not in _LOCAL_KEYS}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(out, ensure_ascii=False, indent=2,
                                                   sort_keys=True))
            z.write(path, src["file"])
        return buf.getvalue()
    raise P.PackageError(f"{vid}: not installed")


# ── the packages, for another machine's manager ─────────────────────────────

_PACKAGE_RESPONSES = {
    200: {"description": "the package, rebuilt from the node's folder",
          "content": {"application/zip": {}}},
    403: {"description": "tier C: it does not leave the node"},
    404: {"description": "not on this node (or not that version)"},
}


@public.get("/vocabularies/catalog.json",
            summary="The vocabulary packages this node serves (tiers A and B)",
            responses={200: {"description": "`{packages: [{id, version, snapshot_date, "
                             "title, languages, license, tier, attribution, serves, "
                             "sha256, url}]}`"}})
def vocabularies_catalog() -> Dict[str, Any]:
    """What another machine's vocabulary manager may install from here — the
    format `s3dgraphy.authorities.packages.vocab_catalog` reads; a relative `url`
    is resolved against this catalogue's. Every installed version of tier A or B
    with its source here; tier C (a stub, a local copy) is never listed."""
    return {"packages": node_catalog(_packages())}


@public.get("/vocabularies/{vocab_id}.emvocab.zip",
            summary="One vocabulary package, rebuilt from the node's folder",
            response_class=Response, responses=_PACKAGE_RESPONSES)
def vocabulary_package(vocab_id: str,
                       version: Optional[str] = Query(None, description="a version "
                                                      "other than the newest")):
    """The `.emvocab.zip` of an installed version — its manifest (minus what it
    says about this machine: who installed it, carriers, owner) and its
    unmodified source, the bytes `vocab_install` checks against the sha256.
    Tier C answers 403: a copy of it never leaves the node."""
    P = _packages()
    if not _ID_RE.match(vocab_id or ""):
        return _refuse(404, f"{vocab_id}: not a vocabulary id")
    mine = [r for r in _rows(P) if r.get("id") == vocab_id]
    if version is not None:
        mine = [r for r in mine if str(r.get("version")) == version]
    if not mine:
        return _refuse(404, f"{vocab_id}{' ' + version if version else ''}: "
                            "not installed on this node")
    served = _newest_first(_travelling(mine))
    if not served:
        if any(r.get("tier") not in TRAVELLING for r in mine):
            return _refuse(403, f"{vocab_id}: tier C — not redistributable; its copy "
                                "stays on the machine that downloaded it (install its "
                                "manifest and «Download locally» from the source)")
        return _refuse(404, f"{vocab_id}: no source on this node")
    chosen = str(served[0].get("version"))
    V = _facade()
    try:
        data = (V.vocab_package_bytes(vocab_id, chosen) if V is not None
                else _fallback_package_bytes(P, vocab_id, chosen))
    except P.PackageError as exc:
        status = 403 if "redistributable" in str(exc) else 404
        return _refuse(status, str(exc))
    name = f"{vocab_id}-{chosen}{SUFFIX}" if version else f"{vocab_id}{SUFFIX}"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── the bridge's read routes, on the node ───────────────────────────────────

def _summary_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """A summary as the bridge gives it, minus this node's paths: where a
    package was installed from is said only when it is an address."""
    out = dict(row)
    origin = str(out.get("installed_from") or "")
    if origin and not origin.startswith(("http://", "https://")):
        out["installed_from"] = None
    out.pop("fetch", None)
    return out


@public.get("/vocab/installed",
            summary="The vocabularies installed on this node (tiers A and B)",
            responses={200: {"description": "`{ok, dir, installed: [summary]}` — the "
                             "bridge's `/vocab/installed`"}})
def vocab_installed() -> Dict[str, Any]:
    """The bridge's `GET /vocab/installed`, on the node: the newest version of
    each id with its `versions`. `dir` is where the packages are served
    (`vocabularies/`), not the node's filesystem."""
    P = _packages()
    V = _facade()
    rows = V.vocab_installed() if V is not None else P.vocab_installed()
    rows = [_summary_out(r) for r in rows if r.get("tier") in TRAVELLING]
    for r in rows:
        if isinstance(r.get("versions"), list):
            r["versions"] = [v for v in r["versions"] if v.get("status") != "stub"]
    return {"ok": True, "dir": "vocabularies/", "installed": rows}


def _travelling_ids(P) -> List[str]:
    return sorted({str(r["id"]) for r in _travelling(_rows(P))})


@public.get("/vocab/search",
            summary="Candidates for a word in this node's vocabularies",
            responses={200: {"description": "`{ok, candidates: [...]}` — exact, then close"}})
def vocab_search(text: str = Query(""), lang: str = Query(""), serves: str = Query(""),
                 limit: str = Query("12")) -> Dict[str, Any]:
    """The bridge's `GET /vocab/search`: exact before close, never an identity;
    with `serves` and nothing found, every vocabulary is asked. Tier C
    vocabularies are not searched."""
    P = _packages()
    try:
        n = int(limit or 12)
    except ValueError:
        return _refuse(422, f"limit: not a number ({limit!r})")
    allowed = _travelling_ids(P)

    def ask(serving):
        got = P.search(text, lang=lang or None, serves=serving, vocabularies=allowed, limit=n)
        return [c for c in got if c.get("tier") in TRAVELLING]
    got = ask(serves or None)
    if not got and serves:
        got = ask(None)
    return {"ok": True, "candidates": got}


@public.get("/vocab/concepts",
            summary="The concepts of some URIs, from this node's vocabularies",
            responses={200: {"description": "`{ok, concepts: {uri: {concept, vocab}}}`"}})
def vocab_concepts(uri: List[str] = Query([])) -> Dict[str, Any]:
    """The bridge's `GET /vocab/concepts?uri=…&uri=…`: each URI found in an
    installed vocabulary of tier A or B, with that vocabulary's summary."""
    P = _packages()
    pairs = [(s, idx) for s, idx in P.ready_vocabularies() if s.get("tier") in TRAVELLING]
    out: Dict[str, Any] = {}
    for u in uri:
        for s, idx in pairs:
            c = (idx.get("concepts") or {}).get(u)
            if c is not None:
                out[u] = {"concept": c, "vocab": _summary_out(s)}
                break
    return {"ok": True, "concepts": out}


def _central_catalog(P, url: str):
    """The central catalogue only: the node does not fetch an address a caller
    names (a public route that fetched any URL would be a proxy)."""
    if url and url != P.CENTRAL_CATALOG_URL:
        raise ValueError("on a node, `url` may only be the central catalogue "
                         f"({P.CENTRAL_CATALOG_URL}); this node's own is "
                         "/v1/vocabularies/catalog.json")
    return P.vocab_catalog(P.CENTRAL_CATALOG_URL)


@public.get("/vocab/catalog",
            summary="The packages the central vocabulary repository offers",
            responses={200: {"description": "`{ok, packages: [...]}`"},
                       400: {"description": "a `url` other than the central catalogue"},
                       502: {"description": "the central catalogue is not reachable"}})
def vocab_catalog(url: str = Query("")) -> Dict[str, Any]:
    """The bridge's `GET /vocab/catalog`, fetched by the node (the page cannot
    read GitHub's release across origins). Only the central catalogue."""
    P = _packages()
    try:
        return {"ok": True, "packages": _central_catalog(P, url)}
    except ValueError as exc:            # PackageError is a ValueError too
        return _refuse(422 if isinstance(exc, P.PackageError) else 400, str(exc))
    except OSError as exc:
        return _refuse(502, f"not reachable: {exc}")


@public.get("/vocab/updates",
            summary="What the central repository has newer than this node",
            responses={200: {"description": "`{ok, updates: [{id, installed, available, url}]}`"},
                       400: {"description": "a `url` other than the central catalogue"},
                       502: {"description": "the central catalogue is not reachable"}})
def vocab_updates(url: str = Query("")) -> Dict[str, Any]:
    """The bridge's `GET /vocab/updates`, against what THIS node has."""
    P = _packages()
    try:
        cat = _central_catalog(P, url)
        allowed = set(_travelling_ids(P))
        return {"ok": True, "updates": [u for u in P.vocab_updates(cat) if u.get("id") in allowed]}
    except ValueError as exc:
        return _refuse(422 if isinstance(exc, P.PackageError) else 400, str(exc))
    except OSError as exc:
        return _refuse(502, f"not reachable: {exc}")


# ── the bridge's write routes: operators only ───────────────────────────────

def _require_operator(request: Request) -> None:
    """The check `/v1/admin/*` makes (`main._require_operator`), here so the
    router does not import `main`."""
    principal = auth_module.authenticator.require_token(request)
    if not ops.is_operator(principal):
        raise HTTPException(status_code=403, detail=ops.refusal())


_WRITE_RESPONSES = {403: {"description": "not an operator of this node"},
                    422: {"description": "the package does not hold"},
                    502: {"description": "the address is not reachable"}}


def _write(fn):
    P = _packages()
    try:
        return fn(P)
    except P.PackageError as exc:
        return _refuse(422, str(exc))
    except OSError as exc:
        return _refuse(502, f"not reachable: {exc}")


@operated.post("/vocab/install",
               summary="Install a vocabulary package on this node (operators)",
               responses={200: {"description": "`{ok, installed: summary}`"},
                          400: {"description": "neither `url` nor `zip_b64`"},
                          **_WRITE_RESPONSES})
def vocab_install(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """The bridge's `POST /vocab/install` — `{url}` or `{zip_b64}`; the sha256
    checked and the index compiled here. A tier C package carrying its source
    is refused by the library."""
    _require_operator(request)
    if body.get("zip_b64"):
        try:
            src: Any = base64.b64decode(body["zip_b64"])
        except ValueError:
            return _refuse(400, "zip_b64: not base64")
    elif str(body.get("url") or "").startswith(("http://", "https://")):
        src = body["url"]
    else:
        return _refuse(400, "install takes {url} or {zip_b64}")
    return _write(lambda P: {"ok": True, "installed": P.vocab_install(src)})


@operated.post("/vocab/remove",
               summary="Remove a vocabulary from this node (operators)",
               responses={200: {"description": "`{ok, removed}`"}, **_WRITE_RESPONSES})
def vocab_remove(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """The bridge's `POST /vocab/remove {id}`."""
    _require_operator(request)
    return _write(lambda P: {"ok": True, "removed": P.vocab_remove(str(body.get("id") or ""))})


@operated.post("/vocab/fetch-local",
               summary="Download a tier C source onto this node only (operators)",
               responses={200: {"description": "`{ok, installed: summary}`"}, **_WRITE_RESPONSES})
def vocab_fetch_local(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """The bridge's `POST /vocab/fetch-local {id}`: the copy stays on the node and
    no route above hands it on."""
    _require_operator(request)
    return _write(lambda P: {"ok": True,
                             "installed": P.vocab_fetch_local(str(body.get("id") or ""))})
