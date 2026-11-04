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
import dataclasses
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
        # Repaid from the draw period's end, its first repayment day, to the term's last
        # payment day, both counted (CR3-418).
        return level_payment(t.principal, t.rate, t.months - t.drawMonths + 1)
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
    until = assumed_before(terms, recorded, today, mode)
    return settle(terms, recorded, draws, today, until, catch_up=mode == RECORDED), draws


def settle(
    t: Terms,
    recorded: list,
    draws,
    today: dt.date,
    assume_before: dt.date | None,
    catch_up: bool = False,
) -> list[Payment]:
    """The payments in date order: each recorded one (a Payment, or its date, amount and
    transaction id to split by the schedule) and one on each payment day before
    `assume_before` with none recorded, assumed as scheduled and split as the schedule splits
    it (`assumed_before` says until when). Settling twice adds nothing: an assumed payment is
    in its own day's grace. `catch_up` (recorded here) says which day a late payment pays, so
    which day's interest it owes (`split_for`)."""
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
    # One walk for every split (`_Walker`); recorded here, the record starts at the first
    # payment recorded.
    real = [_dated(x) for x in recorded if not (isinstance(x, Payment) and x.assumed)]
    start = add_months(t.start, day_of(t, min(real))) if catch_up and real else None
    walker = _Walker(t, draws, catch_up, start)
    out: list[Payment] = []
    for day, _, x in events:
        if x is None:
            p = _as_scheduled(t, out, draws, day)
            if p is None:
                continue
        elif isinstance(x, Payment):
            p = x
        else:
            _, amount, txn = x
            p = split_for(t, out, draws, day, amount, catch_up, walker)
            p.transactionId = txn
        walker.add(p)
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


def _days_paid(
    t: Terms, dates: list[dt.date], catch_up: bool, settled: dt.date | None = None
) -> tuple[list[int], set[int]]:
    """The payment day each payment on these dates (in date order) pays, and every day paid or
    settled: those before `settled` (assumed as scheduled, or with nothing owed). A payment
    pays the day whose grace it is made in; with `catch_up` (recorded here), the oldest day
    missed before it first, as a servicer applies a late payment. The one mapping the splits,
    the missed rows and the schedule ahead all read."""
    paid: set[int] = set()
    k = 1
    while settled is not None and add_months(t.start, k) < settled:
        paid.add(k)
        k += 1
    low = k  # the oldest day not paid
    out: list[int] = []
    for d in dates:
        k = day_of(t, d)
        if catch_up and low < k and add_months(t.start, low) + GRACE < d:
            k = low
        out.append(k)
        paid.add(k)
        while low in paid:
            low += 1
    return out, paid


def _covered(
    t: Terms, dates: list[dt.date], catch_up: bool, settled: dt.date | None = None
) -> set[int]:
    """The payment days paid or settled (`_days_paid`)."""
    return _days_paid(t, sorted(dates), catch_up, settled)[1]


def _record_starts(t: Terms, payments: list[Payment]) -> dt.date | None:
    """The day of the first payment recorded, before which the days are settled (S1.9.3)."""
    real = [p.date for p in payments if not p.assumed]
    return add_months(t.start, day_of(t, min(real))) if real else None


@dataclass
class _Day:
    """A payment day as its payments have paid it so far: what it had due, from what was owed
    before its first payment (a month's interest on a monthly-amortization loan; PMI; the
    schedule's principal), and what was paid toward each."""

    owed: Decimal
    interest: Decimal
    pmi: Decimal
    principal: Decimal
    paidInterest: Decimal = ZERO
    paidTax: Decimal = ZERO
    paidInsurance: Decimal = ZERO
    paidPmi: Decimal = ZERO
    paidPrincipal: Decimal = ZERO


def _owed_before(t: Terms, draws, day: dt.date, principal_paid: Decimal) -> Decimal:
    """What was owed the day before `day`: the principal and the draws to then, less the
    principal paid."""
    before = day - dt.timedelta(days=1)
    owed = (t.principal if t.start <= before else ZERO) + sum(
        (amt for d, amt in draws if d <= before), ZERO
    )
    return max(owed - principal_paid, ZERO)


class _Walker:
    """The payments of a loan walked in date order, each through the payment day it pays: what
    was owed before it (earlier payments that day counted), the day as the earlier payments
    toward it left it, and the principal and interest due that day (`_level_at`). One walk is
    kept as payments are added, so settling a loan reads each payment once, not every earlier
    one again for each."""

    def __init__(self, t: Terms, draws, catch_up: bool, settled: dt.date | None) -> None:
        self.t, self.draws, self.catch_up = t, draws, catch_up
        self.effects = _effects(t, draws)
        self.levels: dict[dt.date, Decimal] = {}
        self.days: dict[int, _Day] = {}
        self.paid = ZERO  # principal paid so far
        # The days paid or settled (before `settled`), and the oldest not paid (`_days_paid`).
        self.covered: set[int] = set()
        k = 1
        while settled is not None and add_months(t.start, k) < settled:
            self.covered.add(k)
            k += 1
        self.low = k

    def _day_for(self, day: dt.date) -> int:
        t = self.t
        k = day_of(t, day)
        if self.catch_up and self.low < k and add_months(t.start, self.low) + GRACE < day:
            k = self.low
        return k

    def look(self, p: Payment) -> tuple[int, Decimal, _Day | None, Decimal]:
        """Where a payment would stand, without adding it: the day it pays, what was owed just
        before it, that day as the earlier payments left it (none for its first), and the
        principal and interest due."""
        t = self.t
        for e in self.effects:
            if e <= p.date and e not in self.levels:
                # Every payment walked so far is before this one: what was owed then.
                self.levels[e] = _level_at(t, e, _owed_before(t, self.draws, e, self.paid))
        e = max((x for x in self.effects if x <= p.date), default=None)
        pi = self.levels[e] if e is not None else scheduled_payment(t)
        k = self._day_for(p.date)
        d = self.days.get(k)
        owed = _owed_before(t, self.draws, p.date, self.paid)
        return k, owed, None if d is None else dataclasses.replace(d), pi

    def add(self, p: Payment) -> tuple[int, Decimal, _Day | None, Decimal]:
        """Walk a payment (after every one walked so far): where it stood, as `look` says."""
        t = self.t
        k, owed, before, pi = self.look(p)
        d = self.days.get(k)
        if d is None:
            interest = (
                p.interest if t.method == "daily" else cents(owed * t.rate_on(p.date) / 100 / 12)
            )
            sched = _scheduled_principal(t, owed, p.interest, p.date, pi)
            d = self.days[k] = _Day(owed, interest, t.pmi_due(owed), sched)
        d.paidInterest += p.interest
        d.paidTax += p.escrowTax
        d.paidInsurance += p.escrowInsurance
        d.paidPmi += p.pmi
        d.paidPrincipal += p.principal
        self.paid += p.principal
        self.covered.add(k)
        while self.low in self.covered:
            self.low += 1
        return k, owed, before, pi


def _walk(
    t: Terms, payments: list[Payment], draws, catch_up: bool, settled: dt.date | None = None
) -> list[tuple[int, Decimal, _Day | None, Decimal]]:
    """Each payment (in date order) as `_Walker` walks it. Recorded here, the days before the
    first payment recorded are settled unless `settled` says otherwise."""
    if catch_up and settled is None:
        settled = _record_starts(t, payments)
    w = _Walker(t, draws, catch_up, settled)
    return [w.add(p) for p in payments]


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
    prior = [p for p in before if p.date < day]
    owed = balance_on(t, prior, draws, day - dt.timedelta(days=1))
    if owed <= 0:
        return None
    rate = t.rate_on(day) / 100
    if t.method == "daily":
        interest = cents(owed * rate * (day - since).days / 365)
    else:
        interest = cents(owed * rate / 12)
    pi = _level_on(
        t,
        day,
        lambda e: balance_on(t, [p for p in prior if p.date < e], draws, e - dt.timedelta(days=1)),
        draws,
    )
    principal = _scheduled_principal(t, owed, interest, day, pi)
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


def split_for(
    t: Terms,
    payments: list[Payment],
    draws,
    day: dt.date,
    amount: Decimal,
    catch_up: bool = False,
    walker: _Walker | None = None,
) -> Payment:
    """How the schedule splits a payment of this amount on this day. It pays the payment day it
    goes with (`_days_paid`; `catch_up`, recorded here): that day's interest, escrow and PMI,
    less what earlier payments toward the day paid of them, and the rest to principal. The
    interest is due once per payment day (CR3-417): a month's, on what was owed before the
    day's first payment; on a daily-interest loan, the days since the last payment. Principal
    beyond the schedule's for the day is an overpayment."""
    prior = sorted((p for p in payments if p.date <= day), key=lambda p: p.date)
    new = Payment(day, amount)
    if walker is None:
        # Recorded here, the record starts at its first payment, this one if none is before.
        settled = _record_starts(t, [*prior, new]) if catch_up else None
        walker = _Walker(t, draws, catch_up, settled)
        for p in prior:
            walker.add(p)
    _, owed, d, pi = walker.look(new)
    rate = t.rate_on(day) / 100
    if t.method == "daily":
        last = prior[-1].date if prior else t.start
        interest = cents(owed * rate * (day - last).days / 365)
    elif d is None:
        interest = cents(owed * rate / 12)
    else:
        interest = max(d.interest - d.paidInterest, ZERO)
    if d is None:
        escrow_tax, escrow_ins, pmi = t.escrowTax, t.escrowInsurance, t.pmi_due(owed)
    else:
        escrow_tax = max(t.escrowTax - d.paidTax, ZERO)
        escrow_ins = max(t.escrowInsurance - d.paidInsurance, ZERO)
        pmi = max(d.pmi - d.paidPmi, ZERO)
    rest = amount - interest - escrow_tax - escrow_ins - pmi
    if rest < 0:
        # Less than the interest and escrow: what there is pays them, in that order, and
        # nothing goes to principal.
        left = amount
        interest = min(interest, left)
        left -= interest
        escrow_tax = min(escrow_tax, left)
        left -= escrow_tax
        escrow_ins = min(escrow_ins, left)
        left -= escrow_ins
        pmi = min(pmi, left)
        rest = ZERO
    principal = min(rest, owed)
    fees = rest - principal
    if d is None:
        sched = _scheduled_principal(t, owed, interest, day, pi)
    else:
        sched = max(d.principal - d.paidPrincipal, ZERO)
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


def _scheduled_principal(
    t: Terms, owed: Decimal, interest: Decimal, day: dt.date, pi: Decimal
) -> Decimal:
    """The principal the schedule has due on a payment day: none in a HELOC's draw period;
    else the principal and interest due (`pi`) less the interest, up to what is owed."""
    if _in_draw(t, day):
        return ZERO
    return max(min(pi - interest, owed), ZERO)


def _effects(t: Terms, draws=()) -> list[dt.date]:
    """The payment days on which the principal and interest due is worked out again (S1.9.2):
    the first after each rate reset, each recast, and each HELOC draw in its repayment period
    (a fee or charge added to what is owed is one), and a HELOC's first repayment day."""
    out: set[dt.date] = set()
    late = [d for d, _ in draws if t.drawMonths and not _in_draw(t, d)]
    for c in [d for d, _ in t.recasts] + [d for d, _ in t.resets] + late:
        k = max(1, _months_between(t.start, c))
        while add_months(t.start, k) <= c:
            k += 1
        out.add(add_months(t.start, k))
    if t.drawMonths:
        out.add(add_months(t.start, t.drawMonths))
    return sorted(out)


def _level_at(t: Terms, day: dt.date, owed: Decimal) -> Decimal:
    """The level principal and interest set on a day that works it out again: what pays `owed`
    (owed before the day) off at that day's rate by the term's last payment day, the payments
    left counted with this one, so the end stays (CR3-418)."""
    left = t.months - _months_between(t.start, day) + 1
    return level_payment(owed, t.rate_on(day), max(1, left))


def _level_on(t: Terms, day: dt.date, owed_on: Callable[[dt.date], Decimal], draws=()) -> Decimal:
    """Principal and interest due on a payment day: the scheduled payment, until a day that
    works it out again (a recast, a reset, a HELOC's repayment starting); from the latest such
    day on or before this one, the level set then from what was owed then (`owed_on`), which
    stays until the next (CR3-419)."""
    e = max((x for x in _effects(t, draws) if x <= day), default=None)
    if e is None:
        return scheduled_payment(t)
    return _level_at(t, e, owed_on(e))


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
    catch_up = mode == RECORDED
    payments = settle(t, payments, draws, today, until, catch_up)
    # The days before `until` are settled: assumed, or nothing was owed (a HELOC not yet
    # drawn), so a late payment never goes back to one.
    settled = min(until, today)
    walked = _walk(t, payments, draws, catch_up, settled)
    rows: list[Row] = []
    for p, (_, owed_then, d, pi_then) in zip(payments, walked, strict=True):
        if p.assumed:
            over = ZERO
        elif d is None:
            over = max(
                p.principal - _scheduled_principal(t, owed_then, p.interest, p.date, pi_then), ZERO
            )
        else:
            over = max(p.principal - max(d.principal - d.paidPrincipal, ZERO), ZERO)
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
                over,
                "assumed" if p.assumed else "paid",
            )
        )
    paid = _covered(t, [p.date for p in payments], catch_up, settled)
    # The first payment day ahead: the first not passed (recorded here, not past its grace),
    # after the last one paid.
    k = 1
    while add_months(t.start, k) + (GRACE if catch_up else dt.timedelta(0)) < today:
        k += 1
    k = max(k, max(paid, default=0) + 1)
    day = add_months(t.start, k)
    if catch_up:
        rows += _missed(t, payments, draws, paid, k)
        rows.sort(key=lambda r: r.date)
    owed = balance_on(t, payments, draws, today)
    previous = max((r.date for r in rows if r.date < day), default=t.start)
    # The payment stays level between the days that change it: a recast, a rate reset, or a
    # HELOC's draw period ending (`_level_on`, as the rows passed have it). Overpayments in
    # between shorten the loan.
    effects = set(_effects(t, draws))
    pi = _level_on(
        t,
        day,
        lambda e: (
            owed
            if e >= day
            else balance_on(t, [p for p in payments if p.date < e], draws, e - dt.timedelta(days=1))
        ),
        draws,
    )
    first = True
    guard = 0
    while owed > 0 and guard < 1200:
        guard += 1
        if not first and day in effects:
            pi = _level_at(t, day, owed)
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
    until = assumed_before(t, payments, today, mode)
    payments = settle(t, payments, draws, today, until, mode == RECORDED)
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


def split_new(
    t: Terms,
    payments: list[Payment],
    draws,
    day: dt.date,
    amount: Decimal,
    catch_up: bool = False,
) -> Payment:
    """How the schedule splits a payment about to be recorded, as `split_for` does, from the
    payments as they will read once it is: it takes the place of the one assumed on its day.
    Those assumed before it stay, whatever the setting: assumed as scheduled, they are paid;
    recorded here, the days before the first payment recorded are too (S1.9.3). `catch_up`:
    the loan reads as recorded here once it is recorded."""
    k = day_of(t, day)
    kept = [p for p in payments if not (p.assumed and day_of(t, p.date) == k)]
    return split_for(t, kept, draws, day, amount, catch_up)


def value(s: Session, account: Account, day: dt.date | None = None) -> Decimal:
    """What the loan counts in net worth on a day: minus what is owed."""
    row = loan_of(s, account)
    if row is None:
        return ZERO
    payments, draws = history(s, account)
    return -balance_on(terms_of(row), payments, draws, day)
