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
- A **payment day** with no payment recorded is read by the loan's Payments setting (S1.9.3):
  **recorded here**, it is **missed** once 15 days have passed (what was due is overdue, the
  balance stays); **assumed as scheduled**, it counts as paid as the schedule says. Automatic
  (none set) is recorded here once the loan has a payment recorded or a connection keeping it.
- A payment goes with the payment day whose grace it is made in: from 15 days after one day to
  15 days after the next. Recorded here, it pays the oldest day missed before it first, as a
  servicer applies a late payment.
"""

import calendar
import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock
from ..store.entities.accounts import Account, Category, Loan, Split, Transaction

ZERO = Decimal(0)
RECORDED, ASSUMED = "recorded", "assumed"
MODES = (RECORDED, ASSUMED)
GRACE = dt.timedelta(days=15)  # a servicer's usual grace period (S1.9.3)
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
    assumed: bool = False  # no payment recorded: made as the schedule says (S1.9.3)


@dataclass
class Row:
    """One payment of the schedule, past (as it was split) or ahead (as computed). Its status:
    `paid` (recorded), `assumed` (as scheduled, none recorded), `missed` (what was due, not
    paid) or `ahead` (the first of which may be a day passed, still in its grace)."""

    date: dt.date
    payment: Decimal
    principal: Decimal
    interest: Decimal
    escrow: Decimal
    pmi: Decimal
    balance: Decimal
    past: bool
    overpayment: Decimal = ZERO
    status: str = "ahead"


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


def automatic(recorded: bool, connected: bool) -> str:
    """What Automatic reads as (S1.9.3): recorded here once the loan has a payment recorded or
    a connection importing its statements; assumed as scheduled until then. A bank account
    pays it by a payment linked from it, which is a payment recorded."""
    return RECORDED if recorded or connected else ASSUMED


def modes(s: Session, account: Account, row: Loan) -> tuple[str, str]:
    """The loan's Payments setting as it reads, and what Automatic would read as."""
    recorded = s.scalars(
        select(Transaction.id).where(
            Transaction.accountId == account.id,
            Transaction.deleted == false(),
            Transaction.amount > 0,
        )
    ).first()
    auto = automatic(recorded is not None, account.connectionId is not None)
    return row.paymentsMode or auto, auto


def history(
    s: Session, account: Account, today: dt.date | None = None
) -> tuple[list[Payment], list[tuple[dt.date, Decimal]]]:
    """The payments made, with their parts, and the HELOC draws (money taken out). Assumed as
    scheduled, a payment day before today with none recorded has its payment, `assumed`."""
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
    recorded: list[Payment | tuple[dt.date, Decimal, str]] = []
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
            recorded.append(p)
        elif terms is not None:
            # However it arrived (a transfer matched from the bank, an import, a row typed in
            # the loan's account), a payment is split by the schedule (S1.9.3).
            recorded.append((t.date, t.amount, t.id))
        else:
            recorded.append(Payment(t.date, t.amount, principal=t.amount, transactionId=t.id))
    if terms is None:
        return [p for p in recorded if isinstance(p, Payment)], draws
    paid = any(t.amount > 0 for t in txns)
    mode = row.paymentsMode or automatic(paid, account.connectionId is not None)
    today = today or clock.today()
    return settle(
        terms, recorded, draws, today, assumed_before(terms, recorded, today, mode)
    ), draws


def settle(
    t: Terms,
    recorded: list,
    draws,
    today: dt.date,
    assume_before: dt.date | None,
) -> list[Payment]:
    """The payments in date order: each recorded one (a Payment, or its date, amount and
    transaction id to split by the schedule) and one on each payment day before
    `assume_before` with none recorded, assumed as scheduled and split as the schedule splits
    it (`assumed_before` says until when). Settling twice adds nothing: an assumed payment is
    in its own day's grace."""
    assume = assume_before is not None
    covered = _covered(t, [_dated(x) for x in recorded], catch_up=False) if assume else set()
    events: list[tuple[dt.date, int, object]] = [(_dated(x), 0, x) for x in recorded]
    if assume:
        k, day = 1, add_months(t.start, 1)
        while day < min(assume_before, today):
            if k not in covered:
                events.append((day, 1, None))
            k += 1
            day = add_months(t.start, k)
    events.sort(key=lambda e: (e[0], e[1]))
    out: list[Payment] = []
    for day, _, x in events:
        if x is None:
            p = _as_scheduled(t, out, draws, day)
            if p is not None:
                out.append(p)
        elif isinstance(x, Payment):
            out.append(x)
        else:
            _, amount, txn = x
            p = split_for(t, out, draws, day, amount)
            p.transactionId = txn
            out.append(p)
    return out


def assumed_before(t: Terms, recorded: list, today: dt.date, mode: str) -> dt.date | None:
    """Until when payment days with none recorded count as paid as scheduled: assumed, until
    today; recorded here, until the first payment recorded, whose day starts the record (S1.9.3:
    a loan entered years in, its payments recorded from now, has nothing missed before)."""
    if mode == ASSUMED:
        return today
    real = [_dated(x) for x in recorded if not (isinstance(x, Payment) and x.assumed)]
    if not real:
        return today
    return add_months(t.start, day_of(t, min(real)))


def _dated(x) -> dt.date:
    return x.date if isinstance(x, Payment) else x[0]


def day_of(t: Terms, day: dt.date) -> int:
    """The payment day (its number from the start) a payment on this day goes with: the first
    whose grace hasn't passed by then."""
    k = max(1, _months_between(t.start, day) - 1)
    while add_months(t.start, k) + GRACE < day:
        k += 1
    return k


def _covered(
    t: Terms, dates: list[dt.date], catch_up: bool, settled: dt.date | None = None
) -> set[int]:
    """The payment days the payments on these dates pay, and those before `settled` (assumed
    as scheduled, or with nothing owed). With `catch_up` (recorded here), a payment pays the
    oldest day missed before it first, as a servicer applies one."""
    paid: set[int] = set()
    k = 1
    while settled is not None and add_months(t.start, k) < settled:
        paid.add(k)
        k += 1
    low = k  # the oldest day not paid
    for d in sorted(dates):
        k = day_of(t, d)
        if catch_up and low < k and add_months(t.start, low) + GRACE < d:
            k = low
        paid.add(k)
        while low in paid:
            low += 1
    return paid


def _as_scheduled(t: Terms, before: list[Payment], draws, day: dt.date) -> Payment | None:
    """A payment day's payment as the schedule makes it, from what is owed then; none when
    nothing is."""
    row = _due(t, before, draws, day, before[-1].date if before else t.start)
    if row is None:
        return None
    return Payment(
        day,
        row.payment,
        principal=row.principal,
        interest=row.interest,
        escrowTax=t.escrowTax,
        escrowInsurance=t.escrowInsurance,
        pmi=row.pmi,
        assumed=True,
    )


def _due(t: Terms, before: list[Payment], draws, day: dt.date, since: dt.date) -> Row | None:
    """What the schedule has due on a payment day, from the balance owed the day before: its
    interest (on a daily-interest loan, the days since `since`), principal, escrow and PMI.
    None when nothing is owed."""
    owed = balance_on(t, [p for p in before if p.date < day], draws, day - dt.timedelta(days=1))
    if owed <= 0:
        return None
    rate = t.rate_on(day) / 100
    if t.method == "daily":
        interest = cents(owed * rate * (day - since).days / 365)
    else:
        interest = cents(owed * rate / 12)
    principal = _scheduled_principal(t, owed, interest, day)
    if day >= t.end or owed - principal < 1:
        principal = owed
    pmi = t.pmi_due(owed - principal)
    return Row(
        day, principal + interest + t.escrow + pmi, principal, interest, t.escrow, pmi, owed, True
    )


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
    mode: str = ASSUMED,
) -> list[Row]:
    """The payments made (and, assumed as scheduled, those assumed; recorded here, the days
    missed), then those ahead until the balance is paid. `extra` gives the payoff planner's
    overpayment on a payment's day, from the principal and interest due."""
    until = assumed_before(t, payments, today, mode)
    payments = settle(t, payments, draws, today, until)
    rows: list[Row] = [
        Row(
            p.date,
            p.total,
            p.principal,
            p.interest,
            p.escrowTax + p.escrowInsurance,
            p.pmi,
            balance_on(t, payments, draws, p.date),
            True,
            ZERO
            if p.assumed
            else max(
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
            "assumed" if p.assumed else "paid",
        )
        for p in payments
    ]
    # The days before `until` are settled: assumed, or nothing was owed (a HELOC not yet
    # drawn), so a late payment never goes back to one.
    paid = _covered(
        t, [p.date for p in payments], catch_up=mode == RECORDED, settled=min(until, today)
    )
    # The first payment day ahead: the first not passed (recorded here, not past its grace),
    # after the last one paid.
    k = 1
    while add_months(t.start, k) + (GRACE if mode == RECORDED else dt.timedelta(0)) < today:
        k += 1
    k = max(k, max(paid, default=0) + 1)
    day = add_months(t.start, k)
    if mode == RECORDED:
        rows += _missed(t, payments, draws, paid, k)
        rows.sort(key=lambda r: r.date)
    owed = balance_on(t, payments, draws, today)
    previous = max((r.date for r in rows if r.date < day), default=t.start)
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


def _missed(t: Terms, payments: list[Payment], draws, paid: set[int], ahead: int) -> list[Row]:
    """Recorded here, each payment day before the first ahead that no payment paid: what was
    due, nothing paid, and the balance as it was. Its interest is owed with it, not added to
    the balance; a daily-interest loan's next accrues from it."""
    rows: list[Row] = []
    for k in range(1, ahead):
        if k in paid:
            continue
        day = add_months(t.start, k)
        since = max(
            [p.date for p in payments if p.date < day] + [r.date for r in rows], default=t.start
        )
        due = _due(t, payments, draws, day, since)
        if due is None:
            continue
        due.balance = balance_on(t, payments, draws, day)
        due.status = "missed"
        rows.append(due)
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
    missed: int = 0  # recorded here: payment days passed their grace with none recorded
    overdue: Decimal = ZERO  # and what they were due: principal, interest, escrow and PMI


def summary(
    t: Terms, payments: list[Payment], draws, today: dt.date, mode: str = ASSUMED
) -> tuple[Summary, list[Row]]:
    """The loan's figures today. What is due next is the schedule's next row, the one source
    the screen, the payment dialog and the bank transactions offered all read (CR3-21): in a
    HELOC's draw period its interest alone, on a daily-interest loan that month's days, and at
    the end what rounding left. Assumed as scheduled, the payments assumed count as made."""
    payments = settle(t, payments, draws, today, assumed_before(t, payments, today, mode))
    rows = schedule(t, payments, draws, today, mode=mode)
    ahead = [r for r in rows if not r.past]
    missed = [r for r in rows if r.status == "missed"]
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
            missed=len(missed),
            overdue=sum((r.payment for r in missed), ZERO),
        ),
        rows,
    )


def split_new(t: Terms, payments: list[Payment], draws, day: dt.date, amount: Decimal) -> Payment:
    """How the schedule splits a payment about to be recorded, as `split_for` does, from the
    payments as they will read once it is: it takes the place of the one assumed on its day.
    Those assumed before it stay, whatever the setting: assumed as scheduled, they are paid;
    recorded here, the days before the first payment recorded are too (S1.9.3)."""
    k = day_of(t, day)
    kept = [p for p in payments if not (p.assumed and day_of(t, p.date) == k)]
    return split_for(t, kept, draws, day, amount)


def value(s: Session, account: Account, day: dt.date | None = None) -> Decimal:
    """What the loan counts in net worth on a day: minus what is owed."""
    row = loan_of(s, account)
    if row is None:
        return ZERO
    payments, draws = history(s, account)
    return -balance_on(terms_of(row), payments, draws, day)
