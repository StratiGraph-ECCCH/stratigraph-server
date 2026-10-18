"""The S3 client, built in ONE place for every store that talks to the bucket.

Four things on this node talk to the object store — the assets
(`assets.S3AssetStore`), the `.blend` archive (`blend_backups.S3BackupBlobs`),
the resident corpus (`corpus.S3CorpusStore`) and the two probes that knock on it
(`reach.probe_s3`, `node_health._probe_s3`). They used to build their client
four times, each with its own idea of the endpoint; the settings that make a
client talk to an S3-compatible server that is NOT Amazon are exactly the ones
that are easy to get right three times and wrong the fourth. So they are here.

**`boto3`, plain S3.** The service behind the endpoint is any S3-compatible
store — RustFS in the dev stack, whatever the institution runs in production —
and nothing on this node uses anything beyond the standard operations
(HeadBucket, CreateBucket, HeadObject, PutObject — multipart for a big file —,
GetObject with a Range, DeleteObject, ListObjectsV2 for a bounded count).

What a store that is not AWS needs from the client, each for a reason:

* **path-style addressing** (`http://host:9000/<bucket>/<key>`). The default,
  virtual-host style, puts the bucket in the HOST NAME (`<bucket>.rustfs`),
  which resolves on Amazon and nowhere on a container network;
* **a region, `us-east-1` unless told otherwise.** SigV4 signs with one; an
  S3-compatible server accepts the default, and it is also the one region in
  which `CreateBucket` takes no `LocationConstraint`;
* **signature v4**, said rather than inherited;
* **checksums only when the operation requires them.** botocore ≥ 1.36 adds a
  CRC trailer to every upload by default, a recent AWS feature that not every
  S3-compatible server speaks; asked for only when required, the request is
  the one every store has always understood;
* **no proxy from the environment.** The endpoint is an internal service
  (`http://rustfs:9000`); a process that inherits `HTTPS_PROXY` must not send
  its bucket traffic to the corporate proxy — the previous client never did,
  and this one keeps it that way;
* **bounded time.** A connect timeout that says «not answering» in seconds, a
  read timeout generous enough for a large part, and a few retries in the
  `standard` mode — a store that blinks is retried, one that is gone is
  reported quickly enough for start-up to refuse with a sentence.

`boto3` is an OPTIONAL dependency (`pip install StratiGraph Server[s3]`). This
module imports it inside `make_client`, so importing the module costs nothing
on a node that keeps its bytes in a directory; the stores catch the
`ImportError` and turn it into their own sentence.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

#: The region a store gets when nobody names one. Not a guess about where the
#: bytes are: it is the region SigV4 signs with and S3-compatible servers accept.
DEFAULT_REGION = "us-east-1"

#: Seconds to open a connection. Short on purpose: the store is on the same
#: network as the node, and a connection that takes longer than this is not
#: coming.
CONNECT_TIMEOUT = 5.0

#: Seconds between two reads on an open connection — the bound on a stall, not on
#: a transfer, so a large object is not cut off by it.
READ_TIMEOUT = 60.0

#: Attempts per call, the first included (`standard` retry mode: backoff, and
#: only the errors worth repeating).
MAX_ATTEMPTS = 3

#: The ways an S3 server says «there is no such thing». A HEAD has no body, so a
#: missing object or bucket answered to `head_object`/`head_bucket` arrives as
#: the bare status (`404`); a GET carries the S3 code (`NoSuchKey`). Both, and
#: `NotFound` / `NoSuchBucket`, are the same fact for the callers here.
NOT_FOUND_CODES = frozenset({"NoSuchKey", "NoSuchObject", "NotFound",
                             "NoSuchBucket", "404"})


def endpoint_url(endpoint: str, secure: bool) -> str:
    """`scheme://host[:port]` — the host from the endpoint, the scheme from
    `secure`.

    The settings carry both an endpoint (`http://rustfs:9000`, or a bare
    `rustfs:9000`) and a `secure` flag, and the flag has always been what
    decides: `assets._s3_settings` derives it from the endpoint's scheme when
    it is not stated, and an operator who states it means it.
    """
    host = str(endpoint).split("://", 1)[-1].rstrip("/")
    return f"{'https' if secure else 'http'}://{host}"


def make_client(endpoint: str, access_key: str, secret_key: str,
                secure: bool = True, *, region: Optional[str] = None) -> Any:
    """A `boto3` S3 client for an S3-compatible endpoint, configured as the
    module docstring says. Raises `ImportError` when `boto3` is not installed —
    the caller says what that means for it."""
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    options: Dict[str, Any] = dict(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        retries={"max_attempts": MAX_ATTEMPTS, "mode": "standard"},
        proxies={},
    )
    try:
        config = Config(request_checksum_calculation="when_required",
                        response_checksum_validation="when_required", **options)
    except TypeError:     # botocore < 1.36: no such options, and no CRC trailers
        config = Config(**options)
    return boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint_url(endpoint, secure),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region or DEFAULT_REGION,
        config=config,
    )


def error_code(exc: BaseException) -> str:
    """The S3 error code of a `ClientError` (`NoSuchKey`, `AccessDenied`, `404`…),
    or "" for anything that is not an answer from the store."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    return str((response.get("Error") or {}).get("Code") or "")


def is_not_found(exc: BaseException) -> bool:
    """Did the store answer «there is no such object» (or bucket)?

    Only a `ClientError` can say that. A network failure is NOT «not found»:
    reading it as one would turn a store that is down into a store that is
    empty, and an upload would then happily «create» what was already there.
    """
    try:
        from botocore.exceptions import ClientError  # type: ignore
    except ImportError:   # pragma: no cover — no boto3, no ClientError either
        return False
    return isinstance(exc, ClientError) and error_code(exc) in NOT_FOUND_CODES


def client_error() -> type:
    """`botocore.exceptions.ClientError`, imported where it is needed — the class
    a store catches to tell an S3 answer from a network failure."""
    from botocore.exceptions import ClientError  # type: ignore
    return ClientError


def read_body(response: Dict[str, Any]) -> bytes:
    """The bytes of a `get_object` answer, and the stream CLOSED whatever happens.

    A body read to the end gives its connection back to the pool by itself; one
    that raised half-way would not, and a pool that leaks a connection per
    failed read is a node that stops talking to its store after a bad
    afternoon. So the close is in a `finally`, as it was with the old client's
    `close()` + `release_conn()`.
    """
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def ensure_bucket(client: Any, bucket: str) -> None:
    """HeadBucket, and CreateBucket when the answer is «no such bucket».

    `BucketAlreadyOwnedByYou` is success, not an error: two processes starting
    together both see the bucket missing and both create it, and the second one
    must not refuse to start for having lost a race it did not need to win.
    Every other answer is raised to the caller, who knows what to say about it.
    """
    ClientError = client_error()
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        if not is_not_found(exc):
            raise
    kwargs: Dict[str, Any] = {"Bucket": bucket}
    region = getattr(getattr(client, "meta", None), "region_name", None)
    if region and region != DEFAULT_REGION:
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    try:
        client.create_bucket(**kwargs)
    except ClientError as exc:
        if error_code(exc) != "BucketAlreadyOwnedByYou":
            raise


def exists(client: Any, bucket: str, key: str) -> bool:
    """HeadObject: is it there? `False` only when the store SAID it is not —
    every other failure is raised, for the reason `is_not_found` gives."""
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:                       # noqa: BLE001 — re-raised
        if is_not_found(exc):
            return False
        raise


def iter_objects(client: Any, bucket: str, prefix: str = "",
                 page_size: int = 1000) -> Iterator[Dict[str, Any]]:
    """Every object under `prefix`, as `{"key", "size"}`, page by page
    (ListObjectsV2 with its continuation token).

    A generator, so a caller that wants a BOUNDED count (`node_health`, which
    stops at `COUNT_CAP`) stops asking after the page it needs — the store is
    never asked to list a bucket the caller will not read.
    """
    token: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"Bucket": bucket, "MaxKeys": page_size}
        if prefix:
            kwargs["Prefix"] = prefix
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents") or []:
            yield {"key": item.get("Key"), "size": int(item.get("Size") or 0)}
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return
