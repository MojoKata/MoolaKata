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
from moolakata.errors import FieldError, Problem
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


# ui.loans._check


def _body(**kw) -> UL.TermsIn:
    kw = {"principal": D(1000), "startDate": d(2026, 1, 1), "termMonths": 12, "rate": D(6), **kw}
    return UL.TermsIn(**kw)


def _refused(field, code, message) -> list[FieldError]:
    return [FieldError(field, code, message)]


TERM = _refused("termMonths", "term-invalid", "Between 1 and 600 months.")
RATE = _refused("rate", "rate-invalid", "Between 0% and 40%.")


@pytest.mark.parametrize(("months", "refusal"), [(0, TERM), (1, []), (600, []), (601, TERM)])
def test_a_term_is_1_to_600_months_both_kept(months, refusal):
    # S1.9.1, R3.11: the term's bounds are kept; one month past either is refused at its field.
    assert UL._check(_body(termMonths=months), "auto-loan") == refusal


@pytest.mark.parametrize(
    ("rate", "refusal"), [("-0.001", RATE), ("0", []), ("40", []), ("40.001", RATE)]
)
def test_a_rate_is_0_to_40_percent_both_kept(rate, refusal):
    # S1.9.1, R3.11: to three places, the smallest step past 40% is refused.
    assert UL._check(_body(rate=D(rate)), "auto-loan") == refusal


def test_interest_is_amortized_monthly_or_accrued_daily_and_nothing_else():
    # S1.9.1: the two interest methods; any other is refused at its field, in its words.
    assert UL._check(_body(method="daily"), "auto-loan") == []
    assert UL._check(_body(method="weekly"), "auto-loan") == _refused(
        "method", "method-invalid", "Monthly or daily."
    )


@pytest.mark.parametrize(
    ("draw", "refusal"),
    [(0, []), (11, []), (12, _refused("drawMonths", "draw-invalid", "Shorter than the term."))],
)
def test_a_helocs_draw_period_is_none_up_to_a_month_short_of_the_term(draw, refusal):
    # S1.9.1: a HELOC's draw period comes before a repayment period, so it is shorter than the
    # term; a period of 0 months is all repayment.
    assert UL._check(_body(principal=D(0), drawMonths=draw), "heloc") == refusal


def test_budget_counting_is_split_or_whole_and_nothing_else():
    # S1.9.7: a payment counts in budgets split by the schedule, or whole.
    assert UL._check(_body(budgetCounting="whole"), "auto-loan") == []
    assert UL._check(_body(budgetCounting="both"), "auto-loan") == _refused(
        "budgetCounting", "counting-invalid", "Split by the schedule, or whole."
    )


def test_the_payments_setting_is_automatic_recorded_or_assumed_and_nothing_else():
    # S1.9.3: Automatic is the setting left unset, so its name is no value of its own.
    for mode in (None, "recorded", "assumed"):
        assert UL._check(_body(paymentsMode=mode), "auto-loan") == []
    assert UL._check(_body(paymentsMode="automatic"), "auto-loan") == _refused(
        "paymentsMode", "payments-mode-invalid", "Automatic, recorded here, or assumed."
    )


AMOUNTS = ("payment", "escrowTax", "escrowInsurance", "pmi", "originalValue")


@pytest.mark.parametrize("field", AMOUNTS)
def test_a_typed_amount_on_the_terms_is_zero_or_more_refused_at_its_own_field(field):
    # S1.9.1, R3.11: nothing and a part of a dollar are kept; a cent below nothing is refused
    # at the field it was typed in.
    for kept in ("0", "0.50"):
        assert UL._check(_body(**{field: D(kept)}), "mortgage") == [], kept
    assert UL._check(_body(**{field: D("-0.01")}), "mortgage") == _refused(
        field, "amount-invalid", "Zero or more."
    )


# ui.loans._check_points, _terms


def _points(**kw) -> UL.TermsIn:
    return _body(**{"points": D(10), "pointsPaidOn": d(2026, 1, 1), "pointsPurpose": "purchase",
                    **kw})  # fmt: skip


NOT_FOR_LOAN = _refused("points", "points-not-for-loan", "Points belong to a mortgage.")
NO_POINTS = _refused("points", "points-missing", "The points paid, or clear their day and purpose.")
NONE_PAID = _refused("points", "amount-invalid", "More than zero.")
NO_DAY = _refused("pointsPaidOn", "required", "The day they were paid.")
LATE = _refused("pointsPaidOn", "points-day-invalid", "By the first payment, at closing.")
PURPOSE = _refused("pointsPurpose", "points-purpose-invalid", "Buying the home, or a refinance.")


@pytest.mark.parametrize(
    ("kind", "kw", "refusal"),
    [
        ("auto-loan", {}, NOT_FOR_LOAN),
        ("mortgage", {"points": None}, NO_POINTS),
        ("mortgage", {"points": D(0)}, NONE_PAID),
        ("mortgage", {"pointsPaidOn": None}, NO_DAY),
        ("mortgage", {"pointsPaidOn": d(2026, 2, 2)}, LATE),
        ("mortgage", {"pointsPurpose": "both"}, PURPOSE),
    ],
)
def test_points_not_whole_are_refused_at_their_field_in_their_words(kind, kw, refusal):
    # S1.9.6, R3.11: a mortgage's points come whole, the amount, the day and the purpose; each
    # part missing or wrong is refused at its own field, and points on any other loan at theirs.
    assert UL._check(_points(**kw), kind) == refusal


@pytest.mark.parametrize("points", ["0.01", "0.50", "1"])
def test_points_of_any_amount_above_nothing_are_kept(points):
    # S1.9.6: points are more than zero, a part of a dollar or one dollar as much as more.
    assert UL._check(_points(points=D(points)), "mortgage") == []


def _caller(uid):
    # `_terms` reads only the caller's id.
    return type("Caller", (), {"id": uid})()


def _problem(field, code, message) -> tuple:
    return (422, code, message, [FieldError(field, code, message)])


def _terms_refused(s, uid, body) -> tuple:
    with pytest.raises(Problem) as e:
        UL._terms(s, _caller(uid), _account(s, uid), body)
    p = e.value
    return (p.status, p.code, p.detail, p.errors)


def test_terms_refused_answer_with_the_first_refusals_code_and_words(book):
    # R3.7: every refusal at its field, the problem's own code and words the first one's.
    s, uid = book
    p = _terms_refused(s, uid, _body(termMonths=0, rate=D(41)))
    assert p == (
        422,
        "term-invalid",
        "Between 1 and 600 months.",
        TERM + RATE,
    )


NO_ITEM = _problem("securedById", "not-found", "No such property or vehicle.")


def test_a_loan_is_secured_only_by_a_live_item(book):
    # S1.9.5: what secures a loan is a property or vehicle that is there: an unknown id and a
    # deleted item are both refused at the field. Unscoped, the deleted item is still read, so
    # the check itself is what refuses it.
    s, uid = book
    assert _terms_refused(s, uid, _body(securedById="Item_none")) == NO_ITEM
    gone = _item(s, _account(s, uid, type="real-estate"))
    gone.mark_deleted(uid)
    s.flush()
    assert _terms_refused(s, uid, _body(securedById=gone.id)) == NO_ITEM


def _category(s, **kw) -> Category:
    cat = Category(id=ids.new_id("Cat"), **{"name": "Housing", "kind": "expense", **kw})
    s.add(cat)
    s.flush()
    return cat


NO_CATEGORY = _problem("budgetCategoryId", "category-unknown", "Choose a category.")


def test_a_whole_payment_counts_under_a_live_category_that_is_not_a_transfer(book):
    # S1.9.7: counted whole, a payment counts under a budget category; an unknown, a deleted or
    # a transfer category is refused at the field. A live expense one is kept.
    s, uid = book
    gone = _category(s)
    gone.mark_deleted(uid)
    s.flush()
    for cat in ("Cat_none", gone.id, _category(s, kind="transfer").id):
        body = _body(budgetCounting="whole", budgetCategoryId=cat)
        assert _terms_refused(s, uid, body) == NO_CATEGORY, cat
    cat = _category(s).id
    out = UL._terms(s, _caller(uid), _account(s, uid), _body(budgetCounting="whole",
                                                             budgetCategoryId=cat))  # fmt: skip
    assert out["budgetCategoryId"] == cat


def test_a_split_payment_keeps_no_budget_category(book):
    # S1.9.7: split by the schedule, a payment counts under each part's category, so a category
    # sent with it is not kept.
    s, uid = book
    body = _body(budgetCounting="split", budgetCategoryId=_category(s).id)
    assert UL._terms(s, _caller(uid), _account(s, uid), body)["budgetCategoryId"] is None


def test_a_recast_is_kept_with_its_day_and_fee(book):
    # S1.9.1: the terms as saved read back on the screen, each recast with its day and fee.
    s, uid = book
    a = _account(s, uid)
    body = _body(recasts=[{"date": d(2026, 6, 15), "fee": D("250.50")}])
    s.add(Loan(id=ids.new_id("Loan"), accountId=a.id, **UL._terms(s, _caller(uid), a, body)))
    s.flush()
    assert [(r.date, r.fee) for r in UL.view(s, a).terms.recasts] == [(d(2026, 6, 15), D("250.50"))]
