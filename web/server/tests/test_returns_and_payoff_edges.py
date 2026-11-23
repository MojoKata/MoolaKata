"""Edges of the returns (S5) and the payoff planner (S1.9.5): plain values, no server. Each test
pins a rule whose figures in the broader tests happen to come out the same either way."""

import datetime as dt
import math
from decimal import Decimal as D

from moolakata import loans as L
from moolakata.ledger import performance as perf
from moolakata.loans import payoff as P

d = dt.date


# ---- Time-weighted return ----


def test_twr_needs_two_points_and_two_are_enough():
    """A return needs a start and an end: one point has none, two have one."""
    assert perf.twr([(d(2026, 1, 1), D(100))], {}) is None
    assert perf.twr([(d(2026, 1, 1), D(100)), (d(2026, 2, 1), D(150))], {}) == D("0.5")


def test_twr_chains_every_step_with_its_own_flows():
    """Each step's return is its end over its start plus the flows in it, and the steps chain:
    10%, then 220 from 110 with 100 added (4.76%), is 15.24%, not 220 over the 200 put in."""
    values = [(d(2026, 1, 1), D(100)), (d(2026, 2, 1), D(110)), (d(2026, 3, 1), D(220))]
    r = perf.twr(values, {d(2026, 3, 1): D(100)})
    assert r.quantize(D("0.0001")) == D("0.1524")


def test_twr_counts_a_step_that_starts_under_a_dollar():
    """Any positive starting value has a return: 50 cents that become a dollar is 100%."""
    values = [(d(2026, 1, 1), D("0.50")), (d(2026, 2, 1), D("1.00"))]
    assert perf.twr(values, {}) == D(1)


def test_flows_between_two_days_are_a_decimal_even_when_there_are_none():
    """Every amount is a Decimal (S14.3), the sum of no flows included."""
    none = perf._flows_between({}, d(2026, 1, 1), d(2026, 2, 1))
    assert type(none) is D and none == 0


# ---- Annualised return ----


def test_a_return_over_years_is_annualised_over_them_and_one_over_no_days_is_as_it_is():
    """3Y and 5Y returns are a year's (S5.2.1), a year 365.25 days: 46.41% over four years is
    10% a year and a loss of 34.39% is 10% a year lost; a day's 0.1% compounds over the year to
    44.06%; a span of no days is the return as it is."""
    four_years = 1461
    assert abs(perf.annualise(D("0.4641"), four_years) - D("0.1")) < D("1e-12")
    assert abs(perf.annualise(D("-0.3439"), four_years) + D("0.1")) < D("1e-12")
    assert perf.annualise(D("0.001"), 1).quantize(D("0.0001")) == D("0.4406")
    assert perf.annualise(D("0.25"), 0) == D("0.25")


def test_a_loss_of_everything_or_more_annualises_to_everything():
    """Nothing left grows into nothing whatever the years; more than all lost is all lost."""
    assert perf.annualise(D(-1), 400) == D(-1)
    assert perf.annualise(D("-1.5"), 400) == D(-1)


# ---- Money-weighted return (IRR) ----


def test_irr_counts_a_flow_on_the_last_day():
    """The period's flows run to its last day inclusive: 100 in, 50 more on the last day and
    160 there is 10 earned on 100 over the year (S5.4)."""
    start, end = d(2026, 1, 1), d(2027, 1, 1)
    rate = perf.irr(start, D(100), {end: D(50)}, end, D(160))
    exact = D("1.1") ** (D("365.25") / D(365)) - 1
    assert abs(rate - exact) < D("1e-8")


def test_irr_of_amounts_under_a_dollar():
    """Cents have a return like dollars do: 50 cents that become a dollar in a year is about
    100% a year, not 'nothing went in'."""
    start, end = d(2026, 1, 1), d(2027, 1, 1)
    rate = perf.irr(start, D("0.50"), {}, end, D(1))
    exact = D(2) ** (D("365.25") / D(365)) - 1
    assert abs(rate - exact) < D("1e-8")


def test_irr_at_the_top_of_its_bracket_is_found():
    """+1000% a year is inside the range searched (-99% to +1000%): 100 that becomes
    100 x 11^4 in four years (1,461 days, exactly 4 x 365.25) is 1000% a year."""
    start, end = d(2024, 1, 1), d(2028, 1, 1)
    rate = perf.irr(start, D(100), {}, end, D(100) * D(11) ** 4)
    assert abs(rate - 10) < D("1e-8")


def test_irr_past_its_bracket_is_none_however_small_the_amounts():
    """No rate from -99% to +1000% fits a tenth of a cent that becomes ten cents in a year
    (+9,900%): None, whatever the size of the amounts."""
    start, end = d(2026, 1, 1), d(2027, 1, 1)
    assert perf.irr(start, D("0.001"), {}, end, D("0.1")) is None


def test_irr_returns_an_exact_root_as_it_is():
    """When the bisection lands on the exact rate it stops there: 100 that becomes
    100 x 5.505^4 in four years is 450.5% a year exactly, the search's first midpoint."""
    start, end = d(2024, 1, 1), d(2028, 1, 1)
    assert perf.irr(start, D(100), {}, end, D(100) * D("5.505") ** 4) == D("4.505")


def test_irr_at_the_top_of_its_bracket_is_that_rate_exactly():
    """+1000% a year is the top of the range searched: 100 that becomes 100 x 11^4 in four
    years (1,461 days, four years of 365.25 exactly) is that rate, found as the bound itself."""
    start, end = d(2024, 1, 1), d(2028, 1, 1)
    assert perf.irr(start, D(100), {}, end, D(100) * D(11) ** 4) == D(10)


def test_irr_at_the_bottom_of_its_bracket_is_found():
    """-99% a year is inside the range searched: 100 that becomes 100 x 0.01^4 in four years is -99%
    a year."""
    start, end = d(2024, 1, 1), d(2028, 1, 1)
    rate = perf.irr(start, D(100), {}, end, D(100) * D("0.01") ** 4)
    assert abs(rate - D("-0.99")) < D("1e-8")


# ---- Benchmark and blended index ----


def test_benchmark_without_an_index_is_empty():
    """No index, no benchmark series (S5.2.3)."""
    assert perf.benchmark([(d(2026, 1, 1), D(100))], {}, []) == []


def test_benchmark_holds_the_money_until_the_index_starts():
    """Before the index's first level the benchmark's money stays as it was; from then it
    follows the index."""
    values = [(d(2026, 1, 1), D(100)), (d(2026, 1, 2), D(100)), (d(2026, 1, 3), D(100))]
    index = [(d(2026, 1, 2), D(10)), (d(2026, 1, 3), D(11))]
    assert perf.benchmark(values, {}, index) == [
        (d(2026, 1, 1), D(100)),
        (d(2026, 1, 2), D("100.00")),
        (d(2026, 1, 3), D("110.00")),
    ]


def test_mix_of_nothing_is_empty():
    """A blend of no indexes has no levels."""
    assert perf.mix([]) == []


def test_mix_starts_at_one_on_the_first_common_day_and_compounds():
    """The blend is 1 on the first day all its parts have, and each day's blended return
    compounds on the last: half in an index up 10% twice, half in cash, is 1.05 x 1.05."""
    days = [d(2026, 1, 1), d(2026, 1, 2), d(2026, 1, 3)]
    up = list(zip(days, [D(1), D("1.1"), D("1.21")], strict=True))
    cash = [(x, D(1)) for x in days]
    assert perf.mix([(D("0.5"), up), (D("0.5"), cash)]) == [
        (days[0], D(1)),
        (days[1], D("1.05")),
        (days[2], D("1.1025")),
    ]


# ---- A loan's draw period ----


def test_a_loan_without_a_draw_period_has_no_draw_end():
    """Only a HELOC's draw period ends (S1.9): a loan without one has no such day."""
    t = L.Terms(D(1000), d(2026, 1, 1), 12, D(6))
    assert L.draw_ends(t) is None
    heloc = L.Terms(D(1000), d(2026, 1, 1), 240, D(6), drawMonths=120)
    assert L.draw_ends(heloc) == d(2036, 1, 1)


# ---- The plan's extra on a payment day ----


def _terms(**kw):
    """200,000 at 6% over 30 years with 130 escrow and 80 PMI."""
    return L.Terms(D(200000), d(2026, 1, 1), 360, D(6), escrowTax=D(130), pmi=D(80), **kw)


def test_extras_on_the_same_day_add_up():
    """S1.9.5: the monthly, yearly and biweekly extras on one payment day all count."""
    t = _terms()
    plan = P.Plan(monthly=D(100), yearly=D(1000), yearlyMonth=3, biweekly=True)
    assert P._Extras(plan, t)(d(2026, 3, 1), D(1200)) == D(1200)  # 100 + 1,000 + 100


def test_a_lump_sum_on_a_payment_day_goes_with_that_payment():
    """A lump sum goes with the first payment on or after its day: on the day itself, that
    one."""
    t = _terms()
    x = P._Extras(P.Plan(lumps=[(d(2026, 3, 1), D(5000))]), t)
    assert x(d(2026, 3, 1), D(1000)) == D(5000)
    lumps = P.Plan(lumps=[(d(2026, 3, 1), D(5000))])
    ahead = L.schedule(t, [], [], d(2026, 1, 15))
    assert P.lump_days(lumps, ahead) == [d(2026, 3, 1)]


def test_a_lump_sum_after_the_last_payment_goes_with_none():
    """A lump sum dated after the loan is paid off has no payment to go with, and is left
    out rather than failing the plan."""
    t = L.Terms(D(1000), d(2026, 1, 1), 2, D(0))
    late = P.Plan(lumps=[(d(2030, 1, 1), D(100))])
    assert P.lump_days(late, L.schedule(t, [], [], d(2026, 1, 15))) == []
    assert P.plan_outcomes(t, [], [], d(2026, 1, 15), late, 7.0).plan.months == 2


def test_rounding_to_a_whole_dollar_rounds():
    """Any positive multiple rounds, a dollar too: 1,000 + 130 escrow + 80 PMI + 0.40 is
    1,210.40, rounded up to 1,211."""
    up = P._Extras(P.Plan(roundTo=D(1)), _terms())
    assert up(d(2026, 2, 1), D("1000.40")) == D("0.60")


def test_rounding_up_adds_to_the_escrow_and_the_other_extras():
    """The payment rounded is P&I plus escrow plus PMI plus the plan's other extras, and the
    rounding comes on top of them: 1,000 + 130 + 80 + 30 = 1,240, rounded to 1,300."""
    plan = P.Plan(monthly=D(30), roundTo=D(100))
    assert P._Extras(plan, _terms())(d(2026, 2, 1), D(1000)) == D(90)  # 30 + 60
    no_extra = P.Plan(roundTo=D(100))
    assert P._Extras(no_extra, _terms())(d(2026, 2, 1), D(1000)) == D(90)  # 1,210 to 1,300


# ---- The plan's outcome ----


def _short(**kw):
    """7,500 at 0% paid 500 a month from 1 Feb 2026."""
    return L.Terms(D(7500), d(2026, 1, 1), 24, D(0), payment=D(500), **kw)


def test_the_plans_payment_is_the_scheduled_one_its_extra_apart():
    """S1.9.5: the plan's payment, and its payment after a lump sum, are principal and
    interest as scheduled; the extra is shown apart. With no lump sum they are the same."""
    t = L.Terms(D(300000), d(2025, 1, 1), 360, D(6))
    r = P.plan_outcomes(t, [], [], d(2025, 1, 15), P.Plan(monthly=D(300)), 7.0)
    assert r.plan.payment == r.plan.paymentAfter == D("1798.65")
    lump = P.Plan(monthly=D(300), lumps=[(d(2026, 6, 15), D(50000))])
    r = P.plan_outcomes(t, [], [], d(2025, 1, 15), lump, 7.0)
    assert r.plan.payment == r.plan.paymentAfter == D("1798.65")


def test_the_payment_after_a_lump_sum_is_the_next_one_due():
    """The payment after the first lump sum is the one that follows it: a lump that leaves 200
    owed makes the next, and last, payment 200."""
    plan = P.Plan(lumps=[(d(2026, 2, 1), D(6800))])
    r = P.plan_outcomes(_short(), [], [], d(2026, 1, 15), plan, 7.0)
    assert r.plan.payment == D(500) and r.plan.paymentAfter == D(200)
    assert r.plan.payoffDate == d(2026, 3, 1)


def test_a_loan_with_one_payment_left():
    """With one payment ahead, that payment is the plan's, before and after."""
    t = L.Terms(D(1000), d(2026, 1, 1), 1, D(0))
    r = P.plan_outcomes(t, [], [], d(2026, 1, 15), P.Plan(), 7.0)
    assert r.plan.payment == r.plan.paymentAfter == D(1000) and r.plan.months == 1


def test_a_paid_off_loan_has_no_plan_ahead():
    """A loan already paid has nothing ahead: no payoff date, no payment, nothing to invest,
    and its amounts are Decimals (S14.3). An overpayment already made isn't the plan's."""
    t = L.Terms(D(300000), d(2025, 1, 1), 360, D(6))
    paid = [L.Payment(d(2025, 2, 1), D(300000), principal=D(300000))]
    r = P.plan_outcomes(t, paid, [], d(2025, 3, 1), P.Plan(monthly=D(300)), 7.0)
    for o in (r.schedule, r.plan):
        assert o.payoffDate is None and o.months == 0
        assert o.payment == o.paymentAfter == 0
        assert type(o.interest) is D and type(o.paid) is D
    assert r.invested.contributed == 0 and r.invested.value == 0


def test_only_a_plan_with_recast_and_a_lump_sum_shows_a_recast():
    """S1.9.5: the recast outcome is shown only when the plan asks for it and has a lump sum."""
    t = _short()
    lump = [(d(2026, 2, 1), D(1000))]
    assert P.plan_outcomes(t, [], [], d(2026, 1, 15), P.Plan(lumps=lump), 7.0).recast is None
    assert P.plan_outcomes(t, [], [], d(2026, 1, 15), P.Plan(recast=True), 7.0).recast is None
    assert P.plan_outcomes(t, [], [], d(2026, 1, 15), P.Plan(), 7.0).recast is None


def test_each_recast_pays_its_fee():
    """A recast after each of two lump sums is two fees, counted in what is paid."""
    t = L.Terms(D(300000), d(2025, 1, 1), 360, D(6))
    lumps = [(d(2026, 6, 15), D(20000)), (d(2027, 6, 15), D(20000))]
    plan = P.Plan(lumps=lumps, recast=True, recastFee=D(250))
    r = P.plan_outcomes(t, [], [], d(2025, 1, 15), plan, 7.0)
    assert r.recast.fees == D(500)
    ahead = [x for x in r.recast.rows if not x.past]
    assert r.recast.paid == sum((x.payment for x in ahead), D(0)) + D(500)


def test_a_recast_plan_rounds_up_too():
    """Rounding up applies to the recast loan's payments as to the shortened one's."""
    t = L.Terms(D(300000), d(2025, 1, 1), 360, D(6), escrowTax=D(300))
    plan = P.Plan(lumps=[(d(2026, 6, 15), D(50000))], recast=True, roundTo=D(100))
    r = P.plan_outcomes(t, [], [], d(2025, 1, 15), plan, 7.0)
    ahead = [x for x in r.recast.rows if not x.past]
    assert all(x.payment % 100 == 0 for x in ahead[:-1])


def test_the_money_invested_instead_grows_at_the_return_until_the_payoff():
    """S1.9.5: the plan's extra invested on its payment day and compounded monthly at the
    expected return until the plan's payoff: 1,000 paid on 1 Feb 2026, payoff 1 Feb 2027,
    at 12% a year, is worth 1,120."""
    plan = P.Plan(lumps=[(d(2026, 1, 15), D(1000))])
    r = P.plan_outcomes(_short(), [], [], d(2026, 1, 10), plan, 12.0)
    assert r.plan.payoffDate == d(2027, 2, 1)
    assert r.invested.contributed == D(1000) and r.invested.value == D("1120.00")


def test_the_money_invested_counts_every_extra_and_only_the_plans():
    """Every payment the plan overpays is invested, after past payments that weren't the
    plan's: of the 7,000 left, 100 extra with each of 11 payments of 500, the 400 left none."""
    paid = [L.Payment(d(2026, 2, 1), D(500), principal=D(500))]
    r = P.plan_outcomes(_short(), paid, [], d(2026, 2, 10), P.Plan(monthly=D(100)), 0.0)
    extras = [x.overpayment for x in r.plan.rows if not x.past and x.overpayment]
    assert len(extras) > 1 and r.invested.contributed == sum(extras, D(0)) == D(1100)


# ---- What the plan expected to have been overpaid ----


def test_expected_extra_counts_the_payment_days_after_since_up_to_today():
    """What the plan has had overpaid since it was chosen: the payment days after that day,
    to today, both counted when they are payment days; lump sums dated after it."""
    t = L.Terms(D(200000), d(2026, 1, 1), 360, D(6))
    since, today = d(2026, 1, 1), d(2026, 4, 1)  # Feb, Mar and Apr

    def extra(plan, chosen=since, terms=t):
        return P.expected_extra(terms, plan, chosen, today, [], [])

    assert extra(P.Plan(monthly=D(100))) == D(300)
    # Chosen on a payment day, that day's payment came before it: Mar and Apr.
    assert extra(P.Plan(monthly=D(100)), d(2026, 2, 1)) == D(200)
    # A lump on `since` or before it was already counted; one after it counts.
    lumps = [(d(2025, 12, 1), D(7)), (since, D(10)), (d(2026, 3, 1), D(1000))]
    assert extra(P.Plan(lumps=lumps)) == D(1000)
    # Yearly in March; biweekly a twelfth of the 1,199.10 due each payment day.
    assert extra(P.Plan(yearly=D(500), yearlyMonth=3)) == D(500)
    assert extra(P.Plan(biweekly=True)) == 3 * D("99.93")
    # Rounding 1,199.10 + 130 escrow + 80 PMI up to 1,500, on three payment days.
    assert extra(P.Plan(roundTo=D(100)), terms=_terms()) == 3 * D("90.90")


def test_a_followed_plans_rounding_counts_pmi_only_while_it_is_due():
    """S1.9.5, S6.10.5: PMI that has ended (the balance under 78% of the home's original value)
    isn't rounded up with the payment. 300,000 at 6% (1,798.65) with 300 escrow and a 90 PMI
    that ended: five payments of 2,098.65 rounded up to 2,100 is 6.75, the planner's own
    figure, never 56.75 from 2,188.65."""
    t = L.Terms(
        D(300000), d(2026, 1, 1), 360, D(6), escrowTax=D(300), pmi=D(90),
        originalValue=D(400000),
    )  # fmt: skip
    plan = P.Plan(roundTo=D(100))
    today = d(2026, 6, 1)
    assert P.expected_extra(t, plan, t.start, today, [], []) == D("6.75")
    planned = P.plan_outcomes(t, [], [], t.start, plan, 0.0).plan.rows
    assert sum((r.overpayment for r in planned if r.date <= today), D(0)) == D("6.75")
    # Still due (no original value to end it): each payment rounds 2,188.65 up.
    due = L.Terms(D(300000), d(2026, 1, 1), 360, D(6), escrowTax=D(300), pmi=D(90))
    assert P.expected_extra(due, plan, due.start, today, [], []) == D("56.75")


def test_a_daily_interest_loans_pmi_goes_by_each_months_own_days():
    """S1.9.5: a loan whose interest runs by the day owes less interest in a short month, so
    more principal comes off and the balance PMI goes by is lower. 300,000 at 6%, nothing paid:
    February's 28 days leave 299,582.17 by March's payment, under 78% of 384,103 (299,600.34),
    so March's rounding leaves PMI out; the other months' 31 or 30 days leave more owed. By the
    month, every payment leaves 299,701.35, and PMI is due on all five."""
    plan = P.Plan(roundTo=D(100))
    kw = dict(escrowTax=D(300), pmi=D(90), originalValue=D(384103))
    daily = L.Terms(D(300000), d(2026, 1, 1), 360, D(6), method="daily", **kw)
    monthly = L.Terms(D(300000), d(2026, 1, 1), 360, D(6), **kw)
    today = d(2026, 6, 1)
    # 2,188.65 rounds up by 11.35 on the four days PMI is due; 2,098.65 by 1.35 in March.
    assert P.expected_extra(daily, plan, daily.start, today, [], []) == D("46.75")
    assert P.expected_extra(monthly, plan, monthly.start, today, [], []) == D("56.75")


def test_a_followed_plans_pmi_ends_with_the_payments_made():
    """The balance PMI goes by is what the payments made left: an extra 70,000 paid with the
    first payment takes the balance under 78% of 400,000, so from the next payment the
    rounding leaves PMI out."""
    t = L.Terms(
        D(380000), d(2026, 1, 1), 360, D(6), escrowTax=D(300), pmi=D(90),
        originalValue=D(400000),
    )  # fmt: skip
    pi = L.scheduled_payment(t)
    feb = d(2026, 2, 1)
    big = L.Payment(feb, D(72000), principal=D(70000))  # 310,000 left: under 312,000
    plan = P.Plan(roundTo=D(100))

    def up(total):
        return D(math.ceil(total / 100)) * 100 - total

    # Chosen on Feb 1: March's payment is the one counted.
    assert P.expected_extra(t, plan, feb, d(2026, 3, 1), [big], []) == up(pi + t.escrow)
    assert P.expected_extra(t, plan, feb, d(2026, 3, 1), [], []) == up(pi + t.escrow + t.pmi)


def test_a_followed_plans_biweekly_extra_follows_the_level_after_a_reset():
    """S1.9.2: after a rate reset the payment is worked out again and stays level, so a plan's
    twelfth of it each payment day is a twelfth of the new level, not of the first."""
    t = L.Terms(D(200000), d(2026, 1, 1), 360, D(6), resets=[(d(2026, 3, 15), D(8))])
    plan = P.Plan(biweekly=True)
    before = L.scheduled_payment(t)
    owed = L.balance_on(t, [], [], d(2026, 3, 31))
    after = L.level_payment(owed, D(8), 360 - 3 + 1)
    got = P.expected_extra(t, plan, t.start, d(2026, 5, 1), [], [])
    assert after != before
    assert got == L.cents(before / 12) * 2 + L.cents(after / 12) * 2
