"""Edges of the returns (S5) and the payoff planner (S1.9.5): plain values, no server. Each test
pins a rule whose figures in the broader tests happen to come out the same either way."""

import datetime as dt
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
    """CR3-404: -99% a year is inside the range searched: 100 that becomes
    100 x 0.01^4 in four years is -99% a year."""
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
    assert P.expected_extra(t, P.Plan(monthly=D(100)), since, today, D(1200)) == D(300)
    # Chosen on a payment day, that day's payment came before it: Mar and Apr.
    feb = d(2026, 2, 1)
    assert P.expected_extra(t, P.Plan(monthly=D(100)), feb, today, D(1200)) == D(200)
    # A lump on `since` or before it was already counted; one after it counts.
    lumps = [(d(2025, 12, 1), D(7)), (since, D(10)), (d(2026, 3, 1), D(1000))]
    assert P.expected_extra(t, P.Plan(lumps=lumps), since, today, D(1200)) == D(1000)
    # Yearly in March, biweekly a twelfth of 1,200 each payment day.
    yearly = P.Plan(yearly=D(500), yearlyMonth=3)
    assert P.expected_extra(t, yearly, since, today, D(1200)) == D(500)
    biweekly = P.Plan(biweekly=True)
    assert P.expected_extra(t, biweekly, since, today, D(1200)) == D(300)
    # Rounding 1,200 + 130 escrow + 80 PMI up to 1,500, on three payment days.
    up = P.Plan(roundTo=D(100))
    assert P.expected_extra(_terms(), up, since, today, D(1200)) == D(270)  # 3 x 90
