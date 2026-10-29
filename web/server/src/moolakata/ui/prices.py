"""Prices (requirements S4, S16.6): the header's refresh status, Refresh prices, Settings ›
Prices for admins, typed prices and an instrument's stored closes."""

import datetime as dt
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, exactjson, ids, settings
from ..errors import FieldError, Problem, refuse
from ..prices import SOURCES
from ..prices import refresh as pricing
from ..store.entities.accounts import Instrument, Transaction
from ..store.entities.prices import Price, PriceSource
from ..store.entities.prices import TypedPrice as Typed
from ..store.entities.users import User
from ..store.repos import secrets as secret_repo
from . import save
from .conventions import ExactRoute, IdOf, Model, Quantity
from .deps import Caller, admin, caller, recent_auth, server
from .imports import JobOut, accepted

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["prices"])


class PriceStatus(Model):
    lastRefresh: dt.datetime | None
    stale: bool
    sources: int
    running: bool


class SourceKind(Model):
    name: str
    label: str
    classes: list[str]
    needsKey: bool
    keyUrl: str | None
    terms: str
    termsChecked: dt.date | None
    attribution: str | None
    fetches: bool


class SecretSet(Model):
    setAt: dt.datetime
    setBy: str | None


class SourceRow(SourceKind):
    id: str
    enabled: bool
    preference: dict[str, int]
    key: SecretSet | None
    lastRunAt: dt.datetime | None
    lastOkAt: dt.datetime | None
    lastError: str | None
    version: int


class SourcesView(Model):
    available: list[SourceKind]
    sources: list[SourceRow]
    refreshTime: str
    refreshZone: str


class NewSource(Model):
    name: str


class Close(Model):
    date: dt.date
    close: Quantity
    source: str
    # A price the reader typed (TypedPrice), a record of the save: its id and version.
    id: str | None = None
    version: int = 0


def _kind(cls) -> SourceKind:
    return SourceKind(
        name=cls.name,
        label=cls.label,
        classes=sorted(cls.classes),
        needsKey=cls.needs_key,
        keyUrl=cls.key_url,
        terms=cls.terms,
        termsChecked=cls.terms_checked,
        attribution=cls.attribution,
        fetches=cls.fetches,
    )


def _shipped(dev: bool) -> list:
    return [c for c in SOURCES.values() if dev or not c.dev_only]


def _row(s, src: PriceSource) -> SourceRow:
    cls = SOURCES[src.name]
    info = secret_repo.info(s, "PriceSource", src.id, "apiKey")
    key = None
    if info:
        by = s.get(User, info.setById) if info.setById else None
        key = SecretSet(setAt=info.setAt, setBy=by.displayName if by else None)
    return SourceRow(
        **_kind(cls).model_dump(),
        id=src.id,
        enabled=src.enabled,
        preference=json.loads(src.preference or "{}"),
        key=key,
        lastRunAt=src.lastRunAt,
        lastOkAt=src.lastOkAt,
        lastError=src.lastError,
        version=src.version,
    )


def _view(s, dev: bool) -> SourcesView:
    from .. import settings

    rows = s.scalars(
        select(PriceSource).where(PriceSource.deleted == false()).order_by(PriceSource.createdAt)
    ).all()
    return SourcesView(
        available=[_kind(c) for c in _shipped(dev)],
        sources=[_row(s, r) for r in rows if r.name in SOURCES],
        refreshTime=settings.get(s, "priceRefreshTime"),
        refreshZone=settings.get(s, "priceRefreshZone"),
    )


def apply_egress(srv) -> None:
    """Only the hosts of enabled sources, the SMTP server, the bitcoin explorer or node and
    linked servers may be reached (S13.5). The SMTP host and a node are ones an admin named, so
    they may be on this machine."""
    from ..bitcoin import sync as bitcoin
    from ..links.peers import hosts as link_hosts

    with srv.db.read() as s:
        smtp = [h] if (h := settings.get(s, "smtpHost")) else []
        btc, btc_named = bitcoin.hosts(s)
        peers = link_hosts(s)
        srv.guard.allow(
            pricing.hosts(s, srv.config.dev) + smtp + btc + peers,
            # A linked server's address came from the other server: never exempt, except
            # between two dev servers on one machine.
            allowed_by_name=smtp + btc_named + (peers if srv.config.dev else []),
        )


@router.get("/prices/status", response_model=PriceStatus)
def price_status(request: Request, c: Caller = Depends(caller)):
    srv = server(request)
    with srv.db.read() as s:
        st = pricing.status(s, srv.config.dev, c.id)
    running = srv.tasks.status().get("prices", {}).get("running", False)
    return PriceStatus(**st, running=running)


@router.post("/prices/refresh", response_model=JobOut, status_code=202)
def refresh_prices(request: Request, c: Caller = Depends(caller)):
    """Refresh prices: the daily task, now (S4.4), followed as a job (S13.8.7)."""
    srv = server(request)
    job = srv.jobs.create("prices", c.id)
    if not srv.tasks.run_now("prices", srv.jobs.follow(job)):
        raise Problem(503, "not-available", "Prices can't be refreshed right now.")
    return accepted(job)


@router.get("/price-sources", response_model=SourcesView)
def list_sources(request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.read() as s:
        return _view(s, srv.config.dev)


def _add(s, srv, c: Caller, name: str, source_id: str) -> PriceSource:
    cls = SOURCES.get(name)
    if cls is None or (cls.dev_only and not srv.config.dev):
        raise refuse("name", "source-unknown", "Choose a source MoolaKata ships.")
    if s.scalars(
        select(PriceSource).where(PriceSource.name == name, PriceSource.deleted == false())
    ).first():
        raise refuse("name", "source-added", f"{cls.label} is already added.", 409)
    taken = {}
    for r in s.scalars(select(PriceSource).where(PriceSource.deleted == false())):
        for k, v in json.loads(r.preference or "{}").items():
            taken[k] = max(taken.get(k, 0), v)
    pref = {k: taken.get(k, 0) + 1 for k in sorted(cls.classes)}
    src = PriceSource(
        id=source_id,
        name=name,
        enabled=not cls.needs_key,
        preference=exactjson.dumps(pref),
        createdById=c.id,
    )
    s.add(src)
    activity.record(s, "prices.source-added", actor=c.id, for_admins=True, detail={"source": name})
    return src


@router.post("/price-sources", response_model=SourcesView, status_code=201)
def add_source(body: NewSource, request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.tx() as s:
        _add(s, srv, c, body.name, ids.new_id("Src"))
        s.flush()
        view = _view(s, srv.config.dev)
    apply_egress(srv)
    return JSONResponse(view.model_dump(mode="json"), status_code=201)


class SourceRecord(Model):
    """A price source as a draft saves it (S4.2): added by name; on or off, its place for
    each class it serves, and its key, a secret written and never read back (S14.4)."""

    name: str
    enabled: bool = False
    preference: dict[str, int] = Field(default_factory=dict)
    apiKey: str | None = Field(None, description="the source's key, written, never read back")


def _source_admin(ctx) -> Caller:
    if not ctx.caller.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")
    return ctx.caller


def _source_create(ctx, record_id: str, body: SourceRecord) -> None:
    c = _source_admin(ctx)
    srv = server(ctx.request)
    src = _add(ctx.s, srv, c, body.name, record_id)
    ctx.s.flush()
    if body.apiKey is not None:
        _source_update(ctx, src, body)
    ctx.after("egress", lambda: apply_egress(srv))


def _source_editable(ctx, record_id: str) -> PriceSource:
    _source_admin(ctx)
    src = ctx.s.get(PriceSource, record_id)
    if src is None or src.deleted or src.name not in SOURCES:
        raise Problem(404, "not-found", "Not found")
    return src


def _source_current(ctx, src: PriceSource) -> dict:
    return {"name": src.name, "enabled": src.enabled, "apiKey": None,
            "preference": json.loads(src.preference or "{}")}  # fmt: skip


def _source_update(ctx, src: PriceSource, body: SourceRecord) -> None:
    s, c = ctx.s, _source_admin(ctx)
    srv = server(ctx.request)
    cls = SOURCES[src.name]
    if body.name != src.name:
        raise refuse("name", "source-fixed", "A source keeps its name; add another.")
    fields = []
    if body.apiKey is not None:
        recent_auth(c)  # a secret set: the password again (S13.7.2)
        if not cls.needs_key:
            raise refuse("apiKey", "no-key", f"{cls.label} needs no key.")
        key = body.apiKey.strip()
        if not 8 <= len(key) <= 200 or any(ch.isspace() for ch in key):
            raise refuse("apiKey", "key-invalid", "Paste the key as the source gives it.")
        secret_repo.put(s, srv.keys.secrets, "PriceSource", src.id, "apiKey", key, c.id)
        fields.append("apiKey")
    if body.enabled != src.enabled:
        if (
            body.enabled
            and cls.needs_key
            and not secret_repo.info(s, "PriceSource", src.id, "apiKey")
        ):
            raise refuse(
                "enabled", "key-needed", f"{cls.label} needs its key before it can be enabled."
            )
        src.enabled = body.enabled
        fields.append("enabled")
    if body.preference != json.loads(src.preference or "{}"):
        errors = [
            FieldError(f"preference.{k}", "class-not-served", f"{cls.label} doesn't serve {k}.")
            for k in body.preference
            if k not in cls.classes
        ]
        if errors:
            raise Problem(422, errors[0].code, errors[0].message, errors)
        src.preference = exactjson.dumps({k: int(v) for k, v in body.preference.items()})
        fields.append("preference")
    if fields:
        src.updatedAt = clock.now()
        activity.record(s, "prices.source-changed", actor=c.id, for_admins=True,
                        detail={"source": src.name, "fields": fields})  # fmt: skip
        ctx.after("egress", lambda: apply_egress(srv))


def _source_delete(ctx, src: PriceSource) -> None:
    c = _source_admin(ctx)
    srv = server(ctx.request)
    secret_repo.remove(ctx.s, "PriceSource", src.id, "apiKey")
    src.mark_deleted(c.id)
    activity.record(ctx.s, "prices.source-removed", actor=c.id, for_admins=True,
                    detail={"source": src.name})  # fmt: skip
    ctx.after("egress", lambda: apply_egress(srv))


save.register(
    save.Kind(
        prefix="Src",
        entity=PriceSource,
        fields=SourceRecord,
        create=_source_create,
        editable=_source_editable,
        current=_source_current,
        update=_source_update,
        delete=_source_delete,
        read=lambda ctx, record_id: _row(ctx.s, ctx.s.get(PriceSource, record_id)),
    )
)


def _held_writable(s, user_id: str, instrument_id: str) -> bool:
    """A typed price is for an instrument the user holds in an account they can change."""
    account_ids = set(
        s.scalars(
            select(Transaction.accountId).where(
                Transaction.instrumentId == instrument_id, Transaction.deleted == false()
            )
        )
    )
    return any(
        access.RANK[lvl] >= access.RANK["write"]
        for a, lvl in access.visible_accounts(s, user_id)
        if a.id in account_ids
    )


class TypedPriceRecord(Model):
    """A price from a statement, or typed, with its date (S4.3), as its dialog's draft saves
    it: its typer's alone, valuing their own accounts and never another user's (S4.10), one a
    day."""

    instrumentId: IdOf("Instr")  # type: ignore[valid-type]
    date: dt.date
    close: Quantity


def _typed_check(ctx, body: TypedPriceRecord) -> None:
    if body.date > clock.today():
        raise refuse("date", "date-in-future", "A price can't be dated in the future.")
    if body.close < 0:
        raise refuse("close", "price-negative", "A price can't be negative.")
    inst = ctx.s.get(Instrument, body.instrumentId)
    if inst is None or inst.deleted or not _held_writable(ctx.s, ctx.caller.id, inst.id):
        raise refuse("instrumentId", "not-found", "One of your holdings.", 404)


def _typed_told(ctx, instrument_id: str) -> None:
    srv = server(ctx.request)
    ctx.after(
        f"prices:{instrument_id}",
        lambda: srv.events.publish("prices", {"instrumentId": instrument_id}),
    )


def _typed_create(ctx, record_id: str, body: TypedPriceRecord) -> None:
    _typed_check(ctx, body)
    have = ctx.s.scalars(
        select(Typed).where(
            Typed.instrumentId == body.instrumentId,
            Typed.userId == ctx.caller.id,
            Typed.date == body.date,
            Typed.deleted == false(),
        )
    ).first()
    if have is not None:
        raise refuse("date", "price-typed", "You typed a price for that day: change it.", 409)
    ctx.s.add(
        Typed(
            id=record_id,
            instrumentId=body.instrumentId,
            userId=ctx.caller.id,
            date=body.date,
            close=body.close,
        )
    )
    _typed_told(ctx, body.instrumentId)


def _typed_editable(ctx, record_id: str) -> Typed:
    t = ctx.s.get(Typed, record_id)
    if t is None or t.deleted or t.userId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found")
    return t


def _typed_update(ctx, t: Typed, body: TypedPriceRecord) -> None:
    if (body.instrumentId, body.date) != (t.instrumentId, t.date):
        raise refuse("date", "price-fixed", "A typed price keeps its day: type another.")
    _typed_check(ctx, body)
    t.close = body.close
    _typed_told(ctx, t.instrumentId)


def _typed_delete(ctx, t: Typed) -> None:
    t.mark_deleted(ctx.caller.id)
    _typed_told(ctx, t.instrumentId)


def _typed_read(ctx, record_id: str) -> Close:
    t = ctx.s.get(Typed, record_id)
    return Close(date=t.date, close=t.close, source="manual", id=t.id, version=t.version)


save.register(
    save.Kind(
        prefix="TyPrc",
        entity=Typed,
        fields=TypedPriceRecord,
        create=_typed_create,
        editable=_typed_editable,
        current=lambda ctx, t: {"instrumentId": t.instrumentId, "date": t.date, "close": t.close},
        update=_typed_update,
        delete=_typed_delete,
        read=_typed_read,
    )
)


@router.get("/instruments/{instrument_id}/prices", response_model=list[Close])
def closes(
    instrument_id: str,
    request: Request,
    c: Caller = Depends(caller),
    start: dt.date | None = Query(None, alias="from"),
    end: dt.date | None = Query(None, alias="to"),
):
    with server(request).db.read() as s:
        inst = s.get(Instrument, instrument_id)
        if inst is None or inst.deleted:
            raise Problem(404, "not-found", "Not found")
        q = select(Price).where(Price.instrumentId == inst.id, Price.deleted == false())
        t = select(Typed).where(
            Typed.instrumentId == inst.id, Typed.userId == c.id, Typed.deleted == false()
        )
        if start:
            q, t = q.where(Price.date >= start), t.where(Typed.date >= start)
        if end:
            q, t = q.where(Price.date <= end), t.where(Typed.date <= end)
        # The closes every account shares, and the prices this user typed, which win their day.
        by_day = {p.date: Close(date=p.date, close=p.close, source=p.source) for p in s.scalars(q)}
        for p in s.scalars(t):
            by_day[p.date] = Close(
                date=p.date, close=p.close, source="manual", id=p.id, version=p.version
            )
        return [by_day[d] for d in sorted(by_day)]
