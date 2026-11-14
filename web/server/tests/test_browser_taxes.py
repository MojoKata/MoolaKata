"""The tax panels show the API's figures (requirements S8.1–S8.13; the filed tax years walk,
decision 3.5): a book of sales of several shapes, each panel opened, its figures held to what
the API answers. The account and book are taken away again, so the shared household's other
figures stay as they were.
"""

import re
from decimal import Decimal

import pytest
from browser import made, months_back, signed_in, wait
from edits import make, remove

pytestmark = pytest.mark.browser


def _money(text: str) -> Decimal:
    """A money cell as shown ($1,234.56, −$12.00, +$5.00), as a number."""
    t = text.replace("−", "-").replace(",", "").replace("$", "").replace("+", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", t)
    assert m, text
    return Decimal(m.group(0))


def test_the_tax_panels_show_the_apis_figures(browser, household):
    h = household
    year = int(months_back(0)[:4]) - 2
    me = h.c.get("/ui/api/session").json()["user"]["id"]
    acct = made(make(h.c, "Acct", name="Panels", type="brokerage"))

    def trade(day, kind, symbol, qty, price):
        cents = int(Decimal(price) * 100) * qty
        amount = f"{'-' if kind == 'buy' else ''}{cents // 100}.{cents % 100:02d}"
        made(make(h.c, "Txn", accountId=acct["id"], date=day, kind=kind, symbol=symbol,
                  quantity=str(qty), price=price, amount=amount))  # fmt: skip

    # A short gain, a long loss washed by a buy ten days later, a fund bought before 2012.
    trade(f"{year}-02-03", "buy", "IBM", 10, "100")
    trade(f"{year}-06-02", "sell", "IBM", 10, "130")
    trade(f"{year - 2}-03-04", "buy", "KO", 10, "60")
    trade(f"{year}-09-01", "sell", "KO", 10, "50")
    trade(f"{year}-09-11", "buy", "KO", 4, "51")
    trade("2011-05-02", "buy", "FSKAX", 5, "20")
    trade(f"{year}-11-02", "sell", "FSKAX", 5, "90")
    book = made(make(h.c, "TaxBk", year=year, filers=[me]))
    try:
        api = h.c.get(f"/ui/api/tax-books/{book['id']}/panels").json()
        page, problems = signed_in(browser, h, "/ui/taxes/gains", "#f-tax-book")
        page.select_option("#f-tax-book", book["id"])
        wait(page, 'table:has(caption:text("Form 8949 rows")) tbody tr', problems)
        shown = page.locator('table:has(caption:text("Form 8949 rows")) tbody tr')
        assert shown.count() == len(api["rows"])
        got = []
        for i in range(shown.count()):
            cells = shown.nth(i).locator("td")
            got.append((cells.nth(0).inner_text(), cells.nth(1).inner_text().split("\n")[0],
                        _money(cells.nth(4).inner_text()), _money(cells.nth(5).inner_text()),
                        _money(cells.nth(8).inner_text())))  # fmt: skip
        want = [
            (r["box"], r["description"], Decimal(str(r["proceeds"])), Decimal(str(r["basis"])),
             Decimal(str(r["gain"])))
            for r in api["rows"]
        ]  # fmt: skip
        assert sorted(got) == sorted(want)
        assert {r["box"] for r in api["rows"]} >= {"A", "D", "E"}
        facts = page.locator(".card.facts").inner_text()
        for x in api["scheduleD"]["boxes"]:
            assert f"Box {x['box']}" in facts
        washes = page.locator('.card:has(h3:text("Wash Sales"))').inner_text()
        assert all(w["symbol"] in washes for w in api["washes"]) and api["washes"]
        # Every other panel draws without a fault.
        for tab in ("income", "retirement", "deductions", "giving", "education", "property"):
            page.goto(h.base + f"/ui/taxes/{tab}")
            wait(page, "main .card", problems)
        page.goto(h.base + "/ui/taxes/summary")
        wait(page, "main .card", problems)
        assert problems == []
        page.close()
    finally:
        made(remove(h.c, "TaxBk", h.c.get(f"/ui/api/tax-books/{book['id']}").json()))
        made(remove(h.c, "Acct", h.c.get(f"/ui/api/accounts/{acct['id']}").json(), confirm=True))


def test_the_retirement_and_income_panels_show_moves_and_new_kinds(browser, household):
    """CR3-37, CR3-38: a conversion and a rollover listed apart from the contributions, an
    HSA's coverage in its limit's note; foreign tax and crypto income on the Income panel."""
    h = household
    year = int(months_back(0)[:4]) - 3
    me = h.c.get("/ui/api/session").json()["user"]["id"]
    made_ids = []

    def acct(name, kind, **kw):
        a = made(make(h.c, "Acct", name=name, type=kind, **kw))
        made_ids.append(a["id"])
        return a["id"]

    def txn(account, day, amount, **kw):
        return made(make(h.c, "Txn", accountId=account, date=day, amount=amount, **kw))

    trad, roth, hsa = (
        acct("Panel IRA", "ira"),
        acct("Panel Roth", "roth-ira"),
        acct("Panel HSA", "hsa"),
    )
    brk = acct("Panel broker", "brokerage", institution="Panel Fidelity")
    ex = acct("Panel exchange", "crypto-exchange")
    txn(trad, f"{year}-01-05", "20000.00", kind="deposit", contributionYear=year - 1)
    txn(trad, f"{year}-03-02", "-15000.00", kind="transfer", payee="Conversion")
    txn(roth, f"{year}-03-02", "15000.00", kind="transfer", payee="Conversion")
    txn(roth, f"{year}-06-01", "4000.00", kind="deposit", contributionSource="rollover")
    txn(hsa, f"{year}-02-01", "3000.00", kind="deposit")
    txn(brk, f"{year}-06-30", "-12.34", kind="foreign-tax", symbol="VXUS")
    txn(ex, f"{year}-04-01", "0.00", kind="reward", symbol="ETH", quantity="0.01", price="2000")
    book = made(make(h.c, "TaxBk", year=year, filers=[me]))
    try:
        page, problems = signed_in(browser, h, "/ui/taxes/retirement", "#f-tax-book")
        page.select_option("#f-tax-book", book["id"])
        wait(page, '.card:has(h3:text("Roth Conversions")) .list-item', problems)
        conv = page.locator('.card:has(h3:text("Roth Conversions"))').inner_text()
        assert "Panel IRA → Panel Roth" in conv
        roll = page.locator('.card:has(h3:text("Rollovers"))').inner_text()
        assert "another account → Panel Roth" in roll
        assert "set the coverage" in page.locator("table.t").inner_text()
        page.goto(h.base + "/ui/taxes/income")
        wait(page, '.card:has(h3:text("Foreign tax paid")) .list-item', problems)
        assert (
            "Panel Fidelity" in page.locator('.card:has(h3:text("Foreign tax paid"))').inner_text()
        )
        assert "Panel exchange" in page.locator('.card:has(h3:text("Crypto Income"))').inner_text()
        assert problems == []
        page.close()
    finally:
        made(remove(h.c, "TaxBk", h.c.get(f"/ui/api/tax-books/{book['id']}").json()))
        for a in made_ids:
            made(remove(h.c, "Acct", h.c.get(f"/ui/api/accounts/{a}").json(), confirm=True))


def test_a_transfer_in_takes_its_lots_as_bought(browser, household):
    """CR3-73: the transaction dialog's shares moved in take their lots, each with its day
    bought, and the saved lot keeps it."""
    h = household
    a = made(make(h.c, "Acct", name="Lots broker", type="brokerage"))
    try:
        page, problems = signed_in(browser, h, f"/ui/accounts/{a['id']}/transactions", "main")
        page.get_by_role("button", name="Add").first.click()
        dialog = page.locator(".dialog")
        dialog.locator("#f-kind").select_option("transfer-in")
        dialog.locator("#f-symbol").fill("VTI")
        dialog.locator("#f-quantity").fill("10")
        dialog.locator("#f-amount").fill("0")
        dialog.get_by_role("button", name="Add a Lot").click()
        dialog.get_by_label("Lot 1: bought on").fill("2019-03-04")
        dialog.get_by_label("Lot 1: quantity").fill("10")
        dialog.get_by_label("Lot 1: cost basis").fill("1500")
        dialog.locator("footer button.primary").click()
        wait(page, ".dialog", problems, state="detached")
        [vti] = h.c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"]
        lots = [(x["acquiredOn"], Decimal(str(x["basis"]))) for x in vti["lots"]]
        assert lots == [("2019-03-04", Decimal("1500"))]
        assert problems == []
        page.close()
    finally:
        made(remove(h.c, "Acct", h.c.get(f"/ui/api/accounts/{a['id']}").json(), confirm=True))
