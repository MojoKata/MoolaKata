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
    active: bool  # the one the caller follows; the others are scenarios (S7.12)
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


class CopyIn(Model):
    name: str
    method: str  # tracking or envelope
    withMoves: bool = False  # this month's moves come along


class CompareRow(Model):
    categoryId: str
    label: str
    available: Money | None  # in the active budget; none where it doesn't plan the category
    spent: Money | None
    otherAvailable: Money | None  # in the scenario
    otherSpent: Money | None


class CompareView(Model):
    """The active budget and one scenario side by side (S7.12.3)."""

    budgetId: str
    otherId: str
    first: dt.date
    last: dt.date
    rows: list[CompareRow]
    toBudget: Money | None  # the active budget's, when an envelope budget
    otherToBudget: Money | None


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


class MoveOut(Model):
    """An amount put from one category to another for the month (S7.11)."""

    id: str
    fromCategoryId: str | None  # none: To Budget, or landed money
    fromLabel: str
    toCategoryId: str | None
    toLabel: str
    amount: Money
    note: str | None
    byName: str | None
    createdAt: dt.datetime
    landed: bool  # landed money given (S7.10.5), deleted from Where the money is too
    version: int


class MoveIn(Model):
    month: dt.date
    fromCategoryId: str | None = None  # none: To Budget, in an envelope budget
    toCategoryId: str | None = None
    amount: Money
    note: str | None = None


class InBudget(Model):
    """A budget counting a transaction, what it counts as there, and its leave-out (S7.3.5)."""

    budgetId: str
    name: str
    countsAs: str | None  # the category's path, or none when uncategorised
    leftOut: bool
    canWrite: bool


class LeaveOutIn(Model):
    leftOut: bool


class MonthView(Model):
    month: dt.date
    rows: list[MonthRow]
    unplanned: list[Unplanned]
    income: Money
    expectedIncome: Money
    spent: Money
    saved: Money
    moved: list[MovedRow]
    moves: list[MoveOut]
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
        active=viewer is not None and budgets.active_id(s, viewer) == b.id,
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
        # A user's first budget is the one they follow (S7.12.1).
        if budgets.active_id(s, c.id) is None:
            s.get(User, c.id).activeBudgetId = b.id
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
        for u in s.scalars(select(User).where(User.activeBudgetId == b.id)):
            u.activeBudgetId = None
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
            moves=_moves_out(s, b, m.month),
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


def _moves_out(s, b: Budget, month: dt.date) -> list[MoveOut]:
    tr = budgets.tree(s)
    rows = s.scalars(
        select(BudgetMove)
        .where(
            BudgetMove.budgetId == b.id,
            BudgetMove.month == month,
            BudgetMove.deleted == false(),
        )
        .order_by(BudgetMove.createdAt)
    ).all()
    users = {u.id: u.displayName for u in s.scalars(select(User))}

    def label(cat_id: str | None, landed: bool, side: str) -> str:
        if cat_id and cat_id in tr.by_id:
            return tr.label(cat_id)
        if landed:
            return "money landed" if side == "from" else "the account's own"
        return "To Budget"

    return [
        MoveOut(
            id=m.id,
            fromCategoryId=m.fromCategoryId,
            fromLabel=label(m.fromCategoryId, bool(m.transactionId), "from"),
            toCategoryId=m.toCategoryId,
            toLabel=label(m.toCategoryId, bool(m.transactionId), "to"),
            amount=m.amount,
            note=m.note,
            byName=users.get(m.createdById),
            createdAt=m.createdAt,
            landed=bool(m.transactionId),
            version=m.version,
        )
        for m in rows
    ]


@router.post("/budgets/{budget_id}/moves", response_model=MoveOut, status_code=201)
def make_move(budget_id: str, body: MoveIn, request: Request, c: Caller = Depends(caller)):
    """An amount put from one category, a reserve among them, to another for one month; in an
    envelope budget, from or to To Budget (S7.11). Made by hand, recorded in Activity."""
    month = budgets.month_of(body.month)
    with server(request).db.tx() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        if not b.moves:
            raise refuse("moves", "moves-off", "Turn on moves in the budget's settings.")
        cats = {x.id: x for x in s.scalars(select(Category).where(Category.deleted == false()))}
        for f in ("fromCategoryId", "toCategoryId"):
            v = getattr(body, f)
            if v is not None and (v not in cats or cats[v].kind == "transfer"):
                raise refuse(f, "category-unknown", "Choose a category.")
        if body.fromCategoryId == body.toCategoryId or (
            b.method != "envelope" and (body.fromCategoryId is None or body.toCategoryId is None)
        ):
            raise refuse(
                "toCategoryId",
                "move-invalid",
                "From one category to another; To Budget only in an envelope budget.",
            )
        if body.amount <= 0:
            raise refuse("amount", "amount-invalid", "More than nothing.")
        if body.note is not None and len(body.note) > 200:
            raise refuse("note", "note-too-long", "At most 200 characters.")
        mv = BudgetMove(
            id=ids.new_id("BdgMv"),
            budgetId=b.id,
            month=month,
            fromCategoryId=body.fromCategoryId,
            toCategoryId=body.toCategoryId,
            amount=body.amount,
            note=(body.note or "").strip() or None,
            createdById=c.id,
        )
        s.add(mv)
        b.updatedAt = clock.now()
        activity.record(
            s, "budget.moved", actor=c.id, subject_kind="budget", subject_id=b.id, owner=b.ownerId
        )
        s.flush()
        (out,) = [x for x in _moves_out(s, b, month) if x.id == mv.id]
    # Read with its month (S13.8.4).
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/budgets/{b.id}/month?month={month.isoformat()[:7]}"},
    )


@router.delete("/budgets/{budget_id}/moves/{move_id}", response_model=Deleted[None])
def delete_move(
    budget_id: str,
    move_id: str,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    """Deleting a move undoes it."""
    with server(request).db.tx() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        mv = s.get(BudgetMove, move_id)
        if mv is None or mv.deleted or mv.budgetId != b.id:
            raise Problem(404, "not-found", "No such move.")
        check(mv, version, lambda: None)
        mv.mark_deleted(c.id)
        activity.record(
            s,
            "budget.move-deleted",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
        s.flush()
        return Deleted[None](deleted=gone(mv))


@router.get("/transactions/{txn_id}/budgets", response_model=list[InBudget])
def in_budgets(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """The caller's budgets counting a transaction, what it counts as in each, and each one's
    leave-out (S7.3.5, S12.2.3). The category is the transaction's, the same in every budget."""
    from ..store.entities.accounts import Split
    from ..store.entities.budgets import BudgetLeaveOut

    with server(request).db.read() as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "No such transaction.")
        access.account(s, c.id, t.accountId)
        tr = budgets.tree(s)
        parts = s.scalars(
            select(Split).where(Split.transactionId == t.id, Split.deleted == false())
        ).all()
        cats = {p.categoryId for p in parts if p.categoryId} or (
            {t.categoryId} if t.categoryId else set()
        )
        counts_as = ", ".join(sorted(tr.label(x) for x in cats if x in tr.by_id)) or None
        out = []
        for b, lvl in access.visible_budgets(s, c.id):
            if t.accountId not in budgets.account_ids(s, b, c.id):
                continue
            left = s.get(BudgetLeaveOut, (b.id, t.id))
            out.append(
                InBudget(
                    budgetId=b.id,
                    name=b.name,
                    countsAs=counts_as,
                    leftOut=left is not None and not left.deleted,
                    canWrite=lvl in ("owner", "write"),
                )
            )
        return out


@router.put("/budgets/{budget_id}/leave-outs/{txn_id}", response_model=InBudget)
def leave_out(
    budget_id: str, txn_id: str, body: LeaveOutIn, request: Request, c: Caller = Depends(caller)
):
    """Leave a transaction out of this budget, or count it again (S7.3.5)."""
    from ..store.entities.budgets import BudgetLeaveOut

    with server(request).db.tx() as s:
        b, lvl = access.budget(s, c.id, budget_id, "write")
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted or t.accountId not in budgets.account_ids(s, b, c.id):
            raise Problem(404, "not-found", "No such transaction in this budget.")
        row = s.get(BudgetLeaveOut, (b.id, t.id))
        if body.leftOut and row is None:
            s.add(BudgetLeaveOut(budgetId=b.id, transactionId=t.id, createdAt=clock.now()))
        elif body.leftOut and row.deleted:
            row.restore()
        elif not body.leftOut and row is not None and not row.deleted:
            row.mark_deleted(c.id)
        activity.record(
            s,
            "budget.left-out" if body.leftOut else "budget.counted-again",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
        s.flush()
        tr = budgets.tree(s)
        return InBudget(
            budgetId=b.id,
            name=b.name,
            countsAs=tr.label(t.categoryId) if t.categoryId in tr.by_id else None,
            leftOut=body.leftOut,
            canWrite=lvl in ("owner", "write"),
        )


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
        tr = budgets.tree(s, b)
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
        # Only the budget the caller follows says what to move (S7.12.2).
        active = budgets.active_id(s, c.id) == b.id
        return WhereView(month=m, sayToMove=active, heldIn=out, cards=cards)


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
        tr = budgets.tree(s, b)
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


@router.post("/budgets/{budget_id}/active", response_model=BudgetRow)
def make_active(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """The budget the caller follows from now on; the one before becomes a scenario. Nothing
    is rewritten (S7.12.1)."""
    with server(request).db.tx() as s:
        b, lvl = access.budget(s, c.id, budget_id)
        s.get(User, c.id).activeBudgetId = b.id
        activity.record(
            s, "budget.activated", actor=c.id, subject_kind="budget", subject_id=b.id, owner=c.id
        )
        s.flush()
        return shape(s, b, lvl, c.id)


@router.post("/budgets/{budget_id}/copy", response_model=BudgetRow, status_code=201)
def copy_budget(budget_id: str, body: CopyIn, request: Request, c: Caller = Depends(caller)):
    """Copy as scenario (S7.12.4): the same accounts and plan from this month, in the method
    chosen, with this month's moves when asked. The copy is the caller's; the budget they
    follow doesn't change."""
    if body.method not in ("tracking", "envelope"):
        raise refuse("method", "method-invalid", "Tracking or envelope.")
    if not body.name.strip() or len(body.name) > 80:
        raise refuse("name", "name-invalid", "Enter a name of up to 80 characters.")
    month = budgets.month_of(clock.today())
    with server(request).db.tx() as s:
        src, _ = access.budget(s, c.id, budget_id)
        b = Budget(
            id=ids.new_id("Bdgt"),
            ownerId=c.id,
            name=body.name.strip(),
            method=body.method,
            reserves=src.reserves,
            moves=src.moves or body.method == "envelope",
            startMonth=month,
        )
        s.add(b)
        s.flush()
        mine = {a.id for a, _ in access.visible_accounts(s, c.id)}
        _set_accounts(s, b, [a for a in budgets.account_ids(s, src, c.id) if a in mine], c.id)
        for ln in budgets.in_force(budgets.lines(s, src), month).values():
            s.add(
                BudgetLine(
                    id=ids.new_id("BdgLn"),
                    budgetId=b.id,
                    categoryId=ln.categoryId,
                    fromMonth=month,
                    amount=ln.amount,
                    cadence=ln.cadence,
                    rollover=ln.rollover,
                    overspend=ln.overspend,
                    projectionId=ln.projectionId,
                    target=ln.target,
                    heldInId=ln.heldInId,
                )
            )
        if body.withMoves:
            for m in s.scalars(
                select(BudgetMove).where(
                    BudgetMove.budgetId == src.id,
                    BudgetMove.month == month,
                    BudgetMove.deleted == false(),
                )
            ):
                if b.method != "envelope" and not (m.fromCategoryId and m.toCategoryId):
                    continue  # To Budget is an envelope budget's alone
                s.add(
                    BudgetMove(
                        id=ids.new_id("BdgMv"),
                        budgetId=b.id,
                        month=month,
                        fromCategoryId=m.fromCategoryId,
                        toCategoryId=m.toCategoryId,
                        amount=m.amount,
                        note=m.note,
                        transactionId=m.transactionId,
                        createdById=c.id,
                    )
                )
        if budgets.active_id(s, c.id) is None:
            s.get(User, c.id).activeBudgetId = b.id
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


@router.get("/budgets/{budget_id}/compare", response_model=CompareView)
def compare(
    budget_id: str,
    request: Request,
    c: Caller = Depends(caller),
    other: str = Query(...),
    month: str | None = None,
    span: str = Query("month", pattern="^(month|year)$"),
):
    """Two budgets side by side, per category: what is available and spent, for the month or
    the year to it (S7.12.3)."""
    last = _month(month)
    first = last.replace(month=1) if span == "year" else last
    today = clock.today()
    with server(request).db.read() as s:
        a, _ = access.budget(s, c.id, budget_id)
        b, _ = access.budget(s, c.id, other)
        sums: dict[str, dict[str, list]] = {}
        labels: dict[str, str] = {}
        to_budget = {}
        for key, bud in (("a", a), ("b", b)):
            m = first
            while m <= last:
                v = budgets.month_view(s, bud, m, today, c.id)
                for r in v.rows:
                    if r.kind == "income" or (r.cadence == "year" and m != last):
                        continue
                    labels[r.categoryId] = r.label
                    got = sums.setdefault(r.categoryId, {}).setdefault(key, [Decimal(0)] * 2)
                    avail = r.balance + r.actual if r.target is not None else r.planned
                    got[0] += avail if r.cadence == "month" or m == last else 0
                    got[1] += r.actual if r.cadence == "month" or m == last else 0
                to_budget[key] = getattr(v, "toBudget", None)
                m = budgets.add_months(m, 1)
        rows = [
            CompareRow(
                categoryId=k,
                label=labels[k],
                available=v["a"][0] if "a" in v else None,
                spent=v["a"][1] if "a" in v else None,
                otherAvailable=v["b"][0] if "b" in v else None,
                otherSpent=v["b"][1] if "b" in v else None,
            )
            for k, v in sorted(sums.items(), key=lambda x: labels[x[0]])
        ]
        return CompareView(
            budgetId=a.id,
            otherId=b.id,
            first=first,
            last=last,
            rows=rows,
            toBudget=to_budget.get("a"),
            otherToBudget=to_budget.get("b"),
        )


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
        tr = budgets.tree(s, b)
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
