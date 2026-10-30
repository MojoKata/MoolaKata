"""Brokerage and plan statements (requirements S1.3.3.8): the summary, the positions and the
cash activity, as Schwab, Fidelity and Empower lay them out; trades are not read."""

import datetime as dt
from decimal import Decimal

from edits import make

from moolakata.importers import brokerage

TODAY = dt.date(2026, 10, 13)

SCHWAB = """Charles Schwab & Co., Inc.
Schwab One Account of ALICE GRIFFIN  Account Number 8812-4417
Statement Period: September 1-30, 2026
Change in Account Value This Period Year to Date
Starting Value $241,380.12 $230,004.11
Deposits 1,500.00 9,000.00
Withdrawals 0.00 (2,000.00)
Dividends and Interest 412.87 3,104.55
Change in Value of Investments 3,257.66 6,442.00
Ending Value $246,550.65 $246,550.65
Positions - Equities
Symbol Description Quantity Price Market Value Cost Basis
AAPL APPLE INC 150.0000 254.74 38,210.50 26,104.00
Positions - Exchange Traded Funds
VTI VANGUARD TOTAL STOCK MARKET ETF 412.0000 303.74 125,140.88 98,410.00
SCHD SCHWAB US DIVIDEND EQUITY ETF
603.2140 28.72 17,322.11 15,901.22
Total Exchange Traded Funds 142,462.99
Cash and Cash Investments
SWVXX SCHWAB VALUE ADVANTAGE MONEY INV 6,214.33 1.00 6,214.33
Transaction Detail
Date Category Action Symbol Description Quantity Price Amount
09/12 Buy AAPL APPLE INC 10.0000 238.91 (2,389.10)
09/15 Deposit MoneyLink Transfer from Joint Household 1,500.00
09/24 Dividend SCHD SCHWAB US DIVIDEND EQUITY ETF 87.42
09/24 Reinvest Shares SCHD SCHWAB US DIVIDEND EQUITY ETF 5.1120 17.10 (87.42)
09/30 Interest Bank Interest SWVXX 6.18
Disclosures
"""

FIDELITY = """Fidelity Investments
INDIVIDUAL Account Number X12-345678
Statement Period: 09/01/2026 - 09/30/2026
Account Summary
Beginning Account Value $50,120.00
Additions 500.00
Subtractions (250.00)
Dividends, Interest & Other Income 31.40
Change in Investment Value 410.60
Ending Account Value $50,812.00
Holdings
Description Quantity Price Value
FXAIX FIDELITY 500 INDEX FUND 210.000 230.00 48,300.00
SPAXX FIDELITY GOVERNMENT MONEY MARKET 2,512.00 1.00 2,512.00
Activity
09/02 Contribution Electronic Funds Transfer Received 500.00
09/16 Withdrawal Check Paid 250.00
09/30 Dividend Received FXAIX 31.40
"""

EMPOWER = """Empower Retirement
Acme Corp 401(k) Plan  Account ending 0099
Statement Period: 07/01/2026 - 09/30/2026
Your Account Summary
Beginning Balance $88,000.00
Contributions 4,500.00
Change in Value 1,210.55
Ending Balance $93,710.55
Your Investments
Fund Units Price Balance
Vanguard Target Retirement 2045 Trust
1,012.4410 54.12 54,793.31
Stable Value Fund
3,891.7240 10.00 38,917.24
"""


def test_a_schwab_statement_reads_its_three_parts():
    b = brokerage.parse(SCHWAB.splitlines(), TODAY)
    s = b.summary
    assert (s.starting, s.ending, s.deposits, s.income, s.change) == (
        Decimal("241380.12"),
        Decimal("246550.65"),
        Decimal("1500.00"),
        Decimal("412.87"),
        Decimal("3257.66"),
    )
    assert (b.periodStart, b.periodEnd) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert [(p.symbol, p.quantity, p.value, p.cash) for p in b.positions] == [
        ("AAPL", Decimal("150.0000"), Decimal("38210.50"), False),
        ("VTI", Decimal("412.0000"), Decimal("125140.88"), False),
        ("SCHD", Decimal("603.2140"), Decimal("17322.11"), False),
        ("SWVXX", Decimal("6214.33"), Decimal("6214.33"), True),
    ]
    assert b.positions[0].cost == Decimal("26104.00")
    assert b.positions[2].label.startswith("SCHD SCHWAB US DIVIDEND"), "two lines read as one"
    kinds = [(a.kind, a.notRead, a.amount) for a in b.activity]
    assert kinds == [
        ("trade", True, Decimal("-2389.10")),
        ("deposit", False, Decimal("1500.00")),
        ("dividend", False, Decimal("87.42")),
        ("trade", True, Decimal("-87.42")),
        ("interest", False, Decimal("6.18")),
    ]
    buy = b.activity[0]
    assert (buy.symbol, buy.quantity, buy.price) == ("AAPL", Decimal("10.0000"), Decimal("238.91"))
    assert brokerage.totals(b)["income"] == Decimal("93.60")


def test_a_fidelity_statement_and_its_core_position():
    b = brokerage.parse(FIDELITY.splitlines(), TODAY)
    assert (b.summary.starting, b.summary.ending, b.summary.withdrawals) == (
        Decimal("50120.00"),
        Decimal("50812.00"),
        Decimal("-250.00"),
    )
    assert [(p.symbol, p.cash) for p in b.positions] == [("FXAIX", False), ("SPAXX", True)]
    assert [(a.kind, a.amount) for a in b.activity] == [
        ("deposit", Decimal("500.00")),
        ("withdrawal", Decimal("-250.00")),
        ("dividend", Decimal("31.40")),
    ]
    t = brokerage.totals(b)
    assert (t["deposits"], t["withdrawals"], t["income"]) == (
        Decimal("500.00"),
        Decimal("-250.00"),
        Decimal("31.40"),
    )


def test_an_empower_plan_statement_names_its_funds():
    b = brokerage.parse(EMPOWER.splitlines(), TODAY)
    assert b.summary.ending == Decimal("93710.55")
    assert b.summary.deposits == Decimal("4500.00"), "contributions"
    assert [(p.label, p.symbol, p.quantity) for p in b.positions] == [
        ("Vanguard Target Retirement 2045 Trust", None, Decimal("1012.4410")),
        ("Stable Value Fund", None, Decimal("3891.7240")),
    ]
    assert b.read


def test_a_line_asked_to_be_ignored_is_shown_ignored_next_time():
    """CR3-16: only what the person asks (Remember…); the line is shown, marked, not dropped."""
    layout = brokerage.learn(None, ["Withdrawal Check"])
    again = brokerage.parse(FIDELITY.splitlines(), TODAY, layout)
    assert [(a.kind, a.ignored) for a in again.activity] == [
        ("deposit", None),
        ("withdrawal", "withdrawal check"),
        ("dividend", None),
    ]
    assert brokerage.learn(layout, forget=["withdrawal check"])["brokerage"]["skip"] == []


def test_a_brokerage_statement_is_checked_and_saved(server):
    from conftest import make_user, sign_in
    from test_accounts import add, new_account
    from test_reading import text_pdf
    from test_statements import _import

    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, name="Individual Brokerage", type="brokerage", institution="Schwab")
    # What MoolaKata holds: SCHD short by the reinvestment, the dividend and deposit present.
    for sym, qty, price, day in (
        ("AAPL", "140", "180.00", "2026-01-05"),
        ("VTI", "412", "240.00", "2026-01-05"),
        ("SCHD", "598.1020", "26.00", "2026-01-05"),
    ):
        r = make(
            c,
            "Txn",
            accountId=a["id"],
            date=day,
            kind="buy",
            symbol=sym,
            quantity=qty,
            price=price,
            amount=str((-Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))),
        )
        assert r.status_code == 200, r.text
    add(c, a["id"], "1500.00", day="2026-09-15", payee="MoneyLink Transfer from Joint Household")
    review = _import(c, a["id"], text_pdf(SCHWAB.splitlines()))["result"]
    assert review["kind"] == "brokerage"
    assert review["summary"]["ending"] == "246550.65"
    pos = {p["symbol"]: p for p in review["positions"]}
    assert pos["VTI"]["difference"] == "0.0000"
    assert pos["AAPL"]["difference"] == "10.0000", "the buy on the 12th isn't entered yet"
    assert pos["SCHD"]["difference"] == "5.1120"
    assert pos["SCHD"]["hint"] == "the Sep 24 reinvestment of 5.1120 isn't entered yet"
    assert pos["AAPL"]["hint"] == "the Sep 12 purchase of 10.0000 isn't entered yet"
    acts = review["activity"]
    assert [x["present"] for x in acts if x["kind"] == "deposit"] == [True]
    trade = next(x for x in acts if x["notRead"])
    assert (trade["symbol"], trade["quantity"], trade["price"]) == ("AAPL", "10.0000", "238.91")
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "endingValue": review["summary"]["ending"],
        "positions": [
            {k: p[k] for k in ("label", "symbol", "instrumentId", "quantity", "price", "cash")}
            | {"marketValue": p["marketValue"], "costBasis": p["costBasis"]}
            for p in review["positions"]
        ],
        "rows": [
            {
                "date": x["date"],
                "description": x["description"],
                "amount": x["amount"],
                "kind": x["kind"],
                "symbol": x["symbol"],
                "include": not x["present"] and not x["notRead"],
            }
            for x in acts
        ],
    }
    url = f"/ui/api/imports/{review['uploadId']}/brokerage"
    bad = {**body, "rows": [{**body["rows"][0], "include": True}]}
    assert c.post(url, json=bad).json()["code"] == "row-not-cash"
    r = c.post(url, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["added"] == 2, "the dividend and the interest"
    rec = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()
    assert [v["reported"] for v in rec["valueChecks"]] == [246550.65]
    checks = {h["label"].split()[0]: h for h in rec["holdingChecks"]}
    assert checks["SCHD"]["difference"] == 5.112
    assert checks["SWVXX"]["cash"]


def test_a_plan_kept_by_snapshots_takes_the_positions_as_its_holdings(server):
    from conftest import make_user, sign_in
    from test_accounts import new_account
    from test_reading import text_pdf
    from test_statements import _import

    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, name="Acme 401(k)", type="401k", institution="Empower")
    review = _import(c, a["id"], text_pdf(EMPOWER.splitlines()))["result"]
    assert review["kind"] == "brokerage" and review["snapshot"]
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "endingValue": review["summary"]["ending"],
        "positions": [
            {
                "label": p["label"],
                "quantity": p["quantity"],
                "price": p["price"],
                "marketValue": p["marketValue"],
            }
            for p in review["positions"]
        ],
        "rows": [],
    }
    r = c.post(f"/ui/api/imports/{review['uploadId']}/brokerage", json=body)
    assert r.status_code == 200, r.text
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()
    assert sorted(x["quantity"] for x in h["holdings"]) == [1012.441, 3891.724]
    rec = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()
    assert all(x["ok"] for x in rec["holdingChecks"])
    # Item 14: the same statement again, its ending value corrected: nothing added twice, the
    # value replaced; and a line asked to be ignored is listed in Profile, and taken back.
    from moolakata.store.entities.accounts import Anchor, HoldingCheck

    again = _import(c, a["id"], text_pdf(EMPOWER.splitlines()))["result"]
    body["endingValue"] = "1.00"
    body["remember"] = ["Employer Match"]
    r = c.post(f"/ui/api/imports/{again['uploadId']}/brokerage", json=body)
    assert r.status_code == 200, r.text
    with server.db.read() as s:
        values = s.query(Anchor).filter_by(accountId=a["id"], source="statement-value").all()
        assert [str(x.balance) for x in values if not x.deleted] == ["1.00"]
        assert s.query(HoldingCheck).filter_by(accountId=a["id"], deleted=False).count() == len(
            review["positions"]
        )
    listed = c.get("/ui/api/statement-layouts/ignored").json()["items"]
    assert listed == [{"institution": "Empower", "kind": "brokerage", "start": "employer match"}]
    assert c.post("/ui/api/statement-layouts/ignored/forget", json=listed[0]).status_code == 204
    assert c.get("/ui/api/statement-layouts/ignored").json()["items"] == []
