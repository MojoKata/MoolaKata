"""Loans' routes and the screen they answer with (requirements S1.9): who may read or change a
loan, the screen's every field read from the terms, the schedule and the servicer's balance,
and the equity of what it is secured by, each pinned on the case that tells it apart."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import make, saved, share, terms
from sqlalchemy import select
from test_accounts import new_account

from moolakata import assets, clock, ids
from moolakata.store.entities.accounts import Account, Anchor, Category, Loan
from moolakata.store.entities.assets import Item
from moolakata.store.entities.prices import TypedPrice
from moolakata.store.entities.users import User
from moolakata.ui import loans as UL

d = dt.date
T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def book(server, frozen):
    """A session on the test household, unscoped as the server's own work reads it, and the
    first admin's id to own what a test adds; nothing it adds is kept."""
    with server.db.tx(unscoped="test") as s:
        yield s, s.scalars(select(User.id)).first()
        s.rollback()


def _account(s, uid, type="mortgage", name="Home") -> Account:
    a = Account(id=ids.new_id("Acct"), ownerId=uid, name=name, type=type)
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


def _item(s, a, **kw) -> Item:
    kw = {"name": "House", "acquiredOn": d(2025, 6, 1), "costBasis": D(400000), **kw}
    it = Item(id=ids.new_id("Item"), accountId=a.id, **kw)
    s.add(it)
    s.flush()
    return it


def _anchor(s, a, day, balance, source="typed") -> Anchor:
    x = Anchor(id=ids.new_id("Anchr"), accountId=a.id, date=day, balance=D(balance), source=source)
    s.add(x)
    s.flush()
    return x


# ui.loans._account, _terms_out, view, _equity


def test_a_loans_screen_is_refused_on_an_account_that_is_not_a_loan(server, frozen):
    # S1.9: only a loan account carries terms; the refusal says so in its code and words.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    bank = new_account(c, name="Checking")
    r = c.get(f"/ui/api/accounts/{bank['id']}/loan")
    body = r.json()
    assert (r.status_code, body["code"], body["detail"]) == (
        409,
        "not-a-loan",
        "This account is not a loan.",
    )


def test_a_reader_of_a_shared_loan_reads_it_but_cannot_follow_its_plans(server, frozen):
    # S10.4: a loan shared at Read is read, never changed: following a plan changes the loan's
    # plans, so it needs Write.
    make_user(server, "jane")
    john = make_user(server, "john")
    jane = sign_in(server, "jane")
    loan = new_account(jane, name="Home", type="mortgage")
    saved(terms(jane, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    plan = make(jane, "Pyoff", accountId=loan["id"], name="Extra", inputs={"monthly": "300"})
    assert plan.status_code == 200, plan.text
    saved(share(jane, "account", loan["id"], users={john.id: "read"}))
    jc = sign_in(server, "john")
    assert jc.get(f"/ui/api/accounts/{loan['id']}/loan").status_code == 200
    r = jc.post(
        f"/ui/api/accounts/{loan['id']}/loan/plans/{plan.json()['id']}/follow",
        json={"following": True},
    )
    assert (r.status_code, r.json()["code"]) == (403, "share-read-only"), r.text


def test_a_loan_without_terms_shows_nothing_owed(book):
    # S1.9: until its terms are set, a loan's screen has no balance, payment or schedule.
    s, uid = book
    v = UL.view(s, _account(s, uid))
    amounts = (v.balance, v.rate, v.payment, v.total, v.interestPaid, v.interestAhead,
               v.principalThisYear, v.overpaid, v.overdue)  # fmt: skip
    assert all(x == 0 for x in amounts) and v.missed == 0
    assert (v.terms, v.rows, v.servicer, v.version) == (None, [], None, 0)


def test_the_terms_read_back_as_they_were_set(book):
    # S1.9.1, S1.9.7: every term the dialog sets is on the screen's terms, a recast with its
    # day and fee.
    s, uid = book
    a = _account(s, uid)
    home = _item(s, _account(s, uid, type="real-estate"))
    cat = s.scalars(select(Category.id).where(Category.kind != "transfer")).first()
    row = _loan(s, a, payment=D("2100.00"), escrowTax=D(300), escrowInsurance=D(100), pmi=D(90),
                drawMonths=12, recasts='[{"date": "2026-06-15", "fee": "250"}]',
                originalValue=D(380000), securedById=home.id, budgetCounting="whole",
                budgetCategoryId=cat)  # fmt: skip
    t = UL.view(s, a).terms
    assert (t.payment, t.escrowTax, t.escrowInsurance, t.pmi, t.drawMonths) == (
        D("2100.00"),
        300,
        100,
        90,
        12,
    )
    assert [(r.date, r.fee) for r in t.recasts] == [(d(2026, 6, 15), 250)]
    assert (t.originalValue, t.securedById, t.budgetCategoryId) == (380000, home.id, cat)
    assert t.id == row.id


def test_the_screen_has_the_terms_version_and_the_payoff_dates(book):
    # S13.8.6: the screen carries the terms' version, for the next change to name; S1.9.5:
    # the payoff date and the one the terms first gave.
    s, uid = book
    a = _account(s, uid)
    row = _loan(s, a, rate=D(5))
    row.rate = D(6)  # changed once: its second version
    s.flush()
    v = UL.view(s, a)
    assert (v.version, v.terms.version) == (2, 2)
    assert (v.payoffDate, v.originalPayoff) == (d(2056, 1, 1), d(2056, 1, 1))


def test_the_servicers_balance_is_the_latest_typed_on_this_loan_owed_as_a_positive_amount(book):
    # S1.9.4: the balance typed from the servicer's statement, the latest of them: not one a
    # file reported, nor one on another account. A loan's balance is kept as minus what is
    # owed; the check reads what is owed.
    s, uid = book
    a = _account(s, uid)
    _loan(s, a)
    _anchor(s, a, d(2026, 3, 1), "-299500.00")  # older, kept first
    _anchor(s, a, d(2026, 6, 1), "-298000.00")
    _anchor(s, a, d(2026, 8, 1), "-1.00", source="ofx")
    _anchor(s, _account(s, uid, name="Car"), d(2026, 9, 1), "-2.00")
    sv = UL.view(s, a).servicer
    assert (sv.date, sv.servicer) == (d(2026, 6, 1), D("298000.00"))
    assert sv.difference == sv.servicer - sv.computed and sv.computed > 298000


def test_equity_is_none_once_the_home_is_deleted(book):
    # S1.9.5: equity is shown for what the loan is secured by while it is there.
    s, uid = book
    a = _account(s, uid)
    home = _item(s, _account(s, uid, type="real-estate"))
    _loan(s, a, securedById=home.id)
    assert UL.view(s, a).equity is not None
    home.mark_deleted(uid)
    s.flush()
    assert UL.view(s, a).equity is None


def test_equity_counts_every_live_loan_on_the_home_at_what_it_owes_today(book):
    # S1.9.5: the equity is the value less what every loan secured by the home owes: a second
    # loan on it counts, one on another item doesn't, and one not started yet owes nothing
    # today. The loan-to-value is this loan's alone.
    s, uid = book
    homes = _account(s, uid, type="real-estate")
    home = _item(s, homes, costBasis=D(500000))
    cabin = _item(s, homes, name="Cabin")
    a = _account(s, uid)
    _loan(s, a, securedById=home.id)
    second = _account(s, uid, name="Second")
    _loan(s, second, principal=D(50000), termMonths=120, securedById=home.id)
    later = _account(s, uid, name="Later")
    _loan(s, later, principal=D(20000), startDate=d(2026, 12, 1), securedById=home.id)
    elsewhere = _account(s, uid, name="Cabin loan")
    _loan(s, elsewhere, principal=D(70000), securedById=cabin.id)
    # Each assumed paid as scheduled to Oct 1: this one owes 297,257.77, the second 47,198.53.
    e = UL.view(s, a).equity
    assert (e.value, e.owed, e.equity) == (500000, D("344456.30"), D("155543.70"))
    assert e.ltv == D("59.5")


def test_equity_of_metal_is_its_value_at_spot(book):
    # S1.9.5, S1.10.2: what the loan is secured by is valued as its own screen values it;
    # metal at spot, not at its basis.
    s, uid = book
    vault = _account(s, uid, type="precious-metals")
    gold = _item(s, vault, name="Bars", costBasis=D(1000), valuation="spot", metal="gold",
                 unitWeight=D(10), weightUnit="ozt", purity=D(1))  # fmt: skip
    inst = assets.metal_instrument(s, "gold")
    s.add(TypedPrice(instrumentId=inst.id, userId=uid, date=d(2026, 10, 1), close=D(2000)))
    s.flush()
    a = _account(s, uid, type="personal-loan")
    _loan(s, a, principal=D(5000), termMonths=24, securedById=gold.id)
    assert UL.view(s, a).equity.value == D(20000)


def test_a_home_worth_nothing_has_a_loan_to_value_of_zero(book):
    # S1.9.5: a home sold is worth nothing; the loan-to-value is 0, not a division by zero.
    s, uid = book
    home = _item(s, _account(s, uid, type="real-estate"), soldOn=d(2026, 9, 1),
                 proceeds=D(450000))  # fmt: skip
    a = _account(s, uid)
    _loan(s, a, securedById=home.id)
    e = UL.view(s, a).equity
    assert (e.value, e.ltv) == (0, 0) and e.equity == -e.owed


def test_without_pmi_there_is_no_day_it_can_be_dropped(book):
    # S1.9.5: when PMI can be dropped is shown for a loan that charges it.
    s, uid = book
    home = _item(s, _account(s, uid, type="real-estate"))
    a = _account(s, uid)
    _loan(s, a, originalValue=D(400000), securedById=home.id)
    e = UL.view(s, a).equity
    assert (e.pmiRequest, e.pmiEnds) == (None, None)


@pytest.mark.parametrize(
    ("original", "field", "day"),
    [
        # 80% of 372,347.30 is 297,877.84, the balance after Aug 1, 2026's payment.
        ("372347.30", "pmiRequest", d(2026, 8, 1)),
        # 78% of 368,635.50 is 287,535.69, the balance after Mar 1, 2029's payment.
        ("368635.50", "pmiEnds", d(2029, 3, 1)),
    ],
)
def test_pmi_can_be_dropped_on_the_day_the_balance_reaches_its_share_of_the_value(
    book, original, field, day
):
    # S1.9.5: on request at 80% of the original value, by itself at 78%: the day the balance
    # is that share, exactly, counts.
    s, uid = book
    home = _item(s, _account(s, uid, type="real-estate"))
    a = _account(s, uid)
    _loan(s, a, pmi=D(90), originalValue=D(original), securedById=home.id)
    assert getattr(UL.view(s, a).equity, field) == day
