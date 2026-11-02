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
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import access, clock, exactjson, ids
from ..errors import FieldError, Problem, refuse
from ..store import scoping
from ..store.tables._base import AllOf, ByKind, Creates, Via, creates_of
from .conventions import ExactRoute, Gone, Model, check
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
    # What a kind's create learned for its read: a new tax book's dependents left out.
    notes: dict[str, Any] = field(default_factory=dict)
    _after: dict[str, Callable[[], None]] = field(default_factory=dict)
    _verify: dict[str, tuple[str, Callable[[], None]]] = field(default_factory=dict)

    def ask(self, code: str, message: str) -> None:
        """Go on only when the person confirmed this question about this record."""
        if (code, self.record_id) not in self.confirmed:
            raise Asked(code, self.record_id, message)

    def verify(self, key: str, fn: Callable[[], None]) -> None:
        """Run `fn` once after every op, however many ops ask for the same `key`: a check that
        spans records (a transaction's splits add up to it), its refusals named by the record
        that asked first."""
        self._verify.setdefault(key, (self.record_id, fn))

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


def may_create(ctx: Ctx, kind: Kind, fields: dict) -> None:
    """Whether the caller may make a record of the kind, as its table declares (docs/schema.md
    §7.9), asked before the kind's own code runs: a parent they can't read answers 404, never
    saying whether it exists; one they read without the permission, 403. A key not sent is left
    to the record's own checks."""
    from sqlalchemy import inspect

    table = inspect(kind.entity).local_table
    _may(ctx, table, creates_of(table), fields)


def _may(ctx: Ctx, table, rule: Creates, fields: dict) -> None:
    if isinstance(rule, AllOf):
        for r in rule.rules:
            _may(ctx, table, r, fields)
        return
    if isinstance(rule, Via | ByKind):
        item_id = fields.get(rule.key)
        if isinstance(rule, Via):
            parent = next(f.column.table for f in table.foreign_keys if f.parent.name == rule.key)
        else:
            name = dict(rule.tables).get(fields.get(rule.kind))
            parent = next((t for t in table.metadata.sorted_tables if t.name == name), None)
        # A key not sent, or not an id of its table, is the record's own checks' to refuse.
        if parent is None or not isinstance(item_id, str):
            return
        if not ids.is_id(item_id, parent.info.get("prefix", "")):
            return
        entity = access.entity_of_table(parent.name)
        held = access.perms(ctx.s, entity, item_id, ctx.caller.id)
        if held is None:
            if rule.missing:
                raise refuse(rule.key, *rule.missing, 404)
            raise Problem(404, "not-found", "Not found")
        if not getattr(held, rule.permission):
            if rule.refused:
                raise refuse(rule.key, *rule.refused, 403)
            try:
                access.need(
                    ctx.s, entity, item_id, ctx.caller.id, rule.permission, parent.name.lower()
                )
            except Problem as e:
                raise refuse(rule.key, e.code, e.detail, 403) from e
        return
    if rule == "admin" and not ctx.caller.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")
    if rule == "never":
        raise Problem(403, "server-only", "Only MoolaKata itself makes these.")


def _apply(ctx: Ctx, op: Op, kind: Kind) -> None:
    if op.op == "create":
        _new_id(ctx, kind, op.id)
        may_create(ctx, kind, op.fields)
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


@dataclass
class _Outcome:
    """What the ops came to so far: refusals with their statuses, stale records, questions."""

    errors: list[FieldError] = field(default_factory=list)
    statuses: set[int] = field(default_factory=set)
    stale: list[dict] = field(default_factory=list)
    asks: list[dict] = field(default_factory=list)

    def attempt(self, s: Session, record_id: str, entity: str, fn: Callable[[], None]) -> None:
        """Run `fn` in a savepoint, so one refusal doesn't spoil the checks of the rest."""
        point = s.begin_nested()
        try:
            fn()
            s.flush()
            point.commit()
        except Asked as a:
            point.rollback()
            self.asks.append({"code": a.code, "id": a.record_id, "message": a.message})
        except Problem as p:
            point.rollback()
            if p.status == 412:
                self.stale.append({"entity": entity, "id": record_id, **exactjson.marked(p.extra)})
                return
            self.statuses.add(p.status)
            if p.errors:
                self.errors += [
                    FieldError(e.field, e.code, e.message, e.id or record_id) for e in p.errors
                ]
            else:
                self.errors.append(FieldError(None, p.code, p.detail, record_id))

    def refuse(self, field_: str, code: str, message: str, record_id: str) -> None:
        self.errors.append(FieldError(field_, code, message, record_id))
        self.statuses.add(422)


def apply(s: Session, c: Caller, request: Request, body: SaveIn) -> tuple[list[Saved], Ctx]:
    """Apply the ops in `s`, raising one Problem for everything refused (S13.8.11.4, .5)."""
    if len(body.ops) > MAX_OPS:
        raise Problem(413, "too-many-ops", f"A save holds at most {MAX_OPS} changes.")
    ctx = Ctx(s, c, request, frozenset((x.code, x.id) for x in body.confirm))
    # Foreign keys are checked at the commit, so the order of the ops can't break a reference.
    s.execute(text("PRAGMA defer_foreign_keys = ON"))
    out = _Outcome()
    seen: set[str] = set()
    for op in sorted(body.ops, key=lambda o: ORDER[o.op]):
        kind = KINDS.get(op.entity)
        if kind is None:
            out.refuse("entity", "entity-unknown", "Not a kind of record a dialog saves.", op.id)
            continue
        if op.id in seen:
            out.refuse("id", "id-repeated", "One change per record.", op.id)
            continue
        seen.add(op.id)
        ctx.record_id = op.id
        out.attempt(s, op.id, op.entity, lambda op=op, kind=kind: _apply(ctx, op, kind))
    # Checks that span records, once every op has gone in; noise after a refusal or a stale.
    if not (out.stale or out.errors):
        for record_id, fn in list(ctx._verify.values()):
            ctx.record_id = record_id
            out.attempt(s, record_id, "", fn)
    errors, statuses, stale, asks = out.errors, out.statuses, out.stale, out.asks
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
            # Deleted, it is in no view: what the caller just did, read as the server.
            e = kind.entity
            row = s.execute(
                scoping.unscoped(
                    select(e.deletedAt, e.version).where(e.id == op.id), "a record just deleted"
                )
            ).first()
            saved.append(
                Saved(
                    entity=op.entity,
                    id=op.id,
                    deleted=Gone(id=op.id, deletedAt=row[0], version=row[1]),
                )
            )
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
        with srv.db.tx(user=c.id) as s:
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
