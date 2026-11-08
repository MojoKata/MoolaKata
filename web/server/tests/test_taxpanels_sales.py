"""The gains panels' rules, each on its own (requirements S8.1, S8.3, S8.4, S8.13, S8.15): a
sale's Form 8949 box, Schedule D's totals by box and term, physical items sold, a residence's
years owned, the wash sales a book lists and the option sales flagged beside them, and the
issues: what changed or differs since the federal return was filed."""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_user, sign_in
from edits import create, drop, make, option_trade, saved, sell
from test_accounts import add, new_account
from test_assets import item
from test_taxpanels import book, trade
from test_taxpanels import panels as read_panels

from moolakata import clock
from moolakata.taxes import panels

D = Decimal
# Into the next year, so the year's last day can be a sale's.
T0 = dt.datetime(2027, 1, 15, 12, tzinfo=dt.UTC)


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice", born=1951)
    yield sign_in(server, "alice")
    clock.fix(None)


# ---------- A sale's 8949 box (S8.1) ----------


@pytest.mark.parametrize(
    ("cls", "first"),
    [
        ("equity", dt.date(2011, 1, 1)),
        ("etf", dt.date(2012, 1, 1)),
        ("mutual-fund", dt.date(2012, 1, 1)),
        ("bond", dt.date(2014, 1, 1)),
        ("option", dt.date(2014, 1, 1)),
    ],
)
def test_the_broker_reports_the_basis_from_its_classs_first_day_on(cls, first):
    assert panels._covered(cls, first)
    assert not panels._covered(cls, first - dt.timedelta(days=1))


@pytest.mark.parametrize(
    ("reported", "covered", "short", "long"),
    [(True, True, "A", "D"), (True, False, "B", "E"), (False, True, "C", "F"),
     (False, False, "C", "F")],
)  # fmt: skip
def test_the_box_is_the_brokers_reporting_by_term(reported, covered, short, long):
    assert panels._box(False, reported, covered) == short
    assert panels._box(True, reported, covered) == long


def test_a_security_is_boxed_by_whether_its_basis_is_reported():
    on, before = dt.date(2011, 1, 1), dt.date(2010, 12, 31)
    for year in (2024, 2025, 2026):
        assert panels.box_of(False, "equity", "brokerage", on, year) == "A"
        assert panels.box_of(True, "equity", "brokerage", on, year) == "D"
        assert panels.box_of(False, "equity", "brokerage", before, year) == "B"
        assert panels.box_of(True, "equity", "brokerage", before, year) == "E"
        # Bought on a day not known: its basis is not taken as reported.
        assert panels.box_of(False, "equity", "brokerage", None, year) == "B"
        assert panels.box_of(True, "equity", "brokerage", None, year) == "E"


def test_a_digital_asset_before_2025_has_no_1099_b():
    on = dt.date(2026, 3, 1)
    assert panels.box_of(False, "crypto", "crypto-exchange", on, 2024) == "C"
    assert panels.box_of(True, "crypto", "crypto-exchange", on, 2024) == "F"
    assert panels.box_of(False, "crypto", "crypto-wallet", None, 2024) == "C"


def test_a_digital_asset_from_2025_has_boxes_of_its_own():
    basis_from, before = dt.date(2026, 1, 1), dt.date(2025, 12, 31)
    for year in (2025, 2026):
        # A self-custody wallet's has no 1099-DA, whenever bought.
        assert panels.box_of(False, "crypto", "crypto-wallet", basis_from, year) == "I"
        assert panels.box_of(True, "crypto", "crypto-wallet", basis_from, year) == "L"
        assert panels.box_of(False, "crypto", "crypto-wallet", None, year) == "I"
        # A broker's reports the basis of what was bought from 2026 on.
        assert panels.box_of(False, "crypto", "crypto-exchange", basis_from, year) == "G"
        assert panels.box_of(True, "crypto", "crypto-exchange", basis_from, year) == "J"
        assert panels.box_of(False, "crypto", "crypto-exchange", before, year) == "H"
        assert panels.box_of(True, "crypto", "crypto-exchange", before, year) == "K"
        assert panels.box_of(False, "crypto", "crypto-exchange", None, year) == "H"
        assert panels.box_of(True, "crypto", "crypto-exchange", None, year) == "K"


# ---------- Schedule D (S8.1, S8.17) ----------


def row(box, proceeds, basis, adjustment="0", long_term=False, collectable=False, account="a1"):
    return panels.Row(
        description="x",
        acquired=None,
        sold=dt.date(2026, 5, 1),
        proceeds=D(proceeds),
        basis=None if basis is None else D(basis),
        code="",
        adjustment=D(adjustment),
        longTerm=long_term,
        box=box,
        account="Brokerage",
        accountId=account,
        collectable=collectable,
    )


@pytest.fixture
def carryover(monkeypatch):
    def carried(s, book):
        assert (s, book) == (S, BOOK)
        return D("300"), D("70"), False

    monkeypatch.setattr(panels.books, "carryover", carried)


S, BOOK = object(), SimpleNamespace(year=2026)


def test_schedule_d_totals_each_box_and_term(carryover):
    rows = [
        row("D", "1000", "400", long_term=True),
        row("A", "100", "250", adjustment="50"),
        row("D", "500", "100", long_term=True, collectable=True),
        row("C", "80", None),  # no basis: its proceeds count, its gain is not known
        row("A", "10", "5"),
        row("C", "60", "90", collectable=True),  # a short-term collectable: not the 28% rate
        row("F", "20", "30", long_term=True),
    ]
    d = panels.schedule_d(S, BOOK, rows)
    assert list(d.byBox) == ["A", "C", "D", "F"], "in box order"
    assert d.byBox["A"] == (D("110"), D("255"), D("50"), D("-95.00"))
    assert d.byBox["C"] == (D("140"), D("90"), D("0"), D("-30.00"))
    assert d.byBox["D"] == (D("1500"), D("500"), D("0"), D("1000.00"))
    assert d.byBox["F"] == (D("20"), D("30"), D("0"), D("-10.00"))
    assert d.shortTerm == D("-125.00")
    assert d.longTerm == D("990.00")
    assert d.collectables == D("400.00"), "the long-term collectables' gain only"
    assert (d.carryoverShort, d.carryoverLong) == (D("300"), D("70"))
    assert d.net == D("-125") + D("990") - D("300") - D("70")


def test_schedule_d_of_no_sales_is_zero(carryover):
    d = panels.schedule_d(S, BOOK, [])
    assert d.byBox == {}
    assert (d.shortTerm, d.longTerm, d.collectables) == (0, 0, 0)
    for total in (d.shortTerm, d.longTerm, d.collectables):
        assert isinstance(total, Decimal)


def test_schedule_d_of_sales_with_no_basis_is_zero_gain(carryover):
    d = panels.schedule_d(S, BOOK, [row("A", "50", None), row("D", "20", None, long_term=True)])
    assert d.byBox == {
        "A": (D("50"), D("0"), D("0"), D("0")),
        "D": (D("20"), D("0"), D("0"), D("0")),
    }
    assert (d.shortTerm, d.longTerm) == (0, 0)
    for v in d.byBox.values():
        assert all(isinstance(x, Decimal) for x in v)


# ---------- Changed or different since filing (S8.15) ----------


class Names:
    """A session that knows only the accounts' names."""

    def __init__(self, **names):
        self.names = names

    def get(self, cls, id_):
        assert cls is panels.Account
        return SimpleNamespace(name=self.names[id_])


def change(account, gains):
    return SimpleNamespace(accountId=account, gains=D(gains))


def test_no_edit_since_filing_is_no_issue(monkeypatch):
    monkeypatch.setattr(panels.closed, "unsettled", lambda s, book: [])
    assert panels.changed_after_filing(Names(), None) is None


def test_edits_since_filing_say_how_far_and_where_in_the_order_made(monkeypatch):
    changes = [change("b", "1200.50"), change("a", "-100"), change("b", "200"), change("b", "1")]
    s = Names(a="Savings", b="Brokerage")

    def unsettled(session, book):
        assert (session, book) == (s, BOOK)
        return changes

    monkeypatch.setattr(panels.closed, "unsettled", unsettled)
    text = panels.changed_after_filing(s, BOOK)
    assert text == (
        "Realized gains changed by +$1,301.50 after the federal return was filed: "
        "Brokerage, 3 edits; Savings, 1 edit"
    )


def test_edits_since_filing_that_lower_the_gains_say_minus(monkeypatch):
    monkeypatch.setattr(panels.closed, "unsettled", lambda s, book: [change("a", "-0.01")])
    text = panels.changed_after_filing(Names(a="Savings"), None)
    assert text == (
        "Realized gains changed by -$0.01 after the federal return was filed: Savings, 1 edit"
    )


def test_edits_since_filing_that_cancel_out_say_plus_nothing(monkeypatch):
    changes = [change("a", "-5"), change("a", "5")]
    monkeypatch.setattr(panels.closed, "unsettled", lambda s, book: changes)
    text = panels.changed_after_filing(Names(a="Savings"), None)
    assert text == (
        "Realized gains changed by +$0.00 after the federal return was filed: Savings, 2 edits"
    )


def test_a_difference_from_filed_is_of_each_accounts_gains_and_names_them_sorted(monkeypatch):
    seen = {}
    s = Names(a="Zeta", b="Alpha")

    def unexplained(session, book, live):
        assert (session, book) == (s, BOOK)
        seen.update(live)
        return {"b": D("-1500.25"), "a": D("400")}

    monkeypatch.setattr(panels.closed, "unexplained", unexplained)
    rows = [
        row("A", "100", "40", account="a"),
        row("A", "100", "40", account="a"),
        row("A", "100", None, account="b"),  # no basis: counted as no gain
        row("C", "10", "4", account=None),  # an item with no account: not in the check
    ]
    text = panels.differs_from_filed(s, BOOK, rows)
    assert seen == {"a": D("120.00"), "b": D("0")}
    assert text == (
        "Realized gains differ by -$1,100.25 from those when the federal return was filed, "
        "by no change made here: Alpha, Zeta"
    )


def test_no_difference_from_filed_is_no_issue(monkeypatch):
    monkeypatch.setattr(panels.closed, "unexplained", lambda s, book, live: {})
    assert panels.differs_from_filed(Names(), None, [row("A", "1", "1")]) is None


def test_a_difference_from_filed_that_cancels_out_says_plus_nothing(monkeypatch):
    monkeypatch.setattr(
        panels.closed, "unexplained", lambda s, book, live: {"a": D("3"), "b": D("-3")}
    )
    text = panels.differs_from_filed(Names(a="A", b="B"), None, [])
    assert text.startswith("Realized gains differ by +$0.00 from those")


# ---------- Physical items sold, a residence (S8.13) ----------


def thing(c, account_id, sold_on=None, proceeds=None, fees="0", **kw):
    it = item(c, account_id, **kw)
    if sold_on:
        saved(sell(c, it["id"], sold_on, proceeds, fees))
    return it


def rows_of(server, book_id):
    """The book's 8949 rows as the panels work them out, with what the API leaves out."""
    from moolakata.store.entities.taxes import TaxBook

    with server.db.read(unscoped="test") as s:
        return panels.form_8949(s, s.get(TaxBook, book_id))[0]


def test_physical_items_sold_in_the_year_are_8949_rows(server, alice):
    coll = new_account(alice, name="Coins", type="collectables")
    metal = new_account(alice, name="Vault", type="precious-metals")
    cars = new_account(alice, name="Cars", type="vehicle")
    other = new_account(alice, name="Stuff", type="other-asset")
    homes = new_account(alice, name="Homes", type="real-estate")
    # Held exactly a year: short term; a day more: long term.
    thing(alice, coll["id"], "2026-05-01", "3000", "100", name="Coin", acquiredOn="2025-05-01")
    thing(alice, metal["id"], "2026-05-01", "500", name="Bar", acquiredOn="2025-04-30",
          costBasis="800")  # fmt: skip
    thing(alice, cars["id"], "2026-01-01", "18000", name="Car", acquiredOn="2022-01-01",
          costBasis="30000", personalUse=True)  # fmt: skip
    thing(alice, cars["id"], "2026-12-31", "5000", name="Bike", acquiredOn="2022-01-01",
          costBasis="5000", personalUse=True)  # fmt: skip
    thing(alice, other["id"], "2026-06-01", "400", name="Loom", acquiredOn="2026-01-02")
    home = thing(alice, homes["id"], name="Cabin", acquiredOn="2020-01-02", costBasis="100000",
                 closingCosts="2000")  # fmt: skip
    for day, amount in (("2025-06-01", "5000"), ("2026-08-01", "7000")):
        r = make(alice, "Imprv", itemId=home["id"], date=day, description="Roof", amount=amount)
        assert r.status_code == 200, r.text
    saved(sell(alice, home["id"], "2026-07-01", "150000", "6000"))
    # Not this book's: sold the year before or the year after, never sold, deleted, and sold
    # from an account the book leaves out.
    thing(alice, other["id"], "2025-12-31", "10", name="Old")
    thing(alice, other["id"], "2027-01-02", "10", name="Next")
    thing(alice, other["id"], name="Kept")
    gone = thing(alice, other["id"], "2026-03-01", "10", name="Gone")
    saved(drop(alice, "Item", f"/ui/api/items/{gone['id']}"))
    left = new_account(alice, name="Left", type="other-asset")
    thing(alice, left["id"], "2026-03-01", "10", name="Elsewhere")
    b = book(alice)
    saved(create(alice, "TxBkA", bookId=b, accountId=left["id"], counted=False))
    rows = {r["description"]: r for r in read_panels(alice, b)["rows"]}
    assert set(rows) == {"Coin", "Bar", "Car", "Bike", "Loom", "Cabin"}
    want = {
        # name: proceeds, basis, code, adjustment, gain, long term, box, collectable
        "Coin": ("2900.00", "1000.00", "C", "0.00", "1900.00", False, "C", True),
        "Bar": ("500.00", "800.00", "C", "0.00", "-300.00", True, "F", True),
        "Car": ("18000.00", "30000.00", "L", "12000.00", "0.00", True, "F", False),
        "Bike": ("5000.00", "5000.00", "", "0.00", "0.00", True, "F", False),
        "Loom": ("400.00", "1000.00", "", "0.00", "-600.00", False, "C", False),
        # The improvement made after the sale is not in its basis.
        "Cabin": ("144000.00", "107000.00", "", "0.00", "37000.00", True, "F", False),
    }
    fields = ("proceeds", "basis", "code", "adjustment", "gain", "longTerm", "box", "collectable")
    got = {k: tuple(r[f] for f in fields) for k, r in rows.items()}
    assert got == want
    accounts = {a["name"]: a["id"] for a in (coll, metal, cars, other, homes)}
    direct = {r.description: r for r in rows_of(server, b)}
    assert {k: (r.account, r.accountId) for k, r in direct.items()} == {
        "Coin": ("Coins", accounts["Coins"]),
        "Bar": ("Vault", accounts["Vault"]),
        "Car": ("Cars", accounts["Cars"]),
        "Bike": ("Cars", accounts["Cars"]),
        "Loom": ("Stuff", accounts["Stuff"]),
        "Cabin": ("Homes", accounts["Homes"]),
    }
    assert {r.kind for r in direct.values()} == {"item"}
    coin = direct["Coin"]
    assert (coin.acquired, coin.sold) == (dt.date(2025, 5, 1), dt.date(2026, 5, 1))


def test_a_sold_primary_residence_has_its_gain_and_years_owned(alice):
    homes = new_account(alice, name="Homes", type="real-estate")
    # "Attic" sorts first: an account not real estate is passed over, never the end of the list.
    other = new_account(alice, name="Attic", type="other-asset")
    # 384 days: 1.05 years and a little, to the tenth.
    home = thing(alice, homes["id"], name="Elm St", acquiredOn="2025-01-01", costBasis="300000",
                 closingCosts="4000", primaryResidence=True)  # fmt: skip
    r = make(alice, "Imprv", itemId=home["id"], date="2025-06-01", description="Deck",
             amount="6000")  # fmt: skip
    assert r.status_code == 200, r.text
    saved(sell(alice, home["id"], "2026-01-20", "350000", "20000"))
    # Sold on the year's first day and its last.
    thing(alice, homes["id"], "2026-01-01", "100000", name="Pine St", acquiredOn="2025-01-01",
          costBasis="90000", primaryResidence=True)  # fmt: skip
    thing(alice, homes["id"], "2026-12-31", "200000", name="Oak St", acquiredOn="2016-12-31",
          costBasis="200000", primaryResidence=True)  # fmt: skip
    # Not a sold residence of the year: a rental, one sold the year before or after, one kept,
    # one deleted, one in a real-estate account the book leaves out, and the attic's things.
    thing(alice, homes["id"], "2026-03-01", "90000", name="Rental", acquiredOn="2020-01-01")
    thing(alice, homes["id"], "2025-12-31", "90000", name="Before", acquiredOn="2020-01-01",
          primaryResidence=True)  # fmt: skip
    thing(alice, homes["id"], "2027-01-02", "90000", name="After", acquiredOn="2020-01-01",
          primaryResidence=True)  # fmt: skip
    thing(alice, homes["id"], name="Kept", acquiredOn="2020-01-01", primaryResidence=True)
    gone = thing(alice, homes["id"], "2026-02-01", "1", name="Gone", primaryResidence=True)
    saved(drop(alice, "Item", f"/ui/api/items/{gone['id']}"))
    lake = new_account(alice, name="Lake", type="real-estate")
    thing(alice, lake["id"], "2026-05-01", "1", name="Cabin", primaryResidence=True)
    thing(alice, other["id"], "2026-04-01", "1", name="Shed")
    b = book(alice)
    saved(create(alice, "TxBkA", bookId=b, accountId=lake["id"], counted=False))
    got = sorted(
        (x["name"], x["sold"], x["gain"], x["yearsOwned"])
        for x in read_panels(alice, b)["residences"]
    )
    assert got == [
        ("Elm St", "2026-01-20", "20000.00", 1.1),
        ("Oak St", "2026-12-31", "0.00", 10.0),
        ("Pine St", "2026-01-01", "10000.00", 1.0),
    ]


# ---------- Sales in the year's investing accounts (S8.1) ----------


def test_the_8949_rows_are_the_sales_in_the_years_investing_accounts(server, alice):
    # "Bank" sorts first: an account with no sales is passed over, never the end of the list.
    bank = new_account(alice, name="Bank", type="checking")
    add(alice, bank["id"], "500.00", "2026-03-01", kind="deposit")
    brk = new_account(alice, name="Brokerage", type="brokerage")
    ex = new_account(alice, name="Exchange", type="crypto-exchange")
    wal = new_account(alice, name="Wallet", type="crypto-wallet")
    sales = {}

    def sold(acct, day, qty, price, symbol):
        amount = f"{D(qty) * D(price):.2f}"
        t = add(alice, acct["id"], amount, day, kind="sell", symbol=symbol, quantity=qty,
                price=price)  # fmt: skip
        sales[t["id"]] = (dt.date.fromisoformat(day), acct["id"])

    trade(alice, brk["id"], "2024-01-05", "buy", "10", "100", "IBM")
    # Sold the year before first: passed over, never the end of the account's sales.
    sold(brk, "2025-12-31", "1", "120", "IBM")
    sold(brk, "2026-01-01", "1", "130", "IBM")
    sold(brk, "2026-12-31", "2", "140", "IBM")
    sold(brk, "2027-01-02", "1", "150", "IBM")
    trade(alice, ex["id"], "2025-03-01", "buy", "1", "50000", "BTC")
    sold(ex, "2026-06-01", "0.5", "60000", "BTC")
    trade(alice, wal["id"], "2026-02-01", "buy", "1", "40000", "BTC")
    sold(wal, "2026-07-01", "0.25", "44000", "BTC")
    b = book(alice)
    rows = rows_of(server, b)
    got = sorted(
        (r.account, r.description, r.sold, r.proceeds, r.basis, r.box, r.kind, r.quantity)
        for r in rows
    )
    assert got == [
        ("Brokerage", "1 IBM", dt.date(2026, 1, 1), D("130.00"), D("100.00"), "D", "holding",
         D("1")),
        ("Brokerage", "2 IBM", dt.date(2026, 12, 31), D("280.00"), D("200.00"), "D", "holding",
         D("2")),
        ("Exchange", "0.5 BTC", dt.date(2026, 6, 1), D("30000.00"), D("25000.00"), "K",
         "holding", D("0.5")),
        ("Wallet", "0.25 BTC", dt.date(2026, 7, 1), D("11000.00"), D("10000.00"), "I",
         "holding", D("0.25")),
    ]  # fmt: skip
    for r in rows:
        assert sales[r.saleId] == (r.sold, r.accountId)
        assert r.instrumentId


def opt(c, acct, action, day, premium, underlying="MSFT", right="call", strike="500",
        expiry="2026-12-18", contracts="1"):  # fmt: skip
    return saved(option_trade(c, acct, day, action, underlying, right, strike, expiry, contracts,
                              premium, "0"))  # fmt: skip


def test_an_options_row_is_its_premium_and_its_close_as_paid(server, alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    # Written: the premium received is the proceeds, the close's cost the basis.
    opt(alice, brk["id"], "sell-to-open", "2026-02-02", "4.00", right="put", strike="400")
    opt(alice, brk["id"], "buy-to-close", "2026-03-02", "1.00", right="put", strike="400")
    opt(alice, brk["id"], "sell-to-open", "2026-02-02", "1.00", right="put", strike="300")
    opt(alice, brk["id"], "buy-to-close", "2026-03-02", "3.50", right="put", strike="300")
    # Bought: the premium paid is the basis.
    opt(alice, brk["id"], "buy-to-open", "2026-02-02", "2.00", strike="600")
    opt(alice, brk["id"], "sell-to-close", "2026-03-02", "5.00", strike="600")
    rows = {r.description.split(" ", 1)[1]: r for r in rows_of(server, book(alice))}
    got = {k: (r.proceeds, r.basis, r.gain, r.kind, r.longTerm) for k, r in rows.items()}
    assert got == {
        "MSFT 18DEC26 400 P": (D("400.00"), D("100.00"), D("300.00"), "option", False),
        "MSFT 18DEC26 300 P": (D("100.00"), D("350.00"), D("-250.00"), "option", False),
        "MSFT 18DEC26 600 C": (D("500.00"), D("200.00"), D("300.00"), "option", False),
    }


# ---------- The wash sales a book lists (S3.8, S8.3) ----------


def test_a_wash_sale_lists_its_whole_loss_and_the_replacements_basis_with_it(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    other = new_account(alice, name="Second", type="brokerage")
    trade(alice, brk["id"], "2026-01-05", "buy", "6", "100", "IBM")
    trade(alice, brk["id"], "2026-01-20", "buy", "4", "110", "IBM")
    trade(alice, brk["id"], "2026-02-02", "buy", "2", "50", "IBM")
    # One sale of the three lots: a 400 loss, 216 (36 a share) and 184 (46 a share), and a
    # gain of 28 on the third, which is no part of the loss.
    trade(alice, brk["id"], "2026-03-02", "sell", "12", "64", "IBM")
    # Eight of its ten shares replaced by one lot, the earliest acquired first: the six of the
    # first lot, two of the second, each wash with its share of the lot's 560 cost.
    trade(alice, other["id"], "2026-03-16", "buy", "8", "70", "IBM")
    washes = sorted(read_panels(alice, book(alice))["washes"], key=lambda w: w["disallowed"])
    for w in washes:
        assert (w["sold"], w["symbol"], w["account"]) == ("2026-03-02", "IBM", "Brokerage")
        assert (w["replacedOn"], w["replacementAccount"]) == ("2026-03-16", "Second")
        assert w["loss"] == "400.00", "the sale's whole loss, of both its losing lots"
        assert not w["review"]
    got = [(w["replacementQty"], w["disallowed"], w["adjustedBasis"]) for w in washes]
    assert got == [("2.0", "92.00", "232.00"), ("6.0", "216.00", "636.00")]


def test_an_added_accounts_wash_sale_is_listed_with_its_row(server, alice):
    # S8.14.2, S8.3: an account another user owns, shared and added to the book, counts with
    # its wash sales: the row's W adjustment and the wash beside it.
    from edits import share

    make_user(server, "bob")
    bob = sign_in(server, "bob")
    me = alice.get("/ui/api/session").json()["user"]["id"]
    kid = new_account(bob, name="Emma's custodial", type="brokerage")
    share(bob, "account", kid["id"], users={me: "read"})
    trade(bob, kid["id"], "2026-01-05", "buy", "10", "100", "IBM")
    trade(bob, kid["id"], "2026-03-02", "sell", "10", "80", "IBM")
    trade(bob, kid["id"], "2026-03-16", "buy", "10", "82", "IBM")
    b = book(alice)
    saved(create(alice, "TxBkA", bookId=b, accountId=kid["id"], counted=True))
    p = read_panels(alice, b)
    assert [(r["description"], r["code"], r["adjustment"]) for r in p["rows"]] == [
        ("10 IBM", "W", "200.00")
    ]
    assert [(w["symbol"], w["account"], w["disallowed"]) for w in p["washes"]] == [
        ("IBM", "Emma's custodial", "200.00")
    ]


def test_a_book_lists_only_the_wash_sales_of_the_accounts_it_counts(alice):
    # The left-out account's wash sale comes first: passed over, never the end of the list.
    early = new_account(alice, name="Early", type="brokerage")
    late = new_account(alice, name="Late", type="brokerage")
    trade(alice, early["id"], "2026-01-05", "buy", "10", "100", "IBM")
    trade(alice, early["id"], "2026-02-02", "sell", "10", "80", "IBM")
    trade(alice, early["id"], "2026-02-10", "buy", "10", "82", "IBM")
    trade(alice, late["id"], "2026-01-05", "buy", "10", "100", "AAPL")
    trade(alice, late["id"], "2026-03-02", "sell", "10", "90", "AAPL")
    trade(alice, late["id"], "2026-03-10", "buy", "10", "91", "AAPL")
    b = book(alice)
    saved(create(alice, "TxBkA", bookId=b, accountId=early["id"], counted=False))
    assert [(w["symbol"], w["account"]) for w in read_panels(alice, b)["washes"]] == [
        ("AAPL", "Late")
    ]


def reviews(c, b):
    return [w for w in read_panels(c, b)["washes"] if w["review"]]


def test_a_stock_sold_at_a_loss_with_a_call_bought_on_it_is_flagged(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "HHH"):
        trade(alice, brk["id"], "2026-01-05", "buy", "10", "100", symbol)
    # In the order sold: a gain of 0.50, none, a gain: not flagged, whatever was bought.
    trade(alice, brk["id"], "2026-03-02", "sell", "10", "100.05", "AAA")
    trade(alice, brk["id"], "2026-03-03", "sell", "10", "100", "BBB")
    trade(alice, brk["id"], "2026-03-04", "sell", "10", "120", "CCC")
    for symbol in ("AAA", "BBB", "CCC", "DDD", "GGG"):
        opt(alice, brk["id"], "buy-to-open", "2026-03-10", "1.00", underlying=symbol,
            contracts="2")  # fmt: skip
    # A loss with a call bought on it: flagged.
    trade(alice, brk["id"], "2026-03-05", "sell", "10", "90", "DDD")
    # A loss with a put written on it, one with a call bought on another stock, one with the
    # shares bought back (a wash sale, not a review): not flagged.
    trade(alice, brk["id"], "2026-03-06", "sell", "10", "90", "EEE")
    opt(alice, brk["id"], "sell-to-open", "2026-03-10", "1.00", underlying="EEE", right="put")
    trade(alice, brk["id"], "2026-03-07", "sell", "10", "90", "FFF")
    trade(alice, brk["id"], "2026-03-08", "sell", "10", "90", "HHH")
    trade(alice, brk["id"], "2026-03-20", "buy", "10", "91", "HHH")
    p = read_panels(alice, book(alice))
    assert [w["symbol"] for w in p["washes"] if not w["review"]] == ["HHH"]
    (w,) = [w for w in p["washes"] if w["review"]]
    assert w == {
        "sold": "2026-03-05", "symbol": "DDD", "account": "Brokerage", "loss": "100.00",
        "disallowed": "0.00", "replacedOn": "2026-03-10", "replacementAccount": "Brokerage",
        "replacementQty": "2.0", "adjustedBasis": None, "review": True,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("bought", "flagged"),
    [("2026-02-03", False), ("2026-02-04", True), ("2026-04-05", True), ("2026-04-06", False)],
)
def test_an_option_bought_flags_a_loss_within_30_days_either_side(alice, bought, flagged):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    trade(alice, brk["id"], "2026-01-05", "buy", "10", "100", "DDD")
    trade(alice, brk["id"], "2026-03-06", "sell", "10", "90", "DDD")
    opt(alice, brk["id"], "buy-to-open", bought, "1.00", underlying="DDD")
    assert len(reviews(alice, book(alice))) == int(flagged)


@pytest.mark.parametrize("kind", ["buy", "reinvest", "sell"])
def test_an_options_loss_with_its_stock_bought_is_flagged(alice, kind):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    trade(alice, brk["id"], "2026-01-05", "buy", "20", "100", "XYZ")
    opt(alice, brk["id"], "buy-to-open", "2026-02-02", "5.00", underlying="XYZ")
    opt(alice, brk["id"], "sell-to-close", "2026-03-02", "2.00", underlying="XYZ")
    # Written and closed at a loss too.
    opt(alice, brk["id"], "sell-to-open", "2026-02-02", "1.00", underlying="XYZ", right="put")
    opt(alice, brk["id"], "buy-to-close", "2026-03-03", "1.50", underlying="XYZ", right="put")
    if kind == "sell":
        # Its stock sold, and another stock bought: nothing of its stock bought.
        trade(alice, brk["id"], "2026-03-20", "sell", "7", "100", "XYZ")
        trade(alice, brk["id"], "2026-03-20", "buy", "7", "100", "ABC")
    else:
        add(alice, brk["id"], "-700.00", "2026-03-20", kind=kind, symbol="XYZ", quantity="7",
            price="100")  # fmt: skip
    got = [(w["symbol"], w["loss"], w["replacedOn"], w["replacementQty"])
           for w in reviews(alice, book(alice))]  # fmt: skip
    if kind == "sell":
        assert got == []
    else:
        assert got == [
            ("XYZ 18DEC26 500 C", "300.00", "2026-03-20", "7.0"),
            ("XYZ 18DEC26 500 P", "50.00", "2026-03-20", "7.0"),
        ]


def test_an_imported_option_with_no_contract_is_flagged_for_nothing(server, alice):
    # A file's option whose ticker can't be read is an option with no contract: no underlying
    # to look for, so its loss flags nothing.
    from moolakata.store.entities.accounts import Account
    from moolakata.store.repos import ledger as repo

    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2026-03-10", "buy", "10", "100", "DDD")
    with server.db.tx(unscoped="test: an option a file named") as s:
        inst_id = repo.instrument(s, "DDD MYSTERY", None, "option").id
    loss = row("A", "50", "300")
    loss.instrumentId = inst_id
    with server.db.read(unscoped="test") as s:
        inst = s.get(panels.Instrument, inst_id)
        got = panels._option_reviews(s, [loss], [s.get(Account, brk["id"])], {inst_id: inst})
    assert got == []


def test_a_spouses_call_bought_flags_the_loss_too(server, alice):
    from moolakata.store.entities.accounts import Account
    from moolakata.store.entities.taxes import TaxBook

    make_user(server, "bob")
    bob = sign_in(server, "bob")
    theirs = new_account(bob, name="Bob's", type="brokerage")
    add(bob, theirs["id"], "10000.00", "2026-01-02", kind="deposit")
    opt(bob, theirs["id"], "buy-to-open", "2026-03-10", "1.00", underlying="DDD")
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2026-01-05", "buy", "10", "100", "DDD")
    trade(alice, brk["id"], "2026-03-06", "sell", "10", "90", "DDD")
    b = book(alice)
    with server.db.read(unscoped="test") as s:
        book_ = s.get(TaxBook, b)
        assert panels.form_8949(s, book_)[1] == []
        _, washes = panels.form_8949(s, book_, [s.get(Account, theirs["id"])])
    assert [(w.symbol, w.replacementAccount, w.review) for w in washes] == [("DDD", "Bob's", True)]


def settle(c, acct, symbol, how, day):
    held = next(
        r
        for r in c.get("/ui/api/positions", params={"kind": "options"}).json()["open"]
        if r["symbol"] == symbol
    )
    r = c.post(f"/ui/api/accounts/{acct}/options/{held['instrumentId']}/settle",
               json={"how": how, "date": day, "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text


@pytest.mark.parametrize(
    ("underlying", "how", "day", "flagged"),
    [
        ("MSFT", "exercise", "2026-06-15", True),  # the stock bought back through a call
        ("MSFT", "exercise", "2026-07-02", False),  # 31 days after
        ("IBM", "exercise", "2026-06-15", False),  # another stock's
        ("MSFT", "assign", "2026-06-15", False),  # a call assigned sells the stock
    ],
)
def test_shares_bought_through_a_call_exercised_are_flagged(alice, underlying, how, day, flagged):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "200000.00", "2026-01-02", kind="deposit")
    trade(alice, brk["id"], "2026-01-05", "buy", "200", "500", "MSFT")
    trade(alice, brk["id"], "2026-06-01", "sell", "100", "450", "MSFT")  # a 5,000 loss
    # Opened more than 30 days before the sale: the trade itself flags nothing.
    action = "buy-to-open" if how == "exercise" else "sell-to-open"
    opt(alice, brk["id"], action, "2026-04-01", "3.00", underlying=underlying, strike="520")
    settle(alice, brk["id"], f"{underlying} 18DEC26 520 C", how, day)
    got = [(w["symbol"], w["replacedOn"], w["replacementQty"]) for w in reviews(alice, book(alice))]
    assert got == ([("MSFT", day, "100.0")] if flagged else [])


# ---------- Missing or doubtful data (S8.4) ----------


class Records:
    """A session that holds a few records by kind and id, and answers its one query (the
    transfers in) with the list given."""

    def __init__(self, records, transfers=()):
        self.records = records
        self.transfers = list(transfers)

    def get(self, cls, id_):
        return self.records.get((cls, id_))

    def scalars(self, _query):
        return self.transfers


def acct(id_, name, type_, owner="u1"):
    return SimpleNamespace(id=id_, name=name, type=type_, ownerId=owner)


def sale(description, sold, basis="1", acquired_missing=False, lot_missing=False):
    return panels.Row(
        description=description, acquired=None, sold=sold, proceeds=D("10"),
        basis=None if basis is None else D(basis), code="", adjustment=D(0), longTerm=False,
        box="A", account="Brokerage", accountId="a2", acquiredMissing=acquired_missing,
        lotMissing=lot_missing,
    )  # fmt: skip


@pytest.fixture
def quiet(monkeypatch):
    """A book with nothing to look at, each check's answer to be set by the test."""
    from moolakata.store import mapping

    mapping.map_all()  # the transfers' query is built on the mapped records
    counted = SimpleNamespace(accounts=[], leftOut=[])
    monkeypatch.setattr(panels, "changed_after_filing", lambda s, book: None)
    monkeypatch.setattr(panels, "differs_from_filed", lambda s, book, rows: None)
    monkeypatch.setattr(panels.books, "carryover", lambda s, book: (D(0), D(0), False))
    monkeypatch.setattr(panels.books, "counted", lambda s, book: counted)
    monkeypatch.setattr(panels.dependents, "listed", lambda s, book: [])
    monkeypatch.setattr(panels.dependents, "filers_claimed_elsewhere", lambda s, book: [])
    monkeypatch.setattr(panels.dependents, "form_8615", lambda s, book, deps, accounts: [])
    return counted


def test_a_book_with_nothing_doubtful_lists_no_issue(quiet):
    assert panels.issues(Records({}), SimpleNamespace(year=2026), []) == []


def test_each_doubtful_thing_is_listed_with_its_kind_words_and_link(quiet, monkeypatch):
    msft, vti = SimpleNamespace(symbol="MSFT"), SimpleNamespace(symbol="VTI")
    bank, brk, ira = (acct("a1", "Bank", "checking"), acct("a2", "Brokerage", "brokerage"),
                      acct("a3", "IRA", "ira"))  # fmt: skip
    theirs, mine = acct("a8", "Bob's Brokerage", "brokerage", "u2"), acct("a9", "Mine", "brokerage")
    quiet.accounts[:] = [bank, brk, ira]
    quiet.leftOut[:] = [acct("a4", "Old", "brokerage")]
    monkeypatch.setattr(panels, "changed_after_filing", lambda s, book: "Changed.")
    monkeypatch.setattr(panels, "differs_from_filed", lambda s, book, rows: "Differs.")
    monkeypatch.setattr(panels.books, "carryover", lambda s, book: (D(0), D(0), True))
    replay = SimpleNamespace(
        problems=[
            SimpleNamespace(kind="sale-without-lot", instrumentId="i1", date=dt.date(2026, 5, 1)),
            # The year before's, and another kind of problem: not this book's to list.
            SimpleNamespace(kind="sale-without-lot", instrumentId="i1", date=dt.date(2025, 12, 31)),
            SimpleNamespace(kind="oversold", instrumentId="i1", date=dt.date(2026, 6, 1)),
        ],
        open=[
            # Moved in without its day bought, its basis missing too: listed once, for the day.
            SimpleNamespace(
                acquiredMissing=True, basis=None, instrumentId="i2", acquiredOn=dt.date(2025, 3, 4)
            ),
            SimpleNamespace(
                acquiredMissing=False,
                basis=D(100),
                instrumentId="i2",
                acquiredOn=dt.date(2025, 3, 4),
            ),
            SimpleNamespace(
                acquiredMissing=False, basis=None, instrumentId="i1", acquiredOn=dt.date(2025, 3, 4)
            ),
        ],
    )

    def load(s, a):
        # Only an investing account's ledger is read: the bank's and the IRA's never.
        assert a is brk
        return SimpleNamespace(replay=lambda: replay)

    monkeypatch.setattr(panels.repo, "load", load)
    emma = SimpleNamespace(person=SimpleNamespace(name="Emma"), claimedElsewhere=True)
    liam = SimpleNamespace(person=SimpleNamespace(name="Liam"), claimedElsewhere=False)
    monkeypatch.setattr(panels.dependents, "listed", lambda s, book: [emma, liam])
    monkeypatch.setattr(panels.dependents, "filers_claimed_elsewhere",
                        lambda s, book: [SimpleNamespace(name="Bob")])  # fmt: skip
    monkeypatch.setattr(panels.dependents, "form_8615", lambda s, book, deps, accounts: [
        SimpleNamespace(name="Emma", unearned=D("3456.7"), threshold=D("2700"))])  # fmt: skip
    gift = SimpleNamespace(accountId="a2", transferId="t1", date=dt.date(2026, 8, 9))
    own = SimpleNamespace(accountId="a2", transferId="t2", date=dt.date(2026, 8, 10))
    lost = SimpleNamespace(accountId="a2", transferId="t3", date=dt.date(2026, 8, 11))
    records = {
        (panels.Instrument, "i1"): msft, (panels.Instrument, "i2"): vti,
        (panels.Transaction, "t1"): SimpleNamespace(accountId="a8"),
        (panels.Transaction, "t2"): SimpleNamespace(accountId="a9"),
        (panels.Account, "a8"): theirs, (panels.Account, "a9"): mine,
    }  # fmt: skip
    rows = [
        sale("5 VTI", dt.date(2026, 6, 2), acquired_missing=True),
        sale("3 MSFT", dt.date(2026, 5, 1), basis=None, lot_missing=True),
        sale("2 IBM", dt.date(2026, 7, 3), basis=None),
    ]
    got = panels.issues(Records(records, [gift, own, lost]), SimpleNamespace(year=2026), rows)
    link = "/ui/accounts/a2/holdings"
    assert [(i.kind, i.text, i.link) for i in got] == [
        ("changed-after-filing", "Changed.", None),
        ("differs-from-filed", "Differs.", None),
        ("carryover-share", "Type your share of 2025's joint return's capital-loss carryover: "
         "splitting it is yours to decide, and none counts until it is typed.", None),
        ("left-out", "Old is left out of this tax book.", None),
        ("sale-without-lot", "Brokerage: MSFT sold on May 1 without a lot to match", link),
        ("acquired-missing", "Brokerage: VTI moved in on Mar 4, 2025: when it was bought, and "
         "its basis, for its term and gain", link),
        ("basis-missing", "Brokerage: a lot of MSFT has no cost basis", link),
        ("sale-acquired-missing", "Brokerage: the sale of 5 VTI on Jun 2 is of shares moved in: "
         "when they were bought, for its term", link),
        ("sale-basis", "Brokerage: the sale of 3 MSFT on May 1 has no basis or day bought", None),
        ("sale-basis", "Brokerage: the sale of 2 IBM on Jul 3 has no basis", None),
        ("claimed-twice", "Emma is claimed on another 2026 tax book too", None),
        ("claimed-elsewhere", "Bob is claimed as a dependent on another 2026 tax book", None),
        ("form-8615", "Emma's unearned income of $3,456.70 is above the $2,700 threshold: "
         "Form 8615 may apply", None),
        ("gift-basis", "Brokerage: shares from Bob's Brokerage on Aug 9 keep the giver's basis",
         None),
    ]  # fmt: skip


def test_shares_moved_in_from_another_users_account_in_the_year_keep_its_basis(server, alice):
    from moolakata import ids
    from moolakata.store.entities.accounts import Transaction

    make_user(server, "bob")
    bob = sign_in(server, "bob")
    theirs = new_account(bob, name="Bob's", type="brokerage")
    mine = new_account(alice, name="Mine", type="brokerage")
    days = ("2025-12-31", "2026-01-01", "2026-06-01", "2026-12-31", "2027-01-01")
    with server.db.tx(unscoped="test: transfers between two users' accounts") as s:
        for n, day in enumerate(days):
            out = Transaction(id=ids.new_id("Txn"), accountId=theirs["id"],
                              date=dt.date.fromisoformat(day), kind="transfer-out",
                              amount=D(-100 - n))  # fmt: skip
            into = Transaction(id=ids.new_id("Txn"), accountId=mine["id"], date=out.date,
                               kind="transfer-in", amount=D(100 + n))  # fmt: skip
            if day == "2026-06-01":
                into.mark_deleted(None)
            s.add_all([out, into])
            s.flush()
            out.transferId, into.transferId = into.id, out.id
        # Money moved out to Bob's, and in from nowhere linked: not a gift's basis.
        out = Transaction(id=ids.new_id("Txn"), accountId=mine["id"], date=dt.date(2026, 3, 2),
                          kind="transfer-out", amount=D(-5))  # fmt: skip
        into = Transaction(id=ids.new_id("Txn"), accountId=theirs["id"], date=out.date,
                           kind="transfer-in", amount=D(5))  # fmt: skip
        s.add_all([out, into])
        s.flush()
        out.transferId, into.transferId = into.id, out.id
        s.add(Transaction(id=ids.new_id("Txn"), accountId=mine["id"], date=dt.date(2026, 3, 3),
                          kind="transfer-in", amount=D(7)))  # fmt: skip
    got = [
        i["text"] for i in read_panels(alice, book(alice))["issues"] if i["kind"] == "gift-basis"
    ]
    assert sorted(got) == [
        "Mine: shares from Bob's on Dec 31 keep the giver's basis",
        "Mine: shares from Bob's on Jan 1 keep the giver's basis",
    ]
