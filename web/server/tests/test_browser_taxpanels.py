"""Each tax panel in its states (requirements S8.1–S8.18): a year of sales, income, retirement
money, deductions, giving, a 529, loans and filings, and a year with nothing in it, each panel
opened and held to the figures and words a user reads. The accounts and books are the
module's own, taken away after, so the shared household's other figures stay as they were.
"""

import re
from decimal import Decimal

import pytest
from browser import made, months_back, signed_in, wait
from edits import change, create, loan_payment, make, plan529, remove, saved, sell, terms

pytestmark = pytest.mark.browser

YEAR = 2021  # the year with everything in it
EMPTY = 2020  # nothing happens in it; its federal return carries figures into YEAR


def _money(text: str) -> Decimal:
    t = text.replace("−", "-").replace(",", "").replace("$", "").replace("+", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", t)
    assert m, text
    return Decimal(m.group(0))


class World:
    """The module's own accounts, books, people and donations in the shared household, and
    what to put back after."""

    def __init__(self, h):
        self.h, self.c = h, h.c
        self.accounts: dict[str, dict] = {}
        self.books: dict[int, dict] = {}
        self.persons: list[str] = []
        self.donations: list[dict] = []
        self.cats: dict[str, str] = {}  # a category of each tax tag
        self.person: dict | None = None  # the owner's, as it was
        self.me = self.c.get("/ui/api/session").json()["user"]["id"]

    def acct(self, key, name, kind, **kw):
        a = made(make(self.c, "Acct", name=name, type=kind, **kw))
        self.accounts[key] = a
        return a["id"]

    def txn(self, account, day, amount, **kw):
        return made(make(self.c, "Txn", accountId=account, date=day, amount=amount, **kw))

    def trade(self, account, day, kind, symbol, qty, price):
        cents = int(Decimal(price) * 100 * Decimal(qty))
        amount = f"{'-' if kind == 'buy' else ''}{cents // 100}.{cents % 100:02d}"
        return self.txn(account, day, amount, kind=kind, symbol=symbol, quantity=str(qty),
                        price=price)  # fmt: skip

    def panels(self, year):
        return self.c.get(f"/ui/api/tax-books/{self.books[year]['id']}/panels").json()

    def book(self, year):
        return self.c.get(f"/ui/api/tax-books/{self.books[year]['id']}").json()


def build(h) -> World:
    """YEAR with something on every panel; EMPTY with nothing, its federal return carrying
    last year's figures into YEAR."""
    w = World(h)
    c, y = w.c, YEAR

    def upload(name):
        return made(
            c.post(
                "/ui/api/receipts",
                files={"file": (name, b"%PDF-1.4 " + name.encode(), "application/pdf")},
            )
        )["id"]

    for x in c.get("/ui/api/categories").json()["items"]:
        if x.get("taxTag"):
            w.cats.setdefault(x["taxTag"], x["id"])
    # Sales: a short gain, a long loss washed by a buy ten days later, a fund bought before
    # 2012, shares moved in without their day bought, and a sale with nothing to sell.
    brk = w.acct("broker", "TP broker", "brokerage", institution="TP Schwab")
    w.trade(brk, f"{y}-02-03", "buy", "IBM", 10, "100")
    w.trade(brk, f"{y}-06-02", "sell", "IBM", 10, "130")
    w.trade(brk, "2019-03-04", "buy", "KO", 10, "60")
    w.trade(brk, f"{y}-09-01", "sell", "KO", 10, "50")
    w.trade(brk, f"{y}-09-11", "buy", "KO", 4, "51")
    w.trade(brk, "2011-05-02", "buy", "FSKAX", 5, "20")
    w.trade(brk, f"{y}-11-02", "sell", "FSKAX", 5, "90")
    w.txn(brk, f"{y}-01-12", "0.00", kind="transfer-in", symbol="VTI", quantity="5",
          costBasis="400")  # fmt: skip
    w.trade(brk, f"{y}-03-02", "sell", "VTI", 2, "120")
    w.trade(brk, f"{y}-05-03", "sell", "MSFT", 3, "100")
    w.txn(brk, f"{y}-01-20", "0.00", kind="transfer-in", symbol="T", quantity="9",
          transferLots=[{"acquiredOn": "2018-01-02", "quantity": "9"}])  # fmt: skip
    # Income at the broker: dividends of both kinds, a capital-gain distribution, a return
    # of capital under the basis, foreign tax.
    w.trade(brk, f"{y}-01-05", "buy", "VXUS", 10, "50")
    w.txn(brk, f"{y}-03-15", "300.00", kind="dividend", dividendType="qualified", symbol="VXUS")
    w.txn(brk, f"{y}-03-15", "50.00", kind="dividend", dividendType="ordinary", symbol="VXUS")
    w.txn(brk, f"{y}-06-01", "25.00", kind="capital-gain", symbol="VXUS")
    w.txn(brk, f"{y}-07-01", "100.00", kind="return-of-capital", symbol="VXUS")
    w.txn(brk, f"{y}-06-30", "-12.34", kind="foreign-tax", symbol="VXUS")
    # A return of capital past its basis: a row of its own kind, never a physical item sold
    # (CR3-414).
    w.trade(brk, f"{y}-01-06", "buy", "SCHD", 1, "10")
    w.txn(brk, f"{y}-07-01", "30.00", kind="return-of-capital", symbol="SCHD")
    sav = w.acct("savings", "TP savings", "savings", institution="TP Ally")
    w.txn(sav, f"{y}-06-30", "120.50", kind="interest")
    # Coins: some bought and half sold, a reward received as income.
    ex = w.acct("exchange", "TP exchange", "crypto-exchange", institution="TP Coinbase")
    w.trade(ex, f"{y}-01-05", "buy", "ETH", 1, "2000")
    w.trade(ex, f"{y}-07-01", "sell", "ETH", "0.5", "3000")
    w.txn(ex, f"{y}-04-01", "0.00", kind="reward", symbol="ETH", quantity="0.01", price="2000")
    # A coin and a car sold, a cottage lived in and sold.
    coll = w.acct("collectables", "TP collectables", "collectables")
    coin = made(make(c, "Item", accountId=coll, name="TP coin", acquiredOn="2015-01-01",
                     costBasis="1000"))  # fmt: skip
    saved(sell(c, coin["id"], f"{y}-05-01", "3000"))
    cars = w.acct("cars", "TP cars", "vehicle")
    car = made(make(c, "Item", accountId=cars, name="TP car", acquiredOn="2018-01-01",
                    costBasis="30000", personalUse=True))  # fmt: skip
    saved(sell(c, car["id"], f"{y}-05-01", "18000"))
    homes = w.acct("homes", "TP homes", "real-estate")
    cottage = made(make(c, "Item", accountId=homes, name="TP cottage", acquiredOn="2015-06-01",
                        costBasis="200000", primaryResidence=True))  # fmt: skip
    saved(sell(c, cottage["id"], f"{y}-07-01", "300000"))
    # Loans: a mortgage secured by the cottage with PMI and tax through escrow; a student loan.
    mort = w.acct("mortgage", "TP mortgage", "mortgage")
    saved(terms(c, mort, principal="160000", startDate=f"{y}-01-01", termMonths=360, rate="3",
                escrowTax="200", pmi="50", securedById=cottage["id"]))  # fmt: skip
    saved(loan_payment(c, mort, f"{y}-02-01", "1000"))
    stu = w.acct("student", "TP student loan", "student-loan")
    saved(terms(c, stu, principal="20000", startDate=f"{y}-01-01", termMonths=120, rate="5"))
    saved(loan_payment(c, stu, f"{y}-02-01", "212.13"))
    # Deductions: two doctor's bills, one with its receipt; childcare with its receipt.
    card = w.acct("card", "TP card", "credit-card")
    bill = w.txn(card, f"{y}-04-02", "-240.00", payee="TP clinic", categoryId=w.cats["medical"])
    w.txn(card, f"{y}-05-02", "-60.00", payee="TP clinic", categoryId=w.cats["medical"])
    care = w.txn(card, f"{y}-06-02", "-500.00", payee="TP daycare", categoryId=w.cats["childcare"])
    for t in (bill, care):
        rid = upload(f"tp-bill-{t['id']}.pdf")
        saved(create(c, "RcLnk", receiptId=rid, kind="transaction", itemId=t["id"]))
    # Retirement: contributions over the IRAs' limit together, a distribution, a conversion,
    # a rollover, an HSA with its employer's money.
    ira = w.acct("ira", "TP IRA", "ira")
    roth = w.acct("roth", "TP Roth", "roth-ira")
    plan = w.acct("401k", "TP 401(k)", "401k")
    hsa = w.acct("hsa", "TP HSA", "hsa")
    w.txn(ira, f"{EMPTY}-06-01", "100000.00", kind="deposit", contributionYear=EMPTY - 1)
    w.txn(plan, f"{EMPTY}-06-01", "30000.00", kind="deposit", contributionYear=EMPTY - 1)
    w.txn(ira, f"{y}-02-01", "7000.00", kind="deposit")
    w.txn(roth, f"{y}-02-02", "1000.00", kind="deposit")
    w.txn(ira, f"{y}-03-02", "-10000.00", kind="transfer", payee="Conversion")
    w.txn(roth, f"{y}-03-02", "10000.00", kind="transfer", payee="Conversion")
    w.txn(plan, f"{y}-05-04", "-20000.00", kind="transfer", payee="Rollover")
    w.txn(ira, f"{y}-05-04", "20000.00", kind="transfer", payee="Rollover")
    w.txn(ira, f"{y}-12-01", "-4000.00", kind="withdrawal")
    w.txn(hsa, f"{y}-02-01", "1000.00", kind="deposit", contributionSource="employer")
    w.txn(hsa, f"{y}-03-01", "2000.00", kind="deposit")
    # A custodial account in Emma's name, earning past the Form 8615 threshold.
    kid = w.acct("custodial", "TP custodial", "savings", institution="TP Credit Union")
    w.txn(kid, f"{y}-12-31", "3000.00", kind="interest")
    # Giving: acknowledged, one missing, one too small to need it; goods past $5,000; a QCD.
    church = h.extra["church"]["id"]
    for kind, amount, extra in (
        ("cash", "300", {"acknowledged": True}),
        ("cash", "400", {}),
        ("cash", "100", {}),
        ("goods", "6000", {"description": "TP painting"}),
        ("qcd", "1000", {}),
    ):
        w.donations.append(made(make(c, "Dnatn", date=f"{y}-10-02", kind=kind,
                                     organisationId=church, amount=amount, **extra)))  # fmt: skip
    # Emma's 529: the owner's gift past the exclusion, a five-year election, a grandmother's
    # gift; a withdrawal past the qualified expenses.
    emma = h.extra["emma"]["personId"]
    gran = made(make(c, "Persn", name="TP Margaret", sex="female"))["id"]
    w.persons.append(gran)
    plan529_id = w.acct("529", "TP 529", "529", institution="TP my529")
    saved(plan529(c, plan529_id, planState="Utah", planName="my529", beneficiaryId=emma,
                  openedOn="2019-05-02", stateDeduction="2410"))  # fmt: skip
    made(make(c, "Cntrb", accountId=plan529_id, date=f"{y}-02-01", amount="20000"))
    made(make(c, "Cntrb", accountId=plan529_id, date=f"{y}-03-01", amount="5000",
              contributor=f"person:{gran}"))  # fmt: skip
    made(make(c, "Cntrb", accountId=plan529_id, date=f"{y}-04-01", amount="50000",
              fiveYear=True))  # fmt: skip
    w.txn(plan529_id, f"{y}-08-20", "-6000.00")
    made(make(c, "QExpn", accountId=plan529_id, date=f"{y}-08-15", kind="tuition",
              description="Fall tuition", amount="4500"))  # fmt: skip
    # The owner's age, for the catch-ups and the required distributions.
    profile = c.get("/ui/api/profile").json()
    w.person = c.get(f"/ui/api/persons/{profile['personId']}").json()
    # A son turning 13 in the year.
    leo = made(make(c, "Persn", name="TP Leo", sex="male", birthYear=y - 13))["id"]
    w.persons.append(leo)
    made(make(c, "Rltn", person1Id=w.person["id"], person2Id=leo, relation="child"))
    saved(change(c, "Persn", w.person, birthYear=1947))
    # Last year's book: everything that would show in it left out; its federal return
    # carries the figures this year's starts from.
    w.books[EMPTY] = made(make(c, "TaxBk", year=EMPTY, filers=[w.me]))
    for key in ("ira", "roth", "401k", "hsa", "529", "mortgage", "student"):
        saved(create(c, "TxBkA", bookId=w.books[EMPTY]["id"], accountId=w.accounts[key]["id"],
                     counted=False))  # fmt: skip
    saved(create(c, "TxBkA", bookId=w.books[EMPTY]["id"], accountId=h.extra["mortgage"]["id"],
                 counted=False))  # fmt: skip
    made(make(c, "Filng", bookId=w.books[EMPTY]["id"], jurisdiction="federal", form="Form 1040",
              progress="accepted", filedOn=f"{y}-04-01", sentBy="e-file",
              carried={"agi": "90000", "totalTax": "8400", "capitalLossShort": "500",
                       "capitalLossLong": "1200", "basis8606": "2000"}))  # fmt: skip
    # This year's book: Emma a dependent student with her custodial account, a relative of
    # unknown age, a son; three filings, with estimated payments; documents received and filed.
    b = w.books[y] = made(make(c, "TaxBk", year=y, filers=[w.me], fromLastYear=False))
    made(make(c, "TxDep", bookId=b["id"], personId=emma, claimedAs="qualifying child",
              months=12, student=True, accountIds=[kid]))  # fmt: skip
    made(make(c, "TxDep", bookId=b["id"], personId=gran, claimedAs="qualifying relative",
              months=7))  # fmt: skip
    made(make(c, "TxDep", bookId=b["id"], personId=leo, claimedAs="qualifying child",
              months=12))  # fmt: skip
    fed = made(make(c, "Filng", bookId=b["id"], jurisdiction="federal", form="Form 1040",
                    progress="in progress", sentBy="e-file", extensionFiledOn=f"{y + 1}-04-15",
                    extendedDue=f"{y + 1}-10-17", resultKind="owed", resultAmount="640",
                    payments=[{"quarter": q, "dueDate": due, "amount": "1000"}
                              for q, due in ((1, f"{y}-04-15"), (2, f"{y}-06-15"))]))  # fmt: skip
    made(make(c, "Filng", bookId=b["id"], jurisdiction="state", place="Utah", form="TC-40",
              progress="accepted", filedOn=f"{y + 1}-04-10", sentBy="paper", resultKind="refund",
              resultAmount="120", payments=[{"quarter": 1, "amount": "300"}]))  # fmt: skip
    made(make(c, "Filng", bookId=b["id"], jurisdiction="local", place="TP City",
              form="City return", dueDate=f"{y + 1}-04-18", resultKind="none"))  # fmt: skip

    made(make(c, "TxDoc", bookId=b["id"], form="1099-INT", issuer="TP Ally", accountId=sav,
              receiptId=upload("tp-1099-int.pdf")))  # fmt: skip
    made(make(c, "TxDoc", bookId=b["id"], form="1098-T", issuer="TP University"))
    made(make(c, "TxDoc", bookId=b["id"], direction="filed", form="Return as filed",
              filingId=fed["id"], issuer="IRS", notes="as e-filed",
              receiptId=upload("tp-1040.pdf")))  # fmt: skip
    return w


@pytest.fixture(scope="module")
def world(household):
    w = build(household)
    try:
        yield w
    finally:
        if w.person:
            person = w.c.get(f"/ui/api/persons/{w.person['id']}").json()
            saved(change(w.c, "Persn", person, birthYear=w.person["birthYear"]))
        for b in w.books.values():
            have = w.c.get(f"/ui/api/tax-books/{b['id']}")
            if have.status_code == 200:
                made(remove(w.c, "TaxBk", have.json()))
        for a in w.accounts.values():
            made(remove(w.c, "Acct", w.c.get(f"/ui/api/accounts/{a['id']}").json(), confirm=True))
        for p in w.persons:
            made(remove(w.c, "Persn", w.c.get(f"/ui/api/persons/{p}").json(), confirm=True))
        for d in w.donations:
            made(remove(w.c, "Dnatn", d))


def _text(page, selector: str) -> str:
    """What a part of the page reads, its spacing made single."""
    return " ".join(page.locator(selector).inner_text().split())


def _card(h3: str) -> str:
    return f'.card:has(h3:text-is("{h3}"))'


def opened(browser, w: World, year: int, tab: str, ready: str):
    """The Taxes screen at `tab`, the year's book chosen, once `ready` shows: something only
    that book shows, since the screen first shows the book it picks itself."""
    page, problems = signed_in(browser, w.h, f"/ui/taxes/{tab}", "#f-tax-book")
    page.select_option("#f-tax-book", w.books[year]["id"])
    wait(page, ready, problems)
    return page, problems


ROWS = 'table:has(caption:text("Form 8949 rows")) tbody tr'


def _rows(page) -> dict[str, list[str]]:
    shown = page.locator(ROWS)
    out = {}
    for i in range(shown.count()):
        cells = [" ".join(x.split()) for x in shown.nth(i).locator("td").all_inner_texts()]
        out[shown.nth(i).locator("td").nth(1).inner_text().split("\n")[0]] = cells
    return out


def test_form_8949_shows_each_sale_by_box_with_its_code(browser, world):
    """S8.1, S8.3, S2.2: a short gain in A, a washed long loss in D with its W, a fund bought
    before 2012 in E, coins in C before 2025, a coin in F as a collectable, a car's loss as
    personal use; shares moved in without their day bought dated Various; a sale with nothing
    to sell, its basis missing; Schedule D's totals with last year's carryover."""
    page, problems = opened(browser, world, YEAR, "gains", f'{ROWS}:has-text("10 KO")')
    rows = _rows(page)
    assert len(rows) == len(world.panels(YEAR)["rows"]) == 10
    ibm, ko = rows["10 IBM"], rows["10 KO"]
    assert (ibm[0], ibm[1], ibm[2], ibm[3]) == (
        "A",
        "10 IBM TP broker",
        "Feb 3, 2021",
        "Jun 2, 2021",
    )
    assert [_money(x) for x in ibm[4:6]] == [Decimal(1300), Decimal(1000)]
    assert ibm[6] == "" and ibm[7] == "—" and ibm[8] == "+$300.00"
    assert (ko[0], ko[6], ko[7], ko[8]) == ("D", "W", "$40.00", "−$60.00")
    assert rows["5 FSKAX"][0] == "E" and rows["0.5 ETH"][0] == "C"
    assert rows["2 VTI"][2] == "Various" and rows["2 VTI"][5] == "$160.00"
    msft = rows["3 MSFT"]
    assert (msft[2], msft[5], msft[8]) == ("missing", "missing", "—")  # CR3-415
    coin, car = rows["TP coin"], rows["TP car"]
    assert (coin[0], coin[1], coin[6], coin[8]) == ("F", "TP coin TP collectables · collectable",
                                                    "C", "+$2,000.00")  # fmt: skip
    assert (car[6], car[7], car[8]) == ("L", "$12,000.00", "$0.00")
    facts = _text(page, ".card.facts")
    for box, gain in (("A", "+$400.00"), ("C", "+$500.00"), ("D", "−$60.00"), ("E", "+$350.00"),
                      ("F", "+$102,000.00")):  # fmt: skip
        assert f"Box {box} {gain}" in facts, facts
    assert "Short term +$900.00 Long term +$102,290.00" in facts
    assert "Of it, collectables +$2,000.00" in facts
    assert "Loss carried from last year $1,700.00" in facts
    washes = _text(page, _card("Wash sales"))
    assert (
        "KO sold Sep 1, 2021 TP broker · replaced Sep 11, 2021 in TP broker (4 shares), basis "
        "now $244.00 W $40.00 of $100.00"
    ) in washes
    assert problems == []
    page.close()


def test_form_8949_shows_one_term_at_a_time(browser, world):
    """S8.1: the Term chips keep the short-term rows, or the long-term ones."""
    page, problems = opened(browser, world, YEAR, "gains", f'{ROWS}:has-text("10 KO")')
    api = world.panels(YEAR)["rows"]
    short = sorted(r["description"] for r in api if not r["longTerm"])
    long_ = sorted(r["description"] for r in api if r["longTerm"])
    page.click('.chips button:text-is("Short term")')
    wait(page, '.chips button.on:text-is("Short term")', problems)
    assert (
        sorted(_rows(page))
        == short
        == ["0.5 ETH", "10 IBM", "2 VTI", "3 MSFT", "SCHD return of capital over basis"]
    )
    page.click('.chips button:text-is("Long term")')
    wait(page, f'{ROWS}:has-text("TP cottage")', problems)
    assert sorted(_rows(page)) == long_ and "10 IBM" not in long_
    page.click('.chips button:text-is("All")')
    wait(page, f'{ROWS}:has-text("10 IBM")', problems)
    assert len(_rows(page)) == len(api)
    assert problems == []
    page.close()


def test_the_income_panel_shows_each_line(browser, world):
    """S8.5: interest by payer, dividends ordinary and qualified, a capital-gain distribution,
    a return of capital, dividends by payer, foreign tax and crypto income."""
    page, problems = opened(browser, world, YEAR, "income", 'text="TP Credit Union"')
    interest = _text(page, _card("Interest (1099-INT)"))
    assert "TP Credit Union $3,000.00" in interest and "TP Ally $120.50" in interest
    div = _text(page, _card("Dividends (1099-DIV)"))
    assert (
        "Ordinary (1a) $350.00 Qualified (1b) $300.00 Capital-gain distributions (2a) $25.00 "
        "Return of capital $130.00 TP Schwab $375.00"
    ) in div
    assert _text(page, _card("Foreign tax paid (7)")).endswith("TP Schwab $12.34")
    assert _text(page, _card("Crypto income")).endswith("TP exchange $20.00")
    assert problems == []
    page.close()


def test_the_retirement_panel_shows_limits_distributions_and_moves(browser, world):
    """S8.6: each account against its limit, the IRAs' together over it with the catch-up at
    74; a distribution, last year's 8606 basis, the RMDs; a conversion taxed by Form 8606's
    pro rata share, and a rollover."""
    page, problems = opened(
        browser, world, YEAR, "retirement", f"{_card('Roth conversions')} .list-item"
    )
    table = page.locator('table:has(caption:text("Contributions")) tbody tr')
    rows = {r.split("\n")[0]: " ".join(r.split()) for r in table.all_inner_texts()}
    ira = rows["TP IRA"]
    assert ira.startswith("TP IRA Traditional IRA Admin $7,000.00 $8,000.00")
    assert ira.endswith("across their IRAs $7,000 with the catch-up at 50 and over over the limit")
    assert "Roth eligibility depends on MAGI" in rows["TP Roth"]
    assert "over the limit" in rows["TP Roth"]
    assert rows["TP 401(k)"].startswith("TP 401(k) 401(k) Admin $0.00 $26,000")
    assert "over the limit" not in rows["TP 401(k)"]
    assert (
        "set the coverage; with the catch-up at 55 and over; 1,000.00 of it from the employer"
        in (rows["TP HSA"])
    )
    dist = _text(page, _card("Distributions"))
    assert dist.startswith("Distributions TP IRA $4,000.00")
    assert "Form 8606 basis carried from last year: $2,000.00, for a backdoor Roth's" in dist
    rmds = _text(page, _card("Required minimum distributions"))
    for line in (
        "TP IRA Admin, 74: $100,000 at the end of last year ÷",
        "25.5 $3,921.57",
        "TP 401(k) Admin, 74: $30,000 at the end of last year ÷",
        "25.5 $1,176.47",
    ):
        assert line in rmds, (line, rmds)
    conv = _text(page, _card("Roth conversions"))
    assert "TP IRA → TP Roth Mar 2, 2021" in conv
    assert "· taxed $9,842.52 by Form 8606 $10,000.00" in conv
    roll = _text(page, _card("Rollovers"))
    assert "TP 401(k) → TP IRA May 4, 2021 $20,000.00" in roll
    assert problems == []
    page.close()


def test_the_deductions_panel_shows_tags_payments_and_dependents(browser, world):
    """S8.7, S8.17, S8.14.5.3: tax-tagged categories with their receipts, the loans' interest
    and escrowed tax among them; the estimated payments beside last year's tax; dependents'
    ages, one unknown."""
    page, problems = opened(browser, world, YEAR, "deductions", 'td:text-is("Childcare")')
    table = page.locator('table:has(caption:text("Deductions")) tbody tr')
    rows = [" ".join(r.split()) for r in table.all_inner_texts()]
    assert rows == [
        "Childcare $500.00 1 1 of 1",
        "Loan interest $483.33 2 0 of 2",
        "Medical and dental $300.00 2 1 of 2",
        "Property tax $200.00 1 0 of 1",
    ]
    pills = table.locator(".pill")
    assert pills.nth(0).get_attribute("class") == "pill ok"
    assert pills.nth(2).get_attribute("class") == "pill warn"
    paid = _text(page, _card("Estimated payments"))
    assert "Federal · Q1 $1,000.00 Federal · Q2 $1,000.00 Utah · Q1 $300.00" in paid
    assert "Last year's total tax: $8,400; paid in 2021 so far: $2,300." in paid
    deps = _text(page, _card("Dependents' ages on Dec 31"))
    assert "Emma Griffin 3 · under 13 · under 17" in deps
    assert "TP Margaret age unknown" in deps
    assert (
        "TP Leo · son turns 13: no longer under 13 for the childcare credit 13 · under 17" in deps
    )
    assert problems == []
    page.close()


def test_the_giving_panel_shows_acknowledgements_and_what_is_apart(browser, world):
    """S8.9: goods past $500 and an item past $5,000 noted; each gift's acknowledgement
    received, missing or not needed; a QCD apart, not deducted."""
    page, problems = opened(browser, world, YEAR, "giving", 'h3:text("Not deducted")')
    notes = page.locator(".notice").all_inner_texts()
    assert notes == [
        "Goods given this year come to over $500: Form 8283 goes with the return.",
        "TP painting to St. Mark's Parish is over $5,000: it needs a qualified appraisal.",
    ]
    deductible = page.locator('.card:has(h3:has-text("Deductible"))')
    assert " ".join(deductible.locator("h3").inner_text().split()) == "Deductible $6,800.00"
    rows = [" ".join(r.split()) for r in deductible.locator("tbody tr").all_inner_texts()]
    assert sorted(rows) == [
        "Oct 2, 2021 St. Mark's Parish Cash $100.00 —",
        "Oct 2, 2021 St. Mark's Parish Cash $300.00 received",
        "Oct 2, 2021 St. Mark's Parish Cash $400.00 missing",
        "Oct 2, 2021 St. Mark's Parish Goods $6,000.00 missing",
    ]
    apart = _text(page, '.card:has(h3:text("Not deducted"))')
    assert "Oct 2, 2021 St. Mark's Parish QCD from an IRA $1,000.00 —" in apart
    assert "QCDs (excluded from income instead)" in apart
    assert problems == []
    page.close()


def test_the_education_panel_shows_the_529_students_and_gifts(browser, world):
    """S8.10, S8.11, S8.14.5.3: a 529's contributions by contributor, its state deduction,
    its withdrawal past the expenses; a dependent student's 1098-T and withdrawals; a gift
    past the exclusion and a five-year election running."""
    page, problems = opened(browser, world, YEAR, "education", ':text("year 1 of 5")')
    plans = _text(page, _card("529 plans"))
    assert (
        "TP 529 · Emma Griffin From Admin $70,000.00 From TP Margaret $5,000.00 State deduction "
        "expected $2,410 Distributions (1099-Q) $6,000.00 Qualified expenses $4,500.00 Not "
        "covered $1,500.00"
    ) in plans
    assert (
        "Dependent students Emma Griffin 529 withdrawals for them: $6,000.00 1098-T received"
    ) in plans
    gifts = _text(page, _card("Gifts (Form 709)"))
    assert "Admin to Emma Griffin above the $15,000 exclusion $30,000.00" in gifts
    assert "Admin's 2021 five-year election to TP 529: year 1 of 5, 10,000 a year" in gifts
    assert problems == []
    page.close()


def test_the_loans_and_property_panel_shows_interest_and_sales(browser, world):
    """S8.12, S8.13: a mortgage's interest, PMI and escrowed tax under the home it's secured
    by, a student loan's 1098-E; a collectable and a personal-use loss sold, and a primary
    residence's gain and years owned."""
    page, problems = opened(browser, world, YEAR, "property", ':text("your primary residence")')
    loans = _text(page, _card("Loans (1098, 1098-E)"))
    assert (
        "TP mortgage · 1098 · TP cottage Interest $400.00 PMI $50.00 Property tax through "
        "escrow $200.00"
    ) in loans
    assert "TP student loan · 1098-E Interest $83.33" in loans
    sold = _text(page, _card("Physical assets sold"))
    assert "TP coin May 1, 2021 · collectable +$2,000.00" in sold
    assert "TP car May 1, 2021 · a loss on personal-use property, not deductible $0.00" in sold
    assert "TP cottage Jul 1, 2021 +$100,000.00" in sold
    assert (
        "TP cottage, your primary residence, sold Jul 1, 2021 after 6.1 years: a gain of "
        "$100,000.00. The exclusion is the preparer's to apply."
    ) in sold
    assert "10 IBM" not in sold and "SCHD" not in sold
    assert problems == []
    page.close()


def test_the_issues_panel_lists_what_to_look_at(browser, world):
    """S8.4: lots moved in without their day bought or their basis, a sale of them, a sale
    with nothing to sell, its basis missing, and Form 8615; each with a way to it where
    there is one."""
    page, problems = opened(
        browser,
        world,
        YEAR,
        "issues",
        'text="TP broker: the sale of 3 MSFT on May 3 has no basis or day bought"',
    )
    issues = world.panels(YEAR)["issues"]
    items = page.locator("main .card .list-item")
    shown = [" ".join(x.split()) for x in items.all_inner_texts()]
    assert len(shown) == len(issues)
    for i, x in zip(issues, shown, strict=True):
        assert x == i["text"] + (" Look" if i["link"] else "")
    kinds = {i["kind"] for i in issues}
    assert {"acquired-missing", "sale-acquired-missing", "sale-basis", "sale-without-lot",
            "basis-missing", "form-8615"} <= kinds  # fmt: skip
    assert (
        "TP broker: the sale of 2 VTI on Mar 2 is of shares moved in: when they were bought, "
        "for its term Look"
    ) in shown
    assert "TP broker: the sale of 3 MSFT on May 3 has no basis or day bought" in shown
    links = [a.get_attribute("href") for a in items.locator("a").all()]
    assert links == [i["link"] for i in issues if i["link"]]
    assert problems == []
    page.close()


def test_the_summary_shows_the_years_figures_and_exports(browser, world):
    """S8.1–S8.2, S8.5, S8.9, S12.2.10: the gains, dividends, interest and charitable gifts;
    the exports, with the sales TXF leaves out counted by why; the book's filers, filings,
    documents, last year's figures, dependents and Form 8615."""
    page, problems = opened(browser, world, YEAR, "summary", 'text="2 acknowledgements missing"')
    kpis = [" ".join(x.split()) for x in page.locator(".card.kpi").all_inner_texts()]
    assert kpis[:4] == [
        "Net capital gain or loss +$103,190 short +$900 · long +$102,290",
        "Dividends $350 qualified $300",
        "Interest $3,121 2 payers",
        "Charitable gifts $6,800 2 acknowledgements missing",
    ]
    book = world.book(YEAR)
    have = sum(1 for e in book["expected"] if e["document"])
    assert kpis[4:] == [
        "Filers Admin one filer",
        f"Accounts counted {len(book['accounts'])} all the filers’ own",
        "Filings 3 past due",
        f"Documents {have} of {len(book['expected'])} {len(book['expected']) - have} still to come",
    ]
    exports = page.locator(_card("Exports"))
    base = f"/ui/api/tax-books/{world.books[YEAR]['id']}/exports"
    hrefs = [a.get_attribute("href") for a in exports.locator("a.btn").all()]
    assert hrefs == [f"{base}/8949.csv", f"{base}/moolakata.txf", f"{base}/summary.pdf"]
    assert " ".join(exports.locator(".notice").inner_text().split()) == (
        "TXF leaves out 3 sales (1 collectable, 1 personal-use loss, 1 sale without a lot): "
        "enter them from the CSV."
    )
    status, kind, csv = page.evaluate(
        "async (u) => { const r = await fetch(u);"
        " return [r.status, r.headers.get('content-type'), await r.text()]; }",
        hrefs[0],
    )
    assert status == 200 and kind.startswith("text/csv")
    assert "TP coin" in csv and "10 KO" in csv
    last = _text(page, _card("From last year"))
    assert (
        "Federal · Form 1040 · Admin Adjusted gross income $90,000.00 Total tax $8,400.00 "
        "Capital-loss carryover, short term $500.00 Capital-loss carryover, long term "
        "$1,200.00 Form 8606 basis $2,000.00"
    ) in last
    deps = _text(page, '.card:has(h3:has-text("Dependents"))')
    assert (
        "Emma Griffin qualifying child · 12 months · student Age 3 on Dec 31, 2021: under 13 "
        "and under 17"
    ) in deps
    assert "TP Margaret qualifying relative · 7 months Age unknown: no birth year" in deps
    assert (
        "TP Leo Son · qualifying child · 12 months turns 13: no longer under 13 for the childcare "
        "credit Age 13 on Dec 31, 2021: under 17"
    ) in deps
    assert (
        "Emma Griffin's TP custodial earned $3,000.00 of unearned income this year, above the "
        "$2,200.00 threshold: Form 8615 (the kiddie tax) may apply."
    ) in deps
    assert problems == []
    page.close()


def test_the_filings_tab_shows_each_returns_progress_and_result(browser, world):
    """S8.15: an extended federal return past its due date, owed, with its estimated
    payments; a state return filed on paper and refunded; a local one not started and late,
    nothing due."""
    page, problems = opened(browser, world, YEAR, "filings", 'h3:has-text("TP City")')
    cards = {
        x.split("\n")[0]: " ".join(x.split())
        for x in page.locator("main .card.mt").all_inner_texts()
    }
    fed = next(v for k, v in cards.items() if k.startswith("Federal"))
    assert "In progress" in fed and "past its due date" in fed
    assert "Due Oct 17, 2022 extended Filed —" in fed and "· e-file Result" in fed
    assert "Result Owed $640.00 Documents 1" in fed
    assert fed.endswith("Estimated payments: Q1 $1,000 · Q2 $1,000")
    utah = next(v for k, v in cards.items() if k.startswith("Utah"))
    assert "Accepted" in utah and "past its due date" not in utah
    assert (
        "Due — Filed Apr 10, 2022" in utah and "· paper Result Refund $120.00 Documents —" in utah
    )
    assert utah.endswith("Estimated payments: Q1 $300")
    city = next(v for k, v in cards.items() if k.startswith("TP City"))
    assert "Not started" in city and "past its due date" in city
    assert "Due Apr 18, 2022 Filed — Result Nothing due Documents —" in city
    assert problems == []
    page.close()


def test_the_documents_tab_shows_what_came_and_what_was_filed(browser, world):
    """S8.16: an expected 1099-INT received with its file, a student's 1098-T received, the
    rest to attach; the return as filed, under its filing, with its file and notes."""
    page, problems = opened(browser, world, YEAR, "documents", 'text="tp-1040.pdf"')
    table = page.locator('table:has(caption:text("Documents received and expected")) tbody tr')
    rows = {" ".join(r.split()) for r in table.all_inner_texts()}
    assert (
        "1099-INT TP Ally From TP savings: $10 or more of interest received tp-1099-int.pdf"
    ) in rows
    assert "1098-T — For Emma Griffin: a student received" in rows
    assert "1099-DA TP Coinbase From TP exchange: a crypto exchange Attach" in rows
    expected = world.book(YEAR)["expected"]
    assert len(rows) == len(expected)
    assert table.locator('button:has-text("Attach")').count() == sum(
        1 for e in expected if not e["document"]
    )
    filed = _text(page, 'main .card:has-text("Return as filed")')
    assert filed == "Return as filed Federal · Form 1040 · IRS · as e-filed tp-1040.pdf"
    assert problems == []
    page.close()


def _close_dialog(page, problems):
    page.click(".dialog-x")
    if page.locator(".dialog-ask").count():
        page.click('button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")


def test_attach_opens_an_expected_document_filled_in(browser, world):
    """S8.16: Attach on an expected document starts it as that form, from its issuer, for
    its account."""
    page, problems = opened(browser, world, YEAR, "documents", 'text="tp-1040.pdf"')
    page.click('tr:has(td:text-is("1099-DA")) button:has-text("Attach")')
    wait(page, ".dialog #f-issuer", problems)
    assert page.locator("#dialog-title").inner_text() == "Add a tax document"
    assert page.locator('.dialog [role="radio"][aria-checked="true"]').inner_text() == "Received"
    assert page.input_value("#f-form") == "1099-DA"
    assert page.input_value("#f-issuer") == "TP Coinbase"
    assert page.input_value("#f-account") == world.accounts["exchange"]["id"]
    assert page.locator("#f-filing").count() == 0, "a received document has no filing"
    _close_dialog(page, problems)
    assert problems == []
    page.close()


def test_add_a_filed_document_starts_on_the_first_filing(browser, world):
    """S8.16: a filed document is the return as filed, for one of the book's filings."""
    page, problems = opened(browser, world, YEAR, "documents", 'text="tp-1040.pdf"')
    page.click('button:has-text("Add a filed document")')
    wait(page, ".dialog #f-filing", problems)
    assert page.locator("#dialog-title").inner_text() == "Add a filed document"
    assert page.locator('.dialog [role="radio"][aria-checked="true"]').inner_text() == "Filed"
    assert page.input_value("#f-form") == "Return as filed"
    first = world.book(YEAR)["filings"][0]["id"]
    assert page.input_value("#f-filing") == first
    assert page.get_attribute("#f-issuer", "placeholder") == "IRS"
    assert page.locator("#f-account").count() == 0, "a filed document reports on no account"
    _close_dialog(page, problems)
    assert problems == []
    page.close()


EMPTY_STATES = {
    "gains": ["No sales in 2020.", "None found: no loss sale was replaced within 30 days."],
    "income": ["No interest in 2020.", "None in 2020.", "No staking or rewards in 2020."],
    "retirement": [
        "No retirement accounts in this book.",
        "None in 2020.",
        "None due: no owner has reached the RMD age.",
    ],
    "deductions": [
        "No transactions in tax-tagged categories.",
        "None recorded in the filings.",
        "No dependents in this book: add them on the Summary.",
    ],
    "giving": ["Deductible $0.00", "None."],
    "education": ["No 529 plans in this book.", "No one received more than the annual exclusion."],
    "property": ["No loans in this book.", "Nothing sold in 2020."],
    "summary": ["Net capital gain or loss $0", "0 payers", "deductible", "Nothing carried forward"],
}


@pytest.mark.parametrize("tab", list(EMPTY_STATES))
def test_a_year_with_nothing_in_it_says_so_on_each_panel(browser, world, tab):
    """S8: a year with no sales, income, retirement accounts, deductions, gifts, 529s or
    loans (those it would count left out, and said to be) shows each panel empty, in words."""
    left = ", ".join(world.panels(EMPTY)["leftOut"])
    words = EMPTY_STATES[tab]
    # Only this book leaves accounts out: the screen first shows another, with words alike.
    ready = (
        f'.card.kpi:has-text("{len(world.panels(EMPTY)["leftOut"])} left out")'
        if tab == "summary"
        else f'main:has(p:text("Left out of this book")) :text("{words[-1]}")'
    )
    page, problems = opened(browser, world, EMPTY, tab, ready)
    main = " ".join(page.locator("main").inner_text().split())
    for x in words:
        assert x in main, (x, main)
    if tab != "summary":
        assert f"Left out of this book: {left}." in main
    else:
        assert f"{len(world.panels(EMPTY)['leftOut'])} left out" in main
    # The summary lists the accounts counted and left out; the panels name none of them.
    absent = ["Not deducted", "Dependent students", "Loss carried", "TXF leaves out"]
    for x in absent + (["TP "] if tab != "summary" else []):
        assert x not in main.replace(left, ""), x
    assert problems == []
    page.close()


def test_no_amendment_needed_settles_an_edit_made_after_filing(browser, world):
    """S8.15, S2.8.3: a sale changed anyway after the federal return was filed is listed, with
    an amended return to add or No amendment needed, which settles it."""
    c, year = world.c, 2022
    a = made(make(c, "Acct", name="TP filed broker", type="brokerage"))
    book = None
    try:
        world.trade(a["id"], f"{year}-01-05", "buy", "IBM", 10, "100")
        sale = world.trade(a["id"], f"{year}-03-01", "sell", "IBM", 10, "120")
        book = made(make(c, "TaxBk", year=year, filers=[world.me], fromLastYear=False))
        made(make(c, "Filng", bookId=book["id"], jurisdiction="federal", form="Form 1040",
                  progress="filed", filedOn=f"{year + 1}-03-01"))  # fmt: skip
        saved(change(c, "Txn", c.get(f"/ui/api/transactions/{sale['id']}").json(),
                     confirm=True, price="125", amount="1250.00"))  # fmt: skip
        world.books[year] = book
        said = "Realized gains changed by +$50.00 after the federal return was filed: "
        page, problems = opened(browser, world, year, "issues", f"text={said}")
        item = page.locator(f'.list-item:has-text("{said}")')
        assert " ".join(item.inner_text().split()) == (
            said + "TP filed broker, 1 edit Add an amended return No amendment needed"
        )
        assert item.locator("a").get_attribute("href") == "/ui/taxes/filings"
        item.locator('button:has-text("No amendment needed")').click()
        wait(page, f'.list-item:has-text("{said}")', problems, state="detached")
        kinds = {i["kind"] for i in world.panels(year)["issues"]}
        assert "changed-after-filing" not in kinds
        assert problems == []
        page.close()
    finally:
        world.books.pop(year, None)
        if book:
            made(remove(c, "TaxBk", c.get(f"/ui/api/tax-books/{book['id']}").json()))
        made(remove(c, "Acct", c.get(f"/ui/api/accounts/{a['id']}").json(), confirm=True))


def test_new_tax_book_makes_this_years_book(browser, world):
    """S8.14.1: New tax book offers this year and the two before, last year's by default;
    with no spouse, filing jointly can't be chosen; this year has last year's book to start
    from; Create makes it and shows it."""
    c, year = world.c, int(months_back(0)[:4])
    page, problems = signed_in(browser, world.h, "/ui/taxes/summary", "#f-tax-book")
    made_id = None
    try:
        page.click('.toolbar button:has-text("New tax book")')
        wait(page, ".dialog #f-year", problems)
        assert page.locator("#dialog-title").inner_text() == "New tax book"
        options = page.locator("#f-year option").all_inner_texts()
        assert options == [str(year), str(year - 1), str(year - 2)]
        assert page.input_value("#f-year") == str(year - 1)
        dialog = _text(page, ".dialog")
        assert "Add your spouse among your relationships in Profile to file jointly." in dialog
        page.select_option("#f-year", str(year))
        wait(page, '.dialog :text("Copies last year\'s accounts left out or added")', problems)
        assert page.input_value("#f-bitcoin-fees") == "sale"
        page.click(".dialog footer button.primary")
        wait(page, ".dialog", problems, state="detached")
        books = c.get("/ui/api/tax-books").json()["books"]
        made_id = next(b["id"] for b in books if b["year"] == year)
        wait(page, f'#f-tax-book option[value="{made_id}"]', problems, state="attached")
        page.wait_for_function(
            "id => document.querySelector('#f-tax-book').value === id", arg=made_id
        )
        assert problems == []
        page.close()
    finally:
        if made_id:
            made(remove(c, "TaxBk", c.get(f"/ui/api/tax-books/{made_id}").json()))
