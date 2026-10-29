"""Strategies (requirements S3.5): the user's strategies with their legs and figures, the
groupings and rolls proposed, grouping by hand, and undoing a group. Grouping is a label:
lots, gains and wash sales stay per leg."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from .. import access, activity, clock, ids
from ..errors import Problem, refuse
from ..ledger import types as atypes
from ..options import contract_of
from ..options import strategies as strat
from ..store.entities.accounts import Instrument, Strategy, StrategyLeg
from ..store.repos import ledger as repo
from . import save
from .conventions import ExactRoute, Model, Money, Quantity, Ratio
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["strategies"])


class LegOut(Model):
    instrumentId: str
    symbol: str
    kind: str  # call, put or stock
    quantity: Quantity  # contracts or shares; short below zero; 0 once closed
    cost: Money  # for shares, their value on the opening day
    value: Money | None
    strike: Quantity | None
    expiry: dt.date | None
    realized: Money
    addedOn: dt.date | None
    closedOn: dt.date | None


class StrategyOut(Model):
    id: str
    accountId: str
    accountName: str
    name: str
    shape: str
    underlying: str
    openedOn: dt.date
    closedOn: dt.date | None
    legs: list[LegOut]
    credit: Money  # net option premium received; a debit below zero
    unrealized: Money | None
    realized: Money
    pl: Money | None
    maxProfit: Money | None  # none: unlimited, or not known for a calendar
    maxLoss: Money | None
    breakevens: list[Money]
    expiryKnown: bool
    capitalAtRiskNow: Money | None  # none: unlimited
    capitalAtRiskAtOpen: Money | None
    returnPct: Ratio | None  # on capital at risk at open
    cashSecured: bool
    marginRequirement: Money | None
    canWrite: bool
    version: int


class ProposalLeg(Model):
    instrumentId: str
    symbol: str
    quantity: Quantity | None  # shares, for a stock leg


class ProposalOut(Model):
    key: str
    kind: str  # group, covered-call, roll
    accountId: str
    accountName: str
    underlying: str
    openedOn: dt.date
    shape: str
    legs: list[ProposalLeg]
    strategyId: str | None


class StrategiesView(Model):
    strategies: list[StrategyOut]
    proposals: list[ProposalOut]


def _out(a, v: strat.View, level: str) -> StrategyOut:
    st = v.strategy
    return StrategyOut(
        id=st.id,
        accountId=a.id,
        accountName=a.name,
        name=v.name,
        shape=v.shape,
        underlying=v.underlying,
        openedOn=st.openedOn,
        closedOn=v.closedOn,
        legs=[
            LegOut(
                instrumentId=x.instrumentId,
                symbol=x.symbol,
                kind=x.kind,
                quantity=x.quantity,
                cost=x.cost,
                value=x.value,
                strike=x.strike,
                expiry=x.expiry,
                realized=x.realized,
                addedOn=x.addedOn,
                closedOn=x.closedOn,
            )
            for x in v.legs
        ],
        credit=v.credit,
        unrealized=v.unrealized,
        realized=v.realized,
        pl=v.pl,
        maxProfit=v.figures.maxProfit,
        maxLoss=v.figures.maxLoss,
        breakevens=v.figures.breakevens,
        expiryKnown=v.figures.expiryKnown,
        capitalAtRiskNow=v.riskNow,
        capitalAtRiskAtOpen=v.riskAtOpen,
        returnPct=(v.pl / v.riskAtOpen * 100).quantize(Decimal("0.01"))
        if v.pl is not None and v.riskAtOpen
        else None,
        cashSecured=st.cashSecured,
        marginRequirement=st.marginRequirement,
        canWrite=level in ("owner", "write"),
        version=st.version,
    )


def account_view(s, a, level: str, book: strat.Book | None = None):
    book = book or strat.Book(s, repo.load(s, a))
    views = [_out(a, strat.view(book, st), level) for st in strat.of_account(s, a.id)]
    props = []
    if level in ("owner", "write"):
        for p in strat.proposals(s, a, book):
            under = s.get(Instrument, p.underlyingId)
            props.append(
                ProposalOut(
                    key=p.key,
                    kind=p.kind,
                    accountId=a.id,
                    accountName=a.name,
                    underlying=under.symbol if under else "?",
                    openedOn=p.openedOn,
                    shape=p.shape,
                    legs=[
                        ProposalLeg(instrumentId=i, symbol=sym, quantity=q)
                        for (i, q), sym in zip(p.legs, p.symbols, strict=True)
                    ],
                    strategyId=p.strategyId,
                )
            )
    return views, props


@router.get("/positions/strategies", response_model=StrategiesView)
def list_strategies(request: Request, c: Caller = Depends(caller)):
    """Open strategies first, then those closed; the proposals for the accounts the caller
    may change."""
    out, props = [], []
    with server(request).db.read() as s:
        for a, level in access.visible_accounts(s, c.id):
            if not atypes.investing(a.type):
                continue
            v, p = account_view(s, a, level)
            out += v
            props += p
    out.sort(key=lambda x: (x.closedOn is not None, x.underlying, x.openedOn))
    return StrategiesView(strategies=out, proposals=props)


class LegIn(Model):
    instrumentId: str
    quantity: Quantity | None = None  # shares, for a stock leg


class NewStrategy(Model):
    accountId: str
    legs: list[LegIn] = Field(min_length=1)
    name: str | None = None
    dismiss: bool = False  # a proposal turned down: kept so it isn't made again


def _check_legs(s, account, legs: list[LegIn]) -> tuple[str, dt.date]:
    """The legs are held in the account, all on one underlying; their underlying and the day
    the earliest opened."""
    book = strat.Book(s, repo.load(s, account))
    under = None
    first = None
    for x in legs:
        qty, _ = book.open.get(x.instrumentId, (Decimal(0), Decimal(0)))
        if not qty:
            raise refuse("legs", "leg-not-held", "Legs held in this account.")
        oc = contract_of(s, x.instrumentId)
        u = oc.underlyingId if oc is not None else x.instrumentId
        if under is not None and u != under:
            raise refuse("legs", "legs-differ", "Legs on one underlying.")
        under = u
        d = book.first.get(x.instrumentId)
        if d is not None and (first is None or d < first):
            first = d
    if all(contract_of(s, x.instrumentId) is None for x in legs):
        raise refuse("legs", "no-option", "At least one option leg.")
    return under, first or clock.today()


@router.post("/strategies", response_model=StrategiesView, status_code=201)
def group(body: NewStrategy, request: Request, c: Caller = Depends(caller)):
    """Group legs by hand or as proposed, or turn a proposal down."""
    with server(request).db.tx() as s:
        a, level = access.account(s, c.id, body.accountId, "write")
        if len({x.instrumentId for x in body.legs}) != len(body.legs):
            raise refuse("legs", "legs-twice", "Each leg once.")
        if not body.dismiss:
            taken = {
                r.instrumentId
                for st in strat.of_account(s, a.id)
                for r in strat.legs_of(s, st)
                if contract_of(s, r.instrumentId) is not None
            }
            if any(x.instrumentId in taken for x in body.legs):
                raise refuse("legs", "leg-grouped", "A leg is already in a strategy.")
        under, opened = _check_legs(s, a, body.legs)
        st = Strategy(
            id=ids.new_id("Strat"),
            accountId=a.id,
            underlyingId=under,
            openedOn=opened,
            name=(body.name or "").strip()[:80] or None,
            dismissed=body.dismiss,
        )
        s.add(st)
        s.flush()
        for x in body.legs:
            s.add(
                StrategyLeg(
                    strategyId=st.id,
                    instrumentId=x.instrumentId,
                    quantity=x.quantity,
                    addedOn=opened,
                    createdAt=clock.now(),
                )
            )
        s.flush()
        if not body.dismiss:
            activity.record(
                s,
                "strategy.grouped",
                actor=c.id,
                subject_kind="account",
                subject_id=a.id,
                owner=a.ownerId,
            )
        views, props = account_view(s, a, level)
        return StrategiesView(strategies=views, proposals=props)


class Rolled(Model):
    roll: list[LegIn] = Field(default_factory=list)  # legs rolled into it
    declineRoll: list[str] = Field(default_factory=list)  # a roll's new legs turned down


class StrategyRecord(Model):
    """A strategy as a draft saves it (S3.5): its name, cash-secured tick and margin; grouped
    from its legs, and undone by deleting it, its legs standing on their own again."""

    name: str | None = None
    cashSecured: bool = False
    marginRequirement: Money | None = None


def _own(s, c: Caller, strategy_id: str):
    st = s.get(Strategy, strategy_id)
    if st is None or st.deleted or st.dismissed:
        raise Problem(404, "not-found", "Not found")
    a, level = access.account(s, c.id, st.accountId, "write")
    return st, a, level


@router.post("/strategies/{strategy_id}/roll", response_model=StrategyOut)
def roll(strategy_id: str, body: Rolled, request: Request, c: Caller = Depends(caller)):
    """A roll proposed for it taken in, or turned down so it isn't offered again (S3.5.3)."""
    with server(request).db.tx() as s:
        st, a, level = _own(s, c, strategy_id)
        have = {r.instrumentId for r in strat.legs_of(s, st)}
        today = clock.today()
        for x in body.roll:
            if x.instrumentId in have:
                continue
            u, opened = _check_legs(s, a, [x])
            if u != st.underlyingId:
                raise refuse("roll", "legs-differ", "A roll stays on the same underlying.")
            s.add(
                StrategyLeg(
                    strategyId=st.id,
                    instrumentId=x.instrumentId,
                    addedOn=opened or today,
                    createdAt=clock.now(),
                )
            )
        for iid in body.declineRoll:
            # Kept as a proposal turned down, so the same roll isn't offered again.
            declined = Strategy(
                id=ids.new_id("Strat"),
                accountId=a.id,
                underlyingId=st.underlyingId,
                openedOn=today,
                dismissed=True,
            )
            s.add(declined)
            s.flush()
            s.add(
                StrategyLeg(
                    strategyId=declined.id, instrumentId=iid, addedOn=today, createdAt=clock.now()
                )
            )
        st.updatedAt = clock.now()
        s.flush()
        book = strat.Book(s, repo.load(s, a))
        return _out(a, strat.view(book, st), level)


def _strategy_create(ctx, record_id: str, body: StrategyRecord) -> None:
    raise refuse(None, "strategy-grouped", "A strategy is grouped from the legs it holds.")


def _strategy_update(ctx, st: Strategy, body: StrategyRecord) -> None:
    if body.marginRequirement is not None and body.marginRequirement < 0:
        raise refuse("marginRequirement", "margin-invalid", "An amount, or none.")
    st.name = (body.name or "").strip()[:80] or None
    st.cashSecured = body.cashSecured
    st.marginRequirement = body.marginRequirement
    st.updatedAt = clock.now()


def _strategy_read(ctx, record_id: str) -> StrategyOut:
    st, a, level = _own(ctx.s, ctx.caller, record_id)
    book = strat.Book(ctx.s, repo.load(ctx.s, a))
    return _out(a, strat.view(book, st), level)


save.register(
    save.Kind(
        prefix="Strat",
        entity=Strategy,
        fields=StrategyRecord,
        create=_strategy_create,
        editable=lambda ctx, record_id: _own(ctx.s, ctx.caller, record_id)[0],
        current=lambda ctx, st: {
            "name": st.name,
            "cashSecured": bool(st.cashSecured),
            "marginRequirement": st.marginRequirement,
        },
        update=_strategy_update,
        # Undone: its legs stand on their own again (S3.5.1).
        delete=lambda ctx, st: st.mark_deleted(ctx.caller.id),
        read=_strategy_read,
    )
)
