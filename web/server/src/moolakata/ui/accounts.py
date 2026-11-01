"""Accounts (requirements S1, S12.2.2): the list, an account's page, its holdings, its
balance chart and its reconciliation."""

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import false, func, select

from .. import access, activity, clock, exactjson, valuation
from ..access import Perms
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
from . import save
from .conventions import (
    Access,
    ExactRoute,
    IdOf,
    Model,
    Money,
    Quantity,
)
from .deps import Caller, caller, server
from .sharing import counted_for

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["accounts"])
# How an account is kept current (S1.3): by imports (files and statements alike), by hand, or
# by its wallet. It sets only whether statements are expected (S1.11.7); what its positions are
# is told by its transactions (R3.2).
KEPT_BY = ("manual", "file", "bitcoin")
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
    access: Access
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
    statementIntervalDismissed: str | None  # a proposal set aside
    withdrawalsAMonth: int | None  # a savings account's limit, the bank's (S1.2)
    optionsValue: Money | None  # an investing account's options' market value
    capitalAtRisk: Money | None  # beside it (S3.5.6)
    capitalAtRiskUnlimited: bool = False
    # Sync using MoolaKata Connector (S18.6.2): the owner's Connection and which of its
    # institution accounts this is; shown to the owner only.
    connectionId: str | None
    syncAccount: str | None
    # A self-custody wallet's keys and addresses, one a line, and its gap limit (S1.6.1).
    walletKeys: str | None = None
    gapLimit: int = 20
    # A receiver's Count in my totals, a record of the save (CountedAccount): none until set.
    countedId: str | None = None
    countedVersion: int = 0


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


class AccountRecord(Model):
    """An account as a draft saves it (S12.15): its type is chosen when it is made; its
    settings are its owner's (S10.3)."""

    name: str
    type: str
    institution: str | None = None
    mask: str | None = None
    notes: str | None = None
    keptBy: list[str] = Field(default_factory=lambda: ["manual"])
    lotMethod: str = "fifo"
    openingBalance: Money | None = None
    openingDate: dt.date | None = None
    countInNetWorth: bool | None = None  # a donor-advised fund counts in no one's unless said
    active: bool = True
    statementInterval: str | None = None  # null: the type's default (S1.11.7)
    # The interval learned from what arrives, set aside until another is learned.
    statementIntervalDismissed: str | None = None
    withdrawalsAMonth: int | None = None  # a savings account's limit, the bank's (S1.2)
    # Sync using MoolaKata Connector (S18.6.2), the owner's alone: a Connection of theirs and
    # the institution account; null turns it off.
    connectionId: IdOf("Conn") | None = None  # type: ignore[valid-type]
    syncAccount: str | None = None
    # A self-custody wallet's extended public keys, descriptors and addresses, one a line, and
    # how far past the last address used it looks (S1.6.1): public data only.
    walletKeys: str | None = None
    gapLimit: int = 20


WALLET_FIELDS = ("walletKeys", "gapLimit")


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


class NewReconciliation(Model):
    statementDate: dt.date
    statementBalance: Money


# ---------- shaping ----------


def _check(body: NewAccount | AccountRecord, new: bool | None = None) -> list[FieldError]:
    errors = []
    sent = body.model_fields_set
    new = isinstance(body, NewAccount) if new is None else new
    named = new or "name" in sent
    if named and (not (body.name or "").strip() or len(body.name or "") > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    if new and body.type not in ACCOUNT_TYPES:
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
        errors.append(FieldError("keptBy", "kept-by-invalid", "Imports, manual or bitcoin."))
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
        new or {"openingBalance", "openingDate"} & sent
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


def row(s, a: Account, p: Perms, ctx: Context, detail: bool = False) -> AccountRow | AccountDetail:
    from . import wallets

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
        access=Access.of(p),
        sharedWith=len(access.holders_of(s, Account, a.id)) - 1 if p.shareable else 0,
        counted=a.countInNetWorth if p.mine else a.id in ctx.counted,
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
        connectionId=a.connectionId if p.configurable else None,
        syncAccount=a.syncAccount if p.configurable else None,
        statementIntervalDefault=expected.default_interval(a.type, json.loads(a.keptBy)),
        statementIntervalProposal=expected.proposal(a, imports_of(s, a.id)),
        statementIntervalDismissed=a.statementIntervalDismissed,
        withdrawalsAMonth=a.withdrawalsAMonth,
        **_options_risk(s, a, ledger),
        **wallets.current(s, a),
        **_counted_ref(s, ctx.userId, a, p),
    )


def _counted_ref(s, user_id: str, a: Account, p: Perms) -> dict:
    if p.mine:
        return {}
    from ..store.entities.sharing import CountedAccount
    from ..store.rows import by_key

    row = by_key(s, CountedAccount, userId=user_id, accountId=a.id)
    if row is None or row.deleted:
        return {}
    return {"countedId": row.id, "countedVersion": row.version}


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
    with server(request).db.read(user=c.id) as s:
        visible = access.accounts(s, c.id)
        ctx = context(s, c.id, [a.id for a, _ in visible])
        return [row(s, a, p, ctx) for a, p in visible]


def _make(s, c: Caller, body, account_id: str) -> Account:
    a = Account(
        id=account_id,
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
    return a


@router.get("/accounts/{account_id}", response_model=AccountDetail)
def get_account(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        a, p = access.account(s, c.id, account_id)
        return row(s, a, p, context(s, c.id, [a.id]), detail=True)


ACCOUNT_FIELDS = (
    "name",
    "institution",
    "mask",
    "notes",
    "lotMethod",
    "openingBalance",
    "openingDate",
    "countInNetWorth",
    "active",
)


def _change(s, c: Caller, a: Account, p: Perms, body, sent: set[str]) -> None:
    """The fields `sent` set on an account: its settings with `configurable` (S10.3)."""
    settings_fields = {
        "lotMethod",
        "keptBy",
        "active",
        "countInNetWorth",
        "name",
        "institution",
        "mask",
        "statementInterval",
        "statementIntervalDismissed",
        "connectionId",
        "syncAccount",
        "withdrawalsAMonth",
    }
    if not p.configurable and sent & settings_fields:
        raise Problem(403, "owner-only", "Only the account's owner changes its settings.")
    changed = []
    for f in ACCOUNT_FIELDS:
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
    dismissed = getattr(body, "statementIntervalDismissed", None)
    if "statementIntervalDismissed" in sent and a.statementIntervalDismissed != dismissed:
        if dismissed is not None and dismissed not in expected.INTERVALS:
            raise refuse("statementIntervalDismissed", "statement-interval-invalid", "An interval.")
        a.statementIntervalDismissed = dismissed
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


@router.get("/accounts/{account_id}/series", response_model=Series)
def account_series(
    account_id: str,
    request: Request,
    c: Caller = Depends(caller),
    range: str = Query("1Y", pattern="^(1M|3M|YTD|1Y|5Y|All)$"),
):
    today = clock.today()
    with server(request).db.read(user=c.id) as s:
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
    with server(request).db.read(user=c.id) as s:
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
    with server(request).db.read(user=c.id) as s:
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


class AnchorRecord(Model):
    """A balance typed from the institution's site (S1.11.2), as its dialog's draft saves it."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    date: dt.date
    balance: Money
    note: str | None = None


class AnchorOut(AnchorRecord):
    id: str
    source: str  # typed, or the import or statement it came from
    version: int


def _anchor_check(body: AnchorRecord) -> None:
    if body.date > clock.today():
        raise refuse("date", "date-in-future", "A reported balance can't be in the future.")


def _anchor_create(ctx, record_id: str, body: AnchorRecord) -> None:
    s, c = ctx.s, ctx.caller
    _anchor_check(body)
    a, _ = access.account(s, c.id, body.accountId, "write")
    s.add(
        Anchor(
            id=record_id,
            accountId=a.id,
            date=body.date,
            balance=body.balance,
            source="typed",
            note=(body.note or "").strip() or None,
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


def _anchor_editable(ctx, record_id: str) -> Anchor:
    an = ctx.s.get(Anchor, record_id)
    if an is None or an.deleted:
        raise Problem(404, "not-found", "Not found")
    access.account(ctx.s, ctx.caller.id, an.accountId, "write")
    if an.source != "typed":
        raise refuse(None, "anchor-imported", "A balance from a file changes with the file.")
    return an


def _anchor_update(ctx, an: Anchor, body: AnchorRecord) -> None:
    if body.accountId != an.accountId:
        raise refuse("accountId", "anchor-fixed", "A balance stays with its account.")
    _anchor_check(body)
    an.date, an.balance = body.date, body.balance
    an.note = (body.note or "").strip() or None


def _anchor_read(ctx, record_id: str) -> AnchorOut:
    an = ctx.s.get(Anchor, record_id)
    return AnchorOut(
        id=an.id,
        accountId=an.accountId,
        date=an.date,
        balance=an.balance,
        note=an.note,
        source=an.source,
        version=an.version,
    )


save.register(
    save.Kind(
        prefix="Anchr",
        entity=Anchor,
        fields=AnchorRecord,
        create=_anchor_create,
        editable=_anchor_editable,
        current=lambda ctx, an: {
            "accountId": an.accountId,
            "date": an.date,
            "balance": an.balance,
            "note": an.note,
        },
        update=_anchor_update,
        delete=lambda ctx, an: an.mark_deleted(ctx.caller.id),
        read=_anchor_read,
    )
)


class ReconciliationRecord(NewReconciliation):
    """Ticking off against a statement (S1.11.6), as its dialog's draft saves it: made with the
    statement's closing date and balance; `finished` once the ticked transactions leave no
    difference, which marks them reconciled. A finished one stays; an unfinished one may go."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    finished: bool = False


def _recon_create(ctx, record_id: str, body: ReconciliationRecord) -> None:
    s, c = ctx.s, ctx.caller
    a, _ = access.account(s, c.id, body.accountId, "write")
    r = Reconciliation(id=record_id, accountId=a.id, statementDate=body.statementDate,
                       statementBalance=body.statementBalance)  # fmt: skip
    s.add(r)
    s.flush()
    if body.finished:
        _finish(ctx, r)


def _recon_editable(ctx, record_id: str) -> Reconciliation:
    r = ctx.s.get(Reconciliation, record_id)
    if r is None or r.deleted:
        raise Problem(404, "not-found", "Not found")
    access.account(ctx.s, ctx.caller.id, r.accountId, "write")
    return r


def _recon_current(ctx, r: Reconciliation) -> dict:
    return {
        "accountId": r.accountId,
        "statementDate": r.statementDate,
        "statementBalance": r.statementBalance,
        "finished": r.finishedAt is not None,
    }


def _finish(ctx, r: Reconciliation) -> None:
    """The ticked transactions up to the statement's date are reconciled with it."""
    s, c = ctx.s, ctx.caller
    if _reconciliation_row(s, r).difference != 0:
        raise refuse("finished", "not-balanced", "Tick transactions until the difference is zero.")
    for t in s.scalars(
        select(Transaction).where(
            Transaction.accountId == r.accountId,
            Transaction.deleted == false(),
            Transaction.cleared,
            Transaction.date <= r.statementDate,
            Transaction.reconciliationId.is_(None),
        )
    ):
        t.reconciliationId = r.id
    r.finishedAt, r.finishedById = clock.now(), c.id
    a = s.get(Account, r.accountId)
    activity.record(s, "account.reconciled", actor=c.id, subject_kind="account",
                    subject_id=a.id, owner=a.ownerId)  # fmt: skip


def _recon_update(ctx, r: Reconciliation, body: ReconciliationRecord) -> None:
    current = _recon_current(ctx, r)
    if current["finished"]:
        raise refuse(None, "reconciled", "A reconciled period stays as it was reconciled.")
    if body.accountId != r.accountId:
        raise refuse("accountId", "reconciliation-fixed", "It stays with its account.")
    r.statementDate, r.statementBalance = body.statementDate, body.statementBalance
    r.updatedAt = clock.now()
    ctx.s.flush()
    if body.finished:
        _finish(ctx, r)


def _recon_delete(ctx, r: Reconciliation) -> None:
    if r.finishedAt is not None:
        raise refuse(None, "reconciled", "A reconciled period stays as it was reconciled.")
    r.mark_deleted(ctx.caller.id)


save.register(
    save.Kind(
        prefix="Recon",
        entity=Reconciliation,
        fields=ReconciliationRecord,
        create=_recon_create,
        editable=_recon_editable,
        current=_recon_current,
        update=_recon_update,
        delete=_recon_delete,
        read=lambda ctx, record_id: _reconciliation_row(
            ctx.s, ctx.s.get(Reconciliation, record_id)
        ),
    )
)


# ---------- an account in a dialog's or a screen's draft (S12.15, S13.8.11) ----------


def _account_create(ctx, record_id: str, body: AccountRecord) -> None:
    _raise(_check(body, new=True))
    a = _make(ctx.s, ctx.caller, body, record_id)
    later = {
        f
        for f in ("active", "statementInterval", "withdrawalsAMonth", "connectionId", "syncAccount")
        if getattr(body, f) != AccountRecord.model_fields[f].default
    }
    if later:
        _change(ctx.s, ctx.caller, a, access.OWNER, body, later)
    if body.walletKeys:
        from . import wallets

        wallets.replace(ctx, a, body.walletKeys, body.gapLimit)


def _account_editable(ctx, record_id: str) -> Account:
    return access.account(ctx.s, ctx.caller.id, record_id, "write")[0]


def _account_current(ctx, a: Account) -> dict:
    from . import wallets

    return {
        "type": a.type,
        "keptBy": json.loads(a.keptBy or "[]"),
        "statementInterval": a.statementInterval,
        "statementIntervalDismissed": a.statementIntervalDismissed,
        "withdrawalsAMonth": a.withdrawalsAMonth,
        "connectionId": a.connectionId,
        "syncAccount": a.syncAccount,
        **{f: getattr(a, f) for f in ACCOUNT_FIELDS},
        **wallets.current(ctx.s, a),
    }


def _account_update(ctx, a: Account, body: AccountRecord) -> None:
    from . import wallets

    current = _account_current(ctx, a)
    sent = {f for f in AccountRecord.model_fields if getattr(body, f) != current[f]}
    if "type" in sent:
        raise refuse("type", "type-fixed", "An account keeps its type.")
    _raise(_check(body, new=False))
    p = access.account(ctx.s, ctx.caller.id, a.id, "write")[1]
    _change(ctx.s, ctx.caller, a, p, body, sent - set(WALLET_FIELDS))
    if sent & set(WALLET_FIELDS):
        wallets.replace(ctx, a, body.walletKeys, body.gapLimit)
        a.updatedAt = clock.now()  # its keys are the account's: its version moves with them


def _account_delete(ctx, a: Account) -> None:
    """Soft-deleted with everything that belongs to it (schema.md §4); only by its owner."""
    access.account(ctx.s, ctx.caller.id, a.id, "deletable")
    a.mark_deleted(ctx.caller.id)
    activity.record(
        ctx.s,
        "account.deleted",
        actor=ctx.caller.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
    )


def _account_read(ctx, record_id: str) -> AccountDetail:
    a, p = access.account(ctx.s, ctx.caller.id, record_id)
    return row(ctx.s, a, p, context(ctx.s, ctx.caller.id, [a.id]), detail=True)


save.register(
    save.Kind(
        prefix="Acct",
        entity=Account,
        fields=AccountRecord,
        create=_account_create,
        editable=_account_editable,
        current=_account_current,
        update=_account_update,
        delete=_account_delete,
        read=_account_read,
    )
)
