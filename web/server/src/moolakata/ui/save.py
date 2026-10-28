"""The save (requirements S13.8.11): a browser dialog's draft (S12.15) in one request, applied
in one database transaction or not at all.

Each kind of record a draft may hold registers a `Kind`: how its record is made, read for a
change, changed and deleted, each inside the save's open transaction, with the same checks as
the record's own route. The save puts the ops in order (creates, then updates, then deletes),
runs each in a savepoint so one refusal doesn't spoil the checks of the rest, and gathers every
refusal, stale version and question before it rolls back."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock, exactjson, ids
from ..errors import FieldError, Problem, refuse
from .conventions import ExactRoute, Gone, Model, check, gone
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["save"])

MAX_OPS = 1000
# How far an id made in the browser may be from the server's clock (schema.md §2).
CLOCK_SLACK = dt.timedelta(days=1)


class Asked(Exception):
    """A change that asks first (S13.8.11.5), raised by `Ctx.ask` when it isn't confirmed."""

    def __init__(self, code: str, record_id: str, message: str) -> None:
        super().__init__(message)
        self.code, self.record_id, self.message = code, record_id, message


@dataclass
class Ctx:
    """What a kind's functions are given: the open transaction, who saves, the questions
    already confirmed, and what to run once the save has committed."""

    s: Session
    caller: Caller
    request: Request
    confirmed: frozenset[tuple[str, str]]
    record_id: str = ""
    _after: dict[str, Callable[[], None]] = field(default_factory=dict)

    def ask(self, code: str, message: str) -> None:
        """Go on only when the person confirmed this question about this record."""
        if (code, self.record_id) not in self.confirmed:
            raise Asked(code, self.record_id, message)

    def after(self, key: str, fn: Callable[[], None]) -> None:
        """Run `fn` once after the commit, however many ops ask for the same `key`: a live
        stream event, an alert, the work that follows a change (S13.8.11.6)."""
        self._after.setdefault(key, fn)


@dataclass(frozen=True)
class Kind:
    """One kind of record a draft may save, by its table's prefix (schema.md §3).

    `fields` is the request model its create takes whole; an update's fields are put onto
    `current(ctx, record)`, the record in that model's form, before the whole is checked.
    `editable(ctx, id)` reads the record for a change or a delete, refusing what the caller
    can't change as the record's own route does. `read(ctx, id)` is the record as the API
    answers it, for the save's answer and a stale version's `current`."""

    prefix: str
    entity: type
    fields: type[BaseModel]
    create: Callable[[Ctx, str, Any], None]
    editable: Callable[[Ctx, str], Any]
    current: Callable[[Ctx, Any], dict]
    update: Callable[[Ctx, Any, Any], None]
    delete: Callable[[Ctx, Any], None]
    read: Callable[[Ctx, str], Any]


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> None:
    if not ids.PREFIX.match(kind.prefix):
        raise ValueError(f"bad prefix {kind.prefix!r}")
    KINDS[kind.prefix] = kind


class SetChange(Model):
    """A set of pairs held by a record (a gift's people, a transaction's tags): what to add and
    what to take away (S13.8.11.1)."""

    add: list[Any] = Field(default_factory=list)
    remove: list[Any] = Field(default_factory=list)


class Op(Model):
    op: Literal["create", "update", "delete"]
    entity: str
    id: str
    version: int | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class Confirmed(Model):
    code: str
    id: str


class SaveIn(Model):
    ops: list[Op]
    confirm: list[Confirmed] = Field(default_factory=list)


class Saved(Model):
    """A record the save touched: its new version and the record as read, or what went."""

    entity: str
    id: str
    version: int | None = None
    record: dict | None = None
    deleted: Gone | None = None


class SaveOut(Model):
    saved: list[Saved]


ORDER = {"create": 0, "update": 1, "delete": 2}


def _as_dict(value: Any) -> dict:
    """A record as the API answers it, its decimals written as exact numbers."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return exactjson.marked(value)


def _fields(kind: Kind, values: dict, record_id: str) -> Any:
    """The request model from values, each refusal at its field and named by its record."""
    try:
        return kind.fields.model_validate(values)
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            code = "invalid-" + str(err.get("type", "value")).replace("_", "-")
            errors.append(FieldError(loc or None, code, str(err.get("msg", "invalid")), record_id))
        raise Problem(422, "invalid-request", "Some fields were not accepted.", errors) from e


def _merged(current: dict, changes: dict) -> dict:
    """An update's changed fields put onto the record as it is; a set as add and remove."""
    out = dict(current)
    for name, value in changes.items():
        if isinstance(value, dict) and set(value) <= {"add", "remove"} and value:
            change = SetChange.model_validate(value)
            have = list(out.get(name) or [])
            have = [x for x in have if x not in change.remove]
            have += [x for x in change.add if x not in have]
            out[name] = have
        else:
            out[name] = value
    return out


def _new_id(ctx: Ctx, kind: Kind, record_id: str) -> None:
    """A create's id, made in the browser (schema.md §2): its form, its table, its time, and
    not already taken (S13.8.11.2)."""
    if not ids.is_id(record_id, kind.prefix):
        raise refuse("id", "id-invalid", f"Not an id of {kind.prefix}.")
    made = ids.time_of(record_id)
    if abs(made - clock.now()) > CLOCK_SLACK:
        raise refuse("id", "id-clock", "This computer's clock is off by more than a day.")
    if ctx.s.get(kind.entity, record_id) is not None:
        raise refuse("id", "id-taken", "This id is already taken.", status=409)


def _apply(ctx: Ctx, op: Op, kind: Kind) -> None:
    if op.op == "create":
        _new_id(ctx, kind, op.id)
        kind.create(ctx, op.id, _fields(kind, op.fields, op.id))
        return
    if not ids.is_id(op.id, kind.prefix):
        raise refuse("id", "id-invalid", f"Not an id of {kind.prefix}.")
    if op.version is None:
        raise Problem(428, "version-required", "Send the record's version.")
    record = kind.editable(ctx, op.id)
    check(record, op.version, lambda: kind.read(ctx, op.id))
    if op.op == "update":
        values = _merged(kind.current(ctx, record), op.fields)
        kind.update(ctx, record, _fields(kind, values, op.id))
    else:
        kind.delete(ctx, record)


def apply(s: Session, c: Caller, request: Request, body: SaveIn) -> tuple[list[Saved], Ctx]:
    """Apply the ops in `s`, raising one Problem for everything refused (S13.8.11.4, .5)."""
    if len(body.ops) > MAX_OPS:
        raise Problem(413, "too-many-ops", f"A save holds at most {MAX_OPS} changes.")
    ctx = Ctx(s, c, request, frozenset((x.code, x.id) for x in body.confirm))
    # Foreign keys are checked at the commit, so the order of the ops can't break a reference.
    s.execute(text("PRAGMA defer_foreign_keys = ON"))
    errors: list[FieldError] = []
    statuses: set[int] = set()
    stale: list[dict] = []
    asks: list[dict] = []
    seen: set[str] = set()
    for op in sorted(body.ops, key=lambda o: ORDER[o.op]):
        kind = KINDS.get(op.entity)
        if kind is None:
            message = "Not a kind of record a dialog saves."
            errors.append(FieldError("entity", "entity-unknown", message, op.id))
            statuses.add(422)
            continue
        if op.id in seen:
            errors.append(FieldError("id", "id-repeated", "One change per record.", op.id))
            statuses.add(422)
            continue
        seen.add(op.id)
        ctx.record_id = op.id
        point = s.begin_nested()
        try:
            _apply(ctx, op, kind)
            s.flush()
            point.commit()
        except Asked as a:
            point.rollback()
            asks.append({"code": a.code, "id": a.record_id, "message": a.message})
        except Problem as p:
            point.rollback()
            if p.status == 412:
                stale.append({"entity": op.entity, "id": op.id, **exactjson.marked(p.extra)})
                continue
            statuses.add(p.status)
            if p.errors:
                errors += [FieldError(e.field, e.code, e.message, e.id or op.id) for e in p.errors]
            else:
                errors.append(FieldError(None, p.code, p.detail, op.id))
    if stale:
        raise Problem(
            412,
            "stale-version",
            "Someone changed this since you loaded it.",
            extra={"current": stale},
        )
    if errors:
        status = statuses.pop() if len(statuses) == 1 else 422
        raise Problem(status, "save-refused", "Nothing was saved.", errors)
    if asks:
        raise Problem(409, "confirm-needed", "Saving this asks first.", extra={"asks": asks})
    saved = []
    for op in body.ops:
        kind = KINDS[op.entity]
        if op.op == "delete":
            record = s.get(kind.entity, op.id)
            saved.append(Saved(entity=op.entity, id=op.id, deleted=gone(record)))
        else:
            out = _as_dict(kind.read(ctx, op.id))
            saved.append(Saved(entity=op.entity, id=op.id, version=out.get("version"), record=out))
    return saved, ctx


@router.post("/save", response_model=SaveOut)
def save(body: SaveIn, request: Request, c: Caller = Depends(caller)):
    """A dialog's draft, saved all or nothing (S13.8.11)."""
    srv = server(request)
    key = request.headers.get("idempotency-key")
    again = srv.idempotency.lookup(c.id, key)
    if again:
        status, payload, headers = again
        return JSONResponse(payload, status_code=status, headers=headers)
    try:
        with srv.db.tx() as s:
            saved, ctx = apply(s, c, request, body)
    except IntegrityError as e:
        raise Problem(
            422, "reference-missing", "A change refers to a record that doesn't exist."
        ) from e
    for fn in ctx._after.values():
        fn()
    payload = SaveOut(saved=saved).model_dump(mode="json")
    srv.idempotency.remember(c.id, key, 200, payload, {})
    return JSONResponse(payload, status_code=200)
