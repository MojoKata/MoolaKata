"""529 plans (requirements S1.8): the plan and its beneficiary, contributions totalled per
contributor per year against the annual gift exclusion (a five-year election spread over five),
withdrawals against qualified expenses per year, and how much could roll over to the
beneficiary's Roth IRA."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import valuation
from ..ledger import performance
from ..projections import taxtables
from ..store.entities.accounts import Account, Transaction
from ..store.entities.education import Contribution, EducationPlan, Person, QualifiedExpense
from ..store.entities.users import User
from ..store.repos import ledger as repo

ZERO = Decimal(0)
KINDS = {
    "tuition": "Tuition and fees",
    "room-board": "Room and board",
    "books": "Books and supplies",
    "computer": "A computer and internet",
    "k12": "K-12 tuition",
    "apprenticeship": "Apprenticeship",
    "student-loan": "Student-loan repayment",
}
# What happens inside the plan rather than money put in or taken out.
NOT_MONEY_IN_OR_OUT = (
    "interest",
    "dividend",
    "capital-gain",
    "return-of-capital",
    "buy",
    "sell",
    "reinvest",
    "split",
    "fee",
    "adjustment",
)
ROTH_AFTER_YEARS = 15  # open this long before a rollover
ROTH_RECENT_YEARS = 5  # contributions this recent can't roll over


def plan_of(s: Session, account: Account) -> EducationPlan | None:
    return s.scalars(
        select(EducationPlan).where(
            EducationPlan.accountId == account.id, EducationPlan.deleted == false()
        )
    ).first()


@dataclass
class Beneficiary:
    kind: str  # person
    id: str
    name: str
    birthYear: int | None
    deleted: bool = False  # kept by name (schema.md §6.4)


def beneficiary(s: Session, plan: EducationPlan | None) -> Beneficiary | None:
    if plan is None or not plan.beneficiaryId:
        return None
    p = s.get(Person, plan.beneficiaryId)
    if p is None:
        return None
    return Beneficiary("person", p.id, p.name, p.birthYear, p.deleted)


def _years(day: dt.date, n: int) -> dt.date:
    try:
        return day.replace(year=day.year + n)
    except ValueError:  # 29 February
        return day.replace(year=day.year + n, day=28)


@dataclass
class ContributionRow:
    transactionId: str
    date: dt.date
    amount: Decimal
    contributor: str  # owner or person:<id>
    name: str
    relationship: str | None
    fiveYear: bool


def contributions(s: Session, account: Account) -> list[ContributionRow]:
    """Every deposit into the 529, with who it came from (the owner unless recorded)."""
    owner = s.get(User, account.ownerId)
    txns = s.scalars(
        select(Transaction)
        .where(
            Transaction.accountId == account.id,
            Transaction.deleted == false(),
            Transaction.amount > 0,
            Transaction.kind.not_in(NOT_MONEY_IN_OR_OUT),
            Transaction.instrumentId.is_(None),
        )
        .order_by(Transaction.date)
    ).all()
    tags = {
        c.transactionId: c
        for c in s.scalars(
            select(Contribution).where(
                Contribution.transactionId.in_([t.id for t in txns]),
                Contribution.deleted == false(),
            )
        )
    }
    out = []
    words = None
    for t in txns:
        c = tags.get(t.id)
        key, name, rel = "owner", owner.displayName, "owner"
        if c is not None and c.fromPersonId:
            p = s.get(Person, c.fromPersonId)
            if words is None:
                from ..people import tree

                words = tree.relation_to(s, owner.personId)
            found = words.get(p.id)
            key, name, rel = f"person:{p.id}", p.name, found.word if found else None
        out.append(ContributionRow(t.id, t.date, t.amount, key, name, rel, bool(c and c.fiveYear)))
    return out


@dataclass
class GiftYear:
    contributor: str
    name: str
    year: int
    counted: Decimal  # what counts against this year's exclusion
    exclusion: Decimal
    over: bool  # above the exclusion: a gift-tax return (Form 709) is needed
    fromElection: int | None  # the year of the five-year election this comes from


def counted_years(s: Session, r: ContributionRow) -> dict[int, Decimal]:
    """What one contribution counts against the annual gift exclusion, by year: all of it in
    its year, or a five-year election up to five times its year's exclusion a fifth in its
    year and each of the next four, the rest (and any cent the fifths leave) in its year
    (S1.8.2). Gift spending's Form 709 flag counts 529s by it too (S7.8.7)."""
    if not r.fiveYear:
        return {r.date.year: r.amount}
    exclusion = Decimal(str(taxtables.figures(s, r.date.year)["giftExclusion"]))
    fifth = (min(r.amount, 5 * exclusion) / 5).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return {r.date.year + k: (r.amount - 4 * fifth if k == 0 else fifth) for k in range(5)}


def gift_years(s: Session, rows: list[ContributionRow]) -> list[GiftYear]:
    """Per contributor per year, what counts against the annual gift exclusion: a five-year
    election counts a fifth in its year and each of the next four (S1.8.2). The owner's own
    deposits are not gifts to the beneficiary's account owner, but are to the beneficiary,
    so they count too."""
    counted: dict[tuple[str, int], Decimal] = defaultdict(lambda: ZERO)
    names: dict[str, str] = {}
    election: dict[tuple[str, int], int] = {}
    for r in rows:
        names[r.contributor] = r.name
        for y, amount in counted_years(s, r).items():
            counted[(r.contributor, y)] += amount
            if r.fiveYear:
                election[(r.contributor, y)] = r.date.year
    out = []
    for (who, year), amount in sorted(counted.items(), key=lambda x: (-x[0][1], x[0][0])):
        limit = Decimal(str(taxtables.figures(s, year)["giftExclusion"]))
        out.append(
            GiftYear(
                who, names[who], year, amount, limit, amount > limit, election.get((who, year))
            )
        )
    return out


@dataclass
class WithdrawalYear:
    year: int
    distributions: Decimal  # taken out (Form 1099-Q), rollovers included
    expenses: Decimal  # qualified expenses
    # Distributions beyond the expenses and the rollovers: their earnings may be taxable.
    notCovered: Decimal
    rolledOver: Decimal = ZERO  # to the beneficiary's Roth IRA or another 529


ROLLED_TO = ("roth-ira", "529")  # where a rollover goes, by the receiving account's type


def _taken(s: Session, account: Account) -> list[tuple[Transaction, str | None]]:
    """Every cash outflow of the 529, each with the type of the account it went to when it is
    a matched transfer, read as the server: the reader of a 529 needn't see that account
    (S7.1.1)."""
    from ..budgets import other_halves

    txns = s.scalars(
        select(Transaction).where(
            Transaction.accountId == account.id,
            Transaction.deleted == false(),
            Transaction.amount < 0,
            Transaction.kind.not_in(NOT_MONEY_IN_OR_OUT),
            Transaction.instrumentId.is_(None),
        )
    ).all()
    others = other_halves(s, [t.transferId for t in txns if t.transferId])
    return [(t, others[t.transferId].type if t.transferId in others else None) for t in txns]


def withdrawals(s: Session, account: Account) -> list[WithdrawalYear]:
    """Each year's distributions (as Form 1099-Q reports them) against what covers them:
    qualified expenses, and money rolled over to a Roth IRA or another 529 (S1.8.3, S8.10)."""
    taken: dict[int, Decimal] = defaultdict(lambda: ZERO)
    rolled: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for t, to in _taken(s, account):
        taken[t.date.year] += -t.amount
        if to in ROLLED_TO:
            rolled[t.date.year] += -t.amount
    spent: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for e in expenses(s, account):
        spent[e.year] += e.amount
    years = sorted(set(taken) | set(spent), reverse=True)
    return [
        WithdrawalYear(y, taken[y], spent[y], max(taken[y] - spent[y] - rolled[y], ZERO), rolled[y])
        for y in years
    ]


def expenses(s: Session, account: Account) -> list[QualifiedExpense]:
    return list(
        s.scalars(
            select(QualifiedExpense)
            .where(QualifiedExpense.accountId == account.id, QualifiedExpense.deleted == false())
            .order_by(QualifiedExpense.date.desc())
        )
    )


@dataclass
class Rollover:
    possibleFrom: dt.date | None  # 15 years after opening
    limit: Decimal  # lifetime, from the tax tables
    used: Decimal  # rolled over already
    # The account's value less the last five years' contributions and their earnings, less
    # what was used.
    eligible: Decimal
    available: Decimal  # what could still roll over, once possible


def rollover(
    s: Session,
    account: Account,
    plan: EducationPlan | None,
    rows: list[ContributionRow],
    today: dt.date,
) -> Rollover:
    limit = Decimal(str(taxtables.figures(s, today.year)["rothFrom529"]))
    used = sum((-t.amount for t, to in _taken(s, account) if to == "roth-ira"), ZERO)
    cutoff = _years(today, -ROTH_RECENT_YEARS)
    led = repo.load(s, account)
    value = valuation.account_value(s, led, True)
    recent = _grown(s, led, [r for r in rows if r.date > cutoff], today)
    eligible = max(value - recent - used, ZERO)
    opened = plan.openedOn if plan is not None else None
    return Rollover(
        possibleFrom=_years(opened, ROTH_AFTER_YEARS) if opened else None,
        limit=limit,
        used=used,
        eligible=eligible,
        available=min(max(limit - used, ZERO), eligible),
    )


def _grown(s: Session, led, recent: list[ContributionRow], today: dt.date) -> Decimal:
    """Recent contributions with their estimated earnings (S1.8.4): each grown by the
    account's time-weighted return since its day; one whose return can't be told, as it
    went in."""
    if not recent:
        return ZERO
    first = min(r.date for r in recent)
    values = valuation.series(s, led, True, first, today)
    flow = valuation.flows(s, led, True, first, today)
    total = ZERO
    for r in recent:
        growth = performance.twr([(d, v) for d, v in values if d >= r.date], flow)
        total += r.amount * (1 + growth) if growth is not None else r.amount
    return total.quantize(Decimal("0.01"))


def accounts_for(s: Session, beneficiary_id: str, account_ids: list[str]) -> list[str]:
    """Of these accounts, the 529s for this beneficiary."""
    return list(
        s.scalars(
            select(EducationPlan.accountId).where(
                EducationPlan.beneficiaryId == beneficiary_id,
                EducationPlan.deleted == false(),
                EducationPlan.accountId.in_(account_ids),
            )
        )
    )
