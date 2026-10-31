"""Portfolios (requirements S5.1): named sets of accounts, owned by a user and shared like an
account. A viewer sees only the accounts in it that are shared with them, and every figure
counts only those. *All my accounts* is everyone's implicit first portfolio."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, figures, valuation
from ..errors import FieldError, Problem, refuse
from ..ledger import performance as perf
from ..ledger import types as atypes
from ..options import strategies as strat
from ..store import scoping
from ..store.entities.accounts import Account
from ..store.entities.sharing import Portfolio, PortfolioAccount
from ..store.entities.users import User
from ..store.repos import ledger as repo
from . import save
from .conventions import (
    ExactRoute,
    IdOf,
    Model,
    Money,
    Quantity,
    Ratio,
)
from .deps import Caller, caller, server
from .sharing import counted_for

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["portfolios"])
ALL = "all"
BENCHMARKS = ("VT", "SPY", "60-40")


class PortfolioRow(Model):
    id: str
    name: str
    implicit: bool
    ownerId: str
    ownerName: str
    ownerAvatar: str | None
    level: str
    benchmark: str
    accountIds: list[str]
    value: Money
    sharedWith: int
    notes: str | None
    version: int


def member_ids(s, portfolio_id: str) -> list[str]:
    return list(
        s.scalars(
            select(PortfolioAccount.accountId).where(
                PortfolioAccount.portfolioId == portfolio_id, PortfolioAccount.deleted == false()
            )
        )
    )


def all_mine(s, user_id: str) -> list[Account]:
    """My own accounts, and those shared with me that I count in my totals (S10.7)."""
    counted = counted_for(s, user_id)
    return [a for a, _ in access.accounts(s, user_id) if a.ownerId == user_id or a.id in counted]


def seen_accounts(s, user_id: str, p: Portfolio | None) -> list[Account]:
    """The portfolio's accounts this user can see (S5.1.1)."""
    if p is None:
        return all_mine(s, user_id)
    ids = member_ids(s, p.id)
    return [a for a, _ in access.accounts(s, user_id, Account.id.in_(ids))]


def with_deleted(s, user_id: str, p: Portfolio | None, accounts: list[Account]) -> list[Account]:
    """For a portfolio's past figures: also the viewer's own accounts in it that were deleted,
    which count up to their deletion (R3.10)."""
    if p is None:
        ids = list(
            s.scalars(
                select(Account.id).where(Account.ownerId == user_id, Account.deletedAt.is_not(None))
            )
        )
    else:
        ids = member_ids(s, p.id)
    have = {a.id for a in accounts}
    gone = [
        a
        for a in (s.get(Account, i) for i in ids if i not in have)
        if a is not None and a.deleted and a.ownerId == user_id
    ]
    return accounts + gone


def value_of(s, accounts: list[Account], day: dt.date | None = None) -> Decimal:
    total = Decimal(0)
    for a in accounts:
        total += valuation.account_value(s, repo.load(s, a), atypes.investing(a.type), day)
    return total


def shape(s, user: User, p: Portfolio | None, level: str) -> PortfolioRow:
    seen = seen_accounts(s, user.id, p)
    if p is None:
        return PortfolioRow(
            id=ALL,
            name="All my accounts",
            implicit=True,
            ownerId=user.id,
            ownerName=user.displayName,
            ownerAvatar=user.avatar,
            level="owner",
            benchmark="VT",
            accountIds=[a.id for a in seen],
            value=value_of(s, seen),
            sharedWith=0,
            notes=None,
            version=1,
        )
    owner = s.get(User, p.ownerId)
    shared = len(access.holders_of(s, Portfolio, p.id)) - 1 if level == "owner" else 0
    return PortfolioRow(
        id=p.id,
        name=p.name,
        implicit=False,
        ownerId=p.ownerId,
        ownerName=owner.displayName,
        ownerAvatar=owner.avatar,
        level=level,
        benchmark=p.benchmark,
        accountIds=[a.id for a in seen],
        value=value_of(s, seen),
        sharedWith=shared,
        notes=p.notes,
        version=p.version,
    )


def _check(s, user_id: str, body) -> list[FieldError]:
    errors = []
    if body.name is not None and (not body.name.strip() or len(body.name) > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    if body.benchmark is not None and body.benchmark not in BENCHMARKS:
        errors.append(FieldError("benchmark", "benchmark-invalid", "VT, SPY or a 60/40 mix."))
    if body.accountIds is not None:
        mine = {a.id for a, _ in access.accounts(s, user_id)}
        if any(a not in mine for a in body.accountIds):
            errors.append(
                FieldError(
                    "accountIds",
                    "account-unknown",
                    "Choose accounts you own or that are shared with you.",
                )
            )
    return errors


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)


def _set_members(s, p: Portfolio, wanted: list[str], by: str) -> None:
    current = {
        m.accountId: m
        for m in s.scalars(select(PortfolioAccount).where(PortfolioAccount.portfolioId == p.id))
    }
    now = clock.now()
    for aid in dict.fromkeys(wanted):
        m = current.get(aid)
        if m is None:
            s.add(PortfolioAccount(portfolioId=p.id, accountId=aid, createdAt=now))
        elif m.deleted:
            m.restore()
    for aid, m in current.items():
        if aid not in wanted and not m.deleted:
            m.mark_deleted(by, now)


@router.get("/portfolios", response_model=list[PortfolioRow])
def list_portfolios(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        return [shape(s, c.user, None, "owner")] + [
            shape(s, c.user, p, perms.level())
            for p, perms in access.listing(s, Portfolio, c.id, order_by=Portfolio.name)
        ]


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioRow)
def get_portfolio(portfolio_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        if portfolio_id == ALL:
            return shape(s, c.user, None, "owner")
        p, lvl = access.portfolio(s, c.id, portfolio_id)
        return shape(s, c.user, p, lvl)


class PortfolioRecord(Model):
    """A portfolio as a draft saves it (S5.1): its accounts are its owner's choice."""

    name: str
    accountIds: list[IdOf("Acct")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    benchmark: str = "VT"
    notes: str | None = None


def _portfolio_create(ctx, record_id: str, body: PortfolioRecord) -> None:
    s, c = ctx.s, ctx.caller
    _raise(_check(s, c.id, body))
    p = Portfolio(id=record_id, ownerId=c.id, name=body.name.strip(), benchmark=body.benchmark,
                  notes=body.notes)  # fmt: skip
    s.add(p)
    s.flush()
    _set_members(s, p, body.accountIds, c.id)
    activity.record(s, "portfolio.created", actor=c.id, subject_kind="portfolio",
                    subject_id=p.id, owner=c.id)  # fmt: skip


def _portfolio_editable(ctx, record_id: str) -> Portfolio:
    return access.portfolio(ctx.s, ctx.caller.id, record_id, "write")[0]


def _portfolio_current(ctx, p: Portfolio) -> dict:
    return {"name": p.name, "accountIds": member_ids(ctx.s, p.id), "benchmark": p.benchmark,
            "notes": p.notes}  # fmt: skip


def _portfolio_update(ctx, p: Portfolio, body: PortfolioRecord) -> None:
    s, c = ctx.s, ctx.caller
    _, lvl = access.portfolio(s, c.id, p.id, "write")
    _raise(_check(s, p.ownerId, body))
    fields = []
    for f in ("name", "benchmark", "notes"):
        value = getattr(body, f)
        if value != getattr(p, f):
            setattr(p, f, value.strip() if isinstance(value, str) and f == "name" else value)
            fields.append(f)
    if set(body.accountIds) != set(member_ids(s, p.id)):
        if lvl != "owner":
            raise refuse("accountIds", "owner-only", "Only the owner chooses the accounts.", 403)
        _set_members(s, p, body.accountIds, c.id)
        p.updatedAt = clock.now()
        fields.append("accounts")
    if fields:
        activity.record(s, "portfolio.updated", actor=c.id, subject_kind="portfolio",
                        subject_id=p.id, owner=p.ownerId, detail={"fields": fields})  # fmt: skip


def _portfolio_delete(ctx, p: Portfolio) -> None:
    s, c = ctx.s, ctx.caller
    access.portfolio(s, c.id, p.id, "deletable")
    p.mark_deleted(c.id)
    activity.record(s, "portfolio.deleted", actor=c.id, subject_kind="portfolio",
                    subject_id=p.id, owner=p.ownerId)  # fmt: skip


def _portfolio_read(ctx, record_id: str) -> PortfolioRow:
    p, lvl = access.portfolio(ctx.s, ctx.caller.id, record_id)
    return shape(ctx.s, ctx.caller.user, p, lvl)


save.register(
    save.Kind(
        prefix="Portf",
        entity=Portfolio,
        fields=PortfolioRecord,
        create=_portfolio_create,
        editable=_portfolio_editable,
        current=_portfolio_current,
        update=_portfolio_update,
        delete=_portfolio_delete,
        read=_portfolio_read,
    )
)


# ---------- performance and holdings (S5.2) ----------


class SeriesPoint(Model):
    date: dt.date
    value: Money
    contributions: Money
    benchmark: Money | None


class PortfolioSeries(Model):
    points: list[SeriesPoint]
    benchmark: str
    twr: str | None
    irr: str | None
    contributed: Money
    growth: Money
    start: Money
    end: Money


class ReturnRow(Model):
    id: str
    name: str
    periods: dict[str, str | None]


class HoldingTotal(Model):
    instrumentId: str
    symbol: str
    name: str | None
    instrumentClass: str
    quantity: Quantity
    price: Quantity | None
    priceAsOf: dt.date | None
    priceSource: str | None
    stale: bool
    value: Money | None
    costBasis: Money | None
    gain: Money | None
    weight: Ratio | None
    accounts: list[str]


class PortfolioHoldings(Model):
    holdings: list[HoldingTotal]
    cash: Money
    total: Money
    optionsValue: Money | None  # its options' market value
    capitalAtRisk: Money | None  # beside it (S3.5.6)
    capitalAtRiskUnlimited: bool = False  # an open strategy's risk is unlimited


def _target(s, c: Caller, portfolio_id: str) -> tuple[Portfolio | None, list[Account], str]:
    if portfolio_id == ALL:
        return None, all_mine(s, c.id), "VT"
    p, _ = access.portfolio(s, c.id, portfolio_id)
    return p, seen_accounts(s, c.id, p), p.benchmark


@router.get("/portfolios/{portfolio_id}/series", response_model=PortfolioSeries)
def portfolio_series(
    portfolio_id: str,
    request: Request,
    c: Caller = Depends(caller),
    metric: str = Query("value", pattern="^value$"),
    range: str = Query("1Y", pattern="^(1M|3M|YTD|1Y|5Y|All)$"),
):
    """Value over time with contributions apart from growth, against the benchmark, and the
    period's time- and money-weighted returns (S5.2.1, S5.2.3)."""
    today = figures.today()
    with server(request).db.read(user=c.id) as s:
        p, accounts, bench = _target(s, c, portfolio_id)
        with scoping.as_server(
            s, "a portfolio's figures, over what its viewer reads and their own deleted accounts"
        ) as srv:
            accounts = [srv.get(Account, a.id) for a in accounts]
            accounts = with_deleted(srv, c.id, p, accounts)
            first = figures.first_day(range, today, figures.earliest(srv, accounts))
            comb = figures.combine(srv, accounts, first, today, figures.step_for(first, today))
            values = comb.values
            contrib = figures.contributions(values, comb.flow)
            index = figures.benchmark_index(srv, bench, first, today)
            bench_values = dict(perf.benchmark(values, comb.flow, index))
            start = values[0][1] if values else Decimal(0)
            end = values[-1][1] if values else Decimal(0)
            put_in = (contrib[-1][1] - start) if contrib else Decimal(0)
            rate = perf.irr(values[0][0], start, comb.flow, values[-1][0], end) if values else None
            return PortfolioSeries(
                points=[
                    SeriesPoint(date=d, value=v, contributions=cv, benchmark=bench_values.get(d))
                    for (d, v), (_, cv) in zip(values, contrib, strict=True)
                ],
                benchmark=bench,
                twr=figures.fmt_rate(perf.twr(values, comb.flow)),
                irr=figures.fmt_rate(rate),
                contributed=put_in,
                growth=end - start - put_in,
                start=start,
                end=end,
            )


@router.get("/portfolios/{portfolio_id}/returns", response_model=list[ReturnRow])
def portfolio_returns(portfolio_id: str, request: Request, c: Caller = Depends(caller)):
    """Time-weighted returns per period, per account and for the portfolio (S5.2.3)."""
    today = figures.today()
    with server(request).db.read(user=c.id) as s:
        p, accounts, _ = _target(s, c, portfolio_id)
        with scoping.as_server(
            s, "a portfolio's returns, over what its viewer reads and their own deleted accounts"
        ) as srv:
            accounts = [srv.get(Account, a.id) for a in accounts]
            first = today - dt.timedelta(days=figures.RANGE_DAYS["5Y"])
            step = 7
            rows = []
            # The portfolio's own returns keep an account deleted since, up to its deletion, as its
            # value series does (R3.10); the rows are the accounts it holds now.
            total = figures.combine(srv, with_deleted(srv, c.id, p, accounts), first, today, step)
            for a in accounts:
                led = repo.load(srv, a)
                series = total.byAccount[a.id]
                rows.append(
                    ReturnRow(
                        id=a.id,
                        name=a.name,
                        periods={
                            k: figures.fmt_rate(v)
                            for k, v in figures.period_returns(
                                series, perf.flows(led.transactions), today
                            ).items()
                        },
                    )
                )
            rows.append(
                ReturnRow(
                    id=portfolio_id,
                    name=p.name if p else "All my accounts",
                    periods={
                        k: figures.fmt_rate(v)
                        for k, v in figures.period_returns(total.values, total.flow, today).items()
                    },
                )
            )
            return rows


@router.get("/portfolios/{portfolio_id}/holdings", response_model=PortfolioHoldings)
def portfolio_holdings(portfolio_id: str, request: Request, c: Caller = Depends(caller)):
    """What the portfolio's visible accounts hold, added up by instrument."""
    from ..store.entities.accounts import Instrument

    with server(request).db.read(user=c.id) as s:
        _, accounts, _ = _target(s, c, portfolio_id)
        by: dict[str, dict] = {}
        cash = Decimal(0)
        opts = Decimal(0)
        risk: Decimal | None = Decimal(0)
        any_open = False
        for a in accounts:
            led = repo.load(s, a)
            cash += led.balance()
            if not atypes.investing(a.type):
                continue
            v, r, held = strat.risk_of_account(s, led)
            opts, any_open = opts + v, any_open or held
            risk = None if risk is None or r is None else risk + r
            for pos in valuation.positions(s, led):
                h = by.setdefault(
                    pos.instrumentId,
                    {
                        "qty": Decimal(0),
                        "value": Decimal(0),
                        "basis": Decimal(0),
                        "known": True,
                        "priced": True,
                        "price": pos.price,
                        "accounts": [],
                    },
                )
                h["qty"] += pos.quantity
                if pos.value is None:
                    h["priced"] = False
                else:
                    h["value"] += pos.value
                if pos.costBasis is None:
                    h["known"] = False
                else:
                    h["basis"] += pos.costBasis
                h["accounts"].append(a.name)
        insts = {i.id: i for i in s.scalars(select(Instrument).where(Instrument.id.in_(by)))}
        total = cash + sum((h["value"] for h in by.values()), Decimal(0))
        out = []
        for iid, h in sorted(by.items(), key=lambda kv: -kv[1]["value"]):
            inst = insts[iid]
            value = h["value"] if h["priced"] else None
            basis = h["basis"] if h["known"] else None
            price = h["price"]
            out.append(
                HoldingTotal(
                    instrumentId=iid,
                    symbol=inst.symbol,
                    name=inst.name,
                    instrumentClass=inst.instrumentClass,
                    quantity=h["qty"],
                    price=price.price if price else None,
                    priceAsOf=price.asOf if price else None,
                    priceSource=price.source if price else None,
                    stale=bool(price and price.stale),
                    value=value,
                    costBasis=basis,
                    gain=value - basis if value is not None and basis is not None else None,
                    weight=(value / total * 100).quantize(Decimal("0.1"))
                    if value is not None and total
                    else None,
                    accounts=sorted(set(h["accounts"])),
                )
            )
        return PortfolioHoldings(
            holdings=out,
            cash=cash,
            total=total,
            optionsValue=opts if any_open else None,
            capitalAtRisk=risk if any_open else None,
            capitalAtRiskUnlimited=any_open and risk is None,
        )
