"""The API conventions of requirements S13.8, as pieces the routes share: money, quantities
and ratios as exact JSON numbers, offset paging, versions with If-Match, and Idempotency-Key."""

import datetime as dt
import functools
import inspect
import json
import threading
import time
import typing
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    WithJsonSchema,
)

from .. import exactjson, ids, money
from ..errors import Problem


class Sent(Decimal):
    """A number as a request sent it, so its places are checked; a Decimal the server worked
    out (an average, say) is rounded when it is written instead."""


def _money_in(v: Any) -> Decimal:
    if isinstance(v, float):
        raise ValueError("amounts are exact: send the number as written, never through a float")
    if type(v) is Decimal:
        return v
    return money.parse(v, places=2)


def _quantity_in(v: Any) -> Decimal:
    if isinstance(v, float):
        raise ValueError("quantities are exact: send the number as written, never through a float")
    if type(v) is Decimal:
        return v
    return money.parse(v, places=money.QUANTITY_PLACES)


def _money_out(d: Decimal) -> str:
    return exactjson.mark(money.money_str(d) or "0")


def _quantity_out(d: Decimal) -> str:
    return exactjson.mark(exactjson.text(Decimal(money.quantity_str(d) or "0")))


# Exact numbers in JSON (S13.8.2): read from a number (or a decimal string, as a form field
# gives it), written as a number literal with its own digits, never a float. In Python they
# are Decimals; `when_used="json"` leaves `model_dump()` giving Decimals.
Money = Annotated[
    Decimal,
    BeforeValidator(_money_in),
    PlainSerializer(_money_out, return_type=str, when_used="json"),
    WithJsonSchema({"type": "number", "format": "money", "examples": [1234.5]}),
]
Quantity = Annotated[
    Decimal,
    BeforeValidator(_quantity_in),
    PlainSerializer(_quantity_out, return_type=str, when_used="json"),
    WithJsonSchema({"type": "number", "format": "decimal", "examples": [12.5]}),
]


def _ratio_in(v: Any) -> Decimal:
    if isinstance(v, float):  # worked out by the server, so by its shortest digits
        return Decimal(repr(v))
    return money.parse(v)


def _ratio_out(d: Decimal) -> str:
    return exactjson.mark(exactjson.text(d.normalize() if d == d.to_integral_value() else d))


def _rate_in(places: int):
    def check(v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("rates are exact: send the number as written, never through a float")
        if type(v) is Decimal:
            return v
        return money.parse(v, places=places)

    return check


# A loan's yearly rate in percent, as a note states it: three places (6.875), and four for an
# ARM's reset, which an index and a margin can carry (S1.9.1).
Rate = Annotated[
    Decimal,
    BeforeValidator(_rate_in(3)),
    PlainSerializer(_ratio_out, return_type=str, when_used="json"),
    WithJsonSchema({"type": "number", "format": "decimal", "examples": [6.875]}),
]
ResetRate = Annotated[
    Decimal,
    BeforeValidator(_rate_in(4)),
    PlainSerializer(_ratio_out, return_type=str, when_used="json"),
    WithJsonSchema({"type": "number", "format": "decimal", "examples": [7.3125]}),
]

# A share or rate the server works out for display (a percentage, a factor, years): an exact
# number like the rest, never a binary float.
Ratio = Annotated[
    Decimal,
    BeforeValidator(_ratio_in),
    PlainSerializer(_ratio_out, return_type=str, when_used="json"),
    WithJsonSchema({"type": "number", "format": "decimal", "examples": [12.5]}),
]
# Free-form data a request carries (a projection's inputs, the assumptions, settings), for code
# that works in floats: its numbers arrive as floats, as plain JSON would give them.
Loose = Annotated[dict, BeforeValidator(exactjson.plain)]


class ExactRequest(Request):
    """A request whose JSON body keeps its numbers exact: `1234.50` arrives as a Decimal."""

    async def json(self) -> Any:
        if not hasattr(self, "_json"):
            body = await self.body()
            self._json = json.loads(body, parse_float=Sent) if body else None
        return self._json


def _paged(fn):
    """A list route as every list answers (S13.8.5): `?offset=` and `?limit=`, and a Page. The
    function itself still returns the whole list, for code that calls it directly."""
    sig = inspect.signature(fn)
    extra = inspect.Parameter(
        "paging", inspect.Parameter.KEYWORD_ONLY, default=Depends(Paging), annotation=Paging
    )

    @functools.wraps(fn)
    def paged(*args, paging: Paging, **kw):
        return paging.page(fn(*args, **kw))

    paged.__signature__ = sig.replace(parameters=[*sig.parameters.values(), extra])  # type: ignore[attr-defined]
    return paged


class ExactRoute(APIRoute):
    """Every API route (S13.8): exact numbers in the request body and the response (S13.8.2),
    and every route declared to answer a list paged by offset and limit (S13.8.5)."""

    def __init__(self, path: str, endpoint, **kw):
        model = kw.get("response_model")
        if typing.get_origin(model) is list and set(kw.get("methods") or ["GET"]) == {"GET"}:
            (item,) = typing.get_args(model)
            kw["response_model"] = Page[item]
            endpoint = _paged(endpoint)
        super().__init__(path, endpoint, **kw)

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def exact(request: Request) -> Response:
            response = await handler(ExactRequest(request.scope, request.receive))
            kind = response.headers.get("content-type", "")
            if "json" in kind and hasattr(response, "body") and response.body:
                body = exactjson.unmark_bytes(bytes(response.body))
                if len(body) != len(response.body):
                    response.body = body
                    response.headers["content-length"] = str(len(body))
            return response

        return exact


def IdOf(prefix: str) -> Any:
    """An id of one table (schema.md §2): its prefix and its one spelling, refused at its field
    otherwise. The OpenAPI document carries the prefix (`x-prefix`), from which the browser's
    fields know what a reference refers to (S17.3.9.2)."""

    def check(v: str) -> str:
        if not ids.is_id(v, prefix):
            raise ValueError(f"not an id of {prefix}")
        return v

    pattern = f"^{prefix}_[0-7][{ids.ALPHABET}]{{25}}$"
    schema = {"type": "string", "pattern": pattern, "x-prefix": prefix}
    return Annotated[str, AfterValidator(check), WithJsonSchema(schema)]


class Model(BaseModel):
    """Every request and response body: camelCase as in the database, no extra fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)


class Access(Model):
    """What the reader may do with a record, and whether it is theirs (docs/schema.md §7), as
    its access view says. It travels only from the server: no request body has it."""

    mine: bool
    writable: bool
    deletable: bool
    shareable: bool
    configurable: bool

    @classmethod
    def of(cls, p) -> Access:
        """From an `access.Perms`."""
        return cls(
            mine=p.mine,
            writable=p.writable,
            deletable=p.deletable,
            shareable=p.shareable,
            configurable=p.configurable,
        )


class Page[T](BaseModel):
    """A list (S13.8.5): this page's rows, how many the caller can see in all, and where the
    page starts."""

    items: list[T]
    total: int
    offset: int
    limit: int


DEFAULT_LIMIT = 500
MAX_LIMIT = 1000


class Paging:
    """?offset= and ?limit= on every list (S13.8.5)."""

    def __init__(
        self,
        offset: int = Query(0, ge=0),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    ):
        self.offset = offset
        self.limit = limit

    def page(self, rows: list) -> dict:
        """A page of rows already in hand, in their order."""
        return self.wrap(list(rows[self.offset : self.offset + self.limit]), len(rows))

    def wrap(self, items: list, total: int) -> dict:
        return {"items": items, "total": total, "offset": self.offset, "limit": self.limit}

    def query(self, s, q) -> tuple[list, int]:
        """A page of a SELECT, in its order, with how many rows it has in all."""
        from sqlalchemy import func, select

        total = s.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        rows = s.scalars(q.offset(self.offset).limit(self.limit)).all()
        return list(rows), total


def everything() -> Paging:
    """A whole list, for code that calls a list route itself (MCP, a linked server)."""
    return Paging(offset=0, limit=MAX_LIMIT)


def if_match(request: Request) -> int:
    """The version a PATCH, PUT or DELETE was made against (S13.8.6): required, refused with 428
    when missing. A PUT that creates what doesn't exist yet sends 0."""
    value = request.headers.get("if-match", "").strip().strip('"').removeprefix("W/").strip('"')
    if not value.isdigit():
        raise Problem(
            428 if not value else 400, "version-required", "Send the record's version in If-Match."
        )
    return int(value)


def check(record: Any, version: int, current: Any) -> None:
    """The version a change was made against must be the record's own (S13.8.6); `current` (or
    a function giving it) is what a stale request is answered with. A PUT that creates sends 0,
    which matches only when the record doesn't exist yet."""
    have = 0 if record is None else record.version
    if have != version:
        raise stale(current() if callable(current) else current, have)


def version_of(s, entity, *where) -> int:
    """The version of something made of many records replaced together (the settings, a
    year's tax tables, a wallet's keys, an item's shares): the sum of their versions, deleted
    ones included, so it goes up with every change to any of them (S13.8.6)."""
    from sqlalchemy import func, select

    return int(s.scalar(select(func.coalesce(func.sum(entity.version), 0)).where(*where)) or 0)


def stale(current: Any, version: int | None = None) -> Problem:
    """412 with the record as it is now, so the UI can show what changed, and its version, to
    make the change again against."""
    body = current.model_dump(mode="json") if isinstance(current, BaseModel) else current
    if version is None and isinstance(body, dict):
        version = body.get("version")
    extra = {"current": body} if version is None else {"current": body, "version": version}
    return Problem(412, "stale-version", "Someone changed this since you loaded it.", extra=extra)


class Gone(BaseModel):
    """What a DELETE took away (S13.8.1): its id (for a pair, its two keys joined by a slash),
    when, and the version it had."""

    id: str
    deletedAt: dt.datetime | None = None
    version: int | None = None


class Deleted[P](BaseModel):
    """Every DELETE's answer (S13.8.1): what went, and what it belonged to as it now stands,
    or null for a record that belonged to nothing."""

    deleted: Gone
    parent: P | None = None


def gone(record: Any, id_: str | None = None) -> Gone:
    return Gone(
        id=id_ or record.id,
        deletedAt=getattr(record, "deletedAt", None),
        version=getattr(record, "version", None),
    )


class Idempotency:
    """A POST that creates may carry Idempotency-Key: a repeat within 24 hours gets the first
    answer (S13.8.8). Keys are per user."""

    TTL = 24 * 3600

    def __init__(self, clock=time.monotonic) -> None:
        self._seen: dict[tuple[str, str], tuple[float, int, Any, dict]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def lookup(self, user_id: str, key: str | None):
        if not key:
            return None
        with self._lock:
            self._prune()
            hit = self._seen.get((user_id, key))
        return hit[1:] if hit else None

    def remember(
        self, user_id: str, key: str | None, status: int, body: Any, headers: dict
    ) -> None:
        if not key:
            return
        with self._lock:
            self._seen[(user_id, key)] = (self._clock(), status, body, headers)

    def _prune(self) -> None:
        now = self._clock()
        for k in [k for k, v in self._seen.items() if now - v[0] > self.TTL]:
            del self._seen[k]
