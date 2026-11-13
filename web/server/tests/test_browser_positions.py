"""Positions, strategies and portfolios as they show, driven in headless Chromium (requirements
S3, S5, S17.5.2): one screen state a test, each on its own accounts and symbols in the shared
household, so what the test reads is its own whatever ran before it."""

import re
from decimal import Decimal

import pytest
from browser import Household, made, months_back, signed_in, wait
from edits import create, make, option_trade, saved

pytestmark = pytest.mark.browser

# An expiry still to come, and the days trades are made on: all in the past, on the real clock.
LATER = f"{int(months_back(0)[:4]) + 1}-03-19"
OPENED, CLOSED = f"{months_back(2)}-03", f"{months_back(1)}-03"


def brokerage(h: Household, name: str) -> str:
    return made(make(h.c, "Acct", name=name, type="brokerage"))["id"]


def trade(h: Household, acct: str, day: str, kind: str, symbol: str, qty, price) -> dict:
    """Shares bought or sold, the cash the trade comes to its amount."""
    cash = Decimal(str(qty)) * Decimal(str(price))
    amount = f"{-cash if kind == 'buy' else cash:.2f}"
    return saved(create(h.c, "Txn", accountId=acct, date=day, kind=kind, symbol=symbol,
                        quantity=str(qty), price=str(price), amount=amount))  # fmt: skip


def moved_in(h: Household, acct: str, day: str, symbol: str, qty) -> dict:
    """Shares moved in with neither their basis nor the day they were bought."""
    return saved(create(h.c, "Txn", accountId=acct, date=day, kind="transfer-in", symbol=symbol,
                        quantity=str(qty), amount="0"))  # fmt: skip


def option(h, acct, day, action, sym, right, strike, expiry=LATER, contracts="1", premium="1.00"):
    return saved(option_trade(h.c, acct, day, action, sym, right, strike, expiry, contracts,
                              premium))  # fmt: skip


def open_rows(h: Household, acct: str) -> list[dict]:
    return [r for r in h.c.get("/ui/api/positions").json()["open"] if r["accountId"] == acct]


def legs_of(h: Household, acct: str) -> list[dict]:
    """The account's open option rows as legs to group."""
    return [{"instrumentId": r["instrumentId"]} for r in open_rows(h, acct)
            if r["instrumentClass"] == "option"]  # fmt: skip


def strategies_of(h: Household, acct: str) -> list[dict]:
    v = h.c.get("/ui/api/positions/strategies").json()
    return [x for x in v["strategies"] if x["accountId"] == acct]


def row(page, text: str):
    return page.locator("main tbody tr", has_text=text).first


def toast(page, text: str, problems: list) -> None:
    wait(page, f'.toast:has-text("{text}")', problems)


# ---------- Positions: open ----------


def test_an_open_holdings_lots_show_their_terms_one_moved_in_unknown(browser, household):
    # S3.1, CR3-73: a lot bought years ago is long term, a newer one short; shares moved in
    # without the day bought are a lot whose term is unknown and whose basis is missing, so the
    # row's cost is missing and its term unknown. Enter on its symbol opens its lots.
    h = household
    acct = brokerage(h, "Lots held")
    trade(h, acct, f"{months_back(30)}-03", "buy", "ZLT", 10, 100)
    trade(h, acct, OPENED, "buy", "ZLT", 10, 120)
    trade(h, acct, CLOSED, "sell", "ZLT", 5, 130)
    moved_in(h, acct, CLOSED, "ZLT", 5)
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZLT")
    r = row(page, "ZLT")
    assert "Unknown: when bought is missing" in r.inner_text()
    assert "missing" in r.locator("td").nth(5).inner_text()
    r.locator("button.linklike").first.focus()
    page.keyboard.press("Enter")
    wait(page, 'main tr button[aria-expanded="true"]', problems)
    lots = page.locator("main .list-item").all_inner_texts()
    assert len(lots) == 3
    assert any("bought" in x and "long term" in x for x in lots), lots
    assert any("bought" in x and "short term" in x for x in lots), lots
    assert any("moved in" in x and "when bought is missing, term unknown" in x for x in lots)
    assert page.locator("main .list-item .pill.warn", has_text="no basis").count() == 1
    assert page.locator("main :text('Realized so far')").count() == 1
    assert problems == []
    page.close()


def test_a_wash_sales_replacement_lot_is_held_from_the_sold_shares_day(browser, household):
    # S3.8: a loss sold and bought back within 30 days: the replacement lot is held from the
    # day the sold shares were, a wash sale, and its term counts from then.
    h = household
    acct = brokerage(h, "Washed open")
    first = f"{months_back(14)}-03"
    trade(h, acct, first, "buy", "ZWO", 10, 200)
    trade(h, acct, f"{months_back(1)}-03", "sell", "ZWO", 10, 150)
    trade(h, acct, f"{months_back(1)}-10", "buy", "ZWO", 4, 155)
    (held,) = open_rows(h, acct)
    assert held["lots"][0]["heldFrom"] is not None
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZWO")
    row(page, "ZWO").locator("button.linklike").first.click()
    wait(page, "main .list-item", problems)
    lot = page.locator("main .list-item").first.inner_text()
    assert "(a wash sale)" in lot and "held from" in lot and "long term" in lot, lot
    assert problems == []
    page.close()


def test_an_open_option_shows_its_days_and_whether_it_is_in_the_money(browser, household):
    # S3.1, S3.6: an open option's row: days to expiry, in or out of the money against the
    # underlying's last trade, short or long; one past its expiry says so.
    h = household
    acct = brokerage(h, "Option rows")
    trade(h, acct, OPENED, "buy", "ZOR", 100, 100)
    option(h, acct, OPENED, "sell-to-open", "ZOR", "put", "120")  # in the money
    option(h, acct, OPENED, "buy-to-open", "ZOR", "call", "150")  # out of it
    option(h, acct, OPENED, "buy-to-open", "ZOR", "call", "90", expiry=f"{months_back(1)}-15")
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZOR")
    put = row(page, re.compile(r"ZOR \S+ 120 P"))
    assert "ITM" in put.inner_text() and "Short" in put.inner_text()
    assert re.search(r"\d+d", put.locator("td").nth(1).inner_text())
    call = row(page, re.compile(r"ZOR \S+ 150 C"))
    assert "OTM" in call.inner_text() and "Long" in call.inner_text()
    assert "expired" in row(page, re.compile(r"ZOR \S+ 90 C")).inner_text()
    assert problems == []
    page.close()


def test_an_options_mark_typed_is_its_value_until_a_close(browser, household):
    # S3.7, S4.10: Type a mark… records a price for the day; the option is valued at it, its
    # source a typed mark.
    h = household
    acct = brokerage(h, "Marked")
    option(h, acct, OPENED, "buy-to-open", "ZMK", "call", "75", premium="2.00")
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZMK")
    row(page, "ZMK").locator("button.linklike").first.click()
    page.get_by_role("button", name="Type a mark…").click()
    wait(page, "#f-mark-price", problems)
    assert page.locator(".dialog").inner_text().startswith("Mark ZMK")
    page.fill("#f-mark-price", "3.25")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    toast(page, "marked", problems)
    wait(page, 'main tbody tr:has-text("ZMK"):has-text("typed mark")', problems)
    (held,) = open_rows(h, acct)
    assert (Decimal(str(held["value"])), held["priceSource"]) == (Decimal("325"), "manual")
    assert "$325.00" in row(page, "ZMK").inner_text()
    assert problems == []
    page.close()


def test_a_mark_typed_today_opens_to_be_changed(browser, household):
    # S4.10: a price typed for the day is changed, not typed again.
    h = household
    acct = brokerage(h, "Marked again")
    option(h, acct, OPENED, "buy-to-open", "ZMA", "call", "75", premium="2.00")
    (held,) = open_rows(h, acct)
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZMA")
    today = page.evaluate("new Date().toLocaleDateString('en-CA')")
    saved(create(h.c, "TyPrc", instrumentId=held["instrumentId"], date=today, close="3.25"))
    page.reload()
    wait(page, 'main tbody tr:has-text("ZMA"):has-text("typed mark")', problems)
    row(page, "ZMA").locator("button.linklike").first.click()
    page.get_by_role("button", name="Type a mark…").click()
    wait(page, "#f-mark-price", problems)
    assert Decimal(page.input_value("#f-mark-price")) == Decimal("3.25")
    page.fill("#f-mark-price", "4")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    toast(page, "marked", problems)
    wait(page, 'main tbody tr:has-text("ZMA"):has-text("$400.00")', problems)
    prices = h.c.get(f"/ui/api/instruments/{held['instrumentId']}/prices",
                     params={"from": today, "to": today}).json()["items"]  # fmt: skip
    assert [Decimal(str(x["close"])) for x in prices if x.get("id")] == [Decimal(4)]
    assert problems == []
    page.close()


def test_a_bitcoin_holding_shows_under_crypto_to_the_satoshi(browser, household):
    # S3.1, S1.6: Show Crypto keeps the crypto rows; bitcoin's quantity is to 8 places.
    h = household
    acct = made(make(h.c, "Acct", name="Coin desk", type="crypto-exchange"))["id"]
    trade(h, acct, OPENED, "buy", "BTC", "0.12345678", 60000)
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=Coin desk")
    page.locator('.chips[aria-label="Show"]').get_by_role("button", name="Crypto").click()
    wait(page, '.chips[aria-label="Show"] button[aria-pressed="true"]:has-text("Crypto")',
         problems)  # fmt: skip
    wait(page, 'main tbody tr:has-text("ZLT")', problems, state="detached")
    cells = row(page, "Coin desk").locator("td").all_inner_texts()
    assert cells[1].startswith("BTC") and "0.12345678" in cells[4], cells
    assert problems == []
    page.close()


def test_legs_selected_on_the_open_tab_are_grouped_as_a_strategy(browser, household):
    # S3.5.1: legs ticked on the Open tab are grouped by hand.
    h = household
    acct = brokerage(h, "Hand grouped")
    option(h, acct, OPENED, "sell-to-open", "ZHG", "call", "60", premium="2.00")
    option(h, acct, OPENED, "buy-to-open", "ZHG", "call", "70", premium="0.80")
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=ZHG")
    for r in open_rows(h, acct):
        page.get_by_label(f"Select {r['symbol']}").check()
    wait(page, 'main :text("2 selected")', problems)
    page.get_by_role("button", name="Group 2 legs").click()
    toast(page, "Grouped as a strategy", problems)
    wait(page, 'main :text("2 selected")', problems, state="detached")
    (st,) = strategies_of(h, acct)
    assert (st["shape"], len(st["legs"])) == ("Bear call spread", 2)
    assert problems == []
    page.close()


def test_an_option_trade_recorded_from_positions_says_what_it_comes_to(browser, household):
    # S3.2: the dialog from Positions, the trade chosen, the cash paid said as it is typed.
    h = household
    acct = brokerage(h, "Desk")
    page, problems = signed_in(
        browser, h, "/ui/positions/open", 'button:has-text("Record an option trade")'
    )
    page.click('button:has-text("Record an option trade")')
    wait(page, "#f-underlying", problems)
    page.select_option("#f-account", label="Desk")
    page.get_by_role("radio", name="Buy to open").click()
    assert "negative lot" not in page.locator(".dialog").inner_text()
    page.fill("#f-underlying", "ZDK")
    page.select_option("#f-right", "call")
    page.fill("#f-strike", "45")
    page.fill("#f-expiry", LATER)
    page.fill("#f-contracts", "2")
    page.fill("#f-premium", "1.2x")
    assert "Paid:" not in page.locator(".dialog").inner_text()
    page.fill("#f-premium", "1.25")
    wait(page, '.dialog :text("Paid: $250.65.")', problems)
    # Fees cleared are refused, never read as none; ↺ puts the $0.65 back (R3.11, CR3-437).
    reset = page.get_by_role("button", name="Use the default: $0.65")
    assert reset.count() == 0
    page.fill("#f-fees", "")
    page.click(".dialog footer button.primary")
    wait(page, '.dialog :text("Zero or more.")', problems)
    reset.click()
    assert page.input_value("#f-fees") == "0.65"
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    items = h.c.get("/ui/api/transactions", params={"account": acct}).json()["items"]
    (t,) = items
    assert (t["kind"], t["amount"]) == ("buy-to-open", -250.65)
    assert t["symbol"].startswith("ZDK ") and t["symbol"].endswith(" 45 C")
    # The one refusal: the fees cleared.
    assert [p for p in problems if not p.startswith("422 for")] == []
    page.close()


# ---------- Positions: an option's end ----------


@pytest.mark.parametrize(
    ("how", "action", "right", "strike", "said", "after"),
    [
        ("expired", "buy-to-open", "put", "50", "The premium paid is lost.", "expired"),
        ("assigned", "sell-to-open", "put", "120", "The shares are bought or sold", "assigned"),
        ("exercised", "buy-to-open", "call", "80", "The shares are bought or sold", "exercised"),
    ],
)
def test_an_options_end_is_recorded_as_it_happened(
    browser, household, how, action, right, strike, said, after
):
    # S3.4, S3.6: out of the money it starts as expired, in it as assigned (short) or
    # exercised (long); All fills in the contracts held; the end closes the option as it was.
    h = household
    sym = {"expired": "ZXP", "assigned": "ZAS", "exercised": "ZXC"}[how]
    acct = brokerage(h, f"Ends {how}")
    trade(h, acct, f"{months_back(3)}-03", "buy", sym, 100, 100)
    option(h, acct, OPENED, action, sym, right, strike, expiry=f"{months_back(1)}-15",
           contracts="2")  # fmt: skip
    page, problems = signed_in(browser, h, "/ui/positions/open", f"text={sym}")
    row(page, re.compile(rf"{sym} \S+ {strike} [PC]")).locator("button.linklike").first.click()
    page.get_by_role("button", name="Expired, assigned or exercised…").click()
    wait(page, ".dialog .value-input input", problems)
    checked = page.locator('.dialog [role="radio"][aria-checked="true"]').inner_text()
    assert checked == {"expired": "Expired worthless", "assigned": "Assigned",
                       "exercised": "Exercised"}[how]  # fmt: skip
    assert said in page.locator(".dialog").inner_text()
    if how == "assigned":
        page.get_by_role("radio", name="Expired worthless").click()
        assert "The credit is kept as a gain." in page.locator(".dialog").inner_text()
        page.get_by_role("radio", name="Assigned").click()
    page.get_by_role("button", name="All: 2 contracts").click()
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    toast(page, "recorded", problems)
    # Expired, the option's gain or loss is realized; assigned or exercised, the premium is
    # folded into the shares' basis, so nothing closes but the option.
    closed = [r for r in h.c.get("/ui/api/positions").json()["closed"] if r["accountId"] == acct]
    assert [r["how"] for r in closed] == ([after] if how == "expired" else [])
    shares = {r["symbol"]: Decimal(str(r["quantity"])) for r in open_rows(h, acct)}
    assert shares == {sym: Decimal(100 if how == "expired" else 300)}
    assert problems == []
    page.close()


# ---------- Positions: closed, trades and gains ----------


def test_closed_sales_say_how_a_wash_disallowed_and_a_term_unknown(browser, household):
    # S3.1, S3.8: a loss partly washed shows what was disallowed; shares moved in without their
    # basis or day, sold, show the cost missing and the term unknown; a short bought back.
    h = household
    acct = brokerage(h, "Closings")
    trade(h, acct, f"{months_back(14)}-03", "buy", "ZWC", 10, 200)
    trade(h, acct, f"{months_back(1)}-03", "sell", "ZWC", 10, 150)
    trade(h, acct, f"{months_back(1)}-10", "buy", "ZWC", 4, 155)
    moved_in(h, acct, f"{months_back(3)}-03", "ZUC", 5)
    trade(h, acct, f"{months_back(1)}-05", "sell", "ZUC", 5, 20)
    option(h, acct, OPENED, "sell-to-open", "ZBC", "put", "30", premium="1.50")
    option(h, acct, CLOSED, "buy-to-close", "ZBC", "put", "30", premium="0.50")
    page, problems = signed_in(browser, h, "/ui/positions/closed", "text=Realized, all shown")
    wash = row(page, "ZWC").inner_text()
    assert "sold" in wash and "Long term" in wash, wash
    assert re.search(r"W\s+\$200\.00 disallowed", wash), wash
    unknown = row(page, "ZUC")
    assert "Unknown: when bought is missing" in unknown.inner_text()
    assert unknown.locator(".pill.warn", has_text="missing").count() == 1
    assert unknown.locator("td").nth(7).inner_text().strip() == "—"
    assert "bought back" in row(page, "ZBC").inner_text()
    assert problems == []
    page.close()


def test_option_trades_show_the_closed_with_how_and_the_open_if_closed_now(browser, household):
    # S3.3: each option trade, closed with the day and how, or open with its P/L if closed now.
    h = household
    acct = brokerage(h, "Traded")
    option(h, acct, OPENED, "sell-to-open", "ZTR", "put", "40", premium="2.00")
    option(h, acct, CLOSED, "buy-to-close", "ZTR", "put", "40", premium="0.40")
    option(h, acct, OPENED, "sell-to-open", "ZTR", "put", "35", premium="1.00")
    page, problems = signed_in(browser, h, "/ui/positions/trades", "text=Capital required")
    done = row(page, re.compile(r"ZTR \S+ 40 P")).inner_text()
    assert "bought back" in done and "if closed now" not in done, done
    still = row(page, re.compile(r"ZTR \S+ 35 P")).inner_text()
    assert "open" in still and "if closed now" in still, still
    assert problems == []
    page.close()


def gains_sold(h: Household) -> None:
    """A gain short term and one long, sold last month in their own account (made again by
    each test: a test's accounts go when it ends)."""
    acct = brokerage(h, "Gains desk")
    trade(h, acct, f"{months_back(30)}-03", "buy", "ZGL", 10, 100)
    trade(h, acct, f"{months_back(3)}-03", "buy", "ZGS", 10, 50)
    trade(h, acct, CLOSED, "sell", "ZGL", 10, 130)
    trade(h, acct, CLOSED, "sell", "ZGS", 10, 45)


@pytest.mark.parametrize(
    ("by", "label", "unrealized"),
    [
        ("Month", None, "Unrealized, by account"),
        ("Account", "Gains desk", "Unrealized, by account"),
        ("Instrument", "ZGL", "Unrealized, by instrument"),
        ("Term", "Long term", "Unrealized, by account"),
    ],
)
def test_gains_are_grouped_as_chosen(browser, household, by, label, unrealized):
    # S3.9: realized gains by month, account, instrument or term; unrealized by account, or by
    # instrument when that is chosen.
    h = household
    gains_sold(h)
    page, problems = signed_in(browser, h, "/ui/positions/gains", "text=Realized")
    page.locator('.chips[aria-label="By"]').get_by_role("button", name=by, exact=True).click()
    wait(page, f'main h3:has-text("{unrealized}")', problems)
    year = CLOSED[:4]
    page.locator('.chips[aria-label="Year"]').get_by_role("button", name=year).click()
    wait(page, f'.chips[aria-label="Year"] button[aria-pressed="true"]:has-text("{year}")',
         problems)  # fmt: skip
    realized = page.locator("main .card", has=page.locator('h3:text-is("Realized")'))
    if label is None:
        import datetime as dt

        label = dt.date.fromisoformat(CLOSED).strftime("%B %Y")
    wait(page, f'main .card tbody td:text-is("{label}")', problems)
    labels = realized.locator("tbody tr td:first-child").all_inner_texts()
    assert label in labels, labels
    if by == "Instrument":
        assert "ZGS" in labels
        assert row(page, "ZGL").locator("td").nth(2).inner_text().startswith("+")
    assert problems == []
    page.close()


# ---------- Strategies ----------


def test_a_strategys_figures_open_and_closed(browser, household):
    # S3.5.4, S3.5.5: a bull put spread named by hand: its shape beside the name, max profit
    # and loss, breakeven, capital at risk now and at open; a closed one dim, its legs closed,
    # its return on the capital at risk at open.
    h = household
    acct = brokerage(h, "Spread figures")
    option(h, acct, OPENED, "sell-to-open", "ZSF", "put", "540", premium="2.00")
    option(h, acct, OPENED, "buy-to-open", "ZSF", "put", "530", premium="1.20")
    saved(create(h.c, "Strat", accountId=acct, legs=legs_of(h, acct), name="Income spread"))
    other = brokerage(h, "Spread closed")
    option(h, other, OPENED, "sell-to-open", "ZSC", "put", "100", premium="2.00")
    option(h, other, OPENED, "buy-to-open", "ZSC", "put", "90", premium="1.00")
    saved(create(h.c, "Strat", accountId=other, legs=legs_of(h, other)))
    option(h, other, CLOSED, "buy-to-close", "ZSC", "put", "100", premium="0.50")
    option(h, other, CLOSED, "sell-to-close", "ZSC", "put", "90", premium="0.10")
    page, problems = signed_in(browser, h, "/ui/positions/strategies", "text=Income spread")
    r = row(page, "Income spread")
    cells = r.locator("td").all_inner_texts()
    assert "(Bull put spread)" in cells[0] and "Spread figures" in cells[0]
    assert "Short 1 ZSF" in cells[0] and "Long 1 ZSF" in cells[0]
    assert cells[3].strip() == "$80" and cells[4].strip() == "$920"
    assert cells[5].strip() == "539.20"
    assert cells[6].strip() == "$920" and cells[7].startswith("$920")
    shut = row(page, "Spread closed")
    assert "dim" in (shut.get_attribute("class") or "")
    text = shut.locator("td").first.inner_text()
    assert " · closed " in text and text.count("· closed") >= 3, text
    figures = shut.locator("td").all_inner_texts()
    assert figures[6].strip() == "—"
    assert re.search(r"\$\d+\s+\d+(\.\d+)?%", figures[7]), figures[7]
    (st,) = strategies_of(h, other)
    assert st["returnPct"] is not None and st["closedOn"] == CLOSED
    assert page.locator("main tfoot", has_text="Open strategies").count() == 1
    assert problems == []
    page.close()


def test_a_strategy_without_a_limit_risks_an_unlimited_amount(browser, household):
    # S3.5.5, B12: a short straddle with no margin typed: its capital at risk, and so the
    # open strategies' total, is unlimited, never left out.
    h = household
    acct = brokerage(h, "Straddled")
    option(h, acct, OPENED, "sell-to-open", "ZST", "call", "50", premium="3.00")
    option(h, acct, OPENED, "sell-to-open", "ZST", "put", "50", premium="2.50")
    saved(create(h.c, "Strat", accountId=acct, legs=legs_of(h, acct)))
    page, problems = signed_in(browser, h, "/ui/positions/strategies", "text=Straddled")
    cells = row(page, "Straddled").locator("td").all_inner_texts()
    assert "Short straddle" in cells[0]
    assert cells[4].strip() == "unlimited" and cells[6].strip() == "unlimited"
    foot = page.locator("main tfoot tr").locator("td").all_inner_texts()
    assert foot[-3].strip() == "unlimited" and foot[-2].strip() == "unlimited"
    assert problems == []
    page.close()


@pytest.mark.parametrize("keep", [True, False], ids=["kept", "not a roll"])
def test_a_roll_is_proposed_and_kept_or_left_on_its_own(browser, household, keep):
    # S3.5.3: a leg closed and a new one opened the same day are offered as a roll; kept, the
    # new leg joins the strategy and the closed one stays in it; not a roll, it stands alone.
    h = household
    sym = "ZRK" if keep else "ZRN"
    acct = brokerage(h, f"Rolled {sym}")
    option(h, acct, OPENED, "sell-to-open", sym, "put", "540", premium="2.00")
    option(h, acct, OPENED, "buy-to-open", sym, "put", "530", premium="1.20")
    # Named, or not: a roll names the strategy as it is shown, by its shape without a name
    # (CR3-408).
    name = {"name": f"Spread {sym}"} if keep else {}
    saved(create(h.c, "Strat", accountId=acct, legs=legs_of(h, acct), **name))
    option(h, acct, CLOSED, "buy-to-close", sym, "put", "540", premium="1.00")
    option(h, acct, CLOSED, "sell-to-open", sym, "put", "535", premium="1.50")
    page, problems = signed_in(browser, h, "/ui/positions/strategies", f"text=Rolled {sym}")
    notice = page.locator(".notice", has_text=f"in Rolled {sym}")
    [shown] = strategies_of(h, acct)
    assert f"the day a leg of {shown['name']} on {sym} closed: a roll?" in notice.inner_text()
    assert notice.locator("b").inner_text() == shown["name"] != ""
    notice.get_by_role("button", name="Keep it in the strategy" if keep else "Not a roll").click()
    toast(page, "Rolled into the strategy" if keep else "Left on its own", problems)
    wait(page, f'.notice:has-text("in Rolled {sym}")', problems, state="detached")
    (st,) = strategies_of(h, acct)
    assert len(st["legs"]) == (3 if keep else 2)
    if keep:
        wait(page, f'main tbody tr:has-text("Rolled {sym}"):has-text("{sym}")', problems)
        legs = row(page, f"Rolled {sym}").locator("td").first.inner_text()
        assert "· closed" in legs and legs.count("Short 1") == 1, legs
    assert problems == []
    page.close()


def test_a_short_call_against_shares_is_offered_as_a_covered_call(browser, household):
    # S3.5.2: shares and a short call on them are offered as a covered call, the shares'
    # quantity named; Group them makes it.
    h = household
    acct = brokerage(h, "Covered")
    trade(h, acct, f"{months_back(3)}-03", "buy", "ZCC", 100, 40)
    option(h, acct, OPENED, "sell-to-open", "ZCC", "call", "50", premium="1.10")
    page, problems = signed_in(browser, h, "/ui/positions/strategies", "text=in Covered")
    notice = page.locator(".notice", has_text="in Covered")
    text = notice.inner_text()
    assert "2 legs on ZCC in Covered look like a covered call" in text, text
    assert "100 ZCC" in text
    notice.get_by_role("button", name="Group them").click()
    toast(page, "Grouped as a covered call", problems)
    (st,) = strategies_of(h, acct)
    assert st["shape"] == "Covered call"
    assert problems == []
    page.close()


def short_put_strategy(h: Household, name: str, sym: str) -> str:
    acct = brokerage(h, name)
    option(h, acct, OPENED, "sell-to-open", sym, "put", "25", premium="0.80")
    saved(create(h.c, "Strat", accountId=acct, legs=legs_of(h, acct)))
    return acct


def test_a_strategy_named_cash_secured_and_given_a_margin(browser, household):
    # S3.5.6: a strategy's dialog: its name (empty is its shape), cash-secured for a short
    # put, the margin typed.
    h = household
    acct = short_put_strategy(h, "Wheel desk", "ZWH")
    page, problems = signed_in(browser, h, "/ui/positions/strategies", "text=Wheel desk")
    row(page, "Wheel desk").locator(".row-tool").locator("button.linklike").first.click()
    wait(page, "#f-strategy-name", problems)
    assert "Empty: its shape, short put." in page.locator(".dialog").inner_text()
    page.fill("#f-strategy-name", "The wheel")
    page.get_by_role("switch", name="Cash-secured").click()
    page.fill("#f-margin-requirement", "2500")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    toast(page, "Saved", problems)
    wait(page, 'main tbody tr:has-text("The wheel")', problems)
    assert "(Cash-secured put)" in row(page, "The wheel").inner_text()
    (st,) = strategies_of(h, acct)
    assert (st["name"], st["cashSecured"]) == ("The wheel", True)
    assert Decimal(str(st["marginRequirement"])) == 2500
    assert problems == []
    page.close()


def test_a_strategy_ungrouped_leaves_its_legs(browser, household):
    # S3.5.6: Ungroup asks first, then the legs stand on their own.
    h = household
    acct = short_put_strategy(h, "Ungrouped desk", "ZUG")
    page, problems = signed_in(browser, h, "/ui/positions/strategies", "text=Ungrouped desk")
    row(page, "Ungrouped desk").locator(".row-tool").locator("button.linklike").first.click()
    wait(page, "#f-strategy-name", problems)
    page.get_by_role("button", name="Ungroup").click()
    page.get_by_role("button", name="No", exact=True).click()
    assert page.locator(".dialog").count() == 1 and len(strategies_of(h, acct)) == 1
    page.get_by_role("button", name="Ungroup").click()
    page.get_by_role("button", name="Yes, ungroup").click()
    wait(page, ".dialog", problems, state="detached")
    toast(page, "Ungrouped: the legs stand on their own", problems)  # CR3-407
    wait(page, 'main tbody tr:has-text("Ungrouped desk")', problems, state="detached")
    assert strategies_of(h, acct) == []
    assert len(open_rows(h, acct)) == 1
    assert problems == []
    page.close()


def test_an_adjusted_underlying_gives_its_contracts_a_new_root(browser, household):
    # S3.10.2: the OCC's adjustment typed in its dialog: each contract's new root and
    # deliverable; the lot carries over, and the strategy follows its leg to the new contract.
    h = household
    acct = short_put_strategy(h, "Adjusted desk", "ZAJ")
    page, problems = signed_in(
        browser, h, "/ui/positions/strategies", 'button:has-text("An underlying was adjusted")'
    )
    page.click('button:has-text("An underlying was adjusted")')
    wait(page, "#f-adjust-underlying", problems)
    page.select_option("#f-adjust-underlying", label="ZAJ")
    wait(page, '.dialog:has-text("Options on ZAJ after a corporate action")', problems)
    contract = page.locator(".dialog tbody tr", has_text="ZAJ ")
    assert "Short 1 in Adjusted desk" in contract.inner_text()
    assert contract.get_by_label("New root").input_value() == "ZAJ1"
    contract.get_by_label("Deliverable").fill("150 ZAJ + 20 zak")
    contract.get_by_label("Cash").fill("12.50")
    contract.get_by_label("Strike").fill("25.00")
    contract.get_by_label("New root").fill("Z-?")
    page.get_by_role("button", name="Adjust 1 contract").click()
    wait(page, '.dialog tbody .err:has-text("The new root, such as XYZ1.")', problems)
    assert [p for p in problems if "/options/adjust" not in p] == [] and len(problems) == 1
    problems.clear()
    contract.get_by_label("New root").fill("ZAJ1")
    page.get_by_role("button", name="Adjust 1 contract").click()
    wait(page, ".dialog", problems, state="detached")
    toast(page, "1 contract adjusted", problems)
    (held,) = open_rows(h, acct)
    assert held["symbol"].startswith("ZAJ1 "), held["symbol"]
    (st,) = strategies_of(h, acct)
    assert st["legs"][0]["symbol"].startswith("ZAJ1 ")
    wait(page, 'main tbody tr:has-text("Adjusted desk"):has-text("ZAJ1")', problems)
    assert problems == []
    page.close()


# ---------- Portfolios ----------


def test_a_portfolios_performance_shows_its_returns(browser, household):
    # S5.2: value, the returns time- and money-weighted, contributions apart from growth, the
    # chart against its benchmark, and returns by period, the portfolio's last and bold.
    h = household
    acct = brokerage(h, "Performing")
    trade(h, acct, f"{months_back(6)}-03", "buy", "ZPF", 10, 100)
    trade(h, acct, f"{months_back(1)}-03", "buy", "ZPF", 5, 120)
    p = made(make(h.c, "Portf", name="Growth", accountIds=[acct], benchmark="60-40"))
    page, problems = signed_in(
        browser, h, f"/ui/portfolios/{p['id']}", "text=Time-weighted returns by period"
    )
    wait(page, "main svg", problems)
    kpis = page.locator("main .kpi").all_inner_texts()
    assert "1 account" in kpis[0] and "Time-weighted return (1Y)" in kpis[1]
    assert "growth" in kpis[3]
    assert page.locator('main :text("Benchmark: ")').count() >= 1
    page.locator('.chips[aria-label="Range"]').get_by_role("button", name="3M").click()
    wait(page, 'main .kpi:has-text("Time-weighted return (3M)")', problems)
    rows = page.locator('main table:has(caption:text("Time-weighted")) tbody tr')
    assert rows.last.inner_text().startswith("Growth")
    assert rows.count() >= 2
    assert problems == []
    page.close()


def test_a_portfolios_holdings_with_options_items_a_loan_and_a_stale_price(browser, household):
    # S5.2, S4.7: shares with a typed price over 90 days old marked stale, bitcoin to the
    # satoshi, the home and the mortgage on their own rows, and the options' value with their
    # capital at risk.
    h = household
    acct = brokerage(h, "Held all")
    trade(h, acct, f"{months_back(6)}-03", "buy", "ZHS", 10, 100)
    (shares,) = open_rows(h, acct)
    saved(create(h.c, "TyPrc", instrumentId=shares["instrumentId"], date=f"{months_back(5)}-03",
                 close="110"))  # fmt: skip
    option(h, acct, OPENED, "sell-to-open", "ZHS", "put", "90", premium="2.00")
    coins = made(make(h.c, "Acct", name="Held coins", type="crypto-exchange"))["id"]
    trade(h, coins, OPENED, "buy", "BTC", "0.5", 60000)
    ids = [acct, coins, h.extra["homes"]["id"], h.extra["mortgage"]["id"]]
    p = made(make(h.c, "Portf", name="Everything", accountIds=ids, benchmark="60-40"))
    page, problems = signed_in(browser, h, f"/ui/portfolios/{p['id']}/holdings", "text=Total")
    stock = row(page, "ZHS")
    assert stock.locator(".pill.warn", has_text="stale").count() == 1
    assert "Held all" in stock.inner_text()
    assert row(page, "Held coins").locator("td").nth(2).inner_text() == "0.50000000 BTC"
    assert row(page, "1428 Elm St").locator("td").nth(1).inner_text() == "Item"
    assert row(page, "Owed on the loan").count() == 1
    risk = page.locator("main tfoot tr", has_text="Options · capital at risk").inner_text()
    assert "at risk" in risk and "unlimited" not in risk, risk
    tip = stock.locator("td").nth(3).get_attribute("data-tip")
    assert tip and "as of" in tip, tip
    assert problems == []
    page.close()


def test_a_portfolios_options_without_a_limit_risk_an_unlimited_amount(browser, household):
    # S5.2, S3.5.5: a call sold with no shares to cover it risks an unlimited amount.
    h = household
    acct = brokerage(h, "Naked call")
    option(h, acct, OPENED, "sell-to-open", "ZNC", "call", "70", premium="1.00")
    p = made(make(h.c, "Portf", name="Unlimited", accountIds=[acct], benchmark="60-40"))
    page, problems = signed_in(browser, h, f"/ui/portfolios/{p['id']}/holdings", "text=Total")
    risk = page.locator("main tfoot tr", has_text="Options · capital at risk").inner_text()
    assert "at risk unlimited" in risk, risk
    assert problems == []
    page.close()


def test_a_portfolio_of_accounts_holding_nothing_says_so(browser, household):
    h = household
    acct = brokerage(h, "Nothing held")
    p = made(make(h.c, "Portf", name="Empty one", accountIds=[acct], benchmark="60-40"))
    page, problems = signed_in(
        browser, h, f"/ui/portfolios/{p['id']}/holdings", "text=Nothing held in these accounts yet"
    )
    assert problems == []
    page.close()


def test_a_portfolios_projections_list_those_built_on_it(browser, household):
    # S5.2, S6: the Projections tab lists the projections built on the portfolio; one built
    # on none says where to make one.
    h = household
    p = h.extra["portfolio"]
    page, problems = signed_in(
        browser, h, f"/ui/portfolios/{p['id']}/projections", 'main a:has-text("Retire at 62")'
    )
    assert page.locator("main a.list-item", has_text="Retire at 62").locator(".pill").count() == 1
    acct = brokerage(h, "Unplanned")
    other = made(make(h.c, "Portf", name="Unplanned", accountIds=[acct], benchmark="60-40"))
    page.goto(h.base + f"/ui/portfolios/{other['id']}/projections")
    wait(page, 'main :text("No projection is built on it yet.")', problems)
    assert problems == []
    page.close()


def test_the_portfolios_list_and_a_new_portfolio(browser, household):
    # S5.1: All my accounts first, then each portfolio with its accounts counted and its
    # sharing marked; New portfolio makes one and opens it.
    h = household
    one, two = brokerage(h, "Listed one"), brokerage(h, "Listed two")
    made(make(h.c, "Portf", name="Two accounts", accountIds=[one, two], benchmark="60-40"))
    page, problems = signed_in(browser, h, "/ui/portfolios", "text=Two accounts")
    cards = page.locator("main a.card")
    assert "Your accounts, and shared ones you count" in cards.first.inner_text()
    assert "2 accounts" in page.locator("main a.card", has_text="Two accounts").inner_text()
    retirement = page.locator("main a.card", has_text="Retirement")
    assert "1 account" in retirement.inner_text()
    assert retirement.locator('[data-tip="Shared by me"]').count() == 1
    page.get_by_role("button", name="New portfolio").click()
    wait(page, "#f-name", problems)
    page.fill("#f-name", "Made here")
    page.locator(".dialog label.list-item", has_text="Listed one").locator("input").check()
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    toast(page, "Saved", problems)
    # Saved, the new portfolio opens, and stays open (CR3-406).
    page.wait_for_url(re.compile(r"/ui/portfolios/Portf_"))
    page.wait_for_timeout(1500)  # a late history.back() would land in this time
    assert re.search(r"/ui/portfolios/Portf_", page.url), page.url
    assert problems == []
    page.close()
