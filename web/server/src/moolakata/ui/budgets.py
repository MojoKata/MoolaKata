"""Budgets (requirements S7.1–S7.5): a budget's month, its plan, cash flow, trends and the
recurring transactions in its accounts. A budget is owned by a user and shared like an account;
a household budget is one shared with a group at write (S10.3)."""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import access, activity, budgets, clock, ids
from ..access import Perms
from ..budgets import plan, recurring
from ..errors import FieldError, Problem, refuse, refuse_all
from ..money import grouped
from ..store import scoping
from ..store.entities.accounts import Account, Category, Transaction
from ..store.entities.budgets import Budget, BudgetAccount, BudgetLine, BudgetMove
from ..store.entities.users import User
from . import save
from .conventions import (
    Access,
    ExactRoute,
    IdOf,
    Model,
    Money,
    stale,
)
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["budgets"])

# An account a viewer may not see, never named nor its id given (S7.1.1, S11.3.1).
NOT_SHARED = "an account not shared"


class RoleOut(Model):
    """Where an account's money comes from (S7.1.6), worked out unless chosen."""

    accountId: str
    paidFromId: str | None  # a card's paying account
    paidFromLearned: bool
    movedFromId: str | None  # where money for reserves held here moves from
    movedFromProposed: bool


class BudgetRow(Model):
    id: str
    name: str
    ownerId: str
    ownerName: str
    access: Access
    accountIds: list[str]
    sharedWith: int
    method: str  # tracking or envelope (S7.1.3)
    reserves: bool  # its options (S7.1.4)
    moves: bool
    startMonth: dt.date | None
    roles: list[RoleOut]
    active: bool  # the one the caller follows; the others are scenarios (S7.12)
    version: int


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
    putIn: Money
    unbacked: Money  # an envelope's card spending beyond what it held (S7.13.2)


class ReserveHeld(Model):
    categoryId: str
    label: str
    balance: Money


class LandedOut(Model):
    # No transaction id, date or payee: an account not shared with the viewer, its rows added
    # into one (S7.1.1).
    transactionId: str | None
    date: dt.date | None
    payee: str | None
    amount: Money
    free: Money


class TransferIn(Model):
    """A transfer in from the budget's accounts this month: the reserves' unless kept."""

    transactionId: str | None  # None, as date: an account not shared, as LandedOut
    date: dt.date | None
    payee: str | None
    amount: Money
    kept: bool  # kept as the account's own: not counted for the reserves


class BetweenOut(Model):
    fromId: str | None  # None for an account not shared with the viewer (S7.1.1)
    fromName: str
    toId: str | None
    toName: str
    amount: Money


class HeldInOut(Model):
    """An account reserves are held in, and what is to move there (S7.10.4)."""

    accountId: str | None  # None for an account not shared with the viewer (S7.1.1)
    accountName: str
    movedFromId: str | None
    movedFromName: str | None
    reserves: list[ReserveHeld]
    total: Money
    movedIn: Money
    reservesFlow: Money  # spending and refunds in reserves' categories paid here, signed
    given: Money
    balance: Money
    toMove: Money  # + to move here from moved from, − back to it
    # Moves straight between two accounts reserves are held in: one paid for a reserve the
    # other holds (S7.10.4).
    between: list[BetweenOut]
    withdrawals: int
    limit: int | None
    overLimit: bool  # a move back now would go past the withdrawals allowed
    unassigned: list[LandedOut]
    transfers: list[TransferIn]


class CardOut(Model):
    accountId: str | None  # None for an account not shared with the viewer (S7.1.1)
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
    fromName: str | None = None  # a move from another account reserves are held in


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
    category: it counts nowhere until sorted (S7.3.2). One in an account not shared with the
    viewer has no transaction id, date, payee or other account: that account's rows that left
    the budget are added into one, and those that entered it into another (S7.1.1)."""

    transactionId: str | None
    date: dt.date | None
    accountName: str
    # *an account not shared* for one the viewer can't see (S11.3.1)
    otherAccountName: str | None
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
    access: Access  # the budget's: leaving the transaction out is a change to it


class CardLine(Model):
    """A card's payment line in an envelope budget (S7.13.2)."""

    accountId: str | None  # None for an account not shared with the viewer (S7.1.1)
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
    # The Spent card (S7.3.12): the monthly spending lines' available, reserves included; what
    # they leave less the spending outside the plan and the envelopes' unbacked card spending;
    # that unbacked spending, named beside; and the month's spending against yearly lines,
    # compared with their year instead.
    available: Money
    left: Money
    unbacked: Money
    yearlySpent: Money
    uncategorised: int
    daysLeft: int
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
    """The accounts the budget counts this month."""
    return budgets.account_ids(s, b, viewer, clock.today())


def _names(s, viewer: str, account_ids) -> dict[str, str]:
    """The names of the accounts a viewer may see: their own and those shared with them, so a
    shared budget never names another account (S7.1.1, S11.3.1)."""
    wanted = {x for x in account_ids if x}
    if not wanted:
        return {}
    return {a.id: a.name for a, _ in access.accounts(s, viewer, Account.id.in_(wanted))}


def _withheld(rows, amounts: tuple[str, ...]) -> list:
    """A list's rows as `(key, row)`: one keyed None is the viewer's to see whole; those of an
    account not shared with them keep their amounts and lose their transaction id, date and
    payee, each key's added into one row standing where its first did, so the list's total is
    unchanged (S7.1.1)."""
    out, at = [], {}
    for key, row in rows:
        if key is None:
            out.append(row)
        elif key in at:
            got = out[at[key]]
            for f in amounts:
                setattr(got, f, getattr(got, f) + getattr(row, f))
        else:
            at[key] = len(out)
            out.append(row.model_copy(update={"transactionId": None, "date": None, "payee": None}))
    return out


@contextmanager
def _as_server(s, b: Budget) -> Iterator[tuple[Session, Budget]]:
    """The budget, once the caller's access to it is checked, in a session reading as the
    server: its figures count every account `members` gives the viewer, the owner's own among
    them, whoever may see them (S7.1.1). What names or ids an account is read in the viewer's
    own session (`_names`)."""
    with scoping.as_server(s, "a budget's figures, for one who reads it", False) as srv:
        yield srv, srv.get(Budget, b.id)


def shape(s, b: Budget, held: Perms, viewer: str | None = None) -> BudgetRow:
    owner = s.get(User, b.ownerId)
    shared = len(access.holders_of(s, Budget, b.id)) - 1 if held.shareable else 0
    accts = _accounts_of(s, b, viewer)
    rows = list(s.scalars(select(Account).where(Account.id.in_(accts))))
    roles = plan.roles(s, b, rows, clock.today())
    if viewer is not None:
        # A role chosen by the owner may name an account the viewer can't see (S7.1.1).
        seen = _names(s, viewer, {x for r in roles for x in (r.paidFromId, r.movedFromId)})
        for r in roles:
            r.paidFromId = r.paidFromId if r.paidFromId in seen else None
            r.movedFromId = r.movedFromId if r.movedFromId in seen else None
    return BudgetRow(
        id=b.id,
        name=b.name,
        ownerId=b.ownerId,
        ownerName=owner.displayName,
        access=Access.of(held),
        accountIds=accts,
        sharedWith=shared,
        method=b.method,
        reserves=b.reserves,
        moves=b.moves,
        startMonth=b.startMonth,
        roles=[RoleOut(**r.__dict__) for r in roles],
        active=viewer is not None and budgets.active_id(s, viewer) == b.id,
        version=b.version,
    )


def _check(body) -> list[FieldError]:
    errors = []
    if body.name is not None and (not body.name.strip() or len(body.name) > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    return errors


def _add_accounts(s, b: Budget, wanted: list[str]) -> None:
    """Accounts counted from the budget's start: a scenario's copy of another's."""
    now = clock.now()
    for aid in dict.fromkeys(wanted):
        s.add(BudgetAccount(budgetId=b.id, accountId=aid, createdAt=now))


def _month(value: str | None) -> dt.date:
    if not value:
        return budgets.month_of(clock.today())
    try:
        return budgets.month_of(dt.date.fromisoformat(value + "-01" if len(value) == 7 else value))
    except ValueError:
        raise Problem(422, "month-invalid", "A month such as 2026-10.") from None


@router.get("/budgets", response_model=list[BudgetRow])
def list_budgets(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        return [
            shape(s, b, perms, c.id)
            for b, perms in access.listing(s, Budget, c.id, order_by=Budget.name)
        ]


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
    with server(request).db.read(user=c.id) as s:
        visible = {a.id: a for a, _ in access.accounts(s, c.id)}
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
    with server(request).db.read(user=c.id) as s:
        b, held = access.budget(s, c.id, budget_id)
        return shape(s, b, held, c.id)


def _make_budget(s, c: Caller, body, budget_id: str) -> Budget:
    if body.method not in ("tracking", "envelope"):
        raise Problem(
            422,
            "method-invalid",
            "Tracking or envelope.",
            [FieldError("method", "method-invalid", "Tracking or envelope.")],
        )
    refuse_all(_check(body))
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
    # A user's first budget is the one they follow (S7.12.1).
    if budgets.active_id(s, c.id) is None:
        s.get(User, c.id).activeBudgetId = b.id
    activity.record(
        s, "budget.created", actor=c.id, subject_kind="budget", subject_id=b.id, owner=c.id
    )
    return b


def _change_budget(s, c: Caller, b: Budget, held: Perms, body, sent: set[str]) -> None:
    """The fields `sent`: its name and options. Its accounts are records of their own."""
    refuse_all(_check(body))
    fields = []
    if "name" in sent and body.name.strip() != b.name:
        b.name = body.name.strip()
        fields.append("name")
    for option in ("reserves", "moves"):
        value = getattr(body, option)
        if option in sent and value != getattr(b, option):
            if option == "moves" and b.method == "envelope" and not value:
                raise refuse("moves", "moves-needed", "An envelope budget always has moves.")
            setattr(b, option, value)
            fields.append(option)
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
    from ..store.entities.projections import Projection

    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        with _as_server(s, b) as (srv, sb):
            m = budgets.month_view(srv, sb, _month(month), clock.today(), c.id)
        names = _names(
            s,
            c.id,
            {x.accountId for x in m.moved}
            | {x.otherAccountId for x in m.moved}
            | {x.accountId for x in m.cards}
            | {r.heldInId for r in m.rows},
        )
        # A projection is named only to one who may read it (S7.2.1).
        pids = {r.projectionId for r in m.rows if r.projection}
        readable = set(s.scalars(select(Projection.id).where(Projection.id.in_(pids))))
        return MonthView(
            month=m.month,
            rows=[
                MonthRow(
                    **{k: v for k, v in r.__dict__.items() if k not in ("projection", "heldInId")},
                    heldInId=r.heldInId if r.heldInId in names else None,
                    projectionName=r.projection[0]
                    if r.projection and r.projectionId in readable
                    else None,
                    projectionMonthly=r.projection[1]
                    if r.projection and r.projectionId in readable
                    else None,
                )
                for r in m.rows
            ],
            unplanned=[Unplanned(categoryId=i, label=lb, spent=a) for i, lb, a in m.unplanned],
            income=m.income,
            expectedIncome=m.expectedIncome,
            spent=m.spent,
            saved=m.saved,
            moved=_withheld(
                (
                    (
                        None if x.accountId in names else (x.accountId, x.amount < 0),
                        MovedRow(
                            transactionId=x.transactionId,
                            date=x.date,
                            accountName=names.get(x.accountId, NOT_SHARED),
                            otherAccountName=None
                            if x.accountId not in names
                            else "a deleted account"
                            if x.otherDeleted
                            else names.get(x.otherAccountId, NOT_SHARED),
                            amount=x.amount,
                            payee=x.payee,
                        ),
                    )
                    for x in m.moved
                ),
                ("amount",),
            ),
            moves=_moves_out(s, b, m.month, c.id),
            toBudget=m.toBudget,
            assigned=m.assigned,
            assignedByMoves=m.assignedByMoves,
            cards=[
                CardLine(
                    accountId=x.accountId if x.accountId in names else None,
                    name=names.get(x.accountId, NOT_SHARED),
                    setAside=x.setAside,
                    owed=x.owed,
                    paid=x.paid,
                    notBacked=x.notBacked,
                )
                for x in m.cards
            ],
            available=m.available,
            left=m.left,
            unbacked=m.unbacked,
            yearlySpent=m.yearlySpent,
            uncategorised=m.uncategorised,
            daysLeft=m.daysLeft,
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
    if ln.heldInId and ln.heldInId not in _budget_accounts(s, b, ln.fromMonth):
        errors.append(
            FieldError(f"{at}heldInId", "account-unknown", "One of the budget's accounts.")
        )
    if ln.projectionId and not _projection_ok(s, b, ln.projectionId):
        errors.append(FieldError(f"{at}projectionId", "projection-unknown", "Choose a projection."))
    return errors


def _budget_accounts(s, b: Budget, month: dt.date) -> list[str]:
    """The accounts the budget counts in a month, as its owner chose them, whoever asks: a
    `write` receiver's change to a reserve's line keeps the account it is held in, one they
    may not see (S7.1.1)."""
    with scoping.as_server(s, "a budget's accounts, to check a line against", False) as srv:
        return budgets.account_ids(srv, srv.get(Budget, b.id), None, month)


def _balance_kept(s, b: Budget, cat_id: str, month: dt.date, viewer: str) -> Decimal:
    """What a category's line carries into a month, as the viewer's figures have it: a
    reserve's balance, a rollover line's remainder, an envelope's balance. Kept no longer once
    the category is taken out of the plan (or a reserve's target goes), so that is asked first
    (S7.10.3)."""
    with _as_server(s, b) as (srv, sb):
        before = budgets.month_view(srv, sb, budgets.add_months(month, -1), clock.today(), viewer)
    row = next((r for r in before.rows if r.categoryId == cat_id), None)
    return row.remaining if row is not None and row.rollover else Decimal(0)


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


def _seen(s, viewer: str, account_ids) -> set[str]:
    """Of these accounts, those the viewer may see: a reserve held in another is given to them
    with no account (S7.1.1, S11.3.1)."""
    return set(_names(s, viewer, {x for x in account_ids if x}))


def _line_out(ln: BudgetLine, seen: set[str]) -> LineOut:
    """`seen`: the accounts the reader may see; a line held in another names none. A save
    merges what the draft changed into the line as stored, so it keeps it all the same."""
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
        heldInId=ln.heldInId if ln.heldInId in seen else None,
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
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id, "read")
        lines = budgets.in_force(budgets.lines(s, b), m)
        tr = budgets.tree(s)
        ordered = sorted(lines.values(), key=lambda ln: tr.label(ln.categoryId))
        seen = _seen(s, c.id, (ln.heldInId for ln in ordered))
        return PlanOut(month=m, lines=[_line_out(ln, seen) for ln in ordered])


# ---------- plan lines in a dialog's draft (S12.15, S13.8.11) ----------


class LineIn(Model):
    """A plan line as a draft saves it: the line holds from `fromMonth` on, earlier months
    keeping the plan they had (S7.1.2)."""

    budgetId: IdOf("Bdgt")  # type: ignore[valid-type]
    categoryId: IdOf("Cat")  # type: ignore[valid-type]
    fromMonth: dt.date
    amount: Money
    # Taken out of the plan from `fromMonth` (S7.1.2); any amount, 0 included, keeps it in.
    out: bool = False
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
    # The owner's gift and giving plans set Gifts and Giving whoever writes the line, though
    # those plans aren't shared with them (S7.3.6, S7.1.1).
    why = "the plans a budget's owner keeps, for one who writes it"
    with scoping.as_server(ctx.s, why, False) as srv:
        sb = srv.get(Budget, b.id)
        elsewhere = plan.planned_elsewhere(srv, sb, budgets.tree(srv), month.year)
    refuse_all(_line_errors(ctx.s, b, body, cats, elsewhere))
    return b, month


LINE_FIELDS = (
    "amount",
    "out",
    "cadence",
    "rollover",
    "overspend",
    "projectionId",
    "target",
    "heldInId",
)


def _values(body: LineIn) -> dict:
    return {
        "amount": body.amount,
        "out": body.out,
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
        with srv.db.tx(unscoped="Activity: a budget's plan saved") as s:
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
    A line taking it out from the same month gives way to it."""
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
    being kept while it holds money is asked first (S7.10.3), as is a rollover line or an
    envelope taken out of the plan with a balance; a line of 0 stays in the plan and keeps its
    balance."""
    if body.budgetId != ln.budgetId or body.categoryId != ln.categoryId:
        raise refuse("categoryId", "line-fixed", "A line keeps its budget and category.")
    b, month = _line_checked(ctx, body)
    if month < ln.fromMonth:
        raise refuse("fromMonth", "month-earlier", "A change holds from its own month on.")
    values = _values(body)
    stops = (values["out"] and not ln.out) or (ln.target is not None and values["target"] is None)
    if stops:
        held = _balance_kept(ctx.s, b, ln.categoryId, month, ctx.caller.id)
        if held:
            label = budgets.tree(ctx.s).label(ln.categoryId)
            # An envelope's balance is money set aside: with only its target off, it stays in
            # the envelope, now an ordinary line (S7.10.3, S7.13.3).
            kept = b.method == "envelope" and not values["out"]
            then = "it stays in the envelope" if kept else "it stops being kept"
            ctx.ask("balance-dropped", f"{label} holds {grouped(held)}: {then}.")
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
            raise stale(_line_out(later, _seen(ctx.s, ctx.caller.id, [later.heldInId])))
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
    ln = ctx.s.get(BudgetLine, record_id)
    return _line_out(ln, _seen(ctx.s, ctx.caller.id, [ln.heldInId]))


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


def _moves_out(s, b: Budget, month: dt.date, viewer: str) -> list[MoveOut]:
    """The month's moves, a card's payment line named only to a viewer who may see the card
    (S7.1.1)."""
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
    cards = _names(s, viewer, {m.cardId for m in rows})

    def label(cat_id: str | None, landed: bool, side: str, card: str | None = None) -> str:
        if cat_id and cat_id in tr.by_id:
            return tr.label(cat_id)
        if card and side == "to":
            return f"{cards[card]}'s payment" if card in cards else f"the payment of {NOT_SHARED}"
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
            or card.id not in budgets.account_ids(s, b, None, body.month)
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


@router.get("/transactions/{txn_id}/budgets", response_model=list[InBudget])
def in_budgets(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """The caller's budgets counting a transaction, what it counts as in each, and each one's
    leave-out (S7.3.5, S12.2.3). The category is the transaction's, the same in every budget."""
    from ..store.entities.accounts import Split
    from ..store.entities.budgets import BudgetLeaveOut

    with server(request).db.read(user=c.id) as s:
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
        for b, perms in access.listing(s, Budget, c.id, order_by=Budget.name):
            if t.accountId not in budgets.account_ids(s, b, c.id, t.date):
                continue
            left = s.get(BudgetLeaveOut, (b.id, t.id))
            out.append(
                InBudget(
                    budgetId=b.id,
                    name=b.name,
                    countsAs=counts_as,
                    leftOut=left is not None and not left.deleted,
                    access=Access.of(perms),
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
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        with _as_server(s, b) as (srv, sb):
            tr = budgets.tree(srv, sb, c.id)
            mem = budgets.members(srv, sb, c.id)
            rows = list(srv.scalars(select(Account).where(Account.id.in_(mem.at(m)))))
            roles = {r.accountId: r for r in plan.roles(srv, sb, rows, today)}
            held = reserves.held_in(
                srv, sb, mem, tr, budgets.lines(srv, sb), reserves.moves(srv, sb), m
            )
            owed = {a.id: _card_month(srv, a, m) for a in rows if a.type == "credit-card"}
        names = _names(
            s,
            c.id,
            {a.id for a in rows}
            | {x for r in roles.values() for x in (r.paidFromId, r.movedFromId)},
        )

        def named(account_id: str | None) -> str | None:
            return names.get(account_id, NOT_SHARED) if account_id else None

        def shown(account_id: str | None) -> str | None:
            return account_id if account_id in names else None

        out = []
        for h in held:
            frm = roles.get(h.accountId)
            moved_from = frm.movedFromId if frm else None
            hidden = h.accountId not in names
            out.append(
                HeldInOut(
                    accountId=shown(h.accountId),
                    accountName=named(h.accountId),
                    movedFromId=shown(moved_from),
                    movedFromName=named(moved_from),
                    reserves=[
                        ReserveHeld(categoryId=k, label=tr.label(k), balance=v)
                        for k, v in h.reserves
                    ],
                    total=h.total,
                    movedIn=h.movedIn,
                    reservesFlow=h.reservesFlow,
                    given=h.given,
                    balance=h.balance,
                    toMove=h.toMove,
                    between=[
                        BetweenOut(
                            fromId=shown(x.fromId),
                            fromName=named(x.fromId),
                            toId=shown(x.toId),
                            toName=named(x.toId),
                            amount=x.amount,
                        )
                        for x in h.between
                    ],
                    withdrawals=h.withdrawals,
                    limit=h.limit,
                    overLimit=h.toMove < 0 and h.limit is not None and h.withdrawals + 1 > h.limit,
                    unassigned=_withheld(
                        ((hidden or None, LandedOut(**x.__dict__)) for x in h.unassigned),
                        ("amount", "free"),
                    ),
                    transfers=_withheld(
                        (
                            (
                                kept if hidden else None,
                                TransferIn(
                                    transactionId=x.transactionId,
                                    date=x.date,
                                    payee=x.payee,
                                    amount=x.amount,
                                    kept=kept,
                                ),
                            )
                            for x, kept in h.transfers
                        ),
                        ("amount",),
                    ),
                )
            )
        cards = []
        for a in rows:
            if a.id not in owed:
                continue
            paid_from = roles[a.id].paidFromId if a.id in roles else None
            cards.append(
                CardOut(
                    accountId=shown(a.id),
                    accountName=named(a.id),
                    paidFromId=shown(paid_from),
                    paidFromName=named(paid_from),
                    **owed[a.id],
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
    (S7.10.5): a move the budget keeps, of no more than is unassigned of it, in the month it is
    given, so the month it landed keeps what it showed (R3.10). Only money landed in an account
    the giver can see: the transaction is read in their own session."""
    from ..budgets import reserves

    t = s.get(Transaction, body.transactionId)
    m = budgets.month_of(body.month)
    # What is unassigned of it is what Where the money is shows them (S7.1.1).
    with _as_server(s, b) as (srv, sb):
        mem = budgets.members(srv, sb, c.id)
        lines = budgets.lines(srv, sb)
        found = reserves.held_in(
            srv, sb, mem, budgets.tree(srv, sb, c.id), lines, reserves.moves(srv, sb), m
        )
    if t is None or t.deleted or not mem.counts(t.accountId, t.date) or t.amount <= 0:
        raise refuse("transactionId", "not-found", "No such money landed.")
    if body.fromCategoryId is not None or body.cardId is not None:
        raise refuse("fromCategoryId", "move-invalid", "Landed money comes from where it landed.")
    if m < budgets.month_of(t.date):
        raise refuse("month", "month-invalid", "The month it landed, or one after.")
    held = {h.accountId: h for h in found}
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


def _copies(s, m: BudgetMove, method: str, counted: list[str]) -> bool:
    """Whether a copy as scenario can hold a move as it is, never rewritten as another
    (S7.12.4): a card's payment line only in an envelope copy that counts the card (S7.13.2);
    landed money given or kept, in either method, while the copy counts the account it landed
    in (S7.10.5); To Budget only in an envelope copy (S7.13.1)."""
    if m.cardId:
        return method == "envelope" and m.cardId in counted
    if m.transactionId:
        t = s.get(Transaction, m.transactionId)
        return t is not None and t.accountId in counted
    return method == "envelope" or bool(m.fromCategoryId and m.toCategoryId)


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
    with server(request).db.tx(user=c.id) as s:
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
        mine = {a.id for a, _ in access.accounts(s, c.id)}
        counted = [a for a in budgets.account_ids(s, src, c.id, month) if a in mine]
        _add_accounts(s, b, counted)
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
                    # A reserve is held in one of the budget's accounts, else nowhere (S7.10.4).
                    heldInId=ln.heldInId if ln.heldInId in counted else None,
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
                if not _copies(s, m, b.method, counted):
                    continue
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
                        cardId=m.cardId,
                        createdById=c.id,
                    )
                )
        if budgets.active_id(s, c.id) is None:
            s.get(User, c.id).activeBudgetId = b.id
        activity.record(
            s, "budget.created", actor=c.id, subject_kind="budget", subject_id=b.id, owner=c.id
        )
        s.flush()
        out = shape(s, b, access.OWNER, c.id)
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
    with server(request).db.read(user=c.id) as s:
        a, _ = access.budget(s, c.id, budget_id)
        b, _ = access.budget(s, c.id, other)
        sums: dict[str, dict[str, list]] = {}
        labels: dict[str, str] = {}
        to_budget = {}
        views = {}
        for key, bud in (("a", a), ("b", b)):
            with _as_server(s, bud) as (srv, sb):
                m, views[key] = first, []
                while m <= last:
                    views[key].append((m, budgets.month_view(srv, sb, m, today, c.id)))
                    m = budgets.add_months(m, 1)
        for key, months in views.items():
            for m, v in months:
                for r in v.rows:
                    if r.kind == "income" or (r.cadence == "year" and m != last):
                        continue
                    labels[r.categoryId] = r.label
                    got = sums.setdefault(r.categoryId, {}).get(key)
                    if got is None:
                        # Its first month in the range brings what it carried in; each month
                        # after adds only its own (S7.3.11): a carry is never counted again.
                        got = sums[r.categoryId][key] = [r.carried, Decimal(0)]
                    got[0] += r.planned - r.carried
                    got[1] += r.actual
                to_budget[key] = getattr(v, "toBudget", None)
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
        "spent": f"{m.spent:.2f}",
        "income": f"{m.income:.2f}",
        "saved": f"{m.saved:.2f}",
        "toBudget": None if m.toBudget is None else f"{m.toBudget:.2f}",
        # What lands outside the plan or waits to be sorted changes the month too (S7.14).
        "unplanned": {cid: [str(spent), label] for cid, label, spent in m.unplanned},
        "uncategorised": m.uncategorised,
        "moved": [len(m.moved), f"{sum((x.amount for x in m.moved), Decimal(0)):.2f}"],
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
    was, got = then.get("unplanned", {}), now["unplanned"]
    for cat_id in sorted(set(was) | set(got)):
        a, b = was.get(cat_id), got.get(cat_id)
        if a is None or b is None or a[0] != b[0]:
            spent = (a or ["0.00"])[0], (b or ["0.00"])[0]
            out.append(f"{(b or a)[1]}: spent {spent[0]} then, {spent[1]} now, outside the plan")
    if then.get("uncategorised") != now["uncategorised"]:
        out.append(f"Uncategorised: {then.get('uncategorised')} then, {now['uncategorised']} now")
    if then.get("moved") != now["moved"]:
        (n, total), (n2, total2) = then.get("moved") or [0, "0.00"], now["moved"]
        out.append(f"Left or entered the budget: {n} ({total}) then, {n2} ({total2}) now")
    # Each total that changed is named, even beside a row that explains part of it (S7.14).
    totals = (
        ("spent", "Spent"),
        ("income", "Income"),
        ("saved", "Saved"),
        ("toBudget", "To Budget"),
    )
    for k, name in totals:
        if then.get(k) != now.get(k):
            out.append(f"{name}: {then.get(k)} then, {now.get(k)} now")
    return out


def _reviewed(
    s, b: Budget, month: dt.date, viewer: str, figures: dict | None
) -> ReviewedOut | None:
    """A reviewed month: who and when, for everyone, and what changed in the viewer's own
    figures since, nothing for one who had none kept then (S7.14)."""
    import json

    from ..store.entities.budgets import BudgetReview, BudgetReviewViewer

    r = s.scalars(
        select(BudgetReview).where(
            BudgetReview.budgetId == b.id,
            BudgetReview.month == month,
            BudgetReview.deleted == false(),
        )
    ).first()
    if r is None:
        return None
    kept = s.scalars(
        select(BudgetReviewViewer.figures).where(
            BudgetReviewViewer.reviewId == r.id,
            BudgetReviewViewer.userId == viewer,
            BudgetReviewViewer.deleted == false(),
        )
    ).first()
    changes = []
    if kept is not None:
        if figures is None:
            with _as_server(s, b) as (srv, sb):
                figures = _figures(budgets.month_view(srv, sb, month, clock.today(), viewer))
        changes = _changes(json.loads(kept), figures)
    who = s.get(User, r.reviewedById) if r.reviewedById else None
    return ReviewedOut(
        month=month,
        at=r.updatedAt,
        byName=who.displayName if who else None,
        changes=changes,
    )


@router.get("/budgets/{budget_id}/review", response_model=ReviewView)
def review(budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None):
    """The month before this one unless another is asked: what was overspent, what is to move,
    what is left in To Budget, and what waits to be sorted (S7.14)."""
    from ..budgets import reserves

    m = _month(month) if month else budgets.add_months(budgets.month_of(clock.today()), -1)
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        active = budgets.active_id(s, c.id) == b.id
        held = []
        with _as_server(s, b) as (srv, sb):
            v = budgets.month_view(srv, sb, m, clock.today(), c.id)
            if active:
                mem = budgets.members(srv, sb, c.id)
                held = reserves.held_in(
                    srv,
                    sb,
                    mem,
                    budgets.tree(srv, sb, c.id),
                    budgets.lines(srv, sb),
                    reserves.moves(srv, sb),
                    m,
                )
        ends = {y for h in held for x in h.between for y in (x.fromId, x.toId)}
        names = _names(s, c.id, {h.accountId for h in held} | ends)
        to_move = []
        for h in held:
            if h.toMove:
                to_move.append(
                    ToMoveOut(accountName=names.get(h.accountId, NOT_SHARED), toMove=h.toMove)
                )
            for x in h.between:
                if x.toId == h.accountId:
                    to_move.append(
                        ToMoveOut(
                            accountName=names.get(x.toId, NOT_SHARED),
                            toMove=x.amount,
                            fromName=names.get(x.fromId, NOT_SHARED),
                        )
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
    """Mark reviewed (S7.14): who and when, and the month's figures then as each person the
    budget is shared with sees them, so a later change is flagged to each in their own until
    it is reviewed again. Months are never locked."""
    import json

    from ..store.entities.budgets import BudgetReview, BudgetReviewViewer

    m = budgets.month_of(body.month)
    with server(request).db.tx(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        r = s.scalars(
            select(BudgetReview).where(
                BudgetReview.budgetId == b.id,
                BudgetReview.month == m,
                BudgetReview.deleted == false(),
            )
        ).first()
        if r is None:
            r = BudgetReview(id=ids.new_id("BdgRv"), budgetId=b.id, month=m, reviewedById=c.id)
            s.add(r)
        else:
            r.reviewedById, r.updatedAt = c.id, clock.now()
        with scoping.as_server(s, "a reviewed month's figures, kept for each who reads it") as srv:
            # Each one's figures as they are given them, so none passes on another's account
            # (S7.1.1); each is theirs alone.
            sb = srv.get(Budget, b.id)
            figures = {
                uid: json.dumps(_figures(budgets.month_view(srv, sb, m, clock.today(), uid)))
                for uid in access.holders_of(s, Budget, b.id)
            }
            for row in srv.scalars(
                select(BudgetReviewViewer).where(
                    BudgetReviewViewer.reviewId == r.id, BudgetReviewViewer.deleted == false()
                )
            ):
                if row.userId in figures:
                    row.figures, row.updatedAt = figures.pop(row.userId), clock.now()
                else:  # no longer shared with them
                    row.deletedAt, row.deletedById = clock.now(), c.id
            for uid, kept in figures.items():
                srv.add(BudgetReviewViewer(reviewId=r.id, userId=uid, figures=kept))
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

    with server(request).db.read(user=c.id) as s:
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
    today = clock.today()
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id, "write")
        with _as_server(s, b) as (srv, sb):
            tr = budgets.tree(srv, sb, c.id)
            found = plan.estimate(
                srv, sb, budgets.account_ids(srv, sb, c.id, today), tr, months, today
            )
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
            for x in found
        ]


@router.get("/budgets/{budget_id}/cash-flow", response_model=CashFlow)
def budget_cash_flow(
    budget_id: str, request: Request, c: Caller = Depends(caller), month: str | None = None
):
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        m = _month(month)
        with _as_server(s, b) as (srv, sb):
            f = budgets.cash_flow(srv, sb, m, c.id)
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
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        with _as_server(s, b) as (srv, sb):
            found = budgets.trends(srv, sb, _month(month), category, months, c.id)
        return [TrendPoint(month=m, planned=p, actual=a) for m, p, a in found]


@router.get("/budgets/{budget_id}/recurring", response_model=list[RecurringRow])
def budget_recurring(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """Found in the last 15 months of the budget's accounts each time it is asked."""
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        # The budget's figures are the budget's, over its owner's accounts (S7.1.1).
        with scoping.as_server(s, "a budget's recurring payments, for one who reads it") as srv:
            return _recurring(srv, c, srv.get(Budget, b.id))


def _recurring(s, c: Caller, b: Budget) -> list[RecurringRow]:
    today = clock.today()
    accts = budgets.account_ids(s, b, c.id, today)
    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accts),
            Transaction.deleted == false(),
            Transaction.date >= today - dt.timedelta(days=460),
        )
    ).all()
    # An entry names its account only to someone the account is shared with too; the owner's
    # other accounts are *an account not shared* (S7.1.1, S11.3.1).
    names = (
        {a.id: a.name for a in s.scalars(select(Account).where(Account.id.in_(accts)))}
        if c.id == b.ownerId
        else {a.id: a.name for a, _ in access.accounts(s, c.id, Account.id.in_(accts))}
    )
    return [
        RecurringRow(
            payee=x.payee,
            accountId=x.accountId if x.accountId in names else None,
            accountName=names.get(x.accountId, NOT_SHARED),
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
    """A budget as a draft saves it (S7.1): its method chosen when it is made. Its accounts are
    records of their own (`BudgetAccountRecord`), saved with it."""

    name: str
    method: Literal["tracking", "envelope"] = "tracking"
    reserves: bool = False
    moves: bool = False


class BudgetAccountRecord(Model):
    """An account a budget counts, over months (S7.1.7): from `fromMonth` (none: since the
    budget began) to `untilMonth` (none: still counted). Taking it out sets its last month, so
    earlier months keep it (R3.10); counting it again is a new record. Its roles: a card's
    paying account, or where money for reserves held in it moves from, chosen (none: as the
    history says, S7.1.6). Only the budget's owner chooses its accounts."""

    budgetId: IdOf("Bdgt")  # type: ignore[valid-type]
    accountId: IdOf("Acct")  # type: ignore[valid-type]
    fromMonth: dt.date | None = None
    untilMonth: dt.date | None = None
    paidFromId: IdOf("Acct") | None = None  # type: ignore[valid-type]
    movedFromId: IdOf("Acct") | None = None  # type: ignore[valid-type]


class BudgetAccountOut(BudgetAccountRecord):
    id: str
    version: int


class MoveRecord(MoveIn):
    """A move as a draft makes it (S7.11): made, or deleted to undo it. With a transaction,
    landed money given to a reserve held where it landed, or to no category: kept as the
    account's own (S7.10.5); its month is the one it is given in, never before it landed."""

    budgetId: IdOf("Bdgt")  # type: ignore[valid-type]
    transactionId: IdOf("Txn") | None = None  # type: ignore[valid-type]


def _budget_create(ctx, record_id: str, body: BudgetRecord) -> None:
    _make_budget(ctx.s, ctx.caller, body, record_id)


def _budget_current(ctx, b: Budget) -> dict:
    return {"name": b.name, "method": b.method, "reserves": b.reserves, "moves": b.moves}


def _budget_update(ctx, b: Budget, body: BudgetRecord) -> None:
    current = _budget_current(ctx, b)
    if body.method != current["method"]:
        raise refuse("method", "method-fixed", "A budget keeps its method; copy it as a scenario.")
    sent = {f for f in ("name", "reserves", "moves") if getattr(body, f) != current[f]}
    _, held = access.budget(ctx.s, ctx.caller.id, b.id, "write")
    _change_budget(ctx.s, ctx.caller, b, held, body, sent)
    if "reserves" in sent and not body.reserves:
        _targets_off(ctx, b)


def _targets_off(ctx, b: Budget) -> None:
    """Reserves turned off: every target comes off from this month on, as if taken off line by
    line, after the same question, naming each balance (S7.1.4, S7.10.3). Past months keep
    their plan (S7.1.2); in an envelope budget the balances stay in the envelopes."""
    month = budgets.month_of(clock.today())
    every = budgets.lines(ctx.s, b)
    now = budgets.in_force(every, month)
    reserves = [ln for ln in now.values() if ln.target is not None]
    later = [ln for ln in every if ln.fromMonth > month and ln.target is not None]
    tr = budgets.tree(ctx.s)
    held = [(tr.label(ln.categoryId), _balance_kept(ctx.s, b, ln.categoryId, month, ctx.caller.id))
            for ln in reserves]  # fmt: skip
    held = sorted((label, amount) for label, amount in held if amount)
    if held:
        names = ", ".join(f"{label} holds {grouped(amount)}" for label, amount in held)
        then = (
            "the balances stay in their envelopes"
            if b.method == "envelope"
            else "the balances stop being kept"
        )
        when = f"{month:%B %Y}"
        ctx.ask("balance-dropped", f"Every target comes off from {when}: {names}; {then}.")
    for ln in [*reserves, *later]:
        if ln.fromMonth >= month:
            ln.target, ln.heldInId = None, None
            continue
        values = {f: getattr(ln, f) for f in LINE_FIELDS} | {"target": None, "heldInId": None}
        ctx.s.add(
            BudgetLine(
                id=ids.new_id("BdgLn"),
                budgetId=b.id,
                categoryId=ln.categoryId,
                fromMonth=month,
                **values,
            )
        )
    if reserves or later:
        _planned(ctx, b)


def _budget_delete(ctx, b: Budget) -> None:
    access.budget(ctx.s, ctx.caller.id, b.id, "deletable")
    b.mark_deleted(ctx.caller.id)
    for u in ctx.s.scalars(select(User).where(User.activeBudgetId == b.id)):
        u.activeBudgetId = None
    activity.record(ctx.s, "budget.deleted", actor=ctx.caller.id, subject_kind="budget",
                    subject_id=b.id, owner=ctx.caller.id)  # fmt: skip


def _budget_read(ctx, record_id: str) -> BudgetRow:
    b, held = access.budget(ctx.s, ctx.caller.id, record_id)
    return shape(ctx.s, b, held, ctx.caller.id)


def _move_create(ctx, record_id: str, body: MoveRecord) -> None:
    b, _ = access.budget(ctx.s, ctx.caller.id, body.budgetId)
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
    return next(x for x in _moves_out(ctx.s, b, mv.month, ctx.caller.id) if x.id == mv.id)


# ---------- a budget's accounts, over months (S7.1.7) ----------


def _ba_out(m: BudgetAccount) -> BudgetAccountOut:
    return BudgetAccountOut(
        id=m.id,
        version=m.version,
        budgetId=m.budgetId,
        accountId=m.accountId,
        fromMonth=m.fromMonth,
        untilMonth=m.untilMonth,
        paidFromId=m.paidFromId,
        movedFromId=m.movedFromId,
    )


def _ba_rows(s, b: Budget) -> list[BudgetAccount]:
    return list(
        s.scalars(
            select(BudgetAccount)
            .where(BudgetAccount.budgetId == b.id, BudgetAccount.deleted == false())
            .order_by(BudgetAccount.fromMonth)
        )
    )


@router.get("/budgets/{budget_id}/accounts", response_model=list[BudgetAccountOut])
def budget_accounts(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """The budget's accounts over months, each a record: those the caller can see (S7.1.1)."""
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        seen = {a.id for a, _ in access.accounts(s, c.id)}
        out = [_ba_out(m) for m in _ba_rows(s, b) if m.accountId in seen]
        for x in out:  # a role may name one the caller can't see
            x.paidFromId = x.paidFromId if x.paidFromId in seen else None
            x.movedFromId = x.movedFromId if x.movedFromId in seen else None
        return out


def _ba_checked(ctx, body: BudgetAccountRecord, record_id: str) -> Budget:
    """Its account is one the owner can see; its months whole months, the last not before the
    first; never a month another of the account's records holds; its roles among the budget's
    accounts."""
    b, held = access.budget(ctx.s, ctx.caller.id, body.budgetId, "write")
    if not held.configurable:
        raise Problem(403, "owner-only", "Only the owner chooses the accounts.")
    seen = {a.id for a, _ in access.accounts(ctx.s, ctx.caller.id)}
    if body.accountId not in seen:
        raise refuse(
            "accountId", "account-unknown", "Choose accounts you own or that are shared with you."
        )
    for f in ("fromMonth", "untilMonth"):
        v = getattr(body, f)
        if v is not None and v.day != 1:
            raise refuse(f, "month-invalid", "A month: its first day.")
    if body.fromMonth and body.untilMonth and body.untilMonth < body.fromMonth:
        raise refuse("untilMonth", "months-order", "The last month comes after the first.")
    mine = budgets.Span(body.accountId, body.fromMonth, body.untilMonth)
    for other in _ba_rows(ctx.s, b):
        if other.id == record_id or other.accountId != body.accountId:
            continue
        theirs = budgets.Span(other.accountId, other.fromMonth, other.untilMonth)
        if _overlap(mine, theirs):
            raise refuse(
                "fromMonth", "months-overlap", "The budget counts this account then already."
            )
    counted = {m.accountId for m in _ba_rows(ctx.s, b)} | {body.accountId}
    for f in ("paidFromId", "movedFromId"):
        v = getattr(body, f)
        if v is not None and v not in counted:
            raise refuse(f, "account-unknown", "Choose one of the budget's accounts.")
    return b


def _overlap(a: budgets.Span, b: budgets.Span) -> bool:
    lo = max(a.first or dt.date.min, b.first or dt.date.min)
    hi = min(a.last or dt.date.max, b.last or dt.date.max)
    return lo <= hi


def _ba_changed(ctx, b: Budget) -> None:
    b.updatedAt = clock.now()
    activity.record(ctx.s, "budget.updated", actor=ctx.caller.id, subject_kind="budget",
                    subject_id=b.id, owner=b.ownerId, detail={"fields": ["accounts"]})  # fmt: skip


def _ba_create(ctx, record_id: str, body: BudgetAccountRecord) -> None:
    b = _ba_checked(ctx, body, record_id)
    ctx.s.add(BudgetAccount(id=record_id, createdAt=clock.now(), **body.model_dump()))
    _ba_changed(ctx, b)


def _ba_editable(ctx, record_id: str) -> BudgetAccount:
    m = ctx.s.get(BudgetAccount, record_id)
    if m is None or m.deleted:
        raise Problem(404, "not-found", "Not found")
    access.budget(ctx.s, ctx.caller.id, m.budgetId, "write")
    return m


def _ba_current(ctx, m: BudgetAccount) -> dict:
    return _ba_out(m).model_dump(exclude={"id", "version"})


def _ba_update(ctx, m: BudgetAccount, body: BudgetAccountRecord) -> None:
    if body.budgetId != m.budgetId or body.accountId != m.accountId:
        raise refuse("accountId", "account-fixed", "A budget's account keeps its account.")
    b = _ba_checked(ctx, body, m.id)
    for f in ("fromMonth", "untilMonth", "paidFromId", "movedFromId"):
        setattr(m, f, getattr(body, f))
    _ba_changed(ctx, b)


def _ba_delete(ctx, m: BudgetAccount) -> None:
    """A correction: the account was never counted then (R3.10). Taking it out from a month
    on sets its last month instead."""
    b, held = access.budget(ctx.s, ctx.caller.id, m.budgetId, "write")
    if not held.configurable:
        raise Problem(403, "owner-only", "Only the owner chooses the accounts.")
    m.mark_deleted(ctx.caller.id)
    _ba_changed(ctx, b)


save.register(
    save.Kind(
        prefix="BdgAc",
        entity=BudgetAccount,
        fields=BudgetAccountRecord,
        create=_ba_create,
        editable=_ba_editable,
        current=_ba_current,
        update=_ba_update,
        delete=_ba_delete,
        read=lambda ctx, record_id: _ba_out(ctx.s.get(BudgetAccount, record_id)),
    )
)


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
