"""Accounts (requirements S1, S12.2.2): the list, an account's page, its holdings, its
balance chart and its reconciliation."""

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import false, func, select

from .. import access, activity, clock, exactjson, ids, valuation
from ..errors import FieldError, Problem, refuse
from ..ledger import expected, holdingcheck, reconcile
from ..ledger import types as atypes
from ..ledger.lots import long_term
from ..store.entities.accounts import (
    Account,
    Anchor,
    HoldingCheck,
    Import,
    Instrument,
    Reconciliation,
    Transaction,
)
from ..store.entities.users import User
from ..store.repos import ledger as repo
from ..store.tables.accounts import ACCOUNT_TYPES, LOT_METHODS
from .conventions import Deleted, ExactRoute, Model, Money, Quantity, check, gone, if_match, stale
from .deps import Caller, caller, server
from .sharing import counted_for

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["accounts"])
KEPT_BY = ("manual", "file", "statement", "bitcoin")
RANGES = {"1M": 31, "3M": 92, "1Y": 366, "5Y": 1827}


class AccountRow(Model):
    id: str
    name: str
    type: str
    typeLabel: str
    group: str
    institution: str | None
    mask: str | None
    active: bool
    ownerId: str
    ownerName: str
    level: Literal["owner", "write", "read"]
    sharedWith: int
    ownerAvatar: str | None
    counted: bool
    balance: Money
    change: Money | None
    lastUpdated: dt.datetime | None
    needsAnchor: bool
    mismatch: bool
    countInNetWorth: bool
    investing: bool
    reconcilable: bool
    version: int


class AccountDetail(AccountRow):
    notes: str | None
    keptBy: list[str]
    lotMethod: str
    openingBalance: Money | None
    openingDate: dt.date | None
    openingWorkedOut: Money
    openingStandIn: bool
    tax: str | None
    statementInterval: str | None  # set; none set follows the type (S1.11.7)
    statementIntervalDefault: str  # the type's
    statementIntervalProposal: str | None  # learned from what arrives, not yet accepted
    withdrawalsAMonth: int | None  # a savings account's limit, the bank's (S1.2)
    optionsValue: Money | None  # an investing account's options' market value
    capitalAtRisk: Money | None  # beside it (S3.5.6)
    capitalAtRiskUnlimited: bool = False
    # Sync using MoolaKata Connector (S18.6.2): the owner's Connection and which of its
    # institution accounts this is; shown to the owner only.
    connectionId: str | None
    syncAccount: str | None


class NewAccount(Model):
    name: str
    type: str
    institution: str | None = None
    mask: str | None = None
    notes: str | None = None
    keptBy: list[str] = Field(default_factory=lambda: ["manual"])
    lotMethod: str = "fifo"
    openingBalance: Money | None = None
    openingDate: dt.date | None = None
    # A donor-advised fund counts in no one's net worth unless said (S1.1).
    countInNetWorth: bool | None = None


class AccountChange(Model):
    name: str | None = None
    institution: str | None = None
    mask: str | None = None
    notes: str | None = None
    keptBy: list[str] | None = None
    lotMethod: str | None = None
    openingBalance: Money | None = None
    openingDate: dt.date | None = None
    countInNetWorth: bool | None = None
    active: bool | None = None
    statementInterval: str | None = None  # null: back to the type's default
    dismissIntervalProposal: bool = False
    withdrawalsAMonth: int | None = None  # a savings account's limit, the bank's (S1.2)
    # Sync using MoolaKata Connector (S18.6.2), the owner's alone: a Connection of theirs and
    # the institution account; null turns it off.
    connectionId: str | None = None
    syncAccount: str | None = None


class Point(Model):
    date: dt.date
    value: Money


class Series(Model):
    points: list[Point]
    asOf: dt.date


class LotRow(Model):
    lotId: str | None
    acquiredOn: dt.date
    quantity: Quantity
    basis: Money | None
    basisMissing: bool
    standIn: bool
    longTerm: bool


class HoldingRow(Model):
    instrumentId: str
    symbol: str
    name: str | None
    instrumentClass: str
    quantity: Quantity
    costBasis: Money | None
    price: Quantity | None
    priceAsOf: dt.date | None
    priceSource: str | None
    value: Money | None
    gain: Money | None
    lots: list[LotRow]


class Holdings(Model):
    cash: Money
    total: Money
    holdings: list[HoldingRow]
    problems: list[dict]


class Suspects(Model):
    duplicates: list[list[str]]
    changed: list[str]
    gaps: list[list[dt.date]]
    firstParting: str | None


class CheckRow(Model):
    date: dt.date
    reported: Money
    computed: Money
    difference: Money
    source: str
    ok: bool
    windowFrom: dt.date | None
    suspects: Suspects | None


class PeriodRow(Model):
    start: dt.date
    end: dt.date
    importIds: list[str]


class ReconciliationRow(Model):
    id: str
    statementDate: dt.date
    statementBalance: Money
    cleared: Money
    difference: Money
    finishedAt: dt.datetime | None
    version: int


class ValueCheckRow(Model):
    date: dt.date
    reported: Money  # a statement's ending value
    computed: Money  # what the account was worth that day
    difference: Money
    ok: bool


class HoldingCheckRow(Model):
    label: str
    instrumentId: str | None
    symbol: str | None
    statement: Quantity | None  # its quantity, or the cash
    held: Quantity | None  # MoolaKata's that day
    difference: Quantity | None
    statementBasis: Money | None
    heldBasis: Money | None
    cash: bool
    ok: bool


class ReconcileView(Model):
    periods: list[PeriodRow]
    gaps: list[list[dt.date]]
    overlaps: list[list[dt.date]]
    checks: list[CheckRow]
    valueChecks: list[ValueCheckRow]  # brokerage statements' ending values (S1.3.3.8.1)
    holdingChecksAsOf: dt.date | None
    holdingChecks: list[HoldingCheckRow]  # the latest statement's positions (S1.3.3.8.2)
    needsAnchor: bool
    openingStandIn: bool
    reconciliations: list[ReconciliationRow]


class NewAnchor(Model):
    date: dt.date
    balance: Money
    note: str | None = None


class NewAdjustment(Model):
    date: dt.date
    amount: Money
    note: str


class NewReconciliation(Model):
    statementDate: dt.date
    statementBalance: Money


class ReconciliationChange(Model):
    finish: bool


# ---------- shaping ----------


def _check(body: NewAccount | AccountChange) -> list[FieldError]:
    errors = []
    sent = body.model_fields_set
    named = isinstance(body, NewAccount) or "name" in sent
    if named and (not (body.name or "").strip() or len(body.name or "") > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    if isinstance(body, NewAccount) and body.type not in ACCOUNT_TYPES:
        errors.append(FieldError("type", "type-invalid", "Choose an account type."))
    if body.mask and not (len(body.mask) == 4 and body.mask.isdigit()):
        errors.append(FieldError("mask", "mask-invalid", "The last four digits, such as 4821."))
    if body.lotMethod is not None and body.lotMethod not in LOT_METHODS:
        errors.append(
            FieldError(
                "lotMethod",
                "lot-method-invalid",
                "FIFO, LIFO, HIFO, specific identification or average cost.",
            )
        )
    if body.keptBy is not None and (not body.keptBy or any(k not in KEPT_BY for k in body.keptBy)):
        errors.append(
            FieldError(
                "keptBy", "kept-by-invalid", "Manual, file import, statement import or bitcoin."
            )
        )
    every = getattr(body, "statementInterval", None)
    if every is not None and every not in expected.INTERVALS:
        errors.append(
            FieldError(
                "statementInterval",
                "statement-interval-invalid",
                "Monthly, quarterly, yearly or none.",
            )
        )
    if body.notes and len(body.notes) > 20000:
        errors.append(FieldError("notes", "notes-too-long", "Notes are up to 20,000 characters."))
    if (body.openingBalance is None) != (body.openingDate is None) and (
        isinstance(body, NewAccount) or {"openingBalance", "openingDate"} & sent
    ):
        errors.append(
            FieldError(
                "openingDate",
                "opening-incomplete",
                "An opening balance needs its date, and a date its balance.",
            )
        )
    return errors


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)


@dataclass
class Context:
    """What every row of one caller's list shares."""

    userId: str
    owners: dict[str, User]
    updated: dict
    today: dt.date
    counted: set[str]


def context(s, user_id: str, account_ids: list[str]) -> Context:
    return Context(
        user_id,
        {u.id: u for u in s.scalars(select(User))},
        repo.latest_activity(s, account_ids),
        clock.today(),
        counted_for(s, user_id),
    )


def row(
    s, a: Account, level: str, ctx: Context, detail: bool = False
) -> AccountRow | AccountDetail:
    today = ctx.today
    owner = ctx.owners.get(a.ownerId)
    ledger = repo.load(s, a)
    investing = atypes.investing(a.type)
    value = valuation.account_value(s, ledger, investing)
    month_ago = valuation.account_value(s, ledger, investing, today - dt.timedelta(days=30))
    cover = reconcile.coverage(ledger.imports)
    start = ledger.opening()
    checks = reconcile.checks(start, ledger.transactions, ledger.anchors, cover)
    base = dict(
        id=a.id,
        name=a.name,
        type=a.type,
        typeLabel=atypes.LABELS[a.type],
        group=atypes.GROUPS[a.type],
        institution=a.institution,
        mask=a.mask,
        active=a.active,
        ownerId=a.ownerId,
        ownerName=owner.displayName if owner else "",
        ownerAvatar=owner.avatar if owner else None,
        level=level,
        sharedWith=len(access.holders(s, "account", a.id, a.ownerId)) - 1
        if level == "owner"
        else 0,
        counted=a.countInNetWorth if level == "owner" else a.id in ctx.counted,
        balance=value,
        change=value - month_ago if ledger.transactions else None,
        lastUpdated=ctx.updated.get(a.id),
        countInNetWorth=a.countInNetWorth,
        needsAnchor=atypes.reconcilable(a.type)
        and a.active
        and reconcile.needs_anchor(a, ledger.imports, today),
        mismatch=bool(checks) and not checks[-1].ok,
        investing=investing,
        reconcilable=atypes.reconcilable(a.type),
        version=a.version,
    )
    if not detail:
        return AccountRow(**base)
    return AccountDetail(
        **base,
        notes=a.notes,
        keptBy=json.loads(a.keptBy),
        lotMethod=a.lotMethod,
        openingBalance=a.openingBalance,
        openingDate=a.openingDate,
        openingWorkedOut=start.balance,
        openingStandIn=start.standIn,
        tax=atypes.TAX[a.type],
        statementInterval=a.statementInterval,
        connectionId=a.connectionId if level == "owner" else None,
        syncAccount=a.syncAccount if level == "owner" else None,
        statementIntervalDefault=expected.default_interval(a.type, json.loads(a.keptBy)),
        statementIntervalProposal=expected.proposal(a, imports_of(s, a.id)),
        withdrawalsAMonth=a.withdrawalsAMonth,
        **_options_risk(s, a, ledger),
    )


def _options_risk(s, a, ledger) -> dict:
    if not atypes.investing(a.type):
        return {"optionsValue": None, "capitalAtRisk": None, "capitalAtRiskUnlimited": False}
    from ..options import strategies as strat

    value, risk, any_open = strat.risk_of_account(s, ledger)
    if not any_open:
        return {"optionsValue": None, "capitalAtRisk": None, "capitalAtRiskUnlimited": False}
    # Unlimited (a naked call with no margin typed) is said so, never left out (S3.5.5).
    return {"optionsValue": value, "capitalAtRisk": risk, "capitalAtRiskUnlimited": risk is None}


def imports_of(s, account_id: str) -> list[Import]:
    return list(
        s.scalars(select(Import).where(Import.accountId == account_id, Import.deleted == false()))
    )


# ---------- routes ----------


@router.get("/accounts", response_model=list[AccountRow])
def list_accounts(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        visible = access.visible_accounts(s, c.id)
        ctx = context(s, c.id, [a.id for a, _ in visible])
        return [row(s, a, level, ctx) for a, level in visible]


@router.post("/accounts", response_model=AccountDetail, status_code=201)
def create_account(body: NewAccount, request: Request, c: Caller = Depends(caller)):
    _raise(_check(body))
    with server(request).db.tx() as s:
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=c.id,
            name=body.name.strip(),
            type=body.type,
            institution=(body.institution or "").strip() or None,
            mask=body.mask or None,
            notes=body.notes,
            keptBy=exactjson.dumps(body.keptBy),
            lotMethod=body.lotMethod,
            openingBalance=body.openingBalance,
            openingDate=body.openingDate,
            countInNetWorth=(
                body.countInNetWorth if body.countInNetWorth is not None else body.type != "daf"
            ),
        )
        s.add(a)
        s.flush()
        activity.record(
            s, "account.created", actor=c.id, subject_kind="account", subject_id=a.id, owner=c.id
        )
        out = row(s, a, "owner", context(s, c.id, [a.id]), detail=True)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/accounts/{a.id}"},
    )


@router.get("/accounts/{account_id}", response_model=AccountDetail)
def get_account(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        a, level = access.account(s, c.id, account_id)
        return row(s, a, level, context(s, c.id, [a.id]), detail=True)


@router.patch("/accounts/{account_id}", response_model=AccountDetail)
def change_account(
    account_id: str,
    body: AccountChange,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    _raise(_check(body))
    sent = body.model_fields_set
    with server(request).db.tx() as s:
        a, level = access.account(s, c.id, account_id, "write")
        if a.version != version:
            raise stale(row(s, a, level, context(s, c.id, [a.id]), detail=True))
        settings_fields = {
            "lotMethod",
            "keptBy",
            "active",
            "countInNetWorth",
            "name",
            "institution",
            "mask",
            "statementInterval",
            "dismissIntervalProposal",
            "connectionId",
            "syncAccount",
            "withdrawalsAMonth",
        }
        if level != "owner" and sent & settings_fields:
            raise Problem(403, "owner-only", "Only the account's owner changes its settings.")
        changed = []
        for f in (
            "name",
            "institution",
            "mask",
            "notes",
            "lotMethod",
            "openingBalance",
            "openingDate",
            "countInNetWorth",
            "active",
        ):
            if f in sent:
                value = getattr(body, f)
                if isinstance(value, str):
                    value = value.strip() or None
                if f in ("name",) and value is None:
                    continue
                if getattr(a, f) != value:
                    setattr(a, f, value)
                    changed.append(f)
        if "keptBy" in sent and body.keptBy is not None:
            a.keptBy = exactjson.dumps(body.keptBy)
            changed.append("keptBy")
        if "withdrawalsAMonth" in sent and a.withdrawalsAMonth != body.withdrawalsAMonth:
            if body.withdrawalsAMonth is not None and (
                a.type not in ("savings", "money-market") or not 1 <= body.withdrawalsAMonth <= 99
            ):
                raise Problem(
                    422,
                    "limit-invalid",
                    "A savings account's limit: 1 to 99, or empty.",
                    [
                        FieldError(
                            "withdrawalsAMonth",
                            "limit-invalid",
                            "A savings account's limit: 1 to 99, or empty.",
                        )
                    ],
                )
            a.withdrawalsAMonth = body.withdrawalsAMonth
            changed.append("withdrawalsAMonth")
        if "statementInterval" in sent and a.statementInterval != body.statementInterval:
            a.statementInterval = body.statementInterval
            changed.append("statementInterval")
        if "connectionId" in sent or "syncAccount" in sent:
            from ..store.entities.connector import Connection

            cid = body.connectionId if "connectionId" in sent else a.connectionId
            if cid is not None:
                conn = s.get(Connection, cid)
                if conn is None or conn.deleted or conn.ownerId != c.id or conn.state == "removed":
                    raise refuse("connectionId", "not-found", "One of your own connections.")
                which = (body.syncAccount or "").strip() if "syncAccount" in sent else a.syncAccount
                if not which:
                    raise refuse(
                        "syncAccount", "sync-account-missing", "Which institution account this is."
                    )
                if (a.connectionId, a.syncAccount) != (cid, which):
                    a.connectionId, a.syncAccount = cid, which
                    changed.append("sync")
            elif a.connectionId is not None:
                a.connectionId, a.syncAccount = None, None
                changed.append("sync")
        if body.dismissIntervalProposal:
            seen = expected.proposal(a, imports_of(s, a.id))
            if seen is not None:
                a.statementIntervalDismissed = seen
                changed.append("statementIntervalDismissed")
        if changed:
            kind = (
                "account.closed"
                if "active" in changed and not a.active
                else ("account.reopened" if "active" in changed else "account.updated")
            )
            activity.record(
                s,
                kind,
                actor=c.id,
                subject_kind="account",
                subject_id=a.id,
                owner=a.ownerId,
                detail={"fields": changed},
            )
        s.flush()
        if "lotMethod" in changed:
            # Sales keep the method recorded on them; the wash sales are worked out again (S2.3).
            from .. import washes

            washes.recompute(s, a.ownerId)
        return row(s, a, level, context(s, c.id, [a.id]), detail=True)


@router.delete("/accounts/{account_id}", response_model=Deleted[None])
def delete_account(
    account_id: str, request: Request, c: Caller = Depends(caller), version: int = Depends(if_match)
):
    """Soft-deleted with everything that belongs to it (schema.md §4); only by its owner."""
    with server(request).db.tx() as s:
        a, _ = access.account(s, c.id, account_id, "owner")
        check(a, version, {"id": a.id, "version": a.version})
        a.mark_deleted(c.id)
        activity.record(
            s,
            "account.deleted",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
        s.flush()
        return Deleted[None](deleted=gone(a))


@router.get("/accounts/{account_id}/series", response_model=Series)
def account_series(
    account_id: str,
    request: Request,
    c: Caller = Depends(caller),
    range: str = Query("1Y", pattern="^(1M|3M|YTD|1Y|5Y|All)$"),
):
    today = clock.today()
    with server(request).db.read() as s:
        a, _ = access.account(s, c.id, account_id)
        ledger = repo.load(s, a)
        if range == "YTD":
            first = dt.date(today.year, 1, 1)
        elif range == "All":
            first = min([t.date for t in ledger.transactions], default=today)
        else:
            first = today - dt.timedelta(days=RANGES[range])
        investing = atypes.investing(a.type)
        days = (today - first).days
        step = 1 if days <= 400 else max(1, days // 365)
        pts = valuation.series(s, ledger, investing, first, today, step)
        return Series(points=[Point(date=d, value=v) for d, v in pts], asOf=today)


@router.get("/accounts/{account_id}/holdings", response_model=Holdings)
def account_holdings(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        a, _ = access.account(s, c.id, account_id)
        ledger = repo.load(s, a)
        replay = ledger.replay()
        positions = valuation.positions(s, ledger)
        insts = {
            i.id: i
            for i in s.scalars(
                select(Instrument).where(Instrument.id.in_([p.instrumentId for p in positions]))
            )
        }
        rows = []
        for p in sorted(positions, key=lambda p: -(p.value or Decimal(0))):
            inst = insts[p.instrumentId]
            lots = [x for x in replay.open if x.instrumentId == p.instrumentId]
            rows.append(
                HoldingRow(
                    instrumentId=inst.id,
                    symbol=inst.symbol,
                    name=inst.name,
                    instrumentClass=inst.instrumentClass,
                    quantity=p.quantity,
                    costBasis=p.costBasis,
                    price=p.price.price if p.price else None,
                    priceAsOf=p.price.asOf if p.price else None,
                    priceSource=p.price.source if p.price else None,
                    value=p.value,
                    gain=p.gain,
                    lots=[
                        LotRow(
                            lotId=x.lotId,
                            acquiredOn=x.acquiredOn,
                            quantity=x.quantity,
                            basis=x.basis,
                            basisMissing=x.basisMissing,
                            standIn=x.standIn,
                            longTerm=long_term(x.heldFrom or x.acquiredOn, clock.today()),
                        )
                        for x in sorted(lots, key=lambda x: x.acquiredOn)
                    ],
                )
            )
        cash = ledger.balance()
        total = cash + sum((r.value or Decimal(0) for r in rows), Decimal(0))
        problems = [
            {
                "kind": p.kind,
                "instrumentId": p.instrumentId,
                "date": p.date.isoformat(),
                "transactionId": p.transactionId,
            }
            for p in replay.problems
        ]
        return Holdings(cash=cash, total=total, holdings=rows, problems=problems)


def _reconciliation_row(s, r: Reconciliation) -> ReconciliationRow:
    cleared = sum(
        (
            t.amount
            for t in s.scalars(
                select(Transaction).where(
                    Transaction.accountId == r.accountId,
                    Transaction.deleted == false(),
                    Transaction.date <= r.statementDate,
                    (Transaction.cleared) | (Transaction.reconciliationId.is_not(None)),
                )
            )
        ),
        Decimal(0),
    )
    a = s.get(Account, r.accountId)
    opening = repo.load(s, a).opening().balance
    total = opening + cleared
    return ReconciliationRow(
        id=r.id,
        statementDate=r.statementDate,
        statementBalance=r.statementBalance,
        cleared=total,
        difference=r.statementBalance - total,
        finishedAt=r.finishedAt,
        version=r.version,
    )


@router.get("/accounts/{account_id}/reconcile", response_model=ReconcileView)
def account_reconcile(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        a, _ = access.account(s, c.id, account_id)
        ledger = repo.load(s, a)
        cover = reconcile.coverage(ledger.imports)
        start = ledger.opening()
        checks = reconcile.checks(start, ledger.transactions, ledger.anchors, cover)
        recs = s.scalars(
            select(Reconciliation)
            .where(Reconciliation.accountId == a.id, Reconciliation.deleted == false())
            .order_by(Reconciliation.statementDate)
        ).all()
        asof = s.scalar(
            select(func.max(HoldingCheck.asOf)).where(
                HoldingCheck.accountId == a.id, HoldingCheck.deleted == false()
            )
        )
        rows = (
            s.scalars(
                select(HoldingCheck)
                .where(
                    HoldingCheck.accountId == a.id,
                    HoldingCheck.deleted == false(),
                    HoldingCheck.asOf == asof,
                )
                .order_by(HoldingCheck.cash, HoldingCheck.label)
            ).all()
            if asof
            else []
        )
        held_lines = holdingcheck.compare(ledger, asof, rows) if asof else []
        symbols = {
            i.id: i.symbol
            for i in s.scalars(
                select(Instrument).where(Instrument.id.in_([r.instrumentId for r in rows]))
            )
        }
        return ReconcileView(
            periods=[
                PeriodRow(start=p.start, end=p.end, importIds=p.importIds) for p in cover.periods
            ],
            gaps=[list(g) for g in cover.gaps],
            overlaps=[list(o) for o in cover.overlaps],
            checks=[
                CheckRow(
                    date=k.date,
                    reported=k.reported,
                    computed=k.computed,
                    difference=k.difference,
                    source=k.source,
                    ok=k.ok,
                    windowFrom=k.windowFrom,
                    suspects=Suspects(
                        duplicates=k.suspects.duplicates,
                        changed=k.suspects.changed,
                        gaps=[list(g) for g in k.suspects.gaps],
                        firstParting=k.suspects.firstParting,
                    )
                    if k.suspects
                    else None,
                )
                for k in checks
            ],
            valueChecks=[
                ValueCheckRow(
                    date=v.date,
                    reported=v.reported,
                    computed=v.computed,
                    difference=v.difference,
                    ok=v.ok,
                )
                for v in reconcile.value_checks(s, ledger, ledger.anchors)
            ],
            holdingChecksAsOf=asof,
            holdingChecks=[
                HoldingCheckRow(
                    label=x.label,
                    instrumentId=x.instrumentId,
                    symbol=symbols.get(x.instrumentId),
                    statement=x.statement,
                    held=x.held,
                    difference=x.difference,
                    statementBasis=x.statementBasis,
                    heldBasis=x.heldBasis,
                    cash=x.cash,
                    ok=x.ok,
                )
                for x in held_lines
            ],
            needsAnchor=reconcile.needs_anchor(a, ledger.imports, clock.today()),
            openingStandIn=start.standIn,
            reconciliations=[_reconciliation_row(s, r) for r in recs],
        )


@router.post("/accounts/{account_id}/anchors", status_code=201)
def add_anchor(account_id: str, body: NewAnchor, request: Request, c: Caller = Depends(caller)):
    """A balance typed from the institution's site (S1.11.2)."""
    if body.date > clock.today():
        raise refuse("date", "date-in-future", "A reported balance can't be in the future.")
    with server(request).db.tx() as s:
        a, _ = access.account(s, c.id, account_id, "write")
        s.add(
            Anchor(
                id=ids.new_id("Anchr"),
                accountId=a.id,
                date=body.date,
                balance=body.balance,
                source="typed",
                note=body.note,
                createdById=c.id,
            )
        )
        activity.record(
            s,
            "account.balance-typed",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
    return Response(status_code=201)


@router.post("/accounts/{account_id}/adjustments", status_code=201)
def add_adjustment(
    account_id: str, body: NewAdjustment, request: Request, c: Caller = Depends(caller)
):
    """Accepting a difference as a balance adjustment, with a note (S1.11.4)."""
    if not body.note.strip():
        raise refuse("note", "note-required", "Say why the balance is adjusted.")
    with server(request).db.tx() as s:
        a, _ = access.account(s, c.id, account_id, "write")
        s.add(
            Transaction(
                id=ids.new_id("Txn"),
                accountId=a.id,
                date=body.date,
                kind="adjustment",
                amount=body.amount,
                payee="Balance adjustment",
                memo=body.note.strip(),
                createdById=c.id,
            )
        )
        activity.record(
            s,
            "account.balance-adjusted",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
    return Response(status_code=201)


@router.post(
    "/accounts/{account_id}/reconciliations", response_model=ReconciliationRow, status_code=201
)
def start_reconciliation(
    account_id: str, body: NewReconciliation, request: Request, c: Caller = Depends(caller)
):
    """Ticking off (S1.11.6): a statement's closing date and balance."""
    with server(request).db.tx() as s:
        a, _ = access.account(s, c.id, account_id, "write")
        r = Reconciliation(
            id=ids.new_id("Recon"),
            accountId=a.id,
            statementDate=body.statementDate,
            statementBalance=body.statementBalance,
        )
        s.add(r)
        s.flush()
        return _reconciliation_row(s, r)


@router.patch("/reconciliations/{rec_id}", response_model=ReconciliationRow)
def finish_reconciliation(
    rec_id: str,
    body: ReconciliationChange,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    with server(request).db.tx() as s:
        r = s.get(Reconciliation, rec_id)
        if r is None or r.deleted:
            raise Problem(404, "not-found", "Not found")
        a, _ = access.account(s, c.id, r.accountId, "write")
        if r.version != version:
            raise stale(_reconciliation_row(s, r))
        current = _reconciliation_row(s, r)
        if body.finish and r.finishedAt is None:
            if current.difference != 0:
                raise refuse(
                    None, "not-balanced", "Tick transactions until the difference is zero.", 409
                )
            for t in s.scalars(
                select(Transaction).where(
                    Transaction.accountId == a.id,
                    Transaction.deleted == false(),
                    Transaction.cleared,
                    Transaction.date <= r.statementDate,
                    Transaction.reconciliationId.is_(None),
                )
            ):
                t.reconciliationId = r.id
            r.finishedAt, r.finishedById = clock.now(), c.id
            activity.record(
                s,
                "account.reconciled",
                actor=c.id,
                subject_kind="account",
                subject_id=a.id,
                owner=a.ownerId,
            )
        s.flush()
        return _reconciliation_row(s, r)
