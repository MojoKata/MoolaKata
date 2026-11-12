"""A loan's screens driven in headless Chromium (requirements S1.9, S6.10): the Payoff tab with
each kind of extra and what it comes to, a plan saved, followed, shown again and deleted; the
Schedule tab; a loan with no terms, one paid off, a HELOC in its draw period, an ARM's assumed
rates; the terms form's refusals, its resets and recasts; the servicer's balance; a payment's
split corrected. What the screen shows is checked against what the API works out for the same
plan. Each test's loans are deleted again, so the shared household's figures stay as they were.
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from browser import made, months_back, signed_in, wait
from edits import loan_payment, make, remove, saved, terms

pytestmark = pytest.mark.browser

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RESULTS = '.card:has(h3:text("Balance: the schedule against your plan"))'
SAVED = '.card:has(h3:text("Saved plans"))'
PLAN_ROWS = 'table:has(caption:text("The schedule with your plan")) tbody tr'


def money(v, cents: bool = True) -> str:
    """An amount as the screen shows it: "$1,234.56", or "$1,235" without cents."""
    d = Decimal(str(v))
    a = abs(d)
    if cents:
        out = f"${a.quantize(Decimal('0.01')):,}"
    else:
        out = f"${a.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}"
    return ("−" + out) if d < 0 and out not in ("$0", "$0.00") else out


def day(iso: str) -> str:
    """ "2054-01-01" as "Jan 1, 2054"."""
    y, m, d = iso[:10].split("-")
    return f"{MONTHS[int(m) - 1]} {int(d)}, {y}"


def month(iso: str | None) -> str:
    """ "2054-01-01" as "Jan 2054"; none as a dash."""
    if not iso:
        return "—"
    y, m, _ = iso.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def ahead(n: int) -> str:
    """The first of the month `n` months from now, as 2027-01-01."""
    return f"{months_back(-n)}-01"


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def new_loan(household):
    """A loan account made for one test, with its terms when given; deleted after it."""
    c = household.c
    ids = []

    def new(name: str, type: str = "mortgage", **values) -> dict:
        a = made(make(c, "Acct", name=name, type=type))
        ids.append(a["id"])
        if values:
            saved(terms(c, a["id"], **values))
        return a

    new.ids = ids
    yield new
    for i in ids:
        r = c.get(f"/ui/api/accounts/{i}")
        if r.status_code == 200:
            made(remove(c, "Acct", r.json(), confirm=True))


def fixed(new_loan, name: str) -> dict:
    """A fixed-rate mortgage of $300,000 at 6% made this month, with escrow for its taxes: its
    first payment is next month's."""
    return new_loan(name, principal="300000", startDate=f"{months_back(0)}-01", termMonths=360,
                    rate="6", escrowTax="300")  # fmt: skip


def plan(h, a: dict, **body) -> dict:
    """What the API works out for a plan, as the Payoff tab sends it."""
    r = h.c.post(f"/ui/api/accounts/{a['id']}/loan/payoff", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def planner(browser, h, a: dict):
    return signed_in(browser, h, f"/ui/accounts/{a['id']}/payoff", f"{RESULTS} .kv")


def worked_out(page, problems, act) -> None:
    """`act` changes the plan, and leaving the field takes it (S12.18.4); then its answer, and
    the page settled."""
    with page.expect_response(lambda r: "/loan/payoff" in r.url):
        act()
        page.keyboard.press("Tab")
    wait(page, f"{RESULTS} .kv", problems)


def figure(page, label: str) -> str:
    return page.locator(f'{RESULTS} .kv > div:has(.k:text-is("{label}")) .v').inner_text()


def assert_outcome(page, r: dict) -> None:
    """The figures beside the chart are the plan's, as the API worked them out."""
    p, s = r["plan"], r["schedule"]
    assert figure(page, "Paid off") == month(p["payoffDate"])
    scheduled = page.locator(f'{RESULTS} .kv > div:has(.k:text-is("Paid off")) .small')
    assert scheduled.inner_text() == f"scheduled {month(s['payoffDate'])}"
    assert figure(page, "Months saved") == str(p["monthsSaved"])
    assert figure(page, "Interest saved") == money(p["interestSaved"], cents=False)
    assert figure(page, "Interest still to pay") == money(p["interest"], cents=False)
    assert figure(page, "Total paid") == money(p["paid"], cents=False)


def invested_notice(r: dict, label: str) -> str:
    p, i = r["plan"], r["invested"]
    pct = f"{Decimal(str(i['rate'])).normalize():f}%"
    return (
        f"Investing the same {money(i['contributed'], False)} in {label} at {pct} a year "
        f"instead would be worth about {money(i['value'], False)} by {month(p['payoffDate'])}, "
        f"against {money(p['interestSaved'], False)} of interest saved. A comparison, not "
        "advice: the return is an assumption; the interest saved is certain."
    )


def tab(page, problems, name: str, ready: str) -> None:
    """Another of the account's tabs, as its link opens it: the same page, so what it ran
    before counts too."""
    page.get_by_role("tab", name=name).click()
    wait(page, ready, problems)


def value(page, selector: str) -> Decimal:
    return Decimal(page.locator(selector).input_value())


def extras(page) -> list[tuple[str, str]]:
    """The plan's schedule shown: each row's due date and its extra."""
    rows = page.locator(PLAN_ROWS)
    out = []
    for i in range(rows.count()):
        cells = rows.nth(i).locator("td").all_inner_texts()
        out.append((cells[0], cells[3]))
    return out


# ---------- the Payoff tab ----------


def test_an_empty_plan_shows_the_schedule(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff empty mortgage")
    r = plan(h, a)
    page, problems = planner(browser, h, a)
    assert_outcome(page, r)
    assert figure(page, "Months saved") == "0" and figure(page, "Interest saved") == "$0"
    assert month(r["plan"]["payoffDate"]) == month(r["schedule"]["payoffDate"])
    card = page.locator(RESULTS)
    assert card.locator(".legend").inner_text().split() == ["Schedule", "With", "your", "plan"]
    assert flat(page.locator(SAVED).inner_text()).startswith("Saved plans None yet. Save a plan")
    # The plan's schedule, shown and hidden again: no extra on any row.
    page.get_by_role("button", name="Show the plan’s schedule").click()
    wait(page, PLAN_ROWS, problems)
    shown = extras(page)
    assert len(shown) == len(r["planRows"])
    assert shown[0][0] == day(r["planRows"][0]["date"])
    assert {x for _, x in shown} == {"—"}
    page.get_by_role("button", name="Hide the plan’s schedule").click()
    wait(page, PLAN_ROWS, problems, state="detached")
    assert problems == []
    page.close()


def test_an_empty_plan_asks_for_an_overpayment(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff unchanged mortgage")
    page, problems = planner(browser, h, a)
    card = page.locator(RESULTS)
    try:
        assert "Investing the same" not in card.inner_text()
        assert "Add an overpayment to see what it saves." in card.inner_text()
        assert problems == []
    finally:
        page.close()


def test_a_monthly_extra_from_and_until_and_where_it_would_be_invested(
    browser, household, new_loan
):
    h = household
    a = fixed(new_loan, "Payoff monthly mortgage")
    start, until = ahead(2), ahead(7)
    page, problems = planner(browser, h, a)
    worked_out(page, problems, lambda: page.fill("#f-extra-each-month", "$1,000"))
    worked_out(page, problems, lambda: page.fill("#f-monthly-from", start))
    worked_out(page, problems, lambda: page.fill("#f-monthly-until", until))
    r = plan(h, a, monthly="1000", monthlyFrom=start, monthlyUntil=until)
    assert r["plan"]["monthsSaved"] > 0
    assert_outcome(page, r)
    notice = page.locator(f'{RESULTS} .notice:has-text("Investing the same")')
    assert flat(notice.inner_text()) == invested_notice(r, "US stocks")
    # Six payments carry it, from the first due on or after its start to the last before its end.
    page.get_by_role("button", name="Show the plan’s schedule").click()
    wait(page, PLAN_ROWS, problems)
    carried = [(d, x) for d, x in extras(page) if x != "—"]
    assert carried == [(day(ahead(n)), "$1,000.00") for n in range(2, 8)]
    # Invested in another class, at its own expected return.
    classes = h.c.get("/ui/api/assumptions").json()["classes"]
    other, label = next((k, v) for k, v in classes if k != "usStocks")
    worked_out(page, problems, lambda: page.select_option("#f-invest-class", other))
    r = plan(h, a, monthly="1000", monthlyFrom=start, monthlyUntil=until, investClass=other)
    assert flat(notice.inner_text()) == invested_notice(r, label)
    assert problems == []
    page.close()


def test_a_yearly_extra_goes_with_the_payment_of_its_month(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff yearly mortgage")
    page, problems = planner(browser, h, a)
    worked_out(page, problems, lambda: page.fill("#f-extra-once-a-year", "5000"))
    worked_out(page, problems, lambda: page.select_option("#f-yearly-month", "3"))
    r = plan(h, a, yearly="5000", yearlyMonth=3)
    assert_outcome(page, r)
    assert r["plan"]["monthsSaved"] > 0
    page.get_by_role("button", name="Show the plan’s schedule").click()
    wait(page, PLAN_ROWS, problems)
    carried = [(d, x) for d, x in extras(page) if x != "—"]
    assert len(carried) >= 5
    # Every one a March payment, of $5,000 but the last, which pays off what is left.
    assert all(d.startswith("Mar 1,") for d, _ in carried)
    assert {x for _, x in carried[:-1]} == {"$5,000.00"}
    assert problems == []
    page.close()


def test_lump_sums_shorten_the_loan_or_recast_it(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff lumps mortgage")
    first, second = ahead(4), ahead(16)
    page, problems = planner(browser, h, a)
    add = page.get_by_role("button", name="Add a lump sum")
    for i, (when, amount) in enumerate([(first, "20000"), (second, "10000")]):
        add.click()
        page.fill(f"#x-lump-date-{i}", when)
        worked_out(page, problems, lambda i=i, amount=amount: page.fill(f"#x-lump-amount-{i}",
                                                                         amount))  # fmt: skip
    lumps = [{"date": first, "amount": "20000"}, {"date": second, "amount": "10000"}]
    assert_outcome(page, plan(h, a, lumps=lumps))
    assert page.locator("#f-recast-fee").count() == 0
    worked_out(page, problems, lambda: page.click("#f-recast-after-the-lump-sums"))
    worked_out(page, problems, lambda: page.fill("#f-recast-fee", "250"))
    r = plan(h, a, lumps=lumps, recast=True, recastFee="250")
    p, rc = r["plan"], r["recast"]
    assert_outcome(page, r)
    card = page.locator(RESULTS)
    assert "Recast" in card.locator(".legend").inner_text()
    rows = card.locator('table:has(caption:text("Shortening the loan")) tbody tr')
    shorten = rows.nth(0).locator("td").all_inner_texts()
    recast = rows.nth(1).locator("td").all_inner_texts()
    assert shorten == ["Shorten the loan", money(p["paymentAfter"]), month(p["payoffDate"]),
                       money(p["interestSaved"], False)]  # fmt: skip
    assert recast == ["Recast · $500.00 in fees", money(rc["paymentAfter"]),
                      month(rc["payoffDate"]), money(rc["interestSaved"], False)]  # fmt: skip
    # Recast, the payment drops and the payoff date stays; shortened, it ends sooner.
    assert Decimal(str(rc["paymentAfter"])) < Decimal(str(p["paymentAfter"]))
    assert rc["payoffDate"] == r["schedule"]["payoffDate"] > p["payoffDate"]
    # The second lump sum taken away, and the recast without a fee.
    drop = page.get_by_role("button", name="Remove the lump sum").nth(1)
    worked_out(page, problems, drop.click)
    worked_out(page, problems, lambda: page.fill("#f-recast-fee", ""))
    r = plan(h, a, lumps=lumps[:1], recast=True)
    assert_outcome(page, r)
    assert rows.nth(1).locator("td").first.inner_text() == "Recast"
    assert rows.nth(1).locator("td").nth(1).inner_text() == money(r["recast"]["paymentAfter"])
    assert page.locator("#x-lump-date-1").count() == 0
    assert problems == []
    page.close()


def test_biweekly_payments_and_rounding_each_payment_up(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff biweekly mortgage")
    page, problems = planner(browser, h, a)
    worked_out(page, problems, lambda: page.click("#f-biweekly-payments"))
    assert page.locator("#f-biweekly-payments").get_attribute("aria-checked") == "true"
    biweekly = plan(h, a, biweekly=True)
    assert biweekly["plan"]["monthsSaved"] > 0
    assert_outcome(page, biweekly)
    worked_out(page, problems, lambda: page.fill("#f-round-to", "100"))
    both = plan(h, a, biweekly=True, roundTo="100")
    assert both["plan"]["monthsSaved"] > biweekly["plan"]["monthsSaved"]
    assert_outcome(page, both)
    # Rounding alone: each payment of $2,098.65 with its escrow made $2,100.
    worked_out(page, problems, lambda: page.click("#f-biweekly-payments"))
    rounded = plan(h, a, roundTo="100")
    assert_outcome(page, rounded)
    page.get_by_role("button", name="Show the plan’s schedule").click()
    wait(page, PLAN_ROWS, problems)
    assert extras(page)[0][1] == "$1.35"
    assert problems == []
    page.close()


def test_an_arms_rates_after_today_are_named_as_assumed(browser, household, new_loan):
    h = household
    a = new_loan("Payoff ARM", principal="300000", startDate="2024-01-01", termMonths=360,
                 rate="6", resets=[{"date": "2030-04-01", "rate": "7.125"},
                                   {"date": "2031-04-01", "rate": "7.5"}])  # fmt: skip
    page, problems = planner(browser, h, a)
    warn = page.locator(f"{RESULTS} .notice.warn")
    assert flat(warn.inner_text()) == (
        "After Apr 1, 2030 the rate is your assumption (7.125% from Apr 2030, 7.5% from "
        "Apr 2031), as typed in the terms."
    )
    assert_outcome(page, plan(h, a))
    # Its Overview calls the rate adjustable.
    tab(page, problems, "Overview", '.card.facts:has(h3:has-text("Loan"))')
    rate = page.locator('.card.facts .list-item:has-text("Rate")').inner_text()
    assert flat(rate) == "Rate 6.0% adjustable · monthly amortization"
    assert problems == []
    page.close()


def test_the_plans_refusals_show_at_their_fields(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff refused mortgage")
    page, problems = planner(browser, h, a)
    worked_out(page, problems, lambda: page.fill("#f-extra-each-month", "100"))
    # A minus isn't one of an amount's characters here: refused, and marked with what it takes.
    page.fill("#f-extra-each-month", "-5")
    extra = page.locator("#f-extra-each-month")
    assert extra.input_value() == "100"
    assert extra.get_attribute("data-tip") == "Digits and . only."
    worked_out(page, problems, lambda: page.fill("#f-monthly-from", ahead(6)))
    good = plan(h, a, monthly="100", monthlyFrom=ahead(6))
    worked_out(page, problems, lambda: page.fill("#f-monthly-until", ahead(3)))
    assert page.locator("#f-monthly-until-err").inner_text() == "After the start."
    page.get_by_role("button", name="Add a lump sum").click()
    page.fill("#x-lump-date-0", ahead(2))
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-0", "0"))
    assert page.locator("#x-lump-amount-0-err").inner_text() == "More than zero."
    # Each refusal at its field alone, none again below the form; the last figures stay.
    assert page.locator('.card:has(h3:text("Your plan")) .notice.bad').count() == 0
    assert_outcome(page, good)
    # Corrected, the refusals go and the plan is worked out again.
    worked_out(page, problems, lambda: page.fill("#f-monthly-until", ""))
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-0", "2500"))
    assert page.locator(".field .err").count() == 0
    r = plan(h, a, monthly="100", monthlyFrom=ahead(6), lumps=[{"date": ahead(2),
                                                                "amount": "2500"}])  # fmt: skip
    assert_outcome(page, r)
    assert [p for p in problems if "/loan/payoff" not in p or not p.startswith("422")] == []
    page.close()


def test_a_lump_sum_half_filled_is_left_out_then_refused_at_its_row(browser, household, new_loan):
    """S6.10.1, S12.18.4: a lump sum missing its date or amount is left out of the plan worked
    out, unmarked, while it is filled; a refusal of the one after it lands at that one's row;
    Save plan refuses the half-filled one at its own field and saves nothing."""
    h = household
    a = fixed(new_loan, "Payoff lumps mortgage")
    page, problems = planner(browser, h, a)
    page.get_by_role("button", name="Add a lump sum").click()
    page.get_by_role("button", name="Add a lump sum").click()
    page.fill("#x-lump-date-0", ahead(3))  # a date only
    page.fill("#x-lump-date-1", ahead(2))
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-1", "0"))
    assert page.locator("#x-lump-amount-1-err").inner_text() == "More than zero."
    assert page.locator("#x-lump-amount-0-err").count() == 0, "not the row left out"
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-1", "5000"))
    assert_outcome(page, plan(h, a, lumps=[{"date": ahead(2), "amount": "5000"}]))
    assert page.locator(".field .err").count() == 0, "a row being filled isn't refused"
    page.fill("#f-plan-name", "Half filled")
    page.click(f'{SAVED} button:has-text("Save plan")')
    wait(page, "#x-lump-amount-0-err", problems)
    said = page.locator("#x-lump-amount-0-err").inner_text()
    assert said == "A date and an amount, or remove the lump sum."
    assert page.locator("#x-lump-date-0-err, #x-lump-amount-1-err").count() == 0
    saved_plans = h.c.get(f"/ui/api/accounts/{a['id']}/loan/plans").json()["items"]
    assert [p["name"] for p in saved_plans] == []
    # Typed in, the refusal goes; saved, it holds both lump sums.
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-0", "1000"))
    assert page.locator(".field .err").count() == 0
    page.click(f'{SAVED} button:has-text("Save plan")')
    wait(page, f'{SAVED} .list-item:has-text("Half filled")', problems)
    [p] = h.c.get(f"/ui/api/accounts/{a['id']}/loan/plans").json()["items"]
    assert [(x["date"], float(x["amount"])) for x in p["inputs"]["lumps"]] == [
        (ahead(3), 1000),
        (ahead(2), 5000),
    ]
    assert [x for x in problems if not x.startswith("422")] == []
    page.close()


def test_a_plan_saved_followed_shown_again_and_deleted(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Payoff saved mortgage")
    page, problems = planner(browser, h, a)
    worked_out(page, problems, lambda: page.fill("#f-extra-each-month", "200"))
    page.get_by_role("button", name="Add a lump sum").click()
    page.fill("#x-lump-date-0", ahead(5))
    worked_out(page, problems, lambda: page.fill("#x-lump-amount-0", "15000"))
    worked_out(page, problems, lambda: page.click("#f-recast-after-the-lump-sums"))
    worked_out(page, problems, lambda: page.fill("#f-recast-fee", "300"))
    page.fill("#f-plan-name", "Extra $200 and a bonus")
    page.get_by_role("button", name="Save plan").click()
    wait(page, '.toast:has-text("Plan saved")', problems)
    wait(page, f'{SAVED} .list-item:has-text("Extra $200 and a bonus")', problems)
    (kept,) = h.c.get(f"/ui/api/accounts/{a['id']}/loan/plans").json()["items"]
    item = page.locator(f"{SAVED} .list-item")
    assert kept["headline"].startswith("Paid off ")
    assert flat(item.inner_text()) == f"Extra $200 and a bonus {kept['headline']} Show Follow"
    assert page.locator("#f-plan-name").input_value() == ""
    # Followed from today.
    item.get_by_role("button", name="Follow").click()
    wait(page, '.toast:has-text("Following it from today")', problems)
    wait(page, f'{SAVED} button[aria-pressed="true"]', problems)
    (kept,) = h.c.get(f"/ui/api/accounts/{a['id']}/loan/plans").json()["items"]
    assert kept["following"]
    # The text runs on into the headline: no space is written after the "·".
    since = flat(item.locator(".small").inner_text())
    assert since.startswith(f"the plan you're following, since {day(kept['followingSince'])} ·")
    # With the help pane open, the plan's words keep their width and its buttons go
    # below them (CR3-412), never one word to a line.
    if page.locator(".help .guide").count() == 0:
        page.get_by_role("button", name="Show help (F1)").click()
    wait(page, ".help .guide", problems)
    grow = item.first.locator(".grow")
    assert grow.evaluate("(e) => e.getBoundingClientRect().width") >= 180
    name = grow.evaluate("(e) => e.firstChild.textContent")
    assert "\n" not in grow.inner_text().split("the plan")[0].strip(), name
    assert since.endswith(kept["headline"])
    # Opened again, the planner starts from the plan being followed.
    tab(page, problems, "Overview", '.card.facts:has-text("Following")')
    following = page.locator('.card.facts .list-item:has-text("Following")').inner_text()
    assert flat(following) == "Following Extra $200 and a bonus · ahead by $0.00"
    tab(page, problems, "Payoff", f"{RESULTS} .kv")
    assert value(page, "#f-extra-each-month") == 200
    assert page.locator("#x-lump-date-0").input_value() == ahead(5)
    assert value(page, "#x-lump-amount-0") == 15000
    assert page.locator("#f-recast-after-the-lump-sums").get_attribute("aria-checked") == "true"
    assert value(page, "#f-recast-fee") == 300
    assert page.locator("#f-extra-once-a-year").input_value() == ""
    assert_outcome(page, plan(h, a, **kept["inputs"]))
    # Cleared, then Show puts the plan back.
    worked_out(page, problems, lambda: page.fill("#f-extra-each-month", ""))
    worked_out(page, problems, lambda: item.get_by_role("button", name="Show").click())
    assert value(page, "#f-extra-each-month") == 200
    # No longer followed, then deleted.
    item.get_by_role("button", name="Following").click()
    wait(page, '.toast:has-text("No longer following it")', problems)
    wait(page, f'{SAVED} button:text-is("Follow")', problems)
    page.get_by_role("button", name="Delete Extra $200 and a bonus").click()
    wait(page, '.toast:has-text("Extra $200 and a bonus deleted")', problems)
    wait(page, f'{SAVED} p:has-text("None yet.")', problems)
    assert h.c.get(f"/ui/api/accounts/{a['id']}/loan/plans").json()["items"] == []
    assert problems == []
    page.close()


def test_a_late_answer_never_replaces_a_newer_plans(browser, household, new_loan):
    # The answer to $100 a month held back until the one to $200 is in: the screen keeps $200's.
    h = household
    a = fixed(new_loan, "Payoff late mortgage")
    page, problems = planner(browser, h, a)
    held = []
    page.route("**/loan/payoff", lambda route: held.append(route))
    with page.expect_request("**/loan/payoff"):
        page.fill("#f-extra-each-month", "100")
        page.keyboard.press("Enter")
    with page.expect_request("**/loan/payoff"):
        page.fill("#f-extra-each-month", "200")
        page.keyboard.press("Enter")
    for _ in range(250):  # each request reaches its handler a moment after it is sent
        if len(held) == 2:
            break
        page.wait_for_timeout(20)
    first, second = held
    with page.expect_response(lambda r: r.request == second.request):
        second.continue_()
    with page.expect_response(lambda r: r.request == first.request):
        first.continue_()
    wait(page, f"{RESULTS} .kv", problems)
    page.unroute("**/loan/payoff")
    assert_outcome(page, plan(h, a, monthly="200"))
    assert problems == []
    page.close()


# ---------- a loan's states ----------


def test_a_loan_without_terms_says_where_to_set_them(browser, household, new_loan):
    h = household
    a = new_loan("Termless loan", type="loan")
    summary = '.card:has(h3:text-is("Loan"))'
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", f"{summary} .empty")
    assert page.locator(f"{summary} .empty").inner_text() == (
        "No terms yet. Set them in Settings to compute the schedule."
    )
    tab(page, problems, "Payoff", 'main .empty:has-text("plan the payoff")')
    assert page.locator("main .empty").inner_text() == (
        "No terms yet. Set them in Settings to plan the payoff."
    )
    tab(page, problems, "Schedule", 'main .empty:has-text("compute the schedule")')
    assert page.locator("main .empty").inner_text() == (
        "No terms yet. Set them in Settings to compute the schedule."
    )
    assert problems == []
    page.close()


def test_a_paid_off_loan(browser, household, new_loan):
    # S1.9.2: the whole balance and its month's interest paid with the first payment.
    h = household
    start = f"{months_back(3)}-01"
    a = new_loan("Paid-off loan", type="loan", principal="1200", startDate=start, termMonths=12,
                 rate="5")  # fmt: skip
    paid = f"{months_back(2)}-01"
    assert loan_payment(h.c, a["id"], paid, "1205").status_code == 200
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    assert v["balance"] == 0 and v["nextDate"] is None
    facts = '.card.facts:has(h3:has-text("Loan"))'
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", facts)
    text = page.locator(facts).inner_text()
    assert "Next due\n—" in text
    assert f"Paid off\n{month(paid)} · scheduled {month(v['originalPayoff'])}" in text
    assert f"Overpaid\n{money(v['overpaid'])}" in text
    # Its schedule: the one payment, paid, with what it paid beyond the schedule.
    tab(page, problems, "Schedule", 'table:has(caption:text("Amortization schedule"))')
    rows = page.locator('table:has(caption:text("Amortization schedule")) tbody tr')
    assert rows.count() == 1
    assert rows.first.locator(".pill.ok").inner_text() == "paid"
    assert rows.first.locator("td").all_inner_texts() == [
        f"{day(paid)} paid", "$1,205.00", "$1,200.00", "$5.00", money(v["overpaid"]), "$0.00"
    ]  # fmt: skip
    # Nothing left to plan: no payoff date, and nothing an overpayment would save.
    tab(page, problems, "Payoff", f"{RESULTS} .kv")
    assert figure(page, "Paid off") == "—"
    assert figure(page, "Interest still to pay") == "$0"
    assert figure(page, "Months saved") == "0" and figure(page, "Interest saved") == "$0"
    assert problems == []
    page.close()


def test_a_helocs_draw_period_is_interest_only(browser, household, new_loan):
    h = household
    a = new_loan("Draw-period HELOC", type="heloc", principal="50000",
                 startDate=f"{months_back(12)}-01", termMonths=360, rate="8",
                 drawMonths=120)  # fmt: skip
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    facts = '.card.facts:has(h3:has-text("Loan"))'
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", facts)
    text = page.locator(facts).inner_text()
    assert f"Payment\n$333.33\ninterest only until {day(v['interestOnlyUntil'])}" in text
    # The schedule: interest alone until the draw period ends, all of it on asking. None
    # recorded, the days passed are assumed as scheduled (S1.9.3): three are shown before the
    # next.
    tab(page, problems, "Schedule", 'table:has(caption:text("Amortization schedule"))')
    rows = page.locator('table:has(caption:text("Amortization schedule")) tbody tr')
    assert rows.count() == 15
    assert rows.first.locator(".pill.info").inner_text() == "assumed as scheduled"
    first = rows.nth(3).locator("td").all_inner_texts()
    assert first == [day(v["nextDate"]), "$333.33", "$0.00", "$333.33", "—", "$50,000.00"]
    assert page.locator("thead").inner_text().count("Escrow") == 0
    note = page.locator('.toolbar:has(button:text("Show all")) .small').inner_text()
    assert note.startswith(f"{len(v['rows'])} payments.")
    page.get_by_role("button", name="Show all").click()
    wait(page, 'button:text("Show fewer")', problems)
    assert rows.count() == len(v["rows"])
    last = rows.last.locator("td").all_inner_texts()
    assert last[0] == day(v["payoffDate"]) and last[-1] == "$0.00"
    page.get_by_role("button", name="Show fewer").click()
    wait(page, 'button:text("Show all")', problems)
    assert rows.count() == 15
    # Its payoff plan: an extra each month during the draw period pays principal down.
    tab(page, problems, "Payoff", f"{RESULTS} .kv")
    worked_out(page, problems, lambda: page.fill("#f-extra-each-month", "250"))
    r = plan(h, a, monthly="250")
    assert r["plan"]["monthsSaved"] > 0
    assert_outcome(page, r)
    assert problems == []
    page.close()


def test_the_schedule_shows_escrow_paid_rows_and_an_overpayment(browser, household, new_loan):
    h = household
    a = new_loan("Schedule mortgage", principal="240000", startDate=f"{months_back(3)}-01",
                 termMonths=360, rate="6.5", escrowTax="250", pmi="80")  # fmt: skip
    due = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    first, second = f"{months_back(2)}-01", f"{months_back(1)}-01"
    assert loan_payment(h.c, a["id"], first, due["total"]).status_code == 200
    extra = Decimal(str(due["total"])) + 500
    assert loan_payment(h.c, a["id"], second, str(extra)).status_code == 200
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}/schedule",
                               'table:has(caption:text("Amortization schedule"))')  # fmt: skip
    head = page.locator("thead th").all_inner_texts()
    assert head == ["Due", "Payment", "Principal", "Interest", "Escrow and PMI", "Extra",
                    "Balance"]  # fmt: skip
    rows = page.locator('table:has(caption:text("Amortization schedule")) tbody tr')
    cells = [rows.nth(i).locator("td").all_inner_texts() for i in range(rows.count())]
    # The date and its pill are written without a space between them.
    assert [c[0] for c in cells[:3]] == [f"{day(first)} paid", f"{day(second)} paid",
                                         day(v["nextDate"])]  # fmt: skip
    assert rows.nth(1).locator(".pill.ok").inner_text() == "paid"
    assert rows.nth(0).get_attribute("class") == "dim" and rows.nth(2).get_attribute("class") == ""
    assert {c[4] for c in cells} == {"$330.00"}
    assert cells[0][5] == "—" and cells[1][5] == "$500.00" and cells[2][5] == "—"
    assert cells[1][1] == money(extra)
    assert problems == []
    page.close()


def test_a_loan_that_cant_be_read_says_so_on_each_tab(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Unreadable mortgage")
    busy = {
        "type": "about:blank",
        "title": "Unavailable",
        "status": 503,
        "detail": "The server is busy; try again.",
        "code": "busy",
        "errorId": "err_busy",
    }
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", "main .tabs")
    page.route(
        lambda url: url.split("?")[0].endswith(f"/accounts/{a['id']}/loan"),
        lambda route: route.fulfill(status=503, json=busy,
                                    headers={"Content-Type": "application/problem+json"}),
    )  # fmt: skip
    for name in ("Schedule", "Payoff", "Overview"):
        tab(page, problems, name, 'main .notice.bad:has-text("The server is busy")')
        # The message and its error id, which run together: no space is written between them.
        alert = flat(page.locator("main .notice.bad").first.inner_text())
        assert alert.startswith("The server is busy; try again.") and alert.endswith("(err_busy)")
    assert [p for p in problems if not p.startswith("503 for")] == []
    page.close()


# ---------- the terms ----------


def test_the_terms_form_refuses_what_a_loan_cant_be(browser, household, new_loan):
    h = household
    page, problems = signed_in(browser, h, "/ui/accounts", 'button:has-text("New account")')
    page.click('button:has-text("New account")')
    page.click('button.type-card:has-text("HELOC")')
    wait(page, "#f-draw-months", problems)
    assert page.locator("#f-draw-months").input_value() == "120"
    assert page.locator("#f-term-months").input_value() == "360"
    page.fill("#f-name", "Refused HELOC")
    # A HELOC may open at $0 (Min fills it in), never below: a minus is no amount's character
    # here, so it is refused as typed and the field marked with what it takes (S12.18.2).
    principal = page.locator("#f-original-principal")
    principal.fill("-5")
    assert principal.input_value() == ""
    assert principal.get_attribute("data-tip") == "Digits and . only."
    page.get_by_role("button", name="Min: $0.00").click()
    assert principal.input_value() == "0.00"
    page.fill("#f-start-date", f"{months_back(6)}-01")
    page.fill("#f-term-months", "700")
    page.fill("#f-interest-rate", "45")
    # Past 40%, the rate is marked when it is left (S12.18.3); the server refuses it at Save.
    page.keyboard.press("Tab")
    assert page.locator("#f-interest-rate").get_attribute("data-tip") == "40% or less."
    page.fill("#f-draw-months", "800")
    page.click(".dialog footer button.primary")
    wait(page, "#f-term-months-err", problems)
    said = {
        f: page.locator(f"#f-{f}-err").inner_text()
        for f in ("term-months", "interest-rate", "draw-months")
    }
    assert said == {
        "term-months": "Between 1 and 600 months.",
        "interest-rate": "Between 0% and 40%.",
        "draw-months": "Shorter than the term.",
    }
    assert page.locator("#f-original-principal-err").count() == 0
    assert page.locator(".dialog").count() == 1
    # Corrected, it is made, with its terms.
    page.fill("#f-original-principal", "40000")
    page.fill("#f-term-months", "300")
    page.fill("#f-interest-rate", "8.25")
    page.fill("#f-draw-months", "120")
    page.click(".dialog footer button.primary")
    page.wait_for_url("**/ui/accounts/Acct_*")
    a = next(x for x in h.c.get("/ui/api/accounts").json()["items"] if x["name"] == "Refused HELOC")
    new_loan.ids.append(a["id"])
    t = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["terms"]
    assert (t["principal"], t["termMonths"], t["rate"], t["drawMonths"]) == (40000, 300, 8.25, 120)
    wait(page, '.card.facts:has-text("interest only until")', problems)
    assert [p for p in problems if not p.startswith("422 for")] == []
    page.close()


def test_resets_and_recasts_are_typed_in_the_terms(browser, household, new_loan):
    h = household
    a = fixed(new_loan, "Resets mortgage")
    form = 'form.draft-form:has-text("Loan terms")'
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}/settings", form)
    resets = page.locator('.mt:has(> .toolbar b:text("Rate resets"))')
    recasts = page.locator('.mt:has(> .toolbar b:text("Recasts"))')
    assert "An adjustable rate's new rate from a date" in resets.inner_text()
    assert "The servicer re-amortizes the balance" in recasts.inner_text()
    page.get_by_role("button", name="Add a reset").click()
    page.fill("#x-rate-date-0", "2029-01-01")
    page.fill("#x-rate-0", "7.25%")
    page.get_by_role("button", name="Add a recast").click()
    page.fill("#x-fee-date-0", "2027-06-01")
    page.fill("#x-fee-0", "$250")
    assert "An adjustable rate's new rate" not in resets.inner_text()
    page.click(f"{form} button.primary:enabled")
    wait(page, '.toast:has-text("Saved")', problems)
    t = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["terms"]
    assert t["resets"] == [{"date": "2029-01-01", "rate": 7.25}]
    assert t["recasts"] == [{"date": "2027-06-01", "fee": 250}]
    # The reset taken away again; the recast stays.
    wait(page, "#x-rate-date-0", problems)
    resets.get_by_role("button", name="Remove").click()
    assert page.locator("#x-rate-date-0").count() == 0
    page.click(f"{form} button.primary:enabled")
    wait(page, '.toast:has-text("Saved")', problems)
    t = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["terms"]
    assert t["resets"] == [] and t["recasts"] == [{"date": "2027-06-01", "fee": 250}]
    assert problems == []
    page.close()


def test_the_payments_setting_and_a_payment_missed(browser, household, new_loan):
    """S1.9.3: a payment recorded, Automatic reads as recorded here: the days after it with
    none recorded are missed on the Schedule, and the Overview says how many and what is
    overdue. Payments in Settings names what Automatic reads as; assumed as scheduled, nothing
    is missed."""
    h = household
    a = new_loan("Missed mortgage", principal="200000", startDate=f"{months_back(4)}-01",
                 termMonths=360, rate="6")  # fmt: skip
    due = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["total"]
    assert loan_payment(h.c, a["id"], f"{months_back(3)}-01", due).status_code == 200
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    assert v["paymentsResolved"] == "recorded" and v["missed"] >= 2
    # The Overview: how many are missed and what is overdue, the pill and the amount apart.
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", "#loan-missed")
    assert flat(page.locator("#loan-missed").inner_text()) == (
        f"Missed {v['missed']} payments {money(v['overdue'])} overdue"
    )
    # The Schedule: each a row marked missed, with what was due and the balance as it was.
    tab(page, problems, "Schedule", 'table:has(caption:text("Amortization schedule"))')
    rows = page.locator('table:has(caption:text("Amortization schedule")) tbody tr')
    missed = [r for r in v["rows"] if r["status"] == "missed"]
    shown = rows.filter(has=page.locator(".pill.bad"))
    assert shown.count() == min(len(missed), 3)
    last = missed[-1]
    cells = shown.last.locator("td").all_inner_texts()
    assert cells[0] == f"{day(last['date'])} missed" and cells[-1] == money(v["balance"])
    assert cells[1] == money(last["payment"]) and shown.last.get_attribute("class") == ""
    # Settings: Automatic names what it reads as; assumed as scheduled, nothing is missed.
    form = 'form.draft-form:has-text("Loan terms")'
    tab(page, problems, "Settings", form)
    wait(page, '#f-payments-mode option:text("Automatic: recorded here")', problems,
         state="attached")  # fmt: skip
    options = page.locator("#f-payments-mode option").all_inner_texts()
    assert options == ["Automatic: recorded here", "Recorded here", "Assumed as scheduled"]
    assert page.locator("#f-payments-mode").input_value() == ""
    page.select_option("#f-payments-mode", "assumed")
    page.click(f"{form} button.primary:enabled")
    wait(page, '.toast:has-text("Saved")', problems)
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    assert v["terms"]["paymentsMode"] == "assumed" and v["missed"] == 0
    tab(page, problems, "Overview", '.card.facts:has(h3:has-text("Loan"))')
    assert page.locator("#loan-missed").count() == 0
    # Back to Automatic: recorded here again.
    tab(page, problems, "Settings", form)
    page.select_option("#f-payments-mode", "")
    page.click(f"{form} button.primary:enabled")
    wait(page, '.toast:has-text("Saved")', problems)
    v = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    assert v["terms"]["paymentsMode"] is None and v["missed"] >= 2
    assert problems == []
    page.close()


# ---------- the Overview's dialogs ----------


def test_the_servicers_balance_is_typed_and_checked(browser, household, new_loan):
    h = household
    # Made last month: $300,000 owed until its first payment day, this month's (none recorded,
    # it then counts as paid as scheduled, S1.9.3).
    a = new_loan("Servicer mortgage", principal="300000", startDate=f"{months_back(1)}-01",
                 termMonths=360, rate="6")  # fmt: skip
    facts = '.card.facts:has(h3:has-text("Loan"))'
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}", facts)
    row = page.locator(f'{facts} .list-item:has-text("Servicer\'s balance")')
    assert flat(row.inner_text()) == "Servicer's balance not typed Type it"
    row.get_by_role("button", name="Type it").click()
    wait(page, ".dialog #f-owed", problems)
    dialog = page.locator(".dialog")
    assert "The principal still owed, from the servicer's statement" in dialog.inner_text()
    earlier = f"{months_back(1)}-15"
    page.fill("#f-as-of", earlier)
    page.fill("#f-owed", "300,000")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    wait(page, f"{facts} .pill.ok", problems)
    assert flat(row.inner_text()) == (
        f"Servicer's balance $300,000.00 on {day(earlier)} matches Type it"
    )
    # A later statement, $1,000 under the schedule's balance.
    row.get_by_role("button", name="Type it").click()
    wait(page, ".dialog #f-owed", problems)
    as_of = page.locator("#f-as-of").input_value()
    page.fill("#f-owed", "299000")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    wait(page, f"{facts} .pill.warn", problems)
    # A later statement, $299,000, against the schedule's balance that day.
    s = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["servicer"]
    assert s["date"] == as_of and Decimal(str(s["difference"])) == 299000 - Decimal(
        str(s["computed"])
    )
    assert flat(row.inner_text()) == f"Servicer's balance $299,000.00 on {day(as_of)} off by " \
        f"{money(s['difference'])} Type it"  # fmt: skip
    assert problems == []
    page.close()


def test_a_payments_split_is_corrected_before_it_is_recorded(browser, household, new_loan):
    h = household
    a = new_loan("Split auto loan", type="auto-loan", principal="18000",
                 startDate=f"{months_back(2)}-01", termMonths=60, rate="6")  # fmt: skip
    due = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()
    page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}",
                               'button:has-text("Record a payment")')  # fmt: skip
    page.click('button:has-text("Record a payment")')
    wait(page, ".dialog #f-from-account", problems)
    hint = page.locator('.dialog .toolbar:has(button:text("Show the split")) .small')
    assert hint.inner_text() == "The schedule splits it into principal, interest, escrow and PMI."
    wait(page, '.dialog button:text("Show the split"):enabled', problems)
    page.click('.dialog button:text("Show the split")')
    wait(page, "#x-part-principal", problems)
    assert hint.inner_text() == (
        "Split by the schedule. Correct it from the servicer’s statement if it differs."
    )
    principal = Decimal(page.locator("#x-part-principal").input_value())
    interest = Decimal(page.locator("#x-part-interest").input_value())
    assert principal + interest == Decimal(str(due["total"]))
    # The servicer's statement put $10 more to interest.
    page.fill("#x-part-principal", str(principal - 10))
    page.fill("#x-part-interest", str(interest + 10))
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    (t,) = h.c.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    assert t["kind"] == "deposit" and t["transferAccountName"] is None
    got = sorted(Decimal(str(x["amount"])) for x in t["splits"])
    assert got == sorted([principal - 10, interest + 10])
    assert problems == []
    page.close()
