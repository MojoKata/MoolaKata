"""Loans (requirements S1.9): the rules at their edges, each pinned on the bound that tells it
apart: a day exactly on a reset or today, an amount under a cent or a dollar, a row left out."""

import dataclasses
import datetime as dt
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from moolakata import ids
from moolakata import loans as L
from moolakata.loans import payoff as P
from moolakata.store.entities.accounts import Account, Category, Loan, Split, Transaction
from moolakata.store.entities.assets import Item

d = dt.date


def _summed(t, recorded, draws, today, mode="assumed"):
    # As the loan's screen reads it (S1.9.3): its payments settled first, as `history` gives
    # them, then summed up.
    until = L.assumed_before(t, recorded, today, mode)
    paid = L.settle(t, recorded, draws, today, until, mode == "recorded")
    return L.summary(t, paid, draws, today, mode)


@pytest.fixture
def book(unscoped):
    return unscoped


def _account(s, uid, type="mortgage", **kw) -> Account:
    a = Account(id=ids.new_id("Acct"), ownerId=uid, name="Home", type=type, **kw)
    s.add(a)
    s.flush()
    return a


def _loan(s, a, **kw) -> Loan:
    kw = {"principal": D(300000), "startDate": d(2026, 1, 1), "termMonths": 360, "rate": D(6),
          **kw}  # fmt: skip
    row = Loan(id=ids.new_id("Loan"), accountId=a.id, **kw)
    s.add(row)
    s.flush()
    return row


def _txn(s, a, day, amount, **kw) -> Transaction:
    amount = D(amount)
    t = Transaction(id=ids.new_id("Txn"), accountId=a.id, date=day, amount=amount,
                    kind="withdrawal" if amount < 0 else "deposit", **kw)  # fmt: skip
    s.add(t)
    s.flush()
    return t


def _category(s, key) -> str:
    return s.scalars(select(Category.id).where(Category.builtIn == key)).one()


# loans.Terms.rate_on, Terms.pmi_due, original_value, terms_of, level_payment, loan_of, modes,
# history, settle


def test_a_reset_applies_from_its_own_day():
    # S1.9.1: the rate after a reset is the rate from the reset's date, that day included.
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(6),
                resets=[(d(2026, 7, 1), D("7.5"))])  # fmt: skip
    assert (t.rate_on(d(2026, 6, 30)), t.rate_on(d(2026, 7, 1))) == (6, D("7.5"))


def test_pmi_is_due_while_any_amount_is_owed():
    # S1.9.5: with no original value to end it, PMI stops only once nothing is owed, however
    # little is left.
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(6), pmi=D(90))
    assert t.pmi_due(D(0)) == 0
    assert t.pmi_due(D("0.50")) == t.pmi_due(D(1)) == 90


def test_the_original_value_of_a_home_deleted_or_missing_is_none(book):
    # S1.9.5: the basis PMI reads is the secured item's, while it is there to read.
    s, uid = book
    a = _account(s, uid, type="real-estate")
    home = Item(id=ids.new_id("Item"), accountId=a.id, name="House", acquiredOn=d(2026, 1, 1),
                costBasis=D(400000), closingCosts=D(5000))  # fmt: skip
    s.add(home)
    s.flush()
    row = Loan(id="Loan_x", accountId=a.id, principal=D(300000), startDate=d(2026, 1, 1),
               termMonths=360, rate=D(6), securedById=home.id)  # fmt: skip
    assert L.original_value(s, row) == D(405000)
    home.mark_deleted(uid)
    s.flush()
    assert L.original_value(s, row) is None
    assert L.original_value(s, dataclasses.replace(row, securedById="Item_gone")) is None


def test_the_terms_read_every_field_of_the_loan():
    # S1.9.1: the method and the payment as typed; no draw period read as none; a recast's
    # fee, when it has none, read as 0.
    row = Loan(id="Loan_x", accountId="Acct_x", principal=D(25000), startDate=d(2026, 1, 15),
               termMonths=60, rate=D("7.3"), method="daily", payment=D(500), drawMonths=None,
               resets='[{"date": "2027-01-15", "rate": "8"}]',
               recasts='[{"date": "2027-06-15", "fee": "250"}, {"date": "2028-06-15"}]',
               originalValue=D(30000))  # fmt: skip
    assert L.terms_of(None, row) == L.Terms(
        principal=D(25000), start=d(2026, 1, 15), months=60, rate=D("7.3"), method="daily",
        payment=D(500), drawMonths=0, resets=[(d(2027, 1, 15), D(8))],
        recasts=[(d(2027, 6, 15), D(250)), (d(2028, 6, 15), D(0))], originalValue=D(30000),
    )  # fmt: skip


def test_a_level_payment_with_no_months_left_is_the_balance_and_with_one_adds_its_interest():
    assert L.level_payment(D("1000.005"), D(12), 0) == D("1000.01")
    assert L.level_payment(D(1000), D(12), 1) == D("1010.00")


def test_automatic_reads_as_recorded_on_a_payment_of_any_amount_or_a_connection(book):
    """S1.9.3: Automatic is recorded here once the loan has a payment recorded, a few cents
    being one, or a connection importing its statements. A draw (money taken out) or a row of
    nothing is no payment: until one, every payment day before today is assumed."""
    s, uid = book
    today = d(2026, 10, 13)

    def after_march(a):
        return [p.assumed for p in L.history(s, a, today)[0] if p.date > d(2026, 3, 31)]

    a = _account(s, uid)
    row = _loan(s, a)
    _txn(s, a, d(2026, 3, 1), "-500.00")
    _txn(s, a, d(2026, 3, 1), "0.00")
    assert L.modes(s, a, row) == ("assumed", "assumed")
    assert after_march(a) == [True] * 7
    linked = dataclasses.replace(a, connectionId="Cnctn_x")
    assert L.modes(s, linked, row) == ("recorded", "recorded")
    # Fifty cents is a payment.
    paid = _txn(s, a, d(2026, 3, 2), "0.50")
    assert L.modes(s, a, row) == ("recorded", "recorded")
    pays = L.history(s, a, today)[0]
    assert after_march(a) == [] and paid.id in [p.transactionId for p in pays]


def test_without_terms_the_payments_are_read_whole_or_by_their_split_in_the_order_made(book):
    """S1.9.3: a loan whose terms aren't entered yet has its payments as recorded: wholly
    principal, or by the split they were given, each part by its category's (any other
    category, or none, is principal); in date order, and on one day in the order they were
    recorded. Money taken out is a draw."""
    s, uid = book
    a = _account(s, uid)
    at = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
    # Recorded out of order: the later of two on Mar 1 first, then one on Feb 1.
    second = _txn(s, a, d(2026, 3, 1), "300.00", createdAt=at + dt.timedelta(minutes=1))
    first = _txn(s, a, d(2026, 3, 1), "200.00", createdAt=at)
    feb = _txn(s, a, d(2026, 2, 1), "100.00", createdAt=at + dt.timedelta(minutes=2))
    draw = _txn(s, a, d(2026, 2, 10), "-50.00")
    split = _txn(s, a, d(2026, 4, 1), "2000.00")
    other = Category(id=ids.new_id("Cat"), name="Extra", kind="expense")
    s.add(other)
    s.flush()
    for key, amount in (("loans.interest", 1500), ("transfer.loan", 300),
                        ("housing.property-tax", 150), (other.id, 30), (None, 20)):  # fmt: skip
        cat = None if key is None else key if key == other.id else _category(s, key)
        s.add(Split(id=ids.new_id("Split"), transactionId=split.id, amount=D(amount),
                    categoryId=cat))  # fmt: skip
    s.flush()
    pays, draws = L.history(s, a, d(2026, 10, 13))
    whole = [L.Payment(t.date, t.amount, principal=t.amount, transactionId=t.id)
             for t in (feb, first, second)]  # fmt: skip
    parts = L.Payment(d(2026, 4, 1), D(2000), principal=D(350), interest=D(1500),
                      escrowTax=D(150), transactionId=split.id)  # fmt: skip
    assert pays == [*whole, parts]
    assert draws == [(draw.date, D(50))]


def test_recorded_here_a_late_payment_read_from_the_loan_pays_the_oldest_day_missed(book):
    """S1.9.3: Feb paid, March's paid late on Mar 25, after its grace: it pays March, so April's
    payment on Apr 1 pays April's own interest. Assumed as scheduled it would pay none."""
    s, uid = book
    a = _account(s, uid)
    _loan(s, a, paymentsMode="recorded")
    t = L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6))
    pi = L.scheduled_payment(t)
    days = (d(2026, 2, 1), d(2026, 3, 25), d(2026, 4, 1))
    made = [_txn(s, a, day, pi) for day in days]
    want: list[L.Payment] = []
    for day in days:
        want.append(L.split_for(t, want, [], day, pi, catch_up=True))
    pays, _ = L.history(s, a, d(2026, 4, 10))
    assert want[-1].interest > 0
    assert [(p.interest, p.principal) for p in pays] == [(p.interest, p.principal) for p in want]
    assert [p.transactionId for p in pays] == [t.id for t in made]


def test_settled_the_payments_are_in_date_order_and_on_one_day_as_recorded():
    t = L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6))
    recorded = [(d(2026, 3, 1), D(5000), "Txn_c"), (d(2026, 2, 1), D(2000), "Txn_a"),
                (d(2026, 2, 1), D(1000), "Txn_b")]  # fmt: skip
    out = L.settle(t, recorded, [], d(2026, 3, 10), None)
    assert [p.transactionId for p in out] == ["Txn_a", "Txn_b", "Txn_c"]
    # The first of the two on Feb 1 pays the day's interest.
    assert (out[0].interest, out[1].interest) == (D("1500.00"), 0)


def test_a_payment_day_on_today_is_not_yet_assumed():
    # S1.9.3: a day is assumed paid once it has passed; today it may still be paid.
    t = L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6))
    assert [p.date for p in L.settle(t, [], [], d(2026, 3, 1), d(2026, 3, 1))] == [d(2026, 2, 1)]


def test_settling_catches_up_a_late_payment_only_when_told_the_loan_is_recorded_here():
    """S1.9.3: Mar 25 is after March's grace. Recorded here it pays March, the oldest day missed,
    and Apr 1 pays April's interest; otherwise Mar 25 pays April, and Apr 1 pays none."""
    t = L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6))
    pi = L.scheduled_payment(t)
    recorded = [(day, pi, None) for day in (d(2026, 2, 1), d(2026, 3, 25), d(2026, 4, 1))]
    today, starts = d(2026, 4, 10), d(2026, 2, 1)
    assert L.settle(t, recorded, [], today, starts)[-1].interest == 0
    caught_up = L.settle(t, recorded, [], today, starts, catch_up=True)
    assert caught_up[-1].interest == L.cents((t.principal - caught_up[0].principal
                                              - caught_up[1].principal) / 200)  # fmt: skip


def test_recorded_here_a_payment_never_goes_back_to_a_month_before_the_record():
    """S1.9.3: a HELOC drawn on Apr 10, its record starting Jun 1. The days before are settled
    (May assumed; Feb to Apr had nothing owed), so a second payment in June's grace pays
    toward June, whose interest the first paid, not an undrawn month's."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=240, rate=D(8), drawMonths=120)
    draws = [(d(2026, 4, 10), D(30000))]
    recorded = [(d(2026, 6, 1), D(200), "Txn_a"), (d(2026, 6, 10), D(200), "Txn_b")]
    today = d(2026, 7, 10)
    starts = L.assumed_before(t, recorded, today, "recorded")
    out = L.settle(t, recorded, draws, today, starts, catch_up=True)
    assert [(p.date, p.assumed) for p in out] == [
        (d(2026, 5, 1), True), (d(2026, 6, 1), False), (d(2026, 6, 10), False)
    ]  # fmt: skip
    assert [(p.interest, p.principal) for p in out[1:]] == [(D("200.00"), 0), (0, D(200))]


# loans.day_of, _covered, _record_starts, _owed_before, _Walker, _walk, _as_scheduled, _due,
# balance_on, split_for


def _mortgage(**kw) -> L.Terms:
    return L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6), **kw)


def test_a_payment_on_the_15th_day_after_its_day_is_still_in_its_grace():
    # S1.9.3: a payment goes with the day whose grace it is made in, the 15th day after included.
    t = _mortgage()
    assert [L.day_of(t, x) for x in (d(2026, 2, 16), d(2026, 2, 17))] == [1, 2]


@pytest.mark.parametrize(
    ("today", "first"),
    [(d(2026, 2, 10), d(2026, 3, 1)), (d(2026, 3, 1), d(2026, 3, 1)),
     (d(2026, 3, 10), d(2026, 4, 1))],
)  # fmt: skip
def test_recorded_here_a_heloc_drawn_since_its_last_day_owes_from_the_next(today, first):
    """S1.9.3: a HELOC drawn five days ago, no payment recorded. The days passed (in their grace
    or not) had nothing owed, so nothing is missed and the schedule ahead starts at the first
    payment day after them: today's own, while it is today."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=240, rate=D(8), drawMonths=120)
    draws = [(today - dt.timedelta(days=5), D(10000))]
    rows = L.schedule(t, [], draws, today, mode="recorded")
    assert rows[0].date == first
    assert [r.status for r in rows[:2]] == ["ahead", "ahead"]


def test_recorded_here_a_second_payment_in_the_first_ones_grace_pays_toward_the_same_day():
    """S1.9.3: the record starts at the first payment recorded, Mar 25, which goes with April:
    the days before it are settled, so it never goes back to February or March. A second
    payment on Apr 1 pays toward April too, whose interest and principal the first paid: all
    of it is principal beyond the schedule."""
    t = _mortgage()
    pi = L.scheduled_payment(t)
    first = L.split_for(t, [], [], d(2026, 3, 25), pi, catch_up=True)
    second = L.split_for(t, [first], [], d(2026, 4, 1), pi, catch_up=True)
    assert (first.interest, second.interest) == (D("1500.00"), 0)
    assert second.principal == second.overpayment == pi


def test_owed_before_a_payment_day_counts_the_draws_to_the_day_before_and_the_balance_that_days():
    """S1.9.2: a HELOC whose repayment starts Mar 1, drawn on Feb 28 and again on Mar 1. Mar 1's
    interest and level payment are on what was owed the day before, 10,000, whether its payment
    is recorded or assumed; the balance on Mar 1 counts that day's draw."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    draws = [(d(2026, 2, 28), D(10000)), (d(2026, 3, 1), D(5000))]
    # Mar 1 is the first repayment day, the 2nd of 24: 23 payments left, that one counted.
    level = L.level_payment(D(10000), D(12), 23)
    paid = L.split_for(t, [], draws, d(2026, 3, 1), D(1000))
    assert (paid.interest, paid.principal) == (D("100.00"), D(900))
    assert paid.overpayment == 900 - (level - 100)
    [assumed] = L.settle(t, [], draws, d(2026, 3, 2), d(2026, 3, 2))
    assert (assumed.date, assumed.interest, assumed.principal) == (d(2026, 3, 1), 100, level - 100)
    assert L.balance_on(t, [], draws, d(2026, 3, 1)) == 15000


def test_a_payment_the_day_after_the_loan_starts_owes_a_months_interest_on_its_principal():
    # S1.9.3: from its start, the principal is owed; a payment the next day pays its interest.
    p = L.split_for(_mortgage(), [], [], d(2026, 1, 2), D(2000))
    assert (p.interest, p.principal) == (D("1500.00"), D(500))


def test_a_heloc_draw_in_its_repayment_period_works_the_payment_out_again():
    """S1.9.2: drawn 10,000 in the draw period and 5,000 more on Apr 10, in repayment: from May 1
    the level is what pays 15,000 off by the term's last day, May 1 the 4th of 24."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    draws = [(d(2026, 2, 10), D(10000)), (d(2026, 4, 10), D(5000))]
    level = L.level_payment(D(15000), D(12), 21)
    p = L.split_for(t, [], draws, d(2026, 5, 1), D(2000))
    assert (p.interest, p.overpayment) == (D("150.00"), 2000 - level)


def test_after_a_rate_reset_the_level_is_worked_out_from_what_was_owed_then():
    """S1.9.2: reset to 7% on Mar 15; from Apr 1 the level is what pays the balance owed before
    Apr 1 (the Feb and Mar payments' principal off) at 7% over the 358 payments left. A payment
    of 3,000 on Apr 1 is 7%'s interest, and beyond that level an overpayment."""
    t = _mortgage(resets=[(d(2026, 3, 15), D(7))])
    pi = L.scheduled_payment(t)
    recorded = [(d(2026, 2, 1), pi, "a"), (d(2026, 3, 1), pi, "b"), (d(2026, 4, 1), D(3000), "c")]
    out = L.settle(t, recorded, [], d(2026, 4, 10), None)
    owed = 300000 - out[0].principal - out[1].principal
    assert out[2].interest == L.cents(owed * 7 / 1200)
    assert out[2].overpayment == 3000 - L.level_payment(owed, D(7), 358)


def test_small_payments_toward_one_day_pay_its_interest_escrow_and_pmi_once():
    """S1.9.3: forty-one payments on Feb 1, of 70 but the last. Each pays what the earlier left
    of the day's interest, then tax, insurance and PMI, the one short of them in that order;
    the rest is principal. Each is split whole, and the parts come to what was due."""
    t = _mortgage(escrowTax=D(300), escrowInsurance=D(120), pmi=D(90))
    amounts = [D(70)] * 40 + [D("8.65")]
    out = L.settle(t, [(d(2026, 2, 1), a, None) for a in amounts], [], d(2026, 2, 10), None)

    def total(part):
        return sum(getattr(p, part) for p in out)

    parts = ("interest", "escrowTax", "escrowInsurance", "pmi", "principal", "fees")
    assert [total(x) for x in parts] == [1500, 300, 120, 90, D("798.65"), 0]
    assert all(sum(getattr(p, x) for x in parts) == p.total for p in out)


def test_principal_beyond_the_days_schedule_is_an_overpayment_across_its_payments():
    """S1.9.3: the first payment on Feb 1 pays the interest and 100 of the 298.65 principal due;
    three more pay 100, 100 and 500 of principal: 501.35 beyond the schedule, from the third."""
    t = _mortgage()
    amounts = [D(1600), D(100), D(100), D(500)]
    out = L.settle(t, [(d(2026, 2, 1), a, None) for a in amounts], [], d(2026, 2, 10), None)
    assert [p.overpayment for p in out] == [0, 0, D("1.35"), D(500)]


def test_an_assumed_payment_has_the_escrow_and_pmi_the_schedule_charges():
    # S1.9.3: assumed as scheduled, a payment day's payment is the schedule's whole.
    t = _mortgage(escrowTax=D(300), escrowInsurance=D(120), pmi=D(90))
    [p] = L.settle(t, [], [], d(2026, 2, 10), d(2026, 2, 10))
    assert (p.escrowTax, p.escrowInsurance, p.pmi) == (300, 120, 90)
    assert p.total == p.principal + p.interest + 300 + 120 + 90 == L.scheduled_payment(t) + 510


@pytest.mark.parametrize(
    ("months", "owed", "principal"),
    [(12, "0.50", "0.50"), (12, "100.50", "100.50"), (12, "101.00", "100"),
     (12, "101.50", "100"), (2, "500", "500")],
)  # fmt: skip
def test_an_assumed_payment_takes_a_balance_under_a_dollar_left_and_on_the_last_day_all(
    months, owed, principal
):
    """S1.9.2: at no interest and 100 a month, what an assumed payment on Mar 1 pays: the
    schedule's 100, all that is owed when that leaves under $1, and on the term's last day
    whatever is owed. Once it pays the loan off, it has no PMI."""
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=months, rate=D(0),
                payment=D(100), pmi=D(9))  # fmt: skip
    feb = L.Payment(d(2026, 2, 1), 1000 - D(owed), principal=1000 - D(owed))
    p = L.settle(t, [feb], [], d(2026, 3, 2), d(2026, 3, 2))[-1]
    assert (p.date, p.principal) == (d(2026, 3, 1), D(principal))
    assert p.pmi == (0 if p.principal == D(owed) else 9)


def test_recorded_here_the_schedule_reads_each_payment_as_toward_the_day_it_pays():
    """S1.9.3: March paid late on Mar 25 pays March, so Apr 1 pays April: no row is an
    overpayment. And a HELOC drawn Apr 10, its record starting Jun 1 (May assumed; nothing was
    owed before): Jun 10's payment is toward June, after Jun 1 paid its interest, so all its
    principal is beyond the schedule, never toward a month before the record."""
    t = _mortgage()
    pi = L.scheduled_payment(t)
    recorded = [(day, pi, None) for day in (d(2026, 2, 1), d(2026, 3, 25), d(2026, 4, 1))]
    rows = L.schedule(t, recorded, [], d(2026, 4, 10), mode="recorded")
    assert [(r.status, r.overpayment) for r in rows if r.past] == [("paid", 0)] * 3
    heloc = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(8), drawMonths=2)
    draws = [(d(2026, 4, 10), D(30000))]
    level = L.level_payment(D(30000), D(8), 21)
    recorded = [(d(2026, 6, 1), level, "a"), (d(2026, 6, 10), D(200), "b")]
    rows = L.schedule(heloc, recorded, draws, d(2026, 7, 10), mode="recorded")
    assert [(r.date, r.overpayment) for r in rows if r.past][1:] == [
        (d(2026, 6, 1), 0), (d(2026, 6, 10), D(200))
    ]  # fmt: skip


def test_what_a_payment_brings_beyond_the_balance_and_the_days_dues_is_fees():
    # S1.9.3: a payment of 1,500 on a loan of 1,000: 10 interest, 1,000 principal, 490 fees.
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(12))
    p = L.split_for(t, [], [], d(2026, 2, 1), D(1500))
    assert (p.interest, p.principal, p.fees) == (D("10.00"), D(1000), D(490))


# loans.paid_off, _effects, _level_at, schedule


def test_a_loan_is_paid_off_on_the_first_day_in_date_order_that_leaves_nothing_owed():
    # S1.9.5: the payoff date is the payment's that left nothing owed, read in date order and
    # each from the balance on its own day.
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(0))
    paid = [L.Payment(day, D(x), principal=D(x)) for day, x in
            [(d(2026, 4, 1), 50), (d(2026, 3, 1), 600), (d(2026, 2, 1), 400)]]  # fmt: skip
    assert L.paid_off(t, paid, []) == d(2026, 3, 1)
    assert L.paid_off(t, paid[:2], []) is None


def test_a_reset_in_the_first_month_or_the_last_works_out_the_next_payment_days_level():
    """S1.9.2: a reset on Jan 15 sets Feb 1's level at its rate over all 360 payments; one on
    the 12-month loan's last month sets the last day's, that day counted: all that is owed,
    with its interest."""
    t = _mortgage(resets=[(d(2026, 1, 15), D(7))])
    assert L.due_on(t, [], [], d(2026, 2, 1), t.start)[0] == L.level_payment(D(300000), D(7), 360)
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(12),
                resets=[(d(2026, 12, 15), D(12))])  # fmt: skip
    assert L.due_on(t, [], [], d(2027, 1, 1), d(2026, 12, 1))[0] == D("1010.00")


def test_a_charge_added_to_a_mortgage_leaves_its_level_payment():
    # S1.9.2: only a HELOC's draw in its repayment period works the level out again.
    t = _mortgage()
    pi, _ = L.due_on(t, [], [(d(2026, 3, 10), D(1000))], d(2026, 4, 1), d(2026, 3, 1))
    assert pi == L.scheduled_payment(t)


def test_assumed_as_scheduled_the_days_after_a_payment_recorded_are_assumed_until_today():
    # S1.9.3: a payment recorded doesn't start a record: each day with none recorded is paid.
    t = _mortgage()
    rows = L.schedule(t, [(d(2026, 2, 1), L.scheduled_payment(t), "a")], [], d(2026, 6, 10))
    assert [r.status for r in rows if r.past] == ["paid"] + ["assumed"] * 4


def test_recorded_here_the_schedule_splits_and_reads_a_late_payment_as_paying_the_day_missed():
    """S1.9.3: March missed, Apr 1's payment pays it, so Apr 10's pays April: each owes its own
    day's interest, and none is an overpayment; nothing is missed."""
    t = _mortgage()
    pi = L.scheduled_payment(t)
    recorded = [(day, pi, None) for day in (d(2026, 2, 1), d(2026, 4, 1), d(2026, 4, 10))]
    rows = L.schedule(t, recorded, [], d(2026, 4, 20), mode="recorded")
    past = [(r.status, r.interest, r.overpayment) for r in rows if r.past]
    assert past == [("paid", D(x), 0) for x in ("1500.00", "1498.51", "1497.01")]


def test_assumed_as_scheduled_a_payment_ahead_never_goes_back_to_a_day_before_its_own():
    """S1.9.3: only recorded here does a payment pay the oldest day missed. Payments dated
    Jun 20 and Jun 25 both go with July, so the second, 500, is all an overpayment."""
    t = _mortgage()
    pi = L.scheduled_payment(t)
    recorded = [(d(2026, 4, 1), pi, "a"), (d(2026, 6, 20), pi, "b"), (d(2026, 6, 25), D(500), "c")]
    rows = L.schedule(t, recorded, [], d(2026, 4, 10))
    assert [r.overpayment for r in rows if r.past][-2:] == [0, D(500)]


def test_the_schedules_rows_show_an_overpayment_only_past_the_days_principal_due():
    # S1.9.3: the day's 298.65 of principal is due across its payments: the third's 500 of
    # principal is 401.35 beyond what the first two left of it.
    t = _mortgage()
    recorded = [(d(2026, 2, 1), D(x), None) for x in (1600, 100, 500)]
    rows = L.schedule(t, recorded, [], d(2026, 2, 10), mode="recorded")
    assert [r.overpayment for r in rows if r.past] == [0, 0, D("401.35")]


def test_each_row_passed_has_its_escrow_and_the_balance_on_its_own_day():
    # S1.9.2: each payment's escrow (tax and insurance) and the balance it left.
    t = _mortgage(escrowTax=D(300), escrowInsurance=D(120))
    rows = [r for r in L.schedule(t, [], [], d(2026, 4, 10)) if r.past]
    assert [r.escrow for r in rows] == [420] * 3
    principal = [r.principal for r in rows]
    assert [r.balance for r in rows] == [300000 - sum(principal[: i + 1]) for i in range(3)]


def test_a_helocs_draw_period_ahead_pays_interest_only():
    # S1.9.1: in the draw period the payments are interest only.
    t = L.Terms(principal=D(10000), start=d(2026, 1, 1), months=240, rate=D(8), drawMonths=120)
    row = L.schedule(t, [], [], d(2026, 1, 10))[0]
    assert (row.principal, row.interest, row.payment) == (0, D("66.67"), D("66.67"))


def test_ahead_a_helocs_level_is_worked_out_again_the_day_after_a_draw_in_repayment():
    """S1.9.2: repayment starts Mar 1 on the 10,000 drawn, and Mar 1 is paid. Drawn 5,000 more
    on Apr 3, the level stays what Mar 1 set for Apr 1 (in its grace, today Apr 10), and from
    May 1 is what pays the balance then owed off over the 21 payments left."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    level = L.level_payment(D(10000), D(12), 23)
    draws = [(d(2026, 2, 10), D(10000)), (d(2026, 4, 3), D(5000))]
    rows = L.schedule(t, [(d(2026, 3, 1), level, "a")], draws, d(2026, 4, 10), mode="recorded")
    apr, may = [r for r in rows if not r.past][:2]
    assert (apr.date, apr.principal + apr.interest) == (d(2026, 4, 1), level)
    assert may.principal + may.interest == L.level_payment(apr.balance, D(12), 21)


def test_ahead_the_level_set_by_a_reset_is_from_what_was_owed_the_day_before_it_took_effect():
    """S1.9.2: reset to 7% on Feb 15, so Mar 1 sets the level, from what was owed on Feb 28: a
    charge of 100 that day counted, one of 1,000 on Mar 2 not. Apr 1, ahead, keeps it."""
    t = _mortgage(resets=[(d(2026, 2, 15), D(7))])
    draws = [(d(2026, 2, 28), D(100)), (d(2026, 3, 2), D(1000))]
    rows = L.schedule(t, [], draws, d(2026, 3, 10))
    feb, mar, apr = rows[:3]
    level = L.level_payment(feb.balance + 100, D(7), 359)
    assert (mar.date, apr.date) == (d(2026, 3, 1), d(2026, 4, 1))
    assert mar.principal + mar.interest == apr.principal + apr.interest == level


def test_whatever_is_owed_long_after_the_terms_end_is_due_whole_on_the_next_payment_day():
    # S1.9.2: a charge on a loan whose term ended decades ago is paid by its next payment day.
    t = L.Terms(principal=D(500), start=d(1970, 1, 1), months=1, rate=D(6))
    rows = L.schedule(t, [], [(d(2025, 12, 1), D(1000))], d(2026, 1, 1))
    assert [(r.date, r.principal, r.status) for r in rows] == [
        (d(1970, 2, 1), 500, "assumed"), (d(2026, 1, 1), 1000, "ahead")
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("payment", "rows"),
    [("999.50", [("1000", 0)]), ("999", [("999", 9), ("1", 0)]),
     ("998.50", [("998.50", 9), ("1.50", 0)])],
)  # fmt: skip
def test_ahead_a_balance_under_a_dollar_left_goes_with_the_payment_and_pmi_ends_with_it(
    payment, rows
):
    """S1.9.2, S1.9.5: at no interest, the first payment ahead leaves 0.50, 1.00 or 1.50 of the
    1,000 owed. Under $1 goes with it, and nothing is owed so it has no PMI; a dollar or more
    is the next payment's, and PMI is due while it is owed."""
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(0),
                payment=D(payment), pmi=D(9))  # fmt: skip
    ahead = L.schedule(t, [], [], d(2026, 1, 10))
    assert [(r.principal, r.pmi) for r in ahead] == [(D(p), pmi) for p, pmi in rows]


# loans.due_on, _missed, summary, split_new, payoff.plan_outcomes, payoff.expected_extra


def test_a_day_passed_has_due_a_months_interest_on_what_its_payments_before_left():
    """S1.9.2, S1.9.5: on Mar 1, what was owed the day before (a payment on Feb 28 counted, one
    on Mar 1 not): 299,000, so 1,495 of interest, and the scheduled payment leaves 299,000 less
    the principal it pays beyond that."""
    t = _mortgage()
    pays = [L.Payment(d(2026, 2, 28), D(1000), principal=D(1000)),
            L.Payment(d(2026, 3, 1), D(500), principal=D(500))]  # fmt: skip
    pi = L.scheduled_payment(t)
    assert L.due_on(t, pays, [], d(2026, 3, 1), d(2026, 2, 1)) == (pi, 299000 - (pi - 1495))


def test_a_daily_interest_day_passed_has_due_the_days_since_the_payment_day_before():
    # S1.9.1: simple interest between payment days: 31 days of 6% on 20,000, 101.92, of 365.
    t = L.Terms(principal=D(20000), start=d(2026, 1, 1), months=60, rate=D(6), method="daily")
    pi = L.scheduled_payment(t)
    assert L.due_on(t, [], [], d(2026, 2, 1), t.start) == (pi, 20000 - (pi - D("101.92")))


def test_a_helocs_day_passed_has_the_level_a_draw_in_repayment_set():
    """S1.9.2: drawn 10,000 in the draw period and 5,000 more on Apr 10, in repayment: May 1's
    level pays 15,000 off over the 21 payments left, and its interest is a month's on it."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    draws = [(d(2026, 2, 10), D(10000)), (d(2026, 4, 10), D(5000))]
    level = L.level_payment(D(15000), D(12), 21)
    assert L.due_on(t, [], draws, d(2026, 5, 1), d(2026, 4, 1)) == (level, 15000 - (level - 150))


def test_recorded_here_nothing_is_missed_on_the_day_the_loan_starts():
    # S1.9.3: the first payment day is a month after the start, even with a draw before it.
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=12)
    rows = L.schedule(t, [], [(d(2025, 12, 20), D(1000))], d(2026, 3, 1), mode="recorded")
    assert [(r.date, r.status) for r in rows[:2]] == [
        (d(2026, 2, 1), "assumed"), (d(2026, 3, 1), "ahead")
    ]  # fmt: skip


def test_recorded_here_a_day_missed_after_one_with_nothing_owed_has_its_own_days_balance():
    """S1.9.3: a HELOC paid off on Feb 1 owes nothing on Mar 1, so that day is not missed; drawn
    again on Mar 10, Apr 1 is, with the 2,000 owed that day (Apr 10's draw not yet)."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=12)
    draws = [(d(2026, 1, 10), D(1000)), (d(2026, 3, 10), D(2000)), (d(2026, 4, 10), D(500))]
    rows = L.schedule(t, [(d(2026, 2, 1), D(1010), "a")], draws, d(2026, 5, 1), mode="recorded")
    missed = [(r.date, r.interest, r.balance) for r in rows if r.status == "missed"]
    assert missed == [(d(2026, 4, 1), 20, 2000)]


def test_the_balance_today_leaves_out_a_draw_dated_after_today():
    # S1.9.2: what is owed today counts what was drawn to today.
    t = _mortgage()
    sm, _ = _summed(t, [], [(d(2026, 1, 25), D(1000))], d(2026, 1, 20))
    assert sm.balance == 300000


def test_a_heloc_is_interest_only_until_its_draw_period_ends_while_its_next_day_is_in_it():
    # S1.9.1: the summary says when the draw period ends only while the payment due is in it.
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    draws = [(d(2026, 1, 10), D(10000))]
    during, _ = _summed(t, [], draws, d(2026, 1, 20))
    after, _ = _summed(t, [], draws, d(2026, 2, 20))
    assert (during.interestOnlyUntil, after.interestOnlyUntil) == (d(2026, 3, 1), None)


def test_a_loan_paid_off_has_its_payoff_on_the_payment_that_left_nothing_and_amounts_in_decimals():
    """S1.9.5, R1.9: paid off on Feb 1, nothing is ahead: the payoff date is that payment's,
    and every amount, an empty sum too, is a Decimal. A new loan has nothing paid or missed,
    each a Decimal 0 as well; its original payoff is the term's end."""
    t = L.Terms(principal=D(1000), start=d(2026, 1, 1), months=12, rate=D(0))
    done, _ = _summed(t, [(d(2026, 2, 1), D(1000), "a")], [], d(2026, 3, 10))
    assert (done.payoffDate, done.nextDate, done.originalPayoff) == (d(2026, 2, 1), None, t.end)
    fresh, _ = _summed(_mortgage(), [], [], d(2026, 1, 10))
    for sm in (done, fresh):
        sums = (sm.interestPaid, sm.interestAhead, sm.principalThisYear, sm.overpaid, sm.overdue)
        assert all(type(x) is D for x in sums)
    assert (fresh.interestPaid, fresh.overdue) == (0, 0)


def test_the_principal_paid_this_year_leaves_out_last_years():
    # S1.9.2: Dec 1's payment is last year's; Jan 1's alone is this year's.
    t = _mortgage()
    pi = L.scheduled_payment(t)
    recorded = [(d(2026, 12, 1), pi, "a"), (d(2027, 1, 1), pi, "b")]
    sm, rows = _summed(t, recorded, [], d(2027, 1, 10))
    jan = next(r for r in rows if r.date == d(2027, 1, 1))
    assert sm.principalThisYear == jan.principal


def test_a_payment_about_to_be_recorded_catches_up_only_when_told_the_loan_is_recorded_here():
    """S1.9.3: March missed and paid on Apr 1, recorded here; a payment on Apr 10 pays April,
    with its own month's interest. Not told (assumed as scheduled), Apr 1 paid April, so the
    new one pays no interest and is all principal beyond it."""
    t = _mortgage()
    pi = L.scheduled_payment(t)
    recorded = [(d(2026, 2, 1), pi, "a"), (d(2026, 4, 1), pi, "b")]
    prior = L.settle(t, recorded, [], d(2026, 4, 10), None, catch_up=True)
    caught = L.split_new(t, prior, [], d(2026, 4, 10), pi, True)
    plain = L.split_new(t, prior, [], d(2026, 4, 10), pi)
    assert (caught.interest, caught.overpayment) == (D("1497.01"), 0)
    assert (plain.interest, plain.overpayment) == (0, pi)


def test_recorded_here_the_payoff_plans_schedules_have_the_days_missed():
    """S6.10, S1.9.3: the schedule, the plan and its recast read the loan's Payments setting:
    recorded here, Feb 1 paid and March to June missed, the next payment day Jul 1."""
    t = _mortgage()
    plan = P.Plan(lumps=[(d(2026, 8, 1), D(10000))], recast=True)
    r = P.plan_outcomes(t, [(d(2026, 2, 1), L.scheduled_payment(t), "a")], [], d(2026, 6, 20),
                        plan, 7.0, "recorded")  # fmt: skip
    for o in (r.schedule, r.plan, r.recast):
        assert [x.status for x in o.rows if x.past] == ["paid"] + ["missed"] * 4
        assert next(x.date for x in o.rows if not x.past) == d(2026, 7, 1)


@pytest.mark.parametrize(("value", "extra"), [(D(128100), D("0.45")), (D(127500), D("50.45"))])
def test_a_plans_round_up_counts_pmi_by_the_balance_a_daily_interest_day_left(value, extra):
    """S6.10.5, S1.9.5: 6% daily on 100,000; Feb 1's scheduled payment of 599.55, with 31 days'
    interest (509.59), leaves 99,910.04. PMI of 50 is due while that is above 78% of the home's
    value: 99,918 for 128,100, so none and 600 rounds up by 0.45; 99,450 for 127,500, so 649.55
    by 50.45."""
    t = L.Terms(principal=D(100000), start=d(2026, 1, 1), months=360, rate=D(6), method="daily",
                pmi=D(50), originalValue=value)  # fmt: skip
    assert P.expected_extra(t, P.Plan(roundTo=D(100)), t.start, d(2026, 2, 10), [], []) == extra


# loans.history, _owed_before, _Walker.add, schedule, _missed: the rules at a payment's edges


def test_a_row_of_nothing_is_no_payment(book):
    """S1.9.3: a row of 0.00 pays nothing, so it is no payment: assumed as scheduled, its
    payment day is assumed like any with none recorded."""
    s, uid = book
    a = _account(s, uid)
    _loan(s, a)
    _txn(s, a, d(2026, 3, 1), "0.00")
    pays = L.history(s, a, d(2026, 10, 13))[0]
    assert [p.date.month for p in pays if p.assumed] == list(range(2, 11))
    assert all(p.transactionId is None for p in pays)


def test_a_first_payment_short_of_the_interest_leaves_the_days_principal_as_scheduled():
    """S1.9.3: Feb 1 is due 1,500 of interest and 298.65 of principal; 2,298.65 paid toward it
    overpays 500 however it is split up."""
    t = _mortgage()
    for first, second in ((D(1500), D("798.65")), (D(1000), D("1298.65"))):
        rec = [(d(2026, 2, 1), first, None), (d(2026, 2, 1), second, None)]
        out = L.settle(t, rec, [], d(2026, 2, 10), None)
        assert [p.overpayment for p in out] == [0, D(500)]


def test_a_second_payment_toward_a_day_ahead_is_an_overpayment_in_the_schedule_too():
    """S1.9.3: recorded here, the record starts at the first payment recorded, dated after
    today or not: the days before it count as paid as scheduled, and Apr 5's 500 is principal
    beyond Apr 1's, in its split and on its row."""
    t = _mortgage()
    rec = [(d(2026, 4, 1), L.scheduled_payment(t), "a"), (d(2026, 4, 5), D(500), "b")]
    rows = L.schedule(t, rec, [], d(2026, 2, 10), mode="recorded")
    assert [r.status for r in rows if r.past] == ["assumed", "assumed", "paid", "paid"]
    assert [r.overpayment for r in rows if r.status == "paid"] == [0, D(500)]


def test_ahead_the_balance_counts_a_payment_dated_ahead_whose_day_it_paid():
    """S1.9.2: the first row ahead starts from what the last day paid left, a payment dated
    after today counted: Mar 1 leaves 299,401.21, so Apr 1 pays 301.64 and leaves 299,099.57."""
    t = _mortgage()
    rows = L.schedule(t, [(d(2026, 3, 1), L.scheduled_payment(t), "a")], [], d(2026, 2, 10))
    mar, apr = rows[1:3]
    assert (mar.past, apr.past) == (True, False)
    assert (apr.principal, apr.balance) == (D("301.64"), D("299099.57"))


def test_ahead_a_day_in_its_grace_that_re_levels_has_the_level_its_payment_is_split_by():
    """S1.9.2: a day that works the level out again levels the balance then owed. Apr 1, in its
    grace on Apr 10, levels the 10,611.14 owed on Mar 31 over 22 payments; the 5,000 drawn on
    Apr 3 is owed with its interest, and levelled from May 1, the next such day. The row is the
    split of its payment made now."""
    t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
    level = L.level_payment(D(10000), D(12), 23)
    draws = [(d(2026, 2, 10), D(10000)), (d(2026, 3, 20), D(1000)), (d(2026, 4, 3), D(5000))]
    recorded = [(d(2026, 3, 1), level, "a")]
    rows = L.schedule(t, recorded, draws, d(2026, 4, 10), mode="recorded")
    apr, may = [r for r in rows if not r.past][:2]
    assert apr.date == d(2026, 4, 1)
    assert apr.principal + apr.interest == L.level_payment(D("10611.14"), D(12), 22)
    paid = L.settle(t, recorded, draws, d(2026, 4, 10), None, True)
    split = L.split_for(t, paid, draws, d(2026, 4, 12), apr.payment, True)
    assert (split.interest, split.principal, split.overpayment) == (apr.interest, apr.principal, 0)
    assert may.principal + may.interest == L.level_payment(apr.balance, D(12), 21)


def _daily(**kw) -> L.Terms:
    return L.Terms(principal=D(20000), start=d(2026, 1, 1), months=60, rate=D(6), method="daily",
                   **kw)  # fmt: skip


@pytest.mark.parametrize("today", [d(2026, 4, 1), d(2026, 4, 20)])
def test_a_daily_interest_day_accrues_from_a_catch_up_payment_made_that_day(today):
    """S1.9.1: daily interest accrues between payments. March missed, Apr 1's payment pays it
    and the interest to Apr 1, so April's own row, ahead on Apr 1 or missed by Apr 20, has no
    days left to accrue."""
    t = _daily()
    pi = L.scheduled_payment(t)
    recorded = [(d(2026, 2, 1), pi, "a"), (d(2026, 4, 1), pi, "b")]
    rows = L.schedule(t, recorded, [], today, mode="recorded")
    [apr] = [r for r in rows if r.date == d(2026, 4, 1) and r.status != "paid"]
    assert apr.interest == 0


@pytest.mark.parametrize(("amount", "split"), [
    (D(500), (D(500), 0, 0)),
    (D("2298.65"), (D(1500), D("798.65"), D(500))),
])  # fmt: skip
def test_a_payment_on_the_day_the_loan_starts_goes_toward_its_first_payment_day(amount, split):
    """S1.9.3: a payment goes with the payment day whose grace it is made in, the first one's
    from the start day: on Jan 1 as on Jan 2, it owes Feb 1's month of interest on the
    principal lent that day, then the rest is principal, beyond the 298.65 due an overpayment."""
    p = L.split_for(_mortgage(), [], [], d(2026, 1, 1), amount)
    assert (p.interest, p.principal, p.overpayment) == split
    assert p.fees == 0
