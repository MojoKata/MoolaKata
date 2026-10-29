"""The tax panels and exports (requirements S8.1–S8.13): Form 8949 with wash sales and
collectables, income, retirement with RMDs, deductions, loans, the issues, and the CSV, TXF and
PDF exports."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import loan_payment, saved, sell, terms
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
    r = c.post("/ui/api/tax-books", json={"year": 2026, "filers": [me]})
    assert r.status_code == 201, r.text
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
    assert w["replacementAccount"] == "IRA" and w["adjustedBasis"] == "1000.00"
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
    coin = alice.post(
        f"/ui/api/accounts/{coll['id']}/items",
        json={"name": "Coin", "acquiredOn": "2020-01-01", "costBasis": "1000"},
    ).json()
    car = alice.post(
        f"/ui/api/accounts/{cars['id']}/items",
        json={"name": "Car", "acquiredOn": "2022-01-01", "costBasis": "30000", "personalUse": True},
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
    put = {
        "action": "sell-to-open",
        "underlying": "MSFT",
        "right": "put",
        "strike": "455",
        "expiry": "2026-09-18",
        "contracts": "1",
        "premium": "4.00",
        "fees": "0",
    }
    r = alice.post(f"/ui/api/accounts/{brk['id']}/options", json={**put, "date": "2026-08-20"})
    assert r.status_code == 201, r.text
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
