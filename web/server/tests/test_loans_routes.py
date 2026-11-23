"""Loans' routes and the screen they answer with (requirements S1.9): who may read or change a
loan, the screen's every field read from the terms, the schedule and the servicer's balance,
and the equity of what it is secured by, each pinned on the case that tells it apart."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import loan_payment, make, saved, share, terms
from sqlalchemy import select
from test_accounts import add, logged, new_account

from moolakata import assets, clock, ids
from moolakata import loans as L
from moolakata.errors import FieldError, Problem
from moolakata.loans import payoff as P
from moolakata.store.entities.accounts import (
    Account,
    Anchor,
    Category,
    Loan,
    PayoffPlan,
    Transaction,
)
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


# ui.loans._changed_terms, _categories, _unpaired_payments, _plan, _months, _outcome_out,
# _compute, _plans


def test_setting_and_changing_the_terms_is_logged_as_the_accounts_update_for_its_owner(server):
    # S10.8: the terms made and changed are each logged as the loan account's update, naming
    # its terms, by who changed them (a writer of a shared loan too), for the account's owner.
    jane, john = make_user(server, "jane").id, make_user(server, "john").id
    c, j = sign_in(server, "jane"), sign_in(server, "john")
    loan = new_account(c, name="Home", type="mortgage")
    saved(share(c, "account", loan["id"], users={john: "write"}))
    saved(terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    saved(terms(j, loan["id"], rate="5.5"))
    assert logged(server, loan["id"]) == [
        ("account.updated", jane, "account", jane, {"fields": ["terms"]}),
        ("account.updated", john, "account", jane, {"fields": ["terms"]}),
    ]


def test_a_payments_split_names_each_parts_built_in_category(server, frozen):
    # S1.9.3, S1.9.7: the split the payment dialog records files each part under its own
    # built-in category: principal as the loan's transfer, interest, escrow, PMI and fees.
    from moolakata import loans

    make_user(server, "jane")
    c = sign_in(server, "jane")
    loan = new_account(c, name="Home", type="mortgage")
    saved(terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    r = c.get(f"/ui/api/accounts/{loan['id']}/loan/split",
              params={"date": "2026-10-01", "amount": "1798.65"})  # fmt: skip
    assert r.status_code == 200, r.text
    with server.db.read(unscoped="test") as s:
        keys = set(loans.PARTS.values())
        built = {x.builtIn: x.id for x in s.scalars(select(Category)) if x.builtIn in keys}
    assert r.json()["categories"] == {part: built[key] for part, key in loans.PARTS.items()}


def _mortgage_and_checking(server):
    # 300,000 at 6% from Jan 1, 2026: a payment of 1,798.65, the amount a debit is offered for.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    bank = new_account(c, name="Checking")
    loan = new_account(c, name="Home", type="mortgage")
    saved(terms(c, loan["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    return c, bank, loan


def _offered(c, loan) -> list[tuple]:
    cands = c.get(f"/ui/api/accounts/{loan['id']}/loan/candidates").json()["items"]
    return [(x["transactionId"], x["pairWith"]) for x in cands]


@pytest.mark.parametrize("beside", ["another loans payment", "a charge", "nothing"])
def test_only_an_unpaired_payment_on_this_loan_hides_a_debit_beside_it(server, frozen, beside):
    # S1.9.3, S1.7: a debit within days of a payment of another amount recorded on this loan
    # alone is most likely that payment. A payment on another loan, a charge on this one (money
    # out) and an entry of nothing are no payment of this loan: the debit is still offered.
    c, bank, loan = _mortgage_and_checking(server)
    if beside == "another loans payment":
        other = new_account(c, name="Cabin", type="mortgage")
        saved(terms(c, other["id"], principal="50000", startDate="2026-01-01", termMonths=120,
                    rate="6"))  # fmt: skip
        assert loan_payment(c, other["id"], "2026-10-02", "555.10").status_code == 200
    elif beside == "a charge":
        add(c, loan["id"], "-25.00", "2026-10-02", payee="Late fee")
    else:
        add(c, loan["id"], "0.00", "2026-10-02", payee="Statement")
    debit = add(c, bank["id"], "-1798.65", "2026-10-01", payee="ROCKET MORTGAGE")
    assert _offered(c, loan) == [(debit["id"], None)]


def test_a_payment_of_a_dollar_on_this_loan_hides_a_debit_beside_it(server, frozen):
    # S1.9.3, S1.7: a payment of any amount above nothing, a dollar too, recorded on this loan
    # alone within days of the debit is most likely it: linking the debit would count it twice.
    c, bank, loan = _mortgage_and_checking(server)
    assert loan_payment(c, loan["id"], "2026-10-02", "1.00").status_code == 200
    add(c, bank["id"], "-1798.65", "2026-10-01", payee="ROCKET MORTGAGE")
    assert _offered(c, loan) == []


def test_a_payment_already_linked_to_its_bank_half_hides_no_other_debit(server, frozen):
    # S1.7: a payment that is already a transfer has its other half; a second debit of the same
    # amount days later is offered on its own, paired with nothing.
    c, bank, loan = _mortgage_and_checking(server)
    r = loan_payment(c, loan["id"], "2026-10-01", "1798.65", from_account=bank["id"])
    assert r.status_code == 200, r.text
    debit = add(c, bank["id"], "-1798.65", "2026-10-03", payee="ROCKET MORTGAGE")
    assert _offered(c, loan) == [(debit["id"], None)]


def test_a_plans_every_input_reaches_the_planner():
    # S6.10.1: each input the planner's form sends is the plan worked out, none left at its
    # default: every one here differs from it.
    lump = {"date": d(2028, 6, 1), "amount": D(5000)}
    body = UL.PlanIn(monthly=D(100), monthlyFrom=d(2027, 1, 1), monthlyUntil=d(2030, 12, 1),
                     yearly=D(1000), yearlyMonth=3, lumps=[lump], biweekly=True, roundTo=D(50),
                     recast=True, recastFee=D(250), investClass="bonds")  # fmt: skip
    assert UL._plan(body) == P.Plan(
        monthly=D(100),
        monthlyFrom=d(2027, 1, 1),
        monthlyUntil=d(2030, 12, 1),
        yearly=D(1000),
        yearlyMonth=3,
        lumps=[(d(2028, 6, 1), D(5000))],
        biweekly=True,
        roundTo=D(50),
        recast=True,
        recastFee=D(250),
        investClass="bonds",
    )


def _row(day, balance, past) -> L.Row:
    return L.Row(date=day, payment=D(0), principal=D(0), interest=D(0), escrow=D(0), pmi=D(0),
                 balance=D(balance), past=past)  # fmt: skip


def _outcome(payoff_date, interest, fees=0, rows=()) -> P.Outcome:
    return P.Outcome(payoffDate=payoff_date, months=12, interest=D(interest), paid=D(0),
                     payment=D(0), paymentAfter=D(0), fees=D(fees), rows=list(rows))  # fmt: skip


def test_a_plan_saves_the_schedules_interest_less_its_own_and_its_fees():
    # S6.10.2, S6.10.3: the interest saved is the schedule's interest ahead less the plan's,
    # less the recast fees it pays; the balances drawn are those ahead, not the past's.
    base = _outcome(d(2056, 1, 1), "1000")
    rows = [_row(d(2026, 9, 1), "1500", True), _row(d(2026, 11, 1), "900", False)]
    out = UL._outcome_out(_outcome(d(2054, 11, 1), "600", "50", rows), base)
    assert (out.payoffDate, out.interestSaved) == (d(2054, 11, 1), D(350))
    assert [(p.date, p.balance) for p in out.balances] == [(d(2026, 11, 1), D(900))]


@pytest.mark.parametrize(
    ("plan", "schedule", "saved"),
    [
        # Across a year's end, the later month numbered lower: 14 months.
        (d(2054, 11, 1), d(2056, 1, 1), 14),
        (d(2054, 11, 1), d(2054, 11, 1), 0),
        # Paid off on neither, or only the plan: no months to count.
        (None, None, 0),
        (d(2054, 11, 1), None, 0),
        (None, d(2056, 1, 1), 0),
    ],
)
def test_the_months_saved_run_from_the_plans_payoff_to_the_schedules(plan, schedule, saved):
    # S6.10.2: the months saved are the months between the two payoff dates; without both,
    # none.
    out = UL._outcome_out(_outcome(plan, "0"), _outcome(schedule, "0"))
    assert out.monthsSaved == saved


def test_a_plan_for_a_loan_without_terms_is_refused_in_its_words(book):
    # S6.10: the planner works from the loan's terms; without them it says to set them.
    s, uid = book
    with pytest.raises(Problem) as e:
        UL._compute(s, _caller(uid), _account(s, uid), P.Plan())
    assert (e.value.status, e.value.code, e.value.detail) == (
        409,
        "no-terms",
        "Set the loan's terms first.",
    )


def test_a_plans_money_invested_grows_at_the_users_own_return_for_its_class(book):
    # S6.10.4, S6.3: the comparison invests at the return the user set for the class, not the
    # shipped one (4% for bonds).
    from moolakata.projections import assumptions

    s, uid = book
    assumptions.save(s, uid, {"classes": {"bonds": {"return": 5.5}}})
    a = _account(s, uid)
    _loan(s, a)
    r = UL._compute(s, _caller(uid), a, P.Plan(monthly=D(100), investClass="bonds"))
    assert r.invested.rate == 5.5


def test_a_plan_reads_the_payments_as_the_loan_is_set_to(book):
    # S6.10, S1.9.3: the planner's past is the loan screen's. Automatic, a loan with a payment
    # recorded reads as recorded here: after Feb 1's payment, Mar 1 to Sep 1 are missed, not
    # assumed paid (Oct 1 is still in its grace).
    s, uid = book
    a = _account(s, uid)
    _loan(s, a)
    s.add(Transaction(id=ids.new_id("Txn"), accountId=a.id, date=d(2026, 2, 1), kind="deposit",
                      amount=D("1798.65")))  # fmt: skip
    s.flush()
    r = UL._compute(s, _caller(uid), a, P.Plan(monthly=D(100)))
    past = [x.status for x in r.schedule.rows if x.past]
    assert past == ["paid"] + ["missed"] * 7


def test_a_plan_charges_pmi_until_the_balance_reaches_78_percent_of_the_homes_basis(book):
    # S6.10, S1.9.5: with no value typed, PMI is read from the basis of the home the loan is
    # secured by, as the loan's screen reads it: 78% of 380,500 is 296,790, which Nov 1's
    # payment leaves the balance above (296,945.41) and Dec 1's below (296,631.49).
    s, uid = book
    home = _item(s, _account(s, uid, type="real-estate"), costBasis=D(380500))
    a = _account(s, uid)
    _loan(s, a, pmi=D(90), securedById=home.id)
    r = UL._compute(s, _caller(uid), a, P.Plan())
    ahead = [(x.date, x.pmi) for x in r.schedule.rows if not x.past][:2]
    assert ahead == [(d(2026, 11, 1), D(90)), (d(2026, 12, 1), D(0))]


def _saved_plan(s, a, name, made) -> PayoffPlan:
    p = PayoffPlan(id=ids.new_id("Pyoff"), accountId=a.id, name=name, inputs="{}",
                   createdAt=made)  # fmt: skip
    s.add(p)
    s.flush()
    return p


def test_a_loans_plans_are_its_own_in_the_order_they_were_made(book):
    # S6.10.5: saved plans are kept per loan, a plan of another loan not among them, and are
    # listed oldest first, by when each was made, not the order they were stored in.
    s, uid = book
    a = _account(s, uid)
    later = _saved_plan(s, a, "Later", T0)
    first = _saved_plan(s, a, "First", T0 - dt.timedelta(days=1))
    _saved_plan(s, _account(s, uid, name="Cabin"), "Cabin's", T0 - dt.timedelta(days=2))
    assert [p.id for p in UL._plans(s, a)] == [first.id, later.id]


# ui.loans._check_plan


def _plan_refused(**kw) -> tuple | None:
    """The plan's refusal as (status, code, words, refusals), or None when it is kept."""
    try:
        UL._check_plan(UL.PlanIn(**kw))
    except Problem as e:
        return (e.status, e.code, e.detail, e.errors)
    return None


@pytest.mark.parametrize("field", ("monthly", "yearly", "roundTo", "recastFee"))
def test_a_plans_typed_amount_is_zero_or_more_refused_at_its_own_field(field):
    # S6.10.1, R3.11: each amount is none while blank, so nothing is kept; a cent below nothing
    # is refused at the field it was typed in.
    assert _plan_refused(**{field: D(0)}) is None
    assert _plan_refused(**{field: D("-0.01")}) == _problem(
        field, "amount-invalid", "Zero or more."
    )


@pytest.mark.parametrize(("month", "kept"), [(0, False), (1, True), (12, True), (13, False)])
def test_a_plans_bonus_month_is_1_to_12_both_kept(month, kept):
    # S6.10.1: the extra amount once a year falls in a month of the year, January to December.
    refused = _problem("yearlyMonth", "month-invalid", "A month, 1 to 12.")
    assert _plan_refused(yearly=D(1000), yearlyMonth=month) == (None if kept else refused)


def test_a_plans_monthly_extra_may_end_the_month_it_starts_never_before():
    # S6.10.1: an extra amount every month from a date, until a date; either may be left open,
    # and a span of one month is kept.
    start = d(2027, 3, 1)
    assert _plan_refused(monthly=D(100), monthlyFrom=start) is None
    assert _plan_refused(monthly=D(100), monthlyUntil=start) is None
    assert _plan_refused(monthly=D(100), monthlyFrom=start, monthlyUntil=start) is None
    assert _plan_refused(
        monthly=D(100), monthlyFrom=start, monthlyUntil=d(2027, 2, 28)
    ) == _problem("monthlyUntil", "until-before-from", "After the start.")


def test_a_plans_lump_sum_is_more_than_zero_refused_at_its_own_amount():
    # S6.10.1, R3.11: a lump sum of nothing is no lump sum; a cent is kept. Each is refused at
    # its own place in the list.
    day = d(2028, 6, 1)
    assert _plan_refused(lumps=[{"date": day, "amount": D("0.01")}]) is None
    lumps = [{"date": day, "amount": D(5000)}, {"date": day, "amount": D(0)}]
    assert _plan_refused(lumps=lumps) == _problem(
        "lumps.1.amount", "amount-invalid", "More than zero."
    )


def test_a_plans_invested_extra_is_in_one_of_the_asset_classes():
    # S6.10.4, S6.3: the money is invested in an asset class the user picks, at their return
    # for it; any other name is refused at its field.
    assert _plan_refused(investClass="bonds") is None
    assert _plan_refused(investClass="lottery") == _problem(
        "investClass", "class-invalid", "One of the asset classes."
    )


def test_a_plans_refusals_answer_with_the_first_ones_code_and_words():
    # R3.7: every refusal at its field, the problem's own code and words the first one's.
    assert _plan_refused(yearlyMonth=13, investClass="lottery") == (
        422,
        "month-invalid",
        "A month, 1 to 12.",
        [
            FieldError("yearlyMonth", "month-invalid", "A month, 1 to 12."),
            FieldError("investClass", "class-invalid", "One of the asset classes."),
        ],
    )


# ui.loans._saved, _following, _check_name, _get_plan, _loan_account, _loan_create


def _ctx(s, uid):
    # A draft's handlers read only the session and the caller.
    return type("Ctx", (), {"s": s, "caller": _caller(uid)})()


def _plan_row(s, a, inputs="{}", following=False, since=None, deleted=False) -> PayoffPlan:
    p = PayoffPlan(id=ids.new_id("Pyoff"), accountId=a.id, name="Extra", inputs=inputs,
                   following=following, followingSince=since, createdAt=T0)  # fmt: skip
    if deleted:
        p.mark_deleted(None)
    s.add(p)
    s.flush()
    return p


def test_a_saved_plans_headline_is_its_payoff_month_and_the_interest_it_saves(book):
    # S6.10.2, S6.10.5: a saved plan is listed by its payoff month and the interest it saves
    # against the schedule: 334,069.82 of interest ahead less the plan's 182,118.22.
    s, uid = book
    a = _account(s, uid)
    _loan(s, a)
    p = _plan_row(s, a, inputs='{"monthly": "500"}')
    assert (
        UL._saved(s, _caller(uid), a, p).headline == "Paid off Mar 2044 · $151,952 interest saved"
    )


def test_a_plan_on_a_loan_paid_off_has_no_payoff_month_ahead(book):
    # S6.10.2: a loan already paid off (assumed as scheduled, a year from 2020) has nothing
    # ahead: no payoff month, no interest saved.
    s, uid = book
    a = _account(s, uid)
    _loan(s, a, startDate=d(2020, 1, 1), termMonths=12)
    assert (
        UL._saved(s, _caller(uid), a, _plan_row(s, a)).headline == "Paid off — · $0 interest saved"
    )


def test_a_plan_on_a_loan_without_terms_has_no_headline(book):
    # S6.10: without terms there is nothing to plan against, so nothing to say of the plan.
    s, uid = book
    a = _account(s, uid)
    assert UL._saved(s, _caller(uid), a, _plan_row(s, a)).headline == ""


def _overpaid(day, amount) -> L.Row:
    return L.Row(date=day, payment=D(0), principal=D(0), interest=D(0), escrow=D(0), pmi=D(0),
                 balance=D(0), past=day < T0.date(), overpayment=D(amount))  # fmt: skip


def _tracked(s, a, rows=()):
    t = L.Terms(principal=D(300000), start=d(2026, 1, 1), months=360, rate=D(6))
    return UL._following(s, a, t, list(rows), [], [], T0.date())


def test_the_plan_followed_counts_the_overpayments_made_after_the_day_it_was_chosen(book):
    # S6.10.5: the screen shows whether the overpayments since the plan was chosen are ahead of
    # it: one before that day, or on it, is not among them (as the plan's own expected extra
    # counts the days after it), nor is one ahead of today.
    s, uid = book
    a = _account(s, uid)
    p = _plan_row(s, a, following=True, since=d(2026, 6, 1))
    rows = [_overpaid(d(2026, 3, 1), 500), _overpaid(d(2026, 6, 1), 200),
            _overpaid(d(2026, 8, 1), 100), _overpaid(d(2026, 11, 1), 50)]  # fmt: skip
    f = _tracked(s, a, rows)
    assert (f.planId, f.since, f.expected, f.actual, f.ahead) == (
        p.id,
        d(2026, 6, 1),
        0,
        D(100),
        D(100),
    )


def test_the_plan_followed_is_this_loans_live_one_marked_followed(book):
    # S6.10.5: of a loan's saved plans, only the one marked followed is tracked; another
    # loan's plan followed is not this one's.
    s, uid = book
    a = _account(s, uid)
    _plan_row(s, _account(s, uid, name="Cabin"), following=True, since=d(2026, 6, 1))
    assert _tracked(s, a) is None
    # Made first, so it is the plan a look for any of the loan's would find.
    _plan_row(s, a)
    followed = _plan_row(s, a, following=True, since=d(2026, 6, 1))
    assert _tracked(s, a).planId == followed.id


def _name_refused(name) -> tuple | None:
    try:
        UL._check_name(name)
    except Problem as e:
        return (e.status, e.code, e.detail, e.errors)
    return None


@pytest.mark.parametrize(("name", "kept"), [("", False), ("   ", False), ("x" * 80, True),
                                            ("x" * 81, False)])  # fmt: skip
def test_a_plans_name_is_1_to_80_characters_both_kept(name, kept):
    # S6.10.5, R3.7: a saved plan needs a name, of up to 80 characters, refused at its field.
    refused = _problem("name", "name-invalid", "A name, up to 80 characters.")
    assert _name_refused(name) == (None if kept else refused)


def test_a_plans_name_is_kept_without_the_spaces_around_it():
    # S6.10.5: spaces typed around the name are not part of it.
    assert UL._check_name("  Extra 500 ") == "Extra 500"


def _plan_missing(s, uid, a, plan_id) -> tuple:
    with pytest.raises(Problem) as e:
        UL._get_plan(s, _caller(uid), a.id, plan_id)
    return (e.value.status, e.value.code, e.value.detail)


def test_a_plan_is_found_only_live_and_on_its_own_loan(book):
    # S6.10.5: plans are kept per loan; a deleted plan, another loan's or none at all is not
    # found. Unscoped, where only this check stands between the caller and the plan.
    s, uid = book
    a = _account(s, uid)
    p = _plan_row(s, a)
    assert UL._get_plan(s, _caller(uid), a.id, p.id) == (a, p)
    missing = (404, "not-found", "No such plan.")
    assert _plan_missing(s, uid, a, ids.new_id("Pyoff")) == missing
    assert _plan_missing(s, uid, a, _plan_row(s, a, deleted=True).id) == missing
    cabin = _plan_row(s, _account(s, uid, name="Cabin"))
    assert _plan_missing(s, uid, a, cabin.id) == missing


def _read_only(r) -> tuple:
    return (r.status_code, r.json()["code"], [(e["field"], e["code"]) for e in r.json()["errors"]])


READ_ONLY = (403, "save-refused", [("accountId", "share-read-only")])


def test_a_reader_of_a_shared_loan_cannot_set_or_change_its_terms_or_save_a_plan(server, frozen):
    # S10.4, R3.7: a loan shared at Read is read, never changed: its terms and its plans need
    # Write. New terms or a new plan are refused at the loan they are for; a change to terms
    # already set is refused as a whole, asked of the loan itself (the save checks only a new
    # record's account).
    make_user(server, "jane")
    john = make_user(server, "john")
    jane = sign_in(server, "jane")
    home = new_account(jane, name="Home", type="mortgage")
    cabin = new_account(jane, name="Cabin", type="mortgage")
    saved(terms(jane, cabin["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    for a in (home, cabin):
        saved(share(jane, "account", a["id"], users={john.id: "read"}))
    jc = sign_in(server, "john")
    r = terms(jc, home["id"], principal="300000", startDate="2026-01-01", termMonths=360, rate="6")
    assert _read_only(r) == READ_ONLY, r.text
    r = terms(jc, cabin["id"], rate="5")
    assert _read_only(r) == (403, "save-refused", [(None, "share-read-only")]), r.text
    r = make(jc, "Pyoff", accountId=cabin["id"], name="Extra", inputs={"monthly": "300"})
    assert _read_only(r) == READ_ONLY, r.text


def test_a_loans_terms_are_made_once_then_changed(book):
    # S1.9.1, R3.7: a loan with its terms takes no second set; the refusal says to change them,
    # at the loan the terms are for.
    s, uid = book
    a = _account(s, uid)
    _loan(s, a)
    with pytest.raises(Problem) as e:
        UL._loan_create(
            _ctx(s, uid), ids.new_id("Loan"), UL.LoanRecord(accountId=a.id, **_body().model_dump())
        )
    words = "This loan has its terms; change them."
    assert (e.value.status, e.value.code, e.value.detail, e.value.errors) == (
        409,
        "loan-exists",
        words,
        [FieldError("accountId", "loan-exists", words)],
    )
