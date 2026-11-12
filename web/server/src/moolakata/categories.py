"""Categories (requirements S7.2): one two-level tree for the household, the server's, which every
user reads. Who may change what (S7.2.3): anyone adds a category, at either level, and renames
any; its parent, kind and tax tag are its maker's while nothing uses it, else an admin's; a
category nothing uses is deleted by its maker or an admin (a shipped one by an admin); one in
use is merged into another of its kind, by an admin, everything that names it moving to that
one (S7.2.4). The shipped categories the server counts in by their key are never deleted or
merged away, and keep their kind.

`merge_lines` is the plan's part of a merge, a function of two line histories alone."""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import false, func, select, update
from sqlalchemy.orm import Session

from . import clock, ids
from .budgets import LOAN_PARTS
from .loans import PARTS
from .store.entities.accounts import Category, Loan, Rule, Split, Transaction
from .store.entities.budgets import BudgetLine, BudgetMove
from .taxes.panels import TAG_LABELS

KINDS = ("expense", "income", "savings", "transfer")
TAX_TAGS = tuple(TAG_LABELS)
NAME_MAX = 60
# The shipped categories the server's own code finds by their key: a gift plan's and a giving
# plan's spending, cash spent, a card's fees, a loan payment's parts as budgets count them
# (S1.9.7) and as its transaction is split. Merged away or deleted, what counts in them would
# have nowhere to go; their kind is what those rules assume.
SERVER_KEYS = frozenset(
    {"gifts", "giving", "cash", "fees", "loans", *LOAN_PARTS.values(), *PARTS.values()}
)


def server_named(c: Category) -> bool:
    return c.builtIn in SERVER_KEYS


def paths(cats: Iterable[Category]) -> dict[str, str]:
    """Each category's path, *Parent › Child*."""
    by = {x.id: x for x in cats}
    return {
        x.id: f"{by[x.parentId].name} › {x.name}" if x.parentId in by else x.name
        for x in by.values()
    }


def live(s: Session) -> list[Category]:
    return list(s.scalars(select(Category).where(Category.deleted == false())))


def children(s: Session, cat_id: str) -> list[Category]:
    return list(
        s.scalars(select(Category).where(Category.parentId == cat_id, Category.deleted == false()))
    )


def used(s: Session, cat_ids: Iterable[str]) -> set[str]:
    """Which of these categories something names: a transaction, a split, a rule, a budget's
    plan line or move, a loan's whole-payment category, or a child. Asked of a session that
    reads as the server (`scoping.as_server`): a use is a use whoever can see it."""
    want = set(cat_ids)
    if not want:
        return set()
    out: set[str] = set()
    probes = [
        (Transaction.categoryId, Transaction.deleted),
        (Split.categoryId, Split.deleted),
        (Rule.categoryId, Rule.deleted),
        (BudgetLine.categoryId, BudgetLine.deleted),
        (BudgetMove.fromCategoryId, BudgetMove.deleted),
        (BudgetMove.toCategoryId, BudgetMove.deleted),
        (Loan.budgetCategoryId, Loan.deleted),
        (Category.parentId, Category.deleted),
    ]
    for col, gone in probes:
        out |= set(s.scalars(select(col).where(col.in_(want), gone == false()).distinct()))
    return out


# ---------- a merge's plan lines ----------


@dataclass(frozen=True)
class Line:
    """A plan line's terms from its month on (S7.1.2), as `merge_lines` reads and writes them."""

    fromMonth: dt.date
    amount: Decimal
    out: bool = False
    cadence: str = "month"
    rollover: bool = False
    overspend: str = "carry"
    projectionId: str | None = None
    target: Decimal | None = None
    heldInId: str | None = None

    @staticmethod
    def of(x: BudgetLine) -> Line:
        return Line(
            fromMonth=x.fromMonth,
            amount=x.amount,
            out=x.out,
            cadence=x.cadence,
            rollover=x.rollover,
            overspend=x.overspend,
            projectionId=x.projectionId,
            target=x.target,
            heldInId=x.heldInId,
        )

    def terms(self) -> Line:
        """Its terms alone, whatever month they start."""
        return replace(self, fromMonth=dt.date.min)


CENT = Decimal("0.01")


def per(amount: Decimal, cadence: str, to: str) -> Decimal:
    """An amount planned every `cadence` as one planned every `to`: a year's is a twelfth of it
    a month, to the cent; a month's, twelve times it a year."""
    if cadence == to:
        return amount
    if cadence == "year":
        return (amount / 12).quantize(CENT, rounding=ROUND_HALF_EVEN)
    return amount * 12


def _in_force(lines: list[Line], month: dt.date) -> Line | None:
    found = None
    for x in lines:
        if x.fromMonth <= month:
            found = x
    return found


def _both(t: Line, s: Line, month: dt.date) -> Line:
    """Both categories planned in a month: one line with both amounts, on the target's terms;
    what the target's line leaves unset the source's gives, so a reserve or a carry the source
    built goes on (S7.2.4)."""
    if t.target is not None and s.target is not None:
        target = t.target + s.target
    else:
        target = t.target if t.target is not None else s.target
    return Line(
        fromMonth=month,
        amount=t.amount + per(s.amount, s.cadence, t.cadence),
        cadence=t.cadence,
        rollover=t.rollover or s.rollover,
        overspend=t.overspend,
        projectionId=t.projectionId or s.projectionId,
        target=target,
        heldInId=t.heldInId or s.heldInId,
    )


def merge_lines(target: list[BudgetLine | Line], source: list[BudgetLine | Line]) -> list[Line]:
    """One budget's plan for the target category once the source is merged into it (S7.2.4):
    month by month, what both planned, so every month, past ones too, plans what it did for
    the two. Where only one was in the plan, its line; where neither, out of the plan from
    there, once either had been in it. Lines that change nothing are left out."""
    t = sorted(
        (x if isinstance(x, Line) else Line.of(x) for x in target), key=lambda x: x.fromMonth
    )
    s = sorted(
        (x if isinstance(x, Line) else Line.of(x) for x in source), key=lambda x: x.fromMonth
    )
    out: list[Line] = []
    for month in sorted({x.fromMonth for x in t} | {x.fromMonth for x in s}):
        a, b = _in_force(t, month), _in_force(s, month)
        a_in, b_in = a is not None and not a.out, b is not None and not b.out
        if a_in and b_in:
            line = _both(a, b, month)
        elif a_in:
            line = replace(a, fromMonth=month)
        elif b_in:
            line = replace(b, fromMonth=month)
        elif out:
            line = replace(out[-1], fromMonth=month, out=True, amount=Decimal(0))
        else:
            continue
        if not out or out[-1].terms() != line.terms():
            out.append(line)
    return out


# ---------- the merge ----------


@dataclass
class Plan:
    """A merge worked out and checked: each category that goes, with where its uses go, and
    the children that move under the target as they are."""

    source: Category
    target: Category
    pairs: list[tuple[Category, Category]]  # (merged away, into)
    moved: list[Category]  # the source's children kept, now the target's


class Refused(Exception):
    def __init__(self, field: str | None, code: str, message: str) -> None:
        super().__init__(message)
        self.field, self.code, self.message = field, code, message


def plan(s: Session, source: Category, target: Category, mapping: dict[str, str]) -> Plan:
    """Check a merge of `source` into `target`, `mapping` giving each of the source's children
    its place: itself (it moves under the target) or one of the target's children (it merges
    into that one). Raises `Refused` naming what is wrong."""
    if target.id == source.id:
        raise Refused("into", "merge-itself", "Choose another category to merge it into.")
    if target.deleted:
        raise Refused("into", "category-unknown", "Choose a category.")
    if target.kind != source.kind:
        raise Refused("into", "merge-kind", f"Choose another {source.kind} category.")
    if server_named(source):
        raise Refused(
            None, "category-kept", "MoolaKata counts in this category by its own rules: it stays."
        )
    kids = sorted(children(s, source.id), key=lambda c: (c.name.lower(), c.id))
    if kids and target.parentId:
        raise Refused(
            "into", "merge-level", "Categories have two levels: merge it into a top-level one."
        )
    if target.parentId == source.id:
        raise Refused("into", "merge-itself", "Choose a category outside this one.")
    theirs = {c.id: c for c in children(s, target.id)}
    if set(mapping) != {c.id for c in kids}:
        raise Refused("children", "merge-children", "Say where each of its categories goes.")
    pairs: list[tuple[Category, Category]] = [(source, target)]
    moved: list[Category] = []
    names = {c.name.lower() for c in theirs.values()}
    for c in kids:
        to = mapping[c.id]
        if to == c.id:
            if c.name.lower() in names:
                raise Refused(
                    f"children.{c.id}",
                    "name-taken",
                    f"{target.name} has a {c.name} already: merge {c.name} into it.",
                )
            moved.append(c)
            continue
        into = theirs.get(to)
        if into is None:
            raise Refused(
                f"children.{c.id}", "merge-children", f"Choose one of {target.name}'s categories."
            )
        if into.kind != c.kind:
            raise Refused(f"children.{c.id}", "merge-kind", f"Choose another {c.kind} category.")
        if server_named(c):
            raise Refused(
                f"children.{c.id}",
                "category-kept",
                f"MoolaKata counts in {c.name} by its own rules: it moves, as it is.",
            )
        pairs.append((c, into))
    return Plan(source=source, target=target, pairs=pairs, moved=moved)


@dataclass
class Merged:
    lines: int  # plan lines written
    budgets: set[str]  # the budgets whose plans changed


def apply(s: Session, p: Plan, actor: str) -> Merged:
    """Carry out a checked merge in `s`, a session that reads and writes as the server: every
    use of each category merged away moves to the one it goes into, plan lines are merged per
    budget, children kept move under the target, and the merged categories are deleted."""
    now = clock.now()
    budgets: set[str] = set()
    written = 0
    for c in p.moved:
        c.parentId = p.target.id
    for gone, into in p.pairs:
        for col in (Transaction, Split, Rule):
            s.execute(
                update(col)
                .where(col.categoryId == gone.id, col.deleted == false())
                .values(categoryId=into.id, version=col.version + 1, updatedAt=now)
                .execution_options(synchronize_session=False)
            )
        s.execute(
            update(Loan)
            .where(Loan.budgetCategoryId == gone.id)
            .values(budgetCategoryId=into.id, version=Loan.version + 1, updatedAt=now)
            .execution_options(synchronize_session=False)
        )
        for col in (BudgetMove.fromCategoryId, BudgetMove.toCategoryId):
            s.execute(
                update(BudgetMove)
                .where(col == gone.id, BudgetMove.deleted == false())
                .values({col.key: into.id, "version": BudgetMove.version + 1, "updatedAt": now})
                .execution_options(synchronize_session=False)
            )
        # A move between the two is a move within one category now: it moves nothing.
        s.execute(
            update(BudgetMove)
            .where(
                BudgetMove.fromCategoryId == into.id,
                BudgetMove.toCategoryId == into.id,
                BudgetMove.deleted == false(),
            )
            .values(deletedAt=now, deletedById=actor, version=BudgetMove.version + 1, updatedAt=now)
            .execution_options(synchronize_session=False)
        )
        n, touched = _merge_plans(s, gone.id, into.id, actor, now)
        written += n
        budgets |= touched
        gone.mark_deleted(actor, now)
    s.flush()
    return Merged(lines=written, budgets=budgets)


def _merge_plans(
    s: Session, gone: str, into: str, actor: str, now: dt.datetime
) -> tuple[int, set[str]]:
    rows = list(
        s.scalars(
            select(BudgetLine).where(
                BudgetLine.categoryId.in_((gone, into)), BudgetLine.deleted == false()
            )
        )
    )
    by_budget: dict[str, tuple[list[BudgetLine], list[BudgetLine]]] = {}
    for x in rows:
        pair = by_budget.setdefault(x.budgetId, ([], []))
        pair[0 if x.categoryId == into else 1].append(x)
    written = 0
    touched: set[str] = set()
    for budget_id, (theirs, mine) in by_budget.items():
        if not mine:
            continue
        touched.add(budget_id)
        merged = merge_lines(theirs, mine)
        for x in theirs + mine:
            x.mark_deleted(actor, now)
        s.flush()
        for line in merged:
            s.add(
                BudgetLine(
                    id=ids.new_id("BdgLn"),
                    budgetId=budget_id,
                    categoryId=into,
                    fromMonth=line.fromMonth,
                    amount=line.amount,
                    out=line.out,
                    cadence=line.cadence,
                    rollover=line.rollover,
                    overspend=line.overspend,
                    projectionId=line.projectionId,
                    target=line.target,
                    heldInId=line.heldInId,
                )
            )
            written += 1
    return written, touched


def name_taken(s: Session, name: str, parent_id: str | None, but: str | None = None) -> bool:
    """Whether a live category under `parent_id` (the top level when None) has this name, in
    any case, other than `but`."""
    q = select(Category.id).where(
        Category.deleted == false(),
        func.lower(Category.name) == name.lower(),
        Category.parentId.is_(None) if parent_id is None else Category.parentId == parent_id,
    )
    if but:
        q = q.where(Category.id != but)
    return s.scalars(q).first() is not None
