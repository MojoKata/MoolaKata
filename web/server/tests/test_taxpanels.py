"""The tax panels and exports (requirements S8.1–S8.13): Form 8949 with wash sales and
collectables, income, retirement with RMDs, deductions, loans, the issues, and the CSV, TXF and
PDF exports."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import (
    change,
    edit,
    loan_payment,
    make,
    new_id,
    option_trade,
    remove,
    saved,
    sell,
    share,
    terms,
)
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane", born=1951)
    return sign_in(server, "jane")


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


def test_8949_rows_terms_boxes_and_a_wash_sale(jane):
    brk = new_account(jane, name="Brokerage", type="brokerage")
    ira = new_account(jane, name="IRA", type="ira")
    trade(jane, brk["id"], "2024-01-05", "buy", "10", "100")
    trade(jane, brk["id"], "2026-02-01", "sell", "4", "150")  # long-term gain
    trade(jane, brk["id"], "2026-03-01", "buy", "10", "200", "AAPL")
    trade(jane, brk["id"], "2026-06-01", "sell", "10", "150", "AAPL")  # short-term loss
    trade(jane, ira["id"], "2026-06-15", "buy", "5", "150", "AAPL")  # the replacement
    b = book(jane)
    p = panels(jane, b)
    rows = {r["description"]: r for r in p["rows"]}
    vti, aapl = rows["4 VTI"], rows["10 AAPL"]
    assert vti["box"] == "D" and vti["longTerm"] and vti["gain"] == "200.00"
    assert aapl["box"] == "A" and aapl["code"] == "W"
    assert aapl["adjustment"] == "250.00", "half the 500 loss: 5 of 10 shares replaced"
    assert aapl["gain"] == "-250.00"
    w = p["washes"][0]
    # In an IRA the loss is lost for good: the replacement keeps its cost (S3.8.3).
    assert w["replacementAccount"] == "IRA" and w["adjustedBasis"] == "750.00"
    d = p["scheduleD"]
    assert d["shortTerm"] == "-250.00" and d["longTerm"] == "200.00"
    csv = jane.get(f"/ui/api/tax-books/{b}/exports/8949.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "D,long,4 VTI,2024-01-05,2026-02-01,600.00,400.00,,,200.00,Brokerage" in csv.text
    txf = jane.get(f"/ui/api/tax-books/{b}/exports/moolakata.txf").text
    assert txf.startswith("V042\r\n") and "N323\r\n" in txf and "N321\r\n" in txf
    assert p["txfLeftOut"] == {
        "digital": 0,
        "collectable": 0,
        "personalUse": 0,
        "noLot": 0,
        "noBasis": 0,
    }
    pdf = jane.get(f"/ui/api/tax-books/{b}/exports/summary.pdf")
    assert pdf.content.startswith(b"%PDF-1.4") and pdf.content.rstrip().endswith(b"%%EOF")


def test_collectables_and_personal_use_losses(jane):
    coll = new_account(jane, name="Collectables", type="collectables")
    cars = new_account(jane, name="Cars", type="vehicle")
    coin = make(
        jane, "Item", accountId=coll["id"], name="Coin", acquiredOn="2020-01-01", costBasis="1000"
    ).json()
    car = make(
        jane,
        "Item",
        accountId=cars["id"],
        name="Car",
        acquiredOn="2022-01-01",
        costBasis="30000",
        personalUse=True,
    ).json()
    saved(sell(jane, coin["id"], "2026-05-01", "3000"))
    saved(sell(jane, car["id"], "2026-05-01", "18000"))
    book_id = book(jane)
    p = panels(jane, book_id)
    rows = {r["description"]: r for r in p["rows"]}
    assert rows["Coin"]["collectable"] and rows["Coin"]["box"] == "F"
    assert rows["Car"]["code"] == "L" and rows["Car"]["gain"] == "0.00"
    assert {rows["Coin"]["kind"], rows["Car"]["kind"]} == {"item"}
    assert p["scheduleD"]["collectables"] == "2000.00"
    # TXF has no field for C or L (S8.2): both are left out of it and counted beside it.
    assert p["txfLeftOut"] == {
        "digital": 0,
        "collectable": 1,
        "personalUse": 1,
        "noLot": 0,
        "noBasis": 0,
    }
    txf = jane.get(f"/ui/api/tax-books/{book_id}/exports/moolakata.txf").text
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
    rows += [row("A"), row("B"), row("E", "W")]
    rows[6].lotMissing = True  # no day bought to write
    rows[7].basis = rows[8].basis = None  # no basis to write, never a 0
    assert [exports.in_txf(r) for r in rows] == [True, True] + [False] * 7
    assert exports.txf_left_out(rows) == {
        "digital": 2,
        "collectable": 1,
        "personalUse": 1,
        "noLot": 1,
        "noBasis": 2,
    }
    assert "$0.00" not in exports.txf(rows, dt.date(2027, 1, 2))


def test_income_retirement_and_an_rmd(jane):
    bank = new_account(jane, name="Savings", type="savings", institution="Ally")
    add(jane, bank["id"], "120.50", "2026-06-30", kind="interest")
    brk = new_account(jane, name="Brokerage", type="brokerage", institution="Fidelity")
    add(
        jane,
        brk["id"],
        "300.00",
        "2026-03-15",
        kind="dividend",
        dividendType="qualified",
        symbol="VTI",
    )
    add(
        jane,
        brk["id"],
        "50.00",
        "2026-03-15",
        kind="dividend",
        dividendType="ordinary",
        symbol="VTI",
    )
    ira = new_account(jane, name="IRA", type="ira")
    add(jane, ira["id"], "265000.00", "2025-06-01", kind="deposit")
    add(jane, ira["id"], "9000.00", "2026-02-01", kind="deposit")
    p = panels(jane, book(jane))
    assert p["income"]["interest"] == [{"label": "Ally", "amount": "120.50"}]
    assert p["income"]["ordinary"] == "350.00" and p["income"]["qualified"] == "300.00"
    c = p["retirement"]["contributions"][0]
    assert c["contributed"] == "9000.00" and c["limit"] == "8600.00" and c["over"]
    rmd = p["retirement"]["rmds"][0]
    assert rmd["age"] == 75 and rmd["factor"] == 24.6
    assert rmd["due"] == "10772.36", "265,000 / 24.6"


def test_deductions_loans_and_issues(jane):
    card = new_account(jane, name="Card", type="credit-card")
    cats = {x["name"]: x["id"] for x in jane.get("/ui/api/categories").json()["items"]}
    add(jane, card["id"], "-240.00", "2026-04-02", payee="Clinic", categoryId=cats["Doctor"])
    home = new_account(jane, name="Mortgage", type="mortgage")
    saved(terms(jane, home["id"], principal="300000", startDate="2026-01-01", termMonths=360,
                rate="6"))  # fmt: skip
    saved(loan_payment(jane, home["id"], "2026-02-01", "1798.65"))
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2026-05-01", "sell", "3", "100", "MSFT")  # nothing to sell
    b = book(jane)
    p = panels(jane, b)
    tags = {d["label"]: d for d in p["deductions"]}
    assert tags["Medical and dental"]["total"] == "240.00"
    assert tags["Medical and dental"]["withReceipts"] == 0
    assert tags["Loan interest"]["total"] == "1500.00"
    assert p["loans"][0]["interest"] == "1500.00" and p["loans"][0]["form"] == "1098"
    kinds = {i["kind"] for i in p["issues"]}
    assert {"sale-without-lot", "sale-basis"} <= kinds
    # Sold without a lot: its day bought is missing as its basis is, never its sale's day;
    # the CSV leaves it blank and TXF leaves the row out, counted (S8.1, S8.2).
    (row,) = [r for r in p["rows"] if r["description"] == "3 MSFT"]
    assert (row["acquired"], row["basis"], row["lotMissing"], row["longTerm"]) == (
        None,
        None,
        True,
        False,
    )
    (issue,) = [i for i in p["issues"] if i["kind"] == "sale-basis"]
    assert issue["text"] == "Brokerage: the sale of 3 MSFT on May 1 has no basis or day bought"
    assert p["txfLeftOut"]["noLot"] == 1
    csv = jane.get(f"/ui/api/tax-books/{b}/exports/8949.csv").text
    assert "A,short,3 MSFT,,2026-05-01,300.00,,,,,Brokerage" in csv
    assert "P3 MSFT" not in jane.get(f"/ui/api/tax-books/{b}/exports/moolakata.txf").text


def test_an_ira_limit_holds_across_a_persons_accounts(jane):
    # S8.6: two IRAs of one person share one limit: each under it, both together over.
    one = new_account(jane, name="IRA at Fidelity", type="ira")
    two = new_account(jane, name="IRA at Vanguard", type="roth-ira")
    add(jane, one["id"], "5000.00", "2026-02-01", kind="deposit")
    add(jane, two["id"], "4000.00", "2026-03-01", kind="deposit")
    c = {x["account"]: x for x in panels(jane, book(jane))["retirement"]["contributions"]}
    first, second = c["IRA at Fidelity"], c["IRA at Vanguard"]
    assert first["personTotal"] == second["personTotal"] == "9000.00"
    assert first["over"] and second["over"], "9,000 against the person's 8,600 (with catch-up)"
    assert first["across"] == "IRAs"


def test_a_split_counts_toward_its_tag_as_a_whole_transaction_would(jane):
    # A split part takes its transaction's sign: $60 of a $100 pharmacy run is $60 of
    # medical, not $-60, and the rest counts nowhere.
    card = new_account(jane, name="Card", type="credit-card")
    cats = {x["name"]: x["id"] for x in jane.get("/ui/api/categories").json()["items"]}
    add(
        jane,
        card["id"],
        "-100.00",
        "2026-04-02",
        payee="Pharmacy",
        splits=[
            {"categoryId": cats["Doctor"], "amount": "-60.00"},
            {"categoryId": cats["Groceries"], "amount": "-40.00"},
        ],
    )
    p = panels(jane, book(jane))
    tags = {d["label"]: d for d in p["deductions"]}
    assert tags["Medical and dental"]["total"] == "60.00"


def test_a_replacement_covers_only_its_own_shares(jane):
    brk = new_account(jane, name="Brokerage", type="brokerage")
    ira = new_account(jane, name="IRA", type="ira")
    trade(jane, brk["id"], "2026-01-05", "buy", "12", "200", "AAPL")
    trade(jane, brk["id"], "2026-02-05", "buy", "3", "200", "AAPL")
    trade(jane, brk["id"], "2026-06-01", "sell", "15", "150", "AAPL")  # two lots, one sale
    trade(jane, ira["id"], "2026-06-10", "buy", "8", "150", "AAPL")
    p = panels(jane, book(jane))
    total = sum(float(w["disallowed"]) for w in p["washes"])
    assert total == 400.0, "8 of the 15 shares' 750 loss: 50 a share"


def test_shares_from_an_assigned_put_are_flagged_never_a_replacement(jane):
    # The loss isn't washed by shares an assignment bought; the preparer is asked to look.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "100000.00", "2026-01-02", kind="deposit")
    trade(jane, brk["id"], "2026-08-03", "buy", "100", "500", "MSFT")
    trade(jane, brk["id"], "2026-09-01", "sell", "100", "450", "MSFT")  # a 5,000 loss
    saved(option_trade(jane, brk["id"], "2026-08-20", "sell-to-open", "MSFT", "put", "455",
                       "2026-09-18", "1", "4.00"))  # fmt: skip
    held = jane.get("/ui/api/positions", params={"kind": "options"}).json()["open"][0]
    r = jane.post(
        f"/ui/api/accounts/{brk['id']}/options/{held['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-09-18", "contracts": "1"},
    )
    assert r.status_code == 201, r.text
    p = panels(jane, book(jane))
    [w] = p["washes"]
    assert w["review"] and w["disallowed"] == "0.00", w
    [loss] = [r for r in p["rows"] if r["description"] == "100 MSFT"]
    assert loss["code"] == "" and loss["gain"] == "-5000.00"


def test_a_fund_typed_by_its_symbol_is_a_fund_for_its_box(jane):
    # S2.1: a fund bought in 2011 has no reported basis (funds from 2012), so its
    # sale goes in box E; a share bought the same day, in D.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2011-06-01", "buy", "10", "50", symbol="FSKAX")
    trade(jane, brk["id"], "2011-06-01", "buy", "10", "50", symbol="IBM")
    trade(jane, brk["id"], "2026-03-02", "sell", "10", "60", symbol="FSKAX")
    trade(jane, brk["id"], "2026-03-02", "sell", "10", "60", symbol="IBM")
    rows = {r["description"]: r["box"] for r in panels(jane, book(jane))["rows"]}
    assert rows == {"10 FSKAX": "E", "10 IBM": "D"}


def test_average_cost_is_for_funds_a_share_goes_first_in(jane):
    # S2.3: in an account set to average cost, a fund's sale takes the average of
    # its shares and a listed share's the oldest lot.
    brk = new_account(jane, name="Brokerage", type="brokerage", lotMethod="average")
    for symbol in ("VTSAX", "IBM"):
        trade(jane, brk["id"], "2025-01-06", "buy", "10", "100", symbol=symbol)
        trade(jane, brk["id"], "2025-02-03", "buy", "10", "200", symbol=symbol)
        trade(jane, brk["id"], "2026-03-02", "sell", "10", "250", symbol=symbol)
    rows = {r["description"]: r["basis"] for r in panels(jane, book(jane))["rows"]}
    assert rows == {"10 VTSAX": "1500.00", "10 IBM": "1000.00"}


def test_a_replacement_bought_before_the_loss_sale_is_a_plain_lot_until_it(jane):
    # S3.8.3: highest cost first picks the sale's lots by their cost on the day; the
    # replacement bought nine days before takes the loss only once the sale has it.
    brk = new_account(jane, name="Brokerage", type="brokerage", lotMethod="hifo")
    trade(jane, brk["id"], "2023-08-21", "buy", "10", "366.93", symbol="HON")
    trade(jane, brk["id"], "2024-01-18", "buy", "10", "382.36", symbol="HON")
    trade(jane, brk["id"], "2025-02-21", "buy", "6", "312.57", symbol="HON")
    trade(jane, brk["id"], "2025-03-04", "sell", "6", "310.09", symbol="HON")
    me = jane.get("/ui/api/session").json()["user"]["id"]
    r = make(jane, "TaxBk", year=2025, filers=[me])
    (row,) = panels(jane, r.json()["id"])["rows"]
    assert (row["acquired"], row["basis"], row["adjustment"]) == ("2024-01-18", "2294.16", "433.62")


def test_shares_a_sale_sold_never_replace_it(jane):
    # S3.8.2: last in first out sells the three bought a week before with three of
    # the old lot; those three were sold, so they replace nothing.
    brk = new_account(jane, name="Brokerage", type="brokerage", lotMethod="lifo")
    trade(jane, brk["id"], "2024-01-08", "buy", "10", "200", symbol="IBM")
    trade(jane, brk["id"], "2026-02-23", "buy", "3", "100", symbol="IBM")
    trade(jane, brk["id"], "2026-03-02", "sell", "6", "90", symbol="IBM")
    rows = panels(jane, book(jane))["rows"]
    assert sorted((r["description"], r["adjustment"]) for r in rows) == [
        ("3 IBM", "0.00"),
        ("3 IBM", "0.00"),
    ]


def lots_on(c, account_id, day, sale_id=None):
    q = f"?date={day}" + (f"&saleId={sale_id}" if sale_id else "")
    r = c.get(f"/ui/api/accounts/{account_id}/lots{q}")
    assert r.status_code == 200, r.text
    return {(x["symbol"], x["acquiredOn"]): x for x in r.json()["items"]}


def test_a_sale_takes_the_lots_picked_and_keeps_them_through_an_edit(jane):
    # S2.3: specific identification is chosen per sale: the lots picked, the rest
    # first in; the picks are records of the sale, kept when it changes.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2024-01-08", "buy", "10", "100", symbol="IBM")
    trade(jane, brk["id"], "2025-06-02", "buy", "10", "300", symbol="IBM")
    held = lots_on(jane, brk["id"], "2026-03-02")
    newer = held[("IBM", "2025-06-02")]
    assert (newer["quantity"], newer["basis"], newer["longTerm"]) == ("10.0", "3000.00", False)
    r = make(jane, "Txn", accountId=brk["id"], date="2026-03-02", kind="sell", symbol="IBM",
             quantity="12", price="250", amount="3000.00",
             picks=[{"lotId": newer["lotId"], "quantity": "8"}])  # fmt: skip
    assert r.status_code == 200, r.text
    sale = jane.get(f"/ui/api/transactions/{r.json()['id']}").json()
    assert [(p["lotId"], p["quantity"]) for p in sale["picks"]] == [(newer["lotId"], "8.0")]

    def rows():
        return sorted((x["acquired"], x["description"], x["basis"])
                      for x in panels(jane, book(jane))["rows"])  # fmt: skip

    assert rows() == [("2024-01-08", "4 IBM", "400.00"), ("2025-06-02", "8 IBM", "2400.00")]
    from edits import change

    sale = saved(change(jane, "Txn", sale, memo="rebalance"))
    assert [
        p["quantity"] for p in jane.get(f"/ui/api/transactions/{sale['id']}").json()["picks"]
    ] == ["8.0"]
    # More than the sale, or than the lot held, is refused.
    pick = jane.get(f"/ui/api/transactions/{sale['id']}").json()["picks"][0]
    r = change(jane, "LotPk", {**pick, "saleId": sale["id"]}, quantity="11")
    assert r.status_code == 422 and "more than" in r.text.lower(), r.text


def test_a_pick_of_a_lot_a_wash_sale_split_takes_from_its_parts(jane):
    # L is bought 10 at $160, 4 of which replace an earlier loss sale; picking L for 10
    # takes all of L, never 6 of K.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2025-01-02", "buy", "10", "100", symbol="AAPL")  # K
    trade(jane, brk["id"], "2026-03-02", "buy", "4", "200", symbol="AAPL")  # M
    lot_m = lots_on(jane, brk["id"], "2026-03-20")[("AAPL", "2026-03-02")]
    sold = make(jane, "Txn", accountId=brk["id"], date="2026-03-20", kind="sell",
                symbol="AAPL", quantity="4", price="150", amount="600.00",
                picks=[{"lotId": lot_m["lotId"], "quantity": "4"}])  # fmt: skip
    assert sold.status_code == 200, sold.text
    trade(jane, brk["id"], "2026-04-01", "buy", "10", "160", symbol="AAPL")  # L
    held = lots_on(jane, brk["id"], "2026-05-01")
    lot_l = held[("AAPL", "2026-04-01")]
    assert (lot_l["quantity"], lot_l["basis"]) == ("10.0", "1800.00")  # 1600 + the 200 washed
    r = make(jane, "Txn", accountId=brk["id"], date="2026-05-01", kind="sell", symbol="AAPL",
             quantity="10", price="170", amount="1700.00",
             picks=[{"lotId": lot_l["lotId"], "quantity": "10"}])  # fmt: skip
    assert r.status_code == 200, r.text
    may = [x for x in panels(jane, book(jane))["rows"] if x["sold"] == "2026-05-01"]
    assert sorted((x["acquired"], x["description"]) for x in may) == [
        ("2026-04-01", "4 AAPL"),
        ("2026-04-01", "6 AAPL"),
    ]


def save_picks(c, *picks):
    """Lots picked for sales, each (saleId, lotId, quantity), in one save as the sale's draft
    sends them; the answer and each pick's id."""
    ids = [new_id("LotPk") for _ in picks]
    ops = [{"op": "create", "entity": "LotPk", "id": i,
            "fields": {"saleId": s, "lotId": lot, "quantity": q}}
           for i, (s, lot, q) in zip(ids, picks, strict=True)]  # fmt: skip
    return c.post("/ui/api/save", json={"ops": ops}), ids


def refusals(r):
    """A refused save's status and each refusal's field, code and words."""
    return r.status_code, [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def picks_of(c, sale_id):
    return c.get(f"/ui/api/transactions/{sale_id}").json()["picks"]


def test_lots_are_picked_for_a_live_sale_of_an_account_the_caller_writes(server, frozen):
    """S2.3, S10.3: a pick names a sale (a live sell of a holding) of an account the caller
    writes; one who only reads the sale's account picks for it and changes its picks in
    nothing, whatever lot they name."""
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    own = new_account(john, name="John's", type="brokerage")["id"]
    buy = add(jane, brk, "-1000.00", "2025-01-06", kind="buy", symbol="IBM", quantity="10",
              price="100")  # fmt: skip
    trade(john, own, "2025-01-06", "buy", "10", "100", symbol="IBM")
    sale = add(jane, brk, "500.00", "2026-03-02", kind="sell", symbol="IBM", quantity="5",
               price="100")["id"]  # fmt: skip
    gone = add(jane, brk, "200.00", "2026-03-09", kind="sell", symbol="IBM", quantity="2",
               price="100")  # fmt: skip
    saved(remove(jane, "Txn", gone))
    lot = lots_on(jane, brk, "2026-03-02")[("IBM", "2025-01-06")]["lotId"]
    unknown = [("saleId", "transaction-unknown", "No such transaction.")]
    assert refusals(save_picks(jane, (new_id("Txn"), lot, "1"))[0]) == (422, unknown)
    assert refusals(save_picks(jane, (gone["id"], lot, "1"))[0]) == (422, unknown)
    assert refusals(save_picks(jane, (buy["id"], lot, "1"))[0]) == (
        422,
        [("saleId", "pick-not-a-sale", "Lots are picked for a sale.")],
    )
    saved(save_picks(jane, (sale, lot, "1"))[0])
    (pick,) = picks_of(jane, sale)
    saved(share(jane, "account", brk, users={u["john"].id: "read"}))
    johns = lots_on(john, own, "2026-03-02")[("IBM", "2025-01-06")]["lotId"]
    for r in (save_picks(john, (sale, johns, "1"))[0], change(john, "LotPk", pick, quantity="2")):
        assert (r.status_code, r.json()["errors"][0]["code"]) == (403, "share-read-only"), r.text
    assert [p["quantity"] for p in picks_of(jane, sale)] == ["1.0"]
    saved(share(jane, "account", brk, users={u["john"].id: "write"}))
    saved(change(john, "LotPk", pick, quantity="2"))
    assert [p["quantity"] for p in picks_of(jane, sale)] == ["2.0"]


def test_a_pick_is_of_a_live_lot_of_the_sales_holding_and_more_than_none(jane):
    """S2.3: the lot picked is one of the sale's holding in the sale's account, refused on
    the lot; one unknown or typed over (S2.2) is not found; none or less is refused on the
    quantity."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    other = new_account(jane, name="Other", type="brokerage", mask="2222")["id"]
    trade(jane, brk, "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2025-01-06", "buy", "10", "100", symbol="VTI")
    trade(jane, other, "2025-01-06", "buy", "10", "100", symbol="IBM")
    moved = add(jane, brk, "0.00", "2025-02-03", kind="transfer-in", symbol="IBM", quantity="5")
    held = lots_on(jane, brk, "2026-03-02")
    typed_over = held[("IBM", "2025-02-03")]["lotId"]
    lots = [{"acquiredOn": "2024-05-01", "quantity": "5", "costBasis": "500"}]
    saved(edit(jane, "Txn", f"/ui/api/transactions/{moved['id']}", transferLots=lots))
    sale = add(jane, brk, "500.00", "2026-03-02", kind="sell", symbol="IBM", quantity="5",
               price="100")["id"]  # fmt: skip
    for lot in (new_id("Lot"), typed_over):
        r, _ = save_picks(jane, (sale, lot, "1"))
        assert refusals(r) == (404, [(None, "not-found", "Not found")]), lot
    for lot in (
        held[("VTI", "2025-01-06")]["lotId"],
        lots_on(jane, other, "2026-03-02")[("IBM", "2025-01-06")]["lotId"],
    ):
        assert refusals(save_picks(jane, (sale, lot, "1"))[0]) == (
            422,
            [("lotId", "lot-unknown", "Choose a lot of this holding.")],
        ), lot
    ibm = held[("IBM", "2025-01-06")]["lotId"]
    for none in ("0", "-1"):
        assert refusals(save_picks(jane, (sale, ibm, none))[0]) == (
            422,
            [("quantity", "quantity-invalid", "More than none.")],
        ), none
    assert saved(save_picks(jane, (sale, ibm, "1"))[0])["quantity"] == "1.0"


def test_the_lots_picked_come_to_no_more_than_the_sale_and_what_each_lot_held(jane):
    """S2.3: a sale's picks, live ones only, come to no more than its shares, and each to no
    more than its lot held on the sale's day (a lot bought later held none); each sale in one
    save is checked, its refusal named by the pick."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    trade(jane, brk, "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2025-06-02", "buy", "10", "300", symbol="IBM")
    sale = add(jane, brk, "1000.00", "2026-03-02", kind="sell", symbol="IBM", quantity="5",
               price="200")["id"]  # fmt: skip
    small = add(jane, brk, "400.00", "2026-03-09", kind="sell", symbol="IBM", quantity="2",
                price="200")["id"]  # fmt: skip
    trade(jane, brk, "2026-04-01", "buy", "10", "150", symbol="IBM")
    held = lots_on(jane, brk, "2026-04-01")
    older, newer = held[("IBM", "2025-01-06")]["lotId"], held[("IBM", "2025-06-02")]["lotId"]
    later = held[("IBM", "2026-04-01")]["lotId"]
    over = [("quantity", "picks-over", "The lots picked come to more than the sale.")]
    assert refusals(save_picks(jane, (sale, older, "6"))[0]) == (422, over)
    assert refusals(save_picks(jane, (sale, later, "1"))[0]) == (
        422,
        [("quantity", "pick-over", "More than the lot held that day.")],
    )
    r, ids = save_picks(jane, (sale, older, "5"), (small, newer, "3"))
    assert refusals(r) == (422, over)
    assert r.json()["errors"][0]["id"] == ids[1]
    # A pick taken away no longer counts toward the sale.
    saved(save_picks(jane, (sale, newer, "5"))[0])
    (gone,) = picks_of(jane, sale)
    saved(remove(jane, "LotPk", gone))
    saved(save_picks(jane, (sale, older, "5"))[0])
    assert [(p["lotId"], p["quantity"]) for p in picks_of(jane, sale)] == [(older, "5.0")]


def test_a_pick_keeps_its_sale_and_lot_and_one_taken_away_is_gone(jane):
    """S2.3: a pick changes only its quantity; one taken away is not found to change."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    trade(jane, brk, "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2025-06-02", "buy", "10", "300", symbol="IBM")
    sale = add(jane, brk, "1000.00", "2026-03-02", kind="sell", symbol="IBM", quantity="5",
               price="200")["id"]  # fmt: skip
    other = add(jane, brk, "400.00", "2026-03-09", kind="sell", symbol="IBM", quantity="2",
                price="200")["id"]  # fmt: skip
    held = lots_on(jane, brk, "2026-03-02")
    older, newer = held[("IBM", "2025-01-06")]["lotId"], held[("IBM", "2025-06-02")]["lotId"]
    saved(save_picks(jane, (sale, older, "2"))[0])
    (pick,) = picks_of(jane, sale)
    fixed = (422, [("lotId", "pick-fixed", "A pick keeps its sale and lot.")])
    assert refusals(change(jane, "LotPk", pick, lotId=newer)) == fixed
    assert refusals(change(jane, "LotPk", pick, saleId=other)) == fixed
    pick = saved(change(jane, "LotPk", pick, quantity="3"))
    assert [(p["lotId"], p["quantity"]) for p in picks_of(jane, sale)] == [(older, "3.0")]
    saved(remove(jane, "LotPk", pick))
    gone = {**pick, "version": pick["version"] + 1}
    assert refusals(change(jane, "LotPk", gone, quantity="4")) == (
        404,
        [(None, "not-found", "Not found")],
    )


def test_a_pick_works_the_wash_sales_out_again(jane):
    """S2.3, S3.8: picking the dear lot turns the sale's gain into a loss, and the shares
    bought back two weeks later make it a wash sale at once."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    trade(jane, brk, "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2025-06-02", "buy", "10", "300", symbol="IBM")
    sale = add(jane, brk, "2000.00", "2026-03-02", kind="sell", symbol="IBM", quantity="10",
               price="200")["id"]  # fmt: skip
    trade(jane, brk, "2026-03-16", "buy", "10", "190", symbol="IBM")
    b = book(jane)

    def rows():
        return [(x["acquired"], x["adjustment"]) for x in panels(jane, b)["rows"]]

    assert rows() == [("2025-01-06", "0.00")]
    dear = lots_on(jane, brk, "2026-03-02")[("IBM", "2025-06-02")]["lotId"]
    saved(save_picks(jane, (sale, dear, "10"))[0])
    assert rows() == [("2025-06-02", "1000.00")]


def test_fewer_shares_bought_back_replace_the_earliest_acquired(jane):
    # S3.8.2, Treas. Reg. §1.1091-1(c): highest cost first sells the $120 lot then
    # the $100 one, both at a loss; the ten bought back replace the earliest acquired.
    brk = new_account(jane, name="Brokerage", type="brokerage", lotMethod="hifo")
    trade(jane, brk["id"], "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk["id"], "2025-02-03", "buy", "10", "120", symbol="IBM")
    trade(jane, brk["id"], "2026-03-02", "sell", "20", "80", symbol="IBM")
    trade(jane, brk["id"], "2026-03-16", "buy", "10", "82", symbol="IBM")
    rows = panels(jane, book(jane))["rows"]
    assert sorted((r["acquired"], r["adjustment"]) for r in rows) == [
        ("2025-01-06", "200.00"),
        ("2025-02-03", "0.00"),
    ]


def test_a_reinvested_dividend_counts_as_a_dividend(jane):
    # S8.5: reinvested, a dividend is still one; ordinary unless typed qualified.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "-120.00", "2026-03-31", kind="reinvest", symbol="SCHD",
        quantity="1", price="120")  # fmt: skip
    add(jane, brk["id"], "-80.00", "2026-06-30", kind="reinvest", symbol="SCHD",
        quantity="1", price="80", dividendType="qualified")  # fmt: skip
    inc = panels(jane, book(jane))["income"]
    assert (inc["ordinary"], inc["qualified"]) == ("200.00", "80.00")


def test_a_book_lists_the_wash_sales_of_the_accounts_it_counts(jane):
    # S8.14.2: an account left out of the book takes its wash sales with it.
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2025-01-06", "buy", "10", "100", symbol="IBM")
    trade(jane, brk["id"], "2026-03-02", "sell", "10", "80", symbol="IBM")
    trade(jane, brk["id"], "2026-03-16", "buy", "10", "82", symbol="IBM")
    b = book(jane)
    assert len(panels(jane, b)["washes"]) == 1
    from edits import create

    saved(create(jane, "TxBkA", bookId=b, accountId=brk["id"], counted=False))
    p = panels(jane, b)
    assert p["rows"] == [] and p["washes"] == []


def test_a_roth_conversion_and_a_rollover_are_no_contributions(jane):
    """A matched transfer from a traditional IRA to a Roth IRA is a conversion, from a 401(k) to an
    IRA a rollover; neither counts against a limit nor as a distribution."""
    trad = new_account(jane, name="Traditional IRA", type="ira")
    roth = new_account(jane, name="Roth IRA", type="roth-ira")
    plan = new_account(jane, name="Old 401(k)", type="401k")
    out = add(jane, trad["id"], "-50000.00", "2026-03-02", kind="transfer", payee="Conversion")
    back = add(jane, roth["id"], "50000.00", "2026-03-02", kind="transfer", payee="Conversion")
    assert back["transferId"] == out["id"], "the two halves matched"
    out = add(jane, plan["id"], "-20000.00", "2026-05-04", kind="transfer", payee="Rollover")
    back = add(jane, trad["id"], "20000.00", "2026-05-04", kind="transfer", payee="Rollover")
    assert back["transferId"] == out["id"]
    add(jane, roth["id"], "3000.00", "2026-06-01", kind="deposit")
    r = panels(jane, book(jane))["retirement"]
    c = {x["account"]: x for x in r["contributions"]}
    assert c["Roth IRA"]["contributed"] == "3000.00" and not c["Roth IRA"]["over"]
    assert c["Traditional IRA"]["contributed"] == "0.00"
    assert [(m["fromAccount"], m["toAccount"], m["amount"]) for m in r["conversions"]] == [
        ("Traditional IRA", "Roth IRA", "50000.00")
    ]
    assert [(m["fromAccount"], m["toAccount"]) for m in r["rollovers"]] == [
        ("Old 401(k)", "Traditional IRA")
    ]
    assert r["distributions"] == []


def test_an_hsa_counts_its_employers_money_against_its_coverages_limit(server, frozen):
    """An HSA's limit is its coverage's, $1,000 more at 55; the employer's money counts against it
    beside the owner's."""
    from edits import edit

    make_user(server, "harry", born=1970)  # 56 in 2026
    c = sign_in(server, "harry")
    hsa = new_account(c, name="HSA", type="hsa")
    add(c, hsa["id"], "3000.00", "2026-02-01", kind="deposit", contributionSource="employer")
    add(c, hsa["id"], "2500.00", "2026-03-01", kind="deposit")
    b = book(c)
    [x] = panels(c, b)["retirement"]["contributions"]
    assert x["contributed"] == "5500.00" and x["limit"] == "9750.00", "family 8,750 + 1,000"
    assert "set the coverage" in x["note"]
    r = edit(c, "Acct", f"/ui/api/accounts/{hsa['id']}", hsaCoverage="self")
    assert r.status_code == 200, r.text
    [x] = panels(c, b)["retirement"]["contributions"]
    assert x["limit"] == "5400.00" and x["over"], "self-only 4,400 + 1,000, and 5,500 is over"


def test_foreign_tax_and_crypto_income_on_the_income_panel(jane):
    """Foreign tax a fund paid shows by payer; coins received as income count at their value when
    received, which is the basis of the lot they make."""
    brk = new_account(jane, name="Brokerage", type="brokerage", institution="Fidelity")
    add(jane, brk["id"], "180.00", "2026-06-30", kind="dividend", symbol="VXUS")
    add(jane, brk["id"], "-14.22", "2026-06-30", kind="foreign-tax", symbol="VXUS")
    ex = new_account(jane, name="Exchange", type="crypto-exchange", institution="Coinbase")
    add(jane, ex["id"], "0.00", "2026-04-01", kind="reward", symbol="ETH", quantity="0.01",
        price="2500")  # fmt: skip
    b = book(jane)
    inc = panels(jane, b)["income"]
    assert [(x["label"], x["amount"]) for x in inc["foreignTax"]] == [("Fidelity", "14.22")]
    assert [(x["label"], x["amount"]) for x in inc["cryptoIncome"]] == [("Exchange", "25.00")]
    lots = jane.get(f"/ui/api/accounts/{ex['id']}/holdings").json()["holdings"]
    assert [(h["symbol"], h["costBasis"]) for h in lots] == [("ETH", "25.00")]
    r = add(jane, ex["id"], "-5.00", "2026-04-02", kind="foreign-tax")
    assert r  # money out is the only sign it takes; a deposit's sign is refused below
    bad = make(jane, "Txn", accountId=brk["id"], date="2026-07-01", amount="5.00",
               kind="foreign-tax", symbol="VXUS")  # fmt: skip
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "amount-sign"


def _rows_8949(c, b):
    return [(r["description"], r["acquired"], r["basis"], r["longTerm"]) for r in
            panels(c, b)["rows"]]  # fmt: skip


def test_shares_moved_in_keep_the_days_they_were_bought(jane):
    """A transfer-in typed lot by lot keeps each lot's day bought and basis, so a sale soon after is
    long term for the old lot; one typed without lots has its day bought missing, its term unknown
    and the book says so."""
    fid = new_account(jane, name="Fidelity", type="brokerage")
    r = make(jane, "Txn", accountId=fid["id"], date="2026-01-10", kind="transfer-in",
             symbol="VTI", quantity="100", amount="0.00",
             transferLots=[{"acquiredOn": "2019-03-04", "quantity": "60", "costBasis": "9000"},
                           {"acquiredOn": "2025-11-20", "quantity": "40",
                            "costBasis": "11000"}])  # fmt: skip
    assert r.status_code == 200, r.text
    trade(jane, fid["id"], "2026-03-02", "sell", "100", "300")
    b = book(jane)
    rows = sorted(_rows_8949(jane, b), key=lambda x: x[1])
    assert [(x[1], x[2], x[3]) for x in rows] == [
        ("2019-03-04", "9000.00", True),
        ("2025-11-20", "11000.00", False),
    ]
    bad = make(jane, "Txn", accountId=fid["id"], date="2026-01-12", kind="transfer-in",
               symbol="KO", quantity="10", amount="0.00",
               transferLots=[{"acquiredOn": "2020-01-02", "quantity": "9"}])  # fmt: skip
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "lots-unbalanced"
    r = make(jane, "Txn", accountId=fid["id"], date="2026-02-01", kind="transfer-in",
             symbol="KO", quantity="10", amount="0.00")  # fmt: skip
    assert r.status_code == 200, r.text
    [ko] = [h for h in jane.get(f"/ui/api/accounts/{fid['id']}/holdings").json()["holdings"]
            if h["symbol"] == "KO"]  # fmt: skip
    assert ko["lots"][0]["acquiredMissing"] and ko["lots"][0]["longTerm"] is None
    kinds = [i["kind"] for i in panels(jane, b)["issues"]]
    assert "acquired-missing" in kinds
    # Its quantity and day corrected: the lot still missing its day bought follows them.
    t = saved(change(jane, "Txn", r.json(), quantity="12", date="2026-02-03"))

    def lots_():
        held = jane.get(f"/ui/api/accounts/{fid['id']}/holdings").json()["holdings"]
        return next(h for h in held if h["symbol"] == "KO")["lots"]

    assert [(x["quantity"], x["acquiredOn"], x["acquiredMissing"]) for x in lots_()] == [
        ("12.0", "2026-02-03", True)
    ]
    # Then its lots typed: each keeps the day it was bought, and the day missing is gone.
    saved(change(jane, "Txn", t, transferLots=[
        {"acquiredOn": "2020-01-02", "quantity": "5", "costBasis": "250"},
        {"acquiredOn": "2021-06-01", "quantity": "7", "costBasis": "420"},
    ]))  # fmt: skip
    assert [(x["quantity"], x["acquiredOn"], x["acquiredMissing"]) for x in lots_()] == [
        ("5.0", "2020-01-02", False), ("7.0", "2021-06-01", False)
    ]  # fmt: skip
    assert "acquired-missing" not in [i["kind"] for i in panels(jane, b)["issues"]]


def test_shares_moved_between_two_accounts_carry_their_lots(jane):
    """A transfer out and in of the same shares between two of the owner's accounts is offered as a
    pair; matched, the shares arrive with the lots they left with."""
    schwab = new_account(jane, name="Schwab", type="brokerage")
    fid = new_account(jane, name="Fidelity", type="brokerage")
    add(jane, schwab["id"], "15000.00", "2019-01-02", kind="deposit")
    trade(jane, schwab["id"], "2019-03-04", "buy", "100", "150")
    add(jane, schwab["id"], "0.00", "2026-01-09", kind="transfer-out", symbol="VTI",
        quantity="100")  # fmt: skip
    add(jane, fid["id"], "0.00", "2026-01-10", kind="transfer-in", symbol="VTI",
        quantity="100")  # fmt: skip
    pairs = jane.get("/ui/api/transfers/bitcoin").json()["items"]
    assert [(p["symbol"], p["fromAccount"], p["toAccount"]) for p in pairs] == [
        ("VTI", "Schwab", "Fidelity")
    ]
    r = jane.post(f"/ui/api/transfers/bitcoin/{pairs[0]['id']}", json={"confirm": True},
                   headers={"If-Match": f'"{pairs[0]["version"]}"'})  # fmt: skip
    assert r.status_code == 200, r.text
    [vti] = jane.get(f"/ui/api/accounts/{fid['id']}/holdings").json()["holdings"]
    assert [(x["acquiredOn"], x["basis"], x["longTerm"]) for x in vti["lots"]] == [
        ("2019-03-04", "15000.00", True)
    ]


def test_a_sale_of_shares_moved_in_without_their_day_bought_says_so(jane):
    """S2.2: shares moved in with their basis but not the day they were bought, two sold: Positions
    shows the sale's term unknown, its Form 8949 date is VARIOUS, and Taxes lists the sale until the
    day is typed."""
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "0.00", "2026-01-12", kind="transfer-in", symbol="VTI", quantity="5",
        costBasis="400")  # fmt: skip
    trade(jane, brk["id"], "2026-03-02", "sell", "2", "120")
    closed = jane.get("/ui/api/positions").json()["closed"]
    assert [(x["symbol"], x["term"]) for x in closed] == [("VTI", "unknown")]
    p = panels(jane, book(jane))
    (row,) = [r for r in p["rows"] if r["description"] == "2 VTI"]
    assert row["acquired"] is None and row["basis"] == "160.00"
    (issue,) = [i for i in p["issues"] if i["kind"] == "sale-acquired-missing"]
    assert issue["text"] == (
        "Brokerage: the sale of 2 VTI on Mar 2 is of shares moved in: when they were bought, "
        "for its term"
    )
    assert issue["link"] == f"/ui/accounts/{brk['id']}/holdings"


def test_a_funds_distributions_and_return_of_capital_reach_the_return(jane):
    """S2.4, S8.3: a capital-gain distribution is income on its own line; a return of capital
    comes off the basis, and what passes the basis is a gain on Form 8949, its term the lot's;
    Positions holds the lot at what is left of its basis."""
    brk = new_account(jane, name="Brokerage", type="brokerage")
    trade(jane, brk["id"], "2026-01-05", "buy", "10", "100")
    add(jane, brk["id"], "50.00", "2026-06-01", kind="capital-gain", symbol="VTI")
    add(jane, brk["id"], "1200.00", "2026-07-01", kind="return-of-capital", symbol="VTI")
    p = panels(jane, book(jane))
    inc = p["income"]
    assert inc["capitalGainDistributions"] == "50.00" and inc["returnOfCapital"] == "1200.00"
    (row,) = [r for r in p["rows"] if r["description"] == "VTI return of capital over basis"]
    # Its own kind: the Property panel lists only items sold, never this.
    assert row["kind"] == "return-of-capital"
    assert (row["acquired"], row["sold"], row["gain"], row["longTerm"]) == (
        "2026-01-05",
        "2026-07-01",
        "200.00",
        False,
    )
    [vti] = [x for x in jane.get("/ui/api/positions").json()["open"] if x["symbol"] == "VTI"]
    assert (vti["quantity"], vti["cost"]) == (10, 0)


def test_the_lots_a_sale_may_pick_are_those_held_on_its_day(jane):
    """S2.3: a sale picks from the lots open on its day, a trade of that day among them, each
    however few its shares, a basis missing shown missing; an option bought is a contract,
    not a lot to pick (S3.2)."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    add(jane, brk, "0.00", "2026-01-05", kind="transfer-in", symbol="KO", quantity="0.5")
    trade(jane, brk, "2026-03-02", "buy", "1", "250", symbol="IBM")
    r = option_trade(jane, brk, "2026-03-02", "buy-to-open", "IBM", "call", 300, "2026-12-18",
                     1, "5.00")  # fmt: skip
    assert r.status_code == 200, r.text
    held = lots_on(jane, brk, "2026-03-02")
    assert {k: (x["quantity"], x["basis"]) for k, x in held.items()} == {
        ("IBM", "2026-03-02"): ("1.0", "250.00"),
        ("KO", "2026-01-05"): ("0.5", None),
    }


def test_a_later_sale_picks_from_what_an_earlier_ones_picks_left(jane):
    """S2.3: the lots an earlier sale picked are gone from those a later one picks from, never
    the first in instead."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    trade(jane, brk, "2024-01-08", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2025-06-02", "buy", "10", "300", symbol="IBM")
    newer = lots_on(jane, brk, "2026-03-02")[("IBM", "2025-06-02")]
    r = make(jane, "Txn", accountId=brk, date="2026-03-02", kind="sell", symbol="IBM",
             quantity="4", price="250", amount="1000.00",
             picks=[{"lotId": newer["lotId"], "quantity": "4"}])  # fmt: skip
    assert r.status_code == 200, r.text
    held = lots_on(jane, brk, "2026-04-01")
    assert {k[1]: x["quantity"] for k, x in held.items()} == {
        "2024-01-08": "10.0",
        "2025-06-02": "6.0",
    }


def test_a_replacements_lot_takes_its_wash_sales_loss_from_the_loss_sales_day(jane):
    """S3.8, S2.3: a replacement's lot is offered with the loss its wash sale adds only from
    the loss sale's day on, whichever of the owner's accounts sold; the lots a sale picks from
    leave out its own wash sale."""
    brk = new_account(jane, name="Brokerage", type="brokerage")["id"]
    other = new_account(jane, name="Other", type="brokerage", mask="2222")["id"]
    trade(jane, brk, "2026-01-05", "buy", "10", "100", symbol="IBM")
    trade(jane, brk, "2026-03-02", "buy", "10", "50", symbol="IBM")
    trade(jane, other, "2026-01-05", "buy", "10", "100", symbol="KO")
    trade(jane, brk, "2026-03-02", "buy", "10", "50", symbol="KO")
    trade(jane, other, "2026-03-10", "sell", "10", "50", symbol="KO")
    sale = make(jane, "Txn", accountId=brk, date="2026-03-10", kind="sell", symbol="IBM",
                quantity="10", price="50", amount="500.00")  # fmt: skip
    assert sale.status_code == 200, sale.text

    def bases(day, sale_id=None):
        return {k: x["basis"] for k, x in lots_on(jane, brk, day, sale_id).items()}

    first, replaced = ("IBM", "2026-01-05"), ("IBM", "2026-03-02")
    ko = ("KO", "2026-03-02")
    assert bases("2026-03-09") == {first: "1000.00", replaced: "500.00", ko: "500.00"}
    assert bases("2026-03-10", sale.json()["id"]) == {
        first: "1000.00",
        replaced: "500.00",
        ko: "1000.00",
    }
    assert bases("2026-03-10") == {replaced: "1000.00", ko: "1000.00"}
