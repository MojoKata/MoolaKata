"""Budgets (requirements S7.1–S7.5): a budget's month, its plan, cash flow, trends and the
recurring transactions in its accounts. A budget is owned by a user and shared like an account;
a household budget is one shared with a group at write (S10.3)."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, budgets, clock, ids
from ..budgets import plan, recurring
from ..errors import FieldError, Problem, refuse
from ..store.entities.accounts import Account, Category, Transaction
from ..store.entities.budgets import Budget, BudgetAccount, BudgetLine, BudgetMove
from ..store.entities.users import User
from .conventions import Deleted, ExactRoute, Model, Money, check, gone, if_match, stale
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["budgets"])


class RoleOut(Model):
    """Where an account's money comes from (S7.1.6), worked out unless chosen."""

    accountId: str
    paidFromId: str | None  # a card's paying account
    paidFromLearned: bool
    movedFromId: str | None  # where money for reserves held here moves from
    movedFromProposed: bool


class RoleIn(Model):
    accountId: str
    paidFromId: str | None = None  # none: learned from the card's payments
    movedFromId: str | None = None  # none: proposed from the transfers in


class BudgetRow(Model):
    id: str
    name: str
    ownerId: str
    ownerName: str
    level: str
    accountIds: list[str]
    sharedWith: int
    method: str  # tracking or envelope (S7.1.3)
    reserves: bool  # its options (S7.1.4)
    moves: bool
    startMonth: dt.date | None
    roles: list[RoleOut]
    version: int


class NewBudget(Model):
    name: str
    accountIds: list[str] = Field(default_factory=list)
    method: str = "tracking"
    reserves: bool = False
    moves: bool = False


class BudgetChange(Model):
    name: str | None = None
    accountIds: list[str] | None = None
    reserves: bool | None = None
    moves: bool | None = None
    roles: list[RoleIn] | None = None


class PlanLine(Model):
    categoryId: str
    amount: Money
    cadence: str = "month"
    rollover: bool = False
    overspend: str = "carry"  # an envelope budget's: carried negative, or from next month
    projectionId: str | None = None  # a savings line's active projection
    target: Money | None = None  # a reserve's (S7.10), with reserves on
    heldInId: str | None = None  # the account its money is kept in


class Plan(Model):
    """The plan from a month on: the categories listed, and none other."""

    month: dt.date
    lines: list[PlanLine]


class MonthRow(Model):
    categoryId: str
    label: str
    kind: str
    cadence: str
    rollover: bool
    planned: Money
    carried: Money
    actual: Money
    remaining: Money
    state: str
    fromPlan: str | None  # gifts or giving: planned by those plans, not here (S7.3.6)
    overspend: str
    projectionId: str | None
    projectionName: str | None
    projectionMonthly: Money | None
    moved: Money  # moves in, less moves out, this month (S7.11)
    target: Money | None  # a reserve's (S7.10)
    heldInId: str | None
    balance: Money | None  # a reserve's, at the month's end
    putIn: Money | None


class ReserveHeld(Model):
    categoryId: str
    label: str
    balance: Money


class LandedOut(Model):
    transactionId: str
    date: dt.date
    payee: str | None
    amount: Money
    free: Money


class HeldInOut(Model):
    """An account reserves are held in, and what is to move there (S7.10.4)."""

    accountId: str
    accountName: str
    movedFromId: str | None
    movedFromName: str | None
    reserves: list[ReserveHeld]
    total: Money
    movedIn: Money
    given: Money
    balance: Money
    toMove: Money  # + to move here from moved from, − back to it
    withdrawals: int
    limit: int | None
    overLimit: bool  # a move back now would go past the withdrawals allowed
    unassigned: list[LandedOut]


class CardOut(Model):
    accountId: str
    accountName: str
    paidFromId: str | None
    paidFromName: str | None
    owed: Money
    paid: Money  # this month
    charges: Money  # interest and fees this month


class WhereView(Model):
    month: dt.date
    sayToMove: bool  # only the active budget says what to move (S7.12.2)
    heldIn: list[HeldInOut]
    cards: list[CardOut]


class GiveIn(Model):
    """Landed money given to a reserve, spread among those held there, or kept (S7.10.5)."""

    transactionId: str
    to: str  # a reserve's category id, "spread" or "own"
    amount: Money


class Proposal(Model):
    """A plan line estimated from history (S7.1.5)."""

    categoryId: str
    label: str
    amount: Money
    cadence: str
    source: str  # history or recurring
    detail: str
    target: Money | None  # a yearly cost proposed as a reserve


class Unplanned(Model):
    categoryId: str
    label: str
    spent: Money


class MovedRow(Model):
    """A transfer between one of the budget's accounts and one it doesn't count, with no
    category: it counts nowhere until sorted (S7.3.2)."""

    transactionId: str
    date: dt.date
    accountName: str
    otherAccountName: str  # *an account not shared* for one the viewer can't see (S11.3.1)
    amount: Money  # − left the budget, + entered it
    payee: str | None


class MonthView(Model):
    month: dt.date
    rows: list[MonthRow]
    unplanned: list[Unplanned]
    income: Money
    expectedIncome: Money
    spent: Money
    saved: Money
    moved: list[MovedRow]
    plannedSpending: Money
    uncategorised: int
    daysLeft: int
    canWrite: bool
    version: int  # the budget's: a change to the plan is made against it (S13.8.6)


class LeftOut(Model):
    """An account the budget doesn't count that often receives transfers from its accounts."""

    accountId: str
    name: str
    transfers: int


class Flow(Model):
    name: str
    amount: Money


class CashFlow(Model):
    month: dt.date
    sources: list[Flow]
    uses: list[Flow]
    income: Money
    spending: Money


class TrendPoint(Model):
    month: dt.date
    planned: Money
    actual: Money


class RecurringRow(Model):
    payee: str
    accountId: str | None  # None for an account not shared with the viewer (S11.3.1)
    accountName: str
    every: str
    last: dt.date
    next: dt.date
    usual: Money
    lastAmount: Money
    count: int
    missed: bool
    changed: bool


def _accounts_of(s, b: Budget, viewer: str | None = None) -> list[str]:
    return budgets.account_ids(s, b, viewer)


def _names(s, viewer: str, account_ids: set[str]) -> dict[str, str]:
    """The names of the accounts a viewer may see: their own and those shared with them, so a
    shared budget never names another account (S7.1.1, S11.3.1)."""
    if not account_ids:
        return {}
    reach = access.reach(s, viewer)
    return {
        a.id: a.name
        for a in s.scalars(select(Account).where(Account.id.in_(account_ids)))
        if access.account_level(s, viewer, a, reach) is not None
    }


def shape(s, b: Budget, level: str, viewer: str | None = None) -> BudgetRow:
    owner = s.get(User, b.ownerId)
    shared = len(access.holders(s, "budget", b.id, b.ownerId)) - 1 if level == "owner" else 0
    accts = _accounts_of(s, b, viewer)
    rows = list(s.scalars(select(Account).where(Account.id.in_(accts))))
    return BudgetRow(
        id=b.id,
        name=b.name,
        ownerId=b.ownerId,
        ownerName=owner.displayName,
        level=level,
        accountIds=accts,
        sharedWith=shared,
        method=b.method,
        reserves=b.reserves,
        moves=b.moves,
        startMonth=b.startMonth,
        roles=[RoleOut(**r.__dict__) for r in plan.roles(s, b, rows, clock.today())],
        version=b.version,
    )


def _check(s, user_id: str, body) -> list[FieldError]:
    errors = []
    if body.name is not None and (not body.name.strip() or len(body.name) > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    if body.accountIds is not None:
        mine = {a.id for a, _ in access.visible_accounts(s, user_id)}
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


def _set_accounts(s, b: Budget, wanted: list[str], by: str) -> None:
    current = {
        m.accountId: m
        for m in s.scalars(select(BudgetAccount).where(BudgetAccount.budgetId == b.id))
    }
    now = clock.now()
    for aid in dict.fromkeys(wanted):
        m = current.get(aid)
        if m is None:
            s.add(BudgetAccount(budgetId=b.id, accountId=aid, createdAt=now))
        elif m.deleted:
            m.restore()
    for aid, m in current.items():
        if aid not in wanted and not m.deleted:
            m.mark_deleted(by, now)


def _set_roles(s, b: Budget, wanted: list[RoleIn]) -> None:
    """A card's paying account, or where reserves' money moves from, chosen; none goes back to
    what the history says."""
    members = {
        m.accountId: m
        for m in s.scalars(
            select(BudgetAccount).where(
                BudgetAccount.budgetId == b.id, BudgetAccount.deleted == false()
            )
        )
    }
    for i, r in enumerate(wanted):
        m = members.get(r.accountId)
        for f in ("paidFromId", "movedFromId"):
            v = getattr(r, f)
            if m is None or (v is not None and v not in members):
                raise refuse(
                    f"roles.{i}.{f}", "account-unknown", "Choose one of the budget's accounts."
                )
        m.paidFromId, m.movedFromId = r.paidFromId, r.movedFromId


def _month(value: str | None) -> dt.date:
    if not value:
        return budgets.month_of(clock.today())
    try:
        return budgets.month_of(dt.date.fromisoformat(value + "-01" if len(value) == 7 else value))
    except ValueError:
        raise Problem(422, "month-invalid", "A month such as 2026-10.") from None


@router.get("/budgets", response_model=list[BudgetRow])
def list_budgets(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        return [shape(s, b, lvl, c.id) for b, lvl in access.visible_budgets(s, c.id)]


@router.get("/budgets/left-out", response_model=list[LeftOut])
def left_out(
    request: Request,
    c: Caller = Depends(caller),
    accountIds: list[str] = Query(default_factory=list),
):
    """The caller's accounts outside these that received two or more transfers from them in
    the last year, to name when a budget is made or edited (S7.3.2). Loans are counted by
    their payments, so they're never named."""
    from ..loans import TYPES

    since = clock.today() - dt.timedelta(days=365)
    with server(request).db.read() as s:
        visible = {a.id: a for a, _ in access.visible_accounts(s, c.id)}
        chosen = [a for a in accountIds if a in visible]
        if not chosen:
            return []
        outs = s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(chosen),
                Transaction.transferId.is_not(None),
                Transaction.amount < 0,
                Transaction.deleted == false(),
                Transaction.date >= since,
            )
        ).all()
        counts: dict[str, int] = {}
        for o in s.scalars(
            select(Transaction).where(
                Transaction.id.in_([x.transferId for x in outs]), Transaction.deleted == false()
            )
        ):
            a = visible.get(o.accountId)
            if a is None or a.id in chosen or a.type in TYPES:
                continue
            counts[a.id] = counts.get(a.id, 0) + 1
        return [
            LeftOut(accountId=k, name=visible[k].name, transfers=n)
            for k, n in sorted(counts.items(), key=lambda x: -x[1])
            if n >= 2
        ]


@router.get("/budgets/{budget_id}", response_model=BudgetRow)
def get_budget(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """One budget, as its list shows it: where a new one's Location leads (S13.8.4)."""
    with server(request).db.read() as s:
        b, lvl = access.budget(s, c.id, budget_id)
        return shape(s, b, lvl, c.id)


@router.post("/budgets", response_model=BudgetRow, status_code=201)
def create_budget(body: NewBudget, request: Request, c: Caller = Depends(caller)):
    if body.method not in ("tracking", "envelope"):
        raise Problem(
            422,
            "method-invalid",
            "Tracking or envelope.",
            [FieldError("method", "method-invalid", "Tracking or envelope.")],
        )
    with server(request).db.tx() as s:
        _raise(_check(s, c.id, body))
        b = Budget(
            id=ids.new_id("Bdgt"),
            ownerId=c.id,
            name=body.name.strip(),
            method=body.method,
            reserves=body.reserves,
            # An envelope budget always has moves (S7.1.4).
            moves=body.moves or body.method == "envelope",
            startMonth=budgets.month_of(clock.today()),
        )
        s.add(b)
        s.flush()
        _set_accounts(s, b, body.accountIds, c.id)
        activity.record(
            s, "budget.created", actor=c.id, subject_kind="budget", subject_id=b.id, owner=c.id
        )
        s.flush()
        out = shape(s, b, "owner", c.id)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/budgets/{b.id}"},
    )


@router.patch("/budgets/{budget_id}", response_model=BudgetRow)
def change_budget(
    budget_id: str,
    body: BudgetChange,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    with server(request).db.tx() as s:
        b, lvl = access.budget(s, c.id, budget_id, "write")
        if b.version != version:
            raise stale(shape(s, b, lvl, c.id))
        _raise(_check(s, b.ownerId, body))
        fields = []
        if body.name is not None and body.name.strip() != b.name:
            b.name = body.name.strip()
            fields.append("name")
        if body.accountIds is not None:
            if lvl != "owner":
                raise Problem(403, "owner-only", "Only the owner chooses the accounts.")
            _set_accounts(s, b, body.accountIds, c.id)
            b.updatedAt = clock.now()
            fields.append("accounts")
        for option in ("reserves", "moves"):
            value = getattr(body, option)
            if value is not None and value != getattr(b, option):
                if option == "moves" and b.method == "envelope" and not value:
                    raise refuse("moves", "moves-needed", "An envelope budget always has moves.")
                setattr(b, option, value)
                fields.append(option)
        if body.roles is not None:
            _set_roles(s, b, body.roles)
            b.updatedAt = clock.now()
            fields.append("roles")
        if fields:
            activity.record(
                s,
                "budget.updated",
                actor=c.id,
                subject_kind="budget",
                subject_id=b.id,
                owner=b.ownerId,
                detail={"fields": fields},
            )
        s.flush()
        return shape(s, b, lvl, c.id)


@router.delete("/budgets/{budget_id}", response_model=Deleted[None])
def delete_budget(
    budget_id: str, request: Request, c: Caller = Depends(caller), version: int = Depends(if_match)
):
    with server(request).db.tx() as s:
        b, lvl = access.budget(s, c.id, budget_id, "owner")
        check(b, version, lambda: shape(s, b, lvl, c.id))
        b.mark_deleted(c.id)
        activity.record(
            s, "budget.deleted", actor=c.id, subject_kind="budget", subject_id=b.id, owner=c.id
        )
        s.flush()
        return Deleted[None](deleted=gone(b))


@router.get("/budgets/{budget_id}/month", response_model=MonthView)
def budget_month(
    budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None
):
    with server(request).db.read() as s:
        b, lvl = access.budget(s, c.id, budget_id)
        m = budgets.month_view(s, b, _month(month), clock.today(), c.id)
        names = _names(
            s, c.id, {x.accountId for x in m.moved} | {x.otherAccountId for x in m.moved}
        )
        return MonthView(
            month=m.month,
            rows=[
                MonthRow(
                    **{k: v for k, v in r.__dict__.items() if k != "projection"},
                    projectionName=r.projection[0] if r.projection else None,
                    projectionMonthly=r.projection[1] if r.projection else None,
                )
                for r in m.rows
            ],
            unplanned=[Unplanned(categoryId=i, label=lb, spent=a) for i, lb, a in m.unplanned],
            income=m.income,
            expectedIncome=m.expectedIncome,
            spent=m.spent,
            saved=m.saved,
            moved=[
                MovedRow(
                    transactionId=x.transactionId,
                    date=x.date,
                    accountName=names.get(x.accountId, "an account not shared"),
                    otherAccountName=names.get(x.otherAccountId, "an account not shared"),
                    amount=x.amount,
                    payee=x.payee,
                )
                for x in m.moved
            ],
            plannedSpending=m.plannedSpending,
            uncategorised=m.uncategorised,
            daysLeft=m.daysLeft,
            canWrite=lvl in ("owner", "write"),
            version=b.version,
        )


@router.put("/budgets/{budget_id}/plan", response_model=MonthView)
def set_plan(
    budget_id: str,
    body: Plan,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
    confirm: bool = False,
):
    """From the month given on, the plan is what the body lists; earlier months keep theirs.
    The plan belongs to the budget, so it is made against the budget's version."""
    month = budgets.month_of(body.month)
    with server(request).db.tx() as s:
        b, lvl = access.budget(s, c.id, budget_id, "write")
        check(b, version, lambda: shape(s, b, lvl, c.id))
        cats = {x.id: x for x in s.scalars(select(Category).where(Category.deleted == false()))}
        elsewhere = plan.planned_elsewhere(s, b, budgets.tree(s), month.year)
        errors = []
        seen = set()
        for i, ln in enumerate(body.lines):
            if ln.categoryId not in cats or cats[ln.categoryId].kind == "transfer":
                errors.append(
                    FieldError(f"lines.{i}.categoryId", "category-unknown", "Choose a category.")
                )
            elif ln.categoryId in seen:
                errors.append(
                    FieldError(f"lines.{i}.categoryId", "category-twice", "Each category once.")
                )
            seen.add(ln.categoryId)
            if ln.amount < 0:
                errors.append(
                    FieldError(f"lines.{i}.amount", "amount-negative", "Plan zero or more.")
                )
            if ln.cadence not in ("month", "year"):
                errors.append(
                    FieldError(f"lines.{i}.cadence", "cadence-invalid", "Monthly or yearly.")
                )
            if ln.categoryId in elsewhere:
                errors.append(
                    FieldError(
                        f"lines.{i}.categoryId",
                        "planned-elsewhere",
                        "Planned by your gift or giving plans.",
                    )
                )
            if ln.overspend not in ("carry", "next"):
                errors.append(
                    FieldError(
                        f"lines.{i}.overspend",
                        "overspend-invalid",
                        "Carried negative, or from next month's To Budget.",
                    )
                )
            if ln.target is not None and (
                not b.reserves or ln.cadence != "month" or ln.target <= 0
            ):
                errors.append(
                    FieldError(
                        f"lines.{i}.target",
                        "target-invalid",
                        "A monthly line in a budget with reserves, aiming above zero.",
                    )
                )
            if ln.heldInId and ln.heldInId not in budgets.account_ids(s, b):
                errors.append(
                    FieldError(
                        f"lines.{i}.heldInId", "account-unknown", "One of the budget's accounts."
                    )
                )
            if ln.projectionId and not _projection_ok(s, b, ln.projectionId):
                errors.append(
                    FieldError(
                        f"lines.{i}.projectionId", "projection-unknown", "Choose a projection."
                    )
                )
        _raise(errors)
        every = budgets.lines(s, b)
        current = budgets.in_force(every, month)
        wanted = {ln.categoryId: ln for ln in body.lines}
        # A reserve's balance stops being kept when its line or its target goes: asked first
        # (S7.10.3).
        if not confirm:
            from ..budgets import reserves

            tr = budgets.tree(s)
            accts = budgets.account_ids(s, b)
            moved = reserves.net_moves(reserves.moves(s, b))
            for cat_id, old in current.items():
                new = wanted.get(cat_id)
                if old.target is None or (new is not None and new.target is not None):
                    continue
                r = reserves.reserve(
                    s, tr, accts, every, moved, cat_id, budgets.add_months(month, -1)
                )
                if r is not None and r.balance:
                    raise Problem(
                        409,
                        "reserve-balance",
                        f"{tr.label(cat_id)} holds {r.balance:,.2f}: it stops being kept.",
                    )
        for cat_id in set(current) | set(wanted):
            new = wanted.get(cat_id)
            values = (
                (
                    new.amount,
                    new.cadence,
                    new.rollover or new.target is not None,  # a reserve always rolls over
                    new.overspend,
                    new.projectionId,
                    new.target,
                    new.heldInId if new.target is not None else None,
                )
                if new
                else (Decimal(0), "month", False, "carry", None, None, None)
            )
            old = current.get(cat_id)
            fields = (
                "amount",
                "cadence",
                "rollover",
                "overspend",
                "projectionId",
                "target",
                "heldInId",
            )
            if old is not None and tuple(getattr(old, f) for f in fields) == values:
                continue
            same_month = next(
                (x for x in every if x.categoryId == cat_id and x.fromMonth == month), None
            )
            if same_month is not None:
                for f, v in zip(fields, values, strict=True):
                    setattr(same_month, f, v)
            else:
                s.add(
                    BudgetLine(
                        id=ids.new_id("BdgLn"),
                        budgetId=b.id,
                        categoryId=cat_id,
                        fromMonth=month,
                        **dict(zip(fields, values, strict=True)),
                    )
                )
        b.updatedAt = clock.now()
        activity.record(
            s,
            "budget.planned",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
        s.flush()
    return budget_month(budget_id, request, c, month.isoformat()[:7])


def _projection_ok(s, b: Budget, projection_id: str) -> bool:
    from ..store.entities.projections import Projection

    p = s.get(Projection, projection_id)
    return p is not None and not p.deleted and p.ownerId == b.ownerId


@router.get("/budgets/{budget_id}/where", response_model=WhereView)
def where(budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None):
    """Where the money is (S7.10.4): each account reserves are held in, what is to move there
    or back, the money landed there waiting to be given, and each card's payments."""
    from ..budgets import reserves

    m = _month(month)
    today = clock.today()
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        tr = budgets.tree(s)
        accts = budgets.account_ids(s, b, c.id)
        rows = list(s.scalars(select(Account).where(Account.id.in_(accts))))
        names = {a.id: a.name for a in rows}
        roles = {r.accountId: r for r in plan.roles(s, b, rows, today)}
        held = reserves.held_in(s, b, accts, tr, budgets.lines(s, b), reserves.moves(s, b), m)
        out = []
        for h in held:
            frm = roles.get(h.accountId)
            moved_from = frm.movedFromId if frm else None
            out.append(
                HeldInOut(
                    accountId=h.accountId,
                    accountName=names.get(h.accountId, "an account not shared"),
                    movedFromId=moved_from,
                    movedFromName=names.get(moved_from) if moved_from else None,
                    reserves=[
                        ReserveHeld(categoryId=k, label=tr.label(k), balance=v)
                        for k, v in h.reserves
                    ],
                    total=h.total,
                    movedIn=h.movedIn,
                    given=h.given,
                    balance=h.balance,
                    toMove=h.toMove,
                    withdrawals=h.withdrawals,
                    limit=h.limit,
                    overLimit=h.toMove < 0 and h.limit is not None and h.withdrawals + 1 > h.limit,
                    unassigned=[LandedOut(**x.__dict__) for x in h.unassigned],
                )
            )
        cards = []
        for a in rows:
            if a.type != "credit-card":
                continue
            r = roles.get(a.id)
            got = _card_month(s, a, m)
            cards.append(
                CardOut(
                    accountId=a.id,
                    accountName=a.name,
                    paidFromId=r.paidFromId if r else None,
                    paidFromName=names.get(r.paidFromId) if r and r.paidFromId else None,
                    **got,
                )
            )
        return WhereView(month=m, sayToMove=True, heldIn=out, cards=cards)


def _card_month(s, a: Account, month: dt.date) -> dict:
    """What a card owes at the month's end, what was paid in the month, and its interest and
    fees."""
    from ..store.repos import ledger

    end = budgets.month_end(month)
    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId == a.id,
            Transaction.deleted == false(),
            Transaction.date >= month,
            Transaction.date <= end,
        )
    ).all()
    fees = {c.id for c in s.scalars(select(Category).where(Category.builtIn == "fees"))}
    return {
        "owed": -ledger.load(s, a).balance(end),
        "paid": sum((t.amount for t in txns if t.amount > 0 and t.transferId), Decimal(0)),
        "charges": -sum(
            (
                t.amount
                for t in txns
                if t.amount < 0 and (t.kind in ("interest", "fee") or t.categoryId in fees)
            ),
            Decimal(0),
        ),
    }


@router.post("/budgets/{budget_id}/landed", response_model=WhereView)
def give_landed(
    budget_id: str,
    body: GiveIn,
    request: Request,
    c: Caller = Depends(caller),
    month: str | None = None,
):
    """Landed money given to a reserve, spread among those held where it landed by balance,
    or kept as the account's own (S7.10.5): moves the budget keeps, recorded in Activity."""
    from ..budgets import reserves

    with server(request).db.tx() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        t = s.get(Transaction, body.transactionId)
        accts = budgets.account_ids(s, b, c.id)
        if t is None or t.deleted or t.accountId not in accts or t.amount <= 0:
            raise refuse("transactionId", "not-found", "No such money landed.")
        m = budgets.month_of(t.date)
        tr = budgets.tree(s)
        held = {
            h.accountId: h
            for h in reserves.held_in(s, b, accts, tr, budgets.lines(s, b), reserves.moves(s, b), m)
        }
        h = held.get(t.accountId)
        free = next((x.free for x in h.unassigned if x.transactionId == t.id), None) if h else None
        if free is None or body.amount <= 0 or body.amount > free:
            raise refuse("amount", "amount-invalid", "No more than is unassigned of it.")
        if body.to == "own":
            parts = [(None, body.amount)]
        elif body.to == "spread":
            weights = [(k, max(v, Decimal(0))) for k, v in h.reserves]
            total = sum((w for _, w in weights), Decimal(0)) or Decimal(len(weights))
            parts, left = [], body.amount
            for i, (k, w) in enumerate(weights):
                share = (
                    left
                    if i == len(weights) - 1
                    else (body.amount * (w if total else 1) / total).quantize(Decimal("0.01"))
                )
                parts.append((k, share))
                left -= share
        elif body.to in {k for k, _ in h.reserves}:
            parts = [(body.to, body.amount)]
        else:
            raise refuse("to", "reserve-unknown", "One of the reserves held there.")
        for cat, amount in parts:
            if amount > 0:
                s.add(
                    BudgetMove(
                        id=ids.new_id("BdgMv"),
                        budgetId=b.id,
                        month=m,
                        toCategoryId=cat,
                        amount=amount,
                        transactionId=t.id,
                        createdById=c.id,
                    )
                )
        activity.record(
            s,
            "budget.landed",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
        s.flush()
    return where(budget_id, request, c, month or m.isoformat()[:7])


@router.get("/budgets/{budget_id}/estimate", response_model=list[Proposal])
def estimate(
    budget_id: str,
    request: Request,
    c: Caller = Depends(caller),
    months: int = Query(6, ge=3, le=12),
):
    """A plan from the last 3, 6 or 12 complete months (S7.1.5): nothing is saved."""
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        tr = budgets.tree(s)
        return [
            Proposal(
                categoryId=x.categoryId,
                label=tr.label(x.categoryId),
                amount=x.amount,
                cadence=x.cadence,
                source=x.source,
                detail=x.detail,
                target=x.target,
            )
            for x in plan.estimate(s, b, budgets.account_ids(s, b, c.id), tr, months, clock.today())
        ]


@router.get("/budgets/{budget_id}/cash-flow", response_model=CashFlow)
def budget_cash_flow(
    budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None
):
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        m = _month(month)
        f = budgets.cash_flow(s, b, m, c.id)
        return CashFlow(
            month=m,
            sources=[Flow(name=n, amount=a) for n, a in f["sources"]],
            uses=[Flow(name=n, amount=a) for n, a in f["uses"]],
            income=f["income"],
            spending=f["spending"],
        )


@router.get("/budgets/{budget_id}/trends", response_model=list[TrendPoint])
def budget_trends(
    budget_id: str,
    request: Request,
    c: Caller = Depends(caller),
    month: str | None = None,
    category: str | None = None,
    months: int = Query(12, ge=3, le=36),
):
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        return [
            TrendPoint(month=m, planned=p, actual=a)
            for m, p, a in budgets.trends(s, b, _month(month), category, months, c.id)
        ]


@router.get("/budgets/{budget_id}/recurring", response_model=list[RecurringRow])
def budget_recurring(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """Found in the last 15 months of the budget's accounts each time it is asked."""
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        accts = budgets.account_ids(s, b, c.id)
        today = clock.today()
        txns = s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(accts),
                Transaction.deleted == false(),
                Transaction.date >= today - dt.timedelta(days=460),
            )
        ).all()
        # An entry names its account only to someone the account is shared with too; the owner's
        # other accounts are *an account not shared* (S7.1.1, S11.3.1).
        reach = access.reach(s, c.id) if c.id != b.ownerId else None
        names = {
            a.id: a.name
            for a in s.scalars(select(Account).where(Account.id.in_(accts)))
            if reach is None or access.account_level(s, c.id, a, reach) is not None
        }
        return [
            RecurringRow(
                payee=x.payee,
                accountId=x.accountId if x.accountId in names else None,
                accountName=names.get(x.accountId, "an account not shared"),
                every=x.every,
                last=x.last,
                next=x.next,
                usual=x.usual,
                lastAmount=x.lastAmount,
                count=x.count,
                missed=x.missed,
                changed=x.changed,
            )
            for x in recurring.detect(txns, today)
        ]
