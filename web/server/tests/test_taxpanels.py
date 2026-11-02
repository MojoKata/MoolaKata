"""The tax panels and exports (requirements S8.1–S8.13): Form 8949 with wash sales and
collectables, income, retirement with RMDs, deductions, loans, the issues, and the CSV, TXF and
PDF exports."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import loan_payment, make, option_trade, saved, sell, terms
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server, frozen):
    make_user(server, "alice", born=1951)
    return sign_in(server, "alice")


def book(c):
    me = c.get("/ui/api/session").json()["user"]["id"]
    r = make(c, "TaxBk", year=2026, filers=[me])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def panels(c, b):
    r = c.get(f"/ui/api/tax-books/{b}/panels")
    assert r.status_code == 200, r.text
    return r.json()


def trade(c, acct, day, kind, qty, price, symbol="VTI"):
    amount = float(qty) * float(price)
    add(
        c,
        acct,
        f"{-amount if kind == 'buy' else amount:.2f}",
        day,
        kind=kind,
        symbol=symbol,
        quantity=qty,
        price=price,
    )


def test_8949_rows_terms_boxes_and_a_wash_sale(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    ira = new_account(alice, name="IRA", type="ira")
    trade(alice, brk["id"], "2024-01-05", "buy", "10", "100")
    trade(alice, brk["id"], "2026-02-01", "sell", "4", "150")  # long-term gain
    trade(alice, brk["id"], "2026-03-01", "buy", "10", "200", "AAPL")
    trade(alice, brk["id"], "2026-06-01", "sell", "10", "150", "AAPL")  # short-term loss
    trade(alice, ira["id"], "2026-06-15", "buy", "5", "150", "AAPL")  # the replacement
    b = book(alice)
    p = panels(alice, b)
    rows = {r["description"]: r for r in p["rows"]}
    vti, aapl = rows["4 VTI"], rows["10 AAPL"]
    assert vti["box"] == "D" and vti["longTerm"] and vti["gain"] == "200.00"
    assert aapl["box"] == "A" and aapl["code"] == "W"
    assert aapl["adjustment"] == "250.00", "half the 500 loss: 5 of 10 shares replaced"
    assert aapl["gain"] == "-250.00"
    w = p["washes"][0]
    # In an IRA the loss is lost for good: the replacement keeps its cost (S3.8.3, CR3-391).
    assert w["replacementAccount"] == "IRA" and w["adjustedBasis"] == "750.00"
    d = p["scheduleD"]
    assert d["shortTerm"] == "-250.00" and d["longTerm"] == "200.00"
    csv = alice.get(f"/ui/api/tax-books/{b}/exports/8949.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "D,long,4 VTI,2024-01-05,2026-02-01,600.00,400.00,,,200.00,Brokerage" in csv.text
    txf = alice.get(f"/ui/api/tax-books/{b}/exports/moolakata.txf").text
    assert txf.startswith("V042\r\n") and "N323\r\n" in txf and "N321\r\n" in txf
    assert p["txfLeftOut"] == {"digital": 0, "collectable": 0, "personalUse": 0}
    pdf = alice.get(f"/ui/api/tax-books/{b}/exports/summary.pdf")
    assert pdf.content.startswith(b"%PDF-1.4") and pdf.content.rstrip().endswith(b"%%EOF")


def test_collectables_and_personal_use_losses(alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    cars = new_account(alice, name="Cars", type="vehicle")
    coin = make(
        alice, "Item", accountId=coll["id"], name="Coin", acquiredOn="2020-01-01", costBasis="1000"
    ).json()
    car = make(
        alice,
        "Item",
        accountId=cars["id"],
        name="Car",
        acquiredOn="2022-01-01",
        costBasis="30000",
        personalUse=True,
    ).json()
    saved(sell(alice, coin["id"], "2026-05-01", "3000"))
    saved(sell(alice, car["id"], "2026-05-01", "18000"))
    book_id = book(alice)
    p = panels(alice, book_id)
    rows = {r["description"]: r for r in p["rows"]}
    assert rows["Coin"]["collectable"] and rows["Coin"]["box"] == "F"
    assert rows["Car"]["code"] == "L" and rows["Car"]["gain"] == "0.00"
    assert p["scheduleD"]["collectables"] == "2000.00"
    # TXF has no field for C or L (S8.2): both are left out of it and counted beside it.
    assert p["txfLeftOut"] == {"digital": 0, "collectable": 1, "personalUse": 1}
    txf = alice.get(f"/ui/api/tax-books/{book_id}/exports/moolakata.txf").text
    assert "PCoin" not in txf and "PCar" not in txf


def test_txf_counts_what_it_leaves_out_by_why():
    from decimal import Decimal

    from moolakata.taxes import exports
    from moolakata.taxes.panels import Row

    def row(box, code=""):
        return Row(
            "x",
            dt.date(2025, 1, 2),
            dt.date(2026, 3, 4),
            Decimal(9),
            Decimal(5),
            code,
            Decimal(0),
            box in "DEFJKL",
            box,
            "Acct",
        )

    rows = [row("A"), row("D", "W"), row("I"), row("K"), row("F", "C"), row("C", "L")]
    assert [exports.in_txf(r) for r in rows] == [True, True, False, False, False, False]
    assert exports.txf_left_out(rows) == {"digital": 2, "collectable": 1, "personalUse": 1}


def test_income_retirement_and_an_rmd(alice):
    bank = new_account(alice, name="Savings", type="savings", institution="Ally")
    add(alice, bank["id"], "120.50", "2026-06-30", kind="interest")
    brk = new_account(alice, name="Brokerage", type="brokerage", institution="Fidelity")
    add(
        alice,
        brk["id"],
        "300.00",
        "2026-03-15",
        kind="dividend",
        dividendType="qualified",
        symbol="VTI",
    )
    add(
        alice,
        brk["id"],
        "50.00",
        "2026-03-15",
        kind="dividend",
        dividendType="ordinary",
        symbol="VTI",
    )
    ira = new_account(alice, name="IRA", type="ira")
    add(alice, ira["id"], "265000.00", "2025-06-01", kind="deposit")
    add(alice, ira["id"], "9000.00", "2026-02-01", kind="deposit")
    p = panels(alice, book(alice))
    assert p["income"]["interest"] == [{"label": "Ally", "amount": "120.50"}]
    assert p["income"]["ordinary"] == "350.00" and p["income"]["qualified"] == "300.00"
    c = p["retirement"]["contributions"][0]
    assert c["contributed"] == "9000.00" and c["limit"] == "8600.00" and c["over"]
    rmd = p["retirement"]["rmds"][0]
    assert rmd["age"] == 75 and rmd["factor"] == 24.6
    assert rmd["due"] == "10772.36", "265,000 / 24.6"


def test_deductions_loans_and_issues(alice):
    card = new_account(alice, name="Card", type="credit-card")
    cats = {x["name"]: x["id"] for x in alice.get("/ui/api/categories").json()["items"]}
    add(alice, card["id"], "-240.00", "2026-04-02", payee="Clinic", categoryId=cats["Doctor"])
    home = new_account(alice, name="Mortgage", type="mortgage")
    saved(terms(alice, home["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    saved(loan_payment(alice, home["id"], "2026-02-01", "1798.65"))
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2026-05-01", "sell", "3", "100", "MSFT")  # nothing to sell
    p = panels(alice, book(alice))
    tags = {d["label"]: d for d in p["deductions"]}
    assert tags["Medical and dental"]["total"] == "240.00"
    assert tags["Medical and dental"]["withReceipts"] == 0
    assert tags["Loan interest"]["total"] == "1500.00"
    assert p["loans"][0]["interest"] == "1500.00" and p["loans"][0]["form"] == "1098"
    kinds = {i["kind"] for i in p["issues"]}
    assert {"sale-without-lot", "sale-basis"} <= kinds


def test_an_ira_limit_holds_across_a_persons_accounts(alice):
    # B15, S8.6: two IRAs of one person share one limit: each under it, both together over.
    one = new_account(alice, name="IRA at Fidelity", type="ira")
    two = new_account(alice, name="IRA at Vanguard", type="roth-ira")
    add(alice, one["id"], "5000.00", "2026-02-01", kind="deposit")
    add(alice, two["id"], "4000.00", "2026-03-01", kind="deposit")
    c = {x["account"]: x for x in panels(alice, book(alice))["retirement"]["contributions"]}
    first, second = c["IRA at Fidelity"], c["IRA at Vanguard"]
    assert first["personTotal"] == second["personTotal"] == "9000.00"
    assert first["over"] and second["over"], "9,000 against the person's 8,600 (with catch-up)"
    assert first["across"] == "IRAs"


def test_a_split_counts_toward_its_tag_as_a_whole_transaction_would(alice):
    # B4: a split part takes its transaction's sign: $60 of a $100 pharmacy run is $60 of
    # medical, not $-60, and the rest counts nowhere.
    card = new_account(alice, name="Card", type="credit-card")
    cats = {x["name"]: x["id"] for x in alice.get("/ui/api/categories").json()["items"]}
    add(
        alice,
        card["id"],
        "-100.00",
        "2026-04-02",
        payee="Pharmacy",
        splits=[
            {"categoryId": cats["Doctor"], "amount": "-60.00"},
            {"categoryId": cats["Groceries"], "amount": "-40.00"},
        ],
    )
    p = panels(alice, book(alice))
    tags = {d["label"]: d for d in p["deductions"]}
    assert tags["Medical and dental"]["total"] == "60.00"


def test_a_replacement_covers_only_its_own_shares(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    ira = new_account(alice, name="IRA", type="ira")
    trade(alice, brk["id"], "2026-01-05", "buy", "12", "200", "AAPL")
    trade(alice, brk["id"], "2026-02-05", "buy", "3", "200", "AAPL")
    trade(alice, brk["id"], "2026-06-01", "sell", "15", "150", "AAPL")  # two lots, one sale
    trade(alice, ira["id"], "2026-06-10", "buy", "8", "150", "AAPL")
    p = panels(alice, book(alice))
    total = sum(float(w["disallowed"]) for w in p["washes"])
    assert total == 400.0, "8 of the 15 shares' 750 loss: 50 a share"


def test_shares_from_an_assigned_put_are_flagged_never_a_replacement(alice):
    # B8: the loss isn't washed by shares an assignment bought; the preparer is asked to look.
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    trade(alice, brk["id"], "2026-08-03", "buy", "100", "500", "MSFT")
    trade(alice, brk["id"], "2026-09-01", "sell", "100", "450", "MSFT")  # a 5,000 loss
    saved(option_trade(alice, brk["id"], "2026-08-20", "sell-to-open", "MSFT", "put", "455",
                       "2026-09-18", "1", "4.00"))  # fmt: skip
    held = alice.get("/ui/api/positions", params={"kind": "options"}).json()["open"][0]
    r = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{held['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-09-18"},
    )
    assert r.status_code == 201, r.text
    p = panels(alice, book(alice))
    [w] = p["washes"]
    assert w["review"] and w["disallowed"] == "0.00", w
    [loss] = [r for r in p["rows"] if r["description"] == "100 MSFT"]
    assert loss["code"] == "" and loss["gain"] == "-5000.00"


def test_a_fund_typed_by_its_symbol_is_a_fund_for_its_box(alice):
    # CR3-386, S2.1: a fund bought in 2011 has no reported basis (funds from 2012), so its
    # sale goes in box E; a share bought the same day, in D.
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2011-06-01", "buy", "10", "50", symbol="FSKAX")
    trade(alice, brk["id"], "2011-06-01", "buy", "10", "50", symbol="IBM")
    trade(alice, brk["id"], "2026-03-02", "sell", "10", "60", symbol="FSKAX")
    trade(alice, brk["id"], "2026-03-02", "sell", "10", "60", symbol="IBM")
    rows = {r["description"]: r["box"] for r in panels(alice, book(alice))["rows"]}
    assert rows == {"10 FSKAX": "E", "10 IBM": "D"}


def test_average_cost_is_for_funds_a_share_goes_first_in(alice):
    # CR3-387, S2.3: in an account set to average cost, a fund's sale takes the average of
    # its shares and a listed share's the oldest lot.
    brk = new_account(alice, name="Brokerage", type="brokerage", lotMethod="average")
    for symbol in ("VTSAX", "IBM"):
        trade(alice, brk["id"], "2025-01-06", "buy", "10", "100", symbol=symbol)
        trade(alice, brk["id"], "2025-02-03", "buy", "10", "200", symbol=symbol)
        trade(alice, brk["id"], "2026-03-02", "sell", "10", "250", symbol=symbol)
    rows = {r["description"]: r["basis"] for r in panels(alice, book(alice))["rows"]}
    assert rows == {"10 VTSAX": "1500.00", "10 IBM": "1000.00"}


def test_a_replacement_bought_before_the_loss_sale_is_a_plain_lot_until_it(alice):
    # CR3-388, S3.8.3: highest cost first picks the sale's lots by their cost on the day; the
    # replacement bought nine days before takes the loss only once the sale has it.
    brk = new_account(alice, name="Brokerage", type="brokerage", lotMethod="hifo")
    trade(alice, brk["id"], "2023-08-21", "buy", "10", "366.93", symbol="HON")
    trade(alice, brk["id"], "2024-01-18", "buy", "10", "382.36", symbol="HON")
    trade(alice, brk["id"], "2025-02-21", "buy", "6", "312.57", symbol="HON")
    trade(alice, brk["id"], "2025-03-04", "sell", "6", "310.09", symbol="HON")
    me = alice.get("/ui/api/session").json()["user"]["id"]
    r = make(alice, "TaxBk", year=2025, filers=[me])
    (row,) = panels(alice, r.json()["id"])["rows"]
    assert (row["acquired"], row["basis"], row["adjustment"]) == ("2024-01-18", "2294.16", "433.62")


def test_shares_a_sale_sold_never_replace_it(alice):
    # CR3-388, S3.8.2: last in first out sells the three bought a week before with three of
    # the old lot; those three were sold, so they replace nothing.
    brk = new_account(alice, name="Brokerage", type="brokerage", lotMethod="lifo")
    trade(alice, brk["id"], "2024-01-08", "buy", "10", "200", symbol="IBM")
    trade(alice, brk["id"], "2026-02-23", "buy", "3", "100", symbol="IBM")
    trade(alice, brk["id"], "2026-03-02", "sell", "6", "90", symbol="IBM")
    rows = panels(alice, book(alice))["rows"]
    assert sorted((r["description"], r["adjustment"]) for r in rows) == [
        ("3 IBM", "0.00"),
        ("3 IBM", "0.00"),
    ]


def lots_on(c, account_id, day, sale_id=None):
    q = f"?date={day}" + (f"&saleId={sale_id}" if sale_id else "")
    r = c.get(f"/ui/api/accounts/{account_id}/lots{q}")
    assert r.status_code == 200, r.text
    return {(x["symbol"], x["acquiredOn"]): x for x in r.json()["items"]}


def test_a_sale_takes_the_lots_picked_and_keeps_them_through_an_edit(alice):
    # CR3-389, S2.3: specific identification is chosen per sale: the lots picked, the rest
    # first in; the picks are records of the sale, kept when it changes.
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2024-01-08", "buy", "10", "100", symbol="IBM")
    trade(alice, brk["id"], "2025-06-02", "buy", "10", "300", symbol="IBM")
    held = lots_on(alice, brk["id"], "2026-03-02")
    newer = held[("IBM", "2025-06-02")]
    assert (newer["quantity"], newer["basis"], newer["longTerm"]) == ("10.0", "3000.00", False)
    r = make(alice, "Txn", accountId=brk["id"], date="2026-03-02", kind="sell", symbol="IBM",
             quantity="12", price="250", amount="3000.00",
             picks=[{"lotId": newer["lotId"], "quantity": "8"}])  # fmt: skip
    assert r.status_code == 200, r.text
    sale = alice.get(f"/ui/api/transactions/{r.json()['id']}").json()
    assert [(p["lotId"], p["quantity"]) for p in sale["picks"]] == [(newer["lotId"], "8.0")]

    def rows():
        return sorted((x["acquired"], x["description"], x["basis"])
                      for x in panels(alice, book(alice))["rows"])  # fmt: skip

    assert rows() == [("2024-01-08", "4 IBM", "400.00"), ("2025-06-02", "8 IBM", "2400.00")]
    from edits import change

    sale = saved(change(alice, "Txn", sale, memo="rebalance"))
    assert [
        p["quantity"] for p in alice.get(f"/ui/api/transactions/{sale['id']}").json()["picks"]
    ] == ["8.0"]
    # More than the sale, or than the lot held, is refused.
    pick = alice.get(f"/ui/api/transactions/{sale['id']}").json()["picks"][0]
    r = change(alice, "LotPk", {**pick, "saleId": sale["id"]}, quantity="11")
    assert r.status_code == 422 and "more than" in r.text.lower(), r.text


def test_a_pick_of_a_lot_a_wash_sale_split_takes_from_its_parts(alice):
    # CR3-26: L is bought 10 at $160, 4 of which replace an earlier loss sale; picking L for 10
    # takes all of L, never 6 of K.
    brk = new_account(alice, name="Brokerage", type="brokerage")
    trade(alice, brk["id"], "2025-01-02", "buy", "10", "100", symbol="AAPL")  # K
    trade(alice, brk["id"], "2026-03-02", "buy", "4", "200", symbol="AAPL")  # M
    lot_m = lots_on(alice, brk["id"], "2026-03-20")[("AAPL", "2026-03-02")]
    sold = make(alice, "Txn", accountId=brk["id"], date="2026-03-20", kind="sell",
                symbol="AAPL", quantity="4", price="150", amount="600.00",
                picks=[{"lotId": lot_m["lotId"], "quantity": "4"}])  # fmt: skip
    assert sold.status_code == 200, sold.text
    trade(alice, brk["id"], "2026-04-01", "buy", "10", "160", symbol="AAPL")  # L
    held = lots_on(alice, brk["id"], "2026-05-01")
    lot_l = held[("AAPL", "2026-04-01")]
    assert (lot_l["quantity"], lot_l["basis"]) == ("10.0", "1800.00")  # 1600 + the 200 washed
    r = make(alice, "Txn", accountId=brk["id"], date="2026-05-01", kind="sell", symbol="AAPL",
             quantity="10", price="170", amount="1700.00",
             picks=[{"lotId": lot_l["lotId"], "quantity": "10"}])  # fmt: skip
    assert r.status_code == 200, r.text
    may = [x for x in panels(alice, book(alice))["rows"] if x["sold"] == "2026-05-01"]
    assert sorted((x["acquired"], x["description"]) for x in may) == [
        ("2026-04-01", "4 AAPL"),
        ("2026-04-01", "6 AAPL"),
    ]


def test_fewer_shares_bought_back_replace_the_earliest_acquired(alice):
    # CR3-390, S3.8.2, Treas. Reg. §1.1091-1(c): highest cost first sells the $120 lot then
    # the $100 one, both at a loss; the ten bought back replace the earliest acquired.
    brk = new_account(alice, name="Brokerage", type="brokerage", lotMethod="hifo")
    trade(alice, brk["id"], "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(alice, brk["id"], "2025-02-03", "buy", "10", "120", symbol="IBM")
    trade(alice, brk["id"], "2026-03-02", "sell", "20", "80", symbol="IBM")
    trade(alice, brk["id"], "2026-03-16", "buy", "10", "82", symbol="IBM")
    rows = panels(alice, book(alice))["rows"]
    assert sorted((r["acquired"], r["adjustment"]) for r in rows) == [
        ("2025-01-06", "200.00"),
        ("2025-02-03", "0.00"),
    ]
