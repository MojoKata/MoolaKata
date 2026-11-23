"""Loans (requirements S1.9): the rules at their edges, each pinned on the bound that tells it
apart: a day exactly on a reset or today, an amount under a cent or a dollar, a row left out."""

import dataclasses
import datetime as dt
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from moolakata import ids
from moolakata import loans as L
from moolakata.store.entities.accounts import Account, Category, Loan, Split, Transaction
from moolakata.store.entities.assets import Item
from moolakata.store.entities.users import User

d = dt.date


@pytest.fixture
def book(server):
    """A session on the test household, unscoped as the server's own work reads it, and the
    first admin's id to own what a test adds; nothing it adds is kept."""
    with server.db.tx(unscoped="test") as s:
        yield s, s.scalars(select(User.id)).first()
        s.rollback()


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
