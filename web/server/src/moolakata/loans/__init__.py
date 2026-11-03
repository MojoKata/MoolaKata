"""Loans (requirements S1.9): the schedule computed from a loan's terms and the payments made.

- The **balance** is what is owed: the principal (and a HELOC's draws) less the principal part
  of each payment. It counts in net worth as a negative amount.
- A **payment** is a transaction on the loan account, the other half of a transfer from a
  bank account, **split** into principal, interest, escrow (property tax, insurance), PMI and
  fees. Its split comes from the schedule; the person can correct it from the servicer's
  statement. Principal beyond the schedule's is an **overpayment**: the balance falls faster,
  and the payment stays, so the loan is paid off sooner.
- The **schedule ahead** runs from today's balance: monthly amortization at the rate of the
  day (an ARM's resets apply from their dates), or simple interest accrued daily between
  payments, as most car loans use. A HELOC pays interest only during its draw period, then
  amortizes over what is left of its term. A **recast** keeps the end date and lowers the
  payment to what the balance then needs.
"""

import calendar
import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..store.entities.accounts import Account, Category, Loan, Split, Transaction

ZERO = Decimal(0)
CENT = Decimal("0.01")
PMI_ENDS = Decimal("0.78")
TYPES = ("mortgage", "heloc", "auto-loan", "student-loan", "personal-loan", "loan")
# The split's parts, by the shipped category each is filed under.
PARTS = {
    "principal": "transfer.loan",
    "interest": "loans.interest",
    "escrowTax": "housing.property-tax",
    "escrowInsurance": "housing.insurance",
    "pmi": "loans.pmi",
    "fees": "loans.fees",
}


def is_loan(account_type: str) -> bool:
    return account_type in TYPES


def cents(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(day: dt.date, n: int) -> dt.date:
    y, m = divmod(day.month - 1 + n, 12)
    year, month = day.year + y, m + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass
class Payment:
    date: dt.date
    total: Decimal
    principal: Decimal = ZERO
    interest: Decimal = ZERO
    escrowTax: Decimal = ZERO
    escrowInsurance: Decimal = ZERO
    pmi: Decimal = ZERO
    fees: Decimal = ZERO
    transactionId: str | None = None
    overpayment: Decimal = ZERO


@dataclass
class Row:
    """One payment of the schedule, past (as it was split) or ahead (as computed)."""

    date: dt.date
    payment: Decimal
    principal: Decimal
    interest: Decimal
    escrow: Decimal
    pmi: Decimal
    balance: Decimal
    past: bool
    overpayment: Decimal = ZERO


@dataclass
class Terms:
    principal: Decimal
    start: dt.date
    months: int
    rate: Decimal  # yearly %, at the start
    method: str = "amortized"
    payment: Decimal | None = None
    escrowTax: Decimal = ZERO
    escrowInsurance: Decimal = ZERO
    pmi: Decimal = ZERO
    drawMonths: int = 0
    resets: list[tuple[dt.date, Decimal]] = field(default_factory=list)
    recasts: list[tuple[dt.date, Decimal]] = field(default_factory=list)
    originalValue: Decimal | None = None

    @property
    def end(self) -> dt.date:
        return add_months(self.start, self.months)

    def rate_on(self, day: dt.date) -> Decimal:
        rate = self.rate
        for when, r in sorted(self.resets):
            if when <= day:
                rate = r
        return rate

    @property
    def escrow(self) -> Decimal:
        return self.escrowTax + self.escrowInsurance

    def pmi_due(self, owed: Decimal) -> Decimal:
        """PMI while anything is owed, until the balance reaches 78% of the original value,
        when it ends by itself (S1.9.5)."""
        if owed <= 0 or (self.originalValue and owed <= self.originalValue * PMI_ENDS):
            return ZERO
        return self.pmi


def terms_of(row: Loan) -> Terms:
    return Terms(
        principal=row.principal,
        start=row.startDate,
        months=row.termMonths,
        rate=row.rate,
        method=row.method,
        payment=row.payment,
        escrowTax=row.escrowTax or ZERO,
        escrowInsurance=row.escrowInsurance or ZERO,
        pmi=row.pmi or ZERO,
        drawMonths=row.drawMonths or 0,
        resets=[
            (dt.date.fromisoformat(x["date"]), Decimal(str(x["rate"])))
            for x in json.loads(row.resets)
        ],
        recasts=[
            (dt.date.fromisoformat(x["date"]), Decimal(str(x.get("fee", 0))))
            for x in json.loads(row.recasts)
        ],
        originalValue=row.originalValue,
    )


def level_payment(balance: Decimal, yearly_rate: Decimal, months: int) -> Decimal:
    """The monthly principal and interest that pays the balance off in that many months."""
    if months <= 0:
        return cents(balance)
    r = yearly_rate / 100 / 12
    if r == 0:
        return cents(balance / months)
    return cents(balance * r / (1 - (1 + r) ** -months))


def scheduled_payment(t: Terms) -> Decimal:
    """Principal and interest a month, as the terms set it: typed, or computed."""
    if t.payment is not None:
        return t.payment
    if t.drawMonths:
        return level_payment(t.principal, t.rate, t.months - t.drawMonths)
    return level_payment(t.principal, t.rate, t.months)


def loan_of(s: Session, account: Account) -> Loan | None:
    return s.scalars(
        select(Loan).where(Loan.accountId == account.id, Loan.deleted == false())
    ).first()


def _category_keys(s: Session) -> dict[str, str]:
    """Category id → its shipped key, for the parts of a split."""
    return {
        c.id: c.builtIn for c in s.scalars(select(Category).where(Category.builtIn.is_not(None)))
    }


def history(s: Session, account: Account) -> tuple[list[Payment], list[tuple[dt.date, Decimal]]]:
    """The payments made, with their parts, and the HELOC draws (money taken out)."""
    keys = _category_keys(s)
    by_part = {v: k for k, v in PARTS.items()}
    txns = s.scalars(
        select(Transaction)
        .where(Transaction.accountId == account.id, Transaction.deleted == false())
        .order_by(Transaction.date, Transaction.createdAt)
    ).all()
    splits: dict[str, list[Split]] = {}
    ids = [t.id for t in txns]
    if ids:
        for sp in s.scalars(
            select(Split).where(Split.transactionId.in_(ids), Split.deleted == false())
        ):
            splits.setdefault(sp.transactionId, []).append(sp)
    row = loan_of(s, account)
    terms = terms_of(row) if row is not None else None
    payments: list[Payment] = []
    draws: list[tuple[dt.date, Decimal]] = []
    for t in txns:
        if t.amount < 0:
            draws.append((t.date, -t.amount))
            continue
        parts = splits.get(t.id)
        if parts:
            p = Payment(t.date, t.amount, transactionId=t.id)
            for sp in parts:
                part = by_part.get(keys.get(sp.categoryId or "", ""), "principal")
                setattr(p, part, getattr(p, part) + sp.amount)
        elif terms is not None:
            # However it arrived (a transfer matched from the bank, an import, a row typed in
            # the loan's account), a payment is split by the schedule (S1.9.3).
            p = split_for(terms, payments, draws, t.date, t.amount)
            p.transactionId = t.id
        else:
            p = Payment(t.date, t.amount, principal=t.amount, transactionId=t.id)
        payments.append(p)
    return payments, draws


def balance_on(t: Terms, payments: list[Payment], draws, day: dt.date | None = None) -> Decimal:
    day = day or dt.date.max
    owed = t.principal if t.start <= day else ZERO
    owed += sum((amt for d, amt in draws if d <= day), ZERO)
    owed -= sum((p.principal for p in payments if p.date <= day), ZERO)
    return max(owed, ZERO)


def split_for(t: Terms, payments: list[Payment], draws, day: dt.date, amount: Decimal) -> Payment:
    """How the schedule splits a payment of this amount on this day: interest on the balance
    since the last payment, the escrow and PMI the terms set, and the rest to principal."""
    before = [p for p in payments if p.date < day]
    owed = balance_on(t, before, draws, day - dt.timedelta(days=1))
    rate = t.rate_on(day) / 100
    if t.method == "daily":
        last = before[-1].date if before else t.start
        interest = cents(owed * rate * (day - last).days / 365)
    else:
        interest = cents(owed * rate / 12)
    escrow_tax, escrow_ins = t.escrowTax, t.escrowInsurance
    pmi = t.pmi_due(owed)
    rest = amount - interest - escrow_tax - escrow_ins - pmi
    if rest < 0:
        # Less than the interest and escrow: what there is pays them, in that order.
        escrow_tax = escrow_ins = pmi = ZERO
        interest = min(interest, amount)
        rest = amount - interest
    principal = min(rest, owed)
    fees = rest - principal
    sched = _scheduled_principal(t, owed, interest, day)
    return Payment(
        day,
        amount,
        principal=principal,
        interest=interest,
        escrowTax=escrow_tax,
        escrowInsurance=escrow_ins,
        pmi=pmi,
        fees=fees,
        overpayment=max(principal - sched, ZERO),
    )


def _in_draw(t: Terms, day: dt.date) -> bool:
    return bool(t.drawMonths) and day < add_months(t.start, t.drawMonths)


def draw_ends(t: Terms) -> dt.date | None:
    """The day a HELOC's draw period ends and its repayment starts."""
    return add_months(t.start, t.drawMonths) if t.drawMonths else None


def _scheduled_principal(t: Terms, owed: Decimal, interest: Decimal, day: dt.date) -> Decimal:
    if _in_draw(t, day):
        return ZERO
    return max(min(_pi_payment(t, owed, day) - interest, owed), ZERO)


def _pi_payment(t: Terms, owed: Decimal, day: dt.date) -> Decimal:
    """Principal and interest due on a day: the scheduled payment, unless a recast before it
    lowered it, or a reset changed the rate (an ARM re-amortizes over what is left)."""
    recast = [d for d, _ in t.recasts if d <= day]
    reset = [d for d, _ in t.resets if d <= day]
    if recast or reset:
        # Re-amortized from then on over what is left of the term: the end stays.
        return level_payment(owed, t.rate_on(day), max(1, _months_between(day, t.end) + 1))
    if t.drawMonths and not _in_draw(t, day):
        left = max(1, _months_between(day, t.end))
        return level_payment(owed, t.rate_on(day), left)
    return scheduled_payment(t)


def _months_between(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def schedule(
    t: Terms,
    payments: list[Payment],
    draws,
    today: dt.date,
    extra: Callable[[dt.date, Decimal], Decimal] | None = None,
) -> list[Row]:
    """The payments made, then those ahead until the balance is paid. `extra` gives the
    payoff planner's overpayment on a payment's day, from the principal and interest due."""
    rows: list[Row] = []
    for p in payments:
        rows.append(
            Row(
                p.date,
                p.total,
                p.principal,
                p.interest,
                p.escrowTax + p.escrowInsurance,
                p.pmi,
                balance_on(t, payments, draws, p.date),
                True,
                max(
                    p.principal
                    - _scheduled_principal(
                        t,
                        balance_on(
                            t,
                            [x for x in payments if x.date < p.date],
                            draws,
                            p.date - dt.timedelta(days=1),
                        ),
                        p.interest,
                        p.date,
                    ),
                    ZERO,
                ),
            )
        )
    owed = balance_on(t, payments, draws, today)
    # The next payment falls on the loan's day of the month, after today and the last paid.
    last = payments[-1].date if payments else t.start
    after = max(last, today)
    k = max(1, _months_between(t.start, after))
    while add_months(t.start, k) <= after:
        k += 1
    day = add_months(t.start, k)
    previous = last if payments else t.start
    # The payment stays level between the days that change it: a recast, a rate reset, or a
    # HELOC's draw period ending. Overpayments in between shorten the loan.
    changes = sorted({d for d, _ in t.recasts} | {d for d, _ in t.resets})
    pi = _pi_payment(t, owed, day)
    first = True
    guard = 0
    while owed > 0 and guard < 1200:
        guard += 1
        if not first and (
            any(previous <= d < day for d in changes)
            or (_in_draw(t, previous) and not _in_draw(t, day))
        ):
            pi = _pi_payment(t, owed, day)
        first = False
        rate = t.rate_on(day) / 100
        if t.method == "daily":
            interest = cents(owed * rate * (day - previous).days / 365)
        else:
            interest = cents(owed * rate / 12)
        principal = ZERO if _in_draw(t, day) else min(max(pi - interest, ZERO), owed)
        # PMI goes by the balance the scheduled payment leaves, so a plan's extra, worked out
        # with it, rounds what is paid (S1.9.5).
        scheduled = owed - principal
        bonus = cents(extra(day, pi, scheduled)) if extra else ZERO
        bonus = min(bonus, owed - principal)
        principal = principal + bonus
        if day >= t.end or owed - principal < 1:
            # The last payment takes what rounding left over.
            principal = owed
        owed -= principal
        pmi = t.pmi_due(scheduled) if owed > 0 else ZERO
        rows.append(
            Row(
                day,
                principal + interest + t.escrow + pmi,
                principal,
                interest,
                t.escrow,
                pmi,
                owed,
                False,
                bonus,
            )
        )
        previous = day
        k += 1
        day = add_months(t.start, k)
        if day > add_months(t.end, 600):
            break
    return rows


@dataclass
class Summary:
    balance: Decimal
    rate: Decimal
    payment: Decimal  # principal and interest due next, from the schedule's next row
    total: Decimal  # with escrow and PMI
    nextDate: dt.date | None
    payoffDate: dt.date | None
    interestPaid: Decimal
    interestAhead: Decimal
    principalThisYear: Decimal
    overpaid: Decimal
    originalPayoff: dt.date
    interestOnlyUntil: dt.date | None = None  # a HELOC's draw period's end, while in it


def summary(t: Terms, payments: list[Payment], draws, today: dt.date) -> tuple[Summary, list[Row]]:
    """The loan's figures today. What is due next is the schedule's next row, the one source
    the screen, the payment dialog and the bank transactions offered all read (CR3-21): in a
    HELOC's draw period its interest alone, on a daily-interest loan that month's days, and at
    the end what rounding left."""
    rows = schedule(t, payments, draws, today)
    ahead = [r for r in rows if not r.past]
    owed = balance_on(t, payments, draws, today)
    due = ahead[0] if ahead and owed > 0 else None
    pi = due.principal + due.interest if due else ZERO
    return (
        Summary(
            balance=owed,
            rate=t.rate_on(today),
            payment=pi,
            total=due.payment if due else ZERO,
            interestOnlyUntil=draw_ends(t) if due and _in_draw(t, due.date) else None,
            nextDate=ahead[0].date if ahead else None,
            payoffDate=(
                ahead[-1].date if ahead else (payments[-1].date if payments and owed == 0 else None)
            ),
            interestPaid=sum((p.interest for p in payments), ZERO),
            interestAhead=sum((r.interest for r in ahead), ZERO),
            principalThisYear=sum(
                (p.principal for p in payments if p.date.year == today.year), ZERO
            ),
            overpaid=sum((r.overpayment for r in rows if r.past), ZERO),
            originalPayoff=t.end,
        ),
        rows,
    )


def value(s: Session, account: Account, day: dt.date | None = None) -> Decimal:
    """What the loan counts in net worth on a day: minus what is owed."""
    row = loan_of(s, account)
    if row is None:
        return ZERO
    payments, draws = history(s, account)
    return -balance_on(terms_of(row), payments, draws, day)
