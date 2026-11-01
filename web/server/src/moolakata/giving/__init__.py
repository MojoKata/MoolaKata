"""Charitable giving (requirements S7.9, S8.9): a year's plan and whose giving it counts, the
donations (recorded, and transactions categorised Giving), what counts toward the target and
what is deductible, the acknowledgements the tax rules need, income for the percentage, pace,
pledges, and the donor-advised fund."""

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
from ..store.entities.accounts import Account, Category, Transaction
from ..store.entities.giving import Donation, GivingPlan, Organisation
from ..store.repos import ledger as repo

ZERO = Decimal(0)
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


def plans(s: Session, user_id: str) -> list[tuple[GivingPlan, str]]:
    """The giving plans the user reads (GivingPlanAccess), newest first, with their level."""
    return [
        (p, perms.level())
        for p, perms in access.listing(s, GivingPlan, user_id, order_by=GivingPlan.year.desc())
    ]


def plan_for(s: Session, user_id: str, year: int) -> tuple[GivingPlan | None, str | None]:
    """The year's plan: the user's own, else one shared with them."""
    rows = [(p, lvl) for p, lvl in plans(s, user_id) if p.year == year]
    rows.sort(key=lambda x: x[1] != "owner")
    return rows[0] if rows else (None, None)


def givers(s: Session, plan: GivingPlan | None, user_id: str) -> list[str]:
    """Whose giving a plan counts: its owner's alone. Sharing a plan shows it, and never reads
    the accounts of those it is shared with (S7.9.1)."""
    if plan is None:
        return [user_id]
    return [plan.ownerId]


@dataclass
class Gift:
    """A donation, recorded or read from a transaction categorised Giving."""

    id: str | None  # the Donation's; None for a transaction alone
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
        org = orgs.get(d.organisationId or "")
        if d.kind == "daf-contribution":
            fund = s.get(Account, d.dafAccountId) if d.dafAccountId else None
            name = fund.name if fund else "Donor-advised fund"
        else:
            name = org.name if org else "An organisation"
        out.append(
            Gift(d.id, d.date, d.kind, d.amount, org, name, d.transactionId, d.acknowledged, d)
        )
        if d.transactionId:
            linked.add(d.transactionId)
    # Transactions categorised Giving that no donation records yet count as cash (S7.9.3).
    cats = [c.id for c in s.scalars(select(Category).where(Category.builtIn == "giving"))]
    accounts = [
        a.id
        for a in s.scalars(
            select(Account).where(Account.ownerId.in_(owners), Account.deleted == false())
        )
    ]
    if cats and accounts:
        for t in s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(accounts),
                Transaction.categoryId.in_(cats),
                Transaction.deleted == false(),
                Transaction.date >= first,
                Transaction.date <= last,
                Transaction.amount < 0,
            )
        ):
            if t.id in linked:
                continue
            org = by_name.get((t.payee or "").lower())
            out.append(Gift(None, t.date, "cash", -t.amount, org, t.payee or "Giving", t.id, False))
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
    cats = [c.id for c in s.scalars(select(Category).where(Category.kind == "income"))]
    accounts = [
        a.id
        for a in s.scalars(
            select(Account).where(Account.ownerId.in_(owners), Account.deleted == false())
        )
    ]
    if not cats or not accounts:
        return ZERO
    total = ZERO
    for t in s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(accounts),
            Transaction.categoryId.in_(cats),
            Transaction.deleted == false(),
            Transaction.date >= dt.date(year, 1, 1),
            Transaction.date <= dt.date(year, 12, 31),
        )
    ):
        total += t.amount
    return max(total, ZERO)


def target(plan: GivingPlan | None, earned: Decimal) -> Decimal:
    if plan is None:
        return ZERO
    if plan.targetKind == "amount":
        return plan.amount or ZERO
    return (earned * (plan.percent or Decimal(10)) / 100).quantize(Decimal("1"))


def pledged_ahead(orgs: list[Organisation], today: dt.date, given: dict[str, Decimal]) -> Decimal:
    """Pledges still due this year: monthly ones for the months left, yearly ones not yet
    given."""
    out = ZERO
    for o in orgs:
        if not o.pledge:
            continue
        if o.pledgeEvery == "month":
            out += o.pledge * (12 - today.month)
        elif o.pledgeEvery == "year" and given.get(o.id, ZERO) < o.pledge:
            out += o.pledge - given.get(o.id, ZERO)
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
