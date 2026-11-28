"""ONE DOOR: an object and its story, in the same request.

Decision of E.D., 27 November 2026. Until today a deposit into a room's bucket
took five acts — a PUT of the bytes, a PUT of the stamp and three acts on the
corpus — and any of them could be forgotten. It usually was. The window between
the first act and the last is exactly the «bytes with no story» this router
closes: here the record is read first, and the bytes enter the store only once
it holds.

The record's shape is **`em-bucket-dtc/1`**, the profile EMStudio already writes
(`frontend/src/bucket-dtc.ts`, `bucketRequest`). The server adopts the client's
profile rather than asking every tool of the ecosystem to learn a second one,
and the same body serves EM Tools, 3DSC, StratiField and a partner's own tool.

Three rules hold whatever a caller declares:

* **the depositor comes from the token**, never from the body — nobody deposits
  in somebody else's name;
* **the minimal fields are minimal for every formalism** (`dtc`, `prov-o`,
  `other`): admitting another vocabulary is not admitting a mute deposit;
* **a refusal is a sentence naming the field**, because a client that is told
  «422» learns nothing it can act on.

What is NOT here, and is not pretended to be: the resumable door for a large
object, and the route that takes an already-emitted `.stamp.json`. Both have
their place in the plan; neither is promised by a field that would always be
null, so `stamp_ref` is absent until the server really links a stamp.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .assets import asset_ref_valid
from . import accredited as accredited_module

#: The profile this router reads. Versioned in its own name: a server that one
#: day reads `em-bucket-dtc/2` must be able to say which one a body speaks.
PROFILE = "em-bucket-dtc/1"

#: The formalisms a caller may declare. `dtc` is recommended because dtcstamp is
#: one file without dependencies; the others are admitted with the same minimum.
FORMALISMS = ("dtc", "prov-o", "other")

#: The ceiling of ONE post, the same 64 MiB `s3dgraphy.room_import` observes for
#: a single PUT. Above it the bytes go through the resumable door; this route
#: does not pretend to stream a lot that needs resuming.
SINGLE_POST_LIMIT = 64 * 1024 * 1024

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URI = re.compile(r"^https?://\S+$", re.I)
_DOI = re.compile(r"^(doi:)?10\.\d{4,9}/\S+$", re.I)


class ObjectDeposit(BaseModel):
    """What the node answers once the object is in and described."""

    ref: str = Field(description="sha256:<hex> — the object's address")
    created: bool = Field(description="false when the node already held these bytes")
    size: int
    media_type: str
    #: the room these bytes came in through (their home, F1)
    home: Optional[str] = None
    #: the lot the acquisition act landed in, as the register named it
    acquisition_id: Optional[str] = None
    #: who answers for publishing: an accredited iD, or the depositor
    responsible: Optional[str] = None
    #: what the register did, act by act — passed through, never summarised
    acts: Dict[str, Any] = Field(default_factory=dict)


class ObjectStory(BaseModel):
    """One object's whole story, in one read."""

    ref: str
    room: str
    #: whether this node HOLDS the bytes. «I do not know this file» and «this
    #: file has no story» are different answers, and both are said here.
    held: bool
    media_type: Optional[str] = None
    size: Optional[int] = None
    #: the room these bytes came in through (F1)
    home: Optional[str] = None
    #: the stamp bound to this object, when one has been. Absent until the
    #: stamp route exists: a field that was always null would be a promise.
    stamp_ref: Optional[str] = None
    #: the register's slice about this digest — the shape `GET /v1/corpus` gives
    corpus: Dict[str, Any] = Field(default_factory=dict)
    #: what made it and what it went on to make, the walk `GET
    #: /v1/corpus/neighbourhood` performs
    neighbourhood: Dict[str, Any] = Field(default_factory=dict)
    #: the corpus version both of them came out of
    version: str = ""


def _text(block: Any, key: str) -> str:
    value = (block or {}).get(key) if isinstance(block, dict) else None
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def _kinds() -> Tuple[Tuple[str, ...], Any]:
    from s3dgraphy.utils.utils import get_dtc_kinds, get_dtc_kind_family

    return tuple(get_dtc_kinds().get("acquisition", ()) or ()), get_dtc_kind_family


def _is_capture(kind: str) -> bool:
    from s3dgraphy.dtc.capture import is_capture

    return bool(is_capture(kind))


def _refusal(record: Dict[str, Any], room_id: str, *, bytes_travel: bool) -> Optional[str]:
    """Why this deposit cannot be written, in one sentence, or None.

    The same rules EMStudio's `dtcProblem` applies before it offers the button,
    said here as well: a client is free to be wrong, a register is not.
    """
    if not isinstance(record, dict):
        return "the `dtc` part is not an object"
    profile = _text(record, "profile")
    if profile != PROFILE:
        return (f"this door reads the profile {PROFILE!r}, and the body declares "
                f"{profile or 'none'!r}: GET /v1/dtc/profile/{PROFILE} says what it holds")
    formalism = _text(record, "formalism") or "dtc"
    if formalism not in FORMALISMS:
        return (f"`formalism` is {formalism!r}: this door reads "
                f"{', '.join(FORMALISMS)}")

    obj = record.get("object") or {}
    if not _text(obj, "media_type"):
        return "`object.media_type` is missing: the register describes a file by what it is"
    if not bytes_travel and not _text(obj, "sha256"):
        return ("no file part and no `object.sha256`: say which bytes this record "
                "is about, or send them")

    source = record.get("source") or {}
    kind = _text(source, "dtc_kind")
    kinds, _family = _kinds()
    if not kind:
        return "`source.dtc_kind` is missing: an object comes from an act, and the act has a kind"
    if kinds and kind not in kinds:
        return (f"`source.dtc_kind` {kind!r} is not in the vocabulary's acquisition "
                f"axis: {', '.join(sorted(kinds))}")
    retrieved = _text(source, "retrieved_from")
    if kind == "download" and not retrieved:
        return "a download says where from: `source.retrieved_from` (a URL or a DOI)"
    if retrieved and not (_URI.match(retrieved) or _DOI.match(retrieved)):
        return (f"`source.retrieved_from` is read as a locator: {retrieved!r} is "
                f"neither a URL nor a DOI — prose belongs in `source.note`")

    made_at = _text(record.get("when"), "made_at")
    if made_at and not _DATE.match(made_at):
        return f"`when.made_at` is a date (YYYY-MM-DD), not {made_at!r}"
    capture = _is_capture(kind)
    if capture and not made_at:
        return ("a capture IS the act that made the bytes, so it says when: "
                "`when.made_at`")

    transformation = record.get("transformation") or {}
    if not capture and (_text(transformation, "technique")
                        or _text(transformation, "software")):
        return ("a technique and a software say how the bytes were MADE: on a "
                "retrieval they would be a false claim — leave `transformation` empty")

    rights = record.get("rights") or {}
    if not _text(rights, "license"):
        return "`rights.license` is missing: bytes nobody may use are bytes nobody will"
    embargo = _text(rights, "embargo_until")
    if embargo and not _DATE.match(embargo):
        return f"`rights.embargo_until` is a date (YYYY-MM-DD), not {embargo!r}"

    target = record.get("target") or {}
    room = _text(target, "room")
    if room and room != room_id:
        return (f"`target.room` says {room!r} and the call was made on {room_id!r}: "
                f"one of the two is a mistake, and the server will not choose")
    return None


def _lot_already_is(graph_doc: Dict[str, Any], lot_id: str) -> Optional[str]:
    """The kind of act the register already records for this lot, or None.

    Measured on 28 November 2026: appending an acquisition with an id that
    exists and a DIFFERENT `dtc_kind` is merged in silence — the lot keeps the
    first kind and the new file joins it, with no warning in the answer. So a
    survey and a download deposited under one lot become, in the register, one
    survey. The library is right not to guess which of the two is wrong; the
    door is the place to refuse.
    """
    for node in (graph_doc or {}).get("nodes") or []:
        if str(node.get("id")) != lot_id:
            continue
        kind = (node.get("data") or {}).get("dtc_kind")
        return str(kind) if isinstance(kind, str) and kind.strip() else None
    return None


def _facts(record: Dict[str, Any], responsible: Optional[str]) -> Dict[str, Any]:
    """The acquisition's open block — the facts of the act that are not claims
    about how the bytes were made. Same keys EMStudio writes, so a deposit from
    the desktop and one from a partner's tool read the same in the register."""
    source = record.get("source") or {}
    target = record.get("target") or {}
    transformation = record.get("transformation") or {}
    kind = _text(source, "dtc_kind")
    capture = _is_capture(kind)
    facts: Dict[str, Any] = {}
    for key, value in (("retrieved_from", _text(source, "retrieved_from")),
                       ("source_note", _text(source, "note"))):
        if value:
            facts[key] = value
    made_at = _text(record.get("when"), "made_at")
    if made_at and not capture:
        facts["content_date"] = made_at
    if capture:
        for key, value in (("campaign", _text(source, "campaign")),
                           ("technique", _text(transformation, "technique")),
                           ("software", _text(transformation, "software"))):
            if value:
                facts[key] = value
    if _text(target, "document_id"):
        facts["documents"] = _text(target, "document_id")
    formalism = _text(record, "formalism") or "dtc"
    if formalism != "dtc":
        facts["formalism"] = formalism
        statement = record.get("statement")
        if statement not in (None, "", {}):
            facts["statement"] = statement
    if responsible:
        # D8 · who answers for publishing when it is not the depositor. It lives
        # in the act's facts because that is where a fact about the act lives;
        # the register has no field of its own for it yet, and inventing one in
        # the server would be a dialect.
        facts["responsible"] = responsible
    return facts


async def post_object(room_id: str, request: Request) -> ObjectDeposit:
    """Bytes and their provenance in one request.

    **Two shapes, one door.** `multipart/form-data` with the part `dtc` (the
    record, JSON) FIRST and then `file` — the order is required, so that the
    record can be refused before the body is read, and so a streaming parser can
    do exactly that tomorrow without the clients changing. Or
    `application/json`: the record alone, with `object.sha256` of bytes the node
    already holds.

    **Who may**: editor or above in the room. The old `PUT …/asset` asks only for
    a valid token — anybody could put bytes into any room's name — and that is
    one of the reasons this door exists.

    **Nothing enters the store before the record holds.** A refused deposit
    leaves no orphan bytes, which is the property the test asserts by looking at
    the store rather than at the answer.
    """
    from . import uploads
    from . import main as main_module
    from .main import CorpusAct, _acting_role, _record_home, _store_file

    # THE CEILING FIRST, from the length the client declares: refusing after
    # reading 2 GB is not refusing, it is reading 2 GB and then saying no.
    declared_length = request.headers.get("content-length") or ""
    if declared_length.isdigit() and int(declared_length) > SINGLE_POST_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=(f"over {SINGLE_POST_LIMIT // (1024 * 1024)} MiB this door does "
                    f"not take a deposit in one piece: send the bytes through "
                    f"POST /v1/rooms/{room_id}/uploads, which resumes"))

    # THE ROLE SECOND, before any body: a caller who may not write must not cost
    # a disk write either.
    _acl, _room, role, who = await _acting_role(room_id, request)
    if role is None or not getattr(role, "can_write", False):
        raise HTTPException(
            status_code=403,
            detail=f"depositing in {room_id} takes editor or above")

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    upload = None
    if content_type == "multipart/form-data":
        form = await request.form()
        items = list(form.multi_items())
        if not items or items[0][0] != "dtc":
            raise HTTPException(
                status_code=400,
                detail="the `dtc` part comes first and the `file` part after it: "
                       "the record is read before the bytes, not beside them")
        raw = items[0][1]
        if not isinstance(raw, str):
            raw = (await raw.read()).decode("utf-8", "replace")
        try:
            record = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"the `dtc` part is not JSON: {exc}") from None
        upload = form.get("file")
        if upload is not None and isinstance(upload, str):
            upload = None
    elif content_type == "application/json":
        try:
            record = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"the body is not JSON: {exc}") from None
    else:
        raise HTTPException(
            status_code=415,
            detail="this door reads multipart/form-data (`dtc` then `file`) or "
                   "application/json (the record alone)")

    refusal = _refusal(record, room_id, bytes_travel=upload is not None)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)

    # D8 · the responsible is an iD this node has accredited, or nobody.
    who_block = record.get("who") or {}
    responsible = _text(who_block, "responsible") or None
    if responsible and not accredited_module.is_accredited(responsible):
        raise HTTPException(
            status_code=422,
            detail=(f"{responsible} is not accredited on this node, so it cannot "
                    f"be the one who answers for this object: accredit the iD "
                    f"first, or leave `who.responsible` out and the depositor "
                    f"answers"))
    responsible = responsible or who

    obj = record.get("object") or {}
    media_type = _text(obj, "media_type") or "application/octet-stream"

    if upload is not None:
        temp = uploads.SESSIONS.temp_file()
        hasher = hashlib.sha256()
        size = 0
        try:
            with temp.open("wb") as out:
                while True:
                    chunk = await upload.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > SINGLE_POST_LIMIT:
                        raise HTTPException(
                            status_code=413,
                            detail=(f"over {SINGLE_POST_LIMIT // (1024 * 1024)} MiB "
                                    f"this door does not take a deposit in one "
                                    f"piece: send the bytes through "
                                    f"POST /v1/rooms/{room_id}/uploads, which resumes"))
                    hasher.update(chunk)
                    out.write(chunk)
            if not size:
                raise HTTPException(status_code=400,
                                    detail="the `file` part is empty: nothing to store")
            digest = hasher.hexdigest()
            declared = _text(obj, "sha256")
            wanted = uploads.normalise_sha256(declared) if declared else None
            if declared and wanted is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"`object.sha256` is not a sha256: {declared!r}")
            if wanted and wanted != digest:
                raise HTTPException(
                    status_code=422,
                    detail=(f"the bytes that arrived are sha256:{digest}, not the "
                            f"sha256:{wanted} the record declares — nothing was "
                            f"stored; send them again"))
            info = await _store_file(temp, digest, size, media_type)
        finally:
            temp.unlink(missing_ok=True)
        ref = str(info.get("ref") or f"sha256:{digest}")
        created = bool(info.get("created", True))
        size = int(info.get("size") or size)
        media_type = str(info.get("media_type") or media_type)
    else:
        declared = _text(obj, "sha256")
        ref = declared if declared.startswith("sha256:") else f"sha256:{declared}"
        if not asset_ref_valid(ref):
            raise HTTPException(status_code=400,
                                detail=f"not an asset reference: {ref!r} "
                                       f"(expected 'sha256:<hex>')")
        # main's store, not a copy of the import: a test (and an operator's
        # monkeypatch) swaps it in ONE place, and a door reading its own
        # reference would be looking into a different bucket than the gate.
        held = main_module.ASSET_STORE.head(ref)
        if held is None:
            raise HTTPException(
                status_code=404,
                detail=(f"this node holds no {ref}: send the bytes in the same "
                        f"request (the `file` part) — a record about bytes that "
                        f"are not here describes nothing"))
        created = False
        size = int((held or {}).get("size") or 0) if isinstance(held, dict) else 0
        if not size:
            try:
                size = int(_text(obj, "size_bytes") or 0)
            except ValueError:
                size = 0

    home = _record_home(ref, room_id, who)

    # THE THREE ACTS, in the order a reader needs them: the file exists, whose
    # it is and under which licence, and which lot brought it in. Each one is
    # the library's, through the same adapter `POST /v1/corpus/append` uses, so
    # a deposit made here and one made by hand leave the same register behind.
    def act(**fields: Any) -> Dict[str, Any]:
        one = CorpusAct(**fields)
        try:
            report, _version = main_module.RESIDENT.append(
                one.act, one.model_dump(exclude_none=True), author=who)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return report or {}

    rights = record.get("rights") or {}
    target = record.get("target") or {}
    source = record.get("source") or {}
    kind = _text(source, "dtc_kind")
    made_at = _text(record.get("when"), "made_at")

    # A LOT IS ONE ACT. Joining a lot whose kind is not this deposit's would be
    # taken in silence by the register (measured), and the file would end up
    # described by somebody else's act.
    lot_id = _text(target, "lot_id")
    if lot_id:
        was = _lot_already_is(main_module.RESIDENT.read(), lot_id)
        if was and was != kind:
            raise HTTPException(
                status_code=409,
                detail=(f"the lot {lot_id!r} is a {was!r} and this deposit is a "
                        f"{kind!r}: a lot is one act, so either send this file "
                        f"under a lot of its own or say the same kind"))

    acts: Dict[str, Any] = {}
    acts["resource"] = act(act="resource", checksum=ref, media_type=media_type,
                           name=_text(obj, "name") or None,
                           size=size or None, residency="resident")
    acts["attribution"] = act(act="attribution", checksum=ref,
                              author=_text(who_block, "author_orcid") or None,
                              author_name=_text(who_block, "author") or None,
                              license=_text(rights, "license"),
                              embargo=_text(rights, "embargo_until") or None,
                              reason=_text(rights, "embargo_reason") or None,
                              at=made_at if _is_capture(kind) else None)
    acquisition = act(act="acquisition", resources=[ref], dtc_kind=kind,
                      acquisition_id=_text(target, "lot_id") or None,
                      name=_text(target, "lot_name") or None,
                      metadata=_facts(record, responsible) or None,
                      at=made_at if _is_capture(kind) else None)
    acts["acquisition"] = acquisition

    lot = acquisition.get("acquisition_id") or acquisition.get("id") \
        or (_text(target, "lot_id") or None)
    return ObjectDeposit(ref=ref, created=created, size=size,
                         media_type=media_type, home=home,
                         acquisition_id=lot if isinstance(lot, str) else None,
                         responsible=responsible, acts=acts)


async def get_object_story(room_id: str, sha: str, request: Request) -> ObjectStory:
    """Everything the node can say about one object, in one request.

    Written on 28 November 2026 because EMStudio had to ask three times — the
    register's slice, the walk, and the store — to show one file's provenance,
    and a client that must join three answers is a client that will join them
    differently from the next one.

    **Who may**: somebody who has a role in the room. The bytes are not here,
    only what is said about them, but what is said about them names people and
    licences, and a room is where that belongs.

    `stamp_ref` is null until a stamp has been bound to the object: the binding
    arrives with `POST …/objects/{sha}/stamp`, and until then EMStudio keeps
    sending the stamp as a file of its own — which is honest, and which this
    field will make unnecessary rather than pretend to have done.
    """
    from s3dgraphy.dtc import neighbourhood_of_digest
    from s3dgraphy.dtc.neighbourhood import DEFAULT_HOPS

    from . import main as main_module
    from .main import _acting_role

    _acl, _room, role, _who = await _acting_role(room_id, request)
    if role is None:
        raise HTTPException(
            status_code=403,
            detail=f"the story of a file in {room_id} is told to the people of "
                   f"that room")

    ref = sha if str(sha).startswith("sha256:") else f"sha256:{sha}"
    if not asset_ref_valid(ref):
        raise HTTPException(status_code=400,
                            detail=f"not an asset reference: {ref!r} "
                                   f"(expected 'sha256:<hex>')")
    digest = ref.split(":", 1)[1]

    held = main_module.ASSET_STORE.head(ref)
    # «I cannot read the register» is not «there is nothing in the register»,
    # and a client that cannot tell them apart will show an empty provenance
    # panel for a store that is down (asked for by EMStudio, 28 Nov 2026).
    try:
        graph, version = main_module.RESIDENT.graph()
        walk = neighbourhood_of_digest(graph, digest, hops=DEFAULT_HOPS)
        slice_ = main_module.RESIDENT.read_slice([digest])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — whatever a store fails with
        raise HTTPException(
            status_code=503,
            detail=(f"this node cannot read its register right now ({exc}): "
                    f"the story of {ref} is unknown, which is not the same as "
                    f"empty")) from None

    from . import asset_homes as homes_module

    home = homes_module.ASSET_HOMES.home(ref)
    told = {"graph": slice_} if not isinstance(slice_, dict) else slice_
    return ObjectStory(
        ref=ref, room=room_id, held=held is not None,
        media_type=(held or {}).get("media_type") if isinstance(held, dict) else None,
        size=(held or {}).get("size") if isinstance(held, dict) else None,
        home=home, stamp_ref=_stamp_of(told),
        corpus=told, neighbourhood=walk, version=version)


class StampBound(BaseModel):
    """What the node answers once a stamp speaks for an object."""

    ref: str = Field(description="the object the stamp is about")
    stamp_ref: str = Field(description="the stamp, stored as an object of its own")
    created: bool = Field(description="false when this node already held the stamp's bytes")
    bound: bool = Field(description="false when the link was already there: binding twice is not an error")


async def post_object_stamp(room_id: str, sha: str, request: Request) -> StampBound:
    """Bind an already-emitted stamp to the object it speaks for.

    The stamp is a `.stamp.json` somebody else emitted — EM Tools, 3DSC, the
    EMStudio bridge — and the node does not make one: emitting is the tool's
    act, and a server that re-emitted would be signing a statement it did not
    witness. What the node does is keep the bytes and write the LINK, so that
    one read of the object's story carries the stamp with it instead of leaving
    a client to guess which file in the store speaks for which object.

    **Accepted by digest.** The stamp says which object it is about
    (`self.digest`); if that is not the object in the path, it is refused. A
    stamp cannot be filed against the wrong file by a typo in a URL.

    **Idempotent, and it does not overwrite.** The same stamp twice is one
    binding and `bound: false` the second time. A DIFFERENT stamp on an object
    that already has one is `409`: a stamp is a dated statement, and replacing
    one in silence would make the register say that the first was never made.
    An erratum is a new stamp on a new object, which is what dtcstamp says too.

    **Who may**: editor or above in the room, as for a deposit.
    """
    import hashlib
    import json as _json

    from . import main as main_module
    from .main import CorpusAct, _acting_role, _record_home

    _acl, _room, role, who = await _acting_role(room_id, request)
    if role is None or not getattr(role, "can_write", False):
        raise HTTPException(
            status_code=403,
            detail=f"binding a stamp in {room_id} takes editor or above")

    ref = sha if str(sha).startswith("sha256:") else f"sha256:{sha}"
    if not asset_ref_valid(ref):
        raise HTTPException(status_code=400,
                            detail=f"not an asset reference: {ref!r} "
                                   f"(expected 'sha256:<hex>')")
    digest = ref.split(":", 1)[1]
    if main_module.ASSET_STORE.head(ref) is None:
        raise HTTPException(
            status_code=404,
            detail=(f"this node holds no {ref}: a stamp speaks for an object, "
                    f"so the object comes first"))

    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="the body is the stamp, and it is empty")
    try:
        stamp = _json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400,
                            detail=f"the stamp is not JSON: {exc}") from None
    if not isinstance(stamp, dict) or not isinstance(stamp.get("self"), dict):
        raise HTTPException(
            status_code=422,
            detail="a stamp has a `self` block saying which object it is about")
    said = str((stamp.get("self") or {}).get("digest") or "").strip()
    said_hex = said.split(":", 1)[1] if said.startswith("sha256:") else said
    if not said_hex:
        raise HTTPException(
            status_code=422,
            detail="the stamp's `self.digest` is empty: a stamp that does not "
                   "say which object it is about cannot be bound to one")
    if said_hex.lower() != digest.lower():
        raise HTTPException(
            status_code=422,
            detail=(f"this stamp speaks for sha256:{said_hex} and the object in "
                    f"the path is {ref}: a stamp is filed against the file it "
                    f"names, never against the one a URL names"))

    # THE LINK FIRST, as a question: a stamp already bound and different is a
    # refusal, and a refusal must not leave new bytes behind.
    story = main_module.RESIDENT.read_slice([digest])
    already = _stamp_of(story if isinstance(story, dict) else {})

    body = _json.dumps(stamp, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
    stamp_digest = hashlib.sha256(body).hexdigest()
    stamp_ref = f"sha256:{stamp_digest}"
    if already and already != stamp_ref:
        raise HTTPException(
            status_code=409,
            detail=(f"{ref} already has a stamp ({already}) and this is another "
                    f"one ({stamp_ref}): a stamp is a dated statement, so an "
                    f"erratum is a new stamp on a new object, not a quiet "
                    f"replacement"))

    kept = main_module.ASSET_STORE.put(body, "application/json")
    _record_home(str(kept.get("ref") or stamp_ref), room_id, who)

    def act(**fields: Any) -> Dict[str, Any]:
        one = CorpusAct(**fields)
        try:
            report, _version = main_module.RESIDENT.append(
                one.act, one.model_dump(exclude_none=True), author=who)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return report or {}

    # the stamp is a file of this node too: the register knows it exists…
    act(act="resource", checksum=stamp_ref, media_type="application/json",
        residency="resident", size=len(body), scope="stamp",
        name=f"stamp of {digest[:12]}…")
    # …and the object carries the link to it
    act(act="resource", checksum=ref, dtc_stamp=stamp_ref)

    return StampBound(ref=ref, stamp_ref=stamp_ref,
                      created=bool(kept.get("created", True)),
                      bound=already != stamp_ref)


def _stamp_of(slice_: Dict[str, Any]) -> Optional[str]:
    """The stamp bound to the object in the register, when one is.

    Reads `data.dtc_stamp` off the resource node — the key D5 names. Nothing
    writes it yet; it is read here so that the day the stamp route does, this
    answer carries it without a second deployment.
    """
    for node in (slice_ or {}).get("nodes") or []:
        value = (node.get("data") or {}).get("dtc_stamp")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def dtc_profile() -> Dict[str, Any]:
    """The profile `em-bucket-dtc/1`, so a tool can be written against something
    readable rather than against an example.

    The acquisition kinds are READ from the datamodel, never listed by hand: a
    kind added to the vocabulary is offered here the same day, and a server that
    answered a frozen list would be teaching partners a vocabulary it no longer
    speaks.
    """
    kinds, family = _kinds()
    return {
        "profile": PROFILE,
        "formalisms": list(FORMALISMS),
        "single_post_limit_bytes": SINGLE_POST_LIMIT,
        "required": ["object.media_type", "source.dtc_kind", "rights.license",
                     "object.sha256 (when the bytes do not travel)",
                     "source.retrieved_from (a download)",
                     "when.made_at (a capture)"],
        "the_depositor": "the token's identity, never a field of the body",
        "acquisition_kinds": [
            {"kind": k, "family": family(k) or ""} for k in sorted(kinds)
        ],
        "blocks": {
            "object": ["sha256", "name", "media_type", "size_bytes"],
            "who": ["author", "author_orcid", "responsible"],
            "when": ["made_at"],
            "source": ["dtc_kind", "family", "retrieved_from", "note", "campaign"],
            "transformation": ["technique", "software"],
            "rights": ["license", "embargo_until", "embargo_reason"],
            "target": ["room", "graph_id", "document_id", "lot_id", "lot_name"],
        },
    }


def mount(token_router: APIRouter) -> None:
    """Add the two routes to `main`'s `v1` — the router that carries the token.

    Mounted rather than kept on a router of this module's own, for one measured
    reason: the lock shown in `/docs`, and the test that holds the documentation
    to the code, read the authenticated routes from `v1` itself. A second router
    with the same dependency would be as closed in fact and open in the
    documentation, which is the one kind of disagreement a door must not have.
    """
    token_router.add_api_route(
        "/rooms/{room_id}/objects", post_object, methods=["POST"],
        response_model=ObjectDeposit, tags=["assets"],
        summary="Deposit an object and the record that says where it comes from")
    token_router.add_api_route(
        "/rooms/{room_id}/objects/{sha}/stamp", post_object_stamp, methods=["POST"],
        response_model=StampBound, tags=["assets"],
        summary="Bind an already-emitted stamp to the object it speaks for")
    token_router.add_api_route(
        "/rooms/{room_id}/objects/{sha}/dtc", get_object_story, methods=["GET"],
        response_model=ObjectStory, tags=["assets"],
        summary="Everything this node can say about one object, in one read")
    token_router.add_api_route(
        "/dtc/profile/" + PROFILE, dtc_profile, methods=["GET"],
        response_model=Dict[str, Any], tags=["assets"],
        summary="The shape of a deposit's record, with its vocabulary inside")
