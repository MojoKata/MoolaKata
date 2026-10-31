"""The one gate for every signed call (requirements S13.7.5.4, S13.7.6; link-protocol.md §3,
connector-protocol.md §3): a linked server's on `/link`, the MoolaKata Connector's on
`/connector`. Each route is a plain function of the `Call` it is given, and the gate runs the
same order for all of them:

1. the call's headers: its protocol, the body hash it names, its key, time, nonce and
   signature, checked before a byte of the body is read;
2. its caller found (the link and its state, the paired connector and which of its keys);
3. its calls counted against that caller, and a call that fails before then against its
   address, so naming someone else's key costs them nothing;
4. its body read, and held to the hash the call named (a receipt's sealed bytes written to a
   file as they come, never whole in memory);
5. the route's work run on the thread pool, never on the event loop (S13);
6. every answer, a refusal or a fault included, signed to the call; only a refusal made before
   a call's signature could be checked goes unsigned.
"""

import hashlib
import inspect
import logging
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import exactjson, ratelimit
from . import keys, signing

log = logging.getLogger("moolakata.links")

STATUS = {
    "protocol-unsupported": 426,
    "limit": 429,
    "busy": 429,
    "not-found": 404,
    "too-large": 413,
    "server-error": 500,
}


@dataclass(frozen=True)
class Kind:
    """One protocol's choices: its headers and labels, the protocol versions it answers, and
    where its nonces and limits are kept."""

    scheme: signing.Scheme
    name: str  # "link protocol", "connector protocol"
    protocol: int
    supported: tuple[int, ...]
    nonces: Callable[[object], signing.Nonces]
    limit: Callable[[object], ratelimit.Window]  # per caller, once its signature checks
    unknown: Callable[[object], ratelimit.Window]  # per address, for calls that don't

    @property
    def digest(self) -> str:
        return self.scheme.lower("body-sha256")


@dataclass
class Call:
    """A call the gate let through: its verified caller, what its route's finder found, and
    its body (or, for a receipt's sealed bytes, the file they were written to)."""

    srv: object
    request: Request
    caller: signing.Caller
    found: object
    body: bytes
    protocol: int
    asked: signing.Asked
    file: Path | None = None
    _json: dict | None = field(default=None, repr=False)

    def json(self) -> dict:
        if self._json is None:
            out = exactjson.loads(self.body or b"{}")
            self._json = out if isinstance(out, dict) else {}
        return self._json

    def header(self, name: str) -> str | None:
        return self.request.headers.get(name)

    @property
    def address(self) -> str | None:
        return self.request.client.host if self.request.client else None


# A finder: who a verified caller is, and the key its calls are counted under, or Refused.
Finder = Callable[[object, signing.Caller], tuple[object, str]]


class Gate:
    def __init__(self, kind: Kind):
        self.kind = kind

    # Answers.

    def asked(self, request: Request) -> signing.Asked | None:
        """The call an answer answers, by the body hash it names: an answer can be signed
        before, or without, its body being read."""
        digest = request.headers.get(self.kind.digest) or None
        return signing.asked_of(request.headers, b"", self.kind.scheme, digest=digest)

    def answer(
        self, srv, data: dict, asked: signing.Asked, status: int = 200, headers=None
    ) -> Response:
        """Signed to the call it answers: its nonce, its caller and its body."""
        body = exactjson.dumps(data, separators=(",", ":")).encode()
        signed = signing.sign_answer(
            keys.signing_key(srv), status, body, asked, scheme=self.kind.scheme
        )
        return Response(
            body,
            status_code=status,
            media_type="application/json",
            headers={**signed, **(headers or {})},
        )

    def signed_headers(self, srv, asked: signing.Asked, digest: str, status: int = 200) -> dict:
        """An answer's signature over bytes streamed after it, by their SHA-256."""
        return signing.sign_answer(
            keys.signing_key(srv), status, b"", asked, digest=digest, scheme=self.kind.scheme
        )

    def refusal(self, request: Request, e: signing.Refused) -> Response:
        """Signed when the call carried a nonce, so the caller can tell a refusal from a
        forgery; unsigned only for one refused before its headers could be read as a call."""
        status = STATUS.get(e.code, 403)
        body = {"code": e.code, "message": e.message}
        if e.code == "protocol-unsupported":
            body["protocols"] = sorted(self.kind.supported)  # those it speaks, for the caller
        headers = {"Retry-After": str(max(1, math.ceil(e.retry_after)))} if e.retry_after else None
        call = self.asked(request)
        if call is None or isinstance(e, Unsigned):
            return JSONResponse(body, status_code=status, headers=headers)
        return self.answer(request.app.state.server, body, call, status, headers)

    # The checks, in order.

    def _protocol(self, request: Request) -> int:
        spoken = request.headers.get(self.kind.scheme.lower("protocol"), str(self.kind.protocol))
        if not spoken.isdigit() or int(spoken) not in self.kind.supported:
            raise signing.Refused(
                "protocol-unsupported",
                f"This server speaks {self.kind.name} "
                f"{', '.join(map(str, self.kind.supported))}; yours sent {spoken}. The older "
                "side needs updating.",
            )
        return int(spoken)

    async def admit(
        self, request: Request, find: Finder | None, files: bool, max_body: int | None
    ) -> Call:
        srv = request.app.state.server
        kind = self.kind
        unknown = kind.unknown(srv)
        address = ratelimit.address_key(request.client.host if request.client else None)
        wait = unknown.wait(address)
        if wait:
            raise Unsigned("limit", "Too many calls from this address: try again later.", wait)
        try:
            protocol = self._protocol(request)
            digest = request.headers.get(kind.digest, "")
            if len(digest) != 64 or digest.strip("0123456789abcdef"):
                raise signing.Refused(
                    "unsigned", f"A call names its body's SHA-256 ({kind.scheme.h('Body-SHA256')})."
                )
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            caller = signing.verify_request(
                request.headers,
                request.method,
                path,
                b"",
                keys.own_public(srv)[1],
                kind.nonces(srv),
                scheme=kind.scheme,
                digest=digest,
            )
            found, counted = find(srv, caller) if find is not None else (None, None)
        except signing.Refused:
            unknown.hit(address)  # never against the key the call names
            raise
        if counted is None:
            unknown.hit(address)  # a stranger's key by design (a join, a pairing)
        else:
            wait = kind.limit(srv).hit(counted)
            if wait:
                raise signing.Refused("limit", "Too many calls: try again in a moment.", wait)
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if max_body is not None and length > max_body:
            raise signing.Refused("too-large", f"This call's body is at most {max_body} bytes.")
        asked = signing.Asked(caller.nonce, signing.fingerprint(caller.public), digest)
        call = Call(srv, request, caller, found, b"", protocol, asked)
        h = hashlib.sha256()
        if files and request.headers.get("content-type", "").startswith("application/octet-stream"):
            call.file = await _to_file(srv, request, h)
        else:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if max_body is not None and size > max_body:
                    raise signing.Refused(
                        "too-large", f"This call's body is at most {max_body} bytes."
                    )
                h.update(chunk)
                chunks.append(chunk)
            call.body = b"".join(chunks)
        if h.hexdigest() != digest:
            if call.file is not None:
                call.file.unlink(missing_ok=True)
            raise signing.Refused("bad-signature", "The body isn't the one the call signed.")
        return call

    def route(self, find: Finder | None = None, files: bool = False, max_body: int | None = None):
        """A route through the gate: `fn(call, **path)` gives a dict to answer, a Response of
        its own, or raises Refused; it runs on the thread pool. `find` gives the caller and the
        key its calls count under (None: a stranger, counted by address); `files` lets a body
        of sealed bytes be written to a file as it comes; `max_body` caps the body below what
        the request limits allow, checked on its headers and as it is read."""

        def wrap(fn):
            params = [p for n, p in inspect.signature(fn).parameters.items() if n != "call"]

            async def run(request: Request, **path):
                try:
                    call = await self.admit(request, find, files, max_body)
                except signing.Refused as e:
                    return self.refusal(request, e)
                try:
                    out = await run_in_threadpool(fn, call, **path)
                except signing.Refused as e:
                    return self.refusal(request, e)
                except Exception:
                    log.exception("a signed call failed: %s", request.url.path)
                    return self.refusal(
                        request,
                        signing.Refused("server-error", "This call failed here; it is logged."),
                    )
                finally:
                    if call.file is not None:
                        call.file.unlink(missing_ok=True)
                if isinstance(out, Response):
                    return out
                return self.answer(call.srv, out, call.asked)

            run.__name__, run.__qualname__, run.__doc__ = fn.__name__, fn.__qualname__, fn.__doc__
            only = inspect.Parameter.KEYWORD_ONLY
            run.__signature__ = inspect.Signature(
                [
                    inspect.Parameter("request", only, annotation=Request),
                    *(p.replace(kind=only) for p in params),
                ]
            )
            run.gate = self  # for the test that every signed route goes through one
            return run

        return wrap


class Unsigned(signing.Refused):
    """A refusal made before a call's signature is checked: never signed (protocol §7)."""


async def _to_file(srv, request: Request, h) -> Path:
    """Sealed bytes as they arrive, hashed, written through a thread to a file in `links-in/`
    (the caller removes it); never whole in memory."""
    folder = srv.config.data_dir / "links-in"
    folder.mkdir(mode=0o700, exist_ok=True)
    tmp = folder / (secrets.token_hex(12) + ".tmp")
    f = await run_in_threadpool(open, tmp, "wb")
    try:
        async for chunk in request.stream():
            h.update(chunk)
            await run_in_threadpool(f.write, chunk)
    except BaseException:
        f.close()
        tmp.unlink(missing_ok=True)
        raise
    await run_in_threadpool(f.close)
    return tmp
