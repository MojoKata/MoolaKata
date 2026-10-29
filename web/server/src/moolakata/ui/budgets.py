"""Budgets (requirements S7.1–S7.5): a budget's month, its plan, cash flow, trends and the
recurring transactions in its accounts. A budget is owned by a user and shared like an account;
a household budget is one shared with a group at write (S10.3)."""

import datetime as dt
from decimal import Decimal
from typing import Literal

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
from . import save
from .conventions import (
    ExactRoute,
    IdOf,
    Model,
    Money,
    stale,
)
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


class TransferIn(Model):
    """A transfer in from the budget's accounts this month: the reserves' unless kept."""

    transactionId: str
    date: dt.date
    payee: str | None
    amount: Money
    kept: bool  # kept as the account's own: not counted for the reserves


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
    transfers: list[TransferIn]


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


class Overspent(Model):
    categoryId: str
    label: str
    over: Money


class ToMoveOut(Model):
    accountName: str
    toMove: Money  # + to move there, − back


class ReviewedOut(Model):
    month: dt.date
    at: dt.datetime
    byName: str | None
    changes: list[str]  # what changed since it was reviewed, none when nothing did


class ReviewView(Model):
    """The month's review (S7.14): its loose ends, each with its action, and whether it was
    reviewed and has changed since."""

    month: dt.date
    overspent: list[Overspent]
    toMove: list[ToMoveOut]
    uncategorised: int
    moved: int  # transfers that left or entered the budget, to sort
    toBudget: Money | None  # left in an envelope budget's To Budget
    reviewed: ReviewedOut | None
    history: list[ReviewedOut]  # the months before, newest first


class ReviewIn(Model):
    month: dt.date


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
    cardId: str | None = None  # an envelope budget's card payment line (S7.13.2)
    amount: Money
    note: str | None = None


class InBudget(Model):
    """A budget counting a transaction, what it counts as there, and its leave-out (S7.3.5)."""

    budgetId: str
    name: str
    countsAs: str | None  # the category's path, or none when uncategorised
    leftOut: bool
    canWrite: bool


class CardLine(Model):
    """A card's payment line in an envelope budget (S7.13.2)."""

    accountId: str
    name: str
    setAside: Money
    owed: Money
    paid: Money
    notBacked: Money


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
    toBudget: Money | None  # an envelope budget's (S7.13.1)
    assigned: Money | None
    assignedByMoves: Money | None
    cards: list[CardLine]
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


def _make_budget(s, c: Caller, body, budget_id: str) -> Budget:
    if body.method not in ("tracking", "envelope"):
        raise Problem(
            422,
            "method-invalid",
            "Tracking or envelope.",
            [FieldError("method", "method-invalid", "Tracking or envelope.")],
        )
    _raise(_check(s, c.id, body))
    b = Budget(
        id=budget_id,
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
    return b


@router.post("/budgets", response_model=BudgetRow, status_code=201)
def create_budget(body: NewBudget, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        b = _make_budget(s, c, body, ids.new_id("Bdgt"))
        s.flush()
        out = shape(s, b, "owner", c.id)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/budgets/{b.id}"},
    )


def _change_budget(s, c: Caller, b: Budget, lvl: str, body, sent: set[str]) -> None:
    """The fields `sent`: its name, accounts (its owner's choice), options and roles."""
    _raise(_check(s, b.ownerId, body))
    fields = []
    if "name" in sent and body.name.strip() != b.name:
        b.name = body.name.strip()
        fields.append("name")
    if "accountIds" in sent:
        if lvl != "owner":
            raise Problem(403, "owner-only", "Only the owner chooses the accounts.")
        _set_accounts(s, b, body.accountIds, c.id)
        b.updatedAt = clock.now()
        fields.append("accounts")
    for option in ("reserves", "moves"):
        value = getattr(body, option)
        if option in sent and value != getattr(b, option):
            if option == "moves" and b.method == "envelope" and not value:
                raise refuse("moves", "moves-needed", "An envelope budget always has moves.")
            setattr(b, option, value)
            fields.append(option)
    if "roles" in sent:
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
            toBudget=m.toBudget,
            assigned=m.assigned,
            assignedByMoves=m.assignedByMoves,
            cards=[
                CardLine(
                    accountId=x.accountId,
                    name=x.name,
                    setAside=x.setAside,
                    owed=x.owed,
                    paid=x.paid,
                    notBacked=x.notBacked,
                )
                for x in m.cards
            ],
            plannedSpending=m.plannedSpending,
            uncategorised=m.uncategorised,
            daysLeft=m.daysLeft,
            canWrite=lvl in ("owner", "write"),
            version=b.version,
        )


def _line_errors(s, b: Budget, ln, cats: dict, elsewhere: set, at: str = "") -> list[FieldError]:
    """What a plan line breaks (S7.1.2, S7.10): its category, amount, cadence, overspending,
    target, held-in account and projection. `at` prefixes each field's name."""
    errors = []
    if ln.categoryId not in cats or cats[ln.categoryId].kind == "transfer":
        errors.append(FieldError(f"{at}categoryId", "category-unknown", "Choose a category."))
    if ln.amount < 0:
        errors.append(FieldError(f"{at}amount", "amount-negative", "Plan zero or more."))
    if ln.cadence not in ("month", "year"):
        errors.append(FieldError(f"{at}cadence", "cadence-invalid", "Monthly or yearly."))
    if ln.categoryId in elsewhere:
        errors.append(
            FieldError(
                f"{at}categoryId", "planned-elsewhere", "Planned by your gift or giving plans."
            )
        )
    if ln.overspend not in ("carry", "next"):
        errors.append(
            FieldError(
                f"{at}overspend",
                "overspend-invalid",
                "Carried negative, or from next month's To Budget.",
            )
        )
    if ln.target is not None and (not b.reserves or ln.cadence != "month" or ln.target <= 0):
        errors.append(
            FieldError(
                f"{at}target",
                "target-invalid",
                "A monthly line in a budget with reserves, aiming above zero.",
            )
        )
    if ln.heldInId and ln.heldInId not in budgets.account_ids(s, b):
        errors.append(
            FieldError(f"{at}heldInId", "account-unknown", "One of the budget's accounts.")
        )
    if ln.projectionId and not _projection_ok(s, b, ln.projectionId):
        errors.append(FieldError(f"{at}projectionId", "projection-unknown", "Choose a projection."))
    return errors


def _reserve_held(s, b: Budget, cat_id: str, month: dt.date) -> Decimal:
    """What a category's reserve holds at the start of a month: kept no longer once its line
    or its target goes, so that is asked first (S7.10.3)."""
    from ..budgets import reserves

    every = budgets.lines(s, b)
    moved = reserves.net_moves(reserves.moves(s, b))
    r = reserves.reserve(
        s,
        budgets.tree(s),
        budgets.account_ids(s, b),
        every,
        moved,
        cat_id,
        budgets.add_months(month, -1),
    )
    return r.balance if r is not None else Decimal(0)


class LineOut(Model):
    """A plan line as it is stored (S7.1.2), which a dialog's draft starts from (S12.15.1)."""

    id: str
    version: int
    budgetId: str
    categoryId: str
    fromMonth: dt.date
    amount: Money
    cadence: str
    rollover: bool
    overspend: str
    projectionId: str | None
    target: Money | None
    heldInId: str | None


class PlanOut(Model):
    """The lines in force in a month, each as stored; a line of 0 is none."""

    month: dt.date
    lines: list[LineOut]


def _line_out(ln: BudgetLine) -> LineOut:
    return LineOut(
        id=ln.id,
        version=ln.version,
        budgetId=ln.budgetId,
        categoryId=ln.categoryId,
        fromMonth=ln.fromMonth,
        amount=ln.amount,
        cadence=ln.cadence,
        rollover=ln.rollover,
        overspend=ln.overspend,
        projectionId=ln.projectionId,
        target=ln.target,
        heldInId=ln.heldInId,
    )


@router.get("/budgets/{budget_id}/plan", response_model=PlanOut)
def get_plan(
    budget_id: str,
    request: Request,
    c: Caller = Depends(caller),
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
):
    """The plan as it holds in a month, line by line as stored: what the plan dialog edits
    (S7.1.2), never the month's figures, which add carried amounts and moves to it."""
    m = dt.date.fromisoformat(month + "-01")
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id, "read")
        lines = budgets.in_force(budgets.lines(s, b), m)
        tr = budgets.tree(s)
        ordered = sorted(lines.values(), key=lambda ln: tr.label(ln.categoryId))
        return PlanOut(month=m, lines=[_line_out(ln) for ln in ordered])


# ---------- plan lines in a dialog's draft (S12.15, S13.8.11) ----------


class LineIn(Model):
    """A plan line as a draft saves it: the line holds from `fromMonth` on, earlier months
    keeping the plan they had (S7.1.2)."""

    budgetId: IdOf("Bdgt")  # type: ignore[valid-type]
    categoryId: IdOf("Cat")  # type: ignore[valid-type]
    fromMonth: dt.date
    amount: Money
    cadence: Literal["month", "year"] = "month"
    rollover: bool = False
    overspend: Literal["carry", "next"] = "carry"
    projectionId: IdOf("Prjct") | None = None  # type: ignore[valid-type]
    target: Money | None = None
    heldInId: IdOf("Acct") | None = None  # type: ignore[valid-type]


def _line_checked(ctx, body: LineIn) -> tuple[Budget, dt.date]:
    """The budget, written by the caller, and the month, after the line's own checks."""
    b, _ = access.budget(ctx.s, ctx.caller.id, body.budgetId, "write")
    month = budgets.month_of(body.fromMonth)
    cats = {x.id: x for x in ctx.s.scalars(select(Category).where(Category.deleted == false()))}
    elsewhere = plan.planned_elsewhere(ctx.s, b, budgets.tree(ctx.s), month.year)
    _raise(_line_errors(ctx.s, b, body, cats, elsewhere))
    return b, month


LINE_FIELDS = ("amount", "cadence", "rollover", "overspend", "projectionId", "target", "heldInId")


def _values(body: LineIn) -> dict:
    return {
        "amount": body.amount,
        "cadence": body.cadence,
        "rollover": body.rollover or body.target is not None,  # a reserve always rolls over
        "overspend": body.overspend,
        "projectionId": body.projectionId,
        "target": body.target,
        "heldInId": body.heldInId if body.target is not None else None,
    }


def _planned(ctx, b: Budget) -> None:
    """The budget changed, and Activity says so once for the whole save."""
    b.updatedAt = clock.now()
    srv, by = server(ctx.request), ctx.caller.id

    def record() -> None:
        with srv.db.tx() as s:
            activity.record(
                s,
                "budget.planned",
                actor=by,
                subject_kind="budget",
                subject_id=b.id,
                owner=b.ownerId,
            )

    ctx.after(f"budget.planned:{b.id}", record)


def _line_create(ctx, record_id: str, body: LineIn) -> None:
    """A category planned from a month: not one in force then, which would be planned twice.
    A line of 0 from the same month (the category taken out then) gives way to it."""
    b, month = _line_checked(ctx, body)
    every = budgets.lines(ctx.s, b)
    if body.categoryId in budgets.in_force(every, month):
        raise refuse("categoryId", "category-twice", "Each category once.")
    for ln in every:
        if ln.categoryId == body.categoryId and ln.fromMonth == month:
            ln.mark_deleted(ctx.caller.id)
    ctx.s.flush()
    ctx.s.add(
        BudgetLine(
            id=record_id,
            budgetId=b.id,
            categoryId=body.categoryId,
            fromMonth=month,
            **_values(body),
        )
    )
    _planned(ctx, b)


def _line_editable(ctx, record_id: str) -> BudgetLine:
    ln = ctx.s.get(BudgetLine, record_id)
    if ln is None or ln.deleted:
        raise Problem(404, "not-found", "Not found")
    access.budget(ctx.s, ctx.caller.id, ln.budgetId, "write")
    return ln


def _line_current(ctx, ln: BudgetLine) -> dict:
    return {
        "budgetId": ln.budgetId,
        "categoryId": ln.categoryId,
        "fromMonth": ln.fromMonth.isoformat(),
        **{f: getattr(ln, f) for f in LINE_FIELDS},
    }


def _line_update(ctx, ln: BudgetLine, body: LineIn) -> None:
    """A line changed from a month on (`fromMonth`): in place when it already starts then, else
    a line of its own from then, the earlier months keeping the old one. A reserve that stops
    being kept while it holds money is asked first (S7.10.3); a line set to 0 is taken out of
    the plan from that month."""
    if body.budgetId != ln.budgetId or body.categoryId != ln.categoryId:
        raise refuse("categoryId", "line-fixed", "A line keeps its budget and category.")
    b, month = _line_checked(ctx, body)
    if month < ln.fromMonth:
        raise refuse("fromMonth", "month-earlier", "A change holds from its own month on.")
    values = _values(body)
    stops = ln.target is not None and (values["target"] is None or values["amount"] == 0)
    if stops:
        held = _reserve_held(ctx.s, b, ln.categoryId, month)
        if held:
            label = budgets.tree(ctx.s).label(ln.categoryId)
            ctx.ask("reserve-balance", f"{label} holds {held:,.2f}: it stops being kept.")
    if month == ln.fromMonth:
        for f, v in values.items():
            setattr(ln, f, v)
    else:
        later = next(
            (
                x
                for x in budgets.lines(ctx.s, b)
                if x.categoryId == ln.categoryId and x.fromMonth == month
            ),
            None,
        )
        if later is not None:
            # A line from that month made since this one was read (by another change, or a
            # taking out): this one no longer holds then, so the change is stale (S13.8.6).
            raise stale(_line_out(later))
        else:
            ctx.s.add(
                BudgetLine(
                    id=ids.new_id("BdgLn"),
                    budgetId=b.id,
                    categoryId=ln.categoryId,
                    fromMonth=month,
                    **values,
                )
            )
    _planned(ctx, b)


def _line_delete(ctx, ln: BudgetLine) -> None:
    raise refuse(
        None,
        "plan-line-delete",
        "A plan line is taken out by setting it to nothing from a month on.",
    )


def _line_read(ctx, record_id: str) -> LineOut:
    return _line_out(ctx.s.get(BudgetLine, record_id))


save.register(
    save.Kind(
        prefix="BdgLn",
        entity=BudgetLine,
        fields=LineIn,
        create=_line_create,
        editable=_line_editable,
        current=_line_current,
        update=_line_update,
        delete=_line_delete,
        read=_line_read,
    )
)


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

    cards = {a.id: a.name for a in s.scalars(select(Account).where(Account.type == "credit-card"))}

    def label(cat_id: str | None, landed: bool, side: str, card: str | None = None) -> str:
        if cat_id and cat_id in tr.by_id:
            return tr.label(cat_id)
        if card and side == "to":
            return f"{cards.get(card, 'a card')}'s payment"
        if landed:
            return "money landed" if side == "from" else "the account's own"
        return "To Budget"

    return [
        MoveOut(
            id=m.id,
            fromCategoryId=m.fromCategoryId,
            fromLabel=label(m.fromCategoryId, bool(m.transactionId), "from"),
            toCategoryId=m.toCategoryId,
            toLabel=label(m.toCategoryId, bool(m.transactionId), "to", m.cardId),
            amount=m.amount,
            note=m.note,
            byName=users.get(m.createdById),
            createdAt=m.createdAt,
            landed=bool(m.transactionId),
            version=m.version,
        )
        for m in rows
    ]


def _move(s, c: Caller, b: Budget, body: MoveIn, move_id: str) -> BudgetMove:
    """An amount put from one category, a reserve among them, to another for one month; in an
    envelope budget, from or to To Budget (S7.11). Made by hand, recorded in Activity."""
    month = budgets.month_of(body.month)
    if not b.moves:
        raise refuse("moves", "moves-off", "Turn on moves in the budget's settings.")
    cats = {x.id: x for x in s.scalars(select(Category).where(Category.deleted == false()))}
    for f in ("fromCategoryId", "toCategoryId"):
        v = getattr(body, f)
        if v is not None and (v not in cats or cats[v].kind == "transfer"):
            raise refuse(f, "category-unknown", "Choose a category.")
    if body.cardId is not None:
        card = s.get(Account, body.cardId)
        if (
            b.method != "envelope"
            or card is None
            or card.type != "credit-card"
            or card.id not in budgets.account_ids(s, b)
            or body.toCategoryId is not None
        ):
            raise refuse("cardId", "card-unknown", "One of an envelope budget's cards.")
    elif body.fromCategoryId == body.toCategoryId or (
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
        id=move_id,
        budgetId=b.id,
        month=month,
        fromCategoryId=body.fromCategoryId,
        toCategoryId=body.toCategoryId,
        cardId=body.cardId,
        amount=body.amount,
        note=(body.note or "").strip() or None,
        createdById=c.id,
    )
    s.add(mv)
    b.updatedAt = clock.now()
    activity.record(
        s, "budget.moved", actor=c.id, subject_kind="budget", subject_id=b.id, owner=b.ownerId
    )
    return mv


@router.post("/budgets/{budget_id}/moves", response_model=MoveOut, status_code=201)
def make_move(budget_id: str, body: MoveIn, request: Request, c: Caller = Depends(caller)):
    """A move made (S7.11)."""
    with server(request).db.tx() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        mv = _move(s, c, b, body, ids.new_id("BdgMv"))
        s.flush()
        month = mv.month
        (out,) = [x for x in _moves_out(s, b, month) if x.id == mv.id]
    # Read with its month (S13.8.4).
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/budgets/{b.id}/month?month={month.isoformat()[:7]}"},
    )


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
                    transfers=[
                        TransferIn(
                            transactionId=x.transactionId,
                            date=x.date,
                            payee=x.payee,
                            amount=x.amount,
                            kept=kept,
                        )
                        for x, kept in h.transfers
                    ],
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


def _give_landed(s, c: Caller, b: Budget, body, move_id: str) -> BudgetMove:
    """Landed money given to a reserve held where it landed, or kept as the account's own
    (S7.10.5): a move the budget keeps, of no more than is unassigned of it, in its month."""
    from ..budgets import reserves

    t = s.get(Transaction, body.transactionId)
    accts = budgets.account_ids(s, b, c.id)
    if t is None or t.deleted or t.accountId not in accts or t.amount <= 0:
        raise refuse("transactionId", "not-found", "No such money landed.")
    if body.fromCategoryId is not None or body.cardId is not None:
        raise refuse("fromCategoryId", "move-invalid", "Landed money comes from where it landed.")
    m = budgets.month_of(t.date)
    tr = budgets.tree(s, b)
    held = {
        h.accountId: h
        for h in reserves.held_in(s, b, accts, tr, budgets.lines(s, b), reserves.moves(s, b), m)
    }
    h = held.get(t.accountId)
    own = body.toCategoryId is None
    free = next((x.free for x in h.unassigned if x.transactionId == t.id), None) if h else None
    if free is None and h and own:
        # A transfer in from the budget's accounts, kept as the account's own (S7.10.4).
        free = next(
            (x.free for x, kept in h.transfers if x.transactionId == t.id and not kept), None
        )
    if free is None or body.amount <= 0 or body.amount > free:
        raise refuse("amount", "amount-invalid", "No more than is unassigned of it.")
    if not own and body.toCategoryId not in {k for k, _ in h.reserves}:
        raise refuse("toCategoryId", "reserve-unknown", "One of the reserves held there.")
    mv = BudgetMove(
        id=move_id,
        budgetId=b.id,
        month=m,
        toCategoryId=body.toCategoryId,
        amount=body.amount,
        transactionId=t.id,
        createdById=c.id,
    )
    s.add(mv)
    s.flush()
    activity.record(
        s, "budget.landed", actor=c.id, subject_kind="budget", subject_id=b.id, owner=b.ownerId
    )
    return mv


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


def _figures(m) -> dict:
    """What a review keeps of a month, to flag a later change (S7.14)."""
    return {
        "rows": {r.categoryId: [str(r.planned), str(r.actual), r.label] for r in m.rows},
        "spent": str(m.spent),
        "income": str(m.income),
        "saved": str(m.saved),
        "toBudget": None if m.toBudget is None else str(m.toBudget),
    }


def _changes(then: dict, now: dict) -> list[str]:
    out = []
    for cat_id in sorted(set(then["rows"]) | set(now["rows"])):
        a, b = then["rows"].get(cat_id), now["rows"].get(cat_id)
        label = (b or a)[2]
        if a is None:
            out.append(f"{label}: planned since")
        elif b is None:
            out.append(f"{label}: no longer planned")
        elif a[1] != b[1]:
            out.append(f"{label}: spent {a[1]} then, {b[1]} now")
        elif a[0] != b[0]:
            out.append(f"{label}: planned {a[0]} then, {b[0]} now")
    for k, name in (("income", "Income"), ("saved", "Saved"), ("toBudget", "To Budget")):
        if then.get(k) != now.get(k) and not out:
            out.append(f"{name}: {then.get(k)} then, {now.get(k)} now")
    return out


def _reviewed(
    s, b: Budget, month: dt.date, viewer: str, figures: dict | None
) -> ReviewedOut | None:
    import json

    from ..store.entities.budgets import BudgetReview

    r = s.scalars(
        select(BudgetReview).where(
            BudgetReview.budgetId == b.id,
            BudgetReview.month == month,
            BudgetReview.deleted == false(),
        )
    ).first()
    if r is None:
        return None
    if figures is None:
        figures = _figures(budgets.month_view(s, b, month, clock.today(), viewer))
    who = s.get(User, r.reviewedById) if r.reviewedById else None
    return ReviewedOut(
        month=month,
        at=r.updatedAt,
        byName=who.displayName if who else None,
        changes=_changes(json.loads(r.figures), figures),
    )


@router.get("/budgets/{budget_id}/review", response_model=ReviewView)
def review(budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None):
    """The month before this one unless another is asked: what was overspent, what is to move,
    what is left in To Budget, and what waits to be sorted (S7.14)."""
    from ..budgets import reserves

    m = _month(month) if month else budgets.add_months(budgets.month_of(clock.today()), -1)
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        v = budgets.month_view(s, b, m, clock.today(), c.id)
        to_move = []
        if budgets.active_id(s, c.id) == b.id:
            accts = budgets.account_ids(s, b, c.id)
            names = {a.id: a.name for a in s.scalars(select(Account).where(Account.id.in_(accts)))}
            for h in reserves.held_in(
                s, b, accts, budgets.tree(s, b), budgets.lines(s, b), reserves.moves(s, b), m
            ):
                if h.toMove:
                    to_move.append(
                        ToMoveOut(accountName=names.get(h.accountId, ""), toMove=h.toMove)
                    )
        history = []
        for k in range(1, 7):
            earlier = budgets.add_months(m, -k)
            r = _reviewed(s, b, earlier, c.id, None)
            if r is not None:
                history.append(r)
        return ReviewView(
            month=m,
            overspent=[
                Overspent(categoryId=r.categoryId, label=r.label, over=-r.remaining)
                for r in v.rows
                if r.state == "over"
            ],
            toMove=to_move,
            uncategorised=v.uncategorised,
            moved=len(v.moved),
            toBudget=v.toBudget,
            reviewed=_reviewed(s, b, m, c.id, _figures(v)),
            history=history,
        )


@router.post("/budgets/{budget_id}/review", response_model=ReviewView)
def mark_reviewed(budget_id: str, body: ReviewIn, request: Request, c: Caller = Depends(caller)):
    """Mark reviewed (S7.14): who and when, and the month's figures then, so a later change is
    flagged until it is reviewed again. Months are never locked."""
    import json

    from ..store.entities.budgets import BudgetReview

    m = budgets.month_of(body.month)
    with server(request).db.tx() as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        figures = json.dumps(_figures(budgets.month_view(s, b, m, clock.today(), c.id)))
        r = s.scalars(
            select(BudgetReview).where(
                BudgetReview.budgetId == b.id,
                BudgetReview.month == m,
                BudgetReview.deleted == false(),
            )
        ).first()
        if r is None:
            s.add(
                BudgetReview(
                    id=ids.new_id("BdgRv"),
                    budgetId=b.id,
                    month=m,
                    figures=figures,
                    reviewedById=c.id,
                )
            )
        else:
            r.figures, r.reviewedById, r.updatedAt = figures, c.id, clock.now()
        activity.record(
            s,
            "budget.reviewed",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
        s.flush()
    return review(budget_id, request, c, m.isoformat()[:7])


@router.post("/budgets/{budget_id}/refresh", response_model=MonthView)
def refresh(
    budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None
):
    """Refresh: the budget's months worked out again at once (S7.3.10)."""
    from ..budgets import cache

    with server(request).db.read() as s:
        access.budget(s, c.id, budget_id)
    cache.forget(budget_id)
    return budget_month(budget_id, request, c, month)


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


# ---------- a budget and its moves in a dialog's draft (S12.15, S13.8.11) ----------


class BudgetRecord(Model):
    """A budget as a draft saves it (S7.1): its method chosen when it is made; its accounts
    its owner's choice; its roles a card's paying account or where reserves' money moves from,
    chosen (none: as the history says)."""

    name: str
    method: Literal["tracking", "envelope"] = "tracking"
    accountIds: list[IdOf("Acct")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    reserves: bool = False
    moves: bool = False
    roles: list[RoleIn] = Field(default_factory=list)


class MoveRecord(MoveIn):
    """A move as a draft makes it (S7.11): made, or deleted to undo it. With a transaction,
    landed money given to a reserve held where it landed, or to no category: kept as the
    account's own (S7.10.5); its month is the transaction's."""

    budgetId: IdOf("Bdgt")  # type: ignore[valid-type]
    transactionId: IdOf("Txn") | None = None  # type: ignore[valid-type]


def _budget_create(ctx, record_id: str, body: BudgetRecord) -> None:
    b = _make_budget(ctx.s, ctx.caller, body, record_id)
    if body.roles:
        ctx.s.flush()
        _set_roles(ctx.s, b, body.roles)


def _budget_current(ctx, b: Budget) -> dict:
    members = list(
        ctx.s.scalars(
            select(BudgetAccount).where(
                BudgetAccount.budgetId == b.id, BudgetAccount.deleted == false()
            )
        )
    )
    return {
        "name": b.name,
        "method": b.method,
        "accountIds": [m.accountId for m in members],
        "reserves": b.reserves,
        "moves": b.moves,
        "roles": [
            {"accountId": m.accountId, "paidFromId": m.paidFromId, "movedFromId": m.movedFromId}
            for m in members
        ],
    }


def _budget_update(ctx, b: Budget, body: BudgetRecord) -> None:
    current = _budget_current(ctx, b)
    if body.method != current["method"]:
        raise refuse("method", "method-fixed", "A budget keeps its method; copy it as a scenario.")
    sent = {f for f in ("name", "reserves", "moves") if getattr(body, f) != current[f]}
    if set(body.accountIds) != set(current["accountIds"]):
        sent.add("accountIds")
    have = {r["accountId"]: r for r in current["roles"]}
    if any(r.model_dump() != have.get(r.accountId) for r in body.roles):
        sent.add("roles")
    _, lvl = access.budget(ctx.s, ctx.caller.id, b.id, "write")
    _change_budget(ctx.s, ctx.caller, b, lvl, body, sent)


def _budget_delete(ctx, b: Budget) -> None:
    access.budget(ctx.s, ctx.caller.id, b.id, "owner")
    b.mark_deleted(ctx.caller.id)
    for u in ctx.s.scalars(select(User).where(User.activeBudgetId == b.id)):
        u.activeBudgetId = None
    activity.record(ctx.s, "budget.deleted", actor=ctx.caller.id, subject_kind="budget",
                    subject_id=b.id, owner=ctx.caller.id)  # fmt: skip


def _budget_read(ctx, record_id: str) -> BudgetRow:
    b, lvl = access.budget(ctx.s, ctx.caller.id, record_id)
    return shape(ctx.s, b, lvl, ctx.caller.id)


def _move_create(ctx, record_id: str, body: MoveRecord) -> None:
    b, _ = access.budget(ctx.s, ctx.caller.id, body.budgetId, "write")
    if body.transactionId:
        _give_landed(ctx.s, ctx.caller, b, body, record_id)
    else:
        _move(ctx.s, ctx.caller, b, body, record_id)


def _move_editable(ctx, record_id: str) -> BudgetMove:
    mv = ctx.s.get(BudgetMove, record_id)
    if mv is None or mv.deleted:
        raise Problem(404, "not-found", "No such move.")
    access.budget(ctx.s, ctx.caller.id, mv.budgetId, "write")
    return mv


def _move_update(ctx, mv: BudgetMove, body: MoveRecord) -> None:
    raise refuse(None, "move-fixed", "A move isn't changed: delete it, and move again.")


def _move_delete(ctx, mv: BudgetMove) -> None:
    """Deleting a move undoes it."""
    b = ctx.s.get(Budget, mv.budgetId)
    mv.mark_deleted(ctx.caller.id)
    activity.record(ctx.s, "budget.move-deleted", actor=ctx.caller.id, subject_kind="budget",
                    subject_id=b.id, owner=b.ownerId)  # fmt: skip


def _move_read(ctx, record_id: str) -> MoveOut:
    mv = ctx.s.get(BudgetMove, record_id)
    b = ctx.s.get(Budget, mv.budgetId)
    return next(x for x in _moves_out(ctx.s, b, mv.month) if x.id == mv.id)


save.register(
    save.Kind(
        prefix="Bdgt",
        entity=Budget,
        fields=BudgetRecord,
        create=_budget_create,
        editable=lambda ctx, record_id: access.budget(ctx.s, ctx.caller.id, record_id, "write")[0],
        current=_budget_current,
        update=_budget_update,
        delete=_budget_delete,
        read=_budget_read,
    )
)
save.register(
    save.Kind(
        prefix="BdgMv",
        entity=BudgetMove,
        fields=MoveRecord,
        create=_move_create,
        editable=_move_editable,
        current=lambda ctx, mv: {
            "budgetId": mv.budgetId,
            "month": mv.month,
            "fromCategoryId": mv.fromCategoryId,
            "toCategoryId": mv.toCategoryId,
            "cardId": mv.cardId,
            "amount": mv.amount,
            "note": mv.note,
        },
        update=_move_update,
        delete=_move_delete,
        read=_move_read,
    )
)
