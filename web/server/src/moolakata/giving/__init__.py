"""Charitable giving (requirements S7.9, S8.9): a year's plan and whose giving it counts, the
donations (recorded, and spending in categories tagged charitable), what counts toward the
target and what is deductible, the acknowledgements the tax rules need, income for the
percentage, pace, pledges, and the donor-advised fund."""

import calendar
import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import access, valuation
from ..store import scoping
from ..store.entities.accounts import Account, Category, Split, Transaction
from ..store.entities.giving import Donation, GivingPlan, Organisation
from ..store.repos import ledger as repo

ZERO = Decimal(0)
CHARITABLE = "charitable"  # the tax tag a donation's category carries (S7.2, S7.9.3)
KINDS = {
    "cash": "Cash",
    "goods": "Goods",
    "securities": "Appreciated shares",
    "qcd": "QCD from an IRA",
    "daf-contribution": "Into the donor-advised fund",
    "daf-grant": "Grant from the donor-advised fund",
}
ACK_AT = Decimal(250)  # a written acknowledgement for any single gift of this or more
FORM_8283_AT = Decimal(500)  # goods over this in a year
APPRAISAL_AT = Decimal(5000)  # an item over this needs an appraisal


def plans(s: Session, user_id: str) -> list[tuple[GivingPlan, access.Perms]]:
    """The giving plans the user reads (GivingPlanAccess), newest first, with what they
    hold."""
    return access.listing(s, GivingPlan, user_id, order_by=GivingPlan.year.desc())


def plan_for(
    s: Session, user_id: str, year: int | None, plan_id: str | None = None
) -> tuple[GivingPlan | None, access.Perms | None]:
    """The plan shown: the user's own for the year, which comes first in any year, or the
    one chosen from those they read; None when there is none, or the one chosen is not theirs
    to read or (with a year) not that year's (S7.9.1)."""
    for p, held in plans(s, user_id):
        if plan_id is None and held.mine and p.year == year:
            return p, held
        if p.id == plan_id and (year is None or p.year == year):
            return p, held
    return None, None


def shared(s: Session, user_id: str, year: int) -> list[tuple[GivingPlan, access.Perms]]:
    """The year's plans shared with the user, to choose beside their own (S7.9.1)."""
    return [(p, held) for p, held in plans(s, user_id) if p.year == year and not held.mine]


def givers(s: Session, plan: GivingPlan | None, user_id: str) -> list[str]:
    """Whose giving a plan counts: its owner's alone. Sharing a plan shows it, and never reads
    the accounts of those it is shared with (S7.9.1)."""
    if plan is None:
        return [user_id]
    return [plan.ownerId]


@dataclass
class Gift:
    """A donation, recorded or read from spending in a category tagged charitable."""

    id: str | None  # the Donation's; None for a transaction (or split part) alone
    date: dt.date
    kind: str
    amount: Decimal
    organisation: Organisation | None
    name: str  # the organisation's, or the payee's
    transactionId: str | None
    acknowledged: bool
    record: Donation | None = None

    @property
    def deductible(self) -> bool:
        if self.kind in ("qcd", "daf-grant"):
            return False
        if self.kind == "daf-contribution":
            return True
        return self.organisation.deductible if self.organisation else True

    @property
    def needsAck(self) -> bool:
        return self.deductible and self.amount >= ACK_AT


def organisations(s: Session, owners: list[str]) -> dict[str, Organisation]:
    return {
        o.id: o
        for o in s.scalars(
            select(Organisation).where(
                Organisation.ownerId.in_(owners), Organisation.deleted == false()
            )
        )
    }


def gift(s: Session, d: Donation, orgs: dict[str, Organisation]) -> Gift:
    """A recorded donation as a gift, its organisation one of `orgs` (its owner's)."""
    org = orgs.get(d.organisationId or "")
    if d.kind == "daf-contribution":
        fund = s.get(Account, d.dafAccountId) if d.dafAccountId else None
        name = fund.name if fund else "Donor-advised fund"
    else:
        name = org.name if org else "An organisation"
    return Gift(d.id, d.date, d.kind, d.amount, org, name, d.transactionId, d.acknowledged, d)


def donations(s: Session, owners: list[str], year: int) -> list[Gift]:
    first, last = dt.date(year, 1, 1), dt.date(year, 12, 31)
    orgs = organisations(s, owners)
    by_name = {o.name.lower(): o for o in orgs.values()}
    out: list[Gift] = []
    linked: set[str] = set()
    for d in s.scalars(
        select(Donation).where(
            Donation.ownerId.in_(owners),
            Donation.deleted == false(),
            Donation.date >= first,
            Donation.date <= last,
        )
    ):
        out.append(gift(s, d, orgs))
        if d.transactionId:
            linked.add(d.transactionId)
    # Spending in a category tagged charitable, wherever it sits, that no donation records yet
    # counts as cash, each split part a gift of its own (S7.9.3, S7.3.1), as Taxes counts it.
    cats = {c.id for c in s.scalars(select(Category).where(Category.taxTag == CHARITABLE))}
    for p in parts(s, _accounts(s, owners), first, last, cats):
        t = p.transaction
        if p.amount >= 0 or t.id in linked:
            continue
        org = by_name.get((t.payee or "").lower())
        out.append(Gift(None, t.date, "cash", -p.amount, org, t.payee or "Giving", t.id, False))
    return sorted(out, key=lambda g: g.date, reverse=True)


def counts(plan: GivingPlan | None, g: Gift) -> bool:
    """What counts toward the target: everything that left the user's hands, a donor-advised
    fund once, when funded or when it grants as the plan says (S7.9.4)."""
    when = plan.dafCounted if plan else "funded"
    if g.kind == "daf-contribution":
        return when == "funded"
    if g.kind == "daf-grant":
        return when == "granted"
    return True


def income(s: Session, plan: GivingPlan | None, owners: list[str], year: int) -> Decimal:
    """The income the target's percentage is of: typed, or the year's income transactions,
    the plan's owner's, worked out as the server for whoever reads the plan (S7.9.1)."""
    if plan is not None and plan.incomeBasis in ("gross", "agi"):
        return plan.income or ZERO
    with scoping.as_server(s, "a giving plan's income, its owner's") as srv:
        return _income(srv, owners, year)


def _income(s: Session, owners: list[str], year: int) -> Decimal:
    cats = {c.id for c in s.scalars(select(Category).where(Category.kind == "income"))}
    first, last = dt.date(year, 1, 1), dt.date(year, 12, 31)
    total = sum((p.amount for p in parts(s, _accounts(s, owners), first, last, cats)), ZERO)
    return max(total, ZERO)


def _accounts(s: Session, owners: list[str]) -> list[str]:
    return [
        a.id
        for a in s.scalars(
            select(Account).where(Account.ownerId.in_(owners), Account.deleted == false())
        )
    ]


@dataclass(frozen=True)
class Part:
    """A transaction in one of the categories asked for, or one split part of one: a split
    transaction counts through its splits (S7.3.1), each part in its own category."""

    transaction: Transaction
    categoryId: str
    amount: Decimal


def parts(
    s: Session, accounts: list[str], first: dt.date, last: dt.date, cats: set[str]
) -> list[Part]:
    """The transactions, and the split parts of transactions, in `cats` over the accounts,
    between two dates inclusive. A split transaction has no category of its own."""
    if not cats or not accounts:
        return []
    within = (
        Transaction.accountId.in_(accounts),
        Transaction.deleted == false(),
        Transaction.date >= first,
        Transaction.date <= last,
    )
    out = [
        Part(t, t.categoryId, t.amount)
        for t in s.scalars(select(Transaction).where(*within, Transaction.categoryId.in_(cats)))
    ]
    for sp, t in s.execute(
        select(Split, Transaction)
        .join(Transaction, Transaction.id == Split.transactionId)
        .where(*within, Split.deleted == false(), Split.categoryId.in_(cats))
    ):
        out.append(Part(t, sp.categoryId, sp.amount))
    return out


def target(plan: GivingPlan | None, earned: Decimal) -> Decimal:
    if plan is None:
        return ZERO
    if plan.targetKind == "amount":
        return plan.amount or ZERO
    return (earned * (plan.percent or Decimal(10)) / 100).quantize(Decimal("1"))


def given_to(gifts: list[Gift], first: dt.date, last: dt.date) -> dict[str, Decimal]:
    """What was given to each organisation between two dates inclusive, by its id: what a
    pledge is met by (S7.9.5)."""
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for g in gifts:
        if g.organisation is not None and first <= g.date <= last:
            out[g.organisation.id] += g.amount
    return dict(out)


def pledge_short(o: Organisation, gifts: list[Gift], today: dt.date) -> Decimal:
    """What is still to be given of a pledge for the month or year `today` is in (S7.9.5)."""
    if not o.pledge or o.pledgeEvery not in ("month", "year"):
        return ZERO
    first = today.replace(day=1) if o.pledgeEvery == "month" else today.replace(month=1, day=1)
    return max(o.pledge - given_to(gifts, first, today).get(o.id, ZERO), ZERO)


def pledged_ahead(orgs: list[Organisation], today: dt.date, gifts: list[Gift]) -> Decimal:
    """Pledges still expected this year (S7.9.6): a monthly one's for this month, less what
    was given to it this month, and for each month after; a yearly one's less what was given
    to it this year."""
    out = ZERO
    for o in orgs:
        out += pledge_short(o, gifts, today)
        if o.pledge and o.pledgeEvery == "month":
            out += o.pledge * (12 - today.month)
    return out


@dataclass
class Fund:
    account: Account
    balance: Decimal
    contributed: Decimal
    granted: Decimal
    grants: list[Gift] = field(default_factory=list)


def funds(s: Session, owners: list[str], year: int, gifts: list[Gift]) -> list[Fund]:
    out = []
    for a in s.scalars(
        select(Account).where(
            Account.ownerId.in_(owners), Account.type == "daf", Account.deleted == false()
        )
    ):
        led = repo.load(s, a)
        bal = valuation.account_value(s, led, True)
        mine = [g for g in gifts if g.record and g.record.dafAccountId == a.id]
        out.append(
            Fund(
                a,
                bal,
                sum((g.amount for g in mine if g.kind == "daf-contribution"), ZERO),
                sum((g.amount for g in mine if g.kind == "daf-grant"), ZERO),
                [g for g in mine if g.kind == "daf-grant"],
            )
        )
    return out


def causes_of(o: Organisation | None) -> list[str]:
    return json.loads(o.causes) if o is not None else []


def pace(total: Decimal, today: dt.date, year: int) -> Decimal:
    """The even pace to the target, as of today."""
    if year < today.year:
        return total
    if year > today.year:
        return ZERO
    days = 366 if calendar.isleap(year) else 365
    return (total * today.timetuple().tm_yday / days).quantize(Decimal("1"))


def by_month(plan: GivingPlan | None, gifts: list[Gift], year: int) -> list[Decimal]:
    """What was given by the end of each month, counted as the plan counts."""
    months = defaultdict(lambda: ZERO)
    for g in gifts:
        if counts(plan, g):
            months[g.date.month] += g.amount
    out, running = [], ZERO
    for m in range(1, 13):
        running += months[m]
        out.append(running)
    return out


def tax_notes(gifts: list[Gift]) -> list[str]:
    """What the year's goods need (S8.9): Form 8283 over $500, an appraisal over $5,000."""
    goods = [g for g in gifts if g.kind == "goods" and g.deductible]
    out = []
    if sum((g.amount for g in goods), ZERO) > FORM_8283_AT:
        out.append("Goods given this year come to over $500: Form 8283 goes with the return.")
    for g in goods:
        if g.amount > APPRAISAL_AT:
            out.append(
                f"{g.record.description or 'An item'} to {g.name} is over $5,000: it "
                "needs a qualified appraisal."
            )
    return out
